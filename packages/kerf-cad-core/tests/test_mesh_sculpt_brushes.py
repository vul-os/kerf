"""test_mesh_sculpt_brushes.py — GK-P22: hermetic tests for sculpt brush engine.

Tests cover:
- Inflate on flat plane centre: max displacement at stroke position, falloff at edges
- Crease (negative inflate): vertices pull inward
- Smooth on noisy mesh: variance reduces
- Pinch: vertices converge toward stroke centre
- Out-of-radius vertices unchanged
- Falloff: boundary vertex has zero displacement
- Strength sign: positive / negative inflate directions
- Smooth strength=0: no change
- Normal override for inflate
- Pinch with negative strength: repels
- All four brush types on a minimal mesh
- Reproducibility: same inputs → same outputs
- SculptStroke defaults
- Invalid brush_type raises ValueError
- Zero-radius raises ValueError
- smooth-taubin: variance reduces on noisy sphere, volume preserved within 1%
- smooth-taubin vs smooth-naive: taubin has less shrink on repeated passes
- smooth-taubin single λ pass: low-pass effect
- smooth-taubin two passes (λ + μ): no DC shift
- smooth-taubin: brush_type_applied echo
- smooth-taubin: out-of-radius vertices unchanged
- smooth-taubin: strength=0 → no change
- _taubin_smooth_one_pass: degenerate/isolated vertices do not crash
"""

from __future__ import annotations

import math
import statistics

import pytest

from kerf_cad_core.mesh_sculpt_brushes import (
    MeshSculptResult,
    SculptStroke,
    apply_sculpt_brush,
    _taubin_smooth_one_pass,
)


# ---------------------------------------------------------------------------
# Fixtures: canonical meshes
# ---------------------------------------------------------------------------


def _flat_plane_grid(n: int = 5, size: float = 10.0):
    """Create an n×n regular flat grid on XY plane, centred at origin.

    Returns (vertices, faces) where faces are quads.
    """
    step = size / (n - 1)
    half = size / 2.0
    vertices = []
    for row in range(n):
        for col in range(n):
            x = -half + col * step
            y = -half + row * step
            z = 0.0
            vertices.append((x, y, z))

    faces = []
    for row in range(n - 1):
        for col in range(n - 1):
            i0 = row * n + col
            i1 = row * n + col + 1
            i2 = (row + 1) * n + col + 1
            i3 = (row + 1) * n + col
            faces.append([i0, i1, i2, i3])
    return vertices, faces


def _noisy_plane(n: int = 7, size: float = 10.0, noise: float = 0.5):
    """Flat plane with per-vertex Z noise for smoothing tests."""
    import random
    rng = random.Random(42)
    vertices, faces = _flat_plane_grid(n, size)
    noisy = [(x, y, z + rng.uniform(-noise, noise)) for x, y, z in vertices]
    return noisy, faces


def _cube_cage():
    """Simple unit cube as 6 quad faces."""
    vertices = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    ]
    faces = [
        [0, 1, 2, 3],  # bottom
        [4, 5, 6, 7],  # top
        [0, 1, 5, 4],  # front
        [2, 3, 7, 6],  # back
        [0, 3, 7, 4],  # left
        [1, 2, 6, 5],  # right
    ]
    return vertices, faces


# ---------------------------------------------------------------------------
# Test 1: Inflate on flat plane — max displacement at centre, falloff at edges
# ---------------------------------------------------------------------------


class TestInflateFlatPlane:
    """GK-P22 T1: inflate brush on a flat plane."""

    def setup_method(self):
        self.vertices, self.faces = _flat_plane_grid(n=7, size=20.0)
        # Brush at exact centre of the plane
        self.stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=5.0,
            brush_type="inflate",
            strength=1.0,
        )
        self.result = apply_sculpt_brush(self.vertices, self.faces, self.stroke)

    def test_output_has_same_vertex_count(self):
        assert len(self.result.output_vertices) == len(self.vertices)

    def test_some_vertices_modified(self):
        assert self.result.num_vertices_modified > 0

    def test_max_displacement_at_centre(self):
        # The centre vertex (index 24 in a 7×7 grid at (0,0,0)) should have the
        # largest displacement since w(0) = 1.
        centre_idx = None
        for i, v in enumerate(self.vertices):
            if abs(v[0]) < 1e-9 and abs(v[1]) < 1e-9:
                centre_idx = i
                break
        assert centre_idx is not None, "Centre vertex not found"
        centre_disp = abs(
            self.result.output_vertices[centre_idx][2] - self.vertices[centre_idx][2]
        )
        assert centre_disp > 0.9, f"Centre displacement {centre_disp} < 0.9"
        # All other modified vertices should be ≤ the centre displacement
        for i, (vo, vi) in enumerate(
            zip(self.result.output_vertices, self.vertices)
        ):
            d = abs(vo[2] - vi[2])
            assert d <= centre_disp + 1e-10, (
                f"Vertex {i} displacement {d} > centre {centre_disp}"
            )

    def test_vertex_outside_radius_unchanged(self):
        # Vertices at distance ≥ radius_mm from brush centre are unchanged
        r = self.stroke.radius_mm
        pos = self.stroke.position_xyz_mm
        for i, v in enumerate(self.vertices):
            dist = math.sqrt(
                (v[0] - pos[0]) ** 2 + (v[1] - pos[1]) ** 2 + (v[2] - pos[2]) ** 2
            )
            if dist >= r:
                vo = self.result.output_vertices[i]
                assert vo[0] == pytest.approx(v[0], abs=1e-12)
                assert vo[1] == pytest.approx(v[1], abs=1e-12)
                assert vo[2] == pytest.approx(v[2], abs=1e-12)

    def test_brush_type_echo(self):
        assert self.result.brush_type_applied == "inflate"

    def test_honest_caveat_nonempty(self):
        assert len(self.result.honest_caveat) > 20

    def test_max_displacement_positive(self):
        assert self.result.max_displacement_mm > 0.0

    def test_mean_displacement_positive(self):
        assert self.result.mean_displacement_mm > 0.0


