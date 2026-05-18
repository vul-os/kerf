"""
LLM tool specs and handlers for kerf-structural.

Tools
-----
structural_rc_beam      — ACI 318 RC beam design (required As, ρ checks)
structural_steel_beam   — AISC 360 W-shape moment capacity (LTB)
structural_rebar        — Lap-splice and development length (ACI 318 §25)
structural_loads        — ASCE 7 factored load combinations
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_structural._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# structural_rc_beam
# ---------------------------------------------------------------------------

rc_beam_spec = ToolSpec(
    name="structural_rc_beam",
    description=(
        "ACI 318-19 singly-reinforced rectangular RC beam design. "
        "Returns required steel area As, steel ratio ρ, ρ_min, ρ_max, "
        "and effective depth. All dimensions in inches; moment in kip-ft."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b":           {"type": "number", "description": "Beam width (in)"},
            "h":           {"type": "number", "description": "Total depth (in)"},
            "Mu_kip_ft":   {"type": "number", "description": "Factored moment demand (kip-ft)"},
            "fc":          {"type": "number", "description": "f'c (psi), default 4000"},
            "fy":          {"type": "number", "description": "fy (psi), default 60000"},
            "cover":       {"type": "number", "description": "Clear cover (in), default 1.5"},
            "stirrup_dia": {"type": "number", "description": "Stirrup diameter (in), default 0.375"},
            "bar_dia":     {"type": "number", "description": "Longitudinal bar dia (in), default 0.625"},
        },
        "required": ["b", "h", "Mu_kip_ft"],
    },
)


@register(rc_beam_spec, write=False)
async def run_rc_beam(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_structural.rc_beam import design_rc_beam
        res = design_rc_beam(
            b=float(a["b"]),
            h=float(a["h"]),
            Mu_kip_ft=float(a["Mu_kip_ft"]),
            fc=float(a.get("fc", 4_000)),
            fy=float(a.get("fy", 60_000)),
            cover=float(a.get("cover", 1.5)),
            stirrup_dia=float(a.get("stirrup_dia", 0.375)),
            bar_dia=float(a.get("bar_dia", 0.625)),
        )
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    if not res.ok:
        return err_payload(res.reason, "DESIGN_FAIL")

    return ok_payload({
        "ok": True,
        "b": res.b, "h": res.h, "d": res.d,
        "Mu_kip_ft": a["Mu_kip_ft"],
        "Rn_psi": round(res.Rn, 2),
        "rho": round(res.rho, 6),
        "rho_min": round(res.rho_min, 6),
        "rho_max": round(res.rho_max, 6),
        "As_required_in2": round(res.As_required, 4),
        "phi": res.phi,
    })


# ---------------------------------------------------------------------------
# structural_steel_beam
# ---------------------------------------------------------------------------

steel_beam_spec = ToolSpec(
    name="structural_steel_beam",
    description=(
        "AISC 360-22 Chapter F — design moment capacity φMn for a compact "
        "doubly-symmetric W-shape. Accounts for lateral-torsional buckling "
        "(plastic / inelastic / elastic LTB zones)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "designation": {"type": "string", "description": "AISC designation e.g. 'W18X50'"},
            "Lb_ft":       {"type": "number", "description": "Unbraced length (ft)"},
            "Fy":          {"type": "number", "description": "Yield strength (ksi), default 50"},
            "Cb":          {"type": "number", "description": "LTB modification factor, default 1.0"},
        },
        "required": ["designation", "Lb_ft"],
    },
)


@register(steel_beam_spec, write=False)
async def run_steel_beam(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_structural.steel_beam import design_steel_beam
        res = design_steel_beam(
            section=a["designation"],
            Lb_ft=float(a["Lb_ft"]),
            Fy=float(a.get("Fy", 50.0)),
            Cb=float(a.get("Cb", 1.0)),
        )
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    if not res.ok:
        return err_payload(res.reason, "DESIGN_FAIL")

    return ok_payload({
        "ok": True,
        "designation": res.designation,
        "Lb_ft": a["Lb_ft"],
        "Lp_ft": round(res.Lp / 12.0, 3),
        "Lr_ft": round(res.Lr / 12.0, 3),
        "ltb_zone": res.ltb_zone,
        "Mp_kip_ft": round(res.Mp / 12.0, 2),
        "Mn_kip_ft": round(res.Mn / 12.0, 2),
        "phi_Mn_kip_ft": round(res.phi_Mn_kip_ft, 2),
    })


# ---------------------------------------------------------------------------
# structural_rebar
# ---------------------------------------------------------------------------

rebar_spec = ToolSpec(
    name="structural_rebar",
    description=(
        "ACI 318-19 §25 rebar detailing: development length l_d and "
        "lap-splice length for Class A or B splices."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bar_mark":     {"type": "integer", "description": "Bar number (3–18)"},
            "splice_class": {"type": "string",  "description": "Splice class 'A' or 'B'"},
            "fc":           {"type": "number",  "description": "f'c (psi), default 4000"},
            "fy":           {"type": "number",  "description": "fy (psi), default 60000"},
            "psi_t":        {"type": "number",  "description": "Casting factor, default 1.0"},
            "psi_e":        {"type": "number",  "description": "Coating factor, default 1.0"},
            "cb_Ktr_db":    {"type": "number",  "description": "Confinement factor, default 2.5"},
        },
        "required": ["bar_mark"],
    },
)


@register(rebar_spec, write=False)
async def run_rebar(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_structural.rebar_detailing import (
            bar_info, development_length, lap_splice_length
        )
        bar_mark = int(a["bar_mark"])
        fc = float(a.get("fc", 4_000))
        fy = float(a.get("fy", 60_000))
        psi_t = float(a.get("psi_t", 1.0))
        psi_e = float(a.get("psi_e", 1.0))
        cb_Ktr_db = float(a.get("cb_Ktr_db", 2.5))
        splice_class = str(a.get("splice_class", "B")).upper()

        info = bar_info(bar_mark)
        ld = development_length(
            bar_mark, fc=fc, fy=fy, psi_t=psi_t, psi_e=psi_e, cb_Ktr_db=cb_Ktr_db
        )
        lap = lap_splice_length(
            bar_mark, splice_class, fc=fc, fy=fy, psi_t=psi_t, psi_e=psi_e,
            cb_Ktr_db=cb_Ktr_db
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    return ok_payload({
        "ok": True,
        "bar_mark": bar_mark,
        "diameter_in": info.diameter,
        "area_in2": info.area,
        "fc_psi": fc,
        "fy_psi": fy,
        "ld_in": round(ld, 4),
        "splice_class": splice_class,
        "lap_length_in": round(lap, 4),
    })


# ---------------------------------------------------------------------------
# structural_loads
# ---------------------------------------------------------------------------

loads_spec = ToolSpec(
    name="structural_loads",
    description=(
        "ASCE 7-22 §2.3.1 strength-design load combinations. "
        "Returns all combination values and the governing (maximum) demand."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "D":  {"type": "number", "description": "Dead load"},
            "L":  {"type": "number", "description": "Live load (floor)"},
            "Lr": {"type": "number", "description": "Roof live load"},
            "S":  {"type": "number", "description": "Snow load"},
            "R":  {"type": "number", "description": "Rain load"},
            "W":  {"type": "number", "description": "Wind load"},
            "E":  {"type": "number", "description": "Seismic load"},
            "H":  {"type": "number", "description": "Lateral earth pressure"},
            "F":  {"type": "number", "description": "Fluid pressure"},
        },
        "required": [],
    },
)


@register(loads_spec, write=False)
async def run_loads(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_structural.load_combinations import LoadCase, asce7_strength_combinations, governing_combination
        lc = LoadCase(
            D=float(a.get("D", 0)),
            L=float(a.get("L", 0)),
            Lr=float(a.get("Lr", 0)),
            S=float(a.get("S", 0)),
            R=float(a.get("R", 0)),
            W=float(a.get("W", 0)),
            E=float(a.get("E", 0)),
            H=float(a.get("H", 0)),
            F=float(a.get("F", 0)),
        )
        combos = asce7_strength_combinations(lc)
        gov = governing_combination(lc)
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    return ok_payload({
        "ok": True,
        "combinations": [{"label": r.label, "value": round(r.value, 6)} for r in combos],
        "governing": {"label": gov.label, "value": round(gov.value, 6)},
    })
