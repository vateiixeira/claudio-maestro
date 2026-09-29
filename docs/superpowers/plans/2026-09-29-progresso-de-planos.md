# Progresso de planos — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar, na página da conversa, na linha de conversa, no Detalhes e no Dashboard, em que tarefa está cada conversa que executa um plano de `docs/superpowers/plans/`.

**Architecture:** O backend lê e interpreta o arquivo do plano (módulo puro `plans.py` com cache por `mtime`), guarda no SQLite o vínculo conversa → plano (automático pelas chamadas `Read`/`Edit`/`Write` da conversa, com ajuste manual) e publica o progresso no resumo da sessão (`plan`), a partir de um cache em memória. O frontend só exibe. A fonte confiável é uma regra no `~/.claude/CLAUDE.md` do usuário que manda marcar todas as caixas de uma tarefa quando ela é concluída.

**Tech Stack:** Python 3.13, FastAPI, SQLite, pytest (backend); Vue 3, TypeScript, Pinia, Tailwind, Vitest, pnpm (frontend).

**Spec:** `docs/superpowers/specs/2026-09-29-progresso-de-planos-design.md` (leia antes de qualquer tarefa).

## Restrições globais

- Siga o `CLAUDE.md` da raiz: TDD, textos da interface em português, código em inglês, nada da marca "Claude Code" na interface, `pnpm` e nunca `npx`/`yarn`, testes nunca tocam o SDK real.
- Subagentes não fazem commit nem `git add`, não sobem servidores nem matam processos.
- Todo caminho recebido precisa estar, depois de resolvido, dentro da pasta de um projeto registrado. Links simbólicos para fora são recusados.
- Listagens nunca leem arquivo de plano por item: `plan` no resumo vem só do cache em memória.
- Leitura de arquivo de plano fora do loop de eventos (`asyncio.to_thread`) quando feita em rota ou varredura.
- Arquivo de plano acima de 2 MB: tratado como sem plano (`plan: null`).
- Rotas novas protegidas como as outras (o middleware de `security.py` já cobre `/api/`; prove com teste).

## Contrato (backend ↔ frontend)

```text
SessionOut.plan: {
  path: str, title: str, total: int, done: int,
  current: {number: int, title: str} | null   # null = plano 100%
} | null

GET  /api/sessions/{id}/plan   → PlanState
PUT  /api/sessions/{id}/plan   body {"path": str} | {"auto": true}  → PlanState
DELETE /api/sessions/{id}/plan → PlanState
PlanState: {link: "auto"|"manual"|"off", path: str|null,
            plan: SessionOut.plan, tasks: [{number: int, title: str, done: bool}]}

GET /api/projects/{id}/plans → [{path: str, title: str, total: int, done: int}]
```

Tipos TypeScript (acrescente exatamente estes em `frontend/src/types/api.ts`; tarefas paralelas acrescentam os mesmos, o conflito de integração é resolvido mantendo uma cópia):

```ts
export interface PlanCurrent { number: number; title: string }
export interface PlanSummary { path: string; title: string; total: number; done: number; current: PlanCurrent | null }
export interface PlanTask { number: number; title: string; done: boolean }
export interface PlanState { link: 'auto' | 'manual' | 'off'; path: string | null; plan: PlanSummary | null; tasks: PlanTask[] }
export interface ProjectPlan { path: string; title: string; total: number; done: number }
// em Session:
//   plan?: PlanSummary | null
```

## Foco da revisão

1. Plano com exemplos de markdown dentro de blocos de código (cabeçalhos `###` e caixas `- [ ]` em ``` ... ```): não podem contar como tarefas. (Tarefa 1.)
2. Plano editado enquanto é lido, ou apagado: `plan: null`, sem exceção e sem derrubar a varredura. (Tarefas 1 e 3.)
3. Conversa que lê vários planos: vale o último tocado; vínculo `manual`/`off` nunca é trocado pelo automático. (Tarefa 2.)
4. Muitas conversas (milhares no índice): listagem sem leitura de arquivo; varredura só dos planos de conversas não finalizadas e com cache por `mtime`. (Tarefas 2 e 3.)
5. Caminho de plano vindo do modelo com `..`, link simbólico ou fora de projeto: recusado sem vincular. (Tarefas 1 e 4.)

## Mapa de arquivos

| Arquivo | Papel |
|---|---|
| `backend/vibing/plans.py` (novo) | Interpretar o plano, validar caminho, cache por `mtime` |
| `backend/vibing/db.py` | Migração com `plan_path` e `plan_link` |
| `backend/vibing/sessions.py` | Campos no `SessionRecord`, vínculo ao vivo, `plan` no `describe`, cache de progresso no `SessionManager`, varredura |
| `backend/vibing/cliwatch.py` | Vínculo pelas linhas novas do arquivo de sessão do CLI |
| `backend/vibing/api/plans.py` (novo) | Rotas de plano |
| `backend/vibing/api/sessions.py` | `plan` no `SessionOut` |
| `backend/vibing/app.py` | Registrar rotas e a varredura no lifespan |
| `frontend/src/types/api.ts`, `frontend/src/api/http.ts` | Tipos e cliente |
| `frontend/src/components/plan/PlanStrip.vue` (novo) | Faixa na página da conversa |
| `frontend/src/components/plan/PlanBadge.vue` (novo) | Selo "4/12" |
| `frontend/src/components/details/DetailsPanel.vue` | Propriedade "Plano" |
| `frontend/src/components/conversation/ConversationRow.vue`, `components/dashboard/NowCard.vue` | Selo e linha da tarefa |
| `frontend/src/views/ConversationView.vue` | Encaixe da faixa |