# ---------------------------------------------------------------------------
# Test 2: Crease brush — vertices pull inward (negative inflate)
# ---------------------------------------------------------------------------


class TestCreaseBrush:
    """GK-P22 T2: crease brush pulls vertices inward."""

    def setup_method(self):
        self.vertices, self.faces = _flat_plane_grid(n=7, size=20.0)
        # Positive strength crease = inward (Z decreases on upward-facing plane)
        self.stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=5.0,
            brush_type="crease",
            strength=1.0,
        )
        self.result = apply_sculpt_brush(self.vertices, self.faces, self.stroke)

    def test_centre_vertex_displaced_inward(self):
        # On a flat plane with normals pointing +Z, crease with positive strength
        # should move the centre vertex in -Z.
        centre_idx = None
        for i, v in enumerate(self.vertices):
            if abs(v[0]) < 1e-9 and abs(v[1]) < 1e-9:
                centre_idx = i
                break
        assert centre_idx is not None
        dz = self.result.output_vertices[centre_idx][2] - self.vertices[centre_idx][2]
        assert dz < 0.0, f"Crease should pull inward, got dz={dz}"

    def test_crease_is_inverse_of_inflate(self):
        inflate_stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=5.0,
            brush_type="inflate",
            strength=1.0,
        )
        inflate_result = apply_sculpt_brush(self.vertices, self.faces, inflate_stroke)

        for i, (vc, vi_r) in enumerate(
            zip(self.result.output_vertices, inflate_result.output_vertices)
        ):
            v_orig = self.vertices[i]
            # crease_delta = -(inflate_delta) for positive strength
            for k in range(3):
                crease_delta = vc[k] - v_orig[k]
                inflate_delta = vi_r[k] - v_orig[k]
                assert crease_delta == pytest.approx(-inflate_delta, abs=1e-12)

    def test_vertices_outside_radius_unchanged(self):
        r = self.stroke.radius_mm
        pos = self.stroke.position_xyz_mm
        for i, v in enumerate(self.vertices):
            dist = math.sqrt(
                (v[0] - pos[0]) ** 2 + (v[1] - pos[1]) ** 2 + (v[2] - pos[2]) ** 2
            )
            if dist >= r:
                vo = self.result.output_vertices[i]
                for k in range(3):
                    assert vo[k] == pytest.approx(v[k], abs=1e-12)


# ---------------------------------------------------------------------------
# Test 3: Smooth brush — variance reduces on noisy mesh
# ---------------------------------------------------------------------------


class TestSmoothBrush:
    """GK-P22 T3: smooth brush reduces Z-variance."""

    def setup_method(self):
        self.vertices, self.faces = _noisy_plane(n=9, size=20.0, noise=2.0)
        self.stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=8.0,
            brush_type="smooth",
            strength=1.0,
        )
        self.result = apply_sculpt_brush(self.vertices, self.faces, self.stroke)

    def test_z_variance_reduces(self):
        z_in = [v[2] for v in self.vertices]
        z_out = [v[2] for v in self.result.output_vertices]
        var_in = statistics.variance(z_in)
        var_out = statistics.variance(z_out)
        assert var_out < var_in, (
            f"Smooth brush should reduce variance: {var_in:.4f} -> {var_out:.4f}"
        )

    def test_xy_coordinates_preserved(self):
        # Smooth only moves vertices in 3D toward the centroid; XY should shift too,
        # but if the mesh is sufficiently symmetric the net XY shift at the centre
        # should be minimal. Here we just verify XY is NOT catastrophically changed.
        for vo, vi in zip(self.result.output_vertices, self.vertices):
            dxy = math.sqrt((vo[0] - vi[0]) ** 2 + (vo[1] - vi[1]) ** 2)
            assert dxy < 2.0 * self.stroke.radius_mm, "XY shift is unexpectedly large"

    def test_smooth_strength_zero_no_change(self):
        stroke_zero = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=8.0,
            brush_type="smooth",
            strength=0.0,
        )
        result_zero = apply_sculpt_brush(self.vertices, self.faces, stroke_zero)
        for vo, vi in zip(result_zero.output_vertices, self.vertices):
            for k in range(3):
                assert vo[k] == pytest.approx(vi[k], abs=1e-12)


