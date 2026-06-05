"""
kerf_cad_core.drawings.section_view
=====================================

Section views, detail views, and title-block generation for 2D engineering
drawings — closing the "no full views/sections/details UI" gap.

Section views (ISO 128-30 §9; ASME Y14.3-2012 §5)
---------------------------------------------------
A section view shows the interior of a part by conceptually cutting through
it with an *aligned cutting plane* and removing the near half.  The cut
surfaces are shown with a *hatch pattern* (ANSI 31 = steel, per ASME Y14.2).
The method:

  1. Tessellate the mesh (or use the supplied polylines from a parent HLR view).
  2. Intersect each edge with the cutting half-space: keep only edges that
     lie entirely in the positive half-space (behind the cut plane).
  3. Extract contour loops on the cutting plane itself by clipping the mesh
     triangles (Sutherland-Hodgman polygon clipping algorithm, Sutherland &
     Hodgman 1974 CACM) — these become the hatch boundary.
  4. Generate hatch lines at 45° (ISO 128-50 §3.2), spacing = 3 mm, inside
     the contour boundary.
  5. Project resulting edges + hatch to 2D via the view's projection basis.

Detail views (ISO 128-30 §10; ASME Y14.3-2012 §9)
--------------------------------------------------
A detail view is a magnified extract of a circular region of an existing
orthographic view:

  1. The caller specifies a *centre* and *radius* in view-plane coordinates.
  2. Clip all polylines of the parent view to the circle boundary.
  3. Scale the clipped geometry by *magnification* (default 2×).
  4. Emit a new ProjectionView-like dict + an annotation with the detail
     label (circle + arrow leader + "A" or "B" etc.) for placement on the
     parent view.

Title block (ISO 7200:2004 "Technical product documentation — Title blocks")
---------------------------------------------------------------------------
Generates a structured title-block dict conforming to ISO 7200:2004 §5.
Fields: document number, title, organisation, scale, sheet, revision, date,
drawn-by, approved-by, weight, material.

LLM tools
---------
  drawing_section_view   — cut + hatch a mesh/polyline view along a plane
  drawing_detail_view    — magnify a circular sub-region of a parent view
  drawing_title_block    — produce an ISO 7200:2004 title-block dict

References
----------
* Sutherland, I.E. & Hodgman, G.W. (1974). "Reentrant polygon clipping."
  CACM 17(1):32–42.
* ISO 128-30:2001 — Technical drawings — Projection methods — Views.
* ISO 128-50:2001 — Basic conventions for cuts and sections.
* ISO 7200:2004  — Technical product documentation — Title blocks.
* ASME Y14.3-2012 — Orthographic and Pictorial Views.
* Bertoline, G.R. & Wiebe, E.N. (2004). Fundamentals of Graphics Communication 5e, §§10–11.

Never raises — all public functions catch exceptions internally.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Pt2 = List[float]       # [x, y]
Polyline2 = List[Pt2]  # list of [x, y]

# ---------------------------------------------------------------------------
# ISO 128-50 §3.2 hatch constants
# ---------------------------------------------------------------------------

_HATCH_ANGLE_DEG: float = 45.0          # default ANSI 31 / ISO "general metal"
_HATCH_SPACING_MM: float = 3.0          # 3 mm per ISO 128-50
_HATCH_PATTERN_LABEL: str = "ANSI 31"

# ---------------------------------------------------------------------------
# Cutting-plane helpers (Sutherland-Hodgman polygon clipping)
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _parse_plane_spec(plane: Any) -> Tuple[np.ndarray, float]:
    """Return (normal, d) from a plane specification.

    Accepts:
    - dict with keys 'normal' + ('d' or 'point')
    - list/array [a, b, c, d]  (ax + by + cz + d = 0)
    - str like 'xz@y=25' (axis-aligned at an offset)
    """
    TOL = 1e-12
    if isinstance(plane, str):
        s = plane.strip().lower()
        # e.g. "xz@y=25"  → normal = [0,1,0], d = 25
        axis_map = {
            "yz": np.array([1.0, 0.0, 0.0]),
            "xz": np.array([0.0, 1.0, 0.0]),
            "xy": np.array([0.0, 0.0, 1.0]),
        }
        for key, n in axis_map.items():
            if s.startswith(key):
                rest = s[len(key):]
                offset = 0.0
                if "@" in rest:
                    try:
                        eq = rest.split("@", 1)[1]
                        offset = float(eq.split("=")[-1])
                    except Exception:
                        pass
                return n, -offset  # ax + by + cz + d = 0 → d = -offset*dot(n,n)
        raise ValueError(f"Unrecognised plane string: {plane!r}")

    if isinstance(plane, (list, tuple, np.ndarray)):
        arr = np.asarray(plane, dtype=float).ravel()
        if arr.shape[0] == 4:
            n = arr[:3]
            nn = np.linalg.norm(n)
            if nn < TOL:
                raise ValueError("Plane normal is zero")
            return n / nn, arr[3] / nn
        raise ValueError(f"Plane array must have 4 elements [a,b,c,d]; got {arr.shape}")

    if isinstance(plane, dict):
        n_raw = plane.get("normal", [0.0, 0.0, 1.0])
        n = _unit(np.asarray(n_raw, dtype=float).ravel()[:3])
        if "d" in plane:
            d = float(plane["d"])
        elif "point" in plane:
            pt = np.asarray(plane["point"], dtype=float).ravel()[:3]
            d = -float(np.dot(n, pt))
        else:
            d = 0.0
        return n, d

    raise TypeError(f"Unsupported plane type: {type(plane)}")


def _signed_dist(pt: np.ndarray, normal: np.ndarray, d: float) -> float:
    return float(np.dot(normal, pt)) + d


def _clip_edge_to_halfspace(
    p0: np.ndarray,
    p1: np.ndarray,
    normal: np.ndarray,
    d: float,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Clip segment p0→p1 to the half-space normal·x + d >= 0.

    Returns the clipped segment, or None if entirely outside.
    """
    d0 = _signed_dist(p0, normal, d)
    d1 = _signed_dist(p1, normal, d)

    if d0 >= 0 and d1 >= 0:
        return p0, p1   # fully inside
    if d0 < 0 and d1 < 0:
        return None     # fully outside

    # One end inside, one outside — find intersection
    t = d0 / (d0 - d1)
    pm = p0 + t * (p1 - p0)

    if d0 >= 0:
        return p0, pm   # p0 inside
    else:
        return pm, p1   # p1 inside


