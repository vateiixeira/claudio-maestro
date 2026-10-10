"""The agents in .claude/agents/ keep the contract the project rules rely on."""

import re
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[2] / ".claude" / "agents"
SERVICE_PORTS = ("6660", "6600", "6610")


def read_agent(name: str) -> tuple[dict[str, str], str]:
    text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    assert match, f"{name}.md has no frontmatter"
    meta = dict(re.findall(r'^(\w+):\s*"?(.*?)"?\s*$', match.group(1), re.M))
    return meta, match.group(2)


@pytest.mark.parametrize("name", ["implementer", "reviewer", "milestone-reviewer", "e2e-tester"])
def test_agent_has_name_and_description(name):
    meta, _ = read_agent(name)
    assert meta["name"] == name
    assert meta["description"]


def test_e2e_tester_runs_in_sonnet_and_cannot_edit_notebooks():
    meta, _ = read_agent("e2e-tester")
    assert meta["model"] == "sonnet"
    assert "NotebookEdit" in meta["disallowedTools"]


def test_e2e_tester_stays_off_the_service_ports():
    _, body = read_agent("e2e-tester")
    for port in SERVICE_PORTS:
        assert port in body, f"the prompt must forbid port {port}"


def test_e2e_tester_does_not_commit_and_leaves_src_alone():
    _, body = read_agent("e2e-tester")
    assert "commit" in body.lower()
    assert "frontend/src" in body
    assert "frontend/e2e" in body
    assert "pnpm --dir frontend e2e" in body
    assert "APROVADO" in body and "REPROVADO" in body
