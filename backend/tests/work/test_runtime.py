"""Work orchestration uses isolated sessions and never the real SDK."""
from contextlib import closing
from pathlib import Path

import pytest
from test_sessions import Recorder, fake_history, make_project, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, PauseStep, text_turn
from claudio_maestro.sessions import SessionManager
from claudio_maestro.work import store
from claudio_maestro.work.files import WorkFiles
from claudio_maestro.work.service import WorkService

pytestmark = pytest.mark.anyio


class World:
    def __init__(self, path):
        self.path = path
        self.db_path = path / 'data' / 'maestro.db'
        db.init_db(self.db_path)
        self.project = make_project(self.db_path, path / 'home' / 'app')
        self.recorder = Recorder()
        self.pause = PauseStep()
        self.factory = FakeAgentFactory(script=lambda content: [self.pause, *text_turn(self.factory.clients[-1].options.session_id, 'feito')])
        self.manager = SessionManager(self.db_path, self.recorder, agent_factory=self.factory,
            history_exists=fake_history(self.factory),
            context_setup=lambda record: self.service.session_context(record),
            on_session_result=lambda sid, result: self.service.on_session_result(sid, result),
            on_session_turn_end=lambda sid: self.service.on_session_turn_end(sid),
            on_session_error=lambda sid, error: self.service.on_session_error(sid, error))
        self.service = WorkService(self.db_path, sessions=self.manager, files=WorkFiles(path / 'work'),
            publish=self.recorder, clock=lambda: 100)

    def item(self, id):
        with closing(db.connect(self.db_path)) as conn:
            return store.get_item(conn, id)

    def attempt(self, id):
        with closing(db.connect(self.db_path)) as conn:
            return store.get_attempt(conn, id)

    def attempts(self, id):
        with closing(db.connect(self.db_path)) as conn:
            return store.list_attempts(conn, id)

    async def delegate(self, **kwargs):
        coordinator = self.service.coordinator(self.project.id)
        return await self.service.delegate(coordinator.session_id, title='Investigar #50', objective='Rastrear o código e as guardas', **kwargs)


@pytest.fixture
async def world(tmp_path):
    world = World(tmp_path)
    yield world
    await world.service.shutdown()
    await world.manager.shutdown()


async def test_coordinator_is_project_scoped_persistent_normal_session(world):
    first = world.service.coordinator(world.project.id)
    assert first.session_id == world.service.coordinator(world.project.id).session_id
    assert first.specialist_id is None
    other = make_project(world.db_path, world.path / 'home' / 'other')
    assert world.service.coordinator(other.id).session_id != first.session_id
    context = world.service.session_context(first)
    assert 'maestro_work' in context.mcp_servers
    assert not hasattr(context, 'decide')


async def test_delegation_is_durable_deduplicated_and_not_inline(world):
    a = await world.delegate(source='kbgen', source_instance='local', source_project='body', external_id='50')
    b = await world.delegate(source='kbgen', source_instance='local', source_project='body', external_id='50')
    assert a.id == b.id
    assert world.factory.clients == []
    assert world.item(a.id).status == 'ready'
    assert world.service.dossier(a.id)['objective'] == 'Rastrear o código e as guardas'
    await world.service.dispatch_once()
    attempt = world.attempts(a.id)[0]
    assert attempt.session_id != world.service.coordinator(world.project.id).session_id
    assert world.manager.find_record(attempt.session_id).specialist_id is None
    assert 'Rastrear o código' in str(world.factory.clients[-1].sent)
    assert world.service.session_identity(attempt.session_id)['work_item_id'] == a.id


