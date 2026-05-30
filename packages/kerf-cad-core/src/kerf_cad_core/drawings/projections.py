"""
kerf_cad_core.drawings.projections
====================================

Automatic 6-view orthographic projection + isometric view generation from a
3D B-rep body or tessellated mesh — per ISO 128-30 and Bertoline-Wiebe
"Fundamentals of Graphics Communication" 5th ed §10.

Given a body (B-rep ``Body`` instance, or a mesh dict with vertices/triangles),
generates:

  • 6 standard orthographic views (front, back, top, bottom, left, right).
  • 1 isometric view (30°/30°/30° azimuth/elevation, body-centred).
  • Hidden-line removal per view: visible edges drawn solid, hidden edges dashed.
  • Third-angle (ANSI/ASME) or first-angle (ISO/DIN) projection layout on a
    standard sheet.

Public API
----------
generate_six_view_drawing(body, projection_type='third_angle', include_iso=True,
                          sheet='A3', scale=None) -> ViewSheet
    Main entry point.

compute_projection_silhouette(body, view_direction) -> list[list[[x,y]]]
    Silhouette curves of the body projected onto the given view plane.

hidden_line_removal(body, view_direction, projection_resolution=0.01)
    -> (visible_edges, hidden_edges)
    Hidden-line classification per view direction.

Data structures
---------------
Curve2D  — a list of [x, y] 2-D points (a polyline segment)
ProjectionView — per-view result (visible/hidden edges, bounding box, label)
ViewSheet — the complete multi-view drawing sheet

Reference: ISO 128-30 (multi-view drawings); Bertoline-Wiebe 5e §10;
           ASME Y14.3-2012 third-angle projection.

LLM tools registered (kerf_chat gated)
---------------------------------------
  drawing_auto_views  — generate 6-view + iso drawing from body/mesh

Never raises — all public functions catch exceptions internally.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Optional B-rep make2d primitives
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.geom.make2d import (  # type: ignore[import]
        Make2DInput,
        ViewParams,
        make2d,
        standard_views,
        brep_to_make2d_input,
        _build_view_matrix,
        _project_vertices,
        _compute_face_normals,
        _build_edge_face_map,
        _extract_silhouette_edges,
        _extract_feature_edges,
        _classify_segment_visibility,
    )
    _MAKE2D_AVAILABLE = True
except Exception:
    _MAKE2D_AVAILABLE = False

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Curve2D = List[List[float]]  # list of [x, y] points — a polyline segment

# ---------------------------------------------------------------------------
# Sheet geometry constants (ISO 216)
# ---------------------------------------------------------------------------

_SHEET_SIZES: Dict[str, Tuple[float, float]] = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "A4": (297.0, 210.0),
    "LETTER": (279.4, 215.9),
}
_DEFAULT_SHEET = "A3"
_MARGIN_MM = 10.0
_TITLE_BLOCK_HEIGHT_MM = 20.0

# ---------------------------------------------------------------------------
# Six standard view directions (Bertoline-Wiebe 5e §10 / ISO 128-30)
# ---------------------------------------------------------------------------
# Convention: coordinate frame is right-hand, Z up.
#   front: looking toward -Y
#   back:  looking toward +Y
#   top:   looking toward -Z
#   bottom:looking toward +Z
#   right: looking toward +X
#   left:  looking toward -X
# For each view we also specify the "up" vector in the view plane (the
# world direction that maps to 2-D "upward" on the drawing sheet).

_VIEW_DIRECTIONS: Dict[str, Tuple[List[float], List[float]]] = {
    # name: (direction, up)
    "front":  ([0.0, -1.0, 0.0], [0.0, 0.0, 1.0]),
    "back":   ([0.0,  1.0, 0.0], [0.0, 0.0, 1.0]),
    "top":    ([0.0,  0.0, -1.0], [0.0, 1.0, 0.0]),
    "bottom": ([0.0,  0.0,  1.0], [0.0, -1.0, 0.0]),
    "right":  ([1.0,  0.0, 0.0], [0.0, 0.0, 1.0]),
    "left":   ([-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]),
}

# Isometric: Bertoline-Wiebe Fig 10-38; azimuth 30° from horizontal,
# elevation 35.264° (= arctan(1/√2)) which gives cube diagonals all equal.
# Standard isometric view direction in right-hand Z-up: looking from
# (1, 1, 1) normalised.  Under orthographic projection from this direction
# the three cube axes X/Y/Z project to 2-D vectors that are exactly 120°
# apart — the defining property of a standard isometric (ISO 5456-3).
_ISO_DIR = np.array([1.0, 1.0, 1.0], dtype=float)
_ISO_DIR /= np.linalg.norm(_ISO_DIR)

_VIEW_LABELS: Dict[str, str] = {
    "front":  "FRONT",
    "back":   "BACK",
    "top":    "TOP",
    "bottom": "BOTTOM",
    "right":  "RIGHT",
    "left":   "LEFT",
    "iso":    "ISO",
}

# ---------------------------------------------------------------------------
# Third-angle projection layout (ANSI/ASME Y14.3-2012, Bertoline-Wiebe 5e §10)
# ---------------------------------------------------------------------------
# Grid positions in (col, row) with origin at top-left, front at (1,1).
# Sheet is divided into a 4-column × 3-row grid:
#   col 0 = left view zone, col 1 = front/top/bottom zone,
#   col 2 = right view zone, col 3 = back/iso zone
#   row 0 = top view zone, row 1 = main row, row 2 = bottom view zone

_THIRD_ANGLE_GRID: Dict[str, Tuple[int, int]] = {
    "top":    (1, 0),
    "left":   (0, 1),
    "front":  (1, 1),
    "right":  (2, 1),
    "back":   (3, 1),
    "bottom": (1, 2),
    "iso":    (3, 0),  # upper-right zone
}
_GRID_COLS = 4
_GRID_ROWS = 3

# First-angle layout (ISO/DIN — left/right/back/iso positions mirrored):
# front stays at (1,1); right goes LEFT, left goes RIGHT, back reverses.
_FIRST_ANGLE_GRID: Dict[str, Tuple[int, int]] = {
    "top":    (1, 2),  # top goes below in first-angle
    "left":   (2, 1),  # left projects to the right of front in first-angle
    "front":  (1, 1),
    "right":  (0, 1),  # right projects to the left of front
    "back":   (3, 1),
    "bottom": (1, 0),  # bottom goes above
    "iso":    (3, 0),
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ProjectionView:
    """Result of projecting a body onto one view plane.

    Attributes
    ----------
    name : str
        View name, e.g. 'front', 'top', 'iso'.
    label : str
        Human-readable label for the drawing sheet.
    visible : list[Curve2D]
        2-D polylines for visible (solid) edges in this view.
    hidden : list[Curve2D]
        2-D polylines for hidden (dashed) edges in this view.
    bbox_2d : dict
        Tight bounding box of the projected geometry:
        {'xmin', 'xmax', 'ymin', 'ymax', 'width', 'height'}.
    view_direction : list[float]
        The 3-D unit direction vector [dx, dy, dz].
    layout_cell : dict
        Sheet cell for this view: {'x', 'y', 'w', 'h'} in mm.
    silhouette_count : int
        Number of silhouette edges before classification.
    """
    name: str = ""
    label: str = ""
    visible: List[Curve2D] = field(default_factory=list)
    hidden: List[Curve2D] = field(default_factory=list)
    bbox_2d: Dict[str, float] = field(default_factory=dict)
    view_direction: List[float] = field(default_factory=list)
    layout_cell: Dict[str, float] = field(default_factory=dict)
    silhouette_count: int = 0


@dataclass
class ViewSheet:
    """Complete multi-view drawing sheet.

    Attributes
    ----------
    views : dict[str, ProjectionView]
        Keyed by view name.
    layout : dict[str, dict]
        Cell layout keyed by view name.
    sheet_size : str
        Sheet size code (e.g. 'A3').
    sheet_width_mm : float
    sheet_height_mm : float
    projection_type : str
        'third_angle' or 'first_angle'.
    include_iso : bool
    scale : float
        Uniform drawing scale applied.
    drawing_id : str
        UUID for this sheet.
    border : list[list[float]]
        Outer sheet border polyline [[x,y], ...].
    title_block : list[list[float]]
        Title-block border polyline.
    projection_symbol : dict
        ISO 128-30 symbol fields for the projection angle.
    ok : bool
    reason : str
        Non-empty string if ok=False.
    """
    views: Dict[str, ProjectionView] = field(default_factory=dict)
    layout: Dict[str, Dict[str, float]] = field(default_factory=dict)
    sheet_size: str = "A3"
    sheet_width_mm: float = 420.0
    sheet_height_mm: float = 297.0
    projection_type: str = "third_angle"
    include_iso: bool = True
    scale: float = 1.0
    drawing_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    border: List[List[float]] = field(default_factory=list)
    title_block: List[List[float]] = field(default_factory=list)
    projection_symbol: Dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (suitable for JSON / LLM tool output)."""
        return {
            "ok": self.ok,
            "reason": self.reason,
            "sheet_size": self.sheet_size,
            "sheet_width_mm": self.sheet_width_mm,
            "sheet_height_mm": self.sheet_height_mm,
            "projection_type": self.projection_type,
            "include_iso": self.include_iso,
            "scale": self.scale,
            "drawing_id": self.drawing_id,
            "border": self.border,
            "title_block": self.title_block,
            "projection_symbol": self.projection_symbol,
            "views": {
                name: {
                    "name": v.name,
                    "label": v.label,
                    "visible": v.visible,
                    "hidden": v.hidden,
                    "bbox_2d": v.bbox_2d,
                    "view_direction": v.view_direction,
                    "layout_cell": v.layout_cell,
                    "silhouette_count": v.silhouette_count,
                }
                for name, v in self.views.items()
            },
        }


