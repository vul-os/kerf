"""
kerf_mates.mbd.flexible_body — Craig-Bampton flexible-body reduction for MBD.

Theory
------
Craig-Bampton (1968) component-mode synthesis partitions the DOFs of a finite-
element model into *interface* (boundary) DOFs and *internal* DOFs.  The
transformation to a reduced basis is:

    T_CB = [  I           0       ]   interface (kept exactly)
            [ Φ_c    Φ_n  ]   internal (constraint modes + normal modes)

where
  Φ_c  = -K_ii^{-1} K_ib   (static constraint modes from unit interface disp.)
  Φ_n  = subset of fixed-interface normal modes

This reduction yields a small (n_interface + n_internal_modes) system with
preserved boundary interface accuracy and well-conditioned modal coordinates.

Time integration uses Newmark-β (β=1/4, γ=1/2 — constant-average-acceleration,
unconditionally stable) for both rigid-body pose and modal coordinates.

References
----------
Craig, R.R., Bampton, M.C.C. (1968). "Coupling of Substructures for Dynamic
    Analysis." AIAA Journal, 6(7), 1313-1319.
    https://doi.org/10.2514/3.4741

Disclaimer: for design exploration only — not Adams MSC-accurate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FlexBody:
    """Flexible body with Craig-Bampton reduced representation.

    The rigid-body inertia is the 6×6 spatial (Plucker) inertia tensor stored
    in a 4×4 block for convenience:  [[m*I3, 0], [0, I3x3]] — the off-diagonal
    first-moment terms are set to zero (body-fixed CG frame).

    References: Craig & Bampton (1968); Shabana, "Dynamics of Multibody
    Systems", 4th ed., Ch. 5.
    """
    name: str
    # 4×4 block encoding 6×6 spatial inertia:
    #   top-left  3×3 = mass*I  (translational)
    #   bot-right 3×3 = I_body  (rotational)
    rigid_body_inertia: np.ndarray          # (4, 4) — see above
    mode_shapes: np.ndarray                 # (n_modes, n_dof) modal matrix Φ
    modal_freqs: np.ndarray                 # (n_modes,) natural frequencies [Hz]
    modal_damping: np.ndarray               # (n_modes,) damping ratio ζ (e.g. 0.02)
    interface_dof: list[int]                # global DOF indices of attached nodes


@dataclass
class FlexBodyState:
    """Full state of a flexible body at one instant."""
    rigid_pose: np.ndarray                  # (4, 4) homogeneous world transform
    rigid_twist: np.ndarray                 # (6,) spatial velocity [v; ω]
    modal_coords: np.ndarray                # (n_modes,) generalised coords η
    modal_rates: np.ndarray                 # (n_modes,) η̇


# ---------------------------------------------------------------------------
# Craig-Bampton reduction
# ---------------------------------------------------------------------------

def _solve_upper_triangular(U: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Back-substitution for an upper-triangular system Ux = b (no scipy)."""
    n = U.shape[0]
    x = np.zeros_like(b, dtype=float)
    for i in range(n - 1, -1, -1):
        x[i] = b[i]
        for j in range(i + 1, n):
            x[i] -= U[i, j] * x[j]
        x[i] /= U[i, i]
    return x


def _cholesky(A: np.ndarray) -> np.ndarray:
    """Lower-triangular Cholesky factor of a symmetric positive-definite matrix
    (pure numpy, no scipy)."""
    n = A.shape[0]
    L = np.zeros_like(A, dtype=float)
    for i in range(n):
        for j in range(i + 1):
            s = A[i, j] - float(np.dot(L[i, :j], L[j, :j]))
            if i == j:
                if s <= 0.0:
                    # Near-singular: clamp to small positive
                    s = max(s, 1e-30)
                L[i, j] = math.sqrt(s)
            else:
                if abs(L[j, j]) < 1e-30:
                    L[i, j] = 0.0
                else:
                    L[i, j] = s / L[j, j]
    return L


