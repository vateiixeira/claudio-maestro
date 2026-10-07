"""The digest agent records and summarizes deliveries."""

import asyncio
import threading
import time
from contextlib import closing

import pytest
from digest_fakes import NOW, World, exchange

from claudio_maestro import db, deliveries
from claudio_maestro.digest.config import DigestConfig, save_config
from claudio_maestro.digest.delivery import DELIVERY_SCHEMA
from claudio_maestro.digest.model import DigestModelError, FakeDigestModel
from claudio_maestro.digest.service import (
    AGENT_OFF,
    ALREADY_PENDING,
    DELIVERY_NOT_FOUND,
    STOPPED_DISABLED,
    DeliveryConflict,
    DeliveryNotFound,
)

ANSWER = {"title": "Tela de entregas", "bullets": ["Tabela nova", "Rota do dia"]}
SECOND_ANSWER = {"title": "Entregas com a rota", "bullets": ["Rota do dia", "Testes novos"]}


def enable(world: World) -> None:
    with closing(db.connect(world.db_path)) as conn:
        save_config(conn, DigestConfig(enabled=True))


def rows(world: World, sid: str) -> list[deliveries.Delivery]:
    with closing(db.connect(world.db_path)) as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM deliveries WHERE session_id = ? ORDER BY id", (sid,))]
        return [deliveries.get(conn, i) for i in ids]


async def drain(service) -> None:
    await service.tick()


@pytest.mark.anyio
async def test_finish_with_agent_on_records_pending_then_done(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    model = FakeDigestModel([ANSWER])
    service = world.service(model)

    await service.record_finish("s1", int(NOW))
    [d] = rows(world, "s1")
    assert d.status == "pending" and d.to_cursor == "a3" and d.from_cursor is None
    assert d.project_name == "app" and d.title == "Sessão s1"
    await drain(service)

    [d] = rows(world, "s1")
    assert (d.status, d.summary_title, d.bullets) == ("done", "Tela de entregas", ANSWER["bullets"])
    request = model.requests[0]
    assert request.schema == DELIVERY_SCHEMA and "[Você] pedido 0" in request.prompt
    types = [e["data"]["status"] for e in world.published("delivery.updated")]
    assert types == ["pending", "done"]


@pytest.mark.anyio
async def test_finish_with_agent_off_is_title_only(tmp_path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 4))
    model = FakeDigestModel([])
    service = world.service(model)
    await service.record_finish("s1", int(NOW))
    await drain(service)
    [d] = rows(world, "s1")
    assert d.status == "title_only" and model.requests == []


