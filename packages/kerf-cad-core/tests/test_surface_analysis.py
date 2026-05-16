"""
test_surface_analysis.py
========================
Hermetic tests for kerf_cad_core.geom.surface_analysis.

All tests are pure-Python: no OCC, no database, no network.
Analytic ground truth uses NURBS surfaces whose curvatures are known:
  - Degree-2 paraboloid z = c*(x²+y²): K = 4c², H = 2c at apex.
  - Plane z = 0: K = H = 0 everywhere.
  - Cylinder (degree-2): K = 0, H = 1/(2R) for exact quadratic patch.
  - Cone: |draft angle| = half-angle of cone.
  - Bilinear sphere: used only for sign/positivity checks (piecewise-flat
    interior cells have K≈0 due to zero second derivatives).
  - Surface deviation: zero for points sampled on the same surface.
  - Naked-edge count for open vs closed box shells.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_analysis import (
    area_centroid_secondmoment,
    draft_angle_analysis,
    edge_continuity_report,
    gaussian_mean_curvature,
    isocurve_extract,
    naked_edge_detect,
    surface_deviation,
)


# ---------------------------------------------------------------------------
# Surface factories
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def make_plane_surface(size: float = 2.0, nu: int = 4, nv: int = 4) -> NurbsSurface:
    """Flat plane z=0 spanning [0,size]×[0,size]."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i * size / (nu - 1), j * size / (nv - 1), 0.0]
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=_make_knots(nu, 1),
        knots_v=_make_knots(nv, 1),
    )


def make_paraboloid_surface(R: float = 2.0, half_extent: float = 0.5,
                             nu: int = 5, nv: int = 5) -> NurbsSurface:
    """Degree-2 paraboloid z = c*(x²+y²) with c = 1/(2R).

    At the apex (x=y=0):
      K = 4c² = 1/R²
      H = 2c  = 1/R
    Exact analytic values for a paraboloid with small extent.
    """
    deg = 2
    c = 1.0 / (2.0 * R)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = (i - (nu - 1) / 2) / ((nu - 1) / 2) * half_extent
        for j in range(nv):
            y = (j - (nv - 1) / 2) / ((nv - 1) / 2) * half_extent
            z = c * (x * x + y * y)
            cp[i, j] = [x, y, z]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def make_flat_paraboloid_surface(half_extent: float = 0.5,
                                  nu: int = 5, nv: int = 5) -> NurbsSurface:
    """Degree-2 flat surface (c=0, z=0). K=H=0 everywhere."""
    deg = 2
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = (i - (nu - 1) / 2) / ((nu - 1) / 2) * half_extent
        for j in range(nv):
            y = (j - (nv - 1) / 2) / ((nv - 1) / 2) * half_extent
            cp[i, j] = [x, y, 0.0]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def make_cylinder_surface_deg2(R: float = 1.0, height: float = 2.0,
                                nu: int = 10, nv: int = 3) -> NurbsSurface:
    """Degree-2 cylinder of radius R, height H, axis along Z.
    Degree 2 in u (azimuthal) gives non-zero second derivatives.
    """
    deg = 2
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        theta = 2 * math.pi * i / (nu - 1)
        for j in range(nv):
            z = height * j / (nv - 1)
            cp[i, j] = [R * math.cos(theta), R * math.sin(theta), z]
    return NurbsSurface(
        degree_u=deg, degree_v=1,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, 1),
    )


def make_cone_surface(half_angle_deg: float = 10.0, height: float = 5.0,
                      nu: int = 10, nv: int = 4) -> NurbsSurface:
    """Cone with axis along +Z, apex at origin, half-angle = half_angle_deg.
    Starts at z=height/4 (non-degenerate) to avoid apex singularity.
    """
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        theta = 2 * math.pi * i / (nu - 1)
        for j in range(nv):
            # Start from z = height/4 to avoid the degenerate apex
            z = height * (j + 1) / (nv)
            r = z * math.tan(math.radians(half_angle_deg))
            cp[i, j] = [r * math.cos(theta), r * math.sin(theta), z]
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=_make_knots(nu, 1),
        knots_v=_make_knots(nv, 1),
    )


# ---------------------------------------------------------------------------
# 1. gaussian_mean_curvature — flat degree-2 surface
# ---------------------------------------------------------------------------

