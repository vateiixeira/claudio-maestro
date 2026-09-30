# Agrupador de sessões: plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam caixas (`- [ ]`) para acompanhamento.

**Objetivo:** juntar sessões relacionadas de um projeto em agrupadores que só o app conhece, visíveis no menu lateral, na tela do projeto, na conversa e na tela Conversas.

**Arquitetura:** uma tabela `session_groups` e uma coluna `sessions.group_id` (com `ON DELETE SET NULL`) no SQLite. O módulo `groups.py` cuida das regras de nome e do CRUD, e o `SessionManager` faz a troca de agrupador, porque guarda o registro da sessão em memória e emite `session.updated`. No frontend, uma store `groups` carregada por `GET /api/groups`, funções puras de ordenação e árvore, e componentes pequenos para a tela do projeto, o painel Detalhes, a linha de conversa e o menu.

**Stack:** Python 3.13, FastAPI, SQLite, pytest; Vue 3, Pinia, TypeScript, Tailwind, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-agrupador-de-sessoes-design.md`

## Restrições globais

- Textos da interface em português brasileiro. Código e identificadores em inglês.
- No frontend, só `pnpm` (`pnpm --dir frontend test`, `pnpm --dir frontend exec vitest run <arquivo>`). Nunca `npx` nem `yarn`.
- Testes antes do código. Os testes nunca tocam o SDK real.
- Toda requisição a `/api/` leva o cabeçalho `X-Vibing: 1`. O cliente `request()` de `frontend/src/api/http.ts` já envia.
- Não liberar CORS, não abrir porta nova e não chamar `git` fora de `run_git`.
- `localStorage` só dentro de try/catch, e a tela funciona sem ele.
- Nome do agrupador: sem espaços nas pontas, de 1 a 80 caracteres, único no projeto sem diferenciar maiúsculas nem acentos.
- Mensagens de erro exatas: "Dê um nome ao agrupador.", "O nome pode ter até 80 caracteres.", "Já existe um agrupador com esse nome neste projeto.", "Agrupador não encontrado.", "O agrupador é de outro projeto."
- Subagentes não fazem commit nem `git add`. O passo "Commit" de cada tarefa é da sessão principal, depois de o `reviewer` aprovar e os testes passarem.
- Mensagem de commit: `[Tipo] Título` em português, verbo no infinitivo, até 72 caracteres, sem ponto final.

## Pontos de atenção na revisão

1. Agrupador removido enquanto a conversa está aberta em outra aba: o `session.updated` chega com `group_id: null`, e a propriedade em Detalhes, a etiqueta e o menu passam a mostrar "Nenhum" ou nada (Tarefa 5, teste "agrupador desconhecido").
2. Sessão com `group_id` de um agrupador que a store ainda não conhece (evento perdido): a etiqueta some, sem quebrar a linha, e o menu ignora a sessão até a recarga (Tarefas 5 e 7).
3. `POST /api/projects/{id}/sessions` sem corpo, como o frontend manda hoje, continua criando a sessão (Tarefa 2).
4. `localStorage` que lança exceção: o menu abre com tudo expandido e não quebra (Tarefa 7).
5. Remover o projeto: os agrupadores dele somem do banco (cascata) e da store do frontend (Tarefas 1 e 3).

---

### Tarefa 1: Tabela de agrupadores e módulo `groups.py`

**Arquivos:**
- Modificar: `backend/vibing/db.py` (lista `MIGRATIONS`, depois do bloco do Marco 9)
- Criar: `backend/vibing/groups.py`
- Testar: `backend/tests/test_db.py` (acrescentar), `backend/tests/test_groups.py` (novo)

**Interfaces:**
- Consome: `vibing.db.connect`, `vibing.db.transaction`, `vibing.db.migrate`, `vibing.projects.ProjectNotFoundError`.
- Produz, em `vibing.groups`:
  - `NAME_MAX = 80`
  - `@dataclass(frozen=True) class Group: id: int; project_id: int; name: str; created_at: int`
  - Erros: `GroupError(Exception)`, `GroupNotFoundError`, `InvalidGroupNameError`, `DuplicateGroupNameError`, `GroupProjectMismatchError` (todos herdam de `GroupError`; a mensagem é mostrada ao usuário)
  - `clean_name(name: str) -> str`
  - `list_groups(conn, project_id: int | None = None) -> list[Group]` (ordem: `project_id, created_at, id`)
  - `get_group(conn, group_id: int) -> Group`
  - `check_group_for(conn, group_id: int, project_id: int) -> Group`
  - `create_group(conn, project_id: int, name: str) -> Group`
  - `rename_group(conn, group_id: int, name: str) -> Group`
  - `delete_group(conn, group_id: int) -> tuple[Group, list[str]]` (o agrupador removido e os `session_id` que ficaram soltos)

- [ ] **Passo 1: Escrever os testes da migração (falham)**

Acrescentar em `backend/tests/test_db.py`:

```python
def insert_project(conn, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, path, color, position, created_at)"
        " VALUES (?, 'p', ?, '#fff', 0, 0)",
        (project_id, f"/tmp/p{project_id}"),
    )


def insert_session(conn, session_id: str, project_id: int = 1, group_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
        " last_activity_at, group_id) VALUES (?, ?, '/tmp', 't', 0, 0, ?)",
        (session_id, project_id, group_id),
    )


