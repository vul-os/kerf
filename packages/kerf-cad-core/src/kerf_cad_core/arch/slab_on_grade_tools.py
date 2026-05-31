"""
kerf_cad_core.arch.slab_on_grade_tools — LLM tool: arch_check_slab_on_grade.

Registers one tool with the Kerf tool registry:

  arch_check_slab_on_grade — Check concrete slab-on-grade thickness adequacy
                             under a concentrated point or wheel load per
                             ACI 360R-10 / Westergaard (1948) interior load model.

Theory (PCA EB119 simplified Westergaard):
  l = [E·h³/(12·(1−ν²)·k)]^0.25   (radius of relative stiffness, mm)
  σ_max = 3·P·(1+ν)/(2·π·h²) · (log₁₀(l/b) + 0.5)   (interior load, MPa)
  MR = 0.62·√f'c   (modulus of rupture, MPa)
  DCR = σ_max / MR;   joint spacing ≤ 30·h (PCA rule)

Returns radius_of_relative_stiffness_l_mm, max_bending_stress_MPa,
        modulus_of_rupture_MR_MPa, dcr, adequate, recommended_joint_spacing_m,
        honest_caveat.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

References:
  Westergaard H.M. (1948) Trans. ASCE 113, 425–444.
  PCA EB119 (Ringo & Anderson 1996) §4.2.
  ACI 360R-10 §A2.1 (interior concentrated load).
  ACI 318-19 §19.2.2.1 (Ec), §19.2.3.1 (fr = MR).
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.slab_on_grade import (
    SlabOnGradeSpec,
    check_slab_on_grade,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _sog_spec = ToolSpec(
        name="arch_check_slab_on_grade",
        description=(
            "Check concrete slab-on-grade thickness adequacy under a concentrated "
            "point or wheel load per ACI 360R-10 / Westergaard (1948) interior load model.\n\n"
            "Theory (PCA EB119 simplified Westergaard):\n"
            "  l = [E·h³/(12·(1−ν²)·k)]^0.25   [radius of relative stiffness, mm]\n"
            "  σ_max = 3·P·(1+ν)/(2·π·h²)·(log₁₀(l/b)+0.5)   [interior load, MPa]\n"
            "  MR = 0.62·√f'c   [modulus of rupture, MPa]\n"
            "  DCR = σ_max / MR;   joint_spacing ≤ 30·h (PCA 30×h rule)\n\n"
            "Returns: radius_of_relative_stiffness_l_mm, max_bending_stress_MPa, "
            "modulus_of_rupture_MR_MPa, dcr, adequate (bool), "
            "recommended_joint_spacing_m, honest_caveat.\n\n"
            "SCOPE: Interior load only — edge / corner positions have higher stress "
            "(Westergaard 1948); thermal curling not modelled; single load; "
            "unreinforced/crack-control slab only. All inputs in mm and MPa; "
            "load in kN; k in MPa/m."
        ),
        input_schema={
            "type": "object",
            "required": [
                "slab_thickness_mm",
                "fc_MPa",
                "subgrade_modulus_k_MPa_per_m",
                "point_load_kN",
                "contact_radius_mm",
                "slab_long_dimension_m",
            ],
            "properties": {
                "slab_thickness_mm": {
                    "type": "number",
                    "description": (
                        "Slab thickness h (mm).  Must be > 0.  "
                        "Typical warehouse floors: 100–200 mm."
                    ),
                },
                "fc_MPa": {
                    "type": "number",
                    "description": (
                        "Specified compressive strength f'c (MPa).  Must be > 0.  "
                        "Typical slab-on-grade: 25–35 MPa."
                    ),
                },
                "subgrade_modulus_k_MPa_per_m": {
                    "type": "number",
                    "description": (
                        "Modulus of subgrade reaction k (MPa/m = kN/m³).  Must be > 0.  "
                        "Typical values: very soft ≈ 13–27 MPa/m; "
                        "medium ≈ 27–55 MPa/m; dense/stiff ≈ 55–110 MPa/m; "
                        "rock ≥ 140 MPa/m.  Obtained from ASTM D1196 plate-bearing test."
                    ),
                },
                "point_load_kN": {
                    "type": "number",
                    "description": (
                        "Applied concentrated or wheel load P (kN).  Must be > 0.  "
                        "For a multi-axle vehicle use the heaviest single wheel load."
                    ),
                },
                "contact_radius_mm": {
                    "type": "number",
                    "description": (
                        "Radius of load contact area (mm).  Must be > 0.  "
                        "For a circular tyre load: b = sqrt(P / (π·p_tyre)) "
                        "where p_tyre is tyre inflation pressure.  "
                        "For a square rigid pad of side a: b = sqrt(a²/π)."
                    ),
                },
                "slab_long_dimension_m": {
                    "type": "number",
                    "description": (
                        "Longer plan dimension of the slab panel (m).  Must be > 0.  "
                        "Used to contextualise the joint spacing recommendation."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_sog_spec, write=False)
    async def run_arch_check_slab_on_grade(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "slab_thickness_mm",
            "fc_MPa",
            "subgrade_modulus_k_MPa_per_m",
            "point_load_kN",
            "contact_radius_mm",
            "slab_long_dimension_m",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = SlabOnGradeSpec(
                slab_thickness_mm=float(a["slab_thickness_mm"]),
                fc_MPa=float(a["fc_MPa"]),
                subgrade_modulus_k_MPa_per_m=float(a["subgrade_modulus_k_MPa_per_m"]),
                point_load_kN=float(a["point_load_kN"]),
                contact_radius_mm=float(a["contact_radius_mm"]),
                slab_long_dimension_m=float(a["slab_long_dimension_m"]),
            )
            report = check_slab_on_grade(spec)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "radius_of_relative_stiffness_l_mm": round(
                    report.radius_of_relative_stiffness_l_mm, 2
                ),
                "max_bending_stress_MPa": round(report.max_bending_stress_MPa, 6),
                "modulus_of_rupture_MR_MPa": round(report.modulus_of_rupture_MR_MPa, 6),
                "dcr": round(report.dcr, 6),
                "adequate": report.adequate,
                "recommended_joint_spacing_m": round(
                    report.recommended_joint_spacing_m, 3
                ),
                "honest_caveat": report.honest_caveat,
            }
        )
