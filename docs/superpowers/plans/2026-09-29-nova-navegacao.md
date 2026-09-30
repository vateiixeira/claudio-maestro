# Nova navegação: plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para executar este plano tarefa a tarefa. Os passos usam caixas (`- [ ]`) para acompanhamento.

**Objetivo:** trocar a navegação em colunas por telas no estilo do Paperclip: Inbox, Conversas, página única da conversa com painel Detalhes, modal de nova conversa e Dashboard.

**Arquitetura:** o backend ganha quatro acréscimos pequenos (`finished_at`, `last_action`, `pending_kind`, marcar várias como lidas e atividade por dia). No frontend, o corpo da conversa sai do `SessionColumn` para um `ConversationThread` reaproveitável; telas novas usam uma linha de conversa comum (`ConversationRow`). As colunas convivem com as telas novas até a última tarefa, que troca `/` para `/inbox` e remove o código de colunas.

**Tecnologias:** Python 3.13, FastAPI, SQLite, pytest; Vue 3, Pinia, Vue Router, Tailwind CSS 4, Vitest, pnpm.

**Spec:** `docs/superpowers/specs/2026-09-29-nova-navegacao-design.md`

## Restrições globais

- Só começa depois de o marco 6 ser concluído e revisado (roadmap).
- Textos da interface em português brasileiro; código e identificadores em inglês.
- Não usar a marca "Claude Code" na interface.
- Frontend só com `pnpm` (`pnpm --dir frontend test`, `pnpm --dir frontend exec vitest run <arquivo>`). Nunca `npx` nem `yarn`.
- Testes escritos antes do código que cobrem. Testes nunca tocam o SDK real.
- Todo `git` passa por `run_git` em `backend/vibing/gitinfo.py`.
- Rotas novas em `/api/` seguem o middleware existente (Host, origem, `X-Vibing: 1`); nada de CORS.
- Identidade visual do Vibing: tokens de `frontend/src/style.css` (`bg`, `panel`, `card`, `elevated`, `line`, `line-strong`, `fg`, `fg-muted`, `primary*`, `secondary*`, `diff-*`) e o token novo `info` (`#60a5fa`).
- `localStorage` sempre dentro de try/catch; o app funciona sem ele.
- Subagentes não fazem commit nem `git add`. A sessão principal commita cada tarefa depois de o `reviewer` aprovar e os testes passarem, com mensagem `[Tipo] Título` em português.
- Ao concluir cada tarefa, marcar o item correspondente do marco 7 no `ROADMAP.md` com `[x]` e a data, e atualizar a contagem.

## Foco da revisão

Situações que a spec implica e que um uso real vai encontrar; cada uma tem teste na tarefa dona do código:

1. **Motivo da espera velho.** Um `session.state` que tira a sessão de `awaiting_decision` chega antes do `session.updated`; a linha não pode continuar dizendo "Pede permissão". Teste na Tarefa 3 (store `sessions`).
2. **Virada do dia.** Conversa às 23h50 e às 00h10, em fuso -03, cai em "Hoje"/"Ontem" certos, em "Finalizadas hoje" e no dia certo do gráfico. Testes nas Tarefas 2 (`message_days` com offset) e 3 (`dateGroup`).
3. **Duplo envio no modal.** Enter duas vezes rápido ou clique duplo em "Iniciar conversa" não pode criar duas sessões. Teste na Tarefa 9.
4. **Rascunho com projeto que sumiu.** O rascunho guardado aponta para um projeto removido ou indisponível; o modal cai no projeto padrão em vez de enviar para um id inválido. Teste na Tarefa 9.
5. **`localStorage` que lança erro.** Painel Detalhes e rascunho do modal continuam funcionando sem memória. Testes nas Tarefas 5 e 9.

---

## Mapa de arquivos

**Backend**

| Arquivo | Mudança |
|---|---|
| `backend/vibing/db.py` | Migração 4: coluna `finished_at` |
| `backend/vibing/sessions.py` | `finished_at` no registro, `last_action` e `pending_kind` no resumo, `mark_seen_many` |
| `backend/vibing/activity.py` (novo) | Leitura de atividade por dia e projeto, com cache |
| `backend/vibing/history.py` | Função pública `sdk_session_file` |
| `backend/vibing/api/sessions.py` | Campos novos em `SessionOut`, rota `POST /api/sessions/seen` |
| `backend/vibing/api/activity.py` (novo) | Rota `GET /api/activity` |
| `backend/vibing/api/__init__.py`, `backend/vibing/app.py` | Registro da rota e do leitor de atividade |
| `backend/tests/conftest.py` | Neutraliza `sdk_session_file` |
| `backend/tests/test_navigation_summary.py` (novo) | Testes da Tarefa 1 |
| `backend/tests/test_navigation_api.py` (novo) | Testes da Tarefa 2 |

**Frontend**

| Arquivo | Responsabilidade |
|---|---|
| `src/style.css` | Token `--color-info` |
| `src/types/api.ts`, `src/api/http.ts` | Campos e chamadas novas |
| `src/conversationList.ts` (novo) | Motivo da espera, abas da Inbox, grupos por data |
| `src/components/conversation/ConversationRow.vue` (novo) | Linha de conversa |
| `src/components/conversation/ConversationThread.vue` (novo) | Corpo da conversa extraído do `SessionColumn` |
| `src/conversation/sessionChanges.ts` (novo) | Carga da lista de alterações de uma sessão |
| `src/components/details/ChangesList.vue`, `FileDiffView.vue`, `DetailsPanel.vue` (novos) | Painel Detalhes |
| `src/components/conversation/ConversationHeader.vue` (novo) | Cabeçalho da página da conversa |
| `src/views/ConversationView.vue` (novo) | Página `/sessions/:id` |
| `src/components/sidebar/AppSidebar.vue` | Menu novo |
| `src/App.vue` | Moldura: menu, conteúdo, modal, título da aba, atalho `C` |
| `src/views/InboxView.vue`, `src/views/ConversationsView.vue` (novos) | Inbox e Conversas |
| `src/components/FirstSteps.vue` (novo, a partir de `HomeView`) | Primeiros passos sem projetos |
| `src/stores/newConversation.ts`, `src/conversation/pendingDrafts.ts`, `src/sessionOptions.ts` (novos) | Modal de nova conversa |
| `src/components/NewConversationModal.vue` (novo) | Modal |
| `src/conversation/pendingDecision.ts` (novo) | Permitir/Negar fora da conversa |
| `src/views/DashboardView.vue`, `src/components/dashboard/ActivityChart.vue` (novos) | Dashboard |
| `src/views/ProjectView.vue` | Lista com `ConversationRow`, "Nova sessão" abre o modal |
| `src/router/index.ts` | Rotas novas; `/` para `/inbox` na Tarefa 12 |
| Removidos na Tarefa 12 | `WorkspaceView`, `AllSessionsView`, `HomeView`, `SessionColumn`, `ColumnResizer`, `SessionGroup`, `SessionRow`, `ChangesPanel`, parte de colunas do store `layout` e os testes deles |

---

### Tarefa 1: Resumo da sessão com `finished_at`, `last_action` e `pending_kind`

**Arquivos:**
- Modificar: `backend/vibing/db.py` (lista `MIGRATIONS`)
- Modificar: `backend/vibing/sessions.py` (`SessionRecord`, `_COLUMNS`, `describe`, `ActiveSession.__init__`, `pending_permission`, `summary`, `_read`, `_can_use_tool`, `_emit_pending_change`, `resolve_prompt`, `_cancel_prompts`, `SessionManager._extras`, `SessionManager.update`)
- Modificar: `backend/vibing/api/sessions.py` (`SessionOut`)
- Criar: `backend/tests/test_navigation_summary.py`

**Interfaces:**
- Produz: campos `finished_at: int | None`, `last_action: str | None`, `pending_kind: "tool" | "question" | "plan" | None` em todo resumo de sessão (listagens, PATCH, `session.updated`).
- Produz: `sessions.last_action_text(name: str, tool_input: dict[str, Any]) -> str`.

- [x] **Passo 1: escrever os testes que falham**

Criar `backend/tests/test_navigation_summary.py`:

```python
"""Marco 7: fields of the session summary used by the new navigation."""

from contextlib import closing

import pytest
from claude_agent_sdk import ToolUseBlock

from test_sessions import by_session, env_cleanup, make_env, session_row, wait_until  # noqa: F401
from vibing import db
from vibing.agent.fake import response_messages, text_turn, tool_turn
from vibing.sessions import last_action_text


# last_action_text -----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "tool_input", "expected"),
    [
        ("Edit", {"file_path": "/home/vi/app/backend/sessions.py"}, "Edit sessions.py"),
        ("Read", {"file_path": "/home/vi/app/ROADMAP.md"}, "Read ROADMAP.md"),
        ("Write", {"file_path": "/tmp/a.txt"}, "Write a.txt"),
        ("MultiEdit", {"file_path": "/tmp/b.py"}, "MultiEdit b.py"),
        ("NotebookEdit", {"notebook_path": "/tmp/n.ipynb"}, "NotebookEdit n.ipynb"),
        ("Bash", {"command": "pnpm   test\n--run"}, "Bash: pnpm test --run"),
        ("Grep", {"pattern": "def main"}, "Grep: def main"),
        ("Glob", {"pattern": "**/*.vue"}, "Glob: **/*.vue"),
        ("Agent", {"description": "Revisar a tarefa"}, "Agent: Revisar a tarefa"),
        ("Task", {"description": "Explorar"}, "Task: Explorar"),
        ("WebFetch", {"url": "https://x"}, "WebFetch"),
        ("Edit", {}, "Edit"),
        ("Bash", {"command": "   "}, "Bash"),
    ],
)
def test_last_action_text(name, tool_input, expected):
    assert last_action_text(name, tool_input) == expected


def test_last_action_text_is_cut_at_80_characters():
    text = last_action_text("Bash", {"command": "x" * 200})
    assert len(text) == 80
    assert text.endswith("…")


# finished_at ----------------------------------------------------------------


def test_migration_adds_finished_at(tmp_path):
    path = tmp_path / "vibing.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert "finished_at" in columns


@pytest.mark.anyio
async def test_finish_sets_and_reopen_clears_finished_at(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    sid = session.session_id

    finished = await env.manager.update(sid, finished=True)
    assert isinstance(finished["finished_at"], int)
    assert session_row(env.db_path, sid)["finished_at"] == finished["finished_at"]

    reopened = await env.manager.update(sid, finished=False)
    assert reopened["finished_at"] is None
    assert session_row(env.db_path, sid)["finished_at"] is None


@pytest.mark.anyio
async def test_new_session_has_no_finished_at(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    assert session.summary()["finished_at"] is None
    listed = env.manager.list_sessions()
    assert listed[0]["finished_at"] is None


# last_action ------------------------------------------------------------------


@pytest.mark.anyio
async def test_last_action_follows_main_tool_use_and_is_emitted(make_env, env_cleanup):
    script, ids = by_session(
        lambda sid: tool_turn(sid, tool_name="Edit", tool_input={"file_path": "/p/app/main.py"}),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    assert session.summary()["last_action"] is None
    await session.send("edite")
    await wait_until(lambda: session.state == "idle")

    assert session.summary()["last_action"] == "Edit main.py"
    updates = env.recorder.of(session.session_id, "session.updated")
    assert any(u["data"]["last_action"] == "Edit main.py" for u in updates)


@pytest.mark.anyio
async def test_subagent_tool_use_does_not_change_last_action(make_env, env_cleanup):
    def turn(sid):
        steps = text_turn(sid, "ok")
        sub = response_messages(
            sid,
            [ToolUseBlock(id="toolu_sub", name="Bash", input={"command": "ls"})],
            parent_tool_use_id="toolu_parent",
            stop_reason="tool_use",
        )
        # Before the final result message.
        return [*steps[:-1], *sub, steps[-1]]

    script, ids = by_session(turn)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    assert session.summary()["last_action"] is None


# pending_kind -----------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "tool_input", "kind"),
    [
        ("Bash", {"command": "ls"}, "tool"),
        ("AskUserQuestion", {"questions": []}, "question"),
        ("ExitPlanMode", {"plan": "passos"}, "plan"),
    ],
)
async def test_pending_kind_follows_the_oldest_prompt(make_env, env_cleanup, tool_name, tool_input, kind):
    script, ids = by_session(
        lambda sid: tool_turn(sid, tool_name=tool_name, tool_input=tool_input, ask_permission=True),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("vai")
    await wait_until(lambda: session.state == "awaiting_decision")

    assert session.summary()["pending_kind"] == kind
    updates = env.recorder.of(session.session_id, "session.updated")
    assert updates[-1]["data"]["pending_kind"] == kind

    [prompt] = session.snapshot()["prompts"]
    decision = {"tool": "allow_once", "question": "deny", "plan": "approve"}[kind]
    session.resolve_prompt(prompt["prompt_id"], decision)
    await wait_until(lambda: session.state == "idle")

    assert session.summary()["pending_kind"] is None
    updates = env.recorder.of(session.session_id, "session.updated")
    assert any(u["data"]["pending_kind"] is None for u in updates[-3:])


@pytest.mark.anyio
async def test_listing_of_closed_session_has_null_extras(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    env.new_session()
    [item] = env.manager.list_sessions()
    assert item["last_action"] is None
    assert item["pending_kind"] is None
```

Acrescentar ao fim de `backend/tests/test_multisession_api.py`:

```python
def test_session_out_has_navigation_fields(api, home):
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]

    finished = api.patch(f"/api/sessions/{sid}", json={"finished": True}).json()
    listed = api.get("/api/sessions").json()[0]

    assert isinstance(finished["finished_at"], int)
    assert listed["finished_at"] == finished["finished_at"]
    assert listed["last_action"] is None
    assert listed["pending_kind"] is None
```

- [x] **Passo 2: rodar e ver falhar**

Run: `uv run pytest backend/tests/test_navigation_summary.py backend/tests/test_multisession_api.py::test_session_out_has_navigation_fields -q`
Expected: FAIL (`ImportError: cannot import name 'last_action_text'` e `KeyError: 'finished_at'`).

- [x] **Passo 3: migração**

Em `backend/vibing/db.py`, acrescentar ao fim de `MIGRATIONS` (depois da migração 3):

```python
    [
        # Marco 7: when the session was finished by the user (None when open or
        # finished by inactivity). Feeds "Finalizadas hoje" in the dashboard.
        "ALTER TABLE sessions ADD COLUMN finished_at INTEGER",
    ],
```

- [x] **Passo 4: registro, colunas e texto da última ação**

Em `backend/vibing/sessions.py`:

1. Nos imports do SDK, acrescentar `AssistantMessage` e `ToolUseBlock` à lista `from claude_agent_sdk import (...)`.
2. Em `SessionRecord`, depois de `permission_mode`, acrescentar:

```python
    # When the user finished the session (seconds); None when open or finished by inactivity.
    finished_at: int | None = None
```

3. Trocar `_COLUMNS` por:

```python
_COLUMNS = (
    _INSERT_COLUMNS
    + ", summary, first_prompt, title_custom, rename_pending, file_modified_at, app_modified_at"
    + ", model, effort, permission_mode, finished_at"
)
```

4. Logo abaixo de `TITLE_MAX_LENGTH = 80`, acrescentar:

```python
LAST_ACTION_MAX = 80
_FILE_TOOLS = frozenset({"Read", "Edit", "MultiEdit", "Write", "NotebookEdit"})
# Tools shown as "Name: argument", with the input key holding the argument.
_ARGUMENT_KEYS = {"Bash": "command", "Grep": "pattern", "Glob": "pattern",
                  "Agent": "description", "Task": "description"}


def last_action_text(name: str, tool_input: dict[str, Any]) -> str:
    """One short line for the dashboard: `Edit sessions.py`, `Bash: pnpm test`."""
    text = name
    if name in _FILE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if isinstance(path, str) and path.strip():
            text = f"{name} {Path(path).name}"
    elif name in _ARGUMENT_KEYS:
        value = tool_input.get(_ARGUMENT_KEYS[name])
        if isinstance(value, str) and value.strip():
            text = f"{name}: {value}"
    text = " ".join(text.split())
    if len(text) > LAST_ACTION_MAX:
        text = text[: LAST_ACTION_MAX - 1] + "…"
    return text
```

- [x] **Passo 5: `describe` com os campos novos**

Em `describe(...)`, acrescentar os parâmetros depois de `pending_permission`:

```python
    last_action: str | None = None,
    pending_kind: str | None = None,
```

e no dicionário devolvido, depois de `"pending_permission": pending_permission,`:

```python
        "last_action": last_action,
        "pending_kind": pending_kind,
```

(`finished_at` já entra pelo `asdict(record)`.)

- [x] **Passo 6: `ActiveSession` guarda a última ação e o tipo do pedido**

1. Em `ActiveSession.__init__`, depois de `self.model_resolved: str | None = None`:

```python
        # Last tool used by the main conversation, for the dashboard; memory only.
        self.last_action: str | None = None
```

2. Depois da propriedade `pending_permission`, acrescentar:

```python
    @property
    def pending_kind(self) -> str | None:
        """Kind of the oldest pending prompt: tool, question or plan."""
        for prompt in self.prompts.values():
            return prompt.kind
        return None

    def _pending_view(self) -> tuple[dict[str, Any] | None, str | None]:
        return (self.pending_permission, self.pending_kind)
```

3. Trocar `_emit_pending_change` por:

```python
    def _emit_pending_change(self, before: tuple[dict[str, Any] | None, str | None]) -> None:
        """Update the summary when the pending permission or prompt kind it shows changed."""
        if self._pending_view() != before:
            self.emit_updated()
```

4. Em `_can_use_tool` (duas vezes), `resolve_prompt` e `_cancel_prompts`, trocar cada `before = self.pending_permission` por `before = self._pending_view()`.

5. Em `ActiveSession.summary`, acrescentar à chamada de `describe`:

```python
            last_action=self.last_action,
            pending_kind=self.pending_kind,
```

6. Em `_read`, logo depois de `self._emit_events(self.builder.handle(message))`:

```python
                if isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
                    self._note_tool_use(message)
```

e acrescentar o método (perto de `_touch`):

```python
    def _note_tool_use(self, message: AssistantMessage) -> None:
        """Keep the last tool of the main conversation and publish it when it changes."""
        uses = [block for block in message.content if isinstance(block, ToolUseBlock)]
        if not uses:
            return
        action = last_action_text(uses[-1].name, uses[-1].input or {})
        if action != self.last_action:
            self.last_action = action
            self.emit_updated()
```

- [x] **Passo 7: o manager passa os campos e grava `finished_at`**

1. Trocar `SessionManager._extras` por:

```python
    @staticmethod
    def _extras(active: ActiveSession | None = None) -> dict[str, Any]:
        """In-memory fields of a session (context, pending prompt, last action), for `describe`."""
        if active is None:
            return {"context": None, "pending_permission": None,
                    "last_action": None, "pending_kind": None}
        return {
            "context": active.context,
            "pending_permission": active.pending_permission,
            "last_action": active.last_action,
            "pending_kind": active.pending_kind,
        }
```

(Manter o decorador que já existe na linha acima de `_extras`; se já for `@staticmethod`, não duplicar.)

2. Em `update(...)`, logo antes de `if not changes:`, acrescentar:

```python
        if "finished" in changes:
            changes["finished_at"] = _now() if changes["finished"] else None
```

- [x] **Passo 8: `SessionOut` com os campos novos**

Em `backend/vibing/api/sessions.py`, no fim de `SessionOut`:

```python
    # When the user finished the session; None when open or finished by inactivity.
    finished_at: int | None = None
    # Last tool of the main conversation ("Edit sessions.py"); None after a restart.
    last_action: str | None = None
    # Kind of the oldest pending prompt.
    pending_kind: Literal["tool", "question", "plan"] | None = None
```

- [x] **Passo 9: rodar e ver passar**

Run: `uv run pytest backend/tests/test_navigation_summary.py backend/tests/test_multisession_api.py -q`
Expected: PASS.

Run: `uv run pytest -q`
Expected: toda a suíte passa. Se `test_db.py` comparar o número de migrações com um valor fixo, ele já usa `db.SCHEMA_VERSION` e continua passando.

- [x] **Passo 10: commit (sessão principal, depois do reviewer)**

```bash
git add backend/vibing/db.py backend/vibing/sessions.py backend/vibing/api/sessions.py backend/tests/test_navigation_summary.py backend/tests/test_multisession_api.py
git commit -m "[Feat] Incluir última ação, tipo do pedido e data de finalização na sessão"
```

---

### Tarefa 2: Rotas de marcar várias como lidas e de atividade por dia

**Arquivos:**
- Modificar: `backend/vibing/sessions.py` (`SessionManager.mark_seen_many`)
- Modificar: `backend/vibing/api/sessions.py` (`SeenManyIn`, rota)
- Modificar: `backend/vibing/history.py` (`sdk_session_file`)
- Criar: `backend/vibing/activity.py`
- Criar: `backend/vibing/api/activity.py`
- Modificar: `backend/vibing/api/__init__.py`, `backend/vibing/app.py`
- Modificar: `backend/tests/conftest.py`
- Criar: `backend/tests/test_navigation_api.py`

**Interfaces:**
- Consome: `SessionManager.mark_seen(session_id)` (existente).
- Produz: `POST /api/sessions/seen` com `{"session_ids": [str]}` (até 500) → `{"updated": int}`.
- Produz: `GET /api/activity?days=14` (1 a 31) → `[{"date": "AAAA-MM-DD", "project_id": int, "sessions": int}]`, ordenado por data e projeto.
- Produz: `activity.message_days(path: Path) -> frozenset[date]`, `activity.ActivityReader(db_path, session_file=None, clock=time.time).read(days: int)`.
- Produz: `create_app(..., session_file=...)` para testes.

- [x] **Passo 1: escrever os testes que falham**

Criar `backend/tests/test_navigation_api.py`:

