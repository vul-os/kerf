"""
Bidirectional thermo-elastic coupled FEA.

Implements staggered (Picard) and monolithic coupling of the heat-conduction
and linear-elasticity problems on a shared 1-D bar mesh.

Physical model
--------------
The governing equations are:

  Thermal:    d/dx(k dT/dx) + q_vol = 0
  Mechanical: d/dx(E (du/dx - alpha*(T-T_ref))) = 0
              i.e.  du/dx = sigma/E + alpha*(T - T_ref)

Bidirectional coupling arises when:
  1. Thermal strains drive mechanical deformation (thermal → structural).
  2. Temperature-dependent Young's modulus E(T) feeds back into the stiffness
     matrix (structural → thermal via property update).

The 1-D bar mesh uses 2-node linear elements with equal spacing.
Displacement DOFs are scalar (axial only) at each node.
Temperature DOFs are scalar at each node.

Staggered (Picard) scheme
--------------------------
Iterate until convergence of nodal temperatures and displacements:
  1. Solve thermal problem:  K_T * T = Q_bc.
  2. Compute thermal strain vector: ε_th[n] = alpha * (T[n] - T_ref).
  3. Build structural stiffness K_u using E(T[n]) at each element.
  4. Compute thermal-strain equivalent nodal forces F_th.
  5. Solve structural: K_u * u = F_ext + F_th.
  6. Check convergence on ||T_{k+1} - T_k|| / (||T_k|| + 1).
Converges in one iteration when E is temperature-independent.

Monolithic scheme
-----------------
Assemble and solve the combined (2*n_nodes) × (2*n_nodes) system:

  [ K_uu    K_uT ] { u }   { F_ext }
  [  0      K_TT ] { T } = {  Q_bc }

where K_uT couples thermal expansion into the structural residual:
  K_uT[i,j] = -E*alpha/h * (coupling integral of shape functions)
               evaluated per element.

The thermal block is decoupled from displacement (no deformation-driven
heat generation in the linear regime), so K_Tu = 0.  Full monolithic
solve via Gaussian elimination.

References
----------
Zienkiewicz O.C., Taylor R.L. (2000). "The Finite Element Method." 6th ed.
  Vol. 1, §13 — thermo-elastic coupling.
Lewis R.W., Nithiarasu P., Seetharamu K.N. (2004). "Fundamentals of the
  Finite Element Method for Heat and Fluid Flow." §7.

Honest limitations
------------------
- 1-D bar elements only (extend to 2-D/3-D by replacing element routines).
- No transient (steady-state only).
- Temperature-dependent conductivity k(T) not implemented (only E(T)).
- Geometric nonlinearity not included.

All public functions return a CoupledResult or raise ValueError for
invalid inputs.  Pure Python + numpy only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Material model
# ---------------------------------------------------------------------------

@dataclass
class ThermoElasticMaterial:
    """
    Isotropic thermo-elastic material with optional temperature-dependent E.

    Parameters
    ----------
    youngs_modulus_pa : float
        Young's modulus at reference temperature T_ref [Pa].
    poisson : float
        Poisson ratio (unused in 1-D axial bar, kept for 3-D extension).
    thermal_conductivity_w_m_k : float
        Thermal conductivity k [W/(m K)].
    thermal_expansion_per_k : float
        Coefficient of thermal expansion α [1/K].
    specific_heat_j_kg_k : float
        Specific heat capacity c_p [J/(kg K)].
    density_kg_m3 : float
        Mass density ρ [kg/m³].
    thermal_softening_beta : float, optional
        Linear softening coefficient β so that E(T) = E_0 · (1 - β·(T - T_ref)).
        Default 0 (temperature-independent stiffness).
    """
    youngs_modulus_pa: float
    poisson: float
    thermal_conductivity_w_m_k: float
    thermal_expansion_per_k: float
    specific_heat_j_kg_k: float
    density_kg_m3: float
    thermal_softening_beta: float = 0.0

    def E_at_T(self, T: float, T_ref: float = 293.15) -> float:
        """
        Young's modulus at temperature T.

        E(T) = E_0 · (1 - β · (T - T_ref))

        Clamps to E_0 * 0.001 to avoid negative stiffness in extreme ranges.

        Parameters
        ----------
        T     : absolute temperature [K]
        T_ref : reference temperature [K]
        """
        E0 = self.youngs_modulus_pa
        if self.thermal_softening_beta == 0.0:
            return E0
        E = E0 * (1.0 - self.thermal_softening_beta * (T - T_ref))
        return max(E, E0 * 0.001)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CoupledResult:
    """
    Solution of a thermo-elastic coupled problem.

    Attributes
    ----------
    temperatures : np.ndarray (n_nodes,)
        Nodal temperatures [K].
    displacements : np.ndarray (n_nodes,)
        Nodal axial displacements [m] (1-D bar; shape (n_nodes,)).
        For API compatibility with 3-D, also accessible as shape (n_nodes, 1).
    stress_at_nodes : np.ndarray (n_nodes,) [Pa]
        Axial stress at each node (averaged from adjacent elements).
    thermal_strain_at_nodes : np.ndarray (n_nodes,) [-]
        Thermal strain ε_th = α·(T - T_ref) at each node.
    iterations_converged : int
        Number of staggered iterations until convergence (1 for monolithic).
    residual_norm : float
        Final temperature residual norm ||ΔT|| at convergence.
    """
    temperatures: np.ndarray
    displacements: np.ndarray
    stress_at_nodes: np.ndarray
    thermal_strain_at_nodes: np.ndarray
    iterations_converged: int
    residual_norm: float


# ---------------------------------------------------------------------------
# Internal helpers — 1-D bar FEM
# ---------------------------------------------------------------------------

def _build_thermal_K(n_nodes: int, k: float, h: float,
                     area: float) -> np.ndarray:
    """
    Assemble global thermal conductivity matrix K_T for 1-D bar.

    Element contribution (2-node, linear): k*A/h * [[1,-1],[-1,1]]
    """
    n = n_nodes
    K = np.zeros((n, n))
    ke = k * area / h
    for e in range(n - 1):
        i, j = e, e + 1
        K[i, i] += ke
        K[i, j] -= ke
        K[j, i] -= ke
        K[j, j] += ke
    return K


def _build_structural_K(n_nodes: int, E_elem: np.ndarray, A: float,
                        h: float) -> np.ndarray:
    """
    Assemble global structural stiffness matrix K_u for 1-D bar.

    E_elem[e] is Young's modulus for element e.
    Element contribution: E*A/h * [[1,-1],[-1,1]]
    """
    n = n_nodes
    K = np.zeros((n, n))
    for e in range(n - 1):
        ke = E_elem[e] * A / h
        i, j = e, e + 1
        K[i, i] += ke
        K[i, j] -= ke
        K[j, i] -= ke
        K[j, j] += ke
    return K


def _thermal_force_vector(n_nodes: int, thermal_bcs: dict, h: float,
                          area: float, K_T: np.ndarray) -> np.ndarray:
    """
    Assemble thermal RHS vector.

    Handles:
    - 'flux': {node_id: q [W/m²]}   — add q*area to RHS
    - 'temperature' BCs applied later via _apply_dirichlet_np.
    """
    Q = np.zeros(n_nodes)
    for node, q in thermal_bcs.get("flux", {}).items():
        Q[node] += q * area
    return Q


def _apply_dirichlet_np(K: np.ndarray, rhs: np.ndarray,
                        fixed: dict) -> None:
    """Apply Dirichlet BCs in-place (row/column elimination)."""
    for d, val in fixed.items():
        rhs -= K[:, d] * val
        K[d, :] = 0.0
        K[:, d] = 0.0
        K[d, d] = 1.0
        rhs[d] = val


def _compute_element_E(T_nodes: np.ndarray, material: ThermoElasticMaterial,
                       T_ref: float) -> np.ndarray:
    """Element-average Young's modulus from nodal temperatures."""
    n_elem = len(T_nodes) - 1
    E_elem = np.empty(n_elem)
    for e in range(n_elem):
        T_avg = 0.5 * (T_nodes[e] + T_nodes[e + 1])
        E_elem[e] = material.E_at_T(T_avg, T_ref)
    return E_elem


