"""
LLM tool: route_harness_3d

Routes a wire bundle along a 3-D polyline path (DMU primitive).

Schema:
  {
    "waypoints": [[x, y, z], ...],   # ≥ 2 points, mm
    "wire_list": [
      {
        "name": "...",           # optional
        "gauge_awg": 20,         # optional — AWG gauge
        "diameter_mm": 0.812,    # optional — overrides gauge_awg
        "count": 1               # optional — parallel wires
      },
      ...
    ]
  }

Returns:
  ok_payload({
    "waypoints": [[x,y,z], ...],
    "wires": [...],
    "bundle_diameter_mm": <float>,
    "length_mm": <float>,
    "segment_lengths_mm": [<float>, ...]
  })
  err_payload(...) on bad input.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_wiring._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore

from kerf_wiring.harness3d import harness_segment, segment_to_dict


route_harness_3d_spec = ToolSpec(
    name="route_harness_3d",
    description=(
        "Route a wiring bundle along a 3-D polyline path (DMU primitive). "
        "Provide an ordered list of (x, y, z) waypoints in mm and a wire list. "
        "Returns the bundle diameter derived from the wire cross-sections and "
        "the total routed path length. "
        "Use this as the primitive for 3-D harness layout before sweep/OCCT."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "waypoints": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": (
                    "Ordered 3-D waypoints [x, y, z] in mm. "
                    "At least 2 points required."
                ),
            },
            "wire_list": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "gauge_awg": {"type": "integer", "minimum": 0, "maximum": 40},
                        "diameter_mm": {"type": "number", "exclusiveMinimum": 0},
                        "count": {"type": "integer", "minimum": 1},
                    },
                },
                "description": (
                    "List of wire specs. Each entry may specify gauge_awg "
                    "(AWG 0–40), diameter_mm (explicit), and count (parallel "
                    "wires). Defaults to AWG 20 when neither gauge nor diameter "
                    "is given."
                ),
            },
        },
        "required": ["waypoints", "wire_list"],
    },
)


@register(route_harness_3d_spec, write=False)
async def route_harness_3d(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    waypoints = a.get("waypoints")
    wire_list = a.get("wire_list")

    if not isinstance(waypoints, list) or len(waypoints) < 2:
        return err_payload(
            "waypoints must be an array of at least 2 [x,y,z] points",
            "BAD_ARGS",
        )
    if not isinstance(wire_list, list) or len(wire_list) < 1:
        return err_payload("wire_list must be a non-empty array", "BAD_ARGS")

    try:
        seg = harness_segment(waypoints, wire_list)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"harness routing error: {exc}", "ERROR")

    return ok_payload(segment_to_dict(seg))
