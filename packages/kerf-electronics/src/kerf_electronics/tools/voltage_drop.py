"""
LLM tool: electronics_check_voltage_drop

NEC 2023 Article 210.19(A) voltage-drop check for AC/DC conductor runs.

References:
  - NEC 2023 Article 210.19(A) Informational Note 4 (≤ 3% feeder, ≤ 2% branch)
  - NEC 2023 Chapter 9 Table 8 (conductor DC resistance at 75°C)
  - IEEE 141-1993 §3.3 (voltage-drop formulas)

TOOLS exported:
  electronics_check_voltage_drop — compute Vd, Vd%, and NEC compliance flag.

All handlers follow the kerf never-raise contract: errors → {"ok": false, "reason": ...}.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.voltage_drop import (
    ConductorSpec,
    CircuitSpec,
    check_voltage_drop,
)

# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_VD_CHECK_SPEC = ToolSpec(
    name="electronics_check_voltage_drop",
    description=(
        "Compute voltage drop across a conductor run and verify NEC 2023 "
        "Article 210.19(A) Informational Note 4 compliance.\n\n"
        "References:\n"
        "  • NEC 2023 Article 210.19(A) Informational Note 4: "
        "recommended ≤ 3% feeder, ≤ 2% branch circuit.\n"
        "  • NEC 2023 Chapter 9 Table 8: DC conductor resistance at 75°C.\n"
        "  • IEEE 141-1993 §3.3: voltage-drop formulas.\n\n"
        "Formulas (IEEE 141 §3.3):\n"
        "  DC / single-phase: V_drop = 2 × I × R [Ω/m] × L [m] × PF\n"
        "  Three-phase:       V_drop = √3 × I × R [Ω/m] × L [m] × PF\n\n"
        "Supported AWG sizes: 14, 12, 10, 8, 6, 4, 2, 1, 1/0, 2/0, 3/0, 4/0, 250kcmil\n"
        "Materials: copper | aluminum (1.64× copper per Table 8)\n\n"
        "Honest caveats:\n"
        "  • Resistance at 75°C baseline — no ambient temperature correction.\n"
        "  • AC reactance (X_L) ignored; may underestimate by 5–15% for ≥ 1/0 AWG.\n"
        "  • NEC 210.19(A) Note 4 is advisory, not mandatory.\n\n"
        "Input: { awg_size, material, length_one_way_m, voltage_V, current_A, "
        "phase, power_factor?, max_drop_pct? }\n"
        "Returns: { ok, voltage_drop_V, voltage_drop_pct, recommended_max_pct, "
        "compliant, resistance_ohm, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "awg_size": {
                "type": "string",
                "enum": [
                    "14", "12", "10", "8", "6", "4", "2", "1",
                    "1/0", "2/0", "3/0", "4/0", "250kcmil",
                ],
                "description": (
                    "AWG conductor size. Use '250kcmil' for 250 kcmil. "
                    "NEC Chapter 9 Table 8 supports 14 AWG–4/0 and 250–750 kcmil; "
                    "this tool covers the most common range."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["copper", "aluminum"],
                "description": "Conductor material: 'copper' or 'aluminum'.",
            },
            "length_one_way_m": {
                "type": "number",
                "description": "One-way conductor run length [m]. Round-trip is computed internally.",
            },
            "voltage_V": {
                "type": "number",
                "description": "System voltage [V] (used as denominator for Vd%).",
            },
            "current_A": {
                "type": "number",
                "description": "Load current [A].",
            },
            "phase": {
                "type": "string",
                "enum": ["dc", "single_phase", "three_phase"],
                "description": (
                    "'dc' for DC circuits (2-wire, round-trip), "
                    "'single_phase' for single-phase AC (2-wire), "
                    "'three_phase' for balanced 3-phase AC."
                ),
            },
            "power_factor": {
                "type": "number",
                "description": (
                    "Power factor (0 < PF ≤ 1.0). Use 1.0 for DC or purely "
                    "resistive loads (default 1.0). Typical: 0.85–0.95 for motors."
                ),
            },
            "max_drop_pct": {
                "type": "number",
                "description": (
                    "Maximum allowable voltage drop percentage. "
                    "Default 3.0 per NEC 210.19(A) Informational Note 4 feeder limit. "
                    "Use 2.0 for branch-circuit check."
                ),
            },
            "ambient_temp_C": {
                "type": "number",
                "description": (
                    "Ambient temperature [°C] (default 30.0). Documented for future "
                    "temperature-correction support; the 75°C NEC Table 8 baseline is "
                    "used as-is in this version."
                ),
            },
        },
        "required": ["awg_size", "material", "length_one_way_m", "voltage_V", "current_A", "phase"],
    },
)


@register(_VD_CHECK_SPEC, write=False)
async def electronics_check_voltage_drop(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        conductor = ConductorSpec(
            awg_size=a["awg_size"],
            material=a["material"],
            length_one_way_m=float(a["length_one_way_m"]),
            ambient_temp_C=float(a.get("ambient_temp_C", 30.0)),
        )
        circuit = CircuitSpec(
            voltage_V=float(a["voltage_V"]),
            current_A=float(a["current_A"]),
            phase=a["phase"],
            power_factor=float(a.get("power_factor", 1.0)),
        )
        max_drop_pct = float(a.get("max_drop_pct", 3.0))
        report = check_voltage_drop(conductor, circuit, max_drop_pct=max_drop_pct)
    except (ValueError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"internal error: {exc}", "INTERNAL")

    return ok_payload({
        "ok": True,
        "voltage_drop_V": report.voltage_drop_V,
        "voltage_drop_pct": report.voltage_drop_pct,
        "recommended_max_pct": report.recommended_max_pct,
        "compliant": report.compliant,
        "resistance_ohm": report.resistance_ohm,
        "honest_caveat": report.honest_caveat,
    })


# ---------------------------------------------------------------------------
# TOOLS export — consumed by plugin._register_tools
# ---------------------------------------------------------------------------

TOOLS = [
    (_VD_CHECK_SPEC.name, _VD_CHECK_SPEC, electronics_check_voltage_drop),
]
