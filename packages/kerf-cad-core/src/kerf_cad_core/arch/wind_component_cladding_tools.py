"""
kerf_cad_core.arch.wind_component_cladding_tools — LLM tool: arch_compute_wind_cc_pressure.

Registers one tool with the Kerf tool registry:

  arch_compute_wind_cc_pressure — compute design wind pressure on building
                                  components and cladding (windows, doors,
                                  wall panels, roof panels) per ASCE 7-22 §30.3
                                  (Components and Cladding — Low-Rise Buildings).

Distinct from arch_compute_wind_load (MWFRS §26–27): C&C uses higher combined
GCp peak-pressure coefficients for localised zones (interior / edge / corner).
Internal pressure coefficient GCpi = ±0.18 (enclosed buildings, Table 26.13-1)
is included explicitly in the design pressure.

Returns qz_psf, GCp_positive, GCp_negative, p_design_positive_psf,
        p_design_negative_psf, ASD_or_LRFD, code_section, honest_caveat.
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

from kerf_cad_core.arch.wind_load_asce7 import WindSiteSpec, BuildingSpec
from kerf_cad_core.arch.wind_component_cladding import (
    ComponentSpec,
    compute_wind_cc_pressure,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _cc_spec = ToolSpec(
        name="arch_compute_wind_cc_pressure",
        description=(
            "Compute design wind pressure on building components and cladding (C&C) "
            "per ASCE 7-22 §30.3 — Low-Rise Buildings (h ≤ 60 ft).\n\n"
            "USE THIS (not arch_compute_wind_load) for: windows, doors, wall panels, "
            "roof cladding, parapets, curtain-wall glazing, coping, fascia.\n\n"
            "Key differences from MWFRS §27 arch_compute_wind_load:\n"
            "  • Higher localised GCp peak coefficients (edge vortex amplification)\n"
            "  • No separate gust factor G — already embedded in GCp\n"
            "  • GCpi = ±0.18 (enclosed) included in the design pressure\n"
            "  • Pressure zones: Zone 1 interior < Zone 4 edge < Zone 5 corner (walls)\n"
            "                    Zone 1 interior < Zone 2 edge < Zone 3 corner (roofs)\n\n"
            "Design pressure:\n"
            "  p_positive = qh·(GCp_positive + 0.18)  [net inward, toward surface]\n"
            "  p_negative = qh·(GCp_negative − 0.18)  [net outward, suction]\n"
            "  where qh = 0.00256·Kh·Kzt·Kd·V²  (Eq 26.10-1)\n\n"
            "GCp effective-area reduction (Fig 30.3-2A/C): larger area → lower |GCp|.\n"
            "  Wall anchors at 10 ft² and 500 ft²; roof anchors at 10 ft² and 100 ft².\n\n"
            "GCp anchors (at 10 ft²):\n"
            "  Zone_1_interior_wall: +0.9 / −1.1\n"
            "  Zone_4_wall_edge:     +1.0 / −1.1\n"
            "  Zone_5_corner_wall:   +1.0 / −1.4 (highest wall suction)\n"
            "  Zone_1_roof_interior: +0.3 / −1.0\n"
            "  Zone_2_roof_edge:     +0.3 / −1.8\n"
            "  Zone_3_roof_corner:   +0.3 / −2.8 (highest roof suction)\n\n"
            "SCOPE: Low-rise (h ≤ 60 ft), enclosed buildings only. "
            "NOT computed: partially-enclosed GCpi=±0.55 (§26.13.2), "
            "open-building GCpi=0, high-rise C&C (§30.4), parapets (§30.9), "
            "roof slopes >7° (Fig 30.3-2D). "
            "Minimum pressure ±16 psf (§30.2.2) must be checked manually.\n\n"
            "Returns qz_psf, GCp_positive, GCp_negative, "
            "p_design_positive_psf, p_design_negative_psf, ASD_or_LRFD, "
            "code_section, honest_caveat."
        ),
        input_schema={
            "type": "object",
            "required": [
                "V_basic_mph",
                "exposure_category",
                "mean_height_h_ft",
                "length_ft",
                "width_ft",
                "area_ft2",
                "zone",
                "component_type",
            ],
            "properties": {
                "V_basic_mph": {
                    "type": "number",
                    "description": (
                        "Basic wind speed V (mph) from ASCE 7-22 Fig 26.5-1 "
                        "(Risk Category II) or Fig 26.5-2A/B/C for other risk "
                        "categories. Must be > 0."
                    ),
                },
                "exposure_category": {
                    "type": "string",
                    "enum": ["B", "C", "D"],
                    "description": (
                        "Surface roughness / exposure per §26.7: "
                        "'B'=urban/suburban; 'C'=open terrain; 'D'=coastal/water."
                    ),
                },
                "mean_height_h_ft": {
                    "type": "number",
                    "description": (
                        "Mean roof height h (ft). Must be > 0. "
                        "ASCE 7-22 §30.3 applies only for h ≤ 60 ft."
                    ),
                },
                "length_ft": {
                    "type": "number",
                    "description": "Building length parallel to wind direction (ft). Must be > 0.",
                },
                "width_ft": {
                    "type": "number",
                    "description": "Building width perpendicular to wind direction (ft). Must be > 0.",
                },
                "area_ft2": {
                    "type": "number",
                    "description": (
                        "Effective wind area of the component (ft²). "
                        "For most elements this equals the tributary area. "
                        "For one-way spanning members use span × (span/3). "
                        "Must be > 0."
                    ),
                },
                "zone": {
                    "type": "string",
                    "enum": [
                        "Zone_1_interior_wall",
                        "Zone_4_wall_edge",
                        "Zone_5_corner_wall",
                        "Zone_1_roof_interior",
                        "Zone_2_roof_edge",
                        "Zone_3_roof_corner",
                    ],
                    "description": (
                        "Pressure zone per ASCE 7-22 §30.3 / Fig 30.3-2: "
                        "Zone_1_interior_wall = field of wall; "
                        "Zone_4_wall_edge = edge strip; "
                        "Zone_5_corner_wall = corner (highest wall suction); "
                        "Zone_1_roof_interior = roof field; "
                        "Zone_2_roof_edge = roof edge strip; "
                        "Zone_3_roof_corner = roof corner (highest suction −2.8 at 10 ft²)."
                    ),
                },
                "component_type": {
                    "type": "string",
                    "enum": ["wall", "roof"],
                    "description": (
                        "'wall' for windows, doors, wall panels (Fig 30.3-2A). "
                        "'roof' for roof cladding, skylights (Fig 30.3-2C, slope ≤7°)."
                    ),
                },
                "K_zt": {
                    "type": "number",
                    "description": (
                        "Topographic factor per §26.8. Default = 1.0 (flat terrain). "
                        "Set > 1.0 for hills/ridges/escarpments."
                    ),
                },
                "risk_category": {
                    "type": "string",
                    "enum": ["I", "II", "III", "IV"],
                    "description": (
                        "Risk Category per §1.5 / Table 1.5-1 (documentation only). "
                        "V_basic_mph must already be from the correct RC map."
                    ),
                },
                "enclosure": {
                    "type": "string",
                    "enum": ["enclosed", "partially_enclosed", "open"],
                    "description": (
                        "Building enclosure classification per §26.12. "
                        "Only 'enclosed' (GCpi=±0.18) is fully supported; "
                        "'partially_enclosed' and 'open' are NOT implemented "
                        "— the call will succeed but GCpi=±0.18 will be used "
                        "with a warning embedded in honest_caveat."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_cc_spec, write=False)
    async def run_arch_compute_wind_cc_pressure(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "V_basic_mph", "exposure_category", "mean_height_h_ft",
            "length_ft", "width_ft", "area_ft2", "zone", "component_type",
        ]
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
            comp = ComponentSpec(
                area_ft2=float(a["area_ft2"]),
                zone=str(a["zone"]),
                component_type=str(a["component_type"]),
            )
            report = compute_wind_cc_pressure(site, bldg, comp)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "qz_psf": report.qz_psf,
                "GCp_positive": report.GCp_positive,
                "GCp_negative": report.GCp_negative,
                "p_design_positive_psf": report.p_design_positive_psf,
                "p_design_negative_psf": report.p_design_negative_psf,
                "ASD_or_LRFD": report.ASD_or_LRFD,
                "code_section": report.code_section,
                "honest_caveat": report.honest_caveat,
            }
        )