async def test_worker_cannot_delegate_or_read_another_project(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    sid = world.attempts(item.id)[0].session_id
    with pytest.raises(store.WorkValidationError):
        await world.service.delegate(sid, title='Recursão', objective='Não permitido')
    other = make_project(world.db_path, world.path / 'home' / 'other')
    with closing(db.connect(world.db_path)) as conn:
        foreign, _ = store.create_item(conn, project_id=other.id, title='Outra', now=100)
    with pytest.raises(store.WorkValidationError):
        world.service.get_work(sid, foreign.id)


async def test_recording_result_inside_turn_does_not_release_claim(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Guarda localizada', evidence=['file.py:12'], tests=['Não executados'])
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'running'
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, attempt.id)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'succeeded'
    assert world.item(item.id).status == 'review'
    assert world.service.result(attempt.id)['summary'] == 'Guarda localizada'


async def test_turn_without_result_waits_instead_of_inventing_success(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'waiting'
    assert world.item(item.id).status == 'waiting'
    assert world.attempt(attempt.id).result_ref is None


async def test_confirmed_unsent_pauses_and_requires_explicit_resume(world, monkeypatch):
    item = await world.delegate()
    async def unsent(*args, **kwargs):
        return {'send_started': False, 'state': 'error'}
    monkeypatch.setattr(world.manager, 'send', unsent)
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    assert attempt.state == 'starting'
    assert world.service.project_mode(world.project.id)['paused']
    assert await world.service.dispatch_once() is None


async def test_send_started_with_error_is_uncertain_never_retried(world, monkeypatch):
    item = await world.delegate()
    calls = []
    async def uncertain(*args, **kwargs):
        calls.append(args)
        return {'send_started': True, 'state': 'error'}
    monkeypatch.setattr(world.manager, 'send', uncertain)
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    assert attempt.state == 'uncertain'
    await world.service.recover()
    await world.service.dispatch_once()
    assert len(calls) == 1
    assert world.attempt(attempt.id).state == 'uncertain'
    with pytest.raises(store.WorkConflictError):
        world.service.resume_project(world.project.id)
    with pytest.raises(store.WorkConflictError):
        world.service.assert_deletion_allowed(session_id=attempt.session_id)
    with pytest.raises(store.WorkConflictError):
        world.service.assert_deletion_allowed(project_id=world.project.id)


async def test_private_write_failure_cannot_record_result(world, monkeypatch):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    def broken(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(world.service.files, 'write', broken)
    with pytest.raises(OSError):
        await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Não salvo')
    assert world.attempt(attempt.id).result_ref is None


async def test_restart_preserves_pending_result_without_sending_again(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Salvo antes do restart')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    count = len(world.factory.clients[-1].sent)
    other = WorkService(world.db_path, sessions=world.manager, files=world.service.files, publish=world.recorder)
    await other.recover()
    assert world.attempt(attempt.id).state == 'succeeded'
    assert len(world.factory.clients[-1].sent) == count
    await other.shutdown()


async def test_activation_uses_shared_transaction_and_legacy_gate(world):
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        assert world.service.can_legacy_dispatch(conn, world.project.id)
    world.service.activate_project(world.project.id)
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        assert not world.service.can_legacy_dispatch(conn, world.project.id)


async def test_busy_legacy_prevents_project_activation(world):
    world.service.legacy_busy = lambda conn, project_id: True
    with pytest.raises(store.WorkConflictError):
        world.service.activate_project(world.project.id)
    assert not world.service.project_mode(world.project.id)['enabled']


async def test_budget_stops_new_delegation(world):
    world.service.max_tasks = 1
    await world.delegate()
    with pytest.raises(store.WorkConflictError):
        await world.delegate(external_id='another')


def test_work_files_are_private_bounded_and_reject_symlinks(tmp_path):
    files = WorkFiles(tmp_path / 'work')
    ref = files.write({'summary': 'privado'})
    assert files.read(ref)['summary'] == 'privado'
    assert (tmp_path / 'work' / ref).stat().st_mode & 0o777 == 0o600
    target = tmp_path / 'secret'
    target.write_text('secret')
    (tmp_path / 'work' / ref).unlink()
    (tmp_path / 'work' / ref).symlink_to(target)
    with pytest.raises(OSError):
        files.read(ref)
    with pytest.raises(store.WorkValidationError):
        files.read('../secret')


async def test_failed_spec_insert_rolls_back_item_mode_and_event(world):
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER reject_spec BEFORE INSERT ON work_specs BEGIN SELECT RAISE(ABORT, 'spec failed'); END")
    with pytest.raises(Exception, match='spec failed'):
        await world.delegate(source='kbgen', external_id='50')
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_items').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM work_events').fetchone()[0] == 0
        conn.execute('DROP TRIGGER reject_spec')
    assert not world.service.project_mode(world.project.id)['enabled']
    item = await world.delegate(source='kbgen', external_id='50')
    assert world.service.dossier(item.id)['objective']


async def test_continuation_exception_is_uncertain_and_not_replayed(world, monkeypatch):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    calls = []
    async def unknown(*args, **kwargs):
        calls.append(args)
        raise RuntimeError('possible delivery')
    monkeypatch.setattr(world.manager, 'send', unknown)
    with pytest.raises(RuntimeError):
        await world.service.send_message(attempt.session_id, 'Continue')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'uncertain'
    assert world.service.project_mode(world.project.id)['paused']
    with pytest.raises(store.WorkConflictError):
        await world.service.send_message(attempt.session_id, 'Continue')
    assert len(calls) == 1


async def test_invalid_input_does_not_activate_project(world):
    with pytest.raises(store.WorkValidationError):
        await world.service.delegate(world.service.coordinator(world.project.id).session_id, title='', objective='Investigar')
    assert not world.service.project_mode(world.project.id)['enabled']


async def test_cto_active_does_not_block_worker_and_issue_contexts_are_distinct(world):
    cto = world.service.coordinator(world.project.id)
    await world.manager.send(cto.session_id, 'Coordene as issues')
    assert world.manager.get(cto.session_id).state == 'running'
    first = await world.delegate(source='kbgen', external_id='50')
    second = await world.service.delegate(cto.session_id, title='Investigar #55', objective='Auditar chaves do cliente', source='kbgen', external_id='55')
    await world.service.dispatch_once()
    a = world.attempts(first.id)[0]
    await world.service.conclude(a.session_id, result_kind='investigation', summary='Primeira analisada')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(a.session_id).state == 'idle')
    await world.service.reconcile()
    await world.service.dispatch_once()
    b = world.attempts(second.id)[0]
    assert a.session_id != b.session_id != cto.session_id
    assert 'Rastrear o código' in world.service.session_context(world.manager.find_record(a.session_id)).system_prompt_append
    assert 'Auditar chaves' in world.service.session_context(world.manager.find_record(b.session_id)).system_prompt_append
    assert 'Rastrear o código' not in world.service.session_context(world.manager.find_record(b.session_id)).system_prompt_append


async def test_completed_history_does_not_exhaust_pending_budget(world):
    world.service.max_tasks = 1
    first = await world.delegate()
    with closing(db.connect(world.db_path)) as conn:
        store.update_item(conn, first.id, expected_revision=first.revision, status='cancelled', now=101)
    second = await world.delegate(external_id='other')
    assert second.id != first.id


async def test_dispatching_with_saved_result_recovers_without_replay(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("UPDATE work_attempts SET state='dispatching' WHERE id=?", (attempt.id,))
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Resposta já salva')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    sent = len(world.factory.clients[-1].sent)
    await world.service.recover()
    assert world.attempt(attempt.id).state == 'succeeded'
    assert len(world.factory.clients[-1].sent) == sent


async def test_unavailable_project_does_not_starve_other_projects(world):
    first = await world.delegate()
    other = make_project(world.db_path, world.path / 'home' / 'other')
    second = world.service.create_item(project_id=other.id, title='Outra issue', objective='Projeto disponível')
    Path(world.project.path).rmdir()
    await world.service.dispatch_once()
    assert world.item(first.id).status == 'blocked'
    assert len(world.attempts(second.id)) == 1
    await world.service.dispatch_once()
    with closing(db.connect(world.db_path)) as conn:
        events = store.list_events(conn, first.id)
    assert any('indisponível' in str(event.data) for event in events)


async def test_attempt_budget_blocks_only_its_item_and_publishes_reason(world):
    first = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(first.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Analisada')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    current = world.item(first.id)
    with closing(db.connect(world.db_path)) as conn:
        store.update_item(conn, first.id, expected_revision=current.revision, status='ready', now=101)
    second = await world.delegate(external_id='next')
    world.service.max_attempts = 1
    await world.service.dispatch_once()
    assert world.item(first.id).status == 'blocked'
    assert len(world.attempts(second.id)) == 1
    assert not world.service.project_mode(world.project.id)['paused']


async def test_changed_event_reports_current_revision_after_finish(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Pronto')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.recorder.of(None, 'work.changed')[-1]['data']['revision'] == world.item(item.id).revision


async def test_failure_before_result_survives_new_manager_recovery(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Salvo antes de falhar')
    await world.manager.get(attempt.session_id)._fail('Falha antes de Result')
    factory = FakeAgentFactory()
    manager = SessionManager(world.db_path, Recorder(), agent_factory=factory, history_exists=fake_history(factory))
    other = WorkService(world.db_path, sessions=manager, files=world.service.files, publish=Recorder())
    await other.recover()
    assert world.attempt(attempt.id).state == 'uncertain'
    assert other.result(attempt.id)['summary'] == 'Salvo antes de falhar'
    assert not factory.clients
    await other.shutdown()
    await manager.shutdown()


async def test_missing_dossier_blocks_only_its_candidate(world):
    first = await world.delegate()
    other = make_project(world.db_path, world.path / 'home' / 'other')
    second = world.service.create_item(project_id=other.id, title='Outra issue', objective='Dossiê disponível')
    with closing(db.connect(world.db_path)) as conn:
        ref = conn.execute('SELECT dossier_ref FROM work_specs WHERE work_item_id=?', (first.id,)).fetchone()[0]
    (world.service.files.root / ref).unlink()
    await world.service.dispatch_once()
    assert world.item(first.id).status == 'blocked'
    assert len(world.attempts(second.id)) == 1


async def test_saved_quiescent_receipt_recovers_with_new_manager(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Fim comprovado')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    factory = FakeAgentFactory()
    manager = SessionManager(world.db_path, Recorder(), agent_factory=factory, history_exists=fake_history(factory))
    other = WorkService(world.db_path, sessions=manager, files=world.service.files, publish=Recorder())
    await other.recover()
    assert world.attempt(attempt.id).state == 'succeeded'
    assert not factory.clients
    await other.shutdown()
    await manager.shutdown()


async def test_lost_result_is_explicit_failure_and_does_not_starve_other_project(world):
    first = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(first.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Arquivo perdido')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    (world.service.files.root / world.attempt(attempt.id).result_ref).unlink()
    other = make_project(world.db_path, world.path / 'home' / 'other')
    second = world.service.create_item(project_id=other.id, title='Outra', objective='Pode avançar')
    await world.service.reconcile()
    await world.service.dispatch_once()
    assert world.attempt(attempt.id).state == 'failed'
    assert world.item(first.id).status == 'blocked'
    assert len(world.attempts(second.id)) == 1
    result = world.service.get_work(world.service.coordinator(world.project.id).session_id, first.id)['attempts'][0]['result']
    assert result['unavailable'] is True
    with closing(db.connect(world.db_path)) as conn:
        assert any('indisponível' in str(e.data) for e in store.list_events(conn, first.id))


async def test_pause_between_snapshot_and_claim_prevents_dispatch(world, monkeypatch):
    item = await world.delegate()
    original = world.manager.create_session
    def create_then_pause(project, **kwargs):
        record = original(project, **kwargs)
        world.service.pause_project(project.id)
        return record
    monkeypatch.setattr(world.manager, 'create_session', create_then_pause)
    assert await world.service.dispatch_once() is None
    assert world.attempts(item.id) == []
    assert not world.factory.clients


async def test_interrupted_result_does_not_become_normal_success(world):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Evidência parcial')
    await world.pause.reached.wait()
    await world.manager.get(attempt.session_id).interrupt()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'failed'
    assert world.service.result(attempt.id)['summary'] == 'Evidência parcial'
    assert world.item(item.id).status == 'blocked'


async def test_missing_result_receipt_never_becomes_success_after_restart(world, monkeypatch):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Entrega sem recibo')
    def broken(*args):
        raise OSError('receipt write failed')
    monkeypatch.setattr(world.manager.get(attempt.session_id), '_on_session_result', broken)
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    factory = FakeAgentFactory()
    manager = SessionManager(world.db_path, Recorder(), agent_factory=factory, history_exists=fake_history(factory))
    other = WorkService(world.db_path, sessions=manager, files=world.service.files, publish=Recorder())
    await other.recover()
    assert world.attempt(attempt.id).state == 'uncertain'
    await other.shutdown()
    await manager.shutdown()


async def test_timeout_interrupts_even_when_result_file_cannot_be_written(world, monkeypatch):
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    world.service.clock = lambda: 10000
    def broken(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(world.service.files, 'write', broken)
    await world.service.reconcile()
    assert world.factory.clients[-1].interrupts == 1
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'failed'
    assert world.item(item.id).status == 'blocked'


@pytest.mark.parametrize('terminal_error', [False, True])
async def test_live_error_overrides_old_receipt_when_signal_write_fails(world, terminal_error):
    if terminal_error:
        from claudio_maestro.agent.fake import result_message
        world.factory.script = lambda content: [world.pause, result_message(
            world.factory.clients[-1].options.session_id, is_error=True, terminal_reason='error')]
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Antes do erro tardio')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    assert world.service._signals(attempt.id)['quiescent']
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER reject_error_signal BEFORE UPDATE ON work_attempt_signals WHEN NEW.error_seen=1 BEGIN SELECT RAISE(ABORT, 'receipt write failure'); END")
    await world.manager.get(attempt.session_id)._fail('Erro posterior ao recibo')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'uncertain'
    assert world.item(item.id).status != 'review'
    with closing(db.connect(world.db_path)) as conn:
        assert store.resource_claims(conn, attempt.id)


async def test_terminal_error_result_is_known_failure_not_uncertain_delivery(world):
    from claudio_maestro.agent.fake import result_message
    world.factory.script = lambda content: [world.pause, result_message(
        world.factory.clients[-1].options.session_id, is_error=True, terminal_reason='error')]
    item = await world.delegate()
    await world.service.dispatch_once()
    attempt = world.attempts(item.id)[0]
    await world.service.conclude(attempt.session_id, result_kind='investigation', summary='Evidência parcial')
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(attempt.session_id).state == 'idle')
    await world.service.reconcile()
    assert world.attempt(attempt.id).state == 'failed'
    assert world.service.result(attempt.id)['summary'] == 'Evidência parcial'
