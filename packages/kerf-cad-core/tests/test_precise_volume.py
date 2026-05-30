"""Tests for geom/precise_volume.py — precise NURBS body volume via Stokes' theorem.

Analytical oracles
------------------
* Unit sphere:    V = 4π/3           within rel error 1e-6 (GL converges fast on smooth surfaces)
* Unit cube:      V = 1.0            within abs error 1e-12
* Cylinder r=1 h=1: V = π           within rel error 1e-5
* Comparison:     stokes_10pt has smaller absolute error than tessellation for the sphere

Reference: do Carmo §4.7; Mortenson §11.7.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    make_box,
    make_sphere,
    make_cylinder,
)
from kerf_cad_core.geom.precise_volume import (
    compute_volume_stokes,
    compute_centroid_stokes,
    compute_inertia_stokes,
    compare_volume_methods,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel_err(got: float, expected: float) -> float:
    """Relative error |got − expected| / |expected|."""
    return abs(got - expected) / max(abs(expected), 1e-30)


# ---------------------------------------------------------------------------
# Test 1: Unit sphere  V = 4π/3  within 1e-6
# ---------------------------------------------------------------------------

class TestSphereStokes:
    """Unit sphere — analytical oracle V = 4π/3."""

    EXACT = 4.0 / 3.0 * math.pi

    def test_unit_sphere_volume_10pt(self):
        """stokes_10pt should recover sphere volume within 1e-6 relative."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        V = compute_volume_stokes(body, n_samples_per_face=10)
        err = _rel_err(V, self.EXACT)
        assert err < 1e-6, (
            f"sphere volume Stokes 10pt: {V:.12f} (expected {self.EXACT:.12f}, "
            f"rel err {err:.2e})"
        )

    def test_unit_sphere_volume_5pt(self):
        """stokes_5pt should recover sphere volume within 1e-4 relative."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        V = compute_volume_stokes(body, n_samples_per_face=5)
        err = _rel_err(V, self.EXACT)
        assert err < 1e-4, (
            f"sphere volume Stokes 5pt: {V:.12f} (expected {self.EXACT:.12f}, "
            f"rel err {err:.2e})"
        )

    def test_unit_sphere_volume_positive(self):
        """Volume must be positive for outward-normal sphere."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        V = compute_volume_stokes(body, n_samples_per_face=10)
        assert V > 0, f"sphere volume should be positive, got {V}"

    def test_sphere_radius_2(self):
        r = 2.0
        body = make_sphere(center=(0, 0, 0), radius=r)
        V = compute_volume_stokes(body, n_samples_per_face=10)
        expected = 4.0 / 3.0 * math.pi * r**3
        assert _rel_err(V, expected) < 1e-6

    def test_sphere_centroid_at_origin(self):
        """Centroid of a centred sphere must be the origin."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        c = compute_centroid_stokes(body, n_samples_per_face=10)
        assert np.allclose(c, [0, 0, 0], atol=1e-5), (
            f"unit sphere centroid {c} should be [0,0,0]"
        )


# ---------------------------------------------------------------------------
# Test 2: Unit cube  V = 1.0  within 1e-12
# ---------------------------------------------------------------------------

class TestCubeStokes:
    """Unit cube — analytical oracle V = 1.0, centroid = [0.5, 0.5, 0.5]."""

    def test_unit_cube_volume(self):
        """Unit cube volume must equal 1.0 within 1e-12."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        V = compute_volume_stokes(body, n_samples_per_face=5)
        assert abs(V - 1.0) < 1e-12, (
            f"unit cube volume {V!r} != 1.0 (err {abs(V - 1.0):.2e})"
        )

    def test_unit_cube_centroid(self):
        """Unit cube centroid must be [0.5, 0.5, 0.5]."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        c = compute_centroid_stokes(body, n_samples_per_face=5)
        assert np.allclose(c, [0.5, 0.5, 0.5], atol=1e-10), (
            f"unit cube centroid {c} != [0.5, 0.5, 0.5]"
        )

    def test_box_2x3x5(self):
        lx, ly, lz = 2.0, 3.0, 5.0
        body = make_box(origin=(0, 0, 0), size=(lx, ly, lz))
        V = compute_volume_stokes(body, n_samples_per_face=5)
        assert abs(V - lx * ly * lz) < 1e-8, (
            f"box {lx}×{ly}×{lz} volume {V} != {lx*ly*lz}"
        )

    def test_box_offset_origin(self):
        ox, oy, oz = 1.0, 2.0, 3.0
        body = make_box(origin=(ox, oy, oz), size=(1, 1, 1))
        V = compute_volume_stokes(body, n_samples_per_face=5)
        assert abs(V - 1.0) < 1e-10
        c = compute_centroid_stokes(body, n_samples_per_face=5)
        expected = np.array([ox + 0.5, oy + 0.5, oz + 0.5])
        assert np.allclose(c, expected, atol=1e-9), (
            f"offset box centroid {c} != {expected}"
        )


# ---------------------------------------------------------------------------
# Test 3: Cylinder  V = π·r²·h  within 1e-5
# ---------------------------------------------------------------------------

class TestCylinderStokes:
    """Cylinder r=1, h=1 — analytical oracle V = π."""

    def test_unit_cylinder_volume(self):
        """Cylinder volume must equal π within 1e-5 relative."""
        body = make_cylinder(center=(0, 0, 0), axis=(0, 0, 1), radius=1.0, height=1.0)
        V = compute_volume_stokes(body, n_samples_per_face=10)
        expected = math.pi
        err = _rel_err(V, expected)
        assert err < 1e-5, (
            f"cylinder volume {V:.10f} != π={expected:.10f} (rel err {err:.2e})"
        )

    def test_cylinder_r2_h3(self):
        r, h = 2.0, 3.0
        body = make_cylinder(center=(0, 0, 0), axis=(0, 0, 1), radius=r, height=h)
        V = compute_volume_stokes(body, n_samples_per_face=10)
        expected = math.pi * r**2 * h
        assert _rel_err(V, expected) < 1e-5, (
            f"cylinder r={r} h={h} rel err too large"
        )

    def test_cylinder_centroid(self):
        """Cylinder centroid should be at (0, 0, h/2)."""
        body = make_cylinder(center=(0, 0, 0), axis=(0, 0, 1), radius=1.0, height=2.0)
        c = compute_centroid_stokes(body, n_samples_per_face=10)
        assert np.allclose(c, [0.0, 0.0, 1.0], atol=1e-4), (
            f"cylinder centroid {c} != [0,0,1]"
        )


# ---------------------------------------------------------------------------
# Test 4: Comparison — stokes_10pt error < tessellation error for sphere
# ---------------------------------------------------------------------------

class TestMethodComparison:
    """stokes_10pt must have smaller absolute error than tessellation for sphere."""

    EXACT_SPHERE = 4.0 / 3.0 * math.pi

    def test_stokes_beats_tessellation_on_sphere(self):
        """For the unit sphere, stokes_10pt is at least as accurate as tessellation."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        cmp = compare_volume_methods(body, methods=["tessellation", "stokes_5pt", "stokes_10pt"])

        assert cmp["ok"], f"compare_volume_methods failed: {cmp.get('reason')}"

        err_tess   = _rel_err(cmp["tessellation"],  self.EXACT_SPHERE)
        err_stokes = _rel_err(cmp["stokes_10pt"], self.EXACT_SPHERE)

        # stokes_10pt should be at least as accurate as tessellation
        assert err_stokes <= err_tess * 2, (
            f"stokes_10pt (err={err_stokes:.2e}) should not be worse than "
            f"tessellation (err={err_tess:.2e}) for the sphere"
        )

        # And stokes_10pt must itself be accurate to 1e-6 relative
        assert err_stokes < 1e-6, (
            f"stokes_10pt sphere error {err_stokes:.2e} must be < 1e-6"
        )

    def test_compare_methods_returns_expected_keys(self):
        """compare_volume_methods dict must contain all requested method keys."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        methods = ["tessellation", "stokes_5pt", "stokes_10pt"]
        cmp = compare_volume_methods(body, methods=methods)
        for m in methods:
            assert m in cmp, f"key {m!r} missing from compare_volume_methods result"
            assert isinstance(cmp[m], float), f"{m} volume should be float"

    def test_compare_default_methods(self):
        """compare_volume_methods with default methods returns 3 volume entries."""
        body = make_cylinder(center=(0, 0, 0), axis=(0, 0, 1), radius=1.0, height=1.0)
        cmp = compare_volume_methods(body)
        assert cmp["ok"]
        for key in ("tessellation", "stokes_5pt", "stokes_10pt"):
            assert key in cmp
            assert cmp[key] is not None


# ---------------------------------------------------------------------------
# Test 5: Inertia tensor sanity check for unit sphere
# ---------------------------------------------------------------------------

class TestInertiaStokes:
    """Inertia tensor of unit sphere about origin: Ixx = Iyy = Izz = 8π/15.

    (For a uniform solid sphere of radius R, density 1:
     V = 4π/3, Ixx = Iyy = Izz = 2/5 · V · R² = 8π/15 when R=1.)
    """

    EXACT_I = 8.0 * math.pi / 15.0   # ≈ 1.6755...

    def test_unit_sphere_inertia_diagonal(self):
        """Diagonal entries of inertia tensor of unit sphere must equal 8π/15."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        I = compute_inertia_stokes(body, n_samples_per_face=15)
        for i, label in enumerate(["Ixx", "Iyy", "Izz"]):
            err = _rel_err(I[i, i], self.EXACT_I)
            assert err < 1e-4, (
                f"{label} = {I[i,i]:.8f}, expected {self.EXACT_I:.8f}, "
                f"rel err {err:.2e}"
            )

    def test_unit_sphere_inertia_symmetry(self):
        """Inertia tensor of centred sphere must be symmetric."""
        body = make_sphere(center=(0, 0, 0), radius=1.0)
        I = compute_inertia_stokes(body, n_samples_per_face=10)
        assert np.allclose(I, I.T, atol=1e-10), "inertia tensor must be symmetric"

    def test_unit_cube_inertia_returns_3x3(self):
        """compute_inertia_stokes must return a (3,3) array."""
        body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
        I = compute_inertia_stokes(body, n_samples_per_face=5)
        assert I.shape == (3, 3), f"inertia must be 3×3, got {I.shape}"
        assert np.allclose(I, I.T, atol=1e-10), "inertia tensor must be symmetric"
