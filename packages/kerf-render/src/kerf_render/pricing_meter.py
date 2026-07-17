"""GPU-seconds → local usage telemetry for Cycles render jobs.

Kerf has no billing anywhere. After a Cycles job completes the worker calls
:func:`meter_render_job` to record the measured GPU wall-clock seconds (and
an informational cost estimate) as a local ``usage_events`` row — a box
owner's own record of what a render job consumed, not a credit charge. No
balance is debited and no network call is made.

Short-circuit path
-------------------
* **Free/browser preview** — ``gpu_seconds == 0`` (browser WebGL fallback,
  cache hit reported as 0 s, or an explicit zero override).  No telemetry
  row is written and the function returns immediately with
  ``charged_usd=0``.

GPU rate table
--------------
Rates are in **USD per GPU-second** (not per hour) to keep the arithmetic
straightforward, purely for the informational cost estimate recorded in
local telemetry (never billed to anyone). Operators can override the
defaults at import time by mutating :data:`GPU_RATES_USD_PER_SECOND` — the
dict is module-level and looked up at call time, not at import time.

.. note::
   **GPU pricing is a placeholder.**  These rates are representative market
   rates for common GPU SKUs, used only to estimate a "this render would
   have cost about $X on rented hardware" figure for the owner's own
   dashboard; treat them as estimates.

+----------------+-------+--------------------+------------------------------+
| model key      | VRAM  | est. $/hr (market) | est. rate (USD / GPU-second) |
+================+=======+====================+==============================+
| rtx_a4000      | 20 GB | ~0.50              | 0.000139                     |
| l4 (default)   | 24 GB | ~0.70              | 0.000194                     |
| a6000          | 48 GB | ~0.75              | 0.000208                     |
| l40s           | 48 GB | ~1.20              | 0.000333                     |
| a100           | 80 GB | ~1.60              | 0.000444                     |
| a100_sxm       | 80 GB | ~2.15              | 0.000597                     |
| rtx_pro_6000   | 96 GB | ~2.20              | 0.000611                     |
| h100           | 80 GB | ~2.50              | 0.000694                     |
| h200           |141 GB | ~3.00              | 0.000833                     |
+----------------+-------+--------------------+------------------------------+

Unknown GPU models fall back to the L4 rate.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GPU rate table (USD per GPU-second) — placeholder rates based on market
# estimates for common GPU SKUs (rate = hourly $ / 3600). Used only for the
# informational cost estimate in local telemetry — never billed.
# ---------------------------------------------------------------------------

#: Maps GPU model name (case-insensitive lookup key) to USD per GPU-second.
#: Callers may extend or override this dict before calling meter_render_job.
GPU_RATES_USD_PER_SECOND: dict[str, float] = {
    "rtx_a4000":    0.000139,  # 20 GB,  ~$0.50/hr — entry
    "l4":           0.000194,  # 24 GB,  ~$0.70/hr — default
    "a6000":        0.000208,  # 48 GB,  ~$0.75/hr
    "l40s":         0.000333,  # 48 GB,  ~$1.20/hr
    "a100":         0.000444,  # 80 GB,  ~$1.60/hr
    "a100_sxm":     0.000597,  # 80 GB,  ~$2.15/hr — SXM interconnect
    "rtx_pro_6000": 0.000611,  # 96 GB,  ~$2.20/hr
    "h100":         0.000694,  # 80 GB,  ~$2.50/hr
    "h200":         0.000833,  # 141 GB, ~$3.00/hr — top
    # Back-compat aliases for legacy keys. Map to closest tier.
    "a10g":         0.000194,  # → l4 (24 GB, same tier)
}

#: Fallback rate applied when the reported gpu_model is not in the table.
#: L4 — the default SKU used by the Cycles dispatch policy.
_DEFAULT_GPU_RATE: float = GPU_RATES_USD_PER_SECOND["l4"]


# ---------------------------------------------------------------------------
# Rate lookup
# ---------------------------------------------------------------------------

def gpu_rate(gpu_model: str) -> float:
    """Return the USD-per-GPU-second estimate rate for *gpu_model*.

    The lookup is case-insensitive.  Unknown models fall back to the L4
    (default GPU tier) rate.
    """
    return GPU_RATES_USD_PER_SECOND.get(gpu_model.lower(), _DEFAULT_GPU_RATE)


def compute_usd_cost(gpu_seconds: float, gpu_model: str) -> float:
    """Return the informational USD cost estimate for *gpu_seconds* on
    *gpu_model*. Never billed to anyone — purely a local telemetry figure.

    Returns ``0.0`` when ``gpu_seconds <= 0`` (free / browser path).
    """
    if gpu_seconds <= 0:
        return 0.0
    return gpu_seconds * gpu_rate(gpu_model)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def meter_render_job(
    pool,
    workspace_id: str,
    gpu_seconds: float,
    gpu_model: str = "l4",
    *,
    job_id: Optional[str] = None,
) -> dict:
    """Record a local usage_events row for a completed render — no billing.

    Parameters
    ----------
    pool:
        asyncpg connection pool (or any object exposing ``acquire()`` as an
        async context manager that yields a connection with ``execute()``).
        May be ``None`` when ``gpu_seconds == 0``, in which case no DB calls
        are made.
    workspace_id:
        The UUID of the workspace that owns the render job. Recorded as the
        ``user_id`` on the local usage_events row.
    gpu_seconds:
        Measured GPU wall-clock seconds as reported by the cycles_worker.
        Pass ``0`` for cache hits or browser-fallback renders (free path).
    gpu_model:
        GPU hardware identifier (e.g. ``"l4"``, ``"a100"``).
        Case-insensitive; unknown values fall back to the L4 rate.
    job_id:
        Optional render job UUID for logging / traceability. Also used as
        the primary key when writing the ``usage_events`` row.

    Returns
    -------
    dict with keys:
        ``charged_usd``  float — informational cost estimate (always 0 if
                          skipped; never actually charged to anyone)
        ``skipped``      bool  — True when no telemetry row was written
        ``skip_reason``  str | None — ``"zero_gpu_seconds"`` or ``None``
    """
    tag = f"[job={job_id}] " if job_id else ""

    # ── Short-circuit: free / browser preview ───────────────────────────────
    if gpu_seconds <= 0:
        logger.debug("%smeter_render_job: skip (zero gpu_seconds)", tag)
        return {
            "charged_usd": 0.0,
            "skipped": True,
            "skip_reason": "zero_gpu_seconds",
        }

    # ── Compute informational cost estimate (never billed) ──────────────────
    cost_usd = compute_usd_cost(gpu_seconds, gpu_model)

    # ── Local usage telemetry — a kind='gpu' usage_events row ───────────────
    if job_id and pool is not None:
        await _record_gpu_usage_event(pool, workspace_id, job_id, gpu_seconds, cost_usd)

    logger.info(
        "%smeter_render_job: recorded workspace=%s gpu_model=%s "
        "gpu_seconds=%.2f est_usd=%.6f",
        tag,
        workspace_id,
        gpu_model,
        gpu_seconds,
        cost_usd,
    )

    return {
        "charged_usd": cost_usd,
        "skipped": False,
        "skip_reason": None,
    }


async def _record_gpu_usage_event(
    pool,
    user_id: str,
    job_id: str,
    gpu_seconds: float,
    usd_cost: float,
) -> None:
    """Append a kind='gpu' row to usage_events (best-effort, fire-and-forget).

    Local telemetry only — a box owner's own record of GPU render usage.
    No credits, no balance, no network call.
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO usage_events
                    (id, user_id, kind, usd_cost, payer)
                VALUES ($1, $2, 'gpu', $3, 'byo')
                ON CONFLICT (id) DO NOTHING
                """,
                job_id,
                user_id,
                usd_cost,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("pricing_meter: failed to record gpu usage_event: %s", exc)


__all__ = [
    "GPU_RATES_USD_PER_SECOND",
    "gpu_rate",
    "compute_usd_cost",
    "meter_render_job",
]
