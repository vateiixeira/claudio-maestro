"""Agent chat API shares the protected session composer endpoint."""

from .test_api import agent, api, events, factory, project, wait_for  # noqa: F401


def test_open_resume_and_send_in_the_same_conversation(api, agent, factory):
    url = f"/api/specialists/{agent['id']}/conversations"
    opened = api.post(url)
    assert opened.status_code == 201, opened.text
    sid = opened.json()['session_id']
    assert api.post(url).json()['session_id'] == sid
    assert not factory.clients
    response = api.post(f'/api/sessions/{sid}/messages', json={'text': 'Olá'})
    assert response.status_code == 202, response.text
    wait_for(lambda: factory.clients and factory.clients[0].sent == ['Olá'])
    assert api.get(url).json()[0]['session_id'] == sid
    other = api.post(url, json={'new': True}).json()['session_id']
    assert other != sid


def test_chat_composer_queues_while_paused_and_exposes_cancellation(api, agent, factory):
    sid = api.post(f"/api/specialists/{agent['id']}/conversations").json()['session_id']
    api.patch(f"/api/specialists/{agent['id']}", json={'queue_paused': True})
    response = api.post(f'/api/sessions/{sid}/messages', json={'text': 'Mensagem em espera'})
    assert response.status_code == 202
    assert response.json()['queued'] is True
    run_id = response.json()['run_id']
    assert not factory.clients
    runs = api.get(f"/api/specialists/{agent['id']}/runs").json()
    assert runs[0]['message'] is True and runs[0]['session_id'] == sid
    assert api.post(f"/api/specialists/{agent['id']}/runs/{run_id}/cancel").status_code == 200


def test_conversation_requires_header_and_rejects_foreign_session(api, agent):
    url = f"/api/specialists/{agent['id']}/conversations"
    assert api.post(url, json={'session_id': 'missing'}).status_code == 404
    api.headers.pop('x-maestro')
    assert api.post(url).status_code == 403
    assert api.get(url).status_code == 403


def test_pending_message_preview_is_scoped_to_its_agent_and_session(api, agent):
    sid = api.post(f"/api/specialists/{agent['id']}/conversations").json()['session_id']
    api.patch(f"/api/specialists/{agent['id']}", json={'queue_paused': True})
    api.post(f'/api/sessions/{sid}/messages', json={'text': 'Distinguir esta mensagem'})
    response = api.get(f"/api/specialists/{agent['id']}/messages", params={'session_id': sid})
    assert response.status_code == 200
    assert response.json()[0]['text'] == 'Distinguir esta mensagem'
    assert api.get(f"/api/specialists/{agent['id']}/messages", params={'session_id': 'outro'}).status_code == 404


def test_terminal_output_also_respects_the_agents_paused_queue(api, agent, factory):
    sid = api.post(f"/api/specialists/{agent['id']}/main").json()['session_id']
    api.patch(f"/api/specialists/{agent['id']}", json={'queue_paused': True})
    accepted = api.portal.call(api.app.state.terminals._send_message, sid, 'Saída do terminal')
    assert accepted is True
    assert not factory.clients
    runs = api.get(f"/api/specialists/{agent['id']}/runs").json()
    assert len(runs) == 1 and runs[0]['outcome'] == 'queued' and runs[0]['message']
