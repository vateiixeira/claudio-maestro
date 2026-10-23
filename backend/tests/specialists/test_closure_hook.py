"""DigestService tells the agents feature about every closure it saves."""

import logging
from contextlib import closing

import pytest
from digest_fakes import NOW, World, claude, user

from claudio_maestro import db
from claudio_maestro.digest.closure_store import Closure, save_closure
from claudio_maestro.digest.config import DigestConfig, save_config
from claudio_maestro.digest.model import FakeDigestModel

pytestmark = pytest.mark.anyio

QUIET = NOW - 600


def enable(world: World) -> None:
    with closing(db.connect(world.db_path)) as conn:
        save_config(conn, DigestConfig(enabled=True))


def seed(world: World) -> None:
    enable(world)
    world.add("s1", [user("u1", "faça X"), claude("a1", "Feito.")], mtime=QUIET, state="idle")


async def test_checked_closure_is_passed_to_the_hook(tmp_path) -> None:
    world = World(tmp_path)
    seed(world)
    seen: list[Closure] = []

    async def on_closure(closure: Closure) -> None:
        seen.append(closure)

    model = FakeDigestModel(
        [{"verdict": "can_close", "user_actions": [], "missing": [], "evidence": "e"}]
    )
    await world.service(model, on_closure=on_closure).run_closure_pass()

    [closure] = seen
    assert (closure.session_id, closure.verdict, closure.evidence) == ("s1", "can_close", "e")


async def test_resolving_an_item_also_reaches_the_hook(tmp_path) -> None:
    world = World(tmp_path)
    seed(world)
    with closing(db.connect(world.db_path)) as conn:
        save_closure(conn, Closure("s1", verdict="user_action", user_actions=["Reiniciar"],
                                   checked_at=int(NOW - 30)))
    seen: list[str | None] = []

    async def on_closure(closure: Closure) -> None:
        seen.append(closure.verdict)

    await world.service(FakeDigestModel(), on_closure=on_closure).resolve_closure_item(
        "s1", "Reiniciar"
    )

    assert seen == ["can_close"]


async def test_a_failing_hook_does_not_lose_the_closure(tmp_path, caplog) -> None:
    world = World(tmp_path)
    seed(world)

    async def on_closure(closure: Closure) -> None:
        raise RuntimeError("quebrou")

    model = FakeDigestModel(
        [{"verdict": "can_close", "user_actions": [], "missing": [], "evidence": "e"}]
    )
    with caplog.at_level(logging.ERROR):
        await world.service(model, on_closure=on_closure).run_closure_pass()

    assert world.closure("s1").verdict == "can_close"
    assert any(e["type"] == "session.closure" for e in world.envelopes)
    assert "quebrou" in caplog.text


async def test_without_a_hook_nothing_changes(tmp_path) -> None:
    world = World(tmp_path)
    seed(world)
    model = FakeDigestModel(
        [{"verdict": "can_close", "user_actions": [], "missing": [], "evidence": "e"}]
    )

    await world.service(model).run_closure_pass()

    assert world.closure("s1").verdict == "can_close"
