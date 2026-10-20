"""Title suggestions: what the model is told, what it may answer and how the answer is cleaned.

Pure, like `prompt.py`: the service reads the conversation and calls the model.
"""

from typing import Any

from claudio_maestro.digest.condense import condense
from claudio_maestro.history import TITLE_MAX_LENGTH

SUGGESTIONS = 3
# Budget of the conversation text sent to the model (characters).
FIRST_BUDGET = 2500
RECENT_BUDGET = 8000
MAX_TEXT = FIRST_BUDGET + RECENT_BUDGET
EMPTY_MESSAGE = "A conversa ainda não tem mensagens."
FORMAT_MESSAGE = "Resposta do agente fora do formato."
NOT_FOUND_MESSAGE = "Conversa não encontrada."
UNEXPECTED_MESSAGE = "Falha inesperada ao sugerir títulos."
# Model used when the user never configured the summaries.
DEFAULT_MODEL = "haiku"
DEFAULT_EFFORT = "low"
_QUOTES = "\"'`“”‘’«»"

SYSTEM_PROMPT = """Você sugere títulos para uma sessão de trabalho do Claude Code, para o dono dela reconhecê-la numa lista de várias sessões.

Você recebe o projeto, o título atual, o primeiro pedido do usuário e um trecho da conversa, condensado: [Você] são os pedidos do usuário, [Claude] as respostas, e linhas como [Edit] caminho são ferramentas usadas.

Devolva exatamente três sugestões, em português do Brasil, cada uma com no máximo 60 caracteres.

Regras:
1. Diga o que está sendo feito, não como a conversa começou. Proibido começar com "Ajuda com", "Sessão sobre", "Conversa sobre" ou cumprimentos.
2. Sem aspas, sem ponto final, sem emojis.
3. Use verbo no infinitivo quando fizer sentido ("Sugerir títulos de sessão").
4. Pese mais o rumo que a conversa tomou do que só a primeira mensagem: se o trabalho mudou de assunto, o título acompanha o assunto atual.
5. Use nomes concretos do projeto quando ajudarem (a tela, o módulo, o bug). Nunca use caminhos de arquivo.
6. As três têm ângulos diferentes: a primeira foca o objetivo da sessão; a segunda é mais específica, com o detalhe técnico que distingue a sessão das outras; a terceira é bem curta, com até 30 caracteres.
7. Todas diferentes do título atual.
8. Não invente. O que a conversa não mostra, você não afirma."""

TITLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["suggestions"],
    "properties": {
        "suggestions": {
            "type": "array",
            "minItems": SUGGESTIONS,
            "maxItems": SUGGESTIONS,
            "items": {"type": "string"},
        },
    },
}


class TitleSuggestError(Exception):
    """Why no suggestions came out. `kind`: not_found, empty, model, format, timeout, unexpected."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


def split_conversation(messages: list[Any], cwd: str | None) -> tuple[str, str, int]:
    """(first request, the rest of the conversation, entries) as short text.

    The first request always goes; the rest is fitted to RECENT_BUDGET, which keeps the
    prompts and the newest entries, so the way the conversation went counts.
    """
    total = condense(messages, {}, cwd, budget=RECENT_BUDGET)
    if total.count == 0:
        return "", "", 0
    for index, message in enumerate(messages):
        if message.type != "user":
            continue
        first = condense([message], {}, cwd, budget=FIRST_BUDGET)
        if first.text.startswith("[Você]"):
            rest = condense(messages[index + 1:], {}, cwd, budget=RECENT_BUDGET)
            return first.text, rest.text, total.count
    return "", total.text, total.count


def build_prompt(*, project: str, title: str, first: str, recent: str) -> str:
    parts = [f"## Sessão\nProjeto: {project}\nTítulo atual: {title}"]
    parts.append(f"## Primeiro pedido\n{first or 'Sem pedido do usuário.'}")
    parts.append(f"## Rumo da conversa\n{recent or 'Nada além do primeiro pedido.'}")
    return "\n\n".join(parts)


def _clean(value: str) -> str:
    text = " ".join(value.split())
    previous = None
    while text != previous:
        previous = text
        text = text.strip(_QUOTES + " ").rstrip(".").strip()
    return text[:TITLE_MAX_LENGTH].rstrip()


def sanitize(raw: Any) -> list[str]:
    """Up to three clean, distinct titles from the model's answer; at least one or an error."""
    items = raw.get("suggestions") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise TitleSuggestError("format", FORMAT_MESSAGE)
    titles: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        title = _clean(item)
        if title and title.casefold() not in seen:
            seen.add(title.casefold())
            titles.append(title)
        if len(titles) == SUGGESTIONS:
            break
    if not titles:
        raise TitleSuggestError("format", FORMAT_MESSAGE)
    return titles
