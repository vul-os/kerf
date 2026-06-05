"""
Test suite for 5-axis route wiring in kerf_cam.routes.

Tests verify that _run_5axis_finish_route and _run_3plus2_route:
  A  Return proper error dict (not an exception) when OCC is absent.
  B  Return dict with the required keys: output_key, gcode_b64, toolpath_length,
     estimated_time, warnings, errors.
  C  With synthetic STEP-like content, return a structured response.
  D  Invalid/corrupt step bytes → errors list is non-empty (not a crash).
  E  5axis_finish signature accepts step_bytes argument.
  F  3plus2 signature accepts step_bytes argument.
"""

from __future__ import annotations

import base64
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

# Probe OCC availability.
_has_occ = False
try:
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: F401
    _has_occ = True
except ImportError:
    pass

requires_occ = pytest.mark.skipif(not _has_occ, reason="pythonOCC not installed")
requires_no_occ = pytest.mark.skipif(_has_occ, reason="test is for no-OCC path only")


# ---------------------------------------------------------------------------
# Required result keys
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = frozenset({"output_key", "gcode_b64", "toolpath_length", "estimated_time", "warnings", "errors"})


def _check_result_shape(result: dict) -> None:
    """Assert that *result* has all required 5-axis response keys."""
    for k in _REQUIRED_KEYS:
        assert k in result, f"Missing key {k!r} in route result: {result!r}"
    assert isinstance(result["warnings"], list), "warnings should be a list"
    assert isinstance(result["errors"], list), "errors should be a list"
    # gcode_b64 must be valid base64
    try:
        base64.b64decode(result["gcode_b64"])
    except Exception as e:
        pytest.fail(f"gcode_b64 is not valid base64: {e}")


# ---------------------------------------------------------------------------
# Test A / B — no-OCC path returns structured error
# ---------------------------------------------------------------------------

@requires_no_occ
def test_5axis_finish_no_occ_returns_structured_result():
    """When OCC is absent, _run_5axis_finish_route must return a dict with required keys."""
    from kerf_cam.routes import _run_5axis_finish_route, CAMOperation

    op = CAMOperation(
        type="5axis_finish",
        tool_diameter=6.0,
        step_over=2.0,
        step_down=1.0,
        feed_rate=800.0,
        spindle_rpm=12000,
        drive_face_id=0,
        tilt_deg=15.0,
    )
    result = _run_5axis_finish_route(op, b"fake step bytes")
    _check_result_shape(result)
    # Without OCC, errors should be non-empty
    assert len(result["errors"]) > 0, "Expected errors when OCC absent"


@requires_no_occ
def test_3plus2_no_occ_returns_structured_result():
    """When OCC is absent, _run_3plus2_route must return a dict with required keys."""
    from kerf_cam.routes import _run_3plus2_route, CAMOperation

    op = CAMOperation(
        type="3plus2",
        tool_diameter=6.0,
        step_over=2.0,
        step_down=1.0,
        feed_rate=1000.0,
        spindle_rpm=10000,
        drive_face_id=0,
    )
    result = _run_3plus2_route(op, b"fake step bytes")
    _check_result_shape(result)
    assert len(result["errors"]) > 0, "Expected errors when OCC absent"


# ---------------------------------------------------------------------------
# Test C / D — OCC available: corrupt bytes → structured error (no crash)
# ---------------------------------------------------------------------------

@requires_occ
def test_5axis_finish_corrupt_bytes_returns_error():
    """Corrupt STEP bytes should produce a structured error result (not a crash)."""
    from kerf_cam.routes import _run_5axis_finish_route, CAMOperation

    op = CAMOperation(
        type="5axis_finish",
        tool_diameter=6.0,
        step_over=2.0,
        step_down=1.0,
        feed_rate=800.0,
        spindle_rpm=12000,
        drive_face_id=0,
        tilt_deg=15.0,
    )
    result = _run_5axis_finish_route(op, b"\x00\x01\x02garbage not a STEP file")
    _check_result_shape(result)
    assert len(result["errors"]) > 0, (
        "Expected non-empty errors for corrupt STEP bytes"
    )


@requires_occ
def test_3plus2_corrupt_bytes_returns_error():
    """Corrupt STEP bytes for 3plus2 should produce a structured error result."""
    from kerf_cam.routes import _run_3plus2_route, CAMOperation

    op = CAMOperation(
        type="3plus2",
        tool_diameter=6.0,
        step_over=2.0,
        step_down=1.0,
        feed_rate=1000.0,
        spindle_rpm=10000,
        drive_face_id=0,
    )
    result = _run_3plus2_route(op, b"\x00garbage")
    _check_result_shape(result)
    assert len(result["errors"]) > 0, (
        "Expected non-empty errors for corrupt STEP bytes"
    )


# ---------------------------------------------------------------------------
# Test E / F — Signature smoke tests (pure Python)
# ---------------------------------------------------------------------------

def test_5axis_finish_route_signature():
    """_run_5axis_finish_route must accept (op, step_bytes) signature."""
    import inspect
    from kerf_cam.routes import _run_5axis_finish_route
    sig = inspect.signature(_run_5axis_finish_route)
    params = list(sig.parameters.keys())
    assert "op" in params, f"Expected 'op' param in signature: {params}"
    assert "step_bytes" in params, f"Expected 'step_bytes' param in signature: {params}"


def test_3plus2_route_signature():
    """_run_3plus2_route must accept (op, step_bytes) signature."""
    import inspect
    from kerf_cam.routes import _run_3plus2_route
    sig = inspect.signature(_run_3plus2_route)
    params = list(sig.parameters.keys())
    assert "op" in params, f"Expected 'op' param in signature: {params}"
    assert "step_bytes" in params, f"Expected 'step_bytes' param in signature: {params}"


# ---------------------------------------------------------------------------
# Test G — OCC path with a real box STEP fixture (if conftest provides it)
# ---------------------------------------------------------------------------

@requires_occ
def test_5axis_finish_real_step(step_fixture_path):
    """Full constant-tilt pipeline with a real STEP fixture returns G-code."""
    from kerf_cam.routes import _run_5axis_finish_route, CAMOperation

    step_bytes = open(step_fixture_path, "rb").read()
    op = CAMOperation(
        type="5axis_finish",
        tool_diameter=3.0,
        step_over=5.0,
        step_down=1.0,
        feed_rate=800.0,
        spindle_rpm=12000,
        drive_face_id=0,
        tilt_deg=15.0,
        post_processor_5x="linuxcnc",
    )
    result = _run_5axis_finish_route(op, step_bytes)
    _check_result_shape(result)
    # Should succeed: errors list empty
    assert len(result["errors"]) == 0, (
        f"Unexpected errors with real STEP: {result['errors']}"
    )
    # G-code should be non-empty
    gcode = base64.b64decode(result["gcode_b64"]).decode()
    assert len(gcode) > 10, "Expected non-empty G-code from 5axis_finish pipeline"
    assert "G1" in gcode, "G1 cutting moves missing from 5axis_finish G-code"
    assert "M30" in gcode, "M30 end-of-program missing from 5axis_finish G-code"