# ---------------------------------------------------------------------------
# Internal mesh helpers
# ---------------------------------------------------------------------------

def _mesh_from_body(body: Any) -> "Make2DInput":
    """Convert body (B-rep Body or mesh dict) to Make2DInput.

    Accepts:
    - A B-rep Body with .solids / .shells attributes → brep_to_make2d_input
    - A dict with keys 'vertices' and 'triangles' → direct conversion
    - None / unsupported → unit-cube fallback
    """
    if not _MAKE2D_AVAILABLE:
        # Return a minimal stub so geometry can still be computed without make2d
        return _fallback_cube_mesh_input()

    if body is None:
        return _fallback_cube_mesh_input()

    if isinstance(body, dict):
        try:
            verts = np.array(body["vertices"], dtype=float)
            tris = np.array(body["triangles"], dtype=int)
            return Make2DInput(vertices=verts, triangles=tris)
        except (KeyError, TypeError, ValueError):
            return _fallback_cube_mesh_input()

    # B-rep Body
    if hasattr(body, "solids") or hasattr(body, "shells"):
        try:
            return brep_to_make2d_input(body)
        except Exception:
            pass

    return _fallback_cube_mesh_input()


def _fallback_cube_mesh_input() -> Any:
    """Build a unit-cube Make2DInput without importing make2d."""
    verts = np.array([
        [-0.5, -0.5, -0.5], [0.5, -0.5, -0.5],
        [0.5,  0.5, -0.5], [-0.5,  0.5, -0.5],
        [-0.5, -0.5,  0.5], [0.5, -0.5,  0.5],
        [0.5,  0.5,  0.5], [-0.5,  0.5,  0.5],
    ], dtype=float)
    faces = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ], dtype=int)
    if _MAKE2D_AVAILABLE:
        return Make2DInput(vertices=verts, triangles=faces)
    # When make2d is unavailable return a plain namespace
    class _Stub:
        vertices = verts
        triangles = faces
        feature_edges = None
        crease_angle_deg = 30.0
    return _Stub()


