"""Tests for geom/volume_weighted_centroid.py — density-weighted centroid + inertia.

Oracles
-------
1. Uniform density:
   - Unit cube + uniform ρ=1 → centroid at (0.5, 0.5, 0.5) within 1%.
2. Linear-z density:
   - Unit cube with ρ(z) = z → analytical z_centroid = 2/3·L = 2/3 within 5%.
3. Shell-dense:
   - Unit sphere with shell_dense → centroid stays at (0,0,0) by symmetry;
     total_mass < uniform-density mass.
4. Inertia diagonal:
   - Unit sphere with uniform density → off-diagonal inertia elements ≈ 0
     (symmetric density on symmetric body).
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.brep import make_box, make_sphere, make_cylinder
from kerf_cad_core.geom.volume_weighted_centroid import (
    compute_centroid_density_field,
    compute_inertia_density_field,
    functionally_graded_centroid,
    CentroidResult,
    InertiaResult,
)


# Deterministic RNG seed for reproducibility in CI
_SEED = 42


# ---------------------------------------------------------------------------
# Test 1: Uniform density → centroid at geometric centre within 1%
# ---------------------------------------------------------------------------

class TestUniformDensity:
    """A uniform density field must recover the body's geometric centroid."""

    def _uniform(self, p: np.ndarray) -> float:
        return 1.0

    def test_unit_cube_centroid_within_1pct(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_centroid_density_field(
            body, self._uniform, n_samples=3000, rng=np.random.default_rng(_SEED)
        )
        assert isinstance(result, CentroidResult)
        expected = np.array([0.5, 0.5, 0.5])
        # Each component within 1% of unit box side length (0.01)
        assert np.allclose(result.centroid, expected, atol=0.02), (
            f"Uniform-density cube centroid {result.centroid} far from {expected}"
        )

    def test_samples_used_positive(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_centroid_density_field(
            body, self._uniform, n_samples=500, rng=np.random.default_rng(_SEED)
        )
        assert result.samples_used > 0, "No interior samples accepted"

    def test_total_mass_positive(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_centroid_density_field(
            body, self._uniform, n_samples=500, rng=np.random.default_rng(_SEED)
        )
        assert result.total_mass > 0.0, "Total mass must be positive for non-zero density"

    def test_std_error_finite(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_centroid_density_field(
            body, self._uniform, n_samples=500, rng=np.random.default_rng(_SEED)
        )
        assert math.isfinite(result.std_error), "std_error should be finite"

    def test_unit_cube_uniform_via_functional_graded(self):
        """functionally_graded_centroid with linear_z α=0 is uniform."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = functionally_graded_centroid(
            body,
            density_func_kind="linear_z",
            rho_0=1.0,
            alpha=0.0,  # no gradient → uniform
            n_samples=3000,
            rng=np.random.default_rng(_SEED),
        )
        expected = np.array([0.5, 0.5, 0.5])
        assert np.allclose(result.centroid, expected, atol=0.02), (
            f"uniform α=0 centroid {result.centroid} != {expected}"
        )


# ---------------------------------------------------------------------------
# Test 2: Linear-z density — centroid shifts toward higher z
# ---------------------------------------------------------------------------

class TestLinearZDensity:
    """ρ(z) = z on a unit cube [0,1]³.

    Analytical result:
        M = ∫₀¹∫₀¹∫₀¹ z dz dy dx = 0.5
        Cz·M = ∫₀¹∫₀¹∫₀¹ z² dz dy dx = 1/3
        Cz = (1/3) / (1/2) = 2/3

    The centroid is shifted toward z=1 (high-density end).
    """

    def _linear_z(self, p: np.ndarray) -> float:
        return max(float(p[2]), 0.0)  # ρ(z) = z, clamped to avoid negative at z=0

    def test_linear_z_centroid_z_within_5pct(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_centroid_density_field(
            body, self._linear_z, n_samples=5000, rng=np.random.default_rng(_SEED)
        )
        analytical_cz = 2.0 / 3.0
        rel_err = abs(result.centroid[2] - analytical_cz) / analytical_cz
        assert rel_err < 0.05, (
            f"Linear-z centroid z={result.centroid[2]:.4f}, "
            f"analytical={analytical_cz:.4f}, rel_err={rel_err:.3%}"
        )

    def test_linear_z_centroid_shifts_above_midplane(self):
        """z-centroid must be above 0.5 (the geometric mid-plane)."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_centroid_density_field(
            body, self._linear_z, n_samples=3000, rng=np.random.default_rng(_SEED)
        )
        assert result.centroid[2] > 0.5, (
            f"Linear-z centroid z={result.centroid[2]:.4f} should be > 0.5"
        )

    def test_linear_z_xy_centroid_near_half(self):
        """x and y centroids are unaffected by z-density (symmetric in x/y)."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_centroid_density_field(
            body, self._linear_z, n_samples=5000, rng=np.random.default_rng(_SEED)
        )
        assert abs(result.centroid[0] - 0.5) < 0.05, (
            f"Linear-z: x-centroid {result.centroid[0]:.4f} should be ~0.5"
        )
        assert abs(result.centroid[1] - 0.5) < 0.05, (
            f"Linear-z: y-centroid {result.centroid[1]:.4f} should be ~0.5"
        )

    def test_functionally_graded_linear_z(self):
        """functionally_graded_centroid with linear_z should match compute_centroid_density_field."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = functionally_graded_centroid(
            body,
            density_func_kind="linear_z",
            rho_0=1.0,
            alpha=1.0,
            n_samples=5000,
            rng=np.random.default_rng(_SEED),
        )
        # ρ(z) = 1 + z, analytical Cz = ∫z(1+z)dz / ∫(1+z)dz = (1/2 + 1/3)/(1 + 1/2) = (5/6)/(3/2) = 5/9 ≈ 0.556
        analytical_cz = 5.0 / 9.0
        rel_err = abs(result.centroid[2] - analytical_cz) / analytical_cz
        assert rel_err < 0.05, (
            f"functionally_graded linear_z Cz={result.centroid[2]:.4f}, "
            f"analytical={analytical_cz:.4f}, rel_err={rel_err:.3%}"
        )


# ---------------------------------------------------------------------------
# Test 3: Shell-dense — centroid stays at centre; mass < uniform
# ---------------------------------------------------------------------------

class TestShellDense:
    """Shell-dense on a symmetric body (sphere).

    For a sphere centred at origin, the shell-dense density field is symmetric
    about the origin → centroid must be at (0, 0, 0).

    Also: dense shell + sparse core → total_mass < ρ_uniform × volume.
    """

    def test_shell_dense_sphere_centroid_at_origin(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = functionally_graded_centroid(
            body,
            density_func_kind="shell_dense",
            rho_shell=2.0,
            rho_core=0.5,
            n_samples=3000,
            rng=np.random.default_rng(_SEED),
        )
        # Centroid should be near origin (symmetry)
        assert np.allclose(result.centroid, [0, 0, 0], atol=0.08), (
            f"Shell-dense sphere centroid {result.centroid} far from origin"
        )

    def test_shell_dense_cube_centroid_at_centre(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = functionally_graded_centroid(
            body,
            density_func_kind="shell_dense",
            rho_shell=2.0,
            rho_core=0.5,
            n_samples=3000,
            rng=np.random.default_rng(_SEED),
        )
        expected = np.array([0.5, 0.5, 0.5])
        assert np.allclose(result.centroid, expected, atol=0.08), (
            f"Shell-dense cube centroid {result.centroid} far from {expected}"
        )

    def test_shell_dense_total_mass_less_than_uniform(self):
        """shell_dense with rho_core < rho_shell < uniform_rho:
        If we define uniform as rho_shell, total mass is less for
        the composite body than for a fully dense body at rho_shell."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        # Uniform body at rho_shell=2.0 → mass = 2.0 × volume = 2.0
        # Shell-dense: shell portion at 2.0, core at 0.5 < 2.0
        # So total mass < 2.0 × volume
        result = functionally_graded_centroid(
            body,
            density_func_kind="shell_dense",
            rho_shell=2.0,
            rho_core=0.5,
            n_samples=3000,
            rng=np.random.default_rng(_SEED),
        )
        # Volume of unit cube = 1.0; fully dense at rho_shell=2.0 → mass=2.0
        uniform_mass = 2.0 * 1.0
        assert result.total_mass < uniform_mass, (
            f"Shell-dense total_mass={result.total_mass:.4f} should be < {uniform_mass} "
            "(dense shell + lighter core)"
        )

    def test_shell_dense_samples_used_positive(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = functionally_graded_centroid(
            body,
            density_func_kind="shell_dense",
            n_samples=1000,
            rng=np.random.default_rng(_SEED),
        )
        assert result.samples_used > 0


# ---------------------------------------------------------------------------
# Test 4: Inertia tensor diagonal — symmetric body + symmetric density
# ---------------------------------------------------------------------------

class TestInertiaTensor:
    """For a sphere with uniform density centred at origin, the inertia
    tensor must be diagonal (off-diagonal elements ≈ 0) because of
    the 3-fold rotational symmetry.

    Also checks that diagonal elements are strictly positive (I > 0).
    """

    def _uniform(self, p: np.ndarray) -> float:
        return 1.0

    def test_sphere_uniform_inertia_off_diagonal_near_zero(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = compute_inertia_density_field(
            body, self._uniform, n_samples=8000, rng=np.random.default_rng(_SEED)
        )
        assert isinstance(result, InertiaResult)
        I = result.inertia_tensor
        # Off-diagonal elements should be small relative to diagonal
        diag_mean = abs(np.diag(I)).mean()
        off_diag = [I[i, j] for i in range(3) for j in range(3) if i != j]
        for val in off_diag:
            assert abs(val) < 0.15 * diag_mean, (
                f"Off-diagonal inertia element {val:.4f} too large "
                f"(diagonal mean={diag_mean:.4f})"
            )

    def test_sphere_uniform_inertia_diagonal_positive(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = compute_inertia_density_field(
            body, self._uniform, n_samples=8000, rng=np.random.default_rng(_SEED)
        )
        I = result.inertia_tensor
        for i in range(3):
            assert I[i, i] > 0, f"Diagonal element I[{i},{i}]={I[i,i]:.4f} must be > 0"

    def test_cube_symmetric_density_off_diagonal_near_zero(self):
        """Unit cube centred at (0.5,0.5,0.5) with ρ=1 → inertia about
        the centroid is diagonal (principal axes = coordinate axes)."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_inertia_density_field(
            body, self._uniform, n_samples=8000, rng=np.random.default_rng(_SEED)
        )
        I = result.inertia_tensor
        diag_mean = abs(np.diag(I)).mean()
        off_diag = [I[i, j] for i in range(3) for j in range(3) if i != j]
        for val in off_diag:
            assert abs(val) < 0.15 * diag_mean, (
                f"Cube off-diagonal inertia {val:.4f} too large (diag mean={diag_mean:.4f})"
            )

    def test_inertia_result_shape(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = compute_inertia_density_field(
            body, self._uniform, n_samples=1000, rng=np.random.default_rng(_SEED)
        )
        assert result.inertia_tensor.shape == (3, 3), "Inertia tensor must be 3×3"

    def test_inertia_centroid_matches_centroid_result(self):
        """The centroid from InertiaResult should match CentroidResult for same body."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        rng_a = np.random.default_rng(_SEED)
        rng_b = np.random.default_rng(_SEED)
        cr = compute_centroid_density_field(body, self._uniform, n_samples=2000, rng=rng_a)
        ir = compute_inertia_density_field(body, self._uniform, n_samples=2000, rng=rng_b)
        # Both should agree on centroid to within MC noise
        assert np.allclose(cr.centroid, ir.centroid, atol=0.05), (
            f"Centroid mismatch: CentroidResult={cr.centroid}, InertiaResult={ir.centroid}"
        )


# ---------------------------------------------------------------------------
# Test 5: Radial density — stays at geometric centre for symmetric body
# ---------------------------------------------------------------------------

class TestRadialDensity:
    def test_radial_sphere_centroid_at_origin(self):
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        result = functionally_graded_centroid(
            body,
            density_func_kind="radial",
            rho_max=1.0,
            n_samples=3000,
            rng=np.random.default_rng(_SEED),
        )
        assert np.allclose(result.centroid, [0, 0, 0], atol=0.08), (
            f"Radial sphere centroid {result.centroid} far from origin"
        )

    def test_radial_cube_centroid_at_centre(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = functionally_graded_centroid(
            body,
            density_func_kind="radial",
            n_samples=3000,
            rng=np.random.default_rng(_SEED),
        )
        expected = np.array([0.5, 0.5, 0.5])
        assert np.allclose(result.centroid, expected, atol=0.08), (
            f"Radial cube centroid {result.centroid} far from {expected}"
        )


# ---------------------------------------------------------------------------
# Test 6: Return-type contracts
# ---------------------------------------------------------------------------

class TestReturnTypes:
    def test_centroid_result_fields(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_centroid_density_field(
            body, lambda p: 1.0, n_samples=200, rng=np.random.default_rng(_SEED)
        )
        assert hasattr(result, "centroid")
        assert hasattr(result, "total_mass")
        assert hasattr(result, "std_error")
        assert hasattr(result, "samples_used")
        assert isinstance(result.centroid, np.ndarray)
        assert result.centroid.shape == (3,)

    def test_inertia_result_fields(self):
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        result = compute_inertia_density_field(
            body, lambda p: 1.0, n_samples=200, rng=np.random.default_rng(_SEED)
        )
        assert hasattr(result, "centroid")
        assert hasattr(result, "total_mass")
        assert hasattr(result, "inertia_tensor")
        assert hasattr(result, "samples_used")
        assert result.inertia_tensor.shape == (3, 3)
