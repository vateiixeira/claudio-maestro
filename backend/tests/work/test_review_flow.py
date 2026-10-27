"""Independent reviews, human receipts and CTO delivery use only FakeAgent."""
import json
from contextlib import closing

import pytest
from test_runtime import World
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.work import store

pytestmark = pytest.mark.anyio


@pytest.fixture
async def world(tmp_path, monkeypatch):
    world = World(tmp_path)
    async def capture(project, workspace, **kwargs):
        return {'complete': True, 'digest': 'backend-digest', 'workspace': str(workspace), 'head': 'backend-head'}
    monkeypatch.setattr('claudio_maestro.work.targets.capture_target', capture)
    yield world
    await world.service.shutdown()
    await world.manager.shutdown()


async def deliver(world, *, delivery_type='investigation_complete', result_kind='investigation'):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    await world.service.conclude(attempt.session_id, result_kind=result_kind,
        delivery_type=delivery_type, summary='Rastreamento completo', evidence=['app.py:12'],
        tests=[{'executed': True, 'status': 'passed', 'command': 'pytest', 'output_ref': 'session:tool-1'}])
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    return item, world.attempt(attempt.id)


async def test_independent_review_binds_backend_target_and_transfers_workspace(world):
    item, author = await deliver(world)
    assert world.item(item.id).status == 'review'
    assert world.manager.get(author.session_id).client is None
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, author.id)
    other = await world.delegate(external_id='other')
    reviewer = await world.service.dispatch_once()
    assert reviewer.work_item_id == item.id and reviewer.role == 'reviewer'
    assert reviewer.session_id != author.session_id
    with closing(db.connect(world.db_path)) as conn:
        assert not store.resource_claims(conn, author.id)
        assert store.resource_claims(conn, reviewer.id)
    binding = world.service.reviews(item.id)['items'][0]
    assert binding['author_attempt_id'] == author.id
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'],
        disposition='approve', summary='Aceite e evidências conferidos', evidence=['app.py:12'])
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status == 'done'
    assert world.item(other.id).status == 'ready'
    assert world.manager.get(reviewer.session_id).client is None


async def test_technical_gap_cannot_close_and_worker_cannot_approve(world):
    item, author = await deliver(world, delivery_type='technical_followup')
    binding = world.service.reviews(item.id)['items'][0]
    with pytest.raises(store.WorkValidationError):
        await world.service.submit_review(author.session_id, binding_id=binding['id'], disposition='approve', summary='Auto', evidence=[])
    reviewer = await world.service.dispatch_once()
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'], disposition='approve', summary='Ainda faltam guardas', evidence=['app.py:12'])
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status == 'ready'


async def test_changed_patch_rejects_review(world, monkeypatch):
    item, author = await deliver(world)
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(item.id)['items'][0]
    async def changed(*args, **kwargs):
        return {'complete': True, 'digest': 'different', 'workspace': str(args[1])}
    monkeypatch.setattr('claudio_maestro.work.targets.capture_target', changed)
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'], disposition='approve', summary='Conferido', evidence=['app.py:12'])
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status != 'done'
    assert world.service.reviews(item.id)['items'][0]['status'] == 'stale'


