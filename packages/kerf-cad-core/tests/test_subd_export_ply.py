"""
Tests for subd_export_ply.py — Catmull-Clark limit-surface PLY exporter.

Coverage:
  1.  Cube cage, 2 levels, ASCII → valid PLY header (ply, format ascii 1.0,
      element vertex N, element face F, end_header).
  2.  Cube cage, 2 levels → 96 faces (6 × 4²).
  3.  Vertex count matches element header count (ASCII).
  4.  Face count matches element header count (ASCII).
  5.  Round-trip ASCII: parse_ply vertex count matches header N.
  6.  Round-trip ASCII: parse_ply face count matches header F.
  7.  Binary little-endian: starts with 'ply\\n'.
  8.  Binary little-endian: header contains 'format binary_little_endian 1.0'.
  9.  Binary little-endian round-trip: vertex count matches header.
  10. Binary little-endian round-trip: face count matches header.
  11. Binary little-endian: vertex data is compact (not ASCII-encoded).
  12. property list uchar int vertex_indices present in header.
  13. levels=0 → cage faces unchanged (6 for cube).
  14. levels=1 → 24 faces (6 × 4).
  15. Face count scales 4× per level: level-1 × 4 == level-2.
  16. Sphere cage convergence: 2 levels, all vertices within bounding box.
  17. dict cage input accepted.
  18. Invalid format raises ValueError.
  19. Empty cage: no crash, returns bytes.
  20. ASCII parse_ply: coordinate values round-trip (first vertex matches).
"""

from __future__ import annotations

import math
import struct
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_export_ply import export_limit_to_ply, parse_ply


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


def _extract_header(data: bytes) -> str:
    """Return PLY header as a string (up to end_header, inclusive)."""
    end = data.find(b"end_header\n")
    if end == -1:
        end = data.find(b"end_header\r\n")
    if end == -1:
        return ""
    return data[:end + 12].decode("ascii", errors="replace")


def _parse_header_counts(data: bytes):
    """Return (n_verts, n_faces) from PLY header."""
    header = _extract_header(data)
    n_verts = 0
    n_faces = 0
    current_elem = None
    for line in header.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "element":
            current_elem = parts[1] if len(parts) >= 2 else None
            count = int(parts[2]) if len(parts) >= 3 else 0
            if current_elem == "vertex":
                n_verts = count
            elif current_elem == "face":
                n_faces = count
    return n_verts, n_faces


# ---------------------------------------------------------------------------
# Tests: ASCII header validity
# ---------------------------------------------------------------------------

class TestAsciiHeader:

    def test_starts_with_ply(self):
        """PLY file must start with 'ply\\n'."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        assert data.startswith(b"ply\n"), "PLY must begin with 'ply\\n'"

    def test_format_line_ascii(self):
        """Header must contain 'format ascii 1.0'."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        assert b"format ascii 1.0" in data

    def test_element_vertex_line(self):
        """Header must contain 'element vertex N' with N > 0."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        n_verts, _ = _parse_header_counts(data)
        assert n_verts > 0

    def test_element_face_line(self):
        """Header must contain 'element face F' with F == 96 for cube 2 levels."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        _, n_faces = _parse_header_counts(data)
        assert n_faces == 96, f"Expected 96 faces, got {n_faces}"

    def test_end_header_present(self):
        """Header must end with 'end_header'."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        assert b"end_header\n" in data

    def test_property_float_xyz(self):
        """Header must declare 'property float x', 'property float y', 'property float z'."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        header = _extract_header(data)
        assert "property float x" in header
        assert "property float y" in header
        assert "property float z" in header

    def test_property_list_face(self):
        """Header must declare 'property list uchar int vertex_indices'."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        header = _extract_header(data)
        assert "property list uchar int vertex_indices" in header


# ---------------------------------------------------------------------------
# Tests: ASCII face/vertex counts
# ---------------------------------------------------------------------------

class TestAsciiCounts:

    def test_cube_2_levels_96_faces(self):
        """Cube cage: 2 CC levels → 6 × 4² = 96 faces."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == 96

    def test_cube_1_level_24_faces(self):
        """Cube cage: 1 CC level → 6 × 4 = 24 faces."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == 24

    def test_face_count_scales_4x(self):
        """Each CC level multiplies face count by 4."""
        d1 = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        d2 = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        f1 = len(parse_ply(d1)["faces"])
        f2 = len(parse_ply(d2)["faces"])
        assert f2 == f1 * 4, f"Level-2 faces {f2} should be 4× level-1 {f1}"

    def test_levels_zero_original_faces(self):
        """levels=0 returns original cage faces (6 for cube)."""
        data = export_limit_to_ply(_cube_mesh(), levels=0, format="ascii")
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == 6

    def test_header_vertex_count_matches_body(self):
        """Header element vertex N matches actual vertex rows in body."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        n_verts_header, _ = _parse_header_counts(data)
        parsed = parse_ply(data)
        assert len(parsed["vertices"]) == n_verts_header

    def test_header_face_count_matches_body(self):
        """Header element face F matches actual face rows in body."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        _, n_faces_header = _parse_header_counts(data)
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == n_faces_header


# ---------------------------------------------------------------------------
# Tests: ASCII round-trip (parse_ply)
# ---------------------------------------------------------------------------

class TestAsciiRoundTrip:

    def test_vertex_count_roundtrip(self):
        """parse_ply vertex count matches header N."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        n_verts_header, _ = _parse_header_counts(data)
        parsed = parse_ply(data)
        assert len(parsed["vertices"]) == n_verts_header

    def test_face_count_roundtrip(self):
        """parse_ply face count matches header F."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        _, n_faces_header = _parse_header_counts(data)
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == n_faces_header

    def test_first_vertex_coordinate_roundtrip(self):
        """First vertex in parse_ply matches first ASCII data line."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        # Find body start
        body_start = data.find(b"end_header\n") + len(b"end_header\n")
        body_lines = data[body_start:].decode("ascii").splitlines()
        body_lines = [l for l in body_lines if l.strip()]
        first_line = body_lines[0].split()
        expected = [float(first_line[0]), float(first_line[1]), float(first_line[2])]
        parsed = parse_ply(data)
        got = parsed["vertices"][0]
        for a, b in zip(expected, got):
            assert abs(a - b) < 1e-5, f"Vertex coordinate mismatch: {expected} != {got}"

    def test_face_indices_non_negative(self):
        """All face vertex indices must be >= 0 (PLY is 0-based)."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        parsed = parse_ply(data)
        for face in parsed["faces"]:
            for idx in face:
                assert idx >= 0, f"Negative face index: {idx}"

    def test_face_indices_within_range(self):
        """All face vertex indices must be < n_vertices."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        parsed = parse_ply(data)
        n = len(parsed["vertices"])
        for face in parsed["faces"]:
            for idx in face:
                assert idx < n, f"Face index {idx} out of range (n_verts={n})"


