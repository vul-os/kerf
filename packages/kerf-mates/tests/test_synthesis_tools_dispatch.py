"""
Dispatch tests for mechanism synthesis LLM tools (coverage sweep wiring).

Covers:
  synthesise_four_bar   — 4-bar linkage Burmester synthesis
  synthesise_cam        — cam-profile synthesis (cycloidal / polynomial / harmonic)
  synthesise_gear_train — ISO spur-gear train synthesis

Tests verify:
  1. ToolSpec is registered in the global registry.
  2. Happy-path dispatch returns ok=True with expected keys.
  3. Bad-args return appropriate error payload.
"""

from __future__ import annotations

import asyncio
import json
import pytest


class _FakeCtx:
    project_id = "proj-test"
    pool = None


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _registered_names():
    try:
        from kerf_chat.tools.registry import Registry
        return {t.spec.name for t in Registry}
    except ImportError:
        from kerf_mates._compat import _registry
        return {entry["spec"].name for entry in _registry}


# ===========================================================================
# synthesise_four_bar
# ===========================================================================

class TestSynthesiseFourBar:

    def test_spec_registered(self):
        import kerf_mates.synthesis_tools  # noqa: F401 — triggers @register
        assert "synthesise_four_bar" in _registered_names()

    def test_happy_path(self):
        from kerf_mates.synthesis_tools import run_synthesise_four_bar
        ctx = _FakeCtx()
        args = json.dumps({
            "points": [[10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            "max_iters": 500,
        }).encode()
        raw = _run(run_synthesise_four_bar(ctx, args))
        payload = json.loads(raw)
        assert payload.get("ok") is True, f"Expected ok=True; got {payload}"
        for key in ("r1", "r2", "r3", "r4", "px", "py", "max_error_mm", "grashof"):
            assert key in payload, f"Missing key: {key}"

    def test_wrong_point_count(self):
        from kerf_mates.synthesis_tools import run_synthesise_four_bar
        ctx = _FakeCtx()
        args = json.dumps({"points": [[0, 0], [1, 1]]}).encode()
        raw = _run(run_synthesise_four_bar(ctx, args))
        payload = json.loads(raw)
        # Returns SYNTH_ERROR (ok=False from synthesise_four_bar)
        assert payload.get("code") == "SYNTH_ERROR"

    def test_bad_json(self):
        from kerf_mates.synthesis_tools import run_synthesise_four_bar
        ctx = _FakeCtx()
        raw = _run(run_synthesise_four_bar(ctx, b"not json"))
        payload = json.loads(raw)
        assert payload.get("code") == "BAD_ARGS"

    def test_missing_points_field(self):
        from kerf_mates.synthesis_tools import run_synthesise_four_bar
        ctx = _FakeCtx()
        args = json.dumps({}).encode()
        raw = _run(run_synthesise_four_bar(ctx, args))
        payload = json.loads(raw)
        # points=None → not a list → BAD_ARGS
        assert payload.get("code") == "BAD_ARGS"


# ===========================================================================
# synthesise_cam
# ===========================================================================

class TestSynthesiseCam:

    def test_spec_registered(self):
        import kerf_mates.synthesis_tools  # noqa: F401
        assert "synthesise_cam" in _registered_names()

    def test_cycloidal_happy_path(self):
        from kerf_mates.synthesis_tools import run_synthesise_cam
        ctx = _FakeCtx()
        args = json.dumps({
            "law": "cycloidal",
            "h": 10.0,
            "beta_deg": 120.0,
            "n_points": 36,
        }).encode()
        raw = _run(run_synthesise_cam(ctx, args))
        payload = json.loads(raw)
        assert payload.get("ok") is True, f"Expected ok=True; got {payload}"
        assert "profile" in payload
        assert payload["lift_ok"] is True

    def test_polynomial_order7(self):
        from kerf_mates.synthesis_tools import run_synthesise_cam
        ctx = _FakeCtx()
        args = json.dumps({
            "law": "polynomial",
            "h": 8.0,
            "beta_deg": 90.0,
            "poly_order": 7,
            "n_points": 18,
        }).encode()
        raw = _run(run_synthesise_cam(ctx, args))
        payload = json.loads(raw)
        assert payload.get("ok") is True
        assert payload["poly_order"] == 7

    def test_harmonic_happy_path(self):
        from kerf_mates.synthesis_tools import run_synthesise_cam
        ctx = _FakeCtx()
        args = json.dumps({
            "law": "harmonic",
            "h": 5.0,
            "beta_deg": 90.0,
            "n_points": 18,
        }).encode()
        raw = _run(run_synthesise_cam(ctx, args))
        payload = json.loads(raw)
        assert payload.get("ok") is True

    def test_fall_segment(self):
        from kerf_mates.synthesis_tools import run_synthesise_cam
        ctx = _FakeCtx()
        args = json.dumps({
            "law": "cycloidal",
            "h": 10.0,
            "beta_deg": 120.0,
            "rise": False,
            "n_points": 10,
        }).encode()
        raw = _run(run_synthesise_cam(ctx, args))
        payload = json.loads(raw)
        assert payload.get("ok") is True
        # Fall: first displacement = h, last = 0
        first = payload["profile"][0]["displacement"]
        last = payload["profile"][-1]["displacement"]
        assert abs(first - 10.0) < 1e-4
        assert abs(last - 0.0) < 1e-4

    def test_invalid_law(self):
        from kerf_mates.synthesis_tools import run_synthesise_cam
        ctx = _FakeCtx()
        args = json.dumps({"law": "unknown", "h": 10.0, "beta_deg": 90.0}).encode()
        raw = _run(run_synthesise_cam(ctx, args))
        payload = json.loads(raw)
        assert payload.get("code") == "SYNTH_ERROR"

    def test_missing_law(self):
        from kerf_mates.synthesis_tools import run_synthesise_cam
        ctx = _FakeCtx()
        args = json.dumps({"h": 10.0, "beta_deg": 90.0}).encode()
        raw = _run(run_synthesise_cam(ctx, args))
        payload = json.loads(raw)
        assert payload.get("code") == "BAD_ARGS"


# ===========================================================================
# synthesise_gear_train
# ===========================================================================

class TestSynthesiseGearTrain:

    def test_spec_registered(self):
        import kerf_mates.synthesis_tools  # noqa: F401
        assert "synthesise_gear_train" in _registered_names()

    def test_happy_path_reduction(self):
        from kerf_mates.synthesis_tools import run_synthesise_gear_train
        ctx = _FakeCtx()
        args = json.dumps({"target_ratio": 4.0}).encode()
        raw = _run(run_synthesise_gear_train(ctx, args))
        payload = json.loads(raw)
        assert payload.get("ok") is True, f"Expected ok=True; got {payload}"
        assert "stage_configs" in payload
        assert payload["stages"] in (1, 2)
        for sc in payload["stage_configs"]:
            assert sc["z1"] >= 17
            assert sc["z2"] >= 17

    def test_prefer_stages_1(self):
        from kerf_mates.synthesis_tools import run_synthesise_gear_train
        ctx = _FakeCtx()
        args = json.dumps({"target_ratio": 3.0, "prefer_stages": 1}).encode()
        raw = _run(run_synthesise_gear_train(ctx, args))
        payload = json.loads(raw)
        assert payload.get("ok") is True
        assert payload["stages"] == 1

    def test_prefer_stages_2(self):
        from kerf_mates.synthesis_tools import run_synthesise_gear_train
        ctx = _FakeCtx()
        args = json.dumps({"target_ratio": 4.0, "prefer_stages": 2}).encode()
        raw = _run(run_synthesise_gear_train(ctx, args))
        payload = json.loads(raw)
        assert payload.get("ok") is True
        assert payload["stages"] == 2

    def test_missing_target_ratio(self):
        from kerf_mates.synthesis_tools import run_synthesise_gear_train
        ctx = _FakeCtx()
        args = json.dumps({}).encode()
        raw = _run(run_synthesise_gear_train(ctx, args))
        payload = json.loads(raw)
        assert payload.get("code") == "BAD_ARGS"

    def test_negative_ratio(self):
        from kerf_mates.synthesis_tools import run_synthesise_gear_train
        ctx = _FakeCtx()
        args = json.dumps({"target_ratio": -2.0}).encode()
        raw = _run(run_synthesise_gear_train(ctx, args))
        payload = json.loads(raw)
        assert payload.get("code") == "SYNTH_ERROR"

    def test_bad_json(self):
        from kerf_mates.synthesis_tools import run_synthesise_gear_train
        ctx = _FakeCtx()
        raw = _run(run_synthesise_gear_train(ctx, b"not json"))
        payload = json.loads(raw)
        assert payload.get("code") == "BAD_ARGS"
