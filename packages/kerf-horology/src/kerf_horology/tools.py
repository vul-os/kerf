"""LLM-callable tools for the horology plugin.

These are thin wrappers around the underlying computation modules that
present a clean JSON-serialisable interface for Kerf's tool-call layer.

Tools
-----
train_calculator
    Given a target frequency (Hz) and power-reserve (hours), returns the
    required gear-train ratio, barrel turns to store, and a 3-stage
    integer wheel/pinion factorisation.

check_tooth_profile
    Validates the involute tooth profile for a given module, tooth count,
    and pressure angle, returning pass/fail and any failure reasons.
"""

from __future__ import annotations

import math
from typing import Any

from kerf_partsgen.generators.horology.involute import check_involute_profile
from kerf_partsgen.generators.horology.train_calculator import compute_train_ratio


def _train_calculator(
    freq_hz: float,
    power_reserve_hours: float,
    escape_wheel_teeth: int = 15,
    barrel_turns_per_day: float = 7.5,
) -> dict[str, Any]:
    """Compute gear-train ratio for a mechanical watch movement.

    Parameters
    ----------
    freq_hz:
        Balance-wheel frequency in Hz (e.g. 3.0 for 21 600 bph).
    power_reserve_hours:
        Required power reserve in hours (e.g. 48 for two-day reserve).
    escape_wheel_teeth:
        Escape-wheel tooth count (default 15, Swiss lever standard).
    barrel_turns_per_day:
        Mainspring barrel turns per 24-hour day (default 7.5, ETA 2824).

    Returns
    -------
    dict with keys:
        required_ratio (float): total gear ratio barrel → escape wheel
        barrel_turns_stored (float): turns stored for the power reserve
        stages (list): [{wheel_teeth, pinion_leaves, ratio}, ...]
        achieved_ratio (float): product of stage ratios
        ratio_error_pct (float): deviation from required ratio (%)
    """
    spec = compute_train_ratio(
        freq_hz=freq_hz,
        power_reserve_hours=power_reserve_hours,
        escape_wheel_teeth=escape_wheel_teeth,
        barrel_turns_per_day=barrel_turns_per_day,
    )
    return {
        "freq_hz": spec.freq_hz,
        "power_reserve_hours": spec.power_reserve_hours,
        "escape_wheel_teeth": spec.escape_wheel_teeth,
        "barrel_turns_per_day": spec.barrel_turns_per_day,
        "required_ratio": round(spec.required_ratio, 4),
        "barrel_turns_stored": round(spec.barrel_turns_stored, 3),
        "stages": [
            {
                "wheel_teeth": s.wheel_teeth,
                "pinion_leaves": s.pinion_leaves,
                "ratio": round(s.ratio, 6),
            }
            for s in spec.stages
        ],
        "achieved_ratio": round(spec.achieved_ratio, 4),
        "ratio_error_pct": round(spec.ratio_error_pct, 4),
    }


def _check_tooth_profile(
    module: float,
    num_teeth: int,
    pressure_angle_deg: float = 20.0,
) -> dict[str, Any]:
    """Validate an involute tooth profile.

    Parameters
    ----------
    module:
        Tooth module in mm (pitch_diameter / num_teeth).
    num_teeth:
        Number of teeth on the gear.
    pressure_angle_deg:
        Pressure angle in degrees (20.0 standard for Swiss watches).

    Returns
    -------
    dict with keys:
        passed (bool): True if all geometry criteria pass
        reasons (list[str]): failure reasons (empty when passed)
        r_base (float): base-circle radius (mm)
        r_pitch (float): pitch radius (mm)
        r_tip (float): tip-circle radius (mm)
    """
    result = check_involute_profile(module, num_teeth, pressure_angle_deg)
    return {
        "passed": result.passed,
        "reasons": result.reasons,
        "r_base_mm": round(result.r_base, 6),
        "r_pitch_mm": round(result.r_pitch, 6),
        "r_tip_mm": round(result.r_tip, 6),
        "n_profile_points": result.n_points,
    }


# Registry-style tool definitions
TOOLS = [
    {
        "name": "train_calculator",
        "description": (
            "Compute the required gear-train ratio and barrel power storage "
            "for a mechanical watch movement given target frequency and "
            "power reserve."
        ),
        "fn": _train_calculator,
    },
    {
        "name": "check_tooth_profile",
        "description": (
            "Validate involute tooth profile geometry for a given module, "
            "tooth count, and pressure angle."
        ),
        "fn": _check_tooth_profile,
    },
]
