# Comandos e menções: plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam caixas (`- [ ]`) para acompanhamento.

**Objetivo:** o campo de mensagem (conversa e modal de nova conversa) ganha dois menus de sugestão: `/` lista os comandos e skills da pasta, e `@` lista arquivos e pastas do projeto. Os dois seguem o comportamento da extensão oficial do VS Code.

**Arquitetura:**
- **Backend:** dois serviços novos em memória, `CommandCatalog` (`commands.py`) e `FileIndex` (`filesearch.py`). O catálogo usa um cliente descartável do SDK com `disableAllHooks` e cache de 5 min por pasta. O índice usa `git ls-files` via `run_git` e cache de 30 s. As rotas ficam em `api/suggestions.py` e resolvem a pasta pelo id da sessão ou do projeto; o navegador nunca envia caminho.
- **Frontend:** funções puras em `conversation/suggestions.ts`. O composable `useComposerSuggestions` liga o menu a um `textarea`. A lista é `SuggestionMenu.vue`, e o realce das menções e a dica de argumentos ficam em `MentionMirror.vue`.
- **Histórico:** o comando volta como balão do usuário.
- **Preferências (Tarefa 12, fora da spec):** modelo, raciocínio e modo padrão das conversas novas, aplicados pelo backend ao criar a sessão.

**Stack:** Python 3.13, FastAPI, `claude-agent-sdk` 0.2.161, pytest; Vue 3, TypeScript, Tailwind v4, Vitest, pnpm.

**Spec:** `docs/superpowers/specs/2026-09-30-comandos-e-mencoes-design.md`

## Linha de base

Worktree `.claude/worktrees/pendencias-12-13`, branch `worktree-pendencias-12-13`. Em 2026-09-30, depois do commit 6c65ebb: `uv run pytest -q` deu 1290 passed e `pnpm --dir frontend test` deu 908 passed. Os números de linha citados abaixo são desse ponto; confira com `grep` antes de editar.

## Restrições globais

- Textos da interface, mensagens de erro e documentação em português brasileiro. Código, identificadores, comentários e docstrings em inglês.
- Frontend: só `pnpm`. Rode `pnpm --dir frontend test`, `pnpm --dir frontend exec vitest run <arquivo>` e `pnpm --dir frontend build`. Nunca `npx` nem `yarn`.
- Imports do frontend são relativos (não há alias `@/`). Os tipos de payload ficam em `frontend/src/types/api.ts`.
- Os testes vêm antes do código, e nenhum teste automatizado toca o SDK real. Os testes do backend usam `FakeAgentFactory` e clientes falsos. Os do frontend usam `routeFetch`/`jsonResponse` de `frontend/src/test/factories.ts` com `vi.stubGlobal('fetch', ...)`.
- Todo `git` passa por `run_git` (`backend/vibing/gitinfo.py`), com argumentos em lista.
- As rotas novas ficam atrás das proteções que já existem (`Host`, `Origin`, `X-Vibing: 1`). O navegador não envia caminho: a pasta sai do id.
- `q` tem no máximo 200 caracteres. Id desconhecido dá 404. Pasta sumida dá 409 com `A pasta do projeto não existe mais: <pasta>`. Falha do catálogo ou da busca dá 502 com a mensagem.
- Catálogo: cache de 5 min por pasta resolvida, limite de 10 s para conectar e buscar, `settings='{"disableAllHooks": true}'` e `setting_sources` `None`.
- Busca de arquivos: cache de 30 s, no máximo 100 arquivos por busca, varredura com teto de 20 000 arquivos, e as exclusões `node_modules`, `.git`, `dist`, `build`, `.next`, `.nuxt`, `.DS_Store`, `Thumbs.db`, `*.log`, `.env`, `.env.*`, `yarn-error.log` e `npm-debug.log*`.
- Menu `@`: espera 200 ms. Menu `/`: a lista é buscada uma vez por fonte.
- Não usar a marca "Claude Code" na interface. Não configurar nem pedir `ANTHROPIC_API_KEY`.
- Subagentes não fazem commit nem `git add`. O passo "Commit" de cada tarefa é da sessão principal, depois de o `reviewer` aprovar e os testes passarem. A mesma sessão marca o item do `ROADMAP.md` com `[x]` e a data e atualiza a contagem.
- Mensagem de commit: `[Tipo] Título` em português, verbo no infinitivo, até 72 caracteres, sem ponto final.

## Desvio da spec, decidido neste plano

A spec prevê `git ls-files` só quando a pasta é um repositório e varredura fora do git. Mas um projeto do app pode ser uma pasta com **vários repositórios** dentro. Nesse caso, a varredura entraria em tudo o que o `.gitignore` de cada repositório exclui (`.venv`, `target`, caches) e gastaria o teto de 20 000 arquivos. Regra adotada:

- A pasta é um repositório (tem `.git`): `git ls-files` nela, como na spec.
- A pasta não é repositório: `git ls-files` em cada repositório encontrado por `gitinfo.discover`, com o prefixo relativo. A varredura cobre só o resto da pasta e não entra nesses repositórios.
- Falha de git num repositório interno é registrada no log e esse repositório fica de fora. Falha na pasta principal vira `FileSearchError`.

## Pontos de atenção na revisão

1. **Resposta atrasada:** digitar `@a`, `@ab` e `@abc` depressa não pode deixar na tela a resposta de `@ab` que chegou por último. Coberto na Tarefa 6, "resposta velha descartada".
2. **Esc no modal:** fecha só o menu, não o modal. O mesmo vale para Enter com menu aberto, que não envia nem cria a conversa. Coberto na Tarefa 8, "Esc fecha só o menu".
3. **Projeto com vários repositórios e pastas pesadas ignoradas** (`.venv` fora do `.gitignore` de um repositório interno): a busca não pode ficar vazia nem lenta. Coberto na Tarefa 3, "pasta com vários repositórios".
4. **Ditado:** o texto ditado não pode abrir o menu, e um menu aberto fecha quando o ditado começa. Coberto na Tarefa 7, "ditado não abre menu".
5. **Comando embutido do CLI no histórico** (`/model`, `/clear` digitados no terminal): vira balão `/model`, e a saída local (`<local-command-stdout>`) continua como aviso. O agente de resumos passa a ver `[Você] /model`. Coberto na Tarefa 10.

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `backend/vibing/agent/base.py` | `AgentOptions.settings` |
| `backend/vibing/agent/sdk_client.py` | Repassa `settings` a `ClaudeAgentOptions` |
| `backend/vibing/sessions.py` | `SessionManager.agent_factory` e `SessionManager.find_record` |
| `backend/vibing/commands.py` (novo) | `CommandInfo`, `CommandCatalog`, `CommandCatalogError`, `parse_commands` |
| `backend/vibing/filesearch.py` (novo) | `FileMatch`, `FileIndex`, `FileSearchError`, `match_files`, `is_excluded` |
| `backend/vibing/api/suggestions.py` (novo) | Rotas `/commands` e `/files` de sessão e projeto |
| `backend/vibing/api/__init__.py` | Registra o router novo |
| `backend/vibing/app.py` | Cria `app.state.commands` e `app.state.files` no `lifespan` |
| `backend/vibing/conversation.py` | `_classify_user_text`: comando vira texto do usuário |
| `frontend/src/types/api.ts` | `CommandInfo`, `FileMatch`, `SuggestionScope` |
| `frontend/src/api/http.ts` | `listCommands(scope)`, `searchFiles(scope, q)` |
| `frontend/src/conversation/suggestions.ts` (novo) | Funções puras |
| `frontend/src/conversation/useComposerSuggestions.ts` (novo) | Composable |
| `frontend/src/components/conversation/SuggestionMenu.vue` (novo) | Lista |
| `frontend/src/components/conversation/MentionMirror.vue` (novo) | Camada espelhada |
| `frontend/src/components/conversation/MessageComposer.vue` | Integração no campo da conversa |
| `frontend/src/components/NewConversationModal.vue` | Integração no modal |
| `scripts/commands_smoke.py` (novo) | Teste manual do catálogo contra o SDK real |
| `backend/vibing/api/app_state.py` | Validação dos padrões de conversa nova (Tarefa 12) |
| `frontend/src/components/preferences/GeneralPreferences.vue` | Padrões de modelo, raciocínio e modo (Tarefa 12) |

---

### Tarefa 1: `settings` em `AgentOptions` e no cliente do SDK

Item 1 do marco 13 no `ROADMAP.md`.

**Arquivos:**
- Modificar: `backend/vibing/agent/base.py` (dataclass `AgentOptions`, por volta da L44)
- Modificar: `backend/vibing/agent/sdk_client.py` (`build_sdk_options`, por volta da L70-97)
- Teste: `backend/tests/test_agent_sdk_client.py`

**Interfaces:**
- Produz: `AgentOptions.settings: str | None = None`. Quando não é `None`, `build_sdk_options` passa `settings=<valor>` ao `ClaudeAgentOptions`. O `FakeAgentClient` já guarda `options` inteiro, então os testes leem `client.options.settings`.

- [x] **Passo 1: escrever os testes que falham.** Em `backend/tests/test_agent_sdk_client.py`, junto de `test_build_options_passes_empty_setting_sources`:

```python
def test_build_options_does_not_set_settings_by_default(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))
    assert sdk.settings == ClaudeAgentOptions().settings


def test_build_options_passes_settings_json(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, settings='{"disableAllHooks": true}'))
    assert sdk.settings == '{"disableAllHooks": true}'
```

- [x] **Passo 2: rodar e ver falhar.** Rode `uv run pytest backend/tests/test_agent_sdk_client.py -q -k settings`. Esperado: `TypeError: AgentOptions.__init__() got an unexpected keyword argument 'settings'`.

- [x] **Passo 3: implementar.** Em `AgentOptions`, depois de `setting_sources`:

```python
    # JSON with settings that override the loaded ones (e.g. '{"disableAllHooks": true}'
    # for throwaway clients that must not run hooks). None: nothing extra.
    settings: str | None = None
```

Em `build_sdk_options`, depois do bloco de `setting_sources`:

```python
    if options.settings is not None:
        kwargs["settings"] = options.settings
```

- [x] **Passo 4: rodar e ver passar.** Rode `uv run pytest backend/tests/test_agent_sdk_client.py -q` e depois `uv run pytest -q`. Esperado: tudo PASS.

- [x] **Passo 5: commit** (sessão principal, depois da aprovação do `reviewer`). Marque o item 1 do marco 13 no roadmap.

```bash
git add backend/vibing/agent/base.py backend/vibing/agent/sdk_client.py backend/tests/test_agent_sdk_client.py ROADMAP.md
git commit -m "[Feat] Repassar settings do app ao cliente do SDK"
```

---

### Tarefa 2: catálogo de comandos e rotas `/commands`

Item 2 do marco 13.

**Arquivos:**
- Criar: `backend/vibing/commands.py`
- Criar: `backend/vibing/api/suggestions.py`
- Modificar: `backend/vibing/api/__init__.py` (importar e registrar `suggestions.router`)
- Modificar: `backend/vibing/sessions.py` (`SessionManager`: propriedade `agent_factory` e método `find_record`, perto de `get`, L2181)
- Modificar: `backend/vibing/app.py` (`lifespan`, logo depois de `app.state.sessions = SessionManager(...)`)
- Teste: `backend/tests/test_commands.py` (novo), `backend/tests/test_suggestions_api.py` (novo)

**Interfaces:**
- Consome: `AgentOptions.settings` (Tarefa 1) e `AgentFactory` (`vibing.agent.base`).
- Produz:
  - `vibing.commands`:
    - `CommandInfo(name: str, description: str, argument_hint: str)`, dataclass congelada
    - `CommandCatalogError(Exception)`
    - `parse_commands(raw: Any) -> list[CommandInfo]`
    - `CommandCatalog(agent_factory, clock=time.monotonic, timeout=10.0)` com `async list(folder: Path) -> list[CommandInfo]`
    - `NO_HOOKS = '{"disableAllHooks": true}'`
  - `SessionManager.agent_factory` (propriedade) e `SessionManager.find_record(session_id: str) -> SessionRecord`, que levanta `SessionNotFoundError` e não cria sessão em memória.
  - `vibing.api.suggestions.router` com `GET /api/sessions/{id}/commands` e `GET /api/projects/{id}/commands`, que devolvem `[{name, description, argument_hint}]`.
  - `app.state.commands: CommandCatalog`.

- [x] **Passo 1: escrever os testes do catálogo** em `backend/tests/test_commands.py`:

