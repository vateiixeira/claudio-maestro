"""Teste manual do agentd contra o SDK real. Consome a assinatura: rode só quando necessário.

Confere que uma sessão com um pedido de permissão pendente sobrevive à perda do cliente
(o que acontece quando o backend reinicia): o processo do agente continua no agentd, o
segundo cliente se religa a ele, o pedido chega de novo e o comando termina.

Segue os cuidados do CLAUDE.md: modelo haiku, prompt mínimo, pasta temporária,
setting_sources=[], variáveis CLAUDE* removidas, sessão apagada e processos encerrados
ao final. Imprime OK ou o motivo da falha.

Uso: uv run python scripts/agentd_smoke.py
"""

import asyncio
import contextlib
import os
import shutil
import signal
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

for name in [n for n in os.environ if n.startswith("CLAUDE")]:
    del os.environ[name]

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    PermissionResultAllow,
    ResultMessage,
    TextBlock,
    delete_session,
)

from claudio_maestro.agent.agentd_client import AgentdClient  # noqa: E402
from claudio_maestro.agent.base import AgentOptions, AttachInfo  # noqa: E402
from claudio_maestro.agent.sdk_client import SdkAgentClient  # noqa: E402

PROMPT = (
    "Use a ferramenta Bash para rodar exatamente este comando: "
    "mkdir spike-dir && touch spike-dir/x && echo smoke-ok. "
    "Depois responda só o que o comando imprimiu."
)
PERMISSION_TIMEOUT = 90
RESULT_TIMEOUT = 120
WAIT_BEFORE_ATTACH = 10


class SmokeFailure(Exception):
    pass


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def run(folder: Path, session_id: str, agentd: AgentdClient) -> None:
    permission_seen = asyncio.Event()
    never = asyncio.Event()  # never set: the first client's permission request hangs
    first_tool: dict[str, Any] = {}

    async def hang(tool_name: str, tool_input: dict[str, Any], _context: Any) -> Any:
        first_tool.update(name=tool_name, input=tool_input)
        permission_seen.set()
        await never.wait()
        raise SmokeFailure("o pedido do primeiro cliente não deveria ser respondido")

    allowed: list[str] = []

    async def allow(tool_name: str, _input: dict[str, Any], _context: Any) -> PermissionResultAllow:
        allowed.append(tool_name)
        return PermissionResultAllow()

    # 1. New session through the agentd; the Bash permission request is left hanging.
    first = SdkAgentClient(AgentOptions(
        cwd=folder, session_id=session_id, resume=False, can_use_tool=hang,
        model="haiku", setting_sources=[], agentd=agentd,
    ))
    await first.connect()
    reader = asyncio.create_task(drain(first))
    await first.send(PROMPT)
    try:
        await asyncio.wait_for(permission_seen.wait(), PERMISSION_TIMEOUT)
    except TimeoutError as error:
        raise SmokeFailure("o Claude não pediu permissão para o Bash a tempo") from error
    print("pedido de permissão:", first_tool.get("name"), first_tool.get("input"))

    # 2. The client goes away (as when the backend restarts); the process must stay.
    if not await first.detach():
        raise SmokeFailure("detach() devolveu False: o cliente não passou pelo agentd")
    await asyncio.gather(reader, return_exceptions=True)
    print(f"cliente solto; esperando {WAIT_BEFORE_ATTACH} s")
    await asyncio.sleep(WAIT_BEFORE_ATTACH)

    # 3. The agentd still has the process.
    children = [child for child in await agentd.list() if child.session_id == session_id]
    if len(children) != 1:
        raise SmokeFailure(f"o agentd deveria guardar 1 processo da sessão, guarda {len(children)}")
    child = children[0]
    if child.exit_code is not None or not process_alive(child.pid):
        raise SmokeFailure(f"o processo do agente morreu (código {child.exit_code})")
    if child.init is None:
        raise SmokeFailure("o agentd não guardou a resposta de inicialização")
    print("processo vivo no agentd, pid", child.pid)

    # 4. A second client attaches; the pending request comes again and is allowed.
    second = SdkAgentClient(AgentOptions(
        cwd=folder, session_id=session_id, resume=True, can_use_tool=allow,
        model="haiku", setting_sources=[], agentd=agentd,
        attach=AttachInfo(child.id, child.ack, child.init),
    ))
    await second.connect()
    answer: list[str] = []
    result: ResultMessage | None = None
    try:
        async with asyncio.timeout(RESULT_TIMEOUT):
            async for message in second.messages():
                if isinstance(message, AssistantMessage):
                    answer += [b.text for b in message.content if isinstance(b, TextBlock)]
                elif isinstance(message, ResultMessage):
                    result = message
                    break
    except TimeoutError as error:
        raise SmokeFailure("o resultado não chegou a tempo depois de religar") from error
    finally:
        with contextlib.suppress(Exception):
            await second.close()

    # 5. Checks.
    if "Bash" not in allowed:
        raise SmokeFailure("o pedido de permissão pendente não chegou de novo ao segundo cliente")
    if result is None or result.is_error:
        raise SmokeFailure(f"o turno terminou com erro: {result}")
    if not (folder / "spike-dir" / "x").exists():
        raise SmokeFailure("o comando não criou spike-dir/x")
    if "smoke-ok" not in "\n".join(answer):
        raise SmokeFailure(f"a resposta não traz smoke-ok: {answer!r}")


async def drain(client: SdkAgentClient) -> None:
    async for _message in client.messages():
        pass


async def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="maestro-agentd-smoke-")).resolve()
    data_dir = Path(tempfile.mkdtemp(prefix="maestro-agentd-data-")).resolve()
    session_id = str(uuid.uuid4())
    agentd = AgentdClient(data_dir, idle_exit=120, orphan_timeout=300)
    failure: str | None = None
    try:
        await run(folder, session_id, agentd)
    except SmokeFailure as error:
        failure = str(error)
    except Exception as error:  # noqa: BLE001 - report anything unexpected as a failure
        failure = f"{type(error).__name__}: {error}"
    finally:
        await cleanup(agentd, folder, data_dir, session_id)
    if failure is not None:
        print("FALHOU:", failure)
        return 1
    print("OK")
    return 0


async def cleanup(agentd: AgentdClient, folder: Path, data_dir: Path, session_id: str) -> None:
    """Kill the agent process and the agentd, delete the test session and the temp folders."""
    with contextlib.suppress(Exception):
        # Only if still connected: do not start an agentd just to clean up.
        for child in (await agentd.list()) if agentd.connected else []:
            if child.session_id == session_id:
                await agentd.kill(child.id)
    server_pid = agentd.server_pid
    with contextlib.suppress(Exception):
        await agentd.aclose()
    if server_pid is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(server_pid, signal.SIGTERM)
        for _ in range(50):  # up to 5 s for it to exit
            if not process_alive(server_pid):
                break
            await asyncio.sleep(0.1)
        else:
            with contextlib.suppress(ProcessLookupError):
                os.kill(server_pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        delete_session(session_id, directory=str(folder))
        print("sessão apagada:", session_id)
    shutil.rmtree(folder, ignore_errors=True)
    shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
