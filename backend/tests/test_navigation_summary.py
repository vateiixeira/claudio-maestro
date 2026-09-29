"""Marco 7: fields of the session summary used by the new navigation."""

from contextlib import closing

import pytest
from claude_agent_sdk import ToolUseBlock

from test_sessions import by_session, env_cleanup, make_env, session_row, wait_until  # noqa: F401
from vibing import db
from vibing.agent.fake import response_messages, text_turn, tool_turn
from vibing.sessions import last_action_text


# last_action_text -----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "tool_input", "expected"),
    [
        ("Edit", {"file_path": "/home/vi/app/backend/sessions.py"}, "Edit sessions.py"),
        ("Read", {"file_path": "/home/vi/app/ROADMAP.md"}, "Read ROADMAP.md"),
        ("Write", {"file_path": "/tmp/a.txt"}, "Write a.txt"),
        ("MultiEdit", {"file_path": "/tmp/b.py"}, "MultiEdit b.py"),
        ("NotebookEdit", {"notebook_path": "/tmp/n.ipynb"}, "NotebookEdit n.ipynb"),
        ("Bash", {"command": "pnpm   test\n--run"}, "Bash: pnpm test --run"),
        ("Grep", {"pattern": "def main"}, "Grep: def main"),
        ("Glob", {"pattern": "**/*.vue"}, "Glob: **/*.vue"),
        ("Agent", {"description": "Revisar a tarefa"}, "Agent: Revisar a tarefa"),
        ("Task", {"description": "Explorar"}, "Task: Explorar"),
        ("WebFetch", {"url": "https://x"}, "WebFetch"),
        ("Edit", {}, "Edit"),
        ("Bash", {"command": "   "}, "Bash"),
    ],
)
def test_last_action_text(name, tool_input, expected):
    assert last_action_text(name, tool_input) == expected


def test_last_action_text_is_cut_at_80_characters():
    text = last_action_text("Bash", {"command": "x" * 200})
    assert len(text) == 80
    assert text.endswith("…")


# finished_at ----------------------------------------------------------------


def test_migration_adds_finished_at(tmp_path):
    path = tmp_path / "vibing.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert "finished_at" in columns


@pytest.mark.anyio
async def test_finish_sets_and_reopen_clears_finished_at(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    sid = session.session_id

    finished = await env.manager.update(sid, finished=True)
    assert isinstance(finished["finished_at"], int)
    assert session_row(env.db_path, sid)["finished_at"] == finished["finished_at"]

    reopened = await env.manager.update(sid, finished=False)
    assert reopened["finished_at"] is None
    assert session_row(env.db_path, sid)["finished_at"] is None


@pytest.mark.anyio
async def test_new_session_has_no_finished_at(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    assert session.summary()["finished_at"] is None
    listed = env.manager.list_sessions()
    assert listed[0]["finished_at"] is None


# last_action ------------------------------------------------------------------


@pytest.mark.anyio
async def test_last_action_follows_main_tool_use_and_is_emitted(make_env, env_cleanup):
    script, ids = by_session(
        lambda sid: tool_turn(sid, tool_name="Edit", tool_input={"file_path": "/p/app/main.py"}),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    assert session.summary()["last_action"] is None
    await session.send("edite")
    await wait_until(lambda: session.state == "idle")

    assert session.summary()["last_action"] == "Edit main.py"
    updates = env.recorder.of(session.session_id, "session.updated")
    assert any(u["data"]["last_action"] == "Edit main.py" for u in updates)


@pytest.mark.anyio
async def test_subagent_tool_use_does_not_change_last_action(make_env, env_cleanup):
    def turn(sid):
        steps = text_turn(sid, "ok")
        sub = response_messages(
            sid,
            [ToolUseBlock(id="toolu_sub", name="Bash", input={"command": "ls"})],
            parent_tool_use_id="toolu_parent",
            stop_reason="tool_use",
        )
        # Before the final result message.
        return [*steps[:-1], *sub, steps[-1]]

    script, ids = by_session(turn)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    assert session.summary()["last_action"] is None


# pending_kind -----------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "tool_input", "kind"),
    [
        ("Bash", {"command": "ls"}, "tool"),
        ("AskUserQuestion", {"questions": []}, "question"),
        ("ExitPlanMode", {"plan": "passos"}, "plan"),
    ],
)
async def test_pending_kind_follows_the_oldest_prompt(make_env, env_cleanup, tool_name, tool_input, kind):
    script, ids = by_session(
        lambda sid: tool_turn(sid, tool_name=tool_name, tool_input=tool_input, ask_permission=True),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("vai")
    await wait_until(lambda: session.state == "awaiting_decision")

    assert session.summary()["pending_kind"] == kind
    updates = env.recorder.of(session.session_id, "session.updated")
    assert updates[-1]["data"]["pending_kind"] == kind

    [prompt] = session.snapshot()["prompts"]
    decision = {"tool": "allow_once", "question": "deny", "plan": "approve"}[kind]
    session.resolve_prompt(prompt["prompt_id"], decision)
    await wait_until(lambda: session.state == "idle")

    assert session.summary()["pending_kind"] is None
    updates = env.recorder.of(session.session_id, "session.updated")
    assert any(u["data"]["pending_kind"] is None for u in updates[-3:])


@pytest.mark.anyio
async def test_listing_of_closed_session_has_null_extras(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    env.new_session()
    [item] = env.manager.list_sessions()
    assert item["last_action"] is None
    assert item["pending_kind"] is None
