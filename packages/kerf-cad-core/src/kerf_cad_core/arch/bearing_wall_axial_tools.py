"""
kerf_cad_core.arch.bearing_wall_axial_tools — LLM tool: arch_check_bearing_wall_axial.

Registers one tool with the Kerf tool registry:

  arch_check_bearing_wall_axial — check axial-load capacity of a plain concrete or
                                   masonry bearing wall per:
                                     ACI 318-19 §11.5.3.1 (empirical: φPn = 0.55·φ·f'c·Ag·[1−(k·lc/(32·t))²])
                                     TMS 402-22 §8.3 Eq 8-22 (masonry: φPn = φ·0.80·f'm·Ag·[1−(h_eff/(140·r))²])
                                   Returns phi_Pn_kN_per_m, slenderness_factor, dcr, adequate,
                                   governing_check, honest_caveat.

Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

References:
  ACI 318-19 §11.5.3.1.
  TMS 402-22 §8.3 Eq 8-22.
  Wight J.K. (2019) Reinforced Concrete: Mechanics and Design 8e §13.13.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.bearing_wall_axial import (
    BearingWallSpec,
    check_bearing_wall,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _wall_spec = ToolSpec(
        name="arch_check_bearing_wall_axial",
        description=(
            "Check axial-load capacity of a plain concrete, reinforced concrete, "
            "or masonry bearing wall.\n\n"
            "ACI 318-19 §11.5.3.1 (concrete/RC — empirical method):\n"
            "  φ·Pn = 0.55·φ·f'c·Ag·[1 − (k·lc/(32·t))²]\n"
            "  Valid when e ≤ t/6 (small eccentricity bound). "
            "k: fixed_fixed=0.8, pin_pin=1.0, cantilever=2.0.\n\n"
            "TMS 402-22 §8.3 Eq 8-22 (clay_masonry / concrete_masonry):\n"
            "  r = t/√12; h_eff = k·h; C_s = 1 − (h_eff/(140·r))² (valid h_eff/r ≤ 99).\n"
            "  φ·Pn = φ·0.80·f'm·Ag·C_s\n\n"
            "Returns phi_Pn_kN_per_m, slenderness_factor, dcr, adequate, "
            "governing_check, honest_caveat.\n\n"
            "SCOPE: ACI §11.5.3.1 EMPIRICAL method only. Large eccentricity (e>t/6) "
            "requires full PM interaction (ACI §11.4). Reinforcement NOT credited in "
            "ACI §11.5.3.1. TMS Eq 8-22 valid for h_eff/r ≤ 99 only. "
            "No in-plane shear (ACI §11.6). All inputs in mm and MPa; force in kN/m."
        ),
        input_schema={
            "type": "object",
            "required": [
                "wall_thickness_t_mm",
                "wall_height_h_mm",
                "wall_length_lw_m",
                "material",
                "f_prime_MPa",
                "P_factored_kN_per_m",
            ],
            "properties": {
                "wall_thickness_t_mm": {
                    "type": "number",
                    "description": "Wall thickness t (mm). Must be > 0.",
                },
                "wall_height_h_mm": {
                    "type": "number",
                    "description": (
                        "Clear storey height h between supports (mm). Must be > 0. "
                        "Governs slenderness and empirical φPn."
                    ),
                },
                "wall_length_lw_m": {
                    "type": "number",
                    "description": (
                        "Horizontal plan length of wall (m). Informational. Must be > 0."
                    ),
                },
                "material": {
                    "type": "string",
                    "enum": [
                        "concrete",
                        "reinforced_concrete",
                        "clay_masonry",
                        "concrete_masonry",
                    ],
                    "description": (
                        "Wall material. 'concrete'/'reinforced_concrete' use ACI §11.5.3.1; "
                        "'clay_masonry'/'concrete_masonry' use TMS 402-22 §8.3 Eq 8-22."
                    ),
                },
                "f_prime_MPa": {
                    "type": "number",
                    "description": (
                        "Compressive strength (MPa): f'c for concrete/RC, f'm for masonry. "
                        "Must be > 0."
                    ),
                },
                "P_factored_kN_per_m": {
                    "type": "number",
                    "description": (
                        "Factored axial compressive demand per unit wall width (kN/m). "
                        "Must be >= 0."
                    ),
                },
                "As_per_m": {
                    "type": "number",
                    "description": (
                        "Vertical reinforcement area (mm²/m). Default 0. "
                        "NOTE: NOT credited in ACI §11.5.3.1 empirical formula."
                    ),
                },
                "fy_MPa": {
                    "type": "number",
                    "description": (
                        "Steel yield strength (MPa). Default 420. "
                        "Informational only in ACI §11.5.3.1 method."
                    ),
                },
                "end_conditions": {
                    "type": "string",
                    "enum": ["fixed_fixed", "pin_pin", "cantilever"],
                    "description": (
                        "End conditions. fixed_fixed→k=0.8 (ACI Commentary R11.5.3.1); "
                        "pin_pin→k=1.0; cantilever→k=2.0."
                    ),
                },
                "eccentricity_e_mm": {
                    "type": "number",
                    "description": (
                        "Load eccentricity from wall centroid (mm). Default 0. "
                        "ACI §11.5.3.1 requires e ≤ t/6. If e > t/6, formula is not "
                        "applicable; governing_check = 'large_eccentricity_method_required'."
                    ),
                },
                "phi": {
                    "type": "number",
                    "description": (
                        "Strength-reduction factor φ. Default 0.65 "
                        "(ACI 318-19 Table 21.2.2 compression-controlled)."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_wall_spec, write=False)
    async def run_arch_check_bearing_wall_axial(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "wall_thickness_t_mm",
            "wall_height_h_mm",
            "wall_length_lw_m",
            "material",
            "f_prime_MPa",
            "P_factored_kN_per_m",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = BearingWallSpec(
                wall_thickness_t_mm=float(a["wall_thickness_t_mm"]),
                wall_height_h_mm=float(a["wall_height_h_mm"]),
                wall_length_lw_m=float(a["wall_length_lw_m"]),
                material=str(a["material"]),
                f_prime_MPa=float(a["f_prime_MPa"]),
                As_per_m=float(a.get("As_per_m", 0.0)),
                fy_MPa=float(a.get("fy_MPa", 420.0)),
                end_conditions=str(a.get("end_conditions", "pin_pin")),
                eccentricity_e_mm=float(a.get("eccentricity_e_mm", 0.0)),
            )
            P_factored = float(a["P_factored_kN_per_m"])
            phi = float(a.get("phi", 0.65))
            report = check_bearing_wall(spec, P_factored, phi=phi)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "phi_Pn_kN_per_m": round(report.phi_Pn_kN_per_m, 3),
                "slenderness_factor": round(report.slenderness_factor, 6),
                "dcr": round(report.dcr, 6) if report.dcr != float("inf") else "inf",
                "adequate": report.adequate,
                "governing_check": report.governing_check,
                "honest_caveat": report.honest_caveat,
            }
        )
