"""The official service: systemd unit (Linux) and launchd agent (macOS)."""

import plistlib
import subprocess
from pathlib import Path

import pytest

from claudio_maestro import service
from claudio_maestro.service import (
    MARK,
    launchd_plist,
    run_service,
    service_env,
    systemd_quote,
    systemd_unit,
)

REPO = Path("/home/fulano/claudio-maestro")
UV = "/home/fulano/.local/bin/uv"


def test_service_env_keeps_path_and_maestro_vars():
    env = service_env({"PATH": "/a:/b", "MAESTRO_DATA_DIR": "/d", "MAESTRO_RUN_MODE": "x", "HOME": "/h"})
    assert env == {"PATH": "/a:/b", "MAESTRO_DATA_DIR": "/d"}


def test_service_env_drops_port_variables():
    # The service port comes from --port; the dev and preview ports belong to development.
    env = service_env({
        "PATH": "/a", "MAESTRO_PORT": "7000", "MAESTRO_DEV_PORT": "7001", "MAESTRO_PREVIEW_PORT": "7002",
        "MAESTRO_UPDATE_CHECK": "0",
    })
    assert env == {"PATH": "/a", "MAESTRO_UPDATE_CHECK": "0"}


@pytest.mark.parametrize(
    ("raw", "quoted"),
    [
        ("PATH=/a b:/c", '"PATH=/a b:/c"'),
        ('X=a"b', '"X=a\\"b"'),
        ("X=a\\b", '"X=a\\\\b"'),
        ("X=50%", '"X=50%%"'),
        ("X=$HOME", '"X=$$HOME"'),
    ],
)
def test_systemd_quote_escapes_specials(raw, quoted):
    assert systemd_quote(raw) == quoted


def test_systemd_unit():
    text = systemd_unit(UV, REPO, 6660, {"PATH": "/usr/bin", "MAESTRO_DATA_DIR": "/d"})
    lines = text.splitlines()
    assert lines[0] == f"# {MARK}. Não edite: rode o install de novo."
    assert f'WorkingDirectory="{REPO}"' in lines or f"WorkingDirectory={REPO}" in lines
    assert 'Environment="PATH=/usr/bin"' in lines
    assert 'Environment="MAESTRO_DATA_DIR=/d"' in lines
    assert 'Environment="MAESTRO_RUN_MODE=systemd"' in lines
    assert (
        f'ExecStart="{UV}" "run" "--frozen" "--project" "{REPO}" "claudio-maestro" "--port" "6660"' in lines
    )
    for expected in ("KillMode=process", "Restart=on-failure", "RestartSec=3", "TimeoutStopSec=15",
                     "SuccessExitStatus=143", "WantedBy=default.target", "Type=simple"):
        assert expected in lines


def test_launchd_plist():
    data = plistlib.loads(launchd_plist(UV, REPO, 6660, {"PATH": "/usr/bin"}, Path("/h/Library/Logs/claudio-maestro.log")))
    assert data["Label"] == "io.github.vateiixeira.claudio-maestro"
    assert MARK in data["Comment"]
    assert data["ProgramArguments"] == [UV, "run", "--frozen", "--project", str(REPO), "claudio-maestro", "--port", "6660"]
    assert data["WorkingDirectory"] == str(REPO)
    assert data["EnvironmentVariables"] == {"PATH": "/usr/bin", "MAESTRO_RUN_MODE": "launchd"}
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] == {"SuccessfulExit": False}
    assert data["AbandonProcessGroup"] is True
    assert data["StandardOutPath"] == data["StandardErrorPath"] == "/h/Library/Logs/claudio-maestro.log"


