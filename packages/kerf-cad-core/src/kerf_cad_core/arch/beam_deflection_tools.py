"""
kerf_cad_core.arch.beam_deflection_tools — LLM tool: arch_compute_beam_deflection.

Registers one tool with the Kerf tool registry:

  arch_compute_beam_deflection — compute mid-span deflection δ_max, maximum
                                  bending moment M_max, and shear V_max for
                                  common architectural beam load cases.

Supported cases (Roark 9e §8 + AISC Manual Table 3-23):
  • simply_supported + point_center   δ = PL³/(48EI),     M = PL/4
  • simply_supported + udl            δ = 5wL⁴/(384EI),   M = wL²/8
  • cantilever      + point_center    δ = PL³/(3EI),      M = PL
  • cantilever      + udl             δ = wL⁴/(8EI),      M = wL²/2
  • fixed_fixed     + udl             δ = wL⁴/(384EI),    M = wL²/12

All dimensions in **millimetres**, forces in **Newtons**, stresses in **MPa**.
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

from kerf_cad_core.arch.beam_deflection import (
    BeamSpec,
    compute_beam_deflection,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _beam_deflection_spec = ToolSpec(
        name="arch_compute_beam_deflection",
        description=(
            "Compute mid-span deflection δ_max, maximum bending moment M_max, "
            "and maximum shear V_max for a single-span structural beam using "
            "closed-form Euler-Bernoulli formulas (Roark 9e §8 + AISC Manual Table 3-23). "
            "\n\nSupported load cases:"
            "\n  • simply_supported + point_center — point load P at mid-span; "
            "δ=PL³/(48EI), M=PL/4."
            "\n  • simply_supported + udl — uniform distributed load w over full span; "
            "δ=5wL⁴/(384EI), M=wL²/8."
            "\n  • cantilever + point_center — tip point load P; "
            "δ=PL³/(3EI), M=PL."
            "\n  • cantilever + udl — UDL over full cantilever; "
            "δ=wL⁴/(8EI), M=wL²/2."
            "\n  • fixed_fixed + udl — UDL on fully fixed beam; "
            "δ=wL⁴/(384EI), M=wL²/12 at supports."
            "\n\nAll dimensions in millimetres; forces in N; stresses in MPa. "
            "Returns δ_max_mm, M_max_Nmm, V_max_N, deflection_location_mm, "
            "and an honest caveat listing scope limits. "
            "Scope: linear-elastic, small-deflection only. "
            "No buckling, no yield, no shear deformation, no partial-span loads."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "length_mm": {
                    "type": "number",
                    "description": (
                        "Clear span length in mm. Must be > 0. "
                        "Example: 6000 for a 6 m span."
                    ),
                },
                "E_MPa": {
                    "type": "number",
                    "description": (
                        "Elastic (Young's) modulus in MPa. "
                        "Typical: 200 000 (steel), 70 000 (aluminium), "
                        "12 000–16 000 (LVL timber). Default 200 000 MPa."
                    ),
                },
                "I_mm4": {
                    "type": "number",
                    "description": (
                        "Second moment of area about the bending axis in mm⁴. "
                        "Example W14x90: I_x = 270 000 000 mm⁴ "
                        "(AISC v15 Table 1-1, Ix = 999 in⁴ ≈ 415 880 000 mm⁴ "
                        "— use section-specific value)."
                    ),
                },
                "support_type": {
                    "type": "string",
                    "enum": ["simply_supported", "cantilever", "fixed_fixed"],
                    "description": (
                        "'simply_supported' — pin at each end. "
                        "'cantilever' — fully fixed at one end, free at the other. "
                        "'fixed_fixed' — encastré at both ends."
                    ),
                },
                "load_type": {
                    "type": "string",
                    "enum": ["point_center", "udl"],
                    "description": (
                        "'point_center' — single point load P at mid-span "
                        "(or free tip for cantilever). "
                        "'udl' — uniform distributed load w (N/mm) over full span."
                    ),
                },
                "load_value": {
                    "type": "number",
                    "description": (
                        "Load magnitude. "
                        "For point_center: total point load P in N. "
                        "For udl: load intensity w in N/mm. "
                        "Must be ≥ 0. Example: 100 000 N = 100 kN; 5 N/mm = 5 kN/m."
                    ),
                },
            },
            "required": [
                "length_mm",
                "E_MPa",
                "I_mm4",
                "support_type",
                "load_type",
                "load_value",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_beam_deflection_spec, write=False)
    async def run_arch_compute_beam_deflection(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = ["length_mm", "E_MPa", "I_mm4", "support_type",
                           "load_type", "load_value"]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = BeamSpec(
                length_mm=float(a["length_mm"]),
                E_MPa=float(a.get("E_MPa", 200_000.0)),
                I_mm4=float(a["I_mm4"]),
                support_type=str(a["support_type"]),
                load_type=str(a["load_type"]),
                load_value=float(a["load_value"]),
            )
            report = compute_beam_deflection(spec)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "delta_max_mm": round(report.delta_max_mm, 6),
                "M_max_Nmm": round(report.M_max_Nmm, 3),
                "V_max_N": round(report.V_max_N, 3),
                "deflection_location_mm": round(report.deflection_location_mm, 3),
                "honest_caveat": report.honest_caveat,
            }
        )
