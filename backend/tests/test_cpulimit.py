"""CPU limits of the sessions: systemd weight and quota, and the `nice` of each `claude`."""

import pytest

from claudio_maestro.cpulimit import (
    CpuLimitError,
    CpuLimits,
    cpu_limits,
    session_nice_from_env,
)


def test_defaults():
    assert cpu_limits({}, 16) == CpuLimits(weight=20, quota_percent=900, session_nice=10)


@pytest.mark.parametrize(("cores", "quota"), [(1, 100), (2, 100), (4, 200), (8, 400), (16, 900)])
def test_auto_quota_is_sixty_percent_of_the_cores_and_never_zero(cores, quota):
    assert cpu_limits({}, cores).quota_percent == quota


@pytest.mark.parametrize("raw", ["", "auto", "AUTO", " Auto "])
def test_quota_auto_spellings(raw):
    assert cpu_limits({"MAESTRO_CPU_QUOTA": raw}, 16).quota_percent == 900


@pytest.mark.parametrize("raw", ["off", "OFF", " off "])
def test_quota_off(raw):
    assert cpu_limits({"MAESTRO_CPU_QUOTA": raw}, 16).quota_percent is None


def test_explicit_values():
    env = {"MAESTRO_CPU_WEIGHT": "50", "MAESTRO_CPU_QUOTA": "800", "MAESTRO_SESSION_NICE": "5"}
    assert cpu_limits(env, 16) == CpuLimits(weight=50, quota_percent=800, session_nice=5)


def test_empty_values_mean_default():
    env = {"MAESTRO_CPU_WEIGHT": "", "MAESTRO_SESSION_NICE": "  "}
    assert cpu_limits(env, 16) == CpuLimits(weight=20, quota_percent=900, session_nice=10)


def test_nice_zero_turns_it_off():
    assert cpu_limits({"MAESTRO_SESSION_NICE": "0"}, 16).session_nice == 0


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("MAESTRO_CPU_QUOTA", "0"),
        ("MAESTRO_CPU_QUOTA", "-100"),
        ("MAESTRO_CPU_QUOTA", "abc"),
        ("MAESTRO_CPU_QUOTA", "8.5"),
        ("MAESTRO_CPU_QUOTA", "100001"),
        ("MAESTRO_CPU_WEIGHT", "0"),
        ("MAESTRO_CPU_WEIGHT", "10001"),
        ("MAESTRO_CPU_WEIGHT", "muito"),
        ("MAESTRO_SESSION_NICE", "20"),
        ("MAESTRO_SESSION_NICE", "-1"),
        ("MAESTRO_SESSION_NICE", "x"),
    ],
)
def test_invalid_values_name_the_variable(name, raw):
    with pytest.raises(CpuLimitError, match=name):
        cpu_limits({name: raw}, 16)


def test_session_nice_from_env_ignores_the_other_variables():
    # The agentd only needs the nice: a broken quota must not stop it.
    assert session_nice_from_env({"MAESTRO_CPU_QUOTA": "abc", "MAESTRO_SESSION_NICE": "3"}) == 3
    assert session_nice_from_env({}) == 10
    with pytest.raises(CpuLimitError, match="MAESTRO_SESSION_NICE"):
        session_nice_from_env({"MAESTRO_SESSION_NICE": "99"})
