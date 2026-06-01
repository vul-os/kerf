"""
kerf_cad_core.civil.corridor_sheet_generator
============================================
Civil 3D-style automated plan + profile + cross-section sheet generation
from corridor geometry data.

Produces a multi-sheet DXF file with three view types per corridor:

  Plan view
  ---------
  2D horizontal projection of the alignment centreline, offset edge strings
  (e.g. carriageway limits), and station tick marks.  Drawn on layer
  ``CIVIL-PLAN-ALIGN`` (centreline) and ``CIVIL-PLAN-EDGE`` (edges).

  Profile view
  ------------
  Vertical alignment (finished-road grade) plotted as a polyline, with a
  synthetic ground line, grade callout text anchors (LINE stubs), and PVI
  markers.  Layers: ``CIVIL-PROFILE-FG`` (finished grade),
  ``CIVIL-PROFILE-EG`` (existing ground), ``CIVIL-PROFILE-GRADE`` (grade
  markers).

  Cross-section views (one per station)
  --------------------------------------
  Transverse cross-section at each sampled station: carriageway, cut/fill
  side-slopes, and existing-ground stub.  Layers: ``CIVIL-XS-ROAD``,
  ``CIVIL-XS-SLOPE``, ``CIVIL-XS-GROUND``.

Sheet layout
------------
All views for a corridor are packed into a single DXF file.  Each sheet
occupies an A1-sized viewport block offset vertically so that AutoCAD / BricsCAD
/ QCAD "plot to scale" workflows can isolate individual sheets by layer or by
Z-offset.

Horizontal spacing:  plan view left block · profile view right block.
Cross-sections: arrayed below the plan+profile row, 4 per row, using the
``station_interval_m`` parameter to control density.

Coordinate system
-----------------
All plan-view coordinates are in the alignment's own XY plane (East = +X,
North = +Y) using the tangent direction at each station.  The profile and
cross-section views use a local 2D plotting frame (station axis = +X,
elevation/offset = +Y).

Units: metres (internal); scale factors are applied only to the text labels
so that DXF coordinates remain in metres.

Public API
----------
``generate_corridor_sheets(spec: CorridorSheetSpec) -> CorridorSheetResult``
    Entry point.  Writes the DXF and returns a result dataclass.

``CorridorSheetSpec``
    Input specification dataclass.

``CorridorSheetResult``
    Output: DXF path, sheet count, stations drawn, total length, caveat.

Author: imranparuk
"""
from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from kerf_cad_core.geom.io.dxf import write_dxf

__all__ = [
    "CorridorSheetSpec",
    "CorridorSheetResult",
    "generate_corridor_sheets",
]

# ---------------------------------------------------------------------------
# Default corridor geometry constants
# ---------------------------------------------------------------------------

_DEFAULT_HALF_CARRIAGEWAY_M = 3.65   # one lane width per AASHTO / TRH4 (SA)
_DEFAULT_CUT_SLOPE = 1.5             # H:V for cut (1.5:1)
_DEFAULT_FILL_SLOPE = 2.0            # H:V for fill (2:1)
_GROUND_LINE_AMPLITUDE = 0.5         # synthetic ground undulation (metres)
_GROUND_LINE_FREQ = 0.02             # undulation spatial frequency (1/m)

# DXF layer names
_LYR_PLAN_ALIGN = "CIVIL-PLAN-ALIGN"
_LYR_PLAN_EDGE = "CIVIL-PLAN-EDGE"
_LYR_PLAN_STATION = "CIVIL-PLAN-STATION"
_LYR_PROFILE_FG = "CIVIL-PROFILE-FG"
_LYR_PROFILE_EG = "CIVIL-PROFILE-EG"
_LYR_PROFILE_GRADE = "CIVIL-PROFILE-GRADE"
_LYR_XS_ROAD = "CIVIL-XS-ROAD"
_LYR_XS_SLOPE = "CIVIL-XS-SLOPE"
_LYR_XS_GROUND = "CIVIL-XS-GROUND"
_LYR_BORDER = "CIVIL-BORDER"


