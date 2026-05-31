"""
kerf_cad_core.arch.slab_deflection_tools — LLM tool: arch_compute_slab_deflection.

Registers one tool with the Kerf tool registry:

  arch_compute_slab_deflection — compute center-point deflection δ_max and
                                  maximum moments M_xx / M_yy for a two-way
                                  rectangular concrete slab under uniform load,
                                  using Kirchhoff thin-plate theory.

Boundary conditions supported:
  • simply_supported — all four edges simply supported (AESS).
  • fixed_fixed      — all four edges fully fixed (AEFC).

Reference: Timoshenko & Woinowsky-Krieger 2e §44 Tables 41–42; Roark 9e Table 11.4.
Formula:   δ = α · q · a⁴ / D;  D = E·h³ / (12·(1−ν²))

All plan dimensions in **millimetres**, load in **kPa**, stiffness in **N·mm**.
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

from kerf_cad_core.arch.slab_deflection import (
    SlabSpec,
    LoadSpec,
    compute_slab_deflection,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _slab_deflection_spec = ToolSpec(
        name="arch_compute_slab_deflection",
        description=(
            "Compute center-point deflection δ_max and maximum bending moments "
            "M_xx / M_yy for a two-way rectangular concrete slab under uniform load "
            "(UDL) using Kirchhoff thin-plate theory.\n\n"
            "Supported boundary conditions:\n"
            "  • simply_supported — all four edges simply supported (AESS); "
            "α from Timoshenko Table 41.\n"
            "  • fixed_fixed — all four edges fully fixed (AEFC); "
            "α from Timoshenko Table 42 (a/b=1 exact; others approximate).\n\n"
            "Formula: δ_max = α · q · a⁴ / D\n"
            "  a = shorter plan span [mm], D = E·h³/(12·(1−ν²)) [N·mm].\n\n"
            "All plan dimensions in mm; load in kPa; stiffness D in N·mm; "
            "moments in N·mm/mm.\n"
            "Returns delta_max_mm, M_max_xx_Nmm_per_mm, M_max_yy_Nmm_per_mm, "
            "plate_stiffness_D, and an honest_caveat.\n\n"
            "SCOPE: linear-elastic Kirchhoff thin plate only. "
            "NOT included: shear deformation (Mindlin), plastic hinges, "
            "concrete cracking, creep/shrinkage, punching shear."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "length_a_mm": {
                    "type": "number",
                    "description": (
                        "Length of one side of the slab in mm. Must be > 0. "
                        "Example: 5000 for a 5 m span."
                    ),
                },
                "width_b_mm": {
                    "type": "number",
                    "description": (
                        "Length of the perpendicular side of the slab in mm. "
                        "Must be > 0. The shorter dimension is automatically used "
                        "as span a (Timoshenko convention)."
                    ),
                },
                "thickness_h_mm": {
                    "type": "number",
                    "description": (
                        "Slab thickness h in mm. Must be > 0. "
                        "Typical RC slab: 150–300 mm."
                    ),
                },
                "E_MPa": {
                    "type": "number",
                    "description": (
                        "Elastic modulus in MPa. "
                        "Typical concrete: 25 000–35 000 MPa "
                        "(C25/30: ~31 000; C30/37: ~33 000; C40/50: ~35 000). "
                        "Default 30 000 MPa."
                    ),
                },
                "poisson": {
                    "type": "number",
                    "description": (
                        "Poisson's ratio ν. Concrete: 0.2 (Eurocode 2; ACI 318-19). "
                        "Default 0.2."
                    ),
                },
                "udl_kPa": {
                    "type": "number",
                    "description": (
                        "Uniform distributed load in kPa (kN/m²). Must be ≥ 0. "
                        "Typical: self-weight + imposed = 5–15 kPa."
                    ),
                },
                "edge_condition": {
                    "type": "string",
                    "enum": ["simply_supported", "fixed_fixed"],
                    "description": (
                        "'simply_supported' — all four edges pinned (rotation free). "
                        "'fixed_fixed' — all four edges encastré (zero rotation)."
                    ),
                },
            },
            "required": [
                "length_a_mm",
                "width_b_mm",
                "thickness_h_mm",
                "udl_kPa",
                "edge_condition",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_slab_deflection_spec, write=False)
    async def run_arch_compute_slab_deflection(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = ["length_a_mm", "width_b_mm", "thickness_h_mm",
                           "udl_kPa", "edge_condition"]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            slab = SlabSpec(
                length_a_mm=float(a["length_a_mm"]),
                width_b_mm=float(a["width_b_mm"]),
                thickness_h_mm=float(a["thickness_h_mm"]),
                E_MPa=float(a.get("E_MPa", 30_000.0)),
                poisson=float(a.get("poisson", 0.2)),
            )
            load = LoadSpec(
                udl_kPa=float(a["udl_kPa"]),
                edge_condition=str(a["edge_condition"]),
            )
            report = compute_slab_deflection(slab, load)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "delta_max_mm": round(report.delta_max_mm, 6),
                "location": report.location,
                "M_max_xx_Nmm_per_mm": round(report.M_max_xx_Nmm_per_mm, 3),
                "M_max_yy_Nmm_per_mm": round(report.M_max_yy_Nmm_per_mm, 3),
                "plate_stiffness_D": round(report.plate_stiffness_D, 2),
                "honest_caveat": report.honest_caveat,
            }
        )
