"""Teste manual do agente de resumos contra o SDK real. Consome a assinatura.

Segue o CLAUDE.md: modelo haiku, prompt mínimo, pasta temporária, setting_sources=[]
(o SdkDigestModel já usa), variáveis CLAUDE* removidas. Confere que a saída
estruturada volta com tools=[] e max_turns=3, e que a sessão do agente foi apagada.

Uso: uv run python scripts/digest_smoke.py
"""

import asyncio
import os
import tempfile
from pathlib import Path

for name in [n for n in os.environ if n.startswith("CLAUDE")]:
    del os.environ[name]

from vibing.config import claude_projects_dir  # noqa: E402
from vibing.digest.model import DigestRequest, SdkDigestModel  # noqa: E402
from vibing.digest.prompt import build_prompt, system_prompt  # noqa: E402


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vibing-digest-smoke-") as folder:
        before = set(claude_projects_dir().rglob("*.jsonl"))
        prompt = build_prompt(
            project="demo", title="Sessão de teste", digest=None, plan=None, specs=[],
            text="[Você] Crie a rota de saúde\n[Claude] Criei GET /api/health.\n[Edit] app.py",
            restarted=False,
        )
        model = SdkDigestModel(Path(folder))
        result = await model.summarize(
            DigestRequest(system_prompt(""), prompt, model="haiku", effort="low")
        )
        print("resultado:", result)
        leaked = set(claude_projects_dir().rglob("*.jsonl")) - before
        print("sessões deixadas para trás:", [str(p) for p in leaked] or "nenhuma")


if __name__ == "__main__":
    asyncio.run(main())
