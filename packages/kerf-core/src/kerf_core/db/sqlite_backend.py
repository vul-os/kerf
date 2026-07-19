"""aiosqlite-backed drop-in for the asyncpg pool/connection surface.

kerf's whole query layer talks to ``conn.fetch`` / ``conn.fetchrow`` /
``conn.fetchval`` / ``conn.execute`` / ``conn.executemany`` and to the pool's
``acquire()`` / ``transaction()`` — the asyncpg API.  This module provides
:class:`SqlitePool` and :class:`SqliteConnection` that expose the *same* surface
on top of :mod:`aiosqlite`, translating each query through
:mod:`kerf_core.db.dialect` on the way in and returning asyncpg-compatible
``Record`` (``dict``-subclass) rows on the way out.

Design notes
------------
* **Autocommit + explicit txns.** Connections run with ``isolation_level=None``
  so transaction boundaries are ours to control.  :meth:`SqliteConnection.transaction`
  is savepoint-aware, so the ``async with conn.transaction():`` blocks that the
  query layer nests translate to ``BEGIN`` at depth 0 and ``SAVEPOINT`` deeper.
* **execute() status strings.** asyncpg's ``execute`` returns a command tag such
  as ``"UPDATE 1"`` / ``"DELETE 1"`` / ``"INSERT 0 1"`` and several callsites
  compare against those exact strings — so we synthesise them from the SQL verb
  and ``cursor.rowcount``.
* **Pooling.** A small fixed pool of connections over a Queue.  A ``:memory:``
  database is pinned to a single connection (each stdlib in-memory DB is private
  to its connection), which also serialises access — fine for the embedded,
  single-user default.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

import aiosqlite

from .dialect import (
    parse_array_column,
    sqlite_path_from_url,
    translate_query,
    translate_sql,
)


class Record(dict):
    """asyncpg-Record-compatible row.

    A plain ``dict`` subclass so that ``dict(row)``, ``row["col"]``,
    ``row.get(...)`` and ``.keys()`` — every access pattern the query layer uses
    — work unchanged.
    """

    __slots__ = ()


def _row_to_record(cursor_description, row) -> Record:
    return Record(
        (
            cursor_description[i][0],
            parse_array_column(cursor_description[i][0], row[i]),
        )
        for i in range(len(row))
    )


def _command_tag(sql: str, rowcount: int) -> str:
    verb = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    n = rowcount if rowcount is not None and rowcount >= 0 else 0
    if verb == "INSERT":
        return f"INSERT 0 {n}"
    if verb in ("UPDATE", "DELETE"):
        return f"{verb} {n}"
    return verb


class SqliteConnection:
    """asyncpg-Connection-compatible wrapper around an aiosqlite connection."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn
        self._txn_depth = 0

    # ── query surface ──────────────────────────────────────────────────────
    async def execute(self, sql: str, *args: Any) -> str:
        q, params = translate_query(sql, args)
        cur = await self._conn.execute(q, params)
        try:
            return _command_tag(q, cur.rowcount)
        finally:
            await cur.close()

    async def executemany(self, sql: str, args_iter: Iterable[Iterable[Any]]) -> None:
        import re as _re
        from .dialect import adapt_param

        translated = translate_sql(sql)
        # Placeholder order is identical across rows, so compute the $N -> ?
        # rebinding order once and apply it to every row.
        order = [int(m.group(1)) - 1 for m in _re.finditer(r"\$(\d+)", translated)]
        q = _re.sub(r"\$\d+", "?", translated)
        prepared = [
            [adapt_param(r[i]) for i in order] if order
            else [adapt_param(v) for v in r]
            for r in args_iter
        ]
        await self._conn.executemany(q, prepared)

    async def fetch(self, sql: str, *args: Any) -> list[Record]:
        q, params = translate_query(sql, args)
        cur = await self._conn.execute(q, params)
        try:
            rows = await cur.fetchall()
            desc = cur.description
            return [_row_to_record(desc, r) for r in rows]
        finally:
            await cur.close()

    async def fetchrow(self, sql: str, *args: Any) -> Optional[Record]:
        q, params = translate_query(sql, args)
        cur = await self._conn.execute(q, params)
        try:
            row = await cur.fetchone()
            if row is None:
                return None
            return _row_to_record(cur.description, row)
        finally:
            await cur.close()

    async def fetchval(self, sql: str, *args: Any, column: int = 0) -> Any:
        q, params = translate_query(sql, args)
        cur = await self._conn.execute(q, params)
        try:
            row = await cur.fetchone()
            return row[column] if row is not None else None
        finally:
            await cur.close()

    # ── transactions (savepoint-aware) ─────────────────────────────────────
    @asynccontextmanager
    async def transaction(self):
        depth = self._txn_depth
        if depth == 0:
            await self._conn.execute("BEGIN")
        else:
            await self._conn.execute(f"SAVEPOINT kerf_sp_{depth}")
        self._txn_depth += 1
        try:
            yield self
        except BaseException:
            if depth == 0:
                await self._conn.execute("ROLLBACK")
            else:
                await self._conn.execute(f"ROLLBACK TO kerf_sp_{depth}")
                await self._conn.execute(f"RELEASE kerf_sp_{depth}")
            self._txn_depth -= 1
            raise
        else:
            if depth == 0:
                await self._conn.execute("COMMIT")
            else:
                await self._conn.execute(f"RELEASE kerf_sp_{depth}")
            self._txn_depth -= 1

    # ── LISTEN/NOTIFY compatibility (embedded mode has no pub/sub) ──────────
    async def add_listener(self, channel: str, callback) -> None:
        """No-op: embedded SQLite has no LISTEN/NOTIFY. Workers that use this
        (kerf-tess) fall back to their polling loop, which always exists."""

    async def remove_listener(self, channel: str, callback) -> None:
        """No-op counterpart to :meth:`add_listener`."""

    async def close(self) -> None:
        await self._conn.close()


