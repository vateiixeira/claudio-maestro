"""Text appended to the system prompt of an agent's session."""

_HEAD = """# Agente: {name}

Você é o agente "{name}" do Cláudio Maestro. Siga a skill abaixo.

## Ferramentas do Maestro
- `registro_consultar`: antes de tratar itens (erros, issues, pedidos), consulte pelas chaves os que já foram tratados. Não refaça o que já está resolvido ou descartado, a menos que algo tenha mudado.
- `registro_gravar`: grave cada item que você tratar, com a situação, o link e uma nota curta.
- `aprendizados_reescrever`: quando aprender algo que vale para as próximas execuções, reescreva os aprendizados inteiros, consolidando. Limite de 4.000 caracteres.
- `avisar`: mande à pessoa que usa o Maestro o que ela precisa saber agora.
{concluir}
## Regras do Maestro
- Ao subir uma branch, diga sempre o nome: `git push -u origin <branch>`. Push sem o nome da branch pede ok.
- Merge, push para a branch padrão e push forçado sempre pedem ok. Não tente contornar.
- Não comente no GitHub (PR, issue, revisão). Responda na conversa principal.

## Projetos que você pode ler
"""

_CONCLUDE = (
    "- `concluir`: quando a tarefa inteira terminar, chame com um resumo do que foi feito. "
    "Isso encerra esta sessão.\n"
)

_MAIN = """## Esta é a conversa principal
Aqui você conversa com a pessoa que usa o Maestro, a qualquer hora. Não é uma execução agendada: faça o que ela pedir. O fim de um turno não encerra esta conversa. Os resultados das execuções chegam como anúncios no bloco <maestro-anuncios>.

"""

NO_EXTRA_PROJECTS = "- Só a pasta de origem."
NO_LEARNINGS = "(nenhum ainda)"


def build_append(
    *,
    name: str,
    skill_body: str,
    learnings: str,
    extra_projects: list[tuple[str, str]],
    main: bool = False,
    conversation: bool = False,
) -> str:
    """The agent's prompt: tools, readable projects, skill and learnings. Never carries
    secrets: those only reach the process environment. The main conversation has no
    `concluir` (it never ends) and says what it is."""
    projects = (
        "\n".join(f"- {project}: {path}" for project, path in extra_projects)
        if extra_projects
        else NO_EXTRA_PROJECTS
    )
    return (
        _HEAD.format(name=name, concluir="" if main else (
            _CONCLUDE.replace("Isso encerra esta sessão.",
                              "Nesta conversa, concluir registra o resultado e não encerra a sessão.")
            if conversation else _CONCLUDE
        ))
        + f"{projects}\n\n"
        + (_MAIN if main else "")
        + f"## Skill\n{skill_body.strip()}\n\n"
        + f"## Aprendizados\n{learnings.strip() or NO_LEARNINGS}"
    )