# ---------------------------------------------------------------------------
# Tests: binary_little_endian format
# ---------------------------------------------------------------------------

class TestBinaryLittleEndian:

    def test_starts_with_ply(self):
        """Binary PLY must start with 'ply\\n'."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="binary_little_endian")
        assert data.startswith(b"ply\n")

    def test_format_line_binary_le(self):
        """Header must contain 'format binary_little_endian 1.0'."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="binary_little_endian")
        assert b"format binary_little_endian 1.0" in data

    def test_binary_roundtrip_vertex_count(self):
        """parse_ply vertex count matches header N for binary format."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="binary_little_endian")
        n_verts_header, _ = _parse_header_counts(data)
        parsed = parse_ply(data)
        assert len(parsed["vertices"]) == n_verts_header

    def test_binary_roundtrip_face_count(self):
        """parse_ply face count matches header F for binary format."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="binary_little_endian")
        _, n_faces_header = _parse_header_counts(data)
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == n_faces_header

    def test_binary_96_faces_cube_2_levels(self):
        """Binary: cube cage 2 levels → 96 faces."""
        data = export_limit_to_ply(_cube_mesh(), levels=2, format="binary_little_endian")
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == 96

    def test_binary_body_is_compact(self):
        """Binary body must not contain ASCII-encoded vertex lines.

        After end_header, the first 12 bytes (3×float32) form a vertex.
        For a compact binary file, those bytes must NOT all be printable ASCII.
        (A valid float32 representation of any non-zero coordinate will typically
        have at least one byte outside printable ASCII range, OR the test verifies
        that the binary body is smaller than an equivalent ASCII body.)
        """
        bin_data = export_limit_to_ply(_cube_mesh(), levels=2, format="binary_little_endian")
        asc_data = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        # Binary should be shorter than ASCII for meshes of this size
        assert len(bin_data) < len(asc_data), (
            f"Binary PLY ({len(bin_data)} B) should be smaller than "
            f"ASCII PLY ({len(asc_data)} B)"
        )

    def test_binary_first_vertex_matches_ascii(self):
        """First vertex coordinates in binary and ASCII PLY should match."""
        bin_data = export_limit_to_ply(_cube_mesh(), levels=1, format="binary_little_endian")
        asc_data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        bin_parsed = parse_ply(bin_data)
        asc_parsed = parse_ply(asc_data)
        bv = bin_parsed["vertices"][0]
        av = asc_parsed["vertices"][0]
        for a, b in zip(av, bv):
            assert abs(a - b) < 1e-4, f"Vertex mismatch ascii={av} binary={bv}"

    def test_binary_vertex_struct_readable(self):
        """Binary body: first 12 bytes after end_header parse as 3 floats."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="binary_little_endian")
        body_start = data.find(b"end_header\n") + len(b"end_header\n")
        body = data[body_start:]
        assert len(body) >= 12, "Binary body too short for even one vertex"
        x, y, z = struct.unpack_from("<fff", body, 0)
        # All coordinates of the subdivided cube should be within [-2, 2]
        for coord in (x, y, z):
            assert abs(coord) <= 2.0, f"Unexpected coordinate value {coord}"


# ---------------------------------------------------------------------------
# Tests: edge cases and inputs
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_invalid_format_raises_value_error(self):
        """Invalid format string raises ValueError."""
        with pytest.raises(ValueError):
            export_limit_to_ply(_cube_mesh(), levels=1, format="stl")

    def test_empty_cage_no_crash_ascii(self):
        """Empty cage returns bytes without raising (ASCII)."""
        mesh = SubDMesh()
        data = export_limit_to_ply(mesh, levels=2, format="ascii")
        assert isinstance(data, bytes)

    def test_empty_cage_no_crash_binary(self):
        """Empty cage returns bytes without raising (binary)."""
        mesh = SubDMesh()
        data = export_limit_to_ply(mesh, levels=2, format="binary_little_endian")
        assert isinstance(data, bytes)

    def test_dict_cage_input_ascii(self):
        """export_limit_to_ply accepts dict-style cage (ASCII)."""
        cage = {
            "vertices": [
                [-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                [-1,-1, 1],[1,-1, 1],[1,1, 1],[-1,1, 1],
            ],
            "faces": [
                [0,1,2,3],[4,5,6,7],[0,1,5,4],[2,3,7,6],[0,3,7,4],[1,2,6,5],
            ],
        }
        data = export_limit_to_ply(cage, levels=1, format="ascii")
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == 24

    def test_dict_cage_input_binary(self):
        """export_limit_to_ply accepts dict-style cage (binary)."""
        cage = {
            "vertices": [
                [-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                [-1,-1, 1],[1,-1, 1],[1,1, 1],[-1,1, 1],
            ],
            "faces": [
                [0,1,2,3],[4,5,6,7],[0,1,5,4],[2,3,7,6],[0,3,7,4],[1,2,6,5],
            ],
        }
        data = export_limit_to_ply(cage, levels=1, format="binary_little_endian")
        parsed = parse_ply(data)
        assert len(parsed["faces"]) == 24

    def test_returns_bytes(self):
        """export_limit_to_ply always returns bytes, not str."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        assert isinstance(data, bytes)
        data2 = export_limit_to_ply(_cube_mesh(), levels=1, format="binary_little_endian")
        assert isinstance(data2, bytes)

    def test_ascii_format_case_insensitive(self):
        """format='ASCII' (uppercase) is accepted."""
        data = export_limit_to_ply(_cube_mesh(), levels=1, format="ASCII")
        assert b"format ascii 1.0" in data