class _PoolAcquireCtx:
    def __init__(self, pool: "SqlitePool"):
        self._pool = pool
        self._conn: Optional[SqliteConnection] = None

    async def __aenter__(self) -> SqliteConnection:
        self._conn = await self._pool._acquire()
        return self._conn

    async def __aexit__(self, *exc) -> None:
        assert self._conn is not None
        await self._pool._release(self._conn)
        self._conn = None

    def __await__(self):
        # Support `conn = await pool.acquire()` too (asyncpg allows it).
        return self._pool._acquire().__await__()


class SqlitePool:
    """asyncpg-Pool-compatible pool of :class:`SqliteConnection`."""

    def __init__(self, connections: list[SqliteConnection], is_memory: bool):
        self._all = connections
        self._queue: asyncio.Queue[SqliteConnection] = asyncio.Queue()
        for c in connections:
            self._queue.put_nowait(c)
        self._is_memory = is_memory
        self._closed = False

    async def _acquire(self) -> SqliteConnection:
        return await self._queue.get()

    async def _release(self, conn: SqliteConnection) -> None:
        self._queue.put_nowait(conn)

    def acquire(self) -> _PoolAcquireCtx:
        return _PoolAcquireCtx(self)

    async def release(self, conn: SqliteConnection) -> None:
        await self._release(conn)

    # ── pool-level convenience methods (asyncpg parity; used by kerf-pub) ──
    async def execute(self, sql: str, *args: Any) -> str:
        conn = await self._acquire()
        try:
            return await conn.execute(sql, *args)
        finally:
            await self._release(conn)

    async def executemany(self, sql: str, args_iter) -> None:
        conn = await self._acquire()
        try:
            return await conn.executemany(sql, args_iter)
        finally:
            await self._release(conn)

    async def fetch(self, sql: str, *args: Any) -> list[Record]:
        conn = await self._acquire()
        try:
            return await conn.fetch(sql, *args)
        finally:
            await self._release(conn)

    async def fetchrow(self, sql: str, *args: Any) -> Optional[Record]:
        conn = await self._acquire()
        try:
            return await conn.fetchrow(sql, *args)
        finally:
            await self._release(conn)

    async def fetchval(self, sql: str, *args: Any, column: int = 0) -> Any:
        conn = await self._acquire()
        try:
            return await conn.fetchval(sql, *args, column=column)
        finally:
            await self._release(conn)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for c in self._all:
            try:
                await c.close()
            except Exception:
                pass


async def _open_connection(path: str) -> SqliteConnection:
    conn = await aiosqlite.connect(path, isolation_level=None)
    # asyncpg-style: rows are keyed; we map to Record ourselves, so keep the
    # raw tuple factory and read cursor.description for names.
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA busy_timeout = 5000")
    if path != ":memory:":
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA synchronous = NORMAL")
    return SqliteConnection(conn)


async def create_sqlite_pool(url: str, *, max_size: int = 5) -> SqlitePool:
    """Open (creating parent dirs as needed) an embedded SQLite pool for *url*."""
    path = sqlite_path_from_url(url)
    is_memory = path == ":memory:"
    if not is_memory:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        path = str(p)
    size = 1 if is_memory else max(1, max_size)
    conns = [await _open_connection(path) for _ in range(size)]
    return SqlitePool(conns, is_memory=is_memory)