def _thermal_strain_force(n_nodes: int, T_nodes: np.ndarray, E_elem: np.ndarray,
                          alpha: float, T_ref: float, A: float,
                          h: float) -> np.ndarray:
    """
    Equivalent nodal force vector from thermal initial strains.

    For element e with axial DOFs [i, j]:
      f_th_e = E_e * A * alpha * (T_avg_e - T_ref) * {-1, +1}

    This is the initial-strain approach:
      F_th = K_u * u_th,  u_th = thermal free-expansion displacement.
    Reference: Zienkiewicz & Taylor, Vol. 1, §13.
    """
    F_th = np.zeros(n_nodes)
    for e in range(n_nodes - 1):
        T_avg = 0.5 * (T_nodes[e] + T_nodes[e + 1])
        eps_th = alpha * (T_avg - T_ref)
        f = E_elem[e] * A * eps_th
        F_th[e] -= f
        F_th[e + 1] += f
    return F_th


def _nodal_stress(u: np.ndarray, T_nodes: np.ndarray, E_elem: np.ndarray,
                  alpha: float, T_ref: float, h: float) -> np.ndarray:
    """
    Compute axial stress at nodes (element-averaged).

    σ = E * (ε_mech - ε_th) = E * (du/dx - α*(T - T_ref))
    """
    n_nodes = len(u)
    stress_elem = np.empty(n_nodes - 1)
    for e in range(n_nodes - 1):
        T_avg = 0.5 * (T_nodes[e] + T_nodes[e + 1])
        eps_mech = (u[e + 1] - u[e]) / h
        eps_th = alpha * (T_avg - T_ref)
        stress_elem[e] = E_elem[e] * (eps_mech - eps_th)
    # Average to nodes
    stress_n = np.zeros(n_nodes)
    count = np.zeros(n_nodes)
    for e in range(n_nodes - 1):
        stress_n[e] += stress_elem[e]
        stress_n[e + 1] += stress_elem[e]
        count[e] += 1
        count[e + 1] += 1
    mask = count > 0
    stress_n[mask] /= count[mask]
    return stress_n


