"""`claudio-maestro service install | uninstall | status`: the official way to keep the
app running (systemd user unit on Linux, launchd agent on macOS).

The generated files keep the agentd alive when the app restarts (KillMode=process,
AbandonProcessGroup) and mark themselves, so this command never touches a file it
did not write. Every process runs with an argument list, without a shell.
"""

import os
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from claudio_maestro.runmode import LAUNCHD_LABEL, OFFICIAL_UNIT

MARK = "Gerado por claudio-maestro service install"
TIMEOUT = 30
UNIT_DIR = Path(".config/systemd/user")
AGENTS_DIR = Path("Library/LaunchAgents")
LOG_PATH = Path("Library/Logs/claudio-maestro.log")

Run = Callable[..., subprocess.CompletedProcess]
Which = Callable[[str], str | None]


MAESTRO_NAMES = ("claudio_maestro", "claudio-maestro")
# The service port comes from --port; the dev and preview ports belong to development.
NOT_FOR_THE_SERVICE = frozenset({"MAESTRO_RUN_MODE", "MAESTRO_PORT", "MAESTRO_DEV_PORT", "MAESTRO_PREVIEW_PORT"})
ACTIVE_STATES = frozenset({"active", "activating", "reloading"})
ENABLED_STATES = frozenset({"enabled", "enabled-runtime"})


class ServiceError(Exception):
    """A problem explained to the user (in Portuguese)."""


def service_env(environ: Mapping[str, str]) -> dict[str, str]:
    env = {"PATH": environ.get("PATH", "")}
    env.update(
        (key, value) for key, value in sorted(environ.items())
        if key.startswith("MAESTRO_") and key not in NOT_FOR_THE_SERVICE
    )
    return env


