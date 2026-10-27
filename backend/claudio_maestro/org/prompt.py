"""Texto que o agente recebe: o `system_prompt_append` da sessão e o prompt de um despertar.

Nada aqui carrega segredo (eles só chegam como `env` do processo) nem regra de comando:
o que o agente pode ou não fazer vem do `AGENT.md` (`permissionMode`, `disallowedTools`).
"""

from dataclasses import dataclass

from claudio_maestro.org.definition import AgentDefinition

NO_BOSS = "Você não tem chefe: responde direto à pessoa que usa o Maestro."
NO_REPORTS = "Você não tem subordinados."
NO_ADD_DIRS = "Nenhuma pasta extra."
NO_MEMORY = "(nenhuma ainda)"

_CONCLUDE_LINE = (
    "- `concluir`: quando a tarefa inteira terminar, chame com um resumo do que foi feito. "
    "Isso encerra esta sessão.\n"
)
_CONCLUDE_CONVERSATION_LINE = (
    "- `concluir`: quando o pedido terminar, chame com um resumo do que foi feito. "
    "Nesta conversa, concluir registra o resultado e não encerra a sessão.\n"
)

OPERATING_SKILL = (
    """## Como trabalhar no Maestro

Você roda dentro do Cláudio Maestro, que oferece ferramentas próprias (servidor `maestro`) \
além das do projeto.

### Ferramentas do Maestro
- `registro_consultar`: antes de tratar itens (erros, issues, pedidos), consulte pelas chaves \
os que já foram tratados. Não refaça o que já está resolvido ou descartado, a menos que algo \
tenha mudado.
- `registro_gravar`: grave cada item que você tratar, com a situação, o link e uma nota curta. \
A chave é o identificador do item (por exemplo, o código do erro).
- `organizacao`: lista os agentes do projeto, com descrição e chefe. Use para saber a quem \
pedir ou encaminhar algo.
- `avisar`: mande à pessoa que usa o Maestro o que ela precisa saber agora (até 2.000 \
caracteres). Não use para relato de rotina.
"""
    + _CONCLUDE_LINE
    + """
### Memória
- Sua memória é o arquivo `memoria.md` da sua pasta, que já está acessível. Você mesmo a edita.
- Ela vale para as próximas execuções e entra neste prompt na seção "Memória". Anote só o que \
continua valendo: preferências, armadilhas, decisões. Reescreva consolidando, sem acumular \
histórico.
- Mantenha até 4.000 caracteres.

### Boas práticas
- Mantenha cada resposta curta e objetiva: a pessoa lê o resultado, não o caminho até ele.
- Se faltar uma decisão que só ela pode tomar, pergunte (AskUserQuestion) em vez de supor.
- Use as skills e as ferramentas do projeto como numa sessão normal.
- Nunca escreva segredos (senhas, tokens, chaves) em respostas, avisos, registros ou na memória.
"""
)

_MAIN_SECTION = """## Esta é a conversa principal
Aqui você conversa com a pessoa que usa o Maestro, a qualquer hora. Não é uma execução \
agendada: faça o que ela pedir. O fim de um turno não encerra esta conversa. Os resultados \
das execuções chegam como anúncios no bloco <maestro-anuncios>.

"""

_SKILLS_HEADING = (
    "## Skills a usar\n"
    "Carregue pela ferramenta Skill, quando o trabalho pedir:\n"
)


def _operating_skill(*, main: bool, conversation: bool) -> str:
    if main:
        return OPERATING_SKILL.replace(_CONCLUDE_LINE, "")
    if conversation:
        return OPERATING_SKILL.replace(_CONCLUDE_LINE, _CONCLUDE_CONVERSATION_LINE)
    return OPERATING_SKILL


@dataclass(frozen=True)
class OrgContext:
    """Onde o agente está na organização, já resolvido pelo serviço."""

    project_name: str
    project_path: str
    boss: tuple[str, str] | None  # (name, description)
    reports: list[tuple[str, str]]  # (name, description)
    add_dirs: list[tuple[str, str]]  # (label, path)
    # Arquivo `memoria.md` do agente (dentro da pasta dele, que está em `add_dirs`).
    memory_path: str = ""


def _person(name: str, description: str) -> str:
    return f"- {name}: {description}" if description.strip() else f"- {name}"


def _organization(context: OrgContext) -> str:
    lines = [
        "## Organização",
        f"Projeto: {context.project_name} ({context.project_path}). "
        "Você trabalha nessa pasta.",
        "",
        "Chefe:",
        _person(*context.boss) if context.boss else NO_BOSS,
        "",
        "Subordinados (delegue com critério, conforme a descrição de cada um):",
        "\n".join(_person(n, d) for n, d in context.reports) if context.reports else NO_REPORTS,
        "",
        "Pastas extras que você pode ler e editar:",
        "\n".join(f"- {label}: {path}" for label, path in context.add_dirs)
        if context.add_dirs
        else NO_ADD_DIRS,
        "",
        "",
    ]
    return "\n".join(lines)


def build_append(
    *,
    definition: AgentDefinition,
    context: OrgContext,
    memory: str,
    main: bool,
    conversation: bool,
) -> str:
    """O prompt do agente: `AGENT.md`, organização, skills, skill operacional e memória.

    A conversa principal não tem `concluir` (ela nunca termina) e diz o que é. Numa
    conversa de tarefa (`conversation`), `concluir` registra o resultado sem encerrar."""
    parts = [
        f"# Agente: {definition.name}\n\n{definition.body.strip()}\n\n",
        _organization(context),
    ]
    if definition.skills:
        parts.append(_SKILLS_HEADING + "\n".join(f"- {s}" for s in definition.skills) + "\n\n")
    parts.append(_operating_skill(main=main, conversation=conversation).rstrip() + "\n\n")
    if main:
        parts.append(_MAIN_SECTION)
    where = (
        f"Arquivo: `{context.memory_path}`."
        if context.memory_path
        else "Arquivo: `memoria.md`, na sua pasta."
    )
    parts.append(f"## Memória\n{where}\n\n{memory.strip() or NO_MEMORY}")
    return "".join(parts)


def wake_text(*, source: str, instruction: str | None, routine_name: str | None) -> str:
    """Prompt do despertar de uma rotina ou de um disparo manual. Fino de propósito:
    o resto o agente busca pelas ferramentas."""
    if source == "routine" and routine_name:
        head = f'Execução da rotina "{routine_name}".'
    elif source == "manual" and routine_name:
        head = f'Execução manual da rotina "{routine_name}".'
    elif source == "manual":
        head = "Execução pedida manualmente."
    else:
        head = "Execução agendada."
    body = (instruction or "").strip() or "Sem instrução adicional: siga o seu papel."
    return (
        f"{head}\n\n{body}\n\n"
        "Quando terminar, chame `concluir` com um resumo do que foi feito."
    )
