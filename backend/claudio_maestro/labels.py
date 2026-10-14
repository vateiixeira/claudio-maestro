"""Labels: a global catalog of slug + hex color, applied to sessions. Only the app knows them."""

import re
import sqlite3
import time
from dataclasses import dataclass

from claudio_maestro.db import transaction

SLUG_MAX = 32
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_COLOR = re.compile(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})")


@dataclass(frozen=True)
class Label:
    id: int
    slug: str
    color: str
    created_at: int


class LabelError(Exception):
    """Base error. The message is shown to the user."""


class LabelNotFoundError(LabelError):
    pass


class InvalidLabelError(LabelError):
    pass


class DuplicateLabelError(LabelError):
    pass


_COLUMNS = "id, slug, color, created_at"


def _from_row(row: sqlite3.Row) -> Label:
    return Label(id=row["id"], slug=row["slug"], color=row["color"], created_at=row["created_at"])


def clean_slug(slug: str) -> str:
    cleaned = slug.strip().lower()
    if not cleaned:
        raise InvalidLabelError("Dê um slug à etiqueta.")
    if len(cleaned) > SLUG_MAX:
        raise InvalidLabelError(f"O slug pode ter até {SLUG_MAX} caracteres.")
    if _SLUG.fullmatch(cleaned) is None:
        raise InvalidLabelError(
            "Use só letras minúsculas sem acento, números e hífen no slug (ex.: revisao-final)."
        )
    return cleaned


def clean_color(color: str) -> str:
    cleaned = color.strip().lower()
    if _COLOR.fullmatch(cleaned) is None:
        raise InvalidLabelError("A cor deve ser um hexadecimal como #1a2b3c.")
    if len(cleaned) == 4:
        cleaned = "#" + "".join(char * 2 for char in cleaned[1:])
    return cleaned


def list_labels(conn: sqlite3.Connection) -> list[Label]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM labels ORDER BY id").fetchall()
    return [_from_row(row) for row in rows]


def get_label(conn: sqlite3.Connection, label_id: int) -> Label:
    row = conn.execute(f"SELECT {_COLUMNS} FROM labels WHERE id = ?", (label_id,)).fetchone()
    if row is None:
        raise LabelNotFoundError("Etiqueta não encontrada.")
    return _from_row(row)


def _check_unique(conn: sqlite3.Connection, slug: str, exclude_id: int | None = None) -> None:
    row = conn.execute("SELECT id FROM labels WHERE slug = ?", (slug,)).fetchone()
    if row is not None and row["id"] != exclude_id:
        raise DuplicateLabelError("Já existe uma etiqueta com esse slug.")


def create_label(conn: sqlite3.Connection, slug: str, color: str) -> Label:
    cleaned_slug = clean_slug(slug)
    cleaned_color = clean_color(color)
    with transaction(conn):
        _check_unique(conn, cleaned_slug)
        cursor = conn.execute(
            "INSERT INTO labels (slug, color, created_at) VALUES (?, ?, ?)",
            (cleaned_slug, cleaned_color, int(time.time())),
        )
    return get_label(conn, cursor.lastrowid)


def update_label(
    conn: sqlite3.Connection,
    label_id: int,
    slug: str | None = None,
    color: str | None = None,
) -> Label:
    cleaned_slug = clean_slug(slug) if slug is not None else None
    cleaned_color = clean_color(color) if color is not None else None
    with transaction(conn):
        current = get_label(conn, label_id)
        if cleaned_slug is not None:
            _check_unique(conn, cleaned_slug, exclude_id=label_id)
        conn.execute(
            "UPDATE labels SET slug = ?, color = ? WHERE id = ?",
            (cleaned_slug or current.slug, cleaned_color or current.color, label_id),
        )
    return get_label(conn, label_id)


def delete_label(conn: sqlite3.Connection, label_id: int) -> tuple[Label, list[str]]:
    """Remove the label. Returns it and the sessions that had it (they are not deleted)."""
    with transaction(conn):
        label = get_label(conn, label_id)
        released = [
            row["session_id"]
            for row in conn.execute(
                "SELECT session_id FROM session_labels WHERE label_id = ?", (label_id,)
            )
        ]
        conn.execute("DELETE FROM labels WHERE id = ?", (label_id,))
    return label, released


def set_session_labels(
    conn: sqlite3.Connection, session_id: str, label_ids: list[int]
) -> list[int]:
    """Make `label_ids` the labels of the session. All or nothing: an unknown id changes nothing."""
    wanted = sorted(set(label_ids))
    with transaction(conn):
        known = {row["id"] for row in conn.execute("SELECT id FROM labels")}
        if not set(wanted) <= known:
            raise LabelNotFoundError("Etiqueta não encontrada.")
        conn.execute("DELETE FROM session_labels WHERE session_id = ?", (session_id,))
        conn.executemany(
            "INSERT INTO session_labels (session_id, label_id) VALUES (?, ?)",
            [(session_id, label_id) for label_id in wanted],
        )
    return wanted


def session_label_ids(conn: sqlite3.Connection) -> dict[str, list[int]]:
    """Label ids of every session that has any, ordered by id."""
    result: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT session_id, label_id FROM session_labels ORDER BY session_id, label_id"
    ):
        result.setdefault(row["session_id"], []).append(row["label_id"])
    return result
