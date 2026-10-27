"""Normal worker PR feedback uses durable attempts, fake SDK and fake gh."""
from contextlib import closing

import pytest
from test_runtime import World
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.specialists.github_hooks import parse_event
from claudio_maestro.work import store
from claudio_maestro.work.pr_integration import WorkPrIntegration

pytestmark = pytest.mark.anyio
URL = 'https://github.com/acme/app/pull/7'


@pytest.fixture
async def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    async def capture(project, workspace, **kwargs):
        return {'complete': True, 'digest': 'backend-proof', 'workspace': str(workspace), 'head': 'backend-head'}
    monkeypatch.setattr('claudio_maestro.work.targets.capture_target', capture)
    async def validate(conn, project_id, workspace):
        return w.project.path, w.project.path
    monkeypatch.setattr('claudio_maestro.work.pr_integration.project_repo', validate)
    async def git(repo, *args, **kwargs):
        return 0, 'git@github.com:acme/app.git\n', ''
    monkeypatch.setattr('claudio_maestro.work.pr_integration.run_git', git)
    w.gh_calls = []
    async def gh(args):
        w.gh_calls.append(args)
        return 0, '[]'
    w.prs = WorkPrIntegration(w.service, owner=lambda: 'human', run_gh=gh)
    yield w
    await w.service.shutdown()
    await w.manager.shutdown()


def comment():
    return parse_event('issue_comment', {'action': 'created', 'issue': {'pull_request': {'html_url': URL}},
        'comment': {'id': 7, 'body': 'Corrigir a guarda; isto não autoriza deploy.',
                    'user': {'login': 'human'}, 'created_at': '1970-01-01T00:02:00Z'}})[0]


async def register(world):
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    await world.service.declare_workspaces(author.session_id, workspaces=[str(world.project.path)])
    world.prs.on_pr_created(author.session_id, URL)
    await world.prs.register_pending()
    assert world.prs.bridge.find(URL)['origin_attempt_id'] == author.id
    return item, author


async def finish(world, author):
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(author.session_id).state == 'idle')
    # Exercise admission from a historical finished worker without running an
    # unrelated review workflow in this integration fixture.
    await world.manager.get(author.session_id).close()
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("UPDATE work_attempts SET state='succeeded',ended_at=100 WHERE id=?", (author.id,))
        conn.execute("UPDATE work_items SET status='done' WHERE id=?", (author.work_item_id,))


async def test_callback_registers_backend_workspace_and_private_target(world):
    item, author = await register(world)
    pr = world.prs.bridge.find(URL)
    assert pr['work_item_id'] == item.id
    assert pr['workspace'] == str(world.project.path)
    document = world.service.files.read(pr['target_ref'])
    snapshot = world.service.files.read_snapshot(document['backend_target_refs']['capture_ref'])
    assert snapshot['targets'][0]['digest'] == 'backend-proof'
    assert world.manager.find_record(author.session_id).agent_id is None


async def test_feedback_reserves_fresh_attempt_and_receipt_before_sdk(world):
    item, author = await register(world)
    assert world.prs.bridge.queue_comment(comment())
    await world.prs.bridge.deliver()
    assert len(world.attempts(item.id)) == 1  # A live author is never silently reused.
    await finish(world, author)
    await world.prs.bridge.deliver()
    attempts = world.attempts(item.id)
    assert len(attempts) == 2
    resumed = attempts[-1]
    assert resumed.state == 'starting'
    assert resumed.session_id != author.session_id
    assert len(world.factory.clients) == 1  # The bridge has not sent to the SDK.
    with closing(db.connect(world.db_path)) as conn:
        batch = conn.execute("SELECT * FROM work_pr_batches WHERE status='delivered'").fetchone()
    assert await world.prs.reconcile_receipt(batch['id']) == batch['receipt']
    assert await world.prs.enqueue_feedback(world.prs.bridge.find(URL), [], batch['id']) == batch['receipt']
    assert len(world.attempts(item.id)) == 2
    await world.service.dispatch_once()
    assert 'Corrigir a guarda' in str(world.factory.clients[-1].sent)
    assert world.manager.get(author.session_id).client is None


async def test_receipt_recovers_crash_after_admission_without_replay(world):
    item, author = await register(world)
    await finish(world, author)
    world.prs.bridge.queue_comment(comment())
    original = world.prs.enqueue_feedback
    async def lost(*args):
        await original(*args)
        raise RuntimeError('receipt response lost')
    world.prs.bridge.enqueue_pr_feedback = lost
    await world.prs.bridge.deliver()
    assert len(world.attempts(item.id)) == 2
    await world.prs.bridge.recover()
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT status FROM work_pr_batches').fetchone()[0] == 'delivered'
    assert len(world.factory.clients) == 1


