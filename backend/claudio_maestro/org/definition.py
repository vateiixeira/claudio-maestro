"""Leitura e escrita do `AGENT.md`: frontmatter YAML + prompt do agente."""

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal

import yaml

PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions")
DEFAULT_PERMISSION_MODE = "bypassPermissions"
DEFAULT_MAX_RUN_MINUTES = 120
DEFINITION_MAX_BYTES = 100_000
EFFORTS = ("low", "medium", "high", "xhigh", "max")

_KEYS = (
    "name",
    "description",
    "model",
    "effort",
    "permissionMode",
    "disallowedTools",
    "skills",
    "addDirs",
    "worktree",
    "maxRunMinutes",
)
_FENCE = "---"
_MISSING_FRONTMATTER = (
    "O arquivo precisa começar com um bloco `---` com o cabeçalho do agente, "
    "fechado por outra linha `---`, seguido do prompt."
)


class DefinitionError(ValueError):
    """Definição inválida. `message` está em português; `field` e `line` ajudam a tela."""

    def __init__(
        self, message: str, field: str | None = None, line: int | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.line = line


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    model: str | None
    effort: str | None
    permission_mode: str
    disallowed_tools: list[str]
    skills: list[str]
    add_dirs: list[str]
    worktree: bool
    max_run_minutes: int
    body: str


def definition_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_definition(text: str) -> AgentDefinition:
    if len(text.encode("utf-8")) > DEFINITION_MAX_BYTES:
        raise DefinitionError(
            f"O AGENT.md passa de {DEFINITION_MAX_BYTES // 1000} KB; reduza o texto."
        )
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise DefinitionError(_MISSING_FRONTMATTER, line=1)
    end = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == _FENCE), None
    )
    if end is None:
        raise DefinitionError(_MISSING_FRONTMATTER, line=1)
    block = lines[1:end]
    data = _load_block(block)
    body = "\n".join(lines[end + 1 :]).strip()

    def fail(message: str, field: str) -> DefinitionError:
        return DefinitionError(message, field=field, line=_field_line(block, field))

    for key in data:
        if key not in _KEYS:
            raise fail(
                f"Campo desconhecido no cabeçalho: `{key}`. "
                f"Campos aceitos: {', '.join(_KEYS)}.",
                key,
            )

    name = data.get("name")
    if name is None:
        raise DefinitionError(
            "O cabeçalho precisa do campo `name`.", field="name", line=1
        )
    if not isinstance(name, str) or not name.strip():
        raise fail("O campo `name` precisa ser um texto não vazio.", "name")

    description = data.get("description")
    if description is None:
        description = ""
    elif not isinstance(description, str):
        raise fail("O campo `description` precisa ser um texto.", "description")

    model = _optional_text(data, "model", fail)
    effort = _optional_text(data, "effort", fail)
    if effort is not None and effort not in EFFORTS:
        raise fail(
            f"O campo `effort` precisa ser um de: {', '.join(EFFORTS)}.", "effort"
        )

    permission_mode = data.get("permissionMode")
    if permission_mode is None:
        permission_mode = DEFAULT_PERMISSION_MODE
    elif permission_mode not in PERMISSION_MODES:
        raise fail(
            "O campo `permissionMode` precisa ser um de: "
            f"{', '.join(PERMISSION_MODES)}.",
            "permissionMode",
        )

    worktree = data.get("worktree")
    if worktree is None:
        worktree = False
    elif not isinstance(worktree, bool):
        raise fail("O campo `worktree` precisa ser `true` ou `false`.", "worktree")

    max_run = data.get("maxRunMinutes")
    if max_run is None:
        max_run = DEFAULT_MAX_RUN_MINUTES
    elif isinstance(max_run, bool) or not isinstance(max_run, int) or max_run < 1:
        raise fail(
            "O campo `maxRunMinutes` precisa ser um número inteiro de minutos, "
            "de 1 em diante.",
            "maxRunMinutes",
        )

    if not body:
        raise DefinitionError(
            "O agente precisa de um prompt depois do cabeçalho.",
            field="body",
            line=end + 1,
        )

    return AgentDefinition(
        name=name.strip(),
        description=description,
        model=model,
        effort=effort,
        permission_mode=permission_mode,
        disallowed_tools=_text_list(data, "disallowedTools", fail),
        skills=_text_list(data, "skills", fail),
        add_dirs=_text_list(data, "addDirs", fail),
        worktree=worktree,
        max_run_minutes=max_run,
        body=body,
    )


