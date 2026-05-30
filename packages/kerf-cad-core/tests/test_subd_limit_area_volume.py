"""
Tests for kerf_cad_core.geom.subd_limit_area_volume
====================================================

Validates Stam-quadrature-based limit-surface area + volume integration.

Test oracle notes
-----------------
* CC cube cage (vertices at ±1, 6 quad faces, all valence-3 corners).
  High-subdivision reference (7 levels of CC): area ≈ 9.197, vol ≈ 0.8735.
  At subd_levels=4 the bilinear-limit approximation gives area ≈ 9.204
  (error < 0.1%) and vol ≈ 0.8735 (error < 0.01%).

* Flat 1×1 quad (subd_levels=0): the Stam limit positions map the four
  corners to [±0.25]² (open-boundary shrinkage is correct CC behaviour),
  giving a flat bilinear patch of area = 0.25. GL quadrature is exact
  for polynomial integrands, so n=4 and n=8 should agree to ≤ 1e-12.

* Convergence: refinement_convergence_test on the cube with subd_levels=4
  should report that area/volume are converged (GL already exact for the
  bilinear patch at n=4).

* Centroid of the cube should be at [0, 0, 0] to near machine precision.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_limit_area_volume import (
    compute_centroid,
    compute_enclosed_volume,
    compute_limit_area,
    refinement_convergence_test,
)


# ---------------------------------------------------------------------------
# Mesh factories
# ---------------------------------------------------------------------------

def _cc_cube() -> SubDMesh:
    """Unit CC cube cage: 8 vertices at ±1, 6 quad faces, valence-3 corners."""
    verts = [
        [-1., -1., -1.], [ 1., -1., -1.], [ 1.,  1., -1.], [-1.,  1., -1.],
        [-1., -1.,  1.], [ 1., -1.,  1.], [ 1.,  1.,  1.], [-1.,  1.,  1.],
    ]
    faces = [
        [0, 1, 2, 3],  # bottom z=-1
        [4, 5, 6, 7],  # top    z=+1
        [0, 1, 5, 4],  # front  y=-1
        [2, 3, 7, 6],  # back   y=+1
        [0, 3, 7, 4],  # left   x=-1
        [1, 2, 6, 5],  # right  x=+1
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _flat_unit_quad() -> SubDMesh:
    """Single flat 1×1 quad in the z=0 plane."""
    verts = [[0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# 1. CC cube limit area — within 1% of asymptotic
# ---------------------------------------------------------------------------

class TestCCCubeLimitArea:
    """compute_limit_area on the CC cube cage."""

    # High-subdivision asymptotic reference (7 CC levels of dense subdivision):
    # area ≈ 9.197   vol ≈ 0.8735
    # At subd_levels=4 the bilinear-limit estimate is within 0.1%:
    # area ≈ 9.204, vol ≈ 0.87347
    AREA_ASYMPTOTIC = 9.197
    AREA_TOL = 0.01  # 1% relative tolerance

    def test_area_within_1_percent_of_asymptotic(self):
        """compute_limit_area on CC cube at subd_levels=4 is within 1% of asymptote."""
        mesh = _cc_cube()
        area = compute_limit_area(mesh, n_samples_per_face=8, subd_levels=4)
        rel_err = abs(area - self.AREA_ASYMPTOTIC) / self.AREA_ASYMPTOTIC
        assert rel_err < self.AREA_TOL, (
            f"CC cube area {area:.6f} is {rel_err*100:.2f}% from "
            f"asymptotic {self.AREA_ASYMPTOTIC} (tolerance 1%)"
        )

    def test_area_positive(self):
        """Area must be strictly positive."""
        mesh = _cc_cube()
        area = compute_limit_area(mesh, n_samples_per_face=8, subd_levels=2)
        assert area > 0.0

    def test_area_monotone_with_subd_levels(self):
        """Area should converge monotonically as subd_levels increases."""
        mesh = _cc_cube()
        areas = [
            compute_limit_area(mesh, 8, subd_levels=sl) for sl in [2, 3, 4, 5]
        ]
        # Each refinement should bring area closer to the asymptote (decrease toward 9.197)
        # Check monotone decrease
        for i in range(len(areas) - 1):
            assert areas[i] >= areas[i + 1] - 1e-6, (
                f"Area not monotone decreasing: {areas}"
            )

    def test_area_never_raises_on_bad_input(self):
        """compute_limit_area never raises; returns 0.0 for empty mesh."""
        empty = SubDMesh()
        result = compute_limit_area(empty, n_samples_per_face=8, subd_levels=2)
        assert result == 0.0

    def test_area_scaled_cube(self):
        """Area scales as s^2 when the cube is scaled by factor s."""
        mesh = _cc_cube()
        s = 2.0
        scaled_verts = [[c * s for c in v] for v in mesh.vertices]
        mesh_scaled = SubDMesh(vertices=scaled_verts, faces=mesh.faces)
        area_orig = compute_limit_area(mesh, 8, subd_levels=3)
        area_scaled = compute_limit_area(mesh_scaled, 8, subd_levels=3)
        ratio = area_scaled / (area_orig + 1e-30)
        assert abs(ratio - s * s) < 0.01, (
            f"Scaled area ratio {ratio:.4f} != {s*s:.4f}"
        )


# ---------------------------------------------------------------------------
# 2. CC cube limit volume — within 1% of asymptotic
# ---------------------------------------------------------------------------

class TestCCCubeLimitVolume:
    """compute_enclosed_volume on the CC cube cage."""

    VOLUME_ASYMPTOTIC = 0.8735
    VOLUME_TOL = 0.01  # 1% relative tolerance

    def test_volume_within_1_percent_of_asymptotic(self):
        """compute_enclosed_volume on CC cube at subd_levels=4 is within 1% of asymptote."""
        mesh = _cc_cube()
        vol = compute_enclosed_volume(mesh, n_samples_per_face=8, subd_levels=4)
        rel_err = abs(vol - self.VOLUME_ASYMPTOTIC) / self.VOLUME_ASYMPTOTIC
        assert rel_err < self.VOLUME_TOL, (
            f"CC cube volume {vol:.8f} is {rel_err*100:.3f}% from "
            f"asymptotic {self.VOLUME_ASYMPTOTIC} (tolerance 1%)"
        )

    def test_volume_positive(self):
        """Volume must be non-negative."""
        mesh = _cc_cube()
        vol = compute_enclosed_volume(mesh, n_samples_per_face=8, subd_levels=2)
        assert vol > 0.0

    def test_volume_less_than_bounding_box(self):
        """Volume of CC cube limit < volume of the cage bounding box (2^3=8)."""
        mesh = _cc_cube()
        vol = compute_enclosed_volume(mesh, n_samples_per_face=8, subd_levels=2)
        assert vol < 8.0, f"Volume {vol} exceeds bounding box 8.0"

    def test_volume_never_raises_on_bad_input(self):
        """Never raises; returns 0.0 for empty mesh."""
        empty = SubDMesh()
        result = compute_enclosed_volume(empty, n_samples_per_face=8, subd_levels=2)
        assert result == 0.0

    def test_volume_scaled_cube(self):
        """Volume scales as s^3 when the cube is scaled by factor s."""
        mesh = _cc_cube()
        s = 3.0
        scaled_verts = [[c * s for c in v] for v in mesh.vertices]
        mesh_scaled = SubDMesh(vertices=scaled_verts, faces=mesh.faces)
        vol_orig = compute_enclosed_volume(mesh, 8, subd_levels=3)
        vol_scaled = compute_enclosed_volume(mesh_scaled, 8, subd_levels=3)
        ratio = vol_scaled / (vol_orig + 1e-30)
        assert abs(ratio - s * s * s) < 0.05, (
            f"Scaled volume ratio {ratio:.4f} != {s**3:.4f}"
        )


# ---------------------------------------------------------------------------
# 3. Flat surface area — GL is exact for bilinear polynomial integrands
# ---------------------------------------------------------------------------

class TestFlatSurfaceArea:
    """Flat mesh: GL quadrature is exact for bilinear patches."""

    def test_flat_area_gl_exact(self):
        """For a flat mesh, GL n=4 and n=8 agree to ≤ 1e-9 (GL is exact)."""
        mesh = _flat_unit_quad()
        a4 = compute_limit_area(mesh, n_samples_per_face=4, subd_levels=0)
        a8 = compute_limit_area(mesh, n_samples_per_face=8, subd_levels=0)
        assert abs(a4 - a8) < 1e-9, (
            f"Flat area at n=4 ({a4}) and n=8 ({a8}) differ by {abs(a4-a8):.2e}"
        )

    def test_flat_area_stam_limit_value(self):
        """Flat 1×1 quad at subd_levels=0: Stam limit shrinks corners to ±0.25,
        giving a flat 0.5×0.5 patch of area = 0.25 exactly.
        """
        mesh = _flat_unit_quad()
        area = compute_limit_area(mesh, n_samples_per_face=8, subd_levels=0)
        # Analytically: all 4 corners shrink to [0.25,0.75]×[0.25,0.75] → area = 0.5²= 0.25
        assert abs(area - 0.25) < 1e-9, (
            f"Flat 1×1 Stam-limit area = {area:.15f}, expected 0.25"
        )

    def test_flat_volume_zero(self):
        """Volume of a flat (open) surface should be ~0."""
        mesh = _flat_unit_quad()
        vol = compute_enclosed_volume(mesh, n_samples_per_face=8, subd_levels=0)
        # Flat patch has zero volume contribution
        assert abs(vol) < 1e-9, f"Flat surface volume = {vol:.2e}, expected ~0"

    def test_flat_stays_flat_after_subdivision(self):
        """All vertices of a subdivided flat mesh remain at z=0."""
        from kerf_cad_core.geom.subd import catmull_clark_subdivide
        mesh = _flat_unit_quad()
        sub = catmull_clark_subdivide(mesh, levels=3)
        z_vals = [v[2] for v in sub.vertices]
        max_z = max(abs(z) for z in z_vals)
        assert max_z < 1e-12, (
            f"Flat mesh z-coordinate after subdivision: max|z| = {max_z:.2e}"
        )

    def test_flat_area_larger_mesh(self):
        """A 2×2 grid of flat quads has area between 0 and input area."""
        # Build a 3×3 vertex grid (4 quads, 1×1 total)
        verts = []
        for j in range(3):
            for i in range(3):
                verts.append([i / 2.0, j / 2.0, 0.0])
        faces = [
            [0, 1, 4, 3], [1, 2, 5, 4],
            [3, 4, 7, 6], [4, 5, 8, 7],
        ]
        mesh = SubDMesh(vertices=verts, faces=faces)
        area = compute_limit_area(mesh, n_samples_per_face=8, subd_levels=0)
        # Area is positive and less than 1.0 (Stam shrinkage)
        assert 0.0 < area < 1.0, f"2×2 flat grid area = {area:.6f}"


# ---------------------------------------------------------------------------
# 4. Convergence test
# ---------------------------------------------------------------------------

class TestRefinementConvergence:
    """refinement_convergence_test reports converging area/volume sequences."""

    def test_convergence_runs_without_error(self):
        """refinement_convergence_test returns a complete dict."""
        mesh = _cc_cube()
        res = refinement_convergence_test(mesh, subd_levels=4)
        assert "n_list" in res
        assert "area_list" in res
        assert "volume_list" in res
        assert len(res["area_list"]) == 4
        assert len(res["volume_list"]) == 4

    def test_convergence_area_sequence_positive(self):
        """All area values in the convergence sequence are positive."""
        mesh = _cc_cube()
        res = refinement_convergence_test(mesh, subd_levels=4)
        for a in res["area_list"]:
            assert a > 0.0, f"Non-positive area in sequence: {a}"

    def test_convergence_volume_sequence_positive(self):
        """All volume values in the convergence sequence are positive."""
        mesh = _cc_cube()
        res = refinement_convergence_test(mesh, subd_levels=4)
        for v in res["volume_list"]:
            assert v > 0.0, f"Non-positive volume in sequence: {v}"

    def test_convergence_area_converged(self):
        """At subd_levels=4, GL quadrature is already converged for area."""
        mesh = _cc_cube()
        res = refinement_convergence_test(mesh, target_relative_error=1e-3, subd_levels=4)
        assert res["area_converged"], (
            f"Area not converged: {res['area_list']}, asymptote={res['area_asymptote']:.6f}"
        )

    def test_convergence_volume_converged(self):
        """At subd_levels=4, GL quadrature is already converged for volume."""
        mesh = _cc_cube()
        res = refinement_convergence_test(mesh, target_relative_error=1e-3, subd_levels=4)
        assert res["volume_converged"], (
            f"Volume not converged: {res['volume_list']}, asymptote={res['volume_asymptote']:.8f}"
        )

    def test_convergence_area_sequence_consistent(self):
        """Area at n=4 and n=32 agree within 0.01% (GL exact for bilinear)."""
        mesh = _cc_cube()
        res = refinement_convergence_test(mesh, subd_levels=4)
        a4 = res["area_list"][0]    # n=4
        a32 = res["area_list"][3]   # n=32
        rel_diff = abs(a4 - a32) / (a4 + 1e-30)
        assert rel_diff < 1e-4, (
            f"Area at n=4 ({a4:.6f}) and n=32 ({a32:.6f}) differ by {rel_diff*100:.4f}%"
        )

    def test_convergence_never_raises_empty(self):
        """refinement_convergence_test never raises on empty mesh."""
        empty = SubDMesh()
        res = refinement_convergence_test(empty)
        assert "area_list" in res


# ---------------------------------------------------------------------------
# 5. Centroid
# ---------------------------------------------------------------------------

class TestCentroid:
    """compute_centroid returns correct surface centroid."""

    def test_cube_centroid_at_origin(self):
        """CC cube is symmetric about origin — centroid should be [0,0,0]."""
        mesh = _cc_cube()
        c = compute_centroid(mesh, n_samples_per_face=8, subd_levels=2)
        assert c.shape == (3,)
        np.testing.assert_allclose(c, [0., 0., 0.], atol=1e-10)

    def test_centroid_flat_patch(self):
        """Flat quad centroid is at [0.5, 0.5, 0] (in the Stam-limit patch)."""
        mesh = _flat_unit_quad()
        c = compute_centroid(mesh, n_samples_per_face=8, subd_levels=0)
        # Stam limit: corners at [0.25,0.25], [0.75,0.25], [0.75,0.75], [0.25,0.75]
        # Centroid of that flat square = [0.5, 0.5, 0]
        np.testing.assert_allclose(c, [0.5, 0.5, 0.0], atol=1e-9)

    def test_centroid_never_raises(self):
        """compute_centroid never raises on empty mesh."""
        empty = SubDMesh()
        c = compute_centroid(empty)
        assert c.shape == (3,)

    def test_centroid_translates_with_mesh(self):
        """Centroid should translate by [dx, dy, dz] when mesh is shifted."""
        mesh = _cc_cube()
        dx, dy, dz = 5.0, -3.0, 2.0
        shifted_verts = [[v[0] + dx, v[1] + dy, v[2] + dz] for v in mesh.vertices]
        mesh_shifted = SubDMesh(vertices=shifted_verts, faces=mesh.faces)
        c_orig = compute_centroid(mesh, 8, subd_levels=2)
        c_shifted = compute_centroid(mesh_shifted, 8, subd_levels=2)
        np.testing.assert_allclose(
            c_shifted, c_orig + np.array([dx, dy, dz]), atol=1e-9
        )
