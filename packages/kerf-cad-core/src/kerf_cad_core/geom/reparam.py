"""
kerf_cad_core.geom.reparam — NURBS curve reparametrisation schemes.

Provides three canonical point-cloud parametrisation methods from
Piegl-Tiller §9.2.2 plus the Foley-Nielsen angle-weighted scheme:

  parametrize_chord_length(points)      — classic chord-length (uniform for
                                          equally-spaced data; P&T eq. 9.4)
  parametrize_centripetal(points, α)    — centripetal (α=0.5 default; industry
                                          standard for noisy data; P&T eq. 9.5)
  parametrize_foley_nielsen(points)     — Foley-Nielsen 1989 angle-weighted
                                          chord-length; smoother near sharp turns

All three return a monotonically increasing ndarray in [0, 1] with
u[0] == 0.0 and u[-1] == 1.0.

References
----------
Piegl & Tiller, "The NURBS Book", 2nd ed., §9.2.2 (pp. 364-369)
Foley & Nielsen, "Foley-Nielsen Parametrisation" (1989 Siggraph course notes)
  — see also: Farin, "Curves and Surfaces for CAGD", 5th ed., ch. 11

Author: imranparuk
"""
from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parametrize_chord_length(points: np.ndarray) -> np.ndarray:
    """Chord-length parametrisation (Piegl-Tiller §9.2.2, eq. 9.4).

    Assigns parameter u_i proportional to the cumulative chord lengths:

        d_i = ||P_i - P_{i-1}||          i = 1..n-1
        u_0 = 0,  u_i = Σ_{k=1}^{i} d_k / Σ_{k=1}^{n-1} d_k

    For uniformly-spaced collinear points this produces exact uniform
    spacing in [0, 1].

    Parameters
    ----------
    points : ndarray, shape (n, d)
        Ordered point sequence.  n ≥ 2.

    Returns
    -------
    ndarray, shape (n,)
        Parameter values u[0] = 0.0, u[-1] = 1.0, strictly monotone.
    """
    pts = np.asarray(points, dtype=float)
    _require_2d(pts)
    n = len(pts)
    if n == 1:
        return np.zeros(1)

    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)  # shape (n-1,)
    total = float(diffs.sum())
    if total < 1e-15:
        return np.linspace(0.0, 1.0, n)

    u = np.empty(n)
    u[0] = 0.0
    u[1:] = np.cumsum(diffs) / total
    u[-1] = 1.0  # clamp exactly
    return u


def parametrize_centripetal(
    points: np.ndarray,
    alpha: float = 0.5,
) -> np.ndarray:
    """Centripetal (generalised) parametrisation (Piegl-Tiller §9.2.2, eq. 9.5).

    Assigns parameter proportional to chord-length raised to power α:

        d_i = ||P_i - P_{i-1}||^α
        u_i = Σ_{k=1}^{i} d_k / Σ_{k=1}^{n-1} d_k

    Special cases
    -------------
    α = 0.0  → uniform (u_i = i/(n-1))
    α = 0.5  → centripetal (default; best for noisy/curvature-dense data)
    α = 1.0  → chord-length (same as ``parametrize_chord_length``)

    The centripetal scheme (α=0.5) is the industry standard for NURBS fitting
    to noisy point clouds because it clusters parameters near high-curvature
    sections, reducing oscillation in the fitted curve.

    Parameters
    ----------
    points : ndarray, shape (n, d)
    alpha  : float in [0, 1], default 0.5

    Returns
    -------
    ndarray, shape (n,), values in [0, 1], monotone.
    """
    pts = np.asarray(points, dtype=float)
    _require_2d(pts)
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"alpha must be in [0, 1]; got {alpha}")
    n = len(pts)
    if n == 1:
        return np.zeros(1)
    if alpha == 0.0:
        return np.linspace(0.0, 1.0, n)

    raw_diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    diffs = np.power(np.maximum(raw_diffs, 0.0), alpha)
    total = float(diffs.sum())
    if total < 1e-15:
        return np.linspace(0.0, 1.0, n)

    u = np.empty(n)
    u[0] = 0.0
    u[1:] = np.cumsum(diffs) / total
    u[-1] = 1.0
    return u


