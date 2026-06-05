"""
Tests for kerf_plm.tools plm_quote_to_delivery LLM tool.

Covers:
  1.  Spec name, description, required fields
  2.  Plugin registration (plm_quote_to_delivery in ctx.tools)
  3.  transition — valid transition returns updated job
  4.  transition — invalid transition returns INVALID_TRANSITION error
  5.  transition — unknown operation returns BAD_ARGS
  6.  transition — missing required new_status returns BAD_ARGS
  7.  transition — bad JSON args returns BAD_ARGS
  8.  status_report — returns by_status, overdue_count
  9.  on_time_rate — returns rate in [0, 1]
  10. on_time_rate — 1.0 for on-time delivered job
  11. on_time_rate — 0.0 for late-delivered job
  12. Full QUOTED → INVOICED walk-through via tool
"""

from __future__ import annotations

import asyncio
import json
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_plm.tools import plm_quote_to_delivery_spec, run_plm_quote_to_delivery


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call(args: dict) -> dict:
    raw = _run(run_plm_quote_to_delivery(CTX, json.dumps(args).encode()))
    return json.loads(raw)


def _seed_job(
    job_id: str = "JOB-001",
    current_status: str = "quoted",
    promised: str = "2026-09-01",
    history: list | None = None,
) -> dict:
    if history is None:
        history = [
            {"status": "quoted", "timestamp_iso": "2026-06-01T08:00:00Z", "actor": "sales", "notes": ""}
        ]
    return {
        "job_id": job_id,
        "customer_id": "CUST-1",
        "quote_id": "Q-001",
        "quoted_amount_usd": 15000.0,
        "promised_delivery_iso": promised,
        "current_status": current_status,
        "history": history,
    }


# ---------------------------------------------------------------------------
# 1. Spec shape
# ---------------------------------------------------------------------------

class TestSpec:
    def test_name(self):
        assert plm_quote_to_delivery_spec.name == "plm_quote_to_delivery"

    def test_description_mentions_isa95(self):
        assert "ISA-95" in plm_quote_to_delivery_spec.description

    def test_required_has_operation(self):
        assert "operation" in plm_quote_to_delivery_spec.input_schema["required"]

    def test_operations_enum(self):
        ops = plm_quote_to_delivery_spec.input_schema["properties"]["operation"]["enum"]
        assert "transition" in ops
        assert "status_report" in ops
        assert "on_time_rate" in ops


# ---------------------------------------------------------------------------
# 2. Plugin registration
# ---------------------------------------------------------------------------

class TestPluginRegistration:
    def test_registered_in_tools_init(self):
        from kerf_plm.tools import plm_quote_to_delivery_spec, run_plm_quote_to_delivery
        assert plm_quote_to_delivery_spec.name == "plm_quote_to_delivery"
        assert callable(run_plm_quote_to_delivery)

    def test_plugin_manifest_provides_quote_to_delivery(self):
        """plugin.register() provides plm.quote-to-delivery capability."""
        from kerf_plm.plugin import register as _plugin_register
        import inspect
        src = inspect.getsource(_plugin_register)
        assert "plm.quote-to-delivery" in src


# ---------------------------------------------------------------------------
# 3. transition — valid QUOTED → QUOTE_ACCEPTED
# ---------------------------------------------------------------------------

class TestTransitionValid:
    def test_quoted_to_quote_accepted(self):
        args = {
            "operation":    "transition",
            "job":          _seed_job(),
            "new_status":   "quote_accepted",
            "actor":        "mgr_alice",
            "notes":        "PO confirmed",
            "timestamp_iso":"2026-06-02T10:00:00Z",
        }
        result = _call(args)
        assert result.get("ok") is True
        job = result["job"]
        assert job["current_status"] == "quote_accepted"
        assert len(job["history"]) == 2
        assert job["history"][-1]["actor"] == "mgr_alice"
        assert job["history"][-1]["notes"] == "PO confirmed"

    def test_history_grows_by_one(self):
        args = {
            "operation":  "transition",
            "job":        _seed_job(),
            "new_status": "quote_accepted",
            "actor":      "test",
        }
        result = _call(args)
        assert len(result["job"]["history"]) == 2


# ---------------------------------------------------------------------------
# 4. transition — invalid → INVALID_TRANSITION
# ---------------------------------------------------------------------------

class TestTransitionInvalid:
    def test_skip_to_shipped(self):
        args = {
            "operation":  "transition",
            "job":        _seed_job(),
            "new_status": "shipped",
            "actor":      "admin",
        }
        result = _call(args)
        assert result.get("code") == "INVALID_TRANSITION"
        assert "error" in result

    def test_design_to_sampling_invalid(self):
        job = _seed_job(
            current_status="design",
            history=[
                {"status": "quoted",         "timestamp_iso": "2026-06-01T08:00:00Z", "actor": "s", "notes": ""},
                {"status": "quote_accepted", "timestamp_iso": "2026-06-02T08:00:00Z", "actor": "s", "notes": ""},
                {"status": "design",         "timestamp_iso": "2026-06-03T08:00:00Z", "actor": "s", "notes": ""},
            ],
        )
        args = {
            "operation":  "transition",
            "job":        job,
            "new_status": "sampling",  # not directly valid
            "actor":      "eng",
        }
        result = _call(args)
        assert result.get("code") == "INVALID_TRANSITION"


# ---------------------------------------------------------------------------
# 5. unknown operation → BAD_ARGS
# ---------------------------------------------------------------------------

def test_unknown_operation():
    result = _call({"operation": "fly_to_moon"})
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 6. missing new_status for transition → BAD_ARGS
# ---------------------------------------------------------------------------

