"""Merge of the agent's answer with the stored digest."""

from pathlib import Path

import pytest

from claudio_maestro.digest.merge import DigestFormatError, clean_phase, merge_digest
from claudio_maestro.digest.store import Digest
from claudio_maestro.plans import PlanProgress, PlanTask


def phase(title: str, status: str = "done", kind: str = "feature", **extra) -> dict:
    return {"title": title, "kind": kind, "status": status, "done": [], "pending": [],
            "ref": None, **extra}


def answer(*phases, short: str = "Faz Y", completed: bool = False, evidence=None) -> dict:
    return {"short": short, "phases": list(phases), "plan_completed": completed,
            "plan_evidence": evidence}


def merge(old, result, *, plan_path=None, plan=None, roots=None) -> Digest:
    return merge_digest(old, result, session_id="s1", cursor="u9", read_at=500,
                        plan_path=plan_path, plan=plan, roots=roots or [])


def test_first_reading() -> None:
    got = merge(None, answer(phase("Plano X", "open", "plan")))
    assert got.session_id == "s1" and got.cursor == "u9" and got.read_at == 500
    assert got.short == "Faz Y" and [p["title"] for p in got.phases] == ["Plano X"]
    assert got.error is None and got.plan_done is False


def test_done_phases_are_frozen() -> None:
    frozen = phase("Plano X", done=["Tarefa 1"])
    old = Digest("s1", phases=[frozen, phase("Ajustes", "open")])
    got = merge(old, answer(phase("Plano X", done=["reescrito"]), phase("Ajustes", "done"),
                            phase("Feature Y", "open")))
    assert got.phases[0] == frozen
    assert [p["title"] for p in got.phases] == ["Plano X", "Ajustes", "Feature Y"]
    assert [p["status"] for p in got.phases] == ["done", "done", "open"]


def test_omitted_frozen_phases_come_back() -> None:
    frozen = phase("Plano X")
    got = merge(Digest("s1", phases=[frozen]), answer(phase("Feature Y", "open")))
    assert [p["title"] for p in got.phases] == ["Plano X", "Feature Y"]


def test_only_the_last_phase_stays_open() -> None:
    got = merge(None, answer(phase("A", "open"), phase("B", "open")))
    assert [p["status"] for p in got.phases] == ["done", "open"]


def test_limits_are_applied_by_cutting() -> None:
    long = phase("T" * 300, "open", done=["d" * 300] * 20, pending=[" ", "p"])
    got = merge(None, answer(long, short="s" * 300))
    p = got.phases[0]
    assert len(p["title"]) == 120 and p["title"].endswith("…")
    assert len(p["done"]) == 12 and len(p["done"][0]) == 200
    assert p["pending"] == ["p"]
    assert len(got.short) == 140 and got.short.endswith("…")


def test_text_at_the_limit_is_kept_whole() -> None:
    got = merge(None, answer(phase("T" * 120, "open"), short="s" * 140))
    assert got.phases[0]["title"] == "T" * 120 and got.short == "s" * 140


def test_too_many_phases_fold_the_oldest() -> None:
    phases = [phase(f"F{i}") for i in range(25)] + [phase("Agora", "open")]
    got = merge(None, answer(*phases))
    assert len(got.phases) == 20
    assert got.phases[0]["title"] == "Fases anteriores" and got.phases[0]["kind"] == "other"
    assert got.phases[0]["done"][:2] == ["F0", "F1"]
    assert got.phases[-1]["title"] == "Agora"


def test_clean_phase_fixes_kind_status_and_drops_bad_items(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    inside = root / "plan.md"
    got = clean_phase({"title": " X ", "kind": "weird", "status": "maybe", "done": [1, "a"],
                       "pending": "no", "ref": str(inside)}, [root])
    assert got == {"title": "X", "kind": "other", "status": "open", "done": ["a"],
                   "pending": [], "ref": str(inside.resolve())}
    assert clean_phase({"title": "  "}, [root]) is None
    assert clean_phase("x", [root]) is None
    assert clean_phase({"title": "Y", "ref": "/etc/passwd"}, [root])["ref"] is None
    assert clean_phase({"title": "Y", "ref": "relativo.md"}, [root])["ref"] is None


def test_answer_without_phases_is_a_format_error() -> None:
    with pytest.raises(DigestFormatError):
        merge(None, {"short": "x"})
    with pytest.raises(DigestFormatError):
        merge(None, ["x"])


def test_empty_short_keeps_the_old_one() -> None:
    got = merge(Digest("s1", short="Antes"), answer(phase("A", "open"), short="  "))
    assert got.short == "Antes"


def test_plan_seal_from_the_file() -> None:
    done = PlanProgress("P", (PlanTask(1, "A", True),))
    got = merge(None, answer(phase("A", "open")), plan_path="/p.md", plan=done)
    assert got.plan_done is True and got.plan_ref == "/p.md"


def test_plan_seal_from_evidence_only_with_text() -> None:
    open_plan = PlanProgress("P", (PlanTask(1, "A", False),))
    assert merge(None, answer(completed=True, evidence="Revisão final aprovada."),
                 plan_path="/p.md", plan=open_plan).plan_done is True
    assert merge(None, answer(completed=True, evidence=" "), plan_path="/p.md",
                 plan=open_plan).plan_done is False


def test_plan_seal_stays_until_the_plan_changes() -> None:
    old = Digest("s1", plan_done=True, plan_ref="/p.md")
    assert merge(old, answer(), plan_path="/p.md").plan_done is True
    assert merge(old, answer(), plan_path="/outro.md").plan_done is False


def test_new_phase_repeating_a_frozen_title_is_kept() -> None:
    old = Digest("s1", phases=[phase("Executar plano X"), phase("Ajustes e melhorias"),
                               phase("Feature Y")])
    got = merge(old, answer(phase("Executar plano X"), phase("Ajustes e melhorias"),
                            phase("Feature Y"), phase("Ajustes e melhorias", "open")))
    assert [p["title"] for p in got.phases] == [
        "Executar plano X", "Ajustes e melhorias", "Feature Y", "Ajustes e melhorias"]
    assert [p["status"] for p in got.phases] == ["done", "done", "done", "open"]


def test_repeated_frozen_phase_in_the_answer_collapses_once_per_frozen() -> None:
    old = Digest("s1", phases=[phase("Plano X")])
    got = merge(old, answer(phase(" plano x "), phase("Feature Y", "open")))
    assert [p["title"] for p in got.phases] == ["Plano X", "Feature Y"]


def test_folding_again_merges_the_previous_folded_items() -> None:
    folded = phase("Fases anteriores", kind="other", done=["A", "B"])
    old = Digest("s1", phases=[folded] + [phase(f"F{i}") for i in range(19)])
    got = merge(old, answer(phase("Agora", "open")))
    assert len(got.phases) == 20
    first = got.phases[0]
    assert first["title"] == "Fases anteriores"
    assert first["done"] == ["A", "B", "F0"]
    assert "Fases anteriores" not in first["done"]


def test_folding_keeps_the_newest_items_when_over_the_cap() -> None:
    folded = phase("Fases anteriores", kind="other", done=[f"old{i}" for i in range(12)])
    old = Digest("s1", phases=[folded] + [phase(f"F{i}") for i in range(19)])
    got = merge(old, answer(phase("Agora", "open")))
    assert len(got.phases[0]["done"]) == 12
    assert got.phases[0]["done"][-1] == "F0" and got.phases[0]["done"][0] == "old1"
