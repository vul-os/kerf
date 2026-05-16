"""
Tests for kerf_cad_core.geom.solid_features (Rhino/SolidTools parity).

All tests are hermetic (pure-Python, no DB, no OCC required).
Analytic ground-truths used:
  - pipe_along_curve (straight):   V = π r² L
  - pipe_along_curve (arc, Pappus): V = π r² × (2π R) for full torus
  - shell_solid mass:              (V_outer − V_inner) × ρ
  - draft_faces taper:             h × tan(angle_rad)
  - variable_radius_fillet ends:   match specified radii exactly
  - rib_web cross-section:         trapezoidal A = ½(w_top+w_bottom)×h
  - wirecut depth:                 extent of bbox along direction

≥ 30 test cases total.
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.solid_features import (
    draft_faces,
    pipe_along_curve,
    rib_web,
    shell_solid,
    variable_radius_fillet,
    wirecut,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _approx(a, b, rel=1e-6):
    """Assert |a-b| / max(|a|,|b|,1) < rel."""
    denom = max(abs(a), abs(b), 1.0)
    assert abs(a - b) / denom < rel, f"{a} != {b} (rel tol {rel})"


# ─────────────────────────────────────────────────────────────────────────────
# 1. pipe_along_curve — straight path, constant radius
#    V_expected = π r² L
# ─────────────────────────────────────────────────────────────────────────────

class TestPipeStraightConstantRadius:
    def test_volume_formula(self):
        r = 2.0
        L = 10.0
        pts = [[0, 0, 0], [0, 0, L]]
        res = pipe_along_curve(pts, r, cap_style="mitered")
        assert res["ok"]
        expected = math.pi * r ** 2 * L
        _approx(res["volume"], expected, rel=1e-4)

    def test_volume_with_round_caps(self):
        r = 1.5
        L = 8.0
        pts = [[0, 0, 0], [L, 0, 0]]
        res = pipe_along_curve(pts, r, cap_style="round")
        assert res["ok"]
        body = math.pi * r ** 2 * L
        caps = 2 * (2.0 / 3.0) * math.pi * r ** 3
        expected = body + caps
        _approx(res["volume"], expected, rel=1e-4)

    def test_length_correct(self):
        L = 5.0
        res = pipe_along_curve([[0, 0, 0], [0, L, 0]], 1.0)
        assert res["ok"]
        _approx(res["length"], L, rel=1e-9)

    def test_centroid_midpoint(self):
        L = 10.0
        res = pipe_along_curve([[0, 0, 0], [0, 0, L]], 1.0)
        assert res["ok"]
        cx, cy, cz = res["centroid"]
        _approx(cx, 0.0, rel=1e-6)
        _approx(cz, L / 2.0, rel=1e-6)

    def test_three_point_path(self):
        # L-shaped path: two segments each length 5
        pts = [[0, 0, 0], [5, 0, 0], [5, 5, 0]]
        res = pipe_along_curve(pts, 1.0, cap_style="mitered")
        assert res["ok"]
        expected = math.pi * 1.0 ** 2 * 10.0
        _approx(res["volume"], expected, rel=1e-4)
        _approx(res["length"], 10.0, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# 2. pipe_along_curve — Pappus centroid theorem (arc path)
#    For a semicircle of radius R in XY, path length = π R.
#    Centroid of a semicircle arc = 2R/π from centre.
#    V = π r² × L  (still valid numerically; just checks Pappus consistency)
# ─────────────────────────────────────────────────────────────────────────────

class TestPipeArcPappus:
    def _semicircle_pts(self, R: float, n: int = 100):
        """Sample n points along a semicircle of radius R in the XZ plane."""
        return [
            [R * math.cos(math.pi * i / (n - 1)),
             0.0,
             R * math.sin(math.pi * i / (n - 1))]
            for i in range(n)
        ]

    def test_arc_path_length(self):
        R = 3.0
        pts = self._semicircle_pts(R, n=200)
        res = pipe_along_curve(pts, 0.5, cap_style="mitered")
        assert res["ok"]
        expected_L = math.pi * R
        _approx(res["length"], expected_L, rel=5e-4)

    def test_arc_volume_pappus(self):
        """V = π r² × L; Pappus formula indirectly validated through path length."""
        R = 4.0
        r = 0.3
        pts = self._semicircle_pts(R, n=300)
        res = pipe_along_curve(pts, r, cap_style="mitered")
        assert res["ok"]
        L = math.pi * R
        expected = math.pi * r ** 2 * L
        # Allow 1% due to polyline approximation with 300 segments
        _approx(res["volume"], expected, rel=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# 3. pipe_along_curve — variable radius
# ─────────────────────────────────────────────────────────────────────────────

class TestPipeVariableRadius:
    def test_variable_radius_result_ok(self):
        pts = [[0, 0, 0], [0, 0, 10]]
        res = pipe_along_curve(pts, 1.0, variable_radii={0.0: 1.0, 1.0: 2.0})
        assert res["ok"]
        # Volume should be between π*1²*10 and π*2²*10
        assert math.pi * 1.0 * 10 < res["volume"] < math.pi * 4.0 * 10

    def test_variable_radius_midpoint_interpolation(self):
        """Check that radius at t=0.5 is average of endpoints."""
        pts = [[0, 0, 0], [0, 0, 10]]
        res = pipe_along_curve(pts, 1.0, variable_radii={0.0: 1.0, 1.0: 3.0})
        assert res["ok"]
        seg = res["geometry_params"]["segment_data"]
        mid_seg = seg[len(seg) // 2]
        _approx(mid_seg["radius"], 2.0, rel=0.05)


# ─────────────────────────────────────────────────────────────────────────────
# 4. pipe_along_curve — bend check / min-radius violation
# ─────────────────────────────────────────────────────────────────────────────

class TestPipeBendCheck:
    def test_tight_bend_flagged(self):
        # Sharp 90° corner with segments of length 5 each
        # Bend radius ≈ 5 / (2 * sin(45°)) ≈ 3.54
        pts = [[0, 0, 0], [5, 0, 0], [5, 5, 0]]
        res = pipe_along_curve(pts, 0.5, min_bend_radius=10.0)
        assert res["ok"]
        assert len(res["bend_check"]) == 1
        assert res["bend_check"][0]["violation"] is True

    def test_straight_path_no_violations(self):
        pts = [[0, 0, 0], [3, 0, 0], [6, 0, 0]]
        res = pipe_along_curve(pts, 0.5, min_bend_radius=1.0)
        assert res["ok"]
        assert res["bend_check"] == []

    def test_no_bend_check_when_min_radius_not_given(self):
        pts = [[0, 0, 0], [5, 0, 0], [5, 5, 0]]
        res = pipe_along_curve(pts, 0.5)
        assert res["ok"]
        assert res["bend_check"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. pipe_along_curve — error paths
# ─────────────────────────────────────────────────────────────────────────────

class TestPipeErrors:
    def test_too_few_points(self):
        res = pipe_along_curve([[0, 0, 0]], 1.0)
        assert not res["ok"]
        assert "at least 2" in res["reason"]

    def test_bad_radius(self):
        res = pipe_along_curve([[0, 0, 0], [1, 0, 0]], -1.0)
        assert not res["ok"]

    def test_bad_cap_style(self):
        res = pipe_along_curve([[0, 0, 0], [1, 0, 0]], 1.0, cap_style="beveled")
        assert not res["ok"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. shell_solid — mass formula: (V_outer − V_inner) × ρ
# ─────────────────────────────────────────────────────────────────────────────

class TestShellSolid:
    def test_basic_mass(self):
        w, d, h = 10.0, 8.0, 6.0
        t = 1.0
        rho = 2700.0  # kg/m³ (aluminium-ish)
        res = shell_solid([w, d, h], t, density=rho)
        assert res["ok"]
        v_outer = w * d * h
        v_inner = (w - 2*t) * (d - 2*t) * (h - 2*t)
        expected_mass = (v_outer - v_inner) * rho
        _approx(res["shell_mass"], expected_mass, rel=1e-9)

    def test_volume_outer(self):
        res = shell_solid([5.0, 4.0, 3.0], 0.5)
        assert res["ok"]
        _approx(res["volume_outer"], 60.0, rel=1e-9)

    def test_volume_inner(self):
        w, d, h, t = 10.0, 10.0, 10.0, 1.0
        res = shell_solid([w, d, h], t)
        assert res["ok"]
        _approx(res["volume_inner"], 8.0 ** 3, rel=1e-9)

    def test_feasibility_ok(self):
        res = shell_solid([10.0, 10.0, 10.0], 1.0)
        assert res["ok"]
        assert res["thickness_feasible"] is True

    def test_feasibility_fails_when_too_thick(self):
        res = shell_solid([2.0, 2.0, 2.0], 1.5)
        assert res["ok"]
        assert res["thickness_feasible"] is False

    def test_open_faces_stored(self):
        res = shell_solid([10.0, 10.0, 10.0], 1.0, open_faces=["top", "bottom"])
        assert res["ok"]
        assert set(res["open_faces"]) == {"top", "bottom"}

    def test_bad_wall_thickness(self):
        res = shell_solid([10.0, 10.0, 10.0], -0.5)
        assert not res["ok"]

    def test_invalid_face_name(self):
        res = shell_solid([10.0, 10.0, 10.0], 1.0, open_faces=["ceiling"])
        assert not res["ok"]
        assert "ceiling" in res["reason"]

    def test_wrong_dims_count(self):
        res = shell_solid([10.0, 10.0], 1.0)
        assert not res["ok"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. draft_faces — taper = h × tan(angle)
# ─────────────────────────────────────────────────────────────────────────────

class TestDraftFaces:
    def test_taper_at_top_formula(self):
        h = 20.0
        angle = 5.0
        res = draft_faces(h, angle)
        assert res["ok"]
        expected = h * math.tan(math.radians(angle))
        _approx(res["taper_offset_at_top"], expected, rel=1e-9)

    def test_taper_at_bottom_zero_when_offset_zero(self):
        res = draft_faces(10.0, 3.0, neutral_plane_offset=0.0)
        assert res["ok"]
        _approx(res["taper_offset_at_bottom"], 0.0, rel=1e-9)

    def test_neutral_plane_midheight(self):
        h = 10.0
        angle = 10.0
        res = draft_faces(h, angle, neutral_plane_offset=0.5)
        assert res["ok"]
        half_taper = (h * 0.5) * math.tan(math.radians(angle))
        _approx(res["taper_offset_at_top"], half_taper, rel=1e-9)
        _approx(res["taper_offset_at_bottom"], half_taper, rel=1e-9)

    def test_angle_out_of_range(self):
        res = draft_faces(10.0, 0.0)
        assert not res["ok"]
        res = draft_faces(10.0, 90.0)
        assert not res["ok"]

    def test_bad_neutral_offset(self):
        res = draft_faces(10.0, 5.0, neutral_plane_offset=1.5)
        assert not res["ok"]

    def test_negative_height(self):
        res = draft_faces(-5.0, 3.0)
        assert not res["ok"]


# ─────────────────────────────────────────────────────────────────────────────
# 8. variable_radius_fillet — endpoint radii exact; min-radius violation
# ─────────────────────────────────────────────────────────────────────────────

class TestVariableRadiusFillet:
    def test_endpoints_match_specified(self):
        res = variable_radius_fillet(100.0, 3.0, 7.0)
        assert res["ok"]
        _approx(res["radius_at_start"], 3.0, rel=1e-9)
        _approx(res["radius_at_end"], 7.0, rel=1e-9)

    def test_min_radius_on_edge_is_minimum(self):
        res = variable_radius_fillet(50.0, 2.0, 8.0)
        assert res["ok"]
        _approx(res["min_radius_on_edge"], 2.0, rel=1e-9)

    def test_min_radius_violation_flagged(self):
        res = variable_radius_fillet(50.0, 1.5, 4.0, min_allowed_radius=2.0)
        assert res["ok"]
        assert res["min_radius_violation"] is True

    def test_no_violation_when_above_min(self):
        res = variable_radius_fillet(50.0, 3.0, 5.0, min_allowed_radius=2.0)
        assert res["ok"]
        assert res["min_radius_violation"] is False

    def test_tangency_ok_slow_taper(self):
        """dr/ds = (5-1)/100 = 0.04 < 1 → tangency_ok=True."""
        res = variable_radius_fillet(100.0, 1.0, 5.0)
        assert res["ok"]
        assert res["tangency_ok"] is True

    def test_tangency_fails_rapid_taper(self):
        """dr/ds = (10-1)/1 = 9 > 1 → tangency_ok=False."""
        res = variable_radius_fillet(1.0, 1.0, 10.0)
        assert res["ok"]
        assert res["tangency_ok"] is False

    def test_bad_edge_length(self):
        res = variable_radius_fillet(0.0, 1.0, 2.0)
        assert not res["ok"]

    def test_bad_radius_start(self):
        res = variable_radius_fillet(10.0, -1.0, 2.0)
        assert not res["ok"]


# ─────────────────────────────────────────────────────────────────────────────
# 9. rib_web — trapezoidal cross-section
# ─────────────────────────────────────────────────────────────────────────────

class TestRibWeb:
    def test_zero_draft_rectangle(self):
        """With 0° draft: A = rib_thickness × rib_height (rectangle)."""
        pl, rt, rh = 15.0, 3.0, 5.0
        res = rib_web(pl, rt, rh, draft_angle_deg=0.0)
        assert res["ok"]
        expected_area = rt * rh  # rectangle
        _approx(res["cross_section_area"], expected_area, rel=1e-9)
        _approx(res["volume"], expected_area * pl, rel=1e-9)

    def test_draft_trapezoidal_area(self):
        pl, rt, rh = 10.0, 2.0, 4.0
        angle = 10.0
        taper = rh * math.tan(math.radians(angle))
        w_top = rt
        w_bottom = rt + 2 * taper
        expected_area = 0.5 * (w_top + w_bottom) * rh
        res = rib_web(pl, rt, rh, draft_angle_deg=angle)
        assert res["ok"]
        _approx(res["cross_section_area"], expected_area, rel=1e-9)

    def test_draft_taper_value(self):
        rh = 6.0
        angle = 15.0
        res = rib_web(5.0, 1.0, rh, draft_angle_deg=angle)
        assert res["ok"]
        expected_taper = rh * math.tan(math.radians(angle))
        _approx(res["draft_taper"], expected_taper, rel=1e-9)

    def test_explicit_attachment_width(self):
        res = rib_web(5.0, 2.0, 4.0, attachment_width=6.0)
        assert res["ok"]
        _approx(res["attachment_width"], 6.0, rel=1e-9)

    def test_bad_profile_length(self):
        res = rib_web(-1.0, 2.0, 3.0)
        assert not res["ok"]

    def test_draft_angle_out_of_range(self):
        res = rib_web(5.0, 2.0, 3.0, draft_angle_deg=90.0)
        assert not res["ok"]


# ─────────────────────────────────────────────────────────────────────────────
# 10. wirecut — geometry basics
# ─────────────────────────────────────────────────────────────────────────────

class TestWirecut:
    def test_basic_vertical_cut(self):
        """Profile [[0,0],[0,5]] cut along Z through a 10×10×20 box."""
        res = wirecut([10.0, 10.0, 20.0], [[0, 0], [0, 5]], direction=(0, 0, 1))
        assert res["ok"]
        # path_length = 5; cut_depth = 20
        _approx(res["path_length"], 5.0, rel=1e-9)
        _approx(res["cut_depth"], 20.0, rel=1e-9)
        _approx(res["cut_area"], 100.0, rel=1e-9)

    def test_direction_normalised(self):
        res = wirecut([5.0, 5.0, 5.0], [[0, 0], [1, 0]], direction=(0, 0, 3))
        assert res["ok"]
        dx, dy, dz = res["direction"]
        _approx(math.sqrt(dx**2 + dy**2 + dz**2), 1.0, rel=1e-9)

    def test_diagonal_cut_depth(self):
        """Direction [1,1,0] through [10,10,5] box: depth = √2 * 10."""
        res = wirecut([10.0, 10.0, 5.0], [[0, 0], [1, 0]], direction=(1, 1, 0))
        assert res["ok"]
        expected_depth = math.sqrt(2) * 10.0
        _approx(res["cut_depth"], expected_depth, rel=1e-6)

    def test_too_few_profile_points(self):
        res = wirecut([5.0, 5.0, 5.0], [[0, 0]])
        assert not res["ok"]

    def test_bad_bbox(self):
        res = wirecut([0.0, 5.0, 5.0], [[0, 0], [1, 0]])
        assert not res["ok"]

    def test_zero_direction(self):
        res = wirecut([5.0, 5.0, 5.0], [[0, 0], [1, 0]], direction=(0, 0, 0))
        assert not res["ok"]