def _clip_triangle_to_plane(
    v0: np.ndarray,
    v1: np.ndarray,
    v2: np.ndarray,
    normal: np.ndarray,
    d: float,
) -> List[np.ndarray]:
    """Sutherland-Hodgman: clip a triangle to the plane normal·x + d = 0.

    Returns the polygon vertices ON the plane intersection (0, 1, or 2 points).
    """
    pts = [v0, v1, v2]
    dists = [_signed_dist(p, normal, d) for p in pts]
    intersection: List[np.ndarray] = []

    tol = 1e-9
    for i in range(3):
        j = (i + 1) % 3
        di, dj = dists[i], dists[j]
        # If this vertex is on the plane boundary
        if abs(di) < tol:
            intersection.append(pts[i])
        # If edge crosses the plane (sign change)
        if (di > tol and dj < -tol) or (di < -tol and dj > tol):
            t = di / (di - dj)
            intersection.append(pts[i] + t * (pts[j] - pts[i]))

    return intersection


# ---------------------------------------------------------------------------
# Mesh-based section + hatch
# ---------------------------------------------------------------------------


def _mesh_section_contour(
    vertices: np.ndarray,
    triangles: np.ndarray,
    normal: np.ndarray,
    d: float,
) -> List[Polyline2]:
    """Find the section contour on the cutting plane.

    Projects the plane-triangle intersections into a 2D basis on the cutting
    plane and returns unsorted contour segments.  Uses Sutherland-Hodgman
    (1974).
    """
    # Build 2D basis on the cutting plane
    n = _unit(normal)
    # Choose a perpendicular vector
    up = np.array([0.0, 1.0, 0.0])
    if abs(np.dot(n, up)) > 0.9:
        up = np.array([1.0, 0.0, 0.0])
    right2d = _unit(np.cross(n, up))
    up2d = _unit(np.cross(right2d, n))

    segments: List[Polyline2] = []
    for tri in triangles:
        v0, v1, v2 = vertices[tri[0]], vertices[tri[1]], vertices[tri[2]]
        pts_on_plane = _clip_triangle_to_plane(v0, v1, v2, n, d)
        if len(pts_on_plane) < 2:
            continue
        # Each consecutive pair of intersection points forms a contour segment
        for i in range(0, len(pts_on_plane) - 1, 1):
            a = pts_on_plane[i]
            b = pts_on_plane[i + 1]
            if np.linalg.norm(a - b) < 1e-10:
                continue
            # Project to 2D on the cutting plane
            a2 = [float(np.dot(a, right2d)), float(np.dot(a, up2d))]
            b2 = [float(np.dot(b, right2d)), float(np.dot(b, up2d))]
            segments.append([a2, b2])
    return segments


def _mesh_cut_edges(
    vertices: np.ndarray,
    triangles: np.ndarray,
    normal: np.ndarray,
    d: float,
    view_right: np.ndarray,
    view_up: np.ndarray,
) -> Tuple[List[Polyline2], List[Polyline2]]:
    """Clip all mesh edges to the positive half-space (keep the cut-away side).

    Returns (visible_segments_2d, hatch_boundary_segments_2d).
    """
    from kerf_cad_core.geom.make2d import (  # type: ignore[import]
        _build_edge_face_map,
        _extract_feature_edges,
        _extract_silhouette_edges,
        _compute_face_normals,
    )

    TOL = 1e-10
    face_normals = _compute_face_normals(vertices, triangles)
    ef_map = _build_edge_face_map(triangles)

    feature_edges = _extract_feature_edges(
        _make2d_input(vertices, triangles), face_normals, ef_map
    )
    # view direction (section views look along the plane normal)
    view_dir = normal

    visible: List[Polyline2] = []

    for (i0, i1) in feature_edges:
        p0 = vertices[i0]
        p1 = vertices[i1]
        clipped = _clip_edge_to_halfspace(p0, p1, normal, d)
        if clipped is None:
            continue
        a3, b3 = clipped
        if np.linalg.norm(a3 - b3) < TOL:
            continue
        a2 = [float(np.dot(a3, view_right)), float(np.dot(a3, view_up))]
        b2 = [float(np.dot(b3, view_right)), float(np.dot(b3, view_up))]
        visible.append([a2, b2])

    # Hatch boundary: contour on the cutting plane
    hatch_boundary = _mesh_section_contour(vertices, triangles, normal, d)

    return visible, hatch_boundary


def _make2d_input(vertices: np.ndarray, triangles: np.ndarray) -> Any:
    """Build a Make2DInput (lazy to avoid circular import)."""
    try:
        from kerf_cad_core.geom.make2d import Make2DInput  # type: ignore[import]
        return Make2DInput(vertices=vertices, triangles=triangles)
    except ImportError:
        class _Stub:
            crease_angle_deg = 30.0
            feature_edges = None
        s = _Stub()
        s.vertices = vertices
        s.triangles = triangles
        return s


