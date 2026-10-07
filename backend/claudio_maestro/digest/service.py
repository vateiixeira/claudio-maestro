# backend/claudio_maestro/digest/service.py
"""The digest agent: picks the conversations to read, reads them one at a time and
keeps their summaries. The scheduler loop is at the end of the file."""

import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claudio_maestro import db, deliveries, gitinfo, history
from claudio_maestro.deliveries import Delivery
from claudio_maestro.digest import closure_store, store
from claudio_maestro.digest.closure import (
    CLOSURE_SCHEMA,
    TAIL_BUDGET,
    ClosureFormatError,
    GitFacts,
    apply_answer,
    build_closure_prompt,
    cheap_key,
    closure_candidate,
    closure_eligible,
    closure_system_prompt,
    decide,
    fingerprint,
    normalize,
    tail_messages,
)
from claudio_maestro.digest.closure_store import Closure
from claudio_maestro.digest.condense import Slice, condense, entries_after
from claudio_maestro.digest.config import DigestConfig, load_config, model_known
from claudio_maestro.digest.delivery import (
    DELIVERY_SCHEMA,
    build_delivery_prompt,
    clean_delivery,
    delivery_system_prompt,
    slice_between,
)
from claudio_maestro.digest.merge import DigestFormatError, merge_digest
from claudio_maestro.digest.model import DigestModel, DigestModelError, DigestRequest
from claudio_maestro.digest.prompt import build_prompt, spec_refs, system_prompt
from claudio_maestro.digest.store import Digest
from claudio_maestro.gitinfo import RepoStatus
from claudio_maestro.plans import PlanCache, PlanProgress

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
SCAN_INTERVAL = 60
GIT_RECHECK_SECONDS = 300
ITEM_NOT_FOUND = "Item não encontrado; a verificação foi atualizada."
DELIVERY_NOT_FOUND = "Entrega não encontrada."
AGENT_OFF = "O agente de resumos está desligado."
ALREADY_PENDING = "Esta entrega já está sendo resumida."
UNTITLED = "Conversa sem título"


class ClosureItemNotFound(Exception):
    pass


class DeliveryNotFound(Exception):
    def __init__(self, message: str = DELIVERY_NOT_FOUND) -> None:
        super().__init__(message)
        self.message = message