```python
"""Slash command catalog: throwaway client, filtering, cache, errors."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from vibing.agent.base import AgentError, AgentOptions
from vibing.agent.fake import FakeAgentFactory
from vibing.commands import (
    NO_HOOKS,
    CommandCatalog,
    CommandCatalogError,
    CommandInfo,
    parse_commands,
)

RAW = [
    {"name": "commit", "description": "Cria um commit", "argumentHint": ""},
    {"name": "hello", "description": "Diz olá (project)", "argumentHint": "<nome>"},
    {"name": "superpowers:brainstorming", "description": "Explora ideias"},
    {"name": "clear", "description": "Limpa", "builtin": True},
    {"name": "__internal", "description": "x"},
    {"description": "sem nome"},
    "lixo",
]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_parse_drops_builtins_internal_and_nameless_and_strips_project_suffix():
    assert parse_commands(RAW) == [
        CommandInfo("commit", "Cria um commit", ""),
        CommandInfo("hello", "Diz olá", "<nome>"),
        CommandInfo("superpowers:brainstorming", "Explora ideias", ""),
    ]


def test_parse_accepts_missing_or_invalid_list():
    assert parse_commands(None) == []
    assert parse_commands({"x": 1}) == []


@pytest.mark.anyio
async def test_list_uses_a_throwaway_client_without_hooks_in_the_folder(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    catalog = CommandCatalog(factory)
    commands = await catalog.list(tmp_path)
    assert [c.name for c in commands] == ["commit", "hello", "superpowers:brainstorming"]
    [client] = factory.clients
    options: AgentOptions = client.options
    assert options.cwd == tmp_path.resolve()
    assert options.resume is False
    assert options.settings == NO_HOOKS
    assert json.loads(NO_HOOKS) == {"disableAllHooks": True}
    assert options.setting_sources is None
    assert client.connected and client.closed


@pytest.mark.anyio
async def test_cache_lasts_five_minutes_per_folder(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    clock = Clock()
    catalog = CommandCatalog(factory, clock=clock)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    await catalog.list(a)
    await catalog.list(a)
    assert len(factory.clients) == 1
    await catalog.list(b)
    assert len(factory.clients) == 2
    clock.now += 5 * 60 - 1
    await catalog.list(a)
    assert len(factory.clients) == 2
    clock.now += 1
    await catalog.list(a)
    assert len(factory.clients) == 3


class _GatedClient:
    """Fake client whose get_server_info waits for a gate."""

    def __init__(self, options: AgentOptions, gate: asyncio.Event, hang: bool = False) -> None:
        self.options = options
        self.gate = gate
        self.hang = hang
        self.closed = False

    async def connect(self) -> None:
        return None

    async def get_server_info(self) -> dict[str, Any] | None:
        if self.hang:
            await asyncio.Event().wait()
        await self.gate.wait()
        return {"commands": RAW}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_two_simultaneous_requests_open_one_client(tmp_path: Path):
    gate = asyncio.Event()
    clients: list[_GatedClient] = []

    def factory(options: AgentOptions) -> _GatedClient:
        client = _GatedClient(options, gate)
        clients.append(client)
        return client

    catalog = CommandCatalog(factory)  # type: ignore[arg-type]
    first = asyncio.create_task(catalog.list(tmp_path))
    second = asyncio.create_task(catalog.list(tmp_path))
    await asyncio.sleep(0)
    gate.set()
    assert (await first) == (await second)
    assert len(clients) == 1


@pytest.mark.anyio
async def test_timeout_raises_and_is_not_cached_and_closes(tmp_path: Path):
    clients: list[_GatedClient] = []

    def factory(options: AgentOptions) -> _GatedClient:
        client = _GatedClient(options, asyncio.Event(), hang=not clients)
        clients.append(client)
        if not client.hang:
            client.gate.set()
        return client

    catalog = CommandCatalog(factory, timeout=0.05)  # type: ignore[arg-type]
    with pytest.raises(CommandCatalogError, match="demorou demais"):
        await catalog.list(tmp_path)
    assert clients[0].closed
    assert [c.name for c in await catalog.list(tmp_path)][0] == "commit"
    assert len(clients) == 2


@pytest.mark.anyio
async def test_connect_failure_raises_with_the_agent_message_and_closes(tmp_path: Path):
    factory = FakeAgentFactory(connect_error=AgentError("CLI não encontrado."))
    catalog = CommandCatalog(factory)
    with pytest.raises(CommandCatalogError, match="CLI não encontrado."):
        await catalog.list(tmp_path)
    assert factory.clients[0].closed
    # Failures are not cached.
    with pytest.raises(CommandCatalogError):
        await catalog.list(tmp_path)
    assert len(factory.clients) == 2
```

Antes de escrever o último teste, confira que `FakeAgentClient.close()` marca `closed = True` mesmo sem `connect()` bem-sucedido. Se não marcar, use no teste um cliente próprio no estilo de `_GatedClient`, em vez de mudar o fake.

- [x] **Passo 2: escrever os testes das rotas** em `backend/tests/test_suggestions_api.py`. Siga o estilo de `test_sessions_api.py`: `create_app(agent_factory=factory, history_exists=...)` e `TestClient` com `origin` e `x-vibing`.

```python
"""Suggestion routes: commands and files of a session or project."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vibing.agent.base import AgentError
from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
MISSING = "00000000-0000-0000-0000-000000000000"
RAW = [
    {"name": "hello", "description": "Diz olá (project)", "argumentHint": "<nome>"},
    {"name": "clear", "description": "Limpa", "builtin": True},
]


def make_api(factory: FakeAgentFactory):
    app = create_app(agent_factory=factory, history_exists=lambda sid, cwd: False)
    return TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"})


@pytest.fixture
def factory() -> FakeAgentFactory:
    return FakeAgentFactory(server_info={"commands": RAW})


@pytest.fixture
def api(factory: FakeAgentFactory):
    with make_api(factory) as client:
        yield client


def make_project(api: TestClient, home: Path, name: str = "app") -> dict[str, Any]:
    folder = home / name
    folder.mkdir()
    response = api.post("/api/projects", json={"name": name, "path": str(folder), "color": "#ff8800"})
    assert response.status_code == 201
    return response.json()


def new_session(api: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    response = api.post(f"/api/projects/{project['id']}/sessions")
    assert response.status_code == 201
    return response.json()


EXPECTED = [{"name": "hello", "description": "Diz olá", "argument_hint": "<nome>"}]


def test_project_commands(api, home, factory):
    project = make_project(api, home)
    response = api.get(f"/api/projects/{project['id']}/commands")
    assert response.status_code == 200
    assert response.json() == EXPECTED
    assert factory.clients[-1].options.cwd == Path(project["path"]).resolve()


def test_session_commands_use_the_session_folder_without_opening_it(api, home, factory):
    project = make_project(api, home)
    session = new_session(api, project)
    before = len(factory.clients)
    response = api.get(f"/api/sessions/{session['session_id']}/commands")
    assert response.status_code == 200
    assert response.json() == EXPECTED
    # Only the throwaway catalog client was created, not a session client.
    assert len(factory.clients) == before + 1
    assert factory.clients[-1].options.session_id != session["session_id"]


def test_unknown_ids_are_404(api):
    assert api.get(f"/api/sessions/{MISSING}/commands").status_code == 404
    assert api.get("/api/projects/9999/commands").status_code == 404


def test_missing_folder_is_409(api, home):
    project = make_project(api, home)
    shutil.rmtree(project["path"])
    response = api.get(f"/api/projects/{project['id']}/commands")
    assert response.status_code == 409
    assert response.json()["detail"] == f"A pasta do projeto não existe mais: {project['path']}"


def test_catalog_failure_is_502_with_the_message(home):
    factory = FakeAgentFactory(connect_error=AgentError("CLI não encontrado."))
    with make_api(factory) as api:
        project = make_project(api, home)
        response = api.get(f"/api/projects/{project['id']}/commands")
    assert response.status_code == 502
    assert response.json()["detail"] == "CLI não encontrado."


def test_requests_without_the_app_header_are_refused(api, home):
    project = make_project(api, home)
    response = api.get(
        f"/api/projects/{project['id']}/commands", headers={"x-vibing": ""}
    )
    assert response.status_code == 403
```

Confira como `HostOriginMiddleware` trata o cabeçalho vazio. Se `headers={"x-vibing": ""}` não bastar para removê-lo, use um `TestClient` criado sem `x-vibing`, no mesmo `app`.

- [x] **Passo 3: rodar e ver falhar.** Rode `uv run pytest backend/tests/test_commands.py backend/tests/test_suggestions_api.py -q`. Esperado: `ModuleNotFoundError: No module named 'vibing.commands'` e 404 nas rotas.

- [x] **Passo 4: implementar `backend/vibing/commands.py`:**

```python
"""Slash commands available in a folder: user, project and plugin commands and
skills, read from the CLI with a throwaway client that runs no hooks.

Built-in CLI commands are left out: the app has its own controls for them.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import PermissionResultDeny

from vibing.agent.base import AgentClient, AgentError, AgentFactory, AgentOptions

logger = logging.getLogger(__name__)

CACHE_SECONDS = 5 * 60
TIMEOUT_SECONDS = 10.0
# Connecting fires SessionStart hooks; this keeps the list and runs none.
NO_HOOKS = '{"disableAllHooks": true}'
_PROJECT_SUFFIX = " (project)"


class CommandCatalogError(Exception):
    """Failure with a message ready to show (pt-BR)."""


@dataclass(frozen=True)
class CommandInfo:
    name: str
    description: str
    argument_hint: str


async def _deny_all(tool_name: str, tool_input: dict[str, Any], context: Any) -> PermissionResultDeny:
    return PermissionResultDeny(message="Cliente só para listar comandos.")


def parse_commands(raw: Any) -> list[CommandInfo]:
    """`get_server_info()["commands"]` without built-ins, internal names and nameless
    entries, with the " (project)" suffix removed, sorted by name."""
    found: list[CommandInfo] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or entry.get("builtin") is True:
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name or name.startswith("__"):
            continue
        description = entry.get("description")
        description = description if isinstance(description, str) else ""
        if description.endswith(_PROJECT_SUFFIX):
            description = description[: -len(_PROJECT_SUFFIX)]
        hint = entry.get("argumentHint")
        found.append(CommandInfo(name, description, hint if isinstance(hint, str) else ""))
    found.sort(key=lambda command: command.name)
    return found


class CommandCatalog:
    """Commands per folder, cached for `CACHE_SECONDS`. Concurrent requests for the
    same folder share one client. Failures are not cached."""

    def __init__(
        self,
        agent_factory: AgentFactory,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._factory = agent_factory
        self._clock = clock
        self._timeout = timeout
        self._cache: dict[Path, tuple[float, list[CommandInfo]]] = {}
        self._locks: dict[Path, asyncio.Lock] = {}

    async def list(self, folder: Path) -> list[CommandInfo]:
        key = folder.resolve()
        cached = self._fresh(key)
        if cached is not None:
            return cached
        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = self._fresh(key)
            if cached is not None:
                return cached
            commands = await self._fetch(key)
            self._cache[key] = (self._clock(), commands)
            return commands

    def _fresh(self, key: Path) -> list[CommandInfo] | None:
        entry = self._cache.get(key)
        if entry is None or self._clock() - entry[0] >= CACHE_SECONDS:
            return None
        return entry[1]

    async def _fetch(self, folder: Path) -> list[CommandInfo]:
        client: AgentClient | None = None
        try:
            client = self._factory(
                AgentOptions(
                    cwd=folder,
                    session_id=str(uuid.uuid4()),
                    resume=False,
                    can_use_tool=_deny_all,
                    settings=NO_HOOKS,
                )
            )
            info = await asyncio.wait_for(self._read(client), self._timeout)
        except TimeoutError as exc:
            raise CommandCatalogError("A lista de comandos demorou demais. Tente de novo.") from exc
        except AgentError as exc:
            raise CommandCatalogError(exc.message_pt) from exc
        except Exception as exc:
            logger.exception("Falha ao listar os comandos de %s", folder)
            raise CommandCatalogError("Não foi possível carregar os comandos.") from exc
        finally:
            if client is not None:
                with suppress(Exception):
                    await client.close()
        return parse_commands((info or {}).get("commands"))

    @staticmethod
    async def _read(client: AgentClient) -> dict[str, Any] | None:
        await client.connect()
        return await client.get_server_info()
```

- [x] **Passo 5: `SessionManager`.** Em `backend/vibing/sessions.py`, antes de `def get(`:

```python
    @property
    def agent_factory(self) -> AgentFactory:
        """The factory sessions use; throwaway clients (command catalog) share it."""
        return self._agent_factory

    def find_record(self, session_id: str) -> SessionRecord:
        """The session's record, from memory or the database, without loading the
        session into memory."""
        session = self._sessions.get(session_id)
        if session is not None:
            return session.record
        row = self._read_row(session_id)
        if row is None:
            raise SessionNotFoundError("Sessão não encontrada.")
        return _record(row)
```

Confira se `AgentFactory` já está importado em `sessions.py`; se não estiver, importe de `vibing.agent.base`. `_read_row` já existe (por volta da L2900).

- [x] **Passo 6: rotas** em `backend/vibing/api/suggestions.py`:

```python
"""Suggestion routes for the message field: slash commands and files of the folder a
session or project works in. The browser never sends a path: it comes from the id."""

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from vibing import projects, sessions
from vibing.api.deps import DbDep
from vibing.api.sessions import ManagerDep
from vibing.commands import CommandCatalogError

router = APIRouter(prefix="/api")


def _existing(folder: Path) -> Path:
    if not folder.is_dir():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A pasta do projeto não existe mais: {folder}",
        )
    return folder


def session_folder(manager: sessions.SessionManager, session_id: str) -> Path:
    try:
        record = manager.find_record(session_id)
    except sessions.SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _existing(Path(record.work_dir()))


def project_folder(conn: Any, project_id: int) -> Path:
    try:
        project = projects.get_project(conn, project_id)
    except projects.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _existing(Path(project.path))


async def _commands(request: Request, folder: Path) -> list[dict[str, str]]:
    try:
        found = await request.app.state.commands.list(folder)
    except CommandCatalogError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [
        {"name": c.name, "description": c.description, "argument_hint": c.argument_hint}
        for c in found
    ]


@router.get("/sessions/{session_id}/commands")
async def session_commands(
    session_id: str, request: Request, manager: ManagerDep
) -> list[dict[str, str]]:
    return await _commands(request, session_folder(manager, session_id))


@router.get("/projects/{project_id}/commands")
async def project_commands(project_id: int, request: Request, conn: DbDep) -> list[dict[str, str]]:
    return await _commands(request, project_folder(conn, project_id))
```

Registre o router em `backend/vibing/api/__init__.py` (import `suggestions` e `router.include_router(suggestions.router)`, antes de `ws.router`). No `lifespan` de `app.py`, logo depois de criar `app.state.sessions`:

```python
        app.state.commands = CommandCatalog(app.state.sessions.agent_factory)
```

Import: `from vibing.commands import CommandCatalog`.

- [x] **Passo 7: rodar e ver passar.** Rode `uv run pytest backend/tests/test_commands.py backend/tests/test_suggestions_api.py -q` e depois `uv run pytest -q`. Esperado: tudo PASS.

- [x] **Passo 8: commit** (sessão principal, depois do `reviewer`). Marque o item 2 no roadmap.

```bash
git add backend/vibing/commands.py backend/vibing/api/suggestions.py backend/vibing/api/__init__.py backend/vibing/sessions.py backend/vibing/app.py backend/tests/test_commands.py backend/tests/test_suggestions_api.py ROADMAP.md
git commit -m "[Feat] Listar comandos da pasta da sessão ou do projeto"
```

---

### Tarefa 3: busca de arquivos e rotas `/files`

Item 3 do marco 13.

**Arquivos:**
- Criar: `backend/vibing/filesearch.py`
- Modificar: `backend/vibing/api/suggestions.py` (rotas `/files`)
- Modificar: `backend/vibing/app.py` (`app.state.files = FileIndex()`)
- Teste: `backend/tests/test_filesearch.py` (novo), `backend/tests/test_suggestions_api.py` (acrescentar)

**Interfaces:**
- Consome: `run_git`, `GitError` e `discover` de `vibing.gitinfo`, e `session_folder`/`project_folder` de `api/suggestions.py` (Tarefa 2).
- Produz:
  - `vibing.filesearch`:
    - `FileMatch(path: str, name: str, type: Literal["file", "directory"])`, dataclass congelada. Pastas têm `path` com `/` no fim e `name` sem a barra.
    - `FileSearchError(Exception)`
    - `is_excluded(rel: str) -> bool`
    - `match_files(paths: list[str], query: str) -> list[FileMatch]`
    - `FileIndex(clock=time.monotonic)` com `async search(folder: Path, query: str) -> list[FileMatch]`
    - Constantes `LIST_SECONDS = 30.0`, `WALK_LIMIT = 20_000`, `RESULT_LIMIT = 100`
  - Rotas `GET /api/sessions/{id}/files?q=` e `GET /api/projects/{id}/files?q=`, que devolvem `[{path, name, type}]`.
  - `app.state.files: FileIndex`.

