"""
Signal-integrity analyzer for PCB nets.

Provides controlled-impedance analysis, propagation delay estimation,
first-order crosstalk (NEXT/FEXT), reflection coefficient, and termination
recommendation for single-ended and differential transmission lines.

This module COMPLEMENTS kerf_electronics.tools.diffpair: diffpair owns
differential-pair routing, routing coupling, and per-pair calc_impedance.
This SI module operates at the stackup/net level and adds:
  - Propagation delay / flight-time estimation
  - First-order crosstalk (NEXT + FEXT) for aggressor/victim pairs
  - Reflection coefficient + termination recommendation from driver + topology
  - Combined per-net SI report

Impedance helpers are imported from kerf_electronics.si.solver (which itself
mirrors the formulas in diffpair.py — IPC-2141A + Wadell 1991).  The SI solver
is the single source of truth for the math; this file is purely the tool layer.

Tools registered (via @register + TOOLS export):
  si_impedance    — microstrip / stripline single-ended + differential Z0
  si_propagation  — propagation delay ps/mm and flight time for a length
  si_crosstalk    — NEXT + FEXT from spacing, height, run length
  si_termination  — reflection Γ + termination scheme recommendation
  si_report       — combined per-net SI summary

Author: imranparuk
"""

from __future__ import annotations

import json
import math
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

# Import the pure-math solver — all formulas live there.
from kerf_electronics.si.solver import (
    microstrip_z0,
    stripline_z0,
    diff_z0,
    propagation_delay_ps_per_mm,
    flight_time_ps,
    crosstalk_next,
    crosstalk_fext,
    reflection_coefficient,
    termination_recommendation,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────────────────────

def _num(val: Any, name: str, required: bool = True, default: float | None = None):
    """Return a validated positive float or None.  On error return an error string."""
    if val is None:
        if required:
            return None, f"{name} is required"
        return default, None
    if not isinstance(val, (int, float)) or val <= 0:
        return None, f"{name} must be a positive number, got {val!r}"
    return float(val), None


# ──────────────────────────────────────────────────────────────────────────────
# 1. si_impedance
# ──────────────────────────────────────────────────────────────────────────────

_SI_IMPEDANCE_SPEC = ToolSpec(
    name="si_impedance",
    description=(
        "Calculate single-ended and differential characteristic impedance Z0 "
        "for a PCB transmission line using standard closed-form approximations. "
        "Supports microstrip (surface trace over ground plane) and stripline "
        "(buried trace between two reference planes). "
        "Returns z0_ohms and, when spacing_mm is supplied, zdiff_ohms. "
        "Formulas: IPC-2141A (2004) for Z0; Wadell (1991) §3.7/4.3 for Zdiff. "
        "Stackup input shape: "
        "{ structure, trace_width_mm, dielectric_height_mm, copper_thickness_mm, er, spacing_mm? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "structure": {
                "type": "string",
                "enum": ["microstrip", "stripline"],
                "description": (
                    "'microstrip' = surface trace above ground plane; "
                    "'stripline' = buried trace between two reference planes."
                ),
            },
            "trace_width_mm": {
                "type": "number",
                "description": "Trace width W [mm].",
            },
            "dielectric_height_mm": {
                "type": "number",
                "description": (
                    "Microstrip: height H of dielectric between trace and ground plane [mm]. "
                    "Stripline: total dielectric thickness B between both reference planes [mm]."
                ),
            },
            "copper_thickness_mm": {
                "type": "number",
                "description": "Copper thickness T [mm] (default: 0.035 = 1 oz copper).",
            },
            "er": {
                "type": "number",
                "description": "Substrate relative permittivity εr (FR4 ≈ 4.3–4.8).",
            },
            "spacing_mm": {
                "type": "number",
                "description": (
                    "Edge-to-edge gap S between the two conductors of a differential pair [mm]. "
                    "When supplied, zdiff_ohms is also returned."
                ),
            },
        },
        "required": ["structure", "trace_width_mm", "dielectric_height_mm", "er"],
    },
)


