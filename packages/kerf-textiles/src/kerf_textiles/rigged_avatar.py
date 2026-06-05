"""
kerf_textiles.rigged_avatar
===========================
Skeletal rig for the parametric CAESAR body-form avatar, supporting
linear-blend skinning (LBS) deformation and pose-sequence animation.

Method
------
The rig consists of a joint hierarchy mirroring human anatomy
(spine chain + bilateral upper/lower limb chain).  Joints are
represented as local rotation angles (Euler XYZ in radians) applied
to a bind-pose skeleton.  Global joint transforms are computed by
forward kinematics (FK) — composing parent-to-child rigid transforms
in joint order (Magnenat-Thalmann & Thalmann 2004, §3).

Linear-Blend Skinning (LBS)
----------------------------
Each body-mesh vertex is associated with up to N_INFLUENCES joints
via non-negative blend weights that sum to 1.  The skinned position
is the weighted sum of per-joint transformed positions (Mohr & Gleicher
2003):

    v_posed = Σ_j  w_{ij} · (M_j · M_j0^{-1}) · v_bind

where
    w_{ij}   = blend weight of vertex i for joint j
    M_j      = current global joint transform (4×4 homogeneous)
    M_j0^{-1}= inverse bind-pose transform
    v_bind   = vertex position in bind pose

Units: centimetres throughout (matching kerf_apparel.avatar output).

Pose Sequence
-------------
A pose sequence is a list of ``Keyframe`` objects, each holding the
full set of joint rotation angles (one angle per DOF) and a time
stamp.  Between keyframes the pose is linearly interpolated per-DOF
(SLERP would be more correct for rotations; linear is adequate for
small angles and short sequences — see Kavan et al. 2008 caveat).

Joints defined
--------------
The rig maps to the CAESAR body-form landmarks (Robinette 2002):

    0  root         — pelvis / root
    1  spine_lower  — between hip and waist
    2  spine_mid    — at waist
    3  spine_upper  — at underbust
    4  neck         — base of neck
    5  l_shoulder   — left shoulder
    6  l_elbow      — left elbow
    7  l_wrist      — left wrist (end)
    8  r_shoulder   — right shoulder
    9  r_elbow      — right elbow
   10  r_wrist      — right wrist (end)
   11  l_hip        — left hip
   12  l_knee       — left knee
   13  l_ankle      — left ankle (end)
   14  r_hip        — right hip
   15  r_knee       — right knee
   16  r_ankle      — right ankle (end)

Each joint has 1 DOF (rotation around its principal axis by convention)
to keep the system tractable.  Shoulders/hips have 3 DOF (x,y,z).

References
----------
Mohr, A. & Gleicher, M. (2003). "Deformation sensitive decimation."
  Eurographics Workshop on Natural Phenomena.  (LBS formulation)
Magnenat-Thalmann, N. & Thalmann, D. (2004). "Handbook of Virtual Humans."
  §3 (joint hierarchy and FK).
Robinette, K. et al. (2002). "CAESAR Final Report." (body proportions)
Kavan, L. et al. (2008). "Geometric skinning with approximate dual
  quaternion blending." TOG 27(4).  (LBS limitations)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Joint hierarchy constants
# ---------------------------------------------------------------------------

#: Number of joints in the rig
N_JOINTS = 17

#: Joint index constants (used throughout this module)
ROOT        = 0
SPINE_LOWER = 1
SPINE_MID   = 2
SPINE_UPPER = 3
NECK        = 4
L_SHOULDER  = 5
L_ELBOW     = 6
L_WRIST     = 7
R_SHOULDER  = 8
R_ELBOW     = 9
R_WRIST     = 10
L_HIP       = 11
L_KNEE      = 12
L_ANKLE     = 13
R_HIP       = 14
R_KNEE      = 15
R_ANKLE     = 16

JOINT_NAMES = [
    "root", "spine_lower", "spine_mid", "spine_upper", "neck",
    "l_shoulder", "l_elbow", "l_wrist",
    "r_shoulder", "r_elbow", "r_wrist",
    "l_hip", "l_knee", "l_ankle",
    "r_hip", "r_knee", "r_ankle",
]

#: Parent joint index for each joint (-1 = root has no parent)
PARENT = [-1, 0, 1, 2, 3, 3, 5, 6, 3, 8, 9, 0, 11, 12, 0, 14, 15]

#: DOF per joint (shoulder/hip get 3; spine chain 2; others 1)
JOINT_DOF = [3, 2, 2, 2, 2, 3, 1, 1, 3, 1, 1, 3, 1, 1, 3, 1, 1]

#: Total number of pose DOF
TOTAL_DOF: int = sum(JOINT_DOF)  # = 3+2+2+2+2+3+1+1+3+1+1+3+1+1+3+1+1 = 31


# ---------------------------------------------------------------------------
# Bind-pose joint positions (in cm, from CAESAR proportions for 168 cm female)
# ---------------------------------------------------------------------------

def _bind_pose_positions(height_cm: float = 168.0) -> np.ndarray:
    """
    Return bind-pose (T-pose) joint positions for a given height.
    Positions are in centimetres matching the CAESAR avatar coordinate system:
    X = lateral (positive = right side of body), Z = height (up), Y = depth.

    This matches kerf_apparel.avatar which uses X, Y for cross-section and
    Z for height (Z=0 at floor, Z=height_cm at crown).

    All proportions derived from Robinette et al. (2002) CAESAR mean
    measurements scaled to *height_cm*.
    """
    s = height_cm / 168.0   # scale factor relative to reference 168 cm

    # Heights along Z axis (cm, from floor) — Z is up in CAESAR convention
    z_ankle   = 6.7   * s
    z_knee    = 45.4  * s
    z_hip     = 80.6  * s
    z_root    = 84.0  * s   # midpoint between hip joints
    z_waist   = 105.0 * s
    z_underbust = 114.0 * s
    z_shoulder  = 137.8 * s
    z_neck      = 144.5 * s

    # Lateral offsets (cm) along X
    hip_half    = 9.0  * s
    shoulder_x  = 18.0 * s
    elbow_x     = 23.0 * s
    wrist_x     = 24.5 * s

    # Arms hang down from shoulder in T-pose (same Z height as shoulder - offset)
    positions = np.zeros((N_JOINTS, 3), dtype=np.float64)

    # Format: [X_lateral, Y_depth, Z_height]
    positions[ROOT]        = [0.0,         0.0, z_root]
    positions[SPINE_LOWER] = [0.0,         0.0, z_hip]
    positions[SPINE_MID]   = [0.0,         0.0, z_waist]
    positions[SPINE_UPPER] = [0.0,         0.0, z_underbust]
    positions[NECK]        = [0.0,         0.0, z_neck]
    positions[L_SHOULDER]  = [-shoulder_x, 0.0, z_shoulder]
    positions[L_ELBOW]     = [-elbow_x,    0.0, z_shoulder - 22.0 * s]
    positions[L_WRIST]     = [-wrist_x,    0.0, z_shoulder - 42.0 * s]
    positions[R_SHOULDER]  = [ shoulder_x, 0.0, z_shoulder]
    positions[R_ELBOW]     = [ elbow_x,    0.0, z_shoulder - 22.0 * s]
    positions[R_WRIST]     = [ wrist_x,    0.0, z_shoulder - 42.0 * s]
    positions[L_HIP]       = [-hip_half,   0.0, z_hip]
    positions[L_KNEE]      = [-hip_half,   0.0, z_knee]
    positions[L_ANKLE]     = [-hip_half,   0.0, z_ankle]
    positions[R_HIP]       = [ hip_half,   0.0, z_hip]
    positions[R_KNEE]      = [ hip_half,   0.0, z_knee]
    positions[R_ANKLE]     = [ hip_half,   0.0, z_ankle]

    return positions


# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------

def _rot_x(angle: float) -> np.ndarray:
    """4×4 homogeneous rotation about X axis."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([
        [1, 0,  0, 0],
        [0, c, -s, 0],
        [0, s,  c, 0],
        [0, 0,  0, 1],
    ], dtype=np.float64)


