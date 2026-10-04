"""The closure check: can the session be closed, what is left for the user, what was
not delivered. Pure: the service reads files and git and calls the model."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from claudio_maestro.digest.closure_store import VERDICTS
from claudio_maestro.digest.condense import _user_texts
from claudio_maestro.digest.config import DigestConfig
from claudio_maestro.digest.store import Digest
from claudio_maestro.gitinfo import RepoStatus
from claudio_maestro.history import Transcript
from claudio_maestro.plans import PlanProgress

QUIET_SECONDS = 180
TAIL_BUDGET = 12_000
TAIL_PROMPTS = 2
ITEM_LIMIT = 200
MAX_ITEMS = 8
EVIDENCE_LIMIT = 200
CLOSED_STATES = ("idle", "closed")

SYSTEM_PROMPT = """Você confere se uma sessão do Claude Code pode ser fechada pelo dono dela. Escreva em português do Brasil, com frases curtas e concretas.

Você recebe o resumo da sessão (fases com o que foi feito e o que falta), o plano vinculado com as tarefas sem [x], fatos do git da pasta da sessão, os itens que o usuário já marcou como feitos e o final da conversa, condensado: [Você] são os pedidos do usuário, [Claude] as respostas, e linhas como [Edit] caminho são ferramentas usadas.

