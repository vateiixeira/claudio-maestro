import asyncio
import json

import pytest

from claudio_maestro.specialists.files import LEARNINGS_MAX_CHARS, LearningsTooLongError
from claudio_maestro.specialists.store import Item
from claudio_maestro.specialists.tools import (
    MAX_KEY,
    SERVER_NAME,
    TOOL_PREFIX,
    build_server,
    build_tools,
)


class FakeHost:
    def __init__(self, items: list[Item] | None = None) -> None:
        self.items = items or []
        self.calls: list[tuple] = []
        self.fail_with: Exception | None = None

    async def conclude(self, session_id: str, summary: str) -> None:
        self.calls.append(("conclude", session_id, summary))
        if self.fail_with:
            raise self.fail_with

    async def notify(self, session_id: str, text: str) -> None:
        self.calls.append(("notify", session_id, text))

    def lookup(self, specialist_id: int, keys: list[str]) -> list[Item]:
        self.calls.append(("lookup", specialist_id, keys))
        return [item for item in self.items if item.key in keys]

    def record(
        self, specialist_id: int, key: str, status: str, link: str | None, note: str | None
    ) -> Item:
        self.calls.append(("record", specialist_id, key, status, link, note))
        return Item(key=key, status=status, link=link, note=note, created_at=10, updated_at=10)

    def rewrite_learnings(self, specialist_id: int, text: str) -> None:
        self.calls.append(("rewrite_learnings", specialist_id, text))
        if self.fail_with:
            raise self.fail_with


def _handlers(host: FakeHost) -> dict:
    tools = build_tools(host, specialist_id=7, session_id="sess-1")
    return {t.name: t.handler for t in tools}


def _call(host: FakeHost, name: str, args: dict) -> dict:
    return asyncio.run(_handlers(host)[name](args))


def _text(result: dict) -> str:
    return result["content"][0]["text"]


def _item(key: str, status: str = "feito") -> Item:
    return Item(key=key, status=status, link="https://x/1", note="ok", created_at=1, updated_at=5)


def test_lookup_returns_only_found_keys():
    host = FakeHost([_item("a"), _item("b", "pendente")])

    result = _call(host, "registro_consultar", {"chaves": ["a", "c"]})

    assert not result.get("is_error")
    assert json.loads(_text(result)) == {
        "itens": [
            {"chave": "a", "situacao": "feito", "link": "https://x/1", "nota": "ok", "atualizado_em": 5}
        ]
    }
    assert host.calls == [("lookup", 7, ["a", "c"])]


def test_lookup_with_nothing_found_returns_empty_list():
    result = _call(FakeHost(), "registro_consultar", {"chaves": ["z"]})

    assert json.loads(_text(result)) == {"itens": []}


def test_lookup_accepts_200_keys_and_rejects_more():
    host = FakeHost()
    assert not _call(host, "registro_consultar", {"chaves": [f"k{i}" for i in range(200)]}).get("is_error")

    host = FakeHost()
    result = _call(host, "registro_consultar", {"chaves": [f"k{i}" for i in range(201)]})

    assert result["is_error"] is True
    assert "200" in _text(result)
    assert host.calls == []


def test_lookup_rejects_empty_or_non_text_keys():
    host = FakeHost()
    assert _call(host, "registro_consultar", {"chaves": []})["is_error"] is True
    assert _call(host, "registro_consultar", {"chaves": ["a", 3]})["is_error"] is True
    assert host.calls == []


def test_record_stores_item_and_turns_empty_link_and_note_into_none():
    host = FakeHost()

    result = _call(host, "registro_gravar", {"chave": "k", "situacao": "feito"})

    assert not result.get("is_error")
    assert host.calls == [("record", 7, "k", "feito", None, None)]


def test_record_passes_link_and_note():
    host = FakeHost()

    _call(host, "registro_gravar", {"chave": "k", "situacao": "feito", "link": "u", "nota": "n"})

    assert host.calls == [("record", 7, "k", "feito", "u", "n")]


@pytest.mark.parametrize(
    ("field", "limit"),
    [("chave", 200), ("situacao", 40), ("link", 500), ("nota", 500)],
)
def test_record_validates_lengths(field, limit):
    base = {"chave": "k", "situacao": "feito", "link": "", "nota": ""}

    host = FakeHost()
    assert not _call(host, "registro_gravar", {**base, field: "x" * limit}).get("is_error")
    assert len(host.calls) == 1

    host = FakeHost()
    result = _call(host, "registro_gravar", {**base, field: "x" * (limit + 1)})
    assert result["is_error"] is True
    assert str(limit) in _text(result)
    assert host.calls == []


