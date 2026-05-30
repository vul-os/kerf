"""
Tests for subd_export_gltf.py — Catmull-Clark limit-surface glTF 2.0 exporter.

Coverage:
  1.  Cube cage, 2 levels, gltf → valid JSON (json.loads succeeds).
  2.  asset.version == "2.0" in .gltf output.
  3.  asset.version == "2.0" in .glb (parse_gltf round-trip).
  4.  Cube cage, 2 levels, gltf → 96 faces → 192 triangles.
  5.  Round-trip .gltf vertex count matches POSITION accessor count.
  6.  Round-trip .gltf face (triangle) count matches indices accessor count // 3.
  7.  Round-trip .glb vertex count matches n_vertices.
  8.  Round-trip .glb face count matches n_triangles.
  9.  .glb binary header starts with b"glTF" (magic=0x46546C67).
  10. .glb binary header version field == 2.
  11. export_limit_to_gltf returns bytes (both formats).
  12. .gltf JSON contains meshes[0].primitives[0].attributes.POSITION.
  13. .gltf JSON contains meshes[0].primitives[0].indices key.
  14. Sphere cage convergence: parse_gltf vertices within [-2, 2]^3.
  15. levels=0 → original cage faces (6 quads → 12 triangles for cube).
  16. levels=1 → 24 faces → 48 triangles.
  17. Invalid format raises ValueError.
  18. dict cage input accepted (.gltf).
  19. dict cage input accepted (.glb).
  20. face count scales 4× per level (triangles scale same).
  21. parse_gltf raises ValueError for non-glTF data.
  22. parse_gltf raises ValueError for asset.version != "2.0".
  23. POSITION accessor type == "VEC3" in JSON.
  24. indices accessor componentType == 5125 (UNSIGNED_INT) in JSON.
  25. buffers[0].byteLength > 0 in JSON.
"""

from __future__ import annotations

import base64
import json
import struct
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_export_gltf import export_limit_to_gltf, parse_gltf

