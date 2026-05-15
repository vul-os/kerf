"""Tests for is_paid_user and the default-visibility helper.

All tests are hermetic (no network, no real DB).
"""
from __future__ import annotations

import pytest

from kerf_billing.buckets import is_paid_user


# ── Minimal fake asyncpg connection ─────────────────────────────────────────
class _Conn:
    """Records fetchrow calls; callers control what gets returned."""

    def __init__(self, rows: dict | None = None) -> None:
        # ``rows`` maps a SELECT SQL fragment → row dict (or None)
        self._rows = rows or {}
        self.queries: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql: str, *args):
        self.queries.append((sql, args))
        # Match by first keyword in the FROM clause; keyed by table name.
        for key, row in self._rows.items():
            if key in sql:
                return row
        return None


# ── is_paid_user ─────────────────────────────────────────────────────────────
class TestIsPaidUser:
    async def test_no_balance_row_is_free(self):
        conn = _Conn(rows={"cloud_user_balances": None})
        result = await is_paid_user(conn, "user-1")
        assert result is False

    async def test_zero_credits_is_free(self):
        conn = _Conn(rows={"cloud_user_balances": {"credits_usd": 0}})
        result = await is_paid_user(conn, "user-1")
        assert result is False

    async def test_positive_credits_is_paid(self):
        conn = _Conn(rows={"cloud_user_balances": {"credits_usd": 5.00}})
        result = await is_paid_user(conn, "user-1")
        assert result is True

    async def test_small_positive_credits_is_paid(self):
        conn = _Conn(rows={"cloud_user_balances": {"credits_usd": 0.0001}})
        result = await is_paid_user(conn, "user-1")
        assert result is True

    async def test_query_passes_user_id(self):
        conn = _Conn(rows={"cloud_user_balances": None})
        await is_paid_user(conn, "abc-123")
        assert len(conn.queries) == 1
        _sql, args = conn.queries[0]
        assert args[0] == "abc-123"


# ── Default visibility logic (matrix: cloud × tier) ──────────────────────────

def _default_visibility(cloud_enabled: bool, is_paid: bool) -> str:
    """Mirror the logic in create_project so we can test it without spinning
    up FastAPI.  Keep in sync with the implementation in routes.py."""
    if cloud_enabled and not is_paid:
        return "public"
    return "private"


class TestDefaultVisibilityMatrix:
    """Four-cell matrix: cloud/self-host × paid/free."""

    def test_cloud_paid_is_private(self):
        assert _default_visibility(cloud_enabled=True, is_paid=True) == "private"

    def test_cloud_free_is_public(self):
        assert _default_visibility(cloud_enabled=True, is_paid=False) == "public"

    def test_selfhost_paid_is_private(self):
        # Self-hosted never touches the billing module; the cloud_enabled=False
        # branch always returns "private" regardless of any billing state.
        assert _default_visibility(cloud_enabled=False, is_paid=True) == "private"

    def test_selfhost_free_is_private(self):
        # On self-host "free" has no meaning (no Workshop), still private.
        assert _default_visibility(cloud_enabled=False, is_paid=False) == "private"


# ── Workshop publish stays explicit (invariant guard) ────────────────────────
class TestWorkshopPublishExplicit:
    """Publish endpoint is a separate POST /api/workshop/publish that always
    sets visibility='public' when called.  The default-visibility change must
    NOT touch that codepath.  This test is a documentation-level assertion;
    the actual endpoint lives in routes.py and is exercised by its own suite.

    We just verify that _default_visibility never returns 'public' on
    self-host (the only context where that could accidentally affect Workshop)
    and that a paid cloud user starts private (not auto-published).
    """

    def test_cloud_paid_starts_private_not_published(self):
        vis = _default_visibility(cloud_enabled=True, is_paid=True)
        assert vis == "private", "Paid-tier project must start private, not auto-published."

    def test_selfhost_always_private(self):
        # Self-hosted Workshop concept doesn't exist; default must be private.
        for is_paid in (True, False):
            vis = _default_visibility(cloud_enabled=False, is_paid=is_paid)
            assert vis == "private", f"Self-host must always default private (is_paid={is_paid})."
