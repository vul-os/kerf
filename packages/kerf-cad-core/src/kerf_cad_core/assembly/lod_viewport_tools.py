"""
kerf_cad_core.assembly.lod_viewport_tools — Wave 8 LLM tool for viewport LOD planning.

Wave 8 module
-------------
  kerf_cad_core.assembly.lod_viewport_bridge

Tool registered
---------------
  assembly_plan_viewport_lods — Assign camera-distance-driven LOD tiers to
    assembly components for the frontend renderer.

References
----------
Akenine-Möller, T., Haines, E. & Hoffman, N. (2018) "Real-Time Rendering",
    4th ed., CRC Press, §19.9 Level of Detail.
Clark, J.H. (1976) "Hierarchical Geometric Models for Visible Surface Algorithms",
    CACM 19(10):547-554.
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.assembly.lod_viewport_bridge import (
    ViewportLodAssignment,
    ViewportLodRequest,
    plan_viewport_lods,
)


# ---------------------------------------------------------------------------
# Tool: assembly_plan_viewport_lods
# ---------------------------------------------------------------------------

_assembly_plan_viewport_lods_spec = ToolSpec(
    name="assembly_plan_viewport_lods",
    description=(
        "Compute per-component viewport LOD tier assignments for an assembly,\n"
        "based on camera distance relative to bounding-box diagonal.\n"
        "\n"
        "Tier rules (d = camera distance to bbox centroid, diag = bbox diagonal):\n"
        "  d < 5×diag   → 'high'   (_lod0.glb, full triangles)\n"
        "  5–20×diag    → 'mid'    (_lod1.glb, ¼ triangles)\n"
        "  20–100×diag  → 'low'    (_lod2.glb, 1/16 triangles)\n"
        "  > 100×diag   → 'culled' (not rendered)\n"
        "\n"
        "Demotion rule: if total component count > 500, every assignment\n"
        "is demoted one tier (high→mid, mid→low, low→culled).\n"
        "\n"
        "Returns per component:\n"
        "  component_id        — original id\n"
        "  tier                — 'high' | 'mid' | 'low' | 'culled'\n"
        "  target_triangle_count — int\n"
        "  mesh_url_suffix     — '_lod0.glb' | '_lod1.glb' | '_lod2.glb' | ''\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "description": (
                    "List of component LOD request objects. Each must have:\n"
                    "  component_id: str\n"
                    "  bbox_min: [xmin, ymin, zmin]\n"
                    "  bbox_max: [xmax, ymax, zmax]\n"
                    "  mesh_triangle_count: int\n"
                    "  camera_position: [x, y, z]\n"
                    "Optional:\n"
                    "  target_fps: float (default 60)\n"
                    "  total_part_count: int (default = len(components))"
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["components"],
    },
)


@register(_assembly_plan_viewport_lods_spec, write=False)
async def run_assembly_plan_viewport_lods(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    comps_raw = a.get("components")
    if not isinstance(comps_raw, list):
        return err_payload("components must be an array", "BAD_ARGS")
    if len(comps_raw) == 0:
        return err_payload("components must be non-empty", "BAD_ARGS")

    total_count = len(comps_raw)

    requests: list[ViewportLodRequest] = []
    for i, comp in enumerate(comps_raw):
        if not isinstance(comp, dict):
            return err_payload(f"components[{i}] must be an object", "BAD_ARGS")
        try:
            req = ViewportLodRequest(
                component_id=str(comp["component_id"]),
                bbox_min=tuple(float(x) for x in comp["bbox_min"]),
                bbox_max=tuple(float(x) for x in comp["bbox_max"]),
                mesh_triangle_count=int(comp["mesh_triangle_count"]),
                camera_position=tuple(float(x) for x in comp["camera_position"]),
                target_fps=float(comp.get("target_fps", 60.0)),
                total_part_count=int(comp.get("total_part_count", total_count)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(
                f"components[{i}] missing or invalid field: {exc}", "BAD_ARGS"
            )
        requests.append(req)

    try:
        assignments: list[ViewportLodAssignment] = plan_viewport_lods(requests)
    except Exception as exc:
        return err_payload(f"LOD planning error: {exc}", "EVAL_ERROR")

    result = [
        {
            "component_id": asgn.component_id,
            "tier": asgn.tier,
            "target_triangle_count": asgn.target_triangle_count,
            "mesh_url_suffix": asgn.mesh_url_suffix,
        }
        for asgn in assignments
    ]

    tier_counts = {"high": 0, "mid": 0, "low": 0, "culled": 0}
    for asgn in assignments:
        tier_counts[asgn.tier] = tier_counts.get(asgn.tier, 0) + 1

    return ok_payload({
        "assignments": result,
        "summary": tier_counts,
        "total_components": total_count,
    })


__all__ = ["run_assembly_plan_viewport_lods"]
