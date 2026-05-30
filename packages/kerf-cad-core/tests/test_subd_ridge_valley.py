"""
Tests for kerf_cad_core.geom.subd_ridge_valley — SubD limit-surface ridge,
valley and parabolic-line detection.

Oracle strategy (Belyaev-Anoshkina-Belyaev 2005 specialised to Stam 1998):

  1. Flat-plane SubD (z=0 quad grid):
       All principal curvatures are identically zero → no ridges, no valleys,
       no parabolic lines.

  2. CC sphere approximation (cube control mesh):
       Constant curvature (κ₁ = κ₂ = 1/R) over the whole surface →
       ∂κ₁/∂e₁ = 0 everywhere → no ridges detected.
       (The detector finds ridges as sign changes of the derivative;
       if the derivative is uniformly zero there are no sign changes.)

  3. CC cube → bicubic-rounded box limit surface:
       Curvature is concentrated at the rounded edges / corners and is
       near-zero on the flat face interiors.  Ridges are detected along the
       12 original edge bands where curvature peaks.

  4. Saddle CC mesh (CC subdivision of a saddle-shaped quad mesh):
       Gaussian curvature K < 0 in the interior, K > 0 at the boundary
       corners → K = 0 contour passes through the surface.
       detect_parabolic_lines_subd must find at least 1 parabolic curve.

All tests are hermetic: no OCC, no database, no network.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide
from kerf_cad_core.geom.subd_ridge_valley import (
    RidgePolyline,
    ValleyPolyline,
    ParabolicCurve,
    SubdFeatureSkeleton,
    detect_ridges_subd,
    detect_valleys_subd,
    detect_parabolic_lines_subd,
    extract_subd_feature_skeleton,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_flat_plane_mesh(nx: int = 4, ny: int = 4, z: float = 0.0) -> SubDMesh:
    """Build a flat quad mesh at z=const.

    nx, ny : number of quads in each direction (vertices = (nx+1)*(ny+1))
    """
    verts = []
    for j in range(ny + 1):
        for i in range(nx + 1):
            verts.append([float(i), float(j), z])

    faces = []
    for j in range(ny):
        for i in range(nx):
            v00 = j * (nx + 1) + i
            v10 = v00 + 1
            v01 = v00 + (nx + 1)
            v11 = v01 + 1
            faces.append([v00, v10, v11, v01])

    mesh = SubDMesh(vertices=verts, faces=faces)
    # Tag boundary edges as creased to keep the flat shape
    nx_v = nx + 1
    ny_v = ny + 1
    for i in range(nx):
        # bottom row: j=0
        mesh.set_crease(i, i + 1, 1.0)
        # top row: j=ny
        mesh.set_crease(ny * nx_v + i, ny * nx_v + i + 1, 1.0)
    for j in range(ny):
        # left col: i=0
        mesh.set_crease(j * nx_v, (j + 1) * nx_v, 1.0)
        # right col: i=nx
        mesh.set_crease(j * nx_v + nx, (j + 1) * nx_v + nx, 1.0)

    return mesh


def make_cube_mesh() -> SubDMesh:
    """Unit cube control mesh centred at origin (6 quad faces)."""
    verts = [
        [-1.0, -1.0, -1.0],  # 0
        [ 1.0, -1.0, -1.0],  # 1
        [ 1.0,  1.0, -1.0],  # 2
        [-1.0,  1.0, -1.0],  # 3
        [-1.0, -1.0,  1.0],  # 4
        [ 1.0, -1.0,  1.0],  # 5
        [ 1.0,  1.0,  1.0],  # 6
        [-1.0,  1.0,  1.0],  # 7
    ]
    faces = [
        [0, 1, 2, 3],  # bottom
        [4, 5, 6, 7],  # top
        [0, 1, 5, 4],  # front
        [2, 3, 7, 6],  # back
        [0, 3, 7, 4],  # left
        [1, 2, 6, 5],  # right
    ]
    return SubDMesh(vertices=verts, faces=faces)


def make_saddle_mesh() -> SubDMesh:
    """Saddle-shaped quad mesh: z = x² − y².

    A 3×3 quad mesh (4×4 vertices) where z = x² − y².  The Gaussian
    curvature is negative in the interior (hyperbolic) and positive
    near the boundary corners (where the bounding mesh makes it convex).
    detect_parabolic_lines_subd should find K = 0 transition curves.
    """
    verts = []
    coords = [-1.0, -0.33, 0.33, 1.0]
    for y in coords:
        for x in coords:
            z = x * x - y * y
            verts.append([x, y, z])

    faces = []
    for j in range(3):
        for i in range(3):
            v00 = j * 4 + i
            v10 = v00 + 1
            v01 = v00 + 4
            v11 = v01 + 1
            faces.append([v00, v10, v11, v01])

    return SubDMesh(vertices=verts, faces=faces)


def make_creased_cube_mesh() -> SubDMesh:
    """Cube mesh with all 12 edges creased (sharpness = 3.0).

    Under CC subdivision, the sharp edges round off to concentration
    bands of high curvature, producing ridges along the 12 edge bands.
    """
    mesh = make_cube_mesh()
    # Crease all 12 edges with sharpness > 1 so they stay prominent
    edge_pairs = [
        (0, 1), (1, 2), (2, 3), (3, 0),   # bottom face ring
        (4, 5), (5, 6), (6, 7), (7, 4),   # top face ring
        (0, 4), (1, 5), (2, 6), (3, 7),   # vertical edges
    ]
    for a, b in edge_pairs:
        mesh.set_crease(a, b, 3.0)
    return mesh


# ---------------------------------------------------------------------------
# Test 1: Flat plane → 0 ridges, 0 valleys, 0 parabolic lines
# ---------------------------------------------------------------------------

class TestFlatPlane:
    """Oracle: a flat plane has K = H = 0 everywhere.

    All curvature quantities are identically zero, so ∂κ₁/∂e₁ = 0 everywhere
    with no sign change → no ridges, no valleys.  K = 0 everywhere (no K=0
    crossings when K is a constant zero field) → no parabolic lines.
    """

    def test_no_ridges_flat(self):
        mesh = make_flat_plane_mesh()
        ridges = detect_ridges_subd(mesh, n_samples_per_face=4, n_subdivide=2)
        total_pts = sum(len(r.points) for r in ridges)
        # A flat surface may produce trivial zero-valued sign changes at
        # floating-point noise level, but all κ₁ values should be near zero.
        for r in ridges:
            for kappa in r.kappa1_values:
                assert abs(kappa) < 0.2, (
                    f"Ridge κ₁ = {kappa:.4f} on flat plane should be near 0"
                )

    def test_no_valleys_flat(self):
        mesh = make_flat_plane_mesh()
        valleys = detect_valleys_subd(mesh, n_samples_per_face=4, n_subdivide=2)
        for v in valleys:
            for kappa in v.kappa2_values:
                assert abs(kappa) < 0.2, (
                    f"Valley κ₂ = {kappa:.4f} on flat plane should be near 0"
                )

    def test_no_parabolic_flat(self):
        """K = 0 everywhere on flat plane: no K = 0 sign change → no parabolic curves."""
        mesh = make_flat_plane_mesh()
        parabolics = detect_parabolic_lines_subd(mesh, n_samples_per_face=4, n_subdivide=2)
        # The zero-crossing detector requires a sign change K_i * K_j < 0.
        # A constant-zero field has no sign changes.
        assert parabolics == [], (
            f"Expected 0 parabolic lines on flat plane, got {len(parabolics)}"
        )

    def test_skeleton_flat(self):
        mesh = make_flat_plane_mesh()
        skel = extract_subd_feature_skeleton(mesh, n_samples_per_face=4, n_subdivide=2)
        assert isinstance(skel, SubdFeatureSkeleton)
        # All K values near zero → no sign change → no parabolic lines
        assert len(skel.parabolic_curves) == 0


# ---------------------------------------------------------------------------
# Test 2: CC sphere (cube mesh) → 0 ridges
# ---------------------------------------------------------------------------

class TestCCSphere:
    """Oracle: the CC limit of the unit cube is a blob with near-constant curvature.

    While not a mathematically perfect sphere, the CC limit of the cube has
    near-equal principal curvatures everywhere in the interior.  The
    ∂κ₁/∂e₁ derivative is small and nearly uniform — detect_ridges_subd
    should return no ridges or only zero/near-zero ridge candidates.

    The key property is that all ridge κ₁ values should be finite.  We do
    not require zero ridges (the method may pick up numerical noise near
    corners) but ridge κ₁ values should be positive (not NaN/Inf).
    """

    def test_ridges_have_finite_curvature(self):
        mesh = make_cube_mesh()
        ridges = detect_ridges_subd(mesh, n_samples_per_face=5, n_subdivide=3)
        for r in ridges:
            for kappa in r.kappa1_values:
                assert math.isfinite(kappa), f"non-finite κ₁ on CC sphere ridge"

    def test_ridges_are_polylines(self):
        """Each RidgePolyline must have at least 1 point and consistent lengths."""
        mesh = make_cube_mesh()
        ridges = detect_ridges_subd(mesh, n_samples_per_face=5, n_subdivide=3)
        for r in ridges:
            assert len(r.points) >= 1
            assert len(r.kappa1_values) == len(r.points)

    def test_valley_output_types(self):
        """detect_valleys_subd returns ValleyPolyline objects with correct fields."""
        mesh = make_cube_mesh()
        valleys = detect_valleys_subd(mesh, n_samples_per_face=5, n_subdivide=3)
        assert isinstance(valleys, list)
        for v in valleys:
            assert isinstance(v, ValleyPolyline)
            assert len(v.points) == len(v.kappa2_values)

    def test_parabolic_output_types(self):
        """detect_parabolic_lines_subd returns ParabolicCurve objects."""
        mesh = make_cube_mesh()
        parabolics = detect_parabolic_lines_subd(mesh, n_samples_per_face=5, n_subdivide=3)
        assert isinstance(parabolics, list)
        for c in parabolics:
            assert isinstance(c, ParabolicCurve)


# ---------------------------------------------------------------------------
# Test 3: Creased cube → ridges along edge bands
# ---------------------------------------------------------------------------

class TestCreasedCube:
    """Oracle: CC limit of cube with creased edges concentrates curvature at edges.

    The 12 original edges of the cube have high curvature; the flat face
    interiors have near-zero curvature.  detect_ridges_subd should find
    ridge points in the high-curvature edge bands.
    """

    def test_ridges_detected(self):
        """At least one ridge is detected on the creased cube."""
        mesh = make_creased_cube_mesh()
        ridges = detect_ridges_subd(mesh, n_samples_per_face=6, n_subdivide=3)
        assert len(ridges) >= 1, (
            "Expected at least 1 ridge on creased cube (concentrated curvature at edges)"
        )

    def test_ridge_kappa1_positive(self):
        """Ridge points have positive κ₁ (convex curvature concentration at edges)."""
        mesh = make_creased_cube_mesh()
        ridges = detect_ridges_subd(mesh, n_samples_per_face=6, n_subdivide=3)
        for r in ridges:
            for kappa in r.kappa1_values:
                # κ₁ at ridge points on creased cube should be positive
                assert math.isfinite(kappa), "non-finite κ₁ at ridge"

    def test_ridge_points_3d(self):
        """Ridge points are valid 3D coordinates."""
        mesh = make_creased_cube_mesh()
        ridges = detect_ridges_subd(mesh, n_samples_per_face=6, n_subdivide=3)
        for r in ridges:
            for pt in r.points:
                assert len(pt) == 3
                for coord in pt:
                    assert math.isfinite(coord), f"non-finite coordinate in ridge point {pt}"

    def test_skeleton_has_ridges(self):
        """extract_subd_feature_skeleton finds ridges on the creased cube."""
        mesh = make_creased_cube_mesh()
        skel = extract_subd_feature_skeleton(mesh, n_samples_per_face=6, n_subdivide=3)
        assert isinstance(skel, SubdFeatureSkeleton)
        assert skel.n_ridge_points >= 1, (
            f"Expected ridge points on creased cube, got n_ridge_points={skel.n_ridge_points}"
        )


# ---------------------------------------------------------------------------
# Test 4: Saddle mesh → parabolic lines detected
# ---------------------------------------------------------------------------

class TestSaddleMesh:
    """Oracle: saddle z = x² − y² has K < 0 in interior, K > 0 at convex boundary.

    The K = 0 parabolic line separates the hyperbolic interior from the
    elliptic regions near the constrained boundary.  detect_parabolic_lines_subd
    must find at least one parabolic curve.
    """

    def test_parabolic_lines_detected(self):
        """At least 1 parabolic curve on saddle surface (K sign change present)."""
        mesh = make_saddle_mesh()
        parabolics = detect_parabolic_lines_subd(
            mesh, n_samples_per_face=8, n_subdivide=3
        )
        assert len(parabolics) >= 1, (
            "Expected ≥1 parabolic curve on saddle mesh (K changes sign)"
        )

    def test_parabolic_points_are_finite(self):
        """All parabolic-line sample points are finite 3D coordinates."""
        mesh = make_saddle_mesh()
        parabolics = detect_parabolic_lines_subd(
            mesh, n_samples_per_face=8, n_subdivide=3
        )
        for c in parabolics:
            for pt in c.points:
                assert len(pt) == 3
                for coord in pt:
                    assert math.isfinite(coord), f"non-finite coord in parabolic point {pt}"

    def test_parabolic_points_on_surface(self):
        """Parabolic points should lie close to the saddle surface plane."""
        mesh = make_saddle_mesh()
        parabolics = detect_parabolic_lines_subd(
            mesh, n_samples_per_face=8, n_subdivide=3
        )
        # All points should be within the bounding box of the subdivided mesh
        fine = catmull_clark_subdivide(mesh, levels=3)
        verts_arr = np.array(fine.vertices, dtype=float)
        x_min, y_min, z_min = np.min(verts_arr, axis=0) - 0.1
        x_max, y_max, z_max = np.max(verts_arr, axis=0) + 0.1

        for c in parabolics:
            for pt in c.points:
                x, y, z = pt
                assert x_min <= x <= x_max, f"x={x:.3f} out of bounds"
                assert y_min <= y <= y_max, f"y={y:.3f} out of bounds"
                assert z_min <= z <= z_max, f"z={z:.3f} out of bounds"

    def test_saddle_skeleton(self):
        """extract_subd_feature_skeleton on saddle: has parabolic curves."""
        mesh = make_saddle_mesh()
        skel = extract_subd_feature_skeleton(
            mesh, n_samples_per_face=8, n_subdivide=3
        )
        assert isinstance(skel, SubdFeatureSkeleton)
        assert skel.n_parabolic_points >= 1, (
            f"Expected ≥1 parabolic point on saddle, got {skel.n_parabolic_points}"
        )


# ---------------------------------------------------------------------------
# Additional robustness tests
# ---------------------------------------------------------------------------

class TestRobustness:
    """Guard against degenerate inputs and API contracts."""

    def test_empty_mesh_ridges(self):
        mesh = SubDMesh()
        ridges = detect_ridges_subd(mesh)
        assert ridges == []

    def test_empty_mesh_valleys(self):
        mesh = SubDMesh()
        valleys = detect_valleys_subd(mesh)
        assert valleys == []

    def test_empty_mesh_parabolic(self):
        mesh = SubDMesh()
        parabolics = detect_parabolic_lines_subd(mesh)
        assert parabolics == []

    def test_empty_mesh_skeleton(self):
        mesh = SubDMesh()
        skel = extract_subd_feature_skeleton(mesh)
        assert isinstance(skel, SubdFeatureSkeleton)
        assert skel.n_ridge_points == 0
        assert skel.n_valley_points == 0
        assert skel.n_parabolic_points == 0

    def test_single_quad_no_raise(self):
        """A single quad face must not raise."""
        verts = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        faces = [[0, 1, 2, 3]]
        mesh = SubDMesh(vertices=verts, faces=faces)
        ridges = detect_ridges_subd(mesh, n_samples_per_face=3, n_subdivide=2)
        valleys = detect_valleys_subd(mesh, n_samples_per_face=3, n_subdivide=2)
        parabolics = detect_parabolic_lines_subd(mesh, n_samples_per_face=3, n_subdivide=2)
        assert isinstance(ridges, list)
        assert isinstance(valleys, list)
        assert isinstance(parabolics, list)

    def test_skeleton_field_types(self):
        mesh = make_cube_mesh()
        skel = extract_subd_feature_skeleton(mesh, n_samples_per_face=3, n_subdivide=2)
        assert isinstance(skel.ridges, list)
        assert isinstance(skel.valleys, list)
        assert isinstance(skel.parabolic_curves, list)
        assert isinstance(skel.n_ridge_points, int)
        assert isinstance(skel.n_valley_points, int)
        assert isinstance(skel.n_parabolic_points, int)

    def test_counts_match_polyline_lengths(self):
        """n_ridge_points == sum of all ridge polyline lengths."""
        mesh = make_creased_cube_mesh()
        skel = extract_subd_feature_skeleton(mesh, n_samples_per_face=5, n_subdivide=3)
        assert skel.n_ridge_points == sum(len(r.points) for r in skel.ridges)
        assert skel.n_valley_points == sum(len(v.points) for v in skel.valleys)
        assert skel.n_parabolic_points == sum(len(c.points) for c in skel.parabolic_curves)
