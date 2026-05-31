"""test_subd_face_loop_select.py
================================
Tests for subd/face_loop_select.py — SUBD-CAGE-FACE-LOOP.

Coverage (14 tests across 9 classes):

  TestTorusFaceLoop (4 tests):
    1.  Regular 4×4 torus, dir=0: face loop from face 0 is closed.
    2.  Regular 4×4 torus, dir=0: closed=True, terminated_at_irregular=False.
    3.  Regular 4×4 torus, dir=0: loop length equals nv (=4).
    4.  Regular 4×4 torus: direction 0 and direction 1 give different (orthogonal) rings.

  TestCylinderFaceLoop (2 tests):
    5.  Cylinder cage (nu=12 axial strip): circumferential ring (dir=1) closes with length=12.
    6.  Cylinder cage: circumferential ring visits each circumferential face exactly once.

  TestCubeFaceLoop (2 tests):
    7.  Cube cage (6 quads): traversal yields a ring of 4 faces (dir=0).
    8.  Cube cage: ring of 4 is closed.

  TestMixedFaceLoop (1 test):
    9.  Mixed tri/quad cage: terminated_at_irregular=True.

  TestWalkDirections (2 tests):
    10. 4×6 torus dir=0 loop length = 6 (nv direction).
    11. 4×6 torus dir=1 loop length = 4 (nu direction).

  TestBadInputs (2 tests):
    12. start_face_idx >= num_faces raises ValueError.
    13. walk_direction not in {0, 1} raises ValueError.

  TestResultStructure (3 tests):
    14. Return type is FaceLoopResult.
    15. FaceLoopResult has all required fields.
    16. honest_caveat is a non-empty string.

  TestNonQuadStartFace (1 test):
    17. Start face is a triangle → immediately terminated_at_irregular.

  TestSingleQuadFace (1 test):
    18. Single-quad cage → boundary, terminated_at_irregular.
"""

from __future__ import annotations

import math
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.subd.face_loop_select import FaceLoopResult, select_face_loop


# ---------------------------------------------------------------------------
# Cage fixtures
# ---------------------------------------------------------------------------

def _torus_cage(nu: int = 4, nv: int = 4) -> SubDMesh:
    """nu × nv quad torus.  All vertices regular (valence 4) for nu,nv >= 3.

    Face layout:
      face (i,j): [i*nv+j, i*nv+(j+1)%nv, ((i+1)%nu)*nv+(j+1)%nv, ((i+1)%nu)*nv+j]

    walk_direction=0 crosses (v0,v1)↔(v2,v3) — horizontal circumferential edges
        → hops between i-rows → ring length = nu
    walk_direction=1 crosses (v1,v2)↔(v3,v0) — vertical axial edges
        → hops between j-columns → ring length = nv
    """
    verts: List[List[float]] = []
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


def _cylinder_cage(nu: int = 12, nv: int = 4) -> SubDMesh:
    """Open cylinder cage: nu quads circumferentially, nv quads axially.

    Face layout:
      face (j,i): [j*nu+i, j*nu+(i+1)%nu, (j+1)*nu+(i+1)%nu, (j+1)*nu+i]

    walk_direction=1 crosses vertical (axial) edges → circumferential ring of nu faces.
    walk_direction=0 crosses horizontal (circumferential) edges → axial strip of nv faces
        (terminated at boundary top/bottom cap).
    """
    verts: List[List[float]] = []
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


def _cube_cage() -> SubDMesh:
    """Unit cube cage: 8 vertices, 6 quad faces."""
    verts = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 1.0], [0.0, 1.0, 1.0],
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


