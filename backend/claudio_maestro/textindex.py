"""Full-text index of the conversations, in a file of its own (`search.db`).

A disposable cache: it keeps the text of the user and assistant messages of every session the
app knows, read from the CLI history files, and can be deleted at any time; the next pass builds
it again. The main database keeps only metadata.
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from claudio_maestro import db, history
from claudio_maestro.conversation import classify_user_text

logger = logging.getLogger(__name__)

INDEX_FILENAME = "search.db"
SCHEMA_VERSION = 1
# The trigram tokenizer finds nothing shorter than this.
MIN_TERM_LENGTH = 3
# Characters kept of one message.
MAX_TEXT = 100_000
# A longer line is a pasted dump, not a message: it is skipped.
MAX_LINE_BYTES = 16 * 1024 * 1024
CONTEXT_BEFORE = 80
CONTEXT_AFTER = 120

SessionFile = Callable[[str, str], Path | None]

_FILES_SQL = """
CREATE TABLE IF NOT EXISTS files (
  session_id TEXT PRIMARY KEY,
  inode      INTEGER NOT NULL,
  size       INTEGER NOT NULL,
  mtime_ns   INTEGER NOT NULL,
  consumed   INTEGER NOT NULL
)
"""
_MESSAGES_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5(
  text,
  session_id UNINDEXED,
  uuid       UNINDEXED,
  at         UNINDEXED,
  tokenize = 'trigram remove_diacritics 1'
)
"""


@dataclass(frozen=True)
class MatchPart:
    text: str
    hit: bool


@dataclass(frozen=True)
class Match:
    parts: list[MatchPart]
    at: int | None = None


class TextIndexUnavailable(Exception):
    """This SQLite has no FTS5 or no trigram tokenizer."""


# Text -------------------------------------------------------------------------------


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """`text` without accents or case and with each run of whitespace as one space, and for
    each character of the result the index of the character of `text` it came from."""
    out: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                positions.append(index)
            continue
        for piece in unicodedata.normalize("NFD", char.lower()):
            if not unicodedata.combining(piece):
                out.append(piece)
                positions.append(index)
    return "".join(out), positions


def normalize_term(term: str) -> str:
    return normalize_with_map(term)[0].strip()


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _is_corrupt(exc: sqlite3.Error) -> bool:
    """The file is damaged (SQLITE_CORRUPT or SQLITE_NOTADB, with or without extended bits).
    Anything else (lock, full disk, I/O error, constraint) says nothing about the file."""
    code = getattr(exc, "sqlite_errorcode", None)
    return code is not None and code & 0xFF in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)


class _OldSchema(sqlite3.DatabaseError):
    """The file was written by another version of the index."""


def build_match(text: str, term: str, at: int | None) -> Match:
    """The snippet of `text` around the last occurrence of `term`, as parts (the hit apart)."""
    needle = normalize_term(term)
    normalized, positions = normalize_with_map(text)
    start = normalized.rfind(needle) if needle else -1
    if start < 0:
        head = _flat(text[: CONTEXT_BEFORE + CONTEXT_AFTER]).strip()
        more = "…" if len(text) > CONTEXT_BEFORE + CONTEXT_AFTER else ""
        return Match([MatchPart(head + more, False)] if head else [], at)
    first = positions[start]
    last = positions[start + len(needle) - 1] + 1
    while last < len(text) and unicodedata.combining(text[last]):
        last += 1
    left = max(0, first - CONTEXT_BEFORE)
    while 0 < left < first and not text[left - 1].isspace():
        left += 1
    right = min(len(text), last + CONTEXT_AFTER)
    while last < right < len(text) and not text[right].isspace():
        right -= 1
    pieces = [
        MatchPart(("…" if left > 0 else "") + _flat(text[left:first]).lstrip(), False),
        MatchPart(_flat(text[first:last]), True),
        MatchPart(_flat(text[last:right]).rstrip() + ("…" if right < len(text) else ""), False),
    ]
    return Match([piece for piece in pieces if piece.text], at)


def extract_text(entry: Any) -> str:
    """What a transcript entry says to the reader ('' when it says nothing searchable)."""
    if not isinstance(entry, dict) or entry.get("type") not in ("user", "assistant"):
        return ""
    if entry.get("isMeta") or entry.get("isSidechain") or entry.get("isCompactSummary"):
        return ""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        raw = block.get("text")
        if not isinstance(raw, str):
            continue
        if entry["type"] == "user":
            raw, _notice = classify_user_text(raw)
        if raw.strip():
            texts.append(raw)
    # Whitespace runs become one space, as in the search term: a phrase crosses line breaks.
    text = _flat("\n".join(texts)).strip()[:MAX_TEXT]
    # A loose surrogate (invalid UTF-16 in the JSON) would make SQLite refuse the whole batch.
    return text.encode("utf-8", "replace").decode("utf-8")


