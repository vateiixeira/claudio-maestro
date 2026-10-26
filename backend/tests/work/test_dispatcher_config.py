"""Copies must never dispatch preexisting work unless explicitly enabled."""

import shutil
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from test_sessions import Recorder, make_project

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, text_turn
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings, load_settings
from claudio_maestro.sessions import SessionManager
from claudio_maestro.work.files import WorkFiles
from claudio_maestro.work.service import WorkService


@pytest.mark.parametrize('scheduler, explicit, expected', [('0', None, False), ('1', None, True), ('0', '1', True), ('1', '0', False)])
def test_dispatcher_setting_respects_copy_flag_and_explicit_override(monkeypatch, scheduler, explicit, expected):
    monkeypatch.setenv('MAESTRO_SPECIALISTS_SCHEDULER', scheduler)
    if explicit is None:
        monkeypatch.delenv('MAESTRO_WORK_DISPATCHER', raising=False)
    else:
        monkeypatch.setenv('MAESTRO_WORK_DISPATCHER', explicit)
    assert load_settings().work_dispatcher_enabled is expected


@pytest.mark.parametrize('scheduler, override, expected', [(False, None, False), (True, False, False), (False, True, True)])
def test_seeded_ready_work_obeys_dispatcher_in_lifespan(tmp_path, monkeypatch, scheduler, override, expected):
    path = tmp_path / 'copy.db'
    db.init_db(path)
    project = make_project(path, tmp_path / 'home' / 'project')
    factory = FakeAgentFactory(script=lambda content: text_turn(factory.clients[-1].options.session_id, 'feito'))
    manager = SessionManager(path, Recorder(), agent_factory=factory)
    service = WorkService(path, sessions=manager, files=WorkFiles(tmp_path / 'work'), publish=lambda event: None)
    item = service.create_item(project_id=project.id, title='Ready before bootstrap', objective='Não executar automaticamente em cópia')
    # Reuse the DB as a copied data directory. No SDK or source side effects.
    data = tmp_path / 'copy'
    data.mkdir()
    shutil.copytree(tmp_path / 'work', data / 'work')
    with closing(db.connect(path)) as source, closing(db.connect(data / 'maestro.db')) as target:
        source.backup(target)
    settings = Settings(home_dir=tmp_path / 'home', data_dir=data,
        specialists_scheduler=scheduler, work_dispatcher=override)
    app = create_app(settings=settings, agent_factory=factory)
    with TestClient(app, base_url='http://127.0.0.1:6660', headers={'origin': 'http://localhost:6600', 'x-maestro': '1'}) as api:
        deadline = time.monotonic() + .4
        while time.monotonic() < deadline:
            if factory.clients:
                break
            time.sleep(.01)
        assert bool(factory.clients) is expected
        if not expected:
            assert api.portal.call(app.state.work.dispatch_once) is None
            with closing(db.connect(data / 'maestro.db')) as conn:
                assert conn.execute('SELECT COUNT(*) FROM work_attempts WHERE work_item_id=?', (item.id,)).fetchone()[0] == 0
            # Direct manual conversation remains an explicit user action.
            sid = api.post(f'/api/projects/{project.id}/cto').json()['session_id']
            assert api.post(f'/api/sessions/{sid}/messages', json={'text': 'mensagem manual explícita'}).status_code == 202
            assert factory.clients
