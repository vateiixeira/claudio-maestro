"""Bounded, read-only review evidence. Never creates checkouts or SDK sessions.

The caller supplies the registered project's root (never an issue-supplied root).
Each exact repository/worktree gets its own target; aggregate targets by workspace
in the service. Persist the returned document privately, then recapture and compare
its digest before accepting a review. Incomplete targets never have a digest.

Limits apply to each of two complete observations. The content/file budget covers
changed and untracked files plus binary staged/unstaged patches. A separate metadata
budget covers the complete index and path/flag lists, never the baseline file bodies.
HEAD and a digest of complete index metadata identify the immutable baseline.
Git determines changed paths; normal line-ending normalization is Git semantics,
not a byte-for-byte snapshot of unchanged baseline files. Index flags that suppress
change detection are refused, and core.filemode/ignoreStat are overridden per call.
Symlinks, submodules, conflicts and undecodable Git output fail closed. Ignored
untracked files are outside the Git patch contract. The base is the backend-read
HEAD, not a caller-supplied hash. No claim of an atomic filesystem snapshot is made:
stat checks and matching observations detect instability; caller must hold its
checkout reservation and stop writers throughout capture/review acceptance.
"""

import asyncio
import base64
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claudio_maestro import gitinfo
from claudio_maestro.gitinfo import DIFF_SUBMODULES, GitError, run_git


@dataclass(frozen=True)
class CaptureLimits:
    max_bytes: int = 8 * 1024 * 1024
    max_files: int = 1000
    max_seconds: float = 15.0
    max_metadata_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        if min(self.max_bytes, self.max_files, self.max_seconds, self.max_metadata_bytes) <= 0:
            raise ValueError('Os limites de captura precisam ser positivos.')


class _Incomplete(Exception):
    pass


