"""The agentd entry point reads the session nice without ever refusing to start."""

import logging

from claudio_maestro.agentd.__main__ import _session_nice


def test_session_nice_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAESTRO_SESSION_NICE", "4")
    assert _session_nice() == 4


def test_a_broken_quota_does_not_matter_to_the_agentd(monkeypatch):
    monkeypatch.setenv("MAESTRO_CPU_QUOTA", "abc")
    monkeypatch.delenv("MAESTRO_SESSION_NICE", raising=False)
    assert _session_nice() == 10


def test_an_invalid_nice_falls_back_to_zero_and_warns(monkeypatch, caplog):
    monkeypatch.setenv("MAESTRO_SESSION_NICE", "99")
    with caplog.at_level(logging.WARNING):
        assert _session_nice() == 0
    assert "MAESTRO_SESSION_NICE" in caplog.text
