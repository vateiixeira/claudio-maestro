"""Automatic remote reconnect uses admission; manual messages remain explicit."""

import time
from contextlib import closing
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_sessions import env_cleanup, make_env  # noqa: F401
from test_sessions_api import make_project

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, text_turn
from claudio_maestro.app import create_app
from claudio_maestro.config import load_settings
from claudio_maestro.sessions import SessionManager
from claudio_maestro.work import store as work_store
from claudio_maestro.work.files import WorkFiles
from claudio_maestro.work.service import WorkService


@pytest.mark.parametrize('kind,scheduler,dispatcher,remote,fenced,expected', [
    ('work', True, False, True, False, False),
    ('legacy', False, True, True, False, False),
    ('manual', True, True, False, False, False),
    ('manual', True, False, True, False, True),
    ('work', True, True, True, False, True),
    ('work_ended', True, True, True, False, False),
    ('legacy', True, True, True, False, True),
    ('manual', True, True, True, True, False),
    ('legacy', True, True, True, True, False),
])
def test_boot_remote_admission_and_manual_send(home, kind, scheduler, dispatcher, remote, fenced, expected):
    factory = FakeAgentFactory(script=lambda content: text_turn(factory.clients[-1].options.session_id, 'feito'))
    settings = replace(load_settings(), remote_reconnect=False, specialists_scheduler=False, work_dispatcher=False)
    headers = {'origin': 'http://localhost:6600', 'x-maestro': '1'}
    with TestClient(create_app(settings=settings, agent_factory=factory), base_url='http://127.0.0.1:6660', headers=headers) as api:
        project = make_project(api, home)
        if kind == 'work_ended':
            item = api.post('/api/work-items', json={'project_id': project['id'], 'title': 'Já finalizada', 'objective': 'Histórico'}).json()
            sid = api.post(f"/api/projects/{project['id']}/sessions").json()['session_id']
            with closing(db.connect(settings.db_path)) as conn:
                attempt = work_store.claim_attempt(conn, item['id'], expected_revision=item['revision'], session_id=sid, now=1)
                work_store.mark_dispatching(conn, attempt.id, now=2)
                work_store.mark_running(conn, attempt.id, now=3)
                ref = api.app.state.work.files.write({'summary': 'Terminada'})
                work_store.finish_attempt(conn, attempt.id, outcome='succeeded', result_kind='investigation', result_ref=ref, turn_ended=True, now=4)
        elif kind == 'work':
            sid = api.post(f"/api/projects/{project['id']}/cto").json()['session_id']
            api.post(f"/api/projects/{project['id']}/work-mode", json={'action': 'enable'})
        elif kind == 'legacy':
            owner = api.post('/api/specialists', json={'name': 'Source', 'slug': 'source', 'project_id': project['id']}).json()
            sid = api.post(f"/api/specialists/{owner['id']}/main").json()['session_id']
        else:
            sid = api.post(f"/api/projects/{project['id']}/sessions").json()['session_id']
        with closing(db.connect(settings.db_path)) as conn:
            conn.execute('UPDATE sessions SET remote_control=1 WHERE session_id=?', (sid,))
        if fenced:
            api.app.state.work.reserve_project_deletion(project['id'])
            api.app.state.work.release_deletion_owner(project['id'])
    assert not factory.clients
    live = replace(settings, remote_reconnect=remote, specialists_scheduler=scheduler, work_dispatcher=dispatcher)
    with TestClient(create_app(settings=live, agent_factory=factory, history_exists=lambda sid, cwd: True), base_url='http://127.0.0.1:6660', headers=headers) as api:
        deadline = time.monotonic() + .4
        while time.monotonic() < deadline:
            if factory.clients:
                break
            time.sleep(.01)
        assert bool(factory.clients) is expected
        if not expected and not fenced and kind != 'work_ended':
            response = api.post(f'/api/sessions/{sid}/messages', json={'text': 'mensagem manual explícita'})
            assert response.status_code == 202, response.text
            deadline = time.monotonic() + 1
            while not factory.clients and time.monotonic() < deadline:
                time.sleep(.01)
            assert factory.clients


@pytest.mark.anyio
async def test_remote_rechecks_admission_after_history_await(make_env, env_cleanup, monkeypatch):
    env = make_env()
    env_cleanup.append(env.manager)
    record = env.new_session()
    record.save(remote_control=True)
    blocked = False
    boot = SessionManager(env.db_path, env.recorder, agent_factory=env.factory,
        history_exists=lambda *args: True, remote_reconnect_allowed=lambda record: not blocked)
    env_cleanup.append(boot)
    session = boot.get(record.session_id)

    async def history_was_read():
        nonlocal blocked
        blocked = True

    monkeypatch.setattr(session, 'ensure_history', history_was_read)
    await boot.reconnect_remote_sessions()
    assert not env.factory.clients


@pytest.mark.anyio
async def test_quiet_remote_connect_is_not_mistaken_for_quiescence(make_env, env_cleanup, tmp_path):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.error = 'erro anterior'
    session._quiet_connect = True
    session._connecting = True
    session._refresh_state()
    assert session.state == 'error'
    service = WorkService(env.db_path, sessions=env.manager, files=WorkFiles(tmp_path / 'work'), publish=env.recorder)
    assert service._open(session.session_id)
