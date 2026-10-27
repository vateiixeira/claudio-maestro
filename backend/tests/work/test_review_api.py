"""F4 HTTP contracts and security over isolated app+FakeAgentFactory."""
from test_api import api, create, wait_for  # noqa: F401
from test_sessions_api import make_project


def test_review_and_human_decision_http_contract(api, home, monkeypatch):
    async def capture(project, workspace, **kwargs):
        return {'complete': True, 'digest': 'api-target', 'workspace': str(workspace), 'head': 'h'}
    monkeypatch.setattr('claudio_maestro.work.targets.capture_target', capture)
    project = make_project(api, home)
    cto = api.post(f"/api/projects/{project['id']}/cto").json()
    item = create(api, project, ready=True)
    detail_url = f"/api/work-items/{item['id']}"
    author = wait_for(lambda: (api.get(detail_url).json()['attempts'] or [None])[0])
    wait_for(lambda: api.get(f"/api/sessions/{author['session_id']}").json()['state'] == 'running')
    decision = api.portal.call(lambda: api.app.state.work.request_decision(author['session_id'], question='Excluir old.py?', action='Excluir somente old.py', options=['sim','não'], evidence=['old.py:1']))
    pending = api.get('/api/work/decisions', params={'project_id': project['id']}).json()['items']
    assert pending[0]['id'] == decision['id'] and pending[0]['request']['options'] == ['sim','não']
    answer_url = f"/api/work/decisions/{decision['id']}/answer"
    body = {'expected_revision': decision['revision'], 'receipt': 'human-http', 'answer': 'não'}
    for headers in ({'x-maestro': ''}, {'origin': 'https://attacker.test'}, {'host': 'attacker.test'}):
        assert api.post(answer_url, json=body, headers=headers).status_code in (400,403)
    answered = api.post(answer_url, json=body)
    assert answered.status_code == 202, answered.text
    assert api.post(answer_url, json=body).json() == answered.json()
    assert len(api.get(detail_url).json()['attempts']) == 1
    feed = api.get(f"/api/projects/{project['id']}/work-feed").json()['items']
    assert feed and all(n['coordinator_session_id'] == cto['session_id'] for n in feed)
    assert api.post(f"/api/projects/{project['id']}/work-feed/seen", json={'through': feed[-1]['id']}).status_code == 200
    assert api.get('/api/work/notifications', params={'project_id': project['id']}).json()['items'][0]['seen_at'] is not None
    detail = api.get(detail_url).json()
    assert detail['decisions'][0]['status'] == 'answered' and detail['reviews'] == []


def test_worker_to_independent_review_to_done_http(api, home, monkeypatch):
    async def capture(project, workspace, **kwargs):
        return {'complete': True, 'digest': 'api-target', 'workspace': str(workspace), 'head': 'h'}
    monkeypatch.setattr('claudio_maestro.work.targets.capture_target', capture)
    project = make_project(api, home)
    cto = api.post(f"/api/projects/{project['id']}/cto").json()
    item = api.portal.call(lambda: api.app.state.work.delegate(cto['session_id'], title='Analisar #55', objective='Explicar guarda'))
    detail_url = f'/api/work-items/{item.id}'
    author = wait_for(lambda: (api.get(detail_url).json()['attempts'] or [None])[0])
    wait_for(lambda: api.get(f"/api/sessions/{author['session_id']}").json()['state'] == 'running')
    api.portal.call(lambda: api.app.state.work.conclude(author['session_id'], result_kind='investigation', summary='Fluxo e guarda rastreados', evidence=['guard.py:10']))
    api.portal.call(api.pause.release.set)
    reviewer = wait_for(lambda: next((a for a in api.get(detail_url).json()['attempts'] if a['role'] == 'reviewer'), None))
    binding = api.get(f'/api/work-items/{item.id}/reviews').json()['items'][0]
    assert reviewer['session_id'] != author['session_id']
    wait_for(lambda: api.get(f"/api/sessions/{reviewer['session_id']}").json()['state'] in ('idle','closed'))
    api.portal.call(lambda: api.app.state.work.submit_review(reviewer['session_id'], binding_id=binding['id'], disposition='approve', summary='Análise completa suficiente', evidence=['guard.py:10']))
    detail = wait_for(lambda: (v if (v := api.get(detail_url).json())['item']['status'] == 'done' else None))
    assert detail['reviews'][0]['status'] == 'approved'


def test_latest_feed_is_bounded_after_100_and_preserves_cursor_and_read_receipt(api, home):
    from contextlib import closing

    from claudio_maestro import db
    project = make_project(api, home)
    api.post(f"/api/projects/{project['id']}/cto")
    api.post(f"/api/projects/{project['id']}/work-mode", json={'action': 'pause'})
    item = create(api, project)
    with closing(db.connect(api.app.state.work.db_path)) as conn:
        for n in range(150):
            conn.execute('INSERT INTO work_events(work_item_id,kind,actor,revision,data,created_at) VALUES (?,?,?,?,?,?)', (item['id'], 'item_updated', 'test', item['revision'], '{}', n))
    path = f"/api/projects/{project['id']}/work-feed"
    older = api.get(path, params={'limit': 100}).json()
    latest = api.get(path, params={'latest': True, 'limit': 5}).json()
    assert len(latest['items']) == 5
    assert latest['after'] > older['after']
    assert latest['after'] == max(row['id'] for row in latest['items'])
    assert [r['id'] for r in latest['items']] == sorted(r['id'] for r in latest['items'])
    assert api.get('/api/work/notifications', params={'latest': True, 'limit': 5}).json()['after'] == latest['after']
    assert api.get(path, params={'after': latest['after']}).json()['items'] == []
    api.post(path + '/seen', json={'through': latest['after']})
    assert all(r['seen_at'] is not None for r in api.get(path, params={'latest': True, 'limit': 5}).json()['items'])


def test_activity_shows_latest_and_pages_all_older_events_without_gaps(api, home):
    from contextlib import closing

    from claudio_maestro import db
    project = make_project(api, home)
    item = create(api, project)
    with closing(db.connect(api.app.state.work.db_path)) as conn:
        for n in range(210):
            conn.execute('INSERT INTO work_events(work_item_id,kind,actor,revision,data,created_at) VALUES(?,?,?,?,?,?)', (item['id'], 'item_updated', 'test', item['revision'], '{}', n))
        expected = [row[0] for row in conn.execute('SELECT id FROM work_events WHERE work_item_id=? ORDER BY id', (item['id'],))]
    url = f"/api/work-items/{item['id']}"
    detail = api.get(url).json()
    assert [e['id'] for e in detail['events']] == expected[-50:]
    assert detail['events_page']['has_more']
    assert detail['events_page']['limit'] == 50
    found = [e['id'] for e in detail['events']]
    page = detail['events_page']
    while page['has_more']:
        response = api.get(url + '/events', params={'before': page['before'], 'limit': 50})
        assert response.status_code == 200, response.text
        page = response.json()
        ids = [e['id'] for e in page['items']]
        assert ids == sorted(ids) and len(ids) <= 50
        assert not set(ids).intersection(found)
        found = ids + found
    assert found == expected
    assert api.get(url + '/events', params={'limit': 201}).status_code == 422
    assert api.get(url + '/events', params={'before': 0}).status_code == 422
    assert api.get('/api/work-items/999999/events').status_code == 404
