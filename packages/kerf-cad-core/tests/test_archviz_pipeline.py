"""
Tests for kerf_cad_core.render.archviz_pipeline.

Coverage:
  make_simple_room_scene — creates valid ArchVizScene with geometry
  render_archviz         — returns (H, W, 3) uint8 image of correct shape
  render_archviz         — image is not all black (some photons/shading)
  _ray_triangle_intersect — Möller-Trumbore hit/miss cases
  _material_brdf          — BRDF returns RGB of length 3

References
----------
Jensen (1996) — photon mapping.
Pharr, Jakob, Humphreys (2023) §5 — camera model.
Möller & Trumbore (1997) — ray/triangle intersection.
Reinhard et al. (2002) — tone mapping.

Author: imranparuk
"""
from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.render.archviz_pipeline import (
    ArchVizScene,
    _material_brdf,
    _ray_triangle_intersect,
    make_simple_room_scene,
    render_archviz,
)


class TestRayTriangleIntersect:
    def test_basic_hit(self):
        """Ray hitting a flat Z=1 triangle should return t > 0."""
        orig = np.array([0.0, 0.0, 0.0])
        direction = np.array([0.0, 0.0, 1.0])
        v0 = np.array([-1.0, -1.0, 1.0])
        v1 = np.array([1.0, -1.0, 1.0])
        v2 = np.array([0.0, 1.0, 1.0])
        t = _ray_triangle_intersect(orig, direction, v0, v1, v2)
        assert t is not None
        assert t == pytest.approx(1.0, abs=1e-6)

    def test_miss(self):
        """Ray parallel to triangle → no intersection."""
        orig = np.array([0.0, 0.0, 0.0])
        direction = np.array([1.0, 0.0, 0.0])
        v0 = np.array([0.0, -1.0, 1.0])
        v1 = np.array([0.0, 1.0, 1.0])
        v2 = np.array([0.0, 0.0, 2.0])
        t = _ray_triangle_intersect(orig, direction, v0, v1, v2)
        assert t is None

    def test_backface_not_detected_at_negative_t(self):
        """Ray going away from triangle → t < 0 → returns None."""
        orig = np.array([0.0, 0.0, 2.0])
        direction = np.array([0.0, 0.0, 1.0])  # going away from triangle at z=1
        v0 = np.array([-1.0, -1.0, 1.0])
        v1 = np.array([1.0, -1.0, 1.0])
        v2 = np.array([0.0, 1.0, 1.0])
        t = _ray_triangle_intersect(orig, direction, v0, v1, v2)
        assert t is None


class TestMaterialBRDF:
    def test_brdf_shape(self):
        mat = {"albedo": (0.8, 0.6, 0.4), "roughness": 0.5, "metallic": 0.0, "ior": 1.5}
        brdf = _material_brdf(mat, 0.7, 0.7, 0.9)
        assert brdf.shape == (3,)

    def test_brdf_nonnegative(self):
        mat = {"albedo": (0.5, 0.5, 0.5), "roughness": 0.3, "metallic": 0.1, "ior": 1.5}
        brdf = _material_brdf(mat, 0.8, 0.8, 0.95)
        assert float(brdf.min()) >= 0.0

    def test_grazing_angle_zero_brdf(self):
        """cos_theta_i = 0 → diffuse only (no specular lobe)."""
        mat = {"albedo": (1.0, 1.0, 1.0), "roughness": 0.5, "metallic": 0.0, "ior": 1.5}
        brdf = _material_brdf(mat, 0.0, 0.0, 0.0)
        # Should still be nonzero (Lambertian diffuse = albedo/pi)
        assert float(brdf.max()) > 0.0


class TestMakeSimpleRoomScene:
    def test_returns_archviz_scene(self):
        scene = make_simple_room_scene()
        assert isinstance(scene, ArchVizScene)

    def test_has_geometry(self):
        scene = make_simple_room_scene(6.0, 5.0, 3.0)
        assert len(scene.geometry_meshes) > 0

    def test_has_materials(self):
        scene = make_simple_room_scene()
        assert "floor" in scene.materials
        assert "wall" in scene.materials


class TestRenderArchviz:
    def test_output_shape(self):
        """render_archviz returns image of correct shape (H, W, 3)."""
        scene = make_simple_room_scene(4.0, 3.0, 2.5)
        W, H = 32, 24
        img = render_archviz(scene, (W, H), samples=16)
        assert img.shape == (H, W, 3)

    def test_output_dtype_uint8(self):
        scene = make_simple_room_scene(4.0, 3.0, 2.5)
        img = render_archviz(scene, (16, 12), samples=8)
        assert img.dtype == np.uint8

    def test_output_not_all_black(self):
        """Scene has a sun + room — at least some pixels should be nonzero."""
        scene = make_simple_room_scene(6.0, 5.0, 3.0)
        img = render_archviz(scene, (32, 24), samples=16)
        assert int(img.max()) > 0

    def test_output_in_valid_range(self):
        scene = make_simple_room_scene()
        img = render_archviz(scene, (16, 12), samples=8)
        assert int(img.min()) >= 0
        assert int(img.max()) <= 255