@register(_SI_IMPEDANCE_SPEC, write=False)
async def si_impedance(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    structure = (a.get("structure") or "").strip()
    if structure not in ("microstrip", "stripline"):
        return err_payload("structure must be 'microstrip' or 'stripline'", "BAD_ARGS")

    W, e = _num(a.get("trace_width_mm"), "trace_width_mm")
    if e:
        return err_payload(e, "BAD_ARGS")
    H_or_B, e = _num(a.get("dielectric_height_mm"), "dielectric_height_mm")
    if e:
        return err_payload(e, "BAD_ARGS")
    er, e = _num(a.get("er"), "er")
    if e:
        return err_payload(e, "BAD_ARGS")
    T, _ = _num(a.get("copper_thickness_mm"), "copper_thickness_mm", required=False, default=0.035)
    S_raw = a.get("spacing_mm")

    try:
        if structure == "microstrip":
            z0 = microstrip_z0(W, H_or_B, T, er)
        else:
            z0 = stripline_z0(W, H_or_B, T, er)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    result: dict = {
        "structure": structure,
        "trace_width_mm": W,
        "dielectric_height_mm": H_or_B,
        "copper_thickness_mm": T,
        "er": er,
        "z0_ohms": round(z0, 2),
        "formulas": "Z0: IPC-2141A (2004); Zdiff: Wadell 1991 §3.7/4.3",
    }

    if isinstance(S_raw, (int, float)) and S_raw > 0:
        S = float(S_raw)
        try:
            zdiff = diff_z0(z0, S, H_or_B, structure)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        result["spacing_mm"] = S
        result["zdiff_ohms"] = round(zdiff, 2)

    return ok_payload(result)


# ──────────────────────────────────────────────────────────────────────────────
# 2. si_propagation
# ──────────────────────────────────────────────────────────────────────────────

_SI_PROPAGATION_SPEC = ToolSpec(
    name="si_propagation",
    description=(
        "Estimate propagation delay (ps/mm) and total flight time (ps) for a PCB net. "
        "For stripline use er directly.  For microstrip, supply trace_width_mm and "
        "dielectric_height_mm so that effective permittivity is computed via Hammerstad. "
        "Input shape: { er, length_mm, structure?, trace_width_mm?, dielectric_height_mm? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "er": {
                "type": "number",
                "description": "Substrate relative permittivity εr.",
            },
            "length_mm": {
                "type": "number",
                "description": "Trace (net) length [mm].",
            },
            "structure": {
                "type": "string",
                "enum": ["microstrip", "stripline"],
                "description": "Structure type for er_eff calculation (default: 'stripline').",
            },
            "trace_width_mm": {
                "type": "number",
                "description": "Trace width [mm] — required for microstrip er_eff.",
            },
            "dielectric_height_mm": {
                "type": "number",
                "description": "Dielectric height [mm] — required for microstrip er_eff.",
            },
        },
        "required": ["er", "length_mm"],
    },
)


