"""
kerf_cam.offset_3d_path — 3D parallel-offset surface-milling toolpath.

Generates raster (Z-axis-aligned) toolpaths at a constant offset distance from
a target surface defined by a sampled z(x,y) grid, following the tool-centre
offset model from:

  Machinery's Handbook 31e §1139 — 3-axis surface-offset milling:
    "The tool centre must be offset by exactly one tool radius along the
     surface unit normal at every contact point to achieve a constant scallop."

  Held & Klingenstein (1991) "Toolpath Generation for Milling Operations",
    Computers & Graphics 15(3):333–341 — parallel-offset raster strategy:
    parallel XY passes at constant Y-increment (stepover), each pass following
    the z(x,y) surface raised by tool_radius along the Z-normal approximation.

Surface-offset model (3-axis Z-axis-aligned)
--------------------------------------------
For a 3-axis machine the spindle is always vertical (Z-axis).  The ball-end
mill contact point on the surface is the point directly below the tool centre.
The offset is therefore a pure Z-shift:

    z_tool(x, y) = z_surface(x, y) + tool_radius

This is the "Z-axis-aligned offset" model (MH 31e §1139, Held 1991).
It is exact only when the surface normal is vertical; on steep flanks the
actual tool-to-surface distance is less than tool_radius and a slight gouge
can occur.  The honest_caveat field documents this limitation.

Scallop height formula
----------------------
For a ball-end mill of radius R with stepover ae:

    h_scallop = R - sqrt(R² - (ae/2)²)

Reference: Kruth & Klewais (1994) "Optimization and Dynamic Adaptation of the
Cutter Inclination Angle during Five-Axis Milling", CIRP Annals 43(1):443–448.
Also: Chuang & Yang (1995) Intl J of Machine Tools 35(2):261–267.

Example: R=5 mm, ae=1 mm → h = 5 - sqrt(25 - 0.25) = 5 - sqrt(24.75) ≈ 0.0251 mm

G-code conventions
------------------
  G21  metric mode (mm)
  G90  absolute distances
  G94  feed per minute
  M03  spindle on CW
  G00  rapid positioning
  G01  linear feed move
  M05  spindle off
  M30  program end

NIST RS-274/NGC §3.5.

Honest caveats (in Offset3DResult.honest_caveat)
-------------------------------------------------
- **3-axis Z-axis-aligned only** — the tool axis is always +Z vertical.
  No 5-axis tool-axis tilt or swarf cutting. Surface normals with large XY
  components receive less than one tool_radius of offset → potential micro-gouge
  on steep walls (worst case when surface slope > 45°).
- **No gouge checking** — self-intersection of the offset surface and holder
  collision are NOT detected. Use cam_verify_toolpath_collision for that.
- **Raster (parallel-passes) strategy only** — no contouring (waterline/z-level)
  passes, no spiral, no adaptive clearing. Best for shallow sculpted surfaces;
  avoid deep pockets.
- **Bilinear interpolation** — the z(x,y) surface is reconstructed from the input
  grid by bilinear (4-corner) interpolation. High-curvature surfaces need a
  dense grid to avoid faceting artefacts in the toolpath.
- **Time estimate** is constant-feed only; add 5–15 % for real machine dynamics
  (acceleration ramps, MH 31e §1109).
- **Scallop height formula** assumes a ball-end mill on a locally flat surface.
  On convex/concave curved surfaces the actual scallop differs; treat this as a
  first-order estimate. Reference: Chuang & Yang (1995).
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
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Offset3DSpec:
    """Specification for a 3D parallel-offset surface-milling operation.

    All distances are in millimetres (G21 metric mode assumed).
    Feed rates are in mm/min.  RPM is spindle speed.

    Parameters
    ----------
    target_surface_points
        Sampled z(x,y) grid as a list of (x, y, z) tuples.
        Points need not be ordered but should form a regular or quasi-regular
        grid in XY.  At least 2 distinct X values and 2 distinct Y values are
        required for interpolation.
    tool_radius_mm
        Ball-end mill radius (mm).  Must be > 0.
    stepover_mm
        Lateral (Y-direction) spacing between successive raster passes (mm).
        Smaller stepover → smaller scallop height → better surface finish but
        longer cycle time.  Must be > 0 and ≤ 2 × tool_radius_mm.
    feed_mm_per_min
        Cutting feed rate (mm/min).  Must be > 0.
    spindle_rpm
        Spindle speed (RPM).  Must be > 0.
    rapid_z_mm
        Rapid traverse rate in Z (mm/min) used for time estimation only.
        Default 10 000 mm/min (typical VMC).
    """
    target_surface_points: List[Tuple[float, float, float]]
    tool_radius_mm: float
    stepover_mm: float
    feed_mm_per_min: float
    spindle_rpm: float
    rapid_z_mm: float = 10000.0

    def __post_init__(self):
        if len(self.target_surface_points) < 4:
            raise ValueError(
                "target_surface_points must have at least 4 points to define a surface"
            )
        xs = {p[0] for p in self.target_surface_points}
        ys = {p[1] for p in self.target_surface_points}
        if len(xs) < 2:
            raise ValueError("target_surface_points must have at least 2 distinct X values")
        if len(ys) < 2:
            raise ValueError("target_surface_points must have at least 2 distinct Y values")
        if self.tool_radius_mm <= 0:
            raise ValueError(
                f"tool_radius_mm must be > 0, got {self.tool_radius_mm!r}"
            )
        if self.stepover_mm <= 0:
            raise ValueError(
                f"stepover_mm must be > 0, got {self.stepover_mm!r}"
            )
        if self.stepover_mm > 2.0 * self.tool_radius_mm:
            raise ValueError(
                f"stepover_mm ({self.stepover_mm}) must be ≤ 2 × tool_radius_mm "
                f"({2.0 * self.tool_radius_mm}) — larger stepover leaves unmachined cusps"
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
class Offset3DResult:
    """Result from ``generate_offset_3d_path``.

    Attributes
    ----------
    gcode
        Complete G-code program (UTF-8, NIST RS-274/NGC §3.5).
    num_passes
        Number of raster passes.
    total_path_length_mm
        Total XY cutting path length in mm.
    max_scallop_height_mm
        Theoretical maximum scallop height: R - sqrt(R² - (stepover/2)²).
        Computed for a flat surface and ball-end mill (Chuang & Yang 1995).
    machining_time_s
        Estimated machining time in seconds (constant-feed only).
    honest_caveat
        Plain-English note on assumptions and limitations.
    """
    gcode: str
    num_passes: int
    total_path_length_mm: float
    max_scallop_height_mm: float
    machining_time_s: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float to NIST RS-274/NGC decimal notation (no trailing zeros).

    >>> _fmt(10.0)
    '10.0'
    >>> _fmt(-5.5)
    '-5.5'
    >>> _fmt(0.0)
    '0.0'
    """
    formatted = f"{v:.{decimals}f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
        if '.' not in formatted:
            formatted = formatted + '.0'
    return formatted


