"""Tests for kerf-worker CLI commands and runner loop.

All tests are hermetic — no real API calls, no real Blender/CalculiX.

Test matrix
-----------
1. enroll → token stored in config file (mock httpx).
2. run loop: mock claim-job returns cycles_render → subprocess succeeds → upload called.
3. status: reads config and prints correct fields.
4. revoke: calls DELETE /api/workers/{id} and removes local config.
5. GPU probe: nvidia-smi present → parsed correctly.
6. GPU probe: nvidia-smi absent → empty gpus, graceful fallback.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import tempfile
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

# ---------------------------------------------------------------------------
# sys.path bootstrap so tests work without installing the package.
# ---------------------------------------------------------------------------
import sys
_HERE = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_HERE / "src"))

from kerf_worker import config as wconfig
from kerf_worker import gpu as gpu_mod
from kerf_worker import runner as runner_mod
from kerf_worker.cli import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_WORKER_ID = str(uuid.uuid4())
_TOKEN = "kerf_wk_" + "a" * 64


@pytest.fixture()
def tmp_config(tmp_path):
    """Redirect config reads/writes to a temp directory."""
    cfg_file = tmp_path / "worker.json"
    with patch.dict(os.environ, {"KERF_WORKER_CONFIG": str(cfg_file)}):
        yield cfg_file


@pytest.fixture()
def enrolled_config(tmp_config):
    """Pre-create an enrolled config file."""
    cfg = wconfig.WorkerConfig(
        worker_id=_WORKER_ID,
        token=_TOKEN,
        api_base="https://kerf.test",
        name="test-gpu",
        capabilities={
            "gpus": [{"name": "Tesla T4", "memory_total_mib": 16384}],
            "supported_workloads": ["cycles_render", "fem_solve"],
            "platform": "linux-nvidia",
        },
    )
    wconfig.save(cfg)
    return tmp_config


# ---------------------------------------------------------------------------
# 1. enroll — token stored
# ---------------------------------------------------------------------------

class TestEnroll:
    def test_enroll_stores_config(self, tmp_config):
        runner = CliRunner()
        enroll_response = {"id": _WORKER_ID, "name": "my-gpu", "token": _TOKEN}

        with (
            patch("kerf_worker.cli.gpu_probe.probe", return_value={"gpus": [], "supported_workloads": [], "platform": "linux-unknown"}),
            patch("kerf_worker.cli.httpx.post") as mock_post,
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = enroll_response
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp

            result = runner.invoke(
                app,
                ["enroll", _TOKEN, "--name", "my-gpu", "--api-url", "https://kerf.test"],
            )

        assert result.exit_code == 0, result.output
        assert "Enrolled successfully" in result.output
        assert _WORKER_ID in result.output

        # Config must be persisted.
        cfg = wconfig.load()
        assert cfg is not None
        assert cfg.worker_id == _WORKER_ID
        assert cfg.token == _TOKEN
        assert cfg.api_base == "https://kerf.test"

    def test_enroll_server_error_exits_nonzero(self, tmp_config):
        runner = CliRunner()
        import httpx as _httpx

        with (
            patch("kerf_worker.cli.gpu_probe.probe", return_value={"gpus": [], "supported_workloads": [], "platform": "unknown"}),
            patch("kerf_worker.cli.httpx.post") as mock_post,
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401, text="Unauthorized")
            )
            mock_post.return_value = mock_resp

            result = runner.invoke(app, ["enroll", "bad-token"])

        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 2. run loop — claim cycles_render, subprocess succeeds, upload called
# ---------------------------------------------------------------------------

class TestRunLoop:
    @pytest.mark.asyncio
    async def test_cycles_render_job(self, enrolled_config):
        """Mock claim-job returns cycles_render; mock blender succeeds; complete called."""
        job_id = str(uuid.uuid4())
        job_spec = {
            "job_id": job_id,
            "scene_blob_hash": "abc123",
            "preset": "cycles_render",
            "samples_total": 64,
            "billing_bucket": "byo",
            "signed_input_url": "",   # no download; test will stub subprocess directly
        }

        heartbeat_calls: List[Dict] = []
        complete_calls: List[Dict] = []

        stop = asyncio.Event()

        # After one successful job completion, stop the loop.
        async def fake_heartbeat(client, base, worker_id, token, status="online"):
            heartbeat_calls.append({"worker_id": worker_id})

        async def fake_claim(client, base, worker_id, token):
            # Return job first call, then stop the loop.
            if not complete_calls:
                return job_spec
            stop.set()
            return None

        async def fake_complete(client, base, worker_id, job_id_arg, token,
                                signed_url="", gpu_seconds=0.0, error=None):
            complete_calls.append({"job_id": job_id_arg, "signed_url": signed_url, "error": error})
            stop.set()

        # Stub out _run_cycles so no real Blender needed.
        async def fake_run_cycles(job, workdir):
            result_path = str(workdir / "out" / "frame_0001.png")
            # Create a dummy file so _upload_result can open it.
            (workdir / "out").mkdir(parents=True, exist_ok=True)
            (workdir / "out" / "frame_0001.png").write_bytes(b"\x89PNG\r\n")
            return (result_path, 5.5, None)

        with (
            patch.object(runner_mod, "_heartbeat_once", fake_heartbeat),
            patch.object(runner_mod, "_claim_job", fake_claim),
            patch.object(runner_mod, "_complete_job", fake_complete),
            patch.object(runner_mod, "_run_cycles", fake_run_cycles),
        ):
            await runner_mod.run_loop(stop_event=stop)

        assert len(complete_calls) == 1
        assert complete_calls[0]["job_id"] == job_id
        assert complete_calls[0]["error"] is None

    @pytest.mark.asyncio
    async def test_unsupported_job_kind_sends_error(self, enrolled_config):
        """An unsupported job kind results in an error completion, not a crash."""
        job_id = str(uuid.uuid4())
        job_spec = {
            "job_id": job_id,
            "preset": "exotic_workload",
            "billing_bucket": "byo",
        }

        complete_calls: List[Dict] = []
        stop = asyncio.Event()

        async def fake_heartbeat(*a, **kw):
            pass

        async def fake_claim(client, base, worker_id, token):
            if not complete_calls:
                return job_spec
            return None

        async def fake_complete(client, base, worker_id, job_id_arg, token,
                                signed_url="", gpu_seconds=0.0, error=None):
            complete_calls.append({"error": error})
            stop.set()

        with (
            patch.object(runner_mod, "_heartbeat_once", fake_heartbeat),
            patch.object(runner_mod, "_claim_job", fake_claim),
            patch.object(runner_mod, "_complete_job", fake_complete),
        ):
            await runner_mod.run_loop(stop_event=stop)

        assert len(complete_calls) == 1
        assert complete_calls[0]["error"] is not None
        assert "unsupported" in complete_calls[0]["error"]


# ---------------------------------------------------------------------------
# 3. status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_enrolled(self, enrolled_config):
        runner = CliRunner()
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert _WORKER_ID in result.output
        assert "test-gpu" in result.output
        assert "Tesla T4" in result.output
        assert "kerf.test" in result.output

    def test_status_not_enrolled(self, tmp_config):
        runner = CliRunner()
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Not enrolled" in result.output


# ---------------------------------------------------------------------------
# 4. revoke
# ---------------------------------------------------------------------------

class TestRevoke:
    def test_revoke_calls_api_and_removes_config(self, enrolled_config):
        runner = CliRunner()

        with patch("kerf_worker.cli.httpx.delete") as mock_delete:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_delete.return_value = mock_resp

            result = runner.invoke(app, ["revoke", "--yes"])

        assert result.exit_code == 0
        assert "revoked" in result.output.lower() or "removed" in result.output.lower()

        # Config file must be gone.
        assert wconfig.load() is None

        # DELETE must have been called with the right URL.
        assert mock_delete.called
        call_url = mock_delete.call_args[0][0]
        assert _WORKER_ID in call_url

    def test_revoke_no_config(self, tmp_config):
        runner = CliRunner()
        result = runner.invoke(app, ["revoke", "--yes"])
        assert result.exit_code == 0
        assert "No enrolled worker" in result.output


# ---------------------------------------------------------------------------
# 5 & 6. GPU probe
# ---------------------------------------------------------------------------

class TestGPUProbe:
    def test_nvidia_smi_parsed(self):
        fake_output = "NVIDIA GeForce RTX 4090, 24576 MiB\nNVIDIA GeForce RTX 3080, 10240 MiB\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=fake_output, stderr=""
            )
            caps = gpu_mod.probe()

        assert caps["platform"] == "linux-nvidia"
        assert len(caps["gpus"]) == 2
        assert caps["gpus"][0]["name"] == "NVIDIA GeForce RTX 4090"
        assert caps["gpus"][0]["memory_total_mib"] == 24576
        assert "cycles_render" in caps["supported_workloads"]

    def test_nvidia_smi_absent(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            caps = gpu_mod.probe()

        assert caps["gpus"] == []
        assert "cycles_render" in caps["supported_workloads"]
        assert "unknown" in caps["platform"]
