"""No real agentd or SDK: a missing reply is not process-death proof."""
import pytest

from claudio_maestro.agent.agentd_client import AgentdClient, AgentdUnavailable
from claudio_maestro.agent.agentd_transport import AgentdTransport

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize('confirmation', [False, True])
async def test_transport_close_requires_confirmed_process_exit(confirmation):
    class FakeAgentd:
        instance_id = 'original-daemon'
        async def kill(self, child_id, *, expected_instance_id=None):
            assert child_id == 'child'
        async def wait_gone(self, child_id, *, require_confirmation=False, expected_instance_id=None):
            assert require_confirmation is True
            return confirmation
    transport = AgentdTransport(FakeAgentd(), session_id='s', attach_id='child')
    if confirmation:
        await transport.kill()
    else:
        with pytest.raises(AgentdUnavailable):
            await transport.kill()


async def test_unavailable_agentd_is_not_a_strict_death_receipt(tmp_path, monkeypatch):
    client = AgentdClient(tmp_path)
    async def unavailable(*args, **kwargs):
        raise AgentdUnavailable('unreachable')
    monkeypatch.setattr(client, 'ensure_running', unavailable)
    assert await client.wait_gone('child', require_confirmation=True) is False
    assert await client.wait_gone('child') is True  # Existing legacy contract.


async def test_new_daemon_empty_list_cannot_prove_old_child_dead(tmp_path, monkeypatch):
    client = AgentdClient(tmp_path, spawn_allowed=False)
    client.instance_id = 'original-daemon-nonce'
    transport = AgentdTransport(client, session_id='s', attach_id='old-child')
    calls = []
    async def reconnect(*args, **kwargs):
        client.instance_id = 'different-daemon-nonce'
    async def call(op, **kwargs):
        calls.append(op)
        return {'ok': True, 'children': [], 'instance_id': 'different-daemon-nonce'}
    monkeypatch.setattr(client, 'ensure_running', reconnect)
    monkeypatch.setattr(client, '_call', call)
    with pytest.raises(AgentdUnavailable):
        await transport.kill()
    assert 'kill' not in calls
    assert await client.wait_gone('old-child', require_confirmation=True,
                                 expected_instance_id='original-daemon-nonce') is False


async def test_daemon_nonce_is_fresh_and_hello_list_agree_without_protocol_bump(tmp_path):
    from claudio_maestro.agentd import PROTOCOL
    from claudio_maestro.agentd.server import Agentd
    first = Agentd(tmp_path / 'first', idle_exit=5, orphan_timeout=5)
    second = Agentd(tmp_path / 'second', idle_exit=5, orphan_timeout=5)
    hello = await first._dispatch(None, {'op': 'hello', 'protocol': PROTOCOL})
    listed = await first._dispatch(None, {'op': 'list'})
    other = await second._dispatch(None, {'op': 'hello', 'protocol': PROTOCOL})
    assert hello['instance_id'] == listed['instance_id']
    assert hello['instance_id'] != other['instance_id']
    assert hello['protocol'] == PROTOCOL


@pytest.mark.parametrize('reply_nonce,proved', [(None, False), ('replacement', False), ('original', True)])
async def test_strict_absence_uses_nonce_in_the_same_list_reply(tmp_path, monkeypatch, reply_nonce, proved):
    client = AgentdClient(tmp_path, spawn_allowed=False)
    client.instance_id = 'original'
    async def connected(*args, **kwargs):
        pass
    async def reply(op, **kwargs):
        assert op == 'list'
        return {'ok': True, 'children': [], **({'instance_id': reply_nonce} if reply_nonce else {})}
    monkeypatch.setattr(client, 'ensure_running', connected)
    monkeypatch.setattr(client, '_call', reply)
    assert await client.wait_gone('child', require_confirmation=True,
                                 expected_instance_id='original') is proved
    children = await client.live_children(expected_instance_id='original')
    assert (children == []) is proved


async def test_reaper_keeps_child_when_exit_is_unconfirmed_then_watch_reaps_real_exit(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from claudio_maestro.agentd.server import Agentd, Child
    server = Agentd(tmp_path, idle_exit=60, orphan_timeout=60)
    proc = SimpleNamespace(returncode=None, pid=12345, stdin=SimpleNamespace(close=lambda: None),
                           send_signal=lambda sig: None, kill=lambda: None)
    child = Child(id='still-live', session_id='s', proc=proc)
    child.terminating = True
    server.children[child.id] = child
    async def no_exit(*args, **kwargs):
        return False
    monkeypatch.setattr(server, '_wait_exit', no_exit)
    original_wait = asyncio.wait_for
    async def drain_timeout(awaitable, *args, **kwargs):
        awaitable.close()
        raise TimeoutError()
    monkeypatch.setattr('claudio_maestro.agentd.server.asyncio.wait_for', drain_timeout)
    await server._reap(child)
    assert child.id in server.children and proc.returncode is None
    monkeypatch.setattr('claudio_maestro.agentd.server.asyncio.wait_for', original_wait)
    proc.returncode = 0
    pump = asyncio.create_task(asyncio.sleep(0))
    child.pumps = {pump}
    await server._watch_exit(child)
    assert child.done.is_set() and child.exit_code == 0
    assert child.id not in server.children
