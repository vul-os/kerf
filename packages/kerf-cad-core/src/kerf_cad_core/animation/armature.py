"""
kerf_cad_core.animation.armature — Skeletal armature and pose evaluation.

Covers Blender-style armature rigging and max3ds skeletal dynamics.

Architecture
------------
Bone / Skeleton are defined here (sculpt.character_rigging does not exist in
this codebase).  The design mirrors Blender's bone system:

  - Each Bone has a local head/tail in its parent's space.
  - The rest-pose matrix (bind matrix) is the bone's transform when no pose
    is applied.
  - Pose rotations are 3×3 rotation matrices applied in local space before
    cascading down the hierarchy.
  - World-space bone matrix = parent_world @ local_rest @ pose_rot

Skinning
--------
linear_blend_skinning() performs LBS vertex deformation given world matrices
and per-vertex bone weights — compatible with the sculpt module concept.

References
----------
Lewis, J.P., Cordner, M., Fong, N. (2000). "Pose Space Deformation: A Unified
    Approach to Shape Interpolation and Skeleton-Driven Deformation."
    SIGGRAPH Proc. pp. 165-172.
Magnenat-Thalmann, N. & Thalmann, D. (1988). "Joint-dependent local deformations
    for hand animation and object grasping." Proc. Graphics Interface '88.
    (Original LBS formulation.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, List

import numpy as np


# ---------------------------------------------------------------------------
# Bone
# ---------------------------------------------------------------------------

@dataclass
class Bone:
    """A single bone in a skeleton hierarchy.

    Attributes
    ----------
    name : str
        Unique bone identifier.
    head : np.ndarray, shape (3,)
        Head position in parent bone's local frame (or world if root).
    tail : np.ndarray, shape (3,)
        Tail position in parent bone's local frame.
    parent : str | None
        Name of the parent bone, or None for a root bone.
    length : float
        Bone length (computed from head-tail distance).
    """
    name: str
    head: np.ndarray       # (3,) in parent local space
    tail: np.ndarray       # (3,) in parent local space
    parent: Optional[str] = None

    def __post_init__(self):
        self.head = np.asarray(self.head, dtype=float)
        self.tail = np.asarray(self.tail, dtype=float)

    @property
    def length(self) -> float:
        """Bone length (Euclidean distance head→tail)."""
        return float(np.linalg.norm(self.tail - self.head))

    @property
    def direction(self) -> np.ndarray:
        """Unit vector from head to tail in local space."""
        d = self.tail - self.head
        n = np.linalg.norm(d)
        if n < 1e-12:
            return np.array([0.0, 1.0, 0.0])
        return d / n


# ---------------------------------------------------------------------------
# Skeleton
# ---------------------------------------------------------------------------

@dataclass
class Skeleton:
    """A collection of named bones forming an articulated hierarchy.

    Attributes
    ----------
    bones : dict[str, Bone]
        All bones keyed by name.
    root_names : list[str]
        Names of root bones (those with parent=None).
    """
    bones: Dict[str, Bone] = field(default_factory=dict)

    def __post_init__(self):
        pass

    @property
    def root_names(self) -> List[str]:
        """Return names of all root bones (no parent)."""
        return [name for name, b in self.bones.items() if b.parent is None]

    def add_bone(self, bone: Bone) -> None:
        """Add a bone to the skeleton."""
        self.bones[bone.name] = bone

    def children_of(self, name: str) -> List[str]:
        """Return the direct children of bone `name`."""
        return [n for n, b in self.bones.items() if b.parent == name]

    def ordered_bones(self) -> List[str]:
        """Return bone names in breadth-first order from roots."""
        from collections import deque
        order: List[str] = []
        queue: deque[str] = deque(self.root_names)
        while queue:
            n = queue.popleft()
            order.append(n)
            queue.extend(self.children_of(n))
        return order


# ---------------------------------------------------------------------------
# Armature
# ---------------------------------------------------------------------------

def _rot3_to_mat4(r: np.ndarray) -> np.ndarray:
    """Embed a (3,3) rotation into a (4,4) homogeneous matrix."""
    m = np.eye(4, dtype=float)
    m[:3, :3] = r
    return m


def _translation_mat4(t: np.ndarray) -> np.ndarray:
    """Build a (4,4) translation matrix from a (3,) vector."""
    m = np.eye(4, dtype=float)
    m[:3, 3] = t
    return m


@dataclass
class Armature:
    """A posed armature — wraps a Skeleton with a pose evaluation mechanism.

    The rest-pose world matrix of each bone is computed by cascading
    head translations through the hierarchy.  A pose rotation is then
    applied in local space per bone.

    Attributes
    ----------
    skeleton : Skeleton
        The underlying Skeleton.
    """
    skeleton: Skeleton

    def _rest_world_matrices(self) -> Dict[str, np.ndarray]:
        """Compute 4×4 world-space rest matrices for every bone.

        Algorithm
        ---------
        Process bones in breadth-first order.  Each bone's rest matrix is:
            M_world = M_parent_world @ T(bone.head)
        where T(v) is a translation matrix by vector v.
        Root bones use T(bone.head) directly (parent is identity).
        """
        rest: Dict[str, np.ndarray] = {}
        for name in self.skeleton.ordered_bones():
            bone = self.skeleton.bones[name]
            local_t = _translation_mat4(bone.head)
            if bone.parent is None or bone.parent not in rest:
                rest[name] = local_t
            else:
                rest[name] = rest[bone.parent] @ local_t
        return rest

    def apply_pose(
        self,
        joint_rotations: Dict[str, np.ndarray],
    ) -> List[np.ndarray]:
        """Apply pose rotations and return world-space 4×4 bone matrices.

        Each bone's posed world matrix is computed as:
            M_world = M_parent_world_posed @ T(bone.head) @ R(pose_rot)

        where R is the pose rotation (3×3 → embedded in 4×4).

        Parameters
        ----------
        joint_rotations : dict[str, np.ndarray]
            Per-bone 3×3 rotation matrices.  Missing bones use identity.

        Returns
        -------
        list[np.ndarray]
            4×4 world-space matrices in the same order as
            skeleton.ordered_bones().

        References
        ----------
        Lewis et al. (2000), §3 — cascading bone transforms.
        """
        posed: Dict[str, np.ndarray] = {}
        result: List[np.ndarray] = []

        for name in self.skeleton.ordered_bones():
            bone = self.skeleton.bones[name]
            local_t = _translation_mat4(bone.head)

            rot3 = joint_rotations.get(name, np.eye(3, dtype=float))
            rot4 = _rot3_to_mat4(rot3)

            if bone.parent is None or bone.parent not in posed:
                posed[name] = local_t @ rot4
            else:
                posed[name] = posed[bone.parent] @ local_t @ rot4
            result.append(posed[name])

        return result


# ---------------------------------------------------------------------------
# Animated armature evaluation
# ---------------------------------------------------------------------------

def evaluate_armature_at_time(
    armature: Armature,
    clip: "kerf_cad_core.animation.keyframe.AnimClip",
    t: float,
) -> List[np.ndarray]:
    """Sample clip FCurves at t; apply_pose; return world bone matrices.

    Channel naming convention (following Blender/max3ds):
        '<bone_name>.rx', '<bone_name>.ry', '<bone_name>.rz'
    where .rx/.ry/.rz are Euler angles (radians) for each axis.
    The rotation matrix is built as Rz @ Ry @ Rx (extrinsic XYZ).

    If a bone has no channels in the clip, identity rotation is used.

    Parameters
    ----------
    armature : Armature
    clip : AnimClip
    t : float
        Evaluation time in seconds.

    Returns
    -------
    list[np.ndarray]
        4×4 world matrices in skeleton.ordered_bones() order.
    """
    channel_values = clip.evaluate(t)

    joint_rotations: Dict[str, np.ndarray] = {}
    for bone_name in armature.skeleton.bones:
        rx = float(channel_values.get(f"{bone_name}.rx", 0.0))
        ry = float(channel_values.get(f"{bone_name}.ry", 0.0))
        rz = float(channel_values.get(f"{bone_name}.rz", 0.0))

        # Build 3×3 rotation matrix: R = Rz @ Ry @ Rx (extrinsic XYZ Euler)
        cx, sx = np.cos(rx), np.sin(rx)
        cy, sy = np.cos(ry), np.sin(ry)
        cz, sz = np.cos(rz), np.sin(rz)

        Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
        Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)

        joint_rotations[bone_name] = Rz @ Ry @ Rx

    return armature.apply_pose(joint_rotations)


def linear_blend_skinning(
    vertices: np.ndarray,
    skin_indices: np.ndarray,
    skin_weights: np.ndarray,
    world_matrices: List[np.ndarray],
    bone_order: List[str],
) -> np.ndarray:
    """Linear Blend Skinning (LBS) vertex deformation.

    Deforms vertices using a weighted blend of bone world transforms.

    Parameters
    ----------
    vertices : np.ndarray, shape (N, 3)
        Rest-pose vertex positions.
    skin_indices : np.ndarray, shape (N, K)
        Bone index (into bone_order) for each weight.
    skin_weights : np.ndarray, shape (N, K)
        Per-vertex, per-bone influence weights (should sum to 1).
    world_matrices : list[np.ndarray]
        4×4 posed world matrices from apply_pose(), indexed by bone_order.
    bone_order : list[str]
        Bone name order (matches world_matrices list).

    Returns
    -------
    np.ndarray, shape (N, 3)
        Deformed vertex positions.

    References
    ----------
    Magnenat-Thalmann & Thalmann (1988) — original LBS.
    Lewis et al. (2000), §2 — standard formulation.
    """
    N = vertices.shape[0]
    out = np.zeros((N, 3), dtype=float)

    for v_idx in range(N):
        total_weight = 0.0
        accum = np.zeros(3, dtype=float)
        for k in range(skin_indices.shape[1]):
            b_idx = int(skin_indices[v_idx, k])
            w = float(skin_weights[v_idx, k])
            if w <= 0.0:
                continue
            M = world_matrices[b_idx]
            # Apply 4×4 transform to homogeneous point
            p = np.array([*vertices[v_idx], 1.0], dtype=float)
            tp = M @ p
            accum += w * tp[:3]
            total_weight += w

        if total_weight > 1e-12:
            out[v_idx] = accum / total_weight
        else:
            out[v_idx] = vertices[v_idx]

    return out


__all__ = [
    "Bone",
    "Skeleton",
    "Armature",
    "evaluate_armature_at_time",
    "linear_blend_skinning",
]