Regras:
1. "user_actions": só ações que o Claude pediu ou sugeriu ao usuário (reiniciar serviço, rodar comando, testar no navegador, aprovar, responder se pode publicar) e que a conversa não mostra feitas. Uma ação por item, no imperativo.
2. "missing": o que foi proposto ou combinado e não foi entregue: tarefas do plano sem [x], algo que o Claude disse que faria e não fez, mudanças sem commit ou commits sem push quando a conversa indica que deveriam estar commitados ou publicados.
3. Não repita itens que o usuário já fez.
4. "verdict": "in_progress" quando não há entrega fechada (conversa exploratória, investigação no meio, o Claude fez uma pergunta e espera resposta); "incomplete" se "missing" tem itens; senão "user_action" se "user_actions" tem itens; senão "can_close".
5. "evidence": uma frase de até 200 caracteres com o motivo do veredito.
6. Cada item com até 200 caracteres, no máximo 8 por lista.
7. Não invente. O que a conversa e os fatos não mostram, você não afirma."""

CLOSURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "user_actions", "missing", "evidence"],
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "user_actions": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": ["string", "null"]},
    },
}


class ClosureFormatError(ValueError):
    def __init__(self) -> None:
        super().__init__("Resposta do agente fora do formato.")


@dataclass(frozen=True)
class GitFacts:
    branch: str | None
    detached: bool
    staged: int
    unstaged: int
    untracked: int
    ahead: int | None
    upstream: str | None
    error: str | None

    @classmethod
    def from_status(cls, status: RepoStatus) -> "GitFacts":
        changed = status.changed or {}
        return cls(
            branch=status.branch, detached=status.detached,
            staged=int(changed.get("staged", 0)), unstaged=int(changed.get("unstaged", 0)),
            untracked=int(changed.get("untracked", 0)), ahead=status.ahead,
            upstream=status.upstream, error=status.error,
        )


def closure_system_prompt(extra_instructions: str) -> str:
    extra = extra_instructions.strip()
    if not extra:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\nInstruções extras do usuário:\n{extra}"


def _is_prompt(message: Any) -> bool:
    content = (getattr(message, "message", None) or {}).get("content")
    return getattr(message, "type", None) == "user" and any(
        t.strip() for t in _user_texts(content)
    )


def tail_messages(transcript: Transcript) -> list[Any]:
    """Entries from the TAIL_PROMPTS-th last user prompt on (everything if fewer)."""
    messages = transcript.messages
    prompts = [i for i, m in enumerate(messages) if _is_prompt(m)]
    if len(prompts) < TAIL_PROMPTS:
        return list(messages)
    return messages[prompts[-TAIL_PROMPTS]:]


def _git_section(git: GitFacts | None) -> str:
    if git is None or git.error:
        return "## Git\nSem dados do git."
    branch = "HEAD destacado" if git.detached else (git.branch or "desconhecido")
    push = (f"Commits sem push: {git.ahead}" if git.upstream and git.ahead is not None
            else "Sem upstream (branch nunca publicado)")
    return (f"## Git\nBranch: {branch}\n"
            f"Sem commit: {git.staged} staged, {git.unstaged} unstaged, {git.untracked} untracked\n"
            f"{push}")


def build_closure_prompt(
    *,
    project: str,
    title: str,
    digest: Digest | None,
    plan: tuple[str, PlanProgress] | None,
    git: GitFacts | None,
    resolved: list[str],
    tail: str,
) -> str:
    parts = [f"## Sessão\nProjeto: {project}\nTítulo: {title}"]
    if digest is not None and (digest.short or digest.phases):
        current = json.dumps({"short": digest.short, "phases": digest.phases}, ensure_ascii=False)
        parts.append(f"## Resumo atual\n{current}")
    else:
        parts.append("## Resumo atual\nSem resumo.")
    if plan is not None:
        path, progress = plan
        open_tasks = [t for t in progress.tasks if not t.done]
        listing = "\n".join(f"- Tarefa {t.number}: {t.title}" for t in open_tasks) or "- Nenhuma."
        parts.append(f"## Plano vinculado\nCaminho: {path}\n"
                     f"Título: {progress.title} ({progress.done}/{progress.total})\n"
                     f"Tarefas sem [x]:\n{listing}")
    else:
        parts.append("## Plano vinculado\nNenhum.")
    parts.append(_git_section(git))
    done = "\n".join(f"- {item}" for item in resolved) if resolved else "Nenhum."
    parts.append(f"## Itens que o usuário já fez\n{done}")
    parts.append(f"## Final da conversa\n{tail}")
    return "\n\n".join(parts)


def normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _items(raw: Any, resolved: set[str]) -> list[str]:
    if not isinstance(raw, list):
        raise ClosureFormatError()
    items: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            continue
        clean = " ".join(value.split())
        if clean and normalize(clean) not in resolved:
            items.append(_clip(clean, ITEM_LIMIT))
    return items[:MAX_ITEMS]


def decide(user_actions: list[str], missing: list[str], model_verdict: str) -> str:
    """The lists decide; the model only chooses "in_progress"."""
    if model_verdict == "in_progress":
        return "in_progress"
    if missing:
        return "incomplete"
    if user_actions:
        return "user_action"
    return "can_close"


def apply_answer(raw: Any, resolved: list[str]) -> tuple[str, list[str], list[str], str | None]:
    if not isinstance(raw, dict) or raw.get("verdict") not in VERDICTS:
        raise ClosureFormatError()
    done = {normalize(item) for item in resolved}
    actions = _items(raw.get("user_actions"), done)
    missing = _items(raw.get("missing"), set())
    evidence = raw.get("evidence")
    if isinstance(evidence, str) and evidence.strip():
        evidence = _clip(" ".join(evidence.split()), EVIDENCE_LIMIT)
    else:
        evidence = None
    return decide(actions, missing, raw["verdict"]), actions, missing, evidence


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:32]


def cheap_key(*, file_mtime: float, plan: PlanProgress | None, resolved: list[str]) -> str:
    """The part of the fingerprint read without git."""
    plan_part = None if plan is None else [plan.done, plan.total]
    return _hash([file_mtime, plan_part, sorted(normalize(r) for r in resolved)])


def fingerprint(cheap: str, git: GitFacts | None) -> str:
    return _hash([cheap, None if git is None else asdict(git)])


def closure_eligible(
    session: dict[str, Any],
    file_mtime: float | None,
    config: DigestConfig,
    now: float,
    *,
    automatic: bool,
) -> bool:
    """Turn closed and not finished; the automatic check also needs the switches on,
    activity within the window and the file quiet for QUIET_SECONDS."""
    if session.get("display_state") in ("finished", "running") or session.get("finished"):
        return False
    if session.get("state") not in CLOSED_STATES:
        return False
    if session.get("cli_running") or session.get("subagents_running"):
        return False
    if file_mtime is None:
        return False
    if not automatic:
        return True
    if not (config.enabled and config.closure_auto):
        return False
    if now - session["last_activity_at"] > config.window_days * 86400:
        return False
    return now - file_mtime >= QUIET_SECONDS
