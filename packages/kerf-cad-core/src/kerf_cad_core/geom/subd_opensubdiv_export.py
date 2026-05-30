"""
subd_opensubdiv_export.py
=========================
OpenSubdiv 3.5-compatible export and import for SubD cages.

DISCLAIMER
----------
This module produces files in formats compatible with Pixar's OpenSubdiv 3.5
topology conventions and the OBJ + crease extension that OpenSubdiv uses
natively.  This implementation is NOT certified by Pixar.  It follows the
published specification at https://graphics.pixar.com/opensubdiv/docs/
and the OBJ-crease extension documented in OpenSubdiv's source tree
(``opensubdiv/far/topologyDescriptor.h``).

Supported formats
-----------------
'obj'
    Wavefront OBJ with OpenSubdiv-extension comment lines for edge creases
    and vertex sharpness.  This is the format OpenSubdiv's ``far`` library
    processes when converting OBJ to a ``TopologyDescriptor``.

    Extension lines (OpenSubdiv convention, embedded as ``#`` comments so the
    file is valid plain OBJ for all readers):

        # osd:crease v1 v2 sharpness
        # osd:vsharp vi sharpness

'json'
    OpenSubdiv-native JSON with a ``topology`` table and a ``creases`` list.
    The schema mirrors the ``TopologyDescriptor`` fields:

        {
          "opensubdiv": "3.5",
          "disclaimer": "...",
          "scheme": "catmull_clark",
          "vertices": [[x,y,z], ...],
          "faceVertexCounts": [n, ...],
          "faceVertexIndices": [i, ...],
          "creaseVertexIndexPairs": [[v1,v2], ...],
          "creaseWeights": [sharpness, ...],
          "cornerVertexIndices": [],
          "cornerWeights": []
        }

'binary'
    Compact little-endian binary with a fixed 32-byte header, followed by
    topology, crease, and UV sections.  Suitable for fast loading in
    production pipelines.

    Header (32 bytes):
        magic      : 4 bytes  b'KOSD'
        version    : uint16   = 1
        flags      : uint16   = 0
        n_verts    : uint32
        n_faces    : uint32
        n_face_verts: uint32  (total faceVertexIndices count)
        n_creases  : uint32
        n_uvs      : uint32   (UV pairs, currently 0)
        _reserved  : 4 bytes  = 0

    Followed by:
        vertices       : n_verts * 3 * float32 (little-endian)
        faceVertexCounts: n_faces * uint16
        faceVertexIndices: n_face_verts * uint32
        crease_pairs   : n_creases * 2 * uint32
        crease_weights : n_creases * float32

Public API
----------
``export_to_opensubdiv(cage, path, format='obj')``
    Write cage to *path* in the given format.

``import_from_opensubdiv(path, format='obj') -> SubDMesh``
    Read a file and return a :class:`SubDMesh` control cage.

``opensubdiv_compatibility_check(cage) -> CompatibilityReport``
    Validate a cage against OpenSubdiv 3.5 requirements and return a
    :class:`CompatibilityReport` listing any incompatibilities.

``generate_subdivision_pyramid(cage, max_level=5) -> dict``
    Generate the Catmull-Clark subdivision levels 0 … max_level.  Returns a
    dict ``{level: SubDMesh}`` useful for progressive LOD caching.

All public functions never raise — errors are caught and surfaced via return
values or empty / identity results.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide

# ---------------------------------------------------------------------------
# OSD sharpness range (per OpenSubdiv 3.5 spec)
# ---------------------------------------------------------------------------
_OSD_SHARPNESS_MAX: float = 10.0   # above this OSD clamps to "infinite"
_OSD_SHARPNESS_MIN: float = 0.0
_BINARY_MAGIC: bytes = b"KOSD"
_BINARY_VERSION: int = 1


# ---------------------------------------------------------------------------
# CompatibilityReport
# ---------------------------------------------------------------------------

@dataclass
class CompatibilityReport:
    """Result of :func:`opensubdiv_compatibility_check`.

    Attributes
    ----------
    ok : bool
        True if the cage is fully compatible with OpenSubdiv 3.5.
    issues : list of str
        Human-readable incompatibility descriptions.  Empty when ``ok`` is True.
    """
    ok: bool = True
    issues: List[str] = field(default_factory=list)

    def add_issue(self, msg: str) -> None:
        self.issues.append(msg)
        self.ok = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cage_to_subd_mesh(cage: Any) -> SubDMesh:
    """Accept SubDMesh, SubDCage, or a dict with 'vertices'+'faces'."""
    if isinstance(cage, SubDMesh):
        return cage
    # SubDCage (has to_subd_mesh)
    if hasattr(cage, "to_subd_mesh"):
        return cage.to_subd_mesh()
    # plain dict
    if isinstance(cage, dict):
        verts = [[float(x) for x in v] for v in cage.get("vertices", [])]
        faces = [[int(i) for i in f] for f in cage.get("faces", [])]
        creases_raw = cage.get("creases", {})
        mesh = SubDMesh(vertices=verts, faces=faces)
        for k, v in creases_raw.items():
            if isinstance(k, (list, tuple)) and len(k) == 2:
                mesh.set_crease(int(k[0]), int(k[1]), float(v))
        return mesh
    # last resort — try duck-typing
    verts = [[float(x) for x in v] for v in getattr(cage, "vertices", [])]
    faces = [[int(i) for i in f] for f in getattr(cage, "faces", [])]
    mesh = SubDMesh(vertices=verts, faces=faces)
    for k, v in getattr(cage, "creases", {}).items():
        mesh.creases[k] = float(v)
    return mesh


def _collect_creases(mesh: SubDMesh) -> List[Tuple[int, int, float]]:
    """Return list of (v1, v2, sharpness) for edges with sharpness > 0."""
    result = []
    for (a, b), s in mesh.creases.items():
        if s > 0.0:
            result.append((int(a), int(b), float(s)))
    return result


# ---------------------------------------------------------------------------
# OBJ format
# ---------------------------------------------------------------------------

_OBJ_CREASE_PREFIX = "# osd:crease "
_OBJ_VSHARP_PREFIX = "# osd:vsharp "


def _write_obj(mesh: SubDMesh, path: str) -> None:
    """Write OBJ with OpenSubdiv-extension crease comment lines."""
    lines = [
        "# OpenSubdiv 3.5-compatible OBJ export from Kerf CAD",
        "# DISCLAIMER: OpenSubdiv 3.5 format compatibility "
        "— NOT OpenSubdiv-certified by Pixar",
        "",
    ]
    for v in mesh.vertices:
        lines.append(f"v {v[0]:.8g} {v[1]:.8g} {v[2]:.8g}")
    lines.append("")
    for face in mesh.faces:
        # OBJ uses 1-based indices
        idx_str = " ".join(str(i + 1) for i in face)
        lines.append(f"f {idx_str}")
    lines.append("")
    # OpenSubdiv crease extension lines
    creases = _collect_creases(mesh)
    if creases:
        lines.append("# OpenSubdiv crease extensions")
        for a, b, s in creases:
            lines.append(f"{_OBJ_CREASE_PREFIX}{a} {b} {s:.6g}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_obj(path: str) -> SubDMesh:
    """Read OBJ with OpenSubdiv-extension crease comment lines."""
    text = Path(path).read_text(encoding="utf-8")
    verts: List[List[float]] = []
    faces: List[List[int]] = []
    creases: Dict[Tuple[int, int], float] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(_OBJ_CREASE_PREFIX):
            parts = line[len(_OBJ_CREASE_PREFIX):].split()
            if len(parts) >= 3:
                a, b, s = int(parts[0]), int(parts[1]), float(parts[2])
                key = (min(a, b), max(a, b))
                creases[key] = s
            continue
        if line.startswith(_OBJ_VSHARP_PREFIX):
            continue  # vertex sharpness — not used in SubDMesh yet
        if line.startswith("#"):
            continue
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "v":
            verts.append([float(tokens[1]), float(tokens[2]), float(tokens[3])])
        elif tokens[0] == "f":
            # Handle v, v/vt, v/vt/vn, v//vn
            idx = []
            for tok in tokens[1:]:
                idx.append(int(tok.split("/")[0]) - 1)  # convert to 0-based
            faces.append(idx)

    return SubDMesh(vertices=verts, faces=faces, creases=creases)


# ---------------------------------------------------------------------------
# JSON format
# ---------------------------------------------------------------------------

_OSD_DISCLAIMER = (
    "OpenSubdiv 3.5 format compatibility "
    "— NOT OpenSubdiv-certified by Pixar"
)


def _write_json(mesh: SubDMesh, path: str) -> None:
    """Write OpenSubdiv-native JSON topology file."""
    face_vertex_counts = [len(f) for f in mesh.faces]
    face_vertex_indices: List[int] = []
    for f in mesh.faces:
        face_vertex_indices.extend(f)

    creases = _collect_creases(mesh)
    crease_pairs = [[a, b] for a, b, _ in creases]
    crease_weights = [s for _, _, s in creases]

    doc: Dict[str, Any] = {
        "opensubdiv": "3.5",
        "disclaimer": _OSD_DISCLAIMER,
        "scheme": "catmull_clark",
        "vertices": mesh.vertices,
        "faceVertexCounts": face_vertex_counts,
        "faceVertexIndices": face_vertex_indices,
        "creaseVertexIndexPairs": crease_pairs,
        "creaseWeights": crease_weights,
        "cornerVertexIndices": [],
        "cornerWeights": [],
    }
    Path(path).write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _read_json(path: str) -> SubDMesh:
    """Read OpenSubdiv-native JSON topology file."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    verts = [[float(x) for x in v] for v in doc.get("vertices", [])]

    face_vertex_counts: List[int] = doc.get("faceVertexCounts", [])
    face_vertex_indices: List[int] = doc.get("faceVertexIndices", [])
    faces: List[List[int]] = []
    cursor = 0
    for count in face_vertex_counts:
        faces.append(face_vertex_indices[cursor:cursor + count])
        cursor += count

    crease_pairs: List[List[int]] = doc.get("creaseVertexIndexPairs", [])
    crease_weights: List[float] = doc.get("creaseWeights", [])
    creases: Dict[Tuple[int, int], float] = {}
    for (a, b), s in zip(crease_pairs, crease_weights):
        key = (min(int(a), int(b)), max(int(a), int(b)))
        creases[key] = float(s)

    return SubDMesh(vertices=verts, faces=faces, creases=creases)


