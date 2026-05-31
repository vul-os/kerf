"""
LLM tool: electronics_check_circuit_protection

NEC 2023 Article 240.4 + Table 310.16 + Article 215 circuit-protection check.

References:
  - NEC 2023 Table 310.16 (75°C column — conductor ampacity)
  - NEC 2023 Article 240.4 (overcurrent protection of conductors)
  - NEC 2023 Article 240.4(D) (small conductor tap rule)
  - NEC 2023 Article 215.3 / 210.20(A) (continuous + non-continuous load sizing)

TOOLS exported:
  electronics_check_circuit_protection — verify OCPD sizing and conductor ampacity.

All handlers follow the kerf never-raise contract: errors → {"ok": false, "reason": ...}.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.circuit_protection_check import (
    ConductorSpec,
    LoadSpec,
    OcpdSpec,
    check_circuit_protection,
)

# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_CP_CHECK_SPEC = ToolSpec(
    name="electronics_check_circuit_protection",
    description=(
        "Verify that an overcurrent protective device (OCPD) is correctly sized "
        "for a conductor and load per NEC 2023 Articles 240 and 215.\n\n"
        "References:\n"
        "  • NEC 2023 Table 310.16 (75°C column): conductor ampacity for "
        "THWN/THHN/XHHW/RHW insulation, ≤3 current-carrying conductors in conduit, "
        "30°C ambient.\n"
        "  • NEC 2023 Article 240.4(B): OCPD ≤ conductor ampacity.\n"
        "  • NEC 2023 Article 240.4(D): small conductor rule — "
        "14 AWG Cu → max 15 A, 12 AWG Cu → max 20 A, 10 AWG Cu → max 30 A.\n"
        "  • NEC 2023 Article 215.3 / 210.20(A): required OCPD ≥ "
        "1.25 × continuous_current + non_continuous_current.\n\n"
        "Supported AWG sizes: 14, 12, 10, 8, 6, 4, 3, 2, 1, 1/0, 2/0, 3/0, 4/0, "
        "250kcmil, 300kcmil, 500kcmil\n"
        "Materials: copper | aluminum\n"
        "Insulation (all 75°C): THWN | THHN | XHHW | RHW\n\n"
        "Honest caveats:\n"
        "  • 75°C THWN baseline — no ambient temperature derating (NEC 310.15(B)(2)(a)).\n"
        "  • No bundling derating (NEC Table 310.15(B)(3)(a)).\n"
        "  • Short-circuit withstand, arc-flash, and grounding are out of scope.\n\n"
        "Input: { awg_size, material, insulation_class, continuous_current_A, "
        "non_continuous_current_A, voltage_V, phase, breaker_rating_A, breaker_type? }\n"
        "Returns: { ok, ampacity_A, required_ocpd_min_A, derated_ampacity_A, "
        "ocpd_compliant, conductor_adequate, code_section_cited, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "awg_size": {
                "type": "string",
                "enum": [
                    "14", "12", "10", "8", "6", "4", "3", "2", "1",
                    "1/0", "2/0", "3/0", "4/0", "250kcmil", "300kcmil", "500kcmil",
                ],
                "description": (
                    "Conductor AWG or kcmil size.  Use '250kcmil' for 250 kcmil, etc. "
                    "NEC Table 310.16 covers AWG 14–4/0 and 250–750 kcmil; "
                    "this tool covers the most common range."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["copper", "aluminum"],
                "description": "Conductor material.",
            },
            "insulation_class": {
                "type": "string",
                "enum": ["THWN", "THHN", "XHHW", "RHW"],
                "description": (
                    "Insulation type — all four carry a 75°C rating and use the "
                    "same NEC Table 310.16 75°C column."
                ),
            },
            "continuous_current_A": {
                "type": "number",
                "description": (
                    "Portion of load current that flows continuously (≥ 3 h) [A]. "
                    "NEC 100 definition of continuous load."
                ),
            },
            "non_continuous_current_A": {
                "type": "number",
                "description": "Portion of load current that is NOT continuous [A].",
            },
            "voltage_V": {
                "type": "number",
                "description": "System voltage [V] (informational, not used in NEC 240.4 calc).",
            },
            "phase": {
                "type": "string",
                "enum": ["single_phase", "three_phase"],
                "description": "Circuit phase configuration (informational).",
            },
            "breaker_rating_A": {
                "type": "number",
                "description": "Nominal OCPD rating [A] (breaker trip rating or fuse ampere rating).",
            },
            "breaker_type": {
                "type": "string",
                "enum": ["standard", "hacr", "slow_blow"],
                "description": (
                    "OCPD type.  'standard' = standard inverse-time circuit breaker; "
                    "'hacr' = HACR-rated breaker (heating/air-conditioning/refrigeration); "
                    "'slow_blow' = time-delay fuse.  Default 'standard'."
                ),
            },
        },
        "required": [
            "awg_size", "material", "insulation_class",
            "continuous_current_A", "non_continuous_current_A",
            "voltage_V", "phase", "breaker_rating_A",
        ],
    },
)


@register(_CP_CHECK_SPEC, write=False)
async def electronics_check_circuit_protection(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        conductor = ConductorSpec(
            awg_size=a["awg_size"],
            material=a["material"],
            insulation_class=a["insulation_class"],
        )
        load = LoadSpec(
            continuous_current_A=float(a["continuous_current_A"]),
            non_continuous_current_A=float(a["non_continuous_current_A"]),
            voltage_V=float(a["voltage_V"]),
            phase=a["phase"],
        )
        ocpd = OcpdSpec(
            breaker_rating_A=float(a["breaker_rating_A"]),
            breaker_type=str(a.get("breaker_type", "standard")),
        )
        report = check_circuit_protection(conductor, load, ocpd)
    except (ValueError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"internal error: {exc}", "INTERNAL")

    return ok_payload({
        "ok": True,
        "ampacity_A": report.ampacity_A,
        "required_ocpd_min_A": report.required_ocpd_min_A,
        "derated_ampacity_A": report.derated_ampacity_A,
        "ocpd_compliant": report.ocpd_compliant,
        "conductor_adequate": report.conductor_adequate,
        "code_section_cited": report.code_section_cited,
        "honest_caveat": report.honest_caveat,
    })


# ---------------------------------------------------------------------------
# TOOLS export — consumed by plugin._register_tools
# ---------------------------------------------------------------------------

TOOLS = [
    (_CP_CHECK_SPEC.name, _CP_CHECK_SPEC, electronics_check_circuit_protection),
]
