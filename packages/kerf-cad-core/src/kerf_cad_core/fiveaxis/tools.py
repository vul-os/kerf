"""
kerf_cad_core.fiveaxis.tools — LLM tool wrappers for 5-axis machine kinematics.

Registers tools with the Kerf tool registry:

  fiveaxis_forward_kinematics   — machine axis positions → tip & tool axis in part frame
  fiveaxis_inverse_post         — tool tip + tool axis → rotary angles + XYZ (RTCP)
  fiveaxis_tool_axis_lead_lag   — lead/lag angles + feed direction → tool axis vector
  fiveaxis_linearisation        — rotary move chord deviation → segment count
  fiveaxis_rotary_feedrate      — DPM or inverse-time feed rate for rotary arc move
  fiveaxis_collision_cone       — holder collision-cone clearance check

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
Soons, J.A. et al. "Modelling of five-axis machine tool kinematics", IJMTM 2001.
Bohez, E.L.J. "Five-axis milling machine tool kinematic chain design", IJMTM 2002.

Author: imranparuk
"""
from __future__ import annotations

import json
import math

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.fiveaxis.kinematics import (
    MachineConfig,
    MachineType,
    RotaryAxis,
    forward_kinematics,
    inverse_post,
    tool_axis_from_lead_lag,
    linearisation_segments,
    rotary_feedrate,
    collision_cone_check,
)


# ---------------------------------------------------------------------------
# Helper: build MachineConfig from JSON dict
# ---------------------------------------------------------------------------

def _build_config(a: dict) -> MachineConfig:
    """Build a MachineConfig from the 'machine' sub-dict in tool args."""
    m = a.get("machine", {})
    mtype_str = m.get("type", "table_table")
    try:
        mtype = MachineType(mtype_str)
    except ValueError:
        raise ValueError(
            f"Unknown machine type '{mtype_str}'; "
            "use 'table_table', 'head_head', or 'table_head'."
        )

    def _make_axis(d: dict, defaults: dict) -> RotaryAxis:
        ax_vec = d.get("axis", defaults["axis"])
        return RotaryAxis(
            axis=tuple(float(v) for v in ax_vec),  # type: ignore[arg-type]
            lo_rad=math.radians(float(d.get("lo_deg", defaults["lo_deg"]))),
            hi_rad=math.radians(float(d.get("hi_deg", defaults["hi_deg"]))),
            name=str(d.get("name", defaults["name"])),
        )

    if mtype == MachineType.TABLE_TABLE:
        r1_defaults = {"axis": [1, 0, 0], "lo_deg": -120.0, "hi_deg": 30.0, "name": "A"}
        r2_defaults = {"axis": [0, 0, 1], "lo_deg": -360.0, "hi_deg": 360.0, "name": "C"}
    elif mtype == MachineType.HEAD_HEAD:
        r1_defaults = {"axis": [0, 1, 0], "lo_deg": -120.0, "hi_deg": 120.0, "name": "B"}
        r2_defaults = {"axis": [0, 0, 1], "lo_deg": -360.0, "hi_deg": 360.0, "name": "C"}
    else:  # TABLE_HEAD
        r1_defaults = {"axis": [1, 0, 0], "lo_deg": -120.0, "hi_deg": 30.0, "name": "A"}
        r2_defaults = {"axis": [0, 1, 0], "lo_deg": -120.0, "hi_deg": 120.0, "name": "B"}

    r1_dict = m.get("first_rotary", {})
    r2_dict = m.get("second_rotary", {})

    return MachineConfig(
        machine_type=mtype,
        first_rotary=_make_axis(r1_dict, r1_defaults),
        second_rotary=_make_axis(r2_dict, r2_defaults),
        pivot_length_mm=float(m.get("pivot_length_mm", 0.0)),
    )


# ---------------------------------------------------------------------------
# Tool: fiveaxis_forward_kinematics
# ---------------------------------------------------------------------------

