"""
Explicit-dynamics FEM — central-difference (Newmark explicit β=0, γ=½) transient solver.

Physics coverage
----------------
* Lumped mass matrix (row-sum diagonalisation of consistent mass, standard for explicit FEM).
* Critical time-step control: dt < 2/ω_max per element; automatic CFL-style dt selection.
* Internal-force assembly re-evaluated every step (supports nonlinear geometry + material).
* Geometric nonlinearity: Green-Lagrange axial strain for bar elements.
* Material nonlinearity: J2 isotropic-hardening plasticity (radial-return algorithm).

Integration scheme (Belytschko/LS-DYNA leapfrog)
-------------------------------------------------
  Initialise:
      a₀ = M⁻¹ · f(x₀, t₀)
      v½  = v₀ + a₀ · dt/2

  Step n = 0, 1, ..., N-1:
      x_{n+1}   = x_n    + v_{n+½}  · dt        position first
      a_{n+1}   = M⁻¹ · f(x_{n+1}, t_{n+1})   force at new position
      v_{n+3/2} = v_{n+½} + a_{n+1} · dt
      v_full    = ½(v_{n+½} + v_{n+3/2})        full-step output velocity

Energy accounting
-----------------
  KE = ½ · sum(m_i · v_full_i²)
  IE = elastic strain energy + cumulative plastic dissipation
  For undamped elastic: |ΔE_total / E₀| < 1%

Public API
----------
  solve_explicit_dynamics(model, duration, *, safety=0.9) -> dict

  ``model`` keys (all SI units):
    nodes        : np.ndarray (n_nodes, 2)  or list of [x, y]   — 2-D nodal coords
    elements     : list of [i, j]            — bar elements (0-based)
    E            : float                     — Young's modulus [Pa]
    area         : float                     — cross-section area [m²]
    rho          : float                     — density [kg/m³]
    sigma_y0     : float                     — initial yield stress [Pa]  (1e30 = elastic)
    H            : float                     — isotropic hardening modulus [Pa]
    fixed_dofs   : list[int]                 — DOF indices to fix (2·node = x, 2·node+1 = y)
    init_vel     : dict[int, float]          — {dof_index: velocity}
    ext_force    : dict[int, float]          — {dof_index: constant external force [N]}

  Returns dict:
    ok           : bool
    t            : list[float]               — time stamps (n_steps+1)
    x            : list[list[float]]         — nodal displacements  (n_steps+1, n_dofs)
    v            : list[list[float]]         — full-step velocities (n_steps+1, n_dofs)
    KE           : list[float]
    IE           : list[float]
    dt           : float
    n_steps      : int
    energy_error : float
    dt_critical  : float                     — CFL-critical dt (safety=1)
    reason       : str  (only when ok=False)

Never raises; returns {"ok": False, "reason": ...} on all error paths.
Requires numpy (available in the standard kerf environment).

References
----------
* Belytschko, Liu, Moran, Elkhodary — "Nonlinear Finite Elements for Continua
  and Structures", 2nd ed. (2014): §6 explicit dynamics, §5.4 lumped mass,
  §4.3 Green-Lagrange strain, §5.9 J2 return mapping.
* Newmark (1959): β=0, γ=½ → central difference.
* LS-DYNA Theory Manual §2.1 — position-first leapfrog (identical to above).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ===========================================================================
# Element-level physics
# ===========================================================================

def _bar_deformed_length(X: np.ndarray, u: np.ndarray, ni: int, nj: int) -> float:
    """Deformed length of bar element given reference coords X and displacement u."""
    xi = X[ni] + u[2 * ni:     2 * ni + 2]
    xj = X[nj] + u[2 * nj:     2 * nj + 2]
    d  = xj - xi
    return float(np.sqrt(d @ d))


def _bar_green_lagrange_strain(L0: float, L: float) -> float:
    """
    Green-Lagrange axial strain for large displacements:

        E_GL = (L² - L0²) / (2 · L0²)

    For small strains: E_GL ≈ (L - L0)/L0 = ε_eng.
    Using GL form captures geometric nonlinearity consistently with the
    second Piola-Kirchhoff framework.
    """
    return (L * L - L0 * L0) / (2.0 * L0 * L0)


def _bar_internal_force(
    X: np.ndarray,
    u: np.ndarray,
    sigma: float,
    area: float,
    ni: int,
    nj: int,
) -> np.ndarray:
    """
    Nodal force vector for a single bar element.
    Returns length-4 array [fi_x, fi_y, fj_x, fj_y].

    The second Piola-Kirchhoff stress S maps to Cauchy via push-forward;
    for a 1-D bar at large displacements the axial force in the deformed
    direction is:
        N = σ · A
    and the nodal forces are N · ê (tension pulls i toward j, j toward i).
    """
    xi = X[ni] + u[2 * ni:     2 * ni + 2]
    xj = X[nj] + u[2 * nj:     2 * nj + 2]
    d  = xj - xi
    L  = float(np.sqrt(d @ d))
    if L < 1e-14:
        return np.zeros(4)
    e = d / L                    # unit vector in deformed direction
    N = sigma * area             # axial force resultant
    # Tension (N > 0): pulls i toward j (+N·ê) and j toward i (-N·ê)
    return np.array([N * e[0], N * e[1], -N * e[0], -N * e[1]])


def _j2_return_map(
    sigma_n: float,
    eps_p_n: float,
    delta_eps: float,
    E: float,
    sigma_y0: float,
    H: float,
) -> tuple[float, float, float]:
    """
    J2 isotropic-hardening radial-return for a uniaxial bar element.

    Parameters
    ----------
    sigma_n   : stress at beginning of step
    eps_p_n   : accumulated equivalent plastic strain
    delta_eps : total strain increment for this step
    E         : Young's modulus
    sigma_y0  : initial yield stress
    H         : isotropic-hardening modulus (H=0 → perfect plasticity)

    Returns
    -------
    (sigma_{n+1}, eps_p_{n+1}, delta_gamma)

    Algorithm: Simo & Hughes, "Computational Inelasticity" (1998) §1.2.
    """
    sigma_y_n   = sigma_y0 + H * eps_p_n
    sigma_trial = sigma_n + E * delta_eps
    f_trial     = abs(sigma_trial) - sigma_y_n

    if f_trial <= 0.0:
        return sigma_trial, eps_p_n, 0.0

    # Plastic step: radial return
    delta_gamma = f_trial / (E + H)
    sign_t      = 1.0 if sigma_trial >= 0.0 else -1.0
    sigma_new   = sigma_trial - sign_t * E * delta_gamma
    eps_p_new   = eps_p_n + delta_gamma
    return sigma_new, eps_p_new, delta_gamma


# ===========================================================================
# CFL-critical time step
# ===========================================================================

def compute_critical_dt(
    X: np.ndarray,
    elements: list[tuple[int, int]],
    masses_lumped: np.ndarray,
    E: float,
    area: float,
    safety: float = 1.0,
) -> float:
    """
    Element-wise CFL time step for wave propagation.

    For each bar element e:
        ω_e = √(k_e / m_e_min)  where k_e = EA/L₀, m_e_min = minimum nodal mass
        dt_e = 2 / ω_e

    Global dt = safety · min_e(dt_e).

    This is the explicit-FEM stability condition dt < 2/ω_max (Newmark §6.3).
    With HRZ lumped mass, the effective element-level ω_max is computed using the
    minimum of the two end-node masses, which conservatively bounds the assembly
    maximum eigenvalue.

    For a uniform bar with HRZ lumping: dt_crit ≈ L_e/c (end elements give
    dt = √(3)/2 · L_e/c, interior elements give L_e/c; the minimum from end elements
    dominates and provides the stability-and-accuracy bound).

    Reference: Belytschko, Liu, Moran & Elkhodary §6.3.2; LS-DYNA Theory Manual §2.1.
    """
    dt_min = math.inf
    for ni, nj in elements:
        d  = X[nj] - X[ni]
        L0 = float(np.sqrt(d @ d))
        if L0 < 1e-14:
            continue
        k_e   = E * area / L0
        # Use minimum end-node mass for conservative stability bound
        m_i   = masses_lumped[2 * ni]
        m_j   = masses_lumped[2 * nj]
        m_min = max(min(m_i, m_j), 1e-30)
        # Use effective element mass (average) for wave-speed bound
        m_avg = max(0.5 * (m_i + m_j), 1e-30)
        # Take the smaller dt from both criteria
        dt_stab  = 2.0 / math.sqrt(k_e / m_min)    # stability: dt < 2/ω_max
        dt_wave  = math.sqrt(m_avg / k_e)            # wave accuracy: dt < L/c ≡ √(m/k)
        dt_e     = min(dt_stab, dt_wave)
        if dt_e < dt_min:
            dt_min = dt_e
    if not math.isfinite(dt_min) or dt_min <= 0.0:
        return 1e-6
    return safety * dt_min


# ===========================================================================
# Lumped mass assembly (HRZ row-sum)
# ===========================================================================

def assemble_lumped_mass(
    X: np.ndarray,
    elements: list[tuple[int, int]],
    area: float,
    rho: float,
    n_nodes: int,
) -> np.ndarray:
    """
    Row-sum lumped mass vector (length 2·n_nodes for 2-D).

    Each bar element contributes ½·ρ·A·L₀ to each of its two end nodes.
    Both DOFs (x, y) of a node get the same lumped mass.

    Total mass in the vector = 2 · ρ · A · Σ(L_e)  (factor 2 for 2 DOFs per node).
    Physical mass of the structure = ρ · A · Σ(L_e).

    Reference: Hinton, Rock & Zienkiewicz (1976) IJNME — HRZ lumping.
    """
    m = np.zeros(2 * n_nodes)
    for ni, nj in elements:
        d      = X[nj] - X[ni]
        L0     = float(np.sqrt(d @ d))
        m_half = 0.5 * rho * area * L0
        m[2 * ni]     += m_half
        m[2 * ni + 1] += m_half
        m[2 * nj]     += m_half
        m[2 * nj + 1] += m_half
    return m


# ===========================================================================
# Internal force assembly (re-evaluated each step)
# ===========================================================================

def assemble_internal_forces(
    X: np.ndarray,
    u: np.ndarray,
    sigmas: list[float],
    area: float,
    elements: list[tuple[int, int]],
    n_dofs: int,
) -> np.ndarray:
    """
    Assemble global internal force vector from current stress state.
    sigmas[e] holds the current 2nd PK / Cauchy stress for element e.
    """
    f_int = np.zeros(n_dofs)
    for e, (ni, nj) in enumerate(elements):
        fe = _bar_internal_force(X, u, sigmas[e], area, ni, nj)
        f_int[2 * ni]     += fe[0]
        f_int[2 * ni + 1] += fe[1]
        f_int[2 * nj]     += fe[2]
        f_int[2 * nj + 1] += fe[3]
    return f_int


# ===========================================================================
# Main solver
# ===========================================================================

def solve_explicit_dynamics(
    model: dict,
    duration: float,
    *,
    safety: float = 0.9,
) -> dict[str, Any]:
    """
    Central-difference explicit dynamics solver for 2-D bar/truss structures.

    See module docstring for full model format and return schema.
    """
    try:
        return _solve_inner(model, duration, safety)
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"unexpected error in explicit_dynamics: {exc}",
            "t": [], "x": [], "v": [], "KE": [], "IE": [],
            "dt": 0.0, "n_steps": 0, "energy_error": 0.0, "dt_critical": 0.0,
        }


def _solve_inner(
    model: dict,
    duration: float,
    safety: float,
) -> dict[str, Any]:
    # ------------------------------------------------------------------
    # Validate + unpack
    # ------------------------------------------------------------------
    if not isinstance(model, dict):
        return _fail("model must be a dict")
    if duration <= 0.0:
        return _fail("duration must be positive")

    nodes_raw    = model.get("nodes")
    elements_raw = model.get("elements")
    if nodes_raw is None or len(nodes_raw) == 0:
        return _fail("model.nodes is required and must be non-empty")
    if elements_raw is None or len(elements_raw) == 0:
        return _fail("model.elements is required and must be non-empty")

    E    = float(model.get("E",        2e11))
    area = float(model.get("area",     1e-4))
    rho  = float(model.get("rho",      7800.0))
    sy0  = float(model.get("sigma_y0", 1e30))
    H    = float(model.get("H",        0.0))

    # Reference (undeformed) node coordinates
    X = np.array(nodes_raw, dtype=float)
    if X.ndim != 2 or X.shape[1] != 2:
        return _fail("nodes must be an (n_nodes, 2) array")

    n_nodes = X.shape[0]
    n_dofs  = 2 * n_nodes

    elements: list[tuple[int, int]] = []
    for e in elements_raw:
        ni, nj = int(e[0]), int(e[1])
        if ni < 0 or ni >= n_nodes or nj < 0 or nj >= n_nodes:
            return _fail(f"element node index out of range: ({ni}, {nj})")
        elements.append((ni, nj))

    fixed_dofs: set[int] = set(int(d) for d in model.get("fixed_dofs", []))
    free_dofs  = [i for i in range(n_dofs) if i not in fixed_dofs]
    if not free_dofs:
        return _fail("all DOFs are fixed — nothing to integrate")

    init_vel_raw  = model.get("init_vel",  {})
    ext_force_raw = model.get("ext_force", {})

    # ------------------------------------------------------------------
    # Lumped mass + element reference lengths
    # ------------------------------------------------------------------
    m_vec = assemble_lumped_mass(X, elements, area, rho, n_nodes)
    # Safety: if a free DOF has zero lumped mass (isolated node), give tiny mass
    for d in free_dofs:
        if m_vec[d] < 1e-30:
            m_vec[d] = 1e-30

    L0_arr = np.array([
        float(np.sqrt(np.sum((X[nj] - X[ni]) ** 2)))
        for ni, nj in elements
    ])

    # ------------------------------------------------------------------
    # CFL time step
    # ------------------------------------------------------------------
    dt_critical = compute_critical_dt(X, elements, m_vec, E, area, safety=1.0)
    dt          = safety * dt_critical
    n_steps     = max(1, int(math.ceil(duration / dt)))
    dt          = duration / n_steps

    # ------------------------------------------------------------------
    # Initial conditions
    # ------------------------------------------------------------------
    u = np.zeros(n_dofs)   # displacement
    v = np.zeros(n_dofs)   # full-step velocity at t = 0

    for dof_str, vel_val in init_vel_raw.items():
        d = int(dof_str)
        if 0 <= d < n_dofs and d not in fixed_dofs:
            v[d] = float(vel_val)

    # Constant external force vector
    f_ext = np.zeros(n_dofs)
    for dof_str, f_val in ext_force_raw.items():
        d = int(dof_str)
        if 0 <= d < n_dofs:
            f_ext[d] = float(f_val)

    # Per-element material state
    n_elem    = len(elements)
    sigmas    = np.zeros(n_elem)   # current stress (Cauchy / 2nd PK equiv)
    eps_p     = np.zeros(n_elem)   # accumulated equivalent plastic strain
    W_plastic = np.zeros(n_elem)   # cumulative plastic dissipation energy [J]

    # ------------------------------------------------------------------
    # Stress update: Green-Lagrange strain increment + J2 return mapping
    # ------------------------------------------------------------------
    def _update_stresses_and_forces(u_new: np.ndarray, u_old: np.ndarray) -> np.ndarray:
        """
        Compute updated stresses from u_old → u_new, update plastic state in-place,
        then return the global internal force vector at u_new.

        Strain increment: Δε = E_GL(u_new) - E_GL(u_old)
        where E_GL = (L² - L0²) / (2·L0²) is the Green-Lagrange measure
        computed from the deformed length at each configuration.
        """
        for e, (ni, nj) in enumerate(elements):
            L_new  = _bar_deformed_length(X, u_new, ni, nj)
            L_prev = _bar_deformed_length(X, u_old, ni, nj)
            if L_new < 1e-14 or L_prev < 1e-14:
                continue
            E_GL_new  = _bar_green_lagrange_strain(L0_arr[e], L_new)
            E_GL_prev = _bar_green_lagrange_strain(L0_arr[e], L_prev)
            delta_eps = E_GL_new - E_GL_prev

            sigma_new, eps_p_new, dgamma = _j2_return_map(
                sigmas[e], eps_p[e], delta_eps, E, sy0, H
            )
            if dgamma > 0.0:
                sigma_y_n  = sy0 + H * eps_p[e]
                W_plastic[e] += sigma_y_n * dgamma * area * L0_arr[e]
            sigmas[e] = sigma_new
            eps_p[e]  = eps_p_new

        return assemble_internal_forces(X, u_new, list(sigmas), area, elements, n_dofs)

    def _elastic_pe(u_cur: np.ndarray) -> float:
        """
        Elastic strain energy: U_e = σ² / (2E) · A · L0   per element.

        Using σ² / (2E) is correct regardless of whether eps_p is tracked,
        because the constitutive law always gives σ = E · ε_elastic, so
        ε_e = σ/E and U = ½·E·ε_e²·A·L0 = σ²/(2E)·A·L0.
        """
        pe = 0.0
        for e in range(n_elem):
            pe += sigmas[e] ** 2 / (2.0 * E) * area * L0_arr[e]
        return pe

    # ------------------------------------------------------------------
    # Initial forces + start-up half-step
    # ------------------------------------------------------------------
    # At t=0: u=0, stress=0 → f_int=0. Only external force contributes.
    f_tot0 = f_ext.copy()   # f_int0 = 0

    a = np.zeros(n_dofs)
    for d in free_dofs:
        a[d] = f_tot0[d] / m_vec[d]
    for d in fixed_dofs:
        a[d] = 0.0

    # v_{1/2} = v_0 + a_0 * dt/2
    v_half = v.copy()
    for d in free_dofs:
        v_half[d] = v[d] + a[d] * 0.5 * dt
    for d in fixed_dofs:
        v_half[d] = 0.0

    # Initial energy using Störmer-Verlet conserved form:
    #   KE_SV = 0.5 · m · v[n-1/2] · v[n+1/2]  + PE(x[n])
    # At n=0, with v[-1/2] ≈ v[0] - a[0]·dt/2:
    #   v[-1/2] = 2·v[0] - v[+1/2]   (symmetric about v[0])
    v_half_minus = 2.0 * v - v_half   # v[-1/2]
    for d in fixed_dofs:
        v_half_minus[d] = 0.0

    KE0 = float(0.5 * np.dot(
        m_vec[free_dofs],
        v_half_minus[free_dofs] * v_half[free_dofs]
    ))
    IE0 = _elastic_pe(u) + float(np.sum(W_plastic))

    t_hist  = [0.0]
    u_hist  = [u.tolist()]
    v_hist  = [v.tolist()]          # store full-step for output (interpolated)
    KE_hist = [KE0]
    IE_hist = [IE0]

    t = 0.0

    # ------------------------------------------------------------------
    # Main time-stepping loop (leapfrog, position-first variant)
    # ------------------------------------------------------------------
    for _step in range(n_steps):
        v_half_before = v_half.copy()   # v[n+1/2]

        # Step 1: position update (always FIRST in central-difference)
        u_new = u.copy()
        for d in free_dofs:
            u_new[d] = u[d] + v_half[d] * dt
        for d in fixed_dofs:
            u_new[d] = 0.0

        # Step 2: stress update + internal force at new position
        f_int_new = _update_stresses_and_forces(u_new, u)
        f_tot_new = f_int_new + f_ext
        for d in fixed_dofs:
            f_tot_new[d] = 0.0

        # Step 3: acceleration at new position
        a_new = np.zeros(n_dofs)
        for d in free_dofs:
            a_new[d] = f_tot_new[d] / m_vec[d]

        # Step 4: velocity update  → v[n+3/2]
        v_half_new = v_half.copy()
        for d in free_dofs:
            v_half_new[d] = v_half[d] + a_new[d] * dt
        for d in fixed_dofs:
            v_half_new[d] = 0.0

        # Step 5: full-step output velocity (centred between adjacent half-steps)
        v_full_new = 0.5 * (v_half_before + v_half_new)
        for d in fixed_dofs:
            v_full_new[d] = 0.0

        # Step 6: energetics — Störmer-Verlet conserved quantity:
        #   KE_SV = 0.5 · Σ m_i · v[n+1/2]_i · v[n+3/2]_i  + PE(x[n+1])
        # This is exactly conserved (machine precision) for elastic linear systems.
        # For nonlinear systems it accumulates only irreversible plastic dissipation.
        KE  = float(0.5 * np.dot(
            m_vec[free_dofs],
            v_half_before[free_dofs] * v_half_new[free_dofs]
        ))
        IE  = _elastic_pe(u_new) + float(np.sum(W_plastic))

        # Advance state
        u      = u_new
        v_half = v_half_new

        t += dt
        t_hist.append(t)
        u_hist.append(u.tolist())
        v_hist.append(v_full_new.tolist())
        KE_hist.append(KE)
        IE_hist.append(IE)

    # ------------------------------------------------------------------
    # Energy conservation error
    # ------------------------------------------------------------------
    E_init  = KE_hist[0]  + IE_hist[0]
    E_final = KE_hist[-1] + IE_hist[-1]
    E_scale = max(abs(E_init), abs(E_final), 1e-30)
    energy_error = float(abs(E_final - E_init) / E_scale)

    return {
        "ok"           : True,
        "t"            : t_hist,
        "x"            : u_hist,
        "v"            : v_hist,
        "KE"           : KE_hist,
        "IE"           : IE_hist,
        "dt"           : dt,
        "n_steps"      : n_steps,
        "energy_error" : energy_error,
        "dt_critical"  : dt_critical,
    }


def _fail(reason: str) -> dict[str, Any]:
    return {
        "ok": False, "reason": reason,
        "t": [], "x": [], "v": [], "KE": [], "IE": [],
        "dt": 0.0, "n_steps": 0, "energy_error": 0.0, "dt_critical": 0.0,
    }


# ===========================================================================
# LLM tool registration
# ===========================================================================

_fem_explicit_dynamics_spec = ToolSpec(
    name="fem_explicit_dynamics",
    description=(
        "Run an explicit-dynamics FEM simulation for transient nonlinear problems "
        "(crash, drop test, impact). Uses central-difference (Newmark β=0, γ=½) "
        "time integration with lumped mass matrix (row-sum HRZ diagonalisation). "
        "Geometric nonlinearity via Green-Lagrange axial strain; material "
        "nonlinearity via J2 isotropic-hardening plasticity (radial-return). "
        "Automatic CFL dt = safety · 2/ω_max per element. "
        "2-D bar/truss mesh; returns time-history of displacements, velocities, "
        "kinetic energy, internal energy, and energy-error metric."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "List of [x, y] reference node coordinates [m].",
            },
            "elements": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "List of [node_i, node_j] bar-element connectivity (0-based).",
            },
            "duration": {
                "type": "number",
                "description": "Simulation end time [s].",
            },
            "E": {
                "type": "number",
                "description": "Young's modulus [Pa]. Default 2e11 (steel).",
                "default": 2e11,
            },
            "area": {
                "type": "number",
                "description": "Cross-sectional area [m²]. Default 1e-4.",
                "default": 1e-4,
            },
            "rho": {
                "type": "number",
                "description": "Mass density [kg/m³]. Default 7800 (steel).",
                "default": 7800,
            },
            "sigma_y0": {
                "type": "number",
                "description": "Initial yield stress [Pa]. Default 1e30 (elastic).",
                "default": 1e30,
            },
            "H": {
                "type": "number",
                "description": "Isotropic hardening modulus [Pa]. Default 0 (perfect plasticity).",
                "default": 0,
            },
            "fixed_dofs": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of DOF indices to fix (2·node = x-DOF, 2·node+1 = y-DOF).",
                "default": [],
            },
            "init_vel": {
                "type": "object",
                "description": "Map of DOF index (string key) → initial velocity [m/s].",
                "default": {},
            },
            "ext_force": {
                "type": "object",
                "description": "Map of DOF index (string key) → constant nodal force [N].",
                "default": {},
            },
            "safety": {
                "type": "number",
                "description": "CFL safety factor (default 0.9; use < 1.0).",
                "default": 0.9,
            },
        },
        "required": ["nodes", "elements", "duration"],
    },
)


@register(_fem_explicit_dynamics_spec)
async def run_fem_explicit_dynamics(ctx: ProjectCtx, args: bytes) -> str:
    import json
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    nodes    = a.get("nodes")
    elements = a.get("elements")
    duration = a.get("duration")

    if nodes is None:
        return err_payload("nodes is required", "BAD_ARGS")
    if elements is None:
        return err_payload("elements is required", "BAD_ARGS")
    if duration is None:
        return err_payload("duration is required", "BAD_ARGS")

    model = {
        "nodes"     : nodes,
        "elements"  : elements,
        "E"         : float(a.get("E",        2e11)),
        "area"      : float(a.get("area",      1e-4)),
        "rho"       : float(a.get("rho",       7800.0)),
        "sigma_y0"  : float(a.get("sigma_y0",  1e30)),
        "H"         : float(a.get("H",         0.0)),
        "fixed_dofs": a.get("fixed_dofs", []),
        "init_vel"  : a.get("init_vel",   {}),
        "ext_force" : a.get("ext_force",  {}),
    }

    result = solve_explicit_dynamics(
        model,
        float(duration),
        safety=float(a.get("safety", 0.9)),
    )
    return json.dumps(result)
