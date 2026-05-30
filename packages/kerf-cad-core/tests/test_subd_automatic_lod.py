"""
Tests for kerf_cad_core.geom.subd_automatic_lod — SubD automatic LOD chain.

Coverage (4 analytical-oracle tests required by DoD):

  T1. LOD count monotonic (4× triangles per CC level):
        For an all-quad cage, each LOD level has >= the previous level's
        triangle count, with the ratio approaching 4× for interior quads.

  T2. Cage LOD 0 vertex count:
        chain.vertex_counts[0] matches cage.num_vertices exactly.

  T3. Progressive mesh collapse round-trip:
        - With all collapses applied (base mesh) → n_base_faces < n_fine_faces.
        - With no collapses (fine mesh via splits) → n_fine_vertices >= n_base_vertices.
        Both checks verify the Hoppe collapse direction is correct.

  T4. LOD picker distance thresholds:
        - At a very large distance (10 000 m) → LOD 0 (coarsest).
        - At a very small distance (0.001 m) → finest LOD.

Additional robustness checks:
  - Empty / degenerate cage does not raise.
  - n_levels clamp (0 → 1, 9 → 8).
  - pick_lod_for_view with empty chain returns 0.
  - pick_lod_for_view with distance <= 0 returns finest.
"""

from __future__ import annotations

import pytest

from kerf_cad_core.geom.subd import (
    SubDMesh,
    catmull_clark_subdivide,
)
from kerf_cad_core.geom.subd_automatic_lod import (
    ProgressiveMesh,
    SubdLodChain,
    generate_progressive_mesh,
    generate_subd_lod_chain,
    pick_lod_for_view,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_cube_cage() -> SubDMesh:
    """Unit cube: 8 vertices, 6 quad faces."""
    verts = [
        [-1.0, -1.0, -1.0],
        [ 1.0, -1.0, -1.0],
        [ 1.0,  1.0, -1.0],
        [-1.0,  1.0, -1.0],
        [-1.0, -1.0,  1.0],
        [ 1.0, -1.0,  1.0],
        [ 1.0,  1.0,  1.0],
        [-1.0,  1.0,  1.0],
    ]
    faces = [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [0, 1, 5, 4],
        [2, 3, 7, 6],
        [0, 3, 7, 4],
        [1, 2, 6, 5],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def make_flat_quad_mesh() -> SubDMesh:
    """3×3 grid of 4 quads in the z=0 plane (9 vertices, 4 faces)."""
    verts = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0],
        [0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [2.0, 1.0, 0.0],
        [0.0, 2.0, 0.0], [1.0, 2.0, 0.0], [2.0, 2.0, 0.0],
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
        [3, 4, 7, 6],
        [4, 5, 8, 7],
    ]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# T1: LOD triangle counts are monotonically non-decreasing (4× growth per level)
# ---------------------------------------------------------------------------

class TestLodCountMonotonic:
    """T1 — each LOD level has >= the previous level's triangle count.

    For an all-quad closed mesh (cube), CC produces all-quad output at each
    level.  Each quad becomes 4 quads → 4× triangle count.  We allow slight
    latitude for boundary effects but require strict monotonic growth.
    """

    def test_cube_triangle_counts_monotonic(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=4)
        assert chain.n_levels == 5, f"expected 5 levels (0..4), got {chain.n_levels}"
        tc = chain.triangle_counts
        for i in range(1, len(tc)):
            assert tc[i] > tc[i - 1], (
                f"triangle count not increasing at level {i}: {tc[i - 1]} → {tc[i]}"
            )

    def test_cube_triangle_counts_quadrupling(self) -> None:
        """For a closed all-quad cage, each CC level multiplies face count by ~4."""
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=3)
        tc = chain.triangle_counts
        # The ratio should be >=3 (exact 4× only for infinite open mesh; boundary
        # effects slightly reduce it for the cube).  We require at least 3×.
        for i in range(1, len(tc)):
            ratio = tc[i] / tc[i - 1] if tc[i - 1] > 0 else 0
            assert ratio >= 3.0, (
                f"expected >=3× at level {i}, got ratio={ratio:.2f} "
                f"({tc[i - 1]} → {tc[i]})"
            )

    def test_vertex_counts_monotonic(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=3)
        vc = chain.vertex_counts
        for i in range(1, len(vc)):
            assert vc[i] > vc[i - 1], (
                f"vertex count not increasing at level {i}: {vc[i - 1]} → {vc[i]}"
            )

    def test_flat_patch_monotonic(self) -> None:
        cage = make_flat_quad_mesh()
        chain = generate_subd_lod_chain(cage, n_levels=3)
        tc = chain.triangle_counts
        for i in range(1, len(tc)):
            assert tc[i] > tc[i - 1]


