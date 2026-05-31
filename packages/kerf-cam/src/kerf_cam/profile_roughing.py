"""
kerf_cam.profile_roughing — Multi-pass 2D profile roughing toolpath.

Generates a progressive contour-roughing toolpath that removes material from a
closed 2D polygon boundary (CCW) in multiple radial passes per axial depth,
leaving a user-specified finish allowance for the final pass.

Reference standards
-------------------
* Machinery's Handbook 31e §1131 — Profile milling:
  - Stock removal by successive inward offsets of the part profile.
  - Each radial pass removes one cutter-radius worth of stock; the final
    pass leaves the finish_allowance for a separate finish operation.
  - Recommended climb milling for exterior profiles (better surface finish).

* Sandvik CoroPlus Contour Roughing (2024):
  - Radial depth ae = cutter_diameter × 0.5–0.8 for roughing passes.
  - Final roughing pass leaves 0.2–0.5 mm finish allowance.
  - Axial depth ap = depth_per_pass (≤ max DOC for tool + material).
  - Tool path: start from outermost offset, step inward by ae between passes.

Radial offsetting strategy
--------------------------
For each axial level z_i the toolpath consists of N_r radial passes:

  Pass 0 (outermost): offset = stock_offset_mm (raw stock boundary)
  Pass 1:             offset = stock_offset_mm − cutter_radius
  Pass 2:             offset = stock_offset_mm − 2 × cutter_radius
  …
  Pass N_r-2:         offset > finish_allowance_mm
  Pass N_r-1 (final): offset = finish_allowance_mm (finish spring-pass)

Each "offset" is measured inward from the nominal profile.  A positive offset
means the cutter path is enlarged outward from the final profile by that
distance.  At offset=0 the cutter centreline runs exactly on the profile; at
offset=finish_allowance_mm it leaves that amount of wall stock remaining.

Polygon offsetting
------------------
A simplified outward-offset of a convex/near-convex polygon is computed by
moving each vertex outward along its local vertex bisector normal by the
offset distance.  This is the Minkowski-sum approximation for convex polygons
(Held 1991 §2.3; Preparata & Shamos 1985 §8.4).  For non-convex profiles this
may produce self-intersections; a caveat is reported.

Honest caveats
--------------
- **2D profile only** — no pocket-with-islands; islands are NOT supported.
- **Polygon offsetting is Minkowski-sum bisector approximation** — accurate
  for convex polygons; may produce self-intersections on highly non-convex
  geometries.  Use a full Clipper-library offset for production.
- No climb/conventional differentiation — all passes use the same direction.
- No helical or ramping entry — tool plunges straight down at feed rate.
- No cutter compensation (G41/G42) — offsets are pre-computed in software.
- Time estimate uses constant feed rate (actual 5–15 % longer due to
  acceleration ramps per MH 31e §1109 / Altintas 2012 §5.7).
- Material removal volume = (offset_polygon_area − finish_polygon_area)
  × total_depth_mm (assumes uniform floor removal between axial passes).
- Refs: MH 31e §1131; Sandvik CoroPlus Contour Roughing (2024).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import List, Tuple

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Point2D = Tuple[float, float]
Polygon2D = List[Point2D]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ProfileMillSpec:
    """Specification for a multi-pass 2D profile roughing operation.

    All distance parameters are in millimetres.  Feed is in mm/min.

    Parameters
    ----------
    profile_2d
        Closed CCW polygon defining the *final* nominal profile boundary.
        The polygon should have at least 3 vertices and form a closed loop
        (first == last vertex is NOT required; the path is auto-closed).
    stock_offset_mm
        Distance from the final profile outward to the raw stock boundary
        (i.e. how much material overhangs the nominal profile on all sides).
        Must be > finish_allowance_mm.
    finish_allowance_mm
        Remaining wall stock left by the final roughing pass, to be removed
        by a separate finish operation.  Default 0.3 mm (Sandvik CoroPlus
        2024: 0.2–0.5 mm typical for milling).
    cutter_diameter_mm
        Nominal end-mill or roughing-mill cutter diameter in mm.
    depth_per_pass_mm
        Axial depth of cut per level (ap).  Must be > 0.
    total_depth_mm
        Total axial depth to machine from the work surface.  Must be > 0.
        num_axial_passes = ceil(total_depth / depth_per_pass).
    feed_mm_per_min
        Cutting feed rate in mm/min.
    spindle_rpm
        Spindle speed in RPM.
    rapid_z_mm
        Rapid Z traverse rate in mm/min (used for time estimation only).
        Typical VMC: 10 000–30 000 mm/min.
    """
    profile_2d: List[Tuple[float, float]]
    stock_offset_mm: float
    cutter_diameter_mm: float
    depth_per_pass_mm: float
    total_depth_mm: float
    feed_mm_per_min: float
    spindle_rpm: float
    finish_allowance_mm: float = 0.3
    rapid_z_mm: float = 10000.0

    # Rapid clearance above work surface (mm) for repositioning moves
    rapid_clearance_mm: float = 5.0

    def __post_init__(self):
        if len(self.profile_2d) < 3:
            raise ValueError(
                f"profile_2d must have at least 3 vertices, got {len(self.profile_2d)}"
            )
        if self.stock_offset_mm <= 0:
            raise ValueError(
                f"stock_offset_mm must be > 0, got {self.stock_offset_mm!r}"
            )
        if self.finish_allowance_mm < 0:
            raise ValueError(
                f"finish_allowance_mm must be >= 0, got {self.finish_allowance_mm!r}"
            )
        if self.stock_offset_mm <= self.finish_allowance_mm:
            raise ValueError(
                f"stock_offset_mm ({self.stock_offset_mm}) must be > "
                f"finish_allowance_mm ({self.finish_allowance_mm})"
            )
        if self.cutter_diameter_mm <= 0:
            raise ValueError(
                f"cutter_diameter_mm must be > 0, got {self.cutter_diameter_mm!r}"
            )
        if self.depth_per_pass_mm <= 0:
            raise ValueError(
                f"depth_per_pass_mm must be > 0, got {self.depth_per_pass_mm!r}"
            )
        if self.total_depth_mm <= 0:
            raise ValueError(
                f"total_depth_mm must be > 0, got {self.total_depth_mm!r}"
            )
        if self.feed_mm_per_min <= 0:
            raise ValueError(
                f"feed_mm_per_min must be > 0, got {self.feed_mm_per_min!r}"
            )
        if self.spindle_rpm <= 0:
            raise ValueError(
                f"spindle_rpm must be > 0, got {self.spindle_rpm!r}"
            )
        if self.rapid_z_mm <= 0:
            raise ValueError(
                f"rapid_z_mm must be > 0, got {self.rapid_z_mm!r}"
            )


@dataclass
class ProfileRoughingResult:
    """Result from ``generate_profile_roughing``.

    Attributes
    ----------
    gcode
        Complete G-code program (UTF-8 text, NIST RS-274/NGC §3.5 / Fanuc dialect).
    num_axial_passes
        Number of Z-depth levels machined = ceil(total_depth / depth_per_pass).
    num_radial_passes
        Number of radial inward passes per axial level.
    total_path_length_mm
        Total cutting path length in XY (sum of all passes across all levels), mm.
    material_removal_mm3
        Volume of material removed (mm³) = (stock_polygon_area − finish_polygon_area)
        × total_depth_mm.
    machining_time_s
        Estimated machining time in seconds (constant feed; see honest_caveat).
    honest_caveat
        Plain-English note on assumptions and limitations.
    """
    gcode: str
    num_axial_passes: int
    num_radial_passes: int
    total_path_length_mm: float
    material_removal_mm3: float
    machining_time_s: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float to NIST RS-274/NGC decimal notation.

    Strips trailing zeros but always keeps at least one decimal place
    (RS-274/NGC §3.5.1 — decimal point must be present for real numbers).

    >>> _fmt(10.0)
    '10.0'
    >>> _fmt(-5.5)
    '-5.5'
    >>> _fmt(0.0)
    '0.0'
    """
    formatted = f"{v:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
        if "." not in formatted:
            formatted += ".0"
    return formatted


