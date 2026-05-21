"""
geom/io/ply.py
==============
Pure-Python PLY read/write for triangle meshes + per-vertex colour +
point clouds (GK-126).  Supports both ASCII and binary (little-endian)
PLY variants.  No third-party dependencies — stdlib only (struct, io).

PLY format summary
------------------
A PLY file has two sections:

1. **Header** — plain ASCII lines terminated by ``end_header``.  Declares
   elements (``element vertex N``, ``element face M``) and their properties.

2. **Body** — ASCII or binary payload matching the header declarations.

Vertex element properties recognised by this module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``x`` ``y`` ``z``              — float/double position (required)
* ``red`` ``green`` ``blue``     — uint8 colour (optional)
* ``alpha``                      — uint8 opacity (optional, ignored on write)

Face element properties recognised
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``vertex_indices`` / ``vertex_index`` — list of int (triangle fans split
  to triangles on read; written as triangles on write)

Binary encoding
~~~~~~~~~~~~~~~
Only **binary_little_endian** is written.  Both
``binary_little_endian`` and ``binary_big_endian`` are read.

Public API
----------
``read_ply(path) -> dict``
    Parse a PLY file (ASCII or binary).  Returns::

        {
            "verts":  list of [x, y, z] float,
            "faces":  list of [i, j, k] int,     # empty for point clouds
            "colors": list of [r, g, b] int  or  None,
        }

``write_ply(path, verts, faces, *, colors=None, binary=False) -> None``
    Serialise *verts* + *faces* (+ optional *colors*) to a PLY file.

Exceptions
----------
``PlyReadError``  — any fatal parse/IO error during read.
``PlyWriteError`` — any fatal serialisation/IO error during write.

References
----------
* The PLY Polygon File Format, Greg Turk, 1994.
  http://paulbourke.net/dataformats/ply/
"""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

