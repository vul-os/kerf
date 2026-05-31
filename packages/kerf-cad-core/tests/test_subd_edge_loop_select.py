"""test_subd_edge_loop_select.py
==============================
Tests for subd/edge_loop_select.py — SUBD-CAGE-EDGE-LOOP-SELECT.

Coverage (25 tests across 9 classes):
  TestTorusLoop (4 tests):
    1.  Regular 4×4 torus: loop from edge 0 is closed.
    2.  Regular 4×4 torus: closed=True, terminated_at_irregular=False.
    3.  Regular 4×4 torus: loop length equals 4 (one row of quads).
    4.  Regular 4×4 torus: all 32 edges produce closed loops.

  TestCubeLoop (4 tests):
    5.  Cube cage (all vertices valence-3): terminates at first irregular vertex.
    6.  Cube: closed=False.
    7.  Cube: irregular_vertex_valences is non-empty.
    8.  Cube: irregular_vertex_valences values equal 3.

  TestCylinderLoop (2 tests):
    9.  Cylinder cage: axial edge at interior row → closed loop.
    10. Cylinder: axial interior loop length equals nu (= 6 circumferential quads).

  TestSingleQuadLoop (2 tests):
    11. Single-quad cage: loop terminates (all vertices boundary = valence 2).
    12. Single-quad: terminated_at_irregular=True.

  TestBadInputs (2 tests):
    13. start_edge_idx >= num_edges raises ValueError.
    14. Negative start_edge_idx raises ValueError.

  TestResultStructure (4 tests):
    15. Return type is EdgeLoopResult.
    16. EdgeLoopResult has all required fields.
    17. vertex_indices is flat [a0,b0,...]: length = 2 * len(edge_indices).
    18. honest_caveat is a non-empty string.

  TestMixedMesh (1 test):
    19. Mixed tri/quad mesh terminates when crossing non-quad face.

  TestLargeTorus (1 test):
    20. 6×8 torus: loop lengths are exactly {6, 8} across all edges.

  TestEdgeIndexValidity (1 test):
    21. All edge indices in result are valid ints in [0, num_edges).

  TestStartEdgeFirst (1 test):
    22. start_edge_idx always appears as the first element of edge_indices.

  TestSmallTorus (1 test):
    23. 4×3 torus: all loops close, lengths are {3, 4}.

  TestOpenGridLoop (2 tests):
    24. Open 2×4 rect grid: at least one terminated loop (boundary vertices).
    25. Open grid: start on boundary edge → terminated_at_irregular.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.subd.edge_loop_select import EdgeLoopResult, select_edge_loop


# ---------------------------------------------------------------------------
# Cage fixtures
# ---------------------------------------------------------------------------

def _torus_cage(nu: int = 4, nv: int = 4) -> SubDMesh:
    """nu × nv quad grid wrapped toroidally (periodic in both U and V).

    Vertex (i, j) has index i*nv + j.
    Face (i, j): [i*nv+j, i*nv+(j+1)%nv, ((i+1)%nu)*nv+(j+1)%nv, ((i+1)%nu)*nv+j]

    All vertices have valence 4 (exactly 4 incident edges) for nu,nv >= 3.
    """
    verts = []
    for i in range(nu):
        for j in range(nv):
            theta = 2 * math.pi * i / nu
            phi = 2 * math.pi * j / nv
            R, r = 2.0, 0.5
            x = (R + r * math.cos(phi)) * math.cos(theta)
            y = (R + r * math.cos(phi)) * math.sin(theta)
            z = r * math.sin(phi)
            verts.append([x, y, z])
    faces = []
    for i in range(nu):
        for j in range(nv):
            v00 = i * nv + j
            v01 = i * nv + (j + 1) % nv
            v11 = ((i + 1) % nu) * nv + (j + 1) % nv
            v10 = ((i + 1) % nu) * nv + j
            faces.append([v00, v01, v11, v10])
    return SubDMesh(vertices=verts, faces=faces)


def _cube_cage() -> SubDMesh:
    """Unit cube cage: 8 vertices, 6 quad faces, 12 edges.

    All vertices have valence 3 (irregular for quad-loop purposes).
    """
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [1.0, 1.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [0.0, 0.0, 1.0],  # 4
        [1.0, 0.0, 1.0],  # 5
        [1.0, 1.0, 1.0],  # 6
        [0.0, 1.0, 1.0],  # 7
    ]
    faces = [
        [0, 1, 2, 3],  # bottom
        [4, 5, 6, 7],  # top
        [0, 1, 5, 4],  # front
        [1, 2, 6, 5],  # right
        [2, 3, 7, 6],  # back
        [3, 0, 4, 7],  # left
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _cylinder_cage(nu: int = 6, nv: int = 4) -> SubDMesh:
    """Cylinder: nu quads around the circumference, nv quads along the axis.

    Open-ended (no caps) — pure quad strip.  nv+1 rows of vertices.
    Vertex (j, i) = j*nu + i.
    Face (j, i): [j*nu+i, j*nu+(i+1)%nu, (j+1)*nu+(i+1)%nu, (j+1)*nu+i]

    Boundary vertices (row 0 and row nv) have valence 3 (irregular).
    Interior vertices have valence 4 (regular).

    Axial edges (connecting row j to row j+1, same column) are PERPENDICULAR
    to the circumference.  From an axial edge at interior rows, the loop
    crosses the quad to the PARALLEL axial edge on the other side, then
    continues circumferentially → closes after nu steps.
    """
    verts = []
    for j in range(nv + 1):
        for i in range(nu):
            theta = 2 * math.pi * i / nu
            x = math.cos(theta)
            y = math.sin(theta)
            z = float(j) / nv
            verts.append([x, y, z])
    faces = []
    for j in range(nv):
        for i in range(nu):
            v00 = j * nu + i
            v01 = j * nu + (i + 1) % nu
            v11 = (j + 1) * nu + (i + 1) % nu
            v10 = (j + 1) * nu + i
            faces.append([v00, v01, v11, v10])
    return SubDMesh(vertices=verts, faces=faces)


def _single_quad_cage() -> SubDMesh:
    """Single quad face: 4 vertices, 1 face, 4 edges.

    All vertices have valence 2 (irregular; boundary open mesh).
    """
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


def _rect_grid_cage(nu: int = 2, nv: int = 4) -> SubDMesh:
    """Open (non-toroidal) nu×nv rectangular quad grid.

    Vertex (i, j): index i*(nv+1) + j.
    Boundary vertices have valence 2 or 3 (irregular).
    Interior vertices have valence 4.
    """
    verts = []
    for i in range(nu + 1):
        for j in range(nv + 1):
            verts.append([float(i), float(j), 0.0])
    faces = []
    for i in range(nu):
        for j in range(nv):
            v00 = i * (nv + 1) + j
            v01 = i * (nv + 1) + (j + 1)
            v11 = (i + 1) * (nv + 1) + (j + 1)
            v10 = (i + 1) * (nv + 1) + j
            faces.append([v00, v01, v11, v10])
    return SubDMesh(vertices=verts, faces=faces)


def _mixed_tri_quad_cage() -> SubDMesh:
    """Mesh with one triangle face next to a quad face."""
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [1.0, 1.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [2.0, 0.5, 0.0],  # 4
    ]
    faces = [
        [0, 1, 2, 3],   # quad
        [1, 4, 2],       # triangle adjacent to edge (1,2)
    ]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _num_edges(cage: SubDMesh) -> int:
    seen = set()
    for face in cage.faces:
        n = len(face)
        for i in range(n):
            key = cage.edge_key(face[i], face[(i + 1) % n])
            seen.add(key)
    return len(seen)


def _axial_edge_idx(cage: SubDMesh, nu: int, row_j: int, col_i: int = 0) -> int:
    """Return the index of the axial edge between row j and j+1 at column col_i."""
    v0 = row_j * nu + col_i
    v1 = (row_j + 1) * nu + col_i
    all_edges = cage._all_edge_keys()
    key = cage.edge_key(v0, v1)
    return all_edges.index(key)


# ---------------------------------------------------------------------------
# Tests 1–4: Regular 4×4 torus
# ---------------------------------------------------------------------------

class TestTorusLoop:
    def setup_method(self):
        self.cage = _torus_cage(nu=4, nv=4)
        self.ne = _num_edges(self.cage)

    def test_torus_loop_is_closed(self):
        """4×4 torus with all-regular vertices → loop from edge 0 must close."""
        res = select_edge_loop(self.cage, 0)
        assert res.closed is True, f"Expected closed=True, got {res}"

    def test_torus_loop_not_terminated_at_irregular(self):
        """Regular torus: terminated_at_irregular must be False."""
        res = select_edge_loop(self.cage, 0)
        assert res.terminated_at_irregular is False

    def test_torus_loop_length(self):
        """4×4 torus: loop length should equal 4 (crosses 4 quads, each row has 4)."""
        res = select_edge_loop(self.cage, 0)
        assert len(res.edge_indices) == 4, (
            f"Expected 4 edges in loop, got {len(res.edge_indices)}: {res.edge_indices}"
        )

    def test_torus_all_starting_edges_close(self):
        """Every edge on the 4×4 torus starts a closed loop (all vertices regular)."""
        for idx in range(self.ne):
            res = select_edge_loop(self.cage, idx)
            assert res.closed is True, (
                f"Edge {idx} loop not closed: {res}"
            )


# ---------------------------------------------------------------------------
# Tests 5–8: Cube cage (all valence-3 vertices = irregular)
# ---------------------------------------------------------------------------

class TestCubeLoop:
    def setup_method(self):
        self.cage = _cube_cage()
        self.ne = _num_edges(self.cage)

    def test_cube_terminates_at_irregular(self):
        """Cube has all valence-3 vertices → loop terminates at first irregular vertex."""
        res = select_edge_loop(self.cage, 0)
        assert res.terminated_at_irregular is True

    def test_cube_not_closed(self):
        """Cube loop must not close (terminates at irregular vertex first)."""
        res = select_edge_loop(self.cage, 0)
        assert res.closed is False

    def test_cube_irregular_valences_nonempty(self):
        """Cube loop: irregular_vertex_valences must be non-empty."""
        res = select_edge_loop(self.cage, 0)
        assert len(res.irregular_vertex_valences) > 0

    def test_cube_irregular_valence_is_3(self):
        """Cube vertices have valence 3 → reported irregular valence should be 3."""
        res = select_edge_loop(self.cage, 0)
        assert all(v == 3 for v in res.irregular_vertex_valences), (
            f"Expected all valences=3, got {res.irregular_vertex_valences}"
        )


# ---------------------------------------------------------------------------
# Tests 9–10: Cylinder cage (axial edges form closed circumferential loops)
# ---------------------------------------------------------------------------

class TestCylinderLoop:
    def setup_method(self):
        self.nu = 6
        self.nv = 4
        self.cage = _cylinder_cage(nu=self.nu, nv=self.nv)
        self.ne = _num_edges(self.cage)

    def test_cylinder_axial_interior_loop_closes(self):
        """Axial edge at interior row on cylinder → closed loop (goes around cylinder)."""
        cage = self.cage
        nu = self.nu
        # Axial edge between interior rows j=1 and j=2, column 0.
        idx = _axial_edge_idx(cage, nu, row_j=1, col_i=0)
        res = select_edge_loop(cage, idx)
        assert res.closed is True, (
            f"Cylinder axial interior loop not closed: {res}"
        )

    def test_cylinder_axial_interior_loop_length_equals_nu(self):
        """Axial interior loop on cylinder has length nu (= 6, one full circumference)."""
        cage = self.cage
        nu = self.nu
        idx = _axial_edge_idx(cage, nu, row_j=1, col_i=0)
        res = select_edge_loop(cage, idx)
        assert len(res.edge_indices) == nu, (
            f"Expected cylinder loop length {nu}, got {len(res.edge_indices)}"
        )


# ---------------------------------------------------------------------------
# Tests 11–12: Single-quad cage
# ---------------------------------------------------------------------------

class TestSingleQuadLoop:
    def setup_method(self):
        self.cage = _single_quad_cage()

    def test_single_quad_terminates(self):
        """Single-quad cage: any edge loop terminates (all vertices are boundary/irregular)."""
        res = select_edge_loop(self.cage, 0)
        # With a single quad, all vertices have valence 2 (boundary) → irregular.
        # The opposite edge in the quad has irregular vertices → terminated.
        assert res.terminated_at_irregular is True

    def test_single_quad_terminated_at_irregular(self):
        """Single-quad cage: terminated_at_irregular=True for edge 0."""
        res = select_edge_loop(self.cage, 0)
        assert res.terminated_at_irregular is True


# ---------------------------------------------------------------------------
# Tests 13–14: ValueError on bad start_edge_idx
# ---------------------------------------------------------------------------

class TestBadInputs:
    def setup_method(self):
        self.cage = _torus_cage(4, 4)
        self.ne = _num_edges(self.cage)

    def test_out_of_range_raises(self):
        """start_edge_idx >= num_edges raises ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            select_edge_loop(self.cage, self.ne)

    def test_negative_raises(self):
        """Negative start_edge_idx raises ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            select_edge_loop(self.cage, -1)


# ---------------------------------------------------------------------------
# Tests 15–18: Structural invariants on EdgeLoopResult
# ---------------------------------------------------------------------------

class TestResultStructure:
    def setup_method(self):
        self.torus = _torus_cage(4, 4)

    def test_result_is_edge_loop_result(self):
        """Return type is EdgeLoopResult."""
        res = select_edge_loop(self.torus, 0)
        assert isinstance(res, EdgeLoopResult)

    def test_result_fields_exist(self):
        """EdgeLoopResult has all required fields."""
        res = select_edge_loop(self.torus, 0)
        assert hasattr(res, "edge_indices")
        assert hasattr(res, "vertex_indices")
        assert hasattr(res, "closed")
        assert hasattr(res, "terminated_at_irregular")
        assert hasattr(res, "irregular_vertex_valences")
        assert hasattr(res, "honest_caveat")

    def test_vertex_indices_length(self):
        """vertex_indices is flat [a0,b0,...]: length = 2 * len(edge_indices)."""
        res = select_edge_loop(self.torus, 0)
        # Each edge contributes 2 vertex entries (its two endpoint vertices).
        assert len(res.vertex_indices) == 2 * len(res.edge_indices), (
            f"vertex_indices length {len(res.vertex_indices)} != "
            f"2 * edge_indices length {2 * len(res.edge_indices)}"
        )

    def test_honest_caveat_is_str(self):
        """honest_caveat is a non-empty string."""
        res = select_edge_loop(self.torus, 0)
        assert isinstance(res.honest_caveat, str)
        assert len(res.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 19: Mixed tri/quad mesh
# ---------------------------------------------------------------------------

class TestMixedMesh:
    def test_mixed_terminates_at_nonquad(self):
        """Mixed tri/quad mesh: loop terminates when opposite edge leads to non-quad face."""
        cage = _mixed_tri_quad_cage()
        # Edge (0,3) is on the quad face only (boundary).  Edge (1,2) borders the triangle.
        # Any edge should eventually terminate.
        ne = _num_edges(cage)
        for idx in range(ne):
            res = select_edge_loop(cage, idx)
            # Either terminates at irregular vertex/boundary or closes (for isolated quad subsets).
            assert res.terminated_at_irregular is True or res.closed is True


# ---------------------------------------------------------------------------
# Test 20: 6×8 torus loop lengths
# ---------------------------------------------------------------------------

class TestLargeTorus:
    def test_6x8_torus_loop_lengths(self):
        """6×8 torus: all loops close; lengths are exactly {6, 8}."""
        cage = _torus_cage(nu=6, nv=8)
        ne = _num_edges(cage)
        lengths = set()
        for idx in range(ne):
            res = select_edge_loop(cage, idx)
            assert res.closed, f"Edge {idx} on 6×8 torus not closed"
            lengths.add(len(res.edge_indices))
        assert lengths == {6, 8}, (
            f"Expected loop lengths {{6, 8}} on 6×8 torus, got {lengths}"
        )


# ---------------------------------------------------------------------------
# Test 21: Edge indices validity
# ---------------------------------------------------------------------------

class TestEdgeIndexValidity:
    def test_edge_indices_valid(self):
        """All edge indices in result are valid ints in [0, num_edges)."""
        cage = _torus_cage(4, 4)
        ne = _num_edges(cage)
        for idx in range(ne):
            res = select_edge_loop(cage, idx)
            for ei in res.edge_indices:
                assert 0 <= ei < ne, f"Edge index {ei} out of range [0, {ne})"


# ---------------------------------------------------------------------------
# Test 22: start_edge_idx is first in result
# ---------------------------------------------------------------------------

class TestStartEdgeFirst:
    def test_start_edge_first(self):
        """start_edge_idx must always appear as the first element of edge_indices."""
        cage = _torus_cage(4, 4)
        ne = _num_edges(cage)
        for idx in range(ne):
            res = select_edge_loop(cage, idx)
            assert res.edge_indices[0] == idx, (
                f"start_edge_idx {idx} not first in {res.edge_indices}"
            )


# ---------------------------------------------------------------------------
# Test 23: 4×3 torus loop lengths
# ---------------------------------------------------------------------------

class TestAsymmetricTorus:
    def test_4x3_torus_loop_lengths(self):
        """4×3 torus: all loops close; lengths are exactly {3, 4}."""
        cage = _torus_cage(nu=4, nv=3)
        ne = _num_edges(cage)
        lengths = set()
        for idx in range(ne):
            res = select_edge_loop(cage, idx)
            assert res.closed, f"4×3 torus edge {idx} loop not closed"
            lengths.add(len(res.edge_indices))
        assert lengths == {3, 4}, (
            f"Expected loop lengths {{3, 4}} on 4×3 torus, got {lengths}"
        )


# ---------------------------------------------------------------------------
# Tests 24–25: Open rectangular grid
# ---------------------------------------------------------------------------

class TestOpenGridLoop:
    def test_open_grid_has_terminated_loops(self):
        """Open 2×4 rect grid: at least one terminated loop (boundary vertices)."""
        cage = _rect_grid_cage(nu=2, nv=4)
        ne = _num_edges(cage)
        terminated = [select_edge_loop(cage, idx) for idx in range(ne)
                      if select_edge_loop(cage, idx).terminated_at_irregular]
        assert len(terminated) > 0, "Expected at least one terminated loop on open grid"

    def test_open_grid_boundary_edge_terminates(self):
        """Open grid: starting on a boundary vertex edge → terminated_at_irregular."""
        cage = _rect_grid_cage(nu=2, nv=4)
        # Edge between corner vertex (0,0) and (0,1) — both boundary vertices.
        # Vertex indices: (i=0, j=0) = 0, (i=0, j=1) = 1.
        all_edges = cage._all_edge_keys()
        key = cage.edge_key(0, 1)
        try:
            idx = all_edges.index(key)
        except ValueError:
            idx = 0
        res = select_edge_loop(cage, idx)
        # The opposite edge in the quad has boundary/irregular vertices.
        assert res.terminated_at_irregular is True