def _compute_body_bbox(mesh_input: Any) -> Dict[str, float]:
    """Return axis-aligned bounding box {'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax',
    'cx', 'cy', 'cz', 'lx', 'ly', 'lz'} of the mesh vertices."""
    v = np.asarray(mesh_input.vertices, dtype=float)
    if v.shape[0] == 0:
        return {k: 0.0 for k in ("xmin","xmax","ymin","ymax","zmin","zmax",
                                  "cx","cy","cz","lx","ly","lz")}
    return {
        "xmin": float(v[:,0].min()), "xmax": float(v[:,0].max()),
        "ymin": float(v[:,1].min()), "ymax": float(v[:,1].max()),
        "zmin": float(v[:,2].min()), "zmax": float(v[:,2].max()),
        "cx": float(v[:,0].mean()), "cy": float(v[:,1].mean()),
        "cz": float(v[:,2].mean()),
        "lx": float(v[:,0].max() - v[:,0].min()),
        "ly": float(v[:,1].max() - v[:,1].min()),
        "lz": float(v[:,2].max() - v[:,2].min()),
    }


# ---------------------------------------------------------------------------
# Sheet layout computation
# ---------------------------------------------------------------------------

def _compute_auto_scale(body_bbox: Dict[str, float], draw_w: float, draw_h: float) -> float:
    """Return the largest standard scale that fits the body in the available area.

    The usable draw area is split into a 4-col × 3-row grid; the front view
    fits in one cell of size (draw_w/4) × (draw_h/3). We scale the largest
    body face to fit that cell with 80% utilisation.
    """
    cell_w = draw_w / _GRID_COLS
    cell_h = draw_h / _GRID_ROWS
    lx = max(body_bbox.get("lx", 1.0), 1e-6)
    ly = max(body_bbox.get("ly", 1.0), 1e-6)
    lz = max(body_bbox.get("lz", 1.0), 1e-6)
    # Front view shows X × Z; top view shows X × Y
    front_scale = min(0.8 * cell_w / lx, 0.8 * cell_h / lz)
    top_scale = min(0.8 * cell_w / lx, 0.8 * cell_h / ly)
    raw = min(front_scale, top_scale)
    # Snap to nearest standard scale (ISO 5455)
    standards = [0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0]
    best = 1.0
    for s in standards:
        if s <= raw:
            best = s
    return max(0.01, min(50.0, best))


