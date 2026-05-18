import uuid
from typing import Optional

import asyncpg


async def record_blob(
    conn: asyncpg.Connection,
    oid: str,
    size: int,
    first_ws: Optional[uuid.UUID],
) -> None:
    """Insert a new blob_objects row (no-op if oid already exists)."""
    await conn.execute(
        """
        INSERT INTO blob_objects (oid, size_bytes, first_workspace_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (oid) DO NOTHING
        """,
        oid,
        size,
        first_ws,
    )


async def add_ref(
    conn: asyncpg.Connection,
    oid: str,
    project_id: uuid.UUID,
    path: str,
) -> None:
    """Record that a project references a blob at the given path.

    Idempotent: silently ignored if the (oid, project_id, path) row
    already exists.
    """
    await conn.execute(
        """
        INSERT INTO blob_refs (oid, project_id, path)
        VALUES ($1, $2, $3)
        ON CONFLICT (oid, project_id, path) DO NOTHING
        """,
        oid,
        project_id,
        path,
    )


async def drop_ref(
    conn: asyncpg.Connection,
    oid: str,
    project_id: uuid.UUID,
    path: str,
) -> None:
    """Remove a single (oid, project_id, path) reference row.

    When removing this ref causes the ref-count to reach zero, stamps
    ``blob_objects.last_unref_at`` with the current time.  The GC sweep
    worker uses this as the start of the 72-hour grace window.
    """
    await conn.execute(
        "DELETE FROM blob_refs WHERE oid = $1 AND project_id = $2 AND path = $3",
        oid,
        project_id,
        path,
    )
    # Stamp last_unref_at if this was the final ref for the oid.
    await conn.execute(
        """
        UPDATE blob_objects
        SET last_unref_at = now()
        WHERE oid = $1
          AND last_unref_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM blob_refs WHERE oid = $1)
        """,
        oid,
    )


async def refcount(
    conn: asyncpg.Connection,
    oid: str,
) -> int:
    """Return the total number of refs pointing at this oid across all projects."""
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM blob_refs WHERE oid = $1",
        oid,
    )
    return int(count or 0)


async def first_workspace(
    conn: asyncpg.Connection,
    oid: str,
) -> Optional[uuid.UUID]:
    """Return the first_workspace_id for this oid, or None if not found."""
    return await conn.fetchval(
        "SELECT first_workspace_id FROM blob_objects WHERE oid = $1",
        oid,
    )
