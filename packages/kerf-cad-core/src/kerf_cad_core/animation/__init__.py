"""kerf_cad_core.animation — Skeletal animation, keyframe FCurves, IK solvers.

Wave 9B: animation + skeletal rig

Covers max3ds animation, Blender animation/rigging, max3ds skeletal dynamics.

Public API
----------
Keyframe / FCurve / AnimClip:
    from kerf_cad_core.animation.keyframe import Keyframe, FCurve, AnimClip

Armature / Skeleton / Bone:
    from kerf_cad_core.animation.armature import Bone, Skeleton, Armature
    from kerf_cad_core.animation.armature import evaluate_armature_at_time
    from kerf_cad_core.animation.armature import linear_blend_skinning

IK solvers:
    from kerf_cad_core.animation.ik_solver import IKChain, solve_ik_ccd, solve_ik_fabrik

References
----------
McLaughlin (2001). Game Programming Gems Ch. 4.3 — bezier keyframe interpolation.
Aristidou & Lasenby (2011). FABRIK. Graphical Models 73(5):243-260.
Wang & Chen (1991). CCD IK. IEEE Trans. Robotics 7(4):489-499.
Lewis et al. (2000). Pose Space Deformation. SIGGRAPH.
"""
from kerf_cad_core.animation.keyframe import Keyframe, FCurve, AnimClip
from kerf_cad_core.animation.armature import (
    Bone,
    Skeleton,
    Armature,
    evaluate_armature_at_time,
    linear_blend_skinning,
)
from kerf_cad_core.animation.ik_solver import IKChain, solve_ik_ccd, solve_ik_fabrik

__all__ = [
    # keyframe
    "Keyframe",
    "FCurve",
    "AnimClip",
    # armature
    "Bone",
    "Skeleton",
    "Armature",
    "evaluate_armature_at_time",
    "linear_blend_skinning",
    # ik_solver
    "IKChain",
    "solve_ik_ccd",
    "solve_ik_fabrik",
]
