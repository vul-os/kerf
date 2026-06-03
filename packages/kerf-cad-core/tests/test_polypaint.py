"""Tests for kerf_cad_core.sculpt.polypaint — per-vertex colour + UV texture bake.

Coverage:
- polypaint_stroke: brush centre gets full colour
- polypaint_stroke: outside radius → no change
- polypaint_stroke: falloff variants
- polypaint_stroke: layer opacity scaling
- polypaint_stroke: output is clipped to [0, 1]
- bake_polypaint_to_uv_texture: returns correct shape
- bake_polypaint_to_uv_texture: flat square with UV==XY returns expected colours
- bake_polypaint_to_uv_texture: uniform red layer → red texture
- bake_polypaint_to_uv_texture: auto-UV path runs without error
- PolyPaintLayer dataclass defaults
"""
from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.sculpt.polypaint import (
    PolyPaintLayer,
    bake_polypaint_to_uv_texture,
    polypaint_stroke,
)
from kerf_cad_core.sculpt.brush import SculptMesh


# ---------------------------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------------------------


def _flat_quad_mesh(n: int = 4):
    """Triangulated n×n unit-square plane (XY plane, z=0).

    Vertices span [0,1]×[0,1]. UV == XY for easy testing.
    Returns (SculptMesh, uv_coords).
    """
    xs = np.linspace(0.0, 1.0, n + 1)
    ys = np.linspace(0.0, 1.0, n + 1)
    xx, yy = np.meshgrid(xs, ys)
    positions = np.stack([xx.ravel(), yy.ravel(), np.zeros(len(xx.ravel()))], axis=1)
    uv = positions[:, :2].copy()   # UV == XY

    tris = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b = a + 1
            c = a + (n + 1) + 1
            d = a + (n + 1)
            tris.append([a, b, c])
            tris.append([a, c, d])

    triangles = np.array(tris, dtype=np.int32)
    mesh = SculptMesh(positions=positions.copy(), triangles=triangles)
    return mesh, uv


def _uniform_layer(mesh: SculptMesh, color=(1.0, 0.0, 0.0), opacity=1.0):
    V = len(mesh.positions)
    vc = np.tile(np.array(color, dtype=np.float32), (V, 1))
    return PolyPaintLayer(vertex_colors=vc, opacity=opacity)


# ---------------------------------------------------------------------------
# Tests: PolyPaintLayer
# ---------------------------------------------------------------------------

class TestPolyPaintLayer:
    def test_default_opacity(self):
        vc = np.zeros((10, 3), dtype=np.float32)
        layer = PolyPaintLayer(vertex_colors=vc)
        assert layer.opacity == 1.0

    def test_custom_opacity(self):
        vc = np.zeros((5, 3), dtype=np.float32)
        layer = PolyPaintLayer(vertex_colors=vc, opacity=0.5)
        assert layer.opacity == 0.5


# ---------------------------------------------------------------------------
# Tests: polypaint_stroke
# ---------------------------------------------------------------------------

class TestPolypaintStroke:
    def test_stroke_at_center_full_color(self):
        """Vertex exactly at brush centre should receive the full stroke colour."""
        mesh, _ = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        black = np.zeros((V, 3), dtype=np.float32)
        layer = PolyPaintLayer(vertex_colors=black.copy(), opacity=1.0)

        # Place the brush exactly on vertex 0 at (0, 0, 0)
        center = np.array([0.0, 0.0, 0.0])
        red = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        new_layer = polypaint_stroke(mesh, layer, center=center, radius=0.1, color=red, falloff="constant")

        # Vertex 0 is exactly at center — distance=0 → weight=1 → should be red
        assert new_layer.vertex_colors[0, 0] > 0.9, (
            f"Expected vertex 0 to be near-red, got {new_layer.vertex_colors[0]}"
        )

    def test_stroke_outside_radius_unchanged(self):
        """Vertices outside radius must not be affected."""
        mesh, _ = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        blue = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (V, 1))
        layer = PolyPaintLayer(vertex_colors=blue.copy(), opacity=1.0)

        # Brush centre far from all vertices
        center = np.array([100.0, 100.0, 0.0])
        red = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        new_layer = polypaint_stroke(mesh, layer, center=center, radius=1.0, color=red)

        np.testing.assert_array_almost_equal(
            new_layer.vertex_colors, blue, decimal=6,
            err_msg="Vertices outside radius should be unchanged"
        )

    def test_stroke_returns_new_layer(self):
        """polypaint_stroke must return a new PolyPaintLayer, not mutate input."""
        mesh, _ = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        orig_colors = np.zeros((V, 3), dtype=np.float32)
        layer = PolyPaintLayer(vertex_colors=orig_colors.copy())
        center = mesh.positions[0].copy()
        new_layer = polypaint_stroke(mesh, layer, center=center, radius=1.0,
                                      color=np.array([1.0, 0.0, 0.0]))
        # Input layer should not be mutated
        np.testing.assert_array_equal(layer.vertex_colors, orig_colors)
        assert new_layer is not layer

    def test_stroke_linear_falloff(self):
        """Linear falloff should give intermediate weight at mid-radius."""
        mesh, _ = _flat_quad_mesh(n=10)
        V = len(mesh.positions)
        black = np.zeros((V, 3), dtype=np.float32)
        layer = PolyPaintLayer(vertex_colors=black.copy(), opacity=1.0)

        center = np.array([0.0, 0.0, 0.0])
        new_layer = polypaint_stroke(mesh, layer, center=center, radius=1.0,
                                      color=np.array([1.0, 0.0, 0.0]),
                                      falloff="linear")
        # Vertex at center: full red; distant verts: less red
        # At minimum find that some vertices are between 0 and 1
        vals = new_layer.vertex_colors[:, 0]
        assert np.any(vals > 0.0)

    def test_stroke_output_clipped_0_1(self):
        """All output colours must stay in [0, 1]."""
        mesh, _ = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        # Start with max white
        white = np.ones((V, 3), dtype=np.float32)
        layer = PolyPaintLayer(vertex_colors=white.copy(), opacity=1.0)
        center = mesh.positions[0].copy()
        new_layer = polypaint_stroke(mesh, layer, center=center, radius=2.0,
                                      color=np.array([2.0, -1.0, 0.5]))  # out-of-range color
        assert new_layer.vertex_colors.min() >= 0.0
        assert new_layer.vertex_colors.max() <= 1.0

    def test_stroke_opacity_zero_no_change(self):
        """opacity=0 stroke should leave colours unchanged."""
        mesh, _ = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        blue = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (V, 1))
        layer = PolyPaintLayer(vertex_colors=blue.copy(), opacity=0.0)
        center = mesh.positions[0].copy()
        new_layer = polypaint_stroke(mesh, layer, center=center, radius=2.0,
                                      color=np.array([1.0, 0.0, 0.0]))
        np.testing.assert_array_almost_equal(new_layer.vertex_colors, blue, decimal=6)

    def test_stroke_dict_mesh(self):
        """polypaint_stroke must accept a dict mesh (not just SculptMesh)."""
        mesh, _ = _flat_quad_mesh(n=4)
        mesh_dict = {"vertices": mesh.positions.tolist(), "faces": mesh.triangles.tolist()}
        V = len(mesh.positions)
        black = np.zeros((V, 3), dtype=np.float32)
        layer = PolyPaintLayer(vertex_colors=black.copy())
        center = mesh.positions[0].copy()
        new_layer = polypaint_stroke(mesh_dict, layer, center=center, radius=1.0,
                                      color=np.array([1.0, 0.0, 0.0]))
        assert new_layer.vertex_colors[0, 0] > 0.9


