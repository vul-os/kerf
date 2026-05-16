"""
kerf_cad_core.thermocycle.tools — LLM tool wrappers for thermodynamic cycle analysis.

Registers tools with the Kerf tool registry:

  thermo_isentropic_relations     — T/p/v isentropic ideal-gas relations
  thermo_isothermal_process       — isothermal p-V-T, work, heat
  thermo_isobaric_process         — isobaric p-V-T, work, heat
  thermo_isochoric_process        — isochoric p-V-T, work, heat
  thermo_isentropic_process       — isentropic compression/expansion
  thermo_polytropic_process       — polytropic p·v^n = const
  thermo_carnot_efficiency        — Carnot heat-engine efficiency
  thermo_carnot_cop_refrigeration — reverse-Carnot refrigeration COP
  thermo_carnot_cop_heat_pump     — reverse-Carnot heat-pump COP
  thermo_otto_cycle               — air-standard Otto cycle
  thermo_diesel_cycle             — air-standard Diesel cycle
  thermo_dual_cycle               — air-standard Dual (mixed) cycle
  thermo_brayton_cycle            — Brayton cycle with optional regeneration
  thermo_rankine_cycle_ideal      — simplified ideal Rankine (steam) cycle
  thermo_refrigeration_cop        — refrigeration/heat-pump COP from Q_L, W_in

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Cengel, Y.A. & Boles, M.A., "Thermodynamics: An Engineering Approach", 8th ed.
Moran, M.J. et al., "Fundamentals of Engineering Thermodynamics", 7th ed.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.thermocycle.cycles import (
    isentropic_relations,
    isothermal_process,
    isobaric_process,
    isochoric_process,
    isentropic_process,
    polytropic_process,
    carnot_efficiency,
    carnot_cop_refrigeration,
    carnot_cop_heat_pump,
    otto_cycle,
    diesel_cycle,
    dual_cycle,
    brayton_cycle,
    rankine_cycle_ideal,
    refrigeration_cop,
)


# ---------------------------------------------------------------------------
# Tool: thermo_isentropic_relations
# ---------------------------------------------------------------------------

_isentropic_relations_spec = ToolSpec(
    name="thermo_isentropic_relations",
    description=(
        "Isentropic relations for an ideal gas with constant specific-heat ratio k.\n"
        "\n"
        "Computes unknown state-2 property from one pair of inputs:\n"
        "    T2/T1 = (p2/p1)^((k-1)/k)\n"
        "    T2/T1 = (v1/v2)^(k-1)\n"
        "    p2/p1 = (v1/v2)^k\n"
        "\n"
        "Provide T1, p1 and then one of: T2, p2, or (v1+v2).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T1": {"type": "number", "description": "Initial temperature (K). Must be > 0."},
            "p1": {"type": "number", "description": "Initial pressure (Pa). Must be > 0."},
            "T2": {"type": "number", "description": "Final temperature (K). Optional."},
            "p2": {"type": "number", "description": "Final pressure (Pa). Optional."},
            "v1": {"type": "number", "description": "Specific volume at state 1 (m³/kg). Optional."},
            "v2": {"type": "number", "description": "Specific volume at state 2 (m³/kg). Optional."},
            "k":  {"type": "number", "description": "Specific heat ratio k (default 1.4 for air)."},
        },
        "required": ["T1", "p1"],
    },
)


@register(_isentropic_relations_spec, write=False)
async def run_isentropic_relations(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T1", "p1"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("T2", "p2", "v1", "v2", "k"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = isentropic_relations(a["T1"], a["p1"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_isothermal_process
# ---------------------------------------------------------------------------

_isothermal_spec = ToolSpec(
    name="thermo_isothermal_process",
    description=(
        "Isothermal (constant-temperature) process for an ideal gas.\n"
        "\n"
        "    p·v = const   →   p2 = p1·v1/v2\n"
        "    w = p1·v1 · ln(v2/v1)   [J/kg]\n"
        "    q = w   (since Δu = 0 at constant T)\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "p1": {"type": "number", "description": "Initial pressure (Pa). Must be > 0."},
            "v1": {"type": "number", "description": "Initial specific volume (m³/kg). Must be > 0."},
            "v2": {"type": "number", "description": "Final specific volume (m³/kg). Must be > 0."},
            "T":  {"type": "number", "description": "Temperature (K). Optional; used to compute R·T."},
        },
        "required": ["p1", "v1", "v2"],
    },
)


@register(_isothermal_spec, write=False)
async def run_isothermal_process(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("p1", "v1", "v2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "T" in a:
        kwargs["T"] = a["T"]

    result = isothermal_process(a["p1"], a["v1"], a["v2"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_isobaric_process
# ---------------------------------------------------------------------------

_isobaric_spec = ToolSpec(
    name="thermo_isobaric_process",
    description=(
        "Isobaric (constant-pressure) process for an ideal gas.\n"
        "\n"
        "    q  = cp · (T2 - T1)   [J/kg]\n"
        "    w  = R  · (T2 - T1)   [J/kg]  (boundary work)\n"
        "    Δu = cv · (T2 - T1)   [J/kg]\n"
        "\n"
        "Default cp = 1005 J/kg·K (air). k = 1.4 assumed for deriving cv.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T1": {"type": "number", "description": "Initial temperature (K). Must be > 0."},
            "T2": {"type": "number", "description": "Final temperature (K). Must be > 0."},
            "cp": {"type": "number", "description": "Specific heat at constant pressure (J/kg·K). Default 1005 J/kg·K."},
        },
        "required": ["T1", "T2"],
    },
)


@register(_isobaric_spec, write=False)
async def run_isobaric_process(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T1", "T2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "cp" in a:
        kwargs["cp"] = a["cp"]

    result = isobaric_process(a["T1"], a["T2"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_isochoric_process
# ---------------------------------------------------------------------------

_isochoric_spec = ToolSpec(
    name="thermo_isochoric_process",
    description=(
        "Isochoric (constant-volume) process for an ideal gas.\n"
        "\n"
        "    q  = cv · (T2 - T1)   [J/kg]\n"
        "    w  = 0                 (no boundary work)\n"
        "    Δu = q\n"
        "\n"
        "Default cv = 717.86 J/kg·K (air).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T1": {"type": "number", "description": "Initial temperature (K). Must be > 0."},
            "T2": {"type": "number", "description": "Final temperature (K). Must be > 0."},
            "cv": {"type": "number", "description": "Specific heat at constant volume (J/kg·K). Default 717.86 J/kg·K."},
        },
        "required": ["T1", "T2"],
    },
)


@register(_isochoric_spec, write=False)
async def run_isochoric_process(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T1", "T2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "cv" in a:
        kwargs["cv"] = a["cv"]

    result = isochoric_process(a["T1"], a["T2"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_isentropic_process
# ---------------------------------------------------------------------------

_isentropic_proc_spec = ToolSpec(
    name="thermo_isentropic_process",
    description=(
        "Isentropic (adiabatic, reversible) compression or expansion.\n"
        "\n"
        "    T2/T1 = (p2/p1)^((k-1)/k)\n"
        "    w_s   = cp · (T1 - T2)   [J/kg]  (positive = work output / expansion)\n"
        "    q     = 0\n"
        "\n"
        "Default k=1.4, cp=1005 J/kg·K (air).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T1": {"type": "number", "description": "Initial temperature (K). Must be > 0."},
            "p1": {"type": "number", "description": "Initial pressure (Pa). Must be > 0."},
            "p2": {"type": "number", "description": "Final pressure (Pa). Must be > 0."},
            "k":  {"type": "number", "description": "Specific heat ratio (default 1.4)."},
            "cp": {"type": "number", "description": "cp (J/kg·K). Default 1005."},
        },
        "required": ["T1", "p1", "p2"],
    },
)


@register(_isentropic_proc_spec, write=False)
async def run_isentropic_process(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T1", "p1", "p2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("k", "cp"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = isentropic_process(a["T1"], a["p1"], a["p2"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_polytropic_process
# ---------------------------------------------------------------------------

_polytropic_spec = ToolSpec(
    name="thermo_polytropic_process",
    description=(
        "Polytropic process: p · v^n = const.\n"
        "\n"
        "    p2   = p1 · (v1/v2)^n\n"
        "    w    = (p2·v2 - p1·v1) / (1 - n)   [J/kg]  for n ≠ 1\n"
        "    w    = p1·v1 · ln(v2/v1)            [J/kg]  for n = 1\n"
        "    q    = Δu + w\n"
        "\n"
        "Special cases: n=0 isobaric, n=1 isothermal, n=1.4 isentropic (air),\n"
        "               n→∞ isochoric (use large n e.g. 1e9).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "p1": {"type": "number", "description": "Initial pressure (Pa). Must be > 0."},
            "v1": {"type": "number", "description": "Initial specific volume (m³/kg). Must be > 0."},
            "v2": {"type": "number", "description": "Final specific volume (m³/kg). Must be > 0."},
            "n":  {"type": "number", "description": "Polytropic index."},
            "T1": {"type": "number", "description": "Initial temperature (K). Optional; used to compute T2."},
        },
        "required": ["p1", "v1", "v2", "n"],
    },
)


@register(_polytropic_spec, write=False)
async def run_polytropic_process(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("p1", "v1", "v2", "n"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "T1" in a:
        kwargs["T1"] = a["T1"]

    result = polytropic_process(a["p1"], a["v1"], a["v2"], a["n"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_carnot_efficiency
# ---------------------------------------------------------------------------

_carnot_eff_spec = ToolSpec(
    name="thermo_carnot_efficiency",
    description=(
        "Maximum (Carnot) thermal efficiency of a heat engine.\n"
        "\n"
        "    η_Carnot = 1 - T_L / T_H\n"
        "\n"
        "This is the upper bound for ANY heat engine operating between T_H and T_L.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_H": {"type": "number", "description": "High-temperature reservoir (K). Must be > T_L > 0."},
            "T_L": {"type": "number", "description": "Low-temperature reservoir (K). Must be > 0."},
        },
        "required": ["T_H", "T_L"],
    },
)


@register(_carnot_eff_spec, write=False)
async def run_carnot_efficiency(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_H", "T_L"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = carnot_efficiency(a["T_H"], a["T_L"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_carnot_cop_refrigeration
# ---------------------------------------------------------------------------

_carnot_cop_r_spec = ToolSpec(
    name="thermo_carnot_cop_refrigeration",
    description=(
        "Maximum (reverse-Carnot) COP for a refrigeration cycle.\n"
        "\n"
        "    COP_R = T_L / (T_H - T_L)\n"
        "\n"
        "This is the theoretical upper bound for a refrigerator between T_H and T_L.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_H": {"type": "number", "description": "High-temperature reservoir (K). Must be > T_L > 0."},
            "T_L": {"type": "number", "description": "Low-temperature reservoir (K). Must be > 0."},
        },
        "required": ["T_H", "T_L"],
    },
)


@register(_carnot_cop_r_spec, write=False)
async def run_carnot_cop_refrigeration(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_H", "T_L"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = carnot_cop_refrigeration(a["T_H"], a["T_L"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_carnot_cop_heat_pump
# ---------------------------------------------------------------------------

_carnot_cop_hp_spec = ToolSpec(
    name="thermo_carnot_cop_heat_pump",
    description=(
        "Maximum (reverse-Carnot) COP for a heat-pump cycle.\n"
        "\n"
        "    COP_HP = T_H / (T_H - T_L)  = 1 + COP_R\n"
        "\n"
        "Always > 1 for T_H > T_L > 0.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_H": {"type": "number", "description": "High-temperature reservoir (K). Must be > T_L > 0."},
            "T_L": {"type": "number", "description": "Low-temperature source (K). Must be > 0."},
        },
        "required": ["T_H", "T_L"],
    },
)


@register(_carnot_cop_hp_spec, write=False)
async def run_carnot_cop_heat_pump(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_H", "T_L"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = carnot_cop_heat_pump(a["T_H"], a["T_L"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_otto_cycle
# ---------------------------------------------------------------------------

_otto_spec = ToolSpec(
    name="thermo_otto_cycle",
    description=(
        "Air-standard Otto cycle (ideal spark-ignition engine).\n"
        "\n"
        "    η_Otto = 1 - 1/r^(k-1)\n"
        "    T2 = T1 · r^(k-1)   (end of isentropic compression)\n"
        "    T4 = T3 / r^(k-1)   (end of isentropic expansion)\n"
        "    w_net = cv · (T3-T2) - cv · (T4-T1)   [J/kg]\n"
        "\n"
        "Issues a warning if computed efficiency exceeds Carnot limit.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r":  {"type": "number", "description": "Compression ratio v1/v2. Must be > 1."},
            "T1": {"type": "number", "description": "Temperature at state 1 / BDC inlet (K). Must be > 0."},
            "T3": {"type": "number", "description": "Peak temperature at state 3 (after heat addition) (K). Must be > T2."},
            "k":  {"type": "number", "description": "Specific heat ratio (default 1.4)."},
            "cp": {"type": "number", "description": "cp (J/kg·K). Default 1005."},
            "cv": {"type": "number", "description": "cv (J/kg·K). Default 717.86."},
        },
        "required": ["r", "T1", "T3"],
    },
)


@register(_otto_spec, write=False)
async def run_otto_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r", "T1", "T3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("k", "cp", "cv"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = otto_cycle(a["r"], a["T1"], a["T3"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_diesel_cycle
# ---------------------------------------------------------------------------

_diesel_spec = ToolSpec(
    name="thermo_diesel_cycle",
    description=(
        "Air-standard Diesel cycle (ideal compression-ignition engine).\n"
        "\n"
        "    r   = v1/v2  (compression ratio)\n"
        "    r_c = v3/v2  (cutoff ratio; v3 = volume at end of heat addition)\n"
        "    η_Diesel = 1 - (r_c^k - 1) / (k · r^(k-1) · (r_c - 1))\n"
        "\n"
        "Issues a warning if computed efficiency exceeds Carnot limit.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r":   {"type": "number", "description": "Compression ratio v1/v2. Must be > 1."},
            "r_c": {"type": "number", "description": "Cutoff ratio v3/v2. Must be in (1, r)."},
            "T1":  {"type": "number", "description": "Temperature at state 1 (K). Must be > 0."},
            "k":   {"type": "number", "description": "Specific heat ratio (default 1.4)."},
            "cp":  {"type": "number", "description": "cp (J/kg·K). Default 1005."},
            "cv":  {"type": "number", "description": "cv (J/kg·K). Default 717.86."},
        },
        "required": ["r", "r_c", "T1"],
    },
)


@register(_diesel_spec, write=False)
async def run_diesel_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r", "r_c", "T1"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("k", "cp", "cv"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = diesel_cycle(a["r"], a["r_c"], a["T1"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_dual_cycle
# ---------------------------------------------------------------------------

_dual_spec = ToolSpec(
    name="thermo_dual_cycle",
    description=(
        "Air-standard Dual (mixed) cycle.\n"
        "\n"
        "Heat is added partly at constant volume (pressure ratio r_p)\n"
        "and partly at constant pressure (cutoff ratio r_c).\n"
        "Reduces to Otto when r_c=1; to Diesel when r_p=1.\n"
        "\n"
        "States: 1 BDC → 2 TDC (isentropic compression) → 3 const-V addition\n"
        "        → 4 const-P addition → 5 BDC (isentropic expansion).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r":   {"type": "number", "description": "Compression ratio v1/v2. Must be > 1."},
            "r_p": {"type": "number", "description": "Pressure ratio at const-V addition p3/p2. Must be >= 1."},
            "r_c": {"type": "number", "description": "Cutoff ratio v4/v3. Must be >= 1."},
            "T1":  {"type": "number", "description": "Temperature at state 1 (K). Must be > 0."},
            "k":   {"type": "number", "description": "Specific heat ratio (default 1.4)."},
            "cp":  {"type": "number", "description": "cp (J/kg·K). Default 1005."},
            "cv":  {"type": "number", "description": "cv (J/kg·K). Default 717.86."},
        },
        "required": ["r", "r_p", "r_c", "T1"],
    },
)


@register(_dual_spec, write=False)
async def run_dual_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r", "r_p", "r_c", "T1"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("k", "cp", "cv"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = dual_cycle(a["r"], a["r_p"], a["r_c"], a["T1"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_brayton_cycle
# ---------------------------------------------------------------------------

_brayton_spec = ToolSpec(
    name="thermo_brayton_cycle",
    description=(
        "Air-standard Brayton cycle (gas-turbine cycle).\n"
        "\n"
        "Supports ideal (eta_c=eta_t=1) or with isentropic component efficiencies,\n"
        "and optional regeneration (recuperator pre-heats compressed air with\n"
        "turbine exhaust).\n"
        "\n"
        "    w_net = w_t - w_c\n"
        "    η = w_net / q_in\n"
        "    BWR = w_c / w_t   (back-work ratio; typically 40-80% for gas turbines)\n"
        "\n"
        "Issues a warning if computed efficiency exceeds Carnot limit.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r_p":      {"type": "number", "description": "Pressure ratio p2/p1. Must be > 1."},
            "T1":       {"type": "number", "description": "Compressor inlet temperature (K). Must be > 0."},
            "T3":       {"type": "number", "description": "Turbine inlet temperature (K). Must be > T2."},
            "k":        {"type": "number", "description": "Specific heat ratio (default 1.4)."},
            "cp":       {"type": "number", "description": "cp (J/kg·K). Default 1005."},
            "eta_c":    {"type": "number", "description": "Isentropic efficiency of compressor (0,1]. Default 1.0."},
            "eta_t":    {"type": "number", "description": "Isentropic efficiency of turbine (0,1]. Default 1.0."},
            "eta_regen":{"type": "number", "description": "Regenerator effectiveness [0,1). 0 = no regeneration (default)."},
        },
        "required": ["r_p", "T1", "T3"],
    },
)


@register(_brayton_spec, write=False)
async def run_brayton_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r_p", "T1", "T3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("k", "cp", "eta_c", "eta_t", "eta_regen"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = brayton_cycle(a["r_p"], a["T1"], a["T3"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_rankine_cycle_ideal
# ---------------------------------------------------------------------------

_rankine_spec = ToolSpec(
    name="thermo_rankine_cycle_ideal",
    description=(
        "Simplified ideal Rankine (steam) cycle — parametric engineering estimates.\n"
        "\n"
        "Uses an Antoine-form saturation temperature approximation (valid ~10 kPa–10 MPa).\n"
        "NOT a substitute for IAPWS-IF97 tables; use for cycle selection and "
        "preliminary design.\n"
        "\n"
        "Supports:\n"
        "  • Saturated or superheated steam at turbine inlet\n"
        "  • Pump and turbine isentropic efficiencies\n"
        "  • Single reheat stage\n"
        "  • Open feedwater heater count (informational note)\n"
        "\n"
        "Issues a warning if computed efficiency exceeds Carnot limit.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "p_high": {
                "type": "number",
                "description": "Boiler / high-side pressure (Pa). Must be > p_low.",
            },
            "p_low": {
                "type": "number",
                "description": "Condenser / low-side pressure (Pa). Must be > 0.",
            },
            "T_superheat": {
                "type": "number",
                "description": (
                    "Turbine inlet temperature (K) for superheated steam. "
                    "Omit or set null for saturated vapour at p_high."
                ),
            },
            "eta_pump": {
                "type": "number",
                "description": "Isentropic pump efficiency (0,1]. Default 1.0.",
            },
            "eta_turbine": {
                "type": "number",
                "description": "Isentropic turbine efficiency (0,1]. Default 1.0.",
            },
            "T_reheat": {
                "type": "number",
                "description": "Reheat temperature (K) at p_reheat. Omit = no reheat.",
            },
            "p_reheat": {
                "type": "number",
                "description": "Reheat pressure (Pa). Required when T_reheat is given.",
            },
            "n_feedwater_heaters": {
                "type": "integer",
                "description": "Number of open feedwater heaters (0-3). Informational only.",
            },
        },
        "required": ["p_high", "p_low"],
    },
)


@register(_rankine_spec, write=False)
async def run_rankine_cycle_ideal(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("p_high", "p_low"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    T_sup = a.get("T_superheat")  # may be None
    for opt in ("eta_pump", "eta_turbine", "T_reheat", "p_reheat", "n_feedwater_heaters"):
        if opt in a and a[opt] is not None:
            kwargs[opt] = a[opt]

    result = rankine_cycle_ideal(a["p_high"], a["p_low"], T_sup, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: thermo_refrigeration_cop
# ---------------------------------------------------------------------------

_refrig_cop_spec = ToolSpec(
    name="thermo_refrigeration_cop",
    description=(
        "Coefficient of Performance (COP) for a refrigeration or heat-pump cycle.\n"
        "\n"
        "    COP_R  = Q_L / W_in           (refrigeration)\n"
        "    COP_HP = (Q_L + W_in) / W_in  (heat pump)\n"
        "    Q_H = Q_L + W_in\n"
        "\n"
        "If T_H and T_L are provided, the computed COP is compared against the\n"
        "reverse-Carnot limit; a warning is issued if COP > COP_Carnot.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_L":  {"type": "number", "description": "Heat removed from cold space per cycle (J or W). Must be > 0."},
            "W_in": {"type": "number", "description": "Net work input per cycle (J or W). Must be > 0."},
            "T_H":  {"type": "number", "description": "High-temperature reservoir (K). Optional; enables Carnot comparison."},
            "T_L":  {"type": "number", "description": "Low-temperature reservoir (K). Optional; enables Carnot comparison."},
            "mode": {
                "type": "string",
                "enum": ["refrigeration", "heat_pump"],
                "description": "'refrigeration' (default) or 'heat_pump'.",
            },
        },
        "required": ["Q_L", "W_in"],
    },
)


@register(_refrig_cop_spec, write=False)
async def run_refrigeration_cop(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q_L", "W_in"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("T_H", "T_L", "mode"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = refrigeration_cop(a["Q_L"], a["W_in"], **kwargs)
    return ok_payload(result)