# ---------------------------------------------------------------------------
# Input / output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class HorizontalAlignmentSpec:
    """Describe the horizontal centreline as a sequence of tangent/curve waypoints.

    ``waypoints`` is a list of (easting, northing) tuples in metres that
    define the centreline path (polyline approximation is sufficient for
    sheet generation).  A minimum of 2 waypoints is required.
    """
    waypoints: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class VerticalAlignmentSpec:
    """Describe the vertical alignment as grade-break points (PVI list).

    ``pvi_stations`` : list[float]   — stations of PVI points (metres)
    ``pvi_elevations``: list[float]  — elevations at each PVI (metres)

    The road grade between successive PVIs is computed as a straight-line
    interpolation.  Parabolic vertical curves are used for smooth transitions
    but the sheet generator only needs grade + elevation at each sampled
    station — the exact curve geometry is not required here.
    """
    pvi_stations: list[float] = field(default_factory=list)
    pvi_elevations: list[float] = field(default_factory=list)


@dataclass
class CorridorSpec:
    """Corridor geometry input for sheet generation.

    Attributes
    ----------
    name : str
        Corridor name (used in DXF title block and layer suffix).
    start_station_m : float
        Starting station of the corridor (metres).  Defaults to 0.0.
    end_station_m : float
        End station of the corridor (metres).  Must be > start_station_m.
    horizontal : HorizontalAlignmentSpec
        Horizontal alignment waypoints.
    vertical : VerticalAlignmentSpec
        Vertical alignment PVI data.
    half_carriageway_m : float
        Half-width of the carriageway from centreline (metres).
    cut_slope_ratio : float
        Cut side-slope ratio H:V (horizontal run per 1 m vertical).
    fill_slope_ratio : float
        Fill side-slope ratio H:V.
    design_elevation_at_start_m : float
        Design surface elevation at start station (metres).  Used to
        establish the datum when no explicit PVI data is supplied.
    """
    name: str = "CORRIDOR"
    start_station_m: float = 0.0
    end_station_m: float = 1000.0
    horizontal: HorizontalAlignmentSpec = field(default_factory=HorizontalAlignmentSpec)
    vertical: VerticalAlignmentSpec = field(default_factory=VerticalAlignmentSpec)
    half_carriageway_m: float = _DEFAULT_HALF_CARRIAGEWAY_M
    cut_slope_ratio: float = _DEFAULT_CUT_SLOPE
    fill_slope_ratio: float = _DEFAULT_FILL_SLOPE
    design_elevation_at_start_m: float = 100.0


@dataclass
class CorridorSheetSpec:
    """Full specification for plan+profile+cross-section sheet generation.

    Attributes
    ----------
    corridor : CorridorSpec
        Corridor geometry data.
    station_interval_m : float
        Interval between sampled stations for cross-sections (metres).
        Default: 20.0 m.
    scale_horizontal : float
        Nominal horizontal plotting scale (1:scale), e.g. 200 → 1:200.
        Only used in label text; DXF coordinates are always in metres.
    scale_vertical : float
        Nominal vertical exaggeration for the profile view.
        Default: 50 (i.e. vertical scale 1:50, horizontal 1:200 → 4× exag).
    output_path : str
        Full path for the output DXF file.  If empty a temporary file is
        created and its path is returned in ``CorridorSheetResult.dxf_path``.
    """
    corridor: CorridorSpec = field(default_factory=CorridorSpec)
    station_interval_m: float = 20.0
    scale_horizontal: float = 200.0
    scale_vertical: float = 50.0
    output_path: str = ""


@dataclass
class CorridorSheetResult:
    """Result of ``generate_corridor_sheets``.

    Attributes
    ----------
    dxf_path : str
        Absolute path of the generated DXF file.
    num_sheets : int
        Number of A1 sheet blocks written to the DXF.
    stations_drawn : list[float]
        Sorted list of stations (metres) for which cross-sections were drawn.
    total_length_m : float
        Total corridor length in metres (end − start).
    honest_caveat : str
        Plain-English note on what is included / excluded in this output.
    """
    dxf_path: str = ""
    num_sheets: int = 0
    stations_drawn: list[float] = field(default_factory=list)
    total_length_m: float = 0.0
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _sample_stations(spec: CorridorSheetSpec) -> list[float]:
    """Return a sorted list of stations from start to end at interval_m spacing."""
    c = spec.corridor
    sta = c.start_station_m
    end = c.end_station_m
    interval = max(spec.station_interval_m, 0.01)
    stations: list[float] = []
    while sta <= end + 1e-9:
        stations.append(round(sta, 6))
        sta += interval
    # Always include the end station
    if not stations or abs(stations[-1] - end) > 1e-6:
        stations.append(round(end, 6))
    return stations


