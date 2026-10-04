"""Rules of the closure check: verdict, item cleaning, fingerprint and eligibility."""

import pytest
from digest_fakes import NOW

from claudio_maestro.digest.closure import (
    ClosureFormatError,
    GitFacts,
    apply_answer,
    cheap_key,
    closure_candidate,
    closure_eligible,
    decide,
    fingerprint,
    normalize,
)
from claudio_maestro.digest.config import DigestConfig
from claudio_maestro.gitinfo import RepoStatus

CFG = DigestConfig(enabled=True)


def answer(verdict="can_close", user_actions=(), missing=(), evidence="ok") -> dict:
    return {"verdict": verdict, "user_actions": list(user_actions),
            "missing": list(missing), "evidence": evidence}


def test_decide_follows_the_lists() -> None:
    assert decide([], [], "can_close") == "can_close"
    assert decide(["Reiniciar"], [], "can_close") == "user_action"
    assert decide(["Reiniciar"], ["Tarefa 5"], "user_action") == "incomplete"
    assert decide([], ["Tarefa 5"], "can_close") == "incomplete"
    assert decide([], [], "user_action") == "can_close"
    assert decide(["x"], ["y"], "in_progress") == "in_progress"


def test_apply_answer_cleans_and_filters_resolved() -> None:
    raw = answer("user_action", ["  Reiniciar   os SERVIÇOS ", "Aprovar o preview", ""],
                 [], "  falta reiniciar ")
    verdict, actions, missing, evidence = apply_answer(raw, ["reiniciar os serviços"])
    assert actions == ["Aprovar o preview"]
    assert (verdict, missing, evidence) == ("user_action", [], "falta reiniciar")


def test_resolving_every_action_closes() -> None:
    verdict, actions, _, _ = apply_answer(answer("user_action", ["Reiniciar"]), ["reiniciar"])
    assert (verdict, actions) == ("can_close", [])


def test_items_are_clipped_and_capped() -> None:
    raw = answer("incomplete", [], ["x" * 300] + [f"item {i}" for i in range(20)])
    _, _, missing, _ = apply_answer(raw, [])
    assert len(missing) == 8
    assert len(missing[0]) == 200 and missing[0].endswith("…")


@pytest.mark.parametrize("raw", [None, [], {"verdict": "talvez"}, {"user_actions": []}])
def test_bad_answer(raw) -> None:
    with pytest.raises(ClosureFormatError):
        apply_answer(raw, [])


def test_normalize() -> None:
    assert normalize("  Rodar   a MIGRAÇÃO ") == "rodar a migração"


def test_git_facts_from_status() -> None:
    status = RepoStatus(path="/r", rel_path=".", branch="feat/x",
                        changed={"staged": 1, "unstaged": 2, "untracked": 3},
                        upstream="origin/feat/x", ahead=4)
    facts = GitFacts.from_status(status)
    assert (facts.branch, facts.staged, facts.unstaged, facts.untracked, facts.ahead) == (
        "feat/x", 1, 2, 3, 4)
    assert GitFacts.from_status(RepoStatus(path="/r", rel_path=".", error="não é git")).error


def test_fingerprint_changes_with_each_input() -> None:
    base = cheap_key(file_mtime=1.0, plan=None, resolved=[])
    assert base != cheap_key(file_mtime=2.0, plan=None, resolved=[])
    assert base != cheap_key(file_mtime=1.0, plan=None, resolved=["a"])
    git = GitFacts("main", False, 0, 0, 0, 0, "origin/main", None)
    dirty = GitFacts("main", False, 0, 1, 0, 0, "origin/main", None)
    assert fingerprint(base, git) != fingerprint(base, dirty)
    assert fingerprint(base, git) == fingerprint(base, git)


def session(**fields) -> dict:
    base = {"display_state": "waiting", "state": "idle", "cli_running": False,
            "subagents_running": False, "finished": False,
            "last_activity_at": int(NOW - 600)}
    base.update(fields)
    return base


def test_eligibility() -> None:
    quiet = NOW - 200
    assert closure_eligible(session(), quiet, CFG, NOW, automatic=True)
    assert closure_eligible(session(state="closed"), quiet, CFG, NOW, automatic=True)
    for changes in ({"state": "running"}, {"state": "connecting"},
                    {"state": "awaiting_decision"}, {"state": "error"},
                    {"cli_running": True}, {"subagents_running": True},
                    {"display_state": "finished"}, {"display_state": "running"},
                    {"last_activity_at": int(NOW - 4 * 86400)}):
        assert not closure_eligible(session(**changes), quiet, CFG, NOW, automatic=True), changes
    assert not closure_eligible(session(), NOW - 60, CFG, NOW, automatic=True)  # not quiet
    assert not closure_eligible(session(), None, CFG, NOW, automatic=True)  # no file
    off = DigestConfig(enabled=True, closure_auto=False)
    assert not closure_eligible(session(), quiet, off, NOW, automatic=True)
    assert not closure_eligible(session(), quiet, DigestConfig(), NOW, automatic=True)
    # Manual: ignores the switches and the quiet time, never an open turn.
    assert closure_eligible(session(), NOW - 1, off, NOW, automatic=False)
    assert not closure_eligible(session(state="running"), NOW - 1, off, NOW, automatic=False)


def test_git_head_is_part_of_the_fingerprint() -> None:
    def facts(head: str) -> GitFacts:
        return GitFacts.from_status(RepoStatus(path="/r", rel_path=".", branch="main", head=head,
                                               upstream="origin/main", ahead=0))

    assert facts("abc").head == "abc"
    base = cheap_key(file_mtime=1.0, plan=None, resolved=[])
    assert fingerprint(base, facts("abc")) != fingerprint(base, facts("def"))
    assert fingerprint(base, facts("abc")) == fingerprint(base, facts("abc"))


def test_candidate_needs_no_file() -> None:
    off = DigestConfig(enabled=True, closure_auto=False)
    assert closure_candidate(session(), CFG, NOW, automatic=True)
    assert not closure_candidate(session(state="running"), CFG, NOW, automatic=True)
    assert not closure_candidate(session(finished=True), CFG, NOW, automatic=True)
    assert not closure_candidate(session(last_activity_at=int(NOW - 4 * 86400)), CFG, NOW,
                                 automatic=True)
    assert not closure_candidate(session(), off, NOW, automatic=True)
    assert closure_candidate(session(), off, NOW, automatic=False)
