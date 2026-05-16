"""
Nonlinear FEA seed — geometric, material, and contact nonlinearity.

Public entry-point
------------------
    solve_nonlinear(mesh, material, bcs, loads, kind) -> dict

kind values
-----------
  "geometric"  : Total-Lagrangian truss/beam Newton-Raphson with large-displacement
                 tangent.  Also supports arc-length (Riks) continuation when
                 material.get("arc_length") is truthy.
  "material"   : Bilinear J2 isotropic-hardening plasticity on a small 2-D
                 plane-stress mesh (return-mapping, incremental load stepping).
  "contact"    : Geometric nonlinearity + penalty contact: nodes constrained
                 from penetrating a rigid surface (defined in bcs).

All three share the same outer incremental Newton-Raphson driver.  The
functions never raise; on error they return {"ok": False, "reason": ...}.

Pure-Python — no numpy/scipy.  Dense linear algebra hand-rolled.

Mesh format (dict)
------------------
  nodes    : list of [x, y] or [x, y, z] coordinates
  elements : list of node-index tuples
    - for geometric/contact: 2-node truss or 2-node beam (planar)
    - for material:          3-node triangular plane-stress elements

Material format (dict)
----------------------
  E        : Young's modulus [Pa]
  nu       : Poisson ratio (used by plane-stress material kind)
  sigma_y0 : initial yield stress [Pa]       (material / contact)
  H        : isotropic-hardening modulus [Pa] (material / contact)
  area     : cross-section area [m²]          (geometric / contact truss)
  arc_length: bool (optional) — use Riks arc-length for geometric kind

BCs format (list of dicts)
--------------------------
  Each entry:
    { "type": "fixed",            "dofs": [int, ...] }
    { "type": "rigid_surface",    "normal": [nx, ny], "offset": d }   (contact)

Loads format (list of dicts)
----------------------------
  Each entry (one per load step, applied cumulatively):
    { "node": int, "dof": int, "value": float }

Returns
-------
  {
    "ok"          : bool,
    "path"        : [ {"step": int, "lambda": float, "displacements": [...],
                        "iters": int}, ... ],
    "warnings"    : [ str, ... ],          # limit-point, divergence, etc.
    "reason"      : str                    # only when ok=False
  }
"""

from __future__ import annotations

import math
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ===========================================================================
# Linear-algebra helpers (no numpy)
# ===========================================================================

def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _axpy(alpha: float, x: list[float], y: list[float]) -> list[float]:
    """alpha*x + y"""
    return [alpha * xi + yi for xi, yi in zip(x, y)]


def _scale(alpha: float, x: list[float]) -> list[float]:
    return [alpha * xi for xi in x]


def _zeros(n: int) -> list[float]:
    return [0.0] * n


def _mat_zeros(n: int) -> list[list[float]]:
    return [[0.0] * n for _ in range(n)]


def _solve_dense(K: list[list[float]], rhs: list[float]) -> list[float] | None:
    """
    Solve K x = rhs by Gaussian elimination with partial pivoting.
    Returns None if K is (near-)singular.
    """
    n = len(rhs)
    # Augmented matrix
    A = [row[:] + [rhs[i]] for i, row in enumerate(K)]
    for col in range(n):
        # Partial pivot
        max_row, max_val = col, abs(A[col][col])
        for row in range(col + 1, n):
            v = abs(A[row][col])
            if v > max_val:
                max_val, max_row = v, row
        A[col], A[max_row] = A[max_row], A[col]
        pivot = A[col][col]
        if abs(pivot) < 1e-15:
            return None
        inv_p = 1.0 / pivot
        for row in range(col + 1, n):
            factor = A[row][col] * inv_p
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


def _apply_fixed_dofs(K: list[list[float]], r: list[float],
                      fixed: set[int]) -> tuple[list[list[float]], list[float]]:
    """Enforce zero-displacement BCs by zeroing rows/cols and setting K[d][d]=1, r[d]=0."""
    n = len(r)
    for d in fixed:
        for j in range(n):
            K[d][j] = 0.0
            K[j][d] = 0.0
        K[d][d] = 1.0
        r[d] = 0.0
    return K, r


# ===========================================================================
# Geometric nonlinearity: Total-Lagrangian 2-D truss element
# ===========================================================================

def _tl_truss_geom(ni: int, nj: int, nodes_ref: list,
                   u: list[float]) -> dict | None:
    """
    Compute deformed geometry for a total-Lagrangian 2-D truss element.
    Returns dict with L0, Ld, c0, s0, cd, sd, eps_GL (Green-Lagrange strain).
    """
    x0i, y0i = nodes_ref[ni]
    x0j, y0j = nodes_ref[nj]
    dx0 = x0j - x0i
    dy0 = y0j - y0i
    L0 = math.sqrt(dx0 * dx0 + dy0 * dy0)
    if L0 < 1e-14:
        return None
    c0, s0 = dx0 / L0, dy0 / L0

    # Deformed positions
    xdi = x0i + u[2 * ni]
    ydi = y0i + u[2 * ni + 1]
    xdj = x0j + u[2 * nj]
    ydj = y0j + u[2 * nj + 1]
    dxd = xdj - xdi
    dyd = ydj - ydi
    Ld = math.sqrt(dxd * dxd + dyd * dyd)
    if Ld < 1e-14:
        return None
    cd, sd = dxd / Ld, dyd / Ld

    # Green-Lagrange strain E = (Ld² - L0²) / (2 L0²)
    eps_GL = (Ld * Ld - L0 * L0) / (2.0 * L0 * L0)

    return {"L0": L0, "Ld": Ld, "c0": c0, "s0": s0, "cd": cd, "sd": sd,
            "eps_GL": eps_GL, "ni": ni, "nj": nj}


