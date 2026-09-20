"""Outbox worker entrypoint.

Skeleton for now — the outbox model, enqueue, and reconciler land with the
write path in step 1.5. This just proves the process starts and stays up
as part of the compose stack (step 1.1's Goal).
"""

from __future__ import annotations

import asyncio
import logging
import os

from tti.logging import configure_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    logger.info("worker started")
    while True:
        logger.debug("worker heartbeat")
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
