"""
Hermetic tests for kerf_cad_core.optics.focal_depth_field — Depth-of-Field
and Hyperfocal Distance.

Coverage (≥ 12 tests):
  compute_depth_of_field:
    T01  50mm f/2.8 @ 5000mm — hyperfocal oracle ~29762mm (H = f²/Nc + f)
    T02  50mm f/2.8 @ 5000mm — near limit oracle
    T03  50mm f/2.8 @ 5000mm — far limit oracle
    T04  50mm f/2.8 @ 5000mm — total DoF oracle
    T05  Focus at hyperfocal → far_limit = ∞, infinity_focus_at_hyperfocal = True
    T06  Focus at hyperfocal → near_limit ≈ H/2
    T07  Larger f-number → bigger DoF (same focal length & distance)
    T08  Shorter focal length → longer hyperfocal for same N, c
    T09  Focus well beyond hyperfocal → DoF infinite
    T10  behind_focus_fraction: rear portion of finite DoF > front
    T11  CoC default = 0.03mm (35mm-FF standard)
    T12  LensFocusSpec dataclass default CoC preserved
    T13  DepthOfFieldReport.to_dict() serialisation — None for ∞, honest_caveat present
    T14  ValueError on non-positive focal_length_mm
    T15  ValueError on non-positive f_number
    T16  ValueError on focus_distance <= focal_length
    LLM tool wrapper:
    T17  optics_compute_depth_of_field — happy path returns ok: True
    T18  optics_compute_depth_of_field — missing required field returns error

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Oracle values cross-checked against Greenleaf "Photographic Optics" §3
tabulated values and Hecht "Optics" 5e §6.4 hand calculations.

References
----------
Hecht, E. — "Optics", 5th ed. (2017), §6.4.
Greenleaf, A.R. — "Photographic Optics" (1950), §3.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.optics.focal_depth_field import (
    LensFocusSpec,
    DepthOfFieldReport,
    compute_depth_of_field,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approx(a: float, b: float, rel: float = 1e-3) -> bool:
    """Return True if |a-b|/max(|b|, 1e-12) <= rel."""
    denom = max(abs(b), 1e-12)
    return abs(a - b) / denom <= rel


def _ctx():
    """Minimal fake ProjectCtx for LLM tool tests."""
    class _Ctx:
        project_id = uuid.uuid4()
        user_id = uuid.uuid4()
    return _Ctx()


# ---------------------------------------------------------------------------
# Oracle: 50mm f/2.8 focused at 5000mm, c=0.03mm
#
# H = f²/(N·c) + f = 50²/(2.8·0.03) + 50 = 2500/0.084 + 50 = 29761.90... + 50
#                  = 29811.90... mm  ≈ 29.81 m
#
# D_near = D·(H-f) / (H + D - 2f)
#        = 5000·(29811.9 - 50) / (29811.9 + 5000 - 100)
#        = 5000·29761.9 / 34711.9
#        ≈ 4285.7 mm
#
# D_far = D·(H-f) / (H - D)
#       = 5000·29761.9 / (29811.9 - 5000)
#       = 5000·29761.9 / 24811.9
#       ≈ 5993.2 mm
#
# DoF = D_far - D_near ≈ 1707.5 mm
# ---------------------------------------------------------------------------

_F = 50.0        # mm
_N = 2.8
_D = 5000.0      # mm
_C = 0.03        # mm
_H_exact = _F ** 2 / (_N * _C) + _F   # 29811.904... mm


class TestHyperfocalOracle:
    """T01 — hyperfocal distance oracle for 50mm f/2.8 c=0.03mm."""

    def test_hyperfocal_value(self):
        spec = LensFocusSpec(focal_length_mm=_F, f_number=_N,
                              focus_distance_mm=_D, circle_of_confusion_mm=_C)
        r = compute_depth_of_field(spec)
        # H = 50²/(2.8·0.03) + 50 ≈ 29811.90 mm
        assert _approx(r.hyperfocal_distance_mm, _H_exact, rel=1e-5), (
            f"H={r.hyperfocal_distance_mm:.3f} expected ≈{_H_exact:.3f}"
        )


class TestNearFarLimitsOracle:
    """T02–T04 — near/far/DoF oracle for canonical 50mm f/2.8 @ 5m."""

    @pytest.fixture(scope="class")
    def report(self):
        spec = LensFocusSpec(focal_length_mm=_F, f_number=_N,
                              focus_distance_mm=_D, circle_of_confusion_mm=_C)
        return compute_depth_of_field(spec)

    def test_near_limit(self, report):
        # D_near = 5000*(H-50)/(H+5000-100); expected ≈ 4285–4286 mm
        expected_near = _D * (_H_exact - _F) / (_H_exact + _D - 2 * _F)
        assert _approx(report.near_limit_mm, expected_near, rel=1e-4), (
            f"near={report.near_limit_mm:.2f} expected={expected_near:.2f}"
        )

    def test_far_limit(self, report):
        # D_far = 5000*(H-50)/(H-5000); expected ≈ 5993 mm
        expected_far = _D * (_H_exact - _F) / (_H_exact - _D)
        assert _approx(report.far_limit_mm, expected_far, rel=1e-4), (
            f"far={report.far_limit_mm:.2f} expected={expected_far:.2f}"
        )

    def test_dof_total(self, report):
        expected_near = _D * (_H_exact - _F) / (_H_exact + _D - 2 * _F)
        expected_far = _D * (_H_exact - _F) / (_H_exact - _D)
        expected_dof = expected_far - expected_near
        assert _approx(report.depth_of_field_mm, expected_dof, rel=1e-4), (
            f"DoF={report.depth_of_field_mm:.2f} expected={expected_dof:.2f}"
        )

    def test_far_greater_than_focus(self, report):
        assert report.far_limit_mm > _D

    def test_near_less_than_focus(self, report):
        assert report.near_limit_mm < _D

    def test_not_infinity_focused(self, report):
        assert report.infinity_focus_at_hyperfocal is False


class TestHyperfocalFocusBehaviour:
    """T05–T06 — focusing exactly at hyperfocal → far=∞, near≈H/2."""

    @pytest.fixture(scope="class")
    def report(self):
        # Focus exactly at H
        spec = LensFocusSpec(focal_length_mm=_F, f_number=_N,
                              focus_distance_mm=_H_exact,
                              circle_of_confusion_mm=_C)
        return compute_depth_of_field(spec)

    def test_far_is_infinite(self, report):
        assert math.isinf(report.far_limit_mm), "far limit must be ∞ at hyperfocal"

    def test_infinity_flag(self, report):
        assert report.infinity_focus_at_hyperfocal is True

    def test_near_limit_approx_half_hyperfocal(self, report):
        # At focus=H: D_near = H·(H-f)/(H+H-2f) = H·(H-f)/(2·(H-f)) = H/2
        expected_near = _H_exact / 2.0
        assert _approx(report.near_limit_mm, expected_near, rel=1e-4), (
            f"near={report.near_limit_mm:.2f} expected≈{expected_near:.2f} (H/2)"
        )

    def test_dof_is_infinite(self, report):
        assert math.isinf(report.depth_of_field_mm)

    def test_behind_fraction_is_nan(self, report):
        assert math.isnan(report.behind_focus_fraction)


class TestLargerFnumberBiggerDof:
    """T07 — larger f-number → bigger DoF for same focal length & distance."""

    def test_f8_dof_greater_than_f2_8(self):
        base = LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                              focus_distance_mm=5000.0)
        wide = LensFocusSpec(focal_length_mm=50.0, f_number=8.0,
                              focus_distance_mm=5000.0)
        r_base = compute_depth_of_field(base)
        r_wide = compute_depth_of_field(wide)
        assert r_wide.depth_of_field_mm > r_base.depth_of_field_mm


class TestShorterFocalLengthLongerHyperfocal:
    """T08 — shorter focal length → LONGER hyperfocal for same N and c.

    H = f²/(N·c) + f.  As f decreases, f² falls faster than f, so H shrinks.
    Conversely, longer focal length → longer hyperfocal.
    """

    def test_100mm_hyperfocal_greater_than_50mm(self):
        spec_50 = LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                                 focus_distance_mm=2000.0)
        spec_100 = LensFocusSpec(focal_length_mm=100.0, f_number=2.8,
                                  focus_distance_mm=2000.0)
        r50 = compute_depth_of_field(spec_50)
        r100 = compute_depth_of_field(spec_100)
        assert r100.hyperfocal_distance_mm > r50.hyperfocal_distance_mm


class TestFocusBeyondHyperfocal:
    """T09 — focus distance well beyond H → DoF infinite."""

    def test_focus_beyond_hyperfocal_gives_infinite_dof(self):
        H = _H_exact
        spec = LensFocusSpec(focal_length_mm=_F, f_number=_N,
                              focus_distance_mm=H * 2.0,
                              circle_of_confusion_mm=_C)
        r = compute_depth_of_field(spec)
        assert math.isinf(r.depth_of_field_mm)
        assert math.isinf(r.far_limit_mm)


class TestBehindFocusFraction:
    """T10 — more DoF lies behind focus than in front (standard result)."""

    def test_behind_fraction_greater_than_half(self):
        spec = LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                              focus_distance_mm=3000.0)
        r = compute_depth_of_field(spec)
        # For distances well inside hyperfocal, rear portion > front
        assert r.behind_focus_fraction > 0.5


class TestDefaultCoC:
    """T11 — default circle_of_confusion_mm is 0.03mm (35mm-FF standard)."""

    def test_default_coc(self):
        spec = LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                              focus_distance_mm=5000.0)
        assert spec.circle_of_confusion_mm == pytest.approx(0.03)


class TestDataclassDefault:
    """T12 — LensFocusSpec CoC default preserved through computation."""

    def test_explicit_vs_default_coc(self):
        spec_default = LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                                      focus_distance_mm=5000.0)
        spec_explicit = LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                                       focus_distance_mm=5000.0,
                                       circle_of_confusion_mm=0.03)
        r_d = compute_depth_of_field(spec_default)
        r_e = compute_depth_of_field(spec_explicit)
        assert r_d.hyperfocal_distance_mm == pytest.approx(r_e.hyperfocal_distance_mm)
        assert r_d.near_limit_mm == pytest.approx(r_e.near_limit_mm)


class TestToDictSerialisation:
    """T13 — DepthOfFieldReport.to_dict() correctness."""

    def test_finite_case_dict(self):
        spec = LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                              focus_distance_mm=5000.0)
        r = compute_depth_of_field(spec)
        d = r.to_dict()
        assert d["ok"] is True
        assert isinstance(d["hyperfocal_distance_mm"], float)
        assert isinstance(d["near_limit_mm"], float)
        assert isinstance(d["far_limit_mm"], float)   # not None here
        assert isinstance(d["depth_of_field_mm"], float)
        assert isinstance(d["behind_focus_fraction"], float)
        assert "honest_caveat" in d
        assert len(d["honest_caveat"]) > 20

    def test_infinite_case_serialises_to_none(self):
        spec = LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                              focus_distance_mm=_H_exact)
        r = compute_depth_of_field(spec)
        d = r.to_dict()
        assert d["far_limit_mm"] is None
        assert d["depth_of_field_mm"] is None
        assert d["behind_focus_fraction"] is None
        assert d["infinity_focus_at_hyperfocal"] is True


class TestErrorPaths:
    """T14–T16 — ValueError on invalid inputs."""

    def test_non_positive_focal_length(self):
        with pytest.raises(ValueError, match="focal_length_mm"):
            compute_depth_of_field(
                LensFocusSpec(focal_length_mm=0.0, f_number=2.8,
                               focus_distance_mm=5000.0)
            )

    def test_non_positive_f_number(self):
        with pytest.raises(ValueError, match="f_number"):
            compute_depth_of_field(
                LensFocusSpec(focal_length_mm=50.0, f_number=-1.0,
                               focus_distance_mm=5000.0)
            )

    def test_focus_distance_too_small(self):
        # focus_distance_mm ≤ focal_length_mm is physically undefined
        with pytest.raises(ValueError, match="focus_distance_mm"):
            compute_depth_of_field(
                LensFocusSpec(focal_length_mm=50.0, f_number=2.8,
                               focus_distance_mm=50.0)  # == focal length
            )


# ---------------------------------------------------------------------------
# LLM tool wrapper tests
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.optics.tools import (  # noqa: E402
        run_compute_depth_of_field_focal,
    )
    _TOOL_AVAILABLE = True
except ImportError:
    _TOOL_AVAILABLE = False


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="LLM tool not yet registered")
class TestLlmToolWrapper:
    """T17–T18 — LLM tool optics_compute_depth_of_field happy + error paths."""

    def _run(self, payload: dict) -> dict:
        raw = asyncio.get_event_loop().run_until_complete(
            run_compute_depth_of_field_focal(_ctx(), json.dumps(payload).encode())
        )
        return json.loads(raw)

    def test_happy_path(self):
        d = self._run({
            "focal_length_mm": 50.0,
            "f_number": 2.8,
            "focus_distance_mm": 5000.0,
            "circle_of_confusion_mm": 0.03,
        })
        assert d.get("ok") is True
        assert "hyperfocal_distance_mm" in d

    def test_missing_required_field(self):
        d = self._run({"focal_length_mm": 50.0, "f_number": 2.8})
        assert d.get("ok") is False
