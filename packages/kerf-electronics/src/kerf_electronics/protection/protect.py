"""
Circuit-protection design — closed-form models.

This module is distinct from:
  • kerf_electronics.powerconv  — DC-DC converter design
  • kerf_electronics.battery    — battery pack sizing
  • kerf_electronics.pdn        — power-delivery network (IR-drop, decap)
  • kerf_electronics.leddriver  — LED driver design
  • kerf_electronics.motordrive — motor drive sizing

Covered topics
--------------
fuse_select
    Continuous-current derating vs temperature, I²t let-through vs downstream
    withstand, voltage rating, interrupt rating.

inrush_ntc_size
    Inrush energy calculation and NTC inrush-limiter sizing (steady-state
    dissipation, resistance at operating temperature).

tvs_mov_clamp
    TVS / MOV clamp check: standoff vs working voltage, clamping voltage at
    surge current, peak-pulse-power & energy absorption, IEC 61000-4-2 /
    IEC 61000-4-5 compliance.

reverse_polarity
    Reverse-polarity protection: series diode voltage drop & power loss vs
    P-channel MOSFET RDS(on) conduction loss.

efuse_trip
    eFuse overcurrent-trip threshold and SOA note.

ptc_resettable
    PTC resettable fuse: hold / trip current at temperature, thermal time
    constant, steady-state power dissipation.

breaker_coordination
    Fuse / breaker time-current coordination — selectivity ratio check.

onderdonk_trace_fuse
    PCB trace fusing current from Onderdonk's equation.

wire_ampacity
    Wire ampacity protection check (NEC 310 simplified / chassis wiring
    per MIL-W-22759 / IPC-2221).

All functions are pure Python (math module only) and follow the kerf
never-raise contract: validation errors are returned as dicts with
{ok: False, reason: str}; condition flags (undersized, uncoordinated,
clamp-too-high, energy-exceeded) are reported via warnings.warn; exceptions
are never raised to callers.

References
----------
[Ott]   Ott, "Electromagnetic Compatibility Engineering", Wiley 2009
[IPC]   IPC-2221B §6.2 trace current / temperature
[NEC]   NEC 2023 Table 310.16 copper conductor ampacity
[IEC4-2] IEC 61000-4-2:2008 ESD immunity levels
[IEC4-5] IEC 61000-4-5:2014 surge immunity
[Onderdonk] W. H. Preece (1887) / I. M. Onderdonk (1928) trace fusing current

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Optional

# ── Physical / empirical constants ───────────────────────────────────────────

_COPPER_RESISTIVITY = 1.724e-8   # Ω·m at 20 °C
_COPPER_ALPHA = 0.00393          # /°C temperature coefficient of resistivity
_COPPER_MELTING_C = 1085.0       # °C — copper melting point

# ── Generic validators ───────────────────────────────────────────────────────


def _pos(value, name: str) -> Optional[str]:
    """Return error string if value is not a strictly positive finite number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive number, got {value!r}"
    return None