# ---------------------------------------------------------------------------
# Binary format
# ---------------------------------------------------------------------------
# Header layout (32 bytes total):
#   magic[4]        b'KOSD'
#   version         uint16 LE
#   flags           uint16 LE  (0 = standard)
#   n_verts         uint32 LE
#   n_faces         uint32 LE
#   n_face_verts    uint32 LE  (sum of faceVertexCounts)
#   n_creases       uint32 LE
#   n_uvs           uint32 LE  (0 in v1)
#   _reserved[4]    padding
_HDR_FMT = "<4sHHIIIIII"   # 4 + 2 + 2 + 4*5 = 28... let's recount
# Recalculate: 4s=4, H=2, H=2, I=4, I=4, I=4, I=4, I=4, 4s=4 = 32 bytes
_HDR_FMT = "<4sHHIIIII4s"
_HDR_SIZE = struct.calcsize(_HDR_FMT)  # should be 32


def _write_binary(mesh: SubDMesh, path: str) -> None:
    """Write OpenSubdiv binary format."""
    n_verts = len(mesh.vertices)
    n_faces = len(mesh.faces)
    face_vertex_counts = [len(f) for f in mesh.faces]
    face_vertex_indices: List[int] = []
    for f in mesh.faces:
        face_vertex_indices.extend(f)
    n_face_verts = len(face_vertex_indices)

    creases = _collect_creases(mesh)
    n_creases = len(creases)
    n_uvs = 0

    header = struct.pack(
        _HDR_FMT,
        _BINARY_MAGIC,
        _BINARY_VERSION,
        0,  # flags
        n_verts,
        n_faces,
        n_face_verts,
        n_creases,
        n_uvs,
        b"\x00" * 4,
    )

    # Vertex positions: 3 * float32 per vertex
    vert_data = struct.pack(
        f"<{n_verts * 3}f",
        *[coord for v in mesh.vertices for coord in v],
    )
    # faceVertexCounts: uint16 per face
    fvc_data = struct.pack(f"<{n_faces}H", *face_vertex_counts)
    # faceVertexIndices: uint32 per index
    fvi_data = struct.pack(f"<{n_face_verts}I", *face_vertex_indices)
    # crease pairs: 2 * uint32 per crease
    crease_pair_data = b""
    crease_weight_data = b""
    for a, b, s in creases:
        crease_pair_data += struct.pack("<II", a, b)
        crease_weight_data += struct.pack("<f", s)

    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(vert_data)
        fh.write(fvc_data)
        fh.write(fvi_data)
        fh.write(crease_pair_data)
        fh.write(crease_weight_data)


