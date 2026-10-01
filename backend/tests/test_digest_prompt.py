"""Fixed prompt, schema and request text of the digest agent."""

import json
from pathlib import Path

from claudio_maestro.digest.prompt import (
    DIGEST_SCHEMA,
    PHASE_KINDS,
    SYSTEM_PROMPT,
    build_prompt,
    is_spec_path,
    spec_refs,
    system_prompt,
)
from claudio_maestro.digest.store import Digest
from claudio_maestro.plans import PlanProgress, PlanTask


def write_spec(root: Path, name: str, text: str) -> Path:
    folder = root / "docs" / "superpowers" / "specs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def test_system_prompt_keeps_the_rules_and_adds_extras() -> None:
    assert "status \"done\"" in SYSTEM_PROMPT and "português do Brasil" in SYSTEM_PROMPT
    assert system_prompt("") == SYSTEM_PROMPT
    extra = system_prompt("Cite a tarefa.")
    assert extra.startswith(SYSTEM_PROMPT)
    assert extra.endswith("Instruções extras do usuário:\nCite a tarefa.")


def test_schema_lists_the_phase_kinds() -> None:
    phase = DIGEST_SCHEMA["properties"]["phases"]["items"]
    assert phase["properties"]["kind"]["enum"] == list(PHASE_KINDS)
    assert set(DIGEST_SCHEMA["required"]) == {"short", "phases", "plan_completed", "plan_evidence"}


def test_spec_path_must_be_inside_a_project(tmp_path: Path) -> None:
    root = tmp_path / "app"
    spec = write_spec(root, "a.md", "# Spec A\n")
    assert is_spec_path(spec, [root]) == spec
    assert is_spec_path(spec, [tmp_path / "other"]) is None
    assert is_spec_path(root / "README.md", [root]) is None


def test_spec_refs_reads_titles_once(tmp_path: Path) -> None:
    root = tmp_path / "app"
    a = write_spec(root, "a.md", "texto\n# Spec A\n")
    b = write_spec(root, "b.md", "sem título\n")
    refs = spec_refs([str(a), str(b), str(a), str(root / "x.py")], [root])
    assert refs == [(str(a), "Spec A"), (str(b), "b")]


def test_build_prompt_sections() -> None:
    plan = PlanProgress("Plano X", (PlanTask(1, "A", True), PlanTask(2, "B", False)))
    old = Digest("s1", short="Faz X", phases=[{"title": "P", "kind": "plan", "status": "open",
                                                "done": [], "pending": [], "ref": None}])
    text = build_prompt(project="app", title="Sessão", digest=old,
                        plan=("/p/plano.md", plan), specs=[("/p/s.md", "Spec S")],
                        text="[Você] oi", restarted=False)
    assert "## Sessão\nProjeto: app\nTítulo: Sessão" in text
    assert json.dumps({"short": "Faz X", "phases": old.phases}, ensure_ascii=False) in text
    assert "Caminho: /p/plano.md\nTítulo: Plano X (1/2)\n- [x] Tarefa 1: A\n- [ ] Tarefa 2: B" in text
    assert "- /p/s.md: Spec S" in text
    assert text.endswith("## Trecho novo da conversa\n[Você] oi")
    assert "compactado" not in text


def test_build_prompt_without_summary_plan_or_specs() -> None:
    text = build_prompt(project="app", title="t", digest=None, plan=None, specs=[],
                        text="[Você] oi", restarted=True)
    assert "## Resumo atual\nSem resumo." in text
    assert "## Plano vinculado\nNenhum." in text
    assert "## Specs citados\nNenhum." in text
    assert "compactado ou reescrito" in text
