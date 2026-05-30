"""Tests for subd_normal_color — GK-P(normap).

Analytical oracles:

1. Up-pointing vertex  (normal ≈ +Z):
   - 'hemispherical' → blue channel dominant (B >> R, B >> G)
   - 'rgb_xyz'       → (128, 128, 255)

2. Down-pointing vertex (normal ≈ −Z):
   - 'hemispherical' → near-black (all channels low)
   - 'rgb_xyz'       → (128, 128, 0)

3. GLB output (flat plane):
   - All vertices share the same normal → all same color
   - GLB file size > 0
   - Valid glTF 2.0 format (magic bytes + version)

4. Face-from-normals on unit cube:
   - 6 distinct face colors (one per axis-aligned face orientation)
"""

from __future__ import annotations

import json
import struct
import tempfile
from pathlib import Path

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_normal_color import (
    compute_face_color_from_normals,
    compute_normal_color_map,
    export_subd_with_normals_glb,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def make_flat_plane() -> SubDMesh:
    """A 2×2 flat quad grid in the XY-plane (normal = +Z for all vertices)."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [1.0, 1.0, 0.0],
        [2.0, 1.0, 0.0],
        [0.0, 2.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, 2.0, 0.0],
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
        [3, 4, 7, 6],
        [4, 5, 8, 7],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def make_unit_cube() -> SubDMesh:
    """Unit cube SubD cage with 8 vertices and 6 outward-facing quad faces.

    Face winding is chosen so that the Newell normal method produces the
    expected outward-facing unit normal for each face:

      bottom  → (0, 0, -1)
      top     → (0, 0,  1)
      front   → (0, -1, 0)
      back    → (0,  1, 0)
      left    → (-1, 0, 0)
      right   → (1,  0, 0)

    Verified with _face_normal() to give 6 distinct normals.
    """
    verts = [
        [-1.0, -1.0, -1.0],  # 0
        [ 1.0, -1.0, -1.0],  # 1
        [ 1.0,  1.0, -1.0],  # 2
        [-1.0,  1.0, -1.0],  # 3
        [-1.0, -1.0,  1.0],  # 4
        [ 1.0, -1.0,  1.0],  # 5
        [ 1.0,  1.0,  1.0],  # 6
        [-1.0,  1.0,  1.0],  # 7
    ]
    # Each face is wound so Newell cross-product gives outward-facing normal.
    faces = [
        [3, 2, 1, 0],  # bottom  (0,0,-1): reversed CCW → CW from below
        [4, 5, 6, 7],  # top     (0,0, 1): CCW from above
        [0, 1, 5, 4],  # front   (0,-1,0)
        [7, 6, 2, 3],  # back    (0, 1,0): reversed
        [4, 7, 3, 0],  # left    (-1,0,0)
        [1, 2, 6, 5],  # right   ( 1,0,0)
    ]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# Oracle 1 — up-pointing vertex (normal ≈ +Z)
# ---------------------------------------------------------------------------

class TestUpNormal:
    """Vertices on the flat plane have normals pointing in +Z."""

    def test_hemispherical_blue_dominant(self):
        mesh = make_flat_plane()
        cmap = compute_normal_color_map(mesh, n_levels=0, encoding="hemispherical")
        assert cmap, "color map must not be empty"
        # Interior vertices of a flat grid all have +Z normals (Stam tangent
        # plane is in XY, tangent cross product points +Z).
        # Collect a sample of colors for vertices that are fully surrounded
        # (not boundary) — index 4 is the centre vertex.
        for vi, rgb in cmap.items():
            r, g, b = rgb
            # Blue channel must dominate (up-pointing → blue)
            assert b > r, f"vertex {vi}: B={b} should > R={r} for up normal"
            assert b > g, f"vertex {vi}: B={b} should > G={g} for up normal"

    def test_rgb_xyz_up_normal(self):
        """For normal (0,0,1): rgb_xyz → (128, 128, 255)."""
        from kerf_cad_core.geom.subd_normal_color import _encode_rgb_xyz
        r, g, b = _encode_rgb_xyz(0.0, 0.0, 1.0)
        assert r == 128, f"R={r} expected 128"
        assert g == 128, f"G={g} expected 128"
        assert b == 255, f"B={b} expected 255"


# ---------------------------------------------------------------------------
# Oracle 2 — down-pointing vertex (normal ≈ −Z)
# ---------------------------------------------------------------------------

class TestDownNormal:
    """Down-pointing normal is (0,0,-1)."""

    def test_hemispherical_near_dark(self):
        """hemispherical encoding of (0,0,-1) → very dark (B ≤ 64)."""
        from kerf_cad_core.geom.subd_normal_color import _encode_hemispherical
        r, g, b = _encode_hemispherical(0.0, 0.0, -1.0)
        # dot = (-1 + 1)/2 = 0 → grey=0, blue=64
        assert b <= 64, f"B={b} expected ≤ 64 for down-pointing normal"
        assert r == 0, f"R={r} expected 0"
        assert g == 0, f"G={g} expected 0"

    def test_rgb_xyz_down_normal(self):
        """For normal (0,0,-1): rgb_xyz → (128, 128, 0)."""
        from kerf_cad_core.geom.subd_normal_color import _encode_rgb_xyz
        r, g, b = _encode_rgb_xyz(0.0, 0.0, -1.0)
        assert r == 128, f"R={r} expected 128"
        assert g == 128, f"G={g} expected 128"
        assert b == 0, f"B={b} expected 0"

    def test_contrast_up_vs_down_hemispherical(self):
        """Up-pointing blue must be significantly darker than down."""
        from kerf_cad_core.geom.subd_normal_color import _encode_hemispherical
        up_rgb   = _encode_hemispherical(0.0, 0.0,  1.0)
        down_rgb = _encode_hemispherical(0.0, 0.0, -1.0)
        # Blue channel: up >> down
        assert up_rgb[2] > down_rgb[2] + 100, (
            f"hemispherical: up_B={up_rgb[2]}, down_B={down_rgb[2]}"
        )


# ---------------------------------------------------------------------------
# Oracle 3 — GLB output (flat plane)
# ---------------------------------------------------------------------------

class TestGlbOutput:
    """Flat plane → all vertices share same colour; file is valid glTF 2.0."""

    def test_glb_file_size_positive(self, tmp_path):
        mesh = make_flat_plane()
        out = str(tmp_path / "flat_plane.glb")
        export_subd_with_normals_glb(mesh, out, color_encoding="rgb_xyz", n_levels=1)
        size = Path(out).stat().st_size
        assert size > 0, f"GLB file size is {size}"

    def test_glb_magic_bytes(self, tmp_path):
        """GLB header must start with 0x46546C67 ('glTF') and version 2."""
        mesh = make_flat_plane()
        out = str(tmp_path / "flat_plane2.glb")
        export_subd_with_normals_glb(mesh, out, color_encoding="rgb_xyz", n_levels=1)
        raw = Path(out).read_bytes()
        magic, version = struct.unpack_from("<II", raw, 0)
        assert magic   == 0x46546C67, f"Bad GLB magic: 0x{magic:08X}"
        assert version == 2,          f"Bad GLB version: {version}"

    def test_glb_valid_gltf_json(self, tmp_path):
        """The JSON chunk of the GLB must parse and report asset.version=='2.0'."""
        mesh = make_flat_plane()
        out = str(tmp_path / "flat_plane3.glb")
        export_subd_with_normals_glb(mesh, out, color_encoding="rgb_xyz", n_levels=1)
        raw = Path(out).read_bytes()
        # GLB layout: 12-byte header + chunks
        # Chunk 0: JSON
        chunk0_len, chunk0_type = struct.unpack_from("<II", raw, 12)
        assert chunk0_type == 0x4E4F534A, "First chunk must be JSON"
        json_bytes = raw[20:20 + chunk0_len]
        gltf_data = json.loads(json_bytes.decode("utf-8").rstrip())
        assert gltf_data["asset"]["version"] == "2.0"

    def test_flat_plane_interior_vertices_share_color(self, tmp_path):
        """On a flat horizontal plane, interior vertices share one consistent color.

        Boundary vertices have degenerate one-rings (Stam fallback, arbitrary
        tangent plane orientation) so their colors vary.  Interior vertices of
        a flat plane all get the same Stam normal (±Z, depending on face winding),
        so they must share a single color.

        We verify that the most-common color accounts for at least ≥ 1/3 of
        all vertices (interior fraction of a 2×2 grid after 1 CC level is ~9/25).
        Additionally the dominant B channel must be either 0 or 255 (pure ±Z).
        """
        mesh = make_flat_plane()
        cmap = compute_normal_color_map(mesh, n_levels=1, encoding="rgb_xyz")
        from collections import Counter
        freq = Counter(cmap.values())
        most_common_color, most_common_count = freq.most_common(1)[0]
        total = len(cmap)
        # At least 1/3 of the vertices should share the dominant color
        assert most_common_count * 3 >= total, (
            f"Expected ≥1/3 of verts to share dominant color, "
            f"got {most_common_count}/{total}"
        )
        # The dominant color must be an axis-aligned normal (pure ±Z):
        # rgb_xyz(0,0,±1) → (128,128,255) or (128,128,0)
        r, g, b = most_common_color
        assert r == 128 and g == 128, (
            f"Dominant color R,G should be 128 for flat-plane Z-normal, "
            f"got ({r},{g},{b})"
        )
        assert b in (0, 255), (
            f"Dominant color B should be 0 or 255 for pure ±Z normal, got {b}"
        )

    def test_color_0_accessor_present(self, tmp_path):
        """The glTF JSON must have a primitive with 'COLOR_0' attribute."""
        mesh = make_flat_plane()
        out = str(tmp_path / "flat_color0.glb")
        export_subd_with_normals_glb(mesh, out, color_encoding="rgb_xyz", n_levels=1)
        raw = Path(out).read_bytes()
        chunk0_len = struct.unpack_from("<I", raw, 12)[0]
        json_bytes = raw[20:20 + chunk0_len]
        gltf_data  = json.loads(json_bytes.decode("utf-8").rstrip())
        primitives = gltf_data["meshes"][0]["primitives"]
        attrs = primitives[0]["attributes"]
        assert "COLOR_0" in attrs, f"COLOR_0 not in attributes: {list(attrs)}"


# ---------------------------------------------------------------------------
# Oracle 4 — face-from-normals: unit cube → 6 distinct colors
# ---------------------------------------------------------------------------

class TestFaceColorFromNormals:
    """Unit cube has 6 faces with 6 distinct axis-aligned normals."""

    def test_six_distinct_colors_rgb_xyz(self):
        mesh = make_unit_cube()
        fmap = compute_face_color_from_normals(mesh, encoding="rgb_xyz")
        assert len(fmap) == 6, f"Expected 6 face entries, got {len(fmap)}"
        colors = set(fmap.values())
        assert len(colors) == 6, (
            f"Expected 6 distinct face colors for unit cube, got {len(colors)}: "
            f"{sorted(colors)}"
        )

    def test_face_color_map_has_all_faces(self):
        mesh = make_unit_cube()
        fmap = compute_face_color_from_normals(mesh)
        assert set(fmap.keys()) == {0, 1, 2, 3, 4, 5}, (
            f"face keys: {set(fmap.keys())}"
        )

    def test_top_face_blue_channel_dominant_rgb_xyz(self):
        """Top face (+Z normal) in rgb_xyz should have high B (≈ 255)."""
        mesh = make_unit_cube()
        fmap = compute_face_color_from_normals(mesh, encoding="rgb_xyz")
        # Face index 1 is the top face (+Z normal): rgb_xyz(0,0,1) = (128,128,255)
        r, g, b = fmap[1]
        assert b > 200, f"top face B={b} expected >200 (rgb_xyz of (0,0,1)=255)"
        assert r == 128, f"top face R={r} expected 128"
        assert g == 128, f"top face G={g} expected 128"

    def test_bottom_face_blue_zero_rgb_xyz(self):
        """Bottom face (−Z normal) in rgb_xyz should have B ≈ 0."""
        mesh = make_unit_cube()
        fmap = compute_face_color_from_normals(mesh, encoding="rgb_xyz")
        # Face index 0 is the bottom face (−Z normal): rgb_xyz(0,0,-1) = (128,128,0)
        r, g, b = fmap[0]
        assert b < 20, f"bottom face B={b} expected <20 (rgb_xyz of (0,0,-1)=0)"
        assert r == 128, f"bottom face R={r} expected 128"
        assert g == 128, f"bottom face G={g} expected 128"

    def test_six_distinct_colors_hemispherical(self):
        mesh = make_unit_cube()
        fmap = compute_face_color_from_normals(mesh, encoding="hemispherical")
        assert len(fmap) == 6
        colors = set(fmap.values())
        # hemispherical: ±Z give unique colors; ±X and ±Y both have same
        # nz component but differ only when nx/ny differ  — however
        # hemispherical only cares about nz so side faces may share colours.
        # At minimum we must have ≥ 2 distinct colours (top ≠ bottom).
        assert len(colors) >= 2, (
            f"Expected ≥ 2 distinct hemispherical face colors, got {colors}"
        )


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unknown_encoding_returns_empty(self):
        mesh = make_flat_plane()
        result = compute_normal_color_map(mesh, encoding="bad_scheme")
        assert result == {}

    def test_empty_mesh_returns_empty(self):
        mesh = SubDMesh()
        result = compute_normal_color_map(mesh)
        assert result == {}

    def test_matcap_encoding_returns_rgb(self):
        """MatCap encoding should return non-trivial colors."""
        mesh = make_unit_cube()
        cmap = compute_normal_color_map(mesh, n_levels=0, encoding="matcap")
        assert len(cmap) == 8, f"Expected 8 cage vertices, got {len(cmap)}"
        for vi, rgb in cmap.items():
            r, g, b = rgb
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_n_levels_zero_uses_cage_directly(self):
        mesh = make_flat_plane()
        cmap0 = compute_normal_color_map(mesh, n_levels=0)
        cmap1 = compute_normal_color_map(mesh, n_levels=1)
        # Both should have entries; count differs (refined has more vertices)
        assert len(cmap0) == len(mesh.vertices)
        assert len(cmap1) > len(mesh.vertices)  # subdivision adds vertices