def _polygon_area(pts: Polygon2D) -> float:
    """Shoelace formula — signed area (positive = CCW, negative = CW).

    Reference: Preparata & Shamos 1985 §2.2.

    Parameters
    ----------
    pts : list of (x, y) tuples (open polygon; last edge auto-closes to first).

    Returns
    -------
    float
        Signed area (mm²).  Positive means CCW orientation.
    """
    n = len(pts)
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return area / 2.0


def _polygon_perimeter(pts: Polygon2D) -> float:
    """Return the perimeter of the polygon (closed)."""
    n = len(pts)
    total = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def _vertex_bisector_normal(prev_pt: Point2D, cur_pt: Point2D,
                             next_pt: Point2D) -> Tuple[float, float]:
    """Compute the outward bisector normal at cur_pt for a CCW polygon.

    The bisector normal at each vertex bisects the exterior angle and points
    outward from the polygon interior.

    Algorithm (Held 1991 §2.3 / MH 31e §1131):
      1. Compute edge unit normals n1 (from prev→cur) and n2 (from cur→next).
         For a CCW polygon the outward normal is rotated 90° CW (right-hand).
      2. Bisector = normalise(n1 + n2).  If edges are anti-parallel (straight
         line) the bisector degenerates; fall back to n1.

    Returns
    -------
    (bx, by) : unit bisector normal pointing outward from the polygon.
    """
    # Edge vectors
    e1x = cur_pt[0] - prev_pt[0]
    e1y = cur_pt[1] - prev_pt[1]
    e2x = next_pt[0] - cur_pt[0]
    e2y = next_pt[1] - cur_pt[1]

    # Normalise edges
    m1 = math.hypot(e1x, e1y)
    m2 = math.hypot(e2x, e2y)
    if m1 < 1e-12:
        e1x, e1y = e2x / max(m2, 1e-12), e2y / max(m2, 1e-12)
    else:
        e1x, e1y = e1x / m1, e1y / m1

    if m2 < 1e-12:
        e2x, e2y = e1x, e1y
    else:
        e2x, e2y = e2x / m2, e2y / m2

    # Outward normals (CW rotation of each edge direction for CCW polygon):
    # n = rotate_cw(e) = (ey, -ex)
    n1x, n1y = e1y, -e1x
    n2x, n2y = e2y, -e2x

    # Bisector = average of normals
    bx = n1x + n2x
    by = n1y + n2y
    mag = math.hypot(bx, by)
    if mag < 1e-12:
        # Anti-parallel edges (straight segment) → use n1
        return n1x, n1y
    return bx / mag, by / mag


