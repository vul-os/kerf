"""
kerf_cad_core.arch.column_load_check_tools — LLM tool: arch_check_column_load.

Registers one tool with the Kerf tool registry:

  arch_check_column_load — check whether a steel (AISC 360-22 §E3) or reinforced
                           concrete (ACI 318-19 §22.4.2.2) column section satisfies
                           its axial-load capacity under a given demand.

All dimensions in **millimetres** and **MPa**; results in **kN**.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.arch.column_load_check import (
    SteelColumnSpec,
    ConcreteColumnSpec,
    check_steel_column,
    check_concrete_column,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_column_load_spec = ToolSpec(
    name="arch_check_column_load",
    description=(
        "Check whether a structural column satisfies its axial-load capacity under a given service "
        "(or factored) demand load. "
        "Supports two column types:\n"
        "  • steel  — AISC 360-22 §E3 LRFD (flexural buckling, inelastic E3-2 and elastic Euler E3-3; "
        "φ_c = 0.90). Accepts W-shapes, HSS, or any section with gross area A_mm2 and min radius of "
        "gyration r_min_mm.\n"
        "  • concrete — ACI 318-19 §22.4.2.2 (short tied column, φ·Pn = φ·0.80·[0.85·f'c·(Ag−Ast) + "
        "fy·Ast]; φ = 0.65 tied / 0.75 spiral).\n"
        "Returns design strength φ·Pn (kN), demand/capacity ratio (DCR), governing mode, PASS/FAIL "
        "status, and an honest code-compliance caveat. "
        "All dimensions in millimetres; stresses/strengths in MPa; forces in kN."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "column_type": {
                "type": "string",
                "enum": ["steel", "concrete"],
                "description": (
                    "'steel' → AISC 360-22 §E3 LRFD check. "
                    "'concrete' → ACI 318-19 §22.4.2.2 short-column check."
                ),
            },
            "P_demand_kN": {
                "type": "number",
                "description": (
                    "Required (factored for LRFD) axial compressive demand in kN. Must be > 0."
                ),
            },
            # ---- steel fields ----
            "section_label": {
                "type": "string",
                "description": (
                    "[Steel only] Section label, e.g. 'W14x90' or 'HSS 152x152x9.5'. "
                    "Used for reporting only."
                ),
            },
            "A_mm2": {
                "type": "number",
                "description": "[Steel only] Gross cross-sectional area in mm².",
            },
            "r_min_mm": {
                "type": "number",
                "description": (
                    "[Steel only] Minimum radius of gyration (weak axis) in mm. "
                    "For W-shapes use ry; for HSS use the governing r."
                ),
            },
            "Fy_MPa": {
                "type": "number",
                "description": "[Steel only] Yield stress in MPa, e.g. 345 for A572 Gr 50.",
            },
            "K": {
                "type": "number",
                "description": (
                    "[Steel only] Effective-length factor. "
                    "Typical values: 1.0 (pin-pin), 0.7 (pin-fixed), 0.5 (fixed-fixed)."
                ),
            },
            "L_mm": {
                "type": "number",
                "description": "[Steel only] Unbraced column length in mm.",
            },
            "E_MPa": {
                "type": "number",
                "description": "[Steel only] Elastic modulus in MPa. Default 200 000 MPa.",
            },
            # ---- concrete fields ----
            "A_g_mm2": {
                "type": "number",
                "description": "[Concrete only] Gross section area in mm² (b × h for rect; π r² for circ).",
            },
            "A_st_mm2": {
                "type": "number",
                "description": "[Concrete only] Total area of longitudinal rebar in mm².",
            },
            "fc_MPa": {
                "type": "number",
                "description": "[Concrete only] Specified concrete compressive strength f'c in MPa.",
            },
            "fy_MPa": {
                "type": "number",
                "description": "[Concrete only] Rebar yield strength in MPa, e.g. 420.",
            },
            "phi": {
                "type": "number",
                "description": (
                    "[Concrete only] Strength-reduction factor φ. "
                    "Default 0.65 (tied); use 0.75 for spiral-reinforced columns."
                ),
            },
        },
        "required": ["column_type", "P_demand_kN"],
    },
)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

@register(_column_load_spec, write=False)
async def run_arch_check_column_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    col_type = a.get("column_type", "")
    P_kN = a.get("P_demand_kN")

    if col_type not in ("steel", "concrete"):
        return err_payload(
            "column_type must be 'steel' or 'concrete'", "BAD_ARGS"
        )
    if P_kN is None:
        return err_payload("P_demand_kN is required", "BAD_ARGS")
    try:
        P_kN = float(P_kN)
    except (TypeError, ValueError) as exc:
        return err_payload(f"P_demand_kN must be a number: {exc}", "BAD_ARGS")
    if P_kN <= 0:
        return err_payload("P_demand_kN must be > 0", "BAD_ARGS")

    if col_type == "steel":
        required = ["A_mm2", "r_min_mm", "Fy_MPa", "K", "L_mm"]
        missing = [f for f in required if a.get(f) is None]
        if missing:
            return err_payload(
                f"Missing required steel fields: {missing}", "BAD_ARGS"
            )
        try:
            spec = SteelColumnSpec(
                section_label=str(a.get("section_label", "unknown")),
                A_mm2=float(a["A_mm2"]),
                r_min_mm=float(a["r_min_mm"]),
                Fy_MPa=float(a["Fy_MPa"]),
                K=float(a["K"]),
                L_mm=float(a["L_mm"]),
                E_MPa=float(a.get("E_MPa", 200_000.0)),
            )
            report = check_steel_column(spec, P_kN)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

    else:  # concrete
        required_c = ["A_g_mm2", "A_st_mm2", "fc_MPa", "fy_MPa"]
        missing_c = [f for f in required_c if a.get(f) is None]
        if missing_c:
            return err_payload(
                f"Missing required concrete fields: {missing_c}", "BAD_ARGS"
            )
        try:
            spec_c = ConcreteColumnSpec(
                A_g_mm2=float(a["A_g_mm2"]),
                A_st_mm2=float(a["A_st_mm2"]),
                fc_MPa=float(a["fc_MPa"]),
                fy_MPa=float(a["fy_MPa"]),
                phi=float(a.get("phi", 0.65)),
            )
            report = check_concrete_column(spec_c, P_kN)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

    return ok_payload(
        {
            "phi_Pn_kN": round(report.phi_Pn_kN, 3),
            "demand_capacity_ratio": round(report.demand_capacity_ratio, 4),
            "governing_mode": report.governing_mode,
            "controls": report.controls,
            "honest_caveat": report.honest_caveat,
        }
    )
