"""Delegated collection publishes closed, compact metadata through captured scope."""
from contextlib import closing

import pytest
from test_runtime import World
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.work import store

pytestmark = pytest.mark.anyio


@pytest.fixture
async def world(tmp_path):
    value = World(tmp_path)
    yield value
    await value.manager.shutdown()


def metadata(id='50', revision='r1', **extra):
    return {'external_id': id, 'title': f'Issue {id}', 'priority': 'normal', 'source_revision': revision,
            'url': f'https://issues.example/{id}', **extra}


async def collector(world):
    collection = world.service.create_collection(project_id=world.project.id, source='kbgen',
        source_instance='local', source_project='app', query='status:open')
    await world.service.dispatch_once()
    attempt = world.attempts(collection['work_item_id'])[0]
    await world.pause.reached.wait()
    return collection, attempt


async def test_collection_is_separate_and_25_backlog_items_do_not_consume_executor_quota(world):
    collection, attempt = await collector(world)
    receipt = await world.service.publish_collection(attempt.session_id, items=[metadata(str(i)) for i in range(25)], cursor='', next_cursor=None)
    assert receipt['total'] == 25
    records = world.service.collection(collection['id'])
    assert len(records['items']) == 25
    assert all(world.item(row['work_item_id']).status == 'backlog' for row in records['items'])
    assert 'description' not in str(world.service.list_work(world.service.coordinator(world.project.id).session_id))
    assert world.factory.clients[-1].options.specialist_id is None if hasattr(world.factory.clients[-1].options, 'specialist_id') else True
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(collection['work_item_id']).status == 'done'
    for row in records['items']:
        world.service.start(row['work_item_id'], expected_revision=world.item(row['work_item_id']).revision)
    assert sum(world.item(row['work_item_id']).status == 'ready' for row in records['items']) == 25


async def test_closed_metadata_scope_and_empty_final_receipt(world):
    collection, attempt = await collector(world)
    for extra in ({'description': 'private body'}, {'source': 'sentry'}, {'stack': 'trace'}):
        with pytest.raises(store.WorkValidationError):
            await world.service.publish_collection(attempt.session_id, items=[metadata(**extra)], cursor='', next_cursor=None)
    cto = world.service.coordinator(world.project.id)
    with pytest.raises(store.WorkValidationError):
        await world.service.publish_collection(cto.session_id, items=[], cursor='', next_cursor=None)
    receipt = await world.service.publish_collection(attempt.session_id, items=[], cursor='', next_cursor=None)
    assert receipt['total'] == 0
    assert world.service.collection(collection['id'])['finalized']
    assert world.item(collection['work_item_id']).status == 'active'


async def test_ingest_atomic_dedup_revision_and_reevaluation(world, monkeypatch):
    collection, attempt = await collector(world)
    original = world.service.files.write
    def broken(value):
        raise OSError('disk full')
    monkeypatch.setattr(world.service.files, 'write', broken)
    with pytest.raises(OSError):
        await world.service.publish_collection(attempt.session_id, items=[metadata()], cursor='', next_cursor='next')
    assert world.service.collection(collection['id'])['items'] == []
    monkeypatch.setattr(world.service.files, 'write', original)
    await world.service.publish_collection(attempt.session_id, items=[metadata(), metadata('55')], cursor='', next_cursor='next')
    first = world.service.collection(collection['id'])['items'][0]['work_item_id']
    before = world.item(first)
    await world.service.publish_collection(attempt.session_id, items=[metadata()], cursor='next', next_cursor='last')
    assert world.item(first).revision == before.revision
    await world.service.publish_collection(attempt.session_id, items=[metadata(revision='r2')], cursor='last', next_cursor=None)
    assert world.item(first).source_revision == 'r2'
    cto = world.service.coordinator(world.project.id)
    updated = world.service.reevaluate(cto.session_id, first, expected_revision=world.item(first).revision, reason='Código mudou', code_reference='commit:abc')
    assert updated.id == first and updated.source_revision == 'r2'
    with pytest.raises(store.WorkConflictError):
        world.service.reevaluate(cto.session_id, first, expected_revision=before.revision, reason='Velho', code_reference='commit:old')