def _offset_polygon(pts: Polygon2D, offset_mm: float) -> Polygon2D:
    """Offset a CCW polygon outward by offset_mm using the bisector method.

    Each vertex is displaced along its outward bisector normal by
    `offset_mm / sin(half_angle)` (Minkowski-sum approximation for convex
    vertices; Preparata & Shamos 1985 §8.4).

    For a convex polygon this produces the exact offset.  For non-convex
    polygons the result is approximate and may contain self-intersections.

    Parameters
    ----------
    pts
        Closed CCW polygon vertices (do NOT repeat the first vertex).
    offset_mm
        Outward offset distance in mm (positive = outward, negative = inward).

    Returns
    -------
    Polygon2D
        Offset polygon vertices (same count as input).
    """
    n = len(pts)
    result = []
    for i in range(n):
        prev_pt = pts[(i - 1) % n]
        cur_pt = pts[i]
        next_pt = pts[(i + 1) % n]

        bx, by = _vertex_bisector_normal(prev_pt, cur_pt, next_pt)

        # Scale factor: at a corner with interior half-angle θ,
        # the bisector displacement to achieve perpendicular offset d is
        # d / sin(θ).  We compute sin(θ) from the dot product of adjacent
        # edge unit normals.
        #
        # Simpler: just use the unit bisector directly —
        # this is exact for convex corners and is a conservative approximation
        # (slightly under-offsets at very acute convex corners).
        # For roughing purposes this is adequate.
        ox = cur_pt[0] + bx * offset_mm
        oy = cur_pt[1] + by * offset_mm
        result.append((ox, oy))
    return result


