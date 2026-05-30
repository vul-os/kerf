"""
subd_export_gltf.py
===================
Export the Catmull-Clark limit-surface as glTF 2.0 (.gltf JSON or .glb binary).

glTF ("Graphics Language Transmission Format") is the Khronos Group standard
for runtime 3-D asset delivery — the "JPEG of 3D", consumed by Three.js,
Babylon.js, Blender, Unity, and Unreal Engine.

Specification
-------------
Reference: Khronos glTF 2.0 — https://www.khronos.org/gltf/
  §5.1  asset object (required; version="2.0")
  §5.9  buffers, bufferViews, accessors
  §5.12 meshes (mesh.primitives[0].attributes.POSITION + indices)
  §5.13 nodes / scenes
  Appendix A: GLB binary container format (magic=0x46546C67, version=2)

Key structures produced
-----------------------
asset:
    version: "2.0"

meshes[0].primitives[0]:
    attributes:
        POSITION: accessor → VEC3 float32 vertex positions
    indices:    accessor → SCALAR uint32 flat triangle indices
    mode:       4  (TRIANGLES)

buffers[0]: one buffer holding all binary data (base64-embedded for .gltf,
            raw chunk for .glb)

bufferViews:
    [0] → vertex data  (componentType FLOAT, byteStride=12)
    [1] → index data   (componentType UNSIGNED_INT, byteStride=4)

accessors:
    [0] → VEC3 FLOAT, count=n_vertices, min/max bounding box
    [1] → SCALAR UNSIGNED_INT, count=n_triangles*3

Honest limitations (v1)
-----------------------
- **Geometry only** — no materials, textures, normals attribute, animations,
  skinning, morph targets, cameras, or lights are produced.  Only POSITION
  and index data are emitted.  A downstream renderer will shade the mesh with
  default (grey) material.
- Faces from the CC subdivider may be quads; they are triangulated here with a
  simple fan (vertex 0 + consecutive pairs), which is correct for convex quads
  produced by Catmull-Clark subdivision but may introduce subtle artefacts on
  degenerate concave quads.
- No quantisation (KHR_mesh_quantization) or draco compression.
- Pure-Python: uses ``json`` and ``struct`` only; no third-party libraries.

Public API
----------
``export_limit_to_gltf(cage, levels=2, format="gltf") -> bytes``
    Subdivide *cage* for *levels* CC steps and emit glTF 2.0 bytes.
    *format* is ``"gltf"`` (JSON + base64 buffer) or ``"glb"`` (binary GLB).

``parse_gltf(data) -> dict``
    Round-trip parser.  Accepts both .gltf (JSON bytes) and .glb (binary).
    Returns ``{"vertices": [[x,y,z],...], "faces": [[i,j,k],...],
               "asset_version": str, "n_vertices": int, "n_triangles": int}``.

References
----------
- Khronos glTF 2.0 specification: https://www.khronos.org/gltf/
- Catmull, E., Clark, J. (1978). "Recursively generated B-spline surfaces on
  arbitrary topological meshes." Computer-Aided Design, 10(6):350-355.
- Khronos GLB container: https://www.khronos.org/registry/glTF/specs/2.0/glTF-2.0.html#glb-file-format-specification
"""

from __future__ import annotations

import base64
import json
import math
import struct
from typing import Any, Dict, List, Optional, Tuple

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide


# ---------------------------------------------------------------------------
# Constants (glTF 2.0 component types and target types)
# ---------------------------------------------------------------------------

_FLOAT = 5126         # GL_FLOAT
_UNSIGNED_INT = 5125  # GL_UNSIGNED_INT
_ARRAY_BUFFER = 34962          # ARRAY_BUFFER (vertex data)
_ELEMENT_ARRAY_BUFFER = 34963  # ELEMENT_ARRAY_BUFFER (index data)
_TRIANGLES = 4

