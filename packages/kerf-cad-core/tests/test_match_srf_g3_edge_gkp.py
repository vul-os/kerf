"""Tests for match_surface_edge_g3 and elevate_to_g3_capability.

Covers the four validation cases from the task specification:
  1. Plane-plane G3: two planar NURBS meeting at a shared edge with
     prescribed G3 -> residual < 1e-6.
  2. Cylinder-plane G3: NURBS cylinder + flat plane -> G3 residual < 1e-4.
  3. Sphere-sphere G3: two sphere patches meeting -> G3 residual = 0
     (analytic case, same geometry).
  4. Degree-elevation: degree-3 NURBS -> elevate_to_g3_capability returns
     degree-4 surface where evaluation matches the original at 100 random
     (u,v) within 1e-12.

All tests are hermetic: pure Python + NumPy, no OCC, no database, no network.

References
----------
Hoschek-Lasser 1993 §14.2 "Higher-order continuity"
Piegl-Tiller §5.5.5 (knot-insertion-preserving G3)
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate
from kerf_cad_core.geom.match_srf import (
    elevate_to_g3_capability,
    match_surface_edge_g3,
    verify_seam_g3_analytic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _knots(n: int, deg: int) -> np.ndarray:
    """Clamped uniform knot vector for n CPs of given degree."""
    inner = max(0, n - deg - 1)
    return np.concatenate([
        np.zeros(deg + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(deg + 1),
    ])


def _make_surface(zfun, x0=0.0, deg=4, nu=6, nv=5) -> NurbsSurface:
    """Build a degree-deg NURBS surface with z = zfun(x, y)."""
    ku = _knots(nu, deg)
    kv = _knots(nv, deg)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            x = x0 + i / (nu - 1)
            y = j / (nv - 1)
            cp[i, j] = [x, y, zfun(x, y)]
    return NurbsSurface(degree_u=deg, degree_v=deg,
                        control_points=cp, knots_u=ku, knots_v=kv)


def _make_sphere_patch(radius: float = 2.0, nu: int = 6, nv: int = 5,
                       deg: int = 4) -> NurbsSurface:
    """Approximate quarter-sphere patch S(u,v) = R*(sin u cos v, sin u sin v, cos u).

    u in [0, pi/4], v in [0, pi/2].
    """
    ku = _knots(nu, deg)
    kv = _knots(nv, deg)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        theta = (math.pi / 4) * i / (nu - 1)
        for j in range(nv):
            phi = (math.pi / 2) * j / (nv - 1)
            cp[i, j] = [
                radius * math.sin(theta) * math.cos(phi),
                radius * math.sin(theta) * math.sin(phi),
                radius * math.cos(theta),
            ]
    return NurbsSurface(degree_u=deg, degree_v=deg,
                        control_points=cp, knots_u=ku, knots_v=kv)


def _make_cylinder_quarter(radius: float = 2.0, height: float = 1.0,
                            nu: int = 6, nv: int = 5, deg: int = 4) -> NurbsSurface:
    """Quarter-cylinder: S(u, v) = (R cos theta, R sin theta, v*H)
    with theta in [0, pi/2].
    """
    ku = _knots(nu, deg)
    kv = _knots(nv, deg)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        theta = (math.pi / 2) * i / (nu - 1)
        for j in range(nv):
            vf = j / (nv - 1)
            cp[i, j] = [radius * math.cos(theta),
                         radius * math.sin(theta),
                         vf * height]
    return NurbsSurface(degree_u=deg, degree_v=deg,
                        control_points=cp, knots_u=ku, knots_v=kv)


# ---------------------------------------------------------------------------
# Test 1: Plane-plane G3
# ---------------------------------------------------------------------------

class TestPlanePlaneG3:
    """Two planar NURBS surfaces meeting at a shared edge with prescribed G3."""

    def test_plane_plane_g3_residual_below_1e6(self):
        """After match_surface_edge_g3, G3 residual < 1e-6 for plane-plane seam."""
        # Target: flat plane with mild cubic z-profile to give non-zero dκ/ds
        tgt = _make_surface(lambda x, y: 0.3 * x**3 + 0.1 * x**2 * y)
        # Source: a purely flat plane positioned adjacent (u0 meets tgt's u1)
        src = _make_surface(lambda x, y: 0.0, x0=1.0)

        # Both should start G3-discontinuous
        before = verify_seam_g3_analytic(src, "u0", tgt, "u1")
        assert before > 1e-4, f"fixture must start G3-discontinuous (got {before:.2e})"

        modified, residuals = match_surface_edge_g3(tgt, src, "u1", "u0")
        assert not math.isnan(residuals), "residual should not be NaN"
        assert residuals < 1e-6, (
            f"plane-plane G3 residual {residuals:.2e} exceeds 1e-6"
        )

    def test_plane_plane_g3_modified_differs_from_source(self):
        """match_surface_edge_g3 must return a modified surface, not the original."""
        tgt = _make_surface(lambda x, y: 0.3 * x**3)
        src = _make_surface(lambda x, y: 0.0, x0=1.0)
        modified, _ = match_surface_edge_g3(tgt, src, "u1", "u0")
        assert modified is not src, "should return a copy, not the original"

    def test_plane_plane_g3_g0_preserved(self):
        """G3 match must preserve G0 (position continuity at seam boundary row)."""
        tgt = _make_surface(lambda x, y: 0.3 * x**3 + 0.05 * y)
        src = _make_surface(lambda x, y: 0.0, x0=1.0)
        modified, _ = match_surface_edge_g3(tgt, src, "u1", "u0")

        # The boundary CPs of the modified source (u0 edge row 0) should be
        # close to the target's u1 edge row 0 after G0 application.
        from kerf_cad_core.geom.match_srf import _get_cp_row
        src_bdy = _get_cp_row(modified, "u0", 0)
        tgt_bdy = _get_cp_row(tgt, "u1", 0)
        # Resampled comparison (both may differ in CP count)
        ns = len(src_bdy)
        nt = len(tgt_bdy)
        for k in range(ns):
            tk = k / (ns - 1) if ns > 1 else 0.0
            idx_f = tk * (nt - 1)
            lo = int(math.floor(idx_f))
            hi = min(lo + 1, nt - 1)
            alpha = idx_f - lo
            tgt_pt = (1.0 - alpha) * tgt_bdy[lo, :3] + alpha * tgt_bdy[hi, :3]
            np.testing.assert_allclose(
                src_bdy[k, :3], tgt_pt, atol=1e-9,
                err_msg=f"G0 not preserved at CP index {k}"
            )


# ---------------------------------------------------------------------------
# Test 2: Cylinder-plane G3
# ---------------------------------------------------------------------------

class TestCylinderPlaneG3:
    """NURBS cylinder meets flat plane: G3 match residual < 1e-4."""

    def test_cylinder_plane_g3_residual_below_1e4(self):
        """After G3 match, curvature-rate residual at cylinder-plane seam < 1e-4."""
        cyl = _make_cylinder_quarter(radius=2.0, height=1.0)
        # Flat plane whose u0 edge coincides with cyl's u1 edge (at theta=pi/2)
        # At theta=pi/2: x=0, y=R, so plane extends in +x direction.
        nu, nv, deg = 6, 5, 4
        ku = _knots(nu, deg)
        kv = _knots(nv, deg)
        cp = np.zeros((nu, nv, 3))
        for i in range(nu):
            for j in range(nv):
                cp[i, j] = [i / (nu - 1), 2.0, j / (nv - 1)]
        plane = NurbsSurface(degree_u=deg, degree_v=deg,
                             control_points=cp, knots_u=ku, knots_v=kv)

        modified, residuals = match_surface_edge_g3(cyl, plane, "u1", "u0")
        assert not math.isnan(residuals), "residual should not be NaN"
        assert residuals < 1e-4, (
            f"cylinder-plane G3 residual {residuals:.2e} exceeds 1e-4"
        )

    def test_cylinder_plane_g3_ok_return(self):
        """match_surface_edge_g3 returns a valid surface, not None."""
        cyl = _make_cylinder_quarter()
        nu, nv, deg = 6, 5, 4
        ku, kv = _knots(nu, deg), _knots(nv, deg)
        cp = np.zeros((nu, nv, 3))
        for i in range(nu):
            for j in range(nv):
                cp[i, j] = [i / (nu - 1), 2.0, j / (nv - 1)]
        plane = NurbsSurface(degree_u=deg, degree_v=deg,
                             control_points=cp, knots_u=ku, knots_v=kv)
        modified, residuals = match_surface_edge_g3(cyl, plane, "u1", "u0")
        assert isinstance(modified, NurbsSurface)
        assert residuals >= 0.0


# ---------------------------------------------------------------------------
# Test 3: Sphere-sphere G3 (analytic case — identical geometry)
# ---------------------------------------------------------------------------

class TestSphereSphereG3:
    """Two identical sphere patches: G3 residual = 0 (analytic idempotence)."""

    def test_sphere_sphere_g3_residual_zero(self):
        """Matching a spherical surface to an identical copy yields G3 residual ~ 0."""
        sph = _make_sphere_patch(radius=3.0)
        # Deep copy — identical geometry
        sph_copy = NurbsSurface(
            degree_u=sph.degree_u,
            degree_v=sph.degree_v,
            control_points=sph.control_points.copy(),
            knots_u=sph.knots_u.copy(),
            knots_v=sph.knots_v.copy(),
        )
        # Both surfaces use the same u1 edge; matching u1 of sph to u1 of sph_copy
        # is the identity operation => G3 residual must be zero.
        modified, residuals = match_surface_edge_g3(sph, sph_copy, "u1", "u1")
        assert not math.isnan(residuals), "residual should not be NaN"
        assert residuals < 1e-7, (
            f"sphere-sphere G3 identity residual {residuals:.2e} should be ~0"
        )

    def test_sphere_sphere_g3_cps_nearly_unchanged(self):
        """Idempotent match: control points should barely change."""
        sph = _make_sphere_patch(radius=2.5)
        sph_copy = NurbsSurface(
            degree_u=sph.degree_u, degree_v=sph.degree_v,
            control_points=sph.control_points.copy(),
            knots_u=sph.knots_u.copy(), knots_v=sph.knots_v.copy(),
        )
        modified, _ = match_surface_edge_g3(sph, sph_copy, "u1", "u1")
        # The modification should be negligible for identical surfaces
        np.testing.assert_allclose(
            modified.control_points, sph_copy.control_points,
            atol=1e-6,
            err_msg="G3 idempotent match should leave CPs nearly unchanged",
        )


# ---------------------------------------------------------------------------
# Test 4: Degree elevation
# ---------------------------------------------------------------------------

class TestDegreeElevation:
    """elevate_to_g3_capability: degree-3 -> degree-4, geometry preserved."""

    def test_elevation_produces_degree_4(self):
        """A degree-3 surface elevated to target_degree=4 has degree 4 in both dirs."""
        surf3 = _make_surface(lambda x, y: 0.2 * x**3 + 0.1 * y**2, deg=3)
        elevated = elevate_to_g3_capability(surf3, target_degree=4)
        assert elevated.degree_u == 4, f"expected degree_u=4, got {elevated.degree_u}"
        assert elevated.degree_v == 4, f"expected degree_v=4, got {elevated.degree_v}"

    def test_elevation_evaluation_matches_original(self):
        """Elevated surface evaluates to same points as original within 1e-12."""
        surf3 = _make_surface(lambda x, y: 0.1 * x**3 - 0.05 * y**3, deg=3,
                              nu=5, nv=5)
        elevated = elevate_to_g3_capability(surf3, target_degree=4)

        u0 = float(surf3.knots_u[surf3.degree_u])
        u1 = float(surf3.knots_u[-surf3.degree_u - 1])
        v0 = float(surf3.knots_v[surf3.degree_v])
        v1 = float(surf3.knots_v[-surf3.degree_v - 1])

        rng = np.random.default_rng(42)
        n_pts = 100
        us = rng.uniform(u0 + 1e-6, u1 - 1e-6, n_pts)
        vs = rng.uniform(v0 + 1e-6, v1 - 1e-6, n_pts)

        max_err = 0.0
        for u, v in zip(us, vs):
            p_orig = surface_evaluate(surf3, u, v)
            p_elev = surface_evaluate(elevated, u, v)
            err = float(np.linalg.norm(p_elev[:3] - p_orig[:3]))
            if err > max_err:
                max_err = err

        assert max_err < 1e-12, (
            f"elevation geometry error {max_err:.2e} exceeds 1e-12 "
            f"at 100 random (u,v)"
        )

    def test_elevation_already_high_degree_noop(self):
        """Elevating a degree-4 surface to target_degree=4 is a no-op."""
        surf4 = _make_surface(lambda x, y: 0.1 * x, deg=4)
        elevated = elevate_to_g3_capability(surf4, target_degree=4)
        assert elevated.degree_u == 4
        assert elevated.degree_v == 4
        np.testing.assert_allclose(
            elevated.control_points, surf4.control_points,
            atol=1e-15,
            err_msg="no-op elevation should leave CPs unchanged",
        )

    def test_elevation_returns_nurbs_surface(self):
        """elevate_to_g3_capability must return a NurbsSurface."""
        surf3 = _make_surface(lambda x, y: 0.0, deg=3)
        result = elevate_to_g3_capability(surf3, target_degree=4)
        assert isinstance(result, NurbsSurface)

    def test_elevation_degree_2_to_4(self):
        """A degree-2 surface can be elevated to degree-4."""
        surf2 = _make_surface(lambda x, y: 0.1 * x**2, deg=2, nu=5, nv=4)
        elevated = elevate_to_g3_capability(surf2, target_degree=4)
        assert elevated.degree_u == 4
        assert elevated.degree_v == 4
        # Verify knot vector lengths are consistent
        nu = elevated.control_points.shape[0]
        nv = elevated.control_points.shape[1]
        assert len(elevated.knots_u) == nu + elevated.degree_u + 1
        assert len(elevated.knots_v) == nv + elevated.degree_v + 1