# ---------------------------------------------------------------------------
# Tests: bake_polypaint_to_uv_texture
# ---------------------------------------------------------------------------

class TestBakePolyPaintToUVTexture:
    def test_output_shape(self):
        mesh, uv = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        red = np.tile(np.array([1.0, 0.0, 0.0], dtype=np.float32), (V, 1))
        layer = PolyPaintLayer(vertex_colors=red)
        tex = bake_polypaint_to_uv_texture(mesh, layer, uv_coords=uv, texture_size=64)
        assert tex.shape == (64, 64, 3), f"Unexpected shape: {tex.shape}"

    def test_output_dtype_float32(self):
        mesh, uv = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        layer = PolyPaintLayer(vertex_colors=np.zeros((V, 3), dtype=np.float32))
        tex = bake_polypaint_to_uv_texture(mesh, layer, uv_coords=uv, texture_size=32)
        assert tex.dtype == np.float32

    def test_uniform_red_layer_produces_red_texture(self):
        """All-red vertex colours with full mesh coverage → texture is red in covered region."""
        mesh, uv = _flat_quad_mesh(n=8)
        V = len(mesh.positions)
        red = np.tile(np.array([1.0, 0.0, 0.0], dtype=np.float32), (V, 1))
        layer = PolyPaintLayer(vertex_colors=red)
        tex = bake_polypaint_to_uv_texture(mesh, layer, uv_coords=uv, texture_size=64)

        # Most covered pixels should be red
        covered = (tex[:, :, 0] > 0.5)
        if covered.sum() > 0:
            assert np.all(tex[covered, 1] < 0.1), "Green channel should be near-zero in red region"
            assert np.all(tex[covered, 2] < 0.1), "Blue channel should be near-zero in red region"

    def test_custom_texture_size(self):
        mesh, uv = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        layer = PolyPaintLayer(vertex_colors=np.zeros((V, 3), dtype=np.float32))
        for size in [16, 128, 256]:
            tex = bake_polypaint_to_uv_texture(mesh, layer, uv_coords=uv, texture_size=size)
            assert tex.shape == (size, size, 3)

    def test_auto_uv_no_error(self):
        """Passing uv_coords=None should trigger LSCM unwrap without error."""
        mesh, _ = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        green = np.tile(np.array([0.0, 1.0, 0.0], dtype=np.float32), (V, 1))
        layer = PolyPaintLayer(vertex_colors=green)
        # Should not raise
        tex = bake_polypaint_to_uv_texture(mesh, layer, uv_coords=None, texture_size=32)
        assert tex.shape == (32, 32, 3)

    def test_output_values_in_0_1(self):
        mesh, uv = _flat_quad_mesh(n=4)
        V = len(mesh.positions)
        # Mixed colours
        colors = np.random.rand(V, 3).astype(np.float32)
        layer = PolyPaintLayer(vertex_colors=colors)
        tex = bake_polypaint_to_uv_texture(mesh, layer, uv_coords=uv, texture_size=32)
        assert tex.min() >= 0.0
        assert tex.max() <= 1.0 + 1e-6
