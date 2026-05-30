"""
oblique_projection.py
=====================
Oblique projection for B-rep / tessellated bodies — cabinet, cavalier and
general oblique per Bertoline-Wiebe "Fundamentals of Graphics Communication"
§11 and ISO 5456-2.

Background
----------
An oblique projection keeps the *front face* (XY-plane) undistorted and maps
the receding (Z) axis to a line at ``angle_deg`` from the horizontal, scaled
by ``scale_z``.  The shearing transform is:

    x' = x + z · cos(angle_rad)
    y' = y + z · sin(angle_rad) · scale_z

Standard types
~~~~~~~~~~~~~~
Cabinet
    angle = 30°, scale_z = 0.5  (Bertoline §11 "cabinet oblique")
    The depth dimension is drawn at half scale so the drawing looks least
    distorted.  Most common in furniture and cabinet-making drawings.

Cavalier
    angle = 45°, scale_z = 1.0  (Bertoline §11 "cavalier oblique")
    All three axes drawn at true scale; looks more distorted than cabinet.

General
    User-specified angle and scale_z.

Isometric (special case)
    Standard isometric: three equal axes at 120° to each other.  Achieved by
    projecting along [1, -1, -1] / √3 with the right rotation; handled here
    as a true orthographic isometric for exact angle fidelity.

Public API
----------
ObliqueDrawing(dataclass)
    Result of an oblique projection: ``visible`` and ``hidden`` polylines,
    ``projection_matrix`` 3×3 float64 (the oblique shear transform),
    ``projection_type``, ``angle_deg``, ``scale_z``.

oblique_project(body, projection_type='cabinet', angle_deg=30, scale_z=0.5)
    -> ObliqueDrawing
    Main entry point.  Accepts a B-rep Body or Make2DInput mesh.

isometric_projection(body) -> ObliqueDrawing
    True orthographic isometric (all axes at 120°, equal scale).

oblique_view_for_drawing(body, type, *, with_hidden_lines=True)
    Full drawing-entry wrapper; returns ``ObliqueDrawing`` with full
    visible/hidden edge classification.

LLM tool: ``drawing_oblique_projection``

Never raises — all exceptions are caught and returned as
``{"ok": False, "reason": ...}``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# Re-use the make2d pipeline for occlusion + edge extraction.
from kerf_cad_core.geom.make2d import (
    Make2DInput,
    Make2DResult,
    ViewParams,
    _build_edge_face_map,
    _build_view_matrix,
    _classify_segment_visibility,
    _compute_face_normals,
    _edge_key,
    _extract_feature_edges,
    _extract_silhouette_edges,
    _make_cube_mesh,
    _project_vertices,
    _TOL,
    make2d,
    brep_to_make2d_input,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CABINET_ANGLE_DEG: float = 30.0
_CABINET_SCALE_Z: float = 0.5

_CAVALIER_ANGLE_DEG: float = 45.0
_CAVALIER_SCALE_Z: float = 1.0

# Isometric: look along [1, 1, 1]/√3 — the only direction that gives exactly
# 120° between all three projected axis pairs (Bertoline §11, Fig. 17-3).
# Note: standard_views()["iso"] uses [1,-1,-1] which gives 60°/120°/60° and
# is an isometric *camera pose* for engineering views, but for the drawing-
# standards isometric (all three axes at 120° in the 2D plane) we need [1,1,1].
_ISO_DIR: List[float] = [1.0, 1.0, 1.0]

_SUBDIVISIONS: int = 8

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ObliqueDrawing:
    """Output of an oblique or isometric projection.

    Attributes
    ----------
    visible : list of polylines
        Each polyline is a list of (x, y) 2-D points (solid / visible edges).
    hidden : list of polylines
        Each polyline is a list of (x, y) 2-D points (hidden / dashed edges).
    projection_matrix : np.ndarray (3, 3)
        The 3×3 oblique shear matrix applied (first two rows give the XY-plane
        mapping; third row encodes the receding-axis shear).
    projection_type : str
        One of ``'cabinet'``, ``'cavalier'``, ``'general'``, ``'isometric'``.
    angle_deg : float
        Receding-axis angle from the horizontal (degrees).
    scale_z : float
        Scale factor applied along the receding (depth) axis.
    visible_count : int
    hidden_count : int
    """
    visible: List[List[Tuple[float, float]]] = field(default_factory=list)
    hidden: List[List[Tuple[float, float]]] = field(default_factory=list)
    projection_matrix: np.ndarray = field(default_factory=lambda: np.eye(3))
    projection_type: str = "cabinet"
    angle_deg: float = _CABINET_ANGLE_DEG
    scale_z: float = _CABINET_SCALE_Z
    visible_count: int = 0
    hidden_count: int = 0


# ---------------------------------------------------------------------------
# Oblique shear math
# ---------------------------------------------------------------------------


def _build_oblique_matrix(angle_deg: float, scale_z: float) -> np.ndarray:
    """Build the 3×3 oblique projection matrix (Bertoline §11, ISO 5456-2 eq. 3).

    The matrix maps 3-D point (x, y, z) → 2-D (x', y'):

        x' = x + z · cos(θ)
        y' = y + z · sin(θ) · scale_z

    where θ = angle_deg (receding-axis angle from horizontal).

    Returned as a (3, 3) matrix M such that

        [x', y', 1]^T  = M @ [x, y, z]^T   (homogeneous 2-D coords, z treated as param)

    More precisely, the first two rows extract (x', y'):

        M[0] = [1,       0,  cos(θ)          ]
        M[1] = [0,       1,  sin(θ) · scale_z]
        M[2] = [0,       0,  1               ]  (pass-through depth for occlusion)
    """
    theta = math.radians(angle_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    M = np.array([
        [1.0,  0.0,  cos_t],
        [0.0,  1.0,  sin_t * scale_z],
        [0.0,  0.0,  1.0],
    ], dtype=float)
    return M


def _apply_oblique_to_vertices(
    vertices: np.ndarray,
    oblique_mat: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Apply the oblique shear to (N, 3) vertices.

    The oblique drawing convention treats the *front face* (XZ→XY projection)
    with a fixed front view (looking along -Y axis, so the front-face is in
    the XZ plane).  We first rotate the model so the front face lies in XZ
    (i.e. we swap y↔z convention to match the standard drawing-board convention
    where X→right, Y→up, Z→into the page).

    For the oblique transform we use world coordinates directly:
        X → drawing X (horizontal)
        Z → drawing Y (vertical)      [the "up" axis in drawing]
        Y → receding oblique axis

    This matches Bertoline §11 Figure 11-5 where the front face is XZ and
    the depth dimension goes into the page (Y-world).

    Parameters
    ----------
    vertices : (N, 3) float
        Centred 3-D vertices [x_world, y_world, z_world].
    oblique_mat : (3, 3) float
        From _build_oblique_matrix.

    Returns
    -------
    uv : (N, 2) float
        Projected 2-D coordinates (drawing X, drawing Y).
    depth : (N,) float
        Depth value for each vertex (used for occlusion; we use y_world as
        depth since that is the receding direction).
    """
    # The oblique convention: front face is XZ (X→right, Z→up, Y→receding).
    # We remap world coords: oblique_x = world_x, oblique_z = world_z,
    # oblique_depth = world_y.
    #
    #   x_draw = x_world + y_world · cos(θ)
    #   y_draw = z_world + y_world · sin(θ) · scale_z

    x_w = vertices[:, 0]
    y_w = vertices[:, 1]   # receding / depth axis
    z_w = vertices[:, 2]   # drawing vertical

    cos_t = oblique_mat[0, 2]
    sin_t_sz = oblique_mat[1, 2]

    x_draw = x_w + y_w * cos_t
    y_draw = z_w + y_w * sin_t_sz

    uv = np.column_stack([x_draw, y_draw])
    # Depth: positive y = farther away (into the page)
    depth = y_w.copy()
    return uv, depth


