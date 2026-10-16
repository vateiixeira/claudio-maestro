"""Search inside the text of the conversations: a phrase said in the middle of one is found."""

import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from history_fakes import FakeHistory, info
from textindex_helpers import assistant, user, write

from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"

PHRASE = (
    "Na jornada do funil você monta uma regra assim:\n\n"
    "Se o card não responder:\n\n"
    "Se a pessoa não responder, o sistema cria uma tarefa automaticamente para o responsável do card."
)


@pytest.fixture
def fake() -> FakeHistory:
    return FakeHistory()


@pytest.fixture
def files() -> dict[str, Path]:
    return {}


@pytest.fixture
def api(fake, files, home: Path, data_dir: Path):
    settings = Settings(home_dir=home, data_dir=data_dir, history_sync_interval_seconds=3600)
    app = create_app(
        settings=settings,
        agent_factory=FakeAgentFactory(),
        history_exists=lambda sid, cwd: sid in fake.messages,
        rename_session=fake.rename_session,
        list_sessions=fake.list_sessions,
        get_session_messages=fake.get_session_messages,
        read_tool_results=fake.read_tool_results,
        session_file=lambda sid, directory: files.get(sid),
    )
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as c:
        yield c


def make_project(api: TestClient, home: Path) -> dict[str, Any]:
    folder = home / "app"
    folder.mkdir(exist_ok=True)
    response = api.post("/api/projects", json={"name": "app", "path": str(folder), "color": "#ff8800"})
    assert response.status_code == 201
    return response.json()


def add_session(fake, files, home, project, session_id, *, summary="", entries, modified_ms=1_000_000_000_000):
    """A session in the history listing of the project and a transcript file for it."""
    fake.add(project["path"], info(session_id, project["path"], summary=summary, modified_ms=modified_ms))
    path = home / f"{session_id}.jsonl"
    write(path, entries)
    files[session_id] = path


def search(api: TestClient, q: str, **params: Any) -> list[dict[str, Any]]:
    return api.get("/api/sessions/search", params={"q": q, **params}).json()


def wait_for_match(api: TestClient, q: str, session_id: str, timeout: float = 5.0) -> dict[str, Any]:
    """The index fills in the background after a sync: ask until the session shows a snippet."""
    deadline = time.monotonic() + timeout
    while True:
        found = {s["session_id"]: s for s in search(api, q)}
        if session_id in found and found[session_id]["match"]:
            return found[session_id]
        assert time.monotonic() < deadline, found
        time.sleep(0.02)


def test_finds_a_phrase_said_inside_a_conversation(api, fake, files, home):
    project = make_project(api, home)
    add_session(
        fake, files, home, project, "s1", summary="Criar tarefa em card parado no Flow",
        entries=[user("como crio uma regra?"), assistant(PHRASE)],
    )
    api.post(f"/api/projects/{project['id']}/sync")

    found = wait_for_match(api, "tarefa automaticamente", "s1")

    assert [p["text"] for p in found["match"]["parts"] if p["hit"]] == ["tarefa automaticamente"]
    assert isinstance(found["match"]["at"], int)


def test_a_title_match_has_no_snippet(api, fake, files, home):
    project = make_project(api, home)
    add_session(fake, files, home, project, "s1", summary="Cupom expirado", entries=[user("oi")])
    api.post(f"/api/projects/{project['id']}/sync")

    [found] = search(api, "cupom")

    assert found["session_id"] == "s1" and found["match"] is None


def test_a_session_that_matches_both_ways_appears_once_with_the_snippet(api, fake, files, home):
    project = make_project(api, home)
    add_session(
        fake, files, home, project, "s1", summary="Funil de vendas",
        entries=[assistant("o funil converte bem")],
    )
    api.post(f"/api/projects/{project['id']}/sync")

    wait_for_match(api, "funil", "s1")

    assert [s["session_id"] for s in search(api, "funil")] == ["s1"]