# ---------------------------------------------------------------------------
# Test 4: Pinch brush — vertices converge toward stroke centre
# ---------------------------------------------------------------------------


class TestPinchBrush:
    """GK-P22 T4: pinch brush attracts vertices toward stroke centre."""

    def setup_method(self):
        self.vertices, self.faces = _flat_plane_grid(n=7, size=20.0)
        self.stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=6.0,
            brush_type="pinch",
            strength=1.0,
        )
        self.result = apply_sculpt_brush(self.vertices, self.faces, self.stroke)

    def test_vertices_move_toward_centre(self):
        pos = self.stroke.position_xyz_mm
        r = self.stroke.radius_mm
        modified_count = 0
        for i, v in enumerate(self.vertices):
            dist = math.sqrt(sum((v[k] - pos[k]) ** 2 for k in range(3)))
            if dist < r and dist > 1e-9:
                vo = self.result.output_vertices[i]
                dist_after = math.sqrt(sum((vo[k] - pos[k]) ** 2 for k in range(3)))
                assert dist_after < dist + 1e-10, (
                    f"Pinch should move vertex closer to centre: {dist:.3f} -> {dist_after:.3f}"
                )
                modified_count += 1
        assert modified_count > 0, "No vertices were pinched"

    def test_pinch_negative_strength_repels(self):
        # Negative strength should push vertices away from the brush centre
        repel_stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=6.0,
            brush_type="pinch",
            strength=-1.0,
        )
        result_repel = apply_sculpt_brush(self.vertices, self.faces, repel_stroke)
        pos = repel_stroke.position_xyz_mm
        r = repel_stroke.radius_mm
        moved_away = 0
        for i, v in enumerate(self.vertices):
            dist = math.sqrt(sum((v[k] - pos[k]) ** 2 for k in range(3)))
            if dist < r and dist > 1e-9:
                vo = result_repel.output_vertices[i]
                dist_after = math.sqrt(sum((vo[k] - pos[k]) ** 2 for k in range(3)))
                if dist_after > dist:
                    moved_away += 1
        assert moved_away > 0, "No vertices were repelled by negative-strength pinch"

    def test_outside_radius_unchanged(self):
        r = self.stroke.radius_mm
        pos = self.stroke.position_xyz_mm
        for i, v in enumerate(self.vertices):
            dist = math.sqrt(sum((v[k] - pos[k]) ** 2 for k in range(3)))
            if dist >= r:
                vo = self.result.output_vertices[i]
                for k in range(3):
                    assert vo[k] == pytest.approx(v[k], abs=1e-12)


# ---------------------------------------------------------------------------
# Test 5: Out-of-radius vertices are strictly unchanged
# ---------------------------------------------------------------------------


