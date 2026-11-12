"""Pictures of tool results, read on demand from the session's `.jsonl`."""

import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from claudio_maestro import history
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
MISSING = "00000000-0000-0000-0000-000000000000"
PNG = b"\x89PNG\r\n\x1a\n" + b"png-bytes-1"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"png-bytes-2"
JPEG = b"\xff\xd8\xff\xe0jpeg-bytes"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def image_block(data: bytes | str, media_type: str = "image/png") -> dict[str, Any]:
    encoded = data if isinstance(data, str) else b64(data)
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": encoded}}


def result_line(tool_use_id: str, content: list[dict[str, Any]]) -> str:
    entry = {"type": "user", "uuid": f"u-{tool_use_id}", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}]}}
    return json.dumps(entry) + "\n"


def write_session(folder: Path, *lines: str, name: str = "sess") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    path.write_text("".join(lines))
    return path


# history.read_tool_result_image ----------------------------------------------


def test_reads_the_nth_image_of_the_result(tmp_path: Path):
    path = write_session(
        tmp_path,
        result_line("toolu_other", [image_block(JPEG, "image/jpeg")]),
        result_line("toolu_a", [{"type": "text", "text": "ok"}, image_block(PNG), image_block(PNG2)]),
    )

    assert history.read_tool_result_image(path, "toolu_a", 0) == (PNG, "image/png")
    assert history.read_tool_result_image(path, "toolu_a", 1) == (PNG2, "image/png")
    assert history.read_tool_result_image(path, "toolu_other", 0) == (JPEG, "image/jpeg")


def test_missing_id_index_or_non_list_content_is_none(tmp_path: Path):
    path = write_session(
        tmp_path,
        result_line("toolu_a", [image_block(PNG)]),
        json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_text", "content": "texto"}]}}) + "\n",
        "linha quebrada toolu_a\n",
    )

    assert history.read_tool_result_image(path, "toolu_zzz", 0) is None
    assert history.read_tool_result_image(path, "toolu_a", 1) is None
    assert history.read_tool_result_image(path, "toolu_text", 0) is None
    assert history.read_tool_result_image(tmp_path / "nao-existe.jsonl", "toolu_a", 0) is None


def test_the_id_must_match_the_tool_result_not_any_text_of_the_line(tmp_path: Path):
    mention = {"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": "veja toolu_a"}]}}
    path = write_session(tmp_path, json.dumps(mention) + "\n",
                         result_line("toolu_b", [image_block(PNG)]))

    assert history.read_tool_result_image(path, "toolu_a", 0) is None


def test_finds_the_image_in_a_subagent_file(tmp_path: Path):
    path = write_session(tmp_path, result_line("toolu_main", [image_block(PNG)]))
    subagents = tmp_path / "sess" / "subagents"
    subagents.mkdir(parents=True)
    (subagents / "agent-1.jsonl").write_text(result_line("toolu_sub", [image_block(JPEG, "image/jpeg")]))
    (subagents / "agent-1.meta.json").write_text("{}")

    assert history.read_tool_result_image(path, "toolu_sub", 0) == (JPEG, "image/jpeg")


def test_subagent_symlinks_are_ignored(tmp_path: Path):
    path = write_session(tmp_path, result_line("toolu_main", [image_block(PNG)]))
    outside = tmp_path / "outside.jsonl"
    outside.write_text(result_line("toolu_sub", [image_block(PNG2)]))
    subagents = tmp_path / "sess" / "subagents"
    subagents.mkdir(parents=True)
    os.symlink(outside, subagents / "agent-1.jsonl")

    assert history.read_tool_result_image(path, "toolu_sub", 0) is None


def test_subagent_folder_that_is_a_symlink_is_ignored(tmp_path: Path):
    path = write_session(tmp_path, result_line("toolu_main", [image_block(PNG)]))
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "agent-1.jsonl").write_text(result_line("toolu_sub", [image_block(PNG2)]))
    (tmp_path / "sess").mkdir()
    os.symlink(real, tmp_path / "sess" / "subagents")

    assert history.read_tool_result_image(path, "toolu_sub", 0) is None


def test_subagent_files_are_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(history, "SUBAGENT_FILES_MAX", 1)
    path = write_session(tmp_path, result_line("toolu_main", [image_block(PNG)]))
    subagents = tmp_path / "sess" / "subagents"
    subagents.mkdir(parents=True)
    (subagents / "agent-1.jsonl").write_text("")
    (subagents / "agent-2.jsonl").write_text(result_line("toolu_sub", [image_block(PNG2)]))

    assert history.read_tool_result_image(path, "toolu_sub", 0) is None


