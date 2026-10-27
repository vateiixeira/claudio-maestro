#!/usr/bin/env python3
"""Backend descartável para os testes E2E do frontend (Playwright).

Cria um diretório temporário, aponta home, dados e conversas para dentro dele, semeia
projetos e conversas gravadas e serve o frontend compilado numa porta própria (6620 por
padrão quando chamado à mão; `MAESTRO_E2E_PORT` troca). O Playwright (`pnpm --dir frontend e2e`)
escolhe uma porta de 6620 a 6659 por worktree e a passa por essa variável. Nada toca em
`~/.claude`, no banco real ou no SDK.

    uv run python scripts/e2e_server.py
"""

import asyncio
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI

from claudio_maestro import cli, db, gitinfo, projects
from claudio_maestro.agent.base import AgentClient, AgentError, AgentOptions
from claudio_maestro.claudecli import ClaudeCliResolver, CommandResult
from claudio_maestro.config import (
    DEFAULT_BACKEND_PORT,
    DEFAULT_DEV_PORT,
    PortError,
    app_ports,
    load_settings,
    validate_port,
)
from claudio_maestro.digest.model import DigestModelError, DigestRequest
from claudio_maestro.runmode import RunMode
from claudio_maestro.specialists import store as specialist_store
from claudio_maestro.specialists.files import SpecialistFiles
from claudio_maestro.updates import ReleaseInfo
from claudio_maestro.usage import UsageReport

DEFAULT_PORT = 6620
PREVIEW_PORT = 6610
# Ports of the user's services and of the worktree preview; the E2E server never takes them.
RESERVED_PORTS = frozenset({DEFAULT_BACKEND_PORT, DEFAULT_DEV_PORT, PREVIEW_PORT})

# The scenario the specs in frontend/e2e/ expect. Change both sides together.
SCENARIO = [
    {
        "name": "Loja Demo",
        "slug": "loja-demo",
        "color": "#2f81f7",
        "conversations": [
            {
                "prompt": "Explique a estrutura do projeto",
                "reply": "O projeto tem uma pasta src com o código da loja.",
            },
            {
                "prompt": "Liste as tarefas pendentes",
                "reply": "Não há tarefas pendentes.",
            },
            {
                # Three `Agent` calls in the same answer; the specs read their model chips.
                # "model" goes in the subagent's transcript, "meta_model" in its meta file.
                "prompt": "Investigue o módulo de pagamentos",
                "reply": "Os três subagentes terminaram.",
                "subagents": [
                    {"description": "Mapear as rotas", "model": "claude-sonnet-5-5"},
                    {"description": "Ler os testes", "meta_model": "haiku"},
                    {"description": "Conferir a documentação"},
                ],
            },
        ],
    },
    {
        "name": "Painel Demo",
        "slug": "painel-demo",
        "color": "#3fb950",
        "conversations": [
            {
                "prompt": "Resuma o último commit",
                "reply": "O último commit ajusta o gráfico semanal.",
            },
            {
                # The phrase of the content search: in the middle of an answer, followed by many
                # short turns so that the page has to scroll to reach it.
                "prompt": "Como configuro a jornada do funil?",
                "reply": (
                    "Na jornada do funil você monta uma regra assim:\n\n"
                    "Se o card não responder:\n\n"
                    "Se a pessoa não responder, o sistema cria uma tarefa automaticamente "
                    "para o responsável do card."
                ),
                "filler_turns": 20,
            },
            {
                # More than the 500 items the chat loads: the term lives only in the first turn,
                # which is out of the loaded stretch (the "find-missed" notice).
                "prompt": "Registre o código xilofone-arquivado no histórico antigo",
                "reply": "Registrado.",
                "filler_turns": 260,
            },
        ],
    },
]


# Git projects the specs in frontend/e2e/git-*.e2e.ts expect. Each one is used by one spec
# only, because the specs change them (commit, merge, push) and the server lives for the run.
GIT_SCENARIO = [
    {"name": "Histórico Demo", "slug": "historico-demo", "color": "#d29922", "git": "history"},
    {"name": "Alterações Demo", "slug": "alteracoes-demo", "color": "#a371f7", "git": "changes"},
    {"name": "Merge Demo", "slug": "merge-demo", "color": "#3fb950", "git": "merge"},
    {"name": "Sincronia Demo", "slug": "sincronia-demo", "color": "#58a6ff", "git": "sync"},
    {"name": "Ramos Demo", "slug": "ramos-demo", "color": "#f0883e", "git": "branches"},
]


