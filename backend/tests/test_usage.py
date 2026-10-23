import asyncio
import http.server
import io
import json
import logging
import os
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


# Retry-After on HTTP 429 ----------------------------------------------------


def _http_429(headers: dict[str, str] | None, code: int = 429) -> urllib.error.HTTPError:
    import email.message

    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(USAGE_URL, code, "x", message, None)


def _request_failure(tmp_path, error) -> UsageCheckError:
    folder = write_credentials(tmp_path / "c")
    with pytest.raises(UsageCheckError) as info:
        request_usage(folder, opener_raising(error))
    return info.value


def test_usage_check_error_defaults():
    assert UsageCheckError("x").retry_after is None
    assert UsageCheckError("x").rate_limited is False
    assert UsageCheckError("x", rate_limited=True).rate_limited is True
    assert UsageCheckError("x", retry_after=90).retry_after == 90


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("120", 120),
        ("5", 60),
        ("99999", 3600),
        ("60", 60),
        ("3600", 3600),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
        ("abc", None),
        ("1.5", None),
        ("-30", None),
        ("", None),
    ],
)
def test_request_429_reads_retry_after(tmp_path, header, expected):
    error = _request_failure(tmp_path, _http_429({"Retry-After": header}))
    assert str(error) == "Consulta de uso falhou (HTTP 429)"
    assert error.retry_after == expected
    _assert_no_token(error)


def test_request_429_is_rate_limited_and_500_is_not(tmp_path):
    assert _request_failure(tmp_path, _http_429({})).rate_limited is True
    assert _request_failure(tmp_path, _http_429({}, code=500)).rate_limited is False
    assert _request_failure(tmp_path, _http_429({}, code=401)).rate_limited is False


def test_message_alone_does_not_block():
    clock = Clock()
    checker, _, _ = make_checker([UsageCheckError("Consulta de uso falhou (HTTP 429)")], clock=clock)
    asyncio.run(checker.refresh())
    assert checker._blocked_until is None


def test_request_429_without_header_has_no_retry_after(tmp_path):
    error = _request_failure(tmp_path, _http_429({}))
    assert str(error) == "Consulta de uso falhou (HTTP 429)"
    assert error.retry_after is None


def test_request_429_with_headers_none_has_no_retry_after(tmp_path):
    assert _request_failure(tmp_path, _http_429(None)).retry_after is None


def test_request_429_error_is_raised_outside_the_except(tmp_path):
    error = _request_failure(tmp_path, _http_429({"Retry-After": "120"}))
    assert error.__cause__ is None
    assert error.__context__ is None


def test_request_other_http_errors_have_no_retry_after(tmp_path):
    error = _request_failure(tmp_path, _http_429({"Retry-After": "120"}, code=500))
    assert str(error) == "Consulta de uso falhou (HTTP 500)"
    assert error.retry_after is None


# UsageChecker backoff -------------------------------------------------------


def _rate_limited(retry_after=None):
    return UsageCheckError("Consulta de uso falhou (HTTP 429)", retry_after=retry_after, rate_limited=True)


def test_429_blocks_for_five_minutes():
    clock = Clock()
    checker, _, _ = make_checker([_rate_limited()], clock=clock)
    asyncio.run(checker.refresh())
    clock.now = 1000.0 + 299
    assert checker.wants_refresh() is False
    clock.now = 1000.0 + 300
    assert checker.wants_refresh() is True


def test_refresh_during_the_block_does_not_fetch_nor_publish():
    clock = Clock()
    checker, published, calls = make_checker([_rate_limited(), REPORT], clock=clock)
    asyncio.run(checker.refresh())
    assert len(calls) == 1 and len(published) == 1
    clock.now += 100
    asyncio.run(checker.refresh())
    assert len(calls) == 1 and len(published) == 1
    clock.now = 1000.0 + 300
    asyncio.run(checker.refresh())
    assert len(calls) == 2 and len(published) == 2
    assert checker.snapshot()["error"] is None


def test_consecutive_429s_wait_longer_up_to_thirty_minutes():
    clock = Clock()
    checker, _, calls = make_checker([_rate_limited() for _ in range(5)], clock=clock)
    waits = []
    for _ in range(5):
        asyncio.run(checker.refresh())
        waits.append(checker._blocked_until - clock.now)
        clock.now = checker._blocked_until
    assert waits == [300, 600, 1200, 1800, 1800]
    assert len(calls) == 5