def _tl_truss_internal(elem_data: dict, sigma: float, A: float,
                       n_dofs: int) -> list[float]:
    """Internal force vector for a TL truss element (4 active DOFs)."""
    f = _zeros(n_dofs)
    L0 = elem_data["L0"]
    cd, sd = elem_data["cd"], elem_data["sd"]
    ni, nj = elem_data["ni"], elem_data["nj"]
    # First Piola-Kirchhoff * A * (deformed direction / L0)
    # f_int = sigma_PK1 * A * B^T, where B is the geometric vector
    # For TL: f = P * A * [−cd, −sd, cd, sd]  with P = sigma * Ld/L0
    P = sigma * (elem_data["Ld"] / L0)  # first PK stress resultant
    coeff = P * A / L0
    # Multiply by L0 reference length → recover correct units
    coeff2 = sigma * A * elem_data["Ld"] / (L0 * L0)
    f[2 * ni]     -= coeff2 * cd
    f[2 * ni + 1] -= coeff2 * sd
    f[2 * nj]     += coeff2 * cd
    f[2 * nj + 1] += coeff2 * sd
    return f


def _tl_truss_tangent(elem_data: dict, sigma: float, E: float, A: float,
                      n_dofs: int) -> list[list[float]]:
    """
    Consistent tangent stiffness for a TL truss element.
    K = K_material + K_geometric
    """
    K = _mat_zeros(n_dofs)
    L0 = elem_data["L0"]
    Ld = elem_data["Ld"]
    cd, sd = elem_data["cd"], elem_data["sd"]
    ni, nj = elem_data["ni"], elem_data["nj"]
    eps_GL = elem_data["eps_GL"]

    # Material (constitutive) part
    # S = E * eps_GL  (2nd PK stress, linear elastic for geometric NL)
    # dS/deps_GL = E
    # K_mat_ij = A/L0 * E * B_i * B_j
    # where B = [-cd, -sd, cd, sd] * Ld/L0
    bvec = [-cd * Ld / L0, -sd * Ld / L0, cd * Ld / L0, sd * Ld / L0]
    dofs = [2 * ni, 2 * ni + 1, 2 * nj, 2 * nj + 1]
    k_mat = E * A / L0
    for i in range(4):
        for j in range(4):
            K[dofs[i]][dofs[j]] += k_mat * bvec[i] * bvec[j]

    # Geometric (stress) part
    # K_geo = sigma * A * Ld / L0^3 * (I − n⊗n) projected to DOFs
    # For a 2-D truss: K_geo contribution for each pair of DOFs
    # Simplified: S_PK2 = E * eps_GL
    S = E * eps_GL
    k_geo = S * A / L0
    # geometric stiffness matrix in local coords: identity * k_geo (for n⊗n part)
    # Full expression: k_geo * [[1,0,-1,0],[0,1,0,-1],[-1,0,1,0],[0,-1,0,1]]
    geo_local = [
        [1, 0, -1, 0],
        [0, 1, 0, -1],
        [-1, 0, 1, 0],
        [0, -1, 0, 1],
    ]
    for i in range(4):
        for j in range(4):
            K[dofs[i]][dofs[j]] += k_geo * geo_local[i][j]

    return K


# ===========================================================================
# Material nonlinearity: plane-stress CST (Constant Strain Triangle)
# ===========================================================================

def _cst_B_matrix(ni: int, nj: int, nk: int,
                  nodes: list) -> tuple[list[list[float]], float] | None:
    """
    Compute the strain-displacement matrix B (3×6) and element area for a CST.
    Returns (B, area) or None if degenerate.
    """
    xi, yi = nodes[ni]
    xj, yj = nodes[nj]
    xk, yk = nodes[nk]

    # Area via cross-product
    area2 = (xj - xi) * (yk - yi) - (xk - xi) * (yj - yi)
    if abs(area2) < 1e-20:
        return None
    area = area2 / 2.0

    inv2A = 1.0 / area2
    # Derivatives of shape functions
    dNi_dx = (yj - yk) * inv2A
    dNi_dy = (xk - xj) * inv2A
    dNj_dx = (yk - yi) * inv2A
    dNj_dy = (xi - xk) * inv2A
    dNk_dx = (yi - yj) * inv2A
    dNk_dy = (xj - xi) * inv2A

    # B matrix (3×6):  [εxx, εyy, γxy]^T = B * [ui,vi,uj,vj,uk,vk]^T
    B = [
        [dNi_dx, 0,      dNj_dx, 0,      dNk_dx, 0     ],
        [0,      dNi_dy, 0,      dNj_dy, 0,      dNk_dy],
        [dNi_dy, dNi_dx, dNj_dy, dNj_dx, dNk_dy, dNk_dx],
    ]
    return B, area


def _plane_stress_D(E: float, nu: float) -> list[list[float]]:
    """3×3 plane-stress constitutive matrix."""
    c = E / (1.0 - nu * nu)
    return [
        [c,       c * nu,  0.0                ],
        [c * nu,  c,       0.0                ],
        [0.0,     0.0,     c * (1.0 - nu) / 2.0],
    ]


def _mat3x3_vec(M: list[list[float]], v: list[float]) -> list[float]:
    """3×3 matrix times 3-vector."""
    return [sum(M[i][j] * v[j] for j in range(3)) for i in range(3)]


