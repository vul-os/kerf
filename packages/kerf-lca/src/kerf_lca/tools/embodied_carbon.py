"""
LLM tools: lca_lookup_material and lca_compute_embodied_carbon

Provides direct access to the ICE v3 embodied-carbon database.

DATA SOURCE
-----------
ICE v3.0, Hammond & Jones, University of Bath, 2019.
Open data; not Ecoinvent (license-restricted).

Tools registered
----------------
lca_lookup_material         — resolve a material name → ICE v3 entry
lca_compute_embodied_carbon — mass × factor → kg CO2-eq (cradle-to-gate + EoL)
"""

from __future__ import annotations

import json
from dataclasses import asdict

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_lca._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_lca.database import (
    MATERIAL_DATABASE,
    compute_embodied_carbon as _compute,
    lookup_material as _lookup,
)

# ---------------------------------------------------------------------------
# Tool 1: lca_lookup_material
# ---------------------------------------------------------------------------

lca_lookup_material_spec = ToolSpec(
    name="lca_lookup_material",
    description=(
        "Look up a material in the ICE v3.0 embodied-carbon database "
        "(Hammond & Jones, University of Bath, 2019). "
        "Returns the material's embodied carbon (kg CO2-eq/kg, cradle-to-gate), "
        "recycling factor, end-of-life carbon, and ICE v3 source citation. "
        "Data is ICE v3 open data — NOT Ecoinvent (license-restricted). "
        "Use this before compute_embodied_carbon to verify a material is supported."
    ),
    input_schema={
        "type": "object",
        "required": ["material_name"],
        "properties": {
            "material_name": {
                "type": "string",
                "description": (
                    "Material name or key. Accepts canonical keys "
                    "(e.g. 'steel-virgin', 'aluminum-recycled', 'concrete-mix') "
                    "and common aliases (e.g. 'steel', 'aluminium', 'concrete', "
                    "'nylon', 'abs', 'carbon fiber', 'CFRP', 'plywood'). "
                    "Case-insensitive."
                ),
            },
        },
    },
)


@register(lca_lookup_material_spec)
async def run_lca_lookup_material(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    material_name = a.get("material_name", "")
    if not isinstance(material_name, str) or not material_name.strip():
        return err_payload("'material_name' must be a non-empty string", "BAD_ARGS")

    entry = _lookup(material_name)
    if entry is None:
        known = sorted(MATERIAL_DATABASE.keys())
        return err_payload(
            f"Material '{material_name}' not found in ICE v3 database. "
            f"Known keys: {known[:20]}... (use lca_lookup_material with exact key)",
            "NOT_FOUND",
        )

    result = {
        "material_key": entry.material_name,
        "embodied_carbon_kg_co2_per_kg": entry.embodied_carbon_kg_co2_per_kg,
        "recycling_factor": entry.recycling_factor,
        "end_of_life_kg_co2_per_kg": entry.end_of_life_kg_co2_per_kg,
        "source": entry.source,
        "ice_v3_page": entry.ice_v3_page,
        "epd_url": entry.epd_url,
        "notes": entry.notes,
        "citation": (
            "Hammond & Jones, ICE v3.0, University of Bath, 2019"
            + (f" ({entry.ice_v3_page})" if entry.ice_v3_page else "")
            + " — NOT Ecoinvent (license-restricted)"
        ),
    }
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool 2: lca_compute_embodied_carbon
# ---------------------------------------------------------------------------

lca_compute_embodied_carbon_spec = ToolSpec(
    name="lca_compute_embodied_carbon",
    description=(
        "Compute cradle-to-gate embodied carbon and end-of-life carbon for a "
        "single part using ICE v3.0 reference factors. "
        "Returns: embodied_co2 (kg CO2-eq), end_of_life_co2 (kg CO2-eq), "
        "source citation ('ICE v3'), and caveats. "
        "Data is ICE v3 open data — NOT Ecoinvent (license-restricted). "
        "For multi-part BOMs use the 'lca_report' tool instead."
    ),
    input_schema={
        "type": "object",
        "required": ["part_mass_kg", "material_name"],
        "properties": {
            "part_mass_kg": {
                "type": "number",
                "description": "Mass of the part in kilograms (must be > 0).",
            },
            "material_name": {
                "type": "string",
                "description": (
                    "Material name or key. Accepts canonical keys and aliases. "
                    "Examples: 'steel-virgin', 'aluminum-recycled', 'concrete-mix', "
                    "'nylon-6', 'carbon-fiber', 'polycarbonate'. "
                    "Case-insensitive."
                ),
            },
        },
    },
)


@register(lca_compute_embodied_carbon_spec)
async def run_lca_compute_embodied_carbon(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    material_name = a.get("material_name", "")
    if not isinstance(material_name, str) or not material_name.strip():
        return err_payload("'material_name' must be a non-empty string", "BAD_ARGS")

    try:
        part_mass_kg = float(a.get("part_mass_kg", 0))
    except (TypeError, ValueError):
        return err_payload("'part_mass_kg' must be a positive number", "BAD_ARGS")

    if part_mass_kg <= 0:
        return err_payload("'part_mass_kg' must be > 0", "BAD_ARGS")

    result = _compute(part_mass_kg=part_mass_kg, material_name=material_name)

    if result.get("error"):
        return err_payload(result["error"], "NOT_FOUND")

    return ok_payload(result)