# ---------------------------------------------------------------------------
# Edge visibility in oblique space
# ---------------------------------------------------------------------------


def _oblique_visible_hidden(
    mesh: Make2DInput,
    oblique_mat: np.ndarray,
    with_hidden_lines: bool = True,
    subdivisions: int = _SUBDIVISIONS,
    tol: float = _TOL,
) -> Tuple[List[List[Tuple[float, float]]], List[List[Tuple[float, float]]]]:
    """Project a tessellated mesh obliquely and classify edges as visible/hidden.

    Uses the same occlusion pipeline as make2d but with the oblique shear
    substituting the orthographic projection step.

    Returns
    -------
    visible, hidden : lists of polylines
    """
    # Centre the mesh
    centroid = mesh.vertices.mean(axis=0)
    verts_c = mesh.vertices - centroid

    # Project with oblique shear
    proj_verts, vert_depths = _apply_oblique_to_vertices(verts_c, oblique_mat)

    # Face normals (in world space) — use original 3D coords
    face_normals = _compute_face_normals(verts_c, mesh.triangles)

    # View direction for the oblique projection is along -Y (into the page).
    # Front-face normal pointing toward the viewer is +Y.
    view_dir = np.array([0.0, 1.0, 0.0])

    # Edge → face adjacency
    ef_map = _build_edge_face_map(mesh.triangles)

    # Feature edges (silhouette + crease)
    feature_edges = _extract_feature_edges(mesh, face_normals, ef_map)
    silhouette_edges = _extract_silhouette_edges(
        mesh, face_normals, ef_map, view_dir
    )

    # Merge unique edges
    all_edges: Dict[Tuple[int, int], bool] = {}
    for e in silhouette_edges:
        all_edges[e] = True
    for e in feature_edges:
        if e not in all_edges:
            all_edges[e] = False

    # Per-face max depth (for bounding box culling in occlusion test)
    face_depths = np.array([
        max(vert_depths[t[0]], vert_depths[t[1]], vert_depths[t[2]])
        for t in mesh.triangles
    ])

    visible_polylines: List[List[Tuple[float, float]]] = []
    hidden_polylines: List[List[Tuple[float, float]]] = []

    for (i0, i1) in all_edges:
        uv_a = proj_verts[i0]
        uv_b = proj_verts[i1]
        da = float(vert_depths[i0])
        db = float(vert_depths[i1])

        # Skip degenerate
        if np.linalg.norm(uv_b - uv_a) < _TOL:
            continue

        owner_faces = frozenset(ef_map.get(_edge_key(i0, i1), []))

        seg = [
            (float(uv_a[0]), float(uv_a[1])),
            (float(uv_b[0]), float(uv_b[1])),
        ]

        if with_hidden_lines:
            is_visible = _classify_segment_visibility(
                uv_a, da, uv_b, db,
                proj_verts, vert_depths,
                mesh.triangles, face_depths,
                owner_faces,
                subdivisions, tol,
            )
            if is_visible:
                visible_polylines.append(seg)
            else:
                hidden_polylines.append(seg)
        else:
            visible_polylines.append(seg)

    return visible_polylines, hidden_polylines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def oblique_project(
    body,
    projection_type: str = "cabinet",
    angle_deg: Optional[float] = None,
    scale_z: Optional[float] = None,
    *,
    with_hidden_lines: bool = True,
    subdivisions: int = _SUBDIVISIONS,
    linear_deflection: float = 1e-2,
) -> ObliqueDrawing:
    """Project a body obliquely per Bertoline §11 / ISO 5456-2.

    Parameters
    ----------
    body :
        A B-rep ``Body`` (tessellated via :func:`brep_to_make2d_input`) **or**
        a pre-built :class:`Make2DInput` mesh.
    projection_type : str
        One of:
        - ``'cabinet'``  — 30°, 1:1:0.5 (default)
        - ``'cavalier'`` — 45°, 1:1:1
        - ``'general'``  — use explicit ``angle_deg`` + ``scale_z``
    angle_deg : float, optional
        Receding-axis angle from horizontal (degrees).  Overrides the
        type-specific default when ``projection_type='general'``.
    scale_z : float, optional
        Scale factor for the receding (depth) axis.  Overrides the
        type-specific default when ``projection_type='general'``.
    with_hidden_lines : bool
        If ``True`` (default), classify back edges as hidden.
    subdivisions : int
        Occlusion sample density per edge (default 8).
    linear_deflection : float
        Tessellation tolerance when tessellating a B-rep body.

    Returns
    -------
    ObliqueDrawing
    """
    # Resolve type defaults
    pt = projection_type.lower()
    if pt == "cabinet":
        _angle = _CABINET_ANGLE_DEG
        _scalez = _CABINET_SCALE_Z
    elif pt == "cavalier":
        _angle = _CAVALIER_ANGLE_DEG
        _scalez = _CAVALIER_SCALE_Z
    elif pt == "general":
        if angle_deg is None or scale_z is None:
            raise ValueError(
                "oblique_project: 'general' type requires explicit "
                "angle_deg and scale_z"
            )
        _angle = float(angle_deg)
        _scalez = float(scale_z)
    else:
        raise ValueError(
            f"oblique_project: unknown projection_type {projection_type!r}. "
            "Use 'cabinet', 'cavalier', or 'general'."
        )

    # Override per-parameter if supplied for non-general types
    if angle_deg is not None:
        _angle = float(angle_deg)
    if scale_z is not None:
        _scalez = float(scale_z)

    # Tessellate B-rep or accept pre-built mesh
    if isinstance(body, Make2DInput):
        mesh = body
    else:
        mesh = brep_to_make2d_input(body, linear_deflection=linear_deflection)

    oblique_mat = _build_oblique_matrix(_angle, _scalez)

    visible, hidden = _oblique_visible_hidden(
        mesh, oblique_mat,
        with_hidden_lines=with_hidden_lines,
        subdivisions=subdivisions,
    )

    return ObliqueDrawing(
        visible=visible,
        hidden=hidden,
        projection_matrix=oblique_mat,
        projection_type=pt,
        angle_deg=_angle,
        scale_z=_scalez,
        visible_count=len(visible),
        hidden_count=len(hidden),
    )


