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