# ---------------------------------------------------------------------------
# Hatch generation (ISO 128-50 §3.2)
# ---------------------------------------------------------------------------


def _bounding_box_2d(segments: List[Polyline2]) -> Tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) of all 2D points in segments."""
    all_pts = [pt for seg in segments for pt in seg]
    if not all_pts:
        return 0.0, 0.0, 0.0, 0.0
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_polygon_2d(point: Pt2, polygon: List[Pt2]) -> bool:
    """Ray-casting point-in-polygon test."""
    x, y = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def _chain_boundary_segments(segments: List[Polyline2]) -> List[List[Pt2]]:
    """Attempt to chain unordered 2D segments into one or more closed polygons.

    Returns a list of polygon vertex lists (each polygon is a closed loop).
    Falls back to returning each segment's midpoint path if chaining fails,
    which still allows bbox-based hatch generation.
    """
    if not segments:
        return []

    # For hatch we need to convert the edge-soup into a simple scan-line form.
    # Use all segment endpoints to build a comprehensive polygon approximation:
    # Build an ordered polyline by chaining segments greedily.
    tol = 1e-6

    def _pt_key(p: Pt2) -> Tuple[int, int]:
        return (int(round(p[0] / tol)), int(round(p[1] / tol)))

    remaining = list(segments)
    chains: List[List[Pt2]] = []

    while remaining:
        chain = list(remaining.pop(0))  # start new chain
        changed = True
        while changed:
            changed = False
            for i, seg in enumerate(remaining):
                # Try to append seg or reversed seg to chain tail
                tail = chain[-1]
                if _pt_key(seg[0]) == _pt_key(tail):
                    chain.extend(seg[1:])
                    remaining.pop(i)
                    changed = True
                    break
                elif _pt_key(seg[-1]) == _pt_key(tail):
                    chain.extend(reversed(seg[:-1]))
                    remaining.pop(i)
                    changed = True
                    break
        if len(chain) >= 3:
            chains.append(chain)
        elif chain:
            chains.append(chain)

    return chains if chains else []


def _generate_hatch(
    boundary_segments: List[Polyline2],
    angle_deg: float = _HATCH_ANGLE_DEG,
    spacing_mm: float = _HATCH_SPACING_MM,
) -> List[Polyline2]:
    """Generate hatch lines at angle_deg within the boundary polygon.

    Uses a scan-line approach with all boundary segments as an edge soup.
    Each horizontal scan ray intersects boundary edges; paired intersections
    produce hatch segments (ISO 128-50 §3.2).

    Returns list of [[x0,y0],[x1,y1]] segments.
    """
    if not boundary_segments:
        return []

    xmin, ymin, xmax, ymax = _bounding_box_2d(boundary_segments)
    extent = max(xmax - xmin, ymax - ymin)
    if extent < 1e-6:
        return []

    # Rotation angle (rotate coords to make hatch lines horizontal)
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    def _rotate(p: Pt2) -> Pt2:
        return [cos_a * p[0] - sin_a * p[1], sin_a * p[0] + cos_a * p[1]]

    def _rotate_back(p: Pt2) -> Pt2:
        ra = -rad
        c, s = math.cos(ra), math.sin(ra)
        return [c * p[0] - s * p[1], s * p[0] + c * p[1]]

    # Rotate all boundary segment endpoints into the hatch-aligned frame
    # Build a flat list of rotated segments (each is [rot_p0, rot_p1, ...])
    rot_segs: List[List[Pt2]] = []
    for seg in boundary_segments:
        rot_segs.append([_rotate(p) for p in seg])

    # Bounding box in rotated space
    all_rot_pts = [p for seg in rot_segs for p in seg]
    rys = [p[1] for p in all_rot_pts]
    rymin, rymax = min(rys), max(rys)

    hatch: List[Polyline2] = []
    y = rymin + spacing_mm * 0.5  # start half-spacing above bottom
    while y <= rymax + spacing_mm * 0.5:
        # Find intersections of horizontal scan line y with all boundary edges
        intersections: List[float] = []
        for seg in rot_segs:
            for k in range(len(seg) - 1):
                p0, p1 = seg[k], seg[k + 1]
                y0, y1 = p0[1], p1[1]
                x0, x1 = p0[0], p1[0]
                # Standard scanline intersection test
                if (y0 <= y < y1) or (y1 <= y < y0):
                    if abs(y1 - y0) < 1e-15:
                        continue
                    t = (y - y0) / (y1 - y0)
                    xi = x0 + t * (x1 - x0)
                    intersections.append(xi)
        intersections.sort()
        # Pair up intersections to form line segments
        for k in range(0, len(intersections) - 1, 2):
            xa, xb = intersections[k], intersections[k + 1]
            if xb - xa < 1e-6:
                continue
            pa = _rotate_back([xa, y])
            pb = _rotate_back([xb, y])
            hatch.append([pa, pb])
        y += spacing_mm

    return hatch


# ---------------------------------------------------------------------------
# Detail view clipping
# ---------------------------------------------------------------------------


def _clip_polyline_to_circle(
    polyline: Polyline2,
    cx: float,
    cy: float,
    radius: float,
) -> List[Polyline2]:
    """Clip a polyline against a circle.

    Handles all four cases including both-endpoints-outside chord clips.
    Returns a list of sub-polylines that lie within the circle.
    """
    result: List[Polyline2] = []
    if len(polyline) < 2:
        return result

    r2 = radius * radius

    def _inside(p: Pt2) -> bool:
        dx, dy = p[0] - cx, p[1] - cy
        return dx * dx + dy * dy <= r2

    def _intersect_ts(a: Pt2, b: Pt2) -> List[float]:
        """Return sorted list of t values in [0,1] where segment a→b crosses circle."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        fx, fy = a[0] - cx, a[1] - cy
        A = dx * dx + dy * dy
        if A < 1e-20:
            return []
        B = 2.0 * (fx * dx + fy * dy)
        C = fx * fx + fy * fy - r2
        disc = B * B - 4.0 * A * C
        if disc < 0:
            return []
        sqrt_disc = math.sqrt(max(0.0, disc))
        t1 = (-B - sqrt_disc) / (2.0 * A)
        t2 = (-B + sqrt_disc) / (2.0 * A)
        return sorted(t for t in (t1, t2) if 0.0 <= t <= 1.0)

    def _lerp(a: Pt2, b: Pt2, t: float) -> Pt2:
        return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]

    current_seg: List[Pt2] = []
    prev = polyline[0]
    pi = _inside(prev)
    if pi:
        current_seg = [prev]

    for i in range(1, len(polyline)):
        curr = polyline[i]
        ci = _inside(curr)
        ts = _intersect_ts(prev, curr)

        if pi and ci:
            # Both inside: continue current segment
            if not current_seg:
                current_seg = [prev]
            current_seg.append(curr)
        elif pi and not ci:
            # Exiting: find the exit point (first t)
            if not current_seg:
                current_seg = [prev]
            for t in ts:
                current_seg.append(_lerp(prev, curr, t))
                break
            if current_seg:
                result.append(current_seg)
            current_seg = []
        elif not pi and ci:
            # Entering: find entry point (last t in [0,1])
            current_seg = []
            for t in reversed(ts):
                current_seg = [_lerp(prev, curr, t)]
                break
            current_seg.append(curr)
        else:
            # Both outside — may still cross circle as a chord
            if len(ts) >= 2:
                # Entry at ts[0], exit at ts[1]
                entry = _lerp(prev, curr, ts[0])
                exit_ = _lerp(prev, curr, ts[1])
                result.append([entry, exit_])
            # else: truly outside, skip
            current_seg = []

        prev = curr
        pi = ci

    if current_seg and len(current_seg) >= 2:
        result.append(current_seg)

    return result