def isometric_projection(
    body,
    *,
    with_hidden_lines: bool = True,
    subdivisions: int = _SUBDIVISIONS,
    linear_deflection: float = 1e-2,
) -> ObliqueDrawing:
    """True orthographic isometric projection (all axes at 120°, equal scale).

    Uses the standard isometric view direction [1, -1, -1]/√3 via the
    make2d orthographic pipeline, then wraps the result in an
    :class:`ObliqueDrawing`.

    The canonical isometric property: when a unit cube is projected, the
    three visible faces each show axes at 120° to each other in the 2-D
    drawing.

    Parameters
    ----------
    body :
        B-rep ``Body`` or :class:`Make2DInput` mesh.
    with_hidden_lines : bool
        Classify and return hidden edges.

    Returns
    -------
    ObliqueDrawing
        ``projection_type='isometric'``, ``angle_deg=30.0``,
        ``scale_z=1.0`` (equal-axis isometric).
    """
    if isinstance(body, Make2DInput):
        mesh = body
    else:
        mesh = brep_to_make2d_input(body, linear_deflection=linear_deflection)

    iso_dir = np.array(_ISO_DIR, dtype=float)
    iso_dir /= np.linalg.norm(iso_dir)

    vp = ViewParams(direction=iso_dir.tolist(), up=[0.0, 0.0, 1.0])
    result: Make2DResult = make2d(
        mesh, vp,
        scale=1.0,
        subdivisions=subdivisions,
    )

    # The isometric matrix is a standard 2/3-row extraction of the
    # isometric view rotation.  For completeness we store the oblique
    # equivalent (axonometric = oblique with angle=30, scale_z=1).
    oblique_mat = _build_oblique_matrix(30.0, 1.0)

    visible = result.visible if with_hidden_lines or True else result.visible
    hidden = result.hidden if with_hidden_lines else []

    return ObliqueDrawing(
        visible=visible,
        hidden=hidden,
        projection_matrix=oblique_mat,
        projection_type="isometric",
        angle_deg=30.0,
        scale_z=1.0,
        visible_count=len(visible),
        hidden_count=len(hidden),
    )


