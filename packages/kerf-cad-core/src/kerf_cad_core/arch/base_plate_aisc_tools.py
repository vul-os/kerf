"""
kerf_cad_core.arch.base_plate_aisc_tools — LLM tool: arch_design_base_plate.

Registers one tool with the Kerf tool registry:

  arch_design_base_plate — AISC DG-1 §3.1 + AISC 360-22 §J8 steel column base
                            plate design for concentric axial compressive loads.

Returns plate dimensions B×N×t (mm), cantilever arms m/n, bearing check DCR,
and Murray-Stockwell thickness.

SCOPE: concentric axial load only.  Moment (DG-1 §3.2), anchor rod (§3.3–3.4),
and shear lug (§3.5) are NOT modelled.

References:
  AISC Design Guide 1, 2nd ed. §3.1 (Fisher & Kloiber 2006).
  AISC 360-22 §J8.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.base_plate_aisc import (
    ColumnSpec,
    ConcreteSpec,
    design_base_plate,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _base_plate_spec = ToolSpec(
        name="arch_design_base_plate",
        description=(
            "Design a steel column base plate for concentric axial compressive load "
            "per AISC Design Guide 1, 2nd ed. §3.1 + AISC 360-22 §J8.\n\n"
            "Concrete bearing strength (AISC 360-22 §J8 Eq J8-2):\n"
            "  Pp = 0.85·f'c·A1·√(A2/A1)   with A2/A1 ≤ 4\n"
            "  φ_c·Pp ≥ P_u   (φ_c = 0.65 default)\n\n"
            "Plate sizing: N ≈ B ≥ √(P_u/(φ_c·0.85·f'c·√(A2/A1))), "
            "rounded up to nearest 5 mm; must also cover column footprint "
            "(0.95·d × 0.80·bf).\n\n"
            "Cantilever dimensions (DG-1 §3.1.2):\n"
            "  m = (N − 0.95·d) / 2        [Eq 3.1-1]\n"
            "  n = (B − 0.80·bf) / 2       [Eq 3.1-2]\n"
            "  n' = √(d·bf) / 4\n"
            "  X = [4·d·bf/(d+bf)²]·[P_u/(φ_c·Pp)]\n"
            "  λ = min(1, 2·√X/(1+√(1-X)))  [Eq 3.1-8]\n"
            "  l = max(m, n, λ·n')\n\n"
            "Plate thickness (Murray-Stockwell, DG-1 Eq 3.1-5):\n"
            "  t = l · √(2·P_u / (0.9·Fy·B·N))\n\n"
            "Returns plate_B_mm, plate_N_mm, plate_thickness_t_mm, m_mm, n_mm, "
            "X_factor, plate_phi_Pn_kN, demand_capacity_ratio, adequate, "
            "and an honest scope caveat.\n\n"
            "SCOPE: concentric axial compressive load ONLY (DG-1 §3.1). "
            "NOT covered: moment transfer (DG-1 §3.2), anchor rod design "
            "(DG-1 §3.3–3.4), shear lug (DG-1 §3.5), biaxial bending, "
            "tensile uplift. All dimensions in mm; loads in kN; stress in MPa."
        ),
        input_schema={
            "type": "object",
            "properties": {
                # --- column properties ---
                "column_d_mm": {
                    "type": "number",
                    "description": (
                        "Overall depth d of the W-section in mm. "
                        "Example: W14x90 → d = 355.6 mm. Must be > 0."
                    ),
                },
                "column_bf_mm": {
                    "type": "number",
                    "description": (
                        "Flange width bf of the W-section in mm. "
                        "Example: W14x90 → bf = 368.3 mm. Must be > 0."
                    ),
                },
                "axial_load_kN": {
                    "type": "number",
                    "description": (
                        "Factored axial compressive demand P_u in kN (LRFD). "
                        "Must be > 0."
                    ),
                },
                # --- concrete properties ---
                "fc_MPa": {
                    "type": "number",
                    "description": (
                        "Concrete compressive strength f'c in MPa. "
                        "Typical: 21 MPa (3 000 psi), 28 MPa (4 000 psi), "
                        "35 MPa (5 000 psi). Must be > 0."
                    ),
                },
                "support_width_B_mm": {
                    "type": "number",
                    "description": (
                        "Width of the concrete pedestal or footing in mm "
                        "(direction parallel to plate B). Must be > 0."
                    ),
                },
                "support_length_L_mm": {
                    "type": "number",
                    "description": (
                        "Length of the concrete pedestal or footing in mm "
                        "(direction parallel to plate N). Must be > 0."
                    ),
                },
                # --- optional ---
                "phi_c": {
                    "type": "number",
                    "description": (
                        "Concrete bearing resistance factor φ_c. "
                        "AISC 360-22 §J8 default = 0.65."
                    ),
                },
                "Fy_MPa": {
                    "type": "number",
                    "description": (
                        "Plate steel yield stress Fy in MPa. "
                        "A36 = 250 MPa; A572 Gr 50 = 345 MPa (default)."
                    ),
                },
            },
            "required": [
                "column_d_mm",
                "column_bf_mm",
                "axial_load_kN",
                "fc_MPa",
                "support_width_B_mm",
                "support_length_L_mm",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_base_plate_spec, write=False)
    async def run_arch_design_base_plate(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required = [
            "column_d_mm", "column_bf_mm", "axial_load_kN",
            "fc_MPa", "support_width_B_mm", "support_length_L_mm",
        ]
        missing = [f for f in required if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            col = ColumnSpec(
                column_d_mm=float(a["column_d_mm"]),
                column_bf_mm=float(a["column_bf_mm"]),
                axial_load_kN=float(a["axial_load_kN"]),
            )
            conc = ConcreteSpec(
                fc_MPa=float(a["fc_MPa"]),
                support_width_B_mm=float(a["support_width_B_mm"]),
                support_length_L_mm=float(a["support_length_L_mm"]),
                phi_c=float(a.get("phi_c", 0.65)),
            )
            Fy = float(a.get("Fy_MPa", 345.0))
            report = design_base_plate(col, conc, Fy=Fy)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "plate_B_mm": round(report.plate_B_mm, 1),
                "plate_N_mm": round(report.plate_N_mm, 1),
                "plate_thickness_t_mm": round(report.plate_thickness_t_mm, 1),
                "m_mm": round(report.m_mm, 2),
                "n_mm": round(report.n_mm, 2),
                "X_factor": round(report.X_factor, 4),
                "plate_phi_Pn_kN": round(report.plate_phi_Pn_kN, 2),
                "demand_capacity_ratio": round(report.demand_capacity_ratio, 4),
                "adequate": report.adequate,
                "honest_caveat": report.honest_caveat,
            }
        )