def test_migration_creates_session_groups(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        assert "session_groups" in table_names(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        assert "group_id" in columns


def test_removing_group_releases_sessions(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        insert_project(conn)
        conn.execute(
            "INSERT INTO session_groups (id, project_id, name, created_at) VALUES (7, 1, 'g', 0)"
        )
        insert_session(conn, "a", group_id=7)
        conn.execute("DELETE FROM session_groups WHERE id = 7")
        row = conn.execute("SELECT group_id FROM sessions WHERE session_id = 'a'").fetchone()
        assert row["group_id"] is None


def test_removing_project_removes_its_groups(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        insert_project(conn)
        conn.execute(
            "INSERT INTO session_groups (project_id, name, created_at) VALUES (1, 'g', 0)"
        )
        conn.execute("DELETE FROM projects WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM session_groups").fetchone()[0] == 0
```

- [ ] **Passo 2: Rodar e ver falhar**

Rodar: `uv run pytest backend/tests/test_db.py -v`
Esperado: FAIL nos três testes novos (`session_groups` não existe).

- [ ] **Passo 3: Acrescentar a migração**

Em `backend/vibing/db.py`, depois do bloco `# Marco 9: ...`, acrescentar como novo item da lista `MIGRATIONS`:

```python
    [
        # Marco 8: groups of related sessions of a project. Only the app knows them;
        # removing a group leaves its sessions loose (ON DELETE SET NULL).
        """
        CREATE TABLE session_groups (
          id          INTEGER PRIMARY KEY,
          project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          name        TEXT NOT NULL,
          created_at  INTEGER NOT NULL
        )
        """,
        "CREATE INDEX session_groups_project_id ON session_groups(project_id)",
        "ALTER TABLE sessions ADD COLUMN group_id INTEGER"
        " REFERENCES session_groups(id) ON DELETE SET NULL",
        "CREATE INDEX sessions_group_id ON sessions(group_id)",
    ],
```

- [ ] **Passo 4: Rodar e ver passar**

Rodar: `uv run pytest backend/tests/test_db.py -v`
Esperado: PASS.

- [ ] **Passo 5: Escrever os testes do módulo (falham)**

Criar `backend/tests/test_groups.py`:

```python
"""Groups module: name rules and CRUD over SQLite."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from vibing import db, groups
from vibing.projects import ProjectNotFoundError


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "t.db")) as c:
        db.migrate(c)
        for pid in (1, 2):
            c.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (?, 'p', ?, '#fff', 0, 0)",
                (pid, f"/tmp/p{pid}"),
            )
        yield c


def add_session(conn, session_id: str, project_id: int = 1, group_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
        " last_activity_at, group_id) VALUES (?, ?, '/tmp', 't', 0, 0, ?)",
        (session_id, project_id, group_id),
    )


def test_create_trims_and_lists(conn):
    created = groups.create_group(conn, 1, "  Checkout  ")
    assert created.name == "Checkout"
    assert created.project_id == 1
    assert groups.list_groups(conn) == [created]
    assert groups.list_groups(conn, 2) == []


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_name_is_refused(conn, name):
    with pytest.raises(groups.InvalidGroupNameError, match="Dê um nome ao agrupador."):
        groups.create_group(conn, 1, name)


def test_name_limit(conn):
    assert groups.create_group(conn, 1, "a" * 80).name == "a" * 80
    with pytest.raises(groups.InvalidGroupNameError, match="até 80 caracteres"):
        groups.create_group(conn, 1, "b" * 81)


def test_duplicate_ignores_case_and_accents(conn):
    groups.create_group(conn, 1, "Refatoração")
    with pytest.raises(groups.DuplicateGroupNameError, match="Já existe um agrupador"):
        groups.create_group(conn, 1, "refatoracao")
    # Another project may use the same name.
    assert groups.create_group(conn, 2, "Refatoração").project_id == 2


def test_create_in_unknown_project(conn):
    with pytest.raises(ProjectNotFoundError):
        groups.create_group(conn, 99, "x")


def test_rename(conn):
    g = groups.create_group(conn, 1, "a")
    other = groups.create_group(conn, 1, "b")
    assert groups.rename_group(conn, g.id, "A").name == "A"  # own name, other case: allowed
    with pytest.raises(groups.DuplicateGroupNameError):
        groups.rename_group(conn, g.id, "B")
    with pytest.raises(groups.GroupNotFoundError, match="Agrupador não encontrado."):
        groups.rename_group(conn, 999, "x")
    assert groups.get_group(conn, other.id).name == "b"


def test_delete_returns_released_sessions(conn):
    g = groups.create_group(conn, 1, "a")
    add_session(conn, "s1", group_id=g.id)
    add_session(conn, "s2", group_id=g.id)
    add_session(conn, "s3")
    removed, released = groups.delete_group(conn, g.id)
    assert removed == g
    assert sorted(released) == ["s1", "s2"]
    rows = conn.execute("SELECT group_id FROM sessions").fetchall()
    assert all(row["group_id"] is None for row in rows)
    with pytest.raises(groups.GroupNotFoundError):
        groups.delete_group(conn, g.id)


def test_check_group_for(conn):
    g = groups.create_group(conn, 1, "a")
    assert groups.check_group_for(conn, g.id, 1) == g
    with pytest.raises(groups.GroupProjectMismatchError, match="outro projeto"):
        groups.check_group_for(conn, g.id, 2)
    with pytest.raises(groups.GroupNotFoundError):
        groups.check_group_for(conn, 999, 1)
```

- [ ] **Passo 6: Rodar e ver falhar**

Rodar: `uv run pytest backend/tests/test_groups.py -v`
Esperado: FAIL com `ImportError` (o módulo `groups` não existe).

- [ ] **Passo 7: Criar `backend/vibing/groups.py`**

```python
"""Groups: related sessions of a project. Only the app knows them."""

import sqlite3
import time
import unicodedata
from dataclasses import dataclass

from vibing.db import transaction
from vibing.projects import ProjectNotFoundError

NAME_MAX = 80


@dataclass(frozen=True)
class Group:
    id: int
    project_id: int
    name: str
    created_at: int


class GroupError(Exception):
    """Base error. The message is shown to the user."""


class GroupNotFoundError(GroupError):
    pass


class InvalidGroupNameError(GroupError):
    pass


class DuplicateGroupNameError(GroupError):
    pass


class GroupProjectMismatchError(GroupError):
    pass


_COLUMNS = "id, project_id, name, created_at"


def _from_row(row: sqlite3.Row) -> Group:
    return Group(
        id=row["id"], project_id=row["project_id"], name=row["name"],
        created_at=row["created_at"],
    )


def _fold(text: str) -> str:
    """Case and accents ignored, for comparing names."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise InvalidGroupNameError("Dê um nome ao agrupador.")
    if len(cleaned) > NAME_MAX:
        raise InvalidGroupNameError(f"O nome pode ter até {NAME_MAX} caracteres.")
    return cleaned


def list_groups(conn: sqlite3.Connection, project_id: int | None = None) -> list[Group]:
    query = f"SELECT {_COLUMNS} FROM session_groups"
    params: tuple[int, ...] = ()
    if project_id is not None:
        query += " WHERE project_id = ?"
        params = (project_id,)
    query += " ORDER BY project_id, created_at, id"
    return [_from_row(row) for row in conn.execute(query, params).fetchall()]


def get_group(conn: sqlite3.Connection, group_id: int) -> Group:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM session_groups WHERE id = ?", (group_id,)
    ).fetchone()
    if row is None:
        raise GroupNotFoundError("Agrupador não encontrado.")
    return _from_row(row)


def check_group_for(conn: sqlite3.Connection, group_id: int, project_id: int) -> Group:
    """The group, if it belongs to the project."""
    group = get_group(conn, group_id)
    if group.project_id != project_id:
        raise GroupProjectMismatchError("O agrupador é de outro projeto.")
    return group


def _check_unique(
    conn: sqlite3.Connection, project_id: int, name: str, exclude_id: int | None = None
) -> None:
    folded = _fold(name)
    rows = conn.execute(
        "SELECT id, name FROM session_groups WHERE project_id = ?", (project_id,)
    ).fetchall()
    if any(row["id"] != exclude_id and _fold(row["name"]) == folded for row in rows):
        raise DuplicateGroupNameError("Já existe um agrupador com esse nome neste projeto.")


def create_group(conn: sqlite3.Connection, project_id: int, name: str) -> Group:
    cleaned = clean_name(name)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise ProjectNotFoundError("Projeto não encontrado.")
        _check_unique(conn, project_id, cleaned)
        cursor = conn.execute(
            "INSERT INTO session_groups (project_id, name, created_at) VALUES (?, ?, ?)",
            (project_id, cleaned, int(time.time())),
        )
    return get_group(conn, cursor.lastrowid)


def rename_group(conn: sqlite3.Connection, group_id: int, name: str) -> Group:
    cleaned = clean_name(name)
    with transaction(conn):
        group = get_group(conn, group_id)
        _check_unique(conn, group.project_id, cleaned, exclude_id=group_id)
        conn.execute("UPDATE session_groups SET name = ? WHERE id = ?", (cleaned, group_id))
    return get_group(conn, group_id)


def delete_group(conn: sqlite3.Connection, group_id: int) -> tuple[Group, list[str]]:
    """Remove the group. Returns it and the sessions it released (not deleted)."""
    with transaction(conn):
        group = get_group(conn, group_id)
        released = [
            row["session_id"]
            for row in conn.execute(
                "SELECT session_id FROM sessions WHERE group_id = ?", (group_id,)
            )
        ]
        conn.execute("DELETE FROM session_groups WHERE id = ?", (group_id,))
    return group, released
```

- [ ] **Passo 8: Rodar e ver passar**

Rodar: `uv run pytest backend/tests/test_groups.py backend/tests/test_db.py -v`
Esperado: PASS.

- [ ] **Passo 9: Rodar a suíte do backend**

Rodar: `uv run pytest -q`
Esperado: tudo passa (a migração nova não pode quebrar os testes que já existem).

- [ ] **Passo 10: Commit (sessão principal)**

Marcar no `ROADMAP.md` o item "Tabela de agrupadores no SQLite..." com a data e atualizar a contagem.

```bash
git add backend/vibing/db.py backend/vibing/groups.py backend/tests/test_db.py backend/tests/test_groups.py ROADMAP.md
git commit -m "[Feat] Criar tabela e módulo de agrupadores de sessões"
```

---

### Tarefa 2: Sessões com agrupador, rotas e evento

**Arquivos:**
- Modificar: `backend/vibing/sessions.py` (`SessionRecord` ~linha 232, `_COLUMNS` ~275, `create_session` ~2066, `search` ~2217, `update` ~2473; novo método `remove_group`)
- Modificar: `backend/vibing/api/sessions.py` (`SessionOut`, `SessionPatch`, `create_session`, `update_session`, mapa de erros de agrupador)
- Criar: `backend/vibing/api/groups.py`
- Modificar: `backend/vibing/api/__init__.py`
- Testar: `backend/tests/test_groups_api.py` (novo)

**Interfaces:**
- Consome: tudo o que `vibing.groups` produz na Tarefa 1.
- Produz:
  - `SessionRecord.group_id: int | None = None`. `SessionOut.group_id: int | None = None` em todas as respostas e no `session.updated`.
  - `SessionManager.create_session(project, group_id: int | None = None) -> SessionRecord`
  - `SessionManager.update(..., group_id: int | None | EllipsisType = ...)`: `...` deixa como está e `None` tira do agrupador.
  - `SessionManager.remove_group(group_id: int) -> groups.Group`
  - `vibing.api.sessions.group_http_error(exc: groups.GroupError) -> HTTPException`
  - Rotas: `GET /api/groups` → `[{id, project_id, name, created_at}]`; `POST /api/projects/{id}/groups` `{name}` → 201; `PATCH /api/groups/{id}` `{name}` → 200; `DELETE /api/groups/{id}` → 204. `PATCH /api/sessions/{id}` aceita `group_id`. `POST /api/projects/{id}/sessions` aceita o corpo opcional `{group_id}`.
  - Evento `{"session_id": None, "seq": 0, "type": "groups.changed", "data": {"project_id": <int>}}` ao criar, renomear e remover.

- [ ] **Passo 1: Escrever os testes (falham)**

Criar `backend/tests/test_groups_api.py`:

```python
"""Group routes and the group of a session. Uses the scripted fake agent."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from test_sessions_api import api, connect_ws, factory, make_project, receive  # noqa: F401


def create_group(api: TestClient, project_id: int, name: str = "Checkout") -> dict[str, Any]:
    response = api.post(f"/api/projects/{project_id}/groups", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def new_session(api: TestClient, project_id: int, body: dict | None = None) -> dict[str, Any]:
    if body is None:
        response = api.post(f"/api/projects/{project_id}/sessions")
    else:
        response = api.post(f"/api/projects/{project_id}/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def next_of_type(ws, kind: str) -> dict[str, Any]:
    while True:
        event = receive(ws)
        if event["type"] == kind:
            return event


def test_crud_and_listing(api, home: Path):
    project = make_project(api, home)
    group = create_group(api, project["id"], "  Checkout ")
    assert group["name"] == "Checkout"
    assert group["project_id"] == project["id"]
    assert api.get("/api/groups").json() == [group]

    renamed = api.patch(f"/api/groups/{group['id']}", json={"name": "Pagamento"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Pagamento"

    assert api.delete(f"/api/groups/{group['id']}").status_code == 204
    assert api.get("/api/groups").json() == []


def test_errors(api, home: Path):
    project = make_project(api, home)
    create_group(api, project["id"], "Checkout")
    dup = api.post(f"/api/projects/{project['id']}/groups", json={"name": "checkout"})
    assert dup.status_code == 409
    assert dup.json()["detail"] == "Já existe um agrupador com esse nome neste projeto."
    empty = api.post(f"/api/projects/{project['id']}/groups", json={"name": "  "})
    assert empty.status_code == 422
    assert empty.json()["detail"] == "Dê um nome ao agrupador."
    long = api.post(f"/api/projects/{project['id']}/groups", json={"name": "x" * 81})
    assert long.status_code == 422
    assert api.post("/api/projects/999/groups", json={"name": "x"}).status_code == 404
    assert api.patch("/api/groups/999", json={"name": "x"}).status_code == 404
    assert api.delete("/api/groups/999").status_code == 404


def test_group_routes_need_the_vibing_header(api, home: Path):
    project = make_project(api, home)
    response = api.post(
        f"/api/projects/{project['id']}/groups", json={"name": "x"}, headers={"x-vibing": ""}
    )
    assert response.status_code in (400, 403)


def test_move_change_and_release_session(api, home: Path):
    project = make_project(api, home)
    a = create_group(api, project["id"], "A")
    b = create_group(api, project["id"], "B")
    session = new_session(api, project["id"])
    assert session["group_id"] is None
    url = f"/api/sessions/{session['session_id']}"

    assert api.patch(url, json={"group_id": a["id"]}).json()["group_id"] == a["id"]
    assert api.patch(url, json={"group_id": b["id"]}).json()["group_id"] == b["id"]
    # A PATCH without group_id keeps the group.
    assert api.patch(url, json={"title": "Novo"}).json()["group_id"] == b["id"]
    assert api.patch(url, json={"group_id": None}).json()["group_id"] is None


def test_move_to_group_of_another_project_or_missing(api, home: Path):
    one = make_project(api, home, "one")
    two = make_project(api, home, "two")
    foreign = create_group(api, two["id"], "X")
    session = new_session(api, one["id"])
    url = f"/api/sessions/{session['session_id']}"
    response = api.patch(url, json={"group_id": foreign["id"]})
    assert response.status_code == 422
    assert response.json()["detail"] == "O agrupador é de outro projeto."
    assert api.patch(url, json={"group_id": 999}).status_code == 404
    assert api.get(f"/api/projects/{one['id']}/sessions").json()[0]["group_id"] is None


def test_create_session_inside_group(api, home: Path):
    project = make_project(api, home)
    group = create_group(api, project["id"])
    session = new_session(api, project["id"], {"group_id": group["id"]})
    assert session["group_id"] == group["id"]
    # Without a body (what the frontend sent before) it still works.
    assert new_session(api, project["id"])["group_id"] is None
    other = make_project(api, home, "other")
    response = api.post(f"/api/projects/{other['id']}/sessions", json={"group_id": group["id"]})
    assert response.status_code == 422


def test_events(api, home: Path):
    project = make_project(api, home)
    with connect_ws(api) as ws:
        group = create_group(api, project["id"])
        event = next_of_type(ws, "groups.changed")
        assert event["data"] == {"project_id": project["id"]}
        assert event["session_id"] is None

        session = new_session(api, project["id"])
        api.patch(f"/api/sessions/{session['session_id']}", json={"group_id": group["id"]})
        updated = next_of_type(ws, "session.updated")
        assert updated["data"]["group_id"] == group["id"]

        api.patch(f"/api/groups/{group['id']}", json={"name": "Outro"})
        assert next_of_type(ws, "groups.changed")["data"] == {"project_id": project["id"]}

        api.delete(f"/api/groups/{group['id']}")
        released = next_of_type(ws, "session.updated")
        assert released["session_id"] == session["session_id"]
        assert released["data"]["group_id"] is None
        assert next_of_type(ws, "groups.changed")["data"] == {"project_id": project["id"]}


def test_remove_group_releases_session_not_in_memory(api, home: Path):
    project = make_project(api, home)
    group = create_group(api, project["id"])
    session = new_session(api, project["id"], {"group_id": group["id"]})
    # Drop it from memory the way the app does after the last client leaves.
    manager = api.app.state.sessions
    manager._sessions.pop(session["session_id"], None)
    with connect_ws(api) as ws:
        api.delete(f"/api/groups/{group['id']}")
        released = next_of_type(ws, "session.updated")
        assert released["session_id"] == session["session_id"]
        assert released["data"]["group_id"] is None
    listed = api.get(f"/api/projects/{project['id']}/sessions").json()
    assert listed[0]["group_id"] is None


def test_search_finds_by_group_name(api, home: Path):
    project = make_project(api, home)
    group = create_group(api, project["id"], "Integração Stripe")
    session = new_session(api, project["id"], {"group_id": group["id"]})
    new_session(api, project["id"])
    found = api.get("/api/sessions/search", params={"q": "integracao"}).json()
    assert [s["session_id"] for s in found] == [session["session_id"]]


def test_removing_project_removes_groups(api, home: Path):
    project = make_project(api, home)
    create_group(api, project["id"])
    assert api.delete(f"/api/projects/{project['id']}").status_code == 204
    assert api.get("/api/groups").json() == []
```

Antes de rodar, confirme em `backend/tests/test_sessions_api.py` que `api`, `factory`, `make_project`, `connect_ws` e `receive` existem com esses nomes (existem nas linhas 25 a 85). `SessionManager._sessions` é o dicionário das sessões em memória (`sessions.py` ~linha 1950). Tirar a sessão dele simula uma sessão que só existe no banco.

- [ ] **Passo 2: Rodar e ver falhar**

Rodar: `uv run pytest backend/tests/test_groups_api.py -v`
Esperado: FAIL (rotas inexistentes, `group_id` ausente em `SessionOut`).

- [ ] **Passo 3: Registro da sessão**

Em `backend/vibing/sessions.py`:

1. `import groups` junto dos imports de `vibing` (`from vibing import db, groups`, seguindo o estilo do arquivo) e `from types import EllipsisType`.
2. No fim de `SessionRecord`:

```python
    # Group of related sessions (only the app knows it); None when loose.
    group_id: int | None = None
```

3. Em `_COLUMNS`, acrescentar `", group_id"` ao fim da última linha: `+ ", model, effort, permission_mode, finished_at, plan_path, plan_link, group_id"`.

`describe()` usa `asdict(record)`, então `group_id` já vai para o frontend. Não o coloque em `_INTERNAL_FIELDS`.

- [ ] **Passo 4: `create_session` com agrupador**

Trocar o método por:

```python
    def create_session(self, project: Project, group_id: int | None = None) -> SessionRecord:
        if not project.available:
            raise ProjectUnavailableError("A pasta do projeto não está disponível.")
        now = _now()
        record = SessionRecord(
            session_id=str(uuid.uuid4()),
            project_id=project.id,
            cwd=project.path,
            title=DEFAULT_TITLE,
            created_at=now,
            last_activity_at=now,
            last_seen_at=now,
            finished=False,
            permission_mode=self._default_permission_mode(),
            group_id=group_id,
        )
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            # Same transaction: the group cannot vanish between the check and the insert.
            if group_id is not None:
                groups.check_group_for(conn, group_id, project.id)
            conn.execute(
                f"INSERT INTO sessions ({_INSERT_COLUMNS}, permission_mode, group_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.session_id,
                    record.project_id,
                    record.cwd,
                    record.title,
                    record.created_at,
                    record.last_activity_at,
                    record.last_seen_at,
                    int(record.finished),
                    record.permission_mode,
                    record.group_id,
                ),
            )
        return record
```

- [ ] **Passo 5: `update` com agrupador**

Na assinatura de `update`, depois de `confirm_bypass: bool = False,`, acrescentar `group_id: int | None | EllipsisType = ...,`. Na docstring, acrescentar: "`group_id` moves the session to a group of its project; `None` takes it out, `...` keeps it."

Logo depois de `session = self.get(session_id)`, antes das outras validações:

```python
        if group_id is not ... and group_id is not None:
            with closing(db.connect(self._db_path)) as conn:
                groups.check_group_for(conn, group_id, session.record.project_id)
```

Depois do bloco que trata `title` e antes de `if "finished" in changes:`:

```python
        if group_id is not ... and group_id != session.record.group_id:
            changes["group_id"] = group_id
```

Trocar a linha `session.save(**changes)` por:

```python
        try:
            session.save(**changes)
        except sqlite3.IntegrityError as exc:
            # The group was removed between the check and the write.
            raise groups.GroupNotFoundError("Agrupador não encontrado.") from exc
```

(`sqlite3` já é importado em `sessions.py`, linha 15.)

- [ ] **Passo 6: `remove_group`**

Acrescentar a `SessionManager`, logo depois de `refresh_records`:

```python
    def remove_group(self, group_id: int) -> groups.Group:
        """Delete a group; its sessions become loose, and each gets a `session.updated`."""
        with closing(db.connect(self._db_path)) as conn:
            group, released = groups.delete_group(conn, group_id)
        outside = []
        for session_id in released:
            session = self._sessions.get(session_id)
            if session is None:
                outside.append(session_id)
                continue
            session.record.group_id = None
            session.emit_updated()
        if outside:
            marks = ", ".join("?" * len(outside))
            with closing(db.connect(self._db_path)) as conn:
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM sessions WHERE session_id IN ({marks})", outside
                ).fetchall()
            for row in rows:
                self._publish_closed_update(_record(row))
        return group
```

- [ ] **Passo 7: Busca pelo nome do agrupador**

Em `search`, depois de `if not needle: return []`:

```python
        with closing(db.connect(self._db_path)) as conn:
            group_names = {group.id: group.name for group in groups.list_groups(conn)}
```

Trocar o cálculo de `haystack` por:

```python
            haystack = " ".join(
                [item.get(key) or "" for key in ("title", "summary", "first_prompt")]
                + [group_names.get(item.get("group_id"), "")]
            )
```

Na docstring: "Sessions whose title, summary, first prompt or group name contain `query`, ...".

- [ ] **Passo 8: Modelos e rotas de sessão**

Em `backend/vibing/api/sessions.py`:

1. `from vibing import groups, projects, sessions`, e `Body` no import de `fastapi`.
2. Em `SessionOut`, depois de `cli_running`:

```python
    # Group of related sessions in the project; None when loose.
    group_id: int | None = None
```

3. Em `SessionPatch`, depois de `confirm_bypass`: `group_id: int | None = None`.
4. Modelo novo, depois de `SessionPatch`:

```python
class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: int | None = None
```

5. Mapa de erros de agrupador, depois de `_http_error`:

```python
_GROUP_STATUS = {
    groups.GroupNotFoundError: status.HTTP_404_NOT_FOUND,
    groups.InvalidGroupNameError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    groups.DuplicateGroupNameError: status.HTTP_409_CONFLICT,
    groups.GroupProjectMismatchError: status.HTTP_422_UNPROCESSABLE_ENTITY,
}


def group_http_error(exc: groups.GroupError) -> HTTPException:
    return HTTPException(status_code=_GROUP_STATUS[type(exc)], detail=str(exc))
```

6. `create_session`:

```python
async def create_session(
    project_id: int,
    conn: DbDep,
    manager: ManagerDep,
    body: Annotated[SessionCreate | None, Body()] = None,
) -> dict[str, Any]:
    project = _get_project(conn, project_id)
    try:
        record = manager.create_session(project, group_id=body.group_id if body else None)
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc
    return manager.describe_record(record)
```

7. `update_session`: passar
`group_id=body.group_id if "group_id" in body.model_fields_set else ...,`
e acrescentar `except groups.GroupError as exc: raise group_http_error(exc) from exc` depois do `except` que já existe.

- [ ] **Passo 9: Rotas de agrupador**

Criar `backend/vibing/api/groups.py`:

```python
"""Groups of related sessions inside a project."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from vibing import groups, projects, sessions
from vibing.api.deps import DbDep
from vibing.api.sessions import get_session_manager, group_http_error

router = APIRouter(prefix="/api")

ManagerDep = Annotated[sessions.SessionManager, Depends(get_session_manager)]


class GroupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The 80-character rule and trimming live in `groups.clean_name`; this only
    # stops absurd bodies before they reach it.
    name: str = Field(max_length=1000)


class GroupOut(BaseModel):
    id: int
    project_id: int
    name: str
    created_at: int


def _out(group: groups.Group) -> dict[str, Any]:
    return {
        "id": group.id, "project_id": group.project_id, "name": group.name,
        "created_at": group.created_at,
    }


def _changed(request: Request, project_id: int) -> None:
    """`groups.changed` `{project_id}`: the frontend reloads the group list."""
    request.app.state.hub.publish(
        {"session_id": None, "seq": 0, "type": "groups.changed",
         "data": {"project_id": project_id}}
    )


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(conn: DbDep) -> list[dict[str, Any]]:
    return [_out(group) for group in groups.list_groups(conn)]


@router.post(
    "/projects/{project_id}/groups", response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    project_id: int, body: GroupIn, request: Request, conn: DbDep
) -> dict[str, Any]:
    try:
        group = groups.create_group(conn, project_id, body.name)
    except projects.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc
    _changed(request, project_id)
    return _out(group)


@router.patch("/groups/{group_id}", response_model=GroupOut)
async def rename_group(
    group_id: int, body: GroupIn, request: Request, conn: DbDep
) -> dict[str, Any]:
    try:
        group = groups.rename_group(conn, group_id, body.name)
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc
    _changed(request, group.project_id)
    return _out(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, request: Request, manager: ManagerDep) -> Response:
    try:
        group = manager.remove_group(group_id)
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc
    _changed(request, group.project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Em `backend/vibing/api/__init__.py`, importar `groups` junto dos outros módulos e acrescentar `router.include_router(groups.router)` depois de `plans.router`.

- [ ] **Passo 10: Rodar e ver passar**

Rodar: `uv run pytest backend/tests/test_groups_api.py -v`
Esperado: PASS.

- [ ] **Passo 11: Suíte do backend**

Rodar: `uv run pytest -q`
Esperado: tudo passa. Se algum teste comparar o dicionário inteiro de uma sessão, acrescente `"group_id": None` ao esperado.

- [ ] **Passo 12: Commit (sessão principal)**

```bash
git add backend/vibing/sessions.py backend/vibing/api/sessions.py backend/vibing/api/groups.py backend/vibing/api/__init__.py backend/tests/test_groups_api.py
git commit -m "[Feat] Adicionar rotas de agrupadores e agrupador da sessão"
```

---

### Tarefa 3: Dados do frontend (tipos, cliente, stores e tempo real)

**Arquivos:**
- Modificar: `frontend/src/types/api.ts`, `frontend/src/api/http.ts`, `frontend/src/stores/sessions.ts`, `frontend/src/stores/projects.ts`, `frontend/src/stores/newConversation.ts`, `frontend/src/stores/realtime.ts`
- Criar: `frontend/src/stores/groups.ts`, `frontend/src/groupList.ts`
- Testar: `frontend/src/stores/__tests__/groups.spec.ts`, `frontend/src/__tests__/groupList.spec.ts`, acréscimos em `frontend/src/stores/__tests__/realtime.spec.ts` e `frontend/src/stores/__tests__/projects.spec.ts`
- Modificar: `frontend/src/test/factories.ts` (`makeGroup`)

**Interfaces:**
- Consome: as rotas da Tarefa 2.
- Produz:
  - `Session.group_id?: number | null`; `SessionUpdate.group_id?: number | null`
  - `interface SessionGroup { id: number; project_id: number; name: string; created_at: number }`
  - `http.ts`: `listGroups(): Promise<SessionGroup[]>`, `createGroup(projectId: number, name: string): Promise<SessionGroup>`, `renameGroup(id: number, name: string): Promise<SessionGroup>`, `deleteGroup(id: number): Promise<void>`, `createSession(projectId: number, groupId?: number | null): Promise<Session>`
  - `useGroupsStore()`: `groups`, `loaded`, `forProject(projectId): SessionGroup[]` (na ordem da API), `byId(id): SessionGroup | undefined`, `load()`, `create(projectId, name)`, `rename(id, name)`, `remove(id)`, `forgetProject(projectId)`
  - `groupList.ts`: `isActive(s: Session): boolean`, `sessionsOf(groupId: number, list: Session[]): Session[]` (mais recente primeiro), `groupActivity(group, list): number`, `sortGroups(groups: SessionGroup[], list: Session[]): SessionGroup[]`
  - `useSessionsStore()`: `create(projectId: number, groupId?: number | null)`, `setGroup(sessionId: string, groupId: number | null): Promise<void>`
  - `useNewConversationStore()`: `presetGroupId`, `open(projectId: number | null = null, groupId: number | null = null)`
  - `makeGroup(overrides)` em `test/factories.ts`

- [ ] **Passo 1: Fábrica de teste**

Em `frontend/src/test/factories.ts`, importar `SessionGroup` e acrescentar:

```ts
export function makeGroup(overrides: Partial<SessionGroup> = {}): SessionGroup {
  return { id: 1, project_id: 1, name: 'Checkout', created_at: 1_790_000_000, ...overrides }
}
```

- [ ] **Passo 2: Escrever os testes (falham)**

Criar `frontend/src/__tests__/groupList.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { groupActivity, isActive, sessionsOf, sortGroups } from '../groupList'
import { makeGroup, makeSession } from '../test/factories'

describe('listas de agrupadores', () => {
  const sessions = [
    makeSession({ session_id: 'a', group_id: 1, last_activity_at: 100 }),
    makeSession({ session_id: 'b', group_id: 1, last_activity_at: 300, display_state: 'finished' }),
    makeSession({ session_id: 'c', group_id: 2, last_activity_at: 200 }),
    makeSession({ session_id: 'd', group_id: null, last_activity_at: 999 }),
  ]

  it('sessões do agrupador, da mais recente para a mais antiga', () => {
    expect(sessionsOf(1, sessions).map((s) => s.session_id)).toEqual(['b', 'a'])
  })

  it('ativa é a que não está finalizada', () => {
    expect(isActive(sessions[0]!)).toBe(true)
    expect(isActive(sessions[1]!)).toBe(false)
  })

  it('atividade do agrupador: última sessão, ou a criação quando vazio', () => {
    expect(groupActivity(makeGroup({ id: 1 }), sessions)).toBe(300)
    expect(groupActivity(makeGroup({ id: 9, created_at: 50 }), sessions)).toBe(50)
  })

  it('ordena pela atividade, mais recente primeiro', () => {
    const groups = [makeGroup({ id: 2, name: 'B' }), makeGroup({ id: 1, name: 'A' }), makeGroup({ id: 9, created_at: 400 })]
    expect(sortGroups(groups, sessions).map((g) => g.id)).toEqual([9, 1, 2])
  })
})
```

Criar `frontend/src/stores/__tests__/groups.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGroupsStore } from '../groups'
import { useSessionsStore } from '../sessions'
import { jsonResponse, makeGroup, makeSession, routeFetch } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('store de agrupadores', () => {
  it('carrega, cria, renomeia e remove', async () => {
    const store = useGroupsStore()
    const a = makeGroup({ id: 1, project_id: 1, name: 'A' })
    const b = makeGroup({ id: 2, project_id: 2, name: 'B' })
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/groups': () => jsonResponse([a, b]) }))
    await store.load()
    expect(store.loaded).toBe(true)
    expect(store.forProject(1)).toEqual([a])

    vi.stubGlobal('fetch', routeFetch({ 'POST /api/projects/1/groups': () => jsonResponse(makeGroup({ id: 3, name: 'C' }), 201) }))
    await store.create(1, 'C')
    expect(store.forProject(1).map((g) => g.id)).toEqual([1, 3])

    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/groups/1': () => jsonResponse({ ...a, name: 'Z' }) }))
    await store.rename(1, 'Z')
    expect(store.byId(1)?.name).toBe('Z')

    vi.stubGlobal('fetch', routeFetch({ 'DELETE /api/groups/1': () => new Response(null, { status: 204 }) }))
    await store.remove(1)
    expect(store.byId(1)).toBeUndefined()

    store.forgetProject(2)
    expect(store.byId(2)).toBeUndefined()
  })

  it('uma carga antiga que chega depois não sobrescreve a nova', async () => {
    const store = useGroupsStore()
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((r) => { release = r })))
    const first = store.load()
    const firstRelease = release
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([makeGroup({ id: 2 })])))
    await store.load()
    firstRelease(jsonResponse([makeGroup({ id: 1 })]))
    await first
    expect(store.groups.map((g) => g.id)).toEqual([2])
  })

  it('cria sessão dentro do agrupador e move uma sessão', async () => {
    const sessions = useSessionsStore()
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/sessions': (init) => { bodies.push(JSON.parse(String(init?.body))); return jsonResponse(makeSession({ group_id: 4 }), 201) },
    }))
    await sessions.create(1, 4)
    expect(bodies).toEqual([{ group_id: 4 }])

    vi.stubGlobal('fetch', routeFetch({
      'PATCH /api/sessions/s1': (init) => { bodies.push(JSON.parse(String(init?.body))); return jsonResponse(makeSession({ group_id: null })) },
    }))
    await sessions.setGroup('s1', null)
    expect(bodies[1]).toEqual({ group_id: null })
    expect(sessions.find('s1')?.group_id).toBeNull()
  })

  it('criar sessão sem agrupador não manda corpo', async () => {
    const sessions = useSessionsStore()
    const init = vi.fn()
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/sessions': (i) => { init(i?.body); return jsonResponse(makeSession(), 201) },
    }))
    await sessions.create(1)
    expect(init).toHaveBeenCalledWith(undefined)
  })
})
```

Em `frontend/src/stores/__tests__/realtime.spec.ts`, seguindo o formato dos testes de `project.synced` que já existem ali, acrescentar dois testes: (1) um evento `groups.changed` faz `GET /api/groups` de novo; (2) `loadEverything()` chama `GET /api/groups`. Em `frontend/src/stores/__tests__/projects.spec.ts`, no teste "carrega, cria, renomeia e remove", antes de `store.remove(2)`, pôr `useGroupsStore().groups = [makeGroup({ id: 5, project_id: 2 })]` e, depois, conferir `expect(useGroupsStore().groups).toEqual([])`.

- [ ] **Passo 3: Rodar e ver falhar**

Rodar: `pnpm --dir frontend exec vitest run src/__tests__/groupList.spec.ts src/stores/__tests__/groups.spec.ts src/stores/__tests__/realtime.spec.ts src/stores/__tests__/projects.spec.ts`
Esperado: FAIL (módulos inexistentes).

- [ ] **Passo 4: Tipos e cliente**

Em `frontend/src/types/api.ts`, no fim de `Session`:

```ts
  /** Group of related sessions in the project; null (or absent) when loose. */
  group_id?: number | null
