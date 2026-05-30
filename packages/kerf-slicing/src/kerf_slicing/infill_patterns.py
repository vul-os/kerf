"""
infill_patterns.py — pure-Python 3D-print infill pattern generator.

Generates 2D infill toolpaths for FDM slicing without invoking CuraEngine.
Useful for UI preview, sandboxed slicing, and custom pattern experimentation.

References
----------
- Schoen 1970 "Infinite periodic minimal surfaces without self-intersections"
  (gyroid TPMS definition: sin·cos + sin·cos + sin·cos = 0)
- Aremu et al 2017 "A voxel-based method of constructing and skinning conformal
  and functionally graded lattice structures" (TPMS lattice thresholding)
- Marching squares: Maple/Lorensen-Cline 2D analogue (edge interpolation,
  16-case lookup table).

All coordinates are in millimetres.
"""
from __future__ import annotations

import math
from typing import NamedTuple, Sequence

import numpy as np


# ── primitive types ────────────────────────────────────────────────────────────

class Segment2D(NamedTuple):
    """An undirected line segment in the XY plane."""
    x0: float
    y0: float
    x1: float
    y1: float

    def length(self) -> float:
        dx = self.x1 - self.x0
        dy = self.y1 - self.y0
        return math.hypot(dx, dy)


class BBox2D(NamedTuple):
    """Axis-aligned bounding box in XY."""
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def area(self) -> float:
        return self.width * self.height


# ── marching squares (scratch implementation) ─────────────────────────────────

# Edge indices for a unit cell: 0=bottom, 1=right, 2=top, 3=left
# Each case maps to a list of edge-pair connections (pairs of edge indices).
# Standard 16-case Marching Squares lookup table.
_MS_CASES: dict[int, list[tuple[int, int]]] = {
    0:  [],
    1:  [(3, 0)],
    2:  [(0, 1)],
    3:  [(3, 1)],
    4:  [(1, 2)],
    5:  [(3, 2), (0, 1)],   # ambiguous — split diagonally
    6:  [(0, 2)],
    7:  [(3, 2)],
    8:  [(2, 3)],
    9:  [(2, 0)],
    10: [(3, 0), (1, 2)],   # ambiguous — split diagonally
    11: [(1, 2)],            # corrected: corner 0,2,3 above → edge 1 and 2
    12: [(1, 3)],
    13: [(0, 1)],            # corrected: corner 0,1,3 above
    14: [(0, 3)],
    15: [],
}

# Rebuild the full correct 16-case table from first principles.
# Each cell has 4 corners indexed: 0=SW, 1=SE, 2=NE, 3=NW.
# Each edge connects two corners: 0→(SW,SE), 1→(SE,NE), 2→(NE,NW), 3→(NW,SW)
# For the iso-contour, an edge is "active" when its two corners straddle the iso-value.
# The active edge list per case is determined purely by which corners are above/below.

def _ms_edge_param(v0: float, v1: float, iso: float) -> float:
    """Interpolate t ∈ [0,1] along edge from corner-0 to corner-1 at the iso-level."""
    dv = v1 - v0
    if abs(dv) < 1e-12:
        return 0.5
    return (iso - v0) / dv


