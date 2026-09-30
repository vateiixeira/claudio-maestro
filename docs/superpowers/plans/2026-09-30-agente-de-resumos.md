# Agente de resumos: plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam caixas (`- [ ]`) para acompanhamento.

**Objetivo:** um agente único do app que lê, de tempos em tempos, as conversas em andamento e mantém um resumo em fases de cada uma (feito, falta, plano concluído), visível em Detalhes e na linha de conversa, configurável numa aba das Preferências.

**Arquitetura:** pacote novo `backend/vibing/digest/` com módulos pequenos: `store` (SQLite), `config` (configuração em `app_state`), `condense` (trecho novo da conversa em texto curto), `prompt` (prompt fixo e schema), `merge` (mescla que congela fases concluídas), `model` (interface do modelo, cliente real com `query()` do SDK e cliente falso) e `service` (passada e agendador). O `SessionManager` só ganha a frase curta e o selo no resumo da sessão. Rotas em `api/digest.py`. No frontend, um store `digest`, uma aba nova nas Preferências, uma seção em Detalhes e dois elementos na linha de conversa.

**Stack:** Python 3.13, FastAPI, SQLite, `claude-agent-sdk` 0.2.161, pytest; Vue 3, Pinia, TypeScript, Tailwind, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-agente-de-resumos-design.md`

## Pré-requisito

O marco 8 (`m8-agrupador`) e as melhorias de UI (`worktree-melhorias-ui-sessoes`) mexem em `db.py`, `sessions.py`, `DetailsPanel.vue` e `ConversationRow.vue`. Este plano parte do `main` **depois** de os dois estarem integrados. Antes da Tarefa 1:

1. Confirmar com `git log --oneline main` que os dois ramos entraram. Se não entraram, parar e avisar o usuário.
2. Criar a worktree `m10-resumos` a partir do `main` (superpowers:using-git-worktrees).
3. Rodar `uv run pytest -q` e `pnpm --dir frontend test` e anotar a linha de base.

Os números de linha citados abaixo são do ramo `m8-agrupador` em 2026-09-30; confira com `grep` antes de editar.

## Restrições globais

- Textos da interface e mensagens de erro em português brasileiro. Código e identificadores em inglês.
- No frontend, só `pnpm` (`pnpm --dir frontend test`, `pnpm --dir frontend exec vitest run <arquivo>`). Nunca `npx` nem `yarn`.
- Testes antes do código. Os testes automatizados nunca tocam o SDK real: o `SdkDigestModel` só roda no teste manual da Tarefa 15.
- Toda requisição a `/api/` leva `X-Vibing: 1` (o `request()` de `frontend/src/api/http.ts` já envia). Sem CORS, sem porta nova.
- O agente não tem ferramentas (`tools=[]`), usa `setting_sources=[]` e roda em `<data_dir>/digest-agent/`. Não configurar nem pedir `ANTHROPIC_API_KEY`.
- Configuração padrão: `enabled=False`, `model="sonnet"`, `effort="medium"`, `extra_instructions=""`, `interval_minutes=10`, `min_new_messages=10`, `open_turn_minutes=30`, `window_days=3`.
- Limites: instruções até 4.000 caracteres; intervalo 2 a 240; mínimo 1 a 500; teto 5 a 480; janela 1 a 30. Esforços: `low`, `medium`, `high`, `xhigh`, `max`. Aliases de modelo sempre aceitos: `default`, `opus`, `sonnet`, `haiku`.
- Resumo: `short` até 140 caracteres; até 20 fases; título de fase até 120; até 12 itens em `done` e em `pending`, 200 caracteres cada. Tipos de fase: `plan`, `spec`, `feature`, `adjustments`, `investigation`, `other`. Estados: `open`, `done`.
- Registro de passadas: só as 50 mais recentes.
- Tempo limite de uma leitura: 120 s.
- Eventos globais no WebSocket saem com `session_id: None` e `seq: 0` (como `project.synced`): `session.digest` com `{session_id, digest}` e `digest.status` com o estado do agente.
- Subagentes não fazem commit nem `git add`. O passo "Commit" de cada tarefa é da sessão principal, depois de o `reviewer` aprovar e os testes passarem.
- Mensagem de commit: `[Tipo] Título` em português, verbo no infinitivo, até 72 caracteres, sem ponto final.

## Pontos de atenção na revisão

1. Arquivo da sessão compactado ou reescrito: o cursor some, a leitura recomeça no resumo de compactação e as fases concluídas continuam lá (Tarefa 3, "cursor perdido"; Tarefa 5, "fases congeladas").
2. O modelo devolve fases concluídas alteradas, omitidas ou duas fases abertas: o que estava gravado prevalece e só a última fica aberta (Tarefa 5).
3. Desligar o agente no meio de uma passada: a passada para, fica registrada como "Desligado." e os resumos já gravados ficam (Tarefa 9, "desligar cancela").
4. Limite da assinatura ou login expirado no meio da passada: a passada para, o limite adia as passadas automáticas até a liberação e nada fica em laço (Tarefa 8, "parada"; Tarefa 9, "pausa").
5. A sessão do próprio agente vaza para o histórico quando `delete_session` falha: o índice a ignora (Tarefa 10, "pasta do agente ignorada"). Também: conversa apagada do banco durante a passada não derruba a passada (Tarefa 8, "sessão sumiu").

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `backend/vibing/db.py` | Migração nova: `session_digests` e `digest_runs` |
| `backend/vibing/digest/__init__.py` | Pacote (vazio) |
| `backend/vibing/digest/store.py` | `Digest`, leitura e gravação de resumos e do registro |
| `backend/vibing/digest/config.py` | `DigestConfig`, validação, leitura e gravação em `app_state` |
| `backend/vibing/digest/condense.py` | Trecho depois do cursor e condensação em texto |
| `backend/vibing/digest/prompt.py` | Prompt fixo, schema, specs citados, montagem do pedido |
| `backend/vibing/digest/merge.py` | Mescla da resposta com o resumo gravado |
| `backend/vibing/digest/model.py` | `DigestModel`, `FakeDigestModel`, `SdkDigestModel` |
| `backend/vibing/digest/service.py` | Elegibilidade, passada, fila, agendador, estado |
| `backend/vibing/conversation.py` | `classify_user_text` público |
| `backend/vibing/sessions.py` | `digest_short` e `plan_done` no resumo da sessão |
| `backend/vibing/api/sessions.py` | Campos novos em `SessionOut` |
| `backend/vibing/api/digest.py` | Rotas do agente |
| `backend/vibing/history.py` | `HistoryIndex` ignora a pasta do agente |
| `backend/vibing/app.py` | Cria o serviço e a tarefa do agendador |
| `scripts/digest_smoke.py` | Teste manual contra o SDK real |
| `frontend/src/types/api.ts` | Tipos do agente e campos novos de `Session` |
| `frontend/src/api/http.ts` | Chamadas às rotas novas |
| `frontend/src/stores/digest.ts` | Estado do agente e resumos por sessão |
| `frontend/src/stores/realtime.ts` | Eventos `session.digest` e `digest.status` |
| `frontend/src/digestConfig.ts` | Validação do formulário e textos de estado (puro) |
| `frontend/src/views/PreferencesView.vue` | Casca com abas |
| `frontend/src/components/preferences/GeneralPreferences.vue` | Conteúdo atual das Preferências |
| `frontend/src/components/preferences/DigestAgentPreferences.vue` | Aba do agente |
| `frontend/src/components/details/DigestSection.vue` | Seção "Resumo" em Detalhes |
| `frontend/src/components/details/DetailsPanel.vue` | Inclui a seção |
| `frontend/src/components/conversation/ConversationRow.vue` | Frase curta e "Plano concluído" |

---

### Tarefa 1: Tabelas e acesso ao banco

**Arquivos:**
- Modificar: `backend/vibing/db.py` (lista `MIGRATIONS`, depois do bloco do Marco 8)
- Criar: `backend/vibing/digest/__init__.py`, `backend/vibing/digest/store.py`
- Testar: `backend/tests/test_digest_store.py` (novo)

**Interfaces:**
- Consome: `vibing.db.connect`, `vibing.db.init_db`.
- Produz, em `vibing.digest.store`:
  - `MAX_RUNS = 50`
  - `@dataclass class Digest: session_id: str; cursor: str | None = None; read_at: int | None = None; short: str | None = None; phases: list[dict[str, Any]] = []; plan_done: bool = False; plan_ref: str | None = None; error: str | None = None; error_at: int | None = None` com `to_dict() -> dict` (sem `cursor` e `plan_ref`)
  - `get_digest(conn, session_id: str) -> Digest | None`
  - `save_digest(conn, digest: Digest) -> None` (grava tudo; `sqlite3.IntegrityError` se a sessão não existe)
  - `save_error(conn, session_id: str, message: str, at: int) -> Digest | None` (só `error` e `error_at`; None se a sessão não existe)
  - `briefs(conn) -> dict[str, tuple[str | None, bool]]` (`session_id -> (short, plan_done)`)
  - `start_run(conn, trigger: str, at: int) -> int`
  - `finish_run(conn, run_id: int, *, at: int, read_count: int, skipped_count: int, errors: list[dict], stopped: str | None) -> dict`
  - `list_runs(conn) -> list[dict]` (mais nova primeiro; `errors` já como lista)

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_store.py
"""Database access of the digest agent."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from vibing import db
from vibing.digest import store
from vibing.digest.store import Digest


@pytest.fixture
def conn(tmp_path: Path):
    path = tmp_path / "vibing.db"
    db.init_db(path)
    with closing(db.connect(path)) as c:
        c.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'app', '/tmp/app', '#fff', 0, 0)"
        )
        for sid in ("s1", "s2"):
            c.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at) VALUES (?, 1, '/tmp/app', 't', 0, 0)",
                (sid,),
            )
        yield c


def test_tables_exist(conn: sqlite3.Connection) -> None:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"session_digests", "digest_runs"} <= names


def test_save_and_get_round_trip(conn: sqlite3.Connection) -> None:
    phase = {"title": "Plano X", "kind": "plan", "status": "done", "done": ["a"],
             "pending": [], "ref": None}
    store.save_digest(conn, Digest("s1", cursor="u9", read_at=100, short="Faz X",
                                   phases=[phase], plan_done=True, plan_ref="/p.md"))
    got = store.get_digest(conn, "s1")
    assert got == Digest("s1", cursor="u9", read_at=100, short="Faz X", phases=[phase],
                         plan_done=True, plan_ref="/p.md")
    assert store.get_digest(conn, "s2") is None


def test_to_dict_hides_internal_fields() -> None:
    data = Digest("s1", cursor="u1", plan_ref="/p.md", short="x").to_dict()
    assert "cursor" not in data and "plan_ref" not in data
    assert data == {"session_id": "s1", "read_at": None, "short": "x", "phases": [],
                    "plan_done": False, "error": None, "error_at": None}


def test_save_error_keeps_the_summary(conn: sqlite3.Connection) -> None:
    store.save_digest(conn, Digest("s1", short="Faz X", read_at=5))
    got = store.save_error(conn, "s1", "Falhou.", 10)
    assert got is not None and got.short == "Faz X" and got.error == "Falhou." and got.error_at == 10
    fresh = store.save_error(conn, "s2", "Sem resumo.", 11)
    assert fresh is not None and fresh.short is None and fresh.error == "Sem resumo."


def test_save_error_for_unknown_session_returns_none(conn: sqlite3.Connection) -> None:
    assert store.save_error(conn, "nope", "x", 1) is None


def test_save_digest_for_unknown_session_fails(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.save_digest(conn, Digest("nope"))


def test_digest_goes_away_with_the_session(conn: sqlite3.Connection) -> None:
    store.save_digest(conn, Digest("s1", short="x"))
    conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    assert store.get_digest(conn, "s1") is None


def test_briefs(conn: sqlite3.Connection) -> None:
    store.save_digest(conn, Digest("s1", short="Faz X", plan_done=True))
    assert store.briefs(conn) == {"s1": ("Faz X", True)}


def test_runs_are_logged_newest_first_and_trimmed(conn: sqlite3.Connection) -> None:
    for i in range(store.MAX_RUNS + 5):
        run_id = store.start_run(conn, "auto", i)
        store.finish_run(conn, run_id, at=i + 1, read_count=1, skipped_count=2,
                         errors=[{"session_id": "s1", "title": "t", "message": "m"}],
                         stopped=None)
    runs = store.list_runs(conn)
    assert len(runs) == store.MAX_RUNS
    assert runs[0]["started_at"] == store.MAX_RUNS + 4
    assert runs[0] == {
        "id": runs[0]["id"], "started_at": store.MAX_RUNS + 4, "finished_at": store.MAX_RUNS + 5,
        "trigger": "auto", "read_count": 1, "skipped_count": 2,
        "errors": [{"session_id": "s1", "title": "t", "message": "m"}], "stopped": None,
    }


def test_finish_run_returns_the_run(conn: sqlite3.Connection) -> None:
    run_id = store.start_run(conn, "manual_all", 7)
    run = store.finish_run(conn, run_id, at=9, read_count=0, skipped_count=0, errors=[],
                           stopped="Desligado.")
    assert run["stopped"] == "Desligado." and run["trigger"] == "manual_all"
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_store.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'vibing.digest'`

- [x] **Passo 3: Acrescentar a migração**

No fim de `MIGRATIONS` em `backend/vibing/db.py`, depois do bloco do Marco 8:

```python
    [
        # Marco 10: summary of each conversation kept by the digest agent, and the
        # log of its passes (only the newest MAX_RUNS are kept).
        """
        CREATE TABLE session_digests (
          session_id  TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
          cursor      TEXT,
          read_at     INTEGER,
          short       TEXT,
          phases      TEXT NOT NULL DEFAULT '[]',
          plan_done   INTEGER NOT NULL DEFAULT 0,
          plan_ref    TEXT,
          error       TEXT,
          error_at    INTEGER
        )
        """,
        """
        CREATE TABLE digest_runs (
          id             INTEGER PRIMARY KEY,
          started_at     INTEGER NOT NULL,
          finished_at    INTEGER,
          trigger        TEXT NOT NULL,
          read_count     INTEGER NOT NULL DEFAULT 0,
          skipped_count  INTEGER NOT NULL DEFAULT 0,
          errors         TEXT NOT NULL DEFAULT '[]',
          stopped        TEXT
        )
        """,
    ],
```

- [x] **Passo 4: Escrever `store.py`**

`backend/vibing/digest/__init__.py` vazio, com a docstring `"""Digest agent: keeps a phased summary of each conversation in progress."""`.

```python
# backend/vibing/digest/store.py
"""Database access of the digest agent: session digests and the pass log."""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

MAX_RUNS = 50

_DIGEST_COLUMNS = (
    "session_id, cursor, read_at, short, phases, plan_done, plan_ref, error, error_at"
)
_RUN_COLUMNS = (
    "id, started_at, finished_at, trigger, read_count, skipped_count, errors, stopped"
)


@dataclass
class Digest:
    session_id: str
    # uuid of the last transcript entry already read; None before the first reading.
    cursor: str | None = None
    read_at: int | None = None
    short: str | None = None
    phases: list[dict[str, Any]] = field(default_factory=list)
    plan_done: bool = False
    # Plan path `plan_done` refers to: the seal only goes away when the linked plan changes.
    plan_ref: str | None = None
    error: str | None = None
    error_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """What the frontend receives (the cursor and plan_ref are internal)."""
        return {
            "session_id": self.session_id, "read_at": self.read_at, "short": self.short,
            "phases": self.phases, "plan_done": self.plan_done, "error": self.error,
            "error_at": self.error_at,
        }


def _digest(row: sqlite3.Row) -> Digest:
    try:
        phases = json.loads(row["phases"])
    except ValueError:
        phases = []
    return Digest(
        session_id=row["session_id"], cursor=row["cursor"], read_at=row["read_at"],
        short=row["short"], phases=phases if isinstance(phases, list) else [],
        plan_done=bool(row["plan_done"]), plan_ref=row["plan_ref"], error=row["error"],
        error_at=row["error_at"],
    )


def get_digest(conn: sqlite3.Connection, session_id: str) -> Digest | None:
    row = conn.execute(
        f"SELECT {_DIGEST_COLUMNS} FROM session_digests WHERE session_id = ?", (session_id,)
    ).fetchone()
    return None if row is None else _digest(row)


def save_digest(conn: sqlite3.Connection, digest: Digest) -> None:
    """Write every field. Raises sqlite3.IntegrityError when the session is gone."""
    conn.execute(
        f"INSERT INTO session_digests ({_DIGEST_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(session_id) DO UPDATE SET cursor = excluded.cursor,"
        " read_at = excluded.read_at, short = excluded.short, phases = excluded.phases,"
        " plan_done = excluded.plan_done, plan_ref = excluded.plan_ref,"
        " error = excluded.error, error_at = excluded.error_at",
        (
            digest.session_id, digest.cursor, digest.read_at, digest.short,
            json.dumps(digest.phases, ensure_ascii=False), int(digest.plan_done),
            digest.plan_ref, digest.error, digest.error_at,
        ),
    )


def save_error(conn: sqlite3.Connection, session_id: str, message: str, at: int) -> Digest | None:
    """Record a failed reading, keeping the last summary. None when the session is gone."""
    try:
        conn.execute(
            "INSERT INTO session_digests (session_id, error, error_at) VALUES (?, ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET error = excluded.error,"
            " error_at = excluded.error_at",
            (session_id, message, at),
        )
    except sqlite3.IntegrityError:
        return None
    return get_digest(conn, session_id)


def briefs(conn: sqlite3.Connection) -> dict[str, tuple[str | None, bool]]:
    """Short sentence and plan seal of every digested session."""
    return {
        row["session_id"]: (row["short"], bool(row["plan_done"]))
        for row in conn.execute("SELECT session_id, short, plan_done FROM session_digests")
    }


def _run(row: sqlite3.Row) -> dict[str, Any]:
    run = {key: row[key] for key in row.keys()}
    try:
        errors = json.loads(run["errors"])
    except ValueError:
        errors = []
    run["errors"] = errors if isinstance(errors, list) else []
    return run


def start_run(conn: sqlite3.Connection, trigger: str, at: int) -> int:
    cursor = conn.execute(
        "INSERT INTO digest_runs (started_at, trigger) VALUES (?, ?)", (at, trigger)
    )
    return int(cursor.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    at: int,
    read_count: int,
    skipped_count: int,
    errors: list[dict[str, Any]],
    stopped: str | None,
) -> dict[str, Any]:
    conn.execute(
        "UPDATE digest_runs SET finished_at = ?, read_count = ?, skipped_count = ?,"
        " errors = ?, stopped = ? WHERE id = ?",
        (at, read_count, skipped_count, json.dumps(errors, ensure_ascii=False), stopped, run_id),
    )
    conn.execute(
        "DELETE FROM digest_runs WHERE id NOT IN"
        " (SELECT id FROM digest_runs ORDER BY id DESC LIMIT ?)",
        (MAX_RUNS,),
    )
    row = conn.execute(f"SELECT {_RUN_COLUMNS} FROM digest_runs WHERE id = ?", (run_id,)).fetchone()
    return _run(row)


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        _run(row)
        for row in conn.execute(f"SELECT {_RUN_COLUMNS} FROM digest_runs ORDER BY id DESC")
    ]
```

- [x] **Passo 5: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_store.py backend/tests/test_db.py -q`
Expected: PASS

- [x] **Passo 6: Rodar a suíte do backend**

Run: `uv run pytest -q`
Expected: PASS (mesma contagem da linha de base mais os testes novos)

- [x] **Passo 7: Commit**

```bash
git add backend/vibing/db.py backend/vibing/digest/__init__.py backend/vibing/digest/store.py backend/tests/test_digest_store.py
git commit -m "[Feat] Criar tabelas de resumos e do registro do agente"
```

---

### Tarefa 2: Configuração do agente

**Arquivos:**
- Criar: `backend/vibing/digest/config.py`
- Testar: `backend/tests/test_digest_config.py` (novo)

**Interfaces:**
- Consome: tabela `app_state` (chave, valor JSON).
- Produz, em `vibing.digest.config`:
  - `CONFIG_KEY = "digest_agent"`, `EFFORTS`, `MODEL_ALIASES`, `MAX_INSTRUCTIONS = 4000`, `LIMITS: dict[str, tuple[int, int]]`, `MESSAGES: dict[str, str]`
  - `@dataclass(frozen=True) class DigestConfig` com os campos e padrões das restrições globais; `to_dict() -> dict`
  - `class ConfigError(ValueError)` com `errors: dict[str, str]` (campo → mensagem)
  - `model_known(model: str, known: Iterable[str]) -> bool`
  - `coerce(raw: Any) -> DigestConfig` (valor guardado; inválido cai no padrão campo a campo)
  - `validate(raw: Any, known_models: Iterable[str]) -> DigestConfig` (corpo do PUT; levanta `ConfigError` com todos os erros)
  - `load_config(conn) -> DigestConfig`, `save_config(conn, config: DigestConfig) -> None`

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_config.py
"""Settings of the digest agent."""

from contextlib import closing
from pathlib import Path

import pytest

from vibing import db
from vibing.digest.config import (
    MESSAGES,
    ConfigError,
    DigestConfig,
    coerce,
    load_config,
    model_known,
    save_config,
    validate,
)

KNOWN = ["default", "opus", "sonnet", "haiku", "claude-sonnet-5-5"]


def test_defaults() -> None:
    assert DigestConfig().to_dict() == {
        "enabled": False, "model": "sonnet", "effort": "medium", "extra_instructions": "",
        "interval_minutes": 10, "min_new_messages": 10, "open_turn_minutes": 30,
        "window_days": 3,
    }


def test_coerce_keeps_valid_fields_and_defaults_the_rest() -> None:
    cfg = coerce({"enabled": True, "interval_minutes": 0, "effort": "xhigh", "model": 3})
    assert cfg.enabled is True and cfg.effort == "xhigh"
    assert cfg.interval_minutes == 10 and cfg.model == "sonnet"
    assert coerce(None) == DigestConfig()
    assert coerce([1, 2]) == DigestConfig()


def test_validate_accepts_a_full_body() -> None:
    body = {**DigestConfig().to_dict(), "enabled": True, "model": "claude-sonnet-5-5",
            "extra_instructions": "Cite a tarefa."}
    assert validate(body, KNOWN) == DigestConfig(
        enabled=True, model="claude-sonnet-5-5", extra_instructions="Cite a tarefa."
    )


def test_validate_fills_missing_fields_with_defaults() -> None:
    assert validate({"enabled": True}, KNOWN) == DigestConfig(enabled=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("enabled", "sim"),
        ("model", "gpt-4"),
        ("effort", "huge"),
        ("extra_instructions", "x" * 4001),
        ("interval_minutes", 1),
        ("interval_minutes", 241),
        ("interval_minutes", True),
        ("min_new_messages", 0),
        ("open_turn_minutes", 4),
        ("window_days", 31),
        ("window_days", 2.5),
    ],
)
def test_validate_rejects_each_bad_field(field: str, value: object) -> None:
    with pytest.raises(ConfigError) as info:
        validate({field: value}, KNOWN)
    assert info.value.errors == {field: MESSAGES[field]}


def test_validate_reports_every_error_and_unknown_fields() -> None:
    with pytest.raises(ConfigError) as info:
        validate({"window_days": 0, "effort": "x", "color": "red"}, KNOWN)
    assert set(info.value.errors) == {"window_days", "effort", "color"}
    assert info.value.errors["color"] == "Campo desconhecido: color."


def test_validate_rejects_a_non_object() -> None:
    with pytest.raises(ConfigError) as info:
        validate([1], KNOWN)
    assert info.value.errors == {"body": "Envie a configuração como um objeto."}


def test_aliases_are_always_known() -> None:
    assert model_known("haiku", [])
    assert not model_known("claude-x", [])
    assert model_known("claude-x", ["claude-x"])


def test_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "v.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        assert load_config(conn) == DigestConfig()
        save_config(conn, DigestConfig(enabled=True, window_days=7))
        assert load_config(conn) == DigestConfig(enabled=True, window_days=7)
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_config.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'vibing.digest.config'`