## Ordem e paralelismo

- Tarefa 1 primeiro (backend). Tarefas 5, 6 e 7 (frontend) podem começar junto com a 1, contra o contrato acima.
- Tarefa 2 depois da 1. Tarefas 3 e 4 depois da 2, em paralelo entre si.
- Tarefa 8 (regra no CLAUDE.md global e teste manual) é feita pela sessão principal no fim.

---

### Tarefa 1: Interpretar o plano (`plans.py`)

**Files:**
- Create: `backend/vibing/plans.py`
- Test: `backend/tests/test_plans.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class PlanTask: number: int; title: str; done: bool`
  - `@dataclass(frozen=True) class PlanProgress: title: str; tasks: tuple[PlanTask, ...]` com propriedades `total -> int`, `done -> int`, `current -> PlanTask | None` e `summary(path: str) -> dict` no formato de `SessionOut.plan`.
  - `parse_plan(text: str, fallback_title: str) -> PlanProgress | None`
  - `is_plan_path(path: str | Path, project_roots: Iterable[Path]) -> Path | None` (devolve o caminho resolvido quando válido)
  - `class PlanCache: def read(self, path: Path) -> PlanProgress | None` (lê com cache por `(st_mtime_ns, st_size)`; `None` para ausente, ilegível, > 2 MB ou sem tarefas)
  - `MAX_PLAN_BYTES = 2 * 1024 * 1024`

- [x] **Step 1: Escrever os testes**

```python
# backend/tests/test_plans.py
from pathlib import Path

from vibing.plans import MAX_PLAN_BYTES, PlanCache, is_plan_path, parse_plan

FENCE = "`" * 3  # built at runtime so this plan file has no nested code fence

PLAN = f"""# Nova navegação — plano

## Restrições

- [ ] isto não é tarefa

### Tarefa 1: Resumo da sessão

- [x] **Step 1: teste**
- [x] **Step 2: código**

### Tarefa 2: Rotas

  - [X] passo recuado
  - [ ] passo aberto

### Task 3: English heading

- [ ] step

{FENCE}markdown
### Tarefa 99: exemplo dentro de bloco
- [ ] caixa de exemplo
{FENCE}

### Tarefa 4: Sem caixas

Só texto.
"""


def test_parse_counts_tasks_done_and_current():
    plan = parse_plan(PLAN, "fallback")
    assert plan is not None
    assert plan.title == "Nova navegação — plano"
    assert [(t.number, t.title, t.done) for t in plan.tasks] == [
        (1, "Resumo da sessão", True),
        (2, "Rotas", False),
        (3, "English heading", False),
        (4, "Sem caixas", False),
    ]
    assert plan.total == 4 and plan.done == 1
    assert plan.current is not None and plan.current.number == 2


def test_code_fences_are_ignored():
    plan = parse_plan(PLAN, "fallback")
    assert 99 not in [t.number for t in plan.tasks]


def test_all_done_has_no_current():
    text = "# P\n### Tarefa 1: A\n- [x] a\n### Tarefa 2: B\n- [x] b\n"
    plan = parse_plan(text, "p")
    assert plan.done == 2 and plan.current is None


def test_without_tasks_is_not_a_plan():
    assert parse_plan("# Só um documento\n\n- [ ] item\n", "x") is None


def test_fallback_title():
    plan = parse_plan("### Tarefa 1: A\n- [ ] a\n", "meu-plano")
    assert plan.title == "meu-plano"


def test_summary_shape():
    plan = parse_plan("# P\n### Tarefa 1: A\n- [x] a\n### Tarefa 2: B\n- [ ] b\n", "p")
    assert plan.summary("/x/p.md") == {
        "path": "/x/p.md", "title": "P", "total": 2, "done": 1,
        "current": {"number": 2, "title": "B"},
    }


def _plan_file(root: Path, name: str = "a.md") -> Path:
    folder = root / "docs" / "superpowers" / "plans"
    folder.mkdir(parents=True)
    path = folder / name
    path.write_text("# P\n### Tarefa 1: A\n- [ ] a\n", encoding="utf-8")
    return path


def test_is_plan_path_accepts_plan_inside_project(tmp_path: Path):
    path = _plan_file(tmp_path / "proj")
    assert is_plan_path(path, [tmp_path / "proj"]) == path.resolve()


def test_is_plan_path_rejects_outside_wrong_folder_and_symlink(tmp_path: Path):
    project = tmp_path / "proj"
    path = _plan_file(project)
    other = tmp_path / "outside"
    outside_plan = _plan_file(other)
    assert is_plan_path(outside_plan, [project]) is None
    assert is_plan_path(project / "docs" / "notes.md", [project]) is None
    assert is_plan_path(str(path) + ".txt", [project]) is None
    link = project / "docs" / "superpowers" / "plans" / "link.md"
    link.symlink_to(outside_plan)
    assert is_plan_path(link, [project]) is None
    assert is_plan_path(project / "docs/superpowers/plans/../plans/a.md", [project]) == path.resolve()


def test_cache_rereads_only_when_file_changes(tmp_path: Path, monkeypatch):
    path = _plan_file(tmp_path)
    cache = PlanCache()
    calls = []
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: calls.append(self) or real(self, *a, **k))
    assert cache.read(path).done == 0
    assert cache.read(path).done == 0
    assert len(calls) == 1
    path.write_text("# P\n### Tarefa 1: A\n- [x] a\n", encoding="utf-8")
    import os
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert cache.read(path).done == 1
    assert len(calls) == 2