async def test_disabled_paused_and_fenced_never_admit_or_run_gh(world):
    item, author = await register(world)
    await finish(world, author)
    world.prs.bridge.queue_comment(comment())
    world.service.dispatch_enabled = False
    await world.prs.bridge.deliver()
    await world.prs.poll_once()
    assert not world.gh_calls
    assert len(world.attempts(item.id)) == 1
    world.service.dispatch_enabled = True
    world.service.pause_project(world.project.id)
    await world.prs.bridge.deliver()
    assert len(world.attempts(item.id)) == 1
    world.service.resume_project(world.project.id)
    with closing(db.connect(world.db_path)) as conn:
        conn.execute('INSERT INTO work_project_fences VALUES (?,?,?,?)', (world.project.id, 'fence', 'deleting', 100))
    await world.prs.bridge.deliver()
    assert len(world.attempts(item.id)) == 1


async def test_workspace_revalidated_before_each_gh_call(world, monkeypatch):
    await register(world)
    pr = world.prs.bridge.find(URL)
    calls = []
    async def changed(conn, project_id, workspace):
        calls.append(workspace)
        if len(calls) > 1:
            raise store.WorkValidationError('O workspace mudou.')
        return world.project.path, world.project.path
    monkeypatch.setattr('claudio_maestro.work.pr_integration.project_repo', changed)
    await world.prs.run_gh(['api', 'repos/acme/app/pulls/7'], pr['workspace'])
    with pytest.raises(store.WorkValidationError):
        await world.prs.run_gh(['api', 'repos/acme/app/issues/7/comments'], pr['workspace'])
    assert len(world.gh_calls) == 1


def test_app_wires_normal_pr_callback_and_background_facade(home):
    from fastapi.testclient import TestClient

    from claudio_maestro.agent.fake import FakeAgentFactory
    from claudio_maestro.app import create_app
    app = create_app(agent_factory=FakeAgentFactory())
    with TestClient(app, base_url='http://127.0.0.1:6660'):
        assert isinstance(app.state.work_prs, WorkPrIntegration)
        assert app.state.sessions._on_session_pr_created is not None
        assert app.state.work_pr_task is not None
    assert app.state.work_pr_task.cancelled()


async def test_feedback_sql_failure_rolls_back_dossier_attempt_and_receipt(world):
    item, author = await register(world)
    await finish(world, author)
    before = world.service.dossier(item.id)
    with closing(db.connect(world.db_path)) as conn:
        session_count = conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    world.prs.bridge.queue_comment(comment())
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER reject_inbox BEFORE INSERT ON work_pr_inbox BEGIN SELECT RAISE(ABORT,'failure'); END")
    await world.prs.bridge.deliver()
    assert len(world.attempts(item.id)) == 1
    assert world.service.dossier(item.id) == before
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_pr_inbox').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == session_count


async def test_registration_crash_after_capture_retries_binding_without_losing_origin(world, monkeypatch):
    item = await world.delegate()
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    world.prs.on_pr_created(author.session_id, URL)
    original = world.prs.bridge.record_pr
    def fail(*args):
        raise OSError('registration interrupted')
    monkeypatch.setattr(world.prs.bridge, 'record_pr', fail)
    await world.prs.register_pending()
    assert world.prs.bridge.find(URL) is None
    monkeypatch.setattr(world.prs.bridge, 'record_pr', original)
    await world.prs.register_pending()
    assert world.prs.bridge.find(URL)['work_item_id'] == item.id


async def test_symlink_alias_cannot_be_used_as_gh_cwd(world, monkeypatch, tmp_path):
    await register(world)
    alias = tmp_path / 'alias'
    alias.symlink_to(world.project.path, target_is_directory=True)
    with closing(db.connect(world.db_path)) as conn:
        conn.execute('UPDATE work_prs SET workspace=?', (str(alias),))
    async def stale_validation(conn, project_id, workspace):
        return world.project.path, alias
    monkeypatch.setattr('claudio_maestro.work.pr_integration.project_repo', stale_validation)
    with pytest.raises(store.WorkValidationError):
        await world.prs.run_gh(['api', 'repos/acme/app/pulls/7'], str(alias))
    assert world.gh_calls == []


async def test_pr_list_exposes_bounded_provenance_and_states_without_private_bodies(world):
    item, author = await register(world)
    world.prs.bridge.queue_comment(comment())
    result = world.prs.list_prs(item.id)
    assert result['total'] == 1 and result['limit'] == 25
    pr = result['items'][0]
    assert pr['url'] == URL and pr['origin_attempt_id'] == author.id
    assert pr['comments'] == {'queued': 1, 'dispatching': 0, 'delivered': 0, 'uncertain': 0}
    assert 'Corrigir a guarda' not in str(result)
    assert 'workspace' not in pr and 'target_ref' not in pr


