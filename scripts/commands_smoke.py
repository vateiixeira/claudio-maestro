"""Manual check of the command catalog against the real SDK (only connects: no prompt,
no model call, no session file). Run from the repository root:

    uv run python scripts/commands_smoke.py [folder]
"""

import asyncio
import sys
from pathlib import Path

from vibing.agent.sdk_client import clean_inherited_env
from vibing.commands import CommandCatalog
from vibing.sessions import default_agent_factory


async def main() -> None:
    clean_inherited_env()
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    commands = await CommandCatalog(default_agent_factory).list(folder)
    names = [c.name for c in commands]
    print(f"{len(names)} comandos em {folder}")
    for wanted in ("commit", "superpowers:brainstorming"):
        print(f"  {wanted}: {'ok' if wanted in names else 'FALTANDO'}")


asyncio.run(main())
