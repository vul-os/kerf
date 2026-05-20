"""Fuselage (and propeller slipstream) stability derivative terms.

Uses DATCOM / Roskam closed-form expressions for the fuselage contribution
to pitching moment and directional stability.

References
----------
Roskam, J. (1971). "Methods for Estimating Stability and Control
  Derivatives of Conventional Subsonic Airplanes", Part I, Ch 4–6.
USAF DATCOM, Section 4.2.
"""

from __future__ import annotations

import math


def fuselage_pitching_moment(
    fuselage_length: float,       # m
    fuselage_max_width: float,    # m (maximum fuselage width/diameter)
    fuselage_max_height: float,   # m (maximum fuselage height)
    # Wing reference
    S_ref: float = 16.2,          # m²
    c_mean: float = 1.49,         # m
    # Mach number
    mach: float = 0.12,
) -> dict[str, float]:
    """Fuselage contribution to Cm_alpha (Roskam Vol I, eq 4.8).

    The fuselage produces a destabilising (positive) pitching-moment slope.

    Roskam formula (eq 4.8, simplified):
      Cm_alpha_fus = (K_fus * w_f^2 * l_f) / (c_mean * S_ref)

    where:
      K_fus = empirical factor ~ 0.0035 (from Roskam Fig 4.4, typical GA)
      w_f   = maximum fuselage width (m)
      l_f   = fuselage length (m)

    Returns
    -------
    dict with keys:
        Cm_alpha_fus  (/rad) — fuselage destabilising pitching-moment slope
        Cn_beta_fus   (/rad) — fuselage destabilising directional-stability slope
    """
    # Effective fuselage cross-section width (circular equiv)
    w_f = max(fuselage_max_width, fuselage_max_height)

    # Roskam empirical K factor (Fig 4.4, typical value for GA aircraft at low Mach)
    # K_fus ~ 0.0035 per deg = 0.20 per radian (Roskam uses per-degree tables;
    # the dimensionless formulation below gives /rad directly).
    # Roskam Vol I, eq 4.8 (in the per-rad form):
    #   Cm_alpha_fus = K2 * w_f^2 * l_f / (S_w * c_mean)
    # K2 ~ 0.00385 (tabulated for typical fuselage fineness ratios ~ 8-10)
    fineness = fuselage_length / w_f
    # K2 from Roskam Fig 4.4 — piece-wise linear approximation:
    if fineness < 4:
        K2 = 0.0028
    elif fineness < 7:
        K2 = 0.0028 + (fineness - 4) / 3 * 0.0010
    elif fineness < 12:
        K2 = 0.0038 + (fineness - 7) / 5 * 0.0008
    else:
        K2 = 0.0046

    Cm_alpha_fus = K2 * w_f**2 * fuselage_length / (S_ref * c_mean)

    # Fuselage directional instability (DATCOM §4.2.1.1 / Roskam Vol I, §4.4):
    # Cn_beta_fus = -(K_N) * (S_fs / S_ref) * (l_f / b)  — destabilising
    # S_fs = fuselage side area ~ l_f * w_f (rough)
    # K_N = DATCOM empirical coefficient for streamlined body ~ 0.35-0.45
    # (non-dimensional; different from the K2 Cm_alpha coefficient)
    # References: DATCOM Fig 4.2.1.1-3; Roskam Vol I, eq 4.19-20
    S_fs = fuselage_length * w_f  # side area (m²)
    K_N = 0.36   # streamlined fuselage; DATCOM nominal for l_f/d_f ~ 8-12

    # Cn_beta_fus = -(K_N * S_fs) / (S_ref * b) — returned without /b for driver
    Cn_beta_fus_per_b = -(K_N * S_fs) / S_ref

    return {
        "Cm_alpha_fus": Cm_alpha_fus,
        "Cn_beta_fus_per_b": Cn_beta_fus_per_b,  # divide by span in driver
        "K2": K2,
        "fineness": fineness,
    }


def propeller_contribution(
    n_engines: int = 1,
    thrust_N: float = 0.0,
    dynamic_pressure_Pa: float = 1000.0,
    S_ref: float = 16.2,
    c_mean: float = 1.49,
    x_prop_from_cg: float = 0.0,    # + aft, – fwd (m)
) -> dict[str, float]:
    """Propeller contribution to Cm_alpha (direct thrust-line offset).

    For tractor propellers on a GA aircraft the normal-force of the propeller
    disc is small at low alpha; the dominant effect is thrust-line moment.
    Cm_alpha_prop ≈ 0 in the linear range (thrust normal-force is second
    order).  Included here for completeness.

    Returns
    -------
    dict with keys:
        Cm_alpha_prop (/rad) — propeller thrust-line pitching moment slope
    """
    # Propeller normal-force contribution (small, Roskam Vol I §4.7):
    # T_N_per_rad ≈ 0 for constant-speed prop in level flight
    # Thrust-line offset gives Cm = T * z_prop / (q * S * c) but dCm/d_alpha ~ 0
    Cm_alpha_prop = 0.0

    return {"Cm_alpha_prop": Cm_alpha_prop}