def test_work_detail_http_includes_pr_contract(home):
    from fastapi.testclient import TestClient
    from test_sessions_api import make_project

    from claudio_maestro.agent.fake import FakeAgentFactory
    from claudio_maestro.app import create_app
    app = create_app(agent_factory=FakeAgentFactory())
    with TestClient(app, base_url='http://127.0.0.1:6660', headers={
        'origin': 'http://localhost:6600', 'x-maestro': '1'}) as client:
        project = make_project(client, home)
        item = client.post('/api/work-items', json={'project_id': project['id'],
            'title': 'Revisar PR', 'objective': 'Conferir autoria', 'ready': False}).json()
        detail = client.get(f"/api/work-items/{item['id']}")
        assert detail.status_code == 200
        assert detail.json()['pull_requests'] == {'items': [], 'total': 0, 'limit': 25}


async def test_feedback_obeys_task_quota_without_changing_input(world, monkeypatch):
    item, author = await register(world)
    await finish(world, author)
    original = world.service.dossier(item.id)
    world.service.max_tasks = 1
    await world.delegate(external_id='other')
    def forbidden(*args, **kwargs):
        pytest.fail('Cota já cheia não deve nem preparar outra sessão.')
    monkeypatch.setattr(world.manager, 'create_session_in_transaction', forbidden)
    world.prs.bridge.queue_comment(comment())
    with closing(db.connect(world.db_path)) as conn:
        before = conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    for _ in range(3):
        await world.prs.bridge.deliver()
        with closing(db.connect(world.db_path)) as conn:
            assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == before
    assert len(world.attempts(item.id)) == 1
    assert world.service.dossier(item.id) == original
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT status FROM work_pr_comments').fetchone()[0] == 'queued'
        assert conn.execute('SELECT COUNT(*) FROM work_pr_inbox').fetchone()[0] == 0


async def test_comment_admission_rejects_fence_and_legacy_inside_transaction(world):
    await register(world)
    with closing(db.connect(world.db_path)) as conn:
        conn.execute('INSERT INTO work_project_fences VALUES (?,?,?,?)', (world.project.id, 'fenced', 'delete', 100))
    with pytest.raises(store.WorkConflictError):
        world.prs.bridge.queue_comment(comment())
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_pr_comments').fetchone()[0] == 0
        conn.execute('DELETE FROM work_project_fences')
        conn.execute('UPDATE work_project_modes SET enabled=0')
    with pytest.raises(store.WorkConflictError):
        world.prs.bridge.queue_comment(comment())
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_pr_comments').fetchone()[0] == 0
        conn.execute('UPDATE work_project_modes SET enabled=1,paused=1')
    assert world.prs.bridge.queue_comment(comment())


async def test_pr_state_changes_invalidate_ui_even_without_item_revision_change(world):
    item, _ = await register(world)
    world.prs.publish_pr_changes()
    world.recorder.envelopes.clear()
    revision = world.item(item.id).revision
    world.prs.bridge.queue_comment(comment())
    world.prs.publish_pr_changes()
    events = [e for e in world.recorder.envelopes if e['type'] == 'work.changed']
    assert events[-1]['data'] == {'item_id': item.id, 'project_id': world.project.id, 'revision': revision}
    world.recorder.envelopes.clear()
    world.prs.publish_pr_changes()
    assert not world.recorder.envelopes


async def test_background_pr_worker_survives_temporary_registration_failure(world, monkeypatch):
    import asyncio
    from contextlib import suppress
    calls = []
    async def flaky():
        calls.append(True)
        if len(calls) == 1:
            raise OSError('temporary database outage')
    monkeypatch.setattr(world.prs, 'register_pending', flaky)
    task = asyncio.create_task(world.prs.run(interval=.01))
    try:
        await asyncio.sleep(.05)
        assert not task.done()
        assert len(calls) > 1
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError, OSError):
            await task


async def test_feedback_uses_declared_subrepository_when_project_root_is_not_git(world, monkeypatch):
    from pathlib import Path
    item = await world.delegate(role='implementer')
    await world.service.dispatch_once()
    author = world.attempts(item.id)[0]
    await world.pause.reached.wait()
    workspace = Path(world.project.path) / 'actual-repo'
    workspace.mkdir()
    async def only_subrepo(conn, project_id, supplied):
        if supplied != str(workspace):
            raise store.WorkValidationError('A raiz do projeto contém subrepos; não é Git.')
        return Path(world.project.path), workspace
    monkeypatch.setattr('claudio_maestro.work.pr_integration.project_repo', only_subrepo)
    await world.service.declare_workspaces(author.session_id, workspaces=[str(workspace)])
    world.prs.on_pr_created(author.session_id, URL)
    await world.prs.register_pending()
    assert world.prs.bridge.find(URL)['workspace'] == str(workspace)
    await finish(world, author)
    world.prs.bridge.queue_comment(comment())
    await world.prs.bridge.deliver()
    assert len(world.attempts(item.id)) == 2
    with closing(db.connect(world.db_path)) as conn:
        row = conn.execute('SELECT paths_ref FROM work_attempt_workspaces WHERE attempt_id=?', (world.attempts(item.id)[-1].id,)).fetchone()
    assert world.service.files.read(row['paths_ref'])['workspaces'] == [str(workspace)]
