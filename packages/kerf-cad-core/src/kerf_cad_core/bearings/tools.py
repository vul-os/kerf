"""
kerf_cad_core.bearings.tools — LLM tool wrappers for bearing selection & life.

Registers eight tools with the Kerf tool registry:

  bearing_equivalent_load — P = X·Fr + Y·Fa with e-ratio table (ISO 281)
  bearing_rating_life     — L10 = (C/P)^p basic rating life
  bearing_adjusted_life   — Lna = a1 × a23 × L10 with speed → hours
  bearing_static_safety   — s0 = C0/P0 static safety factor (ISO 76)
  bearing_required_capacity — required C for a target life
  bearing_limiting_speed  — n·dm speed parameter check
  bearing_grease_interval — grease relubrication interval estimate
  bearing_select          — select from built-in series table

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ISO 281:2007 — Rolling bearings — Dynamic load ratings and rating life
ISO 76:2006  — Static load ratings
SKF Bearing Catalogue, 2018 edition
Shigley's Mechanical Engineering Design, 10th ed., Ch. 11

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.bearings.select import (
    bearing_equivalent_load,
    bearing_rating_life,
    bearing_adjusted_life,
    bearing_static_safety,
    bearing_required_capacity,
    bearing_limiting_speed,
    bearing_grease_interval,
    bearing_select,
)


# ---------------------------------------------------------------------------
# Tool: bearing_equivalent_load
# ---------------------------------------------------------------------------

_bearing_equiv_load_spec = ToolSpec(
    name="bearing_equivalent_load",
    description=(
        "Compute the equivalent dynamic bearing load P = X·Fr + Y·Fa per ISO 281.\n"
        "\n"
        "For deep-groove ball bearings (bearing_type='ball'), X and Y are\n"
        "interpolated from the ISO 281 Table 4 e-ratio table based on Fa/C0.\n"
        "  if Fa/Fr <= e → P = 1·Fr + 0·Fa  (radial load governs)\n"
        "  else          → P = X·Fr + Y·Fa  (axial load significant)\n"
        "\n"
        "For roller bearings (cylindrical NU/N series) axial load is ignored:\n"
        "  P = Fr.\n"
        "\n"
        "Returns P_N, X, Y, e, and any warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Fr": {
                "type": "number",
                "description": "Radial force (N). Must be >= 0.",
            },
            "Fa": {
                "type": "number",
                "description": "Axial force (N). Must be >= 0.",
            },
            "bearing_type": {
                "type": "string",
                "enum": ["ball", "angular-contact", "roller"],
                "description": (
                    "Bearing type: 'ball' (deep-groove, default), "
                    "'angular-contact' (25° contact angle), 'roller' (cylindrical)."
                ),
            },
            "C0": {
                "type": "number",
                "description": (
                    "Basic static load rating (N). Used for Fa/C0 ratio in the "
                    "ISO 281 Table 4 interpolation for ball bearings. "
                    "If omitted, conservative defaults are applied."
                ),
            },
        },
        "required": ["Fr", "Fa"],
    },
)


@register(_bearing_equiv_load_spec, write=False)
async def run_bearing_equivalent_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("Fr") is None:
        return json.dumps({"ok": False, "reason": "Fr is required"})
    if a.get("Fa") is None:
        return json.dumps({"ok": False, "reason": "Fa is required"})

    kwargs: dict = {}
    if "bearing_type" in a:
        kwargs["bearing_type"] = a["bearing_type"]
    if "C0" in a:
        kwargs["C0"] = a["C0"]

    result = bearing_equivalent_load(a["Fr"], a["Fa"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bearing_rating_life
# ---------------------------------------------------------------------------

_bearing_rating_life_spec = ToolSpec(
    name="bearing_rating_life",
    description=(
        "Compute the ISO 281 basic rating life L10 for a rolling bearing.\n"
        "\n"
        "L10 is the life exceeded by 90% of a batch of identical bearings.\n"
        "\n"
        "  ball bearing:   L10 = (C/P)³        [10⁶ rev]\n"
        "  roller bearing: L10 = (C/P)^(10/3)  [10⁶ rev]\n"
        "\n"
        "If n_rpm is supplied, L10_hours is also returned.\n"
        "\n"
        "Returns L10_rev, optionally L10_hours, C_over_P ratio, and warnings.\n"
        "Warns if C/P < 1.0 (under-capacity).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {
                "type": "number",
                "description": (
                    "Basic dynamic load rating (N). From bearing data sheet. "
                    "Must be > 0."
                ),
            },
            "P": {
                "type": "number",
                "description": (
                    "Equivalent dynamic bearing load (N). "
                    "Use bearing_equivalent_load tool to compute. Must be > 0."
                ),
            },
            "bearing_type": {
                "type": "string",
                "enum": ["ball", "roller"],
                "description": "Bearing type: 'ball' (p=3, default) or 'roller' (p=10/3).",
            },
            "n_rpm": {
                "type": "number",
                "description": (
                    "Operating speed (rpm). When provided, L10_hours is returned. "
                    "Must be > 0 if supplied."
                ),
            },
        },
        "required": ["C", "P"],
    },
)


@register(_bearing_rating_life_spec, write=False)
async def run_bearing_rating_life(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("C") is None:
        return json.dumps({"ok": False, "reason": "C is required"})
    if a.get("P") is None:
        return json.dumps({"ok": False, "reason": "P is required"})

    kwargs: dict = {}
    if "bearing_type" in a:
        kwargs["bearing_type"] = a["bearing_type"]
    if "n_rpm" in a:
        kwargs["n_rpm"] = a["n_rpm"]

    result = bearing_rating_life(a["C"], a["P"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bearing_adjusted_life
# ---------------------------------------------------------------------------

_bearing_adjusted_life_spec = ToolSpec(
    name="bearing_adjusted_life",
    description=(
        "Compute the ISO 281 adjusted (modified) rating life.\n"
        "\n"
        "  Lna = a1 × a23 × L10          [10⁶ rev]\n"
        "  Lna_hours = Lna × 10⁶ / (60·n)\n"
        "\n"
        "a1 — reliability factor:\n"
        "  1.00 → 90% reliability (standard L10)\n"
        "  0.62 → 95% reliability (L5)\n"
        "  0.44 → 97% reliability (L3)\n"
        "  0.21 → 99% reliability (L1)\n"
        "\n"
        "a23 — combined lubrication + contamination factor; typical 0.5–3.0.\n"
        "      Default 1.0 (ISO 281 simplified method, neutral).\n"
        "\n"
        "Returns L10_rev, Lna_rev, L10_hours, Lna_hours, and warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {
                "type": "number",
                "description": "Basic dynamic load rating (N). Must be > 0.",
            },
            "P": {
                "type": "number",
                "description": "Equivalent dynamic bearing load (N). Must be > 0.",
            },
            "n_rpm": {
                "type": "number",
                "description": "Operating speed (rpm). Must be > 0.",
            },
            "bearing_type": {
                "type": "string",
                "enum": ["ball", "roller"],
                "description": "Bearing type: 'ball' (default) or 'roller'.",
            },
            "a1": {
                "type": "number",
                "description": (
                    "Reliability factor per ISO 281 Table 1. "
                    "1.00=90% (default), 0.62=95%, 0.44=97%, 0.21=99%."
                ),
            },
            "a23": {
                "type": "number",
                "description": (
                    "Lubrication / contamination / material factor. "
                    "Default 1.0. Values > 1 improve life; < 1 reduce life."
                ),
            },
        },
        "required": ["C", "P", "n_rpm"],
    },
)


@register(_bearing_adjusted_life_spec, write=False)
async def run_bearing_adjusted_life(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C", "P", "n_rpm"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "bearing_type" in a:
        kwargs["bearing_type"] = a["bearing_type"]
    if "a1" in a:
        kwargs["a1"] = a["a1"]
    if "a23" in a:
        kwargs["a23"] = a["a23"]

    result = bearing_adjusted_life(a["C"], a["P"], a["n_rpm"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bearing_static_safety
# ---------------------------------------------------------------------------

_bearing_static_safety_spec = ToolSpec(
    name="bearing_static_safety",
    description=(
        "Compute the static safety factor s0 = C0 / P0 per ISO 76.\n"
        "\n"
        "Minimum recommended s0 values (SKF):\n"
        "  s0 >= 0.8 — smooth vibration-free conditions\n"
        "  s0 >= 1.0 — normal conditions\n"
        "  s0 >= 1.5 — moderate shock / vibration\n"
        "  s0 >= 2.0 — heavy shock\n"
        "\n"
        "Returns s0 and warning flags for under-safety conditions.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C0": {
                "type": "number",
                "description": "Basic static load rating (N). Must be > 0.",
            },
            "P0": {
                "type": "number",
                "description": (
                    "Equivalent static load (N). "
                    "For ball: P0 = 0.6·Fr + 0.5·Fa; use max(P0, Fr). "
                    "Must be > 0."
                ),
            },
        },
        "required": ["C0", "P0"],
    },
)


@register(_bearing_static_safety_spec, write=False)
async def run_bearing_static_safety(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("C0") is None:
        return json.dumps({"ok": False, "reason": "C0 is required"})
    if a.get("P0") is None:
        return json.dumps({"ok": False, "reason": "P0 is required"})

    result = bearing_static_safety(a["C0"], a["P0"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bearing_required_capacity
# ---------------------------------------------------------------------------

_bearing_required_capacity_spec = ToolSpec(
    name="bearing_required_capacity",
    description=(
        "Compute the required basic dynamic load rating C for a target life.\n"
        "\n"
        "Inverts the adjusted-life equation:\n"
        "  C = P × (Lh_target × 60 × n / (a1 × a23 × 10⁶))^(1/p)\n"
        "\n"
        "Use this to find the minimum C when selecting a bearing from a catalogue.\n"
        "\n"
        "Returns C_required_N (N).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "P": {
                "type": "number",
                "description": "Equivalent dynamic bearing load (N). Must be > 0.",
            },
            "n_rpm": {
                "type": "number",
                "description": "Operating speed (rpm). Must be > 0.",
            },
            "Lh_target": {
                "type": "number",
                "description": "Target adjusted rating life (hours). Must be > 0.",
            },
            "bearing_type": {
                "type": "string",
                "enum": ["ball", "roller"],
                "description": "Bearing type: 'ball' (default) or 'roller'.",
            },
            "a1": {
                "type": "number",
                "description": "Reliability factor (default 1.0 = L10 = 90%).",
            },
            "a23": {
                "type": "number",
                "description": "Lubrication / material factor (default 1.0).",
            },
        },
        "required": ["P", "n_rpm", "Lh_target"],
    },
)


@register(_bearing_required_capacity_spec, write=False)
async def run_bearing_required_capacity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("P", "n_rpm", "Lh_target"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "bearing_type" in a:
        kwargs["bearing_type"] = a["bearing_type"]
    if "a1" in a:
        kwargs["a1"] = a["a1"]
    if "a23" in a:
        kwargs["a23"] = a["a23"]

    result = bearing_required_capacity(a["P"], a["n_rpm"], a["Lh_target"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bearing_limiting_speed
# ---------------------------------------------------------------------------

_bearing_limiting_speed_spec = ToolSpec(
    name="bearing_limiting_speed",
    description=(
        "Evaluate the n·dm speed parameter (mm·rpm) against catalogue limits.\n"
        "\n"
        "SKF grease-lubrication limits:\n"
        "  deep-groove ball bearing: 600 000 mm·rpm\n"
        "  cylindrical roller:       300 000 mm·rpm\n"
        "\n"
        "dm_mm = (bore + OD) / 2  (pitch diameter in mm).\n"
        "\n"
        "Returns ndm, ndm_limit, utilisation fraction, and over-speed warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dm_mm": {
                "type": "number",
                "description": "Pitch diameter (bore + OD) / 2 in mm. Must be > 0.",
            },
            "n_rpm": {
                "type": "number",
                "description": "Operating speed (rpm). Must be > 0.",
            },
            "bearing_type": {
                "type": "string",
                "enum": ["ball", "roller"],
                "description": "Bearing type: 'ball' (default) or 'roller'.",
            },
        },
        "required": ["dm_mm", "n_rpm"],
    },
)


@register(_bearing_limiting_speed_spec, write=False)
async def run_bearing_limiting_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("dm_mm") is None:
        return json.dumps({"ok": False, "reason": "dm_mm is required"})
    if a.get("n_rpm") is None:
        return json.dumps({"ok": False, "reason": "n_rpm is required"})

    kwargs: dict = {}
    if "bearing_type" in a:
        kwargs["bearing_type"] = a["bearing_type"]

    result = bearing_limiting_speed(a["dm_mm"], a["n_rpm"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bearing_grease_interval
# ---------------------------------------------------------------------------

_bearing_grease_interval_spec = ToolSpec(
    name="bearing_grease_interval",
    description=(
        "Estimate the grease relubrication interval in hours (SKF handbook method).\n"
        "\n"
        "  tf = K × (14×10⁶ / (n × √dm) − 4×dm)   [hours, base formula]\n"
        "\n"
        "A load correction factor (C/P)^0.3 is applied; higher C/P gives a\n"
        "longer relubrication interval.\n"
        "\n"
        "Applicable when n·√dm < 14×10⁶; otherwise continuous oil lubrication\n"
        "is recommended (returns 0 hours with a warning).\n"
        "\n"
        "Load inputs C_kN and P_kN are in kilonewtons (SKF formula convention).\n"
        "\n"
        "Returns relubrication_hours and warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dm_mm": {
                "type": "number",
                "description": "Pitch diameter (mm). Must be > 0.",
            },
            "n_rpm": {
                "type": "number",
                "description": "Operating speed (rpm). Must be > 0.",
            },
            "C_kN": {
                "type": "number",
                "description": "Basic dynamic load rating (kN). Must be > 0.",
            },
            "P_kN": {
                "type": "number",
                "description": "Equivalent dynamic load (kN). Must be > 0.",
            },
        },
        "required": ["dm_mm", "n_rpm", "C_kN", "P_kN"],
    },
)


@register(_bearing_grease_interval_spec, write=False)
async def run_bearing_grease_interval(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("dm_mm", "n_rpm", "C_kN", "P_kN"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = bearing_grease_interval(a["dm_mm"], a["n_rpm"], a["C_kN"], a["P_kN"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bearing_select
# ---------------------------------------------------------------------------

_bearing_select_spec = ToolSpec(
    name="bearing_select",
    description=(
        "Select the lightest bearing from a built-in series table that meets\n"
        "the target adjusted life and static safety requirements.\n"
        "\n"
        "Available series:\n"
        "  '6000' — SKF 6000 deep-groove ball (bore 10–50 mm)\n"
        "  '6200' — SKF 6200 deep-groove ball (bore 10–50 mm)\n"
        "  '6300' — SKF 6300 deep-groove ball (bore 10–50 mm)\n"
        "  'NU200' — SKF NU 200 cylindrical roller (bore 15–70 mm)\n"
        "\n"
        "Returns the selected bearing data dict (or null if none qualifies),\n"
        "plus a list of all candidates with their computed adjusted life.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "series": {
                "type": "string",
                "enum": ["6000", "6200", "6300", "NU200"],
                "description": "Bearing series to search.",
            },
            "Fr": {
                "type": "number",
                "description": "Radial force (N). Must be >= 0.",
            },
            "Fa": {
                "type": "number",
                "description": "Axial force (N). Must be >= 0.",
            },
            "n_rpm": {
                "type": "number",
                "description": "Operating speed (rpm). Must be > 0.",
            },
            "Lh_min": {
                "type": "number",
                "description": "Minimum required adjusted life (hours). Must be > 0.",
            },
            "bearing_type": {
                "type": "string",
                "enum": ["ball", "roller"],
                "description": "Bearing type: 'ball' (default) or 'roller'.",
            },
            "a1": {
                "type": "number",
                "description": "Reliability factor (default 1.0 = L10).",
            },
            "a23": {
                "type": "number",
                "description": "Lubrication / material factor (default 1.0).",
            },
            "s0_min": {
                "type": "number",
                "description": "Minimum required static safety factor (default 1.0).",
            },
        },
        "required": ["series", "Fr", "Fa", "n_rpm", "Lh_min"],
    },
)


@register(_bearing_select_spec, write=False)
async def run_bearing_select(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("series", "Fr", "Fa", "n_rpm", "Lh_min"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "bearing_type" in a:
        kwargs["bearing_type"] = a["bearing_type"]
    if "a1" in a:
        kwargs["a1"] = a["a1"]
    if "a23" in a:
        kwargs["a23"] = a["a23"]
    if "s0_min" in a:
        kwargs["s0_min"] = a["s0_min"]

    result = bearing_select(
        a["series"], a["Fr"], a["Fa"], a["n_rpm"], a["Lh_min"], **kwargs
    )
    return ok_payload(result)