_GLB_MAGIC = 0x46546C67  # "glTF" little-endian


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cube_mesh() -> SubDMesh:
    """Unit cube with 6 quad faces (8 verts)."""
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
        [0, 1, 2, 3],  # -Z
        [4, 5, 6, 7],  # +Z
        [0, 1, 5, 4],  # -Y
        [2, 3, 7, 6],  # +Y
        [0, 3, 7, 4],  # -X
        [1, 2, 6, 5],  # +X
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _sphere_cage() -> SubDMesh:
    """Octahedral cage approximating the unit sphere (8 triangles, 6 verts)."""
    verts = [
        [ 0.0,  0.0,  1.0],
        [ 1.0,  0.0,  0.0],
        [ 0.0,  1.0,  0.0],
        [-1.0,  0.0,  0.0],
        [ 0.0, -1.0,  0.0],
        [ 0.0,  0.0, -1.0],
    ]
    faces = [
        [0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
        [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _cube_dict():
    return {
        "vertices": [
            [-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
            [-1,-1, 1],[1,-1, 1],[1,1, 1],[-1,1, 1],
        ],
        "faces": [
            [0,1,2,3],[4,5,6,7],[0,1,5,4],[2,3,7,6],[0,3,7,4],[1,2,6,5],
        ],
    }


# ---------------------------------------------------------------------------
# Tests: basic .gltf JSON validity
# ---------------------------------------------------------------------------

class TestGltfJson:

    def test_gltf_is_valid_json(self):
        """export_limit_to_gltf(.., format='gltf') produces valid JSON."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        assert isinstance(doc, dict)

    def test_asset_version_gltf(self):
        """asset.version == '2.0' in .gltf output."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        assert doc["asset"]["version"] == "2.0"

    def test_mesh_primitives_position(self):
        """meshes[0].primitives[0].attributes.POSITION key present."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        assert "POSITION" in doc["meshes"][0]["primitives"][0]["attributes"]

    def test_mesh_primitives_indices(self):
        """meshes[0].primitives[0].indices key present."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        assert "indices" in doc["meshes"][0]["primitives"][0]

    def test_position_accessor_vec3(self):
        """POSITION accessor type == 'VEC3'."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        pos_idx = doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
        assert doc["accessors"][pos_idx]["type"] == "VEC3"

    def test_indices_accessor_unsigned_int(self):
        """indices accessor componentType == 5125 (UNSIGNED_INT)."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        idx_acc = doc["meshes"][0]["primitives"][0]["indices"]
        assert doc["accessors"][idx_acc]["componentType"] == 5125

    def test_buffer_byte_length_positive(self):
        """buffers[0].byteLength > 0."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        assert doc["buffers"][0]["byteLength"] > 0

    def test_returns_bytes_gltf(self):
        """export_limit_to_gltf format='gltf' returns bytes."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        assert isinstance(data, bytes)


# ---------------------------------------------------------------------------
# Tests: .glb binary container
# ---------------------------------------------------------------------------

class TestGlbBinary:

    def test_glb_starts_with_magic(self):
        """GLB bytes start with b'glTF' (magic=0x46546C67)."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="glb")
        magic = struct.unpack_from("<I", data, 0)[0]
        assert magic == _GLB_MAGIC, f"Expected magic {_GLB_MAGIC:#010x}, got {magic:#010x}"

    def test_glb_starts_with_gltf_bytes(self):
        """First 4 bytes of GLB spell b'glTF'."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="glb")
        assert data[:4] == b"glTF"

    def test_glb_version_field(self):
        """GLB header version field == 2."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="glb")
        version = struct.unpack_from("<I", data, 4)[0]
        assert version == 2

    def test_glb_total_length_matches(self):
        """GLB header total_length == len(data)."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="glb")
        total_length = struct.unpack_from("<I", data, 8)[0]
        assert total_length == len(data)

    def test_returns_bytes_glb(self):
        """export_limit_to_gltf format='glb' returns bytes."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="glb")
        assert isinstance(data, bytes)


# ---------------------------------------------------------------------------
# Tests: round-trip via parse_gltf (.gltf)
# ---------------------------------------------------------------------------

class TestRoundTripGltf:

    def test_asset_version_roundtrip_gltf(self):
        """parse_gltf asset_version == '2.0' for .gltf format."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        parsed = parse_gltf(data)
        assert parsed["asset_version"] == "2.0"

    def test_vertex_count_roundtrip_gltf(self):
        """parse_gltf n_vertices matches POSITION accessor count."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        pos_idx = doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
        accessor_count = doc["accessors"][pos_idx]["count"]
        parsed = parse_gltf(data)
        assert parsed["n_vertices"] == accessor_count

    def test_triangle_count_roundtrip_gltf(self):
        """parse_gltf n_triangles matches indices count // 3."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        doc = json.loads(data.decode("utf-8"))
        idx_acc_idx = doc["meshes"][0]["primitives"][0]["indices"]
        n_indices = doc["accessors"][idx_acc_idx]["count"]
        parsed = parse_gltf(data)
        assert parsed["n_triangles"] == n_indices // 3

    def test_cube_2_levels_192_triangles_gltf(self):
        """Cube cage 2 CC levels → 96 quads → 192 triangles (.gltf)."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        parsed = parse_gltf(data)
        assert parsed["n_triangles"] == 192, f"Expected 192, got {parsed['n_triangles']}"

    def test_face_indices_non_negative_gltf(self):
        """All face vertex indices >= 0."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        parsed = parse_gltf(data)
        for face in parsed["faces"]:
            for idx in face:
                assert idx >= 0

    def test_face_indices_within_range_gltf(self):
        """All face vertex indices < n_vertices."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        parsed = parse_gltf(data)
        n = parsed["n_vertices"]
        for face in parsed["faces"]:
            for idx in face:
                assert idx < n, f"Index {idx} out of range (n_verts={n})"

    def test_vertex_coordinates_finite_gltf(self):
        """All vertex coordinates are finite floats."""
        import math
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        parsed = parse_gltf(data)
        for v in parsed["vertices"]:
            for c in v:
                assert math.isfinite(c), f"Non-finite coordinate: {c}"


# ---------------------------------------------------------------------------
# Tests: round-trip via parse_gltf (.glb)
# ---------------------------------------------------------------------------

class TestRoundTripGlb:

    def test_asset_version_roundtrip_glb(self):
        """parse_gltf asset_version == '2.0' for .glb format."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="glb")
        parsed = parse_gltf(data)
        assert parsed["asset_version"] == "2.0"

    def test_vertex_count_roundtrip_glb(self):
        """parse_gltf n_vertices consistent for .glb."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="glb")
        parsed = parse_gltf(data)
        assert parsed["n_vertices"] > 0

    def test_triangle_count_roundtrip_glb(self):
        """parse_gltf n_triangles == 192 for cube 2 levels (.glb)."""
        data = export_limit_to_gltf(_cube_mesh(), levels=2, format="glb")
        parsed = parse_gltf(data)
        assert parsed["n_triangles"] == 192, f"Expected 192, got {parsed['n_triangles']}"

    def test_gltf_glb_vertex_counts_match(self):
        """Vertex counts from .gltf and .glb are equal for same input."""
        gltf_data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        glb_data  = export_limit_to_gltf(_cube_mesh(), levels=2, format="glb")
        p_gltf = parse_gltf(gltf_data)
        p_glb  = parse_gltf(glb_data)
        assert p_gltf["n_vertices"] == p_glb["n_vertices"]

    def test_gltf_glb_triangle_counts_match(self):
        """Triangle counts from .gltf and .glb are equal for same input."""
        gltf_data = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        glb_data  = export_limit_to_gltf(_cube_mesh(), levels=2, format="glb")
        p_gltf = parse_gltf(gltf_data)
        p_glb  = parse_gltf(glb_data)
        assert p_gltf["n_triangles"] == p_glb["n_triangles"]

    def test_glb_first_vertex_matches_gltf(self):
        """First vertex coordinates in .glb and .gltf round-trips match."""
        gltf_data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        glb_data  = export_limit_to_gltf(_cube_mesh(), levels=1, format="glb")
        p_gltf = parse_gltf(gltf_data)
        p_glb  = parse_gltf(glb_data)
        vg = p_gltf["vertices"][0]
        vb = p_glb["vertices"][0]
        for a, b in zip(vg, vb):
            assert abs(a - b) < 1e-4, f"Vertex mismatch gltf={vg} glb={vb}"


# ---------------------------------------------------------------------------
# Tests: face / level counts
# ---------------------------------------------------------------------------

class TestLevelCounts:

    def test_levels_0_cube_12_triangles(self):
        """levels=0 returns original cage faces: 6 quads → 12 triangles."""
        data = export_limit_to_gltf(_cube_mesh(), levels=0, format="gltf")
        parsed = parse_gltf(data)
        assert parsed["n_triangles"] == 12, f"Expected 12, got {parsed['n_triangles']}"

    def test_levels_1_cube_48_triangles(self):
        """levels=1 → 24 quads → 48 triangles."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        parsed = parse_gltf(data)
        assert parsed["n_triangles"] == 48, f"Expected 48, got {parsed['n_triangles']}"

    def test_triangle_count_scales_4x(self):
        """Triangles scale 4× per CC level."""
        d1 = export_limit_to_gltf(_cube_mesh(), levels=1, format="gltf")
        d2 = export_limit_to_gltf(_cube_mesh(), levels=2, format="gltf")
        t1 = parse_gltf(d1)["n_triangles"]
        t2 = parse_gltf(d2)["n_triangles"]
        assert t2 == t1 * 4, f"Level-2 tris {t2} should be 4× level-1 {t1}"


# ---------------------------------------------------------------------------
# Tests: sphere cage convergence
# ---------------------------------------------------------------------------

class TestSphereConvergence:

    def test_sphere_vertices_within_bounds(self):
        """Sphere cage 2 CC levels: all vertices within [-2, 2]^3."""
        import math
        data = export_limit_to_gltf(_sphere_cage(), levels=2, format="gltf")
        parsed = parse_gltf(data)
        for v in parsed["vertices"]:
            for c in v:
                assert abs(c) <= 2.0, f"Vertex coordinate {c} out of [-2, 2]"

    def test_sphere_face_count_positive(self):
        """Sphere cage 2 levels produces > 0 triangles."""
        data = export_limit_to_gltf(_sphere_cage(), levels=2, format="gltf")
        parsed = parse_gltf(data)
        assert parsed["n_triangles"] > 0


# ---------------------------------------------------------------------------
# Tests: edge cases and error handling
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_invalid_format_raises_value_error(self):
        """Invalid format string raises ValueError."""
        with pytest.raises(ValueError):
            export_limit_to_gltf(_cube_mesh(), levels=1, format="stl")

    def test_dict_cage_gltf(self):
        """export_limit_to_gltf accepts dict-style cage (.gltf)."""
        data = export_limit_to_gltf(_cube_dict(), levels=1, format="gltf")
        parsed = parse_gltf(data)
        assert parsed["n_triangles"] == 48

    def test_dict_cage_glb(self):
        """export_limit_to_gltf accepts dict-style cage (.glb)."""
        data = export_limit_to_gltf(_cube_dict(), levels=1, format="glb")
        parsed = parse_gltf(data)
        assert parsed["n_triangles"] == 48

    def test_parse_gltf_invalid_data_raises(self):
        """parse_gltf raises ValueError for non-glTF data."""
        with pytest.raises(ValueError):
            parse_gltf(b"not a gltf file at all !!!")

    def test_parse_gltf_wrong_version_raises(self):
        """parse_gltf raises ValueError for asset.version != '2.0'."""
        bad_doc = {
            "asset": {"version": "1.0"},
            "meshes": [],
        }
        with pytest.raises(ValueError, match="asset.version"):
            from kerf_cad_core.geom.subd_export_gltf import _extract_from_doc
            _extract_from_doc(bad_doc, bin_chunk=None)

    def test_empty_cage_no_crash_gltf(self):
        """Empty cage returns valid glTF bytes without raising."""
        mesh = SubDMesh()
        data = export_limit_to_gltf(mesh, levels=2, format="gltf")
        assert isinstance(data, bytes)
        doc = json.loads(data.decode("utf-8"))
        assert doc["asset"]["version"] == "2.0"

    def test_empty_cage_no_crash_glb(self):
        """Empty cage returns valid GLB bytes without raising."""
        mesh = SubDMesh()
        data = export_limit_to_gltf(mesh, levels=2, format="glb")
        assert isinstance(data, bytes)
        assert data[:4] == b"glTF"

    def test_format_case_insensitive(self):
        """format='GLB' (uppercase) is accepted."""
        data = export_limit_to_gltf(_cube_mesh(), levels=1, format="GLB")
        assert data[:4] == b"glTF"
