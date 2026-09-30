# backend/tests/test_digest_model.py
"""Digest model: SDK options, real client over a stubbed query, fake client."""

from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from claude_agent_sdk.types import RateLimitEvent, RateLimitInfo

from vibing.digest.model import (
    DigestModelError,
    DigestRequest,
    FakeDigestModel,
    SdkDigestModel,
    build_digest_options,
)
from vibing.digest.prompt import DIGEST_SCHEMA

REQUEST = DigestRequest(system_prompt="regras", prompt="trecho", model="sonnet", effort="medium")
OUTPUT = {"short": "x", "phases": [], "plan_completed": False, "plan_evidence": None}


def result(**overrides) -> ResultMessage:
    fields = dict(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                  num_turns=1, session_id="sess-1", structured_output=OUTPUT)
    fields.update(overrides)
    return ResultMessage(**fields)


def stub_query(*messages, error: BaseException | None = None):
    calls = []

    async def query(*, prompt, options):
        calls.append((prompt, options))
        for message in messages:
            yield message
        if error is not None:
            raise error

    return query, calls


def test_options_have_no_tools_and_no_user_settings(tmp_path: Path) -> None:
    options = build_digest_options(REQUEST, tmp_path)
    assert options.tools == [] and options.setting_sources == []
    assert options.max_turns == 3 and options.model == "sonnet" and options.effort == "medium"
    assert options.system_prompt == "regras" and options.cwd == str(tmp_path)
    assert options.output_format == {"type": "json_schema", "schema": DIGEST_SCHEMA}


def test_options_cut_every_mcp_server(tmp_path: Path) -> None:
    options = build_digest_options(REQUEST, tmp_path)
    assert options.strict_mcp_config is True and not options.mcp_servers


@pytest.mark.anyio
async def test_returns_the_structured_output_and_deletes_the_session(tmp_path: Path) -> None:
    query, calls = stub_query(SystemMessage("init", {"session_id": "sess-1"}), result())
    deleted = []
    model = SdkDigestModel(tmp_path / "agent", query_fn=query,
                           delete_fn=lambda sid, directory: deleted.append((sid, directory)))
    assert await model.summarize(REQUEST) == OUTPUT
    assert calls[0][0] == "trecho"
    assert deleted == [("sess-1", str(tmp_path / "agent"))]
    assert (tmp_path / "agent").is_dir()


@pytest.mark.anyio
async def test_error_result_raises_and_still_deletes(tmp_path: Path) -> None:
    query, _ = stub_query(SystemMessage("init", {"session_id": "sess-1"}),
                          result(is_error=True, structured_output=None, result="boom"))
    deleted = []
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: deleted.append(s))
    with pytest.raises(DigestModelError) as info:
        await model.summarize(REQUEST)
    assert info.value.stop_pass is False
    assert deleted == ["sess-1"]


@pytest.mark.anyio
async def test_missing_output_raises(tmp_path: Path) -> None:
    query, _ = stub_query(result(structured_output=None))
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError, match="não devolveu o resumo"):
        await model.summarize(REQUEST)


@pytest.mark.anyio
async def test_rate_limit_stops_the_pass(tmp_path: Path) -> None:
    info = RateLimitInfo(status="rejected", resets_at=1_900_000_000)
    event = RateLimitEvent(rate_limit_info=info, uuid="r", session_id="sess-1")
    query, _ = stub_query(SystemMessage("init", {"session_id": "sess-1"}), event)
    deleted = []
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: deleted.append(s))
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True and err.value.resets_at == 1_900_000_000
    assert err.value.message.startswith("Limite da assinatura atingido.")
    assert deleted == ["sess-1"]


@pytest.mark.anyio
async def test_missing_cli_stops_the_pass(tmp_path: Path) -> None:
    query, _ = stub_query(error=CLINotFoundError("no claude"))
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True and "claude" in err.value.message


@pytest.mark.anyio
async def test_login_failure_stops_the_pass(tmp_path: Path) -> None:
    error = RuntimeError("Not logged in · Please run /login")
    query, _ = stub_query(error=error)
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True and "login" in err.value.message


@pytest.mark.anyio
async def test_delete_failure_is_ignored(tmp_path: Path) -> None:
    query, _ = stub_query(SystemMessage("init", {"session_id": "sess-1"}), result())

    def fail(sid, directory):
        raise OSError("nope")

    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=fail)
    assert await model.summarize(REQUEST) == OUTPUT


@pytest.mark.anyio
async def test_fake_model_returns_scripted_answers_and_errors() -> None:
    fake = FakeDigestModel([OUTPUT, DigestModelError("falhou")])
    assert await fake.summarize(REQUEST) == OUTPUT
    with pytest.raises(DigestModelError):
        await fake.summarize(REQUEST)
    assert fake.requests == [REQUEST, REQUEST]


LOGIN_TEXT = "Invalid API key · Please run /login"


def login_messages():
    return [
        SystemMessage("init", {"session_id": "sess-1"}),
        AssistantMessage(content=[TextBlock(text=LOGIN_TEXT)], model="haiku",
                         error="authentication_failed"),
        result(is_error=True, structured_output=None, result=LOGIN_TEXT),
    ]


@pytest.mark.anyio
async def test_expired_login_followed_by_process_error_stops_the_pass(tmp_path: Path) -> None:
    error = ProcessError("Command failed with exit code 1", exit_code=1,
                         stderr="Check stderr output for details")
    query, _ = stub_query(*login_messages(), error=error)
    deleted = []
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: deleted.append(s))
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True and "login" in err.value.message
    assert deleted == ["sess-1"]


@pytest.mark.anyio
async def test_expired_login_with_a_normal_exit_stops_the_pass(tmp_path: Path) -> None:
    query, _ = stub_query(*login_messages())
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True and "login" in err.value.message


@pytest.mark.anyio
async def test_login_marker_only_in_the_result_errors_stops_the_pass(tmp_path: Path) -> None:
    query, _ = stub_query(result(is_error=True, structured_output=None, result=None,
                                 errors=["OAuth token has expired"]))
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True


@pytest.mark.anyio
async def test_process_error_without_a_login_signal_does_not_stop_the_pass(tmp_path: Path) -> None:
    error = ProcessError("Command failed with exit code 1", exit_code=1, stderr="boom")
    query, _ = stub_query(SystemMessage("init", {"session_id": "sess-1"}), error=error)
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is False


@pytest.mark.anyio
async def test_on_init_receives_the_init_data(tmp_path: Path) -> None:
    data = {"session_id": "sess-1", "tools": [], "mcp_servers": []}
    query, _ = stub_query(SystemMessage("init", data), result())
    seen = []
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None,
                           on_init=seen.append)
    await model.summarize(REQUEST)
    assert seen == [data]


@pytest.mark.anyio
async def test_login_words_in_a_successful_reading_do_not_discard_it(tmp_path: Path) -> None:
    talk = AssistantMessage(content=[TextBlock(text="a sessão falou de Please run /login")],
                            model="haiku")
    query, _ = stub_query(SystemMessage("init", {"session_id": "sess-1"}), talk, result())
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    assert await model.summarize(REQUEST) == OUTPUT
