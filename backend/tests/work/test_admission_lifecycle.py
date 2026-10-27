"""A refused reservation never leaves a normal session in the catalog."""
import asyncio
import sqlite3
from contextlib import closing

import pytest
from test_review_flow import deliver
from test_runtime import World

from claudio_maestro import db
from claudio_maestro.work import store

pytestmark = pytest.mark.anyio


@pytest.fixture
async def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    async def capture(project, workspace, **kwargs):
        return {'complete': True, 'digest': 'backend-digest', 'workspace': str(workspace), 'head': 'h'}
    monkeypatch.setattr('claudio_maestro.work.targets.capture_target', capture)
    yield w
    await w.service.shutdown()
    await w.manager.shutdown()


def count(world):
    with closing(db.connect(world.db_path)) as conn:
        return conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]


async def test_pending_dependency_never_accumulates_normal_sessions(world, monkeypatch):
    item = await world.delegate()
    dependency = world.service.create_item(project_id=world.project.id, title='Dependência', objective='Aguardar', ready=False)
    with closing(db.connect(world.db_path)) as conn:
        store.add_dependency(conn, item.id, dependency.id, now=100)
    def forbidden(*args, **kwargs):
        pytest.fail('Uma dependência pendente não deve nem preparar outra sessão.')
    monkeypatch.setattr(world.manager, 'create_session_in_transaction', forbidden)
    before = count(world)
    for _ in range(3):
        assert await world.service.dispatch_once() is None
        assert count(world) == before
    assert not world.attempts(item.id)


@pytest.mark.parametrize('failure', ['conflict', 'stale', 'sql', 'cancel'])
async def test_worker_failed_claim_rolls_back_new_session(world, monkeypatch, failure):
    item = await world.delegate()
    original = store.claim_attempt_in_transaction
    def rejected(conn, *args, **kwargs):
        if failure == 'conflict':
            raise store.WorkConflictError('O recurso foi reservado durante a admissão.')
        if failure == 'stale':
            kwargs['expected_revision'] -= 1
            return original(conn, *args, **kwargs)
        if failure == 'sql':
            raise sqlite3.OperationalError('database failed')
        raise asyncio.CancelledError()
    monkeypatch.setattr(store, 'claim_attempt_in_transaction', rejected)
    before = count(world)
    for _ in range(2):
        if failure in ('conflict', 'stale'):
            assert await world.service.dispatch_once() is None
        else:
            with pytest.raises(sqlite3.OperationalError if failure == 'sql' else asyncio.CancelledError):
                await world.service.dispatch_once()
        assert count(world) == before
    assert not world.attempts(item.id)


@pytest.mark.parametrize('failure', ['conflict', 'sql', 'cancel'])
async def test_failed_review_claim_never_accumulates_reviewer_sessions(world, monkeypatch, failure):
    item, _ = await deliver(world)
    assert world.item(item.id).status == 'review'
    def rejected(*args, **kwargs):
        if failure == 'sql':
            raise sqlite3.OperationalError('database failed')
        if failure == 'cancel':
            raise asyncio.CancelledError()
        raise store.WorkConflictError('Recurso de revisão ocupado.')
    monkeypatch.setattr(store, 'claim_attempt_in_transaction', rejected)
    before = count(world)
    for _ in range(2):
        if failure == 'conflict':
            assert await world.service.dispatch_once() is None
        else:
            with pytest.raises(sqlite3.OperationalError if failure == 'sql' else asyncio.CancelledError):
                await world.service.dispatch_once()
        assert count(world) == before
    assert len(world.attempts(item.id)) == 1


async def test_committed_attempt_session_is_retained_when_sdk_entry_is_cancelled(world, monkeypatch):
    item = await world.delegate()
    async def cancelled(*args):
        raise asyncio.CancelledError()
    monkeypatch.setattr(world.service, '_send_attempt', cancelled)
    before = count(world)
    with pytest.raises(asyncio.CancelledError):
        await world.service.dispatch_once()
    assert count(world) == before + 1
    attempts = world.attempts(item.id)
    assert len(attempts) == 1
    assert world.manager.find_record(attempts[0].session_id).project_id == world.project.id


