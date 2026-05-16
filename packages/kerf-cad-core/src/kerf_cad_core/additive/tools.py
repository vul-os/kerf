"""
kerf_cad_core.additive.tools — LLM tool wrappers for additive-manufacturing
process planning / DFAM.

Registers eleven tools with the Kerf tool registry:

  am_process_params           — process parameter record for FDM/SLA/SLS/MJF/DMLS
  am_build_time_estimate      — layer_count × layer_time + travel overhead
  am_support_volume           — support structure volume from overhang projection
  am_overhang_removability    — overhang angle → support need + removability
  am_orientation_cost         — scalar orientation cost (support + height + quality)
  am_best_orientation         — pick lowest-cost orientation from N candidates
  am_shrinkage_compensation   — scale-up dimension for process shrinkage
  am_lattice_infill           — Gibson-Ashby lattice: E_eff, density, mass
  am_feature_checks           — min wall / hole / bridging-span checks
  am_cost_rollup              — machine-hour + material + post cost
  am_nesting_packing          — powder-bed nesting packing factor + batches

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Gibson, I., Rosen, D. & Stucker, B. "Additive Manufacturing Technologies", 2nd ed.
Gibson, L.J. & Ashby, M.F. "Cellular Solids", 2nd ed.
EOS GmbH application notes (SLS/DMLS build-rate data).

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.additive.dfam import (
    process_params,
    build_time_estimate,
    support_volume,
    overhang_removability,
    orientation_cost,
    best_orientation,
    shrinkage_compensation,
    lattice_infill,
    feature_checks,
    cost_rollup,
    nesting_packing,
)

_PROCESS_ENUM = ["FDM", "SLA", "SLS", "MJF", "DMLS"]
_INFILL_ENUM = ["gyroid", "cubic"]


# ---------------------------------------------------------------------------
# Tool: am_process_params
# ---------------------------------------------------------------------------

_process_params_spec = ToolSpec(
    name="am_process_params",
    description=(
        "Return the built-in process parameter record for an additive-manufacturing "
        "process.\n"
        "\n"
        "Supported processes:\n"
        "  FDM  — fused deposition modelling (FFF)\n"
        "  SLA  — stereolithography\n"
        "  SLS  — selective laser sintering (nylon powder)\n"
        "  MJF  — Multi Jet Fusion (HP)\n"
        "  DMLS — direct metal laser sintering\n"
        "\n"
        "Returns overhang threshold, minimum wall/hole/bridge, default layer "
        "thickness, layer time coefficient, default machine rate, and whether "
        "the process uses support structures or is a powder-bed process.\n"
        "\n"
        "Errors: {ok:false, reason} for unknown process.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process: FDM, SLA, SLS, MJF, or DMLS.",
            },
        },
        "required": ["process"],
    },
)


@register(_process_params_spec, write=False)
async def run_am_process_params(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("process") is None:
        return json.dumps({"ok": False, "reason": "process is required"})
    result = process_params(a["process"])
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_build_time_estimate
# ---------------------------------------------------------------------------

_build_time_spec = ToolSpec(
    name="am_build_time_estimate",
    description=(
        "Estimate additive-manufacturing build time.\n"
        "\n"
        "Model:\n"
        "  layer_count     = ceil(build_height / layer_thickness)\n"
        "  time_per_layer  = cross_section_m2 × fill_fraction × layer_time_coeff\n"
        "  deposit_time    = layer_count × time_per_layer\n"
        "  travel_time     = deposit_time × travel_overhead_frac\n"
        "  total_time      = deposit_time + travel_time\n"
        "\n"
        "bounding_box_m is [x, y, z] where z is the build height.\n"
        "cross_section_m2 defaults to x × y.\n"
        "\n"
        "Returns layer_count, build_time_s, build_time_h.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process.",
            },
            "bounding_box_m": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Part bounding box [x, y, z] in metres. z = build height.",
            },
            "layer_thickness_m": {
                "type": "number",
                "description": (
                    "Layer thickness (m). Defaults to process typical value "
                    "(FDM 0.2 mm, SLA 0.1 mm, SLS/MJF 0.1 mm, DMLS 0.06 mm)."
                ),
            },
            "fill_fraction": {
                "type": "number",
                "description": (
                    "Average fill fraction of the cross-sectional area (0–1, "
                    "default 0.20). Accounts for shells, infill, and voids."
                ),
            },
            "travel_overhead_frac": {
                "type": "number",
                "description": (
                    "Fractional travel/recoating overhead (default 0.15 = 15%)."
                ),
            },
            "cross_section_m2": {
                "type": "number",
                "description": "Override average cross-section area (m²). Defaults to x×y.",
            },
        },
        "required": ["process", "bounding_box_m"],
    },
)


@register(_build_time_spec, write=False)
async def run_am_build_time_estimate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("process") is None:
        return json.dumps({"ok": False, "reason": "process is required"})
    if a.get("bounding_box_m") is None:
        return json.dumps({"ok": False, "reason": "bounding_box_m is required"})

    kwargs: dict = {}
    for k in ("layer_thickness_m", "fill_fraction", "travel_overhead_frac", "cross_section_m2"):
        if k in a:
            kwargs[k] = a[k]

    result = build_time_estimate(a["process"], a["bounding_box_m"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_support_volume
# ---------------------------------------------------------------------------

_support_volume_spec = ToolSpec(
    name="am_support_volume",
    description=(
        "Estimate additive-manufacturing support-structure volume.\n"
        "\n"
        "Model:\n"
        "  support_footprint = projected_area × overhang_fraction\n"
        "  support_volume    = support_footprint × support_height × support_density\n"
        "\n"
        "support_height defaults to bounding_z / 2 if bounding_z_m is supplied, "
        "otherwise a conservative estimate from part geometry is used.\n"
        "\n"
        "Returns support_volume_m3 and support_to_part_ratio.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_volume_m3": {
                "type": "number",
                "description": "Solid part volume (m³). Must be > 0.",
            },
            "projected_area_m2": {
                "type": "number",
                "description": "Top-down projected area of the part (m²). Must be > 0.",
            },
            "overhang_fraction": {
                "type": "number",
                "description": (
                    "Fraction of projected area that is overhang (0–1, default 0.20)."
                ),
            },
            "support_density": {
                "type": "number",
                "description": (
                    "Fill density of the support structure (0–1, default 0.15)."
                ),
            },
            "support_height_m": {
                "type": "number",
                "description": "Average height supports span (m). Optional.",
            },
            "bounding_z_m": {
                "type": "number",
                "description": (
                    "Part bounding-box height (m). Used to estimate support_height "
                    "if support_height_m is not supplied."
                ),
            },
        },
        "required": ["part_volume_m3", "projected_area_m2"],
    },
)


@register(_support_volume_spec, write=False)
async def run_am_support_volume(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("part_volume_m3", "projected_area_m2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("overhang_fraction", "support_density", "support_height_m", "bounding_z_m"):
        if k in a:
            kwargs[k] = a[k]

    result = support_volume(a["part_volume_m3"], a["projected_area_m2"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_overhang_removability
# ---------------------------------------------------------------------------

_overhang_removability_spec = ToolSpec(
    name="am_overhang_removability",
    description=(
        "Assess overhang printability and support-removal difficulty for an "
        "additive-manufacturing process.\n"
        "\n"
        "Convention: overhang_angle_deg is measured from the vertical (build "
        "direction).  0° = perfectly vertical wall; 90° = horizontal ceiling.\n"
        "\n"
        "Critical angles:\n"
        "  FDM  — self-supporting up to 45°\n"
        "  SLA  — self-supporting up to 30°\n"
        "  SLS/MJF — always self-supporting (powder bed)\n"
        "  DMLS — self-supporting up to 45°\n"
        "\n"
        "Returns needs_support, removability ('easy'/'moderate'/'difficult'/'N/A'), "
        "and a risk description.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process.",
            },
            "overhang_angle_deg": {
                "type": "number",
                "description": (
                    "Overhang angle from vertical (degrees, 0–90). "
                    "0° = vertical wall; 90° = horizontal ceiling."
                ),
            },
        },
        "required": ["process", "overhang_angle_deg"],
    },
)


@register(_overhang_removability_spec, write=False)
async def run_am_overhang_removability(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("process", "overhang_angle_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = overhang_removability(a["process"], a["overhang_angle_deg"])
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_orientation_cost
# ---------------------------------------------------------------------------

_orientation_cost_spec = ToolSpec(
    name="am_orientation_cost",
    description=(
        "Compute a scalar cost for one candidate build orientation.\n"
        "\n"
        "Cost = w_support × (overhang_area / surface_area)\n"
        "     + w_height  × (build_height / max_bbox_dim)\n"
        "     + w_surface × (surface_area / surface_area_equiv_sphere)\n"
        "\n"
        "Lower cost is better.  The surface-area term penalises orientations "
        "with more staircase-stepped down-facing skin.\n"
        "\n"
        "Returns cost and each sub-term.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process.",
            },
            "part_bbox_m": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Bounding box [x, y, z] for this orientation. z = build height.",
            },
            "surface_area_m2": {
                "type": "number",
                "description": "Total part surface area (m²). Invariant across orientations.",
            },
            "overhang_area_m2": {
                "type": "number",
                "description": "Overhang area requiring support in this orientation (m²).",
            },
            "w_support": {
                "type": "number",
                "description": "Weight for support-fraction term (default 1.0).",
            },
            "w_height": {
                "type": "number",
                "description": "Weight for build-height term (default 0.5).",
            },
            "w_surface": {
                "type": "number",
                "description": "Weight for surface-area/quality term (default 0.3).",
            },
        },
        "required": ["process", "part_bbox_m", "surface_area_m2", "overhang_area_m2"],
    },
)


@register(_orientation_cost_spec, write=False)
async def run_am_orientation_cost(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("process", "part_bbox_m", "surface_area_m2", "overhang_area_m2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("w_support", "w_height", "w_surface"):
        if k in a:
            kwargs[k] = a[k]

    result = orientation_cost(
        a["part_bbox_m"], a["surface_area_m2"], a["overhang_area_m2"], a["process"],
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_best_orientation
# ---------------------------------------------------------------------------

_best_orientation_spec = ToolSpec(
    name="am_best_orientation",
    description=(
        "Select the best build orientation from N candidate bounding boxes.\n"
        "\n"
        "Evaluates the same cost function as am_orientation_cost for each "
        "candidate and returns the index of the lowest-cost orientation.\n"
        "\n"
        "part_bbox_m_list: list of [x, y, z] bounding boxes (one per candidate).\n"
        "overhang_areas_m2: list of overhang areas, same length as part_bbox_m_list.\n"
        "\n"
        "Returns best_index (0-based), best_cost, and all_costs.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process.",
            },
            "part_bbox_m_list": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "List of [x, y, z] bounding boxes for each orientation.",
            },
            "surface_area_m2": {
                "type": "number",
                "description": "Total part surface area (m²).",
            },
            "overhang_areas_m2": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Overhang areas (m²) per candidate orientation.",
            },
            "w_support": {
                "type": "number",
                "description": "Weight for support-fraction term (default 1.0).",
            },
            "w_height": {
                "type": "number",
                "description": "Weight for build-height term (default 0.5).",
            },
            "w_surface": {
                "type": "number",
                "description": "Weight for surface-area/quality term (default 0.3).",
            },
        },
        "required": ["process", "part_bbox_m_list", "surface_area_m2", "overhang_areas_m2"],
    },
)


@register(_best_orientation_spec, write=False)
async def run_am_best_orientation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("process", "part_bbox_m_list", "surface_area_m2", "overhang_areas_m2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("w_support", "w_height", "w_surface"):
        if k in a:
            kwargs[k] = a[k]

    result = best_orientation(
        a["part_bbox_m_list"],
        a["surface_area_m2"],
        a["overhang_areas_m2"],
        a["process"],
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_shrinkage_compensation
# ---------------------------------------------------------------------------

_shrinkage_compensation_spec = ToolSpec(
    name="am_shrinkage_compensation",
    description=(
        "Compute the scale-up factor and compensated model dimension for an "
        "AM process.\n"
        "\n"
        "  compensated_dim = nominal_dim / (1 - shrinkage_fraction)\n"
        "\n"
        "Shrinkage fractions by process (typical):\n"
        "  FDM PLA 0.3%, ABS 0.8%, Nylon 1.2%\n"
        "  SLA resin 0.2–0.3%\n"
        "  SLS/MJF PA12 2.8–3.0% (significant — must compensate)\n"
        "  DMLS 316L 0.1%, Ti6Al4V 0.1%\n"
        "\n"
        "Returns shrinkage_fraction, compensated_dim_m, scale_factor.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nominal_dim_m": {
                "type": "number",
                "description": "Desired finished-part dimension (m). Must be > 0.",
            },
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process.",
            },
            "material": {
                "type": "string",
                "description": (
                    "Material name (process-specific). Default used if unknown. "
                    "FDM: PLA/ABS/PETG/Nylon. SLA: standard_resin/engineering_resin. "
                    "SLS/MJF: PA12/PA11/TPU. DMLS: 316L/AlSi10Mg/Ti6Al4V/Inconel625."
                ),
            },
        },
        "required": ["nominal_dim_m", "process"],
    },
)


@register(_shrinkage_compensation_spec, write=False)
async def run_am_shrinkage_compensation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("nominal_dim_m", "process"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "material" in a:
        kwargs["material"] = a["material"]

    result = shrinkage_compensation(a["nominal_dim_m"], a["process"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_lattice_infill
# ---------------------------------------------------------------------------

_lattice_infill_spec = ToolSpec(
    name="am_lattice_infill",
    description=(
        "Compute Gibson-Ashby lattice effective properties for an AM part.\n"
        "\n"
        "Two infill topologies:\n"
        "  gyroid: bending-dominated — E_eff = 0.3 × ρ_rel² × E_solid\n"
        "  cubic:  stretch-dominated — E_eff = 1.0 × ρ_rel¹ × E_solid\n"
        "\n"
        "Also returns effective density and total mass of the latticed region.\n"
        "\n"
        "Typical parameters (E in GPa):\n"
        "  PLA: E_solid ≈ 3.5 GPa, ρ_solid ≈ 1240 kg/m³\n"
        "  PA12 SLS: E_solid ≈ 1.7 GPa, ρ_solid ≈ 1010 kg/m³\n"
        "  316L DMLS: E_solid ≈ 193 GPa, ρ_solid ≈ 7980 kg/m³\n"
        "\n"
        "Returns effective_modulus_Pa, effective_density_kg_m3, mass_kg, "
        "relative_stiffness.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process (used for printability warnings).",
            },
            "infill_type": {
                "type": "string",
                "enum": _INFILL_ENUM,
                "description": "Lattice topology: 'gyroid' or 'cubic'.",
            },
            "relative_density": {
                "type": "number",
                "description": (
                    "Infill volume fraction (0–1 exclusive). Typical: 0.10–0.50."
                ),
            },
            "solid_modulus_Pa": {
                "type": "number",
                "description": "Young's modulus of the fully dense solid (Pa). Must be > 0.",
            },
            "solid_density_kg_m3": {
                "type": "number",
                "description": "Density of the fully dense solid (kg/m³). Must be > 0.",
            },
            "volume_m3": {
                "type": "number",
                "description": "Bounding volume of the latticed region (m³). Must be > 0.",
            },
        },
        "required": [
            "process", "infill_type", "relative_density",
            "solid_modulus_Pa", "solid_density_kg_m3", "volume_m3",
        ],
    },
)


@register(_lattice_infill_spec, write=False)
async def run_am_lattice_infill(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("process", "infill_type", "relative_density",
                  "solid_modulus_Pa", "solid_density_kg_m3", "volume_m3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = lattice_infill(
        a["process"],
        a["infill_type"],
        a["relative_density"],
        a["solid_modulus_Pa"],
        a["solid_density_kg_m3"],
        a["volume_m3"],
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_feature_checks
# ---------------------------------------------------------------------------

_feature_checks_spec = ToolSpec(
    name="am_feature_checks",
    description=(
        "Check minimum feature sizes and bridging span for an AM process.\n"
        "\n"
        "Minimum feature limits by process:\n"
        "  FDM:  wall ≥ 0.8 mm, hole ≥ 1.5 mm, bridge ≤ 20 mm\n"
        "  SLA:  wall ≥ 0.6 mm, hole ≥ 0.5 mm, bridge ≤ 12 mm\n"
        "  SLS:  wall ≥ 0.7 mm, hole ≥ 1.5 mm, bridge ≤ 60 mm\n"
        "  MJF:  wall ≥ 0.6 mm, hole ≥ 1.5 mm, bridge ≤ 60 mm\n"
        "  DMLS: wall ≥ 0.4 mm, hole ≥ 0.8 mm, bridge ≤ 10 mm\n"
        "\n"
        "At least one of wall_thickness_m / hole_diameter_m / bridge_span_m "
        "must be supplied.  Failures are reported in warnings (ok=True) so "
        "all issues are visible at once.\n"
        "\n"
        "Errors: {ok:false, reason} only for missing/invalid process.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process.",
            },
            "wall_thickness_m": {
                "type": "number",
                "description": "Wall thickness to check (m).",
            },
            "hole_diameter_m": {
                "type": "number",
                "description": "Hole diameter to check (m).",
            },
            "bridge_span_m": {
                "type": "number",
                "description": "Unsupported bridging span to check (m).",
            },
        },
        "required": ["process"],
    },
)


@register(_feature_checks_spec, write=False)
async def run_am_feature_checks(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("process") is None:
        return json.dumps({"ok": False, "reason": "process is required"})

    kwargs: dict = {}
    for k in ("wall_thickness_m", "hole_diameter_m", "bridge_span_m"):
        if k in a:
            kwargs[k] = a[k]

    result = feature_checks(a["process"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_cost_rollup
# ---------------------------------------------------------------------------

_cost_rollup_spec = ToolSpec(
    name="am_cost_rollup",
    description=(
        "Compute total AM part cost from machine time, material, and post-processing.\n"
        "\n"
        "  machine_cost   = build_time_h × machine_rate\n"
        "  material_mass  = (part_volume × fill_fraction + support_volume) × density\n"
        "  material_cost  = material_mass × material_cost_per_kg\n"
        "  total_cost     = machine_cost + material_cost + post_cost\n"
        "\n"
        "Default machine rates (USD/h): FDM $3, SLA $8, SLS $25, MJF $20, DMLS $80\n"
        "Default material costs (USD/kg): PLA $20, PA12 $80, 316L $400\n"
        "\n"
        "Returns machine_cost_usd, material_cost_usd, total_cost_usd.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "process": {
                "type": "string",
                "enum": _PROCESS_ENUM,
                "description": "AM process.",
            },
            "material": {
                "type": "string",
                "description": (
                    "Material name. Determines density and default cost. "
                    "FDM: PLA/ABS/PETG/Nylon. SLA: standard_resin/engineering_resin. "
                    "SLS/MJF: PA12/PA11/TPU. DMLS: 316L/AlSi10Mg/Ti6Al4V/Inconel625."
                ),
            },
            "build_time_s": {
                "type": "number",
                "description": "Total build time (s). Must be > 0.",
            },
            "support_volume_m3": {
                "type": "number",
                "description": "Support structure volume (m³). Must be >= 0.",
            },
            "part_volume_m3": {
                "type": "number",
                "description": "Solid part volume (m³). Must be > 0.",
            },
            "machine_rate_per_h": {
                "type": "number",
                "description": "Machine operating cost (USD/h). Defaults to process default.",
            },
            "material_cost_per_kg": {
                "type": "number",
                "description": "Material feedstock cost (USD/kg). Defaults to material default.",
            },
            "post_cost": {
                "type": "number",
                "description": "Fixed post-processing cost (USD, default 0).",
            },
            "fill_fraction": {
                "type": "number",
                "description": "Infill fraction for material consumption (default 1.0).",
            },
        },
        "required": ["process", "material", "build_time_s", "support_volume_m3", "part_volume_m3"],
    },
)


@register(_cost_rollup_spec, write=False)
async def run_am_cost_rollup(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("process", "material", "build_time_s", "support_volume_m3", "part_volume_m3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("machine_rate_per_h", "material_cost_per_kg", "post_cost", "fill_fraction"):
        if k in a:
            kwargs[k] = a[k]

    result = cost_rollup(
        a["process"],
        a["material"],
        a["build_time_s"],
        a["support_volume_m3"],
        a["part_volume_m3"],
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: am_nesting_packing
# ---------------------------------------------------------------------------

_nesting_packing_spec = ToolSpec(
    name="am_nesting_packing",
    description=(
        "Estimate powder-bed nesting efficiency and batch throughput.\n"
        "\n"
        "  effective_volume  = build_volume × packing_factor\n"
        "  n_max_per_build   = floor(effective_volume / part_volume)\n"
        "  batches_needed    = ceil(n_parts / n_max_per_build)\n"
        "  utilisation       = (n_parts × part_volume) / effective_volume\n"
        "\n"
        "Typical packing factors: SLS/MJF ≈ 0.55–0.70.\n"
        "\n"
        "Returns n_max_per_build, batches_needed, utilisation.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "build_volume_m3": {
                "type": "number",
                "description": "Total build chamber volume (m³). Must be > 0.",
            },
            "part_volume_m3": {
                "type": "number",
                "description": "Volume of one part (m³). Must be > 0.",
            },
            "n_parts": {
                "type": "integer",
                "description": "Number of parts to nest. Must be >= 1.",
            },
            "packing_factor": {
                "type": "number",
                "description": (
                    "Fraction of build volume usable for parts (0–1, default 0.60). "
                    "Typical SLS/MJF: 0.55–0.70."
                ),
            },
        },
        "required": ["build_volume_m3", "part_volume_m3", "n_parts"],
    },
)


@register(_nesting_packing_spec, write=False)
async def run_am_nesting_packing(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("build_volume_m3", "part_volume_m3", "n_parts"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "packing_factor" in a:
        kwargs["packing_factor"] = a["packing_factor"]

    result = nesting_packing(
        a["build_volume_m3"],
        a["part_volume_m3"],
        a["n_parts"],
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)
