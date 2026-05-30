"""
Tests for ISO 129-1:2018 auto-dimensioning conventions.

Pure-Python, hermetic — no OCC, no database.

Analytical oracles:
  T1  Chain mode:    rectangular view with N x-positions → N-1 horizontal dims.
  T2  Baseline mode: rectangular view with N x-positions → N-1 dims (from baseline).
  T3  Chain count (vertical segment count): N y-positions → N-1 vertical dims.
  T4  Baseline count (vertical): N y-positions → N-1 stacked vertical dims.
  T5  Spacing: parallel dim lines ≥ 10 mm in baseline mode.
  T6  Extension-line overshoot: iso_linear_dim ext endpoint extends past dim line.
  T7  Extension-line gap: ext_start is _ISO_EXTENSION_LINE_GAP_MM from feature edge.
  T8  Arrowhead length = 3.5 mm on all iso_linear_dim.
  T9  Tolerance format symmetric  → "100 ± 0.1".
  T10 Tolerance format unilateral → "100 +0.2/0".
  T11 Tolerance format limit      → "100.1 / 99.9".
  T12 Tolerance unilateral single-value → "+tol/0" pattern.
  T13 Tolerance invalid kind raises ValueError.
  T14 Tolerance limit requires 2-tuple value.
  T15 Validation: extension line too short → flagged as violation.
  T16 Validation: dim-line spacing too tight → flagged.
  T17 Validation: leader angle off preferred → flagged or warned.
  T18 Validation: compliant view → no violations.
  T19 Leader dim for hole feature → iso_leader_dim type.
  T20 Leader angle = 15° (preferred ISO §10 default).
  T21 Mixed mode: small gap → chain; large gap → baseline.
  T22 auto_dimension_view_iso129 invalid mode raises ValueError.
  T23 validate_iso129_compliance with empty view → compliant.
  T24 ValidationResult.to_dict() shape check.
  T25 Text height too small → violation if text_height_mm field present.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from kerf_cad_core.drawings.auto_dimension import (
    ValidationResult,
    apply_iso129_tolerance_format,
    auto_dimension_view_iso129,
    validate_iso129_compliance,
    _ISO_DIM_LINE_SPACING_MM,
    _ISO_EXTENSION_LINE_GAP_MM,
    _ISO_EXTENSION_LINE_OVERSHOOT_MM,
    _ISO_ARROWHEAD_LENGTH_MM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rect_view(
    x: float = 0.0,
    y: float = 0.0,
    w: float = 100.0,
    h: float = 50.0,
    extra_x: List[float] | None = None,
    extra_y: List[float] | None = None,
    features: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Build a minimal view dict with bbox and optional extra feature coords."""
    view: Dict[str, Any] = {
        "bbox": {"x": x, "y": y, "w": w, "h": h},
    }
    if features is not None:
        view["features"] = features
    return view


def _count_dims_by_axis(dims: List[Dict[str, Any]], axis: str) -> int:
    return sum(1 for d in dims if d.get("type") == "iso_linear_dim" and d.get("axis") == axis)


def _count_leaders(dims: List[Dict[str, Any]]) -> int:
    return sum(1 for d in dims if d.get("type") == "iso_leader_dim")


# ---------------------------------------------------------------------------
# T1–T4: Chain and baseline dim counts
# ---------------------------------------------------------------------------