class TestOutOfRadiusUnchanged:
    """GK-P22 T5: vertices outside brush radius must not be modified."""

    def test_tiny_radius_only_centre_vertex_touched(self):
        vertices, faces = _flat_plane_grid(n=5, size=10.0)
        # Use a very small radius so only the centre vertex is inside
        centre = (0.0, 0.0, 0.0)
        tiny_r = 0.01  # 0.01 mm — only the vertex exactly at origin qualifies
        stroke = SculptStroke(
            position_xyz_mm=centre,
            radius_mm=tiny_r,
            brush_type="inflate",
            strength=1.0,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        r = tiny_r
        pos = centre
        for i, v in enumerate(vertices):
            dist = math.sqrt(sum((v[k] - pos[k]) ** 2 for k in range(3)))
            vo = result.output_vertices[i]
            if dist >= r:
                for k in range(3):
                    assert vo[k] == pytest.approx(v[k], abs=1e-12), (
                        f"Vertex {i} at dist={dist:.5f} was unexpectedly modified"
                    )

    def test_large_radius_modifies_all_vertices(self):
        vertices, faces = _flat_plane_grid(n=5, size=10.0)
        # Radius larger than the mesh extent
        stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=100.0,
            brush_type="inflate",
            strength=0.5,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        assert result.num_vertices_modified == len(vertices)


# ---------------------------------------------------------------------------
# Test 6: Falloff — boundary vertex displacement approaches zero
# ---------------------------------------------------------------------------


class TestWendlandFalloff:
    """GK-P22 T6: Wendland C2 falloff w(t) → 0 as t → 1."""

    def test_falloff_at_boundary_is_zero(self):
        from kerf_cad_core.mesh_sculpt_brushes import _wendland_c2
        assert _wendland_c2(1.0) == pytest.approx(0.0, abs=1e-12)
        assert _wendland_c2(0.999) == pytest.approx(
            (1.0 - 0.999 ** 2) ** 2, rel=1e-9
        )

    def test_falloff_at_centre_is_one(self):
        from kerf_cad_core.mesh_sculpt_brushes import _wendland_c2
        assert _wendland_c2(0.0) == pytest.approx(1.0, abs=1e-12)

    def test_falloff_monotonically_decreasing(self):
        from kerf_cad_core.mesh_sculpt_brushes import _wendland_c2
        prev = _wendland_c2(0.0)
        for ti in range(1, 11):
            t = ti / 10.0
            curr = _wendland_c2(t)
            assert curr <= prev + 1e-12
            prev = curr

    def test_vertex_at_exact_radius_zero_displacement(self):
        # Place a vertex at exactly radius_mm from the brush centre
        r = 5.0
        vertices = [(r, 0.0, 0.0), (r + 1.0, 0.0, 0.0)]
        faces = [[0, 1]]
        stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=r,
            brush_type="inflate",
            strength=1.0,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        # vertex 0 is AT the boundary — w(1) = 0 so displacement = 0
        for k in range(3):
            assert result.output_vertices[0][k] == pytest.approx(vertices[0][k], abs=1e-12)


# ---------------------------------------------------------------------------
# Test 7: Inflate with strength sign
# ---------------------------------------------------------------------------


class TestInflateStrengthSign:
    """GK-P22 T7: inflate +strength → up, -strength → down."""

    def _centre_delta_z(self, strength):
        vertices, faces = _flat_plane_grid(n=5, size=10.0)
        stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=3.0,
            brush_type="inflate",
            strength=strength,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        centre_idx = next(
            i for i, v in enumerate(vertices) if abs(v[0]) < 1e-9 and abs(v[1]) < 1e-9
        )
        return result.output_vertices[centre_idx][2] - vertices[centre_idx][2]

    def test_positive_strength_inflates_upward(self):
        dz = self._centre_delta_z(1.0)
        assert dz > 0.0, f"Positive strength should inflate upward, got dz={dz}"

    def test_negative_strength_deflates(self):
        dz = self._centre_delta_z(-1.0)
        assert dz < 0.0, f"Negative strength should deflate, got dz={dz}"

    def test_opposite_strengths_are_symmetric(self):
        dz_pos = self._centre_delta_z(0.5)
        dz_neg = self._centre_delta_z(-0.5)
        assert dz_pos == pytest.approx(-dz_neg, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 8: Normal override for inflate
# ---------------------------------------------------------------------------


class TestNormalOverride:
    """GK-P22 T8: normal_direction_xyz overrides per-vertex normals for inflate."""

    def test_override_axis_x(self):
        vertices, faces = _flat_plane_grid(n=5, size=10.0)
        stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=3.0,
            brush_type="inflate",
            strength=1.0,
            normal_direction_xyz=(1.0, 0.0, 0.0),
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        # The centre vertex should move in +X, not +Z
        centre_idx = next(
            i for i, v in enumerate(vertices) if abs(v[0]) < 1e-9 and abs(v[1]) < 1e-9
        )
        dx = result.output_vertices[centre_idx][0] - vertices[centre_idx][0]
        dz = result.output_vertices[centre_idx][2] - vertices[centre_idx][2]
        assert dx > 0.5, f"Expected X displacement with override, got dx={dx}"
        assert abs(dz) < 1e-10, f"Expected no Z displacement with X override, got dz={dz}"


# ---------------------------------------------------------------------------
# Test 9: All four brush types on minimal mesh (cube cage)
# ---------------------------------------------------------------------------


class TestAllBrushTypesOnCube:
    """GK-P22 T9: all four brush types run without error on a cube cage."""

    def test_all_brush_types_run(self):
        vertices, faces = _cube_cage()
        for btype in ("inflate", "crease", "smooth", "pinch"):
            stroke = SculptStroke(
                position_xyz_mm=(0.5, 0.5, 0.5),
                radius_mm=2.0,
                brush_type=btype,
                strength=0.5,
            )
            result = apply_sculpt_brush(vertices, faces, stroke)
            assert isinstance(result, MeshSculptResult)
            assert result.brush_type_applied == btype
            assert len(result.output_vertices) == len(vertices)


# ---------------------------------------------------------------------------
# Test 10: Reproducibility
# ---------------------------------------------------------------------------


class TestReproducibility:
    """GK-P22 T10: same inputs → identical outputs (deterministic)."""

    def test_identical_results_on_repeated_calls(self):
        vertices, faces = _flat_plane_grid(n=5, size=10.0)
        stroke = SculptStroke(
            position_xyz_mm=(1.0, 1.0, 0.0),
            radius_mm=4.0,
            brush_type="smooth",
            strength=0.8,
        )
        r1 = apply_sculpt_brush(vertices, faces, stroke)
        r2 = apply_sculpt_brush(vertices, faces, stroke)
        for v1, v2 in zip(r1.output_vertices, r2.output_vertices):
            for k in range(3):
                assert v1[k] == v2[k]


# ---------------------------------------------------------------------------
# Test 11: SculptStroke defaults
# ---------------------------------------------------------------------------


class TestSculptStrokeDefaults:
    """GK-P22 T11: SculptStroke.normal_direction_xyz defaults to None."""

    def test_default_normal_is_none(self):
        s = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=5.0,
            brush_type="inflate",
            strength=0.5,
        )
        assert s.normal_direction_xyz is None


# ---------------------------------------------------------------------------
# Test 12: Validation errors
# ---------------------------------------------------------------------------


class TestValidationErrors:
    """GK-P22 T12: invalid parameters raise ValueError."""

    def test_invalid_brush_type_raises(self):
        vertices, faces = _cube_cage()
        stroke = SculptStroke(
            position_xyz_mm=(0.5, 0.5, 0.5),
            radius_mm=2.0,
            brush_type="warp",  # invalid
            strength=0.5,
        )
        with pytest.raises(ValueError, match="brush_type"):
            apply_sculpt_brush(vertices, faces, stroke)

    def test_zero_radius_raises(self):
        vertices, faces = _cube_cage()
        stroke = SculptStroke(
            position_xyz_mm=(0.5, 0.5, 0.5),
            radius_mm=0.0,
            brush_type="inflate",
            strength=0.5,
        )
        with pytest.raises(ValueError, match="radius"):
            apply_sculpt_brush(vertices, faces, stroke)

    def test_negative_radius_raises(self):
        vertices, faces = _cube_cage()
        stroke = SculptStroke(
            position_xyz_mm=(0.5, 0.5, 0.5),
            radius_mm=-1.0,
            brush_type="inflate",
            strength=0.5,
        )
        with pytest.raises(ValueError, match="radius"):
            apply_sculpt_brush(vertices, faces, stroke)


# ---------------------------------------------------------------------------
# Test 13: MeshSculptResult fields are populated correctly
# ---------------------------------------------------------------------------


class TestMeshSculptResultFields:
    """GK-P22 T13: MeshSculptResult fields are correctly populated."""

    def test_result_fields_consistent(self):
        vertices, faces = _flat_plane_grid(n=5, size=10.0)
        stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=5.0,
            brush_type="inflate",
            strength=1.0,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        assert result.num_vertices_modified >= 1
        assert result.max_displacement_mm >= result.mean_displacement_mm
        assert result.mean_displacement_mm >= 0.0
        assert result.brush_type_applied == "inflate"
        assert "GK-P22" in result.honest_caveat

    def test_no_vertices_modified_gives_zero_stats(self):
        # Brush far away from all vertices
        vertices, faces = _cube_cage()
        stroke = SculptStroke(
            position_xyz_mm=(1000.0, 1000.0, 1000.0),
            radius_mm=0.001,
            brush_type="inflate",
            strength=1.0,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        assert result.num_vertices_modified == 0
        assert result.max_displacement_mm == pytest.approx(0.0)
        assert result.mean_displacement_mm == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Helpers for Taubin tests
# ---------------------------------------------------------------------------


def _icosphere(radius: float = 5.0, subdivisions: int = 2):
    """Generate a triangulated icosphere as (vertices, faces).

    Starts from a regular icosahedron and subdivides each triangle into 4
    sub-triangles ``subdivisions`` times.  All vertices are projected back onto
    the sphere of the given *radius* after each subdivision.

    Used for volume-preservation and shrinkage tests (a sphere has analytic
    properties: volume = 4/3 π r³, centroid = origin).
    """
    # Golden ratio
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    # 12 vertices of a regular icosahedron
    raw = [
        (-1,  phi, 0), ( 1,  phi, 0), (-1, -phi, 0), ( 1, -phi, 0),
        (0, -1,  phi), (0,  1,  phi), (0, -1, -phi), (0,  1, -phi),
        ( phi, 0, -1), ( phi, 0,  1), (-phi, 0, -1), (-phi, 0,  1),
    ]
    def norm_to_r(v):
        l = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
        return (v[0]/l*radius, v[1]/l*radius, v[2]/l*radius)

    vertices = [norm_to_r(v) for v in raw]
    faces = [
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
    ]

    edge_midpoints: dict = {}

    def midpoint_idx(a, b):
        key = (min(a, b), max(a, b))
        if key not in edge_midpoints:
            va = vertices[a]
            vb = vertices[b]
            mid = ((va[0]+vb[0])/2, (va[1]+vb[1])/2, (va[2]+vb[2])/2)
            edge_midpoints[key] = len(vertices)
            vertices.append(norm_to_r(mid))
        return edge_midpoints[key]

    for _ in range(subdivisions):
        new_faces = []
        edge_midpoints.clear()
        for tri in faces:
            a, b, c = tri
            ab = midpoint_idx(a, b)
            bc = midpoint_idx(b, c)
            ca = midpoint_idx(c, a)
            new_faces += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]
        faces = new_faces

    return vertices, faces


def _mesh_volume(vertices, faces):
    """Compute signed mesh volume via the divergence theorem (triangle faces only).

    V = (1/6) Σ (v0 · (v1 × v2))  — exact for closed triangle meshes.
    """
    total = 0.0
    for face in faces:
        if len(face) != 3:
            continue
        v0 = vertices[face[0]]
        v1 = vertices[face[1]]
        v2 = vertices[face[2]]
        # Scalar triple product
        total += (
            v0[0] * (v1[1] * v2[2] - v1[2] * v2[1])
            + v0[1] * (v1[2] * v2[0] - v1[0] * v2[2])
            + v0[2] * (v1[0] * v2[1] - v1[1] * v2[0])
        )
    return abs(total) / 6.0


def _add_sphere_noise(vertices, noise_amp: float = 0.3):
    """Add per-vertex radial noise to a sphere mesh (reproducible seed)."""
    import random
    rng = random.Random(7)
    result = []
    for v in vertices:
        r = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
        if r < 1e-12:
            result.append(v)
            continue
        dr = rng.uniform(-noise_amp, noise_amp)
        scale = (r + dr) / r
        result.append((v[0]*scale, v[1]*scale, v[2]*scale))
    return result


# ---------------------------------------------------------------------------
# Test 14: smooth-taubin on noisy sphere — variance reduces, volume preserved
# ---------------------------------------------------------------------------


class TestSmoothTaubinNoisySphere:
    """GK-P22 T14: smooth-taubin reduces noise while preserving volume.

    Criteria:
    - Z-variance (and total-radius variance) decreases after one brush pass.
    - Volume of the smoothed sphere is within 1% of the input volume.
      (Taubin λ|μ is specifically designed to prevent shrinkage.)
    """

    def setup_method(self):
        self.sphere_verts, self.faces = _icosphere(radius=10.0, subdivisions=2)
        self.noisy_verts = _add_sphere_noise(self.sphere_verts, noise_amp=1.5)
        self.stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=20.0,  # covers the whole sphere
            brush_type="smooth-taubin",
            strength=1.0,
        )
        self.result = apply_sculpt_brush(self.noisy_verts, self.faces, self.stroke)

    def test_radius_variance_reduces(self):
        """Radial variance (noise indicator) should decrease after Taubin pass."""
        def radii(verts):
            return [math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in verts]

        r_in = radii(self.noisy_verts)
        r_out = radii(self.result.output_vertices)
        var_in = statistics.variance(r_in)
        var_out = statistics.variance(r_out)
        assert var_out < var_in, (
            f"smooth-taubin should reduce radius variance: {var_in:.6f} -> {var_out:.6f}"
        )

    def test_volume_preserved_within_1_percent(self):
        """Volume must be preserved within 1% (Taubin anti-shrink guarantee)."""
        vol_in = _mesh_volume(self.noisy_verts, self.faces)
        vol_out = _mesh_volume(self.result.output_vertices, self.faces)
        assert vol_in > 0.0, "Input volume should be positive"
        assert vol_out > 0.0, "Output volume should be positive"
        rel_diff = abs(vol_out - vol_in) / vol_in
        assert rel_diff < 0.01, (
            f"Volume changed by {rel_diff*100:.3f}% (must be < 1%): "
            f"in={vol_in:.4f}, out={vol_out:.4f}"
        )

    def test_output_vertex_count_unchanged(self):
        assert len(self.result.output_vertices) == len(self.noisy_verts)

    def test_brush_type_applied_echo(self):
        assert self.result.brush_type_applied == "smooth-taubin"

    def test_num_vertices_modified_positive(self):
        assert self.result.num_vertices_modified > 0