# The agent the "Agentes" and Inbox specs expect (seeded by `_seed_specialists`).
TRIAGEM_PROJECT = "Loja Demo"
TRIAGEM_FAILURE_REASON = "O token do repositório expirou."
TRIAGEM_ALERT_TEXT = "A Triagem falhou nas últimas execuções."
TRIAGEM_SUMMARY_TEXT = "Triagem concluída: 3 itens novos."
TRIAGEM_SKILL = """---
name: Triagem
description: Separa os chamados novos por urgência e responde os simples.
---

# Triagem

1. Leia os chamados abertos desde a última execução.
2. Marque como urgentes os que citam queda ou cobrança em duplicidade.
3. Responda os pedidos simples e deixe o resto para uma pessoa.
"""


class E2EError(Exception):
    """A problem explained to the user (in Portuguese)."""


def check_same_checkout() -> None:
    """Refuse to run when the installed `claudio_maestro` serves another checkout.

    The server compiles and serves the frontend of `cli.REPO_ROOT`; started from a worktree
    whose `uv run` resolves to the main checkout, it would test the wrong code.
    """
    script_root = Path(__file__).resolve().parents[1]
    if Path(cli.REPO_ROOT).resolve() != script_root:
        raise E2EError(
            "O servidor de E2E foi chamado de um checkout diferente do que o `claudio_maestro` "
            f"instalado serve ({cli.REPO_ROOT} em vez de {script_root}). "
            "Rode `uv run` de dentro da pasta do script."
        )


def e2e_port(environ: Mapping[str, str]) -> int:
    raw = environ.get("MAESTRO_E2E_PORT") or str(DEFAULT_PORT)
    try:
        port = validate_port(raw, "MAESTRO_E2E_PORT")
    except PortError as exc:
        raise E2EError(str(exc)) from exc
    if port in RESERVED_PORTS:
        raise E2EError(
            f"A porta {port} é dos serviços ou do preview. Escolha outra em MAESTRO_E2E_PORT."
        )
    return port


