"""
kerf_cad_core.materials.material_tools — LLM tool wrappers for Ashby material
selection (dataclass API).

Wave 12B: Ashby material selection

Registers five tools with the Kerf tool registry:

  ashby_list_materials      — list catalog entries (optionally by category)
  ashby_get_material        — full property record for one material
  ashby_select_materials    — multi-constraint + multi-objective selection
  ashby_build_chart         — return chart data for any two-property Ashby chart
  ashby_pareto_front        — non-dominated materials on a two-property front

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
* Ashby, M.F. (2017). "Materials Selection in Mechanical Design." 5th ed.,
  Butterworth-Heinemann.
* Ashby, M.F. (2018). "Materials: Engineering, Science, Processing, Design."
  4th ed., Butterworth-Heinemann.
* CES EduPack User Manual (Granta Material Intelligence; public references).

Author: imranparuk
"""
from __future__ import annotations

import dataclasses
import json
from functools import lru_cache

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.materials.material_db import (
    MaterialDatabase,
    default_engineering_materials_db,
)
from kerf_cad_core.materials.ashby_selection import (
    AshbyChart,
    SelectionConstraint,
    SelectionObjective,
    build_ashby_chart,
    pareto_front,
    select_materials,
)


# ---------------------------------------------------------------------------
# Shared DB (lazily cached; safe since the default DB is immutable)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _db() -> MaterialDatabase:
    return default_engineering_materials_db()


def _material_to_dict(mat) -> dict:
    """Convert a Material dataclass to a JSON-serialisable dict."""
    d = dataclasses.asdict(mat)
    # Convert thermal_expansion_per_k to µm/(m·K) for readability
    if "thermal_expansion_per_k" in d and d["thermal_expansion_per_k"] is not None:
        d["thermal_expansion_1e-6_per_k"] = round(
            d["thermal_expansion_per_k"] * 1e6, 4
        )
    return d


# ---------------------------------------------------------------------------
# Tool: ashby_list_materials
# ---------------------------------------------------------------------------

_list_spec = ToolSpec(
    name="ashby_list_materials",
    description=(
        "List materials in the Ashby engineering material catalog.\n"
        "\n"
        "Returns canonical name + category for each material. Optionally filter "
        "by category.\n"
        "\n"
        "Available categories: metal | polymer | ceramic | composite | natural\n"
        "\n"
        "The catalog (~55 entries) covers common engineering families:\n"
        "  Metals: steels (1018, 4140QT, 4340QT, 17-4PH, 304SS, 316L), aluminums\n"
        "    (1100, 2024, 6061, 7075), titanium (Ti-6Al-4V, CP-Ti), Mg-AZ31B,\n"
        "    copper alloys, cast irons, Inconel 718.\n"
        "  Polymers: PLA, ABS, PETG, PC, PA66, POM, PEEK, UHMWPE, HDPE, PTFE, PP.\n"
        "  Composites: CFRP unidirectional, CFRP quasi-isotropic, GFRP E-glass woven.\n"
        "  Ceramics: Al2O3 99%, SiC, ZrO2 TZP, Si3N4.\n"
        "  Natural: Oak, Pine, Bamboo.\n"
        "\n"
        "Source: Ashby 'Materials Selection in Mechanical Design' 5e (2017) Appendix A.\n"
        "HONEST: Curated representative subset; production decisions need Granta MI.\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": (
                    "Optional category filter: 'metal', 'polymer', 'ceramic', "
                    "'composite', 'natural'. Omit to list all."
                ),
            },
        },
        "required": [],
    },
)


@register(_list_spec, write=False)
async def run_ashby_list_materials(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    db = _db()
    category = a.get("category")

    if category:
        mats = db.by_category(category)
        if not mats:
            valid = sorted({m.category for m in db.materials})
            return err_payload(
                f"No materials in category {category!r}. Valid: {valid}",
                "NOT_FOUND",
            )
    else:
        mats = list(db.materials)

    items = [{"name": m.name, "category": m.category} for m in mats]
    return ok_payload({
        "ok": True,
        "count": len(items),
        "materials": items,
    })


# ---------------------------------------------------------------------------
# Tool: ashby_get_material
# ---------------------------------------------------------------------------

_get_spec = ToolSpec(
    name="ashby_get_material",
    description=(
        "Return full property record for one engineering material by name.\n"
        "\n"
        "Returns all properties: youngs_modulus_gpa, yield_strength_mpa, "
        "ultimate_strength_mpa, density_kg_m3, poisson, fatigue_endurance_mpa "
        "(null for ceramics), thermal_conductivity_w_m_k, thermal_expansion, "
        "specific_heat_j_kg_k, melting_point_c, max_service_temp_c, "
        "electrical_resistivity_ohm_m, cost_per_kg_usd, embodied_energy_mj_kg, "
        "co2_footprint_kg_co2_per_kg, recyclable_fraction_pct.\n"
        "\n"
        "Use ashby_list_materials to discover available names.\n"
        "\n"
        "Errors: {ok:false, reason} if not found. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Canonical material name, e.g. 'AA6061_T6', 'Ti-6Al-4V', "
                    "'CFRP_quasi_iso', 'PEEK'. Case-sensitive."
                ),
            },
        },
        "required": ["name"],
    },
)


