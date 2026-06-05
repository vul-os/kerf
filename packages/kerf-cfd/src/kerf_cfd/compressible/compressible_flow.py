"""
Compressible Flow — density-based FVM with Roe approximate Riemann solver.

Implements:
  - CompressibleState dataclass (ρ, ρu, ρE conserved variables)
  - roe_flux:               Roe (1981) approximate Riemann solver
  - step_compressible:      One FVM pseudo-time step (Euler / NS)
  - normal_shock_relations: Rankine-Hugoniot jump conditions
  - isentropic_relations:   Isentropic flow relations (stagnation properties)
  - oblique_shock_relations: Oblique shock β–θ–M relations (Anderson 2003 §4)
  - prandtl_meyer_expansion: Prandtl-Meyer expansion fan angle (Anderson §9)

HONEST FLAG: Design-exploration accuracy only.  Simplified inviscid + first-order
viscous terms.  Production compressible CFD uses density-based solvers in
OpenFOAM (rhoSimpleFoam/rhoCentralFoam), ANSYS Fluent, or Star-CCM+.

References
----------
Roe, P.L. (1981). "Approximate Riemann Solvers, Parameter Vectors and Difference
  Schemes." Journal of Computational Physics, 43, 357–372.
Anderson, J.D. (2003). "Modern Compressible Flow." 3rd ed., McGraw-Hill.
Toro, E.F. (2009). "Riemann Solvers and Numerical Methods for Fluid Dynamics."
  3rd ed., Springer.
Sutherland, W. (1893). "The viscosity of gases and molecular force." Phil. Mag. 36.

# Wave 12B: CFD advanced physics (compressible/conjugate-HT/multiphase/marine)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Gas constants
_R_AIR = 287.058      # J/(kg·K)  — specific gas constant for air
_T_REF = 273.15       # K         — Sutherland reference temperature
_MU_REF = 1.716e-5    # Pa·s      — Sutherland reference viscosity
_S_C = 110.4          # K         — Sutherland constant C


# ---------------------------------------------------------------------------
# CompressibleState
# ---------------------------------------------------------------------------

@dataclass
class CompressibleState:
    """
    Conserved-variable state for compressible Euler / Navier-Stokes.

    Stores the standard 5-variable (3-D) or 4-variable (2-D) conserved vector:
      Q = [ρ, ρu, ρv, (ρw), ρE]

    Parameters
    ----------
    rho : (Ncells,) density [kg/m³]
    rho_u : (Ncells, ndim) momentum [kg/(m²·s)]
    rho_E : (Ncells,) total energy per unit volume [J/m³]
    gamma : heat-capacity ratio (1.4 for diatomic air)

    References
    ----------
    Anderson (2003) §2.4 — conserved variable form of governing equations.
    """
    rho: np.ndarray          # (Ncells,)
    rho_u: np.ndarray        # (Ncells, ndim)
    rho_E: np.ndarray        # (Ncells,)
    gamma: float = 1.4

    def __post_init__(self):
        self.rho = np.asarray(self.rho, dtype=float)
        self.rho_u = np.asarray(self.rho_u, dtype=float)
        self.rho_E = np.asarray(self.rho_E, dtype=float)
        if self.rho_u.ndim == 1:
            self.rho_u = self.rho_u[:, None]

    # ------------------------------------------------------------------
    # Derived quantities
    # ------------------------------------------------------------------

    def velocity(self) -> np.ndarray:
        """u = ρu / ρ  →  (Ncells, ndim)."""
        return self.rho_u / self.rho[:, None]

    def pressure(self) -> np.ndarray:
        """
        p = (γ-1)·(ρE - 0.5·ρ·|u|²)

        Calorically perfect gas equation of state.
        Anderson (2003) Eq. 2.65.
        """
        ke = 0.5 * np.sum(self.rho_u ** 2, axis=1) / self.rho   # kinetic energy density
        return (self.gamma - 1.0) * (self.rho_E - ke)

    def temperature(self) -> np.ndarray:
        """
        T = p / (R·ρ)

        Ideal gas law; R = 287 J/(kg·K) for air.
        Anderson (2003) Eq. 1.9.
        """
        return self.pressure() / (_R_AIR * self.rho)

    def sound_speed(self) -> np.ndarray:
        """c = sqrt(γ·p/ρ)."""
        return np.sqrt(self.gamma * self.pressure() / self.rho)

    def mach_number(self) -> np.ndarray:
        """
        M = |u| / c

        Returns per-cell Mach number (dimensionless).
        At rest (u=0) returns 0.
        """
        speed = np.linalg.norm(self.velocity(), axis=1)
        return speed / self.sound_speed()

    def total_enthalpy(self) -> np.ndarray:
        """H = (ρE + p) / ρ  — specific total enthalpy [J/kg]."""
        return (self.rho_E + self.pressure()) / self.rho


# ---------------------------------------------------------------------------
# Roe flux
# ---------------------------------------------------------------------------

def roe_flux(
    state_L: CompressibleState,
    state_R: CompressibleState,
    face_normal: np.ndarray,
) -> np.ndarray:
    """
    Roe approximate Riemann solver — returns numerical flux across a face.

    Implements the Roe-averaged state and characteristic decomposition for
    the compressible Euler equations.  Each call handles a single face with
    left (L) and right (R) states that are length-1 CompressibleState objects.

    Parameters
    ----------
    state_L, state_R : CompressibleState with rho/rho_u/rho_E of shape (1,) / (1, ndim)
    face_normal : (ndim,) unit outward normal of the face

    Returns
    -------
    flux : (ndim+2,) flux vector  [F_rho, F_rho_u_x, F_rho_u_y, (F_rho_u_z), F_rho_E]

    References
    ----------
    Roe, P.L. (1981). J. Comput. Phys. 43, 357–372.
    Toro, E.F. (2009). §11.2 — Roe's scheme.
    """
    n = np.asarray(face_normal, dtype=float)
    n_norm = np.linalg.norm(n)
    if n_norm < 1e-14:
        ndim = state_L.rho_u.shape[1]
        return np.zeros(ndim + 2)
    n_hat = n / n_norm

    ndim = n_hat.shape[0]

    # Scalar extraction (single cell)
    rho_L = float(state_L.rho[0])
    rho_R = float(state_R.rho[0])
    u_L = state_L.velocity()[0]        # (ndim,)
    u_R = state_R.velocity()[0]
    p_L = float(state_L.pressure()[0])
    p_R = float(state_R.pressure()[0])
    H_L = float(state_L.total_enthalpy()[0])
    H_R = float(state_R.total_enthalpy()[0])

    # Roe-averaged quantities  (Roe 1981, §3)
    sqrt_rho_L = np.sqrt(rho_L)
    sqrt_rho_R = np.sqrt(rho_R)
    denom = sqrt_rho_L + sqrt_rho_R

    u_roe = (sqrt_rho_L * u_L + sqrt_rho_R * u_R) / denom
    H_roe = (sqrt_rho_L * H_L + sqrt_rho_R * H_R) / denom

    u_n_roe = float(np.dot(u_roe, n_hat))
    u_sq_roe = float(np.dot(u_roe, u_roe))

    c2_roe = (state_L.gamma - 1.0) * (H_roe - 0.5 * u_sq_roe)
    # Guard against non-physical state (very low pressure)
    c2_roe = max(c2_roe, 1e-6)
    c_roe = np.sqrt(c2_roe)

    # Physical fluxes on each side
    def _euler_flux_normal(rho, u, p, rho_E, n_):
        un = float(np.dot(u, n_))
        f_rho = rho * un
        f_rho_u = rho * un * u + p * n_
        f_rho_E = (rho_E + p) * un
        return np.concatenate([[f_rho], f_rho_u, [f_rho_E]])

    f_L = _euler_flux_normal(rho_L, u_L, p_L, float(state_L.rho_E[0]), n_hat)
    f_R = _euler_flux_normal(rho_R, u_R, p_R, float(state_R.rho_E[0]), n_hat)

    # Jump in conserved variables
    d_rho = rho_R - rho_L
    d_rho_u = state_R.rho_u[0] - state_L.rho_u[0]   # (ndim,)
    d_rho_E = float(state_R.rho_E[0]) - float(state_L.rho_E[0])

    u_n_L = float(np.dot(u_L, n_hat))
    u_n_R = float(np.dot(u_R, n_hat))
    d_p = p_R - p_L
    d_un = u_n_R - u_n_L

    # Roe eigenvalue (wave speed) magnitudes — entropy fix (Harten 1983)
    def _entropy_fix(lam, eps=0.1 * c_roe):
        return np.where(np.abs(lam) < eps, (lam ** 2 + eps ** 2) / (2.0 * eps), np.abs(lam))

    lam1 = _entropy_fix(np.array([u_n_roe - c_roe]))[0]
    lam2 = _entropy_fix(np.array([u_n_roe]))[0]
    lam3 = _entropy_fix(np.array([u_n_roe + c_roe]))[0]

    # Characteristic wave strengths (Roe 1981 §3, for 3-D see Toro §11.2)
    alpha1 = 0.5 * (d_p - state_L.gamma * np.sqrt(max(rho_L * rho_R, 1e-14)) * c_roe * d_un) / (c2_roe)
    # Equivalent:  alpha1 = (dp - rho_roe*c_roe*dun) / (2*c²)
    # but using simpler form that reduces to zero on uniform states
    rho_roe = sqrt_rho_L * sqrt_rho_R
    alpha1 = (d_p - rho_roe * c_roe * d_un) / (2.0 * c2_roe)
    alpha3 = (d_p + rho_roe * c_roe * d_un) / (2.0 * c2_roe)
    alpha2_rho = d_rho - (alpha1 + alpha3)   # density wave

    # Dissipation: sum |λ_k| * α_k * r_k  (eigenvectors r_k)
    # Entropy/shear waves (λ = u_n):
    diss_rho = lam2 * alpha2_rho
    diss_rho_u_n = lam2 * (alpha2_rho * u_n_roe)
    diss_rho_E = lam2 * (alpha2_rho * (0.5 * u_sq_roe))

    # Acoustic waves (λ = u_n ± c):
    diss_rho += lam1 * alpha1 + lam3 * alpha3
    diss_rho_u_n += lam1 * alpha1 * (u_n_roe - c_roe) + lam3 * alpha3 * (u_n_roe + c_roe)
    diss_rho_E += (lam1 * alpha1 * (H_roe - u_n_roe * c_roe)
                   + lam3 * alpha3 * (H_roe + u_n_roe * c_roe))

    # Tangential velocity component dissipation
    u_t_L = u_L - u_n_L * n_hat
    u_t_R = u_R - u_n_R * n_hat
    d_rho_u_t = rho_R * u_t_R - rho_L * u_t_L  # tangential momentum jump

    # Assemble dissipation vector
    diss_momentum = diss_rho_u_n * n_hat + lam2 * d_rho_u_t
    diss = np.concatenate([[diss_rho], diss_momentum, [diss_rho_E]])

    flux = 0.5 * (f_L + f_R) - 0.5 * diss
    # Scale back by face area (caller multiplies by |n| if unnormalized)
    return flux * n_norm


# ---------------------------------------------------------------------------
# Viscosity — Sutherland's law
# ---------------------------------------------------------------------------

def _sutherland_viscosity(T: np.ndarray) -> np.ndarray:
    """
    Dynamic viscosity via Sutherland's law (1893).

    μ(T) = μ_ref · (T/T_ref)^(3/2) · (T_ref + S) / (T + S)

    Valid for air 100–3000 K.
    """
    T = np.maximum(T, 1.0)  # guard
    return _MU_REF * (T / _T_REF) ** 1.5 * (_T_REF + _S_C) / (T + _S_C)


# ---------------------------------------------------------------------------
# FVM time-step
# ---------------------------------------------------------------------------

def step_compressible(
    state: CompressibleState,
    cell_volumes: np.ndarray,
    face_areas: np.ndarray,
    face_normals: np.ndarray,
    neighbours: list[tuple[int, int]],
    dt: float,
) -> CompressibleState:
    """
    One explicit pseudo-time step of the compressible Euler / Navier-Stokes
    equations via cell-centred FVM.

    Inviscid fluxes: Roe (1981) approximate Riemann solver (shock-capturing).
    Viscous fluxes:  Central-difference approximation with Sutherland μ(T).

    Parameters
    ----------
    state        : current conserved-variable state
    cell_volumes : (Ncells,) cell volumes [m³]
    face_areas   : (Nfaces,) face areas [m²]
    face_normals : (Nfaces, ndim) outward face normal vectors (area-weighted)
    neighbours   : list of (left_cell, right_cell) index pairs, length Nfaces
    dt           : time step [s]

    Returns
    -------
    New CompressibleState after one explicit Euler step.

    References
    ----------
    Anderson (2003) §4.2 — finite-volume formulation.
    Toro (2009) §6.3 — explicit first-order time integration.
    """
    ncells = len(state.rho)
    ndim = state.rho_u.shape[1]

    d_rho = np.zeros(ncells)
    d_rho_u = np.zeros((ncells, ndim))
    d_rho_E = np.zeros(ncells)

    T = state.temperature()
    mu = _sutherland_viscosity(T)
    u_vel = state.velocity()

    for i_face, (iL, iR) in enumerate(neighbours):
        n_vec = face_normals[i_face]   # area-weighted normal

        # Extract left/right single-cell states
        def _cell_state(idx):
            return CompressibleState(
                rho=state.rho[idx:idx+1],
                rho_u=state.rho_u[idx:idx+1],
                rho_E=state.rho_E[idx:idx+1],
                gamma=state.gamma,
            )

        s_L = _cell_state(iL)
        s_R = _cell_state(iR)

        # Inviscid Roe flux
        f_inv = roe_flux(s_L, s_R, n_vec)

        # Viscous flux (simplified: τ ~ μ·∂u/∂x, central difference)
        # Approximate face-centred gradient from the two cell values
        A = face_areas[i_face]
        n_hat = n_vec / (np.linalg.norm(n_vec) + 1e-14)
        mu_face = 0.5 * (mu[iL] + mu[iR])
        # Approximate length scale between cell centres (unit; user provides geometry)
        du = u_vel[iR] - u_vel[iL]
        # Viscous stress · normal — simplified as μ·∇u·n (collinear approximation)
        tau_n = mu_face * du   # (ndim,)
        f_visc = np.concatenate([[0.0], tau_n, [float(np.dot(tau_n, 0.5 * (u_vel[iL] + u_vel[iR])))]])

        flux_net = f_inv + f_visc

        # Left cell: flux exits (+)
        d_rho[iL] -= flux_net[0]
        d_rho_u[iL] -= flux_net[1:1+ndim]
        d_rho_E[iL] -= flux_net[1+ndim]

        # Right cell: flux enters (-)
        d_rho[iR] += flux_net[0]
        d_rho_u[iR] += flux_net[1:1+ndim]
        d_rho_E[iR] += flux_net[1+ndim]

    new_rho = state.rho + dt * d_rho / cell_volumes
    new_rho_u = state.rho_u + dt * d_rho_u / cell_volumes[:, None]
    new_rho_E = state.rho_E + dt * d_rho_E / cell_volumes

    return CompressibleState(rho=new_rho, rho_u=new_rho_u, rho_E=new_rho_E, gamma=state.gamma)


# ---------------------------------------------------------------------------
# Normal shock relations
# ---------------------------------------------------------------------------

def normal_shock_relations(M_1: float, gamma: float = 1.4) -> dict:
    """
    Rankine-Hugoniot jump conditions across a normal shock.

    Valid for M_1 > 1 (supersonic upstream).  Returns dimensionless ratios.

    Parameters
    ----------
    M_1   : upstream Mach number (must be ≥ 1.0)
    gamma : heat-capacity ratio (1.4 for air)

    Returns
    -------
    dict with keys:
      p2_p1     — static pressure ratio p₂/p₁
      rho2_rho1 — density ratio ρ₂/ρ₁
      T2_T1     — temperature ratio T₂/T₁
      M2        — downstream Mach number

    References
    ----------
    Anderson (2003) §3.6 — normal shock equations (Eqs. 3.57–3.65).
    Rankine (1870); Hugoniot (1889).

    Example (air, M₁=2):
      p₂/p₁ ≈ 4.50,  T₂/T₁ ≈ 1.687,  ρ₂/ρ₁ ≈ 2.667,  M₂ ≈ 0.577
    """
    if M_1 < 1.0:
        raise ValueError(f"Normal shock requires M_1 ≥ 1.0, got {M_1}")

    g = gamma
    M1sq = M_1 ** 2

    p2_p1 = (2.0 * g * M1sq - (g - 1.0)) / (g + 1.0)

    rho2_rho1 = ((g + 1.0) * M1sq) / ((g - 1.0) * M1sq + 2.0)

    T2_T1 = p2_p1 / rho2_rho1   # ideal gas: T ~ p/ρ

    M2sq_num = 1.0 + ((g - 1.0) / 2.0) * M1sq
    M2sq_den = g * M1sq - (g - 1.0) / 2.0
    M2 = np.sqrt(M2sq_num / M2sq_den)

    return {
        "p2_p1": float(p2_p1),
        "rho2_rho1": float(rho2_rho1),
        "T2_T1": float(T2_T1),
        "M2": float(M2),
    }


# ---------------------------------------------------------------------------
# Isentropic flow relations
# ---------------------------------------------------------------------------

def isentropic_relations(M: float, gamma: float = 1.4) -> dict:
    """
    Isentropic flow stagnation-to-static ratios for a given Mach number.

    Relations (calorically perfect gas, isentropic process):
      T₀/T   = 1 + (γ-1)/2 · M²
      p₀/p   = (T₀/T)^(γ/(γ-1))
      ρ₀/ρ   = (T₀/T)^(1/(γ-1))
      A/A*   = (1/M)·[(2/(γ+1))·(1 + (γ-1)/2·M²)]^((γ+1)/(2(γ-1)))

    Parameters
    ----------
    M     : Mach number (≥ 0)
    gamma : heat-capacity ratio (1.4 for air)

    Returns
    -------
    dict with T0_T, p0_p, rho0_rho, A_Astar, critical_velocity_ratio

    References
    ----------
    Anderson, J.D. (2003) "Modern Compressible Flow" 3rd ed., §3.4.
    NACA Report 1135 (1953) — isentropic flow tables.
    """
    if M < 0.0:
        raise ValueError(f"Mach number must be ≥ 0, got {M}")
    g = gamma
    t_ratio = 1.0 + (g - 1.0) / 2.0 * M ** 2
    p_ratio = t_ratio ** (g / (g - 1.0))
    rho_ratio = t_ratio ** (1.0 / (g - 1.0))

    # Area ratio A/A* (Eq. 3.30, Anderson 2003)
    if M > 0:
        exponent = (g + 1.0) / (2.0 * (g - 1.0))
        A_Astar = (1.0 / M) * ((2.0 / (g + 1.0)) * t_ratio) ** exponent
    else:
        A_Astar = float("inf")   # throat at M=0 is ill-defined

    # Critical velocity ratio u/a* = M·√[(γ+1)/(2 + (γ-1)M²)]^½
    # (normalised by critical sound speed a*)
    vel_ratio = M * ((g + 1.0) / (2.0 + (g - 1.0) * M ** 2)) ** 0.5

    return {
        "M": float(M),
        "gamma": float(gamma),
        "T0_T": float(t_ratio),
        "p0_p": float(p_ratio),
        "rho0_rho": float(rho_ratio),
        "A_Astar": float(A_Astar),
        "critical_velocity_ratio": float(vel_ratio),
        "note": "Anderson (2003) §3.4 — isentropic relations for calorically perfect gas.",
    }


# ---------------------------------------------------------------------------
# Oblique shock relations
# ---------------------------------------------------------------------------

def oblique_shock_relations(
    M1: float,
    theta_deg: float,
    gamma: float = 1.4,
    *,
    weak_solution: bool = True,
) -> dict:
    """
    Oblique shock wave β–θ–M relations.

    Given upstream Mach number M₁ and flow deflection angle θ (deg),
    solve for the wave angle β and downstream conditions.

    Method: iterative solution of the θ-β-M relation
      tan θ = 2 cot β · (M₁²sin²β - 1) / (M₁²(γ + cos 2β) + 2)
    using bisection on β ∈ (β_min, β_max) for the weak solution.

    Parameters
    ----------
    M1          : upstream Mach number (must be > 1)
    theta_deg   : flow deflection angle θ [degrees] (0 ≤ θ ≤ θ_max)
    gamma       : heat-capacity ratio (1.4 for air)
    weak_solution : True → weak shock (smaller β), False → strong shock

    Returns
    -------
    dict with wave_angle_deg, p2_p1, T2_T1, rho2_rho1, M2,
             theta_max_deg, normal_M1_component

    References
    ----------
    Anderson, J.D. (2003) "Modern Compressible Flow" 3rd ed., §4.7.
    Liepmann, H.W., Roshko, A. (1957) "Elements of Gasdynamics" §4.14.
    """
    if M1 <= 1.0:
        raise ValueError(f"Oblique shock requires M1 > 1, got {M1}")
    if theta_deg < 0.0:
        raise ValueError(f"Deflection angle theta must be ≥ 0°, got {theta_deg}")

    g = gamma
    theta_rad = math.radians(theta_deg)

    # --- Find θ_max by sweeping β and finding the maximum θ ---
    beta_min_rad = math.asin(1.0 / M1)   # Mach angle μ (minimum wave angle)
    beta_max_rad = math.pi / 2.0          # normal shock

    def _theta_of_beta(b: float) -> float:
        """θ as a function of β for given M1 (Anderson 2003, Eq. 4.17)."""
        sinb = math.sin(b)
        cosb = math.cos(b)
        M1n_sq = (M1 * sinb) ** 2
        numer = 2.0 * (1.0 / math.tan(b)) * (M1n_sq - 1.0)
        denom = M1 ** 2 * (g + math.cos(2.0 * b)) + 2.0
        if abs(denom) < 1e-14:
            return 0.0
        return math.atan(numer / denom)

    # Scan to find θ_max and the corresponding β
    n_scan = 1000
    betas = np.linspace(beta_min_rad + 1e-6, beta_max_rad - 1e-6, n_scan)
    thetas = np.array([_theta_of_beta(b) for b in betas])
    idx_max = int(np.argmax(thetas))
    theta_max_deg = math.degrees(float(thetas[idx_max]))
    beta_at_theta_max = float(betas[idx_max])

    if theta_deg > theta_max_deg + 1e-3:
        raise ValueError(
            f"Deflection θ={theta_deg:.2f}° exceeds θ_max={theta_max_deg:.2f}° "
            f"for M₁={M1:.3f} — no attached oblique shock solution."
        )

    # --- Bisect for β ---
    if weak_solution:
        # Weak shock: β between β_min and β_at_θ_max
        b_lo = float(beta_min_rad + 1e-6)
        b_hi = float(beta_at_theta_max)
    else:
        # Strong shock: β between β_at_θ_max and π/2
        b_lo = float(beta_at_theta_max)
        b_hi = float(beta_max_rad - 1e-6)

    # Bisection
    for _ in range(80):
        b_mid = 0.5 * (b_lo + b_hi)
        th_mid = _theta_of_beta(b_mid)
        if th_mid < theta_rad:
            if weak_solution:
                b_lo = b_mid
            else:
                b_hi = b_mid
        else:
            if weak_solution:
                b_hi = b_mid
            else:
                b_lo = b_mid

    beta_rad = 0.5 * (b_lo + b_hi)
    beta_deg = math.degrees(beta_rad)

    # --- Downstream conditions using normal shock on M1n = M1·sin(β) ---
    M1n = M1 * math.sin(beta_rad)
    ns = normal_shock_relations(max(M1n, 1.0 + 1e-9), gamma)

    # Downstream Mach number (Anderson 2003, Eq. 4.20)
    M2n = ns["M2"]   # normal component
    M2 = M2n / math.sin(beta_rad - theta_rad)

    return {
        "M1": float(M1),
        "theta_deg": float(theta_deg),
        "beta_deg": float(beta_deg),
        "theta_max_deg": float(theta_max_deg),
        "M1_normal_component": float(M1n),
        "M2": float(M2),
        "p2_p1": ns["p2_p1"],
        "rho2_rho1": ns["rho2_rho1"],
        "T2_T1": ns["T2_T1"],
        "solution_type": "weak" if weak_solution else "strong",
        "note": "Anderson (2003) §4.7 θ-β-M oblique shock relations.",
    }


# ---------------------------------------------------------------------------
# Prandtl-Meyer expansion fan
# ---------------------------------------------------------------------------

def prandtl_meyer_expansion(
    M1: float,
    theta_deg: float,
    gamma: float = 1.4,
) -> dict:
    """
    Prandtl-Meyer expansion fan — downstream Mach number after
    a convex corner expansion.

    The Prandtl-Meyer function ν(M) is:
      ν(M) = √((γ+1)/(γ-1)) · arctan(√((γ-1)/(γ+1)·(M²-1)))
             − arctan(√(M²-1))   [radians]

    Expansion: ν(M₂) = ν(M₁) + θ,  solve for M₂ by bisection.

    Parameters
    ----------
    M1        : upstream Mach number (must be ≥ 1)
    theta_deg : expansion angle θ [degrees] (positive = expansion)
    gamma     : heat-capacity ratio

    Returns
    -------
    dict with M2, nu1_deg, nu2_deg, p2_p1, T2_T1, rho2_rho1

    References
    ----------
    Anderson (2003) §9.6 — Prandtl-Meyer expansion.
    """
    if M1 < 1.0:
        raise ValueError(f"Prandtl-Meyer requires M1 ≥ 1, got {M1}")
    if theta_deg < 0.0:
        raise ValueError(f"Expansion angle must be ≥ 0°, got {theta_deg}")

    g = gamma

    def _nu(M: float) -> float:
        """Prandtl-Meyer function ν(M) in radians."""
        if M < 1.0 + 1e-9:
            return 0.0
        a = math.sqrt((g + 1.0) / (g - 1.0))
        b = math.sqrt((g - 1.0) / (g + 1.0) * (M ** 2 - 1.0))
        return a * math.atan(b) - math.atan(math.sqrt(M ** 2 - 1.0))

    nu1 = _nu(M1)
    nu2 = nu1 + math.radians(theta_deg)

    # Bisect for M2 such that ν(M2) = nu2
    # Maximum ν = π/2·(√((γ+1)/(γ-1)) - 1) (M → ∞)
    nu_max = (math.pi / 2.0) * (math.sqrt((g + 1.0) / (g - 1.0)) - 1.0)
    if nu2 > nu_max:
        raise ValueError(
            f"Expansion ν₂={math.degrees(nu2):.2f}° exceeds ν_max={math.degrees(nu_max):.2f}°"
        )

    # Bisect
    m_lo, m_hi = M1, 100.0
    for _ in range(80):
        m_mid = 0.5 * (m_lo + m_hi)
        if _nu(m_mid) < nu2:
            m_lo = m_mid
        else:
            m_hi = m_mid
    M2 = 0.5 * (m_lo + m_hi)

    # Isentropic ratios (expansion is isentropic)
    # p/p0, T/T0 from M1 and M2
    t1 = 1.0 + (g - 1.0) / 2.0 * M1 ** 2
    t2 = 1.0 + (g - 1.0) / 2.0 * M2 ** 2
    T2_T1 = t1 / t2
    p2_p1 = (t1 / t2) ** (g / (g - 1.0))
    rho2_rho1 = (t1 / t2) ** (1.0 / (g - 1.0))

    return {
        "M1": float(M1),
        "theta_deg": float(theta_deg),
        "M2": float(M2),
        "nu1_deg": math.degrees(nu1),
        "nu2_deg": math.degrees(nu2),
        "T2_T1": float(T2_T1),
        "p2_p1": float(p2_p1),
        "rho2_rho1": float(rho2_rho1),
        "note": "Anderson (2003) §9.6 — Prandtl-Meyer expansion (isentropic).",
    }
