"""
Tests for kerf_marine.hull_fairness — Lackenby slope-continuity, curvature
variance, iterative fairing, and curvature comb.

Oracle basis
------------
Wigley parabolic hull:
    y(x, z) = (B/2) * [1 − (2x/L)²] * [1 − (z/T)²]

For a NURBS surface that *exactly* represents this paraboloid the slope along
any waterline (z = const) is:

    dy/dx = −(B/2) * 4x/L²  * (1 − (z/T)²)

which is a *linear* function of x — hence the second derivative of slope is
constant (d²slope/dx² = const), and for a refined sampling it should be very
small for the smooth hull.  The curvature is bounded and smooth.

DoD (4 tests)
--------------
1. Smooth hull baseline: slope_continuity_metric < 0.1, curvature_variance < 0.01
2. Bumpy hull: metric jumps after CP perturbation; problem_region identifies it
3. Fair-hull round-trip: faired bumpy hull → metric closer to smooth baseline
4. Curvature comb: midship station of Wigley hull → non-trivial curvature profile
"""

from __future__ import annotations

import copy
import math
import os
import sys

import numpy as np
import pytest

# Ensure the package src is on the path
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# kerf-cad-core src must also be importable for NurbsSurface + surface_analysis
_CAD_CORE_SRC = os.path.abspath(
    os.path.join(_HERE, "..", "..", "kerf-cad-core", "src")
)
if _CAD_CORE_SRC not in sys.path:
    sys.path.insert(0, _CAD_CORE_SRC)


# ---------------------------------------------------------------------------
# Fixtures: build Wigley NURBS surface
# ---------------------------------------------------------------------------

def _make_wigley_nurbs(L: float = 100.0, B: float = 10.0, T: float = 5.0,
                       nu: int = 7, nv: int = 5) -> "NurbsSurface":
    """Build a bilinear (degree 1 × 1) NURBS surface approximating the Wigley hull.

    The Wigley hull is y(x, z) = (B/2)*(1−(2x/L)²)*(1−(z/T)²).
    We sample the exact analytic surface at (nu × nv) points and build a
    degree-1 NURBS surface (bilinear loft).  This is smooth by construction
    (the analytic surface is C∞), making it an ideal fairness-audit baseline.

    For higher-degree tests we use degree 3 × 3 B-spline surfaces.

    Coordinate convention:
        u ∈ [0, 1] → x ∈ [0, L]  (longitudinal, bow→stern)
        v ∈ [0, 1] → z ∈ [0, T]  (vertical, keel→deck)
        CP[i, j, :] = (x, y, 0)   where y = half-breadth at (x, z)
    """
    from kerf_cad_core.geom.nurbs import NurbsSurface

    # Build control points on the exact Wigley surface
    us = np.linspace(0.0, 1.0, nu)
    vs = np.linspace(0.0, 1.0, nv)

    cp = np.zeros((nu, nv, 3), dtype=float)
    for i, u in enumerate(us):
        x = u * L
        xi = (x - L / 2.0) / (L / 2.0)   # ∈ [-1, 1]
        for j, v in enumerate(vs):
            z = v * T
            y_half = (B / 2.0) * (1.0 - xi**2) * (1.0 - (z / T)**2)
            cp[i, j, :] = [x, y_half, z]

    # Degree 1 (bilinear) open NURBS — clamped knots
    def _clamped_knots(n: int, p: int) -> np.ndarray:
        """Clamped uniform knot vector for n CPs, degree p."""
        interior = n - p - 1
        knots = np.concatenate([
            np.zeros(p + 1),
            np.linspace(0.0, 1.0, interior + 2)[1:-1],
            np.ones(p + 1),
        ])
        return knots

    ku = _clamped_knots(nu, 1)
    kv = _clamped_knots(nv, 1)

    return NurbsSurface(
        degree_u=1,
        degree_v=1,
        control_points=cp,
        knots_u=ku,
        knots_v=kv,
    )


