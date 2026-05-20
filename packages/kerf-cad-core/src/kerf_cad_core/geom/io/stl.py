"""
geom/io/stl.py
==============
Pure-Python STL read/write for triangle meshes (GK-81).

STL format summary
------------------
Binary STL
~~~~~~~~~~
  - 80-byte header (ignored on read; written as an informational string)
  - uint32 triangle count
  - Per-triangle record (50 bytes each):
      3× float32  normal vector  (nx, ny, nz)
      3× float32  vertex 0       (x, y, z)
      3× float32  vertex 1
      3× float32  vertex 2
      uint16      attribute byte count (ignored; written as 0)

ASCII STL
~~~~~~~~~
  solid <name>
    facet normal <nx> <ny> <nz>
      outer loop
        vertex <x> <y> <z>
        vertex <x> <y> <z>
        vertex <x> <y> <z>
      endloop
    endfacet
    ...
  endsolid <name>

Public API
----------
``read_stl(path) -> dict``
    Parse a binary or ASCII STL file.  Returns::

        {
            "verts":   list of [x, y, z] float,
            "faces":   list of [i, j, k] int  (indices into verts),
            "normals": list of [nx, ny, nz] float  (one per face),
        }

    Vertices are de-duplicated: two vertices are considered identical when all
    three coordinates agree within *merge_tol* (default 1e-7).

``write_stl(path, mesh, *, binary=True, name="kerf") -> None``
    Write a mesh to an STL file.
    *mesh* may be:
      - a ``dict`` with ``"verts"`` and ``"faces"`` keys (normals auto-computed
        when not present as ``"normals"``)
      - an object with ``.verts`` / ``.vertices`` and ``.faces`` attributes

Exceptions
----------
``StlReadError``   — any fatal parse / IO error during read
``StlWriteError``  — any fatal serialisation / IO error during write

References
----------
* StereoLithography Interface Specification, 3D Systems (1989)
"""

from __future__ import annotations

import math
import struct
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "StlReadError",
    "StlWriteError",
    "read_stl",
    "write_stl",
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StlReadError(Exception):
    """Raised when an STL file cannot be parsed."""


