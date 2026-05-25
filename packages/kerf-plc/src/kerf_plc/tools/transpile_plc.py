"""LLM tools: convert_st_to_ladder / convert_ladder_to_st

Bidirectional ST ↔ LD transpiler exposed as LLM tools.

Supported ST ↔ LD subset
-------------------------
  Pure boolean assignment:  ``coil := a AND NOT b;``
  IF/THEN (single condition, optional else)
  FB call + Q-output: ``t(IN := sig, PT := T#1s);``

Input ST must be wrapped in a valid POU declaration:
  PROGRAM main
  VAR motor, start, stop: BOOL; END_VAR
  motor := start AND NOT stop;
  END_PROGRAM

Unsupported constructs (FOR, WHILE, REPEAT, CASE, ELSIF chains) return an
error with the unconvertible fragment and reason.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_plc._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


# ── ST → LD ──────────────────────────────────────────────────────────────────

convert_st_to_ladder_spec = ToolSpec(
    name="convert_st_to_ladder",
    description=(
        "Transpile an IEC 61131-3 Structured Text (ST) POU into an equivalent "
        "Ladder Diagram (LD) PLCopen XML program. "
        "Input must be a complete POU: PROGRAM <name> VAR ... END_VAR ... END_PROGRAM. "
        "Supports boolean assignments, simple IF/THEN/END_IF, and FB calls with Q output. "
        "Returns PLCopen XML with rung count. "
        "Unsupported constructs (FOR, WHILE, CASE, ELSIF) return an error with details."
    ),
    input_schema={
        "type": "object",
        "required": ["st_source"],
        "properties": {
            "st_source": {
                "type": "string",
                "description": (
                    "Complete IEC 61131-3 Structured Text POU source, e.g.:\n"
                    "  PROGRAM main\n"
                    "  VAR motor, start, stop: BOOL; END_VAR\n"
                    "  motor := start AND NOT stop;\n"
                    "  END_PROGRAM"
                ),
            },
        },
    },
)


async def convert_st_to_ladder_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    st_source = a.get("st_source", "").strip()
    if not st_source:
        return err_payload("'st_source' is required", "BAD_ARGS")

    try:
        from kerf_plc.llm.transpile import convert_st_to_ladder, TranspileError
        from kerf_plc.plcopen.writer import dumps
    except Exception as exc:
        return err_payload(f"transpile backend unavailable: {exc}", "INTERNAL")

    try:
        project = convert_st_to_ladder(st_source)
    except TranspileError as exc:
        detail = {}
        try:
            detail = json.loads(str(exc))
        except Exception:
            detail = {"reason": str(exc)}
        return err_payload(f"Transpile error: {detail}", "TRANSPILE_ERROR")
    except Exception as exc:
        return err_payload(f"Parse/transpile error: {exc}", "INTERNAL")

    try:
        xml = dumps(project)
    except Exception as exc:
        return err_payload(f"Serialise error: {exc}", "INTERNAL")

    rung_count = 0
    for pou in project.pous:
        body = pou.body
        if hasattr(body, "rungs"):
            rung_count += len(body.rungs)

    return ok_payload({"xml": xml, "rung_count": rung_count})


# ── LD → ST ──────────────────────────────────────────────────────────────────

convert_ladder_to_st_spec = ToolSpec(
    name="convert_ladder_to_st",
    description=(
        "Transpile a PLCopen Ladder Diagram XML program into equivalent "
        "IEC 61131-3 Structured Text (ST). "
        "The input must be valid PLCopen XML (as returned by make_ladder_program or "
        "convert_st_to_ladder). "
        "Returns the generated ST source string."
    ),
    input_schema={
        "type": "object",
        "required": ["xml"],
        "properties": {
            "xml": {
                "type": "string",
                "description": "PLCopen XML string of the Ladder Diagram program.",
            },
        },
    },
)


async def convert_ladder_to_st_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    xml = a.get("xml", "").strip()
    if not xml:
        return err_payload("'xml' is required", "BAD_ARGS")

    try:
        from kerf_plc.llm.transpile import convert_ladder_to_st
        from kerf_plc.plcopen.reader import loads
    except Exception as exc:
        return err_payload(f"transpile backend unavailable: {exc}", "INTERNAL")

    try:
        project = loads(xml)
    except Exception as exc:
        return err_payload(f"Failed to parse PLCopen XML: {exc}", "PARSE_ERROR")

    try:
        st_source = convert_ladder_to_st(project)
    except Exception as exc:
        return err_payload(f"Transpile error: {exc}", "TRANSPILE_ERROR")

    return ok_payload({"st_source": st_source})


TOOLS = [
    (convert_st_to_ladder_spec.name, convert_st_to_ladder_spec, convert_st_to_ladder_tool),
    (convert_ladder_to_st_spec.name, convert_ladder_to_st_spec, convert_ladder_to_st_tool),
]