def _build_sheet_layout(
    sheet_w: float,
    sheet_h: float,
    margin: float,
    title_h: float,
    grid: Dict[str, Tuple[int, int]],
    include_iso: bool,
) -> Dict[str, Dict[str, float]]:
    """Return {view_name: {x, y, w, h}} for each view in the grid.

    The usable draw area (excluding margins and title block) is divided into
    a uniform _GRID_COLS × _GRID_ROWS grid.
    """
    draw_x0 = margin
    draw_y0 = margin + title_h
    draw_w = sheet_w - 2.0 * margin
    draw_h = sheet_h - 2.0 * margin - title_h
    cell_w = draw_w / _GRID_COLS
    cell_h = draw_h / _GRID_ROWS

    layout: Dict[str, Dict[str, float]] = {}
    for name, (col, row) in grid.items():
        if name == "iso" and not include_iso:
            continue
        layout[name] = {
            "x": draw_x0 + col * cell_w,
            "y": draw_y0 + row * cell_h,
            "w": cell_w,
            "h": cell_h,
        }
    return layout


# ---------------------------------------------------------------------------
# Core projection computation
# ---------------------------------------------------------------------------

def _project_view(
    mesh_input: Any,
    view_dir: List[float],
    view_up: List[float],
    *,
    subdivisions: int = 8,
    tol: float = 1e-9,
) -> Tuple[List[Curve2D], List[Curve2D], int]:
    """Project mesh_input from view_dir and return (visible, hidden, silhouette_count).

    Falls back gracefully when make2d is unavailable.
    """
    if not _MAKE2D_AVAILABLE:
        return [], [], 0

    try:
        vp = ViewParams(direction=view_dir, up=view_up, projection="ortho")
        result = make2d(mesh_input, vp, scale=1.0, subdivisions=subdivisions, tol=tol)
        vis = [[[p[0], p[1]] for p in poly] for poly in result.visible]
        hid = [[[p[0], p[1]] for p in poly] for poly in result.hidden]
        return vis, hid, result.silhouette_count
    except Exception:
        return [], [], 0


def _bbox_of_curves(curves: List[Curve2D]) -> Dict[str, float]:
    """Return tight 2-D bounding box of all curves."""
    all_pts = [pt for curve in curves for pt in curve]
    if not all_pts:
        return {"xmin": 0.0, "xmax": 0.0, "ymin": 0.0, "ymax": 0.0,
                "width": 0.0, "height": 0.0}
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    return {
        "xmin": xmin, "xmax": xmax,
        "ymin": ymin, "ymax": ymax,
        "width": xmax - xmin,
        "height": ymax - ymin,
    }


