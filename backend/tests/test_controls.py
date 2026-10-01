"""Marco 5 in active sessions: models, options, autonomous turns, questions, plans, images.

Only the scripted fake agent is used.
"""

import asyncio
import base64

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, TextBlock

from test_sessions import by_session, make_env, env_cleanup, session_row, wait_until  # noqa: F401
from claudio_maestro.agent.fake import (
    DEFAULT_SERVER_MODELS,
    FakeAgentFactory,
    PauseStep,
    PermissionStep,
    init_message,
    local_command_message,
    response_messages,
    result_message,
    text_turn,
)
from claudio_maestro.sessions import (
    FALLBACK_MODELS,
    BypassNotConfirmedError,
    InvalidAnswerError,
    InvalidDecisionError,
    InvalidImageError,
    RejectMessageRequiredError,
)


async def connected(make_env, env_cleanup, *turns, **kwargs):
    """Env and session after a first turn, idle with a client."""
    script, ids = by_session(lambda sid: text_turn(sid, "oi"), *turns)
    env = make_env(script=script, **kwargs)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")
    return env, session


def options_events(env, session):
    return [e["data"] for e in env.recorder.of(session.session_id, "session.options")]


# Models --------------------------------------------------------------------


@pytest.mark.anyio
async def test_models_without_connected_session_are_the_fixed_list(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)

    models = env.manager.list_models()

    assert [m["value"] for m in models] == ["default", "opus", "sonnet", "haiku"]
    assert models == FALLBACK_MODELS
    for model in models:
        assert set(model) == {
            "value", "displayName", "description", "supportsEffort", "supportedEffortLevels"
        }
        assert model["supportedEffortLevels"] == ["low", "medium", "high", "xhigh", "max"]


@pytest.mark.anyio
async def test_models_come_from_server_info_after_connect(make_env, env_cleanup):
    extra = {**DEFAULT_SERVER_MODELS[0], "unexpected": 1}
    factory_info = {"models": [extra, DEFAULT_SERVER_MODELS[1]]}
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(factory=FakeAgentFactory(script=script, server_info=factory_info))
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("olá")
    await wait_until(lambda: session.state == "idle")

    assert env.manager.list_models() == DEFAULT_SERVER_MODELS
    # Cached: a second session does not ask again.
    other = env.new_session()
    await other.send("oi")
    await wait_until(lambda: other.state in ("idle", "running"))
    assert sum(c.server_info_calls for c in env.factory.clients) == 1


# Options -------------------------------------------------------------------