def _build_grid(
    points: List[Tuple[float, float, float]],
) -> tuple:
    """Build sorted unique X and Y arrays and a z-value lookup dict.

    Returns
    -------
    (x_sorted, y_sorted, z_dict)
        x_sorted : sorted list of unique X values
        y_sorted : sorted list of unique Y values
        z_dict   : dict[(x_idx, y_idx)] -> z  — z at each grid node
                   For scattered points, z at node (xi, yj) is the z of the
                   closest input point within 1e-9 of (x_sorted[xi], y_sorted[yj]).
    """
    xs_sorted = sorted({p[0] for p in points})
    ys_sorted = sorted({p[1] for p in points})

    # Build index maps
    x_idx = {x: i for i, x in enumerate(xs_sorted)}
    y_idx = {y: j for j, y in enumerate(ys_sorted)}

    # Populate z_dict: for each point, map nearest (xi, yj) node
    z_dict: dict = {}
    for px, py, pz in points:
        # Find closest x
        xi = min(range(len(xs_sorted)), key=lambda i: abs(xs_sorted[i] - px))
        yj = min(range(len(ys_sorted)), key=lambda j: abs(ys_sorted[j] - py))
        z_dict[(xi, yj)] = pz

    # Fill any missing grid nodes by nearest-neighbour in full point list
    for xi, x in enumerate(xs_sorted):
        for yj, y in enumerate(ys_sorted):
            if (xi, yj) not in z_dict:
                # Find nearest point
                best_z = min(points, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)[2]
                z_dict[(xi, yj)] = best_z

    return xs_sorted, ys_sorted, z_dict


