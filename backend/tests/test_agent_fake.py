"""Scripted fake agent client used by the session tests."""

import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claudio_maestro.agent.base import AgentClient, AgentError, AgentOptions
from claudio_maestro.agent.fake import (
    INTERRUPTED_FOR_TOOL_USE,
    FailStep,
    FakeAgentClient,
    FakeAgentFactory,
    PauseStep,
    PermissionStep,
    result_message,
    scripted,
    text_turn,
    tool_turn,
)
from claudio_maestro.conversation import ConversationBuilder

SESSION_ID = "0b6f2d1c-7e4a-4c3b-9d8e-1f2a3b4c5d6e"


async def allow_all(name, tool_input, context):
    return PermissionResultAllow()


def make_options(tmp_path: Path, can_use_tool=allow_all) -> AgentOptions:
    return AgentOptions(
        cwd=tmp_path, session_id=SESSION_ID, resume=False, can_use_tool=can_use_tool
    )


async def collect_until_result(client: FakeAgentClient, results: int = 1) -> list:
    """Read messages until `results` ResultMessages arrived."""
    received = []
    seen = 0
    async with asyncio.timeout(2):
        async for message in client.messages():
            received.append(message)
            if isinstance(message, ResultMessage):
                seen += 1
                if seen == results:
                    break
    return received


def test_fake_satisfies_protocol(tmp_path):
    assert isinstance(FakeAgentClient(make_options(tmp_path)), AgentClient)


@pytest.mark.anyio
async def test_delivers_scripted_messages_per_send(tmp_path):
    client = FakeAgentClient(
        make_options(tmp_path),
        script=lambda content: text_turn(SESSION_ID, f"eco: {content}"),
    )
    await client.connect()

    await client.send("oi")
    first = await collect_until_result(client)
    await client.send("de novo")
    second = await collect_until_result(client)

    assert client.connected is True
    assert client.sent == ["oi", "de novo"]
    texts = [
        block.text
        for message in first + second
        if isinstance(message, AssistantMessage)
        for block in message.content
        if isinstance(block, TextBlock)
    ]
    assert texts == ["eco: oi", "eco: de novo"]
    assert isinstance(first[0], SystemMessage) and first[0].subtype == "init"
    assert first[0].data["session_id"] == SESSION_ID
    assert isinstance(first[-1], ResultMessage) and first[-1].subtype == "success"


@pytest.mark.anyio
async def test_send_records_content_blocks(tmp_path):
    client = FakeAgentClient(make_options(tmp_path), script=scripted([]))
    await client.connect()
    blocks = [{"type": "text", "text": "olhe"}]

    await client.send(blocks)

    assert client.sent == [blocks]


@pytest.mark.anyio
async def test_scripted_consumes_turns_in_order(tmp_path):
    client = FakeAgentClient(
        make_options(tmp_path),
        script=scripted(text_turn(SESSION_ID, "um"), text_turn(SESSION_ID, "dois")),
    )
    await client.connect()

    await client.send("a")
    await client.send("b")
    messages = await collect_until_result(client, results=2)

    texts = [
        m.content[0].text
        for m in messages
        if isinstance(m, AssistantMessage) and isinstance(m.content[0], TextBlock)
    ]
    assert texts == ["um", "dois"]


@pytest.mark.anyio
async def test_permission_step_calls_callback_and_records_result(tmp_path):
    calls = []

    async def deny(name, tool_input, context):
        calls.append((name, tool_input, context))
        return PermissionResultDeny(message="não")

    suggestion = PermissionUpdate(type="setMode", mode="acceptEdits", destination="session")
    client = FakeAgentClient(
        make_options(tmp_path, can_use_tool=deny),
        script=scripted(
            [
                PermissionStep(
                    "Write",
                    {"file_path": "a.txt", "content": "x"},
                    tool_use_id="toolu_1",
                    suggestions=[suggestion],
                ),
                result_message(SESSION_ID),
            ]
        ),
    )
    await client.connect()

    await client.send("escreva")
    await collect_until_result(client)

    name, tool_input, context = calls[0]
    assert name == "Write"
    assert tool_input == {"file_path": "a.txt", "content": "x"}
    assert isinstance(context, ToolPermissionContext)
    assert context.tool_use_id == "toolu_1"
    assert context.suggestions == [suggestion]
    assert len(client.permission_results) == 1
    record = client.permission_results[0]
    assert record.tool_name == "Write"
    assert isinstance(record.result, PermissionResultDeny)
    assert record.result.message == "não"


@pytest.mark.anyio
async def test_failure_step_raises_agent_error_in_messages(tmp_path):
    client = FakeAgentClient(
        make_options(tmp_path),
        script=scripted([*text_turn(SESSION_ID, "começo")[:3], FailStep("morreu")]),
    )
    await client.connect()
    await client.send("vai")
    received = []

    with pytest.raises(AgentError) as info:
        async with asyncio.timeout(2):
            async for message in client.messages():
                received.append(message)

    assert info.value.message_pt == "morreu"
    assert len(received) == 3


