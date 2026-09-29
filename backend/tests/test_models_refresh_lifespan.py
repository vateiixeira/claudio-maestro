"""The lifespan refreshes the stored models list without leaking it through /api/state."""

import time

from fastapi.testclient import TestClient

from vibing.agent.fake import DEFAULT_SERVER_MODELS, FakeAgentFactory
from vibing.app import create_app
from vibing.config import Settings

BACKEND_URL = "http://127.0.0.1:6660"
HEADERS = {"origin": "http://localhost:6600", "x-vibing": "1"}


def test_startup_refresh_stores_list_and_hides_it_from_state(home, data_dir):
    factory = FakeAgentFactory()
    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir),
        agent_factory=factory,
        refresh_models=True,
    )
    expected = [m["value"] for m in DEFAULT_SERVER_MODELS]
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        deadline = time.monotonic() + 5
        while (
            [m["value"] for m in api.get("/api/models").json()] != expected
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert [m["value"] for m in api.get("/api/models").json()] == expected
        assert api.get("/api/state").json() == {}
    assert factory.clients[0].closed


def test_no_refresh_with_fake_factory_by_default(home, data_dir):
    factory = FakeAgentFactory()
    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), agent_factory=factory)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS):
        pass
    assert factory.clients == []
