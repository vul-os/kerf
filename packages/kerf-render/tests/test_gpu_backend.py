"""Tests for kerf_render.gpu_backend — GPUBackend protocol + dispatch.

Covers:
1. Protocol conformance — a minimal fake backend satisfies the Protocol.
2. RunPodGPUBackend — capabilities() returns expected structure; submit/poll
   raise NotImplementedError (stub guard until RUNPOD-BACKEND).
3. SelfHostedWorkerBackend — submit writes render_jobs; poll returns status;
   fetch_result returns signed_url bytes.
4. select_backend — (a) preferred, (b) capability-match, (c) default fallback.
5. register_backend — custom backend is findable after registration.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kerf_render.gpu_backend import (
    GPUBackend,
    JobStatus,
    RunPodGPUBackend,
    SelfHostedWorkerBackend,
    register_backend,
    registered_backends,
    select_backend,
)


# ---------------------------------------------------------------------------
# Async runner helper
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Minimal fake asyncpg pool
# ---------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, fetchrow_return=None):
        self._fetchrow_return = fetchrow_return
        self.executions: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.executions.append((sql, args))
        return "INSERT 0 1"

    async def fetchrow(self, sql: str, *args: Any) -> Optional[Dict]:
        return self._fetchrow_return


class _FakePool:
    def __init__(self, fetchrow_return=None):
        self.conn = _FakeConn(fetchrow_return)

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------

class MinimalFakeBackend:
    """A minimal backend that satisfies the GPUBackend Protocol."""
    backend_id = "fake"
    billing_bucket = "kerf_paid"

    async def submit(self, job: Dict[str, Any]) -> str:
        return "fake_ext_id"

    async def poll(self, external_id: str) -> "JobStatus":
        return JobStatus("complete")

    async def fetch_result(self, external_id: str) -> bytes:
        return b"fake_bytes"

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "gpu_type": "fake",
            "vram_gb": 8,
            "supported_workloads": ["render"],
            "max_concurrent": 1,
            "backend_id": "fake",
            "billing_bucket": "kerf_paid",
        }


def test_fake_backend_satisfies_protocol():
    """MinimalFakeBackend is a runtime instance of GPUBackend."""
    b = MinimalFakeBackend()
    assert isinstance(b, GPUBackend)


def test_fake_backend_submit():
    result = run(MinimalFakeBackend().submit({"job_type": "render"}))
    assert result == "fake_ext_id"


def test_fake_backend_poll():
    status = run(MinimalFakeBackend().poll("fake_ext_id"))
    assert isinstance(status, JobStatus)
    assert status.state == "complete"


# ---------------------------------------------------------------------------
# 2. RunPodGPUBackend — stub guard
# ---------------------------------------------------------------------------

class TestRunPodGPUBackend:
    def test_backend_id(self):
        b = RunPodGPUBackend()
        assert b.backend_id == "runpod"

    def test_billing_bucket_is_kerf_paid(self):
        b = RunPodGPUBackend()
        assert b.billing_bucket == "kerf_paid"

    def test_submit_raises_not_implemented(self):
        b = RunPodGPUBackend()
        with pytest.raises(NotImplementedError):
            run(b.submit({"job_type": "render"}))

    def test_poll_raises_not_implemented(self):
        b = RunPodGPUBackend()
        with pytest.raises(NotImplementedError):
            run(b.poll("some-ext-id"))

    def test_fetch_result_raises_not_implemented(self):
        b = RunPodGPUBackend()
        with pytest.raises(NotImplementedError):
            run(b.fetch_result("some-ext-id"))

    def test_capabilities_returns_dict(self):
        b = RunPodGPUBackend()
        caps = run(b.capabilities())
        assert isinstance(caps, dict)
        assert caps["backend_id"] == "runpod"
        assert caps["billing_bucket"] == "kerf_paid"
        assert "render" in caps["supported_workloads"]

    def test_is_gpu_backend_protocol(self):
        b = RunPodGPUBackend()
        assert isinstance(b, GPUBackend)


# ---------------------------------------------------------------------------
# 3. SelfHostedWorkerBackend
# ---------------------------------------------------------------------------

class TestSelfHostedWorkerBackend:
    def test_backend_id(self):
        pool = _FakePool()
        b = SelfHostedWorkerBackend("worker-1", pool)
        assert b.backend_id == "self_hosted"

    def test_billing_bucket_is_byo(self):
        pool = _FakePool()
        b = SelfHostedWorkerBackend("worker-1", pool)
        assert b.billing_bucket == "byo"

    def test_submit_inserts_render_job(self):
        pool = _FakePool()
        b = SelfHostedWorkerBackend("worker-1", pool)
        job = {
            "job_id": "j-abc",
            "user_id": "u-123",
            "scene_blob_hash": "sha:xxx",
            "preset": "standard",
        }
        ext_id = run(b.submit(job))
        assert ext_id == "j-abc"
        # Verify INSERT was called with billing_bucket='byo'
        sqls = [ex[0] for ex in pool.conn.executions]
        assert any("billing_bucket" in s for s in sqls), "Expected billing_bucket in INSERT"

    def test_submit_generates_job_id_if_absent(self):
        pool = _FakePool()
        b = SelfHostedWorkerBackend("worker-1", pool)
        ext_id = run(b.submit({"job_type": "render"}))
        # Should be a valid UUID string
        uuid.UUID(ext_id)  # raises if invalid

    def test_poll_queued(self):
        row = {
            "status": "queued",
            "error": None,
            "samples_done": 0,
            "samples_total": 0,
        }
        pool = _FakePool(fetchrow_return=row)
        b = SelfHostedWorkerBackend("w", pool)
        status = run(b.poll("j"))
        assert status.state == "queued"
        assert status.progress is None

    def test_poll_running_with_progress(self):
        row = {
            "status": "running",
            "error": None,
            "samples_done": 50,
            "samples_total": 100,
        }
        pool = _FakePool(fetchrow_return=row)
        b = SelfHostedWorkerBackend("w", pool)
        status = run(b.poll("j"))
        assert status.state == "running"
        assert status.progress == pytest.approx(0.5)

    def test_poll_rendering_normalises_to_running(self):
        row = {"status": "rendering", "error": None, "samples_done": 10, "samples_total": 100}
        pool = _FakePool(fetchrow_return=row)
        b = SelfHostedWorkerBackend("w", pool)
        status = run(b.poll("j"))
        assert status.state == "running"

    def test_poll_not_found(self):
        pool = _FakePool(fetchrow_return=None)
        b = SelfHostedWorkerBackend("w", pool)
        status = run(b.poll("missing"))
        assert status.state == "not_found"
        assert status.error == "job not found"

    def test_fetch_result_returns_url_bytes(self):
        row = {"status": "complete", "signed_url": "https://cdn.example.com/result.png"}
        pool = _FakePool(fetchrow_return=row)
        b = SelfHostedWorkerBackend("w", pool)
        raw = run(b.fetch_result("j"))
        assert raw == b"https://cdn.example.com/result.png"

    def test_fetch_result_raises_if_not_complete(self):
        row = {"status": "queued", "signed_url": None}
        pool = _FakePool(fetchrow_return=row)
        b = SelfHostedWorkerBackend("w", pool)
        with pytest.raises(ValueError):
            run(b.fetch_result("j"))

    def test_capabilities_reads_db(self):
        caps_payload = {
            "gpu_type": "RTX 4090",
            "vram_gb": 24,
            "supported_workloads": ["render", "fem"],
        }
        row = {"capabilities": caps_payload}
        pool = _FakePool(fetchrow_return=row)
        b = SelfHostedWorkerBackend("w", pool)
        caps = run(b.capabilities())
        assert caps["gpu_type"] == "RTX 4090"
        assert caps["vram_gb"] == 24
        assert "render" in caps["supported_workloads"]
        assert caps["backend_id"] == "self_hosted"
        assert caps["billing_bucket"] == "byo"


# ---------------------------------------------------------------------------
# 4. select_backend — routing logic
# ---------------------------------------------------------------------------

class TestSelectBackend:
    def _make_fake(self, backend_id="fake", billing_bucket="kerf_paid", workloads=None):
        b = MinimalFakeBackend()
        b.backend_id = backend_id
        b.billing_bucket = billing_bucket
        b._supported_workloads = workloads or ["render"]
        return b

    def test_preferred_backend_selected(self):
        backend_a = self._make_fake("runpod")
        backend_b = self._make_fake("self_hosted", "byo")
        job = {"job_type": "render"}
        result = select_backend(
            job,
            project_preferred_backend="self_hosted",
            available_backends=[backend_a, backend_b],
        )
        assert result is backend_b

    def test_preferred_backend_not_found_falls_through_to_capability_match(self):
        backend_a = self._make_fake("runpod")
        job = {"job_type": "render"}
        result = select_backend(
            job,
            project_preferred_backend="nonexistent",
            available_backends=[backend_a],
        )
        assert result is backend_a

    def test_capability_match_picks_first_supporting_workload(self):
        render_backend = self._make_fake("render_only", workloads=["render"])
        fem_backend = self._make_fake("fem_only", workloads=["fem"])
        job = {"job_type": "fem"}
        result = select_backend(job, available_backends=[render_backend, fem_backend])
        assert result is fem_backend

    def test_no_match_returns_default_vendor(self):
        default = self._make_fake("runpod")
        job = {"job_type": "render"}
        result = select_backend(
            job,
            available_backends=[],
            default_vendor_backend=default,
        )
        assert result is default

    def test_no_match_no_default_returns_none(self):
        result = select_backend({"job_type": "render"})
        assert result is None

    def test_preferred_backend_wins_over_capability_match(self):
        preferred = self._make_fake("self_hosted", "byo")
        capable = self._make_fake("runpod")
        job = {"job_type": "render"}
        result = select_backend(
            job,
            project_preferred_backend="self_hosted",
            available_backends=[capable, preferred],
        )
        assert result is preferred


# ---------------------------------------------------------------------------
# 5. register_backend
# ---------------------------------------------------------------------------

class TestRegisterBackend:
    def test_register_custom_backend(self):
        class MyBackend:
            backend_id = "my_cloud"
            billing_bucket = "kerf_paid"
            async def submit(self, job): return "x"
            async def poll(self, ext_id): return JobStatus("queued")
            async def fetch_result(self, ext_id): return b""
            async def capabilities(self): return {}

        register_backend("my_cloud", MyBackend)
        assert "my_cloud" in registered_backends()
        assert registered_backends()["my_cloud"] is MyBackend


# ---------------------------------------------------------------------------
# 6. JobStatus helpers
# ---------------------------------------------------------------------------

class TestJobStatus:
    def test_default_fields(self):
        s = JobStatus("queued")
        assert s.state == "queued"
        assert s.progress is None
        assert s.error is None
        assert s.raw == {}

    def test_with_progress_and_error(self):
        s = JobStatus("failed", progress=0.5, error="OOM", raw={"code": 1})
        assert s.state == "failed"
        assert s.progress == 0.5
        assert s.error == "OOM"
        assert s.raw == {"code": 1}
