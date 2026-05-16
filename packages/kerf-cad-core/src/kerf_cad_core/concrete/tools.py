"""
kerf_cad_core.concrete.tools — LLM tool wrappers for ACI 318-19 RC design.

Registers ten tools with the Kerf tool registry:

  rc_beam_flexure           — singly/doubly reinforced rectangular beam φMn
  rc_beam_required_As       — required tension steel for given Mu
  rc_beam_shear             — Vc, Vs, stirrup spacing, adequacy check
  rc_tbeam_flange           — ACI effective T-beam flange width
  rc_column_axial           — short tied/spiral column φPn (pure axial)
  rc_column_pm_interaction  — uniaxial P-M interaction diagram points
  rc_development_length     — ACI tension development length with modifiers
  rc_slab_one_way           — one-way slab min thickness & required steel
  rc_immediate_deflection   — Branson Ie + immediate deflection
  rc_crack_control          — ACI §24.3 bar spacing & Gergely-Lutz z

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

Units: US-customary (lb, in, kip, psi) unless noted in each tool description.

References
----------
ACI 318-19 "Building Code Requirements for Structural Concrete"
McCormac & Brown "Design of Reinforced Concrete" 9th ed.
Wight "Reinforced Concrete: Mechanics and Design" 8th ed.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.concrete.design import (
    beam_flexure,
    beam_required_As,
    beam_shear,
    tbeam_effective_flange,
    column_axial,
    column_pm_interaction,
    development_length,
    slab_one_way,
    immediate_deflection,
    crack_control,
)


# ---------------------------------------------------------------------------
# Tool: rc_beam_flexure
# ---------------------------------------------------------------------------

_rc_beam_flexure_spec = ToolSpec(
    name="rc_beam_flexure",
    description=(
        "ACI 318-19 rectangular beam flexural strength (Whitney stress block).\n"
        "\n"
        "Computes a, c, εt, φ, Mn, φMn for singly or doubly reinforced beams.\n"
        "Reports tension/transition/compression-controlled zone and ρ vs ACI limits.\n"
        "\n"
        "Units: all lengths in inches (in), stresses in psi, moments in kip·in.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b": {"type": "number", "description": "Beam width (in). Must be > 0."},
            "d": {"type": "number", "description": "Effective depth to tension steel (in). Must be > 0."},
            "As": {"type": "number", "description": "Tension steel area (in²). Must be >= 0."},
            "fc_psi": {"type": "number", "description": "Concrete f'c (psi). Must be > 0."},
            "fy_psi": {"type": "number", "description": "Steel fy (psi). Must be > 0."},
            "As_prime": {"type": "number", "description": "Compression steel area (in²); 0 = singly reinforced (default 0)."},
            "d_prime": {"type": "number", "description": "Depth to compression steel centroid (in); required if As_prime > 0."},
        },
        "required": ["b", "d", "As", "fc_psi", "fy_psi"],
    },
)


@register(_rc_beam_flexure_spec, write=False)
async def run_rc_beam_flexure(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("b", "d", "As", "fc_psi", "fy_psi"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "As_prime" in a:
        kwargs["As_prime"] = a["As_prime"]
    if "d_prime" in a:
        kwargs["d_prime"] = a["d_prime"]

    result = beam_flexure(a["b"], a["d"], a["As"], a["fc_psi"], a["fy_psi"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_beam_required_As
# ---------------------------------------------------------------------------

_rc_beam_required_As_spec = ToolSpec(
    name="rc_beam_required_As",
    description=(
        "ACI 318-19 required tension steel area for a rectangular beam given Mu.\n"
        "\n"
        "Solves the quadratic for As assuming tension-controlled φ=0.90; verifies "
        "ACI minimum steel and reports φMn at As_req.\n"
        "\n"
        "Units: lengths in inches, stresses in psi, moments in kip·in.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b": {"type": "number", "description": "Beam width (in)."},
            "d": {"type": "number", "description": "Effective depth (in)."},
            "Mu_kipin": {"type": "number", "description": "Factored moment demand (kip·in)."},
            "fc_psi": {"type": "number", "description": "f'c (psi)."},
            "fy_psi": {"type": "number", "description": "fy (psi)."},
        },
        "required": ["b", "d", "Mu_kipin", "fc_psi", "fy_psi"],
    },
)


@register(_rc_beam_required_As_spec, write=False)
async def run_rc_beam_required_As(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("b", "d", "Mu_kipin", "fc_psi", "fy_psi"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = beam_required_As(a["b"], a["d"], a["Mu_kipin"], a["fc_psi"], a["fy_psi"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_beam_shear
# ---------------------------------------------------------------------------

_rc_beam_shear_spec = ToolSpec(
    name="rc_beam_shear",
    description=(
        "ACI 318-19 §22.5 one-way shear for rectangular beams.\n"
        "\n"
        "Returns Vc, Vs at provided stirrups, required spacing s_req, maximum "
        "ACI spacing s_max, and adequacy flag.  Warns on spacing violations and "
        "Vs > Vs_max limit.\n"
        "\n"
        "Units: lengths in inches, stresses in psi, forces/shears in kips.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b_w": {"type": "number", "description": "Web width (in)."},
            "d": {"type": "number", "description": "Effective depth (in)."},
            "fc_psi": {"type": "number", "description": "f'c (psi)."},
            "fy_psi": {"type": "number", "description": "Stirrup fy (psi)."},
            "Vu_kip": {"type": "number", "description": "Factored shear demand (kip)."},
            "Av_in2": {"type": "number", "description": "Stirrup area (both legs) per stirrup (in²)."},
            "s_in": {"type": "number", "description": "Stirrup spacing (in)."},
            "rho_w": {"type": "number", "description": "Longitudinal steel ratio As/(bw*d); 0 → simplified Vc (default 0)."},
            "Nu_kip": {"type": "number", "description": "Factored axial load (kip, + compression); default 0."},
        },
        "required": ["b_w", "d", "fc_psi", "fy_psi", "Vu_kip", "Av_in2", "s_in"],
    },
)


@register(_rc_beam_shear_spec, write=False)
async def run_rc_beam_shear(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("b_w", "d", "fc_psi", "fy_psi", "Vu_kip", "Av_in2", "s_in"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "rho_w" in a:
        kwargs["rho_w"] = a["rho_w"]
    if "Nu_kip" in a:
        kwargs["Nu_kip"] = a["Nu_kip"]

    result = beam_shear(
        a["b_w"], a["d"], a["fc_psi"], a["fy_psi"],
        a["Vu_kip"], a["Av_in2"], a["s_in"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_tbeam_flange
# ---------------------------------------------------------------------------

_rc_tbeam_flange_spec = ToolSpec(
    name="rc_tbeam_flange",
    description=(
        "ACI 318-19 §6.3.2 effective overhanging flange width for T-beams.\n"
        "\n"
        "Governs by the smallest of 8*hf, sw/2, and L/8 (T-beam) or L/12 (L-beam).\n"
        "\n"
        "Units: inches.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bw": {"type": "number", "description": "Web width (in)."},
            "hf": {"type": "number", "description": "Flange (slab) thickness (in)."},
            "span_in": {"type": "number", "description": "Clear span (in)."},
            "spacing_in": {"type": "number", "description": "Center-to-center spacing to adjacent beam (in)."},
            "side": {"type": "string", "enum": ["both", "one"], "description": "'both' (T-beam, default) or 'one' (L-beam)."},
        },
        "required": ["bw", "hf", "span_in", "spacing_in"],
    },
)


@register(_rc_tbeam_flange_spec, write=False)
async def run_rc_tbeam_flange(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("bw", "hf", "span_in", "spacing_in"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "side" in a:
        kwargs["side"] = a["side"]

    result = tbeam_effective_flange(a["bw"], a["hf"], a["span_in"], a["spacing_in"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_column_axial
# ---------------------------------------------------------------------------

_rc_column_axial_spec = ToolSpec(
    name="rc_column_axial",
    description=(
        "ACI 318-19 §22.4.2 short tied or spiral column maximum axial load.\n"
        "\n"
        "Returns Pn, φPn, rho_g, and ACI steel ratio limits.\n"
        "Warns if rho_g outside [1%, 8%].\n"
        "\n"
        "Units: dimensions in inches, stresses in psi, loads in kips.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b": {"type": "number", "description": "Column width (in)."},
            "h": {"type": "number", "description": "Column depth (in)."},
            "Ast": {"type": "number", "description": "Total longitudinal steel area (in²)."},
            "fc_psi": {"type": "number", "description": "f'c (psi)."},
            "fy_psi": {"type": "number", "description": "fy (psi)."},
            "column_type": {"type": "string", "enum": ["tied", "spiral"], "description": "'tied' (default) or 'spiral'."},
        },
        "required": ["b", "h", "Ast", "fc_psi", "fy_psi"],
    },
)


@register(_rc_column_axial_spec, write=False)
async def run_rc_column_axial(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("b", "h", "Ast", "fc_psi", "fy_psi"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "column_type" in a:
        kwargs["column_type"] = a["column_type"]

    result = column_axial(a["b"], a["h"], a["Ast"], a["fc_psi"], a["fy_psi"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_column_pm_interaction
# ---------------------------------------------------------------------------

_rc_column_pm_spec = ToolSpec(
    name="rc_column_pm_interaction",
    description=(
        "ACI 318-19 uniaxial P-M interaction diagram for a rectangular column.\n"
        "\n"
        "Sweeps neutral-axis depth from pure-axial to pure-bending, returning "
        "n_points φPn/φMn pairs.  φ interpolated per ACI §21.2.2.\n"
        "Warns if column is potentially slender (h > 22 in).\n"
        "\n"
        "Units: dimensions in inches, stresses in psi, Pn in kips, Mn in kip·in.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b": {"type": "number", "description": "Column width (in)."},
            "h": {"type": "number", "description": "Column depth (in)."},
            "d": {"type": "number", "description": "Depth to tension steel (in)."},
            "d_prime": {"type": "number", "description": "Depth to compression steel (in)."},
            "As_top": {"type": "number", "description": "Compression-side steel area (in²)."},
            "As_bot": {"type": "number", "description": "Tension-side steel area (in²)."},
            "fc_psi": {"type": "number", "description": "f'c (psi)."},
            "fy_psi": {"type": "number", "description": "fy (psi)."},
            "column_type": {"type": "string", "enum": ["tied", "spiral"], "description": "'tied' (default) or 'spiral'."},
            "n_points": {"type": "integer", "description": "Number of interaction diagram points (default 20)."},
        },
        "required": ["b", "h", "d", "d_prime", "As_top", "As_bot", "fc_psi", "fy_psi"],
    },
)


@register(_rc_column_pm_spec, write=False)
async def run_rc_column_pm_interaction(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("b", "h", "d", "d_prime", "As_top", "As_bot", "fc_psi", "fy_psi"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "column_type" in a:
        kwargs["column_type"] = a["column_type"]
    if "n_points" in a:
        kwargs["n_points"] = a["n_points"]

    result = column_pm_interaction(
        a["b"], a["h"], a["d"], a["d_prime"],
        a["As_top"], a["As_bot"], a["fc_psi"], a["fy_psi"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_development_length
# ---------------------------------------------------------------------------

_rc_development_length_spec = ToolSpec(
    name="rc_development_length",
    description=(
        "ACI 318-19 §25.4.2 tension development length for deformed bars.\n"
        "\n"
        "Applies ψt (top bar), ψe (epoxy), and confinement (cb+Ktr)/db modifiers.\n"
        "Returns ld (in), ld/db ratio, and modification factors.\n"
        "\n"
        "Units: bar diameter and cover in inches, stresses in psi.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "db_in": {"type": "number", "description": "Bar diameter (in): #3=0.375, #4=0.5, #5=0.625, #6=0.75, #8=1.0, #10=1.27, #11=1.41."},
            "fc_psi": {"type": "number", "description": "f'c (psi)."},
            "fy_psi": {"type": "number", "description": "fy (psi)."},
            "coating": {"type": "string", "enum": ["uncoated", "epoxy"], "description": "'uncoated' (default) or 'epoxy'."},
            "position": {"type": "string", "enum": ["top", "other"], "description": "'top' (>12 in fresh concrete below) or 'other' (default)."},
            "cover_in": {"type": "number", "description": "Clear side cover (in)."},
            "spacing_in": {"type": "number", "description": "Clear spacing between bars (in)."},
            "cb_in": {"type": "number", "description": "Smaller of cover or half c/c spacing (in); overrides cover_in/spacing_in if > 0."},
            "Ktr": {"type": "number", "description": "Transverse reinf. index Atr*fyt/(1500*s*n); default 0 (conservative)."},
        },
        "required": ["db_in", "fc_psi", "fy_psi"],
    },
)


@register(_rc_development_length_spec, write=False)
async def run_rc_development_length(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("db_in", "fc_psi", "fy_psi"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("coating", "position", "confinement", "cover_in", "spacing_in", "cb_in", "Ktr"):
        if k in a:
            kwargs[k] = a[k]

    result = development_length(a["db_in"], a["fc_psi"], a["fy_psi"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_slab_one_way
# ---------------------------------------------------------------------------

_rc_slab_one_way_spec = ToolSpec(
    name="rc_slab_one_way",
    description=(
        "ACI 318-19 §7.3.1 one-way slab minimum thickness and required steel.\n"
        "\n"
        "Returns h_min per ACI Table 7.3.1.1 (fy-adjusted), effective depth, "
        "factored moment, required As, and ACI minimum temperature steel.\n"
        "\n"
        "Units: span in inches, load in psf (lb/ft²), stresses in psi, areas in in².\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "span_in": {"type": "number", "description": "Clear span (in)."},
            "fc_psi": {"type": "number", "description": "f'c (psi)."},
            "fy_psi": {"type": "number", "description": "fy (psi)."},
            "wu_psf": {"type": "number", "description": "Factored uniform load (psf = lb/ft²)."},
            "condition": {
                "type": "string",
                "enum": ["simply-supported", "one-end-continuous", "both-ends-continuous", "cantilever"],
                "description": "Support condition (default 'simply-supported').",
            },
            "b_in": {"type": "number", "description": "Design strip width (in); default 12 in."},
        },
        "required": ["span_in", "fc_psi", "fy_psi", "wu_psf"],
    },
)


@register(_rc_slab_one_way_spec, write=False)
async def run_rc_slab_one_way(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("span_in", "fc_psi", "fy_psi", "wu_psf"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "condition" in a:
        kwargs["condition"] = a["condition"]
    if "b_in" in a:
        kwargs["b_in"] = a["b_in"]

    result = slab_one_way(a["span_in"], a["fc_psi"], a["fy_psi"], a["wu_psf"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_immediate_deflection
# ---------------------------------------------------------------------------

_rc_immediate_deflection_spec = ToolSpec(
    name="rc_immediate_deflection",
    description=(
        "ACI 318-19 §24.2.3 immediate deflection using Branson effective Ie.\n"
        "\n"
        "Computes Ig, Icr, Mcr, Ie via Branson's formula, then calculates "
        "immediate deflection from the equivalent uniform load.  "
        "Reports L/Δ ratio and warns if < L/240.\n"
        "\n"
        "Units: dimensions in inches, stresses in psi, moments in kip·in.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b": {"type": "number", "description": "Beam width (in)."},
            "h": {"type": "number", "description": "Total depth (in)."},
            "d": {"type": "number", "description": "Effective depth (in)."},
            "As": {"type": "number", "description": "Tension steel area (in²)."},
            "fc_psi": {"type": "number", "description": "f'c (psi)."},
            "fy_psi": {"type": "number", "description": "fy (psi)."},
            "Ma_kipin": {"type": "number", "description": "Maximum service moment (kip·in)."},
            "span_in": {"type": "number", "description": "Span length (in)."},
            "load_condition": {"type": "string", "enum": ["midspan", "cantilever"], "description": "'midspan' (default, 5/384) or 'cantilever' (1/8)."},
        },
        "required": ["b", "h", "d", "As", "fc_psi", "fy_psi", "Ma_kipin", "span_in"],
    },
)


@register(_rc_immediate_deflection_spec, write=False)
async def run_rc_immediate_deflection(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("b", "h", "d", "As", "fc_psi", "fy_psi", "Ma_kipin", "span_in"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "load_condition" in a:
        kwargs["load_condition"] = a["load_condition"]

    result = immediate_deflection(
        a["b"], a["h"], a["d"], a["As"], a["fc_psi"], a["fy_psi"],
        a["Ma_kipin"], a["span_in"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rc_crack_control
# ---------------------------------------------------------------------------

_rc_crack_control_spec = ToolSpec(
    name="rc_crack_control",
    description=(
        "ACI 318-19 §24.3 crack-control bar spacing check (Gergely-Lutz z).\n"
        "\n"
        "Computes service steel stress from cracked-section analysis, maximum "
        "ACI bar spacing, actual bar spacing, and z-factor.  "
        "Warns on spacing violations and z > 175 kip/in.\n"
        "\n"
        "Units: dimensions in inches, stresses in psi, moments in kip·in.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b": {"type": "number", "description": "Beam width (in)."},
            "h": {"type": "number", "description": "Total depth (in)."},
            "d": {"type": "number", "description": "Effective depth (in)."},
            "As": {"type": "number", "description": "Tension steel area (in²)."},
            "fc_psi": {"type": "number", "description": "f'c (psi)."},
            "fy_psi": {"type": "number", "description": "fy (psi)."},
            "n_bars": {"type": "integer", "description": "Number of tension bars."},
            "Ms_kipin": {"type": "number", "description": "Service (unfactored) moment (kip·in)."},
            "cover_in": {"type": "number", "description": "Clear cover to tension steel (in); default 1.5 in."},
        },
        "required": ["b", "h", "d", "As", "fc_psi", "fy_psi", "n_bars", "Ms_kipin"],
    },
)


@register(_rc_crack_control_spec, write=False)
async def run_rc_crack_control(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("b", "h", "d", "As", "fc_psi", "fy_psi", "n_bars", "Ms_kipin"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "cover_in" in a:
        kwargs["cover_in"] = a["cover_in"]

    result = crack_control(
        a["b"], a["h"], a["d"], a["As"], a["fc_psi"], a["fy_psi"],
        a["n_bars"], a["Ms_kipin"], **kwargs
    )
    return ok_payload(result)
