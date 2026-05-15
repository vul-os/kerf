"""
LLM tool: run_plc_lint

Lints an IEC 61131-3 Structured Text (.plc.st) source string via the MATIEC
`iec2c` parser and returns structured diagnostics.

Schema:
  { "source": "<ST source string>" }

Returns:
  ok_payload({ "diagnostics": [...], "warnings": [...] })
  err_payload(...) on failure.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_plc._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore


run_plc_lint_spec = ToolSpec(
    name="run_plc_lint",
    description=(
        "Lint an IEC 61131-3 Structured Text (.plc.st) program via the MATIEC "
        "parser. Returns a list of diagnostics (line, column, severity, message). "
        "When MATIEC is not installed, returns a warning diagnostic rather than "
        "failing. Use this before writing .plc.st content back to the file to "
        "catch syntax errors early."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": (
                    "IEC 61131-3 Structured Text source code to lint. "
                    "See llm_docs/plc.md for the language schema and examples."
                ),
            },
        },
        "required": ["source"],
    },
)


@register(run_plc_lint_spec)
async def run_plc_lint(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    source = a.get("source", "")
    if not isinstance(source, str) or not source.strip():
        return err_payload("'source' is required and must be a non-empty string", "BAD_ARGS")

    from kerf_plc.matiec_lint import lint_st_source
    raw = lint_st_source(source)

    diagnostics = []
    warnings = []
    for d in raw:
        entry = {
            "severity": d.severity,
            "message": d.message,
            "line": d.line,
            "column": d.column,
            "source": d.source,
        }
        if d.line is None and d.severity == "warning":
            warnings.append(d.message)
        else:
            diagnostics.append(entry)

    return ok_payload({"diagnostics": diagnostics, "warnings": warnings})