# ---------------------------------------------------------------------------
# Test 15: smooth-taubin vs smooth-naive — Taubin has less shrink
# ---------------------------------------------------------------------------


class TestTaubinVsNaiveShrink:
    """GK-P22 T15: smooth-taubin causes less mesh shrinkage than smooth.

    After multiple repeated brush passes over the full mesh, the Taubin variant
    should produce a centroid closer to the origin (less shrink) compared to
    repeated naive Laplacian smoothing.
    """

    def _apply_n_passes(self, vertices, faces, brush_type, n=5):
        """Apply the same full-coverage brush n times in sequence."""
        verts = list(vertices)
        for _ in range(n):
            stroke = SculptStroke(
                position_xyz_mm=(0.0, 0.0, 0.0),
                radius_mm=20.0,
                brush_type=brush_type,
                strength=1.0,
            )
            result = apply_sculpt_brush(verts, faces, stroke)
            verts = list(result.output_vertices)
        return verts

    def _mean_radius(self, verts):
        return sum(
            math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in verts
        ) / len(verts)

    def test_taubin_preserves_mean_radius_better(self):
        """After 5 full-mesh passes, Taubin mean radius > naive mean radius."""
        sphere_verts, faces = _icosphere(radius=10.0, subdivisions=2)
        noisy_verts = _add_sphere_noise(sphere_verts, noise_amp=1.0)

        taubin_verts = self._apply_n_passes(noisy_verts, faces, "smooth-taubin", n=5)
        naive_verts = self._apply_n_passes(noisy_verts, faces, "smooth", n=5)

        mean_r_taubin = self._mean_radius(taubin_verts)
        mean_r_naive = self._mean_radius(naive_verts)
        mean_r_input = self._mean_radius(noisy_verts)

        # Taubin should be closer to the original mean radius than naive
        shrink_taubin = abs(mean_r_input - mean_r_taubin)
        shrink_naive = abs(mean_r_input - mean_r_naive)
        assert shrink_taubin < shrink_naive, (
            f"Taubin shrink={shrink_taubin:.4f} should be < naive shrink={shrink_naive:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 16: _taubin_smooth_one_pass low-pass effect (standalone helper)
# ---------------------------------------------------------------------------


class TestTaubinSmoothOnePassLowPass:
    """GK-P22 T16: _taubin_smooth_one_pass() applies a low-pass filter."""

    def test_single_call_reduces_high_freq(self):
        """High-frequency Z noise should be attenuated after one full pass."""
        verts, faces = _flat_plane_grid(n=11, size=20.0)
        # Add alternating +/- high-frequency noise in Z
        noisy = []
        for idx, v in enumerate(verts):
            sign = 1 if idx % 2 == 0 else -1
            noisy.append((v[0], v[1], v[2] + sign * 1.0))

        smoothed = _taubin_smooth_one_pass(noisy, faces)

        z_in = [v[2] for v in noisy]
        z_out = [v[2] for v in smoothed]
        var_in = statistics.variance(z_in)
        var_out = statistics.variance(z_out)
        assert var_out < var_in, (
            f"Taubin one pass should reduce Z variance: {var_in:.4f} -> {var_out:.4f}"
        )

    def test_smooth_mesh_not_distorted(self):
        """A perfectly flat mesh should remain nearly flat after a Taubin pass."""
        verts, faces = _flat_plane_grid(n=7, size=10.0)
        smoothed = _taubin_smooth_one_pass(verts, faces)
        # Z values of a flat mesh are all 0; after Taubin they should stay ~0
        for v in smoothed:
            assert abs(v[2]) < 1e-10, f"Flat mesh Z drifted to {v[2]}"


# ---------------------------------------------------------------------------
# Test 17: Two-pass (λ + μ) — no DC shift on smooth mesh
# ---------------------------------------------------------------------------


class TestTaubinTwoPassNoDCShift:
    """GK-P22 T17: Taubin λ|μ two-pass has minimal DC (mean) shift.

    A single positive-λ pass shifts the mesh centroid (shrinks it).  The
    subsequent negative-μ pass corrects that.  On a sphere the mean radius
    should be closer to the original after two passes than after one pass only.
    """

    def test_two_pass_dc_shift_smaller_than_one_pass(self):
        """Mean radius change after λ+μ < mean radius change after λ alone."""
        sphere_verts, faces = _icosphere(radius=8.0, subdivisions=2)
        noisy_verts = _add_sphere_noise(sphere_verts, noise_amp=0.8)

        from kerf_cad_core.mesh_sculpt_brushes import _build_cotangent_weights

        # Manually replicate the two internal passes from _taubin_smooth_one_pass
        cot_w = _build_cotangent_weights(noisy_verts, faces)
        nv = len(noisy_verts)

        def _one_laplacian(verts, step):
            out = list(verts)
            for i in range(nv):
                pairs = cot_w[i]
                if not pairs:
                    continue
                total_w = sum(w for _, w in pairs)
                if total_w < 1e-14:
                    continue
                inv_w = 1.0 / total_w
                vi = verts[i]
                dx = dy = dz = 0.0
                for j, w in pairs:
                    vj = verts[j]
                    nw = w * inv_w
                    dx += nw * (vj[0] - vi[0])
                    dy += nw * (vj[1] - vi[1])
                    dz += nw * (vj[2] - vi[2])
                out[i] = (vi[0] + step*dx, vi[1] + step*dy, vi[2] + step*dz)
            return out

        def mean_r(verts):
            return sum(
                math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in verts
            ) / len(verts)

        mean_r_in = mean_r(noisy_verts)

        after_lambda = _one_laplacian(noisy_verts, 0.5)
        after_mu = _one_laplacian(after_lambda, -0.53)

        shift_one_pass = abs(mean_r(after_lambda) - mean_r_in)
        shift_two_pass = abs(mean_r(after_mu) - mean_r_in)

        assert shift_two_pass < shift_one_pass, (
            f"Two-pass DC shift {shift_two_pass:.6f} should be < "
            f"one-pass DC shift {shift_one_pass:.6f}"
        )


# ---------------------------------------------------------------------------
# Test 18: smooth-taubin out-of-radius vertices unchanged
# ---------------------------------------------------------------------------


class TestSmoothTaubinOutOfRadius:
    """GK-P22 T18: smooth-taubin leaves out-of-radius vertices unchanged."""

    def test_out_of_radius_vertices_not_moved(self):
        vertices, faces = _flat_plane_grid(n=7, size=20.0)
        # Tiny radius: only the exact-origin vertex is inside
        stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=0.5,
            brush_type="smooth-taubin",
            strength=1.0,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        r = stroke.radius_mm
        pos = stroke.position_xyz_mm
        for i, v in enumerate(vertices):
            dist = math.sqrt(sum((v[k] - pos[k])**2 for k in range(3)))
            if dist >= r:
                vo = result.output_vertices[i]
                for k in range(3):
                    assert vo[k] == pytest.approx(v[k], abs=1e-12), (
                        f"Vertex {i} at dist={dist:.4f} was moved by smooth-taubin"
                    )


# ---------------------------------------------------------------------------
# Test 19: smooth-taubin strength=0 → no change
# ---------------------------------------------------------------------------


class TestSmoothTaubinStrengthZero:
    """GK-P22 T19: smooth-taubin with strength=0 must not move any vertex."""

    def test_strength_zero_no_change(self):
        vertices, faces = _noisy_plane(n=7, size=10.0, noise=1.0)
        stroke = SculptStroke(
            position_xyz_mm=(0.0, 0.0, 0.0),
            radius_mm=20.0,
            brush_type="smooth-taubin",
            strength=0.0,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        for vo, vi in zip(result.output_vertices, vertices):
            for k in range(3):
                assert vo[k] == pytest.approx(vi[k], abs=1e-12), (
                    "smooth-taubin with strength=0 should not move vertices"
                )


# ---------------------------------------------------------------------------
# Test 20: _taubin_smooth_one_pass degenerate / isolated vertices
# ---------------------------------------------------------------------------


class TestTaubinDegenerateInputs:
    """GK-P22 T20: _taubin_smooth_one_pass handles degenerate cases gracefully."""

    def test_single_triangle_no_crash(self):
        """A single isolated triangle should run without raising."""
        verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0)]
        faces = [[0, 1, 2]]
        result = _taubin_smooth_one_pass(verts, faces)
        assert len(result) == 3

    def test_zero_area_triangle_no_nan(self):
        """Degenerate (collinear) triangle must not produce NaN/Inf."""
        # All three vertices collinear — zero area
        verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        faces = [[0, 1, 2]]
        result = _taubin_smooth_one_pass(verts, faces)
        assert len(result) == 3
        for v in result:
            for coord in v:
                assert math.isfinite(coord), f"Got non-finite coordinate: {coord}"

    def test_output_length_matches_input(self):
        """Output vertex list must have the same length as input."""
        verts, faces = _flat_plane_grid(n=5, size=10.0)
        result = _taubin_smooth_one_pass(verts, faces)
        assert len(result) == len(verts)

    def test_default_lambda_mu(self):
        """Default λ=0.5, μ=-0.53 should smooth a noisy mesh."""
        verts, faces = _noisy_plane(n=9, size=20.0, noise=2.0)
        result = _taubin_smooth_one_pass(verts, faces)
        z_in = [v[2] for v in verts]
        z_out = [v[2] for v in result]
        var_in = statistics.variance(z_in)
        var_out = statistics.variance(z_out)
        assert var_out < var_in, "Default Taubin pass should reduce noise variance"