class Run:
    """Fake subprocess.run: answers by the first matching argv prefix."""

    def __init__(self, answers: dict[tuple[str, ...], tuple[int, str]] | None = None):
        self.calls: list[list[str]] = []
        self.answers = answers or {}

    def __call__(self, argv, **kwargs):
        assert "shell" not in kwargs and isinstance(argv, list)
        assert kwargs.get("timeout") == 30
        self.calls.append(argv)
        for prefix, (code, out) in self.answers.items():
            if tuple(argv[1 : 1 + len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, code, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")


def which(name):
    return f"/usr/bin/{name}" if name != "uv" else UV


def call(action, tmp_path, *, platform="linux", run=None, free=True, out=None, which_fn=which):
    lines = [] if out is None else out
    code = run_service(
        action, port=6660, repo=REPO, home=tmp_path, environ={"PATH": "/usr/bin"},
        port_free=lambda port: free, platform=platform, run=run or Run(), which=which_fn,
        uid=501, user="fulano", out=lines.append,
    )
    return code, lines


UNIT = Path(".config/systemd/user/claudio-maestro.service")
PLIST = Path("Library/LaunchAgents/io.github.vateiixeira.claudio-maestro.plist")


def test_install_linux_writes_unit_and_enables(tmp_path):
    run = Run({("--user", "is-active"): (3, "inactive\n"), ("show-user",): (0, "yes\n")})
    code, lines = call("install", tmp_path, run=run)
    assert code == 0
    assert MARK in (tmp_path / UNIT).read_text()
    systemctl = [c[1:] for c in run.calls if c[0] == "/usr/bin/systemctl"]
    assert ["--user", "daemon-reload"] in systemctl
    assert ["--user", "enable", "claudio-maestro.service"] in systemctl
    assert ["--user", "restart", "claudio-maestro.service"] in systemctl
    assert not any("linger" in line for line in lines)


def test_install_linux_hints_linger(tmp_path):
    run = Run({("--user", "is-active"): (3, "inactive\n"), ("show-user",): (0, "no\n")})
    _, lines = call("install", tmp_path, run=run)
    assert any("loginctl enable-linger" in line for line in lines)


def test_install_refuses_busy_port_when_service_is_not_active(tmp_path):
    run = Run({("--user", "is-active"): (3, "inactive\n")})
    code, lines = call("install", tmp_path, run=run, free=False)
    assert code == 1
    assert any("a porta 6660 está em uso por outro programa" in line for line in lines)
    assert any("talvez o Maestro rodando num terminal ou em outro serviço" in line for line in lines)
    assert not (tmp_path / UNIT).exists()


def test_reinstall_over_active_official_service_ignores_its_port(tmp_path):
    (tmp_path / UNIT).parent.mkdir(parents=True)
    (tmp_path / UNIT).write_text(f"# {MARK}\n")
    run = Run({("--user", "is-active"): (0, "active\n"), ("show-user",): (0, "yes\n")})
    code, _ = call("install", tmp_path, run=run, free=False)
    assert code == 0


def test_install_refuses_foreign_file(tmp_path):
    (tmp_path / UNIT).parent.mkdir(parents=True)
    (tmp_path / UNIT).write_text("[Service]\nExecStart=/algo\n")
    code, lines = call("install", tmp_path, run=Run({("--user", "is-active"): (3, "")}))
    assert code == 1
    assert any("não foi gerado por este comando" in line for line in lines)
    assert (tmp_path / UNIT).read_text().startswith("[Service]")


def test_uninstall_linux(tmp_path):
    (tmp_path / UNIT).parent.mkdir(parents=True)
    (tmp_path / UNIT).write_text(f"# {MARK}\n")
    run = Run()
    code, _ = call("uninstall", tmp_path, run=run)
    assert code == 0 and not (tmp_path / UNIT).exists()
    assert ["/usr/bin/systemctl", "--user", "disable", "--now", "claudio-maestro.service"] in run.calls
    # `uv run` exits 143 on SIGTERM; reset-failed (after daemon-reload) clears any "failed" left behind.
    reload = run.calls.index(["/usr/bin/systemctl", "--user", "daemon-reload"])
    assert run.calls[reload + 1] == ["/usr/bin/systemctl", "--user", "reset-failed", "claudio-maestro.service"]


def test_uninstall_linux_ignores_a_failing_reset_failed(tmp_path):
    (tmp_path / UNIT).parent.mkdir(parents=True)
    (tmp_path / UNIT).write_text(f"# {MARK}\n")
    code, lines = call("uninstall", tmp_path, run=Run({("--user", "reset-failed"): (1, "")}))
    assert code == 0 and any("Serviço removido" in line for line in lines)


def test_uninstall_when_not_installed(tmp_path):
    code, lines = call("uninstall", tmp_path)
    assert code == 0 and any("não está instalado" in line for line in lines)


def test_status_linux(tmp_path):
    (tmp_path / UNIT).parent.mkdir(parents=True)
    (tmp_path / UNIT).write_text(f"# {MARK}\n")
    run = Run({("--user", "is-active"): (0, "active\n"), ("--user", "is-enabled"): (0, "enabled\n")})
    code, lines = call("status", tmp_path, run=run)
    assert code == 0
    assert any("journalctl --user -u claudio-maestro -f" in line for line in lines)


def test_install_macos_bootstraps(tmp_path):
    run = Run({("print",): (113, "")})
    code, _ = call("install", tmp_path, platform="darwin", run=run)
    assert code == 0
    data = plistlib.loads((tmp_path / PLIST).read_bytes())
    assert data["StandardOutPath"] == str(tmp_path / "Library/Logs/claudio-maestro.log")
    assert ["/usr/bin/launchctl", "bootstrap", "gui/501", str(tmp_path / PLIST)] in run.calls


def test_uninstall_macos(tmp_path):
    (tmp_path / PLIST).parent.mkdir(parents=True)
    (tmp_path / PLIST).write_bytes(launchd_plist(UV, REPO, 6660, {}, tmp_path / "log"))
    run = Run()
    code, _ = call("uninstall", tmp_path, platform="darwin", run=run)
    assert code == 0 and not (tmp_path / PLIST).exists()
    assert ["/usr/bin/launchctl", "bootout", "gui/501/io.github.vateiixeira.claudio-maestro"] in run.calls


def test_unsupported_platform(tmp_path):
    code, lines = call("install", tmp_path, platform="win32")
    assert code == 1
    assert any("só Linux (systemd) e macOS (launchd) por enquanto" in line for line in lines)


def test_missing_uv(tmp_path):
    code, lines = call("install", tmp_path, which_fn=lambda name: None if name == "uv" else f"/usr/bin/{name}")
    assert code == 1 and any("uv" in line for line in lines)


def test_missing_systemctl(tmp_path):
    code, lines = call("install", tmp_path, which_fn=lambda name: UV if name == "uv" else None)
    assert code == 1 and any("systemctl" in line for line in lines)


def test_systemd_quote_escapes_line_breaks():
    assert systemd_quote("X=a\nb\r") == '"X=a\\nb\\r"'


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        (Path("/home/fulano/meu app/maestro"), "WorkingDirectory=/home/fulano/meu app/maestro"),
        (Path("/home/fulano/100%/maestro"), "WorkingDirectory=/home/fulano/100%%/maestro"),
    ],
)
def test_systemd_unit_writes_working_directory_bare(repo, expected):
    # systemd 259 rejects a quoted WorkingDirectory= as "not absolute".
    assert expected in systemd_unit(UV, repo, 6660, {}).splitlines()