__all__ = [
    "PlyReadError",
    "PlyWriteError",
    "read_ply",
    "write_ply",
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PlyReadError(Exception):
    """Raised when a PLY file cannot be parsed."""


class PlyWriteError(Exception):
    """Raised when a PLY file cannot be written."""


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

_Verts = List[List[float]]
_Faces = List[List[int]]
_Colors = List[List[int]]  # [[r, g, b], ...]

# ---------------------------------------------------------------------------
# PLY scalar type tables
# ---------------------------------------------------------------------------

# Maps PLY type name → (struct format char, byte size, is_float)
_SCALAR_FMT: Dict[str, Tuple[str, int, bool]] = {
    "char":   ("b", 1, False),
    "uchar":  ("B", 1, False),
    "short":  ("h", 2, False),
    "ushort": ("H", 2, False),
    "int":    ("i", 4, False),
    "uint":   ("I", 4, False),
    "float":  ("f", 4, True),
    "double": ("d", 8, True),
    # Aliases used in some files
    "int8":    ("b", 1, False),
    "uint8":   ("B", 1, False),
    "int16":   ("h", 2, False),
    "uint16":  ("H", 2, False),
    "int32":   ("i", 4, False),
    "uint32":  ("I", 4, False),
    "float32": ("f", 4, True),
    "float64": ("d", 8, True),
}


def _scalar_fmt(type_name: str, big_endian: bool) -> str:
    info = _SCALAR_FMT.get(type_name)
    if info is None:
        raise PlyReadError(f"Unknown PLY scalar type: {type_name!r}")
    endian = ">" if big_endian else "<"
    return endian + info[0]


def _scalar_size(type_name: str) -> int:
    info = _SCALAR_FMT.get(type_name)
    if info is None:
        raise PlyReadError(f"Unknown PLY scalar type: {type_name!r}")
    return info[1]


def _read_scalar(data: bytes, offset: int, type_name: str, big_endian: bool) -> Tuple[object, int]:
    """Return (value, new_offset)."""
    fmt = _scalar_fmt(type_name, big_endian)
    size = _scalar_size(type_name)
    (val,) = struct.unpack_from(fmt, data, offset)
    return val, offset + size


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

class _Property:
    """Represents one ``property`` line in a PLY header element."""
    is_list: bool = False
    name: str = ""
    # For scalar
    scalar_type: str = ""
    # For list
    count_type: str = ""
    value_type: str = ""


def _parse_header(data: bytes) -> Tuple[str, int, List[Dict]]:
    """Parse the PLY header.

    Returns (format_str, body_offset, elements) where each element is::

        {
            "name":       str,
            "count":      int,
            "properties": [_Property, ...],
        }

    *format_str* is one of ``"ascii"``, ``"binary_little_endian"``,
    ``"binary_big_endian"``.
    """
    # Locate end_header token — search in raw bytes (ASCII header)
    marker = b"end_header"
    idx = data.find(marker)
    if idx == -1:
        raise PlyReadError("No 'end_header' token found — not a valid PLY file")

    # Body starts after end_header + newline
    body_start = idx + len(marker)
    while body_start < len(data) and data[body_start:body_start + 1] in (b"\r", b"\n"):
        body_start += 1

    header_bytes = data[:idx]
    try:
        header_text = header_bytes.decode("ascii", errors="replace")
    except Exception as exc:
        raise PlyReadError(f"Cannot decode PLY header: {exc}") from exc

    lines = [ln.strip() for ln in header_text.splitlines()]

    if not lines or lines[0] != "ply":
        raise PlyReadError("File does not start with 'ply' magic")

    fmt = "ascii"
    elements: List[Dict] = []
    current_elem: Optional[Dict] = None

    for line in lines[1:]:
        if not line or line.startswith("comment") or line.startswith("obj_info"):
            continue

        parts = line.split()
        keyword = parts[0] if parts else ""

        if keyword == "format":
            if len(parts) < 2:
                raise PlyReadError(f"Malformed format line: {line!r}")
            fmt = parts[1]

        elif keyword == "element":
            if len(parts) < 3:
                raise PlyReadError(f"Malformed element line: {line!r}")
            try:
                count = int(parts[2])
            except ValueError as exc:
                raise PlyReadError(f"Bad element count in: {line!r}") from exc
            current_elem = {"name": parts[1], "count": count, "properties": []}
            elements.append(current_elem)

        elif keyword == "property":
            if current_elem is None:
                raise PlyReadError("'property' before any 'element'")
            prop = _Property()
            if len(parts) >= 2 and parts[1] == "list":
                # property list <count_type> <value_type> <name>
                if len(parts) < 5:
                    raise PlyReadError(f"Malformed list property: {line!r}")
                prop.is_list = True
                prop.count_type = parts[2]
                prop.value_type = parts[3]
                prop.name = parts[4]
            else:
                # property <type> <name>
                if len(parts) < 3:
                    raise PlyReadError(f"Malformed scalar property: {line!r}")
                prop.is_list = False
                prop.scalar_type = parts[1]
                prop.name = parts[2]
            current_elem["properties"].append(prop)

    return fmt, body_start, elements


# ---------------------------------------------------------------------------
# ASCII body parsing helpers
# ---------------------------------------------------------------------------

def _tokenise_ascii_body(data: bytes, body_start: int) -> List[str]:
    """Return a flat list of whitespace-delimited tokens from the body."""
    try:
        text = data[body_start:].decode("ascii", errors="replace")
    except Exception as exc:
        raise PlyReadError(f"Cannot decode ASCII PLY body: {exc}") from exc
    return text.split()


def _cast_ascii(token: str, type_name: str) -> object:
    info = _SCALAR_FMT.get(type_name)
    if info is None:
        raise PlyReadError(f"Unknown PLY type: {type_name!r}")
    _, _, is_float = info
    try:
        return float(token) if is_float else int(token)
    except ValueError as exc:
        raise PlyReadError(f"Cannot parse {token!r} as {type_name}") from exc


# ---------------------------------------------------------------------------
# Read entry point
# ---------------------------------------------------------------------------

def read_ply(path: str) -> Dict:
    """Parse a PLY file (ASCII or binary little/big endian).

    Parameters
    ----------
    path:
        Path to the ``.ply`` file.

    Returns
    -------
    dict with keys:
        ``verts``  — list of ``[x, y, z]`` float
        ``faces``  — list of ``[i, j, k]`` int (empty list for point clouds)
        ``colors`` — list of ``[r, g, b]`` int (0–255) or ``None``
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise PlyReadError(f"Cannot open PLY file {path!r}: {exc}") from exc

    if not data:
        raise PlyReadError(f"PLY file is empty: {path!r}")

    fmt, body_start, elements = _parse_header(data)

    if fmt == "ascii":
        return _read_ascii_body(data, body_start, elements)
    elif fmt in ("binary_little_endian", "binary_big_endian"):
        big_endian = fmt == "binary_big_endian"
        return _read_binary_body(data, body_start, elements, big_endian)
    else:
        raise PlyReadError(f"Unsupported PLY format: {fmt!r}")


# ---------------------------------------------------------------------------
# ASCII body reader
# ---------------------------------------------------------------------------

def _read_ascii_body(data: bytes, body_start: int, elements: List[Dict]) -> Dict:
    tokens = _tokenise_ascii_body(data, body_start)
    pos = 0  # index into tokens

    verts: _Verts = []
    faces: _Faces = []
    colors: Optional[_Colors] = None
    has_colors = False

    for elem in elements:
        name = elem["name"]
        count = elem["count"]
        props = elem["properties"]

        if name == "vertex":
            prop_names = [p.name for p in props]
            has_x = "x" in prop_names
            has_y = "y" in prop_names
            has_z = "z" in prop_names
            has_r = "red" in prop_names
            has_g = "green" in prop_names
            has_b = "blue" in prop_names
            has_colors = has_r and has_g and has_b

            if has_colors:
                colors = []

            for _ in range(count):
                row: Dict[str, object] = {}
                for prop in props:
                    if prop.is_list:
                        n = int(_cast_ascii(tokens[pos], prop.count_type))
                        pos += 1
                        vals = []
                        for _ in range(n):
                            vals.append(_cast_ascii(tokens[pos], prop.value_type))
                            pos += 1
                        row[prop.name] = vals
                    else:
                        row[prop.name] = _cast_ascii(tokens[pos], prop.scalar_type)
                        pos += 1

                if has_x and has_y and has_z:
                    verts.append([float(row["x"]), float(row["y"]), float(row["z"])])
                if has_colors:
                    colors.append([int(row["red"]), int(row["green"]), int(row["blue"])])

        elif name == "face":
            for _ in range(count):
                row = {}
                for prop in props:
                    if prop.is_list:
                        n = int(_cast_ascii(tokens[pos], prop.count_type))
                        pos += 1
                        vals = []
                        for _ in range(n):
                            vals.append(_cast_ascii(tokens[pos], prop.value_type))
                            pos += 1
                        row[prop.name] = vals
                    else:
                        row[prop.name] = _cast_ascii(tokens[pos], prop.scalar_type)
                        pos += 1

                idx_list = row.get("vertex_indices") or row.get("vertex_index")
                if idx_list is not None:
                    idx_list = [int(v) for v in idx_list]
                    # Fan triangulation
                    for i in range(1, len(idx_list) - 1):
                        faces.append([idx_list[0], idx_list[i], idx_list[i + 1]])

        else:
            # Skip unknown elements
            for _ in range(count):
                for prop in props:
                    if prop.is_list:
                        n = int(_cast_ascii(tokens[pos], prop.count_type))
                        pos += 1
                        pos += n
                    else:
                        pos += 1

    return {"verts": verts, "faces": faces, "colors": colors}


# ---------------------------------------------------------------------------
# Binary body reader
# ---------------------------------------------------------------------------

def _read_binary_body(
    data: bytes, body_start: int, elements: List[Dict], big_endian: bool
) -> Dict:
    offset = body_start

    verts: _Verts = []
    faces: _Faces = []
    colors: Optional[_Colors] = None
    has_colors = False

    for elem in elements:
        name = elem["name"]
        count = elem["count"]
        props = elem["properties"]

        if name == "vertex":
            prop_names = [p.name for p in props]
            has_x = "x" in prop_names
            has_y = "y" in prop_names
            has_z = "z" in prop_names
            has_r = "red" in prop_names
            has_g = "green" in prop_names
            has_b = "blue" in prop_names
            has_colors = has_r and has_g and has_b

            if has_colors:
                colors = []

            for _ in range(count):
                row: Dict[str, object] = {}
                for prop in props:
                    if prop.is_list:
                        cnt_val, offset = _read_scalar(data, offset, prop.count_type, big_endian)
                        n = int(cnt_val)
                        vals = []
                        for _ in range(n):
                            v, offset = _read_scalar(data, offset, prop.value_type, big_endian)
                            vals.append(v)
                        row[prop.name] = vals
                    else:
                        v, offset = _read_scalar(data, offset, prop.scalar_type, big_endian)
                        row[prop.name] = v

                if has_x and has_y and has_z:
                    verts.append([float(row["x"]), float(row["y"]), float(row["z"])])
                if has_colors:
                    colors.append([int(row["red"]), int(row["green"]), int(row["blue"])])

        elif name == "face":
            for _ in range(count):
                row = {}
                for prop in props:
                    if prop.is_list:
                        cnt_val, offset = _read_scalar(data, offset, prop.count_type, big_endian)
                        n = int(cnt_val)
                        vals = []
                        for _ in range(n):
                            v, offset = _read_scalar(data, offset, prop.value_type, big_endian)
                            vals.append(v)
                        row[prop.name] = vals
                    else:
                        v, offset = _read_scalar(data, offset, prop.scalar_type, big_endian)
                        row[prop.name] = v

                idx_list = row.get("vertex_indices") or row.get("vertex_index")
                if idx_list is not None:
                    idx_list = [int(v) for v in idx_list]
                    for i in range(1, len(idx_list) - 1):
                        faces.append([idx_list[0], idx_list[i], idx_list[i + 1]])

        else:
            # Skip unknown elements (must know sizes to skip)
            for _ in range(count):
                for prop in props:
                    if prop.is_list:
                        cnt_val, offset = _read_scalar(data, offset, prop.count_type, big_endian)
                        n = int(cnt_val)
                        val_size = _scalar_size(prop.value_type)
                        offset += n * val_size
                    else:
                        offset += _scalar_size(prop.scalar_type)

    return {"verts": verts, "faces": faces, "colors": colors}


# ---------------------------------------------------------------------------
# Write entry point
# ---------------------------------------------------------------------------

def write_ply(
    path: str,
    verts: _Verts,
    faces: _Faces,
    *,
    colors: Optional[_Colors] = None,
    binary: bool = False,
) -> None:
    """Write a mesh (or point cloud) to a PLY file.

    Parameters
    ----------
    path:
        Destination ``.ply`` path.
    verts:
        List of ``[x, y, z]`` positions.
    faces:
        List of ``[i, j, k]`` triangle indices.  Pass an empty list for a
        point cloud (vertex-only PLY).
    colors:
        Optional list of ``[r, g, b]`` uint8 colours, one per vertex.
        Pass ``None`` to omit colour properties.
    binary:
        Write binary little-endian PLY when ``True`` (default: ASCII).
    """
    if colors is not None and len(colors) != len(verts):
        raise PlyWriteError(
            f"colors length {len(colors)} != verts length {len(verts)}"
        )

    try:
        if binary:
            _write_binary(path, verts, faces, colors)
        else:
            _write_ascii(path, verts, faces, colors)
    except PlyWriteError:
        raise
    except OSError as exc:
        raise PlyWriteError(f"Cannot write PLY file {path!r}: {exc}") from exc
    except Exception as exc:
        raise PlyWriteError(f"PLY write error: {exc}") from exc


# ---------------------------------------------------------------------------
# Header builder (shared by ASCII and binary)
# ---------------------------------------------------------------------------

def _build_header(
    n_verts: int,
    n_faces: int,
    has_colors: bool,
    binary: bool,
) -> str:
    fmt = "binary_little_endian" if binary else "ascii"
    lines = [
        "ply",
        f"format {fmt} 1.0",
        "comment written by kerf-cad-core GK-126",
        f"element vertex {n_verts}",
        "property float x",
        "property float y",
        "property float z",
    ]
    if has_colors:
        lines += [
            "property uchar red",
            "property uchar green",
            "property uchar blue",
        ]
    if n_faces > 0:
        lines += [
            f"element face {n_faces}",
            "property list uchar int vertex_indices",
        ]
    lines.append("end_header")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# ASCII writer
# ---------------------------------------------------------------------------

def _write_ascii(
    path: str,
    verts: _Verts,
    faces: _Faces,
    colors: Optional[_Colors],
) -> None:
    has_colors = colors is not None
    header = _build_header(len(verts), len(faces), has_colors, binary=False)

    with open(path, "w", encoding="ascii", errors="replace") as fh:
        fh.write(header)
        for i, v in enumerate(verts):
            x, y, z = float(v[0]), float(v[1]), float(v[2])
            if has_colors:
                r, g, b = colors[i]
                r = max(0, min(255, int(r)))
                g = max(0, min(255, int(g)))
                b = max(0, min(255, int(b)))
                fh.write(f"{x!r} {y!r} {z!r} {r} {g} {b}\n")
            else:
                fh.write(f"{x!r} {y!r} {z!r}\n")
        for face in faces:
            indices = " ".join(str(int(idx)) for idx in face)
            fh.write(f"3 {indices}\n")


# ---------------------------------------------------------------------------
# Binary writer
# ---------------------------------------------------------------------------

def _write_binary(
    path: str,
    verts: _Verts,
    faces: _Faces,
    colors: Optional[_Colors],
) -> None:
    has_colors = colors is not None
    header = _build_header(len(verts), len(faces), has_colors, binary=True)
    header_bytes = header.encode("ascii")

    with open(path, "wb") as fh:
        fh.write(header_bytes)
        for i, v in enumerate(verts):
            x, y, z = float(v[0]), float(v[1]), float(v[2])
            fh.write(struct.pack("<fff", x, y, z))
            if has_colors:
                r, g, b = colors[i]
                r = max(0, min(255, int(r)))
                g = max(0, min(255, int(g)))
                b = max(0, min(255, int(b)))
                fh.write(struct.pack("BBB", r, g, b))
        for face in faces:
            fh.write(struct.pack("<B", 3))
            for idx in face:
                fh.write(struct.pack("<i", int(idx)))