_GLB_MAGIC = 0x46546C67   # "glTF" little-endian
_GLB_VERSION = 2
_CHUNK_JSON = 0x4E4F534A  # "JSON"
_CHUNK_BIN  = 0x004E4942  # "BIN\0"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cage_to_subd_mesh(cage: Any) -> SubDMesh:
    """Coerce cage (SubDMesh, dict, or duck-typed) to SubDMesh."""
    if isinstance(cage, SubDMesh):
        return cage
    if hasattr(cage, "to_subd_mesh"):
        return cage.to_subd_mesh()
    if isinstance(cage, dict):
        verts = [[float(x) for x in v] for v in cage.get("vertices", [])]
        faces = [[int(i) for i in f] for f in cage.get("faces", [])]
        mesh = SubDMesh(vertices=verts, faces=faces)
        for k, v in cage.get("creases", {}).items():
            if isinstance(k, (list, tuple)) and len(k) == 2:
                mesh.set_crease(int(k[0]), int(k[1]), float(v))
        return mesh
    verts = [[float(x) for x in v] for v in getattr(cage, "vertices", [])]
    faces = [[int(i) for i in f] for f in getattr(cage, "faces", [])]
    mesh = SubDMesh(vertices=verts, faces=faces)
    for k, v in getattr(cage, "creases", {}).items():
        mesh.creases[k] = float(v)
    return mesh


def _triangulate(faces: List[List[int]]) -> List[Tuple[int, int, int]]:
    """Fan-triangulate each polygon face.

    For quads [a, b, c, d] → triangles (a,b,c), (a,c,d).
    For triangles: identity.
    Larger n-gons: fan from vertex 0.
    """
    triangles: List[Tuple[int, int, int]] = []
    for face in faces:
        n = len(face)
        if n < 3:
            continue
        a = face[0]
        for i in range(1, n - 1):
            triangles.append((a, face[i], face[i + 1]))
    return triangles


def _build_binary_buffers(
    vertices: List[List[float]],
    triangles: List[Tuple[int, int, int]],
) -> Tuple[bytes, bytes]:
    """Pack vertices and triangle indices as little-endian binary.

    Returns
    -------
    (vertex_bytes, index_bytes)
        vertex_bytes : n_verts × 3 × float32 (12 bytes/vertex)
        index_bytes  : n_tris  × 3 × uint32   ( 4 bytes/index)
    """
    vb_parts = []
    for v in vertices:
        x, y, z = float(v[0]), float(v[1]), float(v[2])
        vb_parts.append(struct.pack("<fff", x, y, z))
    vertex_bytes = b"".join(vb_parts)

    ib_parts = []
    for tri in triangles:
        ib_parts.append(struct.pack("<III", tri[0], tri[1], tri[2]))
    index_bytes = b"".join(ib_parts)

    return vertex_bytes, index_bytes


def _bounding_box(vertices: List[List[float]]) -> Tuple[List[float], List[float]]:
    """Return ([xmin,ymin,zmin], [xmax,ymax,zmax]) of vertex list."""
    if not vertices:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    xs = [float(v[0]) for v in vertices]
    ys = [float(v[1]) for v in vertices]
    zs = [float(v[2]) for v in vertices]
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


def _pad4(data: bytes) -> bytes:
    """Pad bytes to a 4-byte boundary (required by GLB spec §Appendix A)."""
    rem = len(data) % 4
    if rem:
        data = data + b"\x00" * (4 - rem)
    return data


def _pad4_json(data: bytes) -> bytes:
    """Pad JSON chunk with spaces (0x20) to 4-byte boundary (GLB spec)."""
    rem = len(data) % 4
    if rem:
        data = data + b" " * (4 - rem)
    return data


