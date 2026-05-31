"""
LLM tool: electronics_compute_pcb_trace_current

IPC-2221B simplified formula for PCB trace maximum current capacity.

Given trace width (mils), copper weight (oz/ft²), allowed temperature rise
(°C), and layer location (external / internal), returns the maximum allowable
DC current [A] per IPC-2221B Equation 6-4:

  I [A] = k · ΔT^0.44 · A^0.725

  k = 0.048 (external) | 0.024 (internal)
  A = cross-sectional area [mil²] = trace_width_mils × (copper_oz × 1.37)

TOOLS exported:
  electronics_compute_pcb_trace_current — IPC-2221 trace current check.

All handlers follow the kerf never-raise contract: errors → {"ok": false, ...}.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.pcb_trace_current import (
    PcbTraceSpec,
    compute_pcb_trace_max_current,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_PCB_TRACE_SPEC = ToolSpec(
    name="electronics_compute_pcb_trace_current",
    description=(
        "Compute the maximum allowable DC current through a PCB copper trace "
        "per the IPC-2221B simplified formula (Equation 6-4):\n\n"
        "  I [A] = k · ΔT^0.44 · A^0.725\n\n"
        "  A  = cross-sectional area [mil²] = trace_width_mils × (copper_oz × 1.37)\n"
        "  ΔT = allowed temperature rise above ambient [°C]\n"
        "  k  = 0.048 for external (outer-layer) copper\n"
        "       0.024 for internal (inner-layer / buried) copper\n\n"
        "Copper weight → thickness: 0.5 oz ≈ 0.685 mil, 1 oz ≈ 1.37 mil, "
        "2 oz ≈ 2.74 mil, 3 oz ≈ 4.11 mil.\n\n"
        "Reference: IPC-2221B (2012) §6.2 Eq. 6-4 empirical power-law.\n\n"
        "Honest caveats:\n"
        "  • IPC-2221B simplified only. IPC-2152 (2009) has more detailed "
        "thermal curves with copper-weight correction (cf_cw), board thermal "
        "conductivity correction (cf_th), and plane-proximity correction "
        "(cf_pl) — not modelled here. Use tracecurrent_ipc2152 tool for the "
        "full IPC-2152 corrected model.\n"
        "  • Formula assumes worst-case steady-state (no heat spreading from "
        "adjacent copper, vias, or pads).\n"
        "  • Copper resistivity rise with temperature is not accounted for.\n\n"
        "Input:  { trace_width_mils, copper_weight_oz?, temp_rise_C?, location? }\n"
        "Returns: { ok, max_current_A, cross_section_mils2, formula_used, "
        "derate_factor, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trace_width_mils": {
                "type": "number",
                "description": (
                    "Trace width [mils]. 1 mil = 0.0254 mm. "
                    "Typical values: 10 mil (signal), 20–50 mil (power)."
                ),
            },
            "copper_weight_oz": {
                "type": "number",
                "description": (
                    "Copper weight [oz/ft²]. Common values: 0.5, 1, 2, 3. "
                    "Default 1.0 oz (1 oz ≈ 34.8 µm ≈ 1.37 mils)."
                ),
            },
            "temp_rise_C": {
                "type": "number",
                "description": (
                    "Allowable temperature rise above ambient [°C]. "
                    "Default 10 °C (IPC-2221B conservative guideline). "
                    "Typical: 10 °C conservative, 20 °C moderate, 30 °C aggressive."
                ),
            },
            "location": {
                "type": "string",
                "enum": ["external", "internal"],
                "description": (
                    "'external' (outer layer, default) or 'internal' (buried / inner layer). "
                    "Internal traces have ~50% of the current capacity of external traces."
                ),
            },
        },
        "required": ["trace_width_mils"],
    },
)


@register(_PCB_TRACE_SPEC, write=False)
async def electronics_compute_pcb_trace_current(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        spec = PcbTraceSpec(
            trace_width_mils=float(a["trace_width_mils"]),
            copper_weight_oz=float(a.get("copper_weight_oz", 1.0)),
            temp_rise_C=float(a.get("temp_rise_C", 10.0)),
            location=str(a.get("location", "external")),
        )
        report = compute_pcb_trace_max_current(spec)
    except (ValueError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"internal error: {exc}", "INTERNAL")

    return ok_payload({
        "ok": True,
        "max_current_A": report.max_current_A,
        "cross_section_mils2": report.cross_section_mils2,
        "formula_used": report.formula_used,
        "derate_factor": report.derate_factor,
        "honest_caveat": report.honest_caveat,
    })


# ---------------------------------------------------------------------------
# TOOLS export — consumed by plugin._register_tools
# ---------------------------------------------------------------------------

TOOLS = [
    (_PCB_TRACE_SPEC.name, _PCB_TRACE_SPEC, electronics_compute_pcb_trace_current),
]
