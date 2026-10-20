"""Title suggestions: prompt, sanitizing and the service method."""

import asyncio

import pytest
from digest_fakes import World, claude, user

from claudio_maestro.digest.config import DigestConfig, save_config
from claudio_maestro.digest.model import DigestModelError, FakeDigestModel
from claudio_maestro.digest.title_suggest import (
    EMPTY_MESSAGE,
    FORMAT_MESSAGE,
    MAX_TEXT,
    SYSTEM_PROMPT,
    TITLE_SCHEMA,
    TitleSuggestError,
    build_prompt,
    sanitize,
)


def answer(*titles: str) -> dict:
    return {"suggestions": list(titles)}


# sanitize ------------------------------------------------------------------------

def test_sanitize_cleans_quotes_dots_and_spaces() -> None:
    raw = {"suggestions": ['  "Sugerir   títulos de sessão." ', "“Ajustar o menu”", "'Corrigir bug'."]}
    assert sanitize(raw) == ["Sugerir títulos de sessão", "Ajustar o menu", "Corrigir bug"]


def test_sanitize_drops_empty_and_duplicates_and_keeps_three() -> None:
    raw = answer("A", "  ", "a.", "B", '""', "C", "D")
    assert sanitize(raw) == ["A", "B", "C"]


def test_sanitize_cuts_at_the_title_limit() -> None:
    [title] = sanitize(answer("x" * 200))
    assert len(title) == 80


def test_sanitize_needs_at_least_one() -> None:
    for raw in (answer(), answer("", "."), {}, {"suggestions": "x"}, [], None,
                {"suggestions": [1, None]}):
        with pytest.raises(TitleSuggestError) as error:
            sanitize(raw)
        assert error.value.message == FORMAT_MESSAGE
        assert error.value.kind == "format"


def test_sanitize_ignores_non_strings_among_strings() -> None:
    assert sanitize({"suggestions": [3, "Um título"]}) == ["Um título"]


# prompt --------------------------------------------------------------------------

def test_schema_is_three_strings() -> None:
    suggestions = TITLE_SCHEMA["properties"]["suggestions"]
    assert TITLE_SCHEMA["required"] == ["suggestions"]
    assert (suggestions["minItems"], suggestions["maxItems"]) == (3, 3)
    assert suggestions["items"] == {"type": "string"}


def test_system_prompt_carries_the_rules() -> None:
    for fragment in ("português", "60", "infinitivo", "Ajuda com", "30", "título atual"):
        assert fragment in SYSTEM_PROMPT


def test_build_prompt_has_context_and_sections() -> None:
    text = build_prompt(project="app", title="Nova sessão", first="[Você] faça X", recent="[Claude] ok")
    assert "Projeto: app" in text
    assert "Título atual: Nova sessão" in text
    assert "faça X" in text and "[Claude] ok" in text


# service -------------------------------------------------------------------------

def make(tmp_path, messages, **fields):
    world = World(tmp_path)
    world.add("s1", messages, **fields)
    return world


def test_suggest_returns_sanitized_titles(tmp_path) -> None:
    world = make(tmp_path, [user("u1", "Quero um botão de sugerir título"), claude("a1", "Feito")])
    model = FakeDigestModel([answer('"Sugerir títulos."', "Botão de título", "Títulos")])
    service = world.service(model)
    assert asyncio.run(service.suggest_titles("s1")) == [
        "Sugerir títulos", "Botão de título", "Títulos"]
    [request] = model.requests
    assert request.schema is TITLE_SCHEMA
    assert request.system_prompt == SYSTEM_PROMPT
    assert "Quero um botão de sugerir título" in request.prompt
    assert "Projeto: app" in request.prompt
    assert "Título atual: Sessão s1" in request.prompt