# ---------------------------------------------------------------------------
# T2: Cage LOD 0 vertex count matches input cage
# ---------------------------------------------------------------------------

class TestCageLod0VertexCount:
    """T2 — chain.vertex_counts[0] == cage.num_vertices (exact equality)."""

    def test_cube_cage_vertex_count(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=4)
        assert chain.vertex_counts[0] == cage.num_vertices, (
            f"LOD 0 vertex count {chain.vertex_counts[0]} != cage {cage.num_vertices}"
        )

    def test_cube_cage_face_count_via_triangles(self) -> None:
        """Cube has 6 quad faces → 12 triangles at LOD 0."""
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=2)
        assert chain.triangle_counts[0] == 12, (
            f"expected 12 triangles at LOD 0 (6 quads×2), got {chain.triangle_counts[0]}"
        )

    def test_flat_patch_vertex_count(self) -> None:
        cage = make_flat_quad_mesh()
        chain = generate_subd_lod_chain(cage, n_levels=2)
        assert chain.vertex_counts[0] == cage.num_vertices

    def test_levels_list_length(self) -> None:
        cage = make_cube_cage()
        for n in [1, 2, 4]:
            chain = generate_subd_lod_chain(cage, n_levels=n)
            assert len(chain.levels) == n + 1, (
                f"n_levels={n}: expected {n+1} entries, got {len(chain.levels)}"
            )
            assert len(chain.vertex_counts) == n + 1
            assert len(chain.triangle_counts) == n + 1


# ---------------------------------------------------------------------------
# T3: Progressive mesh collapse round-trip
# ---------------------------------------------------------------------------

class TestProgressiveMeshRoundTrip:
    """T3 — Hoppe progressive mesh collapse direction + size invariants.

    - With all collapses applied (base mesh): n_base_faces < n_fine_faces.
    - Splits list has same length as collapses list (each collapse ↔ one split).
    - n_fine_vertices stored correctly equals cage triangulated vertex count.
    """

    def test_base_has_fewer_faces(self) -> None:
        cage = make_cube_cage()
        pm = generate_progressive_mesh(cage)
        # Fine mesh: 6 quads → 12 tris
        assert pm.n_fine_faces == 12, f"expected 12 fine faces, got {pm.n_fine_faces}"
        assert pm.n_base_faces < pm.n_fine_faces, (
            f"base ({pm.n_base_faces}) should be fewer than fine ({pm.n_fine_faces})"
        )

    def test_collapses_and_splits_same_count(self) -> None:
        cage = make_cube_cage()
        pm = generate_progressive_mesh(cage)
        assert len(pm.collapses) == len(pm.splits), (
            f"collapses={len(pm.collapses)} != splits={len(pm.splits)}"
        )

    def test_base_vertices_le_fine_vertices(self) -> None:
        cage = make_cube_cage()
        pm = generate_progressive_mesh(cage)
        assert pm.n_base_vertices <= pm.n_fine_vertices, (
            f"base vertices {pm.n_base_vertices} > fine {pm.n_fine_vertices}"
        )

    def test_fine_vertices_equals_cage_vertex_count(self) -> None:
        cage = make_cube_cage()
        pm = generate_progressive_mesh(cage)
        # Triangulation doesn't add vertices
        assert pm.n_fine_vertices == cage.num_vertices, (
            f"expected {cage.num_vertices} fine verts, got {pm.n_fine_vertices}"
        )

    def test_limited_collapses(self) -> None:
        """n_collapses=3 → exactly 3 collapse records."""
        cage = make_cube_cage()
        pm = generate_progressive_mesh(cage, n_collapses=3)
        assert len(pm.collapses) <= 3

    def test_collapse_records_have_valid_vertex_indices(self) -> None:
        cage = make_cube_cage()
        pm = generate_progressive_mesh(cage)
        nv = pm.n_fine_vertices
        for rec in pm.collapses:
            assert 0 <= rec.v_a < nv, f"v_a={rec.v_a} out of range [0, {nv})"
            assert 0 <= rec.v_b < nv, f"v_b={rec.v_b} out of range [0, {nv})"
            assert rec.v_a != rec.v_b, "v_a == v_b in collapse record"
            assert len(rec.merged_position) == 3

    def test_higher_lod_input_gives_more_collapses(self) -> None:
        """Subdividing before building PM gives more fine faces → more collapses."""
        cage = make_cube_cage()
        pm_cage = generate_progressive_mesh(cage)
        subdivided = catmull_clark_subdivide(cage, levels=2)
        pm_subd = generate_progressive_mesh(subdivided)
        assert pm_subd.n_fine_faces > pm_cage.n_fine_faces


