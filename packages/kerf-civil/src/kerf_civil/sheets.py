"""
kerf_civil.sheets — Automated plan-and-profile sheet production engine.

Generates a JSON sheet set that fully describes plan+profile sheets for a
horizontal/vertical alignment, following AASHTO, MUTCD, and DOT standard
plan-set conventions:

  • Sheet framing — sheet boundaries at the plan scale; overlap/match lines
  • Plan view    — station ticks at the specified grid interval, north arrow,
                  scale bar, plan-view alignment centreline geometry
  • Profile band — existing ground and proposed grade profiles at the profile
                  scale; full-station vertical grid lines; grade labels
  • Match lines  — station-aligned vertical cut lines with "Sta. XXXX+XX →"
                  labels for continuation sheets
  • Title block  — project name, sheet number, scale, date, reference info

Method
------
The engine works entirely in "sheet space" coordinates.  Each sheet is
assigned a station range [sta_start, sta_end] derived from the alignment
total length and the configured sheet coverage.  Station labels follow the
American convention  "XX+YY.YY" for feet or "XXXX+YY.YY" for metres.

Output is a pure JSON / Python dict structure — no external rendering
dependencies.  A downstream renderer (e.g. SVG, PDF, DXF) can consume the
JSON to produce the final drawings.

References
----------
AASHTO (2011). A Policy on Geometric Design of Highways and Streets (Green
  Book), Chapter 2 — Alignment.
FHWA (2012). Plans Preparation Manual, Volume I — Standard Plans.
ODOT (2023). Plans Preparation Manual, Chapter 300 — Standard Sheets.
CALTRANS (2023). Plans Preparation Manual, Chapter 3 — Roadway Plan Sheets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Utility: station label formatting
# ---------------------------------------------------------------------------

def _fmt_station(sta: float, units: str = "m") -> str:
    """
    Format a station value as a string.

    Metric: 1234.56 m → "1+234.56"  (thousands-plus-metres)
    US customary: 12345.6 ft → "123+45.6"  (hundreds-plus-feet)
    """
    if units == "ft":
        # 100-ft stations: "XXX+YY.YY"
        major = int(sta // 100)
        minor = sta - major * 100
        return f"{major}+{minor:05.2f}"
    else:
        # Metric 1000-m stations: "X+YYY.YY"
        major = int(sta // 1000)
        minor = sta - major * 1000
        return f"{major}+{minor:06.2f}"


def _ha_interpolate_xy(
    alignment_elements: list[dict],
    station: float,
) -> tuple[float, float, float]:
    """
    Walk a horizontal alignment element list and return the (x, y, bearing°)
    at the given station.

    Elements are dicts with keys: type (tangent/arc/spiral), length, ...
    This is a simplified linear interpolation suitable for plan-sheet
    centreline generation — full clothoid geometry is in horizontal_alignment.py.

    Returns (x, y, bearing_deg_cw_from_north).
    """
    x, y = 0.0, 0.0
    bearing = 0.0  # degrees, 0=North, CW
    dist = 0.0

    for elem in alignment_elements:
        etype = elem.get("type", "tangent")
        length = float(elem.get("length", 0.0))

        if dist + length >= station:
            # Target station is within this element
            remaining = station - dist
            if etype == "tangent":
                # Straight line
                angle_rad = math.radians(90.0 - bearing)
                x += remaining * math.cos(angle_rad)
                y += remaining * math.sin(angle_rad)
            elif etype == "arc":
                radius = float(elem.get("radius", 1000.0))
                delta_deg = float(elem.get("delta_deg", 0.0))
                turn_right = elem.get("turn_right", True)
                # Arc: bearing changes linearly with distance
                delta_bearing = math.degrees(remaining / radius)
                if not turn_right:
                    delta_bearing = -delta_bearing
                mid_bearing = bearing + delta_bearing / 2
                angle_rad = math.radians(90.0 - mid_bearing)
                x += remaining * math.cos(angle_rad)
                y += remaining * math.sin(angle_rad)
                bearing += delta_bearing
            else:
                # spiral — approximate as tangent
                angle_rad = math.radians(90.0 - bearing)
                x += remaining * math.cos(angle_rad)
                y += remaining * math.sin(angle_rad)
            break

        # Full element traversal
        if etype == "tangent":
            angle_rad = math.radians(90.0 - bearing)
            x += length * math.cos(angle_rad)
            y += length * math.sin(angle_rad)
        elif etype == "arc":
            radius = float(elem.get("radius", 1000.0))
            delta_deg = float(elem.get("delta_deg", 0.0))
            turn_right = elem.get("turn_right", True)
            delta_bearing = math.degrees(length / radius)
            if not turn_right:
                delta_bearing = -delta_bearing
            mid_bearing = bearing + delta_bearing / 2
            angle_rad = math.radians(90.0 - mid_bearing)
            x += length * math.cos(angle_rad)
            y += length * math.sin(angle_rad)
            bearing += delta_bearing
        else:
            angle_rad = math.radians(90.0 - bearing)
            x += length * math.cos(angle_rad)
            y += length * math.sin(angle_rad)

        dist += length

    return x, y, bearing


def _va_elevation(
    vertical_elements: list[dict],
    datum_elev: float,
    initial_grade_pct: float,
    station: float,
) -> tuple[float, float]:
    """
    Return (elevation, grade_pct) at *station* from a vertical alignment.

    vertical_elements: list of dicts with type ('tangent'|'curve'), length,
                       grade_out_pct.
    """
    elev = datum_elev
    grade = initial_grade_pct
    dist = 0.0

    for elem in vertical_elements:
        etype = elem.get("type", "tangent")
        length = float(elem.get("length", 0.0))

        if dist + length >= station:
            x = station - dist
            if etype == "tangent":
                elev += grade / 100.0 * x
            else:
                g_out = float(elem.get("grade_out_pct", grade))
                # Parabolic curve: e(x) = elev_bvc + g1*x + (g2-g1)/(2L)*x²
                elev = elev + (grade / 100.0) * x + (g_out - grade) / (2.0 * length * 100.0) * x * x
                grade = grade + (g_out - grade) * x / length
            return round(elev, 4), round(grade, 4)

        # Full element
        if etype == "tangent":
            elev += grade / 100.0 * length
        else:
            g_out = float(elem.get("grade_out_pct", grade))
            elev = elev + grade / 100.0 * length + (g_out - grade) / 200.0 * length
            grade = g_out
        dist += length

    # Past end — extrapolate with last grade
    remaining = station - dist
    elev += grade / 100.0 * remaining
    return round(elev, 4), round(grade, 4)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ProfileBandPoint:
    station: float
    station_label: str
    existing_elev: float | None
    proposed_elev: float
    grade_pct: float


@dataclass
class StationTick:
    station: float
    label: str
    x: float  # plan-space x at this station
    y: float  # plan-space y at this station
    bearing_deg: float


@dataclass
class MatchLine:
    station: float
    label: str
    sheet_from: int
    sheet_to: int
    x: float
    y: float


@dataclass
class Sheet:
    sheet_number: int
    total_sheets: int
    sta_start: float
    sta_end: float
    sta_start_label: str
    sta_end_label: str
    plan_scale: int          # e.g. 1000 → 1:1000
    profile_scale_h: int     # horizontal
    profile_scale_v: int     # vertical
    units: str               # "m" or "ft"
    # Plan view content
    station_ticks: list[StationTick]
    alignment_polyline: list[dict]   # [{"x": ..., "y": ..., "station": ...}]
    match_lines: list[MatchLine]
    # Profile band content
    profile_points: list[ProfileBandPoint]
    profile_datum_elev: float
    profile_top_elev: float
    # Metadata
    project_name: str
    alignment_name: str
    date: str
    designer: str


@dataclass
class SheetSet:
    sheets: list[Sheet]
    total_length_m: float
    n_sheets: int
    alignment_name: str
    project_name: str
    units: str


# ---------------------------------------------------------------------------
# Sheet production engine
# ---------------------------------------------------------------------------

def produce_sheets(
    *,
    total_length: float,
    alignment_elements: list[dict] | None = None,
    vertical_elements: list[dict] | None = None,
    datum_elev: float = 0.0,
    initial_grade_pct: float = 0.0,
    existing_ground: list[tuple[float, float]] | None = None,
    plan_scale: int = 1000,
    profile_scale_h: int = 1000,
    profile_scale_v: int = 200,
    sheet_length: float | None = None,
    station_interval: float = 20.0,
    units: str = "m",
    project_name: str = "Kerf Civil Project",
    alignment_name: str = "Alignment 1",
    date: str = "",
    designer: str = "",
    overlap: float = 0.0,
) -> SheetSet:
    """
    Produce a plan-and-profile sheet set for a horizontal+vertical alignment.

    Parameters
    ----------
    total_length       : float — alignment total length (m or ft)
    alignment_elements : list of dicts, each with keys
                         'type' (tangent|arc|spiral), 'length', 'radius',
                         'delta_deg', 'turn_right'.  If None, treated as
                         a single tangent.
    vertical_elements  : list of dicts, each with keys
                         'type' (tangent|curve), 'length', 'grade_out_pct'.
                         If None, treated as flat (0 % grade).
    datum_elev         : starting elevation for vertical alignment (m)
    initial_grade_pct  : initial grade (%)
    existing_ground    : list of (station, elev) pairs for existing ground
                         profile.  Interpolated at sheet station ticks.
    plan_scale         : plan-view scale denominator (e.g. 1000 → 1:1000)
    profile_scale_h    : profile horizontal scale denominator
    profile_scale_v    : profile vertical scale denominator
    sheet_length       : alignment length covered per sheet (model units).
                         Default = plan_scale × 0.25 (assumes 250 mm plan width).
    station_interval   : grid/tick interval (m or ft)
    units              : 'm' (metric) or 'ft' (US customary)
    project_name       : title block project name
    alignment_name     : title block alignment name
    date               : date string for title block
    designer           : designer/engineer of record initials
    overlap            : overlap between sheets (m) at match-line stations

    Returns
    -------
    SheetSet dataclass

    References
    ----------
    AASHTO Green Book (2011) Chapter 2; FHWA Plans Preparation Manual (2012);
    ODOT Plans Preparation Manual (2023) Ch.300; CALTRANS PPM (2023) Ch.3.
    """
    if total_length <= 0:
        raise ValueError(f"total_length must be > 0, got {total_length!r}")

    # Default element lists
    ha_elements = alignment_elements or [{"type": "tangent", "length": total_length}]
    va_elements = vertical_elements or [{"type": "tangent", "length": total_length}]

    # Default sheet coverage: plan_scale × 250 mm paper width
    if sheet_length is None:
        sheet_length = plan_scale * 0.250  # 250 mm → metres

    sheet_length = max(sheet_length, station_interval)

    # Build existing ground lookup (linear interpolation by station)
    def _existing_elev(sta: float) -> float | None:
        if not existing_ground:
            return None
        eg = sorted(existing_ground, key=lambda s: s[0])
        if sta <= eg[0][0]:
            return eg[0][1]
        if sta >= eg[-1][0]:
            return eg[-1][1]
        for i in range(len(eg) - 1):
            s0, z0 = eg[i]
            s1, z1 = eg[i + 1]
            if s0 <= sta <= s1:
                t = (sta - s0) / (s1 - s0)
                return z0 + t * (z1 - z0)
        return None

    # --- Partition alignment into sheets ---
    n_sheets = max(1, math.ceil(total_length / sheet_length))
    sheets: list[Sheet] = []

    for sh_idx in range(n_sheets):
        sta_start = sh_idx * sheet_length - (overlap if sh_idx > 0 else 0.0)
        sta_end = min((sh_idx + 1) * sheet_length, total_length)
        sta_start = max(sta_start, 0.0)

        # Station ticks in this sheet
        first_tick = math.ceil(sta_start / station_interval) * station_interval
        ticks_sta = []
        s = first_tick
        while s <= sta_end + 1e-9:
            ticks_sta.append(round(s, 6))
            s = round(s + station_interval, 6)
        # Always include start / end stations
        for boundary_sta in [sta_start, sta_end]:
            if not any(abs(t - boundary_sta) < 1e-6 for t in ticks_sta):
                ticks_sta.append(round(boundary_sta, 6))
        ticks_sta.sort()

        # Build plan station ticks
        station_ticks: list[StationTick] = []
        alignment_pts: list[dict] = []
        for sta in ticks_sta:
            px, py, brg = _ha_interpolate_xy(ha_elements, sta)
            station_ticks.append(StationTick(
                station=sta,
                label=_fmt_station(sta, units),
                x=round(px, 4),
                y=round(py, 4),
                bearing_deg=round(brg, 4),
            ))
            alignment_pts.append({"x": round(px, 4), "y": round(py, 4), "station": sta})

        # Match lines at sheet boundaries
        match_lines: list[MatchLine] = []
        if sh_idx > 0:
            # Back match line (from previous sheet)
            ml_sta = sta_start + (overlap if overlap > 0 else 0.0)
            px, py, brg = _ha_interpolate_xy(ha_elements, ml_sta)
            match_lines.append(MatchLine(
                station=ml_sta,
                label=f"←  Match Line Sta. {_fmt_station(ml_sta, units)}  Sheet {sh_idx}",
                sheet_from=sh_idx,
                sheet_to=sh_idx + 1,
                x=round(px, 4),
                y=round(py, 4),
            ))
        if sh_idx < n_sheets - 1:
            # Forward match line
            fwd_sta = sta_end
            px, py, brg = _ha_interpolate_xy(ha_elements, fwd_sta)
            match_lines.append(MatchLine(
                station=fwd_sta,
                label=f"Match Line Sta. {_fmt_station(fwd_sta, units)}  Sheet {sh_idx + 2}  →",
                sheet_from=sh_idx + 1,
                sheet_to=sh_idx + 2,
                x=round(px, 4),
                y=round(py, 4),
            ))

        # Profile band: collect elevations at each tick
        profile_points: list[ProfileBandPoint] = []
        all_proposed: list[float] = []
        all_existing: list[float] = []

        for sta in ticks_sta:
            prop_elev, grade_pct = _va_elevation(va_elements, datum_elev, initial_grade_pct, sta)
            exist_elev = _existing_elev(sta)
            profile_points.append(ProfileBandPoint(
                station=sta,
                station_label=_fmt_station(sta, units),
                existing_elev=round(exist_elev, 4) if exist_elev is not None else None,
                proposed_elev=round(prop_elev, 4),
                grade_pct=round(grade_pct, 4),
            ))
            all_proposed.append(prop_elev)
            if exist_elev is not None:
                all_existing.append(exist_elev)

        all_z = all_proposed + all_existing
        if all_z:
            z_margin = (max(all_z) - min(all_z)) * 0.1 + 1.0
            profile_datum_elev = round(min(all_z) - z_margin, 2)
            profile_top_elev = round(max(all_z) + z_margin, 2)
        else:
            profile_datum_elev = round(datum_elev - 5.0, 2)
            profile_top_elev = round(datum_elev + 5.0, 2)

        sheets.append(Sheet(
            sheet_number=sh_idx + 1,
            total_sheets=n_sheets,
            sta_start=round(sta_start, 4),
            sta_end=round(sta_end, 4),
            sta_start_label=_fmt_station(sta_start, units),
            sta_end_label=_fmt_station(sta_end, units),
            plan_scale=plan_scale,
            profile_scale_h=profile_scale_h,
            profile_scale_v=profile_scale_v,
            units=units,
            station_ticks=station_ticks,
            alignment_polyline=alignment_pts,
            match_lines=match_lines,
            profile_points=profile_points,
            profile_datum_elev=profile_datum_elev,
            profile_top_elev=profile_top_elev,
            project_name=project_name,
            alignment_name=alignment_name,
            date=date,
            designer=designer,
        ))

    return SheetSet(
        sheets=sheets,
        total_length_m=total_length,
        n_sheets=len(sheets),
        alignment_name=alignment_name,
        project_name=project_name,
        units=units,
    )


# ---------------------------------------------------------------------------
# JSON serialisation helper
# ---------------------------------------------------------------------------

def sheet_set_to_dict(ss: SheetSet) -> dict:
    """Serialise a SheetSet to a plain dict (JSON-serialisable)."""

    def _sheet_to_dict(sh: Sheet) -> dict:
        return {
            "sheet_number": sh.sheet_number,
            "total_sheets": sh.total_sheets,
            "sta_start": sh.sta_start,
            "sta_end": sh.sta_end,
            "sta_start_label": sh.sta_start_label,
            "sta_end_label": sh.sta_end_label,
            "plan_scale": sh.plan_scale,
            "profile_scale_h": sh.profile_scale_h,
            "profile_scale_v": sh.profile_scale_v,
            "units": sh.units,
            "project_name": sh.project_name,
            "alignment_name": sh.alignment_name,
            "date": sh.date,
            "designer": sh.designer,
            "profile_datum_elev": sh.profile_datum_elev,
            "profile_top_elev": sh.profile_top_elev,
            "station_ticks": [
                {
                    "station": t.station,
                    "label": t.label,
                    "x": t.x, "y": t.y,
                    "bearing_deg": t.bearing_deg,
                }
                for t in sh.station_ticks
            ],
            "alignment_polyline": sh.alignment_polyline,
            "match_lines": [
                {
                    "station": ml.station,
                    "label": ml.label,
                    "sheet_from": ml.sheet_from,
                    "sheet_to": ml.sheet_to,
                    "x": ml.x, "y": ml.y,
                }
                for ml in sh.match_lines
            ],
            "profile_band": [
                {
                    "station": pp.station,
                    "station_label": pp.station_label,
                    "existing_elev": pp.existing_elev,
                    "proposed_elev": pp.proposed_elev,
                    "grade_pct": pp.grade_pct,
                }
                for pp in sh.profile_points
            ],
        }

    return {
        "total_length_m": ss.total_length_m,
        "n_sheets": ss.n_sheets,
        "alignment_name": ss.alignment_name,
        "project_name": ss.project_name,
        "units": ss.units,
        "sheets": [_sheet_to_dict(sh) for sh in ss.sheets],
    }
