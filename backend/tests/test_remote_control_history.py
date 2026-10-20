"""Remote Control and the saved conversation: what a restart must keep and not repeat.

Uses the history environment (a fake `get_session_messages`) and the scripted fake agent.
"""

import asyncio
from types import SimpleNamespace

import pytest
from history_fakes import user_entry
from test_sessions_history import make_env, wait_until  # noqa: F401

from claudio_maestro.agent.fake import remote_user_message
from claudio_maestro.sessions import SessionManager


def second_manager(env) -> SessionManager:
    """A new backend process over the same database, agent and history."""
    return SessionManager(
        env.db_path,
        env.events.append,
        agent_factory=env.factory,
        history_exists=lambda s, c: s in env.fake.messages,
        list_sessions=env.fake.list_sessions,
        get_session_messages=env.fake.get_session_messages,
        read_tool_results=env.fake.read_tool_results,
    )


@pytest.mark.anyio
async def test_startup_reconnect_keeps_saved_history(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.manager.get(sid).save(remote_control=True, remote_control_bridge="cse_1")
    boot = second_manager(env)
    try:
        await boot.reconnect_remote_sessions()

        assert boot.get(sid).client is not None
        snapshot = await boot.open(sid)
        texts = [item.get("text") for item in snapshot["items"]]
        assert "oi" in texts and "olá" in texts, texts
    finally:
        await boot.shutdown()


@pytest.mark.anyio
async def test_startup_reconnect_still_warns_about_an_open_turn(make_env):
    from claudio_maestro.sessions import INTERRUPTED_TEXT

    env = make_env()
    sid = env.add_old_session()
    env.manager.get(sid).save(
        remote_control=True, remote_control_bridge="cse_1", turn_open=True
    )
    boot = second_manager(env)
    try:
        await boot.reconnect_remote_sessions()

        snapshot = await boot.open(sid)
        texts = [item.get("text") for item in snapshot["items"]]
        assert INTERRUPTED_TEXT in texts, texts
        assert "oi" in texts, texts
    finally:
        await boot.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("loaded_before", [False, True])
async def test_reattach_replay_does_not_duplicate_phone_message(make_env, loaded_before):
    env = make_env()
    sid = env.add_old_session()
    # While the backend was down the phone sent a message; the CLI wrote it to the file.
    env.fake.messages[sid].append(user_entry("do celular", sid, uuid="phone-1"))
    env.manager.get(sid).save(
        remote_control=True, remote_control_bridge="cse_1", spawn_version=1
    )
    boot = second_manager(env)
    try:
        session = boot.get(sid)
        if loaded_before:
            # The history was read before the reattach (not live): the replayed uuid is not
            # among the ones remembered, so only the item's own id can join the two.
            await session.ensure_history()
        assert await session.reattach(SimpleNamespace(id="c1", ack=0, init=None))
        client = env.factory.clients[-1]
        # The agentd replays what the old backend never acknowledged.
        client.push([remote_user_message("do celular", message_uuid="phone-1")])
        await asyncio.sleep(0.2)

        texts = [getattr(item, "text", None) for item in session.builder.items]
        assert texts.count("do celular") == 1, texts
    finally:
        await boot.shutdown()


@pytest.mark.anyio
async def test_history_user_items_take_the_entry_uuid(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.fake.messages[sid] = [
        user_entry("um", sid, uuid="u-1"),
        user_entry("dois", sid, uuid="u-2"),
    ]

    snapshot = await env.manager.open(sid)

    assert [item["id"] for item in snapshot["items"]] == ["user-u-1", "user-u-2"]
