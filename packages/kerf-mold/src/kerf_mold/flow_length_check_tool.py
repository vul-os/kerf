"""
kerf_mold.flow_length_check_tool
==================================
LLM tool wrapper for the flow-length-to-wall-thickness (L/T) ratio checker.

Registers:
  mold_check_flow_length — compute L/T ratio per cavity feature and classify
                           short-shot risk (Beaumont 2007 §4 Table 4.2 +
                           Menges 2001 §6.2.1).

Errors returned as {"ok": false, "code": "...", "reason": "..."} — never raises.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007, §4.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.2.1.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.flow_length_check import (
    FlowFeature,
    MATERIAL_LT_LIMITS,
    compute_flow_length_check,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_check_flow_length_spec = ToolSpec(
    name="mold_check_flow_length",
    description=(
        "Compute the flow-length-to-wall-thickness (L/T) ratio per cavity "
        "feature and classify the short-shot risk "
        "(Beaumont 2007 §4 Table 4.2 + Menges 2001 §6.2.1).\n\n"
        "For each feature:\n"
        "  lt_ratio = flow_length_mm / wall_thickness_mm\n\n"
        "Risk classification against the material handbook limit:\n"
        "  safe        — lt_ratio ≤ 80 % of limit\n"
        "  caution     — 80–100 % of limit\n"
        "  short_shot  — > 100 % of limit (fill predicted to fail)\n\n"
        "Built-in material limits (Beaumont 2007 Table 4.2):\n"
        "  ABS=150, PC=220, PP=300, PA66=250, POM=200, PMMA=180\n\n"
        "Returns: {ok, feature_results[{id, lt_ratio, material_lt_limit, "
        "utilisation_fraction, risk, detail}], worst_feature_id, "
        "recommended_min_thickness_mm, honest_caveat}.\n\n"
        "Honest caveat: L/T ratio check only — does NOT simulate viscous "
        "pressure drop, melt-front temperature, injection-speed sensitivity, "
        "or multi-gate flow balance. Use Moldflow/Moldex3D/SigmaSoft for full "
        "fill simulation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "features": {
                "type": "array",
                "description": (
                    "List of cavity features to evaluate. Each item: "
                    "{id, flow_length_mm, wall_thickness_mm, material_grade}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique feature identifier, e.g. 'rib_01'.",
                        },
                        "flow_length_mm": {
                            "type": "number",
                            "description": (
                                "Gate-to-farthest-point flow path length (mm). "
                                "Must be > 0."
                            ),
                        },
                        "wall_thickness_mm": {
                            "type": "number",
                            "description": (
                                "Nominal wall thickness of the flow path (mm). "
                                "Must be > 0."
                            ),
                        },
                        "material_grade": {
                            "type": "string",
                            "description": (
                                "Material grade: ABS, PC, PP, PA66, POM, PMMA "
                                "(case-insensitive). Pass custom grades via "
                                "material_db_override."
                            ),
                        },
                    },
                    "required": [
                        "id",
                        "flow_length_mm",
                        "wall_thickness_mm",
                        "material_grade",
                    ],
                },
            },
            "material_db_override": {
                "type": "object",
                "description": (
                    "Optional dict extending the built-in material L/T limits. "
                    "Keys are material grade strings (e.g. 'PEEK'), values are "
                    "L/T limit floats. Overrides built-in values if keys match."
                ),
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["features"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_check_flow_length(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_features = a.get("features", [])
    if not isinstance(raw_features, list) or len(raw_features) == 0:
        return err_payload("features must be a non-empty list", "BAD_ARGS")

    features = []
    for i, rf in enumerate(raw_features):
        try:
            feat = FlowFeature(
                id=str(rf["id"]),
                flow_length_mm=float(rf["flow_length_mm"]),
                wall_thickness_mm=float(rf["wall_thickness_mm"]),
                material_grade=str(rf["material_grade"]),
            )
        except (KeyError, TypeError) as exc:
            return err_payload(f"features[{i}]: missing or wrong-type field: {exc}", "BAD_ARGS")
        except ValueError as exc:
            return err_payload(f"features[{i}]: {exc}", "BAD_ARGS")
        features.append(feat)

    # Optional material override
    material_db_override = None
    raw_override = a.get("material_db_override")
    if raw_override is not None:
        if not isinstance(raw_override, dict):
            return err_payload(
                "material_db_override must be a JSON object {grade: limit}", "BAD_ARGS"
            )
        try:
            material_db_override = {k: float(v) for k, v in raw_override.items()}
        except (TypeError, ValueError) as exc:
            return err_payload(f"material_db_override value error: {exc}", "BAD_ARGS")

    try:
        report = compute_flow_length_check(
            features=features,
            material_db_override=material_db_override,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    return ok_payload({
        "ok": True,
        "feature_results": report.feature_results,
        "worst_feature_id": report.worst_feature_id,
        "recommended_min_thickness_mm": report.recommended_min_thickness_mm,
        "honest_caveat": report.honest_caveat,
    })