# ---------------------------------------------------------------------------
# Public API: section_view
# ---------------------------------------------------------------------------


@dataclass
class SectionViewResult:
    """Output of drawing_section_view.

    Attributes
    ----------
    ok : bool
    reason : str
    visible_edges : list[Polyline2]
        Edges from the remaining half of the model, projected to 2D.
    hatch_lines : list[Polyline2]
        ISO 128-50 hatch at 45° on the cut face.
    contour_edges : list[Polyline2]
        Outline of the cut contour on the section plane (boundary of hatch area).
    cutting_plane_marker : dict
        Dict with 'line_start', 'line_end', 'label', 'arrow_dir' for drawing
        the cutting-plane indicator line (A–A, B–B, etc.) on the parent view.
    hatch_angle_deg : float
    hatch_spacing_mm : float
    hatch_pattern : str
    n_visible_edges : int
    n_hatch_lines : int
    n_contour_edges : int
    """
    ok: bool = True
    reason: str = ""
    visible_edges: List[Polyline2] = field(default_factory=list)
    hatch_lines: List[Polyline2] = field(default_factory=list)
    contour_edges: List[Polyline2] = field(default_factory=list)
    cutting_plane_marker: Dict[str, Any] = field(default_factory=dict)
    hatch_angle_deg: float = _HATCH_ANGLE_DEG
    hatch_spacing_mm: float = _HATCH_SPACING_MM
    hatch_pattern: str = _HATCH_PATTERN_LABEL
    n_visible_edges: int = 0
    n_hatch_lines: int = 0
    n_contour_edges: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "visible_edges": self.visible_edges,
            "hatch_lines": self.hatch_lines,
            "contour_edges": self.contour_edges,
            "cutting_plane_marker": self.cutting_plane_marker,
            "hatch_angle_deg": self.hatch_angle_deg,
            "hatch_spacing_mm": self.hatch_spacing_mm,
            "hatch_pattern": self.hatch_pattern,
            "n_visible_edges": self.n_visible_edges,
            "n_hatch_lines": self.n_hatch_lines,
            "n_contour_edges": self.n_contour_edges,
        }


def compute_section_view(
    vertices: Sequence,
    triangles: Sequence,
    plane: Any,
    view_direction: Optional[Sequence] = None,
    *,
    hatch_angle_deg: float = _HATCH_ANGLE_DEG,
    hatch_spacing_mm: float = _HATCH_SPACING_MM,
    label: str = "A",
) -> SectionViewResult:
    """Compute a section view by cutting a mesh with a plane.

    Parameters
    ----------
    vertices : array-like (N, 3)
        3D vertex positions.
    triangles : array-like (M, 3)
        Triangle face indices.
    plane : dict | list[4] | str
        Cutting plane specification.  Supported forms:
        - ``{"normal": [nx,ny,nz], "point": [px,py,pz]}``
        - ``{"normal": [nx,ny,nz], "d": d}``  (plane equation n·x + d = 0)
        - ``[a, b, c, d]``                     (ax + by + cz + d = 0)
        - ``"xz@y=25"``                         (axis-aligned at offset)
    view_direction : array-like [dx, dy, dz], optional
        Direction from which the section view is projected.  Defaults to
        along the plane normal.
    hatch_angle_deg : float
        Hatch line angle in degrees (default 45° = ANSI 31 / ISO steel).
    hatch_spacing_mm : float
        Spacing between hatch lines (default 3 mm per ISO 128-50 §3.2).
    label : str
        Section label letter (A, B, …) for the cutting-plane marker.

    Returns
    -------
    SectionViewResult

    Never raises.
    """
    try:
        return _compute_section_view_impl(
            vertices, triangles, plane, view_direction,
            hatch_angle_deg=hatch_angle_deg,
            hatch_spacing_mm=hatch_spacing_mm,
            label=label,
        )
    except Exception as exc:
        return SectionViewResult(ok=False, reason=str(exc))


