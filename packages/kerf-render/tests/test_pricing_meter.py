"""Tests for kerf_render.pricing_meter (T-106d).

Covers:
- A10G 30-second render → expected USD cost
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


def test_a10g_rate():
    assert gpu_rate("a10g") == pytest.approx(0.0006)
    assert gpu_rate("A10G") == pytest.approx(0.0006)


def test_a100_rate():
    assert gpu_rate("a100") == pytest.approx(0.0014)
    assert gpu_rate("A100") == pytest.approx(0.0014)


def test_unknown_gpu_falls_back_to_a10g():
    # Unknown model falls back to A10G (not zero — we must not under-bill).
    assert gpu_rate("H100") == pytest.approx(GPU_RATES_USD_PER_SECOND["a10g"])


# ---------------------------------------------------------------------------
# Unit: cost computation
# ---------------------------------------------------------------------------


def test_compute_usd_cost_a10g_30s_no_markup():
    """30 GPU-seconds on A10G at zero markup = bare COGS $0.018."""
    cost = compute_usd_cost(30.0, "a10g", markup_pct=0)
    assert cost == pytest.approx(0.018, rel=1e-9)


def test_compute_usd_cost_a100_30s_no_markup():
    """30 GPU-seconds on A100 at zero markup = bare COGS $0.042."""
    cost = compute_usd_cost(30.0, "a100", markup_pct=0)
    assert cost == pytest.approx(0.042, rel=1e-9)


def test_compute_usd_cost_applies_markup():
    """Default 20% markup: 30s A10G → 0.018 × 1.20 = $0.0216."""
    cost = compute_usd_cost(30.0, "a10g")
    assert cost == pytest.approx(0.018 * (1 + GPU_MARKUP_PCT / 100), rel=1e-9)


def test_compute_usd_cost_explicit_markup():
    """Explicit markup_pct=20 gives same result as the default."""
    assert compute_usd_cost(30.0, "a10g", markup_pct=20) == pytest.approx(
        compute_usd_cost(30.0, "a10g"), rel=1e-9
    )


def test_compute_usd_cost_zero_gpu_seconds():
    assert compute_usd_cost(0.0, "a10g") == 0.0
    assert compute_usd_cost(-1.0, "a10g") == 0.0


# ---------------------------------------------------------------------------
# Integration: meter_render_job — normal paid path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_render_job_a10g_30s_debits_correctly():
    """30 GPU-seconds on A10G → COGS × 1.20 charged; DB execute called once."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    expected = 0.018 * (1 + GPU_MARKUP_PCT / 100)  # 0.0216 at 20%
    result = await meter_render_job(pool, workspace_id, 30.0, "a10g")

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

    await meter_render_job(pool, workspace_id, 10.0, "a10g")

    _, args = pool.conn.calls[0]
    assert args[0] == workspace_id


@pytest.mark.asyncio
async def test_meter_render_job_writes_positive_debit():
    """cloud_debit_balance is called with a *positive* amount (debit convention)."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    await meter_render_job(pool, workspace_id, 60.0, "a10g")

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

    result = await meter_render_job(pool, workspace_id, 0.0, "a10g")

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

    result = await meter_render_job(pool, workspace_id, -5.0, "a10g")

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

    result = await meter_render_job(pool, workspace_id, 30.0, "a10g")

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

    expected = 0.018 * (1 + GPU_MARKUP_PCT / 100)
    result = await meter_render_job(pool, workspace_id, 30.0, "a10g")

    assert result["skipped"] is False
    assert result["charged_usd"] == pytest.approx(expected, rel=1e-9)
    assert len(pool.conn.calls) == 1


@pytest.mark.asyncio
async def test_meter_render_job_billing_disabled_other_value(monkeypatch):
    """KERF_RENDER_BILLING_DISABLED=0 does NOT suppress billing."""
    monkeypatch.setenv("KERF_RENDER_BILLING_DISABLED", "0")

    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    result = await meter_render_job(pool, workspace_id, 30.0, "a10g")

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

    expected = 0.018 * (1 + GPU_MARKUP_PCT / 100)
    result = await meter_render_job(
        pool, workspace_id, 30.0, "a10g", job_id=job_id
    )

    assert result["skipped"] is False
    assert result["charged_usd"] == pytest.approx(expected, rel=1e-9)