def _offset_curves(
    curves: List[Curve2D],
    cx: float,
    cy: float,
    scale: float,
) -> List[Curve2D]:
    """Translate + scale a set of 2-D curves to a sheet cell centre."""
    return [[[cx + p[0] * scale, cy + p[1] * scale] for p in curve]
            for curve in curves]


def _projection_symbol(projection_type: str) -> Dict[str, Any]:
    """Return ISO 128-30 §3 projection symbol metadata."""
    if projection_type == "first_angle":
        return {
            "type": "first_angle",
            "iso_code": "E",
            "label": "FIRST ANGLE PROJECTION (ISO E)",
            "standard": "ISO 128-30",
        }
    return {
        "type": "third_angle",
        "iso_code": "A",
        "label": "THIRD ANGLE PROJECTION (ISO A / ASME Y14.3)",
        "standard": "ISO 128-30 / ASME Y14.3-2012",
    }


# ---------------------------------------------------------------------------
# Public API: compute_projection_silhouette
# ---------------------------------------------------------------------------

def compute_projection_silhouette(
    body: Any,
    view_direction: Sequence[float],
) -> List[Curve2D]:
    """Compute the silhouette boundary of ``body`` projected onto the view plane.

    The silhouette is defined per ISO 128-30 §4: the set of edges where the
    surface normal is perpendicular to the view direction (sign change of
    ``dot(normal, view_dir)``), plus all boundary edges of front-facing faces.

    This is the outline you would trace if you drew the outermost contour of
    the body as seen from ``view_direction``.

    Parameters
    ----------
    body :
        A B-rep Body, or a dict with 'vertices' and 'triangles' keys, or None.
    view_direction :
        3-D unit direction vector [dx, dy, dz] the viewer is looking *toward*.

    Returns
    -------
    list[Curve2D]
        Each element is a polyline [[x0,y0], [x1,y1]] representing one
        silhouette edge projected into the 2-D view plane.  Empty list if
        computation fails.

    Never raises.
    """
    try:
        return _compute_projection_silhouette_inner(body, view_direction)
    except Exception:
        return []


def _compute_projection_silhouette_inner(
    body: Any,
    view_direction: Sequence[float],
) -> List[Curve2D]:
    if not _MAKE2D_AVAILABLE:
        return []

    mesh_input = _mesh_from_body(body)
    vdir = np.asarray(view_direction, dtype=float).ravel()[:3]
    nrm = np.linalg.norm(vdir)
    if nrm < 1e-9:
        return []
    vdir /= nrm

    # Choose a reasonable up vector
    up = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(vdir, up)) > 0.9:
        up = np.array([0.0, 1.0, 0.0])

    vp = ViewParams(direction=vdir.tolist(), up=up.tolist(), projection="ortho")
    view_mat = _build_view_matrix(vp)
    centroid = mesh_input.vertices.mean(axis=0)
    verts_c = mesh_input.vertices - centroid
    proj_verts, _ = _project_vertices(verts_c, view_mat, vp)
    face_normals = _compute_face_normals(verts_c, mesh_input.triangles)
    ef_map = _build_edge_face_map(mesh_input.triangles)
    silhouettes = _extract_silhouette_edges(mesh_input, face_normals, ef_map, vdir)

    segments: List[Curve2D] = []
    for (i0, i1) in silhouettes:
        uv_a = proj_verts[i0]
        uv_b = proj_verts[i1]
        segments.append([
            [float(uv_a[0]), float(uv_a[1])],
            [float(uv_b[0]), float(uv_b[1])],
        ])
    return segments


# ---------------------------------------------------------------------------
# Public API: hidden_line_removal
# ---------------------------------------------------------------------------