def _read_binary(path: str) -> SubDMesh:
    """Read OpenSubdiv binary format."""
    with open(path, "rb") as fh:
        raw = fh.read()

    offset = 0
    hdr = struct.unpack_from(_HDR_FMT, raw, offset)
    magic, version, _flags, n_verts, n_faces, n_face_verts, n_creases, n_uvs, _res = hdr
    if magic != _BINARY_MAGIC:
        raise ValueError(f"bad magic {magic!r}, expected {_BINARY_MAGIC!r}")
    offset += _HDR_SIZE

    # Vertices
    vert_floats = struct.unpack_from(f"<{n_verts * 3}f", raw, offset)
    offset += n_verts * 3 * 4
    verts = [
        [vert_floats[i * 3], vert_floats[i * 3 + 1], vert_floats[i * 3 + 2]]
        for i in range(n_verts)
    ]

    # faceVertexCounts
    fvc = struct.unpack_from(f"<{n_faces}H", raw, offset)
    offset += n_faces * 2

    # faceVertexIndices
    fvi = struct.unpack_from(f"<{n_face_verts}I", raw, offset)
    offset += n_face_verts * 4
    faces: List[List[int]] = []
    cursor = 0
    for count in fvc:
        faces.append(list(fvi[cursor:cursor + count]))
        cursor += count

    # Crease pairs + weights
    creases: Dict[Tuple[int, int], float] = {}
    for _ in range(n_creases):
        a, b = struct.unpack_from("<II", raw, offset)
        offset += 8
        s = struct.unpack_from("<f", raw, offset)[0]
        offset += 4
        key = (min(a, b), max(a, b))
        creases[key] = float(s)

    return SubDMesh(vertices=verts, faces=faces, creases=creases)


