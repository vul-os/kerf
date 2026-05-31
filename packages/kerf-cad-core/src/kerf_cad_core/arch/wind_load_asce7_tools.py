"""
kerf_cad_core.arch.wind_load_asce7_tools — LLM tool: arch_compute_wind_load.

Registers one tool with the Kerf tool registry:

  arch_compute_wind_load — compute design wind pressure on a building wall per
                           ASCE 7-22 §26–27 Directional Procedure (MWFRS).

Returns velocity pressure qz, external pressure coefficients Cp (windward/leeward),
design wall pressures, and total lateral drag pressure (psf).

All pressures in pounds per square foot (psf); wind speed in mph; heights in feet.
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

from kerf_cad_core.arch.wind_load_asce7 import (
    WindSiteSpec,
    BuildingSpec,
    compute_wind_load,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _wind_load_spec = ToolSpec(
        name="arch_compute_wind_load",
        description=(
            "Compute design wind pressure on a building wall per ASCE 7-22 §26–27 "
            "Directional Procedure (Main Wind Force-Resisting System — MWFRS).\n\n"
            "Calculates:\n"
            "  • Kz — velocity pressure exposure coefficient (Table 26.10-1)\n"
            "  • qz — velocity pressure at mean roof height: 0.00256·Kz·Kzt·Kd·V² (psf)\n"
            "  • Cp — external pressure coefficients: windward=+0.8, leeward per Fig 27.4-1\n"
            "  • p_windward = qz·G·Cp_windward  (G=0.85 rigid, §26.11.1)\n"
            "  • p_leeward  = qz·G·|Cp_leeward|\n"
            "  • total_drag = qz·G·(Cp_windward − Cp_leeward)\n\n"
            "Exposure constants (Table 26.10-1):\n"
            "  B: α=7.0, zg=1200 ft (urban/suburban)\n"
            "  C: α=9.5, zg=900 ft  (open terrain — most common)\n"
            "  D: α=11.5, zg=700 ft (coastal/water)\n\n"
            "Scope: rigid buildings only; enclosed/partially-enclosed/open for documentation. "
            "NOT computed: internal pressure GCpi (§26.13), parapet loads (§27.7), "
            "roof pressures, tornado loads (§32), Envelope Procedure (§28).\n\n"
            "Returns qz_psf, Kz, Cp_windward, Cp_leeward, p_windward_psf, "
            "p_leeward_psf, total_drag_psf, L_over_B, code_section, honest_caveat."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "V_basic_mph": {
                    "type": "number",
                    "description": (
                        "Basic wind speed V (mph) from ASCE 7-22 Fig 26.5-1 "
                        "(Risk Category II) or Fig 26.5-2A/B/C for other risk categories. "
                        "Must be > 0. Typical US: 85–200 mph. "
                        "Select the map for the correct risk category."
                    ),
                },
                "exposure_category": {
                    "type": "string",
                    "enum": ["B", "C", "D"],
                    "description": (
                        "Surface roughness / exposure per ASCE 7-22 §26.7: "
                        "'B' = urban, suburban, wooded (z0≈1 ft); "
                        "'C' = open terrain, scattered obstructions < 30 ft (z0≈0.07 ft); "
                        "'D' = flat, unobstructed areas and water surfaces (z0≈0.016 ft)."
                    ),
                },
                "mean_height_h_ft": {
                    "type": "number",
                    "description": (
                        "Mean roof height h (ft). For flat roofs use eave height; "
                        "for gable/hip roofs use mid-slope height. Must be > 0."
                    ),
                },
                "length_ft": {
                    "type": "number",
                    "description": (
                        "Horizontal building dimension parallel to wind direction L (ft). "
                        "Used for L/B ratio to determine leeward Cp. Must be > 0."
                    ),
                },
                "width_ft": {
                    "type": "number",
                    "description": (
                        "Horizontal building dimension perpendicular to wind direction B (ft). "
                        "Must be > 0."
                    ),
                },
                "K_zt": {
                    "type": "number",
                    "description": (
                        "Topographic factor per ASCE 7-22 §26.8 and Fig 26.8-1. "
                        "Default = 1.0 (flat terrain). Set > 1.0 for hills, "
                        "ridges, or escarpments."
                    ),
                },
                "risk_category": {
                    "type": "string",
                    "enum": ["I", "II", "III", "IV"],
                    "description": (
                        "Risk Category per ASCE 7-22 §1.5 / Table 1.5-1. "
                        "Used for documentation only — V_basic_mph must already "
                        "be from the correct risk-category wind speed map."
                    ),
                },
                "enclosure": {
                    "type": "string",
                    "enum": ["enclosed", "partially_enclosed", "open"],
                    "description": (
                        "Building enclosure classification per §26.12. "
                        "Used for documentation; internal pressure GCpi (§26.13) "
                        "is NOT computed in this tool."
                    ),
                },
            },
            "required": [
                "V_basic_mph",
                "exposure_category",
                "mean_height_h_ft",
                "length_ft",
                "width_ft",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_wind_load_spec, write=False)
    async def run_arch_compute_wind_load(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = ["V_basic_mph", "exposure_category", "mean_height_h_ft",
                           "length_ft", "width_ft"]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            site = WindSiteSpec(
                V_basic_mph=float(a["V_basic_mph"]),
                exposure_category=str(a["exposure_category"]),
                K_zt=float(a.get("K_zt", 1.0)),
                risk_category=str(a.get("risk_category", "II")),
            )
            bldg = BuildingSpec(
                mean_height_h_ft=float(a["mean_height_h_ft"]),
                length_ft=float(a["length_ft"]),
                width_ft=float(a["width_ft"]),
                enclosure=str(a.get("enclosure", "enclosed")),
            )
            report = compute_wind_load(site, bldg)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "qz_psf": report.qz_psf,
                "Kz": report.Kz,
                "Cp_windward": report.Cp_windward,
                "Cp_leeward": report.Cp_leeward,
                "p_windward_psf": report.p_windward_psf,
                "p_leeward_psf": report.p_leeward_psf,
                "total_drag_psf": report.total_drag_psf,
                "L_over_B": report.L_over_B,
                "code_section": report.code_section,
                "honest_caveat": report.honest_caveat,
            }
        )