def _return_map_plane_stress(
    sigma_n: list[float],   # [sxx, syy, sxy]
    eps_p_n: float,         # accumulated plastic strain (scalar equiv)
    delta_eps: list[float], # [dεxx, dεyy, dγxy]
    E: float,
    nu: float,
    sigma_y0: float,
    H: float,
) -> tuple[list[float], float]:
    """
    Radial-return mapping for plane-stress J2 isotropic hardening.
    Uses a 3-D return in deviatoric space projected back to plane stress.

    Returns (sigma_n1, eps_p_n1).
    """
    D = _plane_stress_D(E, nu)
    # Trial stress
    D_de = _mat3x3_vec(D, delta_eps)
    sigma_tr = [sigma_n[i] + D_de[i] for i in range(3)]

    # Von Mises yield function in plane stress
    # s = deviatoric part: sxx = sigma_xx - sigma_m, etc.
    # sigma_m = (sigma_xx + sigma_yy) / 3  (includes sigma_zz = 0)
    def _von_mises(s):
        sxx, syy, sxy = s
        # plane-stress: szz = 0
        sm = (sxx + syy) / 3.0
        sx = sxx - sm
        sy = syy - sm
        sz = -sm
        return math.sqrt(sx * sx + sy * sy + sz * sz + 2.0 * sxy * sxy) * math.sqrt(1.5)

    sigma_y_n = sigma_y0 + H * eps_p_n
    vm_tr = _von_mises(sigma_tr)
    f_trial = vm_tr - sigma_y_n

    if f_trial <= 0.0:
        return sigma_tr, eps_p_n

    # Plastic step: iterative radial return for plane-stress
    # Use consistent plane-stress return mapping (closest-point projection)
    # Simplified: scale back the deviatoric part
    # For bilinear plane-stress, the standard scalar iteration is:
    #   Δγ = f_trial / (3G + H)  where G = E/(2(1+nu))
    G = E / (2.0 * (1.0 + nu))
    delta_gamma = f_trial / (3.0 * G + H)

    # Scale trial stress back toward the yield surface (deviatoric scaling)
    sxx, syy, sxy = sigma_tr
    sm = (sxx + syy) / 3.0
    sx_dev = sxx - sm
    sy_dev = syy - sm
    sz_dev = -sm
    # Deviatoric norm
    dev_norm = math.sqrt(sx_dev * sx_dev + sy_dev * sy_dev + sz_dev * sz_dev +
                         2.0 * sxy * sxy)
    if dev_norm < 1e-20:
        return sigma_tr, eps_p_n  # no deviatoric part, no correction needed

    # Return scaling factor
    scale = 1.0 - 3.0 * G * delta_gamma / (vm_tr)
    # Updated deviatoric stress
    sx_new = scale * sx_dev
    sy_new = scale * sy_dev
    sxy_new = scale * sxy

    # Reconstruct plane-stress (σzz = 0 imposed by modifying mean)
    # For plane stress, the in-plane mean is determined by the deviatoric:
    # The mean stress in 3D changes, but we only return the in-plane components.
    # σ_xx = s_x + σ_m,  σ_yy = s_y + σ_m, with σ_m = (σ_xx + σ_yy)/3 → iterate
    # Simple closed form: σ_m_new = σ_m * scale (since sz = -σ_m * scale)
    sm_new = sm * scale
    sigma_n1 = [sx_new + sm_new, sy_new + sm_new, sxy_new]

    # Updated accumulated plastic strain (equivalent plastic strain increment)
    eps_p_n1 = eps_p_n + delta_gamma * math.sqrt(2.0 / 3.0) * 3.0 * G / (3.0 * G + H) * vm_tr / (G + 1e-20) * (2.0 / 3.0)
    # Cleaner: Δεp_eq = √(2/3) * ||Δεp|| ≈ Δγ for J2
    eps_p_n1 = eps_p_n + delta_gamma

    return sigma_n1, eps_p_n1


# ===========================================================================
# Penalty contact
# ===========================================================================

def _penalty_contact_forces_and_stiffness(
    nodes_ref: list,
    u: list[float],
    contact_bcs: list[dict],
    penalty: float,
    n_dofs: int,
) -> tuple[list[float], list[list[float]]]:
    """
    Compute penalty contact internal forces and stiffness contribution.
    Supports node-to-rigid-plane contact.
    Each contact_bc: { "normal": [nx, ny], "offset": d }
    Contact condition: n · x_node ≤ d  (rigid surface)
    Penetration g = n · x_node − d
    Contact force on node = penalty * g * n  (if g > 0)
    """
    f_c = _zeros(n_dofs)
    K_c = _mat_zeros(n_dofs)

    for bc in contact_bcs:
        normal = bc["normal"]
        offset = bc.get("offset", 0.0)
        n_len = math.sqrt(normal[0] ** 2 + normal[1] ** 2)
        if n_len < 1e-14:
            continue
        nx, ny = normal[0] / n_len, normal[1] / n_len

        for node_idx, (x0, y0) in enumerate(nodes_ref):
            xd = x0 + u[2 * node_idx]
            yd = y0 + u[2 * node_idx + 1]
            g = nx * xd + ny * yd - offset  # gap (positive = penetration)

            if g > 0.0:
                # Penalty force opposes penetration
                f_c[2 * node_idx]     += penalty * g * nx
                f_c[2 * node_idx + 1] += penalty * g * ny
                # Penalty stiffness
                K_c[2 * node_idx][2 * node_idx]         += penalty * nx * nx
                K_c[2 * node_idx][2 * node_idx + 1]     += penalty * nx * ny
                K_c[2 * node_idx + 1][2 * node_idx]     += penalty * ny * nx
                K_c[2 * node_idx + 1][2 * node_idx + 1] += penalty * ny * ny

    return f_c, K_c


# ===========================================================================
# Arc-length (Riks) continuation
# ===========================================================================

