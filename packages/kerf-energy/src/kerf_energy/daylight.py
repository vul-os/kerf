"""
Daylight factor calculation — split-flux method.

References:
  BS 8206-2:2008 — Lighting for buildings, Part 2: Code of practice for
    daylighting.
  IES LM-83-12 — Spatial Daylight Autonomy (sDA) and Annual Sunlight
    Exposure (ASE).
  Hopkinson, R. G., Petherbridge, P., & Longmore, J. (1966). Daylighting.
    Heinemann.  (split-flux derivation).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Split-flux (BRS) daylight factor
# ---------------------------------------------------------------------------

def daylight_factor_split_flux(
    window_area_m2: float,
    room_floor_area_m2: float,
    *,
    tau: float = 0.6,
    sky_component_fraction: float = 0.4,
    average_reflectance: float = 0.5,
    externally_obstructed_fraction: float = 0.0,
) -> float:
    """Calculate the mean Daylight Factor (DF) using the BRS split-flux method.

    The Daylight Factor is the ratio (%) of interior illuminance at a reference
    point to the simultaneous unobstructed horizontal illuminance outdoors under
    an overcast CIE sky.

    Split-flux formula (mean DF across the working plane):
        DF = (τ · A_w · θ) / (A_total · (1 − ρ̄²))  × 100 %
    where:
        τ      = glazing visible-light transmittance (default 0.6)
        A_w    = total glazed area (m²)
        θ      = sky-angle factor (fraction of sky visible from window; this
                 implementation treats ``sky_component_fraction`` as a
                 simplified sky-angle / obstruction factor, 0–1)
        A_total = total room surface area, approximated from floor area
                 assuming a compact room.  When not provided separately this
                 implementation uses 6 × floor area as a cube-room proxy.
        ρ̄     = area-weighted average surface reflectance

    Parameters
    ----------
    window_area_m2:
        Total glazed area of daylight apertures (m²).
    room_floor_area_m2:
        Floor area of the room (m²).
    tau:
        Visible-light transmittance of glazing (0–1, default 0.6).
    sky_component_fraction:
        Fraction of external sky visible from the window centroid (0–1).
        Accounts for external obstructions.  Default 0.4 (typical urban).
    average_reflectance:
        Area-weighted mean surface reflectance of walls, ceiling, and floor
        (0–1, default 0.5).
    externally_obstructed_fraction:
        Additional obstruction fraction (0–1).  Applied multiplicatively on
        top of ``sky_component_fraction``.

    Returns
    -------
    float
        Mean daylight factor as a percentage (0–100).
    """
    if window_area_m2 < 0:
        raise ValueError(f"window_area_m2 must be non-negative, got {window_area_m2}")
    if room_floor_area_m2 <= 0:
        raise ValueError(f"room_floor_area_m2 must be positive, got {room_floor_area_m2}")
    if not (0 < tau <= 1):
        raise ValueError(f"tau must be in (0, 1], got {tau}")
    if not (0 <= average_reflectance < 1):
        raise ValueError(
            f"average_reflectance must be in [0, 1), got {average_reflectance}"
        )

    # Total room surface area — cube-room approximation: A ≈ 6 × floor_area
    total_surface_area_m2 = 6.0 * room_floor_area_m2

    effective_sky = sky_component_fraction * (1.0 - externally_obstructed_fraction)

    # Split-flux mean DF:
    #   DF = (τ · A_w · effective_sky) / (A_total · (1 − ρ̄²)) × 100
    numerator = tau * window_area_m2 * effective_sky
    denominator = total_surface_area_m2 * (1.0 - average_reflectance ** 2)

    if denominator == 0:
        return 0.0

    df_percent = (numerator / denominator) * 100.0
    return df_percent


# ---------------------------------------------------------------------------
# Target / compliance helpers
# ---------------------------------------------------------------------------

# BS 8206-2 recommended mean DF targets by space type.
BS8206_TARGETS: dict[str, float] = {
    "kitchen": 2.0,
    "living_room": 1.5,
    "bedroom": 1.0,
    "office": 2.0,
    "classroom": 2.0,
    "corridor": 0.5,
}


def check_bs8206_compliance(space_type: str, df_percent: float) -> dict:
    """Return a compliance dict for BS 8206-2 mean DF targets.

    Parameters
    ----------
    space_type:
        One of the space keys in ``BS8206_TARGETS``.
    df_percent:
        Calculated mean daylight factor (%).

    Returns
    -------
    dict
        ``{"compliant": bool, "target": float, "actual": float, "margin": float}``
    """
    target = BS8206_TARGETS.get(space_type)
    if target is None:
        raise ValueError(
            f"Unknown space type '{space_type}'. "
            f"Known types: {list(BS8206_TARGETS.keys())}"
        )
    compliant = df_percent >= target
    return {
        "compliant": compliant,
        "target": target,
        "actual": df_percent,
        "margin": df_percent - target,
    }