def test_only_raster_media_types_are_allowed(tmp_path: Path):
    svg = image_block(b"<svg onload=alert(1)/>", "image/svg+xml")
    path = write_session(tmp_path, result_line("toolu_svg", [svg]),
                         result_line("toolu_gif", [image_block(b"GIF89a", "image/gif")]),
                         result_line("toolu_webp", [image_block(b"RIFFxxxxWEBP", "image/webp")]))

    with pytest.raises(history.ToolImageTypeNotAllowed):
        history.read_tool_result_image(path, "toolu_svg", 0)
    assert history.read_tool_result_image(path, "toolu_gif", 0) == (b"GIF89a", "image/gif")
    assert history.read_tool_result_image(path, "toolu_webp", 0)[1] == "image/webp"


def test_invalid_base64_and_non_base64_sources_are_none(tmp_path: Path):
    url_block = {"type": "image", "source": {"type": "url", "url": "http://x/y.png"}}
    path = write_session(tmp_path, result_line("toolu_bad", [image_block("não é base64!!")]),
                         result_line("toolu_url", [url_block]))

    assert history.read_tool_result_image(path, "toolu_bad", 0) is None
    assert history.read_tool_result_image(path, "toolu_url", 0) is None


def test_image_over_the_limit_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(history, "TOOL_IMAGE_MAX_BYTES", 10)
    path = write_session(tmp_path, result_line("toolu_big", [image_block(b"x" * 11)]),
                         result_line("toolu_ok", [image_block(b"x" * 10)]))

    with pytest.raises(history.ToolImageTooLarge):
        history.read_tool_result_image(path, "toolu_big", 0)
    assert history.read_tool_result_image(path, "toolu_ok", 0) == (b"x" * 10, "image/png")


def realistic_line(tool_use_id: str, data: bytes) -> str:
    """A line as the CLI writes a Read of a picture: the base64 is in `message.content` and
    again in `toolUseResult`."""
    encoded = b64(data)
    entry = {"type": "user", "uuid": f"u-{tool_use_id}",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": tool_use_id,
                  "content": [image_block(encoded)]}]},
             "toolUseResult": {"type": "image", "file": {"base64": encoded, "type": "image/png"}}}
    return json.dumps(entry) + "\n"


def test_picture_at_the_limit_is_served_even_though_its_base64_appears_twice(tmp_path: Path):
    limit = history.TOOL_IMAGE_MAX_BYTES
    at_limit = b"\x89PNG" + b"\0" * (limit - 4)
    path = write_session(tmp_path, realistic_line("toolu_edge", at_limit))

    found = history.read_tool_result_image(path, "toolu_edge", 0)

    assert found is not None and len(found[0]) == limit and found[1] == "image/png"


def test_picture_just_over_the_limit_is_413_not_dropped_as_a_long_line(tmp_path: Path):
    over = b"\x89PNG" + b"\0" * history.TOOL_IMAGE_MAX_BYTES
    path = write_session(tmp_path, realistic_line("toolu_over", over))

    with pytest.raises(history.ToolImageTooLarge):
        history.read_tool_result_image(path, "toolu_over", 0)


def test_main_file_that_is_a_symlink_or_a_fifo_is_not_read(tmp_path: Path):
    real = write_session(tmp_path, result_line("toolu_a", [image_block(PNG)]), name="real")
    link = tmp_path / "link.jsonl"
    os.symlink(real, link)
    fifo = tmp_path / "fifo.jsonl"
    os.mkfifo(fifo)

    assert history.read_tool_result_image(real, "toolu_a", 0) == (PNG, "image/png")
    assert history.read_tool_result_image(link, "toolu_a", 0) is None
    assert history.read_tool_result_image(fifo, "toolu_a", 0) is None  # and does not block


# Route ------------------------------------------------------------------------


