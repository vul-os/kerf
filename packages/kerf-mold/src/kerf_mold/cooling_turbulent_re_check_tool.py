"""
kerf_mold.cooling_turbulent_re_check_tool
==========================================
LLM tool wrapper for the cooling-channel Reynolds-number turbulence checker.

Registers:
  mold_check_turbulent_re — verify that a mold cooling channel operates in
      the fully-turbulent regime (Re ≥ 10 000) required for Dittus-Boelter
      heat-transfer correlation validity; flag laminar and transitional zones.
      (Beaumont 2007 §11; White "Fluid Mechanics" §8.1;
       Incropera & DeWitt eq. 8.60)

Errors returned as {"ok": false, "code": "...", "reason": "..."} — never
raises.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §11 (Cooling system design).
White F.M. "Fluid Mechanics", 8th ed., McGraw-Hill 2016,
  §8.1 (Reynolds number; laminar/turbulent thresholds).
Incropera F.P., DeWitt D.P. "Fundamentals of Heat and Mass Transfer",
  7th ed., Wiley 2011, §8.5 (Dittus-Boelter; Re ≥ 10 000 validity).
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.cooling_turbulent_re_check import (
    CoolingFlowSpec,
    check_turbulent_re,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_check_turbulent_re_spec = ToolSpec(
    name="mold_check_turbulent_re",
    description=(
        "Verify whether a mold cooling channel operates in the fully-turbulent "
        "flow regime required for effective heat transfer and Dittus-Boelter "
        "correlation validity (Beaumont 2007 §11; White \"Fluid Mechanics\" §8.1; "
        "Incropera & DeWitt eq. 8.60).\n\n"
        "Computes Re = ρ·v·D/μ and classifies flow:\n"
        "  Re < 2300              → laminar     (AVOID: very poor cooling; "
        "Dittus-Boelter NOT applicable)\n"
        "  2300 ≤ Re < 4000       → transitional (unpredictable; avoid)\n"
        "  4000 ≤ Re < 10000      → turbulent    (moderate cooling; Dittus-"
        "Boelter applies but h is sub-optimal)\n"
        "  Re ≥ 10000             → fully_turbulent (target for mold cooling; "
        "Dittus-Boelter applicable)\n\n"
        "Also returns the minimum flow rate [L/min] needed to reach Re = 10 000 "
        "for the given channel diameter and coolant properties.\n\n"
        "Returns: {ok, reynolds_number, flow_regime, velocity_m_per_s, "
        "recommended_min_flow_rate_L_per_min, dittus_boelter_applicable, "
        "honest_caveat}.\n\n"
        "Honest caveat: Re classification ONLY — does NOT compute Nusselt "
        "number / HTC (requires Prandtl number), polymer-side boundary layer, "
        "mold-steel wall resistance, or part-steel contact resistance; "
        "single-phase Newtonian fluid assumed (no two-phase / CO₂ cooling)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "channel_diameter_mm": {
                "type": "number",
                "description": (
                    "Internal (hydraulic) diameter of the circular cooling "
                    "channel [mm].  Must be > 0.  Typical mold cooling channels: "
                    "8–16 mm.  For non-circular channels supply the hydraulic "
                    "diameter D_h = 4·A/P."
                ),
            },
            "flow_rate_L_per_min": {
                "type": "number",
                "description": (
                    "Volumetric coolant flow rate through the channel [L/min].  "
                    "Must be > 0.  Typical mold cooling: 5–20 L/min."
                ),
            },
            "coolant_density_kg_m3": {
                "type": "number",
                "description": (
                    "Coolant density [kg/m³].  Default 1000.0 (water at ~20 °C).  "
                    "For 30 % ethylene-glycol/water use ~1040 kg/m³."
                ),
            },
            "coolant_viscosity_cP": {
                "type": "number",
                "description": (
                    "Coolant dynamic viscosity [centipoise].  "
                    "Default 1.0 cP (water at ~20 °C).  "
                    "For 30 % EG/water at 20 °C use ~2.0 cP.  "
                    "1 cP = 1e-3 Pa·s."
                ),
            },
        },
        "required": ["channel_diameter_mm", "flow_rate_L_per_min"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_check_turbulent_re(
    ctx: "ProjectCtx",
    args: bytes,
) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # --- channel_diameter_mm ---
    raw_d = a.get("channel_diameter_mm")
    if raw_d is None:
        return err_payload("channel_diameter_mm is required", "BAD_ARGS")
    try:
        diameter = float(raw_d)
    except (TypeError, ValueError) as exc:
        return err_payload(f"channel_diameter_mm: {exc}", "BAD_ARGS")

    # --- flow_rate_L_per_min ---
    raw_q = a.get("flow_rate_L_per_min")
    if raw_q is None:
        return err_payload("flow_rate_L_per_min is required", "BAD_ARGS")
    try:
        flow_rate = float(raw_q)
    except (TypeError, ValueError) as exc:
        return err_payload(f"flow_rate_L_per_min: {exc}", "BAD_ARGS")

    # --- optional coolant properties ---
    try:
        density = float(a.get("coolant_density_kg_m3", 1000.0))
    except (TypeError, ValueError) as exc:
        return err_payload(f"coolant_density_kg_m3: {exc}", "BAD_ARGS")

    try:
        viscosity = float(a.get("coolant_viscosity_cP", 1.0))
    except (TypeError, ValueError) as exc:
        return err_payload(f"coolant_viscosity_cP: {exc}", "BAD_ARGS")

    try:
        spec = CoolingFlowSpec(
            channel_diameter_mm=diameter,
            flow_rate_L_per_min=flow_rate,
            coolant_density_kg_m3=density,
            coolant_viscosity_cP=viscosity,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        report = check_turbulent_re(spec)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    return ok_payload({
        "ok": True,
        "reynolds_number": report.reynolds_number,
        "flow_regime": report.flow_regime,
        "velocity_m_per_s": report.velocity_m_per_s,
        "recommended_min_flow_rate_L_per_min": report.recommended_min_flow_rate_L_per_min,
        "dittus_boelter_applicable": report.dittus_boelter_applicable,
        "honest_caveat": report.honest_caveat,
    })