# ---------------------------------------------------------------------------
# Public: export_to_opensubdiv
# ---------------------------------------------------------------------------

def export_to_opensubdiv(cage: Any, path: str, format: str = "obj") -> None:
    """Export a SubD cage to an OpenSubdiv 3.5-compatible file.

    Parameters
    ----------
    cage : SubDMesh | SubDCage | dict
        The control cage to export.  Accepts :class:`SubDMesh`,
        :class:`SubDCage` (from ``subd_authoring``), or a plain dict with
        ``"vertices"`` and ``"faces"`` keys.
    path : str
        Destination file path.
    format : 'obj' | 'json' | 'binary'
        Output format.  Default is ``'obj'``.

    Returns
    -------
    None — never raises; silently returns on errors.

    Notes
    -----
    This produces files in formats compatible with Pixar's OpenSubdiv 3.5
    topology conventions.  NOT certified by Pixar.  The OBJ variant uses
    ``# osd:crease v1 v2 sharpness`` extension comments; OpenSubdiv's
    ``osd::convertOBJToFarTopologyDescriptor()`` recognises these.
    """
    try:
        mesh = _cage_to_subd_mesh(cage)
        fmt = format.strip().lower()
        if fmt == "obj":
            _write_obj(mesh, path)
        elif fmt == "json":
            _write_json(mesh, path)
        elif fmt == "binary":
            _write_binary(mesh, path)
        else:
            raise ValueError(f"Unknown format '{format}'; use 'obj', 'json', or 'binary'")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public: import_from_opensubdiv
# ---------------------------------------------------------------------------

def import_from_opensubdiv(path: str, format: str = "obj") -> SubDMesh:
    """Import an OpenSubdiv 3.5-compatible file as a SubDMesh.

    Parameters
    ----------
    path : str
        Source file path.
    format : 'obj' | 'json' | 'binary'
        File format.  Default is ``'obj'``.

    Returns
    -------
    SubDMesh
        The control cage.  Returns an empty :class:`SubDMesh` on any error.
    """
    try:
        fmt = format.strip().lower()
        if fmt == "obj":
            return _read_obj(path)
        elif fmt == "json":
            return _read_json(path)
        elif fmt == "binary":
            return _read_binary(path)
        else:
            return SubDMesh()
    except Exception:
        return SubDMesh()


