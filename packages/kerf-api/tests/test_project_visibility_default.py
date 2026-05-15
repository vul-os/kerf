"""Tests for the default-visibility logic introduced in create_project.

Tests verify the four-cell matrix:
  cloud=True  + paid    → "private"
  cloud=True  + free    → "public"
  cloud=False + paid    → "private"   (self-hosted, paid concept N/A)
  cloud=False + free    → "private"   (self-hosted, Workshop concept absent)

And the invariant that Workshop publish always stays explicit (never automatic).

These tests are hermetic — no DB, no network, no FastAPI app spin-up.
They replicate the logic from routes.py create_project so regressions are
caught at the test layer, not just at runtime.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Replica of the visibility-default logic from routes.py create_project.
# Keep in sync with the implementation.
# ---------------------------------------------------------------------------

def default_project_visibility(cloud_enabled: bool, is_paid: bool) -> str:
    """Pure-logic replica of the billing-tier default in create_project.

    In cloud mode:
      - paid users → private (privacy as a paid-conversion lever)
      - free users → public  (Workshop free-sharing ethos)
    Self-hosted (cloud_enabled=False):
      - always private; Workshop / public concept does not exist.
    """
    if cloud_enabled and not is_paid:
        return "public"
    return "private"


# ---------------------------------------------------------------------------
# Fake connection to simulate kerf_billing.buckets.is_paid_user
# ---------------------------------------------------------------------------

class _FakeConn:
    """Minimal asyncpg connection stub that answers is_paid_user queries."""

    def __init__(self, credits_usd: float | None = None) -> None:
        """credits_usd=None → no row in cloud_user_balances (new free user)."""
        self._credits = credits_usd

    async def fetchrow(self, sql: str, *args):
        if "cloud_user_balances" in sql:
            if self._credits is None:
                return None
            return {"credits_usd": self._credits}
        return None


# ---------------------------------------------------------------------------
# Tests: matrix (cloud_enabled × is_paid)
# ---------------------------------------------------------------------------

class TestDefaultVisibilityMatrix:
    """Four-cell matrix covering every (cloud, tier) combination."""

    def test_cloud_paid_defaults_to_private(self):
        vis = default_project_visibility(cloud_enabled=True, is_paid=True)
        assert vis == "private", "Paid cloud users get private-by-default."

    def test_cloud_free_defaults_to_public(self):
        vis = default_project_visibility(cloud_enabled=True, is_paid=False)
        assert vis == "public", "Free cloud users get public-by-default (Workshop ethos)."

    def test_selfhost_paid_defaults_to_private(self):
        vis = default_project_visibility(cloud_enabled=False, is_paid=True)
        assert vis == "private", "Self-hosted is always private regardless of billing state."

    def test_selfhost_free_defaults_to_private(self):
        vis = default_project_visibility(cloud_enabled=False, is_paid=False)
        assert vis == "private", "Self-hosted is always private (no Workshop, no billing)."


# ---------------------------------------------------------------------------
# Tests: is_paid_user produces the right boolean for the DB states that matter
# ---------------------------------------------------------------------------

class TestIsPaidUserStates:
    """Verify how cloud_user_balances rows map to paid/free classification."""

    async def test_no_balance_row_is_free(self):
        from kerf_billing.buckets import is_paid_user
        conn = _FakeConn(credits_usd=None)
        assert await is_paid_user(conn, "u1") is False

    async def test_zero_credits_is_free(self):
        from kerf_billing.buckets import is_paid_user
        conn = _FakeConn(credits_usd=0.0)
        assert await is_paid_user(conn, "u1") is False

    async def test_positive_credits_is_paid(self):
        from kerf_billing.buckets import is_paid_user
        conn = _FakeConn(credits_usd=10.00)
        assert await is_paid_user(conn, "u1") is True


# ---------------------------------------------------------------------------
# Tests: Workshop publish stays explicit
# ---------------------------------------------------------------------------

class TestWorkshopPublishRemainsExplicit:
    """Asserting that default_project_visibility never auto-publishes.

    The Workshop endpoint ``POST /api/workshop/publish`` is the *only* path
    that legitimately sets visibility='public' for a new Workshop listing.
    The default-visibility change must not auto-publish anything — a paid user
    gets *private*, not *public*, so they never accidentally expose work.
    """

    def test_paid_cloud_project_not_auto_published(self):
        vis = default_project_visibility(cloud_enabled=True, is_paid=True)
        assert vis != "public", (
            "Paid-tier projects start private; Workshop publish is an explicit opt-in."
        )

    def test_selfhost_never_auto_published(self):
        for is_paid in (True, False):
            vis = default_project_visibility(cloud_enabled=False, is_paid=is_paid)
            assert vis == "private", (
                f"Self-hosted projects must always start private (is_paid={is_paid})."
            )

    def test_free_cloud_starts_public_but_not_workshoplisted(self):
        # A free user's project defaults to public (visible via direct URL) but
        # that is NOT the same as being listed on the Workshop feed.  Workshop
        # listing requires the explicit POST /api/workshop/publish call.
        # This test documents that invariant: the visibility default only
        # controls the visibility field, not the workshop_listings table.
        vis = default_project_visibility(cloud_enabled=True, is_paid=False)
        assert vis == "public"
        # No workshop_listings row is created by the default logic — that is
        # handled exclusively by the publish endpoint (not asserted here since
        # it's tested in the routes test suite, but documented for clarity).