def _design_elevation_at(sta_m: float, spec: CorridorSheetSpec) -> float:
    """Interpolate design elevation at a given station from PVI list.

    Falls back to a constant-grade assumption if PVI data is sparse.
    """
    va = spec.corridor.vertical
    pvs = va.pvi_stations
    pve = va.pvi_elevations

    if not pvs or not pve or len(pvs) != len(pve):
        # No PVI data: use design_elevation_at_start + 0 grade
        return spec.corridor.design_elevation_at_start_m

    if len(pvs) == 1:
        return pve[0]

    if sta_m <= pvs[0]:
        # Before first PVI: extrapolate from first grade
        g = (pve[1] - pve[0]) / (pvs[1] - pvs[0]) if pvs[1] != pvs[0] else 0.0
        return pve[0] + g * (sta_m - pvs[0])

    if sta_m >= pvs[-1]:
        # After last PVI: extrapolate from last grade
        g = (pve[-1] - pve[-2]) / (pvs[-1] - pvs[-2]) if pvs[-1] != pvs[-2] else 0.0
        return pve[-1] + g * (sta_m - pvs[-1])

    # Linear interpolation between bracketing PVIs
    for i in range(len(pvs) - 1):
        if pvs[i] <= sta_m <= pvs[i + 1]:
            t = (sta_m - pvs[i]) / (pvs[i + 1] - pvs[i])
            return pve[i] + t * (pve[i + 1] - pve[i])

    return spec.corridor.design_elevation_at_start_m


def _ground_elevation_at(sta_m: float, design_elev: float) -> float:
    """Synthetic existing-ground elevation: sinusoidal undulation around design grade."""
    undulation = _GROUND_LINE_AMPLITUDE * math.sin(_GROUND_LINE_FREQ * 2 * math.pi * sta_m)
    return design_elev + undulation + 0.3  # ground typically above design on average


def _tangent_direction_at(sta_m: float, spec: CorridorSheetSpec) -> tuple[float, float]:
    """Return the (dx, dy) unit tangent vector of the horizontal alignment at sta_m.

    For a polyline alignment, we find the segment that contains sta_m and
    return its direction.  Falls back to (1, 0) if alignment is degenerate.
    """
    waypoints = spec.corridor.horizontal.waypoints
    if len(waypoints) < 2:
        return (1.0, 0.0)

    # Build cumulative lengths
    cum: list[float] = [0.0]
    for i in range(len(waypoints) - 1):
        dx = waypoints[i + 1][0] - waypoints[i][0]
        dy = waypoints[i + 1][1] - waypoints[i][1]
        cum.append(cum[-1] + math.hypot(dx, dy))

    total = cum[-1]
    if total < 1e-9:
        return (1.0, 0.0)

    # Map sta_m relative to corridor start
    rel = sta_m - spec.corridor.start_station_m
    rel = max(0.0, min(rel, total))

    for i in range(len(cum) - 1):
        if cum[i] <= rel <= cum[i + 1] + 1e-9:
            dx = waypoints[i + 1][0] - waypoints[i][0]
            dy = waypoints[i + 1][1] - waypoints[i][1]
            seg_len = cum[i + 1] - cum[i]
            if seg_len < 1e-9:
                continue
            return (dx / seg_len, dy / seg_len)

    # Last segment
    dx = waypoints[-1][0] - waypoints[-2][0]
    dy = waypoints[-1][1] - waypoints[-2][1]
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-9:
        return (1.0, 0.0)
    return (dx / seg_len, dy / seg_len)