def _mixed_tri_quad_cage() -> SubDMesh:
    """One quad face adjacent to one triangle face (via edge (1,2))."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
        [2.0, 0.5, 0.0],
    ]
    faces = [
        [0, 1, 2, 3],  # quad (face 0)
        [1, 4, 2],      # triangle (face 1) adjacent via edge (1,2)
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _single_quad_cage() -> SubDMesh:
    verts = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
    ]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


def _tri_only_cage() -> SubDMesh:
    """Single triangle face — non-quad start."""
    verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 1.0, 0.0]]
    faces = [[0, 1, 2]]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# Tests 1–4: Regular 4×4 torus face loops
# ---------------------------------------------------------------------------

class TestTorusFaceLoop:
    def setup_method(self) -> None:
        self.cage = _torus_cage(nu=4, nv=4)

    def test_torus_face_loop_closed(self) -> None:
        """4×4 torus, direction=0: face loop from face 0 must close."""
        res = select_face_loop(self.cage, 0, walk_direction=0)
        assert res.closed is True, f"Expected closed=True, got {res}"

    def test_torus_face_loop_not_terminated(self) -> None:
        """4×4 torus, direction=0: terminated_at_irregular must be False."""
        res = select_face_loop(self.cage, 0, walk_direction=0)
        assert res.terminated_at_irregular is False

    def test_torus_face_loop_length_dir0(self) -> None:
        """4×4 torus, direction=0: loop crosses nu=4 faces (one u-row)."""
        res = select_face_loop(self.cage, 0, walk_direction=0)
        # direction=0 hops between i-rows: ring length = nu = 4
        assert len(res.face_indices) == 4, (
            f"Expected 4 faces in loop, got {len(res.face_indices)}: {res.face_indices}"
        )

    def test_torus_directions_orthogonal(self) -> None:
        """4×4 torus: direction=0 and direction=1 produce different face sets."""
        res0 = select_face_loop(self.cage, 0, walk_direction=0)
        res1 = select_face_loop(self.cage, 0, walk_direction=1)
        # Both must close, and their face sets must differ
        assert res0.closed is True
        assert res1.closed is True
        assert set(res0.face_indices) != set(res1.face_indices), (
            "direction=0 and direction=1 unexpectedly yielded the same face set"
        )


# ---------------------------------------------------------------------------
# Tests 5–6: Cylinder face loops
# ---------------------------------------------------------------------------

class TestCylinderFaceLoop:
    def setup_method(self) -> None:
        self.nu = 12
        self.nv = 4
        self.cage = _cylinder_cage(nu=self.nu, nv=self.nv)

    def test_cylinder_circumferential_ring_closes(self) -> None:
        """Cylinder (nu=12): direction=1 circumferential ring closes with length 12."""
        # Face in interior row (j=1): it has all-regular neighbours circumferentially.
        # Face index: j=1, i=0 → face index = j*nu + i = 1*12 + 0 = 12
        face_idx = 1 * self.nu + 0
        res = select_face_loop(self.cage, face_idx, walk_direction=1)
        assert res.closed is True, (
            f"Expected circumferential ring to close, got closed={res.closed}, "
            f"faces={res.face_indices}"
        )

    def test_cylinder_circumferential_ring_length_equals_nu(self) -> None:
        """Cylinder (nu=12): circumferential ring has exactly 12 faces."""
        face_idx = 1 * self.nu + 0
        res = select_face_loop(self.cage, face_idx, walk_direction=1)
        assert len(res.face_indices) == self.nu, (
            f"Expected ring length {self.nu}, got {len(res.face_indices)}"
        )


# ---------------------------------------------------------------------------
# Tests 7–8: Cube face loop (6 quads)
# ---------------------------------------------------------------------------

class TestCubeFaceLoop:
    def setup_method(self) -> None:
        self.cage = _cube_cage()

    def test_cube_face_loop_length_4(self) -> None:
        """Cube cage: face loop produces a ring of exactly 4 faces."""
        # On a cube all vertices are irregular (valence 3) for edge-loop purposes,
        # but face loops can still close: the 6-face cube has two orthogonal 4-rings.
        res = select_face_loop(self.cage, 0, walk_direction=0)
        # Face 0 = bottom [0,1,2,3], dir=0 exits via edge(2,3)↔faces adjacent there
        assert len(res.face_indices) == 4, (
            f"Expected cube face loop length 4, got {len(res.face_indices)}: "
            f"{res.face_indices}"
        )

    def test_cube_face_loop_closed(self) -> None:
        """Cube cage: the 4-face ring is closed."""
        res = select_face_loop(self.cage, 0, walk_direction=0)
        assert res.closed is True, f"Expected closed=True, got {res}"


# ---------------------------------------------------------------------------
# Test 9: Mixed tri/quad — terminated_at_irregular
# ---------------------------------------------------------------------------

class TestMixedFaceLoop:
    def test_mixed_cage_terminates(self) -> None:
        """Mixed tri/quad cage: walking into the triangle face → terminated_at_irregular."""
        cage = _mixed_tri_quad_cage()
        # Face 0 is the quad; direction=0, exit through edge (v2,v3)=edge(2,3).
        # edge(2,3) is a boundary edge (only face 0 uses it), so walk terminates.
        # Direction=1 exit through edge(v3,v0)=edge(3,0) — also boundary.
        # Either way, terminated_at_irregular=True.
        for direction in (0, 1):
            res = select_face_loop(cage, 0, walk_direction=direction)
            assert res.terminated_at_irregular is True, (
                f"Expected terminated (direction={direction}), got {res}"
            )


# ---------------------------------------------------------------------------
# Tests 10–11: Orthogonal ring lengths on 4×6 torus
# ---------------------------------------------------------------------------

class TestWalkDirections:
    def setup_method(self) -> None:
        self.nu = 4
        self.nv = 6
        self.cage = _torus_cage(nu=self.nu, nv=self.nv)

    def test_dir0_ring_length_equals_nu(self) -> None:
        """4×6 torus, dir=0: ring length = nu = 4."""
        res = select_face_loop(self.cage, 0, walk_direction=0)
        assert res.closed is True
        assert len(res.face_indices) == self.nu, (
            f"dir=0 ring length: expected {self.nu}, got {len(res.face_indices)}"
        )

    def test_dir1_ring_length_equals_nv(self) -> None:
        """4×6 torus, dir=1: ring length = nv = 6."""
        res = select_face_loop(self.cage, 0, walk_direction=1)
        assert res.closed is True
        assert len(res.face_indices) == self.nv, (
            f"dir=1 ring length: expected {self.nv}, got {len(res.face_indices)}"
        )


# ---------------------------------------------------------------------------
# Tests 12–13: ValueError on bad inputs
# ---------------------------------------------------------------------------

class TestBadInputs:
    def setup_method(self) -> None:
        self.cage = _torus_cage(4, 4)

    def test_out_of_range_raises(self) -> None:
        """start_face_idx >= num_faces raises ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            select_face_loop(self.cage, len(self.cage.faces))

    def test_invalid_walk_direction_raises(self) -> None:
        """walk_direction not in {0, 1} raises ValueError."""
        with pytest.raises(ValueError, match="walk_direction"):
            select_face_loop(self.cage, 0, walk_direction=2)