- [x] **Passo 3: Escrever `config.py`**

```python
# backend/vibing/digest/config.py
"""Settings of the digest agent, kept in `app_state` under `digest_agent`."""

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from typing import Any

CONFIG_KEY = "digest_agent"
EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
MODEL_ALIASES: tuple[str, ...] = ("default", "opus", "sonnet", "haiku")
MAX_INSTRUCTIONS = 4000
LIMITS: dict[str, tuple[int, int]] = {
    "interval_minutes": (2, 240),
    "min_new_messages": (1, 500),
    "open_turn_minutes": (5, 480),
    "window_days": (1, 30),
}
MESSAGES: dict[str, str] = {
    "enabled": "Ligado precisa ser verdadeiro ou falso.",
    "model": "Escolha um modelo da lista.",
    "effort": "Escolha um nível de raciocínio da lista.",
    "extra_instructions": "As instruções extras podem ter até 4.000 caracteres.",
    "interval_minutes": "O intervalo precisa ser um número inteiro de 2 a 240 minutos.",
    "min_new_messages": "O mínimo de mensagens novas precisa ser um número inteiro de 1 a 500.",
    "open_turn_minutes": "O teto com turno aberto precisa ser um número inteiro de 5 a 480 minutos.",
    "window_days": "A janela precisa ser um número inteiro de 1 a 30 dias.",
}


@dataclass(frozen=True)
class DigestConfig:
    enabled: bool = False
    model: str = "sonnet"
    effort: str = "medium"
    extra_instructions: str = ""
    interval_minutes: int = 10
    min_new_messages: int = 10
    open_turn_minutes: int = 30
    window_days: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FIELD_NAMES = tuple(f.name for f in fields(DigestConfig))


class ConfigError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(" ".join(errors.values()))
        self.errors = errors


def model_known(model: str, known: Iterable[str]) -> bool:
    return model in MODEL_ALIASES or model in set(known)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _field_ok(name: str, value: Any, known_models: Iterable[str] | None) -> bool:
    """`known_models=None` accepts any well-formed model id (stored values)."""
    if name == "enabled":
        return isinstance(value, bool)
    if name == "model":
        if not isinstance(value, str) or not 1 <= len(value) <= 100:
            return False
        return known_models is None or model_known(value, known_models)
    if name == "effort":
        return value in EFFORTS
    if name == "extra_instructions":
        return isinstance(value, str) and len(value) <= MAX_INSTRUCTIONS
    low, high = LIMITS[name]
    return _is_int(value) and low <= value <= high


def coerce(raw: Any) -> DigestConfig:
    """Stored value to config: a missing or invalid field takes the default."""
    if not isinstance(raw, dict):
        return DigestConfig()
    values = {
        name: raw[name] for name in FIELD_NAMES
        if name in raw and _field_ok(name, raw[name], None)
    }
    return DigestConfig(**values)


def validate(raw: Any, known_models: Iterable[str]) -> DigestConfig:
    """Body of `PUT /api/digest/config`. Missing fields take the default."""
    if not isinstance(raw, dict):
        raise ConfigError({"body": "Envie a configuração como um objeto."})
    known = list(known_models)
    errors: dict[str, str] = {}
    for name in raw:
        if name not in FIELD_NAMES:
            errors[name] = f"Campo desconhecido: {name}."
    for name in FIELD_NAMES:
        if name in raw and not _field_ok(name, raw[name], known):
            errors[name] = MESSAGES[name]
    if errors:
        raise ConfigError(errors)
    return DigestConfig(**{name: raw[name] for name in FIELD_NAMES if name in raw})


def load_config(conn: sqlite3.Connection) -> DigestConfig:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (CONFIG_KEY,)).fetchone()
    if row is None:
        return DigestConfig()
    try:
        return coerce(json.loads(row["value"]))
    except ValueError:
        return DigestConfig()


def save_config(conn: sqlite3.Connection, config: DigestConfig) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (CONFIG_KEY, json.dumps(config.to_dict(), ensure_ascii=False)),
    )
```

- [x] **Passo 4: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_config.py -q`
Expected: PASS

- [x] **Passo 5: Roadmap**

Em `ROADMAP.md`, marco 10: trocar o estado para "Em andamento" na tabela, marcar `[x] Configuração do agente em app_state e tabelas session_digests e digest_runs (AAAA-MM-DD)` e atualizar a contagem ("1 de 10").

- [x] **Passo 6: Commit**

```bash
git add backend/vibing/digest/config.py backend/tests/test_digest_config.py ROADMAP.md
git commit -m "[Feat] Adicionar configuração do agente de resumos"
```

---

### Tarefa 3: Leitura incremental e condensação

**Arquivos:**
- Modificar: `backend/vibing/conversation.py` (acrescentar `classify_user_text` público logo depois de `_classify_user_text`)
- Criar: `backend/vibing/digest/condense.py`
- Testar: `backend/tests/test_digest_condense.py` (novo)

**Interfaces:**
- Consome: `vibing.history.Transcript` (`messages`: objetos com `type`, `uuid`, `message`; `tool_results: {tool_use_id: {"is_error": bool, ...}}`; `compact_uuids: set[str]`), `vibing.conversation.COMPACT_SUMMARY_PREFIX`.
- Produz, em `vibing.conversation`: `classify_user_text(text: str) -> tuple[str, str | None]`.
- Produz, em `vibing.digest.condense`:
  - `USER_LIMIT = 4000`, `CLAUDE_LIMIT = 1500`, `BASH_LIMIT = 200`, `DEFAULT_BUDGET = 60_000`, `FILE_TOOLS`
  - `@dataclass class Slice: messages: list[Any]; cursor: str | None; cursor_found: bool`
  - `entries_after(transcript: Transcript, cursor: str | None) -> Slice`
  - `@dataclass class Condensed: text: str; count: int; paths: list[str]`
  - `tool_line(name: str, tool_input: Any, cwd: str | None) -> str`
  - `condense(messages: list[Any], tool_results: dict[str, dict], cwd: str | None, budget: int = DEFAULT_BUDGET) -> Condensed`

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_condense.py
"""Slice after the cursor and condensed text of a transcript."""

from types import SimpleNamespace

from vibing.conversation import COMPACT_SUMMARY_PREFIX
from vibing.digest.condense import (
    Condensed,
    condense,
    entries_after,
    tool_line,
)
from vibing.history import Transcript

CWD = "/home/vi/dev/app"


def user(uuid: str, content) -> SimpleNamespace:
    return SimpleNamespace(type="user", uuid=uuid, message={"role": "user", "content": content})


def claude(uuid: str, *blocks) -> SimpleNamespace:
    return SimpleNamespace(
        type="assistant", uuid=uuid, message={"role": "assistant", "content": list(blocks)}
    )


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def tool(tool_id: str, name: str, **inp) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": inp}


def transcript(*messages, compact=(), results=None) -> Transcript:
    return Transcript(messages=list(messages), tool_results=results or {},
                      compact_uuids=set(compact))


# entries_after ---------------------------------------------------------------

def test_first_reading_takes_everything() -> None:
    t = transcript(user("u1", "oi"), claude("a1", text("olá")))
    s = entries_after(t, None)
    assert [m.uuid for m in s.messages] == ["u1", "a1"]
    assert s.cursor == "a1" and s.cursor_found is True


def test_takes_only_what_follows_the_cursor() -> None:
    t = transcript(user("u1", "oi"), claude("a1", text("olá")), user("u2", "mais"))
    s = entries_after(t, "a1")
    assert [m.uuid for m in s.messages] == ["u2"] and s.cursor == "u2" and s.cursor_found


def test_nothing_new_keeps_the_cursor() -> None:
    t = transcript(user("u1", "oi"))
    s = entries_after(t, "u1")
    assert s.messages == [] and s.cursor == "u1" and s.cursor_found


def test_lost_cursor_restarts_at_the_last_compaction() -> None:
    t = transcript(user("c1", COMPACT_SUMMARY_PREFIX + " resumo"), user("u5", "segue"),
                   compact=["c1"])
    s = entries_after(t, "sumiu")
    assert [m.uuid for m in s.messages] == ["c1", "u5"] and s.cursor_found is False


def test_lost_cursor_without_compaction_restarts_at_the_beginning() -> None:
    t = transcript(user("u1", "oi"), user("u2", "mais"))
    s = entries_after(t, "sumiu")
    assert [m.uuid for m in s.messages] == ["u1", "u2"] and s.cursor_found is False


# tool_line -------------------------------------------------------------------

def test_tool_lines() -> None:
    assert tool_line("Edit", {"file_path": f"{CWD}/backend/x.py"}, CWD) == "[Edit] backend/x.py"
    assert tool_line("Read", {"file_path": "/etc/hosts"}, CWD) == "[Read] /etc/hosts"
    assert tool_line("Bash", {"command": "uv run   pytest\n -q"}, CWD) == "[Bash] uv run pytest -q"
    assert tool_line("Bash", {"command": "x" * 300}, CWD) == "[Bash] " + "x" * 200 + "…"
    assert tool_line("Task", {"subagent_type": "implementer", "description": "Tarefa 3"}, CWD) \
        == "[Task] implementer: Tarefa 3"
    assert tool_line("Agent", {"description": "Buscar"}, CWD) == "[Agent] agente: Buscar"
    assert tool_line("Skill", {"skill": "superpowers:brainstorming"}, CWD) \
        == "[Skill] superpowers:brainstorming"
    assert tool_line("Grep", {"pattern": "def x"}, CWD) == "[Grep] def x"
    assert tool_line("WebFetch", {"url": "https://x"}, CWD) == "[WebFetch]"
    assert tool_line("Edit", None, CWD) == "[Edit]"


# condense --------------------------------------------------------------------

def test_condense_formats_each_kind() -> None:
    messages = [
        user("u1", "Execute o plano X"),
        claude("a1", {"type": "thinking", "thinking": "hmm"}, text("Vou começar."),
               tool("t1", "Edit", file_path=f"{CWD}/a.py"), tool("t2", "Bash", command="pytest")),
        user("r1", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
        user("u2", "<command-name>/model</command-name>"),
        user("u3", [text("Agora ajuste o menu"), {"type": "image", "source": {}}]),
    ]
    out = condense(messages, {"t2": {"is_error": True}}, CWD)
    assert out.text.splitlines() == [
        "[Você] Execute o plano X",
        "[Claude] Vou começar.",
        "[Edit] a.py",
        "[Bash] pytest (falhou)",
        "[Você] Agora ajuste o menu",
    ]
    assert out.count == 5
    assert out.paths == [f"{CWD}/a.py"]


def test_condense_marks_compaction_and_cuts_long_texts() -> None:
    long = "y" * 5000
    out = condense([user("c1", COMPACT_SUMMARY_PREFIX + " " + long),
                    claude("a1", text("z" * 2000))], {}, CWD)
    lines = out.text.splitlines()
    assert lines[0].startswith("[Compactação] " + COMPACT_SUMMARY_PREFIX)
    assert len(lines[0]) == len("[Compactação] ") + 4000 + 1
    assert lines[1] == "[Claude] " + "z" * 1500 + "…"


def test_condense_paths_are_unique_and_ordered() -> None:
    out = condense([claude("a1", tool("t1", "Read", file_path="/p/b.md"),
                           tool("t2", "Edit", file_path="/p/a.md"),
                           tool("t3", "Read", file_path="/p/b.md"))], {}, None)
    assert out.paths == ["/p/b.md", "/p/a.md"]


def test_over_budget_keeps_every_prompt_and_both_ends() -> None:
    messages = [user("u0", "Pedido inicial")]
    messages += [claude(f"a{i}", text(f"resposta {i:03d} " + "x" * 80)) for i in range(100)]
    messages += [user("u9", "Pedido final")]
    out = condense(messages, {}, CWD, budget=2000)
    lines = out.text.splitlines()
    assert lines[0] == "[Você] Pedido inicial" and lines[-1] == "[Você] Pedido final"
    assert "resposta 000" in out.text and "resposta 099" in out.text
    assert any(line.startswith("[… ") and line.endswith(" entradas omitidas …]") for line in lines)
    assert len(out.text) <= 2000 + 200  # the marker lines are not counted
    assert out.count == 102


def test_empty_slice() -> None:
    assert condense([], {}, CWD) == Condensed(text="", count=0, paths=[])
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_condense.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'vibing.digest.condense'`

- [x] **Passo 3: Expor `classify_user_text`**

Em `backend/vibing/conversation.py`, logo depois da função `_classify_user_text`:

```python
def classify_user_text(text: str) -> tuple[str, str | None]:
    """Public name of `_classify_user_text`, used by the digest agent."""
    return _classify_user_text(text)
```

- [x] **Passo 4: Escrever `condense.py`**

```python
# backend/vibing/digest/condense.py
"""What the digest agent reads: the transcript entries after the cursor, as short text.

Pure: the transcript is read by the caller (history.read_transcript_at).
"""

import os
from dataclasses import dataclass
from typing import Any

from vibing.conversation import COMPACT_SUMMARY_PREFIX, classify_user_text
from vibing.history import Transcript

USER_LIMIT = 4000
CLAUDE_LIMIT = 1500
BASH_LIMIT = 200
DEFAULT_BUDGET = 60_000
FILE_TOOLS = frozenset({"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"})
SUBAGENT_TOOLS = frozenset({"Task", "Agent"})


@dataclass
class Slice:
    messages: list[Any]
    # uuid of the last message of the slice; the old cursor when nothing is new.
    cursor: str | None
    # False when the old cursor was not in the file (compacted or rewritten).
    cursor_found: bool


@dataclass
class Condensed:
    text: str
    # Condensable entries (prompts, Claude texts, tool calls, compaction summaries).
    count: int
    # Files read or edited, absolute, first appearance order, no repeats.
    paths: list[str]


def entries_after(transcript: Transcript, cursor: str | None) -> Slice:
    messages = transcript.messages
    if cursor is None:
        start, found = 0, True
    else:
        index = next((i for i, m in enumerate(messages) if m.uuid == cursor), None)
        if index is not None:
            start, found = index + 1, True
        else:
            compacts = [i for i, m in enumerate(messages) if m.uuid in transcript.compact_uuids]
            start, found = (compacts[-1] if compacts else 0), False
    rest = messages[start:]
    return Slice(rest, rest[-1].uuid if rest else cursor, found)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _relative(path: str, cwd: str | None) -> str:
    if cwd and (path == cwd or path.startswith(cwd.rstrip(os.sep) + os.sep)):
        return os.path.relpath(path, cwd)
    return path


def tool_line(name: str, tool_input: Any, cwd: str | None) -> str:
    inp = tool_input if isinstance(tool_input, dict) else {}
    if name in FILE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path")
        return f"[{name}] {_relative(path, cwd)}" if isinstance(path, str) else f"[{name}]"
    if name == "Bash" and isinstance(inp.get("command"), str):
        return f"[Bash] {_clip(' '.join(inp['command'].split()), BASH_LIMIT)}"
    if name in SUBAGENT_TOOLS:
        kind = inp.get("subagent_type") or "agente"
        return f"[{name}] {kind}: {inp.get('description') or ''}".rstrip()
    if name == "Skill" and isinstance(inp.get("skill"), str):
        return f"[Skill] {inp['skill']}"
    if name in ("Grep", "Glob") and isinstance(inp.get("pattern"), str):
        return f"[{name}] {inp['pattern']}"
    return f"[{name}]"


def _user_texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            b["text"] for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
    return []


def _lines(
    messages: list[Any], tool_results: dict[str, dict[str, Any]], cwd: str | None
) -> tuple[list[tuple[str, str]], list[str]]:
    lines: list[tuple[str, str]] = []  # (kind, text); kind "user" is never omitted
    paths: dict[str, None] = {}
    for message in messages:
        body = message.message if isinstance(message.message, dict) else {}
        content = body.get("content")
        if message.type == "user":
            for raw in _user_texts(content):
                if raw.lstrip().startswith(COMPACT_SUMMARY_PREFIX):
                    lines.append(("other", "[Compactação] " + _clip(raw.strip(), USER_LIMIT)))
                    continue
                kept, _notice = classify_user_text(raw)
                if kept:
                    lines.append(("user", "[Você] " + _clip(kept, USER_LIMIT)))
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                value = block["text"].strip()
                if value:
                    lines.append(("other", "[Claude] " + _clip(value, CLAUDE_LIMIT)))
            elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                name, inp = block["name"], block.get("input")
                line = tool_line(name, inp, cwd)
                result = tool_results.get(block.get("id") or "", {})
                if result.get("is_error"):
                    line += " (falhou)"
                lines.append(("other", line))
                if name in FILE_TOOLS and isinstance(inp, dict):
                    path = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(path, str):
                        paths[path] = None
    return lines, list(paths)


def _fit(lines: list[tuple[str, str]], budget: int) -> str:
    sizes = [len(text) + 1 for _, text in lines]
    if sum(sizes) <= budget:
        return "\n".join(text for _, text in lines)
    user_total = sum(size for (kind, _), size in zip(lines, sizes) if kind == "user")
    room = max(budget - user_total, 0)
    others = [i for i, (kind, _) in enumerate(lines) if kind != "user"]
    keep: set[int] = set()
    head = 0
    for i in others:
        if head + sizes[i] > room // 2:
            break
        keep.add(i)
        head += sizes[i]
    tail = 0
    for i in reversed(others):
        if i in keep or tail + sizes[i] > room - head:
            break
        keep.add(i)
        tail += sizes[i]
    out: list[str] = []
    omitted = 0
    for i, (kind, text) in enumerate(lines):
        if kind == "user" or i in keep:
            if omitted:
                out.append(f"[… {omitted} entradas omitidas …]")
                omitted = 0
            out.append(text)
        else:
            omitted += 1
    if omitted:
        out.append(f"[… {omitted} entradas omitidas …]")
    return "\n".join(out)


def condense(
    messages: list[Any],
    tool_results: dict[str, dict[str, Any]],
    cwd: str | None,
    budget: int = DEFAULT_BUDGET,
) -> Condensed:
    lines, paths = _lines(messages, tool_results, cwd)
    return Condensed(text=_fit(lines, budget), count=len(lines), paths=paths)
```

