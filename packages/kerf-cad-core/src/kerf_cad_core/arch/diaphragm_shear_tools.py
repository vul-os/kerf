"""
kerf_cad_core.arch.diaphragm_shear_tools — LLM tool: arch_check_diaphragm_shear.

Registers one tool with the Kerf tool registry:

  arch_check_diaphragm_shear — check in-plane shear capacity of a horizontal wood
                               or cold-formed steel diaphragm (floor or roof) per:
                                 AWC SDPWS-2021 §4.2 (wood structural panel diaphragms)
                                 AISI S400-20 / SDI DDM04 (cold-formed steel / metal deck)
                                 IBC §2305.2 (aspect ratio limits)

Returns unit_shear_v_plf, allowable_unit_shear_v_allow_plf, demand_capacity_ratio,
        adequate, governing_factor, honest_caveat.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

References:
  AWC SDPWS-2021 §4.2, Table 4.2A.
  SDI DDM04 Table 1.3-3.
  IBC 2021 §2305.2.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.diaphragm_shear import (
    DiaphragmSpec,
    check_diaphragm_shear,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _diaphragm_spec = ToolSpec(
        name="arch_check_diaphragm_shear",
        description=(
            "Check in-plane shear capacity of a horizontal wood or cold-formed "
            "steel (metal deck) diaphragm per AWC SDPWS-2021 §4.2 (wood) or "
            "AISI S400-20 / SDI DDM04 (steel deck), with IBC §2305.2 aspect-ratio check.\n\n"
            "Checks performed:\n"
            "  1. Applied unit shear: v = V_lateral_lbs / length_along_load (plf)\n"
            "  2. Allowable unit shear from SDPWS-2021 Table 4.2A (wood) or SDI DDM04 (steel);\n"
            "     species factor C_s (DF_L=1.0, SP=1.0, HF=0.9, SPF=0.8) applied to wood.\n"
            "     Unblocked: 50% reduction per SDPWS §4.2.7 Case 1.\n"
            "  3. Aspect ratio AR = L/W ≤ 4:1 (wood, SDPWS Table 4.2.4) or ≤ 2:1 (steel deck).\n"
            "  4. DCR = v / v_allow ≤ 1.0\n\n"
            "Returns unit_shear_v_plf, allowable_unit_shear_v_allow_plf, "
            "demand_capacity_ratio, adequate, governing_factor, honest_caveat.\n\n"
            "SCOPE: In-plane unit shear only. Chord forces (tension/compression at "
            "diaphragm boundaries) are NOT calculated. Diaphragm deflection NOT calculated. "
            "ASD basis throughout — V_lateral_lbs must reflect the governing ASD load combo. "
            "SDPWS Table 4.2A values are for SDC A–C; SDC D–F may require additional checks. "
            "Inputs: all dimensions in mm; V_lateral_lbs in US pounds; unit shear output in plf."
        ),
        input_schema={
            "type": "object",
            "required": [
                "length_along_load_mm",
                "width_perp_to_load_mm",
                "sheathing_type",
                "nail_spacing_mm",
                "blocked",
                "framing_species",
                "V_lateral_lbs",
            ],
            "properties": {
                "length_along_load_mm": {
                    "type": "number",
                    "description": (
                        "Diaphragm dimension parallel to the lateral load direction (mm). "
                        "Shear V is distributed along this length: v = V/L. Must be > 0."
                    ),
                },
                "width_perp_to_load_mm": {
                    "type": "number",
                    "description": (
                        "Diaphragm dimension perpendicular to the lateral load direction (mm). "
                        "Chord members run along this edge. Used for aspect-ratio check AR=L/W. "
                        "Must be > 0."
                    ),
                },
                "sheathing_type": {
                    "type": "string",
                    "enum": [
                        "plywood_15_32",
                        "plywood_19_32",
                        "osb_15_32",
                        "metal_deck_22ga",
                        "metal_deck_18ga",
                    ],
                    "description": (
                        "Sheathing material and thickness:\n"
                        "  plywood_15_32   — 15/32\" structural plywood (SDPWS Table 4.2A)\n"
                        "  plywood_19_32   — 19/32\" structural plywood (SDPWS Table 4.2A)\n"
                        "  osb_15_32       — 15/32\" OSB (=plywood capacity per SDPWS §4.2.3)\n"
                        "  metal_deck_22ga — 22 ga cold-formed steel deck (SDI DDM04 36/6 ASD)\n"
                        "  metal_deck_18ga — 18 ga cold-formed steel deck (SDI DDM04 36/6 ASD)"
                    ),
                },
                "nail_spacing_mm": {
                    "type": "number",
                    "description": (
                        "Nail spacing at panel edges (mm). Ignored for metal deck. "
                        "Typical: 152.4 mm (6\"), 101.6 mm (4\"), 63.5 mm (2.5\"), 50.8 mm (2\"). "
                        "Allowable shear is linearly interpolated between SDPWS table entries. "
                        "Must be between 50 and 165 mm for wood."
                    ),
                },
                "blocked": {
                    "type": "boolean",
                    "description": (
                        "True = blocked diaphragm (all panel edges supported and blocked). "
                        "False = unblocked (unsupported edges at intermediate framing); "
                        "allowable shear reduced by 0.50 per SDPWS §4.2.7."
                    ),
                },
                "framing_species": {
                    "type": "string",
                    "enum": ["DF_L", "SP", "HF", "SPF"],
                    "description": (
                        "Framing lumber species group (SDPWS Table 4.2A footnote 3). "
                        "Ignored for metal deck.\n"
                        "  DF_L — Douglas Fir-Larch (C_s=1.00, reference)\n"
                        "  SP   — Southern Pine    (C_s=1.00)\n"
                        "  HF   — Hem-Fir           (C_s=0.90)\n"
                        "  SPF  — Spruce-Pine-Fir   (C_s=0.80)"
                    ),
                },
                "V_lateral_lbs": {
                    "type": "number",
                    "description": (
                        "Total applied lateral (in-plane) shear force (US pounds, ASD level). "
                        "Must reflect the governing ASD load combination per ASCE 7 §2.4. "
                        "Must be ≥ 0."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_diaphragm_spec, write=False)
    async def run_arch_check_diaphragm_shear(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "length_along_load_mm",
            "width_perp_to_load_mm",
            "sheathing_type",
            "nail_spacing_mm",
            "blocked",
            "framing_species",
            "V_lateral_lbs",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = DiaphragmSpec(
                length_along_load_mm=float(a["length_along_load_mm"]),
                width_perp_to_load_mm=float(a["width_perp_to_load_mm"]),
                sheathing_type=str(a["sheathing_type"]),
                nail_spacing_mm=float(a["nail_spacing_mm"]),
                blocked=bool(a["blocked"]),
                framing_species=str(a["framing_species"]),
            )
            V_lateral_lbs = float(a["V_lateral_lbs"])
            report = check_diaphragm_shear(spec, V_lateral_lbs)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "unit_shear_v_plf": round(report.unit_shear_v_plf, 3),
                "allowable_unit_shear_v_allow_plf": round(report.allowable_unit_shear_v_allow_plf, 3),
                "demand_capacity_ratio": round(report.demand_capacity_ratio, 6),
                "adequate": report.adequate,
                "governing_factor": report.governing_factor,
                "honest_caveat": report.honest_caveat,
            }
        )
