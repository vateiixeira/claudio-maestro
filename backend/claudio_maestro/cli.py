"""The `claudio-maestro` command: build the frontend when needed and serve the app."""

import argparse
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from claudio_maestro.config import PortError, backend_port, dev_port, validate_port

HOST = "127.0.0.1"
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
Serve = Callable[[Path, int, tuple[int, int]], None]


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


def serve_app(dist: Path, port: int, ports: tuple[int, int]) -> None:
    import uvicorn

    from claudio_maestro.app import create_app

    uvicorn.run(create_app(frontend_dir=dist, ports=ports), host=HOST, port=port)


def main(
    argv: list[str] | None = None,
    *,
    frontend: Path = FRONTEND_DIR,
    serve: Serve = serve_app,
    run: Run = subprocess.run,
    which: Which = shutil.which,
    port_free: Callable[[int], bool] = port_available,
) -> int:
    parser = argparse.ArgumentParser(
        prog="claudio-maestro",
        description="Sobe o Cláudio Maestro em http://localhost:<porta>, compilando o frontend quando preciso.",
    )
    parser.add_argument("--port", help="porta do app (padrão: MAESTRO_PORT ou 6660)")
    args = parser.parse_args(argv)
    try:
        port = validate_port(args.port, "--port") if args.port is not None else backend_port()
        ports = (dev_port(), port)
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
    serve(frontend / "dist", port, ports)
    return 0


def run() -> None:
    """Entry point of the `claudio-maestro` script."""
    sys.exit(main())
