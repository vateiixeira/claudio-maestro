"""Agent conversations share the persistent queue and preserve their session, offline."""

import asyncio
from contextlib import closing

import pytest
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.specialists import store
from claudio_maestro.specialists.service import SpecialistService

from .test_queue import pause_queue
from .test_service import world  # noqa: F401

pytestmark = pytest.mark.anyio


async def test_open_reuses_the_chat_but_new_chat_starts_another_context(world):
    agent = world.add_specialist()
    first = await world.service.open_conversation(agent)
    assert (await world.service.open_conversation(agent)).session_id == first.session_id
    other = await world.service.open_conversation(agent, new=True)
    assert other.session_id != first.session_id
    assert not world.factory.clients
    assert not world.runs(agent)
    assert len(world.service.conversations(agent)) == 2


async def test_messages_share_the_session_and_complete_without_closing_it(world):
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    first = await world.service.send_message(chat.session_id, 'Primeira pergunta')
    await wait_until(lambda: next(r for r in world.runs(agent) if r.id == first.id).outcome == 'concluded')
    second = await world.service.send_message(chat.session_id, 'Explique melhor')
    await wait_until(lambda: next(r for r in world.runs(agent) if r.id == second.id).outcome == 'concluded')
    assert first.id != second.id
    assert len(world.factory.clients) == 1
    assert world.factory.clients[0].sent == ['Primeira pergunta', 'Explique melhor']
    assert not world.record(chat.session_id).finished
    assert 'não encerra' in world.service.session_setup(world.record(chat.session_id)).system_prompt_append


async def test_paused_chat_message_survives_recovery_and_can_be_cancelled(world):
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    pause_queue(world, agent)
    pending = await world.service.send_message(chat.session_id, 'Não perder esta mensagem')
    assert pending.outcome == 'queued' and pending.session_id == chat.session_id
    assert 'Não perder'.encode() not in world.db_path.read_bytes()
    await world.service.shutdown()
    world.service = SpecialistService(world.db_path, files=world.files, sessions=world.manager,
                                      publish=world.recorder, clock=lambda: world.now, finish_poll=0.005)
    await world.service.recover()
    assert not world.factory.clients
    await world.service.cancel_run(agent, pending.id)
    pause_queue(world, agent, False)
    await world.service.drain_queue()
    assert not world.factory.clients


async def test_queued_message_does_not_hide_the_active_run_or_conclusion(world):
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    pause_queue(world, agent)
    first = await world.service.send_message(chat.session_id, 'Uma')
    second = await world.service.send_message(chat.session_id, 'Duas')
    assert first.id < second.id
    with closing(db.connect(world.db_path)) as conn:
        assert store.run_for_session(conn, chat.session_id) is None
    pause_queue(world, agent, False)
    await world.service.drain_queue()
    await wait_until(lambda: len(world.factory.clients[0].sent) == 2)
    assert world.factory.clients[0].sent == ['Uma', 'Duas']
    assert not world.record(chat.session_id).finished


async def test_conclude_in_a_chat_does_not_finish_or_block_the_next_message(world):
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    await world.service.send_message(chat.session_id, 'Converse')
    await wait_until(lambda: world.manager.get(chat.session_id).state == 'idle')
    await world.service.conclude(chat.session_id, 'Respondido')
    await asyncio.sleep(0.03)
    assert not world.record(chat.session_id).finished
    assert not world.service.conversations(agent)[0]['finished']


async def test_continue_a_routine_keeps_its_history_and_clears_auto_finish(world):
    agent = world.add_specialist()
    routine = await world.service.start_run(agent, trigger='manual', text='Rotina')
    await wait_until(lambda: world.manager.get(routine.session_id).state == 'idle')
    await world.service.conclude(routine.session_id, 'Feito')
    chat = await world.service.open_conversation(agent, session_id=routine.session_id)
    assert chat.session_id == routine.session_id
    await world.service.send_message(chat.session_id, 'Por que fez isso?')
    await wait_until(lambda: world.factory.clients[0].sent[-1] == 'Por que fez isso?')
    await asyncio.sleep(0.03)
    assert not world.record(chat.session_id).finished


async def test_cannot_continue_a_session_of_another_agent(world):
    agent = world.add_specialist()
    other = world.add_specialist(slug='outro')
    chat = await world.service.open_conversation(other)
    with pytest.raises(store.SpecialistNotFoundError):
        await world.service.open_conversation(agent, session_id=chat.session_id)


