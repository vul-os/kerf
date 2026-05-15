"""
kerf_cad_core.matsel.tools — LLM tool wrappers for material selection.

Registers four tools with the Kerf tool registry:

  matsel_get          — look up a single material by name
  matsel_list         — list all materials (optionally filtered by family)
  matsel_filter       — filter materials by property constraints
  matsel_select       — Ashby-style material selection: filter + rank

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Ashby, M.F. "Materials Selection in Mechanical Design", 4th ed. (Butterworth-Heinemann)
Callister, W.D. "Materials Science and Engineering: An Introduction"
Shigley's Mechanical Engineering Design, 10th ed.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.matsel.db import (
    get_material,
    list_materials,
    filter_materials,
    ashby_rank,
    select_material,
)


# ---------------------------------------------------------------------------
# Tool: matsel_get
# ---------------------------------------------------------------------------

_matsel_get_spec = ToolSpec(
    name="matsel_get",
    description=(
        "Look up a single engineering material by name from the Kerf material database.\n"
        "\n"
        "Returns all properties: density (kg/m³), E (GPa), sigma_y / sigma_uts / sigma_e "
        "(MPa), thermal conductivity k (W/m·K), CTE (µm/m·K), max service temperature T_max "
        "(°C), relative cost index, and computed Ashby merit indices "
        "(specific_stiffness, specific_strength, light_stiff_beam, light_strong_plate, "
        "cost_per_stiffness).\n"
        "\n"
        "Use matsel_list first to discover available names.\n"
        "\n"
        "Errors: {ok:false, reason} if material not found.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Canonical material name, e.g. 'AISI_4140_QT', 'Al_7075_T6', "
                    "'CFRP_UD_0deg', 'Ti_6Al4V'.  Case-sensitive."
                ),
            },
        },
        "required": ["name"],
    },
)


@register(_matsel_get_spec, write=False)
async def run_matsel_get(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    name = a.get("name")
    if not name:
        return json.dumps({"ok": False, "reason": "name is required"})

    mat = get_material(name)
    if mat is None:
        all_names = list_materials()
        return json.dumps({
            "ok": False,
            "reason": f"Material {name!r} not found. Available: {all_names}",
        })

    return ok_payload({"ok": True, **mat})


# ---------------------------------------------------------------------------
# Tool: matsel_list
# ---------------------------------------------------------------------------

_matsel_list_spec = ToolSpec(
    name="matsel_list",
    description=(
        "List all engineering materials in the Kerf material database.\n"
        "\n"
        "Optionally filter by material family.  Available families:\n"
        "  steel, stainless_steel, aluminium, titanium, magnesium, polymer,\n"
        "  composite, wood, ceramic, cast_iron, copper\n"
        "\n"
        "Returns a list of canonical material names that can be passed to "
        "matsel_get, matsel_filter, or matsel_select.\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "family": {
                "type": "string",
                "description": (
                    "Optional family filter, e.g. 'aluminium', 'composite'. "
                    "If omitted all materials are listed."
                ),
            },
        },
        "required": [],
    },
)


@register(_matsel_list_spec, write=False)
async def run_matsel_list(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    family_filter = a.get("family")
    all_names = list_materials()

    if family_filter:
        from kerf_cad_core.matsel.db import _DB
        filtered = [
            n for n in all_names
            if _DB[n].get("family", "").lower() == family_filter.lower()
        ]
        return ok_payload({"ok": True, "materials": filtered, "count": len(filtered)})

    return ok_payload({"ok": True, "materials": all_names, "count": len(all_names)})


# ---------------------------------------------------------------------------
# Tool: matsel_filter
# ---------------------------------------------------------------------------

_matsel_filter_spec = ToolSpec(
    name="matsel_filter",
    description=(
        "Filter the material database by min/max property constraints.\n"
        "\n"
        "Returns the names of materials satisfying ALL constraints.\n"
        "Warns (but does not fail) when the result set is empty or a constraint "
        "key is unrecognised.\n"
        "\n"
        "Filterable properties (base):\n"
        "  density (kg/m³), E (GPa), sigma_y (MPa), sigma_uts (MPa), sigma_e (MPa),\n"
        "  k (W/m·K), CTE (µm/m·K), T_max (°C), cost_rel\n"
        "\n"
        "Filterable properties (derived Ashby indices):\n"
        "  specific_stiffness (E/ρ), specific_strength (σy/ρ),\n"
        "  light_stiff_beam (E^0.5/ρ), light_strong_plate (σy^(2/3)/ρ),\n"
        "  cost_per_stiffness (cost·ρ/E)\n"
        "\n"
        "Errors: {ok:false, reason} for malformed input.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "constraints": {
                "type": "object",
                "description": (
                    "Object mapping property_name to {\"min\": ..., \"max\": ...}. "
                    "Example: {\"density\": {\"max\": 3000}, \"E\": {\"min\": 50}}. "
                    "Both min and max are optional."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "min": {"type": "number"},
                        "max": {"type": "number"},
                    },
                },
            },
        },
        "required": ["constraints"],
    },
)


@register(_matsel_filter_spec, write=False)
async def run_matsel_filter(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    constraints = a.get("constraints")
    if constraints is None:
        return json.dumps({"ok": False, "reason": "constraints is required"})
    if not isinstance(constraints, dict):
        return json.dumps({"ok": False, "reason": "constraints must be an object"})

    result = filter_materials(constraints)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: matsel_select
# ---------------------------------------------------------------------------

_matsel_select_spec = ToolSpec(
    name="matsel_select",
    description=(
        "Ashby-style material selection: filter by constraints, then rank by a "
        "merit index or objective.\n"
        "\n"
        "Workflow:\n"
        "  1. Apply all constraints (same syntax as matsel_filter).\n"
        "  2. Rank surviving materials by the chosen objective (best first).\n"
        "  3. Return the top_n candidates with index values and ranks.\n"
        "\n"
        "Available objectives / indices:\n"
        "  'specific_stiffness'  — E/ρ              minimise mass, stiffness-limited rod\n"
        "  'specific_strength'   — σy/ρ             minimise mass, strength-limited tie\n"
        "  'light_stiff_beam'    — E^(1/2)/ρ        minimise mass, stiffness-limited beam\n"
        "  'light_strong_plate'  — σy^(2/3)/ρ       minimise mass, yield-limited plate\n"
        "  'cost_per_stiffness'  — cost·ρ/E         minimise cost per unit stiffness\n"
        "  'density'             — minimise weight\n"
        "  'cost_rel'            — minimise relative cost\n"
        "  'CTE'                 — minimise thermal expansion\n"
        "  ...any base property may also be used as an objective.\n"
        "\n"
        "Result warnings flag empty candidate sets or contradictory constraints.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid objective.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "constraints": {
                "type": "object",
                "description": (
                    "Property constraints (same format as matsel_filter). "
                    "May be empty ({}) to rank all materials."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "min": {"type": "number"},
                        "max": {"type": "number"},
                    },
                },
            },
            "objective": {
                "type": "string",
                "description": (
                    "Merit index to maximise (or minimise for density/cost_rel/CTE/"
                    "cost_per_stiffness).  Default: 'specific_stiffness'."
                ),
            },
            "top_n": {
                "type": "integer",
                "description": "Maximum number of results to return (default 10).",
            },
        },
        "required": ["constraints"],
    },
)


@register(_matsel_select_spec, write=False)
async def run_matsel_select(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    constraints = a.get("constraints")
    if constraints is None:
        return json.dumps({"ok": False, "reason": "constraints is required"})
    if not isinstance(constraints, dict):
        return json.dumps({"ok": False, "reason": "constraints must be an object"})

    objective = a.get("objective", "specific_stiffness")
    top_n = a.get("top_n", 10)

    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "reason": f"top_n must be an integer, got {top_n!r}"})

    result = select_material(constraints, objective=objective, top_n=top_n)
    if not result["ok"]:
        return json.dumps(result)
    return ok_payload(result)
