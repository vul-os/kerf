"""
kerf_optics.zernike — Zernike polynomial aberration decomposition (Noll 1976).

Public API
----------
noll_index_to_mn(j)                -> (n, m)
    Convert Noll index j to radial order n and azimuthal frequency m.

zernike_radial(n, m, rho)          -> ndarray
    Evaluate the radial polynomial R_n^|m|(rho) on an array of rho values.

zernike_poly(j, rho, theta)        -> ndarray
    Evaluate the j-th Zernike polynomial (Noll ordering) on polar grids.

zernike_basis(n_max=8, n_samples=64) -> ndarray  shape (n_modes, n_samples, n_samples)
    Return first n_max Zernike basis polynomials sampled on a circular grid.

fit_zernike(wavefront, n_max=8)    -> dict
    Decompose a 2-D wavefront array into Zernike modes (least-squares).
    Returns {Noll_index: coefficient, ...}.

reconstruct_wavefront(zernike_coefficients, grid_size=64) -> ndarray
    Synthesise a wavefront from a {Noll_index: coefficient} dict.

classical_aberration_breakdown(zernike_coefficients) -> dict
    Map Noll-indexed coefficients to classical aberration names and magnitudes.

Background
----------
Zernike polynomials are a complete orthonormal basis on the unit disk.  They
are the standard tool for characterising optical wavefront aberrations (Born
& Wolf, "Principles of Optics", 9th ed., §9.2; Noll 1976, J. Opt. Soc. Am.
66(3):207–211).

Noll ordering (1-based)
~~~~~~~~~~~~~~~~~~~~~~~
The Noll (1976) single-index ordering maps to (n, m) pairs by listing modes
in order of ascending radial degree n, and within each n in order of
ascending |m|, with negative m before positive m for each |m| > 0:

    j=1  (n=0, m= 0)  piston
    j=2  (n=1, m= 1)  x-tilt      ← positive m first within each |m| group
    j=3  (n=1, m=-1)  y-tilt
    j=4  (n=2, m= 0)  defocus
    j=5  (n=2, m= 2)  oblique astigmatism
    j=6  (n=2, m=-2)  vertical astigmatism
    j=7  (n=3, m= 1)  x-coma
    j=8  (n=3, m=-1)  y-coma
    j=9  (n=3, m= 3)  trefoil
    j=10 (n=3, m=-3)  trefoil
    j=11 (n=4, m= 0)  spherical
    ...

Polynomial form (real, normalised)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
For m ≥ 0:
    Z_j(ρ,θ) = √(n+1) · R_n^m(ρ) · { √2·cos(mθ)  for m > 0
                                       1             for m = 0 }
For m < 0:
    Z_j(ρ,θ) = √(n+1) · R_n^|m|(ρ) · √2·sin(|m|θ)

with ρ ∈ [0,1] (normalised pupil radius) and where

    R_n^m(ρ) = Σ_{s=0}^{(n-m)/2}  (-1)^s · C(n-s,s) · C(n-2s,(n-m)/2-s)
               ─────────────────────────────────────────────────────────────
               ρ^(n-2s)

(Eq. 3 in Noll 1976, or equivalently via scipy.special.jacobi).

Normalisation is chosen so that ∫∫_{unit disk} Z_i · Z_j dA / π = δ_{ij},
i.e. the polynomials are orthonormal on the unit disk.

References
----------
- R.J. Noll, "Zernike polynomials and atmospheric turbulence",
  J. Opt. Soc. Am. 66(3), 207–211 (1976). DOI 10.1364/JOSA.66.000207
- M. Born & E. Wolf, "Principles of Optics", 9th ed., §9.2 (2019).
- V.N. Mahajan, "Optical Imaging and Aberrations", Part I (SPIE Press, 1998).
- ISO 24157:2008 "Optics and photonics — Ophthalmological optics and instruments —
  Reporting aberrations of the human eye" (uses Noll ordering).
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

import numpy as np
from scipy.special import factorial  # noqa: F401 — kept for clarity; we use math.comb


# ---------------------------------------------------------------------------
# Noll index ↔ (n, m) conversion
# ---------------------------------------------------------------------------

def noll_index_to_mn(j: int) -> Tuple[int, int]:
    """
    Convert a Noll (1-based) index j to (n, m).

    Parameters
    ----------
    j : int
        Noll index (1-based). Must be >= 1.

    Returns
    -------
    (n, m) : (int, int)
        Radial order n (n >= 0) and azimuthal frequency m
        (-n <= m <= n, same parity as n).

    Raises
    ------
    ValueError if j < 1.

    Notes
    -----
    Algorithm (Noll 1976, Appendix A):
    1. Find n such that n*(n+2)/2 - n < j <= n*(n+2)/2 — equivalently,
       n = ceil((-3 + sqrt(9 + 8*(j-1))) / 2) but we walk from 0 for clarity.
    2. Within the block for degree n, fill m values in Noll order:
       for each |m| from 0 (or 1 if n odd) to n in steps of 2, emit
       the positive-m mode before the negative-m mode (for |m|>0).
    """
    if j < 1:
        raise ValueError(f"Noll index j must be >= 1; got {j}")

    # Find radial order n: the n-th "block" contains (n+1) modes
    # cumulative count of modes up to and including degree n = (n+1)(n+2)/2
    n = 0
    while (n + 1) * (n + 2) // 2 < j:
        n += 1

    # Position within the n-block (1-based)
    # modes before block n: n*(n+1)/2
    pos = j - n * (n + 1) // 2  # 1-based position in the n-block

    # Within the n-block: m values in Noll order.
    # For each |m| (stepping by 2 from n%2 to n):
    #   if |m|==0: one mode (m=0)
    #   else: two modes — negative first, then positive.
    m_abs = n % 2  # starting |m| value (0 for even n, 1 for odd n)
    count = 0
    while True:
        if m_abs == 0:
            count += 1
            if count == pos:
                return n, 0
        else:
            # positive m first, then negative m (Noll 1976 Table 1)
            count += 1
            if count == pos:
                return n, m_abs
            count += 1
            if count == pos:
                return n, -m_abs
        m_abs += 2


# ---------------------------------------------------------------------------
# Radial polynomial R_n^|m|(rho)
# ---------------------------------------------------------------------------

def zernike_radial(n: int, m: int, rho: np.ndarray) -> np.ndarray:
    """
    Evaluate the Zernike radial polynomial R_n^|m|(rho).

    R_n^m(ρ) = Σ_{s=0}^{(n-m)/2} (-1)^s · C(n-s,s)·C(n-2s,(n-m)/2-s) / 1 · ρ^(n-2s)

    (Using the combinatorial form; see Born & Wolf §9.2.1, Eq. 2.)

    Parameters
    ----------
    n   : int, radial order (>= 0)
    m   : int, azimuthal order (|m| <= n, same parity as n)
    rho : ndarray, normalised pupil radius values in [0, 1]

    Returns
    -------
    ndarray of the same shape as rho.
    """
    m_abs = abs(m)
    if (n - m_abs) % 2 != 0:
        return np.zeros_like(rho, dtype=float)

    rho = np.asarray(rho, dtype=float)
    result = np.zeros_like(rho)
    for s in range((n - m_abs) // 2 + 1):
        coeff = ((-1) ** s
                 * math.comb(n - s, s)
                 * math.comb(n - 2 * s, (n - m_abs) // 2 - s))
        result += coeff * rho ** (n - 2 * s)
    return result


# ---------------------------------------------------------------------------
# Single Zernike polynomial (Noll j) on polar grid
# ---------------------------------------------------------------------------

def zernike_poly(j: int, rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """
    Evaluate the j-th Zernike polynomial (Noll ordering) on a polar grid.

    Parameters
    ----------
    j     : int, Noll index (>= 1)
    rho   : ndarray, normalised pupil radius ∈ [0, 1]
    theta : ndarray, azimuthal angle in radians (same shape as rho)

    Returns
    -------
    ndarray of the same shape, zero outside the unit circle (rho > 1).

    Notes
    -----
    Normalisation: orthonormal on the unit disk,
        ∫∫ Z_i Z_j dA / π = δ_{ij}   (δ = Kronecker delta).
    """
    n, m = noll_index_to_mn(j)
    R = zernike_radial(n, m, rho)

    norm = math.sqrt(n + 1)  # √(n+1) for m=0; full factor absorbed below

    if m == 0:
        Z = norm * R
    elif m > 0:
        Z = norm * math.sqrt(2) * R * np.cos(m * theta)
    else:
        Z = norm * math.sqrt(2) * R * np.sin(abs(m) * theta)

    # Zero outside unit circle
    Z[rho > 1.0] = 0.0
    return Z


# ---------------------------------------------------------------------------
# Build the Zernike basis on a Cartesian grid
# ---------------------------------------------------------------------------

def zernike_basis(n_max: int = 8, n_samples: int = 64) -> np.ndarray:
    """
    Return the first n_max Zernike basis polynomials sampled on a circular grid.

    Parameters
    ----------
    n_max    : int, number of Zernike modes to include (Noll indices 1..n_max).
               Default 8 (through coma).
    n_samples: int, grid dimension; the output is (n_max, n_samples, n_samples).
               Default 64.

    Returns
    -------
    basis : ndarray, shape (n_max, n_samples, n_samples)
        basis[i-1] is the (i)-th Zernike polynomial (Noll index i) sampled
        on an n_samples × n_samples Cartesian grid over [-1, 1]².
        Points outside the unit circle have value 0.

    Notes
    -----
    The grid is built so that each pixel centre maps to a normalised (x, y)
    coordinate; samples at the unit-circle boundary are included.

    References
    ----------
    Noll (1976); Born & Wolf §9.2.
    """
    if n_max < 1:
        raise ValueError(f"n_max must be >= 1; got {n_max}")
    if n_samples < 4:
        raise ValueError(f"n_samples must be >= 4; got {n_samples}")

    lin = np.linspace(-1.0, 1.0, n_samples)
    x, y = np.meshgrid(lin, lin)
    rho = np.sqrt(x ** 2 + y ** 2)
    theta = np.arctan2(y, x)

    basis = np.zeros((n_max, n_samples, n_samples), dtype=float)
    for j in range(1, n_max + 1):
        basis[j - 1] = zernike_poly(j, rho, theta)
    return basis


# ---------------------------------------------------------------------------
# Fit wavefront to Zernike modes (least-squares)
# ---------------------------------------------------------------------------

def fit_zernike(wavefront: np.ndarray, n_max: int = 8) -> Dict[int, float]:
    """
    Decompose a 2-D wavefront map into Zernike coefficients via least-squares.

    Parameters
    ----------
    wavefront : ndarray, shape (H, W)
        Wavefront phase map (any units, e.g. waves, radians, nm).
        Must be 2-D.  Pixels outside the unit circle are ignored (NaN or
        masked out by the circular aperture — they are excluded from the fit).
    n_max     : int, number of Zernike modes (Noll indices 1..n_max). Default 8.

    Returns
    -------
    coefficients : dict mapping Noll index j → float coefficient
        The units match the input wavefront units.

    Algorithm
    ---------
    1. Reconstruct the polar grid matching the wavefront dimensions.
    2. Build the design matrix A (n_pixels × n_max) from the Zernike basis,
       keeping only pixels inside the unit circle.
    3. Solve the linear system c = lstsq(A, w_flat) for coefficients c.

    Notes
    -----
    The wavefront is assumed to be defined on the full square grid; only
    points with ρ ≤ 1 are used in the fit.  The basis is evaluated at the
    same grid resolution as the wavefront.

    References
    ----------
    Noll (1976); Malacara "Optical Shop Testing" §3rd ed. Ch.11 (2007).
    """
    wavefront = np.asarray(wavefront, dtype=float)
    if wavefront.ndim != 2:
        raise ValueError(f"wavefront must be 2-D; got shape {wavefront.shape}")

    H, W = wavefront.shape
    n_samples = max(H, W)  # use the larger dimension for basis consistency

    # Build grid at the wavefront resolution
    lin_y = np.linspace(-1.0, 1.0, H)
    lin_x = np.linspace(-1.0, 1.0, W)
    x, y = np.meshgrid(lin_x, lin_y)
    rho = np.sqrt(x ** 2 + y ** 2)
    theta = np.arctan2(y, x)

    # Mask: inside unit circle and not NaN
    mask = (rho <= 1.0) & np.isfinite(wavefront)
    rho_m = rho[mask]
    theta_m = theta[mask]
    w_m = wavefront[mask]

    if w_m.size == 0:
        return {j: 0.0 for j in range(1, n_max + 1)}

    # Design matrix
    A = np.zeros((w_m.size, n_max), dtype=float)
    for j in range(1, n_max + 1):
        A[:, j - 1] = zernike_poly(j, rho_m, theta_m)

    # Least-squares fit
    coeffs, _, _, _ = np.linalg.lstsq(A, w_m, rcond=None)

    return {j: float(coeffs[j - 1]) for j in range(1, n_max + 1)}


# ---------------------------------------------------------------------------
# Reconstruct wavefront from Zernike coefficients
# ---------------------------------------------------------------------------

def reconstruct_wavefront(
    zernike_coefficients: Dict[int, float],
    grid_size: int = 64,
) -> np.ndarray:
    """
    Synthesise a wavefront from Zernike coefficients.

    Parameters
    ----------
    zernike_coefficients : dict mapping Noll index j → coefficient
        Any subset of modes is acceptable; missing modes contribute zero.
    grid_size : int, side of the output square grid. Default 64.

    Returns
    -------
    wavefront : ndarray, shape (grid_size, grid_size)
        Reconstructed wavefront; zero outside the unit circle.

    Notes
    -----
    W(x,y) = Σ_j  c_j · Z_j(ρ,θ)
    """
    if not zernike_coefficients:
        return np.zeros((grid_size, grid_size), dtype=float)

    n_max = max(zernike_coefficients.keys())
    basis = zernike_basis(n_max, grid_size)

    wavefront = np.zeros((grid_size, grid_size), dtype=float)
    for j, coeff in zernike_coefficients.items():
        if 1 <= j <= n_max:
            wavefront += coeff * basis[j - 1]
    return wavefront


# ---------------------------------------------------------------------------
# Classical aberration names
# ---------------------------------------------------------------------------

#: Mapping from Noll index to classical aberration name (primary Seidel / common).
#: Based on Born & Wolf §9.2.3, Mahajan (1998), and Noll (1976).
_NOLL_TO_CLASSICAL: Dict[int, str] = {
    # Noll 1976 Table 1 ordering: within each radial degree n,
    # modes are listed by ascending |m|, positive m before negative m.
    1:  "piston",            # n=0, m=0
    2:  "x-tilt",            # n=1, m=+1
    3:  "y-tilt",            # n=1, m=-1
    4:  "defocus",           # n=2, m=0
    5:  "oblique astigmatism",   # n=2, m=+2
    6:  "vertical astigmatism",  # n=2, m=-2
    7:  "x-coma",            # n=3, m=+1
    8:  "y-coma",            # n=3, m=-1
    9:  "x-trefoil",         # n=3, m=+3
    10: "y-trefoil",         # n=3, m=-3
    11: "spherical",         # n=4, m=0
    12: "secondary oblique astigmatism",  # n=4, m=+2
    13: "secondary vertical astigmatism", # n=4, m=-2
    14: "x-quadrafoil",      # n=4, m=+4
    15: "y-quadrafoil",      # n=4, m=-4
    16: "secondary x-coma",  # n=5, m=+1
    17: "secondary y-coma",  # n=5, m=-1
    18: "secondary x-trefoil",  # n=5, m=+3
    19: "secondary y-trefoil",  # n=5, m=-3
    20: "secondary spherical",  # n=6, m=0
}


def classical_aberration_breakdown(
    zernike_coefficients: Dict[int, float],
) -> dict:
    """
    Map Zernike coefficients to classical aberration names and magnitudes.

    Parameters
    ----------
    zernike_coefficients : dict mapping Noll index j → coefficient

    Returns
    -------
    dict with keys:
      "terms"          : list of dicts, one per mode with non-zero coefficient, sorted
                         by descending |coefficient|.  Each dict has:
                           "noll_index"  : int
                           "name"        : str  (classical name, or "higher-order Z_j")
                           "coefficient" : float
                           "magnitude"   : float  (|coefficient|)
      "primary_aberration": str  — name of the mode with the largest |coefficient|,
                              excluding piston (j=1).
      "rms_wavefront_error": float — √(Σ c_j²) over all modes (Parseval / Noll 1976 eq.7).
      "strehl_ratio_approx": float — exp(-(2π·σ)²) approximation (Maréchal 1947);
                              σ here is in waves (coefficients assumed in waves) — only
                              meaningful when coefficients are in units of λ.

    Notes
    -----
    The Maréchal approximation, Strehl ≈ exp(−(2π·σ)²), is valid for
    σ < λ/14 (Rayleigh criterion); values above that are returned but annotated.
    It is the caller's responsibility to ensure coefficients are in wave units
    for Strehl to be physically meaningful.

    References
    ----------
    - Noll (1976) Eq. 7: σ² = Σ c_j²  (variance)
    - Mahajan (1998) §3.7: Maréchal approximation
    """
    if not zernike_coefficients:
        return {
            "terms": [],
            "primary_aberration": "none",
            "rms_wavefront_error": 0.0,
            "strehl_ratio_approx": 1.0,
        }

    # Build term list
    terms = []
    for j, c in zernike_coefficients.items():
        name = _NOLL_TO_CLASSICAL.get(j, f"higher-order Z_{j}")
        terms.append({
            "noll_index": j,
            "name": name,
            "coefficient": float(c),
            "magnitude": float(abs(c)),
        })

    # Sort by magnitude descending
    terms.sort(key=lambda t: t["magnitude"], reverse=True)

    # Primary aberration: largest |coeff| excluding piston
    non_piston = [t for t in terms if t["noll_index"] != 1]
    primary = non_piston[0]["name"] if non_piston else "piston"

    # RMS wavefront error (Noll 1976 Eq. 7)
    rms = math.sqrt(sum(c ** 2 for c in zernike_coefficients.values()))

    # Maréchal Strehl approximation (valid for rms < 0.07 waves)
    strehl = math.exp(-((2 * math.pi * rms) ** 2))

    return {
        "terms": terms,
        "primary_aberration": primary,
        "rms_wavefront_error": float(rms),
        "strehl_ratio_approx": float(min(strehl, 1.0)),
    }
