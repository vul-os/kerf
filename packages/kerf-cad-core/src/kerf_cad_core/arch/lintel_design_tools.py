"""
kerf_cad_core.arch.lintel_design_tools — LLM tool: arch_design_lintel.

Registers one tool with the Kerf tool registry:

  arch_design_lintel — check a steel, reinforced-concrete, or reinforced-masonry
                        lintel over a wall opening for moment, shear, and deflection
                        capacity, including the triangular masonry arching load above
                        the opening (TMS 402-22 Commentary §5.3.1; BIA TN-31B).

References:
  AISC Manual Table 3-23; AISC 360-22 §F1/§G2.
  ACI 318-19 §9 (flexure), §22.5 (shear).
  TMS 402-22 §5 (lintel design), §9.3 (RM flexure/shear).
  Roark 9e §8 Table 8.1.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.lintel_design import (
    LintelSpec,
    design_lintel,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _lintel_design_spec = ToolSpec(
        name="arch_design_lintel",
        description=(
            "Check a lintel over a wall opening for moment, shear, and deflection capacity. "
            "Supports three material types: steel (AISC Manual Table 3-23 + AISC 360-22 §F1/§G2), "
            "reinforced_concrete (ACI 318-19 §9), and reinforced_masonry (TMS 402-22 §5). "
            "\n\nLoad model:"
            "\n  • Superimposed UDL factored: w_u = 1.2·DL + 1.6·LL (ASCE 7-16 §2.3.1 combo 2)."
            "\n  • Masonry arching action: when masonry_above_height ≥ L/2, only the 45° "
            "isoceles triangular load within the arching triangle is applied "
            "(TMS 402-22 Commentary §5.3.1; BIA TN-31B); otherwise full rectangular load."
            "\n\nCapacity:"
            "\n  • Steel: solid-rectangle section approximation (S_x=b·h²/6). "
            "φ·Mn = 0.90·Fy·S_x; φ·Vn = 1.00·0.6·Fy·0.5·b·h."
            "\n  • RC: ρ_max=0.018 estimate; φ·Mn = 0.90·As·fy·(d−a/2); "
            "φ·Vn = 0.75·0.17·√f'c·b·d (no stirrups)."
            "\n  • RM: ρ_max=0.010 estimate; φ·Mn = 0.90·As·fy·(d−a/2); "
            "φ·Vn = 0.80·A_n·√f'm/3."
            "\n\nDeflection limit: L/360 (floor_lintel=true) or L/240 (default, masonry/roof)."
            "\n\nReturns M_max, V_max, delta_max, phi_Mn, phi_Vn, moment_dcr, shear_dcr, "
            "deflection_ok, adequate, and an honest caveat."
            "\n\nSCOPE: Simple span ONLY. No continuous-beam moment redistribution. "
            "Steel LTB not checked. RC/RM rebar layout estimated from ρ_max. "
            "Load combo 1.2D+1.6L only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "opening_span_mm": {
                    "type": "number",
                    "description": (
                        "Clear span of the wall opening in mm. Must be > 0. "
                        "Example: 1200 for a 1.2 m door opening."
                    ),
                },
                "wall_thickness_mm": {
                    "type": "number",
                    "description": (
                        "Wall thickness in mm. Used for context; "
                        "lintel_width_mm governs section capacity. "
                        "Example: 230 mm for a standard CMU wall."
                    ),
                },
                "material": {
                    "type": "string",
                    "enum": ["steel", "reinforced_concrete", "reinforced_masonry"],
                    "description": (
                        "Lintel material type. "
                        "'steel' — angle, channel, or wide-flange shape; "
                        "fc_or_fy_MPa = Fy (yield stress). "
                        "'reinforced_concrete' — cast-in-place RC beam; "
                        "fc_or_fy_MPa = f'c. "
                        "'reinforced_masonry' — grouted RM lintel; "
                        "fc_or_fy_MPa = f'm."
                    ),
                },
                "lintel_depth_mm": {
                    "type": "number",
                    "description": (
                        "Overall depth of the lintel cross-section in mm. Must be > 0. "
                        "Steel: total section depth (e.g. 101.6 mm for L4×4×1/4). "
                        "RC/RM: total beam depth including cover."
                    ),
                },
                "lintel_width_mm": {
                    "type": "number",
                    "description": (
                        "Width of the lintel cross-section in mm. Must be > 0. "
                        "Steel: flange width (or combined angle leg width). "
                        "RC/RM: beam width (typically equals wall_thickness_mm). "
                        "Example: 101.6 mm for L4×4×1/4 back-to-back, "
                        "230 mm for CMU RM lintel."
                    ),
                },
                "fc_or_fy_MPa": {
                    "type": "number",
                    "description": (
                        "Material strength in MPa. Must be > 0. "
                        "Steel → Fy: 250 (A36), 345 (A992). "
                        "Reinforced concrete → f'c: 21, 28, 35 MPa. "
                        "Reinforced masonry → f'm: 10, 14, 20 MPa."
                    ),
                },
                "dead_load_kN_per_m": {
                    "type": "number",
                    "description": (
                        "Service dead load (superimposed, excluding masonry self-weight) "
                        "in kN/m. Must be ≥ 0. Example: 5 kN/m for floor framing above."
                    ),
                },
                "live_load_kN_per_m": {
                    "type": "number",
                    "description": (
                        "Service live load in kN/m. Must be ≥ 0. "
                        "Example: 3 kN/m."
                    ),
                },
                "masonry_above_height_mm": {
                    "type": "number",
                    "description": (
                        "Height of masonry above the lintel (to floor/beam/slab above) in mm. "
                        "0 → no masonry self-weight. "
                        "> 0 → arching action applies per TMS 402-22 Commentary §5.3.1: "
                        "if h_masonry ≥ L/2, 45° triangular load only; "
                        "if h_masonry < L/2, full rectangular UDL from masonry weight. "
                        "Example: 2400 mm for a storey of masonry."
                    ),
                },
                "floor_lintel": {
                    "type": "boolean",
                    "description": (
                        "True if the lintel supports a floor (deflection limit L/360). "
                        "False (default) if supporting roof or masonry wall (limit L/240). "
                        "Omit for the default L/240 limit."
                    ),
                },
            },
            "required": [
                "opening_span_mm",
                "wall_thickness_mm",
                "material",
                "lintel_depth_mm",
                "lintel_width_mm",
                "fc_or_fy_MPa",
                "dead_load_kN_per_m",
                "live_load_kN_per_m",
                "masonry_above_height_mm",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_lintel_design_spec, write=False)
    async def run_arch_design_lintel(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "opening_span_mm", "wall_thickness_mm", "material",
            "lintel_depth_mm", "lintel_width_mm", "fc_or_fy_MPa",
            "dead_load_kN_per_m", "live_load_kN_per_m", "masonry_above_height_mm",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = LintelSpec(
                opening_span_mm=float(a["opening_span_mm"]),
                wall_thickness_mm=float(a["wall_thickness_mm"]),
                material=str(a["material"]),
                lintel_depth_mm=float(a["lintel_depth_mm"]),
                lintel_width_mm=float(a["lintel_width_mm"]),
                fc_or_fy_MPa=float(a["fc_or_fy_MPa"]),
                dead_load_kN_per_m=float(a["dead_load_kN_per_m"]),
                live_load_kN_per_m=float(a["live_load_kN_per_m"]),
                masonry_above_height_mm=float(a["masonry_above_height_mm"]),
                floor_lintel=bool(a.get("floor_lintel", False)),
            )
            report = design_lintel(spec)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "M_max_kNm": report.M_max_kNm,
                "V_max_kN": report.V_max_kN,
                "delta_max_mm": report.delta_max_mm,
                "phi_Mn_kNm": report.phi_Mn_kNm,
                "phi_Vn_kN": report.phi_Vn_kN,
                "moment_dcr": report.moment_dcr,
                "shear_dcr": report.shear_dcr,
                "deflection_ok": report.deflection_ok,
                "adequate": report.adequate,
                "honest_caveat": report.honest_caveat,
            }
        )
