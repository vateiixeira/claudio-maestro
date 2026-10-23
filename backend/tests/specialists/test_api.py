"""API of the agents (specialists): CRUD, files, runs, notices, events and the app wiring.
Uses the scripted fake agent; the real SDK is never touched."""

import json
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_groups_api import without_header
from test_sessions_api import make_project

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, text_turn
from claudio_maestro.app import create_app
from claudio_maestro.specialists import store
from claudio_maestro.specialists.service import SpecialistService

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
SECRET = "SEGREDO-QUE-NAO-PODE-VAZAR"
MISSING_SESSION = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def factory() -> FakeAgentFactory:
    scripted: FakeAgentFactory = FakeAgentFactory(
        script=lambda content: text_turn(scripted.clients[-1].options.session_id, "feito")
    )
    return scripted


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every event published on the hub, from the routes and from the service alike."""
    published: list[dict[str, Any]] = []
    monkeypatch.setattr("claudio_maestro.events.EventHub.publish", lambda self, e: published.append(e))
    return published


@pytest.fixture
def api(factory: FakeAgentFactory, events):
    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    app = create_app(agent_factory=factory, history_exists=history_exists)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as c:
        yield c


def wait_for(check: Callable[[], Any], timeout: float = 3.0) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("a condição não foi atendida a tempo")
        time.sleep(0.01)


def conn_of(api: TestClient):
    return closing(db.connect(api.app.state.settings.db_path))


def agents_dir(api: TestClient) -> Path:
    return api.app.state.settings.data_dir / "specialists"


def create_agent(api: TestClient, project_id: int, slug: str = "revisor", name: str = "Revisor"):
    response = api.post(
        "/api/specialists", json={"name": name, "slug": slug, "project_id": project_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def project(api: TestClient, home: Path) -> dict[str, Any]:
    return make_project(api, home)


@pytest.fixture
def agent(api: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return create_agent(api, project["id"])


# Create and list ----------------------------------------------------------------


def test_create_returns_the_agent_and_writes_its_folder(api, project):
    agent = create_agent(api, project["id"], "revisor-de-pr", "  Revisor de PR ")

    assert agent["slug"] == "revisor-de-pr"
    assert agent["name"] == "Revisor de PR"
    assert agent["project_id"] == project["id"]
    assert agent["extra_project_ids"] == []
    assert agent["autonomy"] == "ask"
    assert agent["close_by_check"] is True
    assert agent["enabled"] is True
    assert agent["model"] is None and agent["effort"] is None
    assert agent["schedules"] == []
    assert agent["last_run"] is None
    assert agent["open_sessions"] == 0
    assert agent["last_mcp"] == []
    assert agent["description"]
    folder = agents_dir(api) / "revisor-de-pr"
    assert (folder / "SKILL.md").is_file()
    assert api.get("/api/specialists").json() == [agent]


def test_list_is_empty_at_first(api):
    assert api.get("/api/specialists").json() == []


@pytest.mark.parametrize(
    "slug",
    ["../fora", "a/b", "A", "a b", "a_b", "", "-a", "a-", "a--b", "x" * 41, "a.b", "..", "a\n"],
)
def test_create_refuses_a_bad_slug_and_touches_no_disk(api, project, slug):
    response = api.post(
        "/api/specialists", json={"name": "X", "slug": slug, "project_id": project["id"]}
    )
    assert response.status_code == 422
    assert api.get("/api/specialists").json() == []
    root = agents_dir(api)
    assert not root.exists() or list(root.iterdir()) == []
    # Nothing was written outside the agents folder either.
    assert not (root.parent / "fora").exists()
    assert not (root.parent.parent / "fora").exists()


def test_create_accepts_the_longest_slug(api, project):
    create_agent(api, project["id"], "a" + "b" * 39)


def test_create_refuses_a_blank_name_and_missing_fields(api, project):
    blank = api.post(
        "/api/specialists", json={"name": "   ", "slug": "ok", "project_id": project["id"]}
    )
    assert blank.status_code == 422
    assert api.post("/api/specialists", json={"slug": "ok", "project_id": project["id"]}).status_code == 422
    extra = api.post(
        "/api/specialists",
        json={"name": "A", "slug": "ok", "project_id": project["id"], "enabled": False},
    )
    assert extra.status_code == 422
    assert api.get("/api/specialists").json() == []


def test_create_with_an_unknown_project_is_404(api):
    response = api.post("/api/specialists", json={"name": "A", "slug": "ok", "project_id": 999})
    assert response.status_code == 404
    assert api.get("/api/specialists").json() == []
    assert not (agents_dir(api) / "ok").exists()


def test_create_with_a_repeated_slug_is_409(api, project, agent):
    response = api.post(
        "/api/specialists", json={"name": "Outro", "slug": "revisor", "project_id": project["id"]}
    )
    assert response.status_code == 409
    assert "revisor" in response.json()["detail"]
    assert len(api.get("/api/specialists").json()) == 1


def test_create_with_a_leftover_folder_is_409_and_leaves_no_row(api, project):
    (agents_dir(api) / "sobra").mkdir(parents=True)
    response = api.post(
        "/api/specialists", json={"name": "A", "slug": "sobra", "project_id": project["id"]}
    )
    assert response.status_code == 409
    assert api.get("/api/specialists").json() == []


def test_create_failing_on_disk_rolls_the_row_back(api, project, monkeypatch):
    def broken(self, slug, name):
        raise OSError("disco cheio")

    monkeypatch.setattr("claudio_maestro.specialists.files.SpecialistFiles.create", broken)
    with pytest.raises(OSError):
        api.post("/api/specialists", json={"name": "A", "slug": "ok", "project_id": project["id"]})
    assert api.get("/api/specialists").json() == []


# Edit -----------------------------------------------------------------------------


def patch(api: TestClient, agent_id: int, **body: Any):
    return api.patch(f"/api/specialists/{agent_id}", json=body)


def test_patch_updates_the_configuration(api, agent):
    response = patch(
        api,
        agent["id"],
        name="Novo nome",
        autonomy="full",
        outward_patterns=["terraform apply", " kubectl apply "],
        always_ask_patterns=["rm -rf"],
        close_by_check=False,
        model="haiku",
        effort="low",
        run_text="Rode agora",
        enabled=False,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Novo nome"
    assert body["autonomy"] == "full"
    assert body["outward_patterns"] == ["terraform apply", "kubectl apply"]
    assert body["always_ask_patterns"] == ["rm -rf"]
    assert body["close_by_check"] is False
    assert body["model"] == "haiku" and body["effort"] == "low"
    assert body["run_text"] == "Rode agora"
    assert body["enabled"] is False
    assert body["slug"] == "revisor"
    assert api.get("/api/specialists").json() == [body]


def test_patch_can_reset_model_and_effort_to_null(api, agent):
    patch(api, agent["id"], model="haiku", effort="high")
    body = patch(api, agent["id"], model=None, effort=None).json()
    assert body["model"] is None and body["effort"] is None


def test_patch_without_fields_changes_nothing(api, agent):
    response = api.patch(f"/api/specialists/{agent['id']}", json={})
    assert response.status_code == 200
    assert response.json() == agent


@pytest.mark.parametrize(
    "body",
    [
        {"autonomy": "tudo"},
        {"effort": "enorme"},
        {"model": "tem espaço"},
        {"name": "   "},
        {"name": None},
        {"enabled": None},
        {"run_text": ""},
        {"outward_patterns": [""]},
        {"outward_patterns": ["x"] * 101},
        {"slug": "outro"},
        {"unknown": 1},
        {"extra_project_ids": ["a"]},
    ],
)
def test_patch_refuses_invalid_fields(api, agent, body):
    response = api.patch(f"/api/specialists/{agent['id']}", json=body)
    assert response.status_code == 422
    assert api.get("/api/specialists").json() == [agent]


PATTERN_TEXT = (
    "Os padrões aceitam só letras, números, espaço e os sinais - _ . / :, "
    "com até 100 caracteres cada."
)


@pytest.mark.parametrize("field", ["outward_patterns", "always_ask_patterns"])
@pytest.mark.parametrize(
    "pattern",
    ["rm -rf *", "echo $(x)", 'git push "x"', "git push 'x'", "a; b", "a | b", "a && b",
     "a`b`", "x" * 101, "deploy\tprod", "a\nb"],
)
def test_patch_refuses_patterns_with_other_characters_or_too_long(api, agent, field, pattern):
    response = api.patch(f"/api/specialists/{agent['id']}", json={field: ["ok", pattern]})

    assert response.status_code == 422
    assert response.json()["detail"] == PATTERN_TEXT
    assert api.get("/api/specialists").json() == [agent]


@pytest.mark.parametrize("field", ["outward_patterns", "always_ask_patterns"])
def test_patch_accepts_patterns_with_the_allowed_characters(api, agent, field):
    patterns = [
        "python3 filmes.py baixar", "kubectl -n prod apply", "gh api repos/o/r:x",
        "implantação_rápida", "y" * 100,
    ]

    response = api.patch(f"/api/specialists/{agent['id']}", json={field: patterns})

    assert response.status_code == 200
    assert response.json()[field] == patterns


TOOL_TEXT = (
    "Use o nome da ferramenta (ex.: WebFetch ou mcp__servidor__ferramenta) ou o servidor "
    "inteiro (mcp__servidor), com até 200 caracteres. Sem parênteses, espaços nem curingas."
)


def test_new_agent_has_no_blocked_tools(api, agent):
    assert agent["denied_tools"] == []


def test_patch_blocked_tools_round_trip_cleaned(api, agent):
    response = patch(
        api,
        agent["id"],
        denied_tools=[
            " mcp__kbgen-issues__editar_issue ", "WebFetch", "mcp__kbgen-issues",
            "WebFetch", "mcp__claude_ai_Slack_beta__search",
        ],
    )

    assert response.status_code == 200, response.text
    expected = [
        "mcp__kbgen-issues__editar_issue", "WebFetch", "mcp__kbgen-issues",
        "mcp__claude_ai_Slack_beta__search",
    ]
    assert response.json()["denied_tools"] == expected
    assert api.get("/api/specialists").json()[0]["denied_tools"] == expected
    assert patch(api, agent["id"], denied_tools=[]).json()["denied_tools"] == []


@pytest.mark.parametrize(
    "tool",
    ["Bash(rm:*)", "mcp__srv__*", "mcp__*", "*", "dois nomes", "mcp__", "mcp_srv", "mcp__srv__",
     "mcp__srv__a(b)", "mcp__srv___", "mcp__srv__tool__", "mcp__sr v", "a/b", "1Tool", "Ferramenta.ponto", "x" * 201, "ação", "a\nb"],
)
def test_patch_refuses_blocked_tools_that_are_not_tool_names(api, agent, tool):
    response = api.patch(f"/api/specialists/{agent['id']}", json={"denied_tools": ["WebFetch", tool]})

    assert response.status_code == 422
    assert response.json()["detail"] == TOOL_TEXT
    assert api.get("/api/specialists").json() == [agent]


@pytest.mark.parametrize("tools", [[""], ["   "], ["a"] * 101, [1], "WebFetch", None])
def test_patch_refuses_malformed_blocked_tools_list(api, agent, tools):
    response = api.patch(f"/api/specialists/{agent['id']}", json={"denied_tools": tools})

    assert response.status_code == 422
    assert api.get("/api/specialists").json() == [agent]


def test_patch_accepts_mcp_names_with_separators_at_the_ends(api, agent):
    # The CLI turns any other character of a server name into `_` ("Gmail " -> "Gmail_").
    tools = ["mcp__Gmail_", "mcp__-srv", "mcp__srv_-__tool_", "mcp__srv__tool-", "mcp__srv__a__b"]

    response = api.patch(f"/api/specialists/{agent['id']}", json={"denied_tools": tools})

    assert response.status_code == 200, response.text
    assert response.json()["denied_tools"] == tools


def test_patch_accepts_the_limit_of_blocked_tools(api, agent):
    tools = [f"Tool{i}" for i in range(100)]

    response = api.patch(f"/api/specialists/{agent['id']}", json={"denied_tools": tools})

    assert response.status_code == 200
    assert response.json()["denied_tools"] == tools


def test_patch_unknown_agent_is_404(api):
    assert patch(api, 999, name="x").status_code == 404


def test_patch_project_must_exist(api, agent):
    assert patch(api, agent["id"], project_id=999).status_code == 404
    assert api.get("/api/specialists").json() == [agent]


def test_patch_extra_projects_must_exist_and_nothing_is_saved(api, home, agent):
    other = make_project(api, home, "outro")
    ok = patch(api, agent["id"], extra_project_ids=[other["id"], other["id"], agent["project_id"]])
    assert ok.status_code == 200
    assert ok.json()["extra_project_ids"] == [other["id"]]

    bad = patch(api, agent["id"], name="Não grava", extra_project_ids=[other["id"], 999])
    assert bad.status_code == 422
    current = api.get("/api/specialists").json()[0]
    assert current["name"] == "Revisor"
    assert current["extra_project_ids"] == [other["id"]]


def test_get_filters_extra_projects_that_no_longer_exist(api, home, agent):
    other = make_project(api, home, "outro")
    patch(api, agent["id"], extra_project_ids=[other["id"]])
    assert api.delete(f"/api/projects/{other['id']}").status_code == 204
    assert api.get("/api/specialists").json()[0]["extra_project_ids"] == []


def test_patch_replaces_all_schedules(api, agent):
    first = patch(
        api, agent["id"], schedules=[{"days": "12345", "time": "08:40"}, {"days": "6", "time": "10:00"}]
    )
    assert first.status_code == 200, first.text
    schedules = first.json()["schedules"]
    assert [(s["days"], s["time"]) for s in schedules] == [("12345", "08:40"), ("6", "10:00")]
    assert all(s["last_fired_at"] is not None for s in schedules)

    second = patch(api, agent["id"], schedules=[{"days": "7", "time": "23:59"}])
    assert [(s["days"], s["time"]) for s in second.json()["schedules"]] == [("7", "23:59")]
    assert patch(api, agent["id"], schedules=[]).json()["schedules"] == []


def test_patch_normalizes_the_days(api, agent):
    body = patch(api, agent["id"], schedules=[{"days": "5311", "time": "08:00"}]).json()
    assert body["schedules"][0]["days"] == "135"


@pytest.mark.parametrize(
    "schedules",
    [
        [{"days": "", "time": "08:00"}],
        [{"days": "8", "time": "08:00"}],
        [{"days": "0", "time": "08:00"}],
        [{"days": "ab", "time": "08:00"}],
        [{"days": "1", "time": "24:00"}],
        [{"days": "1", "time": "8:00"}],
        [{"days": "1", "time": "08:60"}],
        [{"days": "1", "time": "08:00:00"}],
        [{"days": "1", "time": ""}],
        [{"days": "1"}],
        [{"days": "1", "time": "08:00", "x": 1}],
        [{"days": "123", "time": "08:00"}, {"days": "3", "time": "08:00"}],
        [{"days": "1", "time": "08:00"}, {"days": "1", "time": "08:00"}],
        [{"days": "1", "time": "08:00"}] * 51,
    ],
)
def test_patch_refuses_invalid_or_repeated_schedules(api, agent, schedules):
    patch(api, agent["id"], schedules=[{"days": "1", "time": "09:00"}])
    before = api.get("/api/specialists").json()[0]
    response = patch(api, agent["id"], name="Não grava", schedules=schedules)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], (str, list))
    assert api.get("/api/specialists").json()[0] == before


def test_patch_accepts_the_same_time_on_different_days(api, agent):
    body = patch(
        api, agent["id"], schedules=[{"days": "1", "time": "08:00"}, {"days": "2", "time": "08:00"}]
    )
    assert body.status_code == 200


def test_patch_is_all_or_nothing(api, agent, monkeypatch):
    patch(api, agent["id"], schedules=[{"days": "1", "time": "09:00"}])

    def broken(*args, **kwargs):
        raise RuntimeError("falha no meio")

    monkeypatch.setattr("claudio_maestro.api.specialists.store.replace_schedules", broken)
    with pytest.raises(RuntimeError):
        patch(api, agent["id"], name="Não grava", schedules=[{"days": "2", "time": "10:00"}])
    current = api.get("/api/specialists").json()[0]
    assert current["name"] == "Revisor"
    assert [(s["days"], s["time"]) for s in current["schedules"]] == [("1", "09:00")]


def test_reenabling_stamps_the_schedules_as_fired(api, agent):
    patch(api, agent["id"], schedules=[{"days": "1234567", "time": "08:00"}])
    patch(api, agent["id"], enabled=False)
    with conn_of(api) as conn, db.transaction(conn):
        conn.execute("UPDATE specialist_schedules SET last_fired_at = 100")

    before = int(time.time())
    body = patch(api, agent["id"], enabled=True).json()
    assert body["schedules"][0]["last_fired_at"] >= before


def test_other_edits_do_not_touch_last_fired_at(api, agent):
    patch(api, agent["id"], schedules=[{"days": "1234567", "time": "08:00"}])
    with conn_of(api) as conn, db.transaction(conn):
        conn.execute("UPDATE specialist_schedules SET last_fired_at = 100")
    assert patch(api, agent["id"], enabled=True, name="Outro").json()["schedules"][0][
        "last_fired_at"
    ] == 100
    patch(api, agent["id"], enabled=False)
    assert patch(api, agent["id"], enabled=False).json()["schedules"][0]["last_fired_at"] == 100


def test_patch_sends_the_changed_event(api, agent, events):
    events.clear()
    patch(api, agent["id"], name="Outro")
    assert {"session_id": None, "seq": 0, "type": "specialist.changed", "data": {"id": agent["id"]}} in events


# Skill and learnings ------------------------------------------------------------------


def test_skill_get_and_put(api, agent):
    text = api.get(f"/api/specialists/{agent['id']}/skill").json()["text"]
    assert text.startswith("---")

    new_text = "---\nname: Revisa PRs\ndescription: Revisa os PRs abertos.\n---\n\n# Passos\n"
    response = api.put(f"/api/specialists/{agent['id']}/skill", json={"text": new_text})
    assert response.status_code == 200, response.text
    assert response.json() == {"name": "Revisa PRs", "description": "Revisa os PRs abertos."}
    assert api.get(f"/api/specialists/{agent['id']}/skill").json() == {"text": new_text}
    assert api.get("/api/specialists").json()[0]["description"] == "Revisa os PRs abertos."


@pytest.mark.parametrize(
    "text, message",
    [
        ("sem cabeçalho", "A skill precisa começar com um bloco de cabeçalho entre linhas '---'."),
        ("---\nname: A\n---\n", "O cabeçalho da skill precisa do campo 'description'."),
        ("---\nname: A\ndescription: B\n", "O cabeçalho da skill não foi fechado com uma linha '---'."),
        ("---\nname: A\ndescription: B\n---\n" + "x" * 100_001, "A skill passou de 100 KB."),
    ],
)
def test_invalid_skill_is_422_with_the_message_and_keeps_the_old_one(api, agent, text, message):
    before = api.get(f"/api/specialists/{agent['id']}/skill").json()
    response = api.put(f"/api/specialists/{agent['id']}/skill", json={"text": text})
    assert response.status_code == 422
    assert response.json()["detail"] == message
    assert api.get(f"/api/specialists/{agent['id']}/skill").json() == before


def test_skill_of_an_unknown_agent_is_404(api):
    assert api.get("/api/specialists/999/skill").status_code == 404
    assert api.put("/api/specialists/999/skill", json={"text": "x"}).status_code == 404


def test_skill_file_gone_from_disk_is_404(api, agent):
    (agents_dir(api) / "revisor" / "SKILL.md").unlink()
    assert api.get(f"/api/specialists/{agent['id']}/skill").status_code == 404
    assert api.get("/api/specialists").json()[0]["description"] == ""


def test_learnings_get_and_put(api, agent):
    url = f"/api/specialists/{agent['id']}/learnings"
    assert api.get(url).json() == {"text": ""}
    assert api.put(url, json={"text": "Lembrar disto"}).status_code == 200
    assert api.get(url).json() == {"text": "Lembrar disto"}


def test_unreadable_skill_and_learnings_are_422_not_500(api, agent):
    folder = agents_dir(api) / "revisor"
    (folder / "SKILL.md").write_bytes(b"---\nname: \xff\xfe\n---\n")
    (folder / "aprendizados.md").write_bytes(b"\xff\xfe\x00")
    skill = api.get(f"/api/specialists/{agent['id']}/skill")
    learnings = api.get(f"/api/specialists/{agent['id']}/learnings")
    assert skill.status_code == 422 and learnings.status_code == 422
    assert "UTF-8" in skill.json()["detail"] and "UTF-8" in learnings.json()["detail"]
    assert api.get("/api/specialists").json()[0]["description"] == ""
    # A new text replaces the broken file.
    assert api.put(f"/api/specialists/{agent['id']}/learnings", json={"text": "ok"}).status_code == 200


def test_learnings_put_sends_the_changed_event(api, agent, events):
    events.clear()
    api.put(f"/api/specialists/{agent['id']}/learnings", json={"text": "a"})
    assert {
        "session_id": None, "seq": 0, "type": "specialist.changed", "data": {"id": agent["id"]}
    } in events


def test_learnings_too_long_is_422_with_the_message(api, agent):
    url = f"/api/specialists/{agent['id']}/learnings"
    api.put(url, json={"text": "ok"})
    response = api.put(url, json={"text": "x" * 4001})
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Passou de 4.000 caracteres. Consolide os aprendizados e tente de novo."
    )
    assert api.get(url).json() == {"text": "ok"}
    assert api.put(url, json={"text": "x" * 4000}).status_code == 200


# Secrets -------------------------------------------------------------------------------


def test_secrets_put_and_get_names_only(api, agent):
    url = f"/api/specialists/{agent['id']}/secrets"
    assert api.get(url).json() == {"names": []}
    response = api.put(url, json={"values": {"SENTRY_TOKEN": SECRET, "GH_TOKEN": "x"}})
    assert response.status_code == 200
    assert response.json() == {"names": ["GH_TOKEN", "SENTRY_TOKEN"]}
    assert api.get(url).json() == {"names": ["GH_TOKEN", "SENTRY_TOKEN"]}

    removed = api.put(url, json={"values": {"GH_TOKEN": None}})
    assert removed.json() == {"names": ["SENTRY_TOKEN"]}
    assert api.app.state.specialist_files.read_secrets("revisor") == {"SENTRY_TOKEN": SECRET}


@pytest.mark.parametrize(
    "body",
    [
        {"values": {"minusculo": SECRET}},
        {"values": {"1ABC": SECRET}},
        {"values": {"OK": 123}},
        {"values": {"OK": f"{SECRET}\x00"}},
        {"values": {"OK": SECRET * 5000}},
        {"values": [SECRET]},
        {"values": SECRET},
        {"outro": SECRET},
        {},
    ],
)
def test_invalid_secrets_are_422_and_never_echo_the_value(api, agent, body):
    url = f"/api/specialists/{agent['id']}/secrets"
    api.put(url, json={"values": {"KEEP": "guardado"}})
    response = api.put(url, json=body)
    assert response.status_code == 422
    assert SECRET not in response.text
    assert api.get(url).json() == {"names": ["KEEP"]}


@pytest.mark.parametrize(
    "body",
    [
        {"values": {SECRET: "x"}},
        {"values": {"ok_" + SECRET: None}},
        {"values": {SECRET: 123}},
        {"values": {SECRET: "y" * 30_000}},
    ],
)
def test_an_invalid_secret_name_is_never_echoed(api, agent, body):
    response = api.put(f"/api/specialists/{agent['id']}/secrets", json=body)
    assert response.status_code == 422
    assert SECRET not in response.text
    assert response.json()["detail"] in (
        "Nome de segredo inválido: use letras maiúsculas, números e _.",
        "Valor inválido para um segredo: use texto de até 20000 caracteres.",
    )


@pytest.mark.parametrize("name", ["PATH", "LD_PRELOAD", "ANTHROPIC_API_KEY", "MAESTRO_PORT", "CLAUDECODE"])
def test_a_reserved_secret_name_is_422_with_a_fixed_message(api, agent, name):
    url = f"/api/specialists/{agent['id']}/secrets"

    response = api.put(url, json={"values": {name: SECRET}})

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Este nome é reservado pelo sistema. Escolha outro nome para o segredo."
    )
    assert name not in response.text and SECRET not in response.text
    assert api.get(url).json() == {"names": []}


def test_secrets_with_a_broken_body_do_not_echo_it(api, agent):
    url = f"/api/specialists/{agent['id']}/secrets"
    response = api.put(url, content=f'{{"values": {{"A": "{SECRET}"', headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert SECRET not in response.text


def test_secrets_of_an_unknown_agent_is_404(api):
    assert api.get("/api/specialists/999/secrets").status_code == 404
    assert api.put("/api/specialists/999/secrets", json={"values": {}}).status_code == 404


def test_secret_values_never_returned(api, home, agent, events):
    events.clear()
    aid = agent["id"]
    api.put(f"/api/specialists/{aid}/secrets", json={"values": {"SENTRY_TOKEN": SECRET}})
    patch(api, aid, name="Outro", run_text="Rode")
    with conn_of(api) as conn, db.transaction(conn):
        store.upsert_item(conn, aid, key="PR-1", status="visto", link=None, note=None, now=1)
        store.add_notice(conn, specialist_id=aid, session_id=None, kind="notice", text="oi", now=1)
    api.post(f"/api/specialists/{aid}/run", json={})
    wait_for(lambda: api.get(f"/api/specialists/{aid}/runs").json())

    urls = [
        "/api/specialists",
        f"/api/specialists/{aid}/skill",
        f"/api/specialists/{aid}/learnings",
        f"/api/specialists/{aid}/secrets",
        f"/api/specialists/{aid}/items",
        f"/api/specialists/{aid}/runs",
        "/api/specialist-notices",
        "/api/specialist-notices?unread=1",
        "/api/sessions",
        "/api/projects",
    ]
    for url in urls:
        response = api.get(url)
        assert response.status_code == 200, url
        assert SECRET not in response.text, url
    assert events
    assert SECRET not in json.dumps(events, default=str)


# Items, runs, notices -------------------------------------------------------------------------


def test_items_list_and_delete(api, agent):
    aid = agent["id"]
    with conn_of(api) as conn, db.transaction(conn):
        store.upsert_item(conn, aid, key="PR-2", status="feito", link="http://x/2", note="n", now=5)
        store.upsert_item(conn, aid, key="PR-1", status="visto", link=None, note=None, now=4)
        store.upsert_item(conn, aid, key="org/repo#3", status="visto", link=None, note=None, now=4)
    items = api.get(f"/api/specialists/{aid}/items").json()
    assert [item["key"] for item in items] == ["PR-1", "PR-2", "org/repo#3"]
    assert items[1] == {
        "key": "PR-2", "status": "feito", "link": "http://x/2", "note": "n",
        "created_at": 5, "updated_at": 5,
    }

    url = f"/api/specialists/{aid}/items"
    assert api.delete(url, params={"key": "PR-1"}).status_code == 204
    assert api.delete(url, params={"key": "org/repo#3"}).status_code == 204
    assert [item["key"] for item in api.get(url).json()] == ["PR-2"]
    assert api.delete("/api/specialists/999/items", params={"key": "PR-2"}).status_code == 404
    assert api.get("/api/specialists/999/items").status_code == 404


def test_item_delete_takes_the_key_from_the_query_as_is(api, agent):
    aid = agent["id"]
    with conn_of(api) as conn, db.transaction(conn):
        for key in ("a/../b", "b", "a", "a/b"):
            store.upsert_item(conn, aid, key=key, status="visto", link=None, note=None, now=4)
    url = f"/api/specialists/{aid}/items"

    assert api.delete(url, params={"key": "a/../b"}).status_code == 204

    assert sorted(item["key"] for item in api.get(url).json()) == ["a", "a/b", "b"]


def test_item_delete_needs_the_key_and_the_old_route_is_gone(api, agent):
    aid = agent["id"]
    with conn_of(api) as conn, db.transaction(conn):
        store.upsert_item(conn, aid, key="PR-1", status="visto", link=None, note=None, now=4)

    assert api.delete(f"/api/specialists/{aid}/items").status_code == 422
    assert api.delete(f"/api/specialists/{aid}/items/PR-1").status_code in (404, 405)
    assert [item["key"] for item in api.get(f"/api/specialists/{aid}/items").json()] == ["PR-1"]


def test_runs_newest_first_with_a_limit(api, agent):
    aid = agent["id"]
    with conn_of(api) as conn, db.transaction(conn):
        for n in range(5):
            store.insert_run(
                conn, specialist_id=aid, trigger="manual", started_at=100 + n, outcome="concluded"
            )
    runs = api.get(f"/api/specialists/{aid}/runs").json()
    assert [run["started_at"] for run in runs] == [104, 103, 102, 101, 100]
    assert set(runs[0]) == {
        "id", "specialist_id", "session_id", "trigger", "scheduled_for", "started_at",
        "ended_at", "outcome", "reason",
    }
    assert len(api.get(f"/api/specialists/{aid}/runs?limit=2").json()) == 2
    assert api.get(f"/api/specialists/{aid}/runs?limit=0").status_code == 422
    assert api.get(f"/api/specialists/{aid}/runs?limit=1000").status_code == 422
    assert api.get("/api/specialists/999/runs").status_code == 404
    assert api.get("/api/specialists").json()[0]["last_run"]["started_at"] == 104


def test_notices_list_and_mark_read(api, agent, events):
    aid = agent["id"]
    with conn_of(api) as conn, db.transaction(conn):
        first = store.add_notice(conn, specialist_id=aid, session_id=None, kind="notice", text="a", now=1)
        second = store.add_notice(conn, specialist_id=aid, session_id=None, kind="alert", text="b", now=2)
    listed = api.get("/api/specialist-notices").json()
    assert [n["id"] for n in listed] == [second.id, first.id]
    assert set(listed[0]) == {
        "id", "specialist_id", "session_id", "kind", "text", "created_at", "read_at",
    }

    events.clear()
    response = api.post("/api/specialist-notices/read", json={"ids": [first.id, 999]})
    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    unread = api.get("/api/specialist-notices?unread=1").json()
    assert [n["id"] for n in unread] == [second.id]
    assert len(api.get("/api/specialist-notices").json()) == 2
    # Only what really changed goes in the event: not the unknown id, not the repeated ones.
    assert [e["data"] for e in events if e["type"] == "specialist.notice"] == [
        {"read_ids": [first.id]}
    ]
    events.clear()
    assert api.post("/api/specialist-notices/read", json={"ids": [first.id]}).json() == {"updated": 0}
    assert events == []
    api.post("/api/specialist-notices/read", json={"ids": [first.id, second.id, second.id]})
    assert [e["data"] for e in events if e["type"] == "specialist.notice"] == [
        {"read_ids": [second.id]}
    ]


def test_notices_read_validates_the_body(api):
    assert api.post("/api/specialist-notices/read", json={}).status_code == 422
    assert api.post("/api/specialist-notices/read", json={"ids": ["a"]}).status_code == 422
    assert api.post("/api/specialist-notices/read", json={"ids": list(range(501))}).status_code == 422


# Run now -----------------------------------------------------------------------------------------


def test_run_returns_202_and_creates_the_agents_session(api, factory, agent, events):
    events.clear()
    response = api.post(f"/api/specialists/{agent['id']}/run", json={})
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["specialist_id"] == agent["id"]
    assert run["trigger"] == "manual"
    assert run["session_id"]

    session = api.get(f"/api/sessions/{run['session_id']}").json()
    assert session["specialist_id"] == agent["id"]
    assert session["title"].startswith("Revisor · ")
    assert factory.clients[-1].sent
    listed = api.get(f"/api/specialists/{agent['id']}/runs").json()
    assert [r["id"] for r in listed] == [run["id"]]
    assert api.get("/api/specialists").json()[0]["open_sessions"] == 1
    assert api.get("/api/specialists").json()[0]["last_run"]["id"] == run["id"]
    assert any(e["type"] == "specialist.run" for e in events)


def test_run_sends_the_given_text_or_the_agents_default(api, factory, agent):
    patch(api, agent["id"], run_text="Texto padrão")
    api.post(f"/api/specialists/{agent['id']}/run", json={})
    api.post(f"/api/specialists/{agent['id']}/run", json={"text": "Texto avulso"})
    api.post(f"/api/specialists/{agent['id']}/run")
    sent = [str(client.sent[0]) for client in factory.clients if client.sent]
    assert any("Texto padrão" in s for s in sent)
    assert any("Texto avulso" in s for s in sent)
    assert sum("Texto padrão" in s for s in sent) == 2


def test_run_validates_the_body_and_the_agent(api, agent):
    assert api.post("/api/specialists/999/run", json={}).status_code == 404
    assert api.post(f"/api/specialists/{agent['id']}/run", json={"text": 3}).status_code == 422
    assert api.post(f"/api/specialists/{agent['id']}/run", json={"x": 1}).status_code == 422


def test_run_with_a_missing_project_folder_records_a_failed_run(api, home, project, agent):
    (home / "app").rmdir()
    response = api.post(f"/api/specialists/{agent['id']}/run", json={})
    assert response.status_code == 202
    run = response.json()
    assert run["outcome"] == "failed" and run["session_id"] is None


def test_open_sessions_counts_unfinished_ones(api, agent):
    run = api.post(f"/api/specialists/{agent['id']}/run", json={}).json()
    assert api.get("/api/specialists").json()[0]["open_sessions"] == 1
    api.patch(f"/api/sessions/{run['session_id']}", json={"finished": True})
    assert api.get("/api/specialists").json()[0]["open_sessions"] == 0


# Delete ---------------------------------------------------------------------------------------------


def test_delete_removes_row_and_folder_and_keeps_the_sessions_unlinked(api, agent, events):
    run = api.post(f"/api/specialists/{agent['id']}/run", json={}).json()
    sid = run["session_id"]
    wait_for(lambda: api.get(f"/api/sessions/{sid}").json()["state"] in ("idle", "closed"))
    api.put(f"/api/specialists/{agent['id']}/secrets", json={"values": {"A": SECRET}})
    events.clear()

    response = api.delete(f"/api/specialists/{agent['id']}")
    assert response.status_code == 204
    assert api.get("/api/specialists").json() == []
    assert not (agents_dir(api) / "revisor").exists()
    session = api.get(f"/api/sessions/{sid}").json()
    assert session["specialist_id"] is None
    with conn_of(api) as conn:
        assert conn.execute("SELECT specialist_id FROM sessions WHERE session_id = ?", (sid,)).fetchone()[0] is None
        assert conn.execute("SELECT COUNT(*) FROM specialist_runs").fetchone()[0] == 0
    assert any(e["type"] == "specialist.changed" for e in events)
    assert api.delete(f"/api/specialists/{agent['id']}").status_code == 404


def test_delete_with_an_open_turn_is_409_and_keeps_everything(api, agent, monkeypatch):
    monkeypatch.setattr(api.app.state.specialists, "is_busy", lambda specialist_id: True)
    response = api.delete(f"/api/specialists/{agent['id']}")
    assert response.status_code == 409
    assert response.json()["detail"]
    assert len(api.get("/api/specialists").json()) == 1
    assert (agents_dir(api) / "revisor" / "SKILL.md").is_file()


def test_deleting_a_project_removes_its_agents_and_their_folders(api, home):
    other = make_project(api, home, "outro")
    agent = create_agent(api, other["id"], "do-outro")
    api.put(f"/api/specialists/{agent['id']}/secrets", json={"values": {"A": SECRET}})
    assert (agents_dir(api) / "do-outro" / "secrets.env").is_file()
    assert api.delete(f"/api/projects/{other['id']}").status_code == 204
    assert api.get("/api/specialists").json() == []
    assert not (agents_dir(api) / "do-outro").exists()


def test_deleting_a_project_takes_it_out_of_the_other_agents_extra_projects(api, home, events):
    first = make_project(api, home, "primeiro")
    second = make_project(api, home, "segundo")
    agent = create_agent(api, first["id"], "leitor")
    other = create_agent(api, first["id"], "outro")
    patch(api, agent["id"], extra_project_ids=[second["id"]])
    patch(api, other["id"], extra_project_ids=[])
    events.clear()

    assert api.delete(f"/api/projects/{second['id']}").status_code == 204

    with conn_of(api) as conn:
        assert store.get_specialist(conn, agent["id"]).extra_project_ids == []
        assert store.get_specialist(conn, other["id"]).extra_project_ids == []
    changed = [e["data"]["id"] for e in events if e["type"] == "specialist.changed"]
    assert changed == [agent["id"]]


# Auth ------------------------------------------------------------------------------------------------------


def mutating_requests(agent_id: int) -> list[tuple[str, str, dict | None]]:
    base = f"/api/specialists/{agent_id}"
    return [
        ("POST", "/api/specialists", {"name": "N", "slug": "novo", "project_id": 1}),
        ("PATCH", base, {"name": "X"}),
        ("DELETE", base, None),
        ("PUT", f"{base}/skill", {"text": "x"}),
        ("PUT", f"{base}/learnings", {"text": "x"}),
        ("PUT", f"{base}/secrets", {"values": {"A": "b"}}),
        ("DELETE", f"{base}/items?key=k", None),
        ("POST", f"{base}/run", {}),
        ("POST", "/api/specialist-notices/read", {"ids": [1]}),
    ]


@pytest.mark.parametrize("index", range(9))
def test_routes_refuse_a_request_without_the_app_header(api, agent, index):
    method, url, body = mutating_requests(agent["id"])[index]
    with without_header(api, "x-maestro"):
        assert api.request(method, url, json=body).status_code == 403
    assert api.get("/api/specialists").json() == [agent]


@pytest.mark.parametrize("index", range(9))
def test_routes_refuse_a_foreign_origin(api, agent, index):
    method, url, body = mutating_requests(agent["id"])[index]
    response = api.request(method, url, json=body, headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert api.get("/api/specialists").json() == [agent]


@pytest.mark.parametrize(
    "path",
    [
        "/api/specialists", "/api/specialists/1/skill", "/api/specialists/1/learnings",
        "/api/specialists/1/secrets", "/api/specialists/1/items", "/api/specialists/1/runs",
        "/api/specialist-notices",
    ],
)
def test_reads_refuse_a_request_without_the_app_header(api, agent, path):
    with without_header(api, "x-maestro"):
        assert api.get(path).status_code == 403


# Wiring in the app ---------------------------------------------------------------------------------------------


def test_sessions_carry_specialist_id_none_when_ordinary(api, project):
    session = api.post(f"/api/projects/{project['id']}/sessions").json()
    assert session["specialist_id"] is None
    assert api.get(f"/api/sessions/{session['session_id']}").json()["specialist_id"] is None


def test_finishing_the_session_concludes_the_run_and_the_digest_hook_still_runs(
    api, agent, monkeypatch
):
    seen: list[str] = []

    async def record_finish(session_id: str, finished_at: int) -> None:
        seen.append(session_id)

    monkeypatch.setattr(api.app.state.digest, "record_finish", record_finish)
    run = api.post(f"/api/specialists/{agent['id']}/run", json={}).json()
    sid = run["session_id"]
    assert api.patch(f"/api/sessions/{sid}", json={"finished": True}).status_code == 200

    done = wait_for(
        lambda: next(
            (r for r in api.get(f"/api/specialists/{agent['id']}/runs").json() if r["outcome"] == "concluded"),
            None,
        )
    )
    assert done["reason"] == "Finalizada por você"
    wait_for(lambda: seen)
    assert seen == [sid]


def test_a_failing_digest_hook_does_not_stop_the_specialist_hook(api, agent, monkeypatch):
    def boom(session_id: str, finished_at: int):
        raise RuntimeError("falha nas entregas")

    monkeypatch.setattr(api.app.state.digest, "record_finish", boom)
    run = api.post(f"/api/specialists/{agent['id']}/run", json={}).json()
    api.patch(f"/api/sessions/{run['session_id']}", json={"finished": True})
    wait_for(
        lambda: any(r["outcome"] == "concluded" for r in api.get(f"/api/specialists/{agent['id']}/runs").json())
    )


def test_a_failing_specialist_hook_does_not_stop_the_digest_hook(api, agent, monkeypatch):
    seen: list[str] = []

    async def record_finish(session_id: str, finished_at: int) -> None:
        seen.append(session_id)

    def boom(session_id: str, finished_at: int):
        raise RuntimeError("falha nos agentes")

    monkeypatch.setattr(api.app.state.digest, "record_finish", record_finish)
    monkeypatch.setattr(api.app.state.specialists, "on_finished", boom)
    run = api.post(f"/api/specialists/{agent['id']}/run", json={}).json()
    response = api.patch(f"/api/sessions/{run['session_id']}", json={"finished": True})
    assert response.status_code == 200
    wait_for(lambda: seen)


def test_the_digest_hands_closures_to_the_specialist_service(api):
    # The digest only calls this hook when a closure is saved; checking the wiring.
    assert api.app.state.digest._on_closure == api.app.state.specialists.on_closure


def test_the_scheduler_runs_with_the_app_and_stops_with_it(factory, monkeypatch):
    calls: list[str] = []
    original_shutdown = SpecialistService.shutdown

    async def shutdown(self) -> None:
        calls.append("shutdown")
        await original_shutdown(self)

    async def tick(self) -> None:
        calls.append("tick")

    monkeypatch.setattr(SpecialistService, "shutdown", shutdown)
    monkeypatch.setattr("claudio_maestro.specialists.scheduler.Scheduler.tick", tick)
    app = create_app(agent_factory=factory)
    with TestClient(app, base_url=BACKEND_URL):
        wait_for(lambda: "tick" in calls)
        assert app.state.scheduler_task is not None and not app.state.scheduler_task.done()
    assert calls[-1] == "shutdown"
    assert app.state.scheduler_task.done()


def test_scheduler_switch_off_keeps_it_from_running_but_run_now_works(factory, monkeypatch, home):
    calls: list[str] = []

    async def tick(self) -> None:
        calls.append("tick")

    monkeypatch.setattr("claudio_maestro.specialists.scheduler.Scheduler.tick", tick)
    monkeypatch.setenv("MAESTRO_SPECIALISTS_SCHEDULER", "0")
    app = create_app(agent_factory=factory)
    with TestClient(
        app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
    ) as client:
        assert app.state.settings.specialists_scheduler is False
        assert app.state.scheduler_task is None
        agent = create_agent(client, make_project(client, home)["id"])
        response = client.post(f"/api/specialists/{agent['id']}/run", json={})
        assert response.status_code == 202
        assert response.json()["session_id"] is not None
        time.sleep(0.1)
    assert calls == []


def test_load_settings_reads_the_scheduler_switch(monkeypatch):
    from claudio_maestro.config import load_settings

    monkeypatch.setenv("MAESTRO_SPECIALISTS_SCHEDULER", "0")
    assert load_settings().specialists_scheduler is False
    monkeypatch.setenv("MAESTRO_SPECIALISTS_SCHEDULER", "1")
    assert load_settings().specialists_scheduler is True
    monkeypatch.delenv("MAESTRO_SPECIALISTS_SCHEDULER")
    assert load_settings().specialists_scheduler is True


def test_startup_recovers_lost_finishes_after_reattaching_the_sessions(factory, monkeypatch):
    calls: list[str] = []

    async def reattach_all(self):
        calls.append("reattach")
        return set()

    async def recover(self) -> None:
        calls.append("recover")

    monkeypatch.setattr("claudio_maestro.sessions.SessionManager.reattach_all", reattach_all)
    monkeypatch.setattr(SpecialistService, "recover", recover)
    with TestClient(create_app(agent_factory=factory), base_url=BACKEND_URL):
        assert calls == ["reattach", "recover"]


def test_a_failing_recover_does_not_stop_the_app(factory, monkeypatch):
    async def recover(self) -> None:
        raise RuntimeError("quebrou")

    monkeypatch.setattr(SpecialistService, "recover", recover)
    with TestClient(create_app(agent_factory=factory), base_url=BACKEND_URL) as client:
        assert client.get("/api/specialists", headers={"x-maestro": "1"}).status_code == 200
