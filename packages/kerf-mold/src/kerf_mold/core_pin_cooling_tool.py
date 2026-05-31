"""
kerf_mold.core_pin_cooling_tool
================================
LLM tool wrapper for the baffle/bubbler core-pin interior cooling designer.

Registers:
  mold_design_core_pin_cooling — design and verify a baffle or bubbler cooling
      circuit for a slender injection-mold core pin; compute Reynolds number,
      Dittus-Boelter HTC, estimated core-tip temperature, and cycle-time
      estimate.  (Menges 2001 §7.5 + Beaumont 2007 §11.4)

Errors returned as {"ok": false, "code": "...", "reason": "..."} — never
raises.

References
----------
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §7.5 (Core pin cooling; baffle vs. bubbler).
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §11.4 (Slender-core cooling; fountain effect HTC doubling).
Incropera F.P., DeWitt D.P. "Fundamentals of Heat and Mass Transfer",
  7th ed., Wiley 2011, §8.5 (Dittus-Boelter; eq. 8.60).
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.core_pin_cooling import (
    CorePinSpec,
    design_core_pin_cooling,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_design_core_pin_cooling_spec = ToolSpec(
    name="mold_design_core_pin_cooling",
    description=(
        "Design and verify a baffle or bubbler interior cooling circuit for a "
        "tall injection-mold core pin (slender rib cooling).\n\n"
        "Computes:\n"
        "  • Reynolds number Re = 4·Q·ρ/(π·D_h·μ) in the cooling bore\n"
        "  • Nusselt number Nu = 0.023·Re^0.8·Pr^0.4 (Dittus-Boelter; "
        "Incropera eq. 8.60)\n"
        "  • Convective HTC h = Nu·k_f/D_h [W/m²K]; bubbler ≈ 2× baffle "
        "(Menges 2001 §7.5; Beaumont 2007 §11.4)\n"
        "  • Estimated core-tip temperature from 1-D lumped resistance model "
        "(R_polymer + R_steel + R_coolant)\n"
        "  • Cooling adequacy flag (tip_temp ≤ target AND Re ≥ 10 000)\n"
        "  • Cycle-time estimate via Menges §7.3.3 1-D Fourier formula\n\n"
        "Returns: {ok, reynolds_number, htc_W_per_m2K, "
        "estimated_core_tip_temp_C, cooling_adequate, "
        "cycle_time_estimate_s, honest_caveat}.\n\n"
        "Honest caveat: lumped-capacitance steady-state ONLY — no transient "
        "FEA; uniform melt temperature assumed; bubbler multiplier is "
        "empirical; Dittus-Boelter valid only for Re ≥ 10 000 (L/D ≥ 10); "
        "polymer-side HTC fixed at 2000 W/m²K (Menges §7.1 midpoint). "
        "Confirm with Moldflow Insight / Moldex3D for production tooling."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "core_diameter_mm": {
                "type": "number",
                "description": (
                    "Outer diameter of the core pin [mm].  Must be > 0.  "
                    "Typical slender rib cores: 5–25 mm."
                ),
            },
            "core_height_mm": {
                "type": "number",
                "description": (
                    "Height (length) of the core pin above the parting line "
                    "[mm].  Must be > 0.  Typical tall cores: 50–200 mm."
                ),
            },
            "baffle_or_bubbler": {
                "type": "string",
                "enum": ["baffle", "bubbler"],
                "description": (
                    "'baffle' — longitudinal dividing plate in the central "
                    "bore; 'bubbler' — coaxial inner fountain tube.  Bubbler "
                    "approximately doubles the effective HTC (Menges 2001 §7.5)."
                ),
            },
            "cooling_type_id_mm": {
                "type": "number",
                "description": (
                    "Internal bore diameter of the cooling passage [mm].  "
                    "For baffle: the full bore ID.  For bubbler: the outer "
                    "bore ID.  Must be > 0 and < core_diameter_mm.  Typical "
                    "values: 3–8 mm for cores 10–30 mm OD."
                ),
            },
            "coolant_flow_L_per_min": {
                "type": "number",
                "description": (
                    "Volumetric coolant flow rate through the core pin "
                    "cooling circuit [L/min].  Must be > 0.  Typical: "
                    "0.5–5 L/min for small cores."
                ),
            },
            "melt_temp_C": {
                "type": "number",
                "description": (
                    "Polymer melt temperature at the gate [°C].  "
                    "Typical: ABS 230–260, PP 200–250, PA66 270–300."
                ),
            },
            "target_core_temp_C": {
                "type": "number",
                "description": (
                    "Target core pin temperature / part ejection temperature "
                    "[°C].  Must be < melt_temp_C.  Typical: 60–100 °C."
                ),
            },
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer grade identifier (informational only; used for "
                    "display / caveat — e.g. 'ABS', 'PP', 'PA66').  "
                    "Thermal diffusivity is fixed at ABS baseline "
                    "(1.0e-7 m²/s; Menges 2001 Table 7.3)."
                ),
            },
            "coolant_temp_C": {
                "type": "number",
                "description": (
                    "Coolant supply temperature [°C].  Default 20.0 "
                    "(typical chiller setpoint)."
                ),
            },
            "coolant_density_kg_m3": {
                "type": "number",
                "description": (
                    "Coolant density [kg/m³].  Default 1000.0 (water at "
                    "~20 °C).  For 30 % EG/water use ~1040 kg/m³."
                ),
            },
            "coolant_viscosity_Pa_s": {
                "type": "number",
                "description": (
                    "Coolant dynamic viscosity [Pa·s].  Default 1.0e-3 "
                    "(water at ~20 °C).  For 30 % EG/water use ~2.0e-3 Pa·s."
                ),
            },
            "coolant_Pr": {
                "type": "number",
                "description": (
                    "Coolant Prandtl number.  Default 7.0 (water at ~20 °C).  "
                    "For 30 % EG/water use ~10–12."
                ),
            },
            "coolant_k_W_m_K": {
                "type": "number",
                "description": (
                    "Coolant thermal conductivity [W/m·K].  Default 0.598 "
                    "(water at ~20 °C)."
                ),
            },
        },
        "required": [
            "core_diameter_mm",
            "core_height_mm",
            "baffle_or_bubbler",
            "cooling_type_id_mm",
            "coolant_flow_L_per_min",
            "melt_temp_C",
            "target_core_temp_C",
            "polymer_grade",
        ],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_design_core_pin_cooling(
    ctx: "ProjectCtx",
    args: bytes,
) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # --- Required fields ---
    required = [
        "core_diameter_mm",
        "core_height_mm",
        "baffle_or_bubbler",
        "cooling_type_id_mm",
        "coolant_flow_L_per_min",
        "melt_temp_C",
        "target_core_temp_C",
        "polymer_grade",
    ]
    for field_name in required:
        if a.get(field_name) is None:
            return err_payload(f"{field_name} is required", "BAD_ARGS")

    def _float(key: str, default=None):
        raw = a.get(key, default)
        if raw is None:
            return err_payload(f"{key} is required", "BAD_ARGS"), None
        try:
            return None, float(raw)
        except (TypeError, ValueError) as exc:
            return err_payload(f"{key}: {exc}", "BAD_ARGS"), None

    err, core_diameter_mm = _float("core_diameter_mm")
    if err:
        return err
    err, core_height_mm = _float("core_height_mm")
    if err:
        return err
    err, cooling_type_id_mm = _float("cooling_type_id_mm")
    if err:
        return err
    err, coolant_flow = _float("coolant_flow_L_per_min")
    if err:
        return err
    err, melt_temp = _float("melt_temp_C")
    if err:
        return err
    err, target_temp = _float("target_core_temp_C")
    if err:
        return err

    baffle_or_bubbler = a.get("baffle_or_bubbler", "")
    if not isinstance(baffle_or_bubbler, str):
        return err_payload("baffle_or_bubbler must be a string", "BAD_ARGS")

    polymer_grade = a.get("polymer_grade", "")
    if not isinstance(polymer_grade, str):
        return err_payload("polymer_grade must be a string", "BAD_ARGS")

    # --- Optional fields with defaults ---
    err, coolant_temp = _float("coolant_temp_C", 20.0)
    if err:
        return err
    err, coolant_density = _float("coolant_density_kg_m3", 1000.0)
    if err:
        return err
    err, coolant_visc = _float("coolant_viscosity_Pa_s", 1.0e-3)
    if err:
        return err
    err, coolant_pr = _float("coolant_Pr", 7.0)
    if err:
        return err
    err, coolant_k = _float("coolant_k_W_m_K", 0.598)
    if err:
        return err

    try:
        spec = CorePinSpec(
            core_diameter_mm=core_diameter_mm,
            core_height_mm=core_height_mm,
            baffle_or_bubbler=baffle_or_bubbler,
            cooling_type_id_mm=cooling_type_id_mm,
            coolant_flow_L_per_min=coolant_flow,
            melt_temp_C=melt_temp,
            target_core_temp_C=target_temp,
            polymer_grade=polymer_grade,
            coolant_temp_C=coolant_temp,
            coolant_density_kg_m3=coolant_density,
            coolant_viscosity_Pa_s=coolant_visc,
            coolant_Pr=coolant_pr,
            coolant_k_W_m_K=coolant_k,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        report = design_core_pin_cooling(spec)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    return ok_payload({
        "ok": True,
        "reynolds_number": report.reynolds_number,
        "htc_W_per_m2K": report.htc_W_per_m2K,
        "estimated_core_tip_temp_C": report.estimated_core_tip_temp_C,
        "cooling_adequate": report.cooling_adequate,
        "cycle_time_estimate_s": report.cycle_time_estimate_s,
        "honest_caveat": report.honest_caveat,
    })