def test_systemd_unit_rejects_repo_path_with_line_break():
    with pytest.raises(service.ServiceError):
        systemd_unit(UV, Path("/a\nExecStart=/bin/sh"), 6660, {})


def test_install_reports_unit_error_without_writing(tmp_path):
    run = Run({("--user", "is-active"): (3, "inactive\n")})
    code = run_service(
        "install", port=6660, repo=Path("/a\nb"), home=tmp_path, environ={}, port_free=lambda p: True,
        platform="linux", run=run, which=which, user="fulano", out=lambda line: None,
    )
    assert code == 1 and not (tmp_path / UNIT).exists()


def test_systemd_unit_keeps_dollar_literal_in_environment_but_not_in_exec_start():
    # Environment= does no variable expansion (man systemd.exec); ExecStart= does.
    lines = systemd_unit("/opt/$uv/uv", REPO, 6660, {"MAESTRO_X": "a$b%c"}).splitlines()
    assert 'Environment="MAESTRO_X=a$b%%c"' in lines
    assert any(line.startswith('ExecStart="/opt/$$uv/uv"') for line in lines)


# -- an existing service that already runs the Maestro ---------------------------------------

LIST_UNITS = (
    "claudio-maestro-backend.service loaded active running Maestro\n"
    "other.service loaded active running Other\n"
)
LIST_FILES = "claudio-maestro-backend.service enabled enabled\nother.service enabled enabled\n"
HOME_EXEC = "{ path=/usr/bin/uv ; argv[]=uv run uvicorn claudio_maestro.app:app ; ignore_errors=no }"


def foreign_run(execs: dict[str, str], *, units: str = LIST_UNITS, files: str = LIST_FILES, list_code: int = 0):
    class ForeignRun(Run):
        def __call__(self, argv, **kwargs):
            if argv[1:3] == ["--user", "show"] and argv[3] != "claudio-maestro.service":
                self.calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, execs.get(argv[3], "") + "\n", "")
            return super().__call__(argv, **kwargs)

    return ForeignRun({
        ("--user", "is-active"): (3, "inactive\n"),
        ("--user", "list-units"): (list_code, units),
        ("--user", "list-unit-files"): (list_code, files),
    })