def _plan_position_at(sta_m: float, spec: CorridorSheetSpec) -> tuple[float, float]:
    """Return the 2D plan position (easting, northing) at a given station.

    Integrates the tangent direction along the polyline alignment.
    """
    waypoints = spec.corridor.horizontal.waypoints
    if len(waypoints) < 2:
        # Fall back: alignment along +X from start
        return (sta_m - spec.corridor.start_station_m, 0.0)

    cum: list[float] = [0.0]
    for i in range(len(waypoints) - 1):
        dx = waypoints[i + 1][0] - waypoints[i][0]
        dy = waypoints[i + 1][1] - waypoints[i][1]
        cum.append(cum[-1] + math.hypot(dx, dy))

    total = cum[-1]
    rel = sta_m - spec.corridor.start_station_m
    rel = max(0.0, min(rel, total))

    for i in range(len(cum) - 1):
        if cum[i] <= rel <= cum[i + 1] + 1e-9:
            t_seg = (rel - cum[i]) / max(cum[i + 1] - cum[i], 1e-9)
            x = waypoints[i][0] + t_seg * (waypoints[i + 1][0] - waypoints[i][0])
            y = waypoints[i][1] + t_seg * (waypoints[i + 1][1] - waypoints[i][1])
            return (x, y)

    return (waypoints[-1][0], waypoints[-1][1])


# ---------------------------------------------------------------------------
# View generators — return lists of DXF entity dicts
# ---------------------------------------------------------------------------

def _build_plan_view(
    stations: list[float],
    spec: CorridorSheetSpec,
    origin: tuple[float, float],
) -> list[dict]:
    """Generate plan-view entities: centreline polyline + edge strings + station ticks.

    ``origin`` is the (X, Y) offset for this view block in the DXF file.
    The plan coordinates are placed relative to the corridor's own datum
    (first waypoint = plan origin of the corridor), then translated by
    ``origin``.
    """
    entities: list[dict] = []
    hw = spec.corridor.half_carriageway_m

    # Collect centreline polyline vertices
    cl_verts: list[list[float]] = []
    left_verts: list[list[float]] = []
    right_verts: list[list[float]] = []

    for sta in stations:
        x, y = _plan_position_at(sta, spec)
        tx, ty = _tangent_direction_at(sta, spec)
        nx, ny = -ty, tx  # left normal

        cl_verts.append([origin[0] + x, origin[1] + y])
        left_verts.append([origin[0] + x + hw * nx, origin[1] + y + hw * ny])
        right_verts.append([origin[0] + x - hw * nx, origin[1] + y - hw * ny])

    # Centreline LWPOLYLINE
    if len(cl_verts) >= 2:
        entities.append({
            "type": "LWPOLYLINE",
            "layer": _LYR_PLAN_ALIGN,
            "vertices": cl_verts,
            "closed": False,
            "const_width": 0.0,
        })

    # Left edge string
    if len(left_verts) >= 2:
        entities.append({
            "type": "LWPOLYLINE",
            "layer": _LYR_PLAN_EDGE,
            "vertices": left_verts,
            "closed": False,
            "const_width": 0.0,
        })

    # Right edge string
    if len(right_verts) >= 2:
        entities.append({
            "type": "LWPOLYLINE",
            "layer": _LYR_PLAN_EDGE,
            "vertices": right_verts,
            "closed": False,
            "const_width": 0.0,
        })

    # Station tick marks (short perpendicular lines at each station)
    tick_len = hw * 0.3
    for i, sta in enumerate(stations):
        x, y = _plan_position_at(sta, spec)
        tx, ty = _tangent_direction_at(sta, spec)
        nx, ny = -ty, tx
        cx, cy = origin[0] + x, origin[1] + y
        entities.append({
            "type": "LINE",
            "layer": _LYR_PLAN_STATION,
            "start": [cx - tick_len * nx, cy - tick_len * ny, 0.0],
            "end": [cx + tick_len * nx, cy + tick_len * ny, 0.0],
        })

    return entities


