"""
kerf_cad_core.gdt_callouts.tools — LLM tool wrappers for GD&T auto-callout.

Registers two tools with the Kerf tool registry:

  gdt_auto_callouts
      Given a list of classified model features (holes, slots, planar faces,
      cylinders, patterns, freeform surfaces) + a datum set + an IT grade,
      auto-propose GD&T feature control frames.  Returns proposed callouts
      with IT-grade tolerance values and a rationale for each.

  gdt_callout_balloon_table
      Format a set of proposed callouts as a numbered balloon table suitable
      for drawing annotations.  Returns a text table and a list of balloon
      entries (balloon number, feature id, callout string).

Both tools return {ok: false, reason: ...} on bad input — never raise.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.gdt.tolerances import ToleranceSymbol
from kerf_cad_core.gdt_callouts.propose import (
    propose_callouts,
    it_grade_tolerance,
    VALID_GRADES,
    VALID_FEATURE_TYPES,
    VALID_INTENTS,
)
from kerf_cad_core.gdt.report import gdt_callout_report as _build_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYMBOL_CHARS: dict[str, str] = {
    "FLATNESS":          "⏥",
    "STRAIGHTNESS":      "⏤",
    "CIRCULARITY":       "○",
    "CYLINDRICITY":      "⌭",
    "PROFILE_LINE":      "⌒",
    "PROFILE_SURFACE":   "⌓",
    "PARALLELISM":       "∥",
    "PERPENDICULARITY":  "⊥",
    "ANGULARITY":        "∠",
    "POSITION":          "⊕",
    "CONCENTRICITY":     "◎",
    "SYMMETRY":          "≡",
    "RUNOUT":            "↗",
    "TOTAL_RUNOUT":      "⟿",
}


def _callout_line(tol_dict: dict) -> str:
    """Format a single tolerance dict as a feature-control-frame text line."""
    sym = tol_dict.get("symbol", "?")
    char = _SYMBOL_CHARS.get(sym, sym)
    val = tol_dict.get("tolerance_value", 0)
    prefix = "⌀" if tol_dict.get("diameter_zone") else ""
    mods = tol_dict.get("modifiers") or []
    mod_str = (" " + " ".join(f"({m[0]})" for m in mods)) if mods else ""
    datum_ref = tol_dict.get("datum_ref") or {}
    datum_parts = [
        v for v in [
            datum_ref.get("primary"),
            datum_ref.get("secondary"),
            datum_ref.get("tertiary"),
        ]
        if v
    ]
    compartments = [char, f"{prefix}{val:.4g}{mod_str}"] + datum_parts
    frame = " | ".join(compartments)
    feature = tol_dict.get("feature_name", "?")
    return f"[{frame}]  ← {feature}"


# ---------------------------------------------------------------------------
# Tool: gdt_auto_callouts
# ---------------------------------------------------------------------------

_auto_callouts_spec = ToolSpec(
    name="gdt_auto_callouts",
    description=(
        "Auto-propose GD&T callouts (feature control frames) for a list of "
        "classified model features, following ASME Y14.5 / ISO 1101 rules.\n"
        "\n"
        "Feature types and their proposed callout:\n"
        "  hole        → POSITION (⊕), cylindrical zone, about primary datum\n"
        "  slot        → POSITION, centre-plane zone, about primary datum\n"
        "  planar_face → PERPENDICULARITY (⊥) or PARALLELISM (∥) to orientation "
        "datum; FLATNESS if no datum\n"
        "  cylindrical → RUNOUT (↗) about axis datum; CYLINDRICITY if no datum\n"
        "  pattern     → composite POSITION (⊕) with inter-feature segment\n"
        "  freeform    → PROFILE_SURFACE (⌓) to primary datum; all-around if "
        "none\n"
        "\n"
        "Tolerance magnitudes follow ISO 286-1 IT grades (IT01–IT18).  "
        "Default grade: IT7.  Intent shifts the grade: 'loose' → 2 coarser, "
        "'tight' → 1 finer, 'precise' → 2 finer.\n"
        "\n"
        "feature fields:\n"
        "  feature_id         (required) — feature name or id\n"
        "  feature_type       (required) — hole|slot|planar_face|cylindrical"
        "|pattern|freeform\n"
        "  nominal_size_mm    — characteristic dimension in mm (diameter, width,"
        " etc.)\n"
        "  primary_datum      — position reference datum label (required for "
        "hole/slot/pattern)\n"
        "  secondary_datum    — secondary datum label\n"
        "  tertiary_datum     — tertiary datum label\n"
        "  orientation_datum  — datum for PERPENDICULARITY/PARALLELISM "
        "(planar_face)\n"
        "  axis_datum         — axis datum label for RUNOUT (cylindrical)\n"
        "  pattern_count      — number of instances (pattern)\n"
        "  extra.face_orientation — 'parallel' to get PARALLELISM instead of "
        "PERPENDICULARITY\n"
        "\n"
        "datum fields (from gdt_apply_datum):\n"
        "  label, datum_type (PLANE|AXIS|CENTRE_PLANE|POINT|LINE), feature_ref\n"
        "\n"
        "Returns {ok, callouts, warnings, count, grade_used}.  "
        "On bad input: {ok:false, reason}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "features": {
                "type": "array",
                "description": "List of feature spec dicts.",
                "items": {
                    "type": "object",
                    "properties": {
                        "feature_id":        {"type": "string"},
                        "feature_type":      {
                            "type": "string",
                            "enum": sorted(VALID_FEATURE_TYPES),
                        },
                        "nominal_size_mm":   {"type": "number"},
                        "primary_datum":     {"type": "string"},
                        "secondary_datum":   {"type": "string"},
                        "tertiary_datum":    {"type": "string"},
                        "orientation_datum": {"type": "string"},
                        "axis_datum":        {"type": "string"},
                        "pattern_count":     {"type": "integer"},
                        "extra":             {"type": "object"},
                    },
                    "required": ["feature_id", "feature_type"],
                },
            },
            "datums": {
                "type": "array",
                "description": (
                    "Datum dicts (from gdt_apply_datum) that define the "
                    "reference frame.  Used to validate datum types."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "label":      {"type": "string"},
                        "datum_type": {
                            "type": "string",
                            "enum": ["PLANE", "AXIS", "CENTRE_PLANE", "POINT", "LINE"],
                        },
                        "feature_ref": {"type": "string"},
                    },
                    "required": ["label"],
                },
            },
            "grade": {
                "type": "string",
                "enum": sorted(VALID_GRADES),
                "description": (
                    "IT grade for tolerance magnitudes (ISO 286-1).  "
                    "Default 'IT7'.  Fine precision: IT5/IT6; general: "
                    "IT7/IT8; loose: IT11/IT12."
                ),
            },
            "intent": {
                "type": "string",
                "enum": sorted(VALID_INTENTS),
                "description": (
                    "Tolerancing intent: 'nominal' (default), 'loose' (+2 IT grades), "
                    "'tight' (-1 IT grade), 'precise' (-2 IT grades)."
                ),
            },
        },
        "required": ["features"],
    },
)


@register(_auto_callouts_spec, write=False)
async def run_gdt_auto_callouts(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    features = a.get("features")
    if features is None:
        return err_payload("features is required", "BAD_ARGS")
    if not isinstance(features, list):
        return err_payload("features must be an array", "BAD_ARGS")

    datums = a.get("datums") or []
    grade = str(a.get("grade") or "IT7").upper()
    intent = str(a.get("intent") or "nominal").lower()

    result = propose_callouts(
        features=features,
        datums=datums,
        grade=grade,
        intent=intent,
    )

    if not result.get("ok"):
        return err_payload(result.get("reason", "proposal failed"), "BAD_ARGS")

    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: gdt_callout_balloon_table
# ---------------------------------------------------------------------------

_balloon_table_spec = ToolSpec(
    name="gdt_callout_balloon_table",
    description=(
        "Format a list of proposed GD&T callouts (from gdt_auto_callouts) as "
        "a numbered balloon table for drawing annotations.\n"
        "\n"
        "Each callout receives a sequential balloon number.  The output "
        "includes a text table and a machine-readable list of balloon entries.\n"
        "\n"
        "Input: the 'callouts' list from gdt_auto_callouts output.\n"
        "\n"
        "Returns {ok, balloons, text, count}.\n"
        "  balloons — [{balloon, feature_id, callout_string, rationale}]\n"
        "  text     — formatted table string\n"
        "  count    — number of balloons\n"
        "\n"
        "On bad input: {ok:false, reason}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "callouts": {
                "type": "array",
                "description": (
                    "List of proposed callout dicts from gdt_auto_callouts "
                    "output.callouts."
                ),
                "items": {"type": "object"},
            },
            "title": {
                "type": "string",
                "description": "Optional drawing title for the header.",
            },
        },
        "required": ["callouts"],
    },
)


@register(_balloon_table_spec, write=False)
async def run_gdt_callout_balloon_table(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    callouts = a.get("callouts")
    if callouts is None:
        return err_payload("callouts is required", "BAD_ARGS")
    if not isinstance(callouts, list):
        return err_payload("callouts must be an array", "BAD_ARGS")

    title = str(a.get("title") or "GD&T Callout Balloon Table")

    balloons: list[dict] = []
    lines: list[str] = [title, "=" * len(title), ""]
    lines.append(f"{'#':<4}  {'Feature':<30}  {'Callout'}")
    lines.append("-" * 72)

    for idx, entry in enumerate(callouts, start=1):
        if not isinstance(entry, dict):
            continue
        tol_dict = entry.get("tolerance") or {}
        feature_id = entry.get("feature_id") or tol_dict.get("feature_name") or "?"
        rationale = entry.get("rationale") or ""
        callout_str = _callout_line(tol_dict)
        lines.append(f"{idx:<4}  {feature_id:<30}  {callout_str}")
        balloons.append({
            "balloon": idx,
            "feature_id": feature_id,
            "callout_string": callout_str,
            "rationale": rationale,
        })

    lines.append("")
    lines.append(f"Total: {len(balloons)} callout(s)")

    return ok_payload({
        "balloons": balloons,
        "text": "\n".join(lines),
        "count": len(balloons),
    })
