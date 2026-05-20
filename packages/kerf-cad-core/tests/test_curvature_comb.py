"""
test_curvature_comb.py
======================
GK-65: Curvature comb / porcupine numeric export validated vs analytic κ.

Oracle: for a circle of radius r, κ = 1/r at every sample to ≤1e-9.
"""
from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_cad_core.geom.nurbs import make_circle_nurbs, NurbsCurve, NurbsSurface
from kerf_cad_core.geom.curve_toolkit import curvature_comb, interp_curve
from kerf_cad_core.geom.surface_analysis import isocurve_curvature_comb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_circle(radius: float) -> NurbsCurve:
    """Exact 9-point rational NURBS circle."""
    return make_circle_nurbs(
        center=np.array([0.0, 0.0, 0.0]),
        radius=radius,
    )


def _make_cylindrical_surface(radius: float, height: float = 1.0) -> NurbsSurface:
    """
    Build a NurbsSurface that is a (partial) cylinder of given radius.
    The u direction sweeps angle in [0, pi/2], the v direction is the height.
    Each isocurve at fixed v is a circular arc; each isocurve at fixed u is a
    straight line.  Used to validate isocurve_curvature_comb.
    """
    from kerf_cad_core.geom.nurbs import NurbsSurface

    # Degree-2 exact quarter-circle arc in u; degree-1 (linear) in v.
    # Control points: 3 x 2 grid (3 in u for the quarter-arc, 2 in v).
    # Quarter-arc control points in the XY plane:
    #   P00 = (r, 0, 0),  P10 = (r, r, 0),  P20 = (0, r, 0)  (shoulder at (r,r))
    # Elevated in Z by v: P0v = P0 + v*Z, so 2 v-layers at z=0 and z=height.
    r = float(radius)
    h = float(height)
    w = math.sqrt(2.0) / 2.0  # weight for the conic shoulder point

    # homogeneous control points: shape (nu=3, nv=2, dim=4) for rational surface
    # We store as a plain NurbsSurface with weights applied in control_points[:,:,3]
    # Kerf NurbsSurface uses control_points shape (nu, nv, dim) with uniform weights=1
    # So we build a non-rational (polynomial) approximation: a swept arc via bilinear
    # interp — BUT for the oracle test we only need that curvature is constant,
    # so instead we build the surface from an exact circle sweep.

    # For simplicity: build a degree-1 x degree-1 bilinear surface at a coarse
    # grid that approximates a cylinder, then use isocurve_curvature_comb on the
    # v-isocurve (fixed v → horizontal arc), and compare to the circle test via
    # curve_toolkit directly.  The key test is that the curve-toolkit oracle
    # (circle of radius r) is the primary oracle.

    # Use a fine sampled cylinder, fit as a NurbsSurface via bilinear grid.
    nu_pts = 20
    nv_pts = 5
    angles = np.linspace(0.0, 2.0 * math.pi * 0.9, nu_pts)
    heights = np.linspace(0.0, h, nv_pts)

    ctrl_pts = np.zeros((nu_pts, nv_pts, 3))
    for i, angle in enumerate(angles):
        for j, z in enumerate(heights):
            ctrl_pts[i, j, :] = [r * math.cos(angle), r * math.sin(angle), z]

    # Uniform knots for degree 3 in u, degree 1 in v
    from kerf_cad_core.geom.curve_toolkit import _make_clamped_knots
    ku = _make_clamped_knots(nu_pts, 3)
    kv = _make_clamped_knots(nv_pts, 1)

    return NurbsSurface(
        degree_u=3,
        degree_v=1,
        control_points=ctrl_pts,
        knots_u=ku,
        knots_v=kv,
    )


# ---------------------------------------------------------------------------
# curvature_comb on a circle — primary oracle (GK-65)
# ---------------------------------------------------------------------------