- [x] **Passo 5: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_condense.py backend/tests/test_conversation.py -q`
Expected: PASS

- [x] **Passo 6: Roadmap**

Marcar `[x] Leitura incremental do .jsonl por cursor e condensação do trecho (AAAA-MM-DD)` e atualizar a contagem.

- [x] **Passo 7: Commit**

```bash
git add backend/vibing/conversation.py backend/vibing/digest/condense.py backend/tests/test_digest_condense.py ROADMAP.md
git commit -m "[Feat] Condensar trecho novo da conversa para o agente de resumos"
```

---

### Tarefa 4: Prompt fixo, schema e specs citados

**Arquivos:**
- Criar: `backend/vibing/digest/prompt.py`
- Testar: `backend/tests/test_digest_prompt.py` (novo)

**Interfaces:**
- Consome: `vibing.plans.PlanProgress`, `vibing.plans._read_limited` (leitor limitado de arquivos), `vibing.digest.store.Digest`.
- Produz, em `vibing.digest.prompt`:
  - `PHASE_KINDS: tuple[str, ...]`, `PHASE_STATUSES = ("open", "done")`, `SHORT_LIMIT = 140`, `TITLE_LIMIT = 120`, `ITEM_LIMIT = 200`, `MAX_ITEMS = 12`, `MAX_PHASES = 20`, `MAX_SPECS = 10`
  - `SYSTEM_PROMPT: str`, `DIGEST_SCHEMA: dict`
  - `system_prompt(extra_instructions: str) -> str`
  - `is_spec_path(path: str | Path, roots: Iterable[Path]) -> Path | None`
  - `spec_refs(paths: Iterable[str], roots: Iterable[Path]) -> list[tuple[str, str]]` (bloqueante: lê disco)
  - `build_prompt(*, project: str, title: str, digest: Digest | None, plan: tuple[str, PlanProgress] | None, specs: list[tuple[str, str]], text: str, restarted: bool) -> str`

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_prompt.py
"""Fixed prompt, schema and request text of the digest agent."""

import json
from pathlib import Path

from vibing.digest.prompt import (
    DIGEST_SCHEMA,
    PHASE_KINDS,
    SYSTEM_PROMPT,
    build_prompt,
    is_spec_path,
    spec_refs,
    system_prompt,
)
from vibing.digest.store import Digest
from vibing.plans import PlanProgress, PlanTask


def write_spec(root: Path, name: str, text: str) -> Path:
    folder = root / "docs" / "superpowers" / "specs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def test_system_prompt_keeps_the_rules_and_adds_extras() -> None:
    assert "status \"done\"" in SYSTEM_PROMPT and "português do Brasil" in SYSTEM_PROMPT
    assert system_prompt("") == SYSTEM_PROMPT
    extra = system_prompt("Cite a tarefa.")
    assert extra.startswith(SYSTEM_PROMPT)
    assert extra.endswith("Instruções extras do usuário:\nCite a tarefa.")


def test_schema_lists_the_phase_kinds() -> None:
    phase = DIGEST_SCHEMA["properties"]["phases"]["items"]
    assert phase["properties"]["kind"]["enum"] == list(PHASE_KINDS)
    assert set(DIGEST_SCHEMA["required"]) == {"short", "phases", "plan_completed", "plan_evidence"}


def test_spec_path_must_be_inside_a_project(tmp_path: Path) -> None:
    root = tmp_path / "app"
    spec = write_spec(root, "a.md", "# Spec A\n")
    assert is_spec_path(spec, [root]) == spec
    assert is_spec_path(spec, [tmp_path / "other"]) is None
    assert is_spec_path(root / "README.md", [root]) is None


def test_spec_refs_reads_titles_once(tmp_path: Path) -> None:
    root = tmp_path / "app"
    a = write_spec(root, "a.md", "texto\n# Spec A\n")
    b = write_spec(root, "b.md", "sem título\n")
    refs = spec_refs([str(a), str(b), str(a), str(root / "x.py")], [root])
    assert refs == [(str(a), "Spec A"), (str(b), "b")]


def test_build_prompt_sections() -> None:
    plan = PlanProgress("Plano X", (PlanTask(1, "A", True), PlanTask(2, "B", False)))
    old = Digest("s1", short="Faz X", phases=[{"title": "P", "kind": "plan", "status": "open",
                                                "done": [], "pending": [], "ref": None}])
    text = build_prompt(project="app", title="Sessão", digest=old,
                        plan=("/p/plano.md", plan), specs=[("/p/s.md", "Spec S")],
                        text="[Você] oi", restarted=False)
    assert "## Sessão\nProjeto: app\nTítulo: Sessão" in text
    assert json.dumps({"short": "Faz X", "phases": old.phases}, ensure_ascii=False) in text
    assert "Caminho: /p/plano.md\nTítulo: Plano X (1/2)\n- [x] Tarefa 1: A\n- [ ] Tarefa 2: B" in text
    assert "- /p/s.md: Spec S" in text
    assert text.endswith("## Trecho novo da conversa\n[Você] oi")
    assert "compactado" not in text


def test_build_prompt_without_summary_plan_or_specs() -> None:
    text = build_prompt(project="app", title="t", digest=None, plan=None, specs=[],
                        text="[Você] oi", restarted=True)
    assert "## Resumo atual\nSem resumo." in text
    assert "## Plano vinculado\nNenhum." in text
    assert "## Specs citados\nNenhum." in text
    assert "compactado ou reescrito" in text
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_prompt.py -q`
Expected: FAIL com `ModuleNotFoundError`

- [x] **Passo 3: Escrever `prompt.py`**

```python
# backend/vibing/digest/prompt.py
"""What the digest agent is told: fixed rules, answer schema and the request text."""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from vibing.digest.store import Digest
from vibing.plans import PlanProgress, _read_limited

PHASE_KINDS: tuple[str, ...] = ("plan", "spec", "feature", "adjustments", "investigation", "other")
PHASE_STATUSES: tuple[str, ...] = ("open", "done")
SHORT_LIMIT = 140
TITLE_LIMIT = 120
ITEM_LIMIT = 200
MAX_ITEMS = 12
MAX_PHASES = 20
MAX_SPECS = 10
SPEC_DIR = ("docs", "superpowers", "specs")

SYSTEM_PROMPT = """Você mantém o resumo de trabalho de uma sessão do Claude Code, para o dono dela acompanhar sem reler a conversa. Escreva em português do Brasil, com frases curtas e concretas, sem adjetivos.

Você recebe o resumo atual (pode estar vazio), o plano vinculado à sessão com o estado de cada tarefa, os specs citados e um trecho novo da conversa, condensado: [Você] são os pedidos do usuário, [Claude] as respostas, e linhas como [Edit] caminho são ferramentas usadas.

Regras:
1. Divida o trabalho em fases pela intenção dos pedidos do usuário. Executar um plano, os ajustes feitos depois dele e uma feature nova são fases diferentes. Investigar um problema também é uma fase.
2. Devolva todas as fases, em ordem. As fases com status "done" do resumo atual voltam exatamente como estão. Você pode atualizar a fase "open", fechá-la ("done") e abrir fases novas. No máximo uma fase fica "open", sempre a última.
3. "done" lista entregas concluídas e "pending" o que falta, cada item com até 200 caracteres e no máximo 12 itens. Cite o número da tarefa do plano quando houver ("Tarefa 4: rotas de agrupador").
4. "kind": plan (execução de um plano), spec (escrita de spec ou design), feature, adjustments (ajustes e correções), investigation, other.
5. "ref": caminho absoluto do plano ou spec da fase, copiado das entradas; senão null.
6. "short": o que a sessão faz agora, em até 140 caracteres.
7. "plan_completed": true só se o trecho mostrar que o plano vinculado terminou (todas as tarefas concluídas, revisão final aprovada). Cite essa evidência em "plan_evidence"; senão false e null.
8. Não invente. O que o trecho não mostra, você não afirma."""

_PHASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "kind", "status", "done", "pending", "ref"],
    "properties": {
        "title": {"type": "string"},
        "kind": {"type": "string", "enum": list(PHASE_KINDS)},
        "status": {"type": "string", "enum": list(PHASE_STATUSES)},
        "done": {"type": "array", "items": {"type": "string"}},
        "pending": {"type": "array", "items": {"type": "string"}},
        "ref": {"type": ["string", "null"]},
    },
}

DIGEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["short", "phases", "plan_completed", "plan_evidence"],
    "properties": {
        "short": {"type": "string"},
        "phases": {"type": "array", "items": _PHASE_SCHEMA},
        "plan_completed": {"type": "boolean"},
        "plan_evidence": {"type": ["string", "null"]},
    },
}


def system_prompt(extra_instructions: str) -> str:
    extra = extra_instructions.strip()
    if not extra:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\nInstruções extras do usuário:\n{extra}"


def is_spec_path(path: str | Path, roots: Iterable[Path]) -> Path | None:
    """Resolved path of a `.md` directly inside `docs/superpowers/specs/` of a project."""
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if resolved.suffix.lower() != ".md" or tuple(resolved.parent.parts[-3:]) != SPEC_DIR:
        return None
    for root in roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return resolved
        except (OSError, RuntimeError):
            continue
    return None


def _title(path: Path) -> str:
    text = _read_limited(path)
    if text:
        for line in text.splitlines():
            if line.startswith("# "):
                return line[2:].strip() or path.stem
    return path.stem


def spec_refs(paths: Iterable[str], roots: Iterable[Path]) -> list[tuple[str, str]]:
    """(path, title) of the specs among `paths`, each once, at most MAX_SPECS. Blocking."""
    root_list = list(roots)
    seen: dict[Path, None] = {}
    for raw in paths:
        resolved = is_spec_path(raw, root_list)
        if resolved is not None and resolved not in seen:
            seen[resolved] = None
        if len(seen) >= MAX_SPECS:
            break
    return [(str(p), _title(p)) for p in seen]


def build_prompt(
    *,
    project: str,
    title: str,
    digest: Digest | None,
    plan: tuple[str, PlanProgress] | None,
    specs: list[tuple[str, str]],
    text: str,
    restarted: bool,
) -> str:
    parts = [f"## Sessão\nProjeto: {project}\nTítulo: {title}"]
    if digest is not None and (digest.short or digest.phases):
        current = json.dumps({"short": digest.short, "phases": digest.phases}, ensure_ascii=False)
        parts.append(f"## Resumo atual\n{current}")
    else:
        parts.append("## Resumo atual\nSem resumo.")
    if plan is not None:
        path, progress = plan
        tasks = "\n".join(
            f"- [{'x' if t.done else ' '}] Tarefa {t.number}: {t.title}" for t in progress.tasks
        )
        parts.append(
            f"## Plano vinculado\nCaminho: {path}\n"
            f"Título: {progress.title} ({progress.done}/{progress.total})\n{tasks}"
        )
    else:
        parts.append("## Plano vinculado\nNenhum.")
    if specs:
        parts.append("## Specs citados\n" + "\n".join(f"- {p}: {t}" for p, t in specs))
    else:
        parts.append("## Specs citados\nNenhum.")
    header = "## Trecho novo da conversa"
    if restarted:
        header += (
            "\nO arquivo da conversa foi compactado ou reescrito: o trecho recomeça no resumo"
            " de compactação e pode repetir o que o resumo atual já cobre."
        )
    parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)
```

- [x] **Passo 4: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_prompt.py -q`
Expected: PASS

- [x] **Passo 5: Commit**

```bash
git add backend/vibing/digest/prompt.py backend/tests/test_digest_prompt.py
git commit -m "[Feat] Definir prompt e schema do agente de resumos"
```

---

### Tarefa 5: Mesclagem que congela fases concluídas

**Arquivos:**
- Criar: `backend/vibing/digest/merge.py`
- Testar: `backend/tests/test_digest_merge.py` (novo)

**Interfaces:**
- Consome: constantes de `vibing.digest.prompt`, `Digest`, `PlanProgress`.
- Produz, em `vibing.digest.merge`:
  - `class DigestFormatError(ValueError)` (mensagem: "Resposta do agente fora do formato.")
  - `clean_phase(raw: Any, roots: list[Path]) -> dict | None`
  - `merge_digest(old: Digest | None, result: Any, *, session_id: str, cursor: str | None, read_at: int, plan_path: str | None, plan: PlanProgress | None, roots: list[Path]) -> Digest`

Regras (seção 6 da spec, com um detalhe decidido aqui): as fases `done` gravadas são mantidas como estavam, na ordem. Da resposta, saem as fases cujo título (sem diferenciar maiúsculas nem espaços nas pontas) é igual ao de uma fase congelada; o resto entra depois delas. Isso cobre tanto a resposta que repete as fases congeladas quanto a que as omite.

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_merge.py
"""Merge of the agent's answer with the stored digest."""

from pathlib import Path

import pytest

from vibing.digest.merge import DigestFormatError, clean_phase, merge_digest
from vibing.digest.store import Digest
from vibing.plans import PlanProgress, PlanTask


def phase(title: str, status: str = "done", kind: str = "feature", **extra) -> dict:
    return {"title": title, "kind": kind, "status": status, "done": [], "pending": [],
            "ref": None, **extra}


def answer(*phases, short: str = "Faz Y", completed: bool = False, evidence=None) -> dict:
    return {"short": short, "phases": list(phases), "plan_completed": completed,
            "plan_evidence": evidence}


def merge(old, result, *, plan_path=None, plan=None, roots=None) -> Digest:
    return merge_digest(old, result, session_id="s1", cursor="u9", read_at=500,
                        plan_path=plan_path, plan=plan, roots=roots or [])


def test_first_reading() -> None:
    got = merge(None, answer(phase("Plano X", "open", "plan")))
    assert got.session_id == "s1" and got.cursor == "u9" and got.read_at == 500
    assert got.short == "Faz Y" and [p["title"] for p in got.phases] == ["Plano X"]
    assert got.error is None and got.plan_done is False


def test_done_phases_are_frozen() -> None:
    frozen = phase("Plano X", done=["Tarefa 1"])
    old = Digest("s1", phases=[frozen, phase("Ajustes", "open")])
    got = merge(old, answer(phase("Plano X", done=["reescrito"]), phase("Ajustes", "done"),
                            phase("Feature Y", "open")))
    assert got.phases[0] == frozen
    assert [p["title"] for p in got.phases] == ["Plano X", "Ajustes", "Feature Y"]
    assert [p["status"] for p in got.phases] == ["done", "done", "open"]


def test_omitted_frozen_phases_come_back() -> None:
    frozen = phase("Plano X")
    got = merge(Digest("s1", phases=[frozen]), answer(phase("Feature Y", "open")))
    assert [p["title"] for p in got.phases] == ["Plano X", "Feature Y"]


def test_only_the_last_phase_stays_open() -> None:
    got = merge(None, answer(phase("A", "open"), phase("B", "open")))
    assert [p["status"] for p in got.phases] == ["done", "open"]


def test_limits_are_applied_by_cutting() -> None:
    long = phase("T" * 300, "open", done=["d" * 300] * 20, pending=[" ", "p"])
    got = merge(None, answer(long, short="s" * 300))
    p = got.phases[0]
    assert len(p["title"]) == 121 and p["title"].endswith("…")
    assert len(p["done"]) == 12 and len(p["done"][0]) == 201
    assert p["pending"] == ["p"]
    assert len(got.short) == 141


def test_too_many_phases_fold_the_oldest() -> None:
    phases = [phase(f"F{i}") for i in range(25)] + [phase("Agora", "open")]
    got = merge(None, answer(*phases))
    assert len(got.phases) == 20
    assert got.phases[0]["title"] == "Fases anteriores" and got.phases[0]["kind"] == "other"
    assert got.phases[0]["done"][:2] == ["F0", "F1"]
    assert got.phases[-1]["title"] == "Agora"


def test_clean_phase_fixes_kind_status_and_drops_bad_items(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    inside = root / "plan.md"
    got = clean_phase({"title": " X ", "kind": "weird", "status": "maybe", "done": [1, "a"],
                       "pending": "no", "ref": str(inside)}, [root])
    assert got == {"title": "X", "kind": "other", "status": "open", "done": ["a"],
                   "pending": [], "ref": str(inside.resolve())}
    assert clean_phase({"title": "  "}, [root]) is None
    assert clean_phase("x", [root]) is None
    assert clean_phase({"title": "Y", "ref": "/etc/passwd"}, [root])["ref"] is None
    assert clean_phase({"title": "Y", "ref": "relativo.md"}, [root])["ref"] is None


def test_answer_without_phases_is_a_format_error() -> None:
    with pytest.raises(DigestFormatError):
        merge(None, {"short": "x"})
    with pytest.raises(DigestFormatError):
        merge(None, ["x"])


def test_empty_short_keeps_the_old_one() -> None:
    got = merge(Digest("s1", short="Antes"), answer(phase("A", "open"), short="  "))
    assert got.short == "Antes"


def test_plan_seal_from_the_file() -> None:
    done = PlanProgress("P", (PlanTask(1, "A", True),))
    got = merge(None, answer(phase("A", "open")), plan_path="/p.md", plan=done)
    assert got.plan_done is True and got.plan_ref == "/p.md"


def test_plan_seal_from_evidence_only_with_text() -> None:
    open_plan = PlanProgress("P", (PlanTask(1, "A", False),))
    assert merge(None, answer(completed=True, evidence="Revisão final aprovada."),
                 plan_path="/p.md", plan=open_plan).plan_done is True
    assert merge(None, answer(completed=True, evidence=" "), plan_path="/p.md",
                 plan=open_plan).plan_done is False


def test_plan_seal_stays_until_the_plan_changes() -> None:
    old = Digest("s1", plan_done=True, plan_ref="/p.md")
    assert merge(old, answer(), plan_path="/p.md").plan_done is True
    assert merge(old, answer(), plan_path="/outro.md").plan_done is False
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_merge.py -q`
Expected: FAIL com `ModuleNotFoundError`

- [x] **Passo 3: Escrever `merge.py`**

```python
# backend/vibing/digest/merge.py
"""Merge of the agent's answer with the stored digest. Pure.

Done phases already stored are frozen: the answer may only update the open phase,
close it and add new ones. The model alone never sets the plan seal.
"""

from pathlib import Path
from typing import Any

from vibing.digest.prompt import (
    ITEM_LIMIT,
    MAX_ITEMS,
    MAX_PHASES,
    PHASE_KINDS,
    PHASE_STATUSES,
    SHORT_LIMIT,
    TITLE_LIMIT,
)
from vibing.digest.store import Digest
from vibing.plans import PlanProgress

FOLDED_TITLE = "Fases anteriores"


class DigestFormatError(ValueError):
    def __init__(self) -> None:
        super().__init__("Resposta do agente fora do formato.")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _items(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    items = [_clip(i.strip(), ITEM_LIMIT) for i in raw if isinstance(i, str) and i.strip()]
    return items[:MAX_ITEMS]


def _ref(raw: Any, roots: list[Path]) -> str | None:
    if not isinstance(raw, str) or not raw.startswith("/"):
        return None
    try:
        resolved = Path(raw).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    for root in roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return str(resolved)
        except (OSError, RuntimeError):
            continue
    return None


def clean_phase(raw: Any, roots: list[Path]) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
        return None
    title = raw["title"].strip()
    if not title:
        return None
    return {
        "title": _clip(title, TITLE_LIMIT),
        "kind": raw.get("kind") if raw.get("kind") in PHASE_KINDS else "other",
        "status": raw.get("status") if raw.get("status") in PHASE_STATUSES else "open",
        "done": _items(raw.get("done")),
        "pending": _items(raw.get("pending")),
        "ref": _ref(raw.get("ref"), roots),
    }


def _key(title: str) -> str:
    return title.strip().casefold()


def _fold(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(phases) <= MAX_PHASES:
        return phases
    extra = len(phases) - MAX_PHASES + 1
    folded = phases[:extra]
    summary = {
        "title": FOLDED_TITLE, "kind": "other", "status": "done",
        "done": [_clip(p["title"], ITEM_LIMIT) for p in folded][:MAX_ITEMS],
        "pending": [], "ref": None,
    }
    return [summary, *phases[extra:]]


def merge_digest(
    old: Digest | None,
    result: Any,
    *,
    session_id: str,
    cursor: str | None,
    read_at: int,
    plan_path: str | None,
    plan: PlanProgress | None,
    roots: list[Path],
) -> Digest:
    if not isinstance(result, dict) or not isinstance(result.get("phases"), list):
        raise DigestFormatError()
    frozen = [p for p in (old.phases if old else []) if p.get("status") == "done"]
    frozen_keys = {_key(p["title"]) for p in frozen}
    tail = [
        p for p in (clean_phase(raw, roots) for raw in result["phases"])
        if p is not None and _key(p["title"]) not in frozen_keys
    ]
    for p in tail[:-1]:
        p["status"] = "done"
    phases = _fold([*frozen, *tail])

    short_raw = result.get("short")
    short = _clip(short_raw.strip(), SHORT_LIMIT) if isinstance(short_raw, str) else ""
    evidence = result.get("plan_evidence")
    by_evidence = result.get("plan_completed") is True and isinstance(evidence, str) \
        and bool(evidence.strip())
    by_file = plan is not None and plan.total > 0 and plan.done == plan.total
    kept = old is not None and old.plan_done and old.plan_ref == plan_path

    return Digest(
        session_id=session_id,
        cursor=cursor,
        read_at=read_at,
        short=short or (old.short if old else None),
        phases=phases,
        plan_done=kept or by_file or by_evidence,
        plan_ref=plan_path,
        error=None,
        error_at=None,
    )
```

