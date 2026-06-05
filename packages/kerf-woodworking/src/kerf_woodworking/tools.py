"""tools.py — LLM-callable tool surface for kerf-woodworking.

Exposes the following tools to the Kerf LLM agent:

    woodworking_mortise_tenon       — design a mortise-and-tenon joint
    woodworking_dovetail            — design a dovetail joint
    woodworking_finger_joint        — design a box / finger joint
    woodworking_dowel               — design a dowel joint
    woodworking_biscuit             — design a biscuit / plate joint
    woodworking_pocket_screw        — design a pocket-screw joint
    woodworking_cut_list            — generate an optimised cut list
    woodworking_grain_check         — check grain direction on a joint descriptor
    woodworking_hinge_cup_pattern   — generate hinge-cup bore positions
    woodworking_shelf_pin_pattern   — generate shelf-pin bore positions
    woodworking_drawer_runner_pattern — generate drawer runner bore positions
    woodworking_euro_screw_pattern  — generate confirmat/Euro-screw bore positions
    woodworking_handle_pattern      — generate handle/rail through-hole positions
"""

from __future__ import annotations

import json
from typing import Any

from kerf_woodworking._compat import ToolSpec, err_payload, ok_payload, register
from kerf_woodworking.joinery import (
    biscuit,
    dovetail,
    dowel,
    finger_joint,
    mortise_tenon,
    pocket_screw,
)
from kerf_woodworking.cut_list import (
    BoardPiece,
    StockBoard,
    cut_list_to_dict,
    optimise_cut_list,
)
from kerf_woodworking.grain import add_grain_meta, check_grain
from kerf_woodworking.hardware_boring import (
    hinge_cup_pattern,
    shelf_pin_pattern,
    drawer_runner_pattern,
    euro_screw_pattern,
    handle_pattern,
    bore_pattern_to_dict,
)
from kerf_woodworking.joinery_validate import (
    validate_dovetail,
    validate_mortise_and_tenon,
    validate_box_joint,
    validate_finger_joint,
    joinery_strength_estimate,
)


# ---------------------------------------------------------------------------
# Tool: woodworking_mortise_tenon
# ---------------------------------------------------------------------------

_mortise_tenon_spec = ToolSpec(
    name="woodworking_mortise_tenon",
    description=(
        "Design a mortise-and-tenon joint. Returns geometry, engaged volumes, "
        "and any grain warnings. Tenon and mortise volumes are equal when "
        "shoulder_gap_mm is 0."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tenon_width_mm":  {"type": "number", "description": "Tenon cheek width (mm)"},
            "tenon_height_mm": {"type": "number", "description": "Tenon height (mm)"},
            "tenon_depth_mm":  {"type": "number", "description": "Tenon engagement depth (mm)"},
            "shoulder_gap_mm": {"type": "number", "description": "Clearance per cheek face (mm, default 0.2)"},
            "shoulder_grain":  {"type": "string", "enum": ["along", "across", "diagonal", "any"],
                                "description": "Grain direction at tenon shoulder"},
        },
        "required": ["tenon_width_mm", "tenon_height_mm", "tenon_depth_mm"],
    },
)


