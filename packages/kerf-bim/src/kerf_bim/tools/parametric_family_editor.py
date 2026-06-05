"""
parametric_family_editor.py — LLM tools for the Parametric Family Editor
with nested families and type catalogue (Revit parity).

Registered tools
----------------
bim_family_nested_instantiate — instantiate a NestedFamilyDef with optional type catalogue lookup
bim_family_nested_validate    — validate a NestedFamilyDef + nested structure
bim_family_catalogue_build    — build a validated type catalogue from raw rows
bim_family_catalogue_table    — render type catalogue as a JSON table

References
----------
Revit Family Guide (2024) — Nested and Shared Families, Type Catalogues.
IFC4 ADD2 TC1 — IfcTypeProduct for family type objects.
"""

from __future__ import annotations

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


def _parse_param(raw: dict):
    from kerf_bim.family_editor import FamilyParameter
    return FamilyParameter(
        name=raw["name"],
        type=raw.get("type", "number"),
        default=raw.get("default", 0.0),
        min=raw.get("min"),
        max=raw.get("max"),
        choices=raw.get("choices"),
        units=raw.get("units", ""),
        description=raw.get("description", ""),
    )


def _parse_formula(raw: dict):
    from kerf_bim.family_editor import FamilyFormula
    return FamilyFormula(name=raw["name"], expression=raw["expression"])


def _parse_family_def(raw: dict):
    from kerf_bim.family_editor import FamilyDef
    params = [_parse_param(p) for p in raw.get("parameters", [])]
    formulas = [_parse_formula(f) for f in raw.get("formulas", [])]
    return FamilyDef(
        name=raw.get("name", "Unnamed"),
        category=raw.get("category", "generic"),
        parameters=params,
        formulas=formulas,
        geometry_script=raw.get("geometry_script", ""),
        description=raw.get("description", ""),
    )


def _parse_nested_family(raw: dict):
    from kerf_bim.nested_family import NestedFamily
    return NestedFamily(
        sub_family_id=str(raw.get("sub_family_id", "")),
        placement_params=dict(raw.get("placement_params", {})),
        count=raw.get("count", 1),
        label=str(raw.get("label", "")),
        ifc_type=str(raw.get("ifc_type", "")),
    )


def _parse_nested_def(raw: dict):
    from kerf_bim.nested_family import NestedFamilyDef
    parent = _parse_family_def(raw.get("parent", raw))
    nested = [_parse_nested_family(n) for n in raw.get("nested_families", [])]
    return NestedFamilyDef(parent=parent, nested_families=nested)


# ---------------------------------------------------------------------------
# bim_family_nested_instantiate
# ---------------------------------------------------------------------------

_nested_instantiate_spec = ToolSpec(
    name="bim_family_nested_instantiate",
    description=(
        "Instantiate a Parametric Family with nested sub-families and an "
        "optional type catalogue.\n"
        "\n"
        "family_def: {parent: {name, category, parameters, formulas, geometry_script?}, "
        "nested_families: [{sub_family_id, placement_params, count?, label?, ifc_type?}]}\n"
        "\n"
        "parameter_values: override dict for parent parameters.\n"
        "type_id: if given, looks up type_catalogue entries for override values.\n"
        "type_catalogue: {family_name, entries: [{type_id, name, ...param_overrides}]}\n"
        "\n"
        "Returns resolved parent params + nested sub-family placements.\n"
        "\n"
        "Revit parity: NestedFamilyDef ≈ Revit nested family; "
        "TypeCatalogue ≈ Revit type catalogue .txt."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "family_def": {
                "type": "object",
                "description": "NestedFamilyDef dict.",
                "properties": {
                    "parent":          {"type": "object"},
                    "nested_families": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["parent"],
            },
            "parameter_values": {
                "type": "object",
                "description": "Parameter override values.",
                "default": {},
            },
            "type_id": {
                "type": "string",
                "description": "Type catalogue entry to apply before user overrides.",
            },
            "type_catalogue": {
                "type": "object",
                "description": "TypeCatalogue dict: {family_name, entries: [{type_id, name, ...}]}",
            },
        },
        "required": ["family_def"],
    },
)


async def run_bim_family_nested_instantiate(params: dict, ctx) -> str:
    try:
        from kerf_bim.nested_family import (
            TypeCatalogue, TypeCatalogueEntry, instantiate_nested,
        )
        from kerf_bim.family_editor import FamilyEditorError

        raw_def = params.get("family_def", {})
        try:
            nfdef = _parse_nested_def(raw_def)
        except (ValueError, TypeError, FamilyEditorError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        pv = dict(params.get("parameter_values") or {})
        type_id = params.get("type_id")

        catalogue = None
        raw_cat = params.get("type_catalogue")
        if raw_cat:
            entries = [
                TypeCatalogueEntry(
                    type_id=str(e["type_id"]),
                    name=str(e["name"]),
                    param_overrides={
                        k: v for k, v in e.items()
                        if k not in ("type_id", "name", "description")
                    },
                    description=str(e.get("description", "")),
                )
                for e in raw_cat.get("entries", [])
            ]
            catalogue = TypeCatalogue(
                family_name=str(raw_cat.get("family_name", "")),
                entries=entries,
            )

        result = instantiate_nested(nfdef, pv, type_id=type_id, catalogue=catalogue)
        return ok_payload({"ok": True, **result})
    except Exception as exc:
        return err_payload(str(exc), "NESTED_INSTANTIATE_ERROR")


# ---------------------------------------------------------------------------
# bim_family_nested_validate
# ---------------------------------------------------------------------------

_nested_validate_spec = ToolSpec(
    name="bim_family_nested_validate",
    description=(
        "Validate a NestedFamilyDef: checks parent family errors plus "
        "nested sub-family structure (missing sub_family_ids, unknown "
        "placement_param references). Empty errors list = valid."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "family_def": {
                "type": "object",
                "description": "NestedFamilyDef dict.",
            },
        },
        "required": ["family_def"],
    },
)


