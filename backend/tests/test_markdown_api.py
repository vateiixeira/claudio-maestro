"""Read-only markdown files for the reader page."""

import os
from pathlib import Path

from git_helpers import git, make_repo
from test_git_api import add_project, api, factory, spawn  # noqa: F401 (fixtures)


def session(api, folder: Path) -> tuple[str, dict]:  # noqa: F811
    project = add_project(api, folder)
    sid = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]
    return sid, project


def read(api, sid: str, path: str, **kwargs):  # noqa: F811
    return api.get(f"/api/sessions/{sid}/markdown", params={"path": path}, **kwargs)


def test_reads_a_relative_path_from_the_session_folder(api, home):  # noqa: F811
    root = home / "proj"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "plano.md").write_text("# Plano\n\n- [ ] um\n")
    sid, _ = session(api, root)
    response = read(api, sid, "docs/plano.md")
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str((root / "docs" / "plano.md").resolve())
    assert body["content"] == "# Plano\n\n- [ ] um\n"
    assert body["mtime"] == os.stat(root / "docs" / "plano.md").st_mtime


def test_reads_an_absolute_path_and_any_case_of_the_extension(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (root / "README.MD").write_text("oi")
    sid, _ = session(api, root)
    assert read(api, sid, str(root / "README.MD")).json()["content"] == "oi"


def test_reads_a_utf8_name_with_spaces(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (root / "plano ação.md").write_text("ok")
    sid, _ = session(api, root)
    assert read(api, sid, "plano ação.md").json()["content"] == "ok"


def test_relative_to_the_worktree_then_to_the_original_folder(api, home):  # noqa: F811
    root = make_repo(home / "proj")
    wt = root / ".claude" / "worktrees" / "x"
    git(root, "worktree", "add", "-q", "-b", "feat", str(wt))
    (wt / "so-na-worktree.md").write_text("wt")
    (root / "so-no-principal.md").write_text("principal")
    sid, _ = session(api, root)
    record = api.app.state.sessions.get(sid).record
    record.worktree_path = str(wt)
    record.history_dir = str(wt)
    assert read(api, sid, "so-na-worktree.md").json()["content"] == "wt"
    # Not in the worktree: falls back to the folder the conversation started in.
    assert read(api, sid, "so-no-principal.md").json()["content"] == "principal"


def test_worktree_outside_the_project(api, home, tmp_path):  # noqa: F811
    root = make_repo(home / "proj")
    wt = tmp_path / "fora" / "w"
    git(root, "worktree", "add", "-q", "-b", "feat", str(wt))
    (wt / "plano.md").write_text("fora")
    sid, _ = session(api, root)
    assert read(api, sid, str(wt / "plano.md")).json()["content"] == "fora"


def test_relative_path_cannot_leave_a_worktree_outside_the_project(api, home, tmp_path):  # noqa: F811
    root = make_repo(home / "proj")
    wt = tmp_path / "fora" / "w"
    git(root, "worktree", "add", "-q", "-b", "feat", str(wt))
    (tmp_path / "fora" / "segredo.md").write_text("x")
    sid, _ = session(api, root)
    record = api.app.state.sessions.get(sid).record
    record.worktree_path = str(wt)
    record.history_dir = str(wt)
    assert record.work_dir() == str(wt)
    assert read(api, sid, "../segredo.md").status_code == 403


def test_outside_every_project_is_forbidden(api, home, tmp_path):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (tmp_path / "segredo.md").write_text("x")
    sid, _ = session(api, root)
    assert read(api, sid, str(tmp_path / "segredo.md")).status_code == 403
    assert read(api, sid, "../../segredo.md").status_code == 403


def test_symlinks_are_judged_by_their_target(api, home, tmp_path):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (tmp_path / "segredo.md").write_text("x")
    (root / "fora.md").symlink_to(tmp_path / "segredo.md")
    (root / "notas.txt").write_text("y")
    (root / "notas.md").symlink_to(root / "notas.txt")
    sid, _ = session(api, root)
    assert read(api, sid, "fora.md").status_code == 403
    assert read(api, sid, "notas.md").status_code == 400


def test_only_markdown(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (root / "a.py").write_text("x")
    sid, _ = session(api, root)
    response = read(api, sid, "a.py")
    assert response.status_code == 400
    assert response.json()["detail"] == "Só arquivos markdown (.md) podem ser lidos aqui."


def test_missing_file_and_folder(api, home):  # noqa: F811
    root = home / "proj"
    (root / "pasta.md").mkdir(parents=True)
    sid, _ = session(api, root)
    assert read(api, sid, "nada.md").status_code == 404
    assert read(api, sid, "pasta.md").status_code == 404


def test_fifo_does_not_block(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    os.mkfifo(root / "cano.md")
    sid, _ = session(api, root)
    assert read(api, sid, "cano.md").status_code == 404


def test_too_big(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (root / "grande.md").write_bytes(b"a" * (1024 * 1024 + 1))
    (root / "limite.md").write_bytes(b"a" * (1024 * 1024))
    sid, _ = session(api, root)
    assert read(api, sid, "grande.md").status_code == 413
    assert read(api, sid, "limite.md").status_code == 200


def test_not_utf8(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (root / "bin.md").write_bytes(b"\xff\xfe\x00x")
    sid, _ = session(api, root)
    response = read(api, sid, "bin.md")
    assert response.status_code == 400
    assert response.json()["detail"] == "O arquivo não é texto UTF-8."


def test_bad_path_values(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    sid, _ = session(api, root)
    assert read(api, sid, "").status_code == 400
    assert read(api, sid, "a\x00.md").status_code == 400
    assert read(api, sid, "a" * 4097 + ".md").status_code == 400


def test_unknown_session(api):  # noqa: F811
    assert read(api, "nao-existe", "a.md").status_code == 404


def test_reading_does_not_load_the_session_into_memory(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (root / "a.md").write_text("x")
    sid, _ = session(api, root)
    manager = api.app.state.sessions
    manager._sessions.pop(sid, None)  # as after a restart: only the database row exists
    assert read(api, sid, "a.md").status_code == 200
    assert sid not in manager._sessions


def test_needs_the_app_header(api, home):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (root / "a.md").write_text("x")
    sid, _ = session(api, root)
    assert read(api, sid, "a.md", headers={"x-maestro": ""}).status_code == 403


def test_expands_the_home_shortcut(api, home, monkeypatch):  # noqa: F811
    monkeypatch.setenv("HOME", str(home))
    root = home / "proj"
    root.mkdir()
    (root / "a.md").write_text("casa")
    sid, _ = session(api, root)
    body = read(api, sid, "~/proj/a.md").json()
    assert body["content"] == "casa"
    assert body["path"] == str((root / "a.md").resolve())


def test_a_symlink_swapped_in_after_the_check_is_not_followed(api, home, tmp_path, monkeypatch):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    (tmp_path / "segredo.md").write_text("x")
    (root / "troca.md").symlink_to(tmp_path / "segredo.md")
    sid, _ = session(api, root)

    async def fake_resolve(raw, roots, *, base=None):
        return root / "troca.md"  # what the check would have returned before the swap

    monkeypatch.setattr("claudio_maestro.api.markdown.resolve_project_path", fake_resolve)
    assert read(api, sid, "troca.md").status_code == 404
