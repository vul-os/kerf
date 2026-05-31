"""
Hermetic tests for kerf_cad_core.optics.piston_tip_tilt —
Wavefront alignment analysis: piston (Z₁), tip (Z₂), tilt (Z₃), defocus (Z₄).

Coverage (≥ 12 tests):
  1.  Pure piston W=10nm @ λ=632.8nm → piston_waves ≈ 0.01580 (10/632.8)
  2.  Pure piston dominant_misalignment = "piston"
  3.  Pure tip W=ρ cosθ (scaled) → tip detected as dominant
  4.  Pure tilt W=ρ sinθ (scaled) → tilt detected as dominant
  5.  Pure defocus W ∝ (2ρ²−1) → defocus dominant
  6.  Combined tip+tilt+defocus → all three reported in report
  7.  Zero wavefront → dominant = "none", all coefficients near zero
  8.  Small wavefront below 0.001 wave threshold → dominant = "none"
  9.  wavelength_nm <= 0 → ValueError
  10. fewer than 4 samples → ValueError
  11. to_dict() returns expected keys and ok=True
  12. residual_rms_waves is zero (or near zero) for exact 4-term wavefront
  13. analyze_wavefront_alignment import from optics/__init__.py works
  14. LLM tool happy path: optics_analyze_wavefront_alignment returns ok=True
  15. LLM tool bad args: missing samples → ok=False
  16. LLM tool bad args: missing wavelength_nm → ok=False

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified against Hecht "Optics" 5th ed. §11.3,
Born & Wolf §9.2, Noll (1976) J. Opt. Soc. Am. 66 207.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import numpy as np
import pytest

from kerf_cad_core.optics.piston_tip_tilt import (
    PistonTipTiltReport,
    analyze_wavefront_alignment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grid_samples(
    n_rings: int = 8,
    n_per_ring: int = 16,
) -> list[tuple[float, float]]:
    """Generate (rho, theta) samples over the unit disk on a polar grid."""
    pts: list[tuple[float, float]] = []
    # Add centre point
    pts.append((0.0, 0.0))
    for r in range(1, n_rings + 1):
        rho = r / n_rings
        for k in range(n_per_ring):
            theta = 2.0 * math.pi * k / n_per_ring
            pts.append((rho, theta))
    return pts


def _make_pure_piston(W_nm: float) -> list[tuple[float, float, float]]:
    """W = W_nm (constant across pupil) — pure piston."""
    pts = _grid_samples()
    return [(rho, theta, W_nm) for rho, theta in pts]


def _make_pure_tip(amp_nm: float) -> list[tuple[float, float, float]]:
    """W = amp_nm * (rho * cos theta) — sampled tip (not normalised Noll Z₂)."""
    pts = _grid_samples()
    return [(rho, theta, amp_nm * rho * math.cos(theta)) for rho, theta in pts]


def _make_pure_tilt(amp_nm: float) -> list[tuple[float, float, float]]:
    """W = amp_nm * (rho * sin theta) — sampled tilt (not normalised Noll Z₃)."""
    pts = _grid_samples()
    return [(rho, theta, amp_nm * rho * math.sin(theta)) for rho, theta in pts]


def _make_pure_defocus(amp_nm: float) -> list[tuple[float, float, float]]:
    """W = amp_nm * (2*rho^2 - 1) — sampled defocus (un-normalised Z₄ form)."""
    pts = _grid_samples()
    return [(rho, theta, amp_nm * (2.0 * rho ** 2 - 1.0)) for rho, theta in pts]


def _make_noll_z2(amp_nm: float) -> list[tuple[float, float, float]]:
    """W = amp_nm * Z₂ = amp_nm * 2ρ cosθ — exact Noll tip."""
    pts = _grid_samples()
    return [(rho, theta, amp_nm * 2.0 * rho * math.cos(theta)) for rho, theta in pts]


def _make_noll_z3(amp_nm: float) -> list[tuple[float, float, float]]:
    """W = amp_nm * Z₃ = amp_nm * 2ρ sinθ — exact Noll tilt."""
    pts = _grid_samples()
    return [(rho, theta, amp_nm * 2.0 * rho * math.sin(theta)) for rho, theta in pts]


def _make_noll_z4(amp_nm: float) -> list[tuple[float, float, float]]:
    """W = amp_nm * Z₄ = amp_nm * √3 (2ρ²−1) — exact Noll defocus."""
    sqrt3 = math.sqrt(3.0)
    pts = _grid_samples()
    return [(rho, theta, amp_nm * sqrt3 * (2.0 * rho ** 2 - 1.0)) for rho, theta in pts]


def _make_combined(tip_nm: float, tilt_nm: float, defocus_nm: float) -> list[tuple[float, float, float]]:
    """W = tip_nm*Z₂ + tilt_nm*Z₃ + defocus_nm*Z₄  (no piston)."""
    sqrt3 = math.sqrt(3.0)
    pts = _grid_samples()
    samples = []
    for rho, theta in pts:
        z2 = 2.0 * rho * math.cos(theta)
        z3 = 2.0 * rho * math.sin(theta)
        z4 = sqrt3 * (2.0 * rho ** 2 - 1.0)
        w = tip_nm * z2 + tilt_nm * z3 + defocus_nm * z4
        samples.append((rho, theta, w))
    return samples


# ---------------------------------------------------------------------------
# Test: pure piston
# ---------------------------------------------------------------------------

class TestPurePiston:
    """Flat wavefront W = 10 nm at HeNe λ=632.8 nm."""

    _LAMBDA = 632.8  # nm, HeNe laser
    _W_NM = 10.0

    def _report(self) -> PistonTipTiltReport:
        samples = _make_pure_piston(self._W_NM)
        return analyze_wavefront_alignment(samples, self._LAMBDA)

    def test_piston_waves_value(self):
        r = self._report()
        expected = self._W_NM / self._LAMBDA  # ≈ 0.015803
        assert abs(r.piston_waves - expected) < 1e-6, (
            f"Expected piston_waves ≈ {expected:.6f}, got {r.piston_waves:.6f}"
        )

    def test_tip_waves_near_zero(self):
        r = self._report()
        assert abs(r.tip_waves) < 1e-8

    def test_tilt_waves_near_zero(self):
        r = self._report()
        assert abs(r.tilt_waves) < 1e-8

    def test_defocus_waves_near_zero(self):
        r = self._report()
        assert abs(r.defocus_waves) < 1e-8

    def test_dominant_is_piston(self):
        r = self._report()
        assert r.dominant_misalignment == "piston"

    def test_residual_near_zero(self):
        """Pure piston is exactly representable in Z₁, so residual ≈ 0."""
        r = self._report()
        assert r.residual_rms_waves < 1e-10


# ---------------------------------------------------------------------------
# Test: pure tip (exact Noll Z₂)
# ---------------------------------------------------------------------------

class TestPureTip:
    _LAMBDA = 550.0
    _AMP_NM = 100.0  # 100nm tip amplitude

    def _report(self) -> PistonTipTiltReport:
        samples = _make_noll_z2(self._AMP_NM)
        return analyze_wavefront_alignment(samples, self._LAMBDA)

    def test_tip_dominant(self):
        r = self._report()
        assert r.dominant_misalignment == "tip"

    def test_tip_waves_correct(self):
        r = self._report()
        expected_tip = self._AMP_NM / self._LAMBDA  # Z₂ coefficient = amp_nm
        assert abs(r.tip_waves - expected_tip) < 1e-6

    def test_tilt_near_zero(self):
        r = self._report()
        assert abs(r.tilt_waves) < 1e-8

    def test_defocus_near_zero(self):
        r = self._report()
        assert abs(r.defocus_waves) < 1e-8

    def test_residual_near_zero(self):
        r = self._report()
        assert r.residual_rms_waves < 1e-10


# ---------------------------------------------------------------------------
# Test: pure tilt (exact Noll Z₃)
# ---------------------------------------------------------------------------

class TestPureTilt:
    _LAMBDA = 550.0
    _AMP_NM = 80.0

    def _report(self) -> PistonTipTiltReport:
        samples = _make_noll_z3(self._AMP_NM)
        return analyze_wavefront_alignment(samples, self._LAMBDA)

    def test_tilt_dominant(self):
        r = self._report()
        assert r.dominant_misalignment == "tilt"

    def test_tilt_waves_correct(self):
        r = self._report()
        expected_tilt = self._AMP_NM / self._LAMBDA
        assert abs(r.tilt_waves - expected_tilt) < 1e-6

    def test_tip_near_zero(self):
        r = self._report()
        assert abs(r.tip_waves) < 1e-8

    def test_residual_near_zero(self):
        r = self._report()
        assert r.residual_rms_waves < 1e-10


# ---------------------------------------------------------------------------
# Test: pure defocus (exact Noll Z₄)
# ---------------------------------------------------------------------------

class TestPureDefocus:
    _LAMBDA = 632.8
    _AMP_NM = 316.4  # half-wave defocus

    def _report(self) -> PistonTipTiltReport:
        samples = _make_noll_z4(self._AMP_NM)
        return analyze_wavefront_alignment(samples, self._LAMBDA)

    def test_defocus_dominant(self):
        r = self._report()
        assert r.dominant_misalignment == "defocus"

    def test_defocus_waves_correct(self):
        r = self._report()
        expected = self._AMP_NM / self._LAMBDA  # ≈ 0.5 waves
        assert abs(r.defocus_waves - expected) < 1e-6

    def test_tip_tilt_near_zero(self):
        r = self._report()
        assert abs(r.tip_waves) < 1e-8
        assert abs(r.tilt_waves) < 1e-8

    def test_residual_near_zero(self):
        r = self._report()
        assert r.residual_rms_waves < 1e-10


# ---------------------------------------------------------------------------
# Test: combined tip + tilt + defocus (misalignment scenario)
# ---------------------------------------------------------------------------

class TestCombined:
    _LAMBDA = 632.8
    # Three terms simultaneously present
    _TIP_NM = 50.0
    _TILT_NM = 80.0
    _DEFOCUS_NM = 120.0  # largest → dominant

    def _report(self) -> PistonTipTiltReport:
        samples = _make_combined(self._TIP_NM, self._TILT_NM, self._DEFOCUS_NM)
        return analyze_wavefront_alignment(samples, self._LAMBDA)

    def test_tip_nonzero(self):
        r = self._report()
        assert abs(r.tip_waves) > 0.001

    def test_tilt_nonzero(self):
        r = self._report()
        assert abs(r.tilt_waves) > 0.001

    def test_defocus_nonzero(self):
        r = self._report()
        assert abs(r.defocus_waves) > 0.001

    def test_defocus_dominant(self):
        """defocus_nm=120 > tilt_nm=80 > tip_nm=50 → defocus dominant."""
        r = self._report()
        assert r.dominant_misalignment == "defocus"

    def test_tip_waves_correct(self):
        r = self._report()
        expected = self._TIP_NM / self._LAMBDA
        assert abs(r.tip_waves - expected) < 1e-6

    def test_tilt_waves_correct(self):
        r = self._report()
        expected = self._TILT_NM / self._LAMBDA
        assert abs(r.tilt_waves - expected) < 1e-6

    def test_defocus_waves_correct(self):
        r = self._report()
        expected = self._DEFOCUS_NM / self._LAMBDA
        assert abs(r.defocus_waves - expected) < 1e-6

    def test_residual_near_zero(self):
        """Exact 4-term wavefront → residual ≈ 0 in 4-term fit."""
        r = self._report()
        assert r.residual_rms_waves < 1e-10


# ---------------------------------------------------------------------------
# Test: zero (flat) wavefront
# ---------------------------------------------------------------------------

class TestZeroWavefront:
    def test_dominant_none(self):
        samples = [(rho, theta, 0.0) for rho, theta in _grid_samples()]
        r = analyze_wavefront_alignment(samples, 632.8)
        assert r.dominant_misalignment == "none"

    def test_all_waves_zero(self):
        samples = [(rho, theta, 0.0) for rho, theta in _grid_samples()]
        r = analyze_wavefront_alignment(samples, 632.8)
        assert r.piston_waves == pytest.approx(0.0, abs=1e-12)
        assert r.tip_waves == pytest.approx(0.0, abs=1e-12)
        assert r.tilt_waves == pytest.approx(0.0, abs=1e-12)
        assert r.defocus_waves == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Test: below threshold → "none"
# ---------------------------------------------------------------------------

class TestBelowThreshold:
    """Wavefront so small that all |coefficients| < 0.001 waves."""

    def test_dominant_none_for_tiny_wavefront(self):
        # 0.5 nm piston at λ=632.8 nm → 0.00079 waves < 0.001 threshold
        samples = _make_pure_piston(0.5)
        r = analyze_wavefront_alignment(samples, 632.8)
        # 0.5 / 632.8 ≈ 0.00079 — below 0.001 wave threshold
        assert r.dominant_misalignment == "none"


# ---------------------------------------------------------------------------
# Test: error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_negative_wavelength_raises(self):
        samples = _make_pure_piston(10.0)
        with pytest.raises(ValueError, match="wavelength_nm"):
            analyze_wavefront_alignment(samples, -1.0)

    def test_zero_wavelength_raises(self):
        samples = _make_pure_piston(10.0)
        with pytest.raises(ValueError, match="wavelength_nm"):
            analyze_wavefront_alignment(samples, 0.0)

    def test_too_few_samples_raises(self):
        # Only 3 samples — under-determined for 4-term fit
        samples = [(0.5, 0.0, 5.0), (0.5, math.pi / 2, 5.0), (0.5, math.pi, 5.0)]
        with pytest.raises(ValueError, match="Under-determined"):
            analyze_wavefront_alignment(samples, 632.8)

    def test_exactly_four_samples_ok(self):
        # Minimum viable: 4 samples
        samples = [
            (0.5, 0.0, 10.0),
            (0.5, math.pi / 2, 10.0),
            (0.5, math.pi, 10.0),
            (0.5, 3 * math.pi / 2, 10.0),
        ]
        r = analyze_wavefront_alignment(samples, 632.8)
        assert isinstance(r, PistonTipTiltReport)


# ---------------------------------------------------------------------------
# Test: to_dict() output
# ---------------------------------------------------------------------------

class TestToDict:
    def test_to_dict_has_required_keys(self):
        samples = _make_pure_piston(10.0)
        r = analyze_wavefront_alignment(samples, 632.8)
        d = r.to_dict()
        for key in (
            "ok", "piston_waves", "tip_waves", "tilt_waves", "defocus_waves",
            "residual_rms_waves", "dominant_misalignment", "honest_caveat",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_ok_is_true(self):
        samples = _make_pure_piston(10.0)
        r = analyze_wavefront_alignment(samples, 632.8)
        assert r.to_dict()["ok"] is True

    def test_honest_caveat_not_empty(self):
        samples = _make_pure_piston(10.0)
        r = analyze_wavefront_alignment(samples, 632.8)
        assert len(r.honest_caveat) > 50


# ---------------------------------------------------------------------------
# Test: import from optics/__init__.py
# ---------------------------------------------------------------------------

class TestPublicImport:
    def test_re_export_from_init(self):
        from kerf_cad_core.optics import (  # noqa: PLC0415
            PistonTipTiltReport,
            analyze_wavefront_alignment,
        )
        assert PistonTipTiltReport is not None
        assert callable(analyze_wavefront_alignment)


# ---------------------------------------------------------------------------
# Test: residual from higher-order content
# ---------------------------------------------------------------------------

class TestHigherOrderResidual:
    """A wavefront with Z₅ (astigmatism) leaves a non-zero residual in 4-term fit."""

    def test_residual_nonzero_for_higher_order(self):
        # Add some Z₅ content: Z₅ = √6 ρ² sin(2θ)
        sqrt6 = math.sqrt(6.0)
        pts = _grid_samples(n_rings=12, n_per_ring=24)
        amp_astig_nm = 50.0
        samples = [
            (rho, theta, amp_astig_nm * sqrt6 * rho ** 2 * math.sin(2.0 * theta))
            for rho, theta in pts
        ]
        r = analyze_wavefront_alignment(samples, 632.8)
        # Residual must be measurably non-zero (Z₅ not captured by first 4 terms)
        assert r.residual_rms_waves > 0.001


# ---------------------------------------------------------------------------
# Test: LLM tool wrapper
# ---------------------------------------------------------------------------

def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # noqa: PLC0415
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


class TestLLMTool:
    """Test the optics_analyze_wavefront_alignment LLM tool handler."""

    def _run(self, args: dict) -> dict:
        from kerf_cad_core.optics.tools import run_wavefront_alignment  # noqa: PLC0415
        ctx = _ctx()
        raw = asyncio.get_event_loop().run_until_complete(
            run_wavefront_alignment(ctx, json.dumps(args).encode())
        )
        return json.loads(raw)

    def _samples_list(self) -> list:
        pts = _grid_samples(n_rings=4, n_per_ring=12)
        return [[rho, theta, 10.0] for rho, theta in pts]

    def test_happy_path_ok(self):
        result = self._run({
            "samples": self._samples_list(),
            "wavelength_nm": 632.8,
        })
        assert result["ok"] is True
        assert "piston_waves" in result
        assert "tip_waves" in result
        assert "tilt_waves" in result
        assert "defocus_waves" in result
        assert "dominant_misalignment" in result

    def test_missing_samples_returns_error(self):
        result = self._run({"wavelength_nm": 632.8})
        assert result["ok"] is False

    def test_missing_wavelength_returns_error(self):
        result = self._run({"samples": self._samples_list()})
        assert result["ok"] is False

    def test_negative_wavelength_returns_error(self):
        result = self._run({
            "samples": self._samples_list(),
            "wavelength_nm": -1.0,
        })
        assert result["ok"] is False

    def test_too_few_samples_returns_error(self):
        result = self._run({
            "samples": [[0.5, 0.0, 10.0], [0.5, 1.0, 10.0]],
            "wavelength_nm": 632.8,
        })
        assert result["ok"] is False

    def test_pure_piston_tool_result(self):
        """10nm piston at λ=632.8nm should give piston_waves ≈ 0.01580."""
        pts = _grid_samples(n_rings=6, n_per_ring=18)
        samples = [[rho, theta, 10.0] for rho, theta in pts]
        result = self._run({"samples": samples, "wavelength_nm": 632.8})
        assert result["ok"] is True
        expected = 10.0 / 632.8
        assert abs(result["piston_waves"] - expected) < 1e-6
        assert result["dominant_misalignment"] == "piston"