- [x] **Passo 4: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_merge.py -q`
Expected: PASS

- [x] **Passo 5: Roadmap**

Marcar `[x] Mesclagem que congela fases concluídas e valida o selo "Plano concluído" (AAAA-MM-DD)` e atualizar a contagem.

- [x] **Passo 6: Commit**

```bash
git add backend/vibing/digest/merge.py backend/tests/test_digest_merge.py ROADMAP.md
git commit -m "[Feat] Mesclar resumo novo preservando fases concluídas"
```

---

### Tarefa 6: Interface do modelo, cliente real e cliente falso

**Arquivos:**
- Criar: `backend/vibing/digest/model.py`
- Modificar: `backend/tests/conftest.py` (fixture autouse que impede o cliente real)
- Testar: `backend/tests/test_digest_model.py` (novo)

**Interfaces:**
- Consome: `claude_agent_sdk` (`query`, `ClaudeAgentOptions`, `SystemMessage`, `ResultMessage`, `RateLimitEvent`, `CLINotFoundError`, `delete_session`), `vibing.agent.sdk_client` (`CLI_NOT_FOUND_MESSAGE`, `LOGIN_MESSAGE`, `LOGIN_MARKERS`, `to_agent_error`), `vibing.conversation.rate_limit_text`, `vibing.digest.prompt.DIGEST_SCHEMA`.
- Produz, em `vibing.digest.model`:
  - `@dataclass(frozen=True) class DigestRequest: system_prompt: str; prompt: str; model: str; effort: str`
  - `class DigestModelError(Exception)` com `message: str`, `stop_pass: bool`, `resets_at: int | None`
  - `class DigestModel(Protocol): async def summarize(self, request: DigestRequest) -> dict[str, Any]`
  - `class FakeDigestModel` com `responses: list[dict | Exception]`, `requests: list[DigestRequest]`, `gate: asyncio.Event | None`, `started: asyncio.Event`
  - `build_digest_options(request: DigestRequest, cwd: Path, stderr: Callable[[str], None] | None = None) -> ClaudeAgentOptions`
  - `class SdkDigestModel(cwd: Path, query_fn=None, delete_fn=None)`

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_model.py
"""Digest model: SDK options, real client over a stubbed query, fake client."""

from pathlib import Path

import pytest
from claude_agent_sdk import CLINotFoundError, ResultMessage, SystemMessage
from claude_agent_sdk.types import RateLimitEvent, RateLimitInfo

from vibing.digest.model import (
    DigestModelError,
    DigestRequest,
    FakeDigestModel,
    SdkDigestModel,
    build_digest_options,
)
from vibing.digest.prompt import DIGEST_SCHEMA

REQUEST = DigestRequest(system_prompt="regras", prompt="trecho", model="sonnet", effort="medium")
OUTPUT = {"short": "x", "phases": [], "plan_completed": False, "plan_evidence": None}


def result(**overrides) -> ResultMessage:
    fields = dict(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                  num_turns=1, session_id="sess-1", structured_output=OUTPUT)
    fields.update(overrides)
    return ResultMessage(**fields)


def stub_query(*messages, error: BaseException | None = None):
    calls = []

    async def query(*, prompt, options):
        calls.append((prompt, options))
        for message in messages:
            yield message
        if error is not None:
            raise error

    return query, calls


def test_options_have_no_tools_and_no_user_settings(tmp_path: Path) -> None:
    options = build_digest_options(REQUEST, tmp_path)
    assert options.tools == [] and options.setting_sources == []
    assert options.max_turns == 3 and options.model == "sonnet" and options.effort == "medium"
    assert options.system_prompt == "regras" and options.cwd == str(tmp_path)
    assert options.output_format == {"type": "json_schema", "schema": DIGEST_SCHEMA}


@pytest.mark.anyio
async def test_returns_the_structured_output_and_deletes_the_session(tmp_path: Path) -> None:
    query, calls = stub_query(SystemMessage("init", {"session_id": "sess-1"}), result())
    deleted = []
    model = SdkDigestModel(tmp_path / "agent", query_fn=query,
                           delete_fn=lambda sid, directory: deleted.append((sid, directory)))
    assert await model.summarize(REQUEST) == OUTPUT
    assert calls[0][0] == "trecho"
    assert deleted == [("sess-1", str(tmp_path / "agent"))]
    assert (tmp_path / "agent").is_dir()


@pytest.mark.anyio
async def test_error_result_raises_and_still_deletes(tmp_path: Path) -> None:
    query, _ = stub_query(SystemMessage("init", {"session_id": "sess-1"}),
                          result(is_error=True, structured_output=None, result="boom"))
    deleted = []
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: deleted.append(s))
    with pytest.raises(DigestModelError) as info:
        await model.summarize(REQUEST)
    assert info.value.stop_pass is False
    assert deleted == ["sess-1"]


@pytest.mark.anyio
async def test_missing_output_raises(tmp_path: Path) -> None:
    query, _ = stub_query(result(structured_output=None))
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError, match="não devolveu o resumo"):
        await model.summarize(REQUEST)


@pytest.mark.anyio
async def test_rate_limit_stops_the_pass(tmp_path: Path) -> None:
    info = RateLimitInfo(status="rejected", resets_at=1_900_000_000)
    event = RateLimitEvent(rate_limit_info=info, uuid="r", session_id="sess-1")
    query, _ = stub_query(SystemMessage("init", {"session_id": "sess-1"}), event)
    deleted = []
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: deleted.append(s))
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True and err.value.resets_at == 1_900_000_000
    assert err.value.message.startswith("Limite da assinatura atingido.")
    assert deleted == ["sess-1"]


@pytest.mark.anyio
async def test_missing_cli_stops_the_pass(tmp_path: Path) -> None:
    query, _ = stub_query(error=CLINotFoundError("no claude"))
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True and "claude" in err.value.message


@pytest.mark.anyio
async def test_login_failure_stops_the_pass(tmp_path: Path) -> None:
    error = RuntimeError("Not logged in · Please run /login")
    query, _ = stub_query(error=error)
    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=lambda s, d: None)
    with pytest.raises(DigestModelError) as err:
        await model.summarize(REQUEST)
    assert err.value.stop_pass is True and "login" in err.value.message


@pytest.mark.anyio
async def test_delete_failure_is_ignored(tmp_path: Path) -> None:
    query, _ = stub_query(SystemMessage("init", {"session_id": "sess-1"}), result())

    def fail(sid, directory):
        raise OSError("nope")

    model = SdkDigestModel(tmp_path, query_fn=query, delete_fn=fail)
    assert await model.summarize(REQUEST) == OUTPUT


@pytest.mark.anyio
async def test_fake_model_returns_scripted_answers_and_errors() -> None:
    fake = FakeDigestModel([OUTPUT, DigestModelError("falhou")])
    assert await fake.summarize(REQUEST) == OUTPUT
    with pytest.raises(DigestModelError):
        await fake.summarize(REQUEST)
    assert fake.requests == [REQUEST, REQUEST]
```

Confira no SDK instalado os nomes dos campos obrigatórios de `RateLimitEvent` (`grep -n "class RateLimitEvent" -A12 .venv/lib/python3.13/site-packages/claude_agent_sdk/types.py`) e ajuste a construção no teste se forem outros.

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_model.py -q`
Expected: FAIL com `ModuleNotFoundError`

- [x] **Passo 3: Escrever `model.py`**

```python
# backend/vibing/digest/model.py
"""The model behind the digest agent: one short `query()` per session, no tools.

`SdkDigestModel` is the real one; tests use `FakeDigestModel`.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vibing.agent.sdk_client import (
    CLI_NOT_FOUND_MESSAGE,
    LOGIN_MARKERS,
    LOGIN_MESSAGE,
    to_agent_error,
)
from vibing.conversation import rate_limit_text
from vibing.digest.prompt import DIGEST_SCHEMA

logger = logging.getLogger(__name__)

MAX_TURNS = 3
NO_OUTPUT = "O agente não devolveu o resumo."
BAD_OUTPUT = "Resposta do agente fora do formato."


@dataclass(frozen=True)
class DigestRequest:
    system_prompt: str
    prompt: str
    model: str
    effort: str


class DigestModelError(Exception):
    """A failed reading. `stop_pass` ends the whole pass (login, CLI missing, limit)."""

    def __init__(self, message: str, *, stop_pass: bool = False, resets_at: int | None = None):
        super().__init__(message)
        self.message = message
        self.stop_pass = stop_pass
        self.resets_at = resets_at


class DigestModel(Protocol):
    async def summarize(self, request: DigestRequest) -> dict[str, Any]: ...


class FakeDigestModel:
    """Scripted answers for tests. With `gate`, each call waits for it to be set."""

    DEFAULT = {"short": "Resumo", "phases": [], "plan_completed": False, "plan_evidence": None}

    def __init__(self, responses: list[dict[str, Any] | Exception] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[DigestRequest] = []
        self.gate: asyncio.Event | None = None
        self.started = asyncio.Event()

    async def summarize(self, request: DigestRequest) -> dict[str, Any]:
        self.requests.append(request)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        item = self.responses.pop(0) if self.responses else dict(self.DEFAULT)
        if isinstance(item, Exception):
            raise item
        return item


def build_digest_options(
    request: DigestRequest, cwd: Path, stderr: Callable[[str], None] | None = None
) -> Any:
    from claude_agent_sdk import ClaudeAgentOptions

    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "model": request.model,
        "effort": request.effort,
        "tools": [],
        "max_turns": MAX_TURNS,
        "setting_sources": [],
        "system_prompt": request.system_prompt,
        "output_format": {"type": "json_schema", "schema": DIGEST_SCHEMA},
    }
    if stderr is not None:
        kwargs["stderr"] = stderr
    return ClaudeAgentOptions(**kwargs)


def _sdk_query(*, prompt: str, options: Any):
    from claude_agent_sdk import query

    return query(prompt=prompt, options=options)


def _sdk_delete(session_id: str, directory: str) -> None:
    from claude_agent_sdk import delete_session

    delete_session(session_id, directory=directory)


class SdkDigestModel:
    def __init__(
        self,
        cwd: Path,
        query_fn: Callable[..., Any] | None = None,
        delete_fn: Callable[[str, str], None] | None = None,
    ) -> None:
        self._cwd = cwd
        self._query = query_fn or _sdk_query
        self._delete = delete_fn or _sdk_delete

    def _delete_quietly(self, session_id: str) -> None:
        try:
            self._delete(session_id, str(self._cwd))
        except Exception:
            logger.warning("Não foi possível apagar a sessão %s do agente de resumos", session_id)

    async def summarize(self, request: DigestRequest) -> dict[str, Any]:
        from claude_agent_sdk import CLINotFoundError, ResultMessage, SystemMessage
        from claude_agent_sdk.types import RateLimitEvent

        self._cwd.mkdir(parents=True, exist_ok=True)
        stderr_lines: deque[str] = deque(maxlen=50)
        options = build_digest_options(request, self._cwd, stderr_lines.append)
        session_id: str | None = None
        output: Any = None
        failure: str | None = None
        try:
            async with aclosing(self._query(prompt=request.prompt, options=options)) as stream:
                async for message in stream:
                    if isinstance(message, SystemMessage) and message.subtype == "init":
                        session_id = message.data.get("session_id") or session_id
                    elif isinstance(message, RateLimitEvent):
                        info = message.rate_limit_info
                        if info.status == "rejected":
                            raise DigestModelError(
                                rate_limit_text(info.resets_at), stop_pass=True,
                                resets_at=info.resets_at,
                            )
                    elif isinstance(message, ResultMessage):
                        session_id = session_id or message.session_id
                        if message.is_error or message.structured_output is None:
                            failure = NO_OUTPUT
                        else:
                            output = message.structured_output
        except DigestModelError:
            raise
        except CLINotFoundError as error:
            raise DigestModelError(CLI_NOT_FOUND_MESSAGE, stop_pass=True) from error
        except Exception as error:
            texts = [*stderr_lines, str(error), getattr(error, "stderr", None) or ""]
            if any(marker in text for text in texts for marker in LOGIN_MARKERS):
                raise DigestModelError(LOGIN_MESSAGE, stop_pass=True) from error
            raise DigestModelError(to_agent_error(error).message_pt) from error
        finally:
            if session_id:
                await asyncio.to_thread(self._delete_quietly, session_id)
        if output is None:
            raise DigestModelError(failure or NO_OUTPUT)
        if not isinstance(output, dict):
            raise DigestModelError(BAD_OUTPUT)
        return output
```

- [x] **Passo 4: Proteger os testes do cliente real**

Em `backend/tests/conftest.py`, acrescentar:

```python
@pytest.fixture(autouse=True)
def no_real_digest_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The digest agent never reaches the real SDK in tests."""

    def no_real_query(*, prompt, options):
        raise RuntimeError("Os testes não podem chamar o SDK real no agente de resumos.")

    monkeypatch.setattr("vibing.digest.model._sdk_query", no_real_query)
    monkeypatch.setattr(
        "vibing.digest.model._sdk_delete", lambda session_id, directory: None
    )
```

- [x] **Passo 5: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_model.py -q`
Expected: PASS

- [x] **Passo 6: Roadmap**

Marcar `[x] Interface DigestModel, cliente real sobre o SDK e cliente falso (AAAA-MM-DD)` e atualizar a contagem.

- [x] **Passo 7: Commit**

```bash
git add backend/vibing/digest/model.py backend/tests/test_digest_model.py backend/tests/conftest.py ROADMAP.md
git commit -m "[Feat] Adicionar cliente do SDK para o agente de resumos"
```

---

### Tarefa 7: Frase curta e selo no resumo da sessão

**Arquivos:**
- Modificar: `backend/vibing/sessions.py` (`describe`, `SessionManager.__init__`, `_extras`, método novo)
- Modificar: `backend/vibing/api/sessions.py` (`SessionOut`)
- Testar: `backend/tests/test_digest_brief.py` (novo)

**Interfaces:**
- Consome: `vibing.digest.store.briefs`.
- Produz:
  - `describe(..., digest_short: str | None = None, plan_done: bool = False)` devolve `"digest_short"` e `"plan_done"`.
  - `SessionManager.set_digest_brief(session_id: str, short: str | None, plan_done: bool) -> Awaitable[None]` (async): guarda na memória e, se mudou, publica `session.updated` pela via de `_announce_session`.
  - `SessionOut.digest_short: str | None = None`, `SessionOut.plan_done: bool = False`.

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_brief.py
"""Short sentence and plan seal of the digest in the session summary."""

from contextlib import closing
from pathlib import Path

import pytest
from test_sessions import Env

from vibing import db
from vibing.agent.fake import FakeAgentFactory
from vibing.digest import store
from vibing.digest.store import Digest
from vibing.sessions import SessionManager


@pytest.mark.anyio
async def test_summary_carries_the_brief_and_announces_changes(tmp_path: Path) -> None:
    env = Env(tmp_path, FakeAgentFactory())
    record = env.manager.create_session(env.project)
    sid = record.session_id
    item = next(s for s in env.manager.list_sessions() if s["session_id"] == sid)
    assert item["digest_short"] is None and item["plan_done"] is False

    await env.manager.set_digest_brief(sid, "Executa o plano X", True)
    item = next(s for s in env.manager.list_sessions() if s["session_id"] == sid)
    assert item["digest_short"] == "Executa o plano X" and item["plan_done"] is True
    updates = [e for e in env.recorder.envelopes
               if e["type"] == "session.updated" and e["data"]["session_id"] == sid]
    assert updates and updates[-1]["data"]["digest_short"] == "Executa o plano X"

    count = len(env.recorder.envelopes)
    await env.manager.set_digest_brief(sid, "Executa o plano X", True)
    assert len(env.recorder.envelopes) == count  # unchanged: nothing published
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_briefs_are_loaded_at_startup(tmp_path: Path) -> None:
    env = Env(tmp_path, FakeAgentFactory())
    record = env.manager.create_session(env.project)
    with closing(db.connect(env.db_path)) as conn:
        store.save_digest(conn, Digest(record.session_id, short="Salvo", plan_done=True))
    await env.manager.shutdown()
    restarted = SessionManager(env.db_path, env.recorder, agent_factory=FakeAgentFactory())
    item = next(s for s in restarted.list_sessions() if s["session_id"] == record.session_id)
    assert item["digest_short"] == "Salvo" and item["plan_done"] is True
    await restarted.shutdown()


def test_session_out_accepts_the_fields() -> None:
    from vibing.api.sessions import SessionOut

    assert "digest_short" in SessionOut.model_fields and "plan_done" in SessionOut.model_fields
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_brief.py -q`
Expected: FAIL (`KeyError: 'digest_short'` ou `AttributeError: set_digest_brief`)

- [x] **Passo 3: Implementar em `sessions.py`**

1. Import no topo: `from vibing.digest import store as digest_store`.
2. Em `describe`, acrescentar os parâmetros `digest_short: str | None = None, plan_done: bool = False` depois de `cli_running`, e no dicionário devolvido, depois de `"cli_running"`:

```python
        "digest_short": digest_short,
        "plan_done": plan_done,
```

3. Em `SessionManager.__init__`, logo depois da chamada `self._load_models()`:

```python
        # Short sentence and plan seal of the digest agent, by session (memory copy).
        self._digest_briefs: dict[str, tuple[str | None, bool]] = {}
        self._load_digest_briefs()
```

4. Métodos novos, junto de `_extras`:

```python
    def _load_digest_briefs(self) -> None:
        try:
            with closing(db.connect(self._db_path)) as conn:
                self._digest_briefs = digest_store.briefs(conn)
        except sqlite3.Error:
            logger.exception("Falha ao ler os resumos do agente")

    async def set_digest_brief(self, session_id: str, short: str | None, plan_done: bool) -> None:
        """The digest agent wrote a new summary: show its sentence and seal in the lists."""
        brief = (short, plan_done)
        if self._digest_briefs.get(session_id) == brief:
            return
        self._digest_briefs[session_id] = brief
        await self._announce_session(session_id)
```

5. Em `_extras`, ler o resumo e acrescentar os dois campos nos dois dicionários devolvidos:

```python
        short, plan_done = self._digest_briefs.get(record.session_id, (None, False))
```

e `"digest_short": short, "plan_done": plan_done` em cada `return`.

- [x] **Passo 4: Implementar em `api/sessions.py`**

Em `SessionOut`, depois de `group_id`:

```python
    # Short sentence of the digest agent's summary; None before the first reading.
    digest_short: str | None = None
    # The digest agent marked the linked plan as completed.
    plan_done: bool = False
```

- [x] **Passo 5: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_brief.py backend/tests/test_navigation_summary.py backend/tests/test_sessions_api.py -q`
Expected: PASS. Se algum teste compara o dicionário inteiro de `describe`, acrescente os dois campos nele.

- [x] **Passo 6: Rodar a suíte do backend**

Run: `uv run pytest -q`
Expected: PASS

- [x] **Passo 7: Commit**

```bash
git add backend/vibing/sessions.py backend/vibing/api/sessions.py backend/tests/test_digest_brief.py
git commit -m "[Feat] Incluir frase do resumo e selo do plano na sessão"
```

---

### Tarefa 8: Passada do agente

**Arquivos:**
- Criar: `backend/vibing/digest/service.py` (parte 1: elegibilidade, leitura de uma sessão, passada)
- Testar: `backend/tests/test_digest_pass.py` (novo), `backend/tests/digest_fakes.py` (novo, ajudantes)

**Interfaces:**
- Consome: tudo das Tarefas 1 a 7; `history.sdk_session_file`, `history.read_transcript_at`; `PlanCache`; do `SessionManager`: `list_sessions() -> list[dict]` (campos `session_id`, `project_id`, `cwd`, `title`, `created_at`, `last_activity_at`, `state`, `display_state`, `cli_running`, `plan`), `project_roots() -> list[Path]`, `list_models() -> list[dict]` (campo `value`), `set_digest_brief(...)`.
- Produz, em `vibing.digest.service`:
  - `SESSION_TIMEOUT = 120.0`, `AGENT_DIR_NAME = "digest-agent"`, `STOPPED_DISABLED = "Desligado."`
  - `pre_eligible(session: dict, digest: Digest | None, file_mtime: float | None, config: DigestConfig, now: float) -> bool`
  - `class DigestService(db_path: Path, manager, publish: Callable[[dict], None], model: DigestModel, *, clock: Callable[[], float] = time.time, session_file=None, read_transcript=None, session_timeout: float = SESSION_TIMEOUT)`
    - `config: DigestConfig` (propriedade), `load() -> None` (bloqueante; lê a configuração)
    - `async run_pass(trigger: str, session_ids: list[str] | None = None) -> dict` (devolve a passada registrada)
    - `status() -> dict` (`enabled`, `running`, `next_run_at`, `paused_until`)

Envelope publicado por leitura: `{"session_id": None, "seq": 0, "type": "session.digest", "data": {"session_id": sid, "digest": digest.to_dict()}}`.

- [x] **Passo 1: Escrever os ajudantes de teste**

```python
# backend/tests/digest_fakes.py
"""Helpers for the digest agent tests: a fake session manager and transcripts."""

import os
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from vibing import db
from vibing.history import Transcript

NOW = 1_000_000.0


def user(uuid: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(type="user", uuid=uuid, message={"role": "user", "content": text})


def claude(uuid: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(type="assistant", uuid=uuid,
                           message={"role": "assistant", "content": [{"type": "text", "text": text}]})


def exchange(start: int, count: int) -> list[SimpleNamespace]:
    """`count` condensable entries: alternating prompts and answers."""
    return [
        user(f"u{i}", f"pedido {i}") if i % 2 == 0 else claude(f"a{i}", f"resposta {i}")
        for i in range(start, start + count)
    ]


class FakeManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sessions: list[dict[str, Any]] = []
        self.briefs: dict[str, tuple[str | None, bool]] = {}
        self.models = [{"value": "default"}, {"value": "sonnet"}, {"value": "haiku"}]

    def list_sessions(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self.sessions]

    def project_roots(self) -> list[Path]:
        return [self.root]

    def list_models(self) -> list[dict[str, Any]]:
        return self.models

    async def set_digest_brief(self, session_id: str, short: str | None, plan_done: bool) -> None:
        self.briefs[session_id] = (short, plan_done)


class World:
    """Database with one project, sessions with files and transcripts."""

    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "data" / "vibing.db"
        db.init_db(self.db_path)
        self.root = tmp_path / "app"
        self.root.mkdir()
        self.files_dir = tmp_path / "files"
        self.files_dir.mkdir()
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (1, 'app', ?, '#fff', 0, 0)", (str(self.root),)
            )
        self.manager = FakeManager(self.root)
        self.transcripts: dict[str, Transcript] = {}
        self.envelopes: list[dict[str, Any]] = []
        self.clock = [NOW]

    def add(self, sid: str, messages: list[Any], *, mtime: float = NOW - 10, **fields) -> None:
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at) VALUES (?, 1, ?, ?, ?, ?)",
                (sid, str(self.root), f"Sessão {sid}", NOW - 3600, NOW - 60),
            )
        session = {
            "session_id": sid, "project_id": 1, "cwd": str(self.root), "title": f"Sessão {sid}",
            "created_at": int(NOW - 3600), "last_activity_at": int(NOW - 60), "state": "closed",
            "display_state": "waiting", "cli_running": False, "plan": None,
        }
        session.update(fields)
        self.manager.sessions.append(session)
        self.transcripts[sid] = Transcript(messages=messages, tool_results={})
        path = self.files_dir / f"{sid}.jsonl"
        path.write_text("{}\n")
        os.utime(path, (mtime, mtime))

    def touch(self, sid: str, messages: list[Any], mtime: float) -> None:
        self.transcripts[sid].messages.extend(messages)
        os.utime(self.files_dir / f"{sid}.jsonl", (mtime, mtime))

    def session_file(self, sid: str, cwd: str) -> Path | None:
        path = self.files_dir / f"{sid}.jsonl"
        return path if path.exists() else None

    def read_transcript(self, path: Path | None):
        return None if path is None else self.transcripts.get(path.stem)

    def service(self, model, **kwargs):
        from vibing.digest.service import DigestService

        service = DigestService(
            self.db_path, self.manager, self.envelopes.append, model,
            clock=lambda: self.clock[0], session_file=self.session_file,
            read_transcript=self.read_transcript, **kwargs,
        )
        service.load()
        return service

    def digest(self, sid: str):
        from vibing.digest import store

        with closing(db.connect(self.db_path)) as conn:
            return store.get_digest(conn, sid)

    def published(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.envelopes if e["type"] == type_]
```