def _compute_section_view_impl(
    vertices: Sequence,
    triangles: Sequence,
    plane: Any,
    view_direction: Optional[Sequence],
    *,
    hatch_angle_deg: float,
    hatch_spacing_mm: float,
    label: str,
) -> SectionViewResult:
    verts = np.asarray(vertices, dtype=float)
    tris = np.asarray(triangles, dtype=int)

    if verts.ndim != 2 or verts.shape[1] != 3:
        raise ValueError(f"vertices must be (N,3); got {verts.shape}")
    if tris.ndim != 2 or tris.shape[1] != 3:
        raise ValueError(f"triangles must be (M,3); got {tris.shape}")

    plane_normal, plane_d = _parse_plane_spec(plane)

    # Build view basis (project along view_direction onto the plane's 2D frame)
    if view_direction is not None:
        vdir = _unit(np.asarray(view_direction, dtype=float).ravel()[:3])
    else:
        vdir = plane_normal.copy()

    # Build right/up vectors for the 2D projection
    up_hint = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(vdir, up_hint)) > 0.9:
        up_hint = np.array([0.0, 1.0, 0.0])
    right2d = _unit(np.cross(vdir, up_hint))
    up2d = _unit(np.cross(right2d, vdir))

    # Clip visible edges to the cut half-space (keep behind-the-plane side)
    # "Behind" = positive half-space (normal·x + d >= 0)
    tol = 1e-9
    visible: List[Polyline2] = []

    # Extract all edges from triangle mesh (boundary + crease)
    try:
        from kerf_cad_core.geom.make2d import (  # type: ignore[import]
            _build_edge_face_map,
            _extract_feature_edges,
            _compute_face_normals,
        )
        face_normals = _compute_face_normals(verts, tris)
        ef_map = _build_edge_face_map(tris)
        mesh_input = _make2d_input(verts, tris)
        feature_edges = _extract_feature_edges(mesh_input, face_normals, ef_map)
    except Exception:
        # Fallback: use all triangle edges
        edge_set: Dict = {}
        for tri in tris:
            for k in range(3):
                a, b = int(tri[k]), int(tri[(k + 1) % 3])
                e = (min(a, b), max(a, b))
                edge_set[e] = True
        feature_edges = list(edge_set.keys())

    for (i0, i1) in feature_edges:
        p0, p1 = verts[i0], verts[i1]
        clipped = _clip_edge_to_halfspace(p0, p1, plane_normal, plane_d)
        if clipped is None:
            continue
        a3, b3 = clipped
        if np.linalg.norm(a3 - b3) < tol:
            continue
        a2 = [float(np.dot(a3, right2d)), float(np.dot(a3, up2d))]
        b2 = [float(np.dot(b3, right2d)), float(np.dot(b3, up2d))]
        visible.append([a2, b2])

    # Section contour (where the cut plane intersects the mesh)
    contour = _mesh_section_contour(verts, tris, plane_normal, plane_d)

    # Generate hatch lines
    hatch = _generate_hatch(contour, angle_deg=hatch_angle_deg, spacing_mm=hatch_spacing_mm)

    # Cutting-plane marker: a line running across the bounding box of the
    # visible geometry, annotated with the section label
    bbox_pts = [p for seg in (visible + contour) for p in seg]
    if bbox_pts:
        xs = [p[0] for p in bbox_pts]
        ys = [p[1] for p in bbox_pts]
        marker_xmin, marker_xmax = min(xs), max(xs)
        marker_y = min(ys) - 10.0  # place marker below the view
        cp_marker = {
            "line_start": [marker_xmin, marker_y],
            "line_end": [marker_xmax, marker_y],
            "label_left": f"{label}",
            "label_right": f"{label}",
            "style": "chain_thin",  # thin chain-dotted line (ISO 128-24)
            "arrow_dir_left": [0.0, 1.0],
            "arrow_dir_right": [0.0, 1.0],
        }
    else:
        cp_marker = {}

    return SectionViewResult(
        ok=True,
        visible_edges=visible,
        hatch_lines=hatch,
        contour_edges=contour,
        cutting_plane_marker=cp_marker,
        hatch_angle_deg=hatch_angle_deg,
        hatch_spacing_mm=hatch_spacing_mm,
        hatch_pattern=_HATCH_PATTERN_LABEL,
        n_visible_edges=len(visible),
        n_hatch_lines=len(hatch),
        n_contour_edges=len(contour),
    )


# ---------------------------------------------------------------------------
# Public API: detail_view
# ---------------------------------------------------------------------------


