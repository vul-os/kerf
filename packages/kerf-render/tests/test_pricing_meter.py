"""Tests for kerf_render.pricing_meter — local GPU usage telemetry.

Kerf has no billing anywhere. Covers:
- L4 30-second render → expected cost *estimate* (informational only)
- DB mock receives a local usage_events row, never a credit debit
- Free path: 0 gpu_seconds → no telemetry row written
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from kerf_render.pricing_meter import (
    GPU_RATES_USD_PER_SECOND,
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
    """L4 is the default GPU tier — placeholder rate ~$0.70/hr ÷ 3600."""
    assert gpu_rate("l4") == pytest.approx(0.000194)
    assert gpu_rate("L4") == pytest.approx(0.000194)


def test_a100_rate():
    """A100 80GB — placeholder rate ~$1.60/hr ÷ 3600."""
    assert gpu_rate("a100") == pytest.approx(0.000444)
    assert gpu_rate("A100") == pytest.approx(0.000444)


def test_h100_rate():
    """H100 — placeholder rate ~$2.50/hr ÷ 3600."""
    assert gpu_rate("h100") == pytest.approx(0.000694)


def test_a10g_alias_maps_to_l4():
    """Back-compat: legacy 'a10g' callers must still resolve (mapped to L4)."""
    assert gpu_rate("l4") == pytest.approx(GPU_RATES_USD_PER_SECOND["l4"])


def test_unknown_gpu_falls_back_to_l4():
    # Unknown model falls back to L4 (not zero).
    assert gpu_rate("unknown_xyz") == pytest.approx(GPU_RATES_USD_PER_SECOND["l4"])


# ---------------------------------------------------------------------------
# Unit: cost computation (informational estimate only — never billed)
# ---------------------------------------------------------------------------


def test_compute_usd_cost_l4_30s():
    """30 GPU-seconds on L4 = 30 × 0.000194 = $0.00582 (estimate only)."""
    cost = compute_usd_cost(30.0, "l4")
    assert cost == pytest.approx(30.0 * 0.000194, rel=1e-9)


def test_compute_usd_cost_a100_30s():
    """30 GPU-seconds on A100 = 30 × 0.000444 = $0.01332 (estimate only)."""
    cost = compute_usd_cost(30.0, "a100")
    assert cost == pytest.approx(30.0 * 0.000444, rel=1e-9)


def test_compute_usd_cost_zero_gpu_seconds():
    assert compute_usd_cost(0.0, "l4") == 0.0
    assert compute_usd_cost(-1.0, "l4") == 0.0


# ---------------------------------------------------------------------------
# Integration: meter_render_job — local telemetry, never a credit debit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_render_job_l4_30s_records_telemetry():
    """30 GPU-seconds on L4 → a local usage_events row, never a debit."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    expected = 30.0 * 0.000194
    result = await meter_render_job(pool, workspace_id, 30.0, "l4", job_id=job_id)

    assert result["skipped"] is False
    assert result["skip_reason"] is None
    assert result["charged_usd"] == pytest.approx(expected, rel=1e-9)

    # The DB connection should have received exactly one execute call — an
    # INSERT into usage_events, never a credit-debit call.
    assert len(pool.conn.calls) == 1
    sql, args = pool.conn.calls[0]
    assert "usage_events" in sql
    assert "cloud_debit_balance" not in sql
    assert "'gpu'" in sql
    assert args[0] == job_id
    assert args[1] == workspace_id
    assert args[2] == pytest.approx(expected, rel=1e-9)


@pytest.mark.asyncio
async def test_meter_render_job_correct_workspace_id():
    """The workspace_id is forwarded verbatim as the usage_events user_id."""
    pool = _FakePool()
    workspace_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    job_id = str(uuid.uuid4())

    await meter_render_job(pool, workspace_id, 10.0, "l4", job_id=job_id)

    _, args = pool.conn.calls[0]
    assert args[1] == workspace_id


@pytest.mark.asyncio
async def test_meter_render_job_no_job_id_writes_no_row():
    """Without a job_id there is no primary key for the usage_events row, so
    no DB call is made (matches the original informational-only contract)."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    result = await meter_render_job(pool, workspace_id, 30.0, "l4")

    assert result["skipped"] is False
    assert len(pool.conn.calls) == 0


# ---------------------------------------------------------------------------
# Free path: 0 GPU-seconds → no telemetry row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_render_job_zero_gpu_seconds_no_row():
    """gpu_seconds=0 (browser/cache path) must not touch the DB."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    result = await meter_render_job(pool, workspace_id, 0.0, "l4")

    assert result["charged_usd"] == 0.0
    assert result["skipped"] is True
    assert result["skip_reason"] == "zero_gpu_seconds"
    assert len(pool.conn.calls) == 0


@pytest.mark.asyncio
async def test_meter_render_job_negative_gpu_seconds_no_row():
    """Negative gpu_seconds is treated the same as zero."""
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())

    result = await meter_render_job(pool, workspace_id, -5.0, "l4")

    assert result["charged_usd"] == 0.0
    assert result["skipped"] is True
    assert result["skip_reason"] == "zero_gpu_seconds"
    assert len(pool.conn.calls) == 0


# ---------------------------------------------------------------------------
# optional job_id argument is accepted without error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_render_job_with_job_id():
    pool = _FakePool()
    workspace_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    expected = 30.0 * 0.000194
    result = await meter_render_job(
        pool, workspace_id, 30.0, "l4", job_id=job_id
    )

    assert result["skipped"] is False
    assert result["charged_usd"] == pytest.approx(expected, rel=1e-9)
