"""The `claudio-maestro` command: build the frontend when needed, then serve."""

import os
import socket
import subprocess
from pathlib import Path

import pytest

from claudio_maestro import cli


def make_frontend(tmp_path: Path, built: bool = True) -> Path:
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "public").mkdir()
    (frontend / "src" / "main.ts").write_text("x")
    for name in ("package.json", "index.html", "pnpm-lock.yaml", "vite.config.ts", "tsconfig.app.json"):
        (frontend / name).write_text(name)
    (frontend / "public" / "favicon.svg").write_text("<svg/>")
    if built:
        (frontend / "dist").mkdir()
        (frontend / "dist" / "index.html").write_text("built")
    return frontend


def age_all(frontend: Path, when: float) -> None:
    for path in frontend.rglob("*"):
        os.utime(path, (when, when))


def mark_built(frontend: Path, when: float) -> None:
    os.utime(frontend / "dist" / "index.html", (when, when))


# needs_build


def test_needs_build_without_dist(tmp_path: Path):
    assert cli.needs_build(make_frontend(tmp_path, built=False))


def test_no_build_when_dist_is_newer(tmp_path: Path):
    frontend = make_frontend(tmp_path)
    age_all(frontend, 1000)
    mark_built(frontend, 2000)
    assert not cli.needs_build(frontend)


@pytest.mark.parametrize(
    "name",
    ["src/main.ts", "index.html", "package.json", "pnpm-lock.yaml", "vite.config.ts", "tsconfig.app.json", "public/favicon.svg"],
)
def test_build_when_an_input_is_newer(tmp_path: Path, name: str):
    frontend = make_frontend(tmp_path)
    age_all(frontend, 1000)
    mark_built(frontend, 2000)
    os.utime(frontend / name, (3000, 3000))
    assert cli.needs_build(frontend)


def test_build_when_a_nested_source_is_newer(tmp_path: Path):
    frontend = make_frontend(tmp_path)
    nested = frontend / "src" / "components" / "chat" / "Bloco.vue"
    nested.parent.mkdir(parents=True)
    nested.write_text("<template/>")
    age_all(frontend, 1000)
    mark_built(frontend, 2000)
    os.utime(nested, (3000, 3000))
    assert cli.needs_build(frontend)


# build_frontend


class Runner:
    def __init__(self, codes: dict[str, int] | None = None, on_build=None):
        self.calls: list[tuple[list[str], dict]] = []
        self.codes = codes or {}
        self.on_build = on_build

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        step = argv[3]
        if step == "build" and self.on_build:
            self.on_build()
        return subprocess.CompletedProcess(argv, self.codes.get(step, 0))


def test_build_installs_when_node_modules_is_missing(tmp_path: Path):
    frontend = make_frontend(tmp_path, built=False)
    runner = Runner()
    cli.build_frontend(frontend, run=runner, which=lambda name: "/bin/pnpm")
    assert [argv for argv, _ in runner.calls] == [
        ["/bin/pnpm", "--dir", str(frontend), "install", "--frozen-lockfile"],
        ["/bin/pnpm", "--dir", str(frontend), "build"],
    ]
    assert all("shell" not in kwargs for _, kwargs in runner.calls)


def test_build_skips_install_with_node_modules(tmp_path: Path):
    frontend = make_frontend(tmp_path, built=False)
    (frontend / "node_modules").mkdir()
    runner = Runner()
    cli.build_frontend(frontend, run=runner, which=lambda name: "/bin/pnpm")
    assert [argv[3] for argv, _ in runner.calls] == ["build"]


def test_build_without_pnpm_explains(tmp_path: Path):
    with pytest.raises(cli.CliError, match="pnpm"):
        cli.build_frontend(make_frontend(tmp_path), run=Runner(), which=lambda name: None)