```python
"""Marco 7: mark many sessions as seen, and activity per day and project."""

import json
import os
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_multisession_api import new_session
from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project, receive
from vibing.activity import ActivityReader, message_days
from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app
from vibing.config import Settings
from vibing import db


def local(y, m, d, hh=12, mm=0) -> str:
    """ISO timestamp with the machine's own offset."""
    return datetime(y, m, d, hh, mm).astimezone().isoformat()


def write_transcript(path: Path, stamps: list[str], kind: str = "user") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": kind, "uuid": f"u{i}", "timestamp": s}) for i, s in enumerate(stamps)]
    path.write_text("\n".join(lines) + "\n")


class Files:
    """Fake `session_file`: session id -> path."""

    def __init__(self) -> None:
        self.paths: dict[str, Path] = {}
        self.calls = 0

    def __call__(self, session_id: str, directory: str) -> Path | None:
        self.calls += 1
        return self.paths.get(session_id)


@pytest.fixture
def files() -> Files:
    return Files()


@pytest.fixture
def api(files, home, data_dir):
    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir),
        agent_factory=FakeAgentFactory(),
        history_exists=lambda session_id, cwd: False,
        session_file=files,
    )
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as c:
        yield c


# message_days -----------------------------------------------------------------


def test_message_days_reads_local_dates_of_user_and_assistant_lines(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"type": "user", "timestamp": local(2026, 9, 28, 23, 50)}),
            json.dumps({"type": "assistant", "timestamp": local(2026, 9, 29, 0, 10)}),
            json.dumps({"type": "summary", "timestamp": local(2026, 9, 20)}),
            "não é json",
            json.dumps({"type": "user", "timestamp": "sem data"}),
            json.dumps({"type": "user"}),
        ]) + "\n"
    )
    assert message_days(path) == frozenset({date(2026, 9, 28), date(2026, 9, 29)})


def test_message_days_converts_utc_to_local_day(tmp_path):
    # 02:00 UTC on the 29th is still the 28th in UTC-3, and the 29th in UTC+2.
    moment = datetime(2026, 9, 29, 2, 0).astimezone()  # local wall clock
    utc = moment.astimezone(timezone.utc)
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps({"type": "user", "timestamp": utc.isoformat().replace("+00:00", "Z")}) + "\n")
    assert message_days(path) == frozenset({moment.date()})


# ActivityReader -------------------------------------------------------------------


def insert_session(db_path: Path, project_id: int, sid: str, last_activity: float) -> None:
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
            " last_activity_at, last_seen_at, finished) VALUES (?, ?, '/p', 't', 0, ?, 0, 0)",
            (sid, project_id, int(last_activity)),
        )


def insert_project(db_path: Path, pid: int) -> None:
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (?, ?, ?, '#fff', 0, 0)",
            (pid, f"p{pid}", f"/p{pid}"),
        )


def test_reader_counts_sessions_per_day_and_project(tmp_path, files):
    db_path = tmp_path / "vibing.db"
    db.init_db(db_path)
    insert_project(db_path, 1)
    insert_project(db_path, 2)
    now = datetime(2026, 9, 29, 15, 0).timestamp()
    for sid, pid, stamps in [
        ("a", 1, [local(2026, 9, 29), local(2026, 9, 28)]),
        ("b", 1, [local(2026, 9, 29, 9)]),
        ("c", 2, [local(2026, 9, 27)]),
        ("old", 2, [local(2026, 9, 1)]),  # outside 14 days
    ]:
        path = tmp_path / "h" / f"{sid}.jsonl"
        write_transcript(path, stamps)
        files.paths[sid] = path
        insert_session(db_path, pid, sid, now)

    reader = ActivityReader(db_path, session_file=files, clock=lambda: now)

    assert reader.read(14) == [
        {"date": "2026-09-27", "project_id": 2, "sessions": 1},
        {"date": "2026-09-28", "project_id": 1, "sessions": 1},
        {"date": "2026-09-29", "project_id": 1, "sessions": 2},
    ]


def test_reader_skips_sessions_without_recent_activity_and_missing_files(tmp_path, files):
    db_path = tmp_path / "vibing.db"
    db.init_db(db_path)
    insert_project(db_path, 1)
    now = datetime(2026, 9, 29, 15, 0).timestamp()
    stale = tmp_path / "h" / "stale.jsonl"
    write_transcript(stale, [local(2026, 9, 29)])
    files.paths["stale"] = stale
    insert_session(db_path, 1, "stale", now - 40 * 86400)  # last activity long ago
    insert_session(db_path, 1, "nofile", now)

    reader = ActivityReader(db_path, session_file=files, clock=lambda: now)

    assert reader.read(14) == []
    assert files.calls == 1  # only "nofile" was looked up


def test_reader_caches_by_modification_time(tmp_path, files, monkeypatch):
    db_path = tmp_path / "vibing.db"
    db.init_db(db_path)
    insert_project(db_path, 1)
    now = datetime(2026, 9, 29, 15, 0).timestamp()
    path = tmp_path / "h" / "a.jsonl"
    write_transcript(path, [local(2026, 9, 29)])
    os.utime(path, (now, now))
    files.paths["a"] = path
    insert_session(db_path, 1, "a", now)
    reads = []
    import vibing.activity as activity_module
    original = activity_module.message_days
    monkeypatch.setattr(activity_module, "message_days", lambda p: reads.append(p) or original(p))
    reader = ActivityReader(db_path, session_file=files, clock=lambda: now)

    reader.read(14)
    reader.read(14)
    assert len(reads) == 1

    write_transcript(path, [local(2026, 9, 28)])
    os.utime(path, (now + 5, now + 5))
    assert reader.read(14) == [{"date": "2026-09-28", "project_id": 1, "sessions": 1}]
    assert len(reads) == 2


# Routes ---------------------------------------------------------------------------


def test_activity_route_limits_days(api):
    assert api.get("/api/activity?days=0").status_code == 422
    assert api.get("/api/activity?days=32").status_code == 422
    assert api.get("/api/activity").json() == []


def test_activity_route_reads_registered_sessions(api, home, files, tmp_path):
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]
    path = tmp_path / "h" / f"{sid}.jsonl"
    write_transcript(path, [datetime.now().astimezone().isoformat()])
    files.paths[sid] = path

    body = api.get("/api/activity?days=1").json()

    assert body == [{"date": date.today().isoformat(), "project_id": project["id"], "sessions": 1}]


def test_seen_many_marks_known_sessions_and_ignores_unknown(api, home):
    project = make_project(api, home)
    a = new_session(api, project)["session_id"]
    b = new_session(api, project)["session_id"]

    with api.websocket_connect("ws://127.0.0.1:6660/ws", headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as ws:
        response = api.post("/api/sessions/seen", json={"session_ids": [a, "desconhecida", b, a]})
        events = [receive(ws), receive(ws)]

    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    assert sorted(e["session_id"] for e in events) == sorted([a, b])
    assert all(e["type"] == "session.updated" for e in events)


def test_seen_many_refuses_more_than_500_ids(api):
    response = api.post("/api/sessions/seen", json={"session_ids": [f"s{i}" for i in range(501)]})
    assert response.status_code == 422


def test_seen_many_requires_the_vibing_header(home, data_dir):
    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), agent_factory=FakeAgentFactory())
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN}) as c:
        assert c.post("/api/sessions/seen", json={"session_ids": []}).status_code in (400, 403)
```

- [x] **Passo 2: rodar e ver falhar**

Run: `uv run pytest backend/tests/test_navigation_api.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'vibing.activity'`).

- [x] **Passo 3: `sdk_session_file` e conftest**

Em `backend/vibing/history.py`, logo depois de `_session_file`:

```python
def sdk_session_file(session_id: str, directory: str) -> Path | None:
    """Path of the session's `.jsonl`, resolved as the SDK reads it (None if unknown)."""
    return _session_file(session_id, directory)
```

Em `backend/tests/conftest.py`, dentro de `no_real_sdk_history`, junto dos outros `monkeypatch.setattr`:

```python
    monkeypatch.setattr("vibing.history.sdk_session_file", lambda session_id, directory: None)
```

- [x] **Passo 4: leitor de atividade**

Criar `backend/vibing/activity.py`:

```python
"""Conversations with messages per day and project, read from the CLI history files.

Only sessions of registered projects with activity inside the period are looked
at, and a file is only read again when its modification time changes.
"""

import json
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from vibing import db
from vibing import history

logger = logging.getLogger(__name__)

SessionFile = Callable[[str, str], Path | None]
_MESSAGE_TYPES = frozenset({"user", "assistant"})


def message_days(path: Path) -> frozenset[date]:
    """Local dates of the user and assistant lines of a `.jsonl` history file."""
    days: set[date] = set()
    with path.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            if '"timestamp"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") not in _MESSAGE_TYPES:
                continue
            stamp = entry.get("timestamp")
            if not isinstance(stamp, str):
                continue
            try:
                moment = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            days.add(moment.astimezone().date())
    return frozenset(days)


class ActivityReader:
    def __init__(
        self,
        db_path: Path,
        session_file: SessionFile | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._session_file = session_file
        self._clock = clock
        self._cache: dict[Path, tuple[float, frozenset[date]]] = {}
        self._lock = threading.Lock()

    def _find(self, session_id: str, cwd: str) -> Path | None:
        finder = self._session_file or history.sdk_session_file
        try:
            return finder(session_id, cwd)
        except Exception:
            logger.exception("Falha ao localizar o histórico da sessão %s", session_id)
            return None

    def read(self, days: int) -> list[dict[str, Any]]:
        """`[{date, project_id, sessions}]` for the last `days` days, today included."""
        today = date.fromtimestamp(self._clock())
        first = today - timedelta(days=days - 1)
        since = datetime.combine(first, datetime.min.time()).timestamp()
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT session_id, project_id, cwd FROM sessions WHERE last_activity_at >= ?",
                (int(since),),
            ).fetchall()
        counts: Counter[tuple[date, int]] = Counter()
        with self._lock:
            used: set[Path] = set()
            for row in rows:
                path = self._find(row["session_id"], row["cwd"])
                if path is None:
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime < since:
                    continue
                used.add(path)
                cached = self._cache.get(path)
                if cached is None or cached[0] != mtime:
                    try:
                        cached = (mtime, message_days(path))
                    except OSError:
                        continue
                    self._cache[path] = cached
                for day in cached[1]:
                    if first <= day <= today:
                        counts[(day, row["project_id"])] += 1
            for path in list(self._cache):
                if path not in used:
                    del self._cache[path]
        return [
            {"date": day.isoformat(), "project_id": project_id, "sessions": n}
            for (day, project_id), n in sorted(counts.items())
        ]
```

- [x] **Passo 5: rota de atividade e registro**

Criar `backend/vibing/api/activity.py`:

```python
"""Activity per day and project, for the dashboard chart."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api")


@router.get("/activity")
async def get_activity(
    request: Request, days: Annotated[int, Query(ge=1, le=31)] = 14
) -> list[dict[str, Any]]:
    # Reads files: off the event loop.
    return await asyncio.to_thread(request.app.state.activity.read, days)
```

Em `backend/vibing/api/__init__.py`, importar `activity` e acrescentar `router.include_router(activity.router)`.

Em `backend/vibing/app.py`:
1. Importar `from vibing.activity import ActivityReader, SessionFile`.
2. Acrescentar o parâmetro `session_file: SessionFile | None = None,` em `create_app`, depois de `refresh_models`.
3. No `lifespan`, depois de criar `app.state.sessions`:

```python
        app.state.activity = ActivityReader(app.state.settings.db_path, session_file)
```

- [x] **Passo 6: marcar várias como lidas**

Em `backend/vibing/sessions.py`, depois de `mark_seen`:

```python
    async def mark_seen_many(self, session_ids: list[str]) -> int:
        """Mark each known session as seen (one `session.updated` each); unknown ids are skipped."""
        updated = 0
        for session_id in dict.fromkeys(session_ids):
            try:
                await self.mark_seen(session_id)
            except SessionNotFoundError:
                continue
            updated += 1
        return updated
```

Em `backend/vibing/api/sessions.py`:
1. Importar `Field` de `pydantic`.
2. Depois de `SessionPatch`:

```python
class SeenManyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_ids: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=100)]],
        Field(max_length=500),
    ]
```

3. Antes da rota `@router.post("/sessions/{session_id}/seen", ...)`:

```python
@router.post("/sessions/seen")
async def mark_many_seen(body: SeenManyIn, manager: ManagerDep) -> dict[str, int]:
    return {"updated": await manager.mark_seen_many(body.session_ids)}
```

- [x] **Passo 7: rodar e ver passar**

Run: `uv run pytest backend/tests/test_navigation_api.py -q`
Expected: PASS. Se `test_seen_many_requires_the_vibing_header` receber outro código, conferir em `backend/vibing/security.py` qual status o middleware usa e ajustar a asserção para esse valor exato.

Run: `uv run pytest -q`
Expected: toda a suíte passa.

- [x] **Passo 8: commit**

```bash
git add backend/vibing/sessions.py backend/vibing/api/sessions.py backend/vibing/history.py backend/vibing/activity.py backend/vibing/api/activity.py backend/vibing/api/__init__.py backend/vibing/app.py backend/tests/conftest.py backend/tests/test_navigation_api.py
git commit -m "[Feat] Adicionar rotas de marcar lidas em lote e de atividade por dia"
```

---

### Tarefa 3: Linha de conversa e regras de lista

**Arquivos:**
- Modificar: `frontend/src/style.css` (token `--color-info`)
- Modificar: `frontend/src/types/api.ts` (`Session`, `ActivityDay`)
- Modificar: `frontend/src/api/http.ts` (`markSessionsSeen`, `getActivity`)
- Modificar: `frontend/src/stores/sessions.ts` (limpar pendência velha em `session.state`)
- Criar: `frontend/src/conversationList.ts`
- Criar: `frontend/src/components/conversation/ConversationRow.vue`
- Testes: `frontend/src/__tests__/conversationList.spec.ts`, `frontend/src/components/conversation/__tests__/ConversationRow.spec.ts`, acréscimo em `frontend/src/stores/__tests__/sessions.spec.ts`

**Interfaces:**
- Produz (tipos): `Session.finished_at?: number | null`, `Session.last_action?: string | null`, `Session.pending_kind?: 'tool' | 'question' | 'plan' | null`; `interface ActivityDay { date: string; project_id: number; sessions: number }`.
- Produz (http): `markSessionsSeen(ids: string[]): Promise<{ updated: number }>`, `getActivity(days = 14): Promise<ActivityDay[]>`.
- Produz (`conversationList.ts`): `waitingReason(s: Session): string | null`, `type InboxTab = 'pede-voce' | 'nao-lidas' | 'em-execucao' | 'todas'`, `INBOX_TABS`, `isInboxTab(v: unknown): v is InboxTab`, `inInbox(s: Session, tab: InboxTab): boolean`, `type DateLabel = 'Hoje' | 'Ontem' | 'Esta semana' | 'Antes'`, `dateLabel(seconds: number, now: Date, withWeek: boolean): DateLabel`, `groupByDate(list: Session[], now: Date, withWeek: boolean): { label: DateLabel; sessions: Session[] }[]`.
- Produz: `ConversationRow.vue` com props `{ session: Session; variant?: 'inbox' | 'list' | 'compact' }` (padrão `'list'`), evento `error: [message: string]`; `data-test`: `conversation-row`, `row-link`, `unread-dot`, `waiting-reason`, `row-project`, `row-branch`, `row-finish`, `row-reopen`, `row-mark-read`.

- [x] **Passo 1: testes das regras (falham)**

Criar `frontend/src/__tests__/conversationList.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { dateLabel, groupByDate, inInbox, isInboxTab, waitingReason } from '../conversationList'
import { makeSession } from '../test/factories'

const at = (y: number, m: number, d: number, hh = 12, mm = 0) => new Date(y, m - 1, d, hh, mm).getTime() / 1000

describe('motivo da espera', () => {
  it('só existe para quem aguarda o usuário', () => {
    expect(waitingReason(makeSession({ display_state: 'running' }))).toBeNull()
    expect(waitingReason(makeSession({ display_state: 'finished' }))).toBeNull()
  })

  it('mostra erro, permissão, pergunta, plano ou sua vez', () => {
    expect(waitingReason(makeSession({ display_state: 'waiting', state: 'error' }))).toBe('Parou com erro')
    expect(waitingReason(makeSession({
      display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'tool',
      pending_permission: { prompt_id: 'p', tool_name: 'Bash', summary: 'ls', can_allow_always: false },
    }))).toBe('Pede permissão: Bash')
    expect(waitingReason(makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question' }))).toBe('Fez uma pergunta')
    expect(waitingReason(makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'plan' }))).toBe('Plano para aprovar')
    expect(waitingReason(makeSession({ display_state: 'waiting', state: 'idle' }))).toBe('Sua vez')
  })
})

describe('abas da Inbox', () => {
  const waiting = makeSession({ session_id: 'w', display_state: 'waiting' })
  const running = makeSession({ session_id: 'r', display_state: 'running' })
  const unreadOpen = makeSession({ session_id: 'u', display_state: 'running', unread: true })
  const finishedUnread = makeSession({ session_id: 'fu', display_state: 'finished', unread: true })
  const finishedRead = makeSession({ session_id: 'f', display_state: 'finished' })
  const all = [waiting, running, unreadOpen, finishedUnread, finishedRead]
  const ids = (tab: Parameters<typeof inInbox>[1]) => all.filter((s) => inInbox(s, tab)).map((s) => s.session_id)

  it('separa por aba e nunca mostra finalizadas', () => {
    expect(ids('pede-voce')).toEqual(['w'])
    expect(ids('nao-lidas')).toEqual(['u'])
    expect(ids('em-execucao')).toEqual(['r', 'u'])
    expect(ids('todas')).toEqual(['w', 'r', 'u'])
  })

  it('reconhece as abas válidas', () => {
    expect(isInboxTab('nao-lidas')).toBe(true)
    expect(isInboxTab('outra')).toBe(false)
    expect(isInboxTab(undefined)).toBe(false)
  })
})

describe('grupos por data', () => {
  const now = new Date(2026, 8, 29, 0, 20)

  it('usa o dia local, inclusive perto da meia-noite', () => {
    expect(dateLabel(at(2026, 9, 29, 0, 10), now, false)).toBe('Hoje')
    expect(dateLabel(at(2026, 9, 28, 23, 50), now, false)).toBe('Ontem')
    expect(dateLabel(at(2026, 9, 27), now, false)).toBe('Antes')
  })

  it('tem "Esta semana" só quando pedido', () => {
    expect(dateLabel(at(2026, 9, 24), now, true)).toBe('Esta semana')
    expect(dateLabel(at(2026, 9, 22), now, true)).toBe('Antes')
    expect(dateLabel(at(2026, 9, 24), now, false)).toBe('Antes')
  })

  it('agrupa mantendo a ordem e omitindo grupos vazios', () => {
    const list = [
      makeSession({ session_id: 'a', last_activity_at: at(2026, 9, 29, 0, 5) }),
      makeSession({ session_id: 'b', last_activity_at: at(2026, 9, 20) }),
    ]
    expect(groupByDate(list, now, true).map((g) => [g.label, g.sessions.map((s) => s.session_id)])).toEqual([
      ['Hoje', ['a']],
      ['Antes', ['b']],
    ])
  })
})
```

Acrescentar em `frontend/src/stores/__tests__/sessions.spec.ts` (dentro do `describe` principal; usar os imports que o arquivo já tem, mais `makeEvent` de `../../test/factories` se faltar):

```ts
  it('limpa o pedido pendente quando a sessão sai de awaiting_decision', () => {
    const store = useSessionsStore()
    store.setForProject(1, [makeSession({
      session_id: 's1', state: 'awaiting_decision', display_state: 'waiting', awaiting_decision: true,
      pending_kind: 'tool',
      pending_permission: { prompt_id: 'p', tool_name: 'Bash', summary: 'ls', can_allow_always: false },
    })])

    store.applyEvent(makeEvent('session.state', { state: 'running' }, 5))

    const session = store.find('s1')!
    expect(session.pending_kind).toBeNull()
    expect(session.pending_permission).toBeNull()
  })
```

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/__tests__/conversationList.spec.ts src/stores/__tests__/sessions.spec.ts`
Expected: FAIL (módulo `conversationList` inexistente; `pending_kind` continua `'tool'`).

- [x] **Passo 3: tipos, http, token e store**

Em `frontend/src/types/api.ts`, no fim de `Session`:

```ts
  /** When the user finished the session (seconds); null when open or finished by inactivity. */
  finished_at?: number | null
  /** Last tool of the main conversation ("Edit sessions.py"); null after a backend restart. */
  last_action?: string | null
  /** Kind of the oldest pending prompt. */
  pending_kind?: 'tool' | 'question' | 'plan' | null
```

e, depois de `Session`:

```ts
/** Conversations with messages on a day, per project (`GET /api/activity`). */
export interface ActivityDay {
  date: string
  project_id: number
  sessions: number
}
```

Em `frontend/src/api/http.ts`, importar `ActivityDay` e acrescentar depois de `markSessionSeen`:

```ts
/** Marks many sessions as seen at once; unknown ids are ignored. */
export function markSessionsSeen(sessionIds: string[]): Promise<{ updated: number }> {
  return request('POST', '/api/sessions/seen', { session_ids: sessionIds })
}

/** Conversations with messages per day and project in the last `days` days. */
export function getActivity(days = 14): Promise<ActivityDay[]> {
  return request('GET', `/api/activity?days=${days}`)
}
```

Em `frontend/src/style.css`, junto dos outros tokens de cor do tema (`--color-diff-del-fg` é o último):

```css
  --color-info: #60a5fa;
```

Em `frontend/src/stores/sessions.ts`, no ramo `if (event.type === 'session.state')` de `applyEvent`, depois de `Object.assign(session, deriveDisplay(...))`:

```ts
      // The summary with the new pending prompt comes in a `session.updated`; until
      // then an old reason ("Pede permissão") must not stay on screen.
      if (data.state !== 'awaiting_decision') {
        session.pending_kind = null
        session.pending_permission = null
      }
```

- [x] **Passo 4: regras de lista**

Criar `frontend/src/conversationList.ts`:

```ts
import type { Session } from './types/api'

/** Why a session waits for the user, or null when it does not wait. */
export function waitingReason(session: Session): string | null {
  if (session.display_state !== 'waiting') return null
  if (session.state === 'error') return 'Parou com erro'
  if (session.pending_kind === 'tool') return `Pede permissão: ${session.pending_permission?.tool_name ?? 'ferramenta'}`
  if (session.pending_kind === 'question') return 'Fez uma pergunta'
  if (session.pending_kind === 'plan') return 'Plano para aprovar'
  return 'Sua vez'
}

export type InboxTab = 'pede-voce' | 'nao-lidas' | 'em-execucao' | 'todas'

export const INBOX_TABS: { id: InboxTab; label: string }[] = [
  { id: 'pede-voce', label: 'Pede você' },
  { id: 'nao-lidas', label: 'Não lidas' },
  { id: 'em-execucao', label: 'Em execução' },
  { id: 'todas', label: 'Todas' },
]

export function isInboxTab(value: unknown): value is InboxTab {
  return INBOX_TABS.some((tab) => tab.id === value)
}

/** Whether a session shows in a Inbox tab. Finished sessions never do. */
export function inInbox(session: Session, tab: InboxTab): boolean {
  const waiting = session.display_state === 'waiting'
  const running = session.display_state === 'running'
  const unread = session.unread && session.display_state !== 'finished'
  if (tab === 'pede-voce') return waiting
  if (tab === 'nao-lidas') return unread
  if (tab === 'em-execucao') return running
  return waiting || running || unread
}

export type DateLabel = 'Hoje' | 'Ontem' | 'Esta semana' | 'Antes'

function dayStart(year: number, month: number, day: number): number {
  return new Date(year, month, day).getTime()
}

/** Group of a Unix timestamp (seconds) by the local day. "Esta semana" only when `withWeek`. */
export function dateLabel(seconds: number, now: Date, withWeek: boolean): DateLabel {
  const time = seconds * 1000
  const y = now.getFullYear()
  const m = now.getMonth()
  const d = now.getDate()
  if (time >= dayStart(y, m, d)) return 'Hoje'
  if (time >= dayStart(y, m, d - 1)) return 'Ontem'
  if (withWeek && time >= dayStart(y, m, d - 6)) return 'Esta semana'
  return 'Antes'
}

const ORDER: DateLabel[] = ['Hoje', 'Ontem', 'Esta semana', 'Antes']

/** Sessions split by `dateLabel` of their last activity, keeping the list order. */
export function groupByDate(list: Session[], now: Date, withWeek: boolean): { label: DateLabel; sessions: Session[] }[] {
  const groups = new Map<DateLabel, Session[]>()
  for (const session of list) {
    const label = dateLabel(session.last_activity_at, now, withWeek)
    const bucket = groups.get(label) ?? []
    bucket.push(session)
    groups.set(label, bucket)
  }
  return ORDER.filter((label) => groups.has(label)).map((label) => ({ label, sessions: groups.get(label)! }))
}
```

- [x] **Passo 5: rodar os testes das regras e ver passar**

Run: `pnpm --dir frontend exec vitest run src/__tests__/conversationList.spec.ts src/stores/__tests__/sessions.spec.ts`
Expected: PASS.

- [x] **Passo 6: testes da linha (falham)**

Criar `frontend/src/components/conversation/__tests__/ConversationRow.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationRow from '../ConversationRow.vue'
import { createAppRouter } from '../../../router'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeGitRepo, makeProject, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
  projects.loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ branch: 'develop' })])
})
afterEach(() => vi.unstubAllGlobals())

