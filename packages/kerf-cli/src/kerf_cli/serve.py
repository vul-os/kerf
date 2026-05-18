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

    Performs two pre-flight checks before handing off to uvicorn:
      1. DATABASE_URL must be set (env var).
      2. DATABASE_URL must be reachable (5-second TCP+auth check).

    Fails with sys.exit(1) on any error.
    """
    # --- Pre-flight: missing DATABASE_URL -----------------------------------
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        sys.stderr.write(MISSING_URL_MESSAGE)
        sys.exit(1)

    # --- Pre-flight: unreachable DATABASE_URL --------------------------------
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