class TestChainBaselineCount:
    """
    Oracle:
    - N distinct x-coords (including bbox edges) → N-1 horizontal dims (chain).
    - N distinct x-coords → N-1 horizontal dims (baseline).
    - Same for vertical (y-coords).

    For a plain rectangular view with no extra features:
      x_coords = {bx, bx+bw} → 2 points → 1 horizontal dim.
      y_coords = {by, by+bh} → 2 points → 1 vertical dim.

    With 2 extra x features (creating 4 distinct x-positions):
      chain    → 3 horizontal dims (4-1=3).
      baseline → 3 horizontal dims (4-1=3).
    """

    def test_chain_horizontal_count_no_extra_features(self):
        """Rect view: 2 x-positions → 1 horizontal chain dim."""
        view = _rect_view(w=100.0, h=50.0)
        dims = auto_dimension_view_iso129(view, mode="chain")
        h_count = _count_dims_by_axis(dims, "horizontal")
        assert h_count == 1, f"expected 1 horizontal chain dim for 2 x-points, got {h_count}"

    def test_chain_horizontal_count_with_features(self):
        """4 distinct x-positions (bbox edges + 2 holes) → 3 horizontal chain dims."""
        features = [
            {"kind": "hole", "x_mm": 20.0, "y_mm": 25.0, "diameter_mm": 6.0},
            {"kind": "hole", "x_mm": 60.0, "y_mm": 25.0, "diameter_mm": 6.0},
            {"kind": "hole", "x_mm": 80.0, "y_mm": 25.0, "diameter_mm": 6.0},
        ]
        view = _rect_view(x=0.0, y=0.0, w=100.0, h=50.0, features=features)
        dims = auto_dimension_view_iso129(view, mode="chain")
        h_count = _count_dims_by_axis(dims, "horizontal")
        # x positions: 0, 20, 60, 80, 100 → 5 points → 4 chain dims
        assert h_count == 4, f"expected 4 horizontal chain dims for 5 x-points, got {h_count}"

    def test_baseline_horizontal_count_with_features(self):
        """4 distinct x-positions → 3 baseline horizontal dims (from leftmost)."""
        features = [
            {"kind": "hole", "x_mm": 25.0, "y_mm": 25.0, "diameter_mm": 6.0},
            {"kind": "hole", "x_mm": 50.0, "y_mm": 25.0, "diameter_mm": 6.0},
            {"kind": "hole", "x_mm": 75.0, "y_mm": 25.0, "diameter_mm": 6.0},
        ]
        view = _rect_view(x=0.0, y=0.0, w=100.0, h=50.0, features=features)
        dims = auto_dimension_view_iso129(view, mode="baseline")
        h_count = _count_dims_by_axis(dims, "horizontal")
        # x positions: 0, 25, 50, 75, 100 → 5 points → 4 baseline dims
        assert h_count == 4, f"expected 4 horizontal baseline dims for 5 x-points, got {h_count}"

    def test_chain_vertical_count_no_extra_features(self):
        """Rect view: 2 y-positions → 1 vertical chain dim."""
        view = _rect_view(w=100.0, h=50.0)
        dims = auto_dimension_view_iso129(view, mode="chain")
        v_count = _count_dims_by_axis(dims, "vertical")
        assert v_count == 1, f"expected 1 vertical chain dim, got {v_count}"

    def test_baseline_vertical_count_no_extra_features(self):
        """Rect view: 2 y-positions → 1 vertical baseline dim."""
        view = _rect_view(w=100.0, h=50.0)
        dims = auto_dimension_view_iso129(view, mode="baseline")
        v_count = _count_dims_by_axis(dims, "vertical")
        assert v_count == 1, f"expected 1 vertical baseline dim, got {v_count}"


# ---------------------------------------------------------------------------
# T5–T8: Spacing, extension-line geometry, arrowhead
# ---------------------------------------------------------------------------

