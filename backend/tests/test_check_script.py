"""scripts/check.sh runs the same checks as the CI, so local runs and the CI agree."""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"

# CI steps that prepare the runner instead of checking the code.
SETUP = ("uv sync", "pnpm --dir frontend install")


def ci_checks() -> list[str]:
    commands = re.findall(r"^\s*run:\s*(.+?)\s*$", CI.read_text(), re.M)
    assert all(c[0] not in "|>" for c in commands), (
        "ci.yml has a multi-line `run:`; teach this test to read it"
    )
    return [c for c in commands if not c.startswith(SETUP)]


def script_checks() -> list[str]:
    block = re.search(r"^checks=\((.*?)^\)", SCRIPT.read_text(), re.M | re.S)
    assert block, "scripts/check.sh has no `checks=( ... )` array"
    return re.findall(r'^\s*"([^"]+)"\s*$', block.group(1), re.M)


def test_ci_has_checks():
    assert ci_checks(), "no check command found in ci.yml"


def test_script_runs_exactly_the_ci_checks():
    assert sorted(script_checks()) == sorted(ci_checks())


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)