@register(_get_spec, write=False)
async def run_ashby_get_material(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    name = a.get("name")
    if not name:
        return err_payload("'name' is required", "BAD_ARGS")

    db = _db()
    try:
        mat = db.by_name(name)
    except KeyError:
        names = [m.name for m in db.materials]
        return err_payload(
            f"Material {name!r} not found. Available: {sorted(names)}", "NOT_FOUND"
        )

    return ok_payload({"ok": True, "material": _material_to_dict(mat)})


# ---------------------------------------------------------------------------
# Tool: ashby_select_materials
# ---------------------------------------------------------------------------

_select_spec = ToolSpec(
    name="ashby_select_materials",
    description=(
        "Multi-constraint + multi-objective Ashby material selection.\n"
        "\n"
        "Implements the three-stage Cambridge Engineering Selector methodology "
        "(Ashby 2017 Ch. 5) equivalent to CES EduPack Level 2/3:\n"
        "  1. Screen by hard constraints.\n"
        "  2. Rank by performance indices (Ashby merit indices).\n"
        "  3. Return ranked results with constraint pass/fail details.\n"
        "\n"
        "Constraints: list of {property, operator, value} where operator is "
        "'>=' | '<=' | '>' | '<' | '=='.\n"
        "\n"
        "Objectives: list of {formula, direction, weight} where formula is a "
        "Python expression using Material attribute names, e.g.:\n"
        "  'youngs_modulus_gpa**0.5/density_kg_m3'  (lightest stiff beam)\n"
        "  'yield_strength_mpa/density_kg_m3'        (lightest strong tie)\n"
        "  'yield_strength_mpa**0.667/density_kg_m3' (lightest strong beam)\n"
        "  'youngs_modulus_gpa**0.5/(density_kg_m3*cost_per_kg_usd)' (cheapest stiff)\n"
        "\n"
        "Multi-objective via weighted-sum scalarisation (Ashby 2017 §9.3). "
        "Min-max normalisation ensures fair comparison across different units.\n"
        "\n"
        "HONEST: Representative ~55-material catalog; not Granta MI exhaustive DB.\n"
        "\n"
        "Returns top_k ranked results with score, rank, constraint details.\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "constraints": {
                "type": "array",
                "description": (
                    "Hard constraints: list of {property, operator, value}. "
                    "Example: [{\"property\": \"density_kg_m3\", \"operator\": \"<=\", "
                    "\"value\": 5000}]"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "property": {"type": "string"},
                        "operator": {
                            "type": "string",
                            "enum": [">=", "<=", ">", "<", "=="],
                        },
                        "value": {"type": "number"},
                    },
                    "required": ["property", "operator", "value"],
                },
            },
            "objectives": {
                "type": "array",
                "description": (
                    "Ranked objectives: list of {formula, direction, weight}. "
                    "Example: [{\"formula\": \"youngs_modulus_gpa**0.5/density_kg_m3\", "
                    "\"direction\": \"maximize\", \"weight\": 1.0}]"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "formula": {"type": "string"},
                        "direction": {
                            "type": "string",
                            "enum": ["maximize", "minimize"],
                        },
                        "weight": {"type": "number"},
                    },
                    "required": ["formula", "direction"],
                },
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of results to return (default 10).",
            },
        },
        "required": ["constraints", "objectives"],
    },
)


@register(_select_spec, write=False)
async def run_ashby_select_materials(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_constraints = a.get("constraints", [])
    raw_objectives = a.get("objectives", [])
    top_k = int(a.get("top_k", 10))

    if not raw_objectives:
        return err_payload("At least one objective is required", "BAD_ARGS")

    try:
        constraints = [
            SelectionConstraint(
                property=c["property"],
                operator=c["operator"],
                value=float(c["value"]),
            )
            for c in raw_constraints
        ]
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(f"Invalid constraint: {exc}", "BAD_ARGS")

    try:
        objectives = [
            SelectionObjective(
                formula=o["formula"],
                direction=o["direction"],
                weight=float(o.get("weight", 1.0)),
            )
            for o in raw_objectives
        ]
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(f"Invalid objective: {exc}", "BAD_ARGS")

    db = _db()
    try:
        results = select_materials(db, constraints, objectives, top_k=top_k)
    except Exception as exc:
        return err_payload(f"Selection failed: {exc}", "INTERNAL")

    out = []
    for r in results:
        out.append({
            "rank": r.rank,
            "name": r.material.name,
            "category": r.material.category,
            "score": round(r.score, 6),
            "constraints_satisfied": r.constraints_satisfied,
            "failed_constraints": r.failed_constraints,
        })

    return ok_payload({
        "ok": True,
        "count": len(out),
        "results": out,
    })


# ---------------------------------------------------------------------------
# Tool: ashby_build_chart
# ---------------------------------------------------------------------------

_chart_spec = ToolSpec(
    name="ashby_build_chart",
    description=(
        "Return data for an Ashby material-property bubble chart.\n"
        "\n"
        "Returns parallel arrays of x_values and y_values for all materials "
        "that have both properties defined. Suitable for log-log scatter plots "
        "(strength vs density, modulus vs density, etc.).\n"
        "\n"
        "Common Ashby charts (Ashby 2017 §4):\n"
        "  Strength vs Density : x='density_kg_m3', y='yield_strength_mpa'\n"
        "  Modulus vs Density  : x='density_kg_m3', y='youngs_modulus_gpa'\n"
        "  Strength vs Modulus : x='youngs_modulus_gpa', y='yield_strength_mpa'\n"
        "  Cost vs Density     : x='density_kg_m3', y='cost_per_kg_usd'\n"
        "  CO₂ vs Strength     : x='yield_strength_mpa', y='co2_footprint_kg_co2_per_kg'\n"
        "\n"
        "Any Material attribute name can be used as x_property or y_property.\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "x_property": {
                "type": "string",
                "description": "Material attribute name for x-axis, e.g. 'density_kg_m3'.",
            },
            "y_property": {
                "type": "string",
                "description": "Material attribute name for y-axis, e.g. 'yield_strength_mpa'.",
            },
        },
        "required": ["x_property", "y_property"],
    },
)