def isolated_env(base: Mapping[str, str], root: Path, port: int) -> dict[str, str]:
    """`base` without anything of the app or of the Claude CLI, pointed at `root`."""
    env = {
        key: value
        for key, value in base.items()
        if not key.startswith(("MAESTRO_", "CLAUDE", "GIT_CONFIG", "GH_", "GITHUB_")) and key != "XDG_CONFIG_HOME"
    }
    env.update(
        {
            "HOME": str(root / "home"),
            "MAESTRO_HOME": str(root / "home"),
            "MAESTRO_DATA_DIR": str(root / "data"),
            "CLAUDE_CONFIG_DIR": str(root / "claude-config"),
            "MAESTRO_PORT": str(port),
            "MAESTRO_AGENTD": "0",
            "MAESTRO_REMOTE_RECONNECT": "0",
            "MAESTRO_E2E_CHAT": "1" if base.get("MAESTRO_E2E_CHAT") == "1" else "0",
            # Only the opt-in fake chat harness may start queued work. An
            # inherited dispatcher override never leaks into this environment.
            "MAESTRO_WORK_DISPATCHER": "1" if base.get("MAESTRO_E2E_CHAT") == "1" else "0",
            "MAESTRO_UPDATE_CHECK": "0",
            "MAESTRO_USAGE_CHECK": "0",
            "MAESTRO_CLAUDE_CHECK": "0",
            # The personal git config stays out because of the fake HOME (no ~/.gitconfig) and the
            # dropped XDG_CONFIG_HOME. This variable does not reach the server's git: `run_git`
            # removes every GIT_* variable, so /etc/gitconfig still applies there (SAFE_CONFIG
            # neutralises what matters). It only covers git run directly from this process.
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return env


def _history_folder(projects_dir: Path, project_dir: Path) -> Path:
    """Where the CLI keeps the conversations of `project_dir` (non-alphanumerics become `-`)."""
    return projects_dir / re.sub(r"[^a-zA-Z0-9]", "-", str(project_dir))


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _write_subagents(
    session_file: Path, subagents: list[dict[str, str]], started: datetime
) -> list[str]:
    """Write the files the CLI keeps next to a session for its subagents and return the id of
    the `Agent` call of each one: `<session>/subagents/agent-<n>.meta.json` and `.jsonl`."""
    folder = session_file.parent / session_file.stem / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    tool_use_ids = []
    for number, subagent in enumerate(subagents, start=1):
        tool_use_id = f"toolu_e2e_agent_{number}"
        tool_use_ids.append(tool_use_id)
        meta = {
            "agentType": "Explore", "description": subagent["description"],
            "toolUseId": tool_use_id,
        }
        if "meta_model" in subagent:
            meta["model"] = subagent["meta_model"]
        (folder / f"agent-e2e{number}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        lines = [
            {
                "type": "user", "isSidechain": True, "timestamp": _stamp(started),
                "message": {"role": "user", "content": subagent["description"]},
            }
        ]
        if "model" in subagent:
            lines.append(
                {
                    "type": "assistant", "isSidechain": True,
                    "timestamp": _stamp(started + timedelta(seconds=2)),
                    "message": {
                        "role": "assistant", "model": subagent["model"],
                        "content": [{"type": "text", "text": "Feito."}],
                    },
                }
            )
        (folder / f"agent-e2e{number}.jsonl").write_text(
            "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
            encoding="utf-8",
        )
    return tool_use_ids


def _write_conversation(
    folder: Path, project_dir: Path, prompt: str, reply: str, started: datetime,
    subagents: list[dict[str, str]] | None = None, filler_turns: int = 0,
) -> None:
    """A minimal transcript: one user message and one assistant answer. With `subagents`, the
    answer first calls an `Agent` for each one (with its result) and the files of the subagents
    are written next to the session. With `filler_turns`, that many short question and answer
    turns follow the answer."""
    session_id, user_id, assistant_id = (str(uuid.uuid4()) for _ in range(3))
    folder.mkdir(parents=True, exist_ok=True)
    session_file = folder / f"{session_id}.jsonl"
    base = {"isSidechain": False, "sessionId": session_id, "cwd": str(project_dir)}
    lines = [
        {
            **base, "parentUuid": None, "type": "user", "uuid": user_id,
            "timestamp": _stamp(started),
            "message": {"role": "user", "content": prompt},
        }
    ]
    parent = user_id
    if subagents:
        call_ids = _write_subagents(session_file, subagents, started)
        calls_id, results_id = str(uuid.uuid4()), str(uuid.uuid4())
        lines.append(
            {
                **base, "parentUuid": parent, "type": "assistant", "uuid": calls_id,
                "timestamp": _stamp(started + timedelta(seconds=2)),
                "message": {
                    "id": "msg_e2e_agents", "role": "assistant", "model": "claude-haiku",
                    "content": [
                        {
                            "type": "tool_use", "id": call_id, "name": "Agent",
                            "input": {
                                "description": subagent["description"],
                                "subagent_type": "Explore", "prompt": subagent["description"],
                            },
                        }
                        for call_id, subagent in zip(call_ids, subagents, strict=True)
                    ],
                },
            }
        )
        lines.append(
            {
                **base, "parentUuid": calls_id, "type": "user", "uuid": results_id,
                "timestamp": _stamp(started + timedelta(seconds=4)),
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result", "tool_use_id": call_id,
                            "content": [{"type": "text", "text": "Concluído."}],
                        }
                        for call_id in call_ids
                    ],
                },
            }
        )
        parent = results_id
    lines.append(
        {
            **base, "parentUuid": parent, "type": "assistant", "uuid": assistant_id,
            "timestamp": _stamp(started + timedelta(seconds=5)),
            "message": {
                "role": "assistant", "model": "claude-haiku",
                "content": [{"type": "text", "text": reply}],
            },
        }
    )
    parent = assistant_id
    for number in range(1, filler_turns + 1):
        question_id, answer_id = str(uuid.uuid4()), str(uuid.uuid4())
        moment = started + timedelta(seconds=5 + number * 10)
        lines.append(
            {
                **base, "parentUuid": parent, "type": "user", "uuid": question_id,
                "timestamp": _stamp(moment),
                "message": {"role": "user", "content": f"Continue ({number})"},
            }
        )
        lines.append(
            {
                **base, "parentUuid": question_id, "type": "assistant", "uuid": answer_id,
                "timestamp": _stamp(moment + timedelta(seconds=2)),
                "message": {
                    "role": "assistant", "model": "claude-haiku",
                    "content": [{"type": "text", "text": f"Resposta de enchimento {number}."}],
                },
            }
        )
        parent = answer_id
    session_file.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )


# The seed must not depend on who runs it: no user or system git config (signing, hooks path...).
_GIT_ENV = {"XDG_CONFIG_HOME": None, "GIT_CONFIG_NOSYSTEM": "1"}
_GIT_CONFIG = [("commit.gpgsign", "false")]


def _git(repo: Path, *args: str) -> str:
    """git through the app's own runner (hooks and filters off). Raises E2EError on failure."""
    try:
        code, out, err = asyncio.run(
            gitinfo.run_git(repo, *args, timeout=30, env=_GIT_ENV, config=_GIT_CONFIG)
        )
    except gitinfo.GitError as exc:
        raise E2EError(f"git {args[0]} falhou ao preparar {repo.name}: {exc}") from exc
    if code != 0:
        raise E2EError(f"git {args[0]} falhou ao preparar {repo.name}: {err.strip()}")
    return out


def _new_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", "Pessoa Demo")
    _git(path, "config", "user.email", "demo@example.com")
    return path


def _commit(repo: Path, name: str, message: str, text: str | None = None) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text if text is not None else f"{message}\n")
    _git(repo, "add", "--", name)
    _git(repo, "commit", "-q", "-m", message)


