"""
LLM tool: run_print_slice

Slices a mesh (STL) to FDM G-code by calling the pyworker
POST /run-print-slice route, which invokes CuraEngine as a subprocess.

Schema:
  {
    "target_mesh_ref": "<project-relative path to .stl or step export>",
    "settings": {
      "layer_height":       0.2,          # mm, default 0.2
      "infill_density":     20,           # %, default 20
      "perimeters":         3,            # wall line count, default 3
      "retraction_enabled": true,
      "print_temperature":  200,          # °C
      "bed_temperature":    60            # °C
    }
  }

Returns:
  ok_payload({ "layer_count": N, "print_time_s": T, "filament_mm": F,
               "gcode_preview": "<first 50 lines>", "gcode_bytes": B,
               "warnings": [...] })
  err_payload(...) on failure.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_slicing._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore


run_print_slice_spec = ToolSpec(
    name="run_print_slice",
    description=(
        "Slice a mesh file to FDM 3D-print G-code using CuraEngine. "
        "Provide a project-relative path to the STL mesh and optional print settings. "
        "Returns layer count, estimated print time, filament usage, and a G-code preview. "
        "Requires CuraEngine to be installed on the server; returns a descriptive error "
        "when it is not available."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_mesh_ref": {
                "type": "string",
                "description": (
                    "Absolute project path to the STL mesh to slice "
                    "(e.g. /models/bracket.stl). The file must already exist "
                    "in the project."
                ),
            },
            "settings": {
                "type": "object",
                "description": "Optional print settings dict. See llm_docs/print.md for keys.",
                "properties": {
                    "layer_height":       {"type": "number", "minimum": 0.05, "maximum": 0.35},
                    "infill_density":     {"type": "number", "minimum": 0, "maximum": 100},
                    "perimeters":         {"type": "integer", "minimum": 1, "maximum": 10},
                    "retraction_enabled": {"type": "boolean"},
                    "print_temperature":  {"type": "number", "minimum": 150, "maximum": 300},
                    "bed_temperature":    {"type": "number", "minimum": 0, "maximum": 120},
                },
            },
        },
        "required": ["target_mesh_ref"],
    },
)


@register(run_print_slice_spec, write=False)
async def run_print_slice(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    target_mesh_ref = a.get("target_mesh_ref", "")
    settings = a.get("settings") or {}

    if not target_mesh_ref or not isinstance(target_mesh_ref, str):
        return err_payload("target_mesh_ref is required", "BAD_ARGS")

    # ── Call pyworker ─────────────────────────────────────────────────────────
    pyworker_url = "http://localhost:9090"
    try:
        resp = ctx.http_client.post(
            f"{pyworker_url}/run-print-slice",
            json={"stl_path": target_mesh_ref, "settings": settings},
            timeout=70.0,  # slightly above the 60 s CuraEngine timeout
        )
    except Exception as exc:
        return err_payload(f"slicing worker unavailable: {exc}", "WORKER_ERROR")

    if resp.status_code != 200:
        return err_payload(
            f"slicing worker returned status {resp.status_code}",
            "WORKER_ERROR",
        )

    try:
        result = resp.json()
    except Exception:
        return err_payload("invalid slicing response", "ERROR")

    error_code = result.get("error")
    warnings = result.get("warnings", [])

    if error_code == "CURA_NOT_INSTALLED":
        return err_payload(
            "CuraEngine not found on the server. "
            + "; ".join(warnings),
            "CURA_NOT_INSTALLED",
        )

    gcode = result.get("gcode")
    if not gcode:
        return err_payload(
            "Slicing returned no G-code. " + "; ".join(warnings),
            error_code or "SLICE_ERROR",
        )

    # Return a preview of the first 50 lines so the LLM doesn't receive the
    # entire G-code blob (which can be several MB).
    preview_lines = gcode.splitlines()[:50]
    gcode_preview = "\n".join(preview_lines)

    return ok_payload({
        "layer_count":   result.get("layer_count", 0),
        "print_time_s":  result.get("print_time_s"),
        "filament_mm":   result.get("filament_mm"),
        "gcode_preview": gcode_preview,
        "gcode_bytes":   result.get("gcode_bytes", 0),
        "warnings":      warnings,
    })
