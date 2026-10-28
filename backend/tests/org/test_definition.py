import pytest

from claudio_maestro.org.definition import (
    DEFAULT_MAX_RUN_MINUTES,
    DEFAULT_PERMISSION_MODE,
    DEFINITION_MAX_BYTES,
    AgentDefinition,
    DefinitionError,
    definition_hash,
    parse_definition,
    render_definition,
    template,
)

FULL = """---
name: CTO
description: Coordena o trabalho de engenharia.
model: opus
effort: high
permissionMode: acceptEdits
disallowedTools: ["Bash(git push --force*)", "WebFetch"]
skills: [git-workflow, revisar-pr]
addDirs: [/srv/outro, ../irmao]
worktree: true
maxRunMinutes: 45
---
Você é o CTO do projeto.

Segunda linha.
"""


def _error(text: str) -> DefinitionError:
    with pytest.raises(DefinitionError) as info:
        parse_definition(text)
    return info.value


def test_parse_minimal_fills_defaults():
    d = parse_definition("---\nname: X\n---\nFaça o trabalho.\n")
    assert d.name == "X"
    assert d.body == "Faça o trabalho."
    assert d.description == ""
    assert d.model is None
    assert d.effort is None
    assert d.permission_mode == DEFAULT_PERMISSION_MODE == "bypassPermissions"
    assert d.max_run_minutes == DEFAULT_MAX_RUN_MINUTES == 120
    assert d.disallowed_tools == []
    assert d.skills == []
    assert d.add_dirs == []
    assert d.worktree is False


def test_parse_all_fields():
    d = parse_definition(FULL)
    assert d == AgentDefinition(
        name="CTO",
        description="Coordena o trabalho de engenharia.",
        model="opus",
        effort="high",
        permission_mode="acceptEdits",
        disallowed_tools=["Bash(git push --force*)", "WebFetch"],
        skills=["git-workflow", "revisar-pr"],
        add_dirs=["/srv/outro", "../irmao"],
        worktree=True,
        max_run_minutes=45,
        body="Você é o CTO do projeto.\n\nSegunda linha.",
    )


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_parse_accepts_every_effort(effort):
    d = parse_definition(f"---\nname: X\neffort: {effort}\n---\nCorpo\n")
    assert d.effort == effort


def test_parse_accepts_crlf_and_bom():
    d = parse_definition("﻿---\r\nname: X\r\n---\r\nCorpo\r\n")
    assert d.name == "X"
    assert d.body == "Corpo"


def test_parse_rejects_missing_name():
    error = _error("---\ndescription: sem nome\n---\nCorpo\n")
    assert error.field == "name"
    assert "name" in error.message


def test_parse_rejects_blank_name():
    assert _error("---\nname: '  '\n---\nCorpo\n").field == "name"


def test_parse_rejects_unknown_field():
    error = _error("---\nname: X\nautonomy: high\n---\nCorpo\n")
    assert error.field == "autonomy"
    assert error.line == 3
    assert "autonomy" in error.message


def test_parse_rejects_bad_permission_mode():
    error = _error("---\nname: X\npermissionMode: tudo\n---\nCorpo\n")
    assert error.field == "permissionMode"
    assert error.line == 3
    assert "bypassPermissions" in error.message


def test_parse_rejects_bad_effort():
    error = _error("---\nname: X\neffort: enorme\n---\nCorpo\n")
    assert error.field == "effort"
    assert "xhigh" in error.message


def test_parse_rejects_non_list_disallowed_tools():
    error = _error("---\nname: X\ndisallowedTools: WebFetch\n---\nCorpo\n")
    assert error.field == "disallowedTools"
    assert error.line == 3


@pytest.mark.parametrize("field", ["skills", "addDirs"])
def test_parse_rejects_list_with_non_strings(field):
    assert _error(f"---\nname: X\n{field}: [1, 2]\n---\nCorpo\n").field == field


@pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5", "true"])
def test_parse_rejects_bad_max_run_minutes(value):
    error = _error(f"---\nname: X\nmaxRunMinutes: {value}\n---\nCorpo\n")
    assert error.field == "maxRunMinutes"


def test_parse_rejects_non_boolean_worktree():
    assert _error("---\nname: X\nworktree: talvez\n---\nCorpo\n").field == "worktree"


def test_parse_rejects_missing_frontmatter():
    error = _error("name: X\n\nCorpo\n")
    assert "---" in error.message
    assert error.field is None


def test_parse_rejects_unclosed_frontmatter():
    error = _error("---\nname: X\nCorpo sem fechar\n")
    assert "---" in error.message


def test_parse_rejects_empty_body():
    error = _error("---\nname: X\n---\n   \n")
    assert error.field == "body"


def test_parse_rejects_invalid_yaml_with_line():
    error = _error("---\nname: X\nmodel: [aberto\n---\nCorpo\n")
    assert error.line is not None and error.line >= 3
    assert error.field is None


def test_parse_rejects_non_mapping_frontmatter():
    assert _error("---\n- a\n- b\n---\nCorpo\n").field is None


def test_parse_rejects_oversize():
    text = "---\nname: X\n---\n" + "a" * (DEFINITION_MAX_BYTES + 1)
    error = _error(text)
    assert "100" in error.message


def test_parse_oversize_counts_bytes_not_characters():
    text = "---\nname: X\n---\n" + "ã" * (DEFINITION_MAX_BYTES // 2 + 1)
    assert len(text) < DEFINITION_MAX_BYTES
    _error(text)


def test_render_roundtrip_full_and_minimal():
    full = parse_definition(FULL)
    assert parse_definition(render_definition(full)) == full
    minimal = parse_definition("---\nname: X\n---\nCorpo\n")
    assert parse_definition(render_definition(minimal)) == minimal


def test_render_omits_defaults():
    minimal = parse_definition("---\nname: X\n---\nCorpo\n")
    assert render_definition(minimal) == "---\nname: X\n---\nCorpo\n"


def test_render_roundtrip_awkward_values():
    d = AgentDefinition(
        name="Sim: 'não' # x",
        description="Linha 1\nLinha 2: com dois-pontos",
        model=None,
        effort=None,
        permission_mode="default",
        disallowed_tools=["Bash(rm -rf *)"],
        skills=[],
        add_dirs=["/tmp/a b"],
        worktree=False,
        max_run_minutes=1,
        body="---\ncorpo com separador\n---\nfim",
    )
    assert parse_definition(render_definition(d)) == d


def test_definition_hash_is_stable_sha256_hex():
    h = definition_hash("abc")
    assert h == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert definition_hash("abc") == h
    assert definition_hash("abd") != h


def test_template_cto_parses():
    d = parse_definition(template("CTO", "cto"))
    assert d.name == "CTO"
    assert "tarefas" in d.body
    assert "`tarefa_criar`" in d.body


def test_template_worker_parses():
    d = parse_definition(template("Dev Backend", "worker"))
    assert d.name == "Dev Backend"
    assert "comenta" in d.body
    assert "`tarefa_comentar`" in d.body
    assert "`tarefa_atualizar`" in d.body


def test_template_reviewer_parses():
    d = parse_definition(template("Revisor", "reviewer"))
    assert d.name == "Revisor"
    assert d.description
    assert "in_review" in d.body
    assert "done" in d.body and "in_progress" in d.body
    assert "`tarefa_atualizar`" in d.body
    assert "\n\n" not in d.body  # um parágrafo


def test_template_rejects_unknown_kind():
    with pytest.raises(KeyError):
        template("X", "chefe")  # type: ignore[arg-type]


def test_template_name_with_yaml_specials_roundtrips():
    assert parse_definition(template("Time: A #1", "worker")).name == "Time: A #1"
