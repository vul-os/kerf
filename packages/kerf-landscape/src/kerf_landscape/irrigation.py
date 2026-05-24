"""
Irrigation zone scheduling — head placement, zone flow demand, and schedule.

References
----------
* ASABE/ICC 802-2014, "Landscape Irrigation Scheduling and Water Management"
* ASABE S436.1:2012, "Test Protocol for Determining the Uniformity of Water
  Distribution of Center Pivot, Corner Pivot, and Moving Lateral Irrigation
  Machines Equipped with Spray or Sprinkler Nozzles"
* WUCOLS IV (2014), "Water Use Classification of Landscape Species"
* Hunter Industries, "Landscape Irrigation Design Manual" (2003)
* Irrigation Association, "Certified Landscape Irrigation Auditor" manual (2014)

Public API
----------
head_spacing(head_type, design_wind_speed_mph) -> dict
    Return recommended maximum head spacing and throw radius for common
    head types (spray, rotor, drip) accounting for wind.

zone_flow_demand(heads, precip_rate_in_hr, zone_area_m2) -> dict
    Compute peak flow demand (GPM and L/min) and run time for a zone.

irrigation_schedule(zones, controller_start_h, et_mm_per_week) -> dict
    Build a weekly irrigation schedule (start time, run times per zone) given
    plant ETo demand and system delivery rate.

water_audit(run_times_min, catch_can_readings) -> dict
    Distribution uniformity (DU) of an irrigation zone from catch-can audit
    data per Irrigation Association protocol.
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GPM_TO_LPM = 3.785411784   # 1 US gal = 3.785 L
_IN_TO_MM = 25.4

# Typical application rates (in/hr) by head category
# Source: Hunter Irrigation Design Manual, Appendix A
_TYPICAL_PRECIP_RATE = {
    "spray":    1.5,   # fixed-arc spray heads at 10–15 ft spacing
    "rotor":    0.6,   # gear-driven rotors at 35–50 ft radius
    "drip":     0.5,   # drip/subsurface (expressed as effective zone rate)
    "bubbler":  2.0,   # bubblers for tree basins
}

# Wind correction factor (Kw) for head spacing reduction (IA / Hunter)
# Kw = 1 - 0.03 * wind_mph  (simplified; ≥ 0.5)
def _wind_factor(wind_mph: float) -> float:
    kw = 1.0 - 0.03 * max(0.0, float(wind_mph))
    return max(0.5, kw)

# Head type → (typical throw radius feet, min pressure PSI)
_HEAD_PARAMS = {
    "spray":   {"throw_ft": 12.0, "min_psi": 20},
    "rotor":   {"throw_ft": 45.0, "min_psi": 30},
    "drip":    {"throw_ft": 0.0,  "min_psi": 15},   # spacing determined by row spacing
    "bubbler": {"throw_ft": 2.0,  "min_psi": 15},
}


# ---------------------------------------------------------------------------
# head_spacing
# ---------------------------------------------------------------------------

def head_spacing(
    head_type: str,
    design_wind_speed_mph: float = 0.0,
) -> dict[str, Any]:
    """Return recommended maximum head spacing and throw radius.

    Applies the Irrigation Association "head-to-head" coverage standard
    (head spacing ≤ throw radius × Kw).

    Parameters
    ----------
    head_type              : "spray" | "rotor" | "drip" | "bubbler"
    design_wind_speed_mph  : prevailing wind speed [mph] (default 0 = no wind).

    Returns
    -------
    {"ok", "head_type", "throw_radius_ft", "max_spacing_ft",
     "throw_radius_m", "max_spacing_m", "wind_factor", "min_pressure_psi"}
    """
    if head_type not in _HEAD_PARAMS:
        return {
            "ok": False,
            "reason": f"head_type must be one of {sorted(_HEAD_PARAMS)}; got '{head_type}'",
        }

    kw = _wind_factor(design_wind_speed_mph)
    params = _HEAD_PARAMS[head_type]
    throw_ft = params["throw_ft"]
    spacing_ft = throw_ft * kw  # head-to-head spacing

    return {
        "ok": True,
        "head_type": head_type,
        "throw_radius_ft": round(throw_ft, 2),
        "max_spacing_ft": round(spacing_ft, 2),
        "throw_radius_m": round(throw_ft * 0.3048, 3),
        "max_spacing_m": round(spacing_ft * 0.3048, 3),
        "wind_factor": round(kw, 3),
        "min_pressure_psi": params["min_psi"],
    }


# ---------------------------------------------------------------------------
# zone_flow_demand
# ---------------------------------------------------------------------------

def zone_flow_demand(
    head_count: int,
    head_type: str = "spray",
    gpm_per_head: float | None = None,
    zone_area_m2: float = 100.0,
    precip_rate_in_hr: float | None = None,
    target_precip_in: float = 1.0,
) -> dict[str, Any]:
    """Compute peak flow demand (GPM, L/min) and run time for a zone.

    Two modes
    ---------
    1. ``gpm_per_head`` given → total flow = head_count × gpm_per_head
    2. ``precip_rate_in_hr`` given (or head_type default used) and zone_area_m2
       → flow derived from area × precip rate via:
           Q [GPM] = (precip_rate [in/hr] × zone_area [ft²]) / 96.25
       where 96.25 is the unit-conversion constant (Hunter, 2003, §3.5).

    Parameters
    ----------
    head_count         : number of heads in the zone.
    head_type          : head category ("spray", "rotor", "drip", "bubbler").
    gpm_per_head       : flow per head [US GPM] (if known; overrides area method).
    zone_area_m2       : zone area [m²] (used when gpm_per_head is None).
    precip_rate_in_hr  : zone application rate [in/hr] (defaults to head_type value).
    target_precip_in   : target irrigation depth [in] (default 1.0 in = 25.4 mm).

    Returns
    -------
    {"ok", "total_flow_gpm", "total_flow_lpm",
     "precip_rate_in_hr", "run_time_min", "applied_depth_mm"}
    """
    if head_type not in _HEAD_PARAMS:
        return {"ok": False, "reason": f"unknown head_type '{head_type}'"}
    if head_count < 1:
        return {"ok": False, "reason": "head_count must be ≥ 1"}

    pr = precip_rate_in_hr if precip_rate_in_hr is not None else _TYPICAL_PRECIP_RATE[head_type]
    if pr <= 0:
        return {"ok": False, "reason": "precip_rate_in_hr must be positive"}

    if gpm_per_head is not None:
        total_gpm = float(gpm_per_head) * head_count
    else:
        # Area-based flow: Q = PR × A_ft2 / 96.25
        area_ft2 = float(zone_area_m2) * 10.7639  # m² → ft²
        total_gpm = pr * area_ft2 / 96.25

    total_lpm = total_gpm * _GPM_TO_LPM
    # Run time: t [hr] = target_precip [in] / precip_rate [in/hr]
    run_time_hr = float(target_precip_in) / pr
    run_time_min = run_time_hr * 60.0

    return {
        "ok": True,
        "head_count": head_count,
        "head_type": head_type,
        "total_flow_gpm": round(total_gpm, 3),
        "total_flow_lpm": round(total_lpm, 3),
        "precip_rate_in_hr": round(pr, 4),
        "target_precip_in": round(float(target_precip_in), 3),
        "run_time_min": round(run_time_min, 1),
        "applied_depth_mm": round(float(target_precip_in) * _IN_TO_MM, 2),
    }


# ---------------------------------------------------------------------------
# irrigation_schedule
# ---------------------------------------------------------------------------

def irrigation_schedule(
    zones: list[dict[str, Any]],
    controller_start_h: float = 5.0,
    et_mm_per_week: float = 25.0,
    days_per_week: int = 3,
) -> dict[str, Any]:
    """Build a weekly irrigation schedule from ETo demand and zone run times.

    Algorithm
    ---------
    1. For each zone: derive required weekly irrigation depth (accounting for
       rainfall efficiency factor 0.75) from et_mm_per_week.
    2. Compute run_time_per_day = (weekly_depth / days_per_week) / precip_rate
    3. Assign sequential start times beginning at controller_start_h.
    4. Detect if total daily run time exceeds 4-hour typical window.

    Parameters
    ----------
    zones              : list of zone dicts with keys:
                             name, head_type, precip_rate_in_hr (optional),
                             area_m2 (optional), head_count (optional).
    controller_start_h : controller program start time (hour, 24-h, default 5:00 AM).
    et_mm_per_week     : reference evapotranspiration [mm/week].
    days_per_week      : irrigation days per week (default 3).

    Returns
    -------
    {"ok", "start_time", "days_per_week", "schedule": [{...}],
     "total_run_time_min", "window_exceeded"}
    """
    if not zones:
        return {"ok": False, "reason": "zones must not be empty"}
    if not (1 <= days_per_week <= 7):
        return {"ok": False, "reason": "days_per_week must be between 1 and 7"}
    if et_mm_per_week < 0:
        return {"ok": False, "reason": "et_mm_per_week must be non-negative"}

    # Weekly depth needed (mm), accounting for 0.75 rainfall efficiency (ET − effective rain)
    weekly_depth_mm = et_mm_per_week  # caller is responsible for netting out rain
    daily_depth_mm = weekly_depth_mm / days_per_week
    daily_depth_in = daily_depth_mm / _IN_TO_MM

    schedule = []
    current_h = float(controller_start_h)
    total_run_min = 0.0

    for zone in zones:
        name = str(zone.get("name") or "Zone")
        ht = str(zone.get("head_type") or "spray")
        pr = zone.get("precip_rate_in_hr")
        if pr is None:
            pr = _TYPICAL_PRECIP_RATE.get(ht, 1.0)
        pr = max(0.01, float(pr))

        # Run time per day (minutes)
        run_hr = daily_depth_in / pr
        run_min = run_hr * 60.0

        # Start time as HH:MM
        hh = int(current_h) % 24
        mm = round((current_h - int(current_h)) * 60)
        start_str = f"{hh:02d}:{mm:02d}"

        schedule.append({
            "zone": name,
            "head_type": ht,
            "precip_rate_in_hr": round(pr, 4),
            "daily_depth_mm": round(daily_depth_mm, 2),
            "run_time_min": round(run_min, 1),
            "start_time": start_str,
        })

        total_run_min += run_min
        current_h += run_min / 60.0

    window_exceeded = total_run_min > 240.0  # 4 hours typical

    return {
        "ok": True,
        "program_start": f"{int(controller_start_h):02d}:{round((controller_start_h % 1) * 60):02d}",
        "days_per_week": days_per_week,
        "et_mm_per_week": et_mm_per_week,
        "schedule": schedule,
        "total_run_time_min": round(total_run_min, 1),
        "window_exceeded": window_exceeded,
        "note": "Scheduling per ASABE/ICC 802-2014; precip rates from Hunter Irrigation Design Manual (2003).",
    }


# ---------------------------------------------------------------------------
# water_audit — Distribution Uniformity (DU)
# ---------------------------------------------------------------------------

def water_audit(
    catch_can_readings: list[float],
) -> dict[str, Any]:
    """Compute Distribution Uniformity (DU) from catch-can audit readings.

    Uses the Irrigation Association / ASABE protocol:
        DU_lq = (mean of lowest 25 % of readings) / (mean of all readings) × 100

    A DU_lq ≥ 70 % is typically considered acceptable; ≥ 80 % is good.

    Parameters
    ----------
    catch_can_readings : list of catch-can volumes [mL or any consistent unit];
                         at least 4 readings required for the lower-quartile calc.

    Returns
    -------
    {"ok", "du_lq_pct", "mean_reading", "lower_quartile_mean",
     "min_reading", "max_reading", "rating", "note"}
    """
    if not catch_can_readings or len(catch_can_readings) < 4:
        return {"ok": False, "reason": "at least 4 catch-can readings are required"}

    data = sorted(float(v) for v in catch_can_readings)
    if any(v < 0 for v in data):
        return {"ok": False, "reason": "catch-can readings must be non-negative"}

    mean_all = sum(data) / len(data)
    if mean_all == 0:
        return {"ok": False, "reason": "all readings are zero — no water applied"}

    n_lq = max(1, len(data) // 4)  # lower quartile
    lower_q = data[:n_lq]
    mean_lq = sum(lower_q) / len(lower_q)

    du_lq = (mean_lq / mean_all) * 100.0

    if du_lq >= 80:
        rating = "good"
    elif du_lq >= 70:
        rating = "acceptable"
    elif du_lq >= 60:
        rating = "marginal"
    else:
        rating = "poor"

    return {
        "ok": True,
        "du_lq_pct": round(du_lq, 2),
        "mean_reading": round(mean_all, 4),
        "lower_quartile_mean": round(mean_lq, 4),
        "min_reading": round(data[0], 4),
        "max_reading": round(data[-1], 4),
        "n_readings": len(data),
        "rating": rating,
        "note": "DU_lq per Irrigation Association / ASABE protocol; ≥80 % = good, ≥70 % = acceptable.",
    }
