"""
kerf_cad_core.scan.las_reader — Minimal LAS 1.2/1.4 binary point cloud reader.

Reads ASPRS LAS files (formats 0–5) and returns a PointCloud dataclass.

Supports:
    - LAS 1.2 and LAS 1.4 (detected from version minor in header)
    - Point Data Record Formats 0, 1, 2, 3, 6, 7 (XYZ int32 scaled + intensity)
    - Scale factors and offsets from header
    - Classification from extra uint8 field in record

Design rules:
    - Pure Python + numpy; no external LAS library.
    - Never raises on valid files; malformed files raise ValueError with clear message.
    - read_las_bytes() is the primary entry-point; read_las() wraps it.

References
----------
ASPRS LAS Specification 1.4-R15 (2019)
ASPRS LAS Specification 1.2 (2008)

Author: imranparuk
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class PointCloud:
    """Ingested point cloud from a LAS or E57 file."""

    xyz: np.ndarray                      # (N, 3) float64 — world coords
    intensity: np.ndarray | None         # (N,) uint16 or None
    classification: np.ndarray | None    # (N,) uint8  or None
    bbox: tuple[tuple[float, float, float], tuple[float, float, float]]
    n_points: int
    source_format: str                   # "las" | "e57"


# ---------------------------------------------------------------------------
# LAS header layout
# ---------------------------------------------------------------------------

# Public Header Block offsets (LAS 1.2 / 1.4 common prefix)
# All offsets from start of file.
_HDR_SIGNATURE_OFF      = 0    # 4 bytes "LASF"
_HDR_VERSION_MAJOR_OFF  = 24   # 1 byte
_HDR_VERSION_MINOR_OFF  = 25   # 1 byte
_HDR_HEADER_SIZE_OFF    = 94   # uint16 — total header block size in bytes
_HDR_OFFSET_TO_DATA_OFF = 96   # uint32 — offset to start of point data records
_HDR_NVAR_LEN_RECS_OFF  = 100  # uint32 — number of variable-length records
_HDR_POINT_FORMAT_OFF   = 104  # uint8  — point data record format ID (0–5 for 1.2; 6–10 for 1.4)
_HDR_POINT_RECLEN_OFF   = 105  # uint16 — point data record length in bytes
_HDR_POINT_COUNT_OFF    = 107  # uint32 — legacy point count (LAS 1.2); 0 may mean use 64-bit
_HDR_SCALE_X_OFF        = 131  # double
_HDR_SCALE_Y_OFF        = 139  # double
_HDR_SCALE_Z_OFF        = 147  # double
_HDR_OFFSET_X_OFF       = 155  # double
_HDR_OFFSET_Y_OFF       = 163  # double
_HDR_OFFSET_Z_OFF       = 171  # double
# LAS 1.4 extends the header to 375 bytes; 64-bit point count at offset 247
_HDR14_POINT_COUNT_OFF  = 247  # uint64 (LAS 1.4 only)

# Minimum meaningful header size (LAS 1.2 is 227 bytes)
_MIN_HEADER_SIZE = 227


# ---------------------------------------------------------------------------
# Point record field offsets per format (bytes from record start)
# Only formats 0–3 and 6–7 are decoded here.
#
# Format 0: X(4) Y(4) Z(4) I(2) flags(1) class(1) scan_angle(1) user(1) src(2) = 20 bytes
# Format 1: + GPS time (8)  = 28 bytes
# Format 2: + RGB (6)       = 26 bytes
# Format 3: + GPS + RGB     = 34 bytes
# Format 6: X(4) Y(4) Z(4) I(2) retbits(1) flags(1) class(1) user(1) scan_angle(2) src(2) = 30 bytes
# Format 7: + RGB (6)       = 36 bytes
# ---------------------------------------------------------------------------

_FMT_OFFSETS = {
    # fmt: (x_off, y_off, z_off, i_off, cls_off, rec_len)
    0: (0, 4, 8, 12, 15, 20),
    1: (0, 4, 8, 12, 15, 28),
    2: (0, 4, 8, 12, 15, 26),
    3: (0, 4, 8, 12, 15, 34),
    4: (0, 4, 8, 12, 15, 57),   # waveforms — XYZ+I+class decoded same as fmt 1
    5: (0, 4, 8, 12, 15, 63),   # waveforms+RGB
    6: (0, 4, 8, 12, 16, 30),
    7: (0, 4, 8, 12, 16, 36),
    8: (0, 4, 8, 12, 16, 38),
    9: (0, 4, 8, 12, 16, 59),
    10: (0, 4, 8, 12, 16, 67),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_las(path: str) -> PointCloud:
    """Read a LAS file from disk and return a PointCloud.

    Parameters
    ----------
    path : str
        File system path to the .las or .laz file.
        Note: .laz compressed files are NOT supported (LASzip not bundled).

    Returns
    -------
    PointCloud
    """
    data = Path(path).read_bytes()
    return read_las_bytes(data)


def read_las_bytes(data: bytes) -> PointCloud:
    """Parse LAS binary data from a bytes object.

    Parameters
    ----------
    data : bytes
        Full contents of a .las file.

    Returns
    -------
    PointCloud

    Raises
    ------
    ValueError
        On signature mismatch, truncated header, or unsupported format.
    """
    if len(data) < _MIN_HEADER_SIZE:
        raise ValueError(f"LAS data too short: {len(data)} bytes (need >= {_MIN_HEADER_SIZE})")

    # Signature check
    sig = data[0:4]
    if sig != b"LASF":
        raise ValueError(f"Not a LAS file: bad signature {sig!r}")

    # Version
    ver_major = data[_HDR_VERSION_MAJOR_OFF]
    ver_minor = data[_HDR_VERSION_MINOR_OFF]
    if ver_major != 1 or ver_minor not in (0, 1, 2, 3, 4):
        raise ValueError(f"Unsupported LAS version {ver_major}.{ver_minor}")

    # Header size
    hdr_size = struct.unpack_from("<H", data, _HDR_HEADER_SIZE_OFF)[0]
    if hdr_size < _MIN_HEADER_SIZE:
        raise ValueError(f"LAS header size {hdr_size} < minimum {_MIN_HEADER_SIZE}")

    # Offset to point data
    offset_to_data = struct.unpack_from("<I", data, _HDR_OFFSET_TO_DATA_OFF)[0]

    # Point format and record length
    point_format = data[_HDR_POINT_FORMAT_OFF]
    record_len   = struct.unpack_from("<H", data, _HDR_POINT_RECLEN_OFF)[0]

    if point_format not in _FMT_OFFSETS:
        raise ValueError(f"Unsupported LAS point format {point_format}")

    x_off, y_off, z_off, i_off, cls_off, expected_len = _FMT_OFFSETS[point_format]

    # Actual record_len from header takes precedence (LAS allows extra bytes)
    if record_len < expected_len:
        raise ValueError(
            f"Point record length {record_len} too short for format {point_format} "
            f"(need >= {expected_len})"
        )

    # Scale factors and offsets
    sx, sy, sz = struct.unpack_from("<ddd", data, _HDR_SCALE_X_OFF)
    ox, oy, oz = struct.unpack_from("<ddd", data, _HDR_OFFSET_X_OFF)

    # Point count
    n_points_legacy = struct.unpack_from("<I", data, _HDR_POINT_COUNT_OFF)[0]
    if ver_minor == 4 and len(data) >= _HDR14_POINT_COUNT_OFF + 8:
        n_points_64 = struct.unpack_from("<Q", data, _HDR14_POINT_COUNT_OFF)[0]
        n_points = n_points_64 if n_points_64 > 0 else n_points_legacy
    else:
        n_points = n_points_legacy

    # Sanity check: infer from data length if header says 0
    if n_points == 0:
        available = len(data) - offset_to_data
        if record_len > 0 and available > 0:
            n_points = available // record_len

    if n_points <= 0:
        # Return empty cloud rather than raising
        empty = np.zeros((0, 3), dtype=np.float64)
        return PointCloud(
            xyz=empty,
            intensity=None,
            classification=None,
            bbox=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            n_points=0,
            source_format="las",
        )

    # Clamp n_points to what actually fits in the file
    available_bytes = len(data) - offset_to_data
    max_pts = available_bytes // record_len
    if n_points > max_pts:
        n_points = max_pts

    # Read raw integer XYZ + intensity + classification using numpy structured array
    # Build a dtype that covers the minimum fields we need.
    # We read the whole record as uint8 rows and extract manually to avoid
    # dtype padding complexities across format variants.
    raw = np.frombuffer(data, dtype=np.uint8, offset=offset_to_data,
                        count=n_points * record_len)
    raw = raw.reshape(n_points, record_len)

    # Extract int32 X, Y, Z  (little-endian signed 4-byte integers)
    xi = np.frombuffer(raw[:, x_off:x_off+4].tobytes(), dtype="<i4")
    yi = np.frombuffer(raw[:, y_off:y_off+4].tobytes(), dtype="<i4")
    zi = np.frombuffer(raw[:, z_off:z_off+4].tobytes(), dtype="<i4")

    # Apply scale + offset  →  float64 world coordinates
    x = xi.astype(np.float64) * sx + ox
    y = yi.astype(np.float64) * sy + oy
    z = zi.astype(np.float64) * sz + oz

    xyz = np.column_stack([x, y, z])

    # Intensity: uint16 little-endian
    intensity = np.frombuffer(raw[:, i_off:i_off+2].tobytes(), dtype="<u2").copy()

    # Classification: single uint8 (offset after intensity + return bits)
    classification = raw[:, cls_off].copy()

    # Bounding box
    bbox = (
        (float(x.min()), float(y.min()), float(z.min())),
        (float(x.max()), float(y.max()), float(z.max())),
    )

    return PointCloud(
        xyz=xyz,
        intensity=intensity,
        classification=classification,
        bbox=bbox,
        n_points=n_points,
        source_format="las",
    )