class StlWriteError(Exception):
    """Raised when an STL file cannot be written."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_BINARY_HEADER_SIZE = 80
_BINARY_TRIANGLE_SIZE = 50  # 12 floats × 4 bytes + 2 bytes attribute


def _cross(a: List[float], b: List[float]) -> List[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _normalize(v: List[float]) -> List[float]:
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-300:
        return [0.0, 0.0, 1.0]
    return [v[0] / length, v[1] / length, v[2] / length]


def _face_normal(v0: List[float], v1: List[float], v2: List[float]) -> List[float]:
    e1 = [v1[i] - v0[i] for i in range(3)]
    e2 = [v2[i] - v0[i] for i in range(3)]
    return _normalize(_cross(e1, e2))


def _extract_verts_faces(mesh: Any) -> Tuple[List[List[float]], List[List[int]]]:
    """Unpack mesh dict or mesh-like object into (verts, faces)."""
    if isinstance(mesh, dict):
        verts = mesh.get("verts") or mesh.get("vertices")
        faces = mesh.get("faces")
    else:
        verts = getattr(mesh, "verts", None) or getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
    if verts is None or faces is None:
        raise StlWriteError(
            "mesh must have 'verts'/'vertices' and 'faces' keys or attributes"
        )
    return list(verts), list(faces)


def _extract_normals(
    mesh: Any,
    faces: List[List[int]],
    verts: List[List[float]],
) -> List[List[float]]:
    """Return per-face normals from mesh, or compute them from geometry."""
    normals: Optional[List[List[float]]] = None
    if isinstance(mesh, dict):
        normals = mesh.get("normals")
    else:
        normals = getattr(mesh, "normals", None)
    if normals is not None and len(normals) == len(faces):
        return [list(n) for n in normals]
    # Auto-compute
    result = []
    for face in faces:
        v0, v1, v2 = verts[face[0]], verts[face[1]], verts[face[2]]
        result.append(_face_normal(v0, v1, v2))
    return result


# ---------------------------------------------------------------------------
# Vertex de-duplication
# ---------------------------------------------------------------------------

class _VertexMap:
    """Map (x, y, z) tuples → canonical integer index with merge tolerance."""

    def __init__(self, tol: float = 1e-7) -> None:
        self._tol = tol
        self._verts: List[List[float]] = []
        # Exact-match dict for fast path (quantised key → list of indices)
        self._grid: Dict[Tuple[int, int, int], List[int]] = {}

    def _key(self, x: float, y: float, z: float) -> Tuple[int, int, int]:
        scale = 1.0 / self._tol
        return (round(x * scale), round(y * scale), round(z * scale))

    def add(self, x: float, y: float, z: float) -> int:
        key = self._key(x, y, z)
        candidates = self._grid.get(key, [])
        for idx in candidates:
            v = self._verts[idx]
            if (abs(v[0] - x) <= self._tol and
                    abs(v[1] - y) <= self._tol and
                    abs(v[2] - z) <= self._tol):
                return idx
        new_idx = len(self._verts)
        self._verts.append([x, y, z])
        self._grid.setdefault(key, []).append(new_idx)
        return new_idx

    @property
    def verts(self) -> List[List[float]]:
        return self._verts


# ---------------------------------------------------------------------------
# Binary STL detection
# ---------------------------------------------------------------------------

def _looks_binary(data: bytes) -> bool:
    """Heuristic: if the file starts with 'solid' it *might* be ASCII.

    However, some binary STL files also start with 'solid' in the header.
    We use the triangle-count field to decide: if the file size matches
    the binary formula exactly, treat it as binary.
    """
    if len(data) < _BINARY_HEADER_SIZE + 4:
        return False
    tri_count = struct.unpack_from("<I", data, _BINARY_HEADER_SIZE)[0]
    expected = _BINARY_HEADER_SIZE + 4 + tri_count * _BINARY_TRIANGLE_SIZE
    return len(data) == expected


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_stl(path: str, merge_tol: float = 1e-7) -> Dict:
    """Parse a binary or ASCII STL file.

    Parameters
    ----------
    path:
        Path to the ``.stl`` file.
    merge_tol:
        Vertex-merge tolerance (default 1e-7).  Two vertices closer than this
        in every axis are considered identical and share one index.

    Returns
    -------
    dict with keys:
        ``verts``   — list of ``[x, y, z]`` float
        ``faces``   — list of ``[i, j, k]`` int
        ``normals`` — list of ``[nx, ny, nz]`` float, one per face
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise StlReadError(f"Cannot open STL file {path!r}: {exc}") from exc

    if not data:
        raise StlReadError(f"STL file is empty: {path!r}")

    if _looks_binary(data):
        return _read_binary(data, merge_tol)
    return _read_ascii(data, merge_tol)


def _read_binary(data: bytes, merge_tol: float) -> Dict:
    if len(data) < _BINARY_HEADER_SIZE + 4:
        raise StlReadError("Binary STL too short to contain header + count")

    tri_count = struct.unpack_from("<I", data, _BINARY_HEADER_SIZE)[0]
    expected_size = _BINARY_HEADER_SIZE + 4 + tri_count * _BINARY_TRIANGLE_SIZE
    if len(data) < expected_size:
        raise StlReadError(
            f"Binary STL truncated: expected {expected_size} bytes for "
            f"{tri_count} triangles, got {len(data)}"
        )

    vmap = _VertexMap(merge_tol)
    faces: List[List[int]] = []
    normals: List[List[float]] = []

    offset = _BINARY_HEADER_SIZE + 4
    fmt = "<fff fff fff fff H"  # normal + 3 verts + attrib
    size = struct.calcsize(fmt)

    for _ in range(tri_count):
        vals = struct.unpack_from(fmt, data, offset)
        offset += size
        nx, ny, nz = vals[0], vals[1], vals[2]
        x0, y0, z0 = vals[3], vals[4], vals[5]
        x1, y1, z1 = vals[6], vals[7], vals[8]
        x2, y2, z2 = vals[9], vals[10], vals[11]

        i0 = vmap.add(x0, y0, z0)
        i1 = vmap.add(x1, y1, z1)
        i2 = vmap.add(x2, y2, z2)
        faces.append([i0, i1, i2])
        normals.append([nx, ny, nz])

    return {"verts": vmap.verts, "faces": faces, "normals": normals}