async def test_session_create_transaction_rollback_and_wrapper_defaults_match(world):
    before = count(world)
    with pytest.raises(RuntimeError, match='rollback'):
        with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
            world.manager.create_session_in_transaction(conn, world.project)
            raise RuntimeError('rollback')
    assert count(world) == before
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        transactional = world.manager.create_session_in_transaction(conn, world.project)
    normal = world.manager.create_session(world.project)
    assert transactional.session_id != normal.session_id
    for field in ('cwd', 'model', 'effort', 'permission_mode', 'specialist_id', 'project_id'):
        assert getattr(transactional, field) == getattr(normal, field)
    assert count(world) == before + 2


async def test_transactional_session_creation_refuses_autocommit(world):
    before = count(world)
    with closing(db.connect(world.db_path)) as conn:
        with pytest.raises(RuntimeError, match='transação'):
            world.manager.create_session_in_transaction(conn, world.project)
    assert count(world) == before


async def test_resource_claim_collision_after_session_creation_rolls_everything_back(world, monkeypatch):
    owner = await world.delegate(external_id='resource-owner')
    record = world.manager.create_session(world.project)
    with closing(db.connect(world.db_path)) as conn:
        blocker = store.claim_attempt(conn, owner.id, expected_revision=owner.revision,
            session_id=record.session_id, resources=['shared-schema'], now=100)
        conn.execute("UPDATE work_attempts SET state='succeeded',ended_at=100 WHERE id=?", (blocker.id,))
        conn.execute("UPDATE work_items SET status='done' WHERE id=?", (owner.id,))
    child = await world.delegate(external_id='child')
    original = store.claim_attempt_in_transaction
    def conflict(conn, *args, **kwargs):
        kwargs['resources'] = [*kwargs['resources'], 'shared-schema']
        return original(conn, *args, **kwargs)
    monkeypatch.setattr(store, 'claim_attempt_in_transaction', conflict)
    before = count(world)
    for _ in range(2):
        assert await world.service.dispatch_once() is None
        assert count(world) == before
    assert not world.attempts(child.id)
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, blocker.id) == ['shared-schema']


@pytest.mark.parametrize('failure', ['sql', 'cancel'])
async def test_failure_after_attempt_insert_rolls_back_session_attempt_and_bindings(world, monkeypatch, failure):
    item = await world.delegate()
    original = store.claim_attempt_in_transaction
    def failed_binding(conn, *args, **kwargs):
        original_binding = kwargs['on_claim']
        def bind(conn, attempt):
            original_binding(conn, attempt)
            if failure == 'sql':
                raise sqlite3.OperationalError('failure after bindings')
            raise asyncio.CancelledError()
        kwargs['on_claim'] = bind
        return original(conn, *args, **kwargs)
    monkeypatch.setattr(store, 'claim_attempt_in_transaction', failed_binding)
    before = count(world)
    with pytest.raises(sqlite3.OperationalError if failure == 'sql' else asyncio.CancelledError):
        await world.service.dispatch_once()
    assert count(world) == before
    assert not world.attempts(item.id)
    assert world.factory.clients == []
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_attempt_inputs').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM work_resource_claims').fetchone()[0] == 0


async def test_coordinator_binding_sql_failure_rolls_back_new_session(world):
    before = count(world)
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER reject_cto BEFORE INSERT ON work_coordinators BEGIN SELECT RAISE(ABORT,'failed binding'); END")
    with pytest.raises(sqlite3.IntegrityError):
        world.service.coordinator(world.project.id)
    assert count(world) == before
    with closing(db.connect(world.db_path)) as conn:
        assert not conn.execute('SELECT 1 FROM work_coordinators').fetchone()
        conn.execute('DROP TRIGGER reject_cto')
    canonical = world.service.coordinator(world.project.id)
    assert world.service.coordinator(world.project.id).session_id == canonical.session_id
    assert count(world) == before + 1
