"""
kerf_cad_core.arch.pier_axial_capacity_tools — LLM tool: arch_check_pier_axial.

Registers one tool with the Kerf tool registry:

  arch_check_pier_axial — Check axial-load capacity of a slender masonry or reinforced
                          concrete pier per:
                            TMS 402-22 §8.3 (clay / concrete masonry)
                            ACI 318-19 §22.4.2.2 (reinforced concrete)
                          Includes TMS Eq 8-22 slenderness reduction factor
                          C_s = 1 − (h_eff/(140·r))² for h_eff/r ≤ 99.
                          Effective length h_eff = k·h per end conditions.

Returns phi_Pn_kN, slenderness_factor, h_over_r, governing_failure_mode,
        demand_capacity_ratio, adequate, honest_caveat.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

References:
  TMS 402-22 §8.3, Eq 8-22 (masonry pier axial + slenderness).
  ACI 318-19 §22.4.2.2 (RC short/slender column axial strength).
  Drysdale R.G. & Hamid A.A. (2005) Masonry Structures §10.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.pier_axial_capacity import (
    PierSpec,
    check_pier_axial,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _pier_axial_spec = ToolSpec(
        name="arch_check_pier_axial",
        description=(
            "Check axial-load capacity of a slender masonry or reinforced concrete pier "
            "under a given factored demand load.\n\n"
            "Supported material types:\n"
            "  • clay_masonry      — TMS 402-22 §8.3: φ·Pn = φ·0.80·f'm·Ag·C_s\n"
            "  • concrete_masonry  — TMS 402-22 §8.3: same formula\n"
            "  • reinforced_concrete — ACI 318-19 §22.4.2.2: "
            "φ·Pn = φ·0.80·[0.85·f'c·(Ag−As)+fy·As]·C_s\n\n"
            "Slenderness reduction (TMS Eq 8-22):\n"
            "  C_s = 1 − (h_eff / (140·r))²   for h_eff/r ≤ 99\n"
            "  h_eff/r > 99 → slenderness_limit_exceeded (φ·Pn returned as 0)\n\n"
            "Radius of gyration: r = min(pier_width, pier_thickness) / √12 "
            "(governing weak-axis r for rectangular section).\n\n"
            "Effective height: h_eff = k · h, where k depends on end_conditions:\n"
            "  fixed_fixed=0.5, pin_pin=1.0, fixed_pin=0.7, cantilever=2.0\n\n"
            "Returns phi_Pn_kN, slenderness_factor, h_over_r, governing_failure_mode "
            "(yielding|slender_buckling|slenderness_limit_exceeded), "
            "demand_capacity_ratio, adequate, honest_caveat.\n\n"
            "SCOPE: Concentric axial load ONLY — no eccentricity, no moment interaction, "
            "no PM curve. TMS Eq 8-22 valid for h_eff/r ≤ 99 only. "
            "All dimensions in mm; stresses/strengths in MPa; forces in kN."
        ),
        input_schema={
            "type": "object",
            "required": [
                "pier_width_mm",
                "pier_thickness_mm",
                "height_h_mm",
                "material",
                "f_prime_MPa",
                "end_conditions",
                "P_factored_kN",
            ],
            "properties": {
                "pier_width_mm": {
                    "type": "number",
                    "description": "Width of the pier cross-section in mm (in-plane dimension). Must be > 0.",
                },
                "pier_thickness_mm": {
                    "type": "number",
                    "description": (
                        "Thickness of the pier cross-section in mm (out-of-plane dimension). "
                        "Must be > 0."
                    ),
                },
                "height_h_mm": {
                    "type": "number",
                    "description": (
                        "Clear unsupported height of the pier in mm. "
                        "Must be > 0. Combined with k to give h_eff = k·h."
                    ),
                },
                "material": {
                    "type": "string",
                    "enum": ["clay_masonry", "concrete_masonry", "reinforced_concrete"],
                    "description": (
                        "Material type governing the capacity formula. "
                        "'clay_masonry' or 'concrete_masonry' → TMS 402-22 §8.3. "
                        "'reinforced_concrete' → ACI 318-19 §22.4.2.2."
                    ),
                },
                "f_prime_MPa": {
                    "type": "number",
                    "description": (
                        "Specified compressive strength in MPa. "
                        "For masonry: net f'm. "
                        "For RC: f'c (cylinder strength). "
                        "Must be > 0."
                    ),
                },
                "As_total_mm2": {
                    "type": "number",
                    "description": (
                        "Total longitudinal reinforcement area in mm². "
                        "Set to 0 for unreinforced masonry. "
                        "Required for reinforced_concrete. Default 0.0."
                    ),
                },
                "fy_MPa": {
                    "type": "number",
                    "description": (
                        "Yield strength of reinforcing steel in MPa (e.g. 420). "
                        "Required for reinforced_concrete. Default 420.0."
                    ),
                },
                "end_conditions": {
                    "type": "string",
                    "enum": ["fixed_fixed", "pin_pin", "fixed_pin", "cantilever"],
                    "description": (
                        "Boundary conditions at pier ends. "
                        "fixed_fixed → k=0.5 (both ends restrained against rotation). "
                        "pin_pin → k=1.0 (both ends pinned, default for typical piers). "
                        "fixed_pin → k=0.7 (one fixed, one pinned). "
                        "cantilever → k=2.0 (fixed base, free top)."
                    ),
                },
                "P_factored_kN": {
                    "type": "number",
                    "description": "Factored axial compressive demand Pu in kN. Must be ≥ 0.",
                },
                "phi": {
                    "type": "number",
                    "description": (
                        "Strength-reduction factor φ. "
                        "Default 0.65 (compression-controlled, TMS 402-22 §9.3 / ACI Table 21.2.2). "
                        "Must be in (0, 1]."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_pier_axial_spec, write=False)
    async def run_arch_check_pier_axial(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "pier_width_mm",
            "pier_thickness_mm",
            "height_h_mm",
            "material",
            "f_prime_MPa",
            "end_conditions",
            "P_factored_kN",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            pier = PierSpec(
                pier_width_mm=float(a["pier_width_mm"]),
                pier_thickness_mm=float(a["pier_thickness_mm"]),
                height_h_mm=float(a["height_h_mm"]),
                material=str(a["material"]),
                f_prime_MPa=float(a["f_prime_MPa"]),
                As_total_mm2=float(a.get("As_total_mm2", 0.0)),
                fy_MPa=float(a.get("fy_MPa", 420.0)),
                end_conditions=str(a["end_conditions"]),
            )
            P_kN = float(a["P_factored_kN"])
            phi = float(a.get("phi", 0.65))
            report = check_pier_axial(pier, P_kN, phi=phi)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        dcr = P_kN / report.phi_Pn_kN if report.phi_Pn_kN > 0 else float("inf")
        adequate = dcr <= 1.0 and report.governing_failure_mode != "slenderness_limit_exceeded"

        return ok_payload(
            {
                "phi_Pn_kN": report.phi_Pn_kN,
                "slenderness_factor": report.slenderness_factor,
                "h_over_r": report.h_over_r,
                "governing_failure_mode": report.governing_failure_mode,
                "demand_capacity_ratio": round(dcr, 4),
                "adequate": adequate,
                "honest_caveat": report.honest_caveat,
            }
        )