def _read_ascii(data: bytes, merge_tol: float) -> Dict:
    try:
        text = data.decode("ascii", errors="replace")
    except Exception as exc:
        raise StlReadError(f"Cannot decode ASCII STL: {exc}") from exc

    vmap = _VertexMap(merge_tol)
    faces: List[List[int]] = []
    normals: List[List[float]] = []

    current_normal: Optional[List[float]] = None
    current_verts: List[List[float]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().lower()

        if line.startswith("facet normal"):
            parts = raw_line.strip().split()
            try:
                nx, ny, nz = float(parts[2]), float(parts[3]), float(parts[4])
            except (IndexError, ValueError) as exc:
                raise StlReadError(
                    f"Malformed facet normal line: {raw_line!r}"
                ) from exc
            current_normal = [nx, ny, nz]
            current_verts = []

        elif line.startswith("vertex"):
            parts = raw_line.strip().split()
            try:
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            except (IndexError, ValueError) as exc:
                raise StlReadError(
                    f"Malformed vertex line: {raw_line!r}"
                ) from exc
            current_verts.append([x, y, z])

        elif line.startswith("endfacet"):
            if current_normal is None:
                raise StlReadError("endfacet encountered without a preceding facet normal")
            if len(current_verts) != 3:
                raise StlReadError(
                    f"Expected 3 vertices per facet, got {len(current_verts)}"
                )
            i0 = vmap.add(*current_verts[0])
            i1 = vmap.add(*current_verts[1])
            i2 = vmap.add(*current_verts[2])
            faces.append([i0, i1, i2])
            normals.append(current_normal)
            current_normal = None
            current_verts = []

    if not faces:
        # Could be an empty solid; only error if the file didn't look like STL at all
        text_stripped = text.strip().lower()
        if not text_stripped.startswith("solid"):
            raise StlReadError("File does not appear to be a valid ASCII STL")

    return {"verts": vmap.verts, "faces": faces, "normals": normals}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_stl(
    path: str,
    mesh: Any,
    *,
    binary: bool = True,
    name: str = "kerf",
) -> None:
    """Write a mesh to an STL file.

    Parameters
    ----------
    path:
        Destination ``.stl`` path.
    mesh:
        A ``dict`` with ``"verts"`` and ``"faces"`` (and optionally ``"normals"``)
        or an object with the corresponding attributes.
    binary:
        Write binary STL (default).  Pass ``binary=False`` for ASCII.
    name:
        Solid name embedded in the header (ASCII mode) or header bytes (binary).
    """
    try:
        verts, faces = _extract_verts_faces(mesh)
    except StlWriteError:
        raise
    except Exception as exc:
        raise StlWriteError(f"Cannot extract mesh data: {exc}") from exc

    normals = _extract_normals(mesh, faces, verts)

    try:
        if binary:
            _write_binary(path, verts, faces, normals, name)
        else:
            _write_ascii(path, verts, faces, normals, name)
    except StlWriteError:
        raise
    except OSError as exc:
        raise StlWriteError(f"Cannot write STL file {path!r}: {exc}") from exc


def _write_binary(
    path: str,
    verts: List[List[float]],
    faces: List[List[int]],
    normals: List[List[float]],
    name: str,
) -> None:
    header_str = f"STL written by kerf-cad-core ({name})"
    header = header_str.encode("ascii", errors="replace")[:80].ljust(80, b"\x00")
    tri_count = len(faces)

    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(struct.pack("<I", tri_count))
        for face, normal in zip(faces, normals):
            nx, ny, nz = normal
            v0, v1, v2 = verts[face[0]], verts[face[1]], verts[face[2]]
            fh.write(struct.pack(
                "<fff fff fff fff H",
                nx, ny, nz,
                v0[0], v0[1], v0[2],
                v1[0], v1[1], v1[2],
                v2[0], v2[1], v2[2],
                0,  # attribute byte count
            ))


def _write_ascii(
    path: str,
    verts: List[List[float]],
    faces: List[List[int]],
    normals: List[List[float]],
    name: str,
) -> None:
    with open(path, "w", encoding="ascii", errors="replace") as fh:
        fh.write(f"solid {name}\n")
        for face, normal in zip(faces, normals):
            nx, ny, nz = normal
            v0, v1, v2 = verts[face[0]], verts[face[1]], verts[face[2]]
            fh.write(f"  facet normal {nx!r} {ny!r} {nz!r}\n")
            fh.write("    outer loop\n")
            fh.write(f"      vertex {v0[0]!r} {v0[1]!r} {v0[2]!r}\n")
            fh.write(f"      vertex {v1[0]!r} {v1[1]!r} {v1[2]!r}\n")
            fh.write(f"      vertex {v2[0]!r} {v2[1]!r} {v2[2]!r}\n")
            fh.write("    endloop\n")
            fh.write("  endfacet\n")
        fh.write(f"endsolid {name}\n")
