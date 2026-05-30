"""
kerf_horology.tools_spec
========================
ToolSpec definitions and async handlers for the 9 horology LLM tools.

Wraps the pure-Python computation functions in kerf_horology.tools
and presents them via the standard Kerf ToolSpec / ctx.tools.register pattern.

Tools
-----
horology_train_calculator
horology_check_tooth_profile
horology_escapement_geometry
horology_mainspring_torque
horology_power_reserve
horology_balance_period
horology_isochronism
horology_train_ratios        (new — Daniels §6.1 train analysis)
horology_design_train        (new — inverse design for target BPH)
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_horology._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_horology.tools import (
    _train_calculator,
    _check_tooth_profile,
    _escapement_geometry,
    _mainspring_torque_tool,
    _power_reserve_tool,
    _balance_period_tool,
    _isochronism_tool,
)
from kerf_horology.train_ratio import (
    Wheel,
    compute_train_ratios,
    compute_beat_rate,
    design_train_for_beat_rate,
    power_reserve_estimate,
)


# ---------------------------------------------------------------------------
# 1. train_calculator
# ---------------------------------------------------------------------------

horology_train_calculator_spec = ToolSpec(
    name="horology_train_calculator",
    description=(
        "Compute the required gear-train ratio and barrel power storage for a "
        "mechanical watch movement given target balance frequency and power reserve. "
        "Returns required_ratio, barrel_turns_stored, a 3-stage wheel/pinion "
        "factorisation, achieved_ratio, and ratio_error_pct."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {
                "type": "number",
                "description": "Balance-wheel frequency in Hz (e.g. 4.0 for 28800 bph).",
            },
            "power_reserve_hours": {
                "type": "number",
                "description": "Required power reserve in hours (e.g. 48).",
            },
            "escape_wheel_teeth": {
                "type": "integer",
                "description": "Escape-wheel tooth count (default 15, Swiss lever standard).",
            },
            "barrel_turns_per_day": {
                "type": "number",
                "description": "Mainspring barrel turns per 24-hour day (default 7.5).",
            },
        },
        "required": ["freq_hz", "power_reserve_hours"],
    },
)


async def run_horology_train_calculator(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        result = _train_calculator(
            freq_hz=float(args["freq_hz"]),
            power_reserve_hours=float(args["power_reserve_hours"]),
            escape_wheel_teeth=int(args.get("escape_wheel_teeth", 15)),
            barrel_turns_per_day=float(args.get("barrel_turns_per_day", 7.5)),
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")


# ---------------------------------------------------------------------------
# 2. check_tooth_profile
# ---------------------------------------------------------------------------

horology_check_tooth_profile_spec = ToolSpec(
    name="horology_check_tooth_profile",
    description=(
        "Validate the involute tooth profile geometry for a gear given module, "
        "tooth count, and pressure angle. Returns passed (bool), failure reasons, "
        "base-circle radius, pitch radius, and tip radius."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "module": {
                "type": "number",
                "description": "Tooth module in mm (pitch_diameter / num_teeth).",
            },
            "num_teeth": {
                "type": "integer",
                "description": "Number of teeth on the gear.",
            },
            "pressure_angle_deg": {
                "type": "number",
                "description": "Pressure angle in degrees (default 20.0, standard for Swiss watches).",
            },
        },
        "required": ["module", "num_teeth"],
    },
)


async def run_horology_check_tooth_profile(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        result = _check_tooth_profile(
            module=float(args["module"]),
            num_teeth=int(args["num_teeth"]),
            pressure_angle_deg=float(args.get("pressure_angle_deg", 20.0)),
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")


# ---------------------------------------------------------------------------
# 3. escapement_geometry
# ---------------------------------------------------------------------------

horology_escapement_geometry_spec = ToolSpec(
    name="horology_escapement_geometry",
    description=(
        "Compute Swiss lever escapement geometry: tooth pitch, draw angle, lift angle, "
        "drop, entry/exit pallet angles, impulse force at balance (mN), energy per "
        "impulse (µJ), and a self-consistency check. "
        "Default parameters model the canonical ETA 2824-2 escapement."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "escape_teeth": {
                "type": "integer",
                "description": "Number of teeth on the escape wheel (default 15).",
            },
            "lift_deg": {
                "type": "number",
                "description": "Total lever lift angle in degrees (default 8.0; typical 8–12).",
            },
            "draw_deg": {
                "type": "number",
                "description": "Draw angle on locking faces in degrees (default 12.0; typical 10–14).",
            },
            "escape_wheel_radius_mm": {
                "type": "number",
                "description": "Pitch-circle radius of the escape wheel in mm (default 1.925).",
            },
            "lever_arm_mm": {
                "type": "number",
                "description": "Distance from pallet pivot to pallet stone impulse point in mm (default 1.6).",
            },
            "escape_wheel_torque_Nmm": {
                "type": "number",
                "description": "Torque at the escape-wheel arbor in N·mm (default 0.35).",
            },
        },
        "required": [],
    },
)


async def run_horology_escapement_geometry(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        result = _escapement_geometry(
            escape_teeth=int(args.get("escape_teeth", 15)),
            lift_deg=float(args.get("lift_deg", 8.0)),
            draw_deg=float(args.get("draw_deg", 12.0)),
            escape_wheel_radius_mm=float(args.get("escape_wheel_radius_mm", 1.925)),
            lever_arm_mm=float(args.get("lever_arm_mm", 1.6)),
            escape_wheel_torque_Nmm=float(args.get("escape_wheel_torque_Nmm", 0.35)),
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")


# ---------------------------------------------------------------------------
# 4. mainspring_torque
# ---------------------------------------------------------------------------

horology_mainspring_torque_spec = ToolSpec(
    name="horology_mainspring_torque",
    description=(
        "Return mainspring barrel torque (N·mm) at a given winding state using "
        "the linear torque model. Also returns the winding state as a 0–1 fraction."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "turns": {
                "type": "number",
                "description": "Current winding state (0 = run down, full_turns = fully wound).",
            },
            "full_turns": {
                "type": "number",
                "description": "Total barrel turns from run-down to fully wound.",
            },
            "max_torque_Nmm": {
                "type": "number",
                "description": "Torque at full wind (N·mm).",
            },
            "residual_factor": {
                "type": "number",
                "description": "Fraction of max_torque remaining at zero turns (default 0.5).",
            },
        },
        "required": ["turns", "full_turns", "max_torque_Nmm"],
    },
)


async def run_horology_mainspring_torque(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        result = _mainspring_torque_tool(
            turns=float(args["turns"]),
            full_turns=float(args["full_turns"]),
            max_torque_Nmm=float(args["max_torque_Nmm"]),
            residual_factor=float(args.get("residual_factor", 0.5)),
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")


# ---------------------------------------------------------------------------
# 5. power_reserve
# ---------------------------------------------------------------------------

horology_power_reserve_spec = ToolSpec(
    name="horology_power_reserve",
    description=(
        "Estimate usable power reserve in hours from mainspring parameters and "
        "gear-train ratio. Models the ETA 2824-2 calibre (28800 bph, ~38h reserve) "
        "when given its published specs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "barrel_turns": {
                "type": "number",
                "description": "Winding state at start (= full_turns for fully wound spring).",
            },
            "escape_train_torque_required_Nmm": {
                "type": "number",
                "description": "Minimum escape-wheel torque threshold (N·mm) at the escape wheel.",
            },
            "gear_ratio": {
                "type": "number",
                "description": "Gear ratio barrel → escape-wheel (typically 3000–6000).",
            },
            "beats_per_hour_val": {
                "type": "integer",
                "description": "Beat rate (e.g. 28800 for ETA 2824-2).",
            },
            "full_turns": {
                "type": "number",
                "description": "Mainspring full-wind turns.",
            },
            "max_torque_Nmm": {
                "type": "number",
                "description": "Torque at full wind (N·mm).",
            },
            "residual_factor": {
                "type": "number",
                "description": "Residual torque fraction (default 0.5).",
            },
            "escape_wheel_teeth": {
                "type": "integer",
                "description": "Number of teeth on the escape wheel (default 15).",
            },
        },
        "required": [
            "barrel_turns", "escape_train_torque_required_Nmm",
            "gear_ratio", "beats_per_hour_val", "full_turns", "max_torque_Nmm",
        ],
    },
)


async def run_horology_power_reserve(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        result = _power_reserve_tool(
            barrel_turns=float(args["barrel_turns"]),
            escape_train_torque_required_Nmm=float(args["escape_train_torque_required_Nmm"]),
            gear_ratio=float(args["gear_ratio"]),
            beats_per_hour_val=int(args["beats_per_hour_val"]),
            full_turns=float(args["full_turns"]),
            max_torque_Nmm=float(args["max_torque_Nmm"]),
            residual_factor=float(args.get("residual_factor", 0.5)),
            escape_wheel_teeth=int(args.get("escape_wheel_teeth", 15)),
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")


# ---------------------------------------------------------------------------
# 6. balance_period
# ---------------------------------------------------------------------------

horology_balance_period_spec = ToolSpec(
    name="horology_balance_period",
    description=(
        "Compute balance-wheel oscillation period (seconds) and beat rate (bph) "
        "from moment of inertia and hairspring stiffness. "
        "For ETA 2824-2: I=10 g·mm², k≈6318 N·mm/rad → T=0.25 s, bph=28800."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "I_balance_gmm2": {
                "type": "number",
                "description": "Moment of inertia of the balance (g·mm²).",
            },
            "k_hairspring_Nmmrad": {
                "type": "number",
                "description": "Hairspring torsional stiffness (N·mm/rad).",
            },
        },
        "required": ["I_balance_gmm2", "k_hairspring_Nmmrad"],
    },
)


async def run_horology_balance_period(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        result = _balance_period_tool(
            I_balance_gmm2=float(args["I_balance_gmm2"]),
            k_hairspring_Nmmrad=float(args["k_hairspring_Nmmrad"]),
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")


# ---------------------------------------------------------------------------
# 7. isochronism
# ---------------------------------------------------------------------------

horology_isochronism_spec = ToolSpec(
    name="horology_isochronism",
    description=(
        "Check isochronism of the balance-hairspring oscillator over an amplitude "
        "range. Returns period, beat rate, delta_period_ms (ideal SHO = 0), "
        "rate_sensitivity (s/day per degree amplitude change), is_isochronous, "
        "and diagnostic notes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "I_balance_gmm2": {
                "type": "number",
                "description": "Balance moment of inertia (g·mm²).",
            },
            "k_hairspring_Nmmrad": {
                "type": "number",
                "description": "Hairspring stiffness (N·mm/rad).",
            },
            "amp_min_deg": {
                "type": "number",
                "description": "Minimum balance amplitude to test in degrees (default 180).",
            },
            "amp_max_deg": {
                "type": "number",
                "description": "Maximum balance amplitude to test in degrees (default 300).",
            },
        },
        "required": ["I_balance_gmm2", "k_hairspring_Nmmrad"],
    },
)


async def run_horology_isochronism(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        result = _isochronism_tool(
            I_balance_gmm2=float(args["I_balance_gmm2"]),
            k_hairspring_Nmmrad=float(args["k_hairspring_Nmmrad"]),
            amp_min_deg=float(args.get("amp_min_deg", 180.0)),
            amp_max_deg=float(args.get("amp_max_deg", 300.0)),
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")


# ---------------------------------------------------------------------------
# 8. horology_train_ratios  (Daniels §6.1 gear-train ratio analysis)
# ---------------------------------------------------------------------------

horology_train_ratios_spec = ToolSpec(
    name="horology_train_ratios",
    description=(
        "Analyse a mechanical watch gear train: compute per-stage ratios, "
        "total train ratio (barrel → escape wheel), arbor speeds (rev/hr), "
        "and beat rate (BPH).  Follows Daniels §6.1 (Watchmaking, 1981). "
        "Input is an ordered list of wheel descriptions from barrel to escape wheel. "
        "Each entry has a name, teeth count, and optionally pinion_leaves (the pinion "
        "on that arbor driven by the previous wheel).  The barrel has no pinion; the "
        "escape wheel pinion is driven by the fourth wheel."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wheels": {
                "type": "array",
                "description": (
                    "Ordered list of arbors from barrel to escape wheel.  "
                    "Each item: {name, teeth, pinion_leaves?}.  "
                    "Example: [{name:'barrel',teeth:80}, {name:'center_wheel',teeth:80,pinion_leaves:12}, "
                    "{name:'escape_wheel',teeth:15,pinion_leaves:7}]"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "teeth": {"type": "integer"},
                        "pinion_leaves": {"type": "integer"},
                    },
                    "required": ["name", "teeth"],
                },
            },
            "barrel_rev_per_hr": {
                "type": "number",
                "description": (
                    "Mainspring barrel rotation speed in revolutions per hour.  "
                    "Default 0.125 (1/8 RPH — barrel completes 1 revolution every 8 hours)."
                ),
            },
        },
        "required": ["wheels"],
    },
)


async def run_horology_train_ratios(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        raw_wheels = args["wheels"]
        wheels = [
            Wheel(
                name=str(w["name"]),
                teeth=int(w["teeth"]),
                pinion_leaves=int(w["pinion_leaves"]) if "pinion_leaves" in w else None,
            )
            for w in raw_wheels
        ]
        barrel_rph = float(args.get("barrel_rev_per_hr", 1.0 / 8.0))
        result = compute_train_ratios(wheels, barrel_rev_per_hr=barrel_rph)
        payload = {
            "total_ratio": round(result.total_ratio, 6),
            "beat_rate_bph": round(result.beat_rate_bph, 3),
            "is_valid": result.is_valid,
            "validation_errors": result.validation_errors,
            "stages": [
                {
                    "driving_wheel": s.driving_wheel,
                    "driven_pinion": s.driven_pinion,
                    "wheel_teeth": s.wheel_teeth,
                    "pinion_leaves": s.pinion_leaves,
                    "ratio": round(s.ratio, 6),
                }
                for s in result.stages
            ],
            "arbor_speeds_rev_per_hr": {
                k: round(v, 6) for k, v in result.arbor_speeds_rev_per_hr.items()
            },
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")


# ---------------------------------------------------------------------------
# 9. horology_design_train  (inverse design — target BPH → wheel configuration)
# ---------------------------------------------------------------------------

horology_design_train_spec = ToolSpec(
    name="horology_design_train",
    description=(
        "Design a mechanical watch gear train for a target beat rate (BPH).  "
        "Inverts the Daniels §6.1 formula to find integer wheel/pinion counts "
        "in practical ranges (pinion 6–12 leaves, wheel 60–130 teeth) whose "
        "product matches the required train ratio within 5%.  "
        "Standard beat rates: 18000 (vintage), 21600 (mid), 28800 (modern, ETA 2824-2), "
        "36000 (high-beat, Seiko 9SA5).  "
        "Returns the wheel list and the achieved beat rate."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_bph": {
                "type": "number",
                "description": (
                    "Target beat rate in beats per hour.  "
                    "Standard values: 18000, 21600, 28800, 36000."
                ),
            },
            "mainspring_rev_per_hr": {
                "type": "number",
                "description": (
                    "Mainspring barrel rotation speed in rev/hr.  "
                    "Default 0.125 (= 1/8 RPH, barrel makes 1 revolution every 8 hours).  "
                    "Use 0.3125 for 7.5 turns/day (kerf-partsgen convention)."
                ),
            },
            "escape_wheel_teeth": {
                "type": "integer",
                "description": "Number of teeth on the escape wheel.  Default 15 (Swiss lever standard).",
            },
            "n_stages": {
                "type": "integer",
                "description": "Number of wheel/pinion stages.  Default 3.",
            },
        },
        "required": ["target_bph"],
    },
)


async def run_horology_design_train(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        target_bph = float(args["target_bph"])
        barrel_rph = float(args.get("mainspring_rev_per_hr", 1.0 / 8.0))
        escape_teeth = int(args.get("escape_wheel_teeth", 15))
        n_stages = int(args.get("n_stages", 3))

        wheels = design_train_for_beat_rate(
            target_bph=target_bph,
            mainspring_rev_per_hr=barrel_rph,
            escape_wheel_teeth=escape_teeth,
            n_stages=n_stages,
        )
        result = compute_train_ratios(wheels, barrel_rev_per_hr=barrel_rph)

        payload = {
            "target_bph": target_bph,
            "achieved_bph": round(result.beat_rate_bph, 3),
            "deviation_pct": round(
                abs(result.beat_rate_bph - target_bph) / target_bph * 100, 3
            ),
            "total_ratio": round(result.total_ratio, 6),
            "is_valid": result.is_valid,
            "validation_errors": result.validation_errors,
            "wheels": [
                {
                    "name": w.name,
                    "teeth": w.teeth,
                    "pinion_leaves": w.pinion_leaves,
                }
                for w in wheels
            ],
            "stages": [
                {
                    "driving_wheel": s.driving_wheel,
                    "driven_pinion": s.driven_pinion,
                    "wheel_teeth": s.wheel_teeth,
                    "pinion_leaves": s.pinion_leaves,
                    "ratio": round(s.ratio, 6),
                }
                for s in result.stages
            ],
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "HOROLOGY_ERROR")
