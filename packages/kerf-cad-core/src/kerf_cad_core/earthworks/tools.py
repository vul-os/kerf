"""
kerf_cad_core.earthworks.tools — LLM tool wrappers for site earthworks &
grading calculations.

Registers the following tools with the Kerf tool registry:

  earthworks_cross_section      — cross-section area (level / two-level /
                                   three-level / by coordinates)
  earthworks_volume             — volume between stations (average-end-area
                                   or prismoidal)
  earthworks_borrow_pit         — borrow-pit / spot-elevation grid volume
  earthworks_cut_fill_balance   — cut ↔ fill balance with shrinkage/swell
  earthworks_mass_haul          — mass-haul ordinates, balance points,
                                   overhaul cost, borrow/waste
  earthworks_proctor            — Proctor MDD & OMC parabolic fit
  earthworks_relative_compaction — relative compaction % and pass/fail
  earthworks_lift_productivity  — compaction-roller productivity
  earthworks_slope_daylight     — daylight offset for cut/fill batter
  earthworks_trench             — trench excavation volume & shoring/bedding
  earthworks_dewatering         — simplified well-point pump rate

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Peurifoy, Schexnayder, Shapira, "Construction Planning, Equipment & Methods",
  8th ed., McGraw-Hill 2011.
USBR "Design of Small Canal Structures", 1978.
ASTM D698-12e2 / D1557-12e1 — Proctor compaction.
Cedergren, H.R., "Drainage of Highway and Airfield Pavements", Wiley 1974.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.earthworks.grading import (
    cross_section_level,
    cross_section_two_level,
    cross_section_three_level,
    cross_section_by_coords,
    earthwork_volume,
    borrow_pit_volume,
    cut_fill_balance,
    mass_haul,
    proctor_optimum,
    relative_compaction,
    lift_productivity,
    slope_daylight_offset,
    trench_volume,
    dewatering_pump_rate,
)


# ---------------------------------------------------------------------------
# Tool: earthworks_cross_section
# ---------------------------------------------------------------------------

_cross_section_spec = ToolSpec(
    name="earthworks_cross_section",
    description=(
        "Compute the cross-section area for a road/canal cut or fill.\n"
        "\n"
        "Four methods are supported:\n"
        "  'level'       — prismatic level section (uniform ground across the "
        "section); inputs: formation_width, centre_height, side_slope.\n"
        "  'two-level'   — unsymmetrical section with different left/right "
        "batters; inputs: formation_width, centre_height, left_slope, "
        "right_slope.\n"
        "  'three-level' — three measured heights (left edge, centreline, right "
        "edge); inputs: formation_width, centre_height, left_height, "
        "right_height, side_slope.\n"
        "  'by-coords'   — arbitrary polygon defined by xs/ys coordinate "
        "arrays (shoelace formula).\n"
        "\n"
        "Returns area_m2 and relevant geometry.  Never raises; warnings list "
        "flags advisory conditions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["level", "two-level", "three-level", "by-coords"],
                "description": (
                    "Cross-section method (default 'level')."
                ),
            },
            "formation_width": {
                "type": "number",
                "description": "Road/canal formation width (m). > 0. Required for level/two-level/three-level.",
            },
            "centre_height": {
                "type": "number",
                "description": "Cut/fill height at centreline (m). >= 0.",
            },
            "side_slope": {
                "type": "number",
                "description": "Batter H:V (e.g. 1.5). >= 0. Used for level and three-level.",
            },
            "left_slope": {
                "type": "number",
                "description": "Left batter H:V. Used for two-level method. >= 0.",
            },
            "right_slope": {
                "type": "number",
                "description": "Right batter H:V. Used for two-level method. >= 0.",
            },
            "left_height": {
                "type": "number",
                "description": "Cut/fill height at left formation edge (m). >= 0. Used for three-level.",
            },
            "right_height": {
                "type": "number",
                "description": "Cut/fill height at right formation edge (m). >= 0. Used for three-level.",
            },
            "xs": {
                "type": "array",
                "items": {"type": "number"},
                "description": "X-coordinates of cross-section polygon. Used for by-coords method.",
            },
            "ys": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Y-coordinates of cross-section polygon. Used for by-coords method.",
            },
        },
        "required": [],
    },
)


@register(_cross_section_spec, write=False)
async def run_earthworks_cross_section(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    method = a.get("method", "level")
    try:
        if method == "level":
            for f in ("formation_width", "centre_height", "side_slope"):
                if a.get(f) is None:
                    return json.dumps({"ok": False, "reason": f"{f} is required for method='level'"})
            result = cross_section_level(
                a["formation_width"], a["centre_height"], a["side_slope"]
            )
        elif method == "two-level":
            for f in ("formation_width", "centre_height", "left_slope", "right_slope"):
                if a.get(f) is None:
                    return json.dumps({"ok": False, "reason": f"{f} is required for method='two-level'"})
            result = cross_section_two_level(
                a["formation_width"], a["centre_height"],
                a["left_slope"], a["right_slope"],
            )
        elif method == "three-level":
            for f in ("formation_width", "centre_height", "left_height",
                      "right_height", "side_slope"):
                if a.get(f) is None:
                    return json.dumps({"ok": False, "reason": f"{f} is required for method='three-level'"})
            result = cross_section_three_level(
                a["formation_width"], a["centre_height"],
                a["left_height"], a["right_height"], a["side_slope"],
            )
        elif method == "by-coords":
            if a.get("xs") is None or a.get("ys") is None:
                return json.dumps({"ok": False, "reason": "xs and ys are required for method='by-coords'"})
            result = cross_section_by_coords(a["xs"], a["ys"])
        else:
            return json.dumps({"ok": False, "reason": f"unknown method: {method!r}"})
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_volume
# ---------------------------------------------------------------------------

_volume_spec = ToolSpec(
    name="earthworks_volume",
    description=(
        "Compute earthwork volume between a series of cross-section stations.\n"
        "\n"
        "Two methods:\n"
        "  'average-end-area' (default) — V = L × (A1 + A2) / 2\n"
        "  'prismoidal'                 — V = average-end-area − prismoidal correction\n"
        "\n"
        "Stations must be strictly increasing (m).  Areas are cross-section "
        "areas (m²) at each station.  Prismoidal correction volumes (m³) must "
        "be supplied when method='prismoidal', one per interval.\n"
        "\n"
        "Returns per-interval breakdown and total_volume_m3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stations": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Station chainages (m), strictly increasing. Length >= 2.",
            },
            "areas": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Cross-section areas (m²) at each station. Same length as stations.",
            },
            "method": {
                "type": "string",
                "enum": ["average-end-area", "prismoidal"],
                "description": "Volume method (default 'average-end-area').",
            },
            "prismoidal_corrections": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Prismoidal correction volumes (m³) per interval, length = "
                    "len(stations)-1. Required when method='prismoidal'."
                ),
            },
        },
        "required": ["stations", "areas"],
    },
)


@register(_volume_spec, write=False)
async def run_earthworks_volume(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("stations") is None:
        return json.dumps({"ok": False, "reason": "stations is required"})
    if a.get("areas") is None:
        return json.dumps({"ok": False, "reason": "areas is required"})

    kwargs: dict = {}
    if "method" in a:
        kwargs["method"] = a["method"]
    if "prismoidal_corrections" in a:
        kwargs["prismoidal_corrections"] = a["prismoidal_corrections"]

    try:
        result = earthwork_volume(a["stations"], a["areas"], **kwargs)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_borrow_pit
# ---------------------------------------------------------------------------

_borrow_pit_spec = ToolSpec(
    name="earthworks_borrow_pit",
    description=(
        "Compute borrow-pit / spot-elevation grid volume by the four-quadrant "
        "grid method.\n"
        "\n"
        "Each grid node is weighted by its quadrant count (corner=1, edge=2, "
        "interior=4).  The volume at each node = weight × h × cell_area / 4.\n"
        "\n"
        "Positive result = cut (ground above design); negative = fill.\n"
        "\n"
        "Returns total_volume_m3, cut_volume_m3, fill_volume_m3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "grid_spacing_x": {
                "type": "number",
                "description": "Grid cell dimension in x direction (m). > 0.",
            },
            "grid_spacing_y": {
                "type": "number",
                "description": "Grid cell dimension in y direction (m). > 0.",
            },
            "existing_elevations": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                },
                "description": (
                    "2-D array of existing ground elevations (m) [rows][cols]. "
                    "Minimum 2×2."
                ),
            },
            "design_elevation": {
                "type": "number",
                "description": "Uniform design/formation elevation (m).",
            },
        },
        "required": [
            "grid_spacing_x",
            "grid_spacing_y",
            "existing_elevations",
            "design_elevation",
        ],
    },
)


@register(_borrow_pit_spec, write=False)
async def run_earthworks_borrow_pit(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("grid_spacing_x", "grid_spacing_y", "existing_elevations", "design_elevation"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    try:
        result = borrow_pit_volume(
            a["grid_spacing_x"],
            a["grid_spacing_y"],
            a["existing_elevations"],
            a["design_elevation"],
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_cut_fill_balance
# ---------------------------------------------------------------------------

_cut_fill_balance_spec = ToolSpec(
    name="earthworks_cut_fill_balance",
    description=(
        "Balance cut and fill volumes accounting for material shrinkage and swell.\n"
        "\n"
        "Volume states:\n"
        "  Bank (BCM)      — in-situ before excavation\n"
        "  Loose (LCM)     — in truck/scraper after excavation (expanded)\n"
        "  Compacted (CCM) — after compaction in the fill\n"
        "\n"
        "Key factors:\n"
        "  shrinkage_factor = compacted / bank  (e.g. 0.90 for sand-gravel)\n"
        "  swell_factor     = loose / bank       (e.g. 1.25 for typical soil)\n"
        "\n"
        "Returns surplus/deficit in bank measure and borrow/waste flags."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cut_volume_bank_m3": {
                "type": "number",
                "description": "Available cut volume in bank measure (BCM, m³). >= 0.",
            },
            "fill_volume_compacted_m3": {
                "type": "number",
                "description": "Required fill volume in compacted measure (CCM, m³). >= 0.",
            },
            "shrinkage_factor": {
                "type": "number",
                "description": (
                    "Compacted volume / bank volume (default 1.0). "
                    "Sand-gravel ~0.90; expansive clay ~1.05."
                ),
            },
            "swell_factor": {
                "type": "number",
                "description": "Loose volume / bank volume (default 1.0). Typical 1.10–1.35.",
            },
            "load_factor": {
                "type": "number",
                "description": "Bank / loose volume (default 1.0). = 1/swell_factor.",
            },
        },
        "required": ["cut_volume_bank_m3", "fill_volume_compacted_m3"],
    },
)


@register(_cut_fill_balance_spec, write=False)
async def run_earthworks_cut_fill_balance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("cut_volume_bank_m3", "fill_volume_compacted_m3"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    for k in ("shrinkage_factor", "swell_factor", "load_factor"):
        if k in a:
            kwargs[k] = a[k]

    try:
        result = cut_fill_balance(
            a["cut_volume_bank_m3"],
            a["fill_volume_compacted_m3"],
            **kwargs,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_mass_haul
# ---------------------------------------------------------------------------

_mass_haul_spec = ToolSpec(
    name="earthworks_mass_haul",
    description=(
        "Compute the mass-haul diagram: cumulative ordinates, balance points, "
        "free-haul vs overhaul, economic haul distance, and total cost.\n"
        "\n"
        "The mass-haul ordinate at each station is the cumulative (cut − fill) "
        "volume.  Zero-crossings are balance points.  Overhaul is material hauled "
        "beyond the free_haul_distance.\n"
        "\n"
        "Returns ordinates list, balance_points, total cut/fill, borrow/waste "
        "requirements, and cost breakdown."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stations": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Station chainages at interval boundaries (m). Length = N.",
            },
            "cut_volumes": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Cut volume per interval (m³). Length = N-1.",
            },
            "fill_volumes": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Fill volume per interval (m³, positive). Length = N-1.",
            },
            "free_haul_distance": {
                "type": "number",
                "description": "Free-haul distance (m). Default 500.",
            },
            "overhaul_cost_per_m3_station": {
                "type": "number",
                "description": "Cost per m³·m overhaul. Default 0.",
            },
            "borrow_cost_per_m3": {
                "type": "number",
                "description": "Borrow cost per m³ (bank). Default 0.",
            },
            "waste_cost_per_m3": {
                "type": "number",
                "description": "Waste disposal cost per m³ (bank). Default 0.",
            },
        },
        "required": ["stations", "cut_volumes", "fill_volumes"],
    },
)


@register(_mass_haul_spec, write=False)
async def run_earthworks_mass_haul(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("stations", "cut_volumes", "fill_volumes"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    for k in ("free_haul_distance", "overhaul_cost_per_m3_station",
              "borrow_cost_per_m3", "waste_cost_per_m3"):
        if k in a:
            kwargs[k] = a[k]

    try:
        result = mass_haul(a["stations"], a["cut_volumes"], a["fill_volumes"], **kwargs)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_proctor
# ---------------------------------------------------------------------------

_proctor_spec = ToolSpec(
    name="earthworks_proctor",
    description=(
        "Interpolate Proctor compaction curve to find maximum dry density (MDD) "
        "and optimum moisture content (OMC).\n"
        "\n"
        "Fits a parabola ρ_d = a·w² + b·w + c through the supplied "
        "(moisture_content, dry_density) data points.  The peak of the parabola "
        "gives OMC and MDD.\n"
        "\n"
        "Requires >= 3 data points.  Returns poly coefficients and R²."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "moisture_contents": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Moisture contents (%) for each compaction test point. Min 3.",
            },
            "dry_densities": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Dry densities (kg/m³ or Mg/m³) at each point. "
                    "Same length as moisture_contents."
                ),
            },
        },
        "required": ["moisture_contents", "dry_densities"],
    },
)


@register(_proctor_spec, write=False)
async def run_earthworks_proctor(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("moisture_contents") is None:
        return json.dumps({"ok": False, "reason": "moisture_contents is required"})
    if a.get("dry_densities") is None:
        return json.dumps({"ok": False, "reason": "dry_densities is required"})

    try:
        result = proctor_optimum(a["moisture_contents"], a["dry_densities"])
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_relative_compaction
# ---------------------------------------------------------------------------

_rc_spec = ToolSpec(
    name="earthworks_relative_compaction",
    description=(
        "Check field relative compaction against the laboratory MDD and "
        "the specification RC requirement.\n"
        "\n"
        "RC % = 100 × field_dry_density / lab_mdd.\n"
        "\n"
        "Returns rc_percent, pass/fail flag, and deficit if failing."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "field_dry_density": {
                "type": "number",
                "description": "Field dry density from nuclear gauge or sand-cone (kg/m³). > 0.",
            },
            "lab_mdd": {
                "type": "number",
                "description": "Laboratory maximum dry density from Proctor test (kg/m³). > 0.",
            },
            "spec_rc_percent": {
                "type": "number",
                "description": "Required relative compaction (%). Default 95.",
            },
        },
        "required": ["field_dry_density", "lab_mdd"],
    },
)


@register(_rc_spec, write=False)
async def run_earthworks_relative_compaction(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("field_dry_density") is None:
        return json.dumps({"ok": False, "reason": "field_dry_density is required"})
    if a.get("lab_mdd") is None:
        return json.dumps({"ok": False, "reason": "lab_mdd is required"})

    kwargs: dict = {}
    if "spec_rc_percent" in a:
        kwargs["spec_rc_percent"] = a["spec_rc_percent"]

    try:
        result = relative_compaction(
            a["field_dry_density"], a["lab_mdd"], **kwargs
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_lift_productivity
# ---------------------------------------------------------------------------

_lift_prod_spec = ToolSpec(
    name="earthworks_lift_productivity",
    description=(
        "Estimate compaction-roller productivity for a given lift.\n"
        "\n"
        "Productivity (m²/h) = roller_width × speed × efficiency / num_passes.\n"
        "Volume productivity (m³/h) = area × lift_thickness.\n"
        "\n"
        "Returns area_per_hour_m2 and volume_per_hour_m3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "roller_width_m": {
                "type": "number",
                "description": "Effective compaction drum width (m). > 0.",
            },
            "roller_speed_kmh": {
                "type": "number",
                "description": "Average rolling speed (km/h). > 0.",
            },
            "lift_thickness_m": {
                "type": "number",
                "description": "Compacted lift thickness (m). > 0.",
            },
            "num_passes": {
                "type": "integer",
                "description": "Number of roller passes required per lift. >= 1.",
            },
            "efficiency_factor": {
                "type": "number",
                "description": "Job efficiency fraction (0–1). Default 0.75.",
            },
        },
        "required": [
            "roller_width_m",
            "roller_speed_kmh",
            "lift_thickness_m",
            "num_passes",
        ],
    },
)


@register(_lift_prod_spec, write=False)
async def run_earthworks_lift_productivity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("roller_width_m", "roller_speed_kmh", "lift_thickness_m", "num_passes"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "efficiency_factor" in a:
        kwargs["efficiency_factor"] = a["efficiency_factor"]

    try:
        result = lift_productivity(
            a["roller_width_m"],
            a["roller_speed_kmh"],
            a["lift_thickness_m"],
            int(a["num_passes"]),
            **kwargs,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_slope_daylight
# ---------------------------------------------------------------------------

_slope_daylight_spec = ToolSpec(
    name="earthworks_slope_daylight",
    description=(
        "Compute the horizontal offset from the formation edge to the daylight "
        "(hinge) point for a cut or fill slope.\n"
        "\n"
        "  mode='cut'  — formation below ground (cut into hillside)\n"
        "  mode='fill' — formation above ground (embankment)\n"
        "\n"
        "Returns horizontal_offset_m and total_offset_from_cl_m."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "formation_half_width": {
                "type": "number",
                "description": "Half the formation/subgrade width (m). >= 0.",
            },
            "design_height_at_edge": {
                "type": "number",
                "description": "Design surface elevation at formation edge (m).",
            },
            "ground_height_at_edge": {
                "type": "number",
                "description": "Existing ground elevation at formation edge (m).",
            },
            "batter": {
                "type": "number",
                "description": "Batter H:V (e.g. 1.5). >= 0.",
            },
            "mode": {
                "type": "string",
                "enum": ["cut", "fill"],
                "description": "'cut' (default) or 'fill'.",
            },
        },
        "required": [
            "formation_half_width",
            "design_height_at_edge",
            "ground_height_at_edge",
            "batter",
        ],
    },
)


@register(_slope_daylight_spec, write=False)
async def run_earthworks_slope_daylight(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("formation_half_width", "design_height_at_edge",
              "ground_height_at_edge", "batter"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "mode" in a:
        kwargs["mode"] = a["mode"]

    try:
        result = slope_daylight_offset(
            a["formation_half_width"],
            a["design_height_at_edge"],
            a["ground_height_at_edge"],
            a["batter"],
            **kwargs,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_trench
# ---------------------------------------------------------------------------

_trench_spec = ToolSpec(
    name="earthworks_trench",
    description=(
        "Compute trench excavation volume with side batters, bedding, and "
        "shoring quantities.\n"
        "\n"
        "Trapezoidal cross-section: bottom_width at invert, sides battering at "
        "side_slope H:V.  top_width = bottom_width + 2 × side_slope × depth.\n"
        "\n"
        "Returns gross_volume_m3, net_volume_m3 (less pipe), bedding_volume_m3, "
        "shoring_area_m2, and top_width_m."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "length_m": {
                "type": "number",
                "description": "Trench length (m). > 0.",
            },
            "depth_m": {
                "type": "number",
                "description": "Trench depth from surface to invert (m). > 0.",
            },
            "bottom_width_m": {
                "type": "number",
                "description": "Trench bottom width (m). > 0.",
            },
            "side_slope": {
                "type": "number",
                "description": "Batter H:V per side. 0 = vertical (shored). Default 0.",
            },
            "bedding_thickness_m": {
                "type": "number",
                "description": "Bedding thickness below pipe invert (m). Default 0.10.",
            },
            "pipe_od_m": {
                "type": "number",
                "description": "Pipe outer diameter (m) for volume deduction. Default 0.",
            },
            "shoring_area_per_m": {
                "type": "number",
                "description": "Shoring panel area per metre run (m²/m). Default 0.",
            },
        },
        "required": ["length_m", "depth_m", "bottom_width_m"],
    },
)


@register(_trench_spec, write=False)
async def run_earthworks_trench(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("length_m", "depth_m", "bottom_width_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    for k in ("side_slope", "bedding_thickness_m", "pipe_od_m", "shoring_area_per_m"):
        if k in a:
            kwargs[k] = a[k]

    try:
        result = trench_volume(
            a["length_m"], a["depth_m"], a["bottom_width_m"], **kwargs
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: earthworks_dewatering
# ---------------------------------------------------------------------------

_dewatering_spec = ToolSpec(
    name="earthworks_dewatering",
    description=(
        "Estimate the steady-state pump rate for a well-point dewatering system "
        "in an unconfined aquifer using the Dupuit–Thiem formula.\n"
        "\n"
        "  Q = π·K·(H² − hw²) / ln(R / r)\n"
        "\n"
        "where hw = H − drawdown, R = radius of influence, r = equivalent well "
        "radius.  Returns pump_rate in m³/s, m³/h, and L/s."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hydraulic_conductivity_m_s": {
                "type": "number",
                "description": "Hydraulic conductivity K (m/s). > 0.",
            },
            "aquifer_thickness_m": {
                "type": "number",
                "description": "Saturated aquifer thickness H at undisturbed conditions (m). > 0.",
            },
            "drawdown_m": {
                "type": "number",
                "description": "Required drawdown at the well/system (m). > 0, <= aquifer_thickness_m.",
            },
            "radius_of_influence_m": {
                "type": "number",
                "description": "Radius of influence R (m) — distance where drawdown → 0. > 0.",
            },
            "equivalent_well_radius_m": {
                "type": "number",
                "description": "Equivalent radius r of the well/well-point ring (m). > 0, < R.",
            },
        },
        "required": [
            "hydraulic_conductivity_m_s",
            "aquifer_thickness_m",
            "drawdown_m",
            "radius_of_influence_m",
            "equivalent_well_radius_m",
        ],
    },
)


@register(_dewatering_spec, write=False)
async def run_earthworks_dewatering(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("hydraulic_conductivity_m_s", "aquifer_thickness_m", "drawdown_m",
              "radius_of_influence_m", "equivalent_well_radius_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    try:
        result = dewatering_pump_rate(
            a["hydraulic_conductivity_m_s"],
            a["aquifer_thickness_m"],
            a["drawdown_m"],
            a["radius_of_influence_m"],
            a["equivalent_well_radius_m"],
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return json.dumps({"ok": True, **result})
