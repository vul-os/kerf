"""Database pool management.

kerf runs on one of two backends, selected purely by the ``DATABASE_URL``
scheme:

* ``postgres://…`` / ``postgresql://…`` — the scale backend, an asyncpg pool.
  Exactly the historical behaviour; teams / always-on nodes opt in with this one
  config line.
* ``sqlite://…`` — the embedded, zero-dependency default for a local install
  (see :func:`kerf_core.db.config.get_database_settings`).  Backed by
  :class:`kerf_core.db.sqlite_backend.SqlitePool`, which mirrors the asyncpg
  pool/connection surface, so every downstream query module is backend-agnostic.

The rest of the codebase only ever touches :func:`acquire_connection`,
:func:`transaction`, and the pool's ``fetch``/``execute``/… methods — all of
which are identical across the two backends.
"""

from typing import Any, Optional
from contextlib import asynccontextmanager

import asyncpg

from .config import get_database_settings, DatabaseSettings
from .dialect import is_sqlite_url


_pool: Optional[Any] = None


async def create_pool(settings: Optional[DatabaseSettings] = None) -> Any:
    global _pool
    if settings is None:
        settings = get_database_settings()

    dsn = settings.database_url

    if is_sqlite_url(dsn):
        from .sqlite_backend import create_sqlite_pool
        _pool = await create_sqlite_pool(dsn, max_size=settings.db_max_conns)
        return _pool

    pool = await asyncpg.create_pool(
        dsn,
        min_size=settings.db_min_conns,
        max_size=settings.db_max_conns,
        command_timeout=60,
        timeout=10,
    )

    _pool = pool
    return pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> Optional[Any]:
    return _pool


async def get_pool_required() -> Any:
    pool = get_pool()
    if pool is None:
        raise RuntimeError("Database pool not initialized. Call create_pool() first.")
    return pool


@asynccontextmanager
async def acquire_connection():
    pool = await get_pool_required()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction():
    pool = await get_pool_required()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


async def create_pool_from_config(config) -> Any:
    """Open and cache a pool using a kerf_core Config/Settings instance.

    Branches on the ``database_url`` scheme just like :func:`create_pool`: a
    ``sqlite://`` URL yields the embedded pool, anything else an asyncpg pool.

    asyncpg pool size is resolved from (in priority order):
    1. ``KERF_DB_MAX_CONNS`` environment variable
    2. ``config.db_max_conns`` attribute (if present)
    3. Default of 10
    """
    import os as _os
    global _pool
    if not getattr(config, "database_url", ""):
        raise ValueError("Config.database_url is required but not set")

    try:
        max_size = int(_os.environ.get("KERF_DB_MAX_CONNS", "") or getattr(config, "db_max_conns", 10))
    except (ValueError, TypeError):
        max_size = 10

    if is_sqlite_url(config.database_url):
        from .sqlite_backend import create_sqlite_pool
        _pool = await create_sqlite_pool(config.database_url, max_size=max_size)
        return _pool

    pool = await asyncpg.create_pool(
        config.database_url,
        min_size=2,
        max_size=max_size,
        command_timeout=60,
        timeout=10,
    )
    _pool = pool
    return pool