def hidden_line_removal(
    body: Any,
    view_direction: Sequence[float],
    projection_resolution: float = 0.01,
) -> Tuple[List[Curve2D], List[Curve2D]]:
    """Classify all projected edges of ``body`` as visible or hidden.

    Algorithm (Bertoline-Wiebe 5e §10; adapted from make2d.py):
    1. Tessellate body (or use provided mesh).
    2. Project all vertices to 2-D via orthographic projection along
       ``view_direction``.
    3. For each feature/silhouette edge: sample ``subdivisions`` evenly-spaced
       points along the projected segment.  At each sample, test if any other
       mesh triangle lies between the point and the viewer (depth test via
       barycentric interpolation).
    4. Edge is hidden if the majority of samples are occluded.

    Parameters
    ----------
    body :
        B-rep Body, mesh dict, or None.
    view_direction :
        3-D view direction vector.
    projection_resolution :
        Controls sample density: ``subdivisions = max(4, int(1/projection_resolution))``.
        Default 0.01 → 100 samples per edge (accurate but slower for complex meshes).

    Returns
    -------
    (visible_edges, hidden_edges)
        Each is a list of Curve2D (2-point polylines [[x0,y0],[x1,y1]]).

    Never raises.
    """
    try:
        return _hidden_line_removal_inner(body, view_direction, projection_resolution)
    except Exception:
        return [], []


def _hidden_line_removal_inner(
    body: Any,
    view_direction: Sequence[float],
    projection_resolution: float,
) -> Tuple[List[Curve2D], List[Curve2D]]:
    if not _MAKE2D_AVAILABLE:
        return [], []

    mesh_input = _mesh_from_body(body)
    vdir = np.asarray(view_direction, dtype=float).ravel()[:3]
    nrm = np.linalg.norm(vdir)
    if nrm < 1e-9:
        return [], []
    vdir /= nrm

    up = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(vdir, up)) > 0.9:
        up = np.array([0.0, 1.0, 0.0])

    subdivisions = max(4, int(round(1.0 / max(projection_resolution, 1e-6))))

    vp = ViewParams(direction=vdir.tolist(), up=up.tolist(), projection="ortho")
    view_mat = _build_view_matrix(vp)
    centroid = mesh_input.vertices.mean(axis=0)
    verts_c = mesh_input.vertices - centroid
    proj_verts, vert_depths = _project_vertices(verts_c, view_mat, vp)
    face_normals = _compute_face_normals(verts_c, mesh_input.triangles)
    ef_map = _build_edge_face_map(mesh_input.triangles)

    silhouettes = _extract_silhouette_edges(mesh_input, face_normals, ef_map, vdir)
    feature_edges = _extract_feature_edges(mesh_input, face_normals, ef_map)

    # Merge (deduplicate)
    all_edges: Dict[Tuple[int, int], bool] = {}
    for e in silhouettes:
        all_edges[e] = True
    for e in feature_edges:
        if e not in all_edges:
            all_edges[e] = False

    face_depths = np.array([
        max(vert_depths[t[0]], vert_depths[t[1]], vert_depths[t[2]])
        for t in mesh_input.triangles
    ])

    _TOL = 1e-9
    visible: List[Curve2D] = []
    hidden: List[Curve2D] = []

    for (i0, i1) in all_edges:
        uv_a = proj_verts[i0]
        uv_b = proj_verts[i1]
        da = vert_depths[i0]
        db = vert_depths[i1]
        if np.linalg.norm(uv_b - uv_a) < _TOL:
            continue

        owner_faces = frozenset(ef_map.get((min(i0, i1), max(i0, i1)), []))
        is_vis = _classify_segment_visibility(
            uv_a, da, uv_b, db,
            proj_verts, vert_depths,
            mesh_input.triangles, face_depths,
            owner_faces, subdivisions, _TOL,
        )
        seg: Curve2D = [
            [float(uv_a[0]), float(uv_a[1])],
            [float(uv_b[0]), float(uv_b[1])],
        ]
        if is_vis:
            visible.append(seg)
        else:
            hidden.append(seg)

    return visible, hidden


# ---------------------------------------------------------------------------
# Public API: generate_six_view_drawing
# ---------------------------------------------------------------------------

