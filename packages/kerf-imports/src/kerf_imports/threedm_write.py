"""threedm_write.py — Rhino .3dm binary serializer (WRITE side) with Hausdorff oracle.

This module provides a ThreeDmFile dataclass, write_3dm / write_3dm_bytes
serializers, and a hausdorff_distance oracle function for round-trip fidelity
testing.

The underlying chunk-framing format is openNURBS (Rhino .3dm).  Geometry
payloads are encoded in the same minimal binary layout understood by
kerf_cad_core.geom.io.rhino3dm._read_minimal — so the two modules form a
hermetic write→read round-trip oracle without any third-party dependency.

File layout (openNURBS public spec)
------------------------------------
    33-byte file-comment header:
        "3D Geometry File Format  " + version-char + spaces + "\\x1a\\x00"
        (the comment section is exactly 33 bytes)
    Then sequential chunks:
        [4 bytes BE typecode] [4 bytes LE length] [payload]
        If length == 0xFFFFFFFF: 8-byte LE uint64 follows before payload.
    Typecode 0x00000000 (end-mark) terminates the stream.

Object serialization (payload format)
--------------------------------------
NurbsCurve (typecode 0x64000000):
    int32  degree
    int32  n_cv
    uint8  is_rational
    n_k*float64  knots    (n_k = n_cv + degree + 1)
    n_cv*3*float64  control_points  (row-major XYZ)
    [n_cv*float64  weights  — only if is_rational]

NurbsSurface (typecode 0x4A000000):
    int32  degree_u
    int32  degree_v
    int32  nu
    int32  nv
    uint8  is_rational
    n_ku*float64  knots_u  (n_ku = nu + degree_u + 1)
    n_kv*float64  knots_v  (n_kv = nv + degree_v + 1)
    nu*nv*3*float64  control_points (row-major, [i][j][xyz])
    [nu*nv*float64  weights — only if is_rational]

Mesh (typecode 0x20000000):
    int32  n_verts
    int32  n_faces
    n_verts*3*float64  vertices (row-major XYZ)
    [n_faces*3*int32   faces    — only if n_faces > 0]

v1: reader covers the subset written by write_3dm; full openNURBS reader
is a separate effort (see kerf_cad_core.geom.io.rhino3dm for the full
two-tier reader with optional rhino3dm PyPI package).

Public API
----------
    ThreeDmFile
    write_3dm(model, path) -> None
    write_3dm_bytes(model) -> bytes
    hausdorff_distance(surface_a, surface_b, n_samples=100) -> float
    read_threedm_bytes(data) -> ThreeDmFile   (minimal reader, round-trip only)
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface

__all__ = [
    "ThreeDmFile",
    "write_3dm",
    "write_3dm_bytes",
    "hausdorff_distance",
    "read_threedm_bytes",
]

# ---------------------------------------------------------------------------
# Internal chunk typecodes (matches kerf_cad_core.geom.io.rhino3dm constants)
# ---------------------------------------------------------------------------

_TC_NURBS_SRF = 0x4A000000
_TC_NURBS_CRV = 0x64000000
_TC_MESH       = 0x20000000
_TC_END_MARK   = 0x00000000


# ---------------------------------------------------------------------------
# ThreeDmFile dataclass — minimal in-memory model
# ---------------------------------------------------------------------------

@dataclass
class ThreeDmFile:
    """Minimal in-memory model for a .3dm file.

    Attributes
    ----------
    version:
        File version tag stored in the header comment (6 or 7).
    units:
        Measurement units string, e.g. ``'mm'``, ``'m'``, ``'in'``.
        Stored in the header comment; recovered verbatim on round-trip.
    nurbs_curves:
        List of :class:`~kerf_cad_core.geom.nurbs.NurbsCurve` objects.
    nurbs_surfaces:
        List of :class:`~kerf_cad_core.geom.nurbs.NurbsSurface` objects.
    meshes:
        List of mesh dicts, each with keys ``'vertices'`` (ndarray N×3) and
        ``'faces'`` (ndarray F×3 or None).
    """
    version: int = 6
    units: str = "mm"
    nurbs_curves: List[NurbsCurve] = field(default_factory=list)
    nurbs_surfaces: List[NurbsSurface] = field(default_factory=list)
    meshes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Low-level chunk helpers
# ---------------------------------------------------------------------------

def _write_chunk(typecode: int, payload: bytes) -> bytes:
    """Encode a single chunk: [BE typecode 4B][LE length 4B][payload]."""
    length = len(payload)
    if length < 0xFFFFFFFF:
        hdr = struct.pack(">I", typecode) + struct.pack("<I", length)
    else:
        hdr = (struct.pack(">I", typecode)
               + struct.pack("<I", 0xFFFFFFFF)
               + struct.pack("<Q", length))
    return hdr + payload


def _end_mark() -> bytes:
    """Zero-typecode end-mark chunk."""
    return struct.pack(">I", _TC_END_MARK) + struct.pack("<I", 0)


# ---------------------------------------------------------------------------
# Payload encoders
# ---------------------------------------------------------------------------

def _encode_nurbs_curve(crv: NurbsCurve) -> bytes:
    n_cv = crv.num_control_points
    is_rational = 1 if crv.weights is not None else 0
    buf = io.BytesIO()
    buf.write(struct.pack("<ii", crv.degree, n_cv))
    buf.write(struct.pack("<B", is_rational))
    for k in crv.knots:
        buf.write(struct.pack("<d", float(k)))
    for i in range(n_cv):
        for c in crv.control_points[i]:
            buf.write(struct.pack("<d", float(c)))
    if is_rational and crv.weights is not None:
        for w in crv.weights:
            buf.write(struct.pack("<d", float(w)))
    return buf.getvalue()


def _encode_nurbs_surface(srf: NurbsSurface) -> bytes:
    nu, nv = srf.control_points.shape[:2]
    is_rational = 1 if srf.weights is not None else 0
    buf = io.BytesIO()
    buf.write(struct.pack("<ii", srf.degree_u, srf.degree_v))
    buf.write(struct.pack("<ii", nu, nv))
    buf.write(struct.pack("<B", is_rational))
    for k in srf.knots_u:
        buf.write(struct.pack("<d", float(k)))
    for k in srf.knots_v:
        buf.write(struct.pack("<d", float(k)))
    for i in range(nu):
        for j in range(nv):
            for c in srf.control_points[i, j]:
                buf.write(struct.pack("<d", float(c)))
    if is_rational and srf.weights is not None:
        for i in range(nu):
            for j in range(nv):
                buf.write(struct.pack("<d", float(srf.weights[i, j])))
    return buf.getvalue()


def _encode_mesh(mesh: dict) -> bytes:
    verts = np.asarray(mesh.get("vertices", np.empty((0, 3))), dtype=float)
    faces = mesh.get("faces")
    n_verts = len(verts)
    n_faces = 0 if faces is None else len(faces)
    buf = io.BytesIO()
    buf.write(struct.pack("<ii", n_verts, n_faces))
    for i in range(n_verts):
        for c in verts[i]:
            buf.write(struct.pack("<d", float(c)))
    if n_faces > 0 and faces is not None:
        fa = np.asarray(faces, dtype=np.int32)
        for i in range(n_faces):
            for idx in fa[i, :3]:
                buf.write(struct.pack("<i", int(idx)))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Header builder
# ---------------------------------------------------------------------------

def _make_header(version: int, units: str) -> bytes:
    """Build the 33-byte .3dm file-comment header.

    Format: ``3D Geometry File Format  <version_digit><units_tag>\\x1a\\x00``
    padded/truncated to exactly 33 bytes, ending with ``\\x1a\\x00``.

    The units and version are stored as a small metadata prefix inside the
    comment section so that the round-trip reader can recover them.  The
    comment itself is terminated by the openNURBS sentinel ``\\x1a\\x00``.
    """
    # Embed version + units as a compact tag:  "v<ver> <units> "
    ver_tag = f"v{version} {units}"
    magic = b"3D Geometry File Format  "  # 25 bytes
    tag_bytes = ver_tag.encode("ascii", errors="replace")
    # Total 33: 25 magic + up to 6 tag + padding + \x1a\x00
    # We keep it to 31 bytes before the sentinel (31 + 2 = 33).
    body = (magic + tag_bytes)[:31]
    body = body.ljust(31, b" ")
    header = body + b"\x1a\x00"
    assert len(header) == 33, f"header must be 33 bytes, got {len(header)}"
    return header


def _parse_header_meta(header: bytes) -> tuple[int, str]:
    """Extract (version, units) from the 33-byte header comment.

    Returns defaults (6, 'mm') if the tag cannot be parsed.
    """
    # Find sentinel
    try:
        body = header[:31].rstrip(b" \x00")
        # Find "v<n> <units>" suffix after magic
        text = body.decode("ascii", errors="replace")
        idx = text.rfind(" v")
        if idx >= 0:
            tag = text[idx + 1:].strip()
            parts = tag.split()
            if len(parts) >= 2 and parts[0].startswith("v"):
                ver = int(parts[0][1:])
                units = parts[1]
                return ver, units
    except Exception:
        pass
    return 6, "mm"


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

def write_3dm_bytes(model: ThreeDmFile) -> bytes:
    """Serialize *model* to .3dm binary bytes.

    The binary layout is compatible with the minimal reader in
    ``kerf_cad_core.geom.io.rhino3dm._read_minimal`` and with
    :func:`read_threedm_bytes` provided in this module.

    Parameters
    ----------
    model:
        A :class:`ThreeDmFile` instance to serialize.

    Returns
    -------
    bytes
        Complete .3dm file content.
    """
    buf = bytearray()
    buf.extend(_make_header(model.version, model.units))

    for srf in model.nurbs_surfaces:
        payload = _encode_nurbs_surface(srf)
        buf.extend(_write_chunk(_TC_NURBS_SRF, payload))

    for crv in model.nurbs_curves:
        payload = _encode_nurbs_curve(crv)
        buf.extend(_write_chunk(_TC_NURBS_CRV, payload))

    for mesh in model.meshes:
        payload = _encode_mesh(mesh)
        buf.extend(_write_chunk(_TC_MESH, payload))

    buf.extend(_end_mark())
    return bytes(buf)


def write_3dm(model: ThreeDmFile, path: str) -> None:
    """Serialize *model* to a .3dm binary file at *path*.

    Parameters
    ----------
    model:
        A :class:`ThreeDmFile` instance to serialize.
    path:
        Destination file path.  Created or overwritten.

    Raises
    ------
    OSError
        If the file cannot be written.
    """
    data = write_3dm_bytes(model)
    with open(path, "wb") as fh:
        fh.write(data)


# ---------------------------------------------------------------------------
# Minimal reader (round-trip only)
# ---------------------------------------------------------------------------

def read_threedm_bytes(data: bytes) -> ThreeDmFile:
    """Deserialize .3dm bytes into a :class:`ThreeDmFile`.

    This reader covers only the subset written by :func:`write_3dm_bytes`.
    It is sufficient for hermetic round-trip oracle tests.  For production
    reading of arbitrary .3dm files, use
    ``kerf_cad_core.geom.io.rhino3dm.read_3dm``.

    Parameters
    ----------
    data:
        Raw .3dm file bytes.

    Returns
    -------
    ThreeDmFile

    Raises
    ------
    ValueError
        If the data is too short or missing the magic prefix.
    """
    if len(data) < 33:
        raise ValueError("Data too short to be a valid .3dm file")
    if not data[:4].startswith(b"3D G"):
        raise ValueError(
            "Not a .3dm file: missing '3D G' magic in header"
        )

    header = data[:33]
    version, units = _parse_header_meta(header)

    model = ThreeDmFile(version=version, units=units)

    buf = io.BytesIO(data)
    # Skip 33-byte header, then skip to after \x1a sentinel
    sentinel_pos = data.find(b"\x1a", 0, 128)
    if sentinel_pos < 0:
        sentinel_pos = 32
    buf.seek(sentinel_pos + 1)
    # Skip optional \x00 after \x1a
    peek = buf.read(1)
    if peek != b"\x00":
        buf.seek(buf.tell() - 1)

    file_size = len(data)

    _parse_chunks(buf, file_size, model)
    return model


def _read_chunk_header(buf: io.BytesIO):
    """Read (typecode, length) from buf.  Returns (0, 0) at EOF."""
    raw = buf.read(8)
    if len(raw) < 8:
        return 0, 0
    typecode = struct.unpack(">I", raw[:4])[0]
    length_le = struct.unpack("<I", raw[4:8])[0]
    if length_le == 0xFFFFFFFF:
        big = buf.read(8)
        if len(big) < 8:
            return typecode, 0
        length = struct.unpack("<Q", big)[0]
    else:
        length = length_le
    return typecode, length


def _parse_chunks(buf: io.BytesIO, file_size: int, model: ThreeDmFile,
                  depth: int = 0, end_pos: Optional[int] = None) -> None:
    while True:
        pos = buf.tell()
        if end_pos is not None and pos >= end_pos:
            break
        if pos >= file_size:
            break

        typecode, length = _read_chunk_header(buf)
        if typecode == 0 and length == 0:
            break
        if typecode == _TC_END_MARK:
            break

        chunk_data_start = buf.tell()
        chunk_end = chunk_data_start + length if length > 0 else chunk_data_start

        if typecode == _TC_NURBS_SRF:
            try:
                payload = buf.read(length)
                srf = _decode_nurbs_surface(payload)
                if srf is not None:
                    model.nurbs_surfaces.append(srf)
            except Exception:
                pass

        elif typecode == _TC_NURBS_CRV:
            try:
                payload = buf.read(length)
                crv = _decode_nurbs_curve(payload)
                if crv is not None:
                    model.nurbs_curves.append(crv)
            except Exception:
                pass

        elif typecode == _TC_MESH:
            try:
                payload = buf.read(length)
                mesh = _decode_mesh(payload)
                if mesh is not None:
                    model.meshes.append(mesh)
            except Exception:
                pass

        elif length > 0:
            if depth < 8:
                _parse_chunks(buf, file_size, model, depth + 1, chunk_end)
            else:
                buf.seek(chunk_end)

        buf.seek(max(buf.tell(), chunk_end))


def _decode_nurbs_surface(payload: bytes) -> Optional[NurbsSurface]:
    try:
        r = io.BytesIO(payload)
        degree_u, degree_v = struct.unpack("<ii", r.read(8))
        nu, nv = struct.unpack("<ii", r.read(8))
        is_rational = struct.unpack("<B", r.read(1))[0]
        n_ku = nu + degree_u + 1
        knots_u = np.array(struct.unpack(f"<{n_ku}d", r.read(n_ku * 8)))
        n_kv = nv + degree_v + 1
        knots_v = np.array(struct.unpack(f"<{n_kv}d", r.read(n_kv * 8)))
        n_pts = nu * nv * 3
        pts_flat = struct.unpack(f"<{n_pts}d", r.read(n_pts * 8))
        pts = np.array(pts_flat).reshape(nu, nv, 3)
        weights = None
        if is_rational:
            n_w = nu * nv
            weights_flat = struct.unpack(f"<{n_w}d", r.read(n_w * 8))
            weights = np.array(weights_flat).reshape(nu, nv)
        return NurbsSurface(
            degree_u=degree_u, degree_v=degree_v,
            control_points=pts, knots_u=knots_u, knots_v=knots_v,
            weights=weights,
        )
    except Exception:
        return None


def _decode_nurbs_curve(payload: bytes) -> Optional[NurbsCurve]:
    try:
        r = io.BytesIO(payload)
        degree, n_cv = struct.unpack("<ii", r.read(8))
        is_rational = struct.unpack("<B", r.read(1))[0]
        n_k = n_cv + degree + 1
        knots = np.array(struct.unpack(f"<{n_k}d", r.read(n_k * 8)))
        pts_flat = struct.unpack(f"<{n_cv * 3}d", r.read(n_cv * 3 * 8))
        pts = np.array(pts_flat).reshape(n_cv, 3)
        weights = None
        if is_rational:
            weights_flat = struct.unpack(f"<{n_cv}d", r.read(n_cv * 8))
            weights = np.array(weights_flat)
        return NurbsCurve(degree=degree, control_points=pts, knots=knots, weights=weights)
    except Exception:
        return None


def _decode_mesh(payload: bytes) -> Optional[dict]:
    try:
        r = io.BytesIO(payload)
        n_verts, n_faces = struct.unpack("<ii", r.read(8))
        if n_verts > 0:
            verts_flat = struct.unpack(f"<{n_verts * 3}d", r.read(n_verts * 3 * 8))
            verts = np.array(verts_flat).reshape(n_verts, 3)
        else:
            verts = np.empty((0, 3), dtype=float)
        if n_faces > 0:
            faces_flat = struct.unpack(f"<{n_faces * 3}i", r.read(n_faces * 3 * 4))
            faces = np.array(faces_flat, dtype=int).reshape(n_faces, 3)
        else:
            faces = None
        return {"vertices": verts, "faces": faces}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Hausdorff distance oracle
# ---------------------------------------------------------------------------

def hausdorff_distance(
    surface_a: NurbsSurface,
    surface_b: NurbsSurface,
    n_samples: int = 100,
) -> float:
    """Two-sided Hausdorff distance between two NURBS surfaces.

    Samples an (n_samples × n_samples) UV grid on each surface, then
    computes the two-sided Hausdorff distance using naive numpy broadcasting
    (no kd-tree).  Suitable for n_samples ≤ 200.

    The Hausdorff distance is defined as::

        H(A, B) = max(
            max_{a in A} min_{b in B} ||a - b||,
            max_{b in B} min_{a in A} ||a - b||
        )

    Parameters
    ----------
    surface_a, surface_b:
        :class:`~kerf_cad_core.geom.nurbs.NurbsSurface` instances.
    n_samples:
        Number of sample points per UV direction per surface (grid is
        n_samples × n_samples).  Defaults to 100.

    Returns
    -------
    float
        The estimated two-sided Hausdorff distance.
    """
    pts_a = _sample_surface(surface_a, n_samples)  # (N, 3)
    pts_b = _sample_surface(surface_b, n_samples)  # (N, 3)

    # one-sided: for each point in A, min distance to B
    h_ab = _one_sided_hausdorff(pts_a, pts_b)
    h_ba = _one_sided_hausdorff(pts_b, pts_a)
    return float(max(h_ab, h_ba))


def _sample_surface(srf: NurbsSurface, n: int) -> np.ndarray:
    """Sample n×n points on the surface; return (n*n, 3) array."""
    u_min = float(srf.knots_u[0])
    u_max = float(srf.knots_u[-1])
    v_min = float(srf.knots_v[0])
    v_max = float(srf.knots_v[-1])

    # Avoid exact endpoint coincidences on degenerate poles by using linspace
    us = np.linspace(u_min, u_max, n)
    vs = np.linspace(v_min, v_max, n)

    pts = np.zeros((n * n, 3))
    idx = 0
    for u in us:
        for v in vs:
            try:
                p = srf.evaluate(float(u), float(v))
                pts[idx] = p[:3]
            except Exception:
                pts[idx] = np.nan
            idx += 1
    # Drop NaN rows (degenerate poles)
    valid = ~np.any(np.isnan(pts), axis=1)
    return pts[valid]


def _one_sided_hausdorff(pts_from: np.ndarray, pts_to: np.ndarray) -> float:
    """max over pts_from of min-distance to pts_to, using broadcasting."""
    if len(pts_from) == 0 or len(pts_to) == 0:
        return 0.0
    # Chunk pts_from to avoid huge (N, M, 3) arrays in memory
    # For n_samples=100, N=M=10000 — process in blocks of 500
    block = 500
    max_min_dist = 0.0
    for i in range(0, len(pts_from), block):
        chunk = pts_from[i:i + block]  # (B, 3)
        # (B, M, 3)
        diff = chunk[:, np.newaxis, :] - pts_to[np.newaxis, :, :]
        dists = np.sqrt(np.sum(diff ** 2, axis=2))  # (B, M)
        min_dists = np.min(dists, axis=1)  # (B,)
        max_min_dist = max(max_min_dist, float(np.max(min_dists)))
    return max_min_dist
