"""Settings of the digest agent."""

from contextlib import closing
from pathlib import Path

import pytest

from claudio_maestro import db
from claudio_maestro.digest.config import (
    MESSAGES,
    ConfigError,
    DigestConfig,
    coerce,
    load_config,
    model_known,
    save_config,
    validate,
)

KNOWN = ["default", "opus", "sonnet", "haiku", "claude-sonnet-5-5"]


def test_defaults() -> None:
    assert DigestConfig().to_dict() == {
        "enabled": False, "model": "sonnet", "effort": "medium", "extra_instructions": "",
        "interval_minutes": 10, "min_new_messages": 10, "open_turn_minutes": 30,
        "window_days": 3,
    }


def test_coerce_keeps_valid_fields_and_defaults_the_rest() -> None:
    cfg = coerce({"enabled": True, "interval_minutes": 0, "effort": "xhigh", "model": 3})
    assert cfg.enabled is True and cfg.effort == "xhigh"
    assert cfg.interval_minutes == 10 and cfg.model == "sonnet"
    assert coerce(None) == DigestConfig()
    assert coerce([1, 2]) == DigestConfig()


def test_validate_accepts_a_full_body() -> None:
    body = {**DigestConfig().to_dict(), "enabled": True, "model": "claude-sonnet-5-5",
            "extra_instructions": "Cite a tarefa."}
    assert validate(body, KNOWN) == DigestConfig(
        enabled=True, model="claude-sonnet-5-5", extra_instructions="Cite a tarefa."
    )


def test_validate_fills_missing_fields_with_defaults() -> None:
    assert validate({"enabled": True}, KNOWN) == DigestConfig(enabled=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("enabled", "sim"),
        ("model", "gpt-4"),
        ("effort", "huge"),
        ("extra_instructions", "x" * 4001),
        ("interval_minutes", 1),
        ("interval_minutes", 241),
        ("interval_minutes", True),
        ("min_new_messages", 0),
        ("open_turn_minutes", 4),
        ("window_days", 31),
        ("window_days", 2.5),
    ],
)
def test_validate_rejects_each_bad_field(field: str, value: object) -> None:
    with pytest.raises(ConfigError) as info:
        validate({field: value}, KNOWN)
    assert info.value.errors == {field: MESSAGES[field]}


def test_validate_reports_every_error_and_unknown_fields() -> None:
    with pytest.raises(ConfigError) as info:
        validate({"window_days": 0, "effort": "x", "color": "red"}, KNOWN)
    assert set(info.value.errors) == {"window_days", "effort", "color"}
    assert info.value.errors["color"] == "Campo desconhecido: color."


def test_validate_rejects_a_non_object() -> None:
    with pytest.raises(ConfigError) as info:
        validate([1], KNOWN)
    assert info.value.errors == {"body": "Envie a configuração como um objeto."}


def test_aliases_are_always_known() -> None:
    assert model_known("haiku", [])
    assert not model_known("claude-x", [])
    assert model_known("claude-x", ["claude-x"])


def test_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "v.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        assert load_config(conn) == DigestConfig()
        save_config(conn, DigestConfig(enabled=True, window_days=7))
        assert load_config(conn) == DigestConfig(enabled=True, window_days=7)
