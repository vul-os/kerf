"""Verification suite for kerf_render.cycles_worker (T-106b).

Blender is never invoked: the subprocess seam (``_invoke_blender``) is
monkeypatched so the cache / persistence / preset logic is exercised
deterministically and hermetically.
"""
from __future__ import annotations

import os

import pytest

from kerf_render.cycles_worker import (
    PRESET_SAMPLES,
    PRESET_TIMEOUTS,
    CyclesWorker,
    CyclesWorkerConfig,
    _compute_cache_key,
    _write_output,
    compute_cache_key,
)


def _cfg(tmp_path) -> CyclesWorkerConfig:
    return CyclesWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        storage_base_url=f"file://{tmp_path}/cache",
    )


# ---------------------------------------------------------------------------
# Preset tables
# ---------------------------------------------------------------------------


def test_preset_tables_consistent():
    assert set(PRESET_SAMPLES) == {"draft", "standard", "hero", "cinema"}
    assert set(PRESET_TIMEOUTS) == set(PRESET_SAMPLES)
    assert PRESET_SAMPLES["draft"] < PRESET_SAMPLES["cinema"]


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def test_cache_key_deterministic_and_sensitive():
    a = _compute_cache_key(b"scene-A", "hero")
    assert a == _compute_cache_key(b"scene-A", "hero")
    assert a != _compute_cache_key(b"scene-B", "hero")
    assert a != _compute_cache_key(b"scene-A", "draft")
    assert compute_cache_key(b"scene-A", "hero") == a


# ---------------------------------------------------------------------------
# _write_output
# ---------------------------------------------------------------------------


def test_write_output_png_and_exr(tmp_path):
    cfg = _cfg(tmp_path)
    p_png = _write_output(cfg, "key1", "png", b"PNGDATA")
    p_exr = _write_output(cfg, "key2", "exr", b"EXRDATA")
    assert p_png.endswith("key1.png")
    assert p_exr.endswith("key2.exr")
    assert open(p_png, "rb").read() == b"PNGDATA"


# ---------------------------------------------------------------------------
# process_job — cache hit (no Blender)
# ---------------------------------------------------------------------------


def test_process_job_cache_hit(tmp_path):
    cfg = _cfg(tmp_path)
    worker = CyclesWorker(cfg)
    # Pre-seed the cache by writing an output + index entry via a first run.
    from kerf_render.cycles_worker import _cache_store

    key = _compute_cache_key(b"", "standard")
    _cache_store(cfg, key, "/some/cached/url.png")

    res = worker.process_job({"scene_blob": b"", "preset": "standard"})
    assert res["ok"] is True
    assert res["from_cache"] is True
    assert res["render_seconds"] == 0.0
    assert res["signed_url"] == "/some/cached/url.png"
    assert res["samples"] == PRESET_SAMPLES["standard"]


def test_process_job_unknown_preset_normalises(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    worker = CyclesWorker(cfg)

    def fake_invoke(self, **kw):
        return {"ok": True, "output_data": b"IMG"}

    monkeypatch.setattr(CyclesWorker, "_invoke_blender", fake_invoke)
    res = worker.process_job({"scene_blob": b"", "preset": "nonsense"})
    assert res["ok"] is True
    assert res["samples"] == PRESET_SAMPLES["standard"]


# ---------------------------------------------------------------------------
# process_job — cache miss success (Blender mocked)
# ---------------------------------------------------------------------------


def test_process_job_render_success_then_cached(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    worker = CyclesWorker(cfg)

    calls = {"n": 0}

    def fake_invoke(self, **kw):
        calls["n"] += 1
        return {"ok": True, "output_data": b"RENDERED-PNG-BYTES"}

    monkeypatch.setattr(CyclesWorker, "_invoke_blender", fake_invoke)

    job = {"scene_blob": b"", "preset": "hero"}
    r1 = worker.process_job(job)
    assert r1["ok"] is True
    assert r1["from_cache"] is False
    assert r1["samples"] == PRESET_SAMPLES["hero"]
    assert os.path.exists(r1["signed_url"])
    assert open(r1["signed_url"], "rb").read() == b"RENDERED-PNG-BYTES"
    assert r1["render_seconds"] >= 0.0

    # Second identical job → served from cache, Blender not called again.
    r2 = worker.process_job(job)
    assert r2["from_cache"] is True
    assert calls["n"] == 1


def test_process_job_blender_failure_surfaces(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    worker = CyclesWorker(cfg)

    def fake_invoke(self, **kw):
        return {
            "ok": False,
            "reason": "blender_crashed",
            "stderr_tail": "Segmentation fault",
        }

    monkeypatch.setattr(CyclesWorker, "_invoke_blender", fake_invoke)
    res = worker.process_job({"scene_blob": b"", "preset": "draft"})
    assert res["ok"] is False
    assert res["reason"] == "blender_crashed"
    assert "Segmentation fault" in res["stderr_tail"]


def test_progress_callback_passed_through(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    worker = CyclesWorker(cfg)
    seen = {}

    def fake_invoke(self, **kw):
        seen["has_cb"] = kw.get("progress_callback") is not None
        return {"ok": True, "output_data": b"IMG"}

    monkeypatch.setattr(CyclesWorker, "_invoke_blender", fake_invoke)
    worker.process_job(
        {"scene_blob": b"", "preset": "draft"},
        progress_callback=lambda ev: None,
    )
    assert seen["has_cb"] is True
