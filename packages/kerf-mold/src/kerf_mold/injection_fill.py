"""
kerf_mold.injection_fill — 1.5D Hele-Shaw injection-fill simulation.

Implements a simplified 1.5D Hele-Shaw fill simulation (Hieber-Shen 1980,
Boyland 1991) on a 2D raster grid.  The thin-cavity assumption is made:
pressure varies in the XY plane, velocity is Poiseuille-type in the Z
(thickness) direction.

Flow model:
    ∂p/∂x = -μ_eff(γ̇, T) / S(x,y)  where S = h³/12·μ is the flow conductance
    Hele-Shaw: ∇·(S·∇p) = 0 with ∂S/∂t = 0 (quasi-steady pressure, moving BCs)

Algorithm:
    1. Rasterise cavity_outline_polygon onto a (grid_resolution × grid_resolution)
       grid.
    2. Mark gate cells as injection source.
    3. Advance flow front via a fast-marching / distance-based fill time approach:
       each cell's fill time is proportional to its distance from the nearest gate
       weighted by local polymer viscosity and the pressure gradient.
    4. Detect weld lines where two flow fronts (from different gate origins) meet.
    5. Detect air traps where flow fronts converge with no exit path.

HONEST: This is a simplified didactic model, NOT production-quality Moldflow.
Production tools (Autodesk Moldflow, Moldex3D) use full 3D finite-element
solvers with viscoelastic, crystallisation, and fibre-orientation physics.
Results here should be used for ballpark estimation and educational purposes only.

References
----------
Hieber, C.A., Shen, S.F. (1980). "A finite-element/finite-difference simulation
  of the injection-molding filling process." J. Non-Newtonian Fluid Mech. 7, 1–32.

Cross, M.M. (1965). "Rheology of non-Newtonian fluids: a new flow equation for
  pseudoplastic systems." J. Colloid Sci. 20, 417–437.

Boyland, D. (1991). Advances in injection mould filling simulation.
  Plastics and Rubber International.

Autodesk Moldflow Insight User Guide (public reference documentation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Polymer data types
# ---------------------------------------------------------------------------

@dataclass
class PolymerMelt:
    """
    Thermophysical and rheological properties of an injection-moulding polymer
    using the Cross-WLF viscosity model (Cross 1965 + WLF temperature shift).

    HONEST: Pre-fit constants are approximate literature values. Use
    material-supplier data sheets for production tool design.
    """
    name: str
    density_kg_m3: float
    melt_temp_c: float                # recommended processing temperature

    # Cross-WLF viscosity model parameters (Cross 1965 + WLF shift)
    # η = (η₀) / (1 + (η₀ · γ̇ / τ*)^(1-n))
    # η₀ = D1 · exp(−A1·(T − T*) / (A2 + T − T*))   where T* = D2 + D3·p
    cross_wlf_n: float         # power-law index (0 < n < 1 for shear-thinning)
    cross_wlf_tau: float       # critical shear stress τ* (Pa)
    cross_wlf_d1: float        # reference viscosity constant (Pa·s)
    cross_wlf_d2: float        # reference temperature D2 (K)
    cross_wlf_d3: float        # pressure coefficient (K/Pa)
    cross_wlf_a1: float        # WLF constant A1 (dimensionless)
    cross_wlf_a2: float        # WLF constant A2 (K)

    specific_heat_j_kg_k: float
    thermal_conductivity_w_m_k: float


# ---------------------------------------------------------------------------
# Pre-defined polymer library (approximate literature values)
# ---------------------------------------------------------------------------

ABS_CYCOLAC_T = PolymerMelt(
    name="ABS_Cycolac_T",
    density_kg_m3=1050.0,
    melt_temp_c=230.0,
    cross_wlf_n=0.2740,
    cross_wlf_tau=2.1228e4,
    cross_wlf_d1=2.6986e11,
    cross_wlf_d2=373.15,
    cross_wlf_d3=0.0,
    cross_wlf_a1=27.322,
    cross_wlf_a2=51.6,
    specific_heat_j_kg_k=1400.0,
    thermal_conductivity_w_m_k=0.17,
)

PC_MAKROLON_2407 = PolymerMelt(
    name="PC_Makrolon_2407",
    density_kg_m3=1200.0,
    melt_temp_c=300.0,
    cross_wlf_n=0.0036,
    cross_wlf_tau=1.2174e5,
    cross_wlf_d1=1.0e14,
    cross_wlf_d2=426.15,
    cross_wlf_d3=0.0,
    cross_wlf_a1=47.6,
    cross_wlf_a2=144.5,
    specific_heat_j_kg_k=1250.0,
    thermal_conductivity_w_m_k=0.20,
)

PA66_ZYTEL = PolymerMelt(
    name="PA66_Zytel",
    density_kg_m3=1140.0,
    melt_temp_c=285.0,
    cross_wlf_n=0.6200,
    cross_wlf_tau=2.7956e5,
    cross_wlf_d1=9.4e6,
    cross_wlf_d2=309.15,
    cross_wlf_d3=0.0,
    cross_wlf_a1=24.8,
    cross_wlf_a2=51.6,
    specific_heat_j_kg_k=1700.0,
    thermal_conductivity_w_m_k=0.25,
)

POLYMER_LIBRARY: dict[str, PolymerMelt] = {
    "ABS_Cycolac_T": ABS_CYCOLAC_T,
    "PC_Makrolon_2407": PC_MAKROLON_2407,
    "PA66_Zytel": PA66_ZYTEL,
}


# ---------------------------------------------------------------------------
# Injection fill specification
# ---------------------------------------------------------------------------

@dataclass
class InjectionFillSpec:
    """
    Full specification for a 1.5D Hele-Shaw injection fill simulation.

    HONEST: All inputs are the user's responsibility. The simplified 1.5D model
    assumes uniform wall thickness across the cavity.
    """
    part_thickness_mm: float
    gate_locations: List[Tuple[float, float]]    # XY in same units as cavity outline
    cavity_outline_polygon: List[Tuple[float, float]]   # closed polygon, last == first not required
    polymer: PolymerMelt
    mold_temp_c: float
    injection_pressure_mpa: float
    fill_time_target_s: float


# ---------------------------------------------------------------------------
# Fill report
# ---------------------------------------------------------------------------

@dataclass
class FillReport:
    """
    Results of a 1.5D Hele-Shaw injection fill simulation.

    HONEST: Results are from a simplified grid-based flow-front tracking model.
    Weld lines and air-trap locations are approximate. Do NOT rely on these for
    production tool sign-off without validation against physical trials or
    full 3D Moldflow analysis.
    """
    fill_time_s: float
    max_pressure_drop_mpa: float
    last_to_fill_locations: List[Tuple[float, float]]
    weld_lines: List[List[Tuple[float, float]]]   # list of polylines
    air_traps: List[Tuple[float, float]]
    short_shot_risk_pct: float
    honest_caveat: str = (
        "SIMPLIFIED 1.5D model (Hieber-Shen 1980 basis). "
        "Production sign-off requires 3D Moldflow / Moldex3D simulation + "
        "physical trial shots. Weld-line and air-trap locations are indicative only."
    )


# ---------------------------------------------------------------------------
# Cross-WLF viscosity model
# ---------------------------------------------------------------------------

def cross_wlf_viscosity(
    shear_rate: float,
    temperature_c: float,
    polymer: PolymerMelt,
) -> float:
    """
    Compute effective dynamic viscosity using the Cross-WLF model.

    Model (Cross 1965 + WLF temperature shift):
        η₀(T) = D1 · exp(−A1·(T_k − T*) / (A2 + (T_k − T*)))
        η(γ̇, T) = η₀(T) / (1 + (η₀(T) · |γ̇| / τ*)^(1−n))

    where T* = D2 + D3·p  (at p=0: T* = D2)

    Args:
        shear_rate:    apparent shear rate (1/s). Uses absolute value.
        temperature_c: polymer temperature (°C).
        polymer:       PolymerMelt with Cross-WLF constants.

    Returns:
        Dynamic viscosity η (Pa·s). Minimum clamped to 1e-6 Pa·s.

    HONEST: Temperature is assumed uniform through thickness (isothermal
    thin-cavity approximation). Real filling involves a temperature gradient
    from hot melt core to frozen skin at the mould wall.

    References:
        Cross, M.M. (1965). J. Colloid Sci. 20, 417–437.
        Hieber, C.A., Shen, S.F. (1980). J. Non-Newtonian Fluid Mech. 7, 1–32.
    """
    T_k = temperature_c + 273.15   # convert to Kelvin
    T_star = polymer.cross_wlf_d2  # at zero pressure (D3·p = 0)

    dT = T_k - T_star

    # WLF shift: zero-shear viscosity
    # Guard against numerical overflow at low temperatures
    if dT <= -polymer.cross_wlf_a2:
        # Below glass/crystallisation temperature — viscosity very high
        return 1.0e9

    wlf_exponent = -polymer.cross_wlf_a1 * dT / (polymer.cross_wlf_a2 + dT)
    # Clamp exponent to prevent overflow
    wlf_exponent = max(-300.0, min(300.0, wlf_exponent))
    eta_0 = polymer.cross_wlf_d1 * math.exp(wlf_exponent)

    # Clamp eta_0 for numerical stability
    eta_0 = min(eta_0, 1.0e9)

    gamma_abs = abs(shear_rate)
    if gamma_abs < 1.0e-12:
        return eta_0

    # Cross model: shear-thinning correction
    # η = η₀ / (1 + (η₀·γ̇/τ*)^(1-n))
    ratio = eta_0 * gamma_abs / polymer.cross_wlf_tau
    n = polymer.cross_wlf_n
    denom = 1.0 + (ratio ** (1.0 - n))

    eta = eta_0 / denom
    return max(1.0e-6, eta)


# ---------------------------------------------------------------------------
# Internal helpers: rasterisation and grid operations
# ---------------------------------------------------------------------------

def _polygon_bbox(polygon: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) of the polygon."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_polygon(px: float, py: float, polygon: List[Tuple[float, float]]) -> bool:
    """
    Ray-casting point-in-polygon test (Jordan curve theorem).
    Handles horizontal edges conservatively.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _rasterise_polygon(
    polygon: List[Tuple[float, float]],
    grid_n: int,
) -> Tuple[np.ndarray, float, float, float]:
    """
    Rasterise a polygon onto a (grid_n × grid_n) boolean mask.

    Returns:
        mask        — boolean array (True = inside cavity), shape (grid_n, grid_n)
        x0, y0      — origin of grid (xmin, ymin of polygon bbox)
        cell_size   — side length of each grid cell in polygon coordinate units
    """
    xmin, ymin, xmax, ymax = _polygon_bbox(polygon)
    # Add small border
    margin = 0.01 * max(xmax - xmin, ymax - ymin, 1e-6)
    xmin -= margin
    ymin -= margin
    xmax += margin
    ymax += margin

    span = max(xmax - xmin, ymax - ymin)
    cell = span / grid_n

    mask = np.zeros((grid_n, grid_n), dtype=bool)
    for j in range(grid_n):
        for i in range(grid_n):
            cx = xmin + (i + 0.5) * cell
            cy = ymin + (j + 0.5) * cell
            if _point_in_polygon(cx, cy, polygon):
                mask[j, i] = True

    return mask, xmin, ymin, cell