def _marching_squares(
    F: np.ndarray,
    iso: float,
    x0: float, y0: float,
    dx: float, dy: float,
) -> list[Segment2D]:
    """
    Extract iso-contour segments from a 2D scalar field F using marching squares.

    Parameters
    ----------
    F:
        2D array of shape (ny, nx) sampled at a regular grid.
    iso:
        Iso-value of the contour.
    x0, y0:
        World coordinates of the lower-left corner of the grid.
    dx, dy:
        Grid cell spacing in x and y respectively.

    Returns
    -------
    List of line segments approximating the iso-contour.
    """
    ny, nx = F.shape
    segs: list[Segment2D] = []

    for iy in range(ny - 1):
        for ix in range(nx - 1):
            # Corner values: SW, SE, NE, NW
            vsw = F[iy,     ix    ]
            vse = F[iy,     ix + 1]
            vne = F[iy + 1, ix + 1]
            vnw = F[iy + 1, ix    ]

            # Cell world coordinates
            cx = x0 + ix * dx
            cy = y0 + iy * dy

            # Case index: bit i = 1 if corner i >= iso
            case = (
                (1 if vsw >= iso else 0)
                | (2 if vse >= iso else 0)
                | (4 if vne >= iso else 0)
                | (8 if vnw >= iso else 0)
            )

            if case == 0 or case == 15:
                continue

            # Compute intersection points on each of the 4 edges
            # Edge 0: SW→SE (bottom, y=cy)
            # Edge 1: SE→NE (right, x=cx+dx)
            # Edge 2: NE→NW (top, y=cy+dy) — traversed NE→NW direction
            # Edge 3: NW→SW (left, x=cx) — traversed NW→SW direction
            def pt(edge: int):
                if edge == 0:
                    t = _ms_edge_param(vsw, vse, iso)
                    return cx + t * dx, cy
                elif edge == 1:
                    t = _ms_edge_param(vse, vne, iso)
                    return cx + dx, cy + t * dy
                elif edge == 2:
                    t = _ms_edge_param(vne, vnw, iso)
                    return cx + (1 - t) * dx, cy + dy
                else:  # edge == 3
                    t = _ms_edge_param(vnw, vsw, iso)
                    return cx, cy + (1 - t) * dy

            # Enumerate active edges (corners straddling iso-level)
            active = []
            pairs_sw_se = (vsw >= iso) != (vse >= iso)
            pairs_se_ne = (vse >= iso) != (vne >= iso)
            pairs_ne_nw = (vne >= iso) != (vnw >= iso)
            pairs_nw_sw = (vnw >= iso) != (vsw >= iso)
            if pairs_sw_se: active.append(0)
            if pairs_se_ne: active.append(1)
            if pairs_ne_nw: active.append(2)
            if pairs_nw_sw: active.append(3)

            # Connect active edges into segments
            # For non-ambiguous cases, exactly 2 active edges → 1 segment
            # For ambiguous cases (4 active edges), use saddle-point disambiguation
            if len(active) == 2:
                a, b = active
                p0 = pt(a)
                p1 = pt(b)
                segs.append(Segment2D(p0[0], p0[1], p1[0], p1[1]))
            elif len(active) == 4:
                # Ambiguous case: use saddle-point test (centre value vs iso)
                centre = (vsw + vse + vne + vnw) / 4.0
                if centre >= iso:
                    # Connect: 0-3, 1-2
                    for a, b in [(active[0], active[3]), (active[1], active[2])]:
                        p0 = pt(a)
                        p1 = pt(b)
                        segs.append(Segment2D(p0[0], p0[1], p1[0], p1[1]))
                else:
                    # Connect: 0-1, 2-3
                    for a, b in [(active[0], active[1]), (active[2], active[3])]:
                        p0 = pt(a)
                        p1 = pt(b)
                        segs.append(Segment2D(p0[0], p0[1], p1[0], p1[1]))

    return segs


# ── polygon clipping (Sutherland-Hodgman for bbox) ────────────────────────────

def _clip_segment_to_bbox(seg: Segment2D, bbox: BBox2D) -> Segment2D | None:
    """Clip a segment to a bounding box using Cohen-Sutherland line clipping."""
    x0, y0, x1, y1 = seg.x0, seg.y0, seg.x1, seg.y1
    xmin, ymin, xmax, ymax = bbox

    def _outcode(x: float, y: float) -> int:
        code = 0
        if x < xmin: code |= 1
        if x > xmax: code |= 2
        if y < ymin: code |= 4
        if y > ymax: code |= 8
        return code

    out0 = _outcode(x0, y0)
    out1 = _outcode(x1, y1)

    while True:
        if not (out0 | out1):
            return Segment2D(x0, y0, x1, y1)
        if out0 & out1:
            return None
        # Pick an outside point
        out = out0 if out0 else out1
        dx = x1 - x0
        dy = y1 - y0
        if out & 8:  # above ymax
            x = x0 + dx * (ymax - y0) / dy if abs(dy) > 1e-12 else x0
            y = ymax
        elif out & 4:  # below ymin
            x = x0 + dx * (ymin - y0) / dy if abs(dy) > 1e-12 else x0
            y = ymin
        elif out & 2:  # right of xmax
            y = y0 + dy * (xmax - x0) / dx if abs(dx) > 1e-12 else y0
            x = xmax
        else:  # left of xmin
            y = y0 + dy * (xmin - x0) / dx if abs(dx) > 1e-12 else y0
            x = xmin
        if out == out0:
            x0, y0 = x, y
            out0 = _outcode(x0, y0)
        else:
            x1, y1 = x, y
            out1 = _outcode(x1, y1)


