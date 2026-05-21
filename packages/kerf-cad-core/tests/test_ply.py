"""Tests for PLY read/write — GK-126.

Oracles
-------
1. ASCII write → ASCII read round-trip preserves V, F, per-vertex colour.
2. Binary write → binary read round-trip preserves V, F, per-vertex colour.
3. ASCII write without colours → read returns colors=None.
4. Binary write without colours → read returns colors=None.
5. Point cloud (no faces) round-trip: verts preserved, faces is empty list.
6. Per-vertex colour values clamped to 0–255 on write.
7. PlyReadError raised on corrupt / missing files.
8. PlyWriteError raised when colors length != verts length.
9. Top-level re-exports accessible from geom.__init__ and geom.io.__init__.
10. Fan triangulation: quad face (4 verts) is split into 2 triangles on read.
"""

from __future__ import annotations

import pathlib
import struct
import tempfile

import pytest

from kerf_cad_core.geom.io.ply import (
    PlyReadError,
    PlyWriteError,
    read_ply,
    write_ply,
)
# Verify top-level re-exports
from kerf_cad_core.geom import (
    PlyReadError as _PlyReadErrGeom,
    PlyWriteError as _PlyWriteErrGeom,
    read_ply as _read_ply_geom,
    write_ply as _write_ply_geom,
)
from kerf_cad_core.geom.io import (
    PlyReadError as _PlyReadErrIO,
    PlyWriteError as _PlyWriteErrIO,
    read_ply as _read_ply_io,
    write_ply as _write_ply_io,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Simple tetrahedron: 4 vertices, 4 triangular faces
_VERTS = [
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [0.5, 1.0, 0.0],
    [0.5, 0.5, 1.0],
]
_FACES = [
    [0, 1, 2],
    [0, 1, 3],
    [0, 2, 3],
    [1, 2, 3],
]
_COLORS = [
    [255, 0, 0],
    [0, 255, 0],
    [0, 0, 255],
    [128, 128, 0],
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verts_close(a, b, tol=1e-5):
    if len(a) != len(b):
        return False
    for va, vb in zip(a, b):
        if any(abs(va[i] - vb[i]) > tol for i in range(3)):
            return False
    return True


# ---------------------------------------------------------------------------
# Oracle 1: ASCII round-trip with colour
# ---------------------------------------------------------------------------

def test_ascii_roundtrip_with_color():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "test.ply")
        write_ply(path, _VERTS, _FACES, colors=_COLORS, binary=False)
        result = read_ply(path)

    assert len(result["verts"]) == len(_VERTS)
    assert len(result["faces"]) == len(_FACES)
    assert result["colors"] is not None
    assert len(result["colors"]) == len(_COLORS)

    assert _verts_close(result["verts"], _VERTS)
    assert result["faces"] == _FACES
    assert result["colors"] == _COLORS


# ---------------------------------------------------------------------------
# Oracle 2: Binary round-trip with colour
# ---------------------------------------------------------------------------

def test_binary_roundtrip_with_color():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "test.ply")
        write_ply(path, _VERTS, _FACES, colors=_COLORS, binary=True)
        result = read_ply(path)

    assert len(result["verts"]) == len(_VERTS)
    assert len(result["faces"]) == len(_FACES)
    assert result["colors"] is not None
    assert len(result["colors"]) == len(_COLORS)

    assert _verts_close(result["verts"], _VERTS)
    assert result["faces"] == _FACES
    assert result["colors"] == _COLORS


# ---------------------------------------------------------------------------
# Oracle 3: ASCII round-trip without colour → colors is None
# ---------------------------------------------------------------------------

def test_ascii_roundtrip_no_color():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "test.ply")
        write_ply(path, _VERTS, _FACES, binary=False)
        result = read_ply(path)

    assert len(result["verts"]) == len(_VERTS)
    assert len(result["faces"]) == len(_FACES)
    assert result["colors"] is None
    assert _verts_close(result["verts"], _VERTS)


# ---------------------------------------------------------------------------
# Oracle 4: Binary round-trip without colour → colors is None
# ---------------------------------------------------------------------------

def test_binary_roundtrip_no_color():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "test.ply")
        write_ply(path, _VERTS, _FACES, binary=True)
        result = read_ply(path)

    assert len(result["verts"]) == len(_VERTS)
    assert len(result["faces"]) == len(_FACES)
    assert result["colors"] is None
    assert _verts_close(result["verts"], _VERTS)


# ---------------------------------------------------------------------------
# Oracle 5: Point cloud (no faces)
# ---------------------------------------------------------------------------

def test_point_cloud_ascii():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "cloud.ply")
        write_ply(path, _VERTS, [], colors=_COLORS, binary=False)
        result = read_ply(path)

    assert len(result["verts"]) == len(_VERTS)
    assert result["faces"] == []
    assert result["colors"] is not None
    assert result["colors"] == _COLORS
    assert _verts_close(result["verts"], _VERTS)


