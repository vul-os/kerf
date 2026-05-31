"""
LLM tool: electronics_compute_derated_ampacity

NEC 2023 Article 310 wire ampacity derating calculator — applies ambient
temperature correction (Table 310.15(B)(2)(a)) and conductor bundling
adjustment (Table 310.15(B)(3)(a)) to a caller-supplied base ampacity
from NEC Table 310.16, 75 °C column.

References:
  - NEC 2023 Table 310.16: base ampacity, 75°C insulation column
  - NEC 2023 Article 310.15(B)(2)(a) + Table 310.15(B)(2)(a): ambient
    temperature correction factors for 75°C insulation
  - NEC 2023 Article 310.15(B)(3)(a) + Table 310.15(B)(3)(a): adjustment
    factors for more than three current-carrying conductors

TOOLS exported:
  electronics_compute_derated_ampacity — compute effective ampacity after
      ambient and bundling derating.

All handlers follow the kerf never-raise contract: errors → {"ok": false, ...}.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.wire_ampacity_derate import (
    WireSpec,
    InstallationConditions,
    compute_derated_ampacity,
)

# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_DERATE_SPEC = ToolSpec(
    name="electronics_compute_derated_ampacity",
    description=(
        "Compute the effective installation ampacity of a conductor after applying "
        "NEC 2023 Article 310 derating:\n"
        "  1. Ambient temperature correction — NEC Table 310.15(B)(2)(a), 75°C column.\n"
        "  2. Conductor bundling adjustment — NEC Table 310.15(B)(3)(a).\n\n"
        "Effective ampacity = base_ampacity_A × C_ambient × C_bundling.\n\n"
        "References:\n"
        "  • NEC 2023 Table 310.16 (caller supplies base ampacity from 75°C column).\n"
        "  • NEC 2023 Table 310.15(B)(2)(a): ambient correction — ≤30°C→1.00, "
        "31–35°C→0.94, 36–40°C→0.88, 41–45°C→0.82, 46–50°C→0.75, 51–55°C→0.67, "
        "56–60°C→0.58.\n"
        "  • NEC 2023 Table 310.15(B)(3)(a): bundling — 1–3→1.00, 4–6→0.80, "
        "7–9→0.70, 10–20→0.50, 21–30→0.45, 31–40→0.40, 41+→0.35.\n\n"
        "Honest caveats:\n"
        "  • 75°C insulation column only (THWN/THHN/XHHW/RHW). NEC 110.14(C) "
        "terminal rating limits most ≤100 A circuits to 75°C regardless of "
        "insulation rating.\n"
        "  • Rooftop adder, underground/buried, and Type NM cable derating NOT modelled.\n"
        "  • Free-air installation (Table 310.17) NOT covered — set in_conduit=false "
        "and supply Table 310.17 base ampacity.\n"
        "  • Ambient > 60°C: outside table range — raises an error.\n\n"
        "Input: { awg_size, material, insulation_class, base_ampacity_A, "
        "ambient_temp_C, num_current_carrying_conductors?, in_conduit? }\n"
        "Returns: { ok, base_ampacity_A, ambient_correction_factor, bundling_factor, "
        "effective_ampacity_A, conditions_summary, code_section_cited, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "awg_size": {
                "type": "string",
                "description": (
                    "AWG conductor size string, e.g. '14', '12', '10', '8', '6', '4', "
                    "'2', '1', '1/0', '2/0', '3/0', '4/0', '250kcmil'. "
                    "Used for documentation in the report; the base_ampacity_A value "
                    "must match the corresponding NEC Table 310.16 entry."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["copper", "aluminum"],
                "description": "Conductor material.",
            },
            "insulation_class": {
                "type": "string",
                "enum": ["TW", "THWN", "THHN", "XHHW", "RHW"],
                "description": (
                    "Insulation type. THWN/THHN/XHHW/RHW are all 75°C rated "
                    "and use the 75°C correction column. TW is 60°C — apply with "
                    "caution (this module uses 75°C correction factors)."
                ),
            },
            "base_ampacity_A": {
                "type": "number",
                "description": (
                    "Conductor base ampacity from NEC Table 310.16, 75°C column, "
                    "≤3 conductors in conduit, 30°C ambient [A]. "
                    "Example: 12 AWG copper THWN → 25 A; 10 AWG copper → 35 A."
                ),
            },
            "ambient_temp_C": {
                "type": "number",
                "description": (
                    "Actual ambient temperature at the installation site [°C]. "
                    "NEC Table 310.15(B)(2)(a) correction factor is applied. "
                    "Supported: ≤ 60°C. Values ≤ 30°C yield correction factor 1.00."
                ),
            },
            "num_current_carrying_conductors": {
                "type": "integer",
                "description": (
                    "Total number of current-carrying conductors sharing the conduit, "
                    "raceway, or cable bundle. Default 1. "
                    "Values 1–3 yield a bundling factor of 1.00 (already in Table 310.16). "
                    "4–6 → 0.80, 7–9 → 0.70, 10–20 → 0.50, 21–30 → 0.45, "
                    "31–40 → 0.40, 41+ → 0.35."
                ),
            },
            "in_conduit": {
                "type": "boolean",
                "description": (
                    "True (default) if conductors share a conduit, raceway, or are "
                    "otherwise bundled — bundling derating applies. "
                    "False for free-air installations (Table 310.17); no bundling "
                    "derating is applied but the caller must supply a Table 310.17 "
                    "base ampacity."
                ),
            },
        },
        "required": [
            "awg_size", "material", "insulation_class",
            "base_ampacity_A", "ambient_temp_C",
        ],
    },
)


@register(_DERATE_SPEC, write=False)
async def electronics_compute_derated_ampacity(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        wire = WireSpec(
            awg_size=str(a["awg_size"]),
            material=str(a["material"]),
            insulation_class=str(a["insulation_class"]),
            base_ampacity_A=float(a["base_ampacity_A"]),
        )
        conditions = InstallationConditions(
            ambient_temp_C=float(a["ambient_temp_C"]),
            num_current_carrying_conductors=int(a.get("num_current_carrying_conductors", 1)),
            in_conduit=bool(a.get("in_conduit", True)),
        )
        report = compute_derated_ampacity(wire, conditions)
    except (ValueError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"internal error: {exc}", "INTERNAL")

    return ok_payload({
        "ok": True,
        "base_ampacity_A": report.base_ampacity_A,
        "ambient_correction_factor": report.ambient_correction_factor,
        "bundling_factor": report.bundling_factor,
        "effective_ampacity_A": report.effective_ampacity_A,
        "conditions_summary": report.conditions_summary,
        "code_section_cited": report.code_section_cited,
        "honest_caveat": report.honest_caveat,
    })


# ---------------------------------------------------------------------------
# TOOLS export — consumed by plugin._register_tools
# ---------------------------------------------------------------------------

TOOLS = [
    (_DERATE_SPEC.name, _DERATE_SPEC, electronics_compute_derated_ampacity),
]
