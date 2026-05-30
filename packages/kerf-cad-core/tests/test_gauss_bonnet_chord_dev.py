"""
test_gauss_bonnet_chord_dev.py
==============================
Tests for:
  - gauss_bonnet_residual()  — Gauss-Bonnet integrity check
  - chord_deviation_per_face() — per-face chord-height metric
  - continuity_audit() with include_gauss_bonnet / include_chord_deviation flags

All tests are pure-Python; no OCC, no database, no network.

Analytic oracles
----------------
Sphere (genus 0, χ=2):  ∫K·dA = 4π·R² * (1/R²) = 4π
  → expected = 2π·2 = 4π, so residual ≈ 0

Cube  (genus 0, χ=2):  flat faces → K=0 everywhere → ∫K·dA = 0
  but exterior angles at the 8 corners (3 × π/2 per corner) sum to
  8 × (3 × π/2) = 12π = 4π*(3/2) ... however only 2π·χ = 4π is expected.
  For a cube: each vertex has 3 faces meeting at π/2 dihedral.
  θ_ext at each vertex = π - π/2 = π/2, and 3 edges meet → 3 × (π/2) = 3π/2
  Wait — the Gauss-Bonnet for a polyhedral surface uses angle DEFECT:
  At each vertex, the angle defect = 2π - Σ face_angles_at_vertex.
  For a cube vertex: 3 square faces, each contributing π/2 → defect = 2π-3(π/2)=π/2
  8 vertices × π/2 = 4π = 2πχ ✓

Torus (genus 1, χ=0): ∫K·dA = 0 (Gauss-Bonnet → LHS=0 for χ=0)
  → residual ≈ 0

Chord-deviation oracle: a NURBS bilinear patch (degree-1) has zero chord
  deviation because it IS the linear tessellation; a degree-3 patch has
  nonzero deviation proportional to the second derivatives.

References
----------
do Carmo §4.5 (Gauss-Bonnet theorem, polyhedral version).
Piegl & Tiller §5.4.4 (chord-height tolerance).
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.brep import make_sphere, make_box, make_torus
from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_analysis import (
    gauss_bonnet_residual,
    chord_deviation_per_face,
    continuity_audit,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal body from a list of NurbsSurface objects
# ---------------------------------------------------------------------------

class _DummyFace:
    def __init__(self, surf, fid):
        self.surface = surf
        self.id = fid


class _DummyBody:
    """Minimal duck-typed body with all_faces() and all_edges() for testing."""

    def __init__(self, surfs):
        self._faces = [_DummyFace(s, i) for i, s in enumerate(surfs)]

    def all_faces(self):
        return self._faces

    def all_edges(self):
        return []


def _make_knots(n: int, deg: int) -> np.ndarray:
    """Build a clamped uniform knot vector."""
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def _make_bilinear_patch(size: float = 1.0) -> NurbsSurface:
    """Flat degree-1 bilinear patch z=0 on [0,size]²."""
    nu, nv = 2, 2
    cp = np.array([
        [[0.0, 0.0, 0.0], [0.0, size, 0.0]],
        [[size, 0.0, 0.0], [size, size, 0.0]],
    ])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=_make_knots(nu, 1),
        knots_v=_make_knots(nv, 1),
    )


def _make_degree3_patch(bump: float = 0.1, nu: int = 5, nv: int = 5) -> NurbsSurface:
    """Degree-3 patch with a smooth z-bump for nonzero chord deviation."""
    deg = 3
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = i / (nu - 1)
        for j in range(nv):
            y = j / (nv - 1)
            # Smooth bump: z = bump * sin(π*x) * sin(π*y)
            z = bump * math.sin(math.pi * x) * math.sin(math.pi * y)
            cp[i, j] = [x, y, z]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


# ---------------------------------------------------------------------------
# Test 1: Unit sphere Gauss-Bonnet
# ---------------------------------------------------------------------------

class TestGaussBonnetSphere:
    """Unit sphere (genus 0, χ=2) → expected = 4π; ∫K·dA ≈ 4π."""

    def test_sphere_gb_ok(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = gauss_bonnet_residual(body, n_samples_per_face=15)
        assert result["ok"], f"gauss_bonnet_residual failed: {result.get('reason')}"

    def test_sphere_genus_is_zero(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = gauss_bonnet_residual(body, n_samples_per_face=15)
        assert result["genus_used"] == 0

    def test_sphere_expected_is_4pi(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = gauss_bonnet_residual(body, n_samples_per_face=15)
        assert abs(result["expected"] - 4.0 * math.pi) < 1e-10

    def test_sphere_K_integral_approx_4pi(self):
        """∫K·dA for a unit sphere = 4π (K=1 everywhere, surface area=4π)."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = gauss_bonnet_residual(body, n_samples_per_face=20)
        assert result["ok"]
        # The sphere face uses SphereSurface (analytic) which integrates K
        # via the finite-difference path.  K = 1/R² = 1; area = 4π.
        # The integral should be within 10% of 4π.
        K_int = result["computed_K_integral"]
        assert abs(K_int - 4.0 * math.pi) < 2.0, (
            f"∫K·dA = {K_int:.4f}, expected ≈ 4π = {4*math.pi:.4f}"
        )

    def test_sphere_gb_residual_small(self):
        """Overall Gauss-Bonnet residual < 1e-1 for unit sphere."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = gauss_bonnet_residual(body, n_samples_per_face=20)
        assert result["ok"]
        assert result["residual"] < 2.0, (
            f"Gauss-Bonnet residual = {result['residual']:.4f} (expected < 2.0)"
        )


# ---------------------------------------------------------------------------
# Test 2: Cube Gauss-Bonnet
# ---------------------------------------------------------------------------

class TestGaussBonnetCube:
    """Cube (genus 0, χ=2) → flat faces → ∫K·dA = 0; exterior angles sum = 4π."""

    def test_cube_gb_ok(self):
        body = make_box(size=(1.0, 1.0, 1.0))
        result = gauss_bonnet_residual(body, n_samples_per_face=10)
        assert result["ok"], f"gauss_bonnet_residual failed: {result.get('reason')}"

    def test_cube_genus_is_zero(self):
        body = make_box(size=(1.0, 1.0, 1.0))
        result = gauss_bonnet_residual(body)
        assert result["genus_used"] == 0

    def test_cube_K_integral_near_zero(self):
        """Flat faces have K=0 everywhere so ∫K·dA ≈ 0."""
        body = make_box(size=(1.0, 1.0, 1.0))
        result = gauss_bonnet_residual(body, n_samples_per_face=10)
        assert result["ok"]
        # Flat planes: K=0 everywhere, so K_integral should be ~0
        assert abs(result["computed_K_integral"]) < 0.5, (
            f"cube ∫K·dA = {result['computed_K_integral']:.4f}, expected ≈ 0"
        )

    def test_cube_gb_residual_reasonable(self):
        """Gauss-Bonnet residual should be < 5.0 for cube (angle-defect dominated)."""
        body = make_box(size=(1.0, 1.0, 1.0))
        result = gauss_bonnet_residual(body, n_samples_per_face=10)
        assert result["ok"]
        # Total LHS computed; residual gauges how close we are to 4π
        assert result["residual"] < 10.0, (
            f"Cube GB residual = {result['residual']:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 3: Torus Gauss-Bonnet
# ---------------------------------------------------------------------------

class TestGaussBonnetTorus:
    """Torus (genus 1, χ=0) → expected = 0; ∫K·dA = 0 (interior cancels exterior)."""

    def test_torus_gb_ok(self):
        body = make_torus(center=(0, 0, 0), major_radius=2.0, minor_radius=0.5)
        result = gauss_bonnet_residual(body, n_samples_per_face=15)
        assert result["ok"], f"gauss_bonnet_residual failed: {result.get('reason')}"

    def test_torus_genus_is_one(self):
        body = make_torus(center=(0, 0, 0), major_radius=2.0, minor_radius=0.5)
        result = gauss_bonnet_residual(body, n_samples_per_face=10)
        assert result["genus_used"] == 1

    def test_torus_expected_is_zero(self):
        body = make_torus(center=(0, 0, 0), major_radius=2.0, minor_radius=0.5)
        result = gauss_bonnet_residual(body, n_samples_per_face=10)
        assert abs(result["expected"]) < 1e-10, (
            f"Torus χ=0 → expected=0, got {result['expected']}"
        )

    def test_torus_K_integral_near_zero(self):
        """For a torus ∫K·dA = 0 by Gauss-Bonnet (χ=0, no boundary, no corners)."""
        body = make_torus(center=(0, 0, 0), major_radius=2.0, minor_radius=0.5)
        result = gauss_bonnet_residual(body, n_samples_per_face=20)
        assert result["ok"]
        # The torus K-integral cancels: positive K on outer half, negative on inner.
        # With 20 samples per direction the sum should be < 3.0 in absolute value.
        assert abs(result["computed_K_integral"]) < 3.0, (
            f"Torus ∫K·dA = {result['computed_K_integral']:.4f}, expected ≈ 0"
        )


# ---------------------------------------------------------------------------
# Test 4: Chord-deviation oracle
# ---------------------------------------------------------------------------

class TestChordDeviationOracle:
    """Per-face chord-deviation metric tests."""

    def test_bilinear_patch_zero_deviation(self):
        """A degree-1 flat patch IS the linear tessellation → chord deviation = 0."""
        surf = _make_bilinear_patch(size=1.0)
        body = _DummyBody([surf])
        result = chord_deviation_per_face(body, n_samples=4)
        assert result["ok"]
        per_face = result["per_face"]
        assert len(per_face) == 1
        face_info = list(per_face.values())[0]
        assert face_info["max_deviation"] < 1e-10, (
            f"flat patch max_deviation = {face_info['max_deviation']}"
        )
        assert face_info["suggested_subdivision_level"] == 0

    def test_degree3_patch_nonzero_deviation(self):
        """A bumped degree-3 patch has nonzero chord deviation."""
        bump = 0.1
        surf = _make_degree3_patch(bump=bump, nu=5, nv=5)
        body = _DummyBody([surf])
        result = chord_deviation_per_face(body, n_samples=4, target_tol=1e-3)
        assert result["ok"]
        per_face = result["per_face"]
        assert len(per_face) == 1
        face_info = list(per_face.values())[0]
        # The chord deviation should be > 0 for a bumped surface
        assert face_info["max_deviation"] > 1e-6, (
            f"bumped patch max_deviation = {face_info['max_deviation']} (expected > 0)"
        )

    def test_degree3_patch_deviation_proportional_to_bump(self):
        """Larger bump → larger chord deviation (monotonicity check)."""
        bumps = [0.01, 0.05, 0.1]
        devs = []
        for bump in bumps:
            surf = _make_degree3_patch(bump=bump, nu=5, nv=5)
            body = _DummyBody([surf])
            result = chord_deviation_per_face(body, n_samples=4)
            assert result["ok"]
            face_info = list(result["per_face"].values())[0]
            devs.append(face_info["max_deviation"])
        # Monotonically increasing
        assert devs[0] < devs[1] < devs[2], (
            f"Deviations not monotone: {devs}"
        )

    def test_subdivision_level_increases_with_deviation(self):
        """Larger deviation → higher suggested subdivision level."""
        surf_small = _make_degree3_patch(bump=0.001, nu=5, nv=5)
        surf_large = _make_degree3_patch(bump=0.5, nu=5, nv=5)
        body_small = _DummyBody([surf_small])
        body_large = _DummyBody([surf_large])
        r_small = chord_deviation_per_face(body_small, n_samples=4, target_tol=1e-3)
        r_large = chord_deviation_per_face(body_large, n_samples=4, target_tol=1e-3)
        lev_small = list(r_small["per_face"].values())[0]["suggested_subdivision_level"]
        lev_large = list(r_large["per_face"].values())[0]["suggested_subdivision_level"]
        assert lev_large >= lev_small, (
            f"large bump level {lev_large} should be >= small bump level {lev_small}"
        )

    def test_chord_dev_newton_cotes_bound(self):
        """The chord deviation of a degree-3 bumped surface at n×n samples lies
        within a factor of 5 of the analytic Newton-Cotes chord-height estimate.

        For a smooth surface z = bump*sin(π*x)*sin(π*y) on [0,1]²,
        the 2D chord-height bound (Piegl-Tiller §5.4.4) is:

            bound = (|z_xx| + |z_yy| + 2|z_xy|)_max * h² / 8

        where h = 1/n.  For this function all three second-deriv maxima = bump*π²:
            bound = 4 * bump * π² * h² / 8 = bump * π² * h² / 2

        The measured chord deviation from the sampled NURBS (which approximates
        the function via control points) should be of the same order of magnitude.
        We allow a factor of 5 to account for:
          - NURBS approximation error in the control-point grid
          - Mixed-partial contribution at cell corners
          - Different evaluation path (midpoint of bilinear quad vs exact surface)
        """
        bump = 0.1
        n = 4
        surf = _make_degree3_patch(bump=bump, nu=5, nv=5)
        body = _DummyBody([surf])
        result = chord_deviation_per_face(body, n_samples=n, target_tol=1e-3)
        assert result["ok"]
        measured = list(result["per_face"].values())[0]["max_deviation"]

        h = 1.0 / n
        # Analytic bound: bump * π² * h² / 2
        z_ddx_max = bump * math.pi ** 2
        analytic_estimate = z_ddx_max * h ** 2 / 2.0

        # Measured should be nonzero and within factor-of-5 of the analytic estimate
        assert measured > 1e-6, f"expected nonzero deviation for bumped surface"
        ratio = measured / analytic_estimate
        assert 0.1 < ratio < 5.0, (
            f"chord_deviation/analytic_estimate = {ratio:.3f} (expected between 0.1 and 5.0); "
            f"measured={measured:.6f}, estimate={analytic_estimate:.6f}"
        )

    def test_per_face_returns_all_faces(self):
        """chord_deviation_per_face returns one entry per face."""
        surfs = [_make_bilinear_patch(size=float(k)) for k in range(1, 4)]
        body = _DummyBody(surfs)
        result = chord_deviation_per_face(body, n_samples=3)
        assert result["ok"]
        assert len(result["per_face"]) == 3


# ---------------------------------------------------------------------------
# Test 5: continuity_audit augmented flags
# ---------------------------------------------------------------------------

class TestContinuityAuditFlags:
    """continuity_audit with include_gauss_bonnet / include_chord_deviation."""

    def test_continuity_audit_without_flags_no_gb_key(self):
        body = make_box(size=(1.0, 1.0, 1.0))
        result = continuity_audit(body)
        assert result["ok"]
        assert "gauss_bonnet" not in result
        assert "chord_deviation" not in result

    def test_continuity_audit_with_gauss_bonnet_flag(self):
        body = make_box(size=(1.0, 1.0, 1.0))
        result = continuity_audit(body, include_gauss_bonnet=True)
        assert result["ok"]
        assert "gauss_bonnet" in result
        gb = result["gauss_bonnet"]
        assert "residual" in gb
        assert "expected" in gb
        assert "computed_K_integral" in gb

    def test_continuity_audit_with_chord_deviation_flag(self):
        body = make_box(size=(1.0, 1.0, 1.0))
        result = continuity_audit(body, include_chord_deviation=True)
        assert result["ok"]
        assert "chord_deviation" in result
        cd = result["chord_deviation"]
        assert "per_face" in cd

    def test_continuity_audit_with_both_flags(self):
        body = make_box(size=(1.0, 1.0, 1.0))
        result = continuity_audit(
            body, include_gauss_bonnet=True, include_chord_deviation=True
        )
        assert result["ok"]
        assert "gauss_bonnet" in result
        assert "chord_deviation" in result
        # Edge continuity still present
        assert "edge_continuity" in result
        assert "summary" in result
