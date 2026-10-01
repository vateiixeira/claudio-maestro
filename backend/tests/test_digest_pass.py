# backend/tests/test_digest_pass.py
"""One pass of the digest agent over the eligible sessions."""

import asyncio
from contextlib import closing
from pathlib import Path

import pytest
from digest_fakes import NOW, World, claude, exchange, user

from claudio_maestro import db
from claudio_maestro.digest.config import DigestConfig, save_config
from claudio_maestro.digest.model import DigestModelError, FakeDigestModel
from claudio_maestro.digest.service import pre_eligible
from claudio_maestro.digest.store import Digest

CFG = DigestConfig(enabled=True)


def answer(short: str = "Faz X", *phases) -> dict:
    return {"short": short, "phases": list(phases) or [
        {"title": "Fase", "kind": "feature", "status": "open", "done": [], "pending": [], "ref": None}
    ], "plan_completed": False, "plan_evidence": None}


def session(**fields) -> dict:
    base = {"display_state": "waiting", "last_activity_at": int(NOW - 60), "state": "closed",
            "cli_running": False, "created_at": int(NOW - 3600)}
    base.update(fields)
    return base


# pre_eligible ------------------------------------------------------------------

def test_pre_eligible_rules() -> None:
    assert pre_eligible(session(), None, NOW - 5, CFG, NOW)
    assert not pre_eligible(session(display_state="finished"), None, NOW - 5, CFG, NOW)
    assert not pre_eligible(session(last_activity_at=int(NOW - 4 * 86400)), None, NOW, CFG, NOW)
    assert not pre_eligible(session(), None, None, CFG, NOW)
    read = Digest("s", read_at=int(NOW - 5))
    assert not pre_eligible(session(), read, NOW - 5, CFG, NOW)  # file unchanged
    assert pre_eligible(session(), read, NOW - 1, CFG, NOW)


def test_open_turn_waits_for_the_ceiling() -> None:
    running = session(state="running")
    cli = session(cli_running=True)
    recent = Digest("s", read_at=int(NOW - 10 * 60))
    old = Digest("s", read_at=int(NOW - 31 * 60))
    assert not pre_eligible(running, recent, NOW, CFG, NOW)
    assert not pre_eligible(cli, recent, NOW, CFG, NOW)
    assert pre_eligible(running, old, NOW, CFG, NOW)
    # First reading: counted from the session's creation (an hour ago here).
    assert pre_eligible(running, None, NOW, CFG, NOW)


# pass ----------------------------------------------------------------------------

def enable(world: World, **changes) -> None:
    with closing(db.connect(world.db_path)) as conn:
        save_config(conn, DigestConfig(enabled=True, **changes))


@pytest.mark.anyio
async def test_pass_reads_eligible_sessions(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 12))
    world.add("s2", exchange(0, 3))  # below the minimum of 10
    world.add("s3", exchange(0, 12), display_state="finished")
    model = FakeDigestModel([answer("Faz X")])
    service = world.service(model)

    run = await service.run_pass("auto")

    assert run["read_count"] == 1 and run["skipped_count"] == 1 and run["errors"] == []
    assert run["trigger"] == "auto" and run["stopped"] is None
    digest = world.digest("s1")
    assert digest.short == "Faz X" and digest.cursor == "a11" and digest.read_at == int(NOW)
    assert world.manager.briefs["s1"] == ("Faz X", False)
    events = world.published("session.digest")
    assert events == [{"session_id": None, "seq": 0, "type": "session.digest",
                       "data": {"session_id": "s1", "digest": digest.to_dict()}}]
    request = model.requests[0]
    assert request.model == "sonnet" and request.effort == "medium"
    assert "[Você] pedido 0" in request.prompt and "Projeto: app" in request.prompt


@pytest.mark.anyio
async def test_second_reading_sends_only_what_is_new(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=2)
    world.add("s1", exchange(0, 4))
    model = FakeDigestModel([answer("Primeira"), answer("Segunda")])
    service = world.service(model)
    await service.run_pass("auto")

    world.clock[0] = NOW + 600
    world.touch("s1", [user("u9", "pedido novo"), claude("a9", "feito")], NOW + 500)
    await service.run_pass("auto")

    second = model.requests[1].prompt
    assert "pedido novo" in second and "pedido 0" not in second
    assert '"short": "Primeira"' in second
    assert world.digest("s1").cursor == "a9"