@dataclass
class DetailViewResult:
    """Output of drawing_detail_view.

    Attributes
    ----------
    ok : bool
    reason : str
    clipped_visible : list[Polyline2]
        Visible edges clipped to the detail circle, magnified.
    clipped_hidden : list[Polyline2]
        Hidden edges clipped to the detail circle, magnified.
    magnification : float
        Scale factor applied.
    label : str
        Detail label letter (A, B, …).
    detail_circle : dict
        Circle annotation for the parent view: {'cx', 'cy', 'r', 'label'}.
    detail_label_annotation : dict
        Label + leader for the detail view frame.
    n_clipped_visible : int
    n_clipped_hidden : int
    """
    ok: bool = True
    reason: str = ""
    clipped_visible: List[Polyline2] = field(default_factory=list)
    clipped_hidden: List[Polyline2] = field(default_factory=list)
    magnification: float = 2.0
    label: str = "A"
    detail_circle: Dict[str, Any] = field(default_factory=dict)
    detail_label_annotation: Dict[str, Any] = field(default_factory=dict)
    n_clipped_visible: int = 0
    n_clipped_hidden: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "clipped_visible": self.clipped_visible,
            "clipped_hidden": self.clipped_hidden,
            "magnification": self.magnification,
            "label": self.label,
            "detail_circle": self.detail_circle,
            "detail_label_annotation": self.detail_label_annotation,
            "n_clipped_visible": self.n_clipped_visible,
            "n_clipped_hidden": self.n_clipped_hidden,
        }


def compute_detail_view(
    visible_edges: Sequence,
    hidden_edges: Sequence,
    centre: Sequence,
    radius: float,
    magnification: float = 2.0,
    label: str = "A",
) -> DetailViewResult:
    """Extract a magnified detail view from a region of an existing 2D view.

    Parameters
    ----------
    visible_edges : list of polylines [[x,y],...]
        Visible-edge polylines of the parent view (in mm).
    hidden_edges : list of polylines [[x,y],...]
        Hidden-edge polylines of the parent view (in mm).
    centre : [cx, cy]
        Centre of the detail circle in view coordinates (mm).
    radius : float
        Radius of the detail region (mm).
    magnification : float
        Scale factor for the detail view (default 2×).
    label : str
        Detail label letter, e.g. "A" (default).

    Returns
    -------
    DetailViewResult

    Never raises.
    """
    try:
        return _compute_detail_view_impl(
            visible_edges, hidden_edges, centre, radius, magnification, label
        )
    except Exception as exc:
        return DetailViewResult(ok=False, reason=str(exc))


def _compute_detail_view_impl(
    visible_edges: Sequence,
    hidden_edges: Sequence,
    centre: Sequence,
    radius: float,
    magnification: float,
    label: str,
) -> DetailViewResult:
    cx, cy = float(centre[0]), float(centre[1])
    r = float(radius)
    m = float(magnification)

    if r <= 0:
        raise ValueError(f"radius must be positive; got {r}")
    if m <= 0:
        raise ValueError(f"magnification must be positive; got {m}")

    def _clip_and_scale(edges: Sequence) -> List[Polyline2]:
        result: List[Polyline2] = []
        for poly in edges:
            polyline = [list(pt) for pt in poly]
            clipped_segs = _clip_polyline_to_circle(polyline, cx, cy, r)
            for seg in clipped_segs:
                # Scale around the centre
                scaled = [
                    [cx + (p[0] - cx) * m, cy + (p[1] - cy) * m]
                    for p in seg
                ]
                result.append(scaled)
        return result

    clipped_vis = _clip_and_scale(visible_edges)
    clipped_hid = _clip_and_scale(hidden_edges)

    # Detail circle annotation for the parent view (ISO 128-30 §10.2)
    detail_circle = {
        "cx": cx,
        "cy": cy,
        "r": r,
        "label": label,
        "style": "thin_solid",  # ISO 128-30 §10.2: thin solid circle
    }

    # Label annotation for the detail view (placed at the detail view location)
    detail_label = {
        "text": f"DETAIL {label}",
        "scale_note": f"SCALE {m:.0f}:1" if m >= 1 else f"SCALE 1:{1/m:.0f}",
        "style": "bold",
    }

    return DetailViewResult(
        ok=True,
        clipped_visible=clipped_vis,
        clipped_hidden=clipped_hid,
        magnification=m,
        label=label,
        detail_circle=detail_circle,
        detail_label_annotation=detail_label,
        n_clipped_visible=len(clipped_vis),
        n_clipped_hidden=len(clipped_hid),
    )


# ---------------------------------------------------------------------------
# Public API: title_block
# ---------------------------------------------------------------------------


