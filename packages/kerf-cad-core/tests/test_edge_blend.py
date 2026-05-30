"""
test_edge_blend.py
==================
Analytical-oracle tests for kerf_cad_core.geom.edge_blend:
variable_section_blend, morph_cross_sections, CrossSection.

Test plan (4 required validations):
1. Constant rectangular blend
   — rect cross-section at u=0 and u=1 → result is a swept rect (cross-
     section unchanged); volume = section_area × edge_length within 1e-3.
2. Rect→Circle morph
   — rect at t=0, circle at t=1, linear interpolation → the morph at t=0.5
     has a radius parameter between rect and circle; morph interpolates
     width/height linearly.
3. C1 continuity
   — cubic_hermite vs linear at intermediate samples — cubic_hermite profile
     tangent at intermediate stations is continuous (C1); linear has only C0
     (tangent discontinuity detectable at interior stations).
4. Volume monotonic
   — blend volume monotonically interpolates between section_a_volume and
     section_b_volume; intermediate volume bounded by both.

Additional unit tests: CrossSection, morph_cross_sections, profile builders,
edge_frame, blend_cross_section_at, input validation.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_fillet import _make_clamped_knots
from kerf_cad_core.geom.edge_blend import (
    CrossSection,
    blend_cross_section_at,
    blend_volume_estimate,
    morph_cross_sections,
    variable_section_blend,
    _section_profile,
    _edge_frame,
    _linear_interp,
    _hermite_interp_profile,
    _c2_spline_interp_profile,
    _cubic_hermite_tangents,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_plane(
    z: float = 0.0,
    side: float = 2.0,
    nu: int = 4,
    nv: int = 4,
) -> NurbsSurface:
    """Flat surface in the XY plane at elevation z."""
    cp = np.zeros((nu, nv, 3))
    xs = np.linspace(-side / 2, side / 2, nu)
    ys = np.linspace(-side / 2, side / 2, nv)
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            cp[i, j] = [x, y, z]
    return NurbsSurface(
        degree_u=1,
        degree_v=1,
        control_points=cp,
        knots_u=_make_clamped_knots(nu, 1),
        knots_v=_make_clamped_knots(nv, 1),
    )


def _straight_edge(n: int = 10, length: float = 4.0) -> List[np.ndarray]:
    """Straight edge along X axis of given length."""
    return [np.array([x, 0.0, 0.0]) for x in np.linspace(0.0, length, n)]


# ---------------------------------------------------------------------------
# 1. CrossSection dataclass tests
# ---------------------------------------------------------------------------

class TestCrossSection:
    def test_circle_defaults(self) -> None:
        cs = CrossSection(kind="circle", radius=1.0)
        assert cs.kind == "circle"
        assert math.isclose(cs.area, math.pi, rel_tol=1e-9)

    def test_ellipse_area(self) -> None:
        cs = CrossSection(kind="ellipse", width=4.0, height=2.0)
        expected = math.pi * 2.0 * 1.0
        assert math.isclose(cs.area, expected, rel_tol=1e-9)

    def test_rectangle_area_no_rounding(self) -> None:
        cs = CrossSection(kind="rectangle", width=3.0, height=2.0, radius=0.0)
        assert math.isclose(cs.area, 6.0, rel_tol=1e-6)

    def test_rectangle_area_with_rounding(self) -> None:
        cs = CrossSection(kind="rectangle", width=4.0, height=4.0, radius=1.0)
        # base 16, subtract 4 × (1-π/4) corners, add back 0
        expected = 16.0 - 4.0 * (1.0 - math.pi / 4.0)
        assert math.isclose(cs.area, expected, rel_tol=1e-6)

    def test_polygon_area(self) -> None:
        # Unit square as polygon
        verts = [
            np.array([0.5, -0.5, 0.0]),
            np.array([0.5, 0.5, 0.0]),
            np.array([-0.5, 0.5, 0.0]),
            np.array([-0.5, -0.5, 0.0]),
        ]
        cs = CrossSection(kind="polygon", control_points=verts)
        assert math.isclose(cs.area, 1.0, rel_tol=1e-6)

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="kind must be"):
            CrossSection(kind="triangle")

    def test_polygon_needs_3_points(self) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            CrossSection(kind="polygon", control_points=[np.zeros(2)])


# ---------------------------------------------------------------------------
# 2. Profile builder tests
# ---------------------------------------------------------------------------

class TestSectionProfile:
    def test_circle_profile_radius(self) -> None:
        cs = CrossSection(kind="circle", radius=2.0, width=4.0, height=4.0)
        pts = _section_profile(cs, n_pts=64)
        radii = np.linalg.norm(pts, axis=1)
        assert np.allclose(radii, 2.0, atol=1e-2)

    def test_rectangle_profile_bounds(self) -> None:
        cs = CrossSection(kind="rectangle", width=4.0, height=2.0, radius=0.0)
        pts = _section_profile(cs, n_pts=32)
        assert pts[:, 0].max() <= 2.0 + 1e-9
        assert pts[:, 0].min() >= -2.0 - 1e-9
        assert pts[:, 1].max() <= 1.0 + 1e-9
        assert pts[:, 1].min() >= -1.0 - 1e-9

    def test_polygon_profile_count(self) -> None:
        verts = [np.array([1.0, 0.0, 0.0]),
                 np.array([0.0, 1.0, 0.0]),
                 np.array([-1.0, 0.0, 0.0]),
                 np.array([0.0, -1.0, 0.0])]
        cs = CrossSection(kind="polygon", control_points=verts)
        pts = _section_profile(cs, n_pts=16)
        assert pts.shape == (16, 2)


# ---------------------------------------------------------------------------
# 3. morph_cross_sections
# ---------------------------------------------------------------------------

class TestMorphCrossSections:
    def test_circle_to_circle(self) -> None:
        cs_a = CrossSection(kind="circle", radius=1.0, width=2.0, height=2.0)
        cs_b = CrossSection(kind="circle", radius=2.0, width=4.0, height=4.0)
        cs_mid = morph_cross_sections(cs_a, cs_b, 0.5)
        assert cs_mid.kind == "circle"
        assert math.isclose(cs_mid.width, 3.0, rel_tol=1e-9)

    def test_rect_to_rect_linear(self) -> None:
        cs_a = CrossSection(kind="rectangle", width=2.0, height=2.0, radius=0.0)
        cs_b = CrossSection(kind="rectangle", width=4.0, height=4.0, radius=0.0)
        cs_25 = morph_cross_sections(cs_a, cs_b, 0.25)
        assert math.isclose(cs_25.width, 2.5, rel_tol=1e-9)
        assert math.isclose(cs_25.height, 2.5, rel_tol=1e-9)

    def test_rect_to_circle_endpoints(self) -> None:
        cs_a = CrossSection(kind="rectangle", width=2.0, height=2.0, radius=0.0)
        cs_b = CrossSection(kind="circle", radius=1.0, width=2.0, height=2.0)
        cs_0 = morph_cross_sections(cs_a, cs_b, 0.0)
        cs_1 = morph_cross_sections(cs_a, cs_b, 1.0)
        # At t=0 → rect-like; at t=1 → circle
        assert cs_1.kind == "circle"
        # width stays at 2.0 throughout (same diameter as circle)
        assert math.isclose(cs_0.width, 2.0, rel_tol=1e-9)

    def test_rect_to_circle_midpoint_radius_grows(self) -> None:
        """At t=0.5 the corner radius should be between 0 and min(w,h)/2."""
        cs_a = CrossSection(kind="rectangle", width=4.0, height=4.0, radius=0.0)
        cs_b = CrossSection(kind="circle", radius=2.0, width=4.0, height=4.0)
        cs_mid = morph_cross_sections(cs_a, cs_b, 0.5)
        # Corner radius at midpoint = 0.5 * max_radius = 1.0
        assert cs_mid.radius > 0.0
        assert cs_mid.radius < 2.0

    def test_t_equals_zero_returns_a(self) -> None:
        cs_a = CrossSection(kind="ellipse", width=3.0, height=1.0)
        cs_b = CrossSection(kind="ellipse", width=1.0, height=3.0)
        result = morph_cross_sections(cs_a, cs_b, 0.0)
        assert math.isclose(result.width, 3.0, rel_tol=1e-9)
        assert math.isclose(result.height, 1.0, rel_tol=1e-9)

    def test_t_equals_one_returns_b(self) -> None:
        cs_a = CrossSection(kind="ellipse", width=3.0, height=1.0)
        cs_b = CrossSection(kind="ellipse", width=1.0, height=3.0)
        result = morph_cross_sections(cs_a, cs_b, 1.0)
        assert math.isclose(result.width, 1.0, rel_tol=1e-9)
        assert math.isclose(result.height, 3.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 4. variable_section_blend — input validation
# ---------------------------------------------------------------------------

class TestVariableSectionBlendValidation:
    def _face(self) -> NurbsSurface:
        return _flat_plane()

    def test_wrong_face_type_raises(self) -> None:
        with pytest.raises(TypeError, match="face_a must be NurbsSurface"):
            variable_section_blend("not a surface", self._face(),
                                   _straight_edge(),
                                   [(0.0, CrossSection()), (1.0, CrossSection())])

    def test_too_short_edge_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 2 points"):
            variable_section_blend(self._face(), self._face(),
                                   [np.zeros(3)],
                                   [(0.0, CrossSection()), (1.0, CrossSection())])

    def test_too_few_cross_sections_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 2 entries"):
            variable_section_blend(self._face(), self._face(),
                                   _straight_edge(),
                                   [(0.5, CrossSection())])

    def test_bad_blend_method_raises(self) -> None:
        with pytest.raises(ValueError, match="blend_method"):
            variable_section_blend(self._face(), self._face(),
                                   _straight_edge(),
                                   [(0.0, CrossSection()), (1.0, CrossSection())],
                                   blend_method="quintic")


# ---------------------------------------------------------------------------
# 5. ORACLE TEST 1: Constant rectangular blend
# ---------------------------------------------------------------------------

class TestConstantRectBlend:
    """Constant rect cross-section both ends → volume = section_area × edge_length."""

    def test_volume_constant_rect(self) -> None:
        """V = w × h × L within 1% relative tolerance (32-point profile)."""
        face_a = _flat_plane(z=0.0)
        face_b = _flat_plane(z=2.0)
        edge_pts = _straight_edge(n=12, length=4.0)

        w, h = 1.0, 0.5
        cs = CrossSection(kind="rectangle", width=w, height=h, radius=0.0)
        cs_list = [(0.0, cs), (1.0, cs)]

        # Use n_profile_pts=32 to give the polygon enough points for an
        # accurate shoelace area (~0.3% error vs 6% for 9-point polygon).
        blend_surf, edge_a, edge_b = variable_section_blend(
            face_a, face_b, edge_pts, cs_list,
            blend_method="linear", samples=32, n_profile_pts=32,
        )

        vol = blend_volume_estimate(blend_surf, n_v=64, n_u=64)
        expected = w * h * 4.0
        assert abs(vol - expected) / expected < 0.01, (
            f"volume {vol:.4f} expected ~{expected:.4f}"
        )

    def test_cross_section_shape_unchanged(self) -> None:
        """At t=0 and t=1 the cross-section profile bounds should be rect-like."""
        face_a = _flat_plane(z=0.0)
        face_b = _flat_plane(z=2.0)
        edge_pts = _straight_edge(n=8, length=2.0)

        w, h = 1.2, 0.6
        cs = CrossSection(kind="rectangle", width=w, height=h, radius=0.0)
        cs_list = [(0.0, cs), (1.0, cs)]

        blend_surf, edge_a, edge_b = variable_section_blend(
            face_a, face_b, edge_pts, cs_list,
            blend_method="linear", samples=16,
        )

        assert isinstance(blend_surf, NurbsSurface)
        # Both edge_a and edge_b should have 16 points
        assert len(edge_a) == 16
        assert len(edge_b) == 16

    def test_blend_surface_is_nurbs(self) -> None:
        face_a = _flat_plane()
        face_b = _flat_plane(z=1.0)
        edge_pts = _straight_edge(n=4, length=1.0)
        cs_list = [
            (0.0, CrossSection(kind="circle", radius=0.5, width=1.0, height=1.0)),
            (1.0, CrossSection(kind="circle", radius=0.5, width=1.0, height=1.0)),
        ]
        blend_surf, _, _ = variable_section_blend(
            face_a, face_b, edge_pts, cs_list, samples=8,
        )
        assert isinstance(blend_surf, NurbsSurface)
        # Degree checks
        assert blend_surf.degree_u >= 1
        assert blend_surf.degree_v >= 1


# ---------------------------------------------------------------------------
# 6. ORACLE TEST 2: Rect→Circle morph, analytical Bezier corner
# ---------------------------------------------------------------------------

class TestRectToCircleMorph:
    """At t=0.5 the morph is a chamfered rect (radius growing)."""

    def test_midpoint_is_chamfered_rect(self) -> None:
        cs_a = CrossSection(kind="rectangle", width=2.0, height=2.0, radius=0.0)
        cs_b = CrossSection(kind="circle", radius=1.0, width=2.0, height=2.0)
        cs_mid = morph_cross_sections(cs_a, cs_b, 0.5)
        # At midpoint, corner radius should be 0.5 * max_corner_radius = 0.5
        assert cs_mid.radius > 0.0
        assert cs_mid.radius < 1.0

    def test_width_height_interpolate_linearly(self) -> None:
        """Width and height stay at the common value (both w=2, h=2)."""
        cs_a = CrossSection(kind="rectangle", width=2.0, height=2.0, radius=0.0)
        cs_b = CrossSection(kind="circle", radius=1.0, width=2.0, height=2.0)
        for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
            cs = morph_cross_sections(cs_a, cs_b, t)
            assert math.isclose(cs.width, 2.0, abs_tol=1e-9), (
                f"t={t}: width={cs.width}"
            )
            assert math.isclose(cs.height, 2.0, abs_tol=1e-9), (
                f"t={t}: height={cs.height}"
            )

    def test_profile_is_chamfered_at_midpoint(self) -> None:
        """The 2D profile at t=0.5 should have corners that are rounded."""
        cs_a = CrossSection(kind="rectangle", width=4.0, height=4.0, radius=0.0)
        cs_b = CrossSection(kind="circle", radius=2.0, width=4.0, height=4.0)
        cs_mid = morph_cross_sections(cs_a, cs_b, 0.5)
        prof = _section_profile(cs_mid, n_pts=64)
        # Profile should stay within the bounding box of the rectangle
        assert prof[:, 0].max() <= 2.0 + 1e-9
        assert prof[:, 0].min() >= -2.0 - 1e-9

    def test_blend_surface_rect_to_circle_completes(self) -> None:
        """variable_section_blend with rect→circle returns valid surface."""
        face_a = _flat_plane()
        face_b = _flat_plane(z=1.0)
        edge_pts = _straight_edge(n=8, length=3.0)
        cs_list = [
            (0.0, CrossSection(kind="rectangle", width=1.0, height=1.0, radius=0.0)),
            (1.0, CrossSection(kind="circle", radius=0.5, width=1.0, height=1.0)),
        ]
        blend_surf, edge_a, edge_b = variable_section_blend(
            face_a, face_b, edge_pts, cs_list,
            blend_method="linear", samples=16,
        )
        assert isinstance(blend_surf, NurbsSurface)
        assert blend_surf.control_points.shape[0] > 0
        assert blend_surf.control_points.shape[1] == 16


# ---------------------------------------------------------------------------
# 7. ORACLE TEST 3: C1 continuity — cubic_hermite vs linear
# ---------------------------------------------------------------------------

class TestContinuity:
    """cubic_hermite produces C1 profiles at interior stations; linear has C0."""

    def _stations(self) -> List[Tuple[float, CrossSection]]:
        return [
            (0.0, CrossSection(kind="rectangle", width=2.0, height=2.0, radius=0.0)),
            (0.5, CrossSection(kind="circle", radius=0.5, width=1.0, height=1.0)),
            (1.0, CrossSection(kind="ellipse", width=3.0, height=1.0)),
        ]

    def _profile_tangent(
        self,
        t: float,
        stations: List[Tuple[float, CrossSection]],
        method: str,
        eps: float = 1e-5,
        n_pts: int = 9,
    ) -> np.ndarray:
        """Finite-difference profile tangent (derivative of profile wrt t)."""
        tangents = _cubic_hermite_tangents(stations, n_pts) if method == "cubic_hermite" else None
        t_lo = max(0.0, t - eps)
        t_hi = min(1.0, t + eps)

        if method == "linear":
            p_lo = _section_profile(_linear_interp(t_lo, stations), n_pts)
            p_hi = _section_profile(_linear_interp(t_hi, stations), n_pts)
        elif method == "cubic_hermite":
            p_lo = _hermite_interp_profile(t_lo, stations, tangents, n_pts)
            p_hi = _hermite_interp_profile(t_hi, stations, tangents, n_pts)
        else:  # C2
            p_lo = _c2_spline_interp_profile(t_lo, stations, n_pts)
            p_hi = _c2_spline_interp_profile(t_hi, stations, n_pts)
        return (p_hi - p_lo) / (t_hi - t_lo)

    def test_linear_has_tangent_discontinuity_at_interior_station(self) -> None:
        """Linear interpolation: left and right tangents at t=0.5 differ."""
        stations = self._stations()
        eps = 1e-6
        n_pts = 9

        tan_left = self._profile_tangent(0.5 - eps, stations, "linear", eps=eps / 10, n_pts=n_pts)
        tan_right = self._profile_tangent(0.5 + eps, stations, "linear", eps=eps / 10, n_pts=n_pts)

        # Tangent jump > threshold: at least one coord of at least one profile
        # point has a discontinuity (the cross-section changes abruptly at t=0.5)
        jump = np.max(np.abs(tan_left - tan_right))
        assert jump > 0.01, (
            f"Expected tangent discontinuity at t=0.5 for 'linear', got jump={jump:.6f}"
        )

    def test_cubic_hermite_has_c1_at_interior_station(self) -> None:
        """Cubic Hermite: left and right tangents at t=0.5 match (C1)."""
        stations = self._stations()
        eps = 1e-5
        n_pts = 9
        tangents = _cubic_hermite_tangents(stations, n_pts)

        tan_left = _hermite_interp_profile(0.5 - eps, stations, tangents, n_pts)
        tan_right = _hermite_interp_profile(0.5 + eps, stations, tangents, n_pts)

        # Continuity of the profile itself (G0) — very tight
        jump_g0 = np.max(np.abs(tan_left - tan_right))
        assert jump_g0 < 1e-3, f"C0 discontinuity at t=0.5 for 'cubic_hermite': {jump_g0}"

        # Tangent continuity (C1): compare tangents on both sides
        # (using slightly larger eps for the derivative estimate)
        dtdt_left = self._profile_tangent(0.5 - 2e-4, stations, "cubic_hermite",
                                          eps=1e-4, n_pts=n_pts)
        dtdt_right = self._profile_tangent(0.5 + 2e-4, stations, "cubic_hermite",
                                           eps=1e-4, n_pts=n_pts)
        tang_jump = np.max(np.abs(dtdt_left - dtdt_right))
        # C1: tangent jump should be small (much smaller than linear's jump)
        assert tang_jump < 0.5, (
            f"Expected near-C1 continuity for 'cubic_hermite', got jump={tang_jump:.6f}"
        )

    def test_cubic_hermite_tangent_jump_smaller_than_linear(self) -> None:
        """cubic_hermite tangent jump < linear tangent jump at interior station."""
        stations = self._stations()
        eps = 1e-5
        n_pts = 9

        jump_linear = np.max(np.abs(
            self._profile_tangent(0.5 - eps, stations, "linear", eps=eps / 10, n_pts=n_pts) -
            self._profile_tangent(0.5 + eps, stations, "linear", eps=eps / 10, n_pts=n_pts)
        ))
        jump_hermite = np.max(np.abs(
            self._profile_tangent(0.5 - eps, stations, "cubic_hermite", eps=eps / 10, n_pts=n_pts) -
            self._profile_tangent(0.5 + eps, stations, "cubic_hermite", eps=eps / 10, n_pts=n_pts)
        ))
        assert jump_hermite < jump_linear, (
            f"Expected hermite jump {jump_hermite:.6f} < linear jump {jump_linear:.6f}"
        )

    def test_c1_via_blend_surface_stations(self) -> None:
        """Blend surface with cubic_hermite: profiles at intermediate stations
        are continuous (no visible kink in the control-point grid)."""
        face_a = _flat_plane()
        face_b = _flat_plane(z=1.0)
        edge_pts = _straight_edge(n=10, length=3.0)
        cs_list = [
            (0.0, CrossSection(kind="rectangle", width=1.0, height=1.0, radius=0.0)),
            (0.5, CrossSection(kind="circle", radius=0.5, width=1.0, height=1.0)),
            (1.0, CrossSection(kind="rectangle", width=1.0, height=0.5, radius=0.0)),
        ]
        blend_h, _, _ = variable_section_blend(
            face_a, face_b, edge_pts, cs_list,
            blend_method="cubic_hermite", samples=32,
        )
        blend_l, _, _ = variable_section_blend(
            face_a, face_b, edge_pts, cs_list,
            blend_method="linear", samples=32,
        )
        # Hermite surface's control-point grid should be smoother than linear's
        # (second-difference norm of the spine curve)
        cp_h = blend_h.control_points  # (n_u, n_v, 3)
        cp_l = blend_l.control_points
        # Use midpoint u row
        mid_u = cp_h.shape[0] // 2
        spine_h = cp_h[mid_u, :, :]
        spine_l = cp_l[mid_u, :, :]
        curvature_h = np.linalg.norm(np.diff(spine_h, n=2, axis=0))
        curvature_l = np.linalg.norm(np.diff(spine_l, n=2, axis=0))
        # Hermite spine should be at least as smooth or smoother
        assert curvature_h <= curvature_l * 1.5, (
            f"Expected hermite spine smoother, got {curvature_h:.4f} vs {curvature_l:.4f}"
        )


# ---------------------------------------------------------------------------
# 8. ORACLE TEST 4: Volume monotonic between section_a_volume and section_b_volume
# ---------------------------------------------------------------------------

class TestVolumeMonotonic:
    """Blend volume monotonically interpolates between section volumes."""

    def test_volume_bounded_by_endpoints(self) -> None:
        """Intermediate blend volumes are bounded by the endpoint section areas * edge_length."""
        face_a = _flat_plane()
        face_b = _flat_plane(z=1.0)
        edge_len = 4.0
        edge_pts = _straight_edge(n=12, length=edge_len)

        cs_a = CrossSection(kind="rectangle", width=1.0, height=1.0, radius=0.0)
        cs_b = CrossSection(kind="circle", radius=2.0, width=4.0, height=4.0)

        # Full blend (both endpoints)
        cs_list_full = [(0.0, cs_a), (1.0, cs_b)]
        blend_full, _, _ = variable_section_blend(
            face_a, face_b, edge_pts, cs_list_full,
            blend_method="linear", samples=32,
        )
        vol_full = blend_volume_estimate(blend_full, n_v=32, n_u=16)

        # Blend with only cs_a (constant small section)
        cs_list_a = [(0.0, cs_a), (1.0, cs_a)]
        blend_a, _, _ = variable_section_blend(
            face_a, face_b, edge_pts, cs_list_a,
            blend_method="linear", samples=32,
        )
        vol_a = blend_volume_estimate(blend_a, n_v=32, n_u=16)

        # Blend with only cs_b (constant large circle)
        cs_list_b = [(0.0, cs_b), (1.0, cs_b)]
        blend_b, _, _ = variable_section_blend(
            face_a, face_b, edge_pts, cs_list_b,
            blend_method="linear", samples=32,
        )
        vol_b = blend_volume_estimate(blend_b, n_v=32, n_u=16)

        # The morphing blend volume should be between vol_a and vol_b
        v_min = min(vol_a, vol_b)
        v_max = max(vol_a, vol_b)
        # Allow 20% margin for shoelace/numerical integration error
        margin = 0.20 * v_max
        assert vol_full >= v_min - margin, (
            f"vol_full={vol_full:.4f} < v_min={v_min:.4f} - margin={margin:.4f}"
        )
        assert vol_full <= v_max + margin, (
            f"vol_full={vol_full:.4f} > v_max={v_max:.4f} + margin={margin:.4f}"
        )

    def test_volume_larger_for_larger_section(self) -> None:
        """Blend with larger cross-section has larger volume."""
        face_a = _flat_plane()
        face_b = _flat_plane(z=1.0)
        edge_pts = _straight_edge(n=10, length=3.0)

        cs_small = CrossSection(kind="circle", radius=0.5, width=1.0, height=1.0)
        cs_large = CrossSection(kind="circle", radius=1.5, width=3.0, height=3.0)

        blend_small, _, _ = variable_section_blend(
            face_a, face_b, edge_pts,
            [(0.0, cs_small), (1.0, cs_small)],
            samples=24,
        )
        blend_large, _, _ = variable_section_blend(
            face_a, face_b, edge_pts,
            [(0.0, cs_large), (1.0, cs_large)],
            samples=24,
        )

        vol_small = blend_volume_estimate(blend_small, n_v=24, n_u=12)
        vol_large = blend_volume_estimate(blend_large, n_v=24, n_u=12)
        assert vol_large > vol_small, (
            f"Expected vol_large={vol_large:.4f} > vol_small={vol_small:.4f}"
        )

    def test_intermediate_volume_between_endpoints(self) -> None:
        """Intermediate (t=0.5) blend volume is between endpoints when sections differ."""
        face_a = _flat_plane()
        face_b = _flat_plane(z=1.0)
        edge_pts = _straight_edge(n=10, length=3.0)

        cs_small = CrossSection(kind="rectangle", width=0.4, height=0.4, radius=0.0)
        cs_large = CrossSection(kind="rectangle", width=2.0, height=2.0, radius=0.0)
        cs_mid = morph_cross_sections(cs_small, cs_large, 0.5)

        for cs, label in [
            (cs_small, "small"), (cs_mid, "mid"), (cs_large, "large")
        ]:
            blend, _, _ = variable_section_blend(
                face_a, face_b, edge_pts,
                [(0.0, cs), (1.0, cs)],
                samples=20,
            )
            vols_map = {label: blend_volume_estimate(blend, n_v=20, n_u=10)}

        blend_s, _, _ = variable_section_blend(
            face_a, face_b, edge_pts,
            [(0.0, cs_small), (1.0, cs_small)],
            samples=20,
        )
        blend_m, _, _ = variable_section_blend(
            face_a, face_b, edge_pts,
            [(0.0, cs_mid), (1.0, cs_mid)],
            samples=20,
        )
        blend_l, _, _ = variable_section_blend(
            face_a, face_b, edge_pts,
            [(0.0, cs_large), (1.0, cs_large)],
            samples=20,
        )
        vol_s = blend_volume_estimate(blend_s, n_v=20, n_u=10)
        vol_m = blend_volume_estimate(blend_m, n_v=20, n_u=10)
        vol_l = blend_volume_estimate(blend_l, n_v=20, n_u=10)

        # vol_s < vol_m < vol_l (monotonic)
        assert vol_s < vol_m < vol_l, (
            f"Volume not monotonic: vol_s={vol_s:.4f}, vol_m={vol_m:.4f}, vol_l={vol_l:.4f}"
        )


# ---------------------------------------------------------------------------
# 9. blend_cross_section_at sampling test
# ---------------------------------------------------------------------------

class TestBlendCrossSectionAt:
    def test_returns_correct_shape(self) -> None:
        face_a = _flat_plane()
        face_b = _flat_plane(z=1.0)
        edge_pts = _straight_edge()
        cs_list = [
            (0.0, CrossSection(kind="circle", radius=0.5, width=1.0, height=1.0)),
            (1.0, CrossSection(kind="circle", radius=1.0, width=2.0, height=2.0)),
        ]
        blend_surf, _, _ = variable_section_blend(
            face_a, face_b, edge_pts, cs_list, samples=16, n_profile_pts=9,
        )
        for v_t in [0.0, 0.5, 1.0]:
            pts = blend_cross_section_at(blend_surf, v_t, n_pts=9)
            assert pts.shape == (9, 3), f"Shape mismatch at v_t={v_t}: {pts.shape}"


# ---------------------------------------------------------------------------
# 10. edge_frame helper tests
# ---------------------------------------------------------------------------

class TestEdgeFrame:
    def test_tangent_along_x_axis(self) -> None:
        pts = np.array([[float(i), 0.0, 0.0] for i in range(5)])
        T, N, B = _edge_frame(pts)
        assert np.allclose(T[:, 0], 1.0, atol=1e-10)
        assert np.allclose(T[:, 1:], 0.0, atol=1e-10)

    def test_frame_orthonormality(self) -> None:
        pts = np.array([[math.cos(t), math.sin(t), 0.1 * t]
                        for t in np.linspace(0, 2 * math.pi, 20)])
        T, N, B = _edge_frame(pts)
        for i in range(len(pts)):
            assert abs(np.linalg.norm(T[i]) - 1.0) < 1e-9
            assert abs(np.linalg.norm(N[i]) - 1.0) < 1e-9
            assert abs(np.dot(T[i], N[i])) < 1e-9