def test_retry_after_wins_over_the_growing_wait():
    clock = Clock()
    checker, _, _ = make_checker([_rate_limited(), _rate_limited(retry_after=120)], clock=clock)
    asyncio.run(checker.refresh())
    clock.now = checker._blocked_until
    asyncio.run(checker.refresh())
    assert checker._blocked_until == clock.now + 120
    clock.now += 119
    assert checker.wants_refresh() is False
    clock.now += 1
    assert checker.wants_refresh() is True


def test_success_resets_the_backoff():
    clock = Clock()
    checker, _, _ = make_checker(
        [_rate_limited(), _rate_limited(), REPORT, _rate_limited()], clock=clock
    )
    for _ in range(3):
        asyncio.run(checker.refresh())
        if checker._blocked_until is not None:
            clock.now = checker._blocked_until
    assert checker._blocked_until is None
    assert checker._rate_limited_count == 0
    asyncio.run(checker.refresh())
    assert checker._blocked_until == clock.now + 300


@pytest.mark.parametrize(
    "error",
    [
        UsageCheckError("Login do CLI expirado"),
        UsageCheckError("Consulta de uso falhou (HTTP 500)"),
        UsageCheckError("Sem conexão com a Anthropic"),
        RuntimeError("boom"),
    ],
)
def test_other_errors_do_not_block(error):
    clock = Clock()
    checker, _, _ = make_checker([error], clock=clock)
    asyncio.run(checker.refresh())
    assert checker._blocked_until is None
    assert checker._rate_limited_count == 0
    clock.now += 60
    assert checker.wants_refresh() is True


def test_other_error_during_a_count_keeps_the_block_state():
    clock = Clock()
    checker, _, _ = make_checker(
        [_rate_limited(), UsageCheckError("Sem conexão com a Anthropic")], clock=clock
    )
    asyncio.run(checker.refresh())
    blocked_until = checker._blocked_until
    clock.now = blocked_until
    asyncio.run(checker.refresh())
    assert checker._blocked_until == blocked_until
    assert checker._rate_limited_count == 1


def test_block_is_logged_once_with_the_wait(caplog):
    caplog.set_level(logging.DEBUG)
    clock = Clock()
    checker, _, _ = make_checker([_rate_limited(retry_after=120)], clock=clock)
    asyncio.run(checker.refresh())
    asyncio.run(checker.refresh())
    asyncio.run(checker.refresh())
    blocked = [r for r in caplog.records if "120" in r.getMessage()]
    assert len(blocked) == 1
    assert blocked[0].levelno == logging.WARNING


# Cache of the last good reading ----------------------------------------------


def make_cached(results, cache_path, *, enabled=True, clock=None):
    published: list[dict] = []
    calls: list[int] = []

    async def fetch():
        calls.append(1)
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    checker = UsageChecker(
        published.append, enabled=enabled, fetch=fetch, clock=clock or Clock(), cache_path=cache_path
    )
    return checker, published, calls


def _limit_dict(**changes):
    base = {"kind": "session", "label": "Sessão", "percent": 14, "severity": "normal",
            "resets_at": 1791333000.0}
    return {**base, **changes}


def _write_cache(path: Path, **changes):
    data = {"limits": [_limit_dict()], "plan": "Max 20x", "fetched_at": 900.0, **changes}
    path.write_text(json.dumps(data))
    return path


def test_success_writes_the_cache_with_mode_600(tmp_path):
    path = tmp_path / "data" / "usage.json"
    path.parent.mkdir()
    checker, _, _ = make_cached([REPORT], path)
    asyncio.run(checker.refresh())
    assert (path.stat().st_mode & 0o777) == 0o600
    content = path.read_text()
    assert TOKEN not in content
    assert json.loads(content) == {
        "limits": [_limit_dict()],
        "plan": "Max 20x",
        "fetched_at": 1000.0,
    }
    assert [p.name for p in path.parent.iterdir()] == ["usage.json"]


def test_cache_write_overwrites_the_old_file(tmp_path):
    path = _write_cache(tmp_path / "usage.json")
    path.chmod(0o644)
    checker, _, _ = make_cached([UsageReport([LIMIT], "Pro")], path)
    asyncio.run(checker.refresh())
    assert json.loads(path.read_text())["plan"] == "Pro"
    assert (path.stat().st_mode & 0o777) == 0o600


