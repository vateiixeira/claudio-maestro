import re

from claudio_maestro.org.definition import AgentDefinition
from claudio_maestro.org.prompt import (
    OPERATING_SKILL,
    OrgContext,
    TaskBrief,
    build_append,
    task_wake_text,
    wake_text,
)


def _definition(**overrides) -> AgentDefinition:
    base = dict(
        name="CTO",
        description="Coordena a engenharia.",
        model=None,
        effort=None,
        permission_mode="bypassPermissions",
        disallowed_tools=[],
        skills=[],
        add_dirs=[],
        worktree=False,
        max_run_minutes=120,
        body="Você é o CTO do projeto.",
    )
    base.update(overrides)
    return AgentDefinition(**base)


def _context(**overrides) -> OrgContext:
    base = dict(
        project_name="Ecommerce",
        project_path="/srv/ecommerce",
        boss=None,
        reports=[],
        add_dirs=[],
        memory_path="/data/agents/cto/memoria.md",
    )
    base.update(overrides)
    return OrgContext(**base)


def _append(**overrides) -> str:
    kwargs = dict(
        definition=_definition(),
        context=_context(),
        memory="",
        main=False,
        conversation=False,
    )
    kwargs.update(overrides)
    return build_append(**kwargs)


def test_append_has_body_before_operating_skill():
    text = _append()
    assert text.startswith("# Agente: CTO")
    assert text.index("Você é o CTO do projeto.") < text.index("## Organização")
    assert text.index("## Organização") < text.index(OPERATING_SKILL)
    assert text.index(OPERATING_SKILL) < text.index("## Memória")


def test_append_lists_boss_and_reports():
    text = _append(
        context=_context(
            boss=("Diretora", "Define as prioridades."),
            reports=[("Dev", "Implementa tarefas."), ("QA", "Testa as entregas.")],
            add_dirs=[("api", "/srv/api")],
        )
    )
    assert "Ecommerce" in text and "/srv/ecommerce" in text
    assert "Diretora: Define as prioridades." in text
    assert "Dev: Implementa tarefas." in text
    assert "QA: Testa as entregas." in text
    assert "api: /srv/api" in text


def test_append_without_boss_or_reports_says_so():
    text = _append()
    assert "Você não tem chefe" in text
    assert "Você não tem subordinados" in text


def test_append_lists_skills_only_when_present():
    assert "## Skills a usar" not in _append()
    text = _append(definition=_definition(skills=["git-workflow", "revisar-pr"]))
    assert "## Skills a usar" in text
    assert "- git-workflow" in text and "- revisar-pr" in text
    assert "ferramenta Skill" in text


def test_main_has_no_concluir_and_says_it_is_main():
    main = _append(main=True)
    assert "`concluir`" not in main
    assert "## Esta é a conversa principal" in main
    other = _append()
    assert "`concluir`" in other
    assert "## Esta é a conversa principal" not in other


def test_conversation_concluir_does_not_end_session():
    text = _append(conversation=True)
    assert "`concluir`" in text
    assert "não encerra a sessão" in text
    assert "Isso encerra esta sessão" not in text
    assert "Isso encerra esta sessão" in _append()


def test_memory_section_and_file_path():
    empty = _append()
    assert empty.rstrip().endswith("(nenhuma ainda)")
    assert "/data/agents/cto/memoria.md" in empty
    filled = _append(memory="  Sempre rodar o linter.\n")
    assert filled.rstrip().endswith("Sempre rodar o linter.")
    assert "(nenhuma ainda)" not in filled


def test_memory_path_is_optional():
    text = _append(context=OrgContext("P", "/p", None, [], []))
    assert "`memoria.md`" in text


def test_append_never_mentions_git_push_rules():
    for text in (
        _append(),
        _append(main=True),
        _append(conversation=True),
        OPERATING_SKILL,
    ):
        assert "git push" not in text
        assert "GitHub" not in text
        assert not re.search(r"\bgh\b", text)


def test_operating_skill_is_short_and_lists_base_tools():
    assert len(OPERATING_SKILL.splitlines()) <= 60
    for tool in ("registro_consultar", "registro_gravar", "avisar", "organizacao"):
        assert tool in OPERATING_SKILL


def test_operating_skill_has_tasks_section():
    assert "### Tarefas" in OPERATING_SKILL
    section = OPERATING_SKILL.split("### Tarefas", 1)[1].split("\n### ", 1)[0]
    for tool in (
        "tarefas_listar",
        "tarefa_ler",
        "tarefa_criar",
        "tarefa_atualizar",
        "tarefa_comentar",
        "decidir",
    ):
        assert f"`{tool}`" in section
    for status in ("in_progress", "blocked", "done"):
        assert f"`{status}`" in section
    assert "subordinados" in section
    assert "de outro" in section  # nunca fechar tarefa de outro
    # The section is also in the prompt of every kind of session.
    for text in (_append(), _append(main=True), _append(conversation=True)):
        assert "### Tarefas" in text


