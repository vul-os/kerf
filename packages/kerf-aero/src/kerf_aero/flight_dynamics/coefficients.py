"""
Aerodynamic coefficient tables with bilinear interpolation.

Includes example tables for a Cessna 172-class general aviation aircraft.

Coefficient sign conventions (stability axes → body axes lift/drag split):
  CL — lift coefficient (positive up)
  CD — drag coefficient (positive opposing velocity)
  Cm — pitching moment coefficient (positive nose-up)
  CL_de — incremental CL per radian of elevator deflection
  CD_de — incremental CD per radian of elevator deflection
  Cm_de — incremental Cm per radian of elevator deflection

Alpha is angle of attack in radians; M is Mach number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


def _bilinear_interp(
    x: float,
    y: float,
    xs: Sequence[float],
    ys: Sequence[float],
    table: Sequence[Sequence[float]],
) -> float:
    """
    Bilinear interpolation over a 2-D grid.

    Parameters
    ----------
    x:
        Query value for the first dimension (rows indexed by *xs*).
    y:
        Query value for the second dimension (columns indexed by *ys*).
    xs:
        Strictly increasing breakpoints for *x*.
    ys:
        Strictly increasing breakpoints for *y*.
    table:
        2-D array of shape ``(len(xs), len(ys))``.

    Returns
    -------
    float
        Interpolated (and extrapolation-clamped) value.
    """
    # Clamp to grid bounds
    x_c = max(xs[0], min(xs[-1], x))
    y_c = max(ys[0], min(ys[-1], y))

    # Find bounding indices for x
    i1 = 0
    for k in range(len(xs) - 1):
        if xs[k] <= x_c:
            i1 = k
    i2 = min(i1 + 1, len(xs) - 1)

    # Find bounding indices for y
    j1 = 0
    for k in range(len(ys) - 1):
        if ys[k] <= y_c:
            j1 = k
    j2 = min(j1 + 1, len(ys) - 1)

    x1, x2 = xs[i1], xs[i2]
    y1, y2 = ys[j1], ys[j2]

    dx = x2 - x1
    dy = y2 - y1

    if dx < 1e-15:
        tx = 0.0
    else:
        tx = (x_c - x1) / dx

    if dy < 1e-15:
        ty = 0.0
    else:
        ty = (y_c - y1) / dy

    f11 = table[i1][j1]
    f12 = table[i1][j2]
    f21 = table[i2][j1]
    f22 = table[i2][j2]

    return (
        f11 * (1 - tx) * (1 - ty)
        + f12 * (1 - tx) * ty
        + f21 * tx * (1 - ty)
        + f22 * tx * ty
    )


# ---------------------------------------------------------------------------
# Cessna 172-class coefficient tables
# ---------------------------------------------------------------------------
# Alpha breakpoints (rad): −5° … +20° in 5° steps, plus stall region
_C172_ALPHA_DEG = [-5.0, 0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
_C172_ALPHA_RAD = [math.radians(a) for a in _C172_ALPHA_DEG]

# Mach breakpoints (representative low-speed aircraft, subsonic only)
_C172_MACH = [0.0, 0.1, 0.15, 0.2, 0.25, 0.3]

# CL table [alpha-idx][mach-idx]
# Cessna 172-class: CL_alpha ~ 5.1/rad; CL0 ~ 0.30; CLmax ~ 1.5 at ~16°
_C172_CL: list[list[float]] = [
    # M=0.00  0.10   0.15   0.20   0.25   0.30
    [-0.16, -0.16, -0.16, -0.16, -0.15, -0.15],  # α=-5°
    [ 0.30,  0.30,  0.31,  0.31,  0.32,  0.32],  # α= 0°
    [ 0.51,  0.51,  0.52,  0.52,  0.53,  0.54],  # α= 2°
    [ 0.72,  0.72,  0.73,  0.74,  0.75,  0.76],  # α= 4°
    [ 0.93,  0.93,  0.94,  0.95,  0.97,  0.98],  # α= 6°
    [ 1.13,  1.13,  1.14,  1.16,  1.18,  1.20],  # α= 8°
    [ 1.31,  1.31,  1.33,  1.35,  1.37,  1.40],  # α=10°
    [ 1.43,  1.43,  1.45,  1.47,  1.49,  1.52],  # α=12°
    [ 1.50,  1.50,  1.52,  1.54,  1.56,  1.58],  # α=14°
    [ 1.50,  1.50,  1.51,  1.52,  1.53,  1.53],  # α=16° (near stall)
    [ 1.35,  1.35,  1.35,  1.35,  1.35,  1.35],  # α=18° (post-stall)
    [ 1.10,  1.10,  1.10,  1.10,  1.10,  1.10],  # α=20° (deep stall)
]

# CD table [alpha-idx][mach-idx]
# Oswald e~0.75, AR~7.4, CDmin~0.027 (clean)
_C172_CD: list[list[float]] = [
    [ 0.034, 0.034, 0.034, 0.034, 0.035, 0.035],  # α=-5°
    [ 0.027, 0.027, 0.027, 0.027, 0.028, 0.028],  # α= 0°
    [ 0.029, 0.029, 0.029, 0.029, 0.030, 0.030],  # α= 2°
    [ 0.033, 0.033, 0.033, 0.034, 0.034, 0.035],  # α= 4°
    [ 0.042, 0.042, 0.042, 0.043, 0.044, 0.045],  # α= 6°
    [ 0.055, 0.055, 0.055, 0.056, 0.057, 0.059],  # α= 8°
    [ 0.072, 0.072, 0.073, 0.074, 0.076, 0.078],  # α=10°
    [ 0.095, 0.095, 0.096, 0.097, 0.099, 0.102],  # α=12°
    [ 0.123, 0.123, 0.124, 0.126, 0.129, 0.133],  # α=14°
    [ 0.160, 0.160, 0.162, 0.164, 0.167, 0.172],  # α=16°
    [ 0.210, 0.210, 0.212, 0.215, 0.219, 0.225],  # α=18°
    [ 0.270, 0.270, 0.272, 0.276, 0.281, 0.288],  # α=20°
]

# Cm table [alpha-idx][mach-idx]  (about 25% MAC, trimmed at ~4° AoA)
_C172_CM: list[list[float]] = [
    [ 0.060,  0.060,  0.060,  0.059,  0.059,  0.058],  # α=-5°
    [ 0.020,  0.020,  0.020,  0.020,  0.019,  0.019],  # α= 0°
    [ 0.001,  0.001,  0.001,  0.001,  0.000,  0.000],  # α= 2°
    [-0.018, -0.018, -0.018, -0.019, -0.019, -0.020],  # α= 4°
    [-0.037, -0.037, -0.037, -0.038, -0.039, -0.040],  # α= 6°
    [-0.055, -0.055, -0.056, -0.057, -0.058, -0.059],  # α= 8°
    [-0.073, -0.073, -0.074, -0.075, -0.077, -0.079],  # α=10°
    [-0.090, -0.090, -0.091, -0.093, -0.095, -0.097],  # α=12°
    [-0.105, -0.105, -0.106, -0.108, -0.110, -0.113],  # α=14°
    [-0.115, -0.115, -0.116, -0.118, -0.120, -0.123],  # α=16°
    [-0.120, -0.120, -0.121, -0.123, -0.125, -0.128],  # α=18°
    [-0.122, -0.122, -0.123, -0.125, -0.127, -0.130],  # α=20°
]


@dataclass(frozen=True)
class AircraftCoefficients:
    """
    Aerodynamic coefficient table set for a single aircraft configuration.

    Attributes
    ----------
    name:
        Human-readable aircraft name.
    alpha_rad:
        Angle-of-attack breakpoints (rad), strictly increasing.
    mach_breaks:
        Mach number breakpoints, strictly increasing.
    CL_table:
        Lift coefficient table, shape (n_alpha, n_mach).
    CD_table:
        Drag coefficient table, shape (n_alpha, n_mach).
    Cm_table:
        Pitching-moment coefficient table, shape (n_alpha, n_mach).
    CL_de:
        dCL/d(elevator deflection) [/rad]; may be scalar or per-alpha.
    CD_de:
        dCD/d(elevator deflection) [/rad].
    Cm_de:
        dCm/d(elevator deflection) [/rad].
    """

    name: str
    alpha_rad: list[float]
    mach_breaks: list[float]
    CL_table: list[list[float]]
    CD_table: list[list[float]]
    Cm_table: list[list[float]]
    CL_de: float = 0.36    # /rad   (Cessna 172 typical)
    CD_de: float = 0.008   # /rad
    Cm_de: float = -1.30   # /rad   (nose-down per positive elevator)

    # Lateral-directional (simplified — constant)
    CY_beta: float = -0.31   # side force per rad sideslip
    Cl_beta: float = -0.089  # rolling moment per rad sideslip (dihedral)
    Cn_beta: float =  0.065  # yawing moment per rad sideslip (stability)
    Cl_da:   float =  0.178  # rolling moment per rad aileron
    Cn_dr:   float = -0.073  # yawing moment per rad rudder

    def CL(self, alpha: float, mach: float) -> float:
        """Lift coefficient at angle of attack *alpha* (rad) and Mach."""
        return _bilinear_interp(alpha, mach, self.alpha_rad, self.mach_breaks, self.CL_table)

    def CD(self, alpha: float, mach: float) -> float:
        """Drag coefficient at angle of attack *alpha* (rad) and Mach."""
        return _bilinear_interp(alpha, mach, self.alpha_rad, self.mach_breaks, self.CD_table)

    def Cm(self, alpha: float, mach: float) -> float:
        """Pitching-moment coefficient at *alpha* (rad) and Mach."""
        return _bilinear_interp(alpha, mach, self.alpha_rad, self.mach_breaks, self.Cm_table)


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

#: Pre-built Cessna 172-class coefficient set.
CESSNA172: AircraftCoefficients = AircraftCoefficients(
    name="Cessna 172-class",
    alpha_rad=_C172_ALPHA_RAD,
    mach_breaks=_C172_MACH,
    CL_table=_C172_CL,
    CD_table=_C172_CD,
    Cm_table=_C172_CM,
)


def get_coefficients(name: str = "cessna172") -> AircraftCoefficients:
    """
    Return a named coefficient set.

    Currently available: ``"cessna172"`` (default).
    """
    registry = {
        "cessna172": CESSNA172,
        "c172": CESSNA172,
    }
    key = name.lower().replace(" ", "").replace("-", "")
    if key not in registry:
        raise KeyError(f"Unknown aircraft '{name}'. Available: {list(registry)}")
    return registry[key]
