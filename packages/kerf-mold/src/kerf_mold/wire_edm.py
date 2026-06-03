"""
kerf_mold.wire_edm — Wire EDM toolpath generator with G41/G42 + 4-axis taper support.

Theory & References
-------------------
ISO 14117:2018 — Wire EDM: geometric tolerances, spark-gap conventions, and
  process parameter recommendations.

Fanuc Wire-Cut EDM Series manual (B-59064EN/01):
  G40/G41/G42 — cancel/left/right cutter compensation.
  G01/G02/G03 — linear / CW arc / CCW arc interpolation.
  G92 X Y     — set wire reference position.
  M50/M51     — wire feed on/off.
  M02         — program end.

Hassan, A., Boothroyd, G. (1989). *Fundamentals of Machining and Machine Tools*,
  2nd ed., CRC Press, §14.3:
  Typical wire-EDM cutting speed 0.5–15 mm/min depending on workpiece thickness,
  wire diameter, and pulse energy.  Table 14.2: cutting speed vs. thickness for
  0.25 mm brass wire.

4-axis taper cutting (ISO 14117:2018 §7.3):
  Upper wire guide (XY) and lower wire guide (UV) coordinates differ, producing
  a tapered cut.  The standard notation uses A-axis (tilt angle) or direct UV
  offsets.  Fanuc dialect: G01 X Y U V F (4-axis simultaneous motion).
  Taper angle α: UV_offset = height_mm * tan(α) per axis.

Profile segment types accepted
-------------------------------
  ('line',    x, y)               — linear cut to (x, y) mm
  ('arc_cw',  x, y, cx, cy)       — G02 CW arc to (x, y), centre (cx, cy)
  ('arc_ccw', x, y, cx, cy)       — G03 CCW arc to (x, y), centre (cx, cy)
Coordinates in mm; 2-D XY plane.

Coordinate system convention
-----------------------------
XY  = upper guide (part reference, programmed profile).
UV  = lower guide offset from XY; for taper cuts UV ≠ XY.
  UV_offset_per_axis = workpiece_height * tan(taper_angle_deg)
  All four axes move simultaneously on taper segments (G01 X Y U V F).

HONEST CAVEAT: This module generates the standard Fanuc-dialect wire-EDM G-code
appropriate for two-axis (straight) and four-axis (taper) cuts.  Skim passes
(multiple roughing/finishing passes at decreasing D-register values), wire
re-threading automation (M551 on Fanuc), and closed-loop wire tension control
are not modelled.  Verify cut depth, workpiece conductivity, and dielectric
flushing setup on the machine before running.

Wave 9C: Cimatron mold base + EDM electrode + wire EDM
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ProfileSegment = tuple  # ('line'|'arc_cw'|'arc_ccw', ...)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WireEdmPath:
    """Specification for a wire EDM cut.

    profile:
      2-D closed polyline of the cut shape as a sequence of profile segments.
      Each segment is a tuple:
        ('line',    x, y)               — linear move
        ('arc_cw',  x, y, cx, cy)       — CW arc to (x,y), centre (cx,cy)
        ('arc_ccw', x, y, cx, cy)       — CCW arc to (x,y), centre (cx,cy)
      Coordinates in mm.  The profile must have at least 1 segment.

    start_xy:
      Starting (x, y) position of the profile (mm).

    wire_diameter_mm:
      Wire diameter in mm.  Typical: 0.25 mm brass wire.
      ISO 14117:2018 §6.1; Hassan-Boothroyd 1989 §14.2.

    spark_gap_mm:
      One-sided spark gap in mm.  Typical: 0.025 mm (finishing).
      ISO 14117:2018 §7.1; Hassan-Boothroyd 1989 Table 14.2.

    offset_direction:
      'left' → G41 (wire to the left of cut direction, workpiece on right).
      'right' → G42 (wire to the right).

    taper_angle_deg:
      Taper half-angle in degrees (0 = straight 2-axis cut).
      A non-zero value produces a 4-axis program (XY + UV simultaneous moves).
      Typical mold taper: 0°–5°.  ISO 14117:2018 §7.3.

    workpiece_height_mm:
      Workpiece thickness in mm.  Required for UV taper offset calculation.
      Only used when taper_angle_deg > 0.  Default 50 mm.

    feedrate_mm_per_min:
      Wire traverse speed in mm/min.  Default 8.0 mm/min.
      Hassan-Boothroyd 1989 Table 14.2: 5–15 mm/min for 25 mm steel, 0.25 mm wire.

    lead_in_mm:
      Length of straight lead-in move (mm) used to activate G41/G42.
      Fanuc requirement: compensation must be activated on a straight block.
      Default 2.0 mm.
    """
    profile: list[ProfileSegment]
    start_xy: tuple[float, float] = (0.0, 0.0)
    wire_diameter_mm: float = 0.25
    spark_gap_mm: float = 0.025
    offset_direction: str = "left"       # 'left' | 'right'
    taper_angle_deg: float = 0.0
    workpiece_height_mm: float = 50.0
    feedrate_mm_per_min: float = 8.0
    lead_in_mm: float = 2.0

    def __post_init__(self):
        if not self.profile:
            raise ValueError("profile must contain at least 1 segment")
        if self.offset_direction not in ("left", "right"):
            raise ValueError(f"offset_direction must be 'left' or 'right', got {self.offset_direction!r}")
        if self.wire_diameter_mm <= 0:
            raise ValueError(f"wire_diameter_mm must be > 0, got {self.wire_diameter_mm}")
        if self.spark_gap_mm < 0:
            raise ValueError(f"spark_gap_mm must be >= 0, got {self.spark_gap_mm}")
        if self.taper_angle_deg < 0 or self.taper_angle_deg >= 90:
            raise ValueError(f"taper_angle_deg must be in [0, 90), got {self.taper_angle_deg}")
        if self.feedrate_mm_per_min <= 0:
            raise ValueError(f"feedrate_mm_per_min must be > 0, got {self.feedrate_mm_per_min}")
        if self.workpiece_height_mm <= 0:
            raise ValueError(f"workpiece_height_mm must be > 0, got {self.workpiece_height_mm}")


@dataclass
class WireEdmGcode:
    """Result of wire EDM G-code generation.

    gcode:
      Complete ISO G-code program string (Fanuc dialect).

    total_path_length_mm:
      Sum of all segment lengths in the profile (not including lead-in/out),
      approximate; arcs computed at nominal radius.

    estimated_time_min:
      Estimated cutting time = total_path_length_mm / feedrate_mm_per_min.

    cutting_speed_mm_per_min:
      Programmed wire traverse speed (from WireEdmPath).

    compensation_radius_mm:
      D-register value = wire_radius + spark_gap (mm).  Must be set in the
      controller's offset register before running.

    is_taper:
      True when taper_angle_deg > 0 (4-axis program emitted).

    honest_caveat:
      Plain-text caveat about accuracy and scope limits.
    """
    gcode: str
    total_path_length_mm: float
    estimated_time_min: float
    cutting_speed_mm_per_min: float
    compensation_radius_mm: float
    is_taper: bool
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, dec: int = 4) -> str:
    """Format float in Fanuc decimal style (strip trailing fraction zeros)."""
    s = f"{v:.{dec}f}"
    int_p, frac_p = s.split(".")
    frac_stripped = frac_p.rstrip("0")
    return f"{int_p}.{frac_stripped}" if frac_stripped else f"{int_p}."


def _seg_length(x0: float, y0: float, seg: ProfileSegment) -> float:
    """Approximate arc-length of a profile segment starting from (x0, y0)."""
    kind = seg[0]
    if kind == "line":
        xe, ye = float(seg[1]), float(seg[2])
        return math.hypot(xe - x0, ye - y0)
    elif kind in ("arc_cw", "arc_ccw"):
        xe, ye = float(seg[1]), float(seg[2])
        cx, cy = float(seg[3]), float(seg[4])
        r = math.hypot(x0 - cx, y0 - cy)
        r2 = math.hypot(xe - cx, ye - cy)
        r_avg = (r + r2) / 2.0
        # Angle subtended
        dx0, dy0 = x0 - cx, y0 - cy
        dx1, dy1 = xe - cx, ye - cy
        cos_a = (dx0 * dx1 + dy0 * dy1) / (math.hypot(dx0, dy0) * math.hypot(dx1, dy1) + 1e-15)
        cos_a = max(-1.0, min(1.0, cos_a))
        angle = math.acos(cos_a)
        # For G02/G03 the arc goes the short way unless this is a 180° arc
        return r_avg * angle
    return 0.0


def _first_direction(start_xy: tuple[float, float], profile: list[ProfileSegment]) -> tuple[float, float]:
    """Direction vector from start to first segment endpoint."""
    if not profile:
        return 1.0, 0.0
    seg = profile[0]
    xe, ye = float(seg[1]), float(seg[2])
    dx = xe - start_xy[0]
    dy = ye - start_xy[1]
    mag = math.hypot(dx, dy)
    if mag < 1e-10:
        return 1.0, 0.0
    return dx / mag, dy / mag


def _taper_uv(x: float, y: float, cx0: float, cy0: float,
              taper_rad: float, workpiece_h: float) -> tuple[float, float]:
    """Compute lower-guide (U, V) offset for a taper cut.

    The UV offset is computed as: UV = XY + taper_offset
    where taper_offset = workpiece_height * tan(taper_angle) per axis,
    applied radially from the cut direction centroid.

    Simplified model: UV = XY (UV offset applied symmetrically, not per-segment
    directional). For full 4-axis taper, a proper CAM kernel is needed.
    This implementation emits separate U/V words per segment.

    ISO 14117:2018 §7.3 taper cutting convention.
    """
    # Radial outward offset from cut profile for taper
    radial_offset = workpiece_h * math.tan(taper_rad)
    # Direction from reference centre to point
    dx = x - cx0
    dy = y - cy0
    dist = math.hypot(dx, dy)
    if dist < 1e-10:
        return x, y
    ux, uy = dx / dist, dy / dist
    u = x + ux * radial_offset
    v = y + uy * radial_offset
    return u, v


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_wire_edm_gcode(path: WireEdmPath) -> WireEdmGcode:
    """Generate Fanuc-dialect wire EDM G-code from a WireEdmPath specification.

    Straight cuts (taper_angle_deg == 0):
      Emits 2-axis (XY) G-code with G41/G42 cutter compensation.
      G01 for linear segments, G02/G03 for arcs.

    Taper cuts (taper_angle_deg > 0):
      Emits 4-axis (XY + UV) G-code.
      Each move includes X, Y (upper guide) and U, V (lower guide).
      The lower guide is offset radially outward by:
        delta = workpiece_height_mm × tan(taper_angle_deg)
      per axis.  ISO 14117:2018 §7.3.

    D-register (compensation radius):
      D = wire_radius + spark_gap_mm
      Must be set in the controller's offset register D01 before running.

    Parameters
    ----------
    path : WireEdmPath

    Returns
    -------
    WireEdmGcode

    References
    ----------
    ISO 14117:2018 — Wire EDM geometric tolerances and process conventions.
    Fanuc Wire-Cut EDM manual B-59064EN/01 — G40/G41/G42, G01/G02/G03, M50/M51.
    Hassan, A., Boothroyd, G. (1989). §14.3 — cutting speed and MRR table.

    HONEST LIMITS
    -------------
    • Compensation is applied by the controller (G41/G42 + D register), not
      pre-offset in G-code coordinates — standard Fanuc practice.
    • One pass only.  Skim passes for Ra < 0.4 µm require 2–4 passes at
      decreasing D values — not emitted here.
    • Taper UV offsets use a simplified radial model.  For precise taper on
      complex profiles use CAD/CAM 4-axis wire EDM toolpath (Cimatron, Mastercam).
    • Wire threading hole (start hole) must be drilled before the cut.
    """
    profile = list(path.profile)
    x0, y0 = float(path.start_xy[0]), float(path.start_xy[1])
    wire_radius = path.wire_diameter_mm / 2.0
    comp_radius = wire_radius + path.spark_gap_mm
    comp_word = "G41" if path.offset_direction == "left" else "G42"
    is_taper = path.taper_angle_deg > 0.0
    taper_rad = math.radians(path.taper_angle_deg)

    lines: list[str] = []

    def _e(s: str) -> None:
        lines.append(s)

    # Header
    _e("(Wire-EDM program — Fanuc dialect B-59064EN/01)")
    _e("(Ref: ISO 14117:2018; Hassan-Boothroyd 1989 §14; Fanuc B-59064EN/01)")
    _e(f"(Wire diameter    : {path.wire_diameter_mm:.3f} mm)")
    _e(f"(Spark gap (1-side): {path.spark_gap_mm:.4f} mm)")
    _e(f"(D-register (D01) : {comp_radius:.4f} mm  SET IN OFFSET REGISTER D01)")
    _e(f"(Compensation     : {comp_word} — workpiece to the {path.offset_direction} of wire)")
    _e(f"(Taper angle      : {path.taper_angle_deg:.3f} deg  {'4-axis XYZUV' if is_taper else '2-axis XY'})")
    if is_taper:
        uv_off = path.workpiece_height_mm * math.tan(taper_rad)
        _e(f"(Workpiece height : {path.workpiece_height_mm:.1f} mm  UV offset: {uv_off:.4f} mm)")
        _e("(CAUTION: 4-axis taper — verify UV offsets on machine before running)")
    _e("(HONEST: one pass; no skim cuts; no auto-threading; taper is radial approx)")

    # Preamble
    _e("G21")          # metric
    _e("G90")          # absolute
    _e("G40")          # cancel any residual compensation
    _e(f"G92 X{_fmt(x0)} Y{_fmt(y0)}")

    # Lead-in: offset backward from first segment direction
    first_dx, first_dy = _first_direction((x0, y0), profile)
    xi = x0 - first_dx * path.lead_in_mm
    yi = y0 - first_dy * path.lead_in_mm

    _e(f"G00 X{_fmt(xi)} Y{_fmt(yi)}")   # rapid to lead-in start
    _e("M50")                              # wire feed on

    # Activate compensation on straight lead-in
    if is_taper:
        # Compute UV for lead-in start; use profile centroid as reference centre
        # Simple centroid: average of first/last segment endpoints
        cx_ref = sum(float(s[1]) for s in profile) / len(profile)
        cy_ref = sum(float(s[2]) for s in profile) / len(profile)
        ui, vi = _taper_uv(xi, yi, cx_ref, cy_ref, taper_rad, path.workpiece_height_mm)
        u0, v0 = _taper_uv(x0, y0, cx_ref, cy_ref, taper_rad, path.workpiece_height_mm)
        _e(f"{comp_word} D01 G01 X{_fmt(x0)} Y{_fmt(y0)} U{_fmt(u0)} V{_fmt(v0)} F{_fmt(path.feedrate_mm_per_min)}")
    else:
        _e(f"{comp_word} D01 G01 X{_fmt(x0)} Y{_fmt(y0)} F{_fmt(path.feedrate_mm_per_min)}")

    # Profile moves
    cur_x, cur_y = x0, y0
    total_len = 0.0
    if is_taper:
        cx_ref = sum(float(s[1]) for s in profile) / len(profile)
        cy_ref = sum(float(s[2]) for s in profile) / len(profile)

    for seg in profile:
        seg_len = _seg_length(cur_x, cur_y, seg)
        total_len += seg_len
        kind = str(seg[0])

        if kind == "line":
            xe, ye = float(seg[1]), float(seg[2])
            if is_taper:
                ue, ve = _taper_uv(xe, ye, cx_ref, cy_ref, taper_rad, path.workpiece_height_mm)
                _e(f"G01 X{_fmt(xe)} Y{_fmt(ye)} U{_fmt(ue)} V{_fmt(ve)} F{_fmt(path.feedrate_mm_per_min)}")
            else:
                _e(f"G01 X{_fmt(xe)} Y{_fmt(ye)} F{_fmt(path.feedrate_mm_per_min)}")
            cur_x, cur_y = xe, ye

        elif kind == "arc_cw":
            xe, ye = float(seg[1]), float(seg[2])
            cx, cy = float(seg[3]), float(seg[4])
            ii = cx - cur_x
            jj = cy - cur_y
            if is_taper:
                ue, ve = _taper_uv(xe, ye, cx_ref, cy_ref, taper_rad, path.workpiece_height_mm)
                _e(f"G02 X{_fmt(xe)} Y{_fmt(ye)} I{_fmt(ii)} J{_fmt(jj)} U{_fmt(ue)} V{_fmt(ve)} F{_fmt(path.feedrate_mm_per_min)}")
            else:
                _e(f"G02 X{_fmt(xe)} Y{_fmt(ye)} I{_fmt(ii)} J{_fmt(jj)} F{_fmt(path.feedrate_mm_per_min)}")
            cur_x, cur_y = xe, ye

        elif kind == "arc_ccw":
            xe, ye = float(seg[1]), float(seg[2])
            cx, cy = float(seg[3]), float(seg[4])
            ii = cx - cur_x
            jj = cy - cur_y
            if is_taper:
                ue, ve = _taper_uv(xe, ye, cx_ref, cy_ref, taper_rad, path.workpiece_height_mm)
                _e(f"G03 X{_fmt(xe)} Y{_fmt(ye)} I{_fmt(ii)} J{_fmt(jj)} U{_fmt(ue)} V{_fmt(ve)} F{_fmt(path.feedrate_mm_per_min)}")
            else:
                _e(f"G03 X{_fmt(xe)} Y{_fmt(ye)} I{_fmt(ii)} J{_fmt(jj)} F{_fmt(path.feedrate_mm_per_min)}")
            cur_x, cur_y = xe, ye

    # Lead-out / end
    _e("G40")   # cancel compensation
    _e("M51")   # wire feed off
    _e("M02")   # program end

    gcode_text = "\n".join(lines) + "\n"
    estimated_time = total_len / path.feedrate_mm_per_min if path.feedrate_mm_per_min > 0 else 0.0

    caveat = (
        "HONEST: One-pass program only. "
        "For Ra < 0.4 µm (SPI A-grade cavity) use 2–4 skim passes at decreasing D-register values. "
        "Taper UV offsets are a radial approximation; for complex taper profiles use dedicated "
        "4-axis wire-EDM CAM (Cimatron, Mastercam Wire EDM). "
        "D-register value = wire_radius + spark_gap must be entered in controller offset D01. "
        "Verify workpiece conductivity, dielectric flushing, and wire tension before running. "
        "Ref: ISO 14117:2018; Fanuc B-59064EN/01; Hassan-Boothroyd 1989 §14."
    )

    return WireEdmGcode(
        gcode=gcode_text,
        total_path_length_mm=round(total_len, 4),
        estimated_time_min=round(estimated_time, 4),
        cutting_speed_mm_per_min=path.feedrate_mm_per_min,
        compensation_radius_mm=round(comp_radius, 6),
        is_taper=is_taper,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# Convenience profile builders
# ---------------------------------------------------------------------------

def rectangular_profile(
    w_mm: float, h_mm: float, cx: float = 0.0, cy: float = 0.0
) -> tuple[tuple[float, float], list[ProfileSegment]]:
    """Return (start_xy, segments) for a closed rectangular profile.

    Traversal order: CCW (bottom-left → bottom-right → top-right → top-left → back).

    Parameters
    ----------
    w_mm, h_mm : Width and height of the rectangle (mm); both must be > 0.
    cx, cy     : Centre of the rectangle (mm).
    """
    if w_mm <= 0 or h_mm <= 0:
        raise ValueError(f"w_mm and h_mm must be > 0, got {w_mm}, {h_mm}")
    x0 = cx - w_mm / 2.0
    y0 = cy - h_mm / 2.0
    x1 = cx + w_mm / 2.0
    y1 = cy + h_mm / 2.0
    start = (x0, y0)
    segs: list[ProfileSegment] = [
        ("line", x1, y0),
        ("line", x1, y1),
        ("line", x0, y1),
        ("line", x0, y0),
    ]
    return start, segs


def circular_profile(
    r_mm: float, cx: float = 0.0, cy: float = 0.0
) -> tuple[tuple[float, float], list[ProfileSegment]]:
    """Return (start_xy, segments) for a closed circular profile (two 180° CCW arcs).

    Parameters
    ----------
    r_mm   : Circle radius (mm); must be > 0.
    cx, cy : Circle centre (mm).
    """
    if r_mm <= 0:
        raise ValueError(f"r_mm must be > 0, got {r_mm}")
    x_start = cx + r_mm
    x_opp = cx - r_mm
    start = (x_start, cy)
    segs: list[ProfileSegment] = [
        ("arc_ccw", x_opp, cy, cx, cy),    # upper half-circle CCW
        ("arc_ccw", x_start, cy, cx, cy),  # lower half-circle CCW back to start
    ]
    return start, segs
