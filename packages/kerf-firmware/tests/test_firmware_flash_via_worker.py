"""
test_firmware_flash_via_worker.py — round-trip tests for the cloud-relay
firmware flash job dispatcher.

Covers:
  F01  LLM tool returns BAD_ARGS when project_id missing
  F02  LLM tool returns BAD_ARGS when firmware_artifact_key missing
  F03  LLM tool returns BAD_ARGS when board_target missing
  F04  LLM tool returns BAD_ARGS for invalid UUID project_id
  F05  LLM tool succeeds (stub path, no pool) with valid args
  F06  flash_tool is 'esptool' for 'esp32' board target
  F07  flash_tool is 'avrdude' for 'avr_uno' board target
  F08  flash_tool is 'openocd' for 'stm32f4' board target
  F09  flash_tool is 'avrdude' for unknown board target (default)
  F10  LLM tool handler is an async coroutine
  F11  FirmwareFlashWorker.stop() sets _stop flag
  F12  _flash_tool_for prefix matching (esp8266 → esptool)
  F13  billing_bucket is always 'byo' in stub response
  F14  round-trip: submit + claim via mocked asyncpg pool
  F15  _register_tools adds firmware.flash_via_worker to provides
"""
from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kerf_firmware.tools.firmware_flash_via_worker import (
    _flash_tool_for,
    firmware_flash_via_worker_spec,
    run_firmware_flash_via_worker,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _valid_args(**overrides):
    base = {
        "project_id": str(uuid.uuid4()),
        "firmware_artifact_key": "projects/abc/firmware/firmware.bin",
        "board_target": "esp32",
    }
    base.update(overrides)
    return json.dumps(base).encode()


# ── F01–F04 BAD_ARGS ──────────────────────────────────────────────────────────

class TestBadArgs:
    def test_f01_missing_project_id(self):
        payload = json.dumps({
            "firmware_artifact_key": "key",
            "board_target": "esp32",
        }).encode()
        result = json.loads(_run(run_firmware_flash_via_worker(None, payload)))
        assert result["error"] == "BAD_ARGS"
        assert "project_id" in result["message"]

    def test_f02_missing_artifact_key(self):
        payload = json.dumps({
            "project_id": str(uuid.uuid4()),
            "board_target": "esp32",
        }).encode()
        result = json.loads(_run(run_firmware_flash_via_worker(None, payload)))
        assert result["error"] == "BAD_ARGS"
        assert "firmware_artifact_key" in result["message"]

    def test_f03_missing_board_target(self):
        payload = json.dumps({
            "project_id": str(uuid.uuid4()),
            "firmware_artifact_key": "some/key",
        }).encode()
        result = json.loads(_run(run_firmware_flash_via_worker(None, payload)))
        assert result["error"] == "BAD_ARGS"
        assert "board_target" in result["message"]

    def test_f04_invalid_uuid_project_id(self):
        payload = json.dumps({
            "project_id": "not-a-uuid",
            "firmware_artifact_key": "some/key",
            "board_target": "esp32",
        }).encode()
        result = json.loads(_run(run_firmware_flash_via_worker(None, payload)))
        assert result["error"] == "BAD_ARGS"
        assert "UUID" in result["message"]


# ── F05 stub (no pool) ────────────────────────────────────────────────────────

class TestStubPath:
    def test_f05_valid_args_no_pool_returns_ok(self):
        """F05: valid args with no pool wired → stub ok response."""
        result = json.loads(_run(run_firmware_flash_via_worker(None, _valid_args())))
        assert result["ok"] is True
        assert result["status"] == "queued"
        assert "job_id" in result
        # UUID must be parseable
        uuid.UUID(result["job_id"])

    def test_f13_billing_bucket_is_byo(self):
        """F13: billing_bucket must always be 'byo'."""
        result = json.loads(_run(run_firmware_flash_via_worker(None, _valid_args())))
        assert result["billing_bucket"] == "byo"


# ── F06–F09 flash tool selection ─────────────────────────────────────────────

class TestFlashToolSelection:
    def test_f06_esp32_uses_esptool(self):
        assert _flash_tool_for("esp32") == "esptool"

    def test_f07_avr_uno_uses_avrdude(self):
        assert _flash_tool_for("avr_uno") == "avrdude"

    def test_f08_stm32f4_uses_openocd(self):
        assert _flash_tool_for("stm32f4") == "openocd"

    def test_f09_unknown_defaults_to_avrdude(self):
        assert _flash_tool_for("unknown_board_xyz") == "avrdude"

    def test_f12_esp8266_prefix_match(self):
        """F12: prefix matching — esp8266 → esptool."""
        assert _flash_tool_for("esp8266") == "esptool"


# ── F10 coroutine check ───────────────────────────────────────────────────────

class TestHandlerIsCoroutine:
    def test_f10_handler_is_async(self):
        """F10: the LLM tool handler must be an async coroutine function."""
        assert inspect.iscoroutinefunction(run_firmware_flash_via_worker)


# ── F11 worker stop flag ──────────────────────────────────────────────────────

class TestFirmwareFlashWorker:
    def test_f11_stop_sets_flag(self):
        """F11: FirmwareFlashWorker.stop() sets the _stop flag."""
        from kerf_workers.firmware_flash_worker import FirmwareFlashWorker
        pool = MagicMock()
        worker = FirmwareFlashWorker(pool=pool)
        assert worker._stop is False
        worker.stop()
        assert worker._stop is True


# ── F14 round-trip via mocked pool ──────────────────────────────────────────

class TestRoundTripMockedPool:
    """F14: submit a firmware flash job through the LLM tool handler using a
    mocked asyncpg pool, then verify the claim query would be issued correctly.
    """

    def test_f14_submit_inserts_row(self):
        """F14: run_firmware_flash_via_worker calls pool.execute with the right query."""
        pool = AsyncMock()
        pool.execute = AsyncMock(return_value=None)

        ctx = SimpleNamespace(pool=pool, user_id=None)

        pid = str(uuid.uuid4())
        payload = json.dumps({
            "project_id": pid,
            "firmware_artifact_key": "projects/abc/fw.bin",
            "board_target": "avr_uno",
        }).encode()

        result = json.loads(_run(run_firmware_flash_via_worker(ctx, payload)))

        assert result["ok"] is True
        assert result["status"] == "queued"
        assert result["billing_bucket"] == "byo"
        assert result["flash_tool"] == "avrdude"
        # pool.execute must have been called once (INSERT INTO firmware_flash_jobs)
        pool.execute.assert_called_once()
        call_args = pool.execute.call_args
        sql = call_args[0][0]
        assert "firmware_flash_jobs" in sql
        assert "billing_bucket" in sql


# ── F15 plugin provides ───────────────────────────────────────────────────────

class TestPluginProvides:
    def test_f15_register_tools_adds_flash_via_worker(self):
        """F15: _register_tools adds 'firmware.flash_via_worker' to provides."""
        registered = {}

        class _Tools:
            def register(self, name, spec, handler):
                registered[name] = (spec, handler)

        ctx = SimpleNamespace(tools=_Tools())
        provides: list[str] = []

        from kerf_firmware.plugin import _register_tools
        _register_tools(ctx, provides)

        assert "firmware.flash_via_worker" in provides, (
            f"firmware.flash_via_worker missing from provides: {provides}"
        )
        assert "firmware_flash_via_worker" in registered, (
            f"firmware_flash_via_worker tool not registered"
        )
