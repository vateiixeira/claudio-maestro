"""Active sessions: sending, turns, permissions, interruption and failures.

All tests use the scripted fake agent; nothing here starts the `claude` process.
"""

import asyncio
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import anyio
import pytest
from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    TextBlock,
)

from claudio_maestro import db
from claudio_maestro.agent.base import AgentError
from claudio_maestro.agent.fake import (
    DEFAULT_FAILURE,
    FailStep,
    FakeAgentClient,
    FakeAgentFactory,
    PauseStep,
    PermissionStep,
    init_message,
    response_messages,
    text_turn,
    tool_turn,
)
from claudio_maestro.projects import Project
from claudio_maestro.sessions import (
    DEFAULT_TITLE,
    AlwaysNotAvailableError,
    EmptyMessageError,
    PromptNotFoundError,
    SessionClosedError,
    SessionManager,
    SessionNotFoundError,
    sdk_history_exists,
)

WAIT = 2  # seconds; every wait fails instead of hanging the suite


# Helpers -------------------------------------------------------------------


class Recorder:
    """Stands in for the event hub: keeps every envelope published."""

    def __init__(self) -> None:
        self.envelopes: list[dict[str, Any]] = []

    def __call__(self, envelope: dict[str, Any]) -> None:
        self.envelopes.append(envelope)

    def of(self, session_id: str, type_: str | None = None) -> list[dict[str, Any]]:
        return [
            e
            for e in self.envelopes
            if e["session_id"] == session_id and (type_ is None or e["type"] == type_)
        ]

    def states(self, session_id: str) -> list[str]:
        return [e["data"]["state"] for e in self.of(session_id, "session.state")]


async def wait_until(predicate: Callable[[], bool]) -> None:
    with anyio.fail_after(WAIT):
        while not predicate():
            await anyio.sleep(0.001)


def fake_history(factory: FakeAgentFactory) -> Callable[[str, str], bool]:
    """History exists once some client of that session has sent a message."""

    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    return history_exists


def make_project(db_path: Path, folder: Path) -> Project:
    folder.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(db_path)) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (name, path, color, position, created_at)"
            " VALUES ('app', ?, '#ff8800', 0, 0)",
            (str(folder),),
        )
        project_id = cursor.lastrowid
    return Project(
        id=project_id, name="app", path=str(folder), color="#ff8800", position=0,
        created_at=0, available=True,
    )


