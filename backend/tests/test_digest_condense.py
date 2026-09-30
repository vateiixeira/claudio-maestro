# backend/tests/test_digest_condense.py
"""Slice after the cursor and condensed text of a transcript."""

from types import SimpleNamespace

from vibing.conversation import COMPACT_SUMMARY_PREFIX
from vibing.digest.condense import (
    Condensed,
    condense,
    entries_after,
    tool_line,
)
from vibing.history import Transcript

CWD = "/home/vi/dev/app"


def user(uuid: str, content) -> SimpleNamespace:
    return SimpleNamespace(type="user", uuid=uuid, message={"role": "user", "content": content})


def claude(uuid: str, *blocks) -> SimpleNamespace:
    return SimpleNamespace(
        type="assistant", uuid=uuid, message={"role": "assistant", "content": list(blocks)}
    )


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def tool(tool_id: str, name: str, **inp) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": inp}


def transcript(*messages, compact=(), results=None) -> Transcript:
    return Transcript(messages=list(messages), tool_results=results or {},
                      compact_uuids=set(compact))


# entries_after ---------------------------------------------------------------

def test_first_reading_takes_everything() -> None:
    t = transcript(user("u1", "oi"), claude("a1", text("olá")))
    s = entries_after(t, None)
    assert [m.uuid for m in s.messages] == ["u1", "a1"]
    assert s.cursor == "a1" and s.cursor_found is True


def test_takes_only_what_follows_the_cursor() -> None:
    t = transcript(user("u1", "oi"), claude("a1", text("olá")), user("u2", "mais"))
    s = entries_after(t, "a1")
    assert [m.uuid for m in s.messages] == ["u2"] and s.cursor == "u2" and s.cursor_found


def test_nothing_new_keeps_the_cursor() -> None:
    t = transcript(user("u1", "oi"))
    s = entries_after(t, "u1")
    assert s.messages == [] and s.cursor == "u1" and s.cursor_found


def test_lost_cursor_restarts_at_the_last_compaction() -> None:
    t = transcript(user("c1", COMPACT_SUMMARY_PREFIX + " resumo"), user("u5", "segue"),
                   compact=["c1"])
    s = entries_after(t, "sumiu")
    assert [m.uuid for m in s.messages] == ["c1", "u5"] and s.cursor_found is False


def test_lost_cursor_without_compaction_restarts_at_the_beginning() -> None:
    t = transcript(user("u1", "oi"), user("u2", "mais"))
    s = entries_after(t, "sumiu")
    assert [m.uuid for m in s.messages] == ["u1", "u2"] and s.cursor_found is False


# tool_line -------------------------------------------------------------------

def test_tool_lines() -> None:
    assert tool_line("Edit", {"file_path": f"{CWD}/backend/x.py"}, CWD) == "[Edit] backend/x.py"
    assert tool_line("Read", {"file_path": "/etc/hosts"}, CWD) == "[Read] /etc/hosts"
    assert tool_line("Bash", {"command": "uv run   pytest\n -q"}, CWD) == "[Bash] uv run pytest -q"
    assert tool_line("Bash", {"command": "x" * 300}, CWD) == "[Bash] " + "x" * 200 + "…"
    assert tool_line("Task", {"subagent_type": "implementer", "description": "Tarefa 3"}, CWD) \
        == "[Task] implementer: Tarefa 3"
    assert tool_line("Agent", {"description": "Buscar"}, CWD) == "[Agent] agente: Buscar"
    assert tool_line("Skill", {"skill": "superpowers:brainstorming"}, CWD) \
        == "[Skill] superpowers:brainstorming"
    assert tool_line("Grep", {"pattern": "def x"}, CWD) == "[Grep] def x"
    assert tool_line("WebFetch", {"url": "https://x"}, CWD) == "[WebFetch]"
    assert tool_line("Edit", None, CWD) == "[Edit]"


# condense --------------------------------------------------------------------

def test_condense_formats_each_kind() -> None:
    messages = [
        user("u1", "Execute o plano X"),
        claude("a1", {"type": "thinking", "thinking": "hmm"}, text("Vou começar."),
               tool("t1", "Edit", file_path=f"{CWD}/a.py"), tool("t2", "Bash", command="pytest")),
        user("r1", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
        user("u2", "<command-name>/model</command-name>"),
        user("u3", [text("Agora ajuste o menu"), {"type": "image", "source": {}}]),
    ]
    out = condense(messages, {"t2": {"is_error": True}}, CWD)
    assert out.text.splitlines() == [
        "[Você] Execute o plano X",
        "[Claude] Vou começar.",
        "[Edit] a.py",
        "[Bash] pytest (falhou)",
        "[Você] Agora ajuste o menu",
    ]
    assert out.count == 5
    assert out.paths == [f"{CWD}/a.py"]


def test_condense_marks_compaction_and_cuts_long_texts() -> None:
    long = "y" * 5000
    out = condense([user("c1", COMPACT_SUMMARY_PREFIX + " " + long),
                    claude("a1", text("z" * 2000))], {}, CWD)
    lines = out.text.splitlines()
    assert lines[0].startswith("[Compactação] " + COMPACT_SUMMARY_PREFIX)
    assert len(lines[0]) == len("[Compactação] ") + 4000 + 1
    assert lines[1] == "[Claude] " + "z" * 1500 + "…"


def test_condense_paths_are_unique_and_ordered() -> None:
    out = condense([claude("a1", tool("t1", "Read", file_path="/p/b.md"),
                           tool("t2", "Edit", file_path="/p/a.md"),
                           tool("t3", "Read", file_path="/p/b.md"))], {}, None)
    assert out.paths == ["/p/b.md", "/p/a.md"]


def test_over_budget_keeps_every_prompt_and_both_ends() -> None:
    messages = [user("u0", "Pedido inicial")]
    messages += [claude(f"a{i}", text(f"resposta {i:03d} " + "x" * 80)) for i in range(100)]
    messages += [user("u9", "Pedido final")]
    out = condense(messages, {}, CWD, budget=2000)
    lines = out.text.splitlines()
    assert lines[0] == "[Você] Pedido inicial" and lines[-1] == "[Você] Pedido final"
    assert "resposta 000" in out.text and "resposta 099" in out.text
    assert any(line.startswith("[… ") and line.endswith(" entradas omitidas …]") for line in lines)
    assert len(out.text) <= 2000 + 200  # the marker lines are not counted
    assert out.count == 102


def test_empty_slice() -> None:
    assert condense([], {}, CWD) == Condensed(text="", count=0, paths=[])
