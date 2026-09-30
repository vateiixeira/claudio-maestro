# backend/tests/test_digest_model.py
"""Digest model: SDK options, real client over a stubbed query, fake client."""

from pathlib import Path

import pytest
from claude_agent_sdk import CLINotFoundError, ResultMessage, SystemMessage
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