@pytest.mark.anyio
async def test_options_are_saved_and_used_on_connect(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    summary = await env.manager.update(
        session.session_id, model="sonnet", effort="max", permission_mode="acceptEdits"
    )
    assert summary["model"] == "sonnet"
    assert summary["effort"] == "max"
    assert summary["permission_mode"] == "acceptEdits"
    assert summary["effort_pending"] is False
    row = session_row(env.db_path, session.session_id)
    assert (row["model"], row["effort"], row["permission_mode"]) == ("sonnet", "max", "acceptEdits")

    await session.send("olá")
    options = env.factory.clients[0].options
    assert (options.model, options.effort, options.permission_mode) == (
        "sonnet", "max", "acceptEdits")


@pytest.mark.anyio
async def test_default_model_is_passed_as_none(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await env.manager.update(session.session_id, model="default")

    await session.send("olá")

    assert env.factory.clients[0].options.model is None


@pytest.mark.anyio
async def test_model_and_mode_change_live(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]

    await env.manager.update(session.session_id, model="opus", permission_mode="plan")

    assert client.model_calls == ["opus"]
    assert client.permission_mode_calls == ["plan"]
    assert len(env.factory.clients) == 1
    last = options_events(env, session)[-1]
    assert last["model"] == "opus" and last["permission_mode"] == "plan"
    assert last["effort_pending"] is False


@pytest.mark.anyio
async def test_echo_of_live_change_is_not_shown(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup,
        lambda sid: [local_command_message("Set model to `opus (claude-opus-5-5)`"),
                     *text_turn(sid, "ok")],
    )
    await env.manager.update(session.session_id, model="opus", permission_mode="plan")

    await session.send("de novo")
    await wait_until(lambda: session.state == "idle" and session.pending_turns == 0)

    notices = [i for i in session.snapshot()["items"] if i["type"] == "notice"]
    assert notices == []


@pytest.mark.anyio
async def test_effort_while_idle_reconnects_with_resume(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)

    summary = await env.manager.update(session.session_id, effort="high")
    await wait_until(lambda: len(env.factory.clients) == 2 and session.state == "idle")
    await wait_until(lambda: not session.effort_pending)

    old, new = env.factory.clients
    assert old.closed
    assert new.options.resume is True
    assert new.options.effort == "high"
    assert summary["effort"] == "high"
    events = [e for e in options_events(env, session) if e["effort"] == "high"]
    assert events[0]["effort_pending"] is True
    assert events[-1]["effort_pending"] is False


@pytest.mark.anyio
async def test_effort_during_turn_waits_for_turn_end(make_env, env_cleanup):
    pause = PauseStep()
    env, session = await connected(
        make_env, env_cleanup,
        lambda sid: [init_message(sid), pause, *text_turn(sid, "fim")[2:]],
        lambda sid: text_turn(sid, "depois"),
    )
    await session.send("longo")
    await pause.reached.wait()

    summary = await env.manager.update(session.session_id, effort="low")

    assert summary["effort_pending"] is True
    assert len(env.factory.clients) == 1
    pause.release.set()
    await wait_until(lambda: len(env.factory.clients) == 2 and not session.effort_pending)
    await wait_until(lambda: session.state == "idle")
    assert env.factory.clients[1].options.effort == "low"
    assert env.factory.clients[1].options.resume is True

    await session.send("próxima")
    await wait_until(lambda: session.state == "idle" and env.factory.clients[1].sent)
    assert env.factory.clients[1].sent == ["próxima"]


@pytest.mark.anyio
async def test_effort_without_client_is_not_pending(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()

    summary = await env.manager.update(session.session_id, effort="xhigh")

    assert summary["effort_pending"] is False
    assert env.factory.clients == []


@pytest.mark.anyio
async def test_init_updates_saved_mode_and_model(make_env, env_cleanup):
    script, ids = by_session(
        lambda sid: [init_message(sid, model="claude-opus-5-5", permission_mode="default"),
                     *text_turn(sid, "feito")[1:]],
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await env.manager.update(session.session_id, permission_mode="plan")

    await session.send("execute o plano")
    await wait_until(lambda: session.state == "idle")

    row = session_row(env.db_path, session.session_id)
    assert row["permission_mode"] == "default"
    assert row["model"] is None  # the alias chosen is never replaced by the init
    last = options_events(env, session)[-1]
    assert last["permission_mode"] == "default"
    assert last["model_resolved"] == "claude-opus-5-5"
    assert session.summary()["model_resolved"] == "claude-opus-5-5"


@pytest.mark.anyio
async def test_bypass_requires_confirmation(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()

    with pytest.raises(BypassNotConfirmedError):
        await env.manager.update(session.session_id, permission_mode="bypassPermissions")
    assert session_row(env.db_path, session.session_id)["permission_mode"] is None

    summary = await env.manager.update(
        session.session_id, permission_mode="bypassPermissions", confirm_bypass=True
    )
    assert summary["permission_mode"] == "bypassPermissions"


# Autonomous turns ----------------------------------------------------------


@pytest.mark.anyio
async def test_turn_opened_by_cli_runs_and_ends(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    pause = PauseStep()

    turn = text_turn(session.session_id, "subagente terminou")
    client.push([init_message(session.session_id), turn[2], pause, *turn[3:]])
    await pause.reached.wait()
    # The reader may not have handled the messages before the pause yet.
    await wait_until(lambda: session.state == "running")
    assert session.pending_turns == 0

    pause.release.set()
    await wait_until(lambda: session.state == "idle")
    assert session.pending_turns == 0
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-1] == "subagente terminou"


@pytest.mark.anyio
async def test_stray_result_does_not_go_negative(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "segunda"))
    client = env.factory.clients[0]

    client.push([result_message(session.session_id)])
    await wait_until(lambda: len(env.recorder.of(session.session_id, "turn.result")) == 2)
    assert session.pending_turns == 0
    assert session.state == "idle"

    # A later send still counts normally.
    await session.send("de novo")
    await wait_until(lambda: session.state == "idle" and len(
        env.recorder.of(session.session_id, "turn.result")) == 3)
    assert session.pending_turns == 0


def results_of(env, session):
    return env.recorder.of(session.session_id, "turn.result")


@pytest.mark.anyio
async def test_autonomous_turn_then_user_turn(make_env, env_cleanup):
    """The CLI answers a message sent during an autonomous turn in a turn of its own."""
    pause = PauseStep()
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "resposta do usuário"))
    client = env.factory.clients[0]
    turn = text_turn(session.session_id, "autônomo")
    client.push([init_message(session.session_id), turn[2], pause, *turn[3:]])
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")

    await session.send("pergunta")
    pause.release.set()
    await wait_until(lambda: len(results_of(env, session)) == 3)
    await wait_until(lambda: session.state == "idle")

    assert session.pending_turns == 0
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-2:] == ["autônomo", "resposta do usuário"]


@pytest.mark.anyio
async def test_no_idle_between_autonomous_turn_and_user_turn(make_env, env_cleanup):
    pause = PauseStep()
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "resposta do usuário"))
    client = env.factory.clients[0]
    sid = session.session_id
    turn = text_turn(sid, "autônomo")
    client.push([init_message(sid), turn[2], pause, *turn[3:]])
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")
    await session.send("pergunta")
    pause.release.set()
    await wait_until(lambda: len(results_of(env, session)) == 3)
    await wait_until(lambda: session.state == "idle")

    events = env.recorder.of(sid)
    autonomous_end = [i for i, e in enumerate(events) if e["type"] == "turn.result"][1]
    user_end = [i for i, e in enumerate(events) if e["type"] == "turn.result"][2]
    between = [
        e["data"]["state"] for e in events[autonomous_end:user_end]
        if e["type"] == "session.state"
    ]
    assert "idle" not in between
    assert all(
        e["data"]["state"] == "running"
        for e in events[autonomous_end:user_end] if e["type"] == "session.updated"
    )


