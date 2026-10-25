"""Contracts between the permanent main, additional conversations, queue and PR comments."""

from contextlib import closing

import pytest
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import PauseStep, init_message, text_turn
from claudio_maestro.specialists import store
from specialists.test_service import a_comment, pr_of, world  # noqa: F401

pytestmark = pytest.mark.anyio


async def test_default_conversation_and_sidebar_share_the_permanent_main(world):
    agent = world.add_specialist()
    main = await world.service.ensure_main(agent)
    default = await world.service.open_conversation(agent)
    extra = await world.service.open_conversation(agent, new=True)
    assert default.session_id == main
    assert extra.session_id != main
    assert world.service.is_conversation(main)
    assert world.service.is_conversation(extra.session_id)


async def test_main_turn_holds_the_agents_queue_without_dropping_the_routine(world):
    agent = world.add_specialist()
    main = await world.service.ensure_main(agent)
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    await world.manager.send(main, "Pedido da pessoa")
    await pause.reached.wait()
    routine = await world.service.start_run(agent, trigger="schedule", text="Rotina")
    assert routine.outcome == "queued"
    assert len(world.factory.clients) == 1
    world.turns = lambda sid: text_turn(sid, "ok")
    pause.release.set()
    await wait_until(lambda: len(world.factory.clients) == 2 and world.factory.clients[1].sent)


async def test_comment_waits_for_the_agent_to_be_idle_and_for_queue_resume(world):
    from claudio_maestro.specialists.service import CommentNotSentError

    agent = world.add_specialist()
    main = await world.service.ensure_main(agent)
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    await world.manager.send(main, "Trabalho")
    await pause.reached.wait()
    with pytest.raises(CommentNotSentError):
        await world.service.start_comment_run(pr_of(agent, None), [a_comment("issue:1")])
    assert len(world.factory.clients[0].sent) == 1
    pause.release.set()
    await wait_until(lambda: world.manager.get(main).state == "idle")
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.update_specialist(conn, agent, now=world.now, queue_paused=True)
    with pytest.raises(CommentNotSentError):
        await world.service.start_comment_run(pr_of(agent, None), [a_comment("issue:1")])
    assert len(world.factory.clients[0].sent) == 1


async def test_queued_main_message_delivers_announcements_without_finishing_the_main(world):
    agent = world.add_specialist()
    main = await world.service.ensure_main(agent)
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.add_announcement(conn, specialist_id=agent, run_id=None, session_id=None,
                               text="Resultado da rotina", created_at=world.now)
    run = await world.service.send_message(main, "Explique")
    await wait_until(lambda: world.runs(agent)[0].outcome == "concluded")
    assert world.factory.clients[0].sent[0].endswith("\n\nExplique")
    assert "Resultado da rotina" in world.factory.clients[0].sent[0]
    assert not world.record(main).finished
    assert world.run_of(main).id == run.id
    assert world.announcements(agent)[0].delivered_at is not None


def test_queue_migration_preserves_comment_runs_announcement_links_and_sequence(tmp_path):
    path = tmp_path / "old.db"
    with closing(db.connect(path)) as conn:
        before = next(index for index, statements in enumerate(db.MIGRATIONS)
                      if any("queue_paused" in str(statement) for statement in statements))
        for statements in db.MIGRATIONS[:before]:
            for statement in statements:
                if callable(statement):
                    statement(conn)
                else:
                    conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {before}")
        conn.execute("INSERT INTO projects (id,name,path,color,position,created_at) VALUES (1,'p','/p','x',0,0)")
        conn.execute("INSERT INTO sessions (session_id,project_id,cwd,title,created_at,last_activity_at) VALUES ('main',1,'/p','main',0,0)")
        agent_id = conn.execute("INSERT INTO specialists (slug,name,project_id,created_at,updated_at) VALUES ('agent','Agent',1,0,0)").lastrowid
        conn.execute("UPDATE specialists SET main_session_id = 'main' WHERE id = ?", (agent_id,))
        run_id = conn.execute("INSERT INTO specialist_runs (specialist_id,session_id,trigger,started_at,outcome) VALUES (?, 'main', 'comment', 1, 'concluded')", (agent_id,)).lastrowid
        store.add_announcement(conn, specialist_id=agent_id, run_id=run_id,
                                              session_id="main", text="Resultado", created_at=2)
        conn.execute("INSERT INTO specialist_runs (id,specialist_id,trigger,started_at,outcome) VALUES (501,?,'manual',2,'concluded')", (agent_id,))
        conn.execute("DELETE FROM specialist_runs WHERE id = 501")
        db.migrate(conn)
        assert store.list_announcements(conn, agent_id)[0].run_id == run_id
        assert store.get_run(conn, run_id).trigger == "comment"
        assert store.get_specialist(conn, agent_id).main_session_id == "main"
        following = store.insert_run(conn, specialist_id=agent_id, trigger="manual", started_at=3, outcome="queued")
        assert following.id == 502
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


