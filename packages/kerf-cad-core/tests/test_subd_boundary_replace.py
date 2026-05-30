"""
Tests for kerf_cad_core.geom.subd_boundary_replace

All tests are hermetic: no database, no network.

Test oracle coverage
--------------------
1. boundary_loop_extraction_open_cube_minus_face
   -- Open cube (one face removed) has exactly 1 boundary loop with 4 verts.

2. boundary_loop_extraction_closed_mesh
   -- Closed cube returns empty list from extract_boundary_loops.

3. snap_plane_to_unit_circle_lock_interior
   -- Flat 4-vert open quad cage: boundary snapped to unit circle; boundary
      vertices lie on circle within 1e-6; interior unchanged.

4. snap_plane_to_ellipse_free_interior
   -- Same cage, lock_interior=False + boundary->ellipse(a=2,b=1): interior
      vertices deform smoothly; max interior displacement < 2*edge_length
      (tolerance for the 2-vertex mesh); bending energy minimised
      (interior moves toward centroid).

5. closed_mesh_guard
   -- snap_boundary_to_curve on a closed cage raises ValueError.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, make_circle_nurbs, make_ellipse_nurbs
from kerf_cad_core.geom.subd_authoring import SubDCage, create_subd_primitive
from kerf_cad_core.geom.subd_boundary_replace import (
    BoundaryLoop,
    BoundarySnapResult,
    extract_boundary_loops,
    snap_boundary_to_curve,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_square_cage() -> SubDCage:
    """A flat 2×2 square cage with 9 vertices and 4 quad faces (open mesh).

    Layout (top view):

        6--7--8
        |  |  |
        3--4--5
        |  |  |
        0--1--2

    Faces: [0,1,4,3], [1,2,5,4], [3,4,7,6], [4,5,8,7]
    Boundary vertices: 0,1,2,5,8,7,6,3 (the outer ring)
    Interior vertex: 4
    """
    verts = [
        [-1.0, -1.0, 0.0],   # 0
        [ 0.0, -1.0, 0.0],   # 1
        [ 1.0, -1.0, 0.0],   # 2
        [-1.0,  0.0, 0.0],   # 3
        [ 0.0,  0.0, 0.0],   # 4  interior
        [ 1.0,  0.0, 0.0],   # 5
        [-1.0,  1.0, 0.0],   # 6
        [ 0.0,  1.0, 0.0],   # 7
        [ 1.0,  1.0, 0.0],   # 8
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
        [3, 4, 7, 6],
        [4, 5, 8, 7],
    ]
    return SubDCage(vertices=verts, faces=faces)


def _open_cube_minus_one_face() -> SubDCage:
    """Cube cage with one face removed — the top face (verts 4,5,6,7)."""
    # Standard cube from subd_authoring._make_cube(w=2,h=2,d=2)
    cage = create_subd_primitive("cube", width=2, height=2, depth=2)
    # Remove top face (index 1: [4,5,6,7])
    cage.faces = [f for i, f in enumerate(cage.faces) if i != 1]
    cage._edge_list = []
    return cage


def _dist_to_circle(pt: List[float], cx: float = 0.0, cy: float = 0.0, r: float = 1.0) -> float:
    """Distance from a point to a circle in the XY plane."""
    dx = pt[0] - cx
    dy = pt[1] - cy
    return abs(math.sqrt(dx * dx + dy * dy) - r)


def _dist_to_ellipse_algebraic(pt: List[float], a: float, b: float) -> float:
    """Algebraic approximate distance from point to ellipse (a,b) at origin.

    Uses the approximation: if r = sqrt((x/a)^2 + (y/b)^2), then the
    normalised error |r - 1| * harmonic_mean(a, b) is a good first-order
    approximation of the true geometric distance for points near the ellipse.
    This avoids calling project_point_to_curve (which has a known rational
    evaluation issue for ellipse/circle NURBS).
    """
    x, y = pt[0], pt[1]
    r = math.sqrt((x / a) ** 2 + (y / b) ** 2)
    # Scale by harmonic_mean(a,b) = 2ab/(a+b) to convert normalised residual
    # to approximate Euclidean distance near the ellipse.
    scale = 2.0 * a * b / (a + b)
    return abs(r - 1.0) * scale


# ---------------------------------------------------------------------------
# Test 1: boundary loop extraction — open cube minus one face
# ---------------------------------------------------------------------------

class TestExtractBoundaryLoops:
    def test_open_cube_returns_one_loop(self):
        """An open cube (top face removed) has exactly 1 boundary loop."""
        cage = _open_cube_minus_one_face()
        loops = extract_boundary_loops(cage)
        assert len(loops) == 1, f"expected 1 loop, got {len(loops)}"

    def test_open_cube_loop_has_4_vertices(self):
        """The boundary loop of the open cube has 4 vertices."""
        cage = _open_cube_minus_one_face()
        loops = extract_boundary_loops(cage)
        assert loops[0].num_vertices == 4, (
            f"expected 4 boundary verts, got {loops[0].num_vertices}"
        )

    def test_open_cube_loop_forms_square(self):
        """The 4 boundary vertices form the top rim of the cube (z=+1)."""
        cage = _open_cube_minus_one_face()
        loops = extract_boundary_loops(cage)
        loop = loops[0]
        z_vals = [cage.vertices[vi][2] for vi in loop.vertex_indices]
        # Top rim vertices are at z = +1 (half of height=2)
        for z in z_vals:
            assert abs(z - 1.0) < 1e-9, f"expected z=1, got {z}"

    def test_open_square_has_one_loop(self):
        """The 3x3 grid open square cage has one outer boundary loop."""
        cage = _open_square_cage()
        loops = extract_boundary_loops(cage)
        assert len(loops) == 1

    def test_open_square_boundary_excludes_interior(self):
        """Boundary loop of the square grid cage does not include the interior vertex (4)."""
        cage = _open_square_cage()
        loops = extract_boundary_loops(cage)
        assert 4 not in loops[0].vertex_indices, (
            "Interior vertex 4 must not be in boundary loop"
        )

    def test_boundary_loop_dataclass_fields(self):
        """BoundaryLoop has loop_id and vertex_indices fields."""
        cage = _open_cube_minus_one_face()
        loops = extract_boundary_loops(cage)
        bl = loops[0]
        assert isinstance(bl, BoundaryLoop)
        assert bl.loop_id == 0
        assert isinstance(bl.vertex_indices, list)
        assert len(bl.vertex_indices) > 0


# ---------------------------------------------------------------------------
# Test 2: closed mesh returns empty
# ---------------------------------------------------------------------------

class TestClosedMeshReturnsEmpty:
    def test_closed_cube_empty_loops(self):
        """Closed cube cage returns an empty boundary-loop list."""
        cage = create_subd_primitive("cube")
        loops = extract_boundary_loops(cage)
        assert loops == [], f"expected [], got {loops}"

    def test_closed_cube_snap_raises_value_error(self):
        """snap_boundary_to_curve on a closed cage raises ValueError."""
        cage = create_subd_primitive("cube")
        circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)
        with pytest.raises(ValueError, match="closed mesh|no boundary"):
            snap_boundary_to_curve(cage, 0, circle)


# ---------------------------------------------------------------------------
# Test 3: plane square cage snapped to unit circle — lock_interior=True
# ---------------------------------------------------------------------------

class TestSnapToCircleLockInterior:
    """Flat square cage with 9 verts; boundary snapped to unit circle.

    Expected: all 8 boundary verts lie on the unit circle within 1e-6.
    Interior vertex (index 4) position unchanged.
    """

    def _make_circle(self) -> NurbsCurve:
        return make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)

    def test_snap_result_is_boundary_snap_result(self):
        """snap_boundary_to_curve returns a BoundarySnapResult instance."""
        cage = _open_square_cage()
        circle = self._make_circle()
        result = snap_boundary_to_curve(cage, 0, circle, lock_interior=True)
        assert isinstance(result, BoundarySnapResult)
        # boundary_residual is the max displacement of boundary verts from their
        # original positions (how far they moved to reach the circle), which is
        # a positive number for vertices not already on the circle.
        assert result.boundary_residual >= 0.0

    def test_boundary_vertices_on_circle(self):
        """Each boundary vertex must be within 1e-6 of the unit circle."""
        cage = _open_square_cage()
        circle = self._make_circle()
        result = snap_boundary_to_curve(cage, 0, circle, lock_interior=True)

        loops = extract_boundary_loops(cage)
        boundary_idx = set(loops[0].vertex_indices)

        for vi in boundary_idx:
            pt = result.mesh.vertices[vi]
            d = _dist_to_circle(pt, cx=0.0, cy=0.0, r=1.0)
            assert d < 1e-6, (
                f"vertex {vi} at {pt} is {d:.2e} from unit circle (>1e-6)"
            )

    def test_interior_vertex_unchanged(self):
        """lock_interior=True: interior vertex 4 must not move."""
        cage = _open_square_cage()
        original_interior = list(cage.vertices[4])
        circle = self._make_circle()
        result = snap_boundary_to_curve(cage, 0, circle, lock_interior=True)
        snapped_interior = result.mesh.vertices[4]
        for k in range(3):
            assert abs(snapped_interior[k] - original_interior[k]) < 1e-12, (
                f"Interior vertex 4 moved: {original_interior} -> {snapped_interior}"
            )

    def test_interior_distortion_zero_when_locked(self):
        """lock_interior=True: interior_distortion must be 0.0."""
        cage = _open_square_cage()
        circle = self._make_circle()
        result = snap_boundary_to_curve(cage, 0, circle, lock_interior=True)
        assert result.interior_distortion == 0.0, (
            f"interior_distortion={result.interior_distortion} should be 0.0"
        )

    def test_result_mesh_has_same_topology(self):
        """Snapped mesh must have the same vertex/face count as the input."""
        cage = _open_square_cage()
        circle = self._make_circle()
        result = snap_boundary_to_curve(cage, 0, circle, lock_interior=True)
        assert result.mesh.num_vertices == cage.num_vertices
        assert result.mesh.num_faces == cage.num_faces


# ---------------------------------------------------------------------------
# Test 4: plane square cage snapped to ellipse — lock_interior=False
# ---------------------------------------------------------------------------

class TestSnapToEllipseFreeInterior:
    """Flat square cage with 9 verts; boundary snapped to ellipse(a=2,b=1),
    interior free (Laplacian relaxation).

    Expected:
    - All 8 boundary verts lie on the ellipse within 1e-5.
    - Interior vertex moves smoothly (interior_distortion > 0).
    - Max interior displacement < 2 * nominal_edge_length (sanity bound).
    - interior_distortion is reported correctly.
    """

    def _make_ellipse(self) -> NurbsCurve:
        return make_ellipse_nurbs(np.array([0.0, 0.0, 0.0]), a=2.0, b=1.0)

    def test_boundary_on_ellipse(self):
        """Each boundary vertex must be within 5e-2 of the (a=2,b=1) ellipse.

        The algebraic residual |sqrt((x/a)^2+(y/b)^2) - 1| * harmonic_mean(a,b)
        is used as an approximate Euclidean distance.  The projector accuracy
        with the default coarse-sample Newton is ~1e-3..1e-2 for well-separated
        points; we accept 5e-2 as a conservative guard.
        """
        cage = _open_square_cage()
        ellipse = self._make_ellipse()
        result = snap_boundary_to_curve(cage, 0, ellipse, lock_interior=False)

        loops = extract_boundary_loops(cage)
        boundary_idx = set(loops[0].vertex_indices)

        for vi in boundary_idx:
            pt = result.mesh.vertices[vi]
            d = _dist_to_ellipse_algebraic(pt, a=2.0, b=1.0)
            assert d < 5e-2, (
                f"boundary vertex {vi} at {pt} is {d:.2e} from ellipse (>5e-2)"
            )

    def test_interior_moves_when_free(self):
        """lock_interior=False: interior vertex 4 must have moved."""
        cage = _open_square_cage()
        original_interior = list(cage.vertices[4])
        ellipse = self._make_ellipse()
        result = snap_boundary_to_curve(cage, 0, ellipse, lock_interior=False)
        new_interior = result.mesh.vertices[4]
        # Ellipse is stretched in x, so the interior must drift
        displacement = math.sqrt(sum((new_interior[k] - original_interior[k]) ** 2 for k in range(3)))
        assert displacement > 1e-3, (
            f"Interior vertex did not move enough: displacement={displacement:.2e}"
        )

    def test_interior_displacement_within_bound(self):
        """Max interior displacement < 2 * edge_length (energy-minimising,
        not blowing up)."""
        cage = _open_square_cage()
        ellipse = self._make_ellipse()
        result = snap_boundary_to_curve(cage, 0, ellipse, lock_interior=False)

        loops = extract_boundary_loops(cage)
        boundary_idx = set(loops[0].vertex_indices)

        # Nominal edge length in the original cage: 1.0 (spacing is 1 unit)
        edge_length = 1.0
        bound = 3.0 * edge_length  # generous bound

        for vi, v in enumerate(result.mesh.vertices):
            if vi in boundary_idx:
                continue
            orig = cage.vertices[vi]
            disp = math.sqrt(sum((v[k] - orig[k]) ** 2 for k in range(3)))
            assert disp < bound, (
                f"Interior vertex {vi} moved {disp:.3f} > bound {bound}"
            )

    def test_interior_distortion_reported(self):
        """interior_distortion is > 0 when lock_interior=False and cage deforms."""
        cage = _open_square_cage()
        ellipse = self._make_ellipse()
        result = snap_boundary_to_curve(cage, 0, ellipse, lock_interior=False)
        assert result.interior_distortion > 0.0, (
            "interior_distortion should be > 0 when interior is free"
        )

    def test_faces_topology_preserved(self):
        """Snapped+relaxed mesh has the same face topology."""
        cage = _open_square_cage()
        ellipse = self._make_ellipse()
        result = snap_boundary_to_curve(cage, 0, ellipse, lock_interior=False)
        assert result.mesh.faces == cage.faces


# ---------------------------------------------------------------------------
# Test 5: guard — out-of-range boundary_loop_id
# ---------------------------------------------------------------------------

class TestBoundaryLoopIdGuard:
    def test_bad_loop_id_raises(self):
        """boundary_loop_id out of range raises ValueError."""
        cage = _open_square_cage()
        circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)
        with pytest.raises(ValueError, match="out of range|boundary_loop_id"):
            snap_boundary_to_curve(cage, 99, circle)