def _bilinear_z(
    x: float,
    y: float,
    xs_sorted: list,
    ys_sorted: list,
    z_dict: dict,
) -> float:
    """Bilinear interpolation of z at (x, y).

    Clamps to grid boundary for out-of-range queries.
    """
    # Clamp X
    nx = len(xs_sorted)
    ny = len(ys_sorted)

    # Find bracket for x
    if x <= xs_sorted[0]:
        xi0, xi1 = 0, 1
        tx = 0.0
    elif x >= xs_sorted[-1]:
        xi0, xi1 = nx - 2, nx - 1
        tx = 1.0
    else:
        xi0 = 0
        for i in range(nx - 1):
            if xs_sorted[i] <= x <= xs_sorted[i + 1]:
                xi0 = i
                break
        xi1 = xi0 + 1
        dx = xs_sorted[xi1] - xs_sorted[xi0]
        tx = (x - xs_sorted[xi0]) / dx if dx > 0 else 0.0

    # Find bracket for y
    if y <= ys_sorted[0]:
        yj0, yj1 = 0, 1
        ty = 0.0
    elif y >= ys_sorted[-1]:
        yj0, yj1 = ny - 2, ny - 1
        ty = 1.0
    else:
        yj0 = 0
        for j in range(ny - 1):
            if ys_sorted[j] <= y <= ys_sorted[j + 1]:
                yj0 = j
                break
        yj1 = yj0 + 1
        dy = ys_sorted[yj1] - ys_sorted[yj0]
        ty = (y - ys_sorted[yj0]) / dy if dy > 0 else 0.0

    # Bilinear interpolation
    z00 = z_dict[(xi0, yj0)]
    z10 = z_dict[(xi1, yj0)]
    z01 = z_dict[(xi0, yj1)]
    z11 = z_dict[(xi1, yj1)]
    return (
        z00 * (1 - tx) * (1 - ty)
        + z10 * tx * (1 - ty)
        + z01 * (1 - tx) * ty
        + z11 * tx * ty
    )


def _scallop_height(tool_radius_mm: float, stepover_mm: float) -> float:
    """Theoretical scallop height for ball-end mill on a flat surface.

    h = R - sqrt(R² - (stepover/2)²)

    Reference: Chuang & Yang (1995) Intl J of Machine Tools 35(2):261–267.
    Also: Kruth & Klewais (1994) CIRP Annals 43(1):443–448.
    Also: Held & Klingenstein (1991) Computers & Graphics 15(3):333–341.

    Parameters
    ----------
    tool_radius_mm
        Ball-end mill radius R (mm).
    stepover_mm
        Pass-to-pass stepover ae (mm).  Must satisfy ae ≤ 2R.

    Returns
    -------
    float
        Scallop height in mm (positive; = 0 when stepover = 0).
    """
    ae_half = stepover_mm / 2.0
    discriminant = tool_radius_mm ** 2 - ae_half ** 2
    if discriminant < 0:
        raise ValueError(
            f"stepover_mm ({stepover_mm}) > 2 × tool_radius_mm ({tool_radius_mm}): "
            "tool passes do not overlap and scallop height equals ball radius."
        )
    return tool_radius_mm - math.sqrt(discriminant)


# ---------------------------------------------------------------------------
# Pass Y-positions
# ---------------------------------------------------------------------------

def _compute_pass_y_positions(
    y_min: float,
    y_max: float,
    stepover_mm: float,
) -> List[float]:
    """Generate Y-coordinate list for parallel raster passes.

    Starts at y_min, steps by stepover_mm, always includes y_max as the last
    pass (boundary guarantee per Held & Klingenstein 1991 §3.1).
    """
    if y_max <= y_min:
        return [y_min]

    span = y_max - y_min
    n_steps = math.ceil(span / stepover_mm)
    positions = []
    for i in range(n_steps):
        y = y_min + i * stepover_mm
        if y > y_max:
            break
        positions.append(y)

    # Always include the boundary
    if not positions or abs(positions[-1] - y_max) > 1e-9:
        positions.append(y_max)

    return positions


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

# X sample density for toolpath interpolation: one sample per mm of travel.
_X_SAMPLE_STEP_MM = 1.0


