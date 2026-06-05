"""
LLM tool specs and handlers for 3D rebar detailing + shop drawings.

Tools
-----
rebar_detail_member    — 3D bar placement inside a concrete member solid
rebar_bending_schedule — generate a BS 8666 bar-bending schedule from members
shop_drawing_generate  — fabrication-ready shop + GA drawing data
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_structural._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# rebar_detail_member
# ---------------------------------------------------------------------------

rebar_detail_member_spec = ToolSpec(
    name="rebar_detail_member",
    description=(
        "3D rebar detailing for a rectangular concrete member (beam / column / slab).\n"
        "\n"
        "Places longitudinal bars and closed stirrups/ties inside the concrete solid "
        "with cover offset from member faces. Computes BS 8666:2020 cut lengths for "
        "each bar mark and returns a placement dict with centreline coordinates.\n"
        "\n"
        "Returns:\n"
        "  longitudinal_bars — list of bar instances (mark, shape_code, diameter, "
        "    cut_length, count, mass, centreline)\n"
        "  stirrups — stirrup/tie instances with inner dims A×B\n"
        "  summary  — {total_bar_count, total_mass_kg}\n"
        "\n"
        "Units: mm and kg throughout.\n"
        "Bar sizes: BS 4449 nominal diameters (6, 8, 10, 12, 16, 20, 25, 32, 40, 50 mm)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "member_type":           {"type": "string",  "enum": ["beam", "column", "slab"],
                                      "description": "Member category"},
            "length_mm":             {"type": "number",  "description": "Member length (mm)"},
            "width_mm":              {"type": "number",  "description": "Section width (mm)"},
            "depth_mm":              {"type": "number",  "description": "Section depth/height (mm)"},
            "cover_mm":              {"type": "number",  "description": "Clear cover to stirrup face (mm). Default 25"},
            "long_bar_diameter_mm":  {"type": "integer", "description": "Longitudinal bar diameter (mm). Default 16"},
            "n_bars_bottom":         {"type": "integer", "description": "Bars in bottom layer. Default 3"},
            "n_bars_top":            {"type": "integer", "description": "Bars in top layer. Default 2"},
            "stirrup_diameter_mm":   {"type": "integer", "description": "Stirrup/tie diameter (mm). Default 10"},
            "stirrup_spacing_mm":    {"type": "number",  "description": "Stirrup spacing (mm). Default 200"},
        },
        "required": ["member_type", "length_mm", "width_mm", "depth_mm"],
    },
)


@register(rebar_detail_member_spec, write=False)
async def run_rebar_detail_member(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_structural.rebar_3d import detail_member
        result = detail_member(
            member_type=str(a.get("member_type", "beam")),
            length_mm=float(a["length_mm"]),
            width_mm=float(a["width_mm"]),
            depth_mm=float(a["depth_mm"]),
            cover_mm=float(a.get("cover_mm", 25.0)),
            long_bar_diameter_mm=int(a.get("long_bar_diameter_mm", 16)),
            n_bars_bottom=int(a.get("n_bars_bottom", 3)),
            n_bars_top=int(a.get("n_bars_top", 2)),
            stirrup_diameter_mm=int(a.get("stirrup_diameter_mm", 10)),
            stirrup_spacing_mm=float(a.get("stirrup_spacing_mm", 200.0)),
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    return ok_payload(result)


# ---------------------------------------------------------------------------
# rebar_bending_schedule
# ---------------------------------------------------------------------------

rebar_bending_schedule_spec = ToolSpec(
    name="rebar_bending_schedule",
    description=(
        "Generate a BS 8666:2020 bar-bending schedule from one or more detailed "
        "concrete members.\n"
        "\n"
        "Input is a list of members, each with a member_ref and the bar list from "
        "rebar_detail_member output. Aggregates all bars, computes total lengths and "
        "masses, and returns a printable schedule.\n"
        "\n"
        "Returns:\n"
        "  rows — [{member_ref, bar_mark, bar_type, diameter_mm, shape_code,\n"
        "           cut_length_mm, number_of_bars, total_length_m, mass_kg, dims}]\n"
        "  summary — {total_mass_kg, total_bars, row_count}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "members": {
                "type": "array",
                "description": "List of member detail dicts from rebar_detail_member",
                "items": {
                    "type": "object",
                    "properties": {
                        "member_ref": {"type": "string",  "description": "Member mark e.g. 'B1'"},
                        "all_bars":   {"type": "array",   "description": "Bar list from rebar_detail_member"},
                    },
                    "required": ["member_ref", "all_bars"],
                },
            },
        },
        "required": ["members"],
    },
)


@register(rebar_bending_schedule_spec, write=False)
async def run_rebar_bending_schedule(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    members = a.get("members")
    if not isinstance(members, list) or len(members) == 0:
        return err_payload("'members' must be a non-empty list", "BAD_ARGS")

    try:
        from kerf_structural.rebar_3d import generate_bending_schedule
        result = generate_bending_schedule(members)
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    return ok_payload(result)


# ---------------------------------------------------------------------------
# shop_drawing_generate
# ---------------------------------------------------------------------------

shop_drawing_generate_spec = ToolSpec(
    name="shop_drawing_generate",
    description=(
        "Generate fabrication-ready shop drawing data for an RC member or structure.\n"
        "\n"
        "Produces a multi-sheet drawing dict containing:\n"
        "  Sheet 1 — dimensioned section view + elevation view with rebar marks\n"
        "  Sheet 2 — bar-bending schedule table\n"
        "\n"
        "For GA (general-arrangement) mode (pass multiple members), emits:\n"
        "  Sheet 1 — member location plan\n"
        "  Sheet 2 — assembly marks schedule\n"
        "  Sheet 3 — combined bar-bending schedule\n"
        "\n"
        "Output entities use a drawing-primitive dict format (type, x, y, …) suitable\n"
        "for SVG/DXF rendering by the frontend panel.\n"
        "\n"
        "Remaining gap vs Tekla: no interactive rebar drag-editing or automated\n"
        "clash detection between bars — this covers auto-detailing data generation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string", "enum": ["shop", "ga"],
                "description": "'shop' for single-member shop drawing; 'ga' for multi-member GA. Default 'shop'",
            },
            # Single-member shop drawing fields
            "member_ref":           {"type": "string",  "description": "Member mark (e.g. 'B1')"},
            "member_type":          {"type": "string",  "enum": ["beam", "column", "slab"]},
            "length_mm":            {"type": "number"},
            "width_mm":             {"type": "number"},
            "depth_mm":             {"type": "number"},
            "cover_mm":             {"type": "number",  "description": "Default 25"},
            "long_bar_diameter_mm": {"type": "integer", "description": "Default 16"},
            "n_bars_bottom":        {"type": "integer", "description": "Default 3"},
            "n_bars_top":           {"type": "integer", "description": "Default 2"},
            "stirrup_diameter_mm":  {"type": "integer", "description": "Default 10"},
            "stirrup_spacing_mm":   {"type": "number",  "description": "Default 200"},
            # GA mode: list of members
            "members": {
                "type": "array",
                "description": "For GA mode: list of members with geometry + all_bars from rebar_detail_member",
                "items": {"type": "object"},
            },
            # Drawing metadata
            "title_block": {
                "type": "object",
                "description": "Title block fields: project_name, drawing_title, drawing_number, revision, scale, date, drawn_by, checked_by, client",
            },
            "sheet": {
                "type": "string", "enum": ["A1", "A2", "A3"],
                "description": "Sheet size. Default 'A1'",
            },
        },
        "required": [],
    },
)


@register(shop_drawing_generate_spec, write=False)
async def run_shop_drawing_generate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    mode = str(a.get("mode", "shop")).lower()
    sheet = str(a.get("sheet", "A1"))
    title_block = a.get("title_block", {})

    try:
        if mode == "ga":
            members = a.get("members")
            if not isinstance(members, list) or len(members) == 0:
                return err_payload("GA mode requires 'members' list", "BAD_ARGS")

            from kerf_structural.shop_drawing import generate_ga_drawing
            result = generate_ga_drawing(
                members=members,
                title_block=title_block,
                sheet=sheet,
            )
        else:
            # Single-member shop drawing
            member_ref = str(a.get("member_ref", "M1"))
            member_type = str(a.get("member_type", "beam"))
            length_mm = float(a.get("length_mm", 6000.0))
            width_mm = float(a.get("width_mm", 300.0))
            depth_mm = float(a.get("depth_mm", 600.0))
            cover_mm = float(a.get("cover_mm", 25.0))
            long_d = int(a.get("long_bar_diameter_mm", 16))
            n_bot = int(a.get("n_bars_bottom", 3))
            n_top = int(a.get("n_bars_top", 2))
            stir_d = int(a.get("stirrup_diameter_mm", 10))
            stir_sp = float(a.get("stirrup_spacing_mm", 200.0))

            # First detail the member to get bar list
            from kerf_structural.rebar_3d import detail_member, generate_bending_schedule
            detail = detail_member(
                member_type=member_type,
                length_mm=length_mm,
                width_mm=width_mm,
                depth_mm=depth_mm,
                cover_mm=cover_mm,
                long_bar_diameter_mm=long_d,
                n_bars_bottom=n_bot,
                n_bars_top=n_top,
                stirrup_diameter_mm=stir_d,
                stirrup_spacing_mm=stir_sp,
            )
            sched = generate_bending_schedule([{
                "member_ref": member_ref,
                "all_bars": detail["all_bars"],
            }])

            from kerf_structural.shop_drawing import generate_shop_drawing
            result = generate_shop_drawing(
                member_ref=member_ref,
                member_type=member_type,
                length_mm=length_mm,
                width_mm=width_mm,
                depth_mm=depth_mm,
                cover_mm=cover_mm,
                long_bar_diameter_mm=long_d,
                n_bars_bottom=n_bot,
                n_bars_top=n_top,
                stirrup_diameter_mm=stir_d,
                stirrup_spacing_mm=stir_sp,
                bending_schedule_rows=sched["rows"],
                title_block=title_block,
                sheet=sheet,
            )

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    return ok_payload(result)
