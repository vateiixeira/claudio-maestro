"""Review targets use only disposable repositories and the hardened Git runner."""
import asyncio
import os
import stat

import pytest

from claudio_maestro.gitinfo import run_git
from claudio_maestro.work.targets import CaptureLimits, capture_target


def run(coro):
    return asyncio.run(coro)


def git(repo, *args):
    code, out, err = run(run_git(repo, *args))
    assert code == 0, err
    return out


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'project' / 'repo'
    path.mkdir(parents=True)
    git(path, 'init')
    git(path, 'config', 'user.email', 'test@example.invalid')
    git(path, 'config', 'user.name', 'Test')
    (path / 'a').write_text('original\n')
    git(path, 'add', 'a')
    git(path, 'commit', '-m', 'initial')
    return path


def capture(repo, **kwargs):
    return run(capture_target(repo.parent, repo, **kwargs))


def test_deterministic_and_separate_staged_unstaged(repo):
    (repo / 'a').write_text('staged\n')
    git(repo, 'add', 'a')
    (repo / 'a').write_text('unstaged\n')
    result = capture(repo)
    assert result['complete']
    assert '+staged' in result['staged_patch']
    assert '+unstaged' in result['unstaged_patch']
    assert result == capture(repo)
    (repo / 'a').write_text('changed\n')
    assert result['digest'] != capture(repo)['digest']


@pytest.mark.parametrize('change', ['untracked', 'binary', 'mode', 'delete', 'rename', 'stage'])
def test_changes_affect_digest(repo, change):
    before = capture(repo)
    if change == 'untracked':
        (repo / 'new').write_bytes(b'content')
    elif change == 'binary':
        (repo / 'a').write_bytes(b'\0\xff\0')
    elif change == 'mode':
        (repo / 'a').chmod(0o755)
    elif change == 'delete':
        (repo / 'a').unlink()
    elif change == 'rename':
        git(repo, 'mv', 'a', 'renamed')
    else:
        (repo / 'a').write_text('staged')
        git(repo, 'add', 'a')
    after = capture(repo)
    assert after['complete'], after
    assert after['digest'] != before['digest']


def test_limits_fail_closed(repo):
    (repo / 'new').write_bytes(b'x' * 1000)
    result = capture(repo, limits=CaptureLimits(max_bytes=200))
    assert not result['complete'] and result['digest'] is None
    (repo / 'another').write_text('extra')
    result = capture(repo, limits=CaptureLimits(max_files=1))
    assert not result['complete']


def test_untracked_symlink_is_not_followed(repo, tmp_path):
    secret = tmp_path / 'secret'
    secret.write_text('secret')
    (repo / 'link').symlink_to(secret)
    result = capture(repo)
    assert not result['complete'] and result['digest'] is None
    assert 'secret' not in str(result)


def test_workspace_validation_and_linked_worktree(repo, tmp_path):
    assert not run(capture_target(repo.parent, repo / 'subdir'))['complete']
    external = tmp_path / 'external'
    git(repo, 'worktree', 'add', '-b', 'review', str(external))
    assert run(capture_target(repo.parent, external))['complete']
    forged = tmp_path / 'forged'
    forged.mkdir()
    (forged / '.git').write_text((external / '.git').read_text())
    assert not run(capture_target(repo.parent, forged))['complete']
    assert not run(capture_target(forged, repo))['complete']
    link = repo.parent / 'escape'
    link.symlink_to(external, target_is_directory=True)
    assert not run(capture_target(repo.parent, link))['complete']


def test_instability_invalidates_capture(repo, monkeypatch):
    from claudio_maestro.work import targets
    real = targets.run_git
    calls = 0

    async def changing(*args, **kwargs):
        nonlocal calls
        result = await real(*args, **kwargs)
        if args[1] == 'diff':
            calls += 1
            (repo / 'a').write_text(f'change {calls}\n')
        return result

    monkeypatch.setattr(targets, 'run_git', changing)
    assert not capture(repo)['complete']


def test_truncated_git_output_fails_closed(repo, monkeypatch):
    from claudio_maestro.work import targets
    real = targets.run_git

    async def truncated(*args, **kwargs):
        result = await real(*args, **kwargs)
        if args[1] == 'diff':
            return 0, 'x' * kwargs['limit'], ''
        return result

    monkeypatch.setattr(targets, 'run_git', truncated)
    assert not capture(repo)['complete']


def test_configured_programs_never_execute(repo, tmp_path):
    marker = tmp_path / 'executed'
    command = f'touch {marker}'
    for key in ['core.fsmonitor', 'diff.external', 'filter.evil.clean', 'filter.evil.smudge', 'diff.evil.textconv']:
        git(repo, 'config', key, command)
    (repo / '.gitattributes').write_text('* filter=evil diff=evil\n')
    (repo / 'a').write_text('changed\n')
    assert capture(repo)['complete']
    assert not marker.exists()


def test_untracked_binary_contents_and_permissions_are_evidence(repo):
    import base64

    path = repo / 'binary'
    path.write_bytes(b'\x00\xff\x01')
    first = capture(repo)
    document = next(file for file in first['files'] if file['path'] == 'binary')
    assert base64.b64decode(document['content_base64']) == path.read_bytes()
    path.write_bytes(b'\x00\xff\x02')
    second = capture(repo)
    assert first['digest'] != second['digest']
    path.chmod(0o755)
    assert second['digest'] != capture(repo)['digest']


