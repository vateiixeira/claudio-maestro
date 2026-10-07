"""The delivery summary: one short call when a session is finished, with a title and
bullets of what was delivered in the part of the conversation the record covers."""

import json
from typing import Any

from claudio_maestro.digest.condense import Slice, entries_after
from claudio_maestro.digest.merge import DigestFormatError
from claudio_maestro.digest.store import Digest
from claudio_maestro.history import Transcript

TITLE_LIMIT = 120
BULLET_LIMIT = 200
MAX_BULLETS = 8

SYSTEM_PROMPT = """Você escreve o registro de entrega de uma sessão do Claude Code que o dono acabou de finalizar. O registro entra num changelog diário, lido em reuniões de daily. Escreva em português do Brasil, com frases curtas e concretas, sem adjetivos.

Você recebe o projeto, o título da sessão, o resumo de trabalho mantido até agora (pode estar vazio) e o trecho da conversa que este registro cobre, condensado: [Você] são os pedidos do usuário, [Claude] as respostas, e linhas como [Edit] caminho são ferramentas usadas.

Regras:
1. "title": o que foi entregue, em até 120 caracteres, sem ponto final.
2. "bullets": de 1 a 8 entregas concluídas no trecho, cada uma com até 200 caracteres. Só o que foi feito; pendências e planos não entram.
3. Prefira o resultado ao processo: "Rota de leitura de markdown com checagem de caminho", não "Editei api/markdown.py".
4. Use o resumo atual só como contexto: descreva o que o trecho mostra.
5. Não invente. O que o trecho não mostra, você não afirma."""

DELIVERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "bullets"],
    "properties": {
        "title": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
    },
}


def delivery_system_prompt(extra_instructions: str) -> str:
    extra = extra_instructions.strip()
    if not extra:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\nInstruções extras do usuário:\n{extra}"


def build_delivery_prompt(*, project: str, title: str, digest: Digest | None, text: str,
                          restarted: bool) -> str:
    parts = [f"## Sessão\nProjeto: {project}\nTítulo: {title}"]
    if digest is not None and (digest.short or digest.phases):
        current = json.dumps({"short": digest.short, "phases": digest.phases}, ensure_ascii=False)
        parts.append(f"## Resumo atual\n{current}")
    else:
        parts.append("## Resumo atual\nSem resumo.")
    header = "## Trecho da conversa coberto por este registro"
    if restarted:
        header += (
            "\nO arquivo da conversa foi compactado ou reescrito: o trecho recomeça no resumo"
            " de compactação e pode repetir trabalho de um registro anterior."
        )
    parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)


def slice_between(transcript: Transcript, from_cursor: str | None,
                  to_cursor: str | None) -> Slice:
    """Entries after `from_cursor` (exclusive) up to `to_cursor` (inclusive).

    A `to_cursor` before or equal to `from_cursor` gives nothing; one missing from the
    file (compacted away) or None goes to the end."""
    piece = entries_after(transcript, from_cursor)
    messages = piece.messages
    if to_cursor is not None:
        index = next((i for i, m in enumerate(messages) if m.uuid == to_cursor), None)
        if index is not None:
            messages = messages[: index + 1]
        elif any(m.uuid == to_cursor for m in transcript.messages):
            messages = []  # the end is at or before the start: nothing new
    return Slice(messages, messages[-1].uuid if messages else piece.cursor, piece.cursor_found)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def clean_delivery(raw: Any) -> tuple[str, list[str]]:
    if not isinstance(raw, dict):
        raise DigestFormatError()
    title, bullets = raw.get("title"), raw.get("bullets")
    if not isinstance(title, str) or not title.strip() or not isinstance(bullets, list):
        raise DigestFormatError()
    items = [_clip(b.strip(), BULLET_LIMIT) for b in bullets if isinstance(b, str) and b.strip()]
    if not items:
        raise DigestFormatError()
    return _clip(title.strip(), TITLE_LIMIT), items[:MAX_BULLETS]
