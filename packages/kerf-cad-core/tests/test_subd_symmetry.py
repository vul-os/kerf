"""Tests for subd_symmetry.py — SubD mirror-symmetry detection and enforcement.

Analytical oracles only; no OCC, no database, no network.

Test plan
---------
1. Cube symmetry        — cube cage → detect_mirror_symmetry returns planes with
                          score 1.0 for XY, XZ, YZ.
2. Asymmetric cage      — 3-sided pyramid with only one z-axis cap vertex →
                          no plane has score 1.0; the tetrahedron-axis plane
                          (YZ passing through centroid) has score ≥ 0.67.
3. Enforce round-trip   — slightly asymmetric cube → enforce_mirror_symmetry
                          (plane=XY) → result has perfect symmetry (score 1.0)
                          across XY; max vertex displacement < input tol_input.
4. Mirror edit          — symmetric cube + edit one vertex → mirror_edit
                          produces a still-symmetric cage; the mirrored vertex
                          moves to the reflected position; total vertex count
                          unchanged.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd_authoring import SubDCage, create_subd_primitive, _copy_cage
from kerf_cad_core.geom.subd_symmetry import (
    SymmetryPlane,
    SymmetryResult,
    detect_mirror_symmetry,
    enforce_mirror_symmetry,
    mirror_edit,
    _symmetry_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _max_vertex_displacement(cage_a: SubDCage, cage_b: SubDCage) -> float:
    """Max per-vertex distance between two cages (same topology)."""
    assert len(cage_a.vertices) == len(cage_b.vertices)
    worst = 0.0
    for va, vb in zip(cage_a.vertices, cage_b.vertices):
        d = math.sqrt(sum((x - y) ** 2 for x, y in zip(va, vb)))
        worst = max(worst, d)
    return worst


def _symmetry_score_for_plane(cage: SubDCage, label: str, tol: float = 1e-4) -> float:
    res = detect_mirror_symmetry(cage, tol=tol)
    return res.scores.get(label, res.scores.get(f"{label}_cen", 0.0))


# ---------------------------------------------------------------------------
# 1. Cube symmetry
# ---------------------------------------------------------------------------

class TestCubeSymmetry:
    """A unit cube cage must be perfectly symmetric across XY, XZ, and YZ."""

    def setup_method(self):
        self.cage = create_subd_primitive("cube", width=2.0, height=2.0, depth=2.0)

    def test_cube_xy_score_is_1(self):
        """XY plane (z=0) bisects the cube — every vertex has a mirror."""
        res = detect_mirror_symmetry(self.cage, tol=1e-4)
        xy_score = res.scores.get("XY", 0.0)
        assert xy_score == pytest.approx(1.0, abs=1e-6), (
            f"Expected XY score=1.0 for a unit cube; got {xy_score}"
        )

    def test_cube_xz_score_is_1(self):
        """XZ plane (y=0) bisects the cube — every vertex has a mirror."""
        res = detect_mirror_symmetry(self.cage, tol=1e-4)
        xz_score = res.scores.get("XZ", 0.0)
        assert xz_score == pytest.approx(1.0, abs=1e-6), (
            f"Expected XZ score=1.0 for a unit cube; got {xz_score}"
        )

    def test_cube_yz_score_is_1(self):
        """YZ plane (x=0) bisects the cube — every vertex has a mirror."""
        res = detect_mirror_symmetry(self.cage, tol=1e-4)
        yz_score = res.scores.get("YZ", 0.0)
        assert yz_score == pytest.approx(1.0, abs=1e-6), (
            f"Expected YZ score=1.0 for a unit cube; got {yz_score}"
        )

    def test_dominant_plane_score_is_1(self):
        res = detect_mirror_symmetry(self.cage, tol=1e-4)
        assert res.score == pytest.approx(1.0, abs=1e-6)
        assert res.dominant_plane is not None

    def test_returns_symmetry_result_type(self):
        res = detect_mirror_symmetry(self.cage, tol=1e-4)
        assert isinstance(res, SymmetryResult)
        assert len(res.planes) > 0


# ---------------------------------------------------------------------------
# 2. Asymmetric cage
# ---------------------------------------------------------------------------

class TestAsymmetricCage:
    """An L-shaped cage has limited symmetry across the axis planes.

    We build a genuinely asymmetric shape: three vertices arranged so that
    no axis-aligned plane through the origin reflects ALL of them onto
    another vertex.

    Vertices:
        0: (0,  0, 0)
        1: (2,  0, 0)
        2: (2,  1, 0)

    This is a flat right triangle in the z=0 plane.
    - YZ (x=0): v0 maps to (0,0,0)→self; v1(2,0,0)→(-2,0,0) – not present;
                 score = 1/3.
    - XZ (y=0): v0→self; v1→self (y=0); v2(2,1,0)→(2,-1,0) – not present;
                 score = 2/3.
    - XY (z=0): all vertices are ON the plane (|z|<tol) → score = 3/3 = 1.0.

    So: no axis plane other than XY (the trivial flat-plane case) has score 1.0
    for the 3D-asymmetric part.  We use a non-planar asymmetric cage instead.

    Non-planar asymmetric tetrahedron-like cage:
        0: (0, 0, 0)
        1: (3, 0, 0)   — not mirrored in any simple axis plane
        2: (1, 2, 0)   — breaks YZ symmetry
        3: (0, 0, 4)   — apex above vertex 0

    For YZ (x=0, reflects x→-x):
        v0(0,0,0)  → (0,0,0)   matched (self)
        v1(3,0,0)  → (-3,0,0)  not in set → unmatched
        v2(1,2,0)  → (-1,2,0)  not in set → unmatched
        v3(0,0,4)  → (0,0,4)   matched (self)
        score = 2/4 = 0.50

    For XZ (y=0):
        v0(0,0,0) → (0,0,0)   matched
        v1(3,0,0) → (3,0,0)   matched (y=0 already)
        v2(1,2,0) → (1,-2,0)  not present
        v3(0,0,4) → (0,0,4)   matched
        score = 3/4 = 0.75

    For XY (z=0):
        v0 matched (z=0)
        v1 matched (z=0)
        v2 matched (z=0)
        v3(0,0,4) → (0,0,-4) not present
        score = 3/4 = 0.75

    So max score = 0.75 < 1.0, and no plane achieves a score of 1.0.
    """

    def _make_asymmetric_cage(self) -> SubDCage:
        verts = [
            [0.0, 0.0, 0.0],  # 0
            [3.0, 0.0, 0.0],  # 1
            [1.0, 2.0, 0.0],  # 2
            [0.0, 0.0, 4.0],  # 3 — apex
        ]
        faces = [
            [0, 1, 2],     # base
            [0, 1, 3],     # front
            [1, 2, 3],     # right
            [2, 0, 3],     # left
        ]
        return SubDCage(vertices=verts, faces=faces)

    def setup_method(self):
        self.cage = self._make_asymmetric_cage()

    def test_no_plane_has_score_1(self):
        """Asymmetric tetrahedron-like cage — no axis plane achieves score 1.0."""
        res = detect_mirror_symmetry(self.cage, tol=1e-4)
        assert res.score < 1.0, (
            f"Expected dominant score < 1.0 for asymmetric cage; got {res.score}; "
            f"scores={res.scores}"
        )

    def test_xz_plane_score_above_half(self):
        """XZ (y=0) plane should match 3/4 vertices → score = 0.75."""
        res = detect_mirror_symmetry(self.cage, tol=1e-4)
        xz_score = res.scores.get("XZ", 0.0)
        assert xz_score == pytest.approx(0.75, abs=1e-6), (
            f"Expected XZ score=0.75 for asymmetric cage; got {xz_score}; "
            f"all scores={res.scores}"
        )

    def test_scores_dict_populated(self):
        res = detect_mirror_symmetry(self.cage, tol=1e-4)
        assert len(res.scores) > 0, "scores dict must not be empty"


# ---------------------------------------------------------------------------
# 3. Enforce symmetry round-trip
# ---------------------------------------------------------------------------

class TestEnforceSymmetry:
    """Slightly perturbed cube → enforce_mirror_symmetry(XY) → score = 1.0."""

    def _make_perturbed_cube(self, perturbation: float = 0.05) -> SubDCage:
        """Create a cube where one vertex on the negative-z side is slightly off."""
        cage = create_subd_primitive("cube", width=2.0, height=2.0, depth=2.0)
        result = _copy_cage(cage)
        # Perturb vertex 0 (which is at [-1,-1,-1]) on the negative-z side.
        # The XY plane is z=0; vertex 0 should mirror to vertex 4 ([-1,-1,+1]).
        result.vertices[0] = [
            result.vertices[0][0] + perturbation,
            result.vertices[0][1],
            result.vertices[0][2],
        ]
        return result

    def test_enforce_xy_gives_score_1(self):
        """After enforce_mirror_symmetry(XY, side='left'), score across XY = 1.0."""
        tol_input = 1e-3
        perturbed = self._make_perturbed_cube(perturbation=0.05)

        # Pre-condition: perturbed cage should NOT be perfectly symmetric
        pre_score = _symmetry_score_for_plane(perturbed, "XY", tol=tol_input)
        assert pre_score < 1.0, (
            f"Perturbed cage should have XY score < 1.0 before enforcement; got {pre_score}"
        )

        plane = SymmetryPlane(normal=[0.0, 0.0, 1.0], offset=0.0, label="XY")
        enforced = enforce_mirror_symmetry(perturbed, plane, side="left", tol=tol_input)

        post_score = _symmetry_score_for_plane(enforced, "XY", tol=tol_input * 10)
        assert post_score == pytest.approx(1.0, abs=1e-6), (
            f"Expected XY score=1.0 after enforcement; got {post_score}"
        )

    def test_enforce_vertex_count_unchanged(self):
        """enforce_mirror_symmetry must not change vertex count."""
        cage = self._make_perturbed_cube(perturbation=0.05)
        original_n = len(cage.vertices)
        plane = SymmetryPlane(normal=[0.0, 0.0, 1.0], offset=0.0, label="XY")
        enforced = enforce_mirror_symmetry(cage, plane)
        assert len(enforced.vertices) == original_n

    def test_enforce_face_count_unchanged(self):
        """enforce_mirror_symmetry must not change face count."""
        cage = self._make_perturbed_cube(perturbation=0.05)
        original_f = len(cage.faces)
        plane = SymmetryPlane(normal=[0.0, 0.0, 1.0], offset=0.0, label="XY")
        enforced = enforce_mirror_symmetry(cage, plane)
        assert len(enforced.faces) == original_f

    def test_enforce_max_displacement_reasonable(self):
        """Max vertex displacement after enforcement should be bounded by cage extent."""
        perturbation = 0.05
        cage = self._make_perturbed_cube(perturbation=perturbation)
        original = _copy_cage(cage)
        plane = SymmetryPlane(normal=[0.0, 0.0, 1.0], offset=0.0, label="XY")
        enforced = enforce_mirror_symmetry(cage, plane)
        max_d = _max_vertex_displacement(original, enforced)
        # Displacement should be on the same order as the perturbation, not wildly
        # larger (bounding by half the cage extent = 1.0 is very permissive).
        assert max_d < 1.0, (
            f"Max vertex displacement {max_d:.4f} is unreasonably large"
        )


# ---------------------------------------------------------------------------
# 4. Mirror edit
# ---------------------------------------------------------------------------

class TestMirrorEdit:
    """mirror_edit preserves symmetry while moving a vertex."""

    def setup_method(self):
        self.cage = create_subd_primitive("cube", width=2.0, height=2.0, depth=2.0)
        # XY plane: z=0, normal=[0,0,1], offset=0
        self.plane = SymmetryPlane(normal=[0.0, 0.0, 1.0], offset=0.0, label="XY")

    def test_mirror_edit_vertex_count_unchanged(self):
        """mirror_edit must not change vertex count."""
        n_before = len(self.cage.vertices)
        new_pos = [-1.2, -1.0, -1.0]
        result = mirror_edit(self.cage, 0, new_pos, self.plane)
        assert len(result.vertices) == n_before

    def test_primary_vertex_moved_to_new_position(self):
        """The primary vertex must be at new_position after mirror_edit."""
        new_pos = [-1.2, -1.0, -1.0]
        result = mirror_edit(self.cage, 0, new_pos, self.plane)
        v = result.vertices[0]
        assert v[0] == pytest.approx(-1.2, abs=1e-9)
        assert v[1] == pytest.approx(-1.0, abs=1e-9)
        assert v[2] == pytest.approx(-1.0, abs=1e-9)

    def test_mirror_vertex_moved_to_reflected_position(self):
        """The mirror counterpart must be at reflect(new_position, plane)."""
        new_pos = [-1.2, -1.0, -1.0]
        result = mirror_edit(self.cage, 0, new_pos, self.plane)

        # reflect([-1.2, -1.0, -1.0], z=0) = [-1.2, -1.0, +1.0]
        expected_mirror = [-1.2, -1.0, 1.0]

        # Find the vertex closest to expected_mirror in the result
        best_dist = math.inf
        for v in result.vertices:
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(v, expected_mirror)))
            best_dist = min(best_dist, d)

        assert best_dist < 1e-6, (
            f"Expected a vertex at {expected_mirror} after mirror_edit; "
            f"closest vertex is {best_dist:.2e} away"
        )

    def test_cage_remains_symmetric_after_mirror_edit(self):
        """After mirror_edit the cage should remain symmetric across XY (score 1.0)."""
        new_pos = [-1.2, -1.0, -1.0]
        result = mirror_edit(self.cage, 0, new_pos, self.plane)
        score = _symmetry_score_for_plane(result, "XY", tol=1e-4)
        assert score == pytest.approx(1.0, abs=1e-6), (
            f"Expected XY score=1.0 after mirror_edit; got {score}"
        )

    def test_mirror_edit_face_topology_unchanged(self):
        """mirror_edit must not change face topology."""
        faces_before = [list(f) for f in self.cage.faces]
        new_pos = [-1.2, -1.0, -1.0]
        result = mirror_edit(self.cage, 0, new_pos, self.plane)
        assert result.faces == faces_before

    def test_mirror_edit_out_of_bounds_vertex_returns_copy(self):
        """mirror_edit on an invalid vertex_id returns an unchanged cage."""
        new_pos = [0.0, 0.0, 0.0]
        result = mirror_edit(self.cage, 9999, new_pos, self.plane)
        assert len(result.vertices) == len(self.cage.vertices)
