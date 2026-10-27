"""Bounded worker capacity is independent from retained resource ownership."""
from contextlib import closing

import pytest
from test_runtime import World
from test_sessions import make_project, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import PermissionStep, text_turn
from claudio_maestro.work import pool, store

pytestmark = pytest.mark.anyio


@pytest.fixture
async def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    async def capture(project, workspace, **kwargs):
        return {'complete': True, 'digest': 'stable', 'workspace': str(workspace), 'head': 'head'}
    monkeypatch.setattr('claudio_maestro.work.targets.capture_target', capture)
    yield w
    await w.service.shutdown()
    await w.manager.shutdown()


async def second_item(world, suffix='other'):
    project = make_project(world.db_path, world.path / 'home' / suffix)
    item = world.service.create_item(project_id=project.id, title=suffix, objective='Investigar isoladamente')
    return project, item


async def test_two_independent_workers_and_third_waits_for_persisted_capacity(world):
    world.service.configure_pool(global_limit=2, default_project_limit=1)
    first = await world.delegate()
    other_project, other = await second_item(world)
    third_project, third = await second_item(world, 'third')
    a = await world.service.dispatch_once()
    b = await world.service.dispatch_once()
    assert {a.work_item_id, b.work_item_id} == {first.id, other.id}
    assert len(world.factory.clients) == 2
    assert await world.service.dispatch_once() is None
    assert not world.attempts(third.id)
    with closing(db.connect(world.db_path)) as conn:
        assert pool.snapshot(conn)['occupied'] == 2
        assert pool.limits(conn)['global_limit'] == 2
    assert world.service.pool_status()['global_limit'] == 2


async def test_shared_resource_serializes_different_projects_with_two_slots(world):
    world.service.configure_pool(global_limit=2)
    other_project, other = await second_item(world)
    world.service.configure_pool(project_id=world.project.id, resources=['database:integration'])
    world.service.configure_pool(project_id=other_project.id, resources=['database:integration'])
    first = await world.delegate()
    a = await world.service.dispatch_once()
    assert a.work_item_id == other.id  # Lower canonical id was created first.
    assert await world.service.dispatch_once() is None
    assert not world.attempts(first.id)
    with closing(db.connect(world.db_path)) as conn:
        assert 'shared:database:integration' in store.resource_claims(conn, a.id)
    with pytest.raises(store.WorkConflictError):
        world.service.configure_pool(project_id=other_project.id, resources=[])
    with closing(db.connect(world.db_path)) as conn:
        assert pool.resources(conn, other_project.id) == ['shared:database:integration']


async def test_native_permission_keeps_capacity_and_claims(world):
    world.factory.script = lambda content: [PermissionStep('Bash', {'command': 'pytest'}),
        *text_turn(world.factory.clients[-1].options.session_id, 'fim')]
    first = await world.delegate()
    author = await world.service.dispatch_once()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'awaiting_decision')
    await second_item(world)
    await world.service.reconcile()
    assert await world.service.dispatch_once() is None
    state = world.service.pool_status()
    assert state['occupied'] == 1 and state['suspended'] == []
    assert state['workers'][0]['reason'] == 'running_or_native_permission'
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, author.id)
    assert world.item(first.id).status == 'active'


async def test_durable_human_wait_releases_slot_only_after_quiescence_sdkclose(world):
    first = await world.delegate()
    author = await world.service.dispatch_once()
    await world.pause.reached.wait()
    await world.service.request_decision(author.session_id, question='Remover legado?', action='Excluir legacy.py')
    _, other = await second_item(world)
    await world.service.reconcile()
    assert world.service.pool_status()['occupied'] == 1
    assert await world.service.dispatch_once() is None
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.manager.get(author.session_id).client is None
    state = world.service.pool_status()
    assert state['occupied'] == 0 and state['suspended'][0]['attempt_id'] == author.id
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, author.id)
    resumed = await world.service.dispatch_once()
    assert resumed.work_item_id == other.id
    # A manual/Remote Control new process cannot reuse this historical decision.
    with pytest.raises(store.WorkConflictError):
        world.service.assert_session_start(world.manager.find_record(author.session_id))
    assert world.item(first.id).status == 'waiting'


