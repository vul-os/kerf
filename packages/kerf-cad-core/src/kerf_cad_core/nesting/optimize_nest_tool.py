"""
kerf_cad_core.nesting.optimize_nest_tool — LLM tool registration for
manufacturing_optimize_nest (NFP + GA nesting optimizer).

Registered as: ``manufacturing_optimize_nest``

Author: imranparuk
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.nesting.optimize_nest import manufacturing_optimize_nest as _optimize_nest


_spec = ToolSpec(
    name="manufacturing_optimize_nest",
    description=(
        "NFP + Genetic-Algorithm nesting optimizer for sheet metal / CNC work. "
        "Given a sheet (width × height) and a list of arbitrary-polygon parts with "
        "quantities, packs as many parts as possible into the sheet using: "
        "(1) No-Fit Polygon (NFP) true-shape feasibility (Minkowski-sum, Sergyán 2009); "
        "(2) bottom-left-fill heuristic (Burke 2006); "
        "(3) Genetic Algorithm over placement sequence + rotation (Kovacs 2002), "
        "50 generations, population 40 by default. "
        "\n"
        "HONEST FLAGS: "
        "  - GA is stochastic; pass seed for reproducibility. "
        "  - Curved edges (arcs, splines) must be pre-approximated as polylines. "
        "  - Concave NFPs use convex-hull over-approximation (no false overlaps). "
        "  - runtime_budget_ms can cap execution for large inputs. "
        "\n"
        "Returns: {ok, placements:[{name,rotation,x,y,vertices}], "
        "utilization, utilization_pct, placed_count, total_count, "
        "runtime_ms, generations_run, seed, errors:[]}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sheet": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": "Sheet [width, height] in mm.",
            },
            "parts": {
                "type": "array",
                "description": (
                    "Parts to nest. Each: "
                    "{name (str), vertices ([[x,y],...] >= 3 pts), "
                    "qty (int, default 1)}. "
                    "Curved edges must be pre-approximated as polylines."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "vertices": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            "minItems": 3,
                        },
                        "qty": {"type": "integer", "minimum": 1},
                    },
                    "required": ["name", "vertices"],
                },
            },
            "options": {
                "type": "object",
                "description": (
                    "GA/placement parameters: "
                    "generations (int, default 50), "
                    "population_size (int, default 40), "
                    "rotation_step (degrees: 4→{0,90,180,270}, 12→{0,30,...,330}), "
                    "grid_step (float mm, default 5.0), "
                    "seed (int — reproducibility; HONEST: stochastic), "
                    "runtime_budget_ms (float, 0=no limit), "
                    "crossover_rate (float, default 0.85), "
                    "mutation_rate (float, default 0.15)."
                ),
                "properties": {
                    "generations":       {"type": "integer", "minimum": 1},
                    "population_size":   {"type": "integer", "minimum": 2},
                    "rotation_step":     {"type": "integer", "minimum": 1},
                    "grid_step":         {"type": "number",  "minimum": 0.1},
                    "seed":              {"type": "integer"},
                    "runtime_budget_ms": {"type": "number",  "minimum": 0},
                    "crossover_rate":    {"type": "number"},
                    "mutation_rate":     {"type": "number"},
                },
            },
        },
        "required": ["sheet", "parts"],
    },
)


@register(_spec, write=False)
async def run_manufacturing_optimize_nest(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    sheet = a.get("sheet")
    parts = a.get("parts")

    if not isinstance(sheet, (list, tuple)) or len(sheet) != 2:
        return err_payload("sheet must be [width, height]", "BAD_ARGS")
    if not isinstance(parts, list):
        return err_payload("parts must be a list", "BAD_ARGS")

    try:
        sheet = (float(sheet[0]), float(sheet[1]))
    except (TypeError, ValueError) as exc:
        return err_payload(f"sheet dimensions must be numeric: {exc}", "BAD_ARGS")

    options = a.get("options") or {}

    result = _optimize_nest(sheet=sheet, parts=parts, options=options)
    return ok_payload(result)