_fk_spec = ToolSpec(
    name="fiveaxis_forward_kinematics",
    description=(
        "5-axis machine forward kinematics: convert machine axis positions "
        "(X, Y, Z linear + two rotary angles) into tool-tip position and tool-axis "
        "direction in the part/workpiece frame.\n"
        "\n"
        "Three machine types:\n"
        "  'table_table' — AC trunnion (default): A tilts around X, C rotates around Z; "
        "both pivots in table.\n"
        "  'head_head'   — BC spindle: B tilts around Y, C rotates around Z in head.\n"
        "  'table_head'  — A in table, B in head.\n"
        "\n"
        "RTCP pivot_length_mm: distance from rotary pivot to tool tip; compensates "
        "linear axes so the tip stays on-program.\n"
        "\n"
        "Returns tip_part_mm [x,y,z] and tool_axis [ix,iy,iz] in part frame, "
        "plus any over-travel warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "x_mm": {"type": "number", "description": "Linear X axis position (mm)."},
            "y_mm": {"type": "number", "description": "Linear Y axis position (mm)."},
            "z_mm": {"type": "number", "description": "Linear Z axis position (mm)."},
            "q1_deg": {
                "type": "number",
                "description": "First rotary angle (degrees): A for table_table/table_head, B for head_head.",
            },
            "q2_deg": {
                "type": "number",
                "description": "Second rotary angle (degrees): C for table_table/head_head, B for table_head.",
            },
            "machine": {
                "type": "object",
                "description": (
                    "Machine configuration (optional; defaults to AC trunnion). "
                    "Fields: type ('table_table'|'head_head'|'table_head'), "
                    "pivot_length_mm (float), "
                    "first_rotary: {axis:[x,y,z], lo_deg, hi_deg, name}, "
                    "second_rotary: {axis:[x,y,z], lo_deg, hi_deg, name}."
                ),
            },
        },
        "required": ["x_mm", "y_mm", "z_mm", "q1_deg", "q2_deg"],
    },
)


@register(_fk_spec, write=False)
async def run_fiveaxis_forward_kinematics(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("x_mm", "y_mm", "z_mm", "q1_deg", "q2_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    try:
        config = _build_config(a)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    result = forward_kinematics(
        config,
        float(a["x_mm"]),
        float(a["y_mm"]),
        float(a["z_mm"]),
        math.radians(float(a["q1_deg"])),
        math.radians(float(a["q2_deg"])),
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fiveaxis_inverse_post
# ---------------------------------------------------------------------------

_ik_spec = ToolSpec(
    name="fiveaxis_inverse_post",
    description=(
        "5-axis inverse post-processing: convert desired tool-tip position and "
        "tool-axis direction (in part frame) into machine rotary angles and linear "
        "axis positions (RTCP compensated).\n"
        "\n"
        "Returns up to two solutions (elbow-up/down or ±A).  The 'best' index "
        "points to the solution closest to the previous position (shortest angular "
        "travel) that stays within travel limits.\n"
        "\n"
        "Singularity detection: when the tool axis aligns with the machine Z-axis "
        "(gimbal lock), a warning is emitted and a small avoidance tilt is applied.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tip_part_mm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Tool-tip position in part frame [x, y, z] (mm).",
            },
            "tool_axis": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": (
                    "Tool axis direction unit vector [ix, iy, iz] in part frame "
                    "(points away from part surface toward spindle)."
                ),
            },
            "prev_q1_deg": {
                "type": "number",
                "description": "Previous first-rotary position (degrees), for shortest-path selection.",
            },
            "prev_q2_deg": {
                "type": "number",
                "description": "Previous second-rotary position (degrees), for shortest-path selection.",
            },
            "avoidance_tilt_deg": {
                "type": "number",
                "description": "Avoidance tilt applied at singularity (degrees, default 1.0).",
            },
            "machine": {
                "type": "object",
                "description": "Machine configuration (same as fiveaxis_forward_kinematics).",
            },
        },
        "required": ["tip_part_mm", "tool_axis"],
    },
)