- [x] **Passo 2: Escrever os testes que falham**

```python
# backend/tests/test_digest_pass.py
"""One pass of the digest agent over the eligible sessions."""

import asyncio
from contextlib import closing
from pathlib import Path

import pytest
from digest_fakes import NOW, World, claude, exchange, user

from vibing import db
from vibing.digest.config import DigestConfig, save_config
from vibing.digest.model import DigestModelError, FakeDigestModel
from vibing.digest.service import pre_eligible
from vibing.digest.store import Digest

CFG = DigestConfig(enabled=True)


def answer(short: str = "Faz X", *phases) -> dict:
    return {"short": short, "phases": list(phases) or [
        {"title": "Fase", "kind": "feature", "status": "open", "done": [], "pending": [], "ref": None}
    ], "plan_completed": False, "plan_evidence": None}


def session(**fields) -> dict:
    base = {"display_state": "waiting", "last_activity_at": int(NOW - 60), "state": "closed",
            "cli_running": False, "created_at": int(NOW - 3600)}
    base.update(fields)
    return base


# pre_eligible ------------------------------------------------------------------

def test_pre_eligible_rules() -> None:
    assert pre_eligible(session(), None, NOW - 5, CFG, NOW)
    assert not pre_eligible(session(display_state="finished"), None, NOW - 5, CFG, NOW)
    assert not pre_eligible(session(last_activity_at=int(NOW - 4 * 86400)), None, NOW, CFG, NOW)
    assert not pre_eligible(session(), None, None, CFG, NOW)
    read = Digest("s", read_at=int(NOW - 5))
    assert not pre_eligible(session(), read, NOW - 5, CFG, NOW)  # file unchanged
    assert pre_eligible(session(), read, NOW - 1, CFG, NOW)


def test_open_turn_waits_for_the_ceiling() -> None:
    running = session(state="running")
    cli = session(cli_running=True)
    recent = Digest("s", read_at=int(NOW - 10 * 60))
    old = Digest("s", read_at=int(NOW - 31 * 60))
    assert not pre_eligible(running, recent, NOW, CFG, NOW)
    assert not pre_eligible(cli, recent, NOW, CFG, NOW)
    assert pre_eligible(running, old, NOW, CFG, NOW)
    # First reading: counted from the session's creation (an hour ago here).
    assert pre_eligible(running, None, NOW, CFG, NOW)


# pass ----------------------------------------------------------------------------

def enable(world: World, **changes) -> None:
    with closing(db.connect(world.db_path)) as conn:
        save_config(conn, DigestConfig(enabled=True, **changes))


@pytest.mark.anyio
async def test_pass_reads_eligible_sessions(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world)
    world.add("s1", exchange(0, 12))
    world.add("s2", exchange(0, 3))  # below the minimum of 10
    world.add("s3", exchange(0, 12), display_state="finished")
    model = FakeDigestModel([answer("Faz X")])
    service = world.service(model)

    run = await service.run_pass("auto")

    assert run["read_count"] == 1 and run["skipped_count"] == 1 and run["errors"] == []
    assert run["trigger"] == "auto" and run["stopped"] is None
    digest = world.digest("s1")
    assert digest.short == "Faz X" and digest.cursor == "a11" and digest.read_at == int(NOW)
    assert world.manager.briefs["s1"] == ("Faz X", False)
    events = world.published("session.digest")
    assert events == [{"session_id": None, "seq": 0, "type": "session.digest",
                       "data": {"session_id": "s1", "digest": digest.to_dict()}}]
    request = model.requests[0]
    assert request.model == "sonnet" and request.effort == "medium"
    assert "[Você] pedido 0" in request.prompt and "Projeto: app" in request.prompt


@pytest.mark.anyio
async def test_second_reading_sends_only_what_is_new(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=2)
    world.add("s1", exchange(0, 4))
    model = FakeDigestModel([answer("Primeira"), answer("Segunda")])
    service = world.service(model)
    await service.run_pass("auto")

    world.clock[0] = NOW + 600
    world.touch("s1", [user("u9", "pedido novo"), claude("a9", "feito")], NOW + 500)
    await service.run_pass("auto")

    second = model.requests[1].prompt
    assert "pedido novo" in second and "pedido 0" not in second
    assert '"short": "Primeira"' in second
    assert world.digest("s1").cursor == "a9"


@pytest.mark.anyio
async def test_unchanged_file_is_not_read_again(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    await service.run_pass("auto")
    world.clock[0] = NOW + 600
    run = await service.run_pass("auto")
    assert len(model.requests) == 1 and run["read_count"] == 0


@pytest.mark.anyio
async def test_frozen_phases_survive_the_answer(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    done = {"title": "Plano X", "kind": "plan", "status": "done", "done": ["T1"], "pending": [],
            "ref": None}
    model = FakeDigestModel([
        answer("A", done),
        answer("B", {**done, "done": ["mudou"]},
               {"title": "Ajustes", "kind": "adjustments", "status": "open", "done": [],
                "pending": [], "ref": None}),
    ])
    service = world.service(model)
    await service.run_pass("auto")
    world.clock[0] = NOW + 600
    world.touch("s1", [user("u9", "ajuste")], NOW + 500)
    await service.run_pass("auto")
    phases = world.digest("s1").phases
    assert phases[0] == done and phases[1]["title"] == "Ajustes"


@pytest.mark.anyio
async def test_one_failure_does_not_stop_the_others(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel([DigestModelError("Resposta ruim."), answer("OK")])
    service = world.service(model)
    run = await service.run_pass("auto")
    assert run["read_count"] == 1
    assert run["errors"] == [{"session_id": "s1", "title": "Sessão s1", "message": "Resposta ruim."}]
    assert world.digest("s1").error == "Resposta ruim."
    assert world.digest("s2").short == "OK"


@pytest.mark.anyio
async def test_stop_error_ends_the_pass(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel([DigestModelError("Login expirou.", stop_pass=True)])
    service = world.service(model)
    run = await service.run_pass("auto")
    assert run["stopped"] == "Login expirou." and len(model.requests) == 1
    assert world.digest("s2") is None


@pytest.mark.anyio
async def test_rate_limit_pauses_until_release(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel([DigestModelError("Limite.", stop_pass=True, resets_at=int(NOW + 3600))])
    service = world.service(model)
    await service.run_pass("auto")
    assert service.status()["paused_until"] == int(NOW + 3600)


@pytest.mark.anyio
async def test_timeout_is_a_session_error(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    model.gate = asyncio.Event()  # never set
    service = world.service(model, session_timeout=0.05)
    run = await service.run_pass("auto")
    assert run["errors"][0]["message"] == "O agente demorou demais para responder."


@pytest.mark.anyio
async def test_unknown_model_stops_before_reading(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, model="claude-sumiu", min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    run = await service.run_pass("auto")
    assert run["stopped"] == "O modelo claude-sumiu não está mais disponível."
    assert model.requests == []


@pytest.mark.anyio
async def test_session_gone_before_saving_is_skipped(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    model.gate = asyncio.Event()
    service = world.service(model)
    task = asyncio.create_task(service.run_pass("auto"))
    await model.started.wait()
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    model.gate.set()
    run = await task
    assert run["read_count"] == 0 and run["skipped_count"] == 1 and run["errors"] == []


@pytest.mark.anyio
async def test_manual_session_ignores_the_filters(tmp_path: Path) -> None:
    world = World(tmp_path)  # agent disabled
    world.add("s1", exchange(0, 2), display_state="finished")
    model = FakeDigestModel([answer("Manual")])
    service = world.service(model)
    run = await service.run_pass("manual_session", ["s1", "nope"])
    assert world.digest("s1").short == "Manual" and run["read_count"] == 1
    assert run["errors"] == [{"session_id": "nope", "title": "nope",
                              "message": "Conversa não encontrada."}]


@pytest.mark.anyio
async def test_manual_session_without_news_republishes(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel([answer("Uma vez")])
    service = world.service(model)
    await service.run_pass("manual_session", ["s1"])
    await service.run_pass("manual_session", ["s1"])
    assert len(model.requests) == 1
    assert len(world.published("session.digest")) == 2


@pytest.mark.anyio
async def test_manual_all_ignores_only_the_minimum(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world)  # minimum 10
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2), display_state="finished")
    model = FakeDigestModel()
    service = world.service(model)
    run = await service.run_pass("manual_all")
    assert run["read_count"] == 1 and world.digest("s2") is None


@pytest.mark.anyio
async def test_plan_file_complete_sets_the_seal(tmp_path: Path) -> None:
    world = World(tmp_path)
    enable(world, min_new_messages=1)
    plans = world.root / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    plan = plans / "p.md"
    plan.write_text("# P\n\n### Tarefa 1: A\n- [x] a\n")
    world.add("s1", exchange(0, 2),
              plan={"path": str(plan), "title": "P", "total": 1, "done": 1, "current": None})
    model = FakeDigestModel()
    service = world.service(model)
    await service.run_pass("auto")
    assert world.digest("s1").plan_done is True
    assert "- [x] Tarefa 1: A" in model.requests[0].prompt
```

- [x] **Passo 3: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_pass.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'vibing.digest.service'`

- [x] **Passo 4: Escrever a parte 1 de `service.py`**

```python
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
        self._running = True
        self._publish_status()
        read = skipped = 0
        errors: list[dict[str, Any]] = []
        stopped: str | None = None
        handled: set[str] = set()  # sessions that already got a result or an error
        try:
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

    def _file_mtime(self, session: dict[str, Any]) -> float | None:
        path = self._session_file(session["session_id"], session["cwd"])
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
                                self._file_mtime(s), config, now)
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
        transcript = self._read_transcript(self._session_file(sid, session["cwd"]))
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
        """"read", "skipped" or the error message of this session."""
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
        await self._manager.set_digest_brief(sid, digest.short, digest.plan_done)
        return "read"
```

- [x] **Passo 5: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_pass.py -q`
Expected: PASS

- [x] **Passo 6: Commit**

```bash
git add backend/vibing/digest/service.py backend/tests/digest_fakes.py backend/tests/test_digest_pass.py
git commit -m "[Feat] Implementar passada do agente de resumos"
```

---

### Tarefa 9: Agendador, fila e pausa

**Arquivos:**
- Modificar: `backend/vibing/digest/service.py` (parte 2: fila, laço, configuração)
- Testar: `backend/tests/test_digest_scheduler.py` (novo)

**Interfaces:**
- Consome: `DigestService.run_pass`, `save_config`.
- Produz, em `DigestService`:
  - `request_all() -> None`, `request_session(session_id: str) -> None`
  - `async update_config(config: DigestConfig) -> None` (grava, reprograma, cancela a passada ao desligar)
  - `async tick() -> None` (faz o que estiver pendente ou vencido, uma passada por vez)
  - `async run() -> None` (laço: carrega, espera, `tick`)
  - `start_schedule() -> None` (primeira passada automática um intervalo depois de agora)

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_scheduler.py
"""Scheduler of the digest agent: queue, pause, config changes, cancellation."""

import asyncio
from contextlib import closing
from pathlib import Path

import pytest
from digest_fakes import NOW, World, exchange

from vibing import db
from vibing.digest import store
from vibing.digest.config import DigestConfig, load_config
from vibing.digest.model import FakeDigestModel


def runs(world: World) -> list[dict]:
    with closing(db.connect(world.db_path)) as conn:
        return store.list_runs(conn)


@pytest.mark.anyio
async def test_first_automatic_pass_waits_an_interval(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 12))
    model = FakeDigestModel()
    service = world.service(model)
    await service.update_config(DigestConfig(enabled=True))
    assert service.status()["next_run_at"] == int(NOW + 600)
    await service.tick()
    assert model.requests == []
    world.clock[0] = NOW + 600
    await service.tick()
    assert len(model.requests) == 1
    assert service.status()["next_run_at"] == int(NOW + 1200)


@pytest.mark.anyio
async def test_disabled_agent_runs_only_manual_requests(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 12))
    model = FakeDigestModel()
    service = world.service(model)
    world.clock[0] = NOW + 10_000
    await service.tick()
    assert model.requests == [] and service.status()["next_run_at"] is None
    service.request_session("s1")
    await service.tick()
    assert len(model.requests) == 1
    assert [r["trigger"] for r in runs(world)] == ["manual_session"]


