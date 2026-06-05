"""
LLM tool definitions for the kerf-landscape plugin.

Each tool follows the ToolSpec / register pattern used by all Kerf plugins.
All handlers are synchronous — no database access is required for the pure-
computation landscape functions.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_landscape._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# landscape_contours
# ---------------------------------------------------------------------------

landscape_contours_spec = ToolSpec(
    name="landscape_contours",
    description=(
        "Extract iso-contour lines from a DEM elevation grid at specified levels. "
        "Returns a list of line segments per contour level. "
        "Use for terrain visualisation, grading plans, and topo maps."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dem": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": "2-D elevation grid, shape (ny, nx) [m].",
            },
            "x_coords": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Monotonically increasing x positions [m].",
            },
            "y_coords": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Monotonically increasing y positions [m].",
            },
            "levels": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Contour elevations to extract [m].",
            },
        },
        "required": ["dem", "x_coords", "y_coords", "levels"],
    },
)


@register(landscape_contours_spec)
async def run_landscape_contours(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    dem = a.get("dem")
    x_coords = a.get("x_coords")
    y_coords = a.get("y_coords")
    levels = a.get("levels")

    if dem is None or x_coords is None or y_coords is None or levels is None:
        return err_payload("dem, x_coords, y_coords, levels are required", "BAD_ARGS")

    from kerf_landscape.grading import contours_from_dem
    result = contours_from_dem(dem, x_coords, y_coords, levels)
    if not result.get("ok"):
        return err_payload(result.get("reason", "failed"), "ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# landscape_cut_fill
# ---------------------------------------------------------------------------

landscape_cut_fill_spec = ToolSpec(
    name="landscape_cut_fill",
    description=(
        "Compute cut and fill earthwork volumes between an existing DEM and a "
        "design surface. Returns cut_m3, fill_m3, and net balance."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dem_existing": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": "Existing elevation grid [m].",
            },
            "dem_design": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": "Proposed design elevation grid [m], same shape.",
            },
            "cell_width": {"type": "number", "description": "Cell width [m]."},
            "cell_height": {"type": "number", "description": "Cell depth [m]."},
        },
        "required": ["dem_existing", "dem_design", "cell_width", "cell_height"],
    },
)


@register(landscape_cut_fill_spec)
async def run_landscape_cut_fill(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    dem_e = a.get("dem_existing")
    dem_d = a.get("dem_design")
    cw = a.get("cell_width")
    ch = a.get("cell_height")

    if dem_e is None or dem_d is None or cw is None or ch is None:
        return err_payload("dem_existing, dem_design, cell_width, cell_height are required", "BAD_ARGS")

    from kerf_landscape.grading import cut_fill_volumes
    result = cut_fill_volumes(dem_e, dem_d, cw, ch)
    if not result.get("ok"):
        return err_payload(result.get("reason", "failed"), "ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# landscape_runoff
# ---------------------------------------------------------------------------

landscape_runoff_spec = ToolSpec(
    name="landscape_runoff",
    description=(
        "Compute peak surface runoff using the Rational Method: Q = C · i · A. "
        "Returns peak flow in cfs and m³/s. "
        "C = runoff coefficient (0–1), i = intensity [in/hr], A = area [acres]."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {"type": "number", "description": "Runoff coefficient (0–1)."},
            "i_in_per_hr": {"type": "number", "description": "Rainfall intensity [in/hr]."},
            "A_acres": {"type": "number", "description": "Drainage area [acres]."},
        },
        "required": ["C", "i_in_per_hr", "A_acres"],
    },
)


@register(landscape_runoff_spec)
async def run_landscape_runoff(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    C = a.get("C")
    i = a.get("i_in_per_hr")
    A = a.get("A_acres")

    if C is None or i is None or A is None:
        return err_payload("C, i_in_per_hr, A_acres are required", "BAD_ARGS")

    from kerf_landscape.drainage import rational_method
    result = rational_method(float(C), float(i), float(A))
    if not result.get("ok"):
        return err_payload(result.get("reason", "failed"), "ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# landscape_plants
# ---------------------------------------------------------------------------

landscape_plants_spec = ToolSpec(
    name="landscape_plants",
    description=(
        "Query the xeriscape plant catalogue. "
        "Filter by USDA hardiness zone and/or maximum water use level. "
        "Water use levels: very-low, low, moderate, high."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "zone": {
                "type": "integer",
                "description": "USDA hardiness zone (1–13). Omit to return all zones.",
            },
            "max_water_use": {
                "type": "string",
                "enum": ["very-low", "low", "moderate", "high"],
                "description": "Maximum water use level. Omit for no filter.",
            },
        },
    },
)


@register(landscape_plants_spec)
async def run_landscape_plants(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    from kerf_landscape.planting import (
        get_plant_catalogue, filter_by_zone, filter_by_water_use,
    )

    catalogue = get_plant_catalogue()

    if a.get("zone") is not None:
        catalogue = filter_by_zone(catalogue, int(a["zone"]))

    if a.get("max_water_use"):
        catalogue = filter_by_water_use(catalogue, a["max_water_use"])

    return ok_payload({"ok": True, "plants": catalogue, "count": len(catalogue)})


# ---------------------------------------------------------------------------
# landscape_paver_pattern
# ---------------------------------------------------------------------------

landscape_paver_spec = ToolSpec(
    name="landscape_paver_pattern",
    description=(
        "Generate a paver layout for a rectangular area. "
        "Patterns: running-bond, stack-bond, herringbone-45, basketweave. "
        "Returns unit positions, count, and coverage percentage."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "enum": ["running-bond", "stack-bond", "herringbone-45", "basketweave"],
            },
            "area_width": {"type": "number", "description": "Area width [m]."},
            "area_depth": {"type": "number", "description": "Area depth [m]."},
            "unit_w": {"type": "number", "description": "Paver width [m]."},
            "unit_h": {"type": "number", "description": "Paver height/length [m]."},
            "joint": {"type": "number", "description": "Joint width [m] (default 0.003)."},
        },
        "required": ["pattern", "area_width", "area_depth", "unit_w", "unit_h"],
    },
)


@register(landscape_paver_spec)
async def run_landscape_paver_pattern(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = ["pattern", "area_width", "area_depth", "unit_w", "unit_h"]
    for k in required:
        if a.get(k) is None:
            return err_payload(f"{k} is required", "BAD_ARGS")

    from kerf_landscape.hardscape import paver_pattern
    result = paver_pattern(
        pattern=a["pattern"],
        area_width=float(a["area_width"]),
        area_depth=float(a["area_depth"]),
        unit_w=float(a["unit_w"]),
        unit_h=float(a["unit_h"]),
        joint=float(a.get("joint", 0.003)),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "failed"), "ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# landscape_retaining_wall
# ---------------------------------------------------------------------------

landscape_wall_spec = ToolSpec(
    name="landscape_retaining_wall",
    description=(
        "Preliminary retaining wall sizing using Rankine earth-pressure theory. "
        "Returns Ka, total active force, minimum base width, and FoS against overturning."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "height": {"type": "number", "description": "Retained height [m]."},
            "length": {"type": "number", "description": "Wall length [m]."},
            "wall_type": {
                "type": "string",
                "enum": ["gravity", "cantilevered", "segmental"],
                "description": "Wall construction type.",
            },
            "soil_phi_deg": {"type": "number", "description": "Soil friction angle [deg] (default 30)."},
            "soil_gamma": {"type": "number", "description": "Soil unit weight [N/m³] (default 18000)."},
            "surcharge": {"type": "number", "description": "Surface surcharge [Pa] (default 0)."},
        },
        "required": ["height", "length"],
    },
)


@register(landscape_wall_spec)
async def run_landscape_retaining_wall(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    if a.get("height") is None or a.get("length") is None:
        return err_payload("height and length are required", "BAD_ARGS")

    from kerf_landscape.hardscape import retaining_wall_layout
    result = retaining_wall_layout(
        height=float(a["height"]),
        length=float(a["length"]),
        wall_type=a.get("wall_type", "gravity"),
        soil_phi_deg=float(a.get("soil_phi_deg", 30.0)),
        soil_gamma=float(a.get("soil_gamma", 18000.0)),
        surcharge=float(a.get("surcharge", 0.0)),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "failed"), "ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# landscape_irrigation_schedule
# ---------------------------------------------------------------------------

landscape_irrigation_spec = ToolSpec(
    name="landscape_irrigation_schedule",
    description=(
        "Generate a weekly irrigation schedule from ETo demand and zone configuration. "
        "Computes zone run times from precipitation rate and weekly ET, then assigns "
        "sequential start times. Also provides Distribution Uniformity (DU) from "
        "catch-can audit data. "
        "Follows ASABE/ICC 802-2014 scheduling and Hunter Irrigation Design Manual."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["schedule", "head_spacing", "zone_flow", "audit"],
                "description": (
                    "Calculation mode: "
                    "'schedule' — weekly run-time schedule, "
                    "'head_spacing' — spacing and throw radius for a head type, "
                    "'zone_flow' — peak flow demand and run time for a zone, "
                    "'audit' — distribution uniformity from catch-can data."
                ),
            },
            "zones": {
                "type": "array",
                "description": "Zones for 'schedule' mode: [{name, head_type, precip_rate_in_hr?, area_m2?}].",
                "items": {"type": "object"},
            },
            "et_mm_per_week": {
                "type": "number",
                "description": "Reference ET [mm/week] for schedule mode (default 25).",
            },
            "days_per_week": {
                "type": "integer",
                "description": "Irrigation days per week for schedule mode (default 3).",
            },
            "controller_start_h": {
                "type": "number",
                "description": "Controller start hour 0–23 (default 5.0 = 5:00 AM).",
            },
            "head_type": {
                "type": "string",
                "enum": ["spray", "rotor", "drip", "bubbler"],
                "description": "Head type for 'head_spacing' and 'zone_flow' modes.",
            },
            "wind_mph": {
                "type": "number",
                "description": "Design wind speed [mph] for 'head_spacing' mode (default 0).",
            },
            "head_count": {
                "type": "integer",
                "description": "Number of heads for 'zone_flow' mode.",
            },
            "gpm_per_head": {
                "type": "number",
                "description": "Flow per head [GPM] for 'zone_flow' mode (optional).",
            },
            "zone_area_m2": {
                "type": "number",
                "description": "Zone area [m²] for 'zone_flow' mode.",
            },
            "precip_rate_in_hr": {
                "type": "number",
                "description": "Zone precipitation rate [in/hr] for 'zone_flow' mode.",
            },
            "target_precip_in": {
                "type": "number",
                "description": "Target irrigation depth [in] for 'zone_flow' mode (default 1.0).",
            },
            "catch_can_readings": {
                "type": "array",
                "description": "Catch-can volumes [mL] for 'audit' mode (min 4).",
                "items": {"type": "number"},
            },
        },
        "required": ["mode"],
    },
)


@register(landscape_irrigation_spec)
async def run_landscape_irrigation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    mode = a.get("mode")
    if mode not in ("schedule", "head_spacing", "zone_flow", "audit"):
        return err_payload("mode must be one of: schedule, head_spacing, zone_flow, audit", "BAD_ARGS")

    from kerf_landscape.irrigation import (
        head_spacing, zone_flow_demand, irrigation_schedule, water_audit,
    )

    if mode == "head_spacing":
        ht = a.get("head_type", "spray")
        wind = float(a.get("wind_mph", 0.0))
        result = head_spacing(ht, wind)

    elif mode == "zone_flow":
        if a.get("head_count") is None:
            return err_payload("head_count is required for zone_flow mode", "BAD_ARGS")
        result = zone_flow_demand(
            head_count=int(a["head_count"]),
            head_type=str(a.get("head_type", "spray")),
            gpm_per_head=float(a["gpm_per_head"]) if a.get("gpm_per_head") is not None else None,
            zone_area_m2=float(a.get("zone_area_m2", 100.0)),
            precip_rate_in_hr=float(a["precip_rate_in_hr"]) if a.get("precip_rate_in_hr") is not None else None,
            target_precip_in=float(a.get("target_precip_in", 1.0)),
        )

    elif mode == "audit":
        readings = a.get("catch_can_readings")
        if not isinstance(readings, list):
            return err_payload("catch_can_readings must be an array for audit mode", "BAD_ARGS")
        result = water_audit(readings)

    else:  # schedule
        zones = a.get("zones")
        if not isinstance(zones, list) or len(zones) == 0:
            return err_payload("zones must be a non-empty array for schedule mode", "BAD_ARGS")
        result = irrigation_schedule(
            zones=zones,
            controller_start_h=float(a.get("controller_start_h", 5.0)),
            et_mm_per_week=float(a.get("et_mm_per_week", 25.0)),
            days_per_week=int(a.get("days_per_week", 3)),
        )

    if not result.get("ok"):
        return err_payload(result.get("reason", "failed"), "ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# landscape_layout_sprinkler
# ---------------------------------------------------------------------------

landscape_layout_sprinkler_spec = ToolSpec(
    name="landscape_layout_sprinkler",
    description=(
        "Place sprinkler heads in a rectangular area using standard spacing patterns. "
        "Returns a list of (x, y, arc_deg) positions and zone breakdown. "
        "Sprinkler models: Hunter_PGP, RainBird_5000, Toro_570Z, Hunter_I20, "
        "RainBird_1800_quarter, Hunter_MP1000, KRain_ProPlus. "
        "Patterns: square (50 % radius), triangular (87 % radius, most uniform), "
        "oblong (55 % radius). "
        "Per Hunter Irrigation Design Manual / Rain Bird head-to-head coverage standard."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width_ft": {
                "type": "number",
                "description": "Rectangle width [ft] (X dimension).",
            },
            "length_ft": {
                "type": "number",
                "description": "Rectangle length [ft] (Y dimension).",
            },
            "sprinkler_kind": {
                "type": "string",
                "enum": [
                    "Hunter_PGP", "RainBird_5000", "Toro_570Z",
                    "Hunter_I20", "RainBird_1800_quarter",
                    "Hunter_MP1000", "KRain_ProPlus",
                ],
                "description": "Sprinkler model key from SPRINKLER_CATALOG.",
            },
            "pattern": {
                "type": "string",
                "enum": ["square", "triangular", "oblong"],
                "description": "Head spacing pattern (default 'square').",
            },
        },
        "required": ["width_ft", "length_ft", "sprinkler_kind"],
    },
)


@register(landscape_layout_sprinkler_spec)
async def run_landscape_layout_sprinkler(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    for k in ("width_ft", "length_ft", "sprinkler_kind"):
        if a.get(k) is None:
            return err_payload(f"{k} is required", "BAD_ARGS")

    try:
        from kerf_landscape.irrigation_design import layout_for_rectangle, SPRINKLER_CATALOG
        positions = layout_for_rectangle(
            width_ft=float(a["width_ft"]),
            length_ft=float(a["length_ft"]),
            sprinkler_kind=str(a["sprinkler_kind"]),
            pattern=str(a.get("pattern", "square")),
        )
    except KeyError as e:
        return err_payload(f"unknown sprinkler_kind: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    sprinkler = SPRINKLER_CATALOG[str(a["sprinkler_kind"])]
    return ok_payload({
        "ok": True,
        "sprinkler_kind": a["sprinkler_kind"],
        "pattern": a.get("pattern", "square"),
        "head_count": len(positions),
        "positions": [{"x": p.x, "y": p.y, "arc_deg": p.arc_deg} for p in positions],
        "sprinkler": {
            "model": sprinkler.model,
            "radius_ft": sprinkler.radius_ft,
            "gpm": sprinkler.gpm,
            "pressure_psi": sprinkler.pressure_psi,
        },
    })


# ---------------------------------------------------------------------------
# landscape_flow_demand
# ---------------------------------------------------------------------------

landscape_flow_demand_spec = ToolSpec(
    name="landscape_flow_demand",
    description=(
        "Compute per-zone irrigation flow demand (GPM) for a sprinkler layout. "
        "Distributes heads across zones round-robin and sums flow per zone "
        "accounting for partial arc (90°/180°/360° heads). "
        "Input: positions list from landscape_layout_sprinkler or manual. "
        "Per Hunter Irrigation Design Manual (2003) unit-conversion constants."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "positions": {
                "type": "array",
                "description": "List of sprinkler positions: [{x, y, arc_deg}].",
                "items": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "arc_deg": {"type": "number"},
                    },
                    "required": ["x", "y", "arc_deg"],
                },
            },
            "zone_count": {
                "type": "integer",
                "description": "Number of irrigation zones (default 4).",
            },
            "sprinkler_kind": {
                "type": "string",
                "enum": [
                    "Hunter_PGP", "RainBird_5000", "Toro_570Z",
                    "Hunter_I20", "RainBird_1800_quarter",
                    "Hunter_MP1000", "KRain_ProPlus",
                ],
                "description": "Sprinkler model key (for GPM rating).",
            },
        },
        "required": ["positions", "sprinkler_kind"],
    },
)


@register(landscape_flow_demand_spec)
async def run_landscape_flow_demand(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    if a.get("positions") is None:
        return err_payload("positions is required", "BAD_ARGS")
    if a.get("sprinkler_kind") is None:
        return err_payload("sprinkler_kind is required", "BAD_ARGS")

    from kerf_landscape.irrigation_design import Position, compute_flow_demand

    try:
        positions = [
            Position(x=float(p["x"]), y=float(p["y"]), arc_deg=float(p["arc_deg"]))
            for p in a["positions"]
        ]
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"malformed positions entry: {e}", "BAD_ARGS")

    try:
        result = compute_flow_demand(
            layout=positions,
            zone_count=int(a.get("zone_count", 4)),
            sprinkler_kind=str(a["sprinkler_kind"]),
        )
    except KeyError as e:
        return err_payload(f"unknown sprinkler_kind: {e}", "BAD_ARGS")

    if not result.get("ok"):
        return err_payload(result.get("reason", "failed"), "ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# landscape_lookup_plant
# ---------------------------------------------------------------------------

_PLANT_DISCLAIMER = (
    "NOT USDA certified — for design assistance only. "
    "Data derived from Dirr MWLP 6th ed. (2009), USDA PHZM (2023), "
    "Missouri Botanical Garden. Verify with local Extension Service."
)

landscape_lookup_plant_spec = ToolSpec(
    name="landscape_lookup_plant",
    description=(
        "Look up a landscape plant species by common or scientific name. "
        "Returns full design-specification attributes: mature dimensions, USDA zone "
        "range, light/water requirements, bloom colour, deer resistance, and notes. "
        "Data: Dirr Manual of Woody Landscape Plants 6th ed. (2009), USDA PHZM (2023). "
        "NOT USDA certified — for design assistance only."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Common name (e.g. 'red maple') or scientific name "
                    "(e.g. 'Acer rubrum').  Case-insensitive."
                ),
            },
        },
        "required": ["name"],
    },
)


@register(landscape_lookup_plant_spec)
async def run_landscape_lookup_plant(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    name = a.get("name")
    if not name:
        return err_payload("name is required", "BAD_ARGS")

    from kerf_landscape.plant_catalog import lookup_plant

    sp = lookup_plant(str(name))
    if sp is None:
        return err_payload(
            f"No plant found for '{name}' — try the scientific or full common name.",
            "NOT_FOUND",
        )

    result = {
        "ok": True,
        "scientific_name": sp.scientific_name,
        "common_name": sp.common_name,
        "kind": sp.kind,
        "mature_height_m": sp.mature_height_m,
        "mature_spread_m": sp.mature_spread_m,
        "growth_rate_cm_per_year": sp.growth_rate_cm_per_year,
        "usda_zones_min": sp.usda_zones_min,
        "usda_zones_max": sp.usda_zones_max,
        "light": sp.light,
        "water": sp.water,
        "soil_type": sp.soil_type,
        "bloom_color": sp.bloom_color,
        "deer_resistant": sp.deer_resistant,
        "notes": sp.notes,
        "regions": list(sp.regions),
        "pollinator_value": sp.pollinator_value,
        "disclaimer": _PLANT_DISCLAIMER,
    }
    return ok_payload(result)


# ---------------------------------------------------------------------------
# landscape_filter_plants
# ---------------------------------------------------------------------------

landscape_filter_plants_spec = ToolSpec(
    name="landscape_filter_plants",
    description=(
        "Filter the native plant catalog by site conditions. "
        "Returns species matching ALL supplied criteria (AND logic). "
        "Filters: usda_zone (1-13), light (full_sun/partial_shade/shade), "
        "water (low/medium/high), kind (deciduous_tree/evergreen/shrub/perennial/"
        "grass/groundcover), deer_resistant (bool). "
        "Data: Dirr MWLP 6th ed. (2009). NOT USDA certified."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "usda_zone": {
                "type": "integer",
                "description": "USDA hardiness zone (1-13). Only return species tolerant at this zone.",
            },
            "light": {
                "type": "string",
                "enum": ["full_sun", "partial_shade", "shade"],
                "description": "Light requirement filter.",
            },
            "water": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Water demand filter (once established).",
            },
            "kind": {
                "type": "string",
                "enum": ["deciduous_tree", "evergreen", "shrub", "perennial", "grass", "groundcover"],
                "description": "Plant category filter.",
            },
            "deer_resistant": {
                "type": "boolean",
                "description": "If true, return only deer-resistant species.",
            },
        },
    },
)


@register(landscape_filter_plants_spec)
async def run_landscape_filter_plants(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    from kerf_landscape.plant_catalog import filter_plants

    usda_zone = int(a["usda_zone"]) if a.get("usda_zone") is not None else None
    light = str(a["light"]) if a.get("light") else None
    water = str(a["water"]) if a.get("water") else None
    kind = str(a["kind"]) if a.get("kind") else None
    deer_resistant = bool(a["deer_resistant"]) if a.get("deer_resistant") is not None else None

    plants = filter_plants(
        usda_zone=usda_zone,
        light=light,
        water=water,
        kind=kind,
        deer_resistant=deer_resistant,
    )

    result = {
        "ok": True,
        "count": len(plants),
        "plants": [
            {
                "scientific_name": sp.scientific_name,
                "common_name": sp.common_name,
                "kind": sp.kind,
                "mature_height_m": sp.mature_height_m,
                "mature_spread_m": sp.mature_spread_m,
                "usda_zones_min": sp.usda_zones_min,
                "usda_zones_max": sp.usda_zones_max,
                "light": sp.light,
                "water": sp.water,
                "bloom_color": sp.bloom_color,
                "deer_resistant": sp.deer_resistant,
                "pollinator_value": sp.pollinator_value,
            }
            for sp in plants
        ],
        "disclaimer": _PLANT_DISCLAIMER,
    }
    return ok_payload(result)
