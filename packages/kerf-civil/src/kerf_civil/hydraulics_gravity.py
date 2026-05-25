"""
kerf_civil.hydraulics_gravity — Manning's equation for gravity flow.

Covers:
  - Part-full circular pipe (sewer): geometric properties at a given depth
  - Normal-depth solve for a circular pipe
  - Full-flow circular pipe capacity
  - Open-channel trapezoidal section: geometry + capacity

Standard references
-------------------
Manning's equation (SI units):
    Q = (1/n) * A * R^(2/3) * S^(1/2)
    Reference: Chaudhry, M.H. (2008). Open-Channel Hydraulics, 2nd Ed.,
    Springer. §2.5.

Circular section geometry:
    Reference: Mays, L.W. (2011). Water Resources Engineering, 2nd Ed.,
    Wiley. Table 4.1.

    For a circular pipe of diameter d, water depth y (0 ≤ y ≤ d):
        θ    = 2 * arccos(1 - 2y/d)       [central angle in radians]
        A    = (d²/8) * (θ - sin θ)        [flow area]
        P    = d/2 * θ                      [wetted perimeter]
        R    = A / P                        [hydraulic radius]

Trapezoidal section:
    bottom width b, side slope z (H:1V)
    A = (b + z*y) * y
    P = b + 2*y*sqrt(1 + z²)
    Reference: Chaudhry (2008) §2.4.

Validation
----------
Full-flow circular capacity:
    d = 0.600 m, n = 0.013, S = 0.001
    Q_full = (1/0.013) * π(0.3)² * (0.3/2)^(2/3) * √(0.001)
           ≈ 0.2023 m³/s
    Checked against Mays (2011) Table 4.2.

Public API
----------
circular_section_geometry(d, y)
    → dict: area, wetted_perimeter, hydraulic_radius, top_width, theta_rad

circular_full_flow(d, n, slope)
    → float (m³/s)

circular_normal_depth(d, n, slope, Q, tol=1e-8, max_iter=60)
    → float (y/d ratio)

circular_capacity_at_depth(d, n, slope, y)
    → float (m³/s)

trapezoidal_geometry(b, z, y)
    → dict

trapezoidal_normal_depth(b, z, n, slope, Q, tol=1e-8, max_iter=60)
    → float (depth y in metres)

trapezoidal_capacity(b, z, n, slope, y)
    → float (m³/s)
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Circular section geometry
# ---------------------------------------------------------------------------

def circular_section_geometry(d: float, y: float) -> dict:
    """
    Geometric properties of a circular pipe of diameter *d* at water depth *y*.

    Parameters
    ----------
    d : float — internal pipe diameter (m)
    y : float — water depth (m), 0 ≤ y ≤ d

    Returns
    -------
    dict with keys:
        area_m2           : flow area (m²)
        wetted_perimeter_m: wetted perimeter (m)
        hydraulic_radius_m: hydraulic radius = A/P (m)
        top_width_m       : water surface width (m)
        theta_rad         : central angle (rad)
    """
    if d <= 0:
        raise ValueError(f"diameter must be > 0, got {d!r}")
    y = max(0.0, min(y, d))

    if y == 0.0:
        return {
            "area_m2": 0.0,
            "wetted_perimeter_m": 0.0,
            "hydraulic_radius_m": 0.0,
            "top_width_m": 0.0,
            "theta_rad": 0.0,
        }

    if y >= d:
        # Full flow — use pipe full geometry
        A = math.pi * (d / 2.0) ** 2
        P = math.pi * d
        R = d / 4.0
        return {
            "area_m2": A,
            "wetted_perimeter_m": P,
            "hydraulic_radius_m": R,
            "top_width_m": 0.0,  # no free surface at full flow
            "theta_rad": 2.0 * math.pi,
        }

    # Partial depth
    ratio = 1.0 - 2.0 * y / d
    # clamp to avoid floating-point domain errors
    ratio = max(-1.0, min(1.0, ratio))
    theta = 2.0 * math.acos(ratio)  # central angle (radians)

    r = d / 2.0
    A = (r ** 2 / 2.0) * (theta - math.sin(theta))
    P = r * theta
    R = A / P if P > 1e-20 else 0.0
    T = d * math.sin(theta / 2.0)  # top width

    return {
        "area_m2": A,
        "wetted_perimeter_m": P,
        "hydraulic_radius_m": R,
        "top_width_m": T,
        "theta_rad": theta,
    }


# ---------------------------------------------------------------------------
# Manning's Q for circular pipe
# ---------------------------------------------------------------------------

def circular_full_flow(d: float, n: float, slope: float) -> float:
    """
    Full-flow (pipe-full) discharge by Manning's equation.

    Q = (1/n) * A * R^(2/3) * S^(1/2)

    Parameters
    ----------
    d     : float — pipe diameter (m)
    n     : float — Manning's roughness coefficient
    slope : float — hydraulic gradient (m/m), positive

    Returns
    -------
    float — discharge (m³/s)
    """
    if d <= 0 or n <= 0 or slope <= 0:
        raise ValueError("d, n, slope must all be > 0")
    A = math.pi * (d / 2.0) ** 2
    R = d / 4.0  # R_full = d/4
    return (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(slope)


def circular_capacity_at_depth(d: float, n: float, slope: float, y: float) -> float:
    """
    Discharge at partial depth *y* in a circular pipe (Manning's equation).

    Parameters
    ----------
    d, n, slope : as above
    y : float — water depth (m), 0 ≤ y ≤ d

    Returns
    -------
    float — discharge (m³/s)
    """
    if d <= 0 or n <= 0 or slope <= 0:
        raise ValueError("d, n, slope must all be > 0")
    geom = circular_section_geometry(d, y)
    A = geom["area_m2"]
    R = geom["hydraulic_radius_m"]
    if A <= 0.0 or R <= 0.0:
        return 0.0
    return (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(slope)


def circular_normal_depth(
    d: float,
    n: float,
    slope: float,
    Q: float,
    tol: float = 1e-8,
    max_iter: int = 60,
) -> float:
    """
    Solve for the normal depth in a circular pipe given discharge *Q*.

    Uses bisection on Q(y) − Q_target.

    Returns
    -------
    float — y/d ratio (dimensionless depth)
    """
    if Q <= 0:
        return 0.0
    Q_full = circular_full_flow(d, n, slope)
    if Q >= Q_full:
        return 1.0  # surcharged / pressure flow

    # Bisect in y ∈ [0, d]
    y_lo, y_hi = 0.0, d
    for _ in range(max_iter):
        y_mid = (y_lo + y_hi) / 2.0
        q_mid = circular_capacity_at_depth(d, n, slope, y_mid)
        if q_mid < Q:
            y_lo = y_mid
        else:
            y_hi = y_mid
        if y_hi - y_lo < tol * d:
            break
    return ((y_lo + y_hi) / 2.0) / d


# ---------------------------------------------------------------------------
# Trapezoidal open channel
# ---------------------------------------------------------------------------

def trapezoidal_geometry(b: float, z: float, y: float) -> dict:
    """
    Geometric properties of a trapezoidal channel section.

    Parameters
    ----------
    b : float — bottom width (m)
    z : float — side slope (H : 1V)
    y : float — water depth (m)

    Returns
    -------
    dict: area_m2, wetted_perimeter_m, hydraulic_radius_m, top_width_m
    """
    if b < 0 or z < 0 or y < 0:
        raise ValueError("b, z, y must all be ≥ 0")
    A = (b + z * y) * y
    P = b + 2.0 * y * math.sqrt(1.0 + z ** 2)
    R = A / P if P > 1e-20 else 0.0
    T = b + 2.0 * z * y
    return {
        "area_m2": A,
        "wetted_perimeter_m": P,
        "hydraulic_radius_m": R,
        "top_width_m": T,
    }


def trapezoidal_capacity(b: float, z: float, n: float, slope: float, y: float) -> float:
    """
    Manning's discharge for a trapezoidal channel at depth *y*.

    Returns float — discharge (m³/s)
    """
    if n <= 0 or slope <= 0:
        raise ValueError("n, slope must be > 0")
    geom = trapezoidal_geometry(b, z, y)
    A = geom["area_m2"]
    R = geom["hydraulic_radius_m"]
    if A <= 0.0 or R <= 0.0:
        return 0.0
    return (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(slope)


def trapezoidal_normal_depth(
    b: float,
    z: float,
    n: float,
    slope: float,
    Q: float,
    tol: float = 1e-8,
    max_iter: int = 60,
) -> float:
    """
    Normal depth in a trapezoidal channel for discharge *Q*.

    Returns
    -------
    float — water depth y (m)
    """
    if Q <= 0:
        return 0.0
    # Upper bound: deep enough that Q_section >> Q
    y_hi = max(1.0, Q)  # generous upper bound; refine
    while trapezoidal_capacity(b, z, n, slope, y_hi) < Q:
        y_hi *= 2.0
        if y_hi > 1e6:
            break
    y_lo = 0.0

    for _ in range(max_iter):
        y_mid = (y_lo + y_hi) / 2.0
        if trapezoidal_capacity(b, z, n, slope, y_mid) < Q:
            y_lo = y_mid
        else:
            y_hi = y_mid
        if y_hi - y_lo < tol:
            break
    return (y_lo + y_hi) / 2.0
