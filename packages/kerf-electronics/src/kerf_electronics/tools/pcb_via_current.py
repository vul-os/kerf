"""
LLM tool: electronics_compute_pcb_via_current

IPC-2152 §6.3 + IPC-2221A §6 via current-carrying capacity.

Given drill diameter [mm], plating thickness [µm], via length [mm] (board
thickness), and allowed temperature rise [°C], returns the maximum allowable
DC current per via and the number of parallel vias needed for a target current.

Model:
  A_barrel [µm²] = π × D_drill [µm] × t_plating [µm]   (thin-wall IPC-2152 §6.3)
  I_via [A]      = 0.048 × ΔT^0.44 × A_mil²^0.725       (IPC-2221B Eq. 6-4)
  N_vias         = ceil(target_current_A / I_via)          (IPC-2152 §6.3 Note 2)

TOOLS exported:
  electronics_compute_pcb_via_current — IPC-2152 via current check.

All handlers follow the kerf never-raise contract: errors → {"ok": false, ...}.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.pcb_via_current import (
    PcbViaSpec,
    compute_pcb_via_max_current,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_PCB_VIA_SPEC = ToolSpec(
    name="electronics_compute_pcb_via_current",
    description=(
        "Compute the maximum allowable DC current through a PCB plated-through-hole "
        "(PTH) via and recommend how many parallel vias are needed for a target current.\n\n"
        "Model (IPC-2152 §6.3 + IPC-2221A §6):\n"
        "  A_barrel [µm²] = π × D_drill_µm × t_plating_µm   (thin-wall barrel)\n"
        "  I_via [A]      = 0.048 × ΔT^0.44 × A_mil²^0.725  (IPC-2221B Eq. 6-4)\n"
        "  N_vias         = ceil(target_current_A / I_per_via)\n\n"
        "Typical values:\n"
        "  • 0.3 mm drill, 25 µm plating, ΔT=10 °C → ~1.0–1.5 A per via\n"
        "  • 0.5 mm drill, 25 µm plating, ΔT=10 °C → ~1.6–2.2 A per via\n"
        "  • IPC-6012 Class 2 minimum plating: 20 µm average (18 µm min)\n"
        "  • High-reliability (Class 3): 25 µm average\n\n"
        "Reference: IPC-2152 (2009) §6.3 + IPC-2221A (1998) §6.\n\n"
        "Honest caveats:\n"
        "  • IPC empirical model only. Adjacent copper planes increase capacity "
        "10–30% (IPC-2152 cf_pl correction) — NOT modelled here (conservative).\n"
        "  • Dense via arrays: mutual heating reduces individual capacity ~10–20% "
        "(IPC-7093 §4.1) — apply 0.80–0.90 derating factor manually.\n"
        "  • Via fill: resin/copper-filled vias carry more heat than air-filled "
        "(assumed here).\n\n"
        "Input:  { drill_diameter_mm, plating_thickness_um, via_length_mm, "
        "temp_rise_C?, copper_pad_size_mm?, target_current_A? }\n"
        "Returns: { ok, max_current_A, via_cross_section_um2, "
        "equivalent_trace_width_mm, recommended_via_count_for_target_current, "
        "honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "drill_diameter_mm": {
                "type": "number",
                "description": (
                    "Finished drill hole diameter [mm]. "
                    "Typical: 0.20–0.30 mm (microvias), 0.30–0.60 mm (standard signal), "
                    "0.60–1.00 mm (power/thermal). "
                    "IPC-2221A §9.1 minimum: 0.15 mm."
                ),
            },
            "plating_thickness_um": {
                "type": "number",
                "description": (
                    "Copper plating thickness on via barrel wall [µm]. "
                    "IPC-6012 Class 2 minimum: 20 µm average (18 µm min). "
                    "IPC-6012 Class 3 (high-reliability): 25 µm average. "
                    "Typical standard fab: 25 µm. Heavy copper HDI: 35–50 µm."
                ),
            },
            "via_length_mm": {
                "type": "number",
                "description": (
                    "Via barrel length [mm], equal to PCB board thickness. "
                    "Used to compute barrel DC resistance (informational). "
                    "Typical: 0.8 mm (thin board), 1.6 mm (standard FR-4), "
                    "2.4–3.2 mm (thick board)."
                ),
            },
            "temp_rise_C": {
                "type": "number",
                "description": (
                    "Allowable temperature rise above ambient [°C]. "
                    "Default 10 °C (IPC-2221B conservative guideline). "
                    "Typical: 10 °C (conservative), 20 °C (moderate), 30 °C (aggressive)."
                ),
            },
            "copper_pad_size_mm": {
                "type": "number",
                "description": (
                    "Annular copper pad diameter [mm] surrounding the via hole "
                    "(informational; not used in the current calculation). "
                    "Default 1.0 mm. Typical IPC-2221A: drill + 0.25–0.50 mm annular ring."
                ),
            },
            "target_current_A": {
                "type": "number",
                "description": (
                    "Optional target current [A] to determine how many parallel vias "
                    "are needed. When provided, returns "
                    "recommended_via_count_for_target_current = ceil(target / per_via). "
                    "Example: 5 A target with 1.5 A per via → 4 vias."
                ),
            },
        },
        "required": ["drill_diameter_mm", "plating_thickness_um", "via_length_mm"],
    },
)


@register(_PCB_VIA_SPEC, write=False)
async def electronics_compute_pcb_via_current(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        spec = PcbViaSpec(
            drill_diameter_mm=float(a["drill_diameter_mm"]),
            plating_thickness_um=float(a["plating_thickness_um"]),
            via_length_mm=float(a["via_length_mm"]),
            temp_rise_C=float(a.get("temp_rise_C", 10.0)),
            copper_pad_size_mm=float(a.get("copper_pad_size_mm", 1.0)),
        )
        target_A: float | None = None
        if "target_current_A" in a and a["target_current_A"] is not None:
            target_A = float(a["target_current_A"])
        report = compute_pcb_via_max_current(spec, target_current_A=target_A)
    except (ValueError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"internal error: {exc}", "INTERNAL")

    return ok_payload({
        "ok": True,
        "max_current_A": report.max_current_A,
        "via_cross_section_um2": report.via_cross_section_um2,
        "equivalent_trace_width_mm": report.equivalent_trace_width_mm,
        "recommended_via_count_for_target_current": (
            report.recommended_via_count_for_target_current
        ),
        "honest_caveat": report.honest_caveat,
    })


# ---------------------------------------------------------------------------
# TOOLS export — consumed by plugin._register_tools
# ---------------------------------------------------------------------------

TOOLS = [
    (_PCB_VIA_SPEC.name, _PCB_VIA_SPEC, electronics_compute_pcb_via_current),
]