class TestIsoGeometry:
    """
    Oracle for ISO §5.4:
    - Extension-line gap from feature edge = _ISO_EXTENSION_LINE_GAP_MM.
    - Extension-line overshoot past dim line = _ISO_EXTENSION_LINE_OVERSHOOT_MM.
    - Parallel dim-line spacing ≥ _ISO_DIM_LINE_SPACING_MM.
    - Arrowhead length = _ISO_ARROWHEAD_LENGTH_MM.
    """

    def test_dim_line_spacing_in_baseline_mode(self):
        """Baseline mode: each subsequent dim line is 10 mm further from feature."""
        features = [
            {"kind": "hole", "x_mm": 30.0, "y_mm": 25.0, "diameter_mm": 5.0},
            {"kind": "hole", "x_mm": 70.0, "y_mm": 25.0, "diameter_mm": 5.0},
        ]
        view = _rect_view(x=0.0, y=0.0, w=100.0, h=50.0, features=features)
        dims = auto_dimension_view_iso129(view, mode="baseline")
        h_dims = [d for d in dims if d.get("type") == "iso_linear_dim" and d.get("axis") == "horizontal"]
        assert len(h_dims) >= 2, "need >= 2 horizontal dims for spacing check"
        # Extract y-coordinates of dim lines (dim_p1[1])
        ys = sorted(d["dim_p1"][1] for d in h_dims)
        for i in range(len(ys) - 1):
            spacing = abs(ys[i + 1] - ys[i])
            assert spacing >= _ISO_DIM_LINE_SPACING_MM - 0.5, (
                f"dim-line spacing {spacing:.3f} < {_ISO_DIM_LINE_SPACING_MM} mm (ISO §5.4)"
            )

    def test_extension_line_overshoot(self):
        """Extension line endpoint should be _ISO_EXTENSION_LINE_OVERSHOOT_MM past dim line."""
        view = _rect_view(x=0.0, y=0.0, w=100.0, h=50.0)
        dims = auto_dimension_view_iso129(view, mode="chain")
        h_dims = [d for d in dims if d.get("type") == "iso_linear_dim" and d.get("axis") == "horizontal"]
        assert h_dims, "need at least one horizontal dim"
        d = h_dims[0]
        # For horizontal dim, dim_p1[1] is the dim-line Y.  ext1_end[1] should be
        # dim_line_y + overshoot (ext line goes beyond dim line toward away direction).
        dim_y = d["dim_p1"][1]
        ext1_end_y = d["ext1_end"][1]
        # ext1_end should be >= dim_y - overshoot or <= dim_y + overshoot; direction
        # depends on sign convention. Just check the offset equals overshoot.
        actual_overshoot = abs(ext1_end_y - dim_y)
        assert abs(actual_overshoot - _ISO_EXTENSION_LINE_OVERSHOOT_MM) < 0.01, (
            f"overshoot {actual_overshoot:.3f} != {_ISO_EXTENSION_LINE_OVERSHOOT_MM} mm (ISO §5.4)"
        )

    def test_extension_line_gap_from_feature(self):
        """Extension line start should be _ISO_EXTENSION_LINE_GAP_MM from feature edge."""
        bx, by, bw, bh = 10.0, 5.0, 80.0, 40.0
        view = _rect_view(x=bx, y=by, w=bw, h=bh)
        dims = auto_dimension_view_iso129(view, mode="chain")
        h_dims = [d for d in dims if d.get("type") == "iso_linear_dim" and d.get("axis") == "horizontal"]
        assert h_dims, "need at least one horizontal dim"
        d = h_dims[0]
        # For horizontal dim, feature Y = by + bh (top edge of view bbox).
        # ext1_start[1] should be feature_y - gap (gap away from the feature edge).
        feature_y = by + bh
        ext1_start_y = d["ext1_start"][1]
        gap = abs(feature_y - ext1_start_y)
        assert abs(gap - _ISO_EXTENSION_LINE_GAP_MM) < 0.01, (
            f"extension-line gap {gap:.3f} != {_ISO_EXTENSION_LINE_GAP_MM} mm (ISO §5.4)"
        )

    def test_arrowhead_length_on_iso_dims(self):
        """All iso_linear_dim dicts carry arrowhead_length_mm = 3.5 mm."""
        view = _rect_view(x=0.0, y=0.0, w=100.0, h=60.0)
        dims = auto_dimension_view_iso129(view, mode="chain")
        iso_dims = [d for d in dims if d.get("type") == "iso_linear_dim"]
        assert iso_dims, "need iso_linear_dim entries"
        for d in iso_dims:
            al = d.get("arrowhead_length_mm")
            assert al is not None, "arrowhead_length_mm missing"
            assert abs(float(al) - _ISO_ARROWHEAD_LENGTH_MM) < 0.01, (
                f"arrowhead {al} != {_ISO_ARROWHEAD_LENGTH_MM} mm"
            )


# ---------------------------------------------------------------------------
# T9–T14: Tolerance format
# ---------------------------------------------------------------------------

