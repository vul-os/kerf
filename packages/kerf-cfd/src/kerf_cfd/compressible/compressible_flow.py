"""
Compressible Flow — density-based FVM with Roe approximate Riemann solver.

Implements:
  - CompressibleState dataclass (ρ, ρu, ρE conserved variables)
  - roe_flux:               Roe (1981) approximate Riemann solver
  - step_compressible:      One FVM pseudo-time step (Euler / NS)
  - normal_shock_relations: Rankine-Hugoniot jump conditions

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
