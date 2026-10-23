"""Maestro tools given to each agent (specialist): registry, learnings, notices, conclusion.

An in-process MCP server, one per agent session. The tools talk to a `ToolHost`
(implemented elsewhere), so this module never touches the database, the disk or
the sessions. Bad input becomes a tool error in Portuguese; an exception never
leaves a handler, so it can't break the agent's turn.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from claudio_maestro.specialists.files import LEARNINGS_MAX_CHARS, LearningsTooLongError
from claudio_maestro.specialists.store import Item

logger = logging.getLogger(__name__)

SERVER_NAME = "maestro"
TOOL_PREFIX = "mcp__maestro__"

MAX_LOOKUP_KEYS = 200
MAX_KEY = 200
MAX_STATUS = 40
MAX_LINK = 500
MAX_NOTE = 500
MAX_NOTICE = 2000
MAX_SUMMARY = 4000

_GENERIC_ERROR = "Não foi possível concluir esta ação agora. Tente de novo."

ToolResult = dict[str, Any]


class ToolHost(Protocol):
    async def conclude(self, session_id: str, summary: str) -> None: ...

    async def notify(self, session_id: str, text: str) -> None: ...

    def lookup(self, specialist_id: int, keys: list[str]) -> list[Item]: ...

    def record(
        self, specialist_id: int, key: str, status: str, link: str | None, note: str | None
    ) -> Item: ...

    def rewrite_learnings(self, specialist_id: int, text: str) -> None: ...


class _InvalidInputError(Exception):
    """Input outside the limits; the message is shown to the model."""


def _n(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _ok(text: str) -> ToolResult:
    return {"content": [{"type": "text", "text": text}]}


def _error(text: str) -> ToolResult:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def _text_arg(args: dict[str, Any], field: str, limit: int, *, required: bool = True) -> str:
    value = args.get(field, "")
    # The SDK validates types against the schema first (in English); these checks are only defense.
    if value is None and not required:
        value = ""
    if not isinstance(value, str):
        raise _InvalidInputError(f"O campo “{field}” precisa ser um texto.")
    if required and not value.strip():
        raise _InvalidInputError(f"O campo “{field}” não pode ficar vazio.")
    if len(value) > limit:
        raise _InvalidInputError(
            f"O campo “{field}” passou do limite de {limit} caracteres (tem {len(value)})."
        )
    return value


def _safe(
    handler: Callable[[dict[str, Any]], Awaitable[ToolResult]],
) -> Callable[[dict[str, Any]], Awaitable[ToolResult]]:
    async def wrapper(args: dict[str, Any]) -> ToolResult:
        try:
            return await handler(args)
        except _InvalidInputError as error:
            return _error(str(error))
        except LearningsTooLongError as error:
            return _error(str(error))
        except Exception:
            logger.exception("Falha em uma ferramenta do agente")
            return _error(_GENERIC_ERROR)

    return wrapper


def build_tools(
    host: ToolHost, *, specialist_id: int, session_id: str, main: bool = False
) -> list[SdkMcpTool[Any]]:
    """The agent's tools. The main conversation never ends, so it has no `concluir`."""
    @tool(
        "registro_consultar",
        "Consulta o registro do agente: o que já foi tratado, com situação, link, nota e data. "
        "Use no começo da rotina, antes de agir sobre um item, para não repetir trabalho. "
        f"Passe até {MAX_LOOKUP_KEYS} chaves; só voltam os itens que existem.",
        {
            "type": "object",
            "properties": {
                "chaves": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Chaves dos itens a consultar.",
                },
            },
            "required": ["chaves"],
        },
    )
    @_safe
    async def registro_consultar(args: dict[str, Any]) -> ToolResult:
        keys = args.get("chaves")
        # The SDK validates types against the schema first (in English); these checks are only defense.
        if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
            raise _InvalidInputError("Informe uma lista de chaves (textos) para consultar.")
        if len(keys) > MAX_LOOKUP_KEYS:
            raise _InvalidInputError(f"Consulte no máximo {MAX_LOOKUP_KEYS} chaves por vez.")
        if any(len(key) > MAX_KEY for key in keys):
            raise _InvalidInputError(f"Cada chave pode ter no máximo {MAX_KEY} caracteres.")
        found = host.lookup(specialist_id, keys)
        payload = {
            "itens": [
                {
                    "chave": item.key,
                    "situacao": item.status,
                    "link": item.link,
                    "nota": item.note,
                    "atualizado_em": item.updated_at,
                }
                for item in found
            ]
        }
        return _ok(json.dumps(payload, ensure_ascii=False))

    @tool(
        "registro_gravar",
        "Grava ou atualiza um item no registro do agente. Use depois de tratar algo "
        "(situação como “feito” ou “pendente”), para que as próximas execuções saibam. "
        f"Chave até {MAX_KEY} caracteres, situação até {MAX_STATUS}, link e nota até {MAX_LINK}.",
        {
            "type": "object",
            "properties": {
                "chave": {"type": "string", "description": "Identificador estável do item."},
                "situacao": {"type": "string", "description": "Situação atual do item."},
                "link": {"type": "string", "description": "Link do item (opcional)."},
                "nota": {"type": "string", "description": "Observação curta (opcional)."},
            },
            "required": ["chave", "situacao"],
        },
    )
    @_safe
    async def registro_gravar(args: dict[str, Any]) -> ToolResult:
        key = _text_arg(args, "chave", MAX_KEY)
        status = _text_arg(args, "situacao", MAX_STATUS)
        link = _text_arg(args, "link", MAX_LINK, required=False)
        note = _text_arg(args, "nota", MAX_NOTE, required=False)
        host.record(specialist_id, key, status, link or None, note or None)
        return _ok(f"Registrado: {key} ({status}).")

    @tool(
        "aprendizados_reescrever",
        "Reescreve por inteiro o arquivo de aprendizados do agente, que você lê no início de "
        "cada sessão. Use quando descobrir algo que vale lembrar nas próximas execuções, "
        "consolidando o que já existe com o novo. "
        f"O texto novo substitui o antigo e vai até {_n(LEARNINGS_MAX_CHARS)} caracteres.",
        {
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "O texto completo dos aprendizados."},
            },
            "required": ["texto"],
        },
    )
    @_safe
    async def aprendizados_reescrever(args: dict[str, Any]) -> ToolResult:
        text = args.get("texto")
        # The SDK validates types against the schema first (in English); this check is only defense.
        if not isinstance(text, str):
            raise _InvalidInputError("O campo “texto” precisa ser um texto.")
        if len(text) > LEARNINGS_MAX_CHARS:
            raise LearningsTooLongError
        host.rewrite_learnings(specialist_id, text)
        return _ok("Aprendizados atualizados.")

    @tool(
        "avisar",
        "Manda um aviso curto para a pessoa, que aparece na caixa de avisos do Maestro. "
        "Use para algo que ela precisa saber sem que você pare o trabalho, "
        f"como um problema ou um resultado importante. Até {_n(MAX_NOTICE)} caracteres.",
        {
            "type": "object",
            "properties": {"texto": {"type": "string", "description": "O aviso."}},
            "required": ["texto"],
        },
    )
    @_safe
    async def avisar(args: dict[str, Any]) -> ToolResult:
        text = _text_arg(args, "texto", MAX_NOTICE)
        await host.notify(session_id, text)
        return _ok("Aviso enviado.")

    @tool(
        "concluir",
        "Chame só quando a tarefa inteira terminou. Encerra esta sessão. "
        f"Passe um resumo do que foi feito, até {_n(MAX_SUMMARY)} caracteres.",
        {
            "type": "object",
            "properties": {"resumo": {"type": "string", "description": "Resumo do que foi feito."}},
            "required": ["resumo"],
        },
    )
    @_safe
    async def concluir(args: dict[str, Any]) -> ToolResult:
        summary = _text_arg(args, "resumo", MAX_SUMMARY)
        await host.conclude(session_id, summary)
        return _ok("Sessão concluída.")

    common = [registro_consultar, registro_gravar, aprendizados_reescrever, avisar]
    return common if main else [*common, concluir]


def build_server(
    host: ToolHost, *, specialist_id: int, session_id: str, main: bool = False
) -> McpSdkServerConfig:
    tools = build_tools(host, specialist_id=specialist_id, session_id=session_id, main=main)
    return create_sdk_mcp_server(SERVER_NAME, tools=tools)
