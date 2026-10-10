#!/usr/bin/env python3
"""Backend descartável para os testes E2E do frontend (Playwright).

Cria um diretório temporário, aponta home, dados e conversas para dentro dele, semeia
projetos e conversas gravadas e serve o frontend compilado numa porta própria (6620 por
padrão, `MAESTRO_E2E_PORT` troca). Nada toca em `~/.claude`, no banco real ou no SDK.

    uv run python scripts/e2e_server.py
"""

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

from claudio_maestro import cli, db, projects
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
        ],
    },
]


class E2EError(Exception):
    """A problem explained to the user (in Portuguese)."""


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
        if not key.startswith(("MAESTRO_", "CLAUDE"))
    }
    env.update(
        {
            "HOME": str(root / "home"),
            "MAESTRO_HOME": str(root / "home"),
            "MAESTRO_DATA_DIR": str(root / "data"),
            "CLAUDE_CONFIG_DIR": str(root / "claude-config"),
            "MAESTRO_PORT": str(port),
            "MAESTRO_AGENTD": "0",
            "MAESTRO_UPDATE_CHECK": "0",
            "MAESTRO_USAGE_CHECK": "0",
            "MAESTRO_CLAUDE_CHECK": "0",
        }
    )
    return env


def _history_folder(projects_dir: Path, project_dir: Path) -> Path:
    """Where the CLI keeps the conversations of `project_dir` (non-alphanumerics become `-`)."""
    return projects_dir / re.sub(r"[^a-zA-Z0-9]", "-", str(project_dir))


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _write_conversation(
    folder: Path, project_dir: Path, prompt: str, reply: str, started: datetime
) -> None:
    """A minimal transcript: one user message and one assistant answer."""
    session_id, user_id, assistant_id = (str(uuid.uuid4()) for _ in range(3))
    lines = [
        {
            "parentUuid": None, "isSidechain": False, "type": "user", "uuid": user_id,
            "sessionId": session_id, "cwd": str(project_dir), "timestamp": _stamp(started),
            "message": {"role": "user", "content": prompt},
        },
        {
            "parentUuid": user_id, "isSidechain": False, "type": "assistant",
            "uuid": assistant_id, "sessionId": session_id, "cwd": str(project_dir),
            "timestamp": _stamp(started + timedelta(seconds=5)),
            "message": {
                "role": "assistant", "model": "claude-haiku",
                "content": [{"type": "text", "text": reply}],
            },
        },
    ]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )


def seed(root: Path) -> None:
    """Create the database, the projects and the conversations of `SCENARIO`.

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
                    started,
                )


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
    """
    from claudio_maestro.app import create_app

    return create_app(
        agent_factory=refuse_agent,
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
        fetch_usage=_refuse_usage,
        restart=None,
        run_mode=RunMode("unknown"),
        claude_cli=inert_claude_resolver(),
    )


def stop_on_sigterm() -> None:
    """Make SIGTERM unwind like SIGINT: uvicorn re-raises the signal after its shutdown, and
    the default action would skip the cleanup of the temporary folder."""

    def handler(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handler)


def serve(port: int) -> None:
    """Run uvicorn on 127.0.0.1 until it stops (SIGINT or SIGTERM). No restart."""
    import uvicorn

    try:
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
        env = isolated_env(os.environ, root, port)
        os.environ.clear()
        os.environ.update(env)
        seed(root)
        stop_on_sigterm()
        serve(port)
        return 0
    except E2EError as exc:
        print(f"e2e_server: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
