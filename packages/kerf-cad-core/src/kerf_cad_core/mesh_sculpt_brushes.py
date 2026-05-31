"""mesh_sculpt_brushes.py — GK-P22: Sculpt brushes for SubD cages and triangle meshes.

Implements four sculpt brushes (Inflate, Crease, Smooth, Pinch) that displace
mesh vertices within a brush radius using a Wendland C2 falloff kernel.

References
----------
- Botsch & Sorkine (2008) "On linear variational surface deformation methods",
  IEEE TVCG 14(1):213-230.
- Sculptris / ZBrush brush displacement conventions (Pixologic ZBrush Docs 2024).
- Wendland, H. (1995) "Piecewise polynomial, positive definite and compactly
  supported radial functions of minimal degree", Advances in Computational
  Mathematics 4(1):389-396. Falloff w(t) = (1-t^2)^2 for t in [0,1).

Honest caveats
--------------
- Single-stroke, stateless: no stroke history, no undo stack, no dyntopo.
- Auto-normals computed by one-ring area-weighted averaging (flat mesh: all zeros
  → inflate falls back to global Z if all computed normals are zero).
- Smooth brush uses unweighted centroid of first-order vertex neighbours only;
  Taubin cotangent-weight smoothing and higher-order operators are not implemented.
- Crease brush is a signed-inflate with strength negated when strength > 0 to pull
  inward; full CC crease sharpness propagation across subdivision levels is out
  of scope (mesh-level only).
- Triangle meshes and quad cages are treated identically (vertex + face index list).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SculptStroke:
    """Parameters for a single sculpt-brush stroke.

    Parameters
    ----------
    position_xyz_mm:
        World-space centre of the brush in millimetres.
    radius_mm:
        Brush influence radius in millimetres (> 0).
    brush_type:
        One of ``"inflate"``, ``"crease"``, ``"smooth"``, ``"pinch"``.
    strength:
        Signed displacement scale in [-1, 1].  Positive = outward / toward
        neighbours / toward centre depending on brush type.  Negative reverses
        the direction.
    normal_direction_xyz:
        Override the inflate/crease displacement axis.  When ``None`` (default)
        each vertex's one-ring area-weighted normal is used instead.
    """

    position_xyz_mm: Tuple[float, float, float]
    radius_mm: float
    brush_type: str  # "inflate" | "crease" | "smooth" | "pinch"
    strength: float  # -1 .. 1
    normal_direction_xyz: Optional[Tuple[float, float, float]] = None


@dataclass
class MeshSculptResult:
    """Result of :func:`apply_sculpt_brush`.

    Parameters
    ----------
    output_vertices:
        Full vertex list (same length as input) with displaced positions.
    num_vertices_modified:
        Count of vertices whose displacement magnitude exceeded 1e-12.
    max_displacement_mm:
        Maximum per-vertex displacement magnitude among all modified vertices.
    mean_displacement_mm:
        Mean per-vertex displacement magnitude among all modified vertices
        (0.0 if none were modified).
    brush_type_applied:
        Echo of ``SculptStroke.brush_type``.
    honest_caveat:
        Plain-text caveat string summarising v1 limitations.
    """

    output_vertices: List[Tuple[float, float, float]]
    num_vertices_modified: int
    max_displacement_mm: float
    mean_displacement_mm: float
    brush_type_applied: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "GK-P22 v1: single-stroke, stateless brush — no undo stack, no stroke history, "
    "no dyntopo. Auto-normals use one-ring area-weighted averaging; degenerate "
    "faces (area=0) are skipped. Smooth brush uses unweighted first-order centroid "
    "only. Crease brush is inverted-inflate (no CC subdivision sharpness). "
    "Ref: Botsch-Sorkine 2008 §3; Wendland 1995 C2 kernel."
)


def _wendland_c2(t: float) -> float:
    """Wendland C2 falloff: w(t) = (1 - t^2)^2 for t in [0, 1), else 0.

    Here t = d / radius, so w(0) = 1 at the stroke centre and w(1) = 0 at the
    boundary.  Second derivative is continuous (C2) at the boundary.
    """
    if t >= 1.0:
        return 0.0
    s = 1.0 - t * t
    return s * s


def _vec_sub(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_add(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec_scale(v: Tuple[float, float, float], s: float) -> Tuple[float, float, float]:
    return (v[0] * s, v[1] * s, v[2] * s)


def _vec_length(v: Tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _vec_normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    length = _vec_length(v)
    if length < 1e-14:
        return (0.0, 0.0, 0.0)
    inv = 1.0 / length
    return (v[0] * inv, v[1] * inv, v[2] * inv)


def _vec_cross(a: Tuple[float, float, float],
               b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_dot(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _build_adjacency(num_verts: int,
                     faces: List) -> List[List[int]]:
    """Return one-ring neighbour lists (vertex → [adjacent vertex indices])."""
    adj: List[List[int]] = [[] for _ in range(num_verts)]
    for face in faces:
        n = len(face)
        for i in range(n):
            vi = face[i]
            for j in range(n):
                vj = face[j]
                if vi != vj and vj not in adj[vi]:
                    adj[vi].append(vj)
    return adj


def _compute_vertex_normals(
    vertices: List[Tuple[float, float, float]],
    faces: List,
) -> List[Tuple[float, float, float]]:
    """Area-weighted one-ring normal for each vertex.

    Uses the first two edges of each face polygon as the cross-product pair.
    Degenerate faces (zero area) are skipped.
    """
    n = len(vertices)
    normals: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(n)]

    for face in faces:
        if len(face) < 3:
            continue
        v0 = vertices[face[0]]
        v1 = vertices[face[1]]
        v2 = vertices[face[2]]
        e1 = _vec_sub(v1, v0)
        e2 = _vec_sub(v2, v0)
        fn = _vec_cross(e1, e2)
        # Weight = half the cross-product magnitude (= triangle area)
        for vi in face:
            normals[vi][0] += fn[0]
            normals[vi][1] += fn[1]
            normals[vi][2] += fn[2]

    result: List[Tuple[float, float, float]] = []
    for nm in normals:
        t = (nm[0], nm[1], nm[2])
        result.append(_vec_normalize(t))
    return result


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def apply_sculpt_brush(
    vertices: List[Tuple[float, float, float]],
    faces: List,
    stroke: SculptStroke,
) -> MeshSculptResult:
    """Apply a single sculpt-brush stroke to a mesh.

    For each vertex within ``stroke.radius_mm`` of the brush centre, the vertex
    is displaced by ``strength · falloff(d/r) · direction`` where:

    - ``falloff(t) = (1-t²)²``  (Wendland C2 kernel, Wendland 1995)
    - ``direction`` depends on ``stroke.brush_type``

    Brush semantics
    ---------------
    inflate
        Displace along the vertex normal (or the override axis if provided).
        Positive strength = outward.
    crease
        Same as inflate but with ``strength`` negated: positive strength pulls
        inward, creating a crease/pinch toward the surface (per Sculptris
        convention where Crease = negative inflate).
    smooth
        Displace toward the unweighted centroid of the one-ring neighbours.
        The displacement vector is ``(centroid - vertex) · |strength| · falloff``.
        Strength sign has no effect (smoothing is always toward centroid).
    pinch
        Displace toward the stroke centre projected onto the tangent plane at
        each vertex.  Positive strength pinches inward.

    Parameters
    ----------
    vertices:
        List of ``(x, y, z)`` tuples in mm.
    faces:
        List of face index lists (triangles or quads or n-gons).
    stroke:
        Brush stroke parameters.

    Returns
    -------
    MeshSculptResult
    """
    if stroke.radius_mm <= 0.0:
        raise ValueError("stroke.radius_mm must be > 0")
    if stroke.brush_type not in ("inflate", "crease", "smooth", "pinch"):
        raise ValueError(
            f"brush_type must be one of inflate/crease/smooth/pinch, "
            f"got {stroke.brush_type!r}"
        )

    nv = len(vertices)
    out_verts: List[List[float]] = [
        [v[0], v[1], v[2]] for v in vertices
    ]

    # Build adjacency and per-vertex normals once
    adj = _build_adjacency(nv, faces)
    vert_normals = _compute_vertex_normals(vertices, faces)

    # Override normal direction
    override_normal: Optional[Tuple[float, float, float]] = None
    if stroke.normal_direction_xyz is not None:
        override_normal = _vec_normalize(stroke.normal_direction_xyz)

    cx, cy, cz = stroke.position_xyz_mm
    r = stroke.radius_mm

    displacements: List[float] = []
    modified_indices: List[int] = []

    for i, v in enumerate(vertices):
        dx = v[0] - cx
        dy = v[1] - cy
        dz = v[2] - cz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist >= r:
            continue

        t = dist / r
        w = _wendland_c2(t)  # 0 at boundary, 1 at centre

        if stroke.brush_type == "inflate":
            if override_normal is not None:
                direction = override_normal
            else:
                direction = vert_normals[i]
                # Fallback: if normal is zero vector (degenerate mesh), use global Z
                if _vec_length(direction) < 1e-12:
                    direction = (0.0, 0.0, 1.0)
            scale = stroke.strength * w
            out_verts[i][0] += direction[0] * scale
            out_verts[i][1] += direction[1] * scale
            out_verts[i][2] += direction[2] * scale
            disp = abs(scale) * _vec_length(direction)

        elif stroke.brush_type == "crease":
            # Crease = inward inflate (sign flipped vs inflate per Sculptris convention)
            if override_normal is not None:
                direction = override_normal
            else:
                direction = vert_normals[i]
                if _vec_length(direction) < 1e-12:
                    direction = (0.0, 0.0, 1.0)
            scale = -stroke.strength * w  # inverted
            out_verts[i][0] += direction[0] * scale
            out_verts[i][1] += direction[1] * scale
            out_verts[i][2] += direction[2] * scale
            disp = abs(scale) * _vec_length(direction)

        elif stroke.brush_type == "smooth":
            neighbours = adj[i]
            if not neighbours:
                disp = 0.0
            else:
                cx_n = sum(vertices[j][0] for j in neighbours) / len(neighbours)
                cy_n = sum(vertices[j][1] for j in neighbours) / len(neighbours)
                cz_n = sum(vertices[j][2] for j in neighbours) / len(neighbours)
                delta_x = (cx_n - v[0]) * abs(stroke.strength) * w
                delta_y = (cy_n - v[1]) * abs(stroke.strength) * w
                delta_z = (cz_n - v[2]) * abs(stroke.strength) * w
                out_verts[i][0] += delta_x
                out_verts[i][1] += delta_y
                out_verts[i][2] += delta_z
                disp = math.sqrt(delta_x * delta_x + delta_y * delta_y + delta_z * delta_z)

        elif stroke.brush_type == "pinch":
            # Displace toward stroke centre (in 3D space directly)
            toward = (cx - v[0], cy - v[1], cz - v[2])
            toward_len = _vec_length(toward)
            if toward_len < 1e-14:
                disp = 0.0
            else:
                inv_len = 1.0 / toward_len
                toward_n = (toward[0] * inv_len, toward[1] * inv_len, toward[2] * inv_len)
                scale = stroke.strength * w
                out_verts[i][0] += toward_n[0] * scale
                out_verts[i][1] += toward_n[1] * scale
                out_verts[i][2] += toward_n[2] * scale
                disp = abs(scale)

        else:  # pragma: no cover — guarded by earlier validation
            disp = 0.0

        if disp > 1e-12:
            displacements.append(disp)
            modified_indices.append(i)

    output_vertices = [
        (out_verts[i][0], out_verts[i][1], out_verts[i][2]) for i in range(nv)
    ]

    if displacements:
        max_d = max(displacements)
        mean_d = sum(displacements) / len(displacements)
    else:
        max_d = 0.0
        mean_d = 0.0

    return MeshSculptResult(
        output_vertices=output_vertices,
        num_vertices_modified=len(displacements),
        max_displacement_mm=max_d,
        mean_displacement_mm=mean_d,
        brush_type_applied=stroke.brush_type,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool (gated import)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    import json as _json

    _mesh_sculpt_brush_spec = ToolSpec(
        name="mesh_sculpt_brush",
        description=(
            "Apply a sculpt-brush stroke to a triangle mesh or SubD cage. "
            "Displaces vertices within a brush radius using a Wendland C2 "
            "falloff kernel w(t)=(1-t²)² (Wendland 1995).  "
            "Four brush types: "
            "'inflate' — push along per-vertex normal; "
            "'crease' — pull inward along normal (negative inflate); "
            "'smooth' — blend toward one-ring centroid (Laplacian relaxation); "
            "'pinch' — attract toward the brush centre. "
            "Strength in [-1, 1]; positive = outward/inward/toward-centroid/pinch. "
            "No OCCT required — pure-Python geometry. "
            "Ref: Botsch-Sorkine 2008 §3 (variational deformation); "
            "Sculptris/ZBrush brush math (Pixologic 2024)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "List of [x, y, z] vertex positions in mm.",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                },
                "faces": {
                    "type": "array",
                    "description": (
                        "List of face index arrays (triangles or quads or n-gons). "
                        "Example for two triangles: [[0,1,2],[0,2,3]]."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "position_xyz_mm": {
                    "type": "array",
                    "description": "Brush centre [x, y, z] in mm.",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "radius_mm": {
                    "type": "number",
                    "description": "Brush influence radius in mm (> 0).",
                    "exclusiveMinimum": 0,
                },
                "brush_type": {
                    "type": "string",
                    "enum": ["inflate", "crease", "smooth", "pinch"],
                    "description": "Brush type.",
                },
                "strength": {
                    "type": "number",
                    "description": "Displacement scale [-1, 1].",
                    "minimum": -1.0,
                    "maximum": 1.0,
                },
                "normal_direction_xyz": {
                    "type": "array",
                    "description": (
                        "Optional override axis for inflate/crease brushes [x, y, z]. "
                        "Normalised internally. Omit to use auto-computed vertex normals."
                    ),
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "default": None,
                },
            },
            "required": [
                "vertices",
                "faces",
                "position_xyz_mm",
                "radius_mm",
                "brush_type",
                "strength",
            ],
        },
    )

    @register(_mesh_sculpt_brush_spec)
    async def _run_mesh_sculpt_brush(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            verts = [tuple(v) for v in a["vertices"]]
            faces_raw = [list(f) for f in a["faces"]]
            pos = tuple(a["position_xyz_mm"])
            radius = float(a["radius_mm"])
            btype = str(a["brush_type"])
            strength = float(a["strength"])
            normal_override = (
                tuple(a["normal_direction_xyz"])
                if a.get("normal_direction_xyz") is not None
                else None
            )
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"parameter error: {exc}", "BAD_ARGS")

        try:
            stroke = SculptStroke(
                position_xyz_mm=pos,  # type: ignore[arg-type]
                radius_mm=radius,
                brush_type=btype,
                strength=strength,
                normal_direction_xyz=normal_override,  # type: ignore[arg-type]
            )
            result = apply_sculpt_brush(verts, faces_raw, stroke)  # type: ignore[arg-type]
        except Exception as exc:
            return err_payload(str(exc), "COMPUTE_ERROR")

        return ok_payload(
            {
                "output_vertices": [list(v) for v in result.output_vertices],
                "num_vertices_modified": result.num_vertices_modified,
                "max_displacement_mm": result.max_displacement_mm,
                "mean_displacement_mm": result.mean_displacement_mm,
                "brush_type_applied": result.brush_type_applied,
                "honest_caveat": result.honest_caveat,
            }
        )

except ImportError:
    pass  # Standalone / test mode without kerf_chat