class TestToleranceFormat:
    """
    Analytical oracles — exact string matches per ISO 129-1:2018 §8.
    """

    def test_symmetric_format(self):
        """format(100, 0.1, symmetric) → '100 ± 0.1'."""
        result = apply_iso129_tolerance_format(100, 0.1, kind="symmetric")
        assert result == "100 ± 0.1", f"got: {result!r}"

    def test_symmetric_integer_value(self):
        """format(50, 0.05, symmetric) → '50 ± 0.05'."""
        result = apply_iso129_tolerance_format(50, 0.05, kind="symmetric")
        assert result == "50 ± 0.05", f"got: {result!r}"

    def test_unilateral_tuple_format(self):
        """format(100, (0.2, 0), unilateral) → '100 +0.2/0'."""
        result = apply_iso129_tolerance_format(100, (0.2, 0), kind="unilateral")
        assert result == "100 +0.2/0", f"got: {result!r}"

    def test_unilateral_single_value_implies_zero_lower(self):
        """format(100, 0.2, unilateral) → '100 +0.2/0'."""
        result = apply_iso129_tolerance_format(100, 0.2, kind="unilateral")
        assert result == "100 +0.2/0", f"got: {result!r}"

    def test_limit_format(self):
        """format((100.1, 99.9), None, limit) → '100.1 / 99.9'."""
        result = apply_iso129_tolerance_format((100.1, 99.9), None, kind="limit")
        assert result == "100.1 / 99.9", f"got: {result!r}"

    def test_limit_format_integers(self):
        """format((50, 48), None, limit) → '50 / 48'."""
        result = apply_iso129_tolerance_format((50, 48), None, kind="limit")
        assert result == "50 / 48", f"got: {result!r}"

    def test_invalid_kind_raises_value_error(self):
        with pytest.raises(ValueError, match="kind must be"):
            apply_iso129_tolerance_format(100, 0.1, kind="bogus")

    def test_limit_requires_tuple(self):
        with pytest.raises((ValueError, TypeError)):
            apply_iso129_tolerance_format(100.0, None, kind="limit")


# ---------------------------------------------------------------------------
# T15–T18, T25: Compliance validation
# ---------------------------------------------------------------------------

