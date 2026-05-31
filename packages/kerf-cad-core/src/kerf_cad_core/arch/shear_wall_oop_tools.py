"""
kerf_cad_core.arch.shear_wall_oop_tools — LLM tool: arch_check_shear_wall_oop.

Registers one tool with the Kerf tool registry:

  arch_check_shear_wall_oop — check out-of-plane (OOP) flexural capacity of a
                              reinforced concrete shear wall under combined axial
                              and lateral (wind/seismic) loads per:
                                ACI 318-19 §11.5.3 (slenderness: h/t ≤ 30)
                                ACI 318-19 §11.7.5 (empirical axial: φPn)
                                ACI 318-19 §22.3   (OOP flexure: φMn)
                              Bresler linear interaction DCR = Pu/φPn + Mu/φMn.

Returns slenderness_h_over_t, slenderness_ok, phi_Pn_kN_per_m, phi_Mn_kNm_per_m,
        interaction_dcr, adequate, governing_check, honest_caveat.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

References:
  ACI 318-19 §11.5.3, §11.7.5, §22.3.
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

from kerf_cad_core.arch.shear_wall_oop import (
    ShearWallSpec,
    check_shear_wall_oop,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _oop_spec = ToolSpec(
        name="arch_check_shear_wall_oop",
        description=(
            "Check out-of-plane (OOP) flexural capacity of a reinforced concrete "
            "shear wall under combined axial load and lateral (wind/seismic) moment.\n\n"
            "Checks performed (per ACI 318-19):\n"
            "  1. Slenderness: h/t ≤ 30 (ACI §11.5.3)\n"
            "  2. Empirical axial: φPn = 0.55·φ·f'c·Ag·[1−(k·h/(32·t))²] "
            "(ACI §11.7.5.1; k=0.8 default fixed-fixed)\n"
            "  3. OOP flexure: rectangular stress block, unit-strip "
            "(ACI §22.3; both faces of steel); "
            "a=(As_total·fy)/(0.85·f'c·b); φMn=φ·As_total·fy·(d−a/2)\n"
            "  4. Bresler linear interaction: DCR = Pu/φPn + Mu/φMn ≤ 1.0\n\n"
            "Returns slenderness_h_over_t, slenderness_ok, phi_Pn_kN_per_m, "
            "phi_Mn_kNm_per_m, interaction_dcr, adequate, governing_check, honest_caveat.\n\n"
            "SCOPE: Empirical ACI §11.7.5 only — NOT the slender-wall moment-magnifier "
            "(ACI §11.8 / §6.7.3). No P-delta. No biaxial bending. No in-plane shear "
            "(ACI §11.6/§18.10). Bresler linear interaction approximation. "
            "All inputs in mm and MPa; force in kN/m; moment in kNm/m."
        ),
        input_schema={
            "type": "object",
            "required": [
                "wall_thickness_t_mm",
                "wall_height_h_mm",
                "wall_length_lw_mm",
                "fc_MPa",
                "fy_MPa",
                "As_each_face_mm2_per_m",
                "axial_load_Pu_kN_per_m",
                "oop_moment_Mu_kNm_per_m",
            ],
            "properties": {
                "wall_thickness_t_mm": {
                    "type": "number",
                    "description": "Wall thickness t (mm).  Must be > 0.",
                },
                "wall_height_h_mm": {
                    "type": "number",
                    "description": (
                        "Clear storey height h between lateral supports (mm). "
                        "Must be > 0.  Governs slenderness h/t and empirical φPn."
                    ),
                },
                "wall_length_lw_mm": {
                    "type": "number",
                    "description": (
                        "Horizontal plan length of wall lw (mm). "
                        "Informational — in-plane shear not checked here. "
                        "Must be > 0."
                    ),
                },
                "fc_MPa": {
                    "type": "number",
                    "description": "Concrete compressive strength f'c (MPa).  Must be > 0.",
                },
                "fy_MPa": {
                    "type": "number",
                    "description": "Steel yield strength (MPa), e.g. 420.  Must be > 0.",
                },
                "As_each_face_mm2_per_m": {
                    "type": "number",
                    "description": (
                        "Vertical reinforcement area on each face (mm²/m of wall width). "
                        "Total steel for OOP flexure = 2 × this value. "
                        "Must be ≥ 0."
                    ),
                },
                "axial_load_Pu_kN_per_m": {
                    "type": "number",
                    "description": (
                        "Factored axial compressive load per unit wall width (kN/m). "
                        "Must be ≥ 0.  Tensile uplift not supported."
                    ),
                },
                "oop_moment_Mu_kNm_per_m": {
                    "type": "number",
                    "description": (
                        "Factored out-of-plane bending moment demand per unit width "
                        "(kNm/m).  Must be ≥ 0."
                    ),
                },
                "k_factor": {
                    "type": "number",
                    "description": (
                        "ACI §11.7.5.1 effective-height factor k. "
                        "Default 0.8 (restrained top + bottom against rotation). "
                        "Use 1.0 for cantilever walls (free top)."
                    ),
                },
                "cover_mm": {
                    "type": "number",
                    "description": (
                        "Clear concrete cover to reinforcement (mm). "
                        "Default 25 mm.  Used to compute effective depth d."
                    ),
                },
                "bar_spacing_mm": {
                    "type": "number",
                    "description": (
                        "Assumed vertical bar spacing for effective-depth back-calculation (mm). "
                        "Default 200 mm."
                    ),
                },
                "phi": {
                    "type": "number",
                    "description": (
                        "ACI strength-reduction factor φ for compression-controlled walls. "
                        "Default 0.65 per ACI 318-19 Table 21.2.2."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_oop_spec, write=False)
    async def run_arch_check_shear_wall_oop(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "wall_thickness_t_mm",
            "wall_height_h_mm",
            "wall_length_lw_mm",
            "fc_MPa",
            "fy_MPa",
            "As_each_face_mm2_per_m",
            "axial_load_Pu_kN_per_m",
            "oop_moment_Mu_kNm_per_m",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = ShearWallSpec(
                wall_thickness_t_mm=float(a["wall_thickness_t_mm"]),
                wall_height_h_mm=float(a["wall_height_h_mm"]),
                wall_length_lw_mm=float(a["wall_length_lw_mm"]),
                fc_MPa=float(a["fc_MPa"]),
                fy_MPa=float(a["fy_MPa"]),
                As_each_face_mm2_per_m=float(a["As_each_face_mm2_per_m"]),
                axial_load_Pu_kN_per_m=float(a["axial_load_Pu_kN_per_m"]),
                oop_moment_Mu_kNm_per_m=float(a["oop_moment_Mu_kNm_per_m"]),
                k_factor=float(a.get("k_factor", 0.8)),
                cover_mm=float(a.get("cover_mm", 25.0)),
                bar_spacing_mm=float(a.get("bar_spacing_mm", 200.0)),
            )
            phi = float(a.get("phi", 0.65))
            report = check_shear_wall_oop(spec, phi=phi)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "slenderness_h_over_t": round(report.slenderness_h_over_t, 3),
                "slenderness_ok": report.slenderness_ok,
                "phi_Pn_kN_per_m": round(report.phi_Pn_kN_per_m, 3),
                "phi_Mn_kNm_per_m": round(report.phi_Mn_kNm_per_m, 4),
                "interaction_dcr": round(report.interaction_dcr, 6),
                "adequate": report.adequate,
                "governing_check": report.governing_check,
                "honest_caveat": report.honest_caveat,
            }
        )
