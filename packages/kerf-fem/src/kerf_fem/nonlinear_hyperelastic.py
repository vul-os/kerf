"""
Nonlinear hyperelastic FEM solver — Total-Lagrangian Newton-Raphson.

Wires the existing Neo-Hookean / Mooney-Rivlin / Ogden constitutive models
(kerf_fem.hyperelastic.models) into a large-deformation 3-D FEM solver based
on the Total-Lagrangian (TL) formulation.

Kinematic framework (Holzapfel 2000 §6)
-----------------------------------------
  Reference config X, current config x = X + u
  Deformation gradient F = ∂x/∂X = I + ∂u/∂X
  Right Cauchy-Green tensor C = Fᵀ F,   J = det(F)
  Green-Lagrange strain  E = ½(C - I)
  2nd Piola-Kirchhoff stress  S = 2 ∂W/∂C
  Lagrangian tangent  C_mat = 2 ∂S/∂C  (Voigt 6×6)

Element
-------
H8 (8-node hexahedral) with B-bar volumetric-locking suppression
(Hughes 1980) — same element as nonlinear_static.py.

The hyperelastic element differs from the J2 element only in the
constitutive update: instead of a return-mapping algorithm, we call the
closed-form hyperelastic stress + the FD Lagrangian tangent.

Incompressibility / near-incompressibility
------------------------------------------
  Neo-Hookean:   λ >> μ (set lam ≈ 1000 μ for near-incompressible)
  Mooney-Rivlin: d = 2/K; K >> 2(C10+C01) → near-incompressible
  Ogden:         κ >> μ_p α_p → near-incompressible
  The B-bar method suppresses volumetric locking in all three cases.

Solver
------
  • Incremental Newton-Raphson with load stepping
  • Crisfield (1981) spherical arc-length continuation (optional)
  • Golden-section line search (optional)

Analytic validation cases (see tests)
--------------------------------------
  1. Uniaxial tension of an incompressible Neo-Hookean bar:
       Nominal stress P = μ(λ - 1/λ²)
       Cauchy stress  σ = μ(λ² - 1/λ)
  2. Simple shear
  3. Block compression (equi-biaxial stretch)

Public API
----------
  solve_hyperelastic(model) → dict   (same shape as solve_nonlinear_static)
  fem_hyperelastic_solve tool        (registered in plugin.py)

  model keys:
    nodes          np.ndarray (n_nodes, 3)
    elements       list of 8-node lists
    material       dict  — see HyperelasticModel
    fixed_dofs     list[int]
    loads          list of (dof, force)
    n_steps        int    (default 10)
    arc_length     bool   (default False)
    ds             float  (default 1.0)
    max_iter       int    (default 25)
    tol            float  (default 1e-6)
    line_search    bool   (default True)

References
----------
  Holzapfel (2000) "Nonlinear Solid Mechanics" Wiley — §6–9.
  Hughes (1980) CMAME 22:245-270 — B-bar / selective-reduced integration.
  Crisfield (1981) IJNME 17:1269-1289 — arc-length method.
  Ogden (1972) Proc. R. Soc. London A 326, 565-584.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_fem.hyperelastic.models import (
    HyperelasticModel,
    neo_hookean_stress, neo_hookean_tangent,
    mooney_rivlin_stress, mooney_rivlin_tangent,
    ogden_stress, ogden_tangent,
    neo_hookean_uniaxial_cauchy,
    mooney_rivlin_uniaxial_cauchy,
    ogden_uniaxial_cauchy,
)

# Re-use the H8 kinematics from nonlinear_static (no duplication)
from kerf_fem.nonlinear_static import (
    _h8_shape, _h8_dshape, _h8_jacobian, _h8_dshape_dx,
    _deformation_gradient, _green_lagrange,
    _BL_matrix, _B_geometric, _sigma_matrix_9x9,
    _GAUSS2,
)


# ===========================================================================
# Hyperelastic constitutive dispatch
# ===========================================================================

def _hyperelastic_S_and_Cmat(F: np.ndarray, mat: HyperelasticModel):
    """
    Compute 2nd Piola-Kirchhoff stress S (6-vec Voigt) and Lagrangian tangent
    C_mat (6×6) for the given deformation gradient F.

    The Cauchy stress σ is first obtained from the hyperelastic model, then
    pushed back to PK2 via:
        S = J F⁻¹ σ F⁻ᵀ

    The Lagrangian tangent C_mat = 2 ∂S/∂C is computed by finite-differencing
    the PK2 stress with respect to C (via the model's _fd_tangent helper).

    Returns
    -------
    S     : (6,) Voigt [S11, S22, S33, S12, S13, S23]
    C_mat : (6, 6) Lagrangian tangent
    """
    J = float(np.linalg.det(F))
    if J <= 0:
        raise ValueError(f"det(F) = {J:.4e} ≤ 0 — degenerate element")

    if mat.model == "neo_hookean":
        mu = mat.mu if mat.mu > 0 else 2.0 * mat.C10
        lam_lame = mat.lam if mat.lam > 0 else 1000.0 * mu / 3.0
        sigma = neo_hookean_stress(F, mu, lam_lame)
        C_mat = neo_hookean_tangent(F, mu, lam_lame)

    elif mat.model == "mooney_rivlin":
        sigma = mooney_rivlin_stress(F, mat.C10, mat.C01, mat.d)
        C_mat = mooney_rivlin_tangent(F, mat.C10, mat.C01, mat.d)

    elif mat.model == "ogden":
        sigma = ogden_stress(F, mat.mu_p, mat.alpha_p, mat.kappa)
        C_mat = ogden_tangent(F, mat.mu_p, mat.alpha_p, mat.kappa)

    else:
        raise ValueError(f"Unknown hyperelastic model: {mat.model!r}")

    # Push Cauchy → PK2: S = J F⁻¹ σ F⁻ᵀ
    Finv = np.linalg.inv(F)
    S_full = J * Finv @ sigma @ Finv.T
    # Symmetrise (numerical noise)
    S_full = 0.5 * (S_full + S_full.T)

    S_voigt = np.array([S_full[0, 0], S_full[1, 1], S_full[2, 2],
                        S_full[0, 1], S_full[0, 2], S_full[1, 2]])
    return S_voigt, C_mat


# ===========================================================================
# Hyperelastic H8 element with B-bar
# ===========================================================================

def _h8_hyperelastic_element(
    X_e: np.ndarray,   # (8, 3) reference nodal coords
    u_e: np.ndarray,   # (24,) nodal displacements
    mat: HyperelasticModel,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute H8 element stiffness K_e (24×24) and internal force f_e (24,)
    for a hyperelastic material using the B-bar formulation.

    B-bar suppresses volumetric locking in nearly-incompressible materials
    by averaging the volumetric part of BL over the element (Hughes 1980).

    The internal force uses the exact PK2 stress from the hyperelastic model.
    The tangent stiffness includes both the material tangent (BL^T C_mat BL)
    and the geometric (stress) tangent (BNL^T σ̂ BNL).

    Returns
    -------
    K_e : (24, 24)
    f_e : (24,)
    """
    # ---- Step 1: mean B_vol_bar and element volume ----
    B_vol_sum = np.zeros(24)
    vol_total = 0.0
    gp_data = []

    for xi, wi in _GAUSS2:
        for eta, we in _GAUSS2:
            for zeta, wz in _GAUSS2:
                dN_dX, detJ = _h8_dshape_dx(xi, eta, zeta, X_e)
                F = _deformation_gradient(dN_dX, u_e)
                BL = _BL_matrix(dN_dX, F)
                w = wi * we * wz * detJ
                Bvol_row = BL[0, :] + BL[1, :] + BL[2, :]
                B_vol_sum += Bvol_row * w
                vol_total += w
                gp_data.append((dN_dX, detJ, F, BL, wi * we * wz))

    if abs(vol_total) < 1e-30:
        vol_total = 1.0
    B_vol_mean = B_vol_sum / vol_total   # (24,)

    # ---- Step 2: assemble ----
    K_e = np.zeros((24, 24))
    f_e = np.zeros(24)

    for (dN_dX, detJ, F_gp, BL, w_raw) in gp_data:
        w = w_raw * detJ

        # Hyperelastic stress and tangent
        S, C_mat = _hyperelastic_S_and_Cmat(F_gp, mat)

        # B-bar: replace volumetric rows of BL by mean
        BL_bar = BL.copy()
        Bvol_point = BL[0, :] + BL[1, :] + BL[2, :]
        for ii in range(3):
            BL_bar[ii, :] += (1.0 / 3.0) * (B_vol_mean - Bvol_point)

        # Internal force
        f_e += (BL_bar.T @ S) * w

        # Material stiffness
        K_mat = (BL_bar.T @ C_mat @ BL_bar) * w

        # Geometric stiffness
        BNL = _B_geometric(dN_dX)
        sigma_mat = _sigma_matrix_9x9(S, F_gp)
        K_geo = (BNL.T @ sigma_mat @ BNL) * w

        K_e += K_mat + K_geo

    return K_e, f_e


# ===========================================================================
# Global assembly
# ===========================================================================

def _assemble_hyperelastic(
    nodes: np.ndarray,
    elements: list,
    u: np.ndarray,
    mat: HyperelasticModel,
) -> tuple[sp.csr_matrix, np.ndarray]:
    """Assemble global tangent stiffness and internal force for hyperelastic FEM."""
    n_dofs = 3 * nodes.shape[0]
    rows, cols, vals = [], [], []
    R_int = np.zeros(n_dofs)

    for conn in elements:
        conn = list(conn)
        X_e = nodes[conn, :]
        dof_e = []
        for n_idx in conn:
            dof_e.extend([3 * n_idx, 3 * n_idx + 1, 3 * n_idx + 2])
        dof_e = np.array(dof_e, dtype=int)
        u_e = u[dof_e]

        K_e, f_e = _h8_hyperelastic_element(X_e, u_e, mat)

        R_int[dof_e] += f_e
        for i in range(24):
            for j in range(24):
                rows.append(dof_e[i])
                cols.append(dof_e[j])
                vals.append(K_e[i, j])

    K = sp.coo_matrix((vals, (rows, cols)), shape=(n_dofs, n_dofs)).tocsr()
    return K, R_int


def _apply_bcs(K, R, fixed_dofs):
    K = K.tolil()
    for d in fixed_dofs:
        K[d, :] = 0.0
        K[:, d] = 0.0
        K[d, d] = 1.0
        R[d] = 0.0
    return K.tocsr(), R


# ===========================================================================
# Line search (golden section)
# ===========================================================================

def _safe_residual_norm(u_trial, f_ext, fixed_dofs, nodes, elements, mat):
    """
    Compute residual norm at u_trial.  Returns (norm, valid).
    If assembly fails (element inversion), returns (1e30, False).
    """
    try:
        _, R_int = _assemble_hyperelastic(nodes, elements, u_trial, mat)
    except Exception:
        return 1e30, False
    R = f_ext - R_int
    for d in fixed_dofs:
        R[d] = 0.0
    return float(np.linalg.norm(R)), True


def _line_search_hyp(u, du, f_ext, fixed_dofs, nodes, elements, mat, max_iter=8):
    """
    Backtracking + golden-section line search for hyperelastic NR.

    Strategy:
    1. Try alpha=1 (full step).
    2. If element is inverted (det(F)<=0), halve alpha until valid.
    3. If the full valid step makes residual worse, do golden section.

    Returns alpha ∈ (0, 1].
    """
    # Phase 1: find largest alpha that keeps elements valid
    alpha = 1.0
    min_alpha = 1e-8
    for _ in range(20):  # up to 2^-20 reduction
        rn, valid = _safe_residual_norm(u + alpha * du, f_ext, fixed_dofs,
                                        nodes, elements, mat)
        if valid:
            break
        alpha *= 0.5
        if alpha < min_alpha:
            return min_alpha  # last resort

    if not valid:
        return min_alpha

    # Phase 2: golden-section refinement if full-step increases residual
    rn_0, _ = _safe_residual_norm(u, f_ext, fixed_dofs, nodes, elements, mat)
    if rn < rn_0:
        return alpha  # full step already reduces residual → accept

    # Residual is larger than at u=0; do golden section in [0, alpha]
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = 0.0, alpha
    fa = rn_0
    fb = rn
    # Try midpoint first
    for _ in range(max_iter):
        m = (a + b) / 2.0
        fm, vm = _safe_residual_norm(u + m * du, f_ext, fixed_dofs,
                                     nodes, elements, mat)
        if not vm:
            b = m
            continue
        if fm < fa:
            return m
        b = m
    return a + (b - a) * 0.1  # conservative small step


# ===========================================================================
# Newton-Raphson step
# ===========================================================================

def _newton_step_hyp(u, f_ext, fixed_dofs, nodes, elements, mat,
                     max_iter=25, tol=1e-6, line_search=True):
    """
    Full Newton-Raphson iteration for hyperelastic FEM.

    Each Newton iterate:
    1. Assemble K and R_int from current u_cur.
    2. Solve K du = R.
    3. Find alpha via line search (or simple backtracking) to keep J > 0.
    4. Update u_cur ← u_cur + alpha * du.

    The state `u_cur` is always physically valid (J>0 at all Gauss points)
    after each update — we guarantee this via inversion-safe step acceptance.
    """
    u_cur = u.copy()
    # For displacement-controlled problems (f_ext ≈ 0), ref_norm needs to be
    # based on the actual internal force magnitude, not f_ext.
    # We use a lazy evaluation: set ref_norm from f_ext, then update it from
    # the first assembly if f_ext is near-zero.
    f_norm = float(np.linalg.norm(f_ext))
    ref_norm_set = False

    for it in range(max_iter):
        # Check that u_cur is valid before assembly
        rn_cur, valid_cur = _safe_residual_norm(u_cur, f_ext, fixed_dofs,
                                                 nodes, elements, mat)
        if not valid_cur:
            # u_cur is invalid — can't continue
            return u, it, False  # return original u (safe)

        # Determine reference norm on first valid iteration
        if not ref_norm_set:
            if f_norm > 1e-10:
                ref_norm = f_norm
            else:
                # Displacement-controlled: use R_int norm at start as reference
                try:
                    _, R_int_0 = _assemble_hyperelastic(nodes, elements, u_cur, mat)
                    # Free-DOF R_int magnitude
                    R_free = R_int_0.copy()
                    for d in fixed_dofs:
                        R_free[d] = 0.0
                    ref_norm = max(float(np.linalg.norm(R_free)), 1.0)  # 1 Pa·m³ floor
                except Exception:
                    ref_norm = 1.0
            ref_norm_set = True

        if rn_cur / ref_norm <= tol:
            return u_cur, it, True

        # Assemble K at current valid state
        try:
            K, R_int = _assemble_hyperelastic(nodes, elements, u_cur, mat)
        except Exception:
            return u_cur, it, False

        residual = f_ext - R_int
        for d in fixed_dofs:
            residual[d] = 0.0

        K_bc, rhs_bc = _apply_bcs(K, residual.copy(), fixed_dofs)
        try:
            du = spla.spsolve(K_bc, rhs_bc)
        except Exception:
            return u_cur, it, False

        if not np.isfinite(du).all():
            return u_cur, it, False

        # Decide whether line search is worthwhile:
        # - Skip it when the step is tiny (already near convergence) to
        #   avoid the line search's midpoint bisection stagnating Newton.
        # - Always do backtracking check (phase 1) to prevent J≤0.
        u_norm = max(float(np.linalg.norm(u_cur)), float(np.linalg.norm(du)), 1e-30)
        rel_step = float(np.linalg.norm(du)) / u_norm

        if rel_step > 1e-7:
            # Non-trivial step: use full line search with inversion guard
            alpha = _line_search_hyp(u_cur, du, f_ext, fixed_dofs, nodes, elements, mat)
        else:
            # Tiny step (late Newton): just check J>0 and take alpha=1
            _, valid_full = _safe_residual_norm(u_cur + du, f_ext, fixed_dofs,
                                                 nodes, elements, mat)
            alpha = 1.0 if valid_full else 0.5

        u_cur = u_cur + alpha * du

    # Check final convergence
    rn_final, _ = _safe_residual_norm(u_cur, f_ext, fixed_dofs, nodes, elements, mat)
    return u_cur, max_iter, rn_final / ref_norm <= tol


# ===========================================================================
# Arc-length continuation (Crisfield 1981 spherical)
# ===========================================================================

def _arc_length_step_hyp(u, lam, f_ref, ds, lam_scale,
                         fixed_dofs, nodes, elements, mat,
                         max_iter=25, tol=1e-6, line_search=True):
    # Predictor
    K0, _ = _assemble_hyperelastic(nodes, elements, u, mat)
    f_bc = f_ref.copy()
    K_bc0, f_bc = _apply_bcs(K0, f_bc, fixed_dofs)
    try:
        du_t = spla.spsolve(K_bc0, f_bc)
    except Exception:
        return u, lam, 0, False

    if not np.isfinite(du_t).all():
        return u, lam, 0, False

    norm2 = float(np.dot(du_t, du_t)) + (1.0 / lam_scale) ** 2
    scale = ds / math.sqrt(norm2) if norm2 > 0 else 1.0
    du_pred = du_t * scale
    dlam_pred = scale

    u_new = u + du_pred
    lam_new = lam + dlam_pred

    # Corrector Newton loop
    for it in range(max_iter):
        K, R_int = _assemble_hyperelastic(nodes, elements, u_new, mat)
        R_mech = lam_new * f_ref - R_int
        for d in fixed_dofs:
            R_mech[d] = 0.0

        res_norm = float(np.linalg.norm(R_mech))
        ref = max(float(np.linalg.norm(f_ref)) * abs(lam_new), 1e-12)
        if res_norm / ref <= tol:
            return u_new, lam_new, it + 1, True

        du_step = u_new - u
        c_val = float(np.dot(du_step, du_step)) + ((lam_new - lam) / lam_scale) ** 2 - ds ** 2

        K_lil = K.tolil()
        for d in fixed_dofs:
            K_lil[d, :] = 0.0; K_lil[:, d] = 0.0; K_lil[d, d] = 1.0
        K_bc = K_lil.tocsr()
        f_bc_ref = f_ref.copy()
        for d in fixed_dofs:
            f_bc_ref[d] = 0.0

        try:
            du_R = spla.spsolve(K_bc, R_mech)
            du_f = spla.spsolve(K_bc, f_bc_ref)
        except Exception:
            return u_new, lam_new, it + 1, False

        if not (np.isfinite(du_R).all() and np.isfinite(du_f).all()):
            return u_new, lam_new, it + 1, False

        a1 = float(np.dot(du_step, du_R))
        a2 = float(np.dot(du_step, du_f)) + (lam_new - lam) / (lam_scale ** 2)
        dlam_c = 0.0 if abs(a2) < 1e-30 else -(a1 + 0.5 * c_val) / a2
        du_c = du_R + dlam_c * du_f

        alpha_c = 1.0
        if line_search:
            alpha_c = _line_search_hyp(u_new, du_c,
                                       (lam_new + dlam_c) * f_ref,
                                       fixed_dofs, nodes, elements, mat, max_iter=4)
        u_new = u_new + alpha_c * du_c
        lam_new = lam_new + alpha_c * dlam_c

    return u_new, lam_new, max_iter, False


# ===========================================================================
# Extract Gauss-point stretch and stress for output
# ===========================================================================

def _extract_gp_results(nodes, elements, u, mat):
    """
    For each element, extract the average (centroidal) deformation gradient,
    principal stretches, J, and Cauchy stress over the 8 Gauss points.

    Returns list of dicts with keys: J, principal_stretches, cauchy_stress_voigt.
    """
    results = []
    for conn in elements:
        conn = list(conn)
        X_e = nodes[conn, :]
        dof_e = []
        for n_idx in conn:
            dof_e.extend([3 * n_idx, 3 * n_idx + 1, 3 * n_idx + 2])
        dof_e = np.array(dof_e, dtype=int)
        u_e = u[dof_e]

        F_avg = np.zeros((3, 3))
        sigma_avg = np.zeros((3, 3))
        n_gp = 0
        for xi, wi in _GAUSS2:
            for eta, we in _GAUSS2:
                for zeta, wz in _GAUSS2:
                    dN_dX, detJ = _h8_dshape_dx(xi, eta, zeta, X_e)
                    F = _deformation_gradient(dN_dX, u_e)
                    F_avg += F
                    # Cauchy stress
                    if mat.model == "neo_hookean":
                        mu = mat.mu if mat.mu > 0 else 2.0 * mat.C10
                        lam_l = mat.lam if mat.lam > 0 else 1000.0 * mu / 3.0
                        sigma = neo_hookean_stress(F, mu, lam_l)
                    elif mat.model == "mooney_rivlin":
                        sigma = mooney_rivlin_stress(F, mat.C10, mat.C01, mat.d)
                    else:
                        sigma = ogden_stress(F, mat.mu_p, mat.alpha_p, mat.kappa)
                    sigma_avg += sigma
                    n_gp += 1

        F_avg /= n_gp
        sigma_avg /= n_gp
        J = float(np.linalg.det(F_avg))
        C = F_avg.T @ F_avg
        lam_sq = np.maximum(np.linalg.eigvalsh(C), 0.0)
        stretches = sorted(np.sqrt(lam_sq).tolist(), reverse=True)

        results.append({
            "J": J,
            "principal_stretches": stretches,
            "cauchy_stress_voigt": [
                float(sigma_avg[0, 0]), float(sigma_avg[1, 1]), float(sigma_avg[2, 2]),
                float(sigma_avg[0, 1]), float(sigma_avg[0, 2]), float(sigma_avg[1, 2]),
            ],
        })
    return results


# ===========================================================================
# Nominal stress for uniaxial validation
# ===========================================================================

def _nominal_stress_analytic(mat: HyperelasticModel, lam: float) -> float:
    """
    Incompressible uniaxial nominal (1st Piola-Kirchhoff) stress:
        P = σ / λ  = (σ_11 - σ_22) / λ

    Neo-Hookean:     P = μ(λ - 1/λ²)
    Mooney-Rivlin:   P = 2(λ - 1/λ²)(C10 + C01/λ)
    Ogden:           P = (1/λ) Σ μ_p(λ^α_p - λ^{-α_p/2})
    """
    if mat.model == "neo_hookean":
        mu = mat.mu if mat.mu > 0 else 2.0 * mat.C10
        return mu * (lam - 1.0 / lam**2)
    elif mat.model == "mooney_rivlin":
        return 2.0 * (lam - 1.0 / lam**2) * (mat.C10 + mat.C01 / lam)
    elif mat.model == "ogden":
        # Cauchy = Σ μ_p(λ^α_p - λ^{-α_p/2}),  P = Cauchy/λ
        cauchy = ogden_uniaxial_cauchy(lam, mat.mu_p, mat.alpha_p)
        return cauchy / lam
    else:
        raise ValueError(f"Unknown model: {mat.model!r}")


# ===========================================================================
# Main public solver
# ===========================================================================

def solve_hyperelastic(model: dict) -> dict[str, Any]:
    """
    Large-deformation hyperelastic FEM solver (Total-Lagrangian).

    Parameters (model dict)
    -----------------------
    nodes        : list of [x, y, z]  — reference nodal coordinates
    elements     : list of 8-int lists — H8 connectivity (0-based)
    material     : dict with keys:
        type         : 'neo_hookean' | 'mooney_rivlin' | 'ogden'
        mu_pa        : float  (Neo-Hookean shear modulus, Pa)
        lam_pa       : float  (Neo-Hookean Lamé λ, Pa; default 1000 mu/3)
        C10_pa       : float  (Mooney-Rivlin, Pa)
        C01_pa       : float  (Mooney-Rivlin, Pa)
        d_inv_pa     : float  (MR compressibility, Pa⁻¹; 0=incompressible)
        ogden_mu_p   : list   (Ogden moduli, Pa)
        ogden_alpha_p: list   (Ogden exponents)
        ogden_kappa  : float  (Ogden bulk modulus, Pa)
    fixed_dofs   : list[int]
    loads        : list of [dof, force]
    n_steps      : int    (default 10)
    arc_length   : bool   (default False)
    ds           : float  (default 1.0, arc-length)
    max_iter     : int    (default 25)
    tol          : float  (default 1e-6)
    line_search  : bool   (default True)

    Returns
    -------
    dict with keys:
      ok           : bool
      path         : list of step dicts
                       {step, lambda, displacements, iters, converged,
                        limit_point, gp_results (per-element centroidal)}
      warnings     : list[str]
      reason       : str  (only when ok=False)
    """
    try:
        return _solve_inner(model)
    except Exception as exc:
        import traceback
        return {"ok": False,
                "reason": f"unexpected error: {exc}",
                "traceback": traceback.format_exc(),
                "path": [], "warnings": []}


def _parse_material(mdict: dict) -> HyperelasticModel:
    model_type = str(mdict.get("type", "neo_hookean"))
    if model_type == "neo_hookean":
        mu = float(mdict.get("mu_pa", 0.4e6))
        lam_l = float(mdict.get("lam_pa", 0.0))
        if lam_l <= 0:
            lam_l = 1000.0 * mu / 3.0
        return HyperelasticModel(model="neo_hookean", mu=mu, lam=lam_l,
                                 C10=mu / 2.0)
    elif model_type == "mooney_rivlin":
        C10 = float(mdict.get("C10_pa", 0.15e6))
        C01 = float(mdict.get("C01_pa", 0.015e6))
        d = float(mdict.get("d_inv_pa", 0.0))
        # If d=0 (fully incompressible assumption) add a small bulk penalty
        # to regularise the volumetric mode in the solver
        if d == 0.0:
            # K ≈ 1000 × initial shear modulus
            K = 1000.0 * 2.0 * (C10 + C01)
            d = 2.0 / K if K > 0 else 1e-9
        return HyperelasticModel(model="mooney_rivlin", C10=C10, C01=C01, d=d)
    elif model_type == "ogden":
        mu_p = [float(v) for v in mdict.get("ogden_mu_p", [0.63e6])]
        alpha_p = [float(v) for v in mdict.get("ogden_alpha_p", [1.3])]
        kappa = float(mdict.get("ogden_kappa", 1e9))
        return HyperelasticModel(model="ogden", mu_p=mu_p, alpha_p=alpha_p,
                                 kappa=kappa)
    else:
        raise ValueError(f"Unknown material type: {model_type!r}")


def _solve_inner(model: dict) -> dict[str, Any]:
    nodes_in = model.get("nodes")
    elements_in = model.get("elements")
    if nodes_in is None or elements_in is None:
        return {"ok": False,
                "reason": "model must have 'nodes' and 'elements'",
                "path": [], "warnings": []}

    nodes = np.asarray(nodes_in, dtype=float)
    if nodes.ndim != 2 or nodes.shape[1] != 3:
        return {"ok": False,
                "reason": f"nodes must be (n, 3); got shape {nodes.shape}",
                "path": [], "warnings": []}

    elements = [list(e) for e in elements_in]
    for e_idx, e in enumerate(elements):
        if len(e) != 8:
            return {"ok": False,
                    "reason": f"element {e_idx} has {len(e)} nodes; H8 requires 8",
                    "path": [], "warnings": []}

    mat_dict = model.get("material", {})
    try:
        mat = _parse_material(mat_dict)
    except Exception as exc:
        return {"ok": False, "reason": f"material error: {exc}",
                "path": [], "warnings": []}

    n_nodes = nodes.shape[0]
    n_dofs = 3 * n_nodes

    fixed_dofs = [int(d) for d in model.get("fixed_dofs", [])
                  if 0 <= int(d) < n_dofs]
    f_ref = np.zeros(n_dofs)
    for load in model.get("loads", []):
        dof, force = int(load[0]), float(load[1])
        if 0 <= dof < n_dofs:
            f_ref[dof] += force

    # Prescribed (nonzero) displacements: {dof: final_value}
    # These are applied incrementally: at load step i (lam_i = i/n_steps),
    # u_prescribed[dof] = lam_i * final_value.
    # The prescribed DOFs are treated as additional fixed_dofs for Newton,
    # but their displacement is enforced at each step.
    prescribed_raw = model.get("prescribed_displacements", {})
    prescribed = {}  # dof → final displacement
    for dof_str, val in prescribed_raw.items():
        dof_i = int(dof_str)
        if 0 <= dof_i < n_dofs:
            prescribed[dof_i] = float(val)
    all_fixed_dofs = fixed_dofs + [d for d in prescribed if d not in fixed_dofs]

    n_steps = int(model.get("n_steps", 10))
    arc_length = bool(model.get("arc_length", False))
    ds = float(model.get("ds", 1.0))
    max_iter = int(model.get("max_iter", 25))
    tol = float(model.get("tol", 1e-6))
    ls_enabled = bool(model.get("line_search", True))
    lam_scale = float(model.get("lam_scale", 1.0))

    u = np.zeros(n_dofs)
    lam = 0.0
    path = []
    warnings_out = []

    if not arc_length:
        dlam = 1.0 / max(n_steps, 1)
        for step in range(n_steps):
            lam_target = (step + 1) * dlam
            f_ext = lam_target * f_ref

            # Apply prescribed displacements for this load step
            if prescribed:
                for dof_p, u_final in prescribed.items():
                    u[dof_p] = lam_target * u_final

            u_new, iters, conv = _newton_step_hyp(
                u, f_ext, all_fixed_dofs, nodes, elements, mat,
                max_iter, tol, ls_enabled
            )

            # Re-enforce prescribed displacements after Newton (guard against drift)
            if prescribed:
                for dof_p, u_final in prescribed.items():
                    u_new[dof_p] = lam_target * u_final

            if not conv:
                warnings_out.append(
                    f"Step {step}: Newton did not converge in {max_iter} iters "
                    f"(λ={lam_target:.4g})"
                )

            u = u_new
            lam = lam_target
            gp_res = _extract_gp_results(nodes, elements, u, mat)

            step_dict = {
                "step": step,
                "lambda": float(lam),
                "displacements": u.tolist(),
                "iters": iters,
                "converged": conv,
                "limit_point": False,
                "gp_results": gp_res,
            }
            # For displacement-controlled: report reaction forces on prescribed DOFs
            if prescribed:
                try:
                    _, R_int_now = _assemble_hyperelastic(nodes, elements, u, mat)
                    reactions = {str(d): float(R_int_now[d]) for d in prescribed}
                    step_dict["reaction_forces"] = reactions
                except Exception:
                    pass
            path.append(step_dict)

    else:
        for step in range(n_steps):
            u_new, lam_new, iters, conv = _arc_length_step_hyp(
                u, lam, f_ref, ds, lam_scale,
                all_fixed_dofs, nodes, elements, mat,
                max_iter, tol, ls_enabled
            )
            if not conv:
                # halve and retry
                ds_try = ds * 0.5
                u_new, lam_new, iters, conv = _arc_length_step_hyp(
                    u, lam, f_ref, ds_try, lam_scale,
                    fixed_dofs, nodes, elements, mat,
                    max_iter, tol, ls_enabled
                )
                if not conv:
                    warnings_out.append(
                        f"Arc-length step {step}: did not converge "
                        f"(ds={ds_try:.3e}, λ={lam_new:.4g})"
                    )

            limit_point = (step > 0 and lam_new < lam and lam > 0.0)
            if limit_point:
                warnings_out.append(
                    f"Limit point at step {step}: λ {lam:.4g} → {lam_new:.4g}"
                )

            u = u_new
            lam = lam_new
            gp_res = _extract_gp_results(nodes, elements, u, mat)

            path.append({
                "step": step,
                "lambda": float(lam),
                "displacements": u.tolist(),
                "iters": iters,
                "converged": conv,
                "limit_point": limit_point,
                "gp_results": gp_res,
            })

    return {"ok": True, "path": path, "warnings": warnings_out}


# ===========================================================================
# Single H8 unit-cube helper (for tests)
# ===========================================================================

def _unit_cube_hyperelastic(L=1.0, mat_dict=None, fixed_dofs_fn=None,
                             loads_fn=None, n_steps=5):
    """Return a hyperelastic model dict for a single H8 cube of side L."""
    if mat_dict is None:
        mat_dict = {"type": "neo_hookean", "mu_pa": 0.4e6}
    nodes = np.array([
        [0, 0, 0], [L, 0, 0], [L, L, 0], [0, L, 0],
        [0, 0, L], [L, 0, L], [L, L, L], [0, L, L],
    ], dtype=float)
    return {
        "nodes": nodes.tolist(),
        "elements": [[0, 1, 2, 3, 4, 5, 6, 7]],
        "material": mat_dict,
        "n_steps": n_steps,
    }


# ===========================================================================
# LLM tool: fem_hyperelastic_solve
# ===========================================================================

_fem_hyperelastic_solve_spec = ToolSpec(
    name="fem_hyperelastic_solve",
    description=(
        "Large-deformation hyperelastic FEM solver using the Total-Lagrangian "
        "formulation with Newton-Raphson and optional Crisfield arc-length "
        "continuation.  Supports Neo-Hookean, Mooney-Rivlin, and Ogden "
        "(N=1..3) constitutive models wired into an 8-node hexahedral (H8) "
        "element with B-bar volumetric-locking suppression.  "
        "Validated against analytic incompressible solutions: uniaxial tension "
        "σ=μ(λ²-1/λ) (NH); simple shear; block compression.  "
        "Returns the full load-displacement path with per-element principal "
        "stretches, volume ratio J, and Cauchy stress.  "
        "\n\nPhysics gap: viscoelastic (time-dependent) relaxation and Mullins "
        "(stress-softening) effects are NOT modelled; suitable for "
        "quasi-static equilibrium only.  "
        "\n\nElement: H8 hex with B-bar (Hughes 1980) — no MITC4 shell path.  "
        "\n\nReferences: Holzapfel (2000) Nonlinear Solid Mechanics; "
        "Ogden (1972); Crisfield (1981) IJNME 17:1269-1289."
    ),
    input_schema={
        "type": "object",
        "required": ["nodes", "elements", "material", "fixed_dofs", "loads"],
        "properties": {
            "nodes": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"},
                          "minItems": 3, "maxItems": 3},
                "description": "List of [x, y, z] reference nodal coordinates.",
            },
            "elements": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"},
                          "minItems": 8, "maxItems": 8},
                "description": "H8 connectivity: list of 8-node lists (0-based).",
            },
            "material": {
                "type": "object",
                "description": (
                    "Hyperelastic material. Required key: 'type' "
                    "('neo_hookean'|'mooney_rivlin'|'ogden'). "
                    "Neo-Hookean: mu_pa [Pa], lam_pa [Pa] (optional; default 1000 mu/3). "
                    "Mooney-Rivlin: C10_pa, C01_pa [Pa], d_inv_pa [Pa⁻¹] (0=incompressible). "
                    "Ogden: ogden_mu_p [list Pa], ogden_alpha_p [list], ogden_kappa [Pa]."
                ),
            },
            "fixed_dofs": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "DOF indices to fix (3·node + 0/1/2 for x/y/z).",
            },
            "loads": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"},
                          "minItems": 2, "maxItems": 2},
                "description": "Reference loads: [[dof, force], ...]",
            },
            "n_steps": {"type": "integer",
                        "description": "Number of load steps (default 10)."},
            "arc_length": {"type": "boolean",
                           "description": "Use Crisfield arc-length (default false)."},
            "ds": {"type": "number",
                   "description": "Arc-length increment (default 1.0)."},
            "max_iter": {"type": "integer",
                         "description": "Max Newton iterations per step (default 25)."},
            "tol": {"type": "number",
                    "description": "Relative residual tolerance (default 1e-6)."},
            "line_search": {"type": "boolean",
                            "description": "Enable line search (default true)."},
        },
    },
)


@register(_fem_hyperelastic_solve_spec)
async def run_fem_hyperelastic_solve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    required = ["nodes", "elements", "material", "fixed_dofs", "loads"]
    missing = [k for k in required if k not in a]
    if missing:
        return err_payload(f"missing required fields: {missing}", "BAD_ARGS")

    result = solve_hyperelastic(a)
    if result.get("ok"):
        return ok_payload(result)
    return err_payload(result.get("reason", "solver failed"), "SOLVER_ERROR")


# TOOLS list for plugin.py registration
TOOLS = [
    ("fem_hyperelastic_solve", _fem_hyperelastic_solve_spec,
     run_fem_hyperelastic_solve),
]
