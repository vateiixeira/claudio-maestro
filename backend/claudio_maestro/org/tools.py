"""Maestro tools given to each agent: registry, organization, notices, tasks, decisions, CI and
conclusion.

An in-process MCP server, one per agent session. The tools talk to a `ToolHost`
(implemented elsewhere), so this module never touches the database, the disk or
the sessions. Bad input becomes a tool error in Portuguese, and so does an error of the domain
(`OrgError` and its subclasses, whose message is already in Portuguese); only an unexpected
exception becomes the generic error. An exception never leaves a handler, so it can't break the
agent's turn.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from claudio_maestro.org.store import (
    COMMENT_MAX,
    DECISION_OPTION_MAX,
    DECISION_OPTIONS_MAX,
    DECISION_QUESTION_MAX,
    TASK_DESCRIPTION_MAX,
    TASK_PRIORITIES,
    TASK_STATUSES,
    TASK_TITLE_MAX,
    Item,
    OrgError,
)

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
MAX_AGENT_REF = 200
MAX_TASKS = 100
MAX_URL = 500

_GENERIC_ERROR = "Não foi possível concluir esta ação agora. Tente de novo."

ToolResult = dict[str, Any]


class ToolHost(Protocol):
    async def conclude(self, session_id: str, summary: str) -> None: ...

    async def notify(self, session_id: str, text: str) -> None: ...

    def lookup(self, agent_id: int, keys: list[str]) -> list[Item]: ...

    def record(
        self, agent_id: int, key: str, status: str, link: str | None, note: str | None
    ) -> Item: ...

    def organization(self, agent_id: int) -> list[dict[str, Any]]:
        """Agents of the caller's project: name, description, reports_to, is_me, enabled."""
        ...

    # Tasks. A task dict has `id, title, description, status, priority, assignee, reviewer,
    # creator, parent_id, blocked_reason, worktree, created_at, updated_at, can_change`
    # (agents by name); `task_read` adds `comments` as `{id, author, text, created_at}`.

    def tasks_list(
        self, agent_id: int, *, mine: bool, statuses: list[str] | None
    ) -> list[dict[str, Any]]: ...

    def task_read(self, agent_id: int, task_id: int) -> dict[str, Any]: ...

    async def task_create(self, agent_id: int, session_id: str, **fields: Any) -> dict[str, Any]:
        """`title, description, assignee, reviewer, parent_id, priority` (the agents by name or
        slug, `None` when left out)."""
        ...

    async def task_update(
        self, agent_id: int, session_id: str, task_id: int, **fields: Any
    ) -> dict[str, Any]:
        """`status, assignee, priority, comment` (`None` when left out)."""
        ...

    async def task_comment(
        self, agent_id: int, session_id: str, task_id: int, text: str
    ) -> dict[str, Any]: ...

    def decide(self, session_id: str, question: str, options: list[str]) -> dict[str, Any]: ...

    async def verify_ci(self, session_id: str, run_url: str) -> dict[str, Any]:
        """`receipt, conclusion, head_sha, run_url, repository, jobs`."""
        ...


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


def _optional_text(args: dict[str, Any], field: str, limit: int) -> str | None:
    """A text the agent may leave out; blank counts as left out."""
    value = _text_arg(args, field, limit, required=False)
    return value.strip() or None


def _int_arg(args: dict[str, Any], field: str, *, required: bool = True) -> int | None:
    value = args.get(field)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _InvalidInputError(f"O campo “{field}” precisa ser um número inteiro.")
    return value


def _choice_arg(
    args: dict[str, Any], field: str, choices: tuple[str, ...]
) -> str | None:
    value = args.get(field)
    if value is None or value == "":
        return None
    if value not in choices:
        raise _InvalidInputError(
            f"O campo “{field}” precisa ser um destes valores: {', '.join(choices)}."
        )
    return value


_TASK_KEYS = {
    "id": "id",
    "title": "titulo",
    "description": "descricao",
    "status": "status",
    "priority": "prioridade",
    "assignee": "responsavel",
    "reviewer": "revisor",
    "creator": "criador",
    "parent_id": "pai",
    "blocked_reason": "motivo_bloqueio",
    "worktree": "pasta",
    "created_at": "criada_em",
    "updated_at": "atualizada_em",
    "can_change": "pode_alterar",
}


