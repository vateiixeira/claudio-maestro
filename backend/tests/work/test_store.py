"""Durable work metadata; no SDK or real conversations are involved."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict

import pytest

from claudio_maestro import db
from claudio_maestro.work import store


@pytest.fixture
def world(tmp_path):
    path = tmp_path / 'work.db'
    with closing(db.connect(path)) as conn:
        db.migrate(conn)
        for project_id in (1, 2):
            conn.execute('INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)',
                         (project_id, f'p{project_id}', f'/p{project_id}', '#fff', project_id, 0))
        for sid, project, specialist in [('s1', 1, None), ('s2', 1, None), ('other', 2, None)]:
            conn.execute('INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at, agent_id) VALUES (?, ?, ?, ?, 0, 0, ?)',
                         (sid, project, f'/p{project}', 'session', specialist))
        yield conn, path


def create(conn, **kwargs):
    return store.create_item(conn, project_id=1, title='Investigar issue', now=10, **kwargs)[0]


def test_source_identity_is_not_title_and_includes_every_namespace(world):
    conn, _ = world
    item, created = store.create_item(conn, project_id=1, title='Uma issue', source='kbgen',
        source_instance='local', source_project='body', external_id='50', now=10)
    duplicate, new = store.create_item(conn, project_id=1, title='Novo título não apaga original', source='kbgen',
        source_instance='local', source_project='body', external_id='50', now=20)
    assert created and not new and duplicate == item
    distinct = [store.create_item(conn, project_id=1, title='Uma issue', source=source,
        source_instance=instance, source_project=project, external_id='50', now=20)[0].id
        for source, instance, project in [('sentry', 'local', 'body'), ('kbgen', 'remote', 'body'), ('kbgen', 'local', 'pay')]]
    assert len(set([item.id, *distinct])) == 4
    assert len(store.list_events(conn, item.id)) == 1


def test_concurrent_collectors_get_same_canonical_item(world):
    _, path = world
    def collect(_):
        with closing(db.connect(path)) as connection:
            return store.create_item(connection, project_id=1, title='Issue', source='sentry',
                source_instance='org', source_project='api', external_id='ERR-1', now=10)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(collect, range(4)))
    assert len({item.id for item, _ in results}) == 1
    assert sum(created for _, created in results) == 1


def test_manual_tasks_with_same_title_are_distinct(world):
    conn, _ = world
    assert create(conn).id != create(conn).id


def test_revision_conflict_does_not_overwrite_or_emit_event(world):
    conn, _ = world
    item = create(conn)
    changed = store.update_item(conn, item.id, expected_revision=item.revision, now=11,
        title='Investigar websocket', status='ready', actor='user')
    assert changed.revision == item.revision + 1
    with pytest.raises(store.WorkConflictError):
        store.update_item(conn, item.id, expected_revision=item.revision, now=12, title='Stale')
    assert store.get_item(conn, item.id) == changed
    events = store.list_events(conn, item.id)
    assert len(events) == 2 and events[-1].actor == 'user'
    assert events[-1].revision == changed.revision


def test_invalid_project_and_parent_are_rejected(world):
    conn, _ = world
    with pytest.raises(store.WorkValidationError):
        store.create_item(conn, project_id=999, title='Invalid', now=10)
    other, _ = store.create_item(conn, project_id=2, title='Other', now=10)
    with pytest.raises(store.WorkValidationError):
        create(conn, parent_id=other.id)


def test_claim_binds_session_and_resources_atomically(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision,
        session_id='s1', resources=['checkout:/p1', 'database:testcase'], now=11)
    assert attempt.state == 'starting' and attempt.session_id == 's1'
    assert store.get_item(conn, item.id).status == 'active'
    assert store.resource_claims(conn, attempt.id) == ['checkout:/p1', 'database:testcase']
    other = create(conn, status='ready')
    with pytest.raises(store.WorkConflictError):
        store.claim_attempt(conn, other.id, expected_revision=other.revision,
            session_id='s2', resources=['database:testcase', 'another'], now=12)
    assert store.list_attempts(conn, other.id) == []
    assert store.get_item(conn, other.id) == other
    assert conn.execute("SELECT 1 FROM work_resource_claims WHERE resource = 'another'").fetchone() is None


@pytest.mark.parametrize('session_id', ['other', 'missing'])
def test_claim_refuses_session_from_another_project(world, session_id):
    conn, _ = world
    item = create(conn, status='ready')
    with pytest.raises(store.WorkValidationError):
        store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id=session_id, now=11)
    assert store.get_item(conn, item.id) == item


def test_claim_refuses_legacy_specialist_session(world):
    conn, _ = world
    conn.execute("INSERT INTO specialists (id, slug, name, project_id, created_at, updated_at) VALUES (1, 'old', 'Old', 1, 0, 0)")
    conn.execute("UPDATE sessions SET agent_id = 1 WHERE session_id = 's1'")
    item = create(conn, status='ready')
    with pytest.raises(store.WorkValidationError):
        store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=11)


def test_same_issue_cannot_have_two_active_attempts_even_after_permission_wait(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_running(conn, attempt.id, now=13)
    store.mark_waiting(conn, attempt.id, now=14)
    current = store.get_item(conn, item.id)
    with pytest.raises(store.WorkConflictError):
        store.claim_attempt(conn, item.id, expected_revision=current.revision, session_id='s2', now=15)


def test_uncertain_delivery_survives_reconnect_and_cannot_be_replayed(world):
    conn, path = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision,
        session_id='s1', resources=['checkout:/p1'], now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_uncertain(conn, attempt.id, now=13)
    with closing(db.connect(path)) as connection:
        assert store.get_attempt(connection, attempt.id).state == 'uncertain'
        assert store.resource_claims(connection, attempt.id) == ['checkout:/p1']
        with pytest.raises(store.WorkConflictError):
            store.mark_dispatching(connection, attempt.id, now=14)
        with pytest.raises(store.WorkConflictError):
            store.restore_unsent(connection, attempt.id, now=14)


def test_confirmed_unsent_can_retry_without_new_attempt(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.restore_unsent(conn, attempt.id, now=13)
    assert store.mark_dispatching(conn, attempt.id, now=14).state == 'dispatching'


def test_finish_persists_result_event_and_keeps_resource_until_proven_turn_end(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision,
        session_id='s1', resources=['checkout:/p1'], now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_running(conn, attempt.id, now=13)
    with pytest.raises(store.WorkConflictError):
        store.finish_attempt(conn, attempt.id, outcome='succeeded', result_kind='investigation',
            result_ref='result.json', now=14, turn_ended=False)
    finished, current = store.finish_attempt(conn, attempt.id, outcome='succeeded', result_kind='investigation',
        result_ref='result.json', now=15, turn_ended=True)
    assert current and finished.result_ref == 'result.json'
    assert store.get_item(conn, item.id).status == 'review'
    assert store.resource_claims(conn, attempt.id) == []
    event = store.list_events(conn, item.id)[-1]
    assert event.kind == 'attempt_finished' and event.attempt_id == attempt.id and event.delivered_at is None
    assert event.data['result_kind'] == 'investigation'
    assert store.ack_event(conn, event.id, now=16)
    assert not store.ack_event(conn, event.id, now=17)
    assert store.list_events(conn, item.id)[-1].delivered_at == 16


def test_result_of_stale_revision_is_kept_but_not_accepted_as_current(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_running(conn, attempt.id, now=13)
    active = store.get_item(conn, item.id)
    store.update_item(conn, item.id, expected_revision=active.revision, source_revision='new', now=14)
    finished, current = store.finish_attempt(conn, attempt.id, outcome='succeeded', result_kind='implementation',
        result_ref='patch.json', now=15, turn_ended=True)
    assert not current and finished.result_ref == 'patch.json'
    assert store.get_item(conn, item.id).status == 'ready'
    assert store.list_events(conn, item.id)[-1].data['current_revision'] is False


def test_audit_event_failure_rolls_back_the_whole_transition(world):
    conn, _ = world
    item = create(conn)
    conn.execute("CREATE TRIGGER reject_event BEFORE INSERT ON work_events BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
    with pytest.raises(Exception, match='disk failure'):
        store.update_item(conn, item.id, expected_revision=item.revision, status='ready', now=11)
    assert store.get_item(conn, item.id) == item


def test_filtering_and_metadata_have_no_implicit_specialist_policy(world):
    conn, _ = world
    first = create(conn)
    create(conn, status='ready')
    assert [x.id for x in store.list_items(conn, project_id=1, status='backlog')] == [first.id]
    assert 'specialist_id' not in asdict(first)
    assert 'denied_tools' not in asdict(first)


def test_dependencies_reject_cycles(world):
    conn, _ = world
    a, b, c = create(conn), create(conn), create(conn)
    store.add_dependency(conn, b.id, a.id, now=11)
    store.add_dependency(conn, c.id, b.id, now=12)
    with pytest.raises(store.WorkConflictError):
        store.add_dependency(conn, a.id, c.id, now=13)
    assert store.dependencies(conn, a.id) == []
    assert store.dependencies(conn, c.id) == [b.id]
    ready = store.update_item(conn, b.id, expected_revision=store.get_item(conn, b.id).revision,
        status='ready', now=14)
    with pytest.raises(store.WorkConflictError):
        store.claim_attempt(conn, b.id, expected_revision=ready.revision, session_id='s1', now=15)


def test_result_can_be_recorded_inside_turn_without_releasing_claims(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision,
        session_id='s1', resources=['checkout:/p1'], now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_running(conn, attempt.id, now=13)
    recorded = store.record_result(conn, attempt.id, result_kind='implementation', result_ref='patch.json', now=14)
    assert recorded.state == 'running' and recorded.result_ref == 'patch.json'
    assert store.resource_claims(conn, attempt.id) == ['checkout:/p1']
    assert store.get_item(conn, item.id).status == 'active'
    assert store.list_events(conn, item.id)[-1].kind == 'attempt_result_recorded'


def test_coordinator_is_persistent_per_project_and_not_an_attempt(world):
    conn, _ = world
    assert store.bind_coordinator(conn, 1, 's1', now=10) == 's1'
    assert store.bind_coordinator(conn, 1, 's2', now=11) == 's1'
    assert store.coordinator_session(conn, 1) == 's1'
    item = create(conn, status='ready')
    with pytest.raises(store.WorkValidationError):
        store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=12)


def test_review_uses_an_independent_session(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_running(conn, attempt.id, now=13)
    store.finish_attempt(conn, attempt.id, outcome='succeeded', result_kind='implementation',
        result_ref='patch.json', now=14, turn_ended=True)
    item = store.get_item(conn, item.id)
    with pytest.raises(store.WorkValidationError):
        store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', role='reviewer', now=15)
    review = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s2', role='reviewer', now=16)
    assert review.role == 'reviewer'


def test_wait_and_resume_update_task_without_invalidating_same_attempt(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_running(conn, attempt.id, now=13)
    store.mark_waiting(conn, attempt.id, now=14)
    waiting = store.get_item(conn, item.id)
    assert waiting.status == 'waiting' and waiting.revision == attempt.work_revision
    store.mark_running(conn, attempt.id, now=15)
    assert store.get_item(conn, item.id).status == 'active'


def test_repeated_same_result_receipt_is_idempotent(world):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_running(conn, attempt.id, now=13)
    store.record_result(conn, attempt.id, result_kind='implementation', result_ref='patch.json', now=14)
    before = store.list_events(conn, item.id)
    store.record_result(conn, attempt.id, result_kind='implementation', result_ref='patch.json', now=15)
    assert store.list_events(conn, item.id) == before


@pytest.mark.parametrize('reuse_same_item', [False, True])
def test_every_new_attempt_requires_a_fresh_session_even_after_completion(world, reuse_same_item):
    conn, _ = world
    item = create(conn, status='ready')
    attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=11)
    store.mark_dispatching(conn, attempt.id, now=12)
    store.mark_running(conn, attempt.id, now=13)
    store.finish_attempt(conn, attempt.id, outcome='succeeded', result_kind='investigation',
        result_ref='result.json', now=14, turn_ended=True)
    if reuse_same_item:
        current = store.get_item(conn, item.id)
        item = store.update_item(conn, item.id, expected_revision=current.revision, status='ready', now=15)
    else:
        item = create(conn, status='ready')
    with pytest.raises(store.WorkValidationError):
        store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id='s1', now=16)
    assert store.get_item(conn, item.id) == item
    assert len(store.list_attempts(conn, item.id)) == (1 if reuse_same_item else 0)