- [x] **Passo 1: escrever os testes** em `backend/tests/test_filesearch.py`:

```python
"""File suggestions for @ mentions."""

from pathlib import Path

import pytest

from git_helpers import git, make_repo
from vibing.filesearch import FileIndex, FileMatch, is_excluded, match_files


def touch(root: Path, *paths: str) -> None:
    for rel in paths:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("rel", [
    "node_modules/a.js", "src/.git/x", "dist/a.js", "a/build/b.js", ".next/x", ".nuxt/x",
    ".DS_Store", "a/Thumbs.db", "debug.log", ".env", "a/.env.local", "yarn-error.log",
    "npm-debug.log.1",
])
def test_fixed_exclusions(rel):
    assert is_excluded(rel)


@pytest.mark.parametrize("rel", ["src/build.py", "envs/a.py", "logs/a.txt", "a/.envrc"])
def test_not_excluded(rel):
    assert not is_excluded(rel)


PATHS = sorted([
    "backend/vibing/fs.py",
    "backend/vibing/api/fs.py",
    "backend/vibing/FsHelper.py",
    "frontend/src/App.vue",
    "README.md",
])


def test_term_without_slash_matches_the_file_name_ignoring_case():
    result = match_files(PATHS, "fs")
    files = [m.path for m in result if m.type == "file"]
    assert files == ["backend/vibing/FsHelper.py", "backend/vibing/api/fs.py", "backend/vibing/fs.py"]


def test_term_with_slash_matches_across_one_folder_boundary():
    result = match_files(PATHS, "api/fs")
    assert [m.path for m in result if m.type == "file"] == ["backend/vibing/api/fs.py"]
    assert match_files(PATHS, "backend/fs") == []  # `*` does not cross `/`


def test_folders_of_the_matches_whose_path_contains_the_term_end_with_slash():
    result = match_files(PATHS, "vibing")
    assert FileMatch("backend/vibing/", "vibing", "directory") in result
    assert all(m.type == "directory" for m in result)  # no file name contains "vibing"


def test_everything_is_sorted_by_path():
    result = match_files(PATHS, "fs")
    assert [m.path for m in result] == sorted(m.path for m in result)


def test_empty_term_lists_the_first_files_and_their_folders():
    many = [f"f{i:03}.txt" for i in range(150)]
    result = match_files(many, "")
    assert len(result) == 100
    assert result[0].path == "f000.txt" and result[-1].path == "f099.txt"


def test_at_most_100_files():
    many = [f"a{i:03}.py" for i in range(150)]
    assert len(match_files(many, "a")) == 100


@pytest.mark.anyio
async def test_git_repo_lists_tracked_and_untracked_not_ignored(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("segredo.txt\n.venv/\n")
    touch(repo, "novo.py", "segredo.txt", ".venv/lib/x.py", "node_modules/y.js", "app.log")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore")
    result = await FileIndex().search(repo, "")
    paths = [m.path for m in result if m.type == "file"]
    assert "novo.py" in paths and "README.md" in paths and ".gitignore" in paths
    assert "segredo.txt" not in paths
    assert not any(p.startswith((".venv/", "node_modules/")) or p.endswith(".log") for p in paths)


@pytest.mark.anyio
async def test_folder_without_git_is_walked_with_exclusions(tmp_path: Path):
    touch(tmp_path, "a/b.py", "node_modules/x.js", "dist/y.js", ".env")
    result = await FileIndex().search(tmp_path, "")
    assert [m.path for m in result] == ["a/", "a/b.py"]


@pytest.mark.anyio
async def test_walk_stops_at_the_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("vibing.filesearch.WALK_LIMIT", 5)
    touch(tmp_path, *[f"f{i}.txt" for i in range(20)])
    result = await FileIndex().search(tmp_path, "")
    assert len(result) == 5


@pytest.mark.anyio
async def test_folder_with_several_repositories_uses_git_in_each(tmp_path: Path):
    front = make_repo(tmp_path / "front")
    back = make_repo(tmp_path / "back")
    (back / ".gitignore").write_text(".venv/\n")
    touch(back, ".venv/lib/pesado.py", "api.py")
    touch(tmp_path, "notas.md")
    result = await FileIndex().search(tmp_path, "")
    paths = [m.path for m in result if m.type == "file"]
    assert "front/README.md" in paths and "back/api.py" in paths and "notas.md" in paths
    assert not any(".venv" in p for p in paths)
    assert not any(p.startswith(("front/.git/", "back/.git/")) for p in paths)
    assert front and back


@pytest.mark.anyio
async def test_listing_is_cached_for_30_seconds(tmp_path: Path):
    clock = Clock()
    index = FileIndex(clock=clock)
    touch(tmp_path, "a.py")
    assert [m.path for m in await index.search(tmp_path, "")] == ["a.py"]
    touch(tmp_path, "b.py")
    clock.now = 29.9
    assert [m.path for m in await index.search(tmp_path, "")] == ["a.py"]
    clock.now = 30.0
    assert [m.path for m in await index.search(tmp_path, "")] == ["a.py", "b.py"]
```

Em `test_suggestions_api.py`, acrescente:

```python
def test_project_files(api, home):
    project = make_project(api, home)
    (Path(project["path"]) / "backend").mkdir()
    (Path(project["path"]) / "backend" / "fs.py").write_text("x")
    response = api.get(f"/api/projects/{project['id']}/files", params={"q": "fs"})
    assert response.status_code == 200
    assert response.json() == [{"path": "backend/fs.py", "name": "fs.py", "type": "file"}]


def test_session_files(api, home):
    project = make_project(api, home)
    (Path(project["path"]) / "a.py").write_text("x")
    session = new_session(api, project)
    response = api.get(f"/api/sessions/{session['session_id']}/files", params={"q": ""})
    assert response.status_code == 200
    assert [m["path"] for m in response.json()] == ["a.py"]


def test_files_query_longer_than_200_is_refused(api, home):
    project = make_project(api, home)
    response = api.get(f"/api/projects/{project['id']}/files", params={"q": "x" * 201})
    assert response.status_code == 422


def test_files_unknown_ids_and_missing_folder(api, home):
    assert api.get(f"/api/sessions/{MISSING}/files").status_code == 404
    project = make_project(api, home)
    shutil.rmtree(project["path"])
    assert api.get(f"/api/projects/{project['id']}/files").status_code == 409


def test_files_search_failure_is_502(api, home, monkeypatch):
    from vibing.filesearch import FileSearchError

    async def boom(self, folder, query):
        raise FileSearchError("Falha ao listar os arquivos: x")

    monkeypatch.setattr("vibing.filesearch.FileIndex.search", boom)
    project = make_project(api, home)
    response = api.get(f"/api/projects/{project['id']}/files")
    assert response.status_code == 502
    assert response.json()["detail"] == "Falha ao listar os arquivos: x"
```

- [x] **Passo 2: rodar e ver falhar.** Rode `uv run pytest backend/tests/test_filesearch.py backend/tests/test_suggestions_api.py -q`. Esperado: `ModuleNotFoundError: No module named 'vibing.filesearch'`.

- [x] **Passo 3: implementar `backend/vibing/filesearch.py`:**

```python
"""File and folder suggestions for `@` mentions, like the VS Code extension:
the file name (or, with `/` in the term, the path) contains the term, at most
`RESULT_LIMIT` files, plus the folders of those files whose path contains it.

The listing comes from `git ls-files` (tracked plus untracked not ignored). A folder
that is not a repository lists each repository inside it with git and walks the rest,
so ignored heavy folders (`.venv`, caches) never fill the walk limit.
"""

import asyncio
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from vibing.gitinfo import GitError, discover, run_git

logger = logging.getLogger(__name__)

LIST_SECONDS = 30.0
WALK_LIMIT = 20_000
RESULT_LIMIT = 100
GIT_LIST_TIMEOUT = 10.0
EXCLUDED_DIRS = frozenset({"node_modules", ".git", "dist", "build", ".next", ".nuxt"})
EXCLUDED_NAMES = frozenset({".DS_Store", "Thumbs.db", ".env", "yarn-error.log"})


class FileSearchError(Exception):
    """Failure with a message ready to show (pt-BR)."""


@dataclass(frozen=True)
class FileMatch:
    path: str
    name: str
    type: Literal["file", "directory"]


def is_excluded(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return True
    name = parts[-1]
    return (
        name in EXCLUDED_NAMES
        or name.endswith(".log")
        or name.startswith(".env.")
        or name.startswith("npm-debug.log")
    )


def match_files(paths: list[str], query: str) -> list[FileMatch]:
    """`paths` sorted. Same rule as the extension's `**/*<term>*` glob, ignoring case:
    the match starts at a folder boundary and the `*` never crosses `/`."""
    term = query.lower()
    pattern = re.compile(r"(?:^|/)[^/]*" + re.escape(term) + r"[^/]*$", re.IGNORECASE)
    files = [p for p in paths if pattern.search(p)][:RESULT_LIMIT]
    folders: set[str] = set()
    for path in files:
        parts = path.split("/")[:-1]
        for end in range(1, len(parts) + 1):
            folder = "/".join(parts[:end])
            if term in folder.lower():
                folders.add(folder)
    found = [FileMatch(p, p.rsplit("/", 1)[-1], "file") for p in files]
    found += [FileMatch(f + "/", f.rsplit("/", 1)[-1], "directory") for f in folders]
    found.sort(key=lambda m: m.path)
    return found


async def _ls_files(repo: Path, prefix: str) -> list[str]:
    try:
        code, out, err = await run_git(
            repo, "ls-files", "-co", "--exclude-standard", "-z", timeout=GIT_LIST_TIMEOUT
        )
    except GitError as exc:
        raise FileSearchError(f"Falha ao listar os arquivos: {exc}") from exc
    if code != 0:
        raise FileSearchError(f"Falha ao listar os arquivos: {err.strip() or code}")
    return [prefix + p for p in out.split("\0") if p]


def _walk(folder: Path, skip: set[Path]) -> list[str]:
    found: list[str] = []
    for root, dirs, names in os.walk(folder):  # does not follow links
        base = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and base / d not in skip)
        for name in sorted(names):
            rel = (base / name).relative_to(folder).as_posix()
            if is_excluded(rel):
                continue
            found.append(rel)
            if len(found) >= WALK_LIMIT:
                return found
    return found


async def _list(folder: Path) -> list[str]:
    if (folder / ".git").exists():
        paths = await _ls_files(folder, "")
    else:
        repos = [r for r in await asyncio.to_thread(discover, folder) if r != folder]
        paths = []
        for repo in repos:
            prefix = repo.relative_to(folder).as_posix() + "/"
            try:
                paths += await _ls_files(repo, prefix)
            except FileSearchError:
                logger.warning("Repositório %s ficou fora da busca de arquivos", repo, exc_info=True)
        paths += await asyncio.to_thread(_walk, folder, set(repos))
    return sorted({p for p in paths if not is_excluded(p)})


class FileIndex:
    """Listing per folder, cached for `LIST_SECONDS`; the search runs on it."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lists: dict[Path, tuple[float, list[str]]] = {}
        self._locks: dict[Path, asyncio.Lock] = {}

    async def search(self, folder: Path, query: str) -> list[FileMatch]:
        paths = await self._listing(folder.resolve())
        return match_files(paths, query)

    async def _listing(self, key: Path) -> list[str]:
        async with self._locks.setdefault(key, asyncio.Lock()):
            entry = self._lists.get(key)
            if entry is not None and self._clock() - entry[0] < LIST_SECONDS:
                return entry[1]
            paths = await _list(key)
            self._lists[key] = (self._clock(), paths)
            return paths
```

Confira que `discover(folder)` devolve caminhos de mesma forma que `folder / nome` para a comparação em `skip` funcionar. Se `discover` resolver os caminhos de outra maneira, normalize os dois lados com `.resolve()`. Confira também que `WALK_LIMIT` é lido em tempo de execução (o teste troca o valor com `monkeypatch`). É, porque `_walk` usa o nome global.

- [x] **Passo 4: rotas.** Em `api/suggestions.py`:

```python
from vibing.filesearch import FileSearchError

Q = Annotated[str, Query(max_length=200)]


async def _files(request: Request, folder: Path, q: str) -> list[dict[str, str]]:
    try:
        found = await request.app.state.files.search(folder, q)
    except FileSearchError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [{"path": m.path, "name": m.name, "type": m.type} for m in found]


@router.get("/sessions/{session_id}/files")
async def session_files(
    session_id: str, request: Request, manager: ManagerDep, q: Q = ""
) -> list[dict[str, str]]:
    return await _files(request, session_folder(manager, session_id), q)


@router.get("/projects/{project_id}/files")
async def project_files(
    project_id: int, request: Request, conn: DbDep, q: Q = ""
) -> list[dict[str, str]]:
    return await _files(request, project_folder(conn, project_id), q)
```

No `lifespan`: `app.state.files = FileIndex()`, com `from vibing.filesearch import FileIndex`.

- [x] **Passo 5: rodar e ver passar.** Rode `uv run pytest backend/tests/test_filesearch.py backend/tests/test_suggestions_api.py -q` e depois `uv run pytest -q`.

- [x] **Passo 6: commit** (sessão principal, depois do `reviewer`). Marque o item 3 no roadmap.

```bash
git add backend/vibing/filesearch.py backend/vibing/api/suggestions.py backend/vibing/app.py backend/tests/test_filesearch.py backend/tests/test_suggestions_api.py ROADMAP.md
git commit -m "[Feat] Buscar arquivos e pastas para menções com @"
```

---

### Tarefa 4: funções puras de sugestão (`suggestions.ts`)

Item 4 do marco 13.

**Arquivos:**
- Modificar: `frontend/src/types/api.ts` (tipos novos no fim)
- Modificar: `frontend/src/api/http.ts` (duas funções)
- Criar: `frontend/src/conversation/suggestions.ts`
- Teste: `frontend/src/conversation/__tests__/suggestions.spec.ts` (novo)

**Interfaces:**
- Produz:
  - Em `types/api.ts`:
    ```ts
    export interface CommandInfo { name: string; description: string; argument_hint: string }
    export interface FileMatch { path: string; name: string; type: 'file' | 'directory' }
    export type SuggestionScope = { sessionId: string } | { projectId: number }
    ```
  - Em `api/http.ts`:
    - `listCommands(scope: SuggestionScope): Promise<CommandInfo[]>`
    - `searchFiles(scope: SuggestionScope, q: string, signal?: AbortSignal): Promise<FileMatch[]>`, com a URL `` `${base}/files?${new URLSearchParams({ q })}` ``. `base` é `/api/sessions/${encodeURIComponent(id)}` ou `/api/projects/${id}`.
  - Em `suggestions.ts`:
    - `type TriggerKind = 'command' | 'mention'`
    - `interface Trigger { kind: TriggerKind; start: number; end: number; query: string }`. `start` é a posição do `@` ou da `/`, `end` é o fim do trecho (exclusivo) e `query` é o texto entre os dois.
    - `findTrigger(text: string, cursor: number): Trigger | null`
    - `applySuggestion(text: string, trigger: Trigger, insert: string, addSpace: boolean): { text: string; cursor: number }`
    - `quotePath(path: string): string`
    - `mentionText(path: string): string`, que devolve `'@' + quotePath(path)`
    - `rankCommands(commands: CommandInfo[], term: string): CommandInfo[]`

- [x] **Passo 1: escrever os testes** em `frontend/src/conversation/__tests__/suggestions.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { applySuggestion, findTrigger, mentionText, quotePath, rankCommands } from '../suggestions'
import type { CommandInfo } from '../../types/api'

const cmd = (name: string, description = ''): CommandInfo => ({ name, description, argument_hint: '' })

describe('findTrigger', () => {
  it('acha @ e / no início, depois de espaço e de quebra de linha', () => {
    expect(findTrigger('@fs', 3)).toEqual({ kind: 'mention', start: 0, end: 3, query: 'fs' })
    expect(findTrigger('veja @fs', 8)).toEqual({ kind: 'mention', start: 5, end: 8, query: 'fs' })
    expect(findTrigger('a\n/com', 6)).toEqual({ kind: 'command', start: 2, end: 6, query: 'com' })
  })
  it('o termo vai até o fim do trecho, mesmo com o cursor no meio', () => {
    expect(findTrigger('@backend/fs x', 3)).toEqual({ kind: 'mention', start: 0, end: 11, query: 'backend/fs' })
  })
  it('ignora e/ou, e-mail e cursor fora do trecho', () => {
    expect(findTrigger('e/ou', 4)).toBeNull()
    expect(findTrigger('a@b.com', 7)).toBeNull()
    expect(findTrigger('@fs depois', 10)).toBeNull()
    expect(findTrigger('@fs', 0)).toBeNull()
  })
  it('/ só vale até a próxima barra, como na extensão', () => {
    expect(findTrigger('/usr/bin', 8)).toBeNull()
    expect(findTrigger('/usr/bin', 4)).toEqual({ kind: 'command', start: 0, end: 4, query: 'usr' })
  })
  it('só / e só @ abrem com termo vazio', () => {
    expect(findTrigger('/', 1)).toEqual({ kind: 'command', start: 0, end: 1, query: '' })
    expect(findTrigger('oi @', 4)).toEqual({ kind: 'mention', start: 3, end: 4, query: '' })
  })
})

describe('applySuggestion', () => {
  it('troca o trecho e põe espaço', () => {
    const t = findTrigger('rode /com agora', 9)!
    expect(applySuggestion('rode /com agora', t, '/commit', true)).toEqual({ text: 'rode /commit agora', cursor: 13 })
  })
  it('põe espaço no fim do texto', () => {
    const t = findTrigger('/com', 4)!
    expect(applySuggestion('/com', t, '/commit', true)).toEqual({ text: '/commit ', cursor: 8 })
  })
  it('sem espaço para pasta escolhida com Tab', () => {
    const t = findTrigger('@back', 5)!
    expect(applySuggestion('@back', t, '@backend/', false)).toEqual({ text: '@backend/', cursor: 9 })
  })
})

describe('aspas', () => {
  it('caminho com espaço, aspas ou # vai entre aspas', () => {
    expect(quotePath('a b/c.txt')).toBe('"a b/c.txt"')
    expect(quotePath('a#1.md')).toBe('"a#1.md"')
    expect(quotePath('a"b')).toBe('"a"b"')
    expect(quotePath('src/a.ts')).toBe('src/a.ts')
    expect(mentionText('meu arquivo.md')).toBe('@"meu arquivo.md"')
  })
})

describe('rankCommands', () => {
  const all = [cmd('commit'), cmd('compact-notes'), cmd('code-review', 'Revisa commits'), cmd('superpowers:brainstorming'), cmd('com')]
  it('nome igual, depois prefixo, depois contém/subsequência, depois descrição', () => {
    expect(rankCommands(all, 'com').map((c) => c.name)).toEqual(['com', 'commit', 'compact-notes', 'code-review'])
  })
  it('subsequência casa no grupo 2', () => {
    expect(rankCommands(all, 'sbrain').map((c) => c.name)).toEqual(['superpowers:brainstorming'])
    expect(rankCommands(all, 'superpowers:brain').map((c) => c.name)).toEqual(['superpowers:brainstorming'])
  })
  it('desempata por posição, nome mais curto e ordem alfabética', () => {
    const list = [cmd('xab'), cmd('ab-long'), cmd('ab'), cmd('abc')]
    expect(rankCommands(list, 'ab').map((c) => c.name)).toEqual(['ab', 'abc', 'ab-long', 'xab'])
  })
  it('termo vazio: todos em ordem alfabética', () => {
    expect(rankCommands(all, '').map((c) => c.name)).toEqual(['code-review', 'com', 'commit', 'compact-notes', 'superpowers:brainstorming'])
  })
  it('ignora maiúsculas e minúsculas e descarta o que não casa', () => {
    expect(rankCommands(all, 'COMMIT').map((c) => c.name)).toEqual(['commit', 'code-review'])
    expect(rankCommands(all, 'zzz')).toEqual([])
  })
})
```

Obs.: em `rankCommands(all, 'COMMIT')`, `code-review` entra pelo grupo 3, porque a descrição "Revisa commits" contém "commit".

- [x] **Passo 2: rodar e ver falhar.** Rode `pnpm --dir frontend exec vitest run src/conversation/__tests__/suggestions.spec.ts`. Esperado: falha ao importar `../suggestions`.

- [x] **Passo 3: implementar `frontend/src/conversation/suggestions.ts`:**

```ts
// Pure helpers of the `/` and `@` suggestion menus. Behavior follows the VS Code
// extension: the trigger is the token under the cursor, choosing replaces it.
import type { CommandInfo } from '../types/api'

export type TriggerKind = 'command' | 'mention'

export interface Trigger {
  kind: TriggerKind
  /** Index of the `@` or `/`. */
  start: number
  /** End of the token (exclusive). */
  end: number
  query: string
}

