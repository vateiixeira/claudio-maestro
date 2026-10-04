"""The closure check inside the digest agent: automatic scan, manual run, resolve."""

import asyncio
from contextlib import closing

import pytest
from digest_fakes import NOW, World, claude, user

from claudio_maestro import db
from claudio_maestro.digest.closure import CLOSURE_SCHEMA
from claudio_maestro.digest.closure_store import Closure, save_closure
from claudio_maestro.digest.config import DigestConfig, save_config
from claudio_maestro.digest.model import DigestModelError, FakeDigestModel
from claudio_maestro.digest.service import STOPPED_DISABLED, ClosureItemNotFound

pytestmark = pytest.mark.anyio

QUIET = NOW - 600


def verdict(v="user_action", actions=("Reiniciar os serviços",), missing=(), evidence="e") -> dict:
    return {"verdict": v, "user_actions": list(actions), "missing": list(missing),
            "evidence": evidence}


def enable(world: World, **changes) -> None:
    with closing(db.connect(world.db_path)) as conn:
        save_config(conn, DigestConfig(enabled=True, **changes))


def conversation() -> list:
    return [user("u1", "faça X"), claude("a1", "Feito. Agora reinicie os serviços.")]


def closures(world: World) -> list[dict]:
    return [e["data"] for e in world.envelopes if e["type"] == "session.closure"]


def runs(world: World) -> list[dict]:
    from claudio_maestro.digest.store import list_runs

    with closing(db.connect(world.db_path)) as conn:
        return list_runs(conn)


