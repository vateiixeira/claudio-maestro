"""Remote Control and the real CLI watcher: the app's own dead process is not a terminal."""

import asyncio

import pytest
from test_cliwatch import env, idle_app_session, jsonl, prompt  # noqa: F401
from watchfiles import Change


@pytest.mark.anyio
async def test_app_process_dying_mid_turn_is_not_taken_for_a_terminal(env):  # noqa: F811
    """The app's own process dies in the middle of a turn. Its last lines leave a turn
    open in the file, and the watcher pass after the death sees no app writing, so it
    records the CLI as running. The automatic reconnect must not take that for a
    terminal: it stays `failed` and tries again."""
    session = await idle_app_session(env)
    session.save(remote_control=True)
    session.remote_retry_delays = (0.2,)
    env.start()
    env.file("s1").write_text(jsonl(prompt("u-app")))
    env.watch.push((Change.modified, env.file("s1")))
    await session._fail("O agente encerrou a conexão.")
    assert session.remote_state == "failed"

    await asyncio.sleep(0.8)

    assert env.manager._cli_running("s1")  # the signal that fooled the old check
    assert session.remote_state == "failed"
    assert session._remote_attempts >= 2  # it kept trying, with the interval growing
    assert session._remote_retry_task is not None and not session._remote_retry_task.done()
