"""CPU limits of the sessions, read from the environment.

`MAESTRO_CPU_WEIGHT` and `MAESTRO_CPU_QUOTA` go into the systemd unit (`service install`);
`MAESTRO_SESSION_NICE` is applied by the agentd to every `claude` it starts.
"""

from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_WEIGHT = 20
DEFAULT_SESSION_NICE = 10
MAX_WEIGHT = 10_000
MAX_QUOTA = 100_000
MAX_NICE = 19


class CpuLimitError(ValueError):
    """Invalid CPU limit setting. The message is for the user."""


@dataclass(frozen=True)
class CpuLimits:
    weight: int  # CPUWeight= of the systemd unit
    quota_percent: int | None  # CPUQuota= of the systemd unit; None = no ceiling
    session_nice: int  # 0 = leave the priority of the sessions alone


def _integer(name: str, text: str, low: int, high: int) -> int:
    if not (text.isascii() and text.isdecimal()):
        raise CpuLimitError(f"{name} precisa ser um número inteiro (recebido {text!r}).")
    value = int(text)
    if not low <= value <= high:
        raise CpuLimitError(f"{name} precisa estar entre {low} e {high} (recebido {value}).")
    return value


def _raw(environ: Mapping[str, str], name: str) -> str:
    return environ.get(name, "").strip()


def _quota(environ: Mapping[str, str], cpu_count: int) -> int | None:
    text = _raw(environ, "MAESTRO_CPU_QUOTA").lower()
    if text in ("", "auto"):
        return max(1, cpu_count * 6 // 10) * 100
    if text == "off":
        return None
    return _integer("MAESTRO_CPU_QUOTA", text, 1, MAX_QUOTA)


def session_nice_from_env(environ: Mapping[str, str]) -> int:
    text = _raw(environ, "MAESTRO_SESSION_NICE")
    if not text:
        return DEFAULT_SESSION_NICE
    return _integer("MAESTRO_SESSION_NICE", text, 0, MAX_NICE)


def cpu_limits(environ: Mapping[str, str], cpu_count: int) -> CpuLimits:
    weight_text = _raw(environ, "MAESTRO_CPU_WEIGHT")
    weight = _integer("MAESTRO_CPU_WEIGHT", weight_text, 1, MAX_WEIGHT) if weight_text else DEFAULT_WEIGHT
    return CpuLimits(
        weight=weight,
        quota_percent=_quota(environ, cpu_count),
        session_nice=session_nice_from_env(environ),
    )