def test_metadata_matches_come_first_and_each_group_is_newest_first(api, fake, files, home):
    project = make_project(api, home)
    plain = [user("oi")]
    with_term = [assistant("falando do funil de vendas")]
    add_session(fake, files, home, project, "m_old", summary="funil antigo", entries=plain, modified_ms=1_000_000_000_000)
    add_session(fake, files, home, project, "m_new", summary="funil novo", entries=plain, modified_ms=3_000_000_000_000)
    add_session(fake, files, home, project, "c_old", summary="Outra", entries=with_term, modified_ms=2_000_000_000_000)
    add_session(fake, files, home, project, "c_new", summary="Mais outra", entries=with_term, modified_ms=4_000_000_000_000)
    api.post(f"/api/projects/{project['id']}/sync")
    wait_for_match(api, "funil", "c_old")
    wait_for_match(api, "funil", "c_new")

    assert [s["session_id"] for s in search(api, "funil")] == ["m_new", "m_old", "c_new", "c_old"]


def test_the_limit_counts_both_groups(api, fake, files, home):
    project = make_project(api, home)
    for number in range(3):
        add_session(
            fake, files, home, project, f"c{number}", summary=f"Sessão {number}",
            entries=[assistant("o funil converte")], modified_ms=1_000_000_000_000 + number * 10_000,
        )
    api.post(f"/api/projects/{project['id']}/sync")
    for number in range(3):
        wait_for_match(api, "funil", f"c{number}")

    assert [s["session_id"] for s in search(api, "funil", limit=2)] == ["c2", "c1"]


def test_a_discarded_session_is_out_of_the_content_search(api, fake, files, home):
    project = make_project(api, home)
    add_session(fake, files, home, project, "s1", summary="Qualquer", entries=[assistant("o funil converte")])
    api.post(f"/api/projects/{project['id']}/sync")
    wait_for_match(api, "funil", "s1")

    api.patch("/api/sessions/s1", json={"mark": "discarded"})

    assert search(api, "funil") == []


def test_a_short_term_only_searches_the_metadata(api, fake, files, home):
    project = make_project(api, home)
    add_session(fake, files, home, project, "s1", summary="Ab", entries=[assistant("xx ab yy")])
    api.post(f"/api/projects/{project['id']}/sync")
    time.sleep(0.3)

    [found] = search(api, "ab")

    assert found["session_id"] == "s1" and found["match"] is None


def test_html_in_the_conversation_stays_text(api, fake, files, home):
    project = make_project(api, home)
    add_session(
        fake, files, home, project, "s1", summary="Qualquer",
        entries=[assistant('veja <img src=x onerror="alert(1)"> aqui')],
    )
    api.post(f"/api/projects/{project['id']}/sync")

    found = wait_for_match(api, "onerror", "s1")

    assert "".join(p["text"] for p in found["match"]["parts"]) == 'veja <img src=x onerror="alert(1)"> aqui'


def test_a_failing_index_falls_back_to_the_metadata(api, fake, files, home, monkeypatch):
    project = make_project(api, home)
    add_session(fake, files, home, project, "s1", summary="Funil de vendas", entries=[assistant("o funil")])
    add_session(fake, files, home, project, "s2", summary="Outra", entries=[assistant("o funil")])
    api.post(f"/api/projects/{project['id']}/sync")
    wait_for_match(api, "funil", "s2")

    def boom(query):
        raise RuntimeError("índice quebrado")

    monkeypatch.setattr(api.app.state.textindex, "matching", boom)

    found = search(api, "funil")

    assert [s["session_id"] for s in found] == ["s1"]
    assert found[0]["match"] is None


def test_a_sqlite_error_while_building_the_snippet_keeps_the_session(api, fake, files, home, monkeypatch):
    project = make_project(api, home)
    add_session(fake, files, home, project, "s1", summary="Qualquer", entries=[assistant("o funil")])
    api.post(f"/api/projects/{project['id']}/sync")
    wait_for_match(api, "funil", "s1")

    def boom(query, rowid):
        raise sqlite3.DatabaseError("disk image is malformed")

    monkeypatch.setattr(api.app.state.textindex, "match_for", boom)

    [found] = search(api, "funil")

    assert found["session_id"] == "s1" and found["match"] is None
