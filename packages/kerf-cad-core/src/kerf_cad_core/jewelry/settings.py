"""
kerf_cad_core.jewelry.settings — Parametric stone setting generators.

Twenty-two setting types, each with:
  1. A pure-Python geometry helper that returns a node-spec dict (no OCCT
     required — the dict is consumed by the OCCT worker's opJewelry* handlers).
  2. An LLM tool (ToolSpec + @register runner) following the exact pattern
     in kerf_cad_core.surfacing.

Setting types
-------------
prong_head   — 4-, 6-, basket, trellis, or cathedral prong head.
bezel        — full or partial bezel / collet, with optional taper.
channel      — parallel-rail channel for a row of N calibrated stones.
pave_array   — grid-project over a target region; return placement transforms.
tension      — stone held by spring pressure between two band ends.
flush        — stone set into a drilled seat flush with the metal surface.
halo         — center stone seat ringed by a pavé/accent halo.
three_stone  — center + two graduated side-stone seats on a shared base.
cluster      — N small stones grouped to read as one large stone.
bar          — stones held between parallel metal bars (no prongs between stones).
bead_grain   — stones held by raised metal beads cut up from the surface.
gypsy_pave   — flush-set stones with engraved star/bright-cut accents.
illusion     — faceted metal plate around a small stone to make it look larger.
invisible    — stones with grooved girdles held on a hidden rail.

prong_variant — double, claw, v, fishtail, split, or decorative prong wire variants.
head_gallery  — basket/peg head + decorative gallery rail (plain, scalloped,
                milgrain_edge, pierced, filigree).
under_bezel   — sub-collet that elevates a stone above the shank.
peg_setting   — post head for earrings and pendants.
coronet       — tapered crown of graduated prongs (vintage/Victorian look).

Geometry approach (shared)
--------------------------
Each helper builds a node dict that the OCCT worker evaluates via
BRepPrimAPI / BRepBuilderAPI primitives. No OCCT imports here; all
math is pure Python / optional numpy. The worker receives the node
through the same .feature JSON tree used by pad / sweep1 / boolean.

Units: millimetres throughout.
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

# Re-use helpers from the parent surfacing module.
from kerf_cad_core.surfacing import (
    next_node_id,
    read_feature_content,
    append_feature_node,
)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_PRONG_COUNTS = {4, 6}
_VALID_HEAD_STYLES = {"standard", "basket", "trellis", "cathedral"}
_VALID_BEZEL_STYLES = {"full", "partial", "collet", "tapered"}


def _positive(name: str, value) -> Optional[str]:
    """Return error string if value is not a positive number, else None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number; got {value!r}"
    if v <= 0:
        return f"{name} must be positive; got {v}"
    return None


def _non_negative_int(name: str, value) -> Optional[str]:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return f"{name} must be an integer; got {value!r}"
    if v < 0:
        return f"{name} must be >= 0; got {v}"
    return None


# ---------------------------------------------------------------------------
# Pure-Python geometry helpers (return node-spec dicts)
# ---------------------------------------------------------------------------

def build_prong_head_node(
    node_id: str,
    stone_diameter: float,
    prong_count: int,
    prong_wire_diameter: float,
    prong_height: float,
    head_style: str,
    basket_rail_count: int,
    seat_angle_deg: float,
) -> dict:
    """
    Compute the prong-head node spec.

    The worker's opJewelryProngHead uses these parameters to build:
      - A bearing ledge cylinder of diameter = stone_diameter + 2*wall.
      - `prong_count` round prong wires (diameter = prong_wire_diameter)
        evenly distributed around the stone, each rising prong_height above
        the girdle plane.
      - A horizontal basket rail (or trellis cross-members) if requested.
      - For cathedral style: a vertical arch connecting alternate prongs to
        a lower shank seat.

    Returned dict is appended to the .feature JSON tree.
    """
    # Nominal head outer diameter: stone + one prong wire on each side.
    head_outer_diameter = stone_diameter + 2 * prong_wire_diameter

    # Seat ledge: the bearing surface the girdle of the stone rests on.
    # A 15° (default) inward chamfer holds the stone at seat_angle_deg.
    seat_depth = stone_diameter * math.tan(math.radians(seat_angle_deg)) * 0.1

    return {
        "id": node_id,
        "op": "jewelry_prong_head",
        "stone_diameter": stone_diameter,
        "prong_count": prong_count,
        "prong_wire_diameter": prong_wire_diameter,
        "prong_height": prong_height,
        "head_style": head_style,
        "basket_rail_count": basket_rail_count,
        "seat_angle_deg": seat_angle_deg,
        # Derived geometry hints consumed by the worker (avoids re-computing in JS).
        "_head_outer_diameter": round(head_outer_diameter, 4),
        "_seat_depth": round(seat_depth, 6),
    }


def build_bezel_node(
    node_id: str,
    stone_diameter: float,
    wall_thickness: float,
    bezel_height: float,
    bearing_ledge_height: float,
    bezel_style: str,
    partial_opening_deg: float,
    taper_angle_deg: float,
) -> dict:
    """
    Compute the bezel-setting node spec.

    The worker's opJewelryBezel builds:
      - An outer cylinder (or partial arc) of diameter = stone_diameter + 2*wall.
      - An inner bore to accept the stone (stone_diameter).
      - A horizontal bearing ledge at bearing_ledge_height from the base.
      - For 'partial': a gap of partial_opening_deg cut from the front face
        (common for east-west set ovals and marquise stones).
      - For 'tapered'/'collet': the outer wall inclines inward at taper_angle_deg.

    Partial openings must be in [1, 359] degrees.
    """
    inner_diameter = stone_diameter
    outer_diameter = stone_diameter + 2 * wall_thickness

    return {
        "id": node_id,
        "op": "jewelry_bezel",
        "stone_diameter": stone_diameter,
        "wall_thickness": wall_thickness,
        "bezel_height": bezel_height,
        "bearing_ledge_height": bearing_ledge_height,
        "bezel_style": bezel_style,
        "partial_opening_deg": partial_opening_deg,
        "taper_angle_deg": taper_angle_deg,
        # Worker hints.
        "_inner_diameter": round(inner_diameter, 4),
        "_outer_diameter": round(outer_diameter, 4),
    }


def build_channel_node(
    node_id: str,
    stone_diameter: float,
    stone_count: int,
    stone_spacing: float,
    rail_height: float,
    rail_thickness: float,
    floor_thickness: float,
) -> dict:
    """
    Compute the channel-setting node spec.

    The worker's opJewelryChannel builds two parallel rails separated by
    stone_diameter + rail clearance, with a floor connecting them underneath.
    The channel runs along the X-axis with stones evenly spaced at
    stone_spacing intervals.

    Returns the channel solid node.  The per-stone seat positions are
    available from `seat_positions` in the worker's evaluate result payload
    so a downstream gem-seat op can cut each seat.

    Channel total length = stone_count * stone_spacing.
    """
    channel_length = stone_count * stone_spacing
    # Rail separation: inner face-to-face = stone_diameter (no extra clearance;
    # the worker adds a configurable clearance of 0.05 mm per rail).
    rail_separation = stone_diameter

    return {
        "id": node_id,
        "op": "jewelry_channel",
        "stone_diameter": stone_diameter,
        "stone_count": stone_count,
        "stone_spacing": stone_spacing,
        "rail_height": rail_height,
        "rail_thickness": rail_thickness,
        "floor_thickness": floor_thickness,
        # Worker hints.
        "_channel_length": round(channel_length, 4),
        "_rail_separation": round(rail_separation, 4),
    }


def build_pave_array_node(
    node_id: str,
    region_width: float,
    region_height: float,
    stone_diameter: float,
    stone_spacing: float,
    edge_margin: float,
    surface_normal: list,
    surface_origin: list,
) -> dict:
    """
    Compute the pavé placement array node spec.

    The worker's opJewelryPave projects a rectangular grid onto the target
    surface region and returns a list of placement transforms (4x4 matrix,
    column-major) in the evaluate result.  Each transform positions and
    orients a stone seat so a downstream boolean can cut each seat.

    Grid algorithm (pure Python, replicated in worker for validation):
      1. Effective usable area = (region_width - 2*edge_margin) x
                                 (region_height - 2*edge_margin).
      2. Column pitch = stone_diameter + stone_spacing (centre-to-centre).
      3. Row pitch = column_pitch * sqrt(3)/2 for hex offset, or equal to
         column_pitch for square grid.  This uses square grid (simpler, matches
         calibrated rows on straight channels).
      4. Offset every other row by half a column pitch (hex-offset layout for
         tighter packing density and bead appearance).
      5. Filter any placement whose edge circle would fall outside the usable
         boundary by > 0.01 mm.

    Returns:
      - `placement_count`: integer number of stone positions.
      - `placements`: list of {u, v, row, col} dicts.  The worker converts
        these to full 4x4 world-space transforms and posts them in the result
        payload.  u,v are fractional coordinates [0,1] across the region.
    """
    placements = _compute_pave_grid(
        region_width=region_width,
        region_height=region_height,
        stone_diameter=stone_diameter,
        stone_spacing=stone_spacing,
        edge_margin=edge_margin,
    )

    return {
        "id": node_id,
        "op": "jewelry_pave",
        "region_width": region_width,
        "region_height": region_height,
        "stone_diameter": stone_diameter,
        "stone_spacing": stone_spacing,
        "edge_margin": edge_margin,
        "surface_normal": surface_normal,
        "surface_origin": surface_origin,
        # Placement grid (u,v coords) pre-computed in Python for tests.
        "placements": placements,
        "_placement_count": len(placements),
    }


