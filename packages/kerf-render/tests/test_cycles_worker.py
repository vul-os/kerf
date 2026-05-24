"""Verification suite for kerf_render.cycles_worker (T-106b).

Covers:
  - cycles_worker: preset tables, cache-key determinism, _write_output, cache
    hit / miss, blender failure surfacing, progress-callback pass-through.
  - cycles_job:    JobLifecycle state machine; submit_job / get_job / transition
    module-level API; in-memory registry.
  - cycles_cache:  CyclesCache content-addressed key; hit / miss; LRU eviction;
    thread-safety smoke test.
  - live Blender integration test: skipped when `blender` not on PATH.

Blender is never invoked in the unit tests: the subprocess seam
(``_invoke_blender``) is monkeypatched so the cache / persistence / preset
logic is exercised deterministically and hermetically.
"""
from __future__ import annotations

import os
import shutil
import threading

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
from kerf_render.cycles_cache import CyclesCache, make_cache_key
from kerf_render.cycles_job import (
    JobLifecycle,
    JobStatus,
    clear_registry,
    get_job,
    submit_job,
    transition,
)


def _cfg(tmp_path) -> CyclesWorkerConfig:
    return CyclesWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        storage_base_url=f"file://{tmp_path}/cache",
    )


# ===========================================================================
# cycles_worker — preset tables
# ===========================================================================


def test_preset_tables_consistent():
    assert set(PRESET_SAMPLES) == {"draft", "standard", "hero", "cinema"}
    assert set(PRESET_TIMEOUTS) == set(PRESET_SAMPLES)
    assert PRESET_SAMPLES["draft"] < PRESET_SAMPLES["cinema"]


# ===========================================================================
# cycles_worker — cache key
# ===========================================================================


def test_cache_key_deterministic_and_sensitive():
    a = _compute_cache_key(b"scene-A", "hero")
    assert a == _compute_cache_key(b"scene-A", "hero")
    assert a != _compute_cache_key(b"scene-B", "hero")
    assert a != _compute_cache_key(b"scene-A", "draft")
    assert compute_cache_key(b"scene-A", "hero") == a


# ===========================================================================
# cycles_worker — _write_output
# ===========================================================================


def test_write_output_png_and_exr(tmp_path):
    cfg = _cfg(tmp_path)
    p_png = _write_output(cfg, "key1", "png", b"PNGDATA")
    p_exr = _write_output(cfg, "key2", "exr", b"EXRDATA")
    assert p_png.endswith("key1.png")
    assert p_exr.endswith("key2.exr")
    assert open(p_png, "rb").read() == b"PNGDATA"


# ===========================================================================
# R19 — _write_output: local vs S3 mode
# ===========================================================================


def test_write_output_local_mode_returns_file_path(tmp_path, monkeypatch):
    """R19: With STORAGE_BACKEND unset (local), _write_output returns a file path."""
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    cfg = _cfg(tmp_path)
    result = _write_output(cfg, "abc123", "png", b"BYTES")
    # Must be a local filesystem path (not an http/s3 URL).
    assert result.startswith("/"), f"Expected file path, got: {result}"
    assert result.endswith("abc123.png")
    assert os.path.isfile(result)


def test_write_output_local_mode_non_s3_backend(tmp_path, monkeypatch):
    """R19: With STORAGE_BACKEND=local, _write_output returns a file path."""
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    cfg = _cfg(tmp_path)
    result = _write_output(cfg, "def456", "exr", b"EXRBYTES")
    assert result.startswith("/")
    assert result.endswith("def456.exr")