async def test_lower_limit_preserves_running_workers_but_blocks_new_admission(world):
    world.service.configure_pool(global_limit=2)
    await world.delegate()
    await second_item(world)
    await world.service.dispatch_once()
    await world.service.dispatch_once()
    previous = world.service.pool_status()
    world.service.configure_pool(global_limit=1)
    current = world.service.pool_status()
    assert current['occupied'] == 2 and current['global_limit'] == 1
    assert [r['attempt_id'] for r in current['workers']] == [r['attempt_id'] for r in previous['workers']]
    await second_item(world, 'third')
    assert await world.service.dispatch_once() is None
    assert len(world.factory.clients) == 2


@pytest.mark.parametrize('value', [0, 3, -1, True, '2'])
async def test_pool_limit_never_exceeds_two_and_rejects_invalid_values(world, value):
    with pytest.raises(store.WorkValidationError):
        world.service.configure_pool(global_limit=value)
    assert world.service.pool_status()['global_limit'] == 1


async def test_uncertain_claim_survives_recovery_without_timeout_release(world, monkeypatch):
    item = await world.delegate()
    async def lost(*args, **kwargs):
        return {'send_started': True, 'state': 'error'}
    monkeypatch.setattr(world.manager, 'send', lost)
    attempt = await world.service.dispatch_once()
    assert attempt.state == 'uncertain'
    before = world.service.pool_status()
    await world.service.recover()
    after = world.service.pool_status()
    assert after['occupied'] == before['occupied'] == 1
    assert after['workers'][0]['reason'] == 'uncertain_delivery'
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, attempt.id)
    assert len(world.attempts(item.id)) == 1


async def test_sdk_close_failure_never_releases_slot_or_resource(world, monkeypatch):
    await world.delegate()
    author = await world.service.dispatch_once()
    await world.pause.reached.wait()
    await world.service.request_decision(author.session_id, question='Confirmar remoção?')
    async def failed_close():
        raise RuntimeError('process may still be alive')
    monkeypatch.setattr(world.factory.clients[-1], 'close', failed_close)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.service.pool_status()['occupied'] == 1
    assert world.attempt(author.id).state == 'uncertain'
    assert world.service.pool_status()['suspended'] == []
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, author.id)


async def test_per_project_limit_is_separate_from_global_limit(world):
    world.service.configure_pool(global_limit=2, default_project_limit=1)
    a = await world.delegate(external_id='first')
    b = await world.delegate(external_id='second')
    ra = world.manager.create_session(world.project)
    rb = world.manager.create_session(world.project)
    with closing(db.connect(world.db_path)) as conn:
        first = store.claim_attempt(conn, a.id, expected_revision=a.revision,
            session_id=ra.session_id, resources=['workspace:first'], now=100, require_project_mode=True)
        with pytest.raises(store.WorkConflictError, match='projeto'):
            store.claim_attempt(conn, b.id, expected_revision=b.revision,
                session_id=rb.session_id, resources=['workspace:second'], now=100, require_project_mode=True)
    world.service.configure_pool(project_id=world.project.id, project_limit=2)
    with closing(db.connect(world.db_path)) as conn:
        second = store.claim_attempt(conn, b.id, expected_revision=b.revision,
            session_id=rb.session_id, resources=['workspace:second'], now=100, require_project_mode=True)
    assert first.id != second.id
    assert world.service.pool_status()['occupied'] == 2


async def test_cto_active_turn_does_not_consume_worker_pool(world):
    cto = world.service.coordinator(world.project.id)
    await world.service.send_message(cto.session_id, 'Acompanhar objetivo')
    assert world.service.pool_status()['occupied'] == 0
    await world.delegate()
    author = await world.service.dispatch_once()
    assert author is not None
    assert world.service.pool_status()['occupied'] == 1
    assert len(world.factory.clients) == 2


async def test_crash_during_close_preserves_capacity_across_recovery(world, monkeypatch):
    import asyncio
    await world.delegate()
    attempt = await world.service.dispatch_once()
    await world.pause.reached.wait()
    await world.service.request_decision(attempt.session_id, question='Confirmar ação?')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    session = world.manager.get(attempt.session_id)
    original = session.close
    async def interrupted_close(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(session, 'close', interrupted_close)
    with pytest.raises(asyncio.CancelledError):
        await world.service.reconcile()
    with closing(db.connect(world.db_path)) as conn:
        row = conn.execute('SELECT status FROM work_process_closures WHERE attempt_id=?', (attempt.id,)).fetchone()
        assert row['status'] in ('closing', 'uncertain')
    monkeypatch.setattr(session, 'close', original)
    await world.service.recover()
    assert world.attempt(attempt.id).state == 'uncertain'
    assert world.service.pool_status()['occupied'] == 1
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, attempt.id)