const PATTERNS: [TriggerKind, RegExp][] = [
  ['mention', /(^|\s)@[^\s]*/g],
  ['command', /(^|\s)\/[^\s/]*/g],
]

export function findTrigger(text: string, cursor: number): Trigger | null {
  for (const [kind, pattern] of PATTERNS) {
    for (const match of text.matchAll(pattern)) {
      const start = (match.index ?? 0) + match[1].length
      const end = (match.index ?? 0) + match[0].length
      if (cursor > start && cursor <= end) return { kind, start, end, query: text.slice(start + 1, end) }
    }
  }
  return null
}

export function applySuggestion(
  text: string,
  trigger: Trigger,
  insert: string,
  addSpace: boolean,
): { text: string; cursor: number } {
  const before = text.slice(0, trigger.start) + insert
  const after = text.slice(trigger.end)
  if (!addSpace) return { text: before + after, cursor: before.length }
  if (/^\s/.test(after)) return { text: before + after, cursor: before.length + 1 }
  return { text: before + ' ' + after, cursor: before.length + 1 }
}

export function quotePath(path: string): string {
  return /[\s"#]/.test(path) ? `"${path}"` : path
}

export function mentionText(path: string): string {
  return '@' + quotePath(path)
}

function subsequenceAt(name: string, term: string): number {
  let from = 0
  let first = -1
  for (const char of term) {
    const at = name.indexOf(char, from)
    if (at < 0) return -1
    if (first < 0) first = at
    from = at + 1
  }
  return first
}

export function rankCommands(commands: CommandInfo[], term: string): CommandInfo[] {
  const byName = (a: CommandInfo, b: CommandInfo) => a.name.localeCompare(b.name)
  const q = term.toLowerCase()
  if (!q) return [...commands].sort(byName)
  const ranked: { command: CommandInfo; group: number; position: number }[] = []
  for (const command of commands) {
    const name = command.name.toLowerCase()
    let group = -1
    let position = 0
    if (name === q) group = 0
    else if (name.startsWith(q)) group = 1
    else if (name.includes(q)) [group, position] = [2, name.indexOf(q)]
    else if (subsequenceAt(name, q) >= 0) [group, position] = [2, subsequenceAt(name, q)]
    else if (command.description.toLowerCase().includes(q)) {
      ;[group, position] = [3, command.description.toLowerCase().indexOf(q)]
    }
    if (group >= 0) ranked.push({ command, group, position })
  }
  ranked.sort(
    (a, b) =>
      a.group - b.group ||
      a.position - b.position ||
      a.command.name.length - b.command.name.length ||
      byName(a.command, b.command),
  )
  return ranked.map((r) => r.command)
}
```

Acrescente os tipos em `types/api.ts` e as duas funções em `api/http.ts`, junto das outras de sessão:

```ts
function scopeBase(scope: SuggestionScope): string {
  return 'sessionId' in scope
    ? `/api/sessions/${encodeURIComponent(scope.sessionId)}`
    : `/api/projects/${scope.projectId}`
}

export function listCommands(scope: SuggestionScope): Promise<CommandInfo[]> {
  return request('GET', `${scopeBase(scope)}/commands`)
}

export function searchFiles(scope: SuggestionScope, q: string, signal?: AbortSignal): Promise<FileMatch[]> {
  return request('GET', `${scopeBase(scope)}/files?${new URLSearchParams({ q })}`, undefined, signal)
}
```

- [x] **Passo 4: rodar e ver passar.** Rode `pnpm --dir frontend exec vitest run src/conversation/__tests__/suggestions.spec.ts`, depois `pnpm --dir frontend test` e `pnpm --dir frontend build`.

- [x] **Passo 5: commit** (sessão principal, depois do `reviewer`). Marque o item 4 no roadmap.

```bash
git add frontend/src/conversation/suggestions.ts frontend/src/conversation/__tests__/suggestions.spec.ts frontend/src/types/api.ts frontend/src/api/http.ts ROADMAP.md
git commit -m "[Feat] Adicionar funções de gatilho e ordenação das sugestões"
```

---

### Tarefa 5: composable e `SuggestionMenu`, com o menu `/`

Item 5 do marco 13. Esta tarefa cobre só o menu de comandos. O `@` entra na Tarefa 6.

**Arquivos:**
- Criar: `frontend/src/conversation/useComposerSuggestions.ts`
- Criar: `frontend/src/components/conversation/SuggestionMenu.vue`
- Teste: `frontend/src/conversation/__tests__/useComposerSuggestions.spec.ts` (novo) e `frontend/src/components/conversation/__tests__/SuggestionMenu.spec.ts` (novo)

**Interfaces:**
- Consome: `findTrigger`, `applySuggestion`, `rankCommands` e `mentionText` (Tarefa 4), e `listCommands`/`searchFiles` (Tarefa 4).
- Produz:
  ```ts
  export interface SuggestionItem {
    key: string
    kind: 'command' | 'file' | 'directory'
    label: string   // '/commit', 'fs.py', 'backend/vibing/'
    detail: string  // command description, or the file's folder
    hint: string    // command argument_hint ('' otherwise)
    insert: string  // '/commit', '@backend/vibing/fs.py'
  }
  export type SuggestionStatus = 'loading' | 'ready' | 'error'
  export interface ComposerSuggestionsOptions {
    textarea: Ref<HTMLTextAreaElement | null>
    text: Ref<string>
    scope: () => SuggestionScope | null
    /** After the text changed by a choice (e.g. `resize`). */
    onApplied?: () => void
  }
  export function useComposerSuggestions(options: ComposerSuggestionsOptions): {
    isOpen: ComputedRef<boolean>
    kind: Ref<TriggerKind | null>
    items: ComputedRef<SuggestionItem[]>
    active: Ref<number>
    status: Ref<SuggestionStatus>
    error: Ref<string | null>
    menuId: string
    optionId: (index: number) => string
    commands: Ref<CommandInfo[] | null>
    refresh: () => void
    onKeydown: (event: KeyboardEvent) => boolean
    choose: (index: number, via: 'enter' | 'tab' | 'click') => void
    close: () => void
    onBlur: () => void
  }
  ```
  - `SuggestionMenu.vue`:
    - props: `id: string`, `items: SuggestionItem[]`, `active: number`, `status: SuggestionStatus`, `error: string | null`, `kind: TriggerKind`, `optionId: (i: number) => string` e `placement?: 'above' | 'below'` (padrão `'above'`).
    - emits: `choose(index: number)` e `hover(index: number)`.

**Regras do composable** (spec 5.2, 5.4, 5.5, 6):
- `refresh()` lê `textarea.selectionStart` e `text.value`, e chama `findTrigger`.
  - Sem trecho: fecha e limpa a supressão.
  - Com supressão ativa: não faz nada.
  - Mesmo `kind` e mesma `query` de antes: não faz nada (a seleção fica onde está).
  - Caso contrário: grava o trecho e volta `active` a 0.
- O composable **não observa `text`**. O menu só se mexe por `refresh()`, chamado pelos eventos `input`, `keyup`, `click` e `select` do `textarea`. Assim o ditado, que muda o texto por programa, não abre menu.
- Comandos: na primeira vez que o `kind` vira `'command'` para uma fonte, `status` passa a `'loading'` e roda `listCommands(scope)`.
  - Sucesso: `commands` recebe a lista e `status` fica `'ready'`.
  - Erro: `status` fica `'error'` e `error` recebe `errorMessage(e)`. A lista continua `null`, então fechar e reabrir tenta de novo.
  - A chave da fonte é `JSON.stringify(scope())`. Um `watch` nessa chave zera `commands` e fecha o menu.
  - `items` do comando são `rankCommands(commands, query)`, mapeados assim:
    - `key: 'c:' + name`
    - `label: '/' + name`
    - `detail: description`
    - `hint: argument_hint`
    - `insert: '/' + name`
- `onKeydown(event)` devolve `true` quando tratou o evento (e aí já chamou `preventDefault`). Com o menu fechado, devolve `false`. Com o menu aberto:
  - `ArrowDown`/`ArrowUp` andam com volta nas pontas.
  - `Enter` ou `Tab` sem `shiftKey` e fora de composição (`isComposing` ou `keyCode === 229`):
    - com itens: `choose(active, key === 'Tab' ? 'tab' : 'enter')`;
    - sem itens: nada acontece, mas o evento conta como tratado.
  - `Escape` chama `close()`, liga a supressão e chama `stopPropagation()`.
  - `Shift+Enter` devolve `false`.
- `choose()` para comando: `applySuggestion(text, trigger, insert, true)`. Depois atualiza `text.value`, o `el.value` e o `setSelectionRange`, fecha e, no `nextTick`, chama `onApplied`.
- `onBlur()` fecha sem supressão.
- `menuId` é único por instância (contador de módulo), e `optionId(i)` é `` `${menuId}-opt-${i}` ``.

**Regras do `SuggestionMenu`** (spec 5.4, 5.6, 5.8):
- `<ul :id role="listbox" aria-label="Sugestões" @mousedown.prevent>`. Classes: `absolute left-0 right-0 z-20 max-h-72 overflow-y-auto rounded-lg border border-line-strong bg-panel p-1 shadow-lg`. Posição: `bottom-full mb-1` em `above` e `top-full mt-1` em `below`.
- Item: `<li :id="optionId(i)" role="option" :aria-selected="i === active" @mouseenter="emit('hover', i)" @click="emit('choose', i)">`. Classes `flex cursor-pointer items-baseline gap-2 rounded-md px-2.5 py-1.5 text-sm text-fg`, e `bg-elevated` no item marcado.
  - Comando: `<span class="font-mono">{{ label }}</span>`, `<span class="font-mono text-xs text-fg-muted">{{ hint }}</span>` e `<span class="min-w-0 truncate text-xs text-fg-muted">{{ detail }}</span>`.
- Estados: um `li` com `role="option" aria-disabled="true"` e classe `text-fg-muted`.
  - `loading`: "Carregando…" em comandos e "Buscando…" em menções, só quando não há itens.
  - `ready` sem itens: "Nenhum comando" ou "Nenhum arquivo encontrado".
  - `error`: o texto de `error`.
- `watch(() => props.active)` rola o item marcado com `document.getElementById(optionId(active))?.scrollIntoView?.({ block: 'nearest' })`. O `?.` protege o jsdom, que não tem `scrollIntoView`.

- [x] **Passo 1: testes do composable** em `frontend/src/conversation/__tests__/useComposerSuggestions.spec.ts`. Monte um componente de teste mínimo que usa o composable com um `textarea` real:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { useComposerSuggestions } from '../useComposerSuggestions'
import { jsonResponse, routeFetch } from '../../test/factories'
import type { SuggestionScope } from '../../types/api'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const COMMANDS = [
  { name: 'commit', description: 'Cria commit', argument_hint: '' },
  { name: 'hello', description: 'Diz olá', argument_hint: '<nome>' },
]

function harness(scope = ref<SuggestionScope | null>({ sessionId: 's1' })) {
  let api!: ReturnType<typeof useComposerSuggestions>
  const text = ref('')
  const Comp = defineComponent({
    setup() {
      const textarea = ref<HTMLTextAreaElement | null>(null)
      api = useComposerSuggestions({ textarea, text, scope: () => scope.value })
      return () => h('textarea', { ref: textarea })
    },
  })
  const wrapper = mount(Comp, { attachTo: document.body })
  const el = wrapper.find('textarea').element as HTMLTextAreaElement
  async function type(value: string, cursor = value.length) {
    text.value = value
    el.value = value
    el.setSelectionRange(cursor, cursor)
    api.refresh()
    await flushPromises()
  }
  function key(k: string, extra: KeyboardEventInit = {}) {
    const event = new KeyboardEvent('keydown', { key: k, cancelable: true, ...extra })
    const handled = api.onKeydown(event)
    return { handled, event }
  }
  return { api, text, el, type, key, scope }
}

describe('menu /', () => {
  it('busca a lista uma vez por fonte e filtra no navegador', async () => {
    const fetch = routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) })
    vi.stubGlobal('fetch', fetch)
    const t = harness()
    await t.type('/co')
    expect(t.api.isOpen.value).toBe(true)
    expect(t.api.items.value.map((i) => i.label)).toEqual(['/commit'])
    await t.type('/he')
    await t.type('')
    await t.type('/')
    expect(t.api.items.value.map((i) => i.label)).toEqual(['/commit', '/hello'])
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('mostra carregando e depois erro; reabrir tenta de novo', async () => {
    let fail = true
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/commands': () => (fail ? jsonResponse({ detail: 'CLI não encontrado.' }, 502) : jsonResponse(COMMANDS)),
    }))
    const t = harness()
    t.text.value = '/'
    t.el.value = '/'
    t.el.setSelectionRange(1, 1)
    t.api.refresh()
    expect(t.api.status.value).toBe('loading')
    await flushPromises()
    expect(t.api.status.value).toBe('error')
    expect(t.api.error.value).toBe('CLI não encontrado.')
    fail = false
    await t.type('')
    await t.type('/')
    expect(t.api.status.value).toBe('ready')
  })

  it('teclado: setas com volta, Enter escolhe e põe espaço', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/')
    expect(t.api.active.value).toBe(0)
    t.key('ArrowUp')
    expect(t.api.active.value).toBe(1)
    t.key('ArrowDown')
    expect(t.api.active.value).toBe(0)
    const { handled, event } = t.key('Enter')
    expect(handled).toBe(true)
    expect(event.defaultPrevented).toBe(true)
    expect(t.text.value).toBe('/commit ')
    expect(t.el.selectionStart).toBe(8)
    expect(t.api.isOpen.value).toBe(false)
  })

  it('Tab escolhe; Shift+Enter e composição não são tratados', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/he')
    expect(t.key('Enter', { shiftKey: true }).handled).toBe(false)
    expect(t.key('Enter', { isComposing: true }).handled).toBe(false)
    t.key('Tab')
    expect(t.text.value).toBe('/hello ')
  })

  it('Enter com menu aberto e sem itens não faz nada', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/zzz')
    const { handled, event } = t.key('Enter')
    expect(handled).toBe(true)
    expect(event.defaultPrevented).toBe(true)
    expect(t.text.value).toBe('/zzz')
  })

  it('Esc fecha e suprime até sair do trecho', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/co')
    const { event } = t.key('Escape')
    expect(t.api.isOpen.value).toBe(false)
    expect(event.defaultPrevented).toBe(true)
    await t.type('/com')
    expect(t.api.isOpen.value).toBe(false)
    await t.type('/com ')
    await t.type('/com /')
    expect(t.api.isOpen.value).toBe(true)
  })

  it('trocar a fonte zera a lista e fecha', async () => {
    const fetch = routeFetch({
      'GET /api/projects/1/commands': () => jsonResponse(COMMANDS),
      'GET /api/projects/2/commands': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetch)
    const scope = ref<SuggestionScope | null>({ projectId: 1 })
    const t = harness(scope)
    await t.type('/')
    scope.value = { projectId: 2 }
    await nextTick()
    expect(t.api.isOpen.value).toBe(false)
    await t.type('')
    await t.type('/')
    expect(t.api.items.value).toEqual([])
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('perder o foco fecha sem suprimir', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
    const t = harness()
    await t.type('/co')
    t.api.onBlur()
    expect(t.api.isOpen.value).toBe(false)
    await t.type('/com')
    expect(t.api.isOpen.value).toBe(true)
  })
})
```

- [x] **Passo 2: testes do menu** em `frontend/src/components/conversation/__tests__/SuggestionMenu.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SuggestionMenu from '../SuggestionMenu.vue'

const items = [
  { key: 'c:commit', kind: 'command' as const, label: '/commit', detail: 'Cria commit', hint: '', insert: '/commit' },
  { key: 'c:hello', kind: 'command' as const, label: '/hello', detail: 'Diz olá', hint: '<nome>', insert: '/hello' },
]
const base = { id: 'm1', optionId: (i: number) => `m1-opt-${i}`, kind: 'command' as const, error: null }

describe('SuggestionMenu', () => {
  it('lista com papéis de acessibilidade e item marcado', () => {
    const w = mount(SuggestionMenu, { props: { ...base, items, active: 1, status: 'ready' } })
    expect(w.get('ul').attributes()).toMatchObject({ id: 'm1', role: 'listbox', 'aria-label': 'Sugestões' })
    const options = w.findAll('[role="option"]')
    expect(options.map((o) => o.attributes('aria-selected'))).toEqual(['false', 'true'])
    expect(options[1].attributes('id')).toBe('m1-opt-1')
    expect(options[1].text()).toContain('<nome>')
  })
  it('emite hover e choose', async () => {
    const w = mount(SuggestionMenu, { props: { ...base, items, active: 0, status: 'ready' } })
    await w.findAll('[role="option"]')[1].trigger('mouseenter')
    await w.findAll('[role="option"]')[1].trigger('click')
    expect(w.emitted('hover')).toEqual([[1]])
    expect(w.emitted('choose')).toEqual([[1]])
  })
  it('mousedown não tira o foco', async () => {
    const w = mount(SuggestionMenu, { props: { ...base, items, active: 0, status: 'ready' } })
    const event = new MouseEvent('mousedown', { cancelable: true, bubbles: true })
    w.get('ul').element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })
  it.each([
    ['loading', 'command', null, 'Carregando…'],
    ['loading', 'mention', null, 'Buscando…'],
    ['ready', 'command', null, 'Nenhum comando'],
    ['ready', 'mention', null, 'Nenhum arquivo encontrado'],
    ['error', 'command', 'CLI não encontrado.', 'CLI não encontrado.'],
  ] as const)('estado %s/%s', (status, kind, error, text) => {
    const w = mount(SuggestionMenu, { props: { ...base, kind, error, items: [], active: 0, status } })
    const option = w.get('[role="option"]')
    expect(option.text()).toBe(text)
    expect(option.attributes('aria-disabled')).toBe('true')
  })
})
```

- [x] **Passo 3: rodar e ver falhar.** Rode `pnpm --dir frontend exec vitest run src/conversation/__tests__/useComposerSuggestions.spec.ts src/components/conversation/__tests__/SuggestionMenu.spec.ts`.

- [x] **Passo 4: implementar** o composable e o componente seguindo as regras acima. Esboço do núcleo do composable:

```ts
import { computed, nextTick, ref, watch, type Ref } from 'vue'
import { errorMessage, listCommands } from '../api/http'
import type { CommandInfo, SuggestionScope } from '../types/api'
import { applySuggestion, findTrigger, rankCommands, type Trigger, type TriggerKind } from './suggestions'

let nextMenu = 0

export function useComposerSuggestions(options: ComposerSuggestionsOptions) {
  const menuId = `suggestions-${++nextMenu}`
  const trigger = ref<Trigger | null>(null)
  const suppressed = ref(false)
  const active = ref(0)
  const status = ref<SuggestionStatus>('ready')
  const error = ref<string | null>(null)
  const commands = ref<CommandInfo[] | null>(null)
  let commandsLoading = false
  const scopeKey = () => JSON.stringify(options.scope())

  const kind = computed<TriggerKind | null>(() => trigger.value?.kind ?? null)
  const isOpen = computed(() => trigger.value !== null && !suppressed.value)
  const items = computed<SuggestionItem[]>(() => {
    const t = trigger.value
    if (!t || t.kind !== 'command' || !commands.value) return []
    return rankCommands(commands.value, t.query).map((c) => ({
      key: `c:${c.name}`, kind: 'command', label: `/${c.name}`, detail: c.description,
      hint: c.argument_hint, insert: `/${c.name}`,
    }))
  })
  watch(items, () => { active.value = 0 })
  watch(scopeKey, () => { commands.value = null; close() })

  async function loadCommands() {
    const scope = options.scope()
    if (!scope || commands.value || commandsLoading) return
    const key = scopeKey()
    commandsLoading = true
    status.value = 'loading'
    error.value = null
    try {
      const list = await listCommands(scope)
      if (key === scopeKey()) { commands.value = list; status.value = 'ready' }
    } catch (e) {
      if (key === scopeKey()) { status.value = 'error'; error.value = errorMessage(e) }
    } finally {
      commandsLoading = false
    }
  }

  function refresh() {
    const el = options.textarea.value
    const found = el ? findTrigger(options.text.value, el.selectionStart ?? options.text.value.length) : null
    if (!found) { trigger.value = null; suppressed.value = false; return }
    if (suppressed.value) return
    const current = trigger.value
    if (current && current.kind === found.kind && current.query === found.query) {
      trigger.value = found  // positions may have shifted; keep the selection
      return
    }
    trigger.value = found
    active.value = 0
    if (found.kind === 'command') {
      if (commands.value) status.value = 'ready'
      else void loadCommands()
    }
  }
  // ... onKeydown, choose, close, onBlur as specified
}
```

Na Tarefa 5, `refresh()` também abre o menu para `@`, mas sem itens e com status `ready`, o que mostraria "Nenhum arquivo encontrado". Para não expor isso antes da Tarefa 6, `refresh()` **ignora** `kind === 'mention'` nesta tarefa, tratando o caso como sem trecho. A Tarefa 6 tira esse filtro.

- [x] **Passo 5: rodar e ver passar.** Rode os dois arquivos, depois `pnpm --dir frontend test` e `pnpm --dir frontend build`.

- [x] **Passo 6: commit** (sessão principal, depois do `reviewer`). Marque o item 5 no roadmap.

```bash
git add frontend/src/conversation/useComposerSuggestions.ts frontend/src/conversation/__tests__/useComposerSuggestions.spec.ts frontend/src/components/conversation/SuggestionMenu.vue frontend/src/components/conversation/__tests__/SuggestionMenu.spec.ts ROADMAP.md
git commit -m "[Feat] Adicionar menu de comandos com / no campo de mensagem"
```

---

### Tarefa 6: menu `@` com pastas

Item 6 do marco 13.

**Arquivos:**
- Modificar: `frontend/src/conversation/useComposerSuggestions.ts`
- Modificar: `frontend/src/components/conversation/SuggestionMenu.vue` (linhas de arquivo e pasta)
- Teste: os mesmos dois arquivos de teste da Tarefa 5 (acrescentar)

**Interfaces:**
- Consome: `searchFiles`, `mentionText`, `SuggestionItem` e as regras da Tarefa 5.
- Produz, no composable, o `ref` `mentions: Ref<Set<string>>` com as menções inseridas a partir da lista, sem o espaço final. A Tarefa 9 usa esse conjunto.

**Regras** (spec 5.3):
- Quando `refresh()` chega a um trecho `mention` com `query` nova, agenda a busca com `setTimeout(200)` e cancela a anterior.
  - Cada busca recebe `seq = ++lastSeq`. Uma resposta com `seq !== lastSeq` é descartada.
  - `status` fica `'loading'` enquanto não chega a primeira resposta desde que o menu abriu. Nas buscas seguintes, os itens antigos ficam na tela até a resposta nova chegar.
  - Erro: `status` fica `'error'` e `error` recebe a mensagem. A próxima mudança do termo tenta de novo.
- Itens de arquivo:
  - `key: 'f:' + path`
  - `kind: 'file'`
  - `label: name`
  - `detail`: a pasta (o `path` sem o nome e sem a barra final, ou `''` na raiz)
  - `insert: mentionText(path)`
- Itens de pasta:
  - `key: 'd:' + path`
  - `kind: 'directory'`
  - `label: path` (com `/`)
  - `detail: ''`
  - `insert: mentionText(path)`
- `choose()`:
  - Arquivo: insere com espaço, fecha e acrescenta `insert` a `mentions`.
  - Pasta com `enter`: insere com espaço, fecha e acrescenta a `mentions`.
  - Pasta com `tab` ou `click`: insere **sem** espaço e chama `refresh()` logo depois, com o cursor no fim da inserção. O novo termo (`backend/`) dispara a nova busca e o menu continua aberto.
- `close()` e a desmontagem (`onBeforeUnmount`) cancelam o `setTimeout` pendente.
- `SuggestionMenu`:
  - Arquivo: ícone de arquivo (SVG inline de `ReadTool.vue` L24), nome em `text-fg` e pasta em `text-xs text-fg-muted`.
  - Pasta: ícone de pasta (path de `FolderBrowser.vue` L136-149, `stroke-fg-muted`) e o caminho com `/`.

- [x] **Passo 1: testes que falham.** Acrescente em `useComposerSuggestions.spec.ts`, num `describe('menu @')` com `vi.useFakeTimers()` no `beforeEach` e `vi.useRealTimers()` no `afterEach`:

```ts
const FILES = [
  { path: 'backend/', name: 'backend', type: 'directory' },
  { path: 'backend/fs.py', name: 'fs.py', type: 'file' },
]

it('espera 200 ms antes de buscar', async () => {
  const fetch = routeFetch({ 'GET /api/sessions/s1/files?q=fs': () => jsonResponse(FILES) })
  vi.stubGlobal('fetch', fetch)
  const t = harness()
  await t.type('@fs')
  expect(t.api.status.value).toBe('loading')
  expect(fetch).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(199)
  expect(fetch).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1)
  await flushPromises()
  expect(t.api.items.value.map((i) => i.label)).toEqual(['backend/', 'fs.py'])
  expect(t.api.items.value[1].detail).toBe('backend')
})

it('resposta velha descartada', async () => {
  let releaseOld!: () => void
  const old = new Promise<Response>((resolve) => { releaseOld = () => resolve(jsonResponse([{ path: 'velho.py', name: 'velho.py', type: 'file' }])) })
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/files?q=ab': () => old,
    'GET /api/sessions/s1/files?q=abc': () => jsonResponse([{ path: 'abc.py', name: 'abc.py', type: 'file' }]),
  }))
  const t = harness()
  await t.type('@ab')
  await vi.advanceTimersByTimeAsync(200)
  await t.type('@abc')
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  releaseOld()
  await flushPromises()
  expect(t.api.items.value.map((i) => i.label)).toEqual(['abc.py'])
})

it('arquivo escolhido: @caminho com espaço, fecha e entra no conjunto de menções', async () => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=fs': () => jsonResponse(FILES) }))
  const t = harness()
  await t.type('veja @fs')
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  t.key('ArrowDown')
  t.key('Enter')
  expect(t.text.value).toBe('veja @backend/fs.py ')
  expect(t.api.isOpen.value).toBe(false)
  expect([...t.api.mentions.value]).toEqual(['@backend/fs.py'])
})

it('pasta com Tab: sem espaço, menu continua e busca o novo termo', async () => {
  const fetch = routeFetch({
    'GET /api/sessions/s1/files?q=back': () => jsonResponse(FILES),
    'GET /api/sessions/s1/files?q=backend%2F': () => jsonResponse([FILES[1]]),
  })
  vi.stubGlobal('fetch', fetch)
  const t = harness()
  await t.type('@back')
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  t.key('Tab')
  expect(t.text.value).toBe('@backend/')
  expect(t.api.isOpen.value).toBe(true)
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  expect(t.api.items.value.map((i) => i.label)).toEqual(['fs.py'])
})

it('pasta com Enter: com espaço e fecha', async () => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=back': () => jsonResponse(FILES) }))
  const t = harness()
  await t.type('@back')
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  t.key('Enter')
  expect(t.text.value).toBe('@backend/ ')
  expect(t.api.isOpen.value).toBe(false)
})

it('erro da busca aparece e a próxima mudança tenta de novo', async () => {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/files?q=x': () => jsonResponse({ detail: 'Falha ao listar os arquivos: x' }, 502),
    'GET /api/sessions/s1/files?q=xy': () => jsonResponse([]),
  }))
  const t = harness()
  await t.type('@x')
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  expect(t.api.status.value).toBe('error')
  expect(t.api.error.value).toBe('Falha ao listar os arquivos: x')
  await t.type('@xy')
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  expect(t.api.status.value).toBe('ready')
})

it('caminho com espaço vai entre aspas', async () => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/files?q=meu': () => jsonResponse([{ path: 'meu arquivo.md', name: 'meu arquivo.md', type: 'file' }]) }))
  const t = harness()
  await t.type('@meu')
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  t.key('Enter')
  expect(t.text.value).toBe('@"meu arquivo.md" ')
})
```

Em `SuggestionMenu.spec.ts`: teste de que uma linha de arquivo mostra o nome e a pasta, e uma linha de pasta mostra o caminho com `/`, cada uma com o seu ícone (`svg`).

Com os timers falsos, confira que `flushPromises` e `advanceTimersByTimeAsync` resolvem o `fetch` falso. Se `routeFetch` depender de microtarefas, `advanceTimersByTimeAsync` já as esvazia.

- [x] **Passo 2: rodar e ver falhar.**
- [x] **Passo 3: implementar** conforme as regras e tirar o filtro de `mention` da Tarefa 5.
- [x] **Passo 4: rodar e ver passar.** Rode os arquivos, depois `pnpm --dir frontend test` e `pnpm --dir frontend build`.
- [x] **Passo 5: commit** (sessão principal, depois do `reviewer`). Marque o item 6 no roadmap.

```bash
git add frontend/src/conversation/useComposerSuggestions.ts frontend/src/conversation/__tests__/useComposerSuggestions.spec.ts frontend/src/components/conversation/SuggestionMenu.vue frontend/src/components/conversation/__tests__/SuggestionMenu.spec.ts ROADMAP.md
git commit -m "[Feat] Adicionar menu de arquivos e pastas com @"
```

---

### Tarefa 7: integração no campo da conversa

Item 7 do marco 13.

**Arquivos:**
- Modificar: `frontend/src/components/conversation/MessageComposer.vue`
- Teste: `frontend/src/components/conversation/__tests__/composerSuggestions.spec.ts` (novo)

**Interfaces:**
- Consome: `useComposerSuggestions` e `SuggestionMenu` (Tarefas 5 e 6).
- Produz: o `textarea` do composer embrulhado em `<div class="relative min-w-0 grow">`, junto com o `SuggestionMenu`. A Tarefa 9 põe o `MentionMirror` dentro desse mesmo `div`.

**Mudanças** (spec 5.1, 5.5, 5.8):
1. `const suggestions = useComposerSuggestions({ textarea, text, scope: () => ({ sessionId: props.sessionId }), onApplied: resize })`.
2. No começo de `onKeydown`: `if (suggestions.onKeydown(event)) return`. Assim, com o menu aberto, Enter escolhe e Ctrl+Enter não quebra linha. Com o menu fechado, o comportamento é o de hoje.
3. No `textarea`:
   - Eventos: `@input="onInput"` (que chama `suggestions.refresh()` depois de `resize()`), `@keyup="suggestions.refresh()"`, `@click="suggestions.refresh()"`, `@select="suggestions.refresh()"` e `@blur="suggestions.onBlur()"`.
   - Atributos: `role="combobox"`, `aria-autocomplete="list"`, `:aria-expanded="suggestions.isOpen.value"`, `:aria-controls="suggestions.menuId"` e `:aria-activedescendant="suggestions.isOpen.value && suggestions.items.value.length ? suggestions.optionId(suggestions.active.value) : undefined"`.
4. `send()` chama `suggestions.close()` antes de enviar.
5. `begin()` do ditado chama `suggestions.close()`.
6. O `div` do `textarea` passa a envolver o `textarea` (que perde `grow` e ganha `w-full`) e o `<SuggestionMenu v-if="suggestions.isOpen.value" ... @choose="(i) => suggestions.choose(i, 'click')" @hover="(i) => (suggestions.active.value = i)" />`.
7. A dica do rodapé continua como está.

- [x] **Passo 1: testes que falham** em `composerSuggestions.spec.ts`. Use o setup de `composer.spec.ts`, com `attachTo: document.body`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MessageComposer from '../MessageComposer.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { FakeRecognition } from '../../../test/fakeRecognition'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const COMMANDS = [{ name: 'commit', description: 'Cria commit', argument_hint: '' }]

function setup() {
  const fetchMock = routeFetch({
    'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS),
    'POST /api/sessions/s1/messages': () => jsonResponse({}, 202),
  })
  vi.stubGlobal('fetch', fetchMock)
  const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' }, attachTo: document.body })
  const ta = w.get('textarea')
  const el = ta.element as HTMLTextAreaElement
  async function type(value: string) {
    await ta.setValue(value)
    el.setSelectionRange(value.length, value.length)
    await ta.trigger('input')
    await flushPromises()
  }
  const sent = () => fetchMock.mock.calls.filter((c) => c[0] === '/api/sessions/s1/messages')
  return { w, ta, el, type, sent }
}

describe('MessageComposer com sugestões', () => {
  it('Enter com menu aberto escolhe e não envia', async () => {
    const { w, ta, type, sent } = setup()
    await type('/co')
    expect(w.find('[role="listbox"]').exists()).toBe(true)
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect((ta.element as HTMLTextAreaElement).value).toBe('/commit ')
    expect(sent()).toHaveLength(0)
    expect(w.find('[role="listbox"]').exists()).toBe(false)
  })

  it('com menu fechado, Enter envia como hoje', async () => {
    const { ta, type, sent } = setup()
    await type('/commit agora')
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(sent()).toHaveLength(1)
  })

  it('combobox com aria-expanded, aria-controls e aria-activedescendant', async () => {
    const { w, ta, type } = setup()
    expect(ta.attributes('role')).toBe('combobox')
    expect(ta.attributes('aria-expanded')).toBe('false')
    await type('/')
    expect(ta.attributes('aria-expanded')).toBe('true')
    const menu = w.get('[role="listbox"]')
    expect(ta.attributes('aria-controls')).toBe(menu.attributes('id'))
    expect(ta.attributes('aria-activedescendant')).toBe(w.get('[role="option"]').attributes('id'))
  })

  it('clique no item escolhe', async () => {
    const { w, ta, type } = setup()
    await type('/co')
    await w.get('[role="option"]').trigger('click')
    expect((ta.element as HTMLTextAreaElement).value).toBe('/commit ')
  })

  it('ditado não abre menu e fecha o que estava aberto', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { w, type } = setup()
    await type('/co')
    await w.get('[data-test="dictate"]').trigger('click')
    expect(w.find('[role="listbox"]').exists()).toBe(false)
    FakeRecognition.last!.emitResult('/ditado', true)
    await flushPromises()
    expect(w.find('[role="listbox"]').exists()).toBe(false)
  })
})
```

Confira em `src/test/fakeRecognition.ts` os nomes reais (`FakeRecognition.last`, o método que emite resultado) e ajuste o último teste a eles. O teste precisa mostrar duas coisas: começar o ditado fecha o menu, e o texto ditado não o abre.

- [x] **Passo 2: rodar e ver falhar.**
- [x] **Passo 3: implementar** as mudanças 1 a 7.
- [x] **Passo 4: rodar e ver passar.** Rode o arquivo novo, `composer.spec.ts` e `composerExtras.spec.ts` (que não podem quebrar), depois `pnpm --dir frontend test` e `pnpm --dir frontend build`.
- [x] **Passo 5: commit** (sessão principal, depois do `reviewer`). Marque o item 7 no roadmap.

```bash
git add frontend/src/components/conversation/MessageComposer.vue frontend/src/components/conversation/__tests__/composerSuggestions.spec.ts ROADMAP.md
git commit -m "[Feat] Ligar comandos e menções ao campo da conversa"
```

---

### Tarefa 8: integração no modal de nova conversa

Item 8 do marco 13.

**Arquivos:**
- Modificar: `frontend/src/components/NewConversationModal.vue`
- Teste: `frontend/src/components/__tests__/NewConversationModalSuggestions.spec.ts` (novo)

**Interfaces:**
- Consome: `useComposerSuggestions` e `SuggestionMenu`.

**Mudanças:**
1. `const promptText = computed({ get: () => draft.value.prompt, set: (v) => (draft.value.prompt = v) })`. O composable recebe um `Ref<string>`, e um `computed` gravável serve.
2. `const suggestions = useComposerSuggestions({ textarea: promptEl, text: promptText, scope: () => (draft.value.projectId != null ? { projectId: draft.value.projectId } : null) })`. Trocar o projeto muda a chave, o que zera a lista e fecha o menu (regra da Tarefa 5).
3. No começo de `onPromptKey`: `if (suggestions.onKeydown(event)) return`. O `Escape` tratado pelo composable chama `stopPropagation`, então o `@keydown.esc` do overlay não fecha o modal.
4. No `textarea`, os mesmos eventos e atributos da Tarefa 7, e `onPromptInput` chama `suggestions.refresh()`. `begin()` do ditado chama `suggestions.close()`. `submit()` chama `suggestions.close()`.
5. Envolva o `textarea` num `<div class="relative flex min-h-40 grow flex-col">`: o `textarea` fica com `grow` e o `SuggestionMenu` fica ao lado.
6. `placement`: ao abrir, calcule o espaço acima do `textarea` dentro do corpo rolável (`promptEl.value.getBoundingClientRect().top - scrollBody.getBoundingClientRect().top`). Com 288 px ou mais (a altura máxima do menu), use `'above'`; com menos, `'below'`. No jsdom tudo mede 0, então o resultado é `'below'`.

- [x] **Passo 1: testes que falham.** Use o setup de `NewConversationModal.spec.ts` (pinia real, projetos 1, 2 e 3, `openModal`). Acrescente aos handlers `'GET /api/projects/2/commands'` e `'GET /api/projects/1/commands'`:

```ts
it('usa os comandos do projeto escolhido', async () => {
  const { wrapper, fetch } = await openModal(2, {
    'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
  })
  const ta = wrapper.get('[data-test="nc-prompt"]')
  await ta.setValue('/co')
  ;(ta.element as HTMLTextAreaElement).setSelectionRange(3, 3)
  await ta.trigger('input')
  await flushPromises()
  expect(wrapper.find('[role="listbox"]').text()).toContain('/commit')
  expect(fetch.mock.calls.some((c) => c[0] === '/api/projects/2/commands')).toBe(true)
})