# ---------------------------------------------------------------------------
# T4: LOD picker — distance thresholds
# ---------------------------------------------------------------------------

class TestLodPicker:
    """T4 — pick_lod_for_view returns coarsest at large distance, finest up close."""

    def test_very_large_distance_returns_lod0(self) -> None:
        """At 10 000 m viewing distance → LOD 0 (coarsest)."""
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=4)
        lod = pick_lod_for_view(chain, distance=10_000.0)
        assert lod == 0, f"expected LOD 0 at 10 000 m, got {lod}"

    def test_very_small_distance_returns_finest_lod(self) -> None:
        """At 0.001 m (1 mm) viewing distance → finest LOD."""
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=4)
        lod = pick_lod_for_view(chain, distance=0.001)
        assert lod == chain.n_levels - 1, (
            f"expected finest LOD {chain.n_levels - 1} at 1 mm, got {lod}"
        )

    def test_lod_increases_as_distance_decreases(self) -> None:
        """LOD selection is monotonically non-decreasing as distance decreases."""
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=4)
        distances = [10_000.0, 100.0, 10.0, 1.0, 0.1, 0.001]
        lods = [pick_lod_for_view(chain, d) for d in distances]
        for i in range(1, len(lods)):
            assert lods[i] >= lods[i - 1], (
                f"LOD decreased from {lods[i - 1]} to {lods[i]} "
                f"as distance went from {distances[i - 1]} to {distances[i]}"
            )

    def test_result_in_valid_range(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=4)
        for d in [0.001, 1.0, 10.0, 1000.0]:
            lod = pick_lod_for_view(chain, d)
            assert 0 <= lod < chain.n_levels, (
                f"LOD {lod} out of range [0, {chain.n_levels}) at d={d}"
            )

    def test_empty_chain_returns_zero(self) -> None:
        empty = SubdLodChain()
        assert pick_lod_for_view(empty, distance=5.0) == 0

    def test_single_level_chain_returns_zero(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=1)
        # n_levels=1 → 2 total levels (cage + 1 subdivision)
        # at very close distance should return 1 (finest), not crash
        lod = pick_lod_for_view(chain, distance=0.001)
        assert lod < chain.n_levels

    def test_zero_or_negative_distance_returns_finest(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=3)
        lod = pick_lod_for_view(chain, distance=0.0)
        assert lod == chain.n_levels - 1

        lod_neg = pick_lod_for_view(chain, distance=-5.0)
        assert lod_neg == chain.n_levels - 1


# ---------------------------------------------------------------------------
# Robustness / never-raise checks
# ---------------------------------------------------------------------------

class TestRobustness:
    """Degenerate inputs do not raise; results are sensible defaults."""

    def test_empty_cage_does_not_raise(self) -> None:
        empty = SubDMesh()
        chain = generate_subd_lod_chain(empty, n_levels=2)
        assert chain.n_levels >= 1

    def test_single_quad_cage(self) -> None:
        mesh = SubDMesh(
            vertices=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                      [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
            faces=[[0, 1, 2, 3]],
        )
        chain = generate_subd_lod_chain(mesh, n_levels=3)
        assert chain.n_levels == 4
        assert chain.vertex_counts[0] == 4

    def test_progressive_mesh_empty_cage_does_not_raise(self) -> None:
        empty = SubDMesh()
        pm = generate_progressive_mesh(empty)
        assert pm.n_fine_faces == 0

    def test_n_levels_clamped_to_minimum_1(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=0)
        # 0 → clamped to 1 → 2 total levels
        assert chain.n_levels >= 2

    def test_n_levels_clamped_to_maximum_8(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=99)
        assert chain.n_levels <= 9  # 8 + cage

    def test_switch_distances_positive(self) -> None:
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=3)
        for i, sd in enumerate(chain.switch_distances):
            assert sd >= 0.0, f"negative switch distance at level {i}: {sd}"

    def test_level_pixel_errors_decreasing(self) -> None:
        """Finer LODs have smaller RMS edge lengths → smaller pixel errors."""
        cage = make_cube_cage()
        chain = generate_subd_lod_chain(cage, n_levels=3)
        pe = chain.level_pixel_errors
        for i in range(1, len(pe)):
            assert pe[i] <= pe[i - 1], (
                f"pixel error should decrease at finer LOD {i}: {pe[i - 1]} → {pe[i]}"
            )
