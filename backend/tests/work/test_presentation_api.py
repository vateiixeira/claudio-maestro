"""Read-only attention routes use the same isolated app as work API tests."""
from contextlib import closing
from uuid import uuid4

from test_api import api, create  # noqa: F401
from test_sessions_api import make_project

from claudio_maestro import db


def test_overview_and_detail_contract(api, home):
    project = make_project(api, home)
    item = create(api, project)
    response = api.get(f"/api/projects/{project['id']}/work-overview", params={'limit': 1})
    assert response.status_code == 200
    page = response.json()
    assert page['total'] == 1 and page['counts']['inactive'] == 1
    detail = api.get(f"/api/work-items/{item['id']}").json()
    assert page['items'][0] == detail['attention']
    assert api.get('/api/projects/99999/work-overview').status_code == 404
    assert api.get(f"/api/projects/{project['id']}/work-overview?limit=201").status_code == 422


def test_message_origins_batch_is_readonly_scoped_and_bounded(api, home):
    project = make_project(api, home)
    sid = api.post(f"/api/projects/{project['id']}/cto").json()['session_id']
    create(api, project)
    api.app.state.work.persist_notifications()
    dispatch = str(uuid4())
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        conn.execute('UPDATE work_notifications SET dispatch_id=?', (dispatch,))
    params = [('session_id', sid), ('message_ids', dispatch), ('message_ids', 'human')]
    response = api.get('/api/work/message-origins', params=params)
    assert response.status_code == 200
    assert response.json()['items'] == [{'message_id': dispatch, 'origin': 'automation', 'notification_ids': [1]}]
    assert api.get('/api/work/message-origins', params={'session_id': 'other', 'message_ids': dispatch}).json() == {'items': []}
    assert api.get('/api/work/message-origins', params=[('session_id', sid), *[('message_ids', str(uuid4())) for _ in range(201)]]).status_code == 422
