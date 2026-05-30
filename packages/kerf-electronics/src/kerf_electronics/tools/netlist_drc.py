"""
LLM tool: electronics_netlist_consistency

Check that a PCB layout's copper connectivity matches the schematic netlist.
Wraps the pure-Python engine in netlist_drc.py and returns a structured
ConsistencyReport with IPC-7351B violation tags.

Catches:
  - missing_connections : schematic says A connects B; no PCB trace realises it.
  - extra_connections   : PCB copper joins pins that different schematic nets own.
  - swapped_nets        : pins from net_A routed as net_B and vice versa.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.netlist_drc import (
    check_design_violations,
    compare_netlists,
    pcb_to_netlist,
    schematic_to_netlist,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

netlist_consistency_spec = ToolSpec(
    name="electronics_netlist_consistency",
    description=(
        "Verify that a PCB layout's copper connectivity matches the schematic netlist "
        "(IPC-7351B §4.1-4.2). "
        "Detects: missing_connections (schematic connection not realised in copper), "
        "extra_connections (PCB copper joins pins from different schematic nets — short), "
        "and swapped_nets (pin assignments migrated between nets, indicating a net swap). "
        "Returns a ConsistencyReport with consistent=true/false, per-category lists, "
        "recommended_fixes, and IPC-7351B-tagged violations with severity=error|warning. "
        "Inputs: schematic_json (source_* CircuitJSON elements) and "
        "pcb_json (pcb_* CircuitJSON elements). "
        "Run run_pcb_drc first for physical DRC; run this tool for logical netlist parity."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "schematic_json": {
                "type": "array",
                "description": (
                    "Flat CircuitJSON array containing source_component, source_port, "
                    "source_trace, and source_net elements that define the intended netlist."
                ),
                "items": {"type": "object"},
            },
            "pcb_json": {
                "type": "array",
                "description": (
                    "Flat CircuitJSON array containing pcb_smtpad, pcb_plated_hole, "
                    "and pcb_trace elements that describe the actual copper layout. "
                    "Pads must have source_component_id + pin_name (or component_ref + pin) "
                    "fields to be matched against the schematic."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["schematic_json", "pcb_json"],
    },
)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

@register(netlist_consistency_spec, write=False)
async def run_netlist_consistency(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    schematic_json = a.get("schematic_json")
    pcb_json = a.get("pcb_json")

    if not isinstance(schematic_json, list):
        return err_payload("schematic_json must be an array", "BAD_ARGS")
    if not isinstance(pcb_json, list):
        return err_payload("pcb_json must be an array", "BAD_ARGS")

    try:
        sch_nets = schematic_to_netlist(schematic_json)
        pcb_nets_list = pcb_to_netlist(pcb_json)
        report = compare_netlists(sch_nets, pcb_nets_list)
        violations = check_design_violations(report)
    except Exception as exc:
        return err_payload(f"netlist consistency check failed: {exc}", "CHECK_ERROR")

    # Serialise dataclasses to plain dicts
    def _net_to_dict(n):
        return {"id": n.id, "name": n.name, "connected_pins": n.connected_pins}

    def _viol_to_dict(v):
        return {
            "kind": v.kind,
            "severity": v.severity,
            "message": v.message,
            "reference": v.reference,
            "detail": v.detail,
        }

    result = {
        "consistent": report.consistent,
        "missing_connections": report.missing_connections,
        "extra_connections": report.extra_connections,
        "swapped_nets": report.swapped_nets,
        "recommended_fixes": report.recommended_fixes,
        "violations": [_viol_to_dict(v) for v in violations],
        "summary": {
            "schematic_nets": len(sch_nets),
            "pcb_nets": len(pcb_nets_list),
            "missing_count": len(report.missing_connections),
            "extra_count": len(report.extra_connections),
            "swapped_count": len(report.swapped_nets),
            "violation_count": len(violations),
            "error_count": sum(1 for v in violations if v.severity == "error"),
            "warning_count": sum(1 for v in violations if v.severity == "warning"),
        },
    }
    return ok_payload(result)
