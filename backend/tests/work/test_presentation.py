"""Presentation follows durable identity and never guesses intent from prose."""
from contextlib import closing
from uuid import uuid4

import pytest
from test_runtime import world  # noqa: F401
from test_sessions import wait_until

from claudio_maestro import db

pytestmark = pytest.mark.anyio


async def waiting(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    return item, attempt


async def test_waiting_continuation_and_proven_queue_blocker(world):
    item, attempt = await waiting(world)
    next_item = await world.delegate(external_id='next')
    page = world.service.work_overview(world.project.id, limit=1)
    assert page['total'] == 2
    assert page['counts']['continuation'] == 1
    assert page['counts']['queued'] == 1
    attention = world.service.item_attention(item.id)
    assert attention['can_continue'] and attention['session_id'] == attempt.session_id
    queue = world.service.item_attention(next_item.id)
    assert queue['queue_reason']['kind'] == 'global_capacity'
    assert queue['queue_reason']['work_item_id'] == item.id
    assert queue['queue_reason']['blocker_title'] == item.title


@pytest.mark.parametrize('guard', ['paused', 'uncertain', 'running', 'terminal', 'permission', 'missing', 'wrong_project', 'deleting', 'result', 'subagents'])
async def test_continuation_is_fail_closed(world, guard):
    item, attempt = await waiting(world)
    session = world.manager.get(attempt.session_id)
    with closing(db.connect(world.db_path)) as conn:
        if guard == 'paused':
            world.service.pause_project(world.project.id)
        elif guard in ('uncertain', 'running', 'terminal'):
            state = {'terminal': 'succeeded'}.get(guard, guard)
            conn.execute('UPDATE work_attempts SET state=? WHERE id=?', (state, attempt.id))
        elif guard == 'permission':
            from unittest.mock import PropertyMock, patch
            with patch.object(type(session), 'pending_permission', new_callable=PropertyMock, return_value={'id': 'tool'}):
                value = world.service.item_attention(item.id)
                assert value['kind'] == 'permission' and not value['can_continue']
            return
        elif guard == 'missing':
            conn.execute('UPDATE work_attempts SET session_id=NULL WHERE id=?', (attempt.id,))
        elif guard == 'wrong_project':
            session.record.project_id = -1
        elif guard == 'deleting':
            conn.execute('INSERT INTO work_project_fences(project_id,fence_id,reason,created_at) VALUES (?,?,?,?)', (world.project.id, str(uuid4()), 'test', 100))
        elif guard == 'result':
            conn.execute("UPDATE work_attempts SET result_ref='result' WHERE id=?", (attempt.id,))
        elif guard == 'subagents':
            session.builder._lapsed.add('child')
    value = world.service.item_attention(item.id)
    assert value['can_continue'] is False
    if guard != 'uncertain':
        assert value['kind'] != 'uncertain'


async def test_origins_are_persisted_exact_session_receipts_only(world):
    item = await world.delegate()
    coordinator = world.service.coordinator(world.project.id)
    world.service.persist_notifications()
    dispatch = str(uuid4())
    with closing(db.connect(world.db_path)) as conn:
        conn.execute('UPDATE work_notifications SET dispatch_id=?', (dispatch,))
    assert world.service.message_origins(coordinator.session_id, [dispatch, 'human-looking-like-notification'])['items'] == [
        {'message_id': dispatch, 'origin': 'automation', 'notification_ids': [1]}]
    assert world.service.message_origins('other-session', [dispatch]) == {'items': []}
    assert world.service.message_origins(coordinator.session_id, ['Avisos automáticos do Maestro']) == {'items': []}
    assert item.id


async def test_unoccupied_queue_has_no_invented_cause(world):
    item = await world.delegate()
    assert world.service.item_attention(item.id)['queue_reason'] is None


async def test_recorded_decision_has_own_kind_and_never_plain_continuation(world):
    item, attempt = await waiting(world)
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("INSERT INTO work_decision_requests(work_item_id,attempt_id,work_revision,dossier_ref,target_ref,request_ref,status,created_at) VALUES (?,?,?,?,?,?,'pending',100)", (item.id, attempt.id, world.item(item.id).revision, 'spec', 'target', 'request'))
    value = world.service.item_attention(item.id)
    assert value['kind'] == 'decision' and not value['can_continue']


async def test_overview_counts_beyond_first_page_and_project_scope(world):
    from test_sessions import make_project

    from claudio_maestro.work import store
    with closing(db.connect(world.db_path)) as conn:
        other = make_project(world.db_path, world.path / 'home' / 'other')
        for index in range(205):
            store.create_item(conn, project_id=world.project.id, title=f'Backlog {index}', now=100)
        store.create_item(conn, project_id=other.id, title='Foreign', now=100)
    page = world.service.work_overview(world.project.id, limit=2, offset=200)
    assert page['total'] == 205 and len(page['items']) == 2
    assert page['counts']['inactive'] == 205
    assert sum(page['counts'].values()) == 205


async def test_dependencies_are_explained_without_claiming_execution(world):
    item = await world.delegate()
    other = await world.delegate(external_id='dependency')
    with closing(db.connect(world.db_path)) as conn:
        conn.execute('INSERT INTO work_dependencies VALUES (?,?,?)', (item.id, other.id, 100))
    value = world.service.item_attention(item.id)
    assert value['kind'] == 'queued'
    assert value['queue_reason'] == {'kind': 'dependency', 'work_item_id': other.id, 'blocker_title': other.title}


async def test_automatic_message_identity_matches_live_snapshot_history_and_reconnect(world):
    from types import SimpleNamespace

    from claudio_maestro.conversation import ConversationBuilder

    coordinator = world.service.coordinator(world.project.id)
    await world.delegate()
    await world.service.wake_coordinators_once()
    sid = coordinator.session_id
    session = world.manager.get(sid)
    with closing(db.connect(world.db_path)) as conn:
        dispatch = conn.execute('SELECT dispatch_id FROM work_notifications LIMIT 1').fetchone()[0]
    expected_id = f'user-{dispatch}'
    live = [entry['data'] for entry in world.recorder.of(sid, 'item.upsert') if entry['data']['type'] == 'user']
    assert live[0]['id'] == expected_id
    assert session.builder.snapshot()[0]['id'] == expected_id
    assert world.service.message_origins(sid, [expected_id])['items'][0]['message_id'] == expected_id
    # The SDK receives exactly that UUID, persisted by its transcript. A new
    # builder uses the real history loader and live reattachment path.
    text = session.builder.items[0].text
    entry = SimpleNamespace(type='user', uuid=dispatch, message={'content': text})
    for reconnect in (False, True):
        restored = ConversationBuilder()
        restored.load_history([entry], live=reconnect)
        restored_id = restored.snapshot()[0]['id']
        assert restored_id == expected_id
        assert world.service.message_origins(sid, [restored_id])['items'][0]['origin'] == 'automation'
    # A human can type exactly the same notification text and retains a fresh ID.
    human_id = ConversationBuilder().add_user_message(text)[0].data['id']
    assert world.service.message_origins(sid, [human_id]) == {'items': []}


async def test_old_continuation_stays_actionable_before_recent_backlog(world):
    from claudio_maestro.work import store

    item, _ = await waiting(world)
    with closing(db.connect(world.db_path)) as conn:
        for index in range(60):
            store.create_item(conn, project_id=world.project.id, title=f'Recent {index}', now=200)
    page = world.service.work_overview(world.project.id, limit=1)
    assert page['counts']['continuation'] == 1 and page['total'] == 61
    assert page['items'][0]['work_item_id'] == item.id
    assert page['items'][0]['can_continue']


async def test_unsent_retry_preserves_origins_for_both_recorded_messages(world, monkeypatch):
    coordinator = world.service.coordinator(world.project.id)
    await world.delegate()
    original = world.manager.send

    async def unsent(session_id, text, images=None, *, dispatch_id=None):
        # ActiveSession records before connect, including proven-unsent turns.
        session = world.manager.get(session_id)
        session.builder.add_user_message(text, message_id=dispatch_id)
        return {'send_started': False, 'state': 'error'}

    monkeypatch.setattr(world.manager, 'send', unsent)
    await world.service.wake_coordinators_once()
    with closing(db.connect(world.db_path)) as conn:
        first = conn.execute('SELECT dispatch_id FROM work_notifications LIMIT 1').fetchone()[0]
    world.service.retry_unsent_notifications(world.project.id)
    world.service.resume_project(world.project.id)
    monkeypatch.setattr(world.manager, 'send', original)
    await world.service.wake_coordinators_once()
    with closing(db.connect(world.db_path)) as conn:
        second = conn.execute('SELECT dispatch_id FROM work_notifications LIMIT 1').fetchone()[0]
    assert first != second
    ids = [f'user-{first}', f'user-{second}']
    origins = world.service.message_origins(coordinator.session_id, ids)['items']
    assert [origin['message_id'] for origin in origins] == ids
    assert origins[0]['notification_ids'] == origins[1]['notification_ids']

    assert world.service.message_origins('other-session', ids) == {'items': []}
    # A fresh service reader has no dependency on the runtime instance or cache.
    from claudio_maestro.work.presentation import PresentationMixin

    reader = PresentationMixin()
    reader.db_path = world.db_path
    assert reader.message_origins(coordinator.session_id, ids) == {'items': origins}


@pytest.mark.parametrize('guard', ['paused', 'deleting'])
async def test_admission_barrier_does_not_claim_running_worker_stopped(world, guard):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    if guard == 'paused':
        world.service.pause_project(world.project.id)
    else:
        with closing(db.connect(world.db_path)) as conn:
            conn.execute('INSERT INTO work_project_fences(project_id,fence_id,reason,created_at) VALUES (?,?,?,?)', (world.project.id, str(uuid4()), 'test', 100))
    value = world.service.item_attention(item.id)
    assert value['attempt_id'] == attempt.id and value['kind'] == 'running'
    assert not value['can_continue']
    assert world.service.work_overview(world.project.id)['counts']['running'] == 1


@pytest.mark.parametrize('kind', ['tool', 'question', 'plan'])
async def test_native_prompt_demands_conversation_action_before_running(world, kind):
    from unittest.mock import PropertyMock, patch

    item, attempt = await waiting(world)
    session = world.manager.get(attempt.session_id)
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("UPDATE work_attempts SET state='running' WHERE id=?", (attempt.id,))
    with patch.object(type(session), 'pending_kind', new_callable=PropertyMock, return_value=kind):
        value = world.service.item_attention(item.id)
        assert value['kind'] == 'permission'
        assert value['session_id'] == attempt.session_id and not value['can_continue']
        assert world.service.work_overview(world.project.id)['counts']['permission'] == 1
