"""Regression: PricingRefreshWorker must be in the worker harness.

It refreshes model_prices from LiteLLM at boot + daily. It was never
added to _build_workers, so with co-located in-process workers (no
separate worker app) it never ran — model_prices stayed empty after a
DB reset → no chat model dropdown, no up-to-date pricing, billing
"model not in pricing" errors.
"""
from kerf_workers.runner import _build_workers, _maybe_pricing_worker


def test_maybe_pricing_worker_returns_one():
    workers = _maybe_pricing_worker(pool=object())
    assert len(workers) == 1
    assert type(workers[0]).__name__ == "PricingRefreshWorker"


def test_build_workers_always_includes_pricing_refresh():
    # All job-worker counts 0, compaction off → only the pricing worker.
    ws = _build_workers(
        pool=object(), storage_getter=lambda: None,
        fem_count=0, sim_count=0, tess_count=0, cam_count=0,
        compaction_count=0, cloud_enabled=False, local_mode=True,
    )
    names = [type(w).__name__ for w in ws]
    assert "PricingRefreshWorker" in names, (
        f"pricing refresh not wired into the harness — model_prices will "
        f"never repopulate. workers={names}"
    )