def test_record_rejects_blank_key_and_status():
    host = FakeHost()
    assert _call(host, "registro_gravar", {"chave": "  ", "situacao": "feito"})["is_error"] is True
    assert _call(host, "registro_gravar", {"chave": "k", "situacao": ""})["is_error"] is True
    assert host.calls == []


def test_learnings_rewrite_reaches_host():
    host = FakeHost()

    result = _call(host, "aprendizados_reescrever", {"texto": "x" * LEARNINGS_MAX_CHARS})

    assert not result.get("is_error")
    assert host.calls == [("rewrite_learnings", 7, "x" * LEARNINGS_MAX_CHARS)]


def test_learnings_over_cap_is_tool_error_with_message():
    host = FakeHost()

    result = _call(host, "aprendizados_reescrever", {"texto": "x" * (LEARNINGS_MAX_CHARS + 1)})

    assert result["is_error"] is True
    assert _text(result) == str(LearningsTooLongError())
    assert host.calls == []


def test_learnings_error_raised_by_host_is_tool_error_too():
    host = FakeHost()
    host.fail_with = LearningsTooLongError()

    result = _call(host, "aprendizados_reescrever", {"texto": "curto"})

    assert result["is_error"] is True
    assert _text(result) == str(LearningsTooLongError())


def test_notify_and_conclude_reach_host_with_session_id():
    host = FakeHost()

    assert not _call(host, "avisar", {"texto": "olá"}).get("is_error")
    assert not _call(host, "concluir", {"resumo": "feito"}).get("is_error")

    assert host.calls == [("notify", "sess-1", "olá"), ("conclude", "sess-1", "feito")]


@pytest.mark.parametrize(("name", "field", "limit"), [("avisar", "texto", 2000), ("concluir", "resumo", 4000)])
def test_notify_and_conclude_limits(name, field, limit):
    host = FakeHost()
    assert not _call(host, name, {field: "x" * limit}).get("is_error")

    host = FakeHost()
    result = _call(host, name, {field: "x" * (limit + 1)})
    assert result["is_error"] is True
    assert host.calls == []


def test_blank_notice_and_summary_are_tool_errors():
    host = FakeHost()
    assert _call(host, "avisar", {"texto": " "})["is_error"] is True
    assert _call(host, "concluir", {"resumo": ""})["is_error"] is True
    assert host.calls == []


def test_unexpected_host_failure_is_tool_error_not_exception():
    host = FakeHost()
    host.fail_with = RuntimeError("segredo interno")

    result = _call(host, "concluir", {"resumo": "feito"})

    assert result["is_error"] is True
    assert "segredo interno" not in _text(result)


def test_missing_argument_is_tool_error():
    assert _call(FakeHost(), "avisar", {})["is_error"] is True


def test_server_lists_five_tools_with_prefix():
    tools = build_tools(FakeHost(), specialist_id=7, session_id="sess-1")

    assert SERVER_NAME == "maestro"
    assert TOOL_PREFIX == "mcp__maestro__"
    assert sorted(t.name for t in tools) == [
        "aprendizados_reescrever",
        "avisar",
        "concluir",
        "registro_consultar",
        "registro_gravar",
    ]
    by_name = {t.name: t for t in tools}
    assert by_name["concluir"].description.startswith("Chame só quando a tarefa inteira terminou.")
    assert "mantém a conversa aberta" in by_name["concluir"].description
    # Optional fields stay optional in the schema the model sees.
    assert by_name["registro_gravar"].input_schema["required"] == ["chave", "situacao"]

    server = build_server(FakeHost(), specialist_id=7, session_id="sess-1")
    assert server["type"] == "sdk"
    assert server["name"] == SERVER_NAME


def test_lookup_rejects_key_longer_than_max_key():
    host = FakeHost()
    assert not _call(host, "registro_consultar", {"chaves": ["x" * MAX_KEY] * 200}).get("is_error")

    host = FakeHost()
    result = _call(host, "registro_consultar", {"chaves": ["a", "x" * (MAX_KEY + 1)]})

    assert result["is_error"] is True
    assert str(MAX_KEY) in _text(result)
    assert host.calls == []


def test_main_tools_without_concluir():
    names = [t.name for t in build_tools(FakeHost(), specialist_id=7, session_id="s", main=True)]

    assert "concluir" not in names
    assert names == ["registro_consultar", "registro_gravar", "aprendizados_reescrever", "avisar"]


def test_isolated_tools_keep_concluir():
    names = [t.name for t in build_tools(FakeHost(), specialist_id=7, session_id="s")]

    assert "concluir" in names
