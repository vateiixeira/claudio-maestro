"""Marco 5 routes: models, session options, prompt answers and images."""

import base64

from claude_agent_sdk import PermissionResultAllow

from test_sessions_api import api, factory, new_session, wait_state  # noqa: F401
from vibing.agent.fake import PermissionStep, init_message, text_turn

PNG = base64.b64encode(b"\x89PNG" + b"0" * 60).decode()


def test_models_fixed_list_before_any_session(api):
    response = api.get("/api/models")

    assert response.status_code == 200
    assert [m["value"] for m in response.json()] == ["default", "opus", "sonnet", "haiku"]


def test_models_from_sdk_after_connect(api, home, factory):
    factory.server_info = {"models": [{
        "value": "x", "displayName": "X", "description": "d",
        "supportsEffort": False, "supportedEffortLevels": [],
    }]}
    factory.script = lambda content: text_turn("x", "ok")
    session = new_session(api, home)
    api.post(f"/api/sessions/{session['session_id']}/messages", json={"text": "oi"})
    wait_state(api, session["session_id"], "idle")

    assert [m["value"] for m in api.get("/api/models").json()] == ["x"]


def test_patch_options(api, home):
    session = new_session(api, home)
    assert session["model"] is None and session["effort_pending"] is False

    response = api.patch(
        f"/api/sessions/{session['session_id']}",
        json={"model": "haiku", "effort": "high", "permission_mode": "plan"},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["model"], body["effort"], body["permission_mode"]) == ("haiku", "high", "plan")
    assert body["effort_pending"] is False
    listed = api.get("/api/sessions").json()[0]
    assert listed["permission_mode"] == "plan"


def test_patch_invalid_effort_or_mode(api, home):
    session = new_session(api, home)
    url = f"/api/sessions/{session['session_id']}"
    assert api.patch(url, json={"effort": "huge"}).status_code == 422
    assert api.patch(url, json={"permission_mode": "yolo"}).status_code == 422


def test_bypass_needs_confirmation(api, home):
    session = new_session(api, home)
    url = f"/api/sessions/{session['session_id']}"

    response = api.patch(url, json={"permission_mode": "bypassPermissions"})
    assert response.status_code == 400
    assert response.json()["detail"]

    response = api.patch(
        url, json={"permission_mode": "bypassPermissions", "confirm_bypass": True})
    assert response.status_code == 200
    assert response.json()["permission_mode"] == "bypassPermissions"


QUESTIONS = {"questions": [{
    "question": "Qual?", "header": "Q", "multiSelect": False,
    "options": [{"label": "A", "description": ""}, {"label": "B", "description": ""}],
}]}


def test_answer_question_via_api(api, home, factory):
    factory.script = lambda content: [
        init_message("x"), PermissionStep("AskUserQuestion", QUESTIONS, "toolu_q"),
        *text_turn("x", "ok")[2:],
    ]
    session = new_session(api, home)
    sid = session["session_id"]
    api.post(f"/api/sessions/{sid}/messages", json={"text": "pergunte"})
    snapshot = wait_state(api, sid, "awaiting_decision")
    [prompt] = snapshot["prompts"]
    assert prompt["kind"] == "question"
    url = f"/api/sessions/{sid}/prompts/{prompt['prompt_id']}"

    bad = api.post(url, json={"decision": "answer", "answers": {"Qual?": "  "}})
    assert bad.status_code == 400
    assert bad.json()["detail"]

    good = api.post(url, json={"decision": "answer", "answers": {"Qual?": "B"}})
    assert good.status_code == 200
    wait_state(api, sid, "idle")
    [record] = factory.clients[0].permission_results
    assert record.result == PermissionResultAllow(
        updated_input={**QUESTIONS, "answers": {"Qual?": "B"}})


def test_reject_plan_via_api_requires_message(api, home, factory):
    factory.script = lambda content: [
        init_message("x"), PermissionStep("ExitPlanMode", {"plan": "# P"}, "toolu_p"),
        *text_turn("x", "ok")[2:],
    ]
    session = new_session(api, home)
    sid = session["session_id"]
    api.post(f"/api/sessions/{sid}/messages", json={"text": "planeje"})
    [prompt] = wait_state(api, sid, "awaiting_decision")["prompts"]
    assert prompt["kind"] == "plan" and prompt["plan"] == "# P"
    url = f"/api/sessions/{sid}/prompts/{prompt['prompt_id']}"

    assert api.post(url, json={"decision": "reject"}).status_code == 400
    assert api.post(url, json={"decision": "reject", "message": "refaça"}).status_code == 200
    wait_state(api, sid, "idle")


def test_send_images(api, home, factory):
    factory.script = lambda content: text_turn("x", "ok")
    session = new_session(api, home)
    sid = session["session_id"]

    response = api.post(
        f"/api/sessions/{sid}/messages",
        json={"text": "veja", "images": [{"media_type": "image/jpeg", "data": PNG}]},
    )

    assert response.status_code == 202
    snapshot = wait_state(api, sid, "idle")
    [user] = [i for i in snapshot["items"] if i["type"] == "user"]
    assert user["images"][0]["media_type"] == "image/jpeg"
    assert "data" not in user["images"][0]


def test_send_invalid_image(api, home):
    session = new_session(api, home)
    response = api.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"text": "veja", "images": [{"media_type": "image/tiff", "data": PNG}]},
    )
    assert response.status_code == 400
    assert "formato" in response.json()["detail"]


def test_send_empty_text_without_images(api, home):
    session = new_session(api, home)
    response = api.post(f"/api/sessions/{session['session_id']}/messages", json={"text": " "})
    assert response.status_code == 400


def test_body_over_limit_is_refused(api, home):
    session = new_session(api, home)
    body = b'{"text": "' + b"a" * (60 * 1024 * 1024 + 1) + b'"}'
    response = api.post(
        f"/api/sessions/{session['session_id']}/messages",
        content=body, headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]


def test_chunked_body_over_limit_is_refused(api, home, monkeypatch):
    monkeypatch.setattr("vibing.security.MAX_BODY_BYTES", 1000)
    session = new_session(api, home)

    def chunks():
        for _ in range(5):
            yield b'{"text": "' + b"a" * 400 + b'"}'

    response = api.post(
        f"/api/sessions/{session['session_id']}/messages",
        content=chunks(), headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
