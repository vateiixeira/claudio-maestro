"""What the digest agent is told: fixed rules, answer schema and the request text."""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from claudio_maestro.digest.store import Digest
from claudio_maestro.plans import PlanProgress, _read_limited

PHASE_KINDS: tuple[str, ...] = ("plan", "spec", "feature", "adjustments", "investigation", "other")
PHASE_STATUSES: tuple[str, ...] = ("open", "done")
SHORT_LIMIT = 140
TITLE_LIMIT = 120
ITEM_LIMIT = 200
MAX_ITEMS = 12
MAX_PHASES = 20
MAX_SPECS = 10
SPEC_DIR = ("docs", "superpowers", "specs")

SYSTEM_PROMPT = """Você mantém o resumo de trabalho de uma sessão do Claude Code, para o dono dela acompanhar sem reler a conversa. Escreva em português do Brasil, com frases curtas e concretas, sem adjetivos.

Você recebe o resumo atual (pode estar vazio), o plano vinculado à sessão com o estado de cada tarefa, os specs citados e um trecho novo da conversa, condensado: [Você] são os pedidos do usuário, [Claude] as respostas, e linhas como [Edit] caminho são ferramentas usadas.

Regras:
1. Divida o trabalho em fases pela intenção dos pedidos do usuário. Executar um plano, os ajustes feitos depois dele e uma feature nova são fases diferentes. Investigar um problema também é uma fase.
2. Devolva todas as fases, em ordem. As fases com status "done" do resumo atual voltam exatamente como estão. Você pode atualizar a fase "open", fechá-la ("done") e abrir fases novas. No máximo uma fase fica "open", sempre a última.
3. "done" lista entregas concluídas e "pending" o que falta, cada item com até 200 caracteres e no máximo 12 itens. Cite o número da tarefa do plano quando houver ("Tarefa 4: rotas de agrupador").
4. "kind": plan (execução de um plano), spec (escrita de spec ou design), feature, adjustments (ajustes e correções), investigation, other.
5. "ref": caminho absoluto do plano ou spec da fase, copiado das entradas; senão null.
6. "short": o que a sessão faz agora, em até 140 caracteres.
7. "plan_completed": true só se o trecho mostrar que o plano vinculado terminou (todas as tarefas concluídas, revisão final aprovada). Cite essa evidência em "plan_evidence"; senão false e null.
8. Não invente. O que o trecho não mostra, você não afirma."""

_PHASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "kind", "status", "done", "pending", "ref"],
    "properties": {
        "title": {"type": "string"},
        "kind": {"type": "string", "enum": list(PHASE_KINDS)},
        "status": {"type": "string", "enum": list(PHASE_STATUSES)},
        "done": {"type": "array", "items": {"type": "string"}},
        "pending": {"type": "array", "items": {"type": "string"}},
        "ref": {"type": ["string", "null"]},
    },
}

DIGEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["short", "phases", "plan_completed", "plan_evidence"],
    "properties": {
        "short": {"type": "string"},
        "phases": {"type": "array", "items": _PHASE_SCHEMA},
        "plan_completed": {"type": "boolean"},
        "plan_evidence": {"type": ["string", "null"]},
    },
}


def system_prompt(extra_instructions: str) -> str:
    extra = extra_instructions.strip()
    if not extra:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\nInstruções extras do usuário:\n{extra}"


def is_spec_path(path: str | Path, roots: Iterable[Path]) -> Path | None:
    """Resolved path of a `.md` directly inside `docs/superpowers/specs/` of a project."""
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if resolved.suffix.lower() != ".md" or tuple(resolved.parent.parts[-3:]) != SPEC_DIR:
        return None
    for root in roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return resolved
        except (OSError, RuntimeError):
            continue
    return None


def _title(path: Path) -> str:
    text = _read_limited(path)
    if text:
        for line in text.splitlines():
            if line.startswith("# "):
                return line[2:].strip() or path.stem
    return path.stem


def spec_refs(paths: Iterable[str], roots: Iterable[Path]) -> list[tuple[str, str]]:
    """(path, title) of the specs among `paths`, each once, at most MAX_SPECS. Blocking."""
    root_list = list(roots)
    seen: dict[Path, None] = {}
    for raw in paths:
        resolved = is_spec_path(raw, root_list)
        if resolved is not None and resolved not in seen:
            seen[resolved] = None
        if len(seen) >= MAX_SPECS:
            break
    return [(str(p), _title(p)) for p in seen]


def build_prompt(
    *,
    project: str,
    title: str,
    digest: Digest | None,
    plan: tuple[str, PlanProgress] | None,
    specs: list[tuple[str, str]],
    text: str,
    restarted: bool,
) -> str:
    parts = [f"## Sessão\nProjeto: {project}\nTítulo: {title}"]
    if digest is not None and (digest.short or digest.phases):
        current = json.dumps({"short": digest.short, "phases": digest.phases}, ensure_ascii=False)
        parts.append(f"## Resumo atual\n{current}")
    else:
        parts.append("## Resumo atual\nSem resumo.")
    if plan is not None:
        path, progress = plan
        tasks = "\n".join(
            f"- [{'x' if t.done else ' '}] Tarefa {t.number}: {t.title}" for t in progress.tasks
        )
        parts.append(
            f"## Plano vinculado\nCaminho: {path}\n"
            f"Título: {progress.title} ({progress.done}/{progress.total})\n{tasks}"
        )
    else:
        parts.append("## Plano vinculado\nNenhum.")
    if specs:
        parts.append("## Specs citados\n" + "\n".join(f"- {p}: {t}" for p, t in specs))
    else:
        parts.append("## Specs citados\nNenhum.")
    header = "## Trecho novo da conversa"
    if restarted:
        header += (
            "\nO arquivo da conversa foi compactado ou reescrito: o trecho recomeça no resumo"
            " de compactação e pode repetir o que o resumo atual já cobre."
        )
    parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)