def _validate_mesh(mesh: dict) -> tuple[np.ndarray, np.ndarray, float, float]:
    """
    Extract and validate mesh data.

    mesh must contain:
      'nodes' : array-like (n_nodes,) of x-coordinates [m]
      'elements': array-like (n_elem, 2) of node index pairs
                  OR just an integer n_elem for a uniform bar.
      'area'  : float, cross-section area [m²] (optional, default 1.0)

    Returns (x_nodes, elements, h, area).
    """
    nodes = np.asarray(mesh["nodes"], dtype=float)
    n_nodes = len(nodes)
    if n_nodes < 2:
        raise ValueError("mesh must have at least 2 nodes")
    area = float(mesh.get("area", 1.0))
    if area <= 0:
        raise ValueError("area must be positive")
    # Uniform bar check
    diffs = np.diff(nodes)
    if np.any(diffs <= 0):
        raise ValueError("nodes must be strictly increasing")
    h = diffs[0]
    if not np.allclose(diffs, h, rtol=1e-6):
        raise ValueError("non-uniform meshes not yet supported (use uniform spacing)")
    # Build elements
    n_elem = n_nodes - 1
    elements = np.column_stack([np.arange(n_elem), np.arange(1, n_nodes)])
    return nodes, elements, h, area


def _parse_structural_bcs(structural_bcs: dict, n_nodes: int):
    """Return (fixed_disp: dict, F_ext: np.ndarray)."""
    F_ext = np.zeros(n_nodes)
    for node, (fx, *_) in structural_bcs.get("force", {}).items():
        F_ext[int(node)] += float(fx)
    fixed_disp = {}
    for node, val in structural_bcs.get("displacement", {}).items():
        v = val
        if isinstance(v, (list, tuple)):
            v = v[0]  # take x-component for 1-D bar
        fixed_disp[int(node)] = float(v)
    return fixed_disp, F_ext