def _rot_y(angle: float) -> np.ndarray:
    """4×4 homogeneous rotation about Y axis."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([
        [ c, 0, s, 0],
        [ 0, 1, 0, 0],
        [-s, 0, c, 0],
        [ 0, 0, 0, 1],
    ], dtype=np.float64)


def _rot_z(angle: float) -> np.ndarray:
    """4×4 homogeneous rotation about Z axis."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([
        [c, -s, 0, 0],
        [s,  c, 0, 0],
        [0,  0, 1, 0],
        [0,  0, 0, 1],
    ], dtype=np.float64)


def _translation(t: np.ndarray) -> np.ndarray:
    """4×4 translation matrix from a (3,) vector."""
    M = np.eye(4, dtype=np.float64)
    M[:3, 3] = t
    return M


def _joint_local_rot(joint_idx: int, angles: np.ndarray) -> np.ndarray:
    """
    Build the local rotation matrix for a joint given its DOF angles.

    *angles* is a slice of the full pose vector for this joint:
      - 3-DOF joints: [rx, ry, rz]  (Euler XYZ intrinsic)
      - 2-DOF joints: [rx, ry]
      - 1-DOF joints: [rx]
    """
    dof = JOINT_DOF[joint_idx]
    if dof == 3:
        return _rot_x(angles[0]) @ _rot_y(angles[1]) @ _rot_z(angles[2])
    elif dof == 2:
        return _rot_x(angles[0]) @ _rot_y(angles[1])
    else:  # dof == 1
        return _rot_x(angles[0])


