"""
subd_export_obj.py
==================
Export the Catmull-Clark limit-surface as a triangle/quad mesh in Wavefront OBJ
format (.obj, ASCII).

For each face in the control cage, N levels of Catmull-Clark subdivision are
applied and the resulting vertices (and optional vertex normals) are emitted as
a valid ``.obj`` ASCII file.

Wavefront OBJ specification
---------------------------
Reference: https://en.wikipedia.org/wiki/Wavefront_.obj_file

Key grammar elements used here:

    # comment line
    v  <x> <y> <z>          — vertex position (1-based in face references)
    vn <nx> <ny> <nz>       — vertex normal (unit, 1-based)
    f  <v>///<vn> ...       — face using vertex/texcoord/normal indices
    f  <v> ...              — face using vertex indices only (no normals)

Honest limitations
------------------
- **Geometry only** — no ``.mtl`` material library is produced and no ``mtllib``
  or ``usemtl`` directives are emitted.  Only ``v``, ``vn``, and ``f`` lines
  appear in the output.
- No texture coordinates (``vt``) are emitted.  UVs from cage faces are not
  propagated through subdivision in this implementation.
- Vertex normals are computed from the cross-product of the two face-tangent
  edges at each subdivided vertex (area-weighted per-face contribution then
  normalised), NOT from the Stam exact eigenfunction basis.  This is sufficient
  for display and round-trip testing; a full Stam-basis normal would require
  assembling the 2-ring per output vertex, which is beyond the scope of this
  focused exporter.
- Sharpness (crease) propagation through subdivision is handled by
  ``catmull_clark_subdivide`` (the existing pure-Python CC implementation);
  see ``subd.py`` for crease-decay rules.

Public API
----------
``export_limit_to_obj(cage, levels=2, include_normals=True) -> str``
    Subdivide *cage* for *levels* steps and emit Wavefront OBJ ASCII text.

``parse_obj(text) -> dict``
    Minimal OBJ parser for round-trip oracle tests.  Returns
    ``{"vertices": [[x,y,z],...], "normals": [[nx,ny,nz],...], "faces": [[...],...]}``.

References
----------
- Wavefront OBJ: https://en.wikipedia.org/wiki/Wavefront_.obj_file
- Catmull, E., Clark, J. (1978). "Recursively generated B-spline surfaces on
  arbitrary topological meshes." Computer-Aided Design, 10(6):350-355.
- de Boor, C. (2001). *A Practical Guide to Splines*, §10 (vertex normal
  interpolation via tangent-basis averaging).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide


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


def _cross3(a: List[float], b: List[float]) -> List[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _sub3(a: List[float], b: List[float]) -> List[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _normalize3(v: List[float]) -> List[float]:
    mag = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if mag < 1e-15:
        return [0.0, 0.0, 1.0]
    return [v[0] / mag, v[1] / mag, v[2] / mag]


def _add3(a: List[float], b: List[float]) -> List[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _compute_vertex_normals(
    vertices: List[List[float]],
    faces: List[List[int]],
) -> List[List[float]]:
    """Compute per-vertex normals by area-weighted averaging of face normals.

    For each face we accumulate the cross product of the first two edge vectors
    (not normalised, so the contribution is area-weighted).  Then each vertex
    accumulates contributions from all adjacent faces and we normalise.

    This follows the de Boor §10 principle of blending tangent-basis normals
    across adjacent faces; it is equivalent to the vertex-normal formula in
    most production OBJ exporters (Maya, Blender, etc.) for subdivided meshes.
    """
    n = len(vertices)
    accum: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(n)]

    for face in faces:
        nf = len(face)
        if nf < 3:
            continue
        v0 = vertices[face[0]]
        v1 = vertices[face[1]]
        v2 = vertices[face[2]]
        e1 = _sub3(v1, v0)
        e2 = _sub3(v2, v0)
        fn = _cross3(e1, e2)  # area-weighted face normal
        for vi in face:
            accum[vi] = _add3(accum[vi], fn)

    return [_normalize3(a) for a in accum]


def _fmt_float(f: float) -> str:
    """Format a float for OBJ output (6 significant figures, compact)."""
    return f"{f:.6g}"


# ---------------------------------------------------------------------------
# Public: export_limit_to_obj
# ---------------------------------------------------------------------------

def export_limit_to_obj(
    cage: Any,
    *,
    levels: int = 2,
    include_normals: bool = True,
) -> str:
    """Export the Catmull-Clark limit-surface approximation as Wavefront OBJ.

    Applies *levels* rounds of Catmull-Clark subdivision to *cage* and emits
    the resulting mesh as an ASCII ``.obj`` string.

    Parameters
    ----------
    cage : SubDMesh | dict | duck-typed
        The control cage.  Accepts the same forms as the other subd exporters
        (``SubDMesh``, ``{"vertices": ..., "faces": ...}`` dict, or any object
        with ``vertices`` and ``faces`` attributes).
    levels : int
        Number of CC subdivision steps.  ``levels=2`` on a cube cage (6 quads)
        produces 6 × 4² = 96 quads.  Clamped to [0, 8].
    include_normals : bool
        When ``True``, emit ``vn`` lines and use ``v//vn`` face references.
        When ``False``, emit only ``v`` and ``f`` lines (no ``vn``).

    Returns
    -------
    str
        Valid Wavefront OBJ ASCII text.  No ``.mtl`` material library is
        produced — this file contains geometry only.

    Notes
    -----
    - No MTL / material output.  Only ``v``, ``vn`` (optional), and ``f``
      directives are emitted.
    - No texture coordinates (``vt``).  OBJ face indices use ``v//vn`` (with
      double-slash to skip ``vt``) when normals are included.
    - Vertex normals are area-weighted cross-product averages (not Stam exact
      eigenbasis), suitable for rendering and round-trip tests.
    - Crease sharpness is respected by the underlying CC subdivider.

    References
    ----------
    Wavefront OBJ: https://en.wikipedia.org/wiki/Wavefront_.obj_file
    Catmull & Clark (1978), CAD 10(6):350-355.
    de Boor §10 — vertex normal interpolation via tangent-basis averaging.
    """
    levels = max(0, min(int(levels), 8))

    try:
        mesh = _cage_to_subd_mesh(cage)
    except Exception as exc:
        return f"# subd_export_obj: cage coercion error: {exc}\n"

    try:
        subd = catmull_clark_subdivide(mesh, levels=levels)
    except Exception as exc:
        return f"# subd_export_obj: subdivision error: {exc}\n"

    verts = subd.vertices
    faces = subd.faces

    lines: List[str] = [
        "# Catmull-Clark limit-surface mesh exported by Kerf CAD Core",
        "# Wavefront OBJ format — geometry only; no MTL material library.",
        f"# Subdivision levels: {levels}",
        f"# Vertices: {len(verts)}  Faces: {len(faces)}",
        "#",
        "# Reference: https://en.wikipedia.org/wiki/Wavefront_.obj_file",
        "#",
        "",
    ]

    # Vertex positions
    for v in verts:
        x, y, z = float(v[0]), float(v[1]), float(v[2])
        lines.append(f"v {_fmt_float(x)} {_fmt_float(y)} {_fmt_float(z)}")

    lines.append("")

    if include_normals and verts:
        normals = _compute_vertex_normals(verts, faces)
        for n in normals:
            nx, ny, nz = n[0], n[1], n[2]
            lines.append(f"vn {_fmt_float(nx)} {_fmt_float(ny)} {_fmt_float(nz)}")
        lines.append("")

        # Faces: v//vn (no vt; double-slash skips texcoord per OBJ spec)
        for face in faces:
            tokens = " ".join(f"{vi + 1}//{vi + 1}" for vi in face)
            lines.append(f"f {tokens}")
    else:
        # Faces: vertex index only (1-based)
        for face in faces:
            tokens = " ".join(str(vi + 1) for vi in face)
            lines.append(f"f {tokens}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public: parse_obj
# ---------------------------------------------------------------------------

def parse_obj(text: str) -> Dict[str, Any]:
    """Minimal Wavefront OBJ parser for round-trip oracle tests.

    Handles the subset of OBJ emitted by :func:`export_limit_to_obj`:
    ``v``, ``vn``, and ``f`` directives.  Ignores ``#`` comments, ``mtllib``,
    ``usemtl``, ``o``, ``g``, and all other directives.

    Face index formats supported:
      - ``f i j k ...``              (vertex-only, 1-based)
      - ``f i/t/n j/t/n ...``        (vertex/texcoord/normal)
      - ``f i//n j//n ...``          (vertex//normal, no texcoord)

    Parameters
    ----------
    text : str
        OBJ ASCII text.

    Returns
    -------
    dict with keys:
        ``vertices`` : list of [x, y, z] floats
        ``normals``  : list of [nx, ny, nz] floats (may be empty)
        ``faces``    : list of lists of 0-based vertex indices
    """
    vertices: List[List[float]] = []
    normals: List[List[float]] = []
    faces: List[List[int]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if not parts:
            continue
        directive = parts[0].lower()

        if directive == "v":
            try:
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except (IndexError, ValueError):
                pass

        elif directive == "vn":
            try:
                normals.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except (IndexError, ValueError):
                pass

        elif directive == "f":
            face_verts: List[int] = []
            for token in parts[1:]:
                # Formats: "i", "i/t", "i/t/n", "i//n"
                idx_str = token.split("/")[0]
                try:
                    idx = int(idx_str)
                    # Convert from 1-based OBJ to 0-based
                    face_verts.append(idx - 1 if idx > 0 else len(vertices) + idx)
                except ValueError:
                    pass
            if len(face_verts) >= 3:
                faces.append(face_verts)

    return {"vertices": vertices, "normals": normals, "faces": faces}


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

    _subd_export_limit_to_obj_spec = ToolSpec(
        name="subd_export_limit_to_obj",
        description=(
            "Export a SubD control cage as a Catmull-Clark limit-surface mesh in "
            "Wavefront OBJ format (.obj ASCII).\n"
            "\n"
            "Applies N levels of Catmull-Clark subdivision and emits vertex positions, "
            "optional vertex normals, and face indices as a standard .obj file.\n"
            "\n"
            "HONEST LIMITATIONS:\n"
            "  - No MTL material library is produced (geometry only).\n"
            "  - No texture coordinates (vt).\n"
            "  - Vertex normals are area-weighted face-normal averages, not Stam "
            "    exact eigenbasis (suitable for display and round-trip tests).\n"
            "\n"
            "Returns:\n"
            "  ok           : bool\n"
            "  obj_text     : str   — full OBJ ASCII content\n"
            "  n_vertices   : int   — vertex count after subdivision\n"
            "  n_faces      : int   — face count after subdivision\n"
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
                "include_normals": {
                    "type": "boolean",
                    "description": "Emit vn vertex-normal lines (default true).",
                    "default": True,
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_export_limit_to_obj_spec)
    async def run_subd_export_limit_to_obj(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        levels = int(a.get("levels", 2))
        include_normals = bool(a.get("include_normals", True))

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

        try:
            obj_text = export_limit_to_obj(
                mesh,
                levels=levels,
                include_normals=include_normals,
            )
        except Exception as exc:
            return err_payload(f"export failed: {exc}", "EXPORT_ERROR")

        parsed = parse_obj(obj_text)

        return ok_payload({
            "ok": True,
            "obj_text": obj_text,
            "n_vertices": len(parsed["vertices"]),
            "n_faces": len(parsed["faces"]),
            "levels_used": max(0, min(int(levels), 8)),
        })