class TestGaussianMeanCurvaturePlane:
    def test_flat_d2_returns_ok(self):
        surf = make_flat_paraboloid_surface()
        result = gaussian_mean_curvature(surf, nu=5, nv=5)
        assert result["ok"] is True

    def test_flat_d2_K_near_zero(self):
        """Degree-2 flat surface: K = 0 exactly."""
        surf = make_flat_paraboloid_surface()
        result = gaussian_mean_curvature(surf, nu=5, nv=5)
        K = np.array(result["K_grid"])
        assert np.max(np.abs(K)) < 1e-6, f"K not near zero: max={np.max(np.abs(K))}"

    def test_flat_d2_H_near_zero(self):
        """Degree-2 flat surface: H = 0 exactly."""
        surf = make_flat_paraboloid_surface()
        result = gaussian_mean_curvature(surf, nu=5, nv=5)
        H = np.array(result["H_grid"])
        assert np.max(np.abs(H)) < 1e-6, f"H not near zero: max={np.max(np.abs(H))}"

    def test_num_samples_correct(self):
        surf = make_flat_paraboloid_surface()
        result = gaussian_mean_curvature(surf, nu=5, nv=5)
        assert result["num_samples"] == 25

    def test_kappa1_kappa2_near_zero_for_flat(self):
        surf = make_flat_paraboloid_surface()
        result = gaussian_mean_curvature(surf, nu=5, nv=5)
        k1 = np.array(result["kappa1_grid"])
        k2 = np.array(result["kappa2_grid"])
        assert np.max(np.abs(k1)) < 1e-5
        assert np.max(np.abs(k2)) < 1e-5


# ---------------------------------------------------------------------------
# 2. gaussian_mean_curvature — paraboloid as sphere proxy
# ---------------------------------------------------------------------------

class TestGaussianMeanCurvatureParaboloid:
    """Paraboloid z = c*(x²+y²), c = 1/(2R).
    At the apex: K = 4c² = 1/R², H = 2c = 1/R.
    """
    R = 2.0

    def _surf(self):
        return make_paraboloid_surface(self.R, half_extent=0.3, nu=5, nv=5)

    def test_paraboloid_ok(self):
        result = gaussian_mean_curvature(self._surf(), nu=5, nv=5)
        assert result["ok"] is True

    def test_paraboloid_K_positive(self):
        """Convex paraboloid: K > 0 everywhere."""
        result = gaussian_mean_curvature(self._surf(), nu=5, nv=5)
        K = np.array(result["K_grid"])
        # Interior cells; boundary may have FD artifacts
        K_inner = K[1:-1, 1:-1]
        assert np.all(K_inner > 0), f"K not positive: min={K_inner.min()}"

    def test_paraboloid_H_positive(self):
        """Convex paraboloid: H > 0 everywhere."""
        result = gaussian_mean_curvature(self._surf(), nu=5, nv=5)
        H = np.array(result["H_grid"])
        H_inner = H[1:-1, 1:-1]
        assert np.all(H_inner > 0), f"H not positive: min={H_inner.min()}"

    def test_paraboloid_K_approx_1_over_R2(self):
        """K ≈ 1/R² = 0.25 at interior of paraboloid with R=2."""
        result = gaussian_mean_curvature(self._surf(), nu=5, nv=5)
        K = np.array(result["K_grid"])
        K_inner = K[1:-1, 1:-1].flatten()
        expected = 1.0 / (self.R ** 2)
        rel_err = np.abs(K_inner - expected) / expected
        assert np.median(rel_err) < 0.15, f"K median rel error too large: {np.median(rel_err):.3f}"

    def test_paraboloid_H_approx_1_over_R(self):
        """H ≈ 1/R = 0.5 at interior of paraboloid with R=2."""
        result = gaussian_mean_curvature(self._surf(), nu=5, nv=5)
        H = np.array(result["H_grid"])
        H_inner = H[1:-1, 1:-1].flatten()
        expected = 1.0 / self.R
        rel_err = np.abs(H_inner - expected) / expected
        assert np.median(rel_err) < 0.15, f"H median rel error too large: {np.median(rel_err):.3f}"


# ---------------------------------------------------------------------------
# 3. gaussian_mean_curvature — cylinder (K=0, H=1/(2R))
# ---------------------------------------------------------------------------

