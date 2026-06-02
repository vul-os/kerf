"""
drawing_list.py — LLM tools for the Drawing List / Multi-Sheet Manager.

Exposes:
    bim_auto_number_sheets        — assign AIA NCS sheet numbers
    bim_validate_drawing_list     — check for errors in a drawing set
    bim_compute_cross_references  — find + verify detail markers
    bim_generate_drawing_index    — write an index/title sheet file
    bim_compute_drawing_list_report — full report for a document set
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:  # pragma: no cover — stubs injected in tests
    ToolSpec = None  # type: ignore[assignment]
    err_payload = None  # type: ignore[assignment]
    ok_payload  = None  # type: ignore[assignment]
    register    = None  # type: ignore[assignment]
    ProjectCtx  = None  # type: ignore[assignment]

from kerf_bim.drawing_list import (
    SheetSize,
    SheetSpec,
    auto_number_sheets,
    compute_cross_references,
    compute_drawing_list_report,
    generate_drawing_index_sheet,
    validate_drawing_list,
)

# ── helpers ───────────────────────────────────────────────────────────────────

_VALID_DISCIPLINES = {
    "architectural", "structural", "mep", "civil", "interior", "general"
}
_VALID_SCHEMES = {"aia_standard", "preserve_existing"}
_VALID_FORMATS = {"dxf", "pdf"}

_SHEET_SIZE_VALUES = [s.value for s in SheetSize]

_SHEET_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "title":        {"type": "string"},
        "discipline":   {"type": "string", "enum": sorted(_VALID_DISCIPLINES)},
        "sheet_size":   {"type": "string", "enum": _SHEET_SIZE_VALUES},
        "scale":        {"type": "string"},
        "sheet_number": {"type": "string"},
        "viewports":    {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "view_ref": {"type": "string"},
                    "origin":   {"type": "array", "items": {"type": "number"}},
                },
            },
        },
        "revision":   {"type": "string"},
        "drawn_by":   {"type": "string"},
        "issue_date": {"type": "string"},
    },
    "required": ["title", "discipline"],
}


def _parse_sheet_specs(raw: list[dict]) -> list[SheetSpec] | str:
    """Convert raw dicts into SheetSpec objects; return an error string on failure."""
    specs: list[SheetSpec] = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            return f"sheets[{i}] must be an object"
        title = d.get("title", "")
        disc  = d.get("discipline", "")
        if not title:
            return f"sheets[{i}] missing 'title'"
        if disc not in _VALID_DISCIPLINES:
            return f"sheets[{i}] discipline must be one of {sorted(_VALID_DISCIPLINES)}"
        try:
            size_str = d.get("sheet_size", "A1")
            size = SheetSize(size_str)
        except ValueError:
            return f"sheets[{i}] sheet_size '{d.get('sheet_size')}' is invalid"
        specs.append(SheetSpec(
            title=title,
            discipline=disc,
            sheet_size=size,
            scale=d.get("scale", "1:100"),
            viewports=d.get("viewports", []),
            sheet_number=d.get("sheet_number", ""),
            revision=d.get("revision", ""),
            drawn_by=d.get("drawn_by", ""),
            issue_date=d.get("issue_date", ""),
        ))
    return specs


def _sheet_to_dict(s: SheetSpec) -> dict:
    return {
        "sheet_number": s.sheet_number,
        "title":        s.title,
        "discipline":   s.discipline,
        "sheet_size":   s.sheet_size.value,
        "scale":        s.scale,
        "viewports":    s.viewports,
        "revision":     s.revision,
        "drawn_by":     s.drawn_by,
        "issue_date":   s.issue_date,
    }


# ── gated import guard ────────────────────────────────────────────────────────

if ToolSpec is None or register is None:
    # Running in test stubs or outside the Kerf runtime; skip tool registration.
    TOOLS: list = []
else:

    # ── bim_auto_number_sheets ────────────────────────────────────────────────

    _auto_number_spec = ToolSpec(
        name="bim_auto_number_sheets",
        description=(
            "Auto-number a list of sheets following the AIA NCS 2.0 convention "
            "(A-101/A-102 for architectural, S-201 for structural, etc.). "
            "Returns the sheets with sheet_number fields populated."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sheets": {
                    "type": "array",
                    "description": "List of sheet spec objects",
                    "items": _SHEET_SPEC_SCHEMA,
                },
                "scheme": {
                    "type": "string",
                    "enum": sorted(_VALID_SCHEMES),
                    "description": "Numbering scheme: 'aia_standard' (default) or 'preserve_existing'",
                },
            },
            "required": ["sheets"],
        },
    )

    @register(_auto_number_spec)
    async def run_bim_auto_number_sheets(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        raw_sheets = a.get("sheets")
        if not isinstance(raw_sheets, list):
            return err_payload("'sheets' must be an array", "BAD_ARGS")

        scheme = a.get("scheme", "aia_standard")
        if scheme not in _VALID_SCHEMES:
            return err_payload(f"scheme must be one of {sorted(_VALID_SCHEMES)}", "BAD_ARGS")

        result = _parse_sheet_specs(raw_sheets)
        if isinstance(result, str):
            return err_payload(result, "BAD_ARGS")

        numbered = auto_number_sheets(result, scheme=scheme)
        return ok_payload({"sheets": [_sheet_to_dict(s) for s in numbered]})

    # ── bim_validate_drawing_list ─────────────────────────────────────────────

    _validate_spec = ToolSpec(
        name="bim_validate_drawing_list",
        description=(
            "Validate a construction document drawing set. "
            "Checks for duplicate sheet numbers, missing titles/numbers, "
            "and orphaned cross-references. Returns a list of error strings "
            "(empty list means the set is valid)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sheets": {
                    "type": "array",
                    "items": _SHEET_SPEC_SCHEMA,
                },
            },
            "required": ["sheets"],
        },
    )

    @register(_validate_spec)
    async def run_bim_validate_drawing_list(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        raw_sheets = a.get("sheets")
        if not isinstance(raw_sheets, list):
            return err_payload("'sheets' must be an array", "BAD_ARGS")

        result = _parse_sheet_specs(raw_sheets)
        if isinstance(result, str):
            return err_payload(result, "BAD_ARGS")

        errors = validate_drawing_list(result)
        return ok_payload({"errors": errors, "valid": len(errors) == 0})

    # ── bim_compute_cross_references ──────────────────────────────────────────

    _xref_spec = ToolSpec(
        name="bim_compute_cross_references",
        description=(
            "Scan all viewport view_refs for detail markers (format '<n>/<sheet>') "
            "and return resolved cross-references as (from_sheet, to_sheet, marker) tuples."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sheets": {
                    "type": "array",
                    "items": _SHEET_SPEC_SCHEMA,
                },
            },
            "required": ["sheets"],
        },
    )

    @register(_xref_spec)
    async def run_bim_compute_cross_references(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        raw_sheets = a.get("sheets")
        if not isinstance(raw_sheets, list):
            return err_payload("'sheets' must be an array", "BAD_ARGS")

        result = _parse_sheet_specs(raw_sheets)
        if isinstance(result, str):
            return err_payload(result, "BAD_ARGS")

        refs = compute_cross_references(result)
        return ok_payload({
            "cross_references": [
                {"from_sheet": f, "to_sheet": t, "marker": m}
                for f, t, m in refs
            ]
        })

    # ── bim_generate_drawing_index ────────────────────────────────────────────

    _generate_spec = ToolSpec(
        name="bim_generate_drawing_index",
        description=(
            "Generate a drawing index / title sheet for the document set. "
            "Returns the path to the written index file. "
            "output_format must be 'dxf' or 'pdf'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sheets": {
                    "type": "array",
                    "items": _SHEET_SPEC_SCHEMA,
                },
                "output_format": {
                    "type": "string",
                    "enum": ["dxf", "pdf"],
                },
            },
            "required": ["sheets"],
        },
    )

    @register(_generate_spec)
    async def run_bim_generate_drawing_index(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        raw_sheets = a.get("sheets")
        if not isinstance(raw_sheets, list):
            return err_payload("'sheets' must be an array", "BAD_ARGS")

        output_format = a.get("output_format", "dxf")
        if output_format not in _VALID_FORMATS:
            return err_payload(f"output_format must be one of {sorted(_VALID_FORMATS)}", "BAD_ARGS")

        result = _parse_sheet_specs(raw_sheets)
        if isinstance(result, str):
            return err_payload(result, "BAD_ARGS")

        try:
            path = generate_drawing_index_sheet(result, output_format=output_format)
        except Exception as exc:
            return err_payload(str(exc), "GENERATE_ERROR")

        return ok_payload({"path": path, "output_format": output_format, "sheet_count": len(result)})

    # ── bim_compute_drawing_list_report ───────────────────────────────────────

    _report_spec = ToolSpec(
        name="bim_compute_drawing_list_report",
        description=(
            "Compute a full Drawing List Report for a construction document set: "
            "total sheet count, breakdown by discipline, summary table, and "
            "resolved cross-references."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sheets": {
                    "type": "array",
                    "items": _SHEET_SPEC_SCHEMA,
                },
            },
            "required": ["sheets"],
        },
    )

    @register(_report_spec)
    async def run_bim_compute_drawing_list_report(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        raw_sheets = a.get("sheets")
        if not isinstance(raw_sheets, list):
            return err_payload("'sheets' must be an array", "BAD_ARGS")

        result = _parse_sheet_specs(raw_sheets)
        if isinstance(result, str):
            return err_payload(result, "BAD_ARGS")

        report = compute_drawing_list_report(result)
        return ok_payload({
            "total_sheets":          report.total_sheets,
            "sheets_by_discipline":  report.sheets_by_discipline,
            "sheet_summary_table":   report.sheet_summary_table,
            "cross_references": [
                {"from_sheet": f, "to_sheet": t, "marker": m}
                for f, t, m in report.cross_references
            ],
            "honest_caveat": report.honest_caveat,
        })

    TOOLS = [
        ("bim_auto_number_sheets",       _auto_number_spec,  run_bim_auto_number_sheets),
        ("bim_validate_drawing_list",    _validate_spec,     run_bim_validate_drawing_list),
        ("bim_compute_cross_references", _xref_spec,         run_bim_compute_cross_references),
        ("bim_generate_drawing_index",   _generate_spec,     run_bim_generate_drawing_index),
        ("bim_compute_drawing_list_report", _report_spec,    run_bim_compute_drawing_list_report),
    ]
