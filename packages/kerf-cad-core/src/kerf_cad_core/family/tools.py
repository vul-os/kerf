"""
kerf_cad_core.family.tools — LLM tool wrappers for the parametric family system.

Registers four tools with the Kerf tool registry:

  family_define       — Define a new parametric family and store it in the
                        in-memory family registry.
  family_add_type     — Add a named type (parameter-value set) to an existing
                        family (e.g. "Door 900x2100").
  family_instantiate  — Instantiate a family type; resolve formulas, merge
                        overrides, return a concrete recipe dict.
  family_validate     — Validate a set of param values against a family's
                        constraints (range, formula); does not instantiate.

All tools are pure-Python; no OCC dependency.
Returns {ok: false, errors: [...]} on bad input; never raises.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.family.model import (
    family_define as _family_define,
    family_add_type as _family_add_type,
    family_instantiate as _family_instantiate,
    family_validate as _family_validate,
)

# ---------------------------------------------------------------------------
# Shared sub-schema: a single param definition
# ---------------------------------------------------------------------------

_PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Unique parameter name within the family.",
        },
        "param_type": {
            "type": "string",
            "enum": ["number", "string", "bool"],
            "description": "Parameter data type. Default 'number'.",
        },
        "default": {
            "description": "Default value.  Must match param_type.",
        },
        "min_value": {
            "type": "number",
            "description": "Minimum allowed value (number params only).",
        },
        "max_value": {
            "type": "number",
            "description": "Maximum allowed value (number params only).",
        },
        "formula": {
            "type": "string",
            "description": (
                "Safe arithmetic expression over other param names. "
                "Example: 'width * 2 + 50'. "
                "When set, any explicitly supplied value is ignored; "
                "the formula result is used instead. "
                "Supports: +  -  *  /  **  ()  param names  numeric literals "
                "and math helpers: sqrt, abs, floor, ceil, round, sin, cos, tan, pi, e."
            ),
        },
        "description": {
            "type": "string",
            "description": "Human-readable description of the parameter.",
        },
    },
    "required": ["name"],
}

# ---------------------------------------------------------------------------
# Tool: family_define
# ---------------------------------------------------------------------------

_family_define_spec = ToolSpec(
    name="family_define",
    description=(
        "Define a new parametric family (analogous to a Revit family or FreeCAD "
        "parametric part). "
        "A family consists of named parameters (with type, default, optional range, "
        "and optional formula dependencies) and an optional build-recipe template. "
        "Formula parameters are computed from other params; cycles are rejected. "
        "The family is stored in the in-memory family registry and is available for "
        "family_add_type and family_instantiate calls. "
        "Returns {ok: true, family_name: str} on success. "
        "Returns {ok: false, errors: [...]} on validation failure — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique family name (e.g. 'Door', 'Column', 'Window').",
            },
            "params": {
                "type": "array",
                "description": "Ordered list of parameter definitions.",
                "items": _PARAM_SCHEMA,
            },
            "recipe_template": {
                "type": "object",
                "description": (
                    "Build-recipe template dict. String values may contain "
                    "{param_name} placeholders that are substituted when a "
                    "type is instantiated. "
                    "Example: {\"type\": \"door\", \"width_mm\": \"{width}\", "
                    "\"height_mm\": \"{height}\"}."
                ),
            },
            "description": {
                "type": "string",
                "description": "Human-readable family description.",
            },
        },
        "required": ["name", "params"],
    },
)


@register(_family_define_spec, write=False)
async def run_family_define(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = _family_define(
        name=a.get("name", ""),
        params=a.get("params", []),
        recipe_template=a.get("recipe_template"),
        description=a.get("description", ""),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: family_add_type
# ---------------------------------------------------------------------------

_family_add_type_spec = ToolSpec(
    name="family_add_type",
    description=(
        "Add a named type (parameter-value set) to an existing family. "
        "A 'type' is a pre-defined configuration — for example a 'Door' family "
        "might have types 'Door 900x2100' and 'Door 800x2100'. "
        "Only params defined on the family are accepted; unknown keys are rejected. "
        "Values are validated against each param's min/max range. "
        "Returns {ok: true, family_name: str, type_name: str} on success. "
        "Returns {ok: false, errors: [...]} on failure — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "family_name": {
                "type": "string",
                "description": "Name of the target family (must have been created with family_define).",
            },
            "type_name": {
                "type": "string",
                "description": "Unique name for this type (e.g. 'Door 900x2100').",
            },
            "values": {
                "type": "object",
                "description": (
                    "Param overrides for this type. "
                    "Example: {\"width\": 900, \"height\": 2100}. "
                    "Params not listed here fall back to their family defaults."
                ),
            },
            "description": {
                "type": "string",
                "description": "Human-readable type description.",
            },
        },
        "required": ["family_name", "type_name", "values"],
    },
)


@register(_family_add_type_spec, write=False)
async def run_family_add_type(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = _family_add_type(
        family_name=a.get("family_name", ""),
        type_name=a.get("type_name", ""),
        values=a.get("values", {}),
        description=a.get("description", ""),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: family_instantiate
# ---------------------------------------------------------------------------

_family_instantiate_spec = ToolSpec(
    name="family_instantiate",
    description=(
        "Instantiate a family type: resolve formula parameters, merge instance "
        "overrides on top of the type's values, validate ranges, and substitute "
        "the build-recipe template with resolved values. "
        "Workflow: "
        "1. family_define → create a family with parameters + recipe template. "
        "2. family_add_type → add named types (e.g. 'Door 900x2100'). "
        "3. family_instantiate → get a concrete recipe for a specific placement "
        "   (e.g. 'Entry Door' based on 'Door 900x2100' with custom finish). "
        "Returns {ok: true, instance: {...}, resolved_params: {...}, recipe: {...}}. "
        "Returns {ok: false, errors: [...]} on failure — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "family_name": {
                "type": "string",
                "description": "Name of the target family.",
            },
            "type_name": {
                "type": "string",
                "description": "Name of the type to instantiate.",
            },
            "instance_name": {
                "type": "string",
                "description": "Optional human-readable identifier for this instance (e.g. 'Entry Door').",
            },
            "overrides": {
                "type": "object",
                "description": (
                    "Per-instance param overrides applied on top of the type's values. "
                    "Formula params may NOT be overridden. "
                    "Example: {\"finish\": \"oak\"}."
                ),
            },
        },
        "required": ["family_name", "type_name"],
    },
)


@register(_family_instantiate_spec, write=False)
async def run_family_instantiate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = _family_instantiate(
        family_name=a.get("family_name", ""),
        type_name=a.get("type_name", ""),
        instance_name=a.get("instance_name", ""),
        overrides=a.get("overrides"),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: family_validate
# ---------------------------------------------------------------------------

_family_validate_spec = ToolSpec(
    name="family_validate",
    description=(
        "Validate a set of param values against a family's constraints without "
        "instantiating or modifying state. "
        "Evaluates formula params from the supplied values, checks all min/max "
        "ranges, and returns detailed error messages for any violations. "
        "Useful for live validation in a UI before committing an instance. "
        "Returns {ok: true, resolved_params: {...}} when all values are valid. "
        "Returns {ok: false, errors: [...]} otherwise — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "family_name": {
                "type": "string",
                "description": "Name of the target family.",
            },
            "values": {
                "type": "object",
                "description": (
                    "Param values to validate. "
                    "Non-formula params: provide the intended value. "
                    "Formula params: will be computed automatically. "
                    "Example: {\"width\": 950, \"height\": 2100}."
                ),
            },
        },
        "required": ["family_name", "values"],
    },
)


@register(_family_validate_spec, write=False)
async def run_family_validate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = _family_validate(
        family_name=a.get("family_name", ""),
        values=a.get("values", {}),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)