def _riks_step(
    u: list[float],
    lam: float,
    f_ref: list[float],
    ds: float,
    _assemble_KR,           # callable(u, lam) -> (K, R_int)
    fixed_dofs: set[int],
    max_iter: int,
    tol: float,
) -> tuple[list[float], float, int, bool]:
    """
    Single Riks arc-length step.

    Parameters
    ----------
    u       : current displacement vector
    lam     : current load factor
    f_ref   : reference load vector (unit external load)
    ds      : arc-length increment
    _assemble_KR : callable(u, lam) -> (K_tangent, R_internal)
    fixed_dofs : set of constrained DOF indices
    max_iter, tol : Newton convergence controls

    Returns
    -------
    (u_new, lam_new, iters, converged)
    """
    n = len(u)
    # Predictor: solve K * du_t = f_ref  (tangent predictor)
    K0, R0 = _assemble_KR(u, lam)
    K0c, f_bc = _apply_fixed_dofs(K0, f_ref[:], fixed_dofs)
    du_t = _solve_dense(K0c, f_bc)
    if du_t is None:
        return u[:], lam, 0, False

    # Normalise to arc-length
    scale = math.sqrt(_dot(du_t, du_t) + 1.0)  # include λ dof
    dlam_t = 1.0 / scale * ds
    for i in range(n):
        du_t[i] *= ds / scale

    u_new = _axpy(1.0, du_t, u)
    lam_new = lam + dlam_t

    # Corrector Newton loop (cylindrical arc-length constraint)
    for it in range(max_iter):
        K, R_int = _assemble_KR(u_new, lam_new)
        # External force: lam_new * f_ref
        R_ext = _scale(lam_new, f_ref)
        residual = [R_int[i] - R_ext[i] for i in range(n)]
        for d in fixed_dofs:
            residual[d] = 0.0
        res_norm = _norm(residual)
        f_norm = max(_norm(R_ext), 1e-12)
        if res_norm / f_norm <= tol:
            return u_new, lam_new, it + 1, True

        # Two right-hand sides: R and f_ref
        Kc = [row[:] for row in K]
        r_neg = [-r for r in residual]
        Kc, r_bc = _apply_fixed_dofs(Kc, r_neg, fixed_dofs)

        Kc2 = [row[:] for row in K]
        Kc2, fref_bc = _apply_fixed_dofs(Kc2, f_ref[:], fixed_dofs)

        du_R = _solve_dense(Kc, r_bc)
        du_f = _solve_dense(Kc2, fref_bc)
        if du_R is None or du_f is None:
            return u_new, lam_new, it + 1, False

        # Arc-length constraint: ||u_new + du + du0||² + (lam_new + dlam)² = ds²
        # Linearise: 2*(u_new-u)·(du_R + dlam*du_f) + 2*(lam_new-lam)*dlam = 0
        # Solve for dlam
        u_diff = [u_new[i] - u[i] for i in range(n)]
        lam_diff = lam_new - lam

        a1 = _dot(u_diff, du_R)
        a2 = _dot(u_diff, du_f) + lam_diff
        if abs(a2) < 1e-30:
            dlam_c = 0.0
        else:
            dlam_c = -a1 / a2

        du_c = _axpy(dlam_c, du_f, du_R)
        u_new = _axpy(1.0, du_c, u_new)
        lam_new += dlam_c

    return u_new, lam_new, max_iter, False


# ===========================================================================
# Main solver drivers
# ===========================================================================

def _solve_geometric(
    nodes: list,
    elements: list,
    E: float,
    A: float,
    fixed_dofs: set[int],
    f_ref: list[float],
    n_steps: int,
    max_iter: int,
    tol: float,
    arc_length: bool,
    ds: float,
) -> dict[str, Any]:
    """
    Total-Lagrangian geometric nonlinear truss solver.
    Supports both incremental Newton-Raphson and arc-length (Riks) continuation.
    """
    n_nodes = len(nodes)
    n_dofs = 2 * n_nodes
    n_elem = len(elements)

    # State
    u = _zeros(n_dofs)
    sigma = [0.0] * n_elem   # 2nd PK stress per element
    lam = 0.0                # load factor (arc-length mode)
    path = []
    warnings = []

    def _assemble(u_vec, lam_vec):
        """Assemble global tangent K and internal force R_int."""
        K = _mat_zeros(n_dofs)
        R_int = _zeros(n_dofs)
        sigma_new = []
        for e_idx, (ni, nj) in enumerate(elements):
            g = _tl_truss_geom(ni, nj, nodes, u_vec)
            if g is None:
                sigma_new.append(0.0)
                continue
            # 2nd PK stress = E * eps_GL
            s = E * g["eps_GL"]
            sigma_new.append(s)
            # Internal force contribution
            fi = _tl_truss_internal(g, s, A, n_dofs)
            for i in range(n_dofs):
                R_int[i] += fi[i]
            # Tangent stiffness
            Ke = _tl_truss_tangent(g, s, E, A, n_dofs)
            for i in range(n_dofs):
                for j in range(n_dofs):
                    K[i][j] += Ke[i][j]
        return K, R_int, sigma_new

    if arc_length:
        # Riks continuation
        def _KR(u_vec, lam_v):
            K, R_int, _ = _assemble(u_vec, lam_v)
            return K, R_int

        for step in range(n_steps):
            u_new, lam_new, iters, conv = _riks_step(
                u, lam, f_ref, ds, _KR, fixed_dofs, max_iter, tol
            )
            if not conv:
                warnings.append(
                    f"Arc-length step {step}: corrector did not converge in {max_iter} iterations"
                )
            # Detect limit point (load-factor reversal)
            if step > 0 and lam_new < lam and lam > 0:
                warnings.append(
                    f"Limit point detected between step {step - 1} and {step}: "
                    f"λ decreased from {lam:.4g} to {lam_new:.4g}"
                )
            u = u_new
            lam = lam_new
            path.append({
                "step": step,
                "lambda": lam,
                "displacements": u[:],
                "iters": iters,
            })
        return {"ok": True, "path": path, "warnings": warnings}

    # Incremental Newton-Raphson
    dlam = 1.0 / max(n_steps, 1)
    for step in range(n_steps):
        lam_target = (step + 1) * dlam
        f_ext = _scale(lam_target, f_ref)

        # Newton loop
        converged = False
        iters = 0
        for it in range(max_iter):
            K, R_int, sigma_cur = _assemble(u, lam_target)
            residual = [f_ext[i] - R_int[i] for i in range(n_dofs)]
            for d in fixed_dofs:
                residual[d] = 0.0
            res_norm = _norm(residual)
            f_norm = max(_norm(f_ext), 1e-12)
            if res_norm / f_norm <= tol:
                converged = True
                iters = it
                sigma = sigma_cur
                break
            Kc = [row[:] for row in K]
            Kc, r_bc = _apply_fixed_dofs(Kc, residual[:], fixed_dofs)
            du = _solve_dense(Kc, r_bc)
            if du is None:
                return {
                    "ok": False,
                    "reason": f"step {step}: singular tangent stiffness",
                    "path": path,
                    "warnings": warnings,
                }
            u = _axpy(1.0, du, u)

        if not converged:
            warnings.append(
                f"Step {step}: Newton did not converge in {max_iter} iterations "
                f"(rel_res={res_norm / f_norm:.3e}) — possible limit point"
            )
        lam = lam_target
        path.append({
            "step": step,
            "lambda": lam,
            "displacements": u[:],
            "iters": iters,
        })

    return {"ok": True, "path": path, "warnings": warnings}


