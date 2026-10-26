"""Work context adds prompt/MCPs to normal sessions, never a tool policy."""

import os
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_sessions import Env, fake_history, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import (
    FailStep,
    FakeAgentFactory,
    result_message,
    text_turn,
    tool_turn,
)
from claudio_maestro.sessions import SessionContext, SessionManager
from claudio_maestro.specialists import store

pytestmark = pytest.mark.anyio


@pytest.fixture
async def world(tmp_path):
    factory = FakeAgentFactory()
    env = Env(tmp_path, factory)
    env.server = object()
    env.context_records = []
    env.inits, env.errors, env.prs, env.ends = [], [], [], []
    env.results = []
    env.legacy_inits, env.legacy_errors, env.legacy_prs, env.project_ends = [], [], [], []

    def context(record):
        env.context_records.append(record)
        return SessionContext('Trabalhe na tarefa deste projeto.', {'maestro_work': env.server})

    env.manager = SessionManager(
        env.db_path, env.recorder, agent_factory=factory, history_exists=fake_history(factory),
        context_setup=context,
        on_session_init=lambda sid, servers: env.inits.append((sid, servers)),
        on_session_error=lambda sid, error: env.errors.append((sid, error)),
        on_session_pr_created=lambda sid, url: env.prs.append((sid, url)),
        on_session_turn_end=lambda sid: env.ends.append((sid, env.manager.get(sid).state)),
        on_session_result=lambda sid, result: env.results.append((sid, result)),
        on_init=lambda sid, servers: env.legacy_inits.append((sid, servers)),
        on_turn_error=lambda sid, error: env.legacy_errors.append((sid, error)),
        on_pr_created=lambda sid, url: env.legacy_prs.append((sid, url)),
        on_turn_end=env.project_ends.append,
    )
    factory.script = lambda content: text_turn(factory.clients[-1].options.session_id, 'Pronto.')
    yield env
    await env.manager.shutdown()


async def test_normal_context_preserves_project_configuration(world):
    session = world.new_session()
    session.record.permission_mode = 'acceptEdits'
    await session.send('Investigar')
    await wait_until(lambda: bool(world.ends))
    options = world.factory.clients[-1].options
    assert options.system_prompt_append == 'Trabalhe na tarefa deste projeto.'
    assert options.mcp_servers == {'maestro_work': world.server}
    assert options.setting_sources is None and options.settings is None

    assert options.add_dirs == [] and options.env == {}
    assert options.permission_mode == 'acceptEdits'
    assert options.allow_bypass is True  # Same as any normal session, not enabled by context.
    assert session.record.specialist_id is None and session._extras is None
    assert [record.session_id for record in world.context_records] == [session.session_id]


async def test_context_rebuilt_for_reattach(world):
    session = world.new_session()
    child = SimpleNamespace(id='kept-child', pid=os.getpid(), ack=0, init=None)
    assert await session.reattach(child)
    options = world.factory.clients[-1].options
    assert options.attach is not None and options.resume
    assert options.system_prompt_append == 'Trabalhe na tarefa deste projeto.'
    assert options.mcp_servers == {'maestro_work': world.server}
    assert options.setting_sources is None and options.settings is None

    await session.send('Retomar')
    await wait_until(lambda: bool(world.results))
    assert world.results == [
        (session.session_id, {'is_error': False, 'terminal_reason': 'completed'})
    ]


async def test_context_does_not_replace_normal_permission_protocol(world):
    world.factory.script = lambda content: tool_turn(
        world.factory.clients[-1].options.session_id,
        tool_name='Bash', tool_input={'command': 'arbitrary-project-command'},
        ask_permission=True,
    )
    session = world.new_session()
    await session.send('oi')
    await wait_until(lambda: bool(session.prompts))
    prompt = next(iter(session.prompts.values()))
    assert prompt.tool_name == 'Bash'
    assert session.state == 'awaiting_decision'
    assert not world.ends
    session.resolve_prompt(prompt.prompt_id, 'allow_once')
    await wait_until(lambda: bool(world.ends))
    assert session.error is None


async def test_unmanaged_normal_session_can_have_no_extra_context(world):
    world.manager._context_setup = lambda record: None
    session = world.new_session()
    await session.send('oi')
    await wait_until(lambda: bool(world.ends))
    options = world.factory.clients[-1].options
    assert options.system_prompt_append is None and options.mcp_servers is None


