"""
LLM tool wrappers for the diff-pair serpentine length tuner.

Wave 12D: KiCad v10 diff-pair length tuner
------------------------------------------
Tools registered:
  electronics_tune_trace_to_length    — single-trace serpentine insertion
  electronics_tune_diff_pair_lengths  — symmetric diff-pair length matching

References
----------
- Hall & Heck (2009). *Advanced Signal Integrity for High-Speed Digital Designs*.
  Wiley. §3.6 differential-pair length matching.
- IPC-2141A §6 (2004). Differential Pair Routing.
- Wittwer, D. (2012). *Interactive Length Tuning in PCB Routing*. DesignCon 2012.
- KiCad PNS Router documentation: Length-Tuning chapter.

HONEST CAVEAT: One-shot batch tuner.  KiCad's interactive tuner does live-drag
real-time grow/shrink.  This module computes the final geometry offline in a
single pass.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.routing.diffpair_tuner import (
    MeanderSpec,
    tune_trace_to_length,
    tune_diff_pair_lengths,
)


# ─── electronics_tune_trace_to_length ─────────────────────────────────────────

_TUNE_TRACE_SPEC = ToolSpec(
    name="electronics_tune_trace_to_length",
    description=(
        "Insert serpentine meanders into a PCB trace polyline to reach a target "
        "length.  Supports rectangular, arc-cornered, and 45°-chamfered patterns. "
        "Returns the tuned polyline, meander count, actual tuned length, and "
        "residual error.  HONEST: single-pass greedy placement; not KiCad PNS "
        "live-drag equivalent."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "Trace polyline as [[x_mm, y_mm], …].",
                "minItems": 2,
            },
            "target_length_mm": {
                "type": "number",
                "description": "Desired total trace length in mm after meander insertion.",
            },
            "pattern": {
                "type": "string",
                "enum": ["rectangular", "arc", "chamfered_45"],
                "description": "Meander corner style.  'arc' (default) is best for SI.",
                "default": "arc",
            },
            "segment_length_mm": {
                "type": "number",
                "description": "Arm length of each U-turn (mm).  Default 0.5 mm.",
                "default": 0.5,
            },
            "spacing_mm": {
                "type": "number",
                "description": "Gap between adjacent meander bodies (mm).  Default 0.3 mm.",
                "default": 0.3,
            },
            "corner_radius_mm": {
                "type": "number",
                "description": "Arc corner radius (mm); only used for pattern='arc'.  Default 0.15 mm.",
                "default": 0.15,
            },
            "insertion_region": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
                "description": "Optional bounding box [x_min, y_min, x_max, y_max] mm.  Meanders placed only in this area (IPC-2141A §6.3: avoid connector pads).",
            },
        },
        "required": ["path", "target_length_mm"],
    },
)


@register(_TUNE_TRACE_SPEC, write=False)
async def electronics_tune_trace_to_length(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

    raw_path = d.get("path")
    target = d.get("target_length_mm")

    if not raw_path or len(raw_path) < 2:
        return err_payload("path must have ≥ 2 points", "BAD_ARGS")
    if target is None:
        return err_payload("target_length_mm is required", "BAD_ARGS")

    try:
        path = [tuple(float(c) for c in pt) for pt in raw_path]
    except Exception as exc:
        return err_payload(f"path parse error: {exc}", "BAD_ARGS")

    spec = MeanderSpec(
        pattern=d.get("pattern", "arc"),
        segment_length_mm=float(d.get("segment_length_mm", 0.5)),
        spacing_mm=float(d.get("spacing_mm", 0.3)),
        corner_radius_mm=float(d.get("corner_radius_mm", 0.15)),
    )

    if spec.pattern not in ("rectangular", "arc", "chamfered_45"):
        return err_payload(
            "pattern must be 'rectangular', 'arc', or 'chamfered_45'", "BAD_ARGS"
        )

    insertion_region = None
    if "insertion_region" in d and d["insertion_region"]:
        try:
            insertion_region = tuple(float(v) for v in d["insertion_region"])
        except Exception as exc:
            return err_payload(f"insertion_region parse error: {exc}", "BAD_ARGS")

    result = tune_trace_to_length(path, float(target), spec, insertion_region)

    return ok_payload({
        "base_path": result.base_path,
        "tuned_path": result.tuned_path,
        "inserted_meander_count": result.inserted_meander_count,
        "base_length_mm": round(result.base_length_mm, 6),
        "tuned_length_mm": round(result.tuned_length_mm, 6),
        "target_length_mm": result.target_length_mm,
        "delta_length_mm": round(result.delta_length_mm, 6),
        "error_pct": round(result.error_pct, 4),
        "warnings": result.warnings,
        "honest_caveat": (
            "One-shot greedy tuner (Wittwer 2012). Not equivalent to KiCad PNS "
            "interactive live-drag tuning."
        ),
    })


# ─── electronics_tune_diff_pair_lengths ───────────────────────────────────────

_TUNE_DIFFPAIR_SPEC = ToolSpec(
    name="electronics_tune_diff_pair_lengths",
    description=(
        "Tune both conductors of a PCB differential pair to match each other "
        "within skew_tolerance_mm.  Inserts serpentine meanders symmetrically "
        "on the shorter trace.  Returns tuned polylines, skew, and compliance "
        "status.  Reference: Hall & Heck 2009 §3.6; IPC-2141A §6."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path_a": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "P-conductor polyline [[x_mm, y_mm], …].",
                "minItems": 2,
            },
            "path_b": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "N-conductor polyline [[x_mm, y_mm], …].",
                "minItems": 2,
            },
            "target_length_mm": {
                "type": "number",
                "description": "Desired total length for both conductors (mm).",
            },
            "skew_tolerance_mm": {
                "type": "number",
                "description": "Maximum allowed |L_a − L_b| (mm).  Default 0.025 mm ≈ 1 mil.",
                "default": 0.025,
            },
            "pattern": {
                "type": "string",
                "enum": ["rectangular", "arc", "chamfered_45"],
                "default": "arc",
            },
            "segment_length_mm": {"type": "number", "default": 0.5},
            "spacing_mm": {"type": "number", "default": 0.3},
            "corner_radius_mm": {"type": "number", "default": 0.15},
        },
        "required": ["path_a", "path_b", "target_length_mm"],
    },
)


@register(_TUNE_DIFFPAIR_SPEC, write=False)
async def electronics_tune_diff_pair_lengths(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

    raw_a = d.get("path_a")
    raw_b = d.get("path_b")
    target = d.get("target_length_mm")

    if not raw_a or len(raw_a) < 2:
        return err_payload("path_a must have ≥ 2 points", "BAD_ARGS")
    if not raw_b or len(raw_b) < 2:
        return err_payload("path_b must have ≥ 2 points", "BAD_ARGS")
    if target is None:
        return err_payload("target_length_mm is required", "BAD_ARGS")

    try:
        path_a = [tuple(float(c) for c in pt) for pt in raw_a]
        path_b = [tuple(float(c) for c in pt) for pt in raw_b]
    except Exception as exc:
        return err_payload(f"path parse error: {exc}", "BAD_ARGS")

    spec = MeanderSpec(
        pattern=d.get("pattern", "arc"),
        segment_length_mm=float(d.get("segment_length_mm", 0.5)),
        spacing_mm=float(d.get("spacing_mm", 0.3)),
        corner_radius_mm=float(d.get("corner_radius_mm", 0.15)),
    )

    skew_tol = float(d.get("skew_tolerance_mm", 0.025))

    result = tune_diff_pair_lengths(path_a, path_b, float(target), skew_tol, spec)

    return ok_payload({
        "path_a_tuned": result.a_result.tuned_path,
        "path_b_tuned": result.b_result.tuned_path,
        "length_a_mm": round(result.a_result.tuned_length_mm, 6),
        "length_b_mm": round(result.b_result.tuned_length_mm, 6),
        "meanders_a": result.a_result.inserted_meander_count,
        "meanders_b": result.b_result.inserted_meander_count,
        "skew_mm": round(result.skew_mm, 6),
        "intra_pair_gap_mm": round(result.intra_pair_gap_mm, 6),
        "is_skew_within_tolerance": result.is_skew_within_tolerance,
        "is_coupling_maintained": result.is_coupling_maintained,
        "warnings_a": result.a_result.warnings,
        "warnings_b": result.b_result.warnings,
        "honest_caveat": (
            "One-shot symmetric tuner. Hall & Heck 2009 §3.6 + IPC-2141A §6. "
            "Not KiCad PNS live-drag equivalent. Skew reported honestly — "
            "no silent clamping."
        ),
        "references": [
            "Hall & Heck (2009). Advanced Signal Integrity for High-Speed Designs. Wiley §3.6",
            "IPC-2141A §6 (2004). Differential Pair Routing.",
            "Wittwer (2012). Interactive Length Tuning in PCB Routing. DesignCon.",
        ],
    })


# ─── TOOLS export ─────────────────────────────────────────────────────────────

TOOLS = [
    (
        _TUNE_TRACE_SPEC.name,
        _TUNE_TRACE_SPEC,
        electronics_tune_trace_to_length,
    ),
    (
        _TUNE_DIFFPAIR_SPEC.name,
        _TUNE_DIFFPAIR_SPEC,
        electronics_tune_diff_pair_lengths,
    ),
]