@pytest.mark.anyio
async def test_two_messages_during_autonomous_turn_get_two_turns(make_env, env_cleanup):
    pause = PauseStep()
    env, session = await connected(
        make_env, env_cleanup,
        lambda sid: text_turn(sid, "resposta 1"), lambda sid: text_turn(sid, "resposta 2"))
    client = env.factory.clients[0]
    sid = session.session_id
    turn = text_turn(sid, "autônomo")
    client.push([init_message(sid), turn[2], pause, *turn[3:]])
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")
    await session.send("primeira")
    await session.send("segunda")
    assert session.pending_turns == 2

    pause.release.set()
    await wait_until(lambda: len(results_of(env, session)) == 4)
    await wait_until(lambda: session.state == "idle")

    assert session.pending_turns == 0
    events = env.recorder.of(sid)
    ends = [i for i, e in enumerate(events) if e["type"] == "turn.result"]
    between = [e["data"]["state"] for e in events[ends[1]:ends[3]] if e["type"] == "session.state"]
    assert "idle" not in between
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-3:] == ["autônomo", "resposta 1", "resposta 2"]


@pytest.mark.anyio
async def test_effort_does_not_reconnect_between_autonomous_and_user_turn(
    make_env, env_cleanup
):
    pause, user_pause = PauseStep(), PauseStep()

    def user_turn(sid):
        turn = text_turn(sid, "resposta do usuário")
        return [turn[0], turn[1], turn[2], user_pause, *turn[3:]]

    env, session = await connected(make_env, env_cleanup, user_turn)
    client = env.factory.clients[0]
    sid = session.session_id
    turn = text_turn(sid, "autônomo")
    client.push([init_message(sid), turn[2], pause, *turn[3:]])
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")
    await env.manager.update(sid, effort="high")
    await session.send("pergunta")

    pause.release.set()
    await asyncio.wait_for(user_pause.reached.wait(), 2)
    await asyncio.sleep(0.02)
    # The CLI is answering the user: the client must not be swapped under it.
    assert len(env.factory.clients) == 1
    assert not client.closed
    assert session.state == "running"

    user_pause.release.set()
    await wait_until(lambda: len(env.factory.clients) == 2 and not session.effort_pending)
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-2:] == ["autônomo", "resposta do usuário"]


