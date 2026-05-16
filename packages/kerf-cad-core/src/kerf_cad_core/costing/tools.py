"""
kerf_cad_core.costing.tools — LLM tool wrappers for manufacturing should-cost.

Registers tools with the Kerf tool registry:

  costing_cnc           — CNC machining should-cost
  costing_casting       — Sand/investment casting should-cost
  costing_injection     — Injection moulding should-cost
  costing_sheet_metal   — Sheet-metal fabrication should-cost
  costing_printing      — 3D printing should-cost
  costing_assembly      — Assembly labour should-cost
  costing_rollup        — Generic direct-cost roll-up to unit price
  costing_batch_curve   — Unit-cost vs. batch-size breakpoints
  costing_learning_curve— Wright learning curve unit cost
  costing_make_vs_buy   — Make vs. buy comparison

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Boothroyd, Dewhurst & Knight, "Product Design for Manufacture and Assembly"
Wright, T.P. (1936), "Factors Affecting the Cost of Airplanes"

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.costing.estimate import (
    cnc_cost,
    casting_cost,
    injection_cost,
    sheet_metal_cost,
    printing_cost,
    assembly_cost,
    rollup,
    batch_curve,
    learning_curve,
    make_vs_buy,
)


# ---------------------------------------------------------------------------
# Tool: costing_cnc
# ---------------------------------------------------------------------------

_cnc_spec = ToolSpec(
    name="costing_cnc",
    description=(
        "CNC machining parametric should-cost estimate per unit.\n"
        "\n"
        "Computes: direct material + cycle-time × machine-hour-rate "
        "+ setup amortised over batch + tooling amortisation + overhead.\n"
        "\n"
        "Returns unit cost broken down by category plus a warnings list "
        "(e.g. setup-dominated for small batches).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "material_cost": {
                "type": "number",
                "description": "Raw material cost per part (currency units). Must be > 0.",
            },
            "cycle_time_hr": {
                "type": "number",
                "description": "Machine cycle time per part (hours). Must be > 0.",
            },
            "machine_rate_per_hr": {
                "type": "number",
                "description": "All-in machine-hour rate including operator ($/hr). Must be > 0.",
            },
            "setup_time_hr": {
                "type": "number",
                "description": "Setup/changeover time per batch (hours, default 0.5). >= 0.",
            },
            "batch_size": {
                "type": "integer",
                "description": "Parts per batch run (default 1). >= 1.",
            },
            "tooling_cost": {
                "type": "number",
                "description": "Total tooling investment for this job (default 0). >= 0.",
            },
            "tooling_life_parts": {
                "type": "integer",
                "description": "Tooling life in parts (default 1000). >= 1.",
            },
            "overhead_rate": {
                "type": "number",
                "description": "Overhead as fraction of direct machine cost (default 0.15). in [0,1].",
            },
        },
        "required": ["material_cost", "cycle_time_hr", "machine_rate_per_hr"],
    },
)


@register(_cnc_spec, write=False)
async def run_costing_cnc(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("material_cost", "cycle_time_hr", "machine_rate_per_hr"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("setup_time_hr", "batch_size", "tooling_cost",
                "tooling_life_parts", "overhead_rate"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = cnc_cost(a["material_cost"], a["cycle_time_hr"],
                      a["machine_rate_per_hr"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_casting
# ---------------------------------------------------------------------------

_casting_spec = ToolSpec(
    name="costing_casting",
    description=(
        "Sand / investment casting parametric should-cost per unit.\n"
        "\n"
        "Computes: material (adjusted for yield) + pattern/tooling amortisation "
        "+ pour/handling machine time + finishing + overhead.\n"
        "\n"
        "Returns unit cost breakdown and warnings (small batch with high pattern cost).\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "material_cost_per_kg": {
                "type": "number",
                "description": "Alloy cost per kg. Must be > 0.",
            },
            "part_mass_kg": {
                "type": "number",
                "description": "Net part mass (kg). Must be > 0.",
            },
            "yield_fraction": {
                "type": "number",
                "description": "Metal yield fraction (default 0.70). in (0,1].",
            },
            "pattern_cost": {
                "type": "number",
                "description": "Pattern/tooling total cost (default 0). >= 0.",
            },
            "pattern_life_parts": {
                "type": "integer",
                "description": "Pattern life in parts (default 500). >= 1.",
            },
            "finishing_cost_per_part": {
                "type": "number",
                "description": "Finishing/cleaning per part (default 0). >= 0.",
            },
            "machine_rate_per_hr": {
                "type": "number",
                "description": "Pouring/handling machine rate ($/hr, default 80). > 0.",
            },
            "pour_time_hr": {
                "type": "number",
                "description": "Machine time per part (hr, default 0.05). > 0.",
            },
            "batch_size": {
                "type": "integer",
                "description": "Parts per heat/run (default 1). >= 1.",
            },
            "overhead_rate": {
                "type": "number",
                "description": "Overhead fraction on direct costs (default 0.20). in [0,1].",
            },
        },
        "required": ["material_cost_per_kg", "part_mass_kg"],
    },
)


@register(_casting_spec, write=False)
async def run_costing_casting(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("material_cost_per_kg", "part_mass_kg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("yield_fraction", "pattern_cost", "pattern_life_parts",
                "finishing_cost_per_part", "machine_rate_per_hr",
                "pour_time_hr", "batch_size", "overhead_rate"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = casting_cost(a["material_cost_per_kg"], a["part_mass_kg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_injection
# ---------------------------------------------------------------------------

_injection_spec = ToolSpec(
    name="costing_injection",
    description=(
        "Injection moulding parametric should-cost per good part.\n"
        "\n"
        "Computes: material (scrap-adjusted) + machine time / cavities "
        "+ mould amortisation + overhead.\n"
        "\n"
        "Warns for tiny batches and high scrap rates.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "material_cost_per_kg": {
                "type": "number",
                "description": "Polymer resin cost per kg. Must be > 0.",
            },
            "shot_mass_kg": {
                "type": "number",
                "description": "Total shot mass per cycle per cavity (kg). Must be > 0.",
            },
            "scrap_rate": {
                "type": "number",
                "description": "Fraction of parts scrapped (default 0.03). in [0,1).",
            },
            "cycle_time_hr": {
                "type": "number",
                "description": "Injection cycle time per shot (hr, default 0.005). > 0.",
            },
            "machine_rate_per_hr": {
                "type": "number",
                "description": "Machine + operator rate ($/hr, default 120). > 0.",
            },
            "mould_cost": {
                "type": "number",
                "description": "Total mould tooling cost (default 0). >= 0.",
            },
            "mould_life_shots": {
                "type": "integer",
                "description": "Mould life in shots (default 100000). >= 1.",
            },
            "cavities": {
                "type": "integer",
                "description": "Number of cavities in the mould (default 1). >= 1.",
            },
            "batch_size": {
                "type": "integer",
                "description": "Production run size in parts (default 1). >= 1.",
            },
            "overhead_rate": {
                "type": "number",
                "description": "Overhead fraction on direct machine cost (default 0.15). in [0,1].",
            },
        },
        "required": ["material_cost_per_kg", "shot_mass_kg"],
    },
)


@register(_injection_spec, write=False)
async def run_costing_injection(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("material_cost_per_kg", "shot_mass_kg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("scrap_rate", "cycle_time_hr", "machine_rate_per_hr",
                "mould_cost", "mould_life_shots", "cavities",
                "batch_size", "overhead_rate"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = injection_cost(a["material_cost_per_kg"], a["shot_mass_kg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_sheet_metal
# ---------------------------------------------------------------------------

_sheet_metal_spec = ToolSpec(
    name="costing_sheet_metal",
    description=(
        "Sheet-metal fabrication should-cost per part.\n"
        "\n"
        "Computes: blank material + laser/plasma cutting + press-brake bending "
        "+ setup amortisation + overhead.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "blank_area_m2": {
                "type": "number",
                "description": "Developed blank area (m²). Must be > 0.",
            },
            "material_cost_per_kg": {
                "type": "number",
                "description": "Sheet metal cost per kg. Must be > 0.",
            },
            "material_density_kg_m3": {
                "type": "number",
                "description": "Alloy density (kg/m³, e.g. 7850 steel). Must be > 0.",
            },
            "sheet_thickness_m": {
                "type": "number",
                "description": "Sheet thickness (m). Must be > 0.",
            },
            "num_bends": {
                "type": "integer",
                "description": "Number of bends (default 0). >= 0.",
            },
            "bend_time_hr": {
                "type": "number",
                "description": "Press-brake time per bend (hr, default 0.02). > 0.",
            },
            "press_rate_per_hr": {
                "type": "number",
                "description": "Press/brake machine rate ($/hr, default 60). > 0.",
            },
            "laser_cut_rate_per_hr": {
                "type": "number",
                "description": "Laser cutting rate ($/hr, default 80). > 0.",
            },
            "cut_perimeter_m": {
                "type": "number",
                "description": "Cut path length (m, default 0). >= 0.",
            },
            "cut_speed_m_per_hr": {
                "type": "number",
                "description": "Cutting speed (m/hr, default 10). > 0.",
            },
            "setup_cost": {
                "type": "number",
                "description": "Setup/programming cost per batch (default 0). >= 0.",
            },
            "batch_size": {
                "type": "integer",
                "description": "Parts per run (default 1). >= 1.",
            },
            "overhead_rate": {
                "type": "number",
                "description": "Overhead fraction on direct cost (default 0.15). in [0,1].",
            },
        },
        "required": [
            "blank_area_m2",
            "material_cost_per_kg",
            "material_density_kg_m3",
            "sheet_thickness_m",
        ],
    },
)


@register(_sheet_metal_spec, write=False)
async def run_costing_sheet_metal(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("blank_area_m2", "material_cost_per_kg",
                  "material_density_kg_m3", "sheet_thickness_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("num_bends", "bend_time_hr", "press_rate_per_hr",
                "laser_cut_rate_per_hr", "cut_perimeter_m", "cut_speed_m_per_hr",
                "setup_cost", "batch_size", "overhead_rate"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = sheet_metal_cost(
        a["blank_area_m2"], a["material_cost_per_kg"],
        a["material_density_kg_m3"], a["sheet_thickness_m"],
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_printing
# ---------------------------------------------------------------------------

_printing_spec = ToolSpec(
    name="costing_printing",
    description=(
        "3D printing (FDM/SLA/SLS) should-cost per part.\n"
        "\n"
        "Computes: material (including supports) + machine time / batch "
        "+ post-processing + overhead.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "material_volume_cm3": {
                "type": "number",
                "description": "Part volume (cm³). Must be > 0.",
            },
            "material_cost_per_cm3": {
                "type": "number",
                "description": "Material cost per cm³ (filament/resin/powder). Must be > 0.",
            },
            "build_time_hr": {
                "type": "number",
                "description": "Machine build time for this part (hr). Must be > 0.",
            },
            "machine_rate_per_hr": {
                "type": "number",
                "description": "All-in machine-hour rate ($/hr). Must be > 0.",
            },
            "support_volume_fraction": {
                "type": "number",
                "description": "Support volume as fraction of part volume (default 0.15). in [0,1].",
            },
            "post_processing_cost": {
                "type": "number",
                "description": "Post-processing cost per part (default 0). >= 0.",
            },
            "batch_size": {
                "type": "integer",
                "description": "Parts in this build (default 1). >= 1.",
            },
            "machine_utilisation": {
                "type": "number",
                "description": "Fraction of machine time charged (default 0.80). in (0,1].",
            },
            "overhead_rate": {
                "type": "number",
                "description": "Overhead fraction on direct machine cost (default 0.15). in [0,1].",
            },
        },
        "required": [
            "material_volume_cm3",
            "material_cost_per_cm3",
            "build_time_hr",
            "machine_rate_per_hr",
        ],
    },
)


@register(_printing_spec, write=False)
async def run_costing_printing(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("material_volume_cm3", "material_cost_per_cm3",
                  "build_time_hr", "machine_rate_per_hr"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("support_volume_fraction", "post_processing_cost",
                "batch_size", "machine_utilisation", "overhead_rate"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = printing_cost(
        a["material_volume_cm3"], a["material_cost_per_cm3"],
        a["build_time_hr"], a["machine_rate_per_hr"],
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_assembly
# ---------------------------------------------------------------------------

_assembly_spec = ToolSpec(
    name="costing_assembly",
    description=(
        "Labour-time-based assembly should-cost.\n"
        "\n"
        "Accepts a list of operations each with time_hr and rate_per_hr. "
        "Returns total labour + overhead breakdown.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "operations": {
                "type": "array",
                "description": (
                    "List of assembly operations. Each item: "
                    "{\"name\": string (optional), \"time_hr\": number, \"rate_per_hr\": number}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "time_hr": {"type": "number"},
                        "rate_per_hr": {"type": "number"},
                    },
                    "required": ["time_hr", "rate_per_hr"],
                },
            },
            "overhead_rate": {
                "type": "number",
                "description": "Overhead fraction on total labour (default 0.20). in [0,1].",
            },
        },
        "required": ["operations"],
    },
)


@register(_assembly_spec, write=False)
async def run_costing_assembly(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("operations") is None:
        return json.dumps({"ok": False, "reason": "operations is required"})

    kwargs: dict = {}
    if "overhead_rate" in a:
        kwargs["overhead_rate"] = a["overhead_rate"]

    result = assembly_cost(a["operations"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_rollup
# ---------------------------------------------------------------------------

_rollup_spec = ToolSpec(
    name="costing_rollup",
    description=(
        "Generic manufacturing cost roll-up to unit selling price.\n"
        "\n"
        "Waterfall: direct material + labour + machine + setup/batch "
        "+ tooling → direct cost → +overhead% → manufacturing cost "
        "→ +SG&A% → full cost → ÷(1−margin%) → unit price.\n"
        "\n"
        "Flags negative margin and setup-dominated batches in warnings.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "direct_material": {
                "type": "number",
                "description": "Direct material cost per unit. >= 0.",
            },
            "direct_labour": {
                "type": "number",
                "description": "Direct labour cost per unit. >= 0.",
            },
            "machine_cost": {
                "type": "number",
                "description": "Machine cost per unit. >= 0.",
            },
            "setup_cost_per_batch": {
                "type": "number",
                "description": "Total setup cost per batch run (default 0). >= 0.",
            },
            "batch_size": {
                "type": "integer",
                "description": "Batch size (default 1). >= 1.",
            },
            "tooling_amortisation": {
                "type": "number",
                "description": "Tooling amortisation per unit (default 0). >= 0.",
            },
            "overhead_rate": {
                "type": "number",
                "description": "Overhead fraction of direct cost (default 0.20). in [0,1].",
            },
            "sga_rate": {
                "type": "number",
                "description": "SG&A fraction of manufacturing cost (default 0.10). in [0,1].",
            },
            "margin_rate": {
                "type": "number",
                "description": "Gross margin rate (default 0.20 = 20%). in [0,1).",
            },
        },
        "required": ["direct_material", "direct_labour", "machine_cost"],
    },
)


@register(_rollup_spec, write=False)
async def run_costing_rollup(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("direct_material", "direct_labour", "machine_cost"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("setup_cost_per_batch", "batch_size", "tooling_amortisation",
                "overhead_rate", "sga_rate", "margin_rate"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = rollup(
        a["direct_material"], a["direct_labour"], a["machine_cost"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_batch_curve
# ---------------------------------------------------------------------------

_batch_curve_spec = ToolSpec(
    name="costing_batch_curve",
    description=(
        "Compute unit cost vs. batch-size breakpoints.\n"
        "\n"
        "unit_cost(n) = variable_cost_per_unit + fixed_cost_per_run / n\n"
        "\n"
        "Returns a list of {batch_size, unit_cost} breakpoints plus "
        "min/max unit cost.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fixed_cost_per_run": {
                "type": "number",
                "description": "Fixed cost per production run (setup, tooling). >= 0.",
            },
            "variable_cost_per_unit": {
                "type": "number",
                "description": "Variable cost per unit (material, direct labour). >= 0.",
            },
            "batch_sizes": {
                "type": "array",
                "description": "List of batch sizes to evaluate. Each must be >= 1.",
                "items": {"type": "integer"},
            },
        },
        "required": ["fixed_cost_per_run", "variable_cost_per_unit", "batch_sizes"],
    },
)


@register(_batch_curve_spec, write=False)
async def run_costing_batch_curve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("fixed_cost_per_run", "variable_cost_per_unit", "batch_sizes"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = batch_curve(
        a["fixed_cost_per_run"],
        a["variable_cost_per_unit"],
        a["batch_sizes"],
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_learning_curve
# ---------------------------------------------------------------------------

_learning_curve_spec = ToolSpec(
    name="costing_learning_curve",
    description=(
        "Wright (1936) learning curve — unit cost at cumulative production volume.\n"
        "\n"
        "T_n = T_1 × n^b  where b = log(learning_rate) / log(2)\n"
        "\n"
        "Default learning_rate=0.80 (80% Wright curve): each time cumulative "
        "production doubles, unit cost drops to 80% of the previous value.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "t1": {
                "type": "number",
                "description": "Unit cost (or time) at cumulative volume = 1. Must be > 0.",
            },
            "cumulative_volume": {
                "type": "number",
                "description": "Cumulative units produced (including this unit). Must be > 0.",
            },
            "learning_rate": {
                "type": "number",
                "description": "Learning rate (default 0.80 = 80%). in (0, 1].",
            },
        },
        "required": ["t1", "cumulative_volume"],
    },
)


@register(_learning_curve_spec, write=False)
async def run_costing_learning_curve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("t1", "cumulative_volume"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "learning_rate" in a:
        kwargs["learning_rate"] = a["learning_rate"]

    result = learning_curve(a["t1"], a["cumulative_volume"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: costing_make_vs_buy
# ---------------------------------------------------------------------------

_make_vs_buy_spec = ToolSpec(
    name="costing_make_vs_buy",
    description=(
        "Make vs. buy comparison with break-even batch size.\n"
        "\n"
        "Computes annual totals for both options, the break-even volume "
        "(units where make and buy costs are equal), and a 'preferred' "
        "recommendation based on annual volume.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "make_unit_cost": {
                "type": "number",
                "description": "Variable cost to make one unit in-house. Must be > 0.",
            },
            "buy_unit_price": {
                "type": "number",
                "description": "Purchase price per unit from supplier. Must be > 0.",
            },
            "make_fixed_cost": {
                "type": "number",
                "description": "One-time/annual fixed cost of making in-house (default 0). >= 0.",
            },
            "annual_volume": {
                "type": "integer",
                "description": "Annual production/purchase volume (default 1). >= 1.",
            },
            "make_lead_time_days": {
                "type": "number",
                "description": "In-house production lead time (days, default 14). > 0.",
            },
            "buy_lead_time_days": {
                "type": "number",
                "description": "Supplier lead time (days, default 7). > 0.",
            },
        },
        "required": ["make_unit_cost", "buy_unit_price"],
    },
)


@register(_make_vs_buy_spec, write=False)
async def run_costing_make_vs_buy(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("make_unit_cost", "buy_unit_price"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("make_fixed_cost", "annual_volume",
                "make_lead_time_days", "buy_lead_time_days"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = make_vs_buy(a["make_unit_cost"], a["buy_unit_price"], **kwargs)
    return ok_payload(result)
