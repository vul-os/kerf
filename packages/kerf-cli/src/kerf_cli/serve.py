"""kerf serve — self-host entrypoint.

Fails fast with a clear, actionable error when DATABASE_URL is missing
or points to an unreachable host.  On success: runs migrations then
starts the existing kerf-core FastAPI server via uvicorn.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Public constants (used by tests)
# ---------------------------------------------------------------------------

DOCKER_ONE_LINER = (
    "docker run -d --name kerf-postgres "
    "-e POSTGRES_PASSWORD=kerf "
    "-p 5432:5432 "
    "postgres:16"
)

EXPORT_LINE = "export DATABASE_URL=postgres://postgres:kerf@localhost:5432/kerf"

# The full fail-fast error message (newline-terminated)
MISSING_URL_MESSAGE = (
    "Error: DATABASE_URL is not set.\n"
    "\n"
    "kerf serve requires a PostgreSQL database.  To spin up a local instance:\n"
    "\n"
    f"    {DOCKER_ONE_LINER}\n"
    f"    {EXPORT_LINE}\n"
    "\n"
    "Then re-run:  kerf serve\n"
)

UNREACHABLE_MESSAGE_PREFIX = "Error: cannot connect to DATABASE_URL"
UNREACHABLE_MESSAGE_SUFFIX = (
    "\n"
    "\n"
    "Ensure PostgreSQL is running and DATABASE_URL is correct.\n"
    "To spin up a local instance:\n"
    "\n"
    f"    {DOCKER_ONE_LINER}\n"
    f"    {EXPORT_LINE}\n"
    "\n"
    "Then re-run:  kerf serve\n"
)


def _unreachable_message(url: str) -> str:
    """Return the full 'unreachable' error message for the given URL."""
    return (
        f"{UNREACHABLE_MESSAGE_PREFIX} ({url!r}){UNREACHABLE_MESSAGE_SUFFIX}"
    )


async def _check_db(url: str) -> Optional[str]:
    """Try to open a connection.  Returns an error message string or None."""
    try:
        import asyncpg  # noqa: PLC0415 — optional server dep
    except ImportError:
        # asyncpg is only present in the [server] extra; if we got here the
        # caller already checked for it.
        return "asyncpg is not installed.  Run: pip install 'kerf-cli[server]'"

    try:
        conn = await asyncio.wait_for(asyncpg.connect(url), timeout=5)
        await conn.close()
        return None
    except asyncio.TimeoutError:
        return _unreachable_message(url)
    except Exception as exc:  # noqa: BLE001
        return _unreachable_message(url) + f"\nDetail: {exc}\n"


def run_serve(
    *,
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
    workers: int = 1,
    config: str = "",
    skip_migrate: bool = False,
) -> None:
    """Entry point for `kerf serve`.

    Backend selection is by DATABASE_URL scheme:
      * unset            -> embedded SQLite at ~/.kerf/kerf.db (zero-dependency
                            default; no pre-flight, the file is auto-created).
      * ``sqlite://…``   -> that SQLite file.
      * ``postgres://…`` -> the Postgres scale backend, with the two historical
                            pre-flight checks (set + reachable).

    Fails with sys.exit(1) only on a Postgres pre-flight error.
    """
    from kerf_core.db.config import default_database_url  # noqa: PLC0415
    from kerf_core.db.dialect import is_sqlite_url  # noqa: PLC0415

    # --- Resolve backend: default to embedded SQLite when unset --------------
    db_url = os.environ.get("DATABASE_URL", "").strip() or default_database_url()

    if is_sqlite_url(db_url):
        # Embedded default — no server to reach, nothing to fail on.
        os.environ["DATABASE_URL"] = db_url
        print(f"Using embedded SQLite database ({db_url}).")
        print(
            "  (Zero-dependency default. For teams / always-on nodes, set "
            "DATABASE_URL=postgres://… to use the Postgres scale backend.)"
        )
    else:
        # --- Pre-flight: unreachable DATABASE_URL (Postgres) -----------------
        error = asyncio.run(_check_db(db_url))
        if error:
            sys.stderr.write(error)
            sys.exit(1)

    # --- Optional: run migrations -------------------------------------------
    if not skip_migrate:
        try:
            from kerf_core.db.migrations.runner import run_migrations  # noqa: PLC0415
        except ImportError:
            sys.stderr.write(
                "Error: kerf-core is not installed.  "
                "Run: pip install 'kerf-cli[server]'\n"
            )
            sys.exit(1)

        print("Running migrations…")
        asyncio.run(run_migrations(db_url))

    # --- Start server --------------------------------------------------------
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        sys.stderr.write(
            "Error: uvicorn is not installed.  "
            "Run: pip install 'kerf-cli[server]'\n"
        )
        sys.exit(1)

    if config:
        os.environ["KERF_CONFIG"] = config

    uvicorn.run(
        "kerf_core.app:create_app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
        factory=True,
        log_level="info",
    )
