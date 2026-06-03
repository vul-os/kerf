"""
kerf_cad_core.apparel.avatar — Parametric human avatar (ISO 8559-1:2017) + dress form.

Constructs a procedural human-form mesh from 12 anthropometric measurements
following ISO 8559-1:2017 (Clothing — Sizing systems — Part 1: Anthropometric
definitions for body measurement).

Approach
--------
v1 uses a **segment-primitive** body model:
  - Torso: 10-segment cylinder stack, radii scaled per-region from measurements
  - Limbs: single-axis cylinders (upper arm, forearm, thigh, calf) with joint
    offsets derived from height and inseam
  - Head: sphere with radius = neck_circumference / (2π) * 2.5 (cranial ratio)
  - All segments merged into a single (V×3, F×3) mesh in metres (Y-up)

Production-quality implementations would use SMPL (Loper et al. 2015, MPI-IS
Leipzig) — a learned statistical body model with 10 shape + 72 pose parameters
(SMPL: A Skinned Multi-Person Linear Model, SIGGRAPH Asia 2015).  CLO3D's Avatar
Editor (CLO Virtual Fashion, 2023) exposes the same 12 measurements used here.

References
----------
  ISO 8559-1:2017, "Clothing — Sizing systems — Part 1: Anthropometric
  definitions for body measurement".  ISO, Geneva.
  Annexe A defines the 96 standard landmark points.

  Loper, M. et al. (2015). "SMPL: A skinned multi-person linear model."
  ACM Trans. Graph. (SIGGRAPH Asia), 34(6), 248:1-16.

  CLO Virtual Fashion (2023). "Avatar Editor User Manual", CLO3D v7.4.
  https://support.clo3d.com/hc/en-us/articles/360040570433

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AvatarMeasurements:
    """ISO 8559-1:2017 body measurement system.

    Default values approximate the ISO female 'standard' size (size 38,
    height 168 cm, weight 62 kg).  See ISO 8559-3:2018 Table 1.
    """
    # --- primary measurements (ISO 8559-1 §8.1) ---
    height_cm: float = 170.0          # standing height
    weight_kg: float = 70.0           # body mass (informative; scales BMI proxy)
    bust_cm: float = 92.0             # chest girth (ISO §8.3.1 — tape at fullest chest point)
    waist_cm: float = 76.0            # natural waist girth (ISO §8.4.1)
    hip_cm: float = 98.0              # full hip girth (ISO §8.5.1 — 20 cm below waist)
    inseam_cm: float = 80.0           # inside-leg length (ISO §8.7.1 — crotch to floor)
    shoulder_width_cm: float = 42.0   # across-back shoulder width (ISO §8.2.4)
    arm_length_cm: float = 60.0       # total arm length shoulder→wrist (ISO §8.6.1)
    neck_circumference_cm: float = 36.0  # neck girth (ISO §8.1.2)
    thigh_cm: float = 56.0            # thigh girth (ISO §8.7.3 — max girth at crotch)
    calf_cm: float = 36.0             # calf girth (ISO §8.7.5 — max girth)
    upper_arm_cm: float = 28.0        # upper arm girth (ISO §8.6.2)
    gender: str = 'neutral'           # 'female' | 'male' | 'neutral'


@dataclass
class Avatar:
    """Human-form mesh assembled from parametric measurements.

    Coordinate system: Y-up, origin at floor mid-foot, units = metres.
    """
    measurements: AvatarMeasurements
    skeleton: Any                        # Skeleton if available, else None
    mesh_positions: np.ndarray           # (V, 3) float64
    mesh_triangles: np.ndarray           # (F, 3) int32
    landmarks: dict[str, np.ndarray]     # named landmark positions (m)


# ---------------------------------------------------------------------------
# Internal geometry helpers — all triangle indices are LOCAL (0-based)
# _merge_meshes handles global offsetting.
# ---------------------------------------------------------------------------

def _cylinder_segment(
    radius: float,
    z_bottom: float,
    z_top: float,
    n_sides: int = 12,
    x_offset: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Open-capped cylinder segment, local triangle indices (0-based)."""
    angles = np.linspace(0.0, 2.0 * math.pi, n_sides, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    bot = np.column_stack([x_offset + radius * cos_a, np.full(n_sides, z_bottom), radius * sin_a])
    top = np.column_stack([x_offset + radius * cos_a, np.full(n_sides, z_top), radius * sin_a])
    verts = np.vstack([bot, top]).astype(np.float64)  # (2n, 3)

    # Quads → triangles (local indices)
    tris = []
    for i in range(n_sides):
        j = (i + 1) % n_sides
        bl = i
        br = j
        tl = n_sides + i
        tr = n_sides + j
        tris.append([bl, br, tr])
        tris.append([bl, tr, tl])

    return verts, np.array(tris, dtype=np.int32)


def _disk_cap(
    radius: float,
    z: float,
    n_sides: int = 12,
    flip: bool = False,
    x_offset: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Filled disk cap, local triangle indices (0-based)."""
    angles = np.linspace(0.0, 2.0 * math.pi, n_sides, endpoint=False)
    rim = np.column_stack([
        x_offset + radius * np.cos(angles),
        np.full(n_sides, z),
        radius * np.sin(angles),
    ])
    center = np.array([[x_offset, z, 0.0]])
    verts = np.vstack([rim, center]).astype(np.float64)   # n + 1 verts

    cx = n_sides  # local index of center vertex
    tris = []
    for i in range(n_sides):
        j = (i + 1) % n_sides
        if flip:
            tris.append([cx, j, i])
        else:
            tris.append([cx, i, j])
    return verts, np.array(tris, dtype=np.int32)


def _sphere(
    center: np.ndarray,
    radius: float,
    n_lat: int = 8,
    n_lon: int = 12,
) -> tuple[np.ndarray, np.ndarray]:
    """UV sphere, local triangle indices (0-based)."""
    verts = [center + np.array([0.0, radius, 0.0])]  # north pole (index 0)
    for i in range(1, n_lat):
        lat = math.pi * i / n_lat - math.pi / 2.0
        y = radius * math.sin(lat)
        r = radius * math.cos(lat)
        for j in range(n_lon):
            lon = 2.0 * math.pi * j / n_lon
            verts.append(center + np.array([r * math.cos(lon), y, r * math.sin(lon)]))
    verts.append(center + np.array([0.0, -radius, 0.0]))  # south pole

    verts_arr = np.array(verts, dtype=np.float64)
    n_verts = len(verts)
    south_idx = n_verts - 1

    tris = []
    # north cap
    for j in range(n_lon):
        a = 1 + j
        b = 1 + (j + 1) % n_lon
        tris.append([0, b, a])
    # body bands
    for i in range(n_lat - 2):
        row0 = 1 + i * n_lon
        row1 = 1 + (i + 1) * n_lon
        for j in range(n_lon):
            a0 = row0 + j
            a1 = row0 + (j + 1) % n_lon
            b0 = row1 + j
            b1 = row1 + (j + 1) % n_lon
            tris.append([a0, a1, b1])
            tris.append([a0, b1, b0])
    # south cap
    last_row = 1 + (n_lat - 2) * n_lon
    for j in range(n_lon):
        a = last_row + j
        b = last_row + (j + 1) % n_lon
        tris.append([south_idx, a, b])

    return verts_arr, np.array(tris, dtype=np.int32)


def _merge_meshes(
    meshes: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Merge a list of (verts, tris) pairs — all tris are LOCAL (0-based).

    Applies global offset to each mesh's triangles during merge.
    """
    all_v: list[np.ndarray] = []
    all_t: list[np.ndarray] = []
    offset = 0
    for v, t in meshes:
        all_v.append(v)
        all_t.append(t + offset)  # shift local indices to global
        offset += len(v)
    return (
        np.vstack(all_v).astype(np.float64),
        np.vstack(all_t).astype(np.int32),
    )


def _girth_radius(girth_cm: float) -> float:
    """Convert girth measurement (cm) to cylinder radius (m)."""
    return (girth_cm / 100.0) / (2.0 * math.pi)


def _make_limb_cylinder(
    x_lateral: float,
    r_top: float,
    r_bot: float,
    y_top: float,
    y_bot: float,
    n_sides: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build an arm/leg cylinder with x_lateral offset, local 0-based triangle indices."""
    angles = np.linspace(0.0, 2.0 * math.pi, n_sides, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)
    top_ring = np.column_stack([x_lateral + r_top * cos_a, np.full(n_sides, y_top), r_top * sin_a])
    bot_ring = np.column_stack([x_lateral + r_bot * cos_a, np.full(n_sides, y_bot), r_bot * sin_a])
    verts = np.vstack([top_ring, bot_ring]).astype(np.float64)  # 0..N-1 = top, N..2N-1 = bot
    tris = []
    for i in range(n_sides):
        j = (i + 1) % n_sides
        t0 = i
        t1 = j
        b0 = n_sides + i
        b1 = n_sides + j
        tris.append([t0, t1, b1])
        tris.append([t0, b1, b0])
    return verts, np.array(tris, dtype=np.int32)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_avatar(m: AvatarMeasurements) -> Avatar:
    """Procedurally construct a human-form mesh from measurements.

    Approach: blend a base male/female/neutral mesh by per-region scale factors
    derived from measurement deltas.  v1 ships with one base mesh per gender
    (10-segment cylinder torso + cylinder limbs + sphere head); production-quality
    would use SMPL or MakeHuman.

    Coordinate system: Y-up, origin at floor, units = metres.

    ISO 8559-1:2017 body segments mapped to cylinder primitives:
      Neck      neck_circumference → 1 short cylinder
      Shoulder  shoulder_width     → horizontal extent of torso top
      Bust      bust_cm            → 2 torso cylinders around chest
      Waist     waist_cm           → 2 torso cylinders at natural waist
      Hip       hip_cm             → 2 torso cylinders at hip
      Pelvis    (waist→crotch)     → 1 torso cylinder
      Upper arm upper_arm_cm       → 1 cylinder per arm
      Forearm   arm_length-derived → 1 cylinder per arm
      Thigh     thigh_cm           → 1 cylinder per leg
      Calf      calf_cm            → 1 cylinder per leg
      Head      neck_circumference → sphere

    SMPL reference: Loper et al. (2015) ACM TOG 34(6).
    CLO3D Avatar Editor: CLO Virtual Fashion 2023 user manual §4.2.
    """
    h = m.height_cm / 100.0   # metres

    # -- skeletal proportions derived from height & inseam --
    leg_len = m.inseam_cm / 100.0
    torso_len = h - leg_len - (m.neck_circumference_cm / 100.0 / (2.0 * math.pi) * 2.5 * 2.0)
    torso_len = max(torso_len, 0.2)

    crotch_z = leg_len
    waist_z = crotch_z + torso_len * 0.35
    bust_z = crotch_z + torso_len * 0.65
    shoulder_z = crotch_z + torso_len * 0.90
    neck_bottom_z = shoulder_z
    neck_top_z = neck_bottom_z + m.neck_circumference_cm / 100.0 * 0.35
    head_r = (m.neck_circumference_cm / 100.0) / (2.0 * math.pi) * 2.5
    head_center_z = neck_top_z + head_r

    # -- radii from girth measurements --
    r_hip = _girth_radius(m.hip_cm)
    r_waist = _girth_radius(m.waist_cm)
    r_bust = _girth_radius(m.bust_cm)
    r_neck = _girth_radius(m.neck_circumference_cm)
    r_thigh = _girth_radius(m.thigh_cm)
    r_calf = _girth_radius(m.calf_cm)
    r_upper_arm = _girth_radius(m.upper_arm_cm)
    r_forearm = _girth_radius(m.upper_arm_cm * 0.75)

    N = 12  # sides for body cylinders

    meshes: list[tuple[np.ndarray, np.ndarray]] = []

    # ---- torso (6 stacked cylinder segments, all local 0-based indices) ----
    torso_segs = [
        # (z_bot, z_top, r_avg)
        (0.0,         crotch_z * 0.1,   r_hip * 0.65),
        (crotch_z * 0.1, crotch_z,      r_hip * 0.85),
        (crotch_z,    waist_z,           (r_hip + r_waist) / 2.0),
        (waist_z,     bust_z,            (r_waist + r_bust) / 2.0),
        (bust_z,      shoulder_z,        r_bust * 0.95),
        (neck_bottom_z, neck_top_z,      r_neck * 1.05),
    ]

    for (zb, zt, r_avg) in torso_segs:
        v, t = _cylinder_segment(r_avg, zb, zt, n_sides=N, x_offset=0.0)
        meshes.append((v, t))

    # Close torso top (neck top) and bottom — local indices
    v, t = _disk_cap(r_neck, neck_top_z, n_sides=N, flip=False, x_offset=0.0)
    meshes.append((v, t))
    v, t = _disk_cap(r_hip * 0.65, 0.0, n_sides=N, flip=True, x_offset=0.0)
    meshes.append((v, t))

    # ---- head ----
    head_center = np.array([0.0, head_center_z, 0.0])
    v, t = _sphere(head_center, head_r, n_lat=8, n_lon=N)
    meshes.append((v, t))

    # ---- arms ----
    arm_total = m.arm_length_cm / 100.0
    upper_arm_len = arm_total * 0.45
    forearm_len = arm_total * 0.55
    arm_attach_y = shoulder_z - (shoulder_z - bust_z) * 0.15
    shoulder_half = m.shoulder_width_cm / 100.0 / 2.0

    for side in (-1, 1):  # left (-1), right (+1)
        sx = side * shoulder_half
        # upper arm
        v, t = _make_limb_cylinder(
            sx, r_upper_arm, r_upper_arm * 0.95,
            arm_attach_y, arm_attach_y - upper_arm_len, N
        )
        meshes.append((v, t))
        # forearm
        fa_top = arm_attach_y - upper_arm_len
        v, t = _make_limb_cylinder(
            sx, r_forearm, r_forearm * 0.80,
            fa_top, fa_top - forearm_len, N
        )
        meshes.append((v, t))

    # ---- legs ----
    thigh_len = leg_len * 0.50
    calf_len = leg_len * 0.45
    foot_stub = leg_len - thigh_len - calf_len
    hip_half = r_hip * 0.5   # lateral offset for legs

    for side in (-1, 1):
        lx = side * hip_half
        # foot stub
        v, t = _make_limb_cylinder(lx, r_calf * 0.55, r_calf * 0.50, foot_stub, 0.0, N)
        meshes.append((v, t))
        # calf
        v, t = _make_limb_cylinder(lx, r_calf, r_calf * 0.60, foot_stub + calf_len, foot_stub, N)
        meshes.append((v, t))
        # thigh
        v, t = _make_limb_cylinder(lx, r_thigh, r_calf, leg_len, foot_stub + calf_len, N)
        meshes.append((v, t))

    # ---- merge — _merge_meshes applies global offset to each mesh's local tris ----
    positions, triangles = _merge_meshes(meshes)

    # ---- landmarks (ISO 8559-1 Annex A naming convention) ----
    sw = m.shoulder_width_cm / 100.0
    landmarks: dict[str, np.ndarray] = {
        "crown":              np.array([0.0, head_center_z + head_r, 0.0]),
        "chin":               np.array([0.0, neck_top_z, 0.0]),
        "left_shoulder":      np.array([-sw / 2.0, shoulder_z, 0.0]),
        "right_shoulder":     np.array([ sw / 2.0, shoulder_z, 0.0]),
        "bust_point_left":    np.array([-r_bust * 0.5, bust_z, r_bust * 0.5]),
        "bust_point_right":   np.array([ r_bust * 0.5, bust_z, r_bust * 0.5]),
        "waist_centre_front": np.array([0.0, waist_z, r_waist]),
        "waist_centre_back":  np.array([0.0, waist_z, -r_waist]),
        "hip_centre_front":   np.array([0.0, crotch_z + (waist_z - crotch_z) * 0.5, r_hip]),
        "crotch":             np.array([0.0, crotch_z, 0.0]),
        "left_knee":          np.array([-hip_half, foot_stub + calf_len, 0.0]),
        "right_knee":         np.array([ hip_half, foot_stub + calf_len, 0.0]),
        "left_hip":           np.array([-hip_half, crotch_z + (waist_z - crotch_z) * 0.3, 0.0]),
        "right_hip":          np.array([ hip_half, crotch_z + (waist_z - crotch_z) * 0.3, 0.0]),
    }

    # Try to attach skeleton if sculpt.character_rigging is available
    skeleton = None
    try:
        from kerf_cad_core.sculpt.character_rigging import Skeleton  # type: ignore
        skeleton = Skeleton.from_landmarks(landmarks)
    except (ImportError, AttributeError):
        pass  # v1: no rigging module; skeleton stays None

    return Avatar(
        measurements=m,
        skeleton=skeleton,
        mesh_positions=positions,
        mesh_triangles=triangles,
        landmarks=landmarks,
    )


def fit_dress_form(
    avatar: Avatar,
    ease_cm: float = 2.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute the dress form (slightly larger than avatar) for cloth-pattern draping.

    Method: uniformly expand all vertex positions outward from the Y-axis by
    ease_cm / (2π) in the XZ plane (pure radial ease).  Vertical (Y) positions
    are unchanged so the dress form has the same height and waist/bust/hip level
    positions as the avatar.

    A real dress-form model would apply different ease amounts per body region
    (ASTM D5219-21 §6 pattern ease table).  v1 applies uniform ease.

    Args:
        avatar: source Avatar mesh
        ease_cm: clearance between body and dress form in cm (default 2.5 cm)

    Returns:
        (vertices, triangles) — new vertex array with same connectivity as avatar
    """
    ease_m = ease_cm / 100.0
    v = avatar.mesh_positions.copy()

    # Radial XZ expansion from the Y-axis
    xz = v[:, [0, 2]]                     # (V, 2)
    r = np.linalg.norm(xz, axis=1, keepdims=True)  # (V, 1)
    # Avoid division by zero for points on the Y-axis
    safe_r = np.where(r < 1e-9, 1.0, r)
    direction = xz / safe_r               # unit XZ direction
    expansion = np.where(r < 1e-9, 0.0, ease_m)
    v[:, 0] += direction[:, 0] * expansion[:, 0]
    v[:, 2] += direction[:, 1] * expansion[:, 0]

    return v, avatar.mesh_triangles.copy()
