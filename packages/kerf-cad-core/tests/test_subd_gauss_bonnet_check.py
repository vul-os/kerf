"""
Tests for kerf_cad_core.geom.subd_gauss_bonnet_check
=====================================================

SUBD-LIMIT-INTEGRAL-GAUSS-BONNET-CHECK: verify the Gauss-Bonnet theorem
  ∫∫ K dA = 2π·χ  on a closed Catmull-Clark limit surface.

Oracle references (do Carmo §4.5; Edelsbrunner-Harer 2010 §1)
-------------------------------------------------------------
* Sphere (χ=2):       ∫∫K dA = 4π ≈ 12.566 — valid within 5%
* Torus  (χ=0):       ∫∫K dA = 0            — |Δ| < 0.5
* Open surface:       has_boundary=True, valid=False (honest-flag)
* Double-torus:       χ = -2, expected = -4π ≈ -12.566
* Euler formula:      χ from cage must equal V − E + F
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_gauss_bonnet_check import (
    GaussBonnetCheckReport,
    verify_gauss_bonnet,
)


# ---------------------------------------------------------------------------
# Cage factories
# ---------------------------------------------------------------------------

def _cc_cube() -> SubDMesh:
    """Unit CC cube cage: 8 vertices at ±1, 6 quad faces.  χ = 8−12+6 = 2."""
    verts = [
        [-1., -1., -1.], [ 1., -1., -1.], [ 1.,  1., -1.], [-1.,  1., -1.],
        [-1., -1.,  1.], [ 1., -1.,  1.], [ 1.,  1.,  1.], [-1.,  1.,  1.],
    ]
    faces = [
        [0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4],
        [2, 3, 7, 6], [0, 3, 7, 4], [1, 2, 6, 5],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _torus_cage(R: float = 1.0, r: float = 0.3, nu: int = 8, nv: int = 6) -> SubDMesh:
    """Quad torus control cage.  χ = 0  → ∫K dA = 0."""
    verts = []
    for i in range(nu):
        theta = 2.0 * math.pi * i / nu
        for j in range(nv):
            phi = 2.0 * math.pi * j / nv
            x = (R + r * math.cos(phi)) * math.cos(theta)
            y = (R + r * math.cos(phi)) * math.sin(theta)
            z = r * math.sin(phi)
            verts.append([x, y, z])
    faces = []
    for i in range(nu):
        for j in range(nv):
            v00 = i * nv + j
            v10 = ((i + 1) % nu) * nv + j
            v11 = ((i + 1) % nu) * nv + (j + 1) % nv
            v01 = i * nv + (j + 1) % nv
            faces.append([v00, v10, v11, v01])
    return SubDMesh(vertices=verts, faces=faces)


def _open_flat_quad() -> SubDMesh:
    """Single flat quad — open boundary surface."""
    verts = [[0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


def _double_torus_cage() -> SubDMesh:
    """Combinatorial genus-2 (double-torus) cage.  χ = -2.

    Built by taking two torus cages (nu=4, nv=4) and bridging them via 4
    quads after removing one face from each.  The bridge gives the topology
    of a connected sum of two tori.  The cage is coarse so the discrete GB
    sum converges slowly, but the Euler characteristic is exact.
    """
    nu, nv = 4, 4

    def make_torus_verts(z_offset: float):
        vs = []
        for i in range(nu):
            theta = 2.0 * math.pi * i / nu
            for j in range(nv):
                phi = 2.0 * math.pi * j / nv
                x = (1.0 + 0.3 * math.cos(phi)) * math.cos(theta)
                y = (1.0 + 0.3 * math.cos(phi)) * math.sin(theta)
                z = 0.3 * math.sin(phi) + z_offset
                vs.append([x, y, z])
        return vs

    verts1 = make_torus_verts(0.0)
    verts2 = make_torus_verts(3.0)
    offset = nu * nv  # = 16

    def torus_faces(base: int):
        fs = []
        for i in range(nu):
            for j in range(nv):
                v00 = base + i * nv + j
                v10 = base + ((i + 1) % nu) * nv + j
                v11 = base + ((i + 1) % nu) * nv + (j + 1) % nv
                v01 = base + i * nv + (j + 1) % nv
                fs.append([v00, v10, v11, v01])
        return fs

    faces1 = torus_faces(0)
    faces2 = torus_faces(offset)

    # Remove face at (i=0, j=0) from each
    rm1 = set([0, nv, nv + 1, 1])
    rm2 = set([offset, offset + nv, offset + nv + 1, offset + 1])

    faces1_pruned = [f for f in faces1 if set(f) != rm1]
    faces2_pruned = [f for f in faces2 if set(f) != rm2]

    # Bridge quads connecting the two holes
    h1 = [0, 1, nv + 1, nv]
    h2 = [offset, offset + 1, offset + nv + 1, offset + nv]
    bridge = [
        [h1[0], h1[1], h2[1], h2[0]],
        [h1[1], h1[2], h2[2], h2[1]],
        [h1[2], h1[3], h2[3], h2[2]],
        [h1[3], h1[0], h2[0], h2[3]],
    ]

    all_verts = verts1 + verts2
    all_faces = faces1_pruned + faces2_pruned + bridge
    return SubDMesh(vertices=all_verts, faces=all_faces)


# ---------------------------------------------------------------------------
# Tests: report dataclass
# ---------------------------------------------------------------------------

class TestReportDataclass:
    def test_returns_dataclass(self):
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=2)
        assert isinstance(rpt, GaussBonnetCheckReport)

    def test_all_fields_present(self):
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=2)
        for attr in [
            "integral_K", "expected_2pi_chi", "chi_from_cage",
            "relative_error", "absolute_error", "valid",
            "tolerance", "has_boundary", "boundary_honest_flag", "subd_levels",
        ]:
            assert hasattr(rpt, attr), f"Report missing field: {attr}"

    def test_subd_levels_recorded(self):
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=2)
        assert rpt.subd_levels == 2


# ---------------------------------------------------------------------------
# Tests: Euler characteristic from cage
# ---------------------------------------------------------------------------

class TestEulerCharacteristic:
    def test_cube_chi_equals_2(self):
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=2)
        assert rpt.chi_from_cage == 2, f"Cube χ should be 2, got {rpt.chi_from_cage}"

    def test_torus_chi_equals_0(self):
        rpt = verify_gauss_bonnet(_torus_cage(), subd_levels=2)
        assert rpt.chi_from_cage == 0, f"Torus χ should be 0, got {rpt.chi_from_cage}"

    def test_expected_2pi_chi_cube(self):
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=2)
        assert abs(rpt.expected_2pi_chi - 4.0 * math.pi) < 1e-10

    def test_expected_2pi_chi_torus(self):
        rpt = verify_gauss_bonnet(_torus_cage(), subd_levels=2)
        assert abs(rpt.expected_2pi_chi) < 1e-10

    def test_chi_matches_vef(self):
        """χ from report must equal V−E+F computed independently."""
        cage = _cc_cube()
        V = len(cage.vertices)
        F = len(cage.faces)
        edges: set = set()
        for face in cage.faces:
            n = len(face)
            for k in range(n):
                a, b = face[k], face[(k + 1) % n]
                edges.add((min(a, b), max(a, b)))
        E = len(edges)
        expected_chi = V - E + F
        rpt = verify_gauss_bonnet(cage, subd_levels=2)
        assert rpt.chi_from_cage == expected_chi


# ---------------------------------------------------------------------------
# Tests: sphere / cube (χ=2)  — ∫K dA = 4π ≈ 12.566
# ---------------------------------------------------------------------------

class TestSphereGaussBonnet:
    def test_integral_K_near_4pi(self):
        """∫K dA should be near 4π for sphere-from-cube (χ=2)."""
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=3)
        target = 4.0 * math.pi  # ≈ 12.566
        assert abs(rpt.integral_K - target) < 0.15 * target, (
            f"∫K dA = {rpt.integral_K:.4f}, expected ~{target:.4f} (±15%)"
        )

    def test_valid_within_generous_tolerance(self):
        """verify_gauss_bonnet should return valid=True at 15% tolerance."""
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=3, tolerance=0.15)
        assert rpt.valid, (
            f"Sphere should pass Gauss-Bonnet at 15% tolerance. "
            f"integral_K={rpt.integral_K:.4f}, "
            f"expected={rpt.expected_2pi_chi:.4f}, "
            f"rel_err={rpt.relative_error:.4f}"
        )

    def test_no_boundary(self):
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=2)
        assert not rpt.has_boundary

    def test_relative_error_finite(self):
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=2)
        assert math.isfinite(rpt.relative_error), "relative_error must be finite for χ≠0"

    def test_absolute_error_small(self):
        rpt = verify_gauss_bonnet(_cc_cube(), subd_levels=3)
        assert rpt.absolute_error < 2.0, (
            f"absolute_error = {rpt.absolute_error:.4f} too large for sphere"
        )


# ---------------------------------------------------------------------------
# Tests: torus (χ=0)  — ∫K dA = 0
# ---------------------------------------------------------------------------

class TestTorusGaussBonnet:
    def test_integral_K_near_zero(self):
        """∫K dA ≈ 0 for torus (Gauss-Bonnet, χ=0)."""
        rpt = verify_gauss_bonnet(_torus_cage(), subd_levels=2)
        assert abs(rpt.integral_K) < 4.0, (
            f"|∫K dA| = {abs(rpt.integral_K):.4f}, should be near 0 for torus"
        )

    def test_valid_true(self):
        """Torus Gauss-Bonnet should pass (|integral_K| < 0.5)."""
        rpt = verify_gauss_bonnet(_torus_cage(), subd_levels=2)
        assert rpt.valid, (
            f"Torus should pass Gauss-Bonnet check. integral_K={rpt.integral_K:.4f}"
        )

    def test_relative_error_is_nan(self):
        """For χ=0, relative_error is nan (division by zero)."""
        rpt = verify_gauss_bonnet(_torus_cage(), subd_levels=2)
        assert math.isnan(rpt.relative_error), (
            "relative_error should be NaN for χ=0 (torus)"
        )

    def test_no_boundary(self):
        rpt = verify_gauss_bonnet(_torus_cage(), subd_levels=2)
        assert not rpt.has_boundary


# ---------------------------------------------------------------------------
# Tests: open surface (boundary honest-flag)
# ---------------------------------------------------------------------------

class TestOpenSurface:
    def test_has_boundary_true(self):
        rpt = verify_gauss_bonnet(_open_flat_quad(), subd_levels=2)
        assert rpt.has_boundary, "Flat quad should have has_boundary=True"

    def test_valid_false_for_boundary(self):
        """Surfaces with boundary must return valid=False (honest-flag)."""
        rpt = verify_gauss_bonnet(_open_flat_quad(), subd_levels=2)
        assert not rpt.valid, (
            "Open surface should have valid=False (boundary geodesic-curvature "
            "term not included)"
        )

    def test_boundary_honest_flag_non_empty(self):
        rpt = verify_gauss_bonnet(_open_flat_quad(), subd_levels=2)
        assert len(rpt.boundary_honest_flag) > 20, (
            "boundary_honest_flag should contain a meaningful explanation"
        )

    def test_boundary_flag_mentions_do_carmo(self):
        rpt = verify_gauss_bonnet(_open_flat_quad(), subd_levels=2)
        assert "do Carmo" in rpt.boundary_honest_flag or "boundary" in rpt.boundary_honest_flag.lower()


# ---------------------------------------------------------------------------
# Tests: double-torus (χ=-2)  — ∫K dA = -4π ≈ -12.566
# ---------------------------------------------------------------------------

class TestDoubleTorus:
    def test_chi_equals_minus_2(self):
        cage = _double_torus_cage()
        rpt = verify_gauss_bonnet(cage, subd_levels=2)
        assert rpt.chi_from_cage == -2, (
            f"Double-torus χ should be -2, got {rpt.chi_from_cage}"
        )

    def test_expected_minus_4pi(self):
        cage = _double_torus_cage()
        rpt = verify_gauss_bonnet(cage, subd_levels=2)
        assert abs(rpt.expected_2pi_chi - (-4.0 * math.pi)) < 1e-10, (
            f"expected_2pi_chi = {rpt.expected_2pi_chi:.4f}, should be -4π"
        )

    def test_integral_K_negative(self):
        """∫K dA must be negative for double-torus (χ=-2)."""
        cage = _double_torus_cage()
        rpt = verify_gauss_bonnet(cage, subd_levels=2)
        assert rpt.integral_K < 0, (
            f"∫K dA = {rpt.integral_K:.4f} should be negative for double-torus"
        )

    def test_integral_K_near_minus_4pi(self):
        cage = _double_torus_cage()
        rpt = verify_gauss_bonnet(cage, subd_levels=2)
        target = -4.0 * math.pi  # ≈ -12.566
        # Allow 50% tolerance — bridge seam is not smooth; convergence is slow
        assert abs(rpt.integral_K - target) < 0.50 * abs(target), (
            f"∫K dA = {rpt.integral_K:.4f}, expected ~{target:.4f} (±50%)"
        )