function mountRow(session = makeSession(), variant?: 'inbox' | 'list' | 'compact') {
  const router = createAppRouter(createMemoryHistory())
  return mount(ConversationRow, { props: { session, variant }, global: { plugins: [pinia, router] } })
}

describe('linha de conversa', () => {
  it('mostra título, projeto, branch e tempo, e abre a conversa', () => {
    const wrapper = mountRow(makeSession({ session_id: 'abc', title: 'Corrigir login' }))

    expect(wrapper.find('[data-test="row-link"]').text()).toBe('Corrigir login')
    expect(wrapper.find('[data-test="row-link"]').attributes('href')).toBe('/sessions/abc')
    expect(wrapper.find('[data-test="row-project"]').text()).toContain('loja-online')
    expect(wrapper.find('[data-test="row-branch"]').text()).toContain('develop')
  })

  it('mostra a bolinha de não lida e o motivo da espera', () => {
    const wrapper = mountRow(makeSession({ unread: true, display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question' }))

    expect(wrapper.find('[data-test="unread-dot"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="waiting-reason"]').text()).toBe('Fez uma pergunta')
  })

  it('apaga o texto de finalizadas e oferece Reabrir', () => {
    const wrapper = mountRow(makeSession({ display_state: 'finished', finished: true }))

    expect(wrapper.find('[data-test="row-link"]').classes()).toContain('text-fg-muted')
    expect(wrapper.find('[data-test="row-reopen"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="row-finish"]').exists()).toBe(false)
  })

  it('finaliza pela ação da linha', async () => {
    const fetch = routeFetch({
      'PATCH /api/sessions/s1': () => jsonResponse(makeSession({ display_state: 'finished', finished: true })),
    })
    vi.stubGlobal('fetch', fetch)
    const wrapper = mountRow(makeSession({ display_state: 'waiting' }))

    await wrapper.find('[data-test="row-finish"]').trigger('click')
    await flushPromises()

    expect(JSON.parse(fetch.mock.calls[0]![1]!.body as string)).toEqual({ finished: true })
  })

  it('marca como lida só na Inbox', async () => {
    const fetch = routeFetch({ 'POST /api/sessions/s1/seen': () => jsonResponse(makeSession()) })
    vi.stubGlobal('fetch', fetch)

    expect(mountRow(makeSession({ unread: true }), 'list').find('[data-test="row-mark-read"]').exists()).toBe(false)
    const inbox = mountRow(makeSession({ unread: true }), 'inbox')
    await inbox.find('[data-test="row-mark-read"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledOnce()
  })

  it('a variante compacta não tem ações', () => {
    const wrapper = mountRow(makeSession({ unread: true }), 'compact')
    expect(wrapper.find('[data-test="row-finish"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="row-mark-read"]').exists()).toBe(false)
  })

  it('avisa o erro de uma ação', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/sessions/s1': () => jsonResponse({ detail: 'Falhou.' }, 500) }))
    const wrapper = mountRow(makeSession({ display_state: 'waiting' }))

    await wrapper.find('[data-test="row-finish"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('error')).toEqual([['Falhou.']])
  })
})
```

- [x] **Passo 7: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/conversation/__tests__/ConversationRow.spec.ts`
Expected: FAIL (componente inexistente).

- [x] **Passo 8: componente**

Criar `frontend/src/components/conversation/ConversationRow.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import BranchLabel from '../git/BranchLabel.vue'
import { errorMessage, markSessionSeen } from '../../api/http'
import { waitingReason } from '../../conversationList'
import { formatActivity } from '../../format'
import { displayStateLabels } from '../../sessionState'
import { repoLabel, useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { Session } from '../../types/api'

// One conversation in a list. `inbox` adds "Marcar como lida"; `compact` has no actions.
const props = withDefaults(defineProps<{ session: Session; variant?: 'inbox' | 'list' | 'compact' }>(), { variant: 'list' })
const emit = defineEmits<{ error: [message: string] }>()

const projects = useProjectsStore()
const git = useGitStore()
const sessions = useSessionsStore()

const project = computed(() => projects.byId(props.session.project_id))
const repo = computed(() => git.reposFor(props.session.project_id)[0])
const finished = computed(() => props.session.display_state === 'finished')
const reason = computed(() => waitingReason(props.session))
const busy = ref(false)

async function run(action: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true
  try {
    await action()
  } catch (e) {
    emit('error', errorMessage(e))
  } finally {
    busy.value = false
  }
}
const toggleFinished = () => run(() => sessions.setFinished(props.session.session_id, !finished.value))
const markRead = () => run(() => markSessionSeen(props.session.session_id))
</script>

<template>
  <div
    data-test="conversation-row"
    :data-unread="String(session.unread)"
    class="group relative flex min-h-11 items-center gap-3 rounded-md px-2 hover:bg-card focus-within:bg-card"
  >
    <span class="flex w-2 shrink-0 justify-center">
      <span v-if="session.unread" data-test="unread-dot" class="size-2 rounded-full bg-info" />
    </span>
    <DisplayStateIcon :display="session.display_state" />
    <RouterLink
      data-test="row-link"
      :to="{ name: 'session', params: { id: session.session_id } }"
      class="min-w-0 grow truncate no-underline after:absolute after:inset-0 focus-visible:outline-none"
      :class="[finished ? 'text-fg-muted' : 'text-fg', session.unread ? 'font-semibold' : 'font-normal']"
    >{{ session.title }}</RouterLink>
    <span class="sr-only">{{ displayStateLabels[session.display_state] }}{{ session.unread ? ', com novidade' : '' }}</span>
    <span v-if="reason" data-test="waiting-reason" class="max-w-64 shrink-0 truncate text-xs text-secondary-soft">{{ reason }}</span>
    <span v-if="project" data-test="row-project" class="hidden shrink-0 items-center gap-1.5 text-xs text-fg-muted md:flex">
      <span class="size-2 rounded-[3px]" :style="{ backgroundColor: project.color }" />
      <span class="max-w-40 truncate">{{ project.name }}</span>
    </span>
    <span v-if="repo" data-test="row-branch" class="hidden max-w-40 shrink-0 lg:flex">
      <BranchLabel :text="repoLabel(repo)" muted />
    </span>
    <span class="w-20 shrink-0 text-right text-xs text-fg-muted">{{ formatActivity(session.last_activity_at) }}</span>
    <div
      v-if="variant !== 'compact'"
      class="relative z-10 flex shrink-0 gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100"
    >
      <button
        v-if="variant === 'inbox' && session.unread"
        type="button"
        data-test="row-mark-read"
        class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Marcar ${session.title} como lida`"
        @click="markRead"
      >Marcar como lida</button>
      <button
        v-if="finished"
        type="button"
        data-test="row-reopen"
        class="h-8 rounded-md px-2 text-xs font-medium text-primary-soft hover:bg-elevated disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Reabrir ${session.title}`"
        @click="toggleFinished"
      >Reabrir</button>
      <button
        v-else
        type="button"
        data-test="row-finish"
        class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Finalizar ${session.title}`"
        @click="toggleFinished"
      >Finalizar</button>
    </div>
  </div>
</template>
```

Se `bg-info` não gerar classe, conferir como os outros tokens estão declarados em `style.css` (bloco `@theme`) e declarar `--color-info` no mesmo bloco.

- [x] **Passo 9: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/components/conversation/__tests__/ConversationRow.spec.ts`
Expected: PASS.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa; build sem erros de tipo.

- [x] **Passo 10: commit**

```bash
git add frontend/src/style.css frontend/src/types/api.ts frontend/src/api/http.ts frontend/src/stores/sessions.ts frontend/src/conversationList.ts frontend/src/components/conversation/ConversationRow.vue frontend/src/__tests__/conversationList.spec.ts frontend/src/components/conversation/__tests__/ConversationRow.spec.ts frontend/src/stores/__tests__/sessions.spec.ts
git commit -m "[Feat] Adicionar linha de conversa e regras de Inbox e grupos por data"
```

---

### Tarefa 4: Extrair o corpo da conversa para `ConversationThread`

Refatoração sem mudança de comportamento: tudo que o `SessionColumn` mostra abaixo do cabeçalho passa para um componente próprio, que a página nova vai usar.

**Arquivos:**
- Criar: `frontend/src/components/conversation/ConversationThread.vue`
- Modificar: `frontend/src/components/session/SessionColumn.vue`
- Criar: `frontend/src/components/conversation/__tests__/ConversationThread.spec.ts`

**Interfaces:**
- Produz: `ConversationThread.vue` com props `{ id: string; visible?: boolean }` (padrão `true`), eventos `missing: []` (snapshot 404). Ele carrega a conversa (`conversations.load`), assina os eventos da sessão, marca como vista, mostra a barra de turno, turnos, pedidos, erro, faixa de subagentes e o compositor. O conteúdo rolável fica numa coluna centralizada de até 760 px (`mx-auto w-full max-w-[760px]`); a barra de turno e o compositor usam a mesma largura.
- `SessionColumn` passa a ser: `<section>` com o cabeçalho atual + `<ConversationThread :id :visible @missing="emit('missing')" />`.

- [x] **Passo 1: teste do componente novo (falha)**

Criar `frontend/src/components/conversation/__tests__/ConversationThread.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationThread from '../ConversationThread.vue'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeSnapshot, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

function mountThread() {
  const router = createAppRouter(createMemoryHistory())
  return mount(ConversationThread, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
}

describe('corpo da conversa', () => {
  it('carrega a conversa e mostra o compositor', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ items: [{ type: 'user', id: 'u1', text: 'oi' }] })),
      'POST /api/sessions/s1/seen': () => jsonResponse({}),
    }))
    const wrapper = mountThread()
    await flushPromises()

    expect(wrapper.text()).toContain('oi')
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('avisa quando a conversa não existe', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404) }))
    const wrapper = mountThread()
    await flushPromises()

    expect(wrapper.emitted('missing')).toHaveLength(1)
  })
})
```

Se o item `user` do snapshot precisar de outros campos, copiar o formato de um item `user` usado em `components/session/__tests__/SessionColumn.spec.ts`.

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/conversation/__tests__/ConversationThread.spec.ts`
Expected: FAIL (componente inexistente).

- [x] **Passo 3: mover o código**

1. Criar `ConversationThread.vue` copiando de `SessionColumn.vue`:
   - Do `<script setup>`: todos os imports e todo o código **exceto** o que só o cabeçalho usa: `stateLabel`, `headerError`, `toggling`, `toggleFinished`, `editing`, `titleDraft`, `titleInput`, `startRename`, `cancelRename`, `saveRename`, `isFinished`, `listed`, `repos`, `git`, o `watch` de `git.ensure`, e os imports `RouterLink`, `SessionStateIcon`, `BranchLabel`, `repoLabel`, `useGitStore`, `deriveDisplay`, `displayStateLabels`, `useSessionsStore`. Mantém `project` e `unavailableReason` (o compositor usa).
   - `defineProps<{ id: string; visible?: boolean }>()` com `visible: true` por padrão e `defineEmits<{ missing: [] }>()`.
   - No `reload()`, o 404 continua fazendo `emit('missing')`.
2. Template do `ConversationThread`: a raiz é

```vue
<div class="flex min-h-0 grow flex-col" @focusin="markSeenSoon" @dragover="onDragOver" @drop="onDrop">
```

   e dentro dela, sem mudança de marcação interna: o `div` `conversation-live`, o `div` `conversation-scroller` (com a barra de turno e os turnos) e o bloco do rodapé (erro, `loadError`, `SubagentStrip`, `MessageComposer`). Envolver o conteúdo da barra de turno, o `div` dos turnos e o rodapé com `mx-auto w-full max-w-[760px]` (a barra continua `sticky` e com fundo de ponta a ponta; só o conteúdo interno ganha a largura). O estado "Carregando…" e o erro com "Tentar de novo" vão para o `v-else` quando `conv` não existe; o botão "Fechar coluna" desse estado **não** vem para o thread.
3. Em `SessionColumn.vue`, remover o código movido, importar `ConversationThread` e usar no lugar do corpo:

```vue
<ConversationThread :id="id" :visible="visible" @missing="emit('missing')" />
```

   `SessionColumn` mantém o `<section>` externo, o cabeçalho e o estado sem conversa com "Fechar coluna" (mostrado quando `conv` não existe e há `loadError`; para saber disso, o `SessionColumn` lê `conversations.get(id)`). Os atributos `@focusin`, `@dragover` e `@drop` saem da `section` do `SessionColumn` (agora estão no thread).

- [x] **Passo 4: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/components/conversation/__tests__/ConversationThread.spec.ts src/components/session`
Expected: PASS, incluindo os testes antigos de `SessionColumn`, `SessionTurns`, `SessionSubagents` e `SessionColumnHeader`, sem mudar asserções. Se algum teste antigo procurar um elemento pelo `section` do `SessionColumn` (por exemplo, disparar `focusin` na `section`), ajustar o seletor para o elemento do thread e explicar no relatório; não alterar o que ele verifica.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa.

- [x] **Passo 5: commit**

```bash
git add frontend/src/components/conversation/ConversationThread.vue frontend/src/components/session/SessionColumn.vue frontend/src/components/conversation/__tests__/ConversationThread.spec.ts
git commit -m "[Refactor] Extrair corpo da conversa para ConversationThread"
```

(Se algum teste antigo precisou de ajuste de seletor, incluir o arquivo no `git add`.)

---

### Tarefa 5: Painel Detalhes

**Arquivos:**
- Criar: `frontend/src/conversation/sessionChanges.ts`
- Criar: `frontend/src/components/details/ChangesList.vue`
- Criar: `frontend/src/components/details/FileDiffView.vue`
- Criar: `frontend/src/components/details/DetailsPanel.vue`
- Testes: `frontend/src/components/details/__tests__/DetailsPanel.spec.ts`

**Interfaces:**
- Consome: `getSessionChanges`, `getFileDiff`, `openInEditor` (http); `diffFromUnified`, `diffWithoutHunks`, `toolDiff` (`conversation/diff`); `str` (`conversation/tool`); `DiffLines`; `useChangesPanelStore` (`sessionId`, `edit`, `close()`); stores `conversation`, `sessions`, `projects`, `git`; `formatTokens`, `formatActivity`.
- Produz: `useSessionChanges(sessionId: () => string)` → `{ groups: Ref<ChangesGroup[]>, loading: Ref<boolean>, error: Ref<string | null>, total: ComputedRef<{ added: number; removed: number }>, reload(): Promise<void> }` (recarrega ao mudar `conv.lastResult`; aborta pedidos anteriores).
- Produz: `ChangesList.vue` props `{ groups; loading; error; selected: { group: string | null; file: string } | null }`, evento `select: [group: ChangesGroup, file: ChangedFile]`, `retry: []`.
- Produz: `FileDiffView.vue` props `{ projectId: number; group: ChangesGroup; file: ChangedFile }`.
- Produz: `DetailsPanel.vue` props `{ sessionId: string; drawer?: boolean }`, evento `close: []` (usado só como gaveta). O ⤢ (largo/normal) é estado local do painel; lembrar se o painel está aberto ou fechado é papel da página (Tarefa 6).
- `data-test`: `details-panel`, `details-properties`, `prop-state`, `prop-project`, `prop-branch`, `prop-context`, `prop-turns`, `prop-created`, `prop-activity`, `details-changes`, `changed-file`, `changes-error`, `changes-retry`, `details-diff`, `diff-back`, `diff-expand`, `open-file-editor`.

- [x] **Passo 1: testes (falham)**

Criar `frontend/src/components/details/__tests__/DetailsPanel.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import DetailsPanel from '../DetailsPanel.vue'
import { createAppRouter } from '../../../router'
import { useChangesPanelStore } from '../../../stores/changesPanel'
import { useConversationStore } from '../../../stores/conversation'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeGitRepo, makeProject, makeSession, makeSnapshot, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

const changes = {
  repos: [{
    path: '/home/vi/dev/loja-online', rel_path: '.', branch: 'main', detached: false, head: 'abc',
    files: [{ path: '/home/vi/dev/loja-online/a.py', rel_path: 'a.py', added: 3, removed: 1, uncommitted: true }],
  }],
}

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ branch: 'main' })])
  useSessionsStore(pinia).setForProject(1, [makeSession({
    session_id: 's1', created_at: 1_790_000_000, last_activity_at: 1_790_000_100,
    context: { used_tokens: 84_000, max_tokens: 200_000, percent: 42 },
    display_state: 'waiting', state: 'idle',
  })])
})
afterEach(() => vi.unstubAllGlobals())

async function mountPanel(fetchHandlers = {}) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/changes': () => jsonResponse(changes),
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ items: [
      { type: 'user', id: 'u1', text: 'um' }, { type: 'user', id: 'u2', text: 'dois' },
    ] })),
    ...fetchHandlers,
  }))
  await useConversationStore(pinia).load('s1')
  const router = createAppRouter(createMemoryHistory())
  const wrapper = mount(DetailsPanel, { props: { sessionId: 's1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('painel Detalhes', () => {
  it('mostra as propriedades da conversa', async () => {
    const wrapper = await mountPanel()

    expect(wrapper.find('[data-test="prop-state"]').text()).toContain('Sua vez')
    expect(wrapper.find('[data-test="prop-project"] a').attributes('href')).toBe('/projects/1')
    expect(wrapper.find('[data-test="prop-branch"]').text()).toContain('main')
    expect(wrapper.find('[data-test="prop-context"]').text()).toContain('42%')
    expect(wrapper.find('[data-test="prop-context"]').text()).toContain('84 mil')
    expect(wrapper.find('[data-test="prop-turns"]').text()).toContain('2')
  })

  it('lista os arquivos alterados e abre o diff de um deles', async () => {
    const wrapper = await mountPanel({
      'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff: '@@ -1 +1 @@\n-a\n+b\n', truncated: false }),
    })

    const file = wrapper.find('[data-test="changed-file"]')
    expect(file.text()).toContain('a.py')
    expect(file.text()).toContain('+3')
    await file.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="details-diff"]').text()).toContain('a.py')

    await wrapper.find('[data-test="diff-back"]').trigger('click')
    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(true)
  })

  it('abre o diff de uma edição pedida pela conversa', async () => {
    const wrapper = await mountPanel()
    useChangesPanelStore(pinia).open('s1', {
      type: 'tool', id: 't1', tool_use_id: 't1', name: 'Edit',
      input: { file_path: '/x/b.py', old_string: 'a', new_string: 'b' }, result: null,
    } as never)
    await flushPromises()

    expect(wrapper.find('[data-test="details-diff"]').text()).toContain('/x/b.py')
    await wrapper.find('[data-test="diff-back"]').trigger('click')
    expect(useChangesPanelStore(pinia).edit).toBeNull()
  })

  it('alarga e volta com o botão de expandir', async () => {
    const wrapper = await mountPanel({
      'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff: '', truncated: false }),
    })
    await wrapper.find('[data-test="changed-file"]').trigger('click')
    await flushPromises()

    const expand = wrapper.find('[data-test="diff-expand"]')
    await expand.trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').attributes('data-wide')).toBe('true')
    await expand.trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').attributes('data-wide')).toBe('false')
  })

  it('mostra o erro só na seção de alterações e tenta de novo', async () => {
    let calls = 0
    const wrapper = await mountPanel({
      'GET /api/sessions/s1/changes': () => (++calls === 1 ? jsonResponse({ detail: 'Falhou.' }, 500) : jsonResponse(changes)),
    })

    expect(wrapper.find('[data-test="changes-error"]').text()).toContain('Falhou.')
    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(true)
    await wrapper.find('[data-test="changes-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="changed-file"]').exists()).toBe(true)
  })
})
```

Se o formato de `ToolItem` exigir outros campos, copiar um item `tool` de `components/git/__tests__/ChangesPanel.spec.ts`.

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/details`
Expected: FAIL (componentes inexistentes).

- [x] **Passo 3: carga da lista de alterações**

Criar `frontend/src/conversation/sessionChanges.ts`:

```ts
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, getSessionChanges } from '../api/http'
import { useConversationStore } from '../stores/conversation'
import type { ChangesGroup } from '../types/api'

/** Files changed by a session, reloaded at the end of each of its turns. */
export function useSessionChanges(sessionId: () => string) {
  const conversations = useConversationStore()
  const groups = ref<ChangesGroup[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const total = computed(() => {
    let added = 0
    let removed = 0
    for (const group of groups.value) {
      for (const file of group.files) {
        added += file.added ?? 0
        removed += file.removed ?? 0
      }
    }
    return { added, removed }
  })

  // Only the newest answer is applied; older requests are aborted.
  let generation = 0
  let controller: AbortController | null = null

  async function reload(): Promise<void> {
    const mine = ++generation
    controller?.abort()
    const ctrl = (controller = new AbortController())
    loading.value = true
    try {
      const result = await getSessionChanges(sessionId(), ctrl.signal)
      if (mine !== generation) return
      groups.value = result.repos
      error.value = null
    } catch (e) {
      if (mine === generation) error.value = errorMessage(e)
    } finally {
      if (mine === generation) loading.value = false
    }
  }

  watch(sessionId, () => {
    groups.value = []
    void reload()
  })
  watch(() => conversations.get(sessionId())?.lastResult, (result, before) => {
    if (result && result !== before) void reload()
  })
  onBeforeUnmount(() => {
    generation++
    controller?.abort()
  })
  void reload()

  return { groups, loading, error, total, reload }
}
```

- [x] **Passo 4: lista e diff de arquivo**

Criar `frontend/src/components/details/ChangesList.vue`:

```vue
<script setup lang="ts">
import BranchLabel from '../git/BranchLabel.vue'
import { branchText } from '../../stores/git'
import type { ChangedFile, ChangesGroup } from '../../types/api'

defineProps<{
  groups: ChangesGroup[]
  loading: boolean
  error: string | null
  selected: { group: string | null; file: string } | null
}>()
const emit = defineEmits<{ select: [group: ChangesGroup, file: ChangedFile]; retry: [] }>()
</script>

<template>
  <div class="flex flex-col gap-2">
    <div v-if="error" class="flex flex-col items-start gap-2">
      <p data-test="changes-error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
      <button
        type="button"
        data-test="changes-retry"
        class="h-8 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card"
        @click="emit('retry')"
      >Tentar de novo</button>
    </div>
    <p v-else-if="!loading && groups.length === 0" class="m-0 text-sm text-fg-muted">Sem alterações</p>
    <div v-for="group in groups" :key="group.path ?? '-'" class="flex flex-col rounded-lg border border-line">
      <div class="flex items-center gap-2 border-b border-line px-3 py-2">
        <span class="min-w-0 truncate font-mono text-xs font-semibold">{{ group.rel_path ?? 'Fora de repositório' }}</span>
        <BranchLabel v-if="group.rel_path != null" :text="branchText({ ...group, error: null })" muted />
      </div>
      <button
        v-for="file in group.files"
        :key="file.path"
        type="button"
        data-test="changed-file"
        class="flex min-h-9 items-center gap-2 border-b border-line px-3 text-left last:border-b-0 hover:bg-card"
        :aria-pressed="selected?.group === group.path && selected?.file === file.path"
        @click="emit('select', group, file)"
      >
        <span class="min-w-0 grow truncate font-mono text-xs">{{ file.rel_path }}</span>
        <span v-if="file.uncommitted" class="shrink-0 text-xs text-secondary-soft">sem commit</span>
        <span v-if="file.added != null" class="font-mono text-xs text-diff-add-fg">+{{ file.added }}</span>
        <span v-if="file.removed != null" class="font-mono text-xs text-diff-del-fg">−{{ file.removed }}</span>
      </button>
    </div>
  </div>
</template>
```