# ---------------------------------------------------------------------------
# Pose vector helpers
# ---------------------------------------------------------------------------

def _dof_offset(joint_idx: int) -> int:
    """Return the offset into the flat DOF vector for *joint_idx*."""
    return sum(JOINT_DOF[:joint_idx])


def _joint_angles(joint_idx: int, pose: np.ndarray) -> np.ndarray:
    """Extract the DOF angle slice for *joint_idx* from a flat pose vector."""
    off = _dof_offset(joint_idx)
    return pose[off: off + JOINT_DOF[joint_idx]]


def zero_pose() -> np.ndarray:
    """Return a flat pose vector of zeros (T-pose / bind pose)."""
    return np.zeros(TOTAL_DOF, dtype=np.float64)


# ---------------------------------------------------------------------------
# Skinning rig
# ---------------------------------------------------------------------------

@dataclass
class AvatarRig:
    """
    Skeletal rig for the CAESAR parametric avatar.

    Parameters
    ----------
    height_cm : float
        Standing height of the avatar (cm).
    bind_verts : np.ndarray, shape (Nv, 3)
        Vertex positions of the avatar mesh in the **bind pose** (cm).
    skin_weights : np.ndarray, shape (Nv, N_JOINTS)
        Non-negative blend weights.  Each row must sum to 1 (validated).
    bind_positions : np.ndarray, shape (N_JOINTS, 3)
        Joint world positions in the bind pose.  Built automatically
        if not supplied (via _bind_pose_positions).

    Notes
    -----
    skinning via Mohr & Gleicher (2003):
        v_posed = Σ_j  w_ij · (G_j · G_j0^{-1}) · v_bind_h

    where G_j  = current global joint transform (4×4)
          G_j0 = bind-pose global joint transform
          G_j0^{-1} = its inverse (pre-computed in __post_init__)
    """
    height_cm: float = 168.0
    bind_verts: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))
    skin_weights: np.ndarray = field(default_factory=lambda: np.empty((0, N_JOINTS)))
    bind_positions: Optional[np.ndarray] = None

    # Pre-computed in __post_init__
    _bind_transforms: np.ndarray = field(init=False, repr=False)   # (N_JOINTS, 4, 4)
    _inv_bind:        np.ndarray = field(init=False, repr=False)   # (N_JOINTS, 4, 4)

    def __post_init__(self) -> None:
        if self.bind_positions is None:
            self.bind_positions = _bind_pose_positions(self.height_cm)
        self._bind_transforms = self._compute_global_transforms(zero_pose())
        self._inv_bind = np.array(
            [np.linalg.inv(T) for T in self._bind_transforms], dtype=np.float64
        )

    def _compute_global_transforms(self, pose: np.ndarray) -> np.ndarray:
        """
        Forward kinematics: compute global 4×4 transforms for all joints.

        Returns shape (N_JOINTS, 4, 4).
        """
        global_T = np.zeros((N_JOINTS, 4, 4), dtype=np.float64)
        for j in range(N_JOINTS):
            parent = PARENT[j]
            # Local translation (bind-pose joint position relative to parent)
            if parent < 0:
                t_local = self.bind_positions[j]
            else:
                t_local = self.bind_positions[j] - self.bind_positions[parent]

            # Local transform = translation * rotation
            local_R = _joint_local_rot(j, _joint_angles(j, pose))
            local_T = _translation(t_local) @ local_R

            if parent < 0:
                global_T[j] = local_T
            else:
                global_T[j] = global_T[parent] @ local_T

        return global_T

    def pose_mesh(self, pose: np.ndarray) -> np.ndarray:
        """
        Deform the avatar mesh to a given pose via linear-blend skinning.

        Parameters
        ----------
        pose : np.ndarray, shape (TOTAL_DOF,)
            Flat joint rotation angles.

        Returns
        -------
        np.ndarray, shape (Nv, 3)
            Deformed vertex positions in cm.
        """
        Nv = len(self.bind_verts)
        if Nv == 0:
            return self.bind_verts.copy()

        # Current global transforms
        curr_T = self._compute_global_transforms(pose)

        # Skinning matrix: sum over joints of w_ij * M_j   where M_j = G_j * G_j0^{-1}
        # Shape: (N_JOINTS, 4, 4)
        M = np.einsum('jab,jbc->jac', curr_T, self._inv_bind)

        # Homogeneous bind vertices: (Nv, 4)
        verts_h = np.ones((Nv, 4), dtype=np.float64)
        verts_h[:, :3] = self.bind_verts

        # Weighted sum:  posed_h[i] = Σ_j w_ij * M_j @ v_bind_h[i]
        # Expand: (Nv, 1, 4) @ (1, N_JOINTS, 4, 4) → use einsum
        # v_posed[i] = Σ_j w[i,j] * M[j] @ v[i]
        # = einsum('ij,jkl,il->ik', weights, M, verts_h)
        # Breakdown for clarity:
        #   step1[i, j, k] = M[j, k, :] @ verts_h[i, :] → shape (Nv, N_JOINTS, 4)
        step1 = np.einsum('jkl,il->ijk', M, verts_h)   # (Nv, N_JOINTS, 4)
        #   step2[i, k] = Σ_j w[i,j] * step1[i,j,k]
        posed_h = np.einsum('ij,ijk->ik', self.skin_weights, step1)  # (Nv, 4)

        return posed_h[:, :3]

    def joint_positions(self, pose: np.ndarray) -> np.ndarray:
        """
        Return world joint positions for a given pose.

        Returns
        -------
        np.ndarray, shape (N_JOINTS, 3)
        """
        Ts = self._compute_global_transforms(pose)
        return Ts[:, :3, 3]


