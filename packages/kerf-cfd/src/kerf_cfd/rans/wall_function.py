"""
Standard wall functions for RANS turbulence models.

Implements the Launder-Spalding (1974) wall-function treatment for
near-wall cells, providing the piecewise U+ profile across the viscous
sublayer and the log-law region.

Wall coordinate definitions
---------------------------
  y+ = ρ u_τ y / μ    (dimensionless wall distance)
  u+ = U / u_τ         (dimensionless streamwise velocity)

  u_τ = √(τ_w / ρ)     (friction velocity)
  τ_w = wall shear stress [Pa]

Two regions (Launder & Spalding 1974, §3):
------------------------------------------
  Viscous sublayer  (y+ < y+_lam ≈ 11.06):
    u+ = y+            (linear law, Stokes flow near wall)

  Log-law region  (y+ > y+_lam):
    u+ = (1/κ) ln(y+) + B   (logarithmic law of the wall)
    κ = 0.41  (von Kármán constant)
    B = 5.5   (smooth-wall additive constant)

The viscous sublayer / log-law transition y+ ≈ 11.06 is the intersection
of the linear and log-law profiles:
    y+_lam : y+_lam = (1/κ) ln(y+_lam) + B
    Solution: y+_lam ≈ 11.06  (cf. Launder-Spalding 1974 §3; Pope 2000 §7.1)

References
----------
[LS1974]   Launder B. E., Spalding D. B., "The Numerical Computation of
           Turbulent Flows." Comput. Methods Appl. Mech. Engng. 3 (1974)
           269-289.  Wall functions §3.
[Pope2000] Pope S. B., "Turbulent Flows." Cambridge, 2000. §7.1.
[Wilcox06] Wilcox D. C., "Turbulence Modeling for CFD." 3rd ed., 2006.
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Default wall-function constants
# ---------------------------------------------------------------------------

_KAPPA_DEFAULT: float = 0.41    # von Kármán constant  [Pope2000 §7.1]
_B_DEFAULT:     float = 5.5     # log-law additive constant (smooth wall)
_YPLUS_LAM:     float = 11.06   # viscous-sublayer / log-law transition y+


# ---------------------------------------------------------------------------
# Dimensionless wall distance
# ---------------------------------------------------------------------------

def y_plus(rho: float, u_tau: float, y: float, mu: float) -> float:
    """
    Dimensionless wall distance.

        y+ = ρ · u_τ · y / μ

    Parameters
    ----------
    rho   : fluid density [kg/m³]
    u_tau : friction velocity u_τ = √(τ_w / ρ) [m/s]
    y     : wall-normal distance to cell centre [m]
    mu    : dynamic viscosity [Pa·s]

    Returns
    -------
    y+ ≥ 0  (dimensionless)

    References: [LS1974 §3]; [Pope2000 §7.1 eq. 7.37].
    """
    if mu <= 0.0:
        raise ValueError(f"mu must be > 0, got {mu}")
    return rho * u_tau * y / mu


# ---------------------------------------------------------------------------
# Dimensionless velocity profiles
# ---------------------------------------------------------------------------

def u_plus_viscous(y_plus_val: float) -> float:
    """
    Dimensionless velocity in the viscous sublayer.

        u+ = y+   (linear law, y+ < 5)

    Valid for y+ < 5 (viscous sublayer where turbulence is negligible and
    the velocity profile is purely viscous).

    Parameters
    ----------
    y_plus_val : dimensionless wall distance y+

    Returns
    -------
    u+ = y+   (always non-negative for y+ ≥ 0)

    References: [LS1974 §3]; [Pope2000 §7.1 eq. 7.36].
    """
    return max(y_plus_val, 0.0)


def u_plus_log(
    y_plus_val: float,
    kappa: float = _KAPPA_DEFAULT,
    B: float = _B_DEFAULT,
) -> float:
    """
    Dimensionless velocity in the log-law region.

        u+ = (1/κ) · ln(y+) + B

    Valid for y+ > 30 (fully logarithmic region above the buffer layer).

    Parameters
    ----------
    y_plus_val : dimensionless wall distance y+, must be > 0
    kappa      : von Kármán constant κ (default 0.41)
    B          : log-law additive constant (default 5.5, smooth wall)

    Returns
    -------
    u+  (dimensionless streamwise velocity)

    References: [LS1974 §3]; [Pope2000 §7.1 eq. 7.40].
    """
    if y_plus_val <= 0.0:
        return 0.0
    return (1.0 / kappa) * math.log(max(y_plus_val, 1.0e-30)) + B


# ---------------------------------------------------------------------------
# Piecewise standard wall function
# ---------------------------------------------------------------------------

def standard_wall_function(
    y_plus_val: float,
    kappa: float = _KAPPA_DEFAULT,
    B: float = _B_DEFAULT,
) -> float:
    """
    Piecewise standard wall function.

    Uses the linear (viscous sublayer) law below y+_lam and the logarithmic
    law above y+_lam.  The crossover y+_lam is the intersection of the two
    profiles:

        y+_lam ≈ 11.06   (Launder-Spalding 1974 §3; Pope 2000 §7.1)

    Specifically:
        u+ = y+                         if y+ ≤ y+_lam  (viscous sublayer)
        u+ = (1/κ) · ln(y+) + B        if y+ > y+_lam  (log-law region)

    Parameters
    ----------
    y_plus_val : dimensionless wall distance y+
    kappa      : von Kármán constant κ (default 0.41)
    B          : log-law additive constant (default 5.5)

    Returns
    -------
    u+  (dimensionless streamwise velocity)

    References: [LS1974 §3]; [Pope2000 §7.1].
    """
    if y_plus_val <= 0.0:
        return 0.0
    # Recompute y+_lam for the given (kappa, B) pair to ensure consistency
    # y+_lam is the solution of: y+ = (1/kappa) ln(y+) + B
    # We use the fixed LS1974 default value (11.06) only when the caller
    # uses the default kappa/B, otherwise we recompute via Newton iteration.
    if abs(kappa - _KAPPA_DEFAULT) < 1.0e-12 and abs(B - _B_DEFAULT) < 1.0e-12:
        y_plus_lam = _YPLUS_LAM
    else:
        # Newton iteration to find y+_lam = (1/κ) ln(y+_lam) + B
        y_lam = _YPLUS_LAM
        for _ in range(50):
            f  = y_lam - (1.0 / kappa) * math.log(max(y_lam, 1.0e-30)) - B
            df = 1.0 - 1.0 / (kappa * max(y_lam, 1.0e-30))
            if abs(df) < 1.0e-30:
                break
            y_lam -= f / df
            y_lam = max(y_lam, 1.0)
        y_plus_lam = y_lam

    if y_plus_val <= y_plus_lam:
        return u_plus_viscous(y_plus_val)
    else:
        return u_plus_log(y_plus_val, kappa=kappa, B=B)


# ---------------------------------------------------------------------------
# Friction velocity from wall stress
# ---------------------------------------------------------------------------

def friction_velocity(tau_w: float, rho: float) -> float:
    """
    Friction velocity from wall shear stress.

        u_τ = √(τ_w / ρ)

    Parameters
    ----------
    tau_w : wall shear stress [Pa], must be ≥ 0
    rho   : fluid density [kg/m³], must be > 0

    Returns
    -------
    u_τ ≥ 0  [m/s]

    References: [LS1974 §3]; [Pope2000 §7.1].
    """
    if tau_w < 0.0:
        raise ValueError(f"tau_w must be ≥ 0, got {tau_w}")
    if rho <= 0.0:
        raise ValueError(f"rho must be > 0, got {rho}")
    return math.sqrt(tau_w / rho)
