"""
Circuit-protection LLM tools.

Provides nine LLM-callable tools:

  protection_fuse_select          — fuse continuous-current derating, I²t, voltage &
                                    interrupt rating
  protection_inrush_ntc_size      — inrush energy + NTC inrush-limiter sizing
  protection_tvs_mov_clamp        — TVS/MOV clamp adequacy (standoff, clamp voltage,
                                    power, energy, IEC 61000-4-5)
  protection_reverse_polarity     — series diode vs P-FET conduction loss
  protection_efuse_trip           — eFuse overcurrent-trip threshold + SOA
  protection_ptc_resettable       — PTC hold/trip derating at temperature
  protection_breaker_coordination — fuse/breaker selectivity ratio
  protection_onderdonk_trace_fuse — PCB trace fusing current (Onderdonk)
  protection_wire_ampacity        — wire ampacity check (NEC 310.16)

All handlers follow the kerf never-raise contract: errors → {"ok": false, "reason": ...}.
Condition flags are reported via warnings.warn; exceptions are never raised to callers.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.protection.protect import (
    breaker_coordination,
    efuse_trip,
    fuse_select,
    inrush_ntc_size,
    onderdonk_trace_fuse,
    ptc_resettable,
    reverse_polarity,
    tvs_mov_clamp,
    wire_ampacity,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. protection_fuse_select
# ═══════════════════════════════════════════════════════════════════════════════

_FUSE_SELECT_SPEC = ToolSpec(
    name="protection_fuse_select",
    description=(
        "Select and validate a fuse for a given load and supply.\n\n"
        "Checks:\n"
        "  • Continuous-current derating vs temperature\n"
        "  • I²t let-through vs downstream device withstand\n"
        "  • Voltage rating ≥ supply voltage\n"
        "  • Interrupt rating (short-circuit)\n\n"
        "Warnings issued for: UNDERSIZED, VOLTAGE_RATING_LOW, "
        "INTERRUPT_RATING_LOW, I2T_EXCEEDED.\n\n"
        "Input: { load_current_a, supply_voltage_v, ambient_temp_c, fuse_rating_a, "
        "fuse_voltage_v, fuse_interrupt_a, fuse_i2t_as2, "
        "downstream_i2t_withstand_as2, derating_factor?, temp_derating_ref_c?, "
        "temp_derating_coefficient? }\n"
        "Returns: { ok, derated_current_a, current_ok, voltage_ok, "
        "interrupt_ok, i2t_ok, all_ok, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "load_current_a": {"type": "number", "description": "Continuous load current [A]."},
            "supply_voltage_v": {"type": "number", "description": "Supply voltage [V]."},
            "ambient_temp_c": {"type": "number", "description": "Ambient temperature [°C]."},
            "fuse_rating_a": {"type": "number", "description": "Fuse continuous rating [A] at reference temperature."},
            "fuse_voltage_v": {"type": "number", "description": "Fuse voltage rating [V]."},
            "fuse_interrupt_a": {"type": "number", "description": "Fuse interrupt (short-circuit) rating [A]."},
            "fuse_i2t_as2": {"type": "number", "description": "Fuse let-through I²t [A²s]."},
            "downstream_i2t_withstand_as2": {"type": "number", "description": "Downstream device I²t withstand [A²s]."},
            "derating_factor": {"type": "number", "description": "Safety derating multiplier (default 0.75)."},
            "temp_derating_ref_c": {"type": "number", "description": "Reference temperature for derating [°C] (default 25)."},
            "temp_derating_coefficient": {"type": "number", "description": "Linear derating coefficient [/°C] (default 0.005)."},
        },
        "required": [
            "load_current_a", "supply_voltage_v", "ambient_temp_c",
            "fuse_rating_a", "fuse_voltage_v", "fuse_interrupt_a",
            "fuse_i2t_as2", "downstream_i2t_withstand_as2",
        ],
    },
)


@register(_FUSE_SELECT_SPEC, write=False)
async def protection_fuse_select(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = fuse_select(
        load_current_a=a.get("load_current_a"),
        supply_voltage_v=a.get("supply_voltage_v"),
        ambient_temp_c=a.get("ambient_temp_c"),
        fuse_rating_a=a.get("fuse_rating_a"),
        fuse_voltage_v=a.get("fuse_voltage_v"),
        fuse_interrupt_a=a.get("fuse_interrupt_a"),
        fuse_i2t_as2=a.get("fuse_i2t_as2"),
        downstream_i2t_withstand_as2=a.get("downstream_i2t_withstand_as2"),
        derating_factor=a.get("derating_factor", 0.75),
        temp_derating_ref_c=a.get("temp_derating_ref_c", 25.0),
        temp_derating_coefficient=a.get("temp_derating_coefficient", 0.005),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. protection_inrush_ntc_size
# ═══════════════════════════════════════════════════════════════════════════════

_INRUSH_NTC_SPEC = ToolSpec(
    name="protection_inrush_ntc_size",
    description=(
        "Estimate inrush energy and size an NTC inrush-limiter thermistor.\n\n"
        "Model: peak inrush I = V / R_cold; energy E = 0.5×C×V²; "
        "steady-state P = I_ss²×R_hot.\n\n"
        "Warnings: NTC_OVERLOADED, EXCESSIVE_DROP (>5% of supply).\n\n"
        "Input: { supply_voltage_v, bulk_capacitance_uf, ntc_resistance_cold_ohm, "
        "ntc_resistance_hot_ohm, ntc_max_power_w, steady_state_current_a, ambient_temp_c? }\n"
        "Returns: { ok, inrush_peak_a, inrush_energy_j, steady_state_power_w, "
        "ntc_voltage_drop_v, power_ok, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "supply_voltage_v": {"type": "number", "description": "Supply voltage [V]."},
            "bulk_capacitance_uf": {"type": "number", "description": "Bulk capacitance [μF]."},
            "ntc_resistance_cold_ohm": {"type": "number", "description": "NTC resistance at ambient (cold) [Ω]."},
            "ntc_resistance_hot_ohm": {"type": "number", "description": "NTC resistance at operating temperature (hot) [Ω]."},
            "ntc_max_power_w": {"type": "number", "description": "NTC rated continuous power dissipation [W]."},
            "steady_state_current_a": {"type": "number", "description": "Steady-state load current [A]."},
            "ambient_temp_c": {"type": "number", "description": "Ambient temperature [°C] (default 25)."},
        },
        "required": [
            "supply_voltage_v", "bulk_capacitance_uf",
            "ntc_resistance_cold_ohm", "ntc_resistance_hot_ohm",
            "ntc_max_power_w", "steady_state_current_a",
        ],
    },
)


@register(_INRUSH_NTC_SPEC, write=False)
async def protection_inrush_ntc_size(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = inrush_ntc_size(
        supply_voltage_v=a.get("supply_voltage_v"),
        bulk_capacitance_uf=a.get("bulk_capacitance_uf"),
        ntc_resistance_cold_ohm=a.get("ntc_resistance_cold_ohm"),
        ntc_resistance_hot_ohm=a.get("ntc_resistance_hot_ohm"),
        ntc_max_power_w=a.get("ntc_max_power_w"),
        steady_state_current_a=a.get("steady_state_current_a"),
        ambient_temp_c=a.get("ambient_temp_c", 25.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. protection_tvs_mov_clamp
# ═══════════════════════════════════════════════════════════════════════════════

_TVS_MOV_SPEC = ToolSpec(
    name="protection_tvs_mov_clamp",
    description=(
        "Check TVS / MOV clamp device adequacy for a surge event.\n\n"
        "Checks: standoff ≥ working voltage, clamping voltage ≤ 1.5× standoff, "
        "pulse power ≤ rated power, surge energy ≤ 8/20 μs energy capacity, "
        "I_pp ≥ surge current, IEC 61000-4-5 level compliance.\n\n"
        "Warnings: STANDOFF_TOO_LOW, CLAMP_TOO_HIGH, POWER_EXCEEDED, "
        "ENERGY_EXCEEDED, IPP_UNDERSIZED, IEC_LEVEL_NOT_MET.\n\n"
        "Input: { working_voltage_v, tvs_standoff_v, tvs_clamping_v_at_ipp, "
        "tvs_ipp_a, tvs_peak_power_w, surge_current_a, surge_energy_j, iec_level? }\n"
        "Returns: { ok, standoff_ok, clamping_v_ok, power_ok, energy_ok, ipp_ok, "
        "iec_compliance, pulse_power_w, all_ok, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "working_voltage_v": {"type": "number", "description": "Circuit working voltage [V]."},
            "tvs_standoff_v": {"type": "number", "description": "TVS/MOV standoff voltage [V]."},
            "tvs_clamping_v_at_ipp": {"type": "number", "description": "Clamping voltage at I_pp [V]."},
            "tvs_ipp_a": {"type": "number", "description": "TVS/MOV peak pulse current rating [A]."},
            "tvs_peak_power_w": {"type": "number", "description": "TVS/MOV peak pulse power rating [W]."},
            "surge_current_a": {"type": "number", "description": "Applied surge peak current [A]."},
            "surge_energy_j": {"type": "number", "description": "Applied surge energy [J]."},
            "iec_level": {
                "type": "string",
                "enum": ["1", "2", "3", "4"],
                "description": "IEC 61000-4-5 immunity level '1'..'4' (optional).",
            },
        },
        "required": [
            "working_voltage_v", "tvs_standoff_v", "tvs_clamping_v_at_ipp",
            "tvs_ipp_a", "tvs_peak_power_w", "surge_current_a", "surge_energy_j",
        ],
    },
)


@register(_TVS_MOV_SPEC, write=False)
async def protection_tvs_mov_clamp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = tvs_mov_clamp(
        working_voltage_v=a.get("working_voltage_v"),
        tvs_standoff_v=a.get("tvs_standoff_v"),
        tvs_clamping_v_at_ipp=a.get("tvs_clamping_v_at_ipp"),
        tvs_ipp_a=a.get("tvs_ipp_a"),
        tvs_peak_power_w=a.get("tvs_peak_power_w"),
        surge_current_a=a.get("surge_current_a"),
        surge_energy_j=a.get("surge_energy_j"),
        iec_level=a.get("iec_level"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. protection_reverse_polarity
# ═══════════════════════════════════════════════════════════════════════════════

_REV_POL_SPEC = ToolSpec(
    name="protection_reverse_polarity",
    description=(
        "Compare series diode vs P-channel MOSFET reverse-polarity protection.\n\n"
        "Calculates conduction loss and load voltage for each approach and "
        "recommends the lower-loss option.\n\n"
        "Warnings: DIODE_VF_EXCEEDS_SUPPLY, RDS_ON_HIGH (>10% drop).\n\n"
        "Input: { supply_voltage_v, load_current_a, diode_vf_v, pfet_rds_on_ohm }\n"
        "Returns: { ok, diode_power_w, diode_vload_v, pfet_power_w, pfet_vload_v, "
        "preferred, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "supply_voltage_v": {"type": "number", "description": "Supply voltage [V]."},
            "load_current_a": {"type": "number", "description": "Load current [A]."},
            "diode_vf_v": {"type": "number", "description": "Diode forward voltage at load current [V]."},
            "pfet_rds_on_ohm": {"type": "number", "description": "P-FET RDS(on) at operating conditions [Ω]."},
        },
        "required": ["supply_voltage_v", "load_current_a", "diode_vf_v", "pfet_rds_on_ohm"],
    },
)


@register(_REV_POL_SPEC, write=False)
async def protection_reverse_polarity(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = reverse_polarity(
        supply_voltage_v=a.get("supply_voltage_v"),
        load_current_a=a.get("load_current_a"),
        diode_vf_v=a.get("diode_vf_v"),
        pfet_rds_on_ohm=a.get("pfet_rds_on_ohm"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. protection_efuse_trip
# ═══════════════════════════════════════════════════════════════════════════════

_EFUSE_SPEC = ToolSpec(
    name="protection_efuse_trip",
    description=(
        "eFuse overcurrent-trip threshold check and SOA (Safe Operating Area) note.\n\n"
        "Checks conduction loss at normal current and fault energy during trip delay "
        "against the eFuse's thermal capacity.\n\n"
        "Warnings: CONDUCTION_OVERLOAD, SOA_EXCEEDED, WILL_TRIP.\n\n"
        "Input: { current_limit_a, load_current_a, supply_voltage_v, "
        "efuse_rds_on_ohm, efuse_max_power_w, trip_delay_us? }\n"
        "Returns: { ok, conduction_power_w, fault_energy_j, soa_ok, "
        "conduction_ok, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_limit_a": {"type": "number", "description": "eFuse overcurrent trip threshold [A]."},
            "load_current_a": {"type": "number", "description": "Normal load current [A]."},
            "supply_voltage_v": {"type": "number", "description": "Supply voltage [V]."},
            "efuse_rds_on_ohm": {"type": "number", "description": "eFuse internal FET RDS(on) [Ω]."},
            "efuse_max_power_w": {"type": "number", "description": "eFuse continuous power rating [W]."},
            "trip_delay_us": {"type": "number", "description": "Overcurrent-to-trip delay [μs] (default 1.0)."},
        },
        "required": [
            "current_limit_a", "load_current_a", "supply_voltage_v",
            "efuse_rds_on_ohm", "efuse_max_power_w",
        ],
    },
)


@register(_EFUSE_SPEC, write=False)
async def protection_efuse_trip(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = efuse_trip(
        current_limit_a=a.get("current_limit_a"),
        load_current_a=a.get("load_current_a"),
        supply_voltage_v=a.get("supply_voltage_v"),
        efuse_rds_on_ohm=a.get("efuse_rds_on_ohm"),
        efuse_max_power_w=a.get("efuse_max_power_w"),
        trip_delay_us=a.get("trip_delay_us", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. protection_ptc_resettable
# ═══════════════════════════════════════════════════════════════════════════════

_PTC_SPEC = ToolSpec(
    name="protection_ptc_resettable",
    description=(
        "PTC resettable fuse hold/trip current check at operating temperature.\n\n"
        "Applies linear temperature derating to the hold and trip currents "
        "and checks whether the load current is safely within the hold zone.\n\n"
        "Warnings: PTC_WILL_TRIP, PTC_MARGINAL.\n\n"
        "Input: { ptc_hold_current_a, ptc_trip_current_a, load_current_a, "
        "ptc_resistance_ohm, supply_voltage_v, ambient_temp_c?, "
        "ptc_hold_temp_ref_c?, ptc_temp_derating_pct_per_c? }\n"
        "Returns: { ok, hold_current_derated_a, trip_current_derated_a, "
        "load_within_hold, will_trip, steady_state_power_w, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ptc_hold_current_a": {"type": "number", "description": "Hold current at reference temperature [A]."},
            "ptc_trip_current_a": {"type": "number", "description": "Trip current at reference temperature [A]."},
            "load_current_a": {"type": "number", "description": "Normal load current [A]."},
            "ptc_resistance_ohm": {"type": "number", "description": "PTC resistance at hold condition [Ω]."},
            "supply_voltage_v": {"type": "number", "description": "Supply voltage [V]."},
            "ambient_temp_c": {"type": "number", "description": "Ambient temperature [°C] (default 25)."},
            "ptc_hold_temp_ref_c": {"type": "number", "description": "Reference temperature for hold/trip spec [°C] (default 25)."},
            "ptc_temp_derating_pct_per_c": {"type": "number", "description": "Derating rate [%/°C] (default 0.5)."},
        },
        "required": [
            "ptc_hold_current_a", "ptc_trip_current_a", "load_current_a",
            "ptc_resistance_ohm", "supply_voltage_v",
        ],
    },
)


@register(_PTC_SPEC, write=False)
async def protection_ptc_resettable(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = ptc_resettable(
        ptc_hold_current_a=a.get("ptc_hold_current_a"),
        ptc_trip_current_a=a.get("ptc_trip_current_a"),
        load_current_a=a.get("load_current_a"),
        ptc_resistance_ohm=a.get("ptc_resistance_ohm"),
        supply_voltage_v=a.get("supply_voltage_v"),
        ambient_temp_c=a.get("ambient_temp_c", 25.0),
        ptc_hold_temp_ref_c=a.get("ptc_hold_temp_ref_c", 25.0),
        ptc_temp_derating_pct_per_c=a.get("ptc_temp_derating_pct_per_c", 0.5),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. protection_breaker_coordination
# ═══════════════════════════════════════════════════════════════════════════════

_BREAKER_COORD_SPEC = ToolSpec(
    name="protection_breaker_coordination",
    description=(
        "Fuse / breaker time-current coordination — selectivity ratio check.\n\n"
        "For discrimination: upstream trip current / downstream trip current must "
        "be ≥ selectivity_ratio_min (default 1.6) AND the downstream device must "
        "clear before the upstream device.\n\n"
        "Warnings: UNCOORDINATED, PARTIAL_COORDINATION.\n\n"
        "Input: { upstream_trip_current_a, downstream_trip_current_a, "
        "upstream_trip_time_s, downstream_trip_time_s, selectivity_ratio_min? }\n"
        "Returns: { ok, selectivity_ratio, ratio_ok, time_ok, coordinated, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "upstream_trip_current_a": {"type": "number", "description": "Upstream device trip current [A]."},
            "downstream_trip_current_a": {"type": "number", "description": "Downstream device trip current [A]."},
            "upstream_trip_time_s": {"type": "number", "description": "Upstream device trip time at fault [s]."},
            "downstream_trip_time_s": {"type": "number", "description": "Downstream device trip time at fault [s]."},
            "selectivity_ratio_min": {"type": "number", "description": "Minimum selectivity ratio (default 1.6)."},
        },
        "required": [
            "upstream_trip_current_a", "downstream_trip_current_a",
            "upstream_trip_time_s", "downstream_trip_time_s",
        ],
    },
)


@register(_BREAKER_COORD_SPEC, write=False)
async def protection_breaker_coordination(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = breaker_coordination(
        upstream_trip_current_a=a.get("upstream_trip_current_a"),
        downstream_trip_current_a=a.get("downstream_trip_current_a"),
        upstream_trip_time_s=a.get("upstream_trip_time_s"),
        downstream_trip_time_s=a.get("downstream_trip_time_s"),
        selectivity_ratio_min=a.get("selectivity_ratio_min", 1.6),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. protection_onderdonk_trace_fuse
# ═══════════════════════════════════════════════════════════════════════════════

_ONDERDONK_SPEC = ToolSpec(
    name="protection_onderdonk_trace_fuse",
    description=(
        "PCB copper trace fusing current from Onderdonk's equation.\n\n"
        "Formula: I_fuse = A[cmil] × sqrt(ΔT / (33 × t))\n"
        "where A = cross-sectional area [circular mils], ΔT = melting − ambient [°C], "
        "t = fusing time [s].\n\n"
        "Typical copper thicknesses: 35 μm = 1 oz, 70 μm = 2 oz, 105 μm = 3 oz.\n\n"
        "Input: { trace_width_mm, trace_thickness_um, fusing_time_s, "
        "ambient_temp_c?, melting_temp_c? }\n"
        "Returns: { ok, cross_section_mm2, cross_section_cmil, fusing_current_a }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trace_width_mm": {"type": "number", "description": "Trace width [mm]."},
            "trace_thickness_um": {"type": "number", "description": "Copper thickness [μm] (35=1oz, 70=2oz)."},
            "fusing_time_s": {"type": "number", "description": "Time from fault onset to fuse [s]."},
            "ambient_temp_c": {"type": "number", "description": "Ambient temperature [°C] (default 25)."},
            "melting_temp_c": {"type": "number", "description": "Copper melting point [°C] (default 1085)."},
        },
        "required": ["trace_width_mm", "trace_thickness_um", "fusing_time_s"],
    },
)


@register(_ONDERDONK_SPEC, write=False)
async def protection_onderdonk_trace_fuse(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = onderdonk_trace_fuse(
        trace_width_mm=a.get("trace_width_mm"),
        trace_thickness_um=a.get("trace_thickness_um"),
        fusing_time_s=a.get("fusing_time_s"),
        ambient_temp_c=a.get("ambient_temp_c", 25.0),
        melting_temp_c=a.get("melting_temp_c", 1085.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. protection_wire_ampacity
# ═══════════════════════════════════════════════════════════════════════════════

_WIRE_AMP_SPEC = ToolSpec(
    name="protection_wire_ampacity",
    description=(
        "Wire ampacity protection check per NEC 310.16 copper table.\n\n"
        "Applies ambient-temperature correction factor and optionally checks that "
        "the overcurrent device rating does not exceed the derated wire ampacity.\n\n"
        "Supported AWG: 30, 28, 26, 24, 22, 20, 18, 16, 14, 12, 10, 8, 6, 4, 2, 0.\n\n"
        "Warnings: WIRE_UNDERSIZED, FUSE_OVERSIZED_FOR_WIRE.\n\n"
        "Input: { awg, load_current_a, wire_length_m, ambient_temp_c?, "
        "insulation_temp_c?, fuse_rating_a? }\n"
        "Returns: { ok, base_ampacity_a, derated_ampacity_a, ampacity_ok, "
        "voltage_drop_v, fuse_ok, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "awg": {"type": "integer", "description": "AWG wire gauge."},
            "load_current_a": {"type": "number", "description": "Load current [A]."},
            "wire_length_m": {"type": "number", "description": "One-way wire run length [m]."},
            "ambient_temp_c": {"type": "number", "description": "Ambient temperature [°C] (default 30)."},
            "insulation_temp_c": {"type": "number", "description": "Insulation temperature rating [°C] (default 60)."},
            "fuse_rating_a": {"type": "number", "description": "Overcurrent device rating [A] (optional)."},
        },
        "required": ["awg", "load_current_a", "wire_length_m"],
    },
)


@register(_WIRE_AMP_SPEC, write=False)
async def protection_wire_ampacity(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = wire_ampacity(
        awg=a.get("awg"),
        load_current_a=a.get("load_current_a"),
        wire_length_m=a.get("wire_length_m"),
        ambient_temp_c=a.get("ambient_temp_c", 30.0),
        insulation_temp_c=a.get("insulation_temp_c", 60.0),
        fuse_rating_a=a.get("fuse_rating_a"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_FUSE_SELECT_SPEC.name,    _FUSE_SELECT_SPEC,    protection_fuse_select),
    (_INRUSH_NTC_SPEC.name,     _INRUSH_NTC_SPEC,     protection_inrush_ntc_size),
    (_TVS_MOV_SPEC.name,        _TVS_MOV_SPEC,        protection_tvs_mov_clamp),
    (_REV_POL_SPEC.name,        _REV_POL_SPEC,        protection_reverse_polarity),
    (_EFUSE_SPEC.name,          _EFUSE_SPEC,          protection_efuse_trip),
    (_PTC_SPEC.name,            _PTC_SPEC,            protection_ptc_resettable),
    (_BREAKER_COORD_SPEC.name,  _BREAKER_COORD_SPEC,  protection_breaker_coordination),
    (_ONDERDONK_SPEC.name,      _ONDERDONK_SPEC,      protection_onderdonk_trace_fuse),
    (_WIRE_AMP_SPEC.name,       _WIRE_AMP_SPEC,       protection_wire_ampacity),
]
