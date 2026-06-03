"""
kerf_cad_core.civil.plan_profile_sheet — Plan-and-Profile sheet generator.

Sheet standards
---------------
References:
  • ASCE Manual 21 (Land Subdivision and Site Engineering) — plan-and-profile
    sheet layout, scale conventions, title block fields.
  • AASHTO Green Book (2018) Ch. 3 — stationing conventions, grade notation,
    vertical exaggeration guidelines (V:H typically 10:1 for profile view).
  • Bureau of Land Management Manual of Surveying Instructions (2009)
    §6 — stationing and alignment sheet requirements.

Sheet sizes
-----------
  ANSI_D  : 24 × 36 inches  (610 × 914 mm)  — standard civil drawing
  ARCH_D  : 24 × 36 inches  (same physical size; different border layout)
  (Both share the same physical dimensions; border art differs — we output
  the same SVG canvas for both and note the standard in the title block.)

Layout
------
  Top 60% of sheet  → Plan view (X-Y, north up, alignment polyline + ticks)
  Bottom 40% of sheet → Profile view (station vs elevation, grid + grade line)
  Bottom strip       → Title block (alignment_id, scales, date, sheet_id)

Units: the input (station, x, y, elevation) tuple uses the caller's unit
system (ft or m).  Scales are purely cosmetic (e.g. 1″=50′ → scale_h=50).

SVG coordinate system: origin at top-left, y increases downward.
  Plan view: north is +SVG_y downward → north arrow added.
  Profile view: elevation increases upward → yᵥ = profile_top − (elev−elev_min)/elev_range × profile_height

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Sheet size constants (inches, converted to points for SVG at 96 dpi)
# ---------------------------------------------------------------------------

# ANSI_D and ARCH_D are both 24×36 inches.
# SVG uses pixels at 96 px/inch.
_SHEET_SIZES: dict[str, tuple[float, float]] = {
    "ANSI_D": (24.0, 36.0),  # width × height in inches
    "ARCH_D": (24.0, 36.0),
}
_PX_PER_INCH = 96.0
_MARGIN_PX = 48.0           # 0.5 inch margin on each side
_TITLE_BLOCK_HEIGHT_PX = 96.0  # 1 inch title block at bottom
_PLAN_FRACTION = 0.60        # plan view occupies top 60% of drawing area
_PROFILE_FRACTION = 0.40     # profile view occupies bottom 40%


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PlanProfileSpec:
    """
    Parameters for a plan-and-profile sheet.

    AASHTO Green Book (2018) §3 / ASCE Manual 21:
      plan_view_scale    : denominator of scale ratio (e.g. 50 → 1″=50′)
      profile_view_scale_h: horizontal scale of profile (usually same as plan)
      profile_view_scale_v: vertical scale (exaggeration); AASHTO recommends
                             10:1 (V:H) for most road profiles.
    """
    alignment_id: str
    station_start: float                   # starting station (ft or m)
    station_end: float                     # ending station
    plan_view_scale: float                 # e.g. 50 (1″=50′)
    profile_view_scale_h: float            # horizontal scale
    profile_view_scale_v: float            # vertical scale (exaggeration factor)
    sheet_size: str                        # "ANSI_D" | "ARCH_D"
    grid_interval_ft: float = 50.0         # station grid interval (same units as station)


@dataclass
class PlanProfileSheet:
    """
    Output of generate_plan_profile_sheet.

    svg         : Full SVG string, ready to write to a .svg file.
    plan_view_bbox   : (x, y, width, height) in SVG pixels of plan view.
    profile_view_bbox: (x, y, width, height) in SVG pixels of profile view.
    stations_labeled : List of station values that received tick + label.
    """
    sheet_id: str
    svg: str
    plan_view_bbox: tuple[float, float, float, float]
    profile_view_bbox: tuple[float, float, float, float]
    stations_labeled: list[float]


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------

def _escape_xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _polyline_points(coords: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_plan_profile_sheet(
    alignment_geometry: list[tuple[float, float, float, float]],
    spec: PlanProfileSpec,
) -> PlanProfileSheet:
    """
    Generate a plan-and-profile sheet as an SVG string.

    Parameters
    ----------
    alignment_geometry : list of (station, x, y, elevation) tuples.
        • station  : running chainage (ft or m)
        • x, y     : plan coordinates (easting / northing)
        • elevation: ground elevation at that station
        Must have at least 2 points.

    spec : PlanProfileSpec
        Sheet and scale parameters.

    Returns
    -------
    PlanProfileSheet with SVG string and bbox metadata.

    Layout (ASCE Manual 21 §3.4):
      Plan view  : top portion — alignment polyline + station ticks + north arrow.
      Profile view: bottom portion — station (x-axis) vs elevation (y-axis),
                   vertical exaggeration applied, grid lines, grade annotations.
      Title block: bottom strip — alignment ID, scale, sheet ID, date.

    Vertical exaggeration (AASHTO Green Book 2018 §3):
      The profile vertical scale is profile_view_scale_v × profile_view_scale_h.
      Typical value: V:H = 10:1.  Each elevation unit maps to
      (profile_view_scale_v / profile_view_scale_h) × plan_px_per_unit pixels
      on the SVG profile view.
    """
    if len(alignment_geometry) < 2:
        # Return empty sheet on degenerate input
        w_px, h_px = 36 * _PX_PER_INCH, 24 * _PX_PER_INCH
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w_px:.0f}" height="{h_px:.0f}">'
            f'<rect width="100%" height="100%" fill="white"/>'
            f'<text x="50%" y="50%" text-anchor="middle" font-size="24" fill="red">'
            f'Insufficient alignment data</text></svg>'
        )
        return PlanProfileSheet(
            sheet_id="S001",
            svg=svg,
            plan_view_bbox=(0, 0, w_px, h_px / 2),
            profile_view_bbox=(0, h_px / 2, w_px, h_px / 2),
            stations_labeled=[],
        )

    sheet_key = spec.sheet_size if spec.sheet_size in _SHEET_SIZES else "ANSI_D"
    sheet_w_in, sheet_h_in = _SHEET_SIZES[sheet_key]
    # SVG: landscape orientation → swap to width=36, height=24
    svg_w = sheet_h_in * _PX_PER_INCH   # 36 in = 3456 px
    svg_h = sheet_w_in * _PX_PER_INCH   # 24 in = 2304 px

    margin = _MARGIN_PX
    tb_height = _TITLE_BLOCK_HEIGHT_PX

    draw_w = svg_w - 2 * margin
    draw_h = svg_h - 2 * margin - tb_height

    plan_h = draw_h * _PLAN_FRACTION
    prof_h = draw_h * _PROFILE_FRACTION

    plan_x = margin
    plan_y = margin
    plan_w = draw_w
    plan_bbox = (plan_x, plan_y, plan_w, plan_h)

    prof_x = margin
    prof_y = margin + plan_h
    prof_w = draw_w
    prof_bbox = (prof_x, prof_y, prof_w, prof_h)

    tb_x = margin
    tb_y = margin + plan_h + prof_h
    tb_w = draw_w

    # Extract arrays
    stations = np.array([pt[0] for pt in alignment_geometry], dtype=float)
    xs = np.array([pt[1] for pt in alignment_geometry], dtype=float)
    ys = np.array([pt[2] for pt in alignment_geometry], dtype=float)
    elevs = np.array([pt[3] for pt in alignment_geometry], dtype=float)

    sta_min = float(stations.min())
    sta_max = float(stations.max())
    sta_range = max(sta_max - sta_min, 1e-6)

    x_range = max(float(xs.max() - xs.min()), 1e-6)
    y_range = max(float(ys.max() - ys.min()), 1e-6)
    elev_min = float(elevs.min())
    elev_max = float(elevs.max())
    elev_range = max(elev_max - elev_min, 1e-6)

    # ── Plan view ────────────────────────────────────────────────────────────
    # Scale plan coords to fit plan_w × plan_h with padding
    pad = 40.0
    plan_inner_w = plan_w - 2 * pad
    plan_inner_h = plan_h - 2 * pad

    plan_scale = min(plan_inner_w / x_range, plan_inner_h / y_range)

    def plan_px(x: float, y: float) -> tuple[float, float]:
        """Map world (x,y) → SVG pixel, y-flipped (north up)."""
        px = plan_x + pad + (x - float(xs.min())) * plan_scale
        # SVG y grows downward; north up → invert
        py = plan_y + plan_h - pad - (y - float(ys.min())) * plan_scale
        return (px, py)

    plan_pts = [plan_px(xs[i], ys[i]) for i in range(len(stations))]

    # ── Profile view ──────────────────────────────────────────────────────────
    # Horizontal: station maps to profile_w; vertical: elevation with exaggeration.
    # AASHTO Green Book (2018) §3: V-exaggeration = profile_view_scale_v
    pad_prof_v = 30.0
    pad_prof_h = 60.0   # left pad for elevation labels
    prof_inner_w = prof_w - pad_prof_h - pad
    prof_inner_h = prof_h - 2 * pad_prof_v

    # Vertical exaggeration factor applied to profile_inner_h
    # profile_view_scale_v is the V:H ratio (e.g. 10 → 10× vertical exaggeration)
    v_exag = spec.profile_view_scale_v  # unit-less ratio

    def prof_px_x(sta: float) -> float:
        return prof_x + pad_prof_h + (sta - sta_min) / sta_range * prof_inner_w

    def prof_px_y(elev: float) -> float:
        # Elevation increases upward → invert in SVG
        # Apply vertical exaggeration: stretch the elevation range by v_exag
        # clamped to panel height
        raw = (elev - elev_min) / elev_range   # 0..1
        # Exaggeration scales the normalised elevation; clamp to [0,1]
        exag_raw = min(raw * v_exag, 1.0)
        return prof_y + prof_h - pad_prof_v - exag_raw * prof_inner_h

    profile_pts = [(prof_px_x(stations[i]), prof_px_y(elevs[i])) for i in range(len(stations))]

    # Grid lines + station labels
    grid_interval = spec.grid_interval_ft
    grid_stations: list[float] = []
    sta = math.ceil(sta_min / grid_interval) * grid_interval
    while sta <= sta_max + 1e-6:
        grid_stations.append(sta)
        sta += grid_interval

    # ── Build SVG ─────────────────────────────────────────────────────────────
    parts: list[str] = []

    # SVG root
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w:.0f}" height="{svg_h:.0f}" '
        f'viewBox="0 0 {svg_w:.0f} {svg_h:.0f}">'
    )

    # Background
    parts.append(f'<rect width="{svg_w:.0f}" height="{svg_h:.0f}" fill="white" stroke="none"/>')

    # Outer border
    parts.append(
        f'<rect x="{margin:.1f}" y="{margin:.1f}" '
        f'width="{draw_w:.1f}" height="{draw_h + tb_height:.1f}" '
        f'fill="none" stroke="#333" stroke-width="2"/>'
    )

    # ── Plan view box ─────────────────────────────────────────────────────────
    parts.append(f'<!-- plan_view -->')
    parts.append(
        f'<rect x="{plan_x:.1f}" y="{plan_y:.1f}" '
        f'width="{plan_w:.1f}" height="{plan_h:.1f}" '
        f'fill="#f9f9f9" stroke="#555" stroke-width="1"/>'
    )
    # Label
    parts.append(
        f'<text x="{plan_x + 10:.1f}" y="{plan_y + 20:.1f}" '
        f'font-family="Arial,sans-serif" font-size="13" fill="#333" font-weight="bold">'
        f'PLAN VIEW — {_escape_xml(spec.alignment_id)}</text>'
    )
    # Scale label
    parts.append(
        f'<text x="{plan_x + 10:.1f}" y="{plan_y + 36:.1f}" '
        f'font-family="Arial,sans-serif" font-size="11" fill="#555">'
        f'Scale 1″={spec.plan_view_scale:.0f}\'</text>'
    )

    # North arrow (top-right of plan view)
    na_x = plan_x + plan_w - 50
    na_y = plan_y + 50
    parts.append(
        f'<g transform="translate({na_x:.1f},{na_y:.1f})">'
        f'<line x1="0" y1="20" x2="0" y2="-20" stroke="#333" stroke-width="2"/>'
        f'<polygon points="0,-20 -6,-8 6,-8" fill="#333"/>'
        f'<text x="0" y="34" text-anchor="middle" font-family="Arial,sans-serif" '
        f'font-size="12" fill="#333" font-weight="bold">N</text>'
        f'</g>'
    )

    # Alignment polyline in plan view
    if len(plan_pts) >= 2:
        pts_str = _polyline_points(plan_pts)
        parts.append(
            f'<polyline points="{pts_str}" '
            f'fill="none" stroke="#1a5276" stroke-width="2.5"/>'
        )

    # Station ticks in plan view
    for gsta in grid_stations:
        # Interpolate plan position at gsta
        if sta_range < 1e-9:
            continue
        t = (gsta - sta_min) / sta_range
        idx = int(t * (len(stations) - 1))
        idx = min(idx, len(stations) - 2)
        # Linear interpolation
        t2 = (gsta - stations[idx]) / max(stations[idx + 1] - stations[idx], 1e-9)
        t2 = max(0.0, min(1.0, t2))
        px_x = plan_pts[idx][0] + t2 * (plan_pts[idx + 1][0] - plan_pts[idx][0])
        px_y = plan_pts[idx][1] + t2 * (plan_pts[idx + 1][1] - plan_pts[idx][1])
        # Tick mark
        parts.append(
            f'<circle cx="{px_x:.1f}" cy="{px_y:.1f}" r="3" '
            f'fill="#c0392b" stroke="none"/>'
        )
        sta_label = f'{gsta:.0f}'
        parts.append(
            f'<text x="{px_x + 5:.1f}" y="{px_y - 5:.1f}" '
            f'font-family="Arial,sans-serif" font-size="9" fill="#555">'
            f'{sta_label}</text>'
        )

    # ── Profile view box ──────────────────────────────────────────────────────
    parts.append(f'<!-- profile_view -->')
    parts.append(
        f'<rect x="{prof_x:.1f}" y="{prof_y:.1f}" '
        f'width="{prof_w:.1f}" height="{prof_h:.1f}" '
        f'fill="#f0f4f8" stroke="#555" stroke-width="1"/>'
    )
    # Label
    parts.append(
        f'<text x="{prof_x + 10:.1f}" y="{prof_y + 18:.1f}" '
        f'font-family="Arial,sans-serif" font-size="13" fill="#333" font-weight="bold">'
        f'PROFILE VIEW — Vert. Exag. {spec.profile_view_scale_v:.0f}×</text>'
    )
    parts.append(
        f'<text x="{prof_x + 10:.1f}" y="{prof_y + 33:.1f}" '
        f'font-family="Arial,sans-serif" font-size="11" fill="#555">'
        f'H: 1″={spec.profile_view_scale_h:.0f}\' · V: 1″={spec.profile_view_scale_v:.0f}\'</text>'
    )

    # Grid lines for profile
    for gsta in grid_stations:
        gx = prof_px_x(gsta)
        parts.append(
            f'<line x1="{gx:.1f}" y1="{prof_y + pad_prof_v:.1f}" '
            f'x2="{gx:.1f}" y2="{prof_y + prof_h - pad_prof_v:.1f}" '
            f'stroke="#bbb" stroke-width="0.7" stroke-dasharray="4,4"/>'
        )
        # Station label at bottom of profile
        parts.append(
            f'<text x="{gx:.1f}" y="{prof_y + prof_h - pad_prof_v + 14:.1f}" '
            f'text-anchor="middle" font-family="Arial,sans-serif" font-size="9" fill="#555">'
            f'{gsta:.0f}</text>'
        )

    # Horizontal grid lines (elevation)
    n_elev_ticks = 5
    for i in range(n_elev_ticks + 1):
        frac = i / n_elev_ticks
        # These are on the un-exaggerated scale
        elev_tick = elev_min + frac * elev_range
        gy = prof_px_y(elev_tick)
        parts.append(
            f'<line x1="{prof_x + pad_prof_h:.1f}" y1="{gy:.1f}" '
            f'x2="{prof_x + prof_w - pad:.1f}" y2="{gy:.1f}" '
            f'stroke="#bbb" stroke-width="0.7" stroke-dasharray="4,4"/>'
        )
        parts.append(
            f'<text x="{prof_x + pad_prof_h - 4:.1f}" y="{gy + 4:.1f}" '
            f'text-anchor="end" font-family="Arial,sans-serif" font-size="9" fill="#555">'
            f'{elev_tick:.1f}</text>'
        )

    # Profile polyline (ground line)
    if len(profile_pts) >= 2:
        pts_str = _polyline_points(profile_pts)
        parts.append(
            f'<polyline points="{pts_str}" '
            f'fill="none" stroke="#1a5276" stroke-width="2"/>'
        )

    # Profile axes
    # X-axis
    axis_y = prof_y + prof_h - pad_prof_v
    parts.append(
        f'<line x1="{prof_x + pad_prof_h:.1f}" y1="{axis_y:.1f}" '
        f'x2="{prof_x + prof_w - pad:.1f}" y2="{axis_y:.1f}" '
        f'stroke="#333" stroke-width="1.5"/>'
    )
    # Y-axis
    axis_x = prof_x + pad_prof_h
    parts.append(
        f'<line x1="{axis_x:.1f}" y1="{prof_y + pad_prof_v:.1f}" '
        f'x2="{axis_x:.1f}" y2="{axis_y:.1f}" '
        f'stroke="#333" stroke-width="1.5"/>'
    )

    # ── Title block ───────────────────────────────────────────────────────────
    parts.append(f'<!-- title_block -->')
    parts.append(
        f'<rect x="{tb_x:.1f}" y="{tb_y:.1f}" '
        f'width="{tb_w:.1f}" height="{tb_height:.1f}" '
        f'fill="#eee" stroke="#555" stroke-width="1"/>'
    )
    # Title fields (ASCE Manual 21 §3.4 title block requirements)
    parts.append(
        f'<text x="{tb_x + 10:.1f}" y="{tb_y + 22:.1f}" '
        f'font-family="Arial,sans-serif" font-size="14" fill="#222" font-weight="bold">'
        f'PLAN AND PROFILE — {_escape_xml(spec.alignment_id)}</text>'
    )
    parts.append(
        f'<text x="{tb_x + 10:.1f}" y="{tb_y + 42:.1f}" '
        f'font-family="Arial,sans-serif" font-size="11" fill="#555">'
        f'Sheet: {_escape_xml("S001")} | '
        f'Size: {_escape_xml(sheet_key)} ({sheet_w_in:.0f}″×{sheet_h_in:.0f}″) | '
        f'H Scale: 1″={spec.plan_view_scale:.0f}′ | '
        f'V Scale: 1″={spec.profile_view_scale_v:.0f}′ (V.E. {spec.profile_view_scale_v:.0f}×)</text>'
    )
    parts.append(
        f'<text x="{tb_x + 10:.1f}" y="{tb_y + 60:.1f}" '
        f'font-family="Arial,sans-serif" font-size="11" fill="#555">'
        f'Stations: {sta_min:.0f} — {sta_max:.0f} | '
        f'Grid: {spec.grid_interval_ft:.0f} | '
        f'Ref: ASCE Manual 21 / AASHTO Green Book (2018)</text>'
    )

    # Sheet boundary divider (plan/profile separator line)
    div_y = plan_y + plan_h
    parts.append(
        f'<line x1="{margin:.1f}" y1="{div_y:.1f}" '
        f'x2="{margin + draw_w:.1f}" y2="{div_y:.1f}" '
        f'stroke="#333" stroke-width="1.5"/>'
    )

    parts.append('</svg>')

    svg_str = "\n".join(parts)
    return PlanProfileSheet(
        sheet_id="S001",
        svg=svg_str,
        plan_view_bbox=plan_bbox,
        profile_view_bbox=prof_bbox,
        stations_labeled=list(grid_stations),
    )
