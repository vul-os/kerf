"""
kerf_cad_core.kinematics.tools — LLM tool wrappers for planar kinematics.

Registers seven tools with the Kerf tool registry:

  four_bar_grashof          — Grashof classification + type of a four-bar linkage
  four_bar_position         — Freudenstein position analysis (theta3, theta4)
  four_bar_transmission_angle — transmission angle quality metric
  four_bar_coupler_curve    — sample the coupler-point path
  slider_crank              — position / velocity / acceleration for any crank angle
  cam_follower_cycloidal    — cycloidal rise/fall cam follower kinematics
  cam_follower_harmonic     — harmonic (cosine) rise/fall cam follower kinematics

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
Norton, R.L. "Design of Machinery", 5th ed.
Shigley, J.E. & Uicker, J.J. "Theory of Machines & Mechanisms", 4th ed.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.kinematics.linkage import (
    four_bar_grashof,
    four_bar_position,
    four_bar_transmission_angle,
    four_bar_coupler_curve,
    slider_crank,
    cam_follower_cycloidal,
    cam_follower_harmonic,
)


# ---------------------------------------------------------------------------
# Tool: four_bar_grashof
# ---------------------------------------------------------------------------

_four_bar_grashof_spec = ToolSpec(
    name="four_bar_grashof",
    description=(
        "Classify a four-bar linkage using the Grashof condition.\n"
        "\n"
        "Determines whether the linkage is Grashof (at least one link can "
        "make a full rotation) or non-Grashof (all links only rock), and "
        "identifies the specific type:\n"
        "  'crank-rocker'   — input crank rotates fully, output rocks\n"
        "  'double-crank'   — both input and output rotate fully\n"
        "  'rocker-crank'   — input rocks, output rotates fully\n"
        "  'double-rocker'  — both input and output rock\n"
        "  'non-Grashof'    — no link can fully rotate\n"
        "  'change-point'   — special Grashof (S+L == P+Q)\n"
        "\n"
        "Convention: r1=ground, r2=crank (input), r3=coupler, r4=output.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r1": {"type": "number", "description": "Ground link length (> 0)."},
            "r2": {"type": "number", "description": "Crank (input) link length (> 0)."},
            "r3": {"type": "number", "description": "Coupler link length (> 0)."},
            "r4": {"type": "number", "description": "Output link length (> 0)."},
        },
        "required": ["r1", "r2", "r3", "r4"],
    },
)


@register(_four_bar_grashof_spec, write=False)
async def run_four_bar_grashof(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r1", "r2", "r3", "r4"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = four_bar_grashof(a["r1"], a["r2"], a["r3"], a["r4"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: four_bar_position
# ---------------------------------------------------------------------------

_four_bar_position_spec = ToolSpec(
    name="four_bar_position",
    description=(
        "Four-bar linkage position analysis (Freudenstein equation).\n"
        "\n"
        "Given crank angle theta2, computes the coupler angle theta3 and "
        "output-link angle theta4 using the closed-form Freudenstein equation "
        "with half-angle (Weierstrass) substitution.\n"
        "\n"
        "Convention: r1=ground, r2=crank (input), r3=coupler, r4=output.\n"
        "The ground pivot O2 is at the origin; O4 is at (r1, 0).\n"
        "\n"
        "Two assembly configurations exist (branch=1 open, branch=-1 crossed).\n"
        "\n"
        "Singular/locked configurations are reported in 'warnings' rather than "
        "raising exceptions.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r1": {"type": "number", "description": "Ground link length (> 0)."},
            "r2": {"type": "number", "description": "Crank length (> 0)."},
            "r3": {"type": "number", "description": "Coupler length (> 0)."},
            "r4": {"type": "number", "description": "Output link length (> 0)."},
            "theta2_deg": {
                "type": "number",
                "description": "Crank angle from positive x-axis (degrees).",
            },
            "branch": {
                "type": "integer",
                "enum": [1, -1],
                "description": "Assembly branch: 1 (open, default) or -1 (crossed).",
            },
        },
        "required": ["r1", "r2", "r3", "r4", "theta2_deg"],
    },
)


@register(_four_bar_position_spec, write=False)
async def run_four_bar_position(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r1", "r2", "r3", "r4", "theta2_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "branch" in a:
        kwargs["branch"] = a["branch"]

    result = four_bar_position(a["r1"], a["r2"], a["r3"], a["r4"], a["theta2_deg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: four_bar_transmission_angle
# ---------------------------------------------------------------------------

_four_bar_transmission_angle_spec = ToolSpec(
    name="four_bar_transmission_angle",
    description=(
        "Compute the transmission angle for a four-bar linkage at a given "
        "crank angle.\n"
        "\n"
        "The transmission angle mu is the angle at the coupler-output joint "
        "between the coupler (r3) and output (r4) links.  It measures the "
        "quality of force transmission to the output link.\n"
        "\n"
        "Acceptable range: 40° <= mu <= 140°.  Deviation from 90° should "
        "be kept below 50° for good mechanical advantage.\n"
        "\n"
        "Convention: r1=ground, r2=crank, r3=coupler, r4=output.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r1": {"type": "number", "description": "Ground link length (> 0)."},
            "r2": {"type": "number", "description": "Crank length (> 0)."},
            "r3": {"type": "number", "description": "Coupler length (> 0)."},
            "r4": {"type": "number", "description": "Output link length (> 0)."},
            "theta2_deg": {
                "type": "number",
                "description": "Crank angle from positive x-axis (degrees).",
            },
        },
        "required": ["r1", "r2", "r3", "r4", "theta2_deg"],
    },
)


@register(_four_bar_transmission_angle_spec, write=False)
async def run_four_bar_transmission_angle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r1", "r2", "r3", "r4", "theta2_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = four_bar_transmission_angle(
        a["r1"], a["r2"], a["r3"], a["r4"], a["theta2_deg"]
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: four_bar_coupler_curve
# ---------------------------------------------------------------------------

_four_bar_coupler_curve_spec = ToolSpec(
    name="four_bar_coupler_curve",
    description=(
        "Sample the coupler-point path of a four-bar linkage.\n"
        "\n"
        "Traces the trajectory of a point P fixed on the coupler link over "
        "one full crank revolution (0° to 360°).  The coupler point is "
        "specified by its (px, py) offset from the crank-coupler joint A, "
        "measured along and perpendicular to the coupler.\n"
        "\n"
        "Returns a list of {theta2_deg, x, y} dicts — one per sample.\n"
        "\n"
        "Convention: r1=ground, r2=crank, r3=coupler, r4=output.\n"
        "O2 (crank pivot) at origin; O4 (output pivot) at (r1, 0).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r1": {"type": "number", "description": "Ground link length (> 0)."},
            "r2": {"type": "number", "description": "Crank length (> 0)."},
            "r3": {"type": "number", "description": "Coupler length (> 0)."},
            "r4": {"type": "number", "description": "Output link length (> 0)."},
            "px": {
                "type": "number",
                "description": "Coupler point x-offset along coupler from joint A.",
            },
            "py": {
                "type": "number",
                "description": "Coupler point y-offset perpendicular to coupler from joint A.",
            },
            "n_points": {
                "type": "integer",
                "description": "Number of sample points in [0°, 360°) (default 72).",
            },
            "branch": {
                "type": "integer",
                "enum": [1, -1],
                "description": "Assembly branch: 1 (open, default) or -1 (crossed).",
            },
        },
        "required": ["r1", "r2", "r3", "r4", "px", "py"],
    },
)


@register(_four_bar_coupler_curve_spec, write=False)
async def run_four_bar_coupler_curve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r1", "r2", "r3", "r4", "px", "py"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "n_points" in a:
        kwargs["n_points"] = int(a["n_points"])
    if "branch" in a:
        kwargs["branch"] = a["branch"]

    result = four_bar_coupler_curve(
        a["r1"], a["r2"], a["r3"], a["r4"], a["px"], a["py"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: slider_crank
# ---------------------------------------------------------------------------

_slider_crank_spec = ToolSpec(
    name="slider_crank",
    description=(
        "Slider-crank position, velocity, and acceleration analysis.\n"
        "\n"
        "Computes slider position x_B, velocity v_B, and acceleration a_B "
        "for an in-line (zero-eccentricity) slider-crank mechanism at a "
        "given crank angle theta.\n"
        "\n"
        "  x_B = r·cos(θ) + √(l² − r²·sin²(θ))\n"
        "\n"
        "Velocity and acceleration are computed exactly (not the approximate "
        "n-ratio expansion), so results are valid for any r/l ratio.\n"
        "\n"
        "Set omega_rad_s=0 (default) to get position-only analysis.\n"
        "\n"
        "Singular configurations (r > l or near-singular) are reported in "
        "'warnings' rather than raising exceptions.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r": {
                "type": "number",
                "description": "Crank radius (> 0, any consistent length unit).",
            },
            "l": {
                "type": "number",
                "description": "Connecting-rod length (> 0, same unit as r).",
            },
            "theta_deg": {
                "type": "number",
                "description": "Crank angle from TDC / positive x-axis (degrees).",
            },
            "omega_rad_s": {
                "type": "number",
                "description": "Crank angular velocity (rad/s, default 0).",
            },
            "alpha_rad_s2": {
                "type": "number",
                "description": "Crank angular acceleration (rad/s², default 0).",
            },
        },
        "required": ["r", "l", "theta_deg"],
    },
)


@register(_slider_crank_spec, write=False)
async def run_slider_crank(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r", "l", "theta_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "omega_rad_s" in a:
        kwargs["omega_rad_s"] = a["omega_rad_s"]
    if "alpha_rad_s2" in a:
        kwargs["alpha_rad_s2"] = a["alpha_rad_s2"]

    result = slider_crank(a["r"], a["l"], a["theta_deg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: cam_follower_cycloidal
# ---------------------------------------------------------------------------

_cam_follower_cycloidal_spec = ToolSpec(
    name="cam_follower_cycloidal",
    description=(
        "Cycloidal cam-follower displacement, velocity, and acceleration.\n"
        "\n"
        "The cycloidal profile provides zero acceleration at both ends of "
        "the rise/fall segment, making it the best choice for high-speed "
        "cams (no impulsive loads).\n"
        "\n"
        "  y = h · [θ/β − (1/2π)·sin(2π·θ/β)]           (rise)\n"
        "  y' = (h/β)·[1 − cos(2π·θ/β)]                  (velocity / omega)\n"
        "  y'' = (2πh/β²)·sin(2π·θ/β)                    (acceleration / omega²)\n"
        "\n"
        "velocity_per_omega  = dy/dθ; multiply by ω (rad/s) for actual velocity.\n"
        "acceleration_per_omega2 = d²y/dθ²; multiply by ω² for actual acceleration.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "h": {
                "type": "number",
                "description": "Total follower lift / stroke (> 0, any length unit).",
            },
            "beta_deg": {
                "type": "number",
                "description": "Total cam rotation angle for the segment (degrees, > 0).",
            },
            "theta_deg": {
                "type": "number",
                "description": "Current cam angle within the segment (degrees, >= 0).",
            },
            "rise": {
                "type": "boolean",
                "description": "True (default) for rise; False for fall.",
            },
        },
        "required": ["h", "beta_deg", "theta_deg"],
    },
)


@register(_cam_follower_cycloidal_spec, write=False)
async def run_cam_follower_cycloidal(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("h", "beta_deg", "theta_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "rise" in a:
        kwargs["rise"] = bool(a["rise"])

    result = cam_follower_cycloidal(a["h"], a["beta_deg"], a["theta_deg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: cam_follower_harmonic
# ---------------------------------------------------------------------------

_cam_follower_harmonic_spec = ToolSpec(
    name="cam_follower_harmonic",
    description=(
        "Harmonic (cosine) cam-follower displacement, velocity, and acceleration.\n"
        "\n"
        "The harmonic (SHM) profile is simple to compute but has finite "
        "(non-zero) acceleration at the start and end of the segment, causing "
        "impulsive load transitions.  Use cycloidal or modified-trapezoidal "
        "profiles for high-speed cams.\n"
        "\n"
        "  y = (h/2)·[1 − cos(π·θ/β)]                    (rise)\n"
        "  y' = (πh/2β)·sin(π·θ/β)                        (velocity / omega)\n"
        "  y'' = (π²h/2β²)·cos(π·θ/β)                     (acceleration / omega²)\n"
        "\n"
        "velocity_per_omega  = dy/dθ; multiply by ω (rad/s) for actual velocity.\n"
        "acceleration_per_omega2 = d²y/dθ²; multiply by ω² for actual acceleration.\n"
        "\n"
        "A warning is always included about the acceleration discontinuity.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "h": {
                "type": "number",
                "description": "Total follower lift / stroke (> 0, any length unit).",
            },
            "beta_deg": {
                "type": "number",
                "description": "Total cam rotation angle for the segment (degrees, > 0).",
            },
            "theta_deg": {
                "type": "number",
                "description": "Current cam angle within the segment (degrees, >= 0).",
            },
            "rise": {
                "type": "boolean",
                "description": "True (default) for rise; False for fall.",
            },
        },
        "required": ["h", "beta_deg", "theta_deg"],
    },
)


@register(_cam_follower_harmonic_spec, write=False)
async def run_cam_follower_harmonic(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("h", "beta_deg", "theta_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "rise" in a:
        kwargs["rise"] = bool(a["rise"])

    result = cam_follower_harmonic(a["h"], a["beta_deg"], a["theta_deg"], **kwargs)
    return ok_payload(result)