@register(_SI_PROPAGATION_SPEC, write=False)
async def si_propagation(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    er, e = _num(a.get("er"), "er")
    if e:
        return err_payload(e, "BAD_ARGS")
    length_mm, e = _num(a.get("length_mm"), "length_mm")
    if e:
        return err_payload(e, "BAD_ARGS")

    structure = (a.get("structure") or "stripline").strip()
    W = a.get("trace_width_mm")
    H = a.get("dielectric_height_mm")

    W_f = float(W) if isinstance(W, (int, float)) and W > 0 else 0.0
    H_f = float(H) if isinstance(H, (int, float)) and H > 0 else 0.0

    try:
        td = propagation_delay_ps_per_mm(er, W=W_f, H=H_f, structure=structure)
        ft = flight_time_ps(length_mm, td)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    return ok_payload({
        "er": er,
        "structure": structure,
        "length_mm": length_mm,
        "td_ps_per_mm": round(td, 4),
        "flight_time_ps": round(ft, 2),
        "flight_time_ns": round(ft / 1000.0, 5),
    })


# ──────────────────────────────────────────────────────────────────────────────
# 3. si_crosstalk
# ──────────────────────────────────────────────────────────────────────────────

_SI_CROSSTALK_SPEC = ToolSpec(
    name="si_crosstalk",
    description=(
        "Estimate near-end crosstalk (NEXT) and far-end crosstalk (FEXT) for an "
        "aggressor/victim pair.  Uses first-order proximity coupling model consistent "
        "with IPC-2141A §5: NEXT and FEXT decrease monotonically with increased spacing. "
        "Input shape: "
        "{ spacing_mm, dielectric_height_mm, parallel_length_mm, er, "
        "structure?, aggressor_swing_mv? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "spacing_mm": {
                "type": "number",
                "description": "Edge-to-edge spacing between aggressor and victim traces [mm].",
            },
            "dielectric_height_mm": {
                "type": "number",
                "description": (
                    "Microstrip: H above ground [mm].  "
                    "Stripline: use B/2 (half the dielectric stack height) [mm]."
                ),
            },
            "parallel_length_mm": {
                "type": "number",
                "description": "Length of the parallel run (coupled region) [mm].",
            },
            "er": {
                "type": "number",
                "description": "Substrate relative permittivity εr.",
            },
            "structure": {
                "type": "string",
                "enum": ["microstrip", "stripline"],
                "description": "Structure type (default: 'microstrip').",
            },
            "aggressor_swing_mv": {
                "type": "number",
                "description": "Aggressor signal voltage swing [mV] (default: 1000 mV = 1 V).",
            },
        },
        "required": ["spacing_mm", "dielectric_height_mm", "parallel_length_mm", "er"],
    },
)


@register(_SI_CROSSTALK_SPEC, write=False)
async def si_crosstalk(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    S, e = _num(a.get("spacing_mm"), "spacing_mm")
    if e:
        return err_payload(e, "BAD_ARGS")
    H, e = _num(a.get("dielectric_height_mm"), "dielectric_height_mm")
    if e:
        return err_payload(e, "BAD_ARGS")
    L, e = _num(a.get("parallel_length_mm"), "parallel_length_mm")
    if e:
        return err_payload(e, "BAD_ARGS")
    er, e = _num(a.get("er"), "er")
    if e:
        return err_payload(e, "BAD_ARGS")

    structure = (a.get("structure") or "microstrip").strip()
    swing = float(a.get("aggressor_swing_mv") or 1000.0)
    if swing <= 0:
        swing = 1000.0

    try:
        td = propagation_delay_ps_per_mm(er, structure=structure)
        next_result = crosstalk_next(S, H, aggressor_swing_mv=swing)
        fext_result = crosstalk_fext(S, H, L, td, aggressor_swing_mv=swing, structure=structure)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    return ok_payload({
        "spacing_mm": S,
        "dielectric_height_mm": H,
        "parallel_length_mm": L,
        "er": er,
        "structure": structure,
        "aggressor_swing_mv": swing,
        "td_ps_per_mm": round(td, 4),
        "NEXT": next_result,
        "FEXT": fext_result,
        "note": (
            "First-order model: actual crosstalk depends on rise time, termination, "
            "and 3-D field effects.  Use as a pre-layout screening estimate."
        ),
    })


# ──────────────────────────────────────────────────────────────────────────────
# 4. si_termination
# ──────────────────────────────────────────────────────────────────────────────

_SI_TERMINATION_SPEC = ToolSpec(
    name="si_termination",
    description=(
        "Calculate the voltage reflection coefficient (Γ) at the load end and "
        "recommend a termination scheme (series / parallel / Thevenin / AC-RC / none) "
        "with resistor value(s). "
        "Input shape: { driver_z_ohms, line_z0_ohms, topology?, vcc_mv? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "driver_z_ohms": {
                "type": "number",
                "description": "Driver output impedance [ohms] (typical CMOS: 25–50 Ω).",
            },
            "line_z0_ohms": {
                "type": "number",
                "description": "Transmission line characteristic impedance Z0 [ohms].",
            },
            "topology": {
                "type": "string",
                "enum": ["point_to_point", "bus", "clock"],
                "description": (
                    "Net topology: 'point_to_point' (default), 'bus', or 'clock'. "
                    "Determines which termination scheme is preferred."
                ),
            },
            "vcc_mv": {
                "type": "number",
                "description": "Supply voltage [mV] for Thevenin calculations (default: 3300 mV).",
            },
        },
        "required": ["driver_z_ohms", "line_z0_ohms"],
    },
)