def _bare(root: Path, name: str) -> Path:
    remotes = root / "remotes"
    remotes.mkdir(exist_ok=True)
    bare = remotes / f"{name}.git"
    _git(remotes, "init", "-q", "--bare", "-b", "main", str(bare))
    return bare


def _seed_history(project_dir: Path, root: Path) -> None:
    """`api`: 35 commits on main, 2 not pushed, 1 on the remote to pull, branch feat/relatorios.
    `web`: 3 commits and no remote."""
    bare = _bare(root, "historico-api")
    api = _new_repo(project_dir / "api")
    for number in range(1, 34):
        _commit(api, f"rotas/rota{number}.txt", f"Ajustar a rota {number}")
    _git(api, "remote", "add", "origin", str(bare))
    _git(api, "push", "-q", "-u", "origin", "main")
    _git(api, "switch", "-q", "-c", "feat/relatorios")
    _commit(api, "relatorio.txt", "Criar o relatório de vendas", "vendas por dia\n")
    _git(api, "switch", "-q", "main")
    for number in (34, 35):
        _commit(api, f"rotas/rota{number}.txt", f"Ajustar a rota {number}")
    other = root / "remotes" / "historico-outro"
    _git(root / "remotes", "clone", "-q", str(bare), str(other))
    _git(other, "config", "user.name", "Outra Pessoa")
    _git(other, "config", "user.email", "outra@example.com")
    _commit(other, "cabecalho.txt", "Corrigir o cabeçalho no remoto")
    _git(other, "push", "-q", "origin", "main")
    _git(api, "fetch", "-q", "origin")
    web = _new_repo(project_dir / "web")
    for number in range(1, 4):
        _commit(web, f"pagina{number}.html", f"Montar a página {number}")


def _seed_changes(project_dir: Path, root: Path) -> None:
    """One repository (the project folder itself): two modified files and one new one."""
    repo = _new_repo(project_dir)
    _commit(repo, "README.md", "Criar o leia-me", "# Loja\n")
    _commit(repo, "src/carrinho.ts", "Criar o carrinho", "export const total = 0\n")
    (repo / "README.md").write_text("# Loja\n\nComo rodar.\n")
    (repo / "src" / "carrinho.ts").write_text("export const total = 10\n")
    (repo / "src" / "cupom.ts").write_text("export const cupom = 'NATAL'\n")


def _seed_merge(project_dir: Path, root: Path) -> None:
    """One repository. `feat/cupom` conflicts with main in src/frete.ts (with markers);
    `feat/limpeza` deletes docs/antigo.md, which main changed (a conflict without markers, so
    the E2E can mark it resolved without editing files); `feat/docs` merges clean."""
    repo = _new_repo(project_dir)
    _commit(repo, "src/frete.ts", "Criar o frete", "export const frete = 10\n")
    _commit(repo, "docs/antigo.md", "Criar a página antiga", "# Antigo\n")
    _git(repo, "switch", "-q", "-c", "feat/limpeza")
    _git(repo, "rm", "-q", "--", "docs/antigo.md")
    _git(repo, "commit", "-q", "-m", "Apagar a página antiga")
    _git(repo, "switch", "-q", "-c", "feat/cupom", "main")
    _commit(repo, "src/frete.ts", "Dar desconto no frete com cupom", "export const frete = 5\n")
    _git(repo, "switch", "-q", "-c", "feat/docs", "main")
    _commit(repo, "docs/frete.md", "Documentar o frete", "# Frete\n")
    _git(repo, "switch", "-q", "main")
    _commit(repo, "src/frete.ts", "Subir o frete fixo", "export const frete = 12\n")
    _commit(repo, "docs/antigo.md", "Revisar a página antiga", "# Antigo, revisado\n")


def _seed_sync(project_dir: Path, root: Path) -> None:
    """`loja`: 1 commit to send and 1 to pull, no conflict. `site`: a branch never published."""
    bare = _bare(root, "sincronia-loja")
    loja = _new_repo(project_dir / "loja")
    _commit(loja, "README.md", "Criar a loja", "# Loja\n")
    _git(loja, "remote", "add", "origin", str(bare))
    _git(loja, "push", "-q", "-u", "origin", "main")
    other = _new_repo(root / "outro-clone-loja")
    _git(other, "remote", "add", "origin", str(bare))
    _git(other, "fetch", "-q", "origin")
    _git(other, "reset", "-q", "--hard", "origin/main")
    _commit(other, "frete.md", "Documentar o frete", "frete\n")
    _git(other, "push", "-q", "origin", "main")
    _git(loja, "fetch", "-q", "origin")
    _commit(loja, "carrinho.md", "Documentar o carrinho", "carrinho\n")

    site_bare = _bare(root, "sincronia-site")
    site = _new_repo(project_dir / "site")
    _commit(site, "index.html", "Criar o site", "<h1>Loja</h1>\n")
    _git(site, "remote", "add", "origin", str(site_bare))
    _git(site, "push", "-q", "-u", "origin", "main")
    _git(site, "switch", "-q", "-c", "feat/nova")
    _commit(site, "nova.html", "Criar a página nova", "<p>nova</p>\n")


