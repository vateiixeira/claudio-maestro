"""Late results must prove the exact host dispatch, never just its session."""
import pytest
from test_pool import world  # noqa: F401
from test_sessions import wait_until

from claudio_maestro.agent.fake import remote_user_message, result_message, text_turn

pytestmark = pytest.mark.anyio


async def uncertain_worker(world, monkeypatch):
    item = await world.delegate()
    original = world.manager.send
    async def uncertain(sid, *args, **kwargs):
        await original(sid, *args, **kwargs)
        await world.service.conclude(sid, result_kind='investigation', summary='Evidência completa', evidence=['app.py:12'])
        return {'send_started': True, 'state': 'error'}
    monkeypatch.setattr(world.manager, 'send', uncertain)
    attempt = await world.service.dispatch_once()
    assert attempt.state == 'uncertain'
    return item, attempt


async def test_same_dispatch_echo_and_late_result_reconcile_without_replay(world, monkeypatch):
    item, attempt = await uncertain_worker(world, monkeypatch)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'succeeded'
    assert len(world.factory.clients) == 1 and len(world.factory.clients[0].sent) == 1
    assert world.item(item.id).status == 'review'


async def test_foreign_user_echo_invalidates_result_receipt(world, monkeypatch):
    world.factory.script = lambda content: [world.pause, remote_user_message('Outra instrução'),
        *text_turn(world.factory.clients[-1].options.session_id, 'fim')]
    _, attempt = await uncertain_worker(world, monkeypatch)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'uncertain'


async def test_injected_result_consumes_token_and_later_result_does_not_reuse_it(world, monkeypatch):
    def script(content):
        sid = world.factory.clients[-1].options.session_id
        injected = result_message(sid)
        injected.origin = {'kind': 'task-notification'}
        return [world.pause, injected, *text_turn(sid, 'resultado seguinte')]
    world.factory.script = script
    _, attempt = await uncertain_worker(world, monkeypatch)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'uncertain'


async def test_late_cto_result_only_confirms_its_matching_outbox_dispatch(world, monkeypatch):
    await world.delegate()
    original = world.manager.send
    async def uncertain(sid, *args, **kwargs):
        await original(sid, *args, **kwargs)
        return {'send_started': True, 'state': 'error'}
    monkeypatch.setattr(world.manager, 'send', uncertain)
    await world.service.wake_coordinators_once()
    notice = world.service.notifications(world.project.id)['items'][0]
    assert notice['dispatch_state'] == 'uncertain'
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(notice['coordinator_session_id']).state == 'idle')
    result = world.service.notifications(world.project.id)['items'][0]
    assert result['dispatch_state'] == 'sent' and result['model_received_at'] is not None
    assert len(world.factory.clients[-1].sent) == 1


async def test_foreign_text_block_echo_invalidates_dispatch(world, monkeypatch):
    from claude_agent_sdk import TextBlock, UserMessage
    world.factory.script = lambda content: [world.pause,
        UserMessage(content=[TextBlock(text='Outra instrução')], uuid='foreign-user'),
        *text_turn(world.factory.clients[-1].options.session_id, 'fim')]
    _, attempt = await uncertain_worker(world, monkeypatch)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'uncertain'


async def test_legitimate_tool_result_keeps_same_dispatch_receipt(world, monkeypatch):
    from claude_agent_sdk import ToolResultBlock, UserMessage
    world.factory.script = lambda content: [world.pause,
        UserMessage(content=[ToolResultBlock(tool_use_id='tool-1', content='saída')], uuid='tool-result'),
        *text_turn(world.factory.clients[-1].options.session_id, 'fim')]
    _, attempt = await uncertain_worker(world, monkeypatch)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'succeeded'


async def test_sdk_streamed_uuid_and_installed_parser_preserve_echo_identity(tmp_path):
    from claude_agent_sdk._internal.message_parser import parse_message
    from test_agent_sdk_client import StubSdkClient, make_options

    from claudio_maestro.agent.sdk_client import SdkAgentClient
    sdk = StubSdkClient()
    adapter = SdkAgentClient(make_options(tmp_path), sdk_client=sdk)
    token = 'aa56e4bc-1be7-493c-8a94-512047151312'
    await adapter.send('Investigar somente esta tarefa', message_id=token)
    envelope = sdk.queries[0][0]
    assert envelope['type'] == 'user' and envelope['uuid'] == token
    echo = parse_message({**envelope, 'session_id': 'test'})
    assert echo.uuid == token and echo.content == 'Investigar somente esta tarefa'


async def test_remote_control_result_cannot_prove_a_managed_dispatch(world, monkeypatch):
    _, attempt = await uncertain_worker(world, monkeypatch)
    world.manager.get(attempt.session_id).record.remote_control = True
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'uncertain'


async def test_successful_send_does_not_accept_foreign_result_as_worker_completion(world):
    from claude_agent_sdk import TextBlock, UserMessage
    world.factory.script = lambda content: [world.pause,
        UserMessage(content=[TextBlock(text='Outra entrada')], uuid='foreign'),
        *text_turn(world.factory.clients[-1].options.session_id, 'resultado estrangeiro')]
    await world.delegate()
    attempt = await world.service.dispatch_once()
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Entrega antes do fim')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'uncertain'


async def test_managed_dispatch_uses_canonical_wire_uuid(world):
    from uuid import UUID
    await world.delegate()
    attempt = await world.service.dispatch_once()
    token = world.service._signals(attempt.id)['dispatch_id']
    assert token == str(UUID(token))


async def test_unreserved_turn_during_close_cannot_reuse_old_positive_receipt(world, monkeypatch):
    await world.delegate()
    attempt = await world.service.dispatch_once()
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Entrega do turno reservado')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    session = world.manager.get(attempt.session_id)
    original = session.close
    async def changed_while_closing(*args, **kwargs):
        await original(*args, **kwargs)
        world.service.on_unreserved_turn(attempt.session_id, None)
    monkeypatch.setattr(session, 'close', changed_while_closing)
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'uncertain'