@register(_SI_TERMINATION_SPEC, write=False)
async def si_termination(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    dz, e = _num(a.get("driver_z_ohms"), "driver_z_ohms")
    if e:
        return err_payload(e, "BAD_ARGS")
    z0, e = _num(a.get("line_z0_ohms"), "line_z0_ohms")
    if e:
        return err_payload(e, "BAD_ARGS")

    topology = (a.get("topology") or "point_to_point").strip()
    if topology not in ("point_to_point", "bus", "clock"):
        topology = "point_to_point"

    vcc_mv = float(a.get("vcc_mv") or 3300.0)
    if vcc_mv <= 0:
        vcc_mv = 3300.0

    try:
        gamma = reflection_coefficient(1e9, z0)   # open-end reflection for info
        gamma_driver = reflection_coefficient(dz, z0)
        rec = termination_recommendation(dz, z0, topology=topology, vcc_mv=vcc_mv)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    return ok_payload({
        "driver_z_ohms": dz,
        "line_z0_ohms": z0,
        "topology": topology,
        "gamma_open_load": round(gamma, 4),
        "gamma_at_driver": round(gamma_driver, 4),
        **rec,
    })


# ──────────────────────────────────────────────────────────────────────────────
# 5. si_report
# ──────────────────────────────────────────────────────────────────────────────

_SI_REPORT_SPEC = ToolSpec(
    name="si_report",
    description=(
        "Combined signal-integrity summary for a single net.  "
        "Computes Z0, propagation delay, flight time, worst-case crosstalk (if aggressor "
        "geometry supplied), and termination recommendation in one call. "
        "All numeric values are returned rounded for readability. "
        "Input shape: "
        "{ structure, trace_width_mm, dielectric_height_mm, er, length_mm, "
        "driver_z_ohms, copper_thickness_mm?, topology?, vcc_mv?, "
        "spacing_mm?,  aggressor_parallel_length_mm?, aggressor_swing_mv? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "structure": {
                "type": "string",
                "enum": ["microstrip", "stripline"],
            },
            "trace_width_mm": {"type": "number"},
            "dielectric_height_mm": {"type": "number"},
            "er": {"type": "number"},
            "length_mm": {"type": "number", "description": "Net trace length [mm]."},
            "driver_z_ohms": {"type": "number"},
            "copper_thickness_mm": {"type": "number"},
            "topology": {
                "type": "string",
                "enum": ["point_to_point", "bus", "clock"],
            },
            "vcc_mv": {"type": "number"},
            "spacing_mm": {
                "type": "number",
                "description": "Edge-to-edge spacing to nearest aggressor [mm] (enables crosstalk).",
            },
            "aggressor_parallel_length_mm": {
                "type": "number",
                "description": "Parallel run length with aggressor [mm].",
            },
            "aggressor_swing_mv": {
                "type": "number",
                "description": "Aggressor voltage swing [mV].",
            },
        },
        "required": [
            "structure", "trace_width_mm", "dielectric_height_mm",
            "er", "length_mm", "driver_z_ohms",
        ],
    },
)


