import asyncio
import http.server
import io
import json
import logging
import threading
import urllib.error
from pathlib import Path

import pytest

from claudio_maestro import usage
from claudio_maestro.usage import (
    OAUTH_BETA,
    USAGE_URL,
    UsageChecker,
    UsageCheckError,
    UsageLimit,
    UsageReport,
    parse_usage,
    plan_label,
    read_access_token,
    read_credentials,
    request_usage,
)

TOKEN = "sk-ant-oat01-SEGREDO"

# Captured from the real endpoint on 2026-10-05 (only the part the app uses).
REAL_PAYLOAD = {
    "five_hour": {"utilization": 14.0, "resets_at": "2026-10-06T00:30:00.324376+00:00"},
    "limits": [
        {"kind": "session", "group": "session", "percent": 14, "severity": "normal",
         "resets_at": "2026-10-06T00:30:00.324376+00:00", "scope": None, "is_active": False},
        {"kind": "weekly_all", "group": "weekly", "percent": 17, "severity": "normal",
         "resets_at": "2026-10-05T22:00:00.324395+00:00", "scope": None, "is_active": True},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 3, "severity": "normal",
         "resets_at": "2026-10-05T22:00:00.324561+00:00",
         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
         "is_active": False},
    ],
}


def write_credentials(folder: Path, *, token=TOKEN, expires_at=None, tier="default_claude_max_20x") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    oauth = {"accessToken": token, "refreshToken": "r", "subscriptionType": "max"}
    if tier is not None:
        oauth["rateLimitTier"] = tier
    if expires_at is not None:
        oauth["expiresAt"] = expires_at
    (folder / ".credentials.json").write_text(json.dumps({"claudeAiOauth": oauth}))
    return folder


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_returning(body: bytes, seen: list | None = None):
    def opener(request, timeout):
        if seen is not None:
            seen.append((request, timeout))
        return FakeResponse(body)

    return opener


def opener_raising(exc: Exception):
    def opener(request, timeout):
        raise exc

    return opener


# parse_usage ----------------------------------------------------------------


def test_parse_real_payload():
    limits = parse_usage(REAL_PAYLOAD)
    assert [(x.kind, x.label, x.percent, x.severity) for x in limits] == [
        ("session", "Sessão", 14, "normal"),
        ("weekly_all", "Semana", 17, "normal"),
        ("weekly_scoped", "Semana · Fable", 3, "normal"),
    ]
    assert limits[0].resets_at == pytest.approx(1791246600.324376)


def test_parse_orders_session_first_and_ignores_unknown_kinds():
    payload = {"limits": [
        {"kind": "weekly_all", "percent": 5, "severity": "normal", "resets_at": None},
        {"kind": "monthly_new", "percent": 9, "severity": "normal", "resets_at": None},
        {"kind": "session", "percent": 1, "severity": "normal", "resets_at": None},
    ]}
    assert [x.kind for x in parse_usage(payload)] == ["session", "weekly_all"]


def test_parse_drops_scoped_without_model_name():
    payload = {"limits": [
        {"kind": "weekly_scoped", "percent": 3, "severity": "normal", "scope": None},
        {"kind": "weekly_scoped", "percent": 3, "severity": "normal",
         "scope": {"model": {"display_name": "  "}}},
    ]}
    assert parse_usage(payload) == []


@pytest.mark.parametrize("percent", [float("nan"), True, "14", None])
def test_parse_drops_invalid_percent(percent):
    assert parse_usage({"limits": [{"kind": "session", "percent": percent}]}) == []


def test_parse_clamps_percent_and_normalizes_severity():
    payload = {"limits": [
        {"kind": "session", "percent": 140.4, "severity": "explodiu"},
        {"kind": "weekly_all", "percent": -3, "severity": "critical"},
    ]}
    limits = parse_usage(payload)
    assert (limits[0].percent, limits[0].severity) == (100, "normal")
    assert (limits[1].percent, limits[1].severity) == (0, "critical")
    assert limits[0].resets_at is None