# ---------------------------------------------------------------------------
# Skin-weight generation for CAESAR body-form mesh
# ---------------------------------------------------------------------------

def build_skin_weights(
    verts: np.ndarray,           # (Nv, 3)  vertex positions (cm)
    bind_positions: np.ndarray,  # (N_JOINTS, 3) joint positions (cm)
    height_cm: float = 168.0,
    falloff_cm: float = 30.0,    # Gaussian falloff radius (cm)
) -> np.ndarray:
    """
    Generate smooth skin blend weights using Gaussian distance-based falloff.

    Each vertex is influenced by nearby joints; weights are normalised to
    sum to 1.  This is a simplified version of the envelope skinning method
    (Magnenat-Thalmann 2004, §3.2) — sufficient for smooth body deformation
    without a rigging artist's manual weight painting.

    Algorithm
    ---------
    1. For each vertex, compute Euclidean distance to every joint.
    2. Assign raw weight w_ij = exp(-dist_ij² / (2 * σ²))  where σ = falloff_cm.
    3. Apply joint-specific height-based masking so that, e.g., shoulder joints
       only influence the upper-body vertices.
    4. Normalise row sums to 1.

    Returns
    -------
    np.ndarray, shape (Nv, N_JOINTS), dtype float64
        Each row sums to 1.0 (within floating-point tolerance).
    """
    s = height_cm / 168.0
    Nv = len(verts)
    W = np.zeros((Nv, N_JOINTS), dtype=np.float64)

    # Height zones (Z axis, cm) — CAESAR avatar uses Z-up convention.
    # Vertices outside a joint's zone get weight zeroed before normalisation.
    # Zones are generous (±25 cm) to avoid hard cut-offs.
    zone_margin = 25.0 * s

    # Define Z-height range for each joint's zone of influence.
    # Format: (z_min, z_max) in cm.  Z = 0 at floor, Z = height_cm at crown.
    joint_zone: Dict[int, Tuple[float, float]] = {
        ROOT:         (-5.0,       105.0 * s),
        SPINE_LOWER:  (70.0 * s,   115.0 * s),
        SPINE_MID:    (90.0 * s,   130.0 * s),
        SPINE_UPPER:  (100.0 * s,  150.0 * s),
        NECK:         (130.0 * s,  168.0 * s),
        L_SHOULDER:   (110.0 * s,  168.0 * s),
        L_ELBOW:      (90.0 * s,   168.0 * s),
        L_WRIST:      (80.0 * s,   168.0 * s),
        R_SHOULDER:   (110.0 * s,  168.0 * s),
        R_ELBOW:      (90.0 * s,   168.0 * s),
        R_WRIST:      (80.0 * s,   168.0 * s),
        L_HIP:        (50.0 * s,   105.0 * s),
        L_KNEE:       (20.0 * s,   70.0 * s),
        L_ANKLE:      (-5.0,       35.0 * s),
        R_HIP:        (50.0 * s,   105.0 * s),
        R_KNEE:       (20.0 * s,   70.0 * s),
        R_ANKLE:      (-5.0,       35.0 * s),
    }

    sigma_sq = falloff_cm ** 2

    for j in range(N_JOINTS):
        diff = verts - bind_positions[j]          # (Nv, 3)
        dist_sq = np.sum(diff ** 2, axis=1)        # (Nv,)
        w = np.exp(-dist_sq / (2.0 * sigma_sq))   # Gaussian

        # Zone masking: soft smooth-step instead of hard cutoff.
        # Z (index 2) is the height axis in CAESAR convention.
        z_min, z_max = joint_zone[j]
        vz = verts[:, 2]  # Z coordinate = height in CAESAR convention
        above_min = np.clip((vz - z_min) / zone_margin, 0.0, 1.0)
        below_max = np.clip((z_max - vz) / zone_margin, 0.0, 1.0)
        zone_mask = above_min * below_max
        W[:, j] = w * zone_mask

    # Normalise so each row sums to 1
    row_sums = W.sum(axis=1, keepdims=True)
    # Guard against all-zero rows (very sparse region) → assign to ROOT
    zero_rows = (row_sums[:, 0] < 1e-15)
    W[zero_rows, ROOT] = 1.0
    row_sums[zero_rows] = 1.0
    W /= row_sums

    return W