Criar `frontend/src/components/details/FileDiffView.vue` (lógica igual à seleção de arquivo do `ChangesPanel`):

```vue
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, errorMessage, getFileDiff, openInEditor } from '../../api/http'
import { diffFromUnified, diffWithoutHunks, type DiffLine } from '../../conversation/diff'
import DiffLines from '../conversation/DiffLines.vue'
import type { ChangedFile, ChangesGroup } from '../../types/api'

const props = defineProps<{ projectId: number; group: ChangesGroup; file: ChangedFile }>()

const lines = ref<DiffLine[]>([])
const note = ref<string | null>(null)
const truncated = ref(false)
const error = ref<string | null>(null)
const editorError = ref<string | null>(null)
let generation = 0
let controller: AbortController | null = null

async function load() {
  const mine = ++generation
  controller?.abort()
  lines.value = []
  note.value = null
  truncated.value = false
  error.value = null
  if (props.group.rel_path == null) return
  const ctrl = (controller = new AbortController())
  try {
    const result = await getFileDiff(props.projectId, props.group.rel_path, props.file.rel_path, ctrl.signal)
    if (mine !== generation) return
    lines.value = diffFromUnified(result.diff)
    note.value = result.notice ?? diffWithoutHunks(result.diff)
    truncated.value = result.truncated
  } catch (e) {
    if (mine !== generation) return
    error.value = e instanceof ApiError && e.status === 404 && !e.detail ? 'O arquivo não existe mais.' : errorMessage(e)
  }
}

async function openFile() {
  editorError.value = null
  try {
    await openInEditor(props.file.path)
  } catch (e) {
    editorError.value = errorMessage(e)
  }
}

watch(() => [props.group.path, props.file.path], load, { immediate: true })
onBeforeUnmount(() => {
  generation++
  controller?.abort()
})
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex items-center gap-2">
      <span class="min-w-0 grow truncate font-mono text-xs">{{ file.rel_path }}</span>
      <button
        type="button"
        data-test="open-file-editor"
        class="h-8 shrink-0 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card"
        @click="openFile"
      >Abrir no editor</button>
    </div>
    <p v-if="editorError" role="alert" class="m-0 text-sm text-secondary-soft">{{ editorError }}</p>
    <p v-if="error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
    <p v-else-if="group.rel_path == null" class="m-0 text-sm text-fg-muted">Fora de um repositório git, não há diff contra o último commit.</p>
    <div v-else class="overflow-hidden rounded-lg border border-line bg-bg">
      <p v-if="lines.length === 0" class="m-0 px-3 py-2 text-sm text-fg-muted">{{ note ?? 'Sem alterações' }}</p>
      <DiffLines :lines="lines" />
      <p v-if="truncated" class="m-0 border-t border-line px-3 py-2 text-xs text-fg-muted">Diff cortado por ser grande demais.</p>
    </div>
  </div>
</template>
```

Se `DiffLine` não for exportado de `conversation/diff`, importar o tipo do mesmo lugar que o `ChangesPanel` importa.

- [x] **Passo 5: painel**

Criar `frontend/src/components/details/DetailsPanel.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import BranchLabel from '../git/BranchLabel.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import DiffLines from '../conversation/DiffLines.vue'
import ChangesList from './ChangesList.vue'
import FileDiffView from './FileDiffView.vue'
import { useSessionChanges } from '../../conversation/sessionChanges'
import { toolDiff } from '../../conversation/diff'
import { str } from '../../conversation/tool'
import { waitingReason } from '../../conversationList'
import { formatActivity, formatTokens } from '../../format'
import { displayStateLabels } from '../../sessionState'
import { useChangesPanelStore } from '../../stores/changesPanel'
import { useConversationStore } from '../../stores/conversation'
import { repoLabel, useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { ChangedFile, ChangesGroup } from '../../types/api'

const props = withDefaults(defineProps<{ sessionId: string; drawer?: boolean }>(), { drawer: false })
const emit = defineEmits<{ close: [] }>()

const sessions = useSessionsStore()
const conversations = useConversationStore()
const projects = useProjectsStore()
const git = useGitStore()
const panel = useChangesPanelStore()

const session = computed(() => sessions.find(props.sessionId))
const conv = computed(() => conversations.get(props.sessionId))
const projectId = computed(() => session.value?.project_id ?? conv.value?.projectId ?? null)
const project = computed(() => (projectId.value != null ? projects.byId(projectId.value) : undefined))
const repos = computed(() => (projectId.value != null ? git.reposFor(projectId.value) : []))
const context = computed(() => session.value?.context ?? conv.value?.context ?? null)
const turns = computed(() => (conv.value?.items ?? []).filter((i) => i.type === 'user' && !('parent_tool_use_id' in i && i.parent_tool_use_id)).length)
const stateText = computed(() => {
  const s = session.value
  if (!s) return ''
  return waitingReason(s) ?? displayStateLabels[s.display_state]
})

const changes = useSessionChanges(() => props.sessionId)

// What the panel shows: properties and the list, or one diff (a file or an edit of the conversation).
const selectedFile = ref<{ group: ChangesGroup; file: ChangedFile } | null>(null)
const editOpen = computed(() => panel.sessionId === props.sessionId && panel.edit != null)
const showingDiff = computed(() => editOpen.value || selectedFile.value != null)
const wide = ref(false)
const editLines = computed(() => {
  const item = panel.edit
  return item ? toolDiff(item.name, item.input, item.result?.details ?? null) : []
})

function selectFile(group: ChangesGroup, file: ChangedFile) {
  panel.close()
  selectedFile.value = { group, file }
}
function back() {
  selectedFile.value = null
  if (editOpen.value) panel.close()
  wide.value = false
}
watch(() => props.sessionId, back)
// An edit opened from the conversation replaces a selected file.
watch(editOpen, (open) => { if (open) selectedFile.value = null })
</script>

<template>
  <aside
    data-test="details-panel"
    :data-wide="String(wide)"
    aria-label="Detalhes da conversa"
    class="flex h-full shrink-0 flex-col border-l border-line bg-panel"
    :class="wide ? 'w-[60vw]' : 'w-[360px]'"
  >
    <header class="flex min-h-12 items-center gap-2 border-b border-line px-4">
      <template v-if="showingDiff">
        <button
          type="button"
          data-test="diff-back"
          class="h-8 rounded-md px-2 text-sm text-fg-muted hover:bg-card hover:text-fg"
          @click="back"
        >‹ Voltar</button>
        <span class="grow" />
        <button
          type="button"
          data-test="diff-expand"
          :aria-label="wide ? 'Voltar à largura normal' : 'Alargar o painel'"
          :aria-pressed="wide"
          class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
          @click="wide = !wide"
        >⤢</button>
      </template>
      <h2 v-else class="m-0 grow text-sm font-semibold">Detalhes</h2>
      <button
        v-if="drawer"
        type="button"
        aria-label="Fechar detalhes"
        class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
        @click="emit('close')"
      >×</button>
    </header>

    <div class="flex min-h-0 grow flex-col gap-5 overflow-y-auto p-4">
      <template v-if="showingDiff">
        <section v-if="editOpen && panel.edit" data-test="details-diff" class="overflow-hidden rounded-lg border border-line bg-bg">
          <div class="truncate border-b border-line px-3 py-2 font-mono text-xs text-fg-muted">{{ str(panel.edit.input.file_path) }}</div>
          <DiffLines :lines="editLines" />
        </section>
        <section v-else-if="selectedFile && projectId != null" data-test="details-diff">
          <FileDiffView :project-id="projectId" :group="selectedFile.group" :file="selectedFile.file" />
        </section>
      </template>
      <template v-else>
        <section data-test="details-properties" aria-labelledby="props-title" class="flex flex-col gap-2">
          <h3 id="props-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Propriedades</h3>
          <dl class="m-0 grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2 text-sm">
            <dt class="text-fg-muted">Estado</dt>
            <dd data-test="prop-state" class="m-0 flex items-center gap-1.5">
              <DisplayStateIcon v-if="session" :display="session.display_state" />{{ stateText }}
            </dd>
            <dt class="text-fg-muted">Projeto</dt>
            <dd data-test="prop-project" class="m-0 min-w-0">
              <RouterLink v-if="project" :to="{ name: 'project', params: { id: project.id } }" class="flex items-center gap-1.5 text-fg no-underline hover:text-primary-soft">
                <span class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
                <span class="truncate">{{ project.name }}</span>
              </RouterLink>
            </dd>
            <dt class="text-fg-muted">Branch</dt>
            <dd data-test="prop-branch" class="m-0 flex min-w-0 flex-col gap-1">
              <BranchLabel v-for="repo in repos" :key="repo.path" :text="repoLabel(repo)" :muted="!!repo.error" />
              <span v-if="repos.length === 0" class="text-fg-muted">sem repositório git</span>
            </dd>
            <dt class="text-fg-muted">Contexto</dt>
            <dd data-test="prop-context" class="m-0 flex flex-col gap-1">
              <template v-if="context">
                <span :class="context.percent >= 80 ? 'text-secondary' : 'text-fg'">{{ Math.round(context.percent) }}% · {{ formatTokens(context.used_tokens) }} de {{ formatTokens(context.max_tokens) }}</span>
                <span class="h-1.5 overflow-hidden rounded-full bg-line" aria-hidden="true">
                  <span class="block h-full rounded-full" :class="context.percent >= 80 ? 'bg-secondary' : 'bg-primary'" :style="{ width: `${Math.min(context.percent, 100)}%` }" />
                </span>
              </template>
              <span v-else class="text-fg-muted">Desconhecido</span>
            </dd>
            <dt class="text-fg-muted">Turnos</dt>
            <dd data-test="prop-turns" class="m-0">{{ turns }}</dd>
            <dt class="text-fg-muted">Início</dt>
            <dd data-test="prop-created" class="m-0">{{ session ? formatActivity(session.created_at) : '' }}</dd>
            <dt class="text-fg-muted">Última atividade</dt>
            <dd data-test="prop-activity" class="m-0">{{ session ? formatActivity(session.last_activity_at) : '' }}</dd>
          </dl>
        </section>
        <section data-test="details-changes" aria-labelledby="changes-title" class="flex flex-col gap-2">
          <h3 id="changes-title" class="m-0 flex items-center gap-2 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">
            Alterações
            <span class="normal-case tracking-normal"><span class="text-diff-add-fg">+{{ changes.total.value.added }}</span> <span class="text-diff-del-fg">−{{ changes.total.value.removed }}</span></span>
          </h3>
          <ChangesList
            :groups="changes.groups.value"
            :loading="changes.loading.value"
            :error="changes.error.value"
            :selected="null"
            @select="selectFile"
            @retry="changes.reload()"
          />
        </section>
      </template>
    </div>
  </aside>
</template>
```

- [x] **Passo 6: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/components/details`
Expected: PASS.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa.

- [x] **Passo 7: commit**

```bash
git add frontend/src/conversation/sessionChanges.ts frontend/src/components/details
git commit -m "[Feat] Adicionar painel Detalhes com propriedades, alterações e diff"
```

---

### Tarefa 6: Página da conversa

**Arquivos:**
- Criar: `frontend/src/components/conversation/ConversationHeader.vue`
- Criar: `frontend/src/views/ConversationView.vue`
- Criar: `frontend/src/useMediaQuery.ts`
- Criar: `frontend/src/detailsPanelPref.ts`
- Modificar: `frontend/src/router/index.ts` (rota `session` → `ConversationView`)
- Modificar: `frontend/src/components/session/SessionControls.vue` (contexto só a partir de 80%)
- Testes: `frontend/src/views/__tests__/ConversationView.spec.ts`; ajuste em `frontend/src/components/session/__tests__/SessionControls.spec.ts`

**Interfaces:**
- Consome: `ConversationThread` (Tarefa 4), `DetailsPanel` (Tarefa 5), `useSessionsStore().setFinished/rename/find`, `useConversationStore().get`, `openInEditor`.
- Produz: `ConversationView.vue` com prop `id: string` (a rota passa `props: true`).
- Produz: `frontend/src/detailsPanelPref.ts` com `readDetailsOpen(): boolean` (padrão `true`) e `writeDetailsOpen(open: boolean): void`, chave `vibing:details-open`, ambas com try/catch.
- Produz: `useMediaQuery(query: string): Ref<boolean>`.
- `data-test`: `breadcrumb`, `toggle-details`, `conversation-title`, `title-input`, `toggle-finished`, `header-menu`, `menu-rename`, `menu-editor`, `menu-copy-id`, `header-error`, `external-activity`, `conversation-missing`, `details-drawer`.

- [x] **Passo 1: testes (falham)**

Criar `frontend/src/views/__tests__/ConversationView.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationView from '../ConversationView.vue'
import { createAppRouter } from '../../router'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeProject, makeSession, makeSnapshot, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

function stubMedia(wide: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: wide, media: query, addEventListener() {}, removeEventListener() {},
  }))
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'waiting' })])
  localStorage.clear()
  stubMedia(true)
})
afterEach(() => vi.unstubAllGlobals())

const baseFetch = {
  'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ title: 'Corrigir login' })),
  'GET /api/sessions/s1/changes': () => jsonResponse({ repos: [] }),
  'POST /api/sessions/s1/seen': () => jsonResponse(makeSession()),
  'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
  'GET /api/models': () => jsonResponse([]),
}

