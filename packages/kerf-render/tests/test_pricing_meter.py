"""Tests for kerf_render.pricing_meter (T-106d).

Covers:
- L4 30-second render → expected USD cost (Koyeb-grounded, 35% markup)
- DB mock receives the correct workspace_id and amount
- Free path: 0 gpu_seconds → no debit
- Self-hosted path: KERF_RENDER_BILLING_DISABLED=1 → no debit
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kerf_render.pricing_meter import (
    GPU_RATES_USD_PER_SECOND,
    GPU_MARKUP_PCT,
    compute_usd_cost,
    gpu_rate,
    meter_render_job,
)


# ---------------------------------------------------------------------------
# Minimal fake asyncpg pool
# ---------------------------------------------------------------------------

class _FakeConn:
    """Records calls to execute() so tests can inspect them."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args: Any) -> None:
        self.calls.append((sql, args))


class _FakePool:
    """asyncpg pool stub: acquire() yields a _FakeConn."""

    def __init__(self):
        self.conn = _FakeConn()

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


# ---------------------------------------------------------------------------
# Unit: rate table
# ---------------------------------------------------------------------------


def test_l4_rate():
    """L4 is the default Koyeb tier — grounded to $0.70/hr ÷ 3600."""
    assert gpu_rate("l4") == pytest.approx(0.000194)
    assert gpu_rate("L4") == pytest.approx(0.000194)


def test_a100_rate():
    """A100 80GB on Koyeb — $1.60/hr ÷ 3600."""
    assert gpu_rate("a100") == pytest.approx(0.000444)
    assert gpu_rate("A100") == pytest.approx(0.000444)


def test_h100_rate():
    """H100 on Koyeb — $2.50/hr ÷ 3600."""
    assert gpu_rate("h100") == pytest.approx(0.000694)


def test_a10g_alias_maps_to_l4():
    """Back-compat: legacy 'a10g' callers must still resolve (mapped to L4)."""
    assert gpu_rate("l4") == pytest.approx(GPU_RATES_USD_PER_SECOND["l4"])


def test_unknown_gpu_falls_back_to_l4():
    # Unknown model falls back to L4 (not zero — we must not under-bill).
    assert gpu_rate("unknown_xyz") == pytest.approx(GPU_RATES_USD_PER_SECOND["l4"])


# ---------------------------------------------------------------------------
# Unit: cost computation
# ---------------------------------------------------------------------------


def test_compute_usd_cost_l4_30s_no_markup():
    """30 GPU-seconds on L4 at zero markup = bare COGS 30 × 0.000194 = $0.00582."""
    cost = compute_usd_cost(30.0, "l4", markup_pct=0)
    assert cost == pytest.approx(30.0 * 0.000194, rel=1e-9)


def test_compute_usd_cost_a100_30s_no_markup():
    """30 GPU-seconds on A100 at zero markup = 30 × 0.000444 = $0.01332."""
    cost = compute_usd_cost(30.0, "a100", markup_pct=0)
    assert cost == pytest.approx(30.0 * 0.000444, rel=1e-9)


def test_compute_usd_cost_applies_markup():
    """Default 35% markup applied to L4 30s."""
    expected = 30.0 * 0.000194 * (1 + GPU_MARKUP_PCT / 100)
    assert compute_usd_cost(30.0, "l4") == pytest.approx(expected, rel=1e-9)


def test_compute_usd_cost_default_markup_is_35():
    """Post-Koyeb migration: default markup is 35%."""
    assert GPU_MARKUP_PCT == pytest.approx(35.0)


def test_compute_usd_cost_explicit_markup_matches_default():
    """Explicit markup_pct=GPU_MARKUP_PCT gives same result as the default."""
    assert compute_usd_cost(30.0, "l4", markup_pct=GPU_MARKUP_PCT) == pytest.approx(
        compute_usd_cost(30.0, "l4"), rel=1e-9
    )


def test_compute_usd_cost_zero_gpu_seconds():
    assert compute_usd_cost(0.0, "l4") == 0.0
    assert compute_usd_cost(-1.0, "l4") == 0.0


