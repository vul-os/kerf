"""
LLM tools for mechanism synthesis — kerf-mates coverage sweep.

Wires three tested-but-orphaned synthesis functions as LLM tools:

  synthesise_four_bar_spec / run_synthesise_four_bar
      → kerf_mates.synthesis.fourbar.synthesise_four_bar
      Burmester 4-bar linkage synthesis from three coupler-curve precision points.

  synthesise_cam_spec / run_synthesise_cam
      → kerf_mates.synthesis.cam.synthesise_cam
      Cam-profile synthesis from a follower motion law (cycloidal / polynomial /
      harmonic) with full kinematic output (displacement, velocity, acceleration).

  synthesise_gear_train_spec / run_synthesise_gear_train
      → kerf_mates.synthesis.gear_train.synthesise_gear_train
      1- or 2-stage ISO spur-gear train synthesis for a target ratio.

All tools are registered via ctx.tools.register() in plugin.py.
Never raises — all failures are returned as {"ok": False, "reason": ...}.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mates._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# synthesise_four_bar
# ---------------------------------------------------------------------------

synthesise_four_bar_spec = ToolSpec(
    name="synthesise_four_bar",
    description=(
        "Synthesise a 4-bar planar linkage whose coupler curve passes through "
        "three specified precision points (Burmester theory). "
        "Returns link lengths (r1, r2, r3, r4), coupler-point offset (px, py), "
        "Grashof classification, and max error."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
                "maxItems": 3,
                "description": (
                    "Exactly three [x, y] coupler-curve precision points (mm)."
                ),
            },
            "tol_mm": {
                "type": "number",
                "description": (
                    "Acceptable max distance from any precision point to the "
                    "synthesised coupler curve (mm). Default 0.5."
                ),
            },
            "max_iters": {
                "type": "integer",
                "description": "Nelder-Mead iteration budget. Default 2000.",
            },
        },
        "required": ["points"],
    },
)


@register(synthesise_four_bar_spec, write=False)
async def run_synthesise_four_bar(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    points = a.get("points")
    if not isinstance(points, list):
        return err_payload("points must be a list of [x, y] pairs", "BAD_ARGS")

    kwargs: dict[str, Any] = {}
    if "tol_mm" in a:
        kwargs["tol_mm"] = float(a["tol_mm"])
    if "max_iters" in a:
        kwargs["max_iters"] = int(a["max_iters"])

    from kerf_mates.synthesis.fourbar import synthesise_four_bar
    result = synthesise_four_bar(points, **kwargs)

    if not result.get("ok"):
        return err_payload(result.get("reason", "synthesis failed"), "SYNTH_ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# synthesise_cam
# ---------------------------------------------------------------------------

synthesise_cam_spec = ToolSpec(
    name="synthesise_cam",
    description=(
        "Synthesise a cam follower profile from a motion law. "
        "Returns a sampled profile (displacement, velocity, acceleration vs. "
        "cam angle) for cycloidal, polynomial (3-4-5 or 4-5-6-7), or "
        "harmonic rise/fall segments."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "law": {
                "type": "string",
                "enum": ["cycloidal", "polynomial", "harmonic"],
                "description": "Follower motion law.",
            },
            "h": {
                "type": "number",
                "description": "Follower total lift (mm, > 0).",
            },
            "beta_deg": {
                "type": "number",
                "description": "Cam rotation for the segment (degrees, 0 < beta <= 360).",
            },
            "n_points": {
                "type": "integer",
                "description": "Number of cam-angle samples. Default 360.",
            },
            "rise": {
                "type": "boolean",
                "description": "True for rise segment, False for fall. Default true.",
            },
            "poly_order": {
                "type": "integer",
                "enum": [4, 5, 6, 7],
                "description": (
                    "Polynomial order (4, 5, 6, or 7). "
                    "Used only when law='polynomial'. Default 5."
                ),
            },
        },
        "required": ["law", "h", "beta_deg"],
    },
)


@register(synthesise_cam_spec, write=False)
async def run_synthesise_cam(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    law = a.get("law", "")
    if not law:
        return err_payload("law is required", "BAD_ARGS")

    try:
        h = float(a["h"])
        beta_deg = float(a["beta_deg"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"h and beta_deg must be numbers: {e}", "BAD_ARGS")

    kwargs: dict[str, Any] = {}
    if "n_points" in a:
        kwargs["n_points"] = int(a["n_points"])
    if "rise" in a:
        kwargs["rise"] = bool(a["rise"])
    if "poly_order" in a:
        kwargs["poly_order"] = int(a["poly_order"])

    from kerf_mates.synthesis.cam import synthesise_cam
    result = synthesise_cam(law, h, beta_deg, **kwargs)

    if not result.get("ok"):
        return err_payload(result.get("reason", "cam synthesis failed"), "SYNTH_ERROR")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# synthesise_gear_train
# ---------------------------------------------------------------------------

synthesise_gear_train_spec = ToolSpec(
    name="synthesise_gear_train",
    description=(
        "Synthesise a 1- or 2-stage ISO spur-gear train for a target ratio. "
        "Returns stage configurations with standard module, tooth counts (z1, z2), "
        "centre distance, and pitch diameters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_ratio": {
                "type": "number",
                "description": (
                    "Desired overall gear ratio (z2/z1 per stage, product). "
                    "> 1 = reduction; < 1 = overdrive; = 1 = 1:1."
                ),
            },
            "speed_range_rpm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": "[min_rpm, max_rpm] for the input shaft. Default [0, 10000].",
            },
            "tol_ratio": {
                "type": "number",
                "description": "Fractional tolerance on the achieved ratio. Default 0.02 (2%).",
            },
            "prefer_stages": {
                "type": "integer",
                "enum": [1, 2],
                "description": "Force 1-stage or 2-stage synthesis. Default: automatic.",
            },
            "pressure_angle_deg": {
                "type": "number",
                "description": "Standard pressure angle in degrees (10–30). Default 20.",
            },
        },
        "required": ["target_ratio"],
    },
)


@register(synthesise_gear_train_spec, write=False)
async def run_synthesise_gear_train(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    target_ratio = a.get("target_ratio")
    if target_ratio is None:
        return err_payload("target_ratio is required", "BAD_ARGS")

    kwargs: dict[str, Any] = {}
    if "speed_range_rpm" in a:
        sr = a["speed_range_rpm"]
        kwargs["speed_range_rpm"] = (float(sr[0]), float(sr[1]))
    if "tol_ratio" in a:
        kwargs["tol_ratio"] = float(a["tol_ratio"])
    if "prefer_stages" in a:
        kwargs["prefer_stages"] = int(a["prefer_stages"])
    if "pressure_angle_deg" in a:
        kwargs["pressure_angle_deg"] = float(a["pressure_angle_deg"])

    from kerf_mates.synthesis.gear_train import synthesise_gear_train
    result = synthesise_gear_train(float(target_ratio), **kwargs)

    if not result.get("ok"):
        return err_payload(result.get("reason", "gear-train synthesis failed"), "SYNTH_ERROR")
    return ok_payload(result)