def generate_title_block(
    *,
    title: str = "",
    document_number: str = "",
    organisation: str = "",
    scale: str = "1:1",
    sheet: str = "1/1",
    revision: str = "A",
    date_str: Optional[str] = None,
    drawn_by: str = "",
    approved_by: str = "",
    material: str = "",
    weight_kg: Optional[float] = None,
    project: str = "",
    drawing_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate an ISO 7200:2004 §5 compliant title-block dict.

    All fields are optional; missing fields are represented as empty strings.
    The returned dict also contains a ``fields`` list of
    ``{"label": ..., "value": ...}`` pairs in ISO 7200:2004 §5 field order,
    suitable for SVG/DXF rendering.

    Returns
    -------
    dict
        ``{"ok": True, "title_block": {...}, "fields": [...]}``

    Never raises.
    """
    try:
        return _generate_title_block_impl(
            title=title, document_number=document_number,
            organisation=organisation, scale=scale, sheet=sheet,
            revision=revision, date_str=date_str, drawn_by=drawn_by,
            approved_by=approved_by, material=material, weight_kg=weight_kg,
            project=project, drawing_id=drawing_id,
        )
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _generate_title_block_impl(
    title: str,
    document_number: str,
    organisation: str,
    scale: str,
    sheet: str,
    revision: str,
    date_str: Optional[str],
    drawn_by: str,
    approved_by: str,
    material: str,
    weight_kg: Optional[float],
    project: str,
    drawing_id: Optional[str],
) -> Dict[str, Any]:
    today = date.today().isoformat() if date_str is None else date_str
    did = drawing_id or str(uuid.uuid4())[:8].upper()
    weight_str = f"{weight_kg:.3f} kg" if weight_kg is not None else ""

    # ISO 7200:2004 §5 mandatory fields (in order):
    #   1. Legal owner (organisation)
    #   2. Document type (drawing)
    #   3. Document status (revision)
    #   4. Title
    #   5. Identification number (document_number)
    #   6. Date of issue
    #   7. Sheet
    # Plus commonly-used supplementary fields:
    #   Scale, Drawn by, Approved by, Material, Weight, Project
    fields = [
        {"label": "Organisation",      "value": organisation,      "iso": "§5.2.1"},
        {"label": "Document type",     "value": "Engineering Drawing", "iso": "§5.2.2"},
        {"label": "Revision",          "value": revision,          "iso": "§5.2.3"},
        {"label": "Title",             "value": title,             "iso": "§5.2.4"},
        {"label": "Document No.",      "value": document_number or did, "iso": "§5.2.5"},
        {"label": "Date",              "value": today,             "iso": "§5.2.6"},
        {"label": "Sheet",             "value": sheet,             "iso": "§5.2.7"},
        {"label": "Scale",             "value": scale,             "iso": "supplementary"},
        {"label": "Drawn by",          "value": drawn_by,          "iso": "supplementary"},
        {"label": "Approved by",       "value": approved_by,       "iso": "supplementary"},
        {"label": "Material",          "value": material,          "iso": "supplementary"},
        {"label": "Weight",            "value": weight_str,        "iso": "supplementary"},
        {"label": "Project",           "value": project,           "iso": "supplementary"},
    ]

    tb = {
        "title": title,
        "document_number": document_number or did,
        "organisation": organisation,
        "scale": scale,
        "sheet": sheet,
        "revision": revision,
        "date": today,
        "drawn_by": drawn_by,
        "approved_by": approved_by,
        "material": material,
        "weight": weight_str,
        "project": project,
        "drawing_id": did,
        "standard": "ISO 7200:2004",
    }

    return {"ok": True, "title_block": tb, "fields": fields}


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

    # -----------------------------------------------------------------------
    # drawing_section_view
    # -----------------------------------------------------------------------

    _section_view_spec = ToolSpec(
        name="drawing_section_view",
        description=(
            "Generate a section view of a mesh by cutting it with a plane.\n"
            "\n"
            "Method: Sutherland-Hodgman (1974) polygon clipping → visible edges\n"
            "behind the cut + ISO 128-50 hatch (45°, 3 mm spacing) on the cut face.\n"
            "\n"
            "Inputs:\n"
            "  vertices        : [[x,y,z], ...]  — mesh vertices (3D)\n"
            "  triangles       : [[i,j,k], ...]  — mesh triangles\n"
            "  plane           : {normal:[nx,ny,nz], point:[px,py,pz]}\n"
            "                    or [a,b,c,d] (ax+by+cz+d=0)\n"
            "                    or 'xz@y=25' (axis-aligned string)\n"
            "  view_direction  : [dx,dy,dz]  (default = plane normal)\n"
            "  hatch_angle_deg : float  (default 45.0, ISO 128-50 §3.2)\n"
            "  hatch_spacing_mm: float  (default 3.0 mm)\n"
            "  label           : str    (section label 'A', 'B', …)\n"
            "\n"
            "Returns:\n"
            "  ok, visible_edges, hatch_lines, contour_edges,\n"
            "  cutting_plane_marker, hatch_pattern,\n"
            "  n_visible_edges, n_hatch_lines, n_contour_edges\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "3D vertex array [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "triangles": {
                    "type": "array",
                    "description": "Triangle index array [[i,j,k], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "plane": {
                    "description": "Cutting plane: dict, [a,b,c,d] list, or 'xz@y=25' string.",
                },
                "view_direction": {
                    "type": "array",
                    "description": "View direction [dx,dy,dz] (default = plane normal).",
                    "items": {"type": "number"},
                },
                "hatch_angle_deg": {
                    "type": "number",
                    "description": "Hatch angle in degrees (default 45, ISO ANSI 31).",
                },
                "hatch_spacing_mm": {
                    "type": "number",
                    "description": "Hatch line spacing in mm (default 3 mm, ISO 128-50 §3.2).",
                },
                "label": {
                    "type": "string",
                    "description": "Section label letter, e.g. 'A' (default).",
                },
            },
            "required": ["vertices", "triangles", "plane"],
        },
    )

    @register(_section_view_spec)
    async def run_drawing_section_view(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices")
        raw_tris = a.get("triangles")
        plane = a.get("plane")

        if raw_verts is None or raw_tris is None:
            return err_payload("vertices and triangles are required", "BAD_ARGS")
        if plane is None:
            return err_payload("plane is required", "BAD_ARGS")

        try:
            verts = np.array(raw_verts, dtype=float)
            tris = np.array(raw_tris, dtype=int)
        except Exception as exc:
            return err_payload(f"invalid mesh data: {exc}", "BAD_ARGS")

        vdir = a.get("view_direction")
        hatch_angle = float(a.get("hatch_angle_deg", _HATCH_ANGLE_DEG))
        hatch_spacing = float(a.get("hatch_spacing_mm", _HATCH_SPACING_MM))
        label = str(a.get("label", "A"))

        result = compute_section_view(
            verts, tris, plane,
            view_direction=vdir,
            hatch_angle_deg=hatch_angle,
            hatch_spacing_mm=hatch_spacing,
            label=label,
        )

        if not result.ok:
            return err_payload(result.reason, "OP_FAILED")

        return ok_payload(result.to_dict())

    # -----------------------------------------------------------------------
    # drawing_detail_view
    # -----------------------------------------------------------------------

    _detail_view_spec = ToolSpec(
        name="drawing_detail_view",
        description=(
            "Extract a magnified detail view from a circular region of an\n"
            "existing orthographic 2D view — per ISO 128-30 §10 / ASME Y14.3 §9.\n"
            "\n"
            "Inputs:\n"
            "  visible_edges  : list of 2D polylines [[x,y],...] (from the parent view)\n"
            "  hidden_edges   : list of 2D polylines (from the parent view)\n"
            "  centre         : [cx, cy]  — centre of detail circle in view coords (mm)\n"
            "  radius         : float     — radius of the detail region (mm)\n"
            "  magnification  : float     — scale factor (default 2×)\n"
            "  label          : str       — label letter 'A', 'B', … (default 'A')\n"
            "\n"
            "Returns:\n"
            "  ok, clipped_visible, clipped_hidden,\n"
            "  magnification, label,\n"
            "  detail_circle  {cx, cy, r, label} (for parent view annotation),\n"
            "  detail_label_annotation {text, scale_note},\n"
            "  n_clipped_visible, n_clipped_hidden\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "visible_edges": {
                    "type": "array",
                    "description": "Visible-edge polylines [[x,y],...] from the parent view.",
                    "items": {"type": "array"},
                },
                "hidden_edges": {
                    "type": "array",
                    "description": "Hidden-edge polylines from the parent view.",
                    "items": {"type": "array"},
                },
                "centre": {
                    "type": "array",
                    "description": "Centre of the detail circle [cx, cy] in mm.",
                    "items": {"type": "number"},
                },
                "radius": {
                    "type": "number",
                    "description": "Radius of the detail circle in mm.",
                },
                "magnification": {
                    "type": "number",
                    "description": "Magnification factor for the detail view (default 2).",
                },
                "label": {
                    "type": "string",
                    "description": "Detail label letter, e.g. 'A' (default).",
                },
            },
            "required": ["visible_edges", "centre", "radius"],
        },
    )

    @register(_detail_view_spec)
    async def run_drawing_detail_view(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        visible = a.get("visible_edges")
        if visible is None:
            return err_payload("visible_edges is required", "BAD_ARGS")
        hidden = a.get("hidden_edges") or []
        centre = a.get("centre")
        if centre is None or len(centre) < 2:
            return err_payload("centre [cx, cy] is required", "BAD_ARGS")
        radius = a.get("radius")
        if radius is None or float(radius) <= 0:
            return err_payload("radius must be a positive number", "BAD_ARGS")
        magnification = float(a.get("magnification", 2.0))
        label = str(a.get("label", "A"))

        result = compute_detail_view(
            visible, hidden, centre, float(radius), magnification, label
        )
        if not result.ok:
            return err_payload(result.reason, "OP_FAILED")
        return ok_payload(result.to_dict())

    # -----------------------------------------------------------------------
    # drawing_title_block
    # -----------------------------------------------------------------------

    _title_block_spec = ToolSpec(
        name="drawing_title_block",
        description=(
            "Generate an ISO 7200:2004 §5 compliant title-block dict for a\n"
            "technical drawing sheet.\n"
            "\n"
            "Fields (all optional):\n"
            "  title, document_number, organisation, scale (e.g. '1:2'),\n"
            "  sheet (e.g. '1/2'), revision (e.g. 'B'), date (ISO 8601),\n"
            "  drawn_by, approved_by, material, weight_kg, project.\n"
            "\n"
            "Returns:\n"
            "  ok, title_block (dict with all fields + standard tag),\n"
            "  fields (list of {label, value, iso} in ISO 7200:2004 §5 order)\n"
            "\n"
            "Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title":           {"type": "string"},
                "document_number": {"type": "string"},
                "organisation":    {"type": "string"},
                "scale":           {"type": "string"},
                "sheet":           {"type": "string"},
                "revision":        {"type": "string"},
                "date":            {"type": "string", "description": "ISO 8601, e.g. '2026-06-05'"},
                "drawn_by":        {"type": "string"},
                "approved_by":     {"type": "string"},
                "material":        {"type": "string"},
                "weight_kg":       {"type": "number"},
                "project":         {"type": "string"},
            },
            "required": [],
        },
    )

    @register(_title_block_spec)
    async def run_drawing_title_block(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        result = generate_title_block(
            title=str(a.get("title", "")),
            document_number=str(a.get("document_number", "")),
            organisation=str(a.get("organisation", "")),
            scale=str(a.get("scale", "1:1")),
            sheet=str(a.get("sheet", "1/1")),
            revision=str(a.get("revision", "A")),
            date_str=a.get("date"),
            drawn_by=str(a.get("drawn_by", "")),
            approved_by=str(a.get("approved_by", "")),
            material=str(a.get("material", "")),
            weight_kg=float(a["weight_kg"]) if "weight_kg" in a and a["weight_kg"] is not None else None,
            project=str(a.get("project", "")),
        )

        if not result.get("ok"):
            return err_payload(result.get("reason", "unknown error"), "OP_FAILED")
        return ok_payload(result)


__all__ = [
    "SectionViewResult",
    "DetailViewResult",
    "compute_section_view",
    "compute_detail_view",
    "generate_title_block",
]