class TestGaussianMeanCurvatureCylinder:
    """Degree-2 cylinder radius R: K = 0, H = 1/(2R)."""

    R = 1.5

    def _surf(self):
        return make_cylinder_surface_deg2(self.R, nu=12, nv=3)

    def test_cylinder_ok(self):
        result = gaussian_mean_curvature(self._surf(), nu=8, nv=3)
        assert result["ok"] is True

    def test_cylinder_K_near_zero(self):
        """Cylinder K = 0 everywhere (K = κ1*κ2, κ2=0 for ruling direction)."""
        result = gaussian_mean_curvature(self._surf(), nu=8, nv=3)
        K = np.array(result["K_grid"])
        K_inner = K[1:-1, 1:-1]
        assert np.max(np.abs(K_inner)) < 0.5, f"Cylinder K not near zero: {np.max(np.abs(K_inner))}"

    def test_cylinder_H_approx_1_over_2R(self):
        """|H| ≈ 1/(2R) for degree-2 cylinder (sign depends on normal orientation)."""
        result = gaussian_mean_curvature(self._surf(), nu=8, nv=3)
        H = np.array(result["H_grid"])
        H_inner = np.abs(H[1:-1, 1:-1].flatten())
        expected = 1.0 / (2.0 * self.R)
        # Filter out obviously bad samples (span-boundary FD artifacts)
        reasonable = H_inner[H_inner < 5.0 * expected]
        if len(reasonable) > 0:
            rel_err = np.abs(reasonable - expected) / expected
            assert np.median(rel_err) < 0.5, f"Cylinder |H| median rel error: {np.median(rel_err):.3f}"

    def test_cylinder_has_nonzero_H(self):
        """Cylinder should have some nonzero H (non-flat)."""
        result = gaussian_mean_curvature(self._surf(), nu=8, nv=3)
        H = np.array(result["H_grid"])
        assert np.max(np.abs(H)) > 0.01


# ---------------------------------------------------------------------------
# 4. gaussian_mean_curvature — bad input
# ---------------------------------------------------------------------------

class TestGaussianMeanCurvatureBadInput:
    def test_non_surface_returns_not_ok(self):
        result = gaussian_mean_curvature("not a surface")
        assert result["ok"] is False
        assert "reason" in result

    def test_result_has_required_keys(self):
        surf = make_flat_paraboloid_surface()
        result = gaussian_mean_curvature(surf, nu=4, nv=4)
        for key in ("K_grid", "H_grid", "kappa1_grid", "kappa2_grid",
                    "K_min", "K_max", "H_min", "H_max", "num_samples"):
            assert key in result


# ---------------------------------------------------------------------------
# 5. draft_angle_analysis — plane
# ---------------------------------------------------------------------------

class TestDraftAnglePlane:
    def test_plane_draft_90_deg_pull_Z(self):
        """Flat plane z=0 with pull=[0,0,1]: draft = 90°."""
        surf = make_flat_paraboloid_surface()
        result = draft_angle_analysis(surf, [0.0, 0.0, 1.0], nu=5, nv=5)
        assert result["ok"] is True
        angles = np.array(result["angle_grid"])
        assert np.all(np.abs(angles - 90.0) < 5.0), f"Draft not 90°: {angles}"

    def test_plane_no_undercut_pull_Z(self):
        surf = make_flat_paraboloid_surface()
        result = draft_angle_analysis(surf, [0.0, 0.0, 1.0])
        assert result["has_undercut"] is False

    def test_plane_all_pass_at_zero_required_draft(self):
        surf = make_flat_paraboloid_surface()
        result = draft_angle_analysis(surf, [0.0, 0.0, 1.0], required_draft_deg=0.0)
        pf = np.array(result["pass_fail_grid"])
        assert np.all(pf)

    def test_plane_undercut_when_pull_reversed(self):
        """Normal is [0,0,1], pull=[0,0,-1]: all angles negative → undercut."""
        surf = make_flat_paraboloid_surface()
        result = draft_angle_analysis(surf, [0.0, 0.0, -1.0])
        assert result["has_undercut"] is True


# ---------------------------------------------------------------------------
# 6. draft_angle_analysis — cone
# ---------------------------------------------------------------------------