# ---------------------------------------------------------------------------
# Integration: meter_render_job — normal paid path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_render_job_l4_30s_debits_correctly():
    """30 GPU-seconds on L4 → COGS × (1+markup) charged; DB execute called once."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    expected = 30.0 * 0.000194 * (1 + GPU_MARKUP_PCT / 100)
    result = await meter_render_job(pool, workspace_id, 30.0, "l4")

    assert result["skipped"] is False
    assert result["skip_reason"] is None
    assert result["charged_usd"] == pytest.approx(expected, rel=1e-9)

    # The DB connection should have received exactly one execute call.
    assert len(pool.conn.calls) == 1
    sql, args = pool.conn.calls[0]
    assert "cloud_debit_balance" in sql
    assert args[0] == workspace_id
    assert args[1] == pytest.approx(expected, rel=1e-9)


@pytest.mark.asyncio
async def test_meter_render_job_correct_workspace_id():
    """The workspace_id is forwarded verbatim as the first DB argument."""
    pool = _FakePool()
    workspace_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    await meter_render_job(pool, workspace_id, 10.0, "l4")

    _, args = pool.conn.calls[0]
    assert args[0] == workspace_id


@pytest.mark.asyncio
async def test_meter_render_job_writes_positive_debit():
    """cloud_debit_balance is called with a *positive* amount (debit convention)."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    await meter_render_job(pool, workspace_id, 60.0, "l4")

    _, args = pool.conn.calls[0]
    assert args[1] > 0, "debit amount must be positive"


# ---------------------------------------------------------------------------
# Free path: 0 GPU-seconds → no debit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_render_job_zero_gpu_seconds_no_debit():
    """gpu_seconds=0 (browser/cache path) must not touch the DB."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    result = await meter_render_job(pool, workspace_id, 0.0, "l4")

    assert result["charged_usd"] == 0.0
    assert result["skipped"] is True
    assert result["skip_reason"] == "zero_gpu_seconds"
    # No DB calls should have been made.
    assert len(pool.conn.calls) == 0


@pytest.mark.asyncio
async def test_meter_render_job_negative_gpu_seconds_no_debit():
    """Negative gpu_seconds is treated the same as zero."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    result = await meter_render_job(pool, workspace_id, -5.0, "l4")

    assert result["charged_usd"] == 0.0
    assert result["skipped"] is True
    assert result["skip_reason"] == "zero_gpu_seconds"
    assert len(pool.conn.calls) == 0


# ---------------------------------------------------------------------------
# Self-hosted path: KERF_RENDER_BILLING_DISABLED=1 → no debit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_render_job_billing_disabled_env_var(monkeypatch):
    """KERF_RENDER_BILLING_DISABLED=1 suppresses billing entirely."""
    monkeypatch.setenv("KERF_RENDER_BILLING_DISABLED", "1")

    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    result = await meter_render_job(pool, workspace_id, 30.0, "l4")

    assert result["charged_usd"] == 0.0
    assert result["skipped"] is True
    assert result["skip_reason"] == "billing_disabled"
    assert len(pool.conn.calls) == 0


@pytest.mark.asyncio
async def test_meter_render_job_billing_disabled_not_set(monkeypatch):
    """Without KERF_RENDER_BILLING_DISABLED the paid path executes normally."""
    monkeypatch.delenv("KERF_RENDER_BILLING_DISABLED", raising=False)

    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    expected = 30.0 * 0.000194 * (1 + GPU_MARKUP_PCT / 100)
    result = await meter_render_job(pool, workspace_id, 30.0, "l4")

    assert result["skipped"] is False
    assert result["charged_usd"] == pytest.approx(expected, rel=1e-9)
    assert len(pool.conn.calls) == 1


@pytest.mark.asyncio
async def test_meter_render_job_billing_disabled_other_value(monkeypatch):
    """KERF_RENDER_BILLING_DISABLED=0 does NOT suppress billing."""
    monkeypatch.setenv("KERF_RENDER_BILLING_DISABLED", "0")

    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    result = await meter_render_job(pool, workspace_id, 30.0, "l4")

    assert result["skipped"] is False
    assert len(pool.conn.calls) == 1


# ---------------------------------------------------------------------------
# optional job_id argument is accepted without error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_render_job_with_job_id():
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    expected = 30.0 * 0.000194 * (1 + GPU_MARKUP_PCT / 100)
    result = await meter_render_job(
        pool, workspace_id, 30.0, "l4", job_id=job_id
    )

    assert result["skipped"] is False
    assert result["charged_usd"] == pytest.approx(expected, rel=1e-9)
