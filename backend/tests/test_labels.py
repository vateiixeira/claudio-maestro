"""Labels module: slug and color rules, CRUD and links to sessions."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from claudio_maestro import db, labels


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "t.db")) as c:
        db.migrate(c)
        c.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/tmp/p1', '#fff', 0, 0)"
        )
        yield c


def add_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
        " last_activity_at) VALUES (?, 1, '/tmp', 't', 0, 0)",
        (session_id,),
    )


def test_create_trims_lowercases_and_lists(conn):
    created = labels.create_label(conn, "  Urgente ", "#FF0000")
    assert created.slug == "urgente"
    assert created.color == "#ff0000"
    assert labels.list_labels(conn) == [created]
    assert labels.get_label(conn, created.id) == created


@pytest.mark.parametrize(
    "raw", ["", "   ", "a b", "Urgência", "-x", "x-", "a--b", "a_b", "x" * 33, "a\nb"]
)
def test_invalid_slugs_are_refused_and_nothing_is_saved(conn, raw):
    with pytest.raises(labels.InvalidLabelError):
        labels.create_label(conn, raw, "#ffffff")
    assert labels.list_labels(conn) == []


def test_slug_with_the_maximum_length_is_accepted(conn):
    assert labels.create_label(conn, "x" * 32, "#ffffff").slug == "x" * 32


@pytest.mark.parametrize("raw", ["red", "#12345", "#gggggg", "ff0000", "", "#ff00000"])
def test_invalid_colors_are_refused(conn, raw):
    with pytest.raises(labels.InvalidLabelError):
        labels.create_label(conn, "ok", raw)
    assert labels.list_labels(conn) == []


def test_short_color_is_expanded():
    assert labels.clean_color(" #FfA ") == "#ffffaa"


def test_duplicate_slug_is_refused_ignoring_case(conn):
    labels.create_label(conn, "urgente", "#ff0000")
    with pytest.raises(labels.DuplicateLabelError):
        labels.create_label(conn, "URGENTE", "#00ff00")


def test_update_changes_slug_and_color_and_keeps_the_rest(conn):
    created = labels.create_label(conn, "urgente", "#ff0000")
    only_color = labels.update_label(conn, created.id, color="#00ff00")
    assert (only_color.slug, only_color.color) == ("urgente", "#00ff00")
    renamed = labels.update_label(conn, created.id, slug="Importante")
    assert (renamed.slug, renamed.color) == ("importante", "#00ff00")
    assert renamed.created_at == created.created_at


def test_update_to_its_own_slug_is_not_a_duplicate(conn):
    created = labels.create_label(conn, "urgente", "#ff0000")
    assert labels.update_label(conn, created.id, slug="urgente").slug == "urgente"


def test_update_to_another_slug_in_use_is_refused(conn):
    labels.create_label(conn, "a", "#ff0000")
    b = labels.create_label(conn, "b", "#ff0000")
    with pytest.raises(labels.DuplicateLabelError):
        labels.update_label(conn, b.id, slug="a")
    assert labels.get_label(conn, b.id).slug == "b"


def test_unknown_label_raises_not_found(conn):
    with pytest.raises(labels.LabelNotFoundError):
        labels.get_label(conn, 99)
    with pytest.raises(labels.LabelNotFoundError):
        labels.update_label(conn, 99, color="#ffffff")
    with pytest.raises(labels.LabelNotFoundError):
        labels.delete_label(conn, 99)


def test_set_session_labels_replaces_dedupes_and_sorts(conn):
    add_session(conn, "s1")
    a = labels.create_label(conn, "a", "#111111")
    b = labels.create_label(conn, "b", "#222222")
    assert labels.set_session_labels(conn, "s1", [b.id, a.id, b.id]) == [a.id, b.id]
    assert labels.session_label_ids(conn) == {"s1": [a.id, b.id]}
    assert labels.set_session_labels(conn, "s1", [b.id]) == [b.id]
    assert labels.set_session_labels(conn, "s1", []) == []
    assert labels.session_label_ids(conn) == {}


def test_set_session_labels_with_an_unknown_id_changes_nothing(conn):
    add_session(conn, "s1")
    a = labels.create_label(conn, "a", "#111111")
    labels.set_session_labels(conn, "s1", [a.id])
    with pytest.raises(labels.LabelNotFoundError):
        labels.set_session_labels(conn, "s1", [a.id, 999])
    assert labels.session_label_ids(conn) == {"s1": [a.id]}


def test_delete_returns_the_sessions_that_had_it_and_unlinks_them(conn):
    add_session(conn, "s1")
    add_session(conn, "s2")
    a = labels.create_label(conn, "a", "#111111")
    b = labels.create_label(conn, "b", "#222222")
    labels.set_session_labels(conn, "s1", [a.id, b.id])
    labels.set_session_labels(conn, "s2", [b.id])
    deleted, released = labels.delete_label(conn, b.id)
    assert deleted.slug == "b"
    assert sorted(released) == ["s1", "s2"]
    assert labels.session_label_ids(conn) == {"s1": [a.id]}
    assert [label.slug for label in labels.list_labels(conn)] == ["a"]
