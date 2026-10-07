"""The `claudio-maestro` command: build the frontend when needed and serve the app."""

import argparse
import getpass
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from claudio_maestro import service
from claudio_maestro.config import PortError, app_ports, backend_port, validate_port

HOST = "127.0.0.1"
GRACEFUL_SHUTDOWN_SECONDS = 10
# backend/claudio_maestro/cli.py -> repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
# A change in any of these makes the built frontend stale.
BUILD_INPUTS = (
    "src", "public", "index.html", "package.json", "pnpm-lock.yaml",
    "vite.config.ts", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json",
)

Run = Callable[..., subprocess.CompletedProcess]
Which = Callable[[str], str | None]
Serve = Callable[[Path, int, tuple[int, ...]], bool | None]
Execv = Callable[[str, list[str]], None]


class CliError(Exception):
    """A problem explained to the user (in Portuguese). The command exits with 1."""


def _newest_mtime(paths: Iterable[Path]) -> float:
    newest = 0.0
    for path in paths:
        if path.is_dir():
            files = (child for child in path.rglob("*") if child.is_file())
        elif path.is_file():
            files = iter((path,))
        else:
            continue
        for file in files:
            newest = max(newest, file.stat().st_mtime)
    return newest


def needs_build(frontend: Path) -> bool:
    """True when dist/index.html is missing or older than any build input."""
    index = frontend / "dist" / "index.html"
    if not index.is_file():
        return True
    inputs = (frontend / name for name in BUILD_INPUTS)
    return _newest_mtime(inputs) > index.stat().st_mtime


def build_frontend(frontend: Path, *, run: Run = subprocess.run, which: Which = shutil.which) -> None:
    """`pnpm install` (only without node_modules) and `pnpm build`, without a shell."""
    pnpm = which("pnpm")
    if pnpm is None:
        raise CliError(
            "O frontend precisa ser compilado, mas o pnpm não foi encontrado. "
            "Instale o Node 22.12 ou mais novo e o pnpm (https://pnpm.io/installation) e rode de novo."
        )
    steps = []
    if not (frontend / "node_modules").is_dir():
        steps.append([pnpm, "--dir", str(frontend), "install", "--frozen-lockfile"])
    steps.append([pnpm, "--dir", str(frontend), "build"])
    for argv in steps:
        print(f"Rodando pnpm {' '.join(argv[3:])}...", flush=True)
        if run(argv, check=False).returncode != 0:
            raise CliError(f"A compilação do frontend falhou em `pnpm {' '.join(argv[3:])}`. Veja a saída acima.")


def port_available(port: int) -> bool:
    """True when 127.0.0.1:`port` can be bound (same SO_REUSEADDR as uvicorn)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


class RestartFlag:
    """Handed to the app as `restart`: stops uvicorn the normal way (lifespan shutdown
    releases the sessions and the agentd) and tells `main` to exec itself again."""

    def __init__(self) -> None:
        self.requested = False
        self.server: Any | None = None

    def request(self) -> None:
        self.requested = True
        if self.server is not None:
            self.server.should_exit = True


def serve_app(dist: Path, port: int, ports: tuple[int, ...]) -> bool:
    """Run uvicorn until it stops. True when the app asked to be restarted."""
    import uvicorn

    from claudio_maestro.app import create_app

    flag = RestartFlag()
    config = uvicorn.Config(
        create_app(frontend_dir=dist, ports=ports, restart=flag.request), host=HOST, port=port,
        # A request left hanging (an open event stream, say) must not stop the restart.
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    server = uvicorn.Server(config)
    flag.server = server
    try:
        server.run()
    except KeyboardInterrupt:
        # uvicorn re-raises a captured SIGINT after the shutdown; `uvicorn.run` swallowed it too.
        return False
    return flag.requested


def main(
    argv: list[str] | None = None,
    *,
    frontend: Path = FRONTEND_DIR,
    serve: Serve = serve_app,
    run: Run = subprocess.run,
    which: Which = shutil.which,
    port_free: Callable[[int], bool] = port_available,
    execv: Execv = os.execv,
) -> int:
    parser = argparse.ArgumentParser(
        prog="claudio-maestro",
        description="Sobe o Cláudio Maestro em http://localhost:<porta>, compilando o frontend quando preciso.",
    )
    parser.add_argument("--port", help="porta do app (padrão: MAESTRO_PORT ou 6660)")
    commands = parser.add_subparsers(dest="command")
    svc = commands.add_parser("service", help="instala, remove ou mostra o serviço que mantém o app rodando")
    svc.add_argument("action", choices=["install", "uninstall", "status"])
    # Its own dest: a subparser default would overwrite the top-level --port.
    svc.add_argument("--port", dest="service_port", help="porta do app (padrão: MAESTRO_PORT ou 6660)")
    args = parser.parse_args(argv)
    if args.command == "service":
        try:
            env_port = backend_port()
            raw = args.service_port if args.service_port is not None else args.port
            port = validate_port(raw, "--port") if raw is not None else env_port
        except PortError as exc:
            print(f"claudio-maestro: {exc}", file=sys.stderr)
            return 1
        return service.run_service(
            args.action, port=port, repo=REPO_ROOT, home=Path.home(), environ=os.environ,
            port_free=port_free, user=getpass.getuser(),
        )
    try:
        # Also checked with --port: serving imports the app, which reads MAESTRO_PORT again.
        env_port = backend_port()
        port = validate_port(args.port, "--port") if args.port is not None else env_port
        ports = app_ports(port)
        if not (frontend / "package.json").is_file():
            raise CliError(
                f"Não encontrei o frontend em {frontend}. "
                "Rode o comando a partir de um clone do repositório (veja o README)."
            )
        if needs_build(frontend):
            print("Compilando o frontend...", flush=True)
            build_frontend(frontend, run=run, which=which)
        if not port_free(port):
            raise CliError(f"A porta {port} já está em uso. Use --port ou MAESTRO_PORT para escolher outra.")
    except (CliError, PortError) as exc:
        print(f"claudio-maestro: {exc}", file=sys.stderr)
        return 1
    print(f"Cláudio Maestro em http://localhost:{port}", flush=True)
    if serve(frontend / "dist", port, ports):
        print("Reiniciando o Cláudio Maestro...", flush=True)
        sys.stderr.flush()
        # Same PID: systemd, launchd, `uv run` or a terminal do not notice the swap.
        execv(sys.executable, list(sys.orig_argv))
    return 0


def run() -> None:
    """Entry point of the `claudio-maestro` script."""
    sys.exit(main())