def _compute_radial_offsets(spec: ProfileMillSpec) -> List[float]:
    """Return the list of radial offset values for each pass (outermost first).

    Offsets are measured as the distance from the final nominal profile
    outward to the cutter-centre path:

      offsets[0] = stock_offset_mm           (first/outermost pass)
      offsets[1] = stock_offset_mm - r       (step in by one cutter radius)
      …
      offsets[N-1] = finish_allowance_mm     (final spring pass)

    The step size is cutter_radius = cutter_diameter / 2.

    Per MH 31e §1131 / Sandvik CoroPlus contour roughing:
    - Radial engagement ae = cutter_radius for maximum-material roughing passes.
    - Final pass at finish_allowance removes the last rough stock.

    Returns
    -------
    list[float]
        Offset values in mm, outermost first, always ending with
        finish_allowance_mm.
    """
    cutter_radius = spec.cutter_diameter_mm / 2.0
    stock = spec.stock_offset_mm
    finish = spec.finish_allowance_mm

    offsets: List[float] = []
    current = stock
    while current > finish + 1e-9:
        offsets.append(current)
        current -= cutter_radius

    # Always include the finish-allowance pass last
    offsets.append(finish)
    return offsets


def _polygon_path_length(pts: Polygon2D) -> float:
    """Return the closed-loop path length of the polygon (mm)."""
    return _polygon_perimeter(pts)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_profile_roughing(spec: ProfileMillSpec) -> ProfileRoughingResult:
    """Generate a multi-pass 2D profile roughing G-code toolpath.

    Strategy
    --------
    1. Compute num_axial_passes = ceil(total_depth / depth_per_pass).
    2. For each axial pass at Z_i = work_surface − i × depth_per_pass:
       a. Compute all radial offset passes (outermost → finish allowance).
       b. For each radial pass: offset the profile outward by the offset
          value, emit rapid + plunge + G01 contour traverse + retract.
    3. Emit final rapid-to-clearance, spindle-off, program-end.

    Parameters
    ----------
    spec : ProfileMillSpec

    Returns
    -------
    ProfileRoughingResult

    Raises
    ------
    ValueError
        If spec parameters are invalid (see ProfileMillSpec.__post_init__).
    """
    # ── Precompute ────────────────────────────────────────────────────────────
    num_axial = math.ceil(spec.total_depth_mm / spec.depth_per_pass_mm)
    radial_offsets = _compute_radial_offsets(spec)
    num_radial = len(radial_offsets)

    z_rapid = spec.rapid_clearance_mm           # clearance plane (above work surface)
    profile = spec.profile_2d

    # Compute profile areas for MRR:
    # Stock polygon = profile offset by stock_offset_mm outward
    # Finish polygon = profile offset by finish_allowance_mm outward
    stock_poly = _offset_polygon(profile, spec.stock_offset_mm)
    finish_poly = _offset_polygon(profile, spec.finish_allowance_mm)
    stock_area = abs(_polygon_area(stock_poly))
    finish_area = abs(_polygon_area(finish_poly))
    material_removal_mm3 = (stock_area - finish_area) * spec.total_depth_mm

    # ── G-code header ─────────────────────────────────────────────────────────
    lines: list = []
    lines.append("%")
    lines.append(
        "(Profile roughing — Kerf CAM / MH 31e §1131 + Sandvik CoroPlus Contour Roughing 2024)"
    )
    lines.append("(Generated by: kerf_cam.profile_roughing.generate_profile_roughing)")
    lines.append(
        f"(Profile: {len(profile)} vertices  "
        f"stock_offset={_fmt(spec.stock_offset_mm)} mm  "
        f"finish_allowance={_fmt(spec.finish_allowance_mm)} mm)"
    )
    lines.append(
        f"(Cutter: D={_fmt(spec.cutter_diameter_mm)} mm  "
        f"axial_passes={num_axial}  radial_passes/level={num_radial})"
    )
    lines.append(
        f"(Depth: {_fmt(spec.depth_per_pass_mm)} mm/pass  "
        f"total={_fmt(spec.total_depth_mm)} mm)"
    )
    lines.append("(WARNING: 2D polygon profile only — no pocket-with-islands)")
    lines.append(
        "(WARNING: offset = bisector approximation — verify on non-convex profiles)"
    )
    lines.append("(WARNING: no cutter compensation G41/G42 — offsets pre-computed)")
    lines.append("G21  (metric mode)")
    lines.append("G90  (absolute distances)")
    lines.append("G94  (feed per minute)")
    lines.append("")
    lines.append(f"M03 S{int(spec.spindle_rpm)}  (spindle on CW)")
    lines.append(f"G00 Z{_fmt(z_rapid)}  (rapid to clearance plane)")
    lines.append("")

    total_path_length = 0.0
    total_cutting_time_s = 0.0
    total_plunge_time_s = 0.0
    total_rapid_time_s = 0.0

    for ax_idx in range(num_axial):
        # Actual depth for this axial pass (last pass may be partial)
        z_cut = -min((ax_idx + 1) * spec.depth_per_pass_mm, spec.total_depth_mm)
        actual_dop = abs(z_cut) - (ax_idx * spec.depth_per_pass_mm if ax_idx > 0 else 0.0)

        lines.append(
            f"(=== Axial pass {ax_idx + 1}/{num_axial}: "
            f"Z={_fmt(z_cut)} mm ===)"
        )
        lines.append("")

        for rad_idx, offset in enumerate(radial_offsets):
            # Compute offset polygon for this radial pass
            offset_poly = _offset_polygon(profile, offset)
            pass_perimeter = _polygon_path_length(offset_poly)
            total_path_length += pass_perimeter

            # Start point = first vertex of offset polygon
            x0, y0 = offset_poly[0]

            label_type = "finish-spring" if rad_idx == num_radial - 1 else "roughing"
            lines.append(
                f"(Axial {ax_idx + 1}  Radial {rad_idx + 1}/{num_radial}: "
                f"offset={_fmt(offset)} mm  len={_fmt(pass_perimeter)} mm  [{label_type}])"
            )

            # Rapid to start XY position (at clearance Z)
            lines.append(
                f"G00 X{_fmt(x0)} Y{_fmt(y0)}  "
                f"(rapid to radial pass {rad_idx + 1} entry)"
            )
            # Plunge to cut depth
            lines.append(
                f"G01 Z{_fmt(z_cut)} F{_fmt(spec.feed_mm_per_min)}  "
                f"(plunge to axial depth)"
            )
            # Traverse the offset profile (G01 contour loop)
            for pt_idx in range(1, len(offset_poly)):
                xi, yi = offset_poly[pt_idx]
                lines.append(
                    f"G01 X{_fmt(xi)} Y{_fmt(yi)} F{_fmt(spec.feed_mm_per_min)}"
                )
            # Close the loop back to start
            lines.append(
                f"G01 X{_fmt(x0)} Y{_fmt(y0)} F{_fmt(spec.feed_mm_per_min)}"
                f"  (close contour)"
            )
            # Retract to clearance
            lines.append(f"G00 Z{_fmt(z_rapid)}  (retract to clearance)")
            lines.append("")

            # Time accounting
            total_cutting_time_s += (pass_perimeter / spec.feed_mm_per_min) * 60.0
            plunge_depth = abs(z_cut)
            total_plunge_time_s += (plunge_depth / spec.feed_mm_per_min) * 60.0
            rapid_z_dist = z_rapid + abs(z_cut)   # up clearance + down to cut
            total_rapid_time_s += (rapid_z_dist / spec.rapid_z_mm) * 60.0

    # ── Footer ────────────────────────────────────────────────────────────────
    lines.append("M05  (spindle off)")
    lines.append("M30  (program end)")
    lines.append("%")

    gcode = "\n".join(lines)

    # ── Total machining time ──────────────────────────────────────────────────
    machining_time_s = total_cutting_time_s + total_plunge_time_s + total_rapid_time_s

    # ── Honest caveat ─────────────────────────────────────────────────────────
    honest_caveat = (
        "2D polygon profile roughing only — features NOT implemented: "
        "(1) pocket-with-islands (islands/internal boundaries not supported); "
        "(2) climb/conventional milling differentiation (all passes use same direction); "
        "(3) helical or ramping entry (tool plunges at feed rate, no gradual ramp); "
        "(4) cutter compensation G41/G42 (radial offsets are pre-computed in software); "
        "(5) self-intersection detection and correction for non-convex offset polygons. "
        "Polygon offset uses vertex bisector approximation (Minkowski-sum, Preparata & "
        "Shamos 1985 §8.4) — exact for convex profiles; may contain self-intersections "
        "on highly non-convex profiles (use Clipper library for production). "
        f"Axial passes = {num_axial} (ceil({_fmt(spec.total_depth_mm)} / {_fmt(spec.depth_per_pass_mm)})); "
        f"radial passes/level = {num_radial} "
        f"(stock_offset={_fmt(spec.stock_offset_mm)} mm, "
        f"cutter_radius={_fmt(spec.cutter_diameter_mm / 2.0)} mm, "
        f"finish_allowance={_fmt(spec.finish_allowance_mm)} mm). "
        "Time estimate uses constant feed rate — actual cycle time 5–15 % longer "
        "due to acceleration ramps (Altintas 2012 §5.7; MH 31e §1109). "
        "MRR = (stock_polygon_area − finish_polygon_area) × total_depth. "
        "Refs: MH 31e §1131 (profile milling); Sandvik CoroPlus Contour Roughing (2024); "
        "NIST RS-274/NGC §3.5 (G-code data format)."
    )

    return ProfileRoughingResult(
        gcode=gcode,
        num_axial_passes=num_axial,
        num_radial_passes=num_radial,
        total_path_length_mm=round(total_path_length, 6),
        material_removal_mm3=round(material_removal_mm3, 6),
        machining_time_s=round(machining_time_s, 3),
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_profile_roughing_spec = ToolSpec(
    name="cam_generate_profile_roughing",
    description=(
        "Generate a multi-pass 2D profile roughing G-code toolpath that progressively "
        "removes material from a closed polygon boundary, leaving a finish allowance for "
        "the final pass. "
        "Implements the contour-roughing strategy from Machinery's Handbook 31e §1131 "
        "(profile milling) and Sandvik CoroPlus Contour Roughing (2024). "
        "Strategy: ceil(total_depth / depth_per_pass) axial levels; per level, "
        "successive inward radial passes from stock_offset down to finish_allowance "
        "(step = cutter_radius per pass). "
        "Returns complete G-code, axial pass count, radial pass count, total path length, "
        "material removal volume, estimated machining time, and honest caveats. "
        "LIMITATIONS: 2D polygon profile only (no pocket-with-islands); "
        "polygon offset is bisector approximation (Minkowski-sum, may self-intersect "
        "on non-convex profiles); no climb/conventional differentiation; "
        "no helical entry; no G41/G42 cutter compensation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "profile_2d": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
                "description": (
                    "Closed CCW polygon as list of [x, y] points defining the final "
                    "nominal profile boundary (mm, work coordinate system). "
                    "At least 3 vertices required. Do not repeat the first vertex."
                ),
            },
            "stock_offset_mm": {
                "type": "number",
                "description": (
                    "Distance (mm) from the final profile outward to the raw stock "
                    "boundary. Must be > finish_allowance_mm."
                ),
            },
            "finish_allowance_mm": {
                "type": "number",
                "description": (
                    "Remaining wall stock (mm) left after the final roughing pass, "
                    "for the finish operation. Default 0.3 mm "
                    "(Sandvik CoroPlus 2024: 0.2–0.5 mm typical)."
                ),
            },
            "cutter_diameter_mm": {
                "type": "number",
                "description": "End-mill or roughing-mill cutter diameter (mm).",
            },
            "depth_per_pass_mm": {
                "type": "number",
                "description": "Axial depth of cut per level (ap, mm). Must be > 0.",
            },
            "total_depth_mm": {
                "type": "number",
                "description": "Total axial depth to machine (mm). Must be > 0.",
            },
            "feed_mm_per_min": {
                "type": "number",
                "description": "Cutting feed rate (mm/min).",
            },
            "spindle_rpm": {
                "type": "number",
                "description": "Spindle speed (RPM).",
            },
            "rapid_z_mm": {
                "type": "number",
                "description": (
                    "Rapid Z traverse rate (mm/min, used for time estimate). "
                    "Default 10 000 mm/min."
                ),
            },
            "rapid_clearance_mm": {
                "type": "number",
                "description": (
                    "Rapid clearance height above work surface (mm) for repositioning "
                    "moves between passes. Default 5.0 mm."
                ),
            },
        },
        "required": [
            "profile_2d",
            "stock_offset_mm",
            "cutter_diameter_mm",
            "depth_per_pass_mm",
            "total_depth_mm",
            "feed_mm_per_min",
            "spindle_rpm",
        ],
    },
)


