"""
LLM tool surface for kerf-gdnt.

Exposes the following tools to the Claude / kerf-chat tool registry:

  gdnt_list_symbols       — list all GD&T symbol codes with names and Unicode
  gdnt_create_fcf         — create a feature control frame from parameters
  gdnt_validate_fcf       — validate an FCF dict and return issues
  gdnt_inspect_feature    — check a single measured value against an FCF
  gdnt_build_report       — build a full inspection report from measurements
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_gdnt._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_gdnt.symbols import ALL_SYMBOLS, ALL_MODIFIERS
from kerf_gdnt.feature_control_frame import DatumReference, FeatureControlFrame
from kerf_gdnt.inspection_report import (
    InspectionRow,
    InspectionReport,
    build_report,
    render_report,
    report_to_dicts,
)


# ---------------------------------------------------------------------------
# gdnt_list_symbols
# ---------------------------------------------------------------------------

gdnt_list_symbols_spec = ToolSpec(
    name="gdnt_list_symbols",
    description=(
        "List all GD&T / PMI symbol codes supported by kerf-gdnt, with their "
        "Unicode characters, names, categories, and ISO 1101 / ASME Y14.5 references."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["form", "orientation", "location", "runout", "profile", "all"],
                "description": "Filter by category (default: all).",
            },
        },
    },
)


def run_gdnt_list_symbols(params: dict, ctx: Any) -> str:
    cat = params.get("category", "all")
    symbols = list(ALL_SYMBOLS.values())
    if cat != "all":
        symbols = [s for s in symbols if s.category == cat]
    result = [
        {
            "code": s.code,
            "unicode": s.unicode,
            "name": s.name,
            "category": s.category,
            "iso_code": s.iso_code,
            "asme_code": s.asme_code,
        }
        for s in symbols
    ]
    modifiers = [
        {
            "code": m.code,
            "unicode": m.unicode,
            "name": m.name,
        }
        for m in ALL_MODIFIERS.values()
    ]
    return ok_payload({"symbols": result, "modifiers": modifiers})


# ---------------------------------------------------------------------------
# gdnt_create_fcf
# ---------------------------------------------------------------------------

gdnt_create_fcf_spec = ToolSpec(
    name="gdnt_create_fcf",
    description=(
        "Create a Feature Control Frame (FCF) — the standard rectangular box that "
        "encodes a GD&T tolerance callout.  Returns the rendered Unicode form "
        "(e.g. ⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐) and a serialised dict."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbol_code": {
                "type": "string",
                "description": "GD&T symbol code, e.g. 'position', 'flatness', 'perpendicularity'.",
            },
            "tolerance_value": {
                "type": "number",
                "description": "Numeric tolerance value in drawing units (mm or inches).",
            },
            "diameter_zone": {
                "type": "boolean",
                "description": "True for cylindrical tolerance zones (prefix ⌀).",
                "default": False,
            },
            "tolerance_modifier": {
                "type": "string",
                "enum": ["M", "L", "S", "F", "P", "T"],
                "description": "Material condition modifier: M=MMC, L=LMC, S=RFS, F=free-state, P=projected, T=tangent.",
            },
            "datum_refs": {
                "type": "array",
                "description": "Ordered datum references [primary, secondary, tertiary].",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "modifier": {
                            "type": "string",
                            "enum": ["M", "L", "S"],
                        },
                    },
                    "required": ["label"],
                },
                "maxItems": 3,
            },
            "note": {
                "type": "string",
                "description": "Optional annotation.",
            },
        },
        "required": ["symbol_code", "tolerance_value"],
    },
)


def run_gdnt_create_fcf(params: dict, ctx: Any) -> str:
    try:
        datum_refs = [
            DatumReference(label=d["label"], modifier=d.get("modifier"))
            for d in params.get("datum_refs", [])
        ]
        fcf = FeatureControlFrame(
            symbol_code=params["symbol_code"],
            tolerance_value=float(params["tolerance_value"]),
            diameter_zone=bool(params.get("diameter_zone", False)),
            tolerance_modifier=params.get("tolerance_modifier"),
            datum_refs=datum_refs,
            note=params.get("note"),
        )
        issues = fcf.validate()
        if issues:
            return err_payload("; ".join(issues), "BAD_FCF")
        return ok_payload(fcf.to_dict())
    except Exception as exc:
        return err_payload(str(exc), "FCF_ERROR")


# ---------------------------------------------------------------------------
# gdnt_validate_fcf
# ---------------------------------------------------------------------------

gdnt_validate_fcf_spec = ToolSpec(
    name="gdnt_validate_fcf",
    description="Validate an FCF dict and return any issues (empty list = valid).",
    input_schema={
        "type": "object",
        "properties": {
            "fcf": {
                "type": "object",
                "description": "FCF dict as returned by gdnt_create_fcf.",
            },
        },
        "required": ["fcf"],
    },
)


def run_gdnt_validate_fcf(params: dict, ctx: Any) -> str:
    try:
        fcf = FeatureControlFrame.from_dict(params["fcf"])
        issues = fcf.validate()
        return ok_payload({"valid": len(issues) == 0, "issues": issues})
    except Exception as exc:
        return err_payload(str(exc), "VALIDATE_ERROR")


# ---------------------------------------------------------------------------
# gdnt_inspect_feature
# ---------------------------------------------------------------------------

gdnt_inspect_feature_spec = ToolSpec(
    name="gdnt_inspect_feature",
    description=(
        "Check a single CMM / gauge measurement against a tolerance specification. "
        "Returns pass/fail, deviation, and whether the result is within the tolerance zone."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "feature_id": {
                "type": "string",
                "description": "Feature label, e.g. 'F1', 'top_face'.",
            },
            "fcf": {
                "type": "object",
                "description": "FCF dict from gdnt_create_fcf.",
            },
            "nominal": {
                "type": "number",
                "description": "Nominal (design) value.",
            },
            "measured": {
                "type": "number",
                "description": "Actual measured value.",
            },
            "unilateral": {
                "type": "boolean",
                "description": "True for unilateral zone [nominal, nominal+tol]; false (default) for bilateral ±tol/2.",
                "default": False,
            },
        },
        "required": ["feature_id", "fcf", "nominal", "measured"],
    },
)


def run_gdnt_inspect_feature(params: dict, ctx: Any) -> str:
    try:
        fcf = FeatureControlFrame.from_dict(params["fcf"])
        row = InspectionRow(
            feature_id=params["feature_id"],
            fcf=fcf,
            nominal=float(params["nominal"]),
            measured=float(params["measured"]),
            unilateral=bool(params.get("unilateral", False)),
        )
        return ok_payload(row.to_dict())
    except Exception as exc:
        return err_payload(str(exc), "INSPECT_ERROR")


# ---------------------------------------------------------------------------
# gdnt_build_report
# ---------------------------------------------------------------------------

gdnt_build_report_spec = ToolSpec(
    name="gdnt_build_report",
    description=(
        "Build a full homologation-style GD&T inspection report from a list of "
        "measurement records.  Returns the Markdown report text and a structured "
        "JSON summary."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_number": {
                "type": "string",
                "description": "Drawing part number.",
            },
            "revision": {
                "type": "string",
                "description": "Drawing revision, e.g. 'B'.",
                "default": "A",
            },
            "inspector": {
                "type": "string",
                "description": "Inspector name or ID.",
                "default": "",
            },
            "inspection_date": {
                "type": "string",
                "description": "ISO 8601 date string, e.g. '2025-06-01'. Defaults to today.",
            },
            "measurements": {
                "type": "array",
                "description": "List of measurement records.",
                "items": {
                    "type": "object",
                    "properties": {
                        "feature_id": {"type": "string"},
                        "fcf": {"type": "object"},
                        "nominal": {"type": "number"},
                        "measured": {"type": "number"},
                        "unilateral": {"type": "boolean"},
                    },
                    "required": ["feature_id", "fcf", "nominal", "measured"],
                },
            },
            "units": {
                "type": "string",
                "description": "Unit label for display, e.g. 'mm' or 'in'.",
                "default": "mm",
            },
        },
        "required": ["part_number", "measurements"],
    },
)


def run_gdnt_build_report(params: dict, ctx: Any) -> str:
    try:
        idate = None
        if params.get("inspection_date"):
            idate = date.fromisoformat(params["inspection_date"])

        measurements = []
        for m in params["measurements"]:
            fcf = FeatureControlFrame.from_dict(m["fcf"])
            measurements.append({
                "feature_id": m["feature_id"],
                "fcf": fcf,
                "nominal": float(m["nominal"]),
                "measured": float(m["measured"]),
                "unilateral": bool(m.get("unilateral", False)),
            })

        report = build_report(
            part_number=params["part_number"],
            measurements=measurements,
            revision=params.get("revision", "A"),
            inspector=params.get("inspector", ""),
            inspection_date=idate,
        )

        units = params.get("units", "mm")
        markdown = render_report(report, units=units)
        rows = report_to_dicts(report)

        return ok_payload({
            "markdown": markdown,
            "rows": rows,
            "summary": {
                "total": report.total,
                "passed": report.passed_count,
                "failed": report.failed_count,
                "overall_pass": report.overall_pass,
            },
        })
    except Exception as exc:
        return err_payload(str(exc), "REPORT_ERROR")
