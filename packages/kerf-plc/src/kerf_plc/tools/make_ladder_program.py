"""LLM tool: make_ladder_program(spec)

Generate a complete IEC 61131-3 Ladder Diagram (LD) program from a
natural-language description. Returns PLCopen-compatible XML that can be
loaded by the PLC simulator or exported to compliant tools.

Supported patterns (case-insensitive substring match)
-----------------------------------------------------
  "traffic light"       → 3-state LD (RED / YELLOW / GREEN) with TON per state
  "blinker"             → single-rung self-resetting TON blinker
  "motor start/stop"    → 2-rung start-latch + NC stop + e-stop in series
  "conveyor"            → 3-rung: sensor trigger + motor + part counter
  "tank fill"           → 2-float high/low setpoint with TON deadband

Returns
-------
  ok_payload({"xml": str, "rung_count": int, "pattern": str})
  err_payload({"error": str, "supported": [...], "code": "UNSUPPORTED"})
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_plc._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


make_ladder_program_spec = ToolSpec(
    name="make_ladder_program",
    description=(
        "Generate a complete IEC 61131-3 Ladder Diagram (LD) program from a "
        "natural-language description. Supported patterns: 'traffic light', "
        "'blinker', 'motor start/stop', 'conveyor with sensor', 'tank fill'. "
        "Returns PLCopen XML that can be simulated or exported. "
        "Use create_ladder_rung to add custom rungs after generation."
    ),
    input_schema={
        "type": "object",
        "required": ["spec"],
        "properties": {
            "spec": {
                "type": "string",
                "description": (
                    "Natural-language description of the PLC program, e.g. "
                    "'motor start/stop with e-stop', 'traffic light sequence', "
                    "'blinker at 500 ms', 'conveyor belt with sensor', 'tank fill control'."
                ),
            },
        },
    },
)


async def make_ladder_program_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    spec = a.get("spec", "").strip()
    if not spec:
        return err_payload("'spec' is required", "BAD_ARGS")

    try:
        from kerf_plc.llm.make_ladder import make_ladder_program, SUPPORTED_PATTERNS
        from kerf_plc.plcopen.ast import Project
        from kerf_plc.plcopen.writer import dumps
    except Exception as exc:
        return err_payload(f"make_ladder backend unavailable: {exc}", "INTERNAL")

    result = make_ladder_program(spec)

    if not isinstance(result, Project):
        # make_ladder_program returns {"error": ..., "supported": [...]} for unknown pattern
        return err_payload(
            result.get("error", "Unsupported pattern"),
            "UNSUPPORTED",
        )

    try:
        xml = dumps(result)
    except Exception as exc:
        return err_payload(f"Failed to serialise program: {exc}", "INTERNAL")

    # Count rungs across all LD POUs
    rung_count = 0
    for pou in result.pous:
        body = pou.body
        if hasattr(body, "rungs"):
            rung_count += len(body.rungs)

    # Identify which pattern matched
    spec_lower = spec.lower()
    matched_pattern = "unknown"
    for pat in SUPPORTED_PATTERNS:
        if pat in spec_lower:
            matched_pattern = pat
            break

    return ok_payload({
        "xml": xml,
        "rung_count": rung_count,
        "pattern": matched_pattern,
    })


TOOLS = [
    (make_ladder_program_spec.name, make_ladder_program_spec, make_ladder_program_tool),
]
