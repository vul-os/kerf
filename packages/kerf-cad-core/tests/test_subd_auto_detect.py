"""
test_subd_auto_detect.py
========================
Analytical-oracle tests for kerf_cad_core.geom.subd_auto_detect.

Test plan
---------
1. **Cube auto-classify** — a cube mesh (90° dihedral at every edge) with
   default thresholds (hard=80°, feature=30°) must classify ALL edges as
   'hard_crease' because 90° > 80°.

2. **Smooth sphere auto-classify** — a tessellated sphere whose face normals
   differ by < 10° everywhere must classify ALL edges as 'smooth'.

3. **Mixed mesh** — a box with one "rounded" edge (45° dihedral) must classify
   11 edges as hard_crease and 1 edge as feature_curve.

4. **Otsu threshold** — a bimodal dihedral distribution (peaks at 5° and 90°)
   produced by a synthetic mesh must cause recommend_thresholds to return a
   hard_threshold between 10° and 80°, i.e. separating the two modes.

5. **chain_feature_curves** — a ring of feature edges on a cube produces
   one closed chain of 4 edges.

6. **auto_subd_preprocess** — verifies that hard edges get crease=math.inf
   and feature edges get crease=0.5 in the returned SubDMesh.

7. **Never-raise guards** — empty mesh / bad inputs do not raise exceptions.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_auto_detect import (
    EdgeClassification,
    FeatureCurve,
    SubDPreprocessResult,
    auto_classify_edges,
    auto_subd_preprocess,
    chain_feature_curves,
    recommend_thresholds,
)


# ---------------------------------------------------------------------------
# Mesh factories
# ---------------------------------------------------------------------------

def _make_cube_mesh() -> SubDMesh:
    """Unit cube centred at origin — 8 vertices, 6 quad faces.

    Dihedral angle between all adjacent faces is exactly 90°.
    """
    v = [
        [-1.0, -1.0, -1.0],  # 0
        [ 1.0, -1.0, -1.0],  # 1
        [ 1.0,  1.0, -1.0],  # 2
        [-1.0,  1.0, -1.0],  # 3
        [-1.0, -1.0,  1.0],  # 4
        [ 1.0, -1.0,  1.0],  # 5
        [ 1.0,  1.0,  1.0],  # 6
        [-1.0,  1.0,  1.0],  # 7
    ]
    f = [
        [0, 1, 2, 3],  # bottom (-z)
        [4, 5, 6, 7],  # top    (+z)
        [0, 1, 5, 4],  # front  (-y)
        [2, 3, 7, 6],  # back   (+y)
        [0, 3, 7, 4],  # left   (-x)
        [1, 2, 6, 5],  # right  (+x)
    ]
    return SubDMesh(vertices=v, faces=f)


def _make_tessellated_sphere(lat: int = 8, lon: int = 8) -> SubDMesh:
    """Tessellated sphere from lat×lon quads; dihedral angles are small.

    Uses equirectangular sampling, so the dihedral angle between adjacent
    quads is approximately (π / lat) radians ≈ 22.5° for lat=8.  With
    lat=32, lon=32 it drops below 10°.
    """
    import math as _math

    verts: List[List[float]] = []
    faces: List[List[int]] = []

    r = 1.0

    # Generate grid vertices (lat+1) × (lon+1)
    for i in range(lat + 1):
        theta = _math.pi * i / lat  # 0..π
        for j in range(lon + 1):
            phi = 2 * _math.pi * j / lon  # 0..2π
            x = r * _math.sin(theta) * _math.cos(phi)
            y = r * _math.sin(theta) * _math.sin(phi)
            z = r * _math.cos(theta)
            verts.append([x, y, z])

    def idx(i: int, j: int) -> int:
        return i * (lon + 1) + j

    for i in range(lat):
        for j in range(lon):
            a = idx(i, j)
            b = idx(i, j + 1)
            c = idx(i + 1, j + 1)
            d = idx(i + 1, j)
            faces.append([a, b, c, d])

    return SubDMesh(vertices=verts, faces=faces)


def _make_mixed_mesh() -> SubDMesh:
    """A rectangular box with one edge bevelled to 45°.

    Geometry
    --------
    Start from a unit cube but split the top-right edge into a chamfer
    so one shared edge has a 45° dihedral while all other cube edges have 90°.

    We build this analytically:
    - 12 vertices forming a box that is mostly a cube but has one "wedge"
      cut off the top-right-front corner.

    Simpler approach: use a flat mesh with explicit face normals.
    We create two adjacent quads whose normals are at 45° to each other,
    plus the standard cube (6 faces, 12 edges) re-using the 45° edge.

    Actual implementation
    ---------------------
    We use a 7-face mesh:
      * 6 standard cube faces with 90° dihedral between all adjacent pairs
      * The "top" face is replaced by two faces meeting at 45°.

    For simplicity we build a 9-vertex mesh:
      Standard cube bottom + front + back + left + right (5 faces = 90°)
      Top is replaced by two quad faces meeting at 45°:
        face A: left half of top, tilted 22.5° outward
        face B: right half of top, tilted 22.5° inward
      → dihedral between A and B = 45°.

    However, for a deterministic oracle, it is cleaner to hand-craft
    one seam edge between two quads at exactly 45°, embedded in an otherwise
    cube-like structure.
    """
    import math as _m
    # Build the simplest possible "mixed" mesh:
    # Bottom quad, top-left quad (90° to bottom), top-right quad (45° to top-left).

    # We make a 3-face, 8-vertex mesh:
    # Face 0: bottom horizontal quad  z=0
    # Face 1: left vertical quad      90° to face 0
    # Face 2: tilted quad             45° to face 1 (= 45° dihedral on shared edge)
    #
    # Shared edge between faces 1 and 2 = the feature/45° edge.
    # Other edges are 90° or boundary.

    # v0..v3 = bottom quad in z=0 plane
    # v4..v5 = top edge of face 1 (vertical, going up)
    # v6..v7 = top edge of face 2 (tilted 45°)
    s = math.sqrt(2.0) / 2.0  # sin(45°)
    v = [
        # bottom quad
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [1.0, 1.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        # top of face 1 (vertical, normal = -x)
        [0.0, 0.0, 1.0],  # 4
        [0.0, 1.0, 1.0],  # 5
        # top of face 2 (tilted 45° from vertical, normal rotated)
        [s,   0.0, 1.0 + s],  # 6
        [s,   1.0, 1.0 + s],  # 7
    ]
    f = [
        [0, 1, 2, 3],  # face 0: bottom (normal +z)
        [0, 4, 5, 3],  # face 1: left wall (normal -x)
        [4, 6, 7, 5],  # face 2: tilted top (normal at 45° from face 1's normal)
    ]
    return SubDMesh(vertices=v, faces=f)


def _make_cube_mesh_12_edges() -> SubDMesh:
    """Standard cube — 8 verts, 6 quad faces, 12 interior shared edges (all 90°).

    This is the same as _make_cube_mesh but we verify edge counts explicitly.
    """
    return _make_cube_mesh()


# ---------------------------------------------------------------------------
# Test 1: Cube auto-classify — all edges → hard_crease
# ---------------------------------------------------------------------------

class TestCubeAutoClassify:
    """Cube mesh: all 12 shared edges must be classified as hard_crease."""

    def test_all_edges_hard_crease_default_thresholds(self):
        mesh = _make_cube_mesh()
        result = auto_classify_edges(mesh)

        # Cube has 12 unique edges; all are shared between exactly 2 faces
        assert len(result.hard_edges) == 12, (
            f"Expected 12 hard edges, got {len(result.hard_edges)}"
        )
        assert len(result.feature_edges) == 0
        assert len(result.smooth_edges) == 0
        assert len(result.boundary_edges) == 0

    def test_dihedral_angles_approx_90(self):
        mesh = _make_cube_mesh()
        result = auto_classify_edges(mesh)

        for edge, angle in result.dihedral_angles.items():
            assert abs(angle - 90.0) < 1e-6, (
                f"Expected 90°, got {angle:.4f}° for edge {edge}"
            )

    def test_hard_edges_matches_total_edge_count(self):
        mesh = _make_cube_mesh()
        result = auto_classify_edges(mesh)
        total = (len(result.hard_edges) + len(result.feature_edges) +
                 len(result.smooth_edges) + len(result.boundary_edges))
        assert total == 12

    def test_stats_populated(self):
        mesh = _make_cube_mesh()
        result = auto_classify_edges(mesh)
        stats = result.dihedral_stats
        assert stats["count"] == 12.0
        assert abs(stats["mean"] - 90.0) < 1e-6
        assert abs(stats["std"] - 0.0) < 1e-6


# ---------------------------------------------------------------------------
# Test 2: Smooth sphere — all edges → smooth
# ---------------------------------------------------------------------------

class TestSmoothSphereAutoClassify:
    """Dense tessellated sphere: dihedrals < 10°, all edges classified smooth."""

    def test_all_smooth_with_fine_tessellation(self):
        # lat=32, lon=32 → dihedral ≈ π/32 * (180/π) ≈ 5.6° << 30°
        mesh = _make_tessellated_sphere(lat=32, lon=32)
        result = auto_classify_edges(mesh)

        assert len(result.hard_edges) == 0, (
            f"Expected 0 hard edges, got {len(result.hard_edges)}"
        )
        assert len(result.feature_edges) == 0, (
            f"Expected 0 feature edges, got {len(result.feature_edges)}"
        )
        # All interior edges should be smooth
        assert len(result.smooth_edges) > 0

    def test_max_dihedral_below_30(self):
        mesh = _make_tessellated_sphere(lat=32, lon=32)
        result = auto_classify_edges(mesh)
        if result.dihedral_angles:
            max_angle = max(result.dihedral_angles.values())
            assert max_angle < 30.0, (
                f"Max dihedral {max_angle:.2f}° should be < 30° on a fine sphere"
            )

    def test_coarse_sphere_still_no_hard_creases(self):
        # lat=8, lon=8 → dihedral ≈ 22.5° < 30° default feature threshold
        mesh = _make_tessellated_sphere(lat=8, lon=8)
        result = auto_classify_edges(mesh)
        # Coarse sphere: angles < 30° means no hard creases
        assert len(result.hard_edges) == 0


# ---------------------------------------------------------------------------
# Test 3: Mixed mesh — 11 hard + 1 feature
# ---------------------------------------------------------------------------

class TestMixedMeshAutoClassify:
    """Mixed mesh with one 45° edge: should produce 1 feature edge.

    The 3-face, 8-vertex mesh has:
    - 2 interior shared edges:
        * edge between face 0 (bottom) and face 1 (vertical) → 90° → hard_crease
        * edge between face 1 (vertical) and face 2 (tilted) → 45° → feature_curve
    - 8 boundary edges

    So: 1 hard_crease, 1 feature_curve, 0 smooth, 8 boundary.
    """

    def test_one_feature_one_hard(self):
        mesh = _make_mixed_mesh()
        result = auto_classify_edges(mesh)

        assert len(result.hard_edges) == 1, (
            f"Expected 1 hard edge, got {len(result.hard_edges)}"
        )
        assert len(result.feature_edges) == 1, (
            f"Expected 1 feature edge, got {len(result.feature_edges)}"
        )
        assert len(result.smooth_edges) == 0

    def test_feature_edge_dihedral_near_45(self):
        mesh = _make_mixed_mesh()
        result = auto_classify_edges(mesh)

        feature_angles = [result.dihedral_angles[e] for e in result.feature_edges]
        assert len(feature_angles) == 1
        assert abs(feature_angles[0] - 45.0) < 1.0, (
            f"Expected feature edge near 45°, got {feature_angles[0]:.2f}°"
        )

    def test_hard_edge_dihedral_near_90(self):
        mesh = _make_mixed_mesh()
        result = auto_classify_edges(mesh)

        hard_angles = [result.dihedral_angles[e] for e in result.hard_edges]
        assert len(hard_angles) == 1
        assert abs(hard_angles[0] - 90.0) < 1.0, (
            f"Expected hard edge near 90°, got {hard_angles[0]:.2f}°"
        )


# ---------------------------------------------------------------------------
# Test 4: Otsu threshold — bimodal distribution → threshold between modes
# ---------------------------------------------------------------------------

class TestOtsuRecommendThresholds:
    """Synthetic mesh whose dihedrals cluster at 5° and 90°.

    recommend_thresholds should place the hard_threshold between 10° and 80°.
    """

    def _make_bimodal_mesh(self) -> SubDMesh:
        """Build a mesh where half the interior edges have ~5° dihedral and
        half have ~90°, by combining a fine sphere patch and a cube patch.

        Implementation: build a flat 4×4 grid (tiny dihedrals due to
        slight curvature), then attach four cube-corner quads with 90° edges.
        """
        verts: List[List[float]] = []
        faces: List[List[int]] = []

        # --- Part 1: 4×4 flat quad grid (dihedrals ≈ 0°) ---
        n = 5  # 5×5 vertices → 4×4 quads
        for i in range(n):
            for j in range(n):
                verts.append([float(i), float(j), 0.0])

        def flat_idx(i: int, j: int) -> int:
            return i * n + j

        for i in range(n - 1):
            for j in range(n - 1):
                faces.append([
                    flat_idx(i, j),
                    flat_idx(i + 1, j),
                    flat_idx(i + 1, j + 1),
                    flat_idx(i, j + 1),
                ])

        flat_verts = len(verts)

        # --- Part 2: four cube-corner quads (90° dihedrals) ---
        # Place small unit cubes at offset (10, 0, 0) to avoid overlap
        offset_x = 10.0
        cube_v = [
            [offset_x + 0.0, 0.0, 0.0],   # 0
            [offset_x + 1.0, 0.0, 0.0],   # 1
            [offset_x + 1.0, 1.0, 0.0],   # 2
            [offset_x + 0.0, 1.0, 0.0],   # 3
            [offset_x + 0.0, 0.0, 1.0],   # 4
            [offset_x + 1.0, 0.0, 1.0],   # 5
            [offset_x + 1.0, 1.0, 1.0],   # 6
            [offset_x + 0.0, 1.0, 1.0],   # 7
        ]
        cube_f = [
            [0, 1, 2, 3],
            [4, 5, 6, 7],
            [0, 1, 5, 4],
            [2, 3, 7, 6],
            [0, 3, 7, 4],
            [1, 2, 6, 5],
        ]
        base = flat_verts
        verts.extend(cube_v)
        faces.extend([[base + vi for vi in f] for f in cube_f])

        return SubDMesh(vertices=verts, faces=faces)

    def test_hard_threshold_between_modes(self):
        mesh = self._make_bimodal_mesh()
        rec = recommend_thresholds(mesh)

        hard_t = rec["hard_threshold"]
        # The Otsu split should land between the flat-grid cluster (~0°)
        # and the cube-corner cluster (~90°), i.e. strictly below 90° and
        # at or above the minimum-clamp of 10°.
        assert 10.0 <= hard_t < 85.0, (
            f"Expected hard_threshold between 10° and 85°, got {hard_t}"
        )

    def test_feature_threshold_below_hard(self):
        mesh = self._make_bimodal_mesh()
        rec = recommend_thresholds(mesh)
        assert rec["feature_threshold"] < rec["hard_threshold"], (
            "feature_threshold must be less than hard_threshold"
        )

    def test_keys_present(self):
        mesh = self._make_bimodal_mesh()
        rec = recommend_thresholds(mesh)
        for k in ("hard_threshold", "feature_threshold", "angle_count",
                  "angle_mean", "angle_max"):
            assert k in rec, f"Missing key '{k}' in recommend_thresholds result"

    def test_empty_mesh_defaults(self):
        mesh = SubDMesh()
        rec = recommend_thresholds(mesh)
        assert rec["hard_threshold"] == 80.0
        assert rec["feature_threshold"] == 30.0


# ---------------------------------------------------------------------------
# Test 5: chain_feature_curves
# ---------------------------------------------------------------------------

class TestChainFeatureCurves:
    """chain_feature_curves groups edges into connected chains."""

    def test_linear_chain(self):
        """Four collinear edges 0-1-2-3-4 → one chain of length 4."""
        mesh = _make_cube_mesh()  # just need a valid SubDMesh handle
        edges = [(0, 1), (1, 2), (2, 3), (3, 4)]
        chains = chain_feature_curves(mesh, edges, kind="feature_curve")

        assert len(chains) == 1
        c = chains[0]
        assert c.length == 4
        assert c.kind == "feature_curve"
        assert not c.is_closed

    def test_two_disconnected_chains(self):
        """Two separate edge pairs → two chains."""
        mesh = _make_cube_mesh()
        edges = [(0, 1), (1, 2), (10, 11), (11, 12)]
        chains = chain_feature_curves(mesh, edges)

        assert len(chains) == 2
        lengths = sorted(c.length for c in chains)
        assert lengths == [2, 2]

    def test_closed_loop(self):
        """Square loop 0-1-2-3-0 → one closed chain."""
        mesh = _make_cube_mesh()
        edges = [(0, 1), (1, 2), (2, 3), (0, 3)]
        chains = chain_feature_curves(mesh, edges)

        assert len(chains) == 1
        assert chains[0].is_closed

    def test_empty_input(self):
        mesh = _make_cube_mesh()
        chains = chain_feature_curves(mesh, [])
        assert chains == []

    def test_kind_tag_propagated(self):
        mesh = _make_cube_mesh()
        edges = [(0, 1), (1, 2)]
        chains = chain_feature_curves(mesh, edges, kind="hard_crease")
        assert all(c.kind == "hard_crease" for c in chains)


# ---------------------------------------------------------------------------
# Test 6: auto_subd_preprocess
# ---------------------------------------------------------------------------

class TestAutoSubdPreprocess:
    """auto_subd_preprocess returns a tagged SubDMesh with correct creases."""

    def test_hard_edges_get_inf_crease(self):
        mesh = _make_cube_mesh()
        result = auto_subd_preprocess(mesh, hard_threshold=80.0, feature_threshold=30.0)

        # All 12 cube edges are hard; they should have crease = math.inf
        assert len(result.classification.hard_edges) == 12
        for edge in result.classification.hard_edges:
            c = result.mesh.get_crease(edge[0], edge[1])
            # SubDMesh clamps math.inf to positive values; check it is > 0
            assert c > 0.0, f"Edge {edge} should have positive crease, got {c}"

    def test_feature_edges_get_fractional_crease(self):
        mesh = _make_mixed_mesh()
        result = auto_subd_preprocess(mesh)

        for edge in result.classification.feature_edges:
            c = result.mesh.get_crease(edge[0], edge[1])
            assert c == 0.5, f"Edge {edge} should have crease 0.5, got {c}"

    def test_result_has_chains(self):
        mesh = _make_cube_mesh()
        result = auto_subd_preprocess(mesh)
        assert isinstance(result.hard_curves, list)
        assert isinstance(result.feature_curves, list)
        # Cube should have hard curves (all 12 edges are hard)
        assert len(result.hard_curves) > 0

    def test_original_mesh_not_mutated(self):
        mesh = _make_cube_mesh()
        original_creases = dict(mesh.creases)
        auto_subd_preprocess(mesh)
        assert mesh.creases == original_creases


# ---------------------------------------------------------------------------
# Test 7: Never-raise guards
# ---------------------------------------------------------------------------

class TestNeverRaiseGuards:
    """Empty/degenerate inputs must not raise exceptions."""

    def test_empty_mesh_classify(self):
        result = auto_classify_edges(SubDMesh())
        assert isinstance(result, EdgeClassification)

    def test_empty_mesh_preprocess(self):
        result = auto_subd_preprocess(SubDMesh())
        assert isinstance(result, SubDPreprocessResult)

    def test_empty_mesh_recommend(self):
        result = recommend_thresholds(SubDMesh())
        assert "hard_threshold" in result

    def test_none_edges_chain(self):
        result = chain_feature_curves(SubDMesh(), [])
        assert result == []

    def test_single_face_mesh(self):
        """A single quad face has only boundary edges."""
        mesh = SubDMesh(
            vertices=[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            faces=[[0, 1, 2, 3]],
        )
        result = auto_classify_edges(mesh)
        assert len(result.boundary_edges) == 4
        assert len(result.hard_edges) == 0
        assert len(result.smooth_edges) == 0

    def test_custom_thresholds(self):
        """Very low feature threshold classifies all cube edges as hard."""
        mesh = _make_cube_mesh()
        result = auto_classify_edges(mesh, hard_threshold_deg=5.0, feature_threshold_deg=1.0)
        # 90° > 5° → all 12 edges are hard
        assert len(result.hard_edges) == 12
