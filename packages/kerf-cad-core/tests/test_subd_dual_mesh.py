"""test_subd_dual_mesh.py
========================
Tests for subd/dual_mesh.py — SUBD-CAGE-DUAL-MESH.

Coverage (13 tests across 6 classes):

  TestCubeDual (4 tests):
    1.  Cube cage (8 verts, 6 quads): dual has exactly 6 dual vertices (= face
        centroids).
    2.  Cube: dual has exactly 8 dual faces (one per primal vertex).
    3.  Cube: each dual face has exactly 3 corners (valence-3 vertices → triangular
        dual face, yielding the combinatorial octahedron).
    4.  Cube: no irregular dual faces on a closed manifold.

  TestCubeDualVertexPositions (2 tests):
    5.  Cube: each dual vertex (face centroid) lies at the centroid of its
        primal face (oracle check for the bottom face centroid = (0.5, 0.5, 0)).
    6.  Cube: dual vertex positions are all distinct (no duplicates).

  TestPlaneDual (3 tests):
    7.  Plane 2×2 grid (9 verts, 4 quads): dual has 4 dual vertices.
    8.  Plane: dual has 9 dual faces.
    9.  Plane: interior vertex (valence 4) produces 4-corner dual face; boundary
        vertices are marked as irregular.

  TestCylinderDual (2 tests):
    10. Cylinder (nu=6, nv=2: 12 verts, 6 quads): dual has 6 dual vertices.
    11. Cylinder: dual has 12 dual faces (one per primal vertex); boundary
        vertices (top/bottom rings) count as irregular.

  TestResultStructure (1 test):
    12. Return type is DualMeshResult with all required fields.

  TestHonestCaveat (1 test):
    13. honest_caveat is a non-empty string mentioning 'boundary'.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.subd.dual_mesh import (
    DualMeshResult,
    compute_dual_mesh,
)


# ---------------------------------------------------------------------------
# Helpers to build test cages
# ---------------------------------------------------------------------------

def _unit_cube() -> SubDMesh:
    """Unit cube: 8 vertices, 6 quad faces.

    Faces listed in consistent CCW winding when viewed from outside.
    """
    verts = [
        [0.0, 0.0, 0.0],  # 0 bottom-front-left
        [1.0, 0.0, 0.0],  # 1 bottom-front-right
        [1.0, 1.0, 0.0],  # 2 bottom-back-right
        [0.0, 1.0, 0.0],  # 3 bottom-back-left
        [0.0, 0.0, 1.0],  # 4 top-front-left
        [1.0, 0.0, 1.0],  # 5 top-front-right
        [1.0, 1.0, 1.0],  # 6 top-back-right
        [0.0, 1.0, 1.0],  # 7 top-back-left
    ]
    faces = [
        [0, 1, 2, 3],  # 0: bottom (z=0)
        [4, 5, 6, 7],  # 1: top    (z=1)
        [0, 1, 5, 4],  # 2: front  (y=0)
        [1, 2, 6, 5],  # 3: right  (x=1)
        [2, 3, 7, 6],  # 4: back   (y=1)
        [3, 0, 4, 7],  # 5: left   (x=0)
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _plane_2x2() -> SubDMesh:
    """2×2 plane grid: 9 vertices, 4 quad faces (all in the z=0 plane).

    Vertex layout:
      0--1--2
      |  |  |
      3--4--5
      |  |  |
      6--7--8

    Faces:
      [0,1,4,3], [1,2,5,4], [3,4,7,6], [4,5,8,7]
    """
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [2.0, 0.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [1.0, 1.0, 0.0],  # 4  (center)
        [2.0, 1.0, 0.0],  # 5
        [0.0, 2.0, 0.0],  # 6
        [1.0, 2.0, 0.0],  # 7
        [2.0, 2.0, 0.0],  # 8
    ]
    faces = [
        [0, 1, 4, 3],  # 0: top-left quad
        [1, 2, 5, 4],  # 1: top-right quad
        [3, 4, 7, 6],  # 2: bottom-left quad
        [4, 5, 8, 7],  # 3: bottom-right quad
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _cylinder_6x2() -> SubDMesh:
    """Cylinder with 6 circumferential segments, 2 axial segments.

    12 vertices (two rings of 6), 6 quad faces (the barrel only, no caps).
    This is an OPEN mesh (top and bottom are boundary edges).
    """
    nu = 6  # circumferential
    nz = 2  # axial layers of vertices (1 layer of quads)
    verts: List[List[float]] = []
    for z_idx in range(nz):
        z = float(z_idx)
        for u_idx in range(nu):
            angle = 2.0 * math.pi * u_idx / nu
            verts.append([math.cos(angle), math.sin(angle), z])

    # Face: ring at z=0 → z=1
    faces: List[List[int]] = []
    for u_idx in range(nu):
        u0 = u_idx
        u1 = (u_idx + 1) % nu
        # bottom ring: 0..5; top ring: 6..11
        faces.append([u0, u1, u1 + nu, u0 + nu])

    return SubDMesh(vertices=verts, faces=faces)


def _torus_4x4() -> SubDMesh:
    """4×4 torus: 16 vertices, 16 quads; all vertices have valence 4.

    This is a closed orientable 2-manifold → no irregular dual faces expected.
    """
    nu, nv = 4, 4
    R, r = 2.0, 0.5
    verts: List[List[float]] = []
    for v_idx in range(nv):
        phi = 2.0 * math.pi * v_idx / nv
        for u_idx in range(nu):
            theta = 2.0 * math.pi * u_idx / nu
            x = (R + r * math.cos(phi)) * math.cos(theta)
            y = (R + r * math.cos(phi)) * math.sin(theta)
            z = r * math.sin(phi)
            verts.append([x, y, z])

    faces: List[List[int]] = []
    for v_idx in range(nv):
        for u_idx in range(nu):
            v00 = v_idx * nu + u_idx
            v10 = v_idx * nu + (u_idx + 1) % nu
            v01 = ((v_idx + 1) % nv) * nu + u_idx
            v11 = ((v_idx + 1) % nv) * nu + (u_idx + 1) % nu
            faces.append([v00, v10, v11, v01])

    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# TestCubeDual — topology oracle: cube → combinatorial octahedron dual
# ---------------------------------------------------------------------------

class TestCubeDual:
    """Cube cage (8 verts, 6 quads) dual mesh topology tests."""

    def test_cube_dual_vertex_count(self) -> None:
        """Dual must have exactly 6 dual vertices (one per primal face)."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert len(res.dual_vertices) == 6, (
            f"Expected 6 dual vertices, got {len(res.dual_vertices)}"
        )

    def test_cube_dual_face_count(self) -> None:
        """Dual must have exactly 8 dual faces (one per primal vertex)."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert len(res.dual_faces) == 8, (
            f"Expected 8 dual faces, got {len(res.dual_faces)}"
        )

    def test_cube_dual_face_valences_are_three(self) -> None:
        """Every dual face of the cube must be a triangle (3 corners).

        Each cube vertex has valence 3 (incident to 3 faces), so the dual
        face — the ring of neighboring face centroids — has 3 corners.
        """
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        for i, df in enumerate(res.dual_faces):
            assert len(df) == 3, (
                f"Dual face {i} has {len(df)} corners; expected 3 for valence-3 vertex."
            )

    def test_cube_no_irregular_dual_faces(self) -> None:
        """Closed manifold cube → zero irregular dual faces."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert res.num_irregular_dual_faces == 0, (
            f"Expected 0 irregular dual faces, got {res.num_irregular_dual_faces}"
        )