it('trocar de projeto zera a lista e fecha o menu', async () => {
  const { wrapper, fetch } = await openModal(2, {
    'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
    'GET /api/projects/1/commands': () => jsonResponse([{ name: 'hello', description: '', argument_hint: '' }]),
  })
  const ta = wrapper.get('[data-test="nc-prompt"]')
  const el = ta.element as HTMLTextAreaElement
  await ta.setValue('/')
  el.setSelectionRange(1, 1)
  await ta.trigger('input')
  await flushPromises()
  await wrapper.get('[data-test="nc-project"]').setValue(1)
  await flushPromises()
  expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  await ta.trigger('input')
  await flushPromises()
  expect(wrapper.get('[role="listbox"]').text()).toContain('/hello')
  expect(fetch.mock.calls.filter((c) => String(c[0]).endsWith('/commands'))).toHaveLength(2)
})

it('Esc fecha só o menu, não o modal', async () => {
  const { wrapper } = await openModal(2, {
    'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
  })
  const ta = wrapper.get('[data-test="nc-prompt"]')
  await ta.setValue('/co')
  ;(ta.element as HTMLTextAreaElement).setSelectionRange(3, 3)
  await ta.trigger('input')
  await flushPromises()
  await ta.trigger('keydown', { key: 'Escape' })
  expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  expect(useNewConversationStore(pinia).isOpen).toBe(true)
})