async function mountAt(path: string, handlers = {}) {
  vi.stubGlobal('fetch', routeFetch({ ...baseFetch, ...handlers }))
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(ConversationView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('página da conversa', () => {
  it('mostra trilha, título e o painel Detalhes aberto por padrão', async () => {
    const { wrapper } = await mountAt('/sessions/s1')

    expect(wrapper.find('[data-test="breadcrumb"]').text()).toContain('Conversas')
    expect(wrapper.find('[data-test="breadcrumb"]').text()).toContain('loja-online')
    expect(wrapper.find('[data-test="conversation-title"]').text()).toBe('Corrigir login')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
  })

  it('esconde o painel e lembra a escolha', async () => {
    const { wrapper } = await mountAt('/sessions/s1')
    await wrapper.find('[data-test="toggle-details"]').trigger('click')

    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
    expect(localStorage.getItem('vibing:details-open')).toBe('false')
  })

  it('funciona sem localStorage', async () => {
    vi.stubGlobal('localStorage', {
      getItem() { throw new Error('bloqueado') },
      setItem() { throw new Error('bloqueado') },
      clear() {},
    })
    const { wrapper } = await mountAt('/sessions/s1')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
    await wrapper.find('[data-test="toggle-details"]').trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
  })

  it('em tela estreita o painel vira gaveta fechada', async () => {
    stubMedia(false)
    const { wrapper } = await mountAt('/sessions/s1')

    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
    await wrapper.find('[data-test="toggle-details"]').trigger('click')
    expect(wrapper.find('[data-test="details-drawer"] [data-test="details-panel"]').exists()).toBe(true)
  })

  it('renomeia pelo título', async () => {
    const fetch = routeFetch({
      ...baseFetch,
      'PATCH /api/sessions/s1': () => jsonResponse(makeSession({ session_id: 's1', title: 'Novo nome' })),
    })
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(ConversationView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('[data-test="conversation-title"]').trigger('click')
    await wrapper.find('[data-test="title-input"]').setValue('Novo nome')
    await wrapper.find('[data-test="title-input"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    const patch = fetch.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(patch[1]!.body as string)).toEqual({ title: 'Novo nome' })
  })

  it('mostra "Conversa não encontrada" para id desconhecido', async () => {
    const { wrapper } = await mountAt('/sessions/s1', {
      'GET /api/sessions/s1': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404),
    })

    expect(wrapper.find('[data-test="conversation-missing"]').text()).toContain('Conversa não encontrada')
    expect(wrapper.find('[data-test="conversation-missing"] a').attributes('href')).toBe('/sessions')
  })

  it('copia o id da sessão pelo menu', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const { wrapper } = await mountAt('/sessions/s1')

    await wrapper.find('[data-test="header-menu"]').trigger('click')
    await wrapper.find('[data-test="menu-copy-id"]').trigger('click')

    expect(writeText).toHaveBeenCalledWith('s1')
  })
})
```

Em `frontend/src/components/session/__tests__/SessionControls.spec.ts`, localizar o teste que espera ver "Contexto N%" com N abaixo de 80 e trocar a expectativa: com 42% o `[data-test="context-usage"]` **não** existe; acrescentar um caso com 85% em que ele existe e mostra "Contexto 85%".

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/views/__tests__/ConversationView.spec.ts src/components/session/__tests__/SessionControls.spec.ts`
Expected: FAIL.

- [x] **Passo 3: preferências e media query**

Criar `frontend/src/detailsPanelPref.ts`:

```ts
const KEY = 'vibing:details-open'

/** Whether the details panel starts open on wide screens (default: open). */
export function readDetailsOpen(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'false'
  } catch {
    return true
  }
}

export function writeDetailsOpen(open: boolean): void {
  try {
    localStorage.setItem(KEY, String(open))
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
```

Criar `frontend/src/useMediaQuery.ts`:

```ts
import { onBeforeUnmount, ref, type Ref } from 'vue'

/** Reactive `matchMedia(query).matches`; false where matchMedia does not exist. */
export function useMediaQuery(query: string): Ref<boolean> {
  const list = typeof window.matchMedia === 'function' ? window.matchMedia(query) : null
  const matches = ref(list?.matches ?? false)
  const update = (event: { matches: boolean }) => { matches.value = event.matches }
  list?.addEventListener?.('change', update)
  onBeforeUnmount(() => list?.removeEventListener?.('change', update))
  return matches
}
```

- [x] **Passo 4: cabeçalho**

Criar `frontend/src/components/conversation/ConversationHeader.vue` (renomear e finalizar vêm do cabeçalho do `SessionColumn`):

```vue
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import BranchLabel from '../git/BranchLabel.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { errorMessage, openInEditor } from '../../api/http'
import { useConversationStore } from '../../stores/conversation'
import { repoLabel, useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ id: string }>()

const sessions = useSessionsStore()
const conversations = useConversationStore()
const projects = useProjectsStore()
const git = useGitStore()

const listed = computed(() => sessions.find(props.id))
const conv = computed(() => conversations.get(props.id))
const title = computed(() => conv.value?.title ?? listed.value?.title ?? '')
const projectId = computed(() => listed.value?.project_id ?? conv.value?.projectId ?? null)
const project = computed(() => (projectId.value != null ? projects.byId(projectId.value) : undefined))
const repos = computed(() => (projectId.value != null ? git.reposFor(projectId.value) : []))
watch(projectId, (id) => { if (id != null) git.ensure(id) }, { immediate: true })
const isFinished = computed(() => listed.value?.display_state === 'finished')

const error = ref<string | null>(null)
const toggling = ref(false)
async function toggleFinished() {
  toggling.value = true
  error.value = null
  try {
    await sessions.setFinished(props.id, !isFinished.value)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    toggling.value = false
  }
}

// Inline rename: Enter saves, Esc cancels.
const editing = ref(false)
const draft = ref('')
const input = ref<HTMLInputElement | null>(null)
async function startRename() {
  menuOpen.value = false
  draft.value = title.value
  error.value = null
  editing.value = true
  await nextTick()
  input.value?.select()
}
async function saveRename() {
  const value = draft.value.trim()
  if (!value) {
    error.value = 'O título não pode ficar vazio.'
    return
  }
  try {
    await sessions.rename(props.id, value)
    if (conv.value) conv.value.title = value
    editing.value = false
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}

const menuOpen = ref(false)
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null
onBeforeUnmount(() => { if (copiedTimer) clearTimeout(copiedTimer) })
async function copyId() {
  menuOpen.value = false
  try {
    await navigator.clipboard.writeText(props.id)
    copied.value = true
    copiedTimer = setTimeout(() => { copied.value = false }, 2000)
  } catch {
    error.value = 'Não foi possível copiar o ID.'
  }
}
async function openProject() {
  menuOpen.value = false
  if (!project.value) return
  try {
    await openInEditor(project.value.path)
  } catch (e) {
    error.value = errorMessage(e)
  }
}
</script>

<template>
  <header class="mx-auto flex w-full max-w-[760px] flex-col gap-2 px-4 pt-5 pb-3">
    <div class="flex items-start gap-3">
      <DisplayStateIcon v-if="listed" :display="listed.display_state" :size="16" class="mt-2" />
      <input
        v-if="editing"
        ref="input"
        v-model="draft"
        data-test="title-input"
        aria-label="Título da conversa"
        maxlength="200"
        class="h-10 min-w-0 grow rounded-md border border-line-strong bg-bg px-2.5 text-xl font-semibold text-fg outline-none focus:border-primary"
        @keydown.enter.prevent="saveRename"
        @keydown.esc.prevent="editing = false"
      />
      <h1 v-else class="m-0 min-w-0 grow text-2xl font-semibold tracking-tight">
        <button
          type="button"
          data-test="conversation-title"
          title="Clique para renomear"
          class="max-w-full text-left hover:text-primary-soft focus-visible:outline-2 focus-visible:outline-primary"
          @click="startRename"
        >{{ title }}</button>
      </h1>
      <button
        v-if="listed"
        type="button"
        data-test="toggle-finished"
        class="h-9 shrink-0 rounded-md border border-line-strong px-3 text-sm font-medium hover:bg-card disabled:opacity-40"
        :class="isFinished ? 'text-primary-soft' : 'text-fg'"
        :disabled="toggling"
        @click="toggleFinished"
      >{{ isFinished ? 'Reabrir' : 'Finalizar' }}</button>
      <div class="relative shrink-0">
        <button
          type="button"
          data-test="header-menu"
          aria-label="Mais ações"
          :aria-expanded="menuOpen"
          class="flex size-9 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
          @click="menuOpen = !menuOpen"
        >⋯</button>
        <div
          v-if="menuOpen"
          role="menu"
          class="absolute right-0 z-20 mt-1 flex w-56 flex-col rounded-lg border border-line-strong bg-elevated py-1 shadow-lg"
          @keydown.esc="menuOpen = false"
        >
          <button type="button" role="menuitem" data-test="menu-rename" class="px-3 py-2 text-left text-sm hover:bg-card" @click="startRename">Renomear</button>
          <button type="button" role="menuitem" data-test="menu-editor" class="px-3 py-2 text-left text-sm hover:bg-card" :disabled="!project" @click="openProject">Abrir projeto no editor</button>
          <button type="button" role="menuitem" data-test="menu-copy-id" class="px-3 py-2 text-left text-sm hover:bg-card" @click="copyId">Copiar ID da sessão</button>
        </div>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-1.5 pl-7">
      <span v-if="project" class="flex items-center gap-1.5 rounded-full border border-line-strong bg-card px-2.5 py-[3px] text-xs">
        <span class="size-2 rounded-[3px]" :style="{ backgroundColor: project.color }" />{{ project.name }}
      </span>
      <span v-for="repo in repos" :key="repo.path" class="flex items-center rounded-full border border-line-strong bg-card px-2.5 py-[3px]">
        <BranchLabel :text="repoLabel(repo)" :muted="!!repo.error" />
      </span>
      <span v-if="copied" role="status" class="text-xs text-primary-soft">ID copiado</span>
    </div>
    <p v-if="error" data-test="header-error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
    <p
      v-if="conv?.externalActivity"
      data-test="external-activity"
      role="status"
      class="m-0 rounded-md border border-secondary/40 bg-secondary/10 px-3 py-2 text-xs text-secondary-soft"
    >Esta sessão foi modificada fora do app no último minuto. Usar a mesma sessão no CLI e aqui ao mesmo tempo pode embaralhar o histórico.</p>
  </header>
</template>
```

- [x] **Passo 5: página**

Criar `frontend/src/views/ConversationView.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import ConversationHeader from '../components/conversation/ConversationHeader.vue'
import ConversationThread from '../components/conversation/ConversationThread.vue'
import DetailsPanel from '../components/details/DetailsPanel.vue'
import { readDetailsOpen, writeDetailsOpen } from '../detailsPanelPref'
import { useMediaQuery } from '../useMediaQuery'
import { useChangesPanelStore } from '../stores/changesPanel'
import { useConversationStore } from '../stores/conversation'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'

const props = defineProps<{ id: string }>()

const sessions = useSessionsStore()
const conversations = useConversationStore()
const projects = useProjectsStore()
const changesPanel = useChangesPanelStore()

const title = computed(() => conversations.get(props.id)?.title ?? sessions.find(props.id)?.title ?? '')
const project = computed(() => {
  const id = sessions.find(props.id)?.project_id ?? conversations.get(props.id)?.projectId
  return id != null ? projects.byId(id) : undefined
})

const missing = ref(false)
watch(() => props.id, () => { missing.value = false })

// Wide screens: a side panel whose open state is remembered. Narrow: a drawer, closed at first.
const wideScreen = useMediaQuery('(min-width: 1200px)')
const sideOpen = ref(readDetailsOpen())
const drawerOpen = ref(false)
function toggleDetails() {
  if (wideScreen.value) {
    sideOpen.value = !sideOpen.value
    writeDetailsOpen(sideOpen.value)
  } else {
    drawerOpen.value = !drawerOpen.value
  }
}
// "Ver alterações" in an edit card opens the panel (the drawer on narrow screens).
watch(() => changesPanel.sessionId === props.id && changesPanel.edit != null, (open) => {
  if (!open) return
  if (wideScreen.value) sideOpen.value = true
  else drawerOpen.value = true
})
</script>

<template>
  <div class="relative flex h-full min-w-0">
    <div class="flex min-w-0 grow flex-col">
      <div class="flex min-h-12 items-center gap-2 border-b border-line px-4">
        <nav data-test="breadcrumb" aria-label="Trilha" class="flex min-w-0 grow items-center gap-2 text-sm text-fg-muted">
          <RouterLink to="/sessions" class="shrink-0 font-mono text-xs tracking-[0.08em] uppercase no-underline text-fg-muted hover:text-fg">Conversas</RouterLink>
          <template v-if="project">
            <span aria-hidden="true">›</span>
            <RouterLink :to="{ name: 'project', params: { id: project.id } }" class="flex shrink-0 items-center gap-1.5 no-underline text-fg-muted hover:text-fg">
              <span class="size-2 rounded-[3px]" :style="{ backgroundColor: project.color }" />{{ project.name }}
            </RouterLink>
          </template>
          <span aria-hidden="true">›</span>
          <span class="truncate text-fg">{{ title }}</span>
        </nav>
        <button
          v-if="!missing"
          type="button"
          data-test="toggle-details"
          :aria-pressed="wideScreen ? sideOpen : drawerOpen"
          aria-label="Mostrar ou esconder detalhes"
          class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
          @click="toggleDetails"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="15" y1="4" x2="15" y2="20" /></svg>
        </button>
      </div>
      <div v-if="missing" data-test="conversation-missing" class="flex flex-col items-start gap-3 px-6 py-10">
        <h1 class="m-0 text-xl font-semibold">Conversa não encontrada</h1>
        <p class="m-0 text-fg-muted">Ela pode ter sido apagada fora do app.</p>
        <RouterLink to="/sessions" class="text-primary-soft">Ver todas as conversas</RouterLink>
      </div>
      <template v-else>
        <ConversationHeader :id="id" />
        <ConversationThread :id="id" @missing="missing = true" />
      </template>
    </div>
    <DetailsPanel v-if="!missing && wideScreen && sideOpen" :session-id="id" />
    <div v-if="!missing && !wideScreen && drawerOpen" data-test="details-drawer" class="absolute inset-y-0 right-0 z-30 flex shadow-2xl">
      <DetailsPanel :session-id="id" drawer @close="drawerOpen = false" />
    </div>
  </div>
</template>
```

- [x] **Passo 6: rota e contexto no compositor**

Em `frontend/src/router/index.ts`, importar `ConversationView` e trocar a rota `session`:

```ts
  { path: '/sessions/:id', name: 'session', component: ConversationView, props: true },
```

Em `frontend/src/components/session/SessionControls.vue`, no `span` com `data-test="context-usage"` e no `span` `context-usage-sr`, trocar `v-if="context"` por `v-if="context && contextWarn"`.

- [x] **Passo 7: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/views/__tests__/ConversationView.spec.ts src/components/session/__tests__/SessionControls.spec.ts`
Expected: PASS.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa. `WorkspaceView.spec.ts` pode ter casos que navegam para `/sessions/:id` esperando colunas; esses casos agora falham porque a rota mudou. Remover esses casos (a tela de colunas sai de vez na Tarefa 12) e listar no relatório quais foram.

- [x] **Passo 8: commit**

```bash
git add frontend/src/detailsPanelPref.ts frontend/src/useMediaQuery.ts frontend/src/components/conversation/ConversationHeader.vue frontend/src/views/ConversationView.vue frontend/src/router/index.ts frontend/src/components/session/SessionControls.vue frontend/src/views/__tests__/ConversationView.spec.ts frontend/src/components/session/__tests__/SessionControls.spec.ts frontend/src/views/__tests__/WorkspaceView.spec.ts
git commit -m "[Feat] Abrir conversa em página única com painel Detalhes"
```

---

### Tarefa 7: Menu lateral novo e título da aba

**Arquivos:**
- Modificar: `frontend/src/components/sidebar/AppSidebar.vue` (reescrita)
- Modificar: `frontend/src/App.vue` (título da aba)
- Criar: `frontend/src/stores/newConversation.ts` (store mínimo; o modal vem na Tarefa 9)
- Testes: reescrever `frontend/src/components/sidebar/__tests__/AppSidebar.spec.ts` e `AppSidebarStates.spec.ts`; criar `frontend/src/__tests__/documentTitle.spec.ts`

**Interfaces:**
- Produz: `useNewConversationStore()` → `{ isOpen: Ref<boolean>, presetProjectId: Ref<number | null>, open(projectId?: number | null): void, close(): void }`.
- Produz: `documentTitle(waiting: number): string` em `frontend/src/documentTitle.ts` (`'Vini7 Vibing'` ou `'(N) Vini7 Vibing'`).
- `data-test` do menu: `nav-new`, `nav-dashboard`, `nav-inbox`, `inbox-count`, `nav-conversations`, `project`, `project-name`, `project-color`, `project-branch`, `project-waiting`, `new-project`, `recent`, `preferences`. O `SessionSearch` continua no menu, logo abaixo de "Nova conversa".

- [x] **Passo 1: testes (falham)**

Reescrever `frontend/src/components/sidebar/__tests__/AppSidebar.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AppSidebar from '../AppSidebar.vue'
import { createAppRouter } from '../../../router'
import { useGitStore } from '../../../stores/git'
import { useNewConversationStore } from '../../../stores/newConversation'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { makeGitRepo, makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

function mountSidebar() {
  const router = createAppRouter(createMemoryHistory())
  return mount(AppSidebar, { global: { plugins: [pinia, router] } })
}

describe('menu lateral', () => {
  it('tem as entradas fixas', () => {
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="nav-dashboard"]').attributes('href')).toBe('/dashboard')
    expect(wrapper.find('[data-test="nav-inbox"]').attributes('href')).toBe('/inbox')
    expect(wrapper.find('[data-test="nav-conversations"]').attributes('href')).toBe('/sessions')
    expect(wrapper.find('[data-test="preferences"]').attributes('href')).toBe('/preferencias')
    expect(wrapper.find('[data-test="new-project"]').attributes('href')).toBe('/projects/new')
  })

  it('conta na Inbox as conversas que aguardam você', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', display_state: 'waiting' }),
      makeSession({ session_id: 'b', display_state: 'waiting' }),
      makeSession({ session_id: 'c', display_state: 'running' }),
    ])
    expect(mountSidebar().find('[data-test="inbox-count"]').text()).toBe('2')
  })

  it('lista projetos com cor, branch e aguardando, sem conversas aninhadas', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
    useGitStore(pinia).set(1, [makeGitRepo({ branch: 'develop' })])
    useSessionsStore(pinia).setForProject(1, [makeSession({ display_state: 'waiting' })])

    const project = mountSidebar().find('[data-test="project"]')
    expect(project.attributes('href')).toBe('/projects/1')
    expect(project.find('[data-test="project-name"]').text()).toBe('loja-online')
    expect(project.find('[data-test="project-branch"]').text()).toContain('develop')
    expect(project.find('[data-test="project-waiting"]').text()).toContain('1')
    expect(mountSidebar().find('[data-test="session"]').exists()).toBe(false)
  })

  it('mostra as 5 conversas abertas mais recentemente', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 7 }, (_, i) =>
      makeSession({ session_id: `s${i}`, title: `T${i}`, last_seen_at: 1_790_000_000 + i }),
    ).concat([makeSession({ session_id: 'nunca', last_seen_at: null })]))

    const recent = mountSidebar().findAll('[data-test="recent"]')
    expect(recent.map((r) => r.text())).toEqual(['T6', 'T5', 'T4', 'T3', 'T2'])
    expect(recent[0]!.attributes('href')).toBe('/sessions/s6')
  })

  it('"Nova conversa" abre o modal', async () => {
    const wrapper = mountSidebar()
    await wrapper.find('[data-test="nav-new"]').trigger('click')
    expect(useNewConversationStore(pinia).isOpen).toBe(true)
  })
})
```

Em `AppSidebarStates.spec.ts`, remover os casos que dependem de conversas aninhadas nos projetos e da linha de ocultas; manter os que ainda valem (pasta indisponível, erro ao carregar projetos, "Nenhum projeto ainda", limite de repositórios), ajustando os seletores para o menu novo.

Criar `frontend/src/__tests__/documentTitle.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { documentTitle } from '../documentTitle'

describe('título da aba', () => {
  it('mostra o número de conversas aguardando', () => {
    expect(documentTitle(0)).toBe('Vini7 Vibing')
    expect(documentTitle(3)).toBe('(3) Vini7 Vibing')
  })
})
```

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/sidebar src/__tests__/documentTitle.spec.ts`
Expected: FAIL.

- [x] **Passo 3: store do modal e título**

Criar `frontend/src/stores/newConversation.ts`:

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

/** Whether the "Nova conversa" modal is open, and the project it should start on. */
export const useNewConversationStore = defineStore('newConversation', () => {
  const isOpen = ref(false)
  const presetProjectId = ref<number | null>(null)

  function open(projectId: number | null = null): void {
    presetProjectId.value = projectId
    isOpen.value = true
  }

  function close(): void {
    isOpen.value = false
  }

  return { isOpen, presetProjectId, open, close }
})
```

Criar `frontend/src/documentTitle.ts`:

```ts
/** Browser tab title with the number of conversations waiting for the user. */
export function documentTitle(waiting: number): string {
  return waiting > 0 ? `(${waiting}) Vini7 Vibing` : 'Vini7 Vibing'
}
```

Em `frontend/src/App.vue`, acrescentar ao `<script setup>`:

```ts
import { computed, watchEffect } from 'vue'
import { documentTitle } from './documentTitle'
import { useSessionsStore } from './stores/sessions'

const sessions = useSessionsStore()
const waiting = computed(() => sessions.all.filter((s) => s.display_state === 'waiting').length)
watchEffect(() => { document.title = documentTitle(waiting.value) })
```

(juntar com o import de `vue` que já existe).

- [x] **Passo 4: menu**

Reescrever `frontend/src/components/sidebar/AppSidebar.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import BrandMark from '../BrandMark.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import SessionSearch from './SessionSearch.vue'
import BranchLabel from '../git/BranchLabel.vue'
import { repoLabel, useGitStore } from '../../stores/git'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'

const projects = useProjectsStore()
const sessions = useSessionsStore()
const git = useGitStore()
const newConversation = useNewConversationStore()
const route = useRoute()

const waitingCount = computed(() => sessions.all.filter((s) => s.display_state === 'waiting').length)
function waitingIn(projectId: number): number {
  return sessions.forProject(projectId).filter((s) => s.display_state === 'waiting').length
}
const recent = computed(() =>
  sessions.all
    .filter((s) => s.last_seen_at != null)
    .sort((a, b) => (b.last_seen_at ?? 0) - (a.last_seen_at ?? 0))
    .slice(0, 5),
)
// The project being looked at, directly or through one of its conversations.
const activeProjectId = computed<number | null>(() => {
  if (route.name === 'project') return Number(route.params.id)
  if (route.name === 'session') return sessions.find(String(route.params.id))?.project_id ?? null
  return null
})
const currentProjectId = computed(() => activeProjectId.value)
const itemClass = (active: boolean) => [
  'flex min-h-10 items-center gap-2.5 rounded-lg px-3 no-underline hover:bg-card',
  active ? 'bg-elevated text-fg' : 'text-fg-muted hover:text-fg',
]
</script>

<template>
  <nav aria-label="Navegação" class="flex h-full w-64 shrink-0 flex-col gap-3 border-r border-line bg-panel px-3 pt-5 pb-3 text-sm">
    <RouterLink to="/inbox" class="flex min-h-11 items-center gap-2.5 rounded-lg px-2 text-fg no-underline">
      <BrandMark />
      <span class="text-xl font-bold tracking-tight">Vini7 Vibing</span>
    </RouterLink>

    <div class="flex flex-col gap-0.5">
      <button type="button" data-test="nav-new" :class="itemClass(false)" class="w-full text-left" @click="newConversation.open(currentProjectId)">
        <span aria-hidden="true">＋</span><span class="grow">Nova conversa</span><kbd class="font-mono text-[11px] text-fg-muted">C</kbd>
      </button>
      <SessionSearch />
      <RouterLink to="/dashboard" data-test="nav-dashboard" :class="itemClass(route.name === 'dashboard')" :aria-current="route.name === 'dashboard' ? 'page' : undefined">Dashboard</RouterLink>
      <RouterLink to="/inbox" data-test="nav-inbox" :class="itemClass(route.name === 'inbox')" :aria-current="route.name === 'inbox' ? 'page' : undefined">
        <span class="grow">Inbox</span>
        <span v-if="waitingCount" data-test="inbox-count" class="rounded-full bg-secondary px-2 text-xs font-semibold text-secondary-fg">{{ waitingCount }}</span>
      </RouterLink>
      <RouterLink to="/sessions" data-test="nav-conversations" :class="itemClass(route.name === 'sessions')" :aria-current="route.name === 'sessions' ? 'page' : undefined">Conversas</RouterLink>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <div class="flex items-center px-3 pt-2 pb-0.5">
        <span class="grow font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Projetos</span>
        <RouterLink to="/projects/new" data-test="new-project" aria-label="Novo projeto" class="flex size-7 items-center justify-center rounded-md text-fg-muted no-underline hover:bg-card hover:text-fg">＋</RouterLink>
      </div>
      <p v-if="projects.loadError" class="px-3 py-2 text-xs text-secondary-soft" role="alert">Não foi possível carregar os projetos. {{ projects.loadError }}</p>
      <p v-else-if="projects.loaded && projects.projects.length === 0" class="px-3 py-2 text-xs text-fg-muted">Nenhum projeto ainda.</p>
      <RouterLink
        v-for="project in projects.projects"
        :key="project.id"
        data-test="project"
        :data-available="String(project.available)"
        :to="{ name: 'project', params: { id: project.id } }"
        :class="[itemClass(activeProjectId === project.id), { 'opacity-50': !project.available }]"
        :aria-current="route.name === 'project' && activeProjectId === project.id ? 'page' : undefined"
      >
        <span data-test="project-color" class="size-2.5 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
        <span class="flex min-w-0 grow flex-col">
          <span data-test="project-name" class="truncate font-medium text-fg">{{ project.name }}</span>
          <span v-if="!project.available" class="text-xs">pasta indisponível</span>
          <span v-else-if="git.reposFor(project.id)[0]" data-test="project-branch"><BranchLabel :text="repoLabel(git.reposFor(project.id)[0]!)" muted /></span>
          <span v-if="git.limitReached(project.id)" data-test="repo-limit" class="text-xs text-secondary-soft">Só os 50 primeiros repositórios</span>
        </span>
        <span v-if="waitingIn(project.id)" data-test="project-waiting" class="flex items-center gap-1 text-xs text-secondary">
          <DisplayStateIcon display="waiting" :size="11" />{{ waitingIn(project.id) }}
        </span>
      </RouterLink>

      <template v-if="recent.length">
        <div class="px-3 pt-4 pb-0.5 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Recentes</div>
        <RouterLink
          v-for="session in recent"
          :key="session.session_id"
          data-test="recent"
          :to="{ name: 'session', params: { id: session.session_id } }"
          :class="itemClass(route.name === 'session' && route.params.id === session.session_id)"
        >
          <DisplayStateIcon :display="session.display_state" :size="11" />
          <span class="min-w-0 grow truncate text-[13px]">{{ session.title }}</span>
        </RouterLink>
      </template>
    </div>

    <RouterLink to="/preferencias" data-test="preferences" :class="itemClass(route.name === 'preferences')" :aria-current="route.name === 'preferences' ? 'page' : undefined">Preferências</RouterLink>
  </nav>
</template>
```

O teste "mostra as 5 conversas" espera que o texto do link seja só o título: o `DisplayStateIcon` tem `aria-hidden` e não contribui com texto.

Ajustar a rota `project` e as rotas novas em `frontend/src/router/index.ts`, acrescentando nomes que o menu usa e que ainda não existem, apontando para componentes provisórios até as Tarefas 8 e 10:

```ts
  { path: '/inbox', name: 'inbox', component: () => import('../views/HomeView.vue') },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/HomeView.vue') },
```

(As Tarefas 8 e 10 trocam esses componentes.)

- [x] **Passo 5: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/components/sidebar src/__tests__/documentTitle.spec.ts`
Expected: PASS.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa.

- [x] **Passo 6: commit**

```bash
git add frontend/src/components/sidebar frontend/src/App.vue frontend/src/stores/newConversation.ts frontend/src/documentTitle.ts frontend/src/__tests__/documentTitle.spec.ts frontend/src/router/index.ts
git commit -m "[Feat] Trocar menu lateral por entradas fixas, projetos e recentes"
```

---

### Tarefa 8: Inbox e Conversas

**Arquivos:**
- Criar: `frontend/src/components/FirstSteps.vue` (conteúdo de "sem projetos" do `HomeView`)
- Criar: `frontend/src/views/InboxView.vue`
- Criar: `frontend/src/views/ConversationsView.vue`
- Modificar: `frontend/src/router/index.ts` (`/inbox` → `InboxView`; `/sessions` → `ConversationsView`)
- Testes: `frontend/src/views/__tests__/InboxView.spec.ts`, `frontend/src/views/__tests__/ConversationsView.spec.ts`

**Interfaces:**
- Consome: `ConversationRow` (variant `inbox`/`list`), `INBOX_TABS`, `isInboxTab`, `inInbox`, `groupByDate` (Tarefa 3), `markSessionsSeen` (Tarefa 3), `useNewConversationStore` (Tarefa 7), `useGitStore().ensure`.
- URL da Inbox: `?aba=`; URL de Conversas: `?projeto=<id>&estado=ativas|finalizadas|todas&busca=<texto>`.
- `data-test`: `inbox-tab` (com `aria-selected`), `inbox-search`, `inbox-project`, `mark-all-read`, `inbox-error`, `date-group`, `empty`, `first-steps`, `conversations-new`, `conversations-search`, `conversations-project`, `conversations-state`, `show-more`.

- [x] **Passo 1: testes (falham)**

Criar `frontend/src/views/__tests__/InboxView.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import InboxView from '../InboxView.vue'
import { createAppRouter } from '../../router'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Date.now() / 1000

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 'w1', title: 'Espera 1', display_state: 'waiting', last_activity_at: now }),
    makeSession({ session_id: 'r1', title: 'Roda 1', display_state: 'running', unread: true, last_activity_at: now }),
  ])
  useSessionsStore(pinia).setForProject(2, [
    makeSession({ session_id: 'w2', project_id: 2, title: 'Espera 2', display_state: 'waiting', unread: true, last_activity_at: now - 3 * 86400 }),
    makeSession({ session_id: 'f2', project_id: 2, title: 'Feita', display_state: 'finished', unread: true, last_activity_at: now }),
  ])
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
    'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
  }))
})
afterEach(() => vi.unstubAllGlobals())

async function mountInbox(path = '/inbox') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(InboxView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}
const titles = (w: Awaited<ReturnType<typeof mountInbox>>['wrapper']) =>
  w.findAll('[data-test="row-link"]').map((r) => r.text())

describe('Inbox', () => {
  it('abre na aba Pede você, agrupada por data', async () => {
    const { wrapper } = await mountInbox()
    expect(titles(wrapper)).toEqual(['Espera 1', 'Espera 2'])
    expect(wrapper.findAll('[data-test="date-group"]').map((g) => g.text())).toEqual(['Hoje', 'Antes'])
  })

  it('troca de aba pela URL', async () => {
    const { wrapper, router } = await mountInbox()
    await wrapper.findAll('[data-test="inbox-tab"]')[2]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('em-execucao')
    expect(titles(wrapper)).toEqual(['Roda 1'])
  })

  it('filtra por projeto e por texto', async () => {
    const { wrapper } = await mountInbox('/inbox?aba=todas')
    await wrapper.find('[data-test="inbox-project"]').setValue('2')
    expect(titles(wrapper)).toEqual(['Espera 2'])
    await wrapper.find('[data-test="inbox-project"]').setValue('')
    await wrapper.find('[data-test="inbox-search"]').setValue('roda')
    expect(titles(wrapper)).toEqual(['Roda 1'])
  })

  it('marca como lidas as conversas da aba filtrada', async () => {
    const fetch = routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
      'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/seen': () => jsonResponse({ updated: 2 }),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountInbox('/inbox?aba=nao-lidas')

    await wrapper.find('[data-test="mark-all-read"]').trigger('click')
    await flushPromises()

    const call = fetch.mock.calls.find(([url]) => url === '/api/sessions/seen')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ session_ids: ['r1', 'w2'] })
  })

  it('mostra o erro de marcar todas sem mudar a lista', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
      'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/seen': () => jsonResponse({ detail: 'Falhou.' }, 500),
    }))
    const { wrapper } = await mountInbox('/inbox?aba=nao-lidas')
    await wrapper.find('[data-test="mark-all-read"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="inbox-error"]').text()).toContain('Falhou.')
    expect(titles(wrapper)).toEqual(['Roda 1', 'Espera 2'])
  })

  it('mostra o estado vazio de cada aba', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    useSessionsStore(pinia).setForProject(2, [])
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="empty"]').text()).toBe('Nada pedindo você agora.')
  })

  it('sem projetos mostra os primeiros passos', async () => {
    useProjectsStore(pinia).projects = []
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="first-steps"]').exists()).toBe(true)
  })
})
```

