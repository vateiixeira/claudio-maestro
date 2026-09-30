"""Teste manual do agente de resumos contra o SDK real. Consome a assinatura.

Segue o CLAUDE.md: modelo haiku, prompt mínimo, pasta temporária, setting_sources=[]
(o SdkDigestModel já usa), variáveis CLAUDE* removidas. Confere que a saída
estruturada volta com tools=[] e max_turns=3, que uma segunda leitura (incremental,
com o resumo anterior) funciona, que o agente não recebe ferramentas nem servidores MCP
(imprime o que a mensagem de init informa) e que a sessão do agente foi apagada.

Uso: uv run python scripts/digest_smoke.py
"""

import asyncio
import os
import tempfile
from pathlib import Path

for name in [n for n in os.environ if n.startswith("CLAUDE")]:
    del os.environ[name]

from vibing.config import claude_projects_dir  # noqa: E402
from vibing.digest.merge import merge_digest  # noqa: E402
from vibing.digest.model import DigestRequest, SdkDigestModel  # noqa: E402
from vibing.digest.prompt import build_prompt, system_prompt  # noqa: E402
from vibing.digest.store import Digest  # noqa: E402


def show_init(data: dict) -> None:
    print("  init: tools =", data.get("tools"), "| mcp_servers =", data.get("mcp_servers"))


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vibing-digest-smoke-") as folder:
        before = set(claude_projects_dir().rglob("*.jsonl"))
        model = SdkDigestModel(Path(folder), on_init=show_init)

        def request(digest: Digest | None, text: str, restarted: bool = False) -> DigestRequest:
            prompt = build_prompt(
                project="demo", title="Sessão de teste", digest=digest, plan=None, specs=[],
                text=text, restarted=restarted,
            )
            return DigestRequest(system_prompt(""), prompt, model="haiku", effort="low")

        print("leitura 1 (primeira):")
        first = await model.summarize(request(
            None,
            "[Você] Crie a rota de saúde\n[Claude] Criei GET /api/health.\n[Edit] app.py",
        ))
        print("  resultado:", first)
        digest = merge_digest(
            None, first, session_id="smoke", cursor="u1", read_at=0,
            plan_path=None, plan=None, roots=[],
        )

        print("leitura 2 (incremental, com o resumo anterior):")
        second = await model.summarize(request(
            digest,
            "[Você] Agora adicione um teste para a rota\n"
            "[Claude] Adicionei test_health em tests/test_health.py e ele passa.\n"
            "[Edit] tests/test_health.py",
        ))
        print("  resultado:", second)

        leaked = set(claude_projects_dir().rglob("*.jsonl")) - before
        print("sessões deixadas para trás:", [str(p) for p in leaked] or "nenhuma")


if __name__ == "__main__":
    asyncio.run(main())