# ---------------------------------------------------------------------------
# TestCubeDualVertexPositions — geometry oracle
# ---------------------------------------------------------------------------

class TestCubeDualVertexPositions:
    """Verify dual vertex positions are correct face centroids."""

    def test_bottom_face_centroid(self) -> None:
        """Dual vertex for the bottom face (z=0 quad) must be at (0.5, 0.5, 0)."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        # Face 0 = [0,1,2,3] = bottom face.
        dv = res.dual_vertices[0]
        assert abs(dv[0] - 0.5) < 1e-9, f"x={dv[0]}, expected 0.5"
        assert abs(dv[1] - 0.5) < 1e-9, f"y={dv[1]}, expected 0.5"
        assert abs(dv[2] - 0.0) < 1e-9, f"z={dv[2]}, expected 0.0"

    def test_top_face_centroid(self) -> None:
        """Dual vertex for the top face (z=1 quad) must be at (0.5, 0.5, 1)."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        # Face 1 = [4,5,6,7] = top face.
        dv = res.dual_vertices[1]
        assert abs(dv[0] - 0.5) < 1e-9
        assert abs(dv[1] - 0.5) < 1e-9
        assert abs(dv[2] - 1.0) < 1e-9

    def test_dual_vertices_all_distinct(self) -> None:
        """All 6 dual vertices of the cube should be at distinct positions."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        seen: set = set()
        for dv in res.dual_vertices:
            key = (round(dv[0], 9), round(dv[1], 9), round(dv[2], 9))
            assert key not in seen, f"Duplicate dual vertex at {key}"
            seen.add(key)


# ---------------------------------------------------------------------------
# TestPlaneDual — open-boundary mesh tests
# ---------------------------------------------------------------------------

class TestPlaneDual:
    """2×2 plane grid dual mesh tests."""

    def test_plane_dual_vertex_count(self) -> None:
        """Plane 2×2 grid has 4 faces → dual has 4 dual vertices."""
        mesh = _plane_2x2()
        res = compute_dual_mesh(mesh)
        assert len(res.dual_vertices) == 4

    def test_plane_dual_face_count(self) -> None:
        """Plane 2×2 grid has 9 primal vertices → dual has 9 dual faces."""
        mesh = _plane_2x2()
        res = compute_dual_mesh(mesh)
        assert len(res.dual_faces) == 9

    def test_plane_center_vertex_has_4_corner_dual_face(self) -> None:
        """The center vertex (index 4) has valence 4 → dual face has 4 corners."""
        mesh = _plane_2x2()
        res = compute_dual_mesh(mesh)
        # Vertex 4 is incident to all 4 faces.
        center_dual_face = res.dual_faces[4]
        assert len(center_dual_face) == 4, (
            f"Center vertex dual face has {len(center_dual_face)} corners, expected 4"
        )

    def test_plane_center_dual_face_indices_valid(self) -> None:
        """All indices in the center vertex dual face must be valid dual-vertex indices."""
        mesh = _plane_2x2()
        res = compute_dual_mesh(mesh)
        nf = len(res.dual_vertices)
        for fi in res.dual_faces[4]:
            assert 0 <= fi < nf, f"Invalid dual vertex index {fi} (num dual verts={nf})"

    def test_plane_has_irregular_boundary_dual_faces(self) -> None:
        """Open-boundary plane mesh must report boundary vertices as irregular."""
        mesh = _plane_2x2()
        res = compute_dual_mesh(mesh)
        # Boundary vertices (all except vertex 4) = 8 boundary vertices.
        assert res.num_irregular_dual_faces > 0, (
            "Expected irregular dual faces for boundary mesh, got 0"
        )

    def test_plane_dual_vertex_positions_are_cell_centers(self) -> None:
        """Each dual vertex should lie at the centroid of its primal quad.

        For the plane 2×2 grid with unit spacing:
          Face 0 = [0,1,4,3] → centroid at (0.5, 0.5, 0).
          Face 3 = [4,5,8,7] → centroid at (1.5, 1.5, 0).
        """
        mesh = _plane_2x2()
        res = compute_dual_mesh(mesh)
        dv0 = res.dual_vertices[0]
        assert abs(dv0[0] - 0.5) < 1e-9
        assert abs(dv0[1] - 0.5) < 1e-9
        assert abs(dv0[2] - 0.0) < 1e-9

        dv3 = res.dual_vertices[3]
        assert abs(dv3[0] - 1.5) < 1e-9
        assert abs(dv3[1] - 1.5) < 1e-9
        assert abs(dv3[2] - 0.0) < 1e-9


# ---------------------------------------------------------------------------
# TestCylinderDual — open cylinder (boundary edges at top and bottom rings)
# ---------------------------------------------------------------------------

class TestCylinderDual:
    """Cylinder barrel (open mesh) dual mesh tests."""

    def test_cylinder_dual_vertex_count(self) -> None:
        """Cylinder nu=6 nv=2 has 6 faces → dual has 6 dual vertices."""
        mesh = _cylinder_6x2()
        res = compute_dual_mesh(mesh)
        assert len(res.dual_vertices) == 6

    def test_cylinder_dual_face_count(self) -> None:
        """Cylinder has 12 primal vertices → dual has 12 dual faces."""
        mesh = _cylinder_6x2()
        res = compute_dual_mesh(mesh)
        assert len(res.dual_faces) == 12

    def test_cylinder_has_irregular_boundary_dual_faces(self) -> None:
        """Open cylinder (top/bottom boundary rings) must have irregular dual faces."""
        mesh = _cylinder_6x2()
        res = compute_dual_mesh(mesh)
        assert res.num_irregular_dual_faces > 0, (
            "Expected irregular dual faces on open cylinder, got 0"
        )

    def test_cylinder_all_dual_face_indices_valid(self) -> None:
        """All dual face indices must be valid (in range [0, num_dual_verts))."""
        mesh = _cylinder_6x2()
        res = compute_dual_mesh(mesh)
        nf = len(res.dual_vertices)
        for i, df in enumerate(res.dual_faces):
            for fi in df:
                assert 0 <= fi < nf, (
                    f"Dual face {i}: index {fi} out of range [0, {nf})"
                )


# ---------------------------------------------------------------------------
# TestTorusDual — closed 4×4 torus, all regular valence-4 vertices
# ---------------------------------------------------------------------------

class TestTorusDual:
    """4×4 torus dual mesh tests — closed orientable 2-manifold."""

    def test_torus_dual_vertex_count(self) -> None:
        """4×4 torus has 16 faces → dual has 16 dual vertices."""
        mesh = _torus_4x4()
        res = compute_dual_mesh(mesh)
        assert len(res.dual_vertices) == 16

    def test_torus_dual_face_count(self) -> None:
        """4×4 torus has 16 primal vertices → dual has 16 dual faces."""
        mesh = _torus_4x4()
        res = compute_dual_mesh(mesh)
        assert len(res.dual_faces) == 16

    def test_torus_no_irregular_dual_faces(self) -> None:
        """Closed orientable 2-manifold torus → zero irregular dual faces."""
        mesh = _torus_4x4()
        res = compute_dual_mesh(mesh)
        assert res.num_irregular_dual_faces == 0

    def test_torus_all_dual_faces_valence_4(self) -> None:
        """All torus vertices have valence 4 → all dual faces have 4 corners."""
        mesh = _torus_4x4()
        res = compute_dual_mesh(mesh)
        for i, df in enumerate(res.dual_faces):
            assert len(df) == 4, (
                f"Torus dual face {i} has {len(df)} corners; expected 4"
            )


# ---------------------------------------------------------------------------
# TestResultStructure — DualMeshResult dataclass fields
# ---------------------------------------------------------------------------

class TestResultStructure:
    """Verify DualMeshResult has all required fields with correct types."""

    def test_result_is_dual_mesh_result(self) -> None:
        """Return type must be DualMeshResult."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert isinstance(res, DualMeshResult)

    def test_result_has_dual_vertices_field(self) -> None:
        """DualMeshResult must have dual_vertices field as a list."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert hasattr(res, "dual_vertices")
        assert isinstance(res.dual_vertices, list)

    def test_result_has_dual_faces_field(self) -> None:
        """DualMeshResult must have dual_faces field as a list."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert hasattr(res, "dual_faces")
        assert isinstance(res.dual_faces, list)

    def test_result_has_num_irregular_dual_faces(self) -> None:
        """DualMeshResult must have num_irregular_dual_faces as an int."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert hasattr(res, "num_irregular_dual_faces")
        assert isinstance(res.num_irregular_dual_faces, int)

    def test_result_has_honest_caveat(self) -> None:
        """DualMeshResult must have honest_caveat as a non-empty string."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert hasattr(res, "honest_caveat")
        assert isinstance(res.honest_caveat, str)
        assert len(res.honest_caveat) > 0


# ---------------------------------------------------------------------------
# TestHonestCaveat — verify caveat content
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    """Verify the honest_caveat string contains expected content."""

    def test_honest_caveat_mentions_boundary(self) -> None:
        """honest_caveat must mention 'boundary' (the key limitation)."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert "boundary" in res.honest_caveat.lower(), (
            f"honest_caveat does not mention 'boundary': {res.honest_caveat!r}"
        )

    def test_honest_caveat_mentions_angular_sort(self) -> None:
        """honest_caveat must mention the angular sort ordering method."""
        mesh = _unit_cube()
        res = compute_dual_mesh(mesh)
        assert "angular" in res.honest_caveat.lower() or "atan2" in res.honest_caveat.lower(), (
            "honest_caveat does not mention angular/atan2 sort"
        )