async def test_lower_limit_does_not_deadlock_already_reserved_starting_attempts(world):
    world.service.configure_pool(global_limit=2)
    first = await world.delegate()
    other_project, second = await second_item(world)
    for item, project in ((first, world.project), (second, other_project)):
        record = world.manager.create_session(project)
        with closing(db.connect(world.db_path)) as conn:
            store.claim_attempt(conn, item.id, expected_revision=item.revision,
                session_id=record.session_id, resources=world.service.resource_keys(project),
                require_project_mode=True, now=100)
    world.service.configure_pool(global_limit=1)
    assert await world.service.dispatch_once() is not None
    assert await world.service.dispatch_once() is not None
    assert len(world.factory.clients) == 2  # These two slots were admitted before lowering.
    await second_item(world, 'new')
    assert await world.service.dispatch_once() is None


async def test_failed_close_can_be_reconciled_by_retrying_only_retained_client(world, monkeypatch):
    await world.delegate()
    author = await world.service.dispatch_once()
    await world.pause.reached.wait()
    await world.service.request_decision(author.session_id, question='Confirmar ação?')
    client = world.factory.clients[-1]
    original = client.close
    async def failed():
        raise RuntimeError('transient close failure')
    monkeypatch.setattr(client, 'close', failed)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(author.id).state == 'uncertain'
    monkeypatch.setattr(client, 'close', original)
    result = await world.service.reconcile_process_close(author.id)
    assert result['process_closed'] is True
    assert world.attempt(author.id).state == 'waiting'
    assert world.service.pool_status()['occupied'] == 0
    assert len(client.sent) == 1
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, author.id)


async def test_reattached_close_reconciliation_invalidates_reader_before_kill(world, monkeypatch):
    from types import SimpleNamespace
    await world.delegate()
    author = await world.service.dispatch_once()
    await world.pause.reached.wait()
    await world.service.request_decision(author.session_id, question='Confirmar ação?')
    client = world.factory.clients[-1]
    client._transport = SimpleNamespace(child_id='owned-child', process_instance_id='original-daemon')
    async def failed():
        raise RuntimeError('lost agentd confirmation')
    original = client.close
    monkeypatch.setattr(client, 'close', failed)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(author.id).state == 'uncertain'
    session = world.manager.get(author.session_id)
    # A restart reattaches this exact child. Its reader must be invalidated
    # before kill, otherwise shutdown generates a spurious error callback.
    session.client = client
    errors = []
    async def close_attached():
        if session.client is client:
            errors.append('reader received expected kill as a turn error')
            world.service.on_session_error(author.session_id, 'reader killed')
        await original()
    monkeypatch.setattr(client, 'close', close_attached)
    result = await world.service.reconcile_process_close(author.id)
    assert result['process_closed'] is True
    assert errors == []
    assert world.attempt(author.id).state == 'waiting'
    assert world.service._signals(author.id)['error_seen'] == 0


async def test_saved_confirmed_close_survives_new_manager_without_new_sdk(world):
    from test_sessions import Recorder, fake_history

    from claudio_maestro.agent.fake import FakeAgentFactory
    from claudio_maestro.sessions import SessionManager
    from claudio_maestro.work.service import WorkService
    await world.delegate()
    author = await world.service.dispatch_once()
    await world.pause.reached.wait()
    await world.service.request_decision(author.session_id, question='Confirmar ação?')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    assert await world.service._close_work_process(author)
    factory = FakeAgentFactory()
    manager = SessionManager(world.db_path, Recorder(), agent_factory=factory, history_exists=fake_history(factory))
    other = WorkService(world.db_path, sessions=manager, files=world.service.files, publish=Recorder())
    try:
        await other.recover()
        assert world.attempt(author.id).state == 'waiting'
        assert other.pool_status()['occupied'] == 0
        assert factory.clients == []
    finally:
        await other.shutdown()
        await manager.shutdown()