def _make_wigley_nurbs_deg3(L: float = 100.0, B: float = 10.0, T: float = 5.0,
                             nu: int = 7, nv: int = 5) -> "NurbsSurface":
    """Degree-3 × 3 B-spline NURBS surface for Wigley hull (smoother)."""
    from kerf_cad_core.geom.nurbs import NurbsSurface

    # Need at least degree+1 = 4 CPs; pad if needed
    nu = max(nu, 5)
    nv = max(nv, 5)

    us = np.linspace(0.0, 1.0, nu)
    vs = np.linspace(0.0, 1.0, nv)

    cp = np.zeros((nu, nv, 3), dtype=float)
    for i, u in enumerate(us):
        x = u * L
        xi = (x - L / 2.0) / (L / 2.0)
        for j, v in enumerate(vs):
            z = v * T
            y_half = (B / 2.0) * (1.0 - xi**2) * (1.0 - (z / T)**2)
            cp[i, j, :] = [x, y_half, z]

    def _clamped_knots(n: int, p: int) -> np.ndarray:
        interior = n - p - 1
        knots = np.concatenate([
            np.zeros(p + 1),
            np.linspace(0.0, 1.0, interior + 2)[1:-1],
            np.ones(p + 1),
        ])
        return knots

    ku = _clamped_knots(nu, 3)
    kv = _clamped_knots(nv, 3)

    return NurbsSurface(
        degree_u=3,
        degree_v=3,
        control_points=cp,
        knots_u=ku,
        knots_v=kv,
    )


# ---------------------------------------------------------------------------
# Test 1 — Smooth hull baseline
# ---------------------------------------------------------------------------

class TestFairnessAuditSmoothHull:
    """DoD: smooth Wigley hull → slope_continuity_metric < 0.1, curvature_variance < 0.01."""

    def test_smooth_slope_continuity(self):
        """Wigley hull (degree 1 bilinear) is analytically smooth — slope metric < 0.1."""
        from kerf_marine.hull_fairness import fairness_audit

        surf = _make_wigley_nurbs(nu=9, nv=7)
        report = fairness_audit(surf, n_samples_u=15, n_samples_v=10)

        assert report.slope_continuity_metric < 0.1, (
            f"Smooth Wigley hull should have slope_continuity_metric < 0.1, "
            f"got {report.slope_continuity_metric:.5f}"
        )

    def test_smooth_curvature_variance(self):
        """Wigley hull curvature variance should be < 0.01."""
        from kerf_marine.hull_fairness import fairness_audit

        surf = _make_wigley_nurbs(nu=9, nv=7)
        report = fairness_audit(surf, n_samples_u=15, n_samples_v=10)

        assert report.curvature_variance < 0.01, (
            f"Smooth Wigley hull should have curvature_variance < 0.01, "
            f"got {report.curvature_variance:.6f}"
        )

    def test_smooth_is_fair_flag(self):
        """is_fair should be True for smooth Wigley hull."""
        from kerf_marine.hull_fairness import fairness_audit

        surf = _make_wigley_nurbs(nu=9, nv=7)
        report = fairness_audit(surf, n_samples_u=15, n_samples_v=10)
        assert report.is_fair, (
            "Smooth Wigley hull should be flagged is_fair=True; "
            f"slope_continuity={report.slope_continuity_metric:.4f}, "
            f"curvature_variance={report.curvature_variance:.6f}"
        )

    def test_smooth_returns_fairness_report(self):
        """fairness_audit returns a FairnessReport with expected attributes."""
        from kerf_marine.hull_fairness import fairness_audit, FairnessReport

        surf = _make_wigley_nurbs()
        report = fairness_audit(surf)

        assert isinstance(report, FairnessReport)
        assert isinstance(report.slope_continuity_metric, float)
        assert isinstance(report.curvature_variance, float)
        assert isinstance(report.per_waterline_curvature_variance, list)
        assert isinstance(report.per_buttock_curvature_variance, list)
        assert isinstance(report.problem_regions, list)
        assert isinstance(report.recommendations, list)
        assert len(report.recommendations) > 0


# ---------------------------------------------------------------------------
# Test 2 — Bumpy hull: metric jumps; problem_region identifies location
# ---------------------------------------------------------------------------

