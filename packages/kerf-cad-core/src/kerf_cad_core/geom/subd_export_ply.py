"""
subd_export_ply.py
==================
Export the Catmull-Clark limit-surface as a Stanford PLY (Polygon File Format).
Both ASCII and binary little-endian formats are supported.

PLY format specification
------------------------
Reference: https://en.wikipedia.org/wiki/PLY_(file_format)
Original spec: Turk, G. (1994) "The PLY Polygon File Format", Stanford Univ.

PLY grammar (header):
    ply
    format <ascii|binary_little_endian|binary_big_endian> <version>
    element vertex <N>
    property float x
    property float y
    property float z
    element face <F>
    property list uchar int vertex_indices
    end_header

Data follows immediately after the ``end_header`` line (newline-terminated for
ASCII; raw bytes for binary formats).

Honest limitations (v1)
-----------------------
- **Geometry only** — no per-vertex colour (red/green/blue/alpha), texture
  coordinates, or material references.  PLY is highly extensible via property
  declarations; those extensions are intentionally absent here to keep the
  output minimal and broadly compatible.
- No binary big-endian output; only ``ascii`` and ``binary_little_endian``
  are implemented.
- Vertex normals are not emitted (PLY supports ``property float nx/ny/nz``
  as additional vertex properties; this is a v2 item).
- Crease sharpness is respected by the CC subdivider but is NOT encoded in the
  PLY payload (PLY has no crease semantics).

Public API
----------
``export_limit_to_ply(cage, levels=2, format="ascii") -> bytes``
    Subdivide *cage* and emit a PLY byte string.  *format* is ``"ascii"`` or
    ``"binary_little_endian"``.

``parse_ply(data) -> dict``
    Minimal PLY parser for round-trip oracle tests.  Returns
    ``{"vertices": [[x,y,z],...], "faces": [[...],...]}``.

References
----------
- PLY: https://en.wikipedia.org/wiki/PLY_(file_format)
- Turk, G. (1994). *The PLY Polygon File Format*, Stanford University.
- Catmull, E., Clark, J. (1978). "Recursively generated B-spline surfaces on
  arbitrary topological meshes." Computer-Aided Design, 10(6):350-355.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Tuple

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide


# ---------------------------------------------------------------------------
# Internal helpers — shared with other subd exporters
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


# ---------------------------------------------------------------------------
# Public: export_limit_to_ply
# ---------------------------------------------------------------------------

def export_limit_to_ply(
    cage: Any,
    *,
    levels: int = 2,
    format: str = "ascii",  # noqa: A002 — shadow builtin intentional for API clarity
) -> bytes:
    """Export the Catmull-Clark limit-surface approximation as a PLY file.

    Applies *levels* rounds of Catmull-Clark subdivision to *cage* and emits
    the resulting mesh as a PLY byte string.

    Parameters
    ----------
    cage : SubDMesh | dict | duck-typed
        The control cage.  Accepts the same forms as other subd exporters.
    levels : int
        Number of CC subdivision steps.  ``levels=2`` on a cube cage (6 quads)
        produces 6 × 4² = 96 quads.  Clamped to [0, 8].
    format : str
        PLY format string.  One of:
        - ``"ascii"`` — human-readable ASCII text.
        - ``"binary_little_endian"`` — compact binary (IEEE 754 little-endian
          floats for x/y/z, 32-bit little-endian ints for face indices).

    Returns
    -------
    bytes
        Valid PLY content (header + data), ready to write to a ``.ply`` file.

    Raises
    ------
    ValueError
        If *format* is not one of the supported values.

    Notes
    -----
    - **Geometry only**: no colour, normals, texture coordinates, or materials.
    - Crease sharpness is respected by the CC subdivider but is NOT stored
      in the PLY payload.
    - ``property list uchar int vertex_indices`` uses an unsigned-byte count
      prefix and 32-bit signed-int indices, matching the most common PLY
      convention (accepted by MeshLab, Blender, CloudCompare, etc.).

    References
    ----------
    PLY spec: https://en.wikipedia.org/wiki/PLY_(file_format)
    Turk (1994), "The PLY Polygon File Format", Stanford University.
    Catmull & Clark (1978), CAD 10(6):350-355.
    """
    format = format.lower().strip()
    if format not in ("ascii", "binary_little_endian"):
        raise ValueError(
            f"format must be 'ascii' or 'binary_little_endian', got {format!r}"
        )

    levels = max(0, min(int(levels), 8))

    mesh = _cage_to_subd_mesh(cage)
    subd = catmull_clark_subdivide(mesh, levels=levels)

    verts: List[List[float]] = subd.vertices
    faces: List[List[int]] = subd.faces

    # --- Build header (always ASCII) ----------------------------------------
    header_lines = [
        "ply",
        f"format {format} 1.0",
        "comment Catmull-Clark limit-surface mesh exported by Kerf CAD Core",
        "comment Geometry only: no colour, normals, or texture coordinates.",
        "comment Reference: https://en.wikipedia.org/wiki/PLY_(file_format)",
        f"element vertex {len(verts)}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "end_header",
    ]
    header_bytes = "\n".join(header_lines).encode("ascii") + b"\n"

    if format == "ascii":
        return _build_ascii(header_bytes, verts, faces)
    else:
        return _build_binary_le(header_bytes, verts, faces)


def _fmt_ply_float(f: float) -> str:
    """Format float for PLY ASCII output (6 significant figures)."""
    return f"{f:.6g}"


def _build_ascii(
    header: bytes,
    verts: List[List[float]],
    faces: List[List[int]],
) -> bytes:
    """Build ASCII PLY body and concatenate with header."""
    lines: List[str] = []
    for v in verts:
        x, y, z = float(v[0]), float(v[1]), float(v[2])
        lines.append(f"{_fmt_ply_float(x)} {_fmt_ply_float(y)} {_fmt_ply_float(z)}")
    for face in faces:
        n = len(face)
        indices = " ".join(str(i) for i in face)
        lines.append(f"{n} {indices}")
    body = "\n".join(lines).encode("ascii")
    if body:
        body += b"\n"
    return header + body


def _build_binary_le(
    header: bytes,
    verts: List[List[float]],
    faces: List[List[int]],
) -> bytes:
    """Build binary little-endian PLY body and concatenate with header.

    Vertex data: 3 × float32 (little-endian) per vertex.
    Face data: uchar (count) + count × int32 (little-endian) per face.

    Using ``struct`` from the Python standard library (no numpy dependency).
    """
    parts: List[bytes] = [header]
    # Vertices: pack 3 floats per vertex
    for v in verts:
        parts.append(struct.pack("<fff", float(v[0]), float(v[1]), float(v[2])))
    # Faces: uchar count + int32 per index
    for face in faces:
        n = len(face)
        # uchar (B) + n × int32 (i)
        parts.append(struct.pack(f"<B{n}i", n, *face))
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Public: parse_ply
# ---------------------------------------------------------------------------

def parse_ply(data: bytes) -> Dict[str, Any]:
    """Minimal PLY parser for round-trip oracle tests.

    Handles the subset of PLY emitted by :func:`export_limit_to_ply`:
    - ASCII and binary little-endian formats.
    - ``property float x/y/z`` vertex properties.
    - ``property list uchar int vertex_indices`` face lists.

    Parameters
    ----------
    data : bytes
        Raw PLY content (header + data).

    Returns
    -------
    dict with keys:
        ``vertices`` : list of [x, y, z] floats
        ``faces``    : list of lists of 0-based vertex indices

    Notes
    -----
    This parser is intentionally narrow — it only handles the PLY dialect
    emitted by this module.  It is NOT a general-purpose PLY parser.
    """
    # Split header from data body
    header_end = data.find(b"end_header\n")
    if header_end == -1:
        header_end = data.find(b"end_header\r\n")
        if header_end == -1:
            return {"vertices": [], "faces": []}
        body_start = header_end + len(b"end_header\r\n")
    else:
        body_start = header_end + len(b"end_header\n")

    header_text = data[:header_end].decode("ascii", errors="replace")
    body = data[body_start:]

    # Parse header to determine format + element/property schema
    fmt, n_verts, n_faces = _parse_ply_header(header_text)

    if fmt == "ascii":
        return _parse_ascii_body(body, n_verts, n_faces)
    elif fmt == "binary_little_endian":
        return _parse_binary_le_body(body, n_verts, n_faces)
    else:
        return {"vertices": [], "faces": []}


def _parse_ply_header(header_text: str) -> Tuple[str, int, int]:
    """Extract (format, n_verts, n_faces) from PLY header text."""
    fmt = "ascii"
    n_verts = 0
    n_faces = 0
    current_element = None

    for line in header_text.splitlines():
        line = line.strip()
        if not line or line.startswith("comment") or line == "ply":
            continue
        parts = line.split()
        if parts[0] == "format":
            fmt = parts[1].lower() if len(parts) >= 2 else "ascii"
        elif parts[0] == "element":
            current_element = parts[1] if len(parts) >= 2 else None
            count = int(parts[2]) if len(parts) >= 3 else 0
            if current_element == "vertex":
                n_verts = count
            elif current_element == "face":
                n_faces = count
    return fmt, n_verts, n_faces


def _parse_ascii_body(
    body: bytes,
    n_verts: int,
    n_faces: int,
) -> Dict[str, Any]:
    """Parse ASCII PLY data body."""
    lines = body.decode("ascii", errors="replace").splitlines()
    # Remove empty lines
    lines = [l for l in lines if l.strip()]

    vertices: List[List[float]] = []
    faces: List[List[int]] = []

    for i in range(n_verts):
        if i >= len(lines):
            break
        parts = lines[i].split()
        try:
            vertices.append([float(parts[0]), float(parts[1]), float(parts[2])])
        except (IndexError, ValueError):
            vertices.append([0.0, 0.0, 0.0])

    for j in range(n_faces):
        line_idx = n_verts + j
        if line_idx >= len(lines):
            break
        parts = lines[line_idx].split()
        try:
            count = int(parts[0])
            face = [int(parts[1 + k]) for k in range(count)]
            faces.append(face)
        except (IndexError, ValueError):
            pass

    return {"vertices": vertices, "faces": faces}


def _parse_binary_le_body(
    body: bytes,
    n_verts: int,
    n_faces: int,
) -> Dict[str, Any]:
    """Parse binary little-endian PLY data body."""
    vertices: List[List[float]] = []
    faces: List[List[int]] = []
    offset = 0

    # Each vertex: 3 × float32 = 12 bytes
    vert_size = struct.calcsize("<fff")
    for _ in range(n_verts):
        if offset + vert_size > len(body):
            break
        x, y, z = struct.unpack_from("<fff", body, offset)
        vertices.append([x, y, z])
        offset += vert_size

    # Each face: uchar count + count × int32
    uchar_size = struct.calcsize("<B")
    int32_size = struct.calcsize("<i")
    for _ in range(n_faces):
        if offset + uchar_size > len(body):
            break
        (count,) = struct.unpack_from("<B", body, offset)
        offset += uchar_size
        face_bytes = count * int32_size
        if offset + face_bytes > len(body):
            break
        face = list(struct.unpack_from(f"<{count}i", body, offset))
        faces.append(face)
        offset += face_bytes

    return {"vertices": vertices, "faces": faces}


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

    _subd_export_limit_to_ply_spec = ToolSpec(
        name="subd_export_limit_to_ply",
        description=(
            "Export a SubD control cage as a Catmull-Clark limit-surface mesh in "
            "Stanford PLY format (.ply).\n"
            "\n"
            "Applies N levels of Catmull-Clark subdivision and emits the result as a "
            "valid PLY file (ASCII or binary little-endian). PLY is standard in academic "
            "geometry workflows, point-cloud tools (CloudCompare, MeshLab, PCL), and "
            "scan/reconstruction pipelines.\n"
            "\n"
            "HONEST LIMITATIONS (v1):\n"
            "  - Geometry only: no per-vertex colour, normals, texture coordinates, "
            "    or material references.\n"
            "  - Only ASCII and binary_little_endian formats; no big-endian.\n"
            "  - Crease sharpness is used during subdivision but NOT stored in PLY.\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  ply_bytes_b64       : str   — base64-encoded PLY content\n"
            "  ply_text            : str   — PLY content as text (ascii format only)\n"
            "  n_vertices          : int   — vertex count after subdivision\n"
            "  n_faces             : int   — face count after subdivision\n"
            "  levels_used         : int   — actual subdivision levels applied\n"
            "  format_used         : str   — 'ascii' or 'binary_little_endian'\n"
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
                    "description": (
                        "PLY format: 'ascii' (default) or 'binary_little_endian'."
                    ),
                    "enum": ["ascii", "binary_little_endian"],
                    "default": "ascii",
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_export_limit_to_ply_spec)
    async def run_subd_export_limit_to_ply(ctx: "ProjectCtx", args: bytes) -> str:
        import base64 as _b64

        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        levels = int(a.get("levels", 2))
        ply_format = str(a.get("format", "ascii")).lower().strip()

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if ply_format not in ("ascii", "binary_little_endian"):
            return err_payload(
                "format must be 'ascii' or 'binary_little_endian'", "BAD_ARGS"
            )

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
            ply_bytes = export_limit_to_ply(mesh, levels=levels, format=ply_format)
        except Exception as exc:
            return err_payload(f"export failed: {exc}", "EXPORT_ERROR")

        parsed = parse_ply(ply_bytes)

        payload: dict = {
            "ok": True,
            "ply_bytes_b64": _b64.b64encode(ply_bytes).decode("ascii"),
            "n_vertices": len(parsed["vertices"]),
            "n_faces": len(parsed["faces"]),
            "levels_used": max(0, min(int(levels), 8)),
            "format_used": ply_format,
        }
        if ply_format == "ascii":
            payload["ply_text"] = ply_bytes.decode("ascii", errors="replace")

        return ok_payload(payload)