def generate_six_view_drawing(
    body: Any,
    projection_type: str = "third_angle",
    include_iso: bool = True,
    sheet: str = "A3",
    scale: Optional[float] = None,
) -> ViewSheet:
    """Generate a 6-view orthographic + optional isometric drawing of ``body``.

    Produces front, back, top, bottom, left, right orthographic views and
    (optionally) one isometric view, laid out on a standard drawing sheet.
    Hidden-line removal is performed per ISO 128-20 (using make2d primitives).

    Parameters
    ----------
    body :
        A B-rep ``Body`` instance, a mesh dict {'vertices': [...], 'triangles': [...]},
        or ``None`` (falls back to a unit-cube placeholder).
    projection_type : str
        ``'third_angle'`` (default, ANSI/ASME Y14.3-2012, common in US/UK/AU) or
        ``'first_angle'`` (ISO/DIN, common in continental Europe).
        Third-angle: fold-away convention — top view above front, right view to right.
        First-angle: fold-into convention — top view below front, right view to left.
    include_iso : bool
        If True (default), include an isometric view in the upper-right zone.
        The isometric direction is 30°/30°/30° per Bertoline-Wiebe 5e Fig 10-38
        (standard isometric: equal foreshortening on all three axes).
    sheet : str
        Sheet size: 'A0'..'A4', 'LETTER'.  Default 'A3'.
    scale : float, optional
        Manual drawing scale (e.g. 0.5 = 1:2).  Auto-computed from body bbox
        if None.

    Returns
    -------
    ViewSheet
        Contains all six (or seven) ProjectionView objects plus layout and
        sheet metadata.  Always returns a ViewSheet; on internal error sets
        ``ok=False`` and ``reason``.

    Never raises.
    """
    try:
        return _generate_six_view_inner(body, projection_type, include_iso, sheet, scale)
    except Exception as exc:
        vs = ViewSheet()
        vs.ok = False
        vs.reason = str(exc)
        return vs


def _generate_six_view_inner(
    body: Any,
    projection_type: str,
    include_iso: bool,
    sheet: str,
    scale: Optional[float],
) -> ViewSheet:
    projection_type = projection_type.lower().replace("-", "_").replace(" ", "_")
    if projection_type not in ("third_angle", "first_angle"):
        raise ValueError(
            f"projection_type must be 'third_angle' or 'first_angle'; "
            f"got {projection_type!r}"
        )

    sheet_upper = sheet.upper()
    if sheet_upper not in _SHEET_SIZES:
        raise ValueError(
            f"Unknown sheet size {sheet!r}.  Valid: {sorted(_SHEET_SIZES.keys())}"
        )

    sw, sh = _SHEET_SIZES[sheet_upper]
    margin = _MARGIN_MM
    tb_h = _TITLE_BLOCK_HEIGHT_MM

    # Tessellate body
    mesh_input = _mesh_from_body(body)
    body_bbox = _compute_body_bbox(mesh_input)

    # Auto-scale or validate provided scale
    draw_w = sw - 2.0 * margin
    draw_h = sh - 2.0 * margin - tb_h
    if scale is None:
        scale = _compute_auto_scale(body_bbox, draw_w, draw_h)
    else:
        scale = max(0.001, float(scale))

    # Grid layout
    grid = _THIRD_ANGLE_GRID if projection_type == "third_angle" else _FIRST_ANGLE_GRID
    layout = _build_sheet_layout(sw, sh, margin, tb_h, grid, include_iso)

    # Project each view
    views: Dict[str, ProjectionView] = {}

    all_view_names = list(_VIEW_DIRECTIONS.keys())
    if include_iso:
        all_view_names.append("iso")

    for vname in all_view_names:
        if vname not in layout:
            continue  # iso excluded

        if vname == "iso":
            vdir = _ISO_DIR.tolist()
            vup = [0.0, 0.0, 1.0]
        else:
            vdir, vup = _VIEW_DIRECTIONS[vname]

        vis_raw, hid_raw, sil_count = _project_view(
            mesh_input, vdir, vup, subdivisions=8
        )

        all_curves = vis_raw + hid_raw
        bbox_2d = _bbox_of_curves(all_curves)

        # Centre in the sheet cell
        cell = layout[vname]
        cell_cx = cell["x"] + cell["w"] / 2.0
        cell_cy = cell["y"] + cell["h"] / 2.0

        vis_placed = _offset_curves(vis_raw, cell_cx, cell_cy, scale)
        hid_placed = _offset_curves(hid_raw, cell_cx, cell_cy, scale)

        views[vname] = ProjectionView(
            name=vname,
            label=_VIEW_LABELS.get(vname, vname.upper()),
            visible=vis_placed,
            hidden=hid_placed,
            bbox_2d=bbox_2d,
            view_direction=list(vdir) if isinstance(vdir, list) else vdir.tolist(),
            layout_cell=dict(cell),
            silhouette_count=sil_count,
        )

    # Sheet border + title block border
    border = [
        [margin, margin],
        [sw - margin, margin],
        [sw - margin, sh - margin],
        [margin, sh - margin],
        [margin, margin],
    ]
    tb_border = [
        [margin, margin],
        [sw - margin, margin],
        [sw - margin, margin + tb_h],
        [margin, margin + tb_h],
        [margin, margin],
    ]

    return ViewSheet(
        views=views,
        layout=layout,
        sheet_size=sheet_upper,
        sheet_width_mm=sw,
        sheet_height_mm=sh,
        projection_type=projection_type,
        include_iso=include_iso,
        scale=scale,
        border=border,
        title_block=tb_border,
        projection_symbol=_projection_symbol(projection_type),
        ok=True,
        reason="",
    )