async def test_restart_close_reconciliation_needs_valid_agentd_reply_for_exact_identity(world, monkeypatch):
    from types import SimpleNamespace

    from test_sessions import Recorder, fake_history

    from claudio_maestro.agent.fake import FakeAgentFactory
    from claudio_maestro.sessions import SessionManager
    from claudio_maestro.work.service import WorkService
    await world.delegate()
    author = await world.service.dispatch_once()
    await world.pause.reached.wait()
    await world.service.request_decision(author.session_id, question='Confirmar ação?')
    client = world.factory.clients[-1]
    client._transport = SimpleNamespace(child_id='exact-child', process_instance_id='original-daemon')
    async def failed():
        raise RuntimeError('no close acknowledgement')
    monkeypatch.setattr(client, 'close', failed)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    class Agentd:
        reply = None
        async def live_children(self, *, expected_instance_id=None):
            assert expected_instance_id == 'original-daemon'
            return self.reply
    agentd = Agentd()
    factory = FakeAgentFactory()
    manager = SessionManager(world.db_path, Recorder(), agent_factory=factory,
        history_exists=fake_history(factory), agentd=agentd)
    other = WorkService(world.db_path, sessions=manager, files=world.service.files, publish=Recorder())
    try:
        await other.recover()
        with pytest.raises(store.WorkConflictError, match='processo exato'):
            await other.reconcile_process_close(author.id)
        assert other.pool_status()['occupied'] == 1
        # A successful authoritative list (not missing socket) proves that the
        # exact persisted child identity is gone. No SDK turn is replayed.
        agentd.reply = []
        assert (await other.reconcile_process_close(author.id))['process_closed']
        assert other.pool_status()['occupied'] == 0
        assert factory.clients == []
    finally:
        await other.shutdown()
        await manager.shutdown()


async def test_setup_close_failure_blocks_fallback_and_survives_restart(world):
    from test_sessions import Recorder, fake_history

    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.agent.fake import FakeAgentClient, FakeAgentFactory
    from claudio_maestro.sessions import SessionManager
    from claudio_maestro.work.service import WorkService
    clients = []
    def factory(options):
        client = FakeAgentClient(options, world.factory.script)
        if not clients:
            client.connect_error = AgentError('Sessão em uso', session_in_use=True)
            async def failed():
                raise RuntimeError('process may still be alive')
            client.close = failed
        clients.append(client)
        return client
    world.manager._agent_factory = factory
    item = await world.delegate()
    with pytest.raises(store.WorkConflictError):
        await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    assert len(clients) == 1 and not clients[0].sent
    assert attempt.state == 'uncertain'
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT status FROM work_process_closures WHERE attempt_id=?', (attempt.id,)).fetchone()['status'] == 'uncertain'
    fresh_factory = FakeAgentFactory()
    fresh = SessionManager(world.db_path, Recorder(), agent_factory=fresh_factory,
                           history_exists=fake_history(fresh_factory))
    other = WorkService(world.db_path, sessions=fresh, files=world.service.files, publish=Recorder())
    try:
        await other.recover()
        assert await other.dispatch_once() is None
        assert not fresh_factory.clients
        assert len(world.attempts(item.id)) == 1
        with closing(db.connect(world.db_path)) as conn:
            assert store.resource_claims(conn, attempt.id)
    finally:
        await other.shutdown()
        await fresh.shutdown()


async def test_recorded_delivery_cannot_reopen_process_during_handover(world, monkeypatch):
    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.sessions import ProcessAdmissionDenied
    await world.delegate()
    author = await world.service.dispatch_once()
    await world.service.conclude(author.session_id, result_kind='investigation', summary='Entrega registrada')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    session = world.manager.get(author.session_id)
    original = session.close
    refusals = []
    async def reopen_after_close(*args, **kwargs):
        await original(*args, **kwargs)
        with pytest.raises((AgentError, store.WorkConflictError, ProcessAdmissionDenied)):
            session._new_client(resume=True)
        refusals.append(True)
    monkeypatch.setattr(session, 'close', reopen_after_close)
    await world.service.reconcile()
    assert refusals == [True]
    assert len(world.factory.clients) == 1
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT status FROM work_process_closures WHERE attempt_id=?', (author.id,)).fetchone()['status'] == 'closed'
    assert world.attempt(author.id).state == 'succeeded'