def _compute_pave_grid(
    region_width: float,
    region_height: float,
    stone_diameter: float,
    stone_spacing: float,
    edge_margin: float,
) -> list:
    """
    Returns list of {u, v, row, col} dicts for all stone positions that fit
    inside the pavé region (with edge_margin clearance).

    u = normalised X position [0, 1] across region_width.
    v = normalised Y position [0, 1] across region_height.

    Uses hex-offset row layout: odd rows are shifted by half a column pitch.
    """
    usable_w = region_width - 2 * edge_margin
    usable_h = region_height - 2 * edge_margin

    if usable_w <= 0 or usable_h <= 0:
        return []

    pitch = stone_diameter + stone_spacing
    if pitch <= 0:
        return []

    # Number of columns and rows in the hex-offset grid.
    n_cols = max(1, int(math.floor(usable_w / pitch)))
    n_rows = max(1, int(math.floor(usable_h / pitch)))

    placements = []
    for row in range(n_rows):
        for col in range(n_cols):
            x = edge_margin + col * pitch + (pitch / 2 if row % 2 == 1 else 0)
            y = edge_margin + row * pitch

            # Half-pitch horizontal offset on odd rows may push the rightmost
            # stone past the usable boundary — skip it.
            if x + stone_diameter / 2 > region_width - edge_margin + 1e-9:
                continue
            if y + stone_diameter / 2 > region_height - edge_margin + 1e-9:
                continue

            u = x / region_width
            v = y / region_height
            placements.append({"u": round(u, 6), "v": round(v, 6), "row": row, "col": col})

    return placements


# ---------------------------------------------------------------------------
# LLM Tool: jewelry_create_prong_head
# ---------------------------------------------------------------------------

jewelry_prong_head_spec = ToolSpec(
    name="jewelry_create_prong_head",
    description=(
        "Append a `jewelry_prong_head` node to a `.feature` file. "
        "Generates a parametric prong-head setting (4-prong, 6-prong, basket, "
        "trellis, or cathedral style) sized to accept a stone of `stone_diameter`. "
        "The head solid includes a bearing ledge at `seat_angle_deg` to seat the "
        "gemstone girdle, `prong_count` round prong wires of `prong_wire_diameter`, "
        "and a basket rail (if `head_style` is 'basket' or 'trellis'). "
        "Output: a TopoDS_Solid head body ready for boolean fuse onto a shank."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of the stone in mm (e.g. 6.5 for a 1 ct round brilliant).",
            },
            "prong_count": {
                "type": "integer",
                "enum": [4, 6],
                "description": "Number of prongs. 4 (square set) or 6 (classic Tiffany).",
            },
            "prong_wire_diameter": {
                "type": "number",
                "description": "Round-wire prong diameter in mm. Typical range 0.8–1.5 mm.",
            },
            "prong_height": {
                "type": "number",
                "description": "Height the prong extends above the stone's girdle plane in mm.",
            },
            "head_style": {
                "type": "string",
                "enum": ["standard", "basket", "trellis", "cathedral"],
                "description": (
                    "Head geometry style. "
                    "'standard': plain prongs, no connecting rail. "
                    "'basket': horizontal rail band connecting alternate prong bases. "
                    "'trellis': cross-diagonal rail between adjacent prongs. "
                    "'cathedral': arch ribs rising from prong base to a lower shank seat."
                ),
            },
            "basket_rail_count": {
                "type": "integer",
                "description": "Number of horizontal basket rails (default 1). Ignored for 'standard'.",
            },
            "seat_angle_deg": {
                "type": "number",
                "description": "Angle (degrees) of the bearing ledge chamfer. Default 15°.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "prong_count", "prong_wire_diameter", "prong_height"],
    },
)


@register(jewelry_prong_head_spec, write=True)
async def run_jewelry_create_prong_head(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    prong_count = a.get("prong_count")
    prong_wire_diameter = a.get("prong_wire_diameter")
    prong_height = a.get("prong_height")
    head_style = a.get("head_style", "standard")
    basket_rail_count = a.get("basket_rail_count", 1)
    seat_angle_deg = a.get("seat_angle_deg", 15.0)
    node_id = a.get("id", "").strip()

    # Validate required fields.
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("prong_wire_diameter", prong_wire_diameter),
        ("prong_height", prong_height),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    if prong_count not in _VALID_PRONG_COUNTS:
        return err_payload(
            f"prong_count must be 4 or 6; got {prong_count!r}", "BAD_ARGS"
        )

    head_style_clean = (head_style or "standard").strip().lower()
    if head_style_clean not in _VALID_HEAD_STYLES:
        return err_payload(
            f"head_style must be one of {sorted(_VALID_HEAD_STYLES)}; got {head_style!r}",
            "BAD_ARGS",
        )

    err = _non_negative_int("basket_rail_count", basket_rail_count)
    if err:
        return err_payload(err, "BAD_ARGS")

    seat_err = _positive("seat_angle_deg", seat_angle_deg)
    if seat_err:
        return err_payload(seat_err, "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_prong_head")

    node = build_prong_head_node(
        node_id=node_id,
        stone_diameter=float(stone_diameter),
        prong_count=int(prong_count),
        prong_wire_diameter=float(prong_wire_diameter),
        prong_height=float(prong_height),
        head_style=head_style_clean,
        basket_rail_count=int(basket_rail_count),
        seat_angle_deg=float(seat_angle_deg),
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_prong_head",
        "prong_count": int(prong_count),
        "head_style": head_style_clean,
        "stone_diameter": float(stone_diameter),
    })


# ---------------------------------------------------------------------------
# LLM Tool: jewelry_create_bezel
# ---------------------------------------------------------------------------

jewelry_bezel_spec = ToolSpec(
    name="jewelry_create_bezel",
    description=(
        "Append a `jewelry_bezel` node to a `.feature` file. "
        "Generates a parametric bezel setting — a full or partial metal collar "
        "surrounding a gemstone, with a horizontal bearing ledge on which the "
        "stone's girdle seats. "
        "Styles: 'full' (360° collar), 'partial' (gap of `partial_opening_deg`), "
        "'collet' (tube bezel, minimal wall), 'tapered' (outer wall angled inward "
        "at `taper_angle_deg` for a rub-over look). "
        "Output: a TopoDS_Solid bezel body ready for boolean fuse onto a shank."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of the stone in mm.",
            },
            "wall_thickness": {
                "type": "number",
                "description": "Bezel wall thickness in mm. Typical: 0.3–0.8 mm.",
            },
            "bezel_height": {
                "type": "number",
                "description": "Total height of the bezel collar in mm (from base to top).",
            },
            "bearing_ledge_height": {
                "type": "number",
                "description": (
                    "Height of the bearing ledge from the base. "
                    "The stone girdle rests here. Must be < bezel_height."
                ),
            },
            "bezel_style": {
                "type": "string",
                "enum": ["full", "partial", "collet", "tapered"],
                "description": "Bezel geometry style.",
            },
            "partial_opening_deg": {
                "type": "number",
                "description": "Gap angle (degrees) for 'partial' style. Range [1, 359]. Ignored for 'full'/'collet'/'tapered'.",
            },
            "taper_angle_deg": {
                "type": "number",
                "description": "Outer wall inward taper angle in degrees (0 = straight). Used for 'tapered'/'collet' styles.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "wall_thickness", "bezel_height", "bearing_ledge_height"],
    },
)