def test_write_output_s3_mode_returns_object_store_url(tmp_path, monkeypatch):
    """R19: With STORAGE_BACKEND=s3, _write_output uploads and returns a presigned URL."""
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "test-renders-bucket")

    # Stub kerf_core.storage.create_storage so no real S3 call is made.
    import types, sys

    fake_presigned_url = "https://s3.example.com/renders/key789.png?X-Amz-Signature=abc"

    class _FakeStorage:
        async def put(self, key, body, content_type, size):
            self.last_key = key
            self.last_size = size
            return None

        async def signed_url(self, key, ttl_seconds=900):
            return fake_presigned_url

    fake_storage = _FakeStorage()

    # Patch create_storage in the kerf_render.cycles_worker module namespace.
    from kerf_render import cycles_worker as cw_module

    original = getattr(cw_module, "_write_output_s3", None)

    def _fake_write_output_s3(config, filename, ext, data):
        import asyncio, io

        async def _run():
            await fake_storage.put(f"renders/{filename}", io.BytesIO(data), "image/png", len(data))
            return await fake_storage.signed_url(f"renders/{filename}")

        return asyncio.run(_run())

    monkeypatch.setattr(cw_module, "_write_output_s3", _fake_write_output_s3)

    cfg = _cfg(tmp_path)
    result = _write_output(cfg, "key789", "png", b"IMGDATA")

    # Result must be an object-store URL, not a local file path.
    assert result.startswith("https://"), f"Expected object-store URL, got: {result}"
    assert result == fake_presigned_url


def test_write_output_s3_mode_not_a_local_path(tmp_path, monkeypatch):
    """R19: S3 mode result must never be a local /tmp path."""
    monkeypatch.setenv("STORAGE_BACKEND", "s3")

    from kerf_render import cycles_worker as cw_module

    def _fake_write_output_s3(config, filename, ext, data):
        return "https://tigris.example.com/renders/render123.png"

    monkeypatch.setattr(cw_module, "_write_output_s3", _fake_write_output_s3)
    cfg = _cfg(tmp_path)
    result = _write_output(cfg, "render123", "png", b"X")
    assert not result.startswith("/tmp"), (
        "S3 mode must not return a local /tmp path — "
        f"ephemeral filesystem on Koyeb. Got: {result}"
    )


# ===========================================================================
# cycles_worker — process_job cache hit (no Blender)
# ===========================================================================


def test_process_job_cache_hit(tmp_path):
    cfg = _cfg(tmp_path)
    worker = CyclesWorker(cfg)
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


# ===========================================================================
# cycles_worker — cache miss success (Blender mocked)
# ===========================================================================


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


# ===========================================================================
# cycles_cache — make_cache_key
# ===========================================================================


def test_make_cache_key_deterministic():
    k1 = make_cache_key(scene_glb=b"scene", samples=256, resolution=(1920, 1080))
    k2 = make_cache_key(scene_glb=b"scene", samples=256, resolution=(1920, 1080))
    assert k1 == k2
    assert len(k1) == 64  # hex SHA-256


def test_make_cache_key_sensitive_to_inputs():
    base = make_cache_key(scene_glb=b"A", samples=256, resolution=(1920, 1080))
    assert base != make_cache_key(scene_glb=b"B", samples=256, resolution=(1920, 1080))
    assert base != make_cache_key(scene_glb=b"A", samples=512, resolution=(1920, 1080))
    assert base != make_cache_key(scene_glb=b"A", samples=256, resolution=(2560, 1440))
    assert base != make_cache_key(
        scene_glb=b"A", samples=256, resolution=(1920, 1080),
        translator_version="T-106a-v2",
    )


# ===========================================================================
# cycles_cache — CyclesCache hit / miss
# ===========================================================================


def test_cycles_cache_miss_returns_none():
    cache = CyclesCache()
    assert cache.lookup("nonexistent") is None


def test_cycles_cache_store_and_hit():
    cache = CyclesCache()
    key = make_cache_key(scene_glb=b"scene", samples=256, resolution=(1920, 1080))
    assert cache.lookup(key) is None
    cache.store(key, "/tmp/render.png")
    assert cache.lookup(key) == "/tmp/render.png"


def test_cycles_cache_overwrite_updates_value():
    cache = CyclesCache()
    cache.store("k", "url1")
    cache.store("k", "url2")
    assert cache.lookup("k") == "url2"


def test_cycles_cache_len_and_contains():
    cache = CyclesCache()
    assert len(cache) == 0
    assert "k1" not in cache
    cache.store("k1", "v1")
    assert len(cache) == 1
    assert "k1" in cache


def test_cycles_cache_evict_explicit():
    cache = CyclesCache()
    cache.store("k1", "v1")
    assert cache.evict("k1") is True
    assert cache.evict("k1") is False
    assert cache.lookup("k1") is None


