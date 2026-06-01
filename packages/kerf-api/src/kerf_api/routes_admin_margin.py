"""T-408 — Break-even margin admin endpoint.

GET /api/admin/margin?month=YYYY-MM

Returns the realised gross margin for a given calendar month from the
``monthly_margin`` view (defined in 0008_billing.sql), along with a
configurable fixed-cost input and the resulting break-even seat count.

Auth: account_role must be 'admin' or 'system' (same guard used by every
other admin route in routes.py).

Environment:
    KERF_FIXED_COST_USD  Monthly fixed infrastructure cost in USD.
                         Defaults to 50 (Fly.io shared-cpu-2x + Neon free tier).
                         Override via env var as infrastructure costs change.
"""
from __future__ import annotations

import os
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from kerf_core.db.connection import get_pool_required
from kerf_core.dependencies import require_auth

router = APIRouter()

# ---------------------------------------------------------------------------
# Fixed-cost default (Fly.io shared-cpu-2x + Neon free tier ≈ $50/mo)
# Override via KERF_FIXED_COST_USD env var. GPU rendering is CPU-only on Fly
# today; update this default when RunPod/Modal GPU spend is confirmed.
# ---------------------------------------------------------------------------
_DEFAULT_FIXED_COST_USD = 50.0


def _fixed_cost() -> float:
    raw = os.environ.get("KERF_FIXED_COST_USD", "")
    try:
        return float(raw)
    except (ValueError, TypeError):
        return _DEFAULT_FIXED_COST_USD


# ---------------------------------------------------------------------------
# Admin guard — mirrors the inline checks in routes.py admin routes
# ---------------------------------------------------------------------------

async def _require_admin(request: Request, payload: dict = Depends(require_auth)) -> str:
    """Return user_id if the caller has account_role 'admin' or 'system'.

    Raises 401 if unauthenticated, 403 if not admin/system.
    """
    uid = payload.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT account_role FROM users WHERE id = $1",
            uuid.UUID(uid),
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    if row["account_role"] not in ("admin", "system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
    return uid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_month_str() -> str:
    today = date.today()
    return today.strftime("%Y-%m")


def _parse_month(month_str: str) -> date:
    """Parse 'YYYY-MM' into a ``date`` object (first day of the month)."""
    try:
        parts = month_str.split("-")
        if len(parts) != 2:
            raise ValueError
        year, mon = int(parts[0]), int(parts[1])
        return date(year, mon, 1)
    except (ValueError, OverflowError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid month format '{month_str}'; expected YYYY-MM.",
        )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/admin/margin")
async def get_margin(
    month: Optional[str] = Query(
        default=None,
        description="Calendar month to query, e.g. '2026-05'. Defaults to the current month.",
        examples={"default": {"value": "2026-05"}},
    ),
    fixed_cost_usd: Optional[float] = Query(
        default=None,
        description=(
            "Override the monthly fixed infrastructure cost (USD). "
            "Falls back to the KERF_FIXED_COST_USD env var, then ~$120."
        ),
        gt=0,
    ),
    uid: str = Depends(_require_admin),
):
    """Return gross-margin breakdown for a calendar month.

    Response shape::

        {
          "month": "2026-05",
          "fixed_cost_usd": 120.0,
          "by_kind": [
            {
              "kind": "token",
              "revenue_usd": 45.23,
              "cogs_usd": 37.69,
              "gross_margin_usd": 7.54,
              "event_count": 1234
            },
            ...
          ],
          "totals": {
            "revenue_usd": 52.10,
            "cogs_usd": 43.41,
            "gross_margin_usd": 8.69,
            "event_count": 1410
          },
          "break_even_seats": 14,
          "margin_after_fixed_usd": -111.31,
          "margin_pct": 16.68
        }

    ``break_even_seats`` is the number of $9/mo Studio seats (the entry
    paid tier) needed to cover the fixed cost at the realised margin rate.
    When total revenue is zero the field is ``null``.
    """
    month_str = month or _current_month_str()
    month_date = _parse_month(month_str)
    fc = fixed_cost_usd if fixed_cost_usd is not None else _fixed_cost()

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT kind,
                   revenue_usd,
                   cogs_usd,
                   gross_margin_usd,
                   event_count
            FROM   monthly_margin
            WHERE  month = $1
            ORDER  BY kind
            """,
            month_date,
        )

    by_kind = [
        {
            "kind": r["kind"],
            "revenue_usd": float(r["revenue_usd"]),
            "cogs_usd": float(r["cogs_usd"]),
            "gross_margin_usd": float(r["gross_margin_usd"]),
            "event_count": r["event_count"],
        }
        for r in rows
    ]

    total_revenue = sum(k["revenue_usd"] for k in by_kind)
    total_cogs = sum(k["cogs_usd"] for k in by_kind)
    total_margin = sum(k["gross_margin_usd"] for k in by_kind)
    total_events = sum(k["event_count"] for k in by_kind)

    margin_after_fixed = total_margin - fc

    # Margin percentage (gross margin / revenue * 100), or null when no revenue
    margin_pct: Optional[float] = (
        round(total_margin / total_revenue * 100, 2) if total_revenue else None
    )

    # Break-even seats: how many $9 Studio seats cover the fixed cost?
    # Each seat contributes (seat_price * margin_rate) per month.
    # We use the realised margin rate; if unknown (no revenue) return null.
    break_even_seats: Optional[int] = None
    if total_revenue and total_margin > 0:
        # margin per dollar of revenue
        margin_rate = total_margin / total_revenue
        # revenue needed to cover fixed cost
        revenue_needed = fc / margin_rate
        # seats at $9 each
        studio_seat_price = 9.0
        break_even_seats = int(-(-revenue_needed // studio_seat_price))  # ceiling div

    return {
        "month": month_str,
        "fixed_cost_usd": fc,
        "by_kind": by_kind,
        "totals": {
            "revenue_usd": round(total_revenue, 6),
            "cogs_usd": round(total_cogs, 6),
            "gross_margin_usd": round(total_margin, 6),
            "event_count": total_events,
        },
        "margin_after_fixed_usd": round(margin_after_fixed, 6),
        "break_even_seats": break_even_seats,
        "margin_pct": margin_pct,
    }