def test_new_checker_loads_the_cache(tmp_path):
    path = tmp_path / "usage.json"
    first, _, _ = make_cached([REPORT], path)
    asyncio.run(first.refresh())
    second, published, calls = make_cached([], path)
    assert second.snapshot() == {
        "enabled": True,
        "limits": [_limit_dict()],
        "fetched_at": 1000.0,
        "error": None,
        "plan": "Max 20x",
    }
    assert published == [] and calls == []


def test_cache_drops_limits_already_reset(tmp_path):
    clock = Clock()
    clock.now = 1_000.0
    path = _write_cache(
        tmp_path / "usage.json",
        limits=[
            _limit_dict(kind="session", resets_at=1_000.0),
            _limit_dict(kind="weekly_all", label="Semana", resets_at=999.0),
            _limit_dict(kind="weekly_scoped", label="Semana · Fable", resets_at=1_001.0),
            _limit_dict(kind="weekly_scoped", label="Semana · Outro", resets_at=None),
        ],
    )
    checker, _, _ = make_cached([], path, clock=clock)
    assert [x["label"] for x in checker.snapshot()["limits"]] == ["Semana · Fable", "Semana · Outro"]


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "",
        "[]",
        '"x"',
        "null",
        '{"plan": "Pro", "fetched_at": 1}',
        '{"limits": "x", "plan": null, "fetched_at": 1}',
        '{"limits": [], "plan": 5, "fetched_at": 1}',
        '{"limits": [], "plan": null}',
        '{"limits": [], "plan": null, "fetched_at": "x"}',
        '{"limits": [], "plan": null, "fetched_at": true}',
        '{"limits": [], "plan": null, "fetched_at": NaN}',
    ],
)
def test_malformed_cache_loads_empty(tmp_path, content):
    path = tmp_path / "usage.json"
    path.write_text(content)
    checker, _, _ = make_cached([], path)
    assert checker.snapshot() == {
        "enabled": True, "limits": [], "fetched_at": None, "error": None, "plan": None,
    }


@pytest.mark.parametrize(
    "bad",
    [
        "texto",
        {"kind": "session"},
        _limit_dict(kind="monthly"),
        _limit_dict(kind=3),
        _limit_dict(label=None),
        _limit_dict(percent="14"),
        _limit_dict(percent=True),
        _limit_dict(percent=float("nan")),
        _limit_dict(percent=101),
        _limit_dict(percent=-1),
        _limit_dict(severity="explodiu"),
        _limit_dict(resets_at="amanhã"),
        _limit_dict(resets_at=True),
        _limit_dict(resets_at=float("inf")),
    ],
)
def test_cache_with_an_invalid_limit_is_ignored_entirely(tmp_path, bad):
    path = _write_cache(tmp_path / "usage.json", limits=[_limit_dict(), bad])
    # json.dumps writes NaN/Infinity, which json.loads accepts; the validation must refuse them.
    checker, _, _ = make_cached([], path)
    snap = checker.snapshot()
    assert snap["limits"] == [] and snap["plan"] is None and snap["fetched_at"] is None
    assert snap["error"] is None


def test_cache_larger_than_64_kib_is_ignored(tmp_path):
    path = tmp_path / "usage.json"
    padding = " " * (64 * 1024)
    path.write_text(json.dumps({"limits": [_limit_dict()], "plan": None, "fetched_at": 1.0}) + padding)
    checker, _, _ = make_cached([], path)
    assert checker.snapshot()["limits"] == []


def test_cache_missing_file_loads_empty(tmp_path):
    checker, _, _ = make_cached([], tmp_path / "nope" / "usage.json")
    assert checker.snapshot()["limits"] == []


def test_disabled_checker_neither_reads_nor_writes_the_cache(tmp_path):
    path = _write_cache(tmp_path / "usage.json")
    before = path.read_text()
    checker, published, calls = make_cached([REPORT], path, enabled=False)
    assert checker.snapshot()["limits"] == []
    asyncio.run(checker.refresh())
    assert calls == [] and published == []
    assert path.read_text() == before
    fresh = tmp_path / "other.json"
    other, _, _ = make_cached([REPORT], fresh, enabled=False)
    asyncio.run(other.refresh())
    assert not fresh.exists()


