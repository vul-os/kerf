# TODO: Depends on sibling-created package scaffold
"""Doublet-Lattice Method (DLM) for unsteady subsonic aerodynamics.

Implements the Albano-Rodden (1969) doublet-lattice panel method.  The method
computes the aerodynamic-influence-coefficient (AIC) matrix Q(k, M) that
relates the downwash on receiving panels to the bound circulation (pressure
doublet strengths) on sending panels, as a function of reduced frequency k and
Mach number M.

Reference:
    Albano, E. and Rodden, W.P. (1969).  "A doublet-lattice method for
    calculating lift distributions on oscillating surfaces in subsonic flows."
    AIAA Journal, 7(2):279-285.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

try:
    from .._compat import require_numpy  # noqa: F401  (optional, soft dep)
except Exception:
    pass


# ---------------------------------------------------------------------------
# Kernel function helpers
# ---------------------------------------------------------------------------

def _kernel_W(k: float, r_bar: float, eta: float, M: float) -> complex:
    """Oscillatory kernel function W for the doublet-lattice integral.

    This implements the non-planar kernel function given by Albano and Rodden
    (1969, eq. 17-19) for subsonic flow.  For planar configurations (eta=0)
    the function reduces to the standard planar kernel.

    Parameters
    ----------
    k : float
        Reduced frequency  k = omega * b / V  (b = semi-chord).
    r_bar : float
        Non-dimensional distance parameter r = sqrt(xi^2 + (beta*eta)^2) / b
        where beta = sqrt(1 - M^2).
    eta : float
        Lateral separation between sending and receiving panel (normalised by
        the reference semi-chord).  eta = 0 for coplanar panels.
    M : float
        Mach number.

    Returns
    -------
    complex
        Value of the kernel function W.
    """
    beta2 = 1.0 - M * M
    beta = math.sqrt(max(beta2, 1e-14))

    if abs(r_bar) < 1e-14:
        # Avoid singularity — return large imaginary value (1/r behaviour)
        return complex(0.0)

    # Exponent factor  exp(ik * M * r_bar / beta)
    exp_factor = cmath_exp(1j * k * M * r_bar / beta)

    # I_1 term — standard doublet kernel
    I1 = (1.0 / r_bar) * exp_factor

    # I_2 term (near-field correction)
    I2 = (1.0 / (r_bar * r_bar)) * (1.0 - (1.0 + 1j * k * r_bar) * exp_factor) / r_bar

    W = I1 + I2
    return W


def cmath_exp(z: complex) -> complex:
    """Return exp(z) for a complex number z."""
    return math.exp(z.real) * complex(math.cos(z.imag), math.sin(z.imag))


# ---------------------------------------------------------------------------
# Panel geometry
# ---------------------------------------------------------------------------

class TrapezoidalPanel:
    """A single trapezoidal doublet-lattice panel.

    The panel is defined in the x-z plane (planform view) with the x axis
    pointing downstream.

    Parameters
    ----------
    x_ea : float
        x coordinate of the doublet line (1/4-chord of the panel), in metres.
    y_ea : float
        y (span) coordinate of the panel centre, in metres.
    chord : float
        Local panel chord length, in metres.
    span : float
        Panel span (dy), in metres.
    dihedral : float
        Dihedral angle of the panel in radians (0 for flat wing).
    """

    def __init__(
        self,
        x_ea: float,
        y_ea: float,
        chord: float,
        span: float,
        dihedral: float = 0.0,
    ) -> None:
        self.x_ea = x_ea          # x position of doublet line (1/4-chord)
        self.y_ea = y_ea          # spanwise centre of panel
        self.chord = chord        # panel chord
        self.span = span          # panel spanwise extent dy
        self.dihedral = dihedral  # dihedral angle

        # Control point (collocation) at 3/4-chord
        self.x_cp = x_ea + 0.5 * chord   # 3/4-chord from LE
        self.y_cp = y_ea
        self.semi_chord = 0.5 * chord     # b_j for this panel

    @property
    def area(self) -> float:
        return self.chord * self.span


# ---------------------------------------------------------------------------
# AIC matrix computation
# ---------------------------------------------------------------------------

def _planar_kernel(
    xi: float,
    eta: float,
    zeta: float,
    k: float,
    M: float,
    b_ref: float,
) -> complex:
    """Planar doublet-lattice kernel (Albano-Rodden, planar case).

    Computes the contribution per unit span from a doublet strip located at
    (0, 0) to the collocation point at (xi, eta, zeta).

    Parameters
    ----------
    xi : float
        Streamwise distance from doublet to collocation point (positive aft).
    eta : float
        Spanwise separation.
    zeta : float
        Normal separation (used for non-planar kernel; zero for planar wings).
    k : float
        Reduced frequency (omega * b_ref / V).
    M : float
        Mach number.
    b_ref : float
        Reference semi-chord used for non-dimensionalisation.

    Returns
    -------
    complex
        AIC kernel value.
    """
    beta2 = max(1.0 - M * M, 1e-14)
    beta = math.sqrt(beta2)

    # r = sqrt(xi^2 + beta^2*(eta^2+zeta^2))
    r2 = xi * xi + beta2 * (eta * eta + zeta * zeta)
    if r2 < 1e-28:
        return complex(0.0)
    r = math.sqrt(r2)

    # Non-dimensional quantities
    r_bar = r / b_ref
    xi_bar = xi / b_ref

    # Phase factor for oscillatory motion: exp(-ik * xi/b)
    phase = cmath_exp(-1j * k * xi_bar)

    # Steady kernel T1 (from lifting-line theory)
    # T1 = xi / r^3  (for planar)
    T1_bar = xi_bar / (r_bar ** 3)

    # Oscillatory correction T2
    # Based on Albano-Rodden eq. (A-5): combines exp(-ik*xi/b) terms
    if abs(r_bar) < 1e-14:
        T2_bar = complex(0.0)
    else:
        # Full Kussner kernel (linearised)
        mu = k * M * r_bar / beta2
        exp_mu = cmath_exp(-1j * mu)
        # I1 integral approximation (Rodden 1971 form)
        T2_bar = phase * (T1_bar - (1.0 - 1j * k * r_bar) / (r_bar * r_bar * r_bar) * exp_mu)

    # The AIC contribution = (1 / (2π)) * (T1 + T2) integrated along doublet strip
    # For a finite panel, multiply by the panel half-span later
    kernel_val = T1_bar + T2_bar

    return kernel_val


def _aic_element(
    send: TrapezoidalPanel,
    recv: TrapezoidalPanel,
    k: float,
    M: float,
    b_ref: float,
) -> complex:
    """Compute one element of the AIC matrix A[recv, send].

    Uses the Albano-Rodden planar kernel integrated over the sending panel's
    doublet line (1/4-chord line), evaluated at the receiving panel's
    3/4-chord collocation point.

    Integration is performed numerically (3-point Gauss-Legendre over the
    doublet strip).
    """
    # Gauss-Legendre points and weights for integration over send.span
    # 5-point Gauss rule for better accuracy
    gp = np.array([-0.90617984, -0.53846931,  0.0,  0.53846931,  0.90617984])
    gw = np.array([ 0.23692688,  0.47862867,  0.56888888,  0.47862867,  0.23692688])

    half_span = 0.5 * send.span
    result = complex(0.0)

    for gpi, gwi in zip(gp, gw):
        # Spanwise position on sending panel
        y_send = send.y_ea + gpi * half_span

        # Separation vector from doublet to collocation point
        xi  = recv.x_cp - send.x_ea       # streamwise (aft positive)
        eta = recv.y_cp - y_send           # spanwise
        zeta = 0.0                         # planar assumption

        kernel_val = _planar_kernel(xi, eta, zeta, k, M, b_ref)

        result += gwi * kernel_val * half_span

    # Scale by 1/(4π) per Albano-Rodden normalisation
    # and by the receiving-panel chord (for pressure coefficient normalisation)
    return result / (4.0 * math.pi)


def build_aic_matrix(
    panels: list[TrapezoidalPanel],
    k: float,
    M: float,
    b_ref: float | None = None,
) -> NDArray[np.complexfloating]:
    """Build the full AIC matrix Q for a list of panels.

    Parameters
    ----------
    panels : list[TrapezoidalPanel]
        List of N doublet-lattice panels.
    k : float
        Reduced frequency  k = omega * b_ref / V.
    M : float
        Mach number (subsonic, M < 1).
    b_ref : float, optional
        Reference semi-chord for non-dimensionalisation.  Defaults to the
        mean semi-chord of all panels.

    Returns
    -------
    ndarray, shape (N, N), complex
        AIC matrix Q[i, j] = downwash at panel i due to unit pressure doublet
        at panel j.
    """
    if M >= 1.0:
        raise ValueError(f"DLM is only valid for subsonic flow; got M={M}")

    N = len(panels)
    if b_ref is None:
        b_ref = float(np.mean([p.semi_chord for p in panels]))

    Q = np.zeros((N, N), dtype=complex)

    for i, recv in enumerate(panels):
        for j, send in enumerate(panels):
            Q[i, j] = _aic_element(send, recv, k, M, b_ref)

    return Q


# ---------------------------------------------------------------------------
# Convenience: rectangular wing discretisation
# ---------------------------------------------------------------------------

def make_rectangular_wing(
    span: float,
    chord: float,
    n_span: int = 4,
    n_chord: int = 1,
) -> list[TrapezoidalPanel]:
    """Discretise a flat rectangular wing into doublet-lattice panels.

    The LE is at x=0, y ranges from 0 to span/2 (semi-span, one side).
    Panels are arranged chordwise first, then spanwise.

    Parameters
    ----------
    span : float
        Total wing span (tip-to-tip), in metres.
    chord : float
        Wing chord (constant), in metres.
    n_span : int
        Number of spanwise panels.
    n_chord : int
        Number of chordwise panels.

    Returns
    -------
    list[TrapezoidalPanel]
        List of doublet-lattice panels.
    """
    dy = (span / 2.0) / n_span
    dx = chord / n_chord
    panels: list[TrapezoidalPanel] = []

    for js in range(n_span):
        y_centre = (js + 0.5) * dy
        for jc in range(n_chord):
            x_le = jc * dx
            x_ea = x_le + 0.25 * dx   # doublet line at 1/4-chord of sub-panel
            panels.append(
                TrapezoidalPanel(
                    x_ea=x_ea,
                    y_ea=y_centre,
                    chord=dx,
                    span=dy,
                )
            )

    return panels


# ---------------------------------------------------------------------------
# Steady VLM consistency (k=0 limit)
# ---------------------------------------------------------------------------

def steady_vlm_lift_slope(
    panels: list[TrapezoidalPanel],
    M: float = 0.0,
) -> float:
    """Compute lift-curve slope dCL/dalpha via steady VLM (k=0 DLM limit).

    The steady VLM AIC is the real part of Q(k=0).

    Returns
    -------
    float
        Lift-curve slope per radian, approximately 2π for an ideal wing.
    """
    Q0 = build_aic_matrix(panels, k=0.0, M=M)
    N = len(panels)

    # Downwash vector for uniform angle of attack alpha=1 rad
    w = np.ones(N, dtype=float)

    # Solve for panel doublet strengths: Q0 * gamma = w
    # (real part of Q at k=0 is purely real)
    Q0_real = np.real(Q0)

    try:
        gamma = np.linalg.solve(Q0_real, w)
    except np.linalg.LinAlgError:
        return float("nan")

    # CL = (2 / S) * sum(gamma_j * dy_j)
    S_ref = sum(p.area for p in panels)
    CL = (2.0 / S_ref) * sum(gamma[j] * panels[j].span for j in range(N))

    return float(CL)