@register(_chart_spec, write=False)
async def run_ashby_build_chart(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    x_prop = a.get("x_property")
    y_prop = a.get("y_property")

    if not x_prop or not y_prop:
        return err_payload("'x_property' and 'y_property' are required", "BAD_ARGS")

    db = _db()
    try:
        chart = build_ashby_chart(db, x_prop, y_prop)
    except AttributeError as exc:
        return err_payload(f"Unknown property: {exc}", "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"Chart build failed: {exc}", "INTERNAL")

    # Validate arrays have same length (sanity check)
    assert len(chart.x_values) == len(chart.y_values) == len(chart.materials)

    labels = [m.name for m in chart.materials]
    categories = [m.category for m in chart.materials]

    return ok_payload({
        "ok": True,
        "x_property": chart.x_property,
        "y_property": chart.y_property,
        "log_x": chart.log_x,
        "log_y": chart.log_y,
        "count": len(labels),
        "labels": labels,
        "categories": categories,
        "x_values": [round(v, 6) for v in chart.x_values],
        "y_values": [round(v, 6) for v in chart.y_values],
    })


# ---------------------------------------------------------------------------
# Tool: ashby_pareto_front
# ---------------------------------------------------------------------------

_pareto_spec = ToolSpec(
    name="ashby_pareto_front",
    description=(
        "Return the Pareto-optimal (non-dominated) materials for two conflicting "
        "properties.\n"
        "\n"
        "A material is non-dominated if no other material in the catalog is "
        "simultaneously at least as good on both properties and strictly better "
        "on at least one. This is the 'Pareto line' display in Granta MI / "
        "CES EduPack.\n"
        "\n"
        "Example: find materials that are simultaneously lightweight AND stiff:\n"
        "  x='density_kg_m3' direction_x='minimize',\n"
        "  y='youngs_modulus_gpa' direction_y='maximize'\n"
        "→ typically returns CFRP, ceramics, and some metals.\n"
        "\n"
        "References: Ashby (2017) §9.3; Deb (2001) multi-objective opt. §2.\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "x_property": {
                "type": "string",
                "description": "Material attribute for the first objective axis.",
            },
            "y_property": {
                "type": "string",
                "description": "Material attribute for the second objective axis.",
            },
            "direction_x": {
                "type": "string",
                "enum": ["maximize", "minimize"],
                "description": "Direction for x-axis objective (default 'maximize').",
            },
            "direction_y": {
                "type": "string",
                "enum": ["maximize", "minimize"],
                "description": "Direction for y-axis objective (default 'maximize').",
            },
        },
        "required": ["x_property", "y_property"],
    },
)


@register(_pareto_spec, write=False)
async def run_ashby_pareto_front(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    x_prop = a.get("x_property")
    y_prop = a.get("y_property")
    dir_x = a.get("direction_x", "maximize")
    dir_y = a.get("direction_y", "maximize")

    if not x_prop or not y_prop:
        return err_payload("'x_property' and 'y_property' are required", "BAD_ARGS")

    db = _db()
    try:
        front = pareto_front(db, x_prop, y_prop, dir_x, dir_y)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"Pareto computation failed: {exc}", "INTERNAL")

    items = [
        {
            "name": m.name,
            "category": m.category,
            x_prop: getattr(m, x_prop, None),
            y_prop: getattr(m, y_prop, None),
        }
        for m in front
    ]

    return ok_payload({
        "ok": True,
        "x_property": x_prop,
        "y_property": y_prop,
        "direction_x": dir_x,
        "direction_y": dir_y,
        "count": len(items),
        "pareto_materials": items,
    })