def _read_messages(
    file: BinaryIO, start: int
) -> tuple[list[tuple[str, str | None, int | None]], int]:
    """(text, uuid, at) of the searchable lines from byte `start`, and the offset right after the
    last complete line (a last line without `\\n` may still be being written)."""
    file.seek(start)
    consumed = start
    rows: list[tuple[str, str | None, int | None]] = []
    for raw in file:
        if not raw.endswith(b"\n"):
            break
        consumed += len(raw)
        if len(raw) > MAX_LINE_BYTES:
            continue
        try:
            entry = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        text = extract_text(entry)
        if not text:
            continue
        uuid = entry.get("uuid")
        rows.append(
            (text, uuid if isinstance(uuid, str) else None, history._epoch_seconds(entry.get("timestamp")))
        )
    return rows, consumed


def _phrase(term: str) -> str:
    """The term as one FTS5 phrase: with the trigram tokenizer, "contains this text"."""
    return '"' + " ".join(term.split()).replace('"', '""') + '"'


# The index --------------------------------------------------------------------------


class TextIndex:
    def __init__(
        self, db_path: Path, index_path: Path, session_file: SessionFile | None = None
    ) -> None:
        self._db_path = db_path
        self._path = index_path
        self._session_file = session_file
        # One pass at a time; searches use their own connections and never wait for it.
        self._lock = threading.Lock()
        self._disabled = False
        self._wake = asyncio.Event()

    @property
    def available(self) -> bool:
        return not self._disabled

    # File ---------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            # Private from the first byte: the file holds the text of the conversations.
            os.close(os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600))
        conn = sqlite3.connect(self._path, timeout=5, isolation_level=None, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except BaseException:
            conn.close()
            raise
        self._make_private()
        return conn

    def _make_private(self) -> None:
        """The file holds the text of the conversations: whatever its mode was, it is 0600."""
        for suffix in ("", "-wal", "-shm"):
            with suppress(OSError):
                os.chmod(str(self._path) + suffix, 0o600)

    def _create(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute(_FILES_SQL)
            conn.execute(_MESSAGES_SQL)
        except sqlite3.OperationalError as exc:
            if any(word in str(exc).lower() for word in ("tokenizer", "fts5", "module")):
                raise TextIndexUnavailable(str(exc)) from exc
            raise
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _open_current(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self._create(conn)
            elif version != SCHEMA_VERSION:
                raise _OldSchema(f"esquema {version}, esperado {SCHEMA_VERSION}")
            conn.execute("SELECT COUNT(*) FROM files").fetchone()  # a damaged file fails here
            return conn
        except BaseException:
            conn.close()
            raise

    def _reset(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self._path) + suffix).unlink(missing_ok=True)

    def _ensure(self) -> sqlite3.Connection | None:
        """A connection to a file with the current schema, building the file again when it is
        damaged or old; None when this SQLite cannot hold the index."""
        if self._disabled:
            return None
        for attempt in (1, 2):
            try:
                return self._open_current()
            except TextIndexUnavailable as exc:
                self._disabled = True
                logger.warning("Busca no conteúdo das conversas desligada: %s", exc)
                return None
            except sqlite3.DatabaseError as exc:
                if not (_is_corrupt(exc) or isinstance(exc, _OldSchema)) or attempt == 2:
                    raise
                logger.warning("O índice de busca será refeito.", exc_info=True)
                self._reset()
        return None

    # Updating ---------------------------------------------------------------------

    def _sessions(self) -> list[tuple[str, str]]:
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT session_id, COALESCE(NULLIF(history_dir, ''), cwd) FROM sessions"
                # No file registered yet: nothing to read, and looking it up is not free.
                " WHERE file_modified_at IS NOT NULL"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def refresh(self) -> None:
        """One pass over every session of the main database. Blocking: run it in a thread.
        A file found damaged, at any point of the pass, is deleted and built again."""
        with self._lock:
            # Read first: a problem in the main database only aborts the pass and never
            # touches the index.
            try:
                sessions = self._sessions()
            except Exception:
                logger.exception("Não foi possível ler as sessões para o índice de busca")
                return
            for attempt in (1, 2):
                try:
                    self._pass(sessions)
                    return
                except sqlite3.DatabaseError as exc:
                    if not _is_corrupt(exc):
                        raise
                    logger.warning("O índice de busca será refeito.", exc_info=True)
                    self._reset()
                    if attempt == 2:
                        raise

    def _pass(self, sessions: list[tuple[str, str]]) -> None:
        conn = self._ensure()
        if conn is None:
            return
        with closing(conn):
            known = {
                row[0]: tuple(row[1:])
                for row in conn.execute(
                    "SELECT session_id, inode, size, mtime_ns, consumed FROM files"
                )
            }
            current: set[str] = set()
            for session_id, directory in sessions:
                current.add(session_id)
                try:
                    self._refresh_session(conn, session_id, directory, known.get(session_id))
                except sqlite3.DatabaseError as exc:
                    if _is_corrupt(exc):
                        raise
                    logger.exception("Falha ao indexar a sessão %s", session_id)
                except Exception:
                    logger.exception("Falha ao indexar a sessão %s", session_id)
            for session_id in known.keys() - current:
                self._drop(conn, session_id)

    def _drop(self, conn: sqlite3.Connection, session_id: str) -> None:
        with db.transaction(conn):
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM files WHERE session_id = ?", (session_id,))

    def _refresh_session(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        directory: str,
        known: tuple[int, int, int, int] | None,
    ) -> None:
        finder = self._session_file or history.sdk_session_file
        path = finder(session_id, directory)
        fd = history._open_regular(path) if path is not None else None
        if fd is None:
            if known is not None:
                self._drop(conn, session_id)
            return
        with os.fdopen(fd, "rb") as file:
            info = os.fstat(file.fileno())
            state = (info.st_ino, info.st_size, info.st_mtime_ns)
            if known is not None and known[:3] == state:
                return
            # The CLI only appends: a different file, or a smaller one, is read from the start.
            rebuild = known is None or known[0] != info.st_ino or info.st_size < known[3]
            rows, consumed = _read_messages(file, 0 if rebuild or known is None else known[3])
        with db.transaction(conn):
            if known is not None and rebuild:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.executemany(
                "INSERT INTO messages(text, session_id, uuid, at) VALUES (?, ?, ?, ?)",
                [(text, session_id, uuid, at) for text, uuid, at in rows],
            )
            conn.execute(
                "INSERT OR REPLACE INTO files(session_id, inode, size, mtime_ns, consumed)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, *state, consumed),
            )

    async def run_periodic(self, interval: float) -> None:
        """A pass now, then one every `interval` seconds or as soon as `kick()` is called."""
        while True:
            try:
                await asyncio.to_thread(self.refresh)
            except Exception:
                logger.exception("Falha ao atualizar o índice de busca")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except TimeoutError:
                pass
            self._wake.clear()

    def kick(self) -> None:
        """Ask for a pass now. Call it from the event loop."""
        self._wake.set()

    # Searching --------------------------------------------------------------------

    def _open_for_search(self) -> sqlite3.Connection | None:
        if self._disabled or not self._path.exists():
            return None
        # Read-only: a search never creates the file (the umask would leave it open to others).
        uri = self._path.resolve().as_uri() + "?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=2, check_same_thread=False)

    def matching(self, query: str) -> dict[str, int]:
        """session id -> rowid of the last message with `query`, for every session that has one.
        Empty for a term shorter than MIN_TERM_LENGTH or when the index is not there."""
        term = " ".join(query.split())
        if len(normalize_term(term)) < MIN_TERM_LENGTH:
            return {}
        conn = self._open_for_search()
        if conn is None:
            return {}
        with closing(conn):
            try:
                rows = conn.execute(
                    "SELECT session_id, MAX(rowid) FROM messages WHERE messages MATCH ?"
                    " GROUP BY session_id",
                    (_phrase(term),),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc):  # the first pass has not built it yet
                    return {}
                raise
        return {session_id: rowid for session_id, rowid in rows}

    def match_for(self, query: str, rowid: int) -> Match | None:
        """The snippet of the message `rowid` (from `matching`) around `query`."""
        conn = self._open_for_search()
        if conn is None:
            return None
        with closing(conn):
            try:
                row = conn.execute(
                    "SELECT text, at FROM messages WHERE rowid = ?", (rowid,)
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc):
                    return None
                raise
        return None if row is None else build_match(row[0], query, row[1])