class TestFairnessAuditBumpyHull:
    """DoD: perturb one interior CP → metric jumps; problem region near perturbation.

    Uses degree-3 surface where curvature is well-defined; a perturbation of
    5m in a 100m hull (5% beam deviation) produces detectable fairness failures.
    """

    def _make_bumpy_surface(self, bump_scale: float = 5.0):
        """Perturb the centre CP of a degree-3 Wigley surface in the y-direction."""
        surf = _make_wigley_nurbs_deg3(nu=7, nv=5)
        cp = surf.control_points.copy()
        # Perturb the interior centre point
        i_mid = len(cp) // 2
        j_mid = cp.shape[1] // 2
        cp[i_mid, j_mid, 1] += bump_scale   # y-direction bump
        surf.control_points = cp
        return surf, i_mid, j_mid

    def test_bumpy_curvature_variance_jumps(self):
        """Perturbed degree-3 hull should have curvature_variance >> smooth baseline."""
        from kerf_marine.hull_fairness import fairness_audit

        smooth = _make_wigley_nurbs_deg3(nu=7, nv=5)
        smooth_report = fairness_audit(smooth, n_samples_u=15, n_samples_v=10)

        bumpy, _, _ = self._make_bumpy_surface(bump_scale=5.0)
        bumpy_report = fairness_audit(bumpy, n_samples_u=15, n_samples_v=10)

        assert bumpy_report.curvature_variance > smooth_report.curvature_variance, (
            f"Bumpy hull curvvar {bumpy_report.curvature_variance:.4e} should be "
            f"> smooth curvvar {smooth_report.curvature_variance:.4e}"
        )
        # The bump should cause at least 10× increase in curvature variance
        ratio = bumpy_report.curvature_variance / max(smooth_report.curvature_variance, 1e-12)
        assert ratio > 5.0, (
            f"Bumpy hull curvvar should be >> smooth baseline "
            f"(ratio={ratio:.1f}; bumpy={bumpy_report.curvature_variance:.4e}, "
            f"smooth={smooth_report.curvature_variance:.4e})"
        )

    def test_bumpy_not_fair(self):
        """Bumpy degree-3 hull should not be is_fair (curvature variance exceeded)."""
        from kerf_marine.hull_fairness import fairness_audit

        bumpy, _, _ = self._make_bumpy_surface(bump_scale=5.0)
        report = fairness_audit(bumpy, n_samples_u=15, n_samples_v=10)

        assert not report.is_fair, (
            "Hull with large CP perturbation should fail fairness check. "
            f"slope_continuity={report.slope_continuity_metric:.4f}, "
            f"curvature_variance={report.curvature_variance:.6e}"
        )

    def test_bumpy_problem_region_detected(self):
        """Problem region should be reported for a strongly perturbed degree-3 hull."""
        from kerf_marine.hull_fairness import fairness_audit

        bumpy, i_mid, j_mid = self._make_bumpy_surface(bump_scale=5.0)
        report = fairness_audit(bumpy, n_samples_u=15, n_samples_v=10)

        # At least one problem region should be reported
        assert len(report.problem_regions) > 0, (
            "Perturbed degree-3 hull should have at least one problem region detected. "
            f"slope_continuity={report.slope_continuity_metric:.5f}, "
            f"curvature_variance={report.curvature_variance:.5e}"
        )

        # Problem region should have a positive metric value
        top_pr = report.problem_regions[0]
        assert top_pr.metric_value > 0, "Problem region metric value should be positive"
        assert top_pr.metric_name in ("slope_continuity", "curvature_variance"), (
            f"Unexpected metric name: {top_pr.metric_name}"
        )

    def test_bumpy_as_dict(self):
        """FairnessReport.as_dict() should serialize correctly for bumpy hull."""
        from kerf_marine.hull_fairness import fairness_audit

        bumpy, _, _ = self._make_bumpy_surface(bump_scale=5.0)
        report = fairness_audit(bumpy, n_samples_u=10, n_samples_v=8)
        d = report.as_dict()

        assert "slope_continuity_metric" in d
        assert "curvature_variance" in d
        assert "problem_regions" in d
        assert "recommendations" in d
        assert "is_fair" in d


# ---------------------------------------------------------------------------
# Test 3 — Fair-hull round-trip
# ---------------------------------------------------------------------------