@register(_SI_REPORT_SPEC, write=False)
async def si_report(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    structure = (a.get("structure") or "").strip()
    if structure not in ("microstrip", "stripline"):
        return err_payload("structure must be 'microstrip' or 'stripline'", "BAD_ARGS")

    W, e = _num(a.get("trace_width_mm"), "trace_width_mm")
    if e:
        return err_payload(e, "BAD_ARGS")
    H, e = _num(a.get("dielectric_height_mm"), "dielectric_height_mm")
    if e:
        return err_payload(e, "BAD_ARGS")
    er, e = _num(a.get("er"), "er")
    if e:
        return err_payload(e, "BAD_ARGS")
    L, e = _num(a.get("length_mm"), "length_mm")
    if e:
        return err_payload(e, "BAD_ARGS")
    dz, e = _num(a.get("driver_z_ohms"), "driver_z_ohms")
    if e:
        return err_payload(e, "BAD_ARGS")

    T, _ = _num(a.get("copper_thickness_mm"), "copper_thickness_mm", required=False, default=0.035)
    topology = (a.get("topology") or "point_to_point").strip()
    vcc_mv = float(a.get("vcc_mv") or 3300.0)
    if vcc_mv <= 0:
        vcc_mv = 3300.0

    S_raw = a.get("spacing_mm")
    agg_L_raw = a.get("aggressor_parallel_length_mm")
    agg_swing = float(a.get("aggressor_swing_mv") or 1000.0)
    if agg_swing <= 0:
        agg_swing = 1000.0

    report: dict = {"structure": structure, "trace_width_mm": W, "dielectric_height_mm": H,
                    "er": er, "copper_thickness_mm": T}

    # Impedance
    try:
        if structure == "microstrip":
            z0 = microstrip_z0(W, H, T, er)
        else:
            z0 = stripline_z0(W, H, T, er)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    report["z0_ohms"] = round(z0, 2)

    # Differential Z0 (if spacing given)
    if isinstance(S_raw, (int, float)) and S_raw > 0:
        S = float(S_raw)
        zdiff = diff_z0(z0, S, H, structure)
        report["spacing_mm"] = S
        report["zdiff_ohms"] = round(zdiff, 2)

    # Propagation delay + flight time
    try:
        td = propagation_delay_ps_per_mm(er, W=W, H=H, structure=structure)
        ft = flight_time_ps(L, td)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    report["length_mm"] = L
    report["td_ps_per_mm"] = round(td, 4)
    report["flight_time_ps"] = round(ft, 2)
    report["flight_time_ns"] = round(ft / 1000.0, 5)

    # Crosstalk (optional — requires spacing + aggressor run length)
    if (isinstance(S_raw, (int, float)) and S_raw > 0 and
            isinstance(agg_L_raw, (int, float)) and agg_L_raw > 0):
        S = float(S_raw)
        agg_L = float(agg_L_raw)
        try:
            next_r = crosstalk_next(S, H, aggressor_swing_mv=agg_swing)
            fext_r = crosstalk_fext(S, H, agg_L, td, aggressor_swing_mv=agg_swing,
                                     structure=structure)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        report["crosstalk"] = {
            "aggressor_parallel_length_mm": agg_L,
            "aggressor_swing_mv": agg_swing,
            "NEXT": next_r,
            "FEXT": fext_r,
        }

    # Termination
    try:
        term = termination_recommendation(dz, z0, topology=topology, vcc_mv=vcc_mv)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    report["driver_z_ohms"] = dz
    report["topology"] = topology
    report["termination"] = term

    return ok_payload(report)


# ──────────────────────────────────────────────────────────────────────────────
# TOOLS export — consumed by plugin._register_tools
# ──────────────────────────────────────────────────────────────────────────────

TOOLS = [
    (_SI_IMPEDANCE_SPEC.name,    _SI_IMPEDANCE_SPEC,    si_impedance),
    (_SI_PROPAGATION_SPEC.name,  _SI_PROPAGATION_SPEC,  si_propagation),
    (_SI_CROSSTALK_SPEC.name,    _SI_CROSSTALK_SPEC,    si_crosstalk),
    (_SI_TERMINATION_SPEC.name,  _SI_TERMINATION_SPEC,  si_termination),
    (_SI_REPORT_SPEC.name,       _SI_REPORT_SPEC,       si_report),
]