def test_suggest_uses_haiku_without_stored_config(tmp_path) -> None:
    world = make(tmp_path, [user("u1", "oi")])
    model = FakeDigestModel([answer("A")])
    asyncio.run(world.service(model).suggest_titles("s1"))
    assert model.requests[0].model == "haiku"


def test_suggest_uses_the_digest_model_when_configured(tmp_path) -> None:
    from contextlib import closing

    from claudio_maestro import db

    world = make(tmp_path, [user("u1", "oi")])
    with closing(db.connect(world.db_path)) as conn:
        save_config(conn, DigestConfig(model="opus", effort="high"))
    model = FakeDigestModel([answer("A")])
    asyncio.run(world.service(model).suggest_titles("s1"))
    assert (model.requests[0].model, model.requests[0].effort) == ("opus", "high")


def test_suggest_limits_the_text(tmp_path) -> None:
    messages = []
    for i in range(80):
        messages += [user(f"u{i}", f"pedido {i} " + "x" * 1500), claude(f"a{i}", "y" * 1500)]
    world = make(tmp_path, messages)
    model = FakeDigestModel([answer("A")])
    asyncio.run(world.service(model).suggest_titles("s1"))
    prompt = model.requests[0].prompt
    assert len(prompt) < MAX_TEXT + 3000
    assert "pedido 0 " in prompt  # the first request always goes
    assert "pedido 79 " in prompt  # and the way the conversation went


def test_suggest_without_messages(tmp_path) -> None:
    world = make(tmp_path, [])
    model = FakeDigestModel()
    with pytest.raises(TitleSuggestError) as error:
        asyncio.run(world.service(model).suggest_titles("s1"))
    assert (error.value.kind, error.value.message) == ("empty", EMPTY_MESSAGE)
    assert model.requests == []


def test_suggest_without_transcript_file(tmp_path) -> None:
    world = make(tmp_path, [user("u1", "oi")])
    (world.files_dir / "s1.jsonl").unlink()
    with pytest.raises(TitleSuggestError) as error:
        asyncio.run(world.service(FakeDigestModel()).suggest_titles("s1"))
    assert error.value.kind == "empty"


def test_suggest_unknown_session(tmp_path) -> None:
    world = make(tmp_path, [user("u1", "oi")])
    with pytest.raises(TitleSuggestError) as error:
        asyncio.run(world.service(FakeDigestModel()).suggest_titles("nope"))
    assert error.value.kind == "not_found"


def test_suggest_model_error(tmp_path) -> None:
    world = make(tmp_path, [user("u1", "oi")])
    model = FakeDigestModel([DigestModelError("Sem login.", stop_pass=True)])
    with pytest.raises(TitleSuggestError) as error:
        asyncio.run(world.service(model).suggest_titles("s1"))
    assert (error.value.kind, error.value.message) == ("model", "Sem login.")


def test_suggest_bad_format(tmp_path) -> None:
    world = make(tmp_path, [user("u1", "oi")])
    model = FakeDigestModel([{"suggestions": []}])
    with pytest.raises(TitleSuggestError) as error:
        asyncio.run(world.service(model).suggest_titles("s1"))
    assert error.value.kind == "format"


def test_suggest_timeout(tmp_path) -> None:
    world = make(tmp_path, [user("u1", "oi")])
    model = FakeDigestModel()
    model.gate = asyncio.Event()
    with pytest.raises(TitleSuggestError) as error:
        asyncio.run(world.service(model, session_timeout=0.01).suggest_titles("s1"))
    assert error.value.kind == "timeout"


def test_suggest_does_not_touch_the_session(tmp_path) -> None:
    from contextlib import closing

    from claudio_maestro import db

    world = make(tmp_path, [user("u1", "oi")])
    asyncio.run(world.service(FakeDigestModel([answer("A")])).suggest_titles("s1"))
    with closing(db.connect(world.db_path)) as conn:
        title = conn.execute("SELECT title FROM sessions WHERE session_id = 's1'").fetchone()[0]
    assert title == "Sessão s1"