Criar `frontend/src/views/__tests__/ConversationsView.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationsView from '../ConversationsView.vue'
import { createAppRouter } from '../../router'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Date.now() / 1000

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
    'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
  }))
})
afterEach(() => vi.unstubAllGlobals())

async function mountList(path = '/sessions') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(ConversationsView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('Conversas', () => {
  it('lista todas por última atividade, com grupos de data', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Hoje', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Semana', last_activity_at: now - 3 * 86400, display_state: 'finished' }),
      makeSession({ session_id: 'c', title: 'Velha', last_activity_at: now - 30 * 86400 }),
    ])
    const { wrapper } = await mountList()

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Hoje', 'Semana', 'Velha'])
    expect(wrapper.findAll('[data-test="date-group"]').map((g) => g.text())).toEqual(['Hoje', 'Esta semana', 'Antes'])
  })

  it('filtra por estado e projeto, guardando na URL', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', title: 'Aberta', last_activity_at: now })])
    useSessionsStore(pinia).setForProject(2, [makeSession({ session_id: 'b', project_id: 2, title: 'Feita', display_state: 'finished', last_activity_at: now })])
    const { wrapper, router } = await mountList('/sessions?estado=finalizadas')

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Feita'])
    await wrapper.find('[data-test="conversations-state"]').setValue('todas')
    await wrapper.find('[data-test="conversations-project"]').setValue('1')
    await flushPromises()
    expect(router.currentRoute.value.query).toMatchObject({ estado: 'todas', projeto: '1' })
    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Aberta'])
  })

  it('mostra 100 por vez', async () => {
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 150 }, (_, i) =>
      makeSession({ session_id: `s${i}`, title: `T${i}`, last_activity_at: now - i }),
    ))
    const { wrapper } = await mountList()

    expect(wrapper.findAll('[data-test="conversation-row"]')).toHaveLength(100)
    await wrapper.find('[data-test="show-more"]').trigger('click')
    expect(wrapper.findAll('[data-test="conversation-row"]')).toHaveLength(150)
    expect(wrapper.find('[data-test="show-more"]').exists()).toBe(false)
  })

  it('"Nova conversa" abre o modal com o projeto filtrado', async () => {
    const { wrapper } = await mountList('/sessions?projeto=2')
    await wrapper.find('[data-test="conversations-new"]').trigger('click')
    const store = useNewConversationStore(pinia)
    expect(store.isOpen).toBe(true)
    expect(store.presetProjectId).toBe(2)
  })
})
```

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/views/__tests__/InboxView.spec.ts src/views/__tests__/ConversationsView.spec.ts`
Expected: FAIL.

- [x] **Passo 3: primeiros passos**

Criar `frontend/src/components/FirstSteps.vue` com o bloco `v-if="projects.loaded && projects.projects.length === 0"` do `HomeView.vue` (lista numerada e botão "Criar o primeiro projeto"), com `data-test="first-steps"` na raiz e o passo 2 dizendo "Abra uma nova conversa nesse projeto." O componente não verifica se há projetos; quem usa decide.

- [x] **Passo 4: Inbox**

Criar `frontend/src/views/InboxView.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import FirstSteps from '../components/FirstSteps.vue'
import { errorMessage, markSessionsSeen } from '../api/http'
import { INBOX_TABS, groupByDate, inInbox, isInboxTab, type InboxTab } from '../conversationList'
import { useGitStore } from '../stores/git'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'

const route = useRoute()
const router = useRouter()
const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()

const tab = computed<InboxTab>(() => (isInboxTab(route.query.aba) ? route.query.aba : 'pede-voce'))
function selectTab(id: InboxTab) {
  void router.replace({ query: { ...route.query, aba: id } })
}

const search = ref('')
const projectFilter = ref('')
const error = ref<string | null>(null)
const marking = ref(false)

const visible = computed(() => {
  const q = search.value.trim().toLocaleLowerCase('pt-BR')
  return sessions.all.filter((s) =>
    inInbox(s, tab.value)
    && (!projectFilter.value || s.project_id === Number(projectFilter.value))
    && (!q || s.title.toLocaleLowerCase('pt-BR').includes(q)),
  )
})
const groups = computed(() => groupByDate(visible.value, new Date(), false))
watch(() => projects.projects.map((p) => p.id), (ids) => ids.forEach((id) => git.ensure(id)), { immediate: true })

async function markAll() {
  const ids = visible.value.filter((s) => s.unread).map((s) => s.session_id)
  if (!ids.length || marking.value) return
  marking.value = true
  error.value = null
  try {
    await markSessionsSeen(ids)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    marking.value = false
  }
}
</script>

<template>
  <div class="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-6">
    <h1 class="m-0 font-mono text-sm tracking-[0.08em] text-fg uppercase">Inbox</h1>
    <FirstSteps v-if="projects.loaded && projects.projects.length === 0" />
    <template v-else>
      <div class="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="Filtro da Inbox" class="flex gap-1">
          <button
            v-for="t in INBOX_TABS"
            :key="t.id"
            type="button"
            role="tab"
            data-test="inbox-tab"
            :aria-selected="tab === t.id"
            class="h-9 border-b-2 px-3 text-sm"
            :class="tab === t.id ? 'border-fg text-fg' : 'border-transparent text-fg-muted hover:text-fg'"
            @click="selectTab(t.id)"
          >{{ t.label }}</button>
        </div>
        <span class="grow" />
        <input v-model="search" data-test="inbox-search" type="search" placeholder="Buscar na Inbox…" aria-label="Buscar na Inbox" class="h-9 w-56 rounded-md border border-line-strong bg-bg px-3 text-sm text-fg outline-none focus:border-primary" />
        <select v-model="projectFilter" data-test="inbox-project" aria-label="Projeto" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg">
          <option value="">Todos os projetos</option>
          <option v-for="p in projects.projects" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
        </select>
        <button type="button" data-test="mark-all-read" class="h-9 rounded-md border border-line-strong px-3 text-sm text-fg hover:bg-card disabled:opacity-40" :disabled="marking" @click="markAll">Marcar todas como lidas</button>
      </div>
      <p v-if="error" data-test="inbox-error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
      <p v-if="groups.length === 0" data-test="empty" class="m-0 py-10 text-center text-fg-muted">{{ tab === 'pede-voce' ? 'Nada pedindo você agora.' : 'Nenhuma conversa aqui.' }}</p>
      <section v-for="group in groups" :key="group.label" :aria-label="group.label" class="flex flex-col">
        <div class="flex items-center gap-3 py-2" aria-hidden="false">
          <span class="h-px grow bg-line" /><span data-test="date-group" class="font-mono text-[11px] tracking-[0.08em] text-fg-muted uppercase">{{ group.label }}</span><span class="h-px grow bg-line" />
        </div>
        <ConversationRow v-for="s in group.sessions" :key="s.session_id" :session="s" variant="inbox" @error="error = $event" />
      </section>
    </template>
  </div>
</template>
```

O rótulo do grupo está em maiúsculas só pelo CSS; o texto continua "Hoje", como o teste espera.

- [x] **Passo 5: Conversas**

Criar `frontend/src/views/ConversationsView.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import { groupByDate } from '../conversationList'
import { useGitStore } from '../stores/git'
import { useNewConversationStore } from '../stores/newConversation'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'

const PAGE = 100
type StateFilter = 'ativas' | 'finalizadas' | 'todas'

const route = useRoute()
const router = useRouter()
const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()
const newConversation = useNewConversationStore()

const text = (v: unknown) => (typeof v === 'string' ? v : '')
const state = computed<StateFilter>(() => {
  const v = text(route.query.estado)
  return v === 'ativas' || v === 'finalizadas' ? v : 'todas'
})
const projectId = computed(() => text(route.query.projeto))
const search = computed(() => text(route.query.busca))
function setQuery(key: string, value: string) {
  const query = { ...route.query, [key]: value || undefined }
  void router.replace({ query })
}

const error = ref<string | null>(null)
const limit = ref(PAGE)
watch(() => route.query, () => { limit.value = PAGE })

const filtered = computed(() => {
  const q = search.value.trim().toLocaleLowerCase('pt-BR')
  return sessions.all.filter((s) => {
    if (state.value === 'ativas' && s.display_state === 'finished') return false
    if (state.value === 'finalizadas' && s.display_state !== 'finished') return false
    if (projectId.value && s.project_id !== Number(projectId.value)) return false
    return !q || s.title.toLocaleLowerCase('pt-BR').includes(q)
  })
})
const groups = computed(() => groupByDate(filtered.value.slice(0, limit.value), new Date(), true))
watch(() => projects.projects.map((p) => p.id), (ids) => ids.forEach((id) => git.ensure(id)), { immediate: true })
</script>

<template>
  <div class="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-6">
    <h1 class="m-0 font-mono text-sm tracking-[0.08em] text-fg uppercase">Conversas</h1>
    <div class="flex flex-wrap items-center gap-3">
      <button type="button" data-test="conversations-new" class="h-9 rounded-md border border-line-strong px-3 text-sm font-medium text-fg hover:bg-card" @click="newConversation.open(projectId ? Number(projectId) : null)">＋ Nova conversa</button>
      <input :value="search" data-test="conversations-search" type="search" placeholder="Buscar conversas…" aria-label="Buscar conversas" class="h-9 w-64 rounded-md border border-line-strong bg-bg px-3 text-sm text-fg outline-none focus:border-primary" @input="setQuery('busca', ($event.target as HTMLInputElement).value)" />
      <span class="grow" />
      <select :value="projectId" data-test="conversations-project" aria-label="Projeto" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg" @change="setQuery('projeto', ($event.target as HTMLSelectElement).value)">
        <option value="">Todos os projetos</option>
        <option v-for="p in projects.projects" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
      </select>
      <select :value="state" data-test="conversations-state" aria-label="Estado" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg" @change="setQuery('estado', ($event.target as HTMLSelectElement).value)">
        <option value="todas">Todas</option>
        <option value="ativas">Ativas</option>
        <option value="finalizadas">Finalizadas</option>
      </select>
    </div>
    <p v-if="error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
    <p v-if="groups.length === 0" data-test="empty" class="m-0 py-10 text-center text-fg-muted">Nenhuma conversa aqui.</p>
    <section v-for="group in groups" :key="group.label" :aria-label="group.label" class="flex flex-col">
      <div class="flex items-center gap-3 py-2">
        <span class="h-px grow bg-line" /><span data-test="date-group" class="font-mono text-[11px] tracking-[0.08em] text-fg-muted uppercase">{{ group.label }}</span><span class="h-px grow bg-line" />
      </div>
      <ConversationRow v-for="s in group.sessions" :key="s.session_id" :session="s" @error="error = $event" />
    </section>
    <button v-if="filtered.length > limit" type="button" data-test="show-more" class="h-10 self-center rounded-md border border-line-strong px-4 text-sm text-fg hover:bg-card" @click="limit += PAGE">Mostrar mais</button>
  </div>
</template>
```

Em `frontend/src/router/index.ts`: importar `InboxView` e `ConversationsView`; a rota `inbox` passa a `component: InboxView` e a rota `sessions` passa a `component: ConversationsView` (substituindo `AllSessionsView`).

- [x] **Passo 6: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/views/__tests__/InboxView.spec.ts src/views/__tests__/ConversationsView.spec.ts`
Expected: PASS.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa. `AllSessionsView.spec.ts` monta o componente direto e continua passando; ele é removido na Tarefa 12.

- [x] **Passo 7: commit**

```bash
git add frontend/src/components/FirstSteps.vue frontend/src/views/InboxView.vue frontend/src/views/ConversationsView.vue frontend/src/router/index.ts frontend/src/views/__tests__/InboxView.spec.ts frontend/src/views/__tests__/ConversationsView.spec.ts
git commit -m "[Feat] Adicionar telas de Inbox e Conversas"
```

---

### Tarefa 9: Modal de nova conversa

**Arquivos:**
- Criar: `frontend/src/sessionOptions.ts` (rótulos de raciocínio e modo, extraídos do `SessionControls`)
- Modificar: `frontend/src/components/session/SessionControls.vue` (importar os rótulos)
- Criar: `frontend/src/conversation/pendingDrafts.ts`
- Modificar: `frontend/src/components/conversation/MessageComposer.vue` (começa com o rascunho pendente)
- Criar: `frontend/src/newConversationDraft.ts`
- Criar: `frontend/src/components/NewConversationModal.vue`
- Modificar: `frontend/src/App.vue` (monta o modal e o atalho `C`)
- Modificar: `frontend/src/views/ProjectView.vue` ("Nova sessão" abre o modal)
- Testes: `frontend/src/components/__tests__/NewConversationModal.spec.ts`, `frontend/src/__tests__/newConversationShortcut.spec.ts`; ajuste em `frontend/src/views/__tests__/ProjectView.spec.ts`

**Interfaces:**
- Consome: `useNewConversationStore` (Tarefa 7), `useSessionsStore().create`, `updateSession`, `sendMessage`, `readImage`, `imageProblem`, `base64Of`, `MAX_IMAGES`, `MAX_TOTAL_BYTES`, `filesFrom` (`conversation/images`), `OptionMenu`, `useModelsStore`.
- Produz: `EFFORT_LABELS`, `MODE_LABELS`, `ALL_EFFORTS`, `modeLabel(m: string)` em `sessionOptions.ts`.
- Produz: `setPendingDraft(sessionId: string, draft: { text: string; error: string | null }): void`, `takePendingDraft(sessionId: string): { text: string; error: string | null } | null`.
- Produz: `interface ConversationDraft { projectId: number | null; title: string; prompt: string; model: string | null; effort: Effort | null; permissionMode: PermissionMode | null }`, `loadDraft(): ConversationDraft`, `saveDraft(d: ConversationDraft): void`, `clearDraft(): void` (chave `vibing:new-conversation`, try/catch).
- Produz: `shouldOpenNewConversation(event: KeyboardEvent): boolean` em `frontend/src/newConversationShortcut.ts`.
- `data-test`: `new-conversation-modal`, `nc-project`, `nc-title`, `nc-prompt`, `nc-submit`, `nc-discard`, `nc-close`, `nc-error`, `nc-no-projects`.

- [x] **Passo 1: testes (falham)**

Criar `frontend/src/components/__tests__/NewConversationModal.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NewConversationModal from '../NewConversationModal.vue'
import { createAppRouter } from '../../router'
import { takePendingDraft } from '../../conversation/pendingDrafts'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [
    makeProject({ id: 1, name: 'a' }),
    makeProject({ id: 2, name: 'b', path: '/b' }),
    makeProject({ id: 3, name: 'sumiu', path: '/c', available: false }),
  ]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

function handlers(extra = {}) {
  return {
    'GET /api/models': () => jsonResponse([]),
    'POST /api/projects/2/sessions': () => jsonResponse(makeSession({ session_id: 'nova', project_id: 2 }), 201),
    'POST /api/sessions/nova/messages': () => jsonResponse({ state: 'running', external_activity: false }, 202),
    'PATCH /api/sessions/nova': () => jsonResponse(makeSession({ session_id: 'nova', project_id: 2 })),
    ...extra,
  }
}

async function openModal(preset: number | null = 2, extra = {}) {
  const fetch = routeFetch(handlers(extra))
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/inbox')
  useNewConversationStore(pinia).open(preset)
  const wrapper = mount(NewConversationModal, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, router, fetch }
}

describe('modal de nova conversa', () => {
  it('começa no projeto pedido e só lista projetos disponíveis', async () => {
    const { wrapper } = await openModal(2)
    const select = wrapper.find('[data-test="nc-project"]')
    expect((select.element as HTMLSelectElement).value).toBe('2')
    expect(select.findAll('option').map((o) => o.text())).toEqual(['a', 'b'])
  })

  it('cria a sessão, envia o prompt e abre a conversa', async () => {
    const { wrapper, router, fetch } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('Corrija o login')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    const send = fetch.mock.calls.find(([url]) => url === '/api/sessions/nova/messages')!
    expect(JSON.parse(send[1]!.body as string)).toEqual({ text: 'Corrija o login' })
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
    expect(useNewConversationStore(pinia).isOpen).toBe(false)
    expect(localStorage.getItem('vibing:new-conversation')).toBeNull()
  })

  it('envia título quando preenchido', async () => {
    const { wrapper, fetch } = await openModal(2)
    await wrapper.find('[data-test="nc-title"]').setValue('Login')
    await wrapper.find('[data-test="nc-prompt"]').setValue('Corrija')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    const patch = fetch.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(patch[1]!.body as string)).toEqual({ title: 'Login' })
  })

  it('Enter inicia e Ctrl+Enter quebra linha', async () => {
    const { wrapper, fetch } = await openModal(2)
    const prompt = wrapper.find('[data-test="nc-prompt"]')
    await prompt.setValue('linha 1')
    await prompt.trigger('keydown', { key: 'Enter', ctrlKey: true })
    expect((prompt.element as HTMLTextAreaElement).value).toBe('linha 1\n')
    await prompt.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(fetch.mock.calls.some(([url]) => url === '/api/projects/2/sessions')).toBe(true)
  })

  it('não cria duas sessões com dois envios seguidos', async () => {
    const { wrapper, fetch } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await wrapper.find('[data-test="nc-prompt"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(fetch.mock.calls.filter(([url]) => url === '/api/projects/2/sessions')).toHaveLength(1)
  })

  it('mantém o rascunho quando a criação falha', async () => {
    const { wrapper } = await openModal(2, {
      'POST /api/projects/2/sessions': () => jsonResponse({ detail: 'Pasta indisponível.' }, 409),
    })
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="nc-error"]').text()).toContain('Pasta indisponível.')
    expect((wrapper.find('[data-test="nc-prompt"]').element as HTMLTextAreaElement).value).toBe('oi')
    expect(useNewConversationStore(pinia).isOpen).toBe(true)
  })

  it('abre a conversa com o prompt no compositor quando o envio falha', async () => {
    const { wrapper, router } = await openModal(2, {
      'POST /api/sessions/nova/messages': () => jsonResponse({ detail: 'Sem conexão.' }, 503),
    })
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
    expect(takePendingDraft('nova')).toEqual({ text: 'oi', error: 'Sem conexão.' })
  })

  it('guarda o rascunho ao fechar e restaura ao abrir', async () => {
    const first = await openModal(2)
    await first.wrapper.find('[data-test="nc-prompt"]').setValue('rascunho')
    await first.wrapper.find('[data-test="nc-close"]').trigger('click')
    first.wrapper.unmount()

    const second = await openModal(null)
    expect((second.wrapper.find('[data-test="nc-prompt"]').element as HTMLTextAreaElement).value).toBe('rascunho')
    expect((second.wrapper.find('[data-test="nc-project"]').element as HTMLSelectElement).value).toBe('2')
  })

  it('rascunho com projeto removido cai no projeto padrão', async () => {
    localStorage.setItem('vibing:new-conversation', JSON.stringify({ projectId: 99, title: '', prompt: 'x', model: null, effort: null, permissionMode: null }))
    const { wrapper } = await openModal(null)
    expect((wrapper.find('[data-test="nc-project"]').element as HTMLSelectElement).value).toBe('1')
  })

  it('descartar limpa o rascunho', async () => {
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('lixo')
    await wrapper.find('[data-test="nc-discard"]').trigger('click')
    expect(localStorage.getItem('vibing:new-conversation')).toBeNull()
    expect(useNewConversationStore(pinia).isOpen).toBe(false)
  })

  it('funciona sem localStorage', async () => {
    vi.stubGlobal('localStorage', { getItem() { throw new Error('x') }, setItem() { throw new Error('x') }, removeItem() { throw new Error('x') }, clear() {} })
    const { wrapper, router } = await openModal(2)
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
  })

  it('sem projetos pede para cadastrar um', async () => {
    useProjectsStore(pinia).projects = []
    const { wrapper } = await openModal(null)
    expect(wrapper.find('[data-test="nc-no-projects"] a').attributes('href')).toBe('/projects/new')
  })
})
```

Criar `frontend/src/__tests__/newConversationShortcut.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { shouldOpenNewConversation } from '../newConversationShortcut'

function key(init: KeyboardEventInit, target: HTMLElement = document.body) {
  const event = new KeyboardEvent('keydown', init)
  Object.defineProperty(event, 'target', { value: target })
  return event
}

describe('atalho C', () => {
  it('abre com C fora de campos de texto', () => {
    expect(shouldOpenNewConversation(key({ key: 'c' }))).toBe(true)
    expect(shouldOpenNewConversation(key({ key: 'C', shiftKey: true }))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c', ctrlKey: true }))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c' }, document.createElement('textarea')))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c' }, document.createElement('input')))).toBe(false)
    const editable = document.createElement('div')
    editable.contentEditable = 'true'
    expect(shouldOpenNewConversation(key({ key: 'c' }, editable))).toBe(false)
  })
})
```

Em `frontend/src/views/__tests__/ProjectView.spec.ts`, trocar o teste de "Nova sessão" (que esperava `POST /api/projects/1/sessions` e navegação) por: clicar em "Nova sessão" deixa `useNewConversationStore().isOpen` verdadeiro com `presetProjectId` igual ao id do projeto, sem chamada de criação.

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/__tests__/NewConversationModal.spec.ts src/__tests__/newConversationShortcut.spec.ts src/views/__tests__/ProjectView.spec.ts`
Expected: FAIL.

- [x] **Passo 3: módulos de apoio**

Criar `frontend/src/sessionOptions.ts` movendo de `SessionControls.vue` as constantes `EFFORT_LABELS`, `ALL_EFFORTS`, `MODE_LABELS` e a função `modeLabel`, exportadas; em `SessionControls.vue`, importar de `../../sessionOptions` e apagar as cópias locais.

Criar `frontend/src/conversation/pendingDrafts.ts`:

```ts
export interface PendingDraft {
  text: string
  error: string | null
}

// Text to put in a composer that opens next: a first prompt that could not be sent.
const drafts = new Map<string, PendingDraft>()

export function setPendingDraft(sessionId: string, draft: PendingDraft): void {
  drafts.set(sessionId, draft)
}

/** The draft for this session, removed on read (it fills one composer once). */
export function takePendingDraft(sessionId: string): PendingDraft | null {
  const draft = drafts.get(sessionId) ?? null
  drafts.delete(sessionId)
  return draft
}
```

Em `MessageComposer.vue`, importar `takePendingDraft` e trocar as duas declarações:

```ts
const pendingDraft = takePendingDraft(props.sessionId)
const text = ref(pendingDraft?.text ?? '')
```

e

```ts
const error = ref<string | null>(pendingDraft?.error ?? null)
```

Criar `frontend/src/newConversationDraft.ts`:

```ts
import type { Effort, PermissionMode } from './types/api'

const KEY = 'vibing:new-conversation'

export interface ConversationDraft {
  projectId: number | null
  title: string
  prompt: string
  model: string | null
  effort: Effort | null
  permissionMode: PermissionMode | null
}

export function emptyDraft(): ConversationDraft {
  return { projectId: null, title: '', prompt: '', model: null, effort: null, permissionMode: null }
}

/** The saved draft, or an empty one when there is none, it is invalid or storage fails. */
export function loadDraft(): ConversationDraft {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return emptyDraft()
    const value = JSON.parse(raw) as Partial<ConversationDraft>
    return {
      projectId: typeof value.projectId === 'number' ? value.projectId : null,
      title: typeof value.title === 'string' ? value.title : '',
      prompt: typeof value.prompt === 'string' ? value.prompt : '',
      model: typeof value.model === 'string' ? value.model : null,
      effort: (value.effort ?? null) as Effort | null,
      permissionMode: (value.permissionMode ?? null) as PermissionMode | null,
    }
  } catch {
    return emptyDraft()
  }
}