async def test_collector_cannot_replace_receipt_with_freeform_conclusion(world):
    _, attempt = await collector(world)
    with pytest.raises(store.WorkValidationError):
        await world.service.conclude(attempt.session_id, result_kind='investigation', summary='falsa coleta completa')


async def test_collector_context_and_tools_are_normal_and_scope_captured(world):
    from claudio_maestro.work.tools import build_tools

    _, attempt = await collector(world)
    options = world.factory.clients[-1].options
    assert options.setting_sources is None and options.settings is None
    context = world.service.session_context(world.manager.find_record(attempt.session_id))
    assert 'somente pela coleta' in context.system_prompt_append
    assert 'Leia a issue completa' not in context.system_prompt_append
    tools = {tool.name: tool for tool in build_tools(world.service, attempt.session_id)}
    properties = tools['publish_collection'].input_schema['properties']
    assert 'project_id' not in properties and 'source' not in properties
    entry = properties['items']['items']
    assert entry['additionalProperties'] is False and 'description' not in entry['properties']
    assert properties['items']['maxItems'] == 25
    with pytest.raises(store.WorkValidationError):
        await world.service.collect_source(attempt.session_id, source='sentry', source_instance='x', source_project='x')


async def test_cursor_idempotency_bounds_and_failed_receipt_roll_back_entire_page(world, monkeypatch):
    _, attempt = await collector(world)
    for bad in ('javascript:alert(1)', 'https://user:pass@issues.example/1'):
        with pytest.raises(store.WorkValidationError):
            await world.service.publish_collection(attempt.session_id, items=[metadata(url=bad)], cursor='', next_cursor=None)
    with pytest.raises(store.WorkValidationError):
        await world.service.publish_collection(attempt.session_id, items=[metadata(str(i)) for i in range(26)], cursor='', next_cursor=None)
    with pytest.raises(store.WorkConflictError):
        await world.service.publish_collection(attempt.session_id, items=[], cursor='stale', next_cursor=None)
    write = world.service.files.write
    def fail_receipt(value):
        if 'collection_id' in value:
            raise OSError('receipt full')
        return write(value)
    monkeypatch.setattr(world.service.files, 'write', fail_receipt)
    with pytest.raises(OSError):
        await world.service.publish_collection(attempt.session_id, items=[metadata()], cursor='', next_cursor='next')
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_items WHERE source='kbgen'").fetchone()[0] == 0
    monkeypatch.setattr(world.service.files, 'write', write)
    a = await world.service.publish_collection(attempt.session_id, items=[metadata()], cursor='', next_cursor='next')
    b = await world.service.publish_collection(attempt.session_id, items=[metadata()], cursor='', next_cursor='next')
    assert a == b
    with pytest.raises(store.WorkConflictError):
        await world.service.publish_collection(attempt.session_id, items=[metadata('51')], cursor='', next_cursor='next')
    with pytest.raises(store.WorkValidationError):
        await world.service.publish_collection(attempt.session_id, items=[], cursor='next', next_cursor='next')


async def test_code_reevaluation_preserves_history_and_one_active_executor(world):
    item = await world.delegate(source='kbgen', source_instance='local', source_project='app', external_id='50', source_revision='same')
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='parecer antigo', evidence=['old.py:10'])
    cto = world.service.coordinator(world.project.id)
    changed = world.service.reevaluate(cto.session_id, item.id, expected_revision=world.item(item.id).revision, reason='Corrigir guarda', code_reference='commit:new')
    assert changed.source_revision == 'same'
    with pytest.raises(store.WorkConflictError):
        world.service.start_backlog(cto.session_id, item.id, expected_revision=changed.revision)
    assert world.service.result(attempt.id)['summary'] == 'parecer antigo'
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_input_history WHERE work_item_id=?', (item.id,)).fetchone()[0] == 1
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status != 'done'
    assert len(world.attempts(item.id)) == 1


