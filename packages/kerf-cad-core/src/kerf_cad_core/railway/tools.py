"""
kerf_cad_core.railway.tools — LLM tool wrappers for railway engineering.

Registers thirteen tools with the Kerf tool registry:

  railway_equilibrium_cant      — equilibrium (theoretical) superelevation
  railway_applied_cant          — applied cant + deficiency check
  railway_cant_deficiency       — cant deficiency / excess for given applied cant
  railway_cant_gradient_check   — cant ramp rate check (UIC/EN limits)
  railway_transition_length     — minimum clothoid/cubic spiral length
  railway_gauge_widening        — gauge widening on tight curves
  railway_vertical_curve        — minimum vertical curve length (crest/sag)
  railway_hertzian_contact      — Hertzian wheel–rail contact pressure
  railway_davis_resistance      — Davis train resistance (A+BV+CV²)
  railway_tractive_effort       — tractive effort from power + adhesion limit
  railway_braking_distance      — braking distance & deceleration
  railway_rail_bending          — beam-on-elastic-foundation rail stress
  railway_thermal_stress        — CWR thermal stress + buckling risk

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
UIC 703-2:2011 — Track alignment design parameters
EN 13803-1:2010 — Railway applications — Track alignment design parameters
Hay, W.W. (1982) "Railroad Engineering", 2nd ed.
Esveld, C. (2001) "Modern Railway Track", 2nd ed.
Johnson, K.L. (1985) "Contact Mechanics"
Timoshenko, S.P. (1976) "Strength of Materials, Part II"

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.railway.track import (
    equilibrium_cant,
    applied_cant,
    cant_deficiency,
    cant_gradient_check,
    transition_length,
    gauge_widening,
    vertical_curve_length,
    hertzian_contact,
    davis_resistance,
    tractive_effort,
    braking_distance,
    rail_bending,
    rail_thermal_stress,
)


# ---------------------------------------------------------------------------
# Tool: railway_equilibrium_cant
# ---------------------------------------------------------------------------

_equilibrium_cant_spec = ToolSpec(
    name="railway_equilibrium_cant",
    description=(
        "Compute the equilibrium (theoretical) superelevation / cant for a given "
        "design speed and curve radius.\n"
        "\n"
        "The equilibrium cant is the superelevation at which the resultant of "
        "gravity and centrifugal force acts normal to the track plane — no lateral "
        "force on wheel flanges.\n"
        "\n"
        "Formula: h_eq = V² × G / (g × R)  where V is m/s, G is effective gauge (m).\n"
        "\n"
        "Returns cant_eq_mm (mm).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "speed_kmh": {
                "type": "number",
                "description": "Design speed (km/h). Must be > 0.",
            },
            "radius_m": {
                "type": "number",
                "description": "Horizontal curve radius (m). Must be > 0.",
            },
            "gauge_mm": {
                "type": "number",
                "description": (
                    "Nominal track gauge (mm). Default 1435 mm (standard gauge)."
                ),
            },
        },
        "required": ["speed_kmh", "radius_m"],
    },
)


@register(_equilibrium_cant_spec, write=False)
async def run_equilibrium_cant(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("speed_kmh", "radius_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "gauge_mm" in a:
        kwargs["gauge_mm"] = a["gauge_mm"]

    result = equilibrium_cant(a["speed_kmh"], a["radius_m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_applied_cant
# ---------------------------------------------------------------------------

_applied_cant_spec = ToolSpec(
    name="railway_applied_cant",
    description=(
        "Compute the applied (actual) cant considering policy limits, and report "
        "cant deficiency.\n"
        "\n"
        "Applied cant is capped at max_cant_mm.  Cant deficiency = h_eq − h_applied.\n"
        "Warns if cant deficiency exceeds the allowable limit.\n"
        "\n"
        "Returns cant_eq_mm, cant_applied_mm, cant_deficiency_mm.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "speed_kmh": {
                "type": "number",
                "description": "Design speed (km/h). Must be > 0.",
            },
            "radius_m": {
                "type": "number",
                "description": "Horizontal curve radius (m). Must be > 0.",
            },
            "gauge_mm": {
                "type": "number",
                "description": "Track gauge (mm). Default 1435 mm.",
            },
            "max_cant_mm": {
                "type": "number",
                "description": (
                    "Maximum permissible cant (mm). Default 150 mm (EN 13803 mainline)."
                ),
            },
            "cant_deficiency_limit_mm": {
                "type": "number",
                "description": (
                    "Maximum allowable cant deficiency (mm). Default 130 mm."
                ),
            },
        },
        "required": ["speed_kmh", "radius_m"],
    },
)


@register(_applied_cant_spec, write=False)
async def run_applied_cant(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("speed_kmh", "radius_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("gauge_mm", "max_cant_mm", "cant_deficiency_limit_mm"):
        if k in a:
            kwargs[k] = a[k]

    result = applied_cant(a["speed_kmh"], a["radius_m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_cant_deficiency
# ---------------------------------------------------------------------------

_cant_deficiency_spec = ToolSpec(
    name="railway_cant_deficiency",
    description=(
        "Compute cant deficiency (unbalanced cant) for a given applied cant "
        "on a curve at a specified speed.\n"
        "\n"
        "h_def = h_equilibrium − h_applied\n"
        "Positive = train pulls outward (outer flange loading).\n"
        "Negative = excess cant (inner flange loading).\n"
        "\n"
        "Warns if deficiency exceeds the limit.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "speed_kmh": {
                "type": "number",
                "description": "Speed (km/h). Must be > 0.",
            },
            "radius_m": {
                "type": "number",
                "description": "Curve radius (m). Must be > 0.",
            },
            "cant_applied_mm": {
                "type": "number",
                "description": "Actual applied cant (mm). Must be >= 0.",
            },
            "gauge_mm": {
                "type": "number",
                "description": "Track gauge (mm). Default 1435 mm.",
            },
            "deficiency_limit_mm": {
                "type": "number",
                "description": "Alert threshold for cant deficiency (mm). Default 130 mm.",
            },
        },
        "required": ["speed_kmh", "radius_m", "cant_applied_mm"],
    },
)


@register(_cant_deficiency_spec, write=False)
async def run_cant_deficiency(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("speed_kmh", "radius_m", "cant_applied_mm"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("gauge_mm", "deficiency_limit_mm"):
        if k in a:
            kwargs[k] = a[k]

    result = cant_deficiency(a["speed_kmh"], a["radius_m"], a["cant_applied_mm"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_cant_gradient_check
# ---------------------------------------------------------------------------

_cant_gradient_check_spec = ToolSpec(
    name="railway_cant_gradient_check",
    description=(
        "Check the cant ramp rate against UIC/EN 13803 limits.\n"
        "\n"
        "Two criteria:\n"
        "  Spatial:  cant gradient = Δh / L ≤ 1.0 mm/m\n"
        "  Temporal: cant rate     = Δh × V / L ≤ 55 mm/s\n"
        "\n"
        "Returns cant_gradient_mm_per_m, cant_rate_mm_per_s, gradient_ok, rate_ok.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cant_change_mm": {
                "type": "number",
                "description": "Total cant change over the transition (mm). Must be >= 0.",
            },
            "transition_length_m": {
                "type": "number",
                "description": "Transition length (m). Must be > 0.",
            },
            "speed_kmh": {
                "type": "number",
                "description": "Train speed (km/h). Must be > 0.",
            },
            "gradient_limit_mm_per_m": {
                "type": "number",
                "description": "Spatial cant gradient limit (mm/m). Default 1.0 mm/m.",
            },
            "rate_limit_mm_per_s": {
                "type": "number",
                "description": "Temporal cant rate limit (mm/s). Default 55 mm/s.",
            },
        },
        "required": ["cant_change_mm", "transition_length_m", "speed_kmh"],
    },
)


@register(_cant_gradient_check_spec, write=False)
async def run_cant_gradient_check(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("cant_change_mm", "transition_length_m", "speed_kmh"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("gradient_limit_mm_per_m", "rate_limit_mm_per_s"):
        if k in a:
            kwargs[k] = a[k]

    result = cant_gradient_check(
        a["cant_change_mm"], a["transition_length_m"], a["speed_kmh"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_transition_length
# ---------------------------------------------------------------------------

_transition_length_spec = ToolSpec(
    name="railway_transition_length",
    description=(
        "Compute the minimum transition curve (clothoid/cubic spiral) length "
        "from cant-ramp rate-of-change constraints.\n"
        "\n"
        "Methods:\n"
        "  'rate_of_change' — L = Δh × V / rate_limit  (temporal, default)\n"
        "  'cant_gradient'  — L = Δh / gradient_limit  (spatial)\n"
        "  'combined'       — max(L_rate, L_gradient)\n"
        "\n"
        "Returns transition_length_m, L_rate_m, L_gradient_m.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cant_change_mm": {
                "type": "number",
                "description": "Total cant change over the transition (mm). Must be >= 0.",
            },
            "speed_kmh": {
                "type": "number",
                "description": "Design speed (km/h). Must be > 0.",
            },
            "method": {
                "type": "string",
                "enum": ["rate_of_change", "cant_gradient", "combined"],
                "description": "Length criterion. Default 'rate_of_change'.",
            },
            "rate_limit_mm_s": {
                "type": "number",
                "description": "Temporal cant rate limit (mm/s). Default 55 mm/s.",
            },
            "gradient_limit_mm_m": {
                "type": "number",
                "description": "Spatial cant gradient limit (mm/m). Default 1.0 mm/m.",
            },
        },
        "required": ["cant_change_mm", "speed_kmh"],
    },
)


@register(_transition_length_spec, write=False)
async def run_transition_length(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("cant_change_mm", "speed_kmh"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("method", "rate_limit_mm_s", "gradient_limit_mm_m"):
        if k in a:
            kwargs[k] = a[k]

    result = transition_length(a["cant_change_mm"], a["speed_kmh"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_gauge_widening
# ---------------------------------------------------------------------------

_gauge_widening_spec = ToolSpec(
    name="railway_gauge_widening",
    description=(
        "Compute additional rail gauge widening required on tight curves per "
        "UIC 505 / EN 13715.\n"
        "\n"
        "UIC table (standard gauge):\n"
        "  R >= 250 m → 0 mm\n"
        "  175 ≤ R < 250 m → 5 mm\n"
        "  150 ≤ R < 175 m → 10 mm\n"
        "  R < 150 m → 15 mm\n"
        "\n"
        "Returns gauge_widening_mm and gauge_design_mm.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "radius_m": {
                "type": "number",
                "description": "Curve radius (m). Must be > 0.",
            },
            "gauge_nom_mm": {
                "type": "number",
                "description": "Nominal track gauge (mm). Default 1435 mm.",
            },
            "method": {
                "type": "string",
                "enum": ["UIC", "formula"],
                "description": "'UIC' (table, default) or 'formula' (continuous approximation).",
            },
        },
        "required": ["radius_m"],
    },
)


@register(_gauge_widening_spec, write=False)
async def run_gauge_widening(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("radius_m") is None:
        return json.dumps({"ok": False, "reason": "radius_m is required"})

    kwargs: dict = {}
    for k in ("gauge_nom_mm", "method"):
        if k in a:
            kwargs[k] = a[k]

    result = gauge_widening(a["radius_m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_vertical_curve
# ---------------------------------------------------------------------------

_vertical_curve_spec = ToolSpec(
    name="railway_vertical_curve",
    description=(
        "Compute the minimum vertical curve length for a given change of grade "
        "and design speed.\n"
        "\n"
        "Formulae (EN 13803-1 / UIC 703-2):\n"
        "  Crest: L = V² × |Δg| / 1300  [V km/h, Δg %]\n"
        "  Sag:   L = V² × |Δg| / 400   [V km/h, Δg %]\n"
        "\n"
        "Returns vertical_curve_length_m and K_value (m per 1% grade change).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "delta_g_percent": {
                "type": "number",
                "description": "Algebraic change of grade (%). Absolute value is used.",
            },
            "speed_kmh": {
                "type": "number",
                "description": "Design speed (km/h). Must be > 0.",
            },
            "curve_type": {
                "type": "string",
                "enum": ["crest", "sag"],
                "description": "'crest' (summit, default) or 'sag' (valley).",
            },
        },
        "required": ["delta_g_percent", "speed_kmh"],
    },
)


@register(_vertical_curve_spec, write=False)
async def run_vertical_curve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("delta_g_percent", "speed_kmh"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "curve_type" in a:
        kwargs["curve_type"] = a["curve_type"]

    result = vertical_curve_length(a["delta_g_percent"], a["speed_kmh"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_hertzian_contact
# ---------------------------------------------------------------------------

_hertzian_contact_spec = ToolSpec(
    name="railway_hertzian_contact",
    description=(
        "Compute Hertzian wheel–rail contact semi-axes and maximum contact pressure.\n"
        "\n"
        "Models the wheel and rail as two general quadric surfaces with principal "
        "radii R1x, R1y (wheel) and R2x, R2y (rail).\n"
        "\n"
        "Returns semi_axis_a_m, semi_axis_b_m, contact_area_m2, max_pressure_Pa.\n"
        "\n"
        "Typical inputs:\n"
        "  R1x ≈ 0.46 m (wheel rolling radius)\n"
        "  R1y ≈ 0.5 m  (wheel tread transverse radius)\n"
        "  R2x = 1e9 m  (rail flat in longitudinal direction)\n"
        "  R2y ≈ 0.3 m  (rail head transverse radius)\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "P_N": {
                "type": "number",
                "description": "Normal wheel load (N). Must be > 0. Typical: 50 000–120 000 N.",
            },
            "R1x_m": {
                "type": "number",
                "description": "Wheel rolling radius (m). Must be > 0. Typical: 0.46 m.",
            },
            "R1y_m": {
                "type": "number",
                "description": "Wheel transverse (tread) radius (m). Must be > 0. Typical: 0.5 m.",
            },
            "R2x_m": {
                "type": "number",
                "description": (
                    "Rail longitudinal radius (m). Must be > 0. "
                    "Use large value (e.g. 1e9) for flat rail head in longitudinal dir."
                ),
            },
            "R2y_m": {
                "type": "number",
                "description": "Rail head transverse radius (m). Must be > 0. Typical: 0.3 m.",
            },
            "E1_Pa": {
                "type": "number",
                "description": "Wheel Young's modulus (Pa). Default 210e9 Pa (steel).",
            },
            "nu1": {
                "type": "number",
                "description": "Wheel Poisson's ratio (0–0.5). Default 0.28.",
            },
            "E2_Pa": {
                "type": "number",
                "description": "Rail Young's modulus (Pa). Default 210e9 Pa (steel).",
            },
            "nu2": {
                "type": "number",
                "description": "Rail Poisson's ratio (0–0.5). Default 0.28.",
            },
        },
        "required": ["P_N", "R1x_m", "R1y_m", "R2x_m", "R2y_m"],
    },
)


@register(_hertzian_contact_spec, write=False)
async def run_hertzian_contact(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("P_N", "R1x_m", "R1y_m", "R2x_m", "R2y_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("E1_Pa", "nu1", "E2_Pa", "nu2"):
        if k in a:
            kwargs[k] = a[k]

    result = hertzian_contact(
        a["P_N"], a["R1x_m"], a["R1y_m"], a["R2x_m"], a["R2y_m"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_davis_resistance
# ---------------------------------------------------------------------------

_davis_resistance_spec = ToolSpec(
    name="railway_davis_resistance",
    description=(
        "Compute train resistance using the Davis formula: A + BV + CV².\n"
        "\n"
        "Components:\n"
        "  R_davis  = A + B×V + C×V²          [N/kN — Davis rolling/aero]\n"
        "  R_grade  = 10 × grade%              [N/kN — grade resistance]\n"
        "  R_curve  = 6500 / (R − 55)          [N/kN — Röckl curve resistance]\n"
        "  R_total  = R_davis + R_grade + R_curve\n"
        "\n"
        "Also returns total resistance force R_total_N (Newtons).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mass_kg": {
                "type": "number",
                "description": "Total train mass (kg). Must be > 0.",
            },
            "speed_kmh": {
                "type": "number",
                "description": "Speed (km/h). Must be >= 0.",
            },
            "A": {
                "type": "number",
                "description": "Davis A coefficient (N/kN). Must be >= 0. Typical: 1.5–3.0.",
            },
            "B": {
                "type": "number",
                "description": "Davis B coefficient (N·h/(kN·km)). Must be >= 0. Typical: 0.01–0.05.",
            },
            "C": {
                "type": "number",
                "description": "Davis C coefficient (N·h²/(kN·km²)). Must be >= 0. Typical: 0.001–0.005.",
            },
            "grade_percent": {
                "type": "number",
                "description": "Track grade (%). Positive = ascending. Default 0.",
            },
            "curve_radius_m": {
                "type": "number",
                "description": "Curve radius (m). 0 = tangent track. Default 0. Must be > 55 m if nonzero.",
            },
        },
        "required": ["mass_kg", "speed_kmh", "A", "B", "C"],
    },
)


@register(_davis_resistance_spec, write=False)
async def run_davis_resistance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("mass_kg", "speed_kmh", "A", "B", "C"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("grade_percent", "curve_radius_m", "gauge_mm"):
        if k in a:
            kwargs[k] = a[k]

    result = davis_resistance(
        a["mass_kg"], a["speed_kmh"], a["A"], a["B"], a["C"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_tractive_effort
# ---------------------------------------------------------------------------

_tractive_effort_spec = ToolSpec(
    name="railway_tractive_effort",
    description=(
        "Compute maximum continuous tractive effort from power and check adhesion limit.\n"
        "\n"
        "TE_power     = P / V   (W / (m/s) = N)\n"
        "TE_adhesion  = μ × axle_load_N × driven_axles\n"
        "TE_applied   = min(TE_power, TE_adhesion)  if adhesion active\n"
        "\n"
        "Warns 'adhesion_limited' if adhesion clips the power-based effort.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "power_W": {
                "type": "number",
                "description": "Continuous traction power (W). Must be > 0.",
            },
            "speed_kmh": {
                "type": "number",
                "description": "Speed (km/h). Must be > 0.",
            },
            "adhesion_coeff": {
                "type": "number",
                "description": (
                    "Wheel–rail adhesion coefficient μ. Default 0.25 (dry). "
                    "Wet rail ≈ 0.15; high-speed ≈ 0.20."
                ),
            },
            "axle_load_N": {
                "type": "number",
                "description": "Axle load per driven axle (N). 0 = skip adhesion check. Default 0.",
            },
            "driven_axles": {
                "type": "integer",
                "description": "Number of driven axles. Default 4.",
            },
        },
        "required": ["power_W", "speed_kmh"],
    },
)


@register(_tractive_effort_spec, write=False)
async def run_tractive_effort(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("power_W", "speed_kmh"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("adhesion_coeff", "axle_load_N", "driven_axles"):
        if k in a:
            kwargs[k] = a[k]

    result = tractive_effort(a["power_W"], a["speed_kmh"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_braking_distance
# ---------------------------------------------------------------------------

_braking_distance_spec = ToolSpec(
    name="railway_braking_distance",
    description=(
        "Compute braking distance and mean deceleration from initial speed to rest.\n"
        "\n"
        "s_total = s_reaction + V² / (2 × a_eff)\n"
        "a_eff   = a_brake + g × grade% / 100\n"
        "\n"
        "Returns braking_distance_m, reaction_distance_m, time_to_stop_s.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "speed_kmh": {
                "type": "number",
                "description": "Initial speed (km/h). Must be > 0.",
            },
            "deceleration_ms2": {
                "type": "number",
                "description": (
                    "Applied braking deceleration (m/s²). Must be > 0. "
                    "Conventional trains: 0.7–1.2 m/s²; metro: up to 2.73 m/s²."
                ),
            },
            "reaction_time_s": {
                "type": "number",
                "description": "Driver/system reaction time (s). Default 1.5 s (TSI).",
            },
            "grade_percent": {
                "type": "number",
                "description": (
                    "Track grade (%). Positive = ascending (aids braking). Default 0."
                ),
            },
        },
        "required": ["speed_kmh", "deceleration_ms2"],
    },
)


@register(_braking_distance_spec, write=False)
async def run_braking_distance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("speed_kmh", "deceleration_ms2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("reaction_time_s", "grade_percent"):
        if k in a:
            kwargs[k] = a[k]

    result = braking_distance(a["speed_kmh"], a["deceleration_ms2"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_rail_bending
# ---------------------------------------------------------------------------

_rail_bending_spec = ToolSpec(
    name="railway_rail_bending",
    description=(
        "Compute rail stress, deflection, and ballast pressure using the "
        "Winkler beam-on-elastic-foundation model.\n"
        "\n"
        "Characteristic length: L_c = (4EI/u)^(1/4)\n"
        "Max deflection:        y_max = P / (2 × u × L_c)\n"
        "Max bending moment:    M_max = P × L_c / 4\n"
        "Max rail stress:       σ = M_max × (h/2) / I\n"
        "Sleeper reaction:      F_sl = y_max × u × sleeper_spacing\n"
        "Ballast pressure:      p = F_sl / sleeper_area\n"
        "\n"
        "Typical UIC60 rail: I ≈ 30.55e-6 m⁴, height = 172 mm.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wheel_load_N": {
                "type": "number",
                "description": "Wheel load (N). Must be > 0. Typical: 50 000–100 000 N.",
            },
            "rail_I_m4": {
                "type": "number",
                "description": "Rail second moment of area (m⁴). Must be > 0. UIC60: 30.55e-6 m⁴.",
            },
            "rail_E_Pa": {
                "type": "number",
                "description": "Rail Young's modulus (Pa). Default 210e9 Pa (steel).",
            },
            "foundation_modulus_Pa_per_m": {
                "type": "number",
                "description": (
                    "Winkler foundation modulus u (Pa/m). "
                    "Typical: 15e6–50e6 Pa/m. Default 25e6 Pa/m."
                ),
            },
            "rail_height_m": {
                "type": "number",
                "description": "Rail section height (m). Default 0.172 m (UIC60).",
            },
            "sleeper_spacing_m": {
                "type": "number",
                "description": "Sleeper spacing (m). Default 0.6 m.",
            },
            "sleeper_area_m2": {
                "type": "number",
                "description": "Sleeper bearing area on ballast (m²). Default 0.08 m².",
            },
        },
        "required": ["wheel_load_N", "rail_I_m4"],
    },
)


@register(_rail_bending_spec, write=False)
async def run_rail_bending(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("wheel_load_N", "rail_I_m4"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("rail_E_Pa", "foundation_modulus_Pa_per_m", "rail_height_m",
              "sleeper_spacing_m", "sleeper_area_m2"):
        if k in a:
            kwargs[k] = a[k]

    result = rail_bending(a["wheel_load_N"], a["rail_I_m4"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: railway_thermal_stress
# ---------------------------------------------------------------------------

_thermal_stress_spec = ToolSpec(
    name="railway_thermal_stress",
    description=(
        "Compute rail thermal stress in continuously-welded rail (CWR) and flag "
        "buckling risk.\n"
        "\n"
        "σ = E × α × ΔT   (Pa; positive = compressive when ΔT > 0)\n"
        "\n"
        "Buckling risk flag: compressive stress / yield > 0.70.\n"
        "\n"
        "For jointed rail (CWR=false): no restraint → σ = 0 (free expansion).\n"
        "\n"
        "Returns thermal_stress_Pa, thermal_force_N, CWR_buckling_risk.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "delta_T_K": {
                "type": "number",
                "description": (
                    "Temperature change from stress-free (neutral) temperature (K = °C). "
                    "Positive = warming (compressive); negative = cooling (tensile)."
                ),
            },
            "E_Pa": {
                "type": "number",
                "description": "Rail Young's modulus (Pa). Default 210e9 Pa.",
            },
            "alpha": {
                "type": "number",
                "description": "Rail thermal expansion coefficient (1/K). Default 11.5e-6 /K.",
            },
            "CWR": {
                "type": "boolean",
                "description": (
                    "True (default) = continuously-welded rail (fully restrained). "
                    "False = jointed rail (no thermal stress)."
                ),
            },
            "rail_area_m2": {
                "type": "number",
                "description": "Rail cross-sectional area (m²). Default 7.686e-3 m² (UIC60).",
            },
            "yield_Pa": {
                "type": "number",
                "description": "Rail steel yield stress (Pa). Default 700e6 Pa (grade 900A).",
            },
        },
        "required": ["delta_T_K"],
    },
)


@register(_thermal_stress_spec, write=False)
async def run_thermal_stress(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("delta_T_K") is None:
        return json.dumps({"ok": False, "reason": "delta_T_K is required"})

    kwargs: dict = {}
    for k in ("E_Pa", "alpha", "CWR", "rail_area_m2", "yield_Pa"):
        if k in a:
            kwargs[k] = a[k]

    result = rail_thermal_stress(a["delta_T_K"], **kwargs)
    return ok_payload(result)
