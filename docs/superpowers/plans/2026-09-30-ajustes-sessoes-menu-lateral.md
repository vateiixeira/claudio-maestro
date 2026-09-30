# Ajustes de sessões e menu lateral: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nove ajustes pedidos em 2026-09-30:
- Detalhes redimensionável.
- Conversas do terminal em execução no menu lateral.
- Seção "Em execução".
- Renomear só pelo título.
- Worktree da sessão visível.
- Sigla do projeto nas linhas do menu.
- Ditado no modal de nova conversa.
- Recentes com ordem estável.
- Plano no painel Detalhes.

**Architecture:**
- **Backend:** passa a indexar as sessões guardadas nas pastas de histórico das worktrees de cada repositório, listadas por `run_git`. Grava onde a transcrição está (`history_dir`), a worktree atual (lida do último `cwd` da transcrição) e o branch mais recente. Uma conversa do CLI no meio de um turno passa a contar como `running`.
- **Frontend:** mostra esses dados e reorganiza o menu lateral em componentes pequenos: `SidebarRunning`, `SidebarSessionRow`, `ProjectBadge`.

**Tech Stack:** Python 3.13, FastAPI, SQLite, pytest (uv). Vue 3, Pinia, Vue Router, Tailwind, Vitest (pnpm).

**Spec:** `docs/superpowers/specs/2026-09-30-ajustes-sessoes-menu-lateral-design.md`

## Global Constraints

- **Pasta de trabalho:** a worktree `/home/vi/dev/vini7-vibing/.claude/worktrees/melhorias-ui-sessoes`, branch `worktree-melhorias-ui-sessoes`. Todos os comandos rodam a partir dela.
- **Comandos:** `uv run pytest` (backend) e `pnpm --dir frontend test` (frontend). Nunca `npx` nem `yarn`.
- **Git:** todo `git` do backend passa por `run_git` em `backend/vibing/gitinfo.py`. Nada de `subprocess` com git.
- **Idioma:** textos da interface em português brasileiro. Código e identificadores em inglês.
- **Marca:** não usar "Claude Code" na interface.
- **Testes:** escritos antes do código que cobrem. Os automatizados nunca tocam o SDK real.
- **Subagentes:** não fazem commit nem `git add`. Quem commita é a sessão principal, depois de o `reviewer` aprovar.
- **Commits:** `[Tipo] Título` em português, verbo no infinitivo, até 72 caracteres, sem ponto final, terminando com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Banco:** o backend desta worktree nunca roda contra o banco real (`~/.local/share/vini7-vibing`). Teste manual usa `VIBING_DATA_DIR` numa pasta temporária.
- **Migração:** a migração nova fica no fim de `MIGRATIONS`. Na junção com o `main`, continua depois das que já estiverem lá (o marco 8 também cria migrações).
- **Rótulo de worktree:** `worktree <nome> · <branch>`, ou `worktree <nome>` sem branch.
- **Largura do Detalhes:** padrão 360 px, mínimo 300 px, máximo `min(70vw, janela − 400 px)`, passo de 16 px no teclado, chave `vibing:details-width`.
- **Menu lateral:** "Em execução" mostra até 8 linhas. "Recentes" mostra até 5.

## Review Focus

1. **Transcrição que muda de pasta no meio da sessão (`EnterWorktree`).** A sessão continua no mesmo projeto, com o mesmo id, e passa a mostrar a worktree em até uma passada do watcher mais uma sincronização. Nunca vira uma sessão duplicada. Coberto na Tarefa 4, em `test_session_moved_to_worktree_keeps_row_and_gains_history_dir`.
2. **Worktree apagada depois de usada.** A sessão continua listada, abrível e com o último rótulo conhecido, porque as leituras do SDK usam `history_dir`. Coberto nas Tarefas 4 e 5.
3. **Submódulo com `.git` em arquivo.** Não é worktree, então não pode mostrar rótulo. Coberto na Tarefa 1, em `test_worktree_of_submodule_is_not_a_worktree`.
4. **Clicar em Recentes numa sessão já visível.** Não reordena, mas uma sessão fora da lista visível vai para o topo. Coberto na Tarefa 10.
5. **Largura salva maior que a janela atual**, por exemplo depois de trocar de monitor. O painel ajusta ao máximo sem estourar a tela. Coberto na Tarefa 8, em `ajusta largura salva acima do máximo`.

---

### Task 1: Funções de worktree (`worktree.py`)

**Files:**
- Create: `backend/vibing/worktree.py`
- Test: `backend/tests/test_worktree.py`

**Interfaces:**
- Produces:
  - `Worktree(name: str, path: str)`: dataclass congelada.
  - `last_cwd(path: Path, tail_bytes: int = TAIL_BYTES) -> str | None`
  - `worktree_of(cwd: str) -> Worktree | None`
  - `current_worktree(transcript: Path) -> tuple[bool, Worktree | None]`: o primeiro item diz se decidiu. `False` significa manter o que estava gravado.
  - `parse_worktree_list(output: str) -> list[str]`

- [x] **Step 1: Escrever os testes que falham**

```python
"""Worktree detection from transcripts and `.git` markers (no git process)."""

import json
from pathlib import Path

from vibing.worktree import (
    Worktree, current_worktree, last_cwd, parse_worktree_list, worktree_of,
)


def _jsonl(path: Path, *entries: dict) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


def _linked(root: Path, name: str) -> Path:
    """A folder that looks like a linked worktree of `root`."""
    wt = root / ".claude" / "worktrees" / name
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {root}/.git/worktrees/{name}\n")
    return wt


def test_last_cwd_returns_the_newest_entry(tmp_path: Path):
    f = _jsonl(tmp_path / "s.jsonl", {"cwd": "/a"}, {"type": "x"}, {"cwd": "/b/c d"})
    assert last_cwd(f) == "/b/c d"


def test_last_cwd_reads_only_the_tail_and_survives_a_cut_line(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    big = json.dumps({"cwd": "/old", "pad": "x" * 200_000}) + "\n"
    f.write_text(big + json.dumps({"cwd": "/new"}) + "\n" + '{"cwd": "/par')
    assert last_cwd(f, tail_bytes=1024) == "/new"


def test_last_cwd_unescapes_json(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    f.write_text('{"cwd": "/a/\\u00e7\\"q"}\n')
    assert last_cwd(f) == '/a/ç"q'


def test_last_cwd_missing_file_or_no_cwd(tmp_path: Path):
    assert last_cwd(tmp_path / "nada.jsonl") is None
    assert last_cwd(_jsonl(tmp_path / "s.jsonl", {"type": "x"})) is None


def test_worktree_of_linked_worktree_and_subfolder(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    wt = _linked(tmp_path, "melhorias")
    (wt / "backend").mkdir()
    expected = Worktree(name="melhorias", path=str(wt))
    assert worktree_of(str(wt)) == expected
    assert worktree_of(str(wt / "backend")) == expected


def test_worktree_of_main_checkout_is_none(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    assert worktree_of(str(tmp_path / "src")) is None


def test_worktree_of_submodule_is_not_a_worktree(tmp_path: Path):
    sub = tmp_path / "lib"
    sub.mkdir()
    (sub / ".git").write_text(f"gitdir: {tmp_path}/.git/modules/lib\n")
    assert worktree_of(str(sub)) is None


def test_worktree_of_outside_git_is_none(tmp_path: Path):
    assert worktree_of(str(tmp_path)) is None


def test_current_worktree_decides_only_for_existing_folders(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    wt = _linked(tmp_path, "x")
    f = _jsonl(tmp_path / "a.jsonl", {"cwd": str(tmp_path)}, {"cwd": str(wt)})
    assert current_worktree(f) == (True, Worktree(name="x", path=str(wt)))
    g = _jsonl(tmp_path / "b.jsonl", {"cwd": str(tmp_path)})
    assert current_worktree(g) == (True, None)
    h = _jsonl(tmp_path / "c.jsonl", {"cwd": str(tmp_path / "apagada")})
    assert current_worktree(h) == (False, None)
    assert current_worktree(tmp_path / "nenhum.jsonl") == (False, None)


def test_parse_worktree_list():
    out = (
        "worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n"
        "worktree /repo/.worktrees/a b\nHEAD def\ndetached\n\n"
    )
    assert parse_worktree_list(out) == ["/repo", "/repo/.worktrees/a b"]
    assert parse_worktree_list("") == []
```