export function saveDraft(draft: ConversationDraft): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(draft))
  } catch {
    // Without storage the draft lives only while the page is open.
  }
}

export function clearDraft(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // Nothing to clear.
  }
}
```

Criar `frontend/src/newConversationShortcut.ts`:

```ts
/** "C" alone, outside any text field, opens the new conversation modal. */
export function shouldOpenNewConversation(event: KeyboardEvent): boolean {
  if (event.key !== 'c' || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return false
  const target = event.target as HTMLElement | null
  if (!target) return true
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return false
  return !target.isContentEditable && target.getAttribute?.('contenteditable') !== 'true'
}
```

- [x] **Passo 4: modal**

Criar `frontend/src/components/NewConversationModal.vue`:

```vue
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import OptionMenu, { type MenuOption } from './session/OptionMenu.vue'
import { errorMessage, sendMessage, updateSession } from '../api/http'
import { type DraftImage, MAX_IMAGES, MAX_TOTAL_BYTES, base64Of, filesFrom, imageProblem, readImage } from '../conversation/images'
import { setPendingDraft } from '../conversation/pendingDrafts'
import { clearDraft, loadDraft, saveDraft, type ConversationDraft } from '../newConversationDraft'
import { ALL_EFFORTS, EFFORT_LABELS, MODE_LABELS } from '../sessionOptions'
import { useModelsStore } from '../stores/models'
import { useNewConversationStore } from '../stores/newConversation'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import type { Effort, PermissionMode, SessionUpdate } from '../types/api'

const store = useNewConversationStore()
const projects = useProjectsStore()
const sessions = useSessionsStore()
const models = useModelsStore()
const router = useRouter()
void models.ensure()

const available = computed(() => projects.projects.filter((p) => p.available))
const draft = ref<ConversationDraft>(loadDraft())
const images = ref<DraftImage[]>([])
const error = ref<string | null>(null)
const submitting = ref(false)
const fullscreen = ref(false)
const promptEl = ref<HTMLTextAreaElement | null>(null)

// The project: the one asked for, else the draft's, else the first available. Never one that is gone.
function pickProject() {
  const ids = available.value.map((p) => p.id)
  const wanted = [store.presetProjectId, draft.value.projectId].find((id) => id != null && ids.includes(id))
  draft.value.projectId = wanted ?? ids[0] ?? null
}
onMounted(async () => {
  pickProject()
  await nextTick()
  promptEl.value?.focus()
})
watch(draft, (value) => saveDraft(value), { deep: true })

const modelOptions = computed<MenuOption[]>(() => [
  { value: 'default', label: 'Padrão' },
  ...models.models.map((m) => ({ value: m.value, label: m.displayName, description: m.description })),
])
const modelText = computed(() => models.models.find((m) => m.value === draft.value.model)?.displayName ?? 'Padrão')
const effortOptions = computed<MenuOption[]>(() => [
  { value: 'default', label: 'Padrão' },
  ...ALL_EFFORTS.map((e) => ({ value: e, label: EFFORT_LABELS[e] })),
])
// "Sem perguntas" needs a confirmation: it is only offered inside the conversation.
const modeOptions: MenuOption[] = [
  { value: 'default-account', label: 'Padrão da conta' },
  ...(Object.keys(MODE_LABELS) as PermissionMode[]).filter((m) => m !== 'bypassPermissions').map((m) => ({ value: m, label: MODE_LABELS[m] })),
]

const canSubmit = computed(() => !submitting.value && draft.value.projectId != null && (draft.value.prompt.trim() !== '' || images.value.length > 0))

async function addFiles(files: File[]) {
  let total = images.value.reduce((sum, i) => sum + i.size, 0)
  for (const file of files) {
    const problem = imageProblem(file)
    if (problem) { error.value = problem; continue }
    if (images.value.length >= MAX_IMAGES || total + file.size > MAX_TOTAL_BYTES) { error.value = 'Imagens demais para uma mensagem.'; break }
    total += file.size
    images.value.push(await readImage(file))
  }
}
function onPaste(event: ClipboardEvent) {
  const files = filesFrom(event.clipboardData)
  if (!files.length) return
  event.preventDefault()
  void addFiles(files)
}

function onPromptKey(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.isComposing) return
  event.preventDefault()
  if (event.ctrlKey || event.metaKey || event.altKey) {
    const el = event.target as HTMLTextAreaElement
    const start = el.selectionStart ?? draft.value.prompt.length
    const end = el.selectionEnd ?? start
    draft.value.prompt = draft.value.prompt.slice(0, start) + '\n' + draft.value.prompt.slice(end)
    void nextTick(() => el.setSelectionRange(start + 1, start + 1))
  } else {
    void submit()
  }
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = null
  const { projectId, title, prompt, model, effort, permissionMode } = draft.value
  let sessionId: string
  try {
    sessionId = (await sessions.create(projectId!)).session_id
  } catch (e) {
    error.value = errorMessage(e)
    submitting.value = false
    return
  }
  try {
    const changes: SessionUpdate = {}
    if (title.trim()) changes.title = title.trim()
    if (model) changes.model = model
    if (effort) changes.effort = effort
    if (permissionMode) changes.permission_mode = permissionMode
    if (Object.keys(changes).length) await updateSession(sessionId, changes)
    await sendMessage(sessionId, prompt, images.value.map((i) => ({ media_type: i.mediaType, data: base64Of(i) })))
  } catch (e) {
    // The session exists: open it with the prompt waiting in its composer.
    setPendingDraft(sessionId, { text: prompt, error: errorMessage(e) })
  }
  finish()
  await router.push({ name: 'session', params: { id: sessionId } })
}

// Clears the saved draft and closes. The draft ref is left as is: changing it
// would make the watcher save it again. The next opening mounts a fresh modal.
function finish() {
  clearDraft()
  submitting.value = false
  store.close()
}
function discard() {
  finish()
}
function close() {
  store.close()
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @keydown.esc.prevent="close" @click.self="close">
    <div
      data-test="new-conversation-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="nc-heading"
      class="flex max-h-full w-full flex-col rounded-xl border border-line-strong bg-panel shadow-2xl"
      :class="fullscreen ? 'h-full max-w-none' : 'max-w-2xl'"
    >
      <header class="flex items-center gap-2 border-b border-line px-5 py-3">
        <h2 id="nc-heading" class="m-0 grow text-base font-semibold">Nova conversa</h2>
        <button type="button" :aria-label="fullscreen ? 'Sair da tela cheia' : 'Tela cheia'" class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card" @click="fullscreen = !fullscreen">⤢</button>
        <button type="button" data-test="nc-close" aria-label="Fechar" class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card" @click="close">×</button>
      </header>

      <div v-if="available.length === 0" data-test="nc-no-projects" class="flex flex-col gap-3 px-5 py-6">
        <p class="m-0">Cadastre um projeto antes de iniciar uma conversa.</p>
        <RouterLink to="/projects/new" class="text-primary-soft" @click="close">Cadastrar projeto</RouterLink>
      </div>
      <template v-else>
        <div class="flex min-h-0 grow flex-col gap-3 overflow-y-auto px-5 py-4">
          <label class="flex items-center gap-2 text-sm text-fg-muted">
            em
            <select v-model.number="draft.projectId" data-test="nc-project" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg">
              <option v-for="p in available" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <input v-model="draft.title" data-test="nc-title" placeholder="Título (opcional)" aria-label="Título (opcional)" maxlength="200" class="h-10 rounded-md border border-line-strong bg-bg px-3 text-base font-semibold text-fg outline-none focus:border-primary" />
          <textarea
            ref="promptEl"
            v-model="draft.prompt"
            data-test="nc-prompt"
            aria-label="Prompt"
            placeholder="O que você quer fazer? (Ctrl+V cola imagens)"
            class="min-h-40 grow resize-none rounded-md border border-line-strong bg-bg px-3 py-2 text-sm leading-relaxed text-fg outline-none focus:border-primary"
            @keydown="onPromptKey"
            @paste="onPaste"
          />
          <p v-if="images.length" class="m-0 text-xs text-fg-muted">{{ images.length }} {{ images.length === 1 ? 'imagem anexada' : 'imagens anexadas' }}</p>
          <div class="flex flex-wrap items-center gap-2">
            <OptionMenu name="Modelo" :text="modelText" :options="modelOptions" :selected="draft.model ?? 'default'" @select="(v) => (draft.model = v === 'default' ? null : v)" />
            <OptionMenu name="Raciocínio" :text="`Raciocínio ${draft.effort ? EFFORT_LABELS[draft.effort] : 'padrão'}`" :options="effortOptions" :selected="draft.effort ?? 'default'" @select="(v) => (draft.effort = v === 'default' ? null : (v as Effort))" />
            <OptionMenu name="Modo" :text="draft.permissionMode ? MODE_LABELS[draft.permissionMode] : 'Modo padrão'" :options="modeOptions" :selected="draft.permissionMode ?? 'default-account'" @select="(v) => (draft.permissionMode = v === 'default-account' ? null : (v as PermissionMode))" />
          </div>
          <p v-if="error" data-test="nc-error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
        </div>
        <footer class="flex items-center gap-3 border-t border-line px-5 py-3">
          <button type="button" data-test="nc-discard" class="h-10 rounded-md px-3 text-sm text-fg-muted hover:text-fg" @click="discard">Descartar rascunho</button>
          <span class="grow" />
          <button type="button" data-test="nc-submit" class="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-fg hover:bg-primary-soft disabled:opacity-40" :disabled="!canSubmit" @click="submit">{{ submitting ? 'Iniciando…' : 'Iniciar conversa' }}</button>
        </footer>
      </template>
    </div>
  </div>
</template>
```

- [x] **Passo 5: montar o modal, atalho e página do projeto**

Em `frontend/src/App.vue`:

```ts
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import NewConversationModal from './components/NewConversationModal.vue'
import { shouldOpenNewConversation } from './newConversationShortcut'
import { useNewConversationStore } from './stores/newConversation'

const newConversation = useNewConversationStore()
const route = useRoute()
// The project in view: a project page, or the project of the open conversation.
function currentProjectId(): number | null {
  if (route.name === 'project') return Number(route.params.id)
  if (route.name === 'session') return sessions.find(String(route.params.id))?.project_id ?? null
  return null
}
function onKey(event: KeyboardEvent) {
  if (newConversation.isOpen || !shouldOpenNewConversation(event)) return
  event.preventDefault()
  newConversation.open(currentProjectId())
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
```

(juntar com os imports existentes) e no template, dentro da raiz, depois do `<main>`:

```vue
    <NewConversationModal v-if="newConversation.isOpen" />
```

Em `frontend/src/views/ProjectView.vue`, importar `useNewConversationStore` e trocar o corpo de `newSession()` por:

```ts
function newSession(): void {
  if (!project.value?.available) return
  useNewConversationStore().open(props.id)
}
```

apagando `creating` se ficar sem uso (e o `:disabled="creating"` do botão).

- [x] **Passo 6: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/components/__tests__/NewConversationModal.spec.ts src/__tests__/newConversationShortcut.spec.ts src/views/__tests__/ProjectView.spec.ts src/components/session/__tests__/SessionControls.spec.ts`
Expected: PASS.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa.

- [x] **Passo 7: commit**

```bash
git add frontend/src/sessionOptions.ts frontend/src/components/session/SessionControls.vue frontend/src/conversation/pendingDrafts.ts frontend/src/components/conversation/MessageComposer.vue frontend/src/newConversationDraft.ts frontend/src/newConversationShortcut.ts frontend/src/components/NewConversationModal.vue frontend/src/App.vue frontend/src/views/ProjectView.vue frontend/src/components/__tests__/NewConversationModal.spec.ts frontend/src/__tests__/newConversationShortcut.spec.ts frontend/src/views/__tests__/ProjectView.spec.ts
git commit -m "[Feat] Adicionar modal de nova conversa com rascunho e atalho C"
```

---

### Tarefa 10: Dashboard

**Arquivos:**
- Criar: `frontend/src/conversation/pendingDecision.ts`
- Criar: `frontend/src/components/dashboard/ActivityChart.vue`
- Criar: `frontend/src/views/DashboardView.vue`
- Modificar: `frontend/src/router/index.ts` (`/dashboard` → `DashboardView`)
- Testes: `frontend/src/components/dashboard/__tests__/ActivityChart.spec.ts`, `frontend/src/views/__tests__/DashboardView.spec.ts`

**Interfaces:**
- Consome: `getActivity` (Tarefa 3), `answerPrompt`, `ApiError`, `waitingReason`, `ConversationRow` (variant `compact`), `changedCount` (`stores/git`).
- Produz: `usePendingDecision(session: () => Session)` → `{ pending: ComputedRef<PendingPermission | null>, sending: Ref<PromptDecision | null>, answered: ComputedRef<boolean>, error: Ref<string | null>, decide(d: PromptDecision): Promise<void> }` (mesma regra do `SessionRow`: 409 conta como respondido).
- Produz: `ActivityChart.vue` props `{ data: ActivityDay[]; projects: Project[]; days: number; today: Date }`.
- `data-test`: `now-card`, `now-empty`, `now-allow`, `now-deny`, `stat-running`, `stat-waiting`, `stat-finished-today`, `stat-projects-changes`, `activity-chart`, `activity-bar`, `activity-empty`, `activity-error`, `activity-retry`, `recent-list`, `projects-list`.

- [x] **Passo 1: testes (falham)**

Criar `frontend/src/components/dashboard/__tests__/ActivityChart.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ActivityChart from '../ActivityChart.vue'
import { makeProject } from '../../../test/factories'

const projects = [makeProject({ id: 1, name: 'a', color: '#ff0000' }), makeProject({ id: 2, name: 'b', color: '#00ff00' })]
const today = new Date(2026, 8, 29, 15)

describe('gráfico de atividade', () => {
  it('empilha as barras por projeto em cada dia', () => {
    const wrapper = mount(ActivityChart, { props: { projects, days: 14, today, data: [
      { date: '2026-09-29', project_id: 1, sessions: 2 },
      { date: '2026-09-29', project_id: 2, sessions: 1 },
      { date: '2026-09-20', project_id: 1, sessions: 1 },
    ] } })

    const bars = wrapper.findAll('[data-test="activity-bar"]')
    expect(bars).toHaveLength(3)
    const last = bars.filter((b) => b.attributes('data-date') === '2026-09-29')
    expect(last.map((b) => b.attributes('fill'))).toEqual(['#ff0000', '#00ff00'])
    expect(wrapper.find('table').text()).toContain('29/09')
  })

  it('mostra o estado vazio', () => {
    const wrapper = mount(ActivityChart, { props: { projects, days: 14, today, data: [] } })
    expect(wrapper.find('[data-test="activity-empty"]').text()).toBe('Nenhuma atividade nos últimos 14 dias.')
  })
})
```

Criar `frontend/src/views/__tests__/DashboardView.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import DashboardView from '../DashboardView.vue'
import { createAppRouter } from '../../router'
import { useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeGitRepo, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Math.floor(Date.now() / 1000)

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ changed: { staged: 0, unstaged: 2, untracked: 1 } })])
  useGitStore(pinia).set(2, [makeGitRepo({ path: '/b' })])
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 'r', title: 'Rodando', display_state: 'running', state: 'running', last_action: 'Edit main.py', last_activity_at: now }),
    makeSession({
      session_id: 'w', title: 'Pede', display_state: 'waiting', state: 'awaiting_decision', awaiting_decision: true,
      pending_kind: 'tool', pending_permission: { prompt_id: 'p1', tool_name: 'Bash', summary: 'ls', can_allow_always: false },
      last_activity_at: now,
    }),
    makeSession({ session_id: 'f', title: 'Feita', display_state: 'finished', finished: true, finished_at: now, last_activity_at: now }),
    makeSession({ session_id: 'old', title: 'Ontem', display_state: 'finished', finished: true, finished_at: now - 2 * 86400, last_activity_at: now - 2 * 86400 }),
  ])
})
afterEach(() => vi.unstubAllGlobals())

async function mountDashboard(activity: () => Response = () => jsonResponse([])) {
  const fetch = routeFetch({
    'GET /api/activity?days=14': activity,
    'POST /api/sessions/w/prompts/p1': () => jsonResponse(undefined, 204),
  })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  const wrapper = mount(DashboardView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch }
}

describe('Dashboard', () => {
  it('mostra cartões das conversas ativas com a última ação', async () => {
    const { wrapper } = await mountDashboard()
    const cards = wrapper.findAll('[data-test="now-card"]')
    expect(cards.map((c) => c.find('a').text())).toEqual(['Rodando', 'Pede'])
    expect(cards[0]!.text()).toContain('Edit main.py')
    expect(cards[1]!.text()).toContain('Pede permissão: Bash')
  })

  it('permite pelo cartão', async () => {
    const { wrapper, fetch } = await mountDashboard()
    await wrapper.find('[data-test="now-allow"]').trigger('click')
    await flushPromises()
    const call = fetch.mock.calls.find(([url]) => url === '/api/sessions/w/prompts/p1')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ decision: 'allow_once' })
  })

  it('mostra os números com links', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="stat-running"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-running"]').attributes('href')).toBe('/inbox?aba=em-execucao')
    expect(wrapper.find('[data-test="stat-waiting"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-finished-today"]').text()).toContain('1')
    expect(wrapper.find('[data-test="stat-finished-today"]').attributes('href')).toBe('/sessions?estado=finalizadas')
    expect(wrapper.find('[data-test="stat-projects-changes"]').text()).toContain('1')
  })

  it('falha do gráfico não derruba o resto e pode tentar de novo', async () => {
    let calls = 0
    const { wrapper } = await mountDashboard(() => (++calls === 1 ? jsonResponse({ detail: 'x' }, 500) : jsonResponse([])))

    expect(wrapper.find('[data-test="activity-error"]').text()).toContain('Não foi possível carregar a atividade')
    expect(wrapper.findAll('[data-test="now-card"]')).toHaveLength(2)
    await wrapper.find('[data-test="activity-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="activity-empty"]').exists()).toBe(true)
  })

  it('lista conversas recentes e projetos', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.findAll('[data-test="recent-list"] [data-test="conversation-row"]').length).toBeLessThanOrEqual(8)
    expect(wrapper.find('[data-test="projects-list"]').text()).toContain('3 arquivos')
  })

  it('sem conversas ativas mostra o aviso', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('[data-test="now-empty"]').text()).toBe('Nenhuma conversa ativa agora.')
  })
})
```

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/dashboard src/views/__tests__/DashboardView.spec.ts`
Expected: FAIL.

- [x] **Passo 3: decisão fora da conversa**

Criar `frontend/src/conversation/pendingDecision.ts`:

```ts
import { computed, ref } from 'vue'
import { ApiError, answerPrompt, errorMessage } from '../api/http'
import type { Session } from '../types/api'
import type { PromptDecision } from '../types/conversation'

/** Allow or deny a session's pending tool permission without opening it. */
export function usePendingDecision(session: () => Session) {
  const pending = computed(() => session().pending_permission ?? null)
  const sending = ref<PromptDecision | null>(null)
  const answeredPrompt = ref<string | null>(null)
  const error = ref<string | null>(null)
  const answered = computed(() => pending.value != null && answeredPrompt.value === pending.value.prompt_id)

  async function decide(decision: PromptDecision): Promise<void> {
    const prompt = pending.value
    if (!prompt || sending.value) return
    sending.value = decision
    error.value = null
    try {
      await answerPrompt(session().session_id, prompt.prompt_id, decision)
      answeredPrompt.value = prompt.prompt_id
    } catch (e) {
      // 409: already answered (maybe in another tab).
      if (e instanceof ApiError && e.status === 409) answeredPrompt.value = prompt.prompt_id
      else error.value = errorMessage(e)
    } finally {
      sending.value = null
    }
  }

  return { pending, sending, answered, error, decide }
}
```

- [x] **Passo 4: gráfico**

Criar `frontend/src/components/dashboard/ActivityChart.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { ActivityDay, Project } from '../../types/api'

const props = defineProps<{ data: ActivityDay[]; projects: Project[]; days: number; today: Date }>()

const WIDTH = 700
const HEIGHT = 160
const GAP = 6

function iso(date: Date): string {
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${m}-${d}`
}
const short = (value: string) => `${value.slice(8, 10)}/${value.slice(5, 7)}`

const dayList = computed(() => Array.from({ length: props.days }, (_, i) => {
  const date = new Date(props.today.getFullYear(), props.today.getMonth(), props.today.getDate() - (props.days - 1 - i))
  return iso(date)
}))
const colorOf = (id: number) => props.projects.find((p) => p.id === id)?.color ?? 'var(--color-fg-muted)'
const nameOf = (id: number) => props.projects.find((p) => p.id === id)?.name ?? 'Projeto removido'
const order = computed(() => new Map(props.projects.map((p, i) => [p.id, i])))

const columns = computed(() => dayList.value.map((date) => {
  const parts = props.data
    .filter((d) => d.date === date)
    .sort((a, b) => (order.value.get(a.project_id) ?? 999) - (order.value.get(b.project_id) ?? 999))
  return { date, parts, total: parts.reduce((sum, p) => sum + p.sessions, 0) }
}))
const max = computed(() => Math.max(1, ...columns.value.map((c) => c.total)))
const barWidth = computed(() => (WIDTH - GAP * (props.days - 1)) / props.days)
const legend = computed(() => {
  const ids = new Set(props.data.map((d) => d.project_id))
  return [...ids].sort((a, b) => (order.value.get(a) ?? 999) - (order.value.get(b) ?? 999))
})

function stack(column: { parts: ActivityDay[] }) {
  let y = HEIGHT
  return column.parts.map((part) => {
    const height = (part.sessions / max.value) * (HEIGHT - 8)
    y -= height
    return { part, y, height }
  })
}
</script>

<template>
  <figure data-test="activity-chart" class="m-0 flex flex-col gap-3">
    <figcaption class="text-sm font-semibold">Atividade nos últimos {{ days }} dias</figcaption>
    <p v-if="data.length === 0" data-test="activity-empty" class="m-0 py-8 text-center text-sm text-fg-muted">Nenhuma atividade nos últimos {{ days }} dias.</p>
    <template v-else>
      <svg :viewBox="`0 0 ${WIDTH} ${HEIGHT + 20}`" class="h-44 w-full" role="img" aria-hidden="true">
        <line :x1="0" :x2="WIDTH" :y1="HEIGHT" :y2="HEIGHT" stroke="var(--color-line)" />
        <g v-for="(column, i) in columns" :key="column.date">
          <rect
            v-for="{ part, y, height } in stack(column)"
            :key="part.project_id"
            data-test="activity-bar"
            :data-date="column.date"
            :x="i * (barWidth + GAP)"
            :y="y"
            :width="barWidth"
            :height="height"
            :fill="colorOf(part.project_id)"
            rx="2"
          ><title>{{ short(column.date) }} · {{ nameOf(part.project_id) }}: {{ part.sessions }}</title></rect>
          <text v-if="i === 0 || i === columns.length - 1 || i === Math.floor(columns.length / 2)" :x="i * (barWidth + GAP) + barWidth / 2" :y="HEIGHT + 15" text-anchor="middle" font-size="11" fill="var(--color-fg-muted)">{{ short(column.date) }}</text>
        </g>
      </svg>
      <ul class="m-0 flex list-none flex-wrap gap-3 p-0 text-xs text-fg-muted">
        <li v-for="id in legend" :key="id" class="flex items-center gap-1.5"><span class="size-2 rounded-[3px]" :style="{ backgroundColor: colorOf(id) }" />{{ nameOf(id) }}</li>
      </ul>
      <table class="sr-only">
        <caption>Conversas com atividade por dia e projeto</caption>
        <thead><tr><th>Dia</th><th>Projeto</th><th>Conversas</th></tr></thead>
        <tbody>
          <tr v-for="row in data" :key="`${row.date}-${row.project_id}`"><td>{{ short(row.date) }}</td><td>{{ nameOf(row.project_id) }}</td><td>{{ row.sessions }}</td></tr>
        </tbody>
      </table>
    </template>
  </figure>
</template>
```

- [x] **Passo 5: página**

Criar `frontend/src/views/DashboardView.vue`:

```vue
<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import ActivityChart from '../components/dashboard/ActivityChart.vue'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import DisplayStateIcon from '../components/DisplayStateIcon.vue'
import BranchLabel from '../components/git/BranchLabel.vue'
import { getActivity } from '../api/http'
import { usePendingDecision } from '../conversation/pendingDecision'
import { waitingReason } from '../conversationList'
import { formatActivity } from '../format'
import { displayStateLabels } from '../sessionState'
import { changedCount, repoLabel, useGitStore } from '../stores/git'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import type { ActivityDay, Session } from '../types/api'

const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()

const active = computed(() => sessions.all.filter((s) => s.display_state === 'running' || s.display_state === 'waiting'))
const running = computed(() => active.value.filter((s) => s.display_state === 'running').length)
const waiting = computed(() => active.value.filter((s) => s.display_state === 'waiting').length)
const startOfToday = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000 }
const finishedToday = computed(() => sessions.all.filter((s) => (s.finished_at ?? 0) >= startOfToday()).length)
const changedFiles = (projectId: number) => git.reposFor(projectId).reduce((sum, r) => sum + changedCount(r), 0)
const projectsWithChanges = computed(() => projects.projects.filter((p) => changedFiles(p.id) > 0).length)
const waitingIn = (projectId: number) => sessions.forProject(projectId).filter((s) => s.display_state === 'waiting').length
const recent = computed(() => sessions.all.slice(0, 8))
const projectOf = (s: Session) => projects.byId(s.project_id)

const activity = ref<ActivityDay[]>([])
const activityError = ref(false)
const activityLoading = ref(false)
async function loadActivity() {
  activityLoading.value = true
  activityError.value = false
  try {
    activity.value = await getActivity(14)
  } catch {
    activityError.value = true
  } finally {
    activityLoading.value = false
  }
}
onMounted(() => {
  projects.projects.forEach((p) => git.ensure(p.id))
  void loadActivity()
})

function scrollToProjects() {
  document.getElementById('dashboard-projetos')?.scrollIntoView({ block: 'start' })
}

// One "Agora" card; Allow/Deny when a tool permission is pending.
const NowCard = defineComponent({
  props: { session: { type: Object as () => Session, required: true } },
  setup(props) {
    const decision = usePendingDecision(() => props.session)
    return () => {
      const s = props.session
      const project = projectOf(s)
      const reason = waitingReason(s) ?? displayStateLabels[s.display_state]
      const pending = decision.pending.value
      return h('article', { 'data-test': 'now-card', class: 'flex flex-col gap-2 rounded-lg border border-line bg-card p-4' }, [
        h('div', { class: 'flex items-center gap-2 text-xs text-fg-muted' }, [
          project ? h('span', { class: 'size-2 rounded-[3px]', style: { backgroundColor: project.color } }) : null,
          project?.name ?? '',
          h('span', { class: 'grow' }),
          formatActivity(s.last_activity_at),
        ]),
        h(RouterLink, { to: { name: 'session', params: { id: s.session_id } }, class: 'truncate font-semibold text-fg no-underline hover:text-primary-soft' }, () => s.title),
        h('div', { class: 'flex items-center gap-1.5 text-xs' }, [
          h(DisplayStateIcon, { display: s.display_state, size: 11 }),
          h('span', { class: s.display_state === 'waiting' ? 'text-secondary-soft' : 'text-primary-soft' }, reason),
        ]),
        s.last_action ? h('p', { class: 'm-0 truncate font-mono text-xs text-fg-muted' }, s.last_action) : null,
        pending && !decision.answered.value
          ? h('div', { class: 'flex gap-2 pt-1' }, [
              h('button', { type: 'button', 'data-test': 'now-allow', disabled: decision.sending.value !== null, class: 'h-9 grow rounded-md bg-secondary text-sm font-semibold text-secondary-fg disabled:opacity-60', 'aria-label': `Permitir ${pending.tool_name} em ${s.title}`, onClick: () => decision.decide('allow_once') }, 'Permitir'),
              h('button', { type: 'button', 'data-test': 'now-deny', disabled: decision.sending.value !== null, class: 'h-9 grow rounded-md border border-secondary/50 text-sm text-secondary-soft disabled:opacity-60', 'aria-label': `Negar ${pending.tool_name} em ${s.title}`, onClick: () => decision.decide('deny') }, 'Negar'),
            ])
          : null,
        decision.answered.value ? h('p', { role: 'status', class: 'm-0 text-xs text-fg-muted' }, 'Resposta enviada. Atualizando…') : null,
        decision.error.value ? h('p', { role: 'alert', class: 'm-0 text-xs text-diff-del-fg' }, decision.error.value) : null,
      ])
    }
  },
})
</script>

<template>
  <div class="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-6">
    <h1 class="m-0 font-mono text-sm tracking-[0.08em] text-fg uppercase">Dashboard</h1>

    <section aria-labelledby="now-title" class="flex flex-col gap-3">
      <h2 id="now-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Agora</h2>
      <p v-if="active.length === 0" data-test="now-empty" class="m-0 text-fg-muted">Nenhuma conversa ativa agora.</p>
      <div v-else class="grid gap-3 md:grid-cols-2">
        <NowCard v-for="s in active" :key="s.session_id" :session="s" />
      </div>
    </section>

    <section aria-label="Números" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <RouterLink data-test="stat-running" to="/inbox?aba=em-execucao" class="flex flex-col rounded-lg border border-line p-4 no-underline hover:bg-card"><span class="text-3xl font-semibold text-fg">{{ running }}</span><span class="text-sm text-fg-muted">Em execução</span></RouterLink>
      <RouterLink data-test="stat-waiting" to="/inbox?aba=pede-voce" class="flex flex-col rounded-lg border border-line p-4 no-underline hover:bg-card"><span class="text-3xl font-semibold text-fg">{{ waiting }}</span><span class="text-sm text-fg-muted">Aguardando você</span></RouterLink>
      <RouterLink data-test="stat-finished-today" to="/sessions?estado=finalizadas" class="flex flex-col rounded-lg border border-line p-4 no-underline hover:bg-card"><span class="text-3xl font-semibold text-fg">{{ finishedToday }}</span><span class="text-sm text-fg-muted">Finalizadas hoje</span></RouterLink>
      <button type="button" data-test="stat-projects-changes" class="flex flex-col rounded-lg border border-line p-4 text-left hover:bg-card" @click="scrollToProjects"><span class="text-3xl font-semibold text-fg">{{ projectsWithChanges }}</span><span class="text-sm text-fg-muted">Projetos com alterações</span></button>
    </section>

    <section class="rounded-lg border border-line p-4">
      <div v-if="activityError" class="flex flex-col items-start gap-2">
        <p data-test="activity-error" role="alert" class="m-0 text-sm text-secondary-soft">Não foi possível carregar a atividade.</p>
        <button type="button" data-test="activity-retry" class="h-8 rounded-md border border-line-strong px-2.5 text-xs text-fg hover:bg-card" @click="loadActivity">Tentar de novo</button>
      </div>
      <p v-else-if="activityLoading && activity.length === 0" class="m-0 text-sm text-fg-muted">Carregando…</p>
      <ActivityChart v-else :data="activity" :projects="projects.projects" :days="14" :today="new Date()" />
    </section>

    <div class="grid gap-6 lg:grid-cols-2">
      <section data-test="recent-list" aria-labelledby="recent-title" class="flex flex-col gap-2">
        <h2 id="recent-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Conversas recentes</h2>
        <ConversationRow v-for="s in recent" :key="s.session_id" :session="s" variant="compact" />
      </section>
      <section id="dashboard-projetos" data-test="projects-list" aria-labelledby="projects-title" class="flex flex-col gap-2">
        <h2 id="projects-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Projetos</h2>
        <RouterLink v-for="p in projects.projects" :key="p.id" :to="{ name: 'project', params: { id: p.id } }" class="flex min-h-11 items-center gap-3 rounded-md px-2 text-fg no-underline hover:bg-card">
          <span class="size-2.5 rounded-[3px]" :style="{ backgroundColor: p.color }" />
          <span class="min-w-0 grow truncate">{{ p.name }}</span>
          <BranchLabel v-if="git.reposFor(p.id)[0]" :text="repoLabel(git.reposFor(p.id)[0]!)" muted />
          <span class="text-xs text-fg-muted">{{ changedFiles(p.id) }} {{ changedFiles(p.id) === 1 ? 'arquivo' : 'arquivos' }}</span>
          <span v-if="waitingIn(p.id)" class="flex items-center gap-1 text-xs text-secondary"><DisplayStateIcon display="waiting" :size="11" />{{ waitingIn(p.id) }}</span>
        </RouterLink>
      </section>
    </div>
  </div>
</template>
```

Em `frontend/src/router/index.ts`, importar `DashboardView` e trocar o componente da rota `dashboard`.

- [x] **Passo 6: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/components/dashboard src/views/__tests__/DashboardView.spec.ts`
Expected: PASS.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa.

- [x] **Passo 7: commit**

```bash
git add frontend/src/conversation/pendingDecision.ts frontend/src/components/dashboard frontend/src/views/DashboardView.vue frontend/src/router/index.ts frontend/src/views/__tests__/DashboardView.spec.ts
git commit -m "[Feat] Adicionar Dashboard com conversas ativas, números e atividade"
```

---

### Tarefa 11: Página do projeto com a linha de conversa

**Arquivos:**
- Modificar: `frontend/src/views/ProjectView.vue`
- Testes: `frontend/src/views/__tests__/ProjectView.spec.ts`, `frontend/src/views/__tests__/ProjectViewStates.spec.ts`

**Interfaces:**
- Consome: `ConversationRow`, `groupByDate` (Tarefa 3).
- A lista do projeto passa a ser igual à de Conversas já filtrada: todas as conversas do projeto por última atividade, agrupadas em Hoje, Ontem, Esta semana e Antes, com `ConversationRow` (variant `list`). Sai o agrupamento por estado (`SessionGroup`) e a âncora `#finalizadas`.

- [x] **Passo 1: ajustar os testes (falham)**

Em `ProjectView.spec.ts` e `ProjectViewStates.spec.ts`, trocar os casos que procuram `[data-test="block-running"]`, `block-waiting`, `block-finished` ou `finished-row` por asserções sobre `[data-test="conversation-row"]` e `[data-test="date-group"]`. Acrescentar:

```ts
  it('lista as conversas do projeto por data com a linha de conversa', async () => {
    const now = Date.now() / 1000
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', title: 'Hoje', last_activity_at: now }),
      makeSession({ session_id: 'b', title: 'Velha', last_activity_at: now - 30 * 86400, display_state: 'finished' }),
    ])
    const wrapper = await mountProject()   // helper que o arquivo já usa para montar a página

    expect(wrapper.findAll('[data-test="row-link"]').map((r) => r.text())).toEqual(['Hoje', 'Velha'])
    expect(wrapper.findAll('[data-test="date-group"]').map((g) => g.text())).toEqual(['Hoje', 'Antes'])
  })
```

(usar o nome real do helper de montagem que o arquivo já tem.) Remover o teste de rolagem até `#finalizadas`.

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/views/__tests__/ProjectView.spec.ts src/views/__tests__/ProjectViewStates.spec.ts`
Expected: FAIL.

- [x] **Passo 3: trocar a lista**

Em `ProjectView.vue`:
1. Remover os imports de `SessionGroup`, `displayStateLabels` e `DisplayState` se ficarem sem uso; importar `ConversationRow` e `groupByDate`.
2. Remover `groups`, `scrollToHash` e o `watch`/chamada que o usa.
3. Acrescentar:

```ts
const dateGroups = computed(() => groupByDate(projectSessions.value, new Date(), true))
```

4. Trocar o `<template v-else>` com `SessionGroup` por:

```vue
    <template v-else>
      <section v-for="group in dateGroups" :key="group.label" :aria-label="group.label" class="flex flex-col">
        <div class="flex items-center gap-3 py-2">
          <span class="h-px grow bg-line" /><span data-test="date-group" class="font-mono text-[11px] tracking-[0.08em] text-fg-muted uppercase">{{ group.label }}</span><span class="h-px grow bg-line" />
        </div>
        <ConversationRow v-for="s in group.sessions" :key="s.session_id" :session="s" @error="actionError = $event" />
      </section>
    </template>
```

5. Trocar o texto de lista vazia para: `Nenhuma conversa ainda. Use "Nova sessão" para começar uma conversa nesta pasta.`

- [x] **Passo 4: rodar e ver passar**

Run: `pnpm --dir frontend exec vitest run src/views/__tests__/ProjectView.spec.ts src/views/__tests__/ProjectViewStates.spec.ts`
Expected: PASS.

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa.

- [x] **Passo 5: commit**

```bash
git add frontend/src/views/ProjectView.vue frontend/src/views/__tests__/ProjectView.spec.ts frontend/src/views/__tests__/ProjectViewStates.spec.ts
git commit -m "[UI] Listar conversas do projeto com a linha de conversa"
```

---

### Tarefa 12: Abrir na Inbox e remover as colunas

**Arquivos:**
- Modificar: `frontend/src/router/index.ts`
- Modificar: `frontend/src/stores/layout.ts` (fica só com `finishedAfterDays`, `restore`, `restored`, `loadedFromServer`)
- Modificar: `frontend/src/App.vue` (continua chamando `layout.restore()` para ler as preferências)
- Remover: `frontend/src/views/WorkspaceView.vue`, `AllSessionsView.vue`, `HomeView.vue`; `frontend/src/components/session/SessionColumn.vue`, `ColumnResizer.vue`, `SessionGroup.vue`, `SessionRow.vue`; `frontend/src/components/git/ChangesPanel.vue`; `frontend/src/components/StateCounters.vue` se ficar sem uso
- Remover testes: `views/__tests__/WorkspaceView.spec.ts`, `AllSessionsView.spec.ts`; `components/session/__tests__/ColumnResizer.spec.ts`, `SessionColumn.spec.ts`, `SessionColumnHeader.spec.ts`, `SessionRow.spec.ts`; `components/git/__tests__/ChangesPanel.spec.ts`
- Mover testes: `components/session/__tests__/SessionTurns.spec.ts` e `SessionSubagents.spec.ts` passam a montar `ConversationThread`
- Modificar testes: `stores/__tests__/layout.spec.ts`
- Criar: `frontend/src/__tests__/router.spec.ts`

**Interfaces:**
- `/` redireciona para `/inbox`. Caminhos desconhecidos continuam indo para `/`.
- `useLayoutStore()` → `{ restored, loadedFromServer, finishedAfterDays, restore }`. Nada mais grava `layout` em `/api/state`.

- [x] **Passo 1: testes (falham)**

Criar `frontend/src/__tests__/router.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../router'

describe('rotas', () => {
  it('abre na Inbox', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    expect(router.currentRoute.value.fullPath).toBe('/inbox')
  })

  it('caminho desconhecido vai para a Inbox', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/nao-existe')
    expect(router.currentRoute.value.fullPath).toBe('/inbox')
  })

  it('mantém as rotas de conversa, lista, dashboard e projeto', () => {
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve('/sessions/abc').name).toBe('session')
    expect(router.resolve('/sessions').name).toBe('sessions')
    expect(router.resolve('/dashboard').name).toBe('dashboard')
    expect(router.resolve('/projects/3').name).toBe('project')
  })
})
```

Em `stores/__tests__/layout.spec.ts`, remover os casos de colunas, larguras e gravação; manter (ou escrever) os de leitura de `finished_after_days` e de falha na leitura:

```ts
  it('lê os dias para finalizar das preferências', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/state': () => jsonResponse({ preferences: { finished_after_days: 5 } }) }))
    const layout = useLayoutStore()
    await layout.restore()
    expect(layout.finishedAfterDays).toBe(5)
    expect(layout.loadedFromServer).toBe(true)
  })

  it('não grava nada no estado do app', async () => {
    const fetch = routeFetch({ 'GET /api/state': () => jsonResponse({}) })
    vi.stubGlobal('fetch', fetch)
    await useLayoutStore().restore()
    await new Promise((r) => setTimeout(r, 600))
    expect(fetch.mock.calls.every(([, init]) => (init?.method ?? 'GET') === 'GET')).toBe(true)
  })