def session_row(db_path: Path, session_id: str) -> dict[str, Any]:
    with closing(db.connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return dict(row)


class Env:
    def __init__(self, tmp_path: Path, factory, history_exists=None) -> None:
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.project = make_project(self.db_path, tmp_path / "home" / "app")
        self.factory = factory
        self.recorder = Recorder()
        self.manager = SessionManager(
            self.db_path,
            self.recorder,
            agent_factory=factory,
            history_exists=history_exists or fake_history(factory),
        )

    def new_session(self):
        record = self.manager.create_session(self.project)
        return self.manager.get(record.session_id)


@pytest.fixture
def make_env(tmp_path: Path):
    def build(script=None, connect_error=None, history_exists=None, factory=None) -> Env:
        factory = factory or FakeAgentFactory(script=script, connect_error=connect_error)
        return Env(tmp_path, factory, history_exists)

    return build


@pytest.fixture
async def env_cleanup():
    """Shut down managers created by a test so no task outlives it."""
    managers: list[SessionManager] = []
    yield managers
    for manager in managers:
        await manager.shutdown()


def by_session(*turns: Callable[[str], list]):
    """Script whose turns are built from the client's session id on each send."""
    pending = list(turns)
    session_ids: list[str] = []

    def script(content):
        if not pending:
            return []
        return pending.pop(0)(session_ids[0])

    return script, session_ids


# Creation and first message ------------------------------------------------


@pytest.mark.anyio
async def test_create_session_does_not_start_client(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)

    record = env.manager.create_session(env.project)

    assert env.factory.clients == []
    row = session_row(env.db_path, record.session_id)
    assert row["title"] == DEFAULT_TITLE == "Nova sessão"
    assert row["cwd"] == env.project.path
    assert row["project_id"] == env.project.id
    assert row["created_at"] > 0 and row["last_activity_at"] > 0
    session = env.manager.get(record.session_id)
    assert session.state == "closed"
    assert session.snapshot()["items"] == []


@pytest.mark.anyio
async def test_get_unknown_session_raises(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    with pytest.raises(SessionNotFoundError):
        env.manager.get("00000000-0000-0000-0000-000000000000")


@pytest.mark.anyio
async def test_get_loads_session_from_database(make_env, env_cleanup, tmp_path):
    env = make_env()
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)

    other = SessionManager(env.db_path, Recorder(), agent_factory=env.factory,
                           history_exists=fake_history(env.factory))
    env_cleanup.append(other)
    session = other.get(record.session_id)

    assert session.record.title == DEFAULT_TITLE
    assert session.state == "closed"


@pytest.mark.anyio
async def test_first_message_starts_client_without_resume_and_sets_title(make_env, env_cleanup):
    script = lambda content: text_turn("x", "oi")  # noqa: E731
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    text = "Crie um arquivo chamado notas.txt com a lista de tarefas da semana e depois revise tudo"

    await session.send(text)

    [client] = env.factory.clients
    assert client.options.resume is False
    assert client.options.session_id == session.session_id
    assert client.options.cwd == Path(env.project.path)
    assert client.sent == [text]
    assert session.record.title == text[:80]
    assert session_row(env.db_path, session.session_id)["title"] == text[:80]
    [title_event] = env.recorder.of(session.session_id, "session.title")
    assert title_event["data"] == {"title": text[:80]}


@pytest.mark.anyio
async def test_live_count_counts_sessions_with_a_connected_client(make_env, env_cleanup):
    script = lambda content: text_turn("x", "oi")  # noqa: E731
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    assert env.manager.live_count() == 0
    session = env.new_session()
    assert env.manager.live_count() == 0  # created but no client yet

    await session.send("oi")

    assert env.manager.live_count() == 1


@pytest.mark.anyio
async def test_empty_message_is_refused(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()

    with pytest.raises(EmptyMessageError):
        await session.send("   \n ")

    assert session.snapshot()["items"] == []
    assert env.factory.clients == []


@pytest.mark.anyio
async def test_title_only_changes_on_first_message(make_env, env_cleanup):
    env = make_env(script=lambda content: text_turn("x", "ok"))
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.send("primeira")
    await wait_until(lambda: session.state == "idle")
    await session.send("segunda")

    assert session.record.title == "primeira"


# Turns ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_text_turn_emits_events_in_order_and_goes_idle(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "Olá!"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    with closing(db.connect(env.db_path)) as conn:
        conn.execute("UPDATE sessions SET last_activity_at = 0")

    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    events = env.recorder.of(session.session_id)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[0]["type"] == "item.upsert"
    assert events[0]["data"]["type"] == "user"
    assert events[0]["data"]["text"] == "oi"
    assert env.recorder.states(session.session_id) == ["connecting", "running", "idle"]
    types = [e["type"] for e in events]
    assert types.index("session.init") < types.index("item.append") < types.index("turn.result")
    assert types[-1] == "session.state"
    assert session.pending_turns == 0
    assert session_row(env.db_path, session.session_id)["last_activity_at"] >= int(time.time()) - 5
    assert session.snapshot()["seq"] == events[-1]["seq"]


@pytest.mark.anyio
async def test_message_during_turn_is_accepted_and_answered_after(make_env, env_cleanup):
    pause = PauseStep()

    def first(sid):
        turn = text_turn(sid, "primeira resposta")
        return [*turn[:2], pause, *turn[2:]]

    script, ids = by_session(first, lambda sid: text_turn(sid, "segunda resposta"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("um")
    with anyio.fail_after(WAIT):
        await pause.reached.wait()
    await session.send("dois")

    assert session.state == "running"
    assert session.pending_turns == 2
    users = [i["text"] for i in session.snapshot()["items"] if i["type"] == "user"]
    assert users == ["um", "dois"]

    pause.release.set()
    await wait_until(lambda: session.state == "idle")

    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts == ["primeira resposta", "segunda resposta"]
    assert env.factory.clients[0].sent == ["um", "dois"]
    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_message_with_pending_permission_is_accepted(make_env, env_cleanup):
    script, ids = by_session(
        lambda sid: tool_turn(sid, tool_name="Bash", ask_permission=True),
        lambda sid: text_turn(sid, "depois"),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("rode ls")
    await wait_until(lambda: session.state == "awaiting_decision")
    await session.send("e depois diga oi")

    assert session.state == "awaiting_decision"
    assert session.pending_turns == 2
    [prompt] = session.snapshot()["prompts"]
    session.resolve_prompt(prompt["prompt_id"], "allow_once")
    await wait_until(lambda: session.state == "idle")

    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-1] == "depois"


# Permissions ---------------------------------------------------------------

SUGGESTION = PermissionUpdate(type="setMode", mode="acceptEdits", destination="session")


async def start_permission_turn(make_env, env_cleanup, suggestions=None):
    script, ids = by_session(
        lambda sid: tool_turn(
            sid, tool_name="Write", tool_input={"file_path": "a.txt"}, tool_use_id="toolu_1",
            ask_permission=True, suggestions=suggestions,
        ),
        lambda sid: text_turn(sid, "de novo"),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("escreva")
    await wait_until(lambda: session.state == "awaiting_decision")
    [request] = env.recorder.of(session.session_id, "prompt.request")
    return env, session, request["data"]


@pytest.mark.anyio
async def test_permission_request_is_emitted(make_env, env_cleanup):
    env, session, data = await start_permission_turn(
        make_env, env_cleanup, suggestions=[SUGGESTION]
    )

    assert data["prompt_id"]
    assert data["tool_name"] == "Write"
    assert data["input"] == {"file_path": "a.txt"}
    assert data["tool_use_id"] == "toolu_1"
    assert data["display_name"] == "Write"
    assert "description" in data and "title" in data
    assert data["suggestions"] == [SUGGESTION.to_dict()]
    assert data["can_always"] is True
    assert session.snapshot()["prompts"] == [data]
    assert env.recorder.states(session.session_id)[-1] == "awaiting_decision"


@pytest.mark.anyio
async def test_allow_once(make_env, env_cleanup):
    env, session, data = await start_permission_turn(make_env, env_cleanup)

    session.resolve_prompt(data["prompt_id"], "allow_once")
    await wait_until(lambda: session.state == "idle")

    [record] = env.factory.clients[0].permission_results
    assert record.result == PermissionResultAllow()
    [resolved] = env.recorder.of(session.session_id, "prompt.resolved")
    assert resolved["data"] == {"prompt_id": data["prompt_id"], "decision": "allow_once"}
    assert session.snapshot()["prompts"] == []
    assert "running" in env.recorder.states(session.session_id)[-3:]


@pytest.mark.anyio
async def test_allow_always_passes_suggestions(make_env, env_cleanup):
    env, session, data = await start_permission_turn(
        make_env, env_cleanup, suggestions=[SUGGESTION]
    )

    session.resolve_prompt(data["prompt_id"], "allow_always")
    await wait_until(lambda: session.state == "idle")

    [record] = env.factory.clients[0].permission_results
    assert record.result == PermissionResultAllow(updated_permissions=[SUGGESTION])


@pytest.mark.anyio
async def test_deny(make_env, env_cleanup):
    env, session, data = await start_permission_turn(make_env, env_cleanup)

    session.resolve_prompt(data["prompt_id"], "deny")
    await wait_until(lambda: session.state == "idle")

    [record] = env.factory.clients[0].permission_results
    assert record.result == PermissionResultDeny(message="O usuário recusou.")


@pytest.mark.anyio
async def test_resolving_twice_raises(make_env, env_cleanup):
    env, session, data = await start_permission_turn(make_env, env_cleanup)

    session.resolve_prompt(data["prompt_id"], "allow_once")
    with pytest.raises(PromptNotFoundError):
        session.resolve_prompt(data["prompt_id"], "deny")
    await wait_until(lambda: session.state == "idle")


@pytest.mark.anyio
async def test_allow_always_without_suggestions_is_refused(make_env, env_cleanup):
    env, session, data = await start_permission_turn(make_env, env_cleanup)
    assert data["can_always"] is False

    with pytest.raises(AlwaysNotAvailableError):
        session.resolve_prompt(data["prompt_id"], "allow_always")

    assert session.state == "awaiting_decision"
    assert [p["prompt_id"] for p in session.snapshot()["prompts"]] == [data["prompt_id"]]


# Interruption --------------------------------------------------------------


@pytest.mark.anyio
async def test_interrupt_with_pending_permission(make_env, env_cleanup):
    env, session, data = await start_permission_turn(make_env, env_cleanup)

    await session.interrupt()
    await wait_until(lambda: session.state == "idle")

    [resolved] = env.recorder.of(session.session_id, "prompt.resolved")
    assert resolved["data"] == {"prompt_id": data["prompt_id"], "decision": "cancelled"}
    assert session.snapshot()["prompts"] == []
    notices = [i for i in session.snapshot()["items"] if i["type"] == "notice"]
    assert [(n["level"], n["text"]) for n in notices] == [("info", "Interrompido.")]
    assert env.factory.clients[0].permission_results == []

    await session.send("tente de novo")
    await wait_until(lambda: session.state == "idle" and session.pending_turns == 0)
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-1] == "de novo"
    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_interrupt_without_client_or_turn_does_nothing(make_env, env_cleanup):
    env = make_env(script=lambda content: text_turn("x", "ok"))
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.interrupt()
    assert session.state == "closed"

    await session.send("oi")
    await wait_until(lambda: session.state == "idle")
    await session.interrupt()

    assert env.factory.clients[0].interrupts == 0
    assert session.state == "idle"


# Failures ------------------------------------------------------------------


@pytest.mark.anyio
async def test_failure_mid_turn_then_resend_resumes(make_env, env_cleanup):
    def failing(sid):
        turn = text_turn(sid, "meio")
        return [*turn[:5], FailStep()]

    script, ids = by_session(failing, lambda sid: text_turn(sid, "voltei"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("comece")
    await wait_until(lambda: session.state == "error")

    assert session.error == DEFAULT_FAILURE
    assert env.recorder.of(session.session_id, "session.state")[-1]["data"] == {
        "state": "error", "error": DEFAULT_FAILURE,
    }
    notices = [i for i in session.snapshot()["items"] if i["type"] == "notice"]
    assert [(n["level"], n["text"]) for n in notices] == [("error", DEFAULT_FAILURE)]
    assert session.pending_turns == 0
    assert env.factory.clients[0].closed is True

    await session.send("de novo")
    await wait_until(lambda: session.state == "idle")

    assert len(env.factory.clients) == 2
    assert env.factory.clients[1].options.resume is True
    assert session.error is None
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-1] == "voltei"


@pytest.mark.anyio
async def test_failure_on_send_cancels_pending_prompts(make_env, env_cleanup):
    env, session, data = await start_permission_turn(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.failed = True  # the process died; the next send fails

    await session.send("mais uma")

    assert session.state == "error"
    assert session.error == DEFAULT_FAILURE
    assert session.snapshot()["prompts"] == []
    assert session.pending_turns == 0
    [resolved] = env.recorder.of(session.session_id, "prompt.resolved")
    assert resolved["data"]["decision"] == "cancelled"
    assert client.closed is True
    with pytest.raises(PromptNotFoundError):
        session.resolve_prompt(data["prompt_id"], "allow_once")


@pytest.mark.anyio
async def test_connect_failure(make_env, env_cleanup):
    env = make_env(connect_error=AgentError("Não foi possível conectar ao agente."))
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.send("oi")

    assert session.state == "error"
    assert session.error == "Não foi possível conectar ao agente."
    assert env.recorder.states(session.session_id) == ["connecting", "error"]
    items = session.snapshot()["items"]
    assert [i["type"] for i in items] == ["user", "notice"]
    assert items[1]["level"] == "error"
    assert session.pending_turns == 0


# Snapshot, listing, shutdown ----------------------------------------------


@pytest.mark.anyio
async def test_snapshot_mid_turn_has_partial_text_and_pending_prompt(make_env, env_cleanup):
    def partial(sid):
        streamed = response_messages(sid, [TextBlock(text="Vou rodar")])
        # message_start, content_block_start, text_delta: text still streaming
        return [init_message(sid), *streamed[:3], PermissionStep("Bash", {"command": "ls"})]

    script, ids = by_session(partial)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("liste")
    await wait_until(lambda: session.state == "awaiting_decision")
    snapshot = session.snapshot()

    assert snapshot["session_id"] == session.session_id
    assert snapshot["project_id"] == env.project.id
    assert snapshot["title"] == "liste"
    assert snapshot["cwd"] == env.project.path
    assert snapshot["state"] == "awaiting_decision"
    assert snapshot["error"] is None
    [text] = [i for i in snapshot["items"] if i["type"] == "text"]
    assert text["text"] == "Vou rodar"
    assert text["streaming"] is True
    [prompt] = snapshot["prompts"]
    assert prompt["tool_name"] == "Bash"
    assert snapshot["init"]["session_id"] == session.session_id
    assert snapshot["seq"] == env.recorder.of(session.session_id)[-1]["seq"]


@pytest.mark.anyio
async def test_list_for_project_includes_state(make_env, env_cleanup):
    env = make_env(script=lambda content: text_turn("x", "ok"))
    env_cleanup.append(env.manager)
    first = env.new_session()
    second = env.new_session()
    await second.send("oi")
    await wait_until(lambda: second.state == "idle")

    listed = {s.record.session_id: s for s in env.manager.list_for_project(env.project.id)}

    assert listed[first.session_id].state == "closed"
    assert listed[second.session_id].state == "idle"
    assert listed[second.session_id].record.title == "oi"
    assert env.manager.list_for_project(env.project.id + 1) == []


@pytest.mark.anyio
async def test_shutdown_closes_clients(make_env):
    env = make_env(script=lambda content: text_turn("x", "ok"))
    one = env.new_session()
    two = env.new_session()
    await one.send("a")
    await two.send("b")
    await wait_until(lambda: one.state == two.state == "idle")

    await env.manager.shutdown()

    assert len(env.factory.clients) == 2
    assert all(c.closed for c in env.factory.clients)
    assert one.state == two.state == "closed"


# Resuming existing conversations ------------------------------------------

IN_USE = "O processo do agente encerrou inesperadamente (código 1)."


class CountingHistory:
    """history_exists that answers from a list of results and counts calls."""

    def __init__(self, *answers: bool) -> None:
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, session_id: str, cwd: str) -> bool:
        self.calls += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def fails_without_resume(error: AgentError):
    """Like the real SDK: a session already on disk cannot connect without resume."""
    return lambda options: None if options.resume else error


@pytest.mark.anyio
async def test_reconnect_after_a_successful_connect_resumes_without_checking_disk(
    make_env, env_cleanup
):
    history = CountingHistory(False)
    script, ids = by_session(
        lambda sid: [*text_turn(sid, "meio")[:3], FailStep()],
        lambda sid: text_turn(sid, "voltei"),
    )
    env = make_env(script=script, history_exists=history)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("um")
    await wait_until(lambda: session.state == "error")
    await session.send("dois")
    await wait_until(lambda: session.state == "idle")

    assert [c.options.resume for c in env.factory.clients] == [False, True]
    assert history.calls == 1


@pytest.mark.anyio
async def test_connect_failure_retries_with_resume_when_history_shows_up(make_env, env_cleanup):
    history = CountingHistory(False, True)  # the check after the failure finds it
    env = make_env(
        script=lambda content: text_turn("x", "continuando"),
        connect_error=fails_without_resume(AgentError(IN_USE)),
        history_exists=history,
    )
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.send("continue")
    await wait_until(lambda: session.state == "idle")

    first, second = env.factory.clients
    assert (first.options.resume, second.options.resume) == (False, True)
    assert first.connected is False and first.closed is True
    assert second.sent == ["continue"]
    assert session.error is None
    assert "error" not in env.recorder.states(session.session_id)
    assert not [i for i in session.snapshot()["items"] if i["type"] == "notice"]


@pytest.mark.anyio
async def test_connect_failure_retries_with_resume_on_session_in_use_signal(
    make_env, env_cleanup
):
    history = CountingHistory(False)  # disk never shows it; only the stderr signal
    env = make_env(
        script=lambda content: text_turn("x", "ok"),
        connect_error=fails_without_resume(AgentError(IN_USE, session_in_use=True)),
        history_exists=history,
    )
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.send("continue")
    await wait_until(lambda: session.state == "idle")

    assert [c.options.resume for c in env.factory.clients] == [False, True]


@pytest.mark.anyio
async def test_connect_failure_without_history_is_not_retried(make_env, env_cleanup):
    env = make_env(
        connect_error=AgentError("Não foi possível conectar ao agente."),
        history_exists=CountingHistory(False),
    )
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.send("oi")

    assert len(env.factory.clients) == 1
    assert session.state == "error"


@pytest.mark.anyio
async def test_retry_is_attempted_only_once(make_env, env_cleanup):
    env = make_env(
        connect_error=AgentError(IN_USE, session_in_use=True),
        history_exists=CountingHistory(False),
    )
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.send("oi")

    assert [c.options.resume for c in env.factory.clients] == [False, True]
    assert all(c.closed for c in env.factory.clients)
    assert session.state == "error"
    assert session.error == IN_USE


def test_sdk_history_exists_uses_info_then_messages(monkeypatch):
    import claude_agent_sdk

    calls: list[tuple] = []

    def info(session_id, directory=None):
        calls.append(("info", session_id, directory))
        return infos.pop(0)

    def messages(session_id, directory=None, limit=None, offset=0):
        calls.append(("messages", session_id, directory, limit))
        return found.pop(0)

    monkeypatch.setattr(claude_agent_sdk, "get_session_info", info)
    monkeypatch.setattr(claude_agent_sdk, "get_session_messages", messages)
    infos: list[Any] = [object(), None, None]
    found: list[list] = [["entrada"], []]

    assert sdk_history_exists("sid", "/p") is True
    assert calls == [("info", "sid", "/p")]
    assert sdk_history_exists("sid", "/p") is True
    assert sdk_history_exists("sid", "/p") is False
    assert calls[-1] == ("messages", "sid", "/p", 1)


# Cancellation and concurrent close ----------------------------------------


class GatedClient(FakeAgentClient):
    """Fake client whose connect or send waits for the test to open a gate."""

    def __init__(self, options, *, gate_connect: bool, gate_send: bool) -> None:
        super().__init__(options, script=lambda content: text_turn(options.session_id, "ok"))
        self.gate = asyncio.Event()
        self.waiting = asyncio.Event()
        self.gate_connect = gate_connect
        self.gate_send = gate_send

    async def connect(self) -> None:
        if self.gate_connect:
            self.waiting.set()
            await self.gate.wait()
        await super().connect()

    async def send(self, content) -> None:
        if self.gate_send:
            self.waiting.set()
            await self.gate.wait()
        await super().send(content)


class GatedFactory:
    """Gates only the first client; later ones behave normally."""

    def __init__(self, *, gate_connect: bool = False, gate_send: bool = False) -> None:
        self.clients: list[FakeAgentClient] = []
        self.gate_connect = gate_connect
        self.gate_send = gate_send

    def __call__(self, options) -> FakeAgentClient:
        first = not self.clients
        client = GatedClient(
            options,
            gate_connect=self.gate_connect and first,
            gate_send=self.gate_send and first,
        )
        self.clients.append(client)
        return client


@pytest.mark.anyio
async def test_cancel_during_connect_closes_client_and_restores_state(make_env, env_cleanup):
    factory = GatedFactory(gate_connect=True)
    env = make_env(factory=factory, history_exists=CountingHistory(False))
    env_cleanup.append(env.manager)
    session = env.new_session()

    task = asyncio.create_task(session.send("oi"))
    await wait_until(lambda: bool(factory.clients) and factory.clients[0].waiting.is_set())
    assert session.state == "connecting"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        with anyio.fail_after(WAIT):
            await task

    assert factory.clients[0].closed is True
    assert session.client is None
    assert session.state == "closed"
    assert env.recorder.states(session.session_id)[-1] == "closed"

    await session.send("de novo")  # the lock was released; a new client works
    await wait_until(lambda: session.state == "idle")
    assert len(factory.clients) == 2


@pytest.mark.anyio
async def test_close_during_connect_discards_the_new_client(make_env, env_cleanup):
    factory = GatedFactory(gate_connect=True)
    env = make_env(factory=factory, history_exists=CountingHistory(False))
    env_cleanup.append(env.manager)
    session = env.new_session()

    task = asyncio.create_task(session.send("oi"))
    await wait_until(lambda: bool(factory.clients) and factory.clients[0].waiting.is_set())
    await session.close()
    factory.clients[0].gate.set()
    with anyio.fail_after(WAIT):
        await task

    assert factory.clients[0].closed is True
    assert factory.clients[0].sent == []
    assert session.client is None
    assert session.state == "closed"
    assert session.pending_turns == 0


@pytest.mark.anyio
async def test_close_during_send_leaves_consistent_state(make_env, env_cleanup):
    factory = GatedFactory(gate_send=True)
    env = make_env(factory=factory, history_exists=CountingHistory(False))
    env_cleanup.append(env.manager)
    session = env.new_session()

    task = asyncio.create_task(session.send("oi"))
    await wait_until(lambda: bool(factory.clients) and factory.clients[0].waiting.is_set())
    await session.close()
    factory.clients[0].gate.set()  # the discarded client now fails to send
    with anyio.fail_after(WAIT):
        await task

    assert session.state == "closed"
    assert session.error is None
    assert session.pending_turns == 0
    assert not [i for i in session.snapshot()["items"] if i["type"] == "notice"]

    await session.send("de novo")
    await wait_until(lambda: session.state == "idle")
    assert len(factory.clients) == 2
    assert factory.clients[1].options.resume is True


@pytest.mark.anyio
async def test_send_after_shutdown_is_refused(make_env):
    env = make_env(script=lambda content: text_turn("x", "ok"))
    session = env.new_session()
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    await env.manager.shutdown()

    with pytest.raises(SessionClosedError):
        await session.send("depois")
    assert len(env.factory.clients) == 1
    assert session.state == "closed"


# Open items are closed on failure -------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failing",
    [
        pytest.param(lambda sid: [*text_turn(sid, "meio")[:5], FailStep()], id="mid-text"),
        pytest.param(
            lambda sid: [*tool_turn(sid, tool_name="Bash")[:5], FailStep()], id="mid-tool"
        ),
    ],
)
async def test_failure_closes_open_items(make_env, env_cleanup, failing):
    script, ids = by_session(failing)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("comece")
    await wait_until(lambda: session.state == "error")

    items = session.snapshot()["items"]
    opened = [i for i in items if i["type"] in ("text", "tool")]
    assert opened, "the script should have produced an open item"
    assert all(i.get("streaming") is False for i in items if "streaming" in i)
    upserts = env.recorder.of(session.session_id, "item.upsert")
    last_by_id = {e["data"]["id"]: e["data"] for e in upserts}
    assert all(d.get("streaming") is not True for d in last_by_id.values())


@pytest.mark.anyio
async def test_connect_fails_when_project_folder_is_gone(make_env, env_cleanup):
    import shutil

    env = make_env(script=lambda content: [])
    env_cleanup.append(env.manager)
    session = env.new_session()
    shutil.rmtree(env.project.path)

    await session.send("oi")

    assert session.state == "error"
    assert session.error == f"A pasta do projeto não existe mais: {env.project.path}"
    assert env.factory.clients == []