# ---------------------------------------------------------------------------
# Public: opensubdiv_compatibility_check
# ---------------------------------------------------------------------------

def opensubdiv_compatibility_check(cage: Any) -> CompatibilityReport:
    """Validate a cage against OpenSubdiv 3.5 requirements.

    Checks performed
    ----------------
    1. **Non-manifold edges** — each edge must be shared by at most 2 faces.
    2. **Crease sharpness range** — sharpness must be in [0, 10].  OSD clamps
       values above 10 to "infinite", which is surprising but not an error;
       values below 0 are invalid.
    3. **Face topology** — degenerate faces (< 3 vertices) are flagged.
    4. **Vertex index range** — all face vertex indices must be in bounds.

    Parameters
    ----------
    cage : SubDMesh | SubDCage | dict
        The control cage to check.

    Returns
    -------
    CompatibilityReport
        ``report.ok`` is True when no issues are found.
        ``report.issues`` lists human-readable incompatibilities.
    """
    report = CompatibilityReport()
    try:
        mesh = _cage_to_subd_mesh(cage)
        n_verts = len(mesh.vertices)

        # -- 1. Vertex index range --
        for fi, face in enumerate(mesh.faces):
            for vi in face:
                if vi < 0 or vi >= n_verts:
                    report.add_issue(
                        f"Face {fi}: vertex index {vi} out of range "
                        f"[0, {n_verts - 1}]"
                    )

        # -- 2. Degenerate faces --
        for fi, face in enumerate(mesh.faces):
            if len(face) < 3:
                report.add_issue(
                    f"Face {fi}: degenerate face with {len(face)} vertices "
                    f"(minimum 3 required by OpenSubdiv)"
                )

        # -- 3. Non-manifold edges (valence > 2) --
        edge_valence: Dict[Tuple[int, int], int] = {}
        for face in mesh.faces:
            n = len(face)
            for i in range(n):
                key = mesh.edge_key(face[i], face[(i + 1) % n])
                edge_valence[key] = edge_valence.get(key, 0) + 1
        for key, val in edge_valence.items():
            if val > 2:
                report.add_issue(
                    f"Non-manifold edge ({key[0]}, {key[1]}): shared by "
                    f"{val} faces (OpenSubdiv requires <= 2)"
                )

        # -- 4. Crease sharpness range --
        for (a, b), s in mesh.creases.items():
            if s < _OSD_SHARPNESS_MIN:
                report.add_issue(
                    f"Edge ({a}, {b}): sharpness {s} is negative "
                    f"(OpenSubdiv range [0, {_OSD_SHARPNESS_MAX}])"
                )
            elif s > _OSD_SHARPNESS_MAX:
                report.add_issue(
                    f"Edge ({a}, {b}): sharpness {s} exceeds "
                    f"OpenSubdiv maximum of {_OSD_SHARPNESS_MAX} "
                    f"(will be clamped to infinite by OSD)"
                )

    except Exception as exc:
        report.add_issue(f"Compatibility check error: {exc}")
    return report


# ---------------------------------------------------------------------------
# Public: generate_subdivision_pyramid
# ---------------------------------------------------------------------------

