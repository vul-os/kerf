"""
3-D Nonlinear Static FEM — Newton-Raphson + Crisfield arc-length continuation.

Capabilities
------------
* **Element types**
  - H8  : 3-D 8-node hexahedral element (full 2×2×2 Gauss), with B-bar
          volumetric-locking suppression (selective-reduced-integration of the
          volumetric part; Nagtegaal–Parks–Rice 1974 / Hughes 1980).
  - MITC4 shell path: deferred — see note at bottom of file.

* **Nonlinearities**
  - Geometric: Total-Lagrangian formulation.  Green-Lagrange strain tensor E,
    2nd Piola-Kirchhoff stress S; consistent material + geometric (stress)
    tangent stiffness assembled at every Newton iteration.
  - Material: J2 plasticity with isotropic (Voce / linear) + kinematic
    (Armstrong-Frederick) hardening.  Closest-point projection (CPP) return
    mapping in the full 3-D stress space; consistent (algorithmic) tangent
    modulus from Simo & Taylor (1985).

* **Solvers**
  - Newton-Raphson (NR) with optional golden-section line search on the step
    length to improve robustness near limit points and sharp yield fronts.
  - Crisfield (1981) spherical arc-length continuation: predictor by tangent
    normalisation, corrector enforces the spherical constraint
    ‖Δu‖² + (Δλ / λ̄)² = Δs²; detects limit points (λ̇ sign change);
    adaptive step-size halving on non-convergence.

Public API
----------
    solve_nonlinear_static(model) -> dict

    model keys (all SI units):
      nodes        : np.ndarray (n_nodes, 3)  — reference nodal coords
      elements     : list of 8-node lists     — H8 connectivity (0-based)
      E            : float                    — Young's modulus [Pa]
      nu           : float                    — Poisson ratio
      sigma_y0     : float                    — initial yield stress [Pa]
                                                (1e30 = elastic)
      H_iso        : float                    — isotropic hardening modulus [Pa]
      H_kin        : float                    — kinematic hardening modulus [Pa]
                                                (Armstrong-Frederick C)
      gamma_kin    : float                    — A-F saturation parameter (γ)
      fixed_dofs   : list[int]                — DOF indices to fix (3·n+0/1/2)
      loads        : list of (dof, force)     — reference (unit) external loads
      n_steps      : int                      — number of arc-length / NR steps
      arc_length   : bool                     — use arc-length continuation
      ds           : float                    — arc-length increment (if arc_length)
      max_iter     : int                      — max Newton corrector iterations
      tol          : float                    — relative residual tolerance
      line_search  : bool                     — golden-section line search
      max_ls_iter  : int                      — max line-search evaluations

    Returns dict:
      ok           : bool
      path         : list of step dicts
                       { step, lambda, displacements (flat list), iters,
                         converged, limit_point }
      warnings     : list[str]
      reason       : str  (only when ok=False)

References
----------
* Crisfield (1981) IJNME 17:1269-1289 — arc-length method.
* Simo & Hughes "Computational Inelasticity" (1998), Ch. 2 — CPP return
  mapping, consistent tangent.
* Armstrong & Frederick (1966) — kinematic hardening evolution.
* Hughes (1980) CMAME 22:245-270 — B-bar / selective-reduced integration.
* Nagtegaal, Parks & Rice (1974) CMAME 4:153-177 — volumetric locking.
* Bisshop & Drucker (1945) Quart. Appl. Math. 3:272-275 — large-deflection
  cantilever elastica.
* Lee (1968) "Large deflections of cantilever beams of non-uniform section"
  ASME J. Appl. Mech — Lee's frame snap-through.
* Simo & Hughes (1998) §2.4 — necking of cylindrical bar.

MITC4 shell path: deferred.  The plate.py module provides a stand-alone MITC4
solver for linear static plate problems; coupling it into the NL static driver
(corotational shell, drilling DOF, finite rotation update) is non-trivial and
deferred to T-100-C.  All H8 solid + NL static paths are complete and tested.
"""

from __future__ import annotations

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


# ===========================================================================
# Constants
# ===========================================================================

_GAUSS2 = ((-1.0 / math.sqrt(3.0), 1.0), (1.0 / math.sqrt(3.0), 1.0))
# 2-point Gauss rule in [-1,1]: (xi, weight) pairs


# ===========================================================================
# H8 shape functions and Jacobian
# ===========================================================================

def _h8_shape(xi: float, eta: float, zeta: float) -> np.ndarray:
    """
    8-node hexahedron shape functions N_i(ξ,η,ζ), i=0..7.

    Node ordering (right-hand rule, ζ=-1 face first):
      0: (-1,-1,-1)  1: (+1,-1,-1)  2: (+1,+1,-1)  3: (-1,+1,-1)
      4: (-1,-1,+1)  5: (+1,-1,+1)  6: (+1,+1,+1)  7: (-1,+1,+1)
    """
    xc = np.array([-1, 1, 1, -1, -1, 1, 1, -1], dtype=float)
    ec = np.array([-1, -1, 1, 1, -1, -1, 1, 1], dtype=float)
    zc = np.array([-1, -1, -1, -1, 1, 1, 1, 1], dtype=float)
    return 0.125 * (1.0 + xc * xi) * (1.0 + ec * eta) * (1.0 + zc * zeta)


def _h8_dshape(xi: float, eta: float, zeta: float) -> np.ndarray:
    """
    Derivatives of H8 shape functions wrt (ξ,η,ζ): shape (3, 8).
    Row 0: dN/dξ,  Row 1: dN/dη,  Row 2: dN/dζ.
    """
    xc = np.array([-1, 1, 1, -1, -1, 1, 1, -1], dtype=float)
    ec = np.array([-1, -1, 1, 1, -1, -1, 1, 1], dtype=float)
    zc = np.array([-1, -1, -1, -1, 1, 1, 1, 1], dtype=float)
    dN_dxi  = 0.125 * xc * (1.0 + ec * eta)  * (1.0 + zc * zeta)
    dN_deta = 0.125 * (1.0 + xc * xi) * ec   * (1.0 + zc * zeta)
    dN_dze  = 0.125 * (1.0 + xc * xi) * (1.0 + ec * eta) * zc
    return np.vstack([dN_dxi, dN_deta, dN_dze])  # (3,8)


def _h8_jacobian(dN_dxi: np.ndarray, X_e: np.ndarray):
    """
    Compute Jacobian J = dN_dxi @ X_e  (3×3), its inverse and determinant.

    Parameters
    ----------
    dN_dxi : (3, 8)   shape function derivatives wrt ξ,η,ζ
    X_e    : (8, 3)   element reference nodal coords

    Returns
    -------
    J, Jinv, detJ
    """
    J = dN_dxi @ X_e          # (3,3)
    detJ = float(np.linalg.det(J))
    if abs(detJ) < 1e-20:
        raise ValueError(f"Degenerate element: detJ={detJ:.3e}")
    Jinv = np.linalg.inv(J)
    return J, Jinv, detJ


def _h8_dshape_dx(xi: float, eta: float, zeta: float,
                  X_e: np.ndarray):
    """
    Compute dN/dX (3,8) — shape-function derivatives in the reference
    configuration.  Also returns detJ for integration weight.
    """
    dN_dxi = _h8_dshape(xi, eta, zeta)
    _, Jinv, detJ = _h8_jacobian(dN_dxi, X_e)
    dN_dX = Jinv @ dN_dxi   # (3,8)
    return dN_dX, detJ


# ===========================================================================
# Total-Lagrangian kinematics (Green-Lagrange strain)
# ===========================================================================

