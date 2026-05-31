"""
kerf_mold.melt_flow_ratio_check_tool
=====================================
LLM tool wrapper for melt-flow-ratio injection-speed envelope check.

Tool: mold_check_melt_flow_ratio
  Given a polymer's MFR/MVR (ASTM D1238), wall thickness, and gate type,
  determine the recommended injection speed envelope to avoid jetting,
  sink marks, and gate freeze-off.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.,
    Hanser, §4 (Melt flow and injection speed); §7 (Gate design).
  Menges G., Michaeli W., Mohren P. (2001). *How to Make Injection Molds*,
    3rd ed., Hanser, §6.2 (Injection conditions).
  ASTM International. ASTM D1238-23 "Standard Test Method for Melt Flow
    Rates of Thermoplastics by Extrusion Plastometer."
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.melt_flow_ratio_check import (
    MeltFlowSpec,
    check_melt_flow_ratio,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_check_melt_flow_ratio_spec = ToolSpec(
    name="mold_check_melt_flow_ratio",
    description=(
        "Determine the recommended injection-speed envelope for an injection-moulding "
        "process from the polymer's Melt Flow Rate (MFR, ASTM D1238), wall thickness, "
        "and gate type. Returns speed limits to avoid jetting, sink marks, and gate "
        "freeze-off.\n\n"
        "MFR classification (ASTM D1238 g/10 min):\n"
        "  low_MFR_<5          → viscous; speed 5-25 mm/s; high gate-freeze risk\n"
        "  medium_MFR_5-25     → standard engineering grades; 25-75 mm/s\n"
        "  high_MFR_25-100     → thin-wall free-flow grades; 50-150 mm/s\n"
        "  super_high_MFR_>100 → ultra-thin wall; 80-200 mm/s\n\n"
        "Wall thickness adjustments (Beaumont 2007 §4.3 Table 4.1):\n"
        "  wall < 1.5 mm  → upper bound +30 % (avoid short-shot / freeze)\n"
        "  wall 1.5-3 mm  → baseline\n"
        "  wall 3-4 mm    → lower bound -20 %\n"
        "  wall > 4 mm    → both bounds -25 % (slow fill; jetting + shear heat)\n\n"
        "Gate type adjustments (Beaumont 2007 §7; Menges 2001 §6.6):\n"
        "  edge_gate / pin_gate    → baseline\n"
        "  fan_gate / film_gate    → upper bound +20 % (flow distribution)\n"
        "  hot_tip / hot_runner    → lower bound -10 %, upper +10 %\n"
        "  submarine_gate          → lower bound +10 % (shear-sensitive)\n\n"
        "Risk outputs:\n"
        "  gate_freeze_risk — inversely proportional to MFR\n"
        "  jetting_risk     — high for pin/edge gate + high MFR; low for fan/film\n"
        "  sink_mark_risk   — wall > 4 mm → high; 2.5-4 mm → medium\n\n"
        "Returns: {mfr_classification, recommended_injection_speed_mm_per_s,\n"
        "          gate_freeze_risk, jetting_risk, sink_mark_risk, honest_caveat}.\n\n"
        "HONEST CAVEAT: heuristic speed envelope only — NOT a mold-flow simulation. "
        "MFR is a single-point viscosity proxy at one shear rate (ASTM D1238). "
        "Validate on-tool via a short-shot DOE with cavity-pressure measurement. "
        "Real speed optimisation requires the full shear-thinning viscosity curve, "
        "cavity geometry, gate dimensions, and machine hydraulic response."
    ),
    input_schema={
        "type": "object",
        "required": [
            "polymer_grade",
            "mfr_g_per_10min",
            "wall_thickness_mm",
            "gate_type",
            "melt_temp_C",
            "mold_temp_C",
        ],
        "properties": {
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer commercial grade name (e.g., 'PC', 'PP-H', 'ABS'). "
                    "Used for reporting context only; the speed envelope is driven "
                    "by the numeric MFR value."
                ),
            },
            "mfr_g_per_10min": {
                "type": "number",
                "description": (
                    "Melt Flow Rate (MFR) measured per ASTM D1238 (or ISO 1133) "
                    "at the standard test condition for the polymer, in g/10 min. "
                    "Must be > 0. Typical values: HDPE pipe ~0.3; PP injection 12-40; "
                    "ABS 10-30; PC 4-22; PA66 13-60; LCP > 100."
                ),
                "exclusiveMinimum": 0,
            },
            "wall_thickness_mm": {
                "type": "number",
                "description": (
                    "Nominal wall thickness of the part [mm]. Must be > 0. "
                    "Drives the wall-thickness speed correction and sink-mark risk: "
                    "< 1.5 mm → thin wall (upper speed +30 %); > 4 mm → thick wall "
                    "(both bounds -25 %) + high sink-mark risk "
                    "(Beaumont 2007 §4.3 Table 4.1; §4.6 Table 4.5)."
                ),
                "exclusiveMinimum": 0,
            },
            "gate_type": {
                "type": "string",
                "description": (
                    "Gate geometry/type. Supported values (case-insensitive):\n"
                    "'pin_gate'       — small circular gate; jetting risk for high-MFR\n"
                    "'edge_gate'      — side gate at parting line; most common cold runner\n"
                    "'fan_gate'       — widening fan land; distributes flow, lower jet risk\n"
                    "'film_gate'      — very wide thin film; lowest jetting risk\n"
                    "'hot_tip'        — hot-runner direct tip; wider speed window\n"
                    "'hot_runner'     — hot-runner system\n"
                    "'submarine_gate' — curved sub-gate; shear-sensitive\n"
                    "'sprue_gate'     — large direct sprue; low jetting risk\n"
                    "'tab_gate'       — offset tab reduces cosmetic gate mark\n"
                    "'diaphragm_gate' — annular gate for tubular parts\n"
                    "Unknown types use baseline factors with a caveat."
                ),
            },
            "melt_temp_C": {
                "type": "number",
                "description": (
                    "Melt temperature at the nozzle [deg C]. Must be > 0. "
                    "Used for reporting context; temperature interaction with MFR "
                    "requires the full viscosity curve for quantitative correction. "
                    "Typical ranges: PP 220-280 deg C, ABS 230-260 deg C, PC 280-320 deg C."
                ),
                "exclusiveMinimum": 0,
            },
            "mold_temp_C": {
                "type": "number",
                "description": (
                    "Mold (coolant-side) temperature [deg C]. Must be >= 0. "
                    "Used for reporting context; higher mold temperatures slow "
                    "freeze-off and may extend the processing window. "
                    "Typical ranges: PP 20-80 deg C, ABS 40-80 deg C, PC 70-120 deg C."
                ),
                "minimum": 0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_check_melt_flow_ratio(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute melt-flow-ratio injection-speed check and return a JSON string."""
    try:
        polymer_grade = args.get("polymer_grade")
        mfr = args.get("mfr_g_per_10min")
        wall = args.get("wall_thickness_mm")
        gate_type = args.get("gate_type")
        melt_temp = args.get("melt_temp_C")
        mold_temp = args.get("mold_temp_C")

        # Validate required args
        if polymer_grade is None:
            return err_payload("polymer_grade is required", "BAD_ARGS")
        if mfr is None:
            return err_payload("mfr_g_per_10min is required", "BAD_ARGS")
        if wall is None:
            return err_payload("wall_thickness_mm is required", "BAD_ARGS")
        if gate_type is None:
            return err_payload("gate_type is required", "BAD_ARGS")
        if melt_temp is None:
            return err_payload("melt_temp_C is required", "BAD_ARGS")
        if mold_temp is None:
            return err_payload("mold_temp_C is required", "BAD_ARGS")

        # Type coercions
        try:
            mfr = float(mfr)
        except (TypeError, ValueError):
            return err_payload(
                f"mfr_g_per_10min must be a number, got {mfr!r}", "BAD_ARGS"
            )
        try:
            wall = float(wall)
        except (TypeError, ValueError):
            return err_payload(
                f"wall_thickness_mm must be a number, got {wall!r}", "BAD_ARGS"
            )
        try:
            melt_temp = float(melt_temp)
        except (TypeError, ValueError):
            return err_payload(
                f"melt_temp_C must be a number, got {melt_temp!r}", "BAD_ARGS"
            )
        try:
            mold_temp = float(mold_temp)
        except (TypeError, ValueError):
            return err_payload(
                f"mold_temp_C must be a number, got {mold_temp!r}", "BAD_ARGS"
            )

        spec = MeltFlowSpec(
            polymer_grade=str(polymer_grade),
            mfr_g_per_10min=mfr,
            wall_thickness_mm=wall,
            gate_type=str(gate_type),
            melt_temp_C=melt_temp,
            mold_temp_C=mold_temp,
        )

        report = check_melt_flow_ratio(spec)

        payload: dict[str, Any] = {
            "ok": True,
            "polymer_grade": spec.polymer_grade,
            "mfr_g_per_10min": spec.mfr_g_per_10min,
            "mfr_classification": report.mfr_classification,
            "recommended_injection_speed_mm_per_s": list(
                report.recommended_injection_speed_mm_per_s
            ),
            "gate_freeze_risk": report.gate_freeze_risk,
            "jetting_risk": report.jetting_risk,
            "sink_mark_risk": report.sink_mark_risk,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., "
                "Hanser 2007, §4 (Melt flow and injection speed), §7 (Gate design); "
                "Menges G., Michaeli W., Mohren P. How to Make Injection Molds, "
                "3rd ed., Hanser 2001, §6.2 (Injection conditions); "
                "ASTM D1238-23 (MFR measurement standard)."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "MELT_FLOW_RATIO_ERROR")
