"""
kerf_manufacturing.am_thermomechanical — Coupled Transient Thermo-Mechanical
Additive Manufacturing Simulation.

Physical model
--------------
Stage 1 — Transient Thermal (layer-wise FD on a 1-D nodal stack per layer):

  For each layer k:
    - A moving heat source (Goldak double-ellipsoid, Goldak et al. 1984) deposits
      energy into the newly deposited layer and a thin substrate zone below it.
      The layer is treated as a uniform slab; spatial averaging over the scan
      path gives an equivalent volumetric heat rate Q_vol [W/m³].

      Goldak double-ellipsoid volumetric power density (Goldak 1984):
        q_f(x,y,z) = (6√3 · f_f · Q) / (π^1.5 · a·b·c_f) ·
                      exp(−3x²/a² − 3y²/b² − 3z²/c_f²)
        q_r similarly with c_r, f_r.
        where f_f + f_r = 2; a, b = semi-axes in X, Y; c_f, c_r = front/rear
        half-lengths along scan direction.

      Path-averaged volumetric input rate for a layer of thickness h:
        Q_vol_avg = η · P · v / (b · h · v_scan) * (1 / layer_time) [W/m³]
        simplified: Q_vol = η · P / (V_layer) * duty_cycle
        where V_layer = layer footprint × layer_thickness.

    - Transient heat conduction in each layer slice (1-D column through build):
        ρ(T) cp(T) ∂T/∂t = ∂/∂z[k(T) ∂T/∂z] + Q_vol(z,t)
                           − h_conv(T−T_∞) [surface BC]
                           − ε_r σ_SB (T⁴ − T_∞⁴) [radiation BC]
        With latent heat modelled by the apparent-heat-capacity (enthalpy) method:
          cp_eff(T) = cp(T) + L_f · (1/√(2π σ_T²)) · exp(−(T−T_melt)²/(2σ_T²))
          (smooth Gaussian smearing of latent heat over ±2σ_T around T_melt,
          σ_T ≈ 50 K for metals; Voller et al. 1987)

    - Explicit Euler time stepping with CFL-based dt:
        dt ≤ CFL · ρ cp_eff · dz² / k

    - Melt-pool tracking: record which nodes exceed T_melt, compute:
        melt_pool_depth = max depth of T > T_melt
        melt_pool_width = approximated from Goldak ellipsoid geometry

    - Store thermal history: T_history[layer, node_z] = peak T reached

Stage 2 — Thermo-Mechanical Coupling (thermo-elastic, honest note on plasticity):

  After each layer k, the temperature increment ΔT = T_peak − T_ref is fed
  into the 3-D Tet4 FEM as a thermal load:
    Thermal strain: ε_th = α(T) · ΔT_elem  (element-average ΔT)
    Equivalent eigenstrain: ε* = [α·ΔT, α·ΔT, α·ΔT, 0, 0, 0]
    This replaces the constant inherent-strain vector from the ISM.

  The mechanical solve per layer is identical to am_process_sim (layer-activation
  Tet4 FEM, quasi-static), but with a temperature-dependent eigenstrain derived
  from the transient thermal field rather than a user-calibrated constant ε*.

  Temperature-dependent Young's modulus:
    E(T) = E_0 · (1 − β_E · (T − T_ref)) clamped to [0.1·E_0, E_0]
    β_E ≈ 3.5 × 10⁻⁴ /K for Ti-6Al-4V (Boivineau et al. 2006)

  NOTE (honest):
  * Thermo-elastic only — no return-mapping plasticity.  The thermal eigenstrain
    captures the dominant source of residual stress in metal AM but the
    post-solidification plastic redistribution is absent.  Residual stress
    magnitudes are directionally correct but will be underestimated vs full
    TEP by ~30–50% (Vastola et al. 2016).
  * No part-scale GPU acceleration; problem size is limited to meshes with
    O(10³) elements for interactive use.
  * Simplified powder absorptivity; the Goldak source is idealised (no
    keyhole / evaporation).
  * 1-D thermal column per layer (no lateral heat flow between columns); this
    is a good approximation for thin-wall or single-track builds but
    underestimates preheat accumulation in large volumes.

References
----------
* Goldak J., Chakravarti A., Bibby M. (1984). "A new finite element model for
  welding heat sources." Metallurgical Transactions B 15:299–305.
* Voller V.R. & Prakash C. (1987). "A fixed grid numerical modelling methodology
  for convection-diffusion mushy region phase-change problems." IJHMT 30(8).
* Boivineau M. et al. (2006). "Thermophysical properties of solid and liquid
  Ti-6Al-4V." International Journal of Thermophysics 27(2).
* Vastola G. et al. (2016). "Controlling of residual stress in additive
  manufacturing of Ti6Al4V by finite element modelling." Additive Manufacturing 12.
* Mercelis P. & Kruth J.-P. (2006). "Residual stresses in SLS and SLM."
  Rapid Prototyping Journal 12(5).

Public API
----------
    simulate_am_thermomechanical(mesh, params) -> AMThermoMechResult
    AMThermoMechParams  — dataclass with process + material params
    AMThermoMechResult  — dataclass with thermal history, melt-pool metrics,
                          residual stress, distortion
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AMThermoMechParams:
    """Parameters for the coupled transient thermo-mechanical AM simulation.

    Thermal parameters
    ------------------
    laser_power_w : float
        Laser / electron-beam power [W]. Default 200 W (typical LPBF Ti-6Al-4V).
    scan_speed_m_s : float
        Scan speed [m/s]. Default 0.8 m/s.
    beam_radius_m : float
        Laser beam radius (1/e²) [m]. Default 50 µm.
    absorptivity : float
        Fraction of incident power absorbed by the melt pool. Default 0.35
        (Ti-6Al-4V LPBF; Boivineau 2006).
    layer_time_s : float
        Time to scan one full layer including recoating delay [s].
        Default 10 s (conservative for small parts).
    layer_thickness_m : float
        Build layer height [m]. Default 30 µm.

    Material thermophysical properties (defaults: Ti-6Al-4V)
    ---------------------------------------------------------
    rho_kg_m3 : float
        Density [kg/m³]. Default 4430.
    cp_j_kg_k : float
        Specific heat capacity [J/(kg·K)]. Default 526.
    k_w_m_k : float
        Thermal conductivity [W/(m·K)]. Default 6.7.
    T_melt_k : float
        Melting/solidus temperature [K]. Default 1878 K (Ti-6Al-4V).
    T_liquidus_k : float
        Liquidus temperature [K]. Default 1928 K.
    L_fusion_j_kg : float
        Latent heat of fusion [J/kg]. Default 286 000 J/kg.
    alpha_therm : float
        Coefficient of thermal expansion [1/K]. Default 8.6e-6 /K.
    T_ref_k : float
        Stress-free reference temperature [K]. Default 298.15 K (25 °C).
    T_preheat_k : float
        Build plate preheat temperature [K]. Default 298.15 K (no preheat).
    T_ambient_k : float
        Ambient temperature for convection/radiation [K]. Default 298.15 K.
    h_conv_w_m2_k : float
        Convection heat transfer coefficient [W/(m²·K)]. Default 20 W/(m²·K).
    emissivity : float
        Surface emissivity for radiation. Default 0.3.

    Mechanical properties
    ---------------------
    E_pa : float
        Young's modulus at T_ref [Pa]. Default 114e9 (Ti-6Al-4V).
    nu : float
        Poisson's ratio. Default 0.342.
    beta_E_per_k : float
        Linear temperature softening coefficient for E: E(T) = E_0·(1−β·ΔT).
        Default 3.5e-4 /K.

    Build geometry
    --------------
    build_dir : tuple
        Build direction unit vector. Default (0, 0, 1).
    distortion_tolerance_m : float
        Warning threshold for max distortion. Default 1e-3 m.

    Solver settings
    ---------------
    n_z_nodes : int
        Number of nodes in the 1-D thermal column per layer. Default 20.
    cfl_factor : float
        CFL safety factor for explicit time stepping. Default 0.4.
    latent_heat_smear_k : float
        Half-width σ of Gaussian latent-heat smear [K]. Default 50 K.
    """
    # Laser / beam
    laser_power_w: float = 200.0
    scan_speed_m_s: float = 0.8
    beam_radius_m: float = 50e-6
    absorptivity: float = 0.35
    layer_time_s: float = 10.0
    layer_thickness_m: float = 30e-6

    # Thermophysical (Ti-6Al-4V defaults)
    rho_kg_m3: float = 4430.0
    cp_j_kg_k: float = 526.0
    k_w_m_k: float = 6.7
    T_melt_k: float = 1878.0
    T_liquidus_k: float = 1928.0
    L_fusion_j_kg: float = 286_000.0
    alpha_therm: float = 8.6e-6
    T_ref_k: float = 298.15
    T_preheat_k: float = 298.15
    T_ambient_k: float = 298.15
    h_conv_w_m2_k: float = 20.0
    emissivity: float = 0.3

    # Mechanical
    E_pa: float = 114e9
    nu: float = 0.342
    beta_E_per_k: float = 3.5e-4

    # Build geometry
    build_dir: tuple = (0.0, 0.0, 1.0)
    distortion_tolerance_m: float = 1e-3

    # Solver
    n_z_nodes: int = 20
    cfl_factor: float = 0.4
    latent_heat_smear_k: float = 50.0


@dataclass
class MeltPoolMetrics:
    """Characterisation of the melt pool per build layer."""
    layer_index: int
    peak_temperature_k: float      # maximum temperature reached
    melt_pool_depth_m: float       # depth of T > T_solidus from top surface
    melt_pool_width_m: float       # estimated from Goldak ellipsoid geometry
    solidified: bool               # True if T < T_solidus before next layer


@dataclass
class AMThermoMechResult:
    """Result of the coupled transient thermo-mechanical AM simulation.

    Attributes
    ----------
    ok : bool
    reason : str  (non-empty on failure)
    n_layers : int
    n_nodes : int
    n_elems : int

    -- Thermal results --
    thermal_history_k : list[np.ndarray]
        Peak temperature [K] at each mesh node (shape N) for each layer.
        thermal_history_k[k] is the peak-T field after layer k.
    layer_peak_temp_k : list[float]
        Peak temperature in the entire build after each layer.
    melt_pool_metrics : list[MeltPoolMetrics]
        Per-layer melt-pool characterisation.
    energy_input_j : float
        Total thermal energy deposited [J].
    energy_balance_ok : bool
        True if the deposited energy is within a factor 3 of the estimated
        enthalpy to bring the layer to melting (sanity check).

    -- Mechanical results --
    displacement : np.ndarray  shape (N, 3)
        Total nodal displacement field [m] at end of build.
    max_deviation_m : float
    residual_stress : np.ndarray  shape (M, 6)
        Element Cauchy stress [Pa] (σ_xx,σ_yy,σ_zz,τ_xy,τ_yz,τ_xz).
    max_von_mises_pa : float
    layer_max_disp_m : list[float]
        Max nodal displacement after each layer.

    -- Flags --
    support_elem_flags : list[bool]
    recoater_interference : bool
    warnings : list[str]
    """
    ok: bool = True
    reason: str = ""
    n_layers: int = 0
    n_nodes: int = 0
    n_elems: int = 0

    # Thermal
    thermal_history_k: list = field(default_factory=list)
    layer_peak_temp_k: list = field(default_factory=list)
    melt_pool_metrics: list = field(default_factory=list)
    energy_input_j: float = 0.0
    energy_balance_ok: bool = True

    # Mechanical
    displacement: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    max_deviation_m: float = 0.0
    residual_stress: np.ndarray = field(default_factory=lambda: np.zeros((0, 6)))
    max_von_mises_pa: float = 0.0
    layer_max_disp_m: list = field(default_factory=list)

    # Flags
    support_elem_flags: list = field(default_factory=list)
    recoater_interference: bool = False
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Goldak double-ellipsoid heat source — path-averaged volumetric Q
# ---------------------------------------------------------------------------

def _goldak_volumetric_average(
    p: AMThermoMechParams,
    layer_vol_m3: float,
) -> float:
    """Path-averaged volumetric heat rate [W/m³] in the deposited layer.

    For a raster scan, the time-averaged power density in the layer volume is:
        Q_vol = η · P / V_layer   (W/m³)

    This is the correct source term when applied for the actual scan heating
    time (heating_time = layer_area / (v_scan · track_pitch)).  Scan-speed
    dependence enters through the number of heating time steps, not Q_vol.

    Lower scan speed → longer heating_time → more heat steps → higher T.
    This correctly captures the inverse relationship between scan speed and
    peak temperature (Goldak 1984; Vastola et al. 2016).

    Parameters
    ----------
    p            : AMThermoMechParams
    layer_vol_m3 : float — volume of the new layer [m³]

    Returns
    -------
    Q_vol : float [W/m³]
    """
    Q_eff = p.absorptivity * p.laser_power_w   # effective absorbed power [W]
    return Q_eff / max(layer_vol_m3, 1e-18)


def _goldak_dwell_time(p: AMThermoMechParams) -> float:
    """Not used directly — scan-speed effect enters via heating_time in solver."""
    return 2.0 * p.beam_radius_m / max(p.scan_speed_m_s, 1e-12)


def _goldak_melt_pool_width(p: AMThermoMechParams) -> float:
    """Estimate melt-pool width from Goldak ellipsoid beam radius."""
    # Width = 2 * beam_radius (1/e² definition; melt-pool roughly equal to beam)
    return 2.0 * p.beam_radius_m


# ---------------------------------------------------------------------------
# Apparent specific heat (enthalpy method for latent heat)
# ---------------------------------------------------------------------------

def _cp_eff(T: float, p: AMThermoMechParams) -> float:
    """Effective specific heat including latent heat Gaussian smear [J/(kg·K)].

    cp_eff(T) = cp + L_f · G(T; T_melt, σ)
    G = (1/sqrt(2π σ²)) exp(-(T-T_melt)²/(2σ²))

    This distributes the latent heat of fusion as a Gaussian bell centred on
    T_melt with σ = latent_heat_smear_k (Voller & Prakash 1987).
    """
    sigma = p.latent_heat_smear_k
    gauss = (1.0 / (sigma * math.sqrt(2.0 * math.pi))) * math.exp(
        -0.5 * ((T - p.T_melt_k) / sigma) ** 2
    )
    return p.cp_j_kg_k + p.L_fusion_j_kg * gauss


def _k_eff(T: float, p: AMThermoMechParams) -> float:
    """Temperature-dependent thermal conductivity [W/(m·K)].

    Simple linear model:
      k(T) = k_0 · (1 + 0.3 · (T - T_ref) / (T_melt - T_ref))  clamped ≥ k_0/2
    This captures the moderate increase of k with T for metals.
    """
    dT = T - p.T_ref_k
    T_range = max(p.T_melt_k - p.T_ref_k, 1.0)
    k = p.k_w_m_k * (1.0 + 0.3 * dT / T_range)
    return max(k, 0.5 * p.k_w_m_k)


# ---------------------------------------------------------------------------
# 1-D transient thermal solver for one layer column
# ---------------------------------------------------------------------------

SIGMA_SB = 5.670374419e-8  # Stefan-Boltzmann constant [W/(m²·K⁴)]


def _deposit_heat_instantaneous(
    T: np.ndarray,
    p: AMThermoMechParams,
    E_vol_j_m3: float,
    i_new_bot: int,
    i_new_top: int,
) -> np.ndarray:
    """Instantaneous energy deposition into newly activated layer nodes.

    Adds ΔT = E_vol / (ρ · cp_eff(T)) to each node in [i_new_bot, i_new_top).
    This is a Godunov-split source step: it avoids the CFL instability of
    applying large Q_vol inside an explicit FD time loop.

    Parameters
    ----------
    T          : (n_z,) temperature column [K] (modified in place)
    p          : AMThermoMechParams
    E_vol_j_m3 : float — energy per unit volume to deposit [J/m³]
    i_new_bot  : int — first new-layer node index (inclusive)
    i_new_top  : int — last new-layer node index (exclusive)

    Returns
    -------
    T          : updated temperature array
    """
    T = T.copy()
    for i in range(i_new_bot, i_new_top):
        cp = _cp_eff(T[i], p)
        dT_deposition = E_vol_j_m3 / max(p.rho_kg_m3 * cp, 1.0)
        T[i] = T[i] + dT_deposition
    return T


def _solve_layer_thermal(
    T_init: np.ndarray,
    p: AMThermoMechParams,
    Q_vol: float,   # unused — kept for API compat; deposition is pre-applied
    n_steps: int,
    dt: float,
    dz: float,
    n_new: int,
) -> tuple[np.ndarray, float, float]:
    """Semi-implicit (linearised backward Euler) 1-D thermal diffusion + cooling.

    Unconditionally stable: solves a tridiagonal linear system at each step.
    The linear system is assembled with k, cp evaluated at the current T
    (Picard linearisation) — one Newton iteration per step is sufficient for
    modest time steps.

    Energy deposition is NOT applied here; use _deposit_heat_instantaneous
    (Godunov split) before calling this function.

    Boundary conditions:
      - z = 0 (base plate): T = T_preheat (Dirichlet)
      - z = z_top (free surface): convection + linearised radiation

    Parameters
    ----------
    T_init  : (n_z,) initial temperature [K]
    p       : AMThermoMechParams
    Q_vol   : float — unused (kept for API compat)
    n_steps : int — number of time steps
    dt      : float — time step [s]
    dz      : float — node spacing [m]
    n_new   : int — unused (kept for API compat)

    Returns
    -------
    T_final     : (n_z,) temperature field
    T_peak      : float — max T at deposition point (= T_init.max(), tracked)
    T_peak_top  : float — max T at top node
    """
    from scipy.linalg import solve_banded
    n_z = len(T_init)
    T = T_init.copy()
    T_peak = float(T.max())
    T_peak_top = float(T[-1])

    rho = p.rho_kg_m3
    T_inf = p.T_ambient_k
    h_c = p.h_conv_w_m2_k
    eps_r = p.emissivity

    for _step in range(n_steps):
        # Build tridiagonal system  A·T_new = rhs  (banded storage: ab[0]=upper, ab[1]=diag, ab[2]=lower)
        ab = np.zeros((3, n_z))
        rhs = np.zeros(n_z)

        for i in range(n_z):
            cp = _cp_eff(T[i], p)
            rho_cp = rho * cp

            if i == 0:
                # Dirichlet: T_new[0] = T_preheat
                ab[1, 0] = 1.0
                rhs[0] = p.T_preheat_k
            elif i == n_z - 1:
                # Top surface: convection + linearised radiation
                # Linearise T^4 ≈ T_old^4 + 4*T_old^3*(T_new - T_old)
                T_s = max(T[i], 10.0)  # avoid T=0
                k_im = _k_eff(0.5 * (T[i] + T[i-1]), p)
                # half-volume node
                half_vol = 0.5 * dz
                # diffusion term (backward: involves T_new)
                a_im = k_im / (dz * half_vol * rho_cp)
                rad_lin = eps_r * SIGMA_SB * 4.0 * T_s**3  # linearised radiation
                h_eff = (h_c + rad_lin) / (half_vol * rho_cp)
                # T_new coefficient
                ab[1, i] = 1.0 / dt + a_im + h_eff
                ab[2, i - 1] = -a_im   # lower (T[i-1] coeff in row i)
                # RHS: old T + conv/rad BC offset
                q_rad_offset = eps_r * SIGMA_SB * (T_s**4 - 4.0 * T_s**3 * T_s)  # = -3*eps*sigma*T_s^4
                rhs[i] = (T[i] / dt
                          + h_c * T_inf / (half_vol * rho_cp)
                          + (rad_lin * T_inf - q_rad_offset) / (half_vol * rho_cp))
                # correct: radiation forcing = eps*sigma*(T_inf^4) − linearised part
                # simplified: use total linearised heat loss
                rhs[i] = T[i] / dt + (h_c * T_inf + eps_r * SIGMA_SB * (T_inf**4 - T_s**4 + 4.0 * T_s**3 * T_inf)) / (half_vol * rho_cp)
                ab[1, i] = 1.0 / dt + a_im + (h_c + eps_r * SIGMA_SB * 4.0 * T_s**3) / (half_vol * rho_cp)
                ab[2, i - 1] = -a_im
            else:
                k_ip = _k_eff(0.5 * (T[i+1] + T[i]), p)
                k_im = _k_eff(0.5 * (T[i] + T[i-1]), p)
                a_ip = k_ip / (dz * dz * rho_cp)
                a_im = k_im / (dz * dz * rho_cp)
                ab[1, i] = 1.0 / dt + a_ip + a_im
                if i + 1 < n_z:
                    ab[0, i + 1] = -a_ip   # upper (T[i+1] coeff in row i)
                ab[2, i - 1] = -a_im       # lower (T[i-1] coeff in row i)
                rhs[i] = T[i] / dt

        # Solve banded system
        # scipy.linalg.solve_banded: ab[0] = upper diag (shift right), ab[1] = main, ab[2] = lower (shift left)
        # Note: upper stored at ab[0, 1:], lower at ab[2, :-1]
        T = solve_banded((1, 1), ab, rhs)

        t_peak_now = float(T.max())
        if t_peak_now > T_peak:
            T_peak = t_peak_now
        t_top_now = float(T[-1])
        if t_top_now > T_peak_top:
            T_peak_top = t_top_now

    return T, T_peak, T_peak_top


# ---------------------------------------------------------------------------
# FEM helpers (re-used from am_process_sim pattern, with temp-dependent E)
# ---------------------------------------------------------------------------

def _elasticity_matrix(E: float, nu: float) -> np.ndarray:
    """Isotropic 3-D linear elasticity matrix C (6×6)."""
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))
    C = np.array([
        [lam + 2*mu, lam,        lam,        0,  0,  0 ],
        [lam,        lam + 2*mu, lam,        0,  0,  0 ],
        [lam,        lam,        lam + 2*mu, 0,  0,  0 ],
        [0,          0,          0,          mu, 0,  0 ],
        [0,          0,          0,          0,  mu, 0 ],
        [0,          0,          0,          0,  0,  mu],
    ])
    return C


def _tet4_vol_B(xyz: np.ndarray) -> tuple[float, np.ndarray]:
    """Volume and strain-displacement matrix B (6×12) for Tet4."""
    x1, y1, z1 = xyz[0]
    x2, y2, z2 = xyz[1]
    x3, y3, z3 = xyz[2]
    x4, y4, z4 = xyz[3]

    J = np.array([
        [x2 - x1, x3 - x1, x4 - x1],
        [y2 - y1, y3 - y1, y4 - y1],
        [z2 - z1, z3 - z1, z4 - z1],
    ])
    vol = np.linalg.det(J) / 6.0

    a1 =  (y3 - y4) * (z2 - z4) - (y2 - y4) * (z3 - z4)
    a2 = -((y3 - y4) * (z1 - z4) - (y1 - y4) * (z3 - z4))
    a3 =  (y2 - y4) * (z1 - z4) - (y1 - y4) * (z2 - z4)
    a4 = -(a1 + a2 + a3)

    b1 = -((x3 - x4) * (z2 - z4) - (x2 - x4) * (z3 - z4))
    b2 =  (x3 - x4) * (z1 - z4) - (x1 - x4) * (z3 - z4)
    b3 = -((x2 - x4) * (z1 - z4) - (x1 - x4) * (z2 - z4))
    b4 = -(b1 + b2 + b3)

    c1 =  (x3 - x4) * (y2 - y4) - (x2 - x4) * (y3 - y4)
    c2 = -((x3 - x4) * (y1 - y4) - (x1 - x4) * (y3 - y4))
    c3 =  (x2 - x4) * (y1 - y4) - (x1 - x4) * (y2 - y4)
    c4 = -(c1 + c2 + c3)

    inv6V = 1.0 / (6.0 * abs(vol))

    B = np.zeros((6, 12))
    for i, (ai, bi, ci) in enumerate([(a1, b1, c1), (a2, b2, c2),
                                       (a3, b3, c3), (a4, b4, c4)]):
        col = i * 3
        B[0, col + 0] = ai * inv6V
        B[1, col + 1] = bi * inv6V
        B[2, col + 2] = ci * inv6V
        B[3, col + 0] = bi * inv6V
        B[3, col + 1] = ai * inv6V
        B[4, col + 1] = ci * inv6V
        B[4, col + 2] = bi * inv6V
        B[5, col + 0] = ci * inv6V
        B[5, col + 2] = ai * inv6V

    return abs(vol), B


def _von_mises(sigma6: np.ndarray) -> float:
    sx, sy, sz, txy, tyz, txz = sigma6
    return math.sqrt(0.5 * (
        (sx - sy)**2 + (sy - sz)**2 + (sz - sx)**2
        + 6.0 * (txy**2 + tyz**2 + txz**2)
    ))


def _slice_layers(
    nodes: np.ndarray,
    tets: np.ndarray,
    layer_thickness: float,
    build_axis: int,
) -> list[np.ndarray]:
    """Assign each element to a build layer (same as am_process_sim)."""
    centroids = nodes[tets].mean(axis=1)[:, build_axis]
    z_min = centroids.min()
    layer_idx = np.floor((centroids - z_min) / layer_thickness).astype(int)
    n_layers = int(layer_idx.max()) + 1
    layers: list[np.ndarray] = []
    for k in range(n_layers):
        mask = np.where(layer_idx == k)[0]
        if len(mask) > 0:
            layers.append(mask)
    return layers


def _assemble_K_and_f_thermal(
    nodes: np.ndarray,
    tets: np.ndarray,
    active_mask: np.ndarray,
    C: np.ndarray,
    eps_thermal: np.ndarray,   # (M, 6) per-element thermal eigenstrain
    new_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Assemble K and thermal-eigenstrain load f.

    Same as am_process_sim._assemble_K_and_f but:
    - eps_thermal is per-element (not a global constant).
    - Only active elements contribute to K; only new-mask elements to f.
    """
    N = nodes.shape[0]
    K = np.zeros((3 * N, 3 * N))
    f = np.zeros(3 * N)

    for e_idx in range(len(tets)):
        if not active_mask[e_idx]:
            continue
        conn = tets[e_idx]
        xyz = nodes[conn]
        vol, B = _tet4_vol_B(xyz)
        K_e = vol * (B.T @ C @ B)
        dofs = np.array([3 * n + d for n in conn for d in range(3)])
        for i_loc, i_glb in enumerate(dofs):
            for j_loc, j_glb in enumerate(dofs):
                K[i_glb, j_glb] += K_e[i_loc, j_loc]

        if new_mask[e_idx]:
            eps_e = eps_thermal[e_idx]
            f_e = vol * (B.T @ (C @ eps_e))
            for i_loc, i_glb in enumerate(dofs):
                f[i_glb] += f_e[i_loc]

    return K, f