async def _workspace(project: Path, supplied: Path) -> tuple[Path, Path]:
    # Refuse aliases: a supplied symlink is not proof of the workspace identity.
    absolute = supplied if supplied.is_absolute() else project / supplied
    resolved = absolute.resolve(strict=True)
    if absolute.absolute() != resolved:
        raise _Incomplete('O workspace precisa usar seu caminho real, sem links.')
    if not resolved.is_dir():
        raise _Incomplete('O workspace não é uma pasta.')
    found, truncated = await asyncio.to_thread(gitinfo.discover_scan, project)
    if truncated:
        raise _Incomplete('A descoberta de repositórios atingiu o limite.')
    repositories = {Path(path).resolve() for path in found}
    marker = resolved / '.git'
    if resolved in repositories and marker.is_dir() and not marker.is_symlink():
        return resolved, resolved
    linked = await gitinfo.project_worktree(resolved, [project])
    if linked and linked.path == resolved and linked.main_repo in repositories:
        return resolved, linked.main_repo
    raise _Incomplete('O workspace não é uma raiz Git comprovada do projeto.')


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _read_file(root: Path, name: str, remaining: int) -> dict[str, Any]:
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise _Incomplete('Caminho Git inválido.')
    path = root / relative
    if path.resolve().is_relative_to(root) is False:
        raise _Incomplete('Um arquivo sai do workspace.')
    # Walk with dir_fd + NOFOLLOW, so swapping an ancestor cannot redirect reads.
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            try:
                next_descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=descriptor)
            except FileNotFoundError:
                return {'path': name, 'missing': True}
            os.close(descriptor)
            descriptor = next_descriptor
        try:
            file = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                           dir_fd=descriptor)
        except FileNotFoundError:
            return {'path': name, 'missing': True}
        try:
            before = os.fstat(file)
            if not stat.S_ISREG(before.st_mode):
                raise _Incomplete('A captura exige arquivos regulares, sem links.')
            if before.st_size > remaining:
                raise _Incomplete('O conteúdo ultrapassa o limite de bytes.')
            chunks = []
            size = 0
            while True:
                chunk = os.read(file, min(64 * 1024, remaining - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > remaining:
                    raise _Incomplete('O conteúdo ultrapassa o limite de bytes.')
                chunks.append(chunk)
            after = os.fstat(file)
            current = os.stat(relative.name, dir_fd=descriptor, follow_symlinks=False)
            if _signature(before) != _signature(after) or _signature(after) != _signature(current):
                raise _Incomplete('Um arquivo mudou durante a captura.')
            content = b''.join(chunks)
            return {'path': name, 'mode': stat.S_IMODE(after.st_mode), 'size': size,
                    'content_base64': base64.b64encode(content).decode('ascii')}
        finally:
            os.close(file)
    finally:
        os.close(descriptor)


def _check_baseline_types(repo: Path, names: set[str]) -> None:
    # No baseline contents are read. Git can silently omit a tracked FIFO/device.
    for name in names:
        path = repo / name
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise _Incomplete('Caminho Git inválido.')
        if not path.resolve().is_relative_to(repo):
            raise _Incomplete('Um arquivo sai do workspace.')
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            raise _Incomplete('A captura exige arquivos regulares, sem links.')


async def _observe(repo: Path, limits: CaptureLimits) -> dict[str, Any]:
    used = 0
    metadata_used = 0

    async def query(*args: str, metadata: bool = True) -> str:
        nonlocal used, metadata_used
        remaining = (limits.max_metadata_bytes - metadata_used if metadata
                     else limits.max_bytes - used)
        code, output, _ = await run_git(
            repo, *args, timeout=limits.max_seconds, limit=remaining + 1,
            config=[('core.filemode', 'true'), ('core.ignoreStat', 'false'),
                    ('core.trustctime', 'true')],
        )
        size = len(output.encode('utf-8'))
        # The runner decodes with replacement; never fingerprint lossy evidence.
        if code or '\ufffd' in output:
            raise _Incomplete('Git falhou ou devolveu conteúdo não representável sem perda.')
        if size > remaining:
            raise _Incomplete('A saída Git ultrapassa o limite de bytes.')
        if metadata:
            metadata_used += size
        else:
            used += size
        return output

    toplevel = (await query('rev-parse', '--show-toplevel')).rstrip('\n')
    if Path(toplevel).resolve() != repo:
        raise _Incomplete('O diretório de trabalho Git não corresponde ao workspace.')
    head = (await query('rev-parse', '--verify', 'HEAD')).strip()
    baseline_modes = await query('ls-tree', '-r', '--format=%(objectmode)', head)
    if '160000' in baseline_modes.splitlines():
        raise _Incomplete('Submódulos na base exigem revisão sem captura automática.')
    index = await query('ls-files', '--stage', '-z')
    tracked = set()
    for entry in index.split('\0'):
        if not entry:
            continue
        metadata, name = entry.split('\t', 1)
        mode, _, stage = metadata.split()
        if mode == '160000' or stage != '0':
            raise _Incomplete('Submódulos e conflitos exigem revisão sem captura automática.')
        tracked.add(name)
    index_flags = await query('ls-files', '-v', '-z')
    if any(entry and (entry[0].islower() or entry[0] == 'S')
           for entry in index_flags.split('\0')):
        raise _Incomplete('O índice usa assume-unchanged ou skip-worktree e pode ocultar alterações.')
    await asyncio.to_thread(_check_baseline_types, repo, tracked)
    untracked = await query('ls-files', '--others', '--exclude-standard', '-z')
    flags = ('--binary', '--full-index', '--no-color', '--no-ext-diff', '--no-textconv',
             DIFF_SUBMODULES, '--find-renames=50%', '--no-relative')
    staged_paths = await query('diff', *flags, '--name-only', '-z', '--cached', head, '--')
    unstaged_paths = await query('diff', *flags, '--name-only', '-z', '--')
    paths = {name for listing in (staged_paths, unstaged_paths, untracked)
             for name in listing.split('\0') if name}
    if len(paths) > limits.max_files:
        raise _Incomplete('A captura ultrapassa o limite de arquivos alterados.')
    staged = await query('diff', *flags, '--cached', head, '--', metadata=False)
    unstaged = await query('diff', *flags, '--', metadata=False)
    files = []
    for name in sorted(paths):
        document = await asyncio.to_thread(_read_file, repo, name, limits.max_bytes - used)
        used += document.get('size', 0)
        files.append(document)
    index_digest = hashlib.sha256((index + index_flags).encode('utf-8')).hexdigest()
    return {'head': head, 'base': head, 'index_digest': index_digest,
            'staged_patch': staged, 'unstaged_patch': unstaged,
            'untracked_paths': untracked, 'files': files}


async def capture_target(
    project_root: str | Path, workspace: str | Path, *, limits: CaptureLimits = CaptureLimits(),
) -> dict[str, Any]:
    """Capture one exact workspace using a root resolved from the project registry.

    Returns JSON-compatible evidence with complete=True and a SHA-256 digest only
    after matching observations. All expected failures return complete=False,
    digest=None and a Portuguese reason, without partial patches/content.
    Cancellation propagates. No paths/configuration are changed.
    """
    try:
        async with asyncio.timeout(limits.max_seconds):
            project = Path(project_root).resolve(strict=True)
            repo, main = await _workspace(project, Path(workspace))
            first = await _observe(repo, limits)
            second = await _observe(repo, limits)
            again, again_main = await _workspace(project, repo)
            if first != second or (again, again_main) != (repo, main):
                raise _Incomplete('O alvo mudou durante a captura; tente novamente sem escritores ativos.')
            evidence = {'version': 1, 'project_root': str(project), 'workspace': str(repo),
                        'repository': str(main), **first}
            encoded = json.dumps(evidence, sort_keys=True, ensure_ascii=True,
                                 separators=(',', ':')).encode()
            return {**evidence, 'complete': True, 'digest': hashlib.sha256(encoded).hexdigest()}
    except (OSError, ValueError, GitError, _Incomplete, TimeoutError) as exc:
        reason = str(exc) if isinstance(exc, _Incomplete) else 'Não foi possível capturar o alvo completo dentro dos limites.'
        return {'version': 1, 'complete': False, 'digest': None, 'reason': reason}