async def test_auto_scan_checks_quiet_closed_sessions(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    model = FakeDigestModel([verdict()])
    service = world.service(model)
    run = await service.run_closure_pass()
    assert run is not None and run["trigger"] == "auto_closure" and run["read_count"] == 1
    request = model.requests[0]
    assert request.schema is CLOSURE_SCHEMA
    assert "Agora reinicie os serviços." in request.prompt
    assert "Branch: main" in request.prompt
    saved = world.closure("s1")
    assert (saved.verdict, saved.user_actions) == ("user_action", ["Reiniciar os serviços"])
    assert world.manager.closure_briefs["s1"] == ("user_action", saved.checked_at)
    assert closures(world)[-1]["closure"]["verdict"] == "user_action"


async def test_same_fingerprint_does_not_call_again(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    model = FakeDigestModel([verdict(), verdict()])
    service = world.service(model)
    await service.run_closure_pass()
    world.clock[0] += 400  # past GIT_RECHECK_SECONDS: git is read again, nothing changed
    assert await service.run_closure_pass() is None
    assert len(model.requests) == 1


async def test_git_change_triggers_a_new_check(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    model = FakeDigestModel([verdict("incomplete", (), ["Commit"]), verdict("can_close", ())])
    service = world.service(model)
    await service.run_closure_pass()
    world.git = world.git.__class__(path=world.git.path, rel_path=".", branch="main",
                                    upstream="origin/main", ahead=1)
    world.clock[0] += 400
    await service.run_closure_pass()
    assert world.closure("s1").verdict == "can_close"


async def test_git_is_not_reread_every_minute(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    service = world.service(FakeDigestModel([verdict()]))
    await service.run_closure_pass()
    calls = len(world.git_calls)
    world.clock[0] += 60
    await service.run_closure_pass()
    assert len(world.git_calls) == calls


async def test_idle_scan_logs_no_run_and_publishes_no_status(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=NOW - 10, state="idle")  # not quiet yet
    service = world.service(FakeDigestModel())
    world.envelopes.clear()
    assert await service.run_closure_pass() is None
    assert runs(world) == []
    assert [e for e in world.envelopes if e["type"] == "digest.status"] == []


@pytest.mark.parametrize("changes", [{"enabled": False}, {"closure_auto": False}])
async def test_switches_turn_the_scan_off(tmp_path, changes) -> None:
    world = World(tmp_path)
    with closing(db.connect(world.db_path)) as conn:
        save_config(conn, DigestConfig(**{"enabled": True, **changes}))
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    model = FakeDigestModel([verdict()])
    assert await world.service(model).run_closure_pass() is None
    assert model.requests == []


async def test_error_is_recorded_and_keeps_verdict(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    with closing(db.connect(world.db_path)) as conn:
        save_closure(conn, Closure("s1", verdict="can_close", checked_at=int(NOW - 900)))
    service = world.service(FakeDigestModel([{"nada": 1}]))
    run = await service.run_closure_pass()
    saved = world.closure("s1")
    assert (saved.verdict, saved.error) == ("can_close", "Resposta do agente fora do formato.")
    assert run is not None and run["errors"][0]["session_id"] == "s1"


async def test_stop_pass_on_login(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    world.add("s2", conversation(), mtime=QUIET, state="idle")
    model = FakeDigestModel([DigestModelError("Entre de novo.", stop_pass=True)])
    run = await world.service(model).run_closure_pass()
    assert run["stopped"] == "Entre de novo."
    assert len(model.requests) == 1


async def test_manual_digest_runs_the_check_after(tmp_path) -> None:
    world = World(tmp_path)
    enable(world, closure_auto=False)
    world.add("s1", conversation(), mtime=NOW - 5, state="idle")
    digest_answer = {"short": "Faz X", "phases": [], "plan_completed": False,
                     "plan_evidence": None}
    model = FakeDigestModel([digest_answer, verdict()])
    await world.service(model).run_pass("manual_session", ["s1"])
    assert [r.schema is CLOSURE_SCHEMA for r in model.requests] == [False, True]
    assert '"short": "Faz X"' in model.requests[1].prompt  # uses the fresh summary
    assert world.closure("s1").verdict == "user_action"


async def test_manual_skips_the_check_with_an_open_turn(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=NOW - 5, state="running")
    model = FakeDigestModel([{"short": "x", "phases": [], "plan_completed": False,
                              "plan_evidence": None}])
    await world.service(model).run_pass("manual_session", ["s1"])
    assert len(model.requests) == 1


async def test_resolve_item(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    with closing(db.connect(world.db_path)) as conn:
        save_closure(conn, Closure("s1", verdict="user_action",
                                   user_actions=["Reiniciar os serviços"],
                                   checked_at=int(NOW - 30)))
    service = world.service(FakeDigestModel())
    result = await service.resolve_closure_item("s1", "  reiniciar os SERVIÇOS ")
    assert (result["verdict"], result["user_actions"]) == ("can_close", [])
    saved = world.closure("s1")
    assert saved.resolved == ["Reiniciar os serviços"]
    assert world.manager.closure_briefs["s1"][0] == "can_close"
    assert closures(world)[-1]["closure"]["verdict"] == "can_close"
    with pytest.raises(ClosureItemNotFound):
        await service.resolve_closure_item("s1", "Outra coisa")


async def test_scheduler_runs_the_scan_every_minute(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    model = FakeDigestModel([verdict()])
    service = world.service(model)
    service.start_schedule()
    world.clock[0] += 61
    await service.tick()
    assert world.closure("s1") is not None and world.closure("s1").verdict == "user_action"


class SecondCallGate(FakeDigestModel):
    """Answers the first call at once and holds the following ones until `gate` is set."""

    def __init__(self, responses) -> None:
        super().__init__(responses)
        self.release = asyncio.Event()
        self.second_started = asyncio.Event()

    async def summarize(self, request):
        if self.requests:
            self.requests.append(request)
            self.second_started.set()
            await self.release.wait()
            return self.responses.pop(0) if self.responses else dict(self.DEFAULT)
        return await super().summarize(request)


async def test_cancel_during_the_manual_check_keeps_the_summary(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=NOW - 5, state="idle")
    digest_answer = {"short": "Faz X", "phases": [], "plan_completed": False,
                     "plan_evidence": None}
    model = SecondCallGate([digest_answer, verdict()])
    service = world.service(model)
    task = asyncio.create_task(service.run_pass("manual_session", ["s1"]))
    await asyncio.wait_for(model.second_started.wait(), 5)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    digest = world.digest("s1")
    assert digest.short == "Faz X" and digest.error != STOPPED_DISABLED
    (run,) = runs(world)
    assert run["read_count"] == 1


async def test_stop_without_reset_time_delays_the_next_scan(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    world.add("s2", conversation(), mtime=QUIET, state="idle")  # not reached by the first stop
    model = FakeDigestModel([DigestModelError("Entre de novo.", stop_pass=True),
                             DigestModelError("Entre de novo.", stop_pass=True)])
    service = world.service(model)
    service.start_schedule()
    world.clock[0] += 61
    await service.tick()
    assert len(model.requests) == 1 and len(runs(world)) == 1
    world.clock[0] += 61
    await service.tick()
    assert len(model.requests) == 1 and len(runs(world)) == 1
    world.clock[0] += 600  # a whole summary interval after the stop
    await service.tick()
    assert len(model.requests) == 2


async def test_resolve_during_the_model_call_is_kept(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    with closing(db.connect(world.db_path)) as conn:
        save_closure(conn, Closure("s1", verdict="user_action",
                                   user_actions=["Reiniciar os serviços"],
                                   checked_at=int(NOW - 30)))
    model = FakeDigestModel([verdict()])
    model.gate = asyncio.Event()
    service = world.service(model)
    task = asyncio.create_task(service.run_closure_pass())
    await asyncio.wait_for(model.started.wait(), 5)
    await service.resolve_closure_item("s1", "Reiniciar os serviços")
    model.gate.set()
    await task
    saved = world.closure("s1")
    assert saved.user_actions == [] and saved.verdict == "can_close"
    assert saved.resolved == ["Reiniciar os serviços"]
    assert closures(world)[-1]["closure"]["verdict"] == "can_close"


async def test_disabling_the_agent_cancels_a_scan_in_progress(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", conversation(), mtime=QUIET, state="idle")
    model = FakeDigestModel([verdict()])
    model.gate = asyncio.Event()
    service = world.service(model)
    service.start_schedule()
    world.clock[0] += 61
    ticking = asyncio.create_task(service.tick())
    await asyncio.wait_for(model.started.wait(), 5)
    await service.update_config(DigestConfig(enabled=False))
    await asyncio.wait_for(ticking, 5)
    assert service.status()["running"] is False
    assert world.closure("s1") is None