```

Em `SessionUpdate`: `group_id?: number | null`. E o tipo novo:

```ts
/** Group of related sessions inside a project (`GET /api/groups`). Only the app knows it. */
export interface SessionGroup {
  id: number
  project_id: number
  name: string
  created_at: number
}
```

Em `frontend/src/api/http.ts`, trocar `createSession` e acrescentar uma seção "Groups":

```ts
export function createSession(projectId: number, groupId: number | null = null): Promise<Session> {
  return request('POST', `/api/projects/${projectId}/sessions`, groupId != null ? { group_id: groupId } : undefined)
}

// Groups

export function listGroups(): Promise<SessionGroup[]> {
  return request('GET', '/api/groups')
}

export function createGroup(projectId: number, name: string): Promise<SessionGroup> {
  return request('POST', `/api/projects/${projectId}/groups`, { name })
}

export function renameGroup(id: number, name: string): Promise<SessionGroup> {
  return request('PATCH', `/api/groups/${id}`, { name })
}

export function deleteGroup(id: number): Promise<void> {
  return request('DELETE', `/api/groups/${id}`)
}
```

- [ ] **Passo 5: `groupList.ts`**

```ts
import type { Session, SessionGroup } from './types/api'

/** Whether the session still counts as work in progress (not finished). */
export function isActive(session: Session): boolean {
  return session.display_state !== 'finished'
}

