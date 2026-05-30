"""
kerf_mold.vent_placement_tool -- LLM tool wrapper for air-vent placement.

Tool: mold_optimize_vent_placement
  Recommend air-vent locations for an injection-mold cavity.  Vents allow
  trapped air to escape as the polymer melt fills the cavity.  Candidates
  are ranked by proximity to last-fill zones (Beaumont §8.4.1), parting-line
  rib positions (§8.4.2), and sharp-corner pockets (§8.4.3).  Vent depth is
  material-specific per Beaumont 2007 Table 8.4.

SCOPE: Geometric heuristic only.  Does NOT model actual melt-front progression,
       viscosity, packing pressure, or flash risk.
       For production use Moldflow / Moldex3D / SigmaSoft.

References:
  Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §8.4 + Table 8.4.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_vent_placement_spec = ToolSpec(
    name="mold_optimize_vent_placement",
    description=(
        "Recommend air-vent locations for an injection-mold cavity. "
        "Vents allow trapped air and gas to escape as molten plastic fills the cavity. "
        "Identifies last-fill zones (corners farthest from the gate), parting-line rib "
        "positions, and sharp-corner pockets. Returns vent positions, material-specific "
        "vent depths (Beaumont 2007 Table 8.4), and advisory notes. "
        "Ref: Beaumont 2007 §8.4 (mold venting) + Table 8.4 (vent depth per material). "
        "HONEST FLAG: geometric heuristic -- does NOT model melt-front simulation, "
        "viscosity, flash risk, or packing pressure. "
        "For production use Moldflow / Moldex3D / SigmaSoft."
    ),
    input_schema={
        "type": "object",
        "required": ["width_mm", "depth_mm", "height_mm", "gate_x", "gate_y", "gate_z"],
        "properties": {
            "width_mm": {
                "type": "number",
                "description": "Cavity bounding-box X dimension (mm). Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "depth_mm": {
                "type": "number",
                "description": "Cavity bounding-box Y dimension (mm). Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "height_mm": {
                "type": "number",
                "description": "Cavity bounding-box Z dimension (mm). Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "gate_x": {
                "type": "number",
                "description": "Gate position X coordinate (mm) in cavity coordinate system.",
            },
            "gate_y": {
                "type": "number",
                "description": "Gate position Y coordinate (mm) in cavity coordinate system.",
            },
            "gate_z": {
                "type": "number",
                "description": "Gate position Z coordinate (mm) in cavity coordinate system.",
            },
            "material": {
                "type": "string",
                "description": (
                    "Material name to select vent depth from Beaumont Table 8.4. "
                    "Examples: 'ABS', 'PP', 'PE', 'PC', 'PMMA', 'POM', 'PA', 'PA66', "
                    "'PBT', 'PET', 'LCP', 'PPS', 'TPE', 'TPU'. "
                    "Defaults to 'ABS' (0.025-0.040 mm depth range)."
                ),
                "default": "ABS",
            },
            "max_vents": {
                "type": "integer",
                "description": "Maximum number of vents to recommend. Default 8.",
                "minimum": 1,
                "default": 8,
            },
            "include_parting_ribs": {
                "type": "boolean",
                "description": (
                    "Include parting-line rib vent candidates (Beaumont §8.4.2). "
                    "Default true."
                ),
                "default": True,
            },
            "include_corner_vents": {
                "type": "boolean",
                "description": (
                    "Include sharp-corner pocket vent candidates (Beaumont §8.4.3). "
                    "Default true."
                ),
                "default": True,
            },
            "avoid_zones": {
                "type": "array",
                "description": (
                    "List of forbidden spheres [[cx, cy, cz, radius_mm], ...] "
                    "in the cavity coordinate system. Vent candidates within "
                    "these zones are excluded (functional/cosmetic surfaces)."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "default": [],
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_optimize_vent_placement(
    args: dict,
    ctx: "ProjectCtx",
) -> str:
    try:
        from kerf_mold.vent_placement import (
            CavityBbox,
            optimize_vent_placement,
        )

        # -- Parse required dimensions ----------------------------------------
        try:
            width_mm  = float(args["width_mm"])
            depth_mm  = float(args["depth_mm"])
            height_mm = float(args["height_mm"])
            gate_x    = float(args["gate_x"])
            gate_y    = float(args["gate_y"])
            gate_z    = float(args["gate_z"])
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"Invalid cavity/gate dimensions: {exc}", "BAD_ARGS")

        material   = str(args.get("material") or "ABS")
        max_vents  = int(args.get("max_vents", 8))
        if max_vents < 1:
            return err_payload("max_vents must be >= 1", "BAD_ARGS")

        include_parting = bool(args.get("include_parting_ribs", True))
        include_corners = bool(args.get("include_corner_vents", True))

        avoid_zones_raw = args.get("avoid_zones") or []
        try:
            avoid_zones = [
                (float(z[0]), float(z[1]), float(z[2]), float(z[3]))
                for z in avoid_zones_raw
            ]
        except (TypeError, ValueError, IndexError) as exc:
            return err_payload(f"Invalid avoid_zones: {exc}", "BAD_ARGS")

        # -- Build objects ----------------------------------------------------
        try:
            bbox = CavityBbox(
                width_mm=width_mm,
                depth_mm=depth_mm,
                height_mm=height_mm,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        gate_position = (gate_x, gate_y, gate_z)

        result = optimize_vent_placement(
            cavity_bbox=bbox,
            gate_position=gate_position,
            material=material,
            max_vents=max_vents,
            include_parting_ribs=include_parting,
            include_corner_vents=include_corners,
            avoid_functional_zones=avoid_zones,
        )

        payload = {
            "ok": True,
            "vent_positions": [
                [round(v, 3) for v in pos]
                for pos in result.vent_positions
            ],
            "vent_locations": [
                {
                    "position": [round(v, 3) for v in vl.position],
                    "reason": vl.reason,
                    "depth_min_mm": vl.depth_min_mm,
                    "depth_max_mm": vl.depth_max_mm,
                    "recommended_depth_mm": vl.recommended_depth_mm,
                    "land_length_mm": vl.land_length_mm,
                    "priority": vl.priority,
                    "distance_from_gate_mm": vl.distance_from_gate_mm,
                    "advisory": vl.advisory,
                }
                for vl in result.vent_locations
            ],
            "depth_per_material": result.depth_per_material,
            "count": result.count,
            "recommendations": result.recommendations,
            "warnings": result.warnings,
            "reference": "Beaumont 2007 §8.4; Table 8.4",
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "VENT_PLACEMENT_ERROR")