def _seed_branches(project_dir: Path, root: Path) -> None:
    """Three repositories (`api`, `docs`, `web`) and one conversation, to read the Branch line of
    Detalhes: only the first repository shows until the toggle is clicked."""
    for name in ("api", "docs", "web"):
        _commit(_new_repo(project_dir / name), "README.md", f"Criar {name}", f"# {name}\n")
    settings = load_settings()
    cwd = project_dir.resolve()
    _write_conversation(
        _history_folder(settings.claude_projects_dir, cwd), cwd,
        "Confira os ramos dos repositórios", "Os três repositórios estão na main.",
        datetime.now(UTC) - timedelta(hours=3),
    )


GIT_SEEDERS = {
    "history": _seed_history, "changes": _seed_changes, "merge": _seed_merge, "sync": _seed_sync,
    "branches": _seed_branches,
}


def seed_git(root: Path, home: Path, conn) -> None:
    for entry in GIT_SCENARIO:
        project_dir = home / "projetos" / entry["slug"]
        if not project_dir.resolve().is_relative_to(root):
            raise E2EError(f"A pasta {project_dir} está fora de {root}; nada foi gravado.")
        project_dir.mkdir(parents=True, exist_ok=True)
        GIT_SEEDERS[entry["git"]](project_dir, root)
        projects.create_project(
            conn, name=entry["name"], path=str(project_dir), color=entry["color"], home=home
        )


def _seed_specialists(settings, conn, now: datetime) -> None:
    """Seed the "Triagem" agent (with a skill, a schedule, two runs and two notices), so the
    Agentes page and the Inbox have something to show. Everything goes under the temporary
    data folder: no route creates notices, only the service during a run."""
    stamp = int(now.timestamp())
    project = next(p for p in projects.list_projects(conn) if p.name == TRIAGEM_PROJECT)
    files = SpecialistFiles(settings.data_dir / "specialists")
    files.create("triagem", "Triagem")
    files.write_skill("triagem", TRIAGEM_SKILL)
    agent = specialist_store.create_specialist(
        conn, slug="triagem", name="Triagem", project_id=project.id, now=stamp
    )
    specialist_store.replace_schedules(conn, agent.id, [("12345", "03:00")], stamp)
    for hours_ago, outcome, reason in ((26, "concluded", None), (2, "failed", TRIAGEM_FAILURE_REASON)):
        started = stamp - hours_ago * 3600
        specialist_store.insert_run(
            conn, specialist_id=agent.id, trigger="schedule", started_at=started,
            scheduled_for=started, outcome=outcome, reason=reason, ended_at=started + 120,
        )
    specialist_store.add_notice(
        conn, specialist_id=agent.id, session_id=None, kind="alert",
        text=TRIAGEM_ALERT_TEXT, now=stamp - 3600,
    )
    summary = specialist_store.add_notice(
        conn, specialist_id=agent.id, session_id=None, kind="summary",
        text=TRIAGEM_SUMMARY_TEXT, now=stamp - 25 * 3600,
    )
    specialist_store.mark_notices_read(conn, [summary.id], stamp - 24 * 3600)
    specialist_store.add_announcement(
        conn, specialist_id=agent.id, run_id=None, session_id=None,
        text=TRIAGEM_SUMMARY_TEXT, created_at=stamp - 25 * 3600,
    )