def test_cycles_cache_clear():
    cache = CyclesCache()
    cache.store("a", "1")
    cache.store("b", "2")
    cache.clear()
    assert len(cache) == 0


# ===========================================================================
# cycles_cache — LRU eviction
# ===========================================================================


def test_cycles_cache_lru_evicts_oldest_first():
    """With max_entries=3, inserting a 4th entry evicts the LRU (first-inserted)."""
    cache = CyclesCache(max_entries=3)
    cache.store("a", "1")
    cache.store("b", "2")
    cache.store("c", "3")
    assert len(cache) == 3

    # "d" is inserted; "a" (LRU) should be evicted.
    cache.store("d", "4")
    assert len(cache) == 3
    assert cache.lookup("a") is None  # evicted
    assert cache.lookup("b") == "2"
    assert cache.lookup("c") == "3"
    assert cache.lookup("d") == "4"


def test_cycles_cache_lru_access_promotes_entry():
    """Accessing an entry makes it MRU so it is not evicted first."""
    cache = CyclesCache(max_entries=3)
    cache.store("a", "1")
    cache.store("b", "2")
    cache.store("c", "3")

    # Access "a" to promote it to MRU position.
    cache.lookup("a")

    # Insert "d" — "b" should be evicted (now LRU), not "a".
    cache.store("d", "4")
    assert cache.lookup("a") == "1"   # promoted, still present
    assert cache.lookup("b") is None  # evicted
    assert cache.lookup("c") == "3"
    assert cache.lookup("d") == "4"


def test_cycles_cache_lru_multiple_evictions():
    """Inserting N items beyond capacity evicts N LRU entries."""
    cache = CyclesCache(max_entries=2)
    for i in range(5):
        cache.store(f"k{i}", f"v{i}")
    assert len(cache) == 2
    # Only the two most recently inserted survive.
    assert cache.lookup("k3") == "v3"
    assert cache.lookup("k4") == "v4"
    for i in range(3):
        assert cache.lookup(f"k{i}") is None


def test_cycles_cache_max_entries_one():
    """Edge case: max_entries=1 keeps only the latest entry."""
    cache = CyclesCache(max_entries=1)
    cache.store("a", "1")
    cache.store("b", "2")
    assert len(cache) == 1
    assert cache.lookup("a") is None
    assert cache.lookup("b") == "2"


def test_cycles_cache_invalid_max_entries():
    with pytest.raises(ValueError):
        CyclesCache(max_entries=0)


# ===========================================================================
# cycles_cache — thread-safety smoke test
# ===========================================================================


def test_cycles_cache_thread_safety():
    cache = CyclesCache(max_entries=50)
    errors = []

    def worker(i):
        try:
            for j in range(20):
                key = f"key-{i}-{j}"
                cache.store(key, f"val-{i}-{j}")
                result = cache.lookup(key)
                # May be None if evicted by another thread, but should not crash.
                assert result is None or isinstance(result, str)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread-safety errors: {errors}"


# ===========================================================================
# cycles_job — JobLifecycle state machine
# ===========================================================================


def _make_job(**overrides) -> JobLifecycle:
    defaults = dict(
        job_id="test-job-1",
        scene_glb=b"glb",
        materials_json="{}",
        samples=256,
        resolution=(1920, 1080),
        output_format="png",
    )
    defaults.update(overrides)
    return JobLifecycle(**defaults)


def test_job_initial_state():
    job = _make_job()
    assert job.status == JobStatus.QUEUED
    assert job.result_url is None
    assert job.error is None


def test_job_queued_to_running():
    job = _make_job()
    assert job.start() is True
    assert job.status == JobStatus.RUNNING


def test_job_running_to_completed():
    job = _make_job()
    job.start()
    assert job.complete("/tmp/out.png") is True
    assert job.status == JobStatus.COMPLETED
    assert job.result_url == "/tmp/out.png"


def test_job_running_to_failed():
    job = _make_job()
    job.start()
    assert job.fail("OOM") is True
    assert job.status == JobStatus.FAILED
    assert job.error == "OOM"


def test_job_queued_to_cancelled():
    job = _make_job()
    assert job.cancel() is True
    assert job.status == JobStatus.CANCELLED


