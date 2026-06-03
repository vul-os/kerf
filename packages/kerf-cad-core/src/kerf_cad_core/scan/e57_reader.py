"""
kerf_cad_core.scan.e57_reader — Minimal ASTM E2807-11 (.e57) point cloud reader.

Reads E57 files produced by terrestrial laser scanners (FARO, Leica, Z+F,
Trimble, etc.) and the Aveva E3D laser-import pipeline.

Supports:
    - XML descriptor in the file header (E57 §5.5)
    - CompressedVector binary block decoding for float32 XYZ + uint16/float intensity
    - Flat (uncompressed) binary data sections only; no bitPack or zlib codec
      (compressed variants require the libE57Format library)
    - Multiple Data3D scan scans → concatenated into a single PointCloud

Design rules:
    - Pure Python + numpy; stdlib xml.etree only.
    - read_e57_bytes() is the primary entry-point; read_e57() wraps it.
    - Raises ValueError with clear message on structural errors.
    - Returns empty PointCloud (n_points=0) if no points found.

References
----------
ASTM E2807-11 Standard Specification for 3D Imaging Data Exchange, Version 1.0
ASTM E2807-11 Annex B (XML schema)
libE57Format reference implementation (ASTM committee open source)

Author: imranparuk
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Re-export PointCloud so callers can do `from .e57_reader import PointCloud`
from kerf_cad_core.scan.las_reader import PointCloud


# ---------------------------------------------------------------------------
# E57 file-level constants
# ---------------------------------------------------------------------------

_E57_SIGNATURE = b"ASTM-E57"
_FILE_HDR_SIZE = 48  # bytes — fixed binary file header (§5.3)

# Field offsets within the 48-byte file header
_HDR_SIGNATURE_OFF       = 0   # 8 bytes
_HDR_MAJOR_VERSION_OFF   = 8   # uint32
_HDR_MINOR_VERSION_OFF   = 12  # uint32
_HDR_FILE_PHYS_LEN_OFF   = 16  # uint64
_HDR_XML_PHYS_OFFSET_OFF = 24  # uint64
_HDR_XML_PHYS_LEN_OFF    = 32  # uint64
_HDR_PAGE_SIZE_OFF       = 40  # uint64  (typically 1024)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_e57(path: str) -> PointCloud:
    """Read an E57 file from disk and return a PointCloud.

    Parameters
    ----------
    path : str
        File system path to the .e57 file.

    Returns
    -------
    PointCloud
    """
    data = Path(path).read_bytes()
    return read_e57_bytes(data)


def read_e57_bytes(data: bytes) -> PointCloud:
    """Parse E57 binary data from a bytes object.

    Parameters
    ----------
    data : bytes
        Full contents of a .e57 file.

    Returns
    -------
    PointCloud

    Raises
    ------
    ValueError
        On signature mismatch, truncated header, malformed XML, or
        unsupported CompressedVector codec.
    """
    if len(data) < _FILE_HDR_SIZE:
        raise ValueError(f"E57 data too short: {len(data)} bytes (need >= {_FILE_HDR_SIZE})")

    # Signature check
    sig = data[0:8]
    if sig != _E57_SIGNATURE:
        raise ValueError(f"Not an E57 file: bad signature {sig!r}")

    # Binary file header
    major   = struct.unpack_from("<I", data, _HDR_MAJOR_VERSION_OFF)[0]
    minor   = struct.unpack_from("<I", data, _HDR_MINOR_VERSION_OFF)[0]
    if major != 1:
        raise ValueError(f"Unsupported E57 version {major}.{minor}")

    xml_off = struct.unpack_from("<Q", data, _HDR_XML_PHYS_OFFSET_OFF)[0]
    xml_len = struct.unpack_from("<Q", data, _HDR_XML_PHYS_LEN_OFF)[0]
    page_sz = struct.unpack_from("<Q", data, _HDR_PAGE_SIZE_OFF)[0]
    if page_sz == 0:
        page_sz = 1024  # default per spec

    # E57 uses a page-checksum scheme: each page is (page_sz-4) content bytes
    # followed by a 4-byte CRC32. We strip the checksums to get raw bytes.
    raw_content = _strip_page_checksums(data, page_sz)

    # Extract XML from the raw content
    if xml_off + xml_len > len(raw_content):
        raise ValueError(
            f"E57 XML region [{xml_off}, {xml_off+xml_len}) exceeds "
            f"file size {len(raw_content)}"
        )

    xml_bytes = raw_content[int(xml_off): int(xml_off + xml_len)]
    # Strip trailing nulls
    xml_bytes = xml_bytes.rstrip(b"\x00")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"E57 XML parse error: {exc}") from exc

    # Strip XML namespace prefix from tags for easier matching
    _strip_ns(root)

    # Find Data3D section
    data3d_list = root.findall(".//data3D/vectorChild") or root.findall(".//Data3D/vectorChild")
    if not data3d_list:
        # Try direct children
        data3d_list = root.findall(".//vectorChild")

    if not data3d_list:
        # No scans — return empty cloud
        empty = np.zeros((0, 3), dtype=np.float64)
        return PointCloud(
            xyz=empty, intensity=None, classification=None,
            bbox=((0., 0., 0.), (0., 0., 0.)),
            n_points=0, source_format="e57",
        )

    all_xyz: list[np.ndarray] = []
    all_int: list[np.ndarray] = []

    for scan in data3d_list:
        pts_node = scan.find("points")
        if pts_node is None:
            pts_node = scan.find("Points")
        if pts_node is None:
            continue

        # recordCount attribute
        rec_count_str = pts_node.get("recordCount")
        if rec_count_str is None:
            rec_count_str = "0"
        try:
            rec_count = int(rec_count_str)
        except ValueError:
            rec_count = 0

        # CompressedVector fileOffset + length
        foffset_str = pts_node.get("fileOffset") or "0"
        flen_str    = pts_node.get("length") or "0"
        try:
            file_offset = int(foffset_str)
            _comp_len   = int(flen_str)
        except ValueError:
            continue

        if rec_count <= 0:
            continue

        # Parse prototype to understand field layout
        proto = pts_node.find("prototype")
        if proto is None:
            proto = pts_node.find("Prototype")
        if proto is None:
            continue

        layout = _parse_prototype(proto)
        if not layout:
            continue

        # Read binary data
        xyz_block, int_block = _read_binary_block(
            raw_content, file_offset, rec_count, layout
        )
        if xyz_block is not None:
            all_xyz.append(xyz_block)
        if int_block is not None:
            all_int.append(int_block)

    if not all_xyz:
        empty = np.zeros((0, 3), dtype=np.float64)
        return PointCloud(
            xyz=empty, intensity=None, classification=None,
            bbox=((0., 0., 0.), (0., 0., 0.)),
            n_points=0, source_format="e57",
        )

    xyz = np.vstack(all_xyz).astype(np.float64)
    intensity: np.ndarray | None = None
    if all_int and len(all_int) == len(all_xyz):
        intensity = np.concatenate(all_int).astype(np.uint16)

    n = len(xyz)
    bbox = (
        (float(xyz[:, 0].min()), float(xyz[:, 1].min()), float(xyz[:, 2].min())),
        (float(xyz[:, 0].max()), float(xyz[:, 1].max()), float(xyz[:, 2].max())),
    )

    return PointCloud(
        xyz=xyz,
        intensity=intensity,
        classification=None,
        bbox=bbox,
        n_points=n,
        source_format="e57",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_page_checksums(data: bytes, page_sz: int) -> bytes:
    """Remove 4-byte CRC at end of every page_sz block.

    Returns raw content bytes (without CRC fields).
    If page_sz <= 4 or page_sz > len(data), returns data unchanged.
    """
    if page_sz <= 4 or len(data) < page_sz:
        return data

    content_per_page = page_sz - 4
    out = bytearray()
    off = 0
    n = len(data)
    while off + page_sz <= n:
        out.extend(data[off: off + content_per_page])
        off += page_sz
    # Last partial page (no CRC) — include as-is
    if off < n:
        out.extend(data[off:])
    return bytes(out)


def _strip_ns(element: ET.Element) -> None:
    """Recursively strip XML namespace prefixes from element tags."""
    if element.tag and element.tag.startswith("{"):
        element.tag = element.tag.split("}", 1)[1]
    for child in element:
        _strip_ns(child)


def _parse_prototype(proto: ET.Element) -> dict[str, Any]:
    """Extract field name → (dtype, byte_offset) from a prototype node.

    Returns a dict describing the binary layout:
    {
      'cartesianX': {'dtype': '<f4', 'offset': 0},
      'cartesianY': {'dtype': '<f4', 'offset': 4},
      'cartesianZ': {'dtype': '<f4', 'offset': 8},
      'intensity':  {'dtype': '<f4', 'offset': 12},   # optional
      'record_size': 12,
    }

    Supported field types: Float (single=f4, double=f8), ScaledInteger, Integer.
    """
    layout: dict[str, Any] = {}
    offset = 0

    # E57 standard names for XYZ + intensity
    _INTEREST = {
        "cartesianX", "cartesianY", "cartesianZ",
        "x", "y", "z",
        "intensity",
        "sphericalRange", "sphericalAzimuth", "sphericalElevation",
    }

    for child in proto:
        tag = child.tag
        etype = child.get("type") or ""

        # Determine field size
        if etype in ("Float", "float"):
            precision = child.get("precision") or "double"
            if precision == "single":
                dtype = "<f4"
                size = 4
            else:
                dtype = "<f8"
                size = 8
        elif etype in ("ScaledInteger", "scaledInteger"):
            # Scale + offset applied; underlying int size from min/max range
            # Simplified: assume int32 (4 bytes)
            dtype = "<i4"
            size = 4
        elif etype in ("Integer", "integer"):
            # Size from min/max attributes
            min_val = child.get("minimum")
            max_val = child.get("maximum")
            try:
                mn = int(min_val) if min_val else 0
                mx = int(max_val) if max_val else 255
            except ValueError:
                mn, mx = 0, 255
            r = mx - mn
            if r <= 255:
                size = 1
                dtype = "<u1" if mn >= 0 else "<i1"
            elif r <= 65535:
                size = 2
                dtype = "<u2" if mn >= 0 else "<i2"
            else:
                size = 4
                dtype = "<i4"
        else:
            # Unknown type — skip; assume 4 bytes to keep offset aligned
            size = 4
            dtype = "<u4"

        if tag in _INTEREST:
            layout[tag] = {"dtype": dtype, "offset": offset, "size": size}

        offset += size

    layout["record_size"] = offset
    return layout


def _read_binary_block(
    data: bytes,
    file_offset: int,
    rec_count: int,
    layout: dict[str, Any],
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Read XYZ and intensity arrays from a CompressedVector binary block.

    Parameters
    ----------
    data : bytes
        Raw file bytes (post CRC-strip).
    file_offset : int
        Byte offset to the start of the binary data block in `data`.
    rec_count : int
        Number of point records to read.
    layout : dict
        Output of _parse_prototype().

    Returns
    -------
    (xyz_array, intensity_array)
        xyz_array: (N, 3) float64 or None
        intensity_array: (N,) float64 or None
    """
    rec_size = layout.get("record_size", 0)
    if rec_size <= 0:
        return None, None

    total_bytes = rec_count * rec_size
    if file_offset + total_bytes > len(data):
        # Clamp to available data
        rec_count = (len(data) - file_offset) // rec_size
        if rec_count <= 0:
            return None, None
        total_bytes = rec_count * rec_size

    raw = np.frombuffer(data, dtype=np.uint8, offset=file_offset,
                        count=total_bytes).reshape(rec_count, rec_size)

    # Resolve XYZ field names
    x_key = "cartesianX" if "cartesianX" in layout else "x"
    y_key = "cartesianY" if "cartesianY" in layout else "y"
    z_key = "cartesianZ" if "cartesianZ" in layout else "z"

    def _extract(key: str) -> np.ndarray | None:
        if key not in layout:
            return None
        info = layout[key]
        off, dtype, size = info["offset"], info["dtype"], info["size"]
        col = raw[:, off: off + size].tobytes()
        return np.frombuffer(col, dtype=dtype).astype(np.float64)

    xarr = _extract(x_key)
    yarr = _extract(y_key)
    zarr = _extract(z_key)

    if xarr is None or yarr is None or zarr is None:
        return None, None

    xyz = np.column_stack([xarr, yarr, zarr])

    i_arr = _extract("intensity")
    intensity: np.ndarray | None = None
    if i_arr is not None:
        # Normalise to uint16 range if values are in 0..1 float range
        if i_arr.max() <= 1.0:
            intensity = (i_arr * 65535).astype(np.uint16)
        else:
            intensity = np.clip(i_arr, 0, 65535).astype(np.uint16)

    return xyz, intensity