async def test_comment_dispatch_defers_without_waiting_on_a_slow_queue_lock(world):
    import asyncio

    from claudio_maestro.specialists.service import CommentNotSentError

    agent = world.add_specialist()
    async with world.service._queue_locks[agent]:
        with pytest.raises(CommentNotSentError):
            await asyncio.wait_for(world.service.start_comment_run(pr_of(agent, None),
                                                                   [a_comment("issue:slow")]), 0.1)


async def test_finalizing_metadata_does_not_free_an_agent_whose_turn_is_still_running(world):
    agent = world.add_specialist()
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    first = await world.service.start_run(agent, trigger="manual", text="Primeira")
    await pause.reached.wait()
    await world.manager.update(first.session_id, finished=True)
    second = await world.service.start_run(agent, trigger="manual", text="Segunda")
    assert second.outcome == "queued"
    assert len(world.factory.clients) == 1
    world.turns = lambda sid: text_turn(sid, "ok")
    pause.release.set()
    await wait_until(lambda: len(world.factory.clients) == 2 and world.factory.clients[1].sent)


@pytest.mark.parametrize("message", [True, False])
async def test_failed_connection_preserves_the_payload_until_explicit_queue_resume(world, message):
    from claudio_maestro.agent.base import AgentError
    from specialists.test_queue import pause_queue

    agent = world.add_specialist()
    world.factory.connect_error = AgentError("Sem conexão")
    if message:
        main = await world.service.ensure_main(agent)
        run = await world.service.send_message(main, "Pedido preservado")
    else:
        run = await world.service.start_run(agent, trigger="manual", text="Pedido preservado")
    await wait_until(lambda: world.specialist(agent).queue_paused)
    saved = next(item for item in world.runs(agent) if item.id == run.id)
    assert saved.outcome == "queued"
    assert not any(client.sent for client in world.factory.clients)
    if message:
        assert world.files.read_message("revisor", run.id)[0] == "Pedido preservado"
    else:
        assert world.files.read_run_text("revisor", run.id) == "Pedido preservado"
    world.factory.connect_error = None
    pause_queue(world, agent, False)
    await world.service.drain_queue()
    await wait_until(lambda: any(client.sent for client in world.factory.clients))
    assert [sent for client in world.factory.clients for sent in client.sent] == ["Pedido preservado"]
    assert world.run_of(saved.session_id).id == run.id


@pytest.mark.parametrize("same_conversation", [False, True])
async def test_comments_respect_a_waiting_conversation_but_can_reply_to_it(world, same_conversation):
    from claudio_maestro.specialists.service import CommentNotSentError

    agent = world.add_specialist()
    run = await world.service.start_run(agent, trigger="manual", text="Rotina")
    await wait_until(lambda: world.manager.get(run.session_id).state == "idle")
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.finish_run(conn, run.id, outcome="waiting", ended_at=world.now, reason="Precisa de você")
    pr = pr_of(agent, run.session_id if same_conversation else None)
    if same_conversation:
        await world.service.start_comment_run(pr, [a_comment("issue:waiting")])
        assert len(world.factory.clients[0].sent) == 2
    else:
        with pytest.raises(CommentNotSentError):
            await world.service.start_comment_run(pr, [a_comment("issue:waiting")])
        assert len(world.factory.clients) == 1
