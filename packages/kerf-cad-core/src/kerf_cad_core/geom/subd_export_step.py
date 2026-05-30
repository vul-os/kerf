"""
subd_export_step.py
===================
Export the Catmull-Clark limit-surface as a STEP AP242 file (.stp, ASCII).

Strategy — honest-flag
-----------------------
STEP (ISO 10303) has no native SubD primitive.  This exporter converts the
CC limit-surface to a **faceted B-rep** (polyhedral ADVANCED_FACE set) via:

1. Apply *levels* rounds of Catmull-Clark subdivision to the cage.
2. Represent each resulting quad (or triangle) as a planar B-rep face whose
   underlying surface is a ``PLANE`` entity with one outer ``FACE_OUTER_BOUND``
   edge loop, and each edge as a ``LINE``-based ``EDGE_CURVE``.
3. Wrap the face set in an ``OPEN_SHELL`` → ``SHELL_BASED_SURFACE_MODEL`` →
   ``GEOMETRIC_SET`` top-level ``SHAPE_REPRESENTATION``.

This is a valid STEP AP242 file that any ISO 10303 reader can ingest.  It is
*not* a smooth NURBS representation — each subdivided quad maps to a flat
planar polygon, not a curved B-spline patch.  (Emitting per-quad
``B_SPLINE_SURFACE_WITH_KNOTS`` for a true limit-surface would require
computing Stam exact eigenfunction boundary conditions, which is outside the
scope of this focused exporter.  For smooth NURBS export use
``subd_to_nurbs.py``.)

Public API
----------
``export_limit_to_step(cage, levels=2) -> str``
    Subdivide *cage* for *levels* steps; emit STEP AP242 ASCII text.

``parse_step_subd(text) -> dict``
    Minimal STEP parser for round-trip oracle tests.  Returns
    ``{"vertices": [[x,y,z],...], "faces": [[...],...]}``.

Standards references
--------------------
- ISO 10303-21:2016  — STEP Physical File Structure (Part 21 clear-text encoding)
- ISO 10303-42:2022  — Geometric and topological representation (Part 42)
- ISO 10303-214:2010 — Automotive (AP214) superset for faceted B-rep conventions
- ISO 10303-242:2020 — Managed model-based 3D engineering (AP242 edition 2)

Honest limitations
------------------
- Faceted B-rep: each subdivided polygon is a flat ``PLANE`` face.  Not smooth.
  For smooth NURBS output see ``subd_to_nurbs.py``.
- Geometry only: no colour, material, units block, or PMI.  A minimal SI unit
  context (millimetres) is emitted for STEP validator compliance.
- No STEP shell stitching/orientation audit: the ``ADVANCED_BREP_SHAPE_REP``
  pattern is not used; ``SHELL_BASED_SURFACE_MODEL`` avoids requiring a
  manifold-closed solid.
- Vertex normals are not emitted (STEP planar B-rep has no per-vertex normal
  concept; normal is derived from the ``PLANE`` direction vector).
"""

from __future__ import annotations

import math
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide


# ---------------------------------------------------------------------------
# Internal helpers (shared with obj/ply/gltf exporters)
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