# ---------------------------------------------------------------------------
# Tests: sphere cage convergence
# ---------------------------------------------------------------------------

class TestSphereConvergence:

    def test_sphere_cage_vertices_within_bounds(self):
        """Octahedral cage 2 CC levels: all vertices within [-2, 2]^3."""
        data = export_limit_to_ply(_sphere_cage(), levels=2, format="ascii")
        parsed = parse_ply(data)
        for v in parsed["vertices"]:
            for c in v:
                assert abs(c) <= 2.0, f"Vertex coordinate {c} out of [-2, 2]"

    def test_sphere_cage_face_count_positive(self):
        """Sphere cage 2 levels produces > 0 faces."""
        data = export_limit_to_ply(_sphere_cage(), levels=2, format="ascii")
        parsed = parse_ply(data)
        assert len(parsed["faces"]) > 0

    def test_sphere_bounding_box_shrinks(self):
        """CC rounds the cage: max inf-norm decreases with more levels."""
        def _max_inf(verts):
            return max(max(abs(c) for c in v) for v in verts)

        d1 = export_limit_to_ply(_cube_mesh(), levels=1, format="ascii")
        d2 = export_limit_to_ply(_cube_mesh(), levels=2, format="ascii")
        d3 = export_limit_to_ply(_cube_mesh(), levels=3, format="ascii")
        r1 = _max_inf(parse_ply(d1)["vertices"])
        r2 = _max_inf(parse_ply(d2)["vertices"])
        r3 = _max_inf(parse_ply(d3)["vertices"])
        assert r2 <= r1, f"Level-2 max inf-norm {r2:.4f} should be <= level-1 {r1:.4f}"
        assert r3 <= r2, f"Level-3 max inf-norm {r3:.4f} should be <= level-2 {r2:.4f}"