@pytest.mark.anyio
async def test_send_after_failure_raises_agent_error(tmp_path):
    client = FakeAgentClient(make_options(tmp_path), script=scripted([FailStep()]))
    await client.connect()
    await client.send("vai")
    with pytest.raises(AgentError):
        async with asyncio.timeout(2):
            async for _ in client.messages():
                pass

    with pytest.raises(AgentError):
        await client.send("outra")


@pytest.mark.anyio
async def test_send_before_connect_raises_agent_error(tmp_path):
    client = FakeAgentClient(make_options(tmp_path))

    with pytest.raises(AgentError):
        await client.send("oi")


@pytest.mark.anyio
async def test_connect_error_is_raised(tmp_path):
    client = FakeAgentClient(
        make_options(tmp_path), connect_error=AgentError("Sem Claude.")
    )

    with pytest.raises(AgentError):
        await client.connect()
    assert client.connected is False


@pytest.mark.anyio
async def test_pause_step_holds_turn_until_released(tmp_path):
    pause = PauseStep()
    turn = text_turn(SESSION_ID, "depois da pausa")
    client = FakeAgentClient(
        make_options(tmp_path),
        script=scripted([*turn[:2], pause, *turn[2:]], text_turn(SESSION_ID, "segundo")),
    )
    await client.connect()

    await client.send("primeiro")
    async with asyncio.timeout(2):
        await pause.reached.wait()
    await client.send("durante o turno")
    assert client.sent == ["primeiro", "durante o turno"]

    pause.release.set()
    messages = await collect_until_result(client, results=2)

    results = [m for m in messages if isinstance(m, ResultMessage)]
    assert len(results) == 2
    texts = [
        m.content[0].text
        for m in messages
        if isinstance(m, AssistantMessage) and isinstance(m.content[0], TextBlock)
    ]
    assert texts == ["depois da pausa", "segundo"]


@pytest.mark.anyio
async def test_interrupt_ends_turn_and_skips_remaining_steps(tmp_path):
    pause = PauseStep()
    turn = text_turn(SESSION_ID, "nunca chega")
    client = FakeAgentClient(
        make_options(tmp_path), script=scripted([*turn[:2], pause, *turn[2:]])
    )
    await client.connect()
    await client.send("vai")
    async with asyncio.timeout(2):
        await pause.reached.wait()

    await client.interrupt()
    messages = await collect_until_result(client)

    assert client.interrupts == 1
    assert len(messages) == 3
    result = messages[-1]
    assert isinstance(result, ResultMessage)
    assert result.subtype == "error_during_execution"
    assert not any(isinstance(m, AssistantMessage) for m in messages)


@pytest.mark.anyio
async def test_interrupt_cancels_pending_permission(tmp_path):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def wait_forever(name, tool_input, context):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    client = FakeAgentClient(
        make_options(tmp_path, can_use_tool=wait_forever),
        script=scripted([PermissionStep("Bash", {"command": "ls"}), result_message(SESSION_ID)]),
    )
    await client.connect()
    await client.send("vai")
    async with asyncio.timeout(2):
        await started.wait()

    await client.interrupt()
    messages = await collect_until_result(client)

    assert cancelled.is_set()
    assert messages[-1].subtype == "error_during_execution"
    assert client.permission_results == []


@pytest.mark.anyio
async def test_interrupt_with_pending_permission_mirrors_real_sdk(tmp_path):
    started = asyncio.Event()

    async def wait_forever(name, tool_input, context):
        started.set()
        await asyncio.Event().wait()

    turn = tool_turn(SESSION_ID, tool_name="Bash", tool_use_id="toolu_x", ask_permission=True)
    client = FakeAgentClient(
        make_options(tmp_path, can_use_tool=wait_forever), script=scripted(turn)
    )
    await client.connect()
    await client.send("vai")
    async with asyncio.timeout(2):
        await started.wait()

    await client.interrupt()
    messages = await collect_until_result(client)

    refusal, interrupted, result = messages[-3:]
    assert isinstance(refusal, UserMessage)
    [block] = refusal.content
    assert isinstance(block, ToolResultBlock)
    assert block.tool_use_id == "toolu_x"
    assert block.is_error is True
    assert isinstance(interrupted, UserMessage)
    assert interrupted.content == [TextBlock(text=INTERRUPTED_FOR_TOOL_USE)]
    assert result.subtype == "error_during_execution"
    assert result.is_error is True
    assert result.terminal_reason == "aborted_tools"

    builder = ConversationBuilder()
    for message in messages:
        builder.handle(message)
    notices = [item for item in builder.items if item.type == "notice"]
    assert [(n.level, n.text) for n in notices] == [("info", "Interrompido.")]
    [tool] = [item for item in builder.items if item.type == "tool"]
    assert tool.result["is_error"] is True
    assert tool.streaming is False