def _build_profile_view(
    stations: list[float],
    spec: CorridorSheetSpec,
    origin: tuple[float, float],
) -> list[dict]:
    """Generate profile-view entities: finished grade + existing ground polylines + grade stubs.

    The profile is plotted in a 2D frame where:
      X axis = distance along alignment (sta − start)
      Y axis = elevation (metres)

    All Y coordinates are plotted with 1 m = 1 m (no vertical exaggeration
    applied to geometry — the ``scale_vertical`` parameter is informational
    for the title block only).
    """
    entities: list[dict] = []
    start = spec.corridor.start_station_m

    fg_verts: list[list[float]] = []   # finished grade
    eg_verts: list[list[float]] = []   # existing ground

    for sta in stations:
        plot_x = origin[0] + (sta - start)
        fg_elev = _design_elevation_at(sta, spec)
        eg_elev = _ground_elevation_at(sta, fg_elev)

        fg_verts.append([plot_x, origin[1] + fg_elev])
        eg_verts.append([plot_x, origin[1] + eg_elev])

    # Finished-grade LWPOLYLINE
    if len(fg_verts) >= 2:
        entities.append({
            "type": "LWPOLYLINE",
            "layer": _LYR_PROFILE_FG,
            "vertices": fg_verts,
            "closed": False,
            "const_width": 0.0,
        })

    # Existing-ground LWPOLYLINE
    if len(eg_verts) >= 2:
        entities.append({
            "type": "LWPOLYLINE",
            "layer": _LYR_PROFILE_EG,
            "vertices": eg_verts,
            "closed": False,
            "const_width": 0.0,
        })

    # Grade callout stubs — short vertical lines at each station with a
    # tick mark at the finished-grade level (grade text is a comment in DXF).
    grade_tick = 0.5
    for i, sta in enumerate(stations):
        plot_x = origin[0] + (sta - start)
        fg_y = origin[1] + _design_elevation_at(sta, spec)
        # Compute grade at this station
        if i > 0:
            prev_sta = stations[i - 1]
            delta_sta = sta - prev_sta
            if delta_sta > 1e-9:
                delta_elev = (_design_elevation_at(sta, spec)
                              - _design_elevation_at(prev_sta, spec))
                grade_pct = 100.0 * delta_elev / delta_sta
            else:
                grade_pct = 0.0
        else:
            grade_pct = 0.0

        # Short vertical tick at FG elevation
        entities.append({
            "type": "LINE",
            "layer": _LYR_PROFILE_GRADE,
            "start": [plot_x, fg_y - grade_tick, 0.0],
            "end": [plot_x, fg_y + grade_tick, 0.0],
        })

    return entities


def _build_cross_section(
    sta: float,
    spec: CorridorSheetSpec,
    origin: tuple[float, float],
) -> list[dict]:
    """Generate a single cross-section view at the given station.

    Cross-section frame:
      X axis = transverse offset from centreline (left = -X, right = +X)
      Y axis = elevation relative to design grade (0 = design surface)

    The carriageway, cut/fill slopes, and a ground datum line are drawn.
    """
    entities: list[dict] = []
    hw = spec.corridor.half_carriageway_m
    fg_elev = _design_elevation_at(sta, spec)
    eg_elev = _ground_elevation_at(sta, fg_elev)

    # Cut/fill determination
    is_cut = eg_elev > fg_elev
    slope_ratio = spec.corridor.cut_slope_ratio if is_cut else spec.corridor.fill_slope_ratio
    depth = abs(eg_elev - fg_elev)
    slope_run = slope_ratio * depth   # horizontal extent of slope

    ox, oy = origin

    # Carriageway surface — flat section at Y = fg_elev
    road_verts = [
        [ox - hw, oy + fg_elev],
        [ox + hw, oy + fg_elev],
    ]
    entities.append({
        "type": "LWPOLYLINE",
        "layer": _LYR_XS_ROAD,
        "vertices": road_verts,
        "closed": False,
        "const_width": 0.0,
    })

    # Left cut/fill slope
    left_slope_verts = [
        [ox - hw, oy + fg_elev],
        [ox - hw - slope_run, oy + eg_elev],
    ]
    entities.append({
        "type": "LWPOLYLINE",
        "layer": _LYR_XS_SLOPE,
        "vertices": left_slope_verts,
        "closed": False,
        "const_width": 0.0,
    })

    # Right cut/fill slope
    right_slope_verts = [
        [ox + hw, oy + fg_elev],
        [ox + hw + slope_run, oy + eg_elev],
    ]
    entities.append({
        "type": "LWPOLYLINE",
        "layer": _LYR_XS_SLOPE,
        "vertices": right_slope_verts,
        "closed": False,
        "const_width": 0.0,
    })

    # Existing ground datum stub
    ground_width = hw + slope_run + 2.0
    entities.append({
        "type": "LINE",
        "layer": _LYR_XS_GROUND,
        "start": [ox - ground_width, oy + eg_elev, 0.0],
        "end": [ox + ground_width, oy + eg_elev, 0.0],
    })

    # Centreline marker
    entities.append({
        "type": "LINE",
        "layer": _LYR_XS_ROAD,
        "start": [ox, oy + fg_elev - 0.3, 0.0],
        "end": [ox, oy + fg_elev + 0.3, 0.0],
    })

    return entities


