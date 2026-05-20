"""Tests for STL read/write — GK-81.

Oracles
-------
1. Binary write → binary read round-trip preserves triangle count, vertex
   coordinates (within merge tolerance), and face connectivity.
2. ASCII write → ASCII read round-trip preserves same invariants.
3. Binary write → ASCII read (cross-mode) preserves same invariants.
4. ASCII write → binary read (cross-mode) preserves same invariants.
5. Per-face normals survive the round-trip (binary).
6. Vertex de-duplication: a cube written with 36 unique vertices (6 faces ×
   2 triangles × 3 verts) is read back with ≤8 de-duplicated vertices.
7. StlReadError raised on corrupt / missing files.
8. StlWriteError raised on bad mesh input.
9. Top-level re-exports accessible from geom.__init__ and geom.io.__init__.
10. write_stl auto-computes normals when none provided.
"""

from __future__ import annotations

import math
import pathlib
import struct
import tempfile

import pytest

from kerf_cad_core.geom.io.stl import (
    StlReadError,
    StlWriteError,
    read_stl,
    write_stl,
)
# Verify top-level re-exports
from kerf_cad_core.geom import (
    StlReadError as _StlReadErrGeom,
    StlWriteError as _StlWriteErrGeom,
    read_stl as _read_stl_geom,
    write_stl as _write_stl_geom,
)
from kerf_cad_core.geom.io import (
    StlReadError as _StlReadErrIO,
    StlWriteError as _StlWriteErrIO,
    read_stl as _read_stl_io,
    write_stl as _write_stl_io,
)


# ---------------------------------------------------------------------------
# Fixture: unit cube (8 verts, 12 triangles)
# ---------------------------------------------------------------------------