@pytest.mark.anyio
async def test_unchanged_file_is_not_read_again(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    await service.run_pass("auto")
    world.clock[0] = NOW + 600
    run = await service.run_pass("auto")
    assert len(model.requests) == 1 and run["read_count"] == 0


@pytest.mark.anyio
async def test_frozen_phases_survive_the_answer(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    done = {"title": "Plano X", "kind": "plan", "status": "done", "done": ["T1"], "pending": [],
            "ref": None}
    model = FakeDigestModel([
        answer("A", done),
        answer("B", {**done, "done": ["mudou"]},
               {"title": "Ajustes", "kind": "adjustments", "status": "open", "done": [],
                "pending": [], "ref": None}),
    ])
    service = world.service(model)
    await service.run_pass("auto")
    world.clock[0] = NOW + 600
    world.touch("s1", [user("u9", "ajuste")], NOW + 500)
    await service.run_pass("auto")
    phases = world.digest("s1").phases
    assert phases[0] == done and phases[1]["title"] == "Ajustes"


@pytest.mark.anyio
async def test_one_failure_does_not_stop_the_others(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel([DigestModelError("Resposta ruim."), answer("OK")])
    service = world.service(model)
    run = await service.run_pass("auto")
    assert run["read_count"] == 1
    assert run["errors"] == [{"session_id": "s1", "title": "Sessão s1", "message": "Resposta ruim."}]
    assert world.digest("s1").error == "Resposta ruim."
    assert world.digest("s2").short == "OK"


@pytest.mark.anyio
async def test_stop_error_ends_the_pass(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel([DigestModelError("Login expirou.", stop_pass=True)])
    service = world.service(model)
    run = await service.run_pass("auto")
    assert run["stopped"] == "Login expirou." and len(model.requests) == 1
    assert world.digest("s2") is None


@pytest.mark.anyio
async def test_rate_limit_pauses_until_release(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel([DigestModelError("Limite.", stop_pass=True, resets_at=int(NOW + 3600))])
    service = world.service(model)
    await service.run_pass("auto")
    assert service.status()["paused_until"] == int(NOW + 3600)


@pytest.mark.anyio
async def test_timeout_is_a_session_error(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    model.gate = asyncio.Event()  # never set
    service = world.service(model, session_timeout=0.05)
    run = await service.run_pass("auto")
    assert run["errors"][0]["message"] == "O agente demorou demais para responder."


@pytest.mark.anyio
async def test_unknown_model_stops_before_reading(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, model="claude-sumiu", min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    run = await service.run_pass("auto")
    assert run["stopped"] == "O modelo claude-sumiu não está mais disponível."
    assert model.requests == []


@pytest.mark.anyio
async def test_session_gone_before_saving_is_skipped(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    model.gate = asyncio.Event()
    service = world.service(model)
    task = asyncio.create_task(service.run_pass("auto"))
    await model.started.wait()
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    model.gate.set()
    run = await task
    assert run["read_count"] == 0 and run["skipped_count"] == 1 and run["errors"] == []


@pytest.mark.anyio
async def test_manual_session_ignores_the_filters(tmp_path: Path) -> None:
    world = World(tmp_path)  # agent disabled
    world.add("s1", exchange(0, 2), display_state="finished")
    model = FakeDigestModel([answer("Manual")])
    service = world.service(model)
    run = await service.run_pass("manual_session", ["s1", "nope"])
    assert world.digest("s1").short == "Manual" and run["read_count"] == 1
    assert run["errors"] == [{"session_id": "nope", "title": "nope",
                              "message": "Conversa não encontrada."}]


@pytest.mark.anyio
async def test_manual_session_without_news_republishes(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel([answer("Uma vez")])
    service = world.service(model)
    await service.run_pass("manual_session", ["s1"])
    await service.run_pass("manual_session", ["s1"])
    assert len(model.requests) == 1
    assert len(world.published("session.digest")) == 2


@pytest.mark.anyio
async def test_manual_all_ignores_only_the_minimum(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world)  # minimum 10
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2), display_state="finished")
    model = FakeDigestModel()
    service = world.service(model)
    run = await service.run_pass("manual_all")
    assert run["read_count"] == 1 and world.digest("s2") is None


@pytest.mark.anyio
async def test_plan_file_complete_sets_the_seal(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    plans = world.root / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    plan = plans / "p.md"
    plan.write_text("# P\n\n### Tarefa 1: A\n- [x] a\n")
    world.add("s1", exchange(0, 2),
              plan={"path": str(plan), "title": "P", "total": 1, "done": 1, "current": None})
    model = FakeDigestModel()
    service = world.service(model)
    await service.run_pass("auto")
    assert world.digest("s1").plan_done is True
    assert "- [x] Tarefa 1: A" in model.requests[0].prompt


@pytest.mark.anyio
async def test_transcript_is_looked_up_in_the_history_dir(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    elsewhere = str(tmp_path / "worktree-history")
    world.add("s1", exchange(0, 2), history_dir=elsewhere)
    world.add("s2", exchange(0, 2))  # no history_dir: falls back to the cwd
    service = world.service(FakeDigestModel())
    await service.run_pass("auto")
    assert {d for sid, d in world.lookups if sid == "s1"} == {elsewhere}
    assert {d for sid, d in world.lookups if sid == "s2"} == {str(world.root)}
    assert world.digest("s1") is not None and world.digest("s2") is not None


@pytest.mark.anyio
async def test_unexpected_error_while_preparing_is_a_session_error(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    original = world.read_transcript

    def flaky(path: Path | None):
        if path is not None and path.stem == "s1":
            raise OSError("disco falhou")
        return original(path)

    service = world.service(FakeDigestModel([answer("OK")]))
    service._read_transcript = flaky
    run = await service.run_pass("auto")
    message = "Falha inesperada ao resumir a conversa."
    assert run["errors"] == [{"session_id": "s1", "title": "Sessão s1", "message": message}]
    assert run["read_count"] == 1 and run["stopped"] is None
    assert world.digest("s1").error == message
    assert world.digest("s2").short == "OK"


@pytest.mark.anyio
async def test_brief_failure_after_saving_still_counts_as_read(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))

    async def broken(*args, **kwargs):
        raise RuntimeError("sem resumo curto")

    world.manager.set_digest_brief = broken
    service = world.service(FakeDigestModel([answer("Salvo")]))
    run = await service.run_pass("auto")
    assert run["read_count"] == 1 and run["errors"] == []
    assert world.digest("s1").short == "Salvo" and world.digest("s1").error is None


@pytest.mark.anyio
async def test_failing_publish_does_not_leave_the_agent_running(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world)
    service = world.service(FakeDigestModel())

    def broken(envelope) -> None:
        raise RuntimeError("canal fechado")

    service._publish = broken
    with pytest.raises(RuntimeError):
        await service.run_pass("auto")
    assert service.status()["running"] is False