def test_cache_missing_big_and_invalid(tmp_path: Path):
    cache = PlanCache()
    assert cache.read(tmp_path / "nope.md") is None
    big = tmp_path / "big.md"
    big.write_text("### Tarefa 1: A\n- [ ] a\n" + "x" * MAX_PLAN_BYTES, encoding="utf-8")
    assert cache.read(big) is None
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00 not utf8 ### Tarefa 1")
    assert cache.read(bad) is None
```

- [x] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q backend/tests/test_plans.py`
Expected: FAIL com `ModuleNotFoundError: No module named 'vibing.plans'`.

- [x] **Step 3: Implementar**

```python
# backend/vibing/plans.py
"""Progress of implementation plans (`docs/superpowers/plans/*.md`).

A task starts at a `### Tarefa N: title` (or `### Task N: title`) heading and
runs until the next heading of level 1 to 3. It is done when it has at least
one checkbox and all are checked. Fenced code blocks are ignored.
"""

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_PLAN_BYTES = 2 * 1024 * 1024
PLAN_DIR = ("docs", "superpowers", "plans")

_TASK = re.compile(r"^###\s+(?:Tarefa|Task)\s+(\d+)\s*[:.\-—]\s*(.+?)\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,3})\s+\S")
_TITLE = re.compile(r"^#\s+(.+?)\s*$")
_BOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class PlanTask:
    number: int
    title: str
    done: bool


@dataclass(frozen=True)
class PlanProgress:
    title: str
    tasks: tuple[PlanTask, ...]

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def done(self) -> int:
        return sum(1 for task in self.tasks if task.done)

    @property
    def current(self) -> PlanTask | None:
        return next((task for task in self.tasks if not task.done), None)

    def summary(self, path: str) -> dict[str, Any]:
        current = self.current
        return {
            "path": path, "title": self.title, "total": self.total, "done": self.done,
            "current": {"number": current.number, "title": current.title} if current else None,
        }


def parse_plan(text: str, fallback_title: str) -> PlanProgress | None:
    title: str | None = None
    tasks: list[PlanTask] = []
    number: int | None = None
    task_title = ""
    boxes = checked = 0
    in_fence = False

    def close() -> None:
        if number is not None:
            tasks.append(PlanTask(number, task_title, boxes > 0 and boxes == checked))

    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if title is None and (match := _TITLE.match(line)):
            title = match.group(1)
            continue
        if match := _TASK.match(line):
            close()
            number, task_title = int(match.group(1)), match.group(2)
            boxes = checked = 0
            continue
        if _HEADING.match(line):
            close()
            number = None
            continue
        if number is not None and (match := _BOX.match(line)):
            boxes += 1
            checked += match.group(1) in "xX"
    close()
    if not tasks:
        return None
    return PlanProgress(title or fallback_title, tuple(tasks))


def is_plan_path(path: str | Path, project_roots: Iterable[Path]) -> Path | None:
    """The resolved plan path when it is a `.md` directly inside a
    `docs/superpowers/plans/` folder of a registered project; None otherwise."""
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if resolved.suffix.lower() != ".md" or tuple(resolved.parent.parts[-3:]) != PLAN_DIR:
        return None
    for root in project_roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return resolved
        except (OSError, RuntimeError):
            continue
    return None


class PlanCache:
    """Parsed plans by path, re-read only when size or mtime changes. Thread-safe."""

    def __init__(self) -> None:
        self._entries: dict[Path, tuple[tuple[int, int], PlanProgress | None]] = {}
        self._lock = threading.Lock()

    def read(self, path: Path) -> PlanProgress | None:
        try:
            stat = path.stat()
        except OSError:
            with self._lock:
                self._entries.pop(path, None)
            return None
        key = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            entry = self._entries.get(path)
        if entry is not None and entry[0] == key:
            return entry[1]
        progress: PlanProgress | None = None
        if stat.st_size <= MAX_PLAN_BYTES:
            try:
                progress = parse_plan(path.read_text(encoding="utf-8"), path.stem)
            except (OSError, UnicodeDecodeError):
                progress = None
        with self._lock:
            self._entries[path] = (key, progress)
        return progress

    def forget(self, path: Path) -> None:
        with self._lock:
            self._entries.pop(path, None)
```

- [x] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q backend/tests/test_plans.py` e depois `uv run pytest -q`
Expected: todos PASS.

- [x] **Step 5: Commit (sessão principal)**

`[Feat] Interpretar progresso de planos em docs/superpowers/plans`

---

### Tarefa 2: Vínculo e progresso no resumo da sessão

**Files:**
- Modify: `backend/vibing/db.py` (nova migração no fim de `MIGRATIONS`)
- Modify: `backend/vibing/sessions.py` (`SessionRecord`, `_INSERT_COLUMNS`/`_COLUMNS`, `describe`, `_extras`/`describe_record`/`_describe_active`, `ActiveSession._note_tool_use` e o ponto que recebe mensagens de subagentes, fim de turno, `SessionManager`)
- Modify: `backend/vibing/api/sessions.py` (`SessionOut.plan`)
- Test: `backend/tests/test_plan_sessions.py`

**Interfaces:**
- Consumes (Tarefa 1): `PlanCache`, `is_plan_path`, `PlanProgress.summary`.
- Produces:
  - Colunas `sessions.plan_path TEXT`, `sessions.plan_link TEXT`; campos `SessionRecord.plan_path: str | None = None`, `SessionRecord.plan_link: str | None = None`.
  - `SessionManager.plan_cache: PlanCache` e `SessionManager.plan_summary(record: SessionRecord) -> dict | None` (só memória: devolve o último progresso conhecido do caminho, sem ler arquivo).
  - `async SessionManager.refresh_plan(session_id: str) -> bool` (relê em `asyncio.to_thread` via `plan_cache.read`; emite `session.updated` se o resumo mudou; devolve se mudou).
  - `SessionManager.link_plan(session_id: str, path: str, *, source: Literal["auto", "manual"]) -> bool` (valida com `is_plan_path` contra as pastas dos projetos registrados; `auto` não sobrescreve `manual`/`off`; grava; devolve se mudou).
  - `SessionManager.unlink_plan(session_id: str) -> None` (`plan_link='off'`, `plan_path=None`) e `SessionManager.auto_plan(session_id: str) -> None` (`plan_link='auto'`, mantém `plan_path`).
  - `SessionManager.project_roots() -> list[Path]` (pastas dos projetos registrados; se já existir função equivalente, reutilize).
  - `SessionOut.plan: PlanOut | None` com `PlanOut(path, title, total, done, current: PlanCurrentOut | None)`.
  - Constante `PLAN_TOOLS = {"Read", "Edit", "MultiEdit", "Write"}`.

- [ ] **Step 1: Escrever os testes** (use os fixtures e o cliente falso já usados em `backend/tests/test_context_permission.py` e `test_multisession.py`; crie projetos em `tmp_path` com um `docs/superpowers/plans/p.md`)

Casos obrigatórios, cada um um teste:
1. Migração: banco novo tem as colunas `plan_path` e `plan_link`; banco na versão anterior migra sem perder linhas.
2. Uma `AssistantMessage` do cliente falso com `ToolUseBlock(name="Read", input={"file_path": "<projeto>/docs/superpowers/plans/p.md"})` vincula a sessão (`record.plan_path` resolvido, `plan_link == "auto"`) e o próximo `session.updated` traz `plan == {"path": ..., "title": "P", "total": 2, "done": 1, "current": {"number": 2, "title": "B"}}` (arquivo com uma tarefa marcada e uma aberta).
3. Mensagem de subagente (com `parent_tool_use_id`) que faz `Edit` no plano também vincula.
4. Dois planos tocados em sequência: vale o último.
5. `plan_link == "manual"`: um `Read` de outro plano não troca. `plan_link == "off"`: um `Read` não religa.
6. `file_path` fora de projeto registrado, em pasta errada ou por link simbólico para fora: não vincula.
7. `Edit`/`Write` no plano vinculado seguido do resultado da ferramenta: `refresh_plan` roda e o `session.updated` traz o `done` novo (edite o arquivo no teste antes de entregar o `ToolResultBlock`/`UserMessage` do resultado).
8. Fim de turno (`ResultMessage`) chama `refresh_plan`.
9. `list_sessions()`/busca/listagem do projeto não leem arquivo de plano (conte chamadas de `PlanCache.read` com um espião): `plan` vem do cache em memória, `None` para vínculo ainda não lido.
10. O vínculo sobrevive a recriar o `SessionManager` sobre o mesmo banco (reinício do backend): `record.plan_path` volta e, depois de `refresh_plan`, `plan` aparece.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q backend/tests/test_plan_sessions.py`
Expected: FAIL (colunas e métodos ausentes).

- [ ] **Step 3: Implementar**

Migração (acrescente no fim de `MIGRATIONS` em `db.py`, no mesmo estilo):

```python
    [
        # Marco 9: plan the conversation executes. `plan_link` is "auto" (last plan
        # read or edited), "manual" (chosen by the user) or "off" (never auto-link).
        "ALTER TABLE sessions ADD COLUMN plan_path TEXT",
        "ALTER TABLE sessions ADD COLUMN plan_link TEXT",
    ],
```

`SessionRecord` ganha, no fim:

```python
    # Plan in docs/superpowers/plans the conversation executes (resolved path) and
    # how it was linked: "auto", "manual" or "off" (None = auto without a plan).
    plan_path: str | None = None
    plan_link: str | None = None
```

e as duas colunas entram em `_COLUMNS` (leitura) e em toda gravação que usa `SessionRecord.save`/`save(**changes)`; confira como `finished_at` foi acrescentado no marco 7 e repita o caminho.

No `SessionManager.__init__`: `self.plan_cache = PlanCache()` e `self._plan_progress: dict[str, dict | None] = {}` (resumo por caminho, só memória).

```python
    def plan_summary(self, record: SessionRecord) -> dict[str, Any] | None:
        if not record.plan_path:
            return None
        return self._plan_progress.get(record.plan_path)

    async def refresh_plan(self, session_id: str) -> bool:
        record = self._record(session_id)  # use o acesso a registro já existente
        if record is None or not record.plan_path:
            return False
        path = record.plan_path
        progress = await asyncio.to_thread(self.plan_cache.read, Path(path))
        summary = progress.summary(path) if progress else None
        if self._plan_progress.get(path) == summary and path in self._plan_progress:
            return False
        self._plan_progress[path] = summary
        self._emit_plan_change(path)  # session.updated para toda sessão aberta/ativa com esse plan_path
        return True
```

`_extras`/`describe` passam a receber `plan=self.plan_summary(record)` também para sessões sem cliente (o `plan` vem do registro, não da `ActiveSession`), e `describe` inclui `"plan": plan` no dicionário.

Vínculo ao vivo: em `ActiveSession`, ao receber uma `AssistantMessage` (principal ou de subagente), para cada `ToolUseBlock` com `name in PLAN_TOOLS` e `input.get("file_path")`, chame `manager.link_plan(session_id, file_path, source="auto")`; se vinculou, agende `manager.refresh_plan(session_id)`. Quando chegar o resultado de uma ferramenta `Edit`/`MultiEdit`/`Write` cujo `file_path` é o plano vinculado, agende `refresh_plan`. No fim de turno (onde `ResultMessage` é tratado), agende `refresh_plan`. Guarde as tarefas agendadas e cancele no `_dispose`, como as outras tarefas da sessão.

`api/sessions.py`:

```python
class PlanCurrentOut(BaseModel):
    number: int
    title: str


class PlanOut(BaseModel):
    path: str
    title: str
    total: int
    done: int
    current: PlanCurrentOut | None = None

# em SessionOut:
    plan: PlanOut | None = None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q` (suíte inteira, pelo menos 2 vezes)
Expected: PASS.

- [ ] **Step 5: Commit (sessão principal)**

`[Feat] Vincular conversa ao plano e publicar progresso no resumo`

---

### Tarefa 3: Vínculo pelo CLI, na retomada, e varredura de 30 s

**Files:**
- Modify: `backend/vibing/cliwatch.py` (em `_process`, depois de `update_session`)
- Modify: `backend/vibing/sessions.py` (leitura do histórico na retomada/abertura; `run_plan_sweep`)
- Modify: `backend/vibing/app.py` (tarefa de fundo no lifespan)
- Test: `backend/tests/test_plan_sync.py`

**Interfaces:**
- Consumes (Tarefa 2): `SessionManager.link_plan`, `SessionManager.refresh_plan`, `PLAN_TOOLS`.
- Produces:
  - `plans.scan_plan_refs(lines: Iterable[str]) -> str | None` (em `plans.py`): último `file_path` de `tool_use` com nome em `PLAN_TOOLS` numa sequência de linhas JSONL do histórico (principal ou `isSidechain`); ignora linhas inválidas. Mova `PLAN_TOOLS` para `plans.py` e importe em `sessions.py`.
  - `plans.read_new_lines(path: Path, offset: int | None, *, tail: int = 256 * 1024) -> tuple[list[str], int]`: linhas completas a partir de `offset` (ou só os últimos `tail` bytes, descartando a primeira linha parcial, quando `offset` é `None` ou maior que o tamanho atual); devolve as linhas e o novo offset (fim da última linha completa).
  - `async SessionManager.run_plan_sweep(interval: float, sleep=asyncio.sleep) -> None`: laço que, a cada `interval`, chama `refresh_plan` para cada sessão não finalizada com `plan_path` (lida do banco em `to_thread`), agrupando por caminho para ler cada plano uma vez; falhas registradas sem matar o laço.
  - `Settings.plan_sweep_interval_seconds: float = 30`.

- [ ] **Step 1: Escrever os testes**

1. `scan_plan_refs`: linhas JSONL reais de exemplo (`{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"/p/docs/superpowers/plans/a.md"}}]}}`), outra com `Edit` num segundo plano, uma linha quebrada e uma de outra ferramenta → devolve o segundo plano.
2. `read_new_lines`: arquivo com 3 linhas → offset `None` lê tudo que cabe na cauda; acrescentar 2 linhas (uma sem `\n` final) → só a linha completa nova volta e o offset para antes da parcial; arquivo truncado (offset > tamanho) → relê a cauda; arquivo com mais de `tail` bytes → primeira linha parcial descartada.
3. Observador do CLI: com o índice apontando uma sessão do CLI de um projeto registrado, escrever no arquivo `.jsonl` uma linha com `Read` do plano do projeto e disparar o processamento (siga os testes existentes de `cliwatch`) → `record.plan_path` vinculado e `session.updated` com `plan`. Uma segunda mudança sem referência não relê o arquivo inteiro (offset avança; espie `read_new_lines`).
4. Abrir/retomar uma sessão do histórico cujas mensagens têm `Read` de um plano → vinculada (use o caminho de leitura de histórico que o `SessionManager.open` já usa; o `get_session_messages` falso dos testes).
5. Varredura: duas sessões não finalizadas no mesmo plano e uma finalizada em outro → o arquivo do mesmo plano é lido uma vez por rodada, o da finalizada não; alterar o plano entre rodadas gera `session.updated`; plano apagado vira `plan: None` sem exceção; exceção no meio não mata o laço (injete `sleep` que conta rodadas e para depois de N).
6. Lifespan inicia a varredura só quando não há `agent_factory` injetado ou quando `create_app(plan_sweep=True)` (siga o padrão de `refresh_models`).

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q backend/tests/test_plan_sync.py`
Expected: FAIL.

- [ ] **Step 3: Implementar**

```python
# em backend/vibing/plans.py
import json

PLAN_TOOLS = frozenset({"Read", "Edit", "MultiEdit", "Write"})


def scan_plan_refs(lines: Iterable[str]) -> str | None:
    last: str | None = None
    for line in lines:
        if '"tool_use"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict) and block.get("type") == "tool_use"
                and block.get("name") in PLAN_TOOLS
                and isinstance(block.get("input"), dict)
                and isinstance(block["input"].get("file_path"), str)
            ):
                last = block["input"]["file_path"]
    return last


def read_new_lines(path: Path, offset: int | None, *, tail: int = 256 * 1024) -> tuple[list[str], int]:
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        start = offset if offset is not None and offset <= size else max(0, size - tail)
        handle.seek(start)
        data = handle.read(size - start)
    skip_partial_first = (offset is None or offset > size) and start > 0
    end = data.rfind(b"\n")
    if end < 0:
        return [], start
    chunk = data[: end + 1]
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    if skip_partial_first and lines:
        lines = lines[1:]
    return lines, start + end + 1
```

`cliwatch.py`: mantenha `self._plan_offsets: dict[str, int] = {}`; em `_process`, depois de `update_session`, rode em `to_thread` `read_new_lines(path, self._plan_offsets.get(session_id))`, guarde o novo offset, passe as linhas a `scan_plan_refs` e, se houver referência, chame `await self._sessions.link_plan(session_id, ref, source="auto")` e, se vinculou ou se a referência é o plano já vinculado, `await self._sessions.refresh_plan(session_id)`. Remova o offset quando o arquivo some.

Retomada: onde `SessionManager.open`/a `ActiveSession` carrega as mensagens do histórico, percorra os `ToolUseBlock` carregados (mesma regra de `PLAN_TOOLS`) e vincule ao último, como na Tarefa 2.

Varredura: implemente `run_plan_sweep` no `SessionManager` e registre no lifespan de `app.py` junto das outras tarefas (`tasks.append(asyncio.create_task(manager.run_plan_sweep(settings.plan_sweep_interval_seconds)))`), com o mesmo esquema de liga/desliga de `refresh_models`.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q` (2 vezes)
Expected: PASS.

- [ ] **Step 5: Commit (sessão principal)**

`[Feat] Vincular planos pelo CLI e atualizar progresso a cada 30 s`

---

### Tarefa 4: Rotas de plano

**Files:**
- Create: `backend/vibing/api/plans.py`
- Modify: `backend/vibing/app.py` (incluir o router)
- Test: `backend/tests/test_plans_api.py`

**Interfaces:**
- Consumes (Tarefas 1 e 2): `PlanCache`, `is_plan_path`, `SessionManager.link_plan/unlink_plan/auto_plan/refresh_plan/project_roots`, `gitinfo.discover_scan` (descoberta de repositórios do projeto).
- Produces: as rotas do contrato.

- [ ] **Step 1: Escrever os testes**

1. `GET /api/projects/{id}/plans`: projeto com `docs/superpowers/plans/a.md` (plano) e `b.md` (sem tarefas) na raiz, e um repositório `sub/` com `docs/superpowers/plans/c.md` → devolve `a` e `c` (não `b`), mais recente primeiro, com `title/total/done`; projeto inexistente → 404; projeto indisponível → `[]`.
2. `GET /api/sessions/{id}/plan` sem vínculo → `{"link": "auto", "path": null, "plan": null, "tasks": []}`; com vínculo → `tasks` com `number/title/done`; plano apagado → `path` preenchido, `plan: null`, `tasks: []`.
3. `PUT` com `{"path": plano}` → `link == "manual"` e `plan` preenchido; o próximo `session.updated` também. `PUT` com `{"auto": true}` → `link == "auto"`. Corpo vazio, com os dois campos, ou `path` que não é plano → 400; `path` fora de projeto registrado (inclusive link simbólico) → 403; sessão desconhecida → 404.
4. `DELETE` → `link == "off"`, `path: null`, e um `Read` posterior do plano pela conversa não religa (reaproveite o cliente falso da Tarefa 2).
5. Proteção: sem `X-Vibing` → 403; `Origin` estrangeira → 403 (como em `test_fs_pick_api.py::test_pick_is_protected`).

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q backend/tests/test_plans_api.py`
Expected: FAIL (404 nas rotas).

- [ ] **Step 3: Implementar**

```python
# backend/vibing/api/plans.py
"""Plans a conversation can be linked to, and the link itself."""

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, model_validator

router = APIRouter(prefix="/api")


class PlanLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None = None
    auto: Literal[True] | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> "PlanLinkIn":
        if (self.path is None) == (self.auto is None):
            raise ValueError("Informe o caminho do plano ou o modo automático.")
        return self
```

Implemente `GET /projects/{project_id}/plans` (listagem em `asyncio.to_thread`: raiz do projeto + repositórios de `gitinfo.discover_scan`, `glob("docs/superpowers/plans/*.md")`, `is_plan_path` + `plan_cache.read`, ordenado por `st_mtime` decrescente), e `GET/PUT/DELETE /sessions/{session_id}/plan` usando os métodos do `SessionManager` da Tarefa 2; o `PlanState` é montado lendo o plano pelo `plan_cache` em `to_thread`. Converta a validação do corpo em 400 com `detail` em português (um `ValueError` do validador vira 422 no FastAPI: trate com `RequestValidationError` só nesta rota ou valide manualmente dentro da rota — escolha a validação manual para devolver 400). `is_plan_path` falhando por estar fora de projeto → 403 ("O plano precisa estar dentro de um projeto registrado."); arquivo que não é plano (pasta errada, sem tarefas) → 400 ("O arquivo não é um plano com tarefas.").

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q` (2 vezes)
Expected: PASS.

- [ ] **Step 5: Commit (sessão principal)**

`[Feat] Adicionar rotas para listar, vincular e desligar planos`

---

### Tarefa 5: Faixa do plano na página da conversa (frontend)

**Files:**
- Modify: `frontend/src/types/api.ts` (tipos do contrato), `frontend/src/api/http.ts`
- Create: `frontend/src/components/plan/PlanStrip.vue`, `frontend/src/components/plan/planText.ts`
- Modify: `frontend/src/views/ConversationView.vue` (encaixe abaixo de `<ConversationHeader>`)
- Test: `frontend/src/components/plan/__tests__/PlanStrip.spec.ts`, `frontend/src/components/plan/__tests__/planText.spec.ts`

**Interfaces:**
- Consumes: contrato (`Session.plan`, `GET /api/sessions/{id}/plan`, `openInEditor`).
- Produces:
  - `http.ts`: `getSessionPlan(id: string): Promise<PlanState>`, `linkSessionPlan(id: string, body: { path: string } | { auto: true }): Promise<PlanState>`, `unlinkSessionPlan(id: string): Promise<PlanState>`, `listProjectPlans(projectId: number): Promise<ProjectPlan[]>` (todas via `request`, com `X-Vibing`).
  - `planText.ts`: `planPosition(plan: PlanSummary): string` → `"Tarefa 4 de 12: título"` (com `current`; `"Concluído"` sem), `planBadge(plan: PlanSummary): string` → `"4/12"` (número da tarefa atual e total; `"12/12"` sem atual), `planVisible(session: Pick<Session, 'plan' | 'finished' | 'display_state'>): boolean` → plano não nulo, conversa não finalizada, e `current` não nulo; `planStopped(session): boolean` → `display_state !== 'running'`.
  - `PlanStrip.vue` props `{ session: Session }`.

- [ ] **Step 1: Escrever os testes**

`planText.spec.ts`: as quatro funções com plano em andamento, 100%, conversa finalizada, rodando e parada.

`PlanStrip.spec.ts` (mock de `fetch` com `routeFetch` de `src/test/factories`):
1. Sessão rodando com `plan` → mostra o título do plano, "Tarefa 4 de 12: título" e um `role="progressbar"` com `aria-valuenow="3"` (concluídas) e `aria-valuemax="12"`.
2. Sessão parada (`display_state` diferente de `running`) → classe de apagado e o texto "· parado".
3. Plano 100% ou sessão finalizada ou `plan` nulo → nada renderizado.
4. Clicar no botão da faixa (`aria-expanded` vira `true`) busca `GET /api/sessions/{id}/plan` e lista as tarefas com o estado (concluída, atual, na fila) e a atual rolada para a vista; clicar de novo recolhe.
5. Quando `session.plan.done` muda com a lista aberta, a lista é buscada de novo.
6. "Abrir plano" chama `POST /api/open-in-editor` com o `path`; erro vira mensagem legível (`role="alert"`).

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/plan`
Expected: FAIL (arquivos ausentes).

- [ ] **Step 3: Implementar**

```ts
// frontend/src/components/plan/planText.ts
import type { PlanSummary, Session } from '../../types/api'

export function planPosition(plan: PlanSummary): string {
  return plan.current ? `Tarefa ${plan.current.number} de ${plan.total}: ${plan.current.title}` : 'Concluído'
}

export function planBadge(plan: PlanSummary): string {
  return plan.current ? `${plan.current.number}/${plan.total}` : `${plan.total}/${plan.total}`
}

export function planVisible(session: Pick<Session, 'plan' | 'finished' | 'display_state'>): boolean {
  return !!session.plan && !session.finished && session.display_state !== 'finished' && !!session.plan.current
}

export function planStopped(session: Pick<Session, 'display_state'>): boolean {
  return session.display_state !== 'running'
}
```

`PlanStrip.vue`: um `<section aria-label="Plano">` com um `<button type="button" :aria-expanded>` contendo o título do plano (texto secundário), `planPosition` e "· parado" quando `planStopped`; abaixo, `<div role="progressbar" :aria-valuenow="plan.done" :aria-valuemax="plan.total" aria-label="Progresso do plano">` com a barra (largura `done/total`, cor primária; cinza quando parada); à direita, botão "Abrir plano". Com a lista aberta, `<ol>` com cada tarefa: ✓ concluída (texto apagado), ● atual (destaque), ○ na fila, e `scrollIntoView({ block: 'nearest' })` na atual. Visual discreto, coerente com o cabeçalho da conversa (mesmas cores e espaçamentos). Encaixe em `ConversationView.vue` logo abaixo de `<ConversationHeader>`, com a sessão vinda do store de sessões (`sessions.find(id)`), só quando `planVisible`.

- [ ] **Step 4: Rodar e ver passar**

Run: `pnpm --dir frontend test` e `pnpm --dir frontend build`
Expected: PASS.

- [ ] **Step 5: Commit (sessão principal)**

`[Feat] Mostrar faixa do plano na página da conversa`

---

### Tarefa 6: Plano no painel Detalhes (frontend)

**Files:**
- Modify: `frontend/src/components/details/DetailsPanel.vue`
- Create: `frontend/src/components/plan/PlanProperty.vue`
- Modify (se ainda não tiver os tipos/funções da Tarefa 5): `frontend/src/types/api.ts`, `frontend/src/api/http.ts` — com exatamente as mesmas assinaturas da Tarefa 5
- Test: `frontend/src/components/plan/__tests__/PlanProperty.spec.ts`

**Interfaces:**
- Consumes: contrato; `getSessionPlan`, `linkSessionPlan`, `unlinkSessionPlan`, `listProjectPlans` (assinaturas da Tarefa 5); `planPosition` pode ser duplicado localmente se `planText.ts` ainda não existir no worktree (a integração remove a duplicata).
- Produces: `PlanProperty.vue` props `{ sessionId: string; projectId: number }`.

- [ ] **Step 1: Escrever os testes**

1. Sem vínculo → "Plano: Nenhum" e botão "Escolher plano…".
2. Com plano → nome e "4 de 12"; com 100% → "Concluído".
3. `path` preenchido e `plan` nulo → "Plano indisponível" com o caminho.
4. "Trocar plano…"/"Escolher plano…" abre a lista de `GET /api/projects/{id}/plans` (título e "3/12"); escolher chama `PUT` com `{path}` e atualiza a propriedade com o `PlanState` devolvido; lista vazia → "Nenhum plano em docs/superpowers/plans/".
5. "Desligar" chama `DELETE` e mostra "Nenhum"; com `link == "off"` aparece "Ligar automaticamente", que chama `PUT` com `{auto: true}`.
6. Erros das rotas aparecem legíveis (`role="alert"`) e os botões reabilitam; a lista abre e fecha por teclado (Esc fecha consumindo o evento com `preventDefault`, pelo contrato de camadas do app).
7. O `PlanState` é buscado de novo quando `session.plan` muda no store (evento `session.updated`).

- [ ] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/plan/__tests__/PlanProperty.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implementar**

`PlanProperty.vue` segue o estilo das outras propriedades do `DetailsPanel.vue` (mesmo rótulo à esquerda, valor à direita, menu de ações como os já existentes no painel). Inclua-o na seção de propriedades do `DetailsPanel.vue`, depois das propriedades existentes.

- [ ] **Step 4: Rodar e ver passar**

Run: `pnpm --dir frontend test` e `pnpm --dir frontend build`
Expected: PASS.

- [ ] **Step 5: Commit (sessão principal)**

`[Feat] Mostrar e trocar o plano no painel Detalhes`

---

### Tarefa 7: Selo na linha de conversa e tarefa no Dashboard (frontend)

**Files:**
- Create: `frontend/src/components/plan/PlanBadge.vue`
- Modify: `frontend/src/components/conversation/ConversationRow.vue`, `frontend/src/components/dashboard/NowCard.vue`
- Modify (se ainda não tiver da Tarefa 5): `frontend/src/types/api.ts`, `frontend/src/components/plan/planText.ts` — mesmo conteúdo da Tarefa 5
- Test: `frontend/src/components/plan/__tests__/PlanBadge.spec.ts`, acréscimos em `components/conversation/__tests__/ConversationRow.spec.ts` e `components/dashboard/__tests__/NowCard.spec.ts` (ou o spec existente do cartão)

**Interfaces:**
- Consumes: `Session.plan`, `planBadge`, `planPosition`, `planVisible`, `planStopped`.
- Produces: `PlanBadge.vue` props `{ session: Session }`.

- [x] **Step 1: Escrever os testes**

1. `PlanBadge`: plano em andamento → texto "4/12", mini barra proporcional, `title` e `aria-label` com "Tarefa 4 de 12: título"; parada → classe de apagado; `planVisible` falso → nada.
2. `ConversationRow`: com plano visível, o selo aparece depois do título em todas as variantes (`inbox`, `list`, `compact`), sem empurrar a coluna de horário (o título continua truncando).
3. `NowCard`: com plano visível, uma linha "Tarefa 4 de 12: título" abaixo do título; sem plano, nada.

- [x] **Step 2: Rodar e ver falhar**

Run: `pnpm --dir frontend exec vitest run src/components/plan src/components/conversation/__tests__/ConversationRow.spec.ts`
Expected: FAIL.

- [x] **Step 3: Implementar**

`PlanBadge.vue`: `<span class="inline-flex shrink-0 items-center gap-1 ...">` com o texto `planBadge` e uma barra de 24 px (fundo neutro, preenchimento primário proporcional a `done/total`; cinza quando parada). Em `ConversationRow.vue`, coloque o selo logo depois do título, dentro do mesmo bloco que trunca, com `shrink-0`. Em `NowCard.vue`, uma linha de texto secundário com `planPosition`.

- [x] **Step 4: Rodar e ver passar**

Run: `pnpm --dir frontend test` e `pnpm --dir frontend build`
Expected: PASS.

- [x] **Step 5: Commit (sessão principal)**

`[Feat] Mostrar posição no plano na linha de conversa e no Dashboard`

---

### Tarefa 8: Regra no CLAUDE.md global e teste manual (sessão principal)

**Files:**
- Modify: `/home/vi/.claude/CLAUDE.md` (arquivo do usuário, aprovado por ele)
- Modify: `ROADMAP.md`

- [ ] **Step 1: Acrescentar a regra**

Na seção "Superpowers" de `/home/vi/.claude/CLAUDE.md`:

```markdown
- Ao concluir uma tarefa de um plano em `docs/superpowers/plans/` (depois da revisão e do commit), marque como feitas todas as caixas (`- [x]`) daquela tarefa no arquivo do plano, no checkout principal. Não marque caixas de tarefas que ainda não foram concluídas.
```

- [ ] **Step 2: Aplicar a regra a este plano durante a execução**

A cada tarefa deste plano aprovada e commitada, marcar as caixas dela neste arquivo (é o primeiro teste real da funcionalidade).

- [ ] **Step 3: Teste manual**

Com o app rodando (o usuário já o mantém em `localhost:6600`), abrir a conversa que executa este plano e conferir: faixa com a tarefa atual, selo na linha, Detalhes. Registrar no roadmap o que foi visto.

- [ ] **Step 4: Commit**

`[Docs] Concluir marco 9 de progresso de planos`