def _build_gltf_json(
    vertices: List[List[float]],
    triangles: List[Tuple[int, int, int]],
    buffer_uri: Optional[str],
    buffer_byte_length: int,
    vertex_byte_length: int,
    index_byte_length: int,
) -> Dict[str, Any]:
    """Assemble the glTF JSON structure (§5 of the spec).

    Parameters
    ----------
    buffer_uri : str or None
        If str, embedded as ``"data:application/octet-stream;base64,..."``.
        If None, buffer has no URI (GLB binary chunk reference).
    """
    bbox_min, bbox_max = _bounding_box(vertices)

    doc: Dict[str, Any] = {
        "asset": {
            "version": "2.0",
            "generator": "Kerf CAD Core subd_export_gltf (pure-Python)",
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "name": "SubDLimitSurface",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": _TRIANGLES,
                    }
                ],
            }
        ],
        "accessors": [
            {
                # POSITION: VEC3 FLOAT
                "bufferView": 0,
                "byteOffset": 0,
                "componentType": _FLOAT,
                "count": len(vertices),
                "type": "VEC3",
                "min": bbox_min,
                "max": bbox_max,
            },
            {
                # INDICES: SCALAR UNSIGNED_INT
                "bufferView": 1,
                "byteOffset": 0,
                "componentType": _UNSIGNED_INT,
                "count": len(triangles) * 3,
                "type": "SCALAR",
            },
        ],
        "bufferViews": [
            {
                # vertex buffer view
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": vertex_byte_length,
                "target": _ARRAY_BUFFER,
            },
            {
                # index buffer view
                "buffer": 0,
                "byteOffset": vertex_byte_length,
                "byteLength": index_byte_length,
                "target": _ELEMENT_ARRAY_BUFFER,
            },
        ],
        "buffers": [
            {
                "byteLength": buffer_byte_length,
            }
        ],
    }

    if buffer_uri is not None:
        doc["buffers"][0]["uri"] = buffer_uri

    return doc


# ---------------------------------------------------------------------------
# Public: export_limit_to_gltf
# ---------------------------------------------------------------------------

def export_limit_to_gltf(
    cage: Any,
    *,
    levels: int = 2,
    format: str = "gltf",  # noqa: A002  (shadows built-in but matches API convention)
) -> bytes:
    """Export the Catmull-Clark limit-surface as glTF 2.0 bytes.

    Applies *levels* rounds of Catmull-Clark subdivision to *cage*, triangulates
    the resulting quad/triangle faces, and emits a valid glTF 2.0 asset.

    Parameters
    ----------
    cage : SubDMesh | dict | duck-typed
        The control cage.  Accepts the same forms as the other subd exporters:
        ``SubDMesh``, ``{"vertices": ..., "faces": ...}`` dict, or any object
        with ``vertices`` and ``faces`` attributes.
    levels : int
        Number of CC subdivision steps.  ``levels=2`` on a cube cage (6 quads)
        produces 6 × 4² = 96 quads → 192 triangles.  Clamped to [0, 8].
    format : str
        ``"gltf"`` — JSON file with base64-embedded buffer (UTF-8 bytes).
        ``"glb"``  — binary GLB container (§Appendix A).

    Returns
    -------
    bytes
        Valid glTF 2.0 file bytes.

    Notes
    -----
    - **Geometry only** (v1): no materials, normals attribute, textures,
      animations, skinning, morph targets, cameras, or lights.
    - Quad faces are fan-triangulated: [a,b,c,d] → (a,b,c)+(a,c,d).
    - Indices are uint32 (componentType=5125); vertices are float32.
    - GLB padding follows the spec: JSON chunk padded with 0x20 (space),
      BIN\\0 chunk padded with 0x00, both to 4-byte boundaries.
    - No KHR_mesh_quantization or Draco compression.

    References
    ----------
    Khronos glTF 2.0: https://www.khronos.org/gltf/
    Catmull & Clark (1978), CAD 10(6):350-355.
    """
    levels = max(0, min(int(levels), 8))
    fmt = format.lower()
    if fmt not in ("gltf", "glb"):
        raise ValueError(f"format must be 'gltf' or 'glb', got {format!r}")

    try:
        mesh = _cage_to_subd_mesh(cage)
    except Exception as exc:
        raise ValueError(f"subd_export_gltf: cage coercion error: {exc}") from exc

    try:
        subd = catmull_clark_subdivide(mesh, levels=levels)
    except Exception as exc:
        raise ValueError(f"subd_export_gltf: subdivision error: {exc}") from exc

    verts: List[List[float]] = subd.vertices
    faces: List[List[int]] = subd.faces

    triangles = _triangulate(faces)

    vertex_bytes, index_bytes = _build_binary_buffers(verts, triangles)
    buffer_byte_length = len(vertex_bytes) + len(index_bytes)

    if fmt == "gltf":
        # Embed buffer as data URI (base64)
        raw_buf = vertex_bytes + index_bytes
        b64 = base64.b64encode(raw_buf).decode("ascii")
        uri = f"data:application/octet-stream;base64,{b64}"
        doc = _build_gltf_json(
            verts, triangles, uri, buffer_byte_length,
            len(vertex_bytes), len(index_bytes),
        )
        return json.dumps(doc, separators=(",", ":")).encode("utf-8")

    else:  # glb
        doc = _build_gltf_json(
            verts, triangles, None, buffer_byte_length,
            len(vertex_bytes), len(index_bytes),
        )
        json_chunk_data = _pad4_json(
            json.dumps(doc, separators=(",", ":")).encode("utf-8")
        )
        bin_chunk_data = _pad4(vertex_bytes + index_bytes)

        # GLB header: magic(4) + version(4) + total_length(4) = 12 bytes
        # Each chunk: length(4) + type(4) + data = 8 + len(data)
        total_length = (
            12
            + 8 + len(json_chunk_data)
            + 8 + len(bin_chunk_data)
        )

        glb = bytearray()
        # GLB header
        glb += struct.pack("<III", _GLB_MAGIC, _GLB_VERSION, total_length)
        # JSON chunk
        glb += struct.pack("<II", len(json_chunk_data), _CHUNK_JSON)
        glb += json_chunk_data
        # BIN chunk
        glb += struct.pack("<II", len(bin_chunk_data), _CHUNK_BIN)
        glb += bin_chunk_data

        return bytes(glb)