def _deformation_gradient(dN_dX: np.ndarray, u_e: np.ndarray) -> np.ndarray:
    """
    Compute the deformation gradient F = I + du/dX at a Gauss point.

    Parameters
    ----------
    dN_dX : (3, 8)   dN_i/dX_j
    u_e   : (24,)    element displacement vector (u0,v0,w0, u1,v1,w1, ...)

    Returns
    -------
    F : (3, 3)
    """
    # u_e layout: [u0, v0, w0, u1, v1, w1, ..., u7, v7, w7]
    U = u_e.reshape(8, 3)            # (8, 3)  node × component
    # du/dX = sum_i dN_i/dX ⊗ u_i  = (dN_dX.T @ U).T ... let's be explicit
    # (∂u/∂X)_ij = sum_k (dN_k/dX_j) * u_k_i
    # = (U^T @ dN_dX^T)  shape (3,3): row=displacement component, col=reference coord
    dudX = (U.T @ dN_dX.T)    # (3,3)  [i component, j coord]
    F = np.eye(3) + dudX
    return F


def _green_lagrange(F: np.ndarray) -> np.ndarray:
    """Green-Lagrange strain tensor E = ½(F^T F - I), returned as 6-vector
    in Voigt notation: [E11, E22, E33, 2E12, 2E13, 2E23]."""
    C = F.T @ F           # right Cauchy-Green tensor
    E_mat = 0.5 * (C - np.eye(3))
    # Voigt: [E11, E22, E33, 2*E12, 2*E13, 2*E23]
    return np.array([E_mat[0, 0], E_mat[1, 1], E_mat[2, 2],
                     2.0 * E_mat[0, 1], 2.0 * E_mat[0, 2], 2.0 * E_mat[1, 2]])


def _B_geometric(dN_dX: np.ndarray) -> np.ndarray:
    """
    Nonlinear (geometric) strain-displacement matrix BNL: (9, 24).

    Used for the geometric stiffness:  Kg = integral BNL^T * sigma_hat * BNL dV
    where sigma_hat is the 9×9 Cauchy/PK2 stress matrix (Belytschko notation).
    """
    BNL = np.zeros((9, 24))
    for i in range(8):
        for j in range(3):
            BNL[3 * j: 3 * j + 3, 3 * i + j] = dN_dX[:, i]
    return BNL


def _BL_matrix(dN_dX: np.ndarray, F: np.ndarray) -> np.ndarray:
    """
    Linear part of the TL strain-displacement matrix BL (6×24).

    For the Green-Lagrange strain, BL maps incremental displacements δu
    to incremental strain δE:  δE = BL * δu

    Using the standard TL decomposition (Bathe 1996 §6.2):
      δE_ij = ½ (δu_{i,j} + δu_{j,i} + u_{k,i} δu_{k,j} + u_{k,j} δu_{k,i})
    Linearised form in Voigt (Belytschko & Liu "Nonlinear FEs" App. B):
      BL = BL0 + BLσ (initial-displacement part)
    """
    # 6 × 24
    BL = np.zeros((6, 24))
    # F columns: F[:, j] is the j-th column of F
    # For each node a (0..7), DOF indices: 3a, 3a+1, 3a+2
    for a in range(8):
        dNa = dN_dX[:, a]   # (3,) dN_a/dX_j

        # Columns for node a: cols 3a, 3a+1, 3a+2
        col0, col1, col2 = 3 * a, 3 * a + 1, 3 * a + 2

        # BL contribution for E_11, E_22, E_33, 2E_12, 2E_13, 2E_23
        # Using TL linearisation: δE_IJ = ½(F_kI δu_k,J + F_kJ δu_k,I)
        # Row 0: δE_11 = F_k1 δu_k,1
        BL[0, col0] = F[0, 0] * dNa[0]
        BL[0, col1] = F[1, 0] * dNa[0]
        BL[0, col2] = F[2, 0] * dNa[0]

        # Row 1: δE_22 = F_k2 δu_k,2
        BL[1, col0] = F[0, 1] * dNa[1]
        BL[1, col1] = F[1, 1] * dNa[1]
        BL[1, col2] = F[2, 1] * dNa[1]

        # Row 2: δE_33 = F_k3 δu_k,3
        BL[2, col0] = F[0, 2] * dNa[2]
        BL[2, col1] = F[1, 2] * dNa[2]
        BL[2, col2] = F[2, 2] * dNa[2]

        # Row 3: δ(2E_12) = F_k1 δu_k,2 + F_k2 δu_k,1
        BL[3, col0] = F[0, 0] * dNa[1] + F[0, 1] * dNa[0]
        BL[3, col1] = F[1, 0] * dNa[1] + F[1, 1] * dNa[0]
        BL[3, col2] = F[2, 0] * dNa[1] + F[2, 1] * dNa[0]

        # Row 4: δ(2E_13) = F_k1 δu_k,3 + F_k3 δu_k,1
        BL[4, col0] = F[0, 0] * dNa[2] + F[0, 2] * dNa[0]
        BL[4, col1] = F[1, 0] * dNa[2] + F[1, 2] * dNa[0]
        BL[4, col2] = F[2, 0] * dNa[2] + F[2, 2] * dNa[0]

        # Row 5: δ(2E_23) = F_k2 δu_k,3 + F_k3 δu_k,2
        BL[5, col0] = F[0, 1] * dNa[2] + F[0, 2] * dNa[1]
        BL[5, col1] = F[1, 1] * dNa[2] + F[1, 2] * dNa[1]
        BL[5, col2] = F[2, 1] * dNa[2] + F[2, 2] * dNa[1]

    return BL


# ===========================================================================
# Isotropic linear-elastic constitutive matrix (3-D, Voigt)
# ===========================================================================

def _elastic_C(E: float, nu: float) -> np.ndarray:
    """6×6 3-D isotropic elastic constitutive matrix (Voigt: 11,22,33,12,13,23)."""
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu  = E / (2.0 * (1.0 + nu))
    C = np.zeros((6, 6))
    # Normal-normal coupling
    for i in range(3):
        C[i, i] = lam + 2.0 * mu
        for j in range(3):
            if i != j:
                C[i, j] = lam
    # Shear
    C[3, 3] = mu
    C[4, 4] = mu
    C[5, 5] = mu
    return C


def _deviatoric_projector() -> np.ndarray:
    """6×6 volumetric-deviatoric projection: C_dev = C - (1/3) * C_vol * I_vol."""
    # Not needed directly; B-bar handles it at element level.
    pass


# ===========================================================================
# B-bar volumetric-locking suppression
# ===========================================================================

