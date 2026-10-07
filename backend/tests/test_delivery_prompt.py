"""The delivery summary: prompt, schema, slice and cleaning."""

from types import SimpleNamespace

import pytest

from claudio_maestro.digest.delivery import (
    DELIVERY_SCHEMA,
    build_delivery_prompt,
    clean_delivery,
    delivery_system_prompt,
    slice_between,
)
from claudio_maestro.digest.merge import DigestFormatError
from claudio_maestro.digest.store import Digest
from claudio_maestro.history import Transcript


def msg(uuid: str) -> SimpleNamespace:
    return SimpleNamespace(type="user", uuid=uuid, message={"role": "user", "content": uuid})


def transcript(*uuids: str, compact: tuple[str, ...] = ()) -> Transcript:
    t = Transcript(messages=[msg(u) for u in uuids], tool_results={})
    t.compact_uuids = set(compact)
    return t


def uuids(piece) -> list[str]:
    return [m.uuid for m in piece.messages]


def test_slice_between_whole_conversation() -> None:
    piece = slice_between(transcript("a", "b", "c"), None, "c")
    assert uuids(piece) == ["a", "b", "c"] and piece.cursor_found


def test_slice_between_stops_at_to_cursor() -> None:
    assert uuids(slice_between(transcript("a", "b", "c", "d"), "a", "c")) == ["b", "c"]


def test_slice_between_same_cursor_is_empty() -> None:
    assert uuids(slice_between(transcript("a", "b", "c"), "c", "c")) == []


def test_slice_between_to_cursor_before_from_is_empty() -> None:
    assert uuids(slice_between(transcript("a", "b", "c"), "c", "b")) == []


def test_slice_between_missing_to_cursor_goes_to_the_end() -> None:
    assert uuids(slice_between(transcript("a", "b", "c"), "a", None)) == ["b", "c"]
    assert uuids(slice_between(transcript("a", "b", "c"), "a", "zz")) == ["b", "c"]


def test_slice_between_lost_from_cursor_restarts_at_compaction() -> None:
    piece = slice_between(transcript("k", "x", "y", compact=("k",)), "gone", "y")
    assert uuids(piece) == ["k", "x", "y"] and not piece.cursor_found


def test_prompt_has_project_title_digest_and_text() -> None:
    digest = Digest("s", short="Faz X", phases=[{"title": "F", "done": ["a"]}])
    text = build_delivery_prompt(project="app", title="Tela", digest=digest,
                                 text="[Você] faça", restarted=False)
    assert "Projeto: app" in text and "Título: Tela" in text
    assert "Faz X" in text and "[Você] faça" in text
    plain = build_delivery_prompt(project="app", title="Tela", digest=None, text="t", restarted=True)
    assert "Sem resumo." in plain and "compactado" in plain


def test_system_prompt_appends_extra_instructions() -> None:
    assert "Instruções extras do usuário:\nseja breve" in delivery_system_prompt(" seja breve ")
    assert "Instruções extras" not in delivery_system_prompt("  ")


def test_schema_shape() -> None:
    assert DELIVERY_SCHEMA["required"] == ["title", "bullets"]
    assert DELIVERY_SCHEMA["additionalProperties"] is False


def test_clean_delivery_clips_and_limits() -> None:
    title, bullets = clean_delivery({"title": " " + "t" * 130 + " ",
                                     "bullets": ["  a  ", "", 3, "b" * 250] + ["c"] * 10})
    assert len(title) == 121 and title.endswith("…")
    assert bullets[0] == "a" and len(bullets[1]) == 201 and len(bullets) == 8


@pytest.mark.parametrize("raw", [None, {}, {"title": "", "bullets": ["a"]},
                                 {"title": "T", "bullets": []}, {"title": "T", "bullets": "a"},
                                 {"title": 3, "bullets": ["a"]}])
def test_clean_delivery_rejects_bad_answers(raw) -> None:
    with pytest.raises(DigestFormatError):
        clean_delivery(raw)
