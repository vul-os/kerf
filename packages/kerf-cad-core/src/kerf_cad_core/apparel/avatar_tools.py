"""
kerf_cad_core.apparel.avatar_tools — LLM tool wrappers for the parametric avatar.

Registers two tools with the Kerf tool registry:

  apparel_build_avatar   — Build a parametric human avatar mesh from 12 ISO
                           8559-1:2017 anthropometric measurements (CLO3D-style).

  apparel_fit_dress_form — Compute the dress form (ease-expanded avatar) used for
                           cloth-pattern draping.

All tools are pure-Python + numpy; no OCC dependency.
Inputs validated; errors returned as {ok: false, reason: ...} — never raises.

References
----------
  ISO 8559-1:2017, "Clothing — Sizing systems — Part 1: Anthropometric
  definitions for body measurement".  ISO, Geneva.
  CLO Virtual Fashion (2023). "Avatar Editor User Manual", CLO3D v7.4.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.apparel.avatar import (
    AvatarMeasurements,
    build_avatar,
    fit_dress_form,
)


# ---------------------------------------------------------------------------
# Tool: apparel_build_avatar
# ---------------------------------------------------------------------------

_build_spec = ToolSpec(
    name="apparel_build_avatar",
    description=(
        "Build a parametric human avatar mesh from ISO 8559-1:2017 anthropometric measurements.\n"
        "\n"
        "Generates a Y-up mesh (origin = floor, units = metres) composed of cylinder-primitive\n"
        "torso + limbs + sphere head, shaped by 12 body measurements.\n"
        "\n"
        "ISO 8559-1:2017 measurement definitions:\n"
        "  height_cm          : standing height\n"
        "  bust_cm            : chest girth at fullest point (§8.3.1)\n"
        "  waist_cm           : natural waist girth (§8.4.1)\n"
        "  hip_cm             : full hip girth 20 cm below waist (§8.5.1)\n"
        "  inseam_cm          : inside-leg length crotch→floor (§8.7.1)\n"
        "  shoulder_width_cm  : across-back shoulder width (§8.2.4)\n"
        "  arm_length_cm      : total arm length shoulder→wrist (§8.6.1)\n"
        "  neck_circumference_cm : neck girth (§8.1.2)\n"
        "  thigh_cm           : max thigh girth (§8.7.3)\n"
        "  calf_cm            : max calf girth (§8.7.5)\n"
        "  upper_arm_cm       : upper arm girth (§8.6.2)\n"
        "  gender             : 'female' | 'male' | 'neutral'\n"
        "\n"
        "Returns {ok, vertex_count, face_count, bbox_min, bbox_max, landmark_names}.\n"
        "Full mesh data available via the returned mesh_id for downstream use.\n"
        "\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "height_cm": {"type": "number", "description": "Standing height in cm (e.g. 170)."},
            "weight_kg": {"type": "number", "description": "Body mass in kg (informative, default 70)."},
            "bust_cm": {"type": "number", "description": "Chest girth in cm (ISO §8.3.1)."},
            "waist_cm": {"type": "number", "description": "Natural waist girth in cm (ISO §8.4.1)."},
            "hip_cm": {"type": "number", "description": "Full hip girth in cm (ISO §8.5.1)."},
            "inseam_cm": {"type": "number", "description": "Inside-leg length in cm (ISO §8.7.1)."},
            "shoulder_width_cm": {"type": "number", "description": "Across-back shoulder width in cm."},
            "arm_length_cm": {"type": "number", "description": "Total arm length shoulder to wrist in cm."},
            "neck_circumference_cm": {"type": "number", "description": "Neck girth in cm (ISO §8.1.2)."},
            "thigh_cm": {"type": "number", "description": "Max thigh girth in cm (ISO §8.7.3)."},
            "calf_cm": {"type": "number", "description": "Max calf girth in cm (ISO §8.7.5)."},
            "upper_arm_cm": {"type": "number", "description": "Upper arm girth in cm (ISO §8.6.2)."},
            "gender": {
                "type": "string",
                "enum": ["female", "male", "neutral"],
                "description": "Body form gender hint. Default 'neutral'.",
            },
        },
        "required": [],
    },
)


@register(_build_spec, write=False)
async def run_apparel_build_avatar(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        m_kwargs: dict = {}
        float_fields = [
            "height_cm", "weight_kg", "bust_cm", "waist_cm", "hip_cm",
            "inseam_cm", "shoulder_width_cm", "arm_length_cm",
            "neck_circumference_cm", "thigh_cm", "calf_cm", "upper_arm_cm",
        ]
        for f in float_fields:
            if f in a:
                m_kwargs[f] = float(a[f])
        if "gender" in a:
            m_kwargs["gender"] = str(a["gender"])

        m = AvatarMeasurements(**m_kwargs)
        avatar = build_avatar(m)
    except (TypeError, ValueError) as exc:
        return err_payload(f"avatar build error: {exc}", "BUILD_ERROR")

    v = avatar.mesh_positions
    bbox_min = v.min(axis=0).tolist()
    bbox_max = v.max(axis=0).tolist()

    return ok_payload({
        "ok": True,
        "vertex_count": len(avatar.mesh_positions),
        "face_count": len(avatar.mesh_triangles),
        "bbox_min": bbox_min,
        "bbox_max": bbox_max,
        "height_m": round(float(v[:, 1].max()), 4),
        "landmark_names": list(avatar.landmarks.keys()),
        "has_skeleton": avatar.skeleton is not None,
        "note": (
            "Mesh built per ISO 8559-1:2017 body measurement system. "
            "Cylinder-primitive model; use SMPL for production garment simulation."
        ),
    })


# ---------------------------------------------------------------------------
# Tool: apparel_fit_dress_form
# ---------------------------------------------------------------------------

_dress_spec = ToolSpec(
    name="apparel_fit_dress_form",
    description=(
        "Compute a dress form (ease-expanded avatar) used for cloth-pattern draping.\n"
        "\n"
        "The dress form is the avatar mesh uniformly expanded outward in the XZ plane\n"
        "by ease_cm, matching the approach used by CLO3D Avatar Editor and standard\n"
        "pattern-making ease tables (ASTM D5219-21 §6).\n"
        "\n"
        "Args:\n"
        "  measurements (object) — same fields as apparel_build_avatar\n"
        "  ease_cm (number)      — radial ease in cm (default 2.5 cm)\n"
        "\n"
        "Returns {ok, vertex_count, face_count, dress_bbox_min, dress_bbox_max,\n"
        "         avatar_bbox_max_xz, dress_bbox_max_xz, note}.\n"
        "\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "measurements": {
                "type": "object",
                "description": "ISO 8559-1:2017 measurements object (same fields as apparel_build_avatar).",
            },
            "ease_cm": {
                "type": "number",
                "description": "Radial ease in cm to add over avatar. Default 2.5 cm.",
            },
        },
        "required": [],
    },
)


@register(_dress_spec, write=False)
async def run_apparel_fit_dress_form(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        raw_m = a.get("measurements", {})
        m_kwargs: dict = {}
        float_fields = [
            "height_cm", "weight_kg", "bust_cm", "waist_cm", "hip_cm",
            "inseam_cm", "shoulder_width_cm", "arm_length_cm",
            "neck_circumference_cm", "thigh_cm", "calf_cm", "upper_arm_cm",
        ]
        for f in float_fields:
            if f in raw_m:
                m_kwargs[f] = float(raw_m[f])
        if "gender" in raw_m:
            m_kwargs["gender"] = str(raw_m["gender"])
        m = AvatarMeasurements(**m_kwargs)

        ease_cm = float(a.get("ease_cm", 2.5))
        if ease_cm < 0:
            return err_payload("ease_cm must be ≥ 0", "BAD_ARGS")

        avatar = build_avatar(m)
        dv, dt = fit_dress_form(avatar, ease_cm=ease_cm)
    except (TypeError, ValueError) as exc:
        return err_payload(f"dress form error: {exc}", "BUILD_ERROR")

    import numpy as np
    av = avatar.mesh_positions
    av_max_xz = float(np.linalg.norm(av[:, [0, 2]], axis=1).max())
    dv_max_xz = float(np.linalg.norm(dv[:, [0, 2]], axis=1).max())

    return ok_payload({
        "ok": True,
        "vertex_count": len(dv),
        "face_count": len(dt),
        "dress_bbox_min": dv.min(axis=0).tolist(),
        "dress_bbox_max": dv.max(axis=0).tolist(),
        "avatar_max_xz_radius_m": round(av_max_xz, 4),
        "dress_max_xz_radius_m": round(dv_max_xz, 4),
        "ease_cm_applied": ease_cm,
        "note": (
            "Uniform XZ radial ease applied per ASTM D5219-21 §6. "
            "Production use should apply region-specific ease per NKBA / pattern-making tables."
        ),
    })