/** Sessions of a group, newest activity first. */
export function sessionsOf(groupId: number, list: Session[]): Session[] {
  return list
    .filter((s) => s.group_id === groupId)
    .sort((a, b) => b.last_activity_at - a.last_activity_at || b.created_at - a.created_at)
}

/** Latest activity of the group's sessions; its creation when it has none. */
export function groupActivity(group: SessionGroup, list: Session[]): number {
  return sessionsOf(group.id, list)[0]?.last_activity_at ?? group.created_at
}

/** Groups by latest activity, newest first. */
export function sortGroups(groups: SessionGroup[], list: Session[]): SessionGroup[] {
  return [...groups].sort((a, b) => groupActivity(b, list) - groupActivity(a, list) || b.id - a.id)
}
```

- [ ] **Passo 6: Store de agrupadores**

Criar `frontend/src/stores/groups.ts`:

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { SessionGroup } from '../types/api'

/** Groups of every project, reloaded on `groups.changed` and after reconnecting. */
export const useGroupsStore = defineStore('groups', () => {
  const groups = ref<SessionGroup[]>([])
  const loaded = ref(false)
  // Only the newest listing may write.
  let ticket = 0

  function forProject(projectId: number): SessionGroup[] {
    return groups.value.filter((g) => g.project_id === projectId)
  }

  function byId(id: number): SessionGroup | undefined {
    return groups.value.find((g) => g.id === id)
  }

  function replace(group: SessionGroup): void {
    const index = groups.value.findIndex((g) => g.id === group.id)
    if (index >= 0) groups.value[index] = group
    else groups.value.push(group)
  }

  async function load(): Promise<void> {
    const mine = ++ticket
    const list = await api.listGroups()
    if (mine !== ticket) return
    groups.value = list
    loaded.value = true
  }

  async function create(projectId: number, name: string): Promise<SessionGroup> {
    const group = await api.createGroup(projectId, name)
    replace(group)
    return group
  }

  async function rename(id: number, name: string): Promise<SessionGroup> {
    const group = await api.renameGroup(id, name)
    replace(group)
    return group
  }

  async function remove(id: number): Promise<void> {
    await api.deleteGroup(id)
    groups.value = groups.value.filter((g) => g.id !== id)
  }

  function forgetProject(projectId: number): void {
    groups.value = groups.value.filter((g) => g.project_id !== projectId)
  }

  return { groups, loaded, forProject, byId, load, create, rename, remove, forgetProject }
})
```

- [ ] **Passo 7: Sessões, projetos, nova conversa e tempo real**

`frontend/src/stores/sessions.ts`:
- `create(projectId: number, groupId: number | null = null)` chama `api.createSession(projectId, groupId)`.
- O tipo de `changes` em `patch` passa a ser `{ finished?: boolean; title?: string; group_id?: number | null }`.
- Novo método, exportado no `return`:

```ts
  async function setGroup(sessionId: string, groupId: number | null): Promise<void> {
    await patch(sessionId, { group_id: groupId })
  }
```

`frontend/src/stores/projects.ts`, em `remove`: depois de `useSessionsStore().forgetProject(id)`, `useGroupsStore().forgetProject(id)`.

`frontend/src/stores/newConversation.ts`:

```ts
/** Whether the "Nova conversa" modal is open, and the project and group it should start on. */
export const useNewConversationStore = defineStore('newConversation', () => {
  const isOpen = ref(false)
  const presetProjectId = ref<number | null>(null)
  const presetGroupId = ref<number | null>(null)

  function open(projectId: number | null = null, groupId: number | null = null): void {
    presetProjectId.value = projectId
    presetGroupId.value = groupId
    isOpen.value = true
  }

  function close(): void {
    isOpen.value = false
  }

  return { isOpen, presetProjectId, presetGroupId, open, close }
})
```

`frontend/src/stores/realtime.ts`:
- Em `loadEverything`, depois de `void useModelsStore().reload()`: `void useGroupsStore().load().catch(() => {})` (a falha deixa o menu sem agrupadores até a próxima carga).
- Em `bindRealtime`, novo ouvinte:

```ts
    // Created, renamed or removed in some project: the list is small, reload it all.
    socket.on('groups.changed', () => {
      useGroupsStore().load().catch(() => {})
    }),
```

- [ ] **Passo 8: Rodar e ver passar**

Rodar: `pnpm --dir frontend exec vitest run src/__tests__/groupList.spec.ts src/stores/__tests__/groups.spec.ts src/stores/__tests__/realtime.spec.ts src/stores/__tests__/projects.spec.ts`
Esperado: PASS.

- [ ] **Passo 9: Suíte e compilação**

Rodar: `pnpm --dir frontend test` e `pnpm --dir frontend build`
Esperado: tudo passa, e a compilação sai sem erro de tipo. Testes que conferem `fetch` chamado sem corpo em `POST /sessions` devem continuar passando, porque `groupId` nulo não manda corpo.

- [ ] **Passo 10: Commit (sessão principal)**

```bash
git add frontend/src/types/api.ts frontend/src/api/http.ts frontend/src/groupList.ts frontend/src/stores frontend/src/test/factories.ts frontend/src/__tests__/groupList.spec.ts
git commit -m "[Feat] Adicionar store de agrupadores no frontend"
```

---

### Tarefa 4: Agrupadores na tela do projeto

**Arquivos:**
- Criar: `frontend/src/components/groups/GroupSection.vue`, `frontend/src/components/groups/ProjectGroups.vue`
- Modificar: `frontend/src/views/ProjectView.vue`
- Testar: `frontend/src/components/groups/__tests__/ProjectGroups.spec.ts`, acréscimos em `frontend/src/views/__tests__/ProjectView.spec.ts`

**Interfaces:**
- Consome: `useGroupsStore`, `useSessionsStore`, `sortGroups`, `sessionsOf`, `isActive`, `useNewConversationStore().open(projectId, groupId)`, `ConversationRow` (props `session`, evento `error`).
- Produz: `<ProjectGroups :project-id="number" :available="boolean" @error="(msg: string) => void" />`, que mostra a seção "Agrupadores". `<GroupSection :group="SessionGroup" :sessions="Session[]" :available="boolean" @error />` mostra um agrupador.

Comportamento (da spec, seção 4, "Tela do projeto"):
- A seção tem o título "Agrupadores" (`h2`, mesmo estilo de "Repositórios nesta pasta") e o botão `data-test="group-new"` "＋ Agrupador". Clicar abre um `input` (`data-test="group-new-name"`, `aria-label="Nome do agrupador"`, `maxlength="80"`) com foco. Enter chama `groups.create(projectId, nome)` e fecha o campo; Esc fecha sem criar. Um erro aparece abaixo, em `role="alert"`, e o campo fica aberto com o texto.
- Sem agrupadores: o botão e a linha `data-test="groups-empty"` "Junte aqui conversas do mesmo trabalho, como a que escreveu um prompt e a que o executou."
- Os agrupadores vêm em `sortGroups(groups.forProject(id), sessions.forProject(id))`.
- `GroupSection`: cabeçalho com um botão de seta (`data-test="group-toggle"`, `aria-expanded`), o nome (`data-test="group-name"`), o texto `data-test="group-count"` ("1 conversa · 1 ativa", "3 conversas · 0 ativas", "Nenhuma conversa") e as ações `data-test="group-new-session"` "＋ Conversa" (desabilitada quando `!available`; chama `newConversation.open(group.project_id, group.id)`), `data-test="group-rename"` "Renomear" (troca o nome por um campo `data-test="group-rename-input"`: Enter salva, Esc cancela) e `data-test="group-remove"` "Remover". Começa aberto; fechado, esconde as linhas. O estado não é guardado.
- A confirmação de remoção fica na própria seção (`role="alertdialog"`, `data-test="group-confirm-remove"`). O título é "Remover o agrupador {nome}?", e o texto: "As {N} conversas voltam a ficar soltas; nenhuma é apagada." (com N = 1: "A conversa volta a ficar solta; nenhuma é apagada."; com N = 0: "O agrupador está vazio."). Os botões são `data-test="group-confirm-ok"` "Remover agrupador" e `data-test="group-confirm-cancel"` "Cancelar", com foco em Cancelar ao abrir e Esc cancelando, igual à confirmação de remover o projeto em `ProjectView.vue`.
- O corpo mostra `ConversationRow` para cada `sessionsOf(group.id, sessions)`, inclusive as finalizadas.
- Em `ProjectView.vue`: `ProjectGroups` entra logo antes da lista por data. `dateGroups` passa a usar só as sessões com `group_id == null`. Quando o projeto tem ao menos um agrupador, a lista por data ganha o título `h2` "Sem agrupador" (`data-test="ungrouped-title"`). A mensagem "Nenhuma conversa ainda..." continua valendo só quando o projeto não tem nenhuma sessão.

- [ ] **Passo 1: Escrever os testes (falham)**

Criar `frontend/src/components/groups/__tests__/ProjectGroups.spec.ts`, no formato de `views/__tests__/ProjectView.spec.ts` (pinia real, `routeFetch` para `fetch`, router de memória com `createAppRouter(createMemoryHistory())`). Casos, cada um com as asserções indicadas:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ProjectGroups from '../ProjectGroups.vue'
import { createAppRouter } from '../../../router'
import { useGroupsStore } from '../../../stores/groups'
import { useNewConversationStore } from '../../../stores/newConversation'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeGroup, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => { pinia = createPinia(); setActivePinia(pinia) })
afterEach(() => vi.unstubAllGlobals())

function mountGroups(available = true) {
  const router = createAppRouter(createMemoryHistory())
  return mount(ProjectGroups, { props: { projectId: 1, available }, global: { plugins: [pinia, router] }, attachTo: document.body })
}