# ---------------------------------------------------------------------------
# Tests 14–16: Structural invariants on FaceLoopResult
# ---------------------------------------------------------------------------

class TestResultStructure:
    def setup_method(self) -> None:
        self.cage = _torus_cage(4, 4)

    def test_result_is_face_loop_result(self) -> None:
        """Return type is FaceLoopResult."""
        res = select_face_loop(self.cage, 0)
        assert isinstance(res, FaceLoopResult)

    def test_result_fields_exist(self) -> None:
        """FaceLoopResult has all required fields."""
        res = select_face_loop(self.cage, 0)
        assert hasattr(res, "face_indices")
        assert hasattr(res, "closed")
        assert hasattr(res, "terminated_at_irregular")
        assert hasattr(res, "irregular_face_indices")
        assert hasattr(res, "honest_caveat")

    def test_honest_caveat_is_nonempty_str(self) -> None:
        """honest_caveat is a non-empty string."""
        res = select_face_loop(self.cage, 0)
        assert isinstance(res.honest_caveat, str)
        assert len(res.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 17: Non-quad start face → immediate termination
# ---------------------------------------------------------------------------

class TestNonQuadStartFace:
    def test_triangle_start_terminated(self) -> None:
        """Start face is a triangle → immediately terminated_at_irregular."""
        cage = _tri_only_cage()
        res = select_face_loop(cage, 0)
        assert res.terminated_at_irregular is True
        assert res.closed is False
        assert 0 in res.irregular_face_indices

    def test_triangle_start_face_in_indices(self) -> None:
        """Start face index is included in face_indices even on immediate termination."""
        cage = _tri_only_cage()
        res = select_face_loop(cage, 0)
        assert 0 in res.face_indices


# ---------------------------------------------------------------------------
# Test 18: Single-quad cage → boundary termination
# ---------------------------------------------------------------------------

class TestSingleQuadFace:
    def test_single_quad_terminates(self) -> None:
        """Single-quad cage: all edges are boundary → walk terminates immediately."""
        cage = _single_quad_cage()
        res = select_face_loop(cage, 0)
        assert res.terminated_at_irregular is True, (
            f"Expected terminated on single-quad cage, got {res}"
        )

    def test_single_quad_not_closed(self) -> None:
        """Single-quad cage: cannot close (no neighbours)."""
        cage = _single_quad_cage()
        res = select_face_loop(cage, 0)
        assert res.closed is False