def render_definition(definition: AgentDefinition) -> str:
    """Gera o arquivo, omitindo do cabeçalho o que é igual ao padrão."""
    fields: dict[str, Any] = {"name": definition.name}
    if definition.description:
        fields["description"] = definition.description
    if definition.model is not None:
        fields["model"] = definition.model
    if definition.effort is not None:
        fields["effort"] = definition.effort
    if definition.permission_mode != DEFAULT_PERMISSION_MODE:
        fields["permissionMode"] = definition.permission_mode
    if definition.disallowed_tools:
        fields["disallowedTools"] = list(definition.disallowed_tools)
    if definition.skills:
        fields["skills"] = list(definition.skills)
    if definition.add_dirs:
        fields["addDirs"] = list(definition.add_dirs)
    if definition.worktree:
        fields["worktree"] = True
    if definition.max_run_minutes != DEFAULT_MAX_RUN_MINUTES:
        fields["maxRunMinutes"] = definition.max_run_minutes
    header = "".join(_dump_field(key, value) for key, value in fields.items())
    return f"{_FENCE}\n{header}{_FENCE}\n{definition.body.strip()}\n"


_TEMPLATES = {
    "cto": (
        "Coordena o trabalho do projeto: recebe objetivos, quebra em tarefas e delega.",
        "Você é o CTO deste projeto. Responde pelo trabalho de engenharia: recebe "
        "objetivos, quebra cada um em tarefas pequenas e claras e delega para os "
        "agentes que reportam a você, acompanhando o andamento e revisando o que "
        "voltar. Quando faltar uma decisão que não é sua, pergunte antes de seguir.",
    ),
    "worker": (
        "Executa as tarefas que recebe e comenta o resultado.",
        "Você é um agente de execução deste projeto. Faz a tarefa que lhe foi "
        "atribuída, do começo ao fim, e comenta o resultado na própria tarefa: o que "
        "foi feito, o que ficou de fora e o que merece atenção. Se algo bloquear o "
        "trabalho, diga o que falta em vez de adivinhar.",
    ),
}


def template(name: str, kind: Literal["cto", "worker"]) -> str:
    """AGENT.md inicial: só texto, sem tratamento especial no código."""
    description, body = _TEMPLATES[kind]
    return render_definition(
        AgentDefinition(
            name=name.strip(),
            description=description,
            model=None,
            effort=None,
            permission_mode=DEFAULT_PERMISSION_MODE,
            disallowed_tools=[],
            skills=[],
            add_dirs=[],
            worktree=False,
            max_run_minutes=DEFAULT_MAX_RUN_MINUTES,
            body=body,
        )
    )


def _dump_field(key: str, value: Any) -> str:
    # Uma chave por vez: o PyYAML escreveria um mapa só de folhas numa linha
    # `{name: X}`. Listas saem em linha (`[a, b]`); o resto, em bloco.
    if isinstance(value, list):
        items = yaml.safe_dump(
            value, allow_unicode=True, default_flow_style=True, width=1_000_000
        ).strip()
        return f"{key}: {items}\n"
    return yaml.safe_dump(
        {key: value}, allow_unicode=True, default_flow_style=False, width=1_000_000
    )


def _load_block(block: list[str]) -> dict[str, Any]:
    try:
        data = yaml.safe_load("\n".join(block))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 2 if mark is not None else None  # +1 da cerca, +1 de base 1
        problem = getattr(exc, "problem", None) or "YAML inválido"
        raise DefinitionError(
            f"O cabeçalho do AGENT.md não é um YAML válido: {problem}.", line=line
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DefinitionError(
            "O cabeçalho precisa ser uma lista de campos `chave: valor`.", line=2
        )
    return {str(k): v for k, v in data.items()}


def _field_line(block: list[str], field: str) -> int | None:
    pattern = re.compile(rf"^{re.escape(field)}\s*:")
    for index, line in enumerate(block):
        if pattern.match(line):
            return index + 2
    return None


def _optional_text(data: dict[str, Any], key: str, fail) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise fail(f"O campo `{key}` precisa ser um texto.", key)
    return value.strip() or None


def _text_list(data: dict[str, Any], key: str, fail) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise fail(f"O campo `{key}` precisa ser uma lista de textos.", key)
    return list(value)
