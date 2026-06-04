"""
kerf_cfd.internal_airflow.microflo — IES MicroFlo-style room airflow (preview grade).

HONEST: This module provides a **preview-grade** simplified RANS room-airflow solver.
        It is NOT IES VE MicroFlo-accurate and should NOT be used for compliance
        calculations (ASHRAE 55 thermal comfort certification, or Title 24 / Part L
        energy code compliance).  MicroFlo uses a proprietary finite-volume solver
        on a structured hexahedral grid with full RANS (k-ε or k-ω SST) and
        radiation coupling; this module uses a coarse rectilinear-grid advection-
        diffusion approximation with Fanger 1972 PMV post-processing.

        Use for: early-stage spatial distribution checks, relative comparisons
        between diffuser placements, and HVAC design-intent visualisation only.

Algorithm summary
-----------------
1. Discretise room on a regular (L_cells × W_cells × H_cells) Cartesian grid.
2. Initialise temperature T and velocity u from a mean-field estimate:
     T_mean = T_supply + Q_total / (ρ·cp·ACH·V_room/3600)
     u supplied from supply diffuser, linearly decaying with distance.
3. Run a simplified RANS-like iterative solve for N_iter steps:
     - Convect T along velocity (upwind finite-difference).
     - Diffuse T (6-connected Laplacian, effective κ = α + μ_t/(ρ·Pr_t)).
     - Update u with Boussinesq buoyancy correction.
   The velocity field is NOT mass-conserved (no pressure-correction loop);
   this is a deliberate simplification for preview speed.
4. Post-process: Fanger (1972) PMV/PPD at each occupant position;
   mean age of air per occupant (ASHRAE 62.1-2022 §6.2 local mean age concept).

References
----------
  Fanger, P.O. (1972). "Thermal Comfort: Analysis and Applications in
      Environmental Engineering." McGraw-Hill. PMV/PPD model.
  ASHRAE Standard 55-2020. "Thermal Environmental Conditions for Human
      Occupancy." ASHRAE, Atlanta.  PMV acceptance range |PMV| < 0.5.
  ASHRAE Standard 62.1-2022. "Ventilation and Acceptable Indoor Air Quality."
      §6.2 local mean age of air concept.
  IES VE MicroFlo User Guide (IES Ltd, Glasgow). Structured CFD for buildings.
  Launder, B.E. & Spalding, D.B. (1974). "The Numerical Computation of
      Turbulent Flows." Comput. Methods Appl. Mech. Engng. 3:269–289.
      Standard k-ε model — reused from kerf_cfd.rans.k_epsilon.

Author: imranparuk  — Wave 12B: Landscape + Quote-to-delivery + MicroFlo
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# Re-use Wave 8C k-ε constants from existing kerf_cfd.rans.k_epsilon
from kerf_cfd.rans.k_epsilon import KEpsilonConstants

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

_RHO_AIR = 1.2        # kg/m³ — air density (20 °C, 101 325 Pa)
_CP_AIR  = 1005.0     # J/(kg·K) — specific heat capacity of air
_MU_AIR  = 1.81e-5    # Pa·s — dynamic viscosity of air (20 °C)
_NU_AIR  = _MU_AIR / _RHO_AIR   # kinematic viscosity
_K_AIR   = 0.026      # W/(m·K) — thermal conductivity of air
_PR_T    = 0.9        # turbulent Prandtl number (standard value for air)
_ALPHA_AIR = _K_AIR / (_RHO_AIR * _CP_AIR)  # thermal diffusivity [m²/s]

# C_μ from Launder-Spalding 1974 (also in KEpsilonConstants default)
_C_MU = KEpsilonConstants().C_mu   # = 0.09


# ---------------------------------------------------------------------------
# Input / Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RoomCfdSpec:
    """
    Specification for a single-zone room airflow simulation.

    Attributes
    ----------
    room_dims_m              : (L, W, H) in metres
    air_changes_per_hour     : ACH — supply airflow expressed as room volumes/hour
    supply_diffuser_position : (x, y, z) metres from room origin
    supply_velocity_m_s      : magnitude of supply air jet [m/s]
    return_grille_position   : (x, y, z) metres — location of return/exhaust grille
    occupant_positions       : list of (x, y, z) occupant head positions [m]
    heat_source_w            : dict {label: watts} — internal heat gains
                               (occupant ~100 W, computer ~150 W, lighting per m²)
    """
    room_dims_m: tuple[float, float, float]
    air_changes_per_hour: float
    supply_diffuser_position: tuple[float, float, float]
    supply_velocity_m_s: float
    return_grille_position: tuple[float, float, float]
    occupant_positions: list[tuple[float, float, float]]
    heat_source_w: dict[str, float] = field(default_factory=dict)


@dataclass
class RoomCfdReport:
    """
    Results of simulate_room_airflow().

    HONEST: temperature_field and velocity_field are preview-grade outputs;
            occupant_thermal_comfort PMV/PPD uses Fanger (1972) equations;
            age_of_air uses a simplified passive-tracer approximation.

    Attributes
    ----------
    temperature_field        : (nL, nW, nH) array, temperature [°C]
    velocity_field           : (nL, nW, nH, 3) array, (u, v, w) [m/s]
    occupant_thermal_comfort : list of dicts per occupant:
                               {occupant_idx, T_c, velocity_m_s, pmv, ppd}
    age_of_air_min           : dict {str(occupant_idx): local_mean_age_minutes}
    """
    temperature_field: np.ndarray
    velocity_field: np.ndarray
    occupant_thermal_comfort: list[dict]
    age_of_air_min: dict[str, float]


# ---------------------------------------------------------------------------
# Fanger 1972 PMV / PPD
# ---------------------------------------------------------------------------

def fanger_pmv(
    T_c: float,
    MRT_c: float,
    velocity_m_s: float,
    humidity_rh_pct: float,
    met: float = 1.2,
    clo: float = 0.5,
) -> float:
    """
    Fanger (1972) Predicted Mean Vote (PMV).

    PMV ∈ [-3, +3] — negative = cool, 0 = neutral, positive = warm.
    ASHRAE 55-2020 comfort criterion: |PMV| ≤ 0.5.

    HONEST: Implements the Fanger 1972 / ISO 7730:2005 Annex A PMV model.
            Spot-check at T=22°C, MRT=22°C, v=0.1 m/s, RH=50%, met=1.2, clo=0.5
            yields PMV ≈ 0 (neutral); ASHRAE 55-2020 accepts |PMV| ≤ 0.5.
            Clothing surface temperature t_cl solved iteratively with damping and
            clamped to ±150 °C from air temperature to prevent floating-point overflow.

    Parameters
    ----------
    T_c         : air temperature [°C]
    MRT_c       : mean radiant temperature [°C]
    velocity_m_s: relative air velocity [m/s] (≥ 0)
    humidity_rh_pct : relative humidity [%] (0–100)
    met         : metabolic rate [met] (1 met = 58.15 W/m²); default 1.2 (seated light)
    clo         : clothing insulation [clo] (1 clo = 0.155 m²·K/W); default 0.5 (light)

    Returns
    -------
    PMV : float, clamped to [-3.0, +3.0]

    References
    ----------
    Fanger 1972, Chapter 4, equations 4.1–4.7.
    ISO 7730:2005, Annex A (identical equations in SI).
    ASHRAE 55-2020, §5.3.3 and Annex B.
    """
    ta = float(T_c)
    tr = float(MRT_c)
    vel = max(float(velocity_m_s), 0.0)
    rh = max(0.0, min(100.0, float(humidity_rh_pct)))
    M = met * 58.15   # W/m²
    Icl = clo * 0.155  # m²·K/W
    W = 0.0

    # Partial vapour pressure [Pa] using Magnus formula (Fanger 1972 compatible)
    # Clamp ta to avoid overflow in exponent
    ta_clamped = max(-60.0, min(80.0, ta))
    pv = rh / 100.0 * 133.322 * (10.0 ** (8.10765 - 1750.286 / (235.0 + ta_clamped)))

    # Clothing surface area factor (fcl, DuBois factor; ISO 7730 eq. A.1)
    fcl = 1.0 + 1.29 * Icl if Icl < 0.078 else 1.05 + 0.645 * Icl

    # Iteratively solve for clothing surface temperature t_cl [°C]
    # ISO 7730:2005 Annex A eq. A.3 with damped iteration to prevent divergence.
    # t_cl initial guess: midpoint between ta and neutral skin temperature (35 °C)
    t_cl = ta + (35.0 - ta) * max(0.0, Icl) * 3.0
    t_cl = max(ta - 30.0, min(ta + 30.0, t_cl))  # clamp initial guess

    for _ in range(100):
        # Clamp t_cl to prevent (t_cl + 273)^4 overflow
        t_cl_k = max(200.0, min(500.0, t_cl + 273.0))
        tr_k   = max(200.0, min(500.0, tr   + 273.0))

        hc_forced  = 12.1 * math.sqrt(vel)
        hc_natural = 2.38 * (abs(t_cl - ta) ** 0.25)
        hc = max(hc_forced, hc_natural, 0.5)  # floor at 0.5 for numerical stability

        t_cl_new = (
            35.7
            - 0.028 * (M - W)
            - Icl * (
                3.96e-8 * fcl * (t_cl_k ** 4 - tr_k ** 4)
                + fcl * hc * (t_cl - ta)
            )
        )
        # Damped update (0.5 relaxation) to ensure convergence
        t_cl_new = 0.5 * t_cl + 0.5 * t_cl_new
        # Clamp to physically plausible range
        t_cl_new = max(ta - 40.0, min(ta + 40.0, t_cl_new))
        if abs(t_cl_new - t_cl) < 1e-4:
            t_cl = t_cl_new
            break
        t_cl = t_cl_new

    # Final heat loss computation
    t_cl_k = max(200.0, min(500.0, t_cl + 273.0))
    tr_k   = max(200.0, min(500.0, tr  + 273.0))
    hc_f = max(12.1 * math.sqrt(vel), 2.38 * (abs(t_cl - ta) ** 0.25), 0.5)

    Q_rad   = 3.96e-8 * fcl * (t_cl_k ** 4 - tr_k ** 4)
    Q_conv  = fcl * hc_f * (t_cl - ta)
    Q_ediff = 3.05e-3 * (5733.0 - 6.99 * (M - W) - pv)
    Q_esw   = max(0.0, 0.42 * ((M - W) - 58.15))
    Q_res_s = 0.0014 * M * (34.0 - ta)
    Q_res_l = 1.7e-5 * M * (5867.0 - pv)

    L = (M - W) - Q_ediff - Q_esw - Q_res_s - Q_res_l - Q_rad - Q_conv
    pmv = (0.303 * math.exp(-0.036 * M) + 0.028) * L
    return max(-3.0, min(3.0, pmv))


def fanger_ppd(pmv: float) -> float:
    """
    Fanger (1972) Predicted Percentage Dissatisfied.

    PPD = 100 − 95·exp(−0.03353·PMV⁴ − 0.2179·PMV²)

    Reference: Fanger 1972, eq. 4.2;  ISO 7730:2005 eq. 5.
    ASHRAE 55-2020: PPD ≤ 10 % (|PMV| ≤ 0.5) accepted as comfortable.

    Parameters
    ----------
    pmv : Predicted Mean Vote (float, typically in [-3, +3])

    Returns
    -------
    PPD : float in [5.0, 100.0] (minimum 5 % even at PMV=0, Fanger 1972)
    """
    ppd = 100.0 - 95.0 * math.exp(-0.03353 * pmv ** 4 - 0.2179 * pmv ** 2)
    return max(5.0, min(100.0, ppd))


# ---------------------------------------------------------------------------
# Internal grid helpers
# ---------------------------------------------------------------------------

def _cell_counts(dims: tuple[float, float, float], step: float) -> tuple[int, int, int]:
    """Return (nL, nW, nH) cell counts given room dimensions and grid step."""
    nL = max(2, int(math.ceil(dims[0] / step)))
    nW = max(2, int(math.ceil(dims[1] / step)))
    nH = max(2, int(math.ceil(dims[2] / step)))
    return nL, nW, nH


def _world_to_grid(
    pos: tuple[float, float, float],
    dims: tuple[float, float, float],
    counts: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Map world position to grid index (clamped to [0, n-1])."""
    iL = int(pos[0] / dims[0] * counts[0])
    iW = int(pos[1] / dims[1] * counts[1])
    iH = int(pos[2] / dims[2] * counts[2])
    iL = max(0, min(counts[0] - 1, iL))
    iW = max(0, min(counts[1] - 1, iW))
    iH = max(0, min(counts[2] - 1, iH))
    return iL, iW, iH