def seed(root: Path) -> None:
    """Create the database, the projects and the conversations of `SCENARIO`, and the git
    projects of `GIT_SCENARIO`.

    Reads the environment (see `isolated_env`) and refuses to write anything when a folder
    it would use is not inside `root`.
    """
    root = root.resolve()
    settings = load_settings()
    projects_dir = settings.claude_projects_dir
    for label, folder in (
        ("home", settings.home_dir),
        ("dados", settings.data_dir),
        ("conversas", projects_dir),
    ):
        if folder is None or not folder.resolve().is_relative_to(root):
            raise E2EError(f"A pasta de {label} ({folder}) está fora de {root}; nada foi gravado.")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(settings.db_path)
    now = datetime.now(UTC)
    with closing(db.connect(settings.db_path)) as conn:
        for position, entry in enumerate(SCENARIO):
            project_dir = settings.home_dir / "projetos" / entry["slug"]
            project_dir.mkdir(parents=True, exist_ok=True)
            project = projects.create_project(
                conn, name=entry["name"], path=str(project_dir), color=entry["color"],
                home=settings.home_dir,
            )
            folder = _history_folder(projects_dir, Path(project.path))
            for index, conversation in enumerate(entry["conversations"]):
                started = now - timedelta(minutes=10 * (position * 3 + index + 1))
                _write_conversation(
                    folder, Path(project.path), conversation["prompt"], conversation["reply"],
                    started, conversation.get("subagents"), conversation.get("filler_turns", 0),
                )
        seed_git(root, settings.home_dir, conn)
        _seed_specialists(settings, conn, now)
        if os.environ.get("MAESTRO_E2E_CHAT") == "1":
            # Dedicated to work-flow.e2e.ts. Existing Git/conversation scenarios
            # keep their own repositories and all their original session counts.
            work_dir = _new_repo(settings.home_dir / "projetos" / "trabalho-demo")
            _commit(work_dir, "contrato.txt", "Registrar contrato de exemplo", "Contrato atual: preservar o comportamento.\n")
            projects.create_project(conn, name="Trabalho Demo", path=str(work_dir), color="#3fb950", home=settings.home_dir)
            collection_dir = settings.home_dir / "projetos" / "coleta-demo"
            collection_dir.mkdir(parents=True, exist_ok=True)
            projects.create_project(conn, name="Coleta Demo", path=str(collection_dir), color="#58a6ff", home=settings.home_dir)


def refuse_agent(options: AgentOptions) -> AgentClient:
    """Agent factory of the E2E app: no feature of the test server may start the real agent."""
    raise AgentError("O servidor de E2E não inicia o agente real.")


class RefusingDigestModel:
    """Digest model of the E2E app: the digest agent never reaches the SDK."""

    async def summarize(self, request: DigestRequest) -> dict:
        raise DigestModelError(
            "O servidor de E2E não inicia o agente de resumos.", stop_pass=True
        )


async def refuse_claude_update(argv: list[str], timeout: float) -> CommandResult:
    """`claude update` of the E2E app: never runs the user's binary."""
    return CommandResult(None, "O servidor de E2E não atualiza o Claude.")


def inert_claude_resolver() -> ClaudeCliResolver:
    """A resolver that finds no `claude` on the system: nothing is executed to look for one."""
    return ClaudeCliResolver(
        env={},
        which=lambda name: None,
        run_version=lambda path: None,
        run_update=refuse_claude_update,
    )


async def _no_release() -> ReleaseInfo | None:
    return None


async def _refuse_usage() -> UsageReport:
    raise RuntimeError("O servidor de E2E não consulta o uso da assinatura.")


async def refuse_gh(args: list[str]) -> tuple[int, str]:
    """No GitHub executable, network, credentials or host config in this server."""
    return 127, ""


async def _no_git_fetch(repo: Path, **kwargs: object) -> bool:
    return False


async def _refuse_editor(argv: list[str]) -> None:
    raise FileNotFoundError("O servidor de E2E não abre o editor.")


async def _refuse_picker(initial: Path) -> str | None:
    return None


