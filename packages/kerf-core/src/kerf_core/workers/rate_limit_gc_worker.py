"""kerf_core.workers.rate_limit_gc_worker — GC for rate_limit_buckets.

Deletes rows older than 24 hours from rate_limit_buckets every 15 minutes.
The table is a sliding-window counter and accumulates rows continuously;
without GC it would grow unbounded.

Registration: added to _build_workers() in kerf_workers.runner alongside
CompactionWorker and PricingRefreshWorker.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RateLimitGCWorker:
    """Deletes rate_limit_buckets rows older than 24 hours.

    Runs every ``interval_seconds`` (default 15 min). Cloud-tier only but
    the guard is the caller's responsibility — the worker itself always
    runs if instantiated.
    """

    name = "rate_limit_gc"
    interval_seconds: int = 15 * 60  # 15 minutes

    def __init__(self, pool: Any, interval_seconds: int = 15 * 60) -> None:
        self.pool = pool
        self.interval_seconds = interval_seconds
        self._shutdown = False

    # ------------------------------------------------------------------ lifecycle

    def stop(self) -> None:
        self._shutdown = True

    async def run(self, ctx: asyncio.TaskGroup) -> None:
        task = ctx.create_task(self._loop())
        try:
            await task
        except asyncio.CancelledError:
            self._shutdown = True
            logger.info("rate_limit_gc: worker shutdown")

    # ------------------------------------------------------------------ loop

    async def _loop(self) -> None:
        while not self._shutdown:
            try:
                await self.run_once(self.pool)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("rate_limit_gc: run_once error")
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

    # ------------------------------------------------------------------ core

    async def run_once(self, pool: Any) -> int:
        """Delete rate_limit_buckets rows older than 24 hours.

        Returns the number of rows deleted.
        """
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM rate_limit_buckets "
                "WHERE window_start < now() - interval '24 hours'"
            )
        # asyncpg returns a command tag like "DELETE N"
        try:
            deleted = int(str(result).split()[-1])
        except (ValueError, IndexError):
            deleted = 0
        logger.info("RateLimitGCWorker: cleaned %d rows", deleted)
        return deleted
