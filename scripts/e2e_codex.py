"""Deterministic Codex executable for the disposable browser test server."""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

MODEL = "codex-e2e"


def reply(**message):
    print(json.dumps(message), flush=True)


def serve(home: Path) -> None:
    def thread_file(thread_id: str) -> Path:
        return home / f"{thread_id}.json"

    thread = {}
    turns = []
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        params = request.get("params", {})
        if "id" not in request:
            continue
        request_id = request["id"]
        match method:
            case "initialize":
                result = {"userAgent": "codex-e2e"}
            case "account/read":
                result = {"account": {"type": "chatgpt", "planType": "plus"}, "requiresOpenaiAuth": True}
            case "account/rateLimits/read":
                result = {"rateLimits": {"primary": {"usedPercent": 31, "windowDurationMins": 300}}}
            case "model/list":
                result = {"data": [{"model": MODEL, "displayName": "Codex de teste", "isDefault": True,
                                    "defaultReasoningEffort": "medium",
                                    "supportedReasoningEfforts": [{"reasoningEffort": "medium"}]}]}
            case "config/read":
                result = {"config": {"model": MODEL, "model_reasoning_effort": "medium"}}
            case "thread/start":
                thread = {"id": str(uuid4()), "cwd": os.getcwd(), "historyMode": "paginated"}
                thread_file(thread["id"]).write_text(json.dumps({"thread": thread, "turns": []}))
                result = {"thread": thread, "model": MODEL, "reasoningEffort": "medium"}
            case "thread/read" | "thread/resume":
                saved = json.loads(thread_file(params["threadId"]).read_text())
                thread, turns = saved["thread"], saved["turns"]
                result = {"thread": {**thread, "turns": turns if params.get("includeTurns") else []},
                          "model": MODEL, "reasoningEffort": "medium"}
            case "thread/turns/list":
                result = {"data": turns, "nextCursor": None}
            case "turn/start":
                turn = {"id": str(uuid4()), "items": [], "status": "inProgress"}
                reply(id=request_id, result={"turn": turn})
                event_params = {"threadId": thread["id"], "turnId": turn["id"]}
                reply(method="turn/started", params={**event_params, "turn": turn})
                prompt = params["input"][0]["text"]
                item = {"id": str(uuid4()), "type": "agentMessage", "text": f"Resposta do Codex de teste: {prompt}"}
                reply(method="item/agentMessage/delta", params={**event_params, "itemId": item["id"],
                                                               "delta": item["text"]})
                reply(method="item/completed", params={**event_params, "item": item})
                reply(method="thread/tokenUsage/updated", params={**event_params, "tokenUsage": {
                    "last": {"inputTokens": 115, "cachedInputTokens": 20, "outputTokens": 10,
                             "reasoningOutputTokens": 2, "totalTokens": 125},
                    "modelContextWindow": 1000,
                }})
                turn = {**turn, "status": "completed", "items": [
                    {"id": str(uuid4()), "type": "userMessage", "content": params["input"],
                     "clientId": params.get("clientUserMessageId")}, item,
                ]}
                turns.append(turn)
                thread_file(thread["id"]).write_text(json.dumps({"thread": thread, "turns": turns}))
                reply(method="turn/completed", params={**event_params, "turn": turn})
                continue
            case _:
                reply(id=request_id, error={"code": -32601, "message": "Method not found"})
                continue
        reply(id=request_id, result=result)


if __name__ == "__main__":
    home = Path(os.environ["CODEX_HOME"])
    home.mkdir(exist_ok=True)
    version = home / "version"
    match sys.argv[1:]:
        case ["--version"]:
            print(f"codex-cli {version.read_text() if version.exists() else '0.172.0'}")
        case ["update"]:
            version.write_text("0.173.0")
        case ["app-server", *_]:
            serve(home)
        case _:
            sys.exit(2)