class TestValidateCompliance:
    """
    Analytical oracle: inject known violations and assert they are flagged.
    """

    def test_extension_line_too_short_flagged(self):
        """Extension line shorter than minimum → violation."""
        # Minimum = _ISO_EXTENSION_LINE_GAP_MM + 1.0 mm
        short_len = _ISO_EXTENSION_LINE_GAP_MM + 0.3  # definitely too short
        dim = {
            "type": "iso_linear_dim",
            "axis": "horizontal",
            "value_mm": 100.0,
            "label": "100",
            # ext line from (0,0) to (0, short_len) — much shorter than minimum
            "ext1_start": [0.0, 0.0],
            "ext1_end":   [0.0, short_len],
            "ext2_start": [100.0, 0.0],
            "ext2_end":   [100.0, short_len],
            "dim_p1":     [0.0, -10.0],
            "dim_p2":     [100.0, -10.0],
            "text_pos":   [50.0, -12.0],
            "arrowhead_length_mm": 3.5,
        }
        view = {"iso_dims": [dim]}
        vr = validate_iso129_compliance(view)
        assert not vr.compliant, "should be non-compliant"
        rules = [v["rule"] for v in vr.violations]
        assert any("extension" in r.lower() for r in rules), (
            f"expected extension-line violation; got {rules}"
        )

    def test_dim_line_spacing_too_tight_flagged(self):
        """Two parallel dim lines < 10 mm apart → spacing violation."""
        def _hdim(dim_y: float, label: str) -> Dict:
            return {
                "type": "iso_linear_dim",
                "axis": "horizontal",
                "value_mm": 100.0,
                "label": label,
                "ext1_start": [0.0, dim_y + 3.0],
                "ext1_end":   [0.0, dim_y - 2.0],
                "ext2_start": [100.0, dim_y + 3.0],
                "ext2_end":   [100.0, dim_y - 2.0],
                "dim_p1":     [0.0, dim_y],
                "dim_p2":     [100.0, dim_y],
                "text_pos":   [50.0, dim_y - 1.5],
                "arrowhead_length_mm": 3.5,
            }

        # Spacing = 3 mm (much less than 10 mm minimum)
        view = {"iso_dims": [_hdim(0.0, "100"), _hdim(3.0, "60")]}
        vr = validate_iso129_compliance(view)
        assert not vr.compliant, "should detect spacing violation"
        rules = [v["rule"] for v in vr.violations]
        assert any("spacing" in r.lower() for r in rules), (
            f"expected spacing violation; got {rules}"
        )

    def test_leader_angle_off_preferred_flagged_or_warned(self):
        """Leader angle far from preferred (e.g. 50°) → violation or warning."""
        dim = {
            "type": "iso_leader_dim",
            "label": "Ø10",
            "diameter_mm": 10.0,
            "centre": [50.0, 25.0],
            "leader_start": [50.0, 25.0],
            "leader_elbow": [60.0, 10.0],
            "shoulder_end": [70.0, 10.0],
            "text_pos": [70.5, 9.0],
            "leader_angle_deg": 50.0,  # 50° — between 45° and 60°, deviation = 5°+ from nearest
            "arrowhead_length_mm": 3.5,
            "centre_mark_size_mm": 2.5,
        }
        view = {"iso_dims": [dim]}
        vr = validate_iso129_compliance(view)
        # 50° is between 45° and 60°, deviation = 5° from each — marginal; at least warned
        total_issues = len(vr.violations) + len(vr.warnings)
        assert total_issues >= 1, (
            "expected at least a warning for leader angle 50° (between preferred 45°/60°)"
        )

    def test_compliant_view_has_no_violations(self):
        """A well-formed iso_linear_dim with proper spacing → no violations."""
        def _good_hdim(dim_y: float, x1: float, x2: float, value: float) -> Dict:
            by = dim_y - _ISO_EXTENSION_LINE_OVERSHOOT_MM  # dim line Y
            # feature edge Y is dim_y + _ISO_EXTENSION_LINE_GAP_MM (above dim line)
            fy = by + _ISO_EXTENSION_LINE_GAP_MM + 5.0  # feature edge well above
            return {
                "type": "iso_linear_dim",
                "axis": "horizontal",
                "value_mm": value,
                "label": f"{value:.2f}",
                # ext line from feature edge (fy) downward to dim line overshoot
                "ext1_start": [x1, fy - _ISO_EXTENSION_LINE_GAP_MM],
                "ext1_end":   [x1, by + _ISO_EXTENSION_LINE_OVERSHOOT_MM],
                "ext2_start": [x2, fy - _ISO_EXTENSION_LINE_GAP_MM],
                "ext2_end":   [x2, by + _ISO_EXTENSION_LINE_OVERSHOOT_MM],
                "dim_p1": [x1, by],
                "dim_p2": [x2, by],
                "text_pos": [(x1 + x2) / 2, by - 1.5],
                "arrowhead_length_mm": 3.5,
            }

        # Two dims 10 mm apart in Y → spacing OK
        dim1 = _good_hdim(-10.0, 0.0, 100.0, 100.0)
        dim2 = _good_hdim(-20.0, 0.0, 60.0, 60.0)  # exactly 10 mm below dim1
        view = {"iso_dims": [dim1, dim2]}
        vr = validate_iso129_compliance(view)
        assert vr.compliant, (
            f"expected compliant; violations: {vr.violations}"
        )

    def test_text_height_too_small_flagged(self):
        """Dim with text_height_mm below 2.5 mm → violation."""
        dim = {
            "type": "iso_linear_dim",
            "axis": "horizontal",
            "value_mm": 50.0,
            "label": "50",
            "ext1_start": [0.0, 5.0],
            "ext1_end":   [0.0, -3.0],
            "ext2_start": [50.0, 5.0],
            "ext2_end":   [50.0, -3.0],
            "dim_p1": [0.0, -2.0],
            "dim_p2": [50.0, -2.0],
            "text_pos": [25.0, -4.0],
            "arrowhead_length_mm": 3.5,
            "text_height_mm": 1.5,  # below ISO minimum of 2.5 mm
        }
        view = {"iso_dims": [dim]}
        vr = validate_iso129_compliance(view)
        assert not vr.compliant
        rules = [v["rule"] for v in vr.violations]
        assert any("text" in r.lower() for r in rules), f"expected text violation; got {rules}"

    def test_empty_view_is_compliant(self):
        """View with no dims → compliant by default."""
        vr = validate_iso129_compliance({})
        assert vr.compliant


