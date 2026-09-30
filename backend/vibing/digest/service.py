# backend/vibing/digest/service.py
"""The digest agent: picks the conversations to read, reads them one at a time and
keeps their summaries. The scheduler loop is at the end of the file."""

import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vibing import db, history
from vibing.digest import store
from vibing.digest.condense import Slice, condense, entries_after
from vibing.digest.config import DigestConfig, load_config, model_known
from vibing.digest.merge import DigestFormatError, merge_digest
from vibing.digest.model import DigestModel, DigestModelError, DigestRequest
from vibing.digest.prompt import build_prompt, spec_refs, system_prompt
from vibing.digest.store import Digest
from vibing.plans import PlanCache, PlanProgress

logger = logging.getLogger(__name__)

SESSION_TIMEOUT = 120.0
AGENT_DIR_NAME = "digest-agent"
STOPPED_DISABLED = "Desligado."
TIMEOUT_MESSAGE = "O agente demorou demais para responder."
NOT_FOUND = "Conversa não encontrada."
UNEXPECTED = "Falha inesperada ao resumir a conversa."
NO_FILE = "O arquivo da conversa não foi encontrado."
NOTHING_YET = "Ainda não há nada para resumir."
RUNNING_STATES = ("connecting", "running")


def pre_eligible(
    session: dict[str, Any],
    digest: Digest | None,
    file_mtime: float | None,
    config: DigestConfig,
    now: float,
) -> bool:
    """Cheap checks, before reading the file: not finished, active within the window,
    file changed since the last reading, and the turn closed or open for too long."""
    if session["display_state"] == "finished":
        return False
    if now - session["last_activity_at"] > config.window_days * 86400:
        return False
    if file_mtime is None:
        return False
    read_at = digest.read_at if digest else None
    if read_at is not None and file_mtime <= read_at:
        return False
    if session["state"] in RUNNING_STATES or session.get("cli_running"):
        since = read_at if read_at is not None else session["created_at"]
        return now - since >= config.open_turn_minutes * 60
    return True


@dataclass
class _Prepared:
    old: Digest | None
    slice: Slice
    count: int
    prompt: str
    plan_path: str | None
    plan: PlanProgress | None
    roots: list[Path]
    read_at: int


