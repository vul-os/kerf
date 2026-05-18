"""GPU-seconds → kerf_paid credit debit meter for Cycles render jobs.

After a Cycles job completes the worker calls :func:`meter_render_job` to
convert the measured GPU wall-clock seconds into a USD cost and debit the
workspace owner's ``kerf_paid`` balance via the ``cloud_debit_balance()``
Postgres stored function.

Short-circuit paths
-------------------
* **Free/browser preview** — ``gpu_seconds == 0`` (browser WebGL fallback,
  cache hit reported as 0 s, or an explicit zero override).  No debit is
  issued and the function returns immediately with ``charged_usd=0``.

* **Self-hosted / billing disabled** — when the environment variable
  ``KERF_RENDER_BILLING_DISABLED=1`` is set (standard in the self-host
  docker image, T-106e) the function returns without touching the DB.
  This makes the worker safe to run on user-owned GPU hardware where no
  Kerf cloud account is involved.

GPU rate table
--------------
Rates are in **USD per GPU-second** (not per hour) to keep the arithmetic
straightforward.  Operators can override the defaults at import time by
mutating :data:`GPU_RATES_USD_PER_SECOND` — the dict is module-level and
looked up at call time, not at import time.

+--------+----------------------+
| model  | rate (USD / GPU-sec) |
+========+======================+
| A10G   | 0.0006               |
+--------+----------------------+
| A100   | 0.0014               |
+--------+----------------------+

Unknown GPU models fall back to the A10G rate.

Database contract
-----------------
``cloud_debit_balance(user_id UUID, amount NUMERIC)``

A *positive* ``amount`` is a debit (reduces ``credits_usd``); a negative
amount credits the balance.  The function upserts the ``cloud_user_balances``
row so it is safe to call even if no balance row exists for the user yet.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GPU rate table (USD per GPU-second)
# ---------------------------------------------------------------------------

#: Maps GPU model name (case-insensitive lookup key) to USD per GPU-second.
#: Callers may extend or override this dict before calling meter_render_job.
GPU_RATES_USD_PER_SECOND: dict[str, float] = {
    "a10g": 0.0006,
    "a100": 0.0014,
}

#: Fallback rate applied when the reported gpu_model is not in the table.
_DEFAULT_GPU_RATE: float = GPU_RATES_USD_PER_SECOND["a10g"]

# ---------------------------------------------------------------------------
# Env-var kill-switch
# ---------------------------------------------------------------------------

_BILLING_DISABLED_VAR = "KERF_RENDER_BILLING_DISABLED"


def _billing_disabled() -> bool:
    """Return True when the self-host billing kill-switch is active."""
    return os.environ.get(_BILLING_DISABLED_VAR, "").strip() == "1"


# ---------------------------------------------------------------------------
# Rate lookup
# ---------------------------------------------------------------------------

def gpu_rate(gpu_model: str) -> float:
    """Return the USD-per-GPU-second rate for *gpu_model*.

    The lookup is case-insensitive.  Unknown models fall back to the A10G
    (entry-level GPU) rate so we never under-bill an unrecognised hardware
    type by accident.
    """
    return GPU_RATES_USD_PER_SECOND.get(gpu_model.lower(), _DEFAULT_GPU_RATE)


def compute_usd_cost(gpu_seconds: float, gpu_model: str) -> float:
    """Return the USD cost for *gpu_seconds* on *gpu_model*.

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
    gpu_model: str = "a10g",
    *,
    job_id: Optional[str] = None,
) -> dict:
    """Debit the workspace owner's kerf_paid balance for a completed render.

    Parameters
    ----------
    pool:
        asyncpg connection pool (or any object exposing ``acquire()`` as an
        async context manager that yields a connection with ``execute()``).
        May be ``None`` when ``gpu_seconds == 0`` or billing is disabled,
        in which case no DB calls are made.
    workspace_id:
        The UUID of the workspace that owns the render job.  Used as the
        ``user_id`` argument to ``cloud_debit_balance()``.
    gpu_seconds:
        Measured GPU wall-clock seconds as reported by the cycles_worker.
        Pass ``0`` for cache hits or browser-fallback renders (free path).
    gpu_model:
        GPU hardware identifier (e.g. ``"A10G"``, ``"A100"``).
        Case-insensitive; unknown values fall back to the A10G rate.
    job_id:
        Optional render job UUID for logging / traceability.  Not written
        to the DB by this function (that is handled by the caller or
        ``kerf_billing.render_meter``).

    Returns
    -------
    dict with keys:
        ``charged_usd``  float — actual USD debited (0 if skipped)
        ``skipped``      bool  — True when no debit was issued
        ``skip_reason``  str | None — ``"zero_gpu_seconds"``,
                         ``"billing_disabled"``, or ``None``
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

    # ── Short-circuit: self-hosted / billing disabled ────────────────────────
    if _billing_disabled():
        logger.debug(
            "%smeter_render_job: skip (%s=1)", tag, _BILLING_DISABLED_VAR
        )
        return {
            "charged_usd": 0.0,
            "skipped": True,
            "skip_reason": "billing_disabled",
        }

    # ── Compute cost ─────────────────────────────────────────────────────────
    cost_usd = compute_usd_cost(gpu_seconds, gpu_model)

    # ── Debit via cloud_debit_balance() ──────────────────────────────────────
    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT cloud_debit_balance($1, $2)",
            workspace_id,
            cost_usd,
        )

    logger.info(
        "%smeter_render_job: charged workspace=%s gpu_model=%s "
        "gpu_seconds=%.2f charged_usd=%.6f",
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


__all__ = [
    "GPU_RATES_USD_PER_SECOND",
    "gpu_rate",
    "compute_usd_cost",
    "meter_render_job",
]