def _nonneg(value, name: str) -> Optional[str]:
    """Return error string if value is negative or not a real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _real(value, name: str) -> Optional[str]:
    """Return error string if value is not a finite real number."""
    if not isinstance(value, (int, float)) or math.isnan(value):
        return f"{name} must be a real number, got {value!r}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Fuse selection
# ═══════════════════════════════════════════════════════════════════════════════

def fuse_select(
    load_current_a: float,
    supply_voltage_v: float,
    ambient_temp_c: float,
    fuse_rating_a: float,
    fuse_voltage_v: float,
    fuse_interrupt_a: float,
    fuse_i2t_as2: float,
    downstream_i2t_withstand_as2: float,
    derating_factor: float = 0.75,
    temp_derating_ref_c: float = 25.0,
    temp_derating_coefficient: float = 0.005,
) -> dict:
    """
    Check whether a fuse is appropriately selected for a given load and supply.

    Derating model
    --------------
    A fuse rated at I_fuse at 25 °C is derated linearly with ambient temperature:
        I_derated = I_fuse × derating_factor × max(0, 1 − k × (T_amb − T_ref))
    where k = temp_derating_coefficient [/°C] and T_ref = temp_derating_ref_c.
    The load current must not exceed I_derated.

    I²t coordination
    ----------------
    The fuse let-through energy must not exceed the downstream withstand rating:
        fuse_i2t ≤ downstream_i2t_withstand

    Voltage and interrupt rating
    ----------------------------
    Fuse voltage rating must be ≥ supply voltage.
    Interrupt rating (short-circuit current) must be ≥ the available fault
    current (estimated conservatively as supply_voltage / 0.01 Ω = 100 × V for
    a very low-impedance source — caller should supply actual fault current via
    fuse_interrupt_a).

    Parameters
    ----------
    load_current_a              : float — continuous load current [A]
    supply_voltage_v            : float — supply voltage [V]
    ambient_temp_c              : float — ambient temperature [°C]
    fuse_rating_a               : float — fuse continuous rating [A] at temp_derating_ref_c
    fuse_voltage_v              : float — fuse voltage rating [V]
    fuse_interrupt_a            : float — fuse interrupt (short-circuit) rating [A]
    fuse_i2t_as2                : float — fuse let-through I²t [A²s]
    downstream_i2t_withstand_as2: float — downstream device I²t withstand [A²s]
    derating_factor             : float — safety derating multiplier (default 0.75)
    temp_derating_ref_c         : float — reference temperature for derating [°C] (default 25)
    temp_derating_coefficient   : float — linear derating coefficient [/°C] (default 0.005)

    Returns
    -------
    dict with keys:
        ok, load_current_a, fuse_rating_a, derated_current_a,
        current_ok, voltage_ok, interrupt_ok, i2t_ok,
        warnings (list of flag strings)
    """
    errs = [
        _pos(load_current_a, "load_current_a"),
        _pos(supply_voltage_v, "supply_voltage_v"),
        _real(ambient_temp_c, "ambient_temp_c"),
        _pos(fuse_rating_a, "fuse_rating_a"),
        _pos(fuse_voltage_v, "fuse_voltage_v"),
        _pos(fuse_interrupt_a, "fuse_interrupt_a"),
        _pos(fuse_i2t_as2, "fuse_i2t_as2"),
        _pos(downstream_i2t_withstand_as2, "downstream_i2t_withstand_as2"),
        _pos(derating_factor, "derating_factor"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    # Temperature derating
    temp_factor = max(0.0, 1.0 - temp_derating_coefficient * (ambient_temp_c - temp_derating_ref_c))
    derated_a = fuse_rating_a * derating_factor * temp_factor

    current_ok = load_current_a <= derated_a
    voltage_ok = fuse_voltage_v >= supply_voltage_v
    interrupt_ok = fuse_interrupt_a >= supply_voltage_v / 0.01   # 10 mΩ source — conservative
    i2t_ok = fuse_i2t_as2 <= downstream_i2t_withstand_as2

    warn_flags = []
    if not current_ok:
        msg = (
            f"fuse_select: fuse UNDERSIZED — load {load_current_a:.3f} A exceeds "
            f"derated rating {derated_a:.3f} A at {ambient_temp_c:.1f} °C "
            f"(nominal {fuse_rating_a} A × {derating_factor} derating)"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("UNDERSIZED")

    if not voltage_ok:
        msg = (
            f"fuse_select: voltage rating {fuse_voltage_v} V is below "
            f"supply {supply_voltage_v} V — VOLTAGE_RATING_LOW"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("VOLTAGE_RATING_LOW")

    if not interrupt_ok:
        msg = (
            f"fuse_select: interrupt rating {fuse_interrupt_a} A may be insufficient "
            f"(conservative fault estimate {supply_voltage_v/0.01:.0f} A) — "
            "INTERRUPT_RATING_LOW"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("INTERRUPT_RATING_LOW")

    if not i2t_ok:
        msg = (
            f"fuse_select: fuse I²t let-through {fuse_i2t_as2:.3e} A²s exceeds "
            f"downstream withstand {downstream_i2t_withstand_as2:.3e} A²s — "
            "I2T_EXCEEDED"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("I2T_EXCEEDED")

    return {
        "ok": True,
        "load_current_a": load_current_a,
        "supply_voltage_v": supply_voltage_v,
        "ambient_temp_c": ambient_temp_c,
        "fuse_rating_a": fuse_rating_a,
        "derated_current_a": round(derated_a, 4),
        "temp_factor": round(temp_factor, 4),
        "current_ok": current_ok,
        "voltage_ok": voltage_ok,
        "interrupt_ok": interrupt_ok,
        "i2t_ok": i2t_ok,
        "all_ok": current_ok and voltage_ok and interrupt_ok and i2t_ok,
        "warnings": warn_flags,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Inrush energy & NTC inrush-limiter sizing
# ═══════════════════════════════════════════════════════════════════════════════

def inrush_ntc_size(
    supply_voltage_v: float,
    bulk_capacitance_uf: float,
    ntc_resistance_cold_ohm: float,
    ntc_resistance_hot_ohm: float,
    ntc_max_power_w: float,
    steady_state_current_a: float,
    ambient_temp_c: float = 25.0,
) -> dict:
    """
    Inrush energy estimate and NTC inrush-limiter sizing check.

    Inrush energy
    -------------
    When a bulk capacitor C is charged through a series resistance R_cold
    from a supply V, the energy dissipated in R_cold during charging is:
        E_inrush = 0.5 × C × V²   [J]  (total capacitor charge energy)
    Peak inrush current:
        I_peak = V / R_cold

    NTC steady-state
    ----------------
    At normal operating temperature, the NTC resistance drops to R_hot.
    The steady-state power dissipated in the NTC is:
        P_ss = I_ss² × R_hot

    This must not exceed the NTC's rated continuous power (ntc_max_power_w).
    The voltage drop across the NTC at steady-state:
        V_drop = I_ss × R_hot

    Parameters
    ----------
    supply_voltage_v        : float — supply voltage [V]
    bulk_capacitance_uf     : float — bulk capacitance [μF]
    ntc_resistance_cold_ohm : float — NTC resistance at ambient (cold) [Ω]
    ntc_resistance_hot_ohm  : float — NTC resistance at operating temperature (hot) [Ω]
    ntc_max_power_w         : float — NTC rated continuous power dissipation [W]
    steady_state_current_a  : float — steady-state load current [A]
    ambient_temp_c          : float — ambient temperature [°C] (default 25)

    Returns
    -------
    dict with keys:
        ok, inrush_peak_a, inrush_energy_j, steady_state_power_w,
        ntc_voltage_drop_v, power_ok, warnings
    """
    errs = [
        _pos(supply_voltage_v, "supply_voltage_v"),
        _pos(bulk_capacitance_uf, "bulk_capacitance_uf"),
        _pos(ntc_resistance_cold_ohm, "ntc_resistance_cold_ohm"),
        _pos(ntc_resistance_hot_ohm, "ntc_resistance_hot_ohm"),
        _pos(ntc_max_power_w, "ntc_max_power_w"),
        _pos(steady_state_current_a, "steady_state_current_a"),
        _real(ambient_temp_c, "ambient_temp_c"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    C = bulk_capacitance_uf * 1e-6  # F
    V = supply_voltage_v
    R_cold = ntc_resistance_cold_ohm
    R_hot = ntc_resistance_hot_ohm
    I_ss = steady_state_current_a

    # Peak inrush current
    I_peak = V / R_cold

    # Energy dissipated in NTC during inrush (half the capacitor charge energy)
    E_inrush = 0.5 * C * V ** 2

    # Steady-state
    P_ss = I_ss ** 2 * R_hot
    V_drop = I_ss * R_hot

    power_ok = P_ss <= ntc_max_power_w
    warn_flags = []

    if not power_ok:
        msg = (
            f"inrush_ntc_size: NTC steady-state dissipation {P_ss:.3f} W exceeds "
            f"rated {ntc_max_power_w} W at {I_ss} A, R_hot={R_hot} Ω — "
            "NTC_OVERLOADED"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("NTC_OVERLOADED")

    if V_drop > 0.05 * V:
        msg = (
            f"inrush_ntc_size: NTC voltage drop {V_drop:.3f} V is >{5:.0f}% of supply "
            f"{V} V at steady state — EXCESSIVE_DROP"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("EXCESSIVE_DROP")

    return {
        "ok": True,
        "supply_voltage_v": V,
        "bulk_capacitance_uf": bulk_capacitance_uf,
        "ambient_temp_c": ambient_temp_c,
        "ntc_resistance_cold_ohm": R_cold,
        "ntc_resistance_hot_ohm": R_hot,
        "inrush_peak_a": round(I_peak, 4),
        "inrush_energy_j": round(E_inrush, 6),
        "steady_state_power_w": round(P_ss, 6),
        "ntc_voltage_drop_v": round(V_drop, 4),
        "power_ok": power_ok,
        "warnings": warn_flags,
        "formula": "I_peak = V/R_cold; E = 0.5×C×V²; P_ss = I_ss²×R_hot",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TVS / MOV clamp check
# ═══════════════════════════════════════════════════════════════════════════════

def tvs_mov_clamp(
    working_voltage_v: float,
    tvs_standoff_v: float,
    tvs_clamping_v_at_ipp: float,
    tvs_ipp_a: float,
    tvs_peak_power_w: float,
    surge_current_a: float,
    surge_energy_j: float,
    iec_level: Optional[str] = None,
) -> dict:
    """
    TVS / MOV clamp adequacy check.

    Standoff check
    --------------
    The TVS standoff voltage must be ≥ working voltage (peak AC or DC):
        V_standoff ≥ V_working

    Clamping voltage check
    ----------------------
    The clamping voltage at the specified peak pulse current I_pp is a device
    datasheet value.  It should not exceed the downstream component's VMAX:
        V_clamp(I_pp) ≤ V_downstream_max   [caller must verify; flagged here if
                                              V_clamp > 1.5 × V_standoff]

    Peak pulse power & energy
    -------------------------
    At the given surge current I_pp:
        P_pulse = V_clamp × I_pp   [W]
    This must not exceed the rated peak-pulse power:
        P_pulse ≤ tvs_peak_power_w

    Energy check:
        E_surge ≤ tvs_peak_power_w × t_pulse_s   (approximated here as
        E_surge check is direct: surge_energy_j is compared against
        tvs_peak_power_w × (default 8/20 μs = 20e-6 s for IEC 61000-4-5))

    IEC levels
    ----------
    level "1": I_pp = 0.5 kA (IEC 61000-4-5 Level 1)
    level "2": I_pp = 1.0 kA
    level "3": I_pp = 2.0 kA
    level "4": I_pp = 4.0 kA
    These are checked against surge_current_a when iec_level is given.

    Parameters
    ----------
    working_voltage_v       : float — circuit working voltage (peak) [V]
    tvs_standoff_v          : float — TVS/MOV standoff voltage [V]
    tvs_clamping_v_at_ipp   : float — clamping voltage at I_pp [V]
    tvs_ipp_a               : float — TVS/MOV peak pulse current rating [A]
    tvs_peak_power_w        : float — TVS/MOV peak pulse power rating [W]
    surge_current_a         : float — applied surge peak current [A]
    surge_energy_j          : float — applied surge energy [J]
    iec_level               : str|None — IEC 61000-4-5 level '1'..'4' (optional)

    Returns
    -------
    dict with keys:
        ok, standoff_ok, clamping_v_ok, power_ok, energy_ok, ipp_ok,
        pulse_power_w, iec_compliance, warnings
    """
    errs = [
        _pos(working_voltage_v, "working_voltage_v"),
        _pos(tvs_standoff_v, "tvs_standoff_v"),
        _pos(tvs_clamping_v_at_ipp, "tvs_clamping_v_at_ipp"),
        _pos(tvs_ipp_a, "tvs_ipp_a"),
        _pos(tvs_peak_power_w, "tvs_peak_power_w"),
        _pos(surge_current_a, "surge_current_a"),
        _nonneg(surge_energy_j, "surge_energy_j"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    _IEC_LEVELS = {"1": 500.0, "2": 1000.0, "3": 2000.0, "4": 4000.0}

    if iec_level is not None:
        iec_level_str = str(iec_level).strip()
        if iec_level_str not in _IEC_LEVELS:
            return {"ok": False, "reason": f"iec_level must be '1'..'4', got {iec_level!r}"}
        iec_required_a = _IEC_LEVELS[iec_level_str]
    else:
        iec_level_str = None
        iec_required_a = None

    standoff_ok = tvs_standoff_v >= working_voltage_v
    # Clamping voltage: flag if > 1.5× standoff (heuristic "clamp-too-high")
    clamping_v_ok = tvs_clamping_v_at_ipp <= 1.5 * tvs_standoff_v

    pulse_power_w = tvs_clamping_v_at_ipp * surge_current_a
    power_ok = pulse_power_w <= tvs_peak_power_w

    ipp_ok = tvs_ipp_a >= surge_current_a

    # Energy: approximate max energy = P_peak × 20 μs (8/20 μs waveform)
    max_energy_j = tvs_peak_power_w * 20e-6
    energy_ok = surge_energy_j <= max_energy_j

    iec_compliance = None
    if iec_required_a is not None:
        iec_compliance = tvs_ipp_a >= iec_required_a

    warn_flags = []
    if not standoff_ok:
        msg = (
            f"tvs_mov_clamp: standoff {tvs_standoff_v} V below working voltage "
            f"{working_voltage_v} V — will conduct during normal operation — "
            "STANDOFF_TOO_LOW"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("STANDOFF_TOO_LOW")

    if not clamping_v_ok:
        msg = (
            f"tvs_mov_clamp: clamping voltage {tvs_clamping_v_at_ipp} V is "
            f">{1.5*tvs_standoff_v:.1f} V (1.5× standoff) — CLAMP_TOO_HIGH"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("CLAMP_TOO_HIGH")

    if not power_ok:
        msg = (
            f"tvs_mov_clamp: pulse power {pulse_power_w:.1f} W exceeds rated "
            f"{tvs_peak_power_w} W — POWER_EXCEEDED"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("POWER_EXCEEDED")

    if not energy_ok:
        msg = (
            f"tvs_mov_clamp: surge energy {surge_energy_j:.4e} J exceeds "
            f"max estimate {max_energy_j:.4e} J — ENERGY_EXCEEDED"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("ENERGY_EXCEEDED")

    if not ipp_ok:
        msg = (
            f"tvs_mov_clamp: TVS/MOV I_pp rating {tvs_ipp_a} A below surge current "
            f"{surge_current_a} A — IPP_UNDERSIZED"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("IPP_UNDERSIZED")

    if iec_compliance is False:
        msg = (
            f"tvs_mov_clamp: IEC 61000-4-5 Level {iec_level_str} requires "
            f"{iec_required_a} A; TVS/MOV rated {tvs_ipp_a} A — "
            "IEC_LEVEL_NOT_MET"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("IEC_LEVEL_NOT_MET")

    return {
        "ok": True,
        "working_voltage_v": working_voltage_v,
        "tvs_standoff_v": tvs_standoff_v,
        "tvs_clamping_v_at_ipp": tvs_clamping_v_at_ipp,
        "surge_current_a": surge_current_a,
        "surge_energy_j": surge_energy_j,
        "pulse_power_w": round(pulse_power_w, 2),
        "max_energy_j": round(max_energy_j, 6),
        "standoff_ok": standoff_ok,
        "clamping_v_ok": clamping_v_ok,
        "power_ok": power_ok,
        "energy_ok": energy_ok,
        "ipp_ok": ipp_ok,
        "iec_level": iec_level_str,
        "iec_compliance": iec_compliance,
        "all_ok": standoff_ok and clamping_v_ok and power_ok and energy_ok and ipp_ok,
        "warnings": warn_flags,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Reverse-polarity protection
# ═══════════════════════════════════════════════════════════════════════════════

def reverse_polarity(
    supply_voltage_v: float,
    load_current_a: float,
    diode_vf_v: float,
    pfet_rds_on_ohm: float,
) -> dict:
    """
    Compare series diode vs P-channel MOSFET reverse-polarity protection.

    Series diode
    ------------
    Power loss:
        P_diode = V_f × I_load
    Voltage at load:
        V_load_diode = V_supply − V_f

    P-FET (low-side or high-side with gate pulled to supply)
    --------------------------------------------------------
    Conduction loss:
        P_pfet = I_load² × R_ds(on)
    Voltage at load:
        V_load_pfet = V_supply − I_load × R_ds(on)

    Parameters
    ----------
    supply_voltage_v  : float — supply voltage [V]
    load_current_a    : float — load current [A]
    diode_vf_v        : float — forward voltage of series diode at load current [V]
    pfet_rds_on_ohm   : float — P-FET RDS(on) at operating conditions [Ω]

    Returns
    -------
    dict with keys:
        ok, diode_power_w, diode_vload_v, pfet_power_w, pfet_vload_v,
        preferred (str: 'diode' or 'pfet'), warnings
    """
    errs = [
        _pos(supply_voltage_v, "supply_voltage_v"),
        _pos(load_current_a, "load_current_a"),
        _pos(diode_vf_v, "diode_vf_v"),
        _pos(pfet_rds_on_ohm, "pfet_rds_on_ohm"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    p_diode = diode_vf_v * load_current_a
    v_load_diode = supply_voltage_v - diode_vf_v

    p_pfet = load_current_a ** 2 * pfet_rds_on_ohm
    v_load_pfet = supply_voltage_v - load_current_a * pfet_rds_on_ohm

    preferred = "pfet" if p_pfet < p_diode else "diode"

    warn_flags = []
    if v_load_diode <= 0:
        warnings.warn(
            f"reverse_polarity: diode V_f {diode_vf_v} V ≥ supply {supply_voltage_v} V — "
            "load will not receive voltage — DIODE_VF_EXCEEDS_SUPPLY",
            stacklevel=2,
        )
        warn_flags.append("DIODE_VF_EXCEEDS_SUPPLY")

    if v_load_pfet < 0.9 * supply_voltage_v:
        warnings.warn(
            f"reverse_polarity: P-FET drop {load_current_a * pfet_rds_on_ohm:.3f} V "
            f"is >10% of supply — RDS_ON_HIGH",
            stacklevel=2,
        )
        warn_flags.append("RDS_ON_HIGH")

    return {
        "ok": True,
        "supply_voltage_v": supply_voltage_v,
        "load_current_a": load_current_a,
        "diode_vf_v": diode_vf_v,
        "pfet_rds_on_ohm": pfet_rds_on_ohm,
        "diode_power_w": round(p_diode, 4),
        "diode_vload_v": round(v_load_diode, 4),
        "pfet_power_w": round(p_pfet, 6),
        "pfet_vload_v": round(v_load_pfet, 4),
        "preferred": preferred,
        "warnings": warn_flags,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. eFuse trip & SOA
# ═══════════════════════════════════════════════════════════════════════════════

def efuse_trip(
    current_limit_a: float,
    load_current_a: float,
    supply_voltage_v: float,
    efuse_rds_on_ohm: float,
    efuse_max_power_w: float,
    trip_delay_us: float = 1.0,
) -> dict:
    """
    eFuse overcurrent-trip threshold check and SOA (Safe Operating Area) note.

    The eFuse trips when the load current exceeds current_limit_a.  During the
    trip delay, the eFuse internal FET must dissipate:
        P_peak = V_supply × I_fault × trip_delay_us × 1e-6  [energy, J]
    This is compared against the eFuse thermal capacity (approximated as
    efuse_max_power_w × 1e-3 s — a conservative 1 ms SOA window).

    Conduction loss at normal operation:
        P_conduction = I_load² × R_ds(on)

    Parameters
    ----------
    current_limit_a     : float — eFuse overcurrent trip threshold [A]
    load_current_a      : float — normal load current [A]
    supply_voltage_v    : float — supply voltage [V]
    efuse_rds_on_ohm    : float — eFuse internal FET RDS(on) [Ω]
    efuse_max_power_w   : float — eFuse continuous power rating [W]
    trip_delay_us       : float — overcurrent-to-trip delay [μs] (default 1.0)

    Returns
    -------
    dict with keys:
        ok, current_limit_a, load_current_a, conduction_power_w,
        fault_energy_j, soa_ok, conduction_ok, warnings
    """
    errs = [
        _pos(current_limit_a, "current_limit_a"),
        _pos(load_current_a, "load_current_a"),
        _pos(supply_voltage_v, "supply_voltage_v"),
        _pos(efuse_rds_on_ohm, "efuse_rds_on_ohm"),
        _pos(efuse_max_power_w, "efuse_max_power_w"),
        _pos(trip_delay_us, "trip_delay_us"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    p_cond = load_current_a ** 2 * efuse_rds_on_ohm
    conduction_ok = p_cond <= efuse_max_power_w

    # Fault energy during trip delay (worst case: fault current = supply/Rds)
    # Conservative: fault current at current_limit (eFuse holds at limit until trip)
    t_trip = trip_delay_us * 1e-6
    fault_energy_j = supply_voltage_v * current_limit_a * t_trip
    soa_window_j = efuse_max_power_w * 1e-3  # 1 ms SOA window
    soa_ok = fault_energy_j <= soa_window_j

    warn_flags = []
    if not conduction_ok:
        msg = (
            f"efuse_trip: conduction loss {p_cond:.4f} W exceeds eFuse rating "
            f"{efuse_max_power_w} W — CONDUCTION_OVERLOAD"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("CONDUCTION_OVERLOAD")

    if not soa_ok:
        msg = (
            f"efuse_trip: fault energy {fault_energy_j:.4e} J during {trip_delay_us} μs "
            f"trip delay exceeds SOA estimate {soa_window_j:.4e} J — SOA_EXCEEDED"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("SOA_EXCEEDED")

    if load_current_a >= current_limit_a:
        msg = (
            f"efuse_trip: load current {load_current_a} A ≥ trip threshold "
            f"{current_limit_a} A — eFuse will trip under normal load — WILL_TRIP"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("WILL_TRIP")

    return {
        "ok": True,
        "current_limit_a": current_limit_a,
        "load_current_a": load_current_a,
        "supply_voltage_v": supply_voltage_v,
        "efuse_rds_on_ohm": efuse_rds_on_ohm,
        "conduction_power_w": round(p_cond, 6),
        "trip_delay_us": trip_delay_us,
        "fault_energy_j": round(fault_energy_j, 8),
        "soa_window_j": round(soa_window_j, 6),
        "soa_ok": soa_ok,
        "conduction_ok": conduction_ok,
        "warnings": warn_flags,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PTC resettable fuse
# ═══════════════════════════════════════════════════════════════════════════════

def ptc_resettable(
    ptc_hold_current_a: float,
    ptc_trip_current_a: float,
    load_current_a: float,
    ptc_resistance_ohm: float,
    supply_voltage_v: float,
    ambient_temp_c: float = 25.0,
    ptc_hold_temp_ref_c: float = 25.0,
    ptc_temp_derating_pct_per_c: float = 0.5,
) -> dict:
    """
    PTC resettable fuse hold/trip check at operating temperature.

    Temperature derating
    --------------------
    Hold and trip currents are derated linearly above the reference temperature:
        I_hold_derated = I_hold × max(0.01, 1 − k × (T_amb − T_ref) / 100)
        I_trip_derated = I_trip × max(0.01, 1 − k × (T_amb − T_ref) / 100)
    where k = ptc_temp_derating_pct_per_c [%/°C].

    Steady-state power
    ------------------
        P_hold = I_load² × R_ptc

    Parameters
    ----------
    ptc_hold_current_a         : float — hold current at reference temperature [A]
    ptc_trip_current_a         : float — trip current at reference temperature [A]
    load_current_a             : float — normal load current [A]
    ptc_resistance_ohm         : float — PTC resistance at hold condition [Ω]
    supply_voltage_v           : float — supply voltage [V]
    ambient_temp_c             : float — ambient temperature [°C]
    ptc_hold_temp_ref_c        : float — temperature at which hold/trip are specified [°C]
    ptc_temp_derating_pct_per_c: float — derating rate [%/°C]

    Returns
    -------
    dict with keys:
        ok, hold_current_derated_a, trip_current_derated_a,
        load_within_hold, will_trip, steady_state_power_w, warnings
    """
    errs = [
        _pos(ptc_hold_current_a, "ptc_hold_current_a"),
        _pos(ptc_trip_current_a, "ptc_trip_current_a"),
        _pos(load_current_a, "load_current_a"),
        _pos(ptc_resistance_ohm, "ptc_resistance_ohm"),
        _pos(supply_voltage_v, "supply_voltage_v"),
        _real(ambient_temp_c, "ambient_temp_c"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    if ptc_trip_current_a <= ptc_hold_current_a:
        return {
            "ok": False,
            "reason": (
                f"ptc_trip_current_a ({ptc_trip_current_a}) must be greater than "
                f"ptc_hold_current_a ({ptc_hold_current_a})"
            ),
        }

    temp_delta = ambient_temp_c - ptc_hold_temp_ref_c
    derating = max(0.01, 1.0 - ptc_temp_derating_pct_per_c / 100.0 * temp_delta)

    hold_derated = ptc_hold_current_a * derating
    trip_derated = ptc_trip_current_a * derating

    load_within_hold = load_current_a <= hold_derated
    will_trip = load_current_a >= trip_derated
    p_ss = load_current_a ** 2 * ptc_resistance_ohm

    warn_flags = []
    if not load_within_hold:
        if will_trip:
            msg = (
                f"ptc_resettable: load {load_current_a} A ≥ derated trip "
                f"{trip_derated:.3f} A at {ambient_temp_c} °C — PTC_WILL_TRIP"
            )
            warnings.warn(msg, stacklevel=2)
            warn_flags.append("PTC_WILL_TRIP")
        else:
            msg = (
                f"ptc_resettable: load {load_current_a} A is between hold "
                f"{hold_derated:.3f} A and trip {trip_derated:.3f} A — "
                "PTC_MARGINAL (PTC may trip intermittently)"
            )
            warnings.warn(msg, stacklevel=2)
            warn_flags.append("PTC_MARGINAL")

    return {
        "ok": True,
        "ptc_hold_current_a": ptc_hold_current_a,
        "ptc_trip_current_a": ptc_trip_current_a,
        "load_current_a": load_current_a,
        "ambient_temp_c": ambient_temp_c,
        "derating_factor": round(derating, 4),
        "hold_current_derated_a": round(hold_derated, 4),
        "trip_current_derated_a": round(trip_derated, 4),
        "load_within_hold": load_within_hold,
        "will_trip": will_trip,
        "steady_state_power_w": round(p_ss, 6),
        "warnings": warn_flags,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Breaker / fuse time-current coordination (selectivity)
# ═══════════════════════════════════════════════════════════════════════════════

def breaker_coordination(
    upstream_trip_current_a: float,
    downstream_trip_current_a: float,
    upstream_trip_time_s: float,
    downstream_trip_time_s: float,
    selectivity_ratio_min: float = 1.6,
) -> dict:
    """
    Fuse / breaker time-current coordination: selectivity ratio check.

    Selectivity (discrimination) ratio
    -----------------------------------
    For the upstream device to clear a fault without the downstream device
    also tripping, the trip current ratio must meet:
        I_upstream_trip / I_downstream_trip ≥ selectivity_ratio_min

    AND the upstream trip time must be greater than the downstream trip time
    at the fault current level (i.e., the downstream device clears first):
        t_downstream < t_upstream

    Both conditions must hold for full coordination.  "Partial coordination"
    is flagged when only the current ratio is met.

    Parameters
    ----------
    upstream_trip_current_a   : float — upstream device trip current [A]
    downstream_trip_current_a : float — downstream device trip current [A]
    upstream_trip_time_s      : float — upstream device trip time at fault [s]
    downstream_trip_time_s    : float — downstream device trip time at fault [s]
    selectivity_ratio_min     : float — minimum acceptable ratio (default 1.6)

    Returns
    -------
    dict with keys:
        ok, selectivity_ratio, ratio_ok, time_ok, coordinated, warnings
    """
    errs = [
        _pos(upstream_trip_current_a, "upstream_trip_current_a"),
        _pos(downstream_trip_current_a, "downstream_trip_current_a"),
        _pos(upstream_trip_time_s, "upstream_trip_time_s"),
        _pos(downstream_trip_time_s, "downstream_trip_time_s"),
        _pos(selectivity_ratio_min, "selectivity_ratio_min"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    ratio = upstream_trip_current_a / downstream_trip_current_a
    ratio_ok = ratio >= selectivity_ratio_min
    time_ok = downstream_trip_time_s < upstream_trip_time_s
    coordinated = ratio_ok and time_ok

    warn_flags = []
    if not coordinated:
        msg = (
            f"breaker_coordination: devices are UNCOORDINATED — "
            f"selectivity ratio {ratio:.2f} (min {selectivity_ratio_min}), "
            f"upstream trips in {upstream_trip_time_s} s, "
            f"downstream trips in {downstream_trip_time_s} s"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("UNCOORDINATED")
    elif not time_ok:
        msg = (
            f"breaker_coordination: partial coordination — current ratio ok but "
            f"upstream clears faster ({upstream_trip_time_s} s) than downstream "
            f"({downstream_trip_time_s} s) — PARTIAL_COORDINATION"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("PARTIAL_COORDINATION")

    return {
        "ok": True,
        "upstream_trip_current_a": upstream_trip_current_a,
        "downstream_trip_current_a": downstream_trip_current_a,
        "upstream_trip_time_s": upstream_trip_time_s,
        "downstream_trip_time_s": downstream_trip_time_s,
        "selectivity_ratio": round(ratio, 4),
        "selectivity_ratio_min": selectivity_ratio_min,
        "ratio_ok": ratio_ok,
        "time_ok": time_ok,
        "coordinated": coordinated,
        "warnings": warn_flags,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 8. PCB trace fusing current (Onderdonk)
# ═══════════════════════════════════════════════════════════════════════════════

def onderdonk_trace_fuse(
    trace_width_mm: float,
    trace_thickness_um: float,
    fusing_time_s: float,
    ambient_temp_c: float = 25.0,
    melting_temp_c: float = _COPPER_MELTING_C,
) -> dict:
    """
    PCB copper trace fusing current from Onderdonk's equation.

    Onderdonk (1928):
        I_fuse = A × sqrt( (ΔT) / (33 × t) )

    where:
        A        = cross-sectional area of the trace [circular mils]
        ΔT       = melting_temp − ambient_temp [°C]
        t        = time to fuse [s]
        33       = empirical constant for copper (units: °C·s / (A²·cmil))

    Cross-sectional area conversion:
        A [cm²] = width_mm × 0.1 × thickness_um × 1e-4
                = width_mm × thickness_um × 1e-5   [cm²]
        A [circular mils] = A [cm²] / (5.067e-6)
                          = A [cm²] × 197353   [approximately]

    Note: 1 cmil = (π/4) × (0.0001 in)² = 5.067e-6 cm².

    The formula gives the DC RMS fusing current.  For very short pulses
    (< 0.1 s) and for traces on FR4 the model is conservative (actual fusing
    current may be slightly lower due to substrate heating).

    Parameters
    ----------
    trace_width_mm     : float — trace width [mm]
    trace_thickness_um : float — copper thickness [μm]  (e.g. 35 μm = 1 oz, 70 μm = 2 oz)
    fusing_time_s      : float — time from fault onset to fuse [s]
    ambient_temp_c     : float — ambient temperature [°C] (default 25)
    melting_temp_c     : float — copper melting point [°C] (default 1085)

    Returns
    -------
    dict with keys:
        ok, trace_width_mm, trace_thickness_um, fusing_time_s,
        cross_section_mm2, cross_section_cmil,
        fusing_current_a, formula
    """
    errs = [
        _pos(trace_width_mm, "trace_width_mm"),
        _pos(trace_thickness_um, "trace_thickness_um"),
        _pos(fusing_time_s, "fusing_time_s"),
        _real(ambient_temp_c, "ambient_temp_c"),
        _real(melting_temp_c, "melting_temp_c"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    if melting_temp_c <= ambient_temp_c:
        return {
            "ok": False,
            "reason": (
                f"melting_temp_c ({melting_temp_c}) must be greater than "
                f"ambient_temp_c ({ambient_temp_c})"
            ),
        }

    delta_t = melting_temp_c - ambient_temp_c

    # Cross-sectional area
    area_mm2 = trace_width_mm * (trace_thickness_um * 1e-3)  # mm²
    area_cm2 = area_mm2 * 1e-2  # cm²
    # 1 circular mil = 5.0671e-6 cm²
    area_cmil = area_cm2 / 5.0671e-6

    # Onderdonk: I = A [cmil] × sqrt(delta_T / (33 × t))
    fusing_current_a = area_cmil * math.sqrt(delta_t / (33.0 * fusing_time_s))

    return {
        "ok": True,
        "trace_width_mm": trace_width_mm,
        "trace_thickness_um": trace_thickness_um,
        "fusing_time_s": fusing_time_s,
        "ambient_temp_c": ambient_temp_c,
        "melting_temp_c": melting_temp_c,
        "cross_section_mm2": round(area_mm2, 6),
        "cross_section_cmil": round(area_cmil, 2),
        "fusing_current_a": round(fusing_current_a, 3),
        "formula": "Onderdonk (1928): I = A[cmil] × sqrt(ΔT / (33 × t))",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Wire ampacity protection check
# ═══════════════════════════════════════════════════════════════════════════════

# NEC 310.16 copper wire ampacity (A) for 60°C insulation, 30°C ambient.
# Key: AWG → (ampacity_a, resistance_mohm_per_m)
# Resistance values from ASTM B3 at 20°C.
_AWG_TABLE = {
    # AWG: (ampacity_A, resistance_mΩ/m)
    30: (0.86,  339.7),
    28: (1.4,   213.9),
    26: (2.2,   134.5),
    24: (3.5,   84.22),
    22: (5.0,   53.48),
    20: (7.5,   33.62),
    18: (10.0,  21.14),
    16: (13.0,  13.29),
    14: (15.0,  8.454),
    12: (20.0,  5.315),
    10: (30.0,  3.277),
     8: (40.0,  2.061),
     6: (55.0,  1.296),
     4: (70.0,  0.8152),
     2: (95.0,  0.5118),
     0: (125.0, 0.3224),
}


def wire_ampacity(
    awg: int,
    load_current_a: float,
    wire_length_m: float,
    ambient_temp_c: float = 30.0,
    insulation_temp_c: float = 60.0,
    fuse_rating_a: Optional[float] = None,
) -> dict:
    """
    Wire ampacity protection check.

    Ampacity derating
    -----------------
    The NEC 310.16 table is referenced at 30 °C.  For ambient temperatures
    above 30 °C, a correction factor is applied:
        CF = sqrt((T_ins − T_amb) / (T_ins − 30))
        I_allowed = I_base × CF

    Voltage drop
    ------------
        V_drop = I_load × (R_wire [Ω/m] × wire_length_m × 2)  (round-trip)

    Fuse coordination (optional)
    ----------------------------
    When fuse_rating_a is provided, the fuse must not exceed the derated wire
    ampacity (NEC 240.4):
        fuse_rating_a ≤ I_allowed

    Parameters
    ----------
    awg              : int   — AWG wire gauge (must be in table: 30..0)
    load_current_a   : float — load current [A]
    wire_length_m    : float — one-way wire run length [m]
    ambient_temp_c   : float — ambient temperature [°C] (default 30)
    insulation_temp_c: float — insulation temperature rating [°C] (default 60)
    fuse_rating_a    : float|None — overcurrent device rating [A] (optional)

    Returns
    -------
    dict with keys:
        ok, awg, base_ampacity_a, derated_ampacity_a, load_current_a,
        ampacity_ok, voltage_drop_v, resistance_mohm_per_m,
        fuse_ok (None if fuse_rating_a not given), warnings
    """
    errs = [
        _pos(load_current_a, "load_current_a"),
        _pos(wire_length_m, "wire_length_m"),
        _real(ambient_temp_c, "ambient_temp_c"),
        _real(insulation_temp_c, "insulation_temp_c"),
    ]
    for e in errs:
        if e:
            return {"ok": False, "reason": e}

    if not isinstance(awg, int):
        return {"ok": False, "reason": f"awg must be an integer, got {awg!r}"}
    if awg not in _AWG_TABLE:
        return {
            "ok": False,
            "reason": (
                f"AWG {awg} not in lookup table. Supported: "
                f"{sorted(_AWG_TABLE.keys())}"
            ),
        }

    if insulation_temp_c <= ambient_temp_c:
        return {
            "ok": False,
            "reason": (
                f"insulation_temp_c ({insulation_temp_c}) must be greater than "
                f"ambient_temp_c ({ambient_temp_c})"
            ),
        }

    base_a, r_mohm_per_m = _AWG_TABLE[awg]

    # Temperature correction factor
    cf = math.sqrt((insulation_temp_c - ambient_temp_c) / (insulation_temp_c - 30.0))
    derated_a = base_a * cf

    ampacity_ok = load_current_a <= derated_a

    # Round-trip voltage drop (mΩ → Ω)
    r_total_ohm = r_mohm_per_m * 1e-3 * wire_length_m * 2.0
    v_drop = load_current_a * r_total_ohm

    fuse_ok = None
    if fuse_rating_a is not None:
        err = _pos(fuse_rating_a, "fuse_rating_a")
        if err:
            return {"ok": False, "reason": err}
        fuse_ok = fuse_rating_a <= derated_a

    warn_flags = []
    if not ampacity_ok:
        msg = (
            f"wire_ampacity: AWG {awg} load {load_current_a} A exceeds "
            f"derated ampacity {derated_a:.2f} A at {ambient_temp_c} °C — "
            "WIRE_UNDERSIZED"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("WIRE_UNDERSIZED")

    if fuse_ok is False:
        msg = (
            f"wire_ampacity: fuse rating {fuse_rating_a} A exceeds derated "
            f"wire ampacity {derated_a:.2f} A — FUSE_OVERSIZED_FOR_WIRE"
        )
        warnings.warn(msg, stacklevel=2)
        warn_flags.append("FUSE_OVERSIZED_FOR_WIRE")

    return {
        "ok": True,
        "awg": awg,
        "base_ampacity_a": base_a,
        "derated_ampacity_a": round(derated_a, 3),
        "temp_correction_factor": round(cf, 4),
        "load_current_a": load_current_a,
        "ampacity_ok": ampacity_ok,
        "resistance_mohm_per_m": r_mohm_per_m,
        "wire_length_m": wire_length_m,
        "voltage_drop_v": round(v_drop, 4),
        "fuse_rating_a": fuse_rating_a,
        "fuse_ok": fuse_ok,
        "warnings": warn_flags,
        "standard": "NEC 310.16 / IPC-2221",
    }