class _StopPass(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DigestService:
    def __init__(
        self,
        db_path: Path,
        manager: Any,
        publish: Callable[[dict[str, Any]], None],
        model: DigestModel,
        *,
        clock: Callable[[], float] = time.time,
        session_file: Callable[[str, str], Path | None] | None = None,
        read_transcript: Callable[[Path | None], history.Transcript | None] | None = None,
        session_timeout: float = SESSION_TIMEOUT,
    ) -> None:
        self._db_path = db_path
        self._manager = manager
        self._publish = publish
        self._model = model
        self._clock = clock
        # Looked up at call time, so tests that patch `vibing.history` are honored.
        self._session_file = session_file or (lambda sid, cwd: history.sdk_session_file(sid, cwd))
        self._read_transcript = read_transcript or (lambda path: history.read_transcript_at(path))
        self._session_timeout = session_timeout
        self._plan_cache = PlanCache()
        self._config = DigestConfig()
        self._running = False
        self._next_run_at: float | None = None
        self._paused_until: float | None = None

    # State -------------------------------------------------------------------

    @property
    def config(self) -> DigestConfig:
        return self._config

    def load(self) -> None:
        """Read the stored configuration. Blocking."""
        with closing(db.connect(self._db_path)) as conn:
            self._config = load_config(conn)

    def status(self) -> dict[str, Any]:
        def whole(value: float | None) -> int | None:
            return None if value is None else int(value)

        return {
            "enabled": self._config.enabled,
            "running": self._running,
            "next_run_at": whole(self._next_run_at) if self._config.enabled else None,
            "paused_until": whole(self._paused_until),
        }

    def _publish_status(self) -> None:
        self._publish({"session_id": None, "seq": 0, "type": "digest.status", "data": self.status()})

    def _publish_digest(self, digest: Digest) -> None:
        self._publish({
            "session_id": None, "seq": 0, "type": "session.digest",
            "data": {"session_id": digest.session_id, "digest": digest.to_dict()},
        })

    # One pass ----------------------------------------------------------------

    async def run_pass(self, trigger: str, session_ids: list[str] | None = None) -> dict[str, Any]:
        """Read the sessions of one pass and log it. `session_ids` only for
        `manual_session`. Cancelling it logs the pass as stopped by `STOPPED_DISABLED`."""
        config = self._config
        started = int(self._clock())
        run_id = await asyncio.to_thread(self._start_run, trigger, started)
        read = skipped = 0
        errors: list[dict[str, Any]] = []
        stopped: str | None = None
        handled: set[str] = set()  # sessions that already got a result or an error
        try:
            self._running = True
            self._publish_status()
            known = [m.get("value") for m in self._manager.list_models()]
            if not model_known(config.model, [k for k in known if isinstance(k, str)]):
                raise _StopPass(f"O modelo {config.model} não está mais disponível.")
            sessions = await self._candidates(trigger, session_ids, config, errors)
            for session in sessions:
                handled.add(session["session_id"])
                outcome = await self._digest_one(session, trigger, config)
                if outcome == "read":
                    read += 1
                elif outcome == "skipped":
                    skipped += 1
                else:
                    errors.append({"session_id": session["session_id"],
                                   "title": session["title"], "message": outcome})
        except _StopPass as stop:
            stopped = stop.message
            # Requested sessions not reached yet get the reason, so "Resumindo…" ends.
            for sid in session_ids or []:
                if sid not in handled:
                    await self._fail(sid, stop.message)
        except asyncio.CancelledError:
            stopped = STOPPED_DISABLED
            raise
        finally:
            self._running = False
            run = self._finish_run(run_id, read, skipped, errors, stopped)
            self._publish_status()
        return run

    def _start_run(self, trigger: str, at: int) -> int:
        with closing(db.connect(self._db_path)) as conn:
            return store.start_run(conn, trigger, at)

    def _finish_run(self, run_id: int, read: int, skipped: int,
                    errors: list[dict[str, Any]], stopped: str | None) -> dict[str, Any]:
        # Synchronous on purpose: it also runs while the pass is being cancelled.
        with closing(db.connect(self._db_path)) as conn:
            return store.finish_run(conn, run_id, at=int(self._clock()), read_count=read,
                                    skipped_count=skipped, errors=errors, stopped=stopped)

    async def _candidates(
        self,
        trigger: str,
        session_ids: list[str] | None,
        config: DigestConfig,
        errors: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        sessions = self._manager.list_sessions()
        if session_ids is not None:
            by_id = {s["session_id"]: s for s in sessions}
            chosen = []
            for sid in session_ids:
                if sid in by_id:
                    chosen.append(by_id[sid])
                else:
                    errors.append({"session_id": sid, "title": sid, "message": NOT_FOUND})
            return chosen
        now = self._clock()
        chosen = await asyncio.to_thread(self._filter, sessions, config, now)
        return sorted(chosen, key=lambda s: s["last_activity_at"], reverse=True)

    @staticmethod
    def _history_dir(conn: sqlite3.Connection, session: dict[str, Any]) -> str:
        """Folder the transcript is stored under: `history_dir`, else the `cwd`
        (a session in a git worktree keeps its file under the original folder)."""
        row = conn.execute("SELECT history_dir FROM sessions WHERE session_id = ?",
                           (session["session_id"],)).fetchone()
        return (row["history_dir"] if row else None) or session["cwd"]

    def _file_mtime(self, session: dict[str, Any], directory: str) -> float | None:
        path = self._session_file(session["session_id"], directory)
        if path is None:
            return None
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def _filter(self, sessions: list[dict[str, Any]], config: DigestConfig,
                now: float) -> list[dict[str, Any]]:
        with closing(db.connect(self._db_path)) as conn:
            return [
                s for s in sessions
                if pre_eligible(s, store.get_digest(conn, s["session_id"]),
                                self._file_mtime(s, self._history_dir(conn, s)), config, now)
            ]

    def _prepare(self, session: dict[str, Any], config: DigestConfig) -> _Prepared | None:
        """Everything the request needs, read from disk. Blocking. None without a file."""
        sid = session["session_id"]
        read_at = int(self._clock())  # before reading: later writes count as new
        with closing(db.connect(self._db_path)) as conn:
            old = store.get_digest(conn, sid)
            row = conn.execute("SELECT name FROM projects WHERE id = ?",
                               (session["project_id"],)).fetchone()
            roots = [Path(r["path"]) for r in conn.execute("SELECT path FROM projects")]
            directory = self._history_dir(conn, session)
        transcript = self._read_transcript(self._session_file(sid, directory))
        if transcript is None:
            return None
        piece = entries_after(transcript, old.cursor if old else None)
        condensed = condense(piece.messages, transcript.tool_results, session["cwd"])
        plan_info = session.get("plan") or None
        plan_path = plan_info.get("path") if isinstance(plan_info, dict) else None
        progress = self._plan_cache.read(Path(plan_path)) if plan_path else None
        prompt = build_prompt(
            project=row["name"] if row else "",
            title=session["title"],
            digest=old,
            plan=(plan_path, progress) if plan_path and progress else None,
            specs=spec_refs(condensed.paths, roots),
            text=condensed.text,
            restarted=not piece.cursor_found,
        )
        return _Prepared(old, piece, condensed.count, prompt, plan_path, progress, roots, read_at)

    async def _fail(self, session_id: str, message: str) -> None:
        digest = await asyncio.to_thread(self._save_error, session_id, message)
        if digest is not None:
            self._publish_digest(digest)

    def _save_error(self, session_id: str, message: str) -> Digest | None:
        with closing(db.connect(self._db_path)) as conn:
            return store.save_error(conn, session_id, message, int(self._clock()))

    def _save(self, digest: Digest) -> bool:
        try:
            with closing(db.connect(self._db_path)) as conn:
                store.save_digest(conn, digest)
            return True
        except sqlite3.IntegrityError:
            return False  # the session left the index meanwhile

    async def _digest_one(self, session: dict[str, Any], trigger: str,
                          config: DigestConfig) -> str:
        """"read", "skipped" or the error message of this session. An unexpected error
        is recorded on the session and the pass goes on (cancellation and the
        stop-the-pass signal pass through)."""
        try:
            return await self._read_session(session, trigger, config)
        except _StopPass:
            raise
        except Exception:
            sid = session["session_id"]
            logger.exception("Unexpected error while digesting session %s", sid)
            try:
                await self._fail(sid, UNEXPECTED)
            except Exception:
                logger.exception("Could not record the error of session %s", sid)
            return UNEXPECTED

    async def _read_session(self, session: dict[str, Any], trigger: str,
                            config: DigestConfig) -> str:
        sid = session["session_id"]
        manual = trigger == "manual_session"
        prepared = await asyncio.to_thread(self._prepare, session, config)
        if prepared is None:
            if manual:
                await self._fail(sid, NO_FILE)
            return "skipped"
        if prepared.count == 0:
            if manual:
                if prepared.old is not None:
                    self._publish_digest(prepared.old)
                else:
                    await self._fail(sid, NOTHING_YET)
            return "skipped"
        if trigger == "auto" and prepared.count < config.min_new_messages:
            return "skipped"
        request = DigestRequest(system_prompt(config.extra_instructions), prepared.prompt,
                                config.model, config.effort)
        try:
            async with asyncio.timeout(self._session_timeout):
                result = await self._model.summarize(request)
            digest = merge_digest(
                prepared.old, result, session_id=sid, cursor=prepared.slice.cursor,
                read_at=prepared.read_at, plan_path=prepared.plan_path, plan=prepared.plan,
                roots=prepared.roots,
            )
        except TimeoutError:
            await self._fail(sid, TIMEOUT_MESSAGE)
            return TIMEOUT_MESSAGE
        except DigestFormatError as error:
            await self._fail(sid, str(error))
            return str(error)
        except DigestModelError as error:
            await self._fail(sid, error.message)
            if error.stop_pass:
                if error.resets_at:
                    self._paused_until = float(error.resets_at)
                raise _StopPass(error.message) from error
            return error.message
        if not await asyncio.to_thread(self._save, digest):
            return "skipped"
        self._publish_digest(digest)
        try:
            await self._manager.set_digest_brief(sid, digest.short, digest.plan_done)
        except Exception:
            # The digest is saved and published; only the session brief is missing.
            logger.exception("Could not update the brief of session %s", sid)
        return "read"