async def test_human_answer_is_durable_idempotent_and_waits_for_turn(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    decision = await world.service.request_decision(author.session_id, question='Remover o arquivo antigo?',
        action='Excluir somente legacy.py', options=['sim', 'não'], evidence=['legacy.py:1'])
    answer = await world.service.answer_decision(decision['id'], expected_revision=decision['revision'], receipt='human-1', answer='não')
    assert answer['status'] == 'answered'
    assert await world.service.answer_decision(decision['id'], expected_revision=decision['revision'], receipt='human-1', answer='não') == answer
    assert world.attempt(author.id).state == 'running'
    assert len(world.attempts(item.id)) == 1
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status == 'ready'
    resume = await world.service.dispatch_once()
    assert resume.id != author.id
    assert 'Excluir somente legacy.py' in str(world.factory.clients[-1].sent)
    assert 'não' in str(world.factory.clients[-1].sent)


async def test_notifications_atomic_dedup_and_uncertain_wakeup_never_replayed(world, monkeypatch):
    item = await world.delegate()
    world.service.persist_notifications()
    first = world.service.notifications(world.project.id)
    assert first['items'] and first['items'][0]['work_item_id'] == item.id
    world.service.persist_notifications()
    assert world.service.notifications(world.project.id) == first
    calls = []
    async def uncertain(*args, **kwargs):
        calls.append(args)
        return {'send_started': True, 'state': 'error'}
    monkeypatch.setattr(world.manager, 'send', uncertain)
    await world.service.wake_coordinators_once()
    await world.service.recover()
    await world.service.wake_coordinators_once()
    assert len(calls) == 1
    assert world.service.notifications(world.project.id)['items'][0]['dispatch_state'] == 'uncertain'
    assert world.service.notifications(world.project.id)['items'][0]['seen_at'] is None


async def test_implementation_requires_executed_tests_and_reading_is_unverified(world):
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await world.service.conclude(author.session_id, result_kind='implementation', summary='Código alterado', evidence=['app.py:1'], tests=['Li os testes'])
    assert world.service.result(author.id)['tests'][0]['status'] == 'unverified'
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(item.id)['items'][0]
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'], disposition='approve', summary='Li o patch', evidence=['app.py:1'])
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status == 'ready'
    next_author = await world.service.dispatch_once()
    assert next_author.role == 'implementer'
    assert next_author.id != author.id


async def test_material_change_expires_human_answer_and_preserves_receipt_history(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    decision = await world.service.request_decision(author.session_id, question='Excluir?', action='Excluir old.py', options=['sim','não'])
    with closing(db.connect(world.db_path)) as conn:
        current = store.get_item(conn, item.id)
        store.update_item(conn, item.id, expected_revision=current.revision, source_revision='v2', now=101)
    with pytest.raises(store.WorkConflictError, match='expirou'):
        await world.service.answer_decision(decision['id'], expected_revision=decision['revision'], receipt='old', answer='sim')
    history = world.service.decisions(item_id=item.id, pending_only=False)['items']
    assert history[0]['status'] == 'expired' and history[0]['answer'] is None
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, author.id)


async def test_notifications_and_ack_rollback_together(world):
    await world.delegate()
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER fail_ack BEFORE UPDATE OF delivered_at ON work_events BEGIN SELECT RAISE(ABORT,'crash'); END")
    with pytest.raises(Exception, match='crash'):
        world.service.persist_notifications()
    assert world.service.notifications(world.project.id)['items'] == []
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_events WHERE delivered_at IS NULL').fetchone()[0] > 0
        conn.execute('DROP TRIGGER fail_ack')
    world.service.persist_notifications()
    assert world.service.notifications(world.project.id)['items']


async def test_copied_runtime_zero_automatic_model_calls_but_feed_visible(world):
    await world.delegate()
    world.service.dispatch_enabled = False
    await world.service.dispatch_once()
    await world.service.wake_coordinators_once()
    assert world.factory.clients == []
    assert world.service.notifications(world.project.id)['items']


async def test_decision_continuation_uncertain_never_replays(world, monkeypatch):
    item = await world.delegate()
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    decision = await world.service.request_decision(author.session_id, question='Remover old.py?', action='Remover somente old.py')
    await world.service.answer_decision(decision['id'], expected_revision=decision['revision'], receipt='r1', answer='não')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    calls = []
    async def uncertain(*args, **kwargs):
        calls.append(args)
        return {'send_started': True, 'state': 'error'}
    monkeypatch.setattr(world.manager, 'send', uncertain)
    attempt = await world.service.dispatch_once()
    assert attempt.state == 'uncertain'
    await world.service.recover()
    await world.service.dispatch_once()
    assert len(calls) == 1
    assert world.service.decisions(item_id=item.id, pending_only=False)['items'][0]['resume_attempt_id'] == attempt.id


async def test_stale_queued_review_cannot_starve_other_projects_or_approve(world):
    item, author = await deliver(world)
    with closing(db.connect(world.db_path)) as conn:
        current = store.get_item(conn, item.id)
        store.update_item(conn, item.id, expected_revision=current.revision, source_revision='v2', now=101)
    await world.service.dispatch_once()
    assert world.service.reviews(item.id)['items'][0]['status'] == 'stale'
    assert world.item(item.id).status != 'done'


async def test_invented_test_reference_is_not_verified_execution(world):
    item, author = await deliver(world, result_kind='implementation', delivery_type='implementation_complete')
    test = world.service.result(author.id)['tests'][0]
    assert test['execution_verified'] is False
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(item.id)['items'][0]
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'], disposition='approve', summary='Alegação insuficiente', evidence=['app.py:12'])
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status != 'done'


async def test_completed_sdk_test_tool_is_verifiable_and_implementation_can_finish(world):
    from claudio_maestro.agent.fake import tool_turn
    world.factory.script = lambda content: tool_turn(world.factory.clients[-1].options.session_id,
        tool_name='Bash', tool_input={'command': 'pytest -q'}, tool_use_id='test-receipt', result_content='8 passed')
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.conclude(author.session_id, result_kind='implementation', summary='Corrigir guarda', evidence=['guard.py:1'],
        tests=[{'executed': True, 'status': 'passed', 'command': 'pytest -q', 'output_ref': 'tool:test-receipt'}])
    assert world.service.result(author.id)['tests'][0]['execution_verified']
    await world.service.reconcile()
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(item.id)['items'][0]
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'], disposition='approve', summary='Patch e recibo conferidos', evidence=['guard.py:1'])
    await world.service.reconcile()
    assert world.item(item.id).status == 'done'


async def test_changed_target_between_human_receipt_and_dispatch_does_not_send(world, monkeypatch):
    item = await world.delegate()
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    decision = await world.service.request_decision(author.session_id, question='Excluir old.py?', action='Excluir somente old.py')
    await world.service.answer_decision(decision['id'], expected_revision=decision['revision'], receipt='human-target', answer='sim')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    async def changed(*args, **kwargs):
        return {'complete': True, 'digest': 'other', 'workspace': str(args[1])}
    monkeypatch.setattr('claudio_maestro.work.targets.capture_target', changed)
    clients = len(world.factory.clients)
    resumed = await world.service.dispatch_once()
    assert resumed.state == 'failed' and len(world.factory.clients) == clients
    assert world.service.decisions(item_id=item.id, pending_only=False)['items'][0]['status'] == 'expired'


async def test_review_failure_keeps_history_without_reusing_author_session(world):
    item, author = await deliver(world)
    reviewer = await world.service.dispatch_once()
    with pytest.raises(store.WorkConflictError):
        await world.service.send_message(author.session_id, 'Editar por fora')
    assert reviewer.session_id != author.session_id
    assert world.manager.get(author.session_id).client is None


async def test_unknown_project_mcp_check_preserves_output_without_certifying_execution(world):
    from claudio_maestro.agent.fake import tool_turn
    world.factory.script = lambda content: tool_turn(world.factory.clients[-1].options.session_id,
        tool_name='mcp__project__check_ci', tool_input={'revision': 'HEAD'}, tool_use_id='ci-receipt', result_content='checks passed')
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.conclude(author.session_id, result_kind='implementation', summary='Corrigir guarda', evidence=['guard.py:1'],
        tests=[{'executed': True, 'status': 'passed', 'command': 'CI HEAD', 'tool_name': 'mcp__project__check_ci', 'check_type': 'ci', 'output_ref': 'tool:ci-receipt'}])
    receipt = world.service.result(author.id)['tests'][0]
    assert receipt['execution_verified'] is False
    assert receipt['status'] == 'unverified' and receipt['declared_status'] == 'passed'
    assert receipt['verification_reason']
    assert receipt['trace']['name'] == 'mcp__project__check_ci'
    assert receipt['trace']['source'] == 'session_tool_result_data'


async def test_review_verdict_and_result_rollback_together(world):
    item, _ = await deliver(world)
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(item.id)['items'][0]
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER fail_verdict BEFORE UPDATE OF disposition ON work_review_bindings BEGIN SELECT RAISE(ABORT,'verdict crash'); END")
    with pytest.raises(Exception, match='verdict crash'):
        await world.service.submit_review(reviewer.session_id, binding_id=binding['id'],
            disposition='approve', summary='Conferido', evidence=['app.py:12'])
    assert world.attempt(reviewer.id).result_ref is None
    with closing(db.connect(world.db_path)) as conn:
        assert not conn.execute("SELECT 1 FROM work_events WHERE attempt_id=? AND kind='attempt_result_recorded'", (reviewer.id,)).fetchone()


async def test_material_input_changed_after_human_answer_never_enters_next_prompt(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    decision = await world.service.request_decision(author.session_id, question='Excluir old.py?', action='Excluir somente old.py')
    await world.service.answer_decision(decision['id'], expected_revision=decision['revision'], receipt='human-input', answer='sim')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    with closing(db.connect(world.db_path)) as conn:
        current = store.get_item(conn, item.id)
        store.update_item(conn, item.id, expected_revision=current.revision, source_revision='changed', now=101)
    await world.service.dispatch_once()
    assert 'human_decision_checkpoint' not in str(world.factory.clients[-1].sent)
    assert world.service.decisions(item_id=item.id, pending_only=False)['items'][0]['status'] == 'expired'


async def test_unknown_review_disposition_cannot_be_recorded_by_conclude(world):
    item, _ = await deliver(world)
    reviewer = await world.service.dispatch_once()
    with pytest.raises(store.WorkValidationError, match='submit_review'):
        await world.service.conclude(reviewer.session_id, result_kind='review', summary='Aprovado', evidence=['app.py:12'])


async def test_input_changed_during_decision_target_check_cannot_send_checkpoint(world, monkeypatch):
    item = await world.delegate()
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    decision = await world.service.request_decision(author.session_id, question='Excluir old.py?', action='Excluir somente old.py')
    await world.service.answer_decision(decision['id'], expected_revision=decision['revision'], receipt='human-race', answer='sim')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    original = world.service._targets_current
    async def change_input(*args):
        with closing(db.connect(world.db_path)) as conn:
            current = store.get_item(conn, item.id)
            store.update_item(conn, item.id, expected_revision=current.revision, source_revision='changed-during-capture', now=101)
        return await original(*args)
    monkeypatch.setattr(world.service, '_targets_current', change_input)
    clients = len(world.factory.clients)
    resumed = await world.service.dispatch_once()
    assert resumed.state == 'failed'
    assert len(world.factory.clients) == clients
    assert world.service.decisions(item_id=item.id, pending_only=False)['items'][0]['status'] == 'expired'


async def test_accepted_cto_send_without_result_is_uncertain_after_restart(world, monkeypatch):
    await world.delegate()
    calls = []
    async def accepted(*args, **kwargs):
        calls.append(args)
        return {'send_started': True, 'state': 'running'}
    monkeypatch.setattr(world.manager, 'send', accepted)
    await world.service.wake_coordinators_once()
    assert world.service.notifications(world.project.id)['items'][0]['dispatch_state'] == 'sent'
    await world.service.recover()
    await world.delegate(external_id='after-restart')
    await world.service.wake_coordinators_once()
    assert len(calls) == 1
    assert world.service.notifications(world.project.id)['items'][0]['dispatch_state'] == 'uncertain'


async def test_cto_error_callback_during_send_cannot_be_overwritten_by_sent(world, monkeypatch):
    await world.delegate()
    async def accepted_after_error(sid, *args, **kwargs):
        world.service.on_session_result(sid, {'is_error': True})
        return {'send_started': True, 'state': 'running'}
    monkeypatch.setattr(world.manager, 'send', accepted_after_error)
    await world.service.wake_coordinators_once()
    assert world.service.notifications(world.project.id)['items'][0]['dispatch_state'] == 'uncertain'


async def test_review_human_answer_returns_to_executor_without_phantom_live_review(world):
    item, author = await deliver(world)
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(item.id)['items'][0]
    decision = await world.service.submit_review(reviewer.session_id, binding_id=binding['id'],
        disposition='ask_human', summary='Confirmar remoção', question='Remover old.py?', action='Remover somente old.py')
    await world.service.answer_decision(decision['id'], expected_revision=decision['revision'], receipt='review-human', answer='não')
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.service.reviews(item.id)['items'][0]['status'] == 'returned'
    resumed = await world.service.dispatch_once()
    assert resumed.role == author.role and resumed.session_id != reviewer.session_id
    assert 'review-human' in str(world.factory.clients[-1].sent)


@pytest.mark.parametrize(('result_kind','delivery_type'), [('implementation','investigation_complete'), ('investigation','implementation_complete')])
async def test_delivery_classification_cannot_disguise_implementation(world, result_kind, delivery_type):
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    with pytest.raises(store.WorkValidationError, match='compatível'):
        await world.service.conclude(author.session_id, result_kind=result_kind, delivery_type=delivery_type,
            summary='Corrigir código', evidence=['app.py:1'])


@pytest.mark.parametrize('tool_name', ['Read', 'Grep', 'Glob', 'WebFetch', 'mcp__files__read_file', 'mcp__search__query'])
async def test_read_and_search_tool_results_are_not_test_execution(world, tool_name):
    from claudio_maestro.agent.fake import tool_turn
    world.factory.script = lambda content: tool_turn(world.factory.clients[-1].options.session_id,
        tool_name=tool_name, tool_input={'file_path': 'tests/test_app.py'}, tool_use_id='read-receipt', result_content='def test_app(): assert True')
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.conclude(author.session_id, result_kind='implementation', summary='Corrigir', evidence=['app.py:1'],
        tests=[{'executed': True, 'status': 'passed', 'command': 'pytest -q', 'output_ref': 'tool:read-receipt'}])
    test = world.service.result(author.id)['tests'][0]
    assert test['execution_verified'] is False
    assert test['status'] == 'unverified' and test['declared_status'] == 'passed'
    assert test['verification_reason']
    assert test['trace']['name'] == tool_name


@pytest.mark.parametrize('details', [{'backgroundTaskId':'bg-1'}, {'status':'running'}, {'interrupted':True}, {'timed_out':True}, {'cancelled':True}])
async def test_nonterminal_bash_does_not_prove_a_passing_test(world, details):
    from claudio_maestro.agent.fake import tool_turn
    world.factory.script = lambda content: tool_turn(world.factory.clients[-1].options.session_id,
        tool_name='Bash', tool_input={'command':'pytest -q'}, tool_use_id='pending-test', result_content='Started test run', tool_use_result=details)
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.conclude(author.session_id, result_kind='implementation', summary='Corrigir', evidence=['app.py:1'],
        tests=[{'executed': True,'status':'passed','command':'pytest -q','output_ref':'tool:pending-test'}])
    assert world.service.result(author.id)['tests'][0]['execution_verified'] is False


async def test_implementer_role_cannot_close_as_analysis_without_execution_evidence(world):
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await world.service.conclude(author.session_id, result_kind='investigation', summary='Código alterado', evidence=['app.py:1'])
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(item.id)['items'][0]
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'], disposition='approve', summary='Conferido', evidence=['app.py:1'])
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status != 'done'


async def test_real_mcp_execution_output_is_preserved_but_unknown_contract_stays_unverified(world):
    from claudio_maestro.agent.fake import tool_turn
    output = {'execution_id':'ci-73','status':'completed','conclusion':'success','command':'pytest -q','exit_code':0,'stdout':'8 passed'}
    world.factory.script = lambda content: tool_turn(world.factory.clients[-1].options.session_id,
        tool_name='mcp__project__execute_tests', tool_input={'command':'pytest -q'}, tool_use_id='external-run',
        result_content=[{'type':'text', 'text':json.dumps(output)}], tool_use_result=output)
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.conclude(author.session_id, result_kind='implementation', summary='Corrigir', evidence=['app.py:1'],
        tests=[{'executed':True,'status':'passed','command':'pytest -q','tool_name':'mcp__project__execute_tests','check_type':'ci','output_ref':'tool:external-run'}])
    receipt = world.service.result(author.id)['tests'][0]
    assert receipt['execution_verified'] is False and receipt['status'] == 'unverified'
    assert 'ci-73' in receipt['trace']['output_excerpt'] and receipt['trace']['output_digest']
    assert 'contrato' in receipt['verification_reason']
