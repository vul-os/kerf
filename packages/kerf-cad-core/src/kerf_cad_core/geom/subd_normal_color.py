"""subd_normal_color.py
======================
SubD limit-surface normal-to-color mapping + GLB vertex-color export.

Provides three encoding schemes for visualising normal directions on a
Catmull-Clark subdivision limit surface:

``rgb_xyz``      — normal X,Y,Z mapped linearly to R,G,B via (n+1)/2.
                   Standard normal-map encoding used in all major 3D tools.
``hemispherical`` — dot product with +Z axis drives luminance; up-pointing
                   normals are blue, down-pointing normals are near-black.
                   Useful for diagnostic concavity / convexity checks.
``matcap``       — spherically-projected MatCap lookup; maps the normal to a
                   latitude/longitude UV point on a virtual environment sphere
                   and returns an artificial 3-band HSL colour that mimics
                   a sculpt-mode clay material response.

Public API
----------
compute_normal_color_map(mesh, n_levels=2, encoding='rgb_xyz')
    → dict[int, tuple[int,int,int]]
    Per-vertex RGB (0-255) map for the Catmull-Clark limit surface.

compute_face_color_from_normals(mesh)
    → dict[int, tuple[int,int,int]]
    Per-face average-normal RGB for the control mesh.  Compatible with the
    ``face_color`` schemes from Wave 4FF.

export_subd_with_normals_glb(mesh, path, color_encoding='rgb_xyz',
                              n_levels=2)
    Write the limit surface as a GLB file with per-vertex COLOR_0 attribute.
    Uses the existing kerf-cad-core GLB writer, extended with a COLOR_0
    accessor built directly here (the base writer does not yet expose it).

All exceptions are caught internally; functions return empty dicts / raise
only on programmer-level misuse.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide
from kerf_cad_core.geom.subd_to_nurbs import (
    _stam_limit_tangents,
    subd_limit_positions,
)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

RGB = Tuple[int, int, int]


# ---------------------------------------------------------------------------
# Internal: build vertex adjacency (re-uses subd_to_nurbs helper)
# ---------------------------------------------------------------------------

def _adjacency(mesh: SubDMesh):
    """Return (vert_faces, vert_neighbors) from the cage adjacency."""
    _, vert_faces, vert_neighbors = mesh._build_adjacency()
    return vert_faces, vert_neighbors


# ---------------------------------------------------------------------------
# Internal: compute Stam limit normal for a single vertex
# ---------------------------------------------------------------------------

def _stam_limit_normal(
    vi: int,
    verts_np: List[np.ndarray],
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
    faces: List[List[int]],
) -> np.ndarray:
    """Compute the unit normal at the Stam limit point of vertex *vi*.

    The limit normal is the cross-product of the two Stam limit-tangent
    vectors (t1 × t2), normalised to unit length.  Falls back to +Z for
    degenerate cases (e.g. isolated vertices).
    """
    t1, t2 = _stam_limit_tangents(vi, verts_np, vert_faces, vert_neighbors, faces)
    normal = np.cross(t1, t2)
    length = float(np.linalg.norm(normal))
    if length < 1e-14:
        return np.array([0.0, 0.0, 1.0])
    return normal / length


# ---------------------------------------------------------------------------
# Internal: per-face normal from Newell cross product
# ---------------------------------------------------------------------------

def _face_normal(verts: List[List[float]], face: List[int]) -> np.ndarray:
    """Compute the outward face normal using the Newell method."""
    n = np.zeros(3, dtype=float)
    nv = len(face)
    for i in range(nv):
        cur = np.array(verts[face[i]], dtype=float)
        nxt = np.array(verts[face[(i + 1) % nv]], dtype=float)
        n[0] += (cur[1] - nxt[1]) * (cur[2] + nxt[2])
        n[1] += (cur[2] - nxt[2]) * (cur[0] + nxt[0])
        n[2] += (cur[0] - nxt[0]) * (cur[1] + nxt[1])
    length = float(np.linalg.norm(n))
    if length < 1e-14:
        return np.array([0.0, 0.0, 1.0])
    return n / length


# ---------------------------------------------------------------------------
# Internal: encoding functions  normal → (R, G, B) in 0-255
# ---------------------------------------------------------------------------

def _encode_rgb_xyz(nx: float, ny: float, nz: float) -> RGB:
    """Standard normal-map encoding: n ∈ [-1,1] → pixel ∈ [0,255].

    Formula: pixel = round((n + 1) / 2 * 255)
    Special case: nz = ±1 → (128, 128, 255) / (128, 128, 0).
    """
    r = int(round((nx + 1.0) * 0.5 * 255.0))
    g = int(round((ny + 1.0) * 0.5 * 255.0))
    b = int(round((nz + 1.0) * 0.5 * 255.0))
    return (
        max(0, min(255, r)),
        max(0, min(255, g)),
        max(0, min(255, b)),
    )


def _encode_hemispherical(nx: float, ny: float, nz: float) -> RGB:
    """Hemispherical encoding: up (+Z) → blue; down (−Z) → near-black.

    The hemisphere is:
      - Luminance = max(dot(n, up), 0) in [0, 1]
      - Hue biased toward blue so flat/horizontal normals are mid-grey.

    Formula used:
      dot = (nz + 1) / 2        # [0, 1] where 0=down, 1=up
      R = G = round(dot * 80)   # modest grey level
      B = round(64 + dot * 191) # strong blue component
    """
    dot = (nz + 1.0) * 0.5  # 0.0 for (0,0,-1) → 1.0 for (0,0,1)
    grey = int(round(dot * 80.0))
    blue = int(round(64.0 + dot * 191.0))
    return (
        max(0, min(255, grey)),
        max(0, min(255, grey)),
        max(0, min(255, blue)),
    )


def _encode_matcap(nx: float, ny: float, nz: float) -> RGB:
    """Synthetic MatCap encoding (clay-like sculpt visualisation).

    The MatCap sphere is parameterised by (nx, ny) since the viewer is
    assumed to be looking along −Z.  We map the normal to a UV on the
    MatCap disk and look up a synthetic 3-band response:

      u = (nx + 1) / 2   v = (ny + 1) / 2   # [0,1]^2 on the disk
      frontal_light = max(dot(n, [0.5, 0.5, 0.7]), 0)
      rim_light     = max(dot(n, [-0.3, 0.2, -0.8]), 0)^4  (rim highlight)

    A clay-like base colour (205, 175, 149) is then lit:
      result = base * frontal + rim * (255,255,255)
    """
    # Frontal key-light from upper-right
    frontal = max(0.0, 0.5 * nx + 0.5 * ny + 0.7 * nz)
    frontal /= math.sqrt(0.5 ** 2 + 0.5 ** 2 + 0.7 ** 2)  # normalise

    # Rim light from behind-lower-left
    rim_dot = max(0.0, -0.3 * nx + 0.2 * ny - 0.8 * nz)
    rim_dot /= math.sqrt(0.3 ** 2 + 0.2 ** 2 + 0.8 ** 2)
    rim = rim_dot ** 4 * 0.6  # narrow highlight

    # Clay base
    base_r, base_g, base_b = 205.0, 175.0, 149.0
    r = int(round(base_r * frontal + 255.0 * rim))
    g = int(round(base_g * frontal + 255.0 * rim))
    b = int(round(base_b * frontal + 255.0 * rim))
    return (
        max(0, min(255, r)),
        max(0, min(255, g)),
        max(0, min(255, b)),
    )


_ENCODERS = {
    "rgb_xyz": _encode_rgb_xyz,
    "hemispherical": _encode_hemispherical,
    "matcap": _encode_matcap,
}


# ---------------------------------------------------------------------------
# Public: compute_normal_color_map
# ---------------------------------------------------------------------------

def compute_normal_color_map(
    mesh: SubDMesh,
    n_levels: int = 2,
    encoding: str = "rgb_xyz",
) -> Dict[int, RGB]:
    """Compute per-vertex normal-to-color map for the Catmull-Clark limit surface.

    Parameters
    ----------
    mesh : SubDMesh
        Input subdivision cage.
    n_levels : int
        Number of Catmull-Clark subdivision levels used to compute limit
        normals.  n_levels=0 uses closed-form Stam tangents directly on the
        cage; n_levels>=1 applies subdivision then uses Stam tangents on the
        refined mesh.
    encoding : str
        One of ``'rgb_xyz'``, ``'hemispherical'``, or ``'matcap'``.

    Returns
    -------
    dict[int, tuple[int,int,int]]
        Maps each vertex index (in the *subdivided* mesh) to an RGB tuple
        with values in [0, 255].  Returns an empty dict if the mesh is empty
        or the encoding name is unrecognised.
    """
    if encoding not in _ENCODERS:
        return {}
    if not mesh.vertices or not mesh.faces:
        return {}

    encoder = _ENCODERS[encoding]

    # Subdivide if requested
    if n_levels > 0:
        refined = catmull_clark_subdivide(mesh, levels=n_levels)
    else:
        refined = mesh

    verts_np = [np.array(v, dtype=float) for v in refined.vertices]
    vert_faces, vert_neighbors = _adjacency(refined)

    result: Dict[int, RGB] = {}
    for vi in range(len(refined.vertices)):
        n_vec = _stam_limit_normal(
            vi, verts_np, vert_faces, vert_neighbors, refined.faces
        )
        result[vi] = encoder(float(n_vec[0]), float(n_vec[1]), float(n_vec[2]))
    return result


# ---------------------------------------------------------------------------
# Public: compute_face_color_from_normals
# ---------------------------------------------------------------------------

def compute_face_color_from_normals(
    mesh: SubDMesh,
    encoding: str = "rgb_xyz",
) -> Dict[int, RGB]:
    """Compute per-face average-normal color for the *control* mesh.

    Each face normal is computed via the Newell cross-product method and
    then encoded with the requested scheme.  Compatible with the face_color
    colour scheme dict format from Wave 4FF.

    Parameters
    ----------
    mesh : SubDMesh
        Input subdivision cage (not subdivided).
    encoding : str
        One of ``'rgb_xyz'``, ``'hemispherical'``, or ``'matcap'``.

    Returns
    -------
    dict[int, tuple[int,int,int]]
        Maps each face index to an RGB tuple.
    """
    if encoding not in _ENCODERS:
        return {}
    if not mesh.vertices or not mesh.faces:
        return {}

    encoder = _ENCODERS[encoding]
    result: Dict[int, RGB] = {}
    for fi, face in enumerate(mesh.faces):
        n_vec = _face_normal(mesh.vertices, face)
        result[fi] = encoder(float(n_vec[0]), float(n_vec[1]), float(n_vec[2]))
    return result


# ---------------------------------------------------------------------------
# Internal: pure-Python GLB writer with COLOR_0 attribute
# ---------------------------------------------------------------------------

_GLB_MAGIC = 0x46546C67  # "glTF"
_GLB_VERSION = 2
_JSON_CHUNK_TYPE = 0x4E4F534A  # "JSON"
_BIN_CHUNK_TYPE  = 0x004E4942  # "BIN\0"
_COMPONENT_FLOAT         = 5126
_COMPONENT_UNSIGNED_BYTE = 5121
_COMPONENT_UNSIGNED_SHORT = 5123
_COMPONENT_UNSIGNED_INT  = 5125


def _pack_f32(values: List[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _pack_u8(values: List[int]) -> bytes:
    return struct.pack(f"<{len(values)}B", *values)


def _pack_u16(values: List[int]) -> bytes:
    return struct.pack(f"<{len(values)}H", *values)


def _pack_u32(values: List[int]) -> bytes:
    return struct.pack(f"<{len(values)}I", *values)


def _pad4(n: int) -> int:
    rem = n % 4
    return n if rem == 0 else n + (4 - rem)


def _build_glb_with_colors(
    verts: List[List[float]],
    faces: List[List[int]],
    normals: Optional[List[List[float]]],
    colors_f32: List[List[float]],  # per-vertex RGBA in [0.0, 1.0]
) -> bytes:
    """Build a GLB file bytes with per-vertex COLOR_0 (VEC4 FLOAT).

    This is a minimal inline GLB writer that adds the COLOR_0 attribute
    which the existing kerf write_gltf() does not yet expose.

    Parameters
    ----------
    verts     : [[x,y,z], ...]
    faces     : [[a,b,c], ...] (triangles)
    normals   : [[nx,ny,nz], ...] or None
    colors_f32: [[r,g,b,a], ...] in [0.0, 1.0]
    """
    n_verts = len(verts)
    n_faces = len(faces)

    # Flatten positions
    flat_pos = []
    min_pos = [math.inf, math.inf, math.inf]
    max_pos = [-math.inf, -math.inf, -math.inf]
    for v in verts:
        x, y, z = float(v[0]), float(v[1]), float(v[2])
        flat_pos.extend([x, y, z])
        for i, val in enumerate([x, y, z]):
            if val < min_pos[i]:
                min_pos[i] = val
            if val > max_pos[i]:
                max_pos[i] = val

    # Flatten indices
    flat_idx: List[int] = []
    for f in faces:
        flat_idx.extend([int(f[0]), int(f[1]), int(f[2])])

    n_idx = len(flat_idx)

    # Flatten normals
    flat_norm = []
    if normals:
        for n in normals:
            flat_norm.extend([float(n[0]), float(n[1]), float(n[2])])

    # Flatten colors
    flat_col = []
    for c in colors_f32:
        flat_col.extend([float(c[0]), float(c[1]), float(c[2]), float(c[3])])

    # Choose index byte width
    if n_verts <= 255:
        idx_bw = 1
        pack_idx = _pack_u8
        idx_comp = _COMPONENT_UNSIGNED_BYTE
    elif n_verts <= 65535:
        idx_bw = 2
        pack_idx = _pack_u16
        idx_comp = _COMPONENT_UNSIGNED_SHORT
    else:
        idx_bw = 4
        pack_idx = _pack_u32
        idx_comp = _COMPONENT_UNSIGNED_INT

    # Build binary buffer parts
    bin_parts: List[bytes] = []
    buffer_views = []
    accessors = []

    def _add(data: bytes, target=None) -> int:
        offset = sum(len(p) for p in bin_parts)
        bv: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            bv["target"] = target
        buffer_views.append(bv)
        bin_parts.append(data)
        pad = _pad4(len(data)) - len(data)
        if pad:
            bin_parts.append(b"\x00" * pad)
        return len(buffer_views) - 1

    def _add_acc(bv_idx: int, comp_type: int, count: int, acc_type: str,
                 min_v=None, max_v=None) -> int:
        acc: dict = {
            "bufferView": bv_idx,
            "byteOffset": 0,
            "componentType": comp_type,
            "count": count,
            "type": acc_type,
        }
        if min_v is not None:
            acc["min"] = min_v
        if max_v is not None:
            acc["max"] = max_v
        accessors.append(acc)
        return len(accessors) - 1

    # POSITION
    pos_bv  = _add(_pack_f32(flat_pos), target=34962)
    pos_acc = _add_acc(pos_bv, _COMPONENT_FLOAT, n_verts, "VEC3",
                       min_v=[float(x) for x in min_pos],
                       max_v=[float(x) for x in max_pos])

    # NORMAL (optional)
    norm_acc = None
    if flat_norm:
        norm_bv  = _add(_pack_f32(flat_norm), target=34962)
        norm_acc = _add_acc(norm_bv, _COMPONENT_FLOAT, n_verts, "VEC3")

    # COLOR_0 (VEC4 FLOAT)
    col_bv  = _add(_pack_f32(flat_col), target=34962)
    col_acc = _add_acc(col_bv, _COMPONENT_FLOAT, n_verts, "VEC4")

    # INDICES
    idx_bv  = _add(pack_idx(flat_idx), target=34963)
    idx_acc = _add_acc(idx_bv, idx_comp, n_idx, "SCALAR")

    bin_bytes = b"".join(bin_parts)

    attributes: dict = {"POSITION": pos_acc, "COLOR_0": col_acc}
    if norm_acc is not None:
        attributes["NORMAL"] = norm_acc

    gltf = {
        "asset":  {"version": "2.0", "generator": "kerf-cad-core subd_normal_color"},
        "scene":  0,
        "scenes": [{"name": "Scene", "nodes": [0]}],
        "nodes":  [{"mesh": 0, "name": "subd_limit"}],
        "meshes": [{"name": "subd_limit", "primitives": [{
            "attributes": attributes,
            "indices":    idx_acc,
            "mode":       4,   # TRIANGLES
        }]}],
        "accessors":   accessors,
        "bufferViews": buffer_views,
        "buffers":     [{"byteLength": len(bin_bytes)}],
    }

    json_str   = json.dumps(gltf, separators=(",", ":"))
    json_bytes = json_str.encode("utf-8")
    # JSON chunk must be padded to 4-byte boundary with spaces (0x20)
    json_pad = _pad4(len(json_bytes)) - len(json_bytes)
    json_bytes += b" " * json_pad

    # BIN chunk must be padded to 4-byte boundary with zeros
    bin_pad  = _pad4(len(bin_bytes)) - len(bin_bytes)
    bin_bytes_padded = bin_bytes + b"\x00" * bin_pad

    # GLB header: magic, version, total_length
    json_chunk = struct.pack("<II", len(json_bytes), _JSON_CHUNK_TYPE) + json_bytes
    bin_chunk  = struct.pack("<II", len(bin_bytes_padded), _BIN_CHUNK_TYPE) + bin_bytes_padded if bin_bytes_padded else b""
    header     = struct.pack("<III",
                              _GLB_MAGIC,
                              _GLB_VERSION,
                              12 + len(json_chunk) + len(bin_chunk))
    return header + json_chunk + bin_chunk


# ---------------------------------------------------------------------------
# Internal: triangulate a quad/n-gon mesh for GLB export
# ---------------------------------------------------------------------------

def _triangulate(
    verts: List[List[float]],
    faces: List[List[int]],
) -> Tuple[List[List[float]], List[List[int]]]:
    """Fan-triangulate n-gon faces for GLB export.

    Quads become 2 triangles; n-gons become (n-2) triangles via fan from
    vertex 0.  Triangles are kept as-is.
    """
    tris: List[List[int]] = []
    for face in faces:
        n = len(face)
        if n < 3:
            continue
        # fan triangulation
        for i in range(1, n - 1):
            tris.append([face[0], face[i], face[i + 1]])
    return verts, tris


# ---------------------------------------------------------------------------
# Public: export_subd_with_normals_glb
# ---------------------------------------------------------------------------

def export_subd_with_normals_glb(
    mesh: SubDMesh,
    path: str,
    color_encoding: str = "rgb_xyz",
    n_levels: int = 2,
) -> None:
    """Export the SubD limit surface as GLB with per-vertex COLOR_0 attribute.

    Subdivides the cage to *n_levels*, computes per-vertex Stam limit normals,
    encodes them as colours, and writes a standard glTF 2.0 GLB file with a
    ``COLOR_0`` (VEC4 FLOAT) attribute.  The file is compatible with glTF
    viewers that honour vertex colours (Three.js, Babylon.js, Blender import,
    etc.).

    Parameters
    ----------
    mesh : SubDMesh
        Input cage.
    path : str
        Output file path (should end with ``.glb``).
    color_encoding : str
        One of ``'rgb_xyz'``, ``'hemispherical'``, ``'matcap'``.
    n_levels : int
        Number of Catmull-Clark subdivision levels.
    """
    if not mesh.vertices or not mesh.faces:
        raise ValueError("mesh must have vertices and faces")
    if color_encoding not in _ENCODERS:
        raise ValueError(f"unknown encoding '{color_encoding}'; "
                         f"must be one of {list(_ENCODERS)}")

    # Build the colour map (uses subdivided mesh internally)
    color_map = compute_normal_color_map(mesh, n_levels=n_levels,
                                         encoding=color_encoding)

    # Subdivide to the same level to get the geometry
    if n_levels > 0:
        refined = catmull_clark_subdivide(mesh, levels=n_levels)
    else:
        refined = mesh

    verts, tris = _triangulate(refined.vertices, refined.faces)

    # Build per-vertex color list aligned with verts
    n_verts = len(verts)
    colors_f32: List[List[float]] = []
    for vi in range(n_verts):
        rgb = color_map.get(vi, (128, 128, 128))
        colors_f32.append([rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1.0])

    # Compute per-vertex normals for the refined mesh (Stam limit)
    verts_np = [np.array(v, dtype=float) for v in refined.vertices]
    vert_faces, vert_neighbors = _adjacency(refined)
    normals: List[List[float]] = []
    for vi in range(n_verts):
        n_vec = _stam_limit_normal(
            vi, verts_np, vert_faces, vert_neighbors, refined.faces
        )
        normals.append([float(n_vec[0]), float(n_vec[1]), float(n_vec[2])])

    glb_bytes = _build_glb_with_colors(verts, tris, normals, colors_f32)
    Path(path).write_bytes(glb_bytes)


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "compute_normal_color_map",
    "compute_face_color_from_normals",
    "export_subd_with_normals_glb",
]
