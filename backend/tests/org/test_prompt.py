import re

from claudio_maestro.org.definition import AgentDefinition
from claudio_maestro.org.prompt import (
    OPERATING_SKILL,
    OrgContext,
    build_append,
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


def test_operating_skill_is_short_and_has_no_task_tools():
    assert len(OPERATING_SKILL.splitlines()) <= 60
    for tool in ("registro_consultar", "registro_gravar", "avisar", "organizacao"):
        assert tool in OPERATING_SKILL
    for tool in ("tarefa_criar", "tarefas_listar", "tarefa_comentar", "decidir"):
        assert tool not in OPERATING_SKILL


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
