"""
kerf_cad_core.buildingenergy.compliance_tools — LLM tool wrapper for ASHRAE 90.1
compliance reporting.

Registers one tool with the Kerf tool registry:

  bim_compute_energy_compliance_report
      Runs an 8760-hour simplified whole-building energy simulation,
      compares against ASHRAE 90.1-2022 Appendix G baseline EUI,
      computes LEED v4 EA credits, and returns a structured compliance report.

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ASHRAE 90.1-2022 Appendix G — Performance Rating Method
LEED v4 BD+C — Energy & Atmosphere: Optimize Energy Performance (EA Opt 1)
IECC 2021 — International Energy Conservation Code
ASHRAE 62.1-2022 — Ventilation

Author: imranparuk
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False
    ToolSpec = None  # type: ignore[assignment,misc]
    err_payload = None  # type: ignore[assignment]
    ok_payload = None  # type: ignore[assignment]
    register = None  # type: ignore[assignment]
    ProjectCtx = None  # type: ignore[assignment,misc]

from kerf_cad_core.buildingenergy.compliance_report import (
    ComplianceSpec,
    compute_compliance_report,
)


# ---------------------------------------------------------------------------
# Tool spec definition
# ---------------------------------------------------------------------------

_SPEC_DEF = {
    "name": "bim_compute_energy_compliance_report",
    "description": (
        "Run an 8760-hour simplified whole-building energy simulation and "
        "generate an ASHRAE 90.1-2022 / LEED v4 compliance report.\n"
        "\n"
        "Inputs:\n"
        "  building_type       : 'office'|'residential'|'retail'|'warehouse'|'hospital'|'education'\n"
        "  floor_area_m2       : gross conditioned floor area (m²)\n"
        "  climate_zone        : ASHRAE 169 zone string e.g. '4A', '3B', '6A', '8'\n"
        "  wall_assemblies     : [{U: float [W/(m²·K)], area_m2: float}, ...]\n"
        "  roof_assembly       : {U: float, area_m2: float}\n"
        "  window_specs        : [{U: float, area_m2: float, SHGC: float [0-1]}, ...]\n"
        "  lighting_load_W_per_m2  : installed lighting power density (W/m²)\n"
        "  plug_load_W_per_m2      : equipment / plug load density (W/m²)\n"
        "  hvac_system_type        : 'VAV'|'PTHP'|'CRAC'|'chiller'\n"
        "  annual_run_hours        : operating hours/year (default 8760)\n"
        "\n"
        "Outputs (ComplianceReport):\n"
        "  total_annual_energy_kWh, energy_use_intensity_kWh_per_m2,\n"
        "  ashrae_90_1_compliance, ashrae_baseline_eui,\n"
        "  percent_better_than_baseline, leed_credits_earned,\n"
        "  recommendations, honest_caveat, energy_breakdown\n"
        "\n"
        "References: ASHRAE 90.1-2022 Appendix G; LEED v4 EA Opt 1; IECC 2021.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "building_type": {
                "type": "string",
                "enum": ["office", "residential", "retail", "warehouse", "hospital", "education"],
                "description": "Primary building occupancy type.",
            },
            "floor_area_m2": {
                "type": "number",
                "description": "Gross conditioned floor area (m²). Must be > 0.",
            },
            "climate_zone": {
                "type": "string",
                "description": (
                    "ASHRAE 169 climate zone string. Examples: '1A', '2B', '3C', "
                    "'4A', '5A', '6B', '7', '8'. Zone letter (A/B/C) is optional for zones 7-8."
                ),
            },
            "wall_assemblies": {
                "type": "array",
                "description": (
                    "List of wall assembly dicts: [{\"U\": U-value W/(m²·K), "
                    "\"area_m2\": area m²}, ...]. Include all exposed walls."
                ),
                "items": {"type": "object"},
            },
            "roof_assembly": {
                "type": "object",
                "description": "Roof assembly: {\"U\": float W/(m²·K), \"area_m2\": float m²}.",
            },
            "window_specs": {
                "type": "array",
                "description": (
                    "Glazing specs: [{\"U\": float W/(m²·K), \"area_m2\": float m², "
                    "\"SHGC\": float 0-1}, ...]. One entry per facade orientation."
                ),
                "items": {"type": "object"},
            },
            "lighting_load_W_per_m2": {
                "type": "number",
                "description": "Installed lighting power density W/m². Typical office: 10–14 W/m².",
            },
            "plug_load_W_per_m2": {
                "type": "number",
                "description": "Plug / equipment load density W/m². Typical office: 10–15 W/m².",
            },
            "hvac_system_type": {
                "type": "string",
                "enum": ["VAV", "PTHP", "CRAC", "chiller"],
                "description": (
                    "HVAC system type: 'VAV' (variable air volume, gas+chiller), "
                    "'PTHP' (packaged terminal heat pump), "
                    "'CRAC' (computer room AC, data centres), "
                    "'chiller' (chilled water plant, gas boiler)."
                ),
            },
            "annual_run_hours": {
                "type": "integer",
                "description": "Annual operating hours (1–8760). Default 8760.",
            },
        },
        "required": [
            "building_type", "floor_area_m2", "climate_zone",
            "wall_assemblies", "roof_assembly", "window_specs",
            "lighting_load_W_per_m2", "plug_load_W_per_m2", "hvac_system_type",
        ],
    },
}


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

async def _run_compliance_report(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        if _REGISTRY_AVAILABLE and err_payload:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    required = [
        "building_type", "floor_area_m2", "climate_zone",
        "wall_assemblies", "roof_assembly", "window_specs",
        "lighting_load_W_per_m2", "plug_load_W_per_m2", "hvac_system_type",
    ]
    for field in required:
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    try:
        spec = ComplianceSpec(
            building_type=str(a["building_type"]),
            floor_area_m2=float(a["floor_area_m2"]),
            climate_zone=str(a["climate_zone"]),
            wall_assemblies=list(a["wall_assemblies"]),
            roof_assembly=dict(a["roof_assembly"]),
            window_specs=list(a["window_specs"]),
            lighting_load_W_per_m2=float(a["lighting_load_W_per_m2"]),
            plug_load_W_per_m2=float(a["plug_load_W_per_m2"]),
            hvac_system_type=str(a["hvac_system_type"]),
            annual_run_hours=int(a.get("annual_run_hours", 8760)),
        )
        report = compute_compliance_report(spec)
    except (ValueError, TypeError) as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    result = {
        "ok": True,
        "total_annual_energy_kWh": report.total_annual_energy_kWh,
        "energy_use_intensity_kWh_per_m2": report.energy_use_intensity_kWh_per_m2,
        "ashrae_90_1_compliance": report.ashrae_90_1_compliance,
        "ashrae_baseline_eui": report.ashrae_baseline_eui,
        "percent_better_than_baseline": report.percent_better_than_baseline,
        "leed_credits_earned": report.leed_credits_earned,
        "recommendations": report.recommendations,
        "honest_caveat": report.honest_caveat,
        "energy_breakdown": report.energy_breakdown,
        "warnings": [],
    }

    if _REGISTRY_AVAILABLE and ok_payload:
        return ok_payload(result)
    return json.dumps(result)


# ---------------------------------------------------------------------------
# Conditional registration (requires kerf_chat registry)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE and ToolSpec and register:
    _compliance_spec = ToolSpec(
        name=_SPEC_DEF["name"],
        description=_SPEC_DEF["description"],
        input_schema=_SPEC_DEF["input_schema"],
    )

    @register(_compliance_spec, write=False)
    async def run_bim_compute_energy_compliance_report(
        ctx: ProjectCtx, args: bytes  # type: ignore[valid-type]
    ) -> str:
        return await _run_compliance_report(ctx, args)

else:
    # Stand-alone mode (tests / no registry): expose the handler directly
    async def run_bim_compute_energy_compliance_report(ctx, args: bytes) -> str:  # type: ignore[misc]
        return await _run_compliance_report(ctx, args)
