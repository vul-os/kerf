"""
Nonlinear material path: J2 (von Mises) isotropic-hardening return-mapping
for 1-D / uniaxial bar and small-strain truss elements.

Algorithm
---------
Incremental load stepping with Newton-Raphson inner loop.
Each load increment uses a single-step predictor-corrector (radial-return)
for the constitutive update; the global Newton iteration drives residual to
zero over the load step.

Constitutive model
------------------
Isotropic hardening:
    σ_y(εᵖ) = σ_y0 + H · εᵖ          H = hardening modulus (H=0 → perfect plasticity)

Return mapping (1-D):
    σ_trial = E · (ε_n + Δε)
    f_trial  = |σ_trial| - σ_y(εᵖ_n)
    if f_trial ≤ 0: elastic, accept trial state
    else:
        Δγ = f_trial / (E + H)
        σ_n+1 = σ_trial − sign(σ_trial) · E · Δγ
        εᵖ_n+1 = εᵖ_n + Δγ

Returns
-------
dict with keys:
    ok          bool
    strain      list[float]   total strain at end of each load step
    stress      list[float]   Cauchy stress
    plastic_strain list[float] accumulated plastic strain
    reason      str           present only when ok=False
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Core return-mapping for a single uniaxial increment
# ---------------------------------------------------------------------------

def _return_map_1d(
    sigma_n: float,
    eps_p_n: float,
    delta_eps: float,
    E: float,
    sigma_y0: float,
    H: float,
) -> tuple[float, float]:
    """
    One-increment J2/isotropic-hardening return mapping (1-D).

    Parameters
    ----------
    sigma_n    : stress at start of increment
    eps_p_n    : accumulated plastic strain at start of increment
    delta_eps  : total strain increment
    E          : Young's modulus  [Pa]
    sigma_y0   : initial yield stress [Pa]
    H          : isotropic-hardening modulus [Pa]  (H=0 → perfect plasticity)

    Returns
    -------
    (sigma_n1, eps_p_n1) : updated stress and plastic strain
    """
    sigma_y_n = sigma_y0 + H * eps_p_n

    sigma_trial = sigma_n + E * delta_eps
    f_trial = abs(sigma_trial) - sigma_y_n

    if f_trial <= 0.0:
        # Elastic step — no plastic correction needed
        return sigma_trial, eps_p_n

    # Plastic step — radial return
    delta_gamma = f_trial / (E + H)
    sign_trial = 1.0 if sigma_trial >= 0.0 else -1.0
    sigma_n1 = sigma_trial - sign_trial * E * delta_gamma
    eps_p_n1 = eps_p_n + delta_gamma
    return sigma_n1, eps_p_n1


# ---------------------------------------------------------------------------
# Algorithmic (consistent) tangent for Newton step in 1-D
# ---------------------------------------------------------------------------

def _tangent_1d(
    sigma_trial: float,
    eps_p_n: float,
    E: float,
    sigma_y0: float,
    H: float,
) -> float:
    """
    Algorithmic tangent modulus for the current state.
    Returns E_t = E (elastic) or E·H/(E+H) (plastic).
    """
    sigma_y_n = sigma_y0 + H * eps_p_n
    if abs(sigma_trial) <= sigma_y_n:
        return E
    else:
        if E + H == 0.0:
            return 0.0
        return E * H / (E + H)


# ---------------------------------------------------------------------------
# Uniaxial bar: prescribed displacement-controlled or force-controlled steps
# ---------------------------------------------------------------------------

def run_nonlinear_bar(
    E: float,
    sigma_y0: float,
    H: float,
    load_steps: list[float],
    *,
    max_iter: int = 50,
    tol: float = 1e-10,
    force_controlled: bool = False,
) -> dict[str, Any]:
    """
    Simulate a uniaxial bar through a sequence of load steps using
    incremental loading + Newton iteration.

    Parameters
    ----------
    E          : Young's modulus  [Pa]
    sigma_y0   : initial yield stress [Pa]
    H          : isotropic-hardening modulus [Pa] (≥ 0)
    load_steps : list of target values per step.
                 If force_controlled=False → prescribed total strains.
                 If force_controlled=True  → prescribed total stresses (forces/area).
    max_iter   : maximum Newton iterations per step
    tol        : relative residual tolerance for convergence
    force_controlled : whether load_steps are stress targets (True) or strain targets (False)

    Returns
    -------
    dict  ok, strain, stress, plastic_strain [, reason]
    """
    if E <= 0:
        return {"ok": False, "reason": "E must be positive"}
    if sigma_y0 <= 0:
        return {"ok": False, "reason": "sigma_y0 must be positive"}
    if H < 0:
        return {"ok": False, "reason": "H must be non-negative"}

    strains: list[float] = []
    stresses: list[float] = []
    plastic_strains: list[float] = []

    eps_n = 0.0
    sigma_n = 0.0
    eps_p_n = 0.0

    for step_idx, target in enumerate(load_steps):
        if force_controlled:
            # Newton loop: find Δε such that σ(ε_n + Δε) = σ_target
            sigma_target = target
            delta_eps = (sigma_target - sigma_n) / E  # initial guess (elastic)

            converged = False
            for _it in range(max_iter):
                sigma_trial_it = sigma_n + E * delta_eps
                sigma_new, eps_p_new = _return_map_1d(
                    sigma_n, eps_p_n, delta_eps, E, sigma_y0, H
                )
                residual = sigma_new - sigma_target
                tol_abs = tol * max(abs(sigma_target), sigma_y0)
                if abs(residual) <= tol_abs:
                    converged = True
                    break
                # Consistent tangent: dσ/d(Δε)
                sigma_y_n = sigma_y0 + H * eps_p_n
                if abs(sigma_trial_it) <= sigma_y_n:
                    Et = E
                else:
                    Et = E * H / (E + H) if (E + H) != 0.0 else 0.0
                if Et == 0.0:
                    # Perfect plasticity — stress cannot exceed yield; check feasibility
                    sigma_y_now = sigma_y0 + H * eps_p_new
                    if abs(sigma_target) > sigma_y_now + tol * sigma_y0:
                        return {
                            "ok": False,
                            "reason": (
                                f"step {step_idx}: target stress {sigma_target:.4g} exceeds "
                                f"yield in perfect-plasticity regime (H=0)"
                            ),
                        }
                    converged = True
                    break
                delta_eps -= residual / Et

            if not converged:
                return {
                    "ok": False,
                    "reason": (
                        f"Newton did not converge at load step {step_idx} "
                        f"(target={target:.4g}, residual={residual:.3e})"
                    ),
                }
            # Accept
            eps_n = eps_n + delta_eps
            eps_p_n = eps_p_new
            sigma_n = sigma_new

        else:
            # Strain-controlled — single return-mapping step (always converges)
            delta_eps = target - eps_n
            sigma_new, eps_p_new = _return_map_1d(
                sigma_n, eps_p_n, delta_eps, E, sigma_y0, H
            )
            eps_n = target
            sigma_n = sigma_new
            eps_p_n = eps_p_new

        strains.append(eps_n)
        stresses.append(sigma_n)
        plastic_strains.append(eps_p_n)

    return {
        "ok": True,
        "strain": strains,
        "stress": stresses,
        "plastic_strain": plastic_strains,
    }


# ---------------------------------------------------------------------------
# Small-strain truss: 2-node bar element with axial plasticity
# ---------------------------------------------------------------------------

def run_truss_plastic(
    nodes: list[tuple[float, float]],
    elements: list[tuple[int, int]],
    E: float,
    area: float,
    sigma_y0: float,
    H: float,
    load_steps: list[dict],
    *,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> dict[str, Any]:
    """
    Incremental nonlinear analysis of a 2-D pin-jointed truss with J2
    isotropic-hardening plasticity in each bar element.

    Parameters
    ----------
    nodes      : list of (x, y) coordinates  [m]
    elements   : list of (node_i, node_j) index pairs  (0-based)
    E          : Young's modulus [Pa] (uniform)
    area       : cross-sectional area [m²] (uniform)
    sigma_y0   : initial yield stress [Pa]
    H          : hardening modulus [Pa]
    load_steps : list of load-step dicts, each:
                    { "forces": { node_index: [Fx, Fy], ... },
                      "fixed_dofs": [ dof_index, ... ] }   (only first step used for BCs)

    Returns
    -------
    dict  ok, history (list of per-step result dicts), [reason]

    Each per-step result contains:
        step        int
        displacements  list[float]   global DOF vector
        element_stress list[float]   axial stress per element
        element_plastic_strain list[float]
    """
    if E <= 0:
        return {"ok": False, "reason": "E must be positive"}
    if area <= 0:
        return {"ok": False, "reason": "area must be positive"}
    if sigma_y0 <= 0:
        return {"ok": False, "reason": "sigma_y0 must be positive"}
    if H < 0:
        return {"ok": False, "reason": "H must be non-negative"}
    if not nodes:
        return {"ok": False, "reason": "nodes must be non-empty"}
    if not elements:
        return {"ok": False, "reason": "elements must be non-empty"}
    if not load_steps:
        return {"ok": False, "reason": "load_steps must be non-empty"}

    n_nodes = len(nodes)
    n_dofs = 2 * n_nodes
    n_elem = len(elements)

    # Unpack fixed DOFs from first step
    fixed_dofs: set[int] = set(load_steps[0].get("fixed_dofs", []))

    # State per element
    sigma_e = [0.0] * n_elem    # axial stress
    eps_p_e = [0.0] * n_elem    # accumulated plastic strain
    # Displacements
    u = [0.0] * n_dofs

    history = []

    # Element geometry helpers
    def _elem_geom(e_idx):
        ni, nj = elements[e_idx]
        xi, yi = nodes[ni]
        xj, yj = nodes[nj]
        dx = xj - xi
        dy = yj - yi
        L = (dx**2 + dy**2) ** 0.5
        if L < 1e-14:
            return None
        c = dx / L
        s = dy / L
        return L, c, s, ni, nj

    # Axial strain from global displacements
    def _axial_strain(e_idx, u_vec):
        g = _elem_geom(e_idx)
        if g is None:
            return 0.0
        L, c, s, ni, nj = g
        ux_i = u_vec[2 * ni]
        uy_i = u_vec[2 * ni + 1]
        ux_j = u_vec[2 * nj]
        uy_j = u_vec[2 * nj + 1]
        return (c * (ux_j - ux_i) + s * (uy_j - uy_i)) / L

    # Internal force vector
    def _internal_forces(u_vec, sigma_vec):
        f_int = [0.0] * n_dofs
        for e_idx in range(n_elem):
            g = _elem_geom(e_idx)
            if g is None:
                continue
            L, c, s, ni, nj = g
            sigma = sigma_vec[e_idx]
            f = sigma * area
            # Local → global
            f_int[2 * ni]     -= f * c
            f_int[2 * ni + 1] -= f * s
            f_int[2 * nj]     += f * c
            f_int[2 * nj + 1] += f * s
        return f_int

    # Consistent tangent stiffness matrix (assembled)
    def _stiffness(u_vec, sigma_vec, eps_p_vec):
        K = [[0.0] * n_dofs for _ in range(n_dofs)]
        for e_idx in range(n_elem):
            g = _elem_geom(e_idx)
            if g is None:
                continue
            L, c, s, ni, nj = g
            # Compute trial stress to determine tangent modulus
            eps_ax = _axial_strain(e_idx, u_vec)
            sigma_trial = E * eps_ax  # total (used to decide tangent only)
            sigma_y_n = sigma_y0 + H * eps_p_vec[e_idx]
            if abs(sigma_trial) <= sigma_y_n:
                Et = E
            else:
                Et = E * H / (E + H) if (E + H) != 0.0 else 0.0
            k = Et * area / L
            # DOF indices: [2ni, 2ni+1, 2nj, 2nj+1]
            dofs = [2 * ni, 2 * ni + 1, 2 * nj, 2 * nj + 1]
            local = [c * c, c * s, -c * c, -c * s,
                     c * s, s * s, -c * s, -s * s,
                     -c * c, -c * s, c * c, c * s,
                     -c * s, -s * s, c * s, s * s]
            for i_loc in range(4):
                for j_loc in range(4):
                    K[dofs[i_loc]][dofs[j_loc]] += k * local[i_loc * 4 + j_loc]
        return K

    # Apply boundary conditions (zero rows/cols → identity diagonal)
    def _apply_bcs(K, f_ext, f_int):
        r = [f_ext[i] - f_int[i] for i in range(n_dofs)]
        for d in fixed_dofs:
            for j in range(n_dofs):
                K[d][j] = 0.0
                K[j][d] = 0.0
            K[d][d] = 1.0
            r[d] = 0.0
        return K, r

    # Solve Kx = r via Gaussian elimination (small systems, no heavy deps)
    def _solve(K, r):
        n = len(r)
        # Augmented matrix
        A = [row[:] + [r[i]] for i, row in enumerate(K)]
        for col in range(n):
            # Pivot
            max_row = col
            max_val = abs(A[col][col])
            for row in range(col + 1, n):
                if abs(A[row][col]) > max_val:
                    max_val = abs(A[row][col])
                    max_row = row
            A[col], A[max_row] = A[max_row], A[col]
            pivot = A[col][col]
            if abs(pivot) < 1e-15:
                return None  # singular
            for row in range(col + 1, n):
                factor = A[row][col] / pivot
                for j in range(col, n + 1):
                    A[row][j] -= factor * A[col][j]
        # Back-substitution
        x = [0.0] * n
        for i in range(n - 1, -1, -1):
            x[i] = A[i][n]
            for j in range(i + 1, n):
                x[i] -= A[i][j] * x[j]
            x[i] /= A[i][i]
        return x

    for step_idx, step in enumerate(load_steps):
        # Build external force vector
        f_ext = [0.0] * n_dofs
        for node_idx, fvec in step.get("forces", {}).items():
            node_idx = int(node_idx)
            f_ext[2 * node_idx]     += fvec[0]
            f_ext[2 * node_idx + 1] += fvec[1]

        # Newton-Raphson loop
        sigma_trial_e = sigma_e[:]
        eps_p_trial_e = eps_p_e[:]
        u_trial = u[:]

        converged = False
        residual_norm = float("inf")

        for _it in range(max_iter):
            # Compute internal forces from current trial state
            f_int = _internal_forces(u_trial, sigma_trial_e)
            r = [f_ext[i] - f_int[i] for i in range(n_dofs)]
            # Zero residual at fixed DOFs
            for d in fixed_dofs:
                r[d] = 0.0

            residual_norm = sum(ri**2 for ri in r) ** 0.5
            f_ext_norm = sum(fi**2 for fi in f_ext) ** 0.5 or 1.0
            rel_res = residual_norm / f_ext_norm

            if rel_res <= tol:
                converged = True
                break

            # Assemble tangent stiffness
            K = _stiffness(u_trial, sigma_trial_e, eps_p_trial_e)
            K, r_bc = _apply_bcs(K, f_ext, f_int)

            delta_u = _solve(K, r_bc)
            if delta_u is None:
                return {
                    "ok": False,
                    "reason": (
                        f"step {step_idx}: singular stiffness matrix "
                        f"(check boundary conditions)"
                    ),
                }

            # Update trial displacements
            u_trial = [u_trial[i] + delta_u[i] for i in range(n_dofs)]

            # Update element stresses via return mapping
            for e_idx in range(n_elem):
                eps_ax_new = _axial_strain(e_idx, u_trial)
                eps_ax_old = _axial_strain(e_idx, u)
                delta_eps_ax = eps_ax_new - eps_ax_old
                sigma_new, eps_p_new = _return_map_1d(
                    sigma_e[e_idx], eps_p_e[e_idx],
                    delta_eps_ax, E, sigma_y0, H,
                )
                sigma_trial_e[e_idx] = sigma_new
                eps_p_trial_e[e_idx] = eps_p_new

        if not converged:
            return {
                "ok": False,
                "reason": (
                    f"Newton did not converge at truss load step {step_idx} "
                    f"(rel_residual={rel_res:.3e})"
                ),
            }

        # Accept step
        u = u_trial[:]
        sigma_e = sigma_trial_e[:]
        eps_p_e = eps_p_trial_e[:]

        history.append({
            "step": step_idx,
            "displacements": u[:],
            "element_stress": sigma_e[:],
            "element_plastic_strain": eps_p_e[:],
        })

    return {"ok": True, "history": history}