@pytest.mark.anyio
async def test_interrupt_without_permission_is_aborted_streaming(tmp_path):
    pause = PauseStep()
    turn = text_turn(SESSION_ID, "nunca chega")
    client = FakeAgentClient(
        make_options(tmp_path), script=scripted([*turn[:2], pause, *turn[2:]])
    )
    await client.connect()
    await client.send("vai")
    async with asyncio.timeout(2):
        await pause.reached.wait()

    await client.interrupt()
    messages = await collect_until_result(client)

    assert not any(isinstance(m, UserMessage) for m in messages)
    assert messages[-1].terminal_reason == "aborted_streaming"
    builder = ConversationBuilder()
    for message in messages:
        builder.handle(message)
    assert [(i.type, i.level) for i in builder.items] == [("notice", "info")]


@pytest.mark.anyio
async def test_interrupt_without_turn_only_counts(tmp_path):
    client = FakeAgentClient(make_options(tmp_path), script=scripted())
    await client.connect()

    await client.interrupt()

    assert client.interrupts == 1


@pytest.mark.anyio
async def test_records_model_and_mode_changes_and_close(tmp_path):
    client = FakeAgentClient(make_options(tmp_path))
    await client.connect()

    await client.set_model("haiku")
    await client.set_model(None)
    await client.set_permission_mode("plan")
    await client.close()

    assert client.model_calls == ["haiku", None]
    assert client.permission_mode_calls == ["plan"]
    assert client.closed is True


@pytest.mark.anyio
async def test_close_ends_messages(tmp_path):
    client = FakeAgentClient(make_options(tmp_path), script=scripted())
    await client.connect()

    async def read_all():
        return [m async for m in client.messages()]

    reader = asyncio.create_task(read_all())
    await asyncio.sleep(0)
    await client.close()

    async with asyncio.timeout(2):
        assert await reader == []


@pytest.mark.anyio
async def test_factory_creates_and_records_clients(tmp_path):
    factory = FakeAgentFactory(script=scripted(text_turn(SESSION_ID, "oi")))
    options = make_options(tmp_path)

    client = factory(options)

    assert factory.clients == [client]
    assert client.options is options


# Helpers ------------------------------------------------------------------


def test_text_turn_matches_real_sdk_sequence():
    messages = text_turn(SESSION_ID, "olá", thinking="pensando")

    kinds = [
        m.event["type"] if isinstance(m, StreamEvent) else type(m).__name__
        for m in messages
    ]
    assert kinds == [
        "SystemMessage",
        "SystemMessage",
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "AssistantMessage",
        "content_block_stop",
        "content_block_start",
        "content_block_delta",
        "AssistantMessage",
        "content_block_stop",
        "message_delta",
        "message_stop",
        "ResultMessage",
    ]
    assert messages[1].subtype == "status"
    message_id = messages[2].event["message"]["id"]
    assistants = [m for m in messages if isinstance(m, AssistantMessage)]
    assert all(m.message_id == message_id for m in assistants)


def test_tool_turn_has_two_responses_and_tool_result():
    steps = tool_turn(
        SESSION_ID,
        tool_name="Write",
        tool_input={"file_path": "/p/a.txt", "content": "x"},
        tool_use_id="toolu_9",
        tool_use_result={"type": "create", "filePath": "/p/a.txt"},
        final_text="Feito.",
        ask_permission=True,
    )

    starts = [
        s.event["message"]["id"]
        for s in steps
        if isinstance(s, StreamEvent) and s.event["type"] == "message_start"
    ]
    assert len(set(starts)) == 2
    tool_uses = [
        b
        for s in steps
        if isinstance(s, AssistantMessage)
        for b in s.content
        if isinstance(b, ToolUseBlock)
    ]
    assert tool_uses[0].id == "toolu_9"
    permission_index = next(i for i, s in enumerate(steps) if isinstance(s, PermissionStep))
    user_index = next(i for i, s in enumerate(steps) if isinstance(s, UserMessage))
    assert permission_index < user_index
    assert steps[permission_index].tool_use_id == "toolu_9"
    assert steps[user_index].tool_use_result == {"type": "create", "filePath": "/p/a.txt"}
    assert isinstance(steps[-1], ResultMessage)


@pytest.mark.anyio
async def test_connect_error_can_depend_on_options(tmp_path):
    error = AgentError("em uso", session_in_use=True)
    factory = FakeAgentFactory(connect_error=lambda options: None if options.resume else error)

    fresh = factory(make_options(tmp_path))
    with pytest.raises(AgentError) as info:
        await fresh.connect()
    resumed = factory(AgentOptions(cwd=tmp_path, session_id=SESSION_ID, resume=True,
                                   can_use_tool=allow_all))
    await resumed.connect()

    assert info.value is error
    assert fresh.connected is False
    assert resumed.connected is True
    await resumed.close()


@pytest.mark.anyio
async def test_fake_client_cannot_detach(tmp_path):
    factory = FakeAgentFactory()
    client = factory(AgentOptions(cwd=tmp_path, session_id="s", resume=False,
                                  can_use_tool=lambda *a: None))
    assert await client.detach() is False