def test_append_never_mentions_claude_code_brand():
    assert "Claude Code" not in _append()


def test_wake_text_routine_includes_name_and_instruction():
    text = wake_text(
        source="routine", instruction="Veja os erros do Sentry.", routine_name="Manhã"
    )
    assert "Manhã" in text
    assert "Veja os erros do Sentry." in text
    assert "concluir" in text


def test_wake_text_manual_without_routine_name():
    text = wake_text(source="manual", instruction="Faça X.", routine_name=None)
    assert "Faça X." in text
    assert "None" not in text


def test_wake_text_without_instruction():
    text = wake_text(source="routine", instruction=None, routine_name="Manhã")
    assert "Manhã" in text
    assert "None" not in text


def _brief(**overrides) -> TaskBrief:
    base = dict(
        id=42,
        title="Corrigir o login",
        description="O login falha com e-mail em maiúsculas.\n\nReproduzir no staging.",
        status="in_progress",
        priority="high",
        assignee="Dev",
        reviewer="Revisor",
        creator="CTO",
        parent=None,
        children=[],
        comments=[],
        worktree=None,
    )
    base.update(overrides)
    return TaskBrief(**base)


def test_task_wake_text_assignment_lists_task_and_children():
    text = task_wake_text(
        source="assignment",
        brief=_brief(
            parent=(7, "Autenticação"),
            children=[(43, "Testar", "todo"), (44, "Documentar", "done")],
            worktree="/srv/ecommerce/.claude/worktrees/tarefa-42",
        ),
        reason=None,
    )
    assert "Você recebeu a tarefa" in text
    assert "#42" in text and "Corrigir o login" in text
    assert "O login falha com e-mail em maiúsculas." in text
    assert "Reproduzir no staging." in text
    assert "in_progress" in text and "high" in text
    assert "Dev" in text and "Revisor" in text and "CTO" in text
    assert "#7" in text and "Autenticação" in text
    assert "#43" in text and "Testar" in text and "todo" in text
    assert "#44" in text and "Documentar" in text and "done" in text
    assert "/srv/ecommerce/.claude/worktrees/tarefa-42" in text
    assert "None" not in text
    assert "Ao terminar, atualize o status com `tarefa_atualizar` e deixe um comentário." in text


def test_task_wake_text_without_optional_parts_has_no_none():
    text = task_wake_text(
        source="assignment",
        brief=_brief(assignee=None, reviewer=None, creator=None),
        reason=None,
    )
    assert "None" not in text
    assert "Subtarefas" not in text
    assert "Comentários novos" not in text


def test_task_wake_text_comment_only_new_comments():
    text = task_wake_text(
        source="comment",
        brief=_brief(comments=[("CTO", "Use o helper novo."), ("pessoa", "Pode seguir.")]),
        reason=None,
    )
    assert "Há comentários novos na tarefa" in text
    assert "Você recebeu a tarefa" not in text
    assert "CTO: Use o helper novo." in text
    assert "pessoa: Pode seguir." in text
    assert text.index("Corrigir o login") < text.index("Use o helper novo.")


def test_task_wake_text_sem_relato_asks_for_comment():
    text = task_wake_text(source="sem_relato", brief=_brief(), reason=None)
    assert "A execução anterior terminou sem comentário; comente o que fez" in text
    assert "Corrigir o login" in text


def test_task_wake_text_decision_shows_question_answer_and_receipt():
    text = task_wake_text(
        source="decision",
        brief=_brief(),
        reason=None,
        decision=("Apago a tabela antiga?", "Sim, apague.", "rec-abc123"),
    )
    assert "A pessoa respondeu sua pergunta" in text
    assert "Apago a tabela antiga?" in text
    assert "Sim, apague." in text
    assert "rec-abc123" in text
    assert "recibo: use-o no comentário que fecha a questão" in text


def test_task_wake_text_decision_without_decision_data_is_safe():
    text = task_wake_text(source="decision", brief=_brief(), reason=None)
    assert "A pessoa respondeu sua pergunta" in text
    assert "recibo" not in text


def test_task_wake_text_reason_overrides_source_headline():
    text = task_wake_text(source="assignment", brief=_brief(), reason="sem_relato")
    assert "A execução anterior terminou sem comentário" in text
    assert "Você recebeu a tarefa" not in text


def test_task_wake_text_unknown_source_falls_back_to_generic_headline():
    text = task_wake_text(source="manual", brief=_brief(), reason=None)
    assert "Execução na tarefa" in text
    assert "None" not in text


def test_task_wake_text_never_mentions_claude_code_brand():
    assert "Claude Code" not in task_wake_text(source="assignment", brief=_brief(), reason=None)
