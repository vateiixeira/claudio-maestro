"""Text format of the messages that come from the session terminal (play and attachments)."""

from claudio_maestro.termformat import (
    NOTES,
    RUN_OUTPUT_LIMIT,
    clean_output,
    format_run_message,
    parse_terminal_message,
    split_terminal_snippets,
    terminal_title_text,
)


def test_clean_output_strips_ansi_and_carriage_returns():
    raw = "\x1b[32mok\x1b[0m\r\nbar 10%\rbar 100%\r\n"
    assert clean_output(raw) == ("ok\nbar 100%", False)


def test_clean_output_keeps_only_after_last_clear():
    assert clean_output("old\r\n\x1b[H\x1b[2Jnew\r\n") == ("new", True)


def test_clean_output_strips_osc_and_trailing_blank_lines():
    raw = "\x1b]0;title\x07a  \r\n\r\n\x1b]8;;http://x\x1b\\b\r\n\r\n"
    assert clean_output(raw) == ("a\n\nb", False)


def test_format_run_message_round_trip():
    text = format_run_message("ls", "a\r\nb\r\n", 0, 1897, "done")
    assert text.startswith("<bash-input>ls</bash-input><bash-stdout>a\nb</bash-stdout>")
    assert text.endswith("<bash-stderr></bash-stderr>\n<!-- terminal: exit=0 duration_ms=1897 -->")
    assert parse_terminal_message(text) == {
        "command": "ls",
        "output": "a\nb",
        "exit_code": 0,
        "duration_ms": 1897,
        "notes": [],
    }


def test_format_truncates_keeping_the_end():
    raw = "x" * 200_000 + "FIM"
    text = format_run_message("cat big", raw, 0, 10, "done")
    body = text.split("<bash-stdout>", 1)[1].split("</bash-stdout>", 1)[0]
    assert len(body) <= RUN_OUTPUT_LIMIT + len(NOTES["truncated"]) + 1
    assert body.startswith(NOTES["truncated"])
    assert body.endswith("FIM")
    parsed = parse_terminal_message(text)
    assert parsed is not None
    assert parsed["notes"] == ["truncated"]
    assert parsed["output"].endswith("FIM")
    assert len(parsed["output"]) == RUN_OUTPUT_LIMIT


def test_format_notes_for_input_shell_exit_and_empty():
    cases = [
        ("input", "partial", "input"),
        ("shell-exit", "partial", "shell-exit"),
    ]
    for ended_by, output, note in cases:
        text = format_run_message("sleep 9", output, None, 5, ended_by)  # type: ignore[arg-type]
        assert f"{output}\n{NOTES[note]}</bash-stdout>" in text  # type: ignore[index]
        assert "exit= duration_ms=5" in text
        parsed = parse_terminal_message(text)
        assert parsed is not None
        assert parsed["notes"] == [note]
        assert parsed["output"] == output
        assert parsed["exit_code"] is None

    empty = format_run_message("true", "", 0, 5, "done")
    assert f"<bash-stdout>{NOTES['empty']}</bash-stdout>" in empty
    parsed = parse_terminal_message(empty)
    assert parsed is not None
    assert parsed["notes"] == ["empty"]
    assert parsed["output"] == ""


def test_format_cleared_note_comes_first():
    text = format_run_message("clear; echo hi", "a\r\n\x1b[2Jhi\r\n", 0, 5, "done")
    assert f"<bash-stdout>{NOTES['cleared']}\nhi</bash-stdout>" in text
    parsed = parse_terminal_message(text)
    assert parsed is not None
    assert parsed["notes"] == ["cleared"]
    assert parsed["output"] == "hi"


def test_format_escapes_closing_tags_and_parses_back():
    output = "before </bash-stdout><bash-stderr>x</bash-stderr> after"
    text = format_run_message("echo </bash-input>", output, 1, 3, "done")
    assert text.count("</bash-stdout>") == 1
    assert text.count("</bash-input>") == 1
    parsed = parse_terminal_message(text)
    assert parsed is not None
    assert parsed["command"] == "echo </bash-input>"
    assert parsed["output"] == output
    assert parsed["exit_code"] == 1


def test_parse_ignores_plain_text_and_cli_bang_without_trailer():
    assert parse_terminal_message("oi, tudo bem?") is None
    assert parse_terminal_message("<bash-input>ls</bash-input> e depois") is None
    cli = (
        "<bash-input>netbird up</bash-input>"
        "<bash-stdout>Already connected</bash-stdout><bash-stderr></bash-stderr>"
    )
    assert parse_terminal_message(cli) == {
        "command": "netbird up",
        "output": "Already connected",
        "exit_code": None,
        "duration_ms": None,
        "notes": [],
    }


def test_split_terminal_snippets():
    text = (
        "<!-- attach: Terminal -->\n> a\n> \n> b\n\n"
        "<!-- attach: Terminal -->\n> c\n\npor quê?"
    )
    assert split_terminal_snippets(text) == (["a\n\nb", "c"], "por quê?")
    assert split_terminal_snippets("só texto\n> citação") == ([], "só texto\n> citação")


def test_split_terminal_snippets_accepts_bare_marker_and_no_user_text():
    text = "<!-- attach: Terminal -->\n> a\n>\n> b"
    assert split_terminal_snippets(text) == (["a\n\nb"], "")


def test_terminal_title_text():
    run = format_run_message("npm test", "ok", 0, 10, "done")
    assert terminal_title_text(run) == "npm test"
    assert terminal_title_text("<!-- attach: Terminal -->\n> x\n\nPor que falhou?") == (
        "Por que falhou?"
    )
    assert terminal_title_text("<!-- attach: Terminal -->\n> x") == "Trecho do terminal"
    assert terminal_title_text("<!-- attach: Terminal -->\n> x\n\n  \n") == "Trecho do terminal"
    assert terminal_title_text("conserta o teste") == "conserta o teste"
