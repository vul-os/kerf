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

.. note::
   **GPU pricing is a placeholder.**  Current Fly.io-only deploys use
   CPU rendering on the app server (no GPU spend).  These rates will be
   re-grounded to live RunPod Serverless or Modal pricing once a GPU
   backend is integrated (see ``kerf_render.dispatch`` for the dispatch
   seam and ``kerf_workers.compute_backend`` for the backend interface).
   The table below uses representative market rates for common GPU SKUs;
   treat them as estimates until the backend is confirmed.

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

Unknown GPU models fall back to the L4 rate — the entry-level SKU that
serves as the default for Cycles render dispatch.

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
# GPU markup — mirrors cloud_pricing_token_markup_pct in Settings.
# When non-zero, the billed amount = COGS × (1 + markup/100).
# Overridable at runtime by mutating this module-level variable or by
# passing markup_pct= explicitly to compute_usd_cost / meter_render_job.
# ---------------------------------------------------------------------------

#: Default GPU markup percentage (mirrors cloud_pricing_token_markup_pct).
#: Operators may override this after import; the value is read at call time.
#: TODO: re-calibrate once RunPod/Modal backend is live and per-second billing
#: variance is known. 35% is a conservative placeholder that absorbs storage
#: egress, autoscale buffer, and operational overhead.
GPU_MARKUP_PCT: float = 35.0

# ---------------------------------------------------------------------------
# GPU rate table (USD per GPU-second) — placeholder rates based on market
# estimates for common GPU SKUs (rate = hourly $ / 3600).
#
# TODO: ground these to live RunPod Serverless or Modal pricing once the
# GPU backend is integrated. See kerf_render.dispatch for the dispatch seam.
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

    The lookup is case-insensitive.  Unknown models fall back to the L4
    (default GPU tier) rate so we never under-bill an unrecognised
    hardware type by accident.
    """
    return GPU_RATES_USD_PER_SECOND.get(gpu_model.lower(), _DEFAULT_GPU_RATE)


def compute_usd_cost(
    gpu_seconds: float,
    gpu_model: str,
    *,
    markup_pct: Optional[float] = None,
) -> float:
    """Return the billed USD cost for *gpu_seconds* on *gpu_model*.

    The billed amount is COGS × (1 + markup/100).  When *markup_pct* is
    ``None`` the module-level :data:`GPU_MARKUP_PCT` is used (default 35%).
    Pass ``markup_pct=0`` to get the bare COGS figure.

    Returns ``0.0`` when ``gpu_seconds <= 0`` (free / browser path).
    """
    if gpu_seconds <= 0:
        return 0.0
    cogs = gpu_seconds * gpu_rate(gpu_model)
    pct = markup_pct if markup_pct is not None else GPU_MARKUP_PCT
    return cogs * (1.0 + pct / 100.0)


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
    markup_pct: Optional[float] = None,
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
        GPU hardware identifier (e.g. ``"l4"``, ``"a100"``).
        Case-insensitive; unknown values fall back to the L4 rate.
    job_id:
        Optional render job UUID for logging / traceability.  Also used as
        the primary key when writing a ``usage_events`` row.
    markup_pct:
        GPU markup percentage to apply on top of COGS.  ``None`` uses the
        module-level :data:`GPU_MARKUP_PCT` (default 35%).  Pass ``0`` to
        charge bare COGS (useful for BYO / test scenarios).

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

    # ── Compute cost (COGS × (1 + markup)) ───────────────────────────────────
    cost_usd = compute_usd_cost(gpu_seconds, gpu_model, markup_pct=markup_pct)

    # ── Debit via cloud_debit_balance() ──────────────────────────────────────
    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT cloud_debit_balance($1, $2)",
            workspace_id,
            cost_usd,
        )

    # ── Emit gpu usage_events row (makes GPU spend visible on ledger) ─────────
    if job_id and pool is not None:
        await _record_gpu_usage_event(pool, workspace_id, job_id, gpu_seconds, cost_usd)

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


async def _record_gpu_usage_event(
    pool,
    user_id: str,
    job_id: str,
    gpu_seconds: float,
    usd_cost: float,
) -> None:
    """Append a kind='gpu' row to usage_events (best-effort, fire-and-forget).

    This makes GPU render spend visible alongside token/storage on the user-
    facing billing dashboard, replacing the render-only ``render_usage_events``
    table as the public ledger entry point.
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO usage_events
                    (id, user_id, kind, usd_cost, payer)
                VALUES ($1, $2, 'gpu', $3, 'kerf_paid')
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
    "GPU_MARKUP_PCT",
    "gpu_rate",
    "compute_usd_cost",
    "meter_render_job",
]