@pytest.mark.parametrize("payload", [None, [], {}, {"limits": "x"}])
def test_parse_rejects_payload_without_limits(payload):
    with pytest.raises(UsageCheckError, match="Resposta inesperada"):
        parse_usage(payload)


# plan_label ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subscription", "tier", "expected"),
    [
        ("max", "default_claude_max_20x", "Max 20x"),
        ("max", "default_claude_max_5x", "Max 5x"),
        ("pro", "default_claude_pro", "Pro"),
        ("pro", None, "Pro"),
        ("team", 3, "Team"),
        ("enterprise", "", "Enterprise"),
        ("free", None, "Free"),
        ("MAX", "default_claude_max_5x", "Max 5x"),
        ("novo_plano", None, "Novo_plano"),
        (None, "x_20x", None),
        ("", None, None),
        (5, None, None),
    ],
)
def test_plan_label(subscription, tier, expected):
    assert plan_label(subscription, tier) == expected


# read_access_token -----------------------------------------------------------


def test_read_credentials_returns_token_and_plan(tmp_path):
    assert read_credentials(write_credentials(tmp_path / "c")) == (TOKEN, "Max 20x")


def test_read_credentials_without_plan_fields(tmp_path):
    (tmp_path / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": TOKEN}}))
    assert read_credentials(tmp_path) == (TOKEN, None)


def test_read_credentials_keeps_validations(tmp_path):
    with pytest.raises(UsageCheckError, match="Credenciais do CLI não encontradas"):
        read_credentials(tmp_path / "nada")
    folder = write_credentials(tmp_path / "c", expires_at=1_000_000)
    with pytest.raises(UsageCheckError, match="Token do CLI vencido; renova no próximo uso do CLI"):
        read_credentials(folder, clock=lambda: 1_001.0)


def test_read_token(tmp_path):
    assert read_access_token(write_credentials(tmp_path / "c")) == TOKEN


def test_read_token_missing_file(tmp_path):
    with pytest.raises(UsageCheckError, match="Credenciais do CLI não encontradas"):
        read_access_token(tmp_path / "nada")


@pytest.mark.parametrize("content", ["{", "[]", '{"claudeAiOauth": {}}', '{"claudeAiOauth": {"accessToken": ""}}'])
def test_read_token_bad_file(tmp_path, content):
    (tmp_path / ".credentials.json").write_text(content)
    with pytest.raises(UsageCheckError, match="Credenciais do CLI não encontradas"):
        read_access_token(tmp_path)


def test_read_token_expired(tmp_path):
    folder = write_credentials(tmp_path / "c", expires_at=1_000_000)  # ms
    with pytest.raises(UsageCheckError, match="Token do CLI vencido; renova no próximo uso do CLI"):
        read_access_token(folder, clock=lambda: 1_001.0)


@pytest.mark.parametrize("token", ["abc\nX", "abc def", "abc\tX", "tokén", "abc\r", "\x00abc"])
def test_read_credentials_rejects_token_with_unsafe_characters(tmp_path, token):
    folder = write_credentials(tmp_path / "c", token=token)
    with pytest.raises(UsageCheckError, match="Credenciais do CLI não encontradas") as info:
        read_credentials(folder)
    assert "abc" not in str(info.value)


def test_read_token_not_yet_expired(tmp_path):
    folder = write_credentials(tmp_path / "c", expires_at=2_000_000)
    assert read_access_token(folder, clock=lambda: 1_001.0) == TOKEN


# request_usage ---------------------------------------------------------------


def test_request_sends_token_and_beta_header(tmp_path):
    seen: list = []
    folder = write_credentials(tmp_path / "c")
    report = request_usage(folder, opener_returning(json.dumps(REAL_PAYLOAD).encode(), seen))
    assert len(report.limits) == 3
    request, timeout = seen[0]
    assert request.full_url == USAGE_URL
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request.get_header("Anthropic-beta") == OAUTH_BETA
    assert timeout == 10


def test_request_authorization_is_not_redirectable(tmp_path):
    seen: list = []
    folder = write_credentials(tmp_path / "c")
    request_usage(folder, opener_returning(json.dumps(REAL_PAYLOAD).encode(), seen))
    request = seen[0][0]
    assert request.unredirected_hdrs.get("Authorization") == f"Bearer {TOKEN}"
    assert "Authorization" not in request.headers


def _serve(handler_class):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_request_does_not_follow_redirects(tmp_path, monkeypatch):
    received: list[str | None] = []

    class Second(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"limits": []}')

        def log_message(self, *args):
            pass

    second, second_thread = _serve(Second)

    class First(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{second.server_port}/x")
            self.end_headers()

        def log_message(self, *args):
            pass

    first, first_thread = _serve(First)
    try:
        monkeypatch.setattr(usage, "USAGE_URL", f"http://127.0.0.1:{first.server_port}/api/oauth/usage")
        folder = write_credentials(tmp_path / "c")
        with pytest.raises(UsageCheckError) as info:
            request_usage(folder)
        assert str(info.value) == "Consulta de uso falhou (HTTP 302)"
        _assert_no_token(info.value)
        assert received == []
    finally:
        for server, thread in ((first, first_thread), (second, second_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def test_request_unexpected_error_hides_the_token(tmp_path):
    folder = write_credentials(tmp_path / "c")
    leak = ValueError(f"Invalid header value b'Bearer {TOKEN}'")
    with pytest.raises(UsageCheckError) as info:
        request_usage(folder, opener_raising(leak))
    assert str(info.value) == "Consulta de uso falhou"
    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    _assert_no_token(info.value)


def test_request_report_has_plan_from_credentials(tmp_path):
    folder = write_credentials(tmp_path / "c", tier="default_claude_max_5x")
    report = request_usage(folder, opener_returning(json.dumps(REAL_PAYLOAD).encode()))
    assert isinstance(report, UsageReport)
    assert report.plan == "Max 5x"
    assert TOKEN not in repr(report)


def _assert_no_token(exc: BaseException) -> None:
    for item in (exc, exc.__cause__, exc.__context__):
        assert item is None or TOKEN not in repr(item) and TOKEN not in str(item)


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (401, "Login do CLI expirado"),
        (403, "Login do CLI expirado"),
        (500, "Consulta de uso falhou (HTTP 500)"),
    ],
)
def test_request_http_errors(tmp_path, error, text):
    folder = write_credentials(tmp_path / "c")
    http_error = urllib.error.HTTPError(USAGE_URL, error, "x", {}, None)
    with pytest.raises(UsageCheckError) as info:
        request_usage(folder, opener_raising(http_error))
    assert str(info.value) == text
    _assert_no_token(info.value)


def test_request_network_error(tmp_path):
    folder = write_credentials(tmp_path / "c")
    with pytest.raises(UsageCheckError, match="Sem conexão com a Anthropic") as info:
        request_usage(folder, opener_raising(urllib.error.URLError("dns")))
    _assert_no_token(info.value)


def test_request_bad_json_and_oversized(tmp_path):
    folder = write_credentials(tmp_path / "c")
    with pytest.raises(UsageCheckError, match="Resposta inesperada"):
        request_usage(folder, opener_returning(b"<html>"))
    with pytest.raises(UsageCheckError, match="Resposta inesperada"):
        request_usage(folder, opener_returning(b" " * 1_000_001))


# UsageChecker -----------------------------------------------------------------

LIMIT = UsageLimit("session", "Sessão", 14, "normal", 1791333000.0)
REPORT = UsageReport([LIMIT], "Max 20x")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_checker(results, *, enabled=True, clock=None):
    published: list[dict] = []
    calls: list[int] = []

    async def fetch():
        calls.append(1)
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    checker = UsageChecker(published.append, enabled=enabled, fetch=fetch, clock=clock or Clock())
    return checker, published, calls


def test_refresh_success_publishes_snapshot():
    checker, published, _ = make_checker([REPORT])
    asyncio.run(checker.refresh())
    snap = checker.snapshot()
    assert snap == {
        "enabled": True,
        "limits": [{"kind": "session", "label": "Sessão", "percent": 14,
                    "severity": "normal", "resets_at": 1791333000.0}],
        "fetched_at": 1000.0,
        "error": None,
        "plan": "Max 20x",
    }
    assert published == [{"session_id": None, "seq": 0, "type": "app.usage", "data": snap}]


def test_error_keeps_old_limits_and_success_clears_error():
    clock = Clock()
    checker, published, _ = make_checker(
        [REPORT, UsageCheckError("Login do CLI expirado"), REPORT], clock=clock
    )
    asyncio.run(checker.refresh())
    clock.now = 2000.0
    asyncio.run(checker.refresh())
    snap = checker.snapshot()
    assert snap["error"] == "Login do CLI expirado"
    assert snap["limits"][0]["percent"] == 14
    assert snap["plan"] == "Max 20x"
    assert snap["fetched_at"] == 1000.0
    asyncio.run(checker.refresh())
    assert checker.snapshot()["error"] is None
    assert len(published) == 3


def test_unexpected_exception_becomes_generic_error():
    checker, _, _ = make_checker([RuntimeError("boom")])
    asyncio.run(checker.refresh())
    assert checker.snapshot()["error"] == "Consulta de uso falhou"


def test_unexpected_exception_never_logs_its_message(caplog):
    caplog.set_level(logging.DEBUG)
    checker, _, _ = make_checker([RuntimeError("SEGREDO"), RuntimeError("SEGREDO")], clock=Clock())
    asyncio.run(checker.refresh())
    asyncio.run(checker.refresh())
    assert checker.snapshot()["error"] == "Consulta de uso falhou"
    for record in caplog.records:
        assert "SEGREDO" not in record.getMessage()
        assert "SEGREDO" not in (record.exc_text or "")
        assert record.exc_info is None
    assert sum("Consulta de uso falhou" in r.getMessage() for r in caplog.records) == 1


def test_same_error_is_logged_once(caplog):
    clock = Clock()
    checker, _, _ = make_checker([UsageCheckError("Login do CLI expirado")] * 3, clock=clock)
    for _ in range(3):
        asyncio.run(checker.refresh())
    assert sum("Login do CLI expirado" in r.getMessage() for r in caplog.records) == 1


def test_wants_refresh_respects_sixty_seconds():
    clock = Clock()
    checker, _, _ = make_checker([REPORT], clock=clock)
    assert checker.wants_refresh() is True
    asyncio.run(checker.refresh())
    clock.now += 59
    assert checker.wants_refresh() is False
    clock.now += 1
    assert checker.wants_refresh() is True


def test_no_second_refresh_while_one_runs():
    gate = asyncio.Event()
    calls: list[int] = []

    async def slow_fetch():
        calls.append(1)
        await gate.wait()
        return REPORT

    checker = UsageChecker(lambda e: None, enabled=True, fetch=slow_fetch, clock=Clock())

    async def scenario():
        first = asyncio.create_task(checker.refresh())
        await asyncio.sleep(0)
        assert checker.wants_refresh() is False
        await checker.refresh()  # returns at once
        gate.set()
        await first

    asyncio.run(scenario())
    assert calls == [1]


def test_disabled_never_fetches():
    checker, published, calls = make_checker([REPORT], enabled=False)
    asyncio.run(checker.refresh())
    asyncio.run(checker.run_periodic(0, 0))
    assert calls == [] and published == []
    assert checker.wants_refresh() is False
    assert checker.snapshot() == {
        "enabled": False, "limits": [], "fetched_at": None, "error": None, "plan": None,
    }


def test_error_keeps_old_plan_and_success_updates_it():
    clock = Clock()
    checker, _, _ = make_checker(
        [REPORT, UsageCheckError("Sem conexão com a Anthropic"), UsageReport([LIMIT], "Pro")],
        clock=clock,
    )
    asyncio.run(checker.refresh())
    asyncio.run(checker.refresh())
    assert checker.snapshot()["plan"] == "Max 20x"
    asyncio.run(checker.refresh())
    assert checker.snapshot()["plan"] == "Pro"


def test_snapshot_without_data_has_no_plan():
    checker, _, _ = make_checker([UsageCheckError("Login do CLI expirado")])
    asyncio.run(checker.refresh())
    assert checker.snapshot()["plan"] is None