class DeliveryConflict(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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


@dataclass
class _DeliveryJob:
    delivery: Delivery
    prompt: str | None  # None: nothing to summarize (title only)


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
        git_status: Callable[[Path], Awaitable[RepoStatus]] | None = None,
    ) -> None:
        self._db_path = db_path
        self._manager = manager
        self._publish = publish
        self._model = model
        self._clock = clock
        # Looked up at call time, so tests that patch `claudio_maestro.history` are honored.
        self._session_file = session_file or (lambda sid, cwd: history.sdk_session_file(sid, cwd))
        self._read_transcript = read_transcript or (lambda path: history.read_transcript_at(path))
        self._session_timeout = session_timeout
        self._git_status = git_status or (lambda path: gitinfo.repo_status(path))
        self._closure_next_at: float | None = None
        # session_id -> (cheap fingerprint, when git was last read for it)
        self._closure_scanned: dict[str, tuple[str, float]] = {}
        self._plan_cache = PlanCache()
        self._config = DigestConfig()
        self._running = False
        self._next_run_at: float | None = None
        self._paused_until: float | None = None
        self._pending_all = False
        self._pending_sessions: dict[str, None] = {}
        self._pending_deliveries: dict[int, None] = {}
        self._wake = asyncio.Event()
        self._current: asyncio.Task[dict[str, Any]] | None = None

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
            "paused_until": whole(self._paused_until)
            if self._paused_until is not None and self._paused_until > self._clock() else None,
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
        current: str | None = None  # the session being read right now
        cancelled = False
        try:
            self._running = True
            self._publish_status()
            known = [m.get("value") for m in self._manager.list_models()]
            if not model_known(config.model, [k for k in known if isinstance(k, str)]):
                raise _StopPass(f"O modelo {config.model} não está mais disponível.")
            sessions = await self._candidates(trigger, session_ids, config, errors)
            for session in sessions:
                handled.add(session["session_id"])
                current = session["session_id"]
                outcome = await self._digest_one(session, trigger, config)
                # The summary is settled before the closure check, so a stop or a
                # cancellation during the check does not turn it into a failure.
                current = None
                if outcome == "read":
                    read += 1
                elif outcome == "skipped":
                    skipped += 1
                else:
                    errors.append({"session_id": session["session_id"],
                                   "title": session["title"], "message": outcome})
                if trigger == "manual_session":
                    try:
                        fresh = self._session_summary(session["session_id"]) or session
                        await self._check_closure(fresh, config, automatic=False)
                    except _StopPass:
                        raise
                    except Exception:
                        logger.exception("Unexpected error while checking session %s",
                                         session["session_id"])
        except _StopPass as stop:
            stopped = stop.message
            # Requested sessions not reached yet get the reason, so "Resumindo…" ends.
            for sid in session_ids or []:
                if sid not in handled:
                    await self._fail(sid, stop.message)
        except asyncio.CancelledError:
            stopped = STOPPED_DISABLED
            cancelled = True
            # Synchronous on purpose: a second cancel could interrupt an await here.
            # The requested sessions not finished get the reason, so "Resumindo…" ends.
            for sid in session_ids or []:
                if sid not in handled or sid == current:
                    self._fail_now(sid, STOPPED_DISABLED)
            raise
        finally:
            self._running = False
            if cancelled:
                run = self._finish_run(run_id, read, skipped, errors, stopped)
            else:
                run = await asyncio.to_thread(self._finish_run, run_id, read, skipped,
                                              errors, stopped)
            self._publish_status()
        return run

    def _start_run(self, trigger: str, at: int) -> int:
        with closing(db.connect(self._db_path)) as conn:
            return store.start_run(conn, trigger, at)

    def _finish_run(self, run_id: int, read: int, skipped: int,
                    errors: list[dict[str, Any]], stopped: str | None) -> dict[str, Any]:
        # Blocking: called on the loop only while the pass is being cancelled.
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

    def _fail_now(self, session_id: str, message: str) -> None:
        """`_fail` without awaiting, for the cancellation path."""
        try:
            digest = self._save_error(session_id, message)
            if digest is not None:
                self._publish_digest(digest)
        except Exception:
            logger.exception("Could not record the error of session %s", session_id)

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

    # Closure check -------------------------------------------------------------

    def _publish_closure(self, closure: Closure, last_activity_at: int | None) -> None:
        self._publish({
            "session_id": None, "seq": 0, "type": "session.closure",
            "data": {"session_id": closure.session_id,
                     "closure": closure.to_dict(last_activity_at)},
        })

    async def _closure_saved(self, closure: Closure, last_activity_at: int | None) -> None:
        self._publish_closure(closure, last_activity_at)
        try:
            await self._manager.set_closure_brief(
                closure.session_id, closure.verdict, closure.checked_at)
        except Exception:
            logger.exception("Could not update the closure of session %s", closure.session_id)

    def _closure_inputs(self, session: dict[str, Any]) -> dict[str, Any] | None:
        """Files, summary and plan for one session. Blocking. None without a file."""
        sid = session["session_id"]
        with closing(db.connect(self._db_path)) as conn:
            directory = self._history_dir(conn, session)
            old = closure_store.get_closure(conn, sid)
            digest = store.get_digest(conn, sid)
            row = conn.execute("SELECT name FROM projects WHERE id = ?",
                               (session["project_id"],)).fetchone()
        mtime = self._file_mtime(session, directory)
        if mtime is None:
            return None
        plan_info = session.get("plan") or None
        plan_path = plan_info.get("path") if isinstance(plan_info, dict) else None
        progress = self._plan_cache.read(Path(plan_path)) if plan_path else None
        resolved = old.resolved if old else []
        return {"directory": directory, "mtime": mtime, "old": old, "digest": digest,
                "project": row["name"] if row else "", "plan_path": plan_path,
                "plan": progress, "resolved": resolved,
                "cheap": cheap_key(file_mtime=mtime, plan=progress, resolved=resolved)}

    async def _git_facts(self, cwd: str) -> GitFacts | None:
        try:
            return GitFacts.from_status(await self._git_status(Path(cwd)))
        except Exception:
            logger.exception("Could not read git for %s", cwd)
            return None

    async def _check_closure(self, session: dict[str, Any], config: DigestConfig, *,
                             automatic: bool) -> str:
        """"read", "skipped", "ignored" (not a candidate: not even counted) or the error
        message. Raises _StopPass."""
        sid = session["session_id"]
        now = self._clock()
        if not closure_candidate(session, config, now, automatic=automatic):
            return "ignored"
        inputs = await asyncio.to_thread(self._closure_inputs, session)
        if inputs is None or not closure_eligible(session, inputs["mtime"], config, now,
                                                  automatic=automatic):
            return "skipped"
        old: Closure | None = inputs["old"]
        last = session.get("last_activity_at")
        if automatic:
            scanned = self._closure_scanned.get(sid)
            if (scanned and scanned[0] == inputs["cheap"]
                    and now - scanned[1] < GIT_RECHECK_SECONDS):
                return "skipped"
        git = await self._git_facts(session["cwd"])
        self._closure_scanned[sid] = (inputs["cheap"], now)
        stamp = fingerprint(inputs["cheap"], git)
        if automatic and old is not None and old.is_settled(
                stamp, last, now, config.interval_minutes * 60):
            return "skipped"
        transcript = await asyncio.to_thread(
            self._read_transcript, self._session_file(sid, inputs["directory"]))
        if transcript is None:
            return "skipped"
        tail = condense(tail_messages(transcript), transcript.tool_results, session["cwd"],
                        budget=TAIL_BUDGET).text
        prompt = build_closure_prompt(
            project=inputs["project"], title=session["title"], digest=inputs["digest"],
            plan=(inputs["plan_path"], inputs["plan"]) if inputs["plan_path"] and inputs["plan"]
            else None,
            git=git, resolved=inputs["resolved"], tail=tail,
        )
        request = DigestRequest(closure_system_prompt(config.extra_instructions), prompt,
                                config.model, config.effort, schema=CLOSURE_SCHEMA)
        # `now` is taken before the conversation is read, like `read_at` of the summary:
        # a message sent while the model answers makes the verdict stale.
        at = int(now)
        try:
            async with asyncio.timeout(self._session_timeout):
                raw = await self._model.summarize(request)
            verdict, actions, missing, evidence = apply_answer(raw, inputs["resolved"])
        except TimeoutError:
            return await self._closure_fail(sid, TIMEOUT_MESSAGE, last, at, stamp)
        except ClosureFormatError as error:
            return await self._closure_fail(sid, str(error), last, at, stamp)
        except DigestModelError as error:
            await self._closure_fail(sid, error.message, last, at, stamp)
            if error.stop_pass:
                if error.resets_at:
                    self._paused_until = float(error.resets_at)
                raise _StopPass(error.message) from error
            return error.message
        closure = Closure(sid, verdict=verdict, user_actions=actions, missing=missing,
                          evidence=evidence, resolved=list(inputs["resolved"]),
                          fingerprint=stamp, checked_at=at)
        if not await asyncio.to_thread(self._save_closure, closure):
            return "skipped"
        await self._closure_saved(closure, last)
        return "read"

    async def _closure_fail(self, sid: str, message: str, last: int | None,
                            at: int | None = None, stamp: str | None = None) -> str:
        when = int(self._clock()) if at is None else at

        def save() -> Closure | None:
            with closing(db.connect(self._db_path)) as conn:
                return closure_store.save_closure_error(conn, sid, message, when, stamp)

        closure = await asyncio.to_thread(save)
        if closure is not None:
            self._publish_closure(closure, last)
        return message

    def _save_closure(self, closure: Closure) -> bool:
        """Save a fresh check. An item the user marked done while the model was
        answering is read again here, so it is kept and does not come back."""
        try:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                current = closure_store.get_closure(conn, closure.session_id)
                known = {normalize(r) for r in closure.resolved}
                extra = [r for r in (current.resolved if current else [])
                         if normalize(r) not in known]
                if extra:
                    closure.resolved = [*closure.resolved, *extra]
                    done = {normalize(r) for r in closure.resolved}
                    closure.user_actions = [a for a in closure.user_actions
                                            if normalize(a) not in done]
                    if closure.verdict != "in_progress":
                        closure.verdict = decide(closure.user_actions, closure.missing,
                                                 closure.verdict or "can_close")
                closure_store.save_closure(conn, closure)
            return True
        except sqlite3.IntegrityError:
            return False

    async def run_closure_pass(self) -> dict[str, Any] | None:
        """Automatic scan. Logs a run (`auto_closure`) only when the model was called,
        something failed or the pass stopped."""
        if not (self._config.enabled and self._config.closure_auto):
            return None
        started = int(self._clock())
        read = skipped = 0
        errors: list[dict[str, Any]] = []
        stopped: str | None = None
        announced = False
        try:
            for session in self._manager.list_sessions():
                config = self._config  # read again: the switches may change during the scan
                if not (config.enabled and config.closure_auto):
                    break
                if self._pending_all or self._pending_sessions:
                    break  # a manual request goes first; the next tick resumes the scan
                try:
                    outcome = await self._check_closure(session, config, automatic=True)
                except _StopPass:
                    raise
                except Exception:
                    logger.exception("Unexpected error while checking session %s",
                                     session["session_id"])
                    outcome = await self._closure_fail(session["session_id"], UNEXPECTED,
                                                       session.get("last_activity_at"))
                if outcome == "ignored":
                    continue
                if outcome == "skipped":
                    skipped += 1
                    continue
                if not announced:
                    announced = True
                    self._running = True
                    self._publish_status()
                if outcome == "read":
                    read += 1
                else:
                    errors.append({"session_id": session["session_id"],
                                   "title": session["title"], "message": outcome})
        except _StopPass as stop:
            stopped = stop.message
            if self._paused_until is None or self._paused_until <= self._clock():
                # No reset time to wait for (login, CLI missing): do not hit the same
                # error every minute; go back to the pace of the summaries.
                self._closure_next_at = self._clock() + self._config.interval_minutes * 60
        finally:
            if announced or stopped:
                self._running = False
                self._publish_status()
        if not (read or errors or stopped):
            return None

        def log() -> dict[str, Any]:
            with closing(db.connect(self._db_path)) as conn:
                run_id = store.start_run(conn, "auto_closure", started)
                return store.finish_run(conn, run_id, at=int(self._clock()), read_count=read,
                                        skipped_count=skipped, errors=errors, stopped=stopped)

        return await asyncio.to_thread(log)

    async def resolve_closure_item(self, session_id: str, item: str) -> dict[str, Any]:
        """"Já fiz": the item leaves the actions and joins `resolved`; no model call."""
        wanted = normalize(item)

        def update() -> tuple[Closure, int | None]:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                closure = closure_store.get_closure(conn, session_id)
                row = conn.execute("SELECT last_activity_at FROM sessions WHERE session_id = ?",
                                   (session_id,)).fetchone()
                last = row["last_activity_at"] if row else None
                if closure is None or closure.is_stale(last):
                    raise ClosureItemNotFound(ITEM_NOT_FOUND)
                match = next((a for a in closure.user_actions if normalize(a) == wanted), None)
                if match is None:
                    raise ClosureItemNotFound(ITEM_NOT_FOUND)
                closure.user_actions = [a for a in closure.user_actions if a is not match]
                closure.resolved = [*closure.resolved, match]
                if closure.verdict != "in_progress":
                    closure.verdict = decide(closure.user_actions, closure.missing,
                                             closure.verdict or "can_close")
                closure_store.save_closure(conn, closure)
                return closure, last

        closure, last = await asyncio.to_thread(update)
        await self._closure_saved(closure, last)
        return closure.to_dict(last)

    def _session_summary(self, session_id: str) -> dict[str, Any] | None:
        return next((s for s in self._manager.list_sessions()
                     if s["session_id"] == session_id), None)

    # Deliveries ----------------------------------------------------------------

    def _publish_delivery(self, delivery: Delivery) -> None:
        self._publish({"session_id": None, "seq": 0, "type": "delivery.updated",
                       "data": delivery.to_dict()})

    def _last_uuid(self, session_id: str, directory: str) -> str | None:
        try:
            transcript = self._read_transcript(self._session_file(session_id, directory))
        except Exception:
            logger.exception("Falha ao ler o histórico da sessão %s", session_id)
            return None
        if transcript is None or not transcript.messages:
            return None
        return transcript.messages[-1].uuid

    def _create_delivery(self, session_id: str, finished_at: int) -> Delivery | None:
        """Blocking. None when the session is not in the index."""
        with closing(db.connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT s.project_id, s.cwd, s.title, s.history_dir, p.name AS project_name"
                " FROM sessions s LEFT JOIN projects p ON p.id = s.project_id"
                " WHERE s.session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        to_cursor = self._last_uuid(session_id, row["history_dir"] or row["cwd"])
        status = "pending" if self._config.enabled else "title_only"
        with closing(db.connect(self._db_path)) as conn:
            return deliveries.record_finish(
                conn, session_id=session_id, project_id=row["project_id"],
                project_name=row["project_name"] or "", title=row["title"] or UNTITLED,
                finished_at=finished_at, to_cursor=to_cursor, status=status)

    async def record_finish(self, session_id: str, finished_at: int) -> None:
        """Record the "Finalizar" click; with the agent on, queue its summary."""
        try:
            delivery = await asyncio.to_thread(self._create_delivery, session_id, finished_at)
        except Exception:
            logger.exception("Falha ao registrar a entrega da sessão %s", session_id)
            return
        if delivery is None:
            return
        self._publish_delivery(delivery)
        if delivery.status == "pending":
            self.request_delivery(delivery.id)

    def request_delivery(self, delivery_id: int) -> None:
        self._pending_deliveries[delivery_id] = None
        self._wake.set()

    async def resummarize(self, delivery_id: int) -> dict[str, Any]:
        def mark() -> Delivery:
            with closing(db.connect(self._db_path)) as conn:
                current = deliveries.get(conn, delivery_id)
                if current is None:
                    raise DeliveryNotFound()
                if not self._config.enabled:
                    raise DeliveryConflict(AGENT_OFF)
                if current.status == "pending":
                    raise DeliveryConflict(ALREADY_PENDING)
                marked = deliveries.mark_pending(conn, delivery_id, int(self._clock()))
                assert marked is not None
                return marked

        delivery = await asyncio.to_thread(mark)
        self._publish_delivery(delivery)
        self.request_delivery(delivery_id)
        return delivery.to_dict()

    async def recover_deliveries(self) -> None:
        """At startup: queue the records left pending, or settle them when the agent is off."""
        def settle() -> list[Delivery]:
            with closing(db.connect(self._db_path)) as conn:
                at = int(self._clock())
                return [d for i in deliveries.pending_ids(conn)
                        if (d := deliveries.mark_title_only(conn, i, at))]

        def pending() -> list[int]:
            with closing(db.connect(self._db_path)) as conn:
                return deliveries.pending_ids(conn)

        if self._config.enabled:
            for delivery_id in await asyncio.to_thread(pending):
                self.request_delivery(delivery_id)
        else:
            for delivery in await asyncio.to_thread(settle):
                self._publish_delivery(delivery)

    def _prepare_delivery(self, delivery_id: int) -> _DeliveryJob | None:
        """Blocking. None when the record is gone or no longer pending."""
        with closing(db.connect(self._db_path)) as conn:
            delivery = deliveries.get(conn, delivery_id)
            if delivery is None or delivery.status != "pending":
                return None
            row = None
            if delivery.session_id is not None:
                row = conn.execute("SELECT cwd, history_dir FROM sessions WHERE session_id = ?",
                                   (delivery.session_id,)).fetchone()
            digest = store.get_digest(conn, delivery.session_id) if row else None
        if row is None:
            return _DeliveryJob(delivery, None)
        transcript = self._read_transcript(
            self._session_file(delivery.session_id, row["history_dir"] or row["cwd"]))
        if transcript is None:
            return _DeliveryJob(delivery, None)
        piece = slice_between(transcript, delivery.from_cursor, delivery.to_cursor)
        condensed = condense(piece.messages, transcript.tool_results, row["cwd"])
        if condensed.count == 0:
            return _DeliveryJob(delivery, None)
        prompt = build_delivery_prompt(project=delivery.project_name, title=delivery.title,
                                       digest=digest, text=condensed.text,
                                       restarted=not piece.cursor_found)
        return _DeliveryJob(delivery, prompt)

    def _settle_delivery(self, read: Delivery, *, error: str | None = None,
                         summary: tuple[str, list[str]] | None = None) -> Delivery | None:
        """Blocking. Writes the outcome of the job that read `read`, but only if the record
        is still that very reading: pending, with the same `finished_at` and `to_cursor`.
        Finishing again renews the record (new cursor, back to pending) and queues it, so
        an outcome computed for the old reading is dropped: None, nothing published."""
        at = int(self._clock())
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            current = deliveries.get(conn, read.id)
            if (current is None or current.status != "pending"
                    or current.finished_at != read.finished_at
                    or current.to_cursor != read.to_cursor):
                return None
            if summary is not None:
                return deliveries.save_summary(conn, read.id, summary_title=summary[0],
                                               bullets=summary[1], at=at)
            if error is not None:
                return deliveries.mark_error(conn, read.id, error, at)
            return deliveries.mark_title_only(conn, read.id, at)

    def _fail_delivery(self, delivery_id: int, message: str) -> Delivery | None:
        """Blocking. Marks the record with an error, whatever its state (cancellation and
        unexpected failures, where the reading no longer matters)."""
        with closing(db.connect(self._db_path)) as conn:
            return deliveries.mark_error(conn, delivery_id, message, int(self._clock()))

    def _delivery_failed_now(self, delivery_id: int, message: str) -> None:
        """Synchronous, for the cancellation path."""
        try:
            delivery = self._fail_delivery(delivery_id, message)
            if delivery is not None:
                self._publish_delivery(delivery)
        except Exception:
            logger.exception("Could not record the error of delivery %s", delivery_id)

    async def _summarize_delivery(self, delivery_id: int) -> None:
        config = self._config
        job = await asyncio.to_thread(self._prepare_delivery, delivery_id)
        if job is None:
            return
        error: str | None = None
        summary: tuple[str, list[str]] | None = None
        if job.prompt is not None:
            request = DigestRequest(delivery_system_prompt(config.extra_instructions), job.prompt,
                                    config.model, config.effort, schema=DELIVERY_SCHEMA)
            try:
                async with asyncio.timeout(self._session_timeout):
                    result = await self._model.summarize(request)
                summary = clean_delivery(result)
            except TimeoutError:
                error = TIMEOUT_MESSAGE
            except DigestFormatError as exc:
                error = str(exc)
            except DigestModelError as exc:
                error = exc.message
                if exc.stop_pass and exc.resets_at:
                    self._paused_until = float(exc.resets_at)
        delivery = await asyncio.to_thread(self._settle_delivery, job.delivery,
                                           error=error, summary=summary)
        if delivery is not None:
            self._publish_delivery(delivery)

    async def run_deliveries(self, ids: list[int]) -> None:
        """Summarize the queued records one at a time. Cancelling (agent disabled)
        marks the current and the remaining ones with STOPPED_DISABLED; cancelling with the
        agent still on (the app shutting down) leaves them pending for the next start."""
        done: set[int] = set()
        try:
            for delivery_id in ids:
                try:
                    await self._summarize_delivery(delivery_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Unexpected error while summarizing delivery %s", delivery_id)
                    try:
                        delivery = await asyncio.to_thread(
                            self._fail_delivery, delivery_id, UNEXPECTED)
                    except Exception:
                        # The record stays pending (not queued again: with the database
                        # refusing writes it would call the model on every turn);
                        # `recover_deliveries` picks it up at the next start. Go on with the batch.
                        logger.exception("Could not record the error of delivery %s", delivery_id)
                    else:
                        if delivery is not None:
                            self._publish_delivery(delivery)
                done.add(delivery_id)
        except asyncio.CancelledError:
            if not self._config.enabled:
                for delivery_id in ids:
                    if delivery_id not in done:
                        self._delivery_failed_now(delivery_id, STOPPED_DISABLED)
            raise

    async def _stop_queued_deliveries(self) -> None:
        """The agent was turned off after these records were queued (e.g. while the click
        was being recorded): settle them without calling the model."""
        queued = list(self._pending_deliveries)
        self._pending_deliveries.clear()

        def settle() -> list[Delivery]:
            with closing(db.connect(self._db_path)) as conn:
                at = int(self._clock())
                return [d for i in queued
                        if (d := deliveries.mark_error(conn, i, STOPPED_DISABLED, at))]

        for delivery in await asyncio.to_thread(settle):
            self._publish_delivery(delivery)

    # Scheduler -----------------------------------------------------------------

    def start_schedule(self) -> None:
        """The first automatic pass waits a whole interval."""
        self._next_run_at = (
            self._clock() + self._config.interval_minutes * 60 if self._config.enabled else None
        )
        self._closure_next_at = self._clock() + SCAN_INTERVAL if self._config.enabled else None

    def request_all(self) -> None:
        self._pending_all = True
        self._wake.set()

    def request_session(self, session_id: str) -> None:
        self._pending_sessions[session_id] = None
        self._wake.set()

    async def update_config(self, config: DigestConfig) -> None:
        """Save, reschedule and publish. Disabling cancels the pass in progress."""
        from claudio_maestro.digest.config import save_config

        def save() -> None:
            with closing(db.connect(self._db_path)) as conn:
                save_config(conn, config)

        await asyncio.to_thread(save)
        previous = self._config
        self._config = config
        if not config.enabled:
            self._next_run_at = None
            self._closure_next_at = None
            queued = list(self._pending_deliveries)
            self._pending_deliveries.clear()
            for delivery_id in queued:
                self._delivery_failed_now(delivery_id, STOPPED_DISABLED)
            if previous.enabled and self._current is not None:
                self._current.cancel()
        elif not previous.enabled or previous.interval_minutes != config.interval_minutes:
            self.start_schedule()
        self._publish_status()
        self._wake.set()

    def _due_at(self) -> float | None:
        if not self._config.enabled or self._next_run_at is None:
            return None
        if self._paused_until is not None and self._paused_until > self._next_run_at:
            return self._paused_until
        return self._next_run_at

    def _closure_due_at(self) -> float | None:
        if not (self._config.enabled and self._config.closure_auto):
            return None
        if self._closure_next_at is None:
            return None
        if self._paused_until is not None and self._paused_until > self._closure_next_at:
            return self._paused_until
        return self._closure_next_at

    async def _run_child(self, trigger: str, session_ids: list[str] | None = None,
                         ids: list[int] | None = None) -> None:
        """Run a pass as a child task, so disabling the agent cancels only the pass."""
        if trigger == "auto_closure":
            coroutine = self.run_closure_pass()
        elif trigger == "deliveries":
            coroutine = self.run_deliveries(ids or [])
        else:
            coroutine = self.run_pass(trigger, session_ids)
        task = asyncio.create_task(coroutine)
        self._current = task
        try:
            await asyncio.wait({task})
            if not task.cancelled():
                task.result()  # a failure of the pass surfaces here, to be logged by `run`
        finally:
            if not task.done():  # the loop itself is being cancelled
                task.cancel()
                # Wait for the pass to close its run (it logs `stopped` while unwinding).
                await asyncio.gather(task, return_exceptions=True)
            self._current = None

    async def tick(self) -> None:
        """Do what is pending or due, one pass at a time."""
        if self._pending_all:
            self._pending_all = False
            await self._run_child("manual_all")
        if self._pending_sessions:
            ids = list(self._pending_sessions)
            self._pending_sessions.clear()
            await self._run_child("manual_session", ids)
        if self._pending_deliveries:
            if not self._config.enabled:
                await self._stop_queued_deliveries()
            else:
                delivery_ids = list(self._pending_deliveries)
                self._pending_deliveries.clear()
                await self._run_child("deliveries", ids=delivery_ids)
        due = self._due_at()
        now = self._clock()
        if due is not None and now >= due:
            if self._paused_until is not None and now >= self._paused_until:
                self._paused_until = None
            self._next_run_at = now + self._config.interval_minutes * 60
            await self._run_child("auto")
        closure_due = self._closure_due_at()
        now = self._clock()
        if closure_due is not None and now >= closure_due:
            if self._paused_until is not None and now >= self._paused_until:
                self._paused_until = None
            self._closure_next_at = now + SCAN_INTERVAL
            await self._run_child("auto_closure")

    async def _wait(self) -> None:
        if self._pending_all or self._pending_sessions or self._pending_deliveries:
            return
        due = self._due_at()
        dues = [d for d in (due, self._closure_due_at()) if d is not None]
        timeout = max(min(dues) - self._clock(), 0) if dues else None
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
        except TimeoutError:
            pass

    async def run(self) -> None:
        """Scheduler loop, started with the app."""
        try:
            await asyncio.to_thread(self.load)
        except Exception:
            logger.exception("Não foi possível ler a configuração do agente de resumos")
        try:
            await self.recover_deliveries()
        except Exception:
            logger.exception("Não foi possível retomar as entregas pendentes")
        self.start_schedule()
        self._publish_status()
        while True:
            await self._wait()
            try:
                await self.tick()
            except Exception:
                logger.exception("Falha no agente de resumos")
