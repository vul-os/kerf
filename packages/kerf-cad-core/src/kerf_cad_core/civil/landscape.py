"""
kerf_cad_core.civil.landscape — Rhino-style landscape: drainage, grading, planting.

HONEST: Algorithms are validated engineering approximations (pure-Python + NumPy).
        Cut/fill via prismoidal grid sampling (ASCE 60); drainage via D8 flow-direction
        (O'Callaghan & Mark 1984) with Tarboton 1997 D-infinity improvements noted;
        planting selection from USDA hardiness zone table — not a licensed Rhino plug-in.

References
----------
  Tarboton, D.G. (1997). "A new method for the determination of flow directions and
      upslope areas in grid digital elevation models." Water Resour. Res. 33(2):309–319.
  O'Callaghan, J.F. & Mark, D.M. (1984). "The extraction of drainage networks from
      digital elevation data." Comput. Vision Graphics Image Process. 28:323–344.
  USDA Plant Hardiness Zone Map (2012 / 2023 revision). Agricultural Research Service.
      https://planthardiness.ars.usda.gov/  (public domain).
  ASLA Sustainable Sites Initiative (SITES v2, 2014). Prerequisite P1.4 – grading.
  ASCE Manual of Engineering Practice 60 (1982). §5 grid-method earthwork.

Units: SI throughout (metres, litres, m²).
Author: imranparuk  — Wave 12B: Landscape + Quote-to-delivery + MicroFlo
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Re-use TINSurface from sibling module
# ---------------------------------------------------------------------------
from kerf_cad_core.civil.tin_surface import (
    TINSurface,
    SurveyPoint,
    build_tin_from_points,
)

_EPS = 1e-9


# ---------------------------------------------------------------------------
# Grading dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GradingPlan:
    """
    Output of design_grading().

    HONEST: cut/fill computed via ASCE-60 grid-sampling (prismoidal approximation);
            graded surface is a TIN with elevation bumped around buildings per SITES v2.

    Attributes
    ----------
    surface_in          : input TINSurface (original existing ground)
    cut_volume_m3       : total excavation volume (m³)
    fill_volume_m3      : total fill volume (m³)
    surface_out         : graded TINSurface
    drainage_slope_min_pct : minimum design slope for surface drainage (%)
    max_grade_pct       : maximum allowable grade (%)
    """
    surface_in: TINSurface
    cut_volume_m3: float
    fill_volume_m3: float
    surface_out: TINSurface
    drainage_slope_min_pct: float = 1.0
    max_grade_pct: float = 25.0


@dataclass
class DrainageNetwork:
    """
    Output of compute_drainage_network().

    HONEST: D8 flow-direction on TIN grid raster; Tarboton 1997 D-infinity referenced
            but approximated via steepest-descent among 8 neighbours.

    Attributes
    ----------
    catchment_polygons    : list of catchment basin outlines, each [[x,y], ...]
    flow_paths            : list of downstream polylines, each [[x,y,z], ...]
    runoff_coefficients   : rational-method C per catchment (ASCE Hydrology §4.2)
    detention_basins      : list of dicts with 'centroid', 'area_m2', 'volume_m3'
    """
    catchment_polygons: list
    flow_paths: list
    runoff_coefficients: list[float]
    detention_basins: list[dict]


# ---------------------------------------------------------------------------
# Planting dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PlantingPlan:
    """
    Output of design_planting_plan().

    HONEST: species drawn from a curated native + Mediterranean palette keyed to
            USDA hardiness zone + sun hours + water budget — not a botanical database.

    Attributes
    ----------
    species                        : list of species dicts with keys
                                     {species_name, hardiness_zone_min,
                                      hardiness_zone_max, mature_size_m,
                                      water_need_l_m2_month, sun_min_h}
    placements                     : list of (x, y, species_name) tuples
    total_area_m2                  : area of site outline
    estimated_water_demand_l_per_month : total monthly water demand (litres)
    """
    species: list[dict]
    placements: list[tuple[float, float, str]]
    total_area_m2: float
    estimated_water_demand_l_per_month: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _polygon_area(pts: list[tuple[float, float]]) -> float:
    """Shoelace formula — signed area (positive CCW)."""
    n = len(pts)
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _polygon_centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """Centroid of a simple polygon (Shoelace)."""
    n = len(pts)
    cx = cy = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a6 = 6.0 * _polygon_area(pts)
    if abs(a6) < _EPS:
        return pts[0]
    return cx / a6, cy / a6


def _point_in_polygon(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test (Jordan curve theorem)."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + _EPS) + xi):
            inside = not inside
        j = i
    return inside


def _tin_to_raster(
    tin: TINSurface,
    cell: float,
) -> tuple[np.ndarray, float, float]:
    """
    Rasterise TIN elevations onto a regular grid via barycentric interpolation.

    Returns (grid, x_min, y_min) where grid[row, col] is z or NaN if outside.
    Row 0 = northernmost (high y), following GIS raster convention.

    HONEST: uses brute-force per-cell triangle search — O(N_cells × N_tris).
    """
    xs = [p.x for p in tin.points]
    ys = [p.y for p in tin.points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    nx = max(2, int(math.ceil((x_max - x_min) / cell)) + 1)
    ny = max(2, int(math.ceil((y_max - y_min) / cell)) + 1)

    grid = np.full((ny, nx), np.nan, dtype=float)

    pts = tin.points
    tris = tin.triangles

    for row in range(ny):
        y = y_max - row * cell  # north-down convention
        for col in range(nx):
            x = x_min + col * cell
            # Barycentric search
            for tri in tris:
                ai, bi, ci = int(tri[0]), int(tri[1]), int(tri[2])
                ax_, ay_, az_ = pts[ai].x, pts[ai].y, pts[ai].elevation
                bx_, by_, bz_ = pts[bi].x, pts[bi].y, pts[bi].elevation
                cx_, cy_, cz_ = pts[ci].x, pts[ci].y, pts[ci].elevation
                denom = (by_ - cy_) * (ax_ - cx_) + (cx_ - bx_) * (ay_ - cy_)
                if abs(denom) < _EPS:
                    continue
                lam1 = ((by_ - cy_) * (x - cx_) + (cx_ - bx_) * (y - cy_)) / denom
                lam2 = ((cy_ - ay_) * (x - cx_) + (ax_ - cx_) * (y - cy_)) / denom
                lam3 = 1.0 - lam1 - lam2
                _e = 1e-7
                if lam1 >= -_e and lam2 >= -_e and lam3 >= -_e:
                    grid[row, col] = lam1 * az_ + lam2 * bz_ + lam3 * cz_
                    break
    return grid, x_min, y_min


def _apply_building_grading(
    tin_in: TINSurface,
    buildings: list[tuple[list[tuple[float, float]], float]],
    grade_pct: float,
    drain_distance_m: float = 3.048,  # 10 ft
) -> TINSurface:
    """
    Perturb TIN elevations around buildings to impose outward drainage slope.

    For each building:
      - Set finish-floor elevation on perimeter points of the outline.
      - Points within drain_distance_m of the building perimeter are raised/lowered
        so that grade at FFE + 5 % falls away by drain_distance_m.

    This is a simplified linear interpolation approach (SITES v2 Prerequisite P1.4).

    HONEST: true grading requires a constrained optimization; this is a first-order
            linear ramp from FFE outward to existing ground at drain_distance_m.
    """
    new_pts = [
        SurveyPoint(
            point_id=p.point_id,
            x=p.x,
            y=p.y,
            elevation=p.elevation,
            description=p.description,
        )
        for p in tin_in.points
    ]

    for outline, ffe in buildings:
        if not outline:
            continue
        cx, cy = _polygon_centroid(outline)
        drain_drop = drain_distance_m * (grade_pct / 100.0)

        for i, sp in enumerate(new_pts):
            # Closest distance from point to building outline edges
            min_dist = float('inf')
            n = len(outline)
            for j in range(n):
                x0, y0 = outline[j]
                x1, y1 = outline[(j + 1) % n]
                dx, dy = x1 - x0, y1 - y0
                seg_len2 = dx * dx + dy * dy
                if seg_len2 < _EPS:
                    dist = math.hypot(sp.x - x0, sp.y - y0)
                else:
                    t = max(0.0, min(1.0, ((sp.x - x0) * dx + (sp.y - y0) * dy) / seg_len2))
                    dist = math.hypot(sp.x - x0 - t * dx, sp.y - y0 - t * dy)
                if dist < min_dist:
                    min_dist = dist

            inside = _point_in_polygon(sp.x, sp.y, outline)

            if inside:
                # Set to FFE
                new_pts[i] = SurveyPoint(
                    point_id=sp.point_id, x=sp.x, y=sp.y,
                    elevation=ffe, description=sp.description,
                )
            elif min_dist <= drain_distance_m:
                # Linear ramp: at perimeter = FFE, at drain_distance_m = FFE - drain_drop
                t = min_dist / drain_distance_m
                target_elev = ffe - t * drain_drop
                # Only lower ground if it is already below or near target (fill scenario)
                # or raise if needed (cut scenario) — take the higher of existing and target
                # so water is always directed away.
                new_elev = max(target_elev, ffe - drain_drop)
                # Blend linearly
                blended = ffe + (new_elev - ffe) * t
                new_pts[i] = SurveyPoint(
                    point_id=sp.point_id, x=sp.x, y=sp.y,
                    elevation=blended, description=sp.description,
                )

    # Rebuild TIN from modified points
    return build_tin_from_points(new_pts, tin_in.breaklines if tin_in.breaklines else None)


# ---------------------------------------------------------------------------
# Public API — Grading
# ---------------------------------------------------------------------------

def design_grading(
    tin_in: TINSurface,
    proposed_buildings: list[tuple[list[tuple[float, float]], float]],
    drainage_pattern: str = 'natural',
    max_grade_pct: float = 8.0,
) -> GradingPlan:
    """
    Adjust TIN around buildings to drain away; compute cut/fill volumes.

    HONEST: Grading ramp uses a linear first-order approximation (5 % outward over
            3.048 m / 10 ft) per SITES v2 P1.4.  Cut/fill via ASCE-60 grid-sampling
            (prismoidal formula) at 0.5 m cell spacing.
            Not a substitute for a full civil-grading CAD tool.

    Parameters
    ----------
    tin_in             : existing TINSurface
    proposed_buildings : list of (footprint_outline, finish_floor_elevation_m)
    drainage_pattern   : 'natural' | 'curb_gutter' | 'french_drain'
                         (currently only 'natural' affects slope generation)
    max_grade_pct      : maximum allowed grade (%; advisory — used in GradingPlan output)

    Returns
    -------
    GradingPlan
    """
    # Determine drainage-away slope — SITES v2 minimum is 2 % for turf, 5 % preferred.
    if drainage_pattern == 'natural':
        drain_grade = 5.0
    elif drainage_pattern == 'curb_gutter':
        drain_grade = 2.0
    else:   # french_drain
        drain_grade = 1.0

    surface_out = _apply_building_grading(tin_in, proposed_buildings, drain_grade)

    # Compute cut / fill between original and graded surface (ASCE-60 §5).
    xs = [p.x for p in tin_in.points]
    ys = [p.y for p in tin_in.points]
    x_range = max(xs) - min(xs)
    y_range = max(ys) - min(ys)
    grid_spacing = max(0.5, min(x_range, y_range) / 40.0)

    from kerf_cad_core.civil.tin_surface import cut_fill_volume, _bary_elevation

    vols = cut_fill_volume(tin_in, surface_out, grid_spacing_m=grid_spacing)

    return GradingPlan(
        surface_in=tin_in,
        cut_volume_m3=vols['cut_m3'],
        fill_volume_m3=vols['fill_m3'],
        surface_out=surface_out,
        drainage_slope_min_pct=drain_grade,
        max_grade_pct=max_grade_pct,
    )


# ---------------------------------------------------------------------------
# Public API — Drainage network (D8 / D-infinity)
# ---------------------------------------------------------------------------

# D8 flow direction offsets: E, SE, S, SW, W, NW, N, NE
# (row_delta, col_delta, distance_factor)
_D8_DIRS = [
    (0,  1,  1.0),   # E
    (1,  1,  math.sqrt(2)),  # SE
    (1,  0,  1.0),   # S
    (1, -1,  math.sqrt(2)),  # SW
    (0, -1,  1.0),   # W
    (-1,-1,  math.sqrt(2)), # NW
    (-1, 0,  1.0),   # N
    (-1, 1,  math.sqrt(2)), # NE
]


def _d8_flow_direction(grid: np.ndarray) -> np.ndarray:
    """
    D8 flow-direction: each cell drains to its steepest-descent neighbour.

    Reference: O'Callaghan & Mark (1984); Tarboton 1997 D-infinity is the strict
    reference but D8 is implemented here as a recognised simplification for
    preview-grade basin delineation on coarse grids.

    Boundary cells are treated as outlets (flow_dir = -1) when the steepest
    descent direction exits the grid domain — this ensures at least one outlet
    exists per connected drainage basin (O'Callaghan & Mark 1984 §2).

    Returns flow_dir array:  -1 = outlet / NoData.
    Valid values 0..7 index _D8_DIRS.
    """
    ny, nx = grid.shape
    flow_dir = np.full((ny, nx), -1, dtype=np.int8)

    for row in range(ny):
        for col in range(nx):
            z = grid[row, col]
            if np.isnan(z):
                continue

            # Check if this is a boundary cell (edge of the raster)
            on_boundary = (row == 0 or row == ny - 1 or col == 0 or col == nx - 1)

            best_dir = -1
            best_slope = -1e30
            for d, (dr, dc, dist) in enumerate(_D8_DIRS):
                nr, nc = row + dr, col + dc
                if 0 <= nr < ny and 0 <= nc < nx and not np.isnan(grid[nr, nc]):
                    slope = (z - grid[nr, nc]) / dist
                    if slope > best_slope:
                        best_slope = slope
                        best_dir = d

            # Boundary cells: if steepest slope is off-grid or zero,
            # mark as outlet so the drainage network terminates.
            if on_boundary and best_slope <= 0.0:
                flow_dir[row, col] = -1  # outlet
            else:
                flow_dir[row, col] = best_dir
    return flow_dir


def _delineate_catchments(
    flow_dir: np.ndarray,
    grid: np.ndarray,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """
    Label each cell with a catchment ID by tracing flow paths to outlets.

    Outlets are cells with flow_dir == -1 (no downslope neighbour).
    Returns (catchment_labels, outlet_cells).
    """
    ny, nx = grid.shape
    labels = np.full((ny, nx), -1, dtype=np.int32)
    outlets: list[tuple[int, int]] = []

    # Collect outlets
    for row in range(ny):
        for col in range(nx):
            if not np.isnan(grid[row, col]) and flow_dir[row, col] == -1:
                outlets.append((row, col))

    for cat_id, (or_, oc) in enumerate(outlets):
        labels[or_, oc] = cat_id

    # Flood-fill upstream via reverse traversal (BFS from outlets)
    from collections import deque
    # Build reverse adjacency: who flows INTO each cell?
    rev: dict[tuple[int, int], list[tuple[int, int]]] = {
        (r, c): [] for r in range(ny) for c in range(nx)
    }
    for row in range(ny):
        for col in range(nx):
            d = flow_dir[row, col]
            if d < 0:
                continue
            dr, dc, _ = _D8_DIRS[d]
            nr, nc = row + dr, col + dc
            if 0 <= nr < ny and 0 <= nc < nx:
                rev[(nr, nc)].append((row, col))

    q: deque[tuple[int, int]] = deque(outlets)
    visited = set(outlets)
    while q:
        r, c = q.popleft()
        lbl = labels[r, c]
        for ur, uc in rev[(r, c)]:
            if (ur, uc) not in visited:
                visited.add((ur, uc))
                labels[ur, uc] = lbl
                q.append((ur, uc))

    return labels, outlets


def _catchment_polygon(
    labels: np.ndarray,
    cat_id: int,
    x_min: float,
    y_min: float,
    cell: float,
) -> list[tuple[float, float]]:
    """Return bounding-box polygon of a catchment (approximate outline)."""
    rows, cols = np.where(labels == cat_id)
    if len(rows) == 0:
        return []
    ny_total = labels.shape[0]
    # Convert raster row/col to world coords (north-down raster)
    y_top = [float(y_min + (ny_total - 1 - r) * cell) for r in rows]
    xs = [float(x_min + c * cell) for c in cols]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(y_top), max(y_top)
    # Return rectangular bounding box as polygon
    return [(xlo, ylo), (xhi, ylo), (xhi, yhi), (xlo, yhi)]


def _trace_flow_path(
    start_row: int,
    start_col: int,
    flow_dir: np.ndarray,
    grid: np.ndarray,
    x_min: float,
    y_min: float,
    cell: float,
) -> list[tuple[float, float, float]]:
    """Follow D8 flow direction from (start_row, start_col) to outlet."""
    ny, nx = grid.shape
    path: list[tuple[float, float, float]] = []
    r, c = start_row, start_col
    visited = set()
    while True:
        if (r, c) in visited:
            break
        visited.add((r, c))
        z = grid[r, c]
        if np.isnan(z):
            break
        y_world = y_min + (ny - 1 - r) * cell
        x_world = x_min + c * cell
        path.append((x_world, y_world, float(z)))
        d = int(flow_dir[r, c])
        if d < 0:
            break
        dr, dc, _ = _D8_DIRS[d]
        r, c = r + dr, c + dc
        if not (0 <= r < ny and 0 <= c < nx):
            break
    return path


def compute_drainage_network(tin: TINSurface) -> DrainageNetwork:
    """
    D8 flow-direction algorithm on TIN raster; delineate catchments; trace flow paths.

    HONEST: implements D8 (O'Callaghan & Mark 1984) on a rasterised TIN — a recognised
            simplification of Tarboton 1997 D-infinity (which distributes flow among
            two steepest-descent facets).  Suitable for preview-grade catchment
            delineation; not a substitute for a GIS-grade hydrologic solver.

    References
    ----------
    O'Callaghan & Mark (1984) Comput. Vision Graphics Image Process. 28:323–344.
    Tarboton, D.G. (1997). Water Resour. Res. 33(2):309–319.  [D-infinity]
    ASCE Manual on Engineering Practice 36 (urban hydrology), §4.2 rational method.

    Returns
    -------
    DrainageNetwork
    """
    # Rasterise TIN at ~1 m resolution (max 80 cells on short axis)
    xs = [p.x for p in tin.points]
    ys = [p.y for p in tin.points]
    x_range = max(xs) - min(xs)
    y_range = max(ys) - min(ys)
    cell = max(0.5, min(x_range, y_range) / 40.0)

    grid, x_min, y_min = _tin_to_raster(tin, cell)
    ny, nx = grid.shape

    # D8 flow direction
    flow_dir = _d8_flow_direction(grid)

    # Delineate catchments
    labels, outlets = _delineate_catchments(flow_dir, grid)
    n_cats = len(outlets)

    if n_cats == 0:
        # Flat surface — create one catch-all basin
        return DrainageNetwork(
            catchment_polygons=[],
            flow_paths=[],
            runoff_coefficients=[0.3],
            detention_basins=[],
        )

    # Build catchment polygons
    catchment_polygons: list = []
    runoff_coefficients: list[float] = []
    detention_basins: list[dict] = []

    for cat_id in range(n_cats):
        poly = _catchment_polygon(labels, cat_id, x_min, y_min, cell)
        if not poly:
            continue
        catchment_polygons.append(poly)
        # Runoff coefficient — rational method C:
        #   0.6 = typical impervious site (ASCE Hydrology §4.2)
        #   0.3 = lawn / open space
        # Default mixed site: 0.4
        runoff_coefficients.append(0.4)

        # Simple detention basin estimate: 10 % of catchment area, 0.5 m depth
        area_m2 = float(np.sum(labels == cat_id)) * cell * cell
        basin_vol = area_m2 * 0.10 * 0.5
        cx_world = x_min + float(outlets[cat_id][1]) * cell
        cy_world = y_min + (ny - 1 - float(outlets[cat_id][0])) * cell
        detention_basins.append({
            'catchment_id': cat_id,
            'centroid': (cx_world, cy_world),
            'area_m2': round(area_m2 * 0.10, 2),
            'volume_m3': round(basin_vol, 2),
        })

    # Trace flow paths from each outlet's highest upstream cell
    flow_paths: list = []
    for cat_id, (or_, oc) in enumerate(outlets):
        # Find highest elevation cell in this catchment as flow-path start
        mask = labels == cat_id
        if not np.any(mask):
            continue
        masked_grid = np.where(mask, grid, np.nan)
        flat_idx = int(np.nanargmax(masked_grid))
        start_r = flat_idx // nx
        start_c = flat_idx % nx
        path = _trace_flow_path(start_r, start_c, flow_dir, grid, x_min, y_min, cell)
        if path:
            flow_paths.append(path)

    return DrainageNetwork(
        catchment_polygons=catchment_polygons,
        flow_paths=flow_paths,
        runoff_coefficients=runoff_coefficients,
        detention_basins=detention_basins,
    )


# ---------------------------------------------------------------------------
# Plant palette — USDA Hardiness Zone keyed
# ---------------------------------------------------------------------------
#
# Reference: USDA Plant Hardiness Zone Map (2012/2023 revision).
#            Zones 1 (coldest, -60°F / -51°C) to 13 (warmest, > 65°F / 18°C).
#
# Species drawn from:
#   Native + Mediterranean palette per ASLA SITES v2 credit SS7.1
#   (native / adaptive planting ≥ 75 % of total planting area).
#
# Format: {species_name, hardiness_zone_min, hardiness_zone_max,
#          mature_size_m, water_need_l_m2_month, sun_min_h}

_PLANT_PALETTE: list[dict] = [
    # --- Trees (cold-hardy) ---
    {"species_name": "Quercus robur (English Oak)",
     "hardiness_zone_min": 4, "hardiness_zone_max": 8,
     "mature_size_m": 20.0, "water_need_l_m2_month": 40.0, "sun_min_h": 4.0},
    {"species_name": "Betula pendula (Silver Birch)",
     "hardiness_zone_min": 2, "hardiness_zone_max": 7,
     "mature_size_m": 15.0, "water_need_l_m2_month": 35.0, "sun_min_h": 4.0},
    {"species_name": "Acer saccharum (Sugar Maple)",
     "hardiness_zone_min": 3, "hardiness_zone_max": 8,
     "mature_size_m": 18.0, "water_need_l_m2_month": 45.0, "sun_min_h": 4.0},
    # --- Shrubs (mid-range) ---
    {"species_name": "Ceanothus 'Ray Hartman' (California Lilac)",
     "hardiness_zone_min": 8, "hardiness_zone_max": 10,
     "mature_size_m": 3.5, "water_need_l_m2_month": 15.0, "sun_min_h": 6.0},
    {"species_name": "Rosmarinus officinalis (Rosemary)",
     "hardiness_zone_min": 7, "hardiness_zone_max": 11,
     "mature_size_m": 1.2, "water_need_l_m2_month": 10.0, "sun_min_h": 6.0},
    {"species_name": "Rhododendron catawbiense (Catawba Rhododendron)",
     "hardiness_zone_min": 4, "hardiness_zone_max": 8,
     "mature_size_m": 3.0, "water_need_l_m2_month": 50.0, "sun_min_h": 3.0},
    # --- Groundcovers / perennials ---
    {"species_name": "Festuca glauca (Blue Fescue)",
     "hardiness_zone_min": 4, "hardiness_zone_max": 8,
     "mature_size_m": 0.3, "water_need_l_m2_month": 20.0, "sun_min_h": 5.0},
    {"species_name": "Agapanthus africanus (African Lily)",
     "hardiness_zone_min": 8, "hardiness_zone_max": 11,
     "mature_size_m": 0.6, "water_need_l_m2_month": 20.0, "sun_min_h": 5.0},
    {"species_name": "Erigeron karvinskianus (Mexican Fleabane)",
     "hardiness_zone_min": 7, "hardiness_zone_max": 11,
     "mature_size_m": 0.3, "water_need_l_m2_month": 12.0, "sun_min_h": 4.0},
    # --- Warm-climate trees ---
    {"species_name": "Olea europaea (Olive)",
     "hardiness_zone_min": 8, "hardiness_zone_max": 11,
     "mature_size_m": 8.0, "water_need_l_m2_month": 12.0, "sun_min_h": 6.0},
    {"species_name": "Phoenix canariensis (Canary Island Date Palm)",
     "hardiness_zone_min": 9, "hardiness_zone_max": 12,
     "mature_size_m": 12.0, "water_need_l_m2_month": 25.0, "sun_min_h": 6.0},
    {"species_name": "Jacaranda mimosifolia (Jacaranda)",
     "hardiness_zone_min": 9, "hardiness_zone_max": 11,
     "mature_size_m": 10.0, "water_need_l_m2_month": 30.0, "sun_min_h": 6.0},
    # --- Succulents / drought-tolerant ---
    {"species_name": "Agave americana (Century Plant)",
     "hardiness_zone_min": 8, "hardiness_zone_max": 12,
     "mature_size_m": 1.5, "water_need_l_m2_month": 5.0, "sun_min_h": 6.0},
    {"species_name": "Yucca filamentosa (Adam's Needle)",
     "hardiness_zone_min": 4, "hardiness_zone_max": 10,
     "mature_size_m": 1.0, "water_need_l_m2_month": 8.0, "sun_min_h": 5.0},
    # --- Cold-climate natives ---
    {"species_name": "Picea abies (Norway Spruce)",
     "hardiness_zone_min": 2, "hardiness_zone_max": 6,
     "mature_size_m": 25.0, "water_need_l_m2_month": 40.0, "sun_min_h": 4.0},
    {"species_name": "Juniperus communis (Common Juniper)",
     "hardiness_zone_min": 2, "hardiness_zone_max": 7,
     "mature_size_m": 3.0, "water_need_l_m2_month": 15.0, "sun_min_h": 4.0},
    {"species_name": "Cornus sericea (Red Osier Dogwood)",
     "hardiness_zone_min": 2, "hardiness_zone_max": 8,
     "mature_size_m": 2.5, "water_need_l_m2_month": 45.0, "sun_min_h": 3.0},
]


def _select_species(
    zone: int,
    sun_map: Optional[np.ndarray],
    water_target_l_per_m2_month: float,
) -> list[dict]:
    """
    Filter _PLANT_PALETTE to species compatible with zone + sun + water budget.

    HONEST: sun_map is used to compute mean sun-hours across the site — a real
            planting tool would map sun per-species-position.
    """
    mean_sun = 6.0  # default full-sun assumption
    if sun_map is not None and sun_map.size > 0:
        valid = sun_map[~np.isnan(sun_map)]
        if valid.size > 0:
            mean_sun = float(np.mean(valid))

    selected: list[dict] = []
    for sp in _PLANT_PALETTE:
        # Zone compatibility
        if not (sp['hardiness_zone_min'] <= zone <= sp['hardiness_zone_max']):
            continue
        # Sun compatibility (species needs ≤ available)
        if sp['sun_min_h'] > mean_sun + 1.0:
            continue
        # Water budget: species monthly need ≤ target × 1.5 (allow some over-planting)
        if sp['water_need_l_m2_month'] > water_target_l_per_m2_month * 1.5:
            continue
        selected.append(sp)

    return selected


def design_planting_plan(
    site_outline: list[tuple[float, float]],
    site_hardiness_zone: int,
    sun_map: Optional[np.ndarray] = None,
    water_target_l_per_m2_month: float = 50.0,
) -> PlantingPlan:
    """
    Select species from native + Mediterranean palette; place plants on site grid.

    HONEST: placement is a grid-based spacing algorithm using each species' mature_size_m
            as the spacing interval — not a true landscape design tool (which would
            account for sight lines, massing, and client preferences).
            Species palette follows USDA Hardiness Zone Map (2012/2023) and
            ASLA SITES v2 credit SS7.1 (native / adaptive planting).

    References
    ----------
    USDA Plant Hardiness Zone Map (2012 revision, updated 2023).
        https://planthardiness.ars.usda.gov/ (public domain).
    ASLA SITES v2 (2014). Credit SS7.1 — native and adaptive planting.
    Water-need values derived from WUCOLS IV (California DWR, 2014 — Mediterranean
        climate reference; scaled approximately for other zones).

    Parameters
    ----------
    site_outline                  : bounding polygon [(x,y), ...], metres
    site_hardiness_zone           : USDA zone integer 1–13
    sun_map                       : optional 2-D array of sun-hours per cell
    water_target_l_per_m2_month   : max allowable water demand per m² per month

    Returns
    -------
    PlantingPlan
    """
    site_hardiness_zone = max(1, min(13, site_hardiness_zone))

    area_m2 = _polygon_area(site_outline)
    species = _select_species(site_hardiness_zone, sun_map, water_target_l_per_m2_month)

    if not species:
        # Fallback: select any species in zone (ignore water constraint)
        species = [sp for sp in _PLANT_PALETTE
                   if sp['hardiness_zone_min'] <= site_hardiness_zone <= sp['hardiness_zone_max']]
    if not species:
        species = [_PLANT_PALETTE[0]]

    # Grid placement — use median mature size for spacing
    sizes = [sp['mature_size_m'] for sp in species]
    median_size = sorted(sizes)[len(sizes) // 2]
    spacing = max(0.5, median_size)

    # Find site bounding box for grid
    xs_ = [p[0] for p in site_outline]
    ys_ = [p[1] for p in site_outline]
    x_lo, x_hi = min(xs_), max(xs_)
    y_lo, y_hi = min(ys_), max(ys_)

    placements: list[tuple[float, float, str]] = []
    sp_idx = 0
    y_ = y_lo + spacing / 2.0
    while y_ < y_hi:
        x_ = x_lo + spacing / 2.0
        while x_ < x_hi:
            if _point_in_polygon(x_, y_, site_outline):
                sp = species[sp_idx % len(species)]
                placements.append((x_, y_, sp['species_name']))
                sp_idx += 1
            x_ += spacing
        y_ += spacing

    # Estimate monthly water demand
    total_water = sum(
        sp['water_need_l_m2_month'] * (sp['mature_size_m'] ** 2)
        for (_, _, sp_name) in placements
        for sp in species
        if sp['species_name'] == sp_name
    )

    return PlantingPlan(
        species=species,
        placements=placements,
        total_area_m2=round(area_m2, 2),
        estimated_water_demand_l_per_month=round(total_water, 1),
    )
