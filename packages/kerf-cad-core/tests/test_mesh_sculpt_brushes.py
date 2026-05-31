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
"""

from __future__ import annotations

import math
import statistics

import pytest

from kerf_cad_core.mesh_sculpt_brushes import (
    MeshSculptResult,
    SculptStroke,
    apply_sculpt_brush,
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
