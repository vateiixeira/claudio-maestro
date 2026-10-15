"""The full-text index of the conversations (`textindex.py`)."""

import asyncio
import json
import os
import sqlite3
import stat
import time
from contextlib import closing, suppress
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textindex_helpers import append, assistant, user, write

from claudio_maestro import db
from claudio_maestro.textindex import (
    SCHEMA_VERSION,
    TextIndex,
    build_match,
    normalize_term,
)


class Env:
    """A main database with sessions, their transcript files and an index over them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.db_path = root / "maestro.db"
        self.index_path = root / "data" / "search.db"
        self.files: dict[str, Path] = {}
        db.init_db(self.db_path)
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO projects (name, path, color, position, created_at)"
                " VALUES ('p', ?, '#ff8800', 0, 0)",
                (str(root / "proj"),),
            )
        self.index = TextIndex(
            self.db_path, self.index_path, session_file=lambda sid, directory: self.files.get(sid)
        )

    def register(self, session_id: str, path: Path) -> None:
        self.files[session_id] = path
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at) VALUES (?, 1, ?, ?, 0, 0)",
                (session_id, str(self.root / "proj"), session_id),
            )

    def add(self, session_id: str, entries: list[dict] | None = None) -> Path:
        path = self.root / f"{session_id}.jsonl"
        write(path, entries or [])
        self.register(session_id, path)
        return path

    def rows(self) -> list[tuple[str, str]]:
        if not self.index_path.exists():
            return []
        with closing(sqlite3.connect(self.index_path)) as conn:
            try:
                return conn.execute("SELECT session_id, text FROM messages ORDER BY rowid").fetchall()
            except sqlite3.OperationalError:
                return []

    def texts(self) -> list[str]:
        return [text for _, text in self.rows()]


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# What goes into the index -------------------------------------------------------


def test_indexes_the_text_of_user_and_assistant_messages(env):
    env.add("s1", [user("Como configuro a jornada?"), assistant("Na jornada do funil você monta uma regra")])

    env.index.refresh()

    assert env.rows() == [
        ("s1", "Como configuro a jornada?"),
        ("s1", "Na jornada do funil você monta uma regra"),
    ]


def test_ignores_what_the_chat_does_not_show(env):
    env.add(
        "s1",
        [
            user("meta", isMeta=True),
            user("de lado", isSidechain=True),
            user("resumo da compactação", isCompactSummary=True),
            user("<system-reminder>lembrete</system-reminder>"),
            user("<local-command-stdout>saída</local-command-stdout>"),
            user("<task-notification>fim</task-notification>"),
            user([{"type": "tool_result", "tool_use_id": "t", "content": "resultado"}], uuid="u9"),
            user([{"type": "image", "source": {}}], uuid="u10"),
            {
                "type": "assistant", "uuid": "a2",
                "message": {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "pensando"},
                    {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "ls"}},
                ]},
            },
            {"type": "system", "uuid": "x", "message": {"content": "sistema"}},
            user("fica"),
        ],
    )

    env.index.refresh()

    assert env.rows() == [("s1", "fica")]


def test_joins_the_text_blocks_of_one_message(env):
    env.add(
        "s1",
        [
            user([{"type": "text", "text": "primeiro"}, {"type": "text", "text": "segundo"}]),
            {
                "type": "assistant", "uuid": "a1",
                "message": {"role": "assistant", "content": [
                    {"type": "text", "text": "um"}, {"type": "tool_use", "id": "t", "name": "X", "input": {}},
                    {"type": "text", "text": "dois"},
                ]},
            },
        ],
    )

    env.index.refresh()

    assert env.texts() == ["primeiro segundo", "um dois"]


def test_a_very_long_message_is_cut(env):
    env.add("s1", [assistant("x" * 150_000)])

    env.index.refresh()

    assert len(env.texts()[0]) == 100_000


def test_keeps_the_uuid_and_the_time_of_the_message(env):
    env.add("s1", [assistant("oi tudo bem", uuid="abc")])

    env.index.refresh()

    with closing(sqlite3.connect(env.index_path)) as conn:
        assert conn.execute("SELECT uuid, at FROM messages").fetchall() == [
            ("abc", int(datetime(2026, 10, 14, 20, 41, 40, tzinfo=UTC).timestamp()))
        ]


def test_whitespace_is_collapsed_so_a_phrase_crosses_line_breaks(env):
    env.add("s1", [assistant("Na jornada do funil\n\n  você\tmonta uma regra")])

    env.index.refresh()

    assert env.texts() == ["Na jornada do funil você monta uma regra"]
    assert set(env.index.matching("funil você")) == {"s1"}
    assert set(env.index.matching("do funil\nvocê")) == {"s1"}
    assert last_text(env, "funil você") == "Na jornada do funil você monta uma regra"


def test_an_invalid_line_in_the_middle_is_skipped(env):
    path = env.add("s1", [user("antes")])
    with path.open("a", encoding="utf-8") as file:
        file.write("{isto nao e json\n")
    append(path, [assistant("depois")])

    env.index.refresh()

    assert env.texts() == ["antes", "depois"]


def test_a_line_over_the_limit_is_skipped_and_the_next_ones_are_read(env, monkeypatch):
    monkeypatch.setattr("claudio_maestro.textindex.MAX_LINE_BYTES", 200)
    path = env.add("s1", [user("antes")])
    append(path, [assistant("y" * 500), assistant("depois", uuid="a2")])

    env.index.refresh()
    env.index.refresh()

    assert env.texts() == ["antes", "depois"]


# Keeping it up to date ------------------------------------------------------------


def test_appended_lines_are_indexed_once(env):
    path = env.add("s1", [user("primeira")])
    env.index.refresh()

    append(path, [assistant("segunda")])
    env.index.refresh()
    env.index.refresh()

    assert env.texts() == ["primeira", "segunda"]


def test_a_line_still_being_written_waits_for_the_next_pass(env):
    path = env.add("s1", [user("completa")])
    half = json.dumps(assistant("pela metade"), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as file:
        file.write(half[:20])

    env.index.refresh()
    assert env.texts() == ["completa"]

    with path.open("a", encoding="utf-8") as file:
        file.write(half[20:] + "\n")
    env.index.refresh()

    assert env.texts() == ["completa", "pela metade"]


def test_a_file_that_shrank_is_indexed_again_from_the_start(env):
    path = env.add("s1", [user("um dois três quatro cinco seis"), assistant("sete oito nove")])
    env.index.refresh()

    write(path, [user("novo")])
    env.index.refresh()

    assert env.rows() == [("s1", "novo")]


def test_a_replaced_file_is_indexed_again_from_the_start(env):
    path = env.add("s1", [user("antigo")])
    env.index.refresh()

    replacement = path.with_name("novo.jsonl")
    write(replacement, [user("muito mais novo que o antigo"), assistant("outra")])
    os.replace(replacement, path)
    env.index.refresh()

    assert env.texts() == ["muito mais novo que o antigo", "outra"]


def test_a_session_gone_from_the_database_leaves_the_index(env):
    env.add("s1", [user("um")])
    env.add("s2", [user("dois")])
    env.index.refresh()

    with closing(db.connect(env.db_path)) as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    env.index.refresh()

    assert env.rows() == [("s2", "dois")]


def test_a_missing_file_takes_its_rows_away(env):
    path = env.add("s1", [user("um")])
    env.index.refresh()

    path.unlink()
    env.index.refresh()

    assert env.rows() == []


def test_a_symlink_is_not_followed(env, tmp_path):
    real = tmp_path / "real.jsonl"
    write(real, [user("segredo")])
    link = tmp_path / "s1.jsonl"
    link.symlink_to(real)
    env.register("s1", link)

    env.index.refresh()

    assert env.rows() == []


def test_an_error_in_one_session_does_not_stop_the_others(env):
    env.add("s1", [user("um")])
    env.add("s2", [user("dois")])

    def finder(session_id, directory):
        if session_id == "s1":
            raise RuntimeError("falha de teste")
        return env.files[session_id]

    env.index._session_file = finder
    env.index.refresh()

    assert env.rows() == [("s2", "dois")]


# The file ---------------------------------------------------------------------------


def test_the_file_is_private(env):
    env.add("s1", [user("um")])

    env.index.refresh()

    assert stat.S_IMODE(env.index_path.stat().st_mode) == 0o600


def test_a_different_schema_version_rebuilds_the_file(env):
    env.add("s1", [user("um")])
    env.index.refresh()
    with closing(sqlite3.connect(env.index_path)) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    env.index.refresh()

    with closing(sqlite3.connect(env.index_path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert env.rows() == [("s1", "um")]


def test_a_corrupted_file_is_rebuilt(env):
    env.add("s1", [user("um")])
    env.index_path.parent.mkdir(parents=True, exist_ok=True)
    env.index_path.write_bytes(b"isto nao e um banco sqlite" * 100)

    env.index.refresh()

    assert env.rows() == [("s1", "um")]


def test_without_the_tokenizer_the_index_turns_itself_off(env, monkeypatch, caplog):
    monkeypatch.setattr(
        "claudio_maestro.textindex._MESSAGES_SQL",
        "CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5(text, tokenize = 'nao_existe')",
    )
    env.add("s1", [user("jornada do funil")])

    with caplog.at_level("WARNING"):
        env.index.refresh()
        env.index.refresh()

    assert env.index.available is False
    assert env.index.matching("jornada") == {}
    assert len([r for r in caplog.records if "desligada" in r.getMessage()]) == 1


def test_a_damaged_file_in_the_middle_of_a_pass_is_rebuilt(env, caplog):
    env.add("s1", [user("um")])
    env.index.refresh()
    env.add("s2", [user("dois")])
    calls = {"n": 0}
    real = env.index._session_file

    def finder(session_id, directory):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.DatabaseError("database disk image is malformed")
        return real(session_id, directory)

    env.index._session_file = finder
    with caplog.at_level("WARNING"):
        env.index.refresh()

    assert env.rows() == [("s1", "um"), ("s2", "dois")]
    assert any("refeito" in r.getMessage() for r in caplog.records)


def test_a_real_corruption_found_while_writing_rebuilds_the_file(env):
    env.add("s1", [user("um")])
    env.index.refresh()
    with closing(sqlite3.connect(env.index_path)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # Breaks the pages after the header: the file still opens, the writes then fail.
    size = env.index_path.stat().st_size
    with env.index_path.open("r+b") as file:
        file.seek(4096)
        file.write(b"\xff" * (size - 4096))
    env.add("s2", [user("dois")])

    with suppress(sqlite3.DatabaseError):
        env.index.refresh()
    env.index.refresh()

    assert env.rows() == [("s1", "um"), ("s2", "dois")]


def test_a_lock_is_not_a_reason_to_rebuild(env):
    env.add("s1", [user("um")])
    env.index.refresh()
    inode = env.index_path.stat().st_ino

    def finder(session_id, directory):
        raise sqlite3.OperationalError("database is locked")

    env.index._session_file = finder
    env.index.refresh()

    assert env.index_path.stat().st_ino == inode
    assert env.rows() == [("s1", "um")]


def test_an_existing_file_with_open_permissions_becomes_private(env):
    env.add("s1", [user("um")])
    env.index.refresh()
    env.index_path.chmod(0o644)

    env.index.refresh()

    assert stat.S_IMODE(env.index_path.stat().st_mode) == 0o600


# Searching -------------------------------------------------------------------------


def last_text(env: Env, term: str, session_id: str = "s1") -> str:
    rowid = env.index.matching(term)[session_id]
    match = env.index.match_for(term, rowid)
    assert match is not None
    return "".join(part.text for part in match.parts)


def test_matching_ignores_case_and_accents_and_finds_inside_words(env):
    env.add("s1", [assistant("A configuração do funil ficou pronta")])
    env.add("s2", [assistant("Nada relacionado")])
    env.index.refresh()

    assert set(env.index.matching("CONFIGURACAO")) == {"s1"}
    assert set(env.index.matching("figuração do fu")) == {"s1"}
    assert set(env.index.matching("  configuracao   do ")) == {"s1"}


def test_searching_before_any_pass_finds_nothing_and_creates_no_file(env):
    assert env.index.matching("jornada") == {}
    assert env.index.match_for("jornada", 1) is None
    assert not env.index_path.exists()


def test_searching_never_writes_to_the_file(env):
    env.add("s1", [assistant("a jornada do funil")])
    env.index.refresh()
    before = env.index_path.stat().st_mtime_ns

    assert set(env.index.matching("jornada")) == {"s1"}
    assert env.index.match_for("jornada", 1) is not None

    assert env.index_path.stat().st_mtime_ns == before


def test_a_path_with_special_characters_can_be_searched(tmp_path):
    odd = tmp_path / "pasta com ? e # e %"
    env = Env(odd.mkdir() or odd)
    env.add("s1", [assistant("a jornada do funil")])
    env.index.refresh()

    assert set(env.index.matching("jornada")) == {"s1"}


def test_matching_needs_three_characters(env):
    env.add("s1", [assistant("abc def")])
    env.index.refresh()

    assert env.index.matching("ab") == {}
    assert env.index.matching("  a ") == {}
    assert env.index.matching("") == {}
    assert set(env.index.matching("abc")) == {"s1"}


def test_search_operators_and_quotes_are_plain_text(env):
    env.add("s1", [assistant('ele disse "olá" OR NEAR(a b) e fim')])
    env.index.refresh()

    assert set(env.index.matching('"olá" OR')) == {"s1"}
    assert set(env.index.matching("NEAR(a b)")) == {"s1"}
    assert env.index.matching("olá OR zzz") == {}
    assert env.index.matching("disse*") == {}
    assert env.index.matching('a" OR "b') == {}


def test_matching_points_at_the_last_message_with_the_term(env):
    env.add("s1", [user("falamos de funil"), assistant("resposta sobre funil"), user("outra coisa")])
    env.index.refresh()

    assert last_text(env, "funil") == "resposta sobre funil"


def test_match_for_carries_the_time_of_the_message(env):
    env.add("s1", [assistant("o funil converte")])
    env.index.refresh()

    rowid = env.index.matching("funil")["s1"]

    assert env.index.match_for("funil", rowid).at == int(
        datetime(2026, 10, 14, 20, 41, 40, tzinfo=UTC).timestamp()
    )
    assert env.index.match_for("funil", rowid + 100) is None


# The snippet -------------------------------------------------------------------------


def parts(match):
    return [(p.text, p.hit) for p in match.parts]


def test_build_match_marks_the_hit_and_keeps_the_original_text():
    match = build_match("Na jornada do funil você monta uma regra assim", "JORNADA", at=7)

    assert match.at == 7
    assert parts(match) == [
        ("Na ", False), ("jornada", True), (" do funil você monta uma regra assim", False),
    ]


def test_build_match_ignores_accents_of_the_text_and_not_of_the_term():
    match = build_match("A configuração ficou pronta", "configuracao", at=None)

    assert [text for text, hit in parts(match) if hit] == ["configuração"]


def test_build_match_uses_the_last_occurrence():
    match = build_match("funil aqui e funil ali", "funil", at=None)

    assert parts(match) == [("funil aqui e ", False), ("funil", True), (" ali", False)]


def test_build_match_cuts_long_text_on_word_boundaries_with_ellipsis():
    text = "palavra " * 40 + "ALVO" + " resto" * 60

    first, hit, last = build_match(text, "alvo", at=None).parts

    assert first.text == "…" + "palavra " * 10
    assert (hit.text, hit.hit) == ("ALVO", True)
    assert last.text == " resto" * 20 + "…"


def test_build_match_has_no_line_breaks():
    match = build_match("linha um\nlinha dois com ALVO\n\nfim", "alvo", at=None)

    assert all("\n" not in part.text for part in match.parts)
    assert parts(match)[0] == ("linha um linha dois com ", False)


def test_build_match_without_the_term_shows_the_start():
    assert parts(build_match("texto sem o termo", "zzz", at=None)) == [("texto sem o termo", False)]


def test_normalize_term_collapses_spaces_and_drops_accents():
    assert normalize_term("  Ação   Rápida ") == "acao rapida"


# Running it ---------------------------------------------------------------------------


async def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condição não atendida a tempo"
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_kick_runs_a_pass_without_waiting_for_the_interval(env):
    env.add("s1", [user("um")])
    task = asyncio.create_task(env.index.run_periodic(3600))
    try:
        await wait_for(lambda: env.rows() == [("s1", "um")])

        env.add("s2", [user("dois")])
        env.index.kick()

        await wait_for(lambda: ("s2", "dois") in env.rows())
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