- [x] **Step 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_worktree.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'vibing.worktree'`

- [x] **Step 3: Implementar**

```python
"""Which git worktree a session is working in, read from its transcript.

A linked worktree has a `.git` *file* whose `gitdir:` points into
`<main repo>/.git/worktrees/<id>`. Submodules also use a `.git` file, but it
points into `.git/modules/`, so they do not count. No git process is started.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

TAIL_BYTES = 64 * 1024
_CWD = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Worktree:
    name: str
    path: str


def last_cwd(path: Path, tail_bytes: int = TAIL_BYTES) -> str | None:
    """Last `cwd` value in the last `tail_bytes` of a `.jsonl` transcript."""
    try:
        with open(path, "rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - tail_bytes))
            data = file.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    matches = _CWD.findall(data)
    if not matches:
        return None
    try:
        return json.loads(f'"{matches[-1]}"')
    except ValueError:
        return None


def worktree_of(cwd: str) -> Worktree | None:
    """The linked worktree containing `cwd`, or None (main checkout, submodule, no git)."""
    folder = Path(cwd)
    for candidate in (folder, *folder.parents):
        marker = candidate / ".git"
        try:
            if marker.is_dir():
                return None
            if not marker.is_file():
                continue
            text = marker.read_text(errors="replace")[:4096]
        except OSError:
            return None
        for line in text.splitlines():
            if line.startswith("gitdir:"):
                parts = Path(line[len("gitdir:"):].strip()).parts
                if len(parts) >= 2 and parts[-2] == "worktrees":
                    return Worktree(name=candidate.name, path=str(candidate))
                return None
        return None
    return None


def current_worktree(transcript: Path) -> tuple[bool, Worktree | None]:
    """(decided, worktree) for the session's latest folder.

    Not decided when the last `cwd` is unknown or its folder is gone (a removed
    worktree): the caller keeps what it had.
    """
    cwd = last_cwd(transcript)
    if cwd is None or not Path(cwd).is_dir():
        return False, None
    return True, worktree_of(cwd)


def parse_worktree_list(output: str) -> list[str]:
    """Paths in `git worktree list --porcelain` output, main checkout first."""
    return [line[len("worktree "):] for line in output.splitlines() if line.startswith("worktree ")]
```

- [x] **Step 4: Rodar e ver passar**

Run: `uv run pytest backend/tests/test_worktree.py -q`
Expected: PASS (10 testes)

- [x] **Step 5: Commit**

```bash
git add backend/vibing/worktree.py backend/tests/test_worktree.py
git commit -m "[Feat] Detectar worktree atual a partir da transcrição"
```

---

### Task 2: Colunas novas da sessão e campos na API

**Files:**
- Modify:
  - `backend/vibing/db.py`: fim de `MIGRATIONS`, perto da linha 106.
  - `backend/vibing/sessions.py`: `SessionRecord` (linha 232), `_COLUMNS` e `_INTERNAL_FIELDS` (linhas 274–286).
  - `backend/vibing/api/sessions.py`: `SessionOut` (linhas 76–114).
- Test:
  - `backend/tests/test_db.py`
  - `backend/tests/test_sessions_api.py`, ou o arquivo que já testa `describe`/listagem. Procure com `grep -rn "def test.*describe\|cli_running" backend/tests`.

**Interfaces:**
- Produces:
  - Colunas `history_dir`, `worktree_name`, `worktree_path` e `git_branch` (TEXT, nulas) em `sessions`.
  - Campos `SessionRecord.history_dir`, `.worktree_name`, `.worktree_path` e `.git_branch`, todos `str | None = None`.
  - Propriedade `SessionRecord.history_directory -> str`, que vale `history_dir or cwd`.
  - Método `SessionRecord.work_dir() -> str`, que devolve `worktree_path` se a pasta existe, senão `cwd`.
  - `describe()` devolve `worktree_name`, `worktree_path` e `git_branch`, mas não `history_dir`.
  - `SessionOut` ganha os três campos, opcionais.

- [x] **Step 1: Testes que falham**

Em `backend/tests/test_db.py`:

```python
def test_sessions_have_worktree_columns(tmp_path: Path):
    path = tmp_path / "v.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert {"history_dir", "worktree_name", "worktree_path", "git_branch"} <= cols
```

Use os mesmos imports e o mesmo helper de criação de banco que o arquivo já usa. Se `init_db` tiver outro nome, siga o de `test_migrate_creates_tables`.

No arquivo que testa `describe` (ou num novo `backend/tests/test_session_record.py`):

```python
from pathlib import Path

from vibing.sessions import SessionRecord, describe


def _record(**extra) -> SessionRecord:
    return SessionRecord(
        session_id="s", project_id=1, cwd="/p", title="t", created_at=1, last_activity_at=1, **extra,
    )


def test_describe_exposes_worktree_but_not_history_dir():
    out = describe(
        _record(history_dir="/p/.wt/a", worktree_name="a", worktree_path="/p/.wt/a", git_branch="feat"),
        "closed", None, 0, finished_after=3600, now=2,
    )
    assert out["worktree_name"] == "a"
    assert out["worktree_path"] == "/p/.wt/a"
    assert out["git_branch"] == "feat"
    assert "history_dir" not in out


def test_history_directory_and_work_dir(tmp_path: Path):
    assert _record().history_directory == "/p"
    assert _record(history_dir="/h").history_directory == "/h"
    wt = tmp_path / "wt"
    wt.mkdir()
    assert _record(worktree_path=str(wt)).work_dir() == str(wt)
    assert _record(worktree_path=str(tmp_path / "gone")).work_dir() == "/p"
    assert _record().work_dir() == "/p"
```

No teste de API que lista sessões (por exemplo, o que já confere `cli_running` em `GET /api/projects/{id}/sessions`), acrescente uma verificação de que a resposta traz `worktree_name`, `worktree_path` e `git_branch`, com `None` numa sessão comum.

- [x] **Step 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_db.py backend/tests/test_session_record.py -q`
Expected: FAIL com as colunas ausentes e `TypeError: unexpected keyword argument 'history_dir'`.

- [x] **Step 3: Implementar**

`backend/vibing/db.py`, no fim de `MIGRATIONS`:

```python
    [
        # Ajustes de sessões: folder whose history holds the transcript when it is not
        # the cwd (sessions moved into a worktree), the worktree the session is in now
        # and the newest git branch of the transcript.
        "ALTER TABLE sessions ADD COLUMN history_dir TEXT",
        "ALTER TABLE sessions ADD COLUMN worktree_name TEXT",
        "ALTER TABLE sessions ADD COLUMN worktree_path TEXT",
        "ALTER TABLE sessions ADD COLUMN git_branch TEXT",
    ],
```

`backend/vibing/sessions.py`, no fim dos campos de `SessionRecord`:

```python
    # Folder whose CLI history holds the transcript, when it differs from `cwd` (the
    # CLI moves the file when a session enters a worktree). SDK reads use it.
    history_dir: str | None = None
    # Linked worktree the session works in now (from the transcript's last cwd).
    worktree_name: str | None = None
    worktree_path: str | None = None
    # Newest git branch recorded in the transcript.
    git_branch: str | None = None

    @property
    def history_directory(self) -> str:
        """Directory to hand the SDK when reading or renaming this session."""
        return self.history_dir or self.cwd

    def work_dir(self) -> str:
        """Folder the session works in: its worktree while it exists, else `cwd`."""
        if self.worktree_path and Path(self.worktree_path).is_dir():
            return self.worktree_path
        return self.cwd
```

Confira se `Path` já é importado em `sessions.py`. É, porque a linha 1109 usa `Path`.

Nas mesmas linhas de `_COLUMNS` e `_INTERNAL_FIELDS`:

```python
_COLUMNS = (
    _INSERT_COLUMNS
    + ", summary, first_prompt, title_custom, rename_pending, file_modified_at, app_modified_at"
    + ", model, effort, permission_mode, finished_at, plan_path, plan_link"
    + ", history_dir, worktree_name, worktree_path, git_branch"
)
_INTERNAL_FIELDS = (
    "title_custom", "rename_pending", "file_modified_at", "app_modified_at",
    "plan_path", "plan_link", "history_dir",
)
```

`backend/vibing/api/sessions.py`, no fim de `SessionOut`:

```python
    # Linked worktree the session works in (None outside worktrees) and the newest
    # branch of its transcript.
    worktree_name: str | None = None
    worktree_path: str | None = None
    git_branch: str | None = None
```

- [x] **Step 4: Rodar tudo e ver passar**

Run: `uv run pytest -q`
Expected: PASS em tudo, incluindo os testes antigos que comparam `SCHEMA_VERSION`.

- [x] **Step 5: Commit**

```bash
git add backend/vibing/db.py backend/vibing/sessions.py backend/vibing/api/sessions.py backend/tests/
git commit -m "[Feat] Guardar worktree, branch e pasta do histórico da sessão"
```

---

### Task 3: Conversa do CLI no meio de um turno conta como "em execução"

**Files:**
- Modify:
  - `backend/vibing/sessions.py`: `display_state` (linha 302) e a chamada em `describe` (linha 398).
  - `frontend/src/sessionState.ts`: `deriveDisplay`.
  - `frontend/src/stores/sessions.ts`: a chamada a `deriveDisplay` em `applyEvent`.
  - `ROADMAP.md`: linha "Conversa do CLI ativa aparece como 'Aguardando você'" em "Pontos em aberto".
- Test:
  - `backend/tests/test_cli_turn.py`, ou o arquivo onde `display_state` já é testado. Procure com `grep -rn "display_state(" backend/tests`.
  - `frontend/src/__tests__/sessionState.spec.ts`, se já existir. Senão, crie.

**Interfaces:**
- Produces:
  - `display_state(state, *, finished, last_activity_at, last_seen_at, now, finished_after, cli_running: bool = False)`.
  - `deriveDisplay(state, finished, current?, cliRunning = false)`.

- [x] **Step 1: Testes que falham**

Backend:

```python
from vibing.sessions import SessionRecord, describe, display_state


def test_cli_mid_turn_shows_as_running():
    kw = dict(finished=False, last_activity_at=100, last_seen_at=100, now=110, finished_after=3600)
    assert display_state("closed", cli_running=True, **kw) == "running"
    assert display_state("closed", **kw) == "waiting"
    # A session finished by the user whose CLI works again is running too.
    assert display_state("closed", cli_running=True, **{**kw, "finished": True}) == "running"


def test_describe_uses_cli_running_for_display_state():
    record = SessionRecord(session_id="s", project_id=1, cwd="/p", title="t", created_at=1, last_activity_at=100)
    out = describe(record, "closed", None, 0, finished_after=3600, now=110, cli_running=True)
    assert out["display_state"] == "running"
    assert out["cli_running"] is True
    idle = describe(record, "idle", None, 0, finished_after=3600, now=110, cli_running=True)
    assert idle["cli_running"] is False
    assert idle["display_state"] == "waiting"
```

Frontend (`frontend/src/__tests__/sessionState.spec.ts`; se o arquivo existir, acrescente o `it`):

```ts
import { describe, expect, it } from 'vitest'
import { deriveDisplay } from '../sessionState'

describe('deriveDisplay', () => {
  it('fechada com o CLI no meio de um turno fica em execução', () => {
    expect(deriveDisplay('closed', false, 'waiting', true).display_state).toBe('running')
    expect(deriveDisplay('closed', false, 'waiting').display_state).toBe('waiting')
    expect(deriveDisplay('idle', false, 'waiting', true).display_state).toBe('waiting')
  })
})
```

- [x] **Step 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_cli_turn.py -q`, depois `pnpm --dir frontend exec vitest run src/__tests__/sessionState.spec.ts`
Expected: FAIL (`unexpected keyword argument 'cli_running'`; `display_state` vale `waiting`).

- [x] **Step 3: Implementar**

Backend, em `display_state`:

```python
def display_state(
    state: SessionState,
    *,
    finished: bool,
    last_activity_at: int,
    last_seen_at: int | None,
    now: float,
    finished_after: float,
    cli_running: bool = False,
) -> DisplayState:
    """State shown to the user: running, waiting for them, or finished.

    `finished_after` is in seconds: a session without activity for longer counts
    as finished. A pending decision always waits for the user. A session without a
    client (`closed`) whose CLI is mid-turn is running.
    """
    if state in ("connecting", "running"):
        return "running"
    if state == "awaiting_decision":
        return "waiting"
    if cli_running and state == "closed":
        return "running"
    if finished or now - last_activity_at > finished_after:
        return "finished"
    return "waiting"
```

Em `describe`, acrescente `cli_running=cli_running,` à chamada de `display_state(...)`.

Frontend, em `sessionState.ts`:

```ts
export function deriveDisplay(
  state: SessionState,
  finished: boolean,
  current?: DisplayState,
  cliRunning = false,
): { display_state: DisplayState; awaiting_decision: boolean } {
  if (state === 'connecting' || state === 'running') return { display_state: 'running', awaiting_decision: false }
  if (state === 'awaiting_decision') return { display_state: 'waiting', awaiting_decision: true }
  // Mirrors the backend: no client in the app, but the CLI is mid-turn.
  if (state === 'closed' && cliRunning) return { display_state: 'running', awaiting_decision: false }
  // A session the backend already shows as finished (marked, or idle for too long) stays so.
  const stays = finished || current === 'finished'
  return { display_state: stays ? 'finished' : 'waiting', awaiting_decision: false }
}
```

Em `stores/sessions.ts`, dentro de `applyEvent`, troque por:

```ts
      Object.assign(session, deriveDisplay(data.state, session.finished, session.display_state, session.cli_running ?? false))
```

No `ROADMAP.md`, troque a situação do ponto em aberto "Conversa do CLI ativa aparece como 'Aguardando você'" por:

```
Decidido em 2026-09-30: `cli_running` passa a contar como "Em execução" no estado exibido, na Inbox, no Dashboard e no menu lateral (marco 10)
```

- [x] **Step 4: Rodar tudo e ver passar**

Run: `uv run pytest -q && pnpm --dir frontend test`
Expected: PASS. Se algum teste antigo esperava `waiting` para uma sessão `closed` com `cli_running=True`, ele descrevia o comportamento que o usuário pediu para mudar. Atualize a expectativa para `running` e cite isso no relatório.

- [x] **Step 5: Commit**

```bash
git add backend/vibing/sessions.py backend/tests/ frontend/src/sessionState.ts frontend/src/stores/sessions.ts frontend/src/__tests__/ ROADMAP.md
git commit -m "[Feat] Mostrar conversa do CLI no meio de um turno como em execução"
```

---

### Task 4: Indexar sessões das worktrees e gravar worktree e branch

**Files:**
- Modify:
  - `backend/vibing/history.py`: `HistoryIndex.__init__` (linha 525), `update_session` (556), `_sync` (594), `_list_project` (619), `_store` (689), `_upsert` (734), mais a nova função `git_worktrees`.
  - `backend/vibing/cliwatch.py`: `_process` (266), `_indexed_session` (389), `_listed_info` (371).
  - `backend/tests/history_fakes.py`: `info()` aceita `git_branch`.
- Test:
  - `backend/tests/test_history.py`
  - `backend/tests/test_cliwatch.py`

**Interfaces:**
- Consumes: `worktree.current_worktree`, `worktree.parse_worktree_list` e `worktree.Worktree` (Tarefa 1). Colunas e campos da Tarefa 2.
- Produces:
  - `async def git_worktrees(repo: Path) -> list[str]` em `history.py`: worktrees ligadas, menos a do próprio repositório. Vazio em qualquer falha.
  - Novos parâmetros opcionais de `HistoryIndex(...)`:
    - `list_worktrees: Callable[[Path], Awaitable[list[str]]] | None`, padrão `git_worktrees`;
    - `session_file: Callable[[str, str], Path | None] | None`, padrão `sdk_session_file`;
    - `detect_worktree: Callable[[Path], tuple[bool, Worktree | None]] | None`, padrão `current_worktree`.
  - `HistoryIndex.update_session(session_id, mtime, info, path: Path | None = None) -> bool`.

- [ ] **Step 1: `history_fakes.info` com branch**

Em `backend/tests/history_fakes.py`, acrescente o parâmetro `git_branch: str | None = None` a `info()` e repasse com `git_branch=git_branch` ao `SDKSessionInfo(...)`.

- [ ] **Step 2: Testes que falham**

Em `backend/tests/test_history.py`, siga o padrão dos testes que já criam um `HistoryIndex` com `FakeHistory` e um projeto no banco. Use os helpers do arquivo para criar o banco e inserir o projeto: veja `test_sessions_of_subrepositories_keep_their_cwd` e o fixture `env`. Os nomes abaixo (`make_index`, `add_project`, `rows`) são os que você vai criar ou reaproveitar no topo do bloco novo.

```python
from vibing.worktree import Worktree


def _worktrees(mapping: dict[str, list[str]]):
    async def list_worktrees(repo: Path) -> list[str]:
        return list(mapping.get(str(repo), []))
    return list_worktrees


def make_index(db_path, fake, *, worktrees=None, detected=None, files=None):
    """HistoryIndex with fake listing, worktree listing, file lookup and detection."""
    detected = detected or {}
    return history.HistoryIndex(
        db_path, fake.list_sessions,
        folder_signature=lambda d: None,
        list_worktrees=_worktrees(worktrees or {}),
        session_file=lambda sid, directory: Path(f"/fake/{sid}.jsonl"),
        detect_worktree=lambda path: detected.get(path.stem, (False, None)),
        file_exists=lambda sid, d: True,
    )


async def test_sessions_in_worktree_folders_are_indexed_under_the_project(tmp_path: Path):
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    outside = tmp_path / "proj-wt"  # worktree outside the project folder
    inside = project / ".claude" / "worktrees" / "a"
    db_path = new_db(tmp_path)  # helper existente do arquivo, ou crie com db.init_db
    pid = add_project(db_path, project)
    fake = FakeHistory()
    fake.add(str(inside), info("s-in", str(project), git_branch="worktree-a"))
    fake.add(str(outside), info("s-out", str(outside)))
    idx = make_index(db_path, fake, worktrees={str(project): [str(inside), str(outside)]})
    await idx.sync_all()
    got = rows(db_path)  # {session_id: row}
    assert got["s-in"]["project_id"] == pid
    assert got["s-in"]["history_dir"] == str(inside)
    assert got["s-in"]["git_branch"] == "worktree-a"
    # cwd outside every project: owned by the project whose repo listed the worktree.
    assert got["s-out"]["project_id"] == pid
    assert got["s-out"]["history_dir"] is None  # its cwd is the listed folder


async def test_worktree_listing_failure_keeps_the_project_complete(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    db_path = new_db(tmp_path)
    add_project(db_path, project)
    fake = FakeHistory()
    fake.add(str(project), info("s1", str(project)))

    async def boom(repo: Path) -> list[str]:
        raise RuntimeError("git quebrou")

    idx = make_index(db_path, fake)
    idx._list_worktrees = boom  # simulates an unexpected failure
    await idx.sync_all()
    assert "s1" in rows(db_path)


async def test_worktree_detection_is_written_and_kept_when_folder_is_gone(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    db_path = new_db(tmp_path)
    add_project(db_path, project)
    fake = FakeHistory()
    fake.add(str(project), info("s1", str(project), modified_ms=1_000_000_000_000))
    detected = {"s1": (True, Worktree(name="a", path="/wt/a"))}
    idx = make_index(db_path, fake, detected=detected)
    await idx.sync_all()
    assert (rows(db_path)["s1"]["worktree_name"], rows(db_path)["s1"]["worktree_path"]) == ("a", "/wt/a")
    # File changed, folder gone: not decided, the previous value stays.
    fake.by_directory[str(project)] = [info("s1", str(project), modified_ms=1_000_000_100_000)]
    detected["s1"] = (False, None)
    await idx.sync_all()
    assert rows(db_path)["s1"]["worktree_name"] == "a"
    # Back in the main checkout: cleared.
    fake.by_directory[str(project)] = [info("s1", str(project), modified_ms=1_000_000_200_000)]
    detected["s1"] = (True, None)
    await idx.sync_all()
    assert rows(db_path)["s1"]["worktree_name"] is None


async def test_session_moved_to_worktree_keeps_row_and_gains_history_dir(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    wt = project / ".claude" / "worktrees" / "m"
    db_path = new_db(tmp_path)
    pid = add_project(db_path, project)
    fake = FakeHistory()
    fake.add(str(project), info("s1", str(project)))
    worktrees: dict[str, list[str]] = {}
    idx = make_index(db_path, fake, worktrees=worktrees)
    await idx.sync_all()
    assert rows(db_path)["s1"]["history_dir"] is None
    # The CLI moved the transcript into the worktree's history folder.
    fake.by_directory[str(project)] = []
    fake.add(str(wt), info("s1", str(project), modified_ms=1_000_000_100_000))
    worktrees[str(project)] = [str(wt)]
    await idx.sync_all()
    got = rows(db_path)
    assert list(got) == ["s1"]
    assert got["s1"]["project_id"] == pid
    assert got["s1"]["history_dir"] == str(wt)


async def test_git_worktrees_uses_run_git_and_drops_own_folder(tmp_path: Path, monkeypatch):
    calls = []

    async def fake_run_git(repo, *args, **kw):
        calls.append((repo, args))
        return 0, f"worktree {tmp_path}\nHEAD a\n\nworktree /x/y\nHEAD b\n", ""

    monkeypatch.setattr("vibing.gitinfo.run_git", fake_run_git)
    assert await history.git_worktrees(tmp_path) == ["/x/y"]
    assert calls == [(tmp_path, ("worktree", "list", "--porcelain"))]


async def test_git_worktrees_empty_on_git_error(tmp_path: Path, monkeypatch):
    from vibing import gitinfo

    async def failing(repo, *args, **kw):
        raise gitinfo.GitError("sem git")

    monkeypatch.setattr("vibing.gitinfo.run_git", failing)
    assert await history.git_worktrees(tmp_path) == []
```

Se o arquivo ainda não tiver `new_db`, `add_project` e `rows`, crie-os no topo do bloco novo. `rows` devolve `{row["session_id"]: dict(row)}` de `SELECT * FROM sessions`, e `add_project` insere em `projects` e devolve o id. Reaproveite o que o fixture `env` já faz.

Em `backend/tests/test_cliwatch.py`, siga o padrão dos testes que já rodam `_process` com um arquivo `.jsonl` real sob `root/<pasta>/<sid>.jsonl`:

```python
async def test_update_session_receives_the_transcript_path(...):
    """_process calls history.update_session(sid, mtime, info, path) with the file it saw."""
    # Arrange like the existing test for a known session. Replace
    # history.update_session with a spy that records its arguments.
    # Assert that the 4th argument is the Path of the .jsonl.


async def test_transcript_in_another_history_folder_triggers_project_sync(...):
    """Known session with cwd=/p (folder '-p') whose file appears in '-p--claude-worktrees-x':
    _process calls history.sync_project(project_id) once, and not again on the next
    pass of the same folder."""
```

Escreva os dois com o fixture e os helpers que o arquivo já usa. Os comentários acima dizem o que arrumar e o que conferir.

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_history.py backend/tests/test_cliwatch.py -q`
Expected: FAIL (`HistoryIndex` não aceita `list_worktrees`, falta `git_worktrees`, `update_session` não recebe `path`).

- [ ] **Step 4: Implementar em `history.py`**

Imports no topo:

```python
from collections.abc import Awaitable, Callable
from vibing.worktree import Worktree, current_worktree, parse_worktree_list
```

Nova função, perto de `sdk_list_sessions`:

```python
async def git_worktrees(repo: Path) -> list[str]:
    """Linked worktrees of `repo`, its own folder left out. Empty on any git failure."""
    from vibing import gitinfo  # gitinfo imports this module

    try:
        code, out, _ = await gitinfo.run_git(repo, "worktree", "list", "--porcelain")
    except gitinfo.GitError:
        logger.warning("Não foi possível listar as worktrees de %s", repo)
        return []
    if code != 0:
        return []
    own = os.path.realpath(repo)
    return [path for path in parse_worktree_list(out) if os.path.realpath(path) != own]
```

Atualize o comentário de `sdk_list_sessions` para: `# Worktrees are listed by the index itself (through run_git), folder by folder.`

Em `__init__`, depois de `folder_signature`:

```python
        list_worktrees: Callable[[Path], Awaitable[list[str]]] | None = None,
        session_file: Callable[[str, str], Path | None] | None = None,
        detect_worktree: Callable[[Path], tuple[bool, Worktree | None]] | None = None,
```

E no corpo:

```python
        self._list_worktrees = list_worktrees or git_worktrees
        self._session_file = session_file or sdk_session_file
        self._detect_worktree = detect_worktree or current_worktree
        # session id -> (last_modified seen, detection result): a file read once per change.
        self._worktree_cache: dict[str, tuple[Any, tuple[bool, Worktree | None]]] = {}
```

`_list_project` passa a devolver trios `(info, directory, fallback)`. `fallback` é `True` para sessões vindas de uma worktree:

```python
    async def _list_project(self, path: str) -> tuple[list[tuple[Any, str, bool]], bool]:
        """Sessions listed for the project and whether every listing succeeded.

        The third item is True for sessions found in a worktree's history folder:
        when their cwd is outside every project, they belong to this one.
        """
        folder = Path(path)
        if not folder.is_dir():
            return [], False
        try:
            repos, ok = await asyncio.to_thread(scan_repositories, folder)
        except Exception:
            logger.exception("Falha ao procurar repositórios em %s", path)
            repos, ok = [], False
        directories = [str(folder), *(str(repo) for repo in repos)]
        worktrees: list[str] = []
        for directory in directories:
            try:
                found = await self._list_worktrees(Path(directory))
            except Exception:
                logger.exception("Falha ao listar as worktrees de %s", directory)
                continue  # without worktrees; the project stays complete
            worktrees.extend(w for w in found if w not in directories and w not in worktrees)
        result: list[tuple[Any, str, bool]] = []
        for directory, from_worktree in [
            *((d, False) for d in directories), *((w, True) for w in worktrees)
        ]:
            try:
                infos = await asyncio.to_thread(self._list_cached, directory)
            except Exception:
                logger.exception("Falha ao listar o histórico de %s", directory)
                if not from_worktree:
                    ok = False
                continue
            result.extend((info, directory, from_worktree) for info in infos)
        return result, ok
```

Em `_sync`:

```python
            listed: dict[str, tuple[Any, str, int | None]] = {}  # id -> (info, directory, fallback project)
            complete: set[int] = set()
            for project_id, path in targets:
                entries, ok = await self._list_project(path)
                if ok:
                    complete.add(project_id)
                for info, directory, from_worktree in entries:
                    listed.setdefault(
                        info.session_id, (info, directory, project_id if from_worktree else None)
                    )
            candidates = self._missing_candidates(listed, complete)
            gone = await asyncio.to_thread(self._confirm_gone, candidates) if candidates else []
            worktrees = await asyncio.to_thread(self._worktree_details, listed)
            changed, projects_changed = self._store(listed, gone, worktrees)
```

Troque as anotações de tipo de `_missing_candidates` para o novo formato de `listed`. O corpo não muda.

Novo método:

```python
    def _worktree_details(
        self, listed: dict[str, tuple[Any, str, int | None]]
    ) -> dict[str, tuple[bool, Worktree | None]]:
        """Worktree of each listed session, reading a file only when it changed. Runs in a thread."""
        out: dict[str, tuple[bool, Worktree | None]] = {}
        for session_id, (info, directory, _) in listed.items():
            cached = self._worktree_cache.get(session_id)
            if cached is not None and cached[0] == info.last_modified:
                out[session_id] = cached[1]
                continue
            try:
                path = self._session_file(session_id, directory)
                result = self._detect_worktree(path) if path is not None else (False, None)
            except Exception:
                logger.exception("Falha ao ler a worktree da sessão %s", session_id)
                result = (False, None)
            self._worktree_cache[session_id] = (info.last_modified, result)
            out[session_id] = result
        return out
```

`_confirm_gone` passa a usar a pasta do histórico. Em `_missing_candidates`, selecione `COALESCE(history_dir, cwd) AS cwd` no lugar de `cwd`:

```python
            rows = conn.execute(
                "SELECT session_id, project_id, COALESCE(history_dir, cwd) AS cwd FROM sessions"
                " WHERE file_modified_at IS NOT NULL"
            ).fetchall()
```

Em `_store`:

```python
    def _store(
        self,
        listed: dict[str, tuple[Any, str, int | None]],
        gone: list[tuple[str, int]],
        worktrees: dict[str, tuple[bool, Worktree | None]] | None = None,
    ) -> tuple[set[str], set[int]]:
        ...
            current = {project_id for project_id, _ in projects}
            for session_id, (info, directory, fallback) in listed.items():
                cwd = info.cwd or directory
                # The session's own cwd decides; a worktree outside every project
                # belongs to the project whose repository listed it.
                project_id = owner_project(cwd, projects)
                if project_id is None and fallback in current:
                    project_id = fallback
                if project_id is None:
                    continue
                history_dir = directory if directory != cwd else None
                worktree = (worktrees or {}).get(session_id, (False, None))
                previous = self._upsert(conn, info, project_id, cwd, history_dir, worktree)
                ...
```

Mova `current = {...}` para antes do laço de `listed` (hoje fica depois) e mantenha o uso no laço de `gone`.

`_upsert` ganha dois parâmetros e as colunas novas:

```python
    @staticmethod
    def _upsert(
        conn: sqlite3.Connection,
        info: Any,
        project_id: int,
        cwd: str,
        history_dir: str | None = None,
        worktree: tuple[bool, Worktree | None] = (False, None),
    ) -> bool | int | None:
        """False when nothing changed; otherwise the previous project id (None if new)."""
        modified = _seconds(info.last_modified) or int(time.time())
        created = _seconds(info.created_at) or modified
        summary = truncate_text(info.summary)
        first_prompt = truncate_text(info.first_prompt)
        title = session_title(info)
        branch = getattr(info, "git_branch", None)
        decided, found = worktree
        row = conn.execute(
            "SELECT project_id, title, title_custom, summary, first_prompt, last_activity_at,"
            " file_modified_at, history_dir, git_branch, worktree_name, worktree_path"
            " FROM sessions WHERE session_id = ?",
            (info.session_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at, last_seen_at, finished, summary, first_prompt,"
                " file_modified_at, history_dir, git_branch, worktree_name, worktree_path)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (info.session_id, project_id, cwd, title, created, modified, modified,
                 summary, first_prompt, modified, history_dir, branch,
                 found.name if found else None, found.path if found else None),
            )
            return None
        changes: dict[str, Any] = {
            "project_id": project_id,
            "summary": summary,
            "first_prompt": first_prompt,
            "file_modified_at": modified,
            "last_activity_at": max(row["last_activity_at"], modified),
            "history_dir": history_dir,
        }
        if branch:
            changes["git_branch"] = branch
        if decided:
            changes["worktree_name"] = found.name if found else None
            changes["worktree_path"] = found.path if found else None
        # (keep the title block as it is)
```

Em `update_session`:

```python
    def update_session(
        self, session_id: str, mtime: int, info: Any | None, path: Path | None = None
    ) -> bool:
        """Refresh one indexed session from its file's mtime and, when given, its
        listing entry (title, summary) and its file (current worktree). Blocking:
        run it in a thread. True if the row changed."""
        worktree = self._detect_worktree(path) if path is not None else (False, None)
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            row = conn.execute(
                "SELECT project_id, cwd, history_dir, last_activity_at, file_modified_at,"
                " worktree_name, worktree_path FROM sessions WHERE session_id = ?", (session_id,),
            ).fetchone()
            if row is None:
                return False
            if info is not None:
                info = replace(info, last_modified=mtime * 1000)
                return self._upsert(
                    conn, info, row["project_id"], row["cwd"], row["history_dir"], worktree
                ) is not False
            changed = False
            decided, found = worktree
            if decided:
                name, wpath = (found.name, found.path) if found else (None, None)
                if (row["worktree_name"], row["worktree_path"]) != (name, wpath):
                    conn.execute(
                        "UPDATE sessions SET worktree_name = ?, worktree_path = ? WHERE session_id = ?",
                        (name, wpath, session_id),
                    )
                    changed = True
            if row["file_modified_at"] == mtime and row["last_activity_at"] >= mtime:
                return changed
            conn.execute(
                "UPDATE sessions SET file_modified_at = ?,"
                " last_activity_at = MAX(last_activity_at, ?) WHERE session_id = ?",
                (mtime, mtime, session_id),
            )
            return True
```

- [ ] **Step 5: Implementar em `cliwatch.py`**

`_indexed_session` devolve também a pasta do histórico:

```python
    def _indexed_session(self, session_id: str) -> tuple[int, str, str] | None:
        """(project id, cwd, directory whose history holds the file)."""
        with closing(db.connect(self._history.db_path)) as conn:
            row = conn.execute(
                "SELECT project_id, cwd, COALESCE(history_dir, cwd) AS hdir FROM sessions"
                " WHERE session_id = ?", (session_id,),
            ).fetchone()
        return None if row is None else (row["project_id"], row["cwd"], row["hdir"])
```

Em `_process`:

```python
        project_id, cwd, history_dir = known
        ...
        info = await self._listed_info(session_id, history_dir)
        ...
        await asyncio.to_thread(
            self._history.update_session, session_id, int(mtime), info, path
        )
        # The CLI moved the transcript (a session that entered a worktree): the project
        # sync lists the worktree folders and records where the file lives now.
        if burst.folder != history_folder_name(history_dir):
            key = (session_id, burst.folder)
            if key not in self._moved_synced:
                self._moved_synced.add(key)
                await self._history.sync_project(project_id)
```

No `__init__` do `CliWatcher`: `self._moved_synced: set[tuple[str, str]] = set()`. Confira que `history_folder_name` é a função já usada em `_projects_for_folder`. Ela está importada no arquivo.

- [ ] **Step 6: Rodar tudo e ver passar**

Run: `uv run pytest -q`
Expected: PASS em tudo. Testes antigos que chamavam `_store(listed, gone)` com pares precisam passar trios `(info, directory, None)`. Ajuste-os e cite no relatório.

- [ ] **Step 7: Commit**

```bash
git add backend/vibing/history.py backend/vibing/cliwatch.py backend/tests/
git commit -m "[Feat] Indexar sessões de worktrees com pasta, worktree e branch"
```

---

### Task 5: Ler o histórico pela pasta certa e retomar na worktree

**Files:**
- Modify:
  - `backend/vibing/sessions.py`, linhas 863, 949, 959, 966, 980, 1109–1110, 1244, 1257, 2194, 2277 e 2530.
  - `backend/vibing/activity.py`, linhas 64–86.
  - `backend/vibing/api/git.py`, linha 152.
- Test:
  - `backend/tests/test_sessions.py`, ou o arquivo que testa `ActiveSession` com o cliente falso (procure `AgentOptions` em `backend/tests`).
  - `backend/tests/test_activity.py`

**Interfaces:**
- Consumes: `SessionRecord.history_directory` e `SessionRecord.work_dir()` (Tarefa 2).

- [ ] **Step 1: Testes que falham**

Nos testes de sessão que usam o cliente falso e os fakes de histórico:

```python
async def test_sdk_reads_use_history_dir(...):
    """Session row with history_dir='/h' and cwd=<project>: opening it calls the fake
    get_session_messages / read_transcript with directory '/h', and a rename calls
    rename_session(..., '/h')."""


async def test_client_starts_in_existing_worktree(tmp_path, ...):
    """Row with worktree_path=<existing folder>: sending a message creates the client
    with AgentOptions.cwd == Path(worktree_path). With a folder that no longer
    exists, cwd == Path(record.cwd)."""
```

Siga o fixture que já cria o `SessionManager` com `agent_factory` falso e registra as `AgentOptions` recebidas. Insira a linha com `history_dir` ou `worktree_path` direto no banco antes de abrir.

Em `test_activity.py`:

```python
def test_activity_finds_file_through_history_dir(...):
    """Row with history_dir='/h': the session_file finder is called with ('s', '/h')."""
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest backend/tests/test_sessions.py backend/tests/test_activity.py -q`
Expected: FAIL (os fakes recebem `cwd`, não `/h`).

- [ ] **Step 3: Implementar**

Em `sessions.py`:
- Nas leituras e na renomeação (linhas 863, 949, 959, 966, 980, 1257, 2194, 2277 e 2530), troque `self.record.cwd`, `session.record.cwd` ou `record.cwd` passados como `directory` ao SDK pela forma `.history_directory` do mesmo registro. Exemplo da linha 959:

```python
            await asyncio.to_thread(
                self._get_session_messages, self.session_id, self.record.history_directory
            )
```

- Nas linhas 1109–1110 (checagem da pasta antes de conectar):

```python
            work_dir = self.record.work_dir()
            if not Path(work_dir).is_dir():
                raise AgentError(f"A pasta do projeto não existe mais: {work_dir}")
```

- Na linha 1244, em `_new_client`: `cwd=Path(self.record.work_dir()),`
- A linha 2088 (INSERT de sessão nova) não muda.

Em `activity.py`, em `read`:

```python
            rows = conn.execute(
                "SELECT session_id, project_id, COALESCE(history_dir, cwd) AS cwd FROM sessions"
                " WHERE last_activity_at >= ?",
                (int(since),),
            ).fetchall()
```

Em `api/git.py`, na linha 152: `files = _edited_files(items, Path(session.record.work_dir()))`

- [ ] **Step 4: Rodar tudo e ver passar**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/vibing/sessions.py backend/vibing/activity.py backend/vibing/api/git.py backend/tests/
git commit -m "[Feat] Ler histórico pela pasta certa e retomar sessão na worktree"
```

---

### Task 6: Worktree no cabeçalho, no Detalhes e na linha da lista

**Files:**
- Create:
  - `frontend/src/worktree.ts`
  - `frontend/src/components/git/WorktreeLabel.vue`
- Modify:
  - `frontend/src/types/api.ts` (`Session`)
  - `frontend/src/components/conversation/ConversationHeader.vue` (linhas 185–190)
  - `frontend/src/components/details/DetailsPanel.vue` (linhas 132–136)
  - `frontend/src/components/conversation/ConversationRow.vue` (linhas 78–80)
- Test:
  - `frontend/src/__tests__/worktree.spec.ts`
  - `frontend/src/components/conversation/__tests__/ConversationHeader.spec.ts` (existente)
  - `frontend/src/components/details/__tests__/DetailsPanel.spec.ts`
  - `frontend/src/components/conversation/__tests__/ConversationRow.spec.ts` (existente; procure o arquivo que testa `row-branch`)

**Interfaces:**
- Produces:
  - `worktreeLabel(s: Pick<Session, 'worktree_name' | 'git_branch'>): string | null`
  - Componente `WorktreeLabel` com props `{ text: string; muted?: boolean }`.
  - `Session.worktree_name?`, `.worktree_path?` e `.git_branch?`, do tipo `string | null`.

- [ ] **Step 1: Testes que falham**

`frontend/src/__tests__/worktree.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { worktreeLabel } from '../worktree'

describe('worktreeLabel', () => {
  it('nome e branch, só nome, ou nada', () => {
    expect(worktreeLabel({ worktree_name: 'a', git_branch: 'feat/x' })).toBe('worktree a · feat/x')
    expect(worktreeLabel({ worktree_name: 'a', git_branch: null })).toBe('worktree a')
    expect(worktreeLabel({ worktree_name: null, git_branch: 'main' })).toBeNull()
    expect(worktreeLabel({})).toBeNull()
  })
})
```

Nos specs existentes, com `makeSession({ worktree_name: 'melhorias', worktree_path: '/p/.claude/worktrees/melhorias', git_branch: 'worktree-melhorias' })` e o mesmo setup de cada arquivo:

```ts
it('mostra a worktree no lugar do branch do projeto', async () => {
  // ConversationHeader.spec.ts
  const header = w.find('[data-test="header-worktree"]')
  expect(header.text()).toBe('worktree melhorias · worktree-melhorias')
  expect(w.text()).not.toContain('main') // the project's repo branch is not shown
})

it('Detalhes mostra a linha Worktree com o caminho na dica e o branch da sessão', async () => {
  // DetailsPanel.spec.ts
  const prop = w.find('[data-test="prop-worktree"]')
  expect(prop.text()).toContain('melhorias')
  expect(prop.find('[title]').attributes('title')).toBe('/p/.claude/worktrees/melhorias')
  expect(w.find('[data-test="prop-branch"]').text()).toContain('worktree-melhorias')
})

it('linha da lista mostra a worktree no lugar do branch', async () => {
  // ConversationRow spec
  expect(w.find('[data-test="row-branch"]').text()).toContain('worktree melhorias · worktree-melhorias')
})

it('sem worktree, nada muda', async () => {
  expect(w.find('[data-test="header-worktree"]').exists()).toBe(false)
  expect(w.find('[data-test="prop-worktree"]').exists()).toBe(false)
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/__tests__/worktree.spec.ts src/components/conversation src/components/details`
Expected: FAIL

- [ ] **Step 3: Implementar**

`frontend/src/types/api.ts`, no fim de `Session`:

```ts
  /** Linked git worktree the session works in; null outside worktrees. */
  worktree_name?: string | null
  worktree_path?: string | null
  /** Newest git branch recorded in the session's transcript. */
  git_branch?: string | null
```

`frontend/src/worktree.ts`:

```ts
import type { Session } from './types/api'

/** "worktree <name> · <branch>", "worktree <name>" without a branch, or null outside worktrees. */
export function worktreeLabel(s: Pick<Session, 'worktree_name' | 'git_branch'>): string | null {
  if (!s.worktree_name) return null
  return s.git_branch ? `worktree ${s.worktree_name} · ${s.git_branch}` : `worktree ${s.worktree_name}`
}
```

`frontend/src/components/git/WorktreeLabel.vue`:

```vue
<script setup lang="ts">
defineProps<{ text: string; muted?: boolean }>()
</script>

<template>
  <span class="inline-flex min-w-0 items-center gap-1.5 font-mono text-xs" :class="muted ? 'text-fg-muted' : 'text-fg'">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-fg-muted" aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><path d="M6.5 10v4a3 3 0 0 0 3 3H14" />
    </svg>
    <span class="truncate">{{ text }}</span>
  </span>
</template>
```

`ConversationHeader.vue`: importe `WorktreeLabel` e `worktreeLabel`, e acrescente `const worktree = computed(() => (listed.value ? worktreeLabel(listed.value) : null))`. Na faixa de chips:

```vue
      <span v-if="worktree" data-test="header-worktree" class="flex items-center rounded-full border border-line-strong bg-card px-2.5 py-[3px]" :title="listed?.worktree_path ?? undefined">
        <WorktreeLabel :text="worktree" />
      </span>
      <template v-else>
        <span v-for="repo in repos" :key="repo.path" class="flex items-center rounded-full border border-line-strong bg-card px-2.5 py-[3px]">
          <BranchLabel :text="repoLabel(repo)" :muted="!!repo.error" />
        </span>
      </template>
```

`DetailsPanel.vue`: importe `WorktreeLabel` e troque o bloco Branch por:

```vue
            <dt class="text-fg-muted">Branch</dt>
            <dd data-test="prop-branch" class="m-0 flex min-w-0 flex-col gap-1">
              <template v-if="session?.worktree_name">
                <BranchLabel v-if="session.git_branch" :text="session.git_branch" />
                <span v-else class="text-fg-muted">desconhecido</span>
              </template>
              <template v-else>
                <BranchLabel v-for="repo in repos" :key="repo.path" :text="repoLabel(repo)" :muted="!!repo.error" />
                <span v-if="repos.length === 0" class="text-fg-muted">sem repositório git</span>
              </template>
            </dd>
            <template v-if="session?.worktree_name">
              <dt class="text-fg-muted">Worktree</dt>
              <dd data-test="prop-worktree" class="m-0 min-w-0">
                <span :title="session.worktree_path ?? undefined"><WorktreeLabel :text="session.worktree_name" /></span>
              </dd>
            </template>
```

`ConversationRow.vue`: importe os dois e acrescente `const worktree = computed(() => worktreeLabel(props.session))`:

```vue
    <span data-test="row-branch" class="hidden w-40 shrink-0 lg:flex">
      <WorktreeLabel v-if="worktree" :text="worktree" muted />
      <BranchLabel v-else-if="repo" :text="repoLabel(repo)" muted />
    </span>
```

- [ ] **Step 4: Rodar tudo e ver passar**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: PASS, e o build sem erros de tipo.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "[UI] Mostrar worktree e branch da sessão no cabeçalho, Detalhes e lista"
```

---

### Task 7: Renomear só pelo clique no título

**Files:**
- Modify: `frontend/src/components/conversation/ConversationHeader.vue` (linha 177)
- Test: `frontend/src/components/conversation/__tests__/ConversationHeader.spec.ts`

- [ ] **Step 1: Teste que falha**

Troque o teste que clica em `menu-rename`, se houver, por:

```ts
it('o menu ⋯ não tem Renomear; clicar no título abre a edição', async () => {
  await w.find('[data-test="header-menu"]').trigger('click')
  expect(w.find('[data-test="menu-rename"]').exists()).toBe(false)
  expect(w.findAll('[role="menuitem"]').map((b) => b.text())).toEqual(['Abrir projeto no editor', 'Copiar ID da sessão'])
  await w.find('[data-test="conversation-title"]').trigger('click')
  expect(w.find('[data-test="title-input"]').exists()).toBe(true)
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/conversation/__tests__/ConversationHeader.spec.ts`
Expected: FAIL (`menu-rename` existe)

- [ ] **Step 3: Implementar**

Apague a linha do botão `data-test="menu-rename"`. Se `startRename` fechava o menu (`menuOpen.value = false`), mantenha: não faz mal.

- [ ] **Step 4: Rodar tudo e ver passar**

Run: `pnpm --dir frontend test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/conversation/
git commit -m "[UI] Remover Renomear do menu e manter o clique no título"
```

---

### Task 8: Largura ajustável do painel Detalhes

**Files:**
- Create:
  - `frontend/src/detailsWidthPref.ts`
  - `frontend/src/__tests__/detailsWidthPref.spec.ts`
- Modify: `frontend/src/components/details/DetailsPanel.vue`
- Test: `frontend/src/components/details/__tests__/DetailsResize.spec.ts` (novo)

**Interfaces:**
- Produces:
  - `DETAILS_DEFAULT_WIDTH = 360`, `DETAILS_MIN_WIDTH = 300` e `DETAILS_KEY_STEP = 16`.
  - `detailsMaxWidth(viewport: number): number`
  - `clampDetailsWidth(width: number, viewport: number): number`
  - `readDetailsWidth(): number`
  - `writeDetailsWidth(width: number): void`

- [ ] **Step 1: Testes que falham**

`frontend/src/__tests__/detailsWidthPref.spec.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { clampDetailsWidth, detailsMaxWidth, readDetailsWidth, writeDetailsWidth } from '../detailsWidthPref'

beforeEach(() => localStorage.clear())

describe('largura do Detalhes', () => {
  it('padrão 360 e valor salvo', () => {
    expect(readDetailsWidth()).toBe(360)
    writeDetailsWidth(512)
    expect(readDetailsWidth()).toBe(512)
  })
  it('valor inválido volta ao padrão', () => {
    localStorage.setItem('vibing:details-width', 'abc')
    expect(readDetailsWidth()).toBe(360)
  })
  it('máximo é o menor entre 70% e janela menos 400', () => {
    expect(detailsMaxWidth(2000)).toBe(1400)
    expect(detailsMaxWidth(1200)).toBe(800)
    expect(detailsMaxWidth(600)).toBe(300) // never below the minimum
  })
  it('ajusta aos limites', () => {
    expect(clampDetailsWidth(100, 2000)).toBe(300)
    expect(clampDetailsWidth(5000, 1200)).toBe(800)
    expect(clampDetailsWidth(420.6, 2000)).toBe(421)
  })
})
```

`frontend/src/components/details/__tests__/DetailsResize.spec.ts` usa o mesmo setup de `DetailsPanel.spec.ts` (Pinia, `routeFetch` para `/api/sessions/s1/changes`, sessão no store). Copie a função de montagem de lá. Defina `window.innerWidth = 1600` com `Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true })`.

```ts
function width(w: VueWrapper) {
  return (w.find('[data-test="details-panel"]').element as HTMLElement).style.width
}

it('começa com a largura salva', async () => {
  localStorage.setItem('vibing:details-width', '480')
  const w = await mountPanel()
  expect(width(w)).toBe('480px')
})

it('arrastar a alça para a esquerda alarga e grava ao soltar', async () => {
  const w = await mountPanel()
  const handle = w.find('[data-test="details-resize"]')
  await handle.trigger('pointerdown', { clientX: 1000, pointerId: 1 })
  await handle.trigger('pointermove', { clientX: 900, pointerId: 1 })
  expect(width(w)).toBe('460px')
  expect(localStorage.getItem('vibing:details-width')).toBeNull()
  await handle.trigger('pointerup', { clientX: 900, pointerId: 1 })
  expect(localStorage.getItem('vibing:details-width')).toBe('460')
})

it('teclado: seta esquerda alarga, direita estreita, e respeita o mínimo', async () => {
  const w = await mountPanel()
  const handle = w.find('[data-test="details-resize"]')
  await handle.trigger('keydown', { key: 'ArrowLeft' })
  expect(width(w)).toBe('376px')
  for (let i = 0; i < 10; i++) await handle.trigger('keydown', { key: 'ArrowRight' })
  expect(width(w)).toBe('300px')
  expect(handle.attributes('aria-valuenow')).toBe('300')
  expect(localStorage.getItem('vibing:details-width')).toBe('300')
})

it('duplo clique volta ao padrão', async () => {
  localStorage.setItem('vibing:details-width', '600')
  const w = await mountPanel()
  await w.find('[data-test="details-resize"]').trigger('dblclick')
  expect(width(w)).toBe('360px')
  expect(localStorage.getItem('vibing:details-width')).toBe('360')
})

it('ajusta largura salva acima do máximo', async () => {
  localStorage.setItem('vibing:details-width', '3000')
  const w = await mountPanel()
  expect(width(w)).toBe('1120px') // min(0.7 × 1600, 1600 − 400)
})

it('a alça tem papel de separador acessível', async () => {
  const w = await mountPanel()
  const handle = w.find('[data-test="details-resize"]')
  expect(handle.attributes('role')).toBe('separator')
  expect(handle.attributes('aria-orientation')).toBe('vertical')
  expect(handle.attributes('tabindex')).toBe('0')
  expect(handle.attributes('aria-label')).toBe('Redimensionar detalhes')
})
```

Se `trigger('pointerdown', ...)` não repassar `clientX` no jsdom, use `handle.element.dispatchEvent(new MouseEvent('pointerdown', { clientX: 1000, bubbles: true }))`, seguido de `await nextTick()`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/__tests__/detailsWidthPref.spec.ts src/components/details`
Expected: FAIL

- [ ] **Step 3: Implementar `detailsWidthPref.ts`**

```ts
const KEY = 'vibing:details-width'
export const DETAILS_DEFAULT_WIDTH = 360
export const DETAILS_MIN_WIDTH = 300
export const DETAILS_KEY_STEP = 16

/** Widest the panel may be: 70% of the window, leaving at least 400px for the conversation. */
export function detailsMaxWidth(viewport: number): number {
  return Math.max(DETAILS_MIN_WIDTH, Math.min(Math.floor(viewport * 0.7), viewport - 400))
}

export function clampDetailsWidth(width: number, viewport: number): number {
  return Math.round(Math.min(Math.max(width, DETAILS_MIN_WIDTH), detailsMaxWidth(viewport)))
}

/** Width chosen by the user (default 360). Limits are applied where it is shown. */
export function readDetailsWidth(): number {
  try {
    const value = Number.parseInt(localStorage.getItem(KEY) ?? '', 10)
    return Number.isFinite(value) && value > 0 ? value : DETAILS_DEFAULT_WIDTH
  } catch {
    return DETAILS_DEFAULT_WIDTH
  }
}

export function writeDetailsWidth(width: number): void {
  try {
    localStorage.setItem(KEY, String(Math.round(width)))
  } catch {
    // Without storage the width lasts only for this page.
  }
}
```

- [ ] **Step 4: Implementar a alça em `DetailsPanel.vue`**

No script:

```ts
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  DETAILS_DEFAULT_WIDTH, DETAILS_KEY_STEP, DETAILS_MIN_WIDTH,
  clampDetailsWidth, detailsMaxWidth, readDetailsWidth, writeDetailsWidth,
} from '../../detailsWidthPref'

const viewport = ref(window.innerWidth)
const onWindowResize = () => { viewport.value = window.innerWidth }
onMounted(() => window.addEventListener('resize', onWindowResize))
onBeforeUnmount(() => window.removeEventListener('resize', onWindowResize))

const width = ref(readDetailsWidth())
const applied = computed(() => clampDetailsWidth(width.value, viewport.value))
const maxWidth = computed(() => detailsMaxWidth(viewport.value))

// The handle sits on the left edge: moving the pointer left makes the panel wider.
let drag: { startX: number; startWidth: number } | null = null
function startDrag(event: PointerEvent) {
  event.preventDefault()
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  drag = { startX: event.clientX, startWidth: applied.value }
}
function moveDrag(event: PointerEvent) {
  if (!drag) return
  width.value = clampDetailsWidth(drag.startWidth + (drag.startX - event.clientX), viewport.value)
}
function endDrag() {
  if (!drag) return
  drag = null
  writeDetailsWidth(applied.value)
}
function onResizeKey(event: KeyboardEvent) {
  const delta = event.key === 'ArrowLeft' ? DETAILS_KEY_STEP : event.key === 'ArrowRight' ? -DETAILS_KEY_STEP : 0
  if (!delta) return
  event.preventDefault()
  width.value = clampDetailsWidth(applied.value + delta, viewport.value)
  writeDetailsWidth(width.value)
}
function resetWidth() {
  width.value = DETAILS_DEFAULT_WIDTH
  writeDetailsWidth(width.value)
}
```

No template, troque a abertura do `<aside>` e ponha a alça como primeiro filho:

```vue
  <aside
    data-test="details-panel"
    :data-wide="String(wide)"
    aria-label="Detalhes da conversa"
    class="relative flex h-full shrink-0 flex-col border-l border-line bg-panel"
    :class="wide ? 'w-[60vw]' : ''"
    :style="wide ? undefined : { width: `${applied}px` }"
  >
    <div
      v-if="!wide"
      data-test="details-resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="Redimensionar detalhes"
      tabindex="0"
      :aria-valuenow="applied"
      :aria-valuemin="DETAILS_MIN_WIDTH"
      :aria-valuemax="maxWidth"
      title="Arraste para redimensionar · duplo clique volta ao padrão"
      class="absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize touch-none hover:bg-primary/30 focus-visible:bg-primary/40 focus-visible:outline-none"
      @pointerdown="startDrag"
      @pointermove="moveDrag"
      @pointerup="endDrag"
      @pointercancel="endDrag"
      @dblclick="resetWidth"
      @keydown="onResizeKey"
    />
```

- [ ] **Step 5: Rodar tudo e ver passar**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: PASS. Testes antigos que procuravam a classe `w-[360px]` devem passar a conferir `style.width === '360px'`. Ajuste-os e cite no relatório.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "[UI] Permitir ajustar a largura do painel Detalhes"
```

---

### Task 9: Progresso do plano no painel Detalhes

**Files:**
- Modify:
  - `frontend/src/components/plan/PlanStrip.vue`
  - `frontend/src/components/details/DetailsPanel.vue`
  - `frontend/src/views/ConversationView.vue` (linhas 7, 8 e 114)
- Test:
  - `frontend/src/components/plan/__tests__/PlanStrip.spec.ts`
  - `frontend/src/components/details/__tests__/DetailsPanel.spec.ts`
  - `frontend/src/views/__tests__/ConversationView.spec.ts`

**Interfaces:**
- Produces: `PlanStrip` com a prop `variant?: 'strip' | 'panel'`, padrão `'strip'`.

- [ ] **Step 1: Testes que falham**

Em `PlanStrip.spec.ts`, com o setup de montagem do arquivo e a mesma rota falsa de `GET /api/sessions/<id>/plan`:

```ts
it('no painel, a lista de tarefas já vem aberta', async () => {
  const w = await mountStrip({ variant: 'panel' }) // adapte ao helper do arquivo
  await flushPromises()
  expect(w.find('[data-test="plan-toggle"]').attributes('aria-expanded')).toBe('true')
  expect(w.findAll('[data-test="plan-task"]').length).toBeGreaterThan(0)
  expect(w.find('[data-test="plan-strip"]').classes()).not.toContain('max-w-[760px]')
})

it('no painel, o botão recolhe a lista', async () => {
  const w = await mountStrip({ variant: 'panel' })
  await flushPromises()
  await w.find('[data-test="plan-toggle"]').trigger('click')
  expect(w.findAll('[data-test="plan-task"]').length).toBe(0)
})
```

Em `DetailsPanel.spec.ts`:

```ts
it('mostra a seção Plano quando a sessão tem plano visível', async () => {
  // session with plan: { title: 'Plano X', done: 3, total: 8, ... } as in PlanStrip.spec
  expect(w.find('[data-test="details-plan"]').exists()).toBe(true)
  expect(w.find('[data-test="details-plan"] [data-test="plan-strip"]').exists()).toBe(true)
})

it('sem plano, não há seção Plano', async () => {
  expect(w.find('[data-test="details-plan"]').exists()).toBe(false)
})
```

Em `ConversationView.spec.ts`, troque o teste que espera `plan-strip` na coluna, se houver, por:

```ts
it('o progresso do plano não fica mais acima da conversa', async () => {
  // session with a visible plan, wide screen with the panel open
  const strips = w.findAll('[data-test="plan-strip"]')
  expect(strips.length).toBe(1)
  expect(w.find('[data-test="details-panel"] [data-test="plan-strip"]').exists()).toBe(true)
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/plan src/components/details src/views/__tests__/ConversationView.spec.ts`
Expected: FAIL

- [ ] **Step 3: Implementar**

`PlanStrip.vue`:

```ts
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ session: Session; variant?: 'strip' | 'panel' }>(), { variant: 'strip' })
const inPanel = computed(() => props.variant === 'panel')

const open = ref(inPanel.value)
// (keep tasks, error, list, requestId, load and toggle as they are)

onMounted(() => { if (open.value && visible.value) load() })

// Another conversation starts over (the panel reopens the list).
watch(() => props.session.session_id, () => {
  open.value = inPanel.value
  requestId++
  tasks.value = []
  error.value = null
  if (open.value) load()
})
```

No template, na raiz e no `<ol>`:

```vue
  <section
    v-if="visible && plan"
    data-test="plan-strip"
    aria-label="Plano"
    class="flex w-full flex-col gap-1.5"
    :class="inPanel ? '' : 'mx-auto max-w-[760px] px-4 pb-3'"
  >
  ...
    <ol v-if="open && tasks.length" ref="list" class="m-0 flex list-none flex-col gap-0.5 p-0 pt-1" :class="inPanel ? '' : 'max-h-56 overflow-y-auto'">
```

No painel, o título do plano ocupa `max-w-[35%]`, o que fica apertado. Troque a classe do título por `:class="inPanel ? 'max-w-[45%]' : 'max-w-[35%]'"`, mantendo `shrink-0 truncate text-xs text-fg-muted`.

`DetailsPanel.vue`: importe `PlanStrip` e `planVisible` (de `../plan/PlanStrip.vue` e `../plan/planText`). Entre a seção de propriedades e a de alterações:

```vue
        <section v-if="session && planVisible(session)" data-test="details-plan" aria-labelledby="plan-title" class="flex flex-col gap-2">
          <h3 id="plan-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Plano</h3>
          <PlanStrip :key="sessionId" :session="session" variant="panel" />
        </section>
```

`ConversationView.vue`: apague a linha 114 (`<PlanStrip ... />`) e os imports de `PlanStrip` e `planVisible`, se não forem mais usados no arquivo.

- [ ] **Step 4: Rodar tudo e ver passar**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "[UI] Levar o progresso do plano para o painel Detalhes"
```

---

### Task 10: Menu lateral com "Em execução", sigla do projeto e Recentes estável

**Files:**
- Create:
  - `frontend/src/projectInitials.ts`
  - `frontend/src/components/sidebar/ProjectBadge.vue`
  - `frontend/src/components/sidebar/SidebarSessionRow.vue`
  - `frontend/src/components/sidebar/SidebarRunning.vue`
  - `frontend/src/components/sidebar/itemClass.ts`
- Modify:
  - `frontend/src/recentConversations.ts`
  - `frontend/src/components/sidebar/AppSidebar.vue`
- Test:
  - `frontend/src/__tests__/projectInitials.spec.ts`
  - `frontend/src/__tests__/recentConversations.spec.ts` (existente)
  - `frontend/src/components/sidebar/__tests__/SidebarRunning.spec.ts` (novo)
  - `frontend/src/components/sidebar/__tests__/AppSidebar.spec.ts` (existente)

**Interfaces:**
- Consumes: `worktreeLabel` e `WorktreeLabel` (Tarefa 6). `display_state === 'running'` inclui o CLI (Tarefa 3).
- Produces:
  - `projectInitials(name: string): string`
  - `ProjectBadge` com props `{ project: Project }`.
  - `SidebarSessionRow` com props `{ session: Session }`; os atributos passam para o link.
  - `SidebarRunning`, sem props.
  - `sidebarItemClass(active: boolean): string[]`
  - Em `recentConversations.ts`:
    - `shownRecentIds: Ref<string[]>`
    - `noteOpened(id)`, com a regra nova
    - `noteRunning(id): string[]`
  - Constantes `RUNNING_MAX = 8` (em `SidebarRunning.vue`) e `RECENT_VISIBLE = 5` (em `recentConversations.ts`).

- [ ] **Step 1: Testes que falham, com a sigla e os recentes**

`frontend/src/__tests__/projectInitials.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { projectInitials } from '../projectInitials'

describe('projectInitials', () => {
  it.each([
    ['loja-online', 'LO'],
    ['vini7-vibing', 'VV'],
    ['dash_crm', 'DC'],
    ['angular body', 'AB'],
    ['lojaOnline', 'LO'],
    ['Vibing', 'VI'],
    ['x', 'X'],
    ['ação-rápida', 'AR'],
    ['', '?'],
    ['--', '?'],
  ])('%s → %s', (name, expected) => {
    expect(projectInitials(name)).toBe(expected)
  })
})
```

Acrescente ao `frontend/src/__tests__/recentConversations.spec.ts` (mantenha os testes existentes):

```ts
import { noteOpened, noteRunning, readRecent, shownRecentIds } from '../recentConversations'

beforeEach(() => { localStorage.clear(); shownRecentIds.value = [] })

it('abrir uma conversa já visível em Recentes não muda a ordem', () => {
  noteOpened('c'); noteOpened('b'); noteOpened('a') // [a, b, c]
  shownRecentIds.value = ['a', 'b', 'c']
  expect(noteOpened('c')).toEqual(['a', 'b', 'c'])
  expect(readRecent()).toEqual(['a', 'b', 'c'])
})

it('abrir uma conversa fora da lista visível leva ao topo', () => {
  noteOpened('c'); noteOpened('b'); noteOpened('a')
  shownRecentIds.value = ['a', 'b']
  expect(noteOpened('c')).toEqual(['c', 'a', 'b'])
})

it('noteRunning só acrescenta quem ainda não está na lista', () => {
  noteOpened('b'); noteOpened('a') // [a, b]
  expect(noteRunning('b')).toEqual(['a', 'b'])
  expect(noteRunning('z')).toEqual(['z', 'a', 'b'])
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/__tests__/projectInitials.spec.ts src/__tests__/recentConversations.spec.ts`
Expected: FAIL

- [ ] **Step 3: Implementar `projectInitials.ts` e `recentConversations.ts`**

```ts
/** Two-letter tag of a project: first letters of its first two words, or the first two letters. */
export function projectInitials(name: string): string {
  const plain = name.normalize('NFD').replace(/[̀-ͯ]/g, '')
  const words = plain
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[\s\-_.]+/)
    .filter(Boolean)
  if (words.length === 0) return '?'
  const letters = words.length >= 2 ? words[0]!.charAt(0) + words[1]!.charAt(0) : words[0]!.slice(0, 2)
  return letters.toUpperCase()
}
```

Em `recentConversations.ts`, troque `noteOpened` por:

```ts
/** How many recent conversations the sidebar shows. */
export const RECENT_VISIBLE = 5

/** Ids the sidebar is showing under "Recentes" right now (it writes them). */
export const shownRecentIds = ref<string[]>([])

function save(ids: string[]): string[] {
  recentIds.value = ids
  try {
    localStorage.setItem(KEY, JSON.stringify(ids))
  } catch {
    // Without storage the history lasts only for this page.
  }
  return ids
}

/**
 * A conversation was opened. One already shown under "Recentes" keeps its place, so
 * clicking down the list does not reshuffle it; any other goes to the front.
 */
export function noteOpened(id: string): string[] {
  const current = readRecent()
  if (shownRecentIds.value.includes(id) && current.includes(id)) {
    recentIds.value = current
    return current
  }
  return save([id, ...current.filter((other) => other !== id)].slice(0, RECENT_MAX))
}

/** A conversation started running (in the app or elsewhere): listed once, at the front. */
export function noteRunning(id: string): string[] {
  const current = readRecent()
  if (current.includes(id)) return current
  return save([id, ...current].slice(0, RECENT_MAX))
}
```

- [ ] **Step 4: Testes que falham, com os componentes**

`frontend/src/components/sidebar/__tests__/SidebarRunning.spec.ts`. Siga o setup de `AppSidebar.spec.ts`: Pinia, `useSessionsStore().setForProject(...)`, `useProjectsStore().projects = [...]` e `createAppRouter(createMemoryHistory())`.

```ts
function running(id: string, at: number, extra = {}) {
  return makeSession({ session_id: id, project_id: 1, title: `T ${id}`, display_state: 'running', last_activity_at: at, ...extra })
}

it('lista as sessões em execução, da mais recente para a mais antiga, com a sigla do projeto', async () => {
  sessions.setForProject(1, [running('a', 10), running('b', 30), makeSession({ session_id: 'c', project_id: 1 })])
  const w = await mountRunning()
  const rows = w.findAll('[data-test="running"]')
  expect(rows.map((r) => r.text())).toEqual([expect.stringContaining('T b'), expect.stringContaining('T a')])
  const badge = rows[0]!.find('[data-test="project-badge"]')
  expect(badge.text()).toBe('LO') // makeProject name 'loja-online'
  expect(badge.attributes('title')).toBe('loja-online')
})

it('conversa do CLI em execução aparece', async () => {
  sessions.setForProject(1, [running('cli', 5, { state: 'closed', cli_running: true })])
  const w = await mountRunning()
  expect(w.findAll('[data-test="running"]').length).toBe(1)
})

it('mostra no máximo 8 e oferece Ver todas', async () => {
  sessions.setForProject(1, Array.from({ length: 10 }, (_, i) => running(`s${i}`, i)))
  const w = await mountRunning()
  expect(w.findAll('[data-test="running"]').length).toBe(8)
  const all = w.find('[data-test="running-all"]')
  expect(all.text()).toBe('Ver todas')
  expect(all.attributes('href')).toBe('/inbox?aba=em-execucao')
})

it('sem nada em execução, a seção não aparece', async () => {
  sessions.setForProject(1, [makeSession({ session_id: 'c', project_id: 1 })])
  const w = await mountRunning()
  expect(w.find('[data-test="sidebar-running"]').exists()).toBe(false)
})

it('sessão em worktree mostra o ícone com a dica', async () => {
  sessions.setForProject(1, [running('w', 1, { worktree_name: 'x', git_branch: 'feat' })])
  const w = await mountRunning()
  expect(w.find('[data-test="row-worktree"]').attributes('title')).toBe('worktree x · feat')
})
```

Acrescente ao `AppSidebar.spec.ts` (mantenha os testes de Recentes que já existem):

```ts
it('Recentes não repete o que está em execução', async () => {
  noteOpened('b'); noteOpened('a')
  sessions.setForProject(1, [
    makeSession({ session_id: 'a', project_id: 1, display_state: 'running' }),
    makeSession({ session_id: 'b', project_id: 1 }),
  ])
  const w = await mountSidebar()
  expect(w.findAll('[data-test="recent"]').map((r) => r.attributes('href'))).toEqual(['/sessions/b'])
  expect(w.findAll('[data-test="running"]').length).toBe(1)
})

it('conversa que passou a rodar entra em Recentes e fica lá quando para', async () => {
  const w = await mountSidebar()
  sessions.setForProject(1, [makeSession({ session_id: 'cli', project_id: 1, display_state: 'running', cli_running: true })])
  await flushPromises()
  expect(readRecent()).toContain('cli')
  sessions.find('cli')!.display_state = 'waiting'
  await flushPromises()
  expect(w.findAll('[data-test="recent"]').map((r) => r.attributes('href'))).toContain('/sessions/cli')
})

it('linhas de Recentes mostram a sigla do projeto', async () => {
  noteOpened('b')
  sessions.setForProject(1, [makeSession({ session_id: 'b', project_id: 1 })])
  const w = await mountSidebar()
  expect(w.find('[data-test="recent"] [data-test="project-badge"]').text()).toBe('LO')
})

it('publica os ids visíveis em Recentes', async () => {
  noteOpened('b'); noteOpened('a')
  sessions.setForProject(1, [makeSession({ session_id: 'a', project_id: 1 }), makeSession({ session_id: 'b', project_id: 1 })])
  await mountSidebar()
  await flushPromises()
  expect(shownRecentIds.value).toEqual(['a', 'b'])
})
```

Confira o formato de rota da conversa usado nos testes existentes (`/sessions/<id>` ou outro) e use o mesmo.

- [ ] **Step 5: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/sidebar`
Expected: FAIL

- [ ] **Step 6: Implementar os componentes**

`frontend/src/components/sidebar/itemClass.ts`:

```ts
/** Classes of a sidebar entry; `active` marks the page being shown. */
export function sidebarItemClass(active: boolean): string[] {
  return [
    'flex min-h-10 items-center gap-2.5 rounded-lg px-3 no-underline hover:bg-card',
    active ? 'bg-elevated text-fg' : 'text-fg-muted hover:text-fg',
  ]
}
```

`ProjectBadge.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { projectInitials } from '../../projectInitials'
import type { Project } from '../../types/api'

const props = defineProps<{ project: Project }>()
const initials = computed(() => projectInitials(props.project.name))
</script>

<template>
  <span
    data-test="project-badge"
    :title="project.name"
    class="inline-flex h-3.5 min-w-[18px] shrink-0 items-center justify-center rounded-[3px] px-0.5 text-[9px] leading-none font-semibold text-bg"
    :style="{ backgroundColor: project.color }"
  >{{ initials }}</span>
</template>
```

`SidebarSessionRow.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import ProjectBadge from './ProjectBadge.vue'
import { sidebarItemClass } from './itemClass'
import { useProjectsStore } from '../../stores/projects'
import { worktreeLabel } from '../../worktree'
import type { Session } from '../../types/api'

const props = defineProps<{ session: Session }>()
const route = useRoute()
const projects = useProjectsStore()
const project = computed(() => projects.byId(props.session.project_id))
const worktree = computed(() => worktreeLabel(props.session))
const active = computed(() => route.name === 'session' && route.params.id === props.session.session_id)
</script>

<template>
  <RouterLink
    :to="{ name: 'session', params: { id: session.session_id } }"
    :class="sidebarItemClass(active)"
    :aria-current="active ? 'page' : undefined"
  >
    <DisplayStateIcon :display="session.display_state" :size="11" />
    <ProjectBadge v-if="project" :project="project" />
    <span class="min-w-0 grow truncate text-[13px]">{{ session.title }}</span>
    <span v-if="worktree" data-test="row-worktree" :title="worktree" :aria-label="worktree" class="shrink-0 text-fg-muted">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><path d="M6.5 10v4a3 3 0 0 0 3 3H14" />
      </svg>
    </span>
  </RouterLink>
</template>
```

`SidebarRunning.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import SidebarSessionRow from './SidebarSessionRow.vue'
import { useSessionsStore } from '../../stores/sessions'

const RUNNING_MAX = 8
const sessions = useSessionsStore()
// `all` is already newest first; the CLI mid-turn counts as running (display_state).
const running = computed(() => sessions.all.filter((s) => s.display_state === 'running'))
const shown = computed(() => running.value.slice(0, RUNNING_MAX))
</script>

<template>
  <div v-if="running.length" data-test="sidebar-running" class="flex flex-col gap-1">
    <div class="px-3 pt-4 pb-0.5 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Em execução</div>
    <SidebarSessionRow v-for="session in shown" :key="session.session_id" data-test="running" :session="session" />
    <RouterLink
      v-if="running.length > RUNNING_MAX"
      data-test="running-all"
      :to="{ name: 'inbox', query: { aba: 'em-execucao' } }"
      class="px-3 py-1 text-xs text-fg-muted no-underline hover:text-fg"
    >Ver todas</RouterLink>
  </div>
</template>
```

`AppSidebar.vue`:
- Troque a função local `itemClass` por `const itemClass = sidebarItemClass`, importada de `./itemClass`.
- Importe `SidebarRunning` e `SidebarSessionRow`.
- Importe `noteRunning`, `recentIds`, `RECENT_VISIBLE` e `shownRecentIds` de `../../recentConversations`.
- Troque o `computed` `recent`:

```ts
const runningIds = computed(() => new Set(sessions.all.filter((s) => s.display_state === 'running').map((s) => s.session_id)))
// A conversation that starts running (here or in a terminal) joins "Recentes", so it
// stays there when it stops.
watch(runningIds, (ids) => { for (const id of ids) noteRunning(id) }, { immediate: true })
// Conversations opened or seen running, newest first, minus those listed under "Em execução".
const recent = computed(() =>
  recentIds.value
    .map((id) => sessions.find(id))
    .filter((s): s is NonNullable<typeof s> => s != null && !runningIds.value.has(s.session_id))
    .slice(0, RECENT_VISIBLE),
)
watchEffect(() => { shownRecentIds.value = recent.value.map((s) => s.session_id) })
```

Importe `watch` e `watchEffect` de `vue`. No template, troque o bloco `<template v-if="recent.length">` por:

```vue
      <SidebarRunning />
      <template v-if="recent.length">
        <div class="px-3 pt-4 pb-0.5 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Recentes</div>
        <SidebarSessionRow v-for="session in recent" :key="session.session_id" data-test="recent" :session="session" />
      </template>
```

- [ ] **Step 7: Rodar tudo e ver passar**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: PASS. Testes antigos de Recentes que esperavam a sessão aberta sempre no topo ainda passam, porque `shownRecentIds` começa vazio em cada teste. Se algum falhar por isso, zere `shownRecentIds.value = []` no `beforeEach` dele.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/
git commit -m "[UI] Adicionar Em execução e sigla do projeto ao menu lateral"
```

---

### Task 11: Ditado no modal de nova conversa

**Files:**
- Create: `frontend/src/test/fakeRecognition.ts`, extraído de `composerExtras.spec.ts`.
- Modify:
  - `frontend/src/components/NewConversationModal.vue`
  - `frontend/src/components/conversation/__tests__/composerExtras.spec.ts`, que passa a importar o helper.
- Test: `frontend/src/components/__tests__/NewConversationModalDictation.spec.ts` (novo)

**Interfaces:**
- Consumes: `useDictation(target)` de `frontend/src/conversation/dictation.ts`, que devolve `supported`, `recording`, `error`, `toggle()` e `stop()`.
- Produces: o helper de teste `FakeRecognition`, exportado de `frontend/src/test/fakeRecognition.ts`.

- [ ] **Step 1: Extrair o helper**

Mova a classe `FakeRecognition` do fim de `composerExtras.spec.ts` para `frontend/src/test/fakeRecognition.ts`, como `export class FakeRecognition { ... }`, com o corpo idêntico. No spec, importe com `import { FakeRecognition } from '../../../test/fakeRecognition'`.

Run: `pnpm --dir frontend exec vitest run src/components/conversation/__tests__/composerExtras.spec.ts`
Expected: PASS (a refatoração não muda nada)

- [ ] **Step 2: Testes que falham**

`frontend/src/components/__tests__/NewConversationModalDictation.spec.ts`. Copie o `beforeEach`, `handlers` e `openModal` de `NewConversationModal.spec.ts`.

```ts
import { FakeRecognition } from '../../test/fakeRecognition'

describe('modal de nova conversa: ditado', () => {
  it('sem suporte do navegador, o botão não aparece', async () => {
    const { wrapper } = await openModal(2)
    expect(wrapper.find('[data-test="nc-dictate"]').exists()).toBe(false)
  })

  it('dita no cursor do prompt e não envia sozinho', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper, fetch } = await openModal(2)
    const prompt = wrapper.find('[data-test="nc-prompt"]')
    await prompt.setValue('corrija bug')
    ;(prompt.element as HTMLTextAreaElement).setSelectionRange(8, 8)
    const mic = wrapper.find('[data-test="nc-dictate"]')
    expect(mic.attributes('aria-label')).toBe('Ditar mensagem')
    await mic.trigger('click')
    const rec = FakeRecognition.last!
    expect(rec.lang).toBe('pt-BR')
    expect(wrapper.find('[data-test="nc-recording"]').text()).toContain('Gravando')
    rec.emit(['o', true])
    await flushPromises()
    expect((prompt.element as HTMLTextAreaElement).value).toBe('corrija o bug')
    expect(fetch.mock.calls.filter(([url]) => String(url).includes('/sessions')).length).toBe(0)
  })

  it('iniciar a conversa para o ditado', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-dictate"]').trigger('click')
    const rec = FakeRecognition.last!
    rec.emit(['oi', true])
    await flushPromises()
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(rec.started).toBe(false)
  })

  it('fechar o modal para o ditado', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-dictate"]').trigger('click')
    const rec = FakeRecognition.last!
    await wrapper.find('[data-test="nc-prompt"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(rec.started).toBe(false)
  })

  it('digitar durante a gravação para o ditado', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { wrapper } = await openModal(2)
    await wrapper.find('[data-test="nc-dictate"]').trigger('click')
    await wrapper.find('[data-test="nc-prompt"]').setValue('escrevi')
    expect(wrapper.find('[data-test="nc-dictate"]').attributes('aria-pressed')).toBe('false')
  })
})
```

Se Esc no prompt não fechar o modal nos testes existentes, use o mesmo caminho que `NewConversationModal.spec.ts` usa para fechar (botão × ou Esc no diálogo).

- [ ] **Step 3: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/__tests__/NewConversationModalDictation.spec.ts`
Expected: FAIL (sem `nc-dictate`)

- [ ] **Step 4: Implementar**

No script de `NewConversationModal.vue`:

```ts
import { useDictation } from '../conversation/dictation'

const dictation = useDictation({
  begin() {
    const el = promptEl.value
    return { text: draft.value.prompt, cursor: el?.selectionStart ?? draft.value.prompt.length }
  },
  update(value, cursor) {
    draft.value.prompt = value
    const el = promptEl.value
    if (el) {
      el.value = value
      el.setSelectionRange(cursor, cursor)
    }
  },
})
function stopDictation() {
  if (dictation.recording.value) dictation.stop()
}
// Typing while dictating stops it, so it does not overwrite what was typed.
function onPromptInput() {
  stopDictation()
}
// The modal stays mounted while closed: closing it by any path stops the dictation.
watch(() => store.isOpen, (open) => { if (!open) stopDictation() })
```

Confira que `watch` está importado de `vue` e que o store do modal se chama `store` no arquivo, como mostra `store.close()` em `close()`. No começo de `submit()`, logo depois de `if (!canSubmit.value) return`, chame `stopDictation()`.

No `<textarea data-test="nc-prompt">`, acrescente `@input="onPromptInput"`.

Na barra, logo depois do botão `nc-attach`:

```vue
            <button
              v-if="dictation.supported"
              type="button"
              data-test="nc-dictate"
              :aria-label="dictation.recording.value ? 'Parar ditado' : 'Ditar mensagem'"
              :aria-pressed="dictation.recording.value"
              :title="dictation.recording.value ? 'Parar ditado' : 'Ditar mensagem'"
              class="flex h-9 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 text-sm"
              :class="dictation.recording.value ? 'border-secondary/60 bg-secondary/10 text-secondary' : 'border-line-strong bg-transparent text-fg-muted hover:text-fg'"
              @click="dictation.toggle"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
              Ditar
            </button>
```

Logo depois da `div` da barra, antes de `nc-error`:

```vue
          <span v-if="dictation.recording.value" data-test="nc-recording" role="status" class="flex items-center gap-1.5 text-xs text-secondary">
            <span class="size-2 animate-pulse rounded-full bg-secondary" aria-hidden="true" />Gravando… clique no microfone para parar
          </span>
          <p v-else-if="dictation.error.value" role="alert" class="m-0 text-sm text-diff-del-fg">{{ dictation.error.value }}</p>
```

- [ ] **Step 5: Rodar tudo e ver passar**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "[Feat] Adicionar ditado ao modal de nova conversa"
```

---

### Task 12: Verificação manual contra o SDK real e fechamento (sessão principal)

Feita pela sessão principal, não por subagente.

- [ ] **Step 1: Teste manual da retomada numa worktree.** Siga as regras do `CLAUDE.md`: `haiku`, pasta temporária, `setting_sources=[]`, variáveis `CLAUDE*` removidas, `delete_session` ao final.
  1. Numa pasta temporária, criar um repositório git com um commit e uma worktree (`git worktree add`).
  2. Criar uma sessão curta com `cwd` no repositório principal, com um prompt de uma palavra.
  3. Mover o `.jsonl` para a pasta de histórico sanitizada da worktree, como o CLI faz.
  4. Confirmar que `get_session_messages(sid, directory=<worktree>)` encontra a conversa.
  5. Retomar com `cwd=<worktree>` e `resume=sid`, com mais um prompt mínimo, e confirmar a resposta.
  6. Apagar a sessão.
  7. Registrar o resultado em "Pontos em aberto" do `ROADMAP.md`.
- [ ] **Step 2: Rodar tudo.** `uv run pytest -q`, `pnpm --dir frontend test` e `pnpm --dir frontend build`.
- [ ] **Step 3: Revisão do marco pelo `milestone-reviewer`.**
- [ ] **Step 4: Atualizar o `ROADMAP.md`.** Marcar os itens com a data e mudar o estado do marco 10 para Concluído.
