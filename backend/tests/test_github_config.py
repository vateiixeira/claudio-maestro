"""The release workflow and Dependabot follow the develop -> main flow."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GITHUB = ROOT / ".github"
RELEASE = GITHUB / "workflows" / "release.yml"
CI = GITHUB / "workflows" / "ci.yml"
DEPENDABOT = GITHUB / "dependabot.yml"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def on_of(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def wf() -> dict:
    return load(RELEASE)


def job() -> dict:
    return wf()["jobs"]["release"]


def steps() -> list[dict]:
    return job()["steps"]


def all_runs() -> str:
    return "\n".join(step.get("run", "") for step in steps())


def checkout_step() -> dict:
    return next(s for s in steps() if s.get("uses", "").startswith("actions/checkout@"))


def step_index(fragment: str) -> int:
    return next(i for i, s in enumerate(steps()) if fragment in s.get("run", ""))


def test_release_runs_after_ci_on_main_only():
    assert on_of(wf()) == {
        "workflow_run": {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]}
    }


def test_release_requires_successful_push_run():
    cond = job()["if"]
    assert "conclusion == 'success'" in cond and "event == 'push'" in cond


def test_release_permissions_are_minimal():
    assert wf()["permissions"] == {} and job()["permissions"] == {"contents": "write"}


def test_release_checks_out_the_tested_commit():
    assert checkout_step()["with"]["ref"] == "${{ github.event.workflow_run.head_sha }}"


def test_release_skips_when_tag_exists():
    check = step_index("git ls-remote --tags")
    tag = step_index("git tag -a")
    release = step_index("gh release create")
    assert check < tag < release
    check_id = steps()[check]["id"]
    assert f"steps.{check_id}.outputs.skip" in steps()[tag]["if"]
    assert f"steps.{check_id}.outputs.skip" in steps()[release]["if"]
    assert f"steps.{check_id}.outputs.skip" in steps()[step_index("scripts/release.py notes")]["if"]


def test_release_uses_changelog_notes_and_verify_tag():
    runs = all_runs()
    assert "scripts/release.py notes" in runs
    assert "gh release create" in runs and "--verify-tag" in runs
    assert "Cláudio Maestro" in runs


def test_release_does_not_interpolate_event_data_in_run():
    for step in steps():
        assert "${{ github.event" not in step.get("run", "")


def test_ci_push_trigger_stays_main_only():
    assert on_of(load(CI))["push"] == {"branches": ["main"]}


def test_dependabot_targets_develop():
    updates = load(DEPENDABOT)["updates"]
    assert updates and all(u.get("target-branch") == "develop" for u in updates)