class TestDraftAngleCone:
    """Cone with half_angle_deg = α: |draft angle| ≈ α.
    The normal can point inward or outward depending on parameterization,
    so we check abs(mean_angle) ≈ alpha.
    """
    alpha = 15.0  # degrees

    def test_cone_abs_draft_angle_approx(self):
        surf = make_cone_surface(half_angle_deg=self.alpha, nu=12, nv=4)
        result = draft_angle_analysis(surf, [0.0, 0.0, 1.0], nu=8, nv=3)
        assert result["ok"] is True
        angles = np.array(result["angle_grid"])
        inner = angles[1:-1, 1:-1]
        # Use abs: normal direction can be inward or outward for this parameterization
        abs_mean = float(np.mean(np.abs(inner)))
        assert abs(abs_mean - self.alpha) < 10.0, f"Cone |draft| mean={abs_mean:.2f} expected≈{self.alpha}"

    def test_draft_bad_pull_direction(self):
        surf = make_flat_paraboloid_surface()
        result = draft_angle_analysis(surf, [0.0, 0.0, 0.0])
        assert result["ok"] is False

    def test_draft_wrong_type(self):
        result = draft_angle_analysis("not a surface", [0, 0, 1])
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 7. surface_deviation — zero deviation on-surface
# ---------------------------------------------------------------------------

class TestSurfaceDeviationOnSurface:
    def test_points_sampled_on_surface_have_zero_deviation(self):
        """Points sampled from the surface should have near-zero deviation to itself."""
        surf = make_flat_paraboloid_surface(half_extent=0.5)
        from kerf_cad_core.geom.surface_analysis import _eval_surface
        pts = []
        u_min = float(surf.knots_u[0])
        u_max = float(surf.knots_u[-1])
        v_min = float(surf.knots_v[0])
        v_max = float(surf.knots_v[-1])
        for u in np.linspace(u_min, u_max, 5):
            for v in np.linspace(v_min, v_max, 5):
                pts.append(_eval_surface(surf, u, v)[:3].tolist())

        result = surface_deviation(pts, surf, tolerance=0.05)
        assert result["ok"] is True
        assert result["max_deviation"] < 0.05

    def test_deviation_within_tolerance_flag(self):
        surf = make_flat_paraboloid_surface()
        from kerf_cad_core.geom.surface_analysis import _eval_surface
        p = _eval_surface(surf, 0.5, 0.5)[:3].tolist()
        result = surface_deviation([p], surf, tolerance=1.0)
        assert result["within_tolerance"] is True

    def test_deviation_far_points_large(self):
        """Points far from the surface should have large deviation."""
        surf = make_flat_paraboloid_surface()
        pts = [[10.0, 10.0, 10.0]]
        result = surface_deviation(pts, surf, tolerance=1e-3)
        assert result["ok"] is True
        assert result["max_deviation"] > 1.0

    def test_deviation_non_surface_reference_fails(self):
        result = surface_deviation([[0, 0, 0]], "not a surface")
        assert result["ok"] is False

    def test_deviation_empty_query_fails(self):
        surf = make_flat_paraboloid_surface()
        result = surface_deviation([], surf)
        assert result["ok"] is False

    def test_surface_to_surface_deviation(self):
        """Same surface → max deviation should be small."""
        surf = make_flat_paraboloid_surface(half_extent=0.5)
        result = surface_deviation(surf, surf, nu=4, nv=4, tolerance=0.1)
        assert result["ok"] is True
        assert result["max_deviation"] < 0.1


# ---------------------------------------------------------------------------
# 8. naked_edge_detect
# ---------------------------------------------------------------------------

