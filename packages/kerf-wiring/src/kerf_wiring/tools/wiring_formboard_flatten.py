"""
LLM tool: wiring_formboard_flatten

Flatten a 3D wiring harness graph into a 2D manufacturing formboard layout.

The formboard is the standard manufacturing output used to guide wire cutting,
nail-board routing, and connector assembly on the factory floor.  Lengths are
topologically preserved from the 3D routed harness.

Schema (input)
--------------
{
  "nodes": [{"id": "N1", "connector": "X1", "label": "..."}],
  "segments": [
    {
      "from": "N1", "to": "N2", "length_mm": 500.0,
      "wires": [{"name": "W1", "gauge_awg": 20, "color": "RD"}]
    }
  ],
  "root": "N1",           // optional — defaults to first node
  "connectors": {         // optional — connector pinout annotations
    "X1": {"pins": ["A1", "A2"], "label": "ECU Connector"}
  }
}

Returns (ok_payload)
--------------------
{
  "branches": [...],            // branch/tap points with 2D positions
  "wires": [...],               // wire table (id, from/to connector, gauge, length)
  "annotations": [...],         // connector pinouts + branch tap labels
  "bbox": [minX, minY, maxX, maxY],  // mm
  "trunk_path_mm": [[x, y], ...],    // main trunk 2D path
  "total_wire_length_mm": float
}
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_wiring._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore

from kerf_wiring.formboard_flatten import (
    FormboardError,
    formboard_flatten,
    formboard_to_dict,
)


wiring_formboard_flatten_spec = ToolSpec(
    name="wiring_formboard_flatten",
    description=(
        "Flatten a 3D wiring harness into a 2D manufacturing formboard layout. "
        "Provide the harness graph (nodes + segments with arc-lengths and wire lists). "
        "Returns the 2D board layout with branch points, wire table, connector "
        "pinout annotations, and bounding box. "
        "The main trunk is the longest path from the root connector, laid "
        "horizontally; side branches unfold as stubs at their tap points. "
        "Total wire lengths are preserved exactly from the 3D harness. "
        "Raises an error if the harness graph contains a cycle."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "connector": {
                            "type": "string",
                            "description": "Connector id at this node (optional)",
                        },
                        "label": {"type": "string"},
                    },
                    "required": ["id"],
                },
                "description": "Harness graph nodes (connectors, branch points, terminations).",
            },
            "segments": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "length_mm": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "description": "Arc-length of this segment in mm.",
                        },
                        "wires": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "gauge_awg": {
                                        "type": "integer",
                                        "minimum": 0,
                                        "maximum": 40,
                                    },
                                    "diameter_mm": {
                                        "type": "number",
                                        "exclusiveMinimum": 0,
                                    },
                                    "color": {"type": "string"},
                                    "label": {"type": "string"},
                                },
                            },
                            "description": "Wires routed through this segment.",
                        },
                    },
                    "required": ["from", "to", "length_mm"],
                },
                "description": (
                    "Harness graph segments. Each segment connects two nodes with "
                    "an arc-length (mm) and optional wire list."
                ),
            },
            "root": {
                "type": "string",
                "description": (
                    "Node id of the root connector / main starting point. "
                    "Defaults to the first node in the nodes list."
                ),
            },
            "connectors": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "pins": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "label": {"type": "string"},
                    },
                },
                "description": (
                    "Optional connector pinout info keyed by connector id. "
                    "Generates pinout annotations on the formboard."
                ),
            },
        },
        "required": ["nodes", "segments"],
    },
)


@register(wiring_formboard_flatten_spec, write=False)
async def wiring_formboard_flatten(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

    nodes = a.get("nodes")
    segments = a.get("segments")

    if not isinstance(nodes, list) or len(nodes) < 1:
        return err_payload("nodes must be a non-empty array", "BAD_ARGS")
    if not isinstance(segments, list) or len(segments) < 1:
        return err_payload("segments must be a non-empty array", "BAD_ARGS")

    harness_3d = {
        "nodes": nodes,
        "segments": segments,
    }
    if "root" in a:
        harness_3d["root"] = a["root"]
    if "connectors" in a:
        harness_3d["connectors"] = a["connectors"]

    try:
        fb = formboard_flatten(harness_3d)
    except FormboardError as exc:
        return err_payload(str(exc), "FORMBOARD_ERROR")
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"formboard flatten error: {exc}", "ERROR")

    return ok_payload(formboard_to_dict(fb))
