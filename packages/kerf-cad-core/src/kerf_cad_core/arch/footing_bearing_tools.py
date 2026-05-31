"""
kerf_cad_core.arch.footing_bearing_tools — LLM tool: arch_compute_bearing_capacity.

Registers one tool with the Kerf tool registry:

  arch_compute_bearing_capacity — compute ultimate and allowable bearing
                                   capacity of a shallow rectangular/square/
                                   circular/strip footing using the Meyerhof
                                   (1963) general bearing capacity equation.

References:
  Bowles J.E. (1996) Foundation Analysis and Design 5e §4.
  Das B.M. (2011) Principles of Foundation Engineering 8e §3.

All dimensions in SI: metres, kPa, kN/m³.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.footing_bearing import (
    SoilProperties,
    FootingSpec,
    compute_bearing_capacity,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _footing_spec = ToolSpec(
        name="arch_compute_bearing_capacity",
        description=(
            "Compute the ultimate and allowable bearing capacity of a shallow footing "
            "on cohesive/cohesionless soil using the Meyerhof (1963) general bearing "
            "capacity equation (Bowles 5e §4; Das 8e §3):\n\n"
            "  q_ult = c·N_c·s_c·d_c + γ·Df·N_q·s_q·d_q + 0.5·γ·B·N_γ·s_γ·d_γ\n\n"
            "Meyerhof N-factors:\n"
            "  N_q   = e^(π·tanφ) · tan²(45+φ/2)\n"
            "  N_c   = (N_q−1)·cotφ  (φ>0);  N_c = 5.14  (φ=0, Prandtl limit)\n"
            "  N_γ   = (N_q−1)·tan(1.4φ)\n\n"
            "Shape factors (Meyerhof 1963 / Bowles Table 4-4): "
            "strip=1.0; square/circular use B/L=1; rectangular interpolates.\n"
            "Depth factors (Meyerhof 1963 / Bowles Table 4-4): increase with Df/B.\n\n"
            "Returns q_ult_kPa, q_allow_kPa (= q_ult/FS), FS, N-factors, shape/depth "
            "factors, and an honest scope caveat.\n\n"
            "SCOPE: Meyerhof (1963) shape+depth factors only. "
            "No Brinch Hansen rigidity index (I_r) correction, no inclined/eccentric "
            "loads, no seismic or liquefaction correction, no layered-soil punching. "
            "All inputs in SI units: metres, kPa, kN/m³."
        ),
        input_schema={
            "type": "object",
            "properties": {
                # --- footing geometry ---
                "length_B_m": {
                    "type": "number",
                    "description": (
                        "Shorter plan dimension B in metres (width for rectangular; "
                        "side for square; diameter for circular). Must be > 0."
                    ),
                },
                "width_L_m": {
                    "type": "number",
                    "description": (
                        "Longer plan dimension L in metres. Must be ≥ B. "
                        "For square/circular footings may equal B. "
                        "Ignored for strip footings (only B matters)."
                    ),
                },
                "depth_Df_m": {
                    "type": "number",
                    "description": (
                        "Embedment depth Df in metres — measured from ground surface "
                        "to bottom of footing. Must be > 0. "
                        "Example: 1.5 for a footing 1.5 m below grade."
                    ),
                },
                "shape": {
                    "type": "string",
                    "enum": ["strip", "square", "circular", "rectangular"],
                    "description": (
                        "'strip' — very long footing (L/B → ∞); shape factors = 1. "
                        "'square' — equal sides (B = L). "
                        "'circular' — circular plan; diameter = B. "
                        "'rectangular' — general B × L (B < L)."
                    ),
                },
                # --- soil properties ---
                "cohesion_c_kPa": {
                    "type": "number",
                    "description": (
                        "Cohesion c in kPa. Use 0 for purely frictional soils (sand). "
                        "For saturated clay undrained (φ=0) analysis provide c = Su "
                        "(undrained shear strength). Must be ≥ 0."
                    ),
                },
                "friction_angle_phi_deg": {
                    "type": "number",
                    "description": (
                        "Angle of internal friction φ in degrees. Range [0, 50]. "
                        "Set 0 for undrained clay (φ_u = 0). "
                        "Typical: sand 30–38°; gravel 35–45°; clay 0–25°."
                    ),
                },
                "unit_weight_kN_m3": {
                    "type": "number",
                    "description": (
                        "Moist (or effective) unit weight γ in kN/m³. Must be > 0. "
                        "Typical: loose sand 16–18; dense sand 18–20; clay 17–21; "
                        "submerged (γ') ≈ 8–12."
                    ),
                },
                # --- optional ---
                "factor_of_safety": {
                    "type": "number",
                    "description": (
                        "Factor of safety FS for allowable capacity = q_ult / FS. "
                        "Bowles §4-8 recommends 2.5–3.0 for static loads. "
                        "Default 3.0."
                    ),
                },
                "depth_factor_kf": {
                    "type": "number",
                    "description": (
                        "Optional scale factor on the surcharge term γ·Df. "
                        "Default 1.0.  Use < 1 for partially submerged conditions "
                        "or to match an effective-stress correction."
                    ),
                },
            },
            "required": [
                "length_B_m",
                "width_L_m",
                "depth_Df_m",
                "shape",
                "cohesion_c_kPa",
                "friction_angle_phi_deg",
                "unit_weight_kN_m3",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_footing_spec, write=False)
    async def run_arch_compute_bearing_capacity(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required = [
            "length_B_m", "width_L_m", "depth_Df_m", "shape",
            "cohesion_c_kPa", "friction_angle_phi_deg", "unit_weight_kN_m3",
        ]
        missing = [f for f in required if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            footing = FootingSpec(
                length_B_m=float(a["length_B_m"]),
                width_L_m=float(a["width_L_m"]),
                depth_Df_m=float(a["depth_Df_m"]),
                shape=str(a["shape"]),
            )
            soil = SoilProperties(
                cohesion_c_kPa=float(a["cohesion_c_kPa"]),
                friction_angle_phi_deg=float(a["friction_angle_phi_deg"]),
                unit_weight_kN_m3=float(a["unit_weight_kN_m3"]),
                depth_factor_kf=float(a.get("depth_factor_kf", 1.0)),
            )
            FS = float(a.get("factor_of_safety", 3.0))
            report = compute_bearing_capacity(footing, soil, FS=FS)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "q_ult_kPa": round(report.q_ult_kPa, 3),
                "q_allow_kPa": round(report.q_allow_kPa, 3),
                "factor_of_safety": report.factor_of_safety,
                "N_c": round(report.N_c, 4),
                "N_q": round(report.N_q, 4),
                "N_gamma": round(report.N_gamma, 4),
                "shape_factor_s_c": round(report.shape_factor_s_c, 4),
                "depth_factor_d_c": round(report.depth_factor_d_c, 4),
                "honest_caveat": report.honest_caveat,
            }
        )