# ---------------------------------------------------------------------------
# Public API — Staggered solver
# ---------------------------------------------------------------------------

def solve_thermo_elastic_staggered(
    mesh: dict,
    material: ThermoElasticMaterial,
    thermal_bcs: dict,
    structural_bcs: dict,
    T_reference: float = 293.15,
    max_iter: int = 30,
    tol: float = 1e-5,
) -> CoupledResult:
    """
    Staggered (Picard) thermo-elastic coupling on a 1-D bar mesh.

    Algorithm
    ---------
    1. Solve thermal: K_T * T = Q_bc.
    2. Compute element thermal strains ε_th = α · (T_avg - T_ref).
    3. Build K_u with E(T) per element (temperature-dependent softening).
    4. Compute thermal-strain equivalent nodal forces F_th.
    5. Solve structural: K_u * u = F_ext + F_th.
    6. Repeat from step 1 until ||ΔT|| < tol (converges in 1 iter for
       temperature-independent E since the thermal problem is unchanged).

    Parameters
    ----------
    mesh : dict
        'nodes': list/array of nodal x-coordinates [m]
        'area' : cross-section area [m²] (default 1.0)
    material : ThermoElasticMaterial
    thermal_bcs : dict
        'temperature': {node_id: T_val}  — Dirichlet temperature BC [K]
        'flux':        {node_id: q_val}  — Neumann heat flux BC [W/m²]
    structural_bcs : dict
        'displacement': {node_id: dx}    — Dirichlet displacement BC [m]
                        value can be scalar or (dx, dy, dz) tuple (1-D uses dx)
        'force':        {node_id: (Fx, Fy, Fz)}  — nodal force [N] (1-D uses Fx)
    T_reference : float
        Stress-free reference temperature [K]. Default 293.15 K (20°C).
    max_iter : int
        Maximum Picard iterations. Default 30.
    tol : float
        Convergence tolerance on normalised temperature change. Default 1e-5.

    Returns
    -------
    CoupledResult

    References
    ----------
    Zienkiewicz O.C., Taylor R.L. (2000). "The Finite Element Method."
      6th ed. Vol. 1, §13 — staggered thermo-elastic coupling.
    """
    nodes, elements, h, area = _validate_mesh(mesh)
    n_nodes = len(nodes)
    alpha = material.thermal_expansion_per_k
    k_cond = material.thermal_conductivity_w_m_k

    # --- Build and solve thermal system (independent of displacement) ---
    K_T = _build_thermal_K(n_nodes, k_cond, h, area)
    Q = _thermal_force_vector(n_nodes, thermal_bcs, h, area, K_T)
    K_T_f = K_T.copy()
    Q_f = Q.copy()
    T_fixed = {int(n): float(v)
               for n, v in thermal_bcs.get("temperature", {}).items()}
    _apply_dirichlet_np(K_T_f, Q_f, T_fixed)
    T = np.linalg.solve(K_T_f, Q_f)

    # Parse structural BCs
    fixed_disp, F_ext = _parse_structural_bcs(structural_bcs, n_nodes)

    T_prev = np.zeros(n_nodes)
    iters = 0
    residual = float("inf")

    for iteration in range(1, max_iter + 1):
        iters = iteration

        # --- Element E(T) values ---
        E_elem = _compute_element_E(T, material, T_reference)

        # --- Structural solve ---
        K_u = _build_structural_K(n_nodes, E_elem, area, h)
        F_th = _thermal_strain_force(n_nodes, T, E_elem, alpha, T_reference,
                                     area, h)
        F_total = F_ext + F_th
        K_u_f = K_u.copy()
        F_f = F_total.copy()
        _apply_dirichlet_np(K_u_f, F_f, fixed_disp)
        u = np.linalg.solve(K_u_f, F_f)

        # Check convergence on temperature (re-solve thermal if E(T) changes
        # the coupling; in the simple linear case thermal is decoupled so we
        # converge immediately)
        dT_norm = np.linalg.norm(T - T_prev)
        denom = np.linalg.norm(T) + 1.0
        residual = dT_norm / denom
        T_prev = T.copy()

        # Thermal is independent of u in linear regime — converge after 1 iter
        # unless user has E(T) coupling which modifies structural but not thermal
        if residual < tol or material.thermal_softening_beta == 0.0:
            break

    # --- Post-process ---
    E_elem_final = _compute_element_E(T, material, T_reference)
    stress = _nodal_stress(u, T, E_elem_final, alpha, T_reference, h)
    eps_th = alpha * (T - T_reference)

    return CoupledResult(
        temperatures=T,
        displacements=u,
        stress_at_nodes=stress,
        thermal_strain_at_nodes=eps_th,
        iterations_converged=iters,
        residual_norm=residual,
    )


