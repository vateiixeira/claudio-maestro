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
### Tarefas
- `tarefas_listar` e `tarefa_ler`: veja o que está com você e leia a tarefa inteira, com os \
comentários, antes de agir.
- Ao pegar uma tarefa, ponha-a em `in_progress` com `tarefa_atualizar`, trabalhe e comente o \
resultado com `tarefa_comentar`. Quando terminar, marque `done`; se houver revisor, ela vai \
para `in_review` sozinha.
- `tarefa_criar`: para delegar, crie subtarefas e atribua só a você mesmo ou a seus \
subordinados.
- `decidir`: se faltar uma decisão da pessoa, pergunte e aguarde a resposta.
- Precisa de alguém acima de você? Comente na tarefa; não mude a de quem não é seu \
subordinado.
- Perguntar ao chefe por comentário funciona: a resposta dele acorda você. Mas a troca tem \
um limite: um comentário que responde a uma resposta não acorda de volta quem a escreveu. \
Para o outro lado agir de novo, mude o status da tarefa com comentário (`tarefa_atualizar`): \
por exemplo `blocked` ou `done`, ou `in_progress` ao devolver um trabalho.
- Sem como avançar, marque `blocked` e escreva o motivo no comentário.
- Nunca feche, cancele nem reatribua tarefa de outro agente.
- `verificar_ci`: se a tarefa tem PR, confira o resultado do CI antes de marcar `done`.

### Memória
- Sua memória é o arquivo `memoria.md` da sua pasta, que já está acessível. Você mesmo a edita.
- Ela vale para as próximas execuções e entra neste prompt na seção "Memória". Anote só o que \
continua valendo: preferências, armadilhas, decisões. Reescreva consolidando, sem acumular \
histórico.
- Mantenha até 4.000 caracteres.

### Boas práticas
- Mantenha cada resposta curta e objetiva: a pessoa lê o resultado, não o caminho até ele.
- Se faltar uma decisão que só ela pode tomar, pergunte em vez de supor. Numa tarefa, \
pergunte com `decidir`; o AskUserQuestion é só para a conversa, porque numa tarefa ele \
prende a execução até o tempo acabar.
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
class TaskBrief:
    """A tarefa como o despertar a mostra. Já vem resolvida pelo serviço, inclusive os
    comentários, que são só os novos desde o cursor do despertar."""

    id: int
    title: str
    description: str
    status: str
    priority: str
    assignee: str | None
    reviewer: str | None
    creator: str | None
    parent: tuple[int, str] | None
    children: list[tuple[int, str, str]]  # (id, title, status)
    comments: list[tuple[str, str]]  # (author, text)
    worktree: str | None


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
    # Pasta e branch da worktree da tarefa, quando a sessão abre numa (em vez de na pasta do
    # projeto).
    workdir: str | None = None
    branch: str | None = None


def _person(name: str, description: str) -> str:
    return f"- {name}: {description}" if description.strip() else f"- {name}"


def _organization(context: OrgContext) -> str:
    if context.workdir:
        branch = f" (branch `{context.branch}`)" if context.branch else ""
        where = (
            f"Projeto: {context.project_name} ({context.project_path}). "
            f"Você trabalha na worktree `{context.workdir}`{branch}, uma cópia isolada do "
            "projeto só para esta tarefa. Não edite a pasta principal do projeto."
        )
    else:
        where = (
            f"Projeto: {context.project_name} ({context.project_path}). "
            "Você trabalha nessa pasta."
        )
    lines = [
        "## Organização",
        where,
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


_TASK_HEADLINES = {
    "assignment": "Você recebeu a tarefa",
    "comment": "Há comentários novos na tarefa",
    "decision": "A pessoa respondeu sua pergunta",
    "sem_relato": (
        "A execução anterior terminou sem comentário; comente o que fez"
    ),
    # Why the board woke an agent that is not simply the assignee of a new task.
    "review": "Você é o revisor da tarefa",
    "changes": "O revisor pediu mudanças na tarefa",
    "reopened": "A tarefa foi reaberta",
    "unblocked": "A pessoa desbloqueou a tarefa",
    "closed": "A tarefa que você criou foi fechada",
    "blocked": "A tarefa que você criou foi bloqueada",
}
_COMMENT_REPLY_HINT = "Um comentário seu acorda quem escreveu os comentários acima."
_COMMENT_REPLY_HINT_LAST = (
    "Este despertar já é a resposta a uma resposta: um comentário seu não acorda de volta quem "
    "escreveu os comentários acima. Para o outro lado agir, mude o status com `tarefa_atualizar`."
)
_TASK_CLOSING = "Ao terminar, atualize o status com `tarefa_atualizar` e deixe um comentário."


def task_wake_text(
    *,
    source: str,
    brief: TaskBrief,
    reason: str | None,
    decision: tuple[str, str, str] | None = None,
    echo_hop: int = 0,
) -> str:
    """Prompt do despertar de uma tarefa. O `reason` (quando há) tem precedência sobre a
    origem para escolher a frase de abertura; `decision` é (pergunta, resposta, recibo)."""
    kind = reason if reason in _TASK_HEADLINES else source
    headline = _TASK_HEADLINES.get(kind, "Execução na tarefa")
    lines = [f"{headline} #{brief.id}: {brief.title}.", ""]
    lines.append(f"Situação: `{brief.status}`. Prioridade: {brief.priority}.")
    for label, value in (
        ("Responsável", brief.assignee),
        ("Revisor", brief.reviewer),
        ("Criada por", brief.creator),
    ):
        if value:
            lines.append(f"{label}: {value}.")
    if brief.worktree:
        lines.append(f"Pasta de trabalho desta tarefa: {brief.worktree}")
    if brief.parent:
        lines.append(f"Tarefa-mãe: #{brief.parent[0]} {brief.parent[1]}.")
    lines += ["", "Descrição:", brief.description.strip() or "(sem descrição)"]
    if brief.children:
        lines += ["", "Subtarefas:"]
        lines += [f"- #{cid} {title} ({status})" for cid, title, status in brief.children]
    if brief.comments:
        lines += ["", "Comentários novos:"]
        lines += [f"- {author}: {text.strip()}" for author, text in brief.comments]
    if source == "decision" and decision is not None:
        lines += ["", *_decision_lines(*decision)]
    if kind == "comment" and brief.comments:
        lines += ["", _COMMENT_REPLY_HINT_LAST if echo_hop >= 1 else _COMMENT_REPLY_HINT]
    lines += ["", _TASK_CLOSING]
    return "\n".join(lines)


def _decision_lines(question: str, answer: str, receipt: str) -> list[str]:
    return [
        "Decisão:",
        f"Pergunta: {question}",
        f"Resposta: {answer}",
        f"Recibo: {receipt} (recibo: use-o no comentário que fecha a questão)",
    ]


def decision_message_text(question: str, answer: str, receipt: str) -> str:
    """A decision answered outside any task: it reaches the session that asked as a message."""
    return "\n".join(["A pessoa respondeu sua pergunta.", "", *_decision_lines(question, answer, receipt)])