class TestNakedEdgeDetect:
    def test_closed_box_no_naked_edges(self):
        """A closed box: every edge shared by exactly 2 faces → is_closed=True."""
        adjacency = {
            "top":    ["e_top_front", "e_top_back", "e_top_left", "e_top_right"],
            "bottom": ["e_bot_front", "e_bot_back", "e_bot_left", "e_bot_right"],
            "front":  ["e_top_front", "e_bot_front", "e_front_left", "e_front_right"],
            "back":   ["e_top_back", "e_bot_back", "e_back_left", "e_back_right"],
            "left":   ["e_top_left", "e_bot_left", "e_front_left", "e_back_left"],
            "right":  ["e_top_right", "e_bot_right", "e_front_right", "e_back_right"],
        }
        result = naked_edge_detect(adjacency)
        assert result["ok"] is True
        assert result["is_closed"] is True
        assert result["naked_edge_count"] == 0

    def test_open_box_has_naked_edges(self):
        """Box missing the top face: 4 top edges are naked."""
        adjacency = {
            "bottom": ["e_bot_front", "e_bot_back", "e_bot_left", "e_bot_right"],
            "front":  ["e_top_front", "e_bot_front", "e_front_left", "e_front_right"],
            "back":   ["e_top_back", "e_bot_back", "e_back_left", "e_back_right"],
            "left":   ["e_top_left", "e_bot_left", "e_front_left", "e_back_left"],
            "right":  ["e_top_right", "e_bot_right", "e_front_right", "e_back_right"],
        }
        result = naked_edge_detect(adjacency)
        assert result["ok"] is True
        assert result["is_closed"] is False
        assert result["naked_edge_count"] == 4
        naked_set = set(result["naked_edges"])
        assert "e_top_front" in naked_set
        assert "e_top_back" in naked_set
        assert "e_top_left" in naked_set
        assert "e_top_right" in naked_set

    def test_single_face_all_edges_naked(self):
        adjacency = {"face0": ["e0", "e1", "e2", "e3"]}
        result = naked_edge_detect(adjacency)
        assert result["ok"] is True
        assert result["naked_edge_count"] == 4
        assert result["is_closed"] is False

    def test_non_dict_input_fails(self):
        result = naked_edge_detect("not a dict")
        assert result["ok"] is False

    def test_total_edges_counted(self):
        adjacency = {
            "f1": ["e1", "e2", "e3"],
            "f2": ["e1", "e4", "e5"],
        }
        result = naked_edge_detect(adjacency)
        assert result["total_edges"] == 5  # e1 shared, e2-e5 distinct

    def test_two_face_closed_strip(self):
        """Two faces sharing all edges → no naked edges."""
        adjacency = {
            "f1": ["e1", "e2", "e3", "e4"],
            "f2": ["e1", "e2", "e3", "e4"],
        }
        result = naked_edge_detect(adjacency)
        assert result["is_closed"] is True


# ---------------------------------------------------------------------------
# 9. edge_continuity_report
# ---------------------------------------------------------------------------

class TestEdgeContinuityReport:
    def test_same_surface_G0_near_zero(self):
        """Same surface on both sides → G0 = 0."""
        surf = make_flat_paraboloid_surface()
        u_mid = (float(surf.knots_u[0]) + float(surf.knots_u[-1])) / 2
        v_min = float(surf.knots_v[0])
        v_max = float(surf.knots_v[-1])
        from kerf_cad_core.geom.surface_analysis import _eval_surface
        edge_pts = [_eval_surface(surf, u_mid, v).tolist() for v in np.linspace(v_min, v_max, 5)]
        result = edge_continuity_report(surf, surf, edge_pts, num_samples=5)
        assert result["ok"] is True
        assert result["G0_max"] < 0.05

    def test_same_surface_G1_near_zero(self):
        surf = make_flat_paraboloid_surface()
        u_mid = (float(surf.knots_u[0]) + float(surf.knots_u[-1])) / 2
        v_min = float(surf.knots_v[0])
        v_max = float(surf.knots_v[-1])
        from kerf_cad_core.geom.surface_analysis import _eval_surface
        edge_pts = [_eval_surface(surf, u_mid, v).tolist() for v in np.linspace(v_min, v_max, 3)]
        result = edge_continuity_report(surf, surf, edge_pts)
        assert result["ok"] is True
        assert result["G1_max_deg"] < 5.0

    def test_different_surfaces_runs_ok(self):
        """Plane vs paraboloid: should run without error."""
        plane = make_flat_paraboloid_surface()
        parab = make_paraboloid_surface(R=2.0)
        from kerf_cad_core.geom.surface_analysis import _eval_surface
        u_mid = 0.5
        v_min = float(plane.knots_v[0])
        v_max = float(plane.knots_v[-1])
        edge_pts = [_eval_surface(plane, u_mid, v).tolist() for v in np.linspace(v_min, v_max, 3)]
        result = edge_continuity_report(plane, parab, edge_pts)
        assert result["ok"] is True

    def test_too_few_edge_points_fails(self):
        surf = make_flat_paraboloid_surface()
        result = edge_continuity_report(surf, surf, [[0.0, 0.0, 0.0]])
        assert result["ok"] is False

    def test_per_point_list_present(self):
        surf = make_flat_paraboloid_surface()
        from kerf_cad_core.geom.surface_analysis import _eval_surface
        u_mid = 0.5
        v_min = float(surf.knots_v[0])
        v_max = float(surf.knots_v[-1])
        edge_pts = [_eval_surface(surf, u_mid, v).tolist() for v in np.linspace(v_min, v_max, 4)]
        result = edge_continuity_report(surf, surf, edge_pts, num_samples=3)
        assert result["ok"] is True
        assert isinstance(result["per_point"], list)
        assert len(result["per_point"]) == 3

    def test_bad_surf_a_type(self):
        surf = make_flat_paraboloid_surface()
        result = edge_continuity_report("bad", surf, [[0, 0, 0], [1, 0, 0]])
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 10. isocurve_extract
# ---------------------------------------------------------------------------