def _solve_spd(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Solve AX = B for symmetric positive-definite A without scipy.

    Uses numpy.linalg.solve (LAPACK LU) — the "no scipy" constraint applies to
    eigensolvers and sparse libs; numpy's own linalg is universally available.
    """
    return np.linalg.solve(A, B)


def _fixed_interface_modes(
    K_ii: np.ndarray,
    M_ii: np.ndarray,
    n_modes: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute n_modes lowest-frequency normal modes of the fixed-interface system.

    Solves the symmetric generalised eigenvalue problem K_ii Φ = M_ii Φ Λ
    using numpy.linalg.eigh (real symmetric — no scipy needed).

    Returns
    -------
    (freqs_hz, Phi_n)  where freqs_hz is (n_modes,) in Hz and
                       Phi_n is (n_dof_internal, n_modes).
    """
    # numpy.linalg.eigh solves the standard eigenproblem; convert to generalised
    # via Cholesky transformation: K_ii Φ = λ M_ii Φ  →  L^{-1} K_ii L^{-T} y = λ y
    L = np.linalg.cholesky(M_ii)
    L_inv = np.linalg.inv(L)
    K_tilde = L_inv @ K_ii @ L_inv.T
    # Symmetrise to guard against floating-point asymmetry
    K_tilde = 0.5 * (K_tilde + K_tilde.T)
    eigenvalues, eigenvectors = np.linalg.eigh(K_tilde)

    # Back-transform
    Phi_all = L_inv.T @ eigenvectors                # (n_internal, n_internal)

    # Keep only positive eigenvalues (rigid-body modes have λ≈0 or negative)
    valid = eigenvalues > 0
    eigenvalues = eigenvalues[valid]
    Phi_all = Phi_all[:, valid]

    # Sort ascending
    idx = np.argsort(eigenvalues)
    eigenvalues = eigenvalues[idx]
    Phi_all = Phi_all[:, idx]

    # Pick n_modes (or however many are available)
    n_keep = min(n_modes, Phi_all.shape[1])
    freqs_hz = np.sqrt(np.maximum(eigenvalues[:n_keep], 0.0)) / (2.0 * math.pi)
    Phi_n = Phi_all[:, :n_keep]                     # (n_internal, n_keep)
    return freqs_hz, Phi_n


def craig_bampton_reduce(
    full_stiffness: np.ndarray,     # (N, N)
    full_mass: np.ndarray,           # (N, N)
    interface_dof: list[int],
    n_internal_modes: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Craig-Bampton (1968) modal synthesis.

    Parameters
    ----------
    full_stiffness : (N, N) global stiffness matrix
    full_mass      : (N, N) global mass matrix
    interface_dof  : list of DOF indices designated as interface/boundary DOFs
    n_internal_modes : number of fixed-interface normal modes to retain

    Returns
    -------
    T_CB    : (N, n_b + n_internal_modes) Craig-Bampton transformation matrix
    K_red   : (n_b+n_m, n_b+n_m) reduced stiffness  where n_b=len(interface_dof)
    M_red   : (n_b+n_m, n_b+n_m) reduced mass

    Reference: Craig & Bampton (1968), AIAA J 6(7), §2.
    """
    N = full_stiffness.shape[0]
    n_b = len(interface_dof)

    # Partition DOFs
    all_dof = list(range(N))
    internal_dof = [d for d in all_dof if d not in interface_dof]
    n_i = len(internal_dof)

    b_idx = np.array(interface_dof, dtype=int)
    i_idx = np.array(internal_dof, dtype=int)

    # Sub-matrices
    K_bb = full_stiffness[np.ix_(b_idx, b_idx)]
    K_bi = full_stiffness[np.ix_(b_idx, i_idx)]
    K_ib = full_stiffness[np.ix_(i_idx, b_idx)]
    K_ii = full_stiffness[np.ix_(i_idx, i_idx)]

    M_bb = full_mass[np.ix_(b_idx, b_idx)]
    M_bi = full_mass[np.ix_(b_idx, i_idx)]
    M_ib = full_mass[np.ix_(i_idx, b_idx)]
    M_ii = full_mass[np.ix_(i_idx, i_idx)]

    # Static constraint modes: Φ_c = -K_ii^{-1} K_ib  shape (n_i, n_b)
    Phi_c = -_solve_spd(K_ii, K_ib)

    # Fixed-interface normal modes
    freqs_hz, Phi_n = _fixed_interface_modes(K_ii, M_ii, n_internal_modes)
    n_m = Phi_n.shape[1]

    # Build Craig-Bampton transformation matrix T_CB  (N, n_b + n_m)
    # Layout:  rows correspond to physical DOF order [interface | internal]
    # T_CB (reordered) = [ I      0   ] boundary rows
    #                    [ Phi_c  Phi_n] internal rows
    T_CB_reordered = np.zeros((N, n_b + n_m))

    # Interface rows
    for local_j, global_i in enumerate(b_idx):
        T_CB_reordered[global_i, local_j] = 1.0

    # Internal rows
    for local_i, global_i in enumerate(i_idx):
        T_CB_reordered[global_i, :n_b] = Phi_c[local_i, :]
        T_CB_reordered[global_i, n_b:n_b + n_m] = Phi_n[local_i, :]

    T_CB = T_CB_reordered
    K_red = T_CB.T @ full_stiffness @ T_CB
    M_red = T_CB.T @ full_mass @ T_CB

    return T_CB, K_red, M_red


# ---------------------------------------------------------------------------
# Newmark-β time integration
# ---------------------------------------------------------------------------

# Newmark constants: average-constant-acceleration (β=1/4, γ=1/2)
_NEWMARK_BETA = 0.25
_NEWMARK_GAMMA = 0.50


def _build_modal_matrices(body: FlexBody) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return diagonal modal K and C matrices from body parameters.

    For each mode r:
        ω_r = 2π f_r
        k_r = ω_r²         (modal stiffness, mass-normalised)
        c_r = 2 ζ_r ω_r    (modal damping, mass-normalised)
    """
    n = len(body.modal_freqs)
    omega_r = 2.0 * math.pi * body.modal_freqs        # (n,)
    k_diag = omega_r ** 2                              # (n,)
    c_diag = 2.0 * body.modal_damping * omega_r       # (n,)
    # Diagonal matrices (stored as 1-D vectors for efficiency)
    return k_diag, c_diag, omega_r


def step_flex_body(
    state: FlexBodyState,
    body: FlexBody,
    applied_forces: np.ndarray,   # (n_modes,) generalised modal forces
    dt: float,
) -> FlexBodyState:
    """Newmark-β integration of rigid pose + modal coordinates (one step).

    Rigid-body motion is integrated with a first-order (Euler) update in SE(3)
    via the spatial velocity twist; the modal equations are solved with the
    constant-average-acceleration Newmark scheme (β=1/4, γ=1/2) which is
    unconditionally stable for linear systems.

    Modal equation of motion (mass-normalised):
        η̈ + diag(c_r) η̇ + diag(k_r) η = f_modal

    where f_modal = Φ^T F_physical (projected applied forces).

    References
    ----------
    Newmark, N.M. (1959). "A Method of Computation for Structural Dynamics."
        ASCE J. Engineering Mechanics, 85(3), 67-94.
    Craig & Bampton (1968) AIAA J 6(7).
    """
    n_modes = len(body.modal_freqs)
    if n_modes == 0:
        # No flex modes — just rigid integration
        return _step_rigid(state, body, dt)

    k_diag, c_diag, _ = _build_modal_matrices(body)

    # ── Modal acceleration at t_n ──────────────────────────────────────────
    # η̈_n = f_modal_n - c_r η̇_n - k_r η_n
    eta_ddot_n = applied_forces - c_diag * state.modal_rates - k_diag * state.modal_coords

    # ── Newmark predictor ──────────────────────────────────────────────────
    eta_pred = (state.modal_coords
                + dt * state.modal_rates
                + dt**2 * (0.5 - _NEWMARK_BETA) * eta_ddot_n)
    eta_dot_pred = state.modal_rates + dt * (1.0 - _NEWMARK_GAMMA) * eta_ddot_n

    # ── Effective stiffness per mode: k_eff = 1 + β dt² k_r + γ dt c_r ───
    k_eff = (1.0
             + _NEWMARK_BETA * dt**2 * k_diag
             + _NEWMARK_GAMMA * dt * c_diag)

    # ── Solve for η̈_{n+1} (diagonal system) ──────────────────────────────
    residual = applied_forces - c_diag * eta_dot_pred - k_diag * eta_pred
    eta_ddot_new = residual / k_eff

    # ── Corrector ─────────────────────────────────────────────────────────
    eta_new = eta_pred + _NEWMARK_BETA * dt**2 * eta_ddot_new
    eta_dot_new = eta_dot_pred + _NEWMARK_GAMMA * dt * eta_ddot_new

    # ── Rigid-body integration (first-order exponential on SE(3)) ─────────
    new_pose, new_twist = _step_rigid_pose(state.rigid_pose, state.rigid_twist, dt)

    return FlexBodyState(
        rigid_pose=new_pose,
        rigid_twist=new_twist,
        modal_coords=eta_new,
        modal_rates=eta_dot_new,
    )


def _step_rigid(state: FlexBodyState, body: FlexBody, dt: float) -> FlexBodyState:
    """Rigid-only step (no modal DOF)."""
    new_pose, new_twist = _step_rigid_pose(state.rigid_pose, state.rigid_twist, dt)
    return FlexBodyState(
        rigid_pose=new_pose,
        rigid_twist=state.rigid_twist.copy(),
        modal_coords=state.modal_coords.copy(),
        modal_rates=state.modal_rates.copy(),
    )


def _step_rigid_pose(
    pose: np.ndarray,       # (4, 4) SE(3) transform
    twist: np.ndarray,      # (6,) [vx, vy, vz, wx, wy, wz]
    dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Integrate rigid body pose one step using first-order SE(3) exponential map.

    For small dt, T_{n+1} ≈ T_n · exp(dt · [ξ]) where [ξ] is the 4×4 twist
    matrix in se(3).  We use the closed-form Rodrigues formula.
    """
    v = twist[:3]   # linear velocity
    w = twist[3:]   # angular velocity

    theta = float(np.linalg.norm(w))
    if theta < 1e-12:
        # Pure translation
        R_delta = np.eye(3)
        p_delta = v * dt
    else:
        # Rodrigues' rotation formula
        w_hat = w / theta
        angle = theta * dt
        K = _skew(w_hat)
        R_delta = (np.eye(3)
                   + math.sin(angle) * K
                   + (1.0 - math.cos(angle)) * K @ K)
        # Linear velocity in body frame
        p_delta = (v * dt
                   + ((1.0 - math.cos(angle)) / theta) * np.cross(w_hat, v)
                   + (dt - math.sin(angle) / theta) * np.dot(w_hat, v) * w_hat)

    T_delta = np.eye(4)
    T_delta[:3, :3] = R_delta
    T_delta[:3, 3] = p_delta

    new_pose = pose @ T_delta
    return new_pose, twist.copy()


def _skew(v: np.ndarray) -> np.ndarray:
    """3×3 skew-symmetric matrix for cross product."""
    return np.array([
        [0.0,   -v[2],  v[1]],
        [v[2],   0.0,  -v[0]],
        [-v[1],  v[0],   0.0],
    ])


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_flex_body_state(body: FlexBody) -> FlexBodyState:
    """Create a zeroed initial state for a FlexBody."""
    n = len(body.modal_freqs)
    return FlexBodyState(
        rigid_pose=np.eye(4),
        rigid_twist=np.zeros(6),
        modal_coords=np.zeros(n),
        modal_rates=np.zeros(n),
    )