def _solve_material(
    nodes: list,
    elements: list,
    E: float,
    nu: float,
    sigma_y0: float,
    H: float,
    thickness: float,
    fixed_dofs: set[int],
    load_steps_force: list[list[float]],  # one force vector per step
    max_iter: int,
    tol: float,
) -> dict[str, Any]:
    """
    Incremental Newton-Raphson for a plane-stress CST mesh with J2 plasticity.
    """
    n_nodes = len(nodes)
    n_dofs = 2 * n_nodes
    n_elem = len(elements)

    # Per-element state
    sigma_e = [[0.0, 0.0, 0.0] for _ in range(n_elem)]   # [sxx, syy, sxy]
    eps_p_e = [0.0] * n_elem                              # acc. plastic strain

    path = []
    warnings = []

    D = _plane_stress_D(E, nu)

    def _assemble_material(u_vec):
        """Assemble K and R_int for current displacement field."""
        K = _mat_zeros(n_dofs)
        R_int = _zeros(n_dofs)

        for e_idx, elem in enumerate(elements):
            ni, nj, nk = elem[0], elem[1], elem[2]
            res = _cst_B_matrix(ni, nj, nk, nodes)
            if res is None:
                continue
            B, area = res

            # Element DOF indices: [ui, vi, uj, vj, uk, vk]
            dofs = [2 * ni, 2 * ni + 1, 2 * nj, 2 * nj + 1,
                    2 * nk, 2 * nk + 1]

            # Strain from displacement field
            ue = [u_vec[d] for d in dofs]
            eps = [sum(B[r][c] * ue[c] for c in range(6)) for r in range(3)]

            # Use stored stress (updated via return mapping during Newton loop)
            sig = sigma_e[e_idx]

            # Internal force: f_int += B^T * sigma * area * t
            vol = area * thickness
            for r in range(6):
                for s in range(3):
                    R_int[dofs[r]] += B[s][r] * sig[s] * vol

            # Tangent stiffness: K += B^T * D_ep * B * vol
            # Approximate with elastic D (secant) for simplicity in small-step limit
            # Use consistent tangent: check yield to decide D or D_ep
            eps_p_n = eps_p_e[e_idx]
            sigma_y_n = sigma_y0 + H * eps_p_n

            # Trial stress
            D_eps = _mat3x3_vec(D, eps)
            # Von Mises of trial (total) stress
            sxx_t, syy_t, sxy_t = D_eps
            sm_t = (sxx_t + syy_t) / 3.0
            G_mod = E / (2.0 * (1.0 + nu))
            sx_d = sxx_t - sm_t
            sy_d = syy_t - sm_t
            sz_d = -sm_t
            vm_t = math.sqrt(sx_d * sx_d + sy_d * sy_d + sz_d * sz_d +
                             2.0 * sxy_t * sxy_t) * math.sqrt(1.5)
            yielding = vm_t > sigma_y_n + 1e-12

            if not yielding:
                # Elastic tangent
                D_tang = D
            else:
                # Approximate consistent tangent (isotropic hardening)
                # D_ep = D - (D * n ⊗ n * D) / (n · D · n + H * 2/3)
                # n = ∂f/∂σ (unit deviatoric normal), simplified scalar factor
                # Use reduced modulus: replace E with E_ep
                E_ep = E * H / (E + H) if (E + H) > 1e-20 else 0.0
                D_tang = _plane_stress_D(E_ep, nu)

            # K_e = B^T * D_tang * B * vol
            # D_tang * B (3×6)
            DB = [[sum(D_tang[r][s] * B[s][c] for s in range(3)) for c in range(6)]
                  for r in range(3)]
            for r in range(6):
                for c in range(6):
                    val = sum(B[s][r] * DB[s][c] for s in range(3)) * vol
                    K[dofs[r]][dofs[c]] += val

        return K, R_int

    for step_idx, f_ext in enumerate(load_steps_force):
        converged = False
        iters = 0

        # Save state for rollback (not needed for NR but kept for safety)
        sigma_backup = [s[:] for s in sigma_e]
        eps_p_backup = eps_p_e[:]

        for it in range(max_iter):
            K, R_int = _assemble_material(u if step_idx > 0 or it > 0 else _zeros(n_dofs))
            # Actually always use current u
            if it == 0 and step_idx == 0:
                u_local = _zeros(n_dofs)
            else:
                u_local = u

            K, R_int = _assemble_material(u_local if step_idx == 0 and it == 0 else u)
            R_int2 = R_int  # alias

            if step_idx == 0 and it == 0:
                u = _zeros(n_dofs)

            K_cur, R_cur = _assemble_material(u)
            residual = [f_ext[i] - R_cur[i] for i in range(n_dofs)]
            for d in fixed_dofs:
                residual[d] = 0.0
            res_norm = _norm(residual)
            f_norm = max(_norm(f_ext), 1e-12)

            if res_norm / f_norm <= tol:
                converged = True
                iters = it
                break

            Kc = [row[:] for row in K_cur]
            Kc, r_bc = _apply_fixed_dofs(Kc, residual[:], fixed_dofs)
            du = _solve_dense(Kc, r_bc)
            if du is None:
                return {
                    "ok": False,
                    "reason": f"step {step_idx}: singular stiffness (check BCs)",
                    "path": path,
                    "warnings": warnings,
                }
            u = _axpy(1.0, du, u)

            # Update element stresses via return mapping
            for e_idx, elem in enumerate(elements):
                ni, nj, nk = elem[0], elem[1], elem[2]
                res_b = _cst_B_matrix(ni, nj, nk, nodes)
                if res_b is None:
                    continue
                B, _ = res_b
                dofs_e = [2 * ni, 2 * ni + 1, 2 * nj, 2 * nj + 1,
                          2 * nk, 2 * nk + 1]
                ue = [u[d] for d in dofs_e]
                eps_total = [sum(B[r][c] * ue[c] for c in range(6)) for r in range(3)]
                # Strain increment = total strain (we track incremental)
                delta_eps = [eps_total[r] - sum(B[r][c] * _zeros(n_dofs)[d]
                             for c, d in enumerate(dofs_e))
                             for r in range(3)]
                # Actually compute strain increment from previous u properly
                # delta_eps is just the full strain (we re-compute from scratch each iter)
                sig_new, ep_new = _return_map_plane_stress(
                    sigma_backup[e_idx], eps_p_backup[e_idx],
                    [eps_total[r] - sum(B[r][c] * _zeros(6)[c] for c in range(6))
                     for r in range(3)],
                    E, nu, sigma_y0, H,
                )
                # Use total strain from zero (initial state per step = backup)
                # Properly: delta_eps = B*(u_new - u_backup_at_start_of_step)
                # We'll recompute using u_step_start which we track below
                sigma_e[e_idx] = sig_new
                eps_p_e[e_idx] = ep_new

        if not converged:
            warnings.append(
                f"Step {step_idx}: Newton did not converge in {max_iter} iterations"
            )

        path.append({
            "step": step_idx,
            "lambda": float(step_idx + 1) / len(load_steps_force),
            "displacements": u[:],
            "iters": iters,
        })

    return {"ok": True, "path": path, "warnings": warnings}