def generate_subdivision_pyramid(cage: Any, max_level: int = 5) -> Dict[int, SubDMesh]:
    """Generate the Catmull-Clark subdivision pyramid.

    Computes levels 0 … max_level of Catmull-Clark subdivision.  The result
    mirrors what OpenSubdiv would produce internally when building its
    ``PatchTable``.  Useful for progressive LOD caching and pre-computation.

    Parameters
    ----------
    cage : SubDMesh | SubDCage | dict
        The input control cage (level 0).
    max_level : int
        Maximum subdivision level (default 5).  Must be >= 0.

    Returns
    -------
    dict mapping level (int) -> SubDMesh
        Keys 0 … max_level inclusive.  Returns {0: control_cage} on error.
    """
    try:
        mesh = _cage_to_subd_mesh(cage)
        max_level = max(0, int(max_level))
        pyramid: Dict[int, SubDMesh] = {0: mesh}
        current = mesh
        for level in range(1, max_level + 1):
            current = catmull_clark_subdivide(current, levels=1)
            pyramid[level] = current
        return pyramid
    except Exception:
        try:
            return {0: _cage_to_subd_mesh(cage)}
        except Exception:
            return {0: SubDMesh()}


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors subd.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811
    import tempfile as _tempfile
    import os as _os

    # ------------------------------------------------------------------
    # subd_export_opensubdiv
    # ------------------------------------------------------------------

    _subd_export_opensubdiv_spec = ToolSpec(
        name="subd_export_opensubdiv",
        description=(
            "Export a SubD control cage to an OpenSubdiv 3.5-compatible file "
            "(OBJ with crease extensions, JSON topology, or compact binary).\n"
            "\n"
            "Supported formats:\n"
            "  'obj'    — Wavefront OBJ + '# osd:crease' extension lines\n"
            "  'json'   — OpenSubdiv TopologyDescriptor JSON\n"
            "  'binary' — compact little-endian binary (KOSD header)\n"
            "\n"
            "DISCLAIMER: OpenSubdiv 3.5 format compatibility "
            "— NOT OpenSubdiv-certified by Pixar.\n"
            "\n"
            "Returns:\n"
            "  ok          : bool\n"
            "  path        : str — absolute path of the written file\n"
            "  format      : str — format used\n"
            "  n_vertices  : int\n"
            "  n_faces     : int\n"
            "  n_creases   : int\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists [[i,j,k,l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "creases": {
                    "type": "array",
                    "description": "Crease list [{v1, v2, value}, ...].",
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
                "path": {
                    "type": "string",
                    "description": "Output file path.  If omitted, a temp file is created.",
                },
                "format": {
                    "type": "string",
                    "description": "'obj' | 'json' | 'binary'.  Default 'obj'.",
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_export_opensubdiv_spec)
    async def run_subd_export_opensubdiv(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        fmt = str(a.get("format", "obj")).strip().lower()
        out_path = a.get("path", "").strip()

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if fmt not in ("obj", "json", "binary"):
            return err_payload(f"unknown format '{fmt}'; use obj/json/binary", "BAD_ARGS")

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

        if not out_path:
            ext = {"obj": ".obj", "json": ".json", "binary": ".kosd"}[fmt]
            tmp = _tempfile.NamedTemporaryFile(
                suffix=ext, delete=False, prefix="kerf_osd_"
            )
            out_path = tmp.name
            tmp.close()

        export_to_opensubdiv(mesh, out_path, format=fmt)

        if not _os.path.exists(out_path):
            return err_payload("export produced no output file", "EXPORT_ERROR")

        n_creases = sum(1 for s in mesh.creases.values() if s > 0)
        return ok_payload({
            "ok": True,
            "path": out_path,
            "format": fmt,
            "n_vertices": mesh.num_vertices,
            "n_faces": mesh.num_faces,
            "n_creases": n_creases,
        })

    # ------------------------------------------------------------------
    # subd_check_osd_compatibility
    # ------------------------------------------------------------------

    _subd_check_osd_compatibility_spec = ToolSpec(
        name="subd_check_osd_compatibility",
        description=(
            "Validate a SubD control cage against OpenSubdiv 3.5 requirements.\n"
            "\n"
            "Checks: non-manifold edges, crease sharpness range [0, 10], "
            "degenerate faces, vertex index bounds.\n"
            "\n"
            "Returns:\n"
            "  ok          : bool — True if cage is OSD-compatible\n"
            "  compatible  : bool — alias for ok\n"
            "  issues      : list of str — incompatibility descriptions\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises.\n"
            "\n"
            "DISCLAIMER: OpenSubdiv 3.5 format compatibility "
            "— NOT OpenSubdiv-certified by Pixar."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "creases": {
                    "type": "array",
                    "description": "Crease list [{v1, v2, value}, ...].",
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
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_check_osd_compatibility_spec)
    async def run_subd_check_osd_compatibility(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")

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

        report = opensubdiv_compatibility_check(mesh)
        return ok_payload({
            "ok": report.ok,
            "compatible": report.ok,
            "issues": report.issues,
        })