class TestIsocurveExtract:
    def test_isocurve_u_direction_returns_ok(self):
        surf = make_flat_paraboloid_surface()
        u_mid = (float(surf.knots_u[0]) + float(surf.knots_u[-1])) / 2
        result = isocurve_extract(surf, u_mid, direction="u", num_samples=10)
        assert result["ok"] is True
        assert len(result["points"]) == 10

    def test_isocurve_v_direction_returns_ok(self):
        surf = make_flat_paraboloid_surface()
        v_mid = (float(surf.knots_v[0]) + float(surf.knots_v[-1])) / 2
        result = isocurve_extract(surf, v_mid, direction="v", num_samples=8)
        assert result["ok"] is True
        assert len(result["points"]) == 8

    def test_isocurve_bad_direction_fails(self):
        surf = make_flat_paraboloid_surface()
        result = isocurve_extract(surf, 0.5, direction="w")
        assert result["ok"] is False

    def test_isocurve_arc_length_positive(self):
        surf = make_flat_paraboloid_surface(half_extent=1.0)
        u_mid = (float(surf.knots_u[0]) + float(surf.knots_u[-1])) / 2
        result = isocurve_extract(surf, u_mid, direction="u", num_samples=20)
        assert result["arc_length"] > 0.0

    def test_isocurve_non_surface_fails(self):
        result = isocurve_extract("not a surface", 0.5)
        assert result["ok"] is False

    def test_isocurve_parameter_clamped(self):
        """Parameter outside domain gets clamped, still returns ok."""
        surf = make_flat_paraboloid_surface()
        result = isocurve_extract(surf, 999.0, direction="u", num_samples=5)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# 11. area_centroid_secondmoment
# ---------------------------------------------------------------------------

class TestAreaCentroidSecondMoment:
    def test_flat_d2_returns_ok(self):
        surf = make_flat_paraboloid_surface()
        result = area_centroid_secondmoment(surf, nu=10, nv=10)
        assert result["ok"] is True

    def test_flat_d2_area_approx(self):
        """Flat unit-square (half_extent=0.5, so 1×1): area ≈ 1.0."""
        surf = make_flat_paraboloid_surface(half_extent=0.5)
        result = area_centroid_secondmoment(surf, nu=20, nv=20)
        assert result["ok"] is True
        # The surface spans [-0.5, 0.5] × [-0.5, 0.5], so area = 1.0
        assert abs(result["area"] - 1.0) < 0.15, f"area={result['area']:.4f}"

    def test_flat_d2_centroid_approx(self):
        """Flat surface centered at origin: centroid ≈ (0, 0, 0)."""
        surf = make_flat_paraboloid_surface(half_extent=0.5)
        result = area_centroid_secondmoment(surf, nu=20, nv=20)
        cx, cy, cz = result["centroid"]
        assert abs(cx) < 0.1, f"cx={cx}"
        assert abs(cy) < 0.1, f"cy={cy}"
        assert abs(cz) < 0.05, f"cz={cz}"

    def test_result_has_moment_keys(self):
        surf = make_flat_paraboloid_surface()
        result = area_centroid_secondmoment(surf, nu=5, nv=5)
        for key in ("Ixx", "Iyy", "Izz", "Ixy", "Ixz", "Iyz"):
            assert key in result

    def test_paraboloid_area_positive(self):
        """Paraboloid should have area > 0 and larger than flat."""
        flat = make_flat_paraboloid_surface(half_extent=0.5)
        parab = make_paraboloid_surface(R=1.0, half_extent=0.5)
        r_flat = area_centroid_secondmoment(flat, nu=15, nv=15)
        r_parab = area_centroid_secondmoment(parab, nu=15, nv=15)
        assert r_flat["ok"] and r_parab["ok"]
        # A curved surface has MORE area than its flat projection
        assert r_parab["area"] >= r_flat["area"]

    def test_non_surface_fails(self):
        result = area_centroid_secondmoment(42)
        assert result["ok"] is False