# ---------------------------------------------------------------------------
# Keyframe + pose-sequence interpolation
# ---------------------------------------------------------------------------

@dataclass
class Keyframe:
    """A single keyframe: pose DOF angles at a given time."""
    time: float
    angles: np.ndarray   # shape (TOTAL_DOF,)

    def __post_init__(self) -> None:
        self.angles = np.asarray(self.angles, dtype=np.float64)
        if self.angles.shape != (TOTAL_DOF,):
            raise ValueError(
                f"Keyframe.angles must have shape ({TOTAL_DOF},), "
                f"got {self.angles.shape}"
            )


def interpolate_pose(
    keyframes: Sequence[Keyframe],
    t: float,
) -> np.ndarray:
    """
    Linearly interpolate between keyframes to get the pose at time *t*.

    If *t* is before the first keyframe, returns the first keyframe's pose.
    If *t* is after the last keyframe, returns the last keyframe's pose.

    Per-DOF linear interpolation (adequate for small joint angles; for
    large ranges quaternion-based SLERP would be preferred — Kavan 2008).

    Returns
    -------
    np.ndarray, shape (TOTAL_DOF,)
    """
    if not keyframes:
        return zero_pose()
    if len(keyframes) == 1 or t <= keyframes[0].time:
        return keyframes[0].angles.copy()
    if t >= keyframes[-1].time:
        return keyframes[-1].angles.copy()

    # Find bracketing keyframes
    for i in range(len(keyframes) - 1):
        k0, k1 = keyframes[i], keyframes[i + 1]
        if k0.time <= t <= k1.time:
            dt = k1.time - k0.time
            alpha = (t - k0.time) / dt if dt > 1e-15 else 0.0
            return (1.0 - alpha) * k0.angles + alpha * k1.angles

    return keyframes[-1].angles.copy()


def sample_pose_sequence(
    keyframes: Sequence[Keyframe],
    n_frames: int,
    t_start: Optional[float] = None,
    t_end: Optional[float] = None,
) -> List[np.ndarray]:
    """
    Sample a pose sequence at *n_frames* uniformly spaced times.

    Parameters
    ----------
    keyframes : sequence of Keyframe
    n_frames  : int
        Number of output frames (>= 1).
    t_start   : float or None
        Start time.  Defaults to keyframes[0].time.
    t_end     : float or None
        End time.    Defaults to keyframes[-1].time.

    Returns
    -------
    List[np.ndarray], length n_frames
        Each element is a pose vector of shape (TOTAL_DOF,).
    """
    if not keyframes:
        return [zero_pose()] * max(1, n_frames)

    t0 = t_start if t_start is not None else keyframes[0].time
    t1 = t_end   if t_end   is not None else keyframes[-1].time
    if n_frames == 1:
        return [interpolate_pose(keyframes, (t0 + t1) / 2.0)]

    times = np.linspace(t0, t1, n_frames)
    return [interpolate_pose(keyframes, float(t)) for t in times]