class TestCurvatureCombCircleOracle:
    """Oracle: circle of radius r must yield κ = 1/r at every sample to 1e-9."""

    @pytest.mark.parametrize("radius", [0.5, 1.0, 2.0, 5.0, 0.1])
    def test_kappa_constant_at_1_over_r(self, radius: float):
        circle = _make_circle(radius)
        result = curvature_comb(circle, num_samples=100)

        assert result["ok"], f"curvature_comb failed: {result['reason']}"
        expected = 1.0 / radius
        kappas = result["kappas"]
        assert len(kappas) == 100

        for i, kappa in enumerate(kappas):
            assert abs(kappa - expected) < 1e-9, (
                f"radius={radius}: κ[{i}]={kappa:.15g} != 1/r={expected:.15g}, "
                f"diff={abs(kappa - expected):.3e}"
            )

    def test_result_structure(self):
        """Verify all output arrays are present and consistent length."""
        circle = _make_circle(1.0)
        result = curvature_comb(circle, num_samples=50)

        assert result["ok"]
        assert len(result["parameters"]) == 50
        assert len(result["points"]) == 50
        assert len(result["kappas"]) == 50
        assert len(result["normals"]) == 50
        assert len(result["tips"]) == 50

    def test_tips_offset_by_kappa_times_scale(self):
        """Tips = point + κ·scale·normal; check offset magnitude = κ·scale."""
        radius = 2.0
        scale = 3.0
        circle = _make_circle(radius)
        result = curvature_comb(circle, num_samples=30, scale=scale)

        assert result["ok"]
        kappa_expected = 1.0 / radius

        for i in range(len(result["points"])):
            pt = np.array(result["points"][i])
            tip = np.array(result["tips"][i])
            n_hat = np.array(result["normals"][i])
            kappa = result["kappas"][i]

            # offset vector should equal κ·scale·n_hat
            offset = tip - pt
            expected_offset = kappa * scale * n_hat
            err = float(np.linalg.norm(offset - expected_offset))
            assert err < 1e-12, f"tip offset mismatch at sample {i}: err={err:.3e}"

    def test_normals_unit_length(self):
        """Curvature normals must be unit vectors (except at singular points)."""
        circle = _make_circle(1.0)
        result = curvature_comb(circle, num_samples=50)

        assert result["ok"]
        for i, n in enumerate(result["normals"]):
            n_arr = np.array(n)
            mag = float(np.linalg.norm(n_arr))
            # Circle has non-zero curvature everywhere, so normal must be unit
            assert abs(mag - 1.0) < 1e-9, (
                f"normal[{i}] magnitude={mag:.15g} != 1.0"
            )

    def test_normals_point_toward_center(self):
        """For a circle centred at origin the curvature normal must point toward origin."""
        radius = 3.0
        circle = _make_circle(radius)
        result = curvature_comb(circle, num_samples=30)

        assert result["ok"]
        for i in range(len(result["points"])):
            pt = np.array(result["points"][i][:2])  # XY only
            n_hat = np.array(result["normals"][i][:2])
            # n_hat should be anti-parallel to the radial direction
            radial = pt / (np.linalg.norm(pt) + 1e-300)
            dot = float(np.dot(n_hat, radial))
            # For a standard circle the curvature normal is inward (dot ≈ -1)
            assert dot < -0.99, (
                f"normal[{i}] not pointing toward centre: dot={dot:.4f}"
            )


# ---------------------------------------------------------------------------
# curvature_comb on a straight line — zero curvature
# ---------------------------------------------------------------------------

class TestCurvatureCombLine:
    def test_zero_kappa_on_line(self):
        """A straight-line NURBS has κ = 0 everywhere."""
        from kerf_cad_core.geom.nurbs import make_line_nurbs
        line = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([5.0, 0.0, 0.0]))
        result = curvature_comb(line, num_samples=20)

        assert result["ok"]
        for i, kappa in enumerate(result["kappas"]):
            assert kappa < 1e-10, f"line κ[{i}]={kappa:.3e} should be ~0"


# ---------------------------------------------------------------------------
# curvature_comb API robustness
# ---------------------------------------------------------------------------

class TestCurvatureCombAPI:
    def test_num_samples_respected(self):
        circle = _make_circle(1.0)
        for n in [5, 20, 200]:
            result = curvature_comb(circle, num_samples=n)
            assert result["ok"]
            assert len(result["kappas"]) == n

    def test_scale_zero_gives_tips_equal_points(self):
        """scale=0 means comb tips coincide with curve points."""
        circle = _make_circle(1.0)
        result = curvature_comb(circle, num_samples=20, scale=0.0)
        assert result["ok"]
        for pt, tip in zip(result["points"], result["tips"]):
            err = float(np.linalg.norm(np.array(tip) - np.array(pt)))
            assert err < 1e-12

    def test_polynomial_curve_returns_ok(self):
        """A degree-3 interpolated curve returns ok=True."""
        pts = [[math.cos(t), math.sin(t), 0.0] for t in np.linspace(0, math.pi, 20)]
        curve = interp_curve(pts, degree=3)
        result = curvature_comb(curve, num_samples=30)
        assert result["ok"]
        assert all(k >= 0.0 for k in result["kappas"])


