"""
cobie.py — LLM tools for COBie FM-handoff deliverable generation.

Tools
-----
bim_apply_property_mapping  — map IFC property sets to COBie Excel/XML
bim_export_cobie_excel      — export a COBie deliverable as .xlsx
bim_validate_cobie          — validate a COBie deliverable for compliance
bim_get_standard_template   — retrieve a named built-in COBie template
bim_compute_cobie_completeness — compute % of required columns populated
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# bim_get_standard_template
# ---------------------------------------------------------------------------

_get_template_spec = ToolSpec(
    name="bim_get_standard_template",
    description=(
        "Retrieve a built-in COBie property-mapping template by name.\n"
        "\n"
        "COBie (Construction Operations Building information exchange) maps IFC "
        "property sets to the FM-handoff spreadsheet demanded by facility managers.\n"
        "\n"
        "Available templates:\n"
        "  • standard          — COBie 2.4 generic (IFC pset→COBie column)\n"
        "  • federal_us        — US Federal (GSA/USACE) extended psets\n"
        "  • uk_ukgbc          — UK / UKGBC BS1192-4 lifecycle extension\n"
        "  • singapore_corenet — Singapore BCA CorNet e-Submission variant\n"
        "\n"
        "Returns the template as a JSON dict with 'template_name' and 'mappings'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Template name: 'standard' | 'federal_us' | 'uk_ukgbc' | 'singapore_corenet'."
                ),
            },
        },
        "required": ["name"],
    },
)


@register(_get_template_spec, write=False)
async def run_bim_get_standard_template(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    name = str(a.get("name", "")).strip()
    if not name:
        return err_payload("name is required", "BAD_ARGS")

    try:
        from kerf_bim.cobie import get_standard_template
        tmpl = get_standard_template(name)
    except ValueError as exc:
        return err_payload(str(exc), "NOT_FOUND")

    return ok_payload({
        "template_name": tmpl.template_name,
        "mapping_count": len(tmpl.mappings),
        "mappings": [
            {
                "ifc_pset_name":     m.ifc_pset_name,
                "ifc_property_name": m.ifc_property_name,
                "cobie_sheet":       m.cobie_sheet,
                "cobie_column":      m.cobie_column,
                "default_value":     m.default_value,
            }
            for m in tmpl.mappings
        ],
    })


# ---------------------------------------------------------------------------
# bim_apply_property_mapping
# ---------------------------------------------------------------------------

_apply_mapping_spec = ToolSpec(
    name="bim_apply_property_mapping",
    description=(
        "Map IFC property sets to a full COBie deliverable (all 18 sheets).\n"
        "\n"
        "Supply:\n"
        "  • ifc_data      — normalised IFC model dict (property_sets + elements)\n"
        "  • template_name — one of the 4 built-in templates, or omit for 'standard'\n"
        "\n"
        "ifc_data shape:\n"
        "  {\n"
        "    'created_by': 'user@example.com',\n"
        "    'property_sets': {'PsetName': {'PropName': 'value'}},\n"
        "    'elements': [\n"
        "      {'ifc_class': 'IfcSpace', 'name': 'Room 101',\n"
        "       'property_sets': {'Pset_SpaceCommon': {'GrossFloorArea': '42.0'}}}\n"
        "    ]\n"
        "  }\n"
        "\n"
        "Returns a summary: sheet names, row counts, completeness score."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ifc_data": {
                "type": "object",
                "description": "Normalised IFC model dict.",
            },
            "template_name": {
                "type": "string",
                "description": "Built-in template name (default: 'standard').",
                "default": "standard",
            },
        },
        "required": ["ifc_data"],
    },
)


@register(_apply_mapping_spec, write=False)
async def run_bim_apply_property_mapping(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    ifc_data = a.get("ifc_data")
    if not isinstance(ifc_data, dict):
        return err_payload("ifc_data must be a JSON object", "BAD_ARGS")

    template_name = str(a.get("template_name") or "standard").strip()

    try:
        from kerf_bim.cobie import (
            apply_mapping_template,
            compute_completeness_score,
            get_standard_template,
        )
        template = get_standard_template(template_name)
        deliverable = apply_mapping_template(ifc_data, template)
        score = compute_completeness_score(deliverable)
    except ValueError as exc:
        return err_payload(str(exc), "NOT_FOUND")
    except Exception as exc:
        return err_payload(str(exc), "COBIE_ERROR")

    sheet_summaries = [
        {"sheet": s.name, "rows": len(s.rows), "columns": len(s.columns)}
        for s in deliverable.sheets
    ]

    return ok_payload({
        "template_name": template_name,
        "sheet_count": len(deliverable.sheets),
        "sheets": sheet_summaries,
        "completeness": round(score, 4),
        "completeness_pct": f"{score * 100:.1f}%",
    })


# ---------------------------------------------------------------------------
# bim_validate_cobie
# ---------------------------------------------------------------------------

_validate_spec = ToolSpec(
    name="bim_validate_cobie",
    description=(
        "Validate a COBie deliverable for COBie 2.4 compliance.\n"
        "\n"
        "Checks:\n"
        "  • All 18 COBie sheets present\n"
        "  • Required columns present per sheet\n"
        "  • GUIDs / Emails unique within their sheet\n"
        "\n"
        "Returns {'valid': true} or {'valid': false, 'errors': [...]}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ifc_data": {
                "type": "object",
                "description": "Normalised IFC model dict (same shape as bim_apply_property_mapping).",
            },
            "template_name": {
                "type": "string",
                "description": "Template to apply before validating (default: 'standard').",
                "default": "standard",
            },
        },
        "required": ["ifc_data"],
    },
)


@register(_validate_spec, write=False)
async def run_bim_validate_cobie(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    ifc_data = a.get("ifc_data")
    if not isinstance(ifc_data, dict):
        return err_payload("ifc_data must be a JSON object", "BAD_ARGS")

    template_name = str(a.get("template_name") or "standard").strip()

    try:
        from kerf_bim.cobie import (
            apply_mapping_template,
            get_standard_template,
            validate_cobie_deliverable,
        )
        template = get_standard_template(template_name)
        deliverable = apply_mapping_template(ifc_data, template)
        errors = validate_cobie_deliverable(deliverable)
    except Exception as exc:
        return err_payload(str(exc), "COBIE_ERROR")

    return ok_payload({
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors,
    })


# ---------------------------------------------------------------------------
# bim_export_cobie_excel
# ---------------------------------------------------------------------------

_export_excel_spec = ToolSpec(
    name="bim_export_cobie_excel",
    description=(
        "Export a COBie deliverable to an .xlsx file.\n"
        "\n"
        "Applies the specified template to ifc_data, then writes an Excel "
        "workbook with one tab per COBie sheet.  Falls back to per-sheet "
        ".csv files if openpyxl is not installed.\n"
        "\n"
        "Returns the path of the written file."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ifc_data": {
                "type": "object",
                "description": "Normalised IFC model dict.",
            },
            "output_path": {
                "type": "string",
                "description": "Destination .xlsx file path.",
            },
            "template_name": {
                "type": "string",
                "description": "Template to apply (default: 'standard').",
                "default": "standard",
            },
        },
        "required": ["ifc_data", "output_path"],
    },
)


@register(_export_excel_spec, write=True)
async def run_bim_export_cobie_excel(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    ifc_data = a.get("ifc_data")
    if not isinstance(ifc_data, dict):
        return err_payload("ifc_data must be a JSON object", "BAD_ARGS")

    output_path = str(a.get("output_path") or "").strip()
    if not output_path:
        return err_payload("output_path is required", "BAD_ARGS")

    template_name = str(a.get("template_name") or "standard").strip()

    try:
        from kerf_bim.cobie import (
            apply_mapping_template,
            export_cobie_excel,
            get_standard_template,
        )
        template = get_standard_template(template_name)
        deliverable = apply_mapping_template(ifc_data, template)
        written_path = export_cobie_excel(deliverable, output_path)
    except ValueError as exc:
        return err_payload(str(exc), "NOT_FOUND")
    except Exception as exc:
        return err_payload(str(exc), "EXPORT_ERROR")

    return ok_payload({"path": written_path, "template_name": template_name})


# ---------------------------------------------------------------------------
# bim_compute_cobie_completeness
# ---------------------------------------------------------------------------

_completeness_spec = ToolSpec(
    name="bim_compute_cobie_completeness",
    description=(
        "Compute the COBie completeness score for an IFC dataset.\n"
        "\n"
        "Returns the fraction (0.0–1.0) and percentage of required COBie columns "
        "that have at least one populated value in the deliverable produced by "
        "applying the specified template to ifc_data."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ifc_data": {
                "type": "object",
                "description": "Normalised IFC model dict.",
            },
            "template_name": {
                "type": "string",
                "description": "Template to apply (default: 'standard').",
                "default": "standard",
            },
        },
        "required": ["ifc_data"],
    },
)


@register(_completeness_spec, write=False)
async def run_bim_compute_cobie_completeness(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    ifc_data = a.get("ifc_data")
    if not isinstance(ifc_data, dict):
        return err_payload("ifc_data must be a JSON object", "BAD_ARGS")

    template_name = str(a.get("template_name") or "standard").strip()

    try:
        from kerf_bim.cobie import (
            apply_mapping_template,
            compute_completeness_score,
            get_standard_template,
        )
        template = get_standard_template(template_name)
        deliverable = apply_mapping_template(ifc_data, template)
        score = compute_completeness_score(deliverable)
    except Exception as exc:
        return err_payload(str(exc), "COBIE_ERROR")

    return ok_payload({
        "score": round(score, 4),
        "pct": f"{score * 100:.1f}%",
        "template_name": template_name,
    })


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_get_standard_template",      _get_template_spec,  run_bim_get_standard_template),
    ("bim_apply_property_mapping",     _apply_mapping_spec, run_bim_apply_property_mapping),
    ("bim_validate_cobie",             _validate_spec,      run_bim_validate_cobie),
    ("bim_export_cobie_excel",         _export_excel_spec,  run_bim_export_cobie_excel),
    ("bim_compute_cobie_completeness", _completeness_spec,  run_bim_compute_cobie_completeness),
]