```

- [x] **Passo 2: rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/__tests__/router.spec.ts src/stores/__tests__/layout.spec.ts`
Expected: FAIL (`/` ainda abre o `WorkspaceView`; o store ainda grava).

- [x] **Passo 3: rotas**

Deixar `frontend/src/router/index.ts` assim:

```ts
import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'
import ConversationView from '../views/ConversationView.vue'
import ConversationsView from '../views/ConversationsView.vue'
import DashboardView from '../views/DashboardView.vue'
import InboxView from '../views/InboxView.vue'
import NewProjectView from '../views/NewProjectView.vue'
import PreferencesView from '../views/PreferencesView.vue'
import ProjectView from '../views/ProjectView.vue'

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/inbox' },
  { path: '/inbox', name: 'inbox', component: InboxView },
  { path: '/dashboard', name: 'dashboard', component: DashboardView },
  { path: '/sessions', name: 'sessions', component: ConversationsView },
  { path: '/sessions/:id', name: 'session', component: ConversationView, props: true },
  { path: '/projects/new', name: 'project-new', component: NewProjectView },
  {
    path: '/projects/:id(\\d+)',
    name: 'project',
    component: ProjectView,
    props: (route) => ({ id: Number(route.params.id) }),
  },
  { path: '/preferencias', name: 'preferences', component: PreferencesView },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
```

Procurar com `grep -rn "name: 'home'\|to=\"/\"\|push('/')" frontend/src` e trocar referências à rota `home` por `'/inbox'` (por exemplo, o `router.push('/')` depois de remover um projeto pode ficar, porque `/` redireciona).

- [x] **Passo 4: store `layout` só com preferências**

Reescrever `frontend/src/stores/layout.ts`:

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'

export const DEFAULT_FINISHED_AFTER_DAYS = 3

/**
 * Preferences read from `GET /api/state` at startup: days without activity before a
 * session counts as finished. A failed read is tried again on reconnect.
 */
export const useLayoutStore = defineStore('layout', () => {
  const restored = ref(false)
  const loadedFromServer = ref(false)
  const finishedAfterDays = ref(DEFAULT_FINISHED_AFTER_DAYS)

  // Startup and a reconnect can ask at the same time: share the read in flight.
  let inFlight: Promise<void> | null = null
  function restore(): Promise<void> {
    if (!inFlight) inFlight = doRestore().finally(() => { inFlight = null })
    return inFlight
  }

  async function doRestore(): Promise<void> {
    try {
      const state = await api.getAppState()
      const days = (state?.preferences as Record<string, unknown> | undefined)?.finished_after_days
      if (typeof days === 'number' && Number.isFinite(days) && days > 0) finishedAfterDays.value = days
      loadedFromServer.value = true
    } catch {
      // Defaults stay; the reconnect tries again.
    } finally {
      restored.value = true
    }
  }

  return { restored, loadedFromServer, finishedAfterDays, restore }
})
```

Conferir `PreferencesView.vue`: ele usa `DEFAULT_FINISHED_AFTER_DAYS` e `useLayoutStore().finishedAfterDays`, que continuam existindo.

- [x] **Passo 5: remover código e testes das colunas**

```bash
git rm frontend/src/views/WorkspaceView.vue frontend/src/views/AllSessionsView.vue frontend/src/views/HomeView.vue \
  frontend/src/components/session/SessionColumn.vue frontend/src/components/session/ColumnResizer.vue \
  frontend/src/components/session/SessionGroup.vue frontend/src/components/session/SessionRow.vue \
  frontend/src/components/git/ChangesPanel.vue \
  frontend/src/views/__tests__/WorkspaceView.spec.ts frontend/src/views/__tests__/AllSessionsView.spec.ts \
  frontend/src/components/session/__tests__/ColumnResizer.spec.ts frontend/src/components/session/__tests__/SessionColumn.spec.ts \
  frontend/src/components/session/__tests__/SessionColumnHeader.spec.ts frontend/src/components/session/__tests__/SessionRow.spec.ts \
  frontend/src/components/git/__tests__/ChangesPanel.spec.ts
```

(Subagentes não rodam `git rm`: o implementer apaga os arquivos com `rm`, e a sessão principal registra a remoção no commit.)

Depois:
- `grep -rn "StateCounters" frontend/src` — se só sobrar o próprio arquivo, apagar `components/StateCounters.vue`.
- Em `SessionTurns.spec.ts` e `SessionSubagents.spec.ts`, trocar o componente montado de `SessionColumn` para `ConversationThread` (import de `../../conversation/ConversationThread.vue`), mantendo as asserções. Se algum caso verificava o cabeçalho da coluna, apagar esse caso (o cabeçalho novo tem testes na Tarefa 6).
- Antes de apagar `SessionColumn.spec.ts`, conferir se algum caso cobre comportamento do corpo que não aparece em `ConversationThread.spec.ts`, `SessionTurns.spec.ts` ou `SessionSubagents.spec.ts` (por exemplo: arrastar imagem, marcar como vista ao focar, aviso de pasta indisponível, erro da sessão). Mover esses casos para `ConversationThread.spec.ts`, montando `ConversationThread`.
- `grep -rn "hidden_sessions" frontend/src` — o campo continua no tipo `Project` (o backend manda), mas nada o mostra; manter o tipo.

- [x] **Passo 6: rodar tudo**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: tudo passa; build sem avisos de import ausente.

Run: `uv run pytest -q`
Expected: toda a suíte do backend passa.

- [x] **Passo 7: conferir no navegador**

Com backend e frontend rodando (`CLAUDE.md`, seção Comandos), abrir `http://localhost:6600` e verificar, sem enviar mensagens:
1. `/` abre a Inbox.
2. Menu: Nova conversa, Buscar, Dashboard, Inbox (contador), Conversas, Projetos, Recentes, Preferências.
3. Clicar numa conversa abre `/sessions/:id` com trilha, título, Detalhes e compositor centralizado.
4. Dashboard carrega os números e o gráfico.
5. `C` fora de campos abre o modal; Esc fecha mantendo o rascunho.

Relatar o que foi visto; capturas de tela se possível.

- [x] **Passo 8: commit**

```bash
git add -A frontend/src
git commit -m "[Refactor] Abrir na Inbox e remover a área de colunas"
```

---

## Fechamento do marco

Depois da Tarefa 12:
1. Rodar `uv run pytest -q`, `pnpm --dir frontend test` e `pnpm --dir frontend build` e ver tudo passar.
2. Disparar o `milestone-reviewer` sobre o marco 7 inteiro (concorrência, segurança das rotas novas, integração entre telas e stores).
3. Corrigir o que ele reprovar e pedir nova revisão.
4. Marcar o marco 7 como concluído no `ROADMAP.md`.