def test_job_running_to_cancelled():
    job = _make_job()
    job.start()
    assert job.cancel() is True
    assert job.status == JobStatus.CANCELLED


def test_job_terminal_states_are_immutable():
    """Once in a terminal state no further transitions are allowed."""
    # completed
    j = _make_job()
    j.start()
    j.complete("/tmp/a.png")
    assert j.start() is False
    assert j.complete("/tmp/b.png") is False
    assert j.fail("x") is False
    assert j.cancel() is False

    # failed
    j2 = _make_job(job_id="j2")
    j2.start()
    j2.fail("err")
    assert j2.cancel() is False

    # cancelled
    j3 = _make_job(job_id="j3")
    j3.cancel()
    assert j3.start() is False


def test_job_cannot_skip_queued_directly_to_completed():
    """queued → completed is not a valid direct transition."""
    job = _make_job()
    assert job.complete("/tmp/out.png") is False
    assert job.status == JobStatus.QUEUED


def test_job_cannot_skip_queued_to_failed():
    job = _make_job()
    assert job.fail("err") is False
    assert job.status == JobStatus.QUEUED


def test_job_as_dict_shape():
    job = _make_job()
    d = job.as_dict()
    assert d["id"] == "test-job-1"
    assert d["status"] == "queued"
    assert d["samples"] == 256
    assert d["resolution"] == [1920, 1080]
    assert d["output_format"] == "png"
    assert d["result_url"] is None
    assert d["error"] is None


# ===========================================================================
# cycles_job — module-level registry API
# ===========================================================================


def setup_function():
    """Ensure the registry is clean before each test."""
    clear_registry()


def test_submit_job_returns_id():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080),
    )
    assert isinstance(jid, str) and len(jid) > 0


def test_submit_job_explicit_id():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080), job_id="my-job",
    )
    assert jid == "my-job"


def test_get_job_returns_lifecycle():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080),
    )
    job = get_job(jid)
    assert isinstance(job, JobLifecycle)
    assert job.status == JobStatus.QUEUED


def test_get_job_missing_returns_none():
    assert get_job("no-such-id") is None


def test_transition_queued_to_running():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080),
    )
    assert transition(jid, "running") is True
    assert get_job(jid).status == JobStatus.RUNNING


def test_transition_to_completed():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080),
    )
    transition(jid, "running")
    assert transition(jid, "completed", result_url="/tmp/r.png") is True
    job = get_job(jid)
    assert job.status == JobStatus.COMPLETED
    assert job.result_url == "/tmp/r.png"


def test_transition_to_failed():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080),
    )
    transition(jid, "running")
    assert transition(jid, "failed", error="crash") is True
    job = get_job(jid)
    assert job.status == JobStatus.FAILED
    assert job.error == "crash"


def test_transition_to_cancelled_from_queued():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080),
    )
    assert transition(jid, "cancelled") is True
    assert get_job(jid).status == JobStatus.CANCELLED


def test_transition_unknown_job_returns_false():
    assert transition("ghost-id", "running") is False


def test_transition_unknown_target_returns_false():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080),
    )
    assert transition(jid, "launched") is False


def test_transition_terminal_is_noop():
    jid = submit_job(
        scene_glb=b"glb", materials_json="{}", samples=256,
        resolution=(1920, 1080),
    )
    transition(jid, "cancelled")
    assert transition(jid, "running") is False


# ===========================================================================
# Live Blender integration test (skipped when blender not on PATH)
# ===========================================================================


@pytest.mark.skipif(
    shutil.which("blender") is None,
    reason="blender not found on PATH — skipping live integration test",
)
def test_live_blender_render(tmp_path):
    """End-to-end smoke test: submit a minimal job and let Blender render it.

    Only runs when ``blender`` resolves on PATH.  Uses an empty scene_blob
    (stub script path) so no real geometry is needed.
    """
    cfg = CyclesWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        blender_path=shutil.which("blender"),
    )
    worker = CyclesWorker(cfg)
    res = worker.process_job({"scene_blob": b"", "preset": "draft"})
    # A live run with an empty blob may fail inside Blender (no scene to render),
    # but it should not raise an exception in the harness.
    assert "ok" in res