@pytest.mark.anyio
async def test_refinish_without_new_messages_is_title_only(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    model = FakeDigestModel([ANSWER])
    service = world.service(model)
    await service.record_finish("s1", int(NOW))
    await drain(service)
    await service.record_finish("s1", int(NOW) + 2 * 86400)  # another day, nothing new
    await drain(service)
    first, second = rows(world, "s1")
    assert second.from_cursor == "a3" and second.to_cursor == "a3"
    assert second.status == "title_only" and len(model.requests) == 1


@pytest.mark.anyio
async def test_refinish_another_day_covers_only_new_messages(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    model = FakeDigestModel([ANSWER, ANSWER])
    service = world.service(model)
    await service.record_finish("s1", int(NOW))
    await drain(service)
    world.touch("s1", exchange(4, 2), NOW + 10)
    await service.record_finish("s1", int(NOW) + 2 * 86400)
    await drain(service)
    prompt = model.requests[1].prompt
    assert "pedido 4" in prompt and "pedido 0" not in prompt


@pytest.mark.anyio
async def test_refinish_while_summarizing_keeps_the_renewed_record(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    model = FakeDigestModel([ANSWER, SECOND_ANSWER])
    model.gate = asyncio.Event()
    service = world.service(model)
    await service.record_finish("s1", int(NOW))
    tick = asyncio.create_task(service.tick())
    await model.started.wait()  # the first summary (up to a3) is waiting on the gate

    world.touch("s1", exchange(4, 2), NOW + 10)
    await service.record_finish("s1", int(NOW) + 60)  # same day: renews the same record
    model.gate.set()
    await asyncio.wait_for(tick, 1)
    [d] = rows(world, "s1")
    assert d.status == "pending" and d.to_cursor == "a5"  # the stale result was dropped

    await drain(service)
    [d] = rows(world, "s1")
    assert (d.status, d.summary_title, d.bullets) == (
        "done", SECOND_ANSWER["title"], SECOND_ANSWER["bullets"])
    assert len(model.requests) == 2 and "pedido 4" in model.requests[1].prompt
    statuses = [e["data"]["status"] for e in world.published("delivery.updated")]
    assert statuses == ["pending", "pending", "done"]


@pytest.mark.anyio
async def test_model_error_marks_error(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    service = world.service(FakeDigestModel([DigestModelError("Limite atingido.", stop_pass=True)]))
    await service.record_finish("s1", int(NOW))
    await drain(service)
    [d] = rows(world, "s1")
    assert (d.status, d.error) == ("error", "Limite atingido.")


@pytest.mark.anyio
async def test_bad_answer_marks_error(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    service = world.service(FakeDigestModel([{"title": "", "bullets": []}]))
    await service.record_finish("s1", int(NOW))
    await drain(service)
    assert rows(world, "s1")[0].status == "error"


@pytest.mark.anyio
async def test_resummarize_rules(tmp_path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 4))
    service = world.service(FakeDigestModel([ANSWER]))
    await service.record_finish("s1", int(NOW))  # agent off: title_only
    [d] = rows(world, "s1")
    with pytest.raises(DeliveryNotFound) as missing:
        await service.resummarize(999)
    assert missing.value.message == DELIVERY_NOT_FOUND
    with pytest.raises(DeliveryConflict) as off:
        await service.resummarize(d.id)
    assert off.value.message == AGENT_OFF
    enable(world)
    service.load()
    body = await service.resummarize(d.id)
    assert body["status"] == "pending"
    with pytest.raises(DeliveryConflict) as twice:
        await service.resummarize(d.id)
    assert twice.value.message == ALREADY_PENDING
    await drain(service)
    assert rows(world, "s1")[0].status == "done"


@pytest.mark.anyio
async def test_disabling_marks_queued_and_running_deliveries(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    world.add("s2", exchange(0, 4))
    model = FakeDigestModel([ANSWER, ANSWER])
    model.gate = asyncio.Event()  # never set: the first summary hangs
    service = world.service(model)
    await service.record_finish("s1", int(NOW))
    await service.record_finish("s2", int(NOW))
    tick = asyncio.create_task(service.tick())
    await model.started.wait()  # s1 is waiting on the gate, s2 is queued behind it
    await service.update_config(DigestConfig(enabled=False))
    await asyncio.wait_for(tick, 1)
    for sid in ("s1", "s2"):
        [d] = rows(world, sid)
        assert (d.status, d.error) == ("error", STOPPED_DISABLED)


@pytest.mark.anyio
async def test_disabling_marks_deliveries_still_queued(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    service = world.service(FakeDigestModel([ANSWER]))
    await service.record_finish("s1", int(NOW))  # queued, no tick yet
    await service.update_config(DigestConfig(enabled=False))
    await drain(service)
    [d] = rows(world, "s1")
    assert (d.status, d.error) == ("error", STOPPED_DISABLED)


@pytest.mark.anyio
async def test_shutdown_mid_summary_keeps_the_records_pending(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    world.add("s2", exchange(0, 4))
    model = FakeDigestModel([ANSWER])
    model.gate = asyncio.Event()  # never set: s1 hangs, s2 waits behind it
    service = world.service(model)
    await service.record_finish("s1", int(NOW))
    await service.record_finish("s2", int(NOW))
    loop = asyncio.create_task(service.run())  # the app lifespan cancels it on shutdown
    await asyncio.wait_for(model.started.wait(), 2)
    loop.cancel()
    await asyncio.gather(loop, return_exceptions=True)
    for sid in ("s1", "s2"):
        [d] = rows(world, sid)
        assert (d.status, d.error) == ("pending", None)

    again = world.service(FakeDigestModel([ANSWER, ANSWER]))  # the next start
    await again.recover_deliveries()
    await drain(again)
    assert [rows(world, sid)[0].status for sid in ("s1", "s2")] == ["done", "done"]


@pytest.mark.anyio
async def test_disabling_while_finish_is_being_recorded_does_not_call_the_model(tmp_path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 4))
    model = FakeDigestModel([ANSWER])
    service = world.service(model)
    original = service._create_delivery
    created = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def slow(*args):
        delivery = original(*args)  # read the config as enabled: the record is pending
        loop.call_soon_threadsafe(created.set)
        release.wait(2)
        return delivery

    service._create_delivery = slow
    recording = asyncio.create_task(service.record_finish("s1", int(NOW)))
    await created.wait()
    await service.update_config(DigestConfig(enabled=False))  # the queue is still empty
    release.set()
    await recording
    await drain(service)
    assert model.requests == []
    [d] = rows(world, "s1")
    assert (d.status, d.error) == ("error", STOPPED_DISABLED)
    assert world.published("delivery.updated")[-1]["data"]["status"] == "error"


@pytest.mark.anyio
async def test_startup_recovers_pending(tmp_path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 4))
    with closing(db.connect(world.db_path)) as conn:
        d = deliveries.record_finish(conn, session_id="s1", project_id=1, project_name="app",
                                     title="T", finished_at=int(NOW), to_cursor="a3",
                                     status="pending")
    off = world.service(FakeDigestModel([]))
    await off.recover_deliveries()
    assert rows(world, "s1")[0].status == "title_only"

    with closing(db.connect(world.db_path)) as conn:
        deliveries.mark_pending(conn, d.id, at=1)
    enable(world)
    on = world.service(FakeDigestModel([ANSWER]))
    await on.recover_deliveries()
    await drain(on)
    assert rows(world, "s1")[0].status == "done"


@pytest.mark.anyio
async def test_finish_of_unknown_session_records_nothing(tmp_path) -> None:
    world = World(tmp_path)
    service = world.service(FakeDigestModel([]))
    await service.record_finish("nope", int(NOW))
    assert world.published("delivery.updated") == []


def test_finishing_through_the_api_creates_a_delivery(tmp_path, home) -> None:
    from fastapi.testclient import TestClient
    from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project

    from claudio_maestro.agent.fake import FakeAgentFactory
    from claudio_maestro.app import create_app

    app = create_app(agent_factory=FakeAgentFactory(), digest_model=FakeDigestModel([]))
    with TestClient(app, base_url=BACKEND_URL,
                    headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as api:
        project = make_project(api, home)
        sid = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]
        assert api.patch(f"/api/sessions/{sid}", json={"finished": True}).status_code == 200
        db_path = app.state.settings.db_path
        count = 0
        for _ in range(100):
            with closing(db.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
            if count:
                break
            time.sleep(0.02)
        assert count == 1