def _clip_segments_to_bbox(segments: list[Segment2D], bbox: BBox2D) -> list[Segment2D]:
    """Filter and clip a segment list to a bbox."""
    result = []
    for seg in segments:
        clipped = _clip_segment_to_bbox(seg, bbox)
        if clipped is not None:
            result.append(clipped)
    return result


# ── polygon point-in-test ─────────────────────────────────────────────────────

def _point_in_polygon(x: float, y: float, poly: np.ndarray) -> bool:
    """Ray-casting test for (x,y) inside a polygon given as (N,2) array."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def _clip_segments_to_polygon(
    segments: list[Segment2D],
    poly: np.ndarray,
    bbox: BBox2D,
) -> list[Segment2D]:
    """
    Clip segments to a polygon by first bbox-clipping, then testing midpoints.

    For a convex polygon this is exact; for concave polygons it approximates
    by testing the midpoint of each segment (standard for raster infill patterns).
    """
    bbox_clipped = _clip_segments_to_bbox(segments, bbox)
    result = []
    for seg in bbox_clipped:
        mid_x = (seg.x0 + seg.x1) / 2.0
        mid_y = (seg.y0 + seg.y1) / 2.0
        if _point_in_polygon(mid_x, mid_y, poly):
            result.append(seg)
    return result


# ── 1. Gyroid (TPMS) infill ───────────────────────────────────────────────────

def generate_gyroid_pattern(
    bbox: BBox2D,
    z: float = 0.0,
    density: float = 0.20,
    cell_size: float = 10.0,
    resolution: int = 200,
) -> list[Segment2D]:
    """
    Generate a gyroid TPMS infill pattern for a single layer.

    The gyroid implicit surface is defined by (Schoen 1970):

        f(x,y,z) = sin(2πx/L)·cos(2πy/L)
                 + sin(2πy/L)·cos(2πz/L)
                 + sin(2πz/L)·cos(2πx/L)

    At iso-value f = 0 this is the minimal surface. For non-zero iso, the two
    level-set sheets bounding the solid region are f = ±threshold. The threshold
    is chosen so that the solid volume fraction approximates `density`.

    For a single FDM layer at height z, we evaluate f(x, y, z=const) on a 2D
    grid and extract the iso-contour with marching squares.

    Parameters
    ----------
    bbox:
        Bounding box of the layer cross-section in mm.
    z:
        Layer height in mm (determines the gyroid phase for this layer).
    density:
        Target fill density as a fraction in [0, 1].
    cell_size:
        Gyroid period L in mm.
    resolution:
        Number of sample points per axis for marching squares.

    Returns
    -------
    List of 2D segments forming the gyroid infill toolpath.
    """
    # Map density → iso threshold.
    # Empirically, the volume fraction of the gyroid sheet (|f| < t) scales
    # approximately linearly with t for small t. The maximum absolute value of f
    # is 1.5 (at (π/4, π/4, z) type points). We linearly map density → threshold.
    # This approximation is consistent with Aremu et al 2017.
    t_max = 1.5
    iso = t_max * density  # threshold: solid region is f ∈ [-iso, +iso]

    L = cell_size
    omega = 2.0 * math.pi / L

    xs = np.linspace(bbox.xmin, bbox.xmax, resolution)
    ys = np.linspace(bbox.ymin, bbox.ymax, resolution)
    X, Y = np.meshgrid(xs, ys)  # shape (resolution, resolution)

    # Gyroid field at fixed z
    F = (
        np.sin(omega * X) * np.cos(omega * Y)
        + np.sin(omega * Y) * np.cos(omega * z)
        + np.sin(omega * z) * np.cos(omega * X)
    )

    dx = (bbox.xmax - bbox.xmin) / (resolution - 1)
    dy = (bbox.ymax - bbox.ymin) / (resolution - 1)

    # Extract both bounding iso-surfaces of the solid shell
    segs_pos = _marching_squares(F, iso, bbox.xmin, bbox.ymin, dx, dy)
    segs_neg = _marching_squares(F, -iso, bbox.xmin, bbox.ymin, dx, dy)

    return segs_pos + segs_neg


# ── 2. Honeycomb infill ────────────────────────────────────────────────────────

def generate_honeycomb_pattern(
    bbox: BBox2D,
    cell_size: float = 5.0,
    wall_thickness: float = 0.4,
) -> list[Segment2D]:
    """
    Generate a regular hexagonal honeycomb infill pattern within a bbox.

    Each hexagon is generated with a flat-top orientation (two horizontal edges).
    Wall thickness is applied as an inward offset of wall_thickness/2 on each
    edge so that adjacent cells share a wall of the full specified thickness.

    Parameters
    ----------
    bbox:
        Bounding box in mm.
    cell_size:
        Circumscribed radius (centre to vertex) of each hexagon in mm.
    wall_thickness:
        Wall thickness in mm. Each edge is inset by wall_thickness/2.

    Returns
    -------
    List of 2D segments forming the honeycomb wall toolpaths.
    """
    s = cell_size  # vertex radius
    # Flat-top hex: horizontal step = s*√3, vertical step = 1.5*s
    h_step = s * math.sqrt(3.0)
    v_step = 1.5 * s
    half_h = h_step / 2.0

    # Generate hex centres covering the bbox with margin
    margin = cell_size * 2
    centres: list[tuple[float, float]] = []
    row = 0
    cy = bbox.ymin - margin
    while cy < bbox.ymax + margin:
        offset_x = half_h if (row % 2 == 1) else 0.0
        cx = bbox.xmin - margin + offset_x
        while cx < bbox.xmax + margin:
            centres.append((cx, cy))
            cx += h_step
        cy += v_step
        row += 1

    # Inset amount per edge
    inset = wall_thickness / 2.0
    # Effective vertex radius after inset
    s_in = s - inset

    # Pre-compute hexagon vertex angles (flat-top: first vertex at 30°)
    angles = [math.pi / 6 + k * math.pi / 3 for k in range(6)]

    segs: list[Segment2D] = []
    for cx, cy in centres:
        verts = [(cx + s_in * math.cos(a), cy + s_in * math.sin(a)) for a in angles]
        for i in range(6):
            x0, y0 = verts[i]
            x1, y1 = verts[(i + 1) % 6]
            seg = Segment2D(x0, y0, x1, y1)
            clipped = _clip_segment_to_bbox(seg, bbox)
            if clipped is not None:
                segs.append(clipped)

    return segs


# ── 3. Triangular grid infill ─────────────────────────────────────────────────

def generate_triangular_grid(
    bbox: BBox2D,
    density: float = 0.25,
    cell_size: float = 8.0,
    line_width: float = 0.4,
) -> list[Segment2D]:
    """
    Generate a triangular grid infill pattern.

    The pattern consists of three families of parallel lines at 0°, 60°, and
    120° that together form an equilateral triangular tessellation. Line spacing
    is chosen so that the total line coverage approximates `density`.

    Fill density for parallel lines:  ρ = line_width / spacing
    Three families → effective spacing per family: spacing = line_width / density * 3

    Parameters
    ----------
    bbox:
        Bounding box in mm.
    density:
        Target fill density as a fraction in [0, 1].
    cell_size:
        Override for triangle side length in mm. If provided, `density` is
        ignored in favour of cell_size (density is recalculated for reference).
    line_width:
        Extrusion line width in mm (used for density calculation).

    Returns
    -------
    List of 2D segments forming the triangular grid toolpaths.
    """
    # Spacing between parallel lines in one family so that combined fill ≈ density
    # 3 families, each covers 1/3 of the density
    if density > 0:
        spacing = line_width / (density / 3.0)
    else:
        spacing = cell_size

    diag = math.hypot(bbox.width, bbox.height)
    margin = diag  # generous margin to cover rotated lines

    segs: list[Segment2D] = []

    # Three line families at 0°, 60°, 120°
    for angle_deg in (0, 60, 120):
        theta = math.radians(angle_deg)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        # Perpendicular direction
        perp_x = -sin_t
        perp_y = cos_t

        cx = (bbox.xmin + bbox.xmax) / 2.0
        cy = (bbox.ymin + bbox.ymax) / 2.0
        n_lines = int(math.ceil(diag / spacing)) + 2

        for k in range(-n_lines, n_lines + 1):
            # Centre of this line (offset perpendicularly by k*spacing)
            ox = cx + k * spacing * perp_x
            oy = cy + k * spacing * perp_y
            # Extend line along direction vector
            x0 = ox - margin * cos_t
            y0 = oy - margin * sin_t
            x1 = ox + margin * cos_t
            y1 = oy + margin * sin_t
            seg = Segment2D(x0, y0, x1, y1)
            clipped = _clip_segment_to_bbox(seg, bbox)
            if clipped is not None:
                segs.append(clipped)

    return segs


# ── 4. Concentric infill ──────────────────────────────────────────────────────

def generate_concentric(
    boundary: Sequence[tuple[float, float]],
    n_offsets: int = 5,
    offset_step: float | None = None,
) -> list[Segment2D]:
    """
    Generate concentric inward offsets of a boundary polygon.

    Each offset ring is obtained by moving each vertex inward by `offset_step`
    along the polygon's inward normal. For a convex polygon this is a clean
    inward offset; for concave polygons, self-intersections may occur but
    topology is not repaired (use Clipper/pyclipper for production quality).

    The default offset_step is chosen so that `n_offsets` rings span the
    approximate inradius of the boundary.

    Parameters
    ----------
    boundary:
        Ordered list of (x, y) vertices defining the outer boundary.
        The polygon is treated as closed (last vertex connects to first).
    n_offsets:
        Number of inward offset rings to generate.
    offset_step:
        Distance between consecutive rings in mm.
        If None, defaults to: inradius / (n_offsets + 1)

    Returns
    -------
    List of 2D segments forming the concentric infill rings.
    """
    pts = np.array(boundary, dtype=float)  # shape (N, 2)
    n = len(pts)

    if n < 3:
        return []

    # Estimate inradius as half the minimum bbox dimension
    xmin, ymin = pts.min(axis=0)
    xmax, ymax = pts.max(axis=0)
    inradius = min(xmax - xmin, ymax - ymin) / 2.0

    if offset_step is None:
        offset_step = inradius / (n_offsets + 1)

    segs: list[Segment2D] = []

    # Compute per-vertex inward-offset direction.
    #
    # For each vertex we form the angle bisector of the two adjacent edge
    # directions. The bisector's left-hand perpendicular points inward for a
    # CCW polygon (positive signed area).
    #
    # Implementation: rotate each edge direction 90° CCW → left-hand side →
    # average the two neighbouring edge normals.  For a CCW polygon the
    # resulting bisector points INWARD (toward the polygon interior).
    # For a CW polygon it points OUTWARD, so we flip it.

    def _vertex_inward_dirs(poly: np.ndarray, ccw: bool) -> np.ndarray:
        """Return per-vertex unit inward direction for a polygon."""
        m = len(poly)
        dirs_ = np.zeros((m, 2))
        for i in range(m):
            prev_pt = poly[(i - 1) % m]
            next_pt = poly[(i + 1) % m]
            e1 = poly[i] - prev_pt   # edge arriving at vertex i
            e2 = next_pt - poly[i]   # edge leaving vertex i
            # Left-hand (CCW 90°) perpendicular of each edge:
            # rotate (dx,dy) → (-dy, dx)
            n1 = np.array([-e1[1], e1[0]])
            n2 = np.array([-e2[1], e2[0]])
            l1 = np.linalg.norm(n1)
            l2 = np.linalg.norm(n2)
            if l1 > 1e-12: n1 /= l1
            if l2 > 1e-12: n2 /= l2
            bisector = n1 + n2
            bl = np.linalg.norm(bisector)
            d = (bisector / bl) if bl > 1e-12 else n1
            # For CCW polygon, this bisector points inward; flip for CW.
            dirs_[i] = d if ccw else -d
        return dirs_

    def _signed_area(poly: np.ndarray) -> float:
        n_ = len(poly)
        s = 0.0
        for i in range(n_):
            j = (i + 1) % n_
            s += poly[i, 0] * poly[j, 1] - poly[j, 0] * poly[i, 1]
        return s / 2.0

    current = pts.copy()
    ccw = _signed_area(current) > 0

    for _ in range(n_offsets):
        inward = _vertex_inward_dirs(current, ccw)
        # Move each vertex inward by offset_step along the inward bisector.
        new_pts = current + offset_step * inward
        # Emit segments for this ring
        for i in range(len(new_pts)):
            j = (i + 1) % len(new_pts)
            segs.append(Segment2D(
                new_pts[i, 0], new_pts[i, 1],
                new_pts[j, 0], new_pts[j, 1],
            ))
        current = new_pts

    return segs


# ── 5. Entry point: fill perimeter with pattern ───────────────────────────────

_PATTERN_KINDS = frozenset({"gyroid", "honeycomb", "triangular", "concentric"})


def fill_perimeter_with_pattern(
    layer_polygon: Sequence[tuple[float, float]],
    pattern_kind: str,
    params: dict | None = None,
) -> list[Segment2D]:
    """
    Generate infill segments for a layer polygon using the specified pattern.

    This is the primary entry point for the LLM tool and frontend renderer.
    The generated pattern is clipped to the layer_polygon boundary.

    Parameters
    ----------
    layer_polygon:
        Ordered (x, y) vertices of the layer cross-section polygon.
    pattern_kind:
        One of "gyroid", "honeycomb", "triangular", "concentric".
    params:
        Optional dict of pattern-specific parameters.
        gyroid:      density (0-1), cell_size (mm), z (layer height mm)
        honeycomb:   cell_size (mm), wall_thickness (mm)
        triangular:  density (0-1), cell_size (mm), line_width (mm)
        concentric:  n_offsets (int), offset_step (mm or None)

    Returns
    -------
    List of 2D segments, clipped to the layer polygon.

    Raises
    ------
    ValueError
        For unknown pattern_kind.
    """
    if pattern_kind not in _PATTERN_KINDS:
        raise ValueError(
            f"Unknown pattern kind {pattern_kind!r}. "
            f"Choose from {sorted(_PATTERN_KINDS)}."
        )

    params = params or {}
    pts = np.array(layer_polygon, dtype=float)

    if len(pts) < 3:
        return []

    xmin, ymin = pts.min(axis=0)
    xmax, ymax = pts.max(axis=0)
    bbox = BBox2D(xmin, ymin, xmax, ymax)

    if pattern_kind == "gyroid":
        raw = generate_gyroid_pattern(
            bbox,
            z=params.get("z", 0.0),
            density=params.get("density", 0.20),
            cell_size=params.get("cell_size", 10.0),
        )
    elif pattern_kind == "honeycomb":
        raw = generate_honeycomb_pattern(
            bbox,
            cell_size=params.get("cell_size", 5.0),
            wall_thickness=params.get("wall_thickness", 0.4),
        )
    elif pattern_kind == "triangular":
        raw = generate_triangular_grid(
            bbox,
            density=params.get("density", 0.25),
            cell_size=params.get("cell_size", 8.0),
            line_width=params.get("line_width", 0.4),
        )
    else:  # concentric
        return generate_concentric(
            layer_polygon,
            n_offsets=params.get("n_offsets", 5),
            offset_step=params.get("offset_step", None),
        )

    return _clip_segments_to_polygon(raw, pts, bbox)
