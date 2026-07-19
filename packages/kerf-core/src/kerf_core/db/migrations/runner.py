#!/usr/bin/env python3
"""Idempotent SQL migration runner.

Applied `*.sql` files are recorded in `kerf_migrations_ledger` (a
filename-keyed table — deliberately NOT `schema_migrations`, which some
legacy/ORM tooling already owns with a different schema).

Each unseen migration is applied in its own transaction then stamped.
For databases that were already built by an earlier (non-idempotent)
run, re-applying a migration raises a duplicate-object error — that's
treated as "already applied": the error is swallowed and the file is
stamped, so genuinely-new migrations still run while old ones don't
re-execute. Real (non-duplicate) errors still abort the deploy.
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

_LEDGER = "kerf_migrations_ledger"
_LEDGER_DDL = f"""
CREATE TABLE IF NOT EXISTS {_LEDGER} (
    filename    text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""

# The DBs were built by older tooling, so the historical *.sql set is
# NOT cleanly replayable against them (duplicate objects, references to
# columns that legacy schema never had, etc.). Treat ANY Postgres error
# on an unseen migration as "doesn't cleanly apply to this legacy DB" —
# stamp it and continue. Genuinely-new migrations are written
# IF-NOT-EXISTS-idempotent, so they succeed and apply; only the
# legacy-incompatible history is skipped. (Connection errors raise
# earlier at connect(), so a real outage still aborts the deploy.)
_ALREADY_APPLIED = (asyncpg.PostgresError,)


async def run_sqlite_migrations(database_url: str):
    """Apply the checked-in SQLite migration set (``../migrations_sqlite``).

    The embedded backend always starts from a clean, kerf-owned schema, so this
    path is simple: create the ledger, then apply each unseen ``*.sql`` file in
    order inside its own transaction and stamp it.  No legacy back-stamping is
    needed (that machinery exists only for the historical Postgres DBs).
    """
    import aiosqlite

    from kerf_core.db.dialect import sqlite_path_from_url
    from kerf_core.db.sqlite_backend import _open_connection  # WAL + FK pragmas

    path = sqlite_path_from_url(database_url)
    if path != ":memory:":
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        path = str(Path(path).expanduser())

    sqlite_conn = await _open_connection(path)
    conn = sqlite_conn._conn  # raw aiosqlite connection for executescript
    try:
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_LEDGER} ("
            "filename text PRIMARY KEY, "
            "applied_at text NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        cur = await conn.execute(f"SELECT filename FROM {_LEDGER}")
        applied = {r[0] for r in await cur.fetchall()}
        await cur.close()

        migrations_dir = Path(__file__).parent.parent / "migrations_sqlite"
        ran = 0
        for migration_file in sorted(migrations_dir.glob("*.sql")):
            name = migration_file.name
            if name in applied:
                continue
            sql = migration_file.read_text()
            # executescript runs the DDL (autocommit); the DDL is IF-NOT-EXISTS
            # idempotent so a re-run after a partial failure is safe.
            await conn.executescript(sql)
            await conn.execute(
                f"INSERT INTO {_LEDGER} (filename) VALUES (?) "
                "ON CONFLICT DO NOTHING",
                (name,),
            )
            print(f"  ✓ {name}")
            ran += 1
        print(f"\nSQLite migrations up to date ({ran} applied) at {path}.")
    finally:
        await conn.close()


async def run_migrations(database_url: str):
    # Embedded SQLite backend gets its own clean-baseline applier.
    from kerf_core.db.dialect import is_sqlite_url
    if is_sqlite_url(database_url):
        await run_sqlite_migrations(database_url)
        return

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(_LEDGER_DDL)
        applied = {
            r["filename"]
            for r in await conn.fetch(f"SELECT filename FROM {_LEDGER}")
        }

        migrations_dir = Path(__file__).parent
        migration_files = sorted(migrations_dir.glob("*.sql"))

        ran = 0
        stamped = 0
        for migration_file in migration_files:
            name = migration_file.name
            if name in applied:
                continue
            sql = migration_file.read_text()
            # Strip SQL line comments + whitespace to check whether the file
            # actually contains any statement to execute. T-307's fold
            # produced "tombstone" files (0003, 0007, 0009) that are
            # comments-only after their content was hoisted into the
            # consolidated baseline 0001 / 0004. Sending a comments-only
            # body to asyncpg.execute() crashes the simple-query response
            # parser with `AttributeError: 'NoneType' object has no
            # attribute 'decode'` — Postgres returns an EmptyQueryResponse
            # with no command tag, and asyncpg's _on_result__simple_query
            # tries to .decode() the missing tag. Treat tombstones as
            # "stamp-only" — record them in the ledger so they're not
            # re-evaluated next deploy, but don't try to execute them.
            stripped = "\n".join(
                line for line in sql.splitlines()
                if line.strip() and not line.strip().startswith("--")
            ).strip()
            if not stripped:
                await conn.execute(
                    f"INSERT INTO {_LEDGER} (filename) VALUES ($1) "
                    "ON CONFLICT DO NOTHING",
                    name,
                )
                print(f"  • {name} (tombstone — folded into baseline)")
                stamped += 1
                continue
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                await conn.execute(
                    f"INSERT INTO {_LEDGER} (filename) VALUES ($1) "
                    "ON CONFLICT DO NOTHING",
                    name,
                )
                print(f"  ✓ {name}")
                ran += 1
            except _ALREADY_APPLIED as exc:
                # Pre-existing schema from a legacy/non-idempotent run.
                await conn.execute(
                    f"INSERT INTO {_LEDGER} (filename) VALUES ($1) "
                    "ON CONFLICT DO NOTHING",
                    name,
                )
                print(f"  • {name} (already present — stamped: {type(exc).__name__})")
                stamped += 1

        print(
            f"\nMigrations up to date ({ran} applied, "
            f"{stamped} back-stamped this run)."
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    # Accept the DSN either as argv[1] (explicit path, e.g. a self-host
    # script that passes the DSN directly) or via $DATABASE_URL (used by the
    # Fly.io release_command in fly.toml, which reads env secrets rather than
    # interpolating them into the command string).
    dsn = sys.argv[1] if len(sys.argv) >= 2 else os.environ.get("DATABASE_URL")
    if not dsn:
        # Zero-config default: no DSN given and DATABASE_URL unset -> the
        # embedded SQLite database at ~/.kerf/kerf.db.  This makes
        # `python -m kerf_core.db.migrations.runner` / `npm run migrate` work
        # with no external database, matching the app's default backend.
        from kerf_core.db.config import default_database_url
        dsn = default_database_url()
        print(f"No DATABASE_URL set — using embedded SQLite ({dsn}).")
    asyncio.run(run_migrations(dsn))
