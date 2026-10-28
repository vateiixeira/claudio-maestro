"""Work HTTP routes run only against isolated data and a scripted agent."""

import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import make_project

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, PauseStep, text_turn
from claudio_maestro.app import create_app


@pytest.fixture
def api():
    pause = PauseStep()
    factory = FakeAgentFactory(script=lambda content: [pause, *text_turn(factory.clients[-1].options.session_id, 'feito')])
    app = create_app(agent_factory=factory, history_exists=lambda sid, cwd: any(c.options.session_id == sid and c.sent for c in factory.clients))
    with TestClient(app, base_url='http://127.0.0.1:6660', headers={'origin': 'http://localhost:6600', 'x-maestro': '1'}) as client:
        client.factory, client.pause = factory, pause
        yield client


def create(api, project, **changes):
    body = {'project_id': project['id'], 'title': 'Rastrear websocket', 'objective': 'Investigar fluxo e guardas', 'ready': False, **changes}
    response = api.post('/api/work-items', json=body)
    assert response.status_code == 201, response.text
    return response.json()


def wait_for(read, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError('condição não atendida')


def agent(api, project):
    response = api.post('/api/agents', json={'name': 'Agente', 'slug': 'agente', 'project_id': project['id']})
    assert response.status_code == 201, response.text
    return response.json()


def test_cto_is_idempotent_per_project_and_has_normal_context(api, home):
    project = make_project(api, home)
    first = api.post(f"/api/projects/{project['id']}/cto")
    assert first.status_code == 200
    body = first.json()
    assert body['session_id'] == api.post(f"/api/projects/{project['id']}/cto").json()['session_id']
    assert body['project_id'] == project['id']
    assert api.get('/api/work/sessions').json()[body['session_id']]['work_role'] == 'coordinator'
    response = api.post(f"/api/sessions/{body['session_id']}/messages", json={'text': 'Analise este projeto'})
    assert response.status_code == 202, response.text
    assert api.factory.clients[-1].options.setting_sources is None
    assert api.factory.clients[-1].options.settings is None
    assert 'maestro_work' in api.factory.clients[-1].options.mcp_servers


def test_create_list_detail_and_source_namespaces(api, home):
    project = make_project(api, home)
    item = create(api, project, source='kbgen', source_instance='org', source_project='body', external_id='50')
    duplicate = create(api, project, source='kbgen', source_instance='org', source_project='body', external_id='50')
    assert duplicate['id'] == item['id']
    other = create(api, project, source='sentry', external_id='50')
    page = api.get('/api/work-items', params={'source': 'kbgen', 'project_id': project['id'], 'status': 'backlog', 'limit': 1}).json()
    assert page['total'] == 1 and [row['id'] for row in page['items']] == [item['id']]
    assert api.get('/api/work-items', params={'offset': 1, 'limit': 1}).json()['total'] == 2
    detail = api.get(f"/api/work-items/{item['id']}").json()
    assert detail['dossier']['objective'] == 'Investigar fluxo e guardas'
    assert detail['item']['id'] == item['id']
    assert detail['attempts'] == [] and detail['events'] and detail['dependencies'] == []
    assert other['id'] != item['id']


def test_edit_private_objective_is_optimistic_and_atomic(api, home):
    project = make_project(api, home)
    item = create(api, project)
    changed = api.patch(f"/api/work-items/{item['id']}", json={'expected_revision': item['revision'], 'objective': 'Rastrear também o frontend', 'acceptance': 'Evidenciar guards'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['revision'] == item['revision'] + 1
    assert api.get(f"/api/work-items/{item['id']}").json()['dossier']['objective'] == 'Rastrear também o frontend'
    assert api.patch(f"/api/work-items/{item['id']}", json={'expected_revision': item['revision'], 'title': 'Stale'}).status_code == 409
    current = changed.json()
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        conn.execute("CREATE TRIGGER reject_spec BEFORE UPDATE ON work_specs BEGIN SELECT RAISE(ABORT, 'write failed'); END")
    with pytest.raises(Exception, match='write failed'):
        api.patch(f"/api/work-items/{item['id']}", json={'expected_revision': current['revision'], 'title': 'não pode ficar', 'objective': 'não pode ficar'})
    detail = api.get(f"/api/work-items/{item['id']}").json()
    assert detail['item']['title'] == item['title']
    assert detail['item']['revision'] == current['revision']
    assert detail['dossier']['objective'] == 'Rastrear também o frontend'


def test_http_start_result_and_finish_guard_use_real_service(api, home):
    project = make_project(api, home)
    item = create(api, project)
    response = api.post(f"/api/work-items/{item['id']}/start", json={'expected_revision': item['revision']})
    assert response.status_code == 202, response.text
    attempt = wait_for(lambda: (api.get(f"/api/work-items/{item['id']}").json()['attempts'] or [None])[0])
    sid = attempt['session_id']
    wait_for(lambda: api.get(f'/api/sessions/{sid}').json()['state'] == 'running')
    catalog = api.get('/api/work/sessions').json()
    assert catalog[sid]['work_item_id'] == item['id']
    assert api.patch(f'/api/sessions/{sid}', json={'finished': True}).status_code == 409
    assert api.delete(f"/api/projects/{project['id']}").status_code == 409
    api.portal.call(lambda: api.app.state.work.conclude(sid, result_kind='investigation', summary='Guarda rastreada', evidence=['src/ws.py:10'], tests=['Não executados']))
    api.portal.call(api.pause.release.set)
    detail = wait_for(lambda: (value if (value := api.get(f"/api/work-items/{item['id']}").json())['item']['status'] == 'review' else None))
    assert detail['attempts'][0]['result']['summary'] == 'Guarda rastreada'
    assert api.post(f'/api/sessions/{sid}/messages', json={'text': 'não alterar histórico'}).status_code == 409
    assert not api.portal.call(lambda: api.app.state.terminals._send_message(sid, 'Saída do terminal não pode reabrir histórico'))


def test_invalid_work_payload_and_security_do_not_mutate(api, home):
    project = make_project(api, home)
    assert api.post('/api/work-items', json={'project_id': project['id'], 'title': 'x', 'objective': '', 'cwd': '/tmp'}).status_code == 422
    assert api.get('/api/work-items/999').status_code == 404
    assert api.get('/api/work-items', headers={'x-maestro': ''}).status_code == 403
    assert api.post(f"/api/projects/{project['id']}/cto", headers={'origin': 'https://evil.example'}).status_code == 403
    assert api.get('/api/work-items', headers={'host': 'evil.example'}).status_code == 400
    assert not api.get(f"/api/projects/{project['id']}/work-mode").json()['enabled']


def test_private_patch_rejects_empty_or_null_and_active_state_override(api, home):
    project = make_project(api, home)
    item = create(api, project)
    for field, value in [('objective', '  '), ('objective', None), ('title', None)]:
        response = api.patch(f"/api/work-items/{item['id']}", json={'expected_revision': item['revision'], field: value})
        assert response.status_code == 422, response.text
    api.post(f"/api/work-items/{item['id']}/start", json={'expected_revision': item['revision']})
    detail = wait_for(lambda: (v if (v := api.get(f"/api/work-items/{item['id']}").json())['attempts'] else None))
    response = api.patch(f"/api/work-items/{item['id']}", json={'expected_revision': detail['item']['revision'], 'status': 'cancelled'})
    assert response.status_code == 409


def test_pause_and_resume_and_unknown_projects(api, home):
    project = make_project(api, home)
    path = f"/api/projects/{project['id']}/work-mode"
    assert api.post(path, json={'action': 'enable'}).json() == {'enabled': True, 'paused': False}
    assert api.post(path, json={'action': 'pause'}).json()['paused']
    assert not api.post(path, json={'action': 'resume'}).json()['paused']
    assert not api.post(path, json={'action': 'disable'}).json()['enabled']
    assert api.post('/api/projects/999/cto').status_code == 404
    assert api.post('/api/projects/999/work-mode', json={'action': 'enable'}).status_code == 404


def test_delete_fence_blocks_admission_during_await_and_can_be_cancelled(api, home, monkeypatch):
    project = make_project(api, home)
    attempts = []

    async def close_in_flight(project_id):
        # The hook runs on the app loop after the deletion fence is reserved.
        from claudio_maestro.work import store
        with pytest.raises(store.WorkConflictError):
            api.app.state.work.create_item(project_id=project_id, title='racing', objective='must not run')
        with pytest.raises(store.WorkConflictError):
            api.app.state.work.coordinator(project_id)
        attempts.append('blocked')
        raise RuntimeError('closing failed')

    monkeypatch.setattr(api.app.state.sessions, 'close_project', close_in_flight)
    with pytest.raises(RuntimeError, match='closing failed'):
        api.delete(f"/api/projects/{project['id']}")
    assert attempts == ['blocked']
    mode = api.get(f"/api/projects/{project['id']}/work-mode").json()
    assert mode['deleting'] and mode['fence_id']
    assert api.post('/api/work-items', json={'project_id': project['id'], 'title': 'still blocked', 'objective': 'still blocked'}).status_code == 409
    assert api.post(f"/api/projects/{project['id']}/work-mode", json={'action': 'cancel_delete', 'fence_id': 'stale'}).status_code == 409
    assert api.post(f"/api/projects/{project['id']}/work-mode", json={'action': 'cancel_delete', 'fence_id': mode['fence_id']}).status_code == 200
    assert not api.get(f"/api/projects/{project['id']}/work-mode").json().get('deleting', False)


def test_terminal_uses_managed_admission_and_fence_survives_recovery(api, home, monkeypatch):
    project = make_project(api, home)
    sid = api.post(f"/api/projects/{project['id']}/cto").json()['session_id']
    sent = []

    async def send(session_id, text, images=None):
        sent.append((session_id, text))
        return {'send_started': True, 'state': 'idle'}

    monkeypatch.setattr(api.app.state.work, 'send_message', send)
    assert api.portal.call(lambda: api.app.state.terminals._send_message(sid, 'Saída de teste'))
    assert sent == [(sid, 'Saída de teste')]
    fence = api.app.state.work.reserve_project_deletion(project['id'])
    api.app.state.work.release_deletion_owner(project['id'])
    api.portal.call(api.app.state.work.recover)
    assert api.get(f"/api/projects/{project['id']}/work-mode").json()['fence_id'] == fence
    assert not api.portal.call(lambda: api.app.state.terminals._send_message(sid, 'Bloqueada durante exclusão'))
    assert sent == [(sid, 'Saída de teste')]
    assert api.post(f"/api/projects/{project['id']}/sessions").status_code == 409
    assert api.post(f'/api/sessions/{sid}/messages', json={'text': 'Bloqueada'}).status_code == 409
    response = api.delete(f"/api/projects/{project['id']}", params={'fence_id': fence})
    assert response.status_code == 204, response.text


@pytest.mark.parametrize('managed', [False, True])
def test_stale_normal_client_cannot_start_after_project_cascade(api, home, managed):
    project = make_project(api, home)
    route = 'cto' if managed else 'sessions'
    sid = api.post(f"/api/projects/{project['id']}/{route}").json()['session_id']
    session = api.app.state.sessions.get(sid)
    assert api.delete(f"/api/projects/{project['id']}").status_code == 204
    count = len(api.factory.clients)

    async def late_background_connect():
        async with session._lock:
            return await session._connect()

    assert not api.portal.call(late_background_connect)
    assert len(api.factory.clients) == count


@pytest.mark.parametrize('kind', ['coordinator', 'uncertain_worker', 'agent'])
def test_held_process_reattaches_under_fence_without_starting_a_new_turn(api, home, kind):
    import os
    from types import SimpleNamespace

    from claudio_maestro.work import store as work_store

    project = make_project(api, home)
    if kind == 'agent':
        owner = agent(api, project)
        sid = api.post(f"/api/agents/{owner['id']}/main").json()['session_id']
    elif kind == 'coordinator':
        sid = api.post(f"/api/projects/{project['id']}/cto").json()['session_id']
    else:
        item = create(api, project)
        sid = api.post(f"/api/projects/{project['id']}/sessions").json()['session_id']
        with closing(db.connect(api.app.state.settings.db_path)) as conn:
            item_record = work_store.update_item(conn, item['id'], expected_revision=item['revision'], status='ready', now=1)
            attempt = work_store.claim_attempt(conn, item['id'], expected_revision=item_record.revision, session_id=sid, now=1)
            work_store.mark_dispatching(conn, attempt.id, now=2)
            work_store.mark_uncertain(conn, attempt.id, now=3)
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        conn.execute("INSERT INTO work_project_fences VALUES (?, 'held-process', 'conciliação', 4)", (project['id'],))
    session = api.app.state.sessions.get(sid)
    child = SimpleNamespace(id='held-child', pid=os.getpid(), ack=0, init=None)
    assert api.portal.call(session.reattach, child)
    client = api.factory.clients[-1]
    assert client.options.attach is not None
    assert client.sent == []
    if kind != 'agent':
        assert 'maestro_work' in client.options.mcp_servers


def test_collection_http_is_project_scoped_compact_and_closed(api, home):
    project = make_project(api, home)
    other = make_project(api, home, name='other')
    body = {'source': 'kbgen', 'source_instance': 'local', 'source_project': 'app', 'query': 'status:open'}
    response = api.post(f"/api/projects/{project['id']}/collections", json=body)
    assert response.status_code == 202, response.text
    collection = response.json()
    assert collection['project_id'] == project['id'] and collection['items'] == []
    assert api.get(f"/api/projects/{project['id']}/collections", params={'limit': 1}).json()['total'] == 1
    assert api.get(f"/api/projects/{other['id']}/collections/{collection['id']}").status_code == 404
    assert api.post(f"/api/projects/{project['id']}/collections", json={**body, 'description': 'no body'}).status_code == 422
    assert api.get(f"/api/projects/{project['id']}/collections/{collection['id']}", params={'limit': 201}).status_code == 422
