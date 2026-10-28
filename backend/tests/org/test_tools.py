import asyncio
import json

import pytest

from claudio_maestro.org import store
from claudio_maestro.org.store import Item
from claudio_maestro.org.tasks import TaskAuthorityError
from claudio_maestro.org.tools import (
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
        self.agents: list[dict] = []
        self.task_view: dict = {
            "id": 5, "title": "Ajustar login", "description": "Corrigir o botão.",
            "status": "todo", "priority": "normal", "assignee": "Dev", "reviewer": None,
            "creator": "CTO", "parent_id": None, "blocked_reason": None, "worktree": None,
            "created_at": 1, "updated_at": 2, "can_change": True,
        }
        self.listed: list[dict] = []
        self.ci_result: dict = {
            "receipt": "ci-abc", "conclusion": "failure", "head_sha": "a" * 40,
            "run_url": "https://github.com/o/r/actions/runs/9", "repository": "o/r",
            "jobs": [{"name": "backend", "conclusion": "failure"}],
        }

    async def conclude(self, session_id: str, summary: str) -> None:
        self.calls.append(("conclude", session_id, summary))
        if self.fail_with:
            raise self.fail_with

    async def notify(self, session_id: str, text: str) -> None:
        self.calls.append(("notify", session_id, text))

    def lookup(self, agent_id: int, keys: list[str]) -> list[Item]:
        self.calls.append(("lookup", agent_id, keys))
        return [item for item in self.items if item.key in keys]

    def record(
        self, agent_id: int, key: str, status: str, link: str | None, note: str | None
    ) -> Item:
        self.calls.append(("record", agent_id, key, status, link, note))
        return Item(key=key, status=status, link=link, note=note, created_at=10, updated_at=10)

    def organization(self, agent_id: int) -> list[dict]:
        self.calls.append(("organization", agent_id))
        return self.agents


    def tasks_list(self, agent_id: int, *, mine: bool, statuses: list[str] | None) -> list[dict]:
        self.calls.append(("tasks_list", agent_id, mine, statuses))
        self._maybe_fail()
        return self.listed

    def task_read(self, agent_id: int, task_id: int) -> dict:
        self.calls.append(("task_read", agent_id, task_id))
        self._maybe_fail()
        return {
            **self.task_view,
            "comments": [{"id": 3, "author": "Pessoa", "text": "Oi", "created_at": 9}],
        }

    async def task_create(self, agent_id: int, session_id: str, **fields) -> dict:
        self.calls.append(("task_create", agent_id, session_id, fields))
        self._maybe_fail()
        return self.task_view

    async def task_update(self, agent_id: int, session_id: str, task_id: int, **fields) -> dict:
        self.calls.append(("task_update", agent_id, session_id, task_id, fields))
        self._maybe_fail()
        return self.task_view

    async def task_comment(self, agent_id: int, session_id: str, task_id: int, text: str) -> dict:
        self.calls.append(("task_comment", agent_id, session_id, task_id, text))
        self._maybe_fail()
        return {"id": 11}

    def decide(self, session_id: str, question: str, options: list[str]) -> dict:
        self.calls.append(("decide", session_id, question, options))
        self._maybe_fail()
        return {"id": 4, "task_id": None}

    async def verify_ci(self, session_id: str, run_url: str) -> dict:
        self.calls.append(("verify_ci", session_id, run_url))
        self._maybe_fail()
        return self.ci_result

    def _maybe_fail(self) -> None:
        if self.fail_with:
            raise self.fail_with


def _handlers(host: FakeHost) -> dict:
    tools = build_tools(host, agent_id=7, session_id="sess-1")
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


def test_server_lists_all_tools_with_prefix():
    tools = build_tools(FakeHost(), agent_id=7, session_id="sess-1")

    assert SERVER_NAME == "maestro"
    assert TOOL_PREFIX == "mcp__maestro__"
    assert sorted(t.name for t in tools) == [
        "avisar",
        "concluir",
        "decidir",
        "organizacao",
        "registro_consultar",
        "registro_gravar",
        "tarefa_atualizar",
        "tarefa_comentar",
        "tarefa_criar",
        "tarefa_ler",
        "tarefas_listar",
        "verificar_ci",
    ]
    by_name = {t.name: t for t in tools}
    assert by_name["concluir"].description.startswith("Chame só quando a tarefa inteira terminou.")
    assert "mantém a conversa aberta" in by_name["concluir"].description
    # Optional fields stay optional in the schema the model sees.
    assert by_name["registro_gravar"].input_schema["required"] == ["chave", "situacao"]

    server = build_server(FakeHost(), agent_id=7, session_id="sess-1")
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
    names = [t.name for t in build_tools(FakeHost(), agent_id=7, session_id="s", main=True)]

    assert "concluir" not in names
    assert names == [
        "registro_consultar", "registro_gravar", "avisar", "organizacao", "tarefas_listar",
        "tarefa_ler", "tarefa_criar", "tarefa_atualizar", "tarefa_comentar", "decidir",
        "verificar_ci",
    ]


def test_isolated_tools_keep_concluir():
    names = [t.name for t in build_tools(FakeHost(), agent_id=7, session_id="s")]

    assert "concluir" in names


def test_organizacao_lists_agents_marking_me():
    host = FakeHost()
    host.agents = [
        {"name": "cto", "description": "Lidera", "reports_to": None, "is_me": False, "enabled": True},
        {"name": "dev", "description": "Implementa", "reports_to": "cto", "is_me": True, "enabled": False},
    ]

    result = _call(host, "organizacao", {})

    assert not result.get("is_error")
    assert json.loads(_text(result)) == {
        "agentes": [
            {"nome": "cto", "descricao": "Lidera", "chefe": None, "sou_eu": False, "ligado": True},
            {"nome": "dev", "descricao": "Implementa", "chefe": "cto", "sou_eu": True, "ligado": False},
        ]
    }
    assert host.calls == [("organization", 7)]


def test_organizacao_available_in_main():
    names = [t.name for t in build_tools(FakeHost(), agent_id=7, session_id="s", main=True)]

    assert "organizacao" in names


def test_handler_exception_becomes_generic_error():
    host = FakeHost()

    def boom(agent_id: int) -> list[dict]:
        raise RuntimeError("segredo interno")

    host.organization = boom  # type: ignore[method-assign]

    result = _call(host, "organizacao", {})

    assert result["is_error"] is True
    assert "segredo interno" not in _text(result)
    assert _text(result) == "Não foi possível concluir esta ação agora. Tente de novo."


def test_no_learnings_tool():
    names = [t.name for t in build_tools(FakeHost(), agent_id=7, session_id="s")]

    assert "aprendizados_reescrever" not in names


# Task tools ---------------------------------------------------------------------------


def test_main_conversation_has_task_tools():
    names = {t.name for t in build_tools(FakeHost(), agent_id=7, session_id="s", main=True)}

    assert {
        "tarefas_listar", "tarefa_ler", "tarefa_criar", "tarefa_atualizar", "tarefa_comentar",
        "decidir", "verificar_ci",
    } <= names


def test_tarefas_listar_mine_default():
    host = FakeHost()
    host.listed = [{**host.task_view, "comments": None}]

    result = _call(host, "tarefas_listar", {})

    assert not result.get("is_error")
    assert host.calls == [("tasks_list", 7, True, None)]
    [task] = json.loads(_text(result))["tarefas"]
    assert task["id"] == 5
    assert task["titulo"] == "Ajustar login"
    assert task["responsavel"] == "Dev"
    assert task["prioridade"] == "normal"
    assert "comentarios" not in task


def test_tarefas_listar_everyone_with_statuses():
    host = FakeHost()

    _call(host, "tarefas_listar", {"minhas": False, "status": ["todo", "blocked"]})

    assert host.calls == [("tasks_list", 7, False, ["todo", "blocked"])]


def test_tarefas_listar_rejects_unknown_status():
    host = FakeHost()

    result = _call(host, "tarefas_listar", {"status": ["feito"]})

    assert result["is_error"] is True
    assert "in_progress" in _text(result)
    assert host.calls == []


def test_tarefa_ler_returns_task_with_comments_in_portuguese():
    host = FakeHost()

    result = _call(host, "tarefa_ler", {"id": 5})

    payload = json.loads(_text(result))["tarefa"]
    assert host.calls == [("task_read", 7, 5)]
    assert payload["descricao"] == "Corrigir o botão."
    assert payload["criador"] == "CTO"
    assert payload["pode_alterar"] is True
    assert payload["comentarios"] == [{"id": 3, "autor": "Pessoa", "texto": "Oi", "criado_em": 9}]


def test_tarefa_ler_requires_integer_id():
    host = FakeHost()

    assert _call(host, "tarefa_ler", {"id": "abc"})["is_error"] is True
    assert _call(host, "tarefa_ler", {"id": True})["is_error"] is True
    assert _call(host, "tarefa_ler", {})["is_error"] is True
    assert host.calls == []


def test_tarefa_criar_passes_fields_to_host():
    host = FakeHost()

    result = _call(
        host,
        "tarefa_criar",
        {
            "titulo": "Ajustar login", "descricao": "Corrigir o botão.", "responsavel": "Dev",
            "pai": 2, "prioridade": "high", "revisor": "revisor",
        },
    )

    assert not result.get("is_error")
    assert host.calls == [
        (
            "task_create", 7, "sess-1",
            {
                "title": "Ajustar login", "description": "Corrigir o botão.", "assignee": "Dev",
                "parent_id": 2, "priority": "high", "reviewer": "revisor",
            },
        )
    ]
    assert json.loads(_text(result))["tarefa"]["id"] == 5


def test_tarefa_criar_leaves_optional_fields_out():
    host = FakeHost()

    _call(host, "tarefa_criar", {"titulo": "T", "descricao": "D", "responsavel": "", "revisor": " "})

    assert host.calls == [
        (
            "task_create", 7, "sess-1",
            {
                "title": "T", "description": "D", "assignee": None, "parent_id": None,
                "priority": None, "reviewer": None,
            },
        )
    ]


@pytest.mark.parametrize(
    ("field", "limit"), [("titulo", 160), ("descricao", 20_000), ("responsavel", 200)]
)
def test_tarefa_criar_validates_lengths(field, limit):
    base = {"titulo": "T", "descricao": "D"}

    host = FakeHost()
    assert not _call(host, "tarefa_criar", {**base, field: "x" * limit}).get("is_error")

    host = FakeHost()
    result = _call(host, "tarefa_criar", {**base, field: "x" * (limit + 1)})
    assert result["is_error"] is True
    assert str(limit) in _text(result)
    assert host.calls == []


def test_tarefa_criar_rejects_blank_title_and_bad_priority():
    host = FakeHost()

    assert _call(host, "tarefa_criar", {"titulo": " ", "descricao": "D"})["is_error"] is True
    result = _call(host, "tarefa_criar", {"titulo": "T", "descricao": "D", "prioridade": "alta"})
    assert result["is_error"] is True
    assert "urgent" in _text(result)
    assert host.calls == []


def test_tarefa_atualizar_requires_comentario():
    host = FakeHost()

    assert _call(host, "tarefa_atualizar", {"id": 5, "status": "done"})["is_error"] is True
    assert _call(host, "tarefa_atualizar", {"id": 5, "status": "done", "comentario": "  "})[
        "is_error"
    ] is True
    assert host.calls == []

    schema = {t.name: t for t in build_tools(host, agent_id=7, session_id="s")}[
        "tarefa_atualizar"
    ].input_schema
    assert schema["required"] == ["id", "comentario"]


def test_tarefa_atualizar_passes_fields_to_host():
    host = FakeHost()

    result = _call(
        host,
        "tarefa_atualizar",
        {"id": 5, "status": "in_progress", "responsavel": "dev", "prioridade": "low",
         "comentario": "Peguei."},
    )

    assert not result.get("is_error")
    assert host.calls == [
        (
            "task_update", 7, "sess-1", 5,
            {"status": "in_progress", "assignee": "dev", "priority": "low", "comment": "Peguei."},
        )
    ]


def test_tarefa_atualizar_rejects_unknown_status():
    host = FakeHost()

    result = _call(host, "tarefa_atualizar", {"id": 5, "status": "feito", "comentario": "ok"})

    assert result["is_error"] is True
    assert "done" in _text(result)
    assert host.calls == []


def test_tarefa_atualizar_authority_error_is_portuguese():
    host = FakeHost()
    host.fail_with = TaskAuthorityError()

    result = _call(host, "tarefa_atualizar", {"id": 5, "status": "done", "comentario": "ok"})

    assert result["is_error"] is True
    assert _text(result) == "Você não pode alterar esta tarefa: ela não é sua nem de um subordinado seu."


@pytest.mark.parametrize(
    "error",
    [store.TaskNotFoundError(), store.TaskRevisionError(), store.TaskValidationError("Título inválido."),
     store.OrgError("Qualquer coisa de domínio.")],
)
def test_domain_errors_reach_the_agent(error):
    host = FakeHost()
    host.fail_with = error

    result = _call(host, "tarefa_comentar", {"id": 5, "texto": "oi"})

    assert result["is_error"] is True
    assert _text(result) == str(error)


def test_unexpected_task_failure_stays_generic():
    host = FakeHost()
    host.fail_with = RuntimeError("segredo interno")

    result = _call(host, "tarefa_comentar", {"id": 5, "texto": "oi"})

    assert result["is_error"] is True
    assert "segredo interno" not in _text(result)


def test_tarefa_comentar_passes_text_and_validates():
    host = FakeHost()

    result = _call(host, "tarefa_comentar", {"id": 5, "texto": "Feito."})

    assert not result.get("is_error")
    assert host.calls == [("task_comment", 7, "sess-1", 5, "Feito.")]
    assert _call(host, "tarefa_comentar", {"id": 5, "texto": " "})["is_error"] is True
    assert _call(host, "tarefa_comentar", {"id": 5, "texto": "x" * 20_001})["is_error"] is True
    assert len(host.calls) == 1


def test_decidir_passes_question_and_options():
    host = FakeHost()

    result = _call(host, "decidir", {"pergunta": "Usar Redis?", "opcoes": ["sim", "não"]})

    assert not result.get("is_error")
    assert host.calls == [("decide", "sess-1", "Usar Redis?", ["sim", "não"])]
    assert "aguarde" in _text(result).lower()


def test_decidir_options_are_optional():
    host = FakeHost()

    _call(host, "decidir", {"pergunta": "E agora?"})

    assert host.calls == [("decide", "sess-1", "E agora?", [])]


def test_decidir_validates_options():
    host = FakeHost()
    ok = {"pergunta": "P", "opcoes": ["o"] * 8}
    assert not _call(host, "decidir", ok).get("is_error")
    assert not _call(host, "decidir", {"pergunta": "x" * 2000, "opcoes": ["y" * 200]}).get("is_error")
    assert len(host.calls) == 2

    bad = [
        {"pergunta": " "},
        {"pergunta": "x" * 2001},
        {"pergunta": "P", "opcoes": ["o"] * 9},
        {"pergunta": "P", "opcoes": ["y" * 201]},
        {"pergunta": "P", "opcoes": [""]},
        {"pergunta": "P", "opcoes": ["a", 3]},
        {"pergunta": "P", "opcoes": "sim"},
    ]
    for args in bad:
        assert _call(host, "decidir", args)["is_error"] is True, args
    assert len(host.calls) == 2


def test_verificar_ci_passes_url():
    host = FakeHost()

    result = _call(host, "verificar_ci", {"url": "https://github.com/o/r/actions/runs/9"})

    assert not result.get("is_error")
    assert host.calls == [("verify_ci", "sess-1", "https://github.com/o/r/actions/runs/9")]


def test_verificar_ci_text_carries_conclusion_with_receipt_and_jobs():
    host = FakeHost()

    text = _text(_call(host, "verificar_ci", {"url": "https://github.com/o/r/actions/runs/9"}))

    payload = json.loads(text)
    assert payload["conclusao"] == "failure"
    assert payload["recibo"] == "ci-abc"
    assert payload["jobs"] == [{"nome": "backend", "conclusao": "failure"}]
    assert payload["commit"] == "a" * 40
    assert payload["repositorio"] == "o/r"


def test_verificar_ci_rejects_blank_or_huge_url():
    host = FakeHost()

    assert _call(host, "verificar_ci", {"url": " "})["is_error"] is True
    assert _call(host, "verificar_ci", {"url": "x" * 501})["is_error"] is True
    assert host.calls == []


def test_tools_cited_by_operating_skill_exist():
    import re

    from claudio_maestro.org.prompt import OPERATING_SKILL

    names = {t.name for t in build_tools(FakeHost(), agent_id=7, session_id="s")}
    cited = set(re.findall(r"`([a-z_]+)`", OPERATING_SKILL))
    statuses = {"in_progress", "in_review", "blocked", "done", "maestro"}  # not tools

    assert {"tarefas_listar", "tarefa_ler", "tarefa_criar", "decidir", "verificar_ci"} <= cited
    assert cited - statuses <= names