@pytest.fixture
def api():
    app = create_app(agent_factory=FakeAgentFactory(), history_exists=lambda sid, cwd: False)
    with TestClient(app, base_url=BACKEND_URL,
                    headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as client:
        yield client


@pytest.fixture
def session(api: TestClient, home: Path) -> dict[str, Any]:
    folder = home / "app"
    folder.mkdir()
    project = api.post("/api/projects", json={"name": "app", "path": str(folder),
                                              "color": "#ff8800"}).json()
    response = api.post(f"/api/projects/{project['id']}/sessions")
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The session file resolved by the app: written by each test into `tmp_path/history`."""
    folder = tmp_path / "history"
    asked: list[tuple[str, str]] = []

    def resolve(session_id: str, directory: str) -> Path:
        asked.append((session_id, directory))
        return folder / f"{session_id}.jsonl"

    monkeypatch.setattr("claudio_maestro.history.sdk_session_file", resolve)
    resolve.folder = folder  # type: ignore[attr-defined]
    resolve.asked = asked  # type: ignore[attr-defined]
    return resolve


def url(session_id: str, tool_use_id: str, index: int | str) -> str:
    return f"/api/sessions/{session_id}/tool-results/{tool_use_id}/images/{index}"


def test_route_serves_the_image_from_the_main_file(api, session, transcript):
    sid = session["session_id"]
    write_session(transcript.folder, result_line("toolu_a", [image_block(PNG), image_block(JPEG, "image/jpeg")]),
                  name=sid)

    first = api.get(url(sid, "toolu_a", 0))
    second = api.get(url(sid, "toolu_a", 1))

    assert first.status_code == 200 and first.content == PNG
    assert first.headers["content-type"] == "image/png"
    assert second.status_code == 200 and second.content == JPEG
    assert second.headers["content-type"] == "image/jpeg"
    assert transcript.asked[0][0] == sid


def test_route_sends_the_hardening_headers(api, session, transcript):
    sid = session["session_id"]
    write_session(transcript.folder, result_line("toolu_a", [image_block(PNG)]), name=sid)

    headers = api.get(url(sid, "toolu_a", 0)).headers

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["content-security-policy"] == "default-src 'none'"
    assert headers["cache-control"] == "private, max-age=86400"


def test_route_finds_the_image_in_a_subagent_file(api, session, transcript):
    sid = session["session_id"]
    write_session(transcript.folder, result_line("toolu_a", [image_block(PNG)]), name=sid)
    subagents = transcript.folder / sid / "subagents"
    subagents.mkdir(parents=True)
    (subagents / "agent-x.jsonl").write_text(result_line("toolu_sub", [image_block(PNG2)]))

    response = api.get(url(sid, "toolu_sub", 0))

    assert response.status_code == 200 and response.content == PNG2


def test_route_404_for_unknown_id_index_file_or_session(api, session, transcript):
    sid = session["session_id"]
    assert api.get(url(sid, "toolu_a", 0)).status_code == 404  # no file yet
    write_session(transcript.folder, result_line("toolu_a", [image_block(PNG)]), name=sid)

    assert api.get(url(sid, "toolu_zzz", 0)).status_code == 404
    assert api.get(url(sid, "toolu_a", 1)).status_code == 404
    assert api.get(url(MISSING, "toolu_a", 0)).status_code == 404


def test_route_404_when_the_sdk_cannot_resolve_the_file(api, session, monkeypatch):
    monkeypatch.setattr("claudio_maestro.history.sdk_session_file", lambda sid, directory: None)

    assert api.get(url(session["session_id"], "toolu_a", 0)).status_code == 404


@pytest.mark.parametrize("tool_use_id", ["a..b", "a b", "a" * 129, "toolu.a", "toolu;a"])
def test_route_422_for_an_invalid_tool_use_id(api, session, transcript, tool_use_id):
    assert api.get(url(session["session_id"], tool_use_id, 0)).status_code == 422


def test_route_does_not_turn_the_id_into_a_path(api, session, transcript):
    sid = session["session_id"]
    # A slash splits the path: the route does not match at all.
    assert api.get(f"/api/sessions/{sid}/tool-results/a/b/images/0").status_code == 404
    # `..` is normalized away by the client and `%2F` is decoded to a slash by the server:
    # either way the route does not match, and nothing outside the session file is read.
    assert api.get(f"/api/sessions/{sid}/tool-results/../images/0").status_code in (404, 422)
    assert api.get(f"/api/sessions/{sid}/tool-results/toolu%2Fa/images/0").status_code == 404
    assert api.get(f"/api/sessions/{sid}/tool-results/%2E%2E/images/0").status_code == 422


@pytest.mark.parametrize("index", [100, -1, "x", 1000])
def test_route_422_for_an_invalid_index(api, session, transcript, index):
    assert api.get(url(session["session_id"], "toolu_a", index)).status_code == 422


def test_route_accepts_the_last_valid_index(api, session, transcript):
    sid = session["session_id"]
    write_session(transcript.folder, result_line("toolu_a", [image_block(PNG)]), name=sid)

    assert api.get(url(sid, "toolu_a", 99)).status_code == 404


def test_route_415_for_a_type_that_is_not_allowed(api, session, transcript):
    sid = session["session_id"]
    write_session(transcript.folder,
                  result_line("toolu_svg", [image_block(b"<svg/>", "image/svg+xml")]), name=sid)

    assert api.get(url(sid, "toolu_svg", 0)).status_code == 415


def test_route_413_for_an_image_over_the_limit(api, session, transcript, monkeypatch):
    sid = session["session_id"]
    monkeypatch.setattr(history, "TOOL_IMAGE_MAX_BYTES", 4)
    write_session(transcript.folder, result_line("toolu_big", [image_block(PNG)]), name=sid)

    assert api.get(url(sid, "toolu_big", 0)).status_code == 413


def test_route_requires_the_maestro_header(api, session, transcript):
    sid = session["session_id"]
    write_session(transcript.folder, result_line("toolu_a", [image_block(PNG)]), name=sid)

    response = api.get(url(sid, "toolu_a", 0), headers={"x-maestro": ""})

    assert response.status_code == 403
