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


def test_release_decides_on_tag_and_release_separately():
    check = steps()[step_index("git ls-remote --tags")]
    assert check["id"] == "state"
    run = check["run"]
    assert "gh release view" in run
    assert "tag_exists=" in run and "release_exists=" in run
    assert check["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_release_creates_only_what_is_missing():
    state = steps()[step_index("git ls-remote --tags")]["id"]
    tag_flag = f"steps.{state}.outputs.tag_exists"
    release_flag = f"steps.{state}.outputs.release_exists"
    notes = steps()[step_index("scripts/release.py notes")]
    tag = steps()[step_index("git tag -a")]
    release = steps()[step_index("gh release create")]
    assert step_index("git ls-remote --tags") < step_index("git tag -a")
    assert step_index("git tag -a") < step_index("gh release create")
    assert f"{release_flag} == 'false'" in notes["if"]
    assert f"{release_flag} == 'false'" in release["if"]
    assert f"{tag_flag} == 'false'" in tag["if"]
    assert release_flag not in tag["if"] and tag_flag not in release["if"]


def test_release_serializes_runs():
    assert wf()["concurrency"] == {"group": "release", "cancel-in-progress": False}


def test_ci_workflow_is_named_ci():
    # release.yml listens for `workflow_run` of the workflow called "CI".
    assert load(CI)["name"] == "CI"


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