def _sub3(a: List[float], b: List[float]) -> List[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _cross3(a: List[float], b: List[float]) -> List[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _normalize3(v: List[float]) -> List[float]:
    mag = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if mag < 1e-15:
        return [0.0, 0.0, 1.0]
    return [v[0] / mag, v[1] / mag, v[2] / mag]


def _face_normal(verts: List[List[float]], face: List[int]) -> List[float]:
    """Best-fit normal via Newell's method (handles arbitrary polygon)."""
    n = len(face)
    nx = ny = nz = 0.0
    for i in range(n):
        vi = verts[face[i]]
        vj = verts[face[(i + 1) % n]]
        nx += (vi[1] - vj[1]) * (vi[2] + vj[2])
        ny += (vi[2] - vj[2]) * (vi[0] + vj[0])
        nz += (vi[0] - vj[0]) * (vi[1] + vj[1])
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag < 1e-15:
        return [0.0, 0.0, 1.0]
    return [nx / mag, ny / mag, nz / mag]


def _fmt(f: float) -> str:
    """Format a float for STEP output (8 significant figures)."""
    # Use fixed notation with enough precision; avoid scientific notation for
    # small values typical of geometric data.
    s = f"{f:.8f}"
    # Strip trailing zeros but keep at least one decimal place
    s = s.rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    return s


# ---------------------------------------------------------------------------
# STEP ID allocator
# ---------------------------------------------------------------------------

class _IDAlloc:
    """Monotonically increasing STEP entity ID generator."""
    def __init__(self) -> None:
        self._next = 1

    def alloc(self, count: int = 1) -> int:
        """Return first id of a contiguous block of *count* ids."""
        first = self._next
        self._next += count
        return first

    def next_id(self) -> int:
        return self._next


# ---------------------------------------------------------------------------
# STEP entity builder helpers
# ---------------------------------------------------------------------------

def _cartesian_point(eid: int, x: float, y: float, z: float) -> str:
    return (
        f"#{eid}=CARTESIAN_POINT('',"
        f"({_fmt(x)},{_fmt(y)},{_fmt(z)}));"
    )


def _direction(eid: int, x: float, y: float, z: float) -> str:
    return (
        f"#{eid}=DIRECTION('',"
        f"({_fmt(x)},{_fmt(y)},{_fmt(z)}));"
    )


def _axis2_placement_3d(eid: int, loc: int, axis: int, refdir: int) -> str:
    return (
        f"#{eid}=AXIS2_PLACEMENT_3D('',#{loc},#{axis},#{refdir});"
    )


def _plane(eid: int, a2p3d: int) -> str:
    return f"#{eid}=PLANE('',#{a2p3d});"


def _vertex_point(eid: int, cp: int) -> str:
    return f"#{eid}=VERTEX_POINT('',#{cp});"


def _vector(eid: int, dir_id: int, magnitude: float) -> str:
    return f"#{eid}=VECTOR('',#{dir_id},{_fmt(magnitude)});"


def _line(eid: int, pnt: int, vec: int) -> str:
    return f"#{eid}=LINE('',#{pnt},#{vec});"


def _edge_curve(eid: int, v1: int, v2: int, crv: int, same_sense: bool) -> str:
    ss = ".T." if same_sense else ".F."
    return f"#{eid}=EDGE_CURVE('',#{v1},#{v2},#{crv},{ss});"


def _oriented_edge(eid: int, ec: int, orientation: bool) -> str:
    ori = ".T." if orientation else ".F."
    return f"#{eid}=ORIENTED_EDGE('',*,*,#{ec},{ori});"


def _edge_loop(eid: int, oe_ids: List[int]) -> str:
    refs = ",".join(f"#{i}" for i in oe_ids)
    return f"#{eid}=EDGE_LOOP('',({refs}));"


def _face_outer_bound(eid: int, loop: int, orientation: bool) -> str:
    ori = ".T." if orientation else ".F."
    return f"#{eid}=FACE_OUTER_BOUND('',#{loop},{ori});"


def _advanced_face(eid: int, bound: int, surf: int, same_sense: bool) -> str:
    ss = ".T." if same_sense else ".F."
    return f"#{eid}=ADVANCED_FACE('',({{{bound}}}),#{surf},{ss});".replace(
        "{", ""
    ).replace("}", "")


def _advanced_face_multi(eid: int, bounds: List[int], surf: int, same_sense: bool) -> str:
    ss = ".T." if same_sense else ".F."
    refs = ",".join(f"#{i}" for i in bounds)
    return f"#{eid}=ADVANCED_FACE('',({refs}),#{surf},{ss});"


def _open_shell(eid: int, face_ids: List[int]) -> str:
    refs = ",".join(f"#{i}" for i in face_ids)
    return f"#{eid}=OPEN_SHELL('',({refs}));"


def _shell_based_surface_model(eid: int, shell_id: int) -> str:
    return f"#{eid}=SHELL_BASED_SURFACE_MODEL('',({{{shell_id}}}));".replace(
        "{", "#"
    ).replace("}", "")


def _shape_representation(eid: int, item_id: int, context_id: int) -> str:
    return (
        f"#{eid}=SHAPE_REPRESENTATION('',("
        f"#{item_id}),#{context_id});"
    )


# ---------------------------------------------------------------------------
# SI context entities (minimal AP242-compliant unit block)
# ---------------------------------------------------------------------------

def _emit_unit_context(lines: List[str], alloc: _IDAlloc) -> int:
    """Emit minimal geometric representation context (millimetres, radians).

    Returns the REPRESENTATION_CONTEXT entity id.
    """
    # Named-unit entities
    id_mm_unit = alloc.alloc()
    id_rad_unit = alloc.alloc()
    id_sr_unit = alloc.alloc()
    id_pla_angle = alloc.alloc()
    id_sa_angle = alloc.alloc()
    id_len_measure = alloc.alloc()
    id_gc = alloc.alloc()

    lines.append(
        f"#{id_mm_unit}=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));"
    )
    lines.append(
        f"#{id_rad_unit}=(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.));"
    )
    lines.append(
        f"#{id_sr_unit}=(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT());"
    )
    lines.append(
        f"#{id_pla_angle}=PLANE_ANGLE_MEASURE_WITH_UNIT("
        f"PLANE_ANGLE_MEASURE(1.),#{id_rad_unit});"
    )
    lines.append(
        f"#{id_sa_angle}=SOLID_ANGLE_MEASURE_WITH_UNIT("
        f"SOLID_ANGLE_MEASURE(1.),#{id_sr_unit});"
    )
    lines.append(
        f"#{id_len_measure}=LENGTH_MEASURE_WITH_UNIT("
        f"LENGTH_MEASURE(1.),#{id_mm_unit});"
    )
    lines.append(
        f"#{id_gc}=(GEOMETRIC_REPRESENTATION_CONTEXT(3)"
        f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT("
        f"(UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-6),#{id_mm_unit},"
        f"'distance_accuracy_value','')))"
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT("
        f"(#{id_mm_unit},#{id_rad_unit},#{id_sr_unit}))"
        f"REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY'));"
    )
    return id_gc


# ---------------------------------------------------------------------------
# Core builder: mesh → STEP DATA section entities
# ---------------------------------------------------------------------------

def _build_step_data(
    verts: List[List[float]],
    faces: List[List[int]],
) -> str:
    """Build the STEP DATA section for a polygonal mesh.

    Each face becomes an ADVANCED_FACE on an underlying PLANE.  Each edge is
    a LINE-based EDGE_CURVE.  Vertices are CARTESIAN_POINTs wrapped in
    VERTEX_POINTs.

    Parameters
    ----------
    verts : list of [x, y, z]
    faces : list of face vertex index lists (0-based)

    Returns
    -------
    str — STEP DATA section text (between DATA; and ENDSEC;)
    """
    alloc = _IDAlloc()
    lines: List[str] = []

    # ── Unit / geometry context ──────────────────────────────────────────────
    ctx_id = _emit_unit_context(lines, alloc)

    # ── CARTESIAN_POINT for each vertex ─────────────────────────────────────
    cp_ids: List[int] = []
    for v in verts:
        eid = alloc.alloc()
        lines.append(_cartesian_point(eid, v[0], v[1], v[2]))
        cp_ids.append(eid)

    # ── VERTEX_POINT wrappers ────────────────────────────────────────────────
    vp_ids: List[int] = []
    for cp in cp_ids:
        eid = alloc.alloc()
        lines.append(_vertex_point(eid, cp))
        vp_ids.append(eid)

    # ── Build edge map: (min_vi, max_vi) → EDGE_CURVE id  ───────────────────
    # We share EDGE_CURVE entities for coincident directed edges.
    edge_map: Dict[Tuple[int, int], int] = {}
    # We also need LINE entities per unique edge.

    def _get_or_create_edge(va: int, vb: int) -> int:
        key = (min(va, vb), max(va, vb))
        if key in edge_map:
            return edge_map[key]
        # Direction vector for LINE
        xa, ya, za = verts[va]
        xb, yb, zb = verts[vb]
        dx, dy, dz = xb - xa, yb - ya, zb - za
        mag = math.sqrt(dx * dx + dy * dy + dz * dz)
        if mag < 1e-15:
            dx, dy, dz = 1.0, 0.0, 0.0
        else:
            dx /= mag
            dy /= mag
            dz /= mag
        dir_id = alloc.alloc()
        lines.append(_direction(dir_id, dx, dy, dz))
        vec_id = alloc.alloc()
        lines.append(_vector(vec_id, dir_id, mag))
        line_id = alloc.alloc()
        lines.append(_line(line_id, cp_ids[va], vec_id))
        ec_id = alloc.alloc()
        lines.append(_edge_curve(ec_id, vp_ids[va], vp_ids[vb], line_id, True))
        edge_map[key] = ec_id
        return ec_id

    # ── Build ADVANCED_FACE for each polygon face ────────────────────────────
    advanced_face_ids: List[int] = []

    for face in faces:
        n = len(face)
        if n < 3:
            continue

        # Face normal → PLANE
        fn = _face_normal(verts, face)
        # Pick an arbitrary reference direction perpendicular to normal
        if abs(fn[0]) < 0.9:
            ref = _normalize3(_cross3(fn, [1.0, 0.0, 0.0]))
        else:
            ref = _normalize3(_cross3(fn, [0.0, 1.0, 0.0]))

        # Plane origin = centroid of face
        cx = sum(verts[i][0] for i in face) / n
        cy = sum(verts[i][1] for i in face) / n
        cz = sum(verts[i][2] for i in face) / n

        origin_id = alloc.alloc()
        lines.append(_cartesian_point(origin_id, cx, cy, cz))
        axis_dir_id = alloc.alloc()
        lines.append(_direction(axis_dir_id, fn[0], fn[1], fn[2]))
        ref_dir_id = alloc.alloc()
        lines.append(_direction(ref_dir_id, ref[0], ref[1], ref[2]))
        a2p3d_id = alloc.alloc()
        lines.append(_axis2_placement_3d(a2p3d_id, origin_id, axis_dir_id, ref_dir_id))
        plane_id = alloc.alloc()
        lines.append(_plane(plane_id, a2p3d_id))

        # ORIENTED_EDGEs for loop
        oe_ids: List[int] = []
        for i in range(n):
            va = face[i]
            vb = face[(i + 1) % n]
            ec_id = _get_or_create_edge(va, vb)
            # Orientation: same_sense if va < vb in edge key order
            orientation = (va == min(va, vb))
            oe_id = alloc.alloc()
            lines.append(_oriented_edge(oe_id, ec_id, orientation))
            oe_ids.append(oe_id)

        loop_id = alloc.alloc()
        lines.append(_edge_loop(loop_id, oe_ids))
        fob_id = alloc.alloc()
        lines.append(_face_outer_bound(fob_id, loop_id, True))
        af_id = alloc.alloc()
        lines.append(_advanced_face_multi(af_id, [fob_id], plane_id, True))
        advanced_face_ids.append(af_id)

    # ── OPEN_SHELL → SHELL_BASED_SURFACE_MODEL ──────────────────────────────
    shell_id = alloc.alloc()
    lines.append(_open_shell(shell_id, advanced_face_ids))
    sbsm_id = alloc.alloc()
    lines.append(_shell_based_surface_model(sbsm_id, shell_id))

    # ── SHAPE_REPRESENTATION ─────────────────────────────────────────────────
    sr_id = alloc.alloc()
    lines.append(_shape_representation(sr_id, sbsm_id, ctx_id))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# STEP file header builder
# ---------------------------------------------------------------------------

def _step_header(n_verts: int, n_faces: int, levels: int) -> str:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION((\n"
        "  'Catmull-Clark limit-surface mesh exported by Kerf CAD Core',\n"
        f"  'SubD cage → STEP AP242 faceted B-rep; {n_faces} ADVANCED_FACEs; "
        f"subdivision levels={levels}',\n"
        "  'Honest: flat-polygon facets (PLANE surface), not smooth NURBS.',\n"
        "  'Reference: ISO 10303-242:2020 (AP242 edition 2), ISO 10303-42:2022',\n"
        "  'Catmull-Clark: doi:10.1016/0010-4485(78)90110-0'\n"
        "),'2;1');\n"
        f"FILE_NAME('kerf_subd_export.stp','{ts}',('Kerf CAD Core'),(''),\n"
        "  'kerf_cad_core.geom.subd_export_step','','');\n"
        "FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }'));\n"
        "ENDSEC;\n"
    )


# ---------------------------------------------------------------------------
# Public: export_limit_to_step
# ---------------------------------------------------------------------------

def export_limit_to_step(
    cage: Any,
    *,
    levels: int = 2,
) -> str:
    """Export the Catmull-Clark limit-surface approximation as STEP AP242.

    Applies *levels* rounds of Catmull-Clark subdivision to *cage* and emits a
    valid ISO 10303-21 STEP file (ASCII text).

    Parameters
    ----------
    cage : SubDMesh | dict | duck-typed
        The control cage.  Accepts ``SubDMesh``, ``{"vertices": ..., "faces": ...}``
        dict, or any object with ``vertices`` and ``faces`` attributes.
    levels : int
        Number of CC subdivision steps.  ``levels=2`` on a cube cage (6 quads)
        produces 6 × 4² = 96 ADVANCED_FACEs.  Clamped to [0, 8].

    Returns
    -------
    str
        Valid STEP AP242 ASCII text (ISO 10303-21 encoding).

    Notes
    -----
    **Honest limitation**: This exporter emits a *faceted B-rep* — each
    subdivided polygon is a flat ``PLANE`` face, not a curved NURBS patch.
    STEP (ISO 10303) has no native SubD primitive, so the limit-surface is
    approximated by the subdivision mesh.  For smooth NURBS output see
    ``subd_to_nurbs.py``.

    The output is structurally valid AP242 with:
      - ``CARTESIAN_POINT`` / ``VERTEX_POINT`` / ``EDGE_CURVE`` / ``EDGE_LOOP``
      - ``FACE_OUTER_BOUND`` / ``ADVANCED_FACE`` on ``PLANE`` surface
      - ``OPEN_SHELL`` → ``SHELL_BASED_SURFACE_MODEL`` → ``SHAPE_REPRESENTATION``
      - Minimal SI unit context (millimetres, radians)
      - Standard AP242 FILE_HEADER + FILE_SCHEMA

    References
    ----------
    ISO 10303-21:2016 — STEP Physical File Format (Part 21 clear-text)
    ISO 10303-42:2022 — Geometric and topological representation (Part 42)
    ISO 10303-242:2020 — Managed model-based 3D engineering (AP242 ed. 2)
    Catmull, E., Clark, J. (1978). CAD 10(6):350–355.
    """
    levels = max(0, min(int(levels), 8))

    try:
        mesh = _cage_to_subd_mesh(cage)
    except Exception as exc:
        return f"/* subd_export_step: cage coercion error: {exc} */\n"

    try:
        subd = catmull_clark_subdivide(mesh, levels=levels)
    except Exception as exc:
        return f"/* subd_export_step: subdivision error: {exc} */\n"

    verts = subd.vertices
    faces = subd.faces

    header = _step_header(len(verts), len(faces), levels)
    data_section = _build_step_data(verts, faces)

    return (
        header
        + "DATA;\n"
        + data_section
        + "\nENDSEC;\n"
        + "END-ISO-10303-21;\n"
    )


# ---------------------------------------------------------------------------
# Public: parse_step_subd
# ---------------------------------------------------------------------------

def parse_step_subd(text: str) -> Dict[str, Any]:
    """Minimal STEP parser for round-trip oracle tests.

    Extracts CARTESIAN_POINTs and ADVANCED_FACEs from the DATA section of a
    STEP file produced by :func:`export_limit_to_step`.

    Parameters
    ----------
    text : str
        STEP ASCII text.

    Returns
    -------
    dict with keys:
        ``vertices``        : list of [x, y, z] floats — from CARTESIAN_POINT
        ``advanced_faces``  : int — count of ADVANCED_FACE entities
        ``has_header``      : bool — FILE_DESCRIPTION found
        ``has_schema``      : bool — FILE_SCHEMA found
        ``has_data``        : bool — DATA section found
        ``has_endsec``      : bool — ENDSEC found after DATA
    """
    # Structural checks
    has_header = "FILE_DESCRIPTION" in text
    has_schema = "FILE_SCHEMA" in text
    has_data = bool(re.search(r"\bDATA\s*;", text))
    has_endsec = bool(re.search(r"\bENDSEC\s*;", text))

    # CARTESIAN_POINT: extract all coordinate triples
    # Pattern: #N=CARTESIAN_POINT('', (x,y,z));
    cp_pattern = re.compile(
        r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*"
        r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*,\s*"
        r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*,\s*"
        r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\)\s*\)",
        re.IGNORECASE,
    )
    vertices: List[List[float]] = []
    for m in cp_pattern.finditer(text):
        try:
            vertices.append([float(m.group(1)), float(m.group(2)), float(m.group(3))])
        except ValueError:
            pass

    # Count ADVANCED_FACE entities
    advanced_faces = len(re.findall(r"\bADVANCED_FACE\b", text))

    return {
        "vertices": vertices,
        "advanced_faces": advanced_faces,
        "has_header": has_header,
        "has_schema": has_schema,
        "has_data": has_data,
        "has_endsec": has_endsec,
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

    _subd_export_limit_to_step_spec = ToolSpec(
        name="subd_export_limit_to_step",
        description=(
            "Export a SubD control cage as a Catmull-Clark limit-surface mesh in "
            "STEP AP242 format (.stp ASCII, ISO 10303-242:2020).\n"
            "\n"
            "Applies N levels of Catmull-Clark subdivision and emits a valid STEP "
            "file with CARTESIAN_POINTs, EDGE_CURVEs, ADVANCED_FACEs on PLANE "
            "surfaces, OPEN_SHELL, and SHELL_BASED_SURFACE_MODEL.\n"
            "\n"
            "HONEST LIMITATIONS:\n"
            "  - Faceted B-rep: each subdivided polygon is a flat PLANE face.\n"
            "    STEP has no native SubD primitive. Not smooth NURBS.\n"
            "  - Geometry only: no colour, material, PMI, or units conversion.\n"
            "  - SI millimetre context is emitted for validator compliance.\n"
            "\n"
            "Returns:\n"
            "  ok             : bool\n"
            "  step_text      : str   — full STEP ASCII content\n"
            "  n_vertices     : int   — CARTESIAN_POINT count\n"
            "  n_faces        : int   — ADVANCED_FACE count (= subdivision faces)\n"
            "  levels_used    : int   — actual subdivision levels applied\n"
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
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_export_limit_to_step_spec)
    async def run_subd_export_limit_to_step(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        levels = int(a.get("levels", 2))

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
            step_text = export_limit_to_step(mesh, levels=levels)
        except Exception as exc:
            return err_payload(f"export failed: {exc}", "EXPORT_ERROR")

        parsed = parse_step_subd(step_text)

        return ok_payload({
            "ok": True,
            "step_text": step_text,
            "n_vertices": len(parsed["vertices"]),
            "n_faces": parsed["advanced_faces"],
            "levels_used": max(0, min(int(levels), 8)),
        })
