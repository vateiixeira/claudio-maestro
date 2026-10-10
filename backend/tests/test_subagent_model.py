"""The model each subagent runs on (`subagent["model"]`)."""

import json
import os
import threading
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock
from history_fakes import assistant_entry, user_entry

from claudio_maestro.agent.fake import response_messages
from claudio_maestro.conversation import ConversationBuilder
from claudio_maestro.history import (
    read_subagent_models,
    read_transcript_at,
    read_transcript_file,
)

# Taken at import time: conftest replaces `history.sdk_read_transcript` in every test.
from claudio_maestro.history import sdk_read_transcript as REAL_SDK_READ_TRANSCRIPT

SID = "s-1"


def agent_call(**extra: Any) -> list:
    return response_messages(
        SID,
        [ToolUseBlock(id="toolu_agent", name="Agent",
                      input={"description": "Explorar", "subagent_type": "Explore",
                             "prompt": "x", **extra})],
        stop_reason="tool_use",
    )


def reply(model: str | None, parent: str | None, message_id: str = "msg_sub") -> AssistantMessage:
    return AssistantMessage(
        content=[TextBlock(text="oi")],
        model=model or "",
        parent_tool_use_id=parent,
        message_id=message_id,
        session_id=SID,
    )


def feed(builder: ConversationBuilder, messages) -> list:
    events = []
    for message in messages:
        events.extend(builder.handle(message))
    return events


def sub_of(builder: ConversationBuilder) -> dict:
    [item] = [i for i in builder.snapshot() if i["type"] == "tool" and i["name"] == "Agent"]
    return item["subagent"]


def test_subagent_starts_without_a_model():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    assert sub_of(builder)["model"] is None


def test_model_of_the_agent_input_is_the_fallback():
    builder = ConversationBuilder()
    feed(builder, agent_call(model="haiku"))
    assert sub_of(builder)["model"] == "haiku"


def test_inherit_and_empty_input_model_are_not_a_fallback():
    for value in ("inherit", "", "INHERIT"):
        builder = ConversationBuilder()
        feed(builder, agent_call(model=value))
        assert sub_of(builder)["model"] is None


def test_input_model_that_is_not_text_is_ignored():
    builder = ConversationBuilder()
    feed(builder, agent_call(model=3))
    assert sub_of(builder)["model"] is None


def test_subagent_message_sets_the_real_model_and_announces_it():
    builder = ConversationBuilder()
    feed(builder, agent_call())

    events = builder.handle(reply("claude-sonnet-5-5", "toolu_agent"))

    assert sub_of(builder)["model"] == "claude-sonnet-5-5"
    upserts = [e for e in events if e.type == "item.upsert" and e.data["id"] != "msg_sub:0"]
    assert [e.data["subagent"]["model"] for e in upserts] == ["claude-sonnet-5-5"]


def test_real_model_overrides_the_input_fallback():
    builder = ConversationBuilder()
    feed(builder, agent_call(model="haiku"))

    builder.handle(reply("claude-haiku-4-5-20251001", "toolu_agent"))

    assert sub_of(builder)["model"] == "claude-haiku-4-5-20251001"


def test_unchanged_model_does_not_announce_again():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    builder.handle(reply("claude-sonnet-5-5", "toolu_agent", "msg_a"))

    events = builder.handle(reply("claude-sonnet-5-5", "toolu_agent", "msg_b"))

    assert [e.data["id"] for e in events if e.type == "item.upsert"] == ["msg_b:0"]


def test_main_session_message_does_not_touch_the_subagent():
    builder = ConversationBuilder()
    feed(builder, agent_call(model="haiku"))

    builder.handle(reply("claude-opus-4-7", None))

    assert sub_of(builder)["model"] == "haiku"


def test_empty_or_synthetic_model_is_ignored():
    builder = ConversationBuilder()
    feed(builder, agent_call())

    builder.handle(reply(None, "toolu_agent", "msg_a"))
    builder.handle(reply("<synthetic>", "toolu_agent", "msg_b"))

    assert sub_of(builder)["model"] is None