def test_transition_missing_new_status():
    args = {
        "operation": "transition",
        "job":       _seed_job(),
        # no new_status
        "actor":     "test",
    }
    result = _call(args)
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 7. bad JSON → BAD_ARGS
# ---------------------------------------------------------------------------

def test_bad_json_args():
    raw = _run(run_plm_quote_to_delivery(CTX, b"{bad json"))
    result = json.loads(raw)
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 8. status_report — by_status + overdue_count
# ---------------------------------------------------------------------------

class TestStatusReport:
    def test_basic_report(self):
        jobs = [_seed_job("J1"), _seed_job("J2", current_status="design",
            history=[
                {"status": "quoted",         "timestamp_iso": "2026-06-01T08:00:00Z", "actor": "s", "notes": ""},
                {"status": "quote_accepted", "timestamp_iso": "2026-06-02T08:00:00Z", "actor": "s", "notes": ""},
                {"status": "design",         "timestamp_iso": "2026-06-03T08:00:00Z", "actor": "s", "notes": ""},
            ])]
        result = _call({"operation": "status_report", "jobs": jobs})
        assert result.get("ok") is True
        assert result["by_status"]["quoted"] == 1
        assert result["by_status"]["design"] == 1

    def test_overdue_count_flagged(self):
        overdue_job = _seed_job("OD", current_status="design",
            promised="2020-01-01",
            history=[
                {"status": "quoted",         "timestamp_iso": "2019-12-01T08:00:00Z", "actor": "s", "notes": ""},
                {"status": "quote_accepted", "timestamp_iso": "2019-12-05T08:00:00Z", "actor": "s", "notes": ""},
                {"status": "design",         "timestamp_iso": "2019-12-10T08:00:00Z", "actor": "s", "notes": ""},
            ],
        )
        # set is_overdue manually so it's counted
        overdue_job["is_overdue"] = True
        result = _call({"operation": "status_report", "jobs": [overdue_job]})
        assert result.get("ok") is True
        assert result["overdue_count"] == 1

    def test_empty_jobs_list(self):
        result = _call({"operation": "status_report", "jobs": []})
        assert result.get("ok") is True
        assert result["overdue_count"] == 0

    def test_status_report_missing_jobs_returns_error(self):
        result = _call({"operation": "status_report"})
        assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 9. on_time_rate — rate in [0, 1]
# ---------------------------------------------------------------------------

def test_on_time_rate_range():
    result = _call({"operation": "on_time_rate", "jobs": [_seed_job()]})
    assert result.get("ok") is True
    assert 0.0 <= result["on_time_delivery_rate"] <= 1.0


# ---------------------------------------------------------------------------
# 10. on_time_rate — 1.0 for on-time job
# ---------------------------------------------------------------------------

def test_on_time_rate_on_time():
    delivered_job = _seed_job(
        current_status="delivered",
        promised="2026-07-01",
        history=[
            {"status": "quoted",         "timestamp_iso": "2026-06-01T08:00:00Z", "actor": "s", "notes": ""},
            {"status": "quote_accepted", "timestamp_iso": "2026-06-02T08:00:00Z", "actor": "s", "notes": ""},
            {"status": "design",         "timestamp_iso": "2026-06-05T08:00:00Z", "actor": "s", "notes": ""},
            {"status": "mold_making",    "timestamp_iso": "2026-06-10T08:00:00Z", "actor": "s", "notes": ""},
            {"status": "sampling",       "timestamp_iso": "2026-06-15T08:00:00Z", "actor": "s", "notes": ""},
            {"status": "production",     "timestamp_iso": "2026-06-20T08:00:00Z", "actor": "s", "notes": ""},
            {"status": "shipped",        "timestamp_iso": "2026-06-25T08:00:00Z", "actor": "s", "notes": ""},
            {"status": "delivered",      "timestamp_iso": "2026-06-28T08:00:00Z", "actor": "s", "notes": ""},
        ],
    )
    result = _call({"operation": "on_time_rate", "jobs": [delivered_job]})
    assert result.get("ok") is True
    assert result["on_time_delivery_rate"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 11. on_time_rate — 0.0 for late job
# ---------------------------------------------------------------------------

def test_on_time_rate_late():
    late_job = _seed_job(
        current_status="delivered",
        promised="2025-04-01",
        history=[
            {"status": "quoted",    "timestamp_iso": "2025-01-01T08:00:00Z", "actor": "s", "notes": ""},
            {"status": "delivered", "timestamp_iso": "2025-06-01T08:00:00Z", "actor": "s", "notes": ""},
        ],
    )
    result = _call({"operation": "on_time_rate", "jobs": [late_job]})
    assert result.get("ok") is True
    assert result["on_time_delivery_rate"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 12. Full walk-through QUOTED → INVOICED via tool
# ---------------------------------------------------------------------------

def test_full_workflow_via_tool():
    steps = [
        ("quote_accepted", "2026-06-02T08:00:00Z"),
        ("design",         "2026-06-05T08:00:00Z"),
        ("mold_making",    "2026-06-10T08:00:00Z"),
        ("sampling",       "2026-06-20T08:00:00Z"),
        ("production",     "2026-06-25T08:00:00Z"),
        ("shipped",        "2026-07-01T08:00:00Z"),
        ("delivered",      "2026-07-03T08:00:00Z"),
        ("invoiced",       "2026-07-05T08:00:00Z"),
    ]
    job = _seed_job()
    for new_status, ts in steps:
        result = _call({
            "operation":    "transition",
            "job":          job,
            "new_status":   new_status,
            "actor":        "system",
            "timestamp_iso": ts,
        })
        assert result.get("ok") is True, f"Failed at {new_status}: {result}"
        job = result["job"]

    assert job["current_status"] == "invoiced"
    assert len(job["history"]) == 9  # 1 initial + 8 steps
