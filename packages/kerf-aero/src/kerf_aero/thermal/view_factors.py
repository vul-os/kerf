"""
Analytic view-factor formulas for canonical geometry pairs.

References
----------
  Howell, J.R., Menguç, M.P., Siegel, R., "Thermal Radiation Heat Transfer",
  7th ed., CRC Press, 2021.  View-factor catalogue at
  http://www.thermalradiation.net/

  Incropera et al., "Fundamentals of Heat and Mass Transfer", 7th ed.

Notation
--------
  F_{i→j}  : view factor from surface i to surface j
           = fraction of diffuse radiation leaving i that strikes j.

Reciprocity:  A_i F_{i→j} = A_j F_{j→i}
Summation:    Σ_j F_{i→j} = 1   (for a closed enclosure)

All lengths in metres.  Returned view factors are in [0, 1].
"""

from __future__ import annotations

import math
from typing import Tuple


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_positive(**kwargs: float) -> None:
    for name, val in kwargs.items():
        if val <= 0:
            raise ValueError(f"{name} must be positive, got {val!r}")


# ---------------------------------------------------------------------------
# Infinite parallel plates
# ---------------------------------------------------------------------------

def parallel_plates_infinite() -> float:
    """
    View factor between two infinite parallel plates (Howell C-1).

        F_{1→2} = 1.0

    This holds regardless of plate spacing or width.

    Returns
    -------
    float
        1.0
    """
    return 1.0


# ---------------------------------------------------------------------------
# Parallel identical rectangles, directly opposed
# ---------------------------------------------------------------------------

def parallel_rectangles_equal(a: float, b: float, c: float) -> float:
    """
    View factor F_{1→2} between two identical, directly-opposed, parallel
    rectangles of dimensions *a* × *b* separated by distance *c*
    (Howell C-11; also Incropera Table 13.1, case 1).

        X = a / c,  Y = b / c

        F = (2 / (π X Y)) * [
              ln( sqrt((1+X²)(1+Y²) / (1+X²+Y²)) )
            + X sqrt(1+Y²) arctan(X / sqrt(1+Y²))
            + Y sqrt(1+X²) arctan(Y / sqrt(1+X²))
            - X arctan(X) - Y arctan(Y)
            ]

    Parameters
    ----------
    a, b : float
        Rectangle side lengths [m].
    c : float
        Separation distance [m].

    Returns
    -------
    float
        View factor F_{1→2} in [0, 1].
    """
    _check_positive(a=a, b=b, c=c)
    X = a / c
    Y = b / c
    X2 = X * X
    Y2 = Y * Y
    term1 = math.log(math.sqrt((1 + X2) * (1 + Y2) / (1 + X2 + Y2)))
    term2 = X * math.sqrt(1 + Y2) * math.atan(X / math.sqrt(1 + Y2))
    term3 = Y * math.sqrt(1 + X2) * math.atan(Y / math.sqrt(1 + X2))
    term4 = -X * math.atan(X)
    term5 = -Y * math.atan(Y)
    F = (2.0 / (math.pi * X * Y)) * (term1 + term2 + term3 + term4 + term5)
    return max(0.0, min(1.0, F))


# ---------------------------------------------------------------------------
# Perpendicular rectangles sharing one edge
# ---------------------------------------------------------------------------

