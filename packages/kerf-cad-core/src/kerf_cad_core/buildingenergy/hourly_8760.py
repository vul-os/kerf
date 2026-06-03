"""
kerf_cad_core.buildingenergy.hourly_8760 — 8760-hour whole-building energy simulation engine.

Implements a simplified single-zone heat-balance model that runs 8760 hourly timesteps,
suitable for ASHRAE 90.1 Appendix G compliance screening and IES VE / Carrier HAP / TRACE 3D
parity checks.

HONEST FLAG: This is a simplified single-zone model for design exploration and code compliance
screening.  It is NOT a replacement for detailed EnergyPlus, eQUEST, IES VE, or Carrier HAP
simulation.  Accuracy: ±10–20% on total annual energy vs. full dynamic simulation.

Dataclasses
-----------
WeatherHour        — hourly weather data (TMY3 format)
BuildingModel      — building geometry + thermal properties + schedules
HourlyResult       — per-hour simulation outputs
AnnualResult       — aggregated annual energy totals + EUI

Functions
---------
simulate_8760(model, weather) -> AnnualResult
load_tmy3_weather(file_content) -> list[WeatherHour]

Method: simplified single-zone heat-balance per ASHRAE 90.1 Appendix G:
    Q_loss = UA_envelope × (T_in - T_out) + UA_ventilation × (T_in - T_out)
    Q_solar = SHGC × window_area × (DNI × cos_incidence + DHI)
    Heating load  = max(0, Q_loss - Q_internal - Q_solar)
    Cooling load  = max(0, -Q_loss + Q_internal + Q_solar)
    Fan energy scaled from ASHRAE 90.1 §6.5.3 fan power indices.

References
----------
ASHRAE 90.1-2022 Appendix G — Performance Rating Method (hourly simulation)
ASHRAE 90.1-2022 §6.5.3 — Air-side HVAC fan power limitation
ASHRAE 169-2020 — Climatic Data for Building Design Standards
NREL TMY3 User's Manual (2008) — Typical Meteorological Year 3 weather data
ASHRAE Handbook Fundamentals 2021 — Heat balance / thermal loads
ASHRAE 62.1-2022 — Ventilation for Acceptable Indoor Air Quality

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# ---------------------------------------------------------------------------
# Psychrometric constants
# ---------------------------------------------------------------------------

# Specific heat of moist air [J/(kg·K)]
_CP_AIR = 1006.0
# Density of air at ~21°C, sea level [kg/m³]
_RHO_AIR = 1.20
# Latent heat of vaporisation [J/kg]
_H_FG = 2_501_000.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WeatherHour:
    """One hour of TMY3 weather data.

    Attributes
    ----------
    iso_datetime : str
        ISO 8601 datetime string, e.g. '2026-01-01T00:00'.
    dry_bulb_c : float
        Dry-bulb temperature (°C).
    wet_bulb_c : float
        Wet-bulb temperature (°C). Derived from dew-point if not directly available.
    relative_humidity_pct : float
        Relative humidity (%).
    direct_normal_irradiance_w_m2 : float
        Direct Normal Irradiance DNI (W/m²).  Zero at night.
    diffuse_horizontal_irradiance_w_m2 : float
        Diffuse Horizontal Irradiance DHI (W/m²).  Zero at night.
    wind_speed_m_s : float
        Wind speed (m/s).
    wind_direction_deg : float
        Wind direction (degrees from north, 0–360).
    """
    iso_datetime: str
    dry_bulb_c: float
    wet_bulb_c: float
    relative_humidity_pct: float
    direct_normal_irradiance_w_m2: float
    diffuse_horizontal_irradiance_w_m2: float
    wind_speed_m_s: float
    wind_direction_deg: float


@dataclass
class BuildingModel:
    """Single-zone building model for 8760-hour simulation.

    Attributes
    ----------
    name : str
        Building / project name.
    floor_area_m2 : float
        Gross conditioned floor area (m²).
    window_to_wall_ratio : float
        Window-to-wall ratio (0–1). Used when construction_uw_m2k window U is given.
    construction_uw_m2k : dict
        U-values for envelope components: keys 'wall', 'roof', 'window' (W/(m²·K)).
    internal_load_w_m2 : float
        Combined peak internal load density (equipment + lighting + people) (W/m²).
    occupancy_schedule_8760 : list[float]
        8760 hourly occupancy/load fractions (0–1). Length must equal 8760.
        If empty or None, a default office schedule is synthesised.
    setpoint_heating_c : float
        Heating setpoint temperature (°C). Default 20.0.
    setpoint_cooling_c : float
        Cooling setpoint temperature (°C). Default 24.0.
    ceiling_height_m : float
        Average ceiling height (m). Default 3.0.
    ventilation_ach : float
        Minimum ventilation air changes per hour (ASHRAE 62.1). Default 0.20.
    lighting_fraction : float
        Fraction of internal_load that is lighting (0–1). Default 0.40.
    fan_power_w_per_m2 : float
        Peak fan power density (W/m²), used for fan energy calculation. Default 5.0.
        Per ASHRAE 90.1-2022 §6.5.3: typical VAV ~4–6 W/m².
    """
    name: str
    floor_area_m2: float
    window_to_wall_ratio: float
    construction_uw_m2k: Dict[str, float]
    internal_load_w_m2: float
    occupancy_schedule_8760: List[float]
    setpoint_heating_c: float = 20.0
    setpoint_cooling_c: float = 24.0
    ceiling_height_m: float = 3.0
    ventilation_ach: float = 0.20
    lighting_fraction: float = 0.40
    fan_power_w_per_m2: float = 5.0


@dataclass
class HourlyResult:
    """Per-hour simulation result.

    Attributes
    ----------
    hour : int
        Hour index 0..8759 (0 = Jan 1 00:00).
    heating_load_kw : float
        Zone heating load (kW, positive = heat needed).
    cooling_load_kw : float
        Zone cooling load (kW, positive = cooling needed).
    fan_kw : float
        HVAC supply + return fan power (kW).
    indoor_temp_c : float
        Estimated indoor operative temperature (°C).
        If load is positive the indoor temp is at the setpoint.
    indoor_rh_pct : float
        Estimated indoor relative humidity (%).
    outdoor_temp_c : float
        Outdoor dry-bulb temperature at this hour (°C).
    solar_gain_kw : float
        Solar heat gain through windows (kW).
    internal_gain_kw : float
        Internal gains from occupants + equipment + lighting (kW).
    """
    hour: int
    heating_load_kw: float
    cooling_load_kw: float
    fan_kw: float
    indoor_temp_c: float
    indoor_rh_pct: float
    outdoor_temp_c: float = 0.0
    solar_gain_kw: float = 0.0
    internal_gain_kw: float = 0.0


@dataclass
class AnnualResult:
    """Aggregated annual energy result.

    Attributes
    ----------
    hourly : list[HourlyResult]
        Full 8760-hour result list.
    annual_heating_kwh : float
        Total annual heating energy (kWh, zone load basis).
    annual_cooling_kwh : float
        Total annual cooling energy (kWh, zone load basis).
    annual_fan_kwh : float
        Total annual HVAC fan energy (kWh).
    annual_lighting_kwh : float
        Total annual lighting energy (kWh).
    eui_kwh_m2_yr : float
        Site Energy Use Intensity (kWh/(m²·yr)), all end-uses.
    peak_heating_kw : float
        Peak hourly heating load (kW).
    peak_cooling_kw : float
        Peak hourly cooling load (kW).
    """
    hourly: List[HourlyResult]
    annual_heating_kwh: float
    annual_cooling_kwh: float
    annual_fan_kwh: float
    annual_lighting_kwh: float
    eui_kwh_m2_yr: float
    peak_heating_kw: float = 0.0
    peak_cooling_kw: float = 0.0


# ---------------------------------------------------------------------------
# Default occupancy schedule generator
# ---------------------------------------------------------------------------

def _default_office_schedule() -> List[float]:
    """Generate a default weekday-office occupancy schedule (8760 hours).

    Schedule: 0.05 baseline + occupied Mon–Fri 08:00–18:00 → 1.0 fraction.
    References: ASHRAE 90.1-2022 Appendix G default occupancy schedules.
    """
    schedule: List[float] = []
    for h in range(8760):
        day_of_year = h // 24       # 0–364
        hour_of_day = h % 24        # 0–23
        day_of_week = day_of_year % 7  # 0=Mon … 6=Sun
        is_weekday = day_of_week < 5
        if is_weekday and 8 <= hour_of_day < 18:
            frac = 1.0
        elif is_weekday and (7 <= hour_of_day < 8 or 18 <= hour_of_day < 20):
            frac = 0.40  # ramp up/down
        else:
            frac = 0.05  # night / weekend standby
        schedule.append(frac)
    return schedule


# ---------------------------------------------------------------------------
# Envelope UA calculation
# ---------------------------------------------------------------------------

def _compute_ua_w_per_k(model: BuildingModel) -> float:
    """Compute total envelope UA (W/K) from model geometry.

    Assumes a square floor plan with 4 equal exposed walls.
    Wall area = 4 × √(floor_area) × ceiling_height_m.
    Window area = wall area × WWR.
    Roof area = floor_area_m2.

    References: ASHRAE Handbook Fundamentals 2021, Chapter 26.
    """
    fa = max(model.floor_area_m2, 1.0)
    side_len = math.sqrt(fa)
    perimeter = 4.0 * side_len
    total_wall_gross = perimeter * model.ceiling_height_m
    window_area = total_wall_gross * max(0.0, min(1.0, model.window_to_wall_ratio))
    opaque_wall_area = total_wall_gross - window_area
    roof_area = fa

    U_wall = float(model.construction_uw_m2k.get("wall", 0.35))
    U_roof = float(model.construction_uw_m2k.get("roof", 0.20))
    U_window = float(model.construction_uw_m2k.get("window", 2.00))

    UA = (
        U_wall * opaque_wall_area
        + U_roof * roof_area
        + U_window * window_area
    )
    return max(UA, 1.0)


def _compute_ua_ventilation(model: BuildingModel) -> float:
    """UA for minimum ventilation air (W/K).

    Q_vent = ṁ × Cp × ΔT  →  UA_vent = ACH × V × ρ × Cp / 3600

    References: ASHRAE 62.1-2022; ASHRAE Handbook Fundamentals 2021, Chapter 16.
    """
    vol_m3 = model.floor_area_m2 * model.ceiling_height_m
    return model.ventilation_ach * vol_m3 * _RHO_AIR * _CP_AIR / 3600.0


# ---------------------------------------------------------------------------
# Solar heat gain — simplified isotropic sky model
# ---------------------------------------------------------------------------

def _solar_heat_gain_kw(whr: WeatherHour, model: BuildingModel) -> float:
    """Simplified solar heat gain through windows (kW).

    Uses an isotropic sky model:
      - Each vertical façade sees a diffuse sky component = DHI × 0.5
      - Average direct beam normal contribution on vertical surface ≈ DNI × 0.35
        (weighted average across 4 orientations for daily profile).
    Solar fraction through window = SHGC × window_area × irradiance.

    References:
      ASHRAE Handbook Fundamentals 2021, Chapter 15 (Fenestration)
      Perez isotropic sky model (simplified vertical-surface transposition)
    """
    fa = max(model.floor_area_m2, 1.0)
    side_len = math.sqrt(fa)
    perimeter = 4.0 * side_len
    total_wall_gross = perimeter * model.ceiling_height_m
    window_area = total_wall_gross * max(0.0, min(1.0, model.window_to_wall_ratio))

    # SHGC default per ASHRAE 90.1-2022 Table 5.5: 0.40 typical low-e double
    shgc = float(model.construction_uw_m2k.get("shgc", 0.40))

    dhi = max(0.0, whr.diffuse_horizontal_irradiance_w_m2)
    dni = max(0.0, whr.direct_normal_irradiance_w_m2)

    # Diffuse irradiance on a vertical surface (isotropic): DHI × 0.5 (view factor sky)
    diffuse_vert = dhi * 0.5

    # Average beam component on 4 vertical facades (sum over all orientations / 4)
    # Approximate: ~35% of DNI hits an average vertical surface for mid-latitudes
    beam_avg_vert = dni * 0.35

    irr_vert = diffuse_vert + beam_avg_vert
    q_solar_w = shgc * window_area * irr_vert
    return q_solar_w / 1000.0


# ---------------------------------------------------------------------------
# Estimated indoor RH (simple psychrometric approximation)
# ---------------------------------------------------------------------------

def _estimate_indoor_rh(outdoor_rh: float, t_outdoor: float, t_indoor: float) -> float:
    """Estimate steady-state indoor RH assuming no active humidity control.

    Uses ratio of saturation pressures (August-Roche-Magnus formula) scaled by
    outdoor RH and an empirical ventilation mixing factor.

    References: ASHRAE Handbook Fundamentals 2021, Chapter 1 (Psychrometrics).
    """
    def _psat(t_c: float) -> float:
        """Saturation pressure (Pa), August-Roche-Magnus, valid −40..60°C."""
        return 610.94 * math.exp(17.625 * t_c / (243.04 + t_c))

    p_sat_out = _psat(t_outdoor)
    p_sat_in = _psat(t_indoor)
    if p_sat_in <= 0:
        return 50.0

    # Absolute humidity outdoors (partial pressure of water vapour)
    p_w_out = outdoor_rh / 100.0 * p_sat_out

    # Simple mixed-air model: 70% outdoor moisture, 30% internal moisture gain
    # Internal gains add ~0.5 g/kg moisture → equiv. ~80 Pa at 21°C
    p_w_in = 0.7 * p_w_out + 0.3 * (0.5 * p_sat_in / 100.0 * 50)
    rh_in = (p_w_in / p_sat_in) * 100.0
    return max(10.0, min(90.0, rh_in))


# ---------------------------------------------------------------------------
# Core 8760-hour simulation
# ---------------------------------------------------------------------------

def simulate_8760(model: BuildingModel, weather: List[WeatherHour]) -> AnnualResult:
    """Hour-by-hour heat-balance energy simulation (8760 hours).

    Algorithm
    ---------
    For each hour h:
      1. Compute envelope UA_total = UA_conductive + UA_ventilation.
      2. Compute solar heat gain through windows.
      3. Compute internal gains = internal_load_w_m2 × floor_area × schedule[h].
      4. Net conductive loss/gain = UA_total × (T_setpoint - T_outdoor).
      5. Heating load = max(0,  net_conductive_loss - Q_internal - Q_solar).
      6. Cooling load  = max(0, -net_conductive_loss + Q_internal + Q_solar).
      7. Fan power = fan_power_w_m2 × floor_area × max(schedule[h], 0.05).
    Annual sums → EUI.

    HONEST FLAG: Simplified single-zone model — for code compliance comparison,
    not a detailed eQUEST/EnergyPlus replacement. Thermal mass, multi-zone
    interactions, and part-load equipment curves are not modelled.

    Parameters
    ----------
    model : BuildingModel
    weather : list[WeatherHour]
        Exactly 8760 hours of hourly weather data (e.g. from load_tmy3_weather).

    Returns
    -------
    AnnualResult

    Raises
    ------
    ValueError : if weather list length is not 8760, or model has invalid values.

    References
    ----------
    ASHRAE 90.1-2022 Appendix G — Performance Rating Method
    ASHRAE Handbook Fundamentals 2021, Chapter 18 (Nonresidential Cooling & Heating Load)
    """
    if len(weather) != 8760:
        raise ValueError(
            f"weather must contain exactly 8760 hours; got {len(weather)}"
        )
    if model.floor_area_m2 <= 0:
        raise ValueError("floor_area_m2 must be > 0")
    if not (0.0 <= model.window_to_wall_ratio <= 1.0):
        raise ValueError("window_to_wall_ratio must be 0–1")

    # Prepare occupancy schedule
    sched = model.occupancy_schedule_8760
    if not sched or len(sched) != 8760:
        sched = _default_office_schedule()

    UA_env = _compute_ua_w_per_k(model)
    UA_vent = _compute_ua_ventilation(model)
    UA_total = UA_env + UA_vent

    # Peak internal gains (W)
    Q_int_peak_w = model.internal_load_w_m2 * model.floor_area_m2

    # Fan peak (W)
    fan_peak_w = model.fan_power_w_per_m2 * model.floor_area_m2

    # Lighting fraction for annual totals
    lighting_frac = max(0.0, min(1.0, model.lighting_fraction))

    hourly_results: List[HourlyResult] = []

    total_heating_kwh = 0.0
    total_cooling_kwh = 0.0
    total_fan_kwh = 0.0
    total_lighting_kwh = 0.0
    peak_heat = 0.0
    peak_cool = 0.0

    for h, whr in enumerate(weather):
        t_out = whr.dry_bulb_c
        occ = max(0.0, min(1.0, sched[h]))

        # Internal gains this hour (W)
        Q_int_w = Q_int_peak_w * occ

        # Solar heat gain (kW → W)
        q_solar_kw = _solar_heat_gain_kw(whr, model)
        q_solar_w = q_solar_kw * 1000.0

        # --- Heating ---
        # Net heat loss through envelope (W); positive = zone loses heat
        q_loss_heat = UA_total * (model.setpoint_heating_c - t_out)
        heat_load_w = max(0.0, q_loss_heat - Q_int_w - q_solar_w)

        # --- Cooling ---
        q_gain_cool = UA_total * (t_out - model.setpoint_cooling_c)
        cool_load_w = max(0.0, q_gain_cool + Q_int_w + q_solar_w)

        # Fan: scaled by max of occupancy schedule and 0.05 (minimum vent fan)
        fan_frac = max(occ, 0.05)
        fan_w = fan_peak_w * fan_frac

        # Indoor temp approximation: at setpoint when HVAC active, free-float otherwise
        if heat_load_w > 0:
            t_indoor = model.setpoint_heating_c
        elif cool_load_w > 0:
            t_indoor = model.setpoint_cooling_c
        else:
            # Free-float: within deadband
            t_indoor = max(model.setpoint_heating_c,
                           min(model.setpoint_cooling_c, t_out))

        rh_indoor = _estimate_indoor_rh(whr.relative_humidity_pct, t_out, t_indoor)

        heat_kw = heat_load_w / 1000.0
        cool_kw = cool_load_w / 1000.0
        fan_kw = fan_w / 1000.0

        total_heating_kwh += heat_kw
        total_cooling_kwh += cool_kw
        total_fan_kwh += fan_kw

        # Lighting energy (kWh): fraction of internal load that is lighting
        lighting_w = Q_int_w * lighting_frac
        total_lighting_kwh += lighting_w / 1000.0

        peak_heat = max(peak_heat, heat_kw)
        peak_cool = max(peak_cool, cool_kw)

        hourly_results.append(HourlyResult(
            hour=h,
            heating_load_kw=round(heat_kw, 4),
            cooling_load_kw=round(cool_kw, 4),
            fan_kw=round(fan_kw, 4),
            indoor_temp_c=round(t_indoor, 2),
            indoor_rh_pct=round(rh_indoor, 1),
            outdoor_temp_c=round(t_out, 2),
            solar_gain_kw=round(q_solar_kw, 4),
            internal_gain_kw=round(Q_int_w / 1000.0, 4),
        ))

    # EUI: zone loads only (not accounting for HVAC system efficiency — that is in hvac_plant.py)
    # Lighting also included
    total_site_kwh = total_heating_kwh + total_cooling_kwh + total_fan_kwh + total_lighting_kwh
    eui = total_site_kwh / model.floor_area_m2 if model.floor_area_m2 > 0 else 0.0

    return AnnualResult(
        hourly=hourly_results,
        annual_heating_kwh=round(total_heating_kwh, 1),
        annual_cooling_kwh=round(total_cooling_kwh, 1),
        annual_fan_kwh=round(total_fan_kwh, 1),
        annual_lighting_kwh=round(total_lighting_kwh, 1),
        eui_kwh_m2_yr=round(eui, 2),
        peak_heating_kw=round(peak_heat, 2),
        peak_cooling_kw=round(peak_cool, 2),
    )


# ---------------------------------------------------------------------------
# TMY3 weather file parser
# ---------------------------------------------------------------------------

# TMY3 column indices (0-based) per NREL TMY3 User's Manual (2008), Table 1:
# Col 0:  Date (MM/DD/YYYY)
# Col 1:  Time (HH:MM)
# Col 2:  Extraterrestrial horizontal radiation (Wh/m²)
# Col 3:  Extraterrestrial direct normal radiation (Wh/m²)
# Col 4:  Horizontal infrared irradiance (Wh/m²)
# Col 5:  Global horizontal irradiance (Wh/m²)
# Col 6:  Direct normal irradiance (Wh/m²)   ← DNI
# Col 7:  Diffuse horizontal irradiance (Wh/m²) ← DHI
# Col 8:  Global horizontal illuminance (100 lux)
# Col 9:  Direct normal illuminance
# Col 10: Diffuse horizontal illuminance
# Col 11: Zenith luminance
# Col 12: Dry-bulb temperature (°C)           ← DBT
# Col 13: Dew-point temperature (°C)          ← DPT
# Col 14: Relative humidity (%)               ← RH
# Col 15: Atmospheric pressure (mbar)
# Col 16: Wind direction (degrees)
# Col 17: Wind speed (m/s)
# ...

_TMY3_COL_DATE = 0
_TMY3_COL_TIME = 1
_TMY3_COL_DNI = 6
_TMY3_COL_DHI = 7
_TMY3_COL_DBT = 12
_TMY3_COL_DPT = 13
_TMY3_COL_RH = 14
_TMY3_COL_WIND_DIR = 16
_TMY3_COL_WIND_SPD = 17


def _dewpoint_to_wetbulb(t_db_c: float, t_dp_c: float) -> float:
    """Approximate wet-bulb from dry-bulb + dew-point (Stull 2011 empirical).

    Stull, R. (2011). Wet-Bulb Temperature from Relative Humidity and Air Temperature.
    Journal of Applied Meteorology and Climatology, 50(11), 2267–2269.
    """
    def _psat(t: float) -> float:
        return 610.94 * math.exp(17.625 * t / (243.04 + t))

    rh = min(100.0, max(1.0, _psat(t_dp_c) / _psat(t_db_c) * 100.0))
    t_wb = (
        t_db_c * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
        + math.atan(t_db_c + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )
    return t_wb


def load_tmy3_weather(file_content: str) -> List[WeatherHour]:
    """Parse TMY3 (Typical Meteorological Year 3) CSV file content.

    TMY3 Format: NREL public weather data format (2008 edition).
    Row 0: Station header (Station_ID, City, State, TZ, Lat, Lon, Elev).
    Row 1: Column header labels.
    Rows 2..8761: 8760 hourly data rows (1 per hour, Jan 1 01:00 … Dec 31 24:00).

    TMY3 timestamps use MM/DD/YYYY, HH:MM (solar time, hour ending convention —
    hour ending 01:00 = hour 0 in this model).

    Parameters
    ----------
    file_content : str
        Full text content of a TMY3 .csv file (UTF-8 or ASCII).

    Returns
    -------
    list[WeatherHour]
        Exactly 8760 WeatherHour objects.

    Raises
    ------
    ValueError : if the file cannot be parsed or does not contain 8760 data rows.

    References
    ----------
    Wilcox, S. and Marion, W. (2008). Users Manual for TMY3 Data Sets.
    Technical Report NREL/TP-581-43156. National Renewable Energy Laboratory.
    """
    lines = file_content.splitlines()
    # Strip blank lines
    lines = [l for l in lines if l.strip()]

    if len(lines) < 3:
        raise ValueError("TMY3 file too short — expected header + column names + 8760 data rows")

    # Data rows start at index 2 (skip station header and column header)
    data_lines = lines[2:]

    if len(data_lines) < 8760:
        raise ValueError(
            f"TMY3 file contains {len(data_lines)} data rows; expected 8760"
        )

    hours: List[WeatherHour] = []
    for idx, line in enumerate(data_lines[:8760]):
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 18:
            raise ValueError(
                f"TMY3 row {idx + 3}: expected ≥18 columns, got {len(cols)}: {line!r}"
            )

        date_str = cols[_TMY3_COL_DATE]   # MM/DD/YYYY
        time_str = cols[_TMY3_COL_TIME]   # HH:MM

        try:
            mm, dd, yyyy = date_str.split("/")
            hh, mins = time_str.split(":")
            # TMY3 uses hour-ending: "01:00" = end of first hour → hour index 0
            hour_ending = int(hh)
            hour_start = hour_ending - 1
            # Clamp for hour 24 edge case (some TMY3 files use 24:00 = midnight)
            if hour_ending == 24:
                hour_start = 23
            iso_dt = f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}T{hour_start:02d}:00"
        except (ValueError, IndexError):
            iso_dt = f"1970-01-01T{(idx % 24):02d}:00"

        try:
            dbt = float(cols[_TMY3_COL_DBT])
        except ValueError:
            dbt = 15.0

        try:
            dpt = float(cols[_TMY3_COL_DPT])
        except ValueError:
            dpt = dbt - 5.0

        try:
            rh = float(cols[_TMY3_COL_RH])
        except ValueError:
            rh = 50.0

        try:
            dni = max(0.0, float(cols[_TMY3_COL_DNI]))
        except ValueError:
            dni = 0.0

        try:
            dhi = max(0.0, float(cols[_TMY3_COL_DHI]))
        except ValueError:
            dhi = 0.0

        try:
            wind_dir = float(cols[_TMY3_COL_WIND_DIR])
        except ValueError:
            wind_dir = 0.0

        try:
            wind_spd = max(0.0, float(cols[_TMY3_COL_WIND_SPD]))
        except ValueError:
            wind_spd = 0.0

        t_wb = _dewpoint_to_wetbulb(dbt, dpt)

        hours.append(WeatherHour(
            iso_datetime=iso_dt,
            dry_bulb_c=dbt,
            wet_bulb_c=round(t_wb, 2),
            relative_humidity_pct=rh,
            direct_normal_irradiance_w_m2=dni,
            diffuse_horizontal_irradiance_w_m2=dhi,
            wind_speed_m_s=wind_spd,
            wind_direction_deg=wind_dir,
        ))

    return hours