def build_app(port: int) -> FastAPI:
    """The app on top of the real frontend build, with every way out switched off.

    Needs the environment of `isolated_env` already applied. `cli.main` is not used because
    it builds the app with the real agent (model refresh, command catalog, agentd, plan sweep,
    digest model, `claude` resolver). Every `create_app` parameter is listed here on purpose:
    `settings` (None: read from the isolated environment), `agent_factory`, `history_exists`,
    `rename_session`, `list_sessions`, `get_session_messages`, `read_tool_results` and
    `session_file` (None: the SDK's file readers, which only read the isolated folders),
    `spawn_editor`, `pick_folder`, `digest_model`, `fetch_release`, `fetch_usage`, `git_fetch`
    and `claude_cli` (refusals or inert fakes), `refresh_models`, `plan_sweep` and `agentd`
    (off), `ports` and `frontend_dir` (this server), `restart` (None: no restart or update
    button), `run_mode` (fixed, reads nothing from the system) and `self_updater` (None: the
    real one, which with `restart=None` refuses before running anything).

    The agents (specialists) need no parameter: their folders live under `MAESTRO_DATA_DIR`
    (inside the temporary root), their sessions go through `agent_factory` and their
    schedules read the usage through `fetch_usage`, so nothing of theirs reaches real data.
    """
    from claude_agent_sdk import TextBlock, ToolUseBlock, UserMessage

    from claudio_maestro.agent.fake import (
        FailStep,
        FakeAgentClient,
        init_message,
        response_messages,
        result_message,
        text_turn,
        tool_result_message,
    )
    from claudio_maestro.app import create_app
    from claudio_maestro.commands import NO_HOOKS
    from claudio_maestro.work.tools import build_tools

    clients: list[FakeAgentClient] = []

    class WorkScenarioClient(FakeAgentClient):
        """Deterministic agent, real WorkService/MCP handlers and normal SDK messages.

        Only this throwaway server constructs it. No test-only endpoint or
        dispatcher path is installed in the production application.
        """

        async def _run_steps(self, steps):
            sid = self.options.session_id
            host = app.state.work
            identity = host.session_identity(sid)
            scenario = Path(self.options.cwd).resolve().name
            scenario_root = load_settings().home_dir / 'projetos'
            if identity is None or scenario not in ('trabalho-demo', 'coleta-demo') or Path(self.options.cwd).resolve().parent != scenario_root.resolve():
                return await super()._run_steps(steps)
            tools = {entry.name: entry for entry in build_tools(host, sid)}

            async def call(name, args):
                tool_id = str(uuid.uuid4())
                await super(WorkScenarioClient, self)._run_steps(response_messages(sid, [
                    ToolUseBlock(id=tool_id, name=f'mcp__maestro_work__{name}', input=args),
                ], stop_reason='tool_use'))
                result = await tools[name].handler(args)
                await super(WorkScenarioClient, self)._run_steps([
                    tool_result_message(tool_id, json.dumps(result, ensure_ascii=False), is_error=result.get('is_error', False)),
                ])
                if result.get('is_error'):
                    raise AgentError(str(result))
                return json.loads(result['content'][0]['text'])

            async def say(text):
                await super(WorkScenarioClient, self)._run_steps(response_messages(sid, [TextBlock(text=text)]))

            try:
                # FakeAgentClient.send prepends the host's exact UUID echo.
                # Preserve that envelope before substituting the response body;
                # never synthesize an acknowledgement from the session identity.
                for step in steps:
                    if not isinstance(step, UserMessage):
                        break
                    await super()._run_steps([step])
                await super()._run_steps([init_message(sid)])
                role = identity['work_role']
                if role == 'coordinator':
                    content = self.sent[-1]
                    if scenario == 'coleta-demo' and isinstance(content, str) and content.startswith('E2E coleta: '):
                        for source in ('sentry', 'kbgen'):
                            await call('collect_source', {'source': source, 'source_instance': 'demo', 'source_project': 'demo', 'query': 'environment:production'})
                        await say('Coletas delegadas. Acompanhe as sessões responsáveis e a fila.')
                    elif isinstance(content, str) and content.startswith('E2E tarefa: '):
                        title = content.removeprefix('E2E tarefa: ').strip()
                        await call('delegate_work', {'title': title, 'objective': title, 'acceptance': 'Conferir contrato.txt, registrar decisão humana e validar por revisão independente.', 'role': 'investigator'})
                        await say('Tarefa delegada a uma investigação própria. Acompanhe o trabalho abaixo.')
                    else:
                        await say('Atualização do trabalho recebida pelo CTO.')
                elif scenario == 'coleta-demo':
                    dossier = host.dossier(identity['work_item_id'])
                    assert dossier['kind'] == 'collection'
                    content = self.sent[-1]
                    if dossier['source'] == 'sentry' and len(self.sent) == 1:
                        await say('O ambiente production não foi encontrado. A fonte informa o alias prd. Qual filtro devo usar para continuar?')
                    else:
                        await call('publish_collection', {'items': [{'external_id': f"demo-{dossier['source']}", 'title': f"Issue demonstrativa {dossier['source']}", 'priority': 'normal', 'source_revision': 'demo-1', 'url': 'https://example.com/issues/demo'}], 'cursor': '', 'next_cursor': None})
                        await say('Coleta concluída com metadados publicados.')
                elif role == 'reviewer':
                    evidence = await call('get_review_evidence', {})
                    assert evidence['target']['complete']
                    assert (Path(self.options.cwd) / 'contrato.txt').read_text().startswith('Contrato atual:')
                    await call('submit_review', {'binding_id': evidence['binding']['id'], 'disposition': 'approve', 'summary': 'Revisão independente: contrato e resposta humana conferidos.', 'evidence': ['contrato.txt:1, alvo completo capturado pelo backend e entrega do autor conferidos.']})
                    await say('Revisão independente aprovada com evidências.')
                else:
                    decisions = host.decisions(item_id=identity['work_item_id'], pending_only=False)['items']
                    answered = next((d for d in decisions if d['answer']), None)
                    await call('declare_workspaces', {'workspaces': [str(self.options.cwd)]})
                    if answered is None:
                        await say('Investigação inicial do contrato: o comportamento atual foi localizado em contrato.txt.')
                        await call('request_decision', {'question': 'Manter o contrato atual nesta investigação?', 'action': 'Preservar somente o comportamento de contrato.txt; sem publicação.', 'options': ['Manter contrato atual', 'Rever a proposta'], 'evidence': ['contrato.txt:1, comportamento atual do cenário descartável.']})
                        await say('Investigação inicial registrada, aguardando a decisão humana.')
                    else:
                        assert answered['answer']['answer'] == 'Manter contrato atual'
                        assert (Path(self.options.cwd) / 'contrato.txt').read_text().startswith('Contrato atual:')
                        await call('conclude', {'result_kind': 'investigation', 'delivery_type': 'investigation_complete', 'summary': 'Contrato atual preservado, investigação concluída.', 'evidence': ['contrato.txt:1 e resposta humana vinculada à tentativa anterior.'], 'tests': [{'executed': False, 'status': 'not_run', 'command': 'Investigação sem alteração de código; nenhum teste executado.', 'output_ref': ''}], 'next_action': 'Conferir a revisão independente.'})
                        await say('Contrato atual preservado, investigação concluída.')
                await super()._run_steps([result_message(sid)])
            except Exception as error:
                await super()._run_steps([FailStep(f'Falha no cenário de trabalho E2E: {error}')])

    def chat_agent(options: AgentOptions) -> AgentClient:
        # Specialist chats and read-only command probes use the fake. Ordinary
        # conversations retain the refusal that the existing specs exercise.
        if not options.system_prompt_append and options.settings != NO_HOOKS:
            return refuse_agent(options)
        client = WorkScenarioClient(
            options, script=lambda content: text_turn(options.session_id, f"Resposta de teste: {content}")
        )
        clients.append(client)
        return client

    chat_enabled = os.environ.get("MAESTRO_E2E_CHAT") == "1"
    app = create_app(
        agent_factory=chat_agent if chat_enabled else refuse_agent,
        rename_session=(lambda *args: None) if chat_enabled else None,
        history_exists=(lambda sid, cwd: any(c.options.session_id == sid and c.sent for c in clients)) if chat_enabled else None,
        spawn_editor=_refuse_editor,
        pick_folder=_refuse_picker,
        refresh_models=False,
        plan_sweep=False,
        digest_model=RefusingDigestModel(),
        ports=app_ports(port),
        frontend_dir=cli.FRONTEND_DIR / "dist",
        agentd=False,
        fetch_release=_no_release,
        git_fetch=_no_git_fetch,
        gh_runner=refuse_gh,
        fetch_usage=_refuse_usage,
        restart=None,
        run_mode=RunMode("unknown"),
        claude_cli=inert_claude_resolver(),
    )
    return app