def test_index_changes_even_with_identical_worktree(repo):
    (repo / 'a').write_text('same worktree')
    before = capture(repo)
    git(repo, 'add', 'a')
    after = capture(repo)
    assert before['files'] == after['files']
    assert before['digest'] != after['digest']


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
def test_index_flags_that_hide_worktree_bytes_are_incomplete(repo, flag):
    git(repo, 'update-index', flag, 'a')
    (repo / 'a').write_text('hidden worktree change\n')
    result = capture(repo)
    assert not result['complete'] and result['digest'] is None
    assert 'índice' in result['reason']


def test_submodule_and_nonrepository_are_incomplete(repo, tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert not run(capture_target(empty, empty))['complete']
    head = git(repo, 'rev-parse', 'HEAD').strip()
    git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{head},module')
    assert not capture(repo)['complete']


def test_undecodable_patch_and_fifo_fail_closed(repo):
    import os

    (repo / 'a').write_bytes(b'\xff\xfe\n')
    assert not capture(repo)['complete']
    (repo / 'a').write_text('original\n')
    (repo / 'a').unlink()
    os.mkfifo(repo / 'a')
    assert not capture(repo)['complete']


def test_timeout_fails_closed(repo, monkeypatch):
    from claudio_maestro.work import targets
    real = targets.run_git

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.05)
        return await real(*args, **kwargs)

    monkeypatch.setattr(targets, 'run_git', slow)
    result = capture(repo, limits=CaptureLimits(max_seconds=0.02))
    assert not result['complete'] and result['digest'] is None


def test_linked_worktree_inside_directory_is_not_exact_root(repo, tmp_path):
    external = tmp_path / 'linked'
    git(repo, 'worktree', 'add', '-b', 'nested-review', str(external))
    nested = external / 'folder'
    nested.mkdir()
    assert not run(capture_target(repo.parent, nested))['complete']


def test_file_change_during_read_fails_closed(repo, monkeypatch):
    (repo / 'a').write_text('dirty file\n')
    from claudio_maestro.work import targets
    real = targets.os.read
    changed = False

    def changing(descriptor, amount):
        nonlocal changed
        data = real(descriptor, amount)
        if not changed and stat.S_ISREG(os.fstat(descriptor).st_mode):
            changed = True
            (repo / 'a').write_text('concurrent writer\n')
        return data

    monkeypatch.setattr(targets.os, 'read', changing)
    result = capture(repo)
    assert not result['complete'] and result['digest'] is None


def test_git_worktree_override_cannot_escape_project(repo, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'a').write_text('must not be read')
    git(repo, 'config', 'core.worktree', str(outside))
    result = capture(repo)
    assert not result['complete'] and result['digest'] is None
    assert 'must not be read' not in str(result)


def test_git_directory_symlink_is_not_proof(repo, tmp_path):
    fake = repo.parent / 'fake'
    fake.mkdir()
    (fake / '.git').symlink_to(repo / '.git', target_is_directory=True)
    assert not run(capture_target(repo.parent, fake))['complete']


def test_large_unchanged_baseline_with_small_patch_fits_change_limits(repo):
    for number in range(1100):
        (repo / f'baseline-{number}').write_bytes(b'x' * 8192)
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'large baseline')
    limits = CaptureLimits(max_files=2, max_bytes=4096)
    baseline = capture(repo, limits=limits)
    assert baseline['complete'], baseline
    assert baseline['files'] == []
    (repo / 'a').write_text('small patch\n')
    modified = capture(repo, limits=limits)
    assert modified['complete'], modified
    assert [file['path'] for file in modified['files']] == ['a']
    assert modified['digest'] != baseline['digest']
    assert len(str(modified)) < 4096


def test_filemode_config_cannot_hide_permission_change(repo):
    git(repo, 'config', 'core.filemode', 'false')
    before = capture(repo)
    (repo / 'a').chmod(0o755)
    after = capture(repo)
    assert after['complete']
    assert after['digest'] != before['digest']
    assert '100755' in after['unstaged_patch']


def test_metadata_limits_fail_closed_independently(repo):
    result = capture(repo, limits=CaptureLimits(max_metadata_bytes=8))
    assert not result['complete'] and result['digest'] is None


def test_gitlink_removed_from_index_still_refuses_head_baseline(repo):
    head = git(repo, 'rev-parse', 'HEAD').strip()
    git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{head},module')
    git(repo, 'commit', '-m', 'gitlink baseline')
    git(repo, 'update-index', '--force-remove', 'module')
    result = capture(repo)
    assert not result['complete'] and result['digest'] is None
    assert 'Submódulos' in result['reason']


def test_deleted_tracked_parent_directory_is_valid_patch(repo):
    parent = repo / 'directory'
    parent.mkdir()
    (parent / 'a').write_text('nested content\n')
    git(repo, 'add', 'directory/a')
    git(repo, 'commit', '-m', 'nested file')
    (parent / 'a').unlink()
    parent.rmdir()
    result = capture(repo)
    assert result['complete'], result
    assert 'deleted file mode' in result['unstaged_patch']
    assert {'path': 'directory/a', 'missing': True} in result['files']


@pytest.mark.parametrize('replacement', ['file', 'link', 'loop'])
def test_missing_parent_fix_does_not_accept_invalid_ancestors(repo, replacement):
    parent = repo / 'directory'
    parent.mkdir()
    (parent / 'a').write_text('nested content\n')
    git(repo, 'add', 'directory/a')
    git(repo, 'commit', '-m', 'nested file')
    (parent / 'a').unlink()
    parent.rmdir()
    if replacement == 'file':
        parent.write_text('not a directory')
    elif replacement == 'loop':
        parent.symlink_to('directory')
    else:
        target = repo / 'other'
        target.mkdir()
        (target / 'a').write_text('different content\n')
        parent.symlink_to(target, target_is_directory=True)
    result = capture(repo)
    assert not result['complete'] and result['digest'] is None
