"""Index and working-tree diffs keep their independent contents."""

from pathlib import Path

import pytest
from git_helpers import git, make_repo
from test_git_api import add_project, api, build, factory, spawn  # noqa: F401

from claudio_maestro import gitinfo


@pytest.mark.anyio
async def test_partially_staged_file_has_two_different_diffs(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    path = repo / "README.md"
    path.write_text("preparado\nlinha 2\n")
    git(repo, "add", "README.md")
    path.write_text("preparado\ntrabalho\n")
    staged = await gitinfo.file_diff(repo, "README.md", scope="staged")
    working = await gitinfo.file_diff(repo, "README.md", scope="unstaged")
    combined = await gitinfo.file_diff(repo, "README.md")
    assert "+preparado" in staged.diff and "+trabalho" not in staged.diff
    assert "+trabalho" in working.diff and "+preparado" not in working.diff
    assert "+preparado" in combined.diff and "+trabalho" in combined.diff


@pytest.mark.anyio
async def test_unborn_staged_file_uses_index_not_working_contents(tmp_path: Path):
    repo = make_repo(tmp_path / "r", commit=False)
    (repo / "novo").write_text("preparado\n")
    git(repo, "add", "novo")
    (repo / "novo").write_text("trabalho\n")
    assert "+preparado" in (await gitinfo.file_diff(repo, "novo", scope="staged")).diff
    working = (await gitinfo.file_diff(repo, "novo", scope="unstaged")).diff
    assert "-preparado" in working and "+trabalho" in working


@pytest.mark.anyio
@pytest.mark.parametrize("committed", [True, False])
async def test_untracked_only_appears_in_working_scope(tmp_path: Path, committed: bool):
    repo = make_repo(tmp_path / "r", commit=committed)
    (repo / "solto").write_text("novo\n")
    assert "+novo" in (await gitinfo.file_diff(repo, "solto", scope="unstaged")).diff
    assert (await gitinfo.file_diff(repo, "solto", scope="staged")).diff == ""


@pytest.mark.anyio
async def test_staged_deletion_stays_visible_if_file_recreated(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "rm", "README.md")
    (repo / "README.md").write_text("recriado\n")
    staged = (await gitinfo.file_diff(repo, "README.md", scope="staged")).diff
    assert "deleted file mode" in staged and "+recriado" not in staged
    assert "+recriado" in (await gitinfo.file_diff(repo, "README.md", scope="unstaged")).diff


@pytest.mark.anyio
async def test_staged_rename_does_not_include_later_edit(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "mv", "README.md", "LEIAME.md")
    (repo / "LEIAME.md").write_text("depois\n")
    staged = (await gitinfo.file_diff(repo, "LEIAME.md", scope="staged")).diff
    assert "rename from README.md" in staged and "rename to LEIAME.md" in staged
    assert "new file mode" not in staged
    assert "+depois" not in staged
    assert "+depois" in (await gitinfo.file_diff(repo, "LEIAME.md", scope="unstaged")).diff


@pytest.mark.anyio
async def test_pure_staged_rename_has_no_added_lines(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "mv", "README.md", "LEIAME.md")
    result = await gitinfo.file_diff(repo, "LEIAME.md", scope="staged")
    assert "rename from README.md" in result.diff
    assert "rename to LEIAME.md" in result.diff
    assert "+linha" not in result.diff


@pytest.mark.anyio
async def test_binary_and_unstaged_deletion(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "bin").write_bytes(b"\x00old")
    git(repo, "add", "bin")
    git(repo, "commit", "-qm", "binary")
    (repo / "bin").write_bytes(b"\x00new")
    git(repo, "add", "bin")
    assert "Binary files" in (await gitinfo.file_diff(repo, "bin", scope="staged")).diff
    (repo / "README.md").unlink()
    assert "deleted file mode" in (await gitinfo.file_diff(repo, "README.md", scope="unstaged")).diff


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["staged", "unstaged"])
async def test_scope_keeps_output_bound_and_literal_pathspec(tmp_path: Path, monkeypatch, scope):
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").write_text("mudança\n" * 100)
    if scope == "staged":
        git(repo, "add", "README.md")
    # Git's pathspec magic must not turn one filename into a request for all files.
    assert (await gitinfo.file_diff(repo, ":(glob)*", scope=scope)).diff == ""
    monkeypatch.setattr(gitinfo, "DIFF_LIMIT", 100)
    result = await gitinfo.file_diff(repo, "README.md", scope=scope)
    assert result.truncated and len(result.diff) == 100


def test_diff_api_validates_scope_and_keeps_path_boundary(api, home):
    repo = make_repo(home / "project")
    project = add_project(api, repo)
    url = f"/api/projects/{project['id']}/diff"
    assert api.get(url, params={"repo": ".", "file": "README.md", "scope": "--output=/tmp/x"}).status_code == 422
    for scope in ("staged", "unstaged", "combined"):
        assert api.get(url, params={"repo": ".", "file": "../outside", "scope": scope}).status_code == 403
    (repo / "README.md").write_text("index\n")
    git(repo, "add", "README.md")
    (repo / "README.md").write_text("working\n")
    response = api.get(url, params={"repo": ".", "file": "README.md", "scope": "staged"})
    assert response.status_code == 200
    assert "+index" in response.json()["diff"] and "+working" not in response.json()["diff"]