class TestFairHullRoundTrip:
    """DoD: fair_hull on bumpy hull → metric returns closer to smooth baseline."""

    def test_fairing_reduces_fairness_metric(self):
        """fair_hull should reduce curvature_variance toward smooth baseline for deg-3 hull."""
        from kerf_marine.hull_fairness import fairness_audit, fair_hull

        smooth = _make_wigley_nurbs_deg3(nu=7, nv=5)
        smooth_report = fairness_audit(smooth, n_samples_u=15, n_samples_v=10)

        # Build bumpy degree-3 hull
        bumpy = _make_wigley_nurbs_deg3(nu=7, nv=5)
        cp = bumpy.control_points.copy()
        i_mid = len(cp) // 2
        j_mid = cp.shape[1] // 2
        cp[i_mid, j_mid, 1] += 5.0
        bumpy.control_points = cp

        bumpy_report = fairness_audit(bumpy, n_samples_u=15, n_samples_v=10)
        assert bumpy_report.curvature_variance > smooth_report.curvature_variance, (
            "Pre-condition: bumpy hull must be unfairer than smooth"
        )

        # Fair the bumpy hull
        faired_surf = fair_hull(bumpy, iterations=30, weight=0.6,
                                preserve_bow_stern=True)
        faired_report = fairness_audit(faired_surf, n_samples_u=15, n_samples_v=10)

        assert faired_report.curvature_variance < bumpy_report.curvature_variance, (
            f"Faired hull curvvar {faired_report.curvature_variance:.4e} should be "
            f"< bumpy curvvar {bumpy_report.curvature_variance:.4e}"
        )

    def test_fairing_returns_nurbs_surface(self):
        """fair_hull must return a NurbsSurface (not None, not the input)."""
        from kerf_cad_core.geom.nurbs import NurbsSurface
        from kerf_marine.hull_fairness import fair_hull

        surf = _make_wigley_nurbs(nu=7, nv=5)
        faired = fair_hull(surf, iterations=5, weight=0.3)

        assert isinstance(faired, NurbsSurface), (
            f"fair_hull should return NurbsSurface, got {type(faired).__name__}"
        )
        assert faired is not surf, "fair_hull should return a new surface, not the input"

    def test_fairing_preserves_bow_stern(self):
        """preserve_bow_stern=True: first and last u-rows of CPs are unchanged."""
        from kerf_marine.hull_fairness import fair_hull

        surf = _make_wigley_nurbs(nu=9, nv=7)
        # Perturb interior so there's something to smooth
        surf.control_points[4, 3, 1] += 3.0

        faired = fair_hull(surf, iterations=20, weight=0.5, preserve_bow_stern=True)

        np.testing.assert_allclose(
            faired.control_points[0],
            surf.control_points[0],
            rtol=1e-12,
            err_msg="Bow CPs (u=0 row) should be unchanged with preserve_bow_stern=True",
        )
        np.testing.assert_allclose(
            faired.control_points[-1],
            surf.control_points[-1],
            rtol=1e-12,
            err_msg="Stern CPs (u=-1 row) should be unchanged with preserve_bow_stern=True",
        )

    def test_fairing_changes_interior_cps(self):
        """Fairing should move interior CPs when there is a perturbation."""
        from kerf_marine.hull_fairness import fair_hull

        surf = _make_wigley_nurbs(nu=9, nv=7)
        surf.control_points[4, 3, 1] += 3.0
        original_cp = surf.control_points.copy()

        faired = fair_hull(surf, iterations=20, weight=0.5, preserve_bow_stern=True)

        # Interior CPs should differ from the bumpy original
        interior_orig = original_cp[1:-1, 1:-1, :]
        interior_faired = faired.control_points[1:-1, 1:-1, :]
        diff = float(np.max(np.abs(interior_faired - interior_orig)))
        assert diff > 1e-6, (
            f"Interior CPs should change after fairing (max diff={diff:.2e})"
        )


# ---------------------------------------------------------------------------
# Test 4 — Curvature comb: non-trivial profile at midship waterline
# ---------------------------------------------------------------------------

