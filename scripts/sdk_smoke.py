"""Teste manual contra o SDK real. Consome a assinatura: rode só quando necessário.

Segue os cuidados do CLAUDE.md: modelo haiku, prompt mínimo, pasta temporária,
setting_sources=[], variáveis CLAUDE* removidas e sessão apagada ao final.

Uso: uv run python scripts/sdk_smoke.py
"""

import asyncio
import os
import tempfile

for name in [n for n in os.environ if n.startswith("CLAUDE")]:
    del os.environ[name]

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    delete_session,
)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vibing-smoke-") as folder:
        options = ClaudeAgentOptions(cwd=folder, model="haiku", setting_sources=[], max_turns=1)
        session_id = None
        async with ClaudeSDKClient(options=options) as client:
            await client.query("Responda só: ok")
            async for message in client.receive_response():
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    session_id = message.data.get("session_id")
                    print("init:", message.data.get("model"), "apiKeySource:", message.data.get("apiKeySource"))
                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print("resposta:", block.text)
                elif isinstance(message, ResultMessage):
                    print("resultado:", message.subtype, "erro:", message.is_error, "custo:", message.total_cost_usd)
        if session_id:
            delete_session(session_id, directory=folder)
            print("sessão apagada:", session_id)


if __name__ == "__main__":
    asyncio.run(main())
