"""
Board-level thermal map and hotspot analysis for PCB layouts.

2D steady-state conduction over the PCB plane
----------------------------------------------
Models the PCB as a 2D finite-difference (FD) conduction grid.  Each cell has
an effective in-plane thermal conductivity derived from the copper coverage
fraction and FR4:

    k_eff = f_cu * k_copper + (1 - f_cu) * k_fr4

where:
    k_copper  = 390  W/(m·°C)   (bulk copper at 25 °C)
    k_fr4     =   0.3 W/(m·°C)  (typical PCB laminate)
    f_cu      = copper coverage fraction [0, 1] per cell

Heat sources
-----------
Each component is specified as (x_m, y_m, power_W, theta_jc_c_per_w).  The
solver distributes power uniformly over the nearest FD cell; components
coinciding on the same cell accumulate power.

Thermal vias
-----------
Thermal vias are specified as (x_m, y_m, n_vias, r_via_m) and modelled as
additional vertical conductance to a backside/heatsink node:

    G_via_total = n_vias * k_copper * pi * r_via^2 / t_board

where t_board is the board thickness.  This conductance is added to the
convection term for the affected cell so the via essentially short-circuits
heat to the cold reference.

Convection + radiation boundary
--------------------------------
Each cell loses heat to ambient through convection and radiation:

    q_out = h_eff * dx * dy * (T_cell - T_amb)

where h_eff = h_conv + h_rad_lin and the linearised radiation coefficient:

    h_rad_lin = epsilon * sigma * (T_mean^2 + T_amb^2) * (T_mean + T_amb)

evaluated at T_mean = T_amb + 30 K (first pass) and iterated once.

Forced convection (optional)
-----------------------------
Pass airflow_m_per_s > 0 and board_length_m to use the flat-plate
Dittus–Boelter / Incropera correlation for forced convection:

    Nu = 0.664 * Re^0.5 * Pr^(1/3)   (laminar, Re < 5e5)
    h_forced = Nu * k_air / L

This overrides the natural convection h.

Solver
------
The sparse linear system is assembled and solved by Gauss–Seidel iteration
(no numpy / scipy required).  Convergence is declared when the maximum
temperature change between sweeps falls below tol_k.

Never-raise contract
--------------------
All public functions return dicts.  Validation failures return
{"ok": False, "reason": str} — no exceptions propagate to the caller.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ── Physical constants ────────────────────────────────────────────────────────

_K_COPPER: float = 390.0        # W/(m·°C)
_K_FR4: float = 0.3             # W/(m·°C)
_K_AIR: float = 0.026           # W/(m·°C) at ~300 K
_SIGMA: float = 5.670374419e-8  # W/(m²·K⁴)  Stefan-Boltzmann
_PR_AIR: float = 0.713          # Prandtl number of air at ~300 K
_NU_AIR: float = 1.6e-5         # Kinematic viscosity of air m²/s at ~300 K

# Defaults
_DEFAULT_H_NATURAL: float = 10.0     # W/(m²·°C)  natural convection (both sides combined)
_DEFAULT_EPSILON: float = 0.9        # surface emissivity
_DEFAULT_T_BOARD_M: float = 1.6e-3   # board thickness (m)  standard 1.6 mm


# ── Public input dataclasses ──────────────────────────────────────────────────

@dataclass
class BoardComponent:
    """A single heat-dissipating component on the PCB."""
    ref: str                           # e.g. "U1"
    x_m: float                         # x position on board (m)
    y_m: float                         # y position on board (m)
    power_w: float                     # total dissipated power (W)
    theta_jc: float = 0.0              # junction-to-case thermal resistance (°C/W)
    tj_max_c: Optional[float] = None   # max junction temperature from datasheet (°C)


@dataclass
class ThermalVia:
    """A cluster of thermal vias connecting a cell to the backside."""
    x_m: float          # centre x (m)
    y_m: float          # centre y (m)
    n_vias: int = 1     # number of vias
    r_via_m: float = 1.5e-4    # via barrel radius (m), default 0.15 mm


@dataclass
class BoardThermalMapInput:
    """Full description of a PCB for board-level thermal analysis."""
    # Board geometry
    width_m: float                          # board x-extent (m)
    height_m: float                         # board y-extent (m)
    # Copper coverage
    copper_coverage: float = 0.3            # fraction [0,1] uniform or...
    copper_coverage_map: Optional[List[List[float]]] = None  # [ny][nx] override
    # Components and vias
    components: List[BoardComponent] = field(default_factory=list)
    thermal_vias: List[ThermalVia] = field(default_factory=list)
    # Ambient conditions
    ambient_c: float = 25.0
    h_conv: float = _DEFAULT_H_NATURAL      # convection coefficient W/(m²·°C)
    epsilon: float = _DEFAULT_EPSILON       # surface emissivity
    # Optional forced convection (overrides h_conv when > 0)
    airflow_m_per_s: float = 0.0
    board_length_m: float = 0.0             # characteristic length for Nu correlation
    # Board thickness for via conductance
    t_board_m: float = _DEFAULT_T_BOARD_M
    # Solver parameters
    nx: int = 20                            # grid cells in x
    ny: int = 20                            # grid cells in y
    max_iter: int = 2000
    tol_k: float = 1e-4                     # convergence tolerance (°C)


# ── Forced-convection coefficient ─────────────────────────────────────────────

def _h_forced_flat_plate(velocity_m_s: float, length_m: float) -> float:
    """
    Average heat-transfer coefficient for laminar flow over a flat plate.

    Uses the Pohlhausen / Blasius (Incropera §7.2) correlation:
        Nu_avg = 0.664 * Re_L^0.5 * Pr^(1/3)    Re_L < 5e5
        h = Nu * k_air / L

    Parameters
    ----------
    velocity_m_s:
        Free-stream air velocity (m/s).
    length_m:
        Board length in the flow direction (m).

    Returns
    -------
    h  (W/(m²·°C))
    """
    if velocity_m_s <= 0 or length_m <= 0:
        return _DEFAULT_H_NATURAL
    re_l = velocity_m_s * length_m / _NU_AIR
    nu = 0.664 * (re_l ** 0.5) * (_PR_AIR ** (1.0 / 3.0))
    h = nu * _K_AIR / length_m
    return h


# ── Core FD solver ────────────────────────────────────────────────────────────

def _solve_temperature_field(
    nx: int,
    ny: int,
    dx: float,
    dy: float,
    k_eff: List[List[float]],
    q_src: List[List[float]],
    g_via: List[List[float]],
    h_eff: float,
    T_amb: float,
    max_iter: int,
    tol_k: float,
) -> List[List[float]]:
    """
    Gauss–Seidel FD solver for 2D steady-state heat conduction.

    Equation at node (j, i):
        sum_neighbours [ k_link * (T_nb - T) / cell_dim ]
        - (h_eff + G_via[j][i]) * cell_area * (T - T_amb)
        + q_src[j][i] * cell_area
        = 0

    Boundary cells: adiabatic (zero Neumann) at board edges — heat escapes
    only through the convection+radiation+via terms on every cell.

    Initialisation
    --------------
    The field is pre-seeded to the global energy-balance temperature
    (T_amb + P_total / (h_total_board)), which is the correct mean for a
    perfectly spreading board.  This dramatically improves Gauss–Seidel
    convergence when k is large (nearly isothermal boards would otherwise
    require O(1/h_ratio) iterations to build up the mean temperature from
    an ambient-initialised start).

    Parameters
    ----------
    k_eff:
        ny × nx effective in-plane conductivity (W/(m·°C)).
    q_src:
        ny × nx power density (W/m²) — power / cell area.
    g_via:
        ny × nx via conductance density (W/(m²·°C)) additional surface loss.
    h_eff:
        Effective surface heat-transfer coefficient (W/(m²·°C)) for
        convection + linearised radiation, applied to top + bottom surfaces.
    T_amb:
        Ambient temperature (°C).
    """
    cell_area = dx * dy

    # ── Global energy-balance seed temperature ────────────────────────────
    # P_total / (h_total) where h_total = sum over cells of (h_eff + g_via)*cell_area
    P_total = sum(q_src[j][i] * cell_area for j in range(ny) for i in range(nx))
    H_total = sum((h_eff + g_via[j][i]) * cell_area for j in range(ny) for i in range(nx))
    if H_total > 0:
        T_mean_init = T_amb + P_total / H_total
    else:
        T_mean_init = T_amb

    T: List[List[float]] = [[T_mean_init] * nx for _ in range(ny)]

    for _iter in range(max_iter):
        max_delta = 0.0
        for j in range(ny):
            for i in range(nx):
                # Conductive flux contributions from neighbours
                cond = 0.0
                a_ctr = 0.0

                # right neighbour
                if i < nx - 1:
                    k_r = 0.5 * (k_eff[j][i] + k_eff[j][i + 1])
                    w = k_r * dy / dx
                    cond += w * T[j][i + 1]
                    a_ctr += w
                # left neighbour
                if i > 0:
                    k_l = 0.5 * (k_eff[j][i] + k_eff[j][i - 1])
                    w = k_l * dy / dx
                    cond += w * T[j][i - 1]
                    a_ctr += w
                # top neighbour
                if j < ny - 1:
                    k_t = 0.5 * (k_eff[j][i] + k_eff[j + 1][i])
                    w = k_t * dx / dy
                    cond += w * T[j + 1][i]
                    a_ctr += w
                # bottom neighbour
                if j > 0:
                    k_b = 0.5 * (k_eff[j][i] + k_eff[j - 1][i])
                    w = k_b * dx / dy
                    cond += w * T[j - 1][i]
                    a_ctr += w

                # Surface convection + radiation + vias
                h_total = (h_eff + g_via[j][i]) * cell_area
                a_ctr += h_total
                rhs = cond + h_total * T_amb + q_src[j][i] * cell_area

                if a_ctr == 0.0:
                    new_T = T_amb
                else:
                    new_T = rhs / a_ctr

                delta = abs(new_T - T[j][i])
                if delta > max_delta:
                    max_delta = delta
                T[j][i] = new_T

        if max_delta < tol_k:
            break

    return T


# ── Main public API ───────────────────────────────────────────────────────────

def solve_board_thermal_map(inp: BoardThermalMapInput) -> dict:
    """
    Solve the 2D steady-state thermal field over the PCB plane.

    Parameters
    ----------
    inp:
        BoardThermalMapInput describing the board geometry, components,
        vias, and environmental conditions.

    Returns
    -------
    dict with keys:
        ok                 : bool
        T_field            : list[list[float]] — ny × nx temperature array (°C)
        peak_T_c           : float — hotspot temperature (°C)
        peak_ij            : [int,int] — (j,i) index of hotspot cell
        components         : list of per-component dicts with keys:
                               ref, power_w, T_board_c, Tj_c, over_limit,
                               tj_max_c, margin_c
        total_power_w      : float
        total_conv_rad_w   : float — total heat removed (energy balance)
        energy_balance_err : float — |P_in - P_out| / P_in  (dimensionless)
        nx, ny, dx_m, dy_m
        reason             : str — present only when ok=False
    """
    # ── Input validation ──────────────────────────────────────────────────
    if inp.width_m <= 0:
        return {"ok": False, "reason": "width_m must be > 0"}
    if inp.height_m <= 0:
        return {"ok": False, "reason": "height_m must be > 0"}
    if not (0.0 <= inp.copper_coverage <= 1.0):
        return {"ok": False, "reason": "copper_coverage must be in [0, 1]"}
    if inp.nx < 2 or inp.ny < 2:
        return {"ok": False, "reason": "nx and ny must each be >= 2"}
    if inp.ambient_c < -273.15:
        return {"ok": False, "reason": "ambient_c below absolute zero"}
    if inp.h_conv < 0:
        return {"ok": False, "reason": "h_conv must be >= 0"}
    if not (0.0 <= inp.epsilon <= 1.0):
        return {"ok": False, "reason": "epsilon must be in [0, 1]"}
    if inp.t_board_m <= 0:
        return {"ok": False, "reason": "t_board_m must be > 0"}
    for idx, comp in enumerate(inp.components):
        if comp.power_w < 0:
            return {"ok": False, "reason": f"components[{idx}] ({comp.ref}) power_w < 0"}
        if comp.theta_jc < 0:
            return {"ok": False, "reason": f"components[{idx}] ({comp.ref}) theta_jc < 0"}

    nx, ny = inp.nx, inp.ny
    dx = inp.width_m / nx
    dy = inp.height_m / ny
    cell_area = dx * dy

    T_amb = inp.ambient_c
    T_amb_k = T_amb + 273.15

    # ── Effective h (convection + linearised radiation, iterated once) ────
    if inp.airflow_m_per_s > 0:
        h_base = _h_forced_flat_plate(inp.airflow_m_per_s,
                                      inp.board_length_m if inp.board_length_m > 0 else inp.width_m)
    else:
        h_base = inp.h_conv

    T_mean_k = T_amb_k + 30.0   # first-pass mean surface temperature estimate
    h_rad = (inp.epsilon * _SIGMA
             * (T_mean_k ** 2 + T_amb_k ** 2)
             * (T_mean_k + T_amb_k))
    h_eff = h_base + h_rad   # both top and bottom surfaces combined

    # ── Effective in-plane conductivity per cell ──────────────────────────
    k_eff: List[List[float]] = []
    if inp.copper_coverage_map is not None:
        for j in range(ny):
            row: List[float] = []
            for i in range(nx):
                if j < len(inp.copper_coverage_map) and i < len(inp.copper_coverage_map[j]):
                    f = float(inp.copper_coverage_map[j][i])
                    f = max(0.0, min(1.0, f))
                else:
                    f = inp.copper_coverage
                k = f * _K_COPPER + (1.0 - f) * _K_FR4
                row.append(k)
            k_eff.append(row)
    else:
        f = inp.copper_coverage
        k_uniform = f * _K_COPPER + (1.0 - f) * _K_FR4
        k_eff = [[k_uniform] * nx for _ in range(ny)]

    # ── Heat sources: distribute component power to nearest cell ─────────
    q_src: List[List[float]] = [[0.0] * nx for _ in range(ny)]
    for comp in inp.components:
        ci = int(comp.x_m / dx)
        cj = int(comp.y_m / dy)
        ci = max(0, min(nx - 1, ci))
        cj = max(0, min(ny - 1, cj))
        q_src[cj][ci] += comp.power_w / cell_area

    # ── Via conductance per cell ──────────────────────────────────────────
    # G_via [W/(m²·°C)] = sum(n * k_cu * pi * r^2 / t_board) / cell_area
    g_via: List[List[float]] = [[0.0] * nx for _ in range(ny)]
    for via in inp.thermal_vias:
        vi = int(via.x_m / dx)
        vj = int(via.y_m / dy)
        vi = max(0, min(nx - 1, vi))
        vj = max(0, min(ny - 1, vj))
        G = via.n_vias * _K_COPPER * math.pi * via.r_via_m ** 2 / inp.t_board_m
        g_via[vj][vi] += G / cell_area

    # ── Solve ─────────────────────────────────────────────────────────────
    T_field = _solve_temperature_field(
        nx, ny, dx, dy, k_eff, q_src, g_via,
        h_eff, T_amb, inp.max_iter, inp.tol_k,
    )

    # ── Extract peak temperature ──────────────────────────────────────────
    peak_T = T_amb
    peak_i, peak_j = 0, 0
    for j in range(ny):
        for i in range(nx):
            if T_field[j][i] > peak_T:
                peak_T = T_field[j][i]
                peak_i, peak_j = i, j

    # ── Per-component Tj = T_board + P * theta_jc ─────────────────────────
    comp_results = []
    for comp in inp.components:
        ci = int(comp.x_m / dx)
        cj = int(comp.y_m / dy)
        ci = max(0, min(nx - 1, ci))
        cj = max(0, min(ny - 1, cj))
        T_board_c = T_field[cj][ci]
        Tj = T_board_c + comp.power_w * comp.theta_jc

        over_limit = False
        margin_c: Optional[float] = None
        if comp.tj_max_c is not None:
            margin_c = round(comp.tj_max_c - Tj, 6)
            over_limit = Tj > comp.tj_max_c

        comp_results.append({
            "ref": comp.ref,
            "power_w": comp.power_w,
            "T_board_c": round(T_board_c, 4),
            "Tj_c": round(Tj, 4),
            "over_limit": over_limit,
            "tj_max_c": comp.tj_max_c,
            "margin_c": margin_c,
        })

    # ── Energy balance ────────────────────────────────────────────────────
    total_power = sum(c.power_w for c in inp.components)
    total_out = 0.0
    for j in range(ny):
        for i in range(nx):
            dT = T_field[j][i] - T_amb
            total_out += (h_eff + g_via[j][i]) * cell_area * dT

    energy_err = abs(total_power - total_out) / max(total_power, 1e-12)

    return {
        "ok": True,
        "T_field": T_field,
        "peak_T_c": round(peak_T, 4),
        "peak_ij": [peak_j, peak_i],
        "components": comp_results,
        "total_power_w": round(total_power, 6),
        "total_conv_rad_w": round(total_out, 6),
        "energy_balance_err": round(energy_err, 6),
        "nx": nx,
        "ny": ny,
        "dx_m": round(dx, 8),
        "dy_m": round(dy, 8),
    }


# ── Copper / via recommendation helper ───────────────────────────────────────

def recommend_copper_and_vias(
    inp: BoardThermalMapInput,
    target_delta_t_c: float,
    n_via_options: Optional[List[int]] = None,
) -> dict:
    """
    Recommend copper coverage increase and/or thermal via addition to bring
    the hotspot ΔT (T_peak − T_amb) below target_delta_t_c.

    Strategy:
    1. Solve the baseline field and record ΔT_baseline.
    2. If ΔT_baseline <= target, report already_ok=True.
    3. Sweep copper coverage from current to 1.0 in steps to find the minimum
       coverage that hits the target.
    4. For each n_vias option at the hotspot cell report the ΔT achieved.

    Parameters
    ----------
    inp:
        Baseline board description.
    target_delta_t_c:
        Desired maximum ΔT above ambient (°C).
    n_via_options:
        List of via-count candidates to evaluate at the hotspot.  Default:
        [4, 8, 16, 32].

    Returns
    -------
    dict with keys:
        ok                  : bool
        already_ok          : bool
        baseline_delta_t_c  : float
        target_delta_t_c    : float
        copper_recommendation: dict with min_coverage (float or None) and delta_t_c
        via_options         : list of dicts {n_vias, delta_t_c}
        reason              : str — present on error
    """
    if target_delta_t_c <= 0:
        return {"ok": False, "reason": "target_delta_t_c must be > 0"}
    if n_via_options is None:
        n_via_options = [4, 8, 16, 32]

    baseline = solve_board_thermal_map(inp)
    if not baseline["ok"]:
        return {"ok": False, "reason": f"baseline solve failed: {baseline['reason']}"}

    baseline_dt = baseline["peak_T_c"] - inp.ambient_c

    if baseline_dt <= target_delta_t_c:
        return {
            "ok": True,
            "already_ok": True,
            "baseline_delta_t_c": round(baseline_dt, 4),
            "target_delta_t_c": target_delta_t_c,
            "copper_recommendation": None,
            "via_options": [],
        }

    # ── Sweep copper coverage ─────────────────────────────────────────────
    cu_min = None
    cu_dt = None
    step = 0.05
    f = inp.copper_coverage + step
    while f <= 1.0 + 1e-9:
        f_clamped = min(1.0, f)
        trial = BoardThermalMapInput(
            width_m=inp.width_m,
            height_m=inp.height_m,
            copper_coverage=f_clamped,
            components=inp.components,
            thermal_vias=inp.thermal_vias,
            ambient_c=inp.ambient_c,
            h_conv=inp.h_conv,
            epsilon=inp.epsilon,
            airflow_m_per_s=inp.airflow_m_per_s,
            board_length_m=inp.board_length_m,
            t_board_m=inp.t_board_m,
            nx=inp.nx,
            ny=inp.ny,
            max_iter=inp.max_iter,
            tol_k=inp.tol_k,
        )
        res = solve_board_thermal_map(trial)
        if res["ok"]:
            dt = res["peak_T_c"] - inp.ambient_c
            if dt <= target_delta_t_c:
                cu_min = f_clamped
                cu_dt = round(dt, 4)
                break
        f += step

    copper_rec = {
        "min_coverage": cu_min,
        "delta_t_c": cu_dt,
        "note": (
            "Copper coverage alone cannot reach target"
            if cu_min is None
            else f"Increase copper coverage to {cu_min:.2f}"
        ),
    }

    # ── Sweep via counts at hotspot ────────────────────────────────────────
    peak_j, peak_i = baseline["peak_ij"]
    via_results = []
    for nv in n_via_options:
        # Add a via cluster at the peak cell centre
        vx = (peak_i + 0.5) * (inp.width_m / inp.nx)
        vy = (peak_j + 0.5) * (inp.height_m / inp.ny)
        existing_vias = list(inp.thermal_vias)
        existing_vias.append(ThermalVia(x_m=vx, y_m=vy, n_vias=nv))
        via_trial = BoardThermalMapInput(
            width_m=inp.width_m,
            height_m=inp.height_m,
            copper_coverage=inp.copper_coverage,
            components=inp.components,
            thermal_vias=existing_vias,
            ambient_c=inp.ambient_c,
            h_conv=inp.h_conv,
            epsilon=inp.epsilon,
            airflow_m_per_s=inp.airflow_m_per_s,
            board_length_m=inp.board_length_m,
            t_board_m=inp.t_board_m,
            nx=inp.nx,
            ny=inp.ny,
            max_iter=inp.max_iter,
            tol_k=inp.tol_k,
        )
        vres = solve_board_thermal_map(via_trial)
        if vres["ok"]:
            vdt = round(vres["peak_T_c"] - inp.ambient_c, 4)
        else:
            vdt = None
        via_results.append({"n_vias": nv, "delta_t_c": vdt})

    return {
        "ok": True,
        "already_ok": False,
        "baseline_delta_t_c": round(baseline_dt, 4),
        "target_delta_t_c": target_delta_t_c,
        "copper_recommendation": copper_rec,
        "via_options": via_results,
    }


# ── LLM-tool layer ────────────────────────────────────────────────────────────

import json
from typing import Any

try:
    from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

    class ToolSpec:  # type: ignore
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def err_payload(msg, code="ERROR"):  # type: ignore
        return json.dumps({"ok": False, "error": msg, "code": code})

    def ok_payload(v):  # type: ignore
        return json.dumps({"ok": True, **v})

    def register(spec, write=False):  # type: ignore
        return lambda fn: fn


# ── Tool 1: board_thermal_map ─────────────────────────────────────────────────

_BOARD_THERMAL_MAP_SPEC = ToolSpec(
    name="board_thermal_map",
    description=(
        "Solve the 2D steady-state thermal field over a PCB plane and identify "
        "hotspots, per-component junction temperatures, and energy balance.\n\n"
        "Models in-plane conduction with copper-coverage-weighted effective k, "
        "per-component power sources, thermal vias to a cold backside node, "
        "and convection + radiation boundary.  Optional forced-convection "
        "coefficient via airflow_m_per_s + board_length_m.\n\n"
        "Returns:\n"
        "  T_field          — ny × nx temperature grid (°C)\n"
        "  peak_T_c         — board hotspot temperature (°C)\n"
        "  peak_ij          — [j,i] grid index of hotspot\n"
        "  components       — per-component Tj, over_limit, margin_c\n"
        "  energy_balance_err — |P_in−P_out|/P_in (should be ≪1)\n\n"
        "Never raises; validation errors return {ok:false, reason:str}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width_m":  {"type": "number", "description": "Board width in metres."},
            "height_m": {"type": "number", "description": "Board height in metres."},
            "copper_coverage": {
                "type": "number",
                "description": "Uniform copper coverage fraction [0,1]. Default 0.3.",
                "default": 0.3,
            },
            "ambient_c": {
                "type": "number",
                "description": "Ambient temperature (°C). Default 25.",
                "default": 25.0,
            },
            "h_conv": {
                "type": "number",
                "description": "Natural convection coefficient W/(m²·°C). Default 10.",
                "default": 10.0,
            },
            "epsilon": {
                "type": "number",
                "description": "Surface emissivity [0,1]. Default 0.9.",
                "default": 0.9,
            },
            "airflow_m_per_s": {
                "type": "number",
                "description": "Forced-airflow velocity m/s. 0 = natural convection.",
                "default": 0.0,
            },
            "board_length_m": {
                "type": "number",
                "description": "Characteristic length for forced-convection Nu (m).",
                "default": 0.0,
            },
            "t_board_m": {
                "type": "number",
                "description": "Board thickness for via conductance (m). Default 0.0016.",
                "default": 0.0016,
            },
            "nx": {"type": "integer", "description": "Grid cells in x. Default 20.", "default": 20},
            "ny": {"type": "integer", "description": "Grid cells in y. Default 20.", "default": 20},
            "components": {
                "type": "array",
                "description": (
                    "List of heat-dissipating components. Each item:\n"
                    "  ref (str), x_m (num), y_m (num), power_w (num),\n"
                    "  theta_jc (num, optional °C/W), tj_max_c (num, optional °C)"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "x_m": {"type": "number"},
                        "y_m": {"type": "number"},
                        "power_w": {"type": "number"},
                        "theta_jc": {"type": "number"},
                        "tj_max_c": {"type": "number"},
                    },
                    "required": ["ref", "x_m", "y_m", "power_w"],
                },
            },
            "thermal_vias": {
                "type": "array",
                "description": (
                    "List of thermal-via clusters. Each item:\n"
                    "  x_m (num), y_m (num), n_vias (int, default 1),\n"
                    "  r_via_m (num, default 0.00015)"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "x_m": {"type": "number"},
                        "y_m": {"type": "number"},
                        "n_vias": {"type": "integer"},
                        "r_via_m": {"type": "number"},
                    },
                    "required": ["x_m", "y_m"],
                },
            },
        },
        "required": ["width_m", "height_m"],
    },
)


@register(_BOARD_THERMAL_MAP_SPEC, write=False)
async def board_thermal_map_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    width_m = a.get("width_m")
    height_m = a.get("height_m")
    if not isinstance(width_m, (int, float)):
        return err_payload("width_m must be a number", "BAD_ARGS")
    if not isinstance(height_m, (int, float)):
        return err_payload("height_m must be a number", "BAD_ARGS")

    components = []
    for item in a.get("components", []):
        if not isinstance(item, dict):
            return err_payload("each component must be an object", "BAD_ARGS")
        try:
            components.append(BoardComponent(
                ref=str(item.get("ref", "")),
                x_m=float(item["x_m"]),
                y_m=float(item["y_m"]),
                power_w=float(item["power_w"]),
                theta_jc=float(item.get("theta_jc", 0.0)),
                tj_max_c=float(item["tj_max_c"]) if item.get("tj_max_c") is not None else None,
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"invalid component entry: {exc}", "BAD_ARGS")

    vias = []
    for item in a.get("thermal_vias", []):
        if not isinstance(item, dict):
            return err_payload("each thermal_via must be an object", "BAD_ARGS")
        try:
            vias.append(ThermalVia(
                x_m=float(item["x_m"]),
                y_m=float(item["y_m"]),
                n_vias=int(item.get("n_vias", 1)),
                r_via_m=float(item.get("r_via_m", 1.5e-4)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"invalid thermal_via entry: {exc}", "BAD_ARGS")

    inp = BoardThermalMapInput(
        width_m=float(width_m),
        height_m=float(height_m),
        copper_coverage=float(a.get("copper_coverage", 0.3)),
        components=components,
        thermal_vias=vias,
        ambient_c=float(a.get("ambient_c", 25.0)),
        h_conv=float(a.get("h_conv", _DEFAULT_H_NATURAL)),
        epsilon=float(a.get("epsilon", _DEFAULT_EPSILON)),
        airflow_m_per_s=float(a.get("airflow_m_per_s", 0.0)),
        board_length_m=float(a.get("board_length_m", 0.0)),
        t_board_m=float(a.get("t_board_m", _DEFAULT_T_BOARD_M)),
        nx=int(a.get("nx", 20)),
        ny=int(a.get("ny", 20)),
    )

    result = solve_board_thermal_map(inp)

    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")

    # Omit the full T_field from the LLM payload (can be very large); keep peak + summary
    payload = {k: v for k, v in result.items() if k != "T_field"}
    return ok_payload(payload)


# ── Tool 2: board_thermal_recommend ──────────────────────────────────────────

_BOARD_THERMAL_RECOMMEND_SPEC = ToolSpec(
    name="board_thermal_recommend",
    description=(
        "Recommend copper-coverage increase and/or thermal-via additions to bring "
        "the PCB hotspot ΔT below a target value.\n\n"
        "Solves the baseline field, then sweeps copper coverage (current → 1.0) "
        "and via counts at the hotspot cell to find the minimum changes needed.\n\n"
        "Returns {already_ok, baseline_delta_t_c, copper_recommendation, via_options}.\n"
        "Never raises; validation errors return {ok:false, reason:str}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "board": {
                "type": "object",
                "description": "Same schema as board_thermal_map input.",
            },
            "target_delta_t_c": {
                "type": "number",
                "description": "Target maximum ΔT above ambient (°C).",
            },
            "n_via_options": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Via-count candidates to evaluate. Default [4,8,16,32].",
            },
        },
        "required": ["board", "target_delta_t_c"],
    },
)


@register(_BOARD_THERMAL_RECOMMEND_SPEC, write=False)
async def board_thermal_recommend_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    board_data = a.get("board")
    target_dt = a.get("target_delta_t_c")

    if not isinstance(board_data, dict):
        return err_payload("board must be an object", "BAD_ARGS")
    if not isinstance(target_dt, (int, float)):
        return err_payload("target_delta_t_c must be a number", "BAD_ARGS")

    # Re-use the map tool's parsing by delegating through the raw dict
    sub_args = json.dumps(board_data).encode()
    map_resp_str = await board_thermal_map_tool(ctx, sub_args)
    map_resp = json.loads(map_resp_str)
    if not map_resp.get("ok"):
        return err_payload(f"board parse error: {map_resp.get('error', '?')}", "BAD_ARGS")

    # Re-parse board into BoardThermalMapInput
    bd = board_data
    components = []
    for item in bd.get("components", []):
        components.append(BoardComponent(
            ref=str(item.get("ref", "")),
            x_m=float(item["x_m"]),
            y_m=float(item["y_m"]),
            power_w=float(item["power_w"]),
            theta_jc=float(item.get("theta_jc", 0.0)),
            tj_max_c=float(item["tj_max_c"]) if item.get("tj_max_c") is not None else None,
        ))
    vias = []
    for item in bd.get("thermal_vias", []):
        vias.append(ThermalVia(
            x_m=float(item["x_m"]),
            y_m=float(item["y_m"]),
            n_vias=int(item.get("n_vias", 1)),
            r_via_m=float(item.get("r_via_m", 1.5e-4)),
        ))

    inp = BoardThermalMapInput(
        width_m=float(bd["width_m"]),
        height_m=float(bd["height_m"]),
        copper_coverage=float(bd.get("copper_coverage", 0.3)),
        components=components,
        thermal_vias=vias,
        ambient_c=float(bd.get("ambient_c", 25.0)),
        h_conv=float(bd.get("h_conv", _DEFAULT_H_NATURAL)),
        epsilon=float(bd.get("epsilon", _DEFAULT_EPSILON)),
        airflow_m_per_s=float(bd.get("airflow_m_per_s", 0.0)),
        board_length_m=float(bd.get("board_length_m", 0.0)),
        t_board_m=float(bd.get("t_board_m", _DEFAULT_T_BOARD_M)),
        nx=int(bd.get("nx", 20)),
        ny=int(bd.get("ny", 20)),
    )

    n_via_opts = a.get("n_via_options", [4, 8, 16, 32])
    if not isinstance(n_via_opts, list):
        return err_payload("n_via_options must be an array", "BAD_ARGS")

    result = recommend_copper_and_vias(inp, float(target_dt), n_via_opts)

    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")

    return ok_payload(result)


# ── TOOLS registry ────────────────────────────────────────────────────────────

TOOLS = [
    ("board_thermal_map", _BOARD_THERMAL_MAP_SPEC, board_thermal_map_tool),
    ("board_thermal_recommend", _BOARD_THERMAL_RECOMMEND_SPEC, board_thermal_recommend_tool),
]