def _h8_bbar_element(X_e: np.ndarray, u_e: np.ndarray,
                     E: float, nu: float,
                     gp_state: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute H8 element stiffness K_e (24×24), internal force f_int (24,),
    and updated Gauss-point states using the B-bar formulation.

    B-bar = B_dev + B_vol_bar
    where B_vol_bar uses the mean dilatational strain (constant over element)
    in place of the pointwise dilatational part of B.

    Hughes (1980): replace the volumetric rows of BL by their mean over the
    element volume.  This cures volumetric locking in incompressible elasticity
    and nearly-incompressible plasticity.

    Parameters
    ----------
    X_e      : (8, 3)  reference nodal coords
    u_e      : (24,)   nodal displacements
    E, nu    : elastic constants
    gp_state : list[dict] — one dict per GP, each with keys:
                 'S' (2PK stress, 6-vec), 'alpha' (kin. hardening back-stress),
                 'eps_p_eq' (equiv. plastic strain scalar)

    Returns
    -------
    K_e  : (24, 24) tangent stiffness
    f_e  : (24,)    internal force
    gp_state (mutated in place with updated stresses)
    """
    C_el = _elastic_C(E, nu)
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu  = E / (2.0 * (1.0 + nu))

    gauss = [gp for (gp, _) in _GAUSS2]   # (-1/√3, 1/√3)
    weights = [w for (_, w) in _GAUSS2]

    n_gp = len(gauss) ** 3   # 8 for 2×2×2

    # ------------------------------------------------------------------ #
    # Step 1: compute mean B_vol_bar over the element (Hughes 1980)       #
    # ------------------------------------------------------------------ #
    # The volumetric part of BL is rows 0+1+2 contracted:
    #   B_vol = (1/3) [1,1,1,0,0,0]^T ⊗ BL_vol_row
    # where BL_vol_row = BL[0,:] + BL[1,:] + BL[2,:]
    # We average this over all GPs weighted by detJ.

    B_vol_sum = np.zeros(24)
    vol_total = 0.0

    gp_data = []   # cache (dN_dX, detJ, F, BL) per GP
    for i3, (xi, wi) in enumerate(_GAUSS2):
        for i2, (eta, we) in enumerate(_GAUSS2):
            for i1, (zeta, wz) in enumerate(_GAUSS2):
                dN_dX, detJ = _h8_dshape_dx(xi, eta, zeta, X_e)
                F = _deformation_gradient(dN_dX, u_e)
                BL = _BL_matrix(dN_dX, F)
                w = wi * we * wz * detJ
                # volumetric part of BL: sum of first 3 rows
                Bvol_row = BL[0, :] + BL[1, :] + BL[2, :]   # (24,)
                B_vol_sum += Bvol_row * w
                vol_total += w
                gp_data.append((xi, eta, zeta, dN_dX, detJ, F, BL, wi * we * wz))

    if abs(vol_total) < 1e-30:
        vol_total = 1.0
    B_vol_mean = B_vol_sum / vol_total   # (24,) — mean volumetric row

    # ------------------------------------------------------------------ #
    # Step 2: assemble K_e and f_e with B-bar (correct TL formulation)   #
    # ------------------------------------------------------------------ #
    # Key: for internal force, use the EXACT (nonlinear) Green-Lagrange
    # strain computed from F directly.  The BL matrix is used only for the
    # tangent stiffness (linearised around the current state).
    # B-bar correction applies to BOTH the strain measure (for f_int) and
    # the tangent rows (for K_mat).
    # ------------------------------------------------------------------ #

    # Compute mean volumetric Green-Lagrange strain (for B-bar correction)
    # E_vol_mean = (1/V) ∫ (E_11 + E_22 + E_33) dV
    E_vol_sum = 0.0
    for (xi, eta, zeta, dN_dX, detJ, F_gp, BL, w_raw) in gp_data:
        w = w_raw * detJ
        E_gl = _green_lagrange(F_gp)
        E_vol_sum += (E_gl[0] + E_gl[1] + E_gl[2]) * w
    E_vol_mean = E_vol_sum / vol_total   # mean volumetric GL strain

    K_e = np.zeros((24, 24))
    f_e = np.zeros(24)

    gp_idx = 0
    for (xi, eta, zeta, dN_dX, detJ, F_gp, BL, w_raw) in gp_data:
        w = w_raw * detJ

        # ---- Exact Green-Lagrange strain (nonlinear, for internal force) ----
        E_gl_exact = _green_lagrange(F_gp)   # (6,) exact at this GP

        # B-bar: replace volumetric part of strain with element mean
        # E_bar = E_dev + (E_vol_mean / 3) * [1,1,1,0,0,0]
        # where E_dev = E_exact - (E_vol/3)*[1,1,1,0,0,0]
        E_vol_gp = E_gl_exact[0] + E_gl_exact[1] + E_gl_exact[2]
        E_gl_bar = E_gl_exact.copy()
        for ii in range(3):
            E_gl_bar[ii] += (E_vol_mean - E_vol_gp) / 3.0

        # ---- Return mapping using B-bar strain (INCREMENTAL) ----
        state = gp_state[gp_idx]
        S_old = np.asarray(state['S'], dtype=float)
        alpha_old = np.asarray(state['alpha'], dtype=float)
        eps_p_eq_old = float(state['eps_p_eq'])
        E_gl_conv = np.asarray(state.get('E_gl_conv', [0.0]*6), dtype=float)

        S_new, alpha_new, eps_p_eq_new, C_alg = _return_map_3d(
            E_gl_bar, S_old, alpha_old, eps_p_eq_old,
            state['sigma_y0'], state['H_iso'], state['H_kin'], state['gamma_kin'],
            mu, lam,
            E_gl_conv=E_gl_conv,
        )

        # Update state (stress + back-stress; E_gl_conv updated ONLY at step end)
        state['S'] = S_new.tolist()
        state['alpha'] = alpha_new.tolist()
        state['eps_p_eq'] = eps_p_eq_new
        # Note: E_gl_conv is updated at Newton convergence (below, in _newton_step
        # and _arc_length_step); see _commit_step_states.

        # ---- B-bar matrix for tangent stiffness ----
        BL_bar = BL.copy()
        Bvol_point = BL[0, :] + BL[1, :] + BL[2, :]   # (24,) point volumetric row
        for ii in range(3):
            BL_bar[ii, :] += (1.0 / 3.0) * (B_vol_mean - Bvol_point)

        # Internal force: f_e += BL_bar^T S dV_0
        f_e += (BL_bar.T @ S_new) * w

        # Geometric (stress) stiffness
        BNL = _B_geometric(dN_dX)
        sigma_mat = _sigma_matrix_9x9(S_new, F_gp)
        K_geo = (BNL.T @ sigma_mat @ BNL) * w

        # Material stiffness: K_mat = BL_bar^T C_alg BL_bar dV_0
        K_mat = (BL_bar.T @ C_alg @ BL_bar) * w

        K_e += K_mat + K_geo
        gp_idx += 1

    return K_e, f_e, gp_state


def _sigma_matrix_9x9(S: np.ndarray, F: np.ndarray) -> np.ndarray:
    """
    Build the 9×9 stress matrix for the geometric stiffness in TL form.

    The 2nd PK stress S (Voigt 6-vec) is expanded to a 3×3 symmetric matrix
    S_mat, then tiled 3 times on the diagonal to form σ̂ (9×9) such that
    K_geo = ∫ BNL^T σ̂ BNL dV  (Hughes "The Finite Element Method" §8.2).

    In TL formulation the geometric stiffness uses the 2nd PK stress S pulled
    back to the reference configuration via F:
    Actually σ̂ for TL is the 2PK stress in block form — no F needed here
    because BNL already references the reference domain.
    """
    S11, S22, S33, S12, S13, S23 = S
    S_mat = np.array([[S11, S12, S13],
                      [S12, S22, S23],
                      [S13, S23, S33]])
    sigma9 = np.zeros((9, 9))
    for i in range(3):
        sigma9[3 * i: 3 * i + 3, 3 * i: 3 * i + 3] = S_mat
    return sigma9


# ===========================================================================
# J2 plasticity with isotropic + Armstrong-Frederick kinematic hardening
# Closest-point projection (CPP) return mapping
# Consistent algorithmic tangent (Simo & Taylor 1985)
# ===========================================================================

def _von_mises_norm(s: np.ndarray) -> float:
    """
    Von Mises equivalent stress from 3-D deviatoric stress vector (6-comp Voigt).
    σ_eq = √(3/2 * s : s)
    Voigt Shear factors: s = [s11,s22,s33, s12, s13, s23]
    s:s = s11²+s22²+s33² + 2(s12²+s13²+s23²)
    """
    return math.sqrt(1.5 * (s[0]**2 + s[1]**2 + s[2]**2
                            + 2.0 * (s[3]**2 + s[4]**2 + s[5]**2)))


def _deviatoric(sigma: np.ndarray) -> np.ndarray:
    """Deviatoric part of a 6-component Voigt stress."""
    p = (sigma[0] + sigma[1] + sigma[2]) / 3.0
    s = sigma.copy()
    s[0] -= p
    s[1] -= p
    s[2] -= p
    return s


def _return_map_3d(
    E_gl_new: np.ndarray,   # (6,) total Green-Lagrange strain at new state
    S_n: np.ndarray,        # (6,) 2PK stress at BEGINNING of load step (converged)
    alpha_n: np.ndarray,    # (6,) back-stress at beginning of load step
    eps_p_eq_n: float,      # accumulated equiv. plastic strain at beginning
    sigma_y0: float,        # initial yield stress [Pa]
    H_iso: float,           # isotropic hardening modulus [Pa]
    H_kin: float,           # kinematic hardening modulus C [Pa]  (A-F)
    gamma_kin: float,       # A-F saturation γ  (0 = linear kinematic)
    mu: float,              # shear modulus [Pa]
    lam: float,             # Lamé λ [Pa]
    E_gl_conv: np.ndarray | None = None,  # (6,) GL strain at beginning of step
) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """
    Closest-point projection return mapping for 3-D J2 plasticity with
    combined isotropic (linear) + Armstrong-Frederick kinematic hardening.

    Incremental form (correct for path-dependent plasticity):
      Delta_E = E_gl_new - E_gl_conv   (strain increment from converged state)
      S_trial = S_n + C_el : Delta_E   (elastic predictor)
    Then return-map from S_trial.

    If E_gl_conv is None, falls back to total-strain drive from zero
    (S_n and alpha_n should also be zero in that case).

    Returns (S_{n+1}, alpha_{n+1}, eps_p_eq_{n+1}, C_alg).

    Algorithm follows Simo & Hughes (1998) Algorithm 2.1 (Box 2.1).
    """
    C_el = _elastic_C_from_lam_mu(lam, mu)

    # --- Incremental strain ---
    if E_gl_conv is not None:
        Delta_E = E_gl_new - np.asarray(E_gl_conv)
    else:
        Delta_E = E_gl_new   # total-strain from zero (initial load step)

    # --- Trial stress (incremental elastic predictor) ---
    S_tr = S_n + C_el @ Delta_E
    # Deviatoric trial relative to back-stress
    s_tr = _deviatoric(S_tr)
    xi_tr = s_tr - alpha_n           # relative deviatoric trial stress

    sigma_y_n = sigma_y0 + H_iso * eps_p_eq_n
    norm_xi = _von_mises_norm(xi_tr)   # = √(3/2) ||xi_tr||_dev

    # --- Yield check ---
    f_tr = norm_xi - math.sqrt(2.0 / 3.0) * sigma_y_n

    if f_tr <= 0.0:
        # Elastic step
        return S_tr, alpha_n, eps_p_eq_n, C_el

    # --- Plastic step: Newton iteration for Δγ (scalar) ---
    # For combined linear-isotropic + A-F kinematic hardening, the consistency
    # condition leads to a scalar equation for the plastic multiplier Δγ.
    #
    # The consistency equation (Simo & Hughes §2.3.3 extended for A-F):
    #   f(Δγ) = ‖ξ_n1‖ - √(2/3) σ_y(Δγ) = 0
    #
    # where
    #   σ_y(Δγ) = σ_y0 + H_iso * (eps_p_eq_n + √(2/3) Δγ)
    #   ξ_{n+1} = (ξ_tr - √(6) μ Δγ n_tr) / (1 + γ_kin Δγ)
    #   n_tr    = ξ_tr / ‖ξ_tr‖ (unit deviatoric normal)
    # with ‖ξ‖ = ξ_eq = √(3/2) ||ξ||_voigt
    #
    # Derivation: A-F evolution  ȧ = C ε̇ᵖ - γ a ṗ → discrete:
    #   alpha_{n+1} = (alpha_n + H_kin √(2/3) Δγ n_tr) / (1 + gamma_kin Δγ)
    # Then ξ_{n+1} = s_{n+1} - alpha_{n+1} and the return direction stays n_tr.
    #
    # Substituting gives the scalar residual:
    #   g(Δγ) = (norm_xi_tr - 3μ Δγ) / (1 + gamma_kin Δγ)
    #           - H_kin √(2/3) Δγ / (1 + gamma_kin Δγ)
    #           - √(2/3) * [sigma_y0 + H_iso*(eps_p_eq_n + √(2/3) Δγ)] = 0
    # Note: norm_xi = √(3/2) ‖ξ‖_Voigt, so the 3μ factor converts Δγ to a
    # stress correction: 3μ = 2μ * (3/2) / 1 (using Voigt convention).
    # Specifically ‖Δs‖_eq = 2μ * Δγ * (3/2) × √(2/3) = √6 μ Δγ ... let's
    # keep it consistent with the Simo–Hughes convention:
    #   s_{n+1} = s_tr - 2μ Δγ n_tr  (using ṡ = 2μ ε̇ᵈᵉᵛ convention)
    # and ‖n_tr‖ in the j2 sense = √(3/2) → ‖Δs‖_j2 = 2μ Δγ √(3/2)
    # then ξ_eq decrease per unit Δγ = 2μ√(3/2).
    #
    # Unified scalar residual (Δγ ≥ 0):
    #   g(Δγ) = [norm_xi_tr - 2μ√(3/2) Δγ] / [1 + γ_kin Δγ]
    #            - H_kin√(2/3) Δγ / [1 + γ_kin Δγ]
    #            - √(2/3) σ_y(Δγ) = 0
    # with σ_y(Δγ) = σ_y0 + H_iso(εₚ_n + √(2/3)Δγ).

    sq23 = math.sqrt(2.0 / 3.0)
    sq32 = math.sqrt(3.0 / 2.0)
    two_mu = 2.0 * mu
    two_mu_sq32 = two_mu * sq32

    def _g(dgamma):
        denom = 1.0 + gamma_kin * dgamma
        xi_eq = (norm_xi - two_mu_sq32 * dgamma) / denom
        Hkin_term = H_kin * sq23 * dgamma / denom
        sigma_y = sigma_y0 + H_iso * (eps_p_eq_n + sq23 * dgamma)
        return xi_eq - Hkin_term - sq23 * sigma_y

    def _dg(dgamma):
        denom = 1.0 + gamma_kin * dgamma
        denom2 = denom * denom
        d_xi_eq = (-(two_mu_sq32) * denom - (norm_xi - two_mu_sq32 * dgamma) * gamma_kin) / denom2
        d_Hkin = H_kin * sq23 * (denom - dgamma * gamma_kin) / denom2
        d_sigma_y = sq23 * H_iso * sq23
        return d_xi_eq - d_Hkin - d_sigma_y

    # Newton solve for Δγ starting from elastic estimate
    dgamma = f_tr / (two_mu_sq32 + sq23 * sq23 * H_iso
                     + sq23 * H_kin / (1.0 + 1e-30))  # initial guess
    for _ in range(50):
        g_val = _g(dgamma)
        if abs(g_val) < 1e-12 * sigma_y0:
            break
        dg_val = _dg(dgamma)
        if abs(dg_val) < 1e-30:
            break
        dgamma -= g_val / dg_val
        if dgamma < 0.0:
            dgamma = 0.0

    dgamma = max(dgamma, 0.0)

    # Update direction
    n_tr = xi_tr / (norm_xi + 1e-30)   # (6,) unit normal in Voigt sense

    denom = 1.0 + gamma_kin * dgamma

    # Updated deviatoric relative stress
    xi_new_dev = (norm_xi - two_mu_sq32 * dgamma) / denom * n_tr

    # Back stress update (Armstrong-Frederick discrete)
    alpha_new = (alpha_n + H_kin * sq23 * dgamma * n_tr) / denom

    # Updated deviatoric stress s_{n+1} = xi_{n+1} + alpha_{n+1}
    s_new = xi_new_dev + alpha_new

    # Hydrostatic part unchanged by plastic flow (isochoric)
    p = (S_tr[0] + S_tr[1] + S_tr[2]) / 3.0
    S_new = s_new.copy()
    S_new[0] += p
    S_new[1] += p
    S_new[2] += p

    eps_p_eq_new = eps_p_eq_n + sq23 * dgamma

    # --- Consistent algorithmic tangent (Simo & Taylor 1985) ---
    C_alg = _consistent_tangent(S_tr, n_tr, dgamma, norm_xi, mu, lam,
                                H_iso, H_kin, gamma_kin, eps_p_eq_n)

    return S_new, alpha_new, eps_p_eq_new, C_alg


def _elastic_C_from_lam_mu(lam: float, mu: float) -> np.ndarray:
    """6×6 3-D isotropic elastic tensor from Lamé constants."""
    C = np.zeros((6, 6))
    for i in range(3):
        C[i, i] = lam + 2.0 * mu
        for j in range(3):
            if i != j:
                C[i, j] = lam
    C[3, 3] = mu
    C[4, 4] = mu
    C[5, 5] = mu
    return C


def _consistent_tangent(
    S_tr: np.ndarray,
    n_tr: np.ndarray,
    dgamma: float,
    norm_xi: float,
    mu: float,
    lam: float,
    H_iso: float,
    H_kin: float,
    gamma_kin: float,
    eps_p_eq_n: float,
) -> np.ndarray:
    """
    Consistent algorithmic tangent modulus C_alg (6×6, Voigt) for J2 plasticity
    with combined isotropic + Armstrong-Frederick kinematic hardening.

    Follows Simo & Hughes (1998) eq. (2.6.16) extended for A-F hardening.

    C_alg = C_el - A * (2μ)² β₁ (n⊗n)  -  A * 2μ β₂ I_dev_sym ... (simplified)
    For the full derivation see the implementation notes below.
    """
    C_el = _elastic_C_from_lam_mu(lam, mu)

    if dgamma <= 1e-30:
        return C_el

    # Scalars
    sq23 = math.sqrt(2.0 / 3.0)
    sq32 = math.sqrt(3.0 / 2.0)
    two_mu = 2.0 * mu
    denom = 1.0 + gamma_kin * dgamma

    # Effective hardening denominator for the scalar equation
    # θ = 2μ√(3/2) + (2/3)(H_iso + H_kin/denom)
    theta = two_mu * sq32 + sq23 * (H_iso + H_kin / denom) + \
            two_mu * sq32 * gamma_kin * dgamma / denom  # correction from A-F

    # β₁: scalar coefficient for (n⊗n) correction
    #   from ∂S/∂E = C_el - [2μ * n⊗(∂‖ξ_tr‖/∂S_tr) (2μ) - ...] / θ
    # Concisely (Simo & Taylor):
    beta1 = 1.0 - two_mu * sq32 * dgamma / (norm_xi + 1e-30)
    beta2 = 1.0 / (1.0 + (H_iso + H_kin / denom) * sq23 / (two_mu * sq32))
    # Equivalent: 2μ/θ × (...) for the correction

    # Compact form:  C_alg = beta1 * C_dev + C_vol + correction
    # where C_dev = C_el - C_vol  (deviatoric elastic)
    # and the correction removes the return-mapping part.

    # Build I_dev_sym (deviatoric projector, 6×6)
    # P_dev = I - (1/3) 1⊗1  in Voigt
    I6 = np.eye(6)
    one_vec = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
    P_dev = I6 - np.outer(one_vec, one_vec) / 3.0

    # Volumetric part of C_el
    C_vol = lam * np.outer(one_vec, one_vec)   # (6×6)
    C_dev_el = C_el - C_vol                     # (6×6)

    # Consistent tangent (corrected deviatoric + volumetric):
    # C_alg = C_el
    #       - (1 - beta1) * 2μ * P_dev                   (theta part, symmetric)
    #       - (1 - beta1) * 2μ * (n⊗n) (over-correction removal)
    #       + correction for consistent return

    # Simplified consistent tangent using the θ-notation:
    #   C_alg = C_el - (2μ)² [ (1/θ) * n⊗n + (Δγ/‖ξ‖) (P_dev - n⊗n) ]
    # This is the exact result for linear-combined hardening (Simo & Hughes 2.6.16).
    factor_nn = (two_mu ** 2) * (beta2 / (two_mu * sq32))
    factor_dev = (two_mu ** 2) * dgamma * sq32 / (norm_xi + 1e-30)

    # n⊗n outer product in Voigt
    nn = np.outer(n_tr, n_tr)

    C_alg = C_el - factor_nn * nn - factor_dev * (P_dev - nn)

    # Clamp: if dgamma is effectively zero, return C_el
    if dgamma < 1e-14:
        return C_el

    return C_alg


# ===========================================================================
# Global assembly (sparse)
# ===========================================================================

def _init_gp_state(sigma_y0: float, H_iso: float, H_kin: float,
                   gamma_kin: float, n_gp: int) -> list[dict]:
    """Initialise Gauss-point state list for one element.

    Each GP state stores:
      S          : 2nd PK stress (6-vec Voigt) at end of last CONVERGED step
      alpha      : Armstrong-Frederick back-stress at end of last CONVERGED step
      eps_p_eq   : accumulated equivalent plastic strain at end of last CONVERGED step
      E_gl_conv  : Green-Lagrange strain at end of last CONVERGED step (6-vec)
      sigma_y0, H_iso, H_kin, gamma_kin : material constants

    The incremental return map uses:
      Delta_E = E_gl_bar - E_gl_conv  (strain increment from converged state)
      S_trial  = S_n + C_el : Delta_E  (elastic predictor)
    """
    return [{
        'S': [0.0] * 6,
        'alpha': [0.0] * 6,
        'eps_p_eq': 0.0,
        'E_gl_conv': [0.0] * 6,   # converged GL strain (for incremental trial stress)
        'sigma_y0': sigma_y0,
        'H_iso': H_iso,
        'H_kin': H_kin,
        'gamma_kin': gamma_kin,
    } for _ in range(n_gp)]


def _assemble(
    nodes: np.ndarray,          # (n_nodes, 3)
    elements: list,             # list of 8-node lists
    u: np.ndarray,              # (n_dofs,) displacement
    E: float, nu: float,
    sigma_y0: float,
    H_iso: float, H_kin: float, gamma_kin: float,
    all_gp_states: list[list[dict]],   # [elem][gp] list of state dicts
) -> tuple[sp.csr_matrix, np.ndarray]:
    """
    Assemble global tangent stiffness K (sparse) and internal force R_int.

    Returns K (n_dofs × n_dofs, csr), R_int (n_dofs,).
    """
    n_nodes = nodes.shape[0]
    n_dofs = 3 * n_nodes
    n_elem = len(elements)

    rows, cols, vals = [], [], []
    R_int = np.zeros(n_dofs)

    for e_idx, conn in enumerate(elements):
        conn = list(conn)
        X_e = nodes[conn, :]              # (8, 3)
        dof_e = []
        for n_idx in conn:
            dof_e.extend([3 * n_idx, 3 * n_idx + 1, 3 * n_idx + 2])
        dof_e = np.array(dof_e, dtype=int)  # (24,)
        u_e = u[dof_e]                    # (24,)

        K_e, f_e, _ = _h8_bbar_element(
            X_e, u_e, E, nu,
            all_gp_states[e_idx]
        )

        R_int[dof_e] += f_e

        # Sparse assembly
        for i_local in range(24):
            for j_local in range(24):
                rows.append(dof_e[i_local])
                cols.append(dof_e[j_local])
                vals.append(K_e[i_local, j_local])

    K = sp.coo_matrix((vals, (rows, cols)), shape=(n_dofs, n_dofs)).tocsr()
    return K, R_int


def _apply_bcs(K: sp.csr_matrix, R: np.ndarray,
               fixed_dofs: list[int]) -> tuple[sp.csr_matrix, np.ndarray]:
    """
    Apply homogeneous Dirichlet BCs by zeroing rows/cols and setting diagonal.
    Modifies R in place and returns a new K.
    """
    K = K.tolil()
    for d in fixed_dofs:
        K[d, :] = 0.0
        K[:, d] = 0.0
        K[d, d] = 1.0
        R[d] = 0.0
    return K.tocsr(), R


# ===========================================================================
# Line search (golden section on step length α)
# ===========================================================================

def _line_search(
    u: np.ndarray,
    du: np.ndarray,
    f_ext: np.ndarray,
    fixed_dofs: list[int],
    nodes: np.ndarray,
    elements: list,
    E: float, nu: float,
    sigma_y0: float,
    H_iso: float, H_kin: float, gamma_kin: float,
    all_gp_states: list,
    max_iter: int = 8,
) -> float:
    """
    Golden-section line search to find α ∈ [0, 1] minimising ‖R(u + α du)‖₂.

    Returns α (scalar).  Falls back to α=1.0 if diverging.
    """
    phi = (math.sqrt(5.0) - 1.0) / 2.0  # golden ratio ≈ 0.618

    def _res_norm(alpha):
        u_trial = u + alpha * du
        _, R_int = _assemble(nodes, elements, u_trial,
                             E, nu, sigma_y0, H_iso, H_kin, gamma_kin,
                             # Use a deep copy of states so line search doesn't mutate
                             [
                                 [{k: (list(v) if isinstance(v, list) else v)
                                   for k, v in gp.items()} for gp in elem_states]
                                 for elem_states in all_gp_states
                             ])
        R = f_ext - R_int
        for d in fixed_dofs:
            R[d] = 0.0
        return float(np.linalg.norm(R))

    a, b = 0.0, 1.0
    fa = _res_norm(a)
    fb = _res_norm(b)

    if fb >= fa:
        # Step makes things worse — shrink
        for _ in range(max_iter):
            m = (a + b) / 2.0
            fm = _res_norm(m)
            if fm < fa:
                return m
            b = m
        return 0.1  # small safe step

    # Golden section
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc = _res_norm(c)
    fd = _res_norm(d)

    for _ in range(max_iter):
        if fc < fd:
            b = d
            d = c
            fd = fc
            c = b - phi * (b - a)
            fc = _res_norm(c)
        else:
            a = c
            c = d
            fc = fd
            d = a + phi * (b - a)
            fd = _res_norm(d)

    return (a + b) / 2.0


# ===========================================================================
# Deep-copy GP states
# ===========================================================================

def _copy_gp_states(states: list[list[dict]]) -> list[list[dict]]:
    return [
        [{k: (list(v) if isinstance(v, list) else v) for k, v in gp.items()}
         for gp in elem_states]
        for elem_states in states
    ]


def _commit_step_states(
    states: list[list[dict]],
    nodes: np.ndarray,
    elements: list,
    u: np.ndarray,
    E: float, nu: float,
) -> None:
    """
    After a load step converges, update E_gl_conv in each GP state to the
    current Green-Lagrange strain.  This enables correct incremental trial
    stress computation in subsequent load steps.

    Mutates `states` in place.
    """
    for e_idx, conn in enumerate(elements):
        conn = list(conn)
        X_e = nodes[conn, :]
        dof_e = []
        for n_idx in conn:
            dof_e.extend([3 * n_idx, 3 * n_idx + 1, 3 * n_idx + 2])
        dof_e = np.array(dof_e, dtype=int)
        u_e = u[dof_e]

        gauss = [gp for (gp, _) in _GAUSS2]
        gp_idx = 0
        for xi, _ in _GAUSS2:
            for eta, _ in _GAUSS2:
                for zeta, _ in _GAUSS2:
                    dN_dX, _ = _h8_dshape_dx(xi, eta, zeta, X_e)
                    F = _deformation_gradient(dN_dX, u_e)
                    E_gl = _green_lagrange(F)
                    states[e_idx][gp_idx]['E_gl_conv'] = E_gl.tolist()
                    gp_idx += 1


# ===========================================================================
# Newton-Raphson solver
# ===========================================================================

def _newton_step(
    u: np.ndarray,
    f_ext: np.ndarray,
    fixed_dofs: list[int],
    nodes: np.ndarray,
    elements: list,
    E: float, nu: float,
    sigma_y0: float,
    H_iso: float, H_kin: float, gamma_kin: float,
    all_gp_states: list,
    max_iter: int = 25,
    tol: float = 1e-6,
    line_search: bool = True,
) -> tuple[np.ndarray, int, bool, list]:
    """
    Full Newton-Raphson iteration to convergence for a given external force f_ext.

    Each Newton iteration evaluates R(u_cur) by assembling from the start-of-step
    GP states (all_gp_states).  The states_cur returned are those corresponding
    to the FINAL converged u_cur.

    Returns (u_new, iters, converged, updated_gp_states).
    """
    u_cur = u.copy()

    # Reference norm: use ||f_ext|| as normaliser (avoids double-assembly)
    ref_norm = max(float(np.linalg.norm(f_ext)), 1e-12)

    states_cur = _copy_gp_states(all_gp_states)   # will hold state at u_cur

    for it in range(max_iter):
        # Always assemble from the start-of-step converged states.
        # This is correct for incremental plasticity: the trial stress is
        #   S_tr = S_n + C_el : (E_gl(u_cur) - E_gl_conv)
        # where S_n and E_gl_conv are from the last CONVERGED step, not from
        # previous Newton iterations.
        states_iter = _copy_gp_states(all_gp_states)
        K, R_int = _assemble(nodes, elements, u_cur, E, nu, sigma_y0,
                             H_iso, H_kin, gamma_kin, states_iter)
        residual = f_ext - R_int
        for d in fixed_dofs:
            residual[d] = 0.0

        res_norm = float(np.linalg.norm(residual))

        if res_norm / ref_norm <= tol:
            # Converged: return the states corresponding to u_cur
            return u_cur, it, True, states_iter

        # Apply BCs to K
        K_bc, rhs_bc = _apply_bcs(K, residual.copy(), fixed_dofs)

        # Solve tangent system
        try:
            du = spla.spsolve(K_bc, rhs_bc)
        except Exception:
            return u_cur, it, False, states_iter

        if not np.isfinite(du).all():
            return u_cur, it, False, states_iter

        # Line search
        alpha = 1.0
        if line_search and it < 5:
            alpha = _line_search(
                u_cur, du, f_ext, fixed_dofs,
                nodes, elements, E, nu, sigma_y0,
                H_iso, H_kin, gamma_kin, all_gp_states
            )

        u_cur = u_cur + alpha * du

    # Max iters reached: return states at final u_cur
    states_final = _copy_gp_states(all_gp_states)
    _assemble(nodes, elements, u_cur, E, nu, sigma_y0,
              H_iso, H_kin, gamma_kin, states_final)
    return u_cur, max_iter, False, states_final


# ===========================================================================
# Arc-length continuation (Crisfield 1981 spherical)
# ===========================================================================

def _arc_length_step(
    u: np.ndarray,
    lam: float,
    f_ref: np.ndarray,
    ds: float,
    lam_scale: float,           # normalisation for λ in the constraint sphere
    fixed_dofs: list[int],
    nodes: np.ndarray,
    elements: list,
    E: float, nu: float,
    sigma_y0: float,
    H_iso: float, H_kin: float, gamma_kin: float,
    all_gp_states: list,
    max_iter: int = 25,
    tol: float = 1e-6,
    line_search_en: bool = True,
) -> tuple[np.ndarray, float, int, bool, list]:
    """
    Single Crisfield spherical arc-length predictor-corrector step.

    Spherical constraint:
      ‖u_{n+1} - u_n‖² + (Δλ / λ̄)² = Δs²

    Predictor: tangent vector from K_T δu_t = f_ref, normalised to ‖Δu_t‖² + (Δλ_t/λ̄)² = Δs².

    Corrector: Newton on the augmented residual
      R(u, λ) = f_int(u) - λ f_ref = 0
      c(u, λ) = ‖u - u_n‖² + ((λ - λ_n)/λ̄)² - Δs² = 0

    Returns (u_new, lam_new, iters, converged, updated_gp_states).
    """
    n_dof = len(u)

    # --- Predictor ---
    # Use start-of-step states for predictor tangent stiffness
    states_pred = _copy_gp_states(all_gp_states)
    K0, _ = _assemble(nodes, elements, u, E, nu, sigma_y0,
                      H_iso, H_kin, gamma_kin, states_pred)
    K_bc, f_bc = _apply_bcs(K0, f_ref.copy(), fixed_dofs)
    try:
        du_t = spla.spsolve(K_bc, f_bc)
    except Exception:
        return u, lam, 0, False, all_gp_states

    if not np.isfinite(du_t).all():
        return u, lam, 0, False, all_gp_states

    # Normalise predictor to arc-length ds
    dlam_t_unnorm = 1.0  # unit load increment
    norm2 = float(np.dot(du_t, du_t)) + (dlam_t_unnorm / lam_scale) ** 2
    scale = ds / math.sqrt(norm2) if norm2 > 0 else 1.0
    du_pred = du_t * scale
    dlam_pred = dlam_t_unnorm * scale

    u_new = u + du_pred
    lam_new = lam + dlam_pred

    states_final = _copy_gp_states(all_gp_states)

    # --- Corrector Newton loop ---
    # Each corrector iteration assembles from all_gp_states (start of step).
    # This is the correct incremental formulation: the trial stress at each
    # corrector iterate is computed relative to the START of this arc step.
    for it in range(max_iter):
        states_iter = _copy_gp_states(all_gp_states)
        K, R_int = _assemble(nodes, elements, u_new, E, nu, sigma_y0,
                             H_iso, H_kin, gamma_kin, states_iter)

        # Mechanical residual
        R_mech = lam_new * f_ref - R_int
        for d in fixed_dofs:
            R_mech[d] = 0.0

        res_norm = float(np.linalg.norm(R_mech))
        ref = max(float(np.linalg.norm(f_ref)) * abs(lam_new), 1e-12)
        if res_norm / ref <= tol:
            return u_new, lam_new, it + 1, True, states_iter

        # Arc-length constraint residual
        du_step = u_new - u
        c_val = float(np.dot(du_step, du_step)) + (
            (lam_new - lam) / lam_scale) ** 2 - ds ** 2

        # Solve two systems: K du_R = R_mech,  K du_f = f_ref
        K_bc_c = K.tolil()
        for d in fixed_dofs:
            K_bc_c[d, :] = 0.0
            K_bc_c[:, d] = 0.0
            K_bc_c[d, d] = 1.0
        K_bc_c = K_bc_c.tocsr()

        f_bc_ref = f_ref.copy()
        for d in fixed_dofs:
            f_bc_ref[d] = 0.0

        try:
            du_R = spla.spsolve(K_bc_c, R_mech)
            du_f = spla.spsolve(K_bc_c, f_bc_ref)
        except Exception:
            return u_new, lam_new, it + 1, False, states_iter

        if not (np.isfinite(du_R).all() and np.isfinite(du_f).all()):
            return u_new, lam_new, it + 1, False, states_iter

        # Solve for Δλ_c from linearised arc constraint:
        #   2 du_step·(du_R + Δλ_c du_f) + 2(Δλ_step/λ̄²)(Δλ_c) = -c_val
        #   (ignoring second-order terms in Δλ_c from the constraint)
        a1 = float(np.dot(du_step, du_R))
        a2 = float(np.dot(du_step, du_f)) + (lam_new - lam) / (lam_scale ** 2)
        if abs(a2) < 1e-30:
            dlam_c = 0.0
        else:
            dlam_c = -(a1 + 0.5 * c_val) / a2

        du_c = du_R + dlam_c * du_f

        # Optional line search on corrector step
        alpha_c = 1.0
        if line_search_en:
            f_ext_c = (lam_new + dlam_c) * f_ref
            alpha_c = _line_search(
                u_new, du_c, f_ext_c, fixed_dofs,
                nodes, elements, E, nu, sigma_y0,
                H_iso, H_kin, gamma_kin, all_gp_states, max_iter=4
            )

        u_new = u_new + alpha_c * du_c
        lam_new = lam_new + alpha_c * dlam_c
        states_final = states_iter   # keep most recent

    return u_new, lam_new, max_iter, False, states_final


# ===========================================================================
# Main public solver
# ===========================================================================

def solve_nonlinear_static(model: dict) -> dict[str, Any]:
    """
    3-D nonlinear static FEM solver with Newton-Raphson and arc-length continuation.

    See module docstring for full parameter documentation.
    """
    try:
        return _solve_inner(model)
    except Exception as exc:
        import traceback
        return {"ok": False,
                "reason": f"unexpected error: {exc}",
                "traceback": traceback.format_exc(),
                "path": [], "warnings": []}


def _solve_inner(model: dict) -> dict[str, Any]:
    # --- Parse inputs ---
    nodes_in = model.get("nodes")
    elements_in = model.get("elements")
    if nodes_in is None or elements_in is None:
        return {"ok": False, "reason": "model must have 'nodes' and 'elements'",
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

    E      = float(model.get("E", 200e9))
    nu     = float(model.get("nu", 0.3))
    sigma_y0 = float(model.get("sigma_y0", 1e30))
    H_iso  = float(model.get("H_iso", 0.0))
    H_kin  = float(model.get("H_kin", 0.0))
    gamma_kin = float(model.get("gamma_kin", 0.0))

    if E <= 0:
        return {"ok": False, "reason": "E must be positive", "path": [], "warnings": []}
    if not (-1.0 < nu < 0.5):
        return {"ok": False, "reason": f"nu={nu} outside (-1, 0.5)", "path": [], "warnings": []}

    n_nodes = nodes.shape[0]
    n_dofs  = 3 * n_nodes
    n_elem  = len(elements)

    fixed_dofs_raw = model.get("fixed_dofs", [])
    fixed_dofs = [int(d) for d in fixed_dofs_raw if 0 <= int(d) < n_dofs]

    loads_raw = model.get("loads", [])
    f_ref = np.zeros(n_dofs)
    for load in loads_raw:
        dof, force = int(load[0]), float(load[1])
        if 0 <= dof < n_dofs:
            f_ref[dof] += force

    n_steps     = int(model.get("n_steps", 10))
    arc_length  = bool(model.get("arc_length", False))
    ds          = float(model.get("ds", 1.0))
    max_iter    = int(model.get("max_iter", 25))
    tol         = float(model.get("tol", 1e-6))
    ls_enabled  = bool(model.get("line_search", True))
    max_ls_iter = int(model.get("max_ls_iter", 6))

    # Initialise GP states (8 GPs per H8 element)
    n_gp = 8
    all_gp_states = [
        _init_gp_state(sigma_y0, H_iso, H_kin, gamma_kin, n_gp)
        for _ in range(n_elem)
    ]

    u = np.zeros(n_dofs)
    lam = 0.0
    path = []
    warnings_out = []

    if not arc_length:
        # ---- Incremental Newton-Raphson ----
        dlam = 1.0 / max(n_steps, 1)
        for step in range(n_steps):
            lam_target = (step + 1) * dlam
            f_ext = lam_target * f_ref

            u_new, iters, conv, states_new = _newton_step(
                u, f_ext, fixed_dofs,
                nodes, elements,
                E, nu, sigma_y0, H_iso, H_kin, gamma_kin,
                all_gp_states, max_iter, tol, ls_enabled
            )

            if not conv:
                warnings_out.append(
                    f"Step {step}: Newton did not converge in {max_iter} iters"
                    f" (λ={lam_target:.4g})"
                )

            u = u_new
            lam = lam_target
            all_gp_states = states_new
            # Commit converged GL strain so next step has correct incremental basis
            _commit_step_states(all_gp_states, nodes, elements, u, E, nu)

            path.append({
                "step": step,
                "lambda": float(lam),
                "displacements": u.tolist(),
                "iters": iters,
                "converged": conv,
                "limit_point": False,
            })

    else:
        # ---- Crisfield arc-length continuation ----
        # λ̄ normalisation (Crisfield 1991 §9.4):
        # The spherical constraint is  ‖Δu‖² + (Δλ/λ̄)² = Δs².
        # Set λ̄ = 1.0 (Riks / Crisfield original) so the load factor
        # increments directly in the arc-length space.  For problems where
        # displacement and load have very different scales, a user-supplied
        # lam_scale parameter (exposed in the model dict) can be used.
        lam_scale = float(model.get("lam_scale", 1.0))

        prev_lam = 0.0
        adaptive_ds = ds

        for step in range(n_steps):
            u_new, lam_new, iters, conv, states_new = _arc_length_step(
                u, lam, f_ref, adaptive_ds, lam_scale,
                fixed_dofs,
                nodes, elements,
                E, nu, sigma_y0, H_iso, H_kin, gamma_kin,
                all_gp_states, max_iter, tol, ls_enabled
            )

            if not conv:
                # Halve arc-length and retry
                adaptive_ds *= 0.5
                u_new, lam_new, iters, conv, states_new = _arc_length_step(
                    u, lam, f_ref, adaptive_ds, lam_scale,
                    fixed_dofs,
                    nodes, elements,
                    E, nu, sigma_y0, H_iso, H_kin, gamma_kin,
                    all_gp_states, max_iter, tol, ls_enabled
                )
                if not conv:
                    warnings_out.append(
                        f"Arc-length step {step}: corrector did not converge "
                        f"in {max_iter} iters (ds={adaptive_ds:.3e}, λ={lam_new:.4g})"
                    )

            # Limit-point detection: λ decreases after having increased
            limit_point = False
            if step > 0 and lam_new < lam and lam > 0.0:
                limit_point = True
                warnings_out.append(
                    f"Limit point detected at step {step}: "
                    f"λ reversal {lam:.4g} → {lam_new:.4g}"
                )

            u = u_new
            prev_lam = lam
            lam = lam_new
            all_gp_states = states_new
            # Commit converged GL strain so next arc step has correct incremental basis
            _commit_step_states(all_gp_states, nodes, elements, u, E, nu)

            # Adaptive step-size: grow if converged quickly
            if conv and iters <= max_iter // 3:
                adaptive_ds = min(adaptive_ds * 1.5, ds * 4.0)
            elif not conv:
                adaptive_ds = max(adaptive_ds, ds * 0.01)

            path.append({
                "step": step,
                "lambda": float(lam),
                "displacements": u.tolist(),
                "iters": iters,
                "converged": conv,
                "limit_point": limit_point,
            })

    return {"ok": True, "path": path, "warnings": warnings_out}


# ===========================================================================
# Convenience test helper (also used by the test suite)
# ===========================================================================

def _unit_cube_element(dx=1.0, dy=1.0, dz=1.0, offset=(0.0, 0.0, 0.0)):
    """Return (nodes, elements) for a single H8 unit-cube element.

    Node ordering matches the H8 convention used in _h8_shape:
      0: (-1,-1,-1) corner → (0,0,0)
      1: (+1,-1,-1) corner → (dx,0,0)
      etc.
    """
    ox, oy, oz = offset
    nodes = np.array([
        [ox,      oy,      oz     ],
        [ox + dx, oy,      oz     ],
        [ox + dx, oy + dy, oz     ],
        [ox,      oy + dy, oz     ],
        [ox,      oy,      oz + dz],
        [ox + dx, oy,      oz + dz],
        [ox + dx, oy + dy, oz + dz],
        [ox,      oy + dy, oz + dz],
    ])
    elements = [[0, 1, 2, 3, 4, 5, 6, 7]]
    return nodes, elements


# ===========================================================================
# LLM tool registration
# ===========================================================================

_fem_nonlinear_static_spec = ToolSpec(
    name="fem_nonlinear_static",
    description=(
        "3-D nonlinear static finite-element analysis using Total-Lagrangian "
        "formulation.  Supports large-deformation (geometric nonlinearity via "
        "Green-Lagrange strain + 2nd Piola-Kirchhoff stress), J2 plasticity "
        "with combined isotropic and Armstrong-Frederick kinematic hardening "
        "(closest-point return mapping, consistent tangent), and arc-length "
        "continuation (Crisfield 1981 spherical method) for post-buckling / "
        "snap-through / snap-back path tracing.  Element: 8-node hexahedron "
        "(H8) with B-bar volumetric-locking suppression.  Solver: Newton-"
        "Raphson with optional golden-section line search; adaptive arc-length "
        "step halving on non-convergence.  Returns full load-displacement path."
    ),
    input_schema={
        "type": "object",
        "required": ["nodes", "elements", "E", "nu", "fixed_dofs", "loads"],
        "properties": {
            "nodes": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"},
                          "minItems": 3, "maxItems": 3},
                "description": "List of [x, y, z] reference nodal coordinates (n_nodes × 3).",
            },
            "elements": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"},
                          "minItems": 8, "maxItems": 8},
                "description": "H8 element connectivity: list of 8-node lists (0-based).",
            },
            "E":          {"type": "number", "description": "Young's modulus [Pa]"},
            "nu":         {"type": "number", "description": "Poisson ratio"},
            "sigma_y0":   {"type": "number", "description": "Initial yield stress [Pa] (1e30 = elastic)"},
            "H_iso":      {"type": "number", "description": "Isotropic hardening modulus [Pa]"},
            "H_kin":      {"type": "number", "description": "Armstrong-Frederick kinematic hardening C [Pa]"},
            "gamma_kin":  {"type": "number", "description": "Armstrong-Frederick saturation γ"},
            "fixed_dofs": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of DOF indices to constrain (3·node + 0/1/2 for x/y/z).",
            },
            "loads": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "Reference load list: [[dof_index, force_value], ...]",
            },
            "n_steps":     {"type": "integer", "description": "Number of load/arc-length steps"},
            "arc_length":  {"type": "boolean", "description": "Use Crisfield arc-length continuation"},
            "ds":          {"type": "number",  "description": "Arc-length increment"},
            "max_iter":    {"type": "integer", "description": "Max Newton corrector iterations per step"},
            "tol":         {"type": "number",  "description": "Relative residual tolerance"},
            "line_search": {"type": "boolean", "description": "Enable golden-section line search"},
        },
    },
)


@register(_fem_nonlinear_static_spec)
async def run_fem_nonlinear_static(ctx: ProjectCtx, args: bytes) -> str:
    import json
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    required = ["nodes", "elements", "E", "nu", "fixed_dofs", "loads"]
    missing = [k for k in required if k not in a]
    if missing:
        return err_payload(f"missing required fields: {missing}", "BAD_ARGS")

    result = solve_nonlinear_static(a)
    return json.dumps(result)


# ===========================================================================
# MITC4 shell path — deferred to T-100-C
# ===========================================================================
# The existing kerf_fem.plate module provides a linear-static MITC4 solver.
# Integrating MITC4 into the nonlinear-static driver requires:
#   (a) Corotational formulation for finite rotations (Crisfield Vol.2, Ch.17)
#   (b) Drilling DOF treatment (Ibrahimbegovic 1994)
#   (c) Finite rotation update (quaternion or rotation vector)
#   (d) Coupling with the arc-length constraint (6-DOF tangent predictor)
# This is deferred to T-100-C; all H8 solid paths are fully implemented
# and tested.
