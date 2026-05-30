"""
section_multi_plane.py
======================
Multi-plane section views — cut a body with multiple parallel or perpendicular
planes for serial views (ISO 128-30 §6; Bertoline 5e §11).

Builds on ``section_contour.section_by_plane`` (Wave 4W single-plane cut)
and extends it to:

  * Multiple parallel cuts — serial sections for surgical planning / terrain /
    industrial slicing.
  * Multiple perpendicular cuts — corner-detail views.
  * Arbitrary plane lists — offset sections (Bertoline §11).
  * 2-D drawing layout — pack cross-sections into a grid or linear strip per
    the Bertoline multi-section drawing convention.

Public API
----------
cut_body_with_planes(body, planes, mode='parallel'|'perpendicular'|'arbitrary')
    -> MultiPlaneSectionResult

    For each plane apply ``section_by_plane`` and collect the results.
    The *mode* tag is informational (affects no geometry, used by callers
    and drawing renderers).

    Returns a :class:`MultiPlaneSectionResult` with:
      per_plane_sections       -- list[SectionResult], one per plane
      combined_cross_sections_2d  -- flat list of all 2-D loop sets
      visible_body_parts       -- list[dict], one per plane (side classification)

generate_serial_sections(body, axis_direction, n_sections=5) -> list[SectionResult]

    Evenly-spaced parallel sections perpendicular to *axis_direction*.
    The spacing spans the body's bounding-box projection along the axis.

generate_corner_detail_sections(body, corner_point, axis_pairs=3)
    -> list[SectionResult]

    3 perpendicular planes at *corner_point* aligned with the world XYZ axes
    (or a provided ``axis_pairs`` list of 3 orthonormal axes).

combine_section_views_for_drawing(multi_section_result, layout='grid'|'linear')
    -> DrawingLayout

    Pack the 2-D cross-section loops into a :class:`DrawingLayout` following
    the Bertoline multi-section drawing convention (grid fills left-to-right
    top-to-bottom; linear places sections side by side along a single row).

Data classes
------------
SectionResult        -- single-plane result (loops_3d, plane_normal, plane_d,
                        plane_point, ok, reason)
MultiPlaneSectionResult  -- aggregated multi-plane result
DrawingLayout        -- 2-D layout descriptor for drawing renderers

LLM tools registered (gated)
-----------------------------
  brep_multi_plane_section   -- arbitrary list of planes → MultiPlaneSectionResult
  brep_serial_sections       -- axis + n → list[SectionResult]

All failures are returned as ``{"ok": False, "reason": "..."}``; never raises.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from kerf_cad_core.geom.section_contour import section_by_plane, _parse_plane

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

Point3 = List[float]
Polyline = List[Point3]


def _unit(v: np.ndarray) -> np.ndarray:
    nrm = float(np.linalg.norm(v))
    if nrm < 1e-15:
        raise ValueError("zero-length vector")
    return v / nrm


def _perp(axis: np.ndarray) -> np.ndarray:
    """Return a vector perpendicular to *axis* (any orientation)."""
    axis = _unit(axis)
    cand = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(cand, axis))) > 0.9:
        cand = np.array([1.0, 0.0, 0.0])
    return _unit(np.cross(axis, cand))


def _bounding_box_projections(body: Any, axis: np.ndarray) -> Tuple[float, float]:
    """Return (min_proj, max_proj) of the body's vertices along *axis*.

    Accepts:
      (verts, faces) tuple/list
      dict with 'verts' or 'vertices' key
    """
    verts = _extract_verts(body)
    if not verts:
        return 0.0, 1.0
    projs = [float(np.dot(axis, np.asarray(v, dtype=float)[:3])) for v in verts]
    return min(projs), max(projs)


def _extract_verts(body: Any) -> List[Point3]:
    """Extract vertex list from various body representations."""
    if isinstance(body, (list, tuple)) and len(body) == 2:
        return [list(v)[:3] for v in body[0]]
    if isinstance(body, dict):
        for key in ("verts", "vertices"):
            if key in body:
                return [list(v)[:3] for v in body[key]]
    return []


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SectionResult:
    """Result of a single-plane section cut.

    Attributes
    ----------
    plane_normal : list[float]
        Unit normal of the cutting plane [nx, ny, nz].
    plane_d : float
        Signed distance from origin: the plane satisfies n·x = d.
    plane_point : list[float]
        A representative point on the plane [px, py, pz].
    loops_3d : list[list[list[float]]]
        Ordered polyline loops in 3-D space (each loop is a list of [x,y,z]).
    ok : bool
        True if the section was computed successfully.
    reason : str
        Error description when ok=False; empty string otherwise.
    plane_index : int
        Index of this plane in the original planes list (0-based).
    """

    plane_normal: List[float]
    plane_d: float
    plane_point: List[float]
    loops_3d: List[Polyline]
    ok: bool = True
    reason: str = ""
    plane_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plane_index": self.plane_index,
            "plane_normal": self.plane_normal,
            "plane_d": self.plane_d,
            "plane_point": self.plane_point,
            "loop_count": len(self.loops_3d),
            "loops_3d": self.loops_3d,
            "ok": self.ok,
            "reason": self.reason,
        }


@dataclass
class MultiPlaneSectionResult:
    """Aggregated result from cutting a body with multiple planes.

    Attributes
    ----------
    per_plane_sections : list[SectionResult]
        One entry per input plane, in order.
    combined_cross_sections_2d : list[list[Polyline]]
        All 2-D loop sets stacked: ``combined_cross_sections_2d[i]`` are the
        loops from ``per_plane_sections[i]``.  (Alias kept 2-D for drawing
        renderers that want just the loops without the full SectionResult.)
    visible_body_parts : list[dict]
        Per-plane side classification dict with keys:
          plane_index, pos_face_count, neg_face_count, plane_normal, plane_d.
        Populated from a lightweight centroid classifier when the body
        exposes face geometry; otherwise empty dicts.
    mode : str
        'parallel', 'perpendicular', or 'arbitrary'.
    ok : bool
        True if at least one section succeeded.
    """

    per_plane_sections: List[SectionResult]
    combined_cross_sections_2d: List[List[Polyline]]
    visible_body_parts: List[Dict[str, Any]]
    mode: str = "arbitrary"
    ok: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "section_count": len(self.per_plane_sections),
            "per_plane_sections": [s.to_dict() for s in self.per_plane_sections],
            "visible_body_parts": self.visible_body_parts,
        }


@dataclass
class DrawingEntry:
    """One cell in a drawing layout.

    Attributes
    ----------
    section_index : int
    loops_3d : list[Polyline]
    plane_normal : list[float]
    plane_d : float
    row : int
    col : int
    offset_x : float   (notional 2-D placement, in body units)
    offset_y : float
    """

    section_index: int
    loops_3d: List[Polyline]
    plane_normal: List[float]
    plane_d: float
    row: int
    col: int
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass
class DrawingLayout:
    """2-D layout of multi-section views per Bertoline drawing convention.

    Attributes
    ----------
    entries : list[DrawingEntry]
        Each entry represents one section view with its grid position and
        notional 2-D placement offset.
    layout_type : str
        'grid' or 'linear'.
    num_rows : int
    num_cols : int
    total_width : float   (sum of column widths, in body units)
    total_height : float  (sum of row heights, in body units)
    """

    entries: List[DrawingEntry] = field(default_factory=list)
    layout_type: str = "grid"
    num_rows: int = 1
    num_cols: int = 1
    total_width: float = 0.0
    total_height: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layout_type": self.layout_type,
            "num_rows": self.num_rows,
            "num_cols": self.num_cols,
            "total_width": self.total_width,
            "total_height": self.total_height,
            "entry_count": len(self.entries),
            "entries": [
                {
                    "section_index": e.section_index,
                    "row": e.row,
                    "col": e.col,
                    "offset_x": e.offset_x,
                    "offset_y": e.offset_y,
                    "plane_normal": e.plane_normal,
                    "plane_d": e.plane_d,
                    "loop_count": len(e.loops_3d),
                }
                for e in self.entries
            ],
        }


# ---------------------------------------------------------------------------
# Internal: classify faces per side (lightweight, centroid-based)
# ---------------------------------------------------------------------------


def _classify_body_sides(
    body: Any,
    plane_normal: np.ndarray,
    plane_d: float,
) -> Dict[str, Any]:
    """Return a lightweight side-classification dict for one plane.

    Uses centroid signed-distance; does not require a full BRep Body.
    For (verts, faces) meshes it classifies faces; for plain vert lists
    it just counts vertices on each side.
    """
    result: Dict[str, Any] = {
        "pos_face_count": 0,
        "neg_face_count": 0,
        "on_face_count": 0,
        "plane_normal": plane_normal.tolist(),
        "plane_d": float(plane_d),
    }

    tol = 1e-7

    if isinstance(body, (list, tuple)) and len(body) == 2:
        verts_raw, faces_raw = body[0], body[1]
        verts = [np.asarray(v, dtype=float)[:3] for v in verts_raw]
        for face in faces_raw:
            if len(face) < 3:
                continue
            i, j, k = int(face[0]), int(face[1]), int(face[2])
            if i >= len(verts) or j >= len(verts) or k >= len(verts):
                continue
            centroid = (verts[i] + verts[j] + verts[k]) / 3.0
            d = float(np.dot(plane_normal, centroid)) - plane_d
            if d > tol:
                result["pos_face_count"] += 1
            elif d < -tol:
                result["neg_face_count"] += 1
            else:
                result["on_face_count"] += 1
        return result

    # dict-based body
    if isinstance(body, dict):
        for key in ("verts", "vertices"):
            if key in body:
                verts = [np.asarray(v, dtype=float)[:3] for v in body[key]]
                faces_raw = body.get("faces", body.get("triangles", []))
                for face in faces_raw:
                    if len(face) < 3:
                        continue
                    i, j, k = int(face[0]), int(face[1]), int(face[2])
                    if i >= len(verts) or j >= len(verts) or k >= len(verts):
                        continue
                    centroid = (verts[i] + verts[j] + verts[k]) / 3.0
                    d = float(np.dot(plane_normal, centroid)) - plane_d
                    if d > tol:
                        result["pos_face_count"] += 1
                    elif d < -tol:
                        result["neg_face_count"] += 1
                    else:
                        result["on_face_count"] += 1
                return result

    return result


# ---------------------------------------------------------------------------
# Core: cut_body_with_planes
# ---------------------------------------------------------------------------

_VALID_MODES = frozenset(("parallel", "perpendicular", "arbitrary"))


def cut_body_with_planes(
    body: Any,
    planes: List[Any],
    mode: str = "arbitrary",
) -> MultiPlaneSectionResult:
    """Cut a body with multiple planes and collect the per-plane section results.

    Implements ISO 128-30 §6 multi-section convention.

    Parameters
    ----------
    body :
        Triangle mesh as ``(verts, faces)`` or dict with 'verts'/'faces'.
    planes :
        List of plane specifications; each item is accepted by
        ``section_contour._parse_plane``:
          * dict   ``{"normal": [nx,ny,nz], "d": d}``
          * dict   ``{"normal": [nx,ny,nz], "point": [px,py,pz]}``
          * tuple  ``([nx,ny,nz], d_scalar)``
          * tuple  ``([nx,ny,nz], [px,py,pz])``
    mode :
        Informational tag — ``'parallel'``, ``'perpendicular'``, or
        ``'arbitrary'``.  Does not change the computed geometry; used by
        drawing renderers and downstream tooling.

    Returns
    -------
    MultiPlaneSectionResult
        ``.ok`` is True if at least one section succeeded.
        ``.per_plane_sections[i]`` corresponds to ``planes[i]``.
    """
    if mode not in _VALID_MODES:
        mode = "arbitrary"

    per_plane: List[SectionResult] = []
    combined_2d: List[List[Polyline]] = []
    visible_parts: List[Dict[str, Any]] = []

    for idx, plane_spec in enumerate(planes):
        # Parse plane to (normal, d) for classifier
        try:
            n_arr, d_val = _parse_plane(plane_spec)
        except Exception as exc:
            sr = SectionResult(
                plane_normal=[0.0, 0.0, 1.0],
                plane_d=0.0,
                plane_point=[0.0, 0.0, 0.0],
                loops_3d=[],
                ok=False,
                reason=f"plane parse error: {exc}",
                plane_index=idx,
            )
            per_plane.append(sr)
            combined_2d.append([])
            visible_parts.append({"plane_index": idx})
            continue

        # Run single-plane section
        raw = section_by_plane(body, plane_spec)
        loops: List[Polyline] = raw.get("loops", [])

        plane_pt = (n_arr * d_val).tolist()  # projection of origin onto plane

        sr = SectionResult(
            plane_normal=n_arr.tolist(),
            plane_d=float(d_val),
            plane_point=plane_pt,
            loops_3d=loops,
            ok=bool(raw.get("ok", False)),
            reason=raw.get("reason", ""),
            plane_index=idx,
        )
        per_plane.append(sr)
        combined_2d.append(loops)

        # Side classification
        cls = _classify_body_sides(body, n_arr, d_val)
        cls["plane_index"] = idx
        visible_parts.append(cls)

    overall_ok = any(s.ok for s in per_plane) if per_plane else False

    return MultiPlaneSectionResult(
        per_plane_sections=per_plane,
        combined_cross_sections_2d=combined_2d,
        visible_body_parts=visible_parts,
        mode=mode,
        ok=overall_ok,
    )


# ---------------------------------------------------------------------------
# generate_serial_sections
# ---------------------------------------------------------------------------


def generate_serial_sections(
    body: Any,
    axis_direction: Sequence[float],
    n_sections: int = 5,
) -> List[SectionResult]:
    """Generate *n_sections* evenly-spaced parallel sections perpendicular to
    *axis_direction*.

    The spacing spans the body's bounding-box projection along the axis so
    that each section lies strictly inside the body extent (endpoints excluded).
    This follows the ISO 128-30 §6.3 serial section convention.

    Useful for surgical planning, terrain modelling, manufacturing QC.

    Parameters
    ----------
    body :
        Triangle mesh ``(verts, faces)`` or dict.
    axis_direction :
        Principal axis (need not be unit-length).  Sections are perpendicular
        to this direction.
    n_sections :
        Number of parallel sections to generate (≥ 1).

    Returns
    -------
    list[SectionResult]
        One entry per section, ordered along the axis from min to max.
        ``result[i].plane_d`` increases monotonically.
    """
    n_sections = max(1, int(n_sections))

    try:
        axis = _unit(np.asarray(axis_direction, dtype=float).ravel()[:3])
    except ValueError:
        return [SectionResult(
            plane_normal=[0.0, 0.0, 1.0], plane_d=0.0, plane_point=[0.0, 0.0, 0.0],
            loops_3d=[], ok=False,
            reason="axis_direction must be a non-zero 3-vector",
            plane_index=0,
        )]

    try:
        proj_min, proj_max = _bounding_box_projections(body, axis)
    except Exception as exc:
        return [SectionResult(
            plane_normal=axis.tolist(), plane_d=0.0, plane_point=[0.0, 0.0, 0.0],
            loops_3d=[], ok=False,
            reason=f"bounding box failed: {exc}",
            plane_index=0,
        )]

    if abs(proj_max - proj_min) < 1e-12:
        proj_min -= 0.5
        proj_max += 0.5

    # n+1 intervals → n_sections interior planes
    # e.g. n=5, range [0,10] → planes at 10/6, 20/6, 30/6, 40/6, 50/6
    d_values: List[float] = []
    for i in range(n_sections):
        t = (i + 1) / (n_sections + 1)
        d_values.append(proj_min + t * (proj_max - proj_min))

    planes = [{"normal": axis.tolist(), "d": float(d)} for d in d_values]
    mpr = cut_body_with_planes(body, planes, mode="parallel")
    return mpr.per_plane_sections


# ---------------------------------------------------------------------------
# generate_corner_detail_sections
# ---------------------------------------------------------------------------


def generate_corner_detail_sections(
    body: Any,
    corner_point: Sequence[float],
    axis_pairs: Union[int, List[Sequence[float]]] = 3,
) -> List[SectionResult]:
    """Generate 3 perpendicular section planes at a corner point.

    Implements the Bertoline §11 corner-detail section convention: three
    mutually-perpendicular planes meet at *corner_point* and produce the
    standard front/side/top cross-sections.

    Parameters
    ----------
    body :
        Triangle mesh ``(verts, faces)`` or dict.
    corner_point :
        The shared corner point where all three planes intersect [x, y, z].
    axis_pairs :
        Either the integer 3 (use world XYZ axes) or a list of exactly 3
        mutually-orthogonal unit vectors [[ax,ay,az], ...].

    Returns
    -------
    list[SectionResult]
        Exactly 3 results: planes with normals X, Y, Z (or the supplied axes),
        all passing through *corner_point*.
    """
    corner = np.asarray(corner_point, dtype=float).ravel()[:3]

    # Resolve axes
    if isinstance(axis_pairs, int) or axis_pairs == 3:
        axes = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0]),
        ]
    else:
        raw_axes = list(axis_pairs)
        if len(raw_axes) != 3:
            # Fallback to world XYZ
            axes = [
                np.array([1.0, 0.0, 0.0]),
                np.array([0.0, 1.0, 0.0]),
                np.array([0.0, 0.0, 1.0]),
            ]
        else:
            axes = []
            for ax in raw_axes:
                try:
                    axes.append(_unit(np.asarray(ax, dtype=float).ravel()[:3]))
                except ValueError:
                    axes.append(np.array([0.0, 0.0, 1.0]))

    planes = [
        {"normal": ax.tolist(), "point": corner.tolist()}
        for ax in axes
    ]
    mpr = cut_body_with_planes(body, planes, mode="perpendicular")
    return mpr.per_plane_sections


# ---------------------------------------------------------------------------
# combine_section_views_for_drawing
# ---------------------------------------------------------------------------

# Bertoline 5e §11 grid convention:
#   * linear  — all sections in a single row, left-to-right in axis order
#   * grid    — fill left-to-right, top-to-bottom; prefer roughly square layout
#               cols = ceil(sqrt(n)), rows = ceil(n / cols)
# Spacing between entries = _LAYOUT_PADDING body units.

_LAYOUT_PADDING: float = 2.0  # body units gap between section views


def _loop_extents(loops: List[Polyline]) -> Tuple[float, float, float, float]:
    """Return (min_x, max_x, min_y, max_y) of all loop points projected onto XY."""
    if not loops:
        return 0.0, 1.0, 0.0, 1.0
    xs = []
    ys = []
    for loop in loops:
        for pt in loop:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))
    if not xs:
        return 0.0, 1.0, 0.0, 1.0
    return min(xs), max(xs), min(ys), max(ys)


def combine_section_views_for_drawing(
    multi_section_result: MultiPlaneSectionResult,
    layout: str = "grid",
) -> DrawingLayout:
    """Pack 2-D cross-section loops into a drawing layout.

    Follows the Bertoline 5e §11 multi-section drawing convention:
      * Grid  — fills left-to-right, top-to-bottom with roughly-square aspect.
      * Linear — single row, sections ordered as supplied.

    Section views are arranged using the XY projections of their 3-D loop
    coordinates.  Offsets in the returned :class:`DrawingLayout` represent
    notional 2-D placement in body units.

    Parameters
    ----------
    multi_section_result : MultiPlaneSectionResult
    layout : str
        ``'grid'`` (default) or ``'linear'``.

    Returns
    -------
    DrawingLayout
    """
    sections = multi_section_result.per_plane_sections
    n = len(sections)

    if n == 0:
        return DrawingLayout(entries=[], layout_type=layout, num_rows=0, num_cols=0)

    # Compute per-section extents (XY projection)
    widths: List[float] = []
    heights: List[float] = []
    for sr in sections:
        if sr.loops_3d:
            xmin, xmax, ymin, ymax = _loop_extents(sr.loops_3d)
            widths.append(max(xmax - xmin, 1.0))
            heights.append(max(ymax - ymin, 1.0))
        else:
            widths.append(1.0)
            heights.append(1.0)

    if layout == "linear":
        num_rows = 1
        num_cols = n
    else:
        # Grid: prefer roughly square
        num_cols = max(1, math.ceil(math.sqrt(n)))
        num_rows = max(1, math.ceil(n / num_cols))

    # Build entries with (row, col, offset_x, offset_y)
    entries: List[DrawingEntry] = []
    cur_x = 0.0
    cur_y = 0.0
    col_max_heights: List[float] = [0.0] * num_rows  # per row

    for idx, sr in enumerate(sections):
        row = idx // num_cols
        col = idx % num_cols

        # Compute cumulative x offset for this column across all rows
        # Simple approach: sum widths of preceding columns in same row
        # For simplicity, use uniform column widths (max width in each column)
        entries.append(DrawingEntry(
            section_index=idx,
            loops_3d=sr.loops_3d,
            plane_normal=sr.plane_normal,
            plane_d=sr.plane_d,
            row=row,
            col=col,
            offset_x=0.0,  # filled in below
            offset_y=0.0,  # filled in below
        ))

    # Now compute actual offsets using per-column max widths and per-row max heights
    col_widths = [0.0] * num_cols
    row_heights = [0.0] * num_rows

    for e in entries:
        w = widths[e.section_index]
        h = heights[e.section_index]
        if w > col_widths[e.col]:
            col_widths[e.col] = w
        if h > row_heights[e.row]:
            row_heights[e.row] = h

    # Cumulative offsets
    col_offsets = [0.0]
    for c in range(num_cols - 1):
        col_offsets.append(col_offsets[-1] + col_widths[c] + _LAYOUT_PADDING)

    row_offsets = [0.0]
    for r in range(num_rows - 1):
        row_offsets.append(row_offsets[-1] + row_heights[r] + _LAYOUT_PADDING)

    for e in entries:
        e.offset_x = col_offsets[e.col]
        e.offset_y = row_offsets[e.row]

    total_width = (
        sum(col_widths) + _LAYOUT_PADDING * max(0, num_cols - 1)
    )
    total_height = (
        sum(row_heights) + _LAYOUT_PADDING * max(0, num_rows - 1)
    )

    return DrawingLayout(
        entries=entries,
        layout_type=layout,
        num_rows=num_rows,
        num_cols=num_cols,
        total_width=total_width,
        total_height=total_height,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated, mirrors section_contour.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # brep_multi_plane_section
    # ------------------------------------------------------------------

    _multi_plane_spec = ToolSpec(
        name="brep_multi_plane_section",
        description=(
            "Cut a triangle mesh with multiple planes and return per-plane cross-section loops.\n"
            "\n"
            "Implements ISO 128-30 §6 multi-section convention.  Each plane may be\n"
            "parallel, perpendicular, or at an arbitrary angle to the others.\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  mode            : 'parallel' | 'perpendicular' | 'arbitrary'\n"
            "  section_count   : int\n"
            "  per_plane_sections : list of {\n"
            "    plane_index, plane_normal, plane_d, plane_point,\n"
            "    loop_count, loops_3d, ok, reason\n"
            "  }\n"
            "  visible_body_parts : list of {\n"
            "    plane_index, pos_face_count, neg_face_count, on_face_count,\n"
            "    plane_normal, plane_d\n"
            "  }\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises.\n"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "verts": {
                    "type": "array",
                    "description": "Mesh vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Triangle faces as [[i,j,k], ...] (0-based indices).",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "planes": {
                    "type": "array",
                    "description": (
                        "List of plane specs.  Each item: "
                        "{\"normal\":[nx,ny,nz], \"d\": d} "
                        "or {\"normal\":[nx,ny,nz], \"point\":[px,py,pz]}."
                    ),
                    "items": {"type": "object"},
                },
                "mode": {
                    "type": "string",
                    "enum": ["parallel", "perpendicular", "arbitrary"],
                    "description": "Informational mode tag (default: 'arbitrary').",
                    "default": "arbitrary",
                },
            },
            "required": ["verts", "faces", "planes"],
        },
    )

    @register(_multi_plane_spec)
    async def run_brep_multi_plane_section(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        verts = a.get("verts")
        faces = a.get("faces")
        planes = a.get("planes")
        mode = a.get("mode", "arbitrary")

        if verts is None or faces is None:
            return err_payload("verts and faces are required", "BAD_ARGS")
        if not isinstance(planes, list) or len(planes) == 0:
            return err_payload("planes must be a non-empty list of plane specs", "BAD_ARGS")

        result = cut_body_with_planes((verts, faces), planes, mode=str(mode))
        if not result.ok:
            first_err = next(
                (s.reason for s in result.per_plane_sections if not s.ok), "unknown"
            )
            return err_payload(first_err, "OP_FAILED")
        return ok_payload(result.to_dict())

    # ------------------------------------------------------------------
    # brep_serial_sections
    # ------------------------------------------------------------------

    _serial_spec = ToolSpec(
        name="brep_serial_sections",
        description=(
            "Generate N evenly-spaced parallel sections perpendicular to an axis.\n"
            "\n"
            "ISO 128-30 §6.3 serial sections — useful for surgical planning,\n"
            "terrain modelling, industrial QC.\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  section_count   : int\n"
            "  sections        : list of {\n"
            "    plane_index, plane_normal, plane_d, plane_point,\n"
            "    loop_count, loops_3d, ok, reason\n"
            "  }\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises.\n"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "verts": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "axis_direction": {
                    "type": "array",
                    "description": "Principal axis direction [dx, dy, dz] (need not be unit-length).",
                    "items": {"type": "number"},
                },
                "n_sections": {
                    "type": "integer",
                    "description": "Number of parallel sections to generate (default 5, min 1).",
                    "minimum": 1,
                    "default": 5,
                },
            },
            "required": ["verts", "faces", "axis_direction"],
        },
    )

    @register(_serial_spec)
    async def run_brep_serial_sections(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        verts = a.get("verts")
        faces = a.get("faces")
        axis_dir = a.get("axis_direction")
        n_sections = int(a.get("n_sections", 5))

        if verts is None or faces is None:
            return err_payload("verts and faces are required", "BAD_ARGS")
        if axis_dir is None:
            return err_payload("axis_direction is required", "BAD_ARGS")

        results = generate_serial_sections((verts, faces), axis_dir, n_sections=n_sections)

        ok = any(r.ok for r in results) if results else False
        if not ok:
            first_err = results[0].reason if results else "no sections generated"
            return err_payload(first_err, "OP_FAILED")

        return ok_payload({
            "ok": True,
            "section_count": len(results),
            "sections": [r.to_dict() for r in results],
        })