async def run_bim_family_nested_validate(params: dict, ctx) -> str:
    try:
        from kerf_bim.nested_family import validate_nested
        from kerf_bim.family_editor import FamilyEditorError

        raw_def = params.get("family_def", {})
        try:
            nfdef = _parse_nested_def(raw_def)
        except (ValueError, TypeError, FamilyEditorError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        errors = validate_nested(nfdef)
        return ok_payload({
            "ok": True,
            "valid": len(errors) == 0,
            "errors": errors,
        })
    except Exception as exc:
        return err_payload(str(exc), "NESTED_VALIDATE_ERROR")


# ---------------------------------------------------------------------------
# bim_family_catalogue_build
# ---------------------------------------------------------------------------

_catalogue_build_spec = ToolSpec(
    name="bim_family_catalogue_build",
    description=(
        "Build and validate a type catalogue for a parametric family. "
        "Each row must have type_id and name; other keys are parameter overrides. "
        "Returns the validated catalogue or a list of errors.\n"
        "\n"
        "Revit parity: type catalogue ≈ Revit type catalogue .txt file, "
        "one type per row with parameter value columns."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "family_def": {
                "type": "object",
                "description": "Parent FamilyDef (or NestedFamilyDef with parent key).",
            },
            "rows": {
                "type": "array",
                "description": "Catalogue rows: [{type_id, name, ...param_overrides}]",
                "items": {
                    "type": "object",
                    "properties": {
                        "type_id":     {"type": "string"},
                        "name":        {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["type_id", "name"],
                },
            },
        },
        "required": ["family_def", "rows"],
    },
)


async def run_bim_family_catalogue_build(params: dict, ctx) -> str:
    try:
        from kerf_bim.nested_family import build_type_catalogue
        from kerf_bim.family_editor import FamilyEditorError

        raw_def = params.get("family_def", {})
        # Accept either FamilyDef or NestedFamilyDef format
        if "parent" in raw_def:
            raw_def = raw_def["parent"]
        try:
            fdef = _parse_family_def(raw_def)
        except (ValueError, TypeError, FamilyEditorError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        rows = params.get("rows", [])
        if not isinstance(rows, list):
            return err_payload("rows must be an array", "BAD_ARGS")

        try:
            catalogue = build_type_catalogue(fdef, rows)
        except FamilyEditorError as exc:
            return err_payload(str(exc), "CATALOGUE_BUILD_ERROR")

        return ok_payload({
            "ok": True,
            "family_name":  catalogue.family_name,
            "entry_count":  len(catalogue.entries),
            "type_ids":     [e.type_id for e in catalogue.entries],
            "entries": [
                {
                    "type_id":      e.type_id,
                    "name":         e.name,
                    "description":  e.description,
                    "param_overrides": e.param_overrides,
                }
                for e in catalogue.entries
            ],
        })
    except Exception as exc:
        return err_payload(str(exc), "CATALOGUE_BUILD_ERROR")


# ---------------------------------------------------------------------------
# bim_family_catalogue_table
# ---------------------------------------------------------------------------

_catalogue_table_spec = ToolSpec(
    name="bim_family_catalogue_table",
    description=(
        "Render a validated TypeCatalogue as a flat list-of-dicts table "
        "suitable for display in a React data grid. Each row: "
        "{type_id, name, description, ...param_overrides}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "catalogue": {
                "type": "object",
                "description": "TypeCatalogue dict: {family_name, entries: [...]}",
                "properties": {
                    "family_name": {"type": "string"},
                    "entries":     {"type": "array", "items": {"type": "object"}},
                },
                "required": ["entries"],
            },
        },
        "required": ["catalogue"],
    },
)


async def run_bim_family_catalogue_table(params: dict, ctx) -> str:
    try:
        from kerf_bim.nested_family import TypeCatalogue, TypeCatalogueEntry, render_catalogue_table
        from kerf_bim.family_editor import FamilyEditorError

        raw = params.get("catalogue", {})
        entries = [
            TypeCatalogueEntry(
                type_id=str(e["type_id"]),
                name=str(e["name"]),
                param_overrides={
                    k: v for k, v in e.items()
                    if k not in ("type_id", "name", "description")
                },
                description=str(e.get("description", "")),
            )
            for e in raw.get("entries", [])
        ]
        cat = TypeCatalogue(
            family_name=str(raw.get("family_name", "")),
            entries=entries,
        )
        table = render_catalogue_table(cat)
        return ok_payload({
            "ok": True,
            "family_name": cat.family_name,
            "row_count":   len(table),
            "table":       table,
        })
    except Exception as exc:
        return err_payload(str(exc), "CATALOGUE_TABLE_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_family_nested_instantiate", _nested_instantiate_spec, run_bim_family_nested_instantiate),
    ("bim_family_nested_validate",    _nested_validate_spec,    run_bim_family_nested_validate),
    ("bim_family_catalogue_build",    _catalogue_build_spec,    run_bim_family_catalogue_build),
    ("bim_family_catalogue_table",    _catalogue_table_spec,    run_bim_family_catalogue_table),
]