@register(_mortise_tenon_spec, write=False)
async def woodworking_mortise_tenon(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        joint = mortise_tenon(
            tenon_width_mm=float(a["tenon_width_mm"]),
            tenon_height_mm=float(a["tenon_height_mm"]),
            tenon_depth_mm=float(a["tenon_depth_mm"]),
            shoulder_gap_mm=float(a.get("shoulder_gap_mm", 0.2)),
        )
        if "shoulder_grain" in a:
            add_grain_meta(joint, shoulder_grain=a["shoulder_grain"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(joint)


# ---------------------------------------------------------------------------
# Tool: woodworking_dovetail
# ---------------------------------------------------------------------------

_dovetail_spec = ToolSpec(
    name="woodworking_dovetail",
    description=(
        "Design a through or half-blind dovetail joint. Returns tail geometry "
        "and engagement depth."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "board_thickness_mm": {"type": "number"},
            "tail_count":         {"type": "integer", "description": "Number of tails (default 4)"},
            "tail_angle_deg":     {"type": "number",  "description": "Splay angle in degrees (default 8)"},
            "baseline_offset_mm": {"type": "number",  "description": "Baseline distance from face (default 3)"},
            "half_blind":         {"type": "boolean", "description": "Half-blind dovetail (default false)"},
            "lap_mm":             {"type": "number",  "description": "Front lap thickness (half-blind only)"},
            "board_grain":        {"type": "string",  "enum": ["along", "across", "diagonal", "any"]},
        },
        "required": ["board_thickness_mm"],
    },
)


@register(_dovetail_spec, write=False)
async def woodworking_dovetail(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        joint = dovetail(
            board_thickness_mm=float(a["board_thickness_mm"]),
            tail_count=int(a.get("tail_count", 4)),
            tail_angle_deg=float(a.get("tail_angle_deg", 8.0)),
            baseline_offset_mm=float(a.get("baseline_offset_mm", 3.0)),
            half_blind=bool(a.get("half_blind", False)),
            lap_mm=float(a["lap_mm"]) if "lap_mm" in a else None,
        )
        if "board_grain" in a:
            add_grain_meta(joint, board_grain=a["board_grain"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(joint)


# ---------------------------------------------------------------------------
# Tool: woodworking_finger_joint
# ---------------------------------------------------------------------------

_finger_joint_spec = ToolSpec(
    name="woodworking_finger_joint",
    description="Design a box / finger joint for a given board thickness.",
    input_schema={
        "type": "object",
        "properties": {
            "board_thickness_mm": {"type": "number"},
            "finger_width_mm":    {"type": "number", "description": "Finger width (default 10 mm)"},
            "kerf_mm":            {"type": "number", "description": "Router/saw kerf (default 3.175 mm)"},
        },
        "required": ["board_thickness_mm"],
    },
)


@register(_finger_joint_spec, write=False)
async def woodworking_finger_joint(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        joint = finger_joint(
            board_thickness_mm=float(a["board_thickness_mm"]),
            finger_width_mm=float(a.get("finger_width_mm", 10.0)),
            kerf_mm=float(a.get("kerf_mm", 3.175)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(joint)


# ---------------------------------------------------------------------------
# Tool: woodworking_dowel
# ---------------------------------------------------------------------------

_dowel_spec = ToolSpec(
    name="woodworking_dowel",
    description="Design a dowel joint.",
    input_schema={
        "type": "object",
        "properties": {
            "diameter_mm": {"type": "number", "description": "Dowel diameter (default 8 mm)"},
            "length_mm":   {"type": "number", "description": "Total dowel length (default 40 mm)"},
            "count":       {"type": "integer", "description": "Number of dowels (default 2)"},
            "spacing_mm":  {"type": "number", "description": "Centre-to-centre spacing"},
        },
    },
)


@register(_dowel_spec, write=False)
async def woodworking_dowel(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        joint = dowel(
            diameter_mm=float(a.get("diameter_mm", 8.0)),
            length_mm=float(a.get("length_mm", 40.0)),
            count=int(a.get("count", 2)),
            spacing_mm=float(a["spacing_mm"]) if "spacing_mm" in a else None,
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(joint)


# ---------------------------------------------------------------------------
# Tool: woodworking_biscuit
# ---------------------------------------------------------------------------

_biscuit_spec = ToolSpec(
    name="woodworking_biscuit",
    description="Design a biscuit (plate) joint. Standard sizes: #0, #10, #20.",
    input_schema={
        "type": "object",
        "properties": {
            "size":       {"type": "string", "enum": ["#0", "#10", "#20"],
                           "description": "Biscuit size (default #20)"},
            "count":      {"type": "integer", "description": "Number of biscuits (default 3)"},
            "spacing_mm": {"type": "number",  "description": "Centre-to-centre spacing"},
        },
    },
)


@register(_biscuit_spec, write=False)
async def woodworking_biscuit(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        joint = biscuit(
            size=a.get("size", "#20"),
            count=int(a.get("count", 3)),
            spacing_mm=float(a["spacing_mm"]) if "spacing_mm" in a else None,
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(joint)


# ---------------------------------------------------------------------------
# Tool: woodworking_pocket_screw
# ---------------------------------------------------------------------------

_pocket_screw_spec = ToolSpec(
    name="woodworking_pocket_screw",
    description="Design a pocket-screw (Kreg-style) joint.",
    input_schema={
        "type": "object",
        "properties": {
            "board_thickness_mm": {"type": "number", "description": "Pocket board thickness (default 19 mm)"},
            "screw_diameter_mm":  {"type": "number", "description": "Screw diameter (default 4.5 mm)"},
            "screw_length_mm":    {"type": "number", "description": "Total screw length (default 32 mm)"},
            "count":              {"type": "integer", "description": "Number of screws (default 2)"},
            "spacing_mm":         {"type": "number",  "description": "Centre-to-centre spacing"},
            "target_grain":       {"type": "string",  "enum": ["along", "across", "end", "any"],
                                   "description": "Grain direction of the receiving board"},
        },
    },
)


@register(_pocket_screw_spec, write=False)
async def woodworking_pocket_screw(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        joint = pocket_screw(
            board_thickness_mm=float(a.get("board_thickness_mm", 19.0)),
            screw_diameter_mm=float(a.get("screw_diameter_mm", 4.5)),
            screw_length_mm=float(a.get("screw_length_mm", 32.0)),
            count=int(a.get("count", 2)),
            spacing_mm=float(a["spacing_mm"]) if "spacing_mm" in a else None,
        )
        if "target_grain" in a:
            add_grain_meta(joint, target_grain=a["target_grain"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(joint)


# ---------------------------------------------------------------------------
# Tool: woodworking_cut_list
# ---------------------------------------------------------------------------

_cut_list_spec = ToolSpec(
    name="woodworking_cut_list",
    description=(
        "Generate an optimised cut list (1-D guillotine bin-packing) from a "
        "bill-of-boards and stock size. Returns piece assignments, waste, "
        "utilisation percentage, and off-cut lengths."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pieces": {
                "type": "array",
                "description": "List of required pieces",
                "items": {
                    "type": "object",
                    "properties": {
                        "label":           {"type": "string"},
                        "length_mm":       {"type": "number"},
                        "quantity":        {"type": "integer"},
                        "grain_direction": {"type": "string"},
                    },
                    "required": ["label", "length_mm"],
                },
            },
            "stock_length_mm": {"type": "number", "description": "Uniform stock board length (mm)"},
            "kerf_mm":         {"type": "number", "description": "Saw kerf (default 3.175 mm)"},
            "allow_grain_mismatch": {"type": "boolean"},
        },
        "required": ["pieces", "stock_length_mm"],
    },
)


@register(_cut_list_spec, write=False)
async def woodworking_cut_list(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        pieces_raw = a.get("pieces", [])
        if not isinstance(pieces_raw, list):
            return err_payload("pieces must be an array", "BAD_ARGS")

        pieces = [
            BoardPiece(
                label=p["label"],
                length_mm=float(p["length_mm"]),
                quantity=int(p.get("quantity", 1)),
                grain_direction=p.get("grain_direction", "along"),
            )
            for p in pieces_raw
        ]

        result = optimise_cut_list(
            pieces,
            stock_length_mm=float(a["stock_length_mm"]),
            kerf_mm=float(a.get("kerf_mm", 3.175)),
            allow_grain_mismatch=bool(a.get("allow_grain_mismatch", False)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(cut_list_to_dict(result))


# ---------------------------------------------------------------------------
# Tool: woodworking_grain_check
# ---------------------------------------------------------------------------

_grain_check_spec = ToolSpec(
    name="woodworking_grain_check",
    description=(
        "Check grain-direction metadata on a joint descriptor dict. "
        "Returns a list of grain warnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "joint": {
                "type": "object",
                "description": "Joint descriptor as returned by any woodworking joint tool",
            },
        },
        "required": ["joint"],
    },
)


@register(_grain_check_spec, write=False)
async def woodworking_grain_check(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    joint = a.get("joint")
    if not isinstance(joint, dict):
        return err_payload("joint must be an object", "BAD_ARGS")
    warnings = check_grain(joint)
    return ok_payload({"warnings": warnings})


# ---------------------------------------------------------------------------
# Tool: woodworking_hinge_cup_pattern
# ---------------------------------------------------------------------------

_hinge_cup_spec = ToolSpec(
    name="woodworking_hinge_cup_pattern",
    description=(
        "Generate 35 mm hinge-cup and arm pilot-hole bore positions for a door panel. "
        "Follows the 32 mm System and Blum Clip-Top / INSERTA specifications. "
        "Returns hole centres (x, y), diameters, and depths for CNC machining."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "panel_height_mm": {"type": "number", "description": "Door height (mm)"},
            "panel_width_mm":  {"type": "number", "description": "Door width (mm, default 600)"},
            "panel_thickness_mm": {"type": "number", "description": "Door thickness (mm, default 18)"},
            "overlay_mm":      {"type": "number", "description": "Overlay over carcase (mm, default 0 = full-inset)"},
            "count":           {"type": "integer", "description": "Number of hinges (default 2)"},
        },
        "required": ["panel_height_mm"],
    },
)


@register(_hinge_cup_spec, write=False)
async def woodworking_hinge_cup_pattern(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        pattern = hinge_cup_pattern(
            panel_height_mm=float(a["panel_height_mm"]),
            panel_width_mm=float(a.get("panel_width_mm", 600.0)),
            panel_thickness_mm=float(a.get("panel_thickness_mm", 18.0)),
            overlay_mm=float(a.get("overlay_mm", 0.0)),
            count=int(a.get("count", 2)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(bore_pattern_to_dict(pattern))


# ---------------------------------------------------------------------------
# Tool: woodworking_shelf_pin_pattern
# ---------------------------------------------------------------------------

_shelf_pin_spec = ToolSpec(
    name="woodworking_shelf_pin_pattern",
    description=(
        "Generate 5 mm shelf-pin socket holes on a 32 mm pitch for a cabinet side panel. "
        "Returns two rows of holes (front and rear) at the specified positions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "panel_height_mm": {"type": "number", "description": "Cabinet side panel height (mm)"},
            "panel_width_mm":  {"type": "number", "description": "Cabinet depth (mm, default 600)"},
            "panel_thickness_mm": {"type": "number", "description": "Panel thickness (mm, default 18)"},
            "num_positions":   {"type": "integer", "description": "Number of shelf-pin positions per row (default 10)"},
            "start_y_mm":      {"type": "number", "description": "Y of first hole from bottom (mm, default 96)"},
        },
        "required": ["panel_height_mm"],
    },
)


@register(_shelf_pin_spec, write=False)
async def woodworking_shelf_pin_pattern(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        pattern = shelf_pin_pattern(
            panel_height_mm=float(a["panel_height_mm"]),
            panel_width_mm=float(a.get("panel_width_mm", 600.0)),
            panel_thickness_mm=float(a.get("panel_thickness_mm", 18.0)),
            num_positions=int(a.get("num_positions", 10)),
            start_y_mm=float(a.get("start_y_mm", 96.0)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(bore_pattern_to_dict(pattern))


# ---------------------------------------------------------------------------
# Tool: woodworking_drawer_runner_pattern
# ---------------------------------------------------------------------------

_drawer_runner_spec = ToolSpec(
    name="woodworking_drawer_runner_pattern",
    description=(
        "Generate drawer-runner pilot-hole positions on a cabinet side panel. "
        "Supports undermount (Blum Movento / Tandem) and side-mount runner types."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "panel_height_mm":  {"type": "number", "description": "Cabinet side panel height (mm)"},
            "drawer_height_mm": {"type": "number", "description": "Drawer box height (mm)"},
            "panel_width_mm":   {"type": "number", "description": "Cabinet depth (mm, default 600)"},
            "runner_type":      {"type": "string", "enum": ["undermount", "sidemount"],
                                 "description": "Runner type (default 'undermount')"},
            "num_drawers":      {"type": "integer", "description": "Number of drawers (default 1)"},
        },
        "required": ["panel_height_mm", "drawer_height_mm"],
    },
)


@register(_drawer_runner_spec, write=False)
async def woodworking_drawer_runner_pattern(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        pattern = drawer_runner_pattern(
            panel_height_mm=float(a["panel_height_mm"]),
            drawer_height_mm=float(a["drawer_height_mm"]),
            panel_width_mm=float(a.get("panel_width_mm", 600.0)),
            runner_type=str(a.get("runner_type", "undermount")),
            num_drawers=int(a.get("num_drawers", 1)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(bore_pattern_to_dict(pattern))


# ---------------------------------------------------------------------------
# Tool: woodworking_euro_screw_pattern
# ---------------------------------------------------------------------------

_euro_screw_spec = ToolSpec(
    name="woodworking_euro_screw_pattern",
    description=(
        "Generate Confirmat / Euro-screw face pilot-hole positions for RTA panel joints "
        "(shelf-to-side or floor-to-side connections). "
        "Returns 5 mm pilot holes on the face panel at the specified edge."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "panel_width_mm":  {"type": "number", "description": "Panel width (mm)"},
            "panel_height_mm": {"type": "number", "description": "Panel height (mm)"},
            "panel_thickness_mm": {"type": "number", "description": "Panel thickness (mm, default 18)"},
            "edge":    {"type": "string", "enum": ["bottom", "top", "left", "right"],
                        "description": "Which edge is being joined (default 'bottom')"},
            "spacing_mm": {"type": "number", "description": "Screw spacing (mm, default 128)"},
            "count":      {"type": "integer", "description": "Number of screws (default 2)"},
        },
        "required": ["panel_width_mm", "panel_height_mm"],
    },
)


@register(_euro_screw_spec, write=False)
async def woodworking_euro_screw_pattern(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        pattern = euro_screw_pattern(
            panel_width_mm=float(a["panel_width_mm"]),
            panel_height_mm=float(a["panel_height_mm"]),
            panel_thickness_mm=float(a.get("panel_thickness_mm", 18.0)),
            edge=str(a.get("edge", "bottom")),
            spacing_mm=float(a.get("spacing_mm", 128.0)),
            count=int(a.get("count", 2)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(bore_pattern_to_dict(pattern))


# ---------------------------------------------------------------------------
# Tool: woodworking_handle_pattern
# ---------------------------------------------------------------------------

_handle_spec = ToolSpec(
    name="woodworking_handle_pattern",
    description=(
        "Generate handle / rail through-hole positions for a cabinet door or drawer front. "
        "Supports horizontal and vertical handle orientations. "
        "Common centre-to-centre spacings: 96, 128, 160, 192, 224, 256, 320 mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "panel_width_mm":  {"type": "number", "description": "Panel width (mm)"},
            "panel_height_mm": {"type": "number", "description": "Panel height (mm)"},
            "panel_thickness_mm": {"type": "number", "description": "Panel thickness (mm, default 18)"},
            "centres_mm":      {"type": "number", "description": "Handle hole centres (mm, default 128)"},
            "orientation":     {"type": "string", "enum": ["horizontal", "vertical"],
                                "description": "Handle orientation (default 'horizontal')"},
            "offset_from_edge_mm": {"type": "number",
                                    "description": "Distance from chosen edge to hole (mm, default 40)"},
            "edge":            {"type": "string", "enum": ["top", "bottom", "left", "right"],
                                "description": "Edge the handle is near (default 'top')"},
        },
        "required": ["panel_width_mm", "panel_height_mm"],
    },
)


@register(_handle_spec, write=False)
async def woodworking_handle_pattern(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        pattern = handle_pattern(
            panel_width_mm=float(a["panel_width_mm"]),
            panel_height_mm=float(a["panel_height_mm"]),
            panel_thickness_mm=float(a.get("panel_thickness_mm", 18.0)),
            centres_mm=float(a.get("centres_mm", 128.0)),
            orientation=str(a.get("orientation", "horizontal")),
            offset_from_edge_mm=float(a.get("offset_from_edge_mm", 40.0)),
            edge=str(a.get("edge", "top")),
        )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(bore_pattern_to_dict(pattern))


# ---------------------------------------------------------------------------
# Tool: woodworking_validate_joinery
# ---------------------------------------------------------------------------

_validate_joinery_spec = ToolSpec(
    name="woodworking_validate_joinery",
    description=(
        "Validate woodworking joint geometry against master-craftsman proportions "
        "(Hammer-Krenov §6). Supports dovetail, mortise_and_tenon, box_joint, "
        "and finger_joint. Returns valid/invalid with error codes and messages."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "joint_type": {
                "type": "string",
                "enum": ["dovetail", "mortise_and_tenon", "box_joint", "finger_joint"],
                "description": "Type of joint to validate.",
            },
            "geometry": {
                "type": "object",
                "description": (
                    "Joint geometry dict. For dovetail: tail_angle_deg, board_thickness_mm, "
                    "tail_half_width_mm, tail_count. For mortise_and_tenon: board_thickness_mm, "
                    "tenon_width_mm, mortise_width_mm, tenon_depth_mm. For box_joint/finger_joint: "
                    "finger_count, finger_width_mm, board_thickness_mm, finger_depth_mm."
                ),
            },
        },
        "required": ["joint_type", "geometry"],
    },
)


@register(_validate_joinery_spec, write=False)
async def woodworking_validate_joinery(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        joint_type = a.get("joint_type", "")
        geometry = a.get("geometry", {})
        if not isinstance(geometry, dict):
            return err_payload("geometry must be an object", "BAD_ARGS")

        if joint_type == "dovetail":
            result = validate_dovetail(geometry)
        elif joint_type == "mortise_and_tenon":
            result = validate_mortise_and_tenon(geometry)
        elif joint_type == "box_joint":
            result = validate_box_joint(geometry)
        elif joint_type == "finger_joint":
            result = validate_finger_joint(geometry)
        else:
            return err_payload(
                f"Unknown joint_type '{joint_type}'. Choose from: "
                "dovetail, mortise_and_tenon, box_joint, finger_joint",
                "BAD_ARGS",
            )
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(result.to_dict())


# ---------------------------------------------------------------------------
# Tool: woodworking_joinery_strength
# ---------------------------------------------------------------------------

_joinery_strength_spec = ToolSpec(
    name="woodworking_joinery_strength",
    description=(
        "Estimate joint shear strength (kN) using USDA Forest Products Lab shear values "
        "(Wood Handbook Table 5-1) scaled by joint efficiency. "
        "Supports oak, pine, cherry, maple, walnut. "
        "IMPORTANT: Simplified model — apply safety factor ≥ 3× for structural use."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "geometry": {
                "type": "object",
                "description": (
                    "Joint descriptor dict as returned by any joint tool. "
                    "Must include joint_type and engagement_mm."
                ),
            },
            "wood_species": {
                "type": "string",
                "enum": ["oak", "pine", "cherry", "maple", "walnut"],
                "description": "Wood species for shear value lookup. Default: oak.",
            },
        },
        "required": ["geometry"],
    },
)


@register(_joinery_strength_spec, write=False)
async def woodworking_joinery_strength(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    try:
        geometry = a.get("geometry", {})
        if not isinstance(geometry, dict):
            return err_payload("geometry must be an object", "BAD_ARGS")
        species = a.get("wood_species", "oak")
        result = joinery_strength_estimate(geometry, wood_species=species)
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# TOOLS — (name, spec, handler) tuples consumed by plugin._register_tools
# ---------------------------------------------------------------------------

TOOLS: list[tuple[str, Any, Any]] = [
    ("woodworking_mortise_tenon",        _mortise_tenon_spec,   woodworking_mortise_tenon),
    ("woodworking_dovetail",             _dovetail_spec,        woodworking_dovetail),
    ("woodworking_finger_joint",         _finger_joint_spec,    woodworking_finger_joint),
    ("woodworking_dowel",                _dowel_spec,           woodworking_dowel),
    ("woodworking_biscuit",              _biscuit_spec,         woodworking_biscuit),
    ("woodworking_pocket_screw",         _pocket_screw_spec,    woodworking_pocket_screw),
    ("woodworking_cut_list",             _cut_list_spec,        woodworking_cut_list),
    ("woodworking_grain_check",          _grain_check_spec,     woodworking_grain_check),
    ("woodworking_hinge_cup_pattern",    _hinge_cup_spec,       woodworking_hinge_cup_pattern),
    ("woodworking_shelf_pin_pattern",    _shelf_pin_spec,       woodworking_shelf_pin_pattern),
    ("woodworking_drawer_runner_pattern",_drawer_runner_spec,   woodworking_drawer_runner_pattern),
    ("woodworking_euro_screw_pattern",   _euro_screw_spec,      woodworking_euro_screw_pattern),
    ("woodworking_handle_pattern",       _handle_spec,          woodworking_handle_pattern),
    ("woodworking_validate_joinery",     _validate_joinery_spec, woodworking_validate_joinery),
    ("woodworking_joinery_strength",     _joinery_strength_spec, woodworking_joinery_strength),
]