describe('agrupadores na tela do projeto', () => {
  it('sem agrupadores mostra o botão e a explicação', () => {
    const w = mountGroups()
    expect(w.find('[data-test="groups-empty"]').exists()).toBe(true)
    expect(w.find('[data-test="group-new"]').exists()).toBe(true)
  })

  it('mostra cada agrupador com contagem e todas as sessões, mais recente primeiro', () => {
    useGroupsStore().groups = [makeGroup({ id: 1, name: 'Checkout' }), makeGroup({ id: 2, name: 'Vazio', created_at: 1 })]
    useSessionsStore().setForProject(1, [
      makeSession({ session_id: 'a', group_id: 1, last_activity_at: 10, title: 'Velha' }),
      makeSession({ session_id: 'b', group_id: 1, last_activity_at: 20, title: 'Nova', display_state: 'finished' }),
      makeSession({ session_id: 'c', group_id: null }),
    ])
    const w = mountGroups()
    const names = w.findAll('[data-test="group-name"]').map((n) => n.text())
    expect(names).toEqual(['Checkout', 'Vazio'])
    expect(w.findAll('[data-test="group-count"]').map((n) => n.text())).toEqual(['2 conversas · 1 ativa', 'Nenhuma conversa'])
    const first = w.findAll('[data-test="group-section"]')[0]!
    expect(first.findAll('[data-test="row-link"]').map((l) => l.text())).toEqual(['Nova', 'Velha'])
  })

  it('recolhe e expande', async () => {
    useGroupsStore().groups = [makeGroup()]
    useSessionsStore().setForProject(1, [makeSession({ group_id: 1 })])
    const w = mountGroups()
    const toggle = w.find('[data-test="group-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="row-link"]').exists()).toBe(false)
  })

  it('cria com Enter e mostra o erro sem fechar o campo', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/groups': (init) => JSON.parse(String(init?.body)).name === 'dup'
        ? jsonResponse({ detail: 'Já existe um agrupador com esse nome neste projeto.' }, 409)
        : jsonResponse(makeGroup({ id: 7, name: 'Novo' }), 201),
    }))
    const w = mountGroups()
    await w.find('[data-test="group-new"]').trigger('click')
    const input = w.find('[data-test="group-new-name"]')
    await input.setValue('dup')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Já existe')
    expect(w.find('[data-test="group-new-name"]').exists()).toBe(true)
    await input.setValue('Novo')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('[data-test="group-new-name"]').exists()).toBe(false)
    expect(useGroupsStore().byId(7)?.name).toBe('Novo')
  })

  it('Esc fecha o campo de criação sem criar', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const w = mountGroups()
    await w.find('[data-test="group-new"]').trigger('click')
    await w.find('[data-test="group-new-name"]').trigger('keydown', { key: 'Escape' })
    expect(w.find('[data-test="group-new-name"]').exists()).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('renomeia com Enter', async () => {
    useGroupsStore().groups = [makeGroup({ id: 1, name: 'A' })]
    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/groups/1': () => jsonResponse(makeGroup({ id: 1, name: 'B' })) }))
    const w = mountGroups()
    await w.find('[data-test="group-rename"]').trigger('click')
    const input = w.find('[data-test="group-rename-input"]')
    await input.setValue('B')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('[data-test="group-name"]').text()).toBe('B')
  })

  it('remove com confirmação, foco em Cancelar e texto com a contagem', async () => {
    useGroupsStore().groups = [makeGroup({ id: 1, name: 'A' })]
    useSessionsStore().setForProject(1, [makeSession({ session_id: 'a', group_id: 1 }), makeSession({ session_id: 'b', group_id: 1 })])
    vi.stubGlobal('fetch', routeFetch({ 'DELETE /api/groups/1': () => new Response(null, { status: 204 }) }))
    const w = mountGroups()
    await w.find('[data-test="group-remove"]').trigger('click')
    await flushPromises()
    const dialog = w.find('[data-test="group-confirm-remove"]')
    expect(dialog.text()).toContain('Remover o agrupador A?')
    expect(dialog.text()).toContain('As 2 conversas voltam a ficar soltas; nenhuma é apagada.')
    expect(document.activeElement).toBe(w.find('[data-test="group-confirm-cancel"]').element)
    await w.find('[data-test="group-confirm-ok"]').trigger('click')
    await flushPromises()
    expect(useGroupsStore().groups).toEqual([])
  })

  it('"＋ Conversa" abre a nova conversa no agrupador; desabilitado com a pasta indisponível', async () => {
    useGroupsStore().groups = [makeGroup({ id: 3 })]
    const w = mountGroups()
    await w.find('[data-test="group-new-session"]').trigger('click')
    const nc = useNewConversationStore()
    expect([nc.isOpen, nc.presetProjectId, nc.presetGroupId]).toEqual([true, 1, 3])
    const off = mountGroups(false)
    expect(off.find('[data-test="group-new-session"]').attributes('disabled')).toBeDefined()
  })
})
```

Em `frontend/src/views/__tests__/ProjectView.spec.ts`, acrescentar um teste: com um agrupador e as sessões `a` (`group_id: 1`) e `b` (`group_id: null`), a lista por data (as seções com `[data-test="date-group"]`) mostra só `b`, e `[data-test="ungrouped-title"]` existe. Sem agrupadores, `ungrouped-title` não existe. Siga o `mount` e os stubs de `fetch` que o arquivo já usa, e acrescente `'GET /api/groups': () => jsonResponse([...])` se o arquivo carregar tudo por `routeFetch`.

- [ ] **Passo 2: Rodar e ver falhar**

Rodar: `pnpm --dir frontend exec vitest run src/components/groups src/views/__tests__/ProjectView.spec.ts`
Esperado: FAIL (componentes inexistentes).

- [ ] **Passo 3: `GroupSection.vue`**

```vue
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import ConversationRow from '../conversation/ConversationRow.vue'
import { errorMessage } from '../../api/http'
import { isActive } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useNewConversationStore } from '../../stores/newConversation'
import type { Session, SessionGroup } from '../../types/api'

const props = defineProps<{ group: SessionGroup; sessions: Session[]; available: boolean }>()
const emit = defineEmits<{ error: [message: string] }>()

const groups = useGroupsStore()
const newConversation = useNewConversationStore()

const open = ref(true)
const active = computed(() => props.sessions.filter(isActive).length)
const countText = computed(() => {
  const n = props.sessions.length
  if (n === 0) return 'Nenhuma conversa'
  return `${n} ${n === 1 ? 'conversa' : 'conversas'} · ${active.value} ${active.value === 1 ? 'ativa' : 'ativas'}`
})
const removeText = computed(() => {
  const n = props.sessions.length
  if (n === 0) return 'O agrupador está vazio.'
  if (n === 1) return 'A conversa volta a ficar solta; nenhuma é apagada.'
  return `As ${n} conversas voltam a ficar soltas; nenhuma é apagada.`
})

const renaming = ref(false)
const renameValue = ref('')
const renameError = ref<string | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)
async function startRename() {
  renaming.value = true
  confirming.value = false
  renameValue.value = props.group.name
  renameError.value = null
  await nextTick()
  renameInput.value?.select()
}
async function saveRename() {
  renameError.value = null
  try {
    await groups.rename(props.group.id, renameValue.value)
    renaming.value = false
  } catch (e) {
    renameError.value = errorMessage(e)
  }
}

const confirming = ref(false)
const removing = ref(false)
const removeButton = ref<HTMLButtonElement | null>(null)
const cancelButton = ref<HTMLButtonElement | null>(null)
async function askRemove() {
  confirming.value = true
  renaming.value = false
  await nextTick()
  cancelButton.value?.focus()
}
async function cancelRemove() {
  confirming.value = false
  await nextTick()
  removeButton.value?.focus()
}
async function remove() {
  removing.value = true
  try {
    await groups.remove(props.group.id)
  } catch (e) {
    emit('error', errorMessage(e))
    confirming.value = false
  } finally {
    removing.value = false
  }
}
</script>

<template>
  <section data-test="group-section" :aria-label="group.name" class="flex flex-col rounded-lg border border-line">
    <div class="flex min-h-11 flex-wrap items-center gap-2 px-2">
      <button type="button" data-test="group-toggle" :aria-expanded="String(open)" :aria-label="open ? `Recolher ${group.name}` : `Expandir ${group.name}`" class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card" @click="open = !open">
        <span aria-hidden="true" class="inline-block transition-transform" :class="open ? 'rotate-90' : ''">›</span>
      </button>
      <template v-if="renaming">
        <input ref="renameInput" v-model="renameValue" data-test="group-rename-input" aria-label="Novo nome do agrupador" maxlength="80" class="h-8 grow rounded-md border border-line-strong bg-bg px-2 text-sm text-fg outline-none focus:border-primary" @keydown.enter.prevent="saveRename" @keydown.esc.prevent="renaming = false" />
      </template>
      <template v-else>
        <span data-test="group-name" class="min-w-0 truncate font-semibold">{{ group.name }}</span>
        <span data-test="group-count" class="text-xs text-fg-muted">{{ countText }}</span>
      </template>
      <span class="grow" />
      <button type="button" data-test="group-new-session" :disabled="!available" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg disabled:opacity-40" @click="newConversation.open(group.project_id, group.id)">＋ Conversa</button>
      <button type="button" data-test="group-rename" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="startRename">Renomear</button>
      <button ref="removeButton" type="button" data-test="group-remove" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="askRemove">Remover</button>
    </div>
    <p v-if="renameError" role="alert" class="m-0 px-4 pb-2 text-sm text-secondary-soft">{{ renameError }}</p>
    <div
      v-if="confirming"
      data-test="group-confirm-remove"
      role="alertdialog"
      :aria-label="`Remover o agrupador ${group.name}?`"
      class="mx-2 mb-2 flex flex-col gap-2 rounded-lg border border-secondary/60 bg-card px-4 py-3"
      @keydown.esc.prevent="cancelRemove"
    >
      <p class="m-0 text-sm font-semibold">Remover o agrupador {{ group.name }}?</p>
      <p class="m-0 text-sm text-fg-muted">{{ removeText }}</p>
      <div class="flex gap-2">
        <button type="button" data-test="group-confirm-ok" :disabled="removing" class="h-9 rounded-lg bg-secondary px-3 text-sm font-semibold text-secondary-fg hover:bg-secondary-soft disabled:opacity-40" @click="remove">{{ removing ? 'Removendo…' : 'Remover agrupador' }}</button>
        <button ref="cancelButton" type="button" data-test="group-confirm-cancel" class="h-9 rounded-lg border border-line-strong px-3 text-sm text-fg hover:bg-panel" @click="cancelRemove">Cancelar</button>
      </div>
    </div>
    <div v-if="open && sessions.length" class="flex flex-col px-1 pb-1">
      <ConversationRow v-for="s in sessions" :key="s.session_id" :session="s" @error="emit('error', $event)" />
    </div>
  </section>
</template>
```

- [ ] **Passo 4: `ProjectGroups.vue`**

```vue
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import GroupSection from './GroupSection.vue'
import { errorMessage } from '../../api/http'
import { sessionsOf, sortGroups } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ projectId: number; available: boolean }>()
const emit = defineEmits<{ error: [message: string] }>()

const groups = useGroupsStore()
const sessions = useSessionsStore()

const projectSessions = computed(() => sessions.forProject(props.projectId))
const ordered = computed(() => sortGroups(groups.forProject(props.projectId), projectSessions.value))

const creating = ref(false)
const newName = ref('')
const createError = ref<string | null>(null)
const nameInput = ref<HTMLInputElement | null>(null)
async function startCreate() {
  creating.value = true
  newName.value = ''
  createError.value = null
  await nextTick()
  nameInput.value?.focus()
}
async function create() {
  createError.value = null
  try {
    await groups.create(props.projectId, newName.value)
    creating.value = false
  } catch (e) {
    createError.value = errorMessage(e)
  }
}
</script>

<template>
  <section data-test="groups" aria-labelledby="groups-title" class="flex flex-col gap-2">
    <div class="flex items-center gap-2">
      <h2 id="groups-title" class="m-0 grow font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Agrupadores</h2>
      <button type="button" data-test="group-new" class="h-8 rounded-md border border-line-strong px-3 text-xs font-medium text-fg hover:bg-card" @click="startCreate">＋ Agrupador</button>
    </div>
    <div v-if="creating" class="flex flex-col gap-1">
      <input ref="nameInput" v-model="newName" data-test="group-new-name" aria-label="Nome do agrupador" placeholder="Nome do agrupador" maxlength="80" class="h-9 rounded-md border border-line-strong bg-bg px-3 text-sm text-fg outline-none focus:border-primary" @keydown.enter.prevent="create" @keydown.esc.prevent="creating = false" />
      <p v-if="createError" role="alert" class="m-0 text-sm text-secondary-soft">{{ createError }}</p>
    </div>
    <p v-if="ordered.length === 0 && !creating" data-test="groups-empty" class="m-0 text-sm text-fg-muted">
      Junte aqui conversas do mesmo trabalho, como a que escreveu um prompt e a que o executou.
    </p>
    <GroupSection
      v-for="group in ordered"
      :key="group.id"
      :group="group"
      :sessions="sessionsOf(group.id, projectSessions)"
      :available="available"
      @error="emit('error', $event)"
    />
  </section>