def test_429_after_loading_the_cache_keeps_the_limits_and_sets_the_error(tmp_path):
    clock = Clock()
    path = _write_cache(tmp_path / "usage.json")
    checker, published, _ = make_cached([_rate_limited()], path, clock=clock)
    asyncio.run(checker.refresh())
    snap = checker.snapshot()
    assert snap["error"] == "Consulta de uso falhou (HTTP 429)"
    assert [x["percent"] for x in snap["limits"]] == [14]
    assert snap["plan"] == "Max 20x"
    assert snap["fetched_at"] == 900.0
    assert published[-1]["data"] == snap


def test_failed_fetch_does_not_touch_the_cache(tmp_path):
    path = _write_cache(tmp_path / "usage.json")
    before = path.read_text()
    checker, _, _ = make_cached([_rate_limited()], path)
    asyncio.run(checker.refresh())
    assert path.read_text() == before


def test_unwritable_cache_folder_does_not_break_refresh(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    folder = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        checker, published, _ = make_cached([REPORT], folder / "usage.json")
        asyncio.run(checker.refresh())
    finally:
        folder.chmod(0o700)
    snap = checker.snapshot()
    assert snap["error"] is None and snap["limits"][0]["percent"] == 14
    assert len(published) == 1
    assert not (folder / "usage.json").exists()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_replace_failure_does_not_break_refresh_and_cleans_the_temp_file(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError(f"SEGREDO {src} {dst}")

    monkeypatch.setattr(usage.os, "replace", boom)
    folder = tmp_path / "data"
    folder.mkdir()
    checker, published, _ = make_cached([REPORT], folder / "usage.json")
    asyncio.run(checker.refresh())
    snap = checker.snapshot()
    assert snap["error"] is None and snap["fetched_at"] == 1000.0
    assert len(published) == 1
    assert list(folder.iterdir()) == []


def test_cache_write_failure_log_has_no_details(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    def boom(src, dst):
        raise OSError("SEGREDO")

    monkeypatch.setattr(usage.os, "replace", boom)
    checker, _, _ = make_cached([REPORT], tmp_path / "usage.json")
    asyncio.run(checker.refresh())
    for record in caplog.records:
        assert "SEGREDO" not in record.getMessage()
        assert "SEGREDO" not in (record.exc_text or "")
        assert record.exc_info is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# Cache hardening --------------------------------------------------------------


def test_cache_symlink_is_ignored(tmp_path):
    real = _write_cache(tmp_path / "real.json")
    link = tmp_path / "usage.json"
    link.symlink_to(real)
    checker, _, _ = make_cached([], link)
    assert checker.snapshot()["limits"] == []


def test_cache_fifo_is_ignored_without_blocking(tmp_path):
    fifo = tmp_path / "usage.json"
    os.mkfifo(fifo)
    result: list = []
    thread = threading.Thread(target=lambda: result.append(make_cached([], fifo)[0]), daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result[0].snapshot()["limits"] == []


def test_cache_directory_is_ignored(tmp_path):
    folder = tmp_path / "usage.json"
    folder.mkdir()
    checker, _, _ = make_cached([], folder)
    assert checker.snapshot()["limits"] == []


@pytest.mark.parametrize("fetched_at", [-5, 0, 1e300, 1301.0])
def test_cache_with_implausible_fetched_at_is_ignored(tmp_path, fetched_at):
    path = _write_cache(tmp_path / "usage.json", fetched_at=fetched_at)
    checker, _, _ = make_cached([], path)  # clock is 1000
    assert checker.snapshot()["limits"] == []


def test_cache_fetched_at_slightly_in_the_future_is_kept(tmp_path):
    path = _write_cache(tmp_path / "usage.json", fetched_at=1300.0)
    checker, _, _ = make_cached([], path)
    assert checker.snapshot()["fetched_at"] == 1300.0


def test_cache_label_longer_than_200_chars_is_ignored(tmp_path):
    path = _write_cache(tmp_path / "usage.json", limits=[_limit_dict(label="x" * 201)])
    checker, _, _ = make_cached([], path)
    assert checker.snapshot()["limits"] == []
    path = _write_cache(tmp_path / "usage.json", limits=[_limit_dict(label="x" * 200)])
    checker, _, _ = make_cached([], path)
    assert len(checker.snapshot()["limits"]) == 1