# ---------------------------------------------------------------------------
# Test 21: All five brush types (including smooth-taubin) validated
# ---------------------------------------------------------------------------


class TestAllFiveBrushTypesOnCube:
    """GK-P22 T21: all five brush types including smooth-taubin run without error."""

    def test_smooth_taubin_runs_on_cube(self):
        vertices, faces = _cube_cage()
        stroke = SculptStroke(
            position_xyz_mm=(0.5, 0.5, 0.5),
            radius_mm=2.0,
            brush_type="smooth-taubin",
            strength=0.5,
        )
        result = apply_sculpt_brush(vertices, faces, stroke)
        assert isinstance(result, MeshSculptResult)
        assert result.brush_type_applied == "smooth-taubin"
        assert len(result.output_vertices) == len(vertices)

    def test_invalid_brush_type_still_raises(self):
        """Adding smooth-taubin should not accidentally accept other invalid types."""
        vertices, faces = _cube_cage()
        stroke = SculptStroke(
            position_xyz_mm=(0.5, 0.5, 0.5),
            radius_mm=2.0,
            brush_type="taubin",  # wrong — must be "smooth-taubin"
            strength=0.5,
        )
        with pytest.raises(ValueError, match="brush_type"):
            apply_sculpt_brush(vertices, faces, stroke)
