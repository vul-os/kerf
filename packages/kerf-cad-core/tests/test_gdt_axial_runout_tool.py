"""
Tests for the gdt_check_axial_runout LLM tool wrapper.

Covers:
  - Basic compliance and non-compliance
  - BAD_ARGS cases (missing fields, bad types)
  - FOM calculation
  - Tool registration (when registry is available)

Pure-Python, hermetic — no OCC, no DB, no network.
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.gdt.runout_check import (
    AxialRunoutMeasurement,
    check_axial_runout,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _make_flat_face_measurements(n: int = 8, z: float = 0.0):
    """Return n measurements on a perfectly flat face at z."""
    return [
        AxialRunoutMeasurement(
            angular_position_deg=i * (360.0 / n),
            radial_position_mm=10.0,
            axial_z_mm=z,
        )
        for i in range(n)
    ]


def _make_wavy_face_measurements(amplitude_mm: float = 0.05, n: int = 12):
    """Return n measurements with sinusoidal axial z waviness."""
    measurements = []
    for i in range(n):
        angle = i * (360.0 / n)
        z = amplitude_mm * math.sin(math.radians(angle))
        measurements.append(
            AxialRunoutMeasurement(
                angular_position_deg=angle,
                radial_position_mm=10.0,
                axial_z_mm=z,
            )
        )
    return measurements


# ---------------------------------------------------------------------------
# Python function tests (check_axial_runout)
# ---------------------------------------------------------------------------

class TestCheckAxialRunout:
    def test_flat_face_compliant(self):
        """Flat face (all z equal) → axial FIM = 0, always compliant."""
        measurements = _make_flat_face_measurements(n=8, z=5.0)
        report = check_axial_runout(measurements, tolerance_mm=0.01)
        assert report.axial_fim_mm == pytest.approx(0.0, abs=1e-9)
        assert report.compliant is True
        assert report.fom == pytest.approx(0.0, abs=1e-9)

    def test_wavy_face_compliant(self):
        """Sinusoidal z of amplitude 0.03mm → FIM ≈ 0.06mm; compliant against 0.1mm."""
        measurements = _make_wavy_face_measurements(amplitude_mm=0.03, n=36)
        report = check_axial_runout(measurements, tolerance_mm=0.1)
        assert report.axial_fim_mm == pytest.approx(0.06, abs=0.005)
        assert report.compliant is True
        assert report.fom < 1.0

    def test_wavy_face_non_compliant(self):
        """Sinusoidal z of amplitude 0.08mm → FIM ≈ 0.16mm; fails 0.1mm tolerance."""
        measurements = _make_wavy_face_measurements(amplitude_mm=0.08, n=36)
        report = check_axial_runout(measurements, tolerance_mm=0.1)
        assert report.axial_fim_mm > 0.1
        assert report.compliant is False
        assert report.fom > 1.0

    def test_fom_formula(self):
        """fom = axial_fim_mm / tolerance_mm."""
        measurements = _make_wavy_face_measurements(amplitude_mm=0.05, n=36)
        tol = 0.2
        report = check_axial_runout(measurements, tolerance_mm=tol)
        expected_fom = report.axial_fim_mm / tol
        assert report.fom == pytest.approx(expected_fom, rel=1e-6)

    def test_datum_axis_id_stored(self):
        """datum_axis_id is stored uppercase in the report."""
        measurements = _make_flat_face_measurements(n=4)
        report = check_axial_runout(measurements, tolerance_mm=0.05, datum_axis_id="b")
        assert report.datum_axis_id == "B"

    def test_n_points_stored(self):
        """n_points matches the number of measurements."""
        n = 16
        measurements = _make_flat_face_measurements(n=n)
        report = check_axial_runout(measurements, tolerance_mm=0.1)
        assert report.n_points == n

    def test_to_dict_has_required_keys(self):
        """to_dict() exposes all expected fields."""
        measurements = _make_flat_face_measurements(n=4)
        report = check_axial_runout(measurements, tolerance_mm=0.05)
        d = report.to_dict()
        for key in ("axial_fim_mm", "z_max_mm", "z_min_mm", "fom", "compliant",
                    "n_points", "datum_axis_id", "honest_caveat"):
            assert key in d, f"Missing key '{key}' in to_dict()"

    def test_raises_empty_measurements(self):
        with pytest.raises(ValueError, match="must not be empty"):
            check_axial_runout([], tolerance_mm=0.1)

    def test_raises_single_measurement(self):
        with pytest.raises(ValueError, match="need at least 2"):
            m = _make_flat_face_measurements(n=1)
            check_axial_runout(m, tolerance_mm=0.1)

    def test_raises_zero_tolerance(self):
        with pytest.raises(ValueError, match="must be > 0"):
            check_axial_runout(_make_flat_face_measurements(), tolerance_mm=0.0)

    def test_raises_negative_tolerance(self):
        with pytest.raises(ValueError, match="must be > 0"):
            check_axial_runout(_make_flat_face_measurements(), tolerance_mm=-0.1)


# ---------------------------------------------------------------------------
# LLM tool wrapper tests (run_gdt_check_axial_runout)
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.gdt.runout_check import run_gdt_check_axial_runout
    _TOOL_AVAILABLE = True
except ImportError:
    _TOOL_AVAILABLE = False


def _make_ctx():
    """Return a minimal fake ProjectCtx."""
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import uuid
    return ProjectCtx(
        pool=None,
        storage=None,
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert "error" not in d, f"Expected success payload, got: {d}"
    return d.get("result", d)


def _err(raw: str) -> dict:
    d = json.loads(raw)
    assert "error" in d, f"Expected error payload, got: {d}"
    return d


def _measurements_list(amplitude=0.0, n=8):
    return [
        {
            "angular_position_deg": i * (360.0 / n),
            "radial_position_mm": 10.0,
            "axial_z_mm": amplitude * math.sin(math.radians(i * (360.0 / n))),
        }
        for i in range(n)
    ]


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat registry not available")
class TestRunGdtCheckAxialRunoutTool:
    def test_flat_face_pass(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.1,
            "measurements": _measurements_list(amplitude=0.0, n=8),
        }).encode()
        result = _ok(_run(run_gdt_check_axial_runout(ctx, args)))
        assert result["compliant"] is True
        assert result["axial_fim_mm"] == pytest.approx(0.0, abs=1e-9)

    def test_wavy_face_compliant(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.1,
            "measurements": _measurements_list(amplitude=0.03, n=36),
        }).encode()
        result = _ok(_run(run_gdt_check_axial_runout(ctx, args)))
        assert result["compliant"] is True
        assert result["fom"] < 1.0

    def test_wavy_face_non_compliant(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.05,
            "measurements": _measurements_list(amplitude=0.08, n=36),
        }).encode()
        result = _ok(_run(run_gdt_check_axial_runout(ctx, args)))
        assert result["compliant"] is False
        assert result["fom"] > 1.0

    def test_datum_axis_id_default(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.1,
            "measurements": _measurements_list(n=4),
        }).encode()
        result = _ok(_run(run_gdt_check_axial_runout(ctx, args)))
        assert result["datum_axis_id"] == "A"

    def test_datum_axis_id_custom(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.1,
            "datum_axis_id": "c",
            "measurements": _measurements_list(n=4),
        }).encode()
        result = _ok(_run(run_gdt_check_axial_runout(ctx, args)))
        assert result["datum_axis_id"] == "C"

    def test_missing_tolerance_mm(self):
        ctx = _make_ctx()
        args = json.dumps({
            "measurements": _measurements_list(n=4),
        }).encode()
        err = _err(_run(run_gdt_check_axial_runout(ctx, args)))
        assert err["code"] == "BAD_ARGS"

    def test_missing_measurements(self):
        ctx = _make_ctx()
        args = json.dumps({"tolerance_mm": 0.1}).encode()
        err = _err(_run(run_gdt_check_axial_runout(ctx, args)))
        assert err["code"] == "BAD_ARGS"

    def test_measurements_not_array(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.1,
            "measurements": "not-an-array",
        }).encode()
        err = _err(_run(run_gdt_check_axial_runout(ctx, args)))
        assert err["code"] == "BAD_ARGS"

    def test_bad_json(self):
        ctx = _make_ctx()
        err = _err(_run(run_gdt_check_axial_runout(ctx, b"not json")))
        assert err["code"] == "BAD_ARGS"

    def test_single_measurement_bad_args(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.1,
            "measurements": [_measurements_list(n=1)[0]],
        }).encode()
        err = _err(_run(run_gdt_check_axial_runout(ctx, args)))
        assert err["code"] == "BAD_ARGS"

    def test_zero_tolerance_bad_args(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.0,
            "measurements": _measurements_list(n=4),
        }).encode()
        err = _err(_run(run_gdt_check_axial_runout(ctx, args)))
        assert err["code"] == "BAD_ARGS"

    def test_result_has_all_keys(self):
        ctx = _make_ctx()
        args = json.dumps({
            "tolerance_mm": 0.1,
            "measurements": _measurements_list(n=8),
        }).encode()
        result = _ok(_run(run_gdt_check_axial_runout(ctx, args)))
        for key in ("axial_fim_mm", "z_max_mm", "z_min_mm", "fom", "compliant",
                    "n_points", "datum_axis_id", "honest_caveat"):
            assert key in result, f"Missing key '{key}' in result"
