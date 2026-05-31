"""
kerf_mold.cooling_pressure_drop_tool
======================================
LLM tool wrapper for the Darcy-Weisbach mold cooling-channel pressure-drop
calculator.

Registers:
  mold_compute_cooling_pressure_drop — total pressure drop across a
      multi-segment cooling-channel network (Darcy-Weisbach major losses +
      K-factor minor losses) and chiller pump head verification.
      (Beaumont 2007 §11.2; White "Fluid Mechanics" §6.7)

Errors returned as {"ok": false, "code": "...", "reason": "..."} — never
raises.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §11.2 (Cooling circuit hydraulics), Table 11.1.
White F.M. "Fluid Mechanics", 8th ed., McGraw-Hill 2016,
  §6.7 (Darcy-Weisbach), §6.9 (minor losses).
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.cooling_pressure_drop import (
    CoolingChannelSegment,
    CoolantSpec,
    compute_cooling_pressure_drop,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_cooling_pressure_drop_spec = ToolSpec(
    name="mold_compute_cooling_pressure_drop",
    description=(
        "Compute total pressure drop across a multi-segment injection-mold "
        "cooling-channel network using Darcy-Weisbach for straight runs and "
        "K-factor minor losses for fittings (Beaumont 2007 §11.2; White "
        "\"Fluid Mechanics\" §6.7).  Also verifies whether the chiller pump "
        "head is sufficient.\n\n"
        "Segment types and K-factors (Beaumont 2007 Table 11.1; White §6.9):\n"
        "  straight   → K=0.0  (Darcy-Weisbach only)\n"
        "  elbow_90   → K=0.9\n"
        "  elbow_45   → K=0.4\n"
        "  tee_thru   → K=0.6\n"
        "  tee_branch → K=1.8\n\n"
        "Friction-factor model (smooth pipe, White §6.7):\n"
        "  Re < 2300:   f = 64/Re  (Hagen-Poiseuille laminar)\n"
        "  Re > 4000:   f = 0.316/Re^0.25  (Blasius turbulent)\n"
        "  2300–4000:   linear interpolation (transitional, flagged in caveat)\n\n"
        "Pump head recommendation = total_ΔP × 1.25 (25 % design margin).\n\n"
        "Returns: {ok, total_pressure_drop_bar, reynolds_number, "
        "friction_factor, segment_breakdown, chiller_head_required_bar, "
        "recommended_pump_head_bar, honest_caveat}.\n\n"
        "Honest caveat: single-phase incompressible fluid only (water or "
        "water-glycol); no two-phase / boiling flow; no heat-transfer "
        "coupling (viscosity spatially uniform); smooth-pipe Blasius only "
        "(no Colebrook-White roughness correction); series network assumed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "description": (
                    "Ordered list of cooling-channel segments.  Each segment "
                    "is an object with:\n"
                    "  length_mm (number, >0),\n"
                    "  diameter_mm (number, >0),\n"
                    "  segment_type (string: 'straight'|'elbow_90'|"
                    "'elbow_45'|'tee_thru'|'tee_branch')."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "length_mm": {
                            "type": "number",
                            "description": "Segment length [mm].  Must be > 0.",
                        },
                        "diameter_mm": {
                            "type": "number",
                            "description": (
                                "Internal channel diameter [mm].  Must be > 0."
                            ),
                        },
                        "segment_type": {
                            "type": "string",
                            "enum": [
                                "straight",
                                "elbow_90",
                                "elbow_45",
                                "tee_thru",
                                "tee_branch",
                            ],
                            "description": "Pipe fitting type.",
                        },
                    },
                    "required": ["length_mm", "diameter_mm", "segment_type"],
                },
            },
            "flow_rate_L_per_min": {
                "type": "number",
                "description": (
                    "Total volumetric flow rate through the circuit [L/min].  "
                    "Must be > 0.  Typical mold cooling: 5–20 L/min."
                ),
            },
            "density_kg_m3": {
                "type": "number",
                "description": (
                    "Coolant density [kg/m³].  Default 1000 (water at ~20 °C).  "
                    "For 30 % ethylene-glycol/water use ~1040 kg/m³."
                ),
            },
            "viscosity_cP": {
                "type": "number",
                "description": (
                    "Coolant dynamic viscosity [centipoise].  "
                    "Default 1.0 cP (water at ~20 °C).  "
                    "For 30 % EG/water at 20 °C use ~2.0 cP."
                ),
            },
        },
        "required": ["segments", "flow_rate_L_per_min"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_compute_cooling_pressure_drop(
    ctx: "ProjectCtx",
    args: bytes,
) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

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
        density = float(a.get("density_kg_m3", 1000.0))
    except (TypeError, ValueError) as exc:
        return err_payload(f"density_kg_m3: {exc}", "BAD_ARGS")

    try:
        viscosity = float(a.get("viscosity_cP", 1.0))
    except (TypeError, ValueError) as exc:
        return err_payload(f"viscosity_cP: {exc}", "BAD_ARGS")

    try:
        coolant = CoolantSpec(
            flow_rate_L_per_min=flow_rate,
            density_kg_m3=density,
            viscosity_cP=viscosity,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    # --- segments ---
    raw_segs = a.get("segments")
    if raw_segs is None:
        return err_payload("segments is required", "BAD_ARGS")
    if not isinstance(raw_segs, list):
        return err_payload("segments must be a JSON array", "BAD_ARGS")
    if len(raw_segs) == 0:
        return err_payload("segments must contain at least one segment", "BAD_ARGS")

    segments = []
    for idx, raw in enumerate(raw_segs):
        if not isinstance(raw, dict):
            return err_payload(
                f"segments[{idx}] must be an object", "BAD_ARGS"
            )
        for field_name in ("length_mm", "diameter_mm", "segment_type"):
            if field_name not in raw:
                return err_payload(
                    f"segments[{idx}] missing required field '{field_name}'",
                    "BAD_ARGS",
                )
        try:
            seg = CoolingChannelSegment(
                length_mm=float(raw["length_mm"]),
                diameter_mm=float(raw["diameter_mm"]),
                segment_type=str(raw["segment_type"]),
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"segments[{idx}]: {exc}", "BAD_ARGS")
        segments.append(seg)

    try:
        report = compute_cooling_pressure_drop(segments, coolant)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    return ok_payload({
        "ok": True,
        "total_pressure_drop_bar": report.total_pressure_drop_bar,
        "reynolds_number": report.reynolds_number,
        "friction_factor": report.friction_factor,
        "segment_breakdown": report.segment_breakdown,
        "chiller_head_required_bar": report.chiller_head_required_bar,
        "recommended_pump_head_bar": report.recommended_pump_head_bar,
        "honest_caveat": report.honest_caveat,
    })
