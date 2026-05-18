# TODO: Depends on sibling-created package scaffold
"""p-k Flutter Method (NASTRAN / Hassig 1971).

Implements the p-k flutter eigenvalue iteration method described by:

    Hassig, H.J. (1971).  "An approximate true damping solution of the flutter
    equation by iteration."  Journal of Aircraft, 8(11):885-889.

The equation of motion for a structure with aerodynamic loading in the
frequency domain is:

    [-ω² M_modal + iω ωR B_modal + K_modal + (½ρV²) Q(k, M)] x = 0

where
    M_modal, B_modal, K_modal : modal mass, damping and stiffness (diagonal for
                                 uncoupled structural modes)
    Q(k, M)  : generalised AIC matrix projected onto modal coordinates
    ω        : complex eigenvalue  p = iω  (p = γ ωR + i ωR)
    ωR       : imaginary part of p (reference frequency)
    k        : reduced frequency  k = ωR * b / V

The p-k method iterates at each velocity V:
    1. Guess k (from the previous velocity step or mode natural frequency).
    2. Compute Q(k) from the doublet-lattice method.
    3. Assemble the flutter matrix and solve for eigenvalues p.
    4. Extract new k = Im(p) * b / V.
    5. Repeat until convergence.

The flutter speed is where the real part of any eigenvalue (damping γ)
crosses zero from negative to positive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np
from numpy.typing import NDArray

try:
    from .doublet_lattice import build_aic_matrix, TrapezoidalPanel
except ImportError:
    build_aic_matrix = None  # type: ignore[assignment]
    TrapezoidalPanel = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModalMode:
    """A single structural mode.

    Parameters
    ----------
    frequency : float
        Natural frequency in rad/s.
    mode_shape : NDArray[np.floating]
        Mode-shape vector at the aerodynamic panel centres, shape (N_panels,).
        Each entry is the normalised displacement (heave/pitch) at that panel.
    modal_mass : float
        Generalised (modal) mass.
    modal_damping : float
        Generalised (modal) viscous damping coefficient.  Set to 0 for
        undamped structural analysis.
    """

    frequency: float
    mode_shape: NDArray[np.floating]
    modal_mass: float = 1.0
    modal_damping: float = 0.0


@dataclass
class FlutterPoint:
    """A single point on the p-k V-g / V-f diagram.

    Attributes
    ----------
    velocity : float
        Air speed, m/s.
    damping : float
        Structural damping g = 2 * Re(p) / Im(p)  (dimensionless).
    frequency : float
        Flutter frequency Im(p), rad/s.
    mode_index : int
        Index of the structural mode this point belongs to.
    """

    velocity: float
    damping: float
    frequency: float
    mode_index: int


@dataclass
class FlutterResult:
    """Output of a p-k flutter sweep.

    Attributes
    ----------
    flutter_speed : float or None
        Flutter speed in m/s, or None if no flutter was found in the sweep
        range.
    flutter_frequency : float or None
        Flutter frequency in rad/s at the flutter point.
    flutter_mode : int or None
        Index of the mode that goes unstable.
    vg_curves : list[list[FlutterPoint]]
        V-g-f data for each mode across all velocities swept.
    """

    flutter_speed: float | None = None
    flutter_frequency: float | None = None
    flutter_mode: int | None = None
    vg_curves: list[list[FlutterPoint]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Generalised AIC projection
# ---------------------------------------------------------------------------

def project_aic(
    Q_aero: NDArray[np.complexfloating],
    modes: Sequence[ModalMode],
    panel_areas: NDArray[np.floating],
) -> NDArray[np.complexfloating]:
    """Project the aerodynamic AIC matrix onto modal coordinates.

    Computes the generalised AIC matrix:

        Q_modal[i, j] = phi_i^T * [S] * Q_aero * [S] * phi_j

    where [S] is a diagonal matrix of panel areas (integration weights) and
    phi_i is the mode shape of mode i.

    Parameters
    ----------
    Q_aero : ndarray, shape (N, N), complex
        Panel-level AIC matrix from the doublet-lattice method.
    modes : sequence of ModalMode
        Structural modes, each with a mode_shape of length N.
    panel_areas : ndarray, shape (N,)
        Area of each aerodynamic panel, for integration weighting.

    Returns
    -------
    ndarray, shape (n_modes, n_modes), complex
        Generalised AIC matrix in modal coordinates.
    """
    n_modes = len(modes)
    S = np.diag(panel_areas)

    # Stack mode shapes into a matrix: Phi[N, n_modes]
    N = len(panel_areas)
    Phi = np.zeros((N, n_modes), dtype=float)
    for i, mode in enumerate(modes):
        phi = np.asarray(mode.mode_shape, dtype=float)
        if phi.shape[0] != N:
            raise ValueError(
                f"Mode {i} shape length {phi.shape[0]} != N_panels={N}"
            )
        Phi[:, i] = phi

    # Q_modal = Phi^T S Q_aero S Phi
    Q_modal = Phi.T @ S @ Q_aero @ S @ Phi
    return Q_modal


# ---------------------------------------------------------------------------
# Flutter matrix assembly and eigenvalue solve
# ---------------------------------------------------------------------------

def _build_flutter_matrix(
    K_modal: NDArray[np.floating],
    M_modal: NDArray[np.floating],
    B_modal: NDArray[np.floating],
    Q_modal: NDArray[np.complexfloating],
    omega_ref: float,
    rho: float,
    V: float,
    k: float,
) -> NDArray[np.complexfloating]:
    """Assemble the flutter characteristic matrix.

    The generalised equation of motion in the frequency domain:

        D(p) x = [ p^2 M + p ωR B + K + (½ρV²) Q(k) ] x = 0

    where p = γ ωR + i ωR is the complex eigenvalue, and k = Im(p)*b/V.

    For the p-k iteration we fix Q at the current k and solve for p.

    The eigenvalue problem is cast as:

        D x = 0   =>   A x = λ x  (standard form)

    by letting:

        A = M^{-1} [ -K - (½ρV²) Q + ... ]

    which results in a complex generalised eigenvalue problem.

    Returns
    -------
    ndarray, shape (2n, 2n), complex
        State-space flutter matrix (first-order form).
    """
    n = K_modal.shape[0]
    qbar = 0.5 * rho * V * V

    # Flutter equation: (p^2 M + p*ωR*B + K + qbar*Q) x = 0
    # Cast as state-space: [ x' ]   [    0     I  ] [ x ]
    #                      [ x'']   [ -M^{-1}(K+qQ)   -M^{-1}(ωR*B) ] [ x']
    # Eigenvalue λ = p = complex frequency

    K_eff = K_modal + qbar * Q_modal
    M_inv = np.linalg.inv(M_modal.astype(complex))

    A_top = np.zeros((n, n), dtype=complex)
    A_bot_left  = -M_inv @ K_eff
    A_bot_right = -M_inv @ (omega_ref * B_modal.astype(complex))

    I_n = np.eye(n, dtype=complex)

    # 2n x 2n companion matrix
    A = np.block([
        [A_top,       I_n          ],
        [A_bot_left,  A_bot_right  ],
    ])

    return A


# ---------------------------------------------------------------------------
# p-k iteration at a single velocity
# ---------------------------------------------------------------------------

def _pk_eigenvalues_at_velocity(
    K_modal: NDArray[np.floating],
    M_modal: NDArray[np.floating],
    B_modal: NDArray[np.floating],
    aic_func: Callable[[float], NDArray[np.complexfloating]],
    modes: list[ModalMode],
    panel_areas: NDArray[np.floating],
    rho: float,
    V: float,
    b_ref: float,
    k_init: NDArray[np.floating],
    n_iter: int = 10,
    tol: float = 1e-4,
) -> tuple[NDArray[np.complexfloating], NDArray[np.floating]]:
    """Iterate the p-k equation at a fixed velocity until k converges.

    Parameters
    ----------
    K_modal, M_modal, B_modal : ndarray, shape (n_modes, n_modes)
        Structural matrices in modal coordinates.
    aic_func : callable(k) -> Q_aero
        Function returning the panel-level AIC matrix at reduced frequency k.
    modes, panel_areas : structural modes and panel areas.
    rho : float
        Air density, kg/m³.
    V : float
        Air speed, m/s.
    b_ref : float
        Reference semi-chord, m.
    k_init : ndarray, shape (n_modes,)
        Initial reduced frequency guesses, one per mode.
    n_iter : int
        Maximum number of p-k iterations.
    tol : float
        Convergence tolerance on k.

    Returns
    -------
    eigs : ndarray, shape (2*n_modes,), complex
        Converged complex eigenvalues p = γ*ωR + i*ωR.
    k_out : ndarray, shape (n_modes,)
        Converged reduced frequencies.
    """
    n_modes = len(modes)
    k_vec = k_init.copy()

    eigs_out = np.zeros(2 * n_modes, dtype=complex)

    for _it in range(n_iter):
        eigs_list = []

        for m_idx in range(n_modes):
            k_m = float(k_vec[m_idx])
            k_m = max(k_m, 1e-6)

            # Build AIC and project
            Q_aero = aic_func(k_m)
            Q_modal = project_aic(Q_aero, modes, panel_areas)

            omega_ref = modes[m_idx].frequency if modes[m_idx].frequency > 0 else 1.0

            A = _build_flutter_matrix(
                K_modal, M_modal, B_modal, Q_modal,
                omega_ref, rho, V, k_m,
            )
            eigs = np.linalg.eigvals(A)
            eigs_list.append(eigs)

        # Pick the physically meaningful eigenvalues for each mode
        # (those closest to the expected flutter frequency, im > 0)
        all_eigs = np.concatenate(eigs_list)
        # Keep eigenvalues with positive imaginary parts only
        pos_eigs = all_eigs[np.imag(all_eigs) > 0]
        if len(pos_eigs) < n_modes:
            # Fall back to all eigenvalues sorted by imaginary part
            pos_eigs = all_eigs[np.argsort(-np.abs(np.imag(all_eigs)))]

        eigs_out = all_eigs  # store all

        # Update k for each mode from the matched eigenvalue
        k_new = np.zeros(n_modes)
        for m_idx in range(n_modes):
            omega_m = modes[m_idx].frequency
            # Find eigenvalue closest in frequency to ω_m
            diffs = np.abs(np.imag(all_eigs) - omega_m)
            best = int(np.argmin(diffs))
            omega_flutter = abs(np.imag(all_eigs[best]))
            if omega_flutter < 1e-10:
                k_new[m_idx] = k_vec[m_idx]
            else:
                k_new[m_idx] = omega_flutter * b_ref / max(V, 1e-10)

        dk = np.max(np.abs(k_new - k_vec))
        k_vec = k_new

        if dk < tol:
            break

    return eigs_out, k_vec


# ---------------------------------------------------------------------------
# Main p-k flutter sweep
# ---------------------------------------------------------------------------

def pk_flutter_sweep(
    modes: list[ModalMode],
    panels: list,
    rho: float,
    b_ref: float,
    M: float,
    velocities: NDArray[np.floating],
    n_iter: int = 15,
    structural_damping: float = 0.0,
) -> FlutterResult:
    """Perform a p-k flutter sweep over a range of velocities.

    Parameters
    ----------
    modes : list[ModalMode]
        Structural modes (frequency + mode shape at panel centres).
    panels : list[TrapezoidalPanel]
        Aerodynamic panel mesh.
    rho : float
        Air density, kg/m³.
    b_ref : float
        Reference semi-chord, m.
    M : float
        Mach number.
    velocities : array-like, shape (N_V,)
        Sequence of velocities to sweep, m/s (ascending).
    n_iter : int
        Maximum p-k iterations per velocity.
    structural_damping : float
        Uniform structural damping coefficient added to all modes.

    Returns
    -------
    FlutterResult
        Contains flutter speed, frequency, mode index and V-g curves.
    """
    V_arr = np.asarray(velocities, dtype=float)
    n_modes = len(modes)
    N_panels = len(panels)

    # Panel areas
    panel_areas = np.array([p.area for p in panels], dtype=float)

    # Structural matrices in modal coordinates (diagonal)
    M_modal = np.diag([m.modal_mass for m in modes]).astype(float)
    K_modal = np.diag([
        m.modal_mass * m.frequency ** 2 for m in modes
    ]).astype(float)
    B_modal = np.diag([
        m.modal_damping + structural_damping * m.modal_mass
        for m in modes
    ]).astype(float)

    # AIC function: k -> Q_aero
    def aic_func(k: float) -> NDArray[np.complexfloating]:
        return build_aic_matrix(panels, k=k, M=M, b_ref=b_ref)

    # Initialise reduced frequencies from mode natural frequencies
    # k_j = omega_j * b_ref / V  (at first velocity)
    V0 = V_arr[0]
    k_init = np.array([
        m.frequency * b_ref / max(V0, 1e-10) for m in modes
    ])

    # V-g curves: one list per mode
    vg_curves: list[list[FlutterPoint]] = [[] for _ in range(n_modes)]

    flutter_speed: float | None = None
    flutter_frequency: float | None = None
    flutter_mode_idx: int | None = None

    prev_damping = np.full(n_modes, float("nan"))

    for V in V_arr:
        eigs, k_conv = _pk_eigenvalues_at_velocity(
            K_modal, M_modal, B_modal,
            aic_func, modes, panel_areas,
            rho, V, b_ref, k_init, n_iter,
        )
        k_init = k_conv.copy()

        # Match eigenvalues to modes
        for m_idx, mode in enumerate(modes):
            # Find eigenvalue closest to this mode's natural frequency
            diffs = np.abs(np.imag(eigs) - mode.frequency)
            best = int(np.argmin(diffs))
            p = eigs[best]

            omega_r = abs(np.imag(p))
            if omega_r < 1e-10:
                g = float("nan")
            else:
                g = 2.0 * float(np.real(p)) / omega_r  # structural damping g

            pt = FlutterPoint(
                velocity=V,
                damping=g,
                frequency=omega_r,
                mode_index=m_idx,
            )
            vg_curves[m_idx].append(pt)

            # Check for flutter (damping crosses zero)
            if (
                flutter_speed is None
                and not math.isnan(g)
                and not math.isnan(prev_damping[m_idx])
                and prev_damping[m_idx] < 0.0
                and g >= 0.0
            ):
                # Linear interpolation for crossing point
                V_prev = vg_curves[m_idx][-2].velocity
                g_prev = prev_damping[m_idx]
                if abs(g - g_prev) > 1e-14:
                    V_flutter = V_prev + (-g_prev) / (g - g_prev) * (V - V_prev)
                else:
                    V_flutter = V
                flutter_speed = V_flutter
                flutter_frequency = omega_r
                flutter_mode_idx = m_idx

            if not math.isnan(g):
                prev_damping[m_idx] = g

    return FlutterResult(
        flutter_speed=flutter_speed,
        flutter_frequency=flutter_frequency,
        flutter_mode=flutter_mode_idx,
        vg_curves=vg_curves,
    )