def generate_offset_3d_path(spec: Offset3DSpec) -> Offset3DResult:
    """Generate a 3D parallel-offset surface milling toolpath.

    Strategy
    --------
    1. Build a bilinear z(x,y) interpolator from ``spec.target_surface_points``.
    2. Determine the bounding box [x_min, x_max] × [y_min, y_max] of the grid.
    3. Generate parallel passes at Y positions separated by ``spec.stepover_mm``.
    4. For each pass at constant Y, sample z(x, Y) at 1 mm X increments and
       compute the tool-centre height as z(x,Y) + tool_radius (Z-axis offset).
    5. Emit NIST RS-274/NGC G-code (G21/G90/G94/M03/G00/G01/M05/M30).

    The toolpath is a zig-zag (alternating +X/-X directions per pass) to
    minimise rapid repositioning.

    Parameters
    ----------
    spec
        Offset3DSpec instance.

    Returns
    -------
    Offset3DResult

    Raises
    ------
    ValueError
        If spec parameters are invalid (see Offset3DSpec.__post_init__).
    """
    # ── Build interpolator ─────────────────────────────────────────────────
    xs_sorted, ys_sorted, z_dict = _build_grid(spec.target_surface_points)

    x_min = xs_sorted[0]
    x_max = xs_sorted[-1]
    y_min = ys_sorted[0]
    y_max = ys_sorted[-1]

    R = spec.tool_radius_mm

    # Rapid clearance plane: max surface z + tool_radius + 5 mm safety
    z_surface_max = max(z for _, _, z in spec.target_surface_points)
    z_rapid = z_surface_max + R + 5.0

    # ── Pass Y-positions ───────────────────────────────────────────────────
    y_positions = _compute_pass_y_positions(y_min, y_max, spec.stepover_mm)
    num_passes = len(y_positions)

    # ── X sample positions ─────────────────────────────────────────────────
    x_span = x_max - x_min
    n_x_samples = max(2, math.ceil(x_span / _X_SAMPLE_STEP_MM) + 1)
    x_samples = [x_min + i * (x_span / (n_x_samples - 1)) for i in range(n_x_samples)]

    # ── Scallop height ─────────────────────────────────────────────────────
    h_scallop = _scallop_height(R, spec.stepover_mm)

    # ── G-code header ─────────────────────────────────────────────────────
    lines: list[str] = []
    lines.append("%")
    lines.append(
        "(3D parallel-offset surface milling — Kerf CAM / "
        "MH 31e §1139 + Held & Klingenstein 1991)"
    )
    lines.append("(Generated by: kerf_cam.offset_3d_path.generate_offset_3d_path)")
    lines.append(
        f"(Bounding box: X{_fmt(x_min)}..{_fmt(x_max)}"
        f"  Y{_fmt(y_min)}..{_fmt(y_max)})"
    )
    lines.append(
        f"(Tool radius R={_fmt(R)} mm"
        f"  stepover={_fmt(spec.stepover_mm)} mm"
        f"  passes={num_passes})"
    )
    lines.append(
        f"(Max scallop height: R-sqrt(R²-(ae/2)²) = {_fmt(h_scallop, 6)} mm)"
    )
    lines.append(
        "(WARNING: 3-axis Z-axis-aligned offset only — no 5-axis tilt, "
        "no gouge checking)"
    )
    lines.append(
        "(WARNING: time estimate excludes acceleration ramps — "
        "add 5-15 % per MH 31e §1109)"
    )
    lines.append("G21  (metric mode)")
    lines.append("G90  (absolute distances)")
    lines.append("G94  (feed per minute)")
    lines.append("")
    lines.append(f"M03 S{int(spec.spindle_rpm)}  (spindle on CW)")
    lines.append(f"G00 Z{_fmt(z_rapid)}  (rapid to clearance plane)")
    lines.append("")

    total_path_length = 0.0

    for pass_idx, y in enumerate(y_positions):
        # Zig-zag: even passes go +X, odd passes go -X
        go_positive_x = (pass_idx % 2 == 0)

        # Build (x, z_tool) sequence for this pass
        xs_pass = x_samples if go_positive_x else list(reversed(x_samples))

        # First point
        x0 = xs_pass[0]
        z0_surf = _bilinear_z(x0, y, xs_sorted, ys_sorted, z_dict)
        z0_tool = z0_surf + R

        direction_label = "+X" if go_positive_x else "-X"
        lines.append(
            f"(Pass {pass_idx + 1}/{num_passes}:"
            f" Y={_fmt(y)}  {direction_label})"
        )

        # Rapid to entry position (XY), then Z plunge
        lines.append(
            f"G00 X{_fmt(x0)} Y{_fmt(y)}  (rapid to pass {pass_idx + 1} entry)"
        )
        lines.append(f"G00 Z{_fmt(z0_tool)}  (rapid to surface offset)")

        # Feed along surface
        prev_x = x0
        prev_z = z0_tool
        for xi in xs_pass[1:]:
            zi_surf = _bilinear_z(xi, y, xs_sorted, ys_sorted, z_dict)
            zi_tool = zi_surf + R
            seg_len = math.sqrt((xi - prev_x) ** 2 + (zi_tool - prev_z) ** 2)
            total_path_length += seg_len
            lines.append(
                f"G01 X{_fmt(xi)} Z{_fmt(zi_tool)} F{_fmt(spec.feed_mm_per_min)}"
            )
            prev_x = xi
            prev_z = zi_tool

        # Retract after pass
        lines.append(f"G00 Z{_fmt(z_rapid)}  (retract after pass {pass_idx + 1})")
        lines.append("")

    # ── Footer ─────────────────────────────────────────────────────────────
    lines.append("M05  (spindle off)")
    lines.append("M30  (program end)")
    lines.append("%")

    gcode = "\n".join(lines)

    # ── Machining time estimate ────────────────────────────────────────────
    # Cutting time: total path length at feed rate
    cutting_time_s = (total_path_length / spec.feed_mm_per_min) * 60.0

    # Rapid Z per pass: retract to clearance + rapid to next entry
    # Both at rapid_z_mm rate.  Approximate Z retract per pass:
    z_surface_mean = sum(z for _, _, z in spec.target_surface_points) / len(
        spec.target_surface_points
    )
    z_tool_mean = z_surface_mean + R
    rapid_retract_per_pass = z_rapid - z_tool_mean
    rapid_time_per_pass_s = max(0.0, (rapid_retract_per_pass / spec.rapid_z_mm) * 60.0)
    total_rapid_time_s = num_passes * rapid_time_per_pass_s * 2  # retract + descend

    machining_time_s = cutting_time_s + total_rapid_time_s

    # ── Honest caveat ──────────────────────────────────────────────────────
    honest_caveat = (
        "3D parallel-offset surface milling (3-axis Z-axis-aligned). "
        "Features NOT implemented: "
        "(1) 5-axis tool-axis tilt — the spindle is always vertical (+Z); "
        "steep surfaces (>45°) will receive slightly less than one tool_radius of "
        "offset due to the Z-normal approximation (potential micro-gouge on steep flanks, "
        "MH 31e §1139); "
        "(2) gouge checking — holder or spindle collision is NOT detected (use "
        "cam_verify_toolpath_collision for collision verification); "
        "(3) z-level contouring (waterline) passes — raster passes only; "
        "(4) adaptive/trochoidal clearing — use cam_adaptive_pocket or "
        "cam_trochoidal_slot for pockets; "
        "(5) arc-fitting post-processing — all moves emitted as G01 linear segments "
        "(no G02/G03 even on circular surface regions). "
        "Scallop height formula h = R - sqrt(R² - (ae/2)²) is for a flat surface and "
        "ball-end mill (Chuang & Yang 1995); actual scallop on curved surfaces differs. "
        "Time estimate uses constant feed rate (no acceleration ramps — add 5–15 % "
        "per MH 31e §1109). "
        "Bilinear interpolation used for z(x,y) — high-curvature surfaces need a "
        "dense input grid (recommended: ≤ tool_radius/2 grid spacing). "
        "Refs: MH 31e §1139 (3-axis surface offset); "
        "Held & Klingenstein (1991) Computers & Graphics 15(3):333–341 "
        "(parallel-offset raster strategy); "
        "Chuang & Yang (1995) Intl J Mach Tools 35(2):261–267 (scallop height); "
        "NIST RS-274/NGC §3.5 (G-code format)."
    )

    return Offset3DResult(
        gcode=gcode,
        num_passes=num_passes,
        total_path_length_mm=round(total_path_length, 6),
        max_scallop_height_mm=round(h_scallop, 9),
        machining_time_s=round(machining_time_s, 3),
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_offset_3d_path_spec = ToolSpec(
    name="cam_generate_offset_3d_path",
    description=(
        "Generate a 3D parallel-offset surface-milling G-code toolpath at a "
        "constant tool_radius offset from a target surface defined by a sampled "
        "z(x,y) grid. "
        "Implements the Z-axis-aligned 3-axis surface offset model from "
        "Machinery's Handbook 31e §1139 + Held & Klingenstein (1991). "
        "Raster (zig-zag parallel passes) strategy; bilinear z(x,y) interpolation; "
        "scallop height = R - sqrt(R² - (stepover/2)²) per Chuang & Yang (1995). "
        "Returns complete G-code, pass count, path length, max scallop height, "
        "estimated machining time, and honest caveats. "
        "LIMITATIONS: 3-axis Z-axis-aligned only (no 5-axis tilt); "
        "no gouge checking; raster passes only (no waterline/z-level contouring); "
        "G01 linear segments only (no arc fitting)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_surface_points": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": (
                    "Sampled z(x,y) grid as a list of [x, y, z] triples (mm). "
                    "Must have at least 4 points spanning at least 2 distinct X values "
                    "and 2 distinct Y values. Recommend grid spacing ≤ tool_radius/2."
                ),
            },
            "tool_radius_mm": {
                "type": "number",
                "description": "Ball-end mill radius in mm (must be > 0).",
            },
            "stepover_mm": {
                "type": "number",
                "description": (
                    "Pass-to-pass lateral spacing in mm (must be > 0 and ≤ 2×tool_radius_mm). "
                    "Smaller values → better surface finish but longer cycle time. "
                    "Typical: 0.3–0.5 × tool_diameter for finishing."
                ),
            },
            "feed_mm_per_min": {
                "type": "number",
                "description": "Cutting feed rate in mm/min.",
            },
            "spindle_rpm": {
                "type": "number",
                "description": "Spindle speed in RPM.",
            },
            "rapid_z_mm": {
                "type": "number",
                "description": (
                    "Rapid Z traverse rate in mm/min (used for time estimate only; "
                    "default 10000 mm/min)."
                ),
            },
        },
        "required": [
            "target_surface_points",
            "tool_radius_mm",
            "stepover_mm",
            "feed_mm_per_min",
            "spindle_rpm",
        ],
    },
)


