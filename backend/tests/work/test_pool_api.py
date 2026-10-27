"""Pilot configuration uses the same local API protections and atomic revision."""
from test_api import api  # noqa: F401
from test_sessions_api import make_project


def test_pool_configuration_http_cas_limits_and_security(api, home):
    project = make_project(api, home)
    initial = api.get('/api/work/runtime').json()['pool']
    assert initial['global_limit'] == 1 and initial['maximum'] == 2
    body = {'expected_revision': initial['revision'], 'global_limit': 2,
            'default_project_limit': 1, 'project_id': project['id'],
            'project_limit': 2, 'resources': ['database:shared-test']}
    for headers in ({'x-maestro': ''}, {'origin': 'https://attacker.test'}):
        assert api.patch('/api/work/pool', json=body, headers=headers).status_code == 403
    assert api.patch('/api/work/pool', json={**body, 'global_limit': 3}).status_code == 422
    updated = api.patch('/api/work/pool', json=body)
    assert updated.status_code == 200, updated.text
    current = updated.json()
    assert current['global_limit'] == 2
    assert current['project_limits'][str(project['id'])] == 2
    assert current['resource_config'][str(project['id'])] == ['shared:database:shared-test']
    assert api.patch('/api/work/pool', json=body).status_code == 409
    assert api.get('/api/work/runtime').json()['pool']['revision'] == current['revision']


def test_remote_control_http_refusal_does_not_invalidate_completed_turn(api, home):
    import asyncio

    from test_api import create, wait_for
    project = make_project(api, home)
    item = create(api, project, ready=True)
    author = wait_for(lambda: (api.get(f"/api/work-items/{item['id']}").json()['attempts'] or [None])[0])
    sid = author['session_id']
    wait_for(lambda: api.app.state.sessions.get(sid).state == 'running')
    # Stop only this isolated test's dispatcher, while the fake SDK is paused.
    api.app.state.work._closed = True
    api.portal.call(lambda: asyncio.sleep(.3))
    api.portal.call(lambda: api.app.state.work.request_decision(sid, question='Confirmar ação?'))
    api.portal.call(api.pause.release.set)
    wait_for(lambda: api.app.state.sessions.get(sid).state == 'idle')
    attempt = next(a for a in api.app.state.work._active() if a.id == author['id'])
    assert api.portal.call(lambda: api.app.state.work._close_work_process(attempt))
    before = api.app.state.work._signals(author['id'])
    response = api.patch(f'/api/sessions/{sid}', json={'remote_control': True})
    assert response.status_code == 409, response.text
    assert len(api.factory.clients) == 1
    after = api.app.state.work._signals(author['id'])
    assert after['error_seen'] == before['error_seen'] == 0
    assert after['correlated_result'] == before['correlated_result'] == 1
    api.portal.call(api.app.state.work.reconcile)
    assert api.get(f"/api/work-items/{item['id']}").json()['attempts'][0]['state'] == 'waiting'
    assert api.get('/api/work/runtime').json()['pool']['occupied'] == 0