async def test_compact_queries_exclude_result_bodies_and_paginate(world):
    cto = world.service.coordinator(world.project.id)
    first = await world.delegate()
    world.service.create_item(project_id=world.project.id, title='Outra', objective='Objetivo secreto', ready=False)
    await world.service.dispatch_once()
    attempt = world.attempts(first.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Corpo privado', evidence=['Evidência privada'])
    assert 'Corpo privado' not in str(world.service.get_work(cto.session_id, first.id))
    page = world.service.list_work(cto.session_id, limit=1, offset=1)
    assert page['total'] == 2 and len(page['items']) == 1 and page['offset'] == 1


async def test_final_receipt_file_is_required_even_after_positive_sdk_result(world):
    _, attempt = await collector(world)
    await world.service.publish_collection(attempt.session_id, items=[], cursor='', next_cursor=None)
    result = world.service.result(attempt.id)
    (world.service.files.root / result['collection_receipt']).unlink()
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'failed'
    assert world.item(attempt.work_item_id).status == 'blocked'


async def test_collection_creation_and_second_ingested_item_failure_roll_back(world, monkeypatch):
    write = world.service.files.write
    monkeypatch.setattr(world.service.files, 'write', lambda value: (_ for _ in ()).throw(OSError('full')))
    with pytest.raises(OSError):
        world.service.create_collection(project_id=world.project.id, source='kbgen', source_instance='local', source_project='app')
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_items').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM work_collections').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM work_project_modes').fetchone()[0] == 0
    monkeypatch.setattr(world.service.files, 'write', write)
    collection, attempt = await collector(world)
    def fail_second(value):
        if value.get('external_id') == '55':
            raise OSError('full second')
        return write(value)
    monkeypatch.setattr(world.service.files, 'write', fail_second)
    with pytest.raises(OSError):
        await world.service.publish_collection(attempt.session_id, items=[metadata(), metadata('55')], cursor='', next_cursor=None)
    assert world.service.collection(collection['id'])['items'] == []
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_items WHERE source='kbgen'").fetchone()[0] == 0


async def test_delivery_category_is_explicit_and_does_not_finish_technical_gap(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Falta rastrear frontend',
        delivery_type='technical_followup', next_action='Rastrear guardas')
    assert world.service.result(attempt.id)['delivery_type'] == 'technical_followup'
    with pytest.raises(store.WorkValidationError):
        await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Inválido', delivery_type='all_done')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.item(item.id).status == 'review'


async def test_collection_snapshot_does_not_overwrite_reevaluated_input(world):
    item = world.service.create_item(project_id=world.project.id, title='Issue 50', objective='Entrada antiga',
        source='kbgen', source_instance='local', source_project='app', external_id='50', source_revision='r1', ready=False)
    _, attempt = await collector(world)
    cto = world.service.coordinator(world.project.id)
    updated = world.service.reevaluate(cto.session_id, item.id, expected_revision=item.revision, reason='Código novo', code_reference='commit:new')
    with pytest.raises(store.WorkConflictError):
        await world.service.publish_collection(attempt.session_id, items=[metadata(revision='r2')], cursor='', next_cursor=None)
    assert world.item(item.id).revision == updated.revision
    assert world.service.dossier(item.id)['reevaluation']['code_reference'] == 'commit:new'


async def test_collector_can_inspect_only_its_scoped_metadata_for_cas(world):
    item = world.service.create_item(project_id=world.project.id, title='Issue 50', objective='PRIVATE BODY',
        source='kbgen', source_instance='local', source_project='app', external_id='50', source_revision='r1', ready=False)
    world.service.create_item(project_id=world.project.id, title='Other instance', objective='OTHER PRIVATE',
        source='kbgen', source_instance='foreign', source_project='app', external_id='99', source_revision='r1', ready=False)
    _, attempt = await collector(world)
    value = world.service.source_metadata(attempt.session_id, '50')
    assert value['revision'] == item.revision and 'PRIVATE' not in str(value)
    assert world.service.source_metadata(attempt.session_id, '99') is None
    with pytest.raises(store.WorkValidationError):
        world.service.source_metadata(world.service.coordinator(world.project.id).session_id, '50')