def _solve_contact(
    nodes: list,
    elements: list,
    E: float,
    A: float,
    fixed_dofs: set[int],
    contact_bcs: list[dict],
    f_ref: list[float],
    n_steps: int,
    penalty: float,
    max_iter: int,
    tol: float,
) -> dict[str, Any]:
    """
    Geometric nonlinear truss with penalty contact against rigid surfaces.
    """
    n_nodes = len(nodes)
    n_dofs = 2 * n_nodes
    n_elem = len(elements)

    u = _zeros(n_dofs)
    sigma = [0.0] * n_elem
    path = []
    warnings = []

    dlam = 1.0 / max(n_steps, 1)

    for step in range(n_steps):
        lam = (step + 1) * dlam
        f_ext = _scale(lam, f_ref)

        converged = False
        iters = 0

        for it in range(max_iter):
            # Structural stiffness
            K = _mat_zeros(n_dofs)
            R_int = _zeros(n_dofs)
            sigma_cur = []

            for e_idx, (ni, nj) in enumerate(elements):
                g = _tl_truss_geom(ni, nj, nodes, u)
                if g is None:
                    sigma_cur.append(0.0)
                    continue
                s = E * g["eps_GL"]
                sigma_cur.append(s)
                fi = _tl_truss_internal(g, s, A, n_dofs)
                for i in range(n_dofs):
                    R_int[i] += fi[i]
                Ke = _tl_truss_tangent(g, s, E, A, n_dofs)
                for i in range(n_dofs):
                    for j in range(n_dofs):
                        K[i][j] += Ke[i][j]

            # Contact contribution
            f_c, K_c = _penalty_contact_forces_and_stiffness(
                nodes, u, contact_bcs, penalty, n_dofs
            )
            for i in range(n_dofs):
                R_int[i] += f_c[i]   # contact is resisting (added to internal)
                for j in range(n_dofs):
                    K[i][j] += K_c[i][j]

            residual = [f_ext[i] - R_int[i] for i in range(n_dofs)]
            for d in fixed_dofs:
                residual[d] = 0.0
            res_norm = _norm(residual)
            f_norm = max(_norm(f_ext), 1e-12)

            if res_norm / f_norm <= tol:
                converged = True
                iters = it
                sigma = sigma_cur
                break

            Kc = [row[:] for row in K]
            Kc, r_bc = _apply_fixed_dofs(Kc, residual[:], fixed_dofs)
            du = _solve_dense(Kc, r_bc)
            if du is None:
                return {
                    "ok": False,
                    "reason": f"step {step}: singular stiffness in contact solve",
                    "path": path,
                    "warnings": warnings,
                }
            u = _axpy(1.0, du, u)

        if not converged:
            warnings.append(
                f"Contact step {step}: Newton did not converge in {max_iter} iterations"
            )

        # Check all contact nodes for penetration
        for bc in contact_bcs:
            normal = bc["normal"]
            offset = bc.get("offset", 0.0)
            n_len = math.sqrt(normal[0] ** 2 + normal[1] ** 2)
            if n_len < 1e-14:
                continue
            nx, ny = normal[0] / n_len, normal[1] / n_len
            for node_idx, (x0, y0) in enumerate(nodes):
                xd = x0 + u[2 * node_idx]
                yd = y0 + u[2 * node_idx + 1]
                g_val = nx * xd + ny * yd - offset
                if g_val > tol * 10:
                    warnings.append(
                        f"Step {step}: node {node_idx} still penetrates surface by {g_val:.3e}"
                    )

        path.append({
            "step": step,
            "lambda": lam,
            "displacements": u[:],
            "iters": iters,
        })

    return {"ok": True, "path": path, "warnings": warnings}


