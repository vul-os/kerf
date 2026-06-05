"""
LLM tool specs and handlers for kerf-entertainment.

Tools
-----
lighting_plot_patch        — Build patch sheet from fixture list; detect DMX conflicts.
lighting_dmx_check         — Check DMX address conflicts for a set of fixtures.
rigging_load_analysis      — Compute hoist reactions + bridle leg tensions.
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_entertainment._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# lighting_plot_patch
# ---------------------------------------------------------------------------

lighting_plot_patch_spec = ToolSpec(
    name="lighting_plot_patch",
    description=(
        "Build a theatrical lighting patch sheet from a list of fixture instances. "
        "Returns: instrument count by type, total electrical load (W/A), "
        "DMX conflict list, circuit/dimmer schedule (with overload flags), "
        "patch sheet rows (sorted by channel or dimmer), and magic-sheet data. "
        "Supply voltage defaults to 120 V (North America); use 230 for EU/UK rigs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fixtures": {
                "type": "array",
                "description": "List of fixture instances to patch.",
                "items": {
                    "type": "object",
                    "properties": {
                        "fixture_id":      {"type": "string"},
                        "type_name":       {"type": "string", "description": "Fixture type (e.g. 'ETC Source Four 36°')"},
                        "wattage":         {"type": "number", "description": "Power (W), default 575"},
                        "dmx_footprint":   {"type": "integer", "description": "DMX channel width, default 1"},
                        "weight_kg":       {"type": "number", "description": "Fixture weight (kg), default 4.5"},
                        "position":        {"type": "string", "description": "Hanging position label"},
                        "unit_number":     {"type": "integer", "description": "Unit number on position, default 1"},
                        "channel":         {"type": "integer", "description": "Control channel"},
                        "dimmer":          {"type": "integer", "description": "Dimmer/circuit number"},
                        "dmx_universe":    {"type": "integer", "description": "DMX universe (0-based), default 0"},
                        "dmx_address":     {"type": "integer", "description": "DMX start address 1–512"},
                        "color":           {"type": "string", "description": "Gel/filter code, default 'no color'"},
                        "focus_note":      {"type": "string"},
                        "accessories":     {"type": "array", "items": {"type": "string"}},
                        "note":            {"type": "string"},
                    },
                    "required": ["fixture_id", "dmx_address"],
                },
            },
            "dimmer_capacity_W": {
                "type": "number",
                "description": "Dimmer rated capacity (W), default 2400",
            },
            "supply_voltage": {
                "type": "number",
                "description": "Mains voltage (V), default 120",
            },
            "sort_by": {
                "type": "string",
                "enum": ["channel", "dimmer", "universe", "position"],
                "description": "Patch sheet sort order, default 'channel'",
            },
        },
        "required": ["fixtures"],
    },
)


@register(lighting_plot_patch_spec, write=False)
async def run_lighting_plot_patch(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_entertainment.lighting_plot import (
            FixtureType, FixtureInstance,
            lighting_plot_summary, patch_sheet, magic_sheet,
        )

        raw_fixtures = a.get("fixtures", [])
        if not raw_fixtures:
            return err_payload("'fixtures' list is empty", "BAD_ARGS")

        fixture_list = []
        for raw in raw_fixtures:
            ft = FixtureType(
                type_name=raw.get("type_name", "Unknown"),
                wattage=float(raw.get("wattage", 575.0)),
                dmx_footprint=int(raw.get("dmx_footprint", 1)),
                weight_kg=float(raw.get("weight_kg", 4.5)),
            )
            fi = FixtureInstance(
                fixture_id=raw["fixture_id"],
                fixture_type=ft,
                position=raw.get("position", ""),
                unit_number=int(raw.get("unit_number", 1)),
                channel=int(raw.get("channel", 0)),
                dimmer=int(raw.get("dimmer", 0)),
                dmx_universe=int(raw.get("dmx_universe", 0)),
                dmx_address=int(raw.get("dmx_address", 1)),
                color=raw.get("color", "no color"),
                focus_note=raw.get("focus_note", ""),
                accessories=raw.get("accessories", []),
                note=raw.get("note", ""),
            )
            fixture_list.append(fi)

        dim_cap = float(a.get("dimmer_capacity_W", 2400.0))
        voltage = float(a.get("supply_voltage", 120.0))
        sort_by = a.get("sort_by", "channel")

        summary = lighting_plot_summary(fixture_list, dim_cap, voltage)
        patch = patch_sheet(fixture_list, sort_by=sort_by)
        ms = magic_sheet(fixture_list)

    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    return ok_payload({
        "total_fixtures": summary.total_fixtures,
        "fixture_counts_by_type": summary.fixture_counts_by_type,
        "total_wattage_W": round(summary.total_wattage, 1),
        "total_amperage_A": round(summary.total_amperage, 2),
        "supply_voltage_V": summary.supply_voltage,
        "universes_used": summary.universes_used,
        "dmx_conflicts": [
            {
                "universe": c.universe,
                "address_range": list(c.address_range),
                "fixture_a": c.fixture_a,
                "fixture_b": c.fixture_b,
                "message": c.message,
            }
            for c in summary.dmx_conflicts
        ],
        "circuit_schedule": [
            {
                "dimmer": row.dimmer,
                "fixtures": row.fixtures,
                "total_wattage_W": round(row.total_wattage, 1),
                "total_amperage_A": round(row.total_amperage, 2),
                "channels": row.channels,
                "overloaded": row.overloaded,
                "overload_margin_W": round(row.overload_margin_W, 1),
            }
            for row in summary.circuit_rows
        ],
        "overloaded_circuits": summary.overloaded_circuits,
        "patch_sheet": [
            {
                "channel": row.channel,
                "dimmer": row.dimmer,
                "fixture_ids": row.fixture_ids,
                "position": row.position,
                "unit_number": row.unit_number,
                "dmx_universe": row.dmx_universe,
                "dmx_address": row.dmx_address,
                "dmx_end_address": row.dmx_end_address,
                "fixture_type": row.fixture_type,
                "wattage_W": row.wattage,
                "color": row.color,
                "focus_note": row.focus_note,
                "accessories": row.accessories,
                "note": row.note,
            }
            for row in patch
        ],
        "magic_sheet": [
            {
                "channel": entry.channel,
                "fixture_type": entry.fixture_type,
                "color": entry.color,
                "position": entry.position,
                "focus_note": entry.focus_note,
                "x_ft": entry.x_ft,
                "y_ft": entry.y_ft,
            }
            for entry in ms
        ],
    })


# ---------------------------------------------------------------------------
# lighting_dmx_check
# ---------------------------------------------------------------------------

lighting_dmx_check_spec = ToolSpec(
    name="lighting_dmx_check",
    description=(
        "Check a set of DMX-patched fixtures for address conflicts "
        "(overlapping footprints within the same universe). "
        "Returns a list of conflicting pairs with their overlapping address ranges."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fixtures": {
                "type": "array",
                "description": "Fixtures to check.",
                "items": {
                    "type": "object",
                    "properties": {
                        "fixture_id":    {"type": "string"},
                        "dmx_universe":  {"type": "integer", "description": "Universe (0-based)"},
                        "dmx_address":   {"type": "integer", "description": "Start address 1–512"},
                        "dmx_footprint": {"type": "integer", "description": "Number of addresses, default 1"},
                    },
                    "required": ["fixture_id", "dmx_address"],
                },
            },
        },
        "required": ["fixtures"],
    },
)


@register(lighting_dmx_check_spec, write=False)
async def run_lighting_dmx_check(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_entertainment.lighting_plot import (
            FixtureType, FixtureInstance, check_dmx_conflicts,
        )

        raw_fixtures = a.get("fixtures", [])
        fixture_list = []
        for raw in raw_fixtures:
            ft = FixtureType(dmx_footprint=int(raw.get("dmx_footprint", 1)))
            fi = FixtureInstance(
                fixture_id=raw["fixture_id"],
                fixture_type=ft,
                dmx_universe=int(raw.get("dmx_universe", 0)),
                dmx_address=int(raw.get("dmx_address", 1)),
            )
            fixture_list.append(fi)

        conflicts = check_dmx_conflicts(fixture_list)

    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    return ok_payload({
        "conflict_count": len(conflicts),
        "conflicts_detected": len(conflicts) > 0,
        "conflicts": [
            {
                "universe": c.universe,
                "address_range": list(c.address_range),
                "fixture_a": c.fixture_a,
                "fixture_b": c.fixture_b,
                "message": c.message,
            }
            for c in conflicts
        ],
    })


# ---------------------------------------------------------------------------
# rigging_load_analysis
# ---------------------------------------------------------------------------

rigging_load_analysis_spec = ToolSpec(
    name="rigging_load_analysis",
    description=(
        "Entertainment rigging load analysis (Braceworks-style). "
        "Computes hoist/rigging-point reactions for straight truss segments "
        "with distributed self-weight + concentrated fixture/equipment loads. "
        "Flags overloaded hoists.  Optionally analyses a symmetric two-leg "
        "bridle (T = W / 2cosθ) and warns if angle exceeds ESTA E1.6 60° limit. "
        "Input truss positions and loads in metres, loads in Newtons."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trusses": {
                "type": "array",
                "description": "List of truss segments to analyse.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label":               {"type": "string"},
                        "length_m":            {"type": "number", "description": "Truss length (m)"},
                        "truss_type":          {"type": "string", "description": "Built-in type: F32/F34/F44/F52/F64/FLAT"},
                        "self_weight_N_per_m": {"type": "number", "description": "Override linear weight (N/m)"},
                        "rigging_points": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "position_m":         {"type": "number"},
                                    "label":              {"type": "string"},
                                    "hoist_capacity_N":   {"type": "number", "description": "WLL (N), 0=unchecked"},
                                },
                                "required": ["position_m"],
                            },
                        },
                        "point_loads": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "position_m": {"type": "number"},
                                    "load_N":     {"type": "number"},
                                    "label":      {"type": "string"},
                                },
                                "required": ["position_m", "load_N"],
                            },
                        },
                    },
                    "required": ["length_m"],
                },
            },
            "bridles": {
                "type": "array",
                "description": "Optional symmetric two-leg bridle analyses.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label":                 {"type": "string"},
                        "load_N":                {"type": "number", "description": "Vertical load at pick point (N)"},
                        "horizontal_spread_m":   {"type": "number", "description": "Distance between anchor points (m)"},
                        "vertical_height_m":     {"type": "number", "description": "Height from pick point to anchor plane (m)"},
                        "leg_capacity_N":        {"type": "number", "description": "WLL of each leg (N), 0=unchecked"},
                        "leg_a_label":           {"type": "string"},
                        "leg_b_label":           {"type": "string"},
                    },
                    "required": ["load_N", "horizontal_spread_m", "vertical_height_m"],
                },
            },
        },
        "required": [],
    },
)


@register(rigging_load_analysis_spec, write=False)
async def run_rigging_load_analysis(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_entertainment.rigging import (
            TrussSegment, RiggingPoint, PointLoad,
            analyse_truss, bridle_leg_tension,
        )

        truss_results = []
        for td in a.get("trusses", []):
            rpts = [
                RiggingPoint(
                    position_m=float(r["position_m"]),
                    label=r.get("label", f"Hoist @ {r['position_m']}m"),
                    hoist_capacity_N=float(r.get("hoist_capacity_N", 0.0)),
                )
                for r in td.get("rigging_points", [])
            ]
            pls = [
                PointLoad(
                    position_m=float(p["position_m"]),
                    load_N=float(p["load_N"]),
                    label=p.get("label", ""),
                )
                for p in td.get("point_loads", [])
            ]
            seg = TrussSegment(
                label=td.get("label", "Truss"),
                length_m=float(td["length_m"]),
                truss_type=td.get("truss_type", "F34"),
                self_weight_N_per_m=float(td.get("self_weight_N_per_m", 0.0)),
                rigging_points=rpts,
                point_loads=pls,
            )
            res = analyse_truss(seg)
            truss_results.append({
                "label": res.label,
                "length_m": res.length_m,
                "truss_type": res.truss_type,
                "self_weight_N_per_m": round(res.self_weight_N_per_m, 2),
                "total_self_weight_N": round(res.total_self_weight_N, 1),
                "total_point_load_N": round(res.total_point_load_N, 1),
                "total_load_N": round(res.total_load_N, 1),
                "hoist_results": [
                    {
                        "label": hr.label,
                        "position_m": hr.position_m,
                        "reaction_N": round(hr.reaction_N, 1),
                        "hoist_capacity_N": hr.hoist_capacity_N,
                        "overloaded": hr.overloaded,
                        "overload_margin_N": round(hr.overload_margin_N, 1),
                        "utilisation_ratio": round(hr.utilisation_ratio, 3),
                    }
                    for hr in res.hoist_results
                ],
                "overloaded_hoists": res.overloaded_hoists,
                "equilibrium_check": res.equilibrium_check,
                "equilibrium_error_N": round(res.equilibrium_error_N, 4),
                "warnings": res.warnings,
            })

        bridle_results = []
        for bd in a.get("bridles", []):
            br = bridle_leg_tension(
                load_N=float(bd["load_N"]),
                horizontal_spread_m=float(bd["horizontal_spread_m"]),
                vertical_height_m=float(bd["vertical_height_m"]),
                leg_capacity_N=float(bd.get("leg_capacity_N", 0.0)),
                leg_a_label=bd.get("leg_a_label", "Leg A"),
                leg_b_label=bd.get("leg_b_label", "Leg B"),
            )
            bridle_results.append({
                "label": bd.get("label", "Bridle"),
                "load_N": br.load_N,
                "half_angle_deg": round(br.half_angle_deg, 2),
                "leg_tension_N": round(br.leg_tension_N, 1),
                "leg_a_label": br.leg_a_label,
                "leg_b_label": br.leg_b_label,
                "leg_length_m": round(br.leg_a_length_m, 3),
                "horizontal_spread_m": br.horizontal_spread_m,
                "vertical_height_m": br.vertical_height_m,
                "overloaded": br.overloaded,
                "leg_capacity_N": br.leg_capacity_N,
                "overload_margin_N": round(br.overload_margin_N, 1),
                "warnings": br.warnings,
            })

    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    any_overload = (
        any(t["overloaded_hoists"] for t in truss_results)
        or any(b["overloaded"] for b in bridle_results)
    )

    return ok_payload({
        "any_overload": any_overload,
        "trusses": truss_results,
        "bridles": bridle_results,
    })