@pytest.mark.anyio
async def test_followup_init_ends_the_wait_before_message_start(
    make_env, env_cleanup, monkeypatch
):
    """The follow-up turn opens with an init; the first stream event only comes after
    the time to the first byte, which can outlast the grace period."""
    monkeypatch.setattr("claudio_maestro.sessions.AUTONOMOUS_FOLLOWUP_GRACE", 0.05)
    pause, user_pause = PauseStep(), PauseStep()

    def user_turn(sid):
        turn = text_turn(sid, "resposta do usuário")
        return [turn[0], user_pause, *turn[1:]]

    env, session = await connected(make_env, env_cleanup, user_turn)
    client = env.factory.clients[0]
    sid = session.session_id
    turn = text_turn(sid, "autônomo")
    client.push([init_message(sid), turn[2], pause, *turn[3:]])
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")
    await env.manager.update(sid, effort="high")
    await session.send("pergunta")
    pause.release.set()

    await asyncio.wait_for(user_pause.reached.wait(), 2)
    # Several times the grace period, with only the init of the follow-up seen.
    await asyncio.sleep(0.3)
    assert session.state == "running"
    assert session.pending_turns == 1
    assert len(env.factory.clients) == 1
    assert not client.closed

    user_pause.release.set()
    await wait_until(lambda: len(results_of(env, session)) == 3)
    await wait_until(lambda: len(env.factory.clients) == 2 and not session.effort_pending)
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-2:] == ["autônomo", "resposta do usuário"]
    events = env.recorder.of(sid)
    ends = [i for i, e in enumerate(events) if e["type"] == "turn.result"]
    between = [e["data"]["state"] for e in events[ends[1]:ends[2]] if e["type"] == "session.state"]
    assert "idle" not in between


@pytest.mark.anyio
async def test_followup_expiry_keeps_effort_pending_until_next_send(
    make_env, env_cleanup, monkeypatch
):
    """When no follow-up turn comes the session goes idle without reconnecting (that
    would drop an answer still in flight); the next send applies the new effort."""
    monkeypatch.setattr("claudio_maestro.sessions.AUTONOMOUS_FOLLOWUP_GRACE", 0.05)
    pause = PauseStep()
    env, session = await connected(
        make_env, env_cleanup, lambda sid: [], lambda sid: text_turn(sid, "depois"))
    client = env.factory.clients[0]
    sid = session.session_id
    client.push([*response_messages(sid, [TextBlock(text="a")])[:1], pause,
                 *response_messages(sid, [TextBlock(text="b")])[1:],
                 result_message(sid)])
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")
    await env.manager.update(sid, effort="high")
    await session.send("pergunta")
    pause.release.set()

    await wait_until(lambda: session.state == "idle")
    await asyncio.sleep(0.05)
    assert session.pending_turns == 0
    assert session.effort_pending
    assert len(env.factory.clients) == 1

    await session.send("de novo")
    await wait_until(lambda: len(env.factory.clients) == 2 and not session.effort_pending)
    assert env.factory.clients[1].options.effort == "high"
    await wait_until(lambda: session.state == "idle")


# Questions -----------------------------------------------------------------

QUESTIONS = {
    "questions": [
        {"question": "Qual cor?", "header": "Cor", "multiSelect": False,
         "options": [{"label": "Azul", "description": ""}, {"label": "Verde", "description": ""}]},
        {"question": "Quais linguagens?", "header": "Ling", "multiSelect": True,
         "options": [{"label": "Python", "description": ""}, {"label": "Go", "description": ""}]},
    ]
}


async def prompt_turn(make_env, env_cleanup, tool_name, tool_input):
    script, ids = by_session(lambda sid: [
        init_message(sid), PermissionStep(tool_name, tool_input, "toolu_q"),
        *text_turn(sid, "ok")[2:],
    ])
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("vai")
    await wait_until(lambda: session.state == "awaiting_decision")
    [request] = env.recorder.of(session.session_id, "prompt.request")
    return env, session, request["data"]


