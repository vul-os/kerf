"""
LLM tool surface for kerf-gdnt.

Exposes the following tools to the Claude / kerf-chat tool registry:

  gdnt_list_symbols         — list all GD&T symbol codes with names and Unicode
  gdnt_create_fcf           — create a feature control frame from parameters
  gdnt_validate_fcf         — validate an FCF dict and return issues
  gdnt_inspect_feature      — check a single measured value against an FCF
  gdnt_build_report         — build a full inspection report from measurements
  gdt_worst_case_stack      — 1D worst-case (arithmetic) tolerance stack-up
  gdt_rss_stack             — 1D RSS (root-sum-square) statistical stack-up
  gdt_monte_carlo_stack     — 1D Monte-Carlo tolerance stack-up + yield
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
from kerf_gdnt.tol_stack import (
    StackElement,
    worst_case_stack,
    rss_stack,
    monte_carlo_stack,
    expected_yield_at_spec,
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


# ---------------------------------------------------------------------------
# Tolerance stack-up tools — shared element-list deserialiser
# ---------------------------------------------------------------------------

_ELEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "nominal":       {"type": "number", "description": "Nominal dimension value."},
        "plus_tol":      {"type": "number", "description": "Upper tolerance (≥ 0)."},
        "minus_tol":     {"type": "number", "description": "Lower tolerance magnitude (≥ 0)."},
        "distribution":  {
            "type": "string",
            "enum": ["uniform", "normal", "triangular"],
            "description": "Assumed statistical distribution for Monte-Carlo sampling.",
            "default": "normal",
        },
        "direction": {
            "type": "integer",
            "enum": [1, -1],
            "description": "1 = additive; -1 = subtractive.",
            "default": 1,
        },
    },
    "required": ["nominal", "plus_tol", "minus_tol"],
}


def _parse_elements(raw: list[dict]) -> list[StackElement]:
    return [
        StackElement(
            nominal=float(e["nominal"]),
            plus_tol=float(e["plus_tol"]),
            minus_tol=float(e["minus_tol"]),
            distribution=e.get("distribution", "normal"),
            direction=int(e.get("direction", 1)),
        )
        for e in raw
    ]


# ---------------------------------------------------------------------------
# gdt_worst_case_stack
# ---------------------------------------------------------------------------

gdt_worst_case_stack_spec = ToolSpec(
    name="gdt_worst_case_stack",
    description=(
        "1D worst-case (arithmetic) tolerance stack-up per ASME Y14.5-2018 §11. "
        "Accumulates all element tolerances simultaneously at their worst values — "
        "gives a 100 % yield guarantee but may be overly conservative for long chains. "
        "Returns nominal sum, worst-case max/min bounds, and the total range."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": "Ordered list of tolerance chain elements.",
                "items": _ELEMENT_SCHEMA,
                "minItems": 1,
            },
        },
        "required": ["elements"],
    },
)


def run_gdt_worst_case_stack(params: dict, ctx: Any) -> str:
    try:
        elements = _parse_elements(params["elements"])
        result = worst_case_stack(elements)
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "STACK_ERROR")


# ---------------------------------------------------------------------------
# gdt_rss_stack
# ---------------------------------------------------------------------------

gdt_rss_stack_spec = ToolSpec(
    name="gdt_rss_stack",
    description=(
        "1D Root-Sum-Square (RSS) statistical tolerance stack-up (Bhote 1991 §15). "
        "Assumes independent normal distributions where 3σ = declared tolerance. "
        "Returns nominal sum, ±3σ assembly bounds (≈99.73 % yield), total σ, and 6σ range."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": "Ordered list of tolerance chain elements.",
                "items": _ELEMENT_SCHEMA,
                "minItems": 1,
            },
        },
        "required": ["elements"],
    },
)


def run_gdt_rss_stack(params: dict, ctx: Any) -> str:
    try:
        elements = _parse_elements(params["elements"])
        result = rss_stack(elements)
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "STACK_ERROR")


# ---------------------------------------------------------------------------
# gdt_monte_carlo_stack
# ---------------------------------------------------------------------------

gdt_monte_carlo_stack_spec = ToolSpec(
    name="gdt_monte_carlo_stack",
    description=(
        "1D Monte-Carlo tolerance stack-up. Samples each element according to its "
        "declared distribution (normal / uniform / triangular) and accumulates totals "
        "over n_trials iterations.  Returns mean, std, percentiles (5/95/99), "
        "observed extremes, and — if spec_min/spec_max are provided — the estimated "
        "yield (fraction of trials within spec)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": "Ordered list of tolerance chain elements.",
                "items": _ELEMENT_SCHEMA,
                "minItems": 1,
            },
            "n_trials": {
                "type": "integer",
                "description": "Number of Monte-Carlo trials (default 10 000).",
                "default": 10000,
                "minimum": 100,
                "maximum": 1000000,
            },
            "spec_min": {
                "type": "number",
                "description": "Lower specification limit for yield calculation (optional).",
            },
            "spec_max": {
                "type": "number",
                "description": "Upper specification limit for yield calculation (optional).",
            },
        },
        "required": ["elements"],
    },
)


def run_gdt_monte_carlo_stack(params: dict, ctx: Any) -> str:
    try:
        elements = _parse_elements(params["elements"])
        n_trials = int(params.get("n_trials", 10_000))
        result = monte_carlo_stack(elements, n_trials=n_trials)

        if "spec_min" in params and "spec_max" in params:
            yield_val = expected_yield_at_spec(
                elements,
                spec_min=float(params["spec_min"]),
                spec_max=float(params["spec_max"]),
                n_trials=n_trials,
            )
            result["expected_yield"] = yield_val

        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "STACK_ERROR")
# gdt_validate_datum_reference_frame   (DRF precedence -- ASME Y14.5-2018 §4.11)
# ---------------------------------------------------------------------------

gdt_validate_datum_reference_frame_spec = ToolSpec(
    name="gdt_validate_datum_reference_frame",
    description=(
        "Validate the datum reference frame (DRF) declared in a feature control "
        "frame against ASME Y14.5-2018 §4.11 datum precedence rules. Checks: "
        "3-2-1 contact (primary plane 3-pt, secondary 2-pt, tertiary 1-pt); "
        "duplicate datum letters; missing primary datum; material-boundary "
        "modifiers on features of size (RMB/MMB/LMB); conflicting modifier with "
        "feature type (e.g. MMB/LMB/RMB on a planar datum). Each violation "
        "includes an ASME Y14.5-2018 §4 rule citation. "
        "NOTE: composite tolerance frames (§10.5) are flagged but out of scope."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "datum_refs": {
                "type": "array",
                "description": (
                    "Ordered datum references from the FCF "
                    "[primary, secondary?, tertiary?]. At most 3 entries."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Datum letter, e.g. 'A'.",
                        },
                        "modifier": {
                            "type": "string",
                            "enum": ["M", "L", "S"],
                            "description": "Material-boundary modifier: M=MMB, L=LMB, S=RMB/RFS.",
                        },
                    },
                    "required": ["label"],
                },
                "maxItems": 3,
            },
            "datums": {
                "type": "object",
                "description": (
                    "Registry of datum features on the drawing. Keys are datum "
                    "letters; values describe the nominated feature."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "feature_type": {
                            "type": "string",
                            "enum": [
                                "flat_face", "plane", "cylinder", "cone",
                                "sphere", "slot", "width",
                            ],
                            "description": "Geometric type of the nominated datum feature.",
                        },
                        "is_datum_target": {
                            "type": "boolean",
                            "description": "True when datum targets (§4.24) are used.",
                            "default": False,
                        },
                        "target_type": {
                            "type": "string",
                            "enum": ["point", "line", "area", "movable"],
                            "description": "Type of datum target (§4.24 Fig. 4-11).",
                        },
                    },
                    "required": ["feature_type"],
                },
            },
            "is_composite_lower_segment": {
                "type": "boolean",
                "description": (
                    "Set True if this is the lower segment of a composite "
                    "tolerance frame (§10.5). DRF precedence checks are skipped "
                    "-- out of scope."
                ),
                "default": False,
            },
        },
        "required": ["datum_refs", "datums"],
    },
)


def run_gdt_validate_datum_reference_frame(params: dict, ctx: Any) -> str:
    try:
        from kerf_gdnt.datum_reference_validator import (
            validate_datum_reference_frame,
            DatumReferenceEntry,
            DatumInfo,
        )

        frame_datums = [
            DatumReferenceEntry(
                label=d["label"],
                modifier=d.get("modifier"),
            )
            for d in params.get("datum_refs", [])
        ]

        datum_registry: dict[str, DatumInfo] = {}
        for label, info in params.get("datums", {}).items():
            datum_registry[label] = DatumInfo(
                label=label,
                feature_type=info["feature_type"],
                is_datum_target=bool(info.get("is_datum_target", False)),
                target_type=info.get("target_type"),
            )

        report = validate_datum_reference_frame(
            frame_datums=frame_datums,
            datum_registry=datum_registry,
            is_composite_lower_segment=bool(
                params.get("is_composite_lower_segment", False)
            ),
        )
        return ok_payload(report.to_dict())
    except Exception as exc:
        return err_payload(str(exc), "DRF_VALIDATE_ERROR")


# ---------------------------------------------------------------------------
# gdt_validate_composite_tolerance_frame  (§10.5 PLTZF/FRTZF)
# ---------------------------------------------------------------------------

gdt_validate_composite_tolerance_frame_spec = ToolSpec(
    name="gdt_validate_composite_tolerance_frame",
    description=(
        "Parse and validate an ASME Y14.5-2018 §10.5 composite position tolerance "
        "frame (PLTZF / FRTZF). "
        "A composite frame has two lines: the upper line (PLTZF, Pattern-Locating "
        "Tolerance Zone Framework) controls location of the entire pattern; the "
        "lower line (FRTZF, Feature-Relating Tolerance Zone Framework) controls "
        "feature-to-feature relationships. "
        "Rules checked: FRTZF tolerance ≤ PLTZF tolerance (§10.5.1 Note 2); "
        "FRTZF primary datum must match PLTZF primary datum (§10.5.1(a)); "
        "FRTZF datums must be a precedence-ordered subset of PLTZF datums "
        "(§10.5.1(b)); symbol must match between lines. "
        "Each violation includes a §10.5 rule citation. "
        "HONEST FLAG: parser accepts one canonical text format only — "
        "full Unicode GD&T requires a dedicated lexer. "
        "Input text format: 'symbol|[D]tol[M|L|S]|datum1|... / symbol|[D]tol[M|L|S]|datum1|...'"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "frame_text": {
                "type": "string",
                "description": (
                    "Composite tolerance frame in canonical text form. "
                    "Two lines separated by '/'. "
                    "Example: 'position|D0.5|A|B|C / position|D0.2|A' "
                    "(PLTZF: ⌀0.5 A|B|C; FRTZF: ⌀0.2 A). "
                    "Symbol codes: position, flatness, perpendicularity, etc. "
                    "D prefix = diameter zone. Modifier suffix: M=MMC, L=LMC, S=RFS."
                ),
            },
        },
        "required": ["frame_text"],
    },
)


def run_gdt_validate_composite_tolerance_frame(params: dict, ctx: Any) -> str:
    try:
        from kerf_gdnt.composite_tolerance import (
            parse_composite_frame,
            validate_composite_frame,
        )
        frame = parse_composite_frame(params["frame_text"])
        report = validate_composite_frame(frame)
        return ok_payload({
            "valid": report.valid,
            "pltzf": frame.pltzf.__dict__,
            "frtzf": frame.frtzf.__dict__,
            **report.to_dict(),
        })
    except ValueError as exc:
        return err_payload(str(exc), "COMPOSITE_PARSE_ERROR")
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITE_VALIDATE_ERROR")
