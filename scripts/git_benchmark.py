"""Mede consultas Git em repositórios descartáveis, sem rede ou SDK real.

Uso: uv run python scripts/git_benchmark.py --contract panel --output /tmp/git-after.json
Frio significa cache de política do app limpo, não page cache do sistema operacional.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from claudio_maestro import gitinfo

IDENTITY = {
    "GIT_AUTHOR_NAME": "Benchmark",
    "GIT_AUTHOR_EMAIL": "benchmark@example.invalid",
    "GIT_COMMITTER_NAME": "Benchmark",
    "GIT_COMMITTER_EMAIL": "benchmark@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


async def git(repo: Path, *args: str, input: bytes | None = None) -> str:
    code, out, err = await gitinfo.run_git(repo, *args, env=IDENTITY, input=input, timeout=30)
    if code:
        raise RuntimeError(f"{args[0]} falhou: {err}")
    return out.strip()


async def fixture(root: Path) -> tuple[Path, Path]:
    small = root / "small"
    small.mkdir()
    await git(small, "init", "-b", "main")
    (small / "partial.txt").write_text("base\n" + "context\n" * 10 + "end\n")
    await git(small, "add", "--", "partial.txt")
    await git(small, "commit", "-m", "Base")
    (small / "partial.txt").write_text("staged\n" + "context\n" * 10 + "end\n")
    await git(small, "add", "--", "partial.txt")
    (small / "partial.txt").write_text("staged\n" + "context\n" * 10 + "unstaged\n")
    large = root / "large"
    large.mkdir()
    await git(large, "init", "-b", "main")
    (large / "tracked.txt").write_text("base\n")
    await git(large, "add", "--", "tracked.txt")
    await git(large, "commit", "-m", "Base")
    base = await git(large, "rev-parse", "HEAD")
    tree = await git(large, "rev-parse", "HEAD^{tree}")
    for ref, count, label in [("refs/heads/main", 1101, "local"),
                              ("refs/remotes/origin/main", 101, "remote")]:
        parent = base
        for i in range(count):
            parent = await git(large, "commit-tree", tree, "-p", parent, "-m", f"{label} {i}")
        await git(large, "update-ref", ref, parent)
    await git(large, "config", "remote.origin.url", str(root / "not-contacted"))
    await git(large, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    await git(large, "config", "branch.main.remote", "origin")
    await git(large, "config", "branch.main.merge", "refs/heads/main")
    for i in range(201):
        (large / f"new-{i:03}.txt").write_text("new\n")
    assert await git(large, "rev-list", "--count", "origin/main..HEAD") == "1101"
    assert await git(large, "rev-list", "--count", "HEAD..origin/main") == "101"
    return small, large


async def measure(operation, repetitions: int) -> dict:
    samples = []
    real_run = gitinfo.run_git
    for mode in ("cold_app", "warm"):
        for _ in range(repetitions):
            if mode == "cold_app":
                gitinfo.clear_policy_cache()
            calls = Counter()

            async def counted(repo, *args, **kwargs):
                calls[args[0]] += 1
                return await real_run(repo, *args, **kwargs)

            with patch.object(gitinfo, "run_git", counted):
                started = time.perf_counter()
                result = await operation()
                elapsed = (time.perf_counter() - started) * 1000
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(result["error"])
            samples.append({"mode": mode, "ms": elapsed, "run_git_calls": sum(calls.values()),
                            "commands": dict(calls),
                            "json_bytes": len(json.dumps(result).encode())})
    summary = {}
    for mode in ("cold_app", "warm"):
        selected = [s for s in samples if s["mode"] == mode]
        times = sorted(s["ms"] for s in selected)
        summary[mode] = {"median_ms": statistics.median(times),
                         "p95_ms": times[math.ceil(len(times) * .95) - 1],
                         "run_git_calls": sorted({s["run_git_calls"] for s in selected}),
                         "median_json_bytes": statistics.median(s["json_bytes"] for s in selected)}
    return {"summary": summary, "samples": samples}


async def main(output: Path, repetitions: int, contract: str):
    source_digest = hashlib.sha256(Path(gitinfo.__file__).read_bytes()).hexdigest()
    include_legacy = contract == "legacy"
    with tempfile.TemporaryDirectory(prefix="maestro-git-benchmark-") as temp:
        small, large = await fixture(Path(temp))
        combined = await gitinfo.file_diff(small, "partial.txt")
        staged = await git(small, "diff", "--no-ext-diff", "--no-textconv", "--cached", "--", "partial.txt")
        unstaged = await git(small, "diff", "--no-ext-diff", "--no-textconv", "--", "partial.txt")
        first = await gitinfo.repo_log(large, include_incoming=include_legacy)
        continuation = {} if include_legacy else {
            "snapshot_head": first["head_sha"], "snapshot_upstream": first["upstream_sha"] or "-",
        }
        old = await gitinfo.repo_log(large, skip=1000, limit=101, include_incoming=include_legacy, **continuation)
        details = await gitinfo.repo_details(large, include_commits=include_legacy)
        incoming = await gitinfo.repo_log(large, direction="incoming", limit=101, include_incoming=False)
        staged_scope = await gitinfo.file_diff(small, "partial.txt", scope="staged")
        unstaged_scope = await gitinfo.file_diff(small, "partial.txt", scope="unstaged")
        observations = {
            "combined_diff_contains_staged_and_unstaged": "+staged" in combined.diff and "+unstaged" in combined.diff,
            "git_staged_and_unstaged_differ": staged != unstaged,
            "staged_scope_matches_git": staged_scope.diff.strip() == staged,
            "unstaged_scope_matches_git": unstaged_scope.diff.strip() == unstaged,
            "outgoing_count": first["outgoing_count"],
            "incoming_count": first["incoming_count"],
            "incoming_returned": len(first["incoming"]),
            "incoming_direction_returned": len(incoming["commits"]),
            "known_local_commits_wrongly_marked_pushed": sum(c["pushed"] is True for c in old["commits"]),
            "files_returned": len(details["files"]),
            "files_truncated": details["files_truncated"],
        }
        scenarios = {}
        for label, call in {
            "small_details": lambda: gitinfo.repo_details(small, include_commits=include_legacy),
            "large_details": lambda: gitinfo.repo_details(large, include_commits=include_legacy),
            "large_log_first": lambda: gitinfo.repo_log(large, include_incoming=include_legacy),
            "large_log_page_1000": lambda: gitinfo.repo_log(large, skip=1000, limit=101, include_incoming=include_legacy, **continuation),
        }.items():
            scenarios[label] = await measure(call, repetitions)
        if hashlib.sha256(Path(gitinfo.__file__).read_bytes()).hexdigest() != source_digest:
            raise RuntimeError("gitinfo.py mudou durante o benchmark; repetir com código estável")
        result = {"schema": 2, "contract": contract,
                  "query_options": {"include_commits": include_legacy, "include_incoming": include_legacy,
                                    "continuation_uses_snapshot": not include_legacy},
                  "python": platform.python_version(), "platform": platform.platform(),
                  "cpu": platform.processor(), "cpu_count": os.cpu_count(),
                  "git_version": await git(small, "--version"), "repetitions_per_mode": repetitions,
                  "gitinfo_sha256": source_digest,
                  "limitations": ["cold_app limpa apenas cache de política; cache do SO não é limpo",
                                  "mede funções backend, não HTTP/DOM/latência visual",
                                  "run_git_calls não conta subprocessos internos auxiliares do wrapper",
                                  "sem rede, SDK ou comparação de runtime com VS Code"],
                  "observations": observations, "scenarios": scenarios}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"output": str(output), "observations": observations,
                          "scenarios": {k: v["summary"] for k, v in scenarios.items()}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--contract", choices=("legacy", "panel"), default="panel",
                        help="panel mede consultas sob demanda; legacy inclui commits e incoming antecipados")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions precisa ser positivo")
    asyncio.run(main(args.output, args.repetitions, args.contract))