def test_point_cloud_binary():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "cloud.ply")
        write_ply(path, _VERTS, [], colors=_COLORS, binary=True)
        result = read_ply(path)

    assert len(result["verts"]) == len(_VERTS)
    assert result["faces"] == []
    assert result["colors"] is not None
    assert result["colors"] == _COLORS
    assert _verts_close(result["verts"], _VERTS)


# ---------------------------------------------------------------------------
# Oracle 6: Colour clamping
# ---------------------------------------------------------------------------

def test_color_clamping():
    clamped_colors = [
        [300, -10, 128],   # should clamp to [255, 0, 128]
        [0, 0, 0],
        [255, 255, 255],
        [1, 2, 3],
    ]
    expected = [
        [255, 0, 128],
        [0, 0, 0],
        [255, 255, 255],
        [1, 2, 3],
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "clamped.ply")
        write_ply(path, _VERTS, _FACES, colors=clamped_colors, binary=False)
        result = read_ply(path)

    assert result["colors"] == expected


# ---------------------------------------------------------------------------
# Oracle 7: PlyReadError on corrupt / missing files
# ---------------------------------------------------------------------------

def test_read_missing_file():
    with pytest.raises(PlyReadError):
        read_ply("/nonexistent/path/file.ply")


def test_read_empty_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "empty.ply")
        with open(path, "wb"):
            pass
        with pytest.raises(PlyReadError):
            read_ply(path)


def test_read_no_magic():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "bad.ply")
        with open(path, "w") as fh:
            fh.write("not_ply\nend_header\n")
        with pytest.raises(PlyReadError):
            read_ply(path)


def test_read_no_end_header():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "bad.ply")
        with open(path, "w") as fh:
            fh.write("ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\n")
        with pytest.raises(PlyReadError):
            read_ply(path)


# ---------------------------------------------------------------------------
# Oracle 8: PlyWriteError when colors length != verts length
# ---------------------------------------------------------------------------

def test_write_color_length_mismatch():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "bad.ply")
        bad_colors = [[255, 0, 0]]  # only 1 color for 4 verts
        with pytest.raises(PlyWriteError):
            write_ply(path, _VERTS, _FACES, colors=bad_colors)


# ---------------------------------------------------------------------------
# Oracle 9: Top-level re-exports
# ---------------------------------------------------------------------------

def test_toplevel_reexports():
    assert _read_ply_geom is read_ply
    assert _write_ply_geom is write_ply
    assert _PlyReadErrGeom is PlyReadError
    assert _PlyWriteErrGeom is PlyWriteError

    assert _read_ply_io is read_ply
    assert _write_ply_io is write_ply
    assert _PlyReadErrIO is PlyReadError
    assert _PlyWriteErrIO is PlyWriteError


# ---------------------------------------------------------------------------
# Oracle 10: Fan triangulation of quad face
# ---------------------------------------------------------------------------

def test_fan_triangulation_quad():
    """A quad face [0, 1, 2, 3] must be split into 2 triangles on read."""
    # Write a PLY with one quad face manually (ASCII)
    ply_text = (
        "ply\n"
        "format ascii 1.0\n"
        "element vertex 4\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "element face 1\n"
        "property list uchar int vertex_indices\n"
        "end_header\n"
        "0.0 0.0 0.0\n"
        "1.0 0.0 0.0\n"
        "1.0 1.0 0.0\n"
        "0.0 1.0 0.0\n"
        "4 0 1 2 3\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "quad.ply")
        with open(path, "w") as fh:
            fh.write(ply_text)
        result = read_ply(path)

    assert len(result["verts"]) == 4
    # Quad → 2 triangles
    assert len(result["faces"]) == 2
    assert result["faces"][0] == [0, 1, 2]
    assert result["faces"][1] == [0, 2, 3]


# ---------------------------------------------------------------------------
# Oracle 11: Cross-mode (binary write → ASCII-compatible header check)
# ---------------------------------------------------------------------------

def test_binary_file_starts_with_ply():
    """Binary PLY must still start with 'ply\n' in ASCII header."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(pathlib.Path(tmpdir) / "bin.ply")
        write_ply(path, _VERTS, _FACES, binary=True)
        with open(path, "rb") as fh:
            header_start = fh.read(3)
    assert header_start == b"ply"


# ---------------------------------------------------------------------------
# Oracle 12: Large mesh identity preservation
# ---------------------------------------------------------------------------

def test_large_mesh_roundtrip():
    """100 vertices / 50 faces survive ASCII and binary round-trips."""
    verts = [[float(i), float(i * 2), float(i * 3)] for i in range(100)]
    faces = [[i, i + 1, i + 2] for i in range(0, 98, 2)]  # 49 non-overlapping tris
    colors = [[i % 256, (i * 2) % 256, (i * 3) % 256] for i in range(100)]

    for binary in (False, True):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(pathlib.Path(tmpdir) / "large.ply")
            write_ply(path, verts, faces, colors=colors, binary=binary)
            result = read_ply(path)

        assert len(result["verts"]) == 100
        assert len(result["faces"]) == len(faces)
        assert result["colors"] is not None
        assert len(result["colors"]) == 100
        assert _verts_close(result["verts"], verts)
        assert result["faces"] == faces
        assert result["colors"] == colors
