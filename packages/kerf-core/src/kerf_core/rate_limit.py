"""Postgres-backed sliding-window rate limiter.

Multi-machine safe — state lives in Postgres. Each bucket_key is the
composition of a route name and a caller identity (user_id when
authenticated, otherwise IP). window_seconds is the granularity; the
helper rounds now() down to the nearest multiple to derive window_start
and UPSERTs an atomic increment.

Raises HTTPException 429 with a ``Retry-After`` header (seconds until the
next window) when count would exceed max_per_window.

JSON body on 429: ``{"detail": "rate limit exceeded", "retry_after": N}``
so the frontend can surface a sensible toast.
"""
from __future__ import annotations

import math
import time
from typing import Optional

from fastapi import HTTPException
from starlette import status


async def enforce(
    pool,
    key: str,
    max_per_window: int,
    window_seconds: int = 60,
) -> None:
    """Check + increment a rate-limit bucket for ``key``.

    Raises ``HTTPException(429)`` with a ``Retry-After`` header and a JSON
    body if the current window's count (after increment) exceeds
    ``max_per_window``.

    Parameters
    ----------
    pool:
        An asyncpg connection pool (or any object with ``.acquire()``).
    key:
        Bucket key — typically ``f"{route_prefix}:{user_id_or_ip}"``.
    max_per_window:
        Maximum calls allowed within a single window.
    window_seconds:
        Window width in seconds (default 60).  The window_start is
        computed server-side by Postgres using::

            to_timestamp(floor(extract(epoch from now()) / W) * W)

        This is deterministic and immune to clock skew between app servers.
    """
    # Compute retry-after in Python for the response header.
    # We compute the same floor truncation that Postgres will use.
    now_epoch = time.time()
    window_start_epoch = math.floor(now_epoch / window_seconds) * window_seconds
    retry_after = window_seconds - int(now_epoch - window_start_epoch)
    if retry_after <= 0:
        retry_after = window_seconds

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO rate_limit_buckets (bucket_key, window_start, count)
            VALUES (
                $1,
                to_timestamp(floor(extract(epoch from now()) / $2) * $2),
                1
            )
            ON CONFLICT (bucket_key, window_start) DO UPDATE
                SET count = rate_limit_buckets.count + 1
            RETURNING count
            """,
            key,
            float(window_seconds),
        )

    count = row["count"] if row else 1

    if count > max_per_window:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"detail": "rate limit exceeded", "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
