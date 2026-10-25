from claudio_maestro.specialists.prompt import build_append

HEAD = """# Agente: Revisor

Você é o agente "Revisor" do Cláudio Maestro. Siga a skill abaixo.

## Ferramentas do Maestro
- `registro_consultar`: antes de tratar itens (erros, issues, pedidos), consulte pelas chaves os que já foram tratados. Não refaça o que já está resolvido ou descartado, a menos que algo tenha mudado.
- `registro_gravar`: grave cada item que você tratar, com a situação, o link e uma nota curta.
- `aprendizados_reescrever`: quando aprender algo que vale para as próximas execuções, reescreva os aprendizados inteiros, consolidando. Limite de 4.000 caracteres.
- `avisar`: mande à pessoa que usa o Maestro o que ela precisa saber agora.
- `concluir`: quando a tarefa inteira terminar, chame com um resumo do que foi feito. Isso encerra esta sessão.

## Regras do Maestro
- Ao subir uma branch, diga sempre o nome: `git push -u origin <branch>`. Push sem o nome da branch pede ok.
- Merge, push para a branch padrão e push forçado sempre pedem ok. Não tente contornar.
- Não comente no GitHub (PR, issue, revisão). Responda na conversa principal.

## Projetos que você pode ler
"""


def test_build_append_exact_text_with_projects_and_learnings():
    text = build_append(
        name="Revisor",
        skill_body="# Revisar\n\nLeia os PRs.\n",
        learnings="Prefira commits pequenos.",
        extra_projects=[("api", "/home/vi/api"), ("web", "/home/vi/web")],
    )

    assert text == (
        HEAD
        + "- api: /home/vi/api\n- web: /home/vi/web\n"
        + "\n## Skill\n# Revisar\n\nLeia os PRs.\n"
        + "\n## Aprendizados\nPrefira commits pequenos."
    )


def test_build_append_exact_text_without_projects_and_learnings():
    text = build_append(
        name="Revisor", skill_body="Faça X.", learnings="", extra_projects=[]
    )

    assert text == (
        HEAD
        + "- Só a pasta de origem.\n"
        + "\n## Skill\nFaça X.\n"
        + "\n## Aprendizados\n(nenhum ainda)"
    )


def test_build_append_treats_blank_learnings_as_none():
    text = build_append(name="A", skill_body="x", learnings="  \n ", extra_projects=[])

    assert text.endswith("## Aprendizados\n(nenhum ainda)")


def test_build_append_trims_blank_edges_of_skill_and_learnings():
    text = build_append(
        name="A", skill_body="\n\n# Skill\n\ncorpo\n\n", learnings="\nnota\n\n", extra_projects=[]
    )

    assert "\n## Skill\n# Skill\n\ncorpo\n\n## Aprendizados\nnota" in text
    assert text.endswith("nota")


NO_GITHUB = "- Não comente no GitHub (PR, issue, revisão). Responda na conversa principal.\n"
MAIN_SECTION = (
    "## Esta é a conversa principal\n"
    "Aqui você conversa com a pessoa que usa o Maestro, a qualquer hora. Não é uma execução "
    "agendada: faça o que ela pedir. O fim de um turno não encerra esta conversa. Os resultados das execuções chegam como anúncios no "
    "bloco <maestro-anuncios>.\n\n"
)


def test_build_append_has_the_github_rule_in_both_modes():
    for main in (False, True):
        text = build_append(
            name="Revisor", skill_body="Faça X.", learnings="", extra_projects=[], main=main
        )
        assert NO_GITHUB in text
        assert text.index("## Regras do Maestro") < text.index(NO_GITHUB) < text.index(
            "## Projetos que você pode ler"
        )


def test_build_append_main_has_no_concluir_and_has_the_main_section():
    text = build_append(
        name="Revisor", skill_body="Faça X.", learnings="", extra_projects=[], main=True
    )

    assert "concluir" not in text
    assert MAIN_SECTION + "## Skill\nFaça X." in text
    assert "- `avisar`: mande à pessoa que usa o Maestro o que ela precisa saber agora.\n\n" in text


def test_build_append_isolated_has_concluir_and_no_main_section():
    text = build_append(name="Revisor", skill_body="Faça X.", learnings="", extra_projects=[])

    assert "- `concluir`: quando a tarefa inteira terminar" in text
    assert "conversa principal\nAqui" not in text