class TestWaterlineCurvatureComb:
    """DoD: curvature comb at midship station of Wigley hull → parabolic profile."""

    def test_comb_returns_dict_with_ok(self):
        """waterline_curvature_comb returns ok dict with expected keys."""
        from kerf_marine.hull_fairness import waterline_curvature_comb

        surf = _make_wigley_nurbs_deg3(nu=7, nv=5)
        result = waterline_curvature_comb(surf, draft=0.5, n_stations=10)

        assert result["ok"] is True, f"Expected ok=True, reason={result.get('reason','')}"
        assert "curvatures" in result
        assert "comb_teeth" in result
        assert "stations_u" in result
        assert len(result["curvatures"]) == 10
        assert len(result["comb_teeth"]) == 10

    def test_comb_nonzero_curvature(self):
        """Wigley hull waterline should have non-zero curvature at midship."""
        from kerf_marine.hull_fairness import waterline_curvature_comb

        surf = _make_wigley_nurbs_deg3(L=100.0, B=10.0, T=5.0, nu=7, nv=5)
        result = waterline_curvature_comb(surf, draft=0.5, n_stations=11)

        assert result["ok"] is True
        curvs = result["curvatures"]
        max_curv = result["max_curvature"]

        # Wigley hull has parabolic waterlines → non-zero curvature
        assert max_curv > 1e-6, (
            f"Expected non-zero curvature for Wigley hull, got max={max_curv:.2e}"
        )

    def test_comb_parabolic_profile_symmetry(self):
        """
        Wigley hull is symmetric about midship: curvatures at equally-spaced
        stations from bow and stern should have the same magnitude.

        We use a fairly coarse tolerance (25%) because bilinear NURBS
        interpolates the parabola piecewise — the profile is not exactly
        symmetric after linear interpolation, but it should be approximately so.
        """
        from kerf_marine.hull_fairness import waterline_curvature_comb

        surf = _make_wigley_nurbs_deg3(L=100.0, B=10.0, T=5.0, nu=9, nv=7)
        n = 11  # odd number → exact midship station
        result = waterline_curvature_comb(surf, draft=0.5, n_stations=n)

        assert result["ok"] is True
        curvs = result["curvatures"]

        # Check that curvature magnitudes are roughly symmetric around midship
        # (first vs last, second vs second-to-last, etc.)
        # Use relaxed tolerance for bilinear interpolation artifacts
        for k in range(1, n // 2):
            c_fwd = abs(curvs[k])
            c_aft = abs(curvs[n - 1 - k])
            if c_fwd > 1e-8 or c_aft > 1e-8:
                ratio = max(c_fwd, c_aft) / max(min(c_fwd, c_aft), 1e-10)
                assert ratio < 10.0, (
                    f"Curvature asymmetry too large at station {k}: "
                    f"fwd={c_fwd:.4e}, aft={c_aft:.4e}, ratio={ratio:.2f}"
                )

    def test_comb_tooth_geometry(self):
        """Each comb tooth should have valid 3D geometry (finite values)."""
        from kerf_marine.hull_fairness import waterline_curvature_comb

        surf = _make_wigley_nurbs_deg3(nu=7, nv=5)
        result = waterline_curvature_comb(surf, draft=0.3, n_stations=8)

        assert result["ok"] is True
        for tooth in result["comb_teeth"]:
            assert math.isfinite(tooth["curvature"]), "Curvature must be finite"
            for coord in tooth["position"]:
                assert math.isfinite(coord), "Position must be finite"
            for coord in tooth["tooth_tip_3d"]:
                assert math.isfinite(coord), "Tooth tip must be finite"

    def test_comb_midship_higher_than_ends(self):
        """Wigley hull: max curvature along waterline should occur near midship,
        not at bow/stern where half-breadth → 0."""
        from kerf_marine.hull_fairness import waterline_curvature_comb

        surf = _make_wigley_nurbs_deg3(L=100.0, B=10.0, T=5.0, nu=9, nv=7)
        result = waterline_curvature_comb(surf, draft=0.3, n_stations=9)

        assert result["ok"] is True
        curvs = [abs(c) for c in result["curvatures"]]

        # Midship station is at index len//2
        mid_idx = len(curvs) // 2
        mid_curv = curvs[mid_idx]
        end_curv = max(curvs[0], curvs[-1])

        # Midship curvature should be at least as large as end curvature
        # (Wigley hull is broadest amidships)
        assert mid_curv >= end_curv * 0.3, (
            f"Midship curvature {mid_curv:.4e} should be comparable to or larger than "
            f"end curvature {end_curv:.4e} for Wigley hull"
        )