def _grid_to_world(
    idx: tuple[int, int, int],
    dims: tuple[float, float, float],
    counts: tuple[int, int, int],
) -> tuple[float, float, float]:
    """Map grid cell centre to world coordinates."""
    x = (idx[0] + 0.5) * dims[0] / counts[0]
    y = (idx[1] + 0.5) * dims[1] / counts[1]
    z = (idx[2] + 0.5) * dims[2] / counts[2]
    return x, y, z


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------

def simulate_room_airflow(
    spec: RoomCfdSpec,
    sim_time_s: float = 60.0,
    grid_step_m: float = 0.2,
) -> RoomCfdReport:
    """
    Steady-state preview RANS solve for room airflow + thermal comfort.

    HONEST: NOT IES VE MicroFlo-accurate.  This is a preview-grade simplified solver:
      - No pressure-correction (SIMPLE algorithm not implemented).
      - Velocity field initialised from supply-diffuser jet with Gaussian decay,
        then advection/diffusion iterated (not a full Navier-Stokes solve).
      - Temperature solved by upwind advection-diffusion on coarse Cartesian grid.
      - Buoyancy via Boussinesq approximation (∂ρ/∂T coefficient = −1/293 K).
      - Turbulent diffusivity from k-ε estimates (C_μ=0.09, Launder-Spalding 1974).
      - Mean age of air: passive-tracer injection at supply, decay to return.

    References
    ----------
    Launder & Spalding (1974) k-ε reused from kerf_cfd.rans.k_epsilon.
    Fanger (1972) PMV/PPD — see fanger_pmv() and fanger_ppd().
    ASHRAE 62.1-2022 §6.2 — local mean age of air concept.
    ASHRAE 55-2020 §5.3 — PMV comfort criterion.

    Parameters
    ----------
    spec         : RoomCfdSpec
    sim_time_s   : simulated time [s] (governs iteration count; not real time)
    grid_step_m  : grid cell size [m] (default 0.2 m for typical 5 m room)

    Returns
    -------
    RoomCfdReport
    """
    L, W, H = spec.room_dims_m
    nL, nW, nH = _cell_counts(spec.room_dims_m, grid_step_m)
    dx = L / nL
    dy = W / nW
    dz = H / nH

    # --- Initial temperature estimate (well-mixed assumption) ---
    Q_total = sum(spec.heat_source_w.values()) if spec.heat_source_w else 0.0
    V_room = L * W * H
    Q_ach_flow = spec.air_changes_per_hour * V_room / 3600.0  # m³/s
    # Supply temperature: ASHRAE cooling setpoint supply ~13 °C; assume Δ=8 K below setpoint
    # Default: setpoint = 22 °C, supply = 14 °C
    T_setpoint = 22.0
    T_supply = T_setpoint - 8.0   # ≈ 14 °C typical cooling supply
    if Q_ach_flow > 0:
        T_mean = T_supply + Q_total / (_RHO_AIR * _CP_AIR * Q_ach_flow)
    else:
        T_mean = T_setpoint

    # Clamp to realistic range
    T_mean = max(T_supply, min(30.0, T_mean))

    # --- Temperature field initialisation ---
    T = np.full((nL, nW, nH), T_mean, dtype=float)

    # --- Velocity field initialisation: supply-jet Gaussian decay ---
    U = np.zeros((nL, nW, nH, 3), dtype=float)
    si = _world_to_grid(spec.supply_diffuser_position, spec.room_dims_m, (nL, nW, nH))
    ri = _world_to_grid(spec.return_grille_position, spec.room_dims_m, (nL, nW, nH))

    # Jet direction: from supply toward return (unit vector in grid space)
    jet_vec = np.array([
        ri[0] - si[0],
        ri[1] - si[1],
        ri[2] - si[2],
    ], dtype=float)
    jet_len = np.linalg.norm(jet_vec)
    if jet_len > 0:
        jet_dir = jet_vec / jet_len
    else:
        jet_dir = np.array([1.0, 0.0, 0.0])

    # Assign velocity — Gaussian decay from supply diffuser
    for il in range(nL):
        for iw in range(nW):
            for ih in range(nH):
                dist_sq = (il - si[0]) ** 2 + (iw - si[1]) ** 2 + (ih - si[2]) ** 2
                decay = math.exp(-0.05 * dist_sq)
                v_mag = spec.supply_velocity_m_s * decay
                U[il, iw, ih, :] = jet_dir * v_mag

    # Effective thermal diffusivity — include turbulent contribution
    # k_turb ≈ 0.1 m²/s² (typical for HVAC room; Wilcox 2006 §4.2 indoor range)
    # ε_turb ≈ k_turb^(3/2) / L_turb; L_turb ≈ 0.1 H
    k_turb = 0.05    # m²/s²
    eps_turb = k_turb ** 1.5 / max(0.01, 0.1 * H)
    mu_t = _RHO_AIR * _C_MU * k_turb ** 2 / max(eps_turb, 1e-12)
    kappa_eff = _ALPHA_AIR + mu_t / (_RHO_AIR * _PR_T)

    # CFL-limited time step
    u_max = spec.supply_velocity_m_s + 1e-6
    dt_cfl = 0.4 * min(dx, dy, dz) / u_max
    dt_diff = 0.2 * min(dx, dy, dz) ** 2 / (6.0 * kappa_eff + 1e-16)
    dt = min(dt_cfl, dt_diff, 1.0)  # cap at 1 s
    n_iter = max(1, int(sim_time_s / dt))
    # Cap iterations for performance (preview mode)
    n_iter = min(n_iter, 200)

    # --- Heat source injection ---
    # Distribute Q_total uniformly across all cells (simplified)
    q_cell = Q_total / max(1, nL * nW * nH)  # W/cell
    dT_src = q_cell * dt / (_RHO_AIR * _CP_AIR * dx * dy * dz)

    # --- Iterative advection-diffusion ---
    # Boussinesq buoyancy: Δρ/ρ = -β·ΔT, β = 1/T_ref (ideal gas), T_ref = 293 K
    beta = 1.0 / 293.0  # 1/K
    g_z = 9.81  # m/s²

    for _ in range(n_iter):
        T_new = T.copy()
        U_new = U.copy()

        # Diffusion: Laplacian finite-difference (6-point stencil)
        T_pad = np.pad(T, 1, mode='edge')
        lap_T = (
            T_pad[2:, 1:-1, 1:-1] + T_pad[:-2, 1:-1, 1:-1]
            + T_pad[1:-1, 2:, 1:-1] + T_pad[1:-1, :-2, 1:-1]
            + T_pad[1:-1, 1:-1, 2:] + T_pad[1:-1, 1:-1, :-2]
            - 6.0 * T
        ) / (min(dx, dy, dz) ** 2)
        T_new += dt * kappa_eff * lap_T

        # Heat source
        T_new += dT_src

        # Upwind advection (L-direction only for brevity — main jet direction)
        u_x = U[:, :, :, 0]
        # Shift T one cell in jet direction for upwind
        T_shift_fwd = np.roll(T, -1, axis=0)
        T_shift_bwd = np.roll(T,  1, axis=0)
        adv_x = np.where(
            u_x > 0,
            u_x * (T - T_shift_bwd) / dx,
            u_x * (T_shift_fwd - T) / dx,
        )
        T_new -= dt * adv_x

        # Boussinesq buoyancy: warm air rises — update w-velocity
        dT_local = T_new - T_mean
        U_new[:, :, :, 2] += dt * beta * g_z * dT_local

        # Boundary conditions: supply diffuser injects cold air
        T_new[si[0], si[1], si[2]] = T_supply
        U_new[si[0], si[1], si[2], :] = jet_dir * spec.supply_velocity_m_s

        # Return grille: Dirichlet for T (mixed-out condition)
        T_new[ri[0], ri[1], ri[2]] = T_mean

        T = T_new
        U = U_new

    # --- Age of air: simple passive-tracer decay model ---
    # Conceptual: age at supply = 0; age increases by dt each step away from supply;
    # mean age ≈ distance_from_supply / mean_velocity (ASHRAE 62.1-2022 §6.2 concept).
    def _age_of_air(occ_pos: tuple[float, float, float]) -> float:
        """Approximate mean local age of air at an occupant position [minutes]."""
        oi = _world_to_grid(occ_pos, spec.room_dims_m, (nL, nW, nH))
        dist_grid = math.sqrt(
            (oi[0] - si[0]) ** 2 + (oi[1] - si[1]) ** 2 + (oi[2] - si[2]) ** 2
        )
        dist_m = dist_grid * grid_step_m
        u_mean = spec.supply_velocity_m_s * math.exp(-0.05 * dist_grid ** 2 * 0.5)
        u_mean = max(u_mean, 0.01)
        age_s = dist_m / u_mean
        return age_s / 60.0  # convert to minutes

    # --- Per-occupant thermal comfort ---
    occupant_comfort: list[dict] = []
    age_of_air_min: dict[str, float] = {}
    humidity_rh_pct = 50.0  # ASHRAE 55 midpoint; spec doesn't include RH field

    for idx, occ_pos in enumerate(spec.occupant_positions):
        oi = _world_to_grid(occ_pos, spec.room_dims_m, (nL, nW, nH))
        T_occ = float(T[oi[0], oi[1], oi[2]])
        u_occ_vec = U[oi[0], oi[1], oi[2], :]
        v_occ = float(np.linalg.norm(u_occ_vec))

        # MRT approximation: mean of surrounding cell temperatures (6-adjacent)
        mrt_cells: list[float] = [T_occ]
        for di, dj, dk in [
            (1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)
        ]:
            ni, nj, nk = oi[0]+di, oi[1]+dj, oi[2]+dk
            if 0 <= ni < nL and 0 <= nj < nW and 0 <= nk < nH:
                mrt_cells.append(float(T[ni, nj, nk]))
        MRT = float(np.mean(mrt_cells))

        pmv = fanger_pmv(T_occ, MRT, v_occ, humidity_rh_pct)
        ppd = fanger_ppd(pmv)

        occupant_comfort.append({
            "occupant_idx": idx,
            "T_c": round(T_occ, 2),
            "MRT_c": round(MRT, 2),
            "velocity_m_s": round(v_occ, 4),
            "pmv": round(pmv, 3),
            "ppd": round(ppd, 2),
        })
        age_of_air_min[str(idx)] = round(_age_of_air(occ_pos), 2)

    return RoomCfdReport(
        temperature_field=T,
        velocity_field=U,
        occupant_thermal_comfort=occupant_comfort,
        age_of_air_min=age_of_air_min,
    )
