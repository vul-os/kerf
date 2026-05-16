"""
kerf_cad_core.seismic.tools — LLM tool wrappers for seismic ELF analysis.

Registers nine tools with the Kerf tool registry:

  seismic_site_coefficients         — Fa, Fv, SMS, SM1, SDS, SD1 from Ss, S1
                                      and ASCE 7 site class
  seismic_design_spectrum           — Sa(T) on the ASCE 7 design response
                                      spectrum (T0, Ts, constant-a, constant-v,
                                      long-period regions)
  seismic_approximate_period        — Ta = Ct·hn^x per ASCE 7 Table 12.8-2
  seismic_response_coefficient      — Cs with cap (SD1/T or SD1·TL/T²) and
                                      floor (0.044·SDS·Ie ≥ 0.01;
                                      0.5·S1/(R/Ie) when S1≥0.6g)
  seismic_base_shear                — V = Cs · W
  seismic_vertical_distribution     — Fx and Cvx (k-exponent vs period)
  seismic_story_shear_overturning   — Vx and Mx at each storey
  seismic_drift_stability           — inelastic drift Δx, drift ratio,
                                      P-delta θ coefficient
  seismic_sdof_displacement         — elastic SDOF spectral displacement Sd

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ASCE/SEI 7-22 "Minimum Design Loads and Associated Criteria for
Buildings and Other Structures", Chapters 11–12.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.seismic.elf import (
    site_coefficients,
    design_spectrum,
    approximate_period,
    seismic_response_coefficient,
    base_shear,
    vertical_distribution,
    story_shear_and_overturning,
    drift_and_stability,
    sdof_spectral_displacement,
)


# ---------------------------------------------------------------------------
# Tool: seismic_site_coefficients
# ---------------------------------------------------------------------------

_site_coefficients_spec = ToolSpec(
    name="seismic_site_coefficients",
    description=(
        "Compute ASCE 7 site-modified spectral accelerations from mapped MCE "
        "values Ss and S1 for a given ASCE 7 site class.\n"
        "\n"
        "Site coefficients Fa (short-period) and Fv (1-second) are interpolated "
        "from ASCE 7 Tables 11.4-1 and 11.4-2.  Site-modified values:\n"
        "  SMS = Fa · Ss   SM1 = Fv · S1\n"
        "Design spectral accelerations:\n"
        "  SDS = 2/3 · SMS   SD1 = 2/3 · SM1\n"
        "\n"
        "Site class E with Ss > 0.75g or S1 > 0.30g requires site-specific "
        "analysis — tool returns an error for those cases.\n"
        "\n"
        "Returns Fa, Fv, SMS, SM1, SDS, SD1, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Ss": {
                "type": "number",
                "description": (
                    "Mapped MCE short-period spectral acceleration (g). "
                    "Must be >= 0. Obtain from ASCE 7 Figure 22-1 or USGS."
                ),
            },
            "S1": {
                "type": "number",
                "description": (
                    "Mapped MCE 1-second spectral acceleration (g). "
                    "Must be >= 0. Obtain from ASCE 7 Figure 22-2 or USGS."
                ),
            },
            "site_class": {
                "type": "string",
                "enum": ["A", "B", "C", "D", "E"],
                "description": (
                    "ASCE 7 site class (soil type): "
                    "A=hard rock, B=rock, C=very dense soil/soft rock, "
                    "D=stiff soil (default when unknown), E=soft clay."
                ),
            },
        },
        "required": ["Ss", "S1", "site_class"],
    },
)


@register(_site_coefficients_spec, write=False)
async def run_site_coefficients(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Ss", "S1", "site_class"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = site_coefficients(a["Ss"], a["S1"], a["site_class"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_design_spectrum
# ---------------------------------------------------------------------------

_design_spectrum_spec = ToolSpec(
    name="seismic_design_spectrum",
    description=(
        "Evaluate the ASCE 7 design response spectral acceleration Sa(T) at a "
        "given structural period T.\n"
        "\n"
        "The spectrum has four regions:\n"
        "  rising (0 ≤ T < T0):             Sa = SDS·(0.4 + 0.6·T/T0)\n"
        "  constant acceleration (T0–Ts):    Sa = SDS\n"
        "  constant velocity (Ts–TL):        Sa = SD1/T\n"
        "  long period (T > TL):             Sa = SD1·TL/T²\n"
        "\n"
        "where T0 = 0.2·SD1/SDS, Ts = SD1/SDS.\n"
        "\n"
        "Returns T, Sa_g, region, T0, Ts, TL, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T": {
                "type": "number",
                "description": "Structural period (s). Must be >= 0.",
            },
            "SDS": {
                "type": "number",
                "description": "Design spectral acceleration, short period (g). > 0.",
            },
            "SD1": {
                "type": "number",
                "description": "Design spectral acceleration, 1-second period (g). > 0.",
            },
            "TL": {
                "type": "number",
                "description": (
                    "Long-period transition period (s). Default 6.0. "
                    "Obtain from ASCE 7 Figure 22-14 for your region."
                ),
            },
        },
        "required": ["T", "SDS", "SD1"],
    },
)


@register(_design_spectrum_spec, write=False)
async def run_design_spectrum(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T", "SDS", "SD1"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "TL" in a:
        kwargs["TL"] = a["TL"]

    result = design_spectrum(a["T"], a["SDS"], a["SD1"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_approximate_period
# ---------------------------------------------------------------------------

_approximate_period_spec = ToolSpec(
    name="seismic_approximate_period",
    description=(
        "Compute the approximate fundamental period Ta = Ct · hn^x per "
        "ASCE 7 Table 12.8-2.\n"
        "\n"
        "Ct and x coefficients by structure type:\n"
        "  'steel_moment':         Ct=0.0724, x=0.80\n"
        "  'concrete_moment':      Ct=0.0466, x=0.90\n"
        "  'eccentrically_braced': Ct=0.0731, x=0.75\n"
        "  'other' (default):      Ct=0.0488, x=0.75\n"
        "\n"
        "hn is the height above base to the highest structural level (m).\n"
        "Flags tall structures (hn > 72 m) and long-period results (Ta > 4 s).\n"
        "\n"
        "Returns Ta_s, Ct, x, hn_m, structure_type, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hn": {
                "type": "number",
                "description": (
                    "Height above base to highest structural level (m). Must be > 0."
                ),
            },
            "structure_type": {
                "type": "string",
                "enum": [
                    "steel_moment", "concrete_moment",
                    "eccentrically_braced", "other",
                ],
                "description": (
                    "Structural system type for Ct/x coefficient lookup. "
                    "Default: 'other'."
                ),
            },
        },
        "required": ["hn"],
    },
)


@register(_approximate_period_spec, write=False)
async def run_approximate_period(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("hn") is None:
        return json.dumps({"ok": False, "reason": "hn is required"})

    kwargs: dict = {}
    if "structure_type" in a:
        kwargs["structure_type"] = a["structure_type"]

    result = approximate_period(a["hn"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_response_coefficient
# ---------------------------------------------------------------------------

_response_coefficient_spec = ToolSpec(
    name="seismic_response_coefficient",
    description=(
        "Compute seismic response coefficient Cs per ASCE 7 §12.8.1.1.\n"
        "\n"
        "  Cs_basic = SDS / (R/Ie)\n"
        "  Cs_cap   = SD1 / (T · R/Ie)        for T ≤ TL\n"
        "           = SD1·TL / (T² · R/Ie)     for T > TL\n"
        "  Cs_floor = max(0.044·SDS·Ie, 0.01)  always\n"
        "           = max(above, 0.5·S1/(R/Ie)) when S1 ≥ 0.6g\n"
        "  Cs       = max(min(Cs_basic, Cs_cap), Cs_floor)\n"
        "\n"
        "Flags when cap governs (long-period/high-R) or floor governs.\n"
        "\n"
        "Returns Cs, Cs_basic, Cs_cap, Cs_floor, cap_governs, "
        "floor_governs, R_over_Ie, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "SDS": {
                "type": "number",
                "description": "Design spectral acceleration, short period (g). > 0.",
            },
            "SD1": {
                "type": "number",
                "description": "Design spectral acceleration, 1-second period (g). > 0.",
            },
            "T": {
                "type": "number",
                "description": "Fundamental period (s). > 0.",
            },
            "R": {
                "type": "number",
                "description": (
                    "Response modification coefficient (dimensionless). "
                    "From ASCE 7 Table 12.2-1. > 0. Typical: 3–8."
                ),
            },
            "Ie": {
                "type": "number",
                "description": (
                    "Seismic importance factor (dimensionless). "
                    "1.0 (Risk Cat I/II), 1.25 (Risk Cat III), 1.5 (Risk Cat IV)."
                ),
            },
            "TL": {
                "type": "number",
                "description": (
                    "Long-period transition period (s). Default 6.0."
                ),
            },
            "S1": {
                "type": "number",
                "description": (
                    "Mapped MCE 1-second acceleration (g) for Cs floor "
                    "when S1 ≥ 0.6g. Default 0."
                ),
            },
        },
        "required": ["SDS", "SD1", "T", "R", "Ie"],
    },
)


@register(_response_coefficient_spec, write=False)
async def run_response_coefficient(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("SDS", "SD1", "T", "R", "Ie"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("TL", "S1"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = seismic_response_coefficient(
        a["SDS"], a["SD1"], a["T"], a["R"], a["Ie"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_base_shear
# ---------------------------------------------------------------------------

_base_shear_spec = ToolSpec(
    name="seismic_base_shear",
    description=(
        "Compute the seismic base shear V = Cs · W (ASCE 7 §12.8.1).\n"
        "\n"
        "W is the effective seismic weight (total dead load + applicable "
        "portions of live/snow/storage loads per §12.7.2).\n"
        "\n"
        "Returns V_kN, Cs, W_kN, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Cs": {
                "type": "number",
                "description": (
                    "Seismic response coefficient (dimensionless). > 0. "
                    "Compute via seismic_response_coefficient tool."
                ),
            },
            "W": {
                "type": "number",
                "description": "Effective seismic weight (kN). > 0.",
            },
        },
        "required": ["Cs", "W"],
    },
)


@register(_base_shear_spec, write=False)
async def run_base_shear(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Cs", "W"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = base_shear(a["Cs"], a["W"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_vertical_distribution
# ---------------------------------------------------------------------------

_vertical_distribution_spec = ToolSpec(
    name="seismic_vertical_distribution",
    description=(
        "Distribute the base shear V vertically to storey levels as Fx "
        "per ASCE 7 §12.8.3.\n"
        "\n"
        "  Cvx = (wx · hx^k) / Σ(wi · hi^k)\n"
        "  Fx  = Cvx · V\n"
        "\n"
        "k exponent:\n"
        "  T ≤ 0.5 s  → k = 1.0 (linear/triangular distribution)\n"
        "  T ≥ 2.5 s  → k = 2.0 (parabolic — higher modes)\n"
        "  0.5–2.5 s  → k interpolated linearly\n"
        "\n"
        "W_stories and h_stories are listed from the ground floor to the "
        "roof (bottom to top).\n"
        "\n"
        "Returns Fx_kN (list), Cvx (list), k, V_kN, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V": {
                "type": "number",
                "description": "Total base shear (kN). > 0.",
            },
            "W_stories": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Seismic weight at each storey level (kN). "
                    "List from bottom (ground) to top (roof). All > 0."
                ),
            },
            "h_stories": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Height of each storey level above the base (m). "
                    "Strictly increasing. All > 0."
                ),
            },
            "T": {
                "type": "number",
                "description": "Fundamental period (s). > 0.",
            },
        },
        "required": ["V", "W_stories", "h_stories", "T"],
    },
)


@register(_vertical_distribution_spec, write=False)
async def run_vertical_distribution(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("V", "W_stories", "h_stories", "T"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = vertical_distribution(
        a["V"], a["W_stories"], a["h_stories"], a["T"]
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_story_shear_overturning
# ---------------------------------------------------------------------------

_story_shear_overturning_spec = ToolSpec(
    name="seismic_story_shear_overturning",
    description=(
        "Compute storey shear Vx and overturning moment Mx at each level "
        "from the lateral force distribution Fx.\n"
        "\n"
        "  Vx[i]  = Σ Fx[j]  for j ≥ i  (sum of forces above and at level i)\n"
        "  Mx[i]  = Σ Fx[j]·(h[j]−h[i]) for j ≥ i  (moment about level i)\n"
        "\n"
        "Fx and h_stories lists must be the same length and ordered "
        "bottom to top.\n"
        "\n"
        "Returns Vx_kN (list), Mx_kNm (list), warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Fx": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Lateral force at each storey (kN). Bottom to top. "
                    "Compute via seismic_vertical_distribution."
                ),
            },
            "h_stories": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Height of each storey above the base (m). "
                    "Bottom to top. Must match Fx length."
                ),
            },
        },
        "required": ["Fx", "h_stories"],
    },
)


@register(_story_shear_overturning_spec, write=False)
async def run_story_shear_overturning(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Fx", "h_stories"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = story_shear_and_overturning(a["Fx"], a["h_stories"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_drift_stability
# ---------------------------------------------------------------------------

_drift_stability_spec = ToolSpec(
    name="seismic_drift_stability",
    description=(
        "Compute inelastic storey drift Δx, drift ratio, and P-delta "
        "stability coefficient θ per ASCE 7 §12.8.6–12.8.7.\n"
        "\n"
        "  Δx = Cd · δxe / Ie             (inelastic drift, m)\n"
        "  drift_ratio = Δx / hsx\n"
        "  θ = Px·Δx / (Vx·hsx·Cd)\n"
        "\n"
        "Flags:\n"
        "  • drift_ratio > drift_limit_ratio → drift exceedance warning\n"
        "  • θ > 0.10 → P-delta stability warning (ASCE 7 §12.8.7)\n"
        "  • any drift exceedance → irregularity-note\n"
        "\n"
        "All lists are ordered bottom storey to top (same length).\n"
        "\n"
        "Returns Delta_x_m, drift_ratio, drift_ok, theta, theta_ok, "
        "Cd, Ie, drift_limit_ratio, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "delta_xe": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Elastic storey displacements from analysis (m). Bottom to top."
                ),
            },
            "Cd": {
                "type": "number",
                "description": (
                    "Deflection amplification factor (dimensionless). "
                    "From ASCE 7 Table 12.2-1. > 0. Typical: 4–6.5."
                ),
            },
            "Ie": {
                "type": "number",
                "description": "Seismic importance factor (dimensionless). > 0.",
            },
            "Px": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Total gravity load (dead + applicable live) above each "
                    "storey level (kN). Bottom to top. All >= 0."
                ),
            },
            "Vx": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Storey shear at each level (kN). Bottom to top. "
                    "Compute via seismic_story_shear_overturning. All > 0."
                ),
            },
            "hsx": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Storey height at each level (m). Bottom to top. All > 0."
                ),
            },
            "drift_limit_ratio": {
                "type": "number",
                "description": (
                    "Allowable drift ratio Δ_allow/hsx. "
                    "Default 0.02 (2%); per ASCE 7 Table 12.12-1."
                ),
            },
        },
        "required": ["delta_xe", "Cd", "Ie", "Px", "Vx", "hsx"],
    },
)


@register(_drift_stability_spec, write=False)
async def run_drift_stability(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("delta_xe", "Cd", "Ie", "Px", "Vx", "hsx"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "drift_limit_ratio" in a:
        kwargs["drift_limit_ratio"] = a["drift_limit_ratio"]

    result = drift_and_stability(
        a["delta_xe"], a["Cd"], a["Ie"],
        a["Px"], a["Vx"], a["hsx"],
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_sdof_displacement
# ---------------------------------------------------------------------------

_sdof_displacement_spec = ToolSpec(
    name="seismic_sdof_displacement",
    description=(
        "Compute the elastic SDOF spectral displacement:\n"
        "\n"
        "  Sd = Sa · g · T² / (4π²)   (metres)\n"
        "\n"
        "where Sa is the spectral acceleration in g, T is the period in "
        "seconds, and g = 9.80665 m/s².\n"
        "\n"
        "Useful for quick displacement demand estimates from a spectrum "
        "value (e.g., from seismic_design_spectrum Sa_g output).\n"
        "\n"
        "Returns Sd_m, Sd_mm, Sa_g, T_s, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Sa_g": {
                "type": "number",
                "description": "Spectral acceleration (g). >= 0.",
            },
            "T": {
                "type": "number",
                "description": "Period (s). > 0.",
            },
        },
        "required": ["Sa_g", "T"],
    },
)


@register(_sdof_displacement_spec, write=False)
async def run_sdof_displacement(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Sa_g", "T"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = sdof_spectral_displacement(a["Sa_g"], a["T"])
    return ok_payload(result)