async def test_queued_images_stay_private_and_reach_the_same_chat(world):
    import base64
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    pause_queue(world, agent)
    images = [{'media_type': 'image/png', 'data': base64.b64encode(b'fake png').decode()}]
    pending = await world.service.send_message(chat.session_id, 'Veja', images)
    path = world.files.root / 'revisor' / f'pending-{pending.id}.txt'
    assert path.stat().st_mode & 0o777 == 0o600
    assert b'fake png' not in world.db_path.read_bytes()
    pause_queue(world, agent, False)
    await world.service.drain_queue()
    assert world.factory.clients[0].sent[0][1]['source']['data'] == images[0]['data']
    assert not path.exists()


async def test_recovery_of_a_starting_message_never_uses_an_old_idle_client_as_receipt(world):
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    first = await world.service.send_message(chat.session_id, 'Primeira')
    await wait_until(lambda: next(r for r in world.runs(agent) if r.id == first.id).outcome == 'concluded')
    pause_queue(world, agent)
    second = await world.service.send_message(chat.session_id, 'Ainda não enviada')
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.claim_run(conn, second.id, chat.session_id, int(world.now))
    await world.service.recover()
    assert world.specialist(agent).queue_paused
    assert next(r for r in world.runs(agent) if r.id == second.id).outcome == 'failed'
    assert world.factory.clients[0].sent == ['Primeira']
    assert any('confira' in notice.text.lower() for notice in world.notices())


async def test_recovery_completes_a_message_whose_turn_end_was_persisted(world):
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    run = await world.service.send_message(chat.session_id, 'Terminado')
    await wait_until(lambda: world.factory.clients and world.manager.get(chat.session_id).state == 'idle')
    await world.service.shutdown()
    await world.manager.shutdown()
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("UPDATE specialist_runs SET outcome = 'running' WHERE id = ?", (run.id,))
        conn.execute('UPDATE sessions SET turn_open = 0 WHERE session_id = ?', (chat.session_id,))
    from claudio_maestro.sessions import SessionManager
    world.manager = SessionManager(world.db_path, world.recorder, agent_factory=world.factory)
    world.service = SpecialistService(world.db_path, files=world.files, sessions=world.manager,
                                     publish=world.recorder, clock=lambda: world.now, finish_poll=0.005)
    await world.service.recover()
    await wait_until(lambda: world.runs(agent)[0].outcome == 'concluded')
    await wait_until(lambda: not world.service._tasks)
    assert len(world.factory.clients) == 1


async def test_a_successful_followup_releases_an_older_waiting_run(world):
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    first = await world.service.send_message(chat.session_id, 'Primeira')
    await wait_until(lambda: next(r for r in world.runs(agent) if r.id == first.id).outcome == 'concluded')
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.finish_run(conn, first.id, outcome='waiting', ended_at=int(world.now), reason='Precisa de você')
    second = await world.service.send_message(chat.session_id, 'Pode continuar')
    await wait_until(lambda: next(r for r in world.runs(agent) if r.id == second.id).outcome == 'concluded')
    routine = await world.service.start_run(agent, trigger='manual', text='Próxima rotina')
    await wait_until(lambda: any(c.sent == ['Próxima rotina'] for c in world.factory.clients))
    assert next(r for r in world.runs(agent) if r.id == routine.id).session_id != chat.session_id


async def test_missing_session_does_not_block_completion_or_other_agents(world):
    agent = world.add_specialist()
    other = world.add_specialist(slug='outro')
    chat = await world.service.open_conversation(agent)
    run = await world.service.send_message(chat.session_id, 'Primeira')
    await wait_until(lambda: world.factory.clients and world.manager.get(chat.session_id).state == 'idle')
    await world.service.shutdown()
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("UPDATE specialist_runs SET outcome = 'running', session_id = NULL WHERE id = ?", (run.id,))
    world.service = SpecialistService(world.db_path, files=world.files, sessions=world.manager,
                                     publish=world.recorder, clock=lambda: world.now, finish_poll=0.005)
    pause_queue(world, other)
    pending = await world.service.start_run(other, trigger='manual', text='Não bloquear')
    pause_queue(world, other, False)
    await world.service.recover()
    await wait_until(lambda: any(c.sent == ['Não bloquear'] for c in world.factory.clients))
    assert next(r for r in world.runs(agent) if r.id == run.id).outcome == 'failed'
    assert next(r for r in world.runs(other) if r.id == pending.id).session_id is not None