@pytest.mark.anyio
async def test_requests_are_queued_without_repeats(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    service.request_session("s1")
    service.request_session("s1")
    service.request_session("s2")
    service.request_all()
    service.request_all()
    await service.tick()
    # Newest first: the general request runs before the session requests.
    assert [r["trigger"] for r in runs(world)] == ["manual_session", "manual_all"]


@pytest.mark.anyio
async def test_disabling_cancels_the_running_pass(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel([FakeDigestModel.DEFAULT])
    service = world.service(model)
    await service.update_config(DigestConfig(enabled=True, min_new_messages=1))
    world.clock[0] = NOW + 600
    model.gate = asyncio.Event()  # never set: the first reading hangs
    tick = asyncio.create_task(service.tick())
    await model.started.wait()
    await service.update_config(DigestConfig(enabled=False))
    await asyncio.wait_for(tick, 1)  # the pass is cancelled, the tick itself ends normally
    assert runs(world)[0]["stopped"] == "Desligado."
    assert service.status() == {"enabled": False, "running": False, "next_run_at": None,
                                "paused_until": None}


@pytest.mark.anyio
async def test_pause_holds_automatic_passes(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 12))
    model = FakeDigestModel()
    service = world.service(model)
    await service.update_config(DigestConfig(enabled=True))
    service._paused_until = NOW + 3600
    world.clock[0] = NOW + 600
    await service.tick()
    assert model.requests == []
    world.clock[0] = NOW + 3600
    await service.tick()
    assert len(model.requests) == 1 and service.status()["paused_until"] is None


@pytest.mark.anyio
async def test_update_config_is_saved_and_published(tmp_path: Path) -> None:
    world = World(tmp_path)
    service = world.service(FakeDigestModel())
    await service.update_config(DigestConfig(enabled=True, window_days=5))
    with closing(db.connect(world.db_path)) as conn:
        assert load_config(conn).window_days == 5
    assert world.published("digest.status")[-1]["data"]["enabled"] is True


@pytest.mark.anyio
async def test_run_wakes_up_for_a_request(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    loop = asyncio.create_task(service.run())
    await asyncio.sleep(0)
    service.request_session("s1")
    await asyncio.wait_for(model.started.wait(), 1)
    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_scheduler.py -q`
Expected: FAIL com `AttributeError: 'DigestService' object has no attribute 'update_config'`

- [x] **Passo 3: Implementar a parte 2**

Em `DigestService.__init__`, acrescentar:

```python
        self._pending_all = False
        self._pending_sessions: dict[str, None] = {}
        self._wake = asyncio.Event()
        self._current: asyncio.Task[dict[str, Any]] | None = None
```

No fim da classe:

```python
    # Scheduler -----------------------------------------------------------------

    def start_schedule(self) -> None:
        """The first automatic pass waits a whole interval."""
        self._next_run_at = (
            self._clock() + self._config.interval_minutes * 60 if self._config.enabled else None
        )

    def request_all(self) -> None:
        self._pending_all = True
        self._wake.set()

    def request_session(self, session_id: str) -> None:
        self._pending_sessions[session_id] = None
        self._wake.set()

    async def update_config(self, config: DigestConfig) -> None:
        from vibing.digest.config import save_config

        def save() -> None:
            with closing(db.connect(self._db_path)) as conn:
                save_config(conn, config)

        await asyncio.to_thread(save)
        previous = self._config
        self._config = config
        if not config.enabled:
            self._next_run_at = None
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

    async def _run_child(self, trigger: str, session_ids: list[str] | None = None) -> None:
        """Run a pass as a child task, so disabling the agent cancels only the pass."""
        self._current = asyncio.create_task(self.run_pass(trigger, session_ids))
        try:
            await asyncio.wait({self._current})
        finally:
            if not self._current.done():  # the loop itself is being cancelled
                self._current.cancel()
            self._current = None

    async def tick(self) -> None:
        if self._pending_all:
            self._pending_all = False
            await self._run_child("manual_all")
        if self._pending_sessions:
            ids = list(self._pending_sessions)
            self._pending_sessions.clear()
            await self._run_child("manual_session", ids)
        due = self._due_at()
        now = self._clock()
        if due is not None and now >= due:
            if self._paused_until is not None and now >= self._paused_until:
                self._paused_until = None
            self._next_run_at = now + self._config.interval_minutes * 60
            await self._run_child("auto")

    async def _wait(self) -> None:
        if self._pending_all or self._pending_sessions:
            return
        due = self._due_at()
        timeout = None if due is None else max(due - self._clock(), 0)
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
        except TimeoutError:
            pass

    async def run(self) -> None:
        """Scheduler loop, started with the app."""
        await asyncio.to_thread(self.load)
        self.start_schedule()
        self._publish_status()
        while True:
            await self._wait()
            try:
                await self.tick()
            except Exception:
                logger.exception("Falha no agente de resumos")
```

- [x] **Passo 4: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_scheduler.py backend/tests/test_digest_pass.py -q`
Expected: PASS

- [x] **Passo 5: Roadmap**

Marcar `[x] Agendador: elegibilidade, uma sessão por vez, lock, fila de pedidos manuais, parada por erro e limite (AAAA-MM-DD)` e atualizar a contagem.

- [x] **Passo 6: Commit**

```bash
git add backend/vibing/digest/service.py backend/tests/test_digest_scheduler.py ROADMAP.md
git commit -m "[Feat] Agendar passadas do agente de resumos"
```

---

### Tarefa 10: Rotas, integração no app e índice sem as sessões do agente

**Arquivos:**
- Criar: `backend/vibing/api/digest.py`
- Modificar: `backend/vibing/api/__init__.py` (registrar o router), `backend/vibing/app.py` (serviço e tarefa), `backend/vibing/history.py` (`HistoryIndex` com `ignored_dirs`)
- Testar: `backend/tests/test_digest_api.py` (novo), `backend/tests/test_history.py` (acrescentar)

**Interfaces:**
- Consome: `DigestService`, `validate`, `ConfigError`, `store.get_digest`, `store.list_runs`, `SdkDigestModel`.
- Produz:
  - `create_app(..., digest_model: DigestModel | None = None)`; `app.state.digest: DigestService`
  - `HistoryIndex(..., ignored_dirs: Iterable[Path] = ())`
  - Rotas: `GET /api/digest/config` → `{"config": {...}, "status": {...}}`; `PUT /api/digest/config` → mesma forma, 422 com `detail` em texto; `POST /api/digest/run` → 202 com o estado; `GET /api/digest/runs` → lista; `GET /api/sessions/{id}/digest` → resumo ou `null`, 404 para sessão desconhecida; `POST /api/sessions/{id}/digest` → 202 `{"queued": true}`, 404 para sessão desconhecida.

- [x] **Passo 1: Escrever os testes que falham**

```python
# backend/tests/test_digest_api.py
"""Routes of the digest agent."""

import time
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project

from vibing import db
from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app
from vibing.digest import store
from vibing.digest.model import FakeDigestModel
from vibing.digest.store import Digest


@pytest.fixture
def model() -> FakeDigestModel:
    return FakeDigestModel()


@pytest.fixture
def api(model: FakeDigestModel):
    app = create_app(agent_factory=FakeAgentFactory(), digest_model=model)
    with TestClient(app, base_url=BACKEND_URL,
                    headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as client:
        yield client


def new_session(api: TestClient, home: Path) -> str:
    project = make_project(api, home)
    return api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]


def test_config_defaults(api: TestClient) -> None:
    body = api.get("/api/digest/config").json()
    assert body["config"]["enabled"] is False and body["config"]["model"] == "sonnet"
    assert body["status"] == {"enabled": False, "running": False, "next_run_at": None,
                              "paused_until": None}


def test_put_config(api: TestClient) -> None:
    config = api.get("/api/digest/config").json()["config"]
    response = api.put("/api/digest/config", json={**config, "enabled": True, "window_days": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["window_days"] == 5 and body["status"]["enabled"] is True
    assert body["status"]["next_run_at"] is not None
    assert api.get("/api/digest/config").json()["config"]["window_days"] == 5


def test_put_config_rejects_bad_fields(api: TestClient) -> None:
    response = api.put("/api/digest/config", json={"window_days": 0})
    assert response.status_code == 422
    assert response.json()["detail"] == "A janela precisa ser um número inteiro de 1 a 30 dias."


def test_run_and_runs(api: TestClient) -> None:
    assert api.post("/api/digest/run").status_code == 202
    deadline = time.time() + 2
    while not api.get("/api/digest/runs").json() and time.time() < deadline:
        time.sleep(0.01)
    runs = api.get("/api/digest/runs").json()
    assert runs and runs[0]["trigger"] == "manual_all"


def test_session_digest_routes(api: TestClient, home: Path) -> None:
    sid = new_session(api, home)
    assert api.get(f"/api/sessions/{sid}/digest").json() is None
    settings = api.app.state.settings
    with closing(db.connect(settings.db_path)) as conn:
        store.save_digest(conn, Digest(sid, short="Faz X", cursor="u1"))
    body = api.get(f"/api/sessions/{sid}/digest").json()
    assert body["short"] == "Faz X" and "cursor" not in body
    assert api.post(f"/api/sessions/{sid}/digest").json() == {"queued": True}
    assert api.get("/api/sessions/nope/digest").status_code == 404
    assert api.post("/api/sessions/nope/digest").status_code == 404


def test_routes_need_the_app_header(api: TestClient) -> None:
    response = api.get("/api/digest/config", headers={"x-vibing": ""})
    assert response.status_code == 403


def test_put_needs_the_app_origin(api: TestClient) -> None:
    response = api.put("/api/digest/config", json={}, headers={"origin": "https://evil.example"})
    assert response.status_code == 403
```

Em `backend/tests/test_history.py`, acrescentar (use o ajudante que o arquivo já tem para criar um `HistoryIndex` com listagem falsa; o nome muda de arquivo para arquivo, confira com `grep -n "HistoryIndex(" backend/tests/test_history.py`):

```python
@pytest.mark.anyio
async def test_sessions_in_ignored_dirs_are_not_indexed(tmp_path: Path) -> None:
    """The digest agent's throwaway sessions never enter the index, even when a
    registered project contains the app's data folder."""
    db_path = tmp_path / "data" / "vibing.db"
    db.init_db(db_path)
    home = tmp_path / "home"
    add_project(db_path, home, "home")
    agent_dir = home / ".local" / "share" / "vini7-vibing" / "digest-agent"
    fake = FakeHistory()
    fake.add(str(home), info("mine", str(home / "app")), info("agent", str(agent_dir)))
    index = HistoryIndex(db_path, fake.list_sessions, ignored_dirs=[agent_dir])
    await index.sync_all()
    assert set(rows(db_path)) == {"mine"}
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_digest_api.py backend/tests/test_history.py -q`
Expected: FAIL (`TypeError: create_app() got an unexpected keyword argument 'digest_model'`)

- [x] **Passo 3: `HistoryIndex` ignora a pasta do agente**

Em `backend/vibing/history.py`:

1. `HistoryIndex.__init__` ganha o parâmetro `ignored_dirs: Iterable[Path] = ()` (import de `Iterable` de `collections.abc`) e guarda `self._ignored = tuple(str(Path(d)) for d in ignored_dirs)`.
2. No laço de `_store`, antes de `project_id = owner_project(cwd, projects)`:

```python
                if any(_is_within(cwd, ignored) for ignored in self._ignored):
                    continue  # the digest agent's own throwaway sessions
```

- [x] **Passo 4: Escrever as rotas**

```python
# backend/vibing/api/digest.py
"""Routes of the digest agent: settings, passes and summaries."""

import asyncio
import json
from contextlib import closing
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from vibing import db
from vibing.api.deps import DbDep
from vibing.api.sessions import get_session_manager
from vibing.digest import store
from vibing.digest.config import ConfigError, validate
from vibing.digest.service import DigestService
from vibing.sessions import SessionManager

router = APIRouter(prefix="/api")

NOT_FOUND = "Sessão não encontrada."


def get_digest_service(request: Request) -> DigestService:
    return request.app.state.digest


ServiceDep = Annotated[DigestService, Depends(get_digest_service)]
ManagerDep = Annotated[SessionManager, Depends(get_session_manager)]


def _state(service: DigestService) -> dict[str, Any]:
    return {"config": service.config.to_dict(), "status": service.status()}


def _require_session(conn, session_id: str) -> None:
    row = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


@router.get("/digest/config")
async def get_config(service: ServiceDep) -> dict[str, Any]:
    return _state(service)


@router.put("/digest/config")
async def put_config(request: Request, service: ServiceDep, manager: ManagerDep) -> dict[str, Any]:
    try:
        raw = json.loads(await request.body())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON inválido.") from exc
    known = [m.get("value") for m in manager.list_models() if isinstance(m.get("value"), str)]
    try:
        config = validate(raw, known)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await service.update_config(config)
    return _state(service)


@router.post("/digest/run", status_code=status.HTTP_202_ACCEPTED)
async def run_now(service: ServiceDep) -> dict[str, Any]:
    service.request_all()
    return service.status()


@router.get("/digest/runs")
async def list_runs(request: Request) -> list[dict[str, Any]]:
    path = request.app.state.settings.db_path

    def read() -> list[dict[str, Any]]:
        with closing(db.connect(path)) as conn:
            return store.list_runs(conn)

    return await asyncio.to_thread(read)


@router.get("/sessions/{session_id}/digest")
def get_session_digest(session_id: str, conn: DbDep) -> dict[str, Any] | None:
    _require_session(conn, session_id)
    digest = store.get_digest(conn, session_id)
    return None if digest is None else digest.to_dict()


@router.post("/sessions/{session_id}/digest", status_code=status.HTTP_202_ACCEPTED)
def request_session_digest(session_id: str, conn: DbDep, service: ServiceDep) -> dict[str, bool]:
    _require_session(conn, session_id)
    service.request_session(session_id)
    return {"queued": True}
```

Em `backend/vibing/api/__init__.py`, importar `digest` na lista em ordem alfabética e acrescentar `router.include_router(digest.router)` depois de `plans.router`.

Nota: `request_session` é chamado de uma rota síncrona (thread do FastAPI) e mexe num `asyncio.Event`. Para ficar seguro, transforme a rota em `async def` e leia o banco com `asyncio.to_thread`, como `list_runs`:

```python
@router.post("/sessions/{session_id}/digest", status_code=status.HTTP_202_ACCEPTED)
async def request_session_digest(
    session_id: str, request: Request, service: ServiceDep
) -> dict[str, bool]:
    path = request.app.state.settings.db_path

    def check() -> None:
        with closing(db.connect(path)) as conn:
            _require_session(conn, session_id)

    await asyncio.to_thread(check)
    service.request_session(session_id)
    return {"queued": True}
```

Use esta versão, não a síncrona.

- [x] **Passo 5: Integrar no app**

Em `backend/vibing/app.py`:

1. Imports: `from vibing.digest.model import DigestModel, SdkDigestModel` e `from vibing.digest.service import AGENT_DIR_NAME, DigestService`.
2. `create_app` ganha `digest_model: DigestModel | None = None` (documentar na docstring: "`digest_model` defaults to the real SDK; the agent only calls it when enabled or asked").
3. Na `lifespan`, antes de criar `app.state.history`:

```python
        agent_dir = app.state.settings.data_dir / AGENT_DIR_NAME
        app.state.digest = DigestService(
            app.state.settings.db_path,
            app.state.sessions,
            app.state.hub.publish,
            digest_model or SdkDigestModel(agent_dir),
        )
```

4. Na criação de `history.HistoryIndex(...)`, passar `ignored_dirs=[agent_dir]`.
5. Em `tasks`, acrescentar `asyncio.create_task(app.state.digest.run())`.

- [x] **Passo 6: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_digest_api.py backend/tests/test_history.py -q`
Expected: PASS

- [x] **Passo 7: Rodar a suíte do backend**

Run: `uv run pytest -q`
Expected: PASS

- [x] **Passo 8: Roadmap**

Marcar `[x] Rotas de configuração, disparo, registro e resumo por sessão, com eventos no WebSocket` e `[x] Sessões do agente apagadas com delete_session e ignoradas pelo índice do histórico`, com a data, e atualizar a contagem.

- [x] **Passo 9: Commit**

```bash
git add backend/vibing/api/digest.py backend/vibing/api/__init__.py backend/vibing/app.py backend/vibing/history.py backend/tests/test_digest_api.py backend/tests/test_history.py ROADMAP.md
git commit -m "[Feat] Expor rotas do agente de resumos e iniciar o agendador"
```

---

### Tarefa 11: Tipos, chamadas e store do frontend

**Arquivos:**
- Modificar: `frontend/src/types/api.ts`, `frontend/src/api/http.ts`, `frontend/src/stores/realtime.ts`
- Criar: `frontend/src/stores/digest.ts`, `frontend/src/digestConfig.ts`
- Testar: `frontend/src/stores/__tests__/digest.spec.ts`, `frontend/src/__tests__/digestConfig.spec.ts` (novos)

**Interfaces:**
- Produz, em `types/api.ts`: `DigestPhaseKind`, `DigestPhase`, `SessionDigest`, `DigestConfig`, `DigestStatus`, `DigestRunError`, `DigestRun`, `DigestState` (`{ config: DigestConfig; status: DigestStatus }`); `Session` ganha `digest_short?: string | null` e `plan_done?: boolean`.
- Produz, em `api/http.ts`: `getDigestConfig(): Promise<DigestState>`, `putDigestConfig(config: DigestConfig): Promise<DigestState>`, `runDigest(): Promise<DigestStatus>`, `listDigestRuns(): Promise<DigestRun[]>`, `getSessionDigest(id: string): Promise<SessionDigest | null>`, `requestSessionDigest(id: string): Promise<{ queued: boolean }>`.
- Produz, em `stores/digest.ts` (`useDigestStore`): `status: Ref<DigestStatus | null>`, `digests: Ref<Record<string, SessionDigest | null>>`, `pending: Ref<Record<string, boolean>>`, `errors: Ref<Record<string, string | null>>`, `applyStatus(data: unknown)`, `applyDigest(data: unknown)`, `load(sessionId: string): Promise<void>`, `request(sessionId: string): Promise<void>`, `invalidate(): void`.
- Produz, em `digestConfig.ts`: `DIGEST_LIMITS`, `DIGEST_MESSAGES`, `MAX_INSTRUCTIONS`, `PHASE_KIND_LABELS`, `digestConfigProblem(form: DigestForm): string | null`, `digestStatusText(status: DigestStatus | null, now?: Date): string`, `type DigestForm` (valores do formulário como texto para os números).

- [x] **Passo 1: Escrever os testes que falham**

```ts
// frontend/src/__tests__/digestConfig.spec.ts
import { describe, expect, it } from 'vitest'
import { digestConfigProblem, digestStatusText, type DigestForm } from '../digestConfig'

const form = (over: Partial<DigestForm> = {}): DigestForm => ({
  enabled: true, model: 'sonnet', effort: 'medium', extra_instructions: '',
  interval_minutes: '10', min_new_messages: '10', open_turn_minutes: '30', window_days: '3',
  ...over,
})

describe('validação da configuração do agente', () => {
  it('aceita os padrões', () => {
    expect(digestConfigProblem(form())).toBeNull()
  })
  it.each([
    [{ interval_minutes: '1' }, 'O intervalo precisa ser um número inteiro de 2 a 240 minutos.'],
    [{ interval_minutes: '2.5' }, 'O intervalo precisa ser um número inteiro de 2 a 240 minutos.'],
    [{ min_new_messages: '0' }, 'O mínimo de mensagens novas precisa ser um número inteiro de 1 a 500.'],
    [{ open_turn_minutes: '481' }, 'O teto com turno aberto precisa ser um número inteiro de 5 a 480 minutos.'],
    [{ window_days: '' }, 'A janela precisa ser um número inteiro de 1 a 30 dias.'],
    [{ extra_instructions: 'x'.repeat(4001) }, 'As instruções extras podem ter até 4.000 caracteres.'],
    [{ model: '' }, 'Escolha um modelo da lista.'],
  ])('recusa %o', (over, message) => {
    expect(digestConfigProblem(form(over))).toBe(message)
  })
})

describe('texto de estado do agente', () => {
  const now = new Date(2026, 8, 30, 14, 0)
  const at = (h: number, m: number) => Math.floor(new Date(2026, 8, 30, h, m).getTime() / 1000)
  it('desligado, rodando, pausado e próxima passada', () => {
    expect(digestStatusText(null, now)).toBe('Desligado')
    expect(digestStatusText({ enabled: false, running: false, next_run_at: null, paused_until: null }, now)).toBe('Desligado')
    expect(digestStatusText({ enabled: true, running: true, next_run_at: at(14, 10), paused_until: null }, now)).toBe('Rodando…')
    expect(digestStatusText({ enabled: true, running: false, next_run_at: at(14, 10), paused_until: at(18, 0) }, now)).toBe('Pausado até 18:00 (limite da assinatura)')
    expect(digestStatusText({ enabled: true, running: false, next_run_at: at(14, 32), paused_until: null }, now)).toBe('Próxima passada às 14:32')
    expect(digestStatusText({ enabled: false, running: true, next_run_at: null, paused_until: null }, now)).toBe('Rodando…')
  })
})
```

```ts
// frontend/src/stores/__tests__/digest.spec.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { useDigestStore } from '../digest'
import { jsonResponse, routeFetch } from '../../test/factories'
import type { SessionDigest } from '../../types/api'

const digest = (over: Partial<SessionDigest> = {}): SessionDigest => ({
  session_id: 's1', read_at: 100, short: 'Faz X', phases: [], plan_done: false, error: null, error_at: null, ...over,
})

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('store do agente de resumos', () => {
  it('carrega o resumo de uma sessão', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/digest': () => jsonResponse(digest()) }))
    const store = useDigestStore()
    await store.load('s1')
    expect(store.digests.s1?.short).toBe('Faz X')
  })

  it('guarda null para sessão sem resumo', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/digest': () => jsonResponse(null) }))
    const store = useDigestStore()
    await store.load('s1')
    expect(store.digests.s1).toBeNull()
  })

  it('pedido fica pendente até o evento chegar', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/sessions/s1/digest': () => jsonResponse({ queued: true }, 202) }))
    const store = useDigestStore()
    await store.request('s1')
    expect(store.pending.s1).toBe(true)
    store.applyDigest({ session_id: 's1', digest: digest({ short: 'Novo' }) })
    expect(store.pending.s1).toBe(false)
    expect(store.digests.s1?.short).toBe('Novo')
  })

  it('falha no pedido desfaz o pendente e guarda o erro', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/sessions/s1/digest': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404) }))
    const store = useDigestStore()
    await store.request('s1')
    expect(store.pending.s1).toBe(false)
    expect(store.errors.s1).toBe('Sessão não encontrada.')
  })

  it('ignora eventos malformados', () => {
    const store = useDigestStore()
    store.applyDigest(null)
    store.applyDigest({ session_id: 3 })
    store.applyStatus('x')
    expect(store.digests).toEqual({})
    expect(store.status).toBeNull()
  })

  it('aplica o estado e invalida os resumos na reconexão', async () => {
    const store = useDigestStore()
    store.applyStatus({ enabled: true, running: false, next_run_at: 1, paused_until: null })
    expect(store.status?.enabled).toBe(true)
    store.applyDigest({ session_id: 's1', digest: digest() })
    store.invalidate()
    await flushPromises()
    expect('s1' in store.digests).toBe(false)
  })
})
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/__tests__/digestConfig.spec.ts src/stores/__tests__/digest.spec.ts`
Expected: FAIL (módulos inexistentes)

- [x] **Passo 3: Tipos**

Em `frontend/src/types/api.ts`, em `Session`, depois de `group_id`:

```ts
  /** Short sentence of the digest agent's summary; null before the first reading. */
  digest_short?: string | null
  /** The digest agent marked the linked plan as completed. */
  plan_done?: boolean
```

No fim do arquivo:

```ts
export type DigestPhaseKind = 'plan' | 'spec' | 'feature' | 'adjustments' | 'investigation' | 'other'
export interface DigestPhase {
  title: string
  kind: DigestPhaseKind
  status: 'open' | 'done'
  done: string[]
  pending: string[]
  ref: string | null
}
/** Summary kept by the digest agent (`GET /api/sessions/{id}/digest`). */
export interface SessionDigest {
  session_id: string
  read_at: number | null
  short: string | null
  phases: DigestPhase[]
  plan_done: boolean
  error: string | null
  error_at: number | null
}
export interface DigestConfig {
  enabled: boolean
  model: string
  effort: Effort
  extra_instructions: string
  interval_minutes: number
  min_new_messages: number
  open_turn_minutes: number
  window_days: number
}
export interface DigestStatus { enabled: boolean; running: boolean; next_run_at: number | null; paused_until: number | null }
export interface DigestState { config: DigestConfig; status: DigestStatus }
export interface DigestRunError { session_id: string; title: string; message: string }
export interface DigestRun {
  id: number
  started_at: number
  finished_at: number | null
  trigger: 'auto' | 'manual_all' | 'manual_session'
  read_count: number
  skipped_count: number
  errors: DigestRunError[]
  stopped: string | null
}
```

- [x] **Passo 4: Chamadas**

No fim de `frontend/src/api/http.ts` (importando os tipos novos no import de `../types/api`):

```ts
// Digest agent

export function getDigestConfig(): Promise<DigestState> {
  return request('GET', '/api/digest/config')
}

export function putDigestConfig(config: DigestConfig): Promise<DigestState> {
  return request('PUT', '/api/digest/config', config)
}

export function runDigest(): Promise<DigestStatus> {
  return request('POST', '/api/digest/run')
}

export function listDigestRuns(): Promise<DigestRun[]> {
  return request('GET', '/api/digest/runs')
}

export function getSessionDigest(id: string): Promise<SessionDigest | null> {
  return request('GET', `/api/sessions/${encodeURIComponent(id)}/digest`)
}

export function requestSessionDigest(id: string): Promise<{ queued: boolean }> {
  return request('POST', `/api/sessions/${encodeURIComponent(id)}/digest`)
}
```

- [x] **Passo 5: `digestConfig.ts`**

```ts
// frontend/src/digestConfig.ts
import type { DigestPhaseKind, DigestStatus, Effort } from './types/api'

export const MAX_INSTRUCTIONS = 4000

export const DIGEST_LIMITS = {
  interval_minutes: [2, 240],
  min_new_messages: [1, 500],
  open_turn_minutes: [5, 480],
  window_days: [1, 30],
} as const

type NumberField = keyof typeof DIGEST_LIMITS

// Same texts as backend/vibing/digest/config.py MESSAGES.
export const DIGEST_MESSAGES: Record<NumberField | 'model' | 'extra_instructions', string> = {
  model: 'Escolha um modelo da lista.',
  extra_instructions: 'As instruções extras podem ter até 4.000 caracteres.',
  interval_minutes: 'O intervalo precisa ser um número inteiro de 2 a 240 minutos.',
  min_new_messages: 'O mínimo de mensagens novas precisa ser um número inteiro de 1 a 500.',
  open_turn_minutes: 'O teto com turno aberto precisa ser um número inteiro de 5 a 480 minutos.',
  window_days: 'A janela precisa ser um número inteiro de 1 a 30 dias.',
}

export const PHASE_KIND_LABELS: Record<DigestPhaseKind, string> = {
  plan: 'Plano',
  spec: 'Spec',
  feature: 'Feature',
  adjustments: 'Ajustes',
  investigation: 'Investigação',
  other: 'Outro',
}

/** Form values: numbers stay as typed text until saving. */
export interface DigestForm {
  enabled: boolean
  model: string
  effort: Effort
  extra_instructions: string
  interval_minutes: string
  min_new_messages: string
  open_turn_minutes: string
  window_days: string
}

export function digestConfigProblem(form: DigestForm): string | null {
  if (!form.model) return DIGEST_MESSAGES.model
  if (form.extra_instructions.length > MAX_INSTRUCTIONS) return DIGEST_MESSAGES.extra_instructions
  for (const field of Object.keys(DIGEST_LIMITS) as NumberField[]) {
    const raw = String(form[field]).trim()
    const [low, high] = DIGEST_LIMITS[field]
    const value = Number(raw)
    if (!/^\d+$/.test(raw) || value < low || value > high) return DIGEST_MESSAGES[field]
  }
  return null
}

