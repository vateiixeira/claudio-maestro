"""Entry point: `python -m claudio_maestro.agentd --data-dir D`."""

import argparse
import asyncio
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from claudio_maestro.agentd import LOG_NAME
from claudio_maestro.agentd.paths import private_dir
from claudio_maestro.agentd.server import Agentd, LockedError


async def _run(agentd: Agentd) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, agentd.request_stop)  # graceful: kills children, frees lock
    await agentd.serve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claudio_maestro.agentd")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--idle-exit", type=float, default=600)
    parser.add_argument("--orphan-timeout", type=float, default=1800)
    args = parser.parse_args(argv)
    os.umask(0o077)
    private_dir(args.data_dir)
    handler = RotatingFileHandler(args.data_dir / LOG_NAME, maxBytes=1024 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    agentd = Agentd(args.data_dir, idle_exit=args.idle_exit, orphan_timeout=args.orphan_timeout)
    try:
        asyncio.run(_run(agentd))
    except LockedError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