def perpendicular_rectangles_shared_edge(
    w: float, h: float, l: float
) -> float:
    """
    View factor F_{1→2} between two rectangles sharing a common edge,
    oriented at 90° to each other (Howell C-12; Incropera Table 13.1, case 2).

    Surface 1: dimensions *w* × *l* (width × length)
    Surface 2: dimensions *h* × *l* (height × length)
    They share the edge of length *l*.

        H = h / w,  W_ratio = l / w   (note: Howell uses W for the width ratio)

    Howell C-12 formula (a = H = h/l, b = W = w/l  per Howell notation):
        Let  A = W / √(1 + W²),   B = H / √(1 + H²)
        ...

    Using the standard Incropera notation directly:

        H = h/l,  W = w/l
        F_{1→2} = (1/πW) [W arctan(1/W) + H arctan(1/H)
                          - √(H²+W²) arctan(1/√(H²+W²))
                          + (1/4) ln{ [(1+W²)(1+H²)/(1+W²+H²)] *
                              [(W²(1+W²+H²)/((1+W²)(W²+H²)))^W²] *
                              [(H²(1+H²+W²)/((1+H²)(H²+W²)))^H²] }]

    (Incropera 7th ed., Table 13.1, geometry 2 / eq. 13.4)

    Parameters
    ----------
    w : float
        Width of surface 1 (perpendicular direction) [m].
    h : float
        Height of surface 2 (perpendicular direction) [m].
    l : float
        Length of the shared edge [m].

    Returns
    -------
    float
        F_{1→2} in [0, 1].
    """
    _check_positive(w=w, h=h, l=l)
    H = h / l
    W = w / l
    H2 = H * H
    W2 = W * W
    HW2 = H2 + W2

    # arctan terms
    t1 = W * math.atan(1.0 / W)
    t2 = H * math.atan(1.0 / H)
    t3 = -math.sqrt(HW2) * math.atan(1.0 / math.sqrt(HW2))

    # logarithm term
    log_arg = (
        ((1 + W2) * (1 + H2) / (1 + HW2))
        * ((W2 * (1 + HW2) / ((1 + W2) * (W2 + H2))) ** W2)
        * ((H2 * (1 + HW2) / ((1 + H2) * (H2 + W2))) ** H2)
    )
    # guard against log(0) in degenerate cases
    if log_arg <= 0:
        log_arg = 1e-300
    t4 = 0.25 * math.log(log_arg)

    F = (1.0 / (math.pi * W)) * (t1 + t2 + t3 + t4)
    return max(0.0, min(1.0, F))


# ---------------------------------------------------------------------------
# Coaxial parallel disks of equal radius
# ---------------------------------------------------------------------------

def parallel_disks_equal_radius(r: float, h: float) -> float:
    """
    View factor F_{1→2} between two coaxial, parallel, equal-radius disks
    separated by distance *h* (Howell C-41; Incropera Table 13.1, case 4):

        R = r / h
        S = 1 + (1 + R²) / R²   →   1 + 1/R² + 1

        F = (S/2) - sqrt( (S/2)² - (r2/r1)² )

    For equal radii r1 = r2 = r:
        F = (S - sqrt(S² - 4)) / 2
    where S = 1 + (1 + R²) / R²

    Parameters
    ----------
    r : float
        Disk radius [m].
    h : float
        Separation distance [m].

    Returns
    -------
    float
        F_{1→2} in [0, 1].
    """
    _check_positive(r=r, h=h)
    R = r / h
    R2 = R * R
    S = 1.0 + (1.0 + R2) / R2
    disc = S * S - 4.0
    if disc < 0.0:
        disc = 0.0
    F = 0.5 * (S - math.sqrt(disc))
    return max(0.0, min(1.0, F))


# ---------------------------------------------------------------------------
# Sphere to environment (enclosing sphere / convex object)
# ---------------------------------------------------------------------------

def sphere_to_environment() -> float:
    """
    View factor F_{1→2} from a convex surface (e.g., a sphere) to the
    surrounding enclosure (Howell; Incropera Eq. 13.3).

    A convex surface cannot "see" itself, so:

        F_{1→2} = 1.0

    Returns
    -------
    float
        1.0
    """
    return 1.0


# ---------------------------------------------------------------------------
# Convenience: view-factor matrix for two-surface enclosure
# ---------------------------------------------------------------------------

def two_surface_enclosure(
    A1: float,
    A2: float,
    F12: float,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Complete the 2×2 view-factor matrix for a two-surface enclosure.

    Given F_{1→2} and areas A1, A2:
      - F_{1→1} = 1 - F_{1→2}
      - F_{2→1} = A1 F_{1→2} / A2   (reciprocity)
      - F_{2→2} = 1 - F_{2→1}

    Parameters
    ----------
    A1, A2 : float
        Surface areas [m²].
    F12 : float
        View factor F_{1→2}.

    Returns
    -------
    ((F11, F12), (F21, F22))
    """
    _check_positive(A1=A1, A2=A2)
    if not (0.0 <= F12 <= 1.0):
        raise ValueError(f"F12 must be in [0, 1], got {F12}")
    F11 = 1.0 - F12
    F21 = A1 * F12 / A2
    F22 = 1.0 - F21
    return (F11, F12), (F21, F22)
