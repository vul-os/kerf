"""
kerf_cad_core.shaft.tools — LLM tool wrappers for shaft & bearing sizing.

Registers four tools with the Kerf tool registry:

  shaft_diameter          — required shaft diameter from bending + torsion loads
  shaft_critical_speed    — first lateral whirl critical speed for a uniform shaft
  bearing_l10             — ISO 281 basic L10 bearing rating life
  key_size                — ANSI B17.1 key cross-section + stress checks

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
ASME B106.1M-1985 — Design of Transmission Shafting
ISO 281:2007 — Rolling bearings — Dynamic load ratings and rating life
ANSI B17.1-1967 — Keys and Keyseats

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.shaft.calc import (
    shaft_diameter,
    shaft_critical_speed,
    bearing_l10,
    key_size,
)


# ---------------------------------------------------------------------------
# Tool: shaft_diameter
# ---------------------------------------------------------------------------

_shaft_diameter_spec = ToolSpec(
    name="shaft_diameter",
    description=(
        "Compute the required minimum solid circular shaft diameter from combined "
        "bending and torsion loads.\n"
        "\n"
        "Two methods are supported:\n"
        "  'DE-Goodman' (default) — Distortion-Energy / Goodman criterion per "
        "ASME B106; uses Von Mises equivalent stress; suitable for fatigue-loaded "
        "rotating shafts.  sigma_allow should be the endurance limit Se (Pa).\n"
        "  'max-shear'            — Tresca / maximum-shear-stress criterion; "
        "suitable for static or shock-loaded shafts.\n"
        "\n"
        "Returns diameter_m (metres).  Both M and T may be zero (returns 0.0).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid / negative inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "M": {
                "type": "number",
                "description": "Bending moment (N·m). Must be >= 0.",
            },
            "T": {
                "type": "number",
                "description": "Torsional moment / torque (N·m). Must be >= 0.",
            },
            "sigma_allow": {
                "type": "number",
                "description": (
                    "Allowable normal stress (Pa). "
                    "For DE-Goodman: endurance limit Se. "
                    "For max-shear: allowable bending stress. Must be > 0."
                ),
            },
            "method": {
                "type": "string",
                "enum": ["DE-Goodman", "max-shear"],
                "description": (
                    "Sizing criterion: 'DE-Goodman' (default) or 'max-shear'."
                ),
            },
            "Kf": {
                "type": "number",
                "description": (
                    "Fatigue stress concentration factor for bending (default 1.0)."
                ),
            },
            "Kfs": {
                "type": "number",
                "description": (
                    "Fatigue stress concentration factor for torsion (default 1.0)."
                ),
            },
            "safety_factor": {
                "type": "number",
                "description": (
                    "Additional safety factor on the required diameter (default 1.0)."
                ),
            },
        },
        "required": ["M", "T", "sigma_allow"],
    },
)


@register(_shaft_diameter_spec, write=False)
async def run_shaft_diameter(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    M = a.get("M")
    T = a.get("T")
    sigma_allow = a.get("sigma_allow")

    if M is None:
        return json.dumps({"ok": False, "reason": "M is required"})
    if T is None:
        return json.dumps({"ok": False, "reason": "T is required"})
    if sigma_allow is None:
        return json.dumps({"ok": False, "reason": "sigma_allow is required"})

    kwargs: dict = {}
    if "method" in a:
        kwargs["method"] = a["method"]
    if "Kf" in a:
        kwargs["Kf"] = a["Kf"]
    if "Kfs" in a:
        kwargs["Kfs"] = a["Kfs"]
    if "safety_factor" in a:
        kwargs["safety_factor"] = a["safety_factor"]

    result = shaft_diameter(M, T, sigma_allow, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: shaft_critical_speed
# ---------------------------------------------------------------------------

_shaft_critical_speed_spec = ToolSpec(
    name="shaft_critical_speed",
    description=(
        "Compute the first lateral (whirl) critical speed of a uniform shaft.\n"
        "\n"
        "Uses the Euler-Bernoulli beam equation.  The boundary condition "
        "('simply-supported' or 'fixed-fixed') determines the first eigenvalue "
        "β₁·L used in the formula.\n"
        "\n"
        "Returns omega_rad_s (rad/s) and n_rpm.\n"
        "Operating speed should remain ≤ 75% of n_rpm to avoid resonance.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "length_m": {
                "type": "number",
                "description": "Shaft length (m). Must be > 0.",
            },
            "mass_per_m": {
                "type": "number",
                "description": (
                    "Mass per unit length (kg/m). Must be > 0. "
                    "For solid steel: mass_per_m ≈ 7850 × π/4 × d²."
                ),
            },
            "E": {
                "type": "number",
                "description": (
                    "Young's modulus (Pa). Must be > 0. "
                    "Steel ≈ 200e9 Pa."
                ),
            },
            "I": {
                "type": "number",
                "description": (
                    "Second moment of area (m⁴). Must be > 0. "
                    "Solid circle: π·d⁴/64."
                ),
            },
            "supports": {
                "type": "string",
                "enum": ["simply-supported", "fixed-fixed"],
                "description": (
                    "Boundary condition: 'simply-supported' (default) or 'fixed-fixed'."
                ),
            },
        },
        "required": ["length_m", "mass_per_m", "E", "I"],
    },
)


@register(_shaft_critical_speed_spec, write=False)
async def run_shaft_critical_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("length_m", "mass_per_m", "E", "I"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "supports" in a:
        kwargs["supports"] = a["supports"]

    result = shaft_critical_speed(
        a["length_m"], a["mass_per_m"], a["E"], a["I"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bearing_l10
# ---------------------------------------------------------------------------

_bearing_l10_spec = ToolSpec(
    name="bearing_l10",
    description=(
        "Compute the ISO 281 basic rating life L10 for a rolling bearing.\n"
        "\n"
        "L10 is the life that 90% of a group of identical bearings will achieve "
        "or exceed under identical operating conditions.\n"
        "\n"
        "  ball bearings:   p = 3     → L10 = (C/P)³      [10⁶ rev]\n"
        "  roller bearings: p = 10/3  → L10 = (C/P)^(10/3) [10⁶ rev]\n"
        "\n"
        "Returns L10_rev (10⁶ revolutions) and L10_hours at the given speed.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {
                "type": "number",
                "description": (
                    "Basic dynamic load rating (N). From bearing manufacturer data. "
                    "Must be > 0."
                ),
            },
            "P": {
                "type": "number",
                "description": (
                    "Equivalent dynamic bearing load (N). "
                    "P = X·Fr + Y·Fa per ISO 281. Must be > 0."
                ),
            },
            "n_rpm": {
                "type": "number",
                "description": "Rotational speed (rpm). Must be > 0.",
            },
            "bearing_type": {
                "type": "string",
                "enum": ["ball", "roller"],
                "description": (
                    "Bearing type: 'ball' (p=3, default) or 'roller' (p=10/3)."
                ),
            },
        },
        "required": ["C", "P", "n_rpm"],
    },
)


@register(_bearing_l10_spec, write=False)
async def run_bearing_l10(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C", "P", "n_rpm"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    bt = a.get("bearing_type", "ball")
    result = bearing_l10(a["C"], a["P"], a["n_rpm"], bt)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: key_size
# ---------------------------------------------------------------------------

_key_size_spec = ToolSpec(
    name="key_size",
    description=(
        "Select the standard key cross-section per ANSI B17.1 / DIN 6885 for "
        "a given shaft diameter, and verify shear and bearing stresses.\n"
        "\n"
        "The key cross-section (width × height) is looked up from the standard "
        "table for the shaft diameter (range 6–230 mm).  Then shear stress "
        "(τ = F / (w·L)) and bearing/compressive stress "
        "(σ_c = F / (h/2·L)) are computed from the transmitted torque.\n"
        "\n"
        "Returns key dimensions, computed stresses, allowables, "
        "pass/fail flags, and safety factors.\n"
        "\n"
        "Errors: {ok:false, reason} for out-of-range shaft diameter or "
        "invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shaft_d_mm": {
                "type": "number",
                "description": "Shaft diameter (mm). Valid range: 6–230 mm.",
            },
            "torque_Nm": {
                "type": "number",
                "description": "Transmitted torque (N·m). Must be >= 0.",
            },
            "material": {
                "type": "string",
                "enum": ["steel_1045", "steel_1020", "stainless_304", "cast_iron"],
                "description": (
                    "Key material (default 'steel_1045'): "
                    "steel_1045 τ=170 MPa σ_c=340 MPa, "
                    "steel_1020 τ=120 MPa σ_c=240 MPa, "
                    "stainless_304 τ=115 MPa σ_c=230 MPa, "
                    "cast_iron τ=55 MPa σ_c=110 MPa."
                ),
            },
            "key_length_mm": {
                "type": "number",
                "description": (
                    "Key length (mm). If omitted, defaults to 1.5 × shaft_d_mm."
                ),
            },
        },
        "required": ["shaft_d_mm", "torque_Nm"],
    },
)


@register(_key_size_spec, write=False)
async def run_key_size(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("shaft_d_mm") is None:
        return json.dumps({"ok": False, "reason": "shaft_d_mm is required"})
    if a.get("torque_Nm") is None:
        return json.dumps({"ok": False, "reason": "torque_Nm is required"})

    kwargs: dict = {}
    if "material" in a:
        kwargs["material"] = a["material"]
    if "key_length_mm" in a:
        kwargs["key_length_mm"] = a["key_length_mm"]

    result = key_size(a["shaft_d_mm"], a["torque_Nm"], **kwargs)
    return ok_payload(result)
