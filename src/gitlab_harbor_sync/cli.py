"""Command-line entry point."""

from __future__ import annotations

import asyncio
import logging
import os

from .controller import SyncController


async def async_main() -> None:
    controller = SyncController()
    try:
        await controller.run()
    finally:
        await controller.close()


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        logging.getLogger("gitlab-harbor-sync").exception("Reconciliation failed")
        return 1
    return 0