def systemd_quote(text: str, *, dollar: bool = True) -> str:
    """Quote one word for a systemd setting. `dollar` doubles `$`, which only command lines
    (ExecStart=) expand; Environment= does not, so there `$` must stay as it is."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if dollar:
        escaped = escaped.replace("$", "$$")
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r")
    return f'"{escaped}"'


def systemd_path(path: Path) -> str:
    """A path for `WorkingDirectory=`: written bare, because systemd (verified on 259) does not
    unquote it and rejects a quoted value as "not absolute". Spaces are fine; only `%` (a
    specifier) needs escaping, and a line break would break the file."""
    text = str(path)
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ServiceError(f"o caminho {text!r} tem caracteres de controle; mova o app para outra pasta")
    return text.replace("%", "%%")


def _command(uv: str, repo: Path, port: int) -> list[str]:
    return [uv, "run", "--frozen", "--project", str(repo), "claudio-maestro", "--port", str(port)]


def systemd_unit(uv: str, repo: Path, port: int, env: Mapping[str, str]) -> str:
    environment = [f"Environment={systemd_quote(f'{k}={v}', dollar=False)}" for k, v in env.items()]
    environment.append(f"Environment={systemd_quote('MAESTRO_RUN_MODE=systemd', dollar=False)}")
    exec_start = " ".join(systemd_quote(arg) for arg in _command(uv, repo, port))
    return "\n".join([
        f"# {MARK}. Não edite: rode o install de novo.",
        "[Unit]",
        "Description=Cláudio Maestro",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={systemd_path(repo)}",
        *environment,
        f"ExecStart={exec_start}",
        "Restart=on-failure",
        "RestartSec=3",
        "# Ao parar, encerra só o app: o agentd e as sessões ficam vivos.",
        "KillMode=process",
        "TimeoutStopSec=15",
        "# O `uv run` sai com 143 (SIGTERM) ao parar: não é falha.",
        "SuccessExitStatus=143",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def launchd_plist(uv: str, repo: Path, port: int, env: Mapping[str, str], log_path: Path) -> bytes:
    return plistlib.dumps({
        "Label": LAUNCHD_LABEL,
        "Comment": f"{MARK}. Não edite: rode o install de novo.",
        "ProgramArguments": _command(uv, repo, port),
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": {**env, "MAESTRO_RUN_MODE": "launchd"},
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "AbandonProcessGroup": True,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    })


def _run(run: Run, argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return run(argv, capture_output=True, text=True, check=False, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceError(f"não foi possível rodar {Path(argv[0]).name}: {exc}") from exc


def _checked(run: Run, argv: list[str]) -> None:
    result = _run(run, argv)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:300]
        raise ServiceError(f"`{Path(argv[0]).name} {' '.join(argv[1:])}` falhou: {detail}")


def _ours(path: Path) -> bool:
    try:
        return MARK in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _require(which: Which, name: str, hint: str) -> str:
    found = which(name)
    if found is None:
        raise ServiceError(f"{name} não encontrado. {hint}")
    return os.path.abspath(found)


def _port_check(active: bool, port: int, port_free: Callable[[int], bool]) -> None:
    if not active and not port_free(port):
        raise ServiceError(
            f"a porta {port} está em uso por outro programa (talvez o Maestro rodando num terminal "
            "ou em outro serviço); pare-o e rode de novo"
        )


def _mentions_maestro(text: str) -> bool:
    return any(name in text for name in MAESTRO_NAMES)


def _foreign_systemd_unit(run: Run, systemctl: str) -> str | None:
    """A user unit, not ours, that runs the Maestro and is active or enabled; None when there is
    none or when systemctl cannot say (then the install goes on)."""
    base = [systemctl, "--user"]
    try:
        listed = _run(run, [*base, "list-units", "--type=service", "--all", "--no-legend", "--plain"])
        files = _run(run, [*base, "list-unit-files", "--type=service", "--no-legend"])
    except ServiceError:
        return None
    if listed.returncode != 0 or files.returncode != 0:
        return None
    candidates: dict[str, None] = {}
    for line in (listed.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in ACTIVE_STATES:
            candidates[parts[0]] = None
    for line in (files.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ENABLED_STATES:
            candidates[parts[0]] = None
    for unit in candidates:
        if unit == OFFICIAL_UNIT or not unit.endswith(".service") or "@." in unit:
            continue
        try:
            shown = _run(run, [*base, "show", unit, "-p", "ExecStart", "--value"])
        except ServiceError:
            continue
        if shown.returncode == 0 and _mentions_maestro(shown.stdout or ""):
            return unit
    return None


def _foreign_launchd_agent(home: Path) -> tuple[str, Path] | None:
    """A LaunchAgent, not ours, whose ProgramArguments run the Maestro: (label, file)."""
    official = f"{LAUNCHD_LABEL}.plist"
    try:
        files = sorted((home / AGENTS_DIR).glob("*.plist"))
    except OSError:
        return None
    for path in files:
        if path.name == official:
            continue
        try:
            data = plistlib.loads(path.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        arguments = data.get("ProgramArguments") if isinstance(data, dict) else None
        if isinstance(arguments, list) and _mentions_maestro(" ".join(str(a) for a in arguments)):
            return str(data.get("Label") or path.stem), path
    return None


def _systemd(action, *, port, repo, home, environ, port_free, run, which, user, out) -> None:
    systemctl = _require(which, "systemctl", "O serviço oficial no Linux precisa do systemd.")
    path = home / UNIT_DIR / OFFICIAL_UNIT
    if action == "status":
        if not path.exists():
            out("O serviço não está instalado. Para instalar: uv run claudio-maestro service install")
            return
        active = _run(run, [systemctl, "--user", "is-active", OFFICIAL_UNIT]).stdout.strip() or "?"
        enabled = _run(run, [systemctl, "--user", "is-enabled", OFFICIAL_UNIT]).stdout.strip() or "?"
        out(f"Serviço {OFFICIAL_UNIT}: {active}, {enabled}.")
        out("Log: journalctl --user -u claudio-maestro -f")
        return
    if path.exists() and not _ours(path):
        raise ServiceError(f"{path} existe mas não foi gerado por este comando; remova-o ou renomeie antes")
    if action == "uninstall":
        if not path.exists():
            out("O serviço não está instalado.")
            return
        _run(run, [systemctl, "--user", "disable", "--now", OFFICIAL_UNIT])
        path.unlink()
        _checked(run, [systemctl, "--user", "daemon-reload"])
        # The unit may be left "failed" by the stop; its file is gone, so this can fail harmlessly.
        _run(run, [systemctl, "--user", "reset-failed", OFFICIAL_UNIT])
        out("Serviço removido.")
        return
    uv = _require(which, "uv", "Instale o uv (https://docs.astral.sh/uv/) e rode de novo.")
    foreign = _foreign_systemd_unit(run, systemctl)
    if foreign is not None:
        raise ServiceError(
            f"Já existe um serviço que roda o Maestro: {foreign}. "
            f"Desative-o antes: systemctl --user disable --now {foreign}"
        )
    active = _run(run, [systemctl, "--user", "is-active", OFFICIAL_UNIT]).stdout.strip() == "active"
    _port_check(active, port, port_free)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(systemd_unit(uv, repo, port, service_env(environ)), encoding="utf-8")
    _checked(run, [systemctl, "--user", "daemon-reload"])
    _checked(run, [systemctl, "--user", "enable", OFFICIAL_UNIT])
    _checked(run, [systemctl, "--user", "restart", OFFICIAL_UNIT])
    out(f"Serviço instalado e rodando: http://localhost:{port}")
    out("Log: journalctl --user -u claudio-maestro -f")
    loginctl = which("loginctl")
    if loginctl is not None and user:
        linger = _run(run, [loginctl, "show-user", user, "-p", "Linger", "--value"]).stdout.strip()
        if linger != "yes":
            out("Para subir no boot sem fazer login, rode: loginctl enable-linger")


def _launchd(action, *, port, repo, home, environ, port_free, run, which, uid, out) -> None:
    launchctl = _require(which, "launchctl", "O serviço oficial no macOS precisa do launchd.")
    path = home / AGENTS_DIR / f"{LAUNCHD_LABEL}.plist"
    log_path = home / LOG_PATH
    target = f"gui/{uid}/{LAUNCHD_LABEL}"
    if action == "status":
        if not path.exists():
            out("O serviço não está instalado. Para instalar: uv run claudio-maestro service install")
            return
        loaded = _run(run, [launchctl, "print", target]).returncode == 0
        out(f"Serviço {LAUNCHD_LABEL}: {'carregado' if loaded else 'não carregado'}.")
        out(f"Log: {log_path}")
        return
    if path.exists() and not _ours(path):
        raise ServiceError(f"{path} existe mas não foi gerado por este comando; remova-o ou renomeie antes")
    if action == "uninstall":
        if not path.exists():
            out("O serviço não está instalado.")
            return
        _run(run, [launchctl, "bootout", target])
        path.unlink()
        out("Serviço removido.")
        return
    uv = _require(which, "uv", "Instale o uv (https://docs.astral.sh/uv/) e rode de novo.")
    foreign_agent = _foreign_launchd_agent(home)
    if foreign_agent is not None:
        label, plist = foreign_agent
        raise ServiceError(
            f"Já existe um serviço que roda o Maestro: {label}. "
            f"Desative-o antes: launchctl bootout gui/{uid}/{label} e remova {plist}"
        )
    loaded = _run(run, [launchctl, "print", target]).returncode == 0
    _port_check(loaded, port, port_free)
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(launchd_plist(uv, repo, port, service_env(environ), log_path))
    _run(run, [launchctl, "bootout", target])  # not loaded is fine
    _checked(run, [launchctl, "bootstrap", f"gui/{uid}", str(path)])
    out(f"Serviço instalado e rodando: http://localhost:{port}")
    out(f"Log: {log_path}")


def run_service(
    action: str,
    *,
    port: int,
    repo: Path,
    home: Path,
    environ: Mapping[str, str],
    port_free: Callable[[int], bool],
    platform: str = sys.platform,
    run: Run = subprocess.run,
    which: Which = shutil.which,
    uid: int | None = None,
    user: str | None = None,
    out: Callable[[str], None] = print,
    err: Callable[[str], None] | None = None,
) -> int:
    if err is None:
        err = out if out is not print else (lambda line: print(line, file=sys.stderr))
    try:
        if platform.startswith("linux"):
            _systemd(action, port=port, repo=repo, home=home, environ=environ, port_free=port_free,
                     run=run, which=which, user=user, out=out)
        elif platform == "darwin":
            _launchd(action, port=port, repo=repo, home=home, environ=environ, port_free=port_free,
                     run=run, which=which, uid=os.getuid() if uid is None else uid, out=out)
        else:
            raise ServiceError("só Linux (systemd) e macOS (launchd) por enquanto")
    except ServiceError as exc:
        err(f"claudio-maestro: {exc}")
        return 1
    return 0