@pytest.mark.anyio
async def test_question_prompt_is_answered(make_env, env_cleanup):
    env, session, data = await prompt_turn(make_env, env_cleanup, "AskUserQuestion", QUESTIONS)
    assert data["kind"] == "question"
    assert data["questions"] == QUESTIONS["questions"]

    answers = {"Qual cor?": "Verde", "Quais linguagens?": ["Python", "Go"]}
    session.resolve_prompt(data["prompt_id"], "answer", answers=answers)
    await wait_until(lambda: session.state == "idle")

    [record] = env.factory.clients[0].permission_results
    assert record.result == PermissionResultAllow(updated_input={
        **QUESTIONS, "answers": {"Qual cor?": "Verde", "Quais linguagens?": "Python, Go"},
    })
    [resolved] = env.recorder.of(session.session_id, "prompt.resolved")
    assert resolved["data"]["decision"] == "answer"


@pytest.mark.anyio
@pytest.mark.parametrize("answers", [
    None,
    {},
    {"Qual cor?": "Verde"},  # missing a question
    {"Qual cor?": "  ", "Quais linguagens?": ["Go"]},  # blank
    {"Qual cor?": "x" * 2001, "Quais linguagens?": ["Go"]},  # too long
    {"Qual cor?": "Verde", "Quais linguagens?": ["Go", " "]},  # blank in multi
    {"Qual cor?": ["Verde"], "Quais linguagens?": ["Go"]},  # list for single choice
    {"Qual cor?": "Verde", "Quais linguagens?": []},  # empty multi
    {"Qual cor?": "Verde", "Quais linguagens?": ["Go"], "Outra?": "x"},  # extra question
])
async def test_invalid_answers_are_refused(make_env, env_cleanup, answers):
    env, session, data = await prompt_turn(make_env, env_cleanup, "AskUserQuestion", QUESTIONS)

    with pytest.raises(InvalidAnswerError):
        session.resolve_prompt(data["prompt_id"], "answer", answers=answers)
    assert session.state == "awaiting_decision"
    session.resolve_prompt(data["prompt_id"], "deny")
    await wait_until(lambda: session.state == "idle")


@pytest.mark.anyio
async def test_free_text_answers_are_accepted(make_env, env_cleanup):
    env, session, data = await prompt_turn(make_env, env_cleanup, "AskUserQuestion", QUESTIONS)

    session.resolve_prompt(data["prompt_id"], "answer", answers={
        "Qual cor?": "  Roxo  ", "Quais linguagens?": ["Rust", "Go"]})
    await wait_until(lambda: session.state == "idle")

    [record] = env.factory.clients[0].permission_results
    assert record.result.updated_input["answers"] == {
        "Qual cor?": "Roxo", "Quais linguagens?": "Rust, Go"}


@pytest.mark.anyio
async def test_decision_must_match_prompt_kind(make_env, env_cleanup):
    env, session, data = await prompt_turn(make_env, env_cleanup, "AskUserQuestion", QUESTIONS)
    with pytest.raises(InvalidDecisionError):
        session.resolve_prompt(data["prompt_id"], "approve")
    with pytest.raises(InvalidDecisionError):
        session.resolve_prompt(data["prompt_id"], "allow_once")
    session.resolve_prompt(data["prompt_id"], "deny")
    await wait_until(lambda: session.state == "idle")


# Plans ---------------------------------------------------------------------

PLAN = {"plan": "# Plano\n\n1. Fazer", "planFilePath": "~/.claude/plans/x.md"}


@pytest.mark.anyio
async def test_plan_prompt_is_approved(make_env, env_cleanup):
    env, session, data = await prompt_turn(make_env, env_cleanup, "ExitPlanMode", PLAN)
    assert data["kind"] == "plan"
    assert data["plan"] == PLAN["plan"]

    session.resolve_prompt(data["prompt_id"], "approve")
    await wait_until(lambda: session.state == "idle")

    [record] = env.factory.clients[0].permission_results
    assert isinstance(record.result, PermissionResultAllow)


@pytest.mark.anyio
async def test_plan_rejection_needs_a_message(make_env, env_cleanup):
    env, session, data = await prompt_turn(make_env, env_cleanup, "ExitPlanMode", PLAN)

    with pytest.raises(RejectMessageRequiredError):
        session.resolve_prompt(data["prompt_id"], "reject", message="   ")
    session.resolve_prompt(data["prompt_id"], "reject", message="Faça em duas etapas")
    await wait_until(lambda: session.state == "idle")

    [record] = env.factory.clients[0].permission_results
    assert record.result == PermissionResultDeny(message="Faça em duas etapas")