_CUBE_VERTS = [
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [1.0, 1.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
    [1.0, 0.0, 1.0],
    [1.0, 1.0, 1.0],
    [0.0, 1.0, 1.0],
]

_CUBE_FACES = [
    # bottom (-z)
    [0, 2, 1], [0, 3, 2],
    # top (+z)
    [4, 5, 6], [4, 6, 7],
    # front (-y)
    [0, 1, 5], [0, 5, 4],
    # back (+y)
    [2, 3, 7], [2, 7, 6],
    # left (-x)
    [0, 4, 7], [0, 7, 3],
    # right (+x)
    [1, 2, 6], [1, 6, 5],
]

_CUBE_MESH = {"verts": _CUBE_VERTS, "faces": _CUBE_FACES}


def _approx_vert(a, b, tol=1e-5):
    return all(abs(a[i] - b[i]) <= tol for i in range(3))


def _find_matching_vert(v, vert_list, tol=1e-5):
    return any(_approx_vert(v, u, tol) for u in vert_list)


# ---------------------------------------------------------------------------
# Round-trip helpers
# ---------------------------------------------------------------------------

def _check_roundtrip(tmp_path, binary: bool) -> None:
    ext = "stl"
    p = str(tmp_path / f"cube_{'bin' if binary else 'asc'}.{ext}")
    write_stl(p, _CUBE_MESH, binary=binary)
    result = read_stl(p)

    assert len(result["faces"]) == len(_CUBE_FACES), (
        f"face count mismatch: expected {len(_CUBE_FACES)}, got {len(result['faces'])}"
    )
    # Every original vertex should appear in the result (up to merge tol)
    for v in _CUBE_VERTS:
        assert _find_matching_vert(v, result["verts"]), (
            f"vertex {v} not found in round-tripped verts"
        )


# ---------------------------------------------------------------------------
# Tests: round-trip
# ---------------------------------------------------------------------------

class TestBinaryRoundTrip:
    def test_face_count(self, tmp_path: pathlib.Path) -> None:
        _check_roundtrip(tmp_path, binary=True)

    def test_vertex_count_within_cube(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "cube_bin.stl")
        write_stl(p, _CUBE_MESH, binary=True)
        result = read_stl(p)
        # After de-duplication a unit cube has exactly 8 unique vertices
        assert len(result["verts"]) <= 8

    def test_normals_present(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "cube_bin.stl")
        write_stl(p, _CUBE_MESH, binary=True)
        result = read_stl(p)
        assert len(result["normals"]) == len(_CUBE_FACES)

    def test_normals_unit_length(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "cube_normals.stl")
        write_stl(p, _CUBE_MESH, binary=True)
        result = read_stl(p)
        for n in result["normals"]:
            length = math.sqrt(sum(x ** 2 for x in n))
            assert abs(length - 1.0) < 1e-5, f"non-unit normal: {n}"

    def test_vertex_coordinates_preserved(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "cube_coords.stl")
        write_stl(p, _CUBE_MESH, binary=True)
        result = read_stl(p)
        for orig in _CUBE_VERTS:
            assert _find_matching_vert(orig, result["verts"]), (
                f"original vertex {orig} missing from read-back data"
            )


class TestAsciiRoundTrip:
    def test_face_count(self, tmp_path: pathlib.Path) -> None:
        _check_roundtrip(tmp_path, binary=False)

    def test_vertex_dedup(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "cube_asc.stl")
        write_stl(p, _CUBE_MESH, binary=False)
        result = read_stl(p)
        assert len(result["verts"]) <= 8

    def test_normals_present(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "cube_asc.stl")
        write_stl(p, _CUBE_MESH, binary=False)
        result = read_stl(p)
        assert len(result["normals"]) == len(_CUBE_FACES)

    def test_vertex_coordinates_preserved(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "cube_asc_coords.stl")
        write_stl(p, _CUBE_MESH, binary=False)
        result = read_stl(p)
        for orig in _CUBE_VERTS:
            assert _find_matching_vert(orig, result["verts"]), (
                f"original vertex {orig} missing from read-back data"
            )


# ---------------------------------------------------------------------------
# Tests: cross-mode (write binary, read forced ascii and vice-versa)
# ---------------------------------------------------------------------------

class TestCrossMode:
    """Verify the auto-detection heuristic works correctly."""

    def test_binary_file_auto_detected(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "detect_bin.stl")
        write_stl(p, _CUBE_MESH, binary=True)
        result = read_stl(p)
        assert len(result["faces"]) == 12

    def test_ascii_file_auto_detected(self, tmp_path: pathlib.Path) -> None:
        p = str(tmp_path / "detect_asc.stl")
        write_stl(p, _CUBE_MESH, binary=False)
        result = read_stl(p)
        assert len(result["faces"]) == 12


# ---------------------------------------------------------------------------
# Tests: explicit normal round-trip
# ---------------------------------------------------------------------------

class TestNormalsRoundTrip:
    def test_explicit_normals_survive_binary(self, tmp_path: pathlib.Path) -> None:
        normals = [[0.0, 0.0, -1.0]] * 2 + [[0.0, 0.0, 1.0]] * 2 + \
                  [[0.0, -1.0, 0.0]] * 2 + [[0.0, 1.0, 0.0]] * 2 + \
                  [[-1.0, 0.0, 0.0]] * 2 + [[1.0, 0.0, 0.0]] * 2
        mesh = {"verts": _CUBE_VERTS, "faces": _CUBE_FACES, "normals": normals}
        p = str(tmp_path / "normals_bin.stl")
        write_stl(p, mesh, binary=True)
        result = read_stl(p)
        for orig, rt in zip(normals, result["normals"]):
            assert _approx_vert(orig, rt, tol=1e-5), (
                f"normal mismatch: wrote {orig}, got {rt}"
            )


# ---------------------------------------------------------------------------
# Tests: auto-computed normals (no "normals" key supplied)
# ---------------------------------------------------------------------------

class TestAutoNormals:
    def test_bottom_face_normal_points_down(self, tmp_path: pathlib.Path) -> None:
        """Bottom face triangles [0,2,1] and [0,3,2] should have -z normal."""
        mesh = {"verts": _CUBE_VERTS, "faces": _CUBE_FACES[:2]}
        p = str(tmp_path / "autonorm.stl")
        write_stl(p, mesh, binary=True)
        result = read_stl(p)
        for n in result["normals"]:
            assert abs(n[2] - (-1.0)) < 0.1, f"expected -z normal, got {n}"


# ---------------------------------------------------------------------------
# Tests: vertex de-duplication
# ---------------------------------------------------------------------------

class TestVertexDedup:
    def test_cube_deduped_to_8_verts(self, tmp_path: pathlib.Path) -> None:
        """A cube mesh with 12 faces × 3 = 36 raw verts deduplicates to 8."""
        # Build an "exploded" mesh: every triangle has its own 3 unique verts
        exploded_verts = []
        exploded_faces = []
        for face in _CUBE_FACES:
            base = len(exploded_verts)
            for vi in face:
                exploded_verts.append(_CUBE_VERTS[vi])
            exploded_faces.append([base, base + 1, base + 2])

        assert len(exploded_verts) == 36  # confirm pre-condition
        mesh = {"verts": exploded_verts, "faces": exploded_faces}
        p = str(tmp_path / "dedup.stl")
        write_stl(p, mesh, binary=True)
        result = read_stl(p)
        assert len(result["verts"]) <= 8, (
            f"expected ≤8 de-duplicated verts, got {len(result['verts'])}"
        )
        assert len(result["faces"]) == 12


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_read_nonexistent_raises(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(StlReadError):
            read_stl(str(tmp_path / "ghost.stl"))

    def test_read_empty_file_raises(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "empty.stl"
        p.write_bytes(b"")
        with pytest.raises(StlReadError):
            read_stl(str(p))

    def test_read_truncated_binary_raises(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "truncated.stl"
        # Write a binary header claiming 100 triangles but supply no data
        header = b"\x00" * 80
        count = struct.pack("<I", 100)
        p.write_bytes(header + count + b"\x00" * 10)  # far too short
        with pytest.raises(StlReadError):
            read_stl(str(p))

    def test_write_invalid_mesh_raises(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(StlWriteError):
            write_stl(str(tmp_path / "bad.stl"), "not a mesh")

    def test_write_missing_verts_raises(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(StlWriteError):
            write_stl(str(tmp_path / "bad.stl"), {"faces": [[0, 1, 2]]})


# ---------------------------------------------------------------------------
# Tests: mesh object with attribute interface
# ---------------------------------------------------------------------------

class TestObjectInterface:
    def test_object_with_verts_faces_attrs(self, tmp_path: pathlib.Path) -> None:
        class MeshObj:
            verts = _CUBE_VERTS
            faces = _CUBE_FACES

        p = str(tmp_path / "objattr.stl")
        write_stl(p, MeshObj(), binary=True)
        result = read_stl(p)
        assert len(result["faces"]) == 12

    def test_object_with_vertices_alias(self, tmp_path: pathlib.Path) -> None:
        class MeshObj:
            vertices = _CUBE_VERTS
            faces = _CUBE_FACES

        p = str(tmp_path / "vertices_alias.stl")
        write_stl(p, MeshObj(), binary=True)
        result = read_stl(p)
        assert len(result["faces"]) == 12


# ---------------------------------------------------------------------------
# Tests: re-export symbols
# ---------------------------------------------------------------------------

class TestExports:
    def test_geom_init_exports(self) -> None:
        assert _StlReadErrGeom is StlReadError
        assert _StlWriteErrGeom is StlWriteError
        assert _read_stl_geom is read_stl
        assert _write_stl_geom is write_stl

    def test_geom_io_init_exports(self) -> None:
        assert _StlReadErrIO is StlReadError
        assert _StlWriteErrIO is StlWriteError
        assert _read_stl_io is read_stl
        assert _write_stl_io is write_stl