# ---------------------------------------------------------------------------
# T19–T21: Leader lines and mixed mode
# ---------------------------------------------------------------------------

class TestLeaderAndMixed:

    def test_hole_feature_produces_leader_dim(self):
        """A circular hole feature should emit an iso_leader_dim."""
        features = [{"kind": "hole", "x_mm": 50.0, "y_mm": 25.0, "diameter_mm": 8.0}]
        view = _rect_view(x=0.0, y=0.0, w=100.0, h=50.0, features=features)
        dims = auto_dimension_view_iso129(view, mode="chain")
        leaders = _count_leaders(dims)
        assert leaders == 1, f"expected 1 leader dim, got {leaders}"

    def test_leader_angle_is_preferred(self):
        """Leader dim should use a preferred ISO §10 angle."""
        from kerf_cad_core.drawings.auto_dimension import _ISO_LEADER_ANGLES_DEG
        features = [{"kind": "hole", "x_mm": 50.0, "y_mm": 25.0, "diameter_mm": 8.0}]
        view = _rect_view(x=0.0, y=0.0, w=100.0, h=50.0, features=features)
        dims = auto_dimension_view_iso129(view, mode="chain")
        leaders = [d for d in dims if d.get("type") == "iso_leader_dim"]
        assert leaders
        for ld in leaders:
            angle = ld.get("leader_angle_deg")
            assert angle in _ISO_LEADER_ANGLES_DEG, (
                f"leader angle {angle} not in preferred angles {_ISO_LEADER_ANGLES_DEG}"
            )

    def test_mixed_mode_produces_dims(self):
        """Mixed mode should produce some dimension objects."""
        features = [
            {"kind": "hole", "x_mm": 5.0,  "y_mm": 25.0, "diameter_mm": 5.0},  # close
            {"kind": "hole", "x_mm": 80.0, "y_mm": 25.0, "diameter_mm": 5.0},  # far
        ]
        view = _rect_view(x=0.0, y=0.0, w=100.0, h=50.0, features=features)
        dims = auto_dimension_view_iso129(view, mode="mixed")
        h_count = _count_dims_by_axis(dims, "horizontal")
        assert h_count >= 1, "mixed mode should produce horizontal dims"

    def test_invalid_mode_raises(self):
        view = _rect_view()
        with pytest.raises(ValueError, match="mode must be"):
            auto_dimension_view_iso129(view, mode="invalid")


# ---------------------------------------------------------------------------
# T24: ValidationResult shape
# ---------------------------------------------------------------------------

class TestValidationResultShape:

    def test_to_dict_keys_present(self):
        vr = ValidationResult()
        d = vr.to_dict()
        for key in ("compliant", "violations", "warnings", "violation_count", "warning_count"):
            assert key in d, f"missing key: {key}"

    def test_to_dict_initial_state(self):
        vr = ValidationResult()
        d = vr.to_dict()
        assert d["compliant"] is True
        assert d["violations"] == []
        assert d["warnings"] == []
        assert d["violation_count"] == 0
        assert d["warning_count"] == 0

    def test_add_violation_sets_non_compliant(self):
        vr = ValidationResult()
        vr.add_violation("test rule", 1.0, ">= 2.0", "test detail")
        assert not vr.compliant
        assert vr.to_dict()["violation_count"] == 1

    def test_add_warning_keeps_compliant(self):
        vr = ValidationResult()
        vr.add_warning("test rule", 14.5, "15.0", "close but not a violation")
        assert vr.compliant  # warnings don't affect compliance
        assert vr.to_dict()["warning_count"] == 1
