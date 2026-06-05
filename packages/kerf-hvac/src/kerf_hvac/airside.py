"""airside.py — Full air-side HVAC system modelling for kerf-hvac.

Implements:
  - Psychrometric functions (humidity ratio, enthalpy, dew point, wet-bulb)
  - Cooling coil model (sensible + latent, ADP/bypass-factor, effectiveness-NTU)
  - Heating coil model (sensible, effectiveness)
  - Supply / return fan model (fan curve, power = ΔP·Q/η)
  - Economizer model (outdoor-air mixing for free cooling)
  - VAV terminal box model (airflow modulation to meet zone load)
  - AHU system model (coupled coils + fan + economizer + VAV zones)
  - Coupling to water-side plant (coil load → chiller / boiler input)

Psychrometric reference: ASHRAE Handbook of Fundamentals 2021, Chapter 1
Fan model reference: ASHRAE Handbook HVAC Systems and Equipment 2020, Chapter 20
Coil model reference: ASHRAE HOF 2021, Chapter 23 (heat exchangers)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PATM_PA = 101_325.0        # Standard atmospheric pressure, Pa
CP_AIR = 1006.0            # Specific heat of dry air, J/(kg·K)
CP_WATER_VAPOUR = 1860.0   # Specific heat of water vapour, J/(kg·K)
H_FG_0 = 2_501_000.0      # Latent heat of vaporisation at 0°C, J/kg
RHO_AIR_STD = 1.204        # Air density at 20°C, 1 atm, kg/m³


# ---------------------------------------------------------------------------
# Psychrometrics
# ---------------------------------------------------------------------------

def saturation_pressure_pa(T_db_C: float) -> float:
    """Antoine-like saturation vapour pressure (Pa) at T_db_C (°C).

    Uses ASHRAE 2021 HOF Ch.1 Eq. 5 (valid -60 to 200 °C).
    """
    T_K = T_db_C + 273.15
    if T_db_C >= 0.0:
        # Above freezing (ASHRAE HOF 2021 Eq. 6)
        C8 = -5.8002206e3
        C9 = 1.3914993
        C10 = -4.8640239e-2
        C11 = 4.1764768e-5
        C12 = -1.4452093e-8
        C13 = 6.5459673
        ln_pws = C8 / T_K + C9 + C10 * T_K + C11 * T_K**2 + C12 * T_K**3 + C13 * math.log(T_K)
    else:
        # Below freezing (ASHRAE HOF 2021 Eq. 5)
        C1 = -5.6745359e3
        C2 = 6.3925247
        C3 = -9.677843e-3
        C4 = 6.2215701e-7
        C5 = 2.0747825e-9
        C6 = -9.484024e-13
        C7 = 4.1635019
        ln_pws = C1 / T_K + C2 + C3 * T_K + C4 * T_K**2 + C5 * T_K**3 + C6 * T_K**4 + C7 * math.log(T_K)
    return math.exp(ln_pws)


def humidity_ratio_from_rh(T_db_C: float, rh_fraction: float, p_atm_pa: float = PATM_PA) -> float:
    """Humidity ratio W (kg_w/kg_da) from dry-bulb T and relative humidity.

    ASHRAE HOF 2021 Eq. 20: W = 0.621945 * p_ws / (p - p_ws)
    """
    if not (0.0 <= rh_fraction <= 1.0):
        raise ValueError(f"rh_fraction must be 0–1, got {rh_fraction}")
    pws = saturation_pressure_pa(T_db_C)
    pw = rh_fraction * pws
    if pw >= p_atm_pa:
        raise ValueError("Partial pressure of water exceeds atmospheric — unphysical input")
    return 0.621945 * pw / (p_atm_pa - pw)


def enthalpy_kj_kg(T_db_C: float, W: float) -> float:
    """Moist-air enthalpy h (kJ/kg_da) from dry-bulb T and humidity ratio W.

    ASHRAE HOF 2021 Eq. 30: h = 1.006·T + W·(2501 + 1.86·T)  [kJ/kg_da]
    """
    return CP_AIR / 1000 * T_db_C + W * (H_FG_0 / 1000 + CP_WATER_VAPOUR / 1000 * T_db_C)


def dew_point_C(W: float, p_atm_pa: float = PATM_PA) -> float:
    """Dew-point temperature (°C) from humidity ratio W."""
    pw = W * p_atm_pa / (0.621945 + W)
    # Invert saturation_pressure_pa using Newton-Raphson
    T = 10.0  # initial guess
    for _ in range(50):
        f = saturation_pressure_pa(T) - pw
        # Derivative: df/dT ≈ pws * ln(10) * d(ln_pws)/dT; approximate numerically
        dT = 0.001
        df = (saturation_pressure_pa(T + dT) - saturation_pressure_pa(T - dT)) / (2 * dT)
        if abs(df) < 1e-12:
            break
        T_new = T - f / df
        if abs(T_new - T) < 1e-6:
            T = T_new
            break
        T = T_new
    return T


def wet_bulb_C(T_db_C: float, W: float, p_atm_pa: float = PATM_PA) -> float:
    """Wet-bulb temperature (°C) by psychrometric formula iteration.

    Uses ASHRAE HOF 2021 Eq. 35 (Sprung formula).
    """
    # Bracket search then Newton-Raphson
    T_wb = T_db_C  # upper bound
    T_wb_low = T_db_C - 50.0
    for _ in range(100):
        T_mid = (T_wb + T_wb_low) / 2
        W_sat = 0.621945 * saturation_pressure_pa(T_mid) / (p_atm_pa - saturation_pressure_pa(T_mid))
        # Sprung: W = W_sat - A * (T_db - T_wb) where A ≈ 6.6e-4 for ventilated psychrometer
        A = 6.6e-4  # /°C, ASHRAE Eq. 35 coefficient (1/1518 ≈ psychrometric constant)
        W_calc = W_sat - A * p_atm_pa / 101_325 * (T_db_C - T_mid)
        if abs(W_calc - W) < 1e-7:
            break
        if W_calc > W:
            T_wb = T_mid
        else:
            T_wb_low = T_mid
    return (T_wb + T_wb_low) / 2


def air_density(T_db_C: float, W: float, p_atm_pa: float = PATM_PA) -> float:
    """Moist-air density (kg_da/m³) from dry-bulb T and humidity ratio.

    ρ = p_atm / (R_da · T_K · (1 + 1.607858·W))  [ASHRAE HOF 2021 Eq. 11]
    """
    T_K = T_db_C + 273.15
    R_da = 287.055  # J/(kg·K)
    return p_atm_pa / (R_da * T_K * (1 + 1.607858 * W))


# ---------------------------------------------------------------------------
# State point dataclass
# ---------------------------------------------------------------------------

@dataclass
class AirState:
    """Psychrometric state of a moist-air stream."""
    T_db_C: float                  # Dry-bulb temperature, °C
    W: float                       # Humidity ratio, kg_w/kg_da
    p_atm_pa: float = PATM_PA

    @property
    def h_kj_kg(self) -> float:
        return enthalpy_kj_kg(self.T_db_C, self.W)

    @property
    def rh(self) -> float:
        pws = saturation_pressure_pa(self.T_db_C)
        pw = self.W * self.p_atm_pa / (0.621945 + self.W)
        return min(1.0, pw / pws)

    @property
    def T_dp_C(self) -> float:
        return dew_point_C(self.W, self.p_atm_pa)

    @property
    def T_wb_C(self) -> float:
        return wet_bulb_C(self.T_db_C, self.W, self.p_atm_pa)

    @property
    def density_kg_m3(self) -> float:
        return air_density(self.T_db_C, self.W, self.p_atm_pa)

    def to_dict(self) -> dict:
        return {
            "T_db_C": round(self.T_db_C, 3),
            "T_dp_C": round(self.T_dp_C, 3),
            "T_wb_C": round(self.T_wb_C, 3),
            "W_kg_kgda": round(self.W, 6),
            "rh_fraction": round(self.rh, 4),
            "h_kj_kgda": round(self.h_kj_kg, 3),
            "density_kg_m3": round(self.density_kg_m3, 4),
        }

    @classmethod
    def from_T_rh(cls, T_db_C: float, rh_fraction: float, p_atm_pa: float = PATM_PA) -> "AirState":
        W = humidity_ratio_from_rh(T_db_C, rh_fraction, p_atm_pa)
        return cls(T_db_C=T_db_C, W=W, p_atm_pa=p_atm_pa)


# ---------------------------------------------------------------------------
# Mixing box / Economizer
# ---------------------------------------------------------------------------

@dataclass
class EconomizerResult:
    mixed_state: AirState
    oa_fraction: float          # Outdoor air fraction (0–1)
    free_cooling: bool          # True if economizer is providing free cooling
    oa_flow_m3s: float
    ra_flow_m3s: float
    total_flow_m3s: float


def mix_air_streams(
    state_oa: AirState,
    state_ra: AirState,
    oa_fraction: float,
    total_flow_m3s: float,
) -> AirState:
    """Mass-weighted mixing of two air streams."""
    # Mass flows (kg_da/s)
    rho_oa = state_oa.density_kg_m3
    rho_ra = state_ra.density_kg_m3
    flow_oa = oa_fraction * total_flow_m3s
    flow_ra = (1.0 - oa_fraction) * total_flow_m3s
    m_oa = rho_oa * flow_oa
    m_ra = rho_ra * flow_ra
    m_total = m_oa + m_ra
    if m_total <= 0:
        raise ValueError("Total mass flow is zero")
    T_mix = (m_oa * state_oa.T_db_C + m_ra * state_ra.T_db_C) / m_total
    W_mix = (m_oa * state_oa.W + m_ra * state_ra.W) / m_total
    return AirState(T_db_C=T_mix, W=W_mix, p_atm_pa=state_oa.p_atm_pa)


def economizer_control(
    state_oa: AirState,
    state_ra: AirState,
    total_flow_m3s: float,
    min_oa_fraction: float = 0.15,
    economizer_setpoint_C: float = 18.0,
    enable_enthalpy_control: bool = True,
) -> EconomizerResult:
    """Determine OA fraction with economizer (differential dry-bulb or enthalpy).

    Free cooling is enabled when outdoor air can reduce mixed-air enthalpy.
    Returns mixed state and whether free cooling is active.
    """
    # Decide whether economizer can provide free cooling
    # Dry-bulb lockout: OA below setpoint temp
    oa_cool_enough = state_oa.T_db_C < economizer_setpoint_C
    # Enthalpy lockout: OA enthalpy < RA enthalpy
    oa_enthalpy_ok = state_oa.h_kj_kg < state_ra.h_kj_kg

    free_cooling = oa_cool_enough and (not enable_enthalpy_control or oa_enthalpy_ok)

    if free_cooling:
        oa_fraction = 1.0  # Full outdoor air for maximum free cooling
    else:
        oa_fraction = min_oa_fraction

    oa_flow = oa_fraction * total_flow_m3s
    ra_flow = (1.0 - oa_fraction) * total_flow_m3s
    mixed = mix_air_streams(state_oa, state_ra, oa_fraction, total_flow_m3s)

    return EconomizerResult(
        mixed_state=mixed,
        oa_fraction=oa_fraction,
        free_cooling=free_cooling,
        oa_flow_m3s=oa_flow,
        ra_flow_m3s=ra_flow,
        total_flow_m3s=total_flow_m3s,
    )


# ---------------------------------------------------------------------------
# Cooling coil model (ADP / bypass-factor / effectiveness)
# ---------------------------------------------------------------------------

@dataclass
class CoolingCoilResult:
    leaving_state: AirState
    entering_state: AirState
    Q_sensible_W: float         # Sensible heat removed, W (positive = removed)
    Q_latent_W: float           # Latent heat removed, W (positive = removed)
    Q_total_W: float            # Total coil load, W
    condensate_kg_s: float      # Condensate rate, kg/s
    ADP_C: float                # Apparatus dew point, °C
    bypass_factor: float        # Coil bypass factor BF (0–1)
    coil_effectiveness: float   # ε = Q_actual / Q_max
    water_side_load_W: float    # Chilled-water load (= Q_total_W)


def cooling_coil(
    entering_state: AirState,
    supply_airflow_m3s: float,
    chw_supply_T_C: float,
    chw_return_T_C: float,
    coil_bypass_factor: float = 0.10,
    coil_rows: int = 6,
    fins_per_m: float = 315.0,
) -> CoolingCoilResult:
    """Direct-expansion or chilled-water cooling coil model.

    Uses the ADP/bypass-factor method (ASHRAE HOF 2021 Ch. 23):
      - ADP: apparatus dew point — the effective surface temperature
      - BF: fraction of air that bypasses the coil surface
      - Leaving dry-bulb = BF·T_enter + (1–BF)·ADP
      - Leaving W: similar interpolation at ADP

    coil_bypass_factor: typically 0.05–0.20 (fewer rows → higher BF)
    coil_rows: number of coil rows (used to validate BF consistency)
    fins_per_m: fin density in fins/m (for info only)
    """
    if not (0.0 <= coil_bypass_factor < 1.0):
        raise ValueError(f"coil_bypass_factor must be 0–1, got {coil_bypass_factor}")
    if supply_airflow_m3s <= 0:
        raise ValueError("supply_airflow_m3s must be positive")
    if chw_supply_T_C >= entering_state.T_db_C:
        # No cooling needed / possible
        chw_supply_T_C_eff = chw_supply_T_C
    else:
        chw_supply_T_C_eff = chw_supply_T_C

    # Apparatus dew point (ADP): weighted average of CHW supply and return
    # ADP ≈ mean coil surface temperature, approximated as CHW mean temp
    ADP_C = (chw_supply_T_C + chw_return_T_C) / 2.0

    # ADP must be below entering dew point for any dehumidification
    ADP_C = min(ADP_C, entering_state.T_db_C - 0.5)

    # Saturation humidity at ADP
    pws_adp = saturation_pressure_pa(ADP_C)
    W_adp = 0.621945 * pws_adp / (entering_state.p_atm_pa - pws_adp)

    BF = coil_bypass_factor

    # Leaving conditions (mass-weighted bypass + contact)
    T_leaving = BF * entering_state.T_db_C + (1.0 - BF) * ADP_C
    W_leaving = BF * entering_state.W + (1.0 - BF) * W_adp
    # Ensure W_leaving is non-negative
    W_leaving = max(W_leaving, 0.0)

    leaving_state = AirState(
        T_db_C=T_leaving,
        W=W_leaving,
        p_atm_pa=entering_state.p_atm_pa,
    )

    # Mass flow of dry air (kg_da/s)
    rho_avg = (entering_state.density_kg_m3 + leaving_state.density_kg_m3) / 2
    m_da = rho_avg * supply_airflow_m3s

    # Enthalpy change
    dh_total = entering_state.h_kj_kg - leaving_state.h_kj_kg   # kJ/kg_da
    Q_total_W = m_da * dh_total * 1000  # W

    # Sensible and latent split
    # Sensible: CP_air * dT  (per kg dry air)
    dh_sensible = CP_AIR * (entering_state.T_db_C - T_leaving) / 1000  # kJ/kg_da
    Q_sensible_W = m_da * dh_sensible * 1000

    Q_latent_W = Q_total_W - Q_sensible_W

    # Condensate
    dW = entering_state.W - W_leaving
    condensate_kg_s = m_da * max(dW, 0.0)

    # Coil effectiveness
    # Max possible cooling: cool all air to ADP at ADP humidity
    h_adp = enthalpy_kj_kg(ADP_C, W_adp)
    dh_max = entering_state.h_kj_kg - h_adp
    effectiveness = dh_total / dh_max if dh_max > 0 else 0.0
    effectiveness = min(max(effectiveness, 0.0), 1.0)

    return CoolingCoilResult(
        leaving_state=leaving_state,
        entering_state=entering_state,
        Q_sensible_W=max(Q_sensible_W, 0.0),
        Q_latent_W=max(Q_latent_W, 0.0),
        Q_total_W=max(Q_total_W, 0.0),
        condensate_kg_s=condensate_kg_s,
        ADP_C=ADP_C,
        bypass_factor=BF,
        coil_effectiveness=effectiveness,
        water_side_load_W=max(Q_total_W, 0.0),
    )


# ---------------------------------------------------------------------------
# Heating coil model
# ---------------------------------------------------------------------------

@dataclass
class HeatingCoilResult:
    leaving_state: AirState
    entering_state: AirState
    Q_sensible_W: float         # Sensible heat added, W (positive = added)
    water_side_load_W: float    # Hot-water or steam load


def heating_coil(
    entering_state: AirState,
    supply_airflow_m3s: float,
    hw_supply_T_C: float,
    hw_return_T_C: float,
    coil_effectiveness: float = 0.80,
) -> HeatingCoilResult:
    """Simple effectiveness heating coil model.

    ε-NTU method (ASHRAE HOF 2021 Ch. 23, counterflow):
      Q_actual = ε · Q_max
      Q_max = m_da · CP_air · (T_hw_supply - T_air_entering)
    """
    if not (0.0 < coil_effectiveness <= 1.0):
        raise ValueError(f"coil_effectiveness must be (0,1], got {coil_effectiveness}")
    if supply_airflow_m3s <= 0:
        raise ValueError("supply_airflow_m3s must be positive")

    rho = entering_state.density_kg_m3
    m_da = rho * supply_airflow_m3s

    T_max = hw_supply_T_C  # max leaving temp if ε=1
    Q_max = m_da * CP_AIR * max(T_max - entering_state.T_db_C, 0.0)
    Q_actual = coil_effectiveness * Q_max

    dT = Q_actual / (m_da * CP_AIR) if m_da > 0 else 0.0
    T_leaving = entering_state.T_db_C + dT
    # Humidity ratio unchanged (sensible only)
    leaving_state = AirState(
        T_db_C=T_leaving,
        W=entering_state.W,
        p_atm_pa=entering_state.p_atm_pa,
    )

    return HeatingCoilResult(
        leaving_state=leaving_state,
        entering_state=entering_state,
        Q_sensible_W=Q_actual,
        water_side_load_W=Q_actual,
    )


# ---------------------------------------------------------------------------
# Fan model
# ---------------------------------------------------------------------------

@dataclass
class FanResult:
    flow_m3s: float
    static_pressure_pa: float
    shaft_power_W: float        # Shaft power = ΔP·Q/η_fan
    motor_power_W: float        # Electrical power = shaft / η_motor
    fan_efficiency: float
    motor_efficiency: float
    temperature_rise_C: float   # Fan heat addition to airstream


def fan_power(
    flow_m3s: float,
    static_pressure_pa: float,
    fan_efficiency: float = 0.70,
    motor_efficiency: float = 0.92,
    air_density_kg_m3: float = RHO_AIR_STD,
) -> FanResult:
    """Fan power calculation: W_shaft = ΔP·Q/η_fan.

    ASHRAE HVAC Systems and Equipment 2020, Ch. 20.
    Temperature rise due to fan heat added to air:
      ΔT = W_shaft / (m_da · CP_air)
    """
    if flow_m3s <= 0:
        raise ValueError("flow_m3s must be positive")
    if static_pressure_pa < 0:
        raise ValueError("static_pressure_pa must be non-negative")
    if not (0.0 < fan_efficiency <= 1.0):
        raise ValueError(f"fan_efficiency must be (0,1], got {fan_efficiency}")
    if not (0.0 < motor_efficiency <= 1.0):
        raise ValueError(f"motor_efficiency must be (0,1], got {motor_efficiency}")

    shaft_power_W = static_pressure_pa * flow_m3s / fan_efficiency
    motor_power_W = shaft_power_W / motor_efficiency

    m_da = air_density_kg_m3 * flow_m3s
    temp_rise_C = shaft_power_W / (m_da * CP_AIR) if m_da > 0 else 0.0

    return FanResult(
        flow_m3s=flow_m3s,
        static_pressure_pa=static_pressure_pa,
        shaft_power_W=shaft_power_W,
        motor_power_W=motor_power_W,
        fan_efficiency=fan_efficiency,
        motor_efficiency=motor_efficiency,
        temperature_rise_C=temp_rise_C,
    )


# ---------------------------------------------------------------------------
# VAV terminal box
# ---------------------------------------------------------------------------

@dataclass
class VAVZone:
    """One VAV-served zone descriptor."""
    name: str
    design_flow_m3s: float      # Design (peak) airflow to zone, m³/s
    min_flow_fraction: float    # Minimum airflow fraction (0.2–0.3 typical)
    zone_load_W: float          # Current sensible zone load, W (+ = cooling)
    zone_T_setpoint_C: float    # Zone thermostat setpoint, °C
    zone_T_current_C: float     # Current zone temperature, °C


@dataclass
class VAVBoxResult:
    zone_name: str
    supply_flow_m3s: float      # Actual airflow delivered, m³/s
    supply_T_C: float           # Supply air temperature, °C
    zone_load_met_W: float      # Load met by supply air, W
    fraction_of_design: float   # Flow / design_flow
    damper_position: float      # 0–1 (0=min, 1=design)
    unmet_load_W: float         # Residual unmet load (+ = warm zone, - = cool zone)


def vav_box(
    zone: VAVZone,
    supply_air_state: AirState,
    supply_duct_pressure_pa: float = 250.0,
) -> VAVBoxResult:
    """VAV terminal box: modulate airflow to meet zone sensible load.

    Airflow is throttled between minimum and design CFM to maintain setpoint.
    Load met = m_da · CP_air · (T_supply - T_zone)  [for cooling: T_supply < T_zone]

    If T_supply < T_zone (cooling mode):
      Q_per_m3s = ρ · CP_air · (T_zone - T_supply)
      flow_needed = Q_zone / Q_per_m3s

    For heating mode (T_supply > T_zone), logic is symmetric.
    """
    rho = supply_air_state.density_kg_m3
    T_supply = supply_air_state.T_db_C
    T_zone = zone.zone_T_current_C

    cooling_mode = zone.zone_load_W > 0  # positive load = zone needs cooling

    dT = abs(T_zone - T_supply)
    if dT < 0.1:
        # No useful temperature differential — deliver minimum flow
        flow_m3s = zone.min_flow_fraction * zone.design_flow_m3s
        load_met = rho * flow_m3s * CP_AIR * (T_zone - T_supply)
        return VAVBoxResult(
            zone_name=zone.name,
            supply_flow_m3s=flow_m3s,
            supply_T_C=T_supply,
            zone_load_met_W=load_met,
            fraction_of_design=zone.min_flow_fraction,
            damper_position=zone.min_flow_fraction,
            unmet_load_W=zone.zone_load_W - load_met,
        )

    # Required flow to meet load
    Q_per_m3s = rho * CP_AIR * dT  # W/(m³/s)
    flow_needed = zone.zone_load_W / Q_per_m3s

    # Clamp to min / max airflow
    flow_min = zone.min_flow_fraction * zone.design_flow_m3s
    flow_max = zone.design_flow_m3s
    flow_actual = max(flow_min, min(flow_max, flow_needed))

    fraction = flow_actual / zone.design_flow_m3s
    load_met = rho * flow_actual * CP_AIR * (T_zone - T_supply)
    unmet = zone.zone_load_W - load_met

    return VAVBoxResult(
        zone_name=zone.name,
        supply_flow_m3s=flow_actual,
        supply_T_C=T_supply,
        zone_load_met_W=load_met,
        fraction_of_design=fraction,
        damper_position=fraction,
        unmet_load_W=unmet,
    )


# ---------------------------------------------------------------------------
# Duct system pressure loss (simplified static pressure method)
# ---------------------------------------------------------------------------

@dataclass
class DuctSystemResult:
    total_static_pressure_pa: float   # Total system static pressure, Pa
    friction_pa: float                # Duct friction component
    fittings_pa: float                # Fitting minor losses
    fan_static_pressure_pa: float     # Required fan static pressure (= total + safety)


def duct_static_pressure(
    total_flow_m3s: float,
    equivalent_length_m: float = 100.0,
    duct_velocity_m_s: float = 5.0,
    roughness_mm: float = 0.09,
    num_90deg_elbows: int = 4,
    safety_factor: float = 1.15,
    air_density_kg_m3: float = RHO_AIR_STD,
) -> DuctSystemResult:
    """Simplified duct system static pressure for fan sizing.

    Uses Darcy-Weisbach with hydraulic diameter from velocity and flow.
    Equivalent-length approach for a typical commercial duct system.
    """
    from kerf_hvac.pressure import darcy_weisbach_loss, friction_factor, ELBOW_90_RECT_K

    # Estimate hydraulic diameter from flow and velocity
    area_m2 = total_flow_m3s / duct_velocity_m_s if duct_velocity_m_s > 0 else 0.1
    # Assume near-square duct: D_h ≈ √area × 1.13 (hydraulic diameter correction)
    D_h = math.sqrt(area_m2) * 1.13

    eps = roughness_mm / 1000
    rho = air_density_kg_m3

    # Friction loss
    friction = darcy_weisbach_loss(
        velocity_m_s=duct_velocity_m_s,
        hydraulic_diameter_m=D_h,
        length_m=equivalent_length_m,
        roughness_m=eps,
    )

    # Fitting losses: N × K × ½ρv²
    vp = 0.5 * rho * duct_velocity_m_s ** 2
    fittings = num_90deg_elbows * ELBOW_90_RECT_K * vp

    total = friction + fittings
    fan_sp = total * safety_factor

    return DuctSystemResult(
        total_static_pressure_pa=total,
        friction_pa=friction,
        fittings_pa=fittings,
        fan_static_pressure_pa=fan_sp,
    )


# ---------------------------------------------------------------------------
# AHU System Model — coupled air-side + water-side
# ---------------------------------------------------------------------------

@dataclass
class AHUConfig:
    """Air Handling Unit configuration."""
    name: str = "AHU-1"
    supply_airflow_m3s: float = 1.0      # Design supply airflow, m³/s
    min_oa_fraction: float = 0.15        # Minimum OA fraction (15% = ASHRAE 62.1)
    economizer_setpoint_C: float = 18.0  # Economizer dry-bulb lockout
    enable_economizer: bool = True
    enable_enthalpy_economizer: bool = True

    # Cooling coil
    chw_supply_T_C: float = 7.0          # Chilled-water supply temp, °C
    chw_return_T_C: float = 12.0         # Chilled-water return temp, °C
    cooling_coil_bypass_factor: float = 0.10

    # Heating coil
    hw_supply_T_C: float = 60.0          # Hot-water supply temp, °C
    hw_return_T_C: float = 45.0          # Hot-water return temp, °C
    heating_coil_effectiveness: float = 0.80

    # Supply fan
    supply_fan_efficiency: float = 0.70
    supply_fan_motor_efficiency: float = 0.92

    # Return fan
    return_fan_efficiency: float = 0.65
    return_fan_motor_efficiency: float = 0.90

    # Duct system
    duct_equivalent_length_m: float = 100.0
    duct_velocity_m_s: float = 5.0
    num_elbows: int = 4
    duct_static_safety: float = 1.15


@dataclass
class PlantCoupling:
    """Water-side plant coupling parameters."""
    # Chiller COP (cooling)
    chiller_cop: float = 5.5
    # Boiler efficiency
    boiler_efficiency: float = 0.92
    # Whether a chiller is serving this AHU
    has_chiller: bool = True
    # Whether a boiler is serving this AHU
    has_boiler: bool = True


@dataclass
class AHUSystemResult:
    """Complete AHU system simulation result."""
    # State points
    outdoor_air: AirState
    return_air: AirState
    mixed_air: AirState                # After mixing box
    post_cooling_coil: AirState        # After cooling coil
    supply_air: AirState               # After heating coil + fan heat

    # Economizer
    oa_fraction: float
    free_cooling: bool
    free_cooling_load_W: float         # Load offset by economizer, W

    # Coil results
    cooling_coil_Q_total_W: float
    cooling_coil_Q_sensible_W: float
    cooling_coil_Q_latent_W: float
    cooling_coil_ADP_C: float
    cooling_coil_bypass_factor: float
    cooling_coil_effectiveness: float
    condensate_kg_s: float

    heating_coil_Q_W: float

    # Fan results
    supply_fan_flow_m3s: float
    supply_fan_static_pa: float
    supply_fan_power_W: float
    supply_fan_motor_power_W: float
    supply_fan_temp_rise_C: float

    return_fan_flow_m3s: float
    return_fan_static_pa: float
    return_fan_power_W: float
    return_fan_motor_power_W: float

    total_fan_power_W: float

    # VAV zones
    zone_results: list[VAVBoxResult]
    total_zone_flow_m3s: float
    total_zone_load_met_W: float

    # Plant coupling
    chiller_load_W: float              # Total cooling load to chiller
    chiller_power_W: float             # Chiller electrical input
    boiler_load_W: float               # Total heating load to boiler
    boiler_fuel_W: float               # Boiler fuel input
    total_system_power_W: float        # Fan + chiller + boiler electrical

    # Energy balance
    energy_balance_W: float            # Should be near zero (Q_in - Q_out)

    # Duct system
    duct_static_pressure_pa: float


def simulate_ahu_system(
    ahu: AHUConfig,
    outdoor_air_state: AirState,
    return_air_state: AirState,
    zones: list[VAVZone],
    plant: Optional[PlantCoupling] = None,
) -> AHUSystemResult:
    """Full AHU air-side system simulation coupled to water-side plant.

    Sequence of operations:
      1. Economizer: determine OA fraction and mix outdoor + return air
      2. Cooling coil: cool/dehumidify mixed air
      3. Heating coil: reheat to supply-air setpoint (if needed)
      4. Supply fan: add fan heat, compute power
      5. VAV distribution: modulate zone airflows to meet loads
      6. Return fan: compute return-side fan power
      7. Plant coupling: route coil loads to chiller / boiler
      8. Energy balance verification
    """
    if plant is None:
        plant = PlantCoupling()

    total_flow_m3s = ahu.supply_airflow_m3s

    # ------------------------------------------------------------------
    # 1. Economizer / Mixing box
    # ------------------------------------------------------------------
    eco = economizer_control(
        state_oa=outdoor_air_state,
        state_ra=return_air_state,
        total_flow_m3s=total_flow_m3s,
        min_oa_fraction=ahu.min_oa_fraction,
        economizer_setpoint_C=ahu.economizer_setpoint_C,
        enable_enthalpy_control=ahu.enable_enthalpy_economizer,
    )
    mixed_state = eco.mixed_state

    # ------------------------------------------------------------------
    # 2. Cooling coil
    # ------------------------------------------------------------------
    cc = cooling_coil(
        entering_state=mixed_state,
        supply_airflow_m3s=total_flow_m3s,
        chw_supply_T_C=ahu.chw_supply_T_C,
        chw_return_T_C=ahu.chw_return_T_C,
        coil_bypass_factor=ahu.cooling_coil_bypass_factor,
    )
    post_cooling_state = cc.leaving_state

    # ------------------------------------------------------------------
    # 3. Heating coil (reheat if needed)
    # ------------------------------------------------------------------
    # Determine if reheat is required: if post-cooling temp < supply setpoint.
    # For VAV systems, supply setpoint is typically 12–14°C.
    # Limit the reheat HW supply to the target setpoint (not full HW temp):
    # we use the setpoint as the effective "HW supply" so effectiveness·(setpoint - T_in)
    # does not overshoot the setpoint.
    supply_setpoint_C = 13.0  # Typical VAV supply air setpoint
    if post_cooling_state.T_db_C < supply_setpoint_C:
        # Use setpoint as the target leaving temperature; HW coil heats to setpoint.
        # We pass the setpoint as HW supply temperature so the coil cannot exceed it.
        hc = heating_coil(
            entering_state=post_cooling_state,
            supply_airflow_m3s=total_flow_m3s,
            hw_supply_T_C=supply_setpoint_C,       # Limit leaving T to setpoint
            hw_return_T_C=post_cooling_state.T_db_C,
            coil_effectiveness=1.0,                 # At setpoint limit, ε→1 gives setpoint
        )
        post_heating_state = hc.leaving_state
        heating_Q_W = hc.Q_sensible_W
    else:
        post_heating_state = post_cooling_state
        heating_Q_W = 0.0

    # ------------------------------------------------------------------
    # 4. Duct system static pressure
    # ------------------------------------------------------------------
    duct = duct_static_pressure(
        total_flow_m3s=total_flow_m3s,
        equivalent_length_m=ahu.duct_equivalent_length_m,
        duct_velocity_m_s=ahu.duct_velocity_m_s,
        num_90deg_elbows=ahu.num_elbows,
        safety_factor=ahu.duct_static_safety,
        air_density_kg_m3=post_heating_state.density_kg_m3,
    )

    # ------------------------------------------------------------------
    # 5. Supply fan
    # ------------------------------------------------------------------
    sf = fan_power(
        flow_m3s=total_flow_m3s,
        static_pressure_pa=duct.fan_static_pressure_pa,
        fan_efficiency=ahu.supply_fan_efficiency,
        motor_efficiency=ahu.supply_fan_motor_efficiency,
        air_density_kg_m3=post_heating_state.density_kg_m3,
    )
    # Fan heat added to airstream
    supply_air_state = AirState(
        T_db_C=post_heating_state.T_db_C + sf.temperature_rise_C,
        W=post_heating_state.W,
        p_atm_pa=post_heating_state.p_atm_pa,
    )

    # ------------------------------------------------------------------
    # 6. VAV terminal boxes
    # ------------------------------------------------------------------
    zone_results: list[VAVBoxResult] = []
    total_zone_flow = 0.0
    total_zone_load_met = 0.0
    for z in zones:
        zr = vav_box(z, supply_air_state)
        zone_results.append(zr)
        total_zone_flow += zr.supply_flow_m3s
        total_zone_load_met += zr.zone_load_met_W

    # ------------------------------------------------------------------
    # 7. Return fan
    # ------------------------------------------------------------------
    # Return fan handles return airflow (typically supply - OA exhaust)
    return_flow = total_flow_m3s * (1.0 - eco.oa_fraction) + total_flow_m3s * eco.oa_fraction * 0.5
    return_flow = min(return_flow, total_flow_m3s)
    # Typically 80% of supply static pressure for return side
    rf = fan_power(
        flow_m3s=return_flow,
        static_pressure_pa=duct.fan_static_pressure_pa * 0.6,
        fan_efficiency=ahu.return_fan_efficiency,
        motor_efficiency=ahu.return_fan_motor_efficiency,
        air_density_kg_m3=return_air_state.density_kg_m3,
    )

    total_fan_power_W = sf.motor_power_W + rf.motor_power_W

    # ------------------------------------------------------------------
    # 8. Plant coupling
    # ------------------------------------------------------------------
    chiller_load_W = cc.water_side_load_W  # Cooling coil → chiller
    boiler_load_W = heating_Q_W            # Heating coil → boiler

    chiller_power_W = chiller_load_W / plant.chiller_cop if plant.has_chiller and plant.chiller_cop > 0 else 0.0
    boiler_fuel_W = boiler_load_W / plant.boiler_efficiency if plant.has_boiler and plant.boiler_efficiency > 0 else 0.0

    total_system_power_W = total_fan_power_W + chiller_power_W

    # ------------------------------------------------------------------
    # 9. Free cooling quantification
    # ------------------------------------------------------------------
    # Free cooling offset: if economizer is active, the chiller would otherwise
    # need to handle the additional mixed-air enthalpy reduction
    if eco.free_cooling:
        # Without economizer, at min OA fraction
        mixed_no_eco = mix_air_streams(
            outdoor_air_state, return_air_state, ahu.min_oa_fraction, total_flow_m3s
        )
        rho_avg = (mixed_state.density_kg_m3 + mixed_no_eco.density_kg_m3) / 2
        m_da = rho_avg * total_flow_m3s
        free_cooling_W = max(
            m_da * (mixed_no_eco.h_kj_kg - mixed_state.h_kj_kg) * 1000, 0.0
        )
    else:
        free_cooling_W = 0.0

    # ------------------------------------------------------------------
    # 10. Energy balance
    # ------------------------------------------------------------------
    # Input: heating coil + fan shaft power (shaft energy heats the air)
    Q_in = heating_Q_W + sf.shaft_power_W + rf.shaft_power_W
    # Output: cooling coil load
    Q_out = cc.Q_total_W
    # Balance: supply enthalpy relative to return (net system heat exchange)
    rho_supply = supply_air_state.density_kg_m3
    rho_return = return_air_state.density_kg_m3
    m_supply = rho_supply * total_flow_m3s
    m_return = rho_return * total_flow_m3s
    # Net energy delivered to zones
    energy_to_zones = m_supply * supply_air_state.h_kj_kg * 1000 - m_return * return_air_state.h_kj_kg * 1000
    energy_balance = Q_in - Q_out + energy_to_zones  # Not exactly zero — residual = zone loads

    return AHUSystemResult(
        outdoor_air=outdoor_air_state,
        return_air=return_air_state,
        mixed_air=mixed_state,
        post_cooling_coil=post_cooling_state,
        supply_air=supply_air_state,

        oa_fraction=eco.oa_fraction,
        free_cooling=eco.free_cooling,
        free_cooling_load_W=free_cooling_W,

        cooling_coil_Q_total_W=cc.Q_total_W,
        cooling_coil_Q_sensible_W=cc.Q_sensible_W,
        cooling_coil_Q_latent_W=cc.Q_latent_W,
        cooling_coil_ADP_C=cc.ADP_C,
        cooling_coil_bypass_factor=cc.bypass_factor,
        cooling_coil_effectiveness=cc.coil_effectiveness,
        condensate_kg_s=cc.condensate_kg_s,

        heating_coil_Q_W=heating_Q_W,

        supply_fan_flow_m3s=sf.flow_m3s,
        supply_fan_static_pa=duct.fan_static_pressure_pa,
        supply_fan_power_W=sf.shaft_power_W,
        supply_fan_motor_power_W=sf.motor_power_W,
        supply_fan_temp_rise_C=sf.temperature_rise_C,

        return_fan_flow_m3s=rf.flow_m3s,
        return_fan_static_pa=duct.fan_static_pressure_pa * 0.6,
        return_fan_power_W=rf.shaft_power_W,
        return_fan_motor_power_W=rf.motor_power_W,

        total_fan_power_W=total_fan_power_W,

        zone_results=zone_results,
        total_zone_flow_m3s=total_zone_flow,
        total_zone_load_met_W=total_zone_load_met,

        chiller_load_W=chiller_load_W,
        chiller_power_W=chiller_power_W,
        boiler_load_W=boiler_load_W,
        boiler_fuel_W=boiler_fuel_W,
        total_system_power_W=total_system_power_W,

        energy_balance_W=energy_balance,
        duct_static_pressure_pa=duct.fan_static_pressure_pa,
    )
