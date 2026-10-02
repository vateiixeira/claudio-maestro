#!/usr/bin/env python3
"""Fake `claude` for tests: speaks the stream-json control protocol on stdin/stdout.

User message text drives it:
  "ask"        -> asks permission for Bash over a control_request, then answers
                  "permitido" or "negado" and ends the turn.
  "stream:N"   -> N text deltas (50 ms apart) of one message, then the full message.
  "exit:C"     -> writes "fake failure" to stderr and exits with code C.
  anything else -> "eco: <text>".
Every assistant/user/result line carries a fresh `uuid`.
"""

import json
import os
import sys
import threading
import time
import uuid

SESSION = "fake-session"
for i, arg in enumerate(sys.argv):
    if arg in ("--session-id", "--resume") and i + 1 < len(sys.argv):
        SESSION = sys.argv[i + 1]
    elif arg.startswith("--resume="):
        SESSION = arg.split("=", 1)[1]

_lock = threading.Lock()
_responses: dict[str, dict] = {}
_answered = threading.Condition(_lock)


def emit(obj: dict) -> None:
    with _lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def assistant(text: str, message_id: str | None = None) -> None:
    emit({
        "type": "assistant", "uuid": str(uuid.uuid4()), "session_id": SESSION,
        "parent_tool_use_id": None,
        "message": {"id": message_id or f"msg_{uuid.uuid4().hex[:12]}", "role": "assistant",
                    "model": "fake", "content": [{"type": "text", "text": text}]},
    })


def result() -> None:
    emit({"type": "result", "subtype": "success", "uuid": str(uuid.uuid4()),
          "session_id": SESSION, "duration_ms": 1, "duration_api_ms": 1,
          "is_error": False, "num_turns": 1})


def stream_event(event: dict) -> None:
    emit({"type": "stream_event", "uuid": str(uuid.uuid4()), "session_id": SESSION,
          "parent_tool_use_id": None, "event": event})


def turn(text: str) -> None:
    emit({"type": "system", "subtype": "init", "uuid": str(uuid.uuid4()),
          "session_id": SESSION, "model": "fake", "permissionMode": "default"})
    if text == "ask":
        request_id = f"perm-{uuid.uuid4().hex[:8]}"
        tool_use_id = f"toolu_{uuid.uuid4().hex[:8]}"
        emit({"type": "assistant", "uuid": str(uuid.uuid4()), "session_id": SESSION,
              "parent_tool_use_id": None,
              "message": {"id": f"msg_{uuid.uuid4().hex[:12]}", "role": "assistant",
                          "model": "fake", "content": [{"type": "tool_use", "id": tool_use_id,
                                                        "name": "Bash",
                                                        "input": {"command": "echo hi"}}]}})
        emit({"type": "control_request", "request_id": request_id,
              "request": {"subtype": "can_use_tool", "tool_name": "Bash",
                          "input": {"command": "echo hi"}, "tool_use_id": tool_use_id,
                          "permission_suggestions": []}})
        with _answered:
            while request_id not in _responses:
                _answered.wait()
            answer = _responses.pop(request_id)
        allowed = (answer.get("response") or {}).get("behavior") == "allow"
        assistant("permitido" if allowed else "negado")
    elif text.startswith("stream:"):
        count = int(text.split(":", 1)[1])
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        stream_event({"type": "message_start", "message": {"id": message_id}})
        stream_event({"type": "content_block_start", "index": 0,
                      "content_block": {"type": "text", "text": ""}})
        words = []
        for i in range(count):
            words.append(f"w{i}")
            stream_event({"type": "content_block_delta", "index": 0,
                          "delta": {"type": "text_delta", "text": f"w{i} "}})
            time.sleep(0.05)
        stream_event({"type": "content_block_stop", "index": 0})
        assistant(" ".join(words) + " ", message_id)
    elif text.startswith("exit:"):
        sys.stderr.write("fake failure\n")
        sys.stderr.flush()
        os._exit(int(text.split(":", 1)[1]))
    else:
        assistant(f"eco: {text}")
    result()


def main() -> None:
    for raw in sys.stdin:
        msg = json.loads(raw)
        kind = msg.get("type")
        if kind == "control_request":
            sub = msg["request"].get("subtype")
            payload = {"commands": [], "models": [{"value": "fake"}], "pid": os.getpid()} \
                if sub == "initialize" else {}
            emit({"type": "control_response",
                  "response": {"subtype": "success", "request_id": msg["request_id"],
                               "response": payload}})
        elif kind == "control_response":
            with _answered:
                _responses[msg["response"]["request_id"]] = msg["response"]
                _answered.notify_all()
        elif kind == "user":
            content = msg["message"]["content"]
            text = content if isinstance(content, str) else next(
                (b.get("text", "") for b in content if b.get("type") == "text"), "")
            threading.Thread(target=turn, args=(text,), daemon=True).start()


if __name__ == "__main__":
    main()
