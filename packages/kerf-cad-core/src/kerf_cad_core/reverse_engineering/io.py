"""
kerf_cad_core.reverse_engineering.io — Point-cloud file I/O.

Supported formats
-----------------
PLY  — ASCII, binary-little-endian, binary-big-endian (format-line detection).
PCD  — ASCII / binary (DATA ascii / DATA binary).

Return type
-----------
list[list[float]] — every entry is [x, y, z].  Extra fields (normals, colour,
intensity…) are silently ignored.

Errors
------
UnsupportedFormatError  — raised when the format cannot be parsed, is missing
                          required header fields, or the DATA section is corrupt.

Design notes
------------
- Pure Python + struct; zero external deps.
- Binary reads are done in one os.read / bytes.read call per row-block to keep
  I/O tight (no per-byte loop).
- Works on both file paths (str / Path) and bytes / BytesIO objects via the
  _open() helper.

Author: imranparuk
"""
from __future__ import annotations

import io
import os
import struct
from pathlib import Path
from typing import Union

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class UnsupportedFormatError(Exception):
    """Raised when a PLY/PCD file cannot be parsed."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _open_binary(src: Union[str, Path, bytes, "io.IOBase"]) -> io.RawIOBase:
    """Return a readable binary stream from path, bytes, or existing stream."""
    if isinstance(src, (str, Path)):
        return open(src, "rb")  # type: ignore[return-value]
    if isinstance(src, (bytes, bytearray, memoryview)):
        return io.BytesIO(bytes(src))  # type: ignore[return-value]
    if isinstance(src, (io.RawIOBase, io.BufferedIOBase, io.BytesIO)):
        return src  # type: ignore[return-value]
    raise TypeError(f"Unsupported source type: {type(src)}")


# ---------------------------------------------------------------------------
# PLY parser
# ---------------------------------------------------------------------------

# Maps PLY scalar-type tokens to struct format chars and byte widths.
_PLY_TYPE: dict[str, tuple[str, int]] = {
    "char": ("b", 1), "uchar": ("B", 1), "uint8": ("B", 1), "int8": ("b", 1),
    "short": ("h", 2), "ushort": ("H", 2), "int16": ("h", 2), "uint16": ("H", 2),
    "int": ("i", 4), "uint": ("I", 4), "int32": ("i", 4), "uint32": ("I", 4),
    "float": ("f", 4), "float32": ("f", 4),
    "double": ("d", 8), "float64": ("d", 8),
    "long": ("q", 8), "ulong": ("Q", 8),
}


def _parse_ply_header(stream: io.IOBase) -> tuple[str, list[dict], int]:
    """Read and parse a PLY header.

    Returns
    -------
    format_str  : "ascii" | "binary_little_endian" | "binary_big_endian"
    properties  : list of {name, fmt, size} for vertex element
    n_vertices  : number of vertices declared
    """
    magic = stream.readline()
    if not magic.strip().endswith(b"ply"):
        raise UnsupportedFormatError("Not a PLY file (missing 'ply' magic)")

    fmt_str = ""
    n_vertices = 0
    properties: list[dict] = []
    in_vertex = False

    while True:
        raw = stream.readline()
        if not raw:
            raise UnsupportedFormatError("PLY header ended without 'end_header'")
        line = raw.decode("utf-8", errors="replace").strip()
        if line == "end_header":
            break
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "format":
            if len(tokens) < 2:
                raise UnsupportedFormatError("PLY format line malformed")
            fmt_str = tokens[1]
        elif tokens[0] == "element":
            in_vertex = (len(tokens) >= 2 and tokens[1] == "vertex")
            if in_vertex and len(tokens) >= 3:
                try:
                    n_vertices = int(tokens[2])
                except ValueError as exc:
                    raise UnsupportedFormatError(f"PLY vertex count invalid: {tokens[2]}") from exc
        elif tokens[0] == "property" and in_vertex:
            if len(tokens) < 3:
                continue
            type_tok = tokens[1]
            prop_name = tokens[2]
            if type_tok == "list":
                # list property — skip (face data etc.)
                properties.append({"name": prop_name, "fmt": None, "size": None, "is_list": True})
                continue
            if type_tok not in _PLY_TYPE:
                raise UnsupportedFormatError(f"PLY: unknown property type '{type_tok}'")
            fmt_char, byte_size = _PLY_TYPE[type_tok]
            properties.append({
                "name": prop_name,
                "fmt": fmt_char,
                "size": byte_size,
                "is_list": False,
            })

    if not fmt_str:
        raise UnsupportedFormatError("PLY header missing 'format' line")
    if fmt_str not in ("ascii", "binary_little_endian", "binary_big_endian"):
        raise UnsupportedFormatError(f"PLY: unsupported format '{fmt_str}'")
    return fmt_str, properties, n_vertices


def load_ply(src: Union[str, Path, bytes, "io.IOBase"]) -> list[list[float]]:
    """Parse a PLY file and return its vertex coordinates as [[x,y,z], ...].

    Supports ASCII, binary-little-endian, and binary-big-endian PLY.

    Parameters
    ----------
    src : str | Path | bytes | file-like
        File path, raw bytes, or an open binary stream.

    Returns
    -------
    list[list[float]]
        One [x, y, z] per vertex.

    Raises
    ------
    UnsupportedFormatError
        If the file is malformed or lacks x/y/z properties.
    """
    stream = _open_binary(src)
    try:
        fmt_str, properties, n_vertices = _parse_ply_header(stream)

        # Identify x, y, z property indices
        prop_names = [p["name"] for p in properties]
        for required in ("x", "y", "z"):
            if required not in prop_names:
                raise UnsupportedFormatError(f"PLY vertex element missing '{required}' property")

        x_idx = prop_names.index("x")
        y_idx = prop_names.index("y")
        z_idx = prop_names.index("z")

        if fmt_str == "ascii":
            return _load_ply_ascii(stream, properties, n_vertices, x_idx, y_idx, z_idx)
        else:
            endian = "<" if fmt_str == "binary_little_endian" else ">"
            return _load_ply_binary(stream, properties, n_vertices, x_idx, y_idx, z_idx, endian)
    finally:
        if isinstance(src, (str, Path)):
            stream.close()


def _load_ply_ascii(
    stream: io.IOBase,
    properties: list[dict],
    n_vertices: int,
    x_idx: int,
    y_idx: int,
    z_idx: int,
) -> list[list[float]]:
    """Read ASCII PLY vertex data."""
    pts: list[list[float]] = []
    count = 0
    non_list_count = sum(1 for p in properties if not p.get("is_list"))
    while count < n_vertices:
        raw = stream.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        tokens = line.split()
        if len(tokens) < non_list_count:
            raise UnsupportedFormatError(
                f"PLY ASCII: row {count} has {len(tokens)} values, expected ≥{non_list_count}"
            )
        try:
            x = float(tokens[x_idx])
            y = float(tokens[y_idx])
            z = float(tokens[z_idx])
        except (ValueError, IndexError) as exc:
            raise UnsupportedFormatError(f"PLY ASCII: cannot parse row {count}: {exc}") from exc
        pts.append([x, y, z])
        count += 1
    return pts


def _load_ply_binary(
    stream: io.IOBase,
    properties: list[dict],
    n_vertices: int,
    x_idx: int,
    y_idx: int,
    z_idx: int,
    endian: str,
) -> list[list[float]]:
    """Read binary PLY vertex data (little-endian or big-endian)."""
    # Build a struct format string for one vertex row (skip list properties).
    row_fmt_parts: list[str] = []
    row_size = 0
    for p in properties:
        if p.get("is_list"):
            # Cannot handle variable-length lists in a fixed struct; reject.
            raise UnsupportedFormatError(
                "PLY binary: list properties in vertex element are not supported"
            )
        row_fmt_parts.append(p["fmt"])
        row_size += p["size"]

    row_fmt = endian + "".join(row_fmt_parts)
    row_struct = struct.Struct(row_fmt)
    assert row_struct.size == row_size  # sanity

    pts: list[list[float]] = []
    # Read all vertex data in one shot
    data = stream.read(row_size * n_vertices)
    if len(data) < row_size * n_vertices:
        raise UnsupportedFormatError(
            f"PLY binary: file truncated; expected {row_size * n_vertices} bytes, "
            f"got {len(data)}"
        )
    offset = 0
    for _ in range(n_vertices):
        values = row_struct.unpack_from(data, offset)
        offset += row_size
        pts.append([float(values[x_idx]), float(values[y_idx]), float(values[z_idx])])
    return pts


# ---------------------------------------------------------------------------
# PCD parser
# ---------------------------------------------------------------------------

def load_pcd(src: Union[str, Path, bytes, "io.IOBase"]) -> list[list[float]]:
    """Parse a PCD (Point Cloud Data) file and return [[x,y,z], ...].

    Supports DATA ascii and DATA binary.  DATA binary_compressed is not
    supported (raises UnsupportedFormatError).

    Parameters
    ----------
    src : str | Path | bytes | file-like
        File path, raw bytes, or an open binary stream.

    Returns
    -------
    list[list[float]]
        One [x, y, z] per point.

    Raises
    ------
    UnsupportedFormatError
        If the file is malformed or unsupported.
    """
    stream = _open_binary(src)
    try:
        return _parse_pcd(stream)
    finally:
        if isinstance(src, (str, Path)):
            stream.close()


def _parse_pcd(stream: io.IOBase) -> list[list[float]]:
    """Internal PCD parser, reads from an already-open binary stream."""
    fields: list[str] = []
    sizes: list[int] = []
    types: list[str] = []
    count: list[int] = []
    n_points = 0
    data_type = ""
    header_bytes: list[bytes] = []

    # Read header line by line until DATA
    while True:
        raw = stream.readline()
        if not raw:
            raise UnsupportedFormatError("PCD: EOF before DATA line")
        header_bytes.append(raw)
        line = raw.decode("utf-8", errors="replace").strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        key = tokens[0].upper()
        if key == "FIELDS":
            fields = tokens[1:]
        elif key == "SIZE":
            try:
                sizes = [int(t) for t in tokens[1:]]
            except ValueError as exc:
                raise UnsupportedFormatError(f"PCD: invalid SIZE: {exc}") from exc
        elif key == "TYPE":
            types = tokens[1:]
        elif key == "COUNT":
            try:
                count = [int(t) for t in tokens[1:]]
            except ValueError as exc:
                raise UnsupportedFormatError(f"PCD: invalid COUNT: {exc}") from exc
        elif key == "POINTS":
            try:
                n_points = int(tokens[1])
            except (ValueError, IndexError) as exc:
                raise UnsupportedFormatError(f"PCD: invalid POINTS: {exc}") from exc
        elif key == "DATA":
            if len(tokens) < 2:
                raise UnsupportedFormatError("PCD: DATA line missing type")
            data_type = tokens[1].lower()
            break  # header done; binary data follows immediately

    # Validate
    if not fields:
        raise UnsupportedFormatError("PCD: missing FIELDS line")
    for req in ("x", "y", "z"):
        if req not in fields:
            raise UnsupportedFormatError(f"PCD: missing field '{req}'")
    if data_type not in ("ascii", "binary"):
        raise UnsupportedFormatError(
            f"PCD: DATA type '{data_type}' not supported (only ascii / binary)"
        )

    x_idx = fields.index("x")
    y_idx = fields.index("y")
    z_idx = fields.index("z")

    if data_type == "ascii":
        return _load_pcd_ascii(stream, n_points, x_idx, y_idx, z_idx)
    else:
        # Build per-field struct information
        if not sizes:
            raise UnsupportedFormatError("PCD binary: missing SIZE line")
        if not types:
            raise UnsupportedFormatError("PCD binary: missing TYPE line")
        if not count:
            count = [1] * len(fields)
        return _load_pcd_binary(stream, fields, sizes, types, count, n_points, x_idx, y_idx, z_idx)


def _load_pcd_ascii(
    stream: io.IOBase,
    n_points: int,
    x_idx: int,
    y_idx: int,
    z_idx: int,
) -> list[list[float]]:
    """Read ASCII PCD data."""
    pts: list[list[float]] = []
    read = 0
    while read < n_points:
        raw = stream.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        try:
            x = float(tokens[x_idx])
            y = float(tokens[y_idx])
            z = float(tokens[z_idx])
        except (ValueError, IndexError) as exc:
            raise UnsupportedFormatError(
                f"PCD ASCII: cannot parse row {read}: {exc}"
            ) from exc
        pts.append([x, y, z])
        read += 1
    return pts


# Maps PCD type codes + size to struct format chars (per element).
_PCD_FMT: dict[tuple[str, int], str] = {
    ("I", 1): "b", ("U", 1): "B",
    ("I", 2): "h", ("U", 2): "H",
    ("I", 4): "i", ("U", 4): "I",
    ("I", 8): "q", ("U", 8): "Q",
    ("F", 4): "f",
    ("F", 8): "d",
}


def _load_pcd_binary(
    stream: io.IOBase,
    fields: list[str],
    sizes: list[int],
    types: list[str],
    count: list[int],
    n_points: int,
    x_idx: int,
    y_idx: int,
    z_idx: int,
) -> list[list[float]]:
    """Read binary (little-endian) PCD data."""
    # PCD binary is always little-endian.
    # Build a flat struct for one point row (expanding count>1 fields).
    fmt_chars: list[str] = []
    flat_x_idx = 0
    flat_y_idx = 0
    flat_z_idx = 0
    flat_pos = 0

    for fi, (f, sz, tp, ct) in enumerate(zip(fields, sizes, types, count)):
        key = (tp.upper(), sz)
        if key not in _PCD_FMT:
            raise UnsupportedFormatError(
                f"PCD binary: unsupported field type {tp}/{sz} for field '{f}'"
            )
        fc = _PCD_FMT[key]
        if fi == x_idx:
            flat_x_idx = flat_pos
        if fi == y_idx:
            flat_y_idx = flat_pos
        if fi == z_idx:
            flat_z_idx = flat_pos
        for _ in range(ct):
            fmt_chars.append(fc)
        flat_pos += ct

    row_fmt = "<" + "".join(fmt_chars)
    row_struct = struct.Struct(row_fmt)
    row_size = row_struct.size

    data = stream.read(row_size * n_points)
    if len(data) < row_size * n_points:
        raise UnsupportedFormatError(
            f"PCD binary: file truncated; expected {row_size * n_points} bytes, "
            f"got {len(data)}"
        )

    pts: list[list[float]] = []
    offset = 0
    for _ in range(n_points):
        row = row_struct.unpack_from(data, offset)
        offset += row_size
        pts.append([float(row[flat_x_idx]), float(row[flat_y_idx]), float(row[flat_z_idx])])
    return pts