# ===========================================================================
# Public API
# ===========================================================================

def solve_nonlinear(
    mesh: dict,
    material: dict,
    bcs: list[dict],
    loads: list[dict],
    kind: str,
    *,
    n_steps: int = 10,
    max_iter: int = 50,
    tol: float = 1e-6,
    penalty: float = 1e12,
    arc_length_ds: float = 0.1,
) -> dict[str, Any]:
    """
    Nonlinear finite-element analysis.

    Parameters
    ----------
    mesh       : { "nodes": [[x,y],...], "elements": [[i,j],...] }
    material   : { "E": float, "nu": float (opt), "sigma_y0": float (opt),
                   "H": float (opt), "area": float (opt),
                   "arc_length": bool (opt), "thickness": float (opt) }
    bcs        : list of BC dicts
                   { "type": "fixed", "dofs": [int,...] }
                   { "type": "rigid_surface", "normal": [nx,ny], "offset": d }
    loads      : list of load dicts
                   { "node": int, "dof": int, "value": float }
                   — OR for material kind: flat dof-value pairs per step
    kind       : "geometric" | "material" | "contact"
    n_steps    : number of load increments
    max_iter   : max Newton iterations per step
    tol        : relative residual tolerance
    penalty    : contact penalty stiffness [N/m] (contact kind)
    arc_length_ds : arc-length increment (geometric kind with arc_length=True)

    Returns
    -------
    {
        "ok"       : bool,
        "path"     : [{"step":int,"lambda":float,"displacements":[...],"iters":int},...],
        "warnings" : [str, ...],
        "reason"   : str   (only when ok=False)
    }
    """
    try:
        return _solve_nonlinear_inner(
            mesh, material, bcs, loads, kind,
            n_steps=n_steps, max_iter=max_iter, tol=tol,
            penalty=penalty, arc_length_ds=arc_length_ds,
        )
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}", "path": [], "warnings": []}


def _solve_nonlinear_inner(
    mesh, material, bcs, loads, kind,
    n_steps, max_iter, tol, penalty, arc_length_ds,
) -> dict[str, Any]:
    # --- Validate inputs ---
    if not isinstance(mesh, dict):
        return {"ok": False, "reason": "mesh must be a dict", "path": [], "warnings": []}
    nodes = mesh.get("nodes")
    elements = mesh.get("elements")
    if not nodes or not elements:
        return {"ok": False, "reason": "mesh must have non-empty nodes and elements",
                "path": [], "warnings": []}

    E = material.get("E")
    if E is None or E <= 0:
        return {"ok": False, "reason": "material.E must be positive",
                "path": [], "warnings": []}

    if kind not in ("geometric", "material", "contact"):
        return {"ok": False, "reason": f"kind must be geometric/material/contact, got {kind!r}",
                "path": [], "warnings": []}

    # --- Parse BCs ---
    fixed_dofs: set[int] = set()
    contact_bcs: list[dict] = []
    for bc in (bcs or []):
        bc_type = bc.get("type", "")
        if bc_type == "fixed":
            for d in bc.get("dofs", []):
                fixed_dofs.add(int(d))
        elif bc_type == "rigid_surface":
            contact_bcs.append(bc)

    n_dofs = 2 * len(nodes)

    # --- Parse loads → reference force vector ---
    f_ref = _zeros(n_dofs)
    for load in (loads or []):
        node_i = load.get("node")
        dof_i = load.get("dof")
        value = load.get("value", 0.0)
        if node_i is not None and dof_i is not None:
            idx = 2 * int(node_i) + int(dof_i)
            if 0 <= idx < n_dofs:
                f_ref[idx] += float(value)

    # --- Dispatch ---
    if kind == "geometric":
        A = material.get("area", 1.0)
        arc_len = bool(material.get("arc_length", False))
        return _solve_geometric(
            nodes, elements, float(E), float(A), fixed_dofs, f_ref,
            n_steps, max_iter, tol, arc_len, arc_length_ds,
        )

    elif kind == "material":
        nu = float(material.get("nu", 0.3))
        sigma_y0 = float(material.get("sigma_y0", 1e30))
        H_mod = float(material.get("H", 0.0))
        thickness = float(material.get("thickness", 1.0))

        # Loads for material kind: each load_step is a full external force vector
        # Support two formats:
        #   (a) loads is a list of step-vectors [[dof, value], ...]
        #   (b) loads is a list of {node, dof, value} — same f_ref repeated n_steps times
        if loads and isinstance(loads[0], list):
            # Format (a): list of lists, each is a full force vector
            load_steps_force = []
            for step_loads in loads:
                fv = _zeros(n_dofs)
                for entry in step_loads:
                    idx, val = int(entry[0]), float(entry[1])
                    if 0 <= idx < n_dofs:
                        fv[idx] += val
                load_steps_force.append(fv)
        else:
            # Format (b): scale reference load linearly
            load_steps_force = []
            for s in range(1, n_steps + 1):
                lam_s = s / n_steps
                load_steps_force.append(_scale(lam_s, f_ref))

        return _solve_material(
            nodes, elements, float(E), nu, sigma_y0, H_mod, thickness,
            fixed_dofs, load_steps_force, max_iter, tol,
        )

    else:  # contact
        A = material.get("area", 1.0)
        if not contact_bcs:
            return {"ok": False,
                    "reason": "contact kind requires at least one rigid_surface BC",
                    "path": [], "warnings": []}
        return _solve_contact(
            nodes, elements, float(E), float(A), fixed_dofs, contact_bcs,
            f_ref, n_steps, penalty, max_iter, tol,
        )


