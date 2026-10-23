"""Teste manual contra o SDK real para os agentes. Consome a assinatura: rode só quando necessário.

Confirma, direto e pelo agentd, as suposições do desenho dos agentes:
  1. uma ferramenta MCP do SDK (`eco`) recebe o que o modelo manda;
  2. `system_prompt` com `append`, `add_dirs` e `env` chegam ao processo `claude`;
  3. com `allow` e `ask` na mesma regra, o `can_use_tool` é chamado para o `git push`;
  4. pelo agentd, a ferramenta MCP continua funcionando depois de desligar o cliente
     (`detach`) e religar com `attach`.

Segue os cuidados do CLAUDE.md: modelo haiku, pastas temporárias, setting_sources=[], variáveis
CLAUDE* removidas e sessões apagadas ao final. O agentd é um só para este teste, numa pasta de
dados temporária: o agentd real, o socket e o lock dele não são tocados.

Imprime uma linha por verificação (`PASS ...` ou `FAIL ...: detalhe`) e termina com
`RESULT: PASS` ou `RESULT: FAIL` (código de saída 0 ou 1).

Uso: uv run python scripts/specialists_smoke.py
"""

import asyncio
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

for name in [n for n in os.environ if n.startswith("CLAUDE")]:
    del os.environ[name]

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    delete_session,
    tool,
)

from claudio_maestro.agent.agentd_client import AgentdClient  # noqa: E402
from claudio_maestro.agent.base import AgentOptions, AttachInfo  # noqa: E402
from claudio_maestro.agent.sdk_client import SdkAgentClient  # noqa: E402

PROMPT = (
    "Chame a ferramenta eco com a palavra secreta, rode `echo $MAESTRO_SMOKE`, "
    "liste a outra pasta ({extra}) e rode `git push origin main`."
)
SECOND_PROMPT = "Chame eco de novo com OK"
SETTINGS = '{"permissions": {"allow": ["Bash(git push:*)"], "ask": ["Bash(git push:*)"]}}'
EXTRA_FILE = "marcador-pasta-extra.txt"
TURN_TIMEOUT = 240  # seconds

failures: list[str] = []
session_dirs: dict[str, Path] = {}  # session id -> the folder it ran in, for delete_session


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        failures.append(name)
    print(f"PASS {name}" if ok else f"FAIL {name}: {detail}", flush=True)


@dataclass
class Observed:
    """What happened in one route, filled in by the eco tool, can_use_tool and the stream."""

    eco_calls: list[str] = field(default_factory=list)
    permission_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    bash_commands: dict[str, str] = field(default_factory=dict)  # tool_use_id -> command
    results: dict[str, str] = field(default_factory=dict)  # tool_use_id -> text

    def record(self, message: Any) -> None:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock) and block.name == "Bash":
                    self.bash_commands[block.id] = str(block.input.get("command", ""))
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    self.results[block.tool_use_id] = result_text(block)

    def bash_result(self, needle: str) -> str | None:
        for tool_use_id, command in self.bash_commands.items():
            if needle in command and tool_use_id in self.results:
                return self.results[tool_use_id]
        return None


def result_text(block: ToolResultBlock) -> str:
    if isinstance(block.content, str):
        return block.content
    return "".join(str(part.get("text", "")) for part in block.content or [])


def make_extras(observed: Observed, extra: Path):
    """The can_use_tool callback and the AgentOptions fields of an agent session."""

    @tool("eco", "Devolve o texto recebido", {"texto": str})
    async def eco(args: dict[str, Any]) -> dict[str, Any]:
        observed.eco_calls.append(str(args.get("texto", "")))
        return {"content": [{"type": "text", "text": str(args.get("texto", ""))}]}

    async def can_use_tool(tool_name: str, tool_input: dict[str, Any], _context: Any):
        observed.permission_calls.append((tool_name, tool_input))
        if tool_name == "Bash" and "git push" in str(tool_input.get("command", "")):
            return PermissionResultDeny(message="git push não é permitido neste teste")
        return PermissionResultAllow()

    fields: dict[str, Any] = {
        "system_prompt_append": "Palavra secreta: ABACAXI.",
        "mcp_servers": {"maestro": create_sdk_mcp_server("maestro", tools=[eco])},
        "add_dirs": [extra],
        "env": {"MAESTRO_SMOKE": "1"},
    }
    return can_use_tool, fields


def make_client(
    folder: Path, session_id: str, observed: Observed, extra: Path,
    agentd: AgentdClient | None = None, attach: AttachInfo | None = None,
) -> SdkAgentClient:
    can_use_tool, fields = make_extras(observed, extra)
    client = SdkAgentClient(AgentOptions(
        cwd=folder, session_id=session_id, resume=False, can_use_tool=can_use_tool,
        model="haiku", permission_mode="default", setting_sources=[], settings=SETTINGS,
        agentd=agentd, attach=attach, **fields,
    ))
    # No AgentOptions field for this one: it only bounds the cost of the test. The SDK client
    # and the agentd spawn both read this options object at connect.
    client.sdk_options.max_turns = 12
    return client


