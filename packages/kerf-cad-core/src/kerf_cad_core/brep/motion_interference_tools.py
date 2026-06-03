"""
kerf_cad_core.brep.motion_interference_tools — LLM tool wrapper for assembly
motion interference sweep.

Tool
----
assembly_motion_interference
    Sweep the assembly clash detector over a multi-body motion timeline,
    report per-frame collisions, and return a timeline of merged
    interference events.

Input schema
------------
{
  "bodies": {
    "<body_id>": {
      "bbox_min": [x, y, z],    // local-frame AABB min corner (mm)
      "bbox_max": [x, y, z],    // local-frame AABB max corner (mm)
      "triangles": [...]         // optional [[v0,v1,v2],...] in local frame
    },
    ...
  },
  "timeline": [
    {
      "t": 0.0,                  // time in seconds
      "transforms": {
        "<body_id>": [16 floats] // row-major 4×4 world transform
      }
    },
    ...
  ],
  "coarse_bbox_only": false     // optional; default false
}

Output payload
--------------
{
  "ok": true,
  "events": [
    {
      "component_a": "arm",
      "component_b": "housing",
      "t_start": 0.3,
      "t_end": 0.7,
      "max_penetration_mm": 1.42,
      "penetration_point": [x, y, z]
    }
  ],
  "frames_swept": 10,
  "total_collision_frames": 4,
  "clearance_min_mm": 0.35,
  "bodies_at_min_clearance": ["body_a", "body_b"],
  "errors": []
}

Author: imranparuk
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.brep.motion_interference import (
    MotionFrame,
    sweep_motion_interference,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_spec = ToolSpec(
    name="assembly_motion_interference",
    description=(
        "Sweep the assembly clash detector over a multi-body motion timeline "
        "and report all interference events.\n"
        "\n"
        "For each frame in the timeline the tool applies every body's 4×4 "
        "world transform and runs a broad-phase AABB + narrow-phase OBB SAT "
        "(optionally triangle-level) pairwise clash test.  Consecutive "
        "collision frames for the same pair are merged into "
        "InterferenceEvent intervals with t_start / t_end and maximum "
        "penetration depth.\n"
        "\n"
        "Also reports the minimum clearance gap across all non-colliding "
        "pair/frame combinations — useful for design clearance QA.\n"
        "\n"
        "Inputs:\n"
        "  bodies          — dict of body_id → geometry descriptor with\n"
        "                    bbox_min, bbox_max (local-frame mm) and optional\n"
        "                    triangles list for narrow-phase.\n"
        "  timeline        — ordered list of {t, transforms} frames; each\n"
        "                    transforms maps body_id → 16-float 4×4 matrix.\n"
        "  coarse_bbox_only — when true, only AABB overlap is tested "
        "(faster, conservative).\n"
        "\n"
        "Returns ok=true even when interference is found; errors list "
        "captures non-fatal input issues."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bodies": {
                "type": "object",
                "description": (
                    "Dict of body_id → geometry descriptor. "
                    "Each descriptor has bbox_min [x,y,z], bbox_max [x,y,z] "
                    "in local (body) frame (mm), and optional triangles list."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "bbox_min": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Local-frame AABB min corner [x,y,z] in mm.",
                        },
                        "bbox_max": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Local-frame AABB max corner [x,y,z] in mm.",
                        },
                        "triangles": {
                            "type": "array",
                            "description": "Optional triangle mesh [[v0,v1,v2],...] in local frame.",
                        },
                    },
                    "required": ["bbox_min", "bbox_max"],
                },
            },
            "timeline": {
                "type": "array",
                "description": "Ordered list of motion frames.",
                "items": {
                    "type": "object",
                    "properties": {
                        "t": {
                            "type": "number",
                            "description": "Frame time in seconds.",
                        },
                        "transforms": {
                            "type": "object",
                            "description": (
                                "Dict of body_id → 16-float row-major 4×4 "
                                "world transform at this frame."
                            ),
                        },
                    },
                    "required": ["t", "transforms"],
                },
            },
            "coarse_bbox_only": {
                "type": "boolean",
                "description": (
                    "When true, only AABB overlap is checked (fast conservative mode). "
                    "Default false."
                ),
            },
        },
        "required": ["bodies", "timeline"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register(_spec, write=False)
async def run_assembly_motion_interference(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_bodies = a.get("bodies")
    raw_timeline = a.get("timeline")
    coarse = bool(a.get("coarse_bbox_only", False))

    if raw_bodies is None:
        return err_payload("'bodies' is required", "BAD_ARGS")
    if not isinstance(raw_bodies, dict):
        return err_payload("'bodies' must be an object (dict)", "BAD_ARGS")
    if raw_timeline is None:
        return err_payload("'timeline' is required", "BAD_ARGS")
    if not isinstance(raw_timeline, list):
        return err_payload("'timeline' must be an array", "BAD_ARGS")

    errors: list[str] = []

    # Parse timeline into MotionFrame objects.
    frames: list[MotionFrame] = []
    for idx, entry in enumerate(raw_timeline):
        if not isinstance(entry, dict):
            errors.append(f"timeline[{idx}]: expected object, got {type(entry).__name__}")
            continue
        t_val = entry.get("t")
        transforms_val = entry.get("transforms")
        if t_val is None:
            errors.append(f"timeline[{idx}]: 't' is required")
            continue
        if transforms_val is None:
            errors.append(f"timeline[{idx}]: 'transforms' is required")
            continue
        try:
            frames.append(MotionFrame(t=float(t_val), component_transforms=transforms_val))
        except Exception as exc:
            errors.append(f"timeline[{idx}]: {exc}")

    try:
        report = sweep_motion_interference(
            bodies=raw_bodies,
            frames=frames,
            coarse_bbox_only=coarse,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"sweep error: {exc}", "INTERNAL_ERROR")

    payload = report.to_dict()
    payload["ok"] = True
    payload["errors"] = errors

    return ok_payload(payload)


# ---------------------------------------------------------------------------
# Module-level TOOLS export (consumed by plugin registry in Wave 9A)
# ---------------------------------------------------------------------------

TOOLS = [("assembly_motion_interference", _spec, run_assembly_motion_interference)]

__all__ = ["run_assembly_motion_interference", "TOOLS"]