</template>
```

- [ ] **Passo 5: `ProjectView.vue`**

- Importar `ProjectGroups` e `useGroupsStore`.
- `const groups = useGroupsStore()`, `const hasGroups = computed(() => groups.forProject(props.id).length > 0)`, `const ungrouped = computed(() => projectSessions.value.filter((s) => s.group_id == null))`, e `dateGroups` sobre `ungrouped.value`.
- No template, logo antes de `<p v-if="sessionsError" ...>`: `<ProjectGroups :project-id="id" :available="project.available" @error="actionError = $event" />`.
- Dentro do `<template v-else>` da lista por data, antes do `v-for`: `<h2 v-if="hasGroups && ungrouped.length" id="ungrouped-title" data-test="ungrouped-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Sem agrupador</h2>`.

- [ ] **Passo 6: Rodar e ver passar**

Rodar: `pnpm --dir frontend exec vitest run src/components/groups src/views/__tests__/ProjectView.spec.ts src/views/__tests__/ProjectViewStates.spec.ts`
Esperado: PASS.

- [ ] **Passo 7: Suíte e compilação**

Rodar: `pnpm --dir frontend test` e `pnpm --dir frontend build`
Esperado: PASS.

- [ ] **Passo 8: Commit (sessão principal)**

Marcar no `ROADMAP.md` os itens "Criar agrupador", "Renomear agrupador", "Remover agrupador..." e "Tela do projeto mostra os agrupadores...".

```bash
git add frontend/src/components/groups frontend/src/views/ProjectView.vue frontend/src/views/__tests__/ProjectView.spec.ts ROADMAP.md
git commit -m "[Feat] Mostrar e gerenciar agrupadores na tela do projeto"
```

---

### Tarefa 5: Mover sessão em Detalhes, etiqueta na linha e no cabeçalho

**Arquivos:**
- Criar: `frontend/src/components/groups/GroupProperty.vue`, `frontend/src/components/groups/GroupTag.vue`
- Modificar: `frontend/src/components/details/DetailsPanel.vue` (depois de `PlanProperty`), `frontend/src/components/conversation/ConversationRow.vue` (depois de `<PlanBadge>`), `frontend/src/components/conversation/ConversationHeader.vue` (depois do chip do projeto, ~linha 186)
- Testar: `frontend/src/components/groups/__tests__/GroupProperty.spec.ts`, `frontend/src/components/groups/__tests__/GroupTag.spec.ts`

**Interfaces:**
- Consome: `useGroupsStore`, `useSessionsStore().setGroup`, `useSessionsStore().find`.
- Produz:
  - `<GroupProperty :session-id="string" :project-id="number" />`: um par `<dt>`/`<dd>` para o `<dl>` de Propriedades.
  - `<GroupTag :group-id="number | null | undefined" />`: não renderiza nada sem agrupador ou quando o agrupador não é conhecido.

Comportamento:
- `GroupProperty`: `<dt>` "Agrupador". `<dd>` com um `<select data-test="prop-group" aria-label="Agrupador">` e as opções "Nenhum" (valor `''`), os agrupadores do projeto em `sortGroups` e "Novo agrupador…" (valor `'__new__'`). O valor selecionado é `String(session.group_id)` quando o agrupador existe na store; senão, `''`. Escolher um agrupador ou "Nenhum" chama `sessions.setGroup(id, valor)`. Escolher "Novo agrupador…" volta o select ao valor atual e mostra um `input` (`data-test="prop-group-new"`, `aria-label="Nome do novo agrupador"`, `maxlength="80"`) com foco. Enter chama `groups.create(projectId, nome)` e depois `sessions.setGroup(id, novo.id)`; Esc fecha. Um erro aparece em `role="alert"` dentro do `<dd>`. Durante a requisição, o select fica desabilitado.
- `GroupTag`: `<span data-test="group-tag" :title="`Agrupador: ${name}`">` com o ícone `▤` (`aria-hidden`) e o nome, truncado com `max-w-40 truncate`, com as classes do `PlanBadge` como referência visual (`text-xs text-fg-muted`, borda `border-line-strong`, `rounded-full px-2`). A cor fica neutra de propósito, porque o agrupador não tem cor.
- `ConversationRow`: `<GroupTag :group-id="session.group_id" />` logo depois de `<PlanBadge :session="session" />`.
- `ConversationHeader`: depois do chip do projeto, `<span v-if="group" data-test="header-group" class="...mesmas classes do chip do projeto...">▤ {{ group.name }}</span>`, com `group = computed(() => listed.value?.group_id != null ? groups.byId(listed.value.group_id) : undefined)`.

- [ ] **Passo 1: Escrever os testes (falham)**

`GroupTag.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import GroupTag from '../GroupTag.vue'
import { useGroupsStore } from '../../../stores/groups'
import { makeGroup } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => { pinia = createPinia(); setActivePinia(pinia) })

describe('etiqueta do agrupador', () => {
  it('mostra o nome do agrupador conhecido', () => {
    useGroupsStore().groups = [makeGroup({ id: 2, name: 'Checkout' })]
    const w = mount(GroupTag, { props: { groupId: 2 }, global: { plugins: [pinia] } })
    expect(w.find('[data-test="group-tag"]').text()).toContain('Checkout')
  })

  it('não mostra nada sem agrupador ou com agrupador desconhecido', () => {
    expect(mount(GroupTag, { props: { groupId: null }, global: { plugins: [pinia] } }).find('[data-test="group-tag"]').exists()).toBe(false)
    expect(mount(GroupTag, { props: { groupId: 99 }, global: { plugins: [pinia] } }).find('[data-test="group-tag"]').exists()).toBe(false)
  })
})
```

`GroupProperty.spec.ts`: monte dentro de um `<dl>` com um componente de teste (`{ components: { GroupProperty }, template: '<dl><GroupProperty session-id="s1" :project-id="1" /></dl>' }`), com pinia real e `routeFetch`. Casos:

1. Opções: com os agrupadores `{1,'A'}` e `{2,'B'}` do projeto 1 e `{3,'X'}` do projeto 2, as opções são `['Nenhum', 'A', 'B', 'Novo agrupador…']` (sem X).
2. Selecionado: com a sessão `s1` em `group_id: 2`, o valor do select é `'2'`. Com `group_id: 99` (agrupador desconhecido, removido em outra aba), o valor é `''`.
3. Mover: `setValue('1')` faz `PATCH /api/sessions/s1` com o corpo `{ group_id: 1 }`. `setValue('')` manda `{ group_id: null }`.
4. Novo agrupador: `setValue('__new__')` mostra `[data-test="prop-group-new"]`. Digitar "Novo" e Enter faz `POST /api/projects/1/groups` com `{ name: 'Novo' }` (resposta `id: 5`) e depois `PATCH /api/sessions/s1` com `{ group_id: 5 }`, e o campo fecha.
5. Erro: `POST` respondendo 409 mostra o `detail` em `[role="alert"]`, deixa o campo aberto e não manda `PATCH`.

- [ ] **Passo 2: Rodar e ver falhar**

Rodar: `pnpm --dir frontend exec vitest run src/components/groups/__tests__/GroupTag.spec.ts src/components/groups/__tests__/GroupProperty.spec.ts`
Esperado: FAIL.

- [ ] **Passo 3: `GroupTag.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useGroupsStore } from '../../stores/groups'

const props = defineProps<{ groupId?: number | null }>()
const groups = useGroupsStore()
// Unknown ids (a group this tab has not loaded yet) show nothing.
const group = computed(() => (props.groupId != null ? groups.byId(props.groupId) : undefined))
</script>

<template>
  <span
    v-if="group"
    data-test="group-tag"
    :title="`Agrupador: ${group.name}`"
    class="flex max-w-40 shrink-0 items-center gap-1 rounded-full border border-line-strong px-2 text-xs text-fg-muted"
  ><span aria-hidden="true">▤</span><span class="truncate">{{ group.name }}</span></span>
</template>
```

- [ ] **Passo 4: `GroupProperty.vue`**

```vue
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { errorMessage } from '../../api/http'
import { sortGroups } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ sessionId: string; projectId: number }>()

const NEW = '__new__'
const groups = useGroupsStore()
const sessions = useSessionsStore()

const options = computed(() => sortGroups(groups.forProject(props.projectId), sessions.forProject(props.projectId)))
const current = computed(() => {
  const id = sessions.find(props.sessionId)?.group_id
  return id != null && groups.byId(id) ? String(id) : ''
})

const busy = ref(false)
const error = ref<string | null>(null)
const creating = ref(false)
const newName = ref('')
const nameInput = ref<HTMLInputElement | null>(null)
const select = ref<HTMLSelectElement | null>(null)

async function run(call: () => Promise<void>): Promise<boolean> {
  busy.value = true
  error.value = null
  try {
    await call()
    return true
  } catch (e) {
    error.value = errorMessage(e)
    return false
  } finally {
    busy.value = false
  }
}

async function onChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value === NEW) {
    // The select goes back to the real group until the new one exists.
    if (select.value) select.value.value = current.value
    creating.value = true
    newName.value = ''
    error.value = null
    await nextTick()
    nameInput.value?.focus()
    return
  }
  await run(() => sessions.setGroup(props.sessionId, value ? Number(value) : null))
}

async function createAndMove() {
  const ok = await run(async () => {
    const group = await groups.create(props.projectId, newName.value)
    await sessions.setGroup(props.sessionId, group.id)
  })
  if (ok) creating.value = false
}
</script>

<template>
  <dt class="text-fg-muted">Agrupador</dt>
  <dd class="m-0 flex min-w-0 flex-col gap-1">
    <select ref="select" data-test="prop-group" aria-label="Agrupador" :value="current" :disabled="busy" class="h-8 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg" @change="onChange">
      <option value="">Nenhum</option>
      <option v-for="g in options" :key="g.id" :value="String(g.id)">{{ g.name }}</option>
      <option :value="NEW">Novo agrupador…</option>
    </select>
    <input v-if="creating" ref="nameInput" v-model="newName" data-test="prop-group-new" aria-label="Nome do novo agrupador" placeholder="Nome do agrupador" maxlength="80" :disabled="busy" class="h-8 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg outline-none focus:border-primary" @keydown.enter.prevent="createAndMove" @keydown.esc.prevent="creating = false" />
    <p v-if="error" role="alert" class="m-0 text-xs text-secondary-soft">{{ error }}</p>
  </dd>
</template>
```

- [ ] **Passo 5: Encaixar nos componentes**

- `DetailsPanel.vue`: importar `GroupProperty` e, logo depois de `<PlanProperty ... />`, pôr `<GroupProperty v-if="projectId != null" :session-id="sessionId" :project-id="projectId" />`.
- `ConversationRow.vue`: importar `GroupTag` e pôr `<GroupTag :group-id="session.group_id" />` depois de `<PlanBadge :session="session" />`.
- `ConversationHeader.vue`: importar `useGroupsStore`, criar o computed `group` descrito acima e o chip `data-test="header-group"` logo depois do chip do projeto.

Acrescentar um teste em `components/conversation/__tests__/ConversationRow.spec.ts` (a linha mostra `[data-test="group-tag"]` com o nome quando a sessão tem agrupador conhecido) e um em `ConversationHeader.spec.ts` (o chip `[data-test="header-group"]` aparece com o nome), no formato dos testes vizinhos.

- [ ] **Passo 6: Rodar e ver passar**

Rodar: `pnpm --dir frontend exec vitest run src/components/groups src/components/conversation src/components/details`
Esperado: PASS.

- [ ] **Passo 7: Suíte e compilação**

Rodar: `pnpm --dir frontend test` e `pnpm --dir frontend build`
Esperado: PASS.

- [ ] **Passo 8: Commit (sessão principal)**

Marcar no `ROADMAP.md` o item "Mover sessão para um agrupador...".

```bash
git add frontend/src/components ROADMAP.md
git commit -m "[Feat] Mover conversa entre agrupadores pelo painel Detalhes"
```

---

### Tarefa 6: Nova conversa dentro do agrupador

**Arquivos:**
- Modificar: `frontend/src/newConversationDraft.ts`, `frontend/src/components/NewConversationModal.vue`, `frontend/src/App.vue` (`currentProjectId`/`onKey`, ~linhas 20-31), `frontend/src/components/sidebar/AppSidebar.vue` (botão `nav-new`)
- Testar: acréscimos em `frontend/src/components/__tests__/NewConversationModal.spec.ts`, `frontend/src/__tests__/App.spec.ts`, `frontend/src/components/sidebar/__tests__/AppSidebar.spec.ts`

**Interfaces:**
- Consome: `useNewConversationStore().presetGroupId`, `open(projectId, groupId)`, `useGroupsStore().forProject`, `sortGroups`, `useSessionsStore().create(projectId, groupId)`.
- Produz: `ConversationDraft.groupId: number | null`.

Comportamento:
- O rascunho ganha `groupId: number | null`. `emptyDraft()` o inicia como `null`, e `loadDraft()` aceita só número (qualquer outra coisa vira `null`).
- O modal ganha, na linha "em [projeto]", um segundo `<select data-test="nc-group" aria-label="Agrupador">` com "Nenhum" (`null`) e os agrupadores do projeto escolhido, em `sortGroups`. Ele fica desabilitado quando `createdId !== null`, igual ao projeto. Com o projeto sem agrupadores, o select não aparece.
- Ao montar, depois de `pickProject()`, `pickGroup()` escolhe o primeiro destes que for um agrupador do projeto escolhido: `store.presetGroupId`, depois `draft.groupId`. Se nenhum for, fica `null`.
- Quando o usuário troca o projeto pelo select (`@change` do `nc-project`), `draft.groupId = null`.
- Se o agrupador escolhido deixar de existir enquanto o modal está aberto (`groups.loaded` e o id fora de `groups.forProject(projectId)`), `draft.groupId = null`.
- No envio, `sessions.create(projectId!, groupId)`.
- `App.vue` e `AppSidebar.vue`: ao abrir o modal a partir de uma conversa (rota `session`), passar também o agrupador dela: `newConversation.open(currentProjectId(), currentGroupId())`, com `currentGroupId()` = `route.name === 'session' ? sessions.find(String(route.params.id))?.group_id ?? null : null`.

