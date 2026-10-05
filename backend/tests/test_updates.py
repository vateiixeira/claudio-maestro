import io
import json
import urllib.error

import pytest

from claudio_maestro import updates
from claudio_maestro.updates import (
    RELEASES_URL,
    ReleaseCheckError,
    ReleaseInfo,
    UpdateChecker,
    parse_release,
    parse_version,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.2.0", (0, 2, 0)),
        ("v0.2.0", (0, 2, 0)),
        (" v1.10.3 ", (1, 10, 3)),
        ("0.2.0-rc1", None),
        ("0.2", None),
        ("abc", None),
        ("", None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_parse_version_compares_numerically():
    assert parse_version("1.10.0") > parse_version("1.9.0")


def _payload(**overrides):
    payload = {
        "tag_name": "v0.2.0",
        "html_url": f"{RELEASES_URL}/tag/v0.2.0",
        "body": "### Adicionado\n- coisa",
        "published_at": "2026-10-06T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_parse_release_reads_fields():
    info = parse_release(_payload())
    assert info == ReleaseInfo(
        version="0.2.0",
        url=f"{RELEASES_URL}/tag/v0.2.0",
        notes="### Adicionado\n- coisa",
        published_at=1791288000.0,
    )


def test_parse_release_rejects_foreign_url():
    assert parse_release(_payload(html_url="https://evil.example/x")).url == RELEASES_URL


def test_parse_release_cuts_long_notes():
    assert len(parse_release(_payload(body="x" * 30_000)).notes) == 20_000


def test_parse_release_tolerates_missing_body_and_date():
    info = parse_release(_payload(body=None, published_at="ontem"))
    assert info.notes == ""
    assert info.published_at is None


@pytest.mark.parametrize("payload", [[], "x", {"tag_name": "nightly"}, {}])
def test_parse_release_rejects_unexpected_shapes(payload):
    with pytest.raises(ReleaseCheckError):
        parse_release(payload)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_get_latest_sends_github_headers():
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["timeout"] = timeout
        return _Response(json.dumps(_payload()).encode())

    info = updates._request_latest(opener)
    assert info is not None and info.version == "0.2.0"
    assert seen["url"] == updates.LATEST_API_URL
    assert seen["headers"]["accept"] == "application/vnd.github+json"
    assert seen["headers"]["user-agent"].startswith("claudio-maestro/")
    assert seen["timeout"] == 10


def test_get_latest_404_means_no_release():
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    assert updates._request_latest(opener) is None


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("u", 403, "rate limited", {}, None),
        urllib.error.URLError("offline"),
        TimeoutError("slow"),
    ],
)
def test_get_latest_failures_raise_check_error(error):
    def opener(request, timeout):
        raise error

    with pytest.raises(ReleaseCheckError):
        updates._request_latest(opener)


def test_get_latest_invalid_json():
    with pytest.raises(ReleaseCheckError):
        updates._request_latest(lambda request, timeout: _Response(b"<html>proxy</html>"))


def _release(version: str) -> ReleaseInfo:
    return ReleaseInfo(version, f"{RELEASES_URL}/tag/v{version}", "notas", 1.0)


def _checker(results, *, enabled=True, current="0.1.0"):
    published = []
    calls = []
    queue = list(results)

    async def fetch():
        calls.append(1)
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    checker = UpdateChecker(
        published.append, enabled=enabled, fetch=fetch, current=lambda: current, clock=lambda: 100.0
    )
    return checker, published, calls


@pytest.mark.anyio
async def test_newer_release_is_available_and_published_once():
    checker, published, _ = _checker([_release("0.2.0"), _release("0.2.0")])
    await checker.check()
    await checker.check()
    state = checker.state()
    assert state["available"] is True
    assert state["latest"]["version"] == "0.2.0"
    assert state["checked_at"] == 100.0
    assert len(published) == 1
    assert published[0] == {"session_id": None, "seq": 0, "type": "app.update", "data": state}


@pytest.mark.anyio
@pytest.mark.parametrize("version", ["0.1.0", "0.0.9"])
async def test_same_or_older_release_is_not_available(version):
    checker, _, _ = _checker([_release(version)])
    await checker.check()
    assert checker.state()["available"] is False


@pytest.mark.anyio
async def test_failure_keeps_previous_result_and_does_not_publish():
    checker, published, _ = _checker([_release("0.2.0"), ReleaseCheckError("offline")])
    await checker.check()
    checker._clock = lambda: 999.0
    await checker.check()
    assert checker.state()["latest"]["version"] == "0.2.0"
    assert checker.state()["checked_at"] == 100.0
    assert len(published) == 1


@pytest.mark.anyio
async def test_unexpected_error_is_swallowed():
    checker, published, _ = _checker([ValueError("bug")])
    await checker.check()
    assert checker.state()["latest"] is None
    assert published == []


@pytest.mark.anyio
async def test_no_release_means_latest_null():
    checker, _, _ = _checker([None])
    await checker.check()
    assert checker.state()["latest"] is None
    assert checker.state()["available"] is False
    assert checker.state()["checked_at"] == 100.0


@pytest.mark.anyio
async def test_disabled_never_fetches():
    checker, published, calls = _checker([_release("0.2.0")], enabled=False)
    await checker.check()
    await checker.run_periodic(0, 0)  # returns at once when disabled
    assert calls == []
    assert published == []
    assert checker.state()["enabled"] is False


@pytest.mark.anyio
async def test_unparsable_current_version_is_never_behind():
    checker, _, _ = _checker([_release("9.0.0")], current="0.2.0.dev1")
    await checker.check()
    assert checker.state()["available"] is False


def test_state_shape_before_any_check():
    checker, _, _ = _checker([])
    assert checker.state() == {
        "enabled": True,
        "current": "0.1.0",
        "available": False,
        "latest": None,
        "checked_at": None,
        "releases_url": RELEASES_URL,
    }