@register(_ik_spec, write=False)
async def run_fiveaxis_inverse_post(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("tip_part_mm") is None:
        return json.dumps({"ok": False, "reason": "tip_part_mm is required"})
    if a.get("tool_axis") is None:
        return json.dumps({"ok": False, "reason": "tool_axis is required"})

    tip_raw = a["tip_part_mm"]
    ax_raw  = a["tool_axis"]
    if len(tip_raw) != 3:
        return json.dumps({"ok": False, "reason": "tip_part_mm must have 3 elements"})
    if len(ax_raw) != 3:
        return json.dumps({"ok": False, "reason": "tool_axis must have 3 elements"})

    try:
        config = _build_config(a)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    prev: None = None
    if "prev_q1_deg" in a and "prev_q2_deg" in a:
        prev = (math.radians(float(a["prev_q1_deg"])), math.radians(float(a["prev_q2_deg"])))  # type: ignore[assignment]

    tilt_rad = math.radians(float(a.get("avoidance_tilt_deg", 1.0)))

    tip = tuple(float(v) for v in tip_raw)  # type: ignore[arg-type]
    ax  = tuple(float(v) for v in ax_raw)   # type: ignore[arg-type]

    result = inverse_post(config, tip, ax, prev_angles_rad=prev, avoidance_tilt_rad=tilt_rad)  # type: ignore[arg-type]
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fiveaxis_tool_axis_lead_lag
# ---------------------------------------------------------------------------

_lead_lag_spec = ToolSpec(
    name="fiveaxis_tool_axis_lead_lag",
    description=(
        "Convert lead/lag angles into a tool-axis unit vector.\n"
        "\n"
        "Lead angle: tilt in the feed-direction plane (positive = lean forward "
        "relative to feed direction).\n"
        "Lag angle: tilt perpendicular to feed (positive = lean to the right of feed).\n"
        "\n"
        "The surface normal points away from the part material.  The tool starts "
        "perpendicular to the surface (aligned with normal), then is tilted.\n"
        "\n"
        "Returns tool_axis [ix, iy, iz] — the resulting tool orientation unit vector.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "feed_direction": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Unit vector of tool-path feed direction [x, y, z].",
            },
            "surface_normal": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Surface normal at contact point (points away from material) [x, y, z].",
            },
            "lead_angle_deg": {
                "type": "number",
                "description": "Lead angle (degrees, positive = lean forward). Default 0.",
            },
            "lag_angle_deg": {
                "type": "number",
                "description": "Lag/tilt angle (degrees, positive = lean right). Default 0.",
            },
        },
        "required": ["feed_direction", "surface_normal"],
    },
)


@register(_lead_lag_spec, write=False)
async def run_fiveaxis_tool_axis_lead_lag(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("feed_direction") is None:
        return json.dumps({"ok": False, "reason": "feed_direction is required"})
    if a.get("surface_normal") is None:
        return json.dumps({"ok": False, "reason": "surface_normal is required"})

    feed = a["feed_direction"]
    norm = a["surface_normal"]
    if len(feed) != 3:
        return json.dumps({"ok": False, "reason": "feed_direction must have 3 elements"})
    if len(norm) != 3:
        return json.dumps({"ok": False, "reason": "surface_normal must have 3 elements"})

    lead_rad = math.radians(float(a.get("lead_angle_deg", 0.0)))
    lag_rad  = math.radians(float(a.get("lag_angle_deg",  0.0)))

    feed_t = tuple(float(v) for v in feed)  # type: ignore[arg-type]
    norm_t = tuple(float(v) for v in norm)  # type: ignore[arg-type]

    result = tool_axis_from_lead_lag(feed_t, norm_t, lead_rad, lag_rad)  # type: ignore[arg-type]
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fiveaxis_linearisation
# ---------------------------------------------------------------------------

_lin_spec = ToolSpec(
    name="fiveaxis_linearisation",
    description=(
        "Estimate the number of linear interpolation segments required for a 5-axis "
        "rotary move to keep the chord deviation of the tool-tip arc within the "
        "specified tolerance.\n"
        "\n"
        "For a circular arc of radius R and subtended angle θ:\n"
        "  chord_deviation = R · (1 − cos(θ/2))   ≈ R·θ²/8  for small angles.\n"
        "\n"
        "The arc radius is approximated from the tool-tip distance from the pivot "
        "(computed via forward kinematics at the start position).\n"
        "\n"
        "Emits a warning if more than 100 segments are needed.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tip_part_mm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Tool-tip position in part frame [x, y, z] (mm).",
            },
            "q1_start_deg": {"type": "number", "description": "First rotary start angle (degrees)."},
            "q1_end_deg":   {"type": "number", "description": "First rotary end angle (degrees)."},
            "q2_start_deg": {"type": "number", "description": "Second rotary start angle (degrees)."},
            "q2_end_deg":   {"type": "number", "description": "Second rotary end angle (degrees)."},
            "x_mm": {"type": "number", "description": "Linear X start position (mm, default 0)."},
            "y_mm": {"type": "number", "description": "Linear Y start position (mm, default 0)."},
            "z_mm": {"type": "number", "description": "Linear Z start position (mm, default 0)."},
            "chord_tol_mm": {
                "type": "number",
                "description": "Maximum allowable chord deviation (mm, default 0.01).",
            },
            "machine": {
                "type": "object",
                "description": "Machine configuration (same as fiveaxis_forward_kinematics).",
            },
        },
        "required": ["tip_part_mm", "q1_start_deg", "q1_end_deg", "q2_start_deg", "q2_end_deg"],
    },
)


