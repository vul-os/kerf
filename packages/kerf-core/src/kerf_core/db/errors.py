"""Backend-agnostic predicates for database errors.

The query layer is written against asyncpg, so route handlers catch
``asyncpg.UniqueViolationError`` to turn a duplicate into a 409 or to recover
from a lost insert race. On the embedded SQLite backend that exception never
arrives — the driver raises ``sqlite3.IntegrityError`` — so those handlers did
not fire and the route answered 500 instead.

That was not theoretical. ``POST /auth/bootstrap-local`` uses the pattern to
absorb a lost race when two requests bootstrap the local singleton user at the
same moment; on SQLite the un-caught IntegrityError became a 500 and the app
showed "Your session expired — sign in again" on a fresh local install. The
same shape governs a duplicate signup email and a duplicate workspace slug,
both of which owe the caller a 409.

Use :func:`is_unique_violation` in an ``except Exception`` handler rather than
naming a driver's exception class directly.
"""
from __future__ import annotations

import sqlite3

import asyncpg


def is_unique_violation(exc: BaseException) -> bool:
    """True when *exc* is a unique/primary-key constraint violation.

    Recognises asyncpg's typed exception and SQLite's message-tagged
    ``IntegrityError``. SQLite reuses ``IntegrityError`` for NOT NULL, CHECK and
    foreign-key failures too, so the message tag is what distinguishes them —
    those must keep propagating rather than being mistaken for a duplicate.
    """
    if isinstance(exc, asyncpg.UniqueViolationError):
        return True
    if isinstance(exc, sqlite3.IntegrityError):
        return "unique constraint failed" in str(exc).lower()
    return False