def test_message_of_a_call_that_is_not_a_subagent_is_ignored():
    builder = ConversationBuilder()
    feed(builder, response_messages(
        SID, [ToolUseBlock(id="toolu_bash", name="Bash", input={"command": "ls"})],
        stop_reason="tool_use"))

    builder.handle(reply("claude-sonnet-5-5", "toolu_bash"))

    [bash] = [i for i in builder.snapshot() if i["type"] == "tool"]
    assert bash.get("subagent") is None


# History ------------------------------------------------------------------


def write_session(tmp_path: Path) -> Path:
    path = tmp_path / "proj" / "sess.jsonl"
    path.parent.mkdir(parents=True)
    call = {"type": "tool_use", "id": "toolu_a", "name": "Agent",
            "input": {"description": "d", "subagent_type": "Explore", "prompt": "x"}}
    lines = [
        {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": "s",
         "message": {"role": "user", "content": "oi"}},
        {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "sessionId": "s",
         "message": {"id": "m1", "role": "assistant", "content": [call]}},
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def write_subagent(path: Path, name: str, meta: dict, assistant_models: list[str]) -> None:
    folder = path.parent / path.stem / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"agent-{name}.meta.json").write_text(json.dumps(meta))
    lines = [{"type": "user", "message": {"role": "user", "content": "x"}}]
    lines += [{"type": "assistant", "message": {"role": "assistant", "model": m, "content": []}}
              for m in assistant_models]
    (folder / f"agent-{name}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))


def test_transcript_without_subagent_folder_has_no_models(tmp_path):
    assert read_transcript_file(write_session(tmp_path), with_subagents=True).subagent_models == {}


def test_transcript_reads_the_model_of_the_first_assistant_message(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a", "model": "sonnet"},
                   ["<synthetic>", "claude-sonnet-5-5", "claude-opus-4-7"])

    assert read_transcript_file(path, with_subagents=True).subagent_models == {"toolu_a": "claude-sonnet-5-5"}


def test_transcript_falls_back_to_the_meta_model(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a", "model": "sonnet"}, [])

    assert read_transcript_file(path, with_subagents=True).subagent_models == {"toolu_a": "sonnet"}


def test_transcript_ignores_broken_meta_files(tmp_path):
    path = write_session(tmp_path)
    folder = path.parent / path.stem / "subagents"
    folder.mkdir(parents=True)
    (folder / "agent-bad.meta.json").write_text("{not json")
    (folder / "agent-nomodel.meta.json").write_text(json.dumps({"toolUseId": "toolu_z"}))
    (folder / "agent-notid.meta.json").write_text(json.dumps({"model": "haiku"}))

    assert read_transcript_file(path, with_subagents=True).subagent_models == {}


def test_transcript_does_not_read_subagents_unless_asked(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a"}, ["claude-sonnet-5-5"])

    assert read_transcript_file(path).subagent_models == {}


def test_read_transcript_at_skips_subagents_by_default(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a"}, ["claude-sonnet-5-5"])

    assert read_transcript_at(path).subagent_models == {}
    assert read_transcript_at(path, with_subagents=True).subagent_models == {
        "toolu_a": "claude-sonnet-5-5"}


def test_the_session_reader_asks_for_the_subagent_models(tmp_path, monkeypatch):
    import claudio_maestro.history as history

    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a"}, ["claude-sonnet-5-5"])
    monkeypatch.setattr(history, "_session_file", lambda session_id, directory: path)

    assert REAL_SDK_READ_TRANSCRIPT("sess", "/x").subagent_models == {
        "toolu_a": "claude-sonnet-5-5"}


def subagents_dir(path: Path) -> Path:
    return path.parent / path.stem / "subagents"


def test_non_dict_lines_of_the_subagent_transcript_are_skipped(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a"}, ["claude-sonnet-5-5"])
    jsonl = subagents_dir(path) / "agent-x1.jsonl"
    jsonl.write_text('["assistant"]\n"assistant"\n42\n' + jsonl.read_text())

    assert read_subagent_models(path) == {"toolu_a": "claude-sonnet-5-5"}


def test_non_dict_message_of_the_subagent_transcript_is_skipped(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a", "model": "sonnet"}, [])
    jsonl = subagents_dir(path) / "agent-x1.jsonl"
    jsonl.write_text('{"type": "assistant", "message": ["assistant"]}\n')

    assert read_subagent_models(path) == {"toolu_a": "sonnet"}


def test_non_dict_meta_is_skipped(tmp_path):
    path = write_session(tmp_path)
    (subagents_dir(path)).mkdir(parents=True)
    (subagents_dir(path) / "agent-x1.meta.json").write_text('["toolUseId"]')

    assert read_subagent_models(path) == {}


def test_deeply_nested_json_does_not_break_the_reading(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a", "model": "sonnet"}, [])
    write_subagent(path, "x2", {"toolUseId": "toolu_b"}, [])
    deep = "[" * 200_000
    (subagents_dir(path) / "agent-x2.meta.json").write_text(deep)
    (subagents_dir(path) / "agent-x1.jsonl").write_text('{"type": "assistant", "message": ' + deep + "\n")

    assert read_transcript_file(path, with_subagents=True).subagent_models == {"toolu_a": "sonnet"}


def test_symlinked_meta_is_not_followed(tmp_path):
    path = write_session(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"toolUseId": "toolu_a", "model": "opus"}))
    subagents_dir(path).mkdir(parents=True)
    (subagents_dir(path) / "agent-x1.meta.json").symlink_to(outside)

    assert read_subagent_models(path) == {}


def test_symlinked_subagent_transcript_is_not_followed(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a", "model": "sonnet"}, [])
    outside = tmp_path / "outside.jsonl"
    outside.write_text(json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-4-7"}}) + "\n")
    (subagents_dir(path) / "agent-x1.jsonl").unlink()
    (subagents_dir(path) / "agent-x1.jsonl").symlink_to(outside)

    assert read_subagent_models(path) == {"toolu_a": "sonnet"}


def test_symlinked_subagents_folder_is_not_followed(tmp_path):
    path = write_session(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "agent-x1.meta.json").write_text(json.dumps({"toolUseId": "toolu_a", "model": "opus"}))
    (path.parent / path.stem).mkdir()
    (path.parent / path.stem / "subagents").symlink_to(elsewhere, target_is_directory=True)

    assert read_subagent_models(path) == {}


def test_symlinked_session_folder_is_not_followed(tmp_path):
    path = write_session(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "subagents"
    elsewhere.mkdir(parents=True)
    (elsewhere / "agent-x1.meta.json").write_text(json.dumps({"toolUseId": "toolu_a", "model": "opus"}))
    (path.parent / path.stem).symlink_to(elsewhere.parent, target_is_directory=True)

    assert read_subagent_models(path) == {}


def run_with_timeout(func, seconds: float = 5.0):
    box: list = []
    thread = threading.Thread(target=lambda: box.append(func()), daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), "the reading hung"
    return box[0]


def test_fifo_as_meta_does_not_hang(tmp_path):
    path = write_session(tmp_path)
    subagents_dir(path).mkdir(parents=True)
    os.mkfifo(subagents_dir(path) / "agent-x1.meta.json")

    assert run_with_timeout(lambda: read_subagent_models(path)) == {}


def test_fifo_as_subagent_transcript_does_not_hang(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a", "model": "sonnet"}, [])
    (subagents_dir(path) / "agent-x1.jsonl").unlink()
    os.mkfifo(subagents_dir(path) / "agent-x1.jsonl")

    assert run_with_timeout(lambda: read_subagent_models(path)) == {"toolu_a": "sonnet"}


def test_huge_meta_is_ignored(tmp_path):
    path = write_session(tmp_path)
    subagents_dir(path).mkdir(parents=True)
    padding = " " * (200 * 1024)
    (subagents_dir(path) / "agent-x1.meta.json").write_text(
        json.dumps({"toolUseId": "toolu_a", "model": "opus"}) + padding)

    assert read_subagent_models(path) == {}


def test_subagent_transcript_is_read_within_a_byte_budget(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a", "model": "sonnet"}, [])
    jsonl = subagents_dir(path) / "agent-x1.jsonl"
    filler = "x" * 1000 + "\n"
    real = json.dumps({"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-4-7"}})
    jsonl.write_text(filler * 100 + real + "\n")  # 100 KB of lines first, still within 200 lines
    assert read_subagent_models(path) == {"toolu_a": "claude-opus-4-7"}

    jsonl.write_text("y" * (3 * 1024 * 1024) + "\n" + real + "\n")  # one huge line, then the model
    assert read_subagent_models(path) == {"toolu_a": "sonnet"}


def test_a_line_longer_than_the_chunk_does_not_confuse_the_next_ones(tmp_path):
    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a"}, [])
    jsonl = subagents_dir(path) / "agent-x1.jsonl"
    real = json.dumps({"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-4-7"}})
    jsonl.write_text("z" * 150_000 + "\n" + real + "\n")

    assert read_subagent_models(path) == {"toolu_a": "claude-opus-4-7"}


def test_only_a_limited_number_of_subagent_files_is_read(tmp_path):
    import claudio_maestro.history as history

    path = write_session(tmp_path)
    subagents_dir(path).mkdir(parents=True)
    for i in range(history.SUBAGENT_FILES_MAX + 20):
        (subagents_dir(path) / f"agent-{i:05d}.meta.json").write_text(
            json.dumps({"toolUseId": f"toolu_{i}", "model": "sonnet"}))

    assert len(read_subagent_models(path)) == history.SUBAGENT_FILES_MAX


def test_one_broken_subagent_does_not_hide_the_others(tmp_path, monkeypatch):
    import claudio_maestro.history as history

    path = write_session(tmp_path)
    write_subagent(path, "x1", {"toolUseId": "toolu_a"}, ["claude-sonnet-5-5"])
    write_subagent(path, "x2", {"toolUseId": "toolu_b"}, ["claude-opus-4-7"])
    real = history._first_assistant_model

    def flaky(p, *args, **kwargs):
        if p.name == "agent-x1.jsonl":
            raise RuntimeError("boom")
        return real(p, *args, **kwargs)

    monkeypatch.setattr(history, "_first_assistant_model", flaky)

    assert read_subagent_models(path) == {"toolu_b": "claude-opus-4-7"}


def history_entries() -> list:
    return [
        user_entry("faça"),
        assistant_entry({"type": "tool_use", "id": "toolu_1", "name": "Agent",
                         "input": {"description": "x", "prompt": "y"}}, "m1"),
        user_entry([{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}], uuid="u2"),
    ]


def test_load_history_gives_the_cards_their_model():
    builder = ConversationBuilder()

    builder.load_history(history_entries(), subagent_models={"toolu_1": "claude-sonnet-5-5"})

    assert sub_of_call(builder, "toolu_1")["model"] == "claude-sonnet-5-5"


def test_load_history_without_a_model_keeps_the_input_fallback():
    builder = ConversationBuilder()
    entries = history_entries()
    entries[1].message["content"][0]["input"]["model"] = "opus"

    builder.load_history(entries)

    assert sub_of_call(builder, "toolu_1")["model"] == "opus"


def test_load_history_ignores_inherit_as_a_fallback():
    builder = ConversationBuilder()
    entries = history_entries()
    entries[1].message["content"][0]["input"]["model"] = "inherit"

    builder.load_history(entries)

    assert sub_of_call(builder, "toolu_1")["model"] is None


def sub_of_call(builder: ConversationBuilder, tool_use_id: str) -> dict:
    [item] = [i for i in builder.snapshot() if i["type"] == "tool" and i["tool_use_id"] == tool_use_id]
    return item["subagent"]
