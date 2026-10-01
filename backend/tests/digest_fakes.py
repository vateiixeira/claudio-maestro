# backend/tests/digest_fakes.py
"""Helpers for the digest agent tests: a fake session manager and transcripts."""

import os
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from claudio_maestro import db
from claudio_maestro.history import Transcript

NOW = 1_000_000.0


def user(uuid: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(type="user", uuid=uuid, message={"role": "user", "content": text})


def claude(uuid: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(type="assistant", uuid=uuid,
                           message={"role": "assistant", "content": [{"type": "text", "text": text}]})


def exchange(start: int, count: int) -> list[SimpleNamespace]:
    """`count` condensable entries: alternating prompts and answers."""
    return [
        user(f"u{i}", f"pedido {i}") if i % 2 == 0 else claude(f"a{i}", f"resposta {i}")
        for i in range(start, start + count)
    ]


class FakeManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sessions: list[dict[str, Any]] = []
        self.briefs: dict[str, tuple[str | None, bool]] = {}
        self.models = [{"value": "default"}, {"value": "sonnet"}, {"value": "haiku"}]

    def list_sessions(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self.sessions]

    def project_roots(self) -> list[Path]:
        return [self.root]

    def list_models(self) -> list[dict[str, Any]]:
        return self.models

    async def set_digest_brief(self, session_id: str, short: str | None, plan_done: bool) -> None:
        self.briefs[session_id] = (short, plan_done)


class World:
    """Database with one project, sessions with files and transcripts."""

    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.root = tmp_path / "app"
        self.root.mkdir()
        self.files_dir = tmp_path / "files"
        self.files_dir.mkdir()
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (1, 'app', ?, '#fff', 0, 0)", (str(self.root),)
            )
        self.manager = FakeManager(self.root)
        self.transcripts: dict[str, Transcript] = {}
        self.envelopes: list[dict[str, Any]] = []
        self.clock = [NOW]
        self.lookups: list[tuple[str, str]] = []  # (session_id, directory) asked of `session_file`

    def add(self, sid: str, messages: list[Any], *, mtime: float = NOW - 10,
            history_dir: str | None = None, **fields) -> None:
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at, history_dir) VALUES (?, 1, ?, ?, ?, ?, ?)",
                (sid, str(self.root), f"Sessão {sid}", NOW - 3600, NOW - 60, history_dir),
            )
        session = {
            "session_id": sid, "project_id": 1, "cwd": str(self.root), "title": f"Sessão {sid}",
            "created_at": int(NOW - 3600), "last_activity_at": int(NOW - 60), "state": "closed",
            "display_state": "waiting", "cli_running": False, "plan": None,
        }
        session.update(fields)
        self.manager.sessions.append(session)
        self.transcripts[sid] = Transcript(messages=messages, tool_results={})
        path = self.files_dir / f"{sid}.jsonl"
        path.write_text("{}\n")
        os.utime(path, (mtime, mtime))

    def touch(self, sid: str, messages: list[Any], mtime: float) -> None:
        self.transcripts[sid].messages.extend(messages)
        os.utime(self.files_dir / f"{sid}.jsonl", (mtime, mtime))

    def session_file(self, sid: str, directory: str) -> Path | None:
        self.lookups.append((sid, directory))
        path = self.files_dir / f"{sid}.jsonl"
        return path if path.exists() else None

    def read_transcript(self, path: Path | None):
        return None if path is None else self.transcripts.get(path.stem)

    def service(self, model, **kwargs):
        from claudio_maestro.digest.service import DigestService

        service = DigestService(
            self.db_path, self.manager, self.envelopes.append, model,
            clock=lambda: self.clock[0], session_file=self.session_file,
            read_transcript=self.read_transcript, **kwargs,
        )
        service.load()
        return service

    def digest(self, sid: str):
        from claudio_maestro.digest import store

        with closing(db.connect(self.db_path)) as conn:
            return store.get_digest(conn, sid)

    def published(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.envelopes if e["type"] == type_]