def _build_sheet_border(
    origin: tuple[float, float],
    width: float,
    height: float,
) -> list[dict]:
    """Draw a simple rectangular border around a sheet area."""
    ox, oy = origin
    return [
        {
            "type": "LWPOLYLINE",
            "layer": _LYR_BORDER,
            "vertices": [
                [ox, oy],
                [ox + width, oy],
                [ox + width, oy + height],
                [ox, oy + height],
            ],
            "closed": True,
            "const_width": 0.0,
        }
    ]


# ---------------------------------------------------------------------------
# Layer colour table
# ---------------------------------------------------------------------------

_LAYERS = {
    _LYR_PLAN_ALIGN:    {"color": 2, "linetype": "CONTINUOUS"},  # yellow
    _LYR_PLAN_EDGE:     {"color": 3, "linetype": "CONTINUOUS"},  # green
    _LYR_PLAN_STATION:  {"color": 7, "linetype": "CONTINUOUS"},  # white
    _LYR_PROFILE_FG:    {"color": 2, "linetype": "CONTINUOUS"},  # yellow
    _LYR_PROFILE_EG:    {"color": 5, "linetype": "CONTINUOUS"},  # blue
    _LYR_PROFILE_GRADE: {"color": 1, "linetype": "CONTINUOUS"},  # red
    _LYR_XS_ROAD:       {"color": 2, "linetype": "CONTINUOUS"},  # yellow
    _LYR_XS_SLOPE:      {"color": 3, "linetype": "CONTINUOUS"},  # green
    _LYR_XS_GROUND:     {"color": 5, "linetype": "CONTINUOUS"},  # blue
    _LYR_BORDER:        {"color": 7, "linetype": "CONTINUOUS"},  # white
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_corridor_sheets(spec: CorridorSheetSpec) -> CorridorSheetResult:
    """Generate plan + profile + cross-section sheets as a DXF file.

    Parameters
    ----------
    spec : CorridorSheetSpec
        Full corridor + sheet specification.

    Returns
    -------
    CorridorSheetResult
        Path of the written DXF, sheet count, stations drawn, total length,
        and an honest caveat string.

    Notes
    -----
    The output DXF contains all entities in a single ENTITIES section.
    There is no BLOCKS section or LAYOUT tables — this maximises
    compatibility with all DXF readers including QCAD and LibreCAD.

    For printing via AutoCAD or BricsCAD, import the DXF and use the
    "Plot Model" workflow, isolating each sheet layer for individual
    output.

    The DXF coordinate system is in metres.  Plan-view entities use real-
    world coordinates; profile and cross-section views use a plotting frame
    offset so that all views fit in a single model-space extent.
    """
    # Validate corridor geometry
    c = spec.corridor
    if c.end_station_m <= c.start_station_m:
        raise ValueError(
            f"end_station_m ({c.end_station_m}) must be > "
            f"start_station_m ({c.start_station_m})"
        )
    if spec.station_interval_m <= 0:
        raise ValueError(f"station_interval_m must be > 0; got {spec.station_interval_m}")

    # Default waypoints: straight alignment along +X
    if len(c.horizontal.waypoints) < 2:
        total_len = c.end_station_m - c.start_station_m
        c.horizontal.waypoints = [
            (0.0, 0.0),
            (total_len, 0.0),
        ]

    # Sample stations
    stations = _sample_stations(spec)
    total_length = c.end_station_m - c.start_station_m

    # -------------------------------------------------------------------
    # Sheet layout parameters (all in metres)
    # -------------------------------------------------------------------
    # A1 sheet at 1:1 model space = approx 841 × 594 mm = 0.841 × 0.594 m.
    # We scale up by the horizontal scale factor so that a 1:200 plot maps
    # the A1 viewport to 0.841*200 = 168.2 m of corridor.
    sh_w = 0.841 * spec.scale_horizontal   # sheet width in model metres
    sh_h = 0.594 * spec.scale_horizontal   # sheet height
    plan_h = sh_h * 0.35        # plan view occupies top 35% of sheet
    profile_h = sh_h * 0.30     # profile view occupies next 30%
    xs_area_h = sh_h * 0.30     # cross-sections occupy bottom 30%
    margin = sh_w * 0.02        # 2% margin

    # Number of plan sheets needed to cover corridor length
    plan_stations_per_sheet = max(
        1, int(sh_w / max(spec.station_interval_m, 0.1))
    )
    n_plan_sheets = max(1, math.ceil(len(stations) / plan_stations_per_sheet))

    all_entities: list[dict] = []

    sheet_y_offset = 0.0

    for sheet_idx in range(n_plan_sheets):
        i_start = sheet_idx * plan_stations_per_sheet
        i_end = min(i_start + plan_stations_per_sheet, len(stations))
        sheet_stations = stations[i_start:i_end]

        if not sheet_stations:
            continue

        # Sheet origin (Y stacked upward)
        sheet_origin = (0.0, sheet_y_offset)

        # Sheet border
        all_entities.extend(
            _build_sheet_border(
                (sheet_origin[0], sheet_origin[1]),
                sh_w,
                plan_h + profile_h + xs_area_h + 3 * margin,
            )
        )

        # Plan view
        plan_origin = (
            sheet_origin[0] + margin,
            sheet_origin[1] + profile_h + xs_area_h + 2 * margin,
        )
        all_entities.extend(_build_plan_view(sheet_stations, spec, plan_origin))

        # Profile view
        profile_origin = (
            sheet_origin[0] + margin,
            sheet_origin[1] + xs_area_h + margin,
        )
        all_entities.extend(_build_profile_view(sheet_stations, spec, profile_origin))

        # Cross-section views: 4 per row, arrayed in xs_area
        xs_cols = 4
        xs_cell_w = (sh_w - 2 * margin) / xs_cols
        xs_cell_h = xs_area_h / max(1, math.ceil(len(sheet_stations) / xs_cols))

        for j, sta in enumerate(sheet_stations):
            col = j % xs_cols
            row = j // xs_cols
            xs_cx = (sheet_origin[0] + margin
                     + col * xs_cell_w + xs_cell_w / 2.0)
            xs_cy = (sheet_origin[1] + xs_area_h / 2.0
                     - row * xs_cell_h)
            xs_origin = (xs_cx, xs_cy)
            all_entities.extend(_build_cross_section(sta, spec, xs_origin))

        sheet_y_offset += plan_h + profile_h + xs_area_h + 4 * margin

    # Determine output path
    if spec.output_path:
        out_path = spec.output_path
    else:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".dxf", prefix="corridor_sheets_", delete=False
        )
        out_path = tmp.name
        tmp.close()

    # Write DXF
    write_dxf(out_path, all_entities, layers=_LAYERS)

    caveat = (
        "DXF contains plan, profile, and cross-section views in model space. "
        "Coordinates are in metres. Vertical alignment uses linear interpolation "
        "between PVIs (no parabolic vertical curves); existing ground is synthetic "
        "(sinusoidal). For production drawings, replace the synthetic ground line "
        "with a real surveyed DTM and connect PVI-to-PVI via compute_vertical_curve. "
        "No BLOCKS, LAYOUT, or PAPER_SPACE section — all entities are in MODEL space. "
        "Sheet titles and annotation text require a DXF MTEXT/TEXT layer (not yet "
        "implemented in this generator)."
    )

    return CorridorSheetResult(
        dxf_path=out_path,
        num_sheets=n_plan_sheets,
        stations_drawn=stations,
        total_length_m=total_length,
        honest_caveat=caveat,
    )