# ---------------------------------------------------------------------------
# Public: parse_gltf
# ---------------------------------------------------------------------------

def parse_gltf(data: bytes) -> Dict[str, Any]:
    """Round-trip parser for glTF 2.0 files (.gltf JSON or .glb binary).

    Reads POSITION (VEC3 FLOAT) and indices (SCALAR UNSIGNED_INT) from the
    first mesh primitive.  Validates ``asset.version == "2.0"``.

    Parameters
    ----------
    data : bytes
        Raw .gltf (JSON) or .glb bytes.

    Returns
    -------
    dict with keys:
        ``asset_version`` : str    — the ``asset.version`` field
        ``n_vertices``    : int    — vertex count from POSITION accessor
        ``n_triangles``   : int    — triangle count (indices // 3)
        ``vertices``      : list   — [[x, y, z], ...] (float32)
        ``faces``         : list   — [[i, j, k], ...] (0-based)

    Raises
    ------
    ValueError
        If the data is not a recognised glTF 2.0 structure.
    """
    # Detect GLB vs JSON
    if len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == _GLB_MAGIC:
        return _parse_glb(data)
    else:
        return _parse_gltf_json(data)


def _parse_gltf_json(data: bytes) -> Dict[str, Any]:
    """Parse a .gltf JSON file (possibly with embedded base64 buffer)."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"parse_gltf: JSON decode error: {exc}") from exc
    return _extract_from_doc(doc, bin_chunk=None)


def _parse_glb(data: bytes) -> Dict[str, Any]:
    """Parse a .glb binary container (GLB spec §Appendix A)."""
    if len(data) < 12:
        raise ValueError("parse_gltf: GLB too short (< 12 bytes)")
    magic, version, total_length = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC:
        raise ValueError(f"parse_gltf: not a GLB file (magic={magic:#010x})")
    if version != 2:
        raise ValueError(f"parse_gltf: unsupported GLB version {version}")

    offset = 12
    json_chunk_data: Optional[bytes] = None
    bin_chunk_data:  Optional[bytes] = None

    while offset < len(data):
        if offset + 8 > len(data):
            break
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk_data = data[offset: offset + chunk_len]
        offset += chunk_len
        if chunk_type == _CHUNK_JSON:
            json_chunk_data = chunk_data
        elif chunk_type == _CHUNK_BIN:
            bin_chunk_data = chunk_data

    if json_chunk_data is None:
        raise ValueError("parse_gltf: GLB has no JSON chunk")

    try:
        doc = json.loads(json_chunk_data.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"parse_gltf: JSON chunk decode error: {exc}") from exc

    return _extract_from_doc(doc, bin_chunk=bin_chunk_data)


def _load_buffer(buf_def: Dict[str, Any], bin_chunk: Optional[bytes]) -> bytes:
    """Load buffer bytes from embedded data URI or GLB binary chunk."""
    uri = buf_def.get("uri", "")
    if uri.startswith("data:"):
        # data:application/octet-stream;base64,<b64>
        comma = uri.find(",")
        if comma == -1:
            raise ValueError("parse_gltf: invalid data URI in buffer")
        return base64.b64decode(uri[comma + 1:])
    if bin_chunk is not None:
        return bin_chunk
    raise ValueError("parse_gltf: buffer has no URI and no GLB binary chunk")


def _extract_from_doc(doc: Dict[str, Any], bin_chunk: Optional[bytes]) -> Dict[str, Any]:
    """Extract mesh geometry from a parsed glTF document dict."""
    asset_version = doc.get("asset", {}).get("version", "")
    if asset_version != "2.0":
        raise ValueError(
            f"parse_gltf: expected asset.version='2.0', got {asset_version!r}"
        )

    meshes = doc.get("meshes", [])
    if not meshes:
        return {
            "asset_version": asset_version,
            "n_vertices": 0,
            "n_triangles": 0,
            "vertices": [],
            "faces": [],
        }

    primitive = meshes[0].get("primitives", [{}])[0]
    pos_acc_idx = primitive.get("attributes", {}).get("POSITION")
    idx_acc_idx = primitive.get("indices")

    accessors = doc.get("accessors", [])
    buffer_views = doc.get("bufferViews", [])
    buffers = doc.get("buffers", [])

    # Load all buffers (usually just one)
    loaded_buffers: List[bytes] = []
    for buf_def in buffers:
        loaded_buffers.append(_load_buffer(buf_def, bin_chunk))

    def _read_accessor(acc_idx: Optional[int]) -> bytes:
        if acc_idx is None:
            return b""
        acc = accessors[acc_idx]
        bv_idx = acc.get("bufferView", 0)
        bv = buffer_views[bv_idx]
        buf_idx = bv.get("buffer", 0)
        buf_data = loaded_buffers[buf_idx]
        bv_offset = bv.get("byteOffset", 0)
        bv_length = bv.get("byteLength", len(buf_data) - bv_offset)
        acc_offset = acc.get("byteOffset", 0)
        start = bv_offset + acc_offset
        return buf_data[start: bv_offset + bv_length]

    # Read vertices
    vertices: List[List[float]] = []
    if pos_acc_idx is not None:
        acc = accessors[pos_acc_idx]
        n_verts = acc.get("count", 0)
        raw = _read_accessor(pos_acc_idx)
        for i in range(n_verts):
            x, y, z = struct.unpack_from("<fff", raw, i * 12)
            vertices.append([x, y, z])

    # Read indices
    faces: List[List[int]] = []
    n_triangles = 0
    if idx_acc_idx is not None:
        acc = accessors[idx_acc_idx]
        n_indices = acc.get("count", 0)
        component_type = acc.get("componentType", _UNSIGNED_INT)
        raw = _read_accessor(idx_acc_idx)
        if component_type == _UNSIGNED_INT:
            fmt_char, stride = "I", 4
        elif component_type == 5123:  # UNSIGNED_SHORT
            fmt_char, stride = "H", 2
        elif component_type == 5121:  # UNSIGNED_BYTE
            fmt_char, stride = "B", 1
        else:
            fmt_char, stride = "I", 4
        indices: List[int] = []
        for i in range(n_indices):
            (val,) = struct.unpack_from(f"<{fmt_char}", raw, i * stride)
            indices.append(val)
        n_triangles = n_indices // 3
        for i in range(n_triangles):
            faces.append([indices[i * 3], indices[i * 3 + 1], indices[i * 3 + 2]])

    return {
        "asset_version": asset_version,
        "n_vertices": len(vertices),
        "n_triangles": n_triangles,
        "vertices": vertices,
        "faces": faces,
    }


# ---------------------------------------------------------------------------
# LLM tool registration (gated)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _subd_export_limit_to_gltf_spec = ToolSpec(
        name="subd_export_limit_to_gltf",
        description=(
            "Export a SubD control cage as a Catmull-Clark limit-surface mesh in "
            "glTF 2.0 format (.gltf JSON or .glb binary).\n"
            "\n"
            "glTF is the Khronos 'JPEG of 3D' — consumed by Three.js, Babylon.js, "
            "Blender, Unity, and Unreal. Applies N levels of Catmull-Clark subdivision "
            "and emits a valid glTF 2.0 asset with POSITION attribute + triangle indices.\n"
            "\n"
            "HONEST LIMITATIONS (v1):\n"
            "  - Geometry only: no materials, normals, textures, animations, skinning.\n"
            "  - Quads fan-triangulated: [a,b,c,d] → (a,b,c)+(a,c,d).\n"
            "  - No KHR_mesh_quantization or Draco compression.\n"
            "\n"
            "Returns:\n"
            "  ok           : bool\n"
            "  gltf_b64     : str   — base64-encoded .gltf or .glb bytes\n"
            "  format       : str   — 'gltf' or 'glb'\n"
            "  n_vertices   : int   — vertex count after subdivision\n"
            "  n_triangles  : int   — triangle count after triangulation\n"
            "  levels_used  : int   — actual subdivision levels applied\n"
            "\n"
            "Errors: {ok: false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices [[x, y, z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists [[i, j, k, l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "creases": {
                    "type": "array",
                    "description": "Optional crease list [{v1, v2, value}, ...].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "value": {"type": "number"},
                        },
                        "required": ["v1", "v2", "value"],
                    },
                },
                "levels": {
                    "type": "integer",
                    "description": "Subdivision levels (default 2, range [0, 8]).",
                    "default": 2,
                    "minimum": 0,
                    "maximum": 8,
                },
                "format": {
                    "type": "string",
                    "description": "'gltf' (JSON + base64 buffer) or 'glb' (binary).",
                    "enum": ["gltf", "glb"],
                    "default": "gltf",
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_export_limit_to_gltf_spec)
    async def run_subd_export_limit_to_gltf(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        levels = int(a.get("levels", 2))
        fmt = str(a.get("format", "gltf")).lower()

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if fmt not in ("gltf", "glb"):
            return err_payload("format must be 'gltf' or 'glb'", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for ce in raw_creases:
            try:
                mesh.set_crease(int(ce["v1"]), int(ce["v2"]), float(ce["value"]))
            except Exception:
                pass

        try:
            gltf_bytes = export_limit_to_gltf(mesh, levels=levels, format=fmt)
        except Exception as exc:
            return err_payload(f"export failed: {exc}", "EXPORT_ERROR")

        try:
            parsed = parse_gltf(gltf_bytes)
        except Exception as exc:
            return err_payload(f"round-trip parse failed: {exc}", "EXPORT_ERROR")

        return ok_payload({
            "ok": True,
            "gltf_b64": base64.b64encode(gltf_bytes).decode("ascii"),
            "format": fmt,
            "n_vertices": parsed["n_vertices"],
            "n_triangles": parsed["n_triangles"],
            "levels_used": max(0, min(int(levels), 8)),
        })
