"""
kerf_cad_core.arch.lateral_bracing_check_tools — LLM tool: arch_check_lateral_bracing.

Registers one tool with the Kerf tool registry:

  arch_check_lateral_bracing — check whether lateral-torsional buckling (LTB)
                               governs for a compact doubly symmetric I-shaped
                               member under a given unbraced length, and compute
                               the LRFD design moment capacity per AISC 360-22 §F2.

Returns Lp, Lr, Mp, Mr, Mn, phi_Mn, governing_mode, and an honest caveat.

All dimensions in **millimetres** and **MPa**; moments in **kN·m**.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

Scope: doubly symmetric compact I-shaped members (W-shapes) only.
       Channels, tees, and built-up sections are out of scope (see §F5/F9/F10).
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.lateral_bracing_check import (
    WSectionSpec,
    check_lateral_bracing,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _ltb_spec = ToolSpec(
        name="arch_check_lateral_bracing",
        description=(
            "Check lateral-torsional buckling (LTB) for a compact doubly symmetric I-shaped "
            "steel member and compute LRFD design moment capacity per AISC 360-22 §F2.\n\n"
            "Returns:\n"
            "  • L_p_mm   — limiting unbraced length for plastic moment (Eq. F2-5)\n"
            "  • L_r_mm   — limiting unbraced length for inelastic-to-elastic LTB boundary (Eq. F2-6)\n"
            "  • Mp_kNm   — plastic moment capacity Fy·Zx\n"
            "  • Mr_kNm   — moment at elastic LTB onset = 0.7·Fy·Sx\n"
            "  • Mn_kNm   — nominal flexural strength for the supplied L_b\n"
            "  • phi_Mn_kNm — LRFD design strength φ_b·Mn (φ_b = 0.90)\n"
            "  • governing_mode — 'yielding' | 'inelastic_LTB' | 'elastic_LTB'\n"
            "  • Lb_to_Lp_ratio — quick check ratio (< 1 → fully braced)\n"
            "  • honest_caveat — code-compliance disclaimer\n\n"
            "SCOPE: Doubly symmetric compact I-shaped members bent about the major axis only "
            "(AISC 360-22 §F2). Channels, tees, and built-up sections are out of scope. "
            "Cb (moment gradient factor) must be supplied — use Cb=1.0 for conservative "
            "(uniform moment) design.\n\n"
            "All inputs in millimetres and MPa; moments returned in kN·m."
        ),
        input_schema={
            "type": "object",
            "required": ["section_label", "S_x_mm3", "Z_x_mm3", "r_y_mm", "J_mm4", "h_o_mm", "L_b_mm"],
            "properties": {
                "section_label": {
                    "type": "string",
                    "description": "Section label for reporting, e.g. 'W14x90' or 'W360x134'.",
                },
                "S_x_mm3": {
                    "type": "number",
                    "description": "Elastic section modulus about the strong axis (mm³).",
                },
                "Z_x_mm3": {
                    "type": "number",
                    "description": "Plastic section modulus about the strong axis (mm³).",
                },
                "r_y_mm": {
                    "type": "number",
                    "description": "Radius of gyration about the weak axis (mm). Used in Eq. F2-5 (Lp).",
                },
                "J_mm4": {
                    "type": "number",
                    "description": "Saint-Venant torsional constant (mm⁴).",
                },
                "h_o_mm": {
                    "type": "number",
                    "description": (
                        "Distance between the centroids of the flanges (mm). "
                        "For standard W-shapes h_o ≈ d − t_f."
                    ),
                },
                "L_b_mm": {
                    "type": "number",
                    "description": "Unbraced length of the compression flange (mm). Must be > 0.",
                },
                "Fy_MPa": {
                    "type": "number",
                    "description": (
                        "Yield stress (MPa). Default 345 MPa (A992 / A572 Gr 50). "
                        "Use 250 MPa for A36."
                    ),
                },
                "E_MPa": {
                    "type": "number",
                    "description": "Elastic modulus (MPa). Default 200 000 MPa.",
                },
                "ry_TS_mm": {
                    "type": "number",
                    "description": (
                        "Effective radius of gyration rts (mm) per AISC Eq. F2-7: "
                        "rts = √(√(Iy·Cw)/Sx). "
                        "Strongly recommended for accurate Lr/Fcr. "
                        "Omit to use ry as a conservative fallback."
                    ),
                },
                "Cb": {
                    "type": "number",
                    "description": (
                        "Moment gradient amplification factor (AISC §F1-1 / §C-F1-3). "
                        "Default 1.0 (conservative uniform moment). "
                        "Typical values: 1.14 (UDL, SS beam), 1.67 (midspan point load). "
                        "Must be ≥ 1.0."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_ltb_spec, write=False)
    async def run_arch_check_lateral_bracing(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = ["section_label", "S_x_mm3", "Z_x_mm3", "r_y_mm", "J_mm4", "h_o_mm", "L_b_mm"]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = WSectionSpec(
                section_label=str(a["section_label"]),
                S_x_mm3=float(a["S_x_mm3"]),
                Z_x_mm3=float(a["Z_x_mm3"]),
                r_y_mm=float(a["r_y_mm"]),
                J_mm4=float(a["J_mm4"]),
                h_o_mm=float(a["h_o_mm"]),
                Fy_MPa=float(a.get("Fy_MPa", 345.0)),
                E_MPa=float(a.get("E_MPa", 200_000.0)),
                ry_TS_mm=float(a["ry_TS_mm"]) if a.get("ry_TS_mm") is not None else None,
            )
            L_b_mm = float(a["L_b_mm"])
            Cb = float(a.get("Cb", 1.0))
            report = check_lateral_bracing(spec, L_b_mm, Cb=Cb)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "section_label": spec.section_label,
                "L_p_mm": round(report.L_p_mm, 1),
                "L_r_mm": round(report.L_r_mm, 1),
                "Mp_kNm": round(report.Mp_kNm, 2),
                "Mr_kNm": round(report.Mr_kNm, 2),
                "Mn_kNm": round(report.Mn_kNm, 2),
                "phi_Mn_kNm": round(report.phi_Mn_kNm, 2),
                "governing_mode": report.governing_mode,
                "Lb_to_Lp_ratio": round(report.Lb_to_Lp_ratio, 4),
                "honest_caveat": report.honest_caveat,
            }
        )