- [ ] **Passo 1: Escrever os testes (falham)**

No arquivo de testes do modal, no formato dos testes que já existem (procure por `nc-project`), acrescentar:

1. `presetGroupId` do projeto escolhido: com `open(1, 2)` e o agrupador `{id: 2, project_id: 1}` na store, o select `nc-group` fica com o valor `2`.
2. `presetGroupId` de outro projeto é ignorado e fica "Nenhum".
3. Trocar o projeto no `nc-project` (disparar `change`) volta `nc-group` para "Nenhum".
4. Envio com agrupador: o `POST /api/projects/1/sessions` recebe o corpo `{ group_id: 2 }`.
5. Rascunho: `loadDraft()` com `groupId: 'x'` no `localStorage` devolve `groupId: null`, e com `groupId: 3` devolve `3` (este caso pode ficar num teste de `newConversationDraft` se houver um arquivo próprio; senão, no do modal).
6. Remover o agrupador escolhido na store com o modal aberto volta o select para "Nenhum".

Em `App.spec.ts` (atalho C) e `AppSidebar.spec.ts` (botão `nav-new`): numa rota `/sessions/<id>` de uma sessão com `group_id: 4`, abrir o modal deixa `useNewConversationStore().presetGroupId === 4`.

- [ ] **Passo 2: Rodar e ver falhar**

Rodar: `pnpm --dir frontend exec vitest run src/components/__tests__/NewConversationModal.spec.ts src/components/__tests__/NewConversationModalExtras.spec.ts src/__tests__/App.spec.ts src/components/sidebar/__tests__/AppSidebar.spec.ts`
Esperado: FAIL nos casos novos.

- [ ] **Passo 3: Rascunho**

Em `newConversationDraft.ts`: `groupId: number | null` na interface, `groupId: null` em `emptyDraft()`, e em `loadDraft()`: `groupId: typeof value.groupId === 'number' ? value.groupId : null,`.

- [ ] **Passo 4: Modal**

Em `NewConversationModal.vue`:

```ts
import { sortGroups } from '../groupList'
import { useGroupsStore } from '../stores/groups'
// ...
const groups = useGroupsStore()
const projectGroups = computed(() =>
  draft.value.projectId == null ? [] : sortGroups(groups.forProject(draft.value.projectId), sessions.forProject(draft.value.projectId)),
)

// The group: the one asked for, else the draft's, when it belongs to the chosen project.
function pickGroup() {
  const ids = projectGroups.value.map((g) => g.id)
  const wanted = [store.presetGroupId, draft.value.groupId].find((id) => id != null && ids.includes(id))
  draft.value.groupId = wanted ?? null
}
```

- Em `onMounted`, logo depois de `pickProject()`: `pickGroup()`.
- No `watch(available, ...)`, depois de `pickProject()`: `pickGroup()`.
- Novo watch: `watch(() => projectGroups.value.map((g) => g.id), (ids) => { if (groups.loaded && draft.value.groupId != null && !ids.includes(draft.value.groupId)) draft.value.groupId = null })`.
- No `select` `nc-project`: `@change="draft.groupId = null"`.
- Depois do `label` do projeto, no mesmo bloco:

```vue
          <label v-if="projectGroups.length" class="flex items-center gap-2 text-sm text-fg-muted">
            agrupador
            <select v-model="draft.groupId" data-test="nc-group" aria-label="Agrupador" :disabled="createdId !== null" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg">
              <option :value="null">Nenhum</option>
              <option v-for="g in projectGroups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
          </label>
```

- Em `submit`: `const { projectId, groupId, title, ... } = draft.value` e `sessions.create(projectId!, groupId)`.

- [ ] **Passo 5: Atalho e botão do menu**

Em `App.vue`, acrescentar:

```ts
// The group of the open conversation, so a new one starts next to it.
function currentGroupId(): number | null {
  if (route.name !== 'session') return null
  return sessions.find(String(route.params.id))?.group_id ?? null
}
```

e trocar a chamada por `newConversation.open(currentProjectId(), currentGroupId())`. Em `AppSidebar.vue`, criar o computed `currentGroupId` com a mesma regra e usar `@click="newConversation.open(currentProjectId, currentGroupId)"`.

- [ ] **Passo 6: Rodar e ver passar**

Rodar: `pnpm --dir frontend exec vitest run src/components/__tests__/NewConversationModal.spec.ts src/components/__tests__/NewConversationModalExtras.spec.ts src/__tests__/App.spec.ts src/components/sidebar/__tests__/AppSidebar.spec.ts`
Esperado: PASS.

- [ ] **Passo 7: Suíte e compilação**

Rodar: `pnpm --dir frontend test` e `pnpm --dir frontend build`
Esperado: PASS.

- [ ] **Passo 8: Commit (sessão principal)**

Marcar no `ROADMAP.md` o item "Criar sessão nova já dentro do agrupador...".

```bash
git add frontend/src/newConversationDraft.ts frontend/src/components/NewConversationModal.vue frontend/src/App.vue frontend/src/components/sidebar/AppSidebar.vue frontend/src/components/__tests__/NewConversationModal.spec.ts frontend/src/__tests__/App.spec.ts frontend/src/components/sidebar/__tests__/AppSidebar.spec.ts ROADMAP.md
git commit -m "[Feat] Criar conversa nova no agrupador da conversa aberta"
```

---

### Tarefa 7: Menu lateral em árvore

**Arquivos:**
- Criar: `frontend/src/sidebarTree.ts`, `frontend/src/sidebarCollapse.ts`, `frontend/src/components/sidebar/SidebarGroups.vue`
- Modificar: `frontend/src/components/sidebar/AppSidebar.vue` (bloco `v-for="project in projects.projects"`)
- Testar: `frontend/src/__tests__/sidebarTree.spec.ts`, `frontend/src/__tests__/sidebarCollapse.spec.ts`, `frontend/src/components/sidebar/__tests__/SidebarGroups.spec.ts`, acréscimos em `AppSidebar.spec.ts`

**Interfaces:**
- Consome: `useGroupsStore`, `useSessionsStore`, `sortGroups`, `sessionsOf`, `isActive`, `DisplayStateIcon`.
- Produz:
  - `sidebarTree.ts`: `interface ActiveGroup { group: SessionGroup; sessions: Session[]; waiting: number }` e `projectTree(groups: SessionGroup[], sessions: Session[]): { active: ActiveGroup[]; idle: SessionGroup[] }`. `active` tem os agrupadores com ao menos uma sessão ativa, na ordem de `sortGroups`, cada um só com as sessões ativas (mais recente primeiro). `idle` tem os demais, na ordem de `sortGroups`.
  - `sidebarCollapse.ts`: `isCollapsed(kind: 'project' | 'group', id: number): boolean`, `setCollapsed(kind, id, collapsed: boolean): void` e `collapsed` (um `ref<{ project: number[]; group: number[] }>` reativo, lido do `localStorage` na chave `vibing:sidebar-collapsed`). Guarda os ids recolhidos, e o padrão é aberto. Leitura e escrita ficam em try/catch.
  - `<SidebarGroups :project-id="number" />`: a árvore de um projeto.

Comportamento (da spec, seção 4, "Menu lateral"):
- A linha do projeto passa a ser um `div` com dois filhos: um botão de seta (`data-test="project-toggle"`, `aria-expanded`, `aria-label="Recolher {nome}"` ou `"Expandir {nome}"`), que só aparece quando o projeto tem agrupadores, e o `RouterLink` que já existe (que continua abrindo a tela do projeto). Sem seta, um espaçador da mesma largura mantém o alinhamento. Não pôr `button` dentro de `a`.
- Com o projeto aberto e com agrupadores, `<SidebarGroups :project-id>` aparece logo abaixo da linha, recuado (`pl-6`).
- Em `SidebarGroups`, cada agrupador ativo tem uma linha `data-test="sidebar-group"` com seta (`data-test="group-toggle"`, `aria-expanded`), `▤`, nome truncado e, se `waiting > 0`, `DisplayStateIcon display="waiting"` com o número (`data-test="group-waiting"`). Aberto, mostra as sessões como `RouterLink` (`data-test="sidebar-session"`) para `{ name: 'session', params: { id } }`, com `DisplayStateIcon` e título truncado. A sessão da rota atual recebe `aria-current="page"` e o destaque `bg-elevated text-fg`.
- Cada agrupador parado tem uma linha `RouterLink` (`data-test="sidebar-group-idle"`) para a tela do projeto, com `opacity-50`, `▤` e o nome, sem seta.
- As alturas mínimas seguem o menu (`min-h-9` nas linhas internas; o menu já usa `min-h-10` nos itens principais).

- [ ] **Passo 1: Escrever os testes (falham)**

`frontend/src/__tests__/sidebarTree.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { projectTree } from '../sidebarTree'
import { makeGroup, makeSession } from '../test/factories'

describe('árvore do menu', () => {
  it('separa agrupadores com sessão ativa dos parados e só lista as ativas', () => {
    const groups = [makeGroup({ id: 1, name: 'A' }), makeGroup({ id: 2, name: 'B' }), makeGroup({ id: 3, name: 'Vazio' })]
    const sessions = [
      makeSession({ session_id: 'a1', group_id: 1, last_activity_at: 10, display_state: 'waiting' }),
      makeSession({ session_id: 'a2', group_id: 1, last_activity_at: 20, display_state: 'finished' }),
      makeSession({ session_id: 'a3', group_id: 1, last_activity_at: 30, display_state: 'running' }),
      makeSession({ session_id: 'b1', group_id: 2, display_state: 'finished' }),
    ]
    const tree = projectTree(groups, sessions)
    expect(tree.active.map((g) => g.group.id)).toEqual([1])
    expect(tree.active[0]!.sessions.map((s) => s.session_id)).toEqual(['a3', 'a1'])
    expect(tree.active[0]!.waiting).toBe(1)
    expect(tree.idle.map((g) => g.id).sort()).toEqual([2, 3])
  })
})
```

`frontend/src/__tests__/sidebarCollapse.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => { localStorage.clear(); vi.resetModules() })
afterEach(() => vi.restoreAllMocks())

describe('estado recolhido do menu', () => {
  it('começa aberto, guarda e relê', async () => {
    const first = await import('../sidebarCollapse')
    expect(first.isCollapsed('project', 1)).toBe(false)
    first.setCollapsed('project', 1, true)
    first.setCollapsed('group', 7, true)
    vi.resetModules()
    const again = await import('../sidebarCollapse')
    expect(again.isCollapsed('project', 1)).toBe(true)
    expect(again.isCollapsed('group', 7)).toBe(true)
    again.setCollapsed('group', 7, false)
    expect(again.isCollapsed('group', 7)).toBe(false)
  })

  it('funciona com o localStorage quebrado', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('x') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('x') })
    const mod = await import('../sidebarCollapse')
    expect(mod.isCollapsed('project', 1)).toBe(false)
    mod.setCollapsed('project', 1, true)
    expect(mod.isCollapsed('project', 1)).toBe(true)
  })

  it('ignora conteúdo inválido', async () => {
    localStorage.setItem('vibing:sidebar-collapsed', '{"project":"x"}')
    const mod = await import('../sidebarCollapse')
    expect(mod.isCollapsed('project', 1)).toBe(false)
  })
})
```

`SidebarGroups.spec.ts` (pinia real e router de memória, como no `AppSidebar.spec.ts`), com os casos:
1. Com um agrupador ativo e um parado, existe um `sidebar-group` e um `sidebar-group-idle`, e o `href` deste último é `/projects/1`.
2. As sessões finalizadas do agrupador ativo não aparecem, e as ativas aparecem com `href` `/sessions/<id>`.
3. O `group-toggle` recolhe: as `sidebar-session` somem, e `isCollapsed('group', id)` passa a `true`.
4. `group-waiting` mostra `1` quando uma sessão aguarda.
5. Com a rota em `/sessions/a1`, a linha dessa sessão tem `aria-current="page"`.

Em `AppSidebar.spec.ts`:
1. Um projeto sem agrupador não tem `project-toggle`.
2. Um projeto com agrupador tem `project-toggle` com `aria-expanded="true"` e mostra `sidebar-group`. Clicar recolhe, e o `sidebar-group` some.
3. Clicar no nome do projeto (o link `data-test="project"`) continua levando a `/projects/1`.

Confira os testes que já existem em `AppSidebar.spec.ts` e `AppSidebarStates.spec.ts` que procuram `[data-test="project"]`. O atributo continua no `RouterLink`, então eles devem seguir passando sem mudança.

- [ ] **Passo 2: Rodar e ver falhar**

Rodar: `pnpm --dir frontend exec vitest run src/__tests__/sidebarTree.spec.ts src/__tests__/sidebarCollapse.spec.ts src/components/sidebar`
Esperado: FAIL.