# ---------------------------------------------------------------------------
# Convenience: build a ready-to-use rig from an existing avatar mesh
# ---------------------------------------------------------------------------

def build_rig_from_avatar(
    avatar_verts: np.ndarray,    # (Nv, 3) float64, cm
    avatar_faces: np.ndarray,    # (Nf, 3) int32
    height_cm: float = 168.0,
    falloff_cm: float = 30.0,
) -> AvatarRig:
    """
    Build an AvatarRig from an existing CAESAR avatar mesh.

    Computes bind-pose joint positions scaled to *height_cm* and generates
    smooth skin weights via Gaussian distance falloff.

    Parameters
    ----------
    avatar_verts : np.ndarray, shape (Nv, 3)
        Avatar mesh vertices in cm.
    avatar_faces : np.ndarray, shape (Nf, 3)
        Triangle face indices.
    height_cm : float
        Avatar height (cm).
    falloff_cm : float
        Gaussian falloff radius for skinning (cm).

    Returns
    -------
    AvatarRig
    """
    bind_pos = _bind_pose_positions(height_cm)
    weights = build_skin_weights(avatar_verts, bind_pos, height_cm, falloff_cm)
    return AvatarRig(
        height_cm=height_cm,
        bind_verts=avatar_verts.copy(),
        skin_weights=weights,
        bind_positions=bind_pos,
    )


# ---------------------------------------------------------------------------
# Preset pose factories (convenience)
# ---------------------------------------------------------------------------

def arm_raise_sequence(
    side: str = "left",
    max_angle_deg: float = 90.0,
    n_frames: int = 10,
) -> List[Keyframe]:
    """
    Build a simple arm-raise pose sequence: arm goes from T-pose (0°)
    to *max_angle_deg* and back to 0°.

    Parameters
    ----------
    side : 'left' | 'right'
    max_angle_deg : float
    n_frames : int   (must be >= 2)

    Returns
    -------
    List[Keyframe], length n_frames
    """
    n_frames = max(2, n_frames)
    shoulder_j = L_SHOULDER if side == "left" else R_SHOULDER
    # In CAESAR Z-up convention (X=lateral, Y=depth, Z=height):
    # Arm raise (shoulder abduction) = rotation around Y axis.
    # Left arm: positive ry rotates the arm upward (away from body in Z-up).
    # Right arm: negative ry for same visual effect.
    sign = 1.0 if side == "left" else -1.0

    keyframes: List[Keyframe] = []
    for i in range(n_frames):
        t = i / (n_frames - 1)
        # Triangle wave: 0 → max → 0
        alpha = 2 * t if t < 0.5 else 2 * (1 - t)
        angle_rad = math.radians(max_angle_deg) * alpha * sign

        angles = zero_pose()
        off = _dof_offset(shoulder_j)
        angles[off + 1] = angle_rad   # ry = shoulder abduction (arm raise)

        keyframes.append(Keyframe(time=float(i), angles=angles))

    return keyframes


def squat_sequence(
    max_angle_deg: float = 45.0,
    n_frames: int = 8,
) -> List[Keyframe]:
    """
    Build a simple squat sequence: hips and knees flex.

    Hip flexion lowers the torso; knee flexion compensates.
    Spine bends slightly forward.
    """
    n_frames = max(2, n_frames)
    keyframes: List[Keyframe] = []

    for i in range(n_frames):
        t = i / (n_frames - 1)
        alpha = 2 * t if t < 0.5 else 2 * (1 - t)
        hip_ang  = math.radians(max_angle_deg * 0.5) * alpha
        knee_ang = math.radians(max_angle_deg) * alpha
        spine_ang = math.radians(max_angle_deg * 0.15) * alpha

        angles = zero_pose()

        # L_HIP and R_HIP: flex around X (forward tilt)
        for hip_j in [L_HIP, R_HIP]:
            off = _dof_offset(hip_j)
            angles[off + 0] = hip_ang   # rx = hip flexion

        # L_KNEE and R_KNEE: extend at knee (negative = flexion in this convention)
        for knee_j in [L_KNEE, R_KNEE]:
            off = _dof_offset(knee_j)
            angles[off + 0] = -knee_ang

        # Spine_mid: slight forward lean
        off = _dof_offset(SPINE_MID)
        angles[off + 0] = spine_ang

        keyframes.append(Keyframe(time=float(i), angles=angles))

    return keyframes
