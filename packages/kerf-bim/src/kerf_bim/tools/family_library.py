"""
family_library.py — LLM tools exposing the cold-start BIM family catalog.

Read-only catalog access (T-110).  These tools let the assistant browse
the pre-populated :data:`kerf_bim.family.library.DEFAULT_LIBRARY` so it
can suggest / clone catalog families without the project having to author
them first.

list_family_library          — list catalog families (optionally by category)
get_family_from_library      — full schema + type presets for one family
list_family_library_categories — distinct catalog categories
"""

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_bim.family.library import DEFAULT_LIBRARY


def _param_to_dict(p) -> dict:
    return {
        "name": getattr(p, "name", ""),
        "kind": getattr(p, "kind", ""),
        "default": getattr(p, "default", None),
        "description": getattr(p, "description", ""),
    }


def _family_summary(fam) -> dict:
    return {
        "name": fam.name,
        "category": fam.category,
        "description": fam.description,
        "type_count": len(getattr(fam, "_library_types", [])),
    }


list_family_library_spec = ToolSpec(
    name="list_family_library",
    description=(
        "List pre-populated catalog families available cold-start (doors, "
        "windows, furniture, plumbing, lighting, structural). Optionally "
        "filter by exact category string."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Optional exact category filter (e.g. 'Door').",
            },
        },
        "required": [],
    },
)


@register(list_family_library_spec)
async def run_list_family_library(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    category = a.get("category")
    if category:
        fams = DEFAULT_LIBRARY.families_in_category(category)
    else:
        fams = DEFAULT_LIBRARY.all_families()

    return ok_payload({
        "families": [_family_summary(f) for f in fams],
        "count": len(fams),
    })


get_family_from_library_spec = ToolSpec(
    name="get_family_from_library",
    description=(
        "Return the full parameter schema and built-in type presets for one "
        "catalog family, looked up by its exact family name."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact family name, e.g. 'Single Swing Door'.",
            },
        },
        "required": ["name"],
    },
)


@register(get_family_from_library_spec)
async def run_get_family_from_library(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    name = a.get("name", "")
    if not name:
        return err_payload("name is required", "BAD_ARGS")

    try:
        fam = DEFAULT_LIBRARY.get_family(name)
    except KeyError:
        return err_payload(f"no catalog family named {name!r}", "NOT_FOUND")

    types = [
        {"name": t.name, "values": dict(t.type_param_values), "description": t.description}
        for t in getattr(fam, "_library_types", [])
    ]
    return ok_payload({
        "name": fam.name,
        "category": fam.category,
        "description": fam.description,
        "type_parameters": [_param_to_dict(p) for p in fam.type_parameters.values()],
        "instance_parameters": [_param_to_dict(p) for p in fam.instance_parameters.values()],
        "types": types,
    })


list_family_library_categories_spec = ToolSpec(
    name="list_family_library_categories",
    description="List the distinct categories present in the cold-start family catalog.",
    input_schema={"type": "object", "properties": {}, "required": []},
)


@register(list_family_library_categories_spec)
async def run_list_family_library_categories(ctx: ProjectCtx, args: bytes) -> str:
    return ok_payload({"categories": DEFAULT_LIBRARY.categories()})