async def test_context_does_not_change_legacy_specialist(world):
    with closing(db.connect(world.db_path)) as conn:
        specialist = store.create_specialist(conn, slug='legacy', name='Legado',
                                            project_id=world.project.id, now=1)
    record = world.manager.create_session(world.project, specialist_id=specialist.id)
    session = world.manager.get(record.session_id)
    await session.send('oi')
    await wait_until(lambda: bool(world.ends))
    options = world.factory.clients[-1].options
    assert not world.context_records
    assert options.system_prompt_append is None and options.mcp_servers is None
    assert options.permission_mode == 'default' and options.allow_bypass is False
    assert world.legacy_inits and world.inits


async def test_normal_lifecycle_reports_identity_after_state_refresh(world):
    session = world.new_session()
    await session.send('oi')
    await wait_until(lambda: bool(world.ends))
    assert world.inits == [(session.session_id, [])]
    assert world.ends == [(session.session_id, 'idle')]
    assert world.project_ends == [world.project.id]
    assert not world.legacy_inits


async def test_normal_error_reaches_new_hook_only(world):
    world.factory.script = lambda content: [FailStep('Falha da execução')]
    session = world.new_session()
    await session.send('oi')
    await wait_until(lambda: bool(world.errors))
    assert world.errors == [(session.session_id, 'Falha da execução')]
    assert not world.legacy_errors and not world.ends


async def test_normal_pr_is_reported_with_origin_session(world):
    url = 'https://github.com/example/app/pull/12'
    world.factory.script = lambda content: tool_turn(
        world.factory.clients[-1].options.session_id,
        tool_name='Bash', tool_input={'command': 'gh pr create --fill'}, result_content=url,
    )
    session = world.new_session()
    await session.send('oi')
    await wait_until(lambda: bool(world.ends))
    assert world.prs == [(session.session_id, url)]
    assert not world.legacy_prs


async def test_hook_failure_does_not_break_normal_turn(world):
    def broken(sid):
        raise RuntimeError('Hook indisponível')

    world.manager._on_session_turn_end = broken
    session = world.new_session()
    await session.send('oi')
    await wait_until(lambda: session.state == 'idle')
    assert session.error is None


async def test_context_failure_refuses_start_without_exposing_private_error(world):
    def broken(record):
        raise RuntimeError('private-token-in-setup')

    world.manager._context_setup = broken
    session = world.new_session()
    assert await session.send('oi') is False
    assert not world.factory.clients
    assert session.error and 'private-token-in-setup' not in session.error


@pytest.mark.parametrize(('is_error', 'terminal_reason'), [
    (False, 'completed'), (True, 'aborted_streaming'), (True, 'error'), (False, None),
])
async def test_result_metadata_precedes_end_hook_and_observes_refreshed_state(
    world, is_error, terminal_reason,
):
    observed = []
    world.manager._on_session_result = lambda sid, result: observed.append(
        ('result', sid, result, world.manager.get(sid).state)
    )
    world.manager._on_session_turn_end = lambda sid: observed.append(('end', sid))
    world.factory.script = lambda content: [result_message(
        world.factory.clients[-1].options.session_id, is_error=is_error,
        terminal_reason=terminal_reason,
    )]
    session = world.new_session()
    await session.send('oi')
    await wait_until(lambda: any(event[0] == 'end' for event in observed))
    assert observed == [
        ('result', session.session_id,
         {'is_error': is_error, 'terminal_reason': terminal_reason}, 'idle'),
        ('end', session.session_id),
    ]


async def test_result_observer_failure_does_not_skip_turn_end(world):
    observed = []

    def broken(sid, result):
        observed.append((sid, result))
        raise RuntimeError('Recibo indisponível')

    world.manager._on_session_result = broken
    session = world.new_session()
    await session.send('oi')
    await wait_until(lambda: bool(world.ends))
    assert observed == [(session.session_id, {'is_error': False, 'terminal_reason': 'completed'})]
    assert session.error is None


async def test_new_connection_admission_does_not_block_existing_process_attach(world):
    calls = []

    def refuse(record):
        calls.append(record.session_id)
        raise RuntimeError('Projeto cercado para exclusão')

    world.manager._connection_admission = refuse
    session = world.new_session()
    assert await session.send('novo processo') is False
    assert not world.factory.clients
    assert calls == [session.session_id]
    child = SimpleNamespace(id='kept-child', pid=os.getpid(), ack=0, init=None)
    assert await session.reattach(child)
    assert len(world.factory.clients) == 1
    assert world.factory.clients[0].options.attach is not None
    assert calls == [session.session_id]
    assert world.factory.clients[0].sent == []