async def run_turn(client: SdkAgentClient, observed: Observed, prompt: str, *, expect_eco: str | None = None) -> None:
    """Send a prompt and read until a result. With `expect_eco`, keep reading past a replayed
    result of the previous turn (after `attach`) until eco received that text."""
    await client.send(prompt)
    async with asyncio.timeout(TURN_TIMEOUT):
        async for message in client.messages():
            observed.record(message)
            if isinstance(message, ResultMessage):
                if expect_eco is None or expect_eco in (c.strip().upper() for c in observed.eco_calls):
                    return


def check_first_turn(route: str, observed: Observed) -> None:
    check(f"{route}: eco recebeu ABACAXI", any("ABACAXI" in c.upper() for c in observed.eco_calls),
          f"chamadas do eco: {observed.eco_calls}")
    echoed = observed.bash_result("MAESTRO_SMOKE")
    check(f"{route}: echo imprimiu 1", echoed is not None and echoed.strip() == "1",
          f"saída do echo: {echoed!r}; comandos: {list(observed.bash_commands.values())}")
    listed = any(EXTRA_FILE in text for text in observed.results.values())
    check(f"{route}: pasta extra listada", listed,
          f"nenhuma saída de ferramenta citou {EXTRA_FILE}; comandos: {list(observed.bash_commands.values())}")
    pushed = [i for name, i in observed.permission_calls
              if name == "Bash" and "git push" in str(i.get("command", ""))]
    check(f"{route}: can_use_tool chamado para git push apesar do allow", bool(pushed),
          f"chamadas do can_use_tool: {[(n, i.get('command', i)) for n, i in observed.permission_calls]}")


def new_folder(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir()
    return folder


def init_repo(folder: Path) -> None:
    git = ["git", "-c", "user.name=smoke", "-c", "user.email=smoke@example.com"]
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "inicio"], ["branch", "-M", "main"]):
        subprocess.run([*git, *args], cwd=folder, check=True, capture_output=True)


async def direct_route(root: Path, session_ids: list[str]) -> None:
    folder, extra = new_folder(root, "direct"), new_folder(root, "direct-extra")
    init_repo(folder)
    (extra / EXTRA_FILE).write_text("x\n")
    observed, session_id = Observed(), str(uuid.uuid4())
    session_ids.append(session_id)
    session_dirs[session_id] = folder
    client = make_client(folder, session_id, observed, extra)
    try:
        await client.connect()
        await run_turn(client, observed, PROMPT.format(extra=extra))
    finally:
        await client.close()
    check_first_turn("direta", observed)


async def agentd_route(root: Path, session_ids: list[str]) -> None:
    folder, extra = new_folder(root, "agentd"), new_folder(root, "agentd-extra")
    init_repo(folder)
    (extra / EXTRA_FILE).write_text("x\n")
    observed, session_id = Observed(), str(uuid.uuid4())
    session_ids.append(session_id)
    session_dirs[session_id] = folder
    agentd = AgentdClient(root / "agentd-data", idle_exit=120, orphan_timeout=120)
    live: SdkAgentClient | None = None
    try:
        await agentd.ensure_running()
        live = first = make_client(folder, session_id, observed, extra, agentd=agentd)
        await first.connect()
        await run_turn(first, observed, PROMPT.format(extra=extra))
        check_first_turn("agentd", observed)

        check("agentd: detach manteve o processo", await first.detach(), "detach() devolveu False")
        live = None
        children = await agentd.list()
        child = children[0] if children else None
        check("agentd: processo vivo depois do detach", child is not None and child.exit_code is None,
              f"filhos do agentd: {children}")
        if child is None:
            return
        live = second = make_client(
            folder, session_id, observed, extra, agentd=agentd,
            attach=AttachInfo(agentd_id=child.id, from_pos=child.ack, init_response=child.init),
        )
        await second.connect()
        await run_turn(second, observed, SECOND_PROMPT, expect_eco="OK")
        check("agentd: eco recebeu OK depois da religação",
              any(c.strip().upper() == "OK" for c in observed.eco_calls),
              f"chamadas do eco: {observed.eco_calls}")
    finally:
        try:
            if live is not None:
                await live.close()
            for child in await agentd.list():
                await agentd.kill(child.id)
            await agentd.shutdown_server()
        except Exception as error:  # cleanup must not hide the checks
            print(f"aviso: limpeza do agentd falhou: {error!r}", file=sys.stderr)
        await agentd.aclose()


async def main() -> int:
    session_ids: list[str] = []
    with tempfile.TemporaryDirectory(prefix="maestro-spec-smoke-") as tmp:
        root = Path(tmp)
        try:
            for name, route in (("direta", direct_route), ("agentd", agentd_route)):
                print(f"== rota {name} ==", flush=True)
                try:
                    await route(root, session_ids)
                except Exception as error:
                    check(f"{name}: rota sem erro", False, repr(error))
        finally:
            for session_id in session_ids:
                try:
                    delete_session(session_id, directory=str(session_dirs.get(session_id, root)))
                    print("sessão apagada:", session_id)
                except Exception as error:
                    print(f"aviso: não apaguei a sessão {session_id}: {error!r}", file=sys.stderr)
    print("RESULT: FAIL" if failures else "RESULT: PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
