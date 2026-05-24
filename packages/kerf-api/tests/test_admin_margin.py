"""T-408 — Break-even margin view + admin route tests.

Strategy: hermetic — all DB calls intercepted by _FakePool / _FakeConn.
No real Postgres connection required.

Tests:
  1. Non-admin user → 403
  2. Unauthenticated → 401
  3. Admin with no usage data → zero totals, null break_even_seats
  4. Admin with known kerf_paid events → correct revenue / COGS / margin
  5. Admin with kerf_free events → zero revenue, COGS absorbed
  6. Mixed payers + kinds → per-kind breakdown sums correctly
  7. Bad month format → 422
  8. Custom fixed_cost_usd query param overrides default
  9. break_even_seats computed correctly for known margin rate
 10. margin_pct is null when no revenue
"""
from __future__ import annotations

import sys
import uuid
import pathlib
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# sys.path bootstrap — mirrors other test files in kerf-api/tests/
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).parent
_PACKAGES_ROOT = _HERE.parent.parent

for _entry in _PACKAGES_ROOT.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_JWT_SECRET = "dev-secret-change-in-production"
_ADMIN_ID = str(uuid.uuid4())
_USER_ID = str(uuid.uuid4())   # regular user; not admin

# Month string used in most tests
_MONTH = "2026-05"
_MONTH_DATE = date(2026, 5, 1)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _mint_jwt(user_id: str) -> str:
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {"sub": user_id, "exp": now + timedelta(hours=1), "iat": now},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _auth(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_mint_jwt(user_id)}"}


# ---------------------------------------------------------------------------
# Fake DB layer
# ---------------------------------------------------------------------------