- [ ] **Passo 3: `sidebarTree.ts`**

```ts
import { isActive, sessionsOf, sortGroups } from './groupList'
import type { Session, SessionGroup } from './types/api'

export interface ActiveGroup {
  group: SessionGroup
  sessions: Session[]
  waiting: number
}

/** Groups of one project for the sidebar: those with active sessions (only those listed) and the idle rest. */
export function projectTree(groups: SessionGroup[], sessions: Session[]): { active: ActiveGroup[]; idle: SessionGroup[] } {
  const active: ActiveGroup[] = []
  const idle: SessionGroup[] = []
  for (const group of sortGroups(groups, sessions)) {
    const open = sessionsOf(group.id, sessions).filter(isActive)
    if (open.length === 0) idle.push(group)
    else active.push({ group, sessions: open, waiting: open.filter((s) => s.display_state === 'waiting').length })
  }
  return { active, idle }
}
```

- [ ] **Passo 4: `sidebarCollapse.ts`**

```ts
import { ref } from 'vue'

const KEY = 'vibing:sidebar-collapsed'

type Kind = 'project' | 'group'
type State = Record<Kind, number[]>

function ids(value: unknown): number[] {
  return Array.isArray(value) ? value.filter((v): v is number => Number.isInteger(v)) : []
}

function read(): State {
  try {
    const raw = localStorage.getItem(KEY)
    const value = raw ? (JSON.parse(raw) as Partial<State>) : {}
    return { project: ids(value?.project), group: ids(value?.group) }
  } catch {
    return { project: [], group: [] }
  }
}

/** Projects and groups the user collapsed in the sidebar. Everything else is open. */
export const collapsed = ref<State>(read())

export function isCollapsed(kind: Kind, id: number): boolean {
  return collapsed.value[kind].includes(id)
}

export function setCollapsed(kind: Kind, id: number, value: boolean): void {
  const rest = collapsed.value[kind].filter((v) => v !== id)
  collapsed.value = { ...collapsed.value, [kind]: value ? [...rest, id] : rest }
  try {
    localStorage.setItem(KEY, JSON.stringify(collapsed.value))
  } catch {
    // Without storage the choice lasts while the page is open.
  }
}
```

- [ ] **Passo 5: `SidebarGroups.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { isCollapsed, setCollapsed } from '../../sidebarCollapse'
import { projectTree } from '../../sidebarTree'
import { useGroupsStore } from '../../stores/groups'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ projectId: number }>()
const groups = useGroupsStore()
const sessions = useSessionsStore()
const route = useRoute()

const tree = computed(() => projectTree(groups.forProject(props.projectId), sessions.forProject(props.projectId)))
const isCurrent = (id: string) => route.name === 'session' && route.params.id === id
const rowClass = 'flex min-h-9 items-center gap-2 rounded-lg px-2 no-underline hover:bg-card'
</script>

<template>
  <div class="flex flex-col gap-0.5 pl-6">
    <div v-for="item in tree.active" :key="item.group.id" data-test="sidebar-group" class="flex flex-col">
      <button
        type="button"
        data-test="group-toggle"
        :aria-expanded="String(!isCollapsed('group', item.group.id))"
        :class="rowClass"
        class="w-full text-left text-fg-muted hover:text-fg"
        @click="setCollapsed('group', item.group.id, !isCollapsed('group', item.group.id))"
      >
        <span aria-hidden="true" class="inline-block w-3 transition-transform" :class="isCollapsed('group', item.group.id) ? '' : 'rotate-90'">›</span>
        <span aria-hidden="true">▤</span>
        <span class="min-w-0 grow truncate text-[13px]">{{ item.group.name }}</span>
        <span v-if="item.waiting" data-test="group-waiting" class="flex items-center gap-1 text-xs text-secondary">
          <DisplayStateIcon display="waiting" :size="11" />{{ item.waiting }}
        </span>
      </button>
      <template v-if="!isCollapsed('group', item.group.id)">
        <RouterLink
          v-for="s in item.sessions"
          :key="s.session_id"
          data-test="sidebar-session"
          :to="{ name: 'session', params: { id: s.session_id } }"
          :aria-current="isCurrent(s.session_id) ? 'page' : undefined"
          :class="[rowClass, 'pl-7', isCurrent(s.session_id) ? 'bg-elevated text-fg' : 'text-fg-muted hover:text-fg']"
        >
          <DisplayStateIcon :display="s.display_state" :size="11" />
          <span class="min-w-0 grow truncate text-[13px]">{{ s.title }}</span>
        </RouterLink>
      </template>
    </div>
    <RouterLink
      v-for="g in tree.idle"
      :key="g.id"
      data-test="sidebar-group-idle"
      :to="{ name: 'project', params: { id: projectId } }"
      :title="`${g.name}: sem conversas ativas`"
      :class="[rowClass, 'text-fg-muted opacity-50 hover:opacity-100']"
    >
      <span aria-hidden="true" class="w-3" />
      <span aria-hidden="true">▤</span>
      <span class="min-w-0 grow truncate text-[13px]">{{ g.name }}</span>
    </RouterLink>
  </div>
</template>
```

- [ ] **Passo 6: `AppSidebar.vue`**

Importar `SidebarGroups`, `useGroupsStore`, `isCollapsed` e `setCollapsed`. Trocar o `RouterLink` do `v-for` de projetos por:

```vue
      <template v-for="project in projects.projects" :key="project.id">
        <div class="flex items-center">
          <button
            v-if="groups.forProject(project.id).length"
            type="button"
            data-test="project-toggle"
            :aria-expanded="String(!isCollapsed('project', project.id))"
            :aria-label="`${isCollapsed('project', project.id) ? 'Expandir' : 'Recolher'} ${project.name}`"
            class="flex size-6 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
            @click="setCollapsed('project', project.id, !isCollapsed('project', project.id))"
          ><span aria-hidden="true" class="inline-block transition-transform" :class="isCollapsed('project', project.id) ? '' : 'rotate-90'">›</span></button>
          <span v-else class="size-6 shrink-0" aria-hidden="true" />
          <RouterLink
            data-test="project"
            ... (os mesmos atributos, classes e conteúdo de hoje, com `class` acrescido de `min-w-0 grow`)
          >
            ...
          </RouterLink>
        </div>
        <SidebarGroups v-if="groups.forProject(project.id).length && !isCollapsed('project', project.id)" :project-id="project.id" />
      </template>
```

com `const groups = useGroupsStore()` no `<script setup>`. O conteúdo interno do `RouterLink` (cor, nome, branch, limite de repositórios, contagem de espera) não muda.

- [ ] **Passo 7: Rodar e ver passar**

Rodar: `pnpm --dir frontend exec vitest run src/__tests__/sidebarTree.spec.ts src/__tests__/sidebarCollapse.spec.ts src/components/sidebar`
Esperado: PASS.

- [ ] **Passo 8: Suíte e compilação**

Rodar: `pnpm --dir frontend test` e `pnpm --dir frontend build`
Esperado: PASS.

- [ ] **Passo 9: Commit (sessão principal)**

Marcar no `ROADMAP.md` o item "Menu lateral: cada projeto vira uma árvore...".

```bash
git add frontend/src/sidebarTree.ts frontend/src/sidebarCollapse.ts frontend/src/components/sidebar frontend/src/__tests__/sidebarTree.spec.ts frontend/src/__tests__/sidebarCollapse.spec.ts ROADMAP.md
git commit -m "[Feat] Mostrar agrupadores em árvore no menu lateral"
```

---

### Tarefa 8: Filtro e busca por agrupador na tela Conversas

**Arquivos:**
- Modificar: `frontend/src/views/ConversationsView.vue`
- Testar: acréscimos em `frontend/src/views/__tests__/ConversationsView.spec.ts`

**Interfaces:**
- Consome: `useGroupsStore().forProject`, `useGroupsStore().byId`, `sortGroups`.
- Produz: a query `agrupador`, com `''` (todos), `'sem'` (sem agrupador) ou o id do agrupador.

Comportamento:
- Um `<select data-test="conversations-group" aria-label="Agrupador">` logo depois do select de projeto, visível só com `projectId` escolhido e com agrupadores nesse projeto. As opções são "Todos os agrupadores" (`''`), "Sem agrupador" (`'sem'`) e os agrupadores do projeto em `sortGroups`.
- O filtro: com `'sem'`, só as sessões com `group_id == null`; com um id, só as sessões com esse `group_id`. Um id que não é do projeto escolhido é ignorado e tratado como `''`.
- Trocar o projeto limpa `agrupador` na mesma navegação: `router.replace({ query: { ...route.query, projeto: value || undefined, agrupador: undefined } })`, pelo mesmo encadeamento `navigation` que `setQuery` usa. Crie `setProject(value: string)` para isso.
- A busca de texto também compara `groups.byId(s.group_id)?.name`, com o mesmo `toLocaleLowerCase('pt-BR')` usado no título.

- [ ] **Passo 1: Escrever os testes (falham)**

Em `ConversationsView.spec.ts`, no formato dos testes de filtro que já existem ali (procure `conversations-project`), acrescentar:

1. Sem projeto escolhido, `conversations-group` não existe.
2. Com `?projeto=1` e os agrupadores `{1,'A'}` e `{2,'B'}`, as opções são `['Todos os agrupadores', 'Sem agrupador', 'A', 'B']` (ou na ordem de `sortGroups` para as sessões do teste).
3. `?projeto=1&agrupador=1` mostra só as sessões com `group_id: 1`, e `?projeto=1&agrupador=sem` só as sem agrupador.
4. Trocar o projeto no select remove `agrupador` da query (confira `router.currentRoute.value.query`).
5. `?busca=checkout` encontra a sessão de título "Ajustar botão" que está no agrupador "Checkout".

- [ ] **Passo 2: Rodar e ver falhar**

Rodar: `pnpm --dir frontend exec vitest run src/views/__tests__/ConversationsView.spec.ts`
Esperado: FAIL nos casos novos.

- [ ] **Passo 3: Implementar**

Em `ConversationsView.vue`:

```ts
import { sortGroups } from '../groupList'
import { useGroupsStore } from '../stores/groups'
// ...
const groups = useGroupsStore()
const projectGroups = computed(() => {
  if (!projectId.value) return []
  const id = Number(projectId.value)
  return sortGroups(groups.forProject(id), sessions.forProject(id))
})
// '' = all, 'sem' = loose ones, else a group of the chosen project (any other id counts as '').
const groupFilter = computed(() => {
  const v = text(route.query.agrupador)
  if (v === 'sem') return v
  return projectGroups.value.some((g) => String(g.id) === v) ? v : ''
})

function setProject(value: string) {
  navigation = navigation
    .then(() => router.replace({ query: { ...route.query, projeto: value || undefined, agrupador: undefined } }))
    .catch(() => {})
}
```

No `filtered`, depois do filtro de projeto:

```ts
    if (groupFilter.value === 'sem' && s.group_id != null) return false
    if (groupFilter.value && groupFilter.value !== 'sem' && String(s.group_id) !== groupFilter.value) return false
    if (!q) return true
    const groupName = s.group_id != null ? groups.byId(s.group_id)?.name ?? '' : ''
    return s.title.toLocaleLowerCase('pt-BR').includes(q) || groupName.toLocaleLowerCase('pt-BR').includes(q)
```

(Isso substitui o `return !q || s.title...` que existe hoje.)

No template, o select de projeto passa a chamar `@change="setProject(($event.target as HTMLSelectElement).value)"` e, logo depois dele:

```vue
      <select v-if="projectGroups.length" :value="groupFilter" data-test="conversations-group" aria-label="Agrupador" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg" @change="setQuery('agrupador', ($event.target as HTMLSelectElement).value)">
        <option value="">Todos os agrupadores</option>
        <option value="sem">Sem agrupador</option>
        <option v-for="g in projectGroups" :key="g.id" :value="String(g.id)">{{ g.name }}</option>
      </select>
```

`SessionSearch.vue` não muda: o placeholder "Procurar sessões" não lista campos, e a busca do backend já cobre o nome do agrupador desde a Tarefa 2.

- [ ] **Passo 4: Rodar e ver passar**

Rodar: `pnpm --dir frontend exec vitest run src/views/__tests__/ConversationsView.spec.ts`
Esperado: PASS.

- [ ] **Passo 5: Suítes e compilação**

Rodar: `uv run pytest -q`, `pnpm --dir frontend test` e `pnpm --dir frontend build`
Esperado: tudo passa.

- [ ] **Passo 6: Commit (sessão principal)**

Marcar no `ROADMAP.md` os itens "Etiqueta do agrupador na linha de conversa e filtro..." e "Busca de sessões também encontra pelo nome do agrupador".

```bash
git add frontend/src/views/ConversationsView.vue frontend/src/views/__tests__/ConversationsView.spec.ts ROADMAP.md
git commit -m "[Feat] Filtrar e buscar conversas por agrupador"
```

---

## Fim do marco

Depois da Tarefa 8, a sessão principal chama o `milestone-reviewer` sobre o intervalo de commits do marco. Com a aprovação, troca o estado do marco 8 no `ROADMAP.md` para "Concluído", registra no changelog (se o roadmap tiver essa seção) e faz o commit `[Docs] Concluir marco 8 de agrupador de sessões`.
