"""
kerf_mold.gate_placement_tool — LLM tool wrapper for gate placement optimisation.

Tool: mold_optimize_gate_placement
  Propose optimal injection-gate position(s) for a mold cavity bounding box.
  Scores candidates by max flow path length + fill-balance variance, applies
  functional-surface / avoid-zone constraints, and returns ranked positions
  with advisory recommendations.

SCOPE: Geometric heuristic only (Beaumont 2007 §7; Menges 2001 §6.6).
       Does NOT model viscosity, shear thinning, weld-line position, or warpage.

References:
  Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §7.
  Menges, G., Michaeli, W., Mohren, P. (2001). *How to Make Injection Molds*, 3rd ed., §6.6.
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

mold_gate_placement_spec = ToolSpec(
    name="mold_optimize_gate_placement",
    description=(
        "Propose optimal injection-gate location(s) for a mold cavity. "
        "For a given cavity bounding box, samples candidate gate positions "
        "(top-center, side-edge, bottom, multi-gate equidistant seeds), "
        "scores each by Euclidean max-flow-length and fill-balance variance, "
        "applies functional-surface / avoid-zone constraints, and returns "
        "ranked gate positions with advisory recommendations. "
        "Ref: Beaumont 2007 §7 (gate design); Menges 2001 §6.6 (gate location). "
        "HONEST FLAG: geometric heuristic only — does NOT model viscosity, "
        "shear thinning, packing pressure, weld-line, or warpage. "
        "For production use Moldflow / Moldex3D / SigmaSoft."
    ),
    input_schema={
        "type": "object",
        "required": ["width_mm", "depth_mm", "height_mm"],
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
            "gate_count": {
                "type": "integer",
                "description": "Number of gates to place. Default 1. Use > 1 for large/thin parts.",
                "minimum": 1,
                "default": 1,
            },
            "functional_faces": {
                "type": "array",
                "description": (
                    "Face labels where gates are forbidden (functional/cosmetic surfaces). "
                    "Valid values: 'top', 'bottom', 'left', 'right', 'front', 'back'."
                ),
                "items": {
                    "type": "string",
                    "enum": ["top", "bottom", "left", "right", "front", "back"],
                },
                "default": [],
            },
            "avoid_zones": {
                "type": "array",
                "description": (
                    "List of forbidden spheres [[cx, cy, cz, radius_mm], ...] "
                    "in the cavity coordinate system.  Gate candidates within "
                    "these spheres are removed."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "default": [],
            },
            "allow_underside_gates": {
                "type": "boolean",
                "description": (
                    "If false (default), bottom-face gates receive a 20 % score "
                    "penalty but are not hard-removed."
                ),
                "default": False,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_optimize_gate_placement(
    args: dict[str, Any],
    ctx: "ProjectCtx",
) -> str:
    try:
        from kerf_mold.gate_placement import (
            CavityBbox,
            GateConstraint,
            optimize_gate_placement,
        )

        # ── Parse required dimensions ───────────────────────────────────────
        try:
            width_mm = float(args["width_mm"])
            depth_mm = float(args["depth_mm"])
            height_mm = float(args["height_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"Invalid cavity dimensions: {exc}", "BAD_ARGS")

        gate_count = int(args.get("gate_count", 1))
        if gate_count < 1:
            return err_payload("gate_count must be >= 1", "BAD_ARGS")

        # ── Parse optional constraints ──────────────────────────────────────
        functional_faces = list(args.get("functional_faces") or [])
        avoid_zones_raw = args.get("avoid_zones") or []
        allow_underside = bool(args.get("allow_underside_gates", False))

        try:
            avoid_zones = [
                (float(z[0]), float(z[1]), float(z[2]), float(z[3]))
                for z in avoid_zones_raw
            ]
        except (TypeError, ValueError, IndexError) as exc:
            return err_payload(f"Invalid avoid_zones: {exc}", "BAD_ARGS")

        # ── Build objects ───────────────────────────────────────────────────
        try:
            bbox = CavityBbox(
                width_mm=width_mm,
                depth_mm=depth_mm,
                height_mm=height_mm,
            )
            constraints = GateConstraint(
                functional_faces=functional_faces,
                avoid_zones=avoid_zones,
                allow_underside_gates=allow_underside,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        result = optimize_gate_placement(
            cavity_bbox=bbox,
            constraints=constraints,
            gate_count=gate_count,
        )

        payload: dict[str, Any] = {
            "ok": True,
            "gate_positions": [
                [round(v, 3) for v in pos]
                for pos in result.gate_positions
            ],
            "gate_count": result.gate_count,
            "flow_metrics": result.flow_metrics,
            "balance_score": result.balance_score,
            "multi_gate_suggested": result.multi_gate_suggested,
            "recommendations": result.recommendations,
            "warnings": result.warnings,
            "candidates_evaluated": result.candidates_evaluated,
            "reference": "Beaumont 2007 §7; Menges 2001 §6.6",
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "GATE_PLACEMENT_ERROR")