@register(jewelry_bezel_spec, write=True)
async def run_jewelry_create_bezel(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    wall_thickness = a.get("wall_thickness")
    bezel_height = a.get("bezel_height")
    bearing_ledge_height = a.get("bearing_ledge_height")
    bezel_style = a.get("bezel_style", "full")
    partial_opening_deg = a.get("partial_opening_deg", 60.0)
    taper_angle_deg = a.get("taper_angle_deg", 0.0)
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("wall_thickness", wall_thickness),
        ("bezel_height", bezel_height),
        ("bearing_ledge_height", bearing_ledge_height),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        bh = float(bezel_height)
        blh = float(bearing_ledge_height)
    except (TypeError, ValueError):
        return err_payload("bezel_height and bearing_ledge_height must be numbers", "BAD_ARGS")

    if blh >= bh:
        return err_payload(
            f"bearing_ledge_height ({blh}) must be less than bezel_height ({bh})",
            "BAD_ARGS",
        )

    bezel_style_clean = (bezel_style or "full").strip().lower()
    if bezel_style_clean not in _VALID_BEZEL_STYLES:
        return err_payload(
            f"bezel_style must be one of {sorted(_VALID_BEZEL_STYLES)}; got {bezel_style!r}",
            "BAD_ARGS",
        )

    try:
        pod = float(partial_opening_deg)
    except (TypeError, ValueError):
        pod = 60.0

    if bezel_style_clean == "partial" and not (1.0 <= pod <= 359.0):
        return err_payload(
            f"partial_opening_deg must be in [1, 359] for partial style; got {pod}",
            "BAD_ARGS",
        )

    try:
        tap = float(taper_angle_deg)
    except (TypeError, ValueError):
        tap = 0.0

    if tap < 0:
        return err_payload(
            f"taper_angle_deg must be >= 0; got {tap}", "BAD_ARGS"
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_bezel")

    node = build_bezel_node(
        node_id=node_id,
        stone_diameter=float(stone_diameter),
        wall_thickness=float(wall_thickness),
        bezel_height=bh,
        bearing_ledge_height=blh,
        bezel_style=bezel_style_clean,
        partial_opening_deg=pod,
        taper_angle_deg=tap,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_bezel",
        "bezel_style": bezel_style_clean,
        "stone_diameter": float(stone_diameter),
    })


# ---------------------------------------------------------------------------
# LLM Tool: jewelry_create_channel
# ---------------------------------------------------------------------------

jewelry_channel_spec = ToolSpec(
    name="jewelry_create_channel",
    description=(
        "Append a `jewelry_channel` node to a `.feature` file. "
        "Generates a parametric channel setting — two parallel metal rails "
        "with a floor, sized to hold a row of `stone_count` calibrated stones "
        "of `stone_diameter` at `stone_spacing` centre-to-centre intervals. "
        "The channel runs along the X-axis. The worker's evaluate result includes "
        "`seat_positions` — a list of per-stone XYZ positions relative to the "
        "channel's local origin — so a downstream gem-seat op can cut each seat. "
        "Output: a TopoDS_Solid channel body."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Stone girdle diameter (width) in mm.",
            },
            "stone_count": {
                "type": "integer",
                "description": "Number of stones in the channel row. Must be >= 1.",
            },
            "stone_spacing": {
                "type": "number",
                "description": "Centre-to-centre spacing between adjacent stones in mm. Must be > stone_diameter.",
            },
            "rail_height": {
                "type": "number",
                "description": "Height of the channel rails above the stone seat in mm.",
            },
            "rail_thickness": {
                "type": "number",
                "description": "Thickness of each rail wall in mm.",
            },
            "floor_thickness": {
                "type": "number",
                "description": "Thickness of the channel floor in mm.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "stone_count", "stone_spacing", "rail_height", "rail_thickness", "floor_thickness"],
    },
)


@register(jewelry_channel_spec, write=True)
async def run_jewelry_create_channel(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    stone_count = a.get("stone_count")
    stone_spacing = a.get("stone_spacing")
    rail_height = a.get("rail_height")
    rail_thickness = a.get("rail_thickness")
    floor_thickness = a.get("floor_thickness")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("stone_spacing", stone_spacing),
        ("rail_height", rail_height),
        ("rail_thickness", rail_thickness),
        ("floor_thickness", floor_thickness),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        sc = int(stone_count)
    except (TypeError, ValueError):
        return err_payload("stone_count must be an integer", "BAD_ARGS")
    if sc < 1:
        return err_payload(f"stone_count must be >= 1; got {sc}", "BAD_ARGS")

    try:
        sd = float(stone_diameter)
        ss = float(stone_spacing)
    except (TypeError, ValueError):
        return err_payload("stone_diameter and stone_spacing must be numbers", "BAD_ARGS")

    if ss <= sd:
        return err_payload(
            f"stone_spacing ({ss}) must be greater than stone_diameter ({sd}) to prevent overlap",
            "BAD_ARGS",
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_channel")

    node = build_channel_node(
        node_id=node_id,
        stone_diameter=sd,
        stone_count=sc,
        stone_spacing=ss,
        rail_height=float(rail_height),
        rail_thickness=float(rail_thickness),
        floor_thickness=float(floor_thickness),
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_channel",
        "stone_count": sc,
        "channel_length": round(sc * ss, 4),
    })


# ---------------------------------------------------------------------------
# LLM Tool: jewelry_pave_array
# ---------------------------------------------------------------------------

jewelry_pave_spec = ToolSpec(
    name="jewelry_pave_array",
    description=(
        "Append a `jewelry_pave` node to a `.feature` file. "
        "Distributes stone placements across a rectangular target surface region "
        "using a hex-offset grid layout. Returns the array of placement transforms "
        "(u,v fractional coordinates on the region surface) so a downstream "
        "gem-seat op can cut individual stone seats. "
        "The operation does NOT cut seats itself — it only records the placement "
        "grid. Pair with a boolean-cut loop or a future gem_seat op to produce "
        "actual seats. "
        "Parameters control stone diameter, centre-to-centre spacing, and an "
        "edge margin that keeps the outermost stones' edges inside the region "
        "boundary. Odd rows are shifted by half a column pitch (hex offset) "
        "for tighter packing and the characteristic pavé bead appearance."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "region_width": {
                "type": "number",
                "description": "Width (X-extent) of the target region in mm.",
            },
            "region_height": {
                "type": "number",
                "description": "Height (Y-extent) of the target region in mm.",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Stone girdle diameter in mm.",
            },
            "stone_spacing": {
                "type": "number",
                "description": "Gap between adjacent stone edges in mm (centre-to-centre = stone_diameter + stone_spacing).",
            },
            "edge_margin": {
                "type": "number",
                "description": "Minimum margin from the region boundary to the outermost stone edge in mm.",
            },
            "surface_normal": {
                "type": "array",
                "items": {"type": "number"},
                "description": "World-space normal of the target surface plane [nx, ny, nz]. Default [0, 0, 1].",
            },
            "surface_origin": {
                "type": "array",
                "items": {"type": "number"},
                "description": "World-space origin of the region [x, y, z]. Default [0, 0, 0].",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "region_width", "region_height", "stone_diameter", "stone_spacing", "edge_margin"],
    },
)


@register(jewelry_pave_spec, write=True)
async def run_jewelry_pave_array(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    region_width = a.get("region_width")
    region_height = a.get("region_height")
    stone_diameter = a.get("stone_diameter")
    stone_spacing = a.get("stone_spacing")
    edge_margin = a.get("edge_margin")
    surface_normal = a.get("surface_normal", [0, 0, 1])
    surface_origin = a.get("surface_origin", [0, 0, 0])
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("region_width", region_width),
        ("region_height", region_height),
        ("stone_diameter", stone_diameter),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        ss = float(stone_spacing)
    except (TypeError, ValueError):
        return err_payload("stone_spacing must be a number", "BAD_ARGS")
    if ss < 0:
        return err_payload(f"stone_spacing must be >= 0; got {ss}", "BAD_ARGS")

    try:
        em = float(edge_margin)
    except (TypeError, ValueError):
        return err_payload("edge_margin must be a number", "BAD_ARGS")
    if em < 0:
        return err_payload(f"edge_margin must be >= 0; got {em}", "BAD_ARGS")

    # Validate surface_normal and surface_origin are 3-element lists.
    if not isinstance(surface_normal, list) or len(surface_normal) != 3:
        return err_payload("surface_normal must be a 3-element list [nx, ny, nz]", "BAD_ARGS")
    if not isinstance(surface_origin, list) or len(surface_origin) != 3:
        return err_payload("surface_origin must be a 3-element list [x, y, z]", "BAD_ARGS")

    try:
        sn = [float(v) for v in surface_normal]
        so = [float(v) for v in surface_origin]
    except (TypeError, ValueError):
        return err_payload("surface_normal and surface_origin elements must be numbers", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_pave")

    node = build_pave_array_node(
        node_id=node_id,
        region_width=float(region_width),
        region_height=float(region_height),
        stone_diameter=float(stone_diameter),
        stone_spacing=ss,
        edge_margin=em,
        surface_normal=sn,
        surface_origin=so,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    placement_count = node.get("_placement_count", 0)

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_pave",
        "placement_count": placement_count,
        "region_width": float(region_width),
        "region_height": float(region_height),
    })


# ---------------------------------------------------------------------------
# Tension setting
# ---------------------------------------------------------------------------

def build_tension_node(
    node_id: str,
    stone_diameter: float,
    band_thickness: float,
    gap: float,
    rail_width: float,
    rail_depth: float,
) -> dict:
    """
    Compute the tension-setting node spec.

    The worker's opJewelryTension builds:
      - Two band-end bodies of thickness `band_thickness`, each with a curved
        inward face that cradles the stone girdle.  The gap between the two
        facing surfaces equals `gap` (the stone is captured by spring tension).
      - A horizontal tension rail on each side of width `rail_width` and
        depth `rail_depth` that forms the bearing shelf gripping the girdle.

    The stone is NOT set into a drilled seat — it is suspended between the two
    opposing rails, held only by the metal's spring tension.

    Derived hints:
      _seat_radius  — radius of the bearing cradle = stone_diameter / 2.
      _band_spread  — total spread of the two band ends = stone_diameter + gap.
    """
    seat_radius = stone_diameter / 2.0
    band_spread = stone_diameter + gap

    return {
        "id": node_id,
        "op": "jewelry_tension",
        "stone_diameter": stone_diameter,
        "band_thickness": band_thickness,
        "gap": gap,
        "rail_width": rail_width,
        "rail_depth": rail_depth,
        "_seat_radius": round(seat_radius, 4),
        "_band_spread": round(band_spread, 4),
    }


jewelry_tension_spec = ToolSpec(
    name="jewelry_create_tension",
    description=(
        "Append a `jewelry_tension` node to a `.feature` file. "
        "Generates a tension setting where the stone is held purely by the "
        "spring pressure of two opposing band ends. "
        "The stone floats in a gap between the band ends; each end has an "
        "inward-curved bearing rail that grips the stone's girdle. "
        "Output: a node spec consumed by the OCCT worker's opJewelryTension "
        "handler to produce two TopoDS_Solid band-end bodies."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of the stone in mm.",
            },
            "band_thickness": {
                "type": "number",
                "description": "Thickness of the band metal at the setting point in mm (typical 2.0–4.0).",
            },
            "gap": {
                "type": "number",
                "description": (
                    "Gap between the two band-end faces in mm. "
                    "Must be < stone_diameter so the stone is retained."
                ),
            },
            "rail_width": {
                "type": "number",
                "description": "Width of the bearing rail that grips the girdle in mm (typical 0.3–0.8).",
            },
            "rail_depth": {
                "type": "number",
                "description": "Depth of the bearing rail notch in mm (typical 0.2–0.5).",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "band_thickness", "gap", "rail_width", "rail_depth"],
    },
)


@register(jewelry_tension_spec, write=True)
async def run_jewelry_create_tension(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    band_thickness = a.get("band_thickness")
    gap = a.get("gap")
    rail_width = a.get("rail_width")
    rail_depth = a.get("rail_depth")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("band_thickness", band_thickness),
        ("gap", gap),
        ("rail_width", rail_width),
        ("rail_depth", rail_depth),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        sd = float(stone_diameter)
        gp = float(gap)
    except (TypeError, ValueError):
        return err_payload("stone_diameter and gap must be numbers", "BAD_ARGS")

    if gp >= sd:
        return err_payload(
            f"gap ({gp}) must be less than stone_diameter ({sd}) so the stone is retained",
            "BAD_ARGS",
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_tension")

    node = build_tension_node(
        node_id=node_id,
        stone_diameter=sd,
        band_thickness=float(band_thickness),
        gap=gp,
        rail_width=float(rail_width),
        rail_depth=float(rail_depth),
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_tension",
        "stone_diameter": sd,
        "gap": gp,
        "_band_spread": node["_band_spread"],
    })


# ---------------------------------------------------------------------------
# Flush / gypsy setting
# ---------------------------------------------------------------------------

def build_flush_node(
    node_id: str,
    stone_diameter: float,
    seat_depth: float,
    bevel_width: float,
    bevel_angle_deg: float,
) -> dict:
    """
    Compute the flush-setting node spec.

    The worker's opJewelryFlush builds a drilled cylindrical seat of diameter
    `stone_diameter` and depth `seat_depth` sunk into the metal surface.  A
    chamfer of width `bevel_width` at `bevel_angle_deg` trims the opening edge
    so that the stone's crown is flush with or just proud of the metal.

    Derived hints:
      _seat_volume_approx  — π r² h (mm³) for material-removal estimate.
      _opening_diameter    — stone_diameter + 2 * bevel_width * tan(bevel_angle).
    """
    r = stone_diameter / 2.0
    seat_volume = math.pi * r * r * seat_depth
    opening_diameter = stone_diameter + 2.0 * bevel_width * math.tan(
        math.radians(bevel_angle_deg)
    )

    return {
        "id": node_id,
        "op": "jewelry_flush",
        "stone_diameter": stone_diameter,
        "seat_depth": seat_depth,
        "bevel_width": bevel_width,
        "bevel_angle_deg": bevel_angle_deg,
        "_seat_volume_approx": round(seat_volume, 4),
        "_opening_diameter": round(opening_diameter, 4),
    }


jewelry_flush_spec = ToolSpec(
    name="jewelry_create_flush",
    description=(
        "Append a `jewelry_flush` node to a `.feature` file. "
        "Generates a flush (gypsy) setting where the stone is set into a "
        "drilled seat so its table sits level with — or just proud of — the "
        "surrounding metal surface. "
        "The worker's opJewelryFlush handler drills a cylindrical pocket of "
        "`stone_diameter` × `seat_depth` and adds a chamfered opening edge "
        "(bevel) to ease the stone in and catch light. "
        "Output: a boolean-cut node spec. Pair with the parent metal body "
        "using a `feature_boolean` cut."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of the stone in mm.",
            },
            "seat_depth": {
                "type": "number",
                "description": "Depth of the drilled seat in mm (typically 60–80% of stone depth).",
            },
            "bevel_width": {
                "type": "number",
                "description": "Width of the opening bevel/chamfer in mm (typical 0.1–0.3).",
            },
            "bevel_angle_deg": {
                "type": "number",
                "description": "Angle of the bevel chamfer in degrees (typical 30–60°).",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "seat_depth", "bevel_width", "bevel_angle_deg"],
    },
)


@register(jewelry_flush_spec, write=True)
async def run_jewelry_create_flush(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    seat_depth = a.get("seat_depth")
    bevel_width = a.get("bevel_width")
    bevel_angle_deg = a.get("bevel_angle_deg")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("seat_depth", seat_depth),
        ("bevel_width", bevel_width),
        ("bevel_angle_deg", bevel_angle_deg),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        ba = float(bevel_angle_deg)
    except (TypeError, ValueError):
        return err_payload("bevel_angle_deg must be a number", "BAD_ARGS")

    if ba >= 90.0:
        return err_payload(
            f"bevel_angle_deg must be < 90°; got {ba}", "BAD_ARGS"
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_flush")

    node = build_flush_node(
        node_id=node_id,
        stone_diameter=float(stone_diameter),
        seat_depth=float(seat_depth),
        bevel_width=float(bevel_width),
        bevel_angle_deg=ba,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_flush",
        "stone_diameter": float(stone_diameter),
        "_opening_diameter": node["_opening_diameter"],
    })


# ---------------------------------------------------------------------------
# Halo setting
# ---------------------------------------------------------------------------

def build_halo_node(
    node_id: str,
    center_diameter: float,
    halo_stone_size: float,
    halo_stone_count: int,
    halo_gap: float,
    halo_metal_width: float,
) -> dict:
    """
    Compute the halo-setting node spec.

    The worker's opJewelryHalo builds:
      - A center stone seat of diameter `center_diameter` (same as a prong head
        or bezel — the caller adds their preferred center setting separately).
      - A ring of `halo_stone_count` accent stones of diameter `halo_stone_size`
        placed evenly around the center stone, separated by `halo_gap` from
        the center stone edge.
      - A metal halo frame of width `halo_metal_width` around the accent ring.

    Derived hints:
      _halo_radius      — centre-to-centre radius of the accent stone ring.
      _halo_outer_diameter — outer extent of the halo frame.
      _accent_pitch_deg — angular pitch between adjacent accent stones.
    """
    # Radial centre of the halo accent stones.
    # Each accent stone sits gap + center_radius + accent_radius from the origin.
    halo_radius = center_diameter / 2.0 + halo_gap + halo_stone_size / 2.0
    halo_outer_diameter = 2.0 * (halo_radius + halo_stone_size / 2.0 + halo_metal_width)
    accent_pitch_deg = 360.0 / halo_stone_count if halo_stone_count > 0 else 0.0

    return {
        "id": node_id,
        "op": "jewelry_halo",
        "center_diameter": center_diameter,
        "halo_stone_size": halo_stone_size,
        "halo_stone_count": halo_stone_count,
        "halo_gap": halo_gap,
        "halo_metal_width": halo_metal_width,
        "_halo_radius": round(halo_radius, 4),
        "_halo_outer_diameter": round(halo_outer_diameter, 4),
        "_accent_pitch_deg": round(accent_pitch_deg, 4),
    }


jewelry_halo_spec = ToolSpec(
    name="jewelry_create_halo",
    description=(
        "Append a `jewelry_halo` node to a `.feature` file. "
        "Generates a halo setting — a ring of small accent/pavé stones "
        "surrounding a center stone seat. "
        "The `halo_stone_count` accent stones of `halo_stone_size` are placed "
        "evenly around the center stone at a radial distance of `halo_gap` from "
        "the center stone edge. A metal halo frame of `halo_metal_width` "
        "surrounds the accent ring. "
        "The center stone seat is NOT generated by this tool — add a "
        "`jewelry_create_prong_head` or `jewelry_create_bezel` node separately "
        "for the center stone. "
        "Output: node spec consumed by the OCCT worker's opJewelryHalo handler."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "center_diameter": {
                "type": "number",
                "description": "Girdle diameter of the center stone in mm.",
            },
            "halo_stone_size": {
                "type": "number",
                "description": "Diameter of each individual halo accent stone in mm (typical 1.0–1.8).",
            },
            "halo_stone_count": {
                "type": "integer",
                "description": "Number of accent stones in the halo ring (typical 14–32). Must be >= 3.",
            },
            "halo_gap": {
                "type": "number",
                "description": "Radial gap between the center stone edge and the nearest halo stone edge in mm (typical 0.1–0.3).",
            },
            "halo_metal_width": {
                "type": "number",
                "description": "Width of the metal frame surrounding the halo accent ring in mm (typical 0.3–0.6).",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "center_diameter", "halo_stone_size", "halo_stone_count", "halo_gap", "halo_metal_width"],
    },
)


@register(jewelry_halo_spec, write=True)
async def run_jewelry_create_halo(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    center_diameter = a.get("center_diameter")
    halo_stone_size = a.get("halo_stone_size")
    halo_stone_count = a.get("halo_stone_count")
    halo_gap = a.get("halo_gap")
    halo_metal_width = a.get("halo_metal_width")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("center_diameter", center_diameter),
        ("halo_stone_size", halo_stone_size),
        ("halo_gap", halo_gap),
        ("halo_metal_width", halo_metal_width),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        hsc = int(halo_stone_count)
    except (TypeError, ValueError):
        return err_payload("halo_stone_count must be an integer", "BAD_ARGS")
    if hsc < 3:
        return err_payload(
            f"halo_stone_count must be >= 3; got {hsc}", "BAD_ARGS"
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_halo")

    node = build_halo_node(
        node_id=node_id,
        center_diameter=float(center_diameter),
        halo_stone_size=float(halo_stone_size),
        halo_stone_count=hsc,
        halo_gap=float(halo_gap),
        halo_metal_width=float(halo_metal_width),
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_halo",
        "center_diameter": float(center_diameter),
        "halo_stone_count": hsc,
        "_halo_outer_diameter": node["_halo_outer_diameter"],
    })


# ---------------------------------------------------------------------------
# Three-stone setting
# ---------------------------------------------------------------------------

def build_three_stone_node(
    node_id: str,
    center_diameter: float,
    side_diameter: float,
    stone_spacing: float,
    base_height: float,
) -> dict:
    """
    Compute the three-stone setting node spec.

    The worker's opJewelryThreeStone builds:
      - A center stone seat of diameter `center_diameter`.
      - Two side stone seats of diameter `side_diameter`, each offset along
        the X-axis by (center_diameter / 2 + stone_spacing + side_diameter / 2).
      - A shared base/gallery of height `base_height` connecting all three seats.

    Derived hints:
      _side_offset_x — X-axis offset of each side stone centre from the origin.
      _total_width   — overall width of the three-stone cluster.
    """
    side_offset_x = center_diameter / 2.0 + stone_spacing + side_diameter / 2.0
    total_width = 2.0 * side_offset_x + side_diameter

    return {
        "id": node_id,
        "op": "jewelry_three_stone",
        "center_diameter": center_diameter,
        "side_diameter": side_diameter,
        "stone_spacing": stone_spacing,
        "base_height": base_height,
        "_side_offset_x": round(side_offset_x, 4),
        "_total_width": round(total_width, 4),
    }


jewelry_three_stone_spec = ToolSpec(
    name="jewelry_create_three_stone",
    description=(
        "Append a `jewelry_three_stone` node to a `.feature` file. "
        "Generates a three-stone setting — a center stone flanked by two "
        "graduated side stones on a shared base/gallery. "
        "The center stone seat has diameter `center_diameter`; the two side "
        "stone seats have diameter `side_diameter` (typically 60–75% of center). "
        "All three seats share a common base of height `base_height`. "
        "Output: node spec consumed by the OCCT worker's opJewelryThreeStone "
        "handler to produce a combined base solid with three seat positions "
        "posted in the evaluate result."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "center_diameter": {
                "type": "number",
                "description": "Girdle diameter of the center stone in mm.",
            },
            "side_diameter": {
                "type": "number",
                "description": "Girdle diameter of each side stone in mm. Typically 60–75% of center_diameter.",
            },
            "stone_spacing": {
                "type": "number",
                "description": "Gap between adjacent stone edges in mm (typical 0.1–0.3).",
            },
            "base_height": {
                "type": "number",
                "description": "Height of the shared gallery base in mm.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "center_diameter", "side_diameter", "stone_spacing", "base_height"],
    },
)


@register(jewelry_three_stone_spec, write=True)
async def run_jewelry_create_three_stone(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    center_diameter = a.get("center_diameter")
    side_diameter = a.get("side_diameter")
    stone_spacing = a.get("stone_spacing")
    base_height = a.get("base_height")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("center_diameter", center_diameter),
        ("side_diameter", side_diameter),
        ("stone_spacing", stone_spacing),
        ("base_height", base_height),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_three_stone")

    node = build_three_stone_node(
        node_id=node_id,
        center_diameter=float(center_diameter),
        side_diameter=float(side_diameter),
        stone_spacing=float(stone_spacing),
        base_height=float(base_height),
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_three_stone",
        "center_diameter": float(center_diameter),
        "side_diameter": float(side_diameter),
        "_total_width": node["_total_width"],
    })


# ---------------------------------------------------------------------------
# Cluster setting
# ---------------------------------------------------------------------------

def _compute_cluster_positions(
    cluster_diameter: float,
    stone_size: float,
    stone_count: int,
) -> list:
    """
    Distribute `stone_count` stones of `stone_size` in a circular cluster of
    overall diameter `cluster_diameter`.

    Uses a simple annular ring layout: all stones are placed on a circle of
    radius = (cluster_diameter / 2) - (stone_size / 2).  When stone_count == 1
    the single stone is placed at the origin.

    Returns a list of {"x": float, "y": float, "angle_deg": float} dicts
    representing stone centre positions in the cluster's local XY plane.
    """
    if stone_count == 1:
        return [{"x": 0.0, "y": 0.0, "angle_deg": 0.0}]

    placement_radius = cluster_diameter / 2.0 - stone_size / 2.0
    if placement_radius <= 0:
        # Stones too large for the cluster diameter — pack all at origin.
        placement_radius = 0.0

    positions = []
    for i in range(stone_count):
        angle_deg = 360.0 * i / stone_count
        angle_rad = math.radians(angle_deg)
        x = placement_radius * math.cos(angle_rad)
        y = placement_radius * math.sin(angle_rad)
        positions.append({
            "x": round(x, 4),
            "y": round(y, 4),
            "angle_deg": round(angle_deg, 4),
        })
    return positions


def build_cluster_node(
    node_id: str,
    cluster_diameter: float,
    stone_size: float,
    stone_count: int,
    dome_height: float,
) -> dict:
    """
    Compute the cluster-setting node spec.

    The worker's opJewelryCluster builds:
      - A domed base (shallow spherical cap) of diameter `cluster_diameter`
        and height `dome_height`, representing the metal platform.
      - `stone_count` stone seats of diameter `stone_size` distributed across
        the dome surface according to `positions`.

    Derived hints:
      _placement_radius  — radial distance of stone centres from the cluster axis.
      positions          — list of per-stone {x, y, angle_deg} dicts.
    """
    placement_radius = max(0.0, cluster_diameter / 2.0 - stone_size / 2.0)
    positions = _compute_cluster_positions(
        cluster_diameter=cluster_diameter,
        stone_size=stone_size,
        stone_count=stone_count,
    )

    return {
        "id": node_id,
        "op": "jewelry_cluster",
        "cluster_diameter": cluster_diameter,
        "stone_size": stone_size,
        "stone_count": stone_count,
        "dome_height": dome_height,
        "positions": positions,
        "_placement_radius": round(placement_radius, 4),
        "_actual_count": len(positions),
    }


jewelry_cluster_spec = ToolSpec(
    name="jewelry_create_cluster",
    description=(
        "Append a `jewelry_cluster` node to a `.feature` file. "
        "Generates a cluster setting where `stone_count` small stones are "
        "grouped together on a domed base to read visually as one large stone. "
        "Stones of `stone_size` are arranged on a circular platform of "
        "`cluster_diameter`. The dome curvature is controlled by `dome_height` "
        "(the height of the domed base profile). "
        "Output: node spec consumed by the OCCT worker's opJewelryCluster "
        "handler. The evaluate result includes `seat_positions` — per-stone "
        "XYZ positions on the dome surface — for downstream seat-cutting."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "cluster_diameter": {
                "type": "number",
                "description": "Overall diameter of the cluster platform in mm.",
            },
            "stone_size": {
                "type": "number",
                "description": "Girdle diameter of each individual stone in the cluster in mm.",
            },
            "stone_count": {
                "type": "integer",
                "description": "Number of stones in the cluster. Must be >= 1.",
            },
            "dome_height": {
                "type": "number",
                "description": "Height of the dome profile above the base plane in mm. Use 0.0 for a flat cluster.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "cluster_diameter", "stone_size", "stone_count", "dome_height"],
    },
)


@register(jewelry_cluster_spec, write=True)
async def run_jewelry_create_cluster(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    cluster_diameter = a.get("cluster_diameter")
    stone_size = a.get("stone_size")
    stone_count = a.get("stone_count")
    dome_height = a.get("dome_height")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("cluster_diameter", cluster_diameter),
        ("stone_size", stone_size),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    # dome_height may be 0.0 (flat cluster) — only check it's a non-negative number.
    try:
        dh = float(dome_height)
    except (TypeError, ValueError):
        return err_payload("dome_height must be a number", "BAD_ARGS")
    if dh < 0:
        return err_payload(f"dome_height must be >= 0; got {dh}", "BAD_ARGS")

    try:
        sc = int(stone_count)
    except (TypeError, ValueError):
        return err_payload("stone_count must be an integer", "BAD_ARGS")
    if sc < 1:
        return err_payload(f"stone_count must be >= 1; got {sc}", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_cluster")

    node = build_cluster_node(
        node_id=node_id,
        cluster_diameter=float(cluster_diameter),
        stone_size=float(stone_size),
        stone_count=sc,
        dome_height=dh,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_cluster",
        "stone_count": sc,
        "cluster_diameter": float(cluster_diameter),
        "_placement_radius": node["_placement_radius"],
    })


# ---------------------------------------------------------------------------
# Bar setting
# ---------------------------------------------------------------------------

_VALID_BAR_LAYOUTS = {"linear", "arc"}


def build_bar_node(
    node_id: str,
    stone_diameter: float,
    bar_width: float,
    bar_height: float,
    stone_count: int,
    pitch: float,
) -> dict:
    """
    Compute the bar-setting node spec.

    The worker's opJewelryBar builds:
      - `stone_count` stone seats of diameter `stone_diameter` spaced at
        `pitch` centre-to-centre along the X-axis.
      - Two parallel metal bars of width `bar_width` and height `bar_height`
        running along either side of the stone row (no prongs between stones).
        The bars grip each stone's girdle at the sides; the stone faces remain
        fully exposed.

    Derived hints:
      _bar_length   — total length of each bar = stone_count * pitch.
      _bar_separation — inner face-to-face separation = stone_diameter (bars
                         just clear the stone girdle; the worker adds 0.05 mm
                         per side for fit clearance).
    """
    bar_length = stone_count * pitch
    bar_separation = stone_diameter

    return {
        "id": node_id,
        "op": "jewelry_bar",
        "stone_diameter": stone_diameter,
        "bar_width": bar_width,
        "bar_height": bar_height,
        "stone_count": stone_count,
        "pitch": pitch,
        "_bar_length": round(bar_length, 4),
        "_bar_separation": round(bar_separation, 4),
    }


jewelry_bar_spec = ToolSpec(
    name="jewelry_create_bar",
    description=(
        "Append a `jewelry_bar` node to a `.feature` file. "
        "Generates a bar setting — two parallel metal bars running along either "
        "side of a row of `stone_count` calibrated stones of `stone_diameter`, "
        "spaced at `pitch` centre-to-centre. "
        "Unlike a channel setting there are NO prongs between stones: each stone "
        "is gripped along its full girdle by the bars alone, creating a clean "
        "uninterrupted look popular in men's bands and eternity rings. "
        "The bars have cross-section `bar_width` × `bar_height`. "
        "Constraint: pitch must be greater than stone_diameter. "
        "Output: a TopoDS_Solid pair of bars with stone seat cutouts."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of each stone in mm.",
            },
            "bar_width": {
                "type": "number",
                "description": "Width of each metal bar in mm (typical 0.4–1.0).",
            },
            "bar_height": {
                "type": "number",
                "description": "Height of each metal bar above the stone seat in mm (typical 0.5–1.2).",
            },
            "stone_count": {
                "type": "integer",
                "description": "Number of stones in the bar row. Must be >= 1.",
            },
            "pitch": {
                "type": "number",
                "description": (
                    "Centre-to-centre distance between adjacent stones in mm. "
                    "Must be > stone_diameter."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "bar_width", "bar_height", "stone_count", "pitch"],
    },
)


@register(jewelry_bar_spec, write=True)
async def run_jewelry_create_bar(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    bar_width = a.get("bar_width")
    bar_height = a.get("bar_height")
    stone_count = a.get("stone_count")
    pitch = a.get("pitch")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("bar_width", bar_width),
        ("bar_height", bar_height),
        ("pitch", pitch),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        sc = int(stone_count)
    except (TypeError, ValueError):
        return err_payload("stone_count must be an integer", "BAD_ARGS")
    if sc < 1:
        return err_payload(f"stone_count must be >= 1; got {sc}", "BAD_ARGS")

    try:
        sd = float(stone_diameter)
        pt = float(pitch)
    except (TypeError, ValueError):
        return err_payload("stone_diameter and pitch must be numbers", "BAD_ARGS")

    if pt <= sd:
        return err_payload(
            f"pitch ({pt}) must be greater than stone_diameter ({sd}) to prevent overlap",
            "BAD_ARGS",
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_bar")

    node = build_bar_node(
        node_id=node_id,
        stone_diameter=sd,
        bar_width=float(bar_width),
        bar_height=float(bar_height),
        stone_count=sc,
        pitch=pt,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_bar",
        "stone_count": sc,
        "stone_diameter": sd,
        "_bar_length": node["_bar_length"],
    })


# ---------------------------------------------------------------------------
# Bead / grain setting
# ---------------------------------------------------------------------------

_VALID_BEAD_LAYOUTS = {"line", "grid"}


def build_bead_grain_node(
    node_id: str,
    stone_diameter: float,
    bead_count_per_stone: int,
    bead_diameter: float,
    field_layout: str,
) -> dict:
    """
    Compute the bead/grain-setting node spec.

    The worker's opJewelryBeadGrain builds:
      - A drilled stone seat of diameter `stone_diameter` sunk into the metal
        surface (similar to a flush seat).
      - `bead_count_per_stone` raised metal beads of diameter `bead_diameter`
        cut up from the surrounding surface and pushed over the stone's girdle
        to retain it.  Beads are spaced evenly around the stone.
      - For `field_layout='line'`: stones are arranged in a single row.
      - For `field_layout='grid'`: stones are arranged in a rectangular grid;
        pitch is derived from stone_diameter and bead geometry.

    Derived hints:
      _bead_pitch_deg   — angular pitch between adjacent beads around one stone.
      _bead_ring_radius — radius of the bead circle around the stone = stone_diameter/2.
    """
    bead_pitch_deg = 360.0 / bead_count_per_stone if bead_count_per_stone > 0 else 0.0
    bead_ring_radius = stone_diameter / 2.0

    return {
        "id": node_id,
        "op": "jewelry_bead_grain",
        "stone_diameter": stone_diameter,
        "bead_count_per_stone": bead_count_per_stone,
        "bead_diameter": bead_diameter,
        "field_layout": field_layout,
        "_bead_pitch_deg": round(bead_pitch_deg, 4),
        "_bead_ring_radius": round(bead_ring_radius, 4),
    }


jewelry_bead_grain_spec = ToolSpec(
    name="jewelry_create_bead_grain",
    description=(
        "Append a `jewelry_bead_grain` node to a `.feature` file. "
        "Generates a bead (grain) setting where each stone is held by small "
        "raised metal beads that are cut up from the surrounding metal surface "
        "and pushed over the stone's girdle. "
        "Parameters control the stone diameter, the number of beads per stone "
        "(`bead_count_per_stone`, minimum 2), the bead diameter, and the "
        "overall field layout (`line` for a single row or `grid` for a "
        "rectangular array). "
        "Output: node spec consumed by opJewelryBeadGrain. Combines with a "
        "gem-seat boolean cut for the stone pocket."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of each stone in mm.",
            },
            "bead_count_per_stone": {
                "type": "integer",
                "description": (
                    "Number of raised beads retaining each stone. Must be >= 2. "
                    "Typical values: 2 (tight inline), 3, 4."
                ),
            },
            "bead_diameter": {
                "type": "number",
                "description": "Diameter of each raised bead in mm (typical 0.3–0.8).",
            },
            "field_layout": {
                "type": "string",
                "enum": ["line", "grid"],
                "description": (
                    "'line' — single row of stones. "
                    "'grid' — rectangular array of stones."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "bead_count_per_stone", "bead_diameter", "field_layout"],
    },
)


@register(jewelry_bead_grain_spec, write=True)
async def run_jewelry_create_bead_grain(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    bead_count_per_stone = a.get("bead_count_per_stone")
    bead_diameter = a.get("bead_diameter")
    field_layout = a.get("field_layout", "line")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("bead_diameter", bead_diameter),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        bcp = int(bead_count_per_stone)
    except (TypeError, ValueError):
        return err_payload("bead_count_per_stone must be an integer", "BAD_ARGS")
    if bcp < 2:
        return err_payload(
            f"bead_count_per_stone must be >= 2; got {bcp}", "BAD_ARGS"
        )

    field_layout_clean = (field_layout or "line").strip().lower()
    if field_layout_clean not in _VALID_BEAD_LAYOUTS:
        return err_payload(
            f"field_layout must be one of {sorted(_VALID_BEAD_LAYOUTS)}; got {field_layout!r}",
            "BAD_ARGS",
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_bead_grain")

    node = build_bead_grain_node(
        node_id=node_id,
        stone_diameter=float(stone_diameter),
        bead_count_per_stone=bcp,
        bead_diameter=float(bead_diameter),
        field_layout=field_layout_clean,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_bead_grain",
        "stone_diameter": float(stone_diameter),
        "bead_count_per_stone": bcp,
        "field_layout": field_layout_clean,
        "_bead_pitch_deg": node["_bead_pitch_deg"],
    })


# ---------------------------------------------------------------------------
# Gypsy-pavé / star setting
# ---------------------------------------------------------------------------

_STAR_RAY_MIN = 4


def build_gypsy_pave_node(
    node_id: str,
    stone_diameter: float,
    seat_depth: float,
    star_ray_count: int,
) -> dict:
    """
    Compute the gypsy-pavé (star setting) node spec.

    The worker's opJewelryGypsyPave builds:
      - A flush-set stone seat of diameter `stone_diameter` and depth
        `seat_depth` (the stone sits flush with the metal surface, as in a
        standard flush/gypsy setting).
      - `star_ray_count` bright-cut engraved rays radiating from the stone's
        girdle edge outward across the surrounding metal, creating a decorative
        star or sunburst pattern that catches light and visually enlarges the
        stone.

    This is also called a "star setting" or "bright-cut star" in the trade.

    Derived hints:
      _ray_pitch_deg — angular pitch between adjacent rays = 360 / star_ray_count.
      _seat_radius   — stone_diameter / 2.
    """
    ray_pitch_deg = 360.0 / star_ray_count if star_ray_count > 0 else 0.0
    seat_radius = stone_diameter / 2.0

    return {
        "id": node_id,
        "op": "jewelry_gypsy_pave",
        "stone_diameter": stone_diameter,
        "seat_depth": seat_depth,
        "star_ray_count": star_ray_count,
        "_ray_pitch_deg": round(ray_pitch_deg, 4),
        "_seat_radius": round(seat_radius, 4),
    }


jewelry_gypsy_pave_spec = ToolSpec(
    name="jewelry_create_gypsy_pave",
    description=(
        "Append a `jewelry_gypsy_pave` node to a `.feature` file. "
        "Generates a gypsy-pavé (star setting) — a flush-set stone with "
        "bright-cut engraved rays radiating outward from the stone's edge "
        "across the surrounding metal surface. "
        "The stone sits flush (its table level with the metal) and the "
        "`star_ray_count` V-cut rays create a decorative star or sunburst "
        "halo that catches light. Also called 'star setting' or 'bright-cut "
        "star'. Minimum ray count: 4. "
        "Output: node spec consumed by opJewelryGypsyPave."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of the stone in mm.",
            },
            "seat_depth": {
                "type": "number",
                "description": "Depth of the flush seat in mm (typically 60–80% of stone depth).",
            },
            "star_ray_count": {
                "type": "integer",
                "description": (
                    "Number of engraved star rays radiating from the stone. "
                    "Must be >= 4. Typical: 6, 8, 12."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "seat_depth", "star_ray_count"],
    },
)


@register(jewelry_gypsy_pave_spec, write=True)
async def run_jewelry_create_gypsy_pave(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    seat_depth = a.get("seat_depth")
    star_ray_count = a.get("star_ray_count")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("seat_depth", seat_depth),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        src = int(star_ray_count)
    except (TypeError, ValueError):
        return err_payload("star_ray_count must be an integer", "BAD_ARGS")
    if src < _STAR_RAY_MIN:
        return err_payload(
            f"star_ray_count must be >= {_STAR_RAY_MIN}; got {src}", "BAD_ARGS"
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_gypsy_pave")

    node = build_gypsy_pave_node(
        node_id=node_id,
        stone_diameter=float(stone_diameter),
        seat_depth=float(seat_depth),
        star_ray_count=src,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_gypsy_pave",
        "stone_diameter": float(stone_diameter),
        "star_ray_count": src,
        "_ray_pitch_deg": node["_ray_pitch_deg"],
    })


# ---------------------------------------------------------------------------
# Illusion / miracle-plate setting
# ---------------------------------------------------------------------------

_ILLUSION_FACET_MIN = 4


def build_illusion_node(
    node_id: str,
    stone_diameter: float,
    plate_diameter: float,
    facet_count: int,
) -> dict:
    """
    Compute the illusion-setting node spec.

    The worker's opJewelryIllusion builds:
      - A stone seat of diameter `stone_diameter` at the centre.
      - A polished metal "miracle plate" of diameter `plate_diameter`
        surrounding the stone.  The plate is faceted with `facet_count` flat
        mirror-polished faces arranged radially so they reflect light similarly
        to the stone's own facets, making the small stone appear larger.

    The plate_diameter must be > stone_diameter.

    Derived hints:
      _plate_wall_width — radial width of the plate surround =
                          (plate_diameter - stone_diameter) / 2.
      _facet_pitch_deg  — angular pitch between adjacent plate facets =
                          360 / facet_count.
    """
    plate_wall_width = (plate_diameter - stone_diameter) / 2.0
    facet_pitch_deg = 360.0 / facet_count if facet_count > 0 else 0.0

    return {
        "id": node_id,
        "op": "jewelry_illusion",
        "stone_diameter": stone_diameter,
        "plate_diameter": plate_diameter,
        "facet_count": facet_count,
        "_plate_wall_width": round(plate_wall_width, 4),
        "_facet_pitch_deg": round(facet_pitch_deg, 4),
    }


jewelry_illusion_spec = ToolSpec(
    name="jewelry_create_illusion",
    description=(
        "Append a `jewelry_illusion` node to a `.feature` file. "
        "Generates an illusion (miracle-plate) setting — a small stone set at "
        "the centre of a larger polished metal plate whose faceted surface "
        "reflects light like the stone itself, creating the visual illusion that "
        "the stone is the size of the plate. "
        "The plate (`plate_diameter`) must be larger than `stone_diameter`. "
        "The plate surface is divided into `facet_count` radial mirror-polished "
        "faces (minimum 4). "
        "Output: node spec consumed by opJewelryIllusion."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of the actual stone in mm.",
            },
            "plate_diameter": {
                "type": "number",
                "description": (
                    "Outer diameter of the illusion plate in mm. "
                    "Must be > stone_diameter."
                ),
            },
            "facet_count": {
                "type": "integer",
                "description": (
                    "Number of radial mirror facets on the plate surround. "
                    "Must be >= 4. Typical: 8, 12, 16."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_diameter", "plate_diameter", "facet_count"],
    },
)


@register(jewelry_illusion_spec, write=True)
async def run_jewelry_create_illusion(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_diameter = a.get("stone_diameter")
    plate_diameter = a.get("plate_diameter")
    facet_count = a.get("facet_count")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("plate_diameter", plate_diameter),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        fc = int(facet_count)
    except (TypeError, ValueError):
        return err_payload("facet_count must be an integer", "BAD_ARGS")
    if fc < _ILLUSION_FACET_MIN:
        return err_payload(
            f"facet_count must be >= {_ILLUSION_FACET_MIN}; got {fc}", "BAD_ARGS"
        )

    try:
        sd = float(stone_diameter)
        pd = float(plate_diameter)
    except (TypeError, ValueError):
        return err_payload("stone_diameter and plate_diameter must be numbers", "BAD_ARGS")

    if pd <= sd:
        return err_payload(
            f"plate_diameter ({pd}) must be greater than stone_diameter ({sd})",
            "BAD_ARGS",
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_illusion")

    node = build_illusion_node(
        node_id=node_id,
        stone_diameter=sd,
        plate_diameter=pd,
        facet_count=fc,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_illusion",
        "stone_diameter": sd,
        "plate_diameter": pd,
        "facet_count": fc,
        "_plate_wall_width": node["_plate_wall_width"],
    })


# ---------------------------------------------------------------------------
# Invisible setting
# ---------------------------------------------------------------------------

_INVISIBLE_ROWS_MIN = 1
_INVISIBLE_COLS_MIN = 1


def build_invisible_node(
    node_id: str,
    stone_size: float,
    rail_width: float,
    rail_height: float,
    grid_rows: int,
    grid_cols: int,
) -> dict:
    """
    Compute the invisible-setting node spec.

    The worker's opJewelryInvisible builds:
      - A hidden rail framework (a grid of crossed metal rails) sized for a
        `grid_rows` × `grid_cols` array of princess/square-cut stones of
        `stone_size`.  Rail cross-section is `rail_width` × `rail_height`.
      - Each stone has a grooved girdle that slides onto the rails; no metal
        is visible between adjacent stones from above (hence "invisible").
      - The evaluate result includes `seat_positions` — a list of {row, col,
        x, y} dicts for downstream boolean-cut stone pockets.

    Derived hints:
      _total_width  — overall X extent of the setting = grid_cols * stone_size.
      _total_height — overall Y extent = grid_rows * stone_size.
      _stone_count  — grid_rows * grid_cols.
    """
    total_width = grid_cols * stone_size
    total_height = grid_rows * stone_size
    stone_count = grid_rows * grid_cols

    # Build seat position grid in the local XY plane.
    seats = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            x = c * stone_size + stone_size / 2.0
            y = r * stone_size + stone_size / 2.0
            seats.append({"row": r, "col": c, "x": round(x, 4), "y": round(y, 4)})

    return {
        "id": node_id,
        "op": "jewelry_invisible",
        "stone_size": stone_size,
        "rail_width": rail_width,
        "rail_height": rail_height,
        "grid_rows": grid_rows,
        "grid_cols": grid_cols,
        "seat_positions": seats,
        "_total_width": round(total_width, 4),
        "_total_height": round(total_height, 4),
        "_stone_count": stone_count,
    }


jewelry_invisible_spec = ToolSpec(
    name="jewelry_create_invisible",
    description=(
        "Append a `jewelry_invisible` node to a `.feature` file. "
        "Generates an invisible setting — a `grid_rows` × `grid_cols` array of "
        "princess (square) or calibrated stones held on a concealed rail "
        "framework with no visible metal between adjacent stones. "
        "Each stone's girdle has a groove that fits over the crossed rails; from "
        "above the stones appear as a continuous, metal-free surface. "
        "Rail geometry is defined by `rail_width` and `rail_height`. "
        "The evaluate result includes `seat_positions` for downstream boolean "
        "stone-pocket cutting. "
        "Output: node spec consumed by opJewelryInvisible."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "stone_size": {
                "type": "number",
                "description": "Side length (diameter) of each square stone in mm.",
            },
            "rail_width": {
                "type": "number",
                "description": "Width of each hidden rail in mm (typical 0.2–0.5).",
            },
            "rail_height": {
                "type": "number",
                "description": "Height (thickness) of each rail in mm (typical 0.5–1.5).",
            },
            "grid_rows": {
                "type": "integer",
                "description": "Number of stone rows in the grid. Must be >= 1.",
            },
            "grid_cols": {
                "type": "integer",
                "description": "Number of stone columns in the grid. Must be >= 1.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "stone_size", "rail_width", "rail_height", "grid_rows", "grid_cols"],
    },
)


@register(jewelry_invisible_spec, write=True)
async def run_jewelry_create_invisible(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    stone_size = a.get("stone_size")
    rail_width = a.get("rail_width")
    rail_height = a.get("rail_height")
    grid_rows = a.get("grid_rows")
    grid_cols = a.get("grid_cols")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    for fname, fval in [
        ("stone_size", stone_size),
        ("rail_width", rail_width),
        ("rail_height", rail_height),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        rows = int(grid_rows)
    except (TypeError, ValueError):
        return err_payload("grid_rows must be an integer", "BAD_ARGS")
    if rows < _INVISIBLE_ROWS_MIN:
        return err_payload(
            f"grid_rows must be >= {_INVISIBLE_ROWS_MIN}; got {rows}", "BAD_ARGS"
        )

    try:
        cols = int(grid_cols)
    except (TypeError, ValueError):
        return err_payload("grid_cols must be an integer", "BAD_ARGS")
    if cols < _INVISIBLE_COLS_MIN:
        return err_payload(
            f"grid_cols must be >= {_INVISIBLE_COLS_MIN}; got {cols}", "BAD_ARGS"
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_invisible")

    node = build_invisible_node(
        node_id=node_id,
        stone_size=float(stone_size),
        rail_width=float(rail_width),
        rail_height=float(rail_height),
        grid_rows=rows,
        grid_cols=cols,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_invisible",
        "stone_size": float(stone_size),
        "grid_rows": rows,
        "grid_cols": cols,
        "_stone_count": node["_stone_count"],
        "_total_width": node["_total_width"],
        "_total_height": node["_total_height"],
    })


# ===========================================================================
# PRONG / HEAD VARIANT LIBRARY
# ===========================================================================
#
# Six additional prong-wire variants: double_prong, claw_prong, v_prong,
# fishtail_prong, split_prong, decorative_prong.
# Each shares the same parametric core (stone_diameter, prong_count,
# wire_gauge, prong_height) and adds a variant-specific parameter.
# ---------------------------------------------------------------------------

_VALID_PRONG_VARIANTS = {
    "double_prong",
    "claw_prong",
    "v_prong",
    "fishtail_prong",
    "split_prong",
    "decorative_prong",
}

_VALID_DECORATIVE_PROFILES = {"round", "tapered", "filigree", "star", "leaf"}


def build_prong_variant_node(
    node_id: str,
    variant: str,
    stone_diameter: float,
    prong_count: int,
    wire_gauge: float,
    prong_height: float,
    *,
    # variant-specific optional param — meaning depends on variant
    variant_param: float = 0.0,
    variant_profile: str = "round",
) -> dict:
    """
    Compute a prong-variant node spec.

    Variants
    --------
    double_prong
        Two parallel wires of `wire_gauge` run side-by-side per prong
        position (doubles the grip area).  `variant_param` = gap between the
        two wires in mm (default 0.3 mm).

    claw_prong
        A single wire with a curved claw tip that hooks over the stone's
        girdle; provides maximum security.  `variant_param` = claw hook depth
        in mm (default 0.4 mm).

    v_prong
        A V-shaped prong with a sharp internal corner that cradles a pointed
        culet (marquise, pear, princess corners).  `variant_param` = half-
        angle of the V in degrees (default 45°).  Best used with 4-prong.

    fishtail_prong
        The prong tip is split into two curved tines that spread over the
        girdle like a fishtail; this is the most decorative option.
        `variant_param` = fishtail spread width in mm (default 0.8 mm).

    split_prong
        The prong is split through most of its height into two tines;
        common in bypass / two-tone rings.  `variant_param` = split start
        height above the bearing seat as a fraction of `prong_height`
        (default 0.5, i.e. split begins halfway up).

    decorative_prong
        A prong with a decorative cross-section profile.  `variant_param`
        is unused; instead `variant_profile` selects the profile:
        `round`, `tapered`, `filigree`, `star`, `leaf`.

    Derived hints
    -------------
    _head_outer_diameter — same formula as jewelry_prong_head:
                           stone_diameter + 2 * wire_gauge.
    _prong_pitch_deg     — angular pitch between adjacent prongs =
                           360 / prong_count.
    """
    head_outer_diameter = stone_diameter + 2.0 * wire_gauge
    prong_pitch_deg = 360.0 / prong_count if prong_count > 0 else 0.0

    return {
        "id": node_id,
        "op": "jewelry_prong_variant",
        "variant": variant,
        "stone_diameter": stone_diameter,
        "prong_count": prong_count,
        "wire_gauge": wire_gauge,
        "prong_height": prong_height,
        "variant_param": variant_param,
        "variant_profile": variant_profile,
        "_head_outer_diameter": round(head_outer_diameter, 4),
        "_prong_pitch_deg": round(prong_pitch_deg, 4),
    }


jewelry_prong_variant_spec = ToolSpec(
    name="jewelry_create_prong_variant",
    description=(
        "Append a `jewelry_prong_variant` node to a `.feature` file. "
        "Generates one of six specialised prong-wire variants (double, claw, "
        "V, fishtail, split, decorative) sized to the stone. "
        "All variants share `stone_diameter`, `prong_count`, `wire_gauge`, and "
        "`prong_height`; each adds a variant-specific parameter. "
        "\n\nVariants:\n"
        "- **`double_prong`** — two side-by-side wires per prong position. "
        "`variant_param` = gap between wires in mm (default 0.3).\n"
        "- **`claw_prong`** — curved claw tip hooks over the girdle. "
        "`variant_param` = claw hook depth in mm (default 0.4).\n"
        "- **`v_prong`** — V-shaped prong for pointed stones (marquise/pear/princess). "
        "`variant_param` = V half-angle in degrees (default 45).\n"
        "- **`fishtail_prong`** — split fishtail tip for decorative look. "
        "`variant_param` = fishtail spread width in mm (default 0.8).\n"
        "- **`split_prong`** — prong split into two tines from mid-height. "
        "`variant_param` = split start as fraction of prong_height (default 0.5).\n"
        "- **`decorative_prong`** — custom cross-section profile. "
        "`variant_profile` selects profile: `round`, `tapered`, `filigree`, `star`, `leaf`.\n"
        "\nOutput: node spec consumed by the OCCT worker's opJewelryProngVariant handler."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "variant": {
                "type": "string",
                "enum": sorted(_VALID_PRONG_VARIANTS),
                "description": "Prong variant type.",
            },
            "stone_diameter": {
                "type": "number",
                "description": "Girdle diameter of the stone in mm.",
            },
            "prong_count": {
                "type": "integer",
                "description": "Number of prong positions around the stone (typically 4 or 6).",
            },
            "wire_gauge": {
                "type": "number",
                "description": "Prong wire diameter in mm (typical 0.8–1.5).",
            },
            "prong_height": {
                "type": "number",
                "description": "Height the prong extends above the stone's girdle plane in mm.",
            },
            "variant_param": {
                "type": "number",
                "description": (
                    "Variant-specific numeric parameter (see variant descriptions above). "
                    "Default 0.0 (worker uses built-in default for each variant)."
                ),
            },
            "variant_profile": {
                "type": "string",
                "enum": sorted(_VALID_DECORATIVE_PROFILES),
                "description": (
                    "Profile for `decorative_prong` variant. "
                    "One of: round, tapered, filigree, star, leaf. "
                    "Ignored for all other variants."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "variant", "stone_diameter", "prong_count", "wire_gauge", "prong_height"],
    },
)


@register(jewelry_prong_variant_spec, write=True)
async def run_jewelry_create_prong_variant(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    variant = a.get("variant", "").strip().lower()
    stone_diameter = a.get("stone_diameter")
    prong_count = a.get("prong_count")
    wire_gauge = a.get("wire_gauge")
    prong_height = a.get("prong_height")
    variant_param = a.get("variant_param", 0.0)
    variant_profile = a.get("variant_profile", "round")
    node_id = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    if variant not in _VALID_PRONG_VARIANTS:
        return err_payload(
            f"variant must be one of {sorted(_VALID_PRONG_VARIANTS)}; got {variant!r}",
            "BAD_ARGS",
        )

    for fname, fval in [
        ("stone_diameter", stone_diameter),
        ("wire_gauge", wire_gauge),
        ("prong_height", prong_height),
    ]:
        err = _positive(fname, fval)
        if err:
            return err_payload(err, "BAD_ARGS")

    try:
        pc = int(prong_count)
    except (TypeError, ValueError):
        return err_payload("prong_count must be an integer", "BAD_ARGS")
    if pc < 2:
        return err_payload(f"prong_count must be >= 2; got {pc}", "BAD_ARGS")

    try:
        vp = float(variant_param)
    except (TypeError, ValueError):
        vp = 0.0
    if vp < 0:
        return err_payload(f"variant_param must be >= 0; got {vp}", "BAD_ARGS")

    vprofile = (variant_profile or "round").strip().lower()
    if vprofile not in _VALID_DECORATIVE_PROFILES:
        return err_payload(
            f"variant_profile must be one of {sorted(_VALID_DECORATIVE_PROFILES)}; got {variant_profile!r}",
            "BAD_ARGS",
        )

    # v_prong half-angle must be < 90.
    if variant == "v_prong" and vp > 0 and vp >= 90.0:
        return err_payload(
            f"v_prong variant_param (half-angle) must be < 90°; got {vp}", "BAD_ARGS"
        )

    # split_prong fraction must be in (0, 1].
    if variant == "split_prong" and vp > 0 and vp > 1.0:
        return err_payload(
            f"split_prong variant_param (split fraction) must be in (0, 1]; got {vp}",
            "BAD_ARGS",
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jewelry_prong_variant")

    node = build_prong_variant_node(
        node_id=node_id,
        variant=variant,
        stone_diameter=float(stone_diameter),
        prong_count=pc,
        wire_gauge=float(wire_gauge),
        prong_height=float(prong_height),
        variant_param=vp,
        variant_profile=vprofile,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "jewelry_prong_variant",
        "variant": variant,
        "stone_diameter": float(stone_diameter),
        "prong_count": pc,
        "_head_outer_diameter": node["_head_outer_diameter"],
    })