def stop_on_sigterm() -> None:
    """Make SIGTERM unwind like SIGINT: uvicorn re-raises the signal after its shutdown, and
    the default action would skip the cleanup of the temporary folder."""

    def handler(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handler)


def restrict_git_remotes() -> None:
    """The E2E remotes are folders inside the temporary root: allow only the file transport.

    https and ssh stay off, so nothing the tests do can reach a real remote.
    """
    gitinfo.FETCH_ALLOWED_PROTOCOLS = ("file",)


def serve(port: int) -> None:
    """Run uvicorn on 127.0.0.1 until it stops (SIGINT or SIGTERM). No restart."""
    import uvicorn

    try:
        restrict_git_remotes()
        if not cli.port_available(port):
            raise E2EError(f"A porta {port} já está em uso. Escolha outra em MAESTRO_E2E_PORT.")
        config = uvicorn.Config(
            build_app(port), host=cli.HOST, port=port,
            timeout_graceful_shutdown=cli.GRACEFUL_SHUTDOWN_SECONDS,
        )
        print(f"Servidor de E2E em http://localhost:{port}", flush=True)
        uvicorn.Server(config).run()
    except KeyboardInterrupt:
        # SIGINT/SIGTERM: uvicorn re-raises the signal after its shutdown, and one that arrives
        # while the app is being built lands here too.
        pass


def main() -> int:
    try:
        check_same_checkout()
        port = e2e_port(os.environ)
    except E2EError as exc:
        print(f"e2e_server: {exc}", file=sys.stderr)
        return 1
    try:
        # Build with the real environment (pnpm needs its own HOME and caches), then isolate.
        if cli.needs_build(cli.FRONTEND_DIR):
            print("Compilando o frontend...", flush=True)
            cli.build_frontend(cli.FRONTEND_DIR)
    except cli.CliError as exc:
        print(f"e2e_server: {exc}", file=sys.stderr)
        return 1
    root = Path(tempfile.mkdtemp(prefix="maestro-e2e-")).resolve()
    try:
        stop_on_sigterm()  # before the seed, so a SIGTERM while seeding still cleans `root`
        env = isolated_env(os.environ, root, port)
        os.environ.clear()
        os.environ.update(env)
        seed(root)
        serve(port)
        return 0
    except E2EError as exc:
        print(f"e2e_server: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
