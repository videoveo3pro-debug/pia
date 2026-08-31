from __future__ import annotations

import asyncio
import logging

from app.services.vpn_manager import VPNManager

logger = logging.getLogger(__name__)


async def run_health_monitor(manager: VPNManager, interval_seconds: int) -> None:
    while True:
        try:
            await asyncio.to_thread(manager.health_tick)
        except Exception as exc:  # keep monitor alive
            logger.warning("health monitor failed: %s", exc)
        await asyncio.sleep(interval_seconds)