@register(_lin_spec, write=False)
async def run_fiveaxis_linearisation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("tip_part_mm", "q1_start_deg", "q1_end_deg", "q2_start_deg", "q2_end_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    tip_raw = a["tip_part_mm"]
    if len(tip_raw) != 3:
        return json.dumps({"ok": False, "reason": "tip_part_mm must have 3 elements"})

    try:
        config = _build_config(a)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    tip = tuple(float(v) for v in tip_raw)  # type: ignore[arg-type]
    result = linearisation_segments(
        config,
        tip,  # type: ignore[arg-type]
        math.radians(float(a["q1_start_deg"])),
        math.radians(float(a["q1_end_deg"])),
        math.radians(float(a["q2_start_deg"])),
        math.radians(float(a["q2_end_deg"])),
        x_mm=float(a.get("x_mm", 0.0)),
        y_mm=float(a.get("y_mm", 0.0)),
        z_mm=float(a.get("z_mm", 0.0)),
        chord_tol_mm=float(a.get("chord_tol_mm", 0.01)),
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fiveaxis_rotary_feedrate
# ---------------------------------------------------------------------------

_feed_spec = ToolSpec(
    name="fiveaxis_rotary_feedrate",
    description=(
        "Compute the rotary axis feed rate for a 5-axis arc move to achieve a "
        "desired tool-tip cutting speed.\n"
        "\n"
        "Two modes:\n"
        "  'dpm'          — Degrees Per Minute: F = V_tip × (180/π) / R\n"
        "  'inverse_time' — G93 inverse-time: F = V_tip / arc_length_per_degree\n"
        "\n"
        "arc_radius_mm must be > 0 (tool-tip arc radius from pivot).\n"
        "desired_tip_speed_mm_per_min must be > 0.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "arc_radius_mm": {
                "type": "number",
                "description": "Tool-tip arc radius (mm). Must be > 0.",
            },
            "desired_tip_speed_mm_per_min": {
                "type": "number",
                "description": "Desired tool-tip cutting speed (mm/min). Must be > 0.",
            },
            "method": {
                "type": "string",
                "enum": ["dpm", "inverse_time"],
                "description": "Feed-rate mode: 'dpm' (default) or 'inverse_time' (G93).",
            },
        },
        "required": ["arc_radius_mm", "desired_tip_speed_mm_per_min"],
    },
)


@register(_feed_spec, write=False)
async def run_fiveaxis_rotary_feedrate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("arc_radius_mm", "desired_tip_speed_mm_per_min"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    method = a.get("method", "dpm")
    result = rotary_feedrate(
        float(a["arc_radius_mm"]),
        float(a["desired_tip_speed_mm_per_min"]),
        method=method,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fiveaxis_collision_cone
# ---------------------------------------------------------------------------

_cone_spec = ToolSpec(
    name="fiveaxis_collision_cone",
    description=(
        "Check tool/holder collision-cone clearance for a given tool orientation.\n"
        "\n"
        "Models the holder as a cone around the tool axis.  The check determines "
        "whether the tilt angle between the tool axis and the surface normal exceeds "
        "the maximum allowable tilt (π/2 − half_cone_angle).\n"
        "\n"
        "Returns clearance_ok (bool), clearance_angle_deg (negative = violation), "
        "and the tilt and half-cone angles.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tool_axis": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Tool axis unit vector [ix, iy, iz] (points away from part).",
            },
            "half_cone_angle_deg": {
                "type": "number",
                "description": "Holder half-cone angle (degrees, 0…90). Typical: 7–15°.",
            },
            "holder_tilt_deg": {
                "type": "number",
                "description": (
                    "Tilt angle between tool axis and surface normal (degrees). "
                    "If 0 (default), computed from tool_axis vs. Z-up."
                ),
            },
        },
        "required": ["tool_axis", "half_cone_angle_deg"],
    },
)


@register(_cone_spec, write=False)
async def run_fiveaxis_collision_cone(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("tool_axis") is None:
        return json.dumps({"ok": False, "reason": "tool_axis is required"})
    if a.get("half_cone_angle_deg") is None:
        return json.dumps({"ok": False, "reason": "half_cone_angle_deg is required"})

    ax_raw = a["tool_axis"]
    if len(ax_raw) != 3:
        return json.dumps({"ok": False, "reason": "tool_axis must have 3 elements"})

    ax  = tuple(float(v) for v in ax_raw)  # type: ignore[arg-type]
    hca = math.radians(float(a["half_cone_angle_deg"]))
    tilt = math.radians(float(a.get("holder_tilt_deg", 0.0)))

    result = collision_cone_check(ax, hca, holder_tilt_rad=tilt)  # type: ignore[arg-type]
    return ok_payload(result)