@register(cam_generate_offset_3d_path_spec)
async def run_cam_generate_offset_3d_path(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required_fields = [
        "target_surface_points",
        "tool_radius_mm",
        "stepover_mm",
        "feed_mm_per_min",
        "spindle_rpm",
    ]
    for field_name in required_fields:
        if field_name not in a:
            return err_payload(f"missing required field: {field_name!r}", "BAD_ARGS")

    try:
        raw_pts = a["target_surface_points"]
        if not isinstance(raw_pts, list) or len(raw_pts) < 4:
            return err_payload(
                "target_surface_points must be a list of at least 4 [x,y,z] triples",
                "BAD_ARGS",
            )
        points = []
        for item in raw_pts:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                return err_payload(
                    "each surface point must be an [x, y, z] triple", "BAD_ARGS"
                )
            points.append((float(item[0]), float(item[1]), float(item[2])))

        spec = Offset3DSpec(
            target_surface_points=points,
            tool_radius_mm=float(a["tool_radius_mm"]),
            stepover_mm=float(a["stepover_mm"]),
            feed_mm_per_min=float(a["feed_mm_per_min"]),
            spindle_rpm=float(a["spindle_rpm"]),
            rapid_z_mm=float(a.get("rapid_z_mm", 10000.0)),
        )
        result = generate_offset_3d_path(spec)
    except (KeyError, TypeError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "gcode": result.gcode,
        "num_passes": result.num_passes,
        "total_path_length_mm": result.total_path_length_mm,
        "max_scallop_height_mm": result.max_scallop_height_mm,
        "machining_time_s": result.machining_time_s,
        "honest_caveat": result.honest_caveat,
    })
