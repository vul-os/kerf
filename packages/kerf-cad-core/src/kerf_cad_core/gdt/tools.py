"""
kerf_cad_core.gdt.tools — LLM tool wrappers for the GD&T framework.

Registers four tools with the Kerf tool registry:

  gdt_apply_datum        — define / update a datum (letter + type + feature ref)
  gdt_apply_tolerance    — attach a geometric tolerance to a named feature
  gdt_validate_scheme    — validate a complete set of datums + tolerances
  gdt_callout_report     — render a formatted callout report

All tools are pure-Python; no OCC dependency, no DB write required for the
validate / report paths.  ``gdt_apply_datum`` and ``gdt_apply_tolerance`` are
data-model operations that store entries in-session (via the returned payload)
and are idempotent re-runs.

Validation rules (gdt_validate_scheme):
  - Position tolerance requires at least one datum reference.
  - Concentricity / Symmetry require an axis or centre-plane datum (AXIS or
    CENTRE_PLANE datum type) in the reference frame.
  - MMC modifier is only valid for features of size
    (is_feature_of_size == True).
  - Runout / Total Runout require exactly one datum reference, which must be
    a cylindrical (AXIS) datum.
  - Datum reference frames must have proper precedence ordering: tertiary
    requires secondary; secondary requires primary.
  - Returns {ok: bool, errors: [...]} — never raises on bad input.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.gdt.datums import Datum, DatumReferenceFrame, DatumType
from kerf_cad_core.gdt.tolerances import GeometricTolerance, ToleranceSymbol
from kerf_cad_core.gdt.modifiers import ToleranceModifier, requires_feature_of_size
from kerf_cad_core.gdt.report import gdt_callout_report as _build_report


# ---------------------------------------------------------------------------
# Validation logic (importable independently for tests)
# ---------------------------------------------------------------------------

def _validate_scheme(
    datums: list[dict],
    tolerances: list[dict],
) -> dict[str, Any]:
    """
    Validate a datum + tolerance scheme.  Returns {ok, errors}.
    Never raises.
    """
    errors: list[str] = []

    # Build datum label → datum_type map
    datum_map: dict[str, DatumType] = {}
    for i, raw in enumerate(datums):
        try:
            d = Datum.from_dict(raw)
            datum_map[d.label] = d.datum_type
        except Exception as exc:
            errors.append(f"datums[{i}]: {exc}")

    # Parse and validate tolerances
    for i, raw in enumerate(tolerances):
        try:
            t = GeometricTolerance.from_dict(raw)
        except Exception as exc:
            errors.append(f"tolerances[{i}]: parse error: {exc}")
            continue

        drf = t.datum_ref
        sym = t.symbol

        # ── Rule: Position requires at least one datum reference ─────────
        if sym == ToleranceSymbol.POSITION and drf.is_empty:
            errors.append(
                f"tolerances[{i}] ({t.feature_name}): POSITION requires at least "
                "one datum reference"
            )

        # ── Rule: Concentricity / Symmetry require axis/centre-plane datum ─
        if sym in (ToleranceSymbol.CONCENTRICITY, ToleranceSymbol.SYMMETRY):
            if drf.is_empty:
                errors.append(
                    f"tolerances[{i}] ({t.feature_name}): {sym.value} requires an "
                    "axis or centre-plane datum reference"
                )
            else:
                required_types = {DatumType.AXIS, DatumType.CENTRE_PLANE}
                has_valid = False
                for label in drf.labels:
                    if datum_map.get(label) in required_types:
                        has_valid = True
                        break
                if not has_valid:
                    errors.append(
                        f"tolerances[{i}] ({t.feature_name}): {sym.value} requires "
                        "a datum of type AXIS or CENTRE_PLANE; none found among "
                        f"references {drf.labels}"
                    )

        # ── Rule: MMC only valid for features of size ─────────────────────
        if ToleranceModifier.MMC in t.modifiers and not t.is_feature_of_size:
            errors.append(
                f"tolerances[{i}] ({t.feature_name}): MMC modifier requires "
                "is_feature_of_size == true"
            )

        # ── Rule: LMC only valid for features of size ─────────────────────
        if ToleranceModifier.LMC in t.modifiers and not t.is_feature_of_size:
            errors.append(
                f"tolerances[{i}] ({t.feature_name}): LMC modifier requires "
                "is_feature_of_size == true"
            )

        # ── Rule: Runout / Total Runout require exactly one AXIS datum ─────
        if sym in (ToleranceSymbol.RUNOUT, ToleranceSymbol.TOTAL_RUNOUT):
            labels = drf.labels
            if len(labels) != 1:
                errors.append(
                    f"tolerances[{i}] ({t.feature_name}): {sym.value} requires "
                    f"exactly one datum reference; got {len(labels)}"
                )
            else:
                label = labels[0]
                dt = datum_map.get(label)
                if dt != DatumType.AXIS:
                    errors.append(
                        f"tolerances[{i}] ({t.feature_name}): {sym.value} datum "
                        f"'{label}' must be of type AXIS (cylindrical datum); got "
                        f"{dt.value if dt else 'unknown'}"
                    )

        # ── Rule: Datum reference frame precedence ordering ────────────────
        if drf.tertiary and not drf.secondary:
            errors.append(
                f"tolerances[{i}] ({t.feature_name}): datum_ref has tertiary "
                "without secondary — invalid precedence order"
            )

        # ── Rule: PROJECTED modifier requires projected_zone_height ────────
        if ToleranceModifier.PROJECTED in t.modifiers:
            if t.projected_zone_height is None or t.projected_zone_height <= 0:
                errors.append(
                    f"tolerances[{i}] ({t.feature_name}): PROJECTED modifier "
                    "requires projected_zone_height > 0"
                )

    return {"ok": len(errors) == 0, "errors": errors}


# ---------------------------------------------------------------------------
# Tool: gdt_apply_datum
# ---------------------------------------------------------------------------

_apply_datum_spec = ToolSpec(
    name="gdt_apply_datum",
    description=(
        "Define or update a GD&T datum (per ASME Y14.5 / ISO 1101). "
        "A datum is a theoretically exact geometric reference (plane, axis, "
        "centre-plane, or point) derived from a real feature on the part. "
        "Each datum is identified by a letter label (A, B, C, …).\n"
        "\n"
        "datum_type options:\n"
        "  PLANE         — flat surface  → datum plane\n"
        "  AXIS          — cylinder/cone → datum axis (use for runout/position)\n"
        "  CENTRE_PLANE  — slot/tab      → centre plane (use for symmetry)\n"
        "  POINT         — sphere centre → datum point\n"
        "  LINE          — edge / line element\n"
        "\n"
        "Returns the datum dict for use in gdt_apply_tolerance and "
        "gdt_validate_scheme."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "Datum letter label, e.g. 'A', 'B', 'C'.",
            },
            "datum_type": {
                "type": "string",
                "enum": ["PLANE", "AXIS", "CENTRE_PLANE", "POINT", "LINE"],
                "description": "Geometric type of the datum feature. Default PLANE.",
            },
            "feature_ref": {
                "type": "string",
                "description": (
                    "Optional reference to the feature this datum targets "
                    "(face name, surface id, feature node id)."
                ),
            },
            "description": {
                "type": "string",
                "description": "Human-readable annotation.",
            },
            "is_compound": {
                "type": "boolean",
                "description": "True for compound (co-datum) references like 'A-B'.",
            },
        },
        "required": ["label"],
    },
)


@register(_apply_datum_spec, write=False)
async def run_gdt_apply_datum(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    label = str(a.get("label", "")).strip()
    if not label:
        return err_payload("label is required", "BAD_ARGS")

    datum_type_str = str(a.get("datum_type", "PLANE")).upper()
    try:
        datum_type = DatumType(datum_type_str)
    except ValueError:
        valid = [e.value for e in DatumType]
        return err_payload(
            f"Invalid datum_type '{datum_type_str}'. Valid: {valid}", "BAD_ARGS"
        )

    try:
        datum = Datum(
            label=label,
            datum_type=datum_type,
            feature_ref=a.get("feature_ref"),
            description=a.get("description"),
            is_compound=bool(a.get("is_compound", False)),
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    return ok_payload({"datum": datum.to_dict(), "message": f"Datum '{label}' defined."})


# ---------------------------------------------------------------------------
# Tool: gdt_apply_tolerance
# ---------------------------------------------------------------------------

_apply_tolerance_spec = ToolSpec(
    name="gdt_apply_tolerance",
    description=(
        "Attach a geometric tolerance (feature control frame) to a named feature "
        "per ASME Y14.5 / ISO 1101.\n"
        "\n"
        "symbol options (14 characteristics):\n"
        "  Form:        FLATNESS, STRAIGHTNESS, CIRCULARITY, CYLINDRICITY\n"
        "  Profile:     PROFILE_LINE, PROFILE_SURFACE\n"
        "  Orientation: PARALLELISM, PERPENDICULARITY, ANGULARITY\n"
        "  Location:    POSITION, CONCENTRICITY, SYMMETRY\n"
        "  Runout:      RUNOUT, TOTAL_RUNOUT\n"
        "\n"
        "modifiers (standard Y14.5 set):\n"
        "  MMC, LMC, RFS, PROJECTED, TANGENT, FREE_STATE,\n"
        "  STATISTICAL, CONTINUOUS_FEATURE, INDEPENDENCY, UNEQUAL_BILATERAL\n"
        "\n"
        "datum_ref: {primary, secondary, tertiary} — datum labels in precedence order.\n"
        "For POSITION set at least primary. For RUNOUT/TOTAL_RUNOUT set only primary "
        "(must be an AXIS datum). Form tolerances need no datum_ref.\n"
        "\n"
        "Returns the tolerance dict for use in gdt_validate_scheme and "
        "gdt_callout_report."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "feature_name": {
                "type": "string",
                "description": "Name or id of the feature being toleranced.",
            },
            "symbol": {
                "type": "string",
                "enum": [s.value for s in ToleranceSymbol],
                "description": "GD&T characteristic symbol.",
            },
            "tolerance_value": {
                "type": "number",
                "description": "Tolerance zone width/diameter in mm (> 0).",
            },
            "diameter_zone": {
                "type": "boolean",
                "description": "True for cylindrical tolerance zone (⌀ prefix). Default false.",
            },
            "datum_ref": {
                "type": "object",
                "description": "Datum reference frame: {primary, secondary, tertiary}.",
                "properties": {
                    "primary":   {"type": "string"},
                    "secondary": {"type": "string"},
                    "tertiary":  {"type": "string"},
                },
            },
            "modifiers": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [m.value for m in ToleranceModifier],
                },
                "description": "Applicable Y14.5 modifiers.",
            },
            "is_feature_of_size": {
                "type": "boolean",
                "description": (
                    "True when the feature has an actual size (shaft, hole, slot). "
                    "Required to be true when using MMC or LMC modifiers."
                ),
            },
            "projected_zone_height": {
                "type": "number",
                "description": "Required when PROJECTED modifier is used (mm > 0).",
            },
            "note": {
                "type": "string",
                "description": "Optional annotation.",
            },
        },
        "required": ["feature_name", "symbol", "tolerance_value"],
    },
)


@register(_apply_tolerance_spec, write=False)
async def run_gdt_apply_tolerance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    feature_name = str(a.get("feature_name", "")).strip()
    if not feature_name:
        return err_payload("feature_name is required", "BAD_ARGS")

    symbol_str = str(a.get("symbol", "")).upper()
    try:
        symbol = ToleranceSymbol(symbol_str)
    except ValueError:
        valid = [s.value for s in ToleranceSymbol]
        return err_payload(f"Invalid symbol '{symbol_str}'. Valid: {valid}", "BAD_ARGS")

    tol_val = a.get("tolerance_value")
    if tol_val is None:
        return err_payload("tolerance_value is required", "BAD_ARGS")
    try:
        tol_val = float(tol_val)
    except (TypeError, ValueError):
        return err_payload("tolerance_value must be a number", "BAD_ARGS")
    if tol_val <= 0:
        return err_payload(f"tolerance_value must be > 0, got {tol_val}", "BAD_ARGS")

    # datum_ref
    drf_raw = a.get("datum_ref") or {}
    try:
        drf = DatumReferenceFrame.from_dict(drf_raw)
    except ValueError as exc:
        return err_payload(f"datum_ref: {exc}", "BAD_ARGS")

    # modifiers
    mods_raw = a.get("modifiers") or []
    mods: list[ToleranceModifier] = []
    for m in mods_raw:
        try:
            mods.append(ToleranceModifier(str(m).upper()))
        except ValueError:
            valid = [x.value for x in ToleranceModifier]
            return err_payload(f"Invalid modifier '{m}'. Valid: {valid}", "BAD_ARGS")

    try:
        tol = GeometricTolerance(
            feature_name=feature_name,
            symbol=symbol,
            tolerance_value=tol_val,
            diameter_zone=bool(a.get("diameter_zone", False)),
            datum_ref=drf,
            modifiers=mods,
            is_feature_of_size=bool(a.get("is_feature_of_size", False)),
            projected_zone_height=a.get("projected_zone_height"),
            note=a.get("note"),
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    return ok_payload({
        "tolerance": tol.to_dict(),
        "message": f"Tolerance {symbol.value} applied to '{feature_name}'.",
    })


# ---------------------------------------------------------------------------
# Tool: gdt_validate_scheme
# ---------------------------------------------------------------------------

_validate_scheme_spec = ToolSpec(
    name="gdt_validate_scheme",
    description=(
        "Validate a complete GD&T scheme (datum set + tolerance set) against "
        "ASME Y14.5 / ISO 1101 rules.\n"
        "\n"
        "Checks:\n"
        "  - POSITION requires at least one datum reference\n"
        "  - CONCENTRICITY / SYMMETRY require an AXIS or CENTRE_PLANE datum\n"
        "  - MMC / LMC modifiers only valid when is_feature_of_size == true\n"
        "  - RUNOUT / TOTAL_RUNOUT require exactly one datum of type AXIS\n"
        "  - Datum reference frames: tertiary requires secondary; secondary "
        "requires primary\n"
        "  - PROJECTED modifier requires projected_zone_height > 0\n"
        "\n"
        "Returns {ok: bool, errors: [string...]}. Never raises on bad input.\n"
        "\n"
        "Pass the datum dicts from gdt_apply_datum and the tolerance dicts from "
        "gdt_apply_tolerance (or build them inline)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "datums": {
                "type": "array",
                "description": "List of datum dicts (from gdt_apply_datum output.datum).",
                "items": {
                    "type": "object",
                    "properties": {
                        "label":       {"type": "string"},
                        "datum_type":  {"type": "string"},
                        "feature_ref": {"type": "string"},
                        "is_compound": {"type": "boolean"},
                    },
                    "required": ["label"],
                },
            },
            "tolerances": {
                "type": "array",
                "description": "List of tolerance dicts (from gdt_apply_tolerance output.tolerance).",
                "items": {"type": "object"},
            },
        },
        "required": ["tolerances"],
    },
)


@register(_validate_scheme_spec, write=False)
async def run_gdt_validate_scheme(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    datums = a.get("datums") or []
    tolerances = a.get("tolerances")
    if tolerances is None:
        return err_payload("tolerances is required", "BAD_ARGS")
    if not isinstance(tolerances, list):
        return err_payload("tolerances must be an array", "BAD_ARGS")

    result = _validate_scheme(datums, tolerances)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: gdt_callout_report
# ---------------------------------------------------------------------------

_callout_report_spec = ToolSpec(
    name="gdt_callout_report",
    description=(
        "Render a GD&T callout report from a list of tolerance dicts. "
        "Produces a formatted text feature control frame listing suitable for "
        "review, drawing notes, or inspection sign-off.\n"
        "\n"
        "Output format per line:\n"
        "  [symbol | [⌀]value [modifiers...] | datum1 | datum2 | ...]  ← feature_name\n"
        "\n"
        "Example:\n"
        "  [⊕ | ⌀0.05 (M) | A | B | C]  ← bore-top\n"
        "\n"
        "Returns {callouts, summary, count, by_category, text}.\n"
        "Pass tolerance dicts from gdt_apply_tolerance or gdt_validate_scheme."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "features": {
                "type": "array",
                "description": "List of tolerance dicts (GeometricTolerance serialised).",
                "items": {"type": "object"},
            },
        },
        "required": ["features"],
    },
)


@register(_callout_report_spec, write=False)
async def run_gdt_callout_report(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    features = a.get("features")
    if features is None:
        return err_payload("features is required", "BAD_ARGS")
    if not isinstance(features, list):
        return err_payload("features must be an array", "BAD_ARGS")

    try:
        report = _build_report(features)
    except Exception as exc:
        return err_payload(f"report error: {exc}", "ERROR")

    return ok_payload(report)