@pytest.mark.parametrize('terminal', [None, 'error_max_turns'])
async def test_explicit_retry_of_published_eof_binds_receipt_to_current_attempt(world, terminal):
    from claudio_maestro.agent.fake import PauseStep

    collection, first = await collector(world)
    original = await world.service.publish_collection(first.session_id, items=[metadata()], cursor='', next_cursor=None)
    issue_id = world.service.collection(collection['id'])['items'][0]['work_item_id']
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(first.session_id).state == 'idle')
    world.service.on_session_result(first.session_id, {'is_error': True, 'terminal_reason': terminal})
    await world.service.reconcile()
    assert world.attempt(first.id).state == 'failed'
    cto = world.service.coordinator(world.project.id)
    issue = world.service.reevaluate(cto.session_id, issue_id, expected_revision=world.item(issue_id).revision,
        reason='Código novo depois da publicação', code_reference='commit:after-eof')
    world.service.resume_project(world.project.id)
    world.service.start(first.work_item_id, expected_revision=world.item(first.work_item_id).revision)
    world.pause = PauseStep()
    await world.service.dispatch_once()
    second = world.attempts(first.work_item_id)[-1]
    await world.pause.reached.wait()
    replay = await world.service.publish_collection(second.session_id, items=[metadata()], cursor='', next_cursor=None)
    assert replay == original
    assert world.attempt(second.id).result_ref is not None
    assert world.attempt(first.id).state == 'failed'
    assert world.item(issue_id).revision == issue.revision
    assert world.service.dossier(issue_id)['reevaluation']['code_reference'] == 'commit:after-eof'
    await world.service.reconcile()
    assert world.attempt(second.id).state == 'running'
    with closing(db.connect(world.db_path)) as conn:
        before = conn.execute("SELECT COUNT(*) FROM work_events WHERE attempt_id=? AND kind='collection_published'", (second.id,)).fetchone()[0]
    await world.service.publish_collection(second.session_id, items=[metadata()], cursor='', next_cursor=None)
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_events WHERE attempt_id=? AND kind='collection_published'", (second.id,)).fetchone()[0] == before
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(second.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(second.id).state == 'succeeded'
    assert world.item(first.work_item_id).status == 'done'


@pytest.mark.parametrize('damage', ['missing', 'wrong_total', 'wrong_type', 'wrong_collection'])
async def test_eof_replay_requires_valid_private_canonical_receipt(world, damage):
    import json

    _, attempt = await collector(world)
    await world.service.publish_collection(attempt.session_id, items=[], cursor='', next_cursor=None)
    result = world.service.result(attempt.id)
    path = world.service.files.root / result['collection_receipt']
    before = world.attempt(attempt.id).result_ref
    if damage == 'missing':
        path.unlink()
    else:
        receipt = json.loads(path.read_text())
        if damage == 'wrong_total':
            receipt['total'] = 1
        elif damage == 'wrong_type':
            receipt['total'] = False
        else:
            receipt['collection_id'] = 'foreign'
        path.write_text(json.dumps(receipt))
    with pytest.raises((OSError, store.WorkValidationError)):
        await world.service.publish_collection(attempt.session_id, items=[], cursor='', next_cursor=None)
    assert world.attempt(attempt.id).result_ref == before


async def test_retry_cannot_bind_missing_eof_receipt_to_new_attempt(world):
    from claudio_maestro.agent.fake import PauseStep

    _, first = await collector(world)
    await world.service.publish_collection(first.session_id, items=[], cursor='', next_cursor=None)
    ref = world.service.result(first.id)['collection_receipt']
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(first.session_id).state == 'idle')
    world.service.on_session_result(first.session_id, {'is_error': True})
    await world.service.reconcile()
    world.service.start(first.work_item_id, expected_revision=world.item(first.work_item_id).revision)
    world.pause = PauseStep()
    await world.service.dispatch_once()
    second = world.attempts(first.work_item_id)[-1]
    await world.pause.reached.wait()
    (world.service.files.root / ref).unlink()
    with pytest.raises(OSError):
        await world.service.publish_collection(second.session_id, items=[], cursor='', next_cursor=None)
    assert world.attempt(second.id).result_ref is None
    assert world.attempt(first.id).state == 'failed'
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_events WHERE attempt_id=? AND kind='collection_published'", (second.id,)).fetchone()[0] == 0