# ---------------------------------------------------------------------------
# LLM tool registration (kerf_chat gated)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _auto_views_spec = ToolSpec(
        name="drawing_auto_views",
        description=(
            "Generate a 6-view orthographic + isometric drawing from a B-rep body\n"
            "or tessellated mesh — per ISO 128-30 / Bertoline-Wiebe 5e §10.\n"
            "\n"
            "Produces: front, back, top, bottom, left, right orthographic views\n"
            "and (optionally) one isometric view, with hidden-line removal.\n"
            "Supports third-angle (ANSI/ASME) and first-angle (ISO/DIN) layouts.\n"
            "\n"
            "Returns:\n"
            "  ok               : bool\n"
            "  views            : per-view visible/hidden polylines + bbox + cell\n"
            "  sheet_size       : str (e.g. 'A3')\n"
            "  projection_type  : 'third_angle' | 'first_angle'\n"
            "  scale            : float\n"
            "  drawing_id       : uuid string\n"
            "  projection_symbol: ISO 128-30 symbol metadata\n"
            "  border / title_block: sheet border polylines\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mesh": {
                    "type": "object",
                    "description": (
                        "Tessellated mesh: {'vertices': [[x,y,z],...], "
                        "'triangles': [[i,j,k],...]}. "
                        "Omit to get a unit-cube placeholder."
                    ),
                },
                "projection_type": {
                    "type": "string",
                    "enum": ["third_angle", "first_angle"],
                    "description": (
                        "Projection convention: 'third_angle' (ANSI/ASME Y14.3, "
                        "default) or 'first_angle' (ISO/DIN)."
                    ),
                },
                "include_iso": {
                    "type": "boolean",
                    "description": "Include isometric view (default true).",
                },
                "sheet": {
                    "type": "string",
                    "enum": ["A0", "A1", "A2", "A3", "A4", "LETTER"],
                    "description": "Sheet size (default 'A3').",
                },
                "scale": {
                    "type": "number",
                    "description": (
                        "Drawing scale (e.g. 0.5 = 1:2).  "
                        "Auto-computed from body size if omitted."
                    ),
                },
            },
            "required": [],
        },
    )

    @register(_auto_views_spec)
    async def run_drawing_auto_views(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        mesh = a.get("mesh")  # optional — None → unit cube fallback
        projection_type = str(a.get("projection_type", "third_angle"))
        include_iso = bool(a.get("include_iso", True))
        sheet = str(a.get("sheet", "A3"))
        scale_raw = a.get("scale")
        scale = float(scale_raw) if scale_raw is not None else None

        if projection_type not in ("third_angle", "first_angle"):
            return err_payload(
                f"projection_type must be 'third_angle' or 'first_angle'; "
                f"got {projection_type!r}",
                "BAD_ARGS",
            )
        if scale is not None and scale <= 0:
            return err_payload(f"scale must be positive; got {scale}", "BAD_ARGS")

        result = generate_six_view_drawing(
            body=mesh,
            projection_type=projection_type,
            include_iso=include_iso,
            sheet=sheet,
            scale=scale,
        )

        if not result.ok:
            return err_payload(result.reason or "unknown error", "OP_FAILED")

        return ok_payload(result.to_dict())
