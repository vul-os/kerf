"""
kerf_cad_core.cuttingtool.cutting_speed_tools
=============================================

LLM tool: manufacturing_query_cutting_speed

Queries the cutting-speed database for a workpiece material × tool material ×
operation combination, returning SFM range, feed range and application notes.

Data sourced from:
  Machinery's Handbook 31e §1100 (Industrial Press, 2020).
  Sandvik Coromant CoroKey 2023/2024 cutting-data recommendations.

Honest disclaimer: illustrative subset — validate against manufacturer
live-data tools (Sandvik CoroPlus® ToolGuide, Kennametal NOVO, etc.) for
production machining programmes.

Author: imranparuk
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.cuttingtool.cutting_speed_database import (
    query_cutting_speed,
    list_materials,
    list_tool_materials,
    list_operations,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_QUERY_SPEED_SPEC = ToolSpec(
    name="manufacturing_query_cutting_speed",
    description=(
        "Query recommended cutting speeds for a workpiece material × tool material ×\n"
        "operation combination.\n"
        "\n"
        "Returns SFM range (min / typical / max) and feed range (IPT for milling;\n"
        "IPR for turning/drilling/reaming), plus m/min equivalents.\n"
        "\n"
        "Data sources:\n"
        "  Machinery's Handbook 31e §1100 (Industrial Press, 2020)\n"
        "  Sandvik Coromant CoroKey 2023/2024\n"
        "\n"
        "IMPORTANT: This is an illustrative subset.  Validate against Sandvik\n"
        "CoroPlus® ToolGuide, Kennametal NOVO, or Iscar iMachining for production.\n"
        "\n"
        "Workpiece materials (20):\n"
        "  aluminum_6061, aluminum_7075, aluminum_cast\n"
        "  brass_360, brass_cast\n"
        "  steel_1018, steel_4140, steel_stainless_304, steel_stainless_316,\n"
        "  steel_hardened_60hrc\n"
        "  cast_iron_gray, cast_iron_ductile\n"
        "  titanium_6al4v, titanium_cp\n"
        "  inconel_718\n"
        "  copper_c110\n"
        "  plastic_acetal, plastic_nylon, plastic_abs\n"
        "  magnesium_az31\n"
        "\n"
        "Tool materials: hss | carbide | ceramic | diamond\n"
        "\n"
        "Operations: turning | milling | drilling | reaming\n"
        "\n"
        "Depth-bar reference values (oracle):\n"
        "  Al 6061 + carbide + milling  → SFM 800–2400, typical 1500; IPT 0.001–0.005\n"
        "  Steel 1018 + HSS + drilling  → SFM 60–90, typical 80; IPR 0.005–0.015\n"
        "  Ti-6Al-4V + carbide + turning → SFM 200–300, typical 250\n"
        "\n"
        "Returns: {ok, material, tool_material, operation, sfm_min, sfm_typical,\n"
        "          sfm_max, sfm_*_m_min, ipt_or_ipr_lo, ipt_or_ipr_hi, feed_unit,\n"
        "          feasible, notes, source, reason}\n"
        "\n"
        "Errors: {ok:false, reason} for unknown keys. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "material": {
                "type": "string",
                "description": (
                    "Workpiece material key (case-insensitive, spaces/hyphens → underscores). "
                    "E.g. 'aluminum_6061', 'steel_1018', 'titanium_6al4v', 'inconel_718'."
                ),
            },
            "tool_material": {
                "type": "string",
                "description": (
                    "Tool material key: 'hss' | 'carbide' | 'ceramic' | 'diamond'."
                ),
            },
            "operation": {
                "type": "string",
                "description": (
                    "Machining operation: 'turning' | 'milling' | 'drilling' | 'reaming'."
                ),
            },
            "list_materials": {
                "type": "boolean",
                "description": (
                    "If true, return the list of all valid workpiece material keys "
                    "instead of performing a query. Useful for discovery."
                ),
            },
        },
        "required": [],
    },
)


@register(_QUERY_SPEED_SPEC, write=False)
async def run_manufacturing_query_cutting_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # Discovery mode
    if a.get("list_materials"):
        return ok_payload({
            "ok": True,
            "workpiece_materials": list_materials(),
            "tool_materials": list_tool_materials(),
            "operations": list_operations(),
        })

    material = a.get("material")
    tool_material = a.get("tool_material")
    operation = a.get("operation")

    if not material:
        return json.dumps({"ok": False, "reason": "'material' is required."})
    if not tool_material:
        return json.dumps({"ok": False, "reason": "'tool_material' is required."})
    if not operation:
        return json.dumps({"ok": False, "reason": "'operation' is required."})

    try:
        result = query_cutting_speed(str(material), str(tool_material), str(operation))
    except Exception as exc:
        return err_payload(f"query_cutting_speed raised unexpectedly: {exc}", "INTERNAL")

    d = result.to_dict()
    if not result.ok:
        return json.dumps(d)
    return ok_payload(d)