it('Enter com menu aberto escolhe e não cria a conversa', async () => {
  const { wrapper, fetch } = await openModal(2, {
    'GET /api/projects/2/commands': () => jsonResponse([{ name: 'commit', description: '', argument_hint: '' }]),
  })
  const ta = wrapper.get('[data-test="nc-prompt"]')
  await ta.setValue('/co')
  ;(ta.element as HTMLTextAreaElement).setSelectionRange(3, 3)
  await ta.trigger('input')
  await flushPromises()
  await ta.trigger('keydown', { key: 'Enter' })
  await flushPromises()
  expect((ta.element as HTMLTextAreaElement).value).toBe('/commit ')
  expect(fetch.mock.calls.some((c) => c[0] === '/api/projects/2/sessions')).toBe(false)
})
```

Confira o nome do getter de aberto no store `useNewConversationStore` (`isOpen`) e ajuste se for outro.

- [x] **Passo 2: rodar e ver falhar.**
- [x] **Passo 3: implementar** as mudanças 1 a 6.
- [x] **Passo 4: rodar e ver passar.** Rode o arquivo novo e os três `NewConversationModal*.spec.ts` existentes, depois `pnpm --dir frontend test` e `pnpm --dir frontend build`.
- [x] **Passo 5: commit** (sessão principal, depois do `reviewer`). Marque o item 8 no roadmap.

```bash
git add frontend/src/components/NewConversationModal.vue frontend/src/components/__tests__/NewConversationModalSuggestions.spec.ts ROADMAP.md
git commit -m "[Feat] Ligar comandos e menções ao modal de nova conversa"
```

---

### Tarefa 9: realce das menções e dica de argumentos (`MentionMirror`)

Item 9 do marco 13.

**Arquivos:**
- Criar: `frontend/src/components/conversation/MentionMirror.vue`
- Modificar: `frontend/src/conversation/useComposerSuggestions.ts` (retorna `argumentHint`; poda de `mentions`)
- Modificar: `frontend/src/components/conversation/MessageComposer.vue` e `frontend/src/components/NewConversationModal.vue`
- Teste: `frontend/src/components/conversation/__tests__/MentionMirror.spec.ts` (novo) e acréscimos em `useComposerSuggestions.spec.ts`

**Interfaces:**
- Consome: `mentions` (Tarefa 6) e `commands` (Tarefa 5).
- Produz:
  - No composable, `argumentHint: ComputedRef<string>`. Ele vale `argument_hint` quando o texto inteiro é `/nome ` e o comando `nome` tem dica, e `''` nos outros casos.
  - A poda: um `watch(text)` tira de `mentions` as que o texto deixou de conter.
  - `MentionMirror.vue`:
    - props: `text: string`, `mentions: Set<string>`, `hint: string` e `scrollTop: number`.
    - Só apresentação: `aria-hidden="true"`, sem eventos.

**Regras** (spec 5.7):
- O `MentionMirror` é um `div` `absolute inset-0 pointer-events-none overflow-hidden whitespace-pre-wrap break-words`. Ele copia do `textarea` a borda (transparente), o preenchimento, a fonte, o tamanho e a altura de linha, e tem texto `text-transparent`.
- O conteúdo é o texto em partes. As ocorrências de cada menção do conjunto (no início ou depois de espaço, e seguidas de espaço ou do fim) viram `<mark class="rounded bg-primary/25 text-transparent">`. Depois do texto vem a dica, `<span class="text-fg-muted">`, e um `​` no fim, para uma quebra de linha final ter altura.
- Um `watch(scrollTop)` copia o valor para `el.scrollTop`.
- No composer, o fundo sai do `textarea` e vai para o `div relative` da Tarefa 7:
  - `div`: `rounded-lg bg-panel`.
  - `textarea`: `relative bg-transparent` (mantém a borda e o texto `text-fg`).
  - `MentionMirror` fica antes do `textarea` no DOM.
  - `@scroll` no `textarea` atualiza um `ref` `scrollTop`.
- No modal, o mesmo, com o fundo `bg-bg` e o preenchimento `px-3 py-2` / `leading-relaxed` do `textarea` dele.

- [ ] **Passo 1: testes que falham.** `MentionMirror.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MentionMirror from '../MentionMirror.vue'

