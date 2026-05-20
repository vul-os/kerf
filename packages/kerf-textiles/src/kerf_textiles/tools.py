"""
kerf_textiles.tools
===================
LLM tool spec + handler for textiles_generate.
"""

from __future__ import annotations

from typing import Any

textiles_generate_spec = {
    "name": "textiles_generate",
    "description": (
        "Generate a textile weave or knit structure. "
        "Returns the cell matrix, float/density statistics, and SVG preview."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["weave", "knit"],
                "description": "Whether to generate a weave or knit structure.",
            },
            "structure": {
                "type": "string",
                "description": (
                    "For weave: 'plain', 'twill', 'satin', 'jacquard'. "
                    "For knit: 'jersey', 'rib', 'interlock'."
                ),
            },
            "params": {
                "type": "object",
                "description": "Structure-specific parameters (over, under, shafts, gauge, etc.).",
            },
        },
        "required": ["type", "structure"],
    },
}


async def run_textiles_generate(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for the textiles_generate LLM tool."""
    gen_type = params.get("type", "weave")
    structure = params.get("structure", "plain")
    extra = params.get("params", {}) or {}

    if gen_type == "weave":
        from kerf_textiles.weave import plain_weave, twill_weave, satin_weave
        from kerf_textiles.export import weave_to_svg, weave_to_json
        import json

        if structure == "plain":
            result = plain_weave()
        elif structure == "twill":
            result = twill_weave(
                over=extra.get("over", 2),
                under=extra.get("under", 1),
                direction=extra.get("direction", "RH"),
            )
        elif structure == "satin":
            result = satin_weave(
                shafts=extra.get("shafts", 5),
                move=extra.get("move", 2),
            )
        else:
            return {"error": f"unknown weave structure: {structure}"}

        return {
            "name": result.name,
            "float_stats": result.float_stats,
            "analytic_warp_mean_float": result.analytic_warp_mean_float,
            "analytic_weft_mean_float": result.analytic_weft_mean_float,
            "svg": weave_to_svg(result),
        }

    elif gen_type == "knit":
        from kerf_textiles.knit import jersey_knit, rib_knit, interlock_knit
        from kerf_textiles.export import knit_to_svg

        gauge = extra.get("gauge", 5.0)
        courses_per_cm = extra.get("courses_per_cm", 7.0)
        needles = extra.get("needles", 10)
        courses = extra.get("courses", 10)

        if structure == "jersey":
            result = jersey_knit(needles=needles, courses=courses,
                                 gauge=gauge, courses_per_cm=courses_per_cm)
        elif structure == "rib":
            result = rib_knit(
                knit_count=extra.get("knit_count", 1),
                purl_count=extra.get("purl_count", 1),
                needles=needles, courses=courses,
                gauge=gauge, courses_per_cm=courses_per_cm,
            )
        elif structure == "interlock":
            result = interlock_knit(needles=needles, courses=courses,
                                    gauge=gauge, courses_per_cm=courses_per_cm)
        else:
            return {"error": f"unknown knit structure: {structure}"}

        return {
            "name": result.name,
            "density_stats": result.density_stats,
            "svg": knit_to_svg(result),
        }

    return {"error": f"unknown type: {gen_type}"}
