"""
kerf_cad_core.earthworks.grading — site earthworks & grading calculations.

Pure-Python, math-only.  No OCC or external dependency beyond the standard
library.  All functions emit Python warnings (never raise) when computed
results indicate an out-of-range or advisory condition.

Functions
---------
cross_section_level         — prismatic level/road cross-section area
cross_section_two_level     — two-level section (different side slopes)
cross_section_three_level   — three-level (centre-height + two side heights)
cross_section_by_coords     — arbitrary section area by the shoelace formula

earthwork_volume            — volume between two stations (average-end-area
                              and prismoidal correction)

borrow_pit_volume           — grid / spot-elevation borrow-pit volume

cut_fill_balance            — balance cut ↔ fill with shrinkage/swell
                              (bank ↔ compacted ↔ loose factors)

mass_haul                   — cumulative mass-haul ordinates, balance points,
                              free-haul / overhaul separation, economic haul
                              distance and overhaul cost, borrow/waste flag

proctor_optimum             — Proctor max dry density & OMC interpolation
                              from a set of (moisture, dry_density) data pairs

relative_compaction         — relative compaction % from field dry density
                              and lab MDD; lift thickness & passes estimate

lift_productivity           — compaction-pass productivity (m²/h, m³/h)

slope_daylight_offset       — horizontal offset to daylight for cut or fill
                              given design grade, existing ground, and batter

trench_volume               — trench excavation volume and shoring/bedding
                              quantities

dewatering_pump_rate        — simplified well-point dewatering pump rate
                              (Dupuit–Thiem unconfined aquifer)

Distinct from
-------------
  civil/alignment  — road horizontal/vertical geometry curves
  geotech/         — bearing capacity, settlement, slope stability, pile
  surveying/       — COGO, traverse, area by coordinates (plan-view)
  pavement/        — pavement structural design (AASHTO/PCA)

References
----------
Peurifoy, Schexnayder, Shapira, "Construction Planning, Equipment & Methods",
  8th ed., McGraw-Hill 2011.
USBR "Design of Small Canal Structures", 1978.
AASHTO "Standard Specifications for Highway Bridges", 17th ed., 2002.
ASTM D698-12e2 / D1557-12e1 — Standard Proctor / Modified Proctor test.
Cedergren, H.R., "Drainage of Highway and Airfield Pavements", Wiley 1974.
Jumikis, A.R., "Soil Mechanics", 1962.

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Sequence


# ---------------------------------------------------------------------------
# Cross-section area helpers
# ---------------------------------------------------------------------------

def cross_section_level(
    formation_width: float,
    centre_height: float,
    side_slope: float,
) -> dict:
    """Level cross-section (prismatic) area for cut or fill.

    The ground is assumed level across the section.  The road formation has
    width *formation_width* (m) and a constant *centre_height* (m) of cut or
    fill.  *side_slope* is the horizontal distance per 1 unit vertical (H:V),
    e.g. 1.5 for a 1.5:1 slope.

    Parameters
    ----------
    formation_width : float
        Road formation / subgrade width (m).  Must be > 0.
    centre_height : float
        Height of cut or fill at the centre-line (m).  Must be >= 0.
    side_slope : float
        Batter (H:V).  Must be >= 0.

    Returns
    -------
    dict
        area_m2  — cross-section area (m²)
        half_width_m — total half-width from centreline to daylight (m)
        warnings — list of advisory strings
    """
    warns: list[str] = []
    if formation_width <= 0:
        raise ValueError("formation_width must be > 0")
    if centre_height < 0:
        raise ValueError("centre_height must be >= 0")
    if side_slope < 0:
        raise ValueError("side_slope must be >= 0")

    b = formation_width
    h = centre_height
    s = side_slope

    # Area = (b + s*h) * h
    area = (b + s * h) * h
    half_width = b / 2.0 + s * h

    if centre_height == 0.0:
        warns.append("centre_height=0: zero cross-section area")
    return {"area_m2": area, "half_width_m": half_width, "warnings": warns}


def cross_section_two_level(
    formation_width: float,
    centre_height: float,
    left_slope: float,
    right_slope: float,
) -> dict:
    """Two-level (unsymmetrical) cross-section area.

    Each side has its own batter.  Used where the existing ground is not level
    or cut/fill batters differ left and right.

    Parameters
    ----------
    formation_width : float
        Formation width (m). > 0.
    centre_height : float
        Cut/fill height at centreline (m). >= 0.
    left_slope, right_slope : float
        Batter H:V for each side. >= 0.

    Returns
    -------
    dict
        area_m2, left_half_width_m, right_half_width_m, warnings
    """
    warns: list[str] = []
    if formation_width <= 0:
        raise ValueError("formation_width must be > 0")
    if centre_height < 0:
        raise ValueError("centre_height must be >= 0")
    if left_slope < 0 or right_slope < 0:
        raise ValueError("slopes must be >= 0")

    b = formation_width
    h = centre_height

    left_hw = b / 2.0 + left_slope * h
    right_hw = b / 2.0 + right_slope * h

    # Average trapezoid: (b_top + b_bottom) / 2 * h
    # Top width = left_hw + right_hw, bottom = b (formation level)
    area = ((left_hw + right_hw) + b) / 2.0 * h

    if h == 0.0:
        warns.append("centre_height=0: zero cross-section area")
    return {
        "area_m2": area,
        "left_half_width_m": left_hw,
        "right_half_width_m": right_hw,
        "warnings": warns,
    }


def cross_section_three_level(
    formation_width: float,
    centre_height: float,
    left_height: float,
    right_height: float,
    side_slope: float,
) -> dict:
    """Three-level cross-section (centre + left + right heights given).

    Standard highway earthwork formula for three-level sections where the
    heights at the left edge, centreline, and right edge of the formation are
    measured independently.

    Parameters
    ----------
    formation_width : float
        Formation width (m). > 0.
    centre_height : float
        Height at centreline (m). >= 0.
    left_height : float
        Height at left formation edge (m). >= 0.
    right_height : float
        Height at right formation edge (m). >= 0.
    side_slope : float
        Batter H:V. >= 0.

    Returns
    -------
    dict
        area_m2, left_daylight_m, right_daylight_m, warnings
    """
    warns: list[str] = []
    if formation_width <= 0:
        raise ValueError("formation_width must be > 0")
    for name, val in [("centre_height", centre_height),
                      ("left_height", left_height),
                      ("right_height", right_height)]:
        if val < 0:
            raise ValueError(f"{name} must be >= 0")
    if side_slope < 0:
        raise ValueError("side_slope must be >= 0")

    b = formation_width
    hc = centre_height
    hl = left_height
    hr = right_height
    s = side_slope

    # Daylight offsets from each edge
    left_day = b / 2.0 + s * hl
    right_day = b / 2.0 + s * hr

    # Three-level formula (Peurifoy):
    #   A = (b/2)(hl + hr) + s*(hl² + hr²)/2 + ... simplified via shoelace
    # Use shoelace on the 5-point cross-section polygon:
    #   (-left_day, 0), (-b/2, hl), (0, hc), (b/2, hr), (right_day, 0)
    xs = [-left_day, -b / 2.0, 0.0, b / 2.0, right_day]
    ys = [0.0, hl, hc, hr, 0.0]
    area = abs(_shoelace(xs, ys))

    if max(hc, hl, hr) == 0.0:
        warns.append("all heights=0: zero cross-section area")
    return {
        "area_m2": area,
        "left_daylight_m": left_day,
        "right_daylight_m": right_day,
        "warnings": warns,
    }


def cross_section_by_coords(
    xs: Sequence[float],
    ys: Sequence[float],
) -> dict:
    """Cross-section area from arbitrary (x, y) coordinate pairs (shoelace).

    Parameters
    ----------
    xs, ys : sequence of float
        Ordered x and y coordinates of the closed cross-section polygon.
        Minimum 3 points.

    Returns
    -------
    dict
        area_m2, centroid_x, centroid_y, warnings
    """
    warns: list[str] = []
    xs_l = list(xs)
    ys_l = list(ys)
    if len(xs_l) != len(ys_l):
        raise ValueError("xs and ys must have the same length")
    n = len(xs_l)
    if n < 3:
        raise ValueError("At least 3 coordinate pairs required")

    area = abs(_shoelace(xs_l, ys_l))

    # Centroid
    cx = cy = 0.0
    a6 = 0.0
    for i in range(n):
        j = (i + 1) % n
        cross = xs_l[i] * ys_l[j] - xs_l[j] * ys_l[i]
        a6 += cross
        cx += (xs_l[i] + xs_l[j]) * cross
        cy += (ys_l[i] + ys_l[j]) * cross
    if abs(a6) < 1e-15:
        warns.append("degenerate polygon: near-zero area")
        cx = sum(xs_l) / n
        cy = sum(ys_l) / n
    else:
        cx /= 3.0 * a6
        cy /= 3.0 * a6

    return {"area_m2": area, "centroid_x": cx, "centroid_y": cy, "warnings": warns}


def _shoelace(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    s = 0.0
    for i in range(n):
        j = (i + 1) % n
        s += xs[i] * ys[j] - xs[j] * ys[i]
    return s / 2.0


# ---------------------------------------------------------------------------
# Earthwork volume between stations
# ---------------------------------------------------------------------------

def earthwork_volume(
    stations: Sequence[float],
    areas: Sequence[float],
    method: str = "average-end-area",
    prismoidal_corrections: Sequence[float] | None = None,
) -> dict:
    """Earthwork volume between a sequence of cross-section stations.

    Parameters
    ----------
    stations : sequence of float
        Station chainages (m), monotonically increasing.  Must have >= 2
        values.
    areas : sequence of float
        Cross-section areas (m²) at each station, same length as *stations*.
        Negative values are treated as fill, positive as cut (or caller may
        pass all-positive with separate sign convention).
    method : str
        'average-end-area' (default) or 'prismoidal'.
    prismoidal_corrections : sequence of float or None
        Per-interval prismoidal correction volume (m³).  Required when
        method='prismoidal'; one value per interval (len = len(stations)-1).

    Returns
    -------
    dict
        intervals       — list of per-interval dicts
                          {station_from, station_to, length_m, area_from_m2,
                           area_to_m2, volume_m3}
        total_volume_m3 — sum of interval volumes (m³)
        method          — echo of method used
        warnings        — advisory list
    """
    warns: list[str] = []
    st = list(stations)
    ar = list(areas)
    n = len(st)
    if n < 2:
        raise ValueError("At least 2 stations required")
    if len(ar) != n:
        raise ValueError("areas and stations must have the same length")
    for i in range(n - 1):
        if st[i + 1] <= st[i]:
            raise ValueError(f"stations must be strictly increasing (index {i})")

    if method not in ("average-end-area", "prismoidal"):
        raise ValueError("method must be 'average-end-area' or 'prismoidal'")

    if method == "prismoidal" and prismoidal_corrections is None:
        warns.append(
            "prismoidal method requested but no prismoidal_corrections supplied; "
            "falling back to average-end-area"
        )
        method = "average-end-area"

    pc: list[float] = []
    if method == "prismoidal":
        pc = list(prismoidal_corrections)  # type: ignore[arg-type]
        if len(pc) != n - 1:
            raise ValueError(
                "prismoidal_corrections must have length len(stations)-1"
            )

    intervals = []
    total = 0.0
    for i in range(n - 1):
        L = st[i + 1] - st[i]
        A1 = ar[i]
        A2 = ar[i + 1]
        vol_aea = L * (A1 + A2) / 2.0
        if method == "prismoidal":
            vol = vol_aea - pc[i]
        else:
            vol = vol_aea
        total += vol
        intervals.append({
            "station_from": st[i],
            "station_to": st[i + 1],
            "length_m": L,
            "area_from_m2": A1,
            "area_to_m2": A2,
            "volume_m3": vol,
        })

    if total < 0:
        warns.append(
            f"total_volume_m3={total:.3f} is negative — check area signs or "
            "swap cut/fill convention"
        )

    return {
        "intervals": intervals,
        "total_volume_m3": total,
        "method": method,
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Borrow-pit / grid volume
# ---------------------------------------------------------------------------

def borrow_pit_volume(
    grid_spacing_x: float,
    grid_spacing_y: float,
    existing_elevations: Sequence[Sequence[float]],
    design_elevation: float,
) -> dict:
    """Borrow-pit / spot-elevation grid volume by the four-quadrant method.

    Each grid node contributes h / (number of quadrants it belongs to).
    Corner nodes weight 1, edge nodes weight 2, interior nodes weight 4.

    Parameters
    ----------
    grid_spacing_x, grid_spacing_y : float
        Grid cell dimensions (m) in the x and y directions. > 0.
    existing_elevations : 2-D sequence
        Existing ground elevations (m) as a 2-D list [rows][cols].
        Each row must have the same number of columns.  Rows represent y
        stations; columns represent x stations.
    design_elevation : float
        Uniform design (formation) elevation (m).  Cut = existing > design;
        fill = existing < design.

    Returns
    -------
    dict
        total_volume_m3 — signed volume (positive = cut, negative = fill)
        cut_volume_m3   — cut portion (positive)
        fill_volume_m3  — fill portion (positive magnitude)
        node_weights    — 2-D list of weights used
        warnings
    """
    warns: list[str] = []
    if grid_spacing_x <= 0 or grid_spacing_y <= 0:
        raise ValueError("grid spacings must be > 0")

    grid = [list(row) for row in existing_elevations]
    nrows = len(grid)
    if nrows < 2:
        raise ValueError("At least 2 rows required")
    ncols = len(grid[0])
    if ncols < 2:
        raise ValueError("At least 2 columns required")
    for r, row in enumerate(grid):
        if len(row) != ncols:
            raise ValueError(f"Row {r} has inconsistent column count")

    cell_area = grid_spacing_x * grid_spacing_y
    total = 0.0
    cut = 0.0
    fill = 0.0
    weights = [[0.0] * ncols for _ in range(nrows)]

    for r in range(nrows):
        for c in range(ncols):
            # Weight by how many cells share this node
            on_row_edge = (r == 0 or r == nrows - 1)
            on_col_edge = (c == 0 or c == ncols - 1)
            if on_row_edge and on_col_edge:
                w = 1
            elif on_row_edge or on_col_edge:
                w = 2
            else:
                w = 4
            weights[r][c] = w
            h = grid[r][c] - design_elevation
            contrib = w * h * cell_area / 4.0
            total += contrib
            if contrib > 0:
                cut += contrib
            else:
                fill += abs(contrib)

    if total > 0:
        warns.append(
            f"Net result is cut ({total:.1f} m³ to remove); verify design elevation"
        )
    elif total < 0:
        warns.append(
            f"Net result is fill ({abs(total):.1f} m³ to import); verify borrow sources"
        )

    return {
        "total_volume_m3": total,
        "cut_volume_m3": cut,
        "fill_volume_m3": fill,
        "node_weights": weights,
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Cut & fill balance (bank ↔ compacted ↔ loose factors)
# ---------------------------------------------------------------------------

def cut_fill_balance(
    cut_volume_bank_m3: float,
    fill_volume_compacted_m3: float,
    shrinkage_factor: float = 1.0,
    swell_factor: float = 1.0,
    load_factor: float = 1.0,
) -> dict:
    """Balance cut and fill volumes accounting for shrinkage and swell.

    Volume states
    -------------
    Bank (BCM)       — in-situ, before excavation
    Loose (LCM)      — in the truck/scraper after excavation (expanded)
    Compacted (CCM)  — after compaction in the fill

    Conversion factors (ratios of BCM)
    -----------------------------------
    swell_factor     — loose / bank  (> 1 for typical soils, e.g. 1.25)
    shrinkage_factor — compacted / bank  (< 1 if material shrinks in fill,
                       e.g. 0.90 for sand-gravel, > 1 for expansive clay)
    load_factor      — bank / loose  (= 1 / swell_factor typically)

    Parameters
    ----------
    cut_volume_bank_m3 : float
        Available cut volume measured in bank measure (m³). >= 0.
    fill_volume_compacted_m3 : float
        Required fill volume in compacted measure (m³). >= 0.
    shrinkage_factor : float
        Compacted volume / bank volume (default 1.0 = no change).
        For sand: ~0.90; for heavy clay fill: ~1.05.
    swell_factor : float
        Loose volume / bank volume (default 1.0). Typical: 1.10–1.35.
    load_factor : float
        Bank volume / loose volume (default 1.0). = 1 / swell_factor.

    Returns
    -------
    dict
        cut_bank_m3           — input cut (bank)
        fill_compacted_m3     — input fill (compacted)
        fill_bank_equivalent_m3 — fill requirement converted to bank measure
        fill_loose_m3         — fill volume as loose measure
        surplus_deficit_bank_m3 — positive = surplus cut, negative = borrow needed
        borrow_needed_bank_m3 — > 0 if more material must be imported
        waste_available_bank_m3 — > 0 if excess cut must be wasted
        warnings
    """
    warns: list[str] = []
    if cut_volume_bank_m3 < 0:
        raise ValueError("cut_volume_bank_m3 must be >= 0")
    if fill_volume_compacted_m3 < 0:
        raise ValueError("fill_volume_compacted_m3 must be >= 0")
    if shrinkage_factor <= 0:
        raise ValueError("shrinkage_factor must be > 0")
    if swell_factor <= 0:
        raise ValueError("swell_factor must be > 0")
    if load_factor <= 0:
        raise ValueError("load_factor must be > 0")

    # Convert fill (compacted) to bank equivalent
    fill_bank = fill_volume_compacted_m3 / shrinkage_factor
    fill_loose = fill_bank * swell_factor

    surplus = cut_volume_bank_m3 - fill_bank
    borrow = max(0.0, -surplus)
    waste = max(0.0, surplus)

    if borrow > 0:
        warns.append(
            f"Unbalanced earthwork: borrow {borrow:.1f} m³ (bank) required — "
            "locate borrow pit or reduce fill"
        )
    if waste > 0:
        warns.append(
            f"Unbalanced earthwork: {waste:.1f} m³ (bank) cut surplus — "
            "waste area or re-grade required"
        )

    return {
        "cut_bank_m3": cut_volume_bank_m3,
        "fill_compacted_m3": fill_volume_compacted_m3,
        "fill_bank_equivalent_m3": fill_bank,
        "fill_loose_m3": fill_loose,
        "surplus_deficit_bank_m3": surplus,
        "borrow_needed_bank_m3": borrow,
        "waste_available_bank_m3": waste,
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Mass-haul diagram
# ---------------------------------------------------------------------------

def mass_haul(
    stations: Sequence[float],
    cut_volumes: Sequence[float],
    fill_volumes: Sequence[float],
    free_haul_distance: float = 500.0,
    overhaul_cost_per_m3_station: float = 0.0,
    borrow_cost_per_m3: float = 0.0,
    waste_cost_per_m3: float = 0.0,
) -> dict:
    """Mass-haul diagram: cumulative ordinates, balance points, overhaul cost.

    Parameters
    ----------
    stations : sequence of float
        Chainages at interval boundaries (m).  Length = N (number of intervals
        + 1).
    cut_volumes : sequence of float
        Cut (positive) volume at each interval (m³).  Length = N-1.
    fill_volumes : sequence of float
        Fill volume at each interval (m³, positive).  Length = N-1.
    free_haul_distance : float
        Free-haul limit (m).  Haul within this distance costs nothing extra.
    overhaul_cost_per_m3_station : float
        Cost per m³·station (m³·m / station-length).  0 if only borrow/waste
        cost is relevant.
    borrow_cost_per_m3 : float
        Cost per m³ of borrow material (bank measure).
    waste_cost_per_m3 : float
        Cost per m³ of wasted material (bank measure).

    Returns
    -------
    dict
        ordinates           — list of {station, cumulative_m3} dicts
        balance_points      — station chainage(s) where ordinate crosses zero
        total_cut_m3        — total cut volume
        total_fill_m3       — total fill volume
        net_m3              — cut minus fill (positive = surplus)
        total_borrow_m3     — borrow needed (net fill deficit)
        total_waste_m3      — waste needed (net cut surplus)
        overhaul_volume_m3_stations — approximate overhaul volume * distance
        overhaul_cost       — cost of overhaul
        borrow_cost         — cost of borrow
        waste_cost          — cost of waste
        total_cost          — sum of above costs
        warnings
    """
    warns: list[str] = []
    st = list(stations)
    cv = list(cut_volumes)
    fv = list(fill_volumes)

    n_intervals = len(cv)
    if len(fv) != n_intervals:
        raise ValueError("cut_volumes and fill_volumes must have the same length")
    if len(st) != n_intervals + 1:
        raise ValueError("stations must have length len(cut_volumes)+1")
    for i in range(len(st) - 1):
        if st[i + 1] <= st[i]:
            raise ValueError(
                f"stations must be strictly increasing (index {i})"
            )

    # Net volume per interval: positive = surplus cut, negative = fill demand
    ordinates = [{"station": st[0], "cumulative_m3": 0.0}]
    cumulative = 0.0
    total_cut = 0.0
    total_fill = 0.0

    for i in range(n_intervals):
        net_i = cv[i] - fv[i]
        cumulative += net_i
        total_cut += cv[i]
        total_fill += fv[i]
        ordinates.append({
            "station": st[i + 1],
            "cumulative_m3": cumulative,
        })

    net = total_cut - total_fill
    borrow_needed = max(0.0, -net)
    waste_needed = max(0.0, net)

    # Balance points: stations where the cumulative ordinate is exactly zero,
    # or where it changes sign (linear interpolation).
    balance_pts: list[float] = []
    for i in range(len(ordinates)):
        oi = ordinates[i]["cumulative_m3"]
        si = ordinates[i]["station"]
        if oi == 0.0 and si not in balance_pts:
            balance_pts.append(si)

    for i in range(len(ordinates) - 1):
        o1 = ordinates[i]["cumulative_m3"]
        o2 = ordinates[i + 1]["cumulative_m3"]
        if o1 * o2 < 0.0:
            # Linear interpolation of sign-change crossing
            s1 = ordinates[i]["station"]
            s2 = ordinates[i + 1]["station"]
            bp = s1 + (s2 - s1) * abs(o1) / (abs(o1) + abs(o2))
            bp_rounded = round(bp, 3)
            if bp_rounded not in balance_pts:
                balance_pts.append(bp_rounded)

    # Approximate overhaul: sum of |net_i| * station_interval for intervals
    # beyond free_haul_distance from their nearest balance point.
    # Simplified method: cumulative area of mass-haul curve outside free-haul
    # band.  Here we use a conservative estimate: overhaul = total transported
    # volume beyond free-haul limit.  Full planimeter analysis requires the
    # full diagram; we approximate by summing haul of surplus intervals.

    # Centre of mass of cut and fill volumes (simple station-weighted)
    sum_cut_station = sum(
        cv[i] * (st[i] + st[i + 1]) / 2.0 for i in range(n_intervals)
    )
    sum_fill_station = sum(
        fv[i] * (st[i] + st[i + 1]) / 2.0 for i in range(n_intervals)
    )
    avg_haul_dist = 0.0
    if total_cut > 0 and total_fill > 0:
        avg_cut_sta = sum_cut_station / total_cut
        avg_fill_sta = sum_fill_station / total_fill
        avg_haul_dist = abs(avg_cut_sta - avg_fill_sta)

    balanced_vol = min(total_cut, total_fill)
    overhaul_vol_m3 = 0.0
    if avg_haul_dist > free_haul_distance and balanced_vol > 0:
        overhaul_dist = avg_haul_dist - free_haul_distance
        overhaul_vol_m3 = balanced_vol * overhaul_dist  # m³·m

    cost_overhaul = overhaul_vol_m3 * overhaul_cost_per_m3_station
    cost_borrow = borrow_needed * borrow_cost_per_m3
    cost_waste = waste_needed * waste_cost_per_m3
    total_cost = cost_overhaul + cost_borrow + cost_waste

    if borrow_needed > 0:
        warns.append(
            f"Unbalanced earthwork: borrow {borrow_needed:.1f} m³ required"
        )
    if waste_needed > 0:
        warns.append(
            f"Unbalanced earthwork: {waste_needed:.1f} m³ excess cut to waste"
        )
    if avg_haul_dist > free_haul_distance and overhaul_cost_per_m3_station > 0:
        warns.append(
            f"Average haul distance {avg_haul_dist:.1f} m exceeds free-haul "
            f"limit {free_haul_distance:.1f} m — overhaul cost incurred"
        )

    return {
        "ordinates": ordinates,
        "balance_points": balance_pts,
        "total_cut_m3": total_cut,
        "total_fill_m3": total_fill,
        "net_m3": net,
        "total_borrow_m3": borrow_needed,
        "total_waste_m3": waste_needed,
        "average_haul_distance_m": avg_haul_dist,
        "overhaul_volume_m3_stations": overhaul_vol_m3,
        "overhaul_cost": cost_overhaul,
        "borrow_cost": cost_borrow,
        "waste_cost": cost_waste,
        "total_cost": total_cost,
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Proctor compaction (max dry density & OMC interpolation)
# ---------------------------------------------------------------------------

def proctor_optimum(
    moisture_contents: Sequence[float],
    dry_densities: Sequence[float],
) -> dict:
    """Fit a parabola through Proctor compaction data to find MDD and OMC.

    A second-degree polynomial is fitted through the (moisture, dry_density)
    data points.  The peak of the parabola gives the optimum moisture content
    (OMC) and maximum dry density (MDD).

    Parameters
    ----------
    moisture_contents : sequence of float
        Moisture contents (%) at each compaction point.  >= 2 points required;
        >= 4 recommended for a meaningful parabolic fit.
    dry_densities : sequence of float
        Dry densities (kg/m³ or Mg/m³ — consistent units) at each point.

    Returns
    -------
    dict
        omc_percent         — optimum moisture content (%)
        mdd                 — maximum dry density (same units as input)
        poly_coefficients   — [a, b, c] for ρ_d = a·w² + b·w + c
        r_squared           — goodness of fit (0–1)
        warnings
    """
    warns: list[str] = []
    wc = list(moisture_contents)
    rho = list(dry_densities)
    n = len(wc)
    if len(rho) != n:
        raise ValueError("moisture_contents and dry_densities must have equal length")
    if n < 3:
        raise ValueError(
            "At least 3 data points are required for a Proctor parabolic fit"
        )

    # Fit a 2nd-degree polynomial: ρ_d = a·w² + b·w + c
    # Using normal equations (Vandermonde / least-squares)
    a, b, c = _poly2_fit(wc, rho)

    if a >= 0:
        warns.append(
            "Fitted parabola opens upward (a >= 0) — data may not form a "
            "proper Proctor compaction curve; OMC/MDD may be unreliable"
        )
        # Return arithmetic peak anyway
        omc = -b / (2.0 * a) if a != 0 else wc[rho.index(max(rho))]
    else:
        omc = -b / (2.0 * a)

    mdd = a * omc ** 2 + b * omc + c

    # R² against the fit
    rho_mean = sum(rho) / n
    ss_res = sum((rho[i] - (a * wc[i] ** 2 + b * wc[i] + c)) ** 2 for i in range(n))
    ss_tot = sum((rho[i] - rho_mean) ** 2 for i in range(n))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

    if r2 < 0.90:
        warns.append(
            f"Poor parabolic fit (R²={r2:.3f}) — consider reviewing data or "
            "adding more compaction points"
        )

    return {
        "omc_percent": omc,
        "mdd": mdd,
        "poly_coefficients": [a, b, c],
        "r_squared": r2,
        "warnings": warns,
    }


def _poly2_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Fit ρ = a·w² + b·w + c by least-squares normal equations."""
    n = len(xs)
    # Build 3×3 normal equation matrix [S4 S3 S2 | S2y] ...
    s0 = float(n)
    s1 = sum(xs)
    s2 = sum(x ** 2 for x in xs)
    s3 = sum(x ** 3 for x in xs)
    s4 = sum(x ** 4 for x in xs)
    sy = sum(ys)
    s1y = sum(xs[i] * ys[i] for i in range(n))
    s2y = sum(xs[i] ** 2 * ys[i] for i in range(n))

    # 3×3 system:
    # [s4 s3 s2] [a]   [s2y]
    # [s3 s2 s1] [b] = [s1y]
    # [s2 s1 s0] [c]   [sy ]
    A = [[s4, s3, s2], [s3, s2, s1], [s2, s1, s0]]
    b_vec = [s2y, s1y, sy]
    sol = _solve3(A, b_vec)
    return sol[0], sol[1], sol[2]


