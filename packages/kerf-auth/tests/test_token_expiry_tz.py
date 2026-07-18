"""Test: email/reset token expires_at round-trips as correct UTC instant.

The bug: _create_email_token and issue_tokens previously used naive
datetime.utcnow() for the expires_at column.  asyncpg/Postgres interprets a
naive datetime in the DB session timezone — on a UTC+2 box the expiry was
shifted 2 h early (tokens appeared expired when they weren't, or vice-versa).

Fix: datetime.now(timezone.utc) produces a tz-aware value that Postgres
stores and returns as the correct absolute UTC instant regardless of the
connection's SET TIME ZONE.

This test:
1. Opens a real asyncpg connection and sets the session to Africa/Johannesburg
   (UTC+2) — the timezone that triggered the original SAST failure.
2. Inserts an email token via _create_email_token.
3. Reads back expires_at and asserts it is within 5 s of the expected UTC
   instant (not shifted by ±2 h).
4. Asserts a freshly issued token is NOT considered expired by the DB query
   that the /reset-password route uses (the only email_tokens kind still
   issued — Kerf sends no email, so accounts are auto-verified at
   registration instead of via an emailed 'verify' token; decisions.md
   2026-07-18 "accounts shrink to the box").

Requires DATABASE_URL to be set; skips otherwise.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _skip_no_db():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set — skipping tz round-trip test")


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid_email(tag: str) -> str:
    return f"tz-test-{tag}-{uuid.uuid4().hex[:12]}@test.invalid"


async def _setup_user(conn) -> str:
    """Insert a throw-away user; return its id as a str."""
    row = await conn.fetchrow(
        "INSERT INTO users (email, name, password_hash) "
        "VALUES ($1, 'TZ Test User', 'x') RETURNING id",
        _uuid_email("main"),
    )
    return str(row["id"])


async def _teardown_user(conn, user_id: str) -> None:
    uid = uuid.UUID(user_id)
    await conn.execute("DELETE FROM email_tokens WHERE user_id = $1", uid)
    await conn.execute("DELETE FROM refresh_tokens WHERE user_id = $1", uid)
    await conn.execute("DELETE FROM users WHERE id = $1", uid)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEmailTokenTZRoundTrip:
    """email_tokens.expires_at stores the correct absolute UTC instant."""

    def test_email_token_expires_at_is_correct_utc_instant(self):
        """_create_email_token writes a tz-aware expires_at; read-back in a
        Africa/Johannesburg session must match the original UTC instant.

        Exercises the 'reset' kind — the only one still issued now that
        Kerf sends no email and accounts are auto-verified at registration
        (decisions.md 2026-07-18 "accounts shrink to the box"; a 'verify'
        kind token is never created any more). ``_create_email_token``'s
        tz-correctness is kind-agnostic, so this is exactly the same
        regression coverage the original 'verify'-kind version had.
        """
        _skip_no_db()

        import asyncpg
        from kerf_auth.routes import _create_email_token, RESET_TOKEN_TTL

        async def _run():
            pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
            try:
                async with pool.acquire() as conn:
                    user_id = await _setup_user(conn)
                    try:
                        # Record the expected expiry BEFORE the insert.
                        before = datetime.now(timezone.utc)
                        expected_expires = before + RESET_TOKEN_TTL

                        # Force the session timezone to Africa/Johannesburg (UTC+2).
                        # This is exactly the environment that triggered the original bug.
                        await conn.execute("SET TIME ZONE 'Africa/Johannesburg'")

                        # Call the production code path.
                        await _create_email_token(conn, user_id, "reset", RESET_TOKEN_TTL)

                        # Read back; AT TIME ZONE 'UTC' ensures we compare apples to apples.
                        row = await conn.fetchrow(
                            "SELECT expires_at AT TIME ZONE 'UTC' AS expires_utc "
                            "FROM email_tokens WHERE user_id = $1 ORDER BY id DESC LIMIT 1",
                            uuid.UUID(user_id),
                        )
                        assert row is not None, "No email_token row found after insert"

                        # Postgres returns a naive datetime for AT TIME ZONE output; attach UTC.
                        stored_utc = row["expires_utc"].replace(tzinfo=timezone.utc)

                        delta = abs((stored_utc - expected_expires).total_seconds())
                        assert delta < 5, (
                            f"expires_at round-trip error: expected ~{expected_expires.isoformat()}, "
                            f"got {stored_utc.isoformat()} — delta={delta:.1f}s "
                            f"(bug: naive utcnow() shifted by session timezone)"
                        )

                        # Sanity: the stored instant must NOT be 2 h off (the old bug amount).
                        assert delta < 7200 * 0.9, (
                            "expires_at is shifted by ~2 h — tz-aware fix not applied"
                        )
                    finally:
                        await _teardown_user(conn, user_id)
            finally:
                await pool.close()

        asyncio.run(_run())

    def test_fresh_reset_token_not_expired_in_johannesburg_session(self):
        """A freshly inserted reset token must pass the DB expiry check
        even when the session timezone is UTC+2."""
        _skip_no_db()

        import asyncpg
        from kerf_auth.routes import _create_email_token, RESET_TOKEN_TTL, hash_token

        async def _run():
            pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
            try:
                async with pool.acquire() as conn:
                    user_id = await _setup_user(conn)
                    try:
                        await conn.execute("SET TIME ZONE 'Africa/Johannesburg'")

                        raw = await _create_email_token(conn, user_id, "reset", RESET_TOKEN_TTL)

                        # Replicate the exact query used by /reset-password.
                        row = await conn.fetchrow(
                            "SELECT id, user_id FROM email_tokens "
                            "WHERE token_hash = $1 AND kind = 'reset' "
                            "  AND used_at IS NULL AND expires_at > now()",
                            hash_token(raw),
                        )
                        assert row is not None, (
                            "Fresh reset token was considered expired immediately — "
                            "timezone bug still present"
                        )
                    finally:
                        await _teardown_user(conn, user_id)
            finally:
                await pool.close()

        asyncio.run(_run())
