"""
Electrical safety, grounding, isolation and arc-flash LLM tools.

Provides twelve LLM-callable tools:

  elecsafety_pe_conductor_size   — PE/EGC adiabatic conductor sizing (IEC 60364-5-54)
  elecsafety_bonding_resistance  — Bonding resistance / GPR check
  elecsafety_ground_electrode    — Ground rod / plate / grid resistance (IEEE 80)
  elecsafety_gpr                 — Ground potential rise
  elecsafety_touch_step_voltage  — Permissible touch/step voltage (IEC 60479/IEEE 80)
  elecsafety_creepage_clearance  — Creepage and clearance (IEC 60664-1)
  elecsafety_insulation_hipot    — Hi-pot test voltage (IEC 60664-1 / 62368-1)
  elecsafety_leakage_limit       — Leakage/touch current limits (IEC 60601/60950)
  elecsafety_rcd_threshold       — RCD/GFCI trip threshold (IEC 61008 / UL 943)
  elecsafety_arc_flash           — Arc-flash incident energy & boundary (IEEE 1584)
  elecsafety_wire_ampacity       — Wire ampacity with temperature derating
  elecsafety_selv_pelv           — SELV/PELV threshold check (IEC 61140)

All handlers follow the kerf never-raise contract: errors → {"ok": false, "reason": ...}.
Hazard flags and limit exceedances are reported via warnings.warn (never raise).

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.elecsafety.safety import (
    arc_flash_incident_energy,
    bonding_resistance_check,
    creepage_clearance,
    ground_electrode_resistance,
    ground_potential_rise,
    insulation_hipot,
    leakage_touch_current_limit,
    protective_earth_conductor_size,
    rcd_gfci_threshold,
    selv_pelv_check,
    touch_step_voltage,
    wire_ampacity,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. elecsafety_pe_conductor_size
# ═══════════════════════════════════════════════════════════════════════════════

_PE_COND_SPEC = ToolSpec(
    name="elecsafety_pe_conductor_size",
    description=(
        "Minimum protective-earth (PE) / equipment-grounding conductor (EGC) "
        "cross-sectional area using the adiabatic equation from IEC 60364-5-54 §543.1:\n\n"
        "  A [mm²] = I × √t / k\n\n"
        "where k = 115 (copper), 76 (aluminium), 52 (steel).\n\n"
        "Input: { fault_current_a, fault_duration_s, material? }\n"
        "Returns: { ok, area_min_mm2, material, k, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fault_current_a": {
                "type": "number",
                "description": "Prospective fault current [A] (RMS symmetrical).",
            },
            "fault_duration_s": {
                "type": "number",
                "description": "Fault clearing time [s].",
            },
            "material": {
                "type": "string",
                "enum": ["copper", "aluminium", "steel"],
                "description": "Conductor material (default 'copper').",
            },
        },
        "required": ["fault_current_a", "fault_duration_s"],
    },
)


@register(_PE_COND_SPEC, write=False)
async def elecsafety_pe_conductor_size(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = protective_earth_conductor_size(
        fault_current_a=a.get("fault_current_a"),
        fault_duration_s=a.get("fault_duration_s"),
        material=a.get("material", "copper"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. elecsafety_bonding_resistance
# ═══════════════════════════════════════════════════════════════════════════════

_BONDING_SPEC = ToolSpec(
    name="elecsafety_bonding_resistance",
    description=(
        "Bonding conductor resistance check for equipotential bonding.\n\n"
        "GPR = I_fault × R_bond.  Flags when GPR > safe touch voltage "
        "(default 50 V AC per IEC 60364-4-41 §411.3.2).\n\n"
        "Input: { fault_current_a, bond_resistance_ohm, safe_touch_voltage_v? }\n"
        "Returns: { ok, gpr_v, gpr_hazard, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fault_current_a": {
                "type": "number",
                "description": "Maximum fault current through the bond [A].",
            },
            "bond_resistance_ohm": {
                "type": "number",
                "description": "Measured bonding conductor resistance [Ω].",
            },
            "safe_touch_voltage_v": {
                "type": "number",
                "description": "Permissible touch voltage [V] (default 50 V AC).",
            },
        },
        "required": ["fault_current_a", "bond_resistance_ohm"],
    },
)


@register(_BONDING_SPEC, write=False)
async def elecsafety_bonding_resistance(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = bonding_resistance_check(
        fault_current_a=a.get("fault_current_a"),
        bond_resistance_ohm=a.get("bond_resistance_ohm"),
        safe_touch_voltage_v=a.get("safe_touch_voltage_v", 50.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. elecsafety_ground_electrode
# ═══════════════════════════════════════════════════════════════════════════════

_GND_ELECTRODE_SPEC = ToolSpec(
    name="elecsafety_ground_electrode",
    description=(
        "Ground electrode resistance: vertical rod (Dwight), plate, or Schwarz grid.\n\n"
        "Rod   (IEEE 80-2013 §14.1): R = ρ/(2πL) × [ln(4L/a) − 1]\n"
        "Plate (IEEE 80-2013 §14.3): R = ρ/(8r), r = √(area/π)\n"
        "Grid  (IEEE 80-2013 §14.2): Schwarz simplified formula\n\n"
        "Input: { electrode_type, soil_resistivity_ohm_m, length_m?, radius_m?, "
        "area_m2?, grid_area_m2?, grid_total_conductor_m?, grid_num_meshes? }\n"
        "Returns: { ok, resistance_ohm, electrode_type, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "electrode_type": {
                "type": "string",
                "enum": ["rod", "plate", "grid"],
                "description": "Electrode geometry.",
            },
            "soil_resistivity_ohm_m": {
                "type": "number",
                "description": "Soil resistivity ρ [Ω·m].",
            },
            "length_m": {
                "type": "number",
                "description": "Rod length [m] (rod only, default 3 m).",
            },
            "radius_m": {
                "type": "number",
                "description": "Rod radius [m] (rod only, default 7.9 mm).",
            },
            "area_m2": {
                "type": "number",
                "description": "Plate area [m²] (plate only, default 1 m²).",
            },
            "grid_area_m2": {
                "type": "number",
                "description": "Total grid area [m²] (grid only, default 100 m²).",
            },
            "grid_total_conductor_m": {
                "type": "number",
                "description": "Total conductor length [m] (grid only, default 40 m).",
            },
            "grid_num_meshes": {
                "type": "number",
                "description": "Number of meshes (grid only, default 4).",
            },
        },
        "required": ["electrode_type", "soil_resistivity_ohm_m"],
    },
)


@register(_GND_ELECTRODE_SPEC, write=False)
async def elecsafety_ground_electrode(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = ground_electrode_resistance(
        electrode_type=a.get("electrode_type", "rod"),
        soil_resistivity_ohm_m=a.get("soil_resistivity_ohm_m"),
        length_m=a.get("length_m", 3.0),
        radius_m=a.get("radius_m", 0.0079),
        area_m2=a.get("area_m2", 1.0),
        grid_area_m2=a.get("grid_area_m2", 100.0),
        grid_total_conductor_m=a.get("grid_total_conductor_m", 40.0),
        grid_num_meshes=a.get("grid_num_meshes", 4.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. elecsafety_gpr
# ═══════════════════════════════════════════════════════════════════════════════

_GPR_SPEC = ToolSpec(
    name="elecsafety_gpr",
    description=(
        "Ground potential rise (GPR) during an earth fault.\n\n"
        "GPR = I_fault × R_ground (IEEE 80-2013 §2.2.3).\n"
        "Flags HAZARD when GPR > 1000 V, EXTREME when GPR > 5000 V.\n\n"
        "Input: { fault_current_a, ground_resistance_ohm }\n"
        "Returns: { ok, gpr_v, hazard_level, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fault_current_a": {
                "type": "number",
                "description": "Symmetrical fault current flowing into earth [A].",
            },
            "ground_resistance_ohm": {
                "type": "number",
                "description": "Total ground electrode resistance [Ω].",
            },
        },
        "required": ["fault_current_a", "ground_resistance_ohm"],
    },
)


@register(_GPR_SPEC, write=False)
async def elecsafety_gpr(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = ground_potential_rise(
        fault_current_a=a.get("fault_current_a"),
        ground_resistance_ohm=a.get("ground_resistance_ohm"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. elecsafety_touch_step_voltage
# ═══════════════════════════════════════════════════════════════════════════════

_TOUCH_STEP_SPEC = ToolSpec(
    name="elecsafety_touch_step_voltage",
    description=(
        "Permissible touch and step voltage for a human body model.\n\n"
        "IEC 60479-1:2005 / IEEE 80-2013 §8:\n"
        "  I_body = Cb × 0.116 / √t   (ventricular fibrillation threshold)\n"
        "  V_touch = (1000 + 1.5 × ρs) × I_body\n"
        "  V_step  = (1000 + 6 × ρs)   × I_body\n\n"
        "Input: { fault_current_a, fault_duration_s, surface_layer_resistivity_ohm_m?, "
        "body_weight_kg? }\n"
        "Returns: { ok, v_touch_permissible_v, v_step_permissible_v, "
        "i_body_permissible_a, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fault_current_a": {
                "type": "number",
                "description": "Fault current [A].",
            },
            "fault_duration_s": {
                "type": "number",
                "description": "Fault clearing time [s].",
            },
            "surface_layer_resistivity_ohm_m": {
                "type": "number",
                "description": "Surface layer resistivity [Ω·m] (crushed rock ≈ 2500; default 0).",
            },
            "body_weight_kg": {
                "type": "number",
                "description": "Body weight [kg] (50 or 70; default 70).",
            },
        },
        "required": ["fault_current_a", "fault_duration_s"],
    },
)


@register(_TOUCH_STEP_SPEC, write=False)
async def elecsafety_touch_step_voltage(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = touch_step_voltage(
        fault_current_a=a.get("fault_current_a"),
        fault_duration_s=a.get("fault_duration_s"),
        surface_layer_resistivity_ohm_m=a.get("surface_layer_resistivity_ohm_m", 0.0),
        body_weight_kg=a.get("body_weight_kg", 70.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. elecsafety_creepage_clearance
# ═══════════════════════════════════════════════════════════════════════════════

_CREEP_CLEAR_SPEC = ToolSpec(
    name="elecsafety_creepage_clearance",
    description=(
        "Minimum creepage distance and clearance per IEC 60664-1:2007+A1.\n\n"
        "Creepage scales with pollution degree and material group (CTI).\n"
        "Clearance scales with overvoltage category and altitude.\n\n"
        "Input: { working_voltage_v_rms, overvoltage_category?, pollution_degree?, "
        "material_group?, altitude_m?, measured_creepage_mm?, measured_clearance_mm? }\n"
        "Returns: { ok, min_creepage_mm, min_clearance_mm, creepage_ok, clearance_ok, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "working_voltage_v_rms": {
                "type": "number",
                "description": "Working voltage [V RMS or DC].",
            },
            "overvoltage_category": {
                "type": "integer",
                "enum": [1, 2, 3, 4],
                "description": "Overvoltage category (I–IV, default 2).",
            },
            "pollution_degree": {
                "type": "integer",
                "enum": [1, 2, 3, 4],
                "description": "Pollution degree (1–4, default 2).",
            },
            "material_group": {
                "type": "string",
                "enum": ["I", "II", "IIIa", "IIIb"],
                "description": "PCB/insulator material group by CTI (default 'II').",
            },
            "altitude_m": {
                "type": "number",
                "description": "Installation altitude [m] (default 2000 m = no correction).",
            },
            "measured_creepage_mm": {
                "type": "number",
                "description": "Actual creepage on PCB [mm] (0 = skip check).",
            },
            "measured_clearance_mm": {
                "type": "number",
                "description": "Actual clearance on PCB [mm] (0 = skip check).",
            },
        },
        "required": ["working_voltage_v_rms"],
    },
)


@register(_CREEP_CLEAR_SPEC, write=False)
async def elecsafety_creepage_clearance(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = creepage_clearance(
        working_voltage_v_rms=a.get("working_voltage_v_rms"),
        overvoltage_category=a.get("overvoltage_category", 2),
        pollution_degree=a.get("pollution_degree", 2),
        material_group=a.get("material_group", "II"),
        altitude_m=a.get("altitude_m", 2000.0),
        measured_creepage_mm=a.get("measured_creepage_mm", 0.0),
        measured_clearance_mm=a.get("measured_clearance_mm", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. elecsafety_insulation_hipot
# ═══════════════════════════════════════════════════════════════════════════════

_HIPOT_SPEC = ToolSpec(
    name="elecsafety_insulation_hipot",
    description=(
        "Hi-pot (dielectric withstand) test voltage for basic or reinforced insulation.\n\n"
        "Based on IEC 60664-1:2007 Table F.4 and IEC 62368-1:2018 Annex Q.\n"
        "Reinforced insulation uses 2× the basic test voltage.\n\n"
        "Input: { working_voltage_v_rms, insulation_class?, equipment_class? }\n"
        "Returns: { ok, test_voltage_v_rms, test_voltage_v_peak, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "working_voltage_v_rms": {
                "type": "number",
                "description": "Working voltage [V RMS or DC].",
            },
            "insulation_class": {
                "type": "string",
                "enum": ["basic", "supplementary", "reinforced", "functional"],
                "description": "Insulation class (default 'basic').",
            },
            "equipment_class": {
                "type": "string",
                "enum": ["I", "II", "III"],
                "description": "Equipment class per IEC 61140 (default 'I').",
            },
        },
        "required": ["working_voltage_v_rms"],
    },
)


@register(_HIPOT_SPEC, write=False)
async def elecsafety_insulation_hipot(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = insulation_hipot(
        working_voltage_v_rms=a.get("working_voltage_v_rms"),
        insulation_class=a.get("insulation_class", "basic"),
        equipment_class=a.get("equipment_class", "I"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. elecsafety_leakage_limit
# ═══════════════════════════════════════════════════════════════════════════════

_LEAKAGE_SPEC = ToolSpec(
    name="elecsafety_leakage_limit",
    description=(
        "Permissible leakage / touch current for IEC 60601-1 (medical) and "
        "IEC 62368-1 / IEC 60950-1 (IT/AV) equipment.\n\n"
        "IEC 62368-1 Class I normal: ≤ 3.5 mA; Class II: ≤ 0.25 mA.\n"
        "IEC 60601-1 Class I NC: ≤ 5 mA earth leakage; patient CF: ≤ 10 μA.\n\n"
        "Input: { equipment_class?, application?, connection?, measured_leakage_a? }\n"
        "Returns: { ok, limit_a, limit_ma, compliant, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "equipment_class": {
                "type": "string",
                "enum": ["I", "II", "III"],
                "description": "Equipment class per IEC 61140 (default 'I').",
            },
            "application": {
                "type": "string",
                "enum": ["it", "medical"],
                "description": "'it' for IEC 62368-1 or 'medical' for IEC 60601-1 (default 'it').",
            },
            "connection": {
                "type": "string",
                "description": (
                    "For IT: 'normal'. For medical: 'normal', 'single_fault', "
                    "'patient_B', 'patient_BF', 'patient_CF' (default 'normal')."
                ),
            },
            "measured_leakage_a": {
                "type": "number",
                "description": "Measured leakage current [A] (0 = no check).",
            },
        },
        "required": [],
    },
)


@register(_LEAKAGE_SPEC, write=False)
async def elecsafety_leakage_limit(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = leakage_touch_current_limit(
        equipment_class=a.get("equipment_class", "I"),
        application=a.get("application", "it"),
        connection=a.get("connection", "normal"),
        measured_leakage_a=a.get("measured_leakage_a", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. elecsafety_rcd_threshold
# ═══════════════════════════════════════════════════════════════════════════════

_RCD_SPEC = ToolSpec(
    name="elecsafety_rcd_threshold",
    description=(
        "RCD / GFCI trip threshold check per IEC 61008-1:2010 and UL 943.\n\n"
        "IEC 61008 general: trip at I_Δn, guaranteed no-trip at 0.5 × I_Δn.\n"
        "UL 943 Class A: trip at 6 mA (personnel protection).\n"
        "UL 943 Class B: trip at 20 mA (submersible pumps).\n\n"
        "Input: { rcd_rating_a, measured_leakage_a, device_type? }\n"
        "Returns: { ok, will_trip, margin_a, trip_threshold_a, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "rcd_rating_a": {
                "type": "number",
                "description": "RCD rated residual current I_Δn [A] (e.g. 0.03 for 30 mA).",
            },
            "measured_leakage_a": {
                "type": "number",
                "description": "Measured system leakage current [A].",
            },
            "device_type": {
                "type": "string",
                "enum": ["general", "ul_class_a", "ul_class_b"],
                "description": "RCD/GFCI standard (default 'general' = IEC 61008).",
            },
        },
        "required": ["rcd_rating_a", "measured_leakage_a"],
    },
)


@register(_RCD_SPEC, write=False)
async def elecsafety_rcd_threshold(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = rcd_gfci_threshold(
        rcd_rating_a=a.get("rcd_rating_a"),
        measured_leakage_a=a.get("measured_leakage_a"),
        device_type=a.get("device_type", "general"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. elecsafety_arc_flash
# ═══════════════════════════════════════════════════════════════════════════════

_ARC_FLASH_SPEC = ToolSpec(
    name="elecsafety_arc_flash",
    description=(
        "Arc-flash incident energy and arc-flash boundary per IEEE 1584-2002.\n\n"
        "Two methods:\n"
        "1. Lee theoretical maximum (conservative): E = 793 × V_kV × I_bf × t / D²\n"
        "2. IEEE 1584 empirical: E = 4.184 × Cf × En × (t/0.2) × (610^x / D^x)\n\n"
        "Returns the higher estimate, arc-flash boundary (1.2 cal/cm² onset), and "
        "NFPA 70E-2021 PPE category.\n\n"
        "Input: { system_voltage_v, bolted_fault_current_ka, arcing_duration_s, "
        "working_distance_mm?, electrode_gap_mm?, system_type? }\n"
        "Returns: { ok, incident_energy_cal_cm2, afb_mm, ppe_category, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "system_voltage_v": {
                "type": "number",
                "description": "System voltage [V] (line-to-line for 3-phase).",
            },
            "bolted_fault_current_ka": {
                "type": "number",
                "description": "Symmetrical bolted fault current [kA].",
            },
            "arcing_duration_s": {
                "type": "number",
                "description": "Arc duration / protection clearing time [s].",
            },
            "working_distance_mm": {
                "type": "number",
                "description": "Working distance from arc [mm] (default 455 mm = 18 in).",
            },
            "electrode_gap_mm": {
                "type": "number",
                "description": "Conductor gap [mm] (default 32 mm for MCC bus).",
            },
            "system_type": {
                "type": "string",
                "enum": ["open_air", "enclosure"],
                "description": "Equipment type: 'open_air' or 'enclosure' (default 'open_air').",
            },
        },
        "required": ["system_voltage_v", "bolted_fault_current_ka", "arcing_duration_s"],
    },
)


@register(_ARC_FLASH_SPEC, write=False)
async def elecsafety_arc_flash(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = arc_flash_incident_energy(
        system_voltage_v=a.get("system_voltage_v"),
        bolted_fault_current_ka=a.get("bolted_fault_current_ka"),
        arcing_duration_s=a.get("arcing_duration_s"),
        working_distance_mm=a.get("working_distance_mm", 455.0),
        electrode_gap_mm=a.get("electrode_gap_mm", 32.0),
        system_type=a.get("system_type", "open_air"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. elecsafety_wire_ampacity
# ═══════════════════════════════════════════════════════════════════════════════

_WIRE_AMP_SPEC = ToolSpec(
    name="elecsafety_wire_ampacity",
    description=(
        "Wire ampacity vs insulation temperature rating with ambient temperature derating.\n\n"
        "Derating factor: √((T_max − T_amb) / (T_max − 30°C))\n"
        "(IEC 60364-5-52 §525.1)\n\n"
        "Insulation types: pvc (70°C), xlpe/pvc90/epr (90°C), "
        "ptfe (200°C), silicone (180°C), rubber (60°C).\n\n"
        "Input: { cross_section_mm2, insulation?, ambient_temp_c?, load_current_a? }\n"
        "Returns: { ok, derated_ampacity_a, base_ampacity_a, overloaded, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cross_section_mm2": {
                "type": "number",
                "description": "Conductor cross-section [mm²].",
            },
            "insulation": {
                "type": "string",
                "enum": ["pvc", "pvc90", "xlpe", "epr", "ptfe", "silicone", "rubber"],
                "description": "Insulation type (default 'pvc').",
            },
            "ambient_temp_c": {
                "type": "number",
                "description": "Ambient temperature [°C] (default 30°C).",
            },
            "load_current_a": {
                "type": "number",
                "description": "Actual load current [A] (0 = no overload check).",
            },
        },
        "required": ["cross_section_mm2"],
    },
)


@register(_WIRE_AMP_SPEC, write=False)
async def elecsafety_wire_ampacity(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = wire_ampacity(
        cross_section_mm2=a.get("cross_section_mm2"),
        insulation=a.get("insulation", "pvc"),
        ambient_temp_c=a.get("ambient_temp_c", 30.0),
        load_current_a=a.get("load_current_a", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. elecsafety_selv_pelv
# ═══════════════════════════════════════════════════════════════════════════════

_SELV_PELV_SPEC = ToolSpec(
    name="elecsafety_selv_pelv",
    description=(
        "SELV / PELV threshold check per IEC 61140:2016 and IEC 60364-4-41.\n\n"
        "Limits: AC ≤ 50 V RMS, DC ≤ 120 V (ripple-free).\n"
        "SELV: separated, isolated from earth.  "
        "PELV: extra-low voltage, protective earth permitted.\n\n"
        "Input: { voltage_v_ac_rms?, voltage_v_dc?, circuit_type? }\n"
        "Returns: { ok, is_selv_pelv, borderline, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "voltage_v_ac_rms": {
                "type": "number",
                "description": "AC RMS voltage [V] (0 if DC only).",
            },
            "voltage_v_dc": {
                "type": "number",
                "description": "DC voltage [V] (0 if AC only).",
            },
            "circuit_type": {
                "type": "string",
                "enum": ["SELV", "PELV"],
                "description": "Circuit classification (default 'SELV').",
            },
        },
        "required": [],
    },
)


@register(_SELV_PELV_SPEC, write=False)
async def elecsafety_selv_pelv(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = selv_pelv_check(
        voltage_v_ac_rms=a.get("voltage_v_ac_rms", 0.0),
        voltage_v_dc=a.get("voltage_v_dc", 0.0),
        circuit_type=a.get("circuit_type", "SELV"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_PE_COND_SPEC.name,       _PE_COND_SPEC,       elecsafety_pe_conductor_size),
    (_BONDING_SPEC.name,       _BONDING_SPEC,       elecsafety_bonding_resistance),
    (_GND_ELECTRODE_SPEC.name, _GND_ELECTRODE_SPEC, elecsafety_ground_electrode),
    (_GPR_SPEC.name,           _GPR_SPEC,           elecsafety_gpr),
    (_TOUCH_STEP_SPEC.name,    _TOUCH_STEP_SPEC,    elecsafety_touch_step_voltage),
    (_CREEP_CLEAR_SPEC.name,   _CREEP_CLEAR_SPEC,   elecsafety_creepage_clearance),
    (_HIPOT_SPEC.name,         _HIPOT_SPEC,         elecsafety_insulation_hipot),
    (_LEAKAGE_SPEC.name,       _LEAKAGE_SPEC,       elecsafety_leakage_limit),
    (_RCD_SPEC.name,           _RCD_SPEC,           elecsafety_rcd_threshold),
    (_ARC_FLASH_SPEC.name,     _ARC_FLASH_SPEC,     elecsafety_arc_flash),
    (_WIRE_AMP_SPEC.name,      _WIRE_AMP_SPEC,      elecsafety_wire_ampacity),
    (_SELV_PELV_SPEC.name,     _SELV_PELV_SPEC,     elecsafety_selv_pelv),
]