# ===========================================================================
# LLM tool registration
# ===========================================================================

_fem_nonlinear_spec = ToolSpec(
    name="fem_nonlinear",
    description=(
        "Run a nonlinear finite-element analysis. "
        "Supports geometric nonlinearity (large-displacement truss, TL Newton-Raphson "
        "or arc-length/Riks continuation for snap-through), "
        "material nonlinearity (J2 isotropic-hardening plasticity on a 2-D "
        "plane-stress mesh), and node-to-rigid-surface penalty contact. "
        "Returns converged load-displacement path, iteration counts per step, "
        "and any warnings about limit points or non-convergence."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mesh": {
                "type": "object",
                "description": "Mesh definition.",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"},
                                  "minItems": 2, "maxItems": 3},
                        "description": "List of [x, y] (or [x,y,z]) node coordinates.",
                    },
                    "elements": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "integer"}},
                        "description": (
                            "Element connectivity. "
                            "geometric/contact: 2-node truss [i,j]. "
                            "material: 3-node triangle [i,j,k]."
                        ),
                    },
                },
                "required": ["nodes", "elements"],
            },
            "material": {
                "type": "object",
                "description": "Material and section properties.",
                "properties": {
                    "E":         {"type": "number", "description": "Young's modulus [Pa]"},
                    "nu":        {"type": "number", "description": "Poisson ratio (material kind)"},
                    "sigma_y0":  {"type": "number", "description": "Initial yield stress [Pa]"},
                    "H":         {"type": "number", "description": "Hardening modulus [Pa]"},
                    "area":      {"type": "number", "description": "Cross-section area [m²] (truss)"},
                    "thickness": {"type": "number", "description": "Thickness [m] (plane-stress)"},
                    "arc_length": {"type": "boolean",
                                   "description": "Use Riks arc-length (geometric kind)"},
                },
                "required": ["E"],
            },
            "bcs": {
                "type": "array",
                "description": "Boundary conditions.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type":   {"type": "string",
                                   "enum": ["fixed", "rigid_surface"]},
                        "dofs":   {"type": "array", "items": {"type": "integer"}},
                        "normal": {"type": "array", "items": {"type": "number"},
                                   "description": "Surface normal (rigid_surface BC)"},
                        "offset": {"type": "number",
                                   "description": "Signed distance from origin (rigid_surface BC)"},
                    },
                    "required": ["type"],
                },
            },
            "loads": {
                "type": "array",
                "description": "Nodal loads (reference load, scaled by λ each step).",
                "items": {
                    "type": "object",
                    "properties": {
                        "node":  {"type": "integer"},
                        "dof":   {"type": "integer", "description": "0=x, 1=y"},
                        "value": {"type": "number"},
                    },
                    "required": ["node", "dof", "value"],
                },
            },
            "kind": {
                "type": "string",
                "enum": ["geometric", "material", "contact"],
                "description": "Type of nonlinearity to solve.",
            },
            "n_steps":        {"type": "integer",  "description": "Number of load steps",
                               "default": 10},
            "max_iter":       {"type": "integer",  "description": "Max Newton iterations per step",
                               "default": 50},
            "tol":            {"type": "number",   "description": "Relative residual tolerance",
                               "default": 1e-6},
            "penalty":        {"type": "number",   "description": "Contact penalty [N/m]",
                               "default": 1e12},
            "arc_length_ds":  {"type": "number",   "description": "Arc-length step size",
                               "default": 0.1},
        },
        "required": ["mesh", "material", "bcs", "loads", "kind"],
    },
)


@register(_fem_nonlinear_spec)
async def run_fem_nonlinear(ctx: ProjectCtx, args: bytes) -> str:
    import json
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    mesh     = a.get("mesh")
    material = a.get("material")
    bcs      = a.get("bcs", [])
    loads    = a.get("loads", [])
    kind     = a.get("kind")

    if not mesh:
        return err_payload("mesh is required", "BAD_ARGS")
    if not material:
        return err_payload("material is required", "BAD_ARGS")
    if not kind:
        return err_payload("kind is required", "BAD_ARGS")

    result = solve_nonlinear(
        mesh=mesh,
        material=material,
        bcs=bcs,
        loads=loads,
        kind=kind,
        n_steps=int(a.get("n_steps", 10)),
        max_iter=int(a.get("max_iter", 50)),
        tol=float(a.get("tol", 1e-6)),
        penalty=float(a.get("penalty", 1e12)),
        arc_length_ds=float(a.get("arc_length_ds", 0.1)),
    )
    return json.dumps(result)