describe('MentionMirror', () => {
  it('realça só as menções escolhidas', () => {
    const w = mount(MentionMirror, { props: { text: 'veja @a.py e @b.py', mentions: new Set(['@a.py']), hint: '', scrollTop: 0 } })
    expect(w.findAll('mark').map((m) => m.text())).toEqual(['@a.py'])
    expect(w.attributes('aria-hidden')).toBe('true')
  })
  it('não realça trecho que só começa igual', () => {
    const w = mount(MentionMirror, { props: { text: '@a.pyc', mentions: new Set(['@a.py']), hint: '', scrollTop: 0 } })
    expect(w.findAll('mark')).toHaveLength(0)
  })
  it('mostra a dica em cinza', () => {
    const w = mount(MentionMirror, { props: { text: '/hello ', mentions: new Set(), hint: '<nome>', scrollTop: 0 } })
    expect(w.get('.text-fg-muted').text()).toBe('<nome>')
  })
  it('acompanha a rolagem', async () => {
    const w = mount(MentionMirror, { props: { text: 'x', mentions: new Set(), hint: '', scrollTop: 0 } })
    await w.setProps({ scrollTop: 40 })
    expect((w.element as HTMLElement).scrollTop).toBe(40)
  })
})
```

Em `useComposerSuggestions.spec.ts`:

```ts
it('argumentHint só com o texto igual a /nome ', async () => {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS) }))
  const t = harness()
  await t.type('/he')
  t.key('Enter')
  expect(t.text.value).toBe('/hello ')
  expect(t.api.argumentHint.value).toBe('<nome>')
  t.text.value = '/hello V'
  await nextTick()
  expect(t.api.argumentHint.value).toBe('')
})

it('menção sai do conjunto quando o texto deixa de contê-la', async () => {
  vi.useFakeTimers()
  try {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/files?q=fs': () => jsonResponse([{ path: 'backend/fs.py', name: 'fs.py', type: 'file' }]),
    }))
    const t = harness()
    await t.type('veja @fs')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    t.key('Enter')
    expect([...t.api.mentions.value]).toEqual(['@backend/fs.py'])
    t.text.value = 'veja @backend/fs.py e mais'
    await nextTick()
    expect(t.api.mentions.value.size).toBe(1)
    t.text.value = 'veja '
    await nextTick()
    expect(t.api.mentions.value.size).toBe(0)
  } finally {
    vi.useRealTimers()
  }
})
```

No composer, um teste em `composerSuggestions.spec.ts`: depois de escolher `/commit`, existe `[aria-hidden="true"]` com o texto; com `hello` e dica, o texto `<nome>` aparece.

- [ ] **Passo 2: rodar e ver falhar.**
- [ ] **Passo 3: implementar.**
- [ ] **Passo 4: rodar e ver passar.** Rode os arquivos, `pnpm --dir frontend test` e `pnpm --dir frontend build`. Abra o app (`pnpm --dir frontend dev` com o backend rodando) e confira a olho que o texto do `textarea` e a camada ficam alinhados em várias linhas e com rolagem. Relate como verificação visual, separada dos testes.
- [ ] **Passo 5: commit** (sessão principal, depois do `reviewer`). Marque o item 9 no roadmap.

```bash
git add frontend/src/components/conversation/MentionMirror.vue frontend/src/components/conversation/__tests__/MentionMirror.spec.ts frontend/src/conversation/useComposerSuggestions.ts frontend/src/conversation/__tests__/useComposerSuggestions.spec.ts frontend/src/components/conversation/MessageComposer.vue frontend/src/components/NewConversationModal.vue frontend/src/components/conversation/__tests__/composerSuggestions.spec.ts ROADMAP.md
git commit -m "[UI] Realçar menções e mostrar dica de argumentos no campo"
```

---

### Tarefa 10: comando como balão no histórico

Item 10 do marco 13. É independente das tarefas de frontend e pode rodar em qualquer ordem depois da Tarefa 1.

**Arquivos:**
- Modificar: `backend/vibing/conversation.py` (`_classify_user_text`, por volta da L770, e a regex nova `_COMMAND_ARGS`)
- Teste: `backend/tests/test_conversation_history.py`; ajustar `backend/tests/test_digest_condense.py`

**Interfaces:**
- Produz: `_classify_user_text("<command-name>/hello</command-name>…<command-args>Vinicius</command-args>")` devolve `("/hello Vinicius", None)`. Sem argumentos, devolve `("/hello", None)`. `<local-command-stdout>` continua virando aviso.

- [x] **Passo 1: testes que falham.** Em `test_conversation_history.py`, troque a expectativa de `test_cli_tags_become_notices_or_are_dropped` (primeira linha: `("user", "/commit")` em vez de `("notice", "Comando /commit")`) e acrescente:

```python
def test_command_with_arguments_becomes_the_user_bubble():
    builder = ConversationBuilder()
    builder.load_history([
        user_entry("<command-message>hello</command-message>\n<command-name>/hello</command-name>"
                   "\n<command-args>Vinicius</command-args>"),
    ])
    assert [(i["type"], i["text"]) for i in builder.snapshot()] == [("user", "/hello Vinicius")]


def test_builtin_command_output_is_still_a_notice():
    builder = ConversationBuilder()
    builder.load_history([
        user_entry("<command-name>/model</command-name>\n<command-message>model</command-message>"
                   "\n<command-args></command-args>"),
        user_entry("<local-command-stdout>Set model to haiku</local-command-stdout>"),
    ])
    assert [(i["type"], i["text"]) for i in builder.snapshot()] == [
        ("user", "/model"),
        ("notice", "Set model to haiku"),
    ]
```

Em `test_digest_condense.py`, `test_condense_formats_each_kind` passa a esperar `"[Você] /model"` entre `[Bash] pytest (falhou)` e `[Você] Agora ajuste o menu`, e `out.count == 6`. Confira em `condense` como o `count` é calculado antes de mudar o número.

- [x] **Passo 2: rodar e ver falhar.** Rode `uv run pytest backend/tests/test_conversation_history.py backend/tests/test_digest_condense.py -q`.

- [x] **Passo 3: implementar.** Em `conversation.py`:

```python
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
```

E em `_classify_user_text`, troque o bloco de `_COMMAND_NAME`:

```python
    match = _COMMAND_NAME.search(text)
    if match:
        name = match.group(1).strip()
        args = _COMMAND_ARGS.search(text)
        arguments = args.group(1).strip() if args else ""
        return (f"{name} {arguments}" if arguments else name), None
```

Se `name` vier vazio, o texto também fica vazio e nada aparece. Isso é aceitável, porque o CLI sempre grava o nome.

- [x] **Passo 4: rodar e ver passar.** Rode `uv run pytest -q`. Procure com `grep -rn "Comando /" backend frontend/src` outros testes ou textos que esperavam o aviso antigo e ajuste os que forem só expectativa de teste.

- [x] **Passo 5: commit** (sessão principal, depois do `reviewer`). Marque o item 10 no roadmap.

```bash
git add backend/vibing/conversation.py backend/tests/test_conversation_history.py backend/tests/test_digest_condense.py ROADMAP.md
git commit -m "[Feat] Mostrar comando rodado como balão do usuário no histórico"
```

---

### Tarefa 11: verificação manual contra o SDK real e no app

Item 11 do marco 13. Quem faz é a sessão principal, com o usuário, depois das Tarefas 1 a 10.

**Arquivos:**
- Criar: `scripts/commands_smoke.py`

- [ ] **Passo 1: script.** Siga o molde de `scripts/sdk_smoke.py`: remova as variáveis `CLAUDE*` do ambiente com `clean_inherited_env()`.

```python
"""Manual check of the command catalog against the real SDK (only connects: no prompt,
no model call, no session file). Run from the repository root:

    uv run python scripts/commands_smoke.py [folder]
"""

import asyncio
import sys
from pathlib import Path

from vibing.agent.sdk_client import clean_inherited_env
from vibing.commands import CommandCatalog
from vibing.sessions import default_agent_factory


async def main() -> None:
    clean_inherited_env()
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    commands = await CommandCatalog(default_agent_factory).list(folder)
    names = [c.name for c in commands]
    print(f"{len(names)} comandos em {folder}")
    for wanted in ("commit", "superpowers:brainstorming"):
        print(f"  {wanted}: {'ok' if wanted in names else 'FALTANDO'}")