# ---------------------------------------------------------------------------
# isocurve_curvature_comb (surface porcupine) — structural tests
# ---------------------------------------------------------------------------

class TestIsocurveCurvatureComb:
    def test_returns_ok_on_valid_surface(self):
        surf = _make_cylindrical_surface(radius=2.0)
        result = isocurve_curvature_comb(surf, parameter=0.5, direction="v", num_samples=30)
        assert result["ok"], f"isocurve_curvature_comb failed: {result['reason']}"

    def test_output_lengths_consistent(self):
        surf = _make_cylindrical_surface(radius=1.0)
        n = 25
        result = isocurve_curvature_comb(surf, parameter=0.5, direction="v", num_samples=n)
        assert result["ok"]
        assert len(result["parameters"]) == n
        assert len(result["points"]) == n
        assert len(result["kappas"]) == n
        assert len(result["normals"]) == n
        assert len(result["tips"]) == n

    def test_tips_formula(self):
        """tips[i] = points[i] + kappas[i] * scale * normals[i]."""
        surf = _make_cylindrical_surface(radius=1.5)
        scale = 2.0
        result = isocurve_curvature_comb(
            surf, parameter=0.5, direction="v", num_samples=20, scale=scale
        )
        assert result["ok"]
        for i in range(len(result["points"])):
            pt = np.array(result["points"][i])
            tip = np.array(result["tips"][i])
            n_hat = np.array(result["normals"][i])
            kappa = result["kappas"][i]
            expected_tip = pt + kappa * scale * n_hat
            err = float(np.linalg.norm(tip - expected_tip))
            assert err < 1e-11, f"tip formula violation at sample {i}: err={err:.3e}"

    def test_bad_surface_type_returns_not_ok(self):
        result = isocurve_curvature_comb("not_a_surface", parameter=0.5)
        assert not result["ok"]
        assert result["reason"] != ""

    def test_bad_direction_returns_not_ok(self):
        surf = _make_cylindrical_surface(radius=1.0)
        result = isocurve_curvature_comb(surf, parameter=0.5, direction="w")
        assert not result["ok"]

    def test_u_and_v_directions(self):
        """Both u and v isocurve directions should succeed."""
        surf = _make_cylindrical_surface(radius=1.0)
        for direction in ("u", "v"):
            result = isocurve_curvature_comb(surf, parameter=0.5, direction=direction, num_samples=15)
            assert result["ok"], f"direction={direction} failed: {result['reason']}"

    def test_nonnegative_kappas(self):
        """Scalar curvature must be non-negative."""
        surf = _make_cylindrical_surface(radius=2.0)
        result = isocurve_curvature_comb(surf, parameter=0.5, direction="v", num_samples=30)
        assert result["ok"]
        for i, k in enumerate(result["kappas"]):
            assert k >= -1e-12, f"κ[{i}]={k:.3e} < 0"


# ---------------------------------------------------------------------------
# curvature_comb exported from geom __init__
# ---------------------------------------------------------------------------

class TestGeomInitExports:
    def test_curvature_comb_importable_from_geom(self):
        from kerf_cad_core.geom import curvature_comb as cc
        assert callable(cc)

    def test_isocurve_curvature_comb_importable_from_geom(self):
        from kerf_cad_core.geom import isocurve_curvature_comb as icc
        assert callable(icc)

    def test_curvature_comb_oracle_via_init_import(self):
        """Re-run the circle oracle using the __init__ export path."""
        from kerf_cad_core.geom import curvature_comb as cc
        radius = 1.5
        circle = _make_circle(radius)
        result = cc(circle, num_samples=50)
        assert result["ok"]
        expected = 1.0 / radius
        for i, kappa in enumerate(result["kappas"]):
            assert abs(kappa - expected) < 1e-9, (
                f"κ[{i}]={kappa:.15g} != {expected:.15g}"
            )
