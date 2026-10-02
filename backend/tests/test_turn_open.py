from contextlib import closing

import anyio
import pytest
from test_sessions import WAIT, by_session, env_cleanup, make_env  # noqa: F401

from claudio_maestro import db
from claudio_maestro.agent.fake import PauseStep, text_turn
from claudio_maestro.sessions import INTERRUPTED_TEXT


def turn_open(env, session_id: str) -> int:
    with closing(db.connect(env.db_path)) as conn:
        return conn.execute(
            "SELECT turn_open FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()[0]


async def paused_turn(make_env, env_cleanup):
    """A session whose first turn stops half-way until `pause.release` is set."""
    pause = PauseStep()

    def first(sid):
        turn = text_turn(sid, "resposta")
        return [*turn[:2], pause, *turn[2:]]

    script, ids = by_session(first)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("oi")
    with anyio.fail_after(WAIT):
        await pause.reached.wait()
    return env, session, pause


@pytest.mark.anyio
async def test_turn_open_follows_the_turn(make_env, env_cleanup):
    env, session, pause = await paused_turn(make_env, env_cleanup)
    assert turn_open(env, session.session_id) == 1
    pause.release.set()
    with anyio.fail_after(WAIT):
        while session.state != "idle":
            await anyio.sleep(0.001)
    assert turn_open(env, session.session_id) == 0


@pytest.mark.anyio
async def test_final_close_keeps_turn_open_and_marks_interrupted(make_env, env_cleanup):
    env, session, _pause = await paused_turn(make_env, env_cleanup)
    await env.manager.shutdown()
    assert turn_open(env, session.session_id) == 1
    record = env.manager.find_record(session.session_id)
    assert env.manager.describe_record(record)["interrupted"] is True


@pytest.mark.anyio
async def test_user_close_clears_turn_open(make_env, env_cleanup):
    env, session, _pause = await paused_turn(make_env, env_cleanup)
    await session.close()
    assert turn_open(env, session.session_id) == 0


@pytest.mark.anyio
async def test_interrupted_session_shows_notice_on_open(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)
    with closing(db.connect(env.db_path)) as conn:
        conn.execute("UPDATE sessions SET turn_open = 1 WHERE session_id = ?",
                     (record.session_id,))
    snapshot = await env.manager.open(record.session_id)
    assert snapshot["interrupted"] is True
    assert any(item.get("text") == INTERRUPTED_TEXT for item in snapshot["items"])