asyncio.run(main())
```

- [ ] **Passo 2: rodar** `uv run python scripts/commands_smoke.py` na raiz da worktree. Esperado: mais de 50 comandos, com `commit` e `superpowers:brainstorming` marcados como `ok`. Confira que nenhum hook `SessionStart` rodou: nenhum efeito colateral dos hooks do usuário, e nenhum arquivo novo de sessão em `~/.claude/projects/<pasta da worktree>/`, comparando a listagem antes e depois.

- [ ] **Passo 3: no app** (backend e frontend rodando, projeto de teste numa pasta temporária com `.claude/commands/hello.md`):
  - `/hel` + Enter insere `/hello `, com a dica de argumentos se houver. Enviar `/hello Vinicius` roda o comando.
  - Reabrir a conversa mostra o balão `/hello Vinicius`.
  - `@` + termo lista o arquivo. Escolher o arquivo e perguntar sobre ele mostra que o Claude recebeu o conteúdo.
  - O mesmo `/` e `@` no modal de nova conversa.
  - Apague a sessão de teste ao terminar.

- [ ] **Passo 4:** registre o resultado no roadmap (item 11), separando o que rodou do que não deu para conferir. Faça o commit:

```bash
git add scripts/commands_smoke.py ROADMAP.md
git commit -m "[Test] Adicionar teste manual do catálogo de comandos"
```

---

### Tarefa 12: padrões de modelo, raciocínio e modo nas Preferências

Item 12 do marco 13. O usuário pediu em 2026-09-30, e o pedido não está na spec de comandos. Desenho curto decidido neste plano:

- As Preferências (aba Geral) ganham três opções para as conversas novas: **Modelo**, **Raciocínio** e **Modo**. Cada uma tem a opção "Padrão", que vale `null` e deixa a decisão como está hoje: o modelo e o raciocínio do CLI, e o `defaultMode` do `settings.json` do usuário para o modo.
- Os valores ficam em `app_state["preferences"]`, nas chaves `new_session_model`, `new_session_effort` e `new_session_mode`. O backend valida:
  - modelo: texto de 1 a 100 caracteres, ou `null`;
  - raciocínio: um de `EFFORTS`, ou `null`;
  - modo: um de `PERMISSION_MODES` **menos** `bypassPermissions`, ou `null`. `bypassPermissions` continua exigindo confirmação por sessão.
  - Um valor inválido dá 400 com mensagem em português.
- **Quem aplica é o backend.** `SessionManager.create_session` lê as preferências na mesma conexão e grava `model`, `effort` e `permission_mode` no registro novo. Assim vale para toda sessão nova: pelo modal, pela tela do projeto ou por qualquer outro caminho.
  - Ordem do modo: preferência salva, depois o `defaultMode` do CLI, depois `None`.
  - Uma preferência ilegível (JSON quebrado, tipo errado) é ignorada, e a sessão nasce como hoje.
- **Modal de nova conversa:** quando um campo do rascunho está `null`, o botão mostra o valor da preferência (ex.: "Opus", "Raciocínio alto") em vez de "Padrão", porque é isso que a sessão vai usar. Escolher outro valor no modal continua valendo só para aquela conversa (PATCH, como hoje).
- O Detalhes e o campo da conversa já mostram o que está no registro, então não mudam.

**Arquivos:**
- Modificar: `backend/vibing/api/app_state.py` (validação das três chaves)
- Modificar: `backend/vibing/sessions.py` (`create_session` e uma função `new_session_defaults(conn) -> tuple[str | None, str | None, str | None]`)
- Modificar: `frontend/src/components/preferences/GeneralPreferences.vue`
- Modificar: `frontend/src/components/NewConversationModal.vue` (texto dos botões com a preferência)
- Teste: `backend/tests/test_new_session_defaults.py` (novo), `frontend/src/components/preferences/__tests__/` (o arquivo de teste existente de `GeneralPreferences`) e `frontend/src/components/__tests__/NewConversationModalExtras.spec.ts`

**Interfaces:**
- Produz: `new_session_defaults(conn: sqlite3.Connection) -> tuple[str | None, str | None, str | None]` em `sessions.py`, que devolve `(model, effort, mode)` já validados.

- [ ] **Passo 1: testes do backend que falham** em `backend/tests/test_new_session_defaults.py`. Use o `api` com `FakeAgentFactory` de `test_sessions_api.py` como modelo:

```python
"""Preferences for new sessions: model, effort and mode."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"


@pytest.fixture
def api():
    app = create_app(agent_factory=FakeAgentFactory(), history_exists=lambda sid, cwd: False)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as c:
        yield c


def project(api: TestClient, home: Path) -> int:
    (home / "app").mkdir()
    r = api.post("/api/projects", json={"name": "app", "path": str(home / "app"), "color": "#ff8800"})
    return r.json()["id"]


def test_new_sessions_use_the_saved_defaults(api, home):
    pid = project(api, home)
    r = api.put("/api/state/preferences", json={
        "new_session_model": "opus", "new_session_effort": "high", "new_session_mode": "acceptEdits",
    })
    assert r.status_code == 200
    s = api.post(f"/api/projects/{pid}/sessions").json()
    assert (s["model"], s["effort"], s["permission_mode"]) == ("opus", "high", "acceptEdits")


def test_without_defaults_sessions_start_as_before(api, home, monkeypatch):
    monkeypatch.setattr("vibing.sessions.user_default_permission_mode", lambda: "plan")
    pid = project(api, home)
    s = api.post(f"/api/projects/{pid}/sessions").json()
    assert (s["model"], s["effort"], s["permission_mode"]) == (None, None, "plan")


@pytest.mark.parametrize("body", [
    {"new_session_model": ""},
    {"new_session_model": "x" * 101},
    {"new_session_effort": "turbo"},
    {"new_session_mode": "bypassPermissions"},
    {"new_session_mode": "qualquer"},
])
def test_invalid_defaults_are_refused(api, body):
    assert api.put("/api/state/preferences", json=body).status_code == 400


def test_null_defaults_are_accepted(api):
    body = {"new_session_model": None, "new_session_effort": None, "new_session_mode": None}
    assert api.put("/api/state/preferences", json=body).status_code == 200
```

Confira duas coisas antes de escrever:
- **`SessionOut`:** se não expõe `model`, `effort` e `permission_mode` com esses nomes, ajuste as asserções ao nome real.
- **`default_permission_mode`:** se o `SessionManager` recebe esse parâmetro em vez de ler `vibing.sessions.user_default_permission_mode` na hora, faça o monkeypatch no lugar certo. O `__init__` usa `default_permission_mode or user_default_permission_mode`, então o nome do módulo é lido na construção: aplique o monkeypatch **antes** de `create_app`, ou passe pela fixture.

- [ ] **Passo 2: rodar e ver falhar.**

- [ ] **Passo 3: implementar o backend.**
  - Em `app_state.py`, junto das outras validações de `preferences`:
    - `new_session_model`: `None`, ou `str` com `1 <= len <= 100` depois de `strip()`.
    - `new_session_effort`: `None` ou um de `sessions.EFFORTS`.
    - `new_session_mode`: `None` ou um de `sessions.PERMISSION_MODES` diferente de `"bypassPermissions"`.
    - Mensagens: "O modelo padrão precisa ser um texto de até 100 caracteres.", "Raciocínio padrão inválido." e "Modo padrão inválido.".
  - Em `sessions.py`, `new_session_defaults(conn)`: lê a linha `preferences` de `app_state`, faz `json.loads` protegido e aplica as mesmas regras. Um valor fora da regra vira `None`.
  - Em `create_session`: dentro do `with closing(db.connect(...))`, antes do `INSERT`, chame `new_session_defaults(conn)`. Monte o registro com `model`, `effort` e `permission_mode = mode or self._default_permission_mode()`. Acrescente `model` e `effort` ao `INSERT`, conferindo que as colunas existem em `sessions` (existem: `record.model` e `record.effort` são gravados pelo PATCH). Como o `record` hoje é criado antes do `with`, reorganize para ler as preferências primeiro.

- [ ] **Passo 4: testes do frontend que falham.**
  - **`GeneralPreferences`:** três `OptionMenu` (ou `select`) com `data-test="pref-new-model"`, `pref-new-effort` e `pref-new-mode`.
    - Carregar preenche com o que veio de `getAppState`.
    - Salvar manda as três chaves no `PUT /api/state/preferences` junto das que já existem.
    - "Padrão" manda `null`.
    - O modo não oferece "Ignorar permissões" (use `SELECTABLE_MODES` de `sessionOptions.ts`).
    - A lista de modelos vem de `useModelsStore` (como no modal).
  - **`NewConversationModalExtras.spec.ts`:** com `GET /api/state` devolvendo `{ preferences: { new_session_model: 'opus', new_session_effort: 'high' } }` e o rascunho vazio, o botão de modelo mostra o `displayName` de `opus` e o de raciocínio mostra "Raciocínio" seguido de `EFFORT_LABELS.high`. Escolher outro modelo no modal mostra o escolhido.

- [ ] **Passo 5: implementar o frontend.** O modal chama `getAppState()` ao abrir (junto com `models.ensure()`), guarda as três preferências num `ref` e usa essas preferências nos textos `modelText`, de raciocínio e de modo quando o rascunho está `null`. O `submit` não muda: o backend já aplica a preferência.

- [ ] **Passo 6: rodar e ver passar.** Rode `uv run pytest -q`, `pnpm --dir frontend test` e `pnpm --dir frontend build`.

- [ ] **Passo 7: commit** (sessão principal, depois do `reviewer`). Marque o item 12 no roadmap e registre a decisão na tabela "Decisões": as preferências de sessão nova valem sobre o `defaultMode` do CLI quando há valor salvo.

```bash
git add backend/vibing/api/app_state.py backend/vibing/sessions.py backend/tests/test_new_session_defaults.py frontend/src/components/preferences/GeneralPreferences.vue frontend/src/components/NewConversationModal.vue frontend/src/components/preferences/__tests__ frontend/src/components/__tests__/NewConversationModalExtras.spec.ts ROADMAP.md
git commit -m "[Feat] Guardar modelo, raciocínio e modo padrão das conversas novas"
```

---

### Tarefa 13: botão de copiar em blocos de código

Item 13 do marco 13. O usuário pediu em 2026-09-30, e o pedido não está na spec de comandos. É independente das outras tarefas.

**Desenho:**
- Cada bloco de código cercado (```` ``` ````) renderizado por `renderMarkdown` fica dentro de um `<div class="code-block">`. No canto superior direito aparece um botão "Copiar" (`data-code-copy`, `aria-label="Copiar código"`), que copia só o código daquele bloco.
- Vale onde `renderMarkdown` é usado: as respostas (`TextBlock.vue`) e o plano (`PlanCard.vue`).
- O botão fica visível ao passar o mouse sobre o bloco, com foco pelo teclado e em telas sem mouse, no mesmo padrão do botão "Copiar" da resposta.
- Depois do clique, o texto do botão vira "Copiado" por 1,5 s. Se a cópia falhar, vira "Não foi possível copiar".

**Arquivos:**
- Modificar: `frontend/src/conversation/markdown.ts`
- Criar: `frontend/src/conversation/codeCopy.ts` (tratador de clique delegado)
- Modificar: `frontend/src/components/conversation/TextBlock.vue` e `frontend/src/components/conversation/PlanCard.vue` (`@click` no contêiner do `v-html`)
- Modificar: `frontend/src/style.css` (estilo de `.code-block` e `.code-copy` junto das regras de `.markdown`)
- Teste: `frontend/src/conversation/__tests__/markdown.spec.ts` (acrescentar), `frontend/src/conversation/__tests__/codeCopy.spec.ts` (novo) e `frontend/src/components/conversation/__tests__/` (teste de `TextBlock`)

**Interfaces:**
- Produz: `onCodeCopyClick(event: MouseEvent): Promise<void>` em `codeCopy.ts`. Quando o alvo está dentro de `[data-code-copy]`, a função copia o `textContent` do `pre code` do mesmo `.code-block` e atualiza o texto do botão. Nos outros casos, não faz nada.

**Atenção:** a função `highlight` do markdown-it só é usada sem embrulho quando o retorno começa com `<pre`. Por isso o embrulho **não** vai em `highlight`: sobrescreva `md.renderer.rules.fence`, chamando a regra padrão e envolvendo o resultado.

```ts
const defaultFence = md.renderer.rules.fence!
md.renderer.rules.fence = (tokens, idx, options, env, self) =>
  `<div class="code-block"><button type="button" class="code-copy" data-code-copy aria-label="Copiar código">Copiar</button>${defaultFence(tokens, idx, options, env, self)}</div>`
```

- [x] **Passo 1: testes que falham.**
  - **`markdown.spec.ts`:** `renderMarkdown('```py\nx = 1\n```')` contém exatamente um `.code-block` com um `button[data-code-copy]` e o `pre`. Código inline (`` `x` ``) não ganha botão. Um bloco sem linguagem também ganha.
  - **`codeCopy.spec.ts`:** monte um `div` com `innerHTML = renderMarkdown('```js\nconst a = "<b>"\n```')`. Com `navigator.clipboard.writeText` substituído por `vi.fn()` (via `Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })`), disparar `onCodeCopyClick` com o botão como alvo faz três coisas: chama `writeText` com `const a = "<b>"\n` (o texto cru, sem tags do realce), troca o texto do botão para "Copiado" e, com timers falsos, volta a "Copiar" depois de 1,5 s. Se `writeText` rejeitar, o botão mostra "Não foi possível copiar". Um clique fora do botão não chama `writeText`.
  - **`TextBlock`:** montar com texto que tem bloco de código e clicar em `[data-code-copy]` chama `writeText` com o código, não com a resposta inteira.

  Confira se o `textContent` de `pre code` inclui o `\n` final que o markdown-it deixa. Se incluir, mantenha-o como está, porque é o que o usuário espera colar.

- [x] **Passo 2: rodar e ver falhar.**
- [x] **Passo 3: implementar.** Aplique a regra `fence` acima e crie `codeCopy.ts`, guardando um timer por botão num `WeakMap`. Em `TextBlock.vue` e `PlanCard.vue`, ponha `@click="onCodeCopyClick"` no `div` do `v-html`. No `style.css`, use `.code-block { position: relative }`. O `.code-copy` fica absoluto no topo à direita, com fonte pequena, borda `line-strong`, fundo `panel`, `opacity: 0` e `opacity: 1` em `.code-block:hover`, em `:focus-visible` e em `@media (hover: none)`.
- [x] **Passo 4: rodar e ver passar.** Rode os arquivos, `pnpm --dir frontend test` e `pnpm --dir frontend build`.
- [x] **Passo 5: commit** (sessão principal, depois do `reviewer`). Marque o item 13 no roadmap.

```bash
git add frontend/src/conversation/markdown.ts frontend/src/conversation/codeCopy.ts frontend/src/components/conversation/TextBlock.vue frontend/src/components/conversation/PlanCard.vue frontend/src/style.css frontend/src/conversation/__tests__ frontend/src/components/conversation/__tests__ ROADMAP.md
git commit -m "[Feat] Adicionar botão de copiar nos blocos de código"
```

---

Depois das Tarefas 1 a 13, `milestone-reviewer` no marco 13 inteiro. Com aprovação, o marco passa a "Concluído" no roadmap.
