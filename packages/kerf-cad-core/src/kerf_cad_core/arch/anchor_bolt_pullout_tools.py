"""
kerf_cad_core.arch.anchor_bolt_pullout_tools — LLM tool: arch_check_anchor_pullout.

Registers one tool with the Kerf tool registry:

  arch_check_anchor_pullout — check cast-in-place headed anchor bolt(s) for
                               tensile pullout capacity per ACI 318-19 §17.6
                               (steel strength §17.6.1 + concrete breakout
                               §17.6.2 + concrete pullout §17.6.3) and
                               ACI 355.2.

References:
  ACI 318-19 Chapter 17 — Anchoring to Concrete.
  ACI 355.2 — Qualification of Post-Installed Mechanical Anchors in Concrete.

All inputs: mm (dimensions), MPa (stress), kN (force).
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

from kerf_cad_core.arch.anchor_bolt_pullout import (
    AnchorBoltSpec,
    check_anchor_pullout,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _anchor_pullout_spec = ToolSpec(
        name="arch_check_anchor_pullout",
        description=(
            "Check cast-in-place headed anchor bolt(s) in pure tension per "
            "ACI 318-19 Chapter 17 + ACI 355.2.\n\n"
            "Three ACI 318-19 §17.6 limit states are evaluated:\n"
            "  1. Steel tensile strength (§17.6.1):\n"
            "       A_se = 0.85·π·d²/4 (effective tensile area per ACI 355.2)\n"
            "       φ·N_sa = φ_s · A_se · fy   (φ_s = 0.75 default)\n\n"
            "  2. Concrete breakout in tension (§17.6.2):\n"
            "       N_b = k_c · λ · √f'c · h_ef^1.5   [N, MPa, mm]  "
            "(k_c = 10 cracked / 14 uncracked, SI equivalent of ACI §17.6.2.2.1)\n"
            "       A_Nco = 9·h_ef²\n"
            "       A_Nc from projected cone geometry (clipped at edges / spacing)\n"
            "       ψ_ed,N = 1.0 if c_a,min≥1.5·h_ef; else 0.7+0.3·c_a,min/(1.5·h_ef)  (§17.6.2.4.1)\n"
            "       ψ_c,N = 1.0 cracked / 1.25 uncracked  (§17.6.2.5.1)\n"
            "       φ·N_cb = φ_c · (A_Nc/A_Nco) · ψ_ed · ψ_c · N_b   (φ_c = 0.65 default)\n\n"
            "  3. Concrete pullout — headed bolt (§17.6.3):\n"
            "       N_p = 8 · A_brg · f'c  (§17.6.3.2)\n"
            "       φ·N_pn = φ_c · N_p\n\n"
            "Governing: min(φ·N_sa, φ·N_cb, φ·N_pn).\n\n"
            "SCOPE: tension-only (no shear interaction §17.7); cracked concrete assumed "
            "by default (conservative); λ = 1.0 (normal-weight concrete); ψ_ec = 1.0 "
            "(concentric load); splitting / side-face blowout / adhesive bond NOT checked. "
            "One close edge assumed; multi-edge confinement requires full §17.6.2.1.2 geometry. "
            "All dimensions in mm; stresses in MPa; loads in kN."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bolt_diameter_mm": {
                    "type": "number",
                    "description": (
                        "Nominal anchor bolt diameter d in mm. Must be > 0. "
                        "Example: 16 for M16 bolt; 19 for 3/4\" bolt."
                    ),
                },
                "embedment_depth_hef_mm": {
                    "type": "number",
                    "description": (
                        "Effective embedment depth h_ef in mm — from concrete surface to "
                        "bearing face of anchor head (ACI 318-19 §17.6.2.1). Must be > 0. "
                        "Typical range: 75–500 mm."
                    ),
                },
                "edge_distance_min_mm": {
                    "type": "number",
                    "description": (
                        "Minimum edge distance c_a,min in mm — from anchor centreline to "
                        "nearest free concrete edge (ACI 318-19 §17.6.2.4.1). Must be ≥ 0. "
                        "Values < 1.5·h_ef trigger the ψ_ed edge-effect factor."
                    ),
                },
                "anchor_spacing_min_mm": {
                    "type": "number",
                    "description": (
                        "Centre-to-centre anchor spacing s in mm (for groups). "
                        "Required if bolt_count > 1. Used to compute group projected "
                        "breakout area A_Nc (§17.6.2.1.2)."
                    ),
                },
                "fc_MPa": {
                    "type": "number",
                    "description": (
                        "Specified compressive strength of concrete f'c in MPa. Must be > 0. "
                        "Typical: 20–50 MPa (3000–7000 psi)."
                    ),
                },
                "fy_steel_MPa": {
                    "type": "number",
                    "description": (
                        "Specified yield strength of anchor steel fy in MPa. Must be > 0. "
                        "Typical: 250 (F1554 Gr36), 420 (A615 Gr60 / F1554 Gr55), "
                        "520 (ASTM A193 B7)."
                    ),
                },
                "head_bearing_area_mm2": {
                    "type": "number",
                    "description": (
                        "Net bearing area of anchor head A_brg in mm² — gross head area "
                        "minus bolt shank area (ACI 318-19 §17.6.3.2). Must be > 0. "
                        "For a standard hex-head bolt: A_brg ≈ A_head − π·d²/4. "
                        "Typical: 200–2000 mm² depending on bolt size and washer."
                    ),
                },
                "N_factored_kN": {
                    "type": "number",
                    "description": (
                        "Factored tensile demand N_u in kN (LRFD combo, e.g. 1.2·DL+1.6·LL). "
                        "Must be ≥ 0."
                    ),
                },
                "bolt_count": {
                    "type": "integer",
                    "description": (
                        "Number of identical anchors in the group. Default 1. "
                        "Must be ≥ 1. Groups assume equal load distribution."
                    ),
                },
                "cracked_concrete": {
                    "type": "boolean",
                    "description": (
                        "If true (default/conservative), use k_c=10 (cracked) per ACI "
                        "§17.6.2.2.1 and ψ_c=1.0. If false, use k_c=14 (uncracked) "
                        "and ψ_c=1.25 — only valid when concrete is verified uncracked "
                        "throughout anchor service life."
                    ),
                },
                "phi_steel": {
                    "type": "number",
                    "description": (
                        "Steel strength-reduction factor φ_s. ACI 318-19 Table 17.5.3 "
                        "ductile steel: 0.75 (default). Use 0.65 for non-ductile."
                    ),
                },
                "phi_concrete": {
                    "type": "number",
                    "description": (
                        "Concrete strength-reduction factor φ_c for breakout and pullout. "
                        "ACI 318-19 Table 17.5.3: 0.65 Condition B (no supplementary "
                        "reinforcement, default); 0.70 Condition A."
                    ),
                },
            },
            "required": [
                "bolt_diameter_mm",
                "embedment_depth_hef_mm",
                "edge_distance_min_mm",
                "anchor_spacing_min_mm",
                "fc_MPa",
                "fy_steel_MPa",
                "head_bearing_area_mm2",
                "N_factored_kN",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_anchor_pullout_spec, write=False)
    async def run_arch_check_anchor_pullout(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required = [
            "bolt_diameter_mm", "embedment_depth_hef_mm", "edge_distance_min_mm",
            "anchor_spacing_min_mm", "fc_MPa", "fy_steel_MPa",
            "head_bearing_area_mm2", "N_factored_kN",
        ]
        missing = [f for f in required if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = AnchorBoltSpec(
                bolt_diameter_mm=float(a["bolt_diameter_mm"]),
                embedment_depth_hef_mm=float(a["embedment_depth_hef_mm"]),
                edge_distance_min_mm=float(a["edge_distance_min_mm"]),
                anchor_spacing_min_mm=float(a["anchor_spacing_min_mm"]),
                fc_MPa=float(a["fc_MPa"]),
                fy_steel_MPa=float(a["fy_steel_MPa"]),
                head_bearing_area_mm2=float(a["head_bearing_area_mm2"]),
                bolt_count=int(a.get("bolt_count", 1)),
                cracked_concrete=bool(a.get("cracked_concrete", True)),
            )
            N_factored = float(a["N_factored_kN"])
            phi_s = float(a.get("phi_steel", 0.75))
            phi_c = float(a.get("phi_concrete", 0.65))
            report = check_anchor_pullout(spec, N_factored, phi_steel=phi_s, phi_concrete=phi_c)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "phi_Nsa_kN": report.phi_Nsa_kN,
                "phi_Ncb_kN": report.phi_Ncb_kN,
                "phi_Nph_kN": report.phi_Nph_kN,
                "phi_Nn_governing_kN": report.phi_Nn_governing_kN,
                "governing_mode": report.governing_mode,
                "dcr": report.dcr,
                "adequate": report.adequate,
                "A_se_mm2": report.A_se_mm2,
                "N_b_kN": report.N_b_kN,
                "A_Nc_mm2": report.A_Nc_mm2,
                "A_Nco_mm2": report.A_Nco_mm2,
                "psi_ed": report.psi_ed,
                "psi_c": report.psi_c,
                "honest_caveat": report.honest_caveat,
            }
        )