function hhmm(seconds: number): string {
  const date = new Date(seconds * 1000)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function digestStatusText(status: DigestStatus | null, now: Date = new Date()): string {
  if (!status) return 'Desligado'
  if (status.running) return 'Rodando…'
  if (!status.enabled) return 'Desligado'
  if (status.paused_until && status.paused_until * 1000 > now.getTime()) {
    return `Pausado até ${hhmm(status.paused_until)} (limite da assinatura)`
  }
  if (status.next_run_at) return `Próxima passada às ${hhmm(status.next_run_at)}`
  return 'Ligado'
}
```

- [x] **Passo 6: Store**

```ts
// frontend/src/stores/digest.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { errorMessage, getSessionDigest, requestSessionDigest } from '../api/http'
import type { DigestStatus, SessionDigest } from '../types/api'

function isStatus(value: unknown): value is DigestStatus {
  const v = value as Partial<DigestStatus> | null
  return !!v && typeof v === 'object' && typeof v.enabled === 'boolean' && typeof v.running === 'boolean'
}

/** Digest agent state and the summaries of the sessions opened in Details. */
export const useDigestStore = defineStore('digest', () => {
  const status = ref<DigestStatus | null>(null)
  // Absent: never loaded. null: loaded, no summary yet.
  const digests = ref<Record<string, SessionDigest | null>>({})
  const pending = ref<Record<string, boolean>>({})
  const errors = ref<Record<string, string | null>>({})
  // Only the newest load per session wins.
  const tickets: Record<string, number> = {}

  function applyStatus(data: unknown): void {
    if (isStatus(data)) status.value = { ...data }
  }

  function applyDigest(data: unknown): void {
    const d = data as { session_id?: unknown; digest?: unknown } | null
    if (!d || typeof d.session_id !== 'string' || !d.digest || typeof d.digest !== 'object') return
    digests.value = { ...digests.value, [d.session_id]: d.digest as SessionDigest }
    pending.value = { ...pending.value, [d.session_id]: false }
  }

  async function load(sessionId: string): Promise<void> {
    const mine = (tickets[sessionId] = (tickets[sessionId] ?? 0) + 1)
    try {
      const fresh = await getSessionDigest(sessionId)
      if (mine !== tickets[sessionId]) return
      digests.value = { ...digests.value, [sessionId]: fresh }
      errors.value = { ...errors.value, [sessionId]: null }
    } catch (e) {
      if (mine !== tickets[sessionId]) return
      errors.value = { ...errors.value, [sessionId]: errorMessage(e) }
    }
  }

  async function request(sessionId: string): Promise<void> {
    pending.value = { ...pending.value, [sessionId]: true }
    errors.value = { ...errors.value, [sessionId]: null }
    try {
      await requestSessionDigest(sessionId)
    } catch (e) {
      pending.value = { ...pending.value, [sessionId]: false }
      errors.value = { ...errors.value, [sessionId]: errorMessage(e) }
    }
  }

  /** Events were lost while the socket was down: loaded summaries are read again. */
  function invalidate(): void {
    digests.value = {}
    pending.value = {}
  }

  return { status, digests, pending, errors, applyStatus, applyDigest, load, request, invalidate }
})
```

- [x] **Passo 7: Eventos**

Em `frontend/src/stores/realtime.ts`, importar `useDigestStore` e acrescentar à lista `offs`, antes de `socket.onReconnect`:

```ts
    // The digest agent wrote a summary, or its state changed (both global events).
    socket.on('session.digest', (event) => useDigestStore().applyDigest(event.data)),
    socket.on('digest.status', (event) => useDigestStore().applyStatus(event.data)),
```

e, dentro do `socket.onReconnect`, antes de `loadEverything()`: `useDigestStore().invalidate()`.

Acrescente em `frontend/src/stores/__tests__/realtime.spec.ts` (importando `useDigestStore` de `../digest`), dentro do `describe('bindRealtime')`:

```ts
  it('leva session.digest e digest.status ao store do agente', () => {
    const sockets: FakeSocket[] = []
    const socket = new EventSocket({
      url: 'ws://x/ws',
      createSocket: () => {
        const s = new FakeSocket()
        sockets.push(s)
        return s
      },
      initialDelay: 10,
    })
    bindRealtime(socket)
    socket.connect()
    sockets[0]!.onopen?.({})
    const digest = { session_id: 's1', read_at: 1, short: 'Faz X', phases: [], plan_done: false, error: null, error_at: null }
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: null, seq: 0, type: 'session.digest', data: { session_id: 's1', digest } }),
    })
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ session_id: null, seq: 0, type: 'digest.status', data: { enabled: true, running: true, next_run_at: null, paused_until: null } }),
    })
    const store = useDigestStore()
    expect(store.digests.s1?.short).toBe('Faz X')
    expect(store.status?.running).toBe(true)
  })
```

- [x] **Passo 8: Rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/__tests__/digestConfig.spec.ts src/stores/__tests__/digest.spec.ts src/stores/__tests__/realtime.spec.ts`
Expected: PASS

- [x] **Passo 9: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/http.ts frontend/src/stores/digest.ts frontend/src/stores/realtime.ts frontend/src/digestConfig.ts frontend/src/__tests__/digestConfig.spec.ts frontend/src/stores/__tests__/digest.spec.ts frontend/src/stores/__tests__/realtime.spec.ts
git commit -m "[Feat] Adicionar store e chamadas do agente de resumos no frontend"
```

---

### Tarefa 12: Aba "Agente de resumos" nas Preferências

**Arquivos:**
- Criar: `frontend/src/components/preferences/GeneralPreferences.vue` (o formulário atual, movido sem mudança de comportamento)
- Criar: `frontend/src/components/preferences/DigestAgentPreferences.vue`
- Modificar: `frontend/src/views/PreferencesView.vue` (casca com título e abas)
- Testar: `frontend/src/views/__tests__/PreferencesView.spec.ts` (acrescentar), `frontend/src/components/preferences/__tests__/DigestAgentPreferences.spec.ts` (novo)

**Interfaces:**
- Consome: `getDigestConfig`, `putDigestConfig`, `runDigest`, `listDigestRuns`, `useDigestStore`, `useModelsStore`, `digestConfigProblem`, `digestStatusText`, `EFFORT_LABELS`, `ALL_EFFORTS` de `sessionOptions.ts`, `formatActivity`.
- Produz: aba na URL `?aba=agente` (padrão: Geral). Seletores de teste: `[data-test="tab-general"]`, `[data-test="tab-agent"]`, `#digest-enabled`, `#digest-model`, `#digest-effort`, `#digest-instructions`, `#digest-interval`, `#digest-min`, `#digest-open-turn`, `#digest-window`, `[data-test="digest-save"]`, `[data-test="digest-saved"]`, `[data-test="digest-run"]`, `[data-test="digest-status"]`, `[data-test="digest-runs"]`, `[data-test="digest-run-row"]`, `[data-test="digest-run-toggle"]`, `[data-test="digest-run-details"]`.

- [x] **Passo 1: Escrever os testes que falham**

Em `frontend/src/views/__tests__/PreferencesView.spec.ts`, acrescentar ao `stub` as rotas do agente (`'GET /api/digest/config'`, `'GET /api/digest/runs'`) e os testes:

```ts
  it('abre na aba Geral e troca para a do agente pela URL', async () => {
    stub({ preferences: {} })
    const w = await mountView()
    expect(w.find('[data-test="tab-general"]').attributes('aria-selected')).toBe('true')
    expect(w.find('#pref-editor').exists()).toBe(true)
    await w.find('[data-test="tab-agent"]').trigger('click')
    await flushPromises()
    expect(w.find('#digest-enabled').exists()).toBe(true)
    expect(w.find('#pref-editor').exists()).toBe(false)
  })
```

No `stub` deste arquivo, as respostas novas:

```ts
    'GET /api/digest/config': () => jsonResponse({
      config: { enabled: false, model: 'sonnet', effort: 'medium', extra_instructions: '', interval_minutes: 10, min_new_messages: 10, open_turn_minutes: 30, window_days: 3 },
      status: { enabled: false, running: false, next_run_at: null, paused_until: null },
    }),
    'GET /api/digest/runs': () => jsonResponse([]),
```

```ts
// frontend/src/components/preferences/__tests__/DigestAgentPreferences.spec.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import DigestAgentPreferences from '../DigestAgentPreferences.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { useDigestStore } from '../../../stores/digest'
import type { DigestConfig, DigestRun } from '../../../types/api'

enableAutoUnmount(afterEach)

const CONFIG: DigestConfig = {
  enabled: false, model: 'sonnet', effort: 'medium', extra_instructions: '',
  interval_minutes: 10, min_new_messages: 10, open_turn_minutes: 30, window_days: 3,
}
const STATUS = { enabled: false, running: false, next_run_at: null, paused_until: null }
const RUN: DigestRun = {
  id: 1, started_at: 1000, finished_at: 1010, trigger: 'auto', read_count: 2, skipped_count: 3,
  errors: [{ session_id: 's1', title: 'Sessão A', message: 'Resposta ruim.' }], stopped: null,
}

let pinia: Pinia
let puts: unknown[]
let runCalls: number

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  puts = []
  runCalls = 0
})
afterEach(() => vi.unstubAllGlobals())

function stub(put?: (body: DigestConfig) => Response) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/digest/config': () => jsonResponse({ config: CONFIG, status: STATUS }),
    'PUT /api/digest/config': (init) => {
      const body = JSON.parse(String(init?.body)) as DigestConfig
      puts.push(body)
      return put ? put(body) : jsonResponse({ config: body, status: { ...STATUS, enabled: body.enabled } })
    },
    'POST /api/digest/run': () => { runCalls++; return jsonResponse({ ...STATUS, running: true }, 202) },
    'GET /api/digest/runs': () => jsonResponse([RUN]),
    'GET /api/models': () => jsonResponse([{ value: 'sonnet', displayName: 'Sonnet' }, { value: 'haiku', displayName: 'Haiku' }]),
  }))
}

async function mountTab() {
  const w = mount(DigestAgentPreferences, { global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('aba do agente de resumos', () => {
  it('mostra a configuração salva e o estado', async () => {
    stub()
    const w = await mountTab()
    expect((w.find('#digest-enabled').element as HTMLInputElement).checked).toBe(false)
    expect((w.find('#digest-model').element as HTMLSelectElement).value).toBe('sonnet')
    expect((w.find('#digest-effort').element as HTMLSelectElement).value).toBe('medium')
    expect((w.find('#digest-interval').element as HTMLInputElement).value).toBe('10')
    expect(w.find('[data-test="digest-status"]').text()).toBe('Desligado')
  })

  it('salva o formulário inteiro', async () => {
    stub()
    const w = await mountTab()
    await w.find('#digest-enabled').setValue(true)
    await w.find('#digest-model').setValue('haiku')
    await w.find('#digest-instructions').setValue('Cite a tarefa.')
    await w.find('#digest-window').setValue('7')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toEqual([{ ...CONFIG, enabled: true, model: 'haiku', extra_instructions: 'Cite a tarefa.', window_days: 7 }])
    expect(w.find('[data-test="digest-saved"]').exists()).toBe(true)
  })

  it('valida no navegador sem chamar o servidor', async () => {
    stub()
    const w = await mountTab()
    await w.find('#digest-interval').setValue('1')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(puts).toEqual([])
    expect(w.find('[role="alert"]').text()).toBe('O intervalo precisa ser um número inteiro de 2 a 240 minutos.')
  })

  it('mostra o erro do servidor', async () => {
    stub(() => jsonResponse({ detail: 'Escolha um modelo da lista.' }, 422))
    const w = await mountTab()
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Escolha um modelo da lista.')
  })

  it('rodar agora chama a rota e fica desabilitado enquanto roda', async () => {
    stub()
    const w = await mountTab()
    await w.find('[data-test="digest-run"]').trigger('click')
    await flushPromises()
    expect(runCalls).toBe(1)
    useDigestStore().applyStatus({ ...STATUS, running: true })
    await flushPromises()
    expect(w.find('[data-test="digest-run"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="digest-status"]').text()).toBe('Rodando…')
  })

  it('lista as passadas e abre os erros', async () => {
    stub()
    const w = await mountTab()
    const row = w.find('[data-test="digest-run-row"]')
    expect(row.text()).toContain('2')
    expect(row.text()).toContain('3')
    expect(w.find('[data-test="digest-run-details"]').exists()).toBe(false)
    await w.find('[data-test="digest-run-toggle"]').trigger('click')
    expect(w.find('[data-test="digest-run-details"]').text()).toContain('Sessão A: Resposta ruim.')
  })

  it('recarrega o registro quando uma passada termina', async () => {
    stub()
    const w = await mountTab()
    const store = useDigestStore()
    store.applyStatus({ ...STATUS, running: true })
    await flushPromises()
    const before = vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/digest/runs').length
    store.applyStatus({ ...STATUS, running: false })
    await flushPromises()
    const after = vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/digest/runs').length
    expect(after).toBe(before + 1)
    expect(w.exists()).toBe(true)
  })
})
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/views/__tests__/PreferencesView.spec.ts src/components/preferences`
Expected: FAIL

- [x] **Passo 3: Mover o formulário atual para `GeneralPreferences.vue`**

Crie `frontend/src/components/preferences/GeneralPreferences.vue` com todo o `<script setup>` atual de `PreferencesView.vue` (ajuste os caminhos de import de `../` para `../../`) e o `<template>` atual **sem** o `<header>` do título (ele passa para a casca). O `<form>` perde `aria-labelledby` e ganha `aria-label="Preferências gerais"`; o resto (ids, `data-test`, textos, rodapé) fica igual.

- [x] **Passo 4: Casca com abas**

```vue
<!-- frontend/src/views/PreferencesView.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DigestAgentPreferences from '../components/preferences/DigestAgentPreferences.vue'
import GeneralPreferences from '../components/preferences/GeneralPreferences.vue'

const TABS = [
  { id: 'geral', label: 'Geral' },
  { id: 'agente', label: 'Agente de resumos' },
] as const
type Tab = (typeof TABS)[number]['id']

const route = useRoute()
const router = useRouter()
const tab = computed<Tab>(() => (route.query.aba === 'agente' ? 'agente' : 'geral'))

function select(id: Tab) {
  if (id === tab.value) return
  void router.replace({ query: { ...route.query, aba: id === 'geral' ? undefined : id } })
}

function onKey(event: KeyboardEvent) {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
  const index = TABS.findIndex((t) => t.id === tab.value)
  const next = TABS[(index + (event.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length]
  select(next.id)
  requestAnimationFrame(() => document.getElementById(`tab-${next.id}`)?.focus())
}
</script>

<template>
  <div class="flex min-h-full items-start justify-center px-6 py-10">
    <div class="flex w-full max-w-[720px] flex-col rounded-xl border border-line-strong bg-panel">
      <header class="flex flex-col gap-4 border-b border-line px-7 pt-6">
        <div class="flex flex-col gap-1">
          <h1 id="preferences-title" class="m-0 text-[22px] font-semibold tracking-tight">Preferências</h1>
          <p class="m-0 text-fg-muted">Ajustes do app neste computador.</p>
        </div>
        <div role="tablist" aria-labelledby="preferences-title" class="-mb-px flex gap-1" @keydown="onKey">
          <button
            v-for="t in TABS"
            :id="`tab-${t.id}`"
            :key="t.id"
            type="button"
            role="tab"
            :data-test="t.id === 'geral' ? 'tab-general' : 'tab-agent'"
            :aria-selected="String(tab === t.id)"
            :aria-controls="`panel-${t.id}`"
            :tabindex="tab === t.id ? 0 : -1"
            class="h-10 border-b-2 px-3 text-sm font-medium"
            :class="tab === t.id ? 'border-primary text-fg' : 'border-transparent text-fg-muted hover:text-fg'"
            @click="select(t.id)"
          >{{ t.label }}</button>
        </div>
      </header>
      <section :id="`panel-${tab}`" role="tabpanel" :aria-labelledby="`tab-${tab}`">
        <GeneralPreferences v-if="tab === 'geral'" />
        <DigestAgentPreferences v-else />
      </section>
    </div>
  </div>
</template>
```

Se algum teste antigo de `PreferencesView.spec.ts` procurar o título dentro do `form`, ajuste o seletor para a página (o texto continua o mesmo).

- [x] **Passo 5: Aba do agente**

```vue
<!-- frontend/src/components/preferences/DigestAgentPreferences.vue -->
<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { errorMessage, getDigestConfig, listDigestRuns, putDigestConfig, runDigest } from '../../api/http'
import { MAX_INSTRUCTIONS, digestConfigProblem, digestStatusText, type DigestForm } from '../../digestConfig'
import { formatActivity } from '../../format'
import { ALL_EFFORTS, EFFORT_LABELS } from '../../sessionOptions'
import { useDigestStore } from '../../stores/digest'
import { useModelsStore } from '../../stores/models'
import type { DigestConfig, DigestRun } from '../../types/api'

const digest = useDigestStore()
const models = useModelsStore()

const TRIGGER_LABELS: Record<DigestRun['trigger'], string> = {
  auto: 'Automática',
  manual_all: 'Rodar agora',
  manual_session: 'Resumir conversa',
}

const form = reactive<DigestForm>({
  enabled: false, model: 'sonnet', effort: 'medium', extra_instructions: '',
  interval_minutes: '10', min_new_messages: '10', open_turn_minutes: '30', window_days: '3',
})
const loading = ref(true)
const loadError = ref<string | null>(null)
const saving = ref(false)
const saved = ref(false)
const error = ref<string | null>(null)
const runs = ref<DigestRun[]>([])
const runsError = ref<string | null>(null)
const open = ref<Record<number, boolean>>({})
const starting = ref(false)

const ready = computed(() => !loading.value && loadError.value === null)
const running = computed(() => digest.status?.running ?? false)
const statusText = computed(() => digestStatusText(digest.status))
// The saved model stays selectable even when the SDK list no longer has it.
const modelOptions = computed(() => {
  const list = models.models.map((m) => ({ value: m.value, label: m.displayName || m.value }))
  if (form.model && !list.some((m) => m.value === form.model)) list.unshift({ value: form.model, label: form.model })
  return list
})

function fill(config: DigestConfig) {
  form.enabled = config.enabled
  form.model = config.model
  form.effort = config.effort
  form.extra_instructions = config.extra_instructions
  form.interval_minutes = String(config.interval_minutes)
  form.min_new_messages = String(config.min_new_messages)
  form.open_turn_minutes = String(config.open_turn_minutes)
  form.window_days = String(config.window_days)
}

async function loadRuns() {
  try {
    runs.value = await listDigestRuns()
    runsError.value = null
  } catch (e) {
    runsError.value = errorMessage(e)
  }
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const state = await getDigestConfig()
    fill(state.config)
    digest.applyStatus(state.status)
    saved.value = false
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
  void models.ensure()
  void loadRuns()
}

watch(form, () => { saved.value = false })
// A pass finished: its line in the log changed.
watch(running, (now, before) => { if (before && !now) void loadRuns() })

async function save() {
  if (!ready.value || saving.value) return
  error.value = null
  saved.value = false
  const problem = digestConfigProblem(form)
  if (problem) {
    error.value = problem
    return
  }
  saving.value = true
  try {
    const state = await putDigestConfig({
      enabled: form.enabled,
      model: form.model,
      effort: form.effort,
      extra_instructions: form.extra_instructions,
      interval_minutes: Number(form.interval_minutes),
      min_new_messages: Number(form.min_new_messages),
      open_turn_minutes: Number(form.open_turn_minutes),
      window_days: Number(form.window_days),
    })
    fill(state.config)
    digest.applyStatus(state.status)
    await nextTick() // let the form watcher run before confirming
    saved.value = true
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

async function runNow() {
  if (running.value || starting.value) return
  starting.value = true
  error.value = null
  try {
    digest.applyStatus(await runDigest())
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    starting.value = false
  }
}

onMounted(load)

const label = 'font-mono text-xs tracking-[0.08em] text-fg-muted uppercase'
const input = 'h-11 rounded-lg border border-line-strong bg-bg px-3.5 text-sm text-fg outline-none focus:border-primary disabled:opacity-40'
</script>

<template>
  <div class="flex flex-col">
    <div v-if="loadError" class="flex flex-col items-start gap-3 px-7 py-6">
      <p role="alert" class="m-0 w-full rounded-lg border border-secondary/40 bg-card px-3.5 py-2.5 text-sm text-secondary-soft">
        Não foi possível ler a configuração do agente. {{ loadError }}
      </p>
      <button type="button" class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card" @click="load">Tentar de novo</button>
    </div>

    <form class="flex flex-col" aria-label="Agente de resumos" :aria-busy="loading" @submit.prevent="save">
      <div class="flex flex-col gap-6 px-7 py-6">
        <p class="m-0 text-sm text-fg-muted">
          Lê as conversas em andamento de tempos em tempos e mantém um resumo em fases de cada uma, visível em Detalhes e na lista de conversas. Só lê: não executa comandos nem altera arquivos. Cada leitura usa a sua assinatura.
        </p>

        <div class="flex items-center justify-between gap-4">
          <label for="digest-enabled" class="flex items-center gap-3 text-sm font-medium text-fg">
            <input id="digest-enabled" v-model="form.enabled" type="checkbox" role="switch" :disabled="!ready" class="size-5 accent-[var(--color-primary)]" />
            Ligado
          </label>
          <span data-test="digest-status" role="status" class="text-sm text-fg-muted">{{ statusText }}</span>
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div class="flex flex-col gap-2">
            <label for="digest-model" :class="label">Modelo</label>
            <select id="digest-model" v-model="form.model" :disabled="!ready" :class="input">
              <option v-for="m in modelOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </div>
          <div class="flex flex-col gap-2">
            <label for="digest-effort" :class="label">Raciocínio</label>
            <select id="digest-effort" v-model="form.effort" :disabled="!ready" :class="input">
              <option v-for="e in ALL_EFFORTS" :key="e" :value="e">{{ EFFORT_LABELS[e] }}</option>
            </select>
          </div>
        </div>

        <div class="flex flex-col gap-2">
          <label for="digest-instructions" :class="label">Instruções extras</label>
          <textarea
            id="digest-instructions"
            v-model="form.extra_instructions"
            rows="4"
            :maxlength="MAX_INSTRUCTIONS"
            :disabled="!ready"
            aria-describedby="digest-instructions-help"
            class="rounded-lg border border-line-strong bg-bg px-3.5 py-2.5 text-sm text-fg outline-none focus:border-primary disabled:opacity-40"
          />
          <p id="digest-instructions-help" class="m-0 flex justify-between text-xs text-fg-muted">
            <span>Somadas às regras fixas do agente. Ex.: "cite sempre o número da tarefa".</span>
            <span>{{ form.extra_instructions.length }}/{{ MAX_INSTRUCTIONS }}</span>
          </p>
        </div>

        <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div class="flex flex-col gap-2">
            <label for="digest-interval" :class="label">Intervalo (min)</label>
            <input id="digest-interval" v-model="form.interval_minutes" type="number" inputmode="numeric" min="2" max="240" step="1" :disabled="!ready" :class="input" />
          </div>
          <div class="flex flex-col gap-2">
            <label for="digest-min" :class="label">Mínimo de mensagens</label>
            <input id="digest-min" v-model="form.min_new_messages" type="number" inputmode="numeric" min="1" max="500" step="1" :disabled="!ready" :class="input" />
          </div>
          <div class="flex flex-col gap-2">
            <label for="digest-open-turn" :class="label">Teto com turno aberto (min)</label>
            <input id="digest-open-turn" v-model="form.open_turn_minutes" type="number" inputmode="numeric" min="5" max="480" step="1" :disabled="!ready" :class="input" />
          </div>
          <div class="flex flex-col gap-2">
            <label for="digest-window" :class="label">Janela (dias)</label>
            <input id="digest-window" v-model="form.window_days" type="number" inputmode="numeric" min="1" max="30" step="1" :disabled="!ready" :class="input" />
          </div>
        </div>
        <p class="m-0 text-xs text-fg-muted">
          Uma conversa é lida de novo quando tem pelo menos o mínimo de mensagens novas e o turno terminou, ou quando o turno está aberto há mais que o teto. Conversas finalizadas ou paradas há mais dias que a janela não são lidas.
        </p>
      </div>

      <p v-if="error" role="alert" class="mx-7 mb-4 rounded-lg border border-secondary/40 bg-card px-3.5 py-2.5 text-sm text-secondary-soft">{{ error }}</p>

      <footer class="flex items-center justify-end gap-3 border-t border-line px-7 pt-4 pb-5">
        <p v-if="saved" data-test="digest-saved" role="status" class="m-0 text-sm text-primary-soft">Configuração salva</p>
        <button
          type="button"
          data-test="digest-run"
          class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!ready || running || starting"
          @click="runNow"
        >Rodar agora</button>
        <button
          type="submit"
          data-test="digest-save"
          class="h-11 rounded-lg bg-primary px-[18px] font-semibold text-primary-fg hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!ready || saving"
        >{{ saving ? 'Salvando…' : 'Salvar' }}</button>
      </footer>
    </form>

    <section aria-labelledby="digest-runs-title" class="flex flex-col gap-2 border-t border-line px-7 py-6">
      <h2 id="digest-runs-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Últimas passadas</h2>
      <p v-if="runsError" role="alert" class="m-0 text-sm text-secondary-soft">{{ runsError }}</p>
      <p v-else-if="runs.length === 0" class="m-0 text-sm text-fg-muted">Nenhuma passada ainda.</p>
      <table v-else data-test="digest-runs" class="w-full text-left text-sm">
        <thead class="text-xs text-fg-muted">
          <tr><th class="py-1 font-normal">Quando</th><th class="font-normal">Origem</th><th class="font-normal">Lidas</th><th class="font-normal">Puladas</th><th class="font-normal">Erros</th></tr>
        </thead>
        <tbody>
          <template v-for="run in runs" :key="run.id">
            <tr data-test="digest-run-row" class="border-t border-line">
              <td class="py-1.5">{{ formatActivity(run.started_at) }}</td>
              <td>{{ TRIGGER_LABELS[run.trigger] }}</td>
              <td>{{ run.read_count }}</td>
              <td>{{ run.skipped_count }}</td>
              <td>
                <button
                  v-if="run.errors.length || run.stopped"
                  type="button"
                  data-test="digest-run-toggle"
                  :aria-expanded="String(!!open[run.id])"
                  class="rounded px-1 text-secondary-soft hover:bg-card"
                  @click="open = { ...open, [run.id]: !open[run.id] }"
                >{{ run.errors.length }}{{ run.stopped ? ' · parou' : '' }}</button>
                <span v-else class="text-fg-muted">0</span>
              </td>
            </tr>
            <tr v-if="open[run.id]" data-test="digest-run-details">
              <td colspan="5" class="pb-2 text-xs text-fg-muted">
                <p v-if="run.stopped" class="m-0">Parou: {{ run.stopped }}</p>
                <p v-for="e in run.errors" :key="e.session_id" class="m-0">{{ e.title }}: {{ e.message }}</p>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </section>
  </div>
</template>
```

