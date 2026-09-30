"""The model behind the digest agent: one short `query()` per session, no tools.

`SdkDigestModel` is the real one; tests use `FakeDigestModel`.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vibing.agent.sdk_client import (
    CLI_NOT_FOUND_MESSAGE,
    LOGIN_MARKERS,
    LOGIN_MESSAGE,
    to_agent_error,
)
from vibing.conversation import rate_limit_text
from vibing.digest.prompt import DIGEST_SCHEMA

logger = logging.getLogger(__name__)

MAX_TURNS = 3
NO_OUTPUT = "O agente não devolveu o resumo."
BAD_OUTPUT = "Resposta do agente fora do formato."


@dataclass(frozen=True)
class DigestRequest:
    system_prompt: str
    prompt: str
    model: str
    effort: str


class DigestModelError(Exception):
    """A failed reading. `stop_pass` ends the whole pass (login, CLI missing, limit)."""

    def __init__(self, message: str, *, stop_pass: bool = False, resets_at: int | None = None):
        super().__init__(message)
        self.message = message
        self.stop_pass = stop_pass
        self.resets_at = resets_at


class DigestModel(Protocol):
    async def summarize(self, request: DigestRequest) -> dict[str, Any]: ...


class FakeDigestModel:
    """Scripted answers for tests. With `gate`, each call waits for it to be set."""

    DEFAULT = {"short": "Resumo", "phases": [], "plan_completed": False, "plan_evidence": None}

    def __init__(self, responses: list[dict[str, Any] | Exception] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[DigestRequest] = []
        self.gate: asyncio.Event | None = None
        self.started = asyncio.Event()

    async def summarize(self, request: DigestRequest) -> dict[str, Any]:
        self.requests.append(request)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        item = self.responses.pop(0) if self.responses else dict(self.DEFAULT)
        if isinstance(item, Exception):
            raise item
        return item


def build_digest_options(
    request: DigestRequest, cwd: Path, stderr: Callable[[str], None] | None = None
) -> Any:
    from claude_agent_sdk import ClaudeAgentOptions

    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "model": request.model,
        "effort": request.effort,
        "tools": [],
        "max_turns": MAX_TURNS,
        "setting_sources": [],
        # `tools=[]` only covers built-in tools; this also cuts the MCP servers
        # from ~/.claude.json and the claude.ai connectors.
        "strict_mcp_config": True,
        "system_prompt": request.system_prompt,
        "output_format": {"type": "json_schema", "schema": DIGEST_SCHEMA},
    }
    if stderr is not None:
        kwargs["stderr"] = stderr
    return ClaudeAgentOptions(**kwargs)


def _has_login_marker(*texts: str | None) -> bool:
    return any(marker in text for text in texts if text for marker in LOGIN_MARKERS)


def _sdk_query(*, prompt: str, options: Any):
    from claude_agent_sdk import query

    return query(prompt=prompt, options=options)


def _sdk_delete(session_id: str, directory: str) -> None:
    from claude_agent_sdk import delete_session

    delete_session(session_id, directory=directory)


class SdkDigestModel:
    def __init__(
        self,
        cwd: Path,
        query_fn: Callable[..., Any] | None = None,
        delete_fn: Callable[[str, str], None] | None = None,
        on_init: Callable[[dict], None] | None = None,
    ) -> None:
        self._cwd = cwd
        self._on_init = on_init
        self._query = query_fn or _sdk_query
        self._delete = delete_fn or _sdk_delete

    def _delete_quietly(self, session_id: str) -> None:
        try:
            self._delete(session_id, str(self._cwd))
        except Exception:
            logger.warning("Não foi possível apagar a sessão %s do agente de resumos", session_id)

    async def summarize(self, request: DigestRequest) -> dict[str, Any]:
        from claude_agent_sdk import (
            AssistantMessage,
            CLINotFoundError,
            ResultMessage,
            SystemMessage,
            TextBlock,
        )
        from claude_agent_sdk.types import RateLimitEvent

        self._cwd.mkdir(parents=True, exist_ok=True)
        stderr_lines: deque[str] = deque(maxlen=50)
        options = build_digest_options(request, self._cwd, stderr_lines.append)
        session_id: str | None = None
        output: Any = None
        failure: str | None = None
        login_seen = False
        try:
            async with aclosing(self._query(prompt=request.prompt, options=options)) as stream:
                async for message in stream:
                    if isinstance(message, SystemMessage) and message.subtype == "init":
                        session_id = message.data.get("session_id") or session_id
                        if self._on_init is not None:
                            self._on_init(message.data)
                    elif isinstance(message, AssistantMessage):
                        texts = [b.text for b in message.content if isinstance(b, TextBlock)]
                        if message.error == "authentication_failed" or _has_login_marker(*texts):
                            login_seen = True
                    elif isinstance(message, RateLimitEvent):
                        info = message.rate_limit_info
                        if info.status == "rejected":
                            raise DigestModelError(
                                rate_limit_text(info.resets_at), stop_pass=True,
                                resets_at=info.resets_at,
                            )
                    elif isinstance(message, ResultMessage):
                        session_id = session_id or message.session_id
                        failed = message.is_error or message.structured_output is None
                        if failed and _has_login_marker(message.result, *(message.errors or [])):
                            login_seen = True
                        if failed and login_seen:
                            raise DigestModelError(LOGIN_MESSAGE, stop_pass=True)
                        if failed:
                            failure = NO_OUTPUT
                        else:
                            output = message.structured_output
        except DigestModelError:
            raise
        except CLINotFoundError as error:
            raise DigestModelError(CLI_NOT_FOUND_MESSAGE, stop_pass=True) from error
        except Exception as error:
            texts = [*stderr_lines, str(error), getattr(error, "stderr", None) or ""]
            if (login_seen and output is None) or _has_login_marker(*texts):
                raise DigestModelError(LOGIN_MESSAGE, stop_pass=True) from error
            raise DigestModelError(to_agent_error(error).message_pt) from error
        finally:
            if session_id:
                await asyncio.to_thread(self._delete_quietly, session_id)
        if login_seen and output is None:
            raise DigestModelError(LOGIN_MESSAGE, stop_pass=True)
        if output is None:
            raise DigestModelError(failure or NO_OUTPUT)
        if not isinstance(output, dict):
            raise DigestModelError(BAD_OUTPUT)
        return output