def _solve3(A: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination for 3×3 system."""
    # Augment
    M = [A[i][:] + [b[i]] for i in range(3)]
    for col in range(3):
        # Partial pivot
        pivot = max(range(col, 3), key=lambda r: abs(M[r][col]))
        M[col], M[pivot] = M[pivot], M[col]
        if abs(M[col][col]) < 1e-14:
            raise ValueError("Singular matrix in _solve3")
        for row in range(col + 1, 3):
            f = M[row][col] / M[col][col]
            for k in range(col, 4):
                M[row][k] -= f * M[col][k]
    # Back-substitute
    x = [0.0] * 3
    for i in range(2, -1, -1):
        x[i] = M[i][3]
        for j in range(i + 1, 3):
            x[i] -= M[i][j] * x[j]
        x[i] /= M[i][i]
    return x


# ---------------------------------------------------------------------------
# Relative compaction & lift productivity
# ---------------------------------------------------------------------------

def relative_compaction(
    field_dry_density: float,
    lab_mdd: float,
    spec_rc_percent: float = 95.0,
) -> dict:
    """Relative compaction % and pass/fail against specification.

    Parameters
    ----------
    field_dry_density : float
        Field dry density measured by nuclear gauge / sand-cone (kg/m³ or
        consistent units with lab_mdd). > 0.
    lab_mdd : float
        Laboratory maximum dry density (MDD) from Proctor test. > 0.
    spec_rc_percent : float
        Required relative compaction (default 95%).

    Returns
    -------
    dict
        rc_percent          — achieved relative compaction (%)
        spec_rc_percent     — specification (%)
        pass_fail           — 'PASS' or 'FAIL'
        deficit_pct         — how much below spec (0 if passing)
        warnings
    """
    warns: list[str] = []
    if field_dry_density <= 0:
        raise ValueError("field_dry_density must be > 0")
    if lab_mdd <= 0:
        raise ValueError("lab_mdd must be > 0")
    if not (0 < spec_rc_percent <= 100):
        raise ValueError("spec_rc_percent must be in (0, 100]")

    rc = 100.0 * field_dry_density / lab_mdd
    deficit = max(0.0, spec_rc_percent - rc)
    pf = "PASS" if rc >= spec_rc_percent else "FAIL"

    if pf == "FAIL":
        warnings.warn(
            f"Compaction not met: achieved RC={rc:.1f}% < required "
            f"{spec_rc_percent:.1f}% — additional passes required",
            stacklevel=2,
        )

    return {
        "rc_percent": rc,
        "spec_rc_percent": spec_rc_percent,
        "pass_fail": pf,
        "deficit_pct": deficit,
        "warnings": warns,
    }


def lift_productivity(
    roller_width_m: float,
    roller_speed_kmh: float,
    lift_thickness_m: float,
    num_passes: int,
    efficiency_factor: float = 0.75,
) -> dict:
    """Compaction roller productivity.

    Parameters
    ----------
    roller_width_m : float
        Effective compaction width of drum (m). > 0.
    roller_speed_kmh : float
        Average rolling speed (km/h). > 0.
    lift_thickness_m : float
        Compacted lift thickness (m). > 0.
    num_passes : int
        Number of passes required per lift. >= 1.
    efficiency_factor : float
        Job efficiency (0–1).  Default 0.75 (45 productive min/h).

    Returns
    -------
    dict
        area_per_hour_m2    — area compacted per hour (m²/h)
        volume_per_hour_m3  — volume compacted per hour (m³/h)
        warnings
    """
    warns: list[str] = []
    if roller_width_m <= 0:
        raise ValueError("roller_width_m must be > 0")
    if roller_speed_kmh <= 0:
        raise ValueError("roller_speed_kmh must be > 0")
    if lift_thickness_m <= 0:
        raise ValueError("lift_thickness_m must be > 0")
    if num_passes < 1:
        raise ValueError("num_passes must be >= 1")
    if not (0 < efficiency_factor <= 1.0):
        raise ValueError("efficiency_factor must be in (0, 1]")

    speed_m_h = roller_speed_kmh * 1000.0
    area_per_h = roller_width_m * speed_m_h * efficiency_factor / num_passes
    vol_per_h = area_per_h * lift_thickness_m

    if lift_thickness_m > 0.30:
        warns.append(
            f"Lift thickness {lift_thickness_m*100:.0f} cm exceeds typical "
            "300 mm maximum — verify roller capability and specification"
        )
    if num_passes > 12:
        warns.append(
            f"num_passes={num_passes} is high — consider changing roller "
            "type or reducing lift thickness"
        )

    return {
        "area_per_hour_m2": area_per_h,
        "volume_per_hour_m3": vol_per_h,
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Slope / batter & daylight offset
# ---------------------------------------------------------------------------

def slope_daylight_offset(
    formation_half_width: float,
    design_height_at_edge: float,
    ground_height_at_edge: float,
    batter: float,
    mode: str = "cut",
) -> dict:
    """Horizontal offset from formation edge to daylight (hinge) point.

    Parameters
    ----------
    formation_half_width : float
        Half the formation width (m). >= 0.
    design_height_at_edge : float
        Design surface elevation at formation edge (m).
    ground_height_at_edge : float
        Existing ground elevation at formation edge (m).
    batter : float
        Slope batter H:V (e.g. 1.5 means 1.5 horizontal per 1 vertical).
        >= 0.
    mode : str
        'cut' — formation below ground (cuts into hill);
        'fill' — formation above ground (embankment).

    Returns
    -------
    dict
        vertical_height_m   — vertical difference (m)
        horizontal_offset_m — horizontal distance from edge to daylight (m)
        total_offset_from_cl_m — total offset from centreline to daylight (m)
        daylight_slope_pct  — batter expressed as % (100/batter for H:1)
        warnings
    """
    warns: list[str] = []
    if formation_half_width < 0:
        raise ValueError("formation_half_width must be >= 0")
    if batter < 0:
        raise ValueError("batter must be >= 0")
    if mode not in ("cut", "fill"):
        raise ValueError("mode must be 'cut' or 'fill'")

    if mode == "cut":
        vert = ground_height_at_edge - design_height_at_edge
    else:  # fill
        vert = design_height_at_edge - ground_height_at_edge

    if vert < 0:
        warns.append(
            f"Computed vertical_height_m={vert:.3f} is negative — ground may "
            "already be at or past daylight; check elevations and mode"
        )
        vert = 0.0

    horiz = batter * vert
    total = formation_half_width + horiz
    slope_pct = (100.0 / batter) if batter > 0 else float("inf")

    return {
        "vertical_height_m": vert,
        "horizontal_offset_m": horiz,
        "total_offset_from_cl_m": total,
        "daylight_slope_pct": slope_pct,
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Trench excavation volume & shoring/bedding
# ---------------------------------------------------------------------------

def trench_volume(
    length_m: float,
    depth_m: float,
    bottom_width_m: float,
    side_slope: float = 0.0,
    bedding_thickness_m: float = 0.10,
    pipe_od_m: float = 0.0,
    shoring_area_per_m: float = 0.0,
) -> dict:
    """Trench excavation volume with side batters, bedding, and shoring.

    The trench has a flat bottom of *bottom_width_m* and sides battering out
    at *side_slope* H:V.

    Parameters
    ----------
    length_m : float
        Trench length (m). > 0.
    depth_m : float
        Trench depth from surface to invert (m). > 0.
    bottom_width_m : float
        Trench bottom width (m). > 0.
    side_slope : float
        Batter H:V on each side. 0 for vertical sides (shored). >= 0.
    bedding_thickness_m : float
        Bedding material thickness below pipe invert (m). >= 0. Default 0.10.
    pipe_od_m : float
        Pipe outer diameter (m). Used to deduct pipe volume from trench. >= 0.
    shoring_area_per_m : float
        Shoring panel / sheet-pile area per metre run (m²/m) for estimating
        shoring quantity. >= 0.

    Returns
    -------
    dict
        gross_volume_m3     — trench excav. volume (m³, trapezoid × length)
        net_volume_m3       — gross less pipe volume (m³)
        bedding_volume_m3   — bedding material volume (m³)
        shoring_area_m2     — total shoring area (m²)
        top_width_m         — trench width at surface (m)
        cross_section_area_m2 — trapezoidal cross-section area (m²)
        warnings
    """
    warns: list[str] = []
    if length_m <= 0:
        raise ValueError("length_m must be > 0")
    if depth_m <= 0:
        raise ValueError("depth_m must be > 0")
    if bottom_width_m <= 0:
        raise ValueError("bottom_width_m must be > 0")
    if side_slope < 0:
        raise ValueError("side_slope must be >= 0")
    if bedding_thickness_m < 0:
        raise ValueError("bedding_thickness_m must be >= 0")
    if pipe_od_m < 0:
        raise ValueError("pipe_od_m must be >= 0")
    if shoring_area_per_m < 0:
        raise ValueError("shoring_area_per_m must be >= 0")

    top_w = bottom_width_m + 2.0 * side_slope * depth_m
    cs_area = (bottom_width_m + top_w) / 2.0 * depth_m
    gross_vol = cs_area * length_m

    # Deduct pipe (approximate as cylinder)
    pipe_vol = math.pi / 4.0 * pipe_od_m ** 2 * length_m
    net_vol = gross_vol - pipe_vol

    # Bedding volume: bottom_width × bedding_thickness × length
    bedding_vol = bottom_width_m * bedding_thickness_m * length_m

    # Shoring
    shoring_area = shoring_area_per_m * length_m

    if depth_m > 1.5 and side_slope == 0.0 and shoring_area_per_m == 0.0:
        warns.append(
            f"Trench depth {depth_m:.1f} m with vertical sides and no shoring "
            "specified — OSHA/regulations typically require shoring > 1.5 m"
        )
    if pipe_od_m > bottom_width_m:
        warns.append(
            "pipe_od_m exceeds bottom_width_m — pipe does not fit; widen trench"
        )

    return {
        "gross_volume_m3": gross_vol,
        "net_volume_m3": max(0.0, net_vol),
        "bedding_volume_m3": bedding_vol,
        "shoring_area_m2": shoring_area,
        "top_width_m": top_w,
        "cross_section_area_m2": cs_area,
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Dewatering pump rate (well-point / Dupuit–Thiem)
# ---------------------------------------------------------------------------

def dewatering_pump_rate(
    hydraulic_conductivity_m_s: float,
    aquifer_thickness_m: float,
    drawdown_m: float,
    radius_of_influence_m: float,
    equivalent_well_radius_m: float,
) -> dict:
    """Simplified well-point dewatering pump rate (Dupuit–Thiem, unconfined).

    Dupuit–Thiem formula for steady radial flow to a well in an unconfined
    (water table) aquifer:

        Q = π·K·(H² - hw²) / ln(R / r)

    where H = saturated thickness far from well (aquifer_thickness_m),
    hw = H - drawdown_m, R = radius_of_influence_m, r = equivalent_well_radius_m.

    Parameters
    ----------
    hydraulic_conductivity_m_s : float
        Hydraulic conductivity K (m/s). > 0.
    aquifer_thickness_m : float
        Saturated aquifer thickness H at undisturbed conditions (m). > 0.
    drawdown_m : float
        Required drawdown at the well (m). > 0 and <= aquifer_thickness_m.
    radius_of_influence_m : float
        Radius of influence R (m) — distance where drawdown is negligible. > 0.
    equivalent_well_radius_m : float
        Equivalent radius r of the well or well-point system (m). > 0 and < R.

    Returns
    -------
    dict
        pump_rate_m3_s   — total pump rate (m³/s)
        pump_rate_m3_h   — pump rate (m³/h)
        pump_rate_L_s    — pump rate (L/s)
        head_at_well_m   — residual head hw at the well (m)
        warnings
    """
    warns: list[str] = []
    if hydraulic_conductivity_m_s <= 0:
        raise ValueError("hydraulic_conductivity_m_s must be > 0")
    if aquifer_thickness_m <= 0:
        raise ValueError("aquifer_thickness_m must be > 0")
    if drawdown_m <= 0:
        raise ValueError("drawdown_m must be > 0")
    if drawdown_m > aquifer_thickness_m:
        raise ValueError("drawdown_m cannot exceed aquifer_thickness_m")
    if radius_of_influence_m <= 0:
        raise ValueError("radius_of_influence_m must be > 0")
    if equivalent_well_radius_m <= 0:
        raise ValueError("equivalent_well_radius_m must be > 0")
    if equivalent_well_radius_m >= radius_of_influence_m:
        raise ValueError(
            "equivalent_well_radius_m must be < radius_of_influence_m"
        )

    K = hydraulic_conductivity_m_s
    H = aquifer_thickness_m
    s = drawdown_m
    R = radius_of_influence_m
    r = equivalent_well_radius_m

    hw = H - s
    Q = math.pi * K * (H ** 2 - hw ** 2) / math.log(R / r)

    if drawdown_m / aquifer_thickness_m > 0.5:
        warns.append(
            f"Drawdown ({drawdown_m:.1f} m) is >50% of aquifer thickness "
            f"({aquifer_thickness_m:.1f} m) — Dupuit assumption becomes less "
            "accurate; consider full 3-D groundwater model"
        )

    return {
        "pump_rate_m3_s": Q,
        "pump_rate_m3_h": Q * 3600.0,
        "pump_rate_L_s": Q * 1000.0,
        "head_at_well_m": hw,
        "warnings": warns,
    }