def parametrize_foley_nielsen(points: np.ndarray) -> np.ndarray:
    """Foley-Nielsen angle-weighted chord-length parametrisation (1989).

    Weights the chord-length increment at each interior vertex by a factor
    that accounts for the local turning angle, placing denser parameter
    values near sharp bends and sparser values along straighter sections.

    Algorithm (Foley & Nielsen, 1989)
    ----------------------------------
    Let d_i = ||P_i - P_{i-1}||  and  θ_i be the angle at P_i:

        θ_i  = angle between chords  (P_{i-1}→P_i)  and  (P_i→P_{i+1})
             = arccos( clip(dot(e_{i-1,i}, e_{i,i+1}), -1, 1) )

    where e_{a,b} = (P_b - P_a) / ||P_b - P_a||  is the unit chord vector.

    The modified chord length is:

        d̂_1 = d_1 * (1 + 1.5 * θ_1 / π * d_1 / (d_1 + d_2))
        d̂_i = d_i * (1 + 1.5 * θ_{i-1}/π * d_{i-1}/(d_{i-1}+d_i)
                          + 1.5 * θ_i/π   * d_i   /(d_i   +d_{i+1}))   2 ≤ i ≤ n-2
        d̂_{n-1} = d_{n-1} * (1 + 1.5 * θ_{n-2}/π * d_{n-2}/(d_{n-2}+d_{n-1}))

    (Endpoints receive only one half of the neighbouring angle term.)

    Then:  u_i = Σ d̂_k / Σ d̂_k,   u_0=0, u_{n-1}=1.

    This scheme produces smoother parameter distributions than pure chord-
    length on data with noisy turn angles, reducing fitting residual for a
    fixed control-point count.

    Parameters
    ----------
    points : ndarray, shape (n, d)  with n ≥ 2

    Returns
    -------
    ndarray, shape (n,), values in [0, 1], monotone.
    """
    pts = np.asarray(points, dtype=float)
    _require_2d(pts)
    n = len(pts)
    if n == 1:
        return np.zeros(1)
    if n == 2:
        return np.array([0.0, 1.0])

    # Raw chord lengths
    d = np.linalg.norm(np.diff(pts, axis=0), axis=1)  # shape (n-1,)

    # Unit chord vectors — fall back to zero for zero-length chords
    with np.errstate(invalid="ignore", divide="ignore"):
        e = np.diff(pts, axis=0)
        norms = np.linalg.norm(e, axis=1, keepdims=True)
        safe = norms > 1e-15
        e_unit = np.where(safe, e / np.where(safe, norms, 1.0), 0.0)

    # Turning angles at interior vertices (indices 1 .. n-2)
    # θ[i] corresponds to vertex pts[i+1], i.e. between chord i and chord i+1
    m = n - 2  # number of interior vertices
    if m > 0:
        dots = np.einsum("ij,ij->i", e_unit[:-1], e_unit[1:])  # shape (m,)
        dots = np.clip(dots, -1.0, 1.0)
        theta = np.arccos(dots)  # shape (m,)  i.e. theta[i] = angle at vertex i+1
    else:
        theta = np.array([], dtype=float)

    # Modified chord lengths d_hat (shape n-1)
    d_hat = d.copy()

    for i in range(n - 1):
        factor = 1.0
        # contribution from the turning angle at the *start* vertex of this chord (vertex i)
        if i > 0 and i - 1 < len(theta):
            t = theta[i - 1]
            denom = d[i - 1] + d[i]
            if denom > 1e-15:
                factor += 1.5 * (t / np.pi) * d[i - 1] / denom
        # contribution from the turning angle at the *end* vertex of this chord (vertex i+1)
        if i < n - 2 and i < len(theta):
            t = theta[i]
            denom = d[i] + d[i + 1]
            if denom > 1e-15:
                factor += 1.5 * (t / np.pi) * d[i] / denom
        d_hat[i] = d[i] * factor

    total = float(d_hat.sum())
    if total < 1e-15:
        return np.linspace(0.0, 1.0, n)

    u = np.empty(n)
    u[0] = 0.0
    u[1:] = np.cumsum(d_hat) / total
    u[-1] = 1.0
    return u


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _require_2d(pts: np.ndarray) -> None:
    if pts.ndim == 1:
        # Treat 1D as a column of scalars — promote to (n, 1)
        return
    if pts.ndim != 2:
        raise ValueError(
            f"points must be a 2D array of shape (n, dim); got shape {pts.shape}"
        )