def test_build_failure_raises(tmp_path: Path):
    frontend = make_frontend(tmp_path)
    (frontend / "node_modules").mkdir()
    with pytest.raises(cli.CliError, match="falhou"):
        cli.build_frontend(frontend, run=Runner({"build": 1}), which=lambda name: "/bin/pnpm")


# port_available


def test_port_available_sees_a_busy_port():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        assert not cli.port_available(busy.getsockname()[1])


# main


class Server:
    def __init__(self):
        self.calls: list[tuple[Path, int, tuple[int, int]]] = []

    def __call__(self, dist: Path, port: int, ports: tuple[int, int]) -> None:
        self.calls.append((dist, port, ports))


def run_main(frontend: Path, argv: list[str], *, free: bool = True, runner: Runner | None = None):
    server = Server()
    code = cli.main(
        argv, frontend=frontend, serve=server, run=runner or Runner(),
        which=lambda name: "/bin/pnpm", port_free=lambda port: free,
    )
    return code, server


def test_main_builds_then_serves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.delenv("MAESTRO_PORT", raising=False)
    monkeypatch.delenv("MAESTRO_DEV_PORT", raising=False)
    frontend = make_frontend(tmp_path, built=False)

    def build():
        (frontend / "dist").mkdir()
        (frontend / "dist" / "index.html").write_text("built")

    runner = Runner(on_build=build)
    code, server = run_main(frontend, [], runner=runner)

    assert code == 0
    assert server.calls == [(frontend / "dist", 6660, (6600, 6660))]
    assert "http://localhost:6660" in capsys.readouterr().out


def test_main_skips_build_when_up_to_date(tmp_path: Path):
    frontend = make_frontend(tmp_path)
    age_all(frontend, 1000)
    mark_built(frontend, 2000)
    runner = Runner()
    code, _ = run_main(frontend, [], runner=runner)
    assert code == 0
    assert runner.calls == []


def test_port_flag_wins_over_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAESTRO_PORT", "7000")
    code, server = run_main(make_frontend(tmp_path), ["--port", "7200"])
    assert code == 0
    assert server.calls[0][1] == 7200
    assert server.calls[0][2][1] == 7200


def test_environment_port_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAESTRO_PORT", "7000")
    _, server = run_main(make_frontend(tmp_path), [])
    assert server.calls[0][1] == 7000


@pytest.mark.parametrize(("argv", "env", "fragment"), [
    (["--port", "abc"], None, "--port"),
    (["--port", "6667"], None, "6665 a 6669"),
    ([], "80", "MAESTRO_PORT"),
])
def test_bad_port_is_a_message_not_a_traceback(tmp_path, monkeypatch, capsys, argv, env, fragment):
    if env is None:
        monkeypatch.delenv("MAESTRO_PORT", raising=False)
    else:
        monkeypatch.setenv("MAESTRO_PORT", env)
    code, server = run_main(make_frontend(tmp_path), argv)
    assert code == 1
    assert server.calls == []
    assert fragment in capsys.readouterr().err


def test_busy_port_is_explained(tmp_path: Path, capsys):
    code, server = run_main(make_frontend(tmp_path), [], free=False)
    assert code == 1
    assert server.calls == []
    assert "já está em uso" in capsys.readouterr().err


def test_missing_frontend_folder_is_explained(tmp_path: Path, capsys):
    code, server = run_main(tmp_path / "nada", [])
    assert code == 1
    assert "clone" in capsys.readouterr().err


def test_build_failure_stops_before_serving(tmp_path: Path, capsys):
    frontend = make_frontend(tmp_path, built=False)
    (frontend / "node_modules").mkdir()
    code, server = run_main(frontend, [], runner=Runner({"build": 1}))
    assert code == 1
    assert server.calls == []


def test_frontend_is_found_from_the_package_not_the_current_folder(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.FRONTEND_DIR.is_absolute()
    assert (cli.FRONTEND_DIR / "package.json").is_file()
    assert cli.FRONTEND_DIR == cli.REPO_ROOT / "frontend"