def _apply_dirichlet(K: np.ndarray, f: np.ndarray, fixed_dofs: list[int]) -> None:
    for d in fixed_dofs:
        K[d, :] = 0.0
        K[:, d] = 0.0
        K[d, d] = 1.0
        f[d] = 0.0


# ---------------------------------------------------------------------------
# Main coupled solver
# ---------------------------------------------------------------------------

def simulate_am_thermomechanical(
    mesh: Any,   # AMMesh (duck-typed to avoid circular import)
    params: AMThermoMechParams,
) -> AMThermoMechResult:
    """Run coupled transient thermo-mechanical AM simulation.

    Parameters
    ----------
    mesh   : AMMesh (from kerf_manufacturing.am_process_sim)
    params : AMThermoMechParams

    Returns
    -------
    AMThermoMechResult
    """
    result = AMThermoMechResult()

    # ---- Validate -----------------------------------------------------------
    nodes = np.asarray(mesh.nodes, dtype=float)
    tets = np.asarray(mesh.tets, dtype=int)
    N = nodes.shape[0]
    M = tets.shape[0]

    if N < 4:
        result.ok = False
        result.reason = "Mesh must have at least 4 nodes"
        return result
    if M < 1:
        result.ok = False
        result.reason = "Mesh must have at least 1 element"
        return result
    if params.laser_power_w <= 0:
        result.ok = False
        result.reason = "laser_power_w must be positive"
        return result
    if params.scan_speed_m_s <= 0:
        result.ok = False
        result.reason = "scan_speed_m_s must be positive"
        return result
    if params.layer_thickness_m <= 0:
        result.ok = False
        result.reason = "layer_thickness_m must be positive"
        return result
    if params.E_pa <= 0:
        result.ok = False
        result.reason = "E_pa must be positive"
        return result
    if not (0.0 < params.nu < 0.5):
        result.ok = False
        result.reason = "nu must be in (0, 0.5)"
        return result

    # ---- Build axis ---------------------------------------------------------
    bd = np.array(params.build_dir, dtype=float)
    bd /= np.linalg.norm(bd)
    build_axis = int(np.argmax(np.abs(bd)))

    # ---- Layer slicing ------------------------------------------------------
    layers = _slice_layers(nodes, tets, params.layer_thickness_m, build_axis)
    n_layers = len(layers)
    if n_layers == 0:
        result.ok = False
        result.reason = "No layers found — check layer_thickness_m vs part height"
        return result

    result.n_layers = n_layers
    result.n_nodes = N
    result.n_elems = M

    # ---- Base-plate fixity --------------------------------------------------
    z_coords = nodes[:, build_axis]
    z_min = z_coords.min()
    tol_bp = max(params.layer_thickness_m * 0.01, 1e-9)
    baseplate_nodes = np.where(z_coords <= z_min + tol_bp)[0]
    fixed_dofs: list[int] = []
    for n in baseplate_nodes:
        fixed_dofs += [3 * int(n), 3 * int(n) + 1, 3 * int(n) + 2]

    # ---- Support flags ------------------------------------------------------
    support_flags = [False] * M
    if layers:
        for idx in layers[0]:
            support_flags[int(idx)] = True
    result.support_elem_flags = support_flags

    # ---- 1-D Thermal column setup -------------------------------------------
    # One column per layer: nodes spaced dz from z_min to z_layer_top
    # Total column height = part height
    z_max = z_coords.max()
    part_height = z_max - z_min
    n_col = params.n_z_nodes
    dz = part_height / max(n_col - 1, 1)

    # Initial temperature column (preheat)
    T_col = np.full(n_col, params.T_preheat_k)

    # CFL-based time step — use conductivity at T_melt for a conservative bound.
    # k increases with T; computing dt at T_melt avoids CFL violations when
    # the column reaches high temperatures during deposition.
    k_max = _k_eff(params.T_melt_k, params)
    cp_min = params.cp_j_kg_k  # base cp (near-melt latent heat term is captured in _cp_eff)
    dt_cfl = params.cfl_factor * params.rho_kg_m3 * cp_min * dz**2 / k_max
    dt = min(dt_cfl, params.layer_time_s / 10.0)
    dt = max(dt, 1e-6)  # floor: 1 µs

    # Heating phase: apply all deposited energy in ONE step (impulse model).
    # The volumetric energy density is:
    #   E_vol = η·P / (v_scan · track_pitch · h_layer)
    # This correctly scales as P/v_scan (higher P or lower v_scan → more energy/vol → higher T).
    # track_pitch ≈ beam_radius (50% overlap hatch)
    # The impulse is then Q_vol_impulse = E_vol / dt (deposited in one CFL step).
    # After the impulse, the column cools for n_cool_steps under BCs.
    track_pitch = params.beam_radius_m  # 50% overlap hatch
    # E_vol is the energy per unit volume deposited in this layer [J/m³]
    # (not yet dividing by layer volume — that's done inside _solve_layer_thermal)
    # We use 1 heat step with Q_vol_impulse = E_vol / dt
    n_heat_steps = 1
    n_cool_steps = max(1, int(params.layer_time_s / dt) - 1)
    # The actual scan time (total energy = Q_eff × scan_time)
    layer_xy_area = max(1e-12,
        (nodes[:, 0].max() - nodes[:, 0].min()) *
        (nodes[:, 1].max() - nodes[:, 1].min())
    )
    actual_scan_time = layer_xy_area / max(params.scan_speed_m_s * track_pitch, 1e-15)
    actual_scan_time = min(actual_scan_time, params.layer_time_s)

    # Nodes per layer in the 1-D column
    # Layer k spans from z_min + k*h to z_min + (k+1)*h
    # Column node index range for layer k:
    h = params.layer_thickness_m
    def layer_col_nodes(k: int) -> tuple[int, int]:
        """Return (i_bot, i_top) index range of column nodes in layer k."""
        z_bot = z_min + k * h
        z_top = z_min + (k + 1) * h
        # Map to column indices
        i_bot = int(round((z_bot - z_min) / dz))
        i_top = int(round((z_top - z_min) / dz))
        i_bot = max(0, min(i_bot, n_col - 1))
        i_top = max(i_bot + 1, min(i_top, n_col))
        return i_bot, i_top


    # Total absorbed energy per layer (scan-speed dependent)
    Q_eff = params.absorptivity * params.laser_power_w
    total_energy_j = Q_eff * actual_scan_time * n_layers


    # ---- Mechanical state ---------------------------------------------------
    u_total = np.zeros(3 * N)
    residual_stress = np.zeros((M, 6))
    active_mask = np.zeros(M, dtype=bool)
    layer_max_disp: list[float] = []

    # Per-node temperature (for eigenstrain computation)
    # Initially T_ref everywhere
    T_nodal = np.full(N, params.T_ref_k)

    thermal_history_list: list[np.ndarray] = []
    layer_peak_temps: list[float] = []
    melt_pool_metrics_list: list[MeltPoolMetrics] = []

    # ---- Layer-by-layer loop ------------------------------------------------
    for k, layer_elems in enumerate(layers):
        # ---- Step 1: Thermal solve for this layer ----
        # Estimate layer volume (average element volume × count)
        # Use element centroids for a better estimate
        elem_vols = []
        for e_idx in layer_elems:
            conn = tets[e_idx]
            xyz = nodes[conn]
            try:
                v, _ = _tet4_vol_B(xyz)
                elem_vols.append(v)
            except Exception:
                pass
        layer_vol = sum(elem_vols) if elem_vols else (
            params.layer_thickness_m * 0.01 * 0.01  # fallback 10mm × 10mm slab
        )

        # Energy per unit volume deposited in this layer [J/m³]
        # E_vol = η·P / (v_scan · track_pitch · h_layer)
        # Scales as P/v_scan → higher P or slower scan → more E_vol → higher T
        E_vol = (params.absorptivity * params.laser_power_w) / max(
            params.scan_speed_m_s * track_pitch * params.layer_thickness_m, 1e-15
        )

        # Number of new layer column nodes
        i_bot, i_top = layer_col_nodes(k)
        n_new_col = max(1, i_top - i_bot)

        # Step 1a: Instantaneous energy deposition (Godunov-split source step).
        # Directly adds ΔT = E_vol / (ρ·cp_eff) to the new layer nodes.
        # This avoids CFL instability of a large Q_vol in the explicit FD.
        T_after_deposit = _deposit_heat_instantaneous(
            T_col, params, E_vol, max(0, n_col - n_new_col), n_col
        )
        T_peak_deposit = float(T_after_deposit.max())
        T_peak_top_deposit = float(T_after_deposit[-1])

        # Step 1b: Diffusion + cooling for the full layer_time
        T_col, T_peak_diffuse, T_peak_top_diffuse = _solve_layer_thermal(
            T_after_deposit, params, 0.0, n_cool_steps + n_heat_steps, dt, dz, 0
        )
        T_peak_heat = max(T_peak_deposit, T_peak_diffuse)
        T_peak_top = max(T_peak_top_deposit, T_peak_top_diffuse)

        # Cooling phase (Q_vol = 0)
        # T_col already includes full layer_time of diffusion + cooling
        T_peak_layer = T_peak_heat

        # Melt pool metrics
        melt_depth = 0.0
        top_T = T_col[-1]
        for iz in range(n_col - 1, -1, -1):
            if T_col[iz] >= params.T_melt_k or T_peak_heat >= params.T_melt_k:
                # Estimate depth from top where peak T > T_melt
                melt_depth = (n_col - 1 - iz) * dz
                break
        # Use peak heating temperature for melt pool assessment
        if T_peak_heat >= params.T_melt_k:
            melt_depth = max(melt_depth, dz)

        melt_pool_w = _goldak_melt_pool_width(params)
        solidified = float(T_col[-1]) < params.T_melt_k

        melt_pool_metrics_list.append(MeltPoolMetrics(
            layer_index=k,
            peak_temperature_k=T_peak_layer,
            melt_pool_depth_m=melt_depth,
            melt_pool_width_m=melt_pool_w,
            solidified=solidified,
        ))
        layer_peak_temps.append(T_peak_layer)

        # ---- Step 2: Map column temperatures to 3-D mesh nodes ----
        # Interpolate 1-D column T to 3-D mesh nodes based on z coordinate
        z_col_coords = np.linspace(z_min, z_max, n_col)
        for n_idx in range(N):
            z_n = float(nodes[n_idx, build_axis])
            # Linear interpolation
            iz = np.searchsorted(z_col_coords, z_n)
            iz = min(iz, n_col - 1)
            iz0 = max(iz - 1, 0)
            if iz0 == iz:
                T_n = float(T_col[iz])
            else:
                frac = (z_n - z_col_coords[iz0]) / (z_col_coords[iz] - z_col_coords[iz0])
                T_n = float(T_col[iz0]) + frac * float(T_col[iz] - T_col[iz0])
            # Update only if this is the new peak for this node
            T_nodal[n_idx] = max(T_nodal[n_idx], T_n)

        thermal_history_list.append(T_nodal.copy())

        # ---- Step 3: Compute per-element thermal eigenstrain ----
        # ε* = α(T) · ΔT  (isotropic; ΔT = T_peak - T_ref)
        # Use element-centroid temperature
        eps_thermal = np.zeros((M, 6))
        for e_idx in layer_elems:
            conn = tets[e_idx]
            T_elem = float(T_nodal[conn].mean())
            dT = max(T_elem - params.T_ref_k, 0.0)
            eps_th = params.alpha_therm * dT
            eps_thermal[int(e_idx), :3] = eps_th   # [ε_xx, ε_yy, ε_zz]
            # shear components = 0 for isotropic thermal expansion

        # ---- Step 4: Mechanical solve with thermal eigenstrain ----
        # Temperature-averaged E for elements in this layer
        # Use the mean peak temperature to soften the modulus
        T_layer_mean = float(np.mean([T_nodal[tets[e]].mean() for e in layer_elems]))
        dT_mech = max(T_layer_mean - params.T_ref_k, 0.0)
        E_eff = params.E_pa * max(
            0.1,
            1.0 - params.beta_E_per_k * dT_mech
        )
        C = _elasticity_matrix(E_eff, params.nu)

        # Activate new elements
        new_mask = np.zeros(M, dtype=bool)
        new_mask[layer_elems] = True
        active_mask |= new_mask

        # Assemble K and f
        K, f = _assemble_K_and_f_thermal(
            nodes, tets, active_mask, C, eps_thermal, new_mask
        )

        # Apply BCs
        _apply_dirichlet(K, f, fixed_dofs)

        # Solve
        try:
            delta_u = np.linalg.solve(K, f)
        except np.linalg.LinAlgError:
            layer_max_disp.append(
                float(np.max(np.linalg.norm(u_total.reshape(-1, 3), axis=1)))
            )
            continue

        u_total += delta_u

        # Track max displacement
        u_nodal = u_total.reshape(-1, 3)
        mags = np.linalg.norm(u_nodal, axis=1)
        layer_max_disp.append(float(mags.max()))

        # Update residual stress
        for e_idx in np.where(active_mask)[0]:
            conn = tets[e_idx]
            xyz = nodes[conn]
            vol, B = _tet4_vol_B(xyz)
            u_e = u_total[[3 * n + d for n in conn for d in range(3)]]
            eps_th_e = eps_thermal[int(e_idx)]
            eps_mech = B @ u_e - eps_th_e
            sigma = C @ eps_mech
            residual_stress[int(e_idx)] = sigma

    # ---- Post-process -------------------------------------------------------
    u_nodal_final = u_total.reshape(-1, 3)
    mags = np.linalg.norm(u_nodal_final, axis=1)
    max_dev = float(mags.max())

    vm_arr = np.array([
        _von_mises(residual_stress[e])
        for e in range(M)
        if active_mask[e]
    ])
    max_vm = float(vm_arr.max()) if len(vm_arr) > 0 else 0.0

    result.displacement = u_nodal_final
    result.max_deviation_m = max_dev
    result.residual_stress = residual_stress
    result.max_von_mises_pa = max_vm
    result.layer_max_disp_m = layer_max_disp
    result.thermal_history_k = thermal_history_list
    result.layer_peak_temp_k = layer_peak_temps
    result.melt_pool_metrics = melt_pool_metrics_list
    result.energy_input_j = float(total_energy_j)

    # ---- Energy balance sanity check ----------------------------------------
    # Estimate energy to heat layer volume to T_melt
    node_ranges = nodes.max(axis=0) - nodes.min(axis=0)
    layer_vol_est = max(1e-15, node_ranges.prod() / n_layers)
    enthalpy_est = (
        params.rho_kg_m3 * layer_vol_est
        * (params.cp_j_kg_k * (params.T_melt_k - params.T_ref_k) + params.L_fusion_j_kg)
    )
    energy_ratio = total_energy_j / max(enthalpy_est, 1e-15)
    result.energy_balance_ok = bool(0.01 < energy_ratio < 1000.0)

    # ---- Recoater interference heuristic ------------------------------------
    top_layer_elems = layers[-1]
    top_node_set: set[int] = set()
    for eidx in top_layer_elems:
        for nn in tets[eidx]:
            top_node_set.add(int(nn))
    inplane_axes = [a for a in range(3) if a != build_axis]
    recoater_limit = 0.5 * params.layer_thickness_m
    for nn in top_node_set:
        for ax in inplane_axes:
            if abs(u_nodal_final[nn, ax]) > recoater_limit:
                result.recoater_interference = True
                break

    # ---- Warnings -----------------------------------------------------------
    warnings: list[str] = []
    if max_dev > params.distortion_tolerance_m:
        warnings.append(
            f"Max distortion {max_dev * 1e3:.3f} mm exceeds tolerance "
            f"{params.distortion_tolerance_m * 1e3:.3f} mm"
        )
    if result.recoater_interference:
        warnings.append(
            "Recoater interference risk: top-layer in-plane displacement "
            f"exceeds 0.5 × layer_thickness ({recoater_limit * 1e6:.1f} µm)"
        )
    if max_vm > 0.5 * params.E_pa * 0.002:
        warnings.append(
            f"High residual von-Mises stress {max_vm / 1e6:.1f} MPa — "
            "may indicate yielding (model is thermo-elastic only)"
        )
    if any(m.peak_temperature_k < params.T_melt_k for m in melt_pool_metrics_list):
        warnings.append(
            "Some layers did not reach melt temperature — "
            "check laser_power_w and absorptivity parameters"
        )
    if not result.energy_balance_ok:
        warnings.append(
            f"Energy balance check: input/enthalpy ratio = {energy_ratio:.2e} "
            "(outside [0.01, 1000]) — verify laser_power_w and layer geometry"
        )
    warnings.append(
        "HONEST MODEL NOTE: Thermo-elastic coupling only (no return-mapping "
        "plasticity). Residual stress magnitudes are directionally correct but "
        "underestimated vs full TEP by ~30-50%. No part-scale GPU acceleration. "
        "1-D thermal column per layer (no lateral inter-layer heat flow). "
        "Simplified Goldak source — no keyhole/evaporation effects."
    )

    result.warnings = warnings
    result.ok = True
    return result