async def test_public_remote_refusal_during_handover_preserves_prior_turn_receipt(world, monkeypatch):
    from claudio_maestro.sessions import ProcessAdmissionDenied
    await world.delegate()
    author = await world.service.dispatch_once()
    await world.service.request_decision(author.session_id, question='Confirmar ação?')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    session = world.manager.get(author.session_id)
    original = session.close
    denied = []
    async def control_while_handing_over(*args, **kwargs):
        await original(*args, **kwargs)
        with pytest.raises(ProcessAdmissionDenied):
            await session.set_remote_control(True)
        denied.append(True)
    monkeypatch.setattr(session, 'close', control_while_handing_over)
    await world.service.reconcile()
    assert denied == [True] and len(world.factory.clients) == 1
    assert world.attempt(author.id).state == 'waiting'
    assert world.service._signals(author.id)['error_seen'] == 0
    assert world.service.pool_status()['occupied'] == 0


async def test_close_receipt_write_failure_never_becomes_proven_unsent(world):
    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.agent.fake import FakeAgentClient
    clients = []
    def factory(options):
        client = FakeAgentClient(options, world.factory.script)
        client.connect_error = AgentError('Sessão em uso', session_in_use=True)
        clients.append(client)
        return client
    world.manager._agent_factory = factory
    item = await world.delegate()
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER fail_close_write BEFORE INSERT ON work_process_closures BEGIN SELECT RAISE(ABORT,'cannot persist close'); END")
    with pytest.raises(store.WorkConflictError):
        await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    assert attempt.state == 'uncertain'
    assert not world.service._signals(attempt.id)['proven_unsent']
    assert len(clients) == 1 and not clients[0].sent
    with closing(db.connect(world.db_path)) as conn:
        assert not conn.execute('SELECT 1 FROM work_process_closures').fetchone()
        assert store.resource_claims(conn, attempt.id)
    await world.service.recover()
    assert await world.service.dispatch_once() is None


async def test_continuation_close_receipt_failure_remains_uncertain(world):
    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.agent.fake import FakeAgentClient
    await world.delegate()
    author = await world.service.dispatch_once()
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(author.id).state == 'waiting'
    await world.manager.get(author.session_id).close()
    def factory(options):
        client = FakeAgentClient(options, world.factory.script)
        client.connect_error = AgentError('Falha ao conectar')
        return client
    world.manager._agent_factory = factory
    world.manager.get(author.session_id)._agent_factory = factory
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER fail_close_write BEFORE INSERT ON work_process_closures BEGIN SELECT RAISE(ABORT,'cannot persist close'); END")
    with pytest.raises(store.WorkConflictError):
        await world.service.send_message(author.session_id, 'Continuar investigação')
    assert world.attempt(author.id).state == 'uncertain'
    assert not world.service._signals(author.id)['proven_unsent']
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, author.id)


async def test_idle_close_observer_failure_persists_uncertainty_without_send_guard(world):
    await world.delegate()
    author = await world.service.dispatch_once()
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(author.id).state == 'waiting'
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER fail_idle_close BEFORE INSERT ON work_process_closures BEGIN SELECT RAISE(ABORT,'cannot persist close'); END")
    await world.manager.get(author.session_id).close()
    assert world.attempt(author.id).state == 'uncertain'
    assert world.service.project_mode(world.project.id)['paused']
    assert not world.service._signals(author.id)['proven_unsent']
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, author.id)


async def test_both_receipt_and_uncertainty_write_failure_never_return_safe_unsent(world):
    import sqlite3

    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.agent.fake import FakeAgentClient
    def factory(options):
        client = FakeAgentClient(options, world.factory.script)
        client.connect_error = AgentError('Falha ao conectar')
        return client
    world.manager._agent_factory = factory
    item = await world.delegate()
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON work_process_closures BEGIN SELECT RAISE(ABORT,'receipt unavailable'); END")
        conn.execute("CREATE TRIGGER fail_uncertainty BEFORE UPDATE ON work_attempts WHEN NEW.state='uncertain' BEGIN SELECT RAISE(ABORT,'core unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError):
        await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    assert attempt.state == 'dispatching'
    assert not world.service._signals(attempt.id)['proven_unsent']
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, attempt.id)
        conn.execute('DROP TRIGGER fail_receipt')
        conn.execute('DROP TRIGGER fail_uncertainty')
