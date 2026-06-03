"""
kerf_cad_core.animation.tools — Wave 9B LLM tool wrappers for animation/rigging.

Covers max3ds animation, Blender animation/rigging, max3ds skeletal dynamics.

Tools registered
----------------
  animation_evaluate_clip  — Evaluate an AnimClip at a given time; returns
                              all channel values.
  animation_solve_ik       — Run CCD or FABRIK IK solve on a bone chain;
                              returns per-bone rotation matrices.
  animation_apply_pose     — Apply joint rotations to an armature; returns
                              world-space bone matrices.

References
----------
McLaughlin (2001). Game Programming Gems Ch. 4.3.
Aristidou & Lasenby (2011). FABRIK. Graphical Models 73(5).
Wang & Chen (1991). CCD IK. IEEE Trans. Robotics 7(4).
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.animation.keyframe import AnimClip, FCurve, Keyframe
from kerf_cad_core.animation.armature import Bone, Skeleton, Armature
from kerf_cad_core.animation.ik_solver import IKChain, solve_ik_ccd, solve_ik_fabrik


# ---------------------------------------------------------------------------
# Tool: animation_evaluate_clip
# ---------------------------------------------------------------------------

_evaluate_clip_spec = ToolSpec(
    name="animation_evaluate_clip",
    description=(
        "Evaluate an AnimClip at a given time and return all channel values.\n"
        "\n"
        "Provide the clip as a JSON structure with:\n"
        "  name        — clip name\n"
        "  duration    — total duration in seconds\n"
        "  fcurves     — dict of channel_name → list of keyframe objects:\n"
        "                  {t, value, interpolation, tangent_in, tangent_out}\n"
        "  eval_time   — time in seconds to evaluate\n"
        "\n"
        "Returns: {ok: true, channels: {name: value, ...}}\n"
        "Errors: {ok: false, reason}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Clip name."},
            "duration": {"type": "number", "description": "Total duration (s)."},
            "fcurves": {
                "type": "object",
                "description": "Channel → keyframe list mapping.",
                "additionalProperties": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "t": {"type": "number"},
                            "value": {},
                            "interpolation": {"type": "string", "enum": ["step", "linear", "bezier"]},
                            "tangent_in": {"type": "array", "items": {"type": "number"}},
                            "tangent_out": {"type": "array", "items": {"type": "number"}},
                        },
                        "required": ["t", "value"],
                    },
                },
            },
            "eval_time": {"type": "number", "description": "Time to evaluate (s)."},
        },
        "required": ["name", "duration", "fcurves", "eval_time"],
    },
)


@register(_evaluate_clip_spec, write=False)
async def run_animation_evaluate_clip(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        clip_name = str(a.get("name", "clip"))
        duration = float(a["duration"])
        eval_time = float(a["eval_time"])
        raw_fcurves = a.get("fcurves", {})
    except Exception as exc:
        return err_payload(f"missing/invalid fields: {exc}", "BAD_ARGS")

    try:
        fcurves: dict = {}
        for ch, kf_list in raw_fcurves.items():
            keys = []
            for kd in kf_list:
                tin = tuple(kd["tangent_in"]) if kd.get("tangent_in") else None
                tout = tuple(kd["tangent_out"]) if kd.get("tangent_out") else None
                val = kd["value"]
                if isinstance(val, list):
                    val = np.array(val, dtype=float)
                else:
                    val = float(val)
                keys.append(Keyframe(
                    t=float(kd["t"]),
                    value=val,
                    interpolation=str(kd.get("interpolation", "bezier")),
                    tangent_in=tin,
                    tangent_out=tout,
                ))
            fcurves[ch] = FCurve(keyframes=keys)

        clip = AnimClip(name=clip_name, duration=duration, fcurves=fcurves)
        result = clip.evaluate(eval_time)
    except Exception as exc:
        return err_payload(f"evaluation error: {exc}", "EVAL_ERROR")

    channels: dict[str, Any] = {}
    for ch, val in result.items():
        if isinstance(val, np.ndarray):
            channels[ch] = val.tolist()
        else:
            channels[ch] = float(val)

    return ok_payload({"channels": channels, "eval_time": eval_time})


# ---------------------------------------------------------------------------
# Tool: animation_solve_ik
# ---------------------------------------------------------------------------

_solve_ik_spec = ToolSpec(
    name="animation_solve_ik",
    description=(
        "Solve inverse kinematics for a bone chain using CCD or FABRIK.\n"
        "\n"
        "Provide:\n"
        "  bones       — list of bone descriptions [{name, head[3], tail[3], parent}]\n"
        "  chain       — list of bone names in order (root → end-effector)\n"
        "  target      — [x, y, z] world-space target for end-effector\n"
        "  algorithm   — 'ccd' or 'fabrik' (default: 'fabrik')\n"
        "  max_iter    — maximum iterations (default: 30)\n"
        "  tol         — convergence tolerance (default: 1e-4)\n"
        "  pole_target — optional [x, y, z] to constrain bend plane\n"
        "\n"
        "Returns: {ok: true, rotations: {bone_name: [[row0], [row1], [row2]], ...}}\n"
        "Errors: {ok: false, reason}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bones": {
                "type": "array",
                "description": "Bone definitions.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "head": {"type": "array", "items": {"type": "number"}},
                        "tail": {"type": "array", "items": {"type": "number"}},
                        "parent": {"type": ["string", "null"]},
                    },
                    "required": ["name", "head", "tail"],
                },
            },
            "chain": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered bone names (root → end-effector).",
            },
            "target": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Target world position [x, y, z].",
            },
            "algorithm": {"type": "string", "enum": ["ccd", "fabrik"]},
            "max_iter": {"type": "integer", "description": "Max iterations."},
            "tol": {"type": "number", "description": "Convergence tolerance."},
            "pole_target": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Optional pole target [x, y, z].",
            },
        },
        "required": ["bones", "chain", "target"],
    },
)


@register(_solve_ik_spec, write=False)
async def run_animation_solve_ik(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        skeleton = Skeleton()
        for bd in a["bones"]:
            b = Bone(
                name=str(bd["name"]),
                head=np.array(bd["head"], dtype=float),
                tail=np.array(bd["tail"], dtype=float),
                parent=bd.get("parent"),
            )
            skeleton.add_bone(b)

        chain_names = [str(x) for x in a["chain"]]
        target = np.array(a["target"], dtype=float)
        algorithm = str(a.get("algorithm", "fabrik")).lower()
        max_iter = int(a.get("max_iter", 30))
        tol = float(a.get("tol", 1e-4))
        pole_raw = a.get("pole_target")
        pole = np.array(pole_raw, dtype=float) if pole_raw is not None else None
    except Exception as exc:
        return err_payload(f"bad input: {exc}", "BAD_ARGS")

    try:
        ik = IKChain(bones=chain_names, target=target, pole_target=pole)
        if algorithm == "ccd":
            rotations = solve_ik_ccd(ik, skeleton, max_iter=max_iter, tol=tol)
        else:
            rotations = solve_ik_fabrik(ik, skeleton, max_iter=max_iter, tol=tol)
    except Exception as exc:
        return err_payload(f"IK solve error: {exc}", "EVAL_ERROR")

    rot_out = {name: r.tolist() for name, r in rotations.items()}
    return ok_payload({"rotations": rot_out, "algorithm": algorithm})


# ---------------------------------------------------------------------------
# Tool: animation_apply_pose
# ---------------------------------------------------------------------------

_apply_pose_spec = ToolSpec(
    name="animation_apply_pose",
    description=(
        "Apply joint rotation matrices to an armature and return world-space\n"
        "bone transform matrices.\n"
        "\n"
        "Provide:\n"
        "  bones      — bone definitions [{name, head[3], tail[3], parent}]\n"
        "  rotations  — {bone_name: [[r00,r01,r02],[r10,...],[r20,...]]} 3×3 mats\n"
        "\n"
        "Returns: {ok: true, world_matrices: [[...4x4...], ...]}\n"
        "         in skeleton.ordered_bones() order.\n"
        "Errors: {ok: false, reason}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "head": {"type": "array", "items": {"type": "number"}},
                        "tail": {"type": "array", "items": {"type": "number"}},
                        "parent": {"type": ["string", "null"]},
                    },
                    "required": ["name", "head", "tail"],
                },
            },
            "rotations": {
                "type": "object",
                "description": "bone_name → 3×3 rotation matrix.",
            },
        },
        "required": ["bones", "rotations"],
    },
)


@register(_apply_pose_spec, write=False)
async def run_animation_apply_pose(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        skeleton = Skeleton()
        for bd in a["bones"]:
            b = Bone(
                name=str(bd["name"]),
                head=np.array(bd["head"], dtype=float),
                tail=np.array(bd["tail"], dtype=float),
                parent=bd.get("parent"),
            )
            skeleton.add_bone(b)

        joint_rotations = {}
        for bname, raw_rot in a.get("rotations", {}).items():
            joint_rotations[str(bname)] = np.array(raw_rot, dtype=float)
    except Exception as exc:
        return err_payload(f"bad input: {exc}", "BAD_ARGS")

    try:
        arm = Armature(skeleton=skeleton)
        world_mats = arm.apply_pose(joint_rotations)
    except Exception as exc:
        return err_payload(f"pose error: {exc}", "EVAL_ERROR")

    return ok_payload({
        "world_matrices": [m.tolist() for m in world_mats],
        "bone_order": skeleton.ordered_bones(),
    })


__all__ = [
    "run_animation_evaluate_clip",
    "run_animation_solve_ik",
    "run_animation_apply_pose",
]
