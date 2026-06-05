"""
gdl_library.py — LLM tools for the GDL Parametric Object Library (ArchiCAD parity).

Registered tools
----------------
bim_gdl_list_objects      — list objects in a GDL library (with optional subtype filter)
bim_gdl_evaluate_object   — evaluate a GDL object with parameter overrides
bim_gdl_validate_object   — validate a GDL object definition
bim_gdl_instantiate       — place a library object (lookup by id) with overrides

References
----------
GRAPHISOFT GDL Reference Manual (ArchiCAD 27).
IFC4 ADD2 TC1 — IfcTypeProduct.
"""

from __future__ import annotations

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


def _parse_gdl_param(raw: dict):
    from kerf_bim.gdl_library import GDLParam
    return GDLParam(
        name=str(raw["name"]),
        type=str(raw.get("type", "length")),
        default=raw.get("default", 0.0),
        min=raw.get("min"),
        max=raw.get("max"),
        values=raw.get("values"),
        description=str(raw.get("description", "")),
    )


def _parse_gdl_object(raw: dict):
    from kerf_bim.gdl_library import GDLObject
    params = [_parse_gdl_param(p) for p in raw.get("params", [])]
    return GDLObject(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        subtype=str(raw.get("subtype", "Object")),
        params=params,
        script=str(raw.get("script", "")),
        description=str(raw.get("description", "")),
        author=str(raw.get("author", "")),
    )


# ---------------------------------------------------------------------------
# bim_gdl_list_objects
# ---------------------------------------------------------------------------

_list_objects_spec = ToolSpec(
    name="bim_gdl_list_objects",
    description=(
        "GDL Parametric Object Library — List objects.\n"
        "\n"
        "Returns metadata for all objects in the built-in kerf GDL starter "
        "library, optionally filtered by ArchiCAD GDL subtype "
        "(Door|Window|Column|Beam|Furniture|Lamp|Object|…).\n"
        "\n"
        "ArchiCAD parity: objects ≈ GDL parametric objects in the ArchiCAD "
        "Object Library."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "subtype": {
                "type": "string",
                "description": (
                    "Filter by GDL subtype (e.g. 'Door', 'Window', 'Column', "
                    "'Beam', 'Furniture', 'Lamp'). Omit to list all."
                ),
            },
        },
    },
)


async def run_bim_gdl_list_objects(params: dict, ctx) -> str:
    try:
        from kerf_bim.gdl_library import DEFAULT_LIBRARY

        subtype = params.get("subtype")
        objects = DEFAULT_LIBRARY.list_objects(subtype=subtype)
        return ok_payload({
            "ok": True,
            "count":   len(objects),
            "objects": objects,
        })
    except Exception as exc:
        return err_payload(str(exc), "GDL_LIST_ERROR")


# ---------------------------------------------------------------------------
# bim_gdl_evaluate_object
# ---------------------------------------------------------------------------

_evaluate_object_spec = ToolSpec(
    name="bim_gdl_evaluate_object",
    description=(
        "GDL Parametric Object Library — Evaluate object.\n"
        "\n"
        "Resolve parameter values for a GDL object (from the built-in library "
        "or a custom definition) and execute the geometry script. Returns "
        "resolved parameters and geometry summary.\n"
        "\n"
        "Provide either object_id (built-in library lookup) or object_def "
        "(full GDL object dict)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "object_id": {
                "type": "string",
                "description": "ID of a built-in library object.",
            },
            "object_def": {
                "type": "object",
                "description": (
                    "Custom GDL object definition: "
                    "{id, name, subtype, params: [{name, type, default, min?, max?}], script?}"
                ),
            },
            "param_overrides": {
                "type": "object",
                "description": "Parameter values to override (upper-case GDL names).",
                "default": {},
            },
        },
    },
)


async def run_bim_gdl_evaluate_object(params: dict, ctx) -> str:
    try:
        from kerf_bim.gdl_library import DEFAULT_LIBRARY, evaluate_gdl_object

        object_id = params.get("object_id")
        raw_def = params.get("object_def")
        overrides = dict(params.get("param_overrides") or {})

        if object_id:
            obj = DEFAULT_LIBRARY.get(object_id)
            if obj is None:
                return err_payload(f"object '{object_id}' not found in built-in library", "NOT_FOUND")
        elif raw_def:
            try:
                obj = _parse_gdl_object(raw_def)
            except (ValueError, TypeError) as exc:
                return err_payload(str(exc), "BAD_ARGS")
        else:
            return err_payload("provide either object_id or object_def", "BAD_ARGS")

        result = evaluate_gdl_object(obj, overrides)
        return ok_payload({"ok": True, **result})
    except Exception as exc:
        return err_payload(str(exc), "GDL_EVALUATE_ERROR")


# ---------------------------------------------------------------------------
# bim_gdl_validate_object
# ---------------------------------------------------------------------------

_validate_object_spec = ToolSpec(
    name="bim_gdl_validate_object",
    description=(
        "GDL Parametric Object Library — Validate object definition. "
        "Returns errors list (empty = valid). Checks subtype, param types, "
        "and script safety (no imports, no exec/eval)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "object_def": {
                "type": "object",
                "description": "GDL object definition dict.",
            },
        },
        "required": ["object_def"],
    },
)


async def run_bim_gdl_validate_object(params: dict, ctx) -> str:
    try:
        from kerf_bim.gdl_library import validate_gdl_object

        raw_def = params.get("object_def", {})
        try:
            obj = _parse_gdl_object(raw_def)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        errors = validate_gdl_object(obj)
        return ok_payload({
            "ok":    True,
            "valid": len(errors) == 0,
            "errors": errors,
        })
    except Exception as exc:
        return err_payload(str(exc), "GDL_VALIDATE_ERROR")


# ---------------------------------------------------------------------------
# bim_gdl_instantiate
# ---------------------------------------------------------------------------

_instantiate_spec = ToolSpec(
    name="bim_gdl_instantiate",
    description=(
        "GDL Parametric Object Library — Place a library object.\n"
        "\n"
        "Looks up object_id in the built-in library, applies param_overrides, "
        "and returns the resolved instance. Use bim_gdl_list_objects to discover "
        "available object IDs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "object_id": {
                "type": "string",
                "description": "ID of the GDL object to place.",
            },
            "param_overrides": {
                "type": "object",
                "description": "Instance-level parameter values (upper-case names).",
                "default": {},
            },
        },
        "required": ["object_id"],
    },
)


async def run_bim_gdl_instantiate(params: dict, ctx) -> str:
    try:
        from kerf_bim.gdl_library import instantiate_gdl, DEFAULT_LIBRARY

        object_id = str(params.get("object_id", ""))
        if not object_id:
            return err_payload("object_id is required", "BAD_ARGS")

        overrides = dict(params.get("param_overrides") or {})
        try:
            result = instantiate_gdl(DEFAULT_LIBRARY, object_id, overrides)
        except KeyError as exc:
            return err_payload(str(exc), "NOT_FOUND")

        return ok_payload({"ok": True, **result})
    except Exception as exc:
        return err_payload(str(exc), "GDL_INSTANTIATE_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_gdl_list_objects",    _list_objects_spec,    run_bim_gdl_list_objects),
    ("bim_gdl_evaluate_object", _evaluate_object_spec, run_bim_gdl_evaluate_object),
    ("bim_gdl_validate_object", _validate_object_spec, run_bim_gdl_validate_object),
    ("bim_gdl_instantiate",     _instantiate_spec,     run_bim_gdl_instantiate),
]