class _FakeRow(dict):
    """dict that supports both item and attribute access (asyncpg Record-like)."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _margin_row(
    *,
    kind: str,
    revenue_usd: float,
    cogs_usd: float,
    gross_margin_usd: float,
    event_count: int,
) -> _FakeRow:
    return _FakeRow({
        "kind": kind,
        "revenue_usd": Decimal(str(revenue_usd)),
        "cogs_usd": Decimal(str(cogs_usd)),
        "gross_margin_usd": Decimal(str(gross_margin_usd)),
        "event_count": event_count,
    })


class _FakeConn:
    """Configurable fake asyncpg connection for the margin route."""

    def __init__(
        self,
        *,
        user_account_role: str = "user",
        margin_rows: Optional[list[_FakeRow]] = None,
    ):
        self._role = user_account_role
        self._margin_rows = margin_rows or []

    # asynccontextmanager protocol (used as `async with pool.acquire() as conn`)
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def fetchrow(self, query: str, *args, **kwargs) -> Optional[_FakeRow]:
        q = query.strip().lower()
        if "from users" in q or "select account_role" in q:
            user_id_arg = args[0] if args else None
            admin_uuid = uuid.UUID(_ADMIN_ID)
            if user_id_arg == admin_uuid:
                return _FakeRow({"account_role": "admin"})
            # Any other user_id → regular user
            return _FakeRow({"account_role": self._role})
        return None

    async def fetch(self, query: str, *args, **kwargs) -> list[_FakeRow]:
        q = query.strip().lower()
        if "from" in q and "monthly_margin" in q:
            return self._margin_rows
        return []

    async def execute(self, query: str, *args, **kwargs) -> str:
        return "OK"


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        return self._conn


# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------

def _build_app() -> FastAPI:
    import kerf_core.db.connection as _conn_mod
    from kerf_api.routes_admin_margin import router as margin_router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _conn_mod._pool = object()  # sentinel; replaced by patch below
        yield
        _conn_mod._pool = None

    app = FastAPI(lifespan=lifespan)
    app.include_router(margin_router, prefix="/api")
    return app


_APP = _build_app()


@contextmanager
def _patched_client(conn: _FakeConn):
    pool = _FakePool(conn)
    with patch(
        "kerf_api.routes_admin_margin.get_pool_required",
        new=AsyncMock(return_value=pool),
    ):
        with TestClient(_APP, raise_server_exceptions=False) as c:
            yield c, conn


def _get(conn: _FakeConn, url: str, user_id: str = _ADMIN_ID, **kwargs):
    with _patched_client(conn) as (c, _):
        return c.get(url, headers=_auth(user_id), **kwargs)


# ---------------------------------------------------------------------------
# 1. RBAC guard — non-admin → 403
# ---------------------------------------------------------------------------

def test_non_admin_gets_403():
    """Regular user calling /api/admin/margin → 403."""
    conn = _FakeConn(user_account_role="user")
    r = _get(conn, f"/api/admin/margin?month={_MONTH}", user_id=_USER_ID)
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 2. RBAC guard — unauthenticated → 401
# ---------------------------------------------------------------------------

def test_unauthenticated_gets_401():
    """No auth header → 401 or 403 (FastAPI returns 403 for missing bearer)."""
    conn = _FakeConn()
    with _patched_client(conn) as (c, _):
        r = c.get(f"/api/admin/margin?month={_MONTH}")
    assert r.status_code in (401, 403), r.text


# ---------------------------------------------------------------------------
# 3. Admin with no usage data → zero totals, null break_even_seats
# ---------------------------------------------------------------------------

def test_empty_month_returns_zero_totals():
    """Admin querying a month with no events → all zeroes, break_even_seats null."""
    conn = _FakeConn(user_account_role="admin", margin_rows=[])
    r = _get(conn, f"/api/admin/margin?month={_MONTH}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["month"] == _MONTH
    totals = body["totals"]
    assert totals["revenue_usd"] == 0.0
    assert totals["cogs_usd"] == 0.0
    assert totals["gross_margin_usd"] == 0.0
    assert totals["event_count"] == 0
    assert body["by_kind"] == []
    assert body["break_even_seats"] is None
    assert body["margin_pct"] is None


# ---------------------------------------------------------------------------
# 4. Known kerf_paid events → correct revenue / COGS / margin
# ---------------------------------------------------------------------------

def test_kerf_paid_margin_arithmetic():
    """kerf_paid: revenue = usd_cost; cogs = revenue / 1.20; margin = revenue - cogs."""
    # 120 USD billed to users from token events
    # COGS = 120 / 1.20 = 100; margin = 20
    rows = [
        _margin_row(
            kind="token",
            revenue_usd=120.0,
            cogs_usd=100.0,
            gross_margin_usd=20.0,
            event_count=10,
        ),
    ]
    conn = _FakeConn(user_account_role="admin", margin_rows=rows)
    r = _get(conn, f"/api/admin/margin?month={_MONTH}")
    assert r.status_code == 200, r.text
    body = r.json()
    totals = body["totals"]
    assert abs(totals["revenue_usd"] - 120.0) < 1e-4
    assert abs(totals["cogs_usd"] - 100.0) < 1e-4
    assert abs(totals["gross_margin_usd"] - 20.0) < 1e-4
    assert totals["event_count"] == 10

    # margin_pct = 20/120 * 100 ≈ 16.67 %
    assert body["margin_pct"] is not None
    assert abs(body["margin_pct"] - 16.67) < 0.1


# ---------------------------------------------------------------------------
# 5. kerf_free events → zero revenue, negative gross margin
# ---------------------------------------------------------------------------

def test_kerf_free_zero_revenue():
    """kerf_free: Kerf absorbs COGS → revenue 0, gross_margin negative."""
    rows = [
        _margin_row(
            kind="token",
            revenue_usd=0.0,
            cogs_usd=50.0,
            gross_margin_usd=-50.0,
            event_count=5,
        ),
    ]
    conn = _FakeConn(user_account_role="admin", margin_rows=rows)
    r = _get(conn, f"/api/admin/margin?month={_MONTH}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["revenue_usd"] == 0.0
    assert abs(body["totals"]["gross_margin_usd"] - (-50.0)) < 1e-4
    # no revenue → margin_pct and break_even_seats are null
    assert body["margin_pct"] is None
    assert body["break_even_seats"] is None


# ---------------------------------------------------------------------------
# 6. Mixed payers + kinds → per-kind breakdown sums correctly
# ---------------------------------------------------------------------------

def test_multi_kind_breakdown():
    """Multiple kinds with different margins sum to correct totals."""
    rows = [
        _margin_row(kind="token",   revenue_usd=100.0, cogs_usd=83.33,  gross_margin_usd=16.67, event_count=8),
        _margin_row(kind="storage", revenue_usd=10.0,  cogs_usd=8.33,   gross_margin_usd=1.67,  event_count=2),
        _margin_row(kind="gpu",     revenue_usd=50.0,  cogs_usd=41.67,  gross_margin_usd=8.33,  event_count=3),
    ]
    conn = _FakeConn(user_account_role="admin", margin_rows=rows)
    r = _get(conn, f"/api/admin/margin?month={_MONTH}")
    assert r.status_code == 200, r.text
    body = r.json()

    # All three kinds must appear
    kinds = {k["kind"] for k in body["by_kind"]}
    assert kinds == {"token", "storage", "gpu"}

    # Totals must equal sum of by_kind values
    total_rev = sum(k["revenue_usd"] for k in body["by_kind"])
    total_cogs = sum(k["cogs_usd"] for k in body["by_kind"])
    total_margin = sum(k["gross_margin_usd"] for k in body["by_kind"])
    total_events = sum(k["event_count"] for k in body["by_kind"])

    assert abs(body["totals"]["revenue_usd"] - total_rev) < 1e-4
    assert abs(body["totals"]["cogs_usd"] - total_cogs) < 1e-4
    assert abs(body["totals"]["gross_margin_usd"] - total_margin) < 1e-4
    assert body["totals"]["event_count"] == total_events


# ---------------------------------------------------------------------------
# 7. Bad month format → 422
# ---------------------------------------------------------------------------

def test_bad_month_format_422():
    """Malformed month string returns 422."""
    for bad in ("2026", "05-2026", "not-a-date", "2026/05"):
        conn = _FakeConn(user_account_role="admin")
        r = _get(conn, f"/api/admin/margin?month={bad}")
        assert r.status_code == 422, f"Expected 422 for month={bad!r}, got {r.status_code}"


# ---------------------------------------------------------------------------
# 8. Custom fixed_cost_usd overrides the default
# ---------------------------------------------------------------------------

def test_custom_fixed_cost_override():
    """fixed_cost_usd query param overrides the default $120."""
    rows = [
        _margin_row(kind="token", revenue_usd=60.0, cogs_usd=50.0, gross_margin_usd=10.0, event_count=1),
    ]
    conn = _FakeConn(user_account_role="admin", margin_rows=rows)
    r = _get(conn, f"/api/admin/margin?month={_MONTH}&fixed_cost_usd=200")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fixed_cost_usd"] == 200.0
    assert abs(body["margin_after_fixed_usd"] - (10.0 - 200.0)) < 1e-4


# ---------------------------------------------------------------------------
# 9. break_even_seats computed correctly
# ---------------------------------------------------------------------------

def test_break_even_seats_arithmetic():
    """break_even_seats = ceil(fixed_cost / (margin_rate * studio_seat_price)).

    With revenue=120, margin=20 → margin_rate=1/6.
    Studio seat=$9 contributes $9 * 1/6 = $1.50/mo.
    To cover $120 fixed cost: ceil(120 / 1.50) = 80 seats.
    """
    rows = [
        _margin_row(kind="token", revenue_usd=120.0, cogs_usd=100.0, gross_margin_usd=20.0, event_count=10),
    ]
    conn = _FakeConn(user_account_role="admin", margin_rows=rows)
    r = _get(conn, f"/api/admin/margin?month={_MONTH}&fixed_cost_usd=120")
    assert r.status_code == 200, r.text
    body = r.json()
    # margin_rate = 20/120 = 1/6
    # revenue_needed = 120 / (1/6) = 720
    # seats = ceil(720 / 9) = 80
    assert body["break_even_seats"] == 80


# ---------------------------------------------------------------------------
# 10. margin_pct is null when revenue is zero
# ---------------------------------------------------------------------------

def test_margin_pct_null_when_no_revenue():
    """When total revenue is zero, margin_pct must be null (not divide-by-zero)."""
    rows = [
        _margin_row(kind="storage", revenue_usd=0.0, cogs_usd=5.0, gross_margin_usd=-5.0, event_count=1),
    ]
    conn = _FakeConn(user_account_role="admin", margin_rows=rows)
    r = _get(conn, f"/api/admin/margin?month={_MONTH}")
    assert r.status_code == 200, r.text
    assert r.json()["margin_pct"] is None


# ---------------------------------------------------------------------------
# 11. Default month parameter (no month supplied)
# ---------------------------------------------------------------------------

def test_default_month_uses_current():
    """Omitting ?month= should still return a 200 (uses current month)."""
    conn = _FakeConn(user_account_role="admin", margin_rows=[])
    r = _get(conn, "/api/admin/margin")
    assert r.status_code == 200, r.text
    body = r.json()
    # month key must be present and look like YYYY-MM
    assert "month" in body
    import re
    assert re.match(r"^\d{4}-\d{2}$", body["month"])


# ---------------------------------------------------------------------------
# 12. Response shape completeness
# ---------------------------------------------------------------------------

def test_response_shape():
    """All required keys are present in a successful response."""
    rows = [
        _margin_row(kind="token", revenue_usd=10.0, cogs_usd=8.33, gross_margin_usd=1.67, event_count=1),
    ]
    conn = _FakeConn(user_account_role="admin", margin_rows=rows)
    r = _get(conn, f"/api/admin/margin?month={_MONTH}")
    assert r.status_code == 200, r.text
    body = r.json()

    required_top = {"month", "fixed_cost_usd", "by_kind", "totals",
                    "margin_after_fixed_usd", "break_even_seats", "margin_pct"}
    assert required_top <= set(body.keys()), f"Missing keys: {required_top - set(body.keys())}"

    required_totals = {"revenue_usd", "cogs_usd", "gross_margin_usd", "event_count"}
    assert required_totals <= set(body["totals"].keys())

    if body["by_kind"]:
        required_kind = {"kind", "revenue_usd", "cogs_usd", "gross_margin_usd", "event_count"}
        assert required_kind <= set(body["by_kind"][0].keys())