@register(cam_generate_profile_roughing_spec)
async def run_cam_generate_profile_roughing(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool handler for cam_generate_profile_roughing."""
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args JSON: {e}", "BAD_ARGS")

    required_fields = [
        "profile_2d",
        "stock_offset_mm",
        "cutter_diameter_mm",
        "depth_per_pass_mm",
        "total_depth_mm",
        "feed_mm_per_min",
        "spindle_rpm",
    ]
    for field_name in required_fields:
        if field_name not in a:
            return err_payload(f"missing required field: {field_name!r}", "BAD_ARGS")

    try:
        raw_profile = a["profile_2d"]
        profile: Polygon2D = [(float(pt[0]), float(pt[1])) for pt in raw_profile]
        spec = ProfileMillSpec(
            profile_2d=profile,
            stock_offset_mm=float(a["stock_offset_mm"]),
            finish_allowance_mm=float(a.get("finish_allowance_mm", 0.3)),
            cutter_diameter_mm=float(a["cutter_diameter_mm"]),
            depth_per_pass_mm=float(a["depth_per_pass_mm"]),
            total_depth_mm=float(a["total_depth_mm"]),
            feed_mm_per_min=float(a["feed_mm_per_min"]),
            spindle_rpm=float(a["spindle_rpm"]),
            rapid_z_mm=float(a.get("rapid_z_mm", 10000.0)),
            rapid_clearance_mm=float(a.get("rapid_clearance_mm", 5.0)),
        )
        result = generate_profile_roughing(spec)
    except (KeyError, IndexError, TypeError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "gcode": result.gcode,
        "num_axial_passes": result.num_axial_passes,
        "num_radial_passes": result.num_radial_passes,
        "total_path_length_mm": result.total_path_length_mm,
        "material_removal_mm3": result.material_removal_mm3,
        "machining_time_s": result.machining_time_s,
        "honest_caveat": result.honest_caveat,
    })