@pytest.mark.anyio
async def test_plain_tool_prompt_has_kind_tool(make_env, env_cleanup):
    env, session, data = await prompt_turn(make_env, env_cleanup, "Bash", {"command": "ls"})
    assert data["kind"] == "tool"
    with pytest.raises(InvalidDecisionError):
        session.resolve_prompt(data["prompt_id"], "approve")
    session.resolve_prompt(data["prompt_id"], "allow_once")
    await wait_until(lambda: session.state == "idle")


# Images --------------------------------------------------------------------

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


@pytest.mark.anyio
async def test_images_are_sent_as_blocks(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "vi"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("veja", images=[{"media_type": "image/png", "data": PNG}])
    await wait_until(lambda: session.state == "idle")

    [sent] = env.factory.clients[0].sent
    assert sent == [
        {"type": "text", "text": "veja"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}},
    ]
    [user] = [i for i in session.snapshot()["items"] if i["type"] == "user"]
    assert user["images"] == [{"type": "image", "media_type": "image/png", "size": 108}]


@pytest.mark.anyio
async def test_image_without_text_is_accepted(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "vi"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("", images=[{"media_type": "image/webp", "data": PNG}])

    [sent] = env.factory.clients[0].sent
    assert [b["type"] for b in sent] == ["image"]


BIG = base64.b64encode(b"0" * (5 * 1024 * 1024 + 1)).decode()


@pytest.mark.anyio
@pytest.mark.parametrize("images,fragment", [
    ([{"media_type": "image/bmp", "data": PNG}], "formato"),
    ([{"media_type": "image/png", "data": "não é base64!"}], "inválid"),
    ([{"media_type": "image/png", "data": BIG}], "5 MB"),
    ([{"media_type": "image/png", "data": PNG}] * 11, "10"),
])
async def test_invalid_images_are_refused(make_env, env_cleanup, images, fragment):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()

    with pytest.raises(InvalidImageError) as info:
        await session.send("veja", images=images)

    assert fragment in str(info.value)
    assert session.snapshot()["items"] == []
    assert env.factory.clients == []


@pytest.mark.anyio
async def test_init_right_after_connect_does_not_stick_in_running(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]

    client.push([init_message(session.session_id)])
    await wait_until(lambda: session.builder.init is not None)
    await asyncio.sleep(0.01)
    assert session.state == "idle"


@pytest.mark.anyio
async def test_send_during_autonomous_turn_ends_idle(make_env, env_cleanup, monkeypatch):
    """If the CLI answers the user inside the autonomous turn (one result only): no
    turn follows, and after a short wait the session stops counting the message."""
    monkeypatch.setattr("claudio_maestro.sessions.AUTONOMOUS_FOLLOWUP_GRACE", 0.05)
    pause = PauseStep()
    env, session = await connected(make_env, env_cleanup, lambda sid: [])
    client = env.factory.clients[0]
    client.push([*response_messages(session.session_id, [TextBlock(text="a")])[:1], pause,
                 *response_messages(session.session_id, [TextBlock(text="b")])[1:],
                 result_message(session.session_id)])
    await pause.reached.wait()
    # The reader may not have handled the messages before the pause yet.
    await wait_until(lambda: session.state == "running")

    await session.send("pergunta")
    pause.release.set()
    await wait_until(lambda: len(results_of(env, session)) == 2)
    # Still running while it waits for a turn that may follow.
    assert session.state == "running"
    await wait_until(lambda: session.state == "idle")
    assert session.pending_turns == 0


@pytest.mark.anyio
async def test_messages_absorbed_by_user_turn_end_idle(make_env, env_cleanup, monkeypatch):
    """The CLI folds messages sent during a normal turn into it: one result only. The
    session must stop counting them after the grace period instead of running forever."""
    monkeypatch.setattr("claudio_maestro.sessions.AUTONOMOUS_FOLLOWUP_GRACE", 0.05)
    pause = PauseStep()

    def first_turn(sid):
        turn = text_turn(sid, "resposta única")
        return [turn[0], turn[1], turn[2], pause, *turn[3:]]

    env, session = await connected(
        make_env, env_cleanup, first_turn, lambda sid: [], lambda sid: [])
    await session.send("primeira")
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")
    await session.send("segunda")
    await session.send("terceira")
    assert session.pending_turns == 3

    pause.release.set()
    await wait_until(lambda: len(results_of(env, session)) == 2)
    # Still running while it waits for a turn that may follow.
    assert session.state == "running"
    await wait_until(lambda: session.state == "idle")
    assert session.pending_turns == 0
    assert len(results_of(env, session)) == 2


@pytest.mark.anyio
async def test_user_turn_followed_by_real_turn_does_not_go_idle_between(
    make_env, env_cleanup, monkeypatch
):
    """One message is absorbed, another gets a turn of its own: the grace period after
    the first result is cancelled by the next turn, and the second one settles the count."""
    monkeypatch.setattr("claudio_maestro.sessions.AUTONOMOUS_FOLLOWUP_GRACE", 0.3)
    pause = PauseStep()

    def first_turn(sid):
        turn = text_turn(sid, "resposta 1")
        return [turn[0], turn[1], turn[2], pause, *turn[3:]]

    env, session = await connected(
        make_env, env_cleanup, first_turn, lambda sid: text_turn(sid, "resposta 2"),
        lambda sid: [])
    sid = session.session_id
    await session.send("primeira")
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")
    await session.send("segunda")
    await session.send("terceira")
    assert session.pending_turns == 3

    pause.release.set()
    await wait_until(lambda: len(results_of(env, session)) == 3)
    await wait_until(lambda: session.state == "idle")

    assert session.pending_turns == 0
    events = env.recorder.of(sid)
    ends = [i for i, e in enumerate(events) if e["type"] == "turn.result"]
    between = [e["data"]["state"] for e in events[ends[1]:ends[2]] if e["type"] == "session.state"]
    assert "idle" not in between
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert texts[-2:] == ["resposta 1", "resposta 2"]


@pytest.mark.anyio
async def test_close_during_followup_grace_leaves_nothing_running(make_env, env_cleanup):
    pause = PauseStep()
    env, session = await connected(make_env, env_cleanup, lambda sid: [])
    client = env.factory.clients[0]
    sid = session.session_id
    turn = text_turn(sid, "autônomo")
    client.push([init_message(sid), turn[2], pause, *turn[3:]])
    await pause.reached.wait()
    await wait_until(lambda: session.state == "running")
    await session.send("pergunta")
    pause.release.set()
    await wait_until(lambda: len(results_of(env, session)) == 2)

    await session.close()

    assert session.state == "closed"
    assert session.pending_turns == 0
    assert session._followup_task is None or session._followup_task.done()


@pytest.mark.anyio
async def test_close_during_effort_reconnect_leaves_no_client(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    old = env.factory.clients[0]
    pause = PauseStep()
    old.close_pause = pause

    await env.manager.update(session.session_id, effort="high")
    await pause.reached.wait()
    close = asyncio.create_task(env.manager.close_project(env.project.id))
    await asyncio.sleep(0.01)
    pause.release.set()
    await close
    await asyncio.sleep(0.01)

    assert session.client is None
    assert all(c.closed or not c.connected for c in env.factory.clients)


@pytest.mark.anyio
async def test_effort_reconnect_keeps_rename_and_turn_end(make_env, env_cleanup):
    pause = PauseStep()
    script, ids = by_session(lambda sid: [init_message(sid), pause, *text_turn(sid, "fim")[2:]])
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    renames, ends = [], []
    env.manager._rename_session = lambda sid, title, cwd: renames.append(title)
    env.manager._on_turn_end = ends.append
    session = env.new_session()
    ids.append(session.session_id)
    await env.manager.update(session.session_id, title="Meu nome")
    assert session.record.rename_pending

    await session.send("longo")
    await pause.reached.wait()
    await env.manager.update(session.session_id, effort="low")
    pause.release.set()
    await wait_until(lambda: len(env.factory.clients) == 2 and not session.effort_pending)

    assert renames == ["Meu nome"]
    assert ends == [env.project.id]
    assert not session.record.rename_pending
