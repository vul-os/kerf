# TODO: Depends on sibling-created package scaffold
"""Aeroelasticity module: Theodorsen-based typical-section flutter analysis.

Provides a self-contained two-DOF (pitch + plunge) typical-section flutter
solver using Theodorsen's (1935) unsteady aerodynamic theory and the p-k
iteration method.

Reference typical-section parameters (Bisplinghoff, Ashley & Halfman 1955,
Chapter 5):
    b    = semi-chord [m]
    a    = non-dim elastic-axis position from midchord (positive aft)
    x_α  = non-dim distance from EA to centre-of-mass  (positive aft)
    r_α  = non-dim radius of gyration about EA
    ω_h  = bending natural frequency [rad/s]
    ω_α  = torsion natural frequency [rad/s]
    μ    = mass ratio  m / (π ρ b²)
    ζ_h, ζ_α = structural damping ratios

Sign conventions (Fung 1955):
    - h positive downward (plunge)
    - α positive nose-up (pitch)
    - L positive upward
    - M_EA positive nose-up

Equations of motion (Fung eq 5.4.2–5.4.3):
    m(h'' + b x_α α'') + K_h h = −L
    I_α α'' + m b x_α h'' + K_α α = M_EA
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

try:
    from .flutter_pk import FlutterResult, FlutterPoint
except ImportError:
    FlutterResult = None  # type: ignore[assignment, misc]
    FlutterPoint = None   # type: ignore[assignment, misc]


# ---------------------------------------------------------------------------
# Theodorsen function C(k)
# ---------------------------------------------------------------------------

def theodorsen_C(k: float) -> complex:
    """Theodorsen's circulation function C(k) = F(k) + i G(k).

    Computed from Hankel functions of the second kind:

        C(k) = H₁⁽²⁾(k) / (H₁⁽²⁾(k) + i H₀⁽²⁾(k))

    Limits:
        k → 0  :  C(k) → 1  (quasi-steady lift)
        k → ∞  :  C(k) → 0.5

    Parameters
    ----------
    k : float
        Reduced frequency  k = ω b / V  (non-negative).

    Returns
    -------
    complex
        Theodorsen function value C(k) = F + iG.
    """
    if k <= 0.0:
        return complex(1.0, 0.0)

    from scipy.special import hankel2

    H1 = hankel2(1, k)
    H0 = hankel2(0, k)

    denom = H1 + 1j * H0
    if abs(denom) < 1e-30:
        return complex(0.5, 0.0)

    return complex(H1 / denom)


# ---------------------------------------------------------------------------
# Typical-section parameters
# ---------------------------------------------------------------------------

@dataclass
class TypicalSectionParams:
    """Parameters for a 2-DOF typical-section flutter model.

    Attributes
    ----------
    b : float
        Wing semi-chord, m.
    a : float
        Elastic-axis offset from midchord, non-dimensional.
        Positive aft: a = 0 at midchord, a = 1 at TE, a = -1 at LE.
        For a = -0.2 the EA is 0.2b forward of midchord (20% chord from LE
        for b=0.5c, i.e. EA at 30% chord).
    x_alpha : float
        Distance from EA to CG, non-dimensional (b units), positive aft.
    r_alpha : float
        Radius of gyration about EA, non-dimensional (b units).
    omega_h : float
        Plunge (bending) natural frequency, rad/s.
    omega_alpha : float
        Pitch (torsion) natural frequency, rad/s.
    mu : float
        Mass ratio  m / (π ρ b²)  where m is mass per unit span.
    rho : float
        Air density, kg/m³.
    zeta_h : float
        Structural damping ratio for plunge mode.
    zeta_alpha : float
        Structural damping ratio for pitch mode.
    """

    b: float = 1.0
    a: float = -0.2
    x_alpha: float = 0.1
    r_alpha: float = 0.5
    omega_h: float = 1.0
    omega_alpha: float = 2.0
    mu: float = 20.0
    rho: float = 1.225
    zeta_h: float = 0.0
    zeta_alpha: float = 0.0

    @property
    def omega_ratio(self) -> float:
        """Frequency ratio ω_h / ω_α."""
        return self.omega_h / self.omega_alpha


# ---------------------------------------------------------------------------
# Theodorsen flutter matrix assembly
# ---------------------------------------------------------------------------

def _build_theodorsen_matrices(
    p_params: TypicalSectionParams,
    V: float,
    k: float,
) -> tuple[
    NDArray[np.complexfloating],
    NDArray[np.complexfloating],
    NDArray[np.complexfloating],
]:
    """Assemble the dimensional p-k system matrices for the Theodorsen typical section.

    The equations of motion (Fung 1955, eqs 5.4.2–5.4.3) are rearranged as:

        A_m q'' + B_eff q' + K_eff q = 0

    where q = {h, α}^T.  The aerodynamic forces appear through the Theodorsen
    function C(k) and are separated into non-circulatory (apparent-mass) terms
    and circulatory (bound-vortex) terms.

    Parameters
    ----------
    p_params : TypicalSectionParams
    V : float
        Air speed, m/s.
    k : float
        Reduced frequency k = ω b / V.

    Returns
    -------
    A_m, B_eff, K_eff : complex ndarray, shape (2, 2)
        Effective mass, damping, and stiffness matrices.
    """
    p = p_params
    pr = math.pi * p.rho
    b = p.b
    a = p.a
    C = theodorsen_C(k)

    m = pr * b**2 * p.mu          # mass per unit span
    I_alpha = m * b**2 * p.r_alpha**2
    K_h = m * p.omega_h**2 * (1.0 + 2j * p.zeta_h)
    K_alpha = I_alpha * p.omega_alpha**2 * (1.0 + 2j * p.zeta_alpha)

    # ----------------------------------------------------------------
    # Effective mass matrix A_m (structural + non-circulatory aero mass)
    #
    # Non-circulatory lift (from Fung 5.3.4):
    #   L_nc = π ρ b²  (h'' + V α' − b a α'')
    # EOM row 1 adds +L_nc to left:  +pr b² h'' − pr b³ a α''
    #
    # Non-circulatory moment (Fung 5.3.4):
    #   M_nc = π ρ b³ (−a h'' + (1/8+a²) b α'') − π ρ V b² (1/2−a) α'
    # EOM row 2 subtracts M_nc from left: +pr b³ a h'' − pr b⁴(1/8+a²) α''
    # ----------------------------------------------------------------
    A_m = np.array([
        [m + pr * b**2,              m * b * p.x_alpha - pr * b**3 * a],
        [m * b * p.x_alpha + pr * b**3 * a,  I_alpha - pr * b**4 * (0.125 + a**2)],
    ], dtype=complex)

    # ----------------------------------------------------------------
    # Effective damping matrix B_eff (non-circulatory + circulatory)
    #
    # Non-circulatory damping:
    #   From L_nc:  +pr b² V  α'  (p^1 coefficient in col α for EOM row 1)
    #   From M_nc:  +pr b³ V (1/2−a) α'  (p^1 coeff for EOM row 2 with -M_nc sign)
    #
    # Circulatory damping (from w_3/4 = h' + V α + b(1/2−a) α'):
    #   p^1 part of w_3/4: [1, b(1/2−a)] → coefficient per {h', α'}
    #   L_c_1  = 2 π ρ V b C  × [1, b(1/2−a)]
    #   M_c_1  = 2 π ρ V b² (1/2+a) C × [1, b(1/2−a)]
    #   EOM row 1 adds +L_c_1; row 2 subtracts M_c_1.
    # ----------------------------------------------------------------
    B_nc = pr * b**2 * np.array([
        [0.0,  V],
        [0.0,  b * V * (0.5 - a)],
    ], dtype=complex)

    w_p1 = np.array([1.0, b * (0.5 - a)], dtype=complex)

    L_c_1 = 2.0 * pr * V * b * C * w_p1
    M_c_1 = (0.5 + a) * b * L_c_1

    B_c = np.array([+L_c_1, -M_c_1], dtype=complex)
    B_eff = B_nc + B_c

    # ----------------------------------------------------------------
    # Effective stiffness matrix K_eff (structural + circulatory)
    #
    # Circulatory stiffness (from p^0 part of w_3/4 = V α):
    #   w_p0 = [0, V] → coefficient per {h, α}
    #   L_c_0  = 2 π ρ V b C × [0, V]
    #   M_c_0  = 2 π ρ V b² (1/2+a) C × [0, V]
    #   EOM row 1 adds +L_c_0; row 2 subtracts M_c_0.
    # ----------------------------------------------------------------
    w_p0 = np.array([0.0, V], dtype=complex)

    L_c_0 = 2.0 * pr * V * b * C * w_p0
    M_c_0 = (0.5 + a) * b * L_c_0

    K_struct = np.array([[K_h, 0.0], [0.0, K_alpha]], dtype=complex)
    K_c = np.array([+L_c_0, -M_c_0], dtype=complex)
    K_eff = K_struct + K_c

    return A_m, B_eff, K_eff


# ---------------------------------------------------------------------------
# Typical-section: p-k method
# ---------------------------------------------------------------------------

def typical_section_pk(
    params: TypicalSectionParams,
    velocities: NDArray[np.floating],
) -> dict[str, object]:
    """Run p-k flutter analysis for a 2-DOF typical section.

    Implements the Hassig (1971) p-k iteration using the Theodorsen
    unsteady aerodynamic model.  At each velocity V the complex eigenvalues
    p = σ + iω are found; flutter occurs when σ → 0 (zero damping).

    Parameters
    ----------
    params : TypicalSectionParams
        Typical-section parameters.
    velocities : array-like
        Array of velocities to sweep, m/s.

    Returns
    -------
    dict with keys:
        'velocities'    : shape (N_V,)
        'damping'       : shape (N_V, 2)  — g = Re(p)/Im(p) for each mode
        'frequency'     : shape (N_V, 2)  — |Im(p)| in rad/s for each mode
        'flutter_speed' : float  — interpolated flutter speed (or nan)
        'flutter_freq'  : float  — flutter frequency at U_F (or nan)
    """
    par = params
    V_arr = np.asarray(velocities, dtype=float)
    N_V = len(V_arr)

    damping_out = np.full((N_V, 2), float("nan"))
    freq_out = np.full((N_V, 2), float("nan"))

    flutter_speed = float("nan")
    flutter_freq = float("nan")
    prev_g = np.full(2, float("nan"))

    # Seed reduced frequencies from natural frequencies at first velocity
    k_seed = np.array([par.omega_h, par.omega_alpha])

    for i_V, V in enumerate(V_arr):
        if V < 1e-10:
            continue

        k_guess = k_seed * par.b / V

        # p-k iteration: update k from Im(p) until convergence
        pos_roots: list[complex] = []
        for _it in range(30):
            k_mean = max(float(np.mean(k_guess)), 1e-6)
            A_m, B_eff, K_eff = _build_theodorsen_matrices(par, V, k_mean)

            # Linearised companion matrix for p² A_m + p B_eff + K_eff = 0:
            #   [[0    I  ]   [x  ]   [x  ]
            #    [-Am⁻¹K  −Am⁻¹B]] [x' ]= p[x' ]
            n = 2
            Am_inv_K = np.linalg.solve(A_m, K_eff)
            Am_inv_B = np.linalg.solve(A_m, B_eff)
            companion = np.block([
                [np.zeros((n, n), dtype=complex), np.eye(n, dtype=complex)],
                [-Am_inv_K,                        -Am_inv_B],
            ])
            eigs = np.linalg.eigvals(companion)

            # Keep eigenvalues with positive imaginary part (physical modes)
            pos_roots = sorted(
                [e for e in eigs if np.imag(e) > 1e-3],
                key=lambda e: abs(np.imag(e)),
            )

            if len(pos_roots) >= 2:
                k_new = np.array([abs(np.imag(pos_roots[0])), abs(np.imag(pos_roots[1]))]) * par.b / V
            elif len(pos_roots) == 1:
                k_new = np.array([abs(np.imag(pos_roots[0]))] * 2) * par.b / V
            else:
                break

            delta_k = float(np.max(np.abs(k_new - k_guess)))
            k_guess = k_new
            if delta_k < 1e-5:
                break

        # Update seed for next velocity
        if len(pos_roots) >= 2:
            k_seed = np.array([abs(np.imag(pos_roots[0])), abs(np.imag(pos_roots[1]))])
        elif len(pos_roots) == 1:
            k_seed = np.array([abs(np.imag(pos_roots[0]))] * 2)

        # Extract per-mode damping and frequency using greedy frequency-tracking.
        # Reference frequencies: use previous velocity's frequencies if available,
        # otherwise fall back to structural natural frequencies.
        ref_freqs: list[float] = []
        for m_idx in range(2):
            prev_f = freq_out[i_V - 1, m_idx] if i_V > 0 else float("nan")
            if not math.isnan(prev_f) and prev_f > 0:
                ref_freqs.append(prev_f)
            else:
                ref_freqs.append(par.omega_h if m_idx == 0 else par.omega_alpha)

        # Greedy assignment: assign each root to the closest unassigned mode
        available = list(pos_roots)
        assigned: list[complex | None] = [None, None]

        for m_idx in range(2):
            if not available:
                break
            ref_f = ref_freqs[m_idx]
            diffs = [abs(abs(np.imag(r)) - ref_f) for r in available]
            best_idx = int(np.argmin(diffs))
            assigned[m_idx] = available.pop(best_idx)

        for m_idx in range(2):
            best = assigned[m_idx]
            if best is None:
                continue
            omega_r = abs(np.imag(best))
            if omega_r > 1e-8:
                g = float(np.real(best)) / omega_r
                damping_out[i_V, m_idx] = g
                freq_out[i_V, m_idx] = omega_r

                # Flutter detection: g crosses from < 0 to ≥ 0
                if (
                    math.isnan(flutter_speed)
                    and not math.isnan(prev_g[m_idx])
                    and prev_g[m_idx] < 0.0
                    and g >= 0.0
                    and i_V > 0
                ):
                    V_prev = V_arr[i_V - 1]
                    g_prev = prev_g[m_idx]
                    if abs(g - g_prev) > 1e-14:
                        V_f = V_prev + (-g_prev) / (g - g_prev) * (V - V_prev)
                    else:
                        V_f = V
                    flutter_speed = float(V_f)
                    flutter_freq = float(omega_r)

                prev_g[m_idx] = g

    return {
        "velocities":    V_arr,
        "damping":       damping_out,
        "frequency":     freq_out,
        "flutter_speed": flutter_speed,
        "flutter_freq":  flutter_freq,
    }


# ---------------------------------------------------------------------------
# Theodorsen flutter matrix for k-method (internal, for typical_section_flutter_speed)
# ---------------------------------------------------------------------------

def _flutter_matrix_k_method(
    k: float,
    U_star: float,
    mu: float,
    a: float,
    x_alpha: float,
    r_alpha: float,
    omega_ratio: float,
    zeta_h: float = 0.0,
    zeta_alpha: float = 0.0,
) -> NDArray[np.complexfloating]:
    """Theodorsen flutter determinant matrix for the k-method.

    Returns the 2×2 matrix A(k, U*) such that flutter condition is det(A) = 0.

    Parameters
    ----------
    k : float
        Reduced frequency  ω b / V.
    U_star : float
        Non-dimensional velocity U/(b ω_α).
    mu, a, x_alpha, r_alpha, omega_ratio : typical-section parameters.
    zeta_h, zeta_alpha : structural damping ratios.
    """
    C = theodorsen_C(k)
    omega_star = k * U_star          # ω / ω_α

    inv_mu = 1.0 / mu

    # Theodorsen force coefficients (Fung 5.4.5–5.4.8, normalised by π ρ b²):
    L_h     = math.pi * (-k**2 + 2j * k * C)
    L_alpha = math.pi * (-(0.5 + a) * k**2 + 2j * C * (k * (0.5 - a) + 1j))
    M_h     = math.pi * (a * k**2 + 2j * k * (0.5 + a) * C)
    M_alpha = math.pi * (-(0.125 + a**2) * k**2 + 2j * (0.5 + a) * C * (k * (0.5 - a) + 1j))

    # Structural terms with damping
    struct_11 = -omega_star**2 * (1.0 + 2j * zeta_h / (omega_star if omega_star > 1e-12 else 1e-12)) + omega_ratio**2
    struct_22 = -omega_star**2 * (1.0 + 2j * zeta_alpha / (omega_star if omega_star > 1e-12 else 1e-12)) + 1.0
    struct_12 = -omega_star**2 * x_alpha
    struct_21 = -omega_star**2 * x_alpha

    A = np.array([
        [struct_11 - inv_mu * L_h,    struct_12 - inv_mu * L_alpha],
        [struct_21 + inv_mu * M_h,    struct_22 + inv_mu * M_alpha],
    ], dtype=complex)

    return A


def typical_section_flutter_speed(
    params: TypicalSectionParams,
    k_range: tuple[float, float] = (0.001, 2.0),
    n_k: int = 500,
    n_U: int = 300,
    U_range: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """Find flutter speed via the k-method (sweep k, locate |det| minimum).

    Parameters
    ----------
    params : TypicalSectionParams
    k_range : tuple
        Range of reduced frequency k values to search.
    n_k, n_U : int
        Grid resolution.
    U_range : ignored, kept for API compatibility.

    Returns
    -------
    (flutter_speed, flutter_frequency) : tuple[float, float]
        Both in SI units; returns (nan, nan) if no flutter found.
    """
    p = params

    # Use the p-k method (more robust than the k-method grid search)
    V_ref = p.b * p.omega_alpha
    V_max = 5.0 * V_ref
    velocities = np.linspace(0.01 * V_ref, V_max, 400)
    result = typical_section_pk(p, velocities)
    U_F = result["flutter_speed"]
    f_F = result["flutter_freq"]
    return float(U_F), float(f_F)


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def run_typical_section(
    b: float = 1.0,
    a: float = -0.2,
    x_alpha: float = 0.1,
    r_alpha: float = 0.5,
    omega_h_over_omega_a: float = 0.5,
    mu: float = 20.0,
    rho: float = 1.225,
    omega_alpha: float = 1.0,
    V_max_factor: float = 4.0,
    n_V: int = 200,
    zeta_h: float = 0.0,
    zeta_alpha: float = 0.0,
) -> dict[str, object]:
    """Convenience function: run a typical-section flutter analysis.

    The flutter speed is expressed as the non-dimensional reduced velocity
        U_F* = U_F / (b ω_α)
    Reference value for default parameters: U_F* ≈ 2.165 (Fung 1955, Fig 5.14).

    Returns
    -------
    dict with keys:
        'flutter_speed'     : float, m/s
        'flutter_speed_nd'  : float, U_F / (b ω_α)
        'flutter_freq'      : float, rad/s
        'vg_data'           : dict from typical_section_pk
        'params'            : TypicalSectionParams
    """
    params = TypicalSectionParams(
        b=b, a=a, x_alpha=x_alpha, r_alpha=r_alpha,
        omega_h=omega_h_over_omega_a * omega_alpha,
        omega_alpha=omega_alpha,
        mu=mu, rho=rho, zeta_h=zeta_h, zeta_alpha=zeta_alpha,
    )

    V_ref = b * omega_alpha
    V_max = V_max_factor * V_ref
    velocities = np.linspace(0.01 * V_ref, V_max, n_V)

    vg = typical_section_pk(params, velocities)

    U_F = vg["flutter_speed"]
    U_F_nd = float(U_F) / V_ref if not math.isnan(float(U_F)) else float("nan")

    return {
        "flutter_speed":    U_F,
        "flutter_speed_nd": U_F_nd,
        "flutter_freq":     vg["flutter_freq"],
        "vg_data":          vg,
        "params":           params,
    }