def oblique_view_for_drawing(
    body,
    type: str = "cabinet",  # noqa: A002
    *,
    with_hidden_lines: bool = True,
    angle_deg: Optional[float] = None,
    scale_z: Optional[float] = None,
    subdivisions: int = _SUBDIVISIONS,
    linear_deflection: float = 1e-2,
) -> ObliqueDrawing:
    """Full drawing-entry point with edge classification.

    Convenience wrapper around :func:`oblique_project` that normalises the
    ``type`` parameter name (mirrors the LLM tool signature).

    Parameters
    ----------
    body :
        B-rep ``Body`` or :class:`Make2DInput` mesh.
    type : str
        ``'cabinet'``, ``'cavalier'``, ``'general'``, or ``'isometric'``.
    with_hidden_lines : bool
        Return hidden edges in ``ObliqueDrawing.hidden`` (default ``True``).
    angle_deg, scale_z :
        Override defaults for ``'general'`` or fine-tuning.

    Returns
    -------
    ObliqueDrawing
    """
    t = type.lower()
    if t == "isometric":
        return isometric_projection(
            body,
            with_hidden_lines=with_hidden_lines,
            subdivisions=subdivisions,
            linear_deflection=linear_deflection,
        )
    return oblique_project(
        body,
        projection_type=t,
        angle_deg=angle_deg,
        scale_z=scale_z,
        with_hidden_lines=with_hidden_lines,
        subdivisions=subdivisions,
        linear_deflection=linear_deflection,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _oblique_spec = ToolSpec(
        name="drawing_oblique_projection",
        description=(
            "Generate an oblique or isometric projection of a 3-D mesh for "
            "cabinet/cavalier/technical drawings per Bertoline §11 and "
            "ISO 5456-2.\n"
            "\n"
            "Projection types:\n"
            "  cabinet   — 30° angle, 1:1:0.5 axis ratio (Bertoline cabinet oblique)\n"
            "  cavalier  — 45° angle, 1:1:1  axis ratio (all axes equal scale)\n"
            "  general   — user-specified angle_deg + scale_z\n"
            "  isometric — true 30°-30°-30° isometric (equal axes, 120° between axes)\n"
            "\n"
            "Returns:\n"
            "  ok               : bool\n"
            "  visible          : list of [[x,y],...] polylines (solid lines)\n"
            "  hidden           : list of [[x,y],...] polylines (dashed lines)\n"
            "  visible_count    : int\n"
            "  hidden_count     : int\n"
            "  projection_type  : str\n"
            "  angle_deg        : float\n"
            "  scale_z          : float\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "List of 3D vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "triangles": {
                    "type": "array",
                    "description": "Triangle index triples [[i,j,k], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "projection_type": {
                    "type": "string",
                    "enum": ["cabinet", "cavalier", "general", "isometric"],
                    "description": "Projection type (default 'cabinet').",
                },
                "angle_deg": {
                    "type": "number",
                    "description": (
                        "Receding-axis angle from horizontal (degrees). "
                        "Required for 'general'; overrides default for others."
                    ),
                },
                "scale_z": {
                    "type": "number",
                    "description": (
                        "Depth-axis scale factor. Required for 'general'; "
                        "overrides default for others."
                    ),
                },
                "with_hidden_lines": {
                    "type": "boolean",
                    "description": "Include hidden edges in output (default true).",
                },
                "subdivisions": {
                    "type": "integer",
                    "description": "Occlusion sample count per edge (default 8).",
                },
            },
            "required": ["vertices", "triangles"],
        },
    )

    @register(_oblique_spec)
    async def run_drawing_oblique_projection(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices")
        raw_tris = a.get("triangles")

        if raw_verts is None or raw_tris is None:
            return err_payload("vertices and triangles are required", "BAD_ARGS")

        try:
            verts = np.array(raw_verts, dtype=float)
            tris = np.array(raw_tris, dtype=int)
        except Exception as exc:
            return err_payload(f"invalid mesh data: {exc}", "BAD_ARGS")

        proj_type = str(a.get("projection_type", "cabinet"))
        angle_deg = a.get("angle_deg")
        scale_z = a.get("scale_z")
        with_hidden = bool(a.get("with_hidden_lines", True))
        subs = int(a.get("subdivisions", _SUBDIVISIONS))

        if proj_type not in ("cabinet", "cavalier", "general", "isometric"):
            return err_payload(
                f"projection_type must be one of cabinet/cavalier/general/isometric; "
                f"got {proj_type!r}",
                "BAD_ARGS",
            )
        if proj_type == "general" and (angle_deg is None or scale_z is None):
            return err_payload(
                "'general' projection_type requires angle_deg and scale_z",
                "BAD_ARGS",
            )

        mesh = Make2DInput(vertices=verts, triangles=tris)
        valid, reason = mesh.is_valid()
        if not valid:
            return err_payload(reason, "BAD_ARGS")

        try:
            drawing = oblique_view_for_drawing(
                mesh,
                type=proj_type,
                with_hidden_lines=with_hidden,
                angle_deg=float(angle_deg) if angle_deg is not None else None,
                scale_z=float(scale_z) if scale_z is not None else None,
                subdivisions=subs,
            )
        except Exception as exc:
            return err_payload(f"oblique_project failed: {exc}", "OP_FAILED")

        return ok_payload({
            "visible": [[[p[0], p[1]] for p in poly] for poly in drawing.visible],
            "hidden":  [[[p[0], p[1]] for p in poly] for poly in drawing.hidden],
            "visible_count": drawing.visible_count,
            "hidden_count":  drawing.hidden_count,
            "projection_type": drawing.projection_type,
            "angle_deg": drawing.angle_deg,
            "scale_z":   drawing.scale_z,
        })