- [x] **Passo 6: Rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/views/__tests__/PreferencesView.spec.ts src/components/preferences`
Expected: PASS

- [x] **Passo 7: Suíte e compilação**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: PASS e compilação sem erro de tipo

- [x] **Passo 8: Roadmap**

Marcar `[x] Aba "Agente de resumos" nas Preferências, com registro das passadas e "Rodar agora"` com a data e atualizar a contagem.

- [x] **Passo 9: Commit**

```bash
git add frontend/src/views/PreferencesView.vue frontend/src/components/preferences frontend/src/views/__tests__/PreferencesView.spec.ts ROADMAP.md
git commit -m "[UI] Adicionar aba do agente de resumos nas preferências"
```

---

### Tarefa 13: Seção "Resumo" em Detalhes

**Arquivos:**
- Criar: `frontend/src/components/details/DigestSection.vue`
- Modificar: `frontend/src/components/details/DetailsPanel.vue` (incluir a seção entre Propriedades e Alterações)
- Testar: `frontend/src/components/details/__tests__/DigestSection.spec.ts` (novo)

**Interfaces:**
- Consome: `useDigestStore` (`digests`, `pending`, `errors`, `load`, `request`), `PHASE_KIND_LABELS`, `formatActivity`.
- Seletores: `[data-test="details-digest"]`, `[data-test="digest-empty"]`, `[data-test="digest-short"]`, `[data-test="digest-plan-done"]`, `[data-test="digest-phase"]`, `[data-test="digest-error"]`, `[data-test="digest-read-at"]`, `[data-test="digest-request"]`.

- [x] **Passo 1: Escrever os testes que falham**

```ts
// frontend/src/components/details/__tests__/DigestSection.spec.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import DigestSection from '../DigestSection.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { useDigestStore } from '../../../stores/digest'
import type { SessionDigest } from '../../../types/api'

enableAutoUnmount(afterEach)

const DIGEST: SessionDigest = {
  session_id: 's1', read_at: Math.floor(Date.now() / 1000) - 120, short: 'Executa o plano do agrupador',
  plan_done: false, error: null, error_at: null,
  phases: [
    { title: 'Plano do agrupador', kind: 'plan', status: 'done', done: ['Tarefa 1: tabela'], pending: [], ref: '/p/docs/superpowers/plans/agrupador.md' },
    { title: 'Ajustes no menu', kind: 'adjustments', status: 'open', done: [], pending: ['Ordenar por nome'], ref: null },
  ],
}

let pinia: Pinia
let posts: number

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  posts = 0
})
afterEach(() => vi.unstubAllGlobals())

function stub(digest: SessionDigest | null) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/digest': () => jsonResponse(digest),
    'POST /api/sessions/s1/digest': () => { posts++; return jsonResponse({ queued: true }, 202) },
  }))
}

async function mountSection() {
  const w = mount(DigestSection, { props: { sessionId: 's1' }, global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('seção Resumo', () => {
  it('sem resumo mostra o aviso e o botão', async () => {
    stub(null)
    const w = await mountSection()
    expect(w.find('[data-test="digest-empty"]').text()).toBe('Ainda não resumida')
    expect(w.find('[data-test="digest-request"]').text()).toBe('Resumir agora')
  })

  it('mostra frase, fases, feito, falta e plano ligado', async () => {
    stub(DIGEST)
    const w = await mountSection()
    expect(w.find('[data-test="digest-short"]').text()).toBe('Executa o plano do agrupador')
    const phases = w.findAll('[data-test="digest-phase"]')
    expect(phases).toHaveLength(2)
    expect(phases[0].text()).toContain('Plano')
    expect(phases[0].text()).toContain('Concluída')
    expect(phases[0].text()).toContain('Tarefa 1: tabela')
    expect(phases[0].text()).toContain('agrupador.md')
    expect(phases[1].text()).toContain('Aberta')
    expect(phases[1].text()).toContain('Ordenar por nome')
    expect(w.find('[data-test="digest-read-at"]').text()).toBe('Lido há 2 min')
    expect(w.find('[data-test="digest-plan-done"]').exists()).toBe(false)
  })

  it('mostra o selo de plano concluído', async () => {
    stub({ ...DIGEST, plan_done: true })
    const w = await mountSection()
    expect(w.find('[data-test="digest-plan-done"]').text()).toBe('Plano concluído')
  })

  it('mostra o erro sem esconder o resumo', async () => {
    stub({ ...DIGEST, error: 'O agente demorou demais para responder.' })
    const w = await mountSection()
    expect(w.find('[data-test="digest-error"]').text()).toBe('O agente demorou demais para responder.')
    expect(w.find('[data-test="digest-short"]').exists()).toBe(true)
  })

  it('resumir agora fica em "Resumindo…" até o evento chegar', async () => {
    stub(DIGEST)
    const w = await mountSection()
    await w.find('[data-test="digest-request"]').trigger('click')
    await flushPromises()
    expect(posts).toBe(1)
    const button = w.find('[data-test="digest-request"]')
    expect(button.text()).toBe('Resumindo…')
    expect(button.attributes('disabled')).toBeDefined()
    useDigestStore().applyDigest({ session_id: 's1', digest: { ...DIGEST, short: 'Nova frase' } })
    await flushPromises()
    expect(w.find('[data-test="digest-short"]').text()).toBe('Nova frase')
    expect(w.find('[data-test="digest-request"]').text()).toBe('Resumir agora')
  })

  it('recarrega depois de invalidar', async () => {
    stub(DIGEST)
    await mountSection()
    const calls = () => vi.mocked(fetch).mock.calls.filter(([u]) => u === '/api/sessions/s1/digest').length
    const before = calls()
    useDigestStore().invalidate()
    await flushPromises()
    expect(calls()).toBe(before + 1)
  })
})
```

- [x] **Passo 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/details/__tests__/DigestSection.spec.ts`
Expected: FAIL

- [x] **Passo 3: Escrever o componente**

```vue
<!-- frontend/src/components/details/DigestSection.vue -->
<script setup lang="ts">
import { computed, watch } from 'vue'
import { PHASE_KIND_LABELS } from '../../digestConfig'
import { formatActivity } from '../../format'
import { useDigestStore } from '../../stores/digest'

const props = defineProps<{ sessionId: string }>()
const store = useDigestStore()

const loaded = computed(() => props.sessionId in store.digests)
const digest = computed(() => store.digests[props.sessionId] ?? null)
const pending = computed(() => !!store.pending[props.sessionId])
const requestError = computed(() => store.errors[props.sessionId] ?? null)
const hasSummary = computed(() => !!digest.value && (!!digest.value.short || digest.value.phases.length > 0))

// Loads when the session changes and again after `invalidate()` (socket came back).
watch([() => props.sessionId, loaded], ([id, isLoaded]) => {
  if (!isLoaded) void store.load(id)
}, { immediate: true })

const fileName = (path: string) => path.split('/').pop() ?? path
</script>

<template>
  <section data-test="details-digest" aria-labelledby="digest-title" class="flex flex-col gap-3">
    <h3 id="digest-title" class="m-0 flex items-center gap-2 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">
      Resumo
      <span v-if="digest?.plan_done" data-test="digest-plan-done" class="rounded border border-primary/40 px-1.5 font-sans text-[11px] tracking-normal normal-case text-primary-soft">Plano concluído</span>
    </h3>

    <div v-if="!loaded" class="flex items-center justify-between gap-2 text-sm">
      <span :class="requestError ? 'text-secondary-soft' : 'text-fg-muted'" :role="requestError ? 'alert' : undefined">{{ requestError ?? 'Carregando…' }}</span>
      <button v-if="requestError" type="button" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="store.load(sessionId)">Tentar de novo</button>
    </div>
    <template v-else>
      <p v-if="!hasSummary" data-test="digest-empty" class="m-0 text-sm text-fg-muted">Ainda não resumida</p>
      <template v-else>
        <p v-if="digest?.short" data-test="digest-short" class="m-0 text-sm font-medium text-fg">{{ digest.short }}</p>
        <ol class="m-0 flex list-none flex-col gap-3 p-0">
          <li
            v-for="(phase, i) in digest?.phases ?? []"
            :key="i"
            data-test="digest-phase"
            class="flex flex-col gap-1.5 rounded-lg border border-line p-3"
            :class="phase.status === 'done' ? 'bg-bg' : 'bg-card'"
          >
            <div class="flex items-center gap-2 text-xs text-fg-muted">
              <span class="font-mono uppercase">{{ PHASE_KIND_LABELS[phase.kind] }}</span>
              <span aria-hidden="true">·</span>
              <span :class="phase.status === 'open' ? 'text-primary-soft' : ''">{{ phase.status === 'open' ? 'Aberta' : 'Concluída' }}</span>
            </div>
            <p class="m-0 text-sm text-fg">{{ phase.title }}</p>
            <p v-if="phase.ref" class="m-0 truncate font-mono text-xs text-fg-muted" :title="phase.ref">{{ fileName(phase.ref) }}</p>
            <div v-if="phase.done.length" class="text-xs">
              <p class="m-0 text-fg-muted">Feito</p>
              <ul class="m-0 pl-4 text-fg"><li v-for="(item, j) in phase.done" :key="j">{{ item }}</li></ul>
            </div>
            <div v-if="phase.pending.length" class="text-xs">
              <p class="m-0 text-fg-muted">Falta</p>
              <ul class="m-0 pl-4 text-fg"><li v-for="(item, j) in phase.pending" :key="j">{{ item }}</li></ul>
            </div>
          </li>
        </ol>
      </template>

      <p v-if="digest?.error || requestError" data-test="digest-error" role="alert" class="m-0 text-xs text-secondary-soft">{{ requestError ?? digest?.error }}</p>

      <div class="flex items-center justify-between gap-2">
        <span v-if="digest?.read_at" data-test="digest-read-at" class="text-xs text-fg-muted">Lido {{ formatActivity(digest.read_at) }}</span>
        <span v-else />
        <button
          type="button"
          data-test="digest-request"
          class="h-8 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="pending"
          @click="store.request(sessionId)"
        >{{ pending ? 'Resumindo…' : 'Resumir agora' }}</button>
      </div>
    </template>
  </section>
</template>
```

Nota: `formatActivity` devolve "agora" para menos de um minuto, então o rodapé fica "Lido agora"; nos outros casos, "Lido há 2 min", "Lido ontem" etc.

- [x] **Passo 4: Incluir no painel**

Em `DetailsPanel.vue`, importar `DigestSection` e colocar `<DigestSection :session-id="sessionId" />` entre a `<section data-test="details-properties">` e a `<section data-test="details-changes">`.

Nos testes de `DetailsPanel` que usam `routeFetch`, acrescente `'GET /api/sessions/s1/digest': () => jsonResponse(null)` (ou o id que o teste usa) para não cair na resposta 599.

- [x] **Passo 5: Rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/components/details`
Expected: PASS

- [x] **Passo 6: Suíte e compilação**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: PASS

- [x] **Passo 7: Roadmap**

Marcar `[x] Seção "Resumo" em Detalhes com fases, selo e "Resumir agora"` com a data e atualizar a contagem.

- [x] **Passo 8: Commit**

```bash
git add frontend/src/components/details ROADMAP.md
git commit -m "[UI] Mostrar resumo em fases no painel Detalhes"
```

---

### Tarefa 14: Frase curta e "Plano concluído" na linha de conversa

**Arquivos:**
- Modificar: `frontend/src/components/conversation/ConversationRow.vue`
- Testar: `frontend/src/components/conversation/__tests__/ConversationRow.spec.ts` (acrescentar)

**Interfaces:**
- Consome: `Session.digest_short`, `Session.plan_done`.
- Seletores: `[data-test="row-digest"]`, `[data-test="row-plan-done"]`.

- [x] **Passo 1: Escrever os testes que falham**

Acrescentar ao arquivo de testes da linha, usando o `mount` e o `makeSession` que ele já usa:

```ts
  it('mostra a frase curta do resumo depois do título', async () => {
    const w = mountRow(makeSession({ digest_short: 'Executa o plano do agrupador' }))
    await flushPromises()
    expect(w.find('[data-test="row-digest"]').text()).toBe('Executa o plano do agrupador')
  })

  it('sem resumo não mostra nada a mais', async () => {
    const w = mountRow(makeSession({ digest_short: null }))
    await flushPromises()
    expect(w.find('[data-test="row-digest"]').exists()).toBe(false)
    expect(w.find('[data-test="row-plan-done"]').exists()).toBe(false)
  })

  it('mostra "Plano concluído"', async () => {
    const w = mountRow(makeSession({ plan_done: true }))
    await flushPromises()
    expect(w.find('[data-test="row-plan-done"]').text()).toBe('Plano concluído')
  })
```

O arquivo já tem `mountRow(session, variant?)` e importa `makeSession` e `flushPromises`.

- [x] **Passo 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/conversation/__tests__/ConversationRow.spec.ts`
Expected: FAIL

- [x] **Passo 3: Implementar**

Em `ConversationRow.vue`, dentro de `<div data-test="row-title">`, depois de `<GroupTag ... />`:

```vue
      <span
        v-if="session.plan_done"
        data-test="row-plan-done"
        class="shrink-0 rounded border border-primary/40 px-1.5 font-mono text-[11px] text-primary-soft"
      >Plano concluído</span>
      <span
        v-if="session.digest_short"
        data-test="row-digest"
        class="min-w-0 truncate text-xs text-fg-muted"
      >{{ session.digest_short }}</span>
```

E no `RouterLink` do título, para a frase não espremer o título a zero, acrescentar à lista de classes dinâmicas: `session.digest_short ? 'max-w-[55%] shrink-0' : ''` (a classe `min-w-0 truncate` fica).

- [x] **Passo 4: Rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/components/conversation/__tests__/ConversationRow.spec.ts`
Expected: PASS

- [x] **Passo 5: Suíte e compilação**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: PASS

- [x] **Passo 6: Roadmap**

Marcar `[x] Frase curta do resumo na linha de conversa` com a data e atualizar a contagem.

- [x] **Passo 7: Commit**

```bash
git add frontend/src/components/conversation/ConversationRow.vue frontend/src/components/conversation/__tests__/ConversationRow.spec.ts ROADMAP.md
git commit -m "[UI] Mostrar frase do resumo na linha de conversa"
```

---

### Tarefa 15: Teste manual contra o SDK real e fechamento do marco

Esta tarefa é da sessão principal, não de subagente: consome a assinatura do usuário.

**Arquivos:**
- Criar: `scripts/digest_smoke.py`
- Modificar: `ROADMAP.md` (decisões e pontos em aberto, se houver achados)

- [x] **Passo 1: Escrever o roteiro**

```python
# scripts/digest_smoke.py
"""Teste manual do agente de resumos contra o SDK real. Consome a assinatura.

Segue o CLAUDE.md: modelo haiku, prompt mínimo, pasta temporária, setting_sources=[]
(o SdkDigestModel já usa), variáveis CLAUDE* removidas. Confere que a saída
estruturada volta com tools=[] e max_turns=3, e que a sessão do agente foi apagada.

Uso: uv run python scripts/digest_smoke.py
"""

import asyncio
import os
import tempfile
from pathlib import Path

for name in [n for n in os.environ if n.startswith("CLAUDE")]:
    del os.environ[name]

from vibing.config import claude_projects_dir  # noqa: E402
from vibing.digest.model import DigestRequest, SdkDigestModel  # noqa: E402
from vibing.digest.prompt import build_prompt, system_prompt  # noqa: E402


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vibing-digest-smoke-") as folder:
        before = set(claude_projects_dir().rglob("*.jsonl"))
        prompt = build_prompt(
            project="demo", title="Sessão de teste", digest=None, plan=None, specs=[],
            text="[Você] Crie a rota de saúde\n[Claude] Criei GET /api/health.\n[Edit] app.py",
            restarted=False,
        )
        model = SdkDigestModel(Path(folder))
        result = await model.summarize(
            DigestRequest(system_prompt(""), prompt, model="haiku", effort="low")
        )
        print("resultado:", result)
        leaked = set(claude_projects_dir().rglob("*.jsonl")) - before
        print("sessões deixadas para trás:", [str(p) for p in leaked] or "nenhuma")


if __name__ == "__main__":
    asyncio.run(main())
```

- [x] **Passo 2: Rodar**

Run: `uv run python scripts/digest_smoke.py`
Expected: um dicionário com `short`, `phases`, `plan_completed`, `plan_evidence`, e "sessões deixadas para trás: nenhuma".

Se a resposta não vier (por exemplo, erro de `max_turns`), anote a mensagem, ajuste `MAX_TURNS` em `backend/vibing/digest/model.py`, rode de novo e registre o ajuste em "Decisões" do `ROADMAP.md`. Se sobrar sessão, registre em "Pontos em aberto" e confira que o `HistoryIndex` não a mostra.

- [x] **Passo 3: Conferir o modelo padrão**

Com o backend rodando, `curl -s -H 'X-Vibing: 1' http://127.0.0.1:6660/api/models` e confira a descrição do alias `sonnet`. Se não for o Sonnet 5.5, avise o usuário antes de fechar o marco.

- [x] **Passo 4: Conferir no app**

Com backend e frontend rodando: abrir Preferências → "Agente de resumos", ligar com `haiku` e raciocínio baixo, clicar "Resumir agora" em Detalhes de uma conversa curta e ver a seção preencher, a frase aparecer na linha e a passada entrar no registro. Depois voltar a configuração ao padrão (desligado).

- [x] **Passo 5: Commit**

```bash
git add scripts/digest_smoke.py ROADMAP.md
git commit -m "[Test] Adicionar teste manual do agente de resumos contra o SDK"
```

- [x] **Passo 6: Revisão do marco**

Disparar o `milestone-reviewer` sobre o ramo inteiro. Depois da aprovação, trocar o estado do marco 10 para "Concluído" no `ROADMAP.md`, registrar a decisão com data e fazer o commit `[Docs] Concluir marco 10 do agente de resumos`.