def test_install_linux_refuses_when_a_home_made_unit_runs_the_maestro(tmp_path):
    run = foreign_run({"claudio-maestro-backend.service": HOME_EXEC, "other.service": "{ argv[]=/usr/bin/sleep }"})
    code, lines = call("install", tmp_path, run=run)
    assert code == 1
    assert any(
        "Já existe um serviço que roda o Maestro: claudio-maestro-backend.service. "
        "Desative-o antes: systemctl --user disable --now claudio-maestro-backend.service" in line
        for line in lines
    )
    assert not (tmp_path / UNIT).exists()
    assert not any(c[1:] == ["--user", "daemon-reload"] for c in run.calls)
    assert ["/usr/bin/systemctl", "--user", "list-units", "--type=service", "--all", "--no-legend", "--plain"] in run.calls
    assert ["/usr/bin/systemctl", "--user", "list-unit-files", "--type=service", "--no-legend"] in run.calls
    assert ["/usr/bin/systemctl", "--user", "show", "claudio-maestro-backend.service", "-p", "ExecStart", "--value"] in run.calls


def test_install_linux_refuses_an_enabled_but_stopped_home_made_unit(tmp_path):
    units = "other.service loaded inactive dead Other\n"
    files = "mine.service enabled enabled\nother.service disabled enabled\n"
    run = foreign_run({"mine.service": "uv run claudio-maestro", "other.service": "uv run claudio-maestro"},
                      units=units, files=files)
    code, lines = call("install", tmp_path, run=run)
    assert code == 1 and any("mine.service" in line for line in lines)


def test_install_linux_ignores_units_that_are_not_the_maestro(tmp_path):
    run = foreign_run({"claudio-maestro-backend.service": "/usr/bin/sleep", "other.service": "/usr/bin/true"})
    code, _ = call("install", tmp_path, run=run)
    assert code == 0
    assert (tmp_path / UNIT).exists()


def test_install_linux_ignores_a_stopped_disabled_home_made_unit(tmp_path):
    units = "old.service loaded inactive dead Old\n"
    files = "old.service disabled enabled\n"
    run = foreign_run({"old.service": HOME_EXEC}, units=units, files=files)
    code, _ = call("install", tmp_path, run=run)
    assert code == 0


def test_install_linux_goes_on_when_listing_units_fails(tmp_path):
    run = foreign_run({"claudio-maestro-backend.service": HOME_EXEC}, list_code=1)
    code, _ = call("install", tmp_path, run=run)
    assert code == 0
    assert (tmp_path / UNIT).exists()


def test_install_linux_does_not_flag_its_own_unit(tmp_path):
    units = "claudio-maestro.service loaded active running Maestro\n"
    run = foreign_run({}, units=units, files="claudio-maestro.service enabled enabled\n")
    run.answers[("--user", "is-active")] = (0, "active\n")
    code, _ = call("install", tmp_path, run=run)
    assert code == 0


def _home_made_plist(tmp_path, name="com.example.maestro", args=("/usr/bin/uv", "run", "claudio-maestro")):
    path = tmp_path / "Library/LaunchAgents" / f"{name}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps({"Label": name, "ProgramArguments": list(args)}))
    return path


def test_install_macos_refuses_when_a_home_made_agent_runs_the_maestro(tmp_path):
    path = _home_made_plist(tmp_path)
    run = Run({("print",): (113, "")})
    code, lines = call("install", tmp_path, platform="darwin", run=run)
    assert code == 1
    assert any(
        "Já existe um serviço que roda o Maestro: com.example.maestro." in line
        and "launchctl bootout gui/501/com.example.maestro" in line
        and str(path) in line
        for line in lines
    )
    assert not (tmp_path / PLIST).exists()
    assert not any(c[1] == "bootstrap" for c in run.calls)


def test_install_macos_ignores_other_agents_and_unreadable_plists(tmp_path):
    _home_made_plist(tmp_path, "com.example.other", ("/usr/bin/true",))
    (tmp_path / "Library/LaunchAgents/broken.plist").write_text("not a plist")
    code, _ = call("install", tmp_path, platform="darwin", run=Run({("print",): (113, "")}))
    assert code == 0