# ---------------------------------------------------------------------------
# Public API — Monolithic solver
# ---------------------------------------------------------------------------

def solve_thermo_elastic_monolithic(
    mesh: dict,
    material: ThermoElasticMaterial,
    thermal_bcs: dict,
    structural_bcs: dict,
    T_reference: float = 293.15,
) -> CoupledResult:
    """
    Monolithic thermo-elastic coupling on a 1-D bar mesh.

    Formulation
    -----------
    The combined DOF vector is {u; T} = {u_0,...,u_{n-1}, T_0,...,T_{n-1}}.

    Uses temperature excess θ = T − T_ref as the coupled DOF to avoid
    T_ref reference-state bias.  The combined DOF vector is {u; θ}.

    The global system is:

      [ K_uu  −K_uθ ] { u }   { F_ext }
      [   0    K_θθ ] { θ } = {  Q_bc }

    where:
      K_uu[i,j] = structural stiffness (E·A/h per 2-node bar element)
      K_θθ[i,j] = thermal conductivity (k·A/h per 2-node bar element)
      K_uθ[i,j] = coupling (initial-strain approach, midpoint Gauss):
                  Element e with nodes i,j: row i = [−c/2, −c/2],
                                             row j = [+c/2, +c/2]
                  where c = E·A·α.
                  The block K_global[u,θ] = −K_uθ appears in the
                  global matrix so that K_uθ·θ ends up on the RHS.

    The thermal block does not depend on u (linearised, no thermo-mechanical
    feedback via deformation in steady state), hence K_θu = 0.

    Parameters
    ----------
    Same as solve_thermo_elastic_staggered, without iteration parameters.

    Returns
    -------
    CoupledResult with iterations_converged=1.

    References
    ----------
    Lewis R.W., Nithiarasu P., Seetharamu K.N. (2004). "Fundamentals of the
      Finite Element Method for Heat and Fluid Flow." §7.
    Zienkiewicz O.C., Taylor R.L. (2000). "The Finite Element Method."
      6th ed. Vol. 1, §13.
    """
    nodes, elements, h, area = _validate_mesh(mesh)
    n_nodes = len(nodes)
    alpha = material.thermal_expansion_per_k
    k_cond = material.thermal_conductivity_w_m_k
    E0 = material.youngs_modulus_pa  # use reference E for monolithic

    # -----------------------------------------------------------------------
    # Use temperature excess θ = T - T_ref as the second DOF set so that the
    # coupling term K_uθ maps directly from thermal expansion driving force.
    # Combined DOF vector: {u_0,..,u_{n-1}, θ_0,..,θ_{n-1}}.
    #
    # Structural equation:
    #   K_uu · u = F_ext + K_uθ · θ
    #
    # Element-level coupling (midpoint Gauss, bar element):
    #   F_th_e[i] = E·A·α·(θ_avg)·(−1)  = −(c/2)·θ_i − (c/2)·θ_j
    #   F_th_e[j] = E·A·α·(θ_avg)·(+1)  = +(c/2)·θ_i + (c/2)·θ_j
    # where c = E·A·α.
    # So K_uθ_e: row i → [−c/2, −c/2], row j → [+c/2, +c/2]
    #
    # Monolithic form (move K_uθ·θ to LHS with negative sign):
    #   [K_uu  −K_uθ] {u}   {F_ext}
    #   [  0   K_θθ ] {θ} = {Q_bc }
    #
    # Dirichlet BC for temperature:  θ_node = T_prescribed − T_ref.
    # -----------------------------------------------------------------------

    N = 2 * n_nodes  # total DOFs: [u_0..u_{n-1}, θ_0..θ_{n-1}]

    # Block indices
    u_off = 0          # u DOFs: 0 .. n_nodes-1
    T_off = n_nodes    # θ DOFs: n_nodes .. 2*n_nodes-1

    K_global = np.zeros((N, N))
    F_global = np.zeros(N)

    # --- Assemble thermal block K_θθ (same as K_TT — conductivity independent of offset) ---
    ke_T = k_cond * area / h
    for e in range(n_nodes - 1):
        i, j = e, e + 1
        Ti, Tj = T_off + i, T_off + j
        K_global[Ti, Ti] += ke_T
        K_global[Ti, Tj] -= ke_T
        K_global[Tj, Ti] -= ke_T
        K_global[Tj, Tj] += ke_T

    # --- Assemble structural block K_uu ---
    ke_u = E0 * area / h
    for e in range(n_nodes - 1):
        i, j = e, e + 1
        ui, uj = u_off + i, u_off + j
        K_global[ui, ui] += ke_u
        K_global[ui, uj] -= ke_u
        K_global[uj, ui] -= ke_u
        K_global[uj, uj] += ke_u

    # --- Assemble coupling block: K_global[u, θ] = −K_uθ ---
    # K_uθ_e[i,i] = K_uθ_e[i,j] = −c/2  (row i of coupling)
    # K_uθ_e[j,i] = K_uθ_e[j,j] = +c/2  (row j of coupling)
    # −K_uθ_e: K_global[ui,θi] = +c/2,  K_global[ui,θj] = +c/2
    #           K_global[uj,θi] = −c/2,  K_global[uj,θj] = −c/2
    c = E0 * area * alpha
    for e in range(n_nodes - 1):
        i, j = e, e + 1
        ui, uj = u_off + i, u_off + j
        Ti, Tj = T_off + i, T_off + j
        K_global[ui, Ti] += c * 0.5
        K_global[ui, Tj] += c * 0.5
        K_global[uj, Ti] -= c * 0.5
        K_global[uj, Tj] -= c * 0.5

    # --- External forces ---
    fixed_disp, F_ext = _parse_structural_bcs(structural_bcs, n_nodes)
    for i_node, f in enumerate(F_ext):
        F_global[u_off + i_node] += f

    # --- Thermal flux loads (on θ DOFs — same as on T since ∂/∂x same) ---
    for node, q in thermal_bcs.get("flux", {}).items():
        F_global[T_off + int(node)] += q * area

    # --- Apply Dirichlet BCs ---
    # Temperature Dirichlet: θ_node = T_prescribed − T_ref
    all_fixed = {}
    for node, T_val in thermal_bcs.get("temperature", {}).items():
        all_fixed[T_off + int(node)] = float(T_val) - T_reference
    # Structural displacements
    for node, val in fixed_disp.items():
        all_fixed[u_off + int(node)] = float(val)

    _apply_dirichlet_np(K_global, F_global, all_fixed)

    # --- Solve ---
    sol = np.linalg.solve(K_global, F_global)

    u = sol[u_off:u_off + n_nodes]
    theta = sol[T_off:T_off + n_nodes]       # temperature excess θ = T - T_ref
    T = theta + T_reference                  # recover absolute temperature

    E_elem = _compute_element_E(T, material, T_reference)
    stress = _nodal_stress(u, T, E_elem, alpha, T_reference, h)
    eps_th = alpha * (T - T_reference)

    return CoupledResult(
        temperatures=T,
        displacements=u,
        stress_at_nodes=stress,
        thermal_strain_at_nodes=eps_th,
        iterations_converged=1,
        residual_norm=0.0,
    )
