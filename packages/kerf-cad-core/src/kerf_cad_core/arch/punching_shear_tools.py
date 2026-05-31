"""
kerf_cad_core.arch.punching_shear_tools — LLM tool: arch_check_punching_shear.

Registers one tool with the Kerf tool registry:

  arch_check_punching_shear — check two-way (punching) shear capacity of a
                              flat concrete slab around a column per
                              ACI 318-19 §22.6 (no shear reinforcement).

Critical section perimeter b_0 at d/2 from column face.
vc = min(0.33·λ·√f'c, 0.17·(1+2/β_c)·λ·√f'c, 0.083·(α_s·d/b_0+2)·λ·√f'c)
φ·Vn = φ · vc · b_0 · d   (φ = 0.75 default)

Returns b_0_mm, vc_governing_MPa, phi_vc_kN, DCR, adequate, governing_eqn,
        honest_caveat.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

References:
  ACI 318-19 §22.6 Two-way shear strength.
  Wight J.K. (2019) Reinforced Concrete: Mechanics and Design 8e §13.10.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.punching_shear import (
    ColumnSlabSpec,
    check_punching_shear,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _punching_spec = ToolSpec(
        name="arch_check_punching_shear",
        description=(
            "Check two-way (punching) shear capacity of a flat concrete slab "
            "around a column per ACI 318-19 §22.6 (no shear reinforcement).\n\n"
            "Critical section: perimeter b_0 at d/2 from the column face "
            "(ACI 318-19 §22.6.4.1).\n\n"
            "Concrete shear stress vc = min of ACI §22.6.5.2 equations:\n"
            "  (a)  vc = 0.33 · λ · √f'c                        [basic]\n"
            "  (b)  vc = 0.17 · (1 + 2/β_c) · λ · √f'c          [aspect-ratio]\n"
            "  (c)  vc = 0.083 · (α_s · d/b_0 + 2) · λ · √f'c   [perimeter]\n\n"
            "Design strength: φ·Vn = φ · vc · b_0 · d   (φ = 0.75 default)\n\n"
            "Returns b_0_mm, vc_governing_MPa, phi_vc_kN, demand_capacity_ratio, "
            "adequate (bool), governing_eqn, and honest_caveat.\n\n"
            "SCOPE: No shear reinforcement (Vs = 0). No unbalanced-moment "
            "interaction. No slab openings/re-entrant corners. No axial load "
            "effect on vc. √f'c cap at √69 MPa not auto-enforced. "
            "Slab edge/corner: set alpha_s=30 (edge) or 20 (corner). "
            "All inputs in mm and MPa; force in kN."
        ),
        input_schema={
            "type": "object",
            "required": [
                "column_size_mm",
                "slab_thickness_mm",
                "fc_MPa",
                "effective_depth_d_mm",
                "column_shape",
                "V_applied_kN",
            ],
            "properties": {
                "column_size_mm": {
                    "type": "number",
                    "description": (
                        "Column side dimension for square columns (mm), or diameter "
                        "for circular columns, or short-side dimension for "
                        "rectangular columns.  Must be > 0."
                    ),
                },
                "slab_thickness_mm": {
                    "type": "number",
                    "description": "Overall slab thickness h (mm).  Must be > 0.",
                },
                "fc_MPa": {
                    "type": "number",
                    "description": (
                        "Specified compressive strength f'c (MPa).  Must be > 0. "
                        "ACI 318-19 §22.6.5.1 caps √f'c at √69 MPa ≈ 8.31 MPa "
                        "for normalweight concrete — ensure f'c ≤ 69 MPa for "
                        "code-compliant results."
                    ),
                },
                "effective_depth_d_mm": {
                    "type": "number",
                    "description": (
                        "Effective slab depth d (mm) to the centroid of the "
                        "tension reinforcement.  Must be > 0 and < slab_thickness_mm."
                    ),
                },
                "column_shape": {
                    "type": "string",
                    "enum": ["square", "rectangular", "circular"],
                    "description": (
                        "'square' — equal-sided column (β_c = 1). "
                        "'rectangular' — requires column_width_b_mm (long side). "
                        "'circular' — b_0 = π·(diameter + d)."
                    ),
                },
                "V_applied_kN": {
                    "type": "number",
                    "description": "Applied factored punching shear V_u (kN).  Must be ≥ 0.",
                },
                "column_width_b_mm": {
                    "type": "number",
                    "description": (
                        "Long-side dimension of a rectangular column (mm). "
                        "Required when column_shape == 'rectangular'. "
                        "Must be ≥ column_size_mm."
                    ),
                },
                "alpha_s": {
                    "type": "integer",
                    "enum": [40, 30, 20],
                    "description": (
                        "ACI α_s location factor: 40 = interior column (default), "
                        "30 = edge column, 20 = corner column "
                        "(ACI 318-19 §22.6.5.2c)."
                    ),
                },
                "lambda_factor": {
                    "type": "number",
                    "description": (
                        "Lightweight-concrete modification factor λ per "
                        "ACI 318-19 §19.2.4.  Default 1.0 (normalweight). "
                        "Use 0.75 for all-lightweight or 0.85 for sand-lightweight."
                    ),
                },
                "phi": {
                    "type": "number",
                    "description": (
                        "ACI strength-reduction factor for shear. "
                        "Default 0.75 per ACI 318-19 Table 21.2.1."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_punching_spec, write=False)
    async def run_arch_check_punching_shear(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "column_size_mm", "slab_thickness_mm", "fc_MPa",
            "effective_depth_d_mm", "column_shape", "V_applied_kN",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = ColumnSlabSpec(
                column_size_mm=float(a["column_size_mm"]),
                slab_thickness_mm=float(a["slab_thickness_mm"]),
                fc_MPa=float(a["fc_MPa"]),
                effective_depth_d_mm=float(a["effective_depth_d_mm"]),
                column_shape=str(a["column_shape"]),
                column_width_b_mm=(
                    float(a["column_width_b_mm"])
                    if a.get("column_width_b_mm") is not None
                    else None
                ),
                alpha_s=int(a.get("alpha_s", 40)),
                lambda_factor=float(a.get("lambda_factor", 1.0)),
            )
            V_applied_kN = float(a["V_applied_kN"])
            phi = float(a.get("phi", 0.75))
            report = check_punching_shear(spec, V_applied_kN, phi=phi)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "b_0_mm": round(report.b_0_mm, 2),
                "vc_basic_MPa": round(report.vc_basic_MPa, 6),
                "vc_aspect_MPa": round(report.vc_aspect_MPa, 6),
                "vc_perimeter_MPa": round(report.vc_perimeter_MPa, 6),
                "vc_governing_MPa": round(report.vc_governing_MPa, 6),
                "phi_vc_kN": round(report.phi_vc_kN, 3),
                "demand_capacity_ratio": round(report.demand_capacity_ratio, 6),
                "adequate": report.adequate,
                "governing_eqn": report.governing_eqn,
                "honest_caveat": report.honest_caveat,
            }
        )
