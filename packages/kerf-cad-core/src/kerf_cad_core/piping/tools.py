"""
kerf_cad_core.piping.tools — LLM tool wrappers for ASME B31.3 process piping.

Registers seven tools with the Kerf tool registry:

  pipe_schedule_lookup        — OD / wall thickness from ASME B36.10M table
  pipe_wall_thickness         — Required wall thickness per ASME B31.3 Eq. (3a)
  pipe_pressure_drop          — Single-phase Darcy-Weisbach pressure drop
  pipe_allowable_span         — Maximum support spacing (deflection + stress)
  pipe_thermal_expansion      — Free elongation ΔL = L·α·ΔT
  pipe_guided_cantilever_leg  — Minimum leg length for thermal-expansion loops
  pipe_expansion_stress       — Two-anchor guided-cantilever expansion stress check

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ASME B31.3-2022 — Process Piping
ASME B36.10M-2018 — Welded and Seamless Wrought Steel Pipe
Crane TP-410 — Flow of Fluids Through Valves, Fittings and Pipe
MSS SP-69 — Pipe Hangers and Supports

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.piping.process import (
    schedule_lookup,
    required_wall_thickness,
    pressure_drop,
    allowable_span,
    thermal_expansion,
    guided_cantilever_leg,
    expansion_stress_check,
)


# ---------------------------------------------------------------------------
# Tool: pipe_schedule_lookup
# ---------------------------------------------------------------------------

_schedule_lookup_spec = ToolSpec(
    name="pipe_schedule_lookup",
    description=(
        "Look up pipe outside diameter and wall thickness from ASME B36.10M / "
        "B36.19M tables for a given nominal pipe size (NPS) and schedule.\n"
        "\n"
        "Returns OD, wall thickness, and inside diameter in both mm and metres.\n"
        "\n"
        "Supported NPS (inches): 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4, 6, 8, "
        "10, 12, 16, 20, 24.\n"
        "Supported schedules include: 20, 40, 60, 80, 100, 120, 160, XXS.\n"
        "\n"
        "Errors: {ok:false, reason} for unknown NPS or schedule. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nominal_size_in": {
                "description": (
                    "Nominal pipe size in inches as a string or number. "
                    "Examples: '4', '1.5', 6, '0.75'."
                ),
            },
            "schedule": {
                "type": "string",
                "description": (
                    "Pipe schedule string. Examples: '40', '80', '160', 'XXS', '20'."
                ),
            },
        },
        "required": ["nominal_size_in", "schedule"],
    },
)


@register(_schedule_lookup_spec, write=False)
async def run_pipe_schedule_lookup(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    nps = a.get("nominal_size_in")
    sch = a.get("schedule")
    if nps is None:
        return json.dumps({"ok": False, "reason": "nominal_size_in is required"})
    if sch is None:
        return json.dumps({"ok": False, "reason": "schedule is required"})

    result = schedule_lookup(nps, sch)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: pipe_wall_thickness
# ---------------------------------------------------------------------------

_wall_thickness_spec = ToolSpec(
    name="pipe_wall_thickness",
    description=(
        "Compute the minimum required pipe wall thickness per ASME B31.3 "
        "§304.1.2 Eq. (3a).\n"
        "\n"
        "Formula: t_m = P·D / (2·(S·E·W + P·Y))\n"
        "Then: t_req = t_m / (1 - c_mill) + c_corr\n"
        "\n"
        "Parameters:\n"
        "  P       — internal design pressure (Pa)\n"
        "  D       — pipe outside diameter (m)\n"
        "  S       — allowable stress at design temperature (Pa)\n"
        "  E       — longitudinal joint quality factor (default 1.0 seamless)\n"
        "  W       — weld joint strength reduction factor (default 1.0)\n"
        "  Y       — B31.3 Table 304.1.1 Y coefficient (default 0.4)\n"
        "  c_corr  — corrosion/erosion allowance (m, default 0)\n"
        "  c_mill  — mill under-tolerance as fraction (default 0 = 0%)\n"
        "\n"
        "Returns t_required in metres and mm, plus all intermediate values.\n"
        "Issues a warning if t_required > D/6 (thick-cylinder regime).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "P": {
                "type": "number",
                "description": "Internal design pressure (Pa). Must be >= 0.",
            },
            "D": {
                "type": "number",
                "description": "Pipe outside diameter (m). Must be > 0.",
            },
            "S": {
                "type": "number",
                "description": "Allowable stress at design temperature (Pa). Must be > 0.",
            },
            "E": {
                "type": "number",
                "description": (
                    "Longitudinal joint quality factor (default 1.0 = seamless). "
                    "0.85 = ERW, 0.80 = furnace butt-weld. Range (0, 1]."
                ),
            },
            "W": {
                "type": "number",
                "description": (
                    "Weld joint strength reduction factor (default 1.0). "
                    "Required for T > 510 °C; otherwise 1.0. Range (0, 1]."
                ),
            },
            "Y": {
                "type": "number",
                "description": (
                    "B31.3 Table 304.1.1 Y coefficient (default 0.4 for "
                    "ferritic/austenitic steel and Ni alloys below 482 °C). Range [0, 1)."
                ),
            },
            "c_corr": {
                "type": "number",
                "description": (
                    "Corrosion/erosion allowance (m). Default 0. "
                    "Typical: 1.5–3 mm (0.0015–0.003 m) for carbon steel."
                ),
            },
            "c_mill": {
                "type": "number",
                "description": (
                    "Mill under-tolerance as a fraction (default 0). "
                    "Typically 0.125 (12.5%) per ASTM A106. Range [0, 1)."
                ),
            },
        },
        "required": ["P", "D", "S"],
    },
)


@register(_wall_thickness_spec, write=False)
async def run_pipe_wall_thickness(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("P", "D", "S"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("E", "W", "Y", "c_corr", "c_mill"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = required_wall_thickness(a["P"], a["D"], a["S"], **kwargs)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: pipe_pressure_drop
# ---------------------------------------------------------------------------

_pressure_drop_spec = ToolSpec(
    name="pipe_pressure_drop",
    description=(
        "Compute single-phase pressure drop in a pipe using the Darcy-Weisbach "
        "equation with Colebrook-White friction factor (Crane TP-410 / ASME B31.3).\n"
        "\n"
        "Fittings and valves are included as an equivalent pipe-length sum "
        "(L_e sum from Crane TP-410 Table B-1).\n"
        "\n"
        "Parameters:\n"
        "  Q           — volumetric flow rate (m³/s)\n"
        "  rho         — fluid density (kg/m³)\n"
        "  mu          — dynamic viscosity (Pa·s)\n"
        "  D_i         — pipe inside diameter (m)\n"
        "  L           — straight pipe length (m)\n"
        "  roughness   — absolute roughness (m, default 46e-6 for carbon steel)\n"
        "  fittings_Le — equivalent length of all fittings (m, default 0)\n"
        "\n"
        "Returns pressure drop in Pa, kPa, bar, velocity, Re, friction factor.\n"
        "Warns if velocity > 3 m/s (erosion check) or Re is in transition zone.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q": {
                "type": "number",
                "description": "Volumetric flow rate (m³/s). Must be > 0.",
            },
            "rho": {
                "type": "number",
                "description": "Fluid density (kg/m³). Must be > 0. Water = 1000.",
            },
            "mu": {
                "type": "number",
                "description": "Dynamic viscosity (Pa·s). Must be > 0. Water ≈ 1e-3.",
            },
            "D_i": {
                "type": "number",
                "description": "Pipe inside diameter (m). Must be > 0.",
            },
            "L": {
                "type": "number",
                "description": "Straight pipe length (m). Must be >= 0.",
            },
            "roughness": {
                "type": "number",
                "description": (
                    "Absolute pipe roughness (m). "
                    "Default 46e-6 m (commercial steel). Must be >= 0."
                ),
            },
            "fittings_Le": {
                "type": "number",
                "description": (
                    "Sum of equivalent lengths for all fittings/valves (m). "
                    "Default 0. From Crane TP-410 Table B-1. Must be >= 0."
                ),
            },
        },
        "required": ["Q", "rho", "mu", "D_i", "L"],
    },
)


@register(_pressure_drop_spec, write=False)
async def run_pipe_pressure_drop(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q", "rho", "mu", "D_i", "L"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "roughness" in a:
        kwargs["roughness"] = a["roughness"]
    if "fittings_Le" in a:
        kwargs["fittings_Le"] = a["fittings_Le"]

    result = pressure_drop(a["Q"], a["rho"], a["mu"], a["D_i"], a["L"], **kwargs)
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: pipe_allowable_span
# ---------------------------------------------------------------------------

_allowable_span_spec = ToolSpec(
    name="pipe_allowable_span",
    description=(
        "Compute the maximum allowable support span for a simply-supported pipe "
        "per MSS SP-69, limited by either mid-span deflection or bending stress "
        "(the smaller governs).\n"
        "\n"
        "Parameters:\n"
        "  D_o              — pipe outside diameter (m)\n"
        "  D_i              — pipe inside diameter (m)\n"
        "  rho_pipe         — pipe material density (kg/m³, carbon steel ≈ 7850)\n"
        "  rho_fluid        — fluid density (kg/m³, water = 1000, gas ≈ 0)\n"
        "  E                — Young's modulus (Pa, carbon steel ≈ 200e9)\n"
        "  S_allow          — allowable bending stress (Pa)\n"
        "  deflection_limit — max allowable deflection (m, default 0.0254 = 1 in)\n"
        "\n"
        "Returns governing span, span from each criterion, section properties.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "D_o": {
                "type": "number",
                "description": "Pipe outside diameter (m). Must be > 0.",
            },
            "D_i": {
                "type": "number",
                "description": "Pipe inside diameter (m). Must be > 0 and < D_o.",
            },
            "rho_pipe": {
                "type": "number",
                "description": "Pipe material density (kg/m³). Carbon steel = 7850.",
            },
            "rho_fluid": {
                "type": "number",
                "description": "Fluid density inside pipe (kg/m³). Water = 1000, gas ≈ 0.",
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa). Carbon steel ≈ 200e9.",
            },
            "S_allow": {
                "type": "number",
                "description": "Allowable bending stress (Pa). Must be > 0.",
            },
            "deflection_limit": {
                "type": "number",
                "description": (
                    "Maximum allowable mid-span deflection (m). "
                    "Default 0.0254 m (1 inch) per MSS SP-69. Must be > 0."
                ),
            },
        },
        "required": ["D_o", "D_i", "rho_pipe", "rho_fluid", "E", "S_allow"],
    },
)


@register(_allowable_span_spec, write=False)
async def run_pipe_allowable_span(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("D_o", "D_i", "rho_pipe", "rho_fluid", "E", "S_allow"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "deflection_limit" in a:
        kwargs["deflection_limit"] = a["deflection_limit"]

    result = allowable_span(
        a["D_o"], a["D_i"], a["rho_pipe"], a["rho_fluid"],
        a["E"], a["S_allow"], **kwargs
    )
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: pipe_thermal_expansion
# ---------------------------------------------------------------------------

_thermal_expansion_spec = ToolSpec(
    name="pipe_thermal_expansion",
    description=(
        "Compute the free thermal elongation of a pipe segment.\n"
        "\n"
        "Formula: ΔL = L · α · (T_operating - T_install)\n"
        "\n"
        "Parameters:\n"
        "  L           — pipe length (m)\n"
        "  alpha       — coefficient of thermal expansion (1/°C)\n"
        "                Carbon steel ≈ 11.7e-6, austenitic SS 316 ≈ 16.0e-6\n"
        "  T_install   — installation temperature (°C)\n"
        "  T_operating — operating temperature (°C)\n"
        "\n"
        "Returns ΔL in metres and mm, and the temperature delta.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "L": {
                "type": "number",
                "description": "Pipe segment length (m). Must be > 0.",
            },
            "alpha": {
                "type": "number",
                "description": (
                    "Coefficient of thermal expansion (1/°C). Must be > 0. "
                    "Carbon steel ≈ 11.7e-6, SS 316 ≈ 16.0e-6."
                ),
            },
            "T_install": {
                "type": "number",
                "description": "Installation (ambient) temperature (°C).",
            },
            "T_operating": {
                "type": "number",
                "description": "Operating temperature (°C).",
            },
        },
        "required": ["L", "alpha", "T_install", "T_operating"],
    },
)


@register(_thermal_expansion_spec, write=False)
async def run_pipe_thermal_expansion(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("L", "alpha", "T_install", "T_operating"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = thermal_expansion(a["L"], a["alpha"], a["T_install"], a["T_operating"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: pipe_guided_cantilever_leg
# ---------------------------------------------------------------------------

_guided_cantilever_leg_spec = ToolSpec(
    name="pipe_guided_cantilever_leg",
    description=(
        "Compute the minimum leg length required for a guided-cantilever "
        "piping elbow to absorb a given thermal or settlement displacement "
        "within the allowable expansion stress.\n"
        "\n"
        "Formula: L_leg = √(3·E·I·δ / (S_allow·Z))\n"
        "\n"
        "Parameters:\n"
        "  D_o     — pipe outside diameter (m)\n"
        "  t       — pipe wall thickness (m)\n"
        "  E       — Young's modulus (Pa)\n"
        "  S_allow — allowable expansion stress range (Pa); "
                     "typically S_A = f·(1.25·S_c + 0.25·S_h) per B31.3\n"
        "  delta   — displacement to absorb (m)\n"
        "\n"
        "Returns minimum leg length in metres and mm.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "D_o": {
                "type": "number",
                "description": "Pipe outside diameter (m). Must be > 0.",
            },
            "t": {
                "type": "number",
                "description": "Pipe wall thickness (m). Must be > 0 and < D_o/2.",
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa). Must be > 0. Carbon steel ≈ 200e9.",
            },
            "S_allow": {
                "type": "number",
                "description": (
                    "Allowable expansion stress range (Pa). Must be > 0. "
                    "Typically S_A = f·(1.25·S_c + 0.25·S_h) per B31.3 §302.3.5."
                ),
            },
            "delta": {
                "type": "number",
                "description": "Displacement to absorb (m). Must be > 0.",
            },
        },
        "required": ["D_o", "t", "E", "S_allow", "delta"],
    },
)


@register(_guided_cantilever_leg_spec, write=False)
async def run_pipe_guided_cantilever_leg(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("D_o", "t", "E", "S_allow", "delta"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = guided_cantilever_leg(a["D_o"], a["t"], a["E"], a["S_allow"], a["delta"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: pipe_expansion_stress
# ---------------------------------------------------------------------------

_expansion_stress_spec = ToolSpec(
    name="pipe_expansion_stress",
    description=(
        "Perform a simplified two-anchor expansion stress check using the "
        "guided-cantilever method per ASME B31.3 Appendix D / Kellogg.\n"
        "\n"
        "For each leg the bending stress from its absorbed displacement is:\n"
        "  σ_i = 3·E·I·δ_i / (L_i²·Z)\n"
        "Total expansion stress (SRSS): σ_E = √(σ_x² + σ_y² + σ_z²)\n"
        "Pass condition: σ_E ≤ S_allow\n"
        "\n"
        "Parameters:\n"
        "  delta_x, delta_y, delta_z — displacements per direction (m, ≥ 0)\n"
        "  L_x, L_y                  — absorbing leg lengths (m, > 0)\n"
        "  E, D_o, t                 — pipe material and geometry\n"
        "  S_allow                   — allowable expansion stress range (Pa)\n"
        "\n"
        "Returns computed stresses, pass/fail, and safety factor.\n"
        "Issues a warning if σ_E > S_allow.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "delta_x": {
                "type": "number",
                "description": "Displacement absorbed by leg L_x (m). Must be >= 0.",
            },
            "delta_y": {
                "type": "number",
                "description": "Displacement absorbed by leg L_y (m). Must be >= 0.",
            },
            "delta_z": {
                "type": "number",
                "description": "Out-of-plane displacement (m). Use 0 for 2D. Must be >= 0.",
            },
            "L_x": {
                "type": "number",
                "description": "Length of leg in x-direction (m). Must be > 0.",
            },
            "L_y": {
                "type": "number",
                "description": "Length of leg in y-direction (m). Must be > 0.",
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa). Must be > 0.",
            },
            "D_o": {
                "type": "number",
                "description": "Pipe outside diameter (m). Must be > 0.",
            },
            "t": {
                "type": "number",
                "description": "Pipe wall thickness (m). Must be > 0 and < D_o/2.",
            },
            "S_allow": {
                "type": "number",
                "description": "Allowable expansion stress range (Pa). Must be > 0.",
            },
        },
        "required": ["delta_x", "delta_y", "delta_z", "L_x", "L_y", "E", "D_o", "t", "S_allow"],
    },
)


@register(_expansion_stress_spec, write=False)
async def run_pipe_expansion_stress(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("delta_x", "delta_y", "delta_z", "L_x", "L_y", "E", "D_o", "t", "S_allow"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = expansion_stress_check(
        a["delta_x"], a["delta_y"], a["delta_z"],
        a["L_x"], a["L_y"],
        a["E"], a["D_o"], a["t"], a["S_allow"],
    )
    return ok_payload(result) if result["ok"] else json.dumps(result)