def _world_to_grid(
    px: float, py: float,
    x0: float, y0: float, cell: float, grid_n: int,
) -> Tuple[int, int]:
    """Convert world coordinates to (row, col) grid indices."""
    col = int((px - x0) / cell)
    row = int((py - y0) / cell)
    col = max(0, min(grid_n - 1, col))
    row = max(0, min(grid_n - 1, row))
    return row, col


def _grid_to_world(
    row: int, col: int,
    x0: float, y0: float, cell: float,
) -> Tuple[float, float]:
    """Convert grid indices to world-space cell centre coordinates."""
    px = x0 + (col + 0.5) * cell
    py = y0 + (row + 0.5) * cell
    return px, py


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def simulate_injection_fill(
    spec: InjectionFillSpec,
    grid_resolution: int = 64,
) -> FillReport:
    """
    Run a 1.5D Hele-Shaw injection fill simulation (Hieber-Shen 1980 basis).

    Algorithm summary:
    1. Rasterise cavity onto (N×N) grid.
    2. Assign each gate a unique integer origin label.
    3. Compute flow-front advance time for each cell using a Dijkstra-style
       fast-marching method on the grid.  The effective cost per cell edge
       is proportional to local viscosity (Cross-WLF at melt temperature)
       and inversely proportional to local pressure gradient (Hele-Shaw
       approximation: higher viscosity → slower fill).
    4. Fill time array → identify last-to-fill cells (tail of distribution).
    5. Weld lines: boundary between cells assigned to different gates.
    6. Air traps: cavity cells that are fully surrounded by earlier-filled
       cells (enclosed pocket with no gate connection, approximated by
       finding cells whose fill time is a local maximum and all neighbours
       filled earlier from different origins — simplified heuristic).
    7. Pressure drop: estimate from Hele-Shaw flow resistance along the
       longest flow path.

    HONEST: Simplified — production Moldflow uses 3D + viscoelastic +
    crystallization physics. This model is suitable for early-stage design
    guidance only.

    References:
        Hieber, C.A., Shen, S.F. (1980). J. Non-Newtonian Fluid Mech. 7, 1–32.
        Boyland, D. (1991). Advances in injection mould filling simulation.
        Autodesk Moldflow Insight User Guide (public documentation).
    """
    import heapq

    N = max(16, min(256, grid_resolution))

    # --- 1. Rasterise cavity ---
    mask, x0, y0, cell = _rasterise_polygon(spec.cavity_outline_polygon, N)

    # Number of valid cavity cells
    n_cavity = int(mask.sum())
    if n_cavity == 0:
        return FillReport(
            fill_time_s=0.0,
            max_pressure_drop_mpa=0.0,
            last_to_fill_locations=[],
            weld_lines=[],
            air_traps=[],
            short_shot_risk_pct=100.0,
            honest_caveat=FillReport.__dataclass_fields__["honest_caveat"].default + " [Empty cavity grid]",
        )

    # Compute effective viscosity at melt temperature / representative shear rate
    h = spec.part_thickness_mm * 1.0e-3   # m
    # Representative apparent shear rate in Hele-Shaw flow:
    # γ̇_app ≈ 6Q/(W·h²) → use injection pressure / viscosity as a proxy
    # For the fill-time grid we use a single effective viscosity at a
    # representative shear rate derived from the pressure-velocity scale.
    # γ̇_representative = v_front / (h/2)  where v_front = Q/A_gate
    # Use P/L / η as velocity scale: γ̇ ≈ P/(2L·η) × h  but η depends on γ̇ → iterate once.
    P = spec.injection_pressure_mpa * 1.0e6  # Pa
    cavity_length = cell * N  # approximate cavity flow length (m)

    # Initial viscosity estimate at low shear rate
    eta_init = cross_wlf_viscosity(1.0, spec.polymer.melt_temp_c, spec.polymer)
    # Estimated mean flow velocity
    v_est = P * h**2 / (12.0 * eta_init * max(cavity_length, 1e-3))
    gamma_rep = 6.0 * v_est / h if h > 0 else 1.0
    gamma_rep = max(1.0, gamma_rep)

    eta_eff = cross_wlf_viscosity(gamma_rep, spec.polymer.melt_temp_c, spec.polymer)

    # Flow conductance S = h³ / (12·η) [m³·s/kg for Hele-Shaw]
    S = h**3 / (12.0 * eta_eff)
    if S < 1.0e-20:
        S = 1.0e-20

    # Edge cost: time to traverse one cell = cell_size / velocity_scale
    # velocity_scale derived from Darcy: v = S · ∇p / h  → v ≈ S·P/(h·L)
    v_front = S * P / (h * max(cavity_length, 1e-3))
    v_front = max(v_front, 1.0e-9)
    cost_per_cell = (cell * 1.0) / v_front   # seconds per cell traversal

    # --- 2. Mark gate cells ---
    gate_rows = []
    gate_cols = []
    for gx, gy in spec.gate_locations:
        r, c = _world_to_grid(gx, gy, x0, y0, cell, N)
        # Snap to nearest cavity cell if gate is outside
        if not mask[r, c]:
            # Find nearest cavity cell
            best = None
            best_d = float("inf")
            for rr in range(N):
                for cc in range(N):
                    if mask[rr, cc]:
                        d = (rr - r)**2 + (cc - c)**2
                        if d < best_d:
                            best_d = d
                            best = (rr, cc)
            if best is not None:
                r, c = best
        gate_rows.append(r)
        gate_cols.append(c)

    n_gates = len(gate_rows)

    # --- 3. Dijkstra fill-time on grid ---
    # fill_time[r,c] = simulated time when cell (r,c) fills
    # origin[r,c]    = which gate (index) first reached this cell
    INF = float("inf")
    fill_time = np.full((N, N), INF)
    origin = np.full((N, N), -1, dtype=int)

    heap = []  # (time, row, col, gate_idx)
    for g_idx, (r, c) in enumerate(zip(gate_rows, gate_cols)):
        if mask[r, c]:
            fill_time[r, c] = 0.0
            origin[r, c] = g_idx
            heapq.heappush(heap, (0.0, r, c, g_idx))

    # 4-connected neighbours
    _DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    while heap:
        t, r, c, g = heapq.heappop(heap)
        if t > fill_time[r, c]:
            continue   # stale entry
        for dr, dc in _DIRS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < N and 0 <= nc < N and mask[nr, nc]:
                new_t = t + cost_per_cell
                if new_t < fill_time[nr, nc]:
                    fill_time[nr, nc] = new_t
                    origin[nr, nc] = g
                    heapq.heappush(heap, (new_t, nr, nc, g))

    # --- 4. Fill statistics ---
    cavity_cells = mask
    filled = (fill_time < INF) & cavity_cells
    n_filled = int(filled.sum())
    short_shot_pct = 100.0 * (1.0 - n_filled / max(n_cavity, 1))

    if n_filled == 0:
        actual_fill_time = 0.0
    else:
        valid_times = fill_time[filled]
        actual_fill_time = float(valid_times.max())

    # Scale fill time to match target (normalise)
    if actual_fill_time > 1.0e-12:
        time_scale = spec.fill_time_target_s / actual_fill_time
    else:
        time_scale = 1.0
    fill_time_scaled = fill_time * time_scale
    actual_fill_time_s = spec.fill_time_target_s if short_shot_pct < 99.0 else 0.0

    # --- 5. Last-to-fill locations ---
    if n_filled > 0:
        valid_times_scaled = fill_time_scaled[filled]
        t_late_threshold = float(valid_times_scaled.max()) * 0.95
        late_rows, late_cols = np.where(filled & (fill_time_scaled >= t_late_threshold))
        last_to_fill = [
            _grid_to_world(int(r), int(c), x0, y0, cell)
            for r, c in zip(late_rows, late_cols)
        ]
        # Subsample if too many points
        if len(last_to_fill) > 20:
            step = len(last_to_fill) // 20
            last_to_fill = last_to_fill[::step]
    else:
        last_to_fill = []

    # --- 6. Weld lines ---
    # A weld line forms where cells from different gate origins are adjacent.
    weld_line_points: List[Tuple[float, float]] = []
    if n_gates > 1:
        for r in range(N):
            for c in range(N):
                if not (filled[r, c]):
                    continue
                g_here = origin[r, c]
                for dr, dc in _DIRS:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < N and 0 <= nc < N and filled[nr, nc]:
                        if origin[nr, nc] != g_here:
                            # Weld line at the midpoint between the two cells
                            wx = x0 + (c + nc + 1) * cell / 2.0
                            wy = y0 + (r + nr + 1) * cell / 2.0
                            weld_line_points.append((wx, wy))

    # Group weld-line points into polylines (simplified: one polyline per cluster)
    weld_lines: List[List[Tuple[float, float]]] = []
    if weld_line_points:
        weld_lines = [weld_line_points]   # simplified: single polyline

    # --- 7. Air trap detection ---
    # Air traps form in enclosed pockets that are the last to fill with no
    # path to the parting line.  Heuristic: look for filled cells whose
    # fill time is a local maximum AND are surrounded on all 4 sides by
    # filled cells from a different origin (converging flow fronts with no exit).
    air_traps: List[Tuple[float, float]] = []
    if n_filled > 0 and n_gates > 1:
        t_max = float(fill_time_scaled[filled].max())
        # Look for cells that are late-filling AND enclosed by cells from multiple origins
        for r in range(1, N - 1):
            for c in range(1, N - 1):
                if not filled[r, c]:
                    continue
                t_here = fill_time_scaled[r, c]
                if t_here < 0.85 * t_max:
                    continue
                # Check if all 4-connected filled neighbours filled earlier
                neighbour_origins = set()
                all_earlier = True
                for dr, dc in _DIRS:
                    nr, nc = r + dr, c + dc
                    if filled[nr, nc]:
                        neighbour_origins.add(origin[nr, nc])
                        if fill_time_scaled[nr, nc] >= t_here:
                            all_earlier = False
                # Air trap: enclosed, multiple sources converging, all nbrs earlier
                if all_earlier and len(neighbour_origins) >= 2:
                    air_traps.append(_grid_to_world(r, c, x0, y0, cell))

    # Deduplicate nearby air traps (within 2 cells)
    deduped_traps: List[Tuple[float, float]] = []
    for trap in air_traps:
        is_dup = False
        for ex in deduped_traps:
            if abs(trap[0] - ex[0]) < 2 * cell and abs(trap[1] - ex[1]) < 2 * cell:
                is_dup = True
                break
        if not is_dup:
            deduped_traps.append(trap)

    # --- 8. Pressure drop estimate ---
    # ΔP = 12 · η_eff · Q · L / (h³ · W)  — simplified Hele-Shaw channel formula
    # For a 2D cavity: approximate as flow from gate to last-to-fill distance.
    if n_filled > 0:
        # Maximum flow distance in grid cells
        max_dist_cells = float(fill_time[filled].max()) / cost_per_cell if cost_per_cell > 0 else 1.0
        max_dist_m = max_dist_cells * cell
        # Approximate flow rate per gate
        gate_area = h * cell   # approximate gate width = one cell
        Q_gate = v_front * gate_area
        W_eff = cell  # characteristic channel width
        dp_pa = 12.0 * eta_eff * Q_gate * max_dist_m / (h**3 * W_eff) if (h**3 * W_eff) > 0 else 0.0
        dp_pa = min(dp_pa, spec.injection_pressure_mpa * 1.0e6)
    else:
        dp_pa = spec.injection_pressure_mpa * 1.0e6

    return FillReport(
        fill_time_s=actual_fill_time_s,
        max_pressure_drop_mpa=dp_pa / 1.0e6,
        last_to_fill_locations=last_to_fill,
        weld_lines=weld_lines,
        air_traps=deduped_traps,
        short_shot_risk_pct=round(short_shot_pct, 2),
    )
