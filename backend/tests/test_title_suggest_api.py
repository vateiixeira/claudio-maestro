"""POST /api/sessions/{id}/title-suggestions."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project

from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.digest.model import DigestModelError, FakeDigestModel
from claudio_maestro.history import Transcript


def msg(kind: str, text: str) -> SimpleNamespace:
    if kind == "user":
        return SimpleNamespace(type="user", uuid="u", message={"role": "user", "content": text})
    return SimpleNamespace(type="assistant", uuid="a", message={
        "role": "assistant", "content": [{"type": "text", "text": text}]})


@pytest.fixture
def model() -> FakeDigestModel:
    return FakeDigestModel()


@pytest.fixture
def api(model: FakeDigestModel):
    app = create_app(agent_factory=FakeAgentFactory(), digest_model=model)
    with TestClient(app, base_url=BACKEND_URL,
                    headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as client:
        yield client


@pytest.fixture
def sid(api: TestClient, home: Path) -> str:
    project = make_project(api, home)
    return api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]


def with_messages(api: TestClient, messages: list) -> None:
    service = api.app.state.digest
    service._session_file = lambda sid, cwd: Path("/x/file.jsonl")
    service._read_transcript = lambda path: Transcript(messages=messages, tool_results={})


def url(sid: str) -> str:
    return f"/api/sessions/{sid}/title-suggestions"


def test_returns_suggestions_and_does_not_rename(
    api: TestClient, sid: str, model: FakeDigestModel
) -> None:
    with_messages(api, [msg("user", "Ajuste o menu"), msg("assistant", "Pronto")])
    model.responses = [{"suggestions": ["Ajustar o menu", "Menu lateral", "Menu"]}]
    before = api.get("/api/sessions").json()[0]["title"]
    response = api.post(url(sid))
    assert response.status_code == 200
    assert response.json() == {"suggestions": ["Ajustar o menu", "Menu lateral", "Menu"]}
    assert api.get("/api/sessions").json()[0]["title"] == before


def test_unknown_session(api: TestClient) -> None:
    assert api.post(url("nope")).status_code == 404


def test_session_without_messages(api: TestClient, sid: str) -> None:
    with_messages(api, [])
    response = api.post(url(sid))
    assert response.status_code == 409
    assert response.json()["detail"] == "A conversa ainda não tem mensagens."


def test_model_failure(api: TestClient, sid: str, model: FakeDigestModel) -> None:
    with_messages(api, [msg("user", "oi")])
    model.responses = [DigestModelError("O login expirou.")]
    response = api.post(url(sid))
    assert response.status_code == 502
    assert response.json()["detail"] == "O login expirou."


def test_bad_format(api: TestClient, sid: str, model: FakeDigestModel) -> None:
    with_messages(api, [msg("user", "oi")])
    model.responses = [{"suggestions": []}]
    response = api.post(url(sid))
    assert response.status_code == 502
    assert response.json()["detail"] == "Resposta do agente fora do formato."


def test_needs_the_app_header_and_origin(api: TestClient, sid: str) -> None:
    assert api.post(url(sid), headers={"x-maestro": ""}).status_code == 403
    assert api.post(url(sid), headers={"origin": "https://evil.example"}).status_code == 403