def _task_payload(task: dict[str, Any]) -> dict[str, Any]:
    payload = {to: task[key] for key, to in _TASK_KEYS.items() if key in task}
    if task.get("comments") is not None:
        payload["comentarios"] = [
            {
                "id": comment["id"],
                "autor": comment["author"],
                "texto": comment["text"],
                "criado_em": comment["created_at"],
            }
            for comment in task["comments"]
        ]
    return payload


def _safe(
    handler: Callable[[dict[str, Any]], Awaitable[ToolResult]],
) -> Callable[[dict[str, Any]], Awaitable[ToolResult]]:
    async def wrapper(args: dict[str, Any]) -> ToolResult:
        try:
            return await handler(args)
        except _InvalidInputError as error:
            return _error(str(error))
        except OrgError as error:
            # The message of a domain error is for the person or the agent, in Portuguese.
            return _error(str(error))
        except Exception:
            logger.exception("Falha em uma ferramenta do agente")
            return _error(_GENERIC_ERROR)

    return wrapper


def build_tools(
    host: ToolHost, *, agent_id: int, session_id: str, main: bool = False
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
        found = host.lookup(agent_id, keys)
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
        host.record(agent_id, key, status, link or None, note or None)
        return _ok(f"Registrado: {key} ({status}).")

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
        "organizacao",
        "Lista os agentes do projeto: nome, identificador, descrição, chefe, se é você e se está "
        "ligado. Use para saber a quem pedir ou encaminhar algo; se dois agentes têm o mesmo "
        "nome, cite o identificador.",
        {"type": "object", "properties": {}},
    )
    @_safe
    async def organizacao(args: dict[str, Any]) -> ToolResult:
        agents = host.organization(agent_id)
        payload = {
            "agentes": [
                {
                    "nome": agent["name"],
                    "identificador": agent["slug"],
                    "descricao": agent["description"],
                    "chefe": agent["reports_to"],
                    "sou_eu": agent["is_me"],
                    "ligado": agent["enabled"],
                }
                for agent in agents
            ]
        }
        return _ok(json.dumps(payload, ensure_ascii=False))

    @tool(
        "tarefas_listar",
        "Lista as tarefas do projeto. Por padrão só as suas (que você executa ou revisa) e só as "
        "abertas (todo, in_progress, in_review, blocked); passe `minhas: false` para ver as de "
        "todos e `status` para escolher os estados (inclusive done e cancelled). "
        f"Volta no máximo as {MAX_TASKS} mais recentes.",
        {
            "type": "object",
            "properties": {
                "minhas": {
                    "type": "boolean",
                    "description": "Só as tarefas suas (padrão: sim).",
                },
                "status": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(TASK_STATUSES)},
                    "description": "Estados a listar (padrão: os abertos).",
                },
            },
        },
    )
    @_safe
    async def tarefas_listar(args: dict[str, Any]) -> ToolResult:
        mine = args.get("minhas")
        if mine is None:
            mine = True
        if not isinstance(mine, bool):
            raise _InvalidInputError("O campo “minhas” precisa ser verdadeiro ou falso.")
        statuses = args.get("status")
        if statuses is not None:
            if not isinstance(statuses, list) or not all(isinstance(s, str) for s in statuses):
                raise _InvalidInputError("O campo “status” precisa ser uma lista de textos.")
            if any(s not in TASK_STATUSES for s in statuses):
                raise _InvalidInputError(
                    f"O campo “status” aceita só estes valores: {', '.join(TASK_STATUSES)}."
                )
        tasks = host.tasks_list(agent_id, mine=mine, statuses=statuses or None)
        return _ok(json.dumps({"tarefas": [_task_payload(t) for t in tasks]}, ensure_ascii=False))

    @tool(
        "tarefa_ler",
        "Lê uma tarefa inteira: descrição, estado, responsável, revisor, tarefa-mãe e os "
        "comentários mais recentes. `pode_alterar` diz se você tem alçada para mudá-la.",
        {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Número da tarefa."}},
            "required": ["id"],
        },
    )
    @_safe
    async def tarefa_ler(args: dict[str, Any]) -> ToolResult:
        task_id = _int_arg(args, "id")
        assert task_id is not None
        task = host.task_read(agent_id, task_id)
        return _ok(json.dumps({"tarefa": _task_payload(task)}, ensure_ascii=False))

    @tool(
        "tarefa_criar",
        "Cria uma tarefa no seu projeto. Você pode atribuí-la a você mesmo ou a um subordinado "
        "(`responsavel`: o nome ou o identificador do agente; veja `organizacao`). Com `revisor`, "
        "a tarefa só fecha depois da revisão. `prioridade`: urgent, high, normal ou low. "
        f"Título até {TASK_TITLE_MAX} caracteres, descrição até {_n(TASK_DESCRIPTION_MAX)}.",
        {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Título curto da tarefa."},
                "descricao": {
                    "type": "string",
                    "description": "O que fazer e como saber que terminou.",
                },
                "responsavel": {
                    "type": "string",
                    "description": "Nome ou identificador do agente que executa (opcional).",
                },
                "pai": {"type": "integer", "description": "Número da tarefa-mãe (opcional)."},
                "prioridade": {"type": "string", "enum": list(TASK_PRIORITIES)},
                "revisor": {
                    "type": "string",
                    "description": "Nome ou identificador do agente que revisa (opcional).",
                },
            },
            "required": ["titulo", "descricao"],
        },
    )
    @_safe
    async def tarefa_criar(args: dict[str, Any]) -> ToolResult:
        title = _text_arg(args, "titulo", TASK_TITLE_MAX)
        description = _text_arg(args, "descricao", TASK_DESCRIPTION_MAX)
        task = await host.task_create(
            agent_id,
            session_id,
            title=title,
            description=description,
            assignee=_optional_text(args, "responsavel", MAX_AGENT_REF),
            reviewer=_optional_text(args, "revisor", MAX_AGENT_REF),
            parent_id=_int_arg(args, "pai", required=False),
            priority=_choice_arg(args, "prioridade", TASK_PRIORITIES),
        )
        return _ok(json.dumps({"tarefa": _task_payload(task)}, ensure_ascii=False))

    @tool(
        "tarefa_atualizar",
        "Muda o estado, o responsável ou a prioridade de uma tarefa. O comentário é obrigatório: "
        "diga o que mudou e por quê. Estados: todo, in_progress, in_review, blocked, done, "
        "cancelled. Só mude tarefas suas ou de subordinados; `done` de tarefa com revisor vira "
        f"`in_review`. Comentário até {_n(COMMENT_MAX)} caracteres.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Número da tarefa."},
                "status": {"type": "string", "enum": list(TASK_STATUSES)},
                "responsavel": {
                    "type": "string",
                    "description": "Nome ou identificador do novo responsável.",
                },
                "prioridade": {"type": "string", "enum": list(TASK_PRIORITIES)},
                "comentario": {"type": "string", "description": "O que mudou e por quê."},
            },
            "required": ["id", "comentario"],
        },
    )
    @_safe
    async def tarefa_atualizar(args: dict[str, Any]) -> ToolResult:
        task_id = _int_arg(args, "id")
        assert task_id is not None
        comment = _text_arg(args, "comentario", COMMENT_MAX)
        task = await host.task_update(
            agent_id,
            session_id,
            task_id,
            status=_choice_arg(args, "status", TASK_STATUSES),
            assignee=_optional_text(args, "responsavel", MAX_AGENT_REF),
            priority=_choice_arg(args, "prioridade", TASK_PRIORITIES),
            comment=comment,
        )
        return _ok(json.dumps({"tarefa": _task_payload(task)}, ensure_ascii=False))

    @tool(
        "tarefa_comentar",
        "Comenta numa tarefa sua ou de um subordinado, sem mudar o estado. Quem acompanha a "
        f"tarefa é avisado. Até {_n(COMMENT_MAX)} caracteres.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Número da tarefa."},
                "texto": {"type": "string", "description": "O comentário."},
            },
            "required": ["id", "texto"],
        },
    )
    @_safe
    async def tarefa_comentar(args: dict[str, Any]) -> ToolResult:
        task_id = _int_arg(args, "id")
        assert task_id is not None
        text = _text_arg(args, "texto", COMMENT_MAX)
        await host.task_comment(agent_id, session_id, task_id, text)
        return _ok(f"Comentário registrado na tarefa {task_id}.")

    @tool(
        "decidir",
        "Faz uma pergunta à pessoa quando falta uma decisão que só ela pode tomar. A resposta "
        "chega depois, num novo despertar: não decida por ela nem siga o que depende da resposta. "
        f"Pergunta até {_n(DECISION_QUESTION_MAX)} caracteres; opções (opcionais) até "
        f"{DECISION_OPTIONS_MAX}, de até {DECISION_OPTION_MAX} caracteres cada.",
        {
            "type": "object",
            "properties": {
                "pergunta": {"type": "string", "description": "A pergunta, com o contexto."},
                "opcoes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Respostas sugeridas (opcional).",
                },
            },
            "required": ["pergunta"],
        },
    )
    @_safe
    async def decidir(args: dict[str, Any]) -> ToolResult:
        question = _text_arg(args, "pergunta", DECISION_QUESTION_MAX)
        options = args.get("opcoes")
        if options is None:
            options = []
        if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
            raise _InvalidInputError("O campo “opcoes” precisa ser uma lista de textos.")
        if len(options) > DECISION_OPTIONS_MAX:
            raise _InvalidInputError(f"Use no máximo {DECISION_OPTIONS_MAX} opções.")
        if any(not o.strip() or len(o) > DECISION_OPTION_MAX for o in options):
            raise _InvalidInputError(
                f"Cada opção precisa ter de 1 a {DECISION_OPTION_MAX} caracteres."
            )
        decision = host.decide(session_id, question, options)
        return _ok(
            f"Pergunta enviada à pessoa (decisão {decision['id']}). A resposta chega depois, num "
            "novo despertar: aguarde, não decida por ela e não siga o que depende da resposta."
        )

    @tool(
        "verificar_ci",
        "Confere uma execução de CI do GitHub Actions e devolve um recibo. Passe o link da "
        "execução (https://github.com/dono/repo/actions/runs/NNN). Só vale se a pasta da sua "
        "sessão está limpa e no commit que o CI testou. O recibo comprova o que o GitHub "
        "informou, inclusive uma falha: cite sempre a conclusão junto do recibo.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Link da execução do CI."},
            },
            "required": ["url"],
        },
    )
    @_safe
    async def verificar_ci(args: dict[str, Any]) -> ToolResult:
        url = _text_arg(args, "url", MAX_URL).strip()
        result = await host.verify_ci(session_id, url)
        payload = {
            "conclusao": result["conclusion"],
            "recibo": result["receipt"],
            "commit": result["head_sha"],
            "url": result["run_url"],
            "repositorio": result["repository"],
            "jobs": [{"nome": j["name"], "conclusao": j["conclusion"]} for j in result["jobs"]],
        }
        return _ok(json.dumps(payload, ensure_ascii=False))

    @tool(
        "concluir",
        "Chame só quando a tarefa inteira terminou. Registra o resultado. "
        "Em uma rotina, encerra a sessão; em um chat, mantém a conversa aberta. "
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
        return _ok("Resultado registrado.")

    common = [
        registro_consultar, registro_gravar, avisar, organizacao, tarefas_listar, tarefa_ler,
        tarefa_criar, tarefa_atualizar, tarefa_comentar, decidir, verificar_ci,
    ]
    return common if main else [*common, concluir]


def build_server(
    host: ToolHost, *, agent_id: int, session_id: str, main: bool = False
) -> McpSdkServerConfig:
    tools = build_tools(host, agent_id=agent_id, session_id=session_id, main=main)
    return create_sdk_mcp_server(SERVER_NAME, tools=tools)
