"""
kerf_textiles.cloth_sim_on_rigged
==================================
Dynamic cloth simulation on a rigged / posed avatar: drives the existing
Provot (1995) mass-spring cloth solver against a skeleton-animated body
mesh so that garments follow the character's motion with physically correct
draping, fold, and collision behaviour over a pose sequence.

Method
------
1. **Rigged avatar deformation** (kerf_textiles.rigged_avatar)
   Linear-blend skinning (LBS) deforms the avatar mesh per frame to
   a new pose sampled from a keyframe sequence (Mohr & Gleicher 2003).

2. **Per-frame body collider update**
   The deformed body mesh is used as a rigid collision body for that frame.
   Mesh-triangle collision response (Bridson 2003, §4) projects any cloth
   particle that penetrates the body surface back outside, cancelling its
   inward velocity component.

3. **Cloth dynamics**
   The mass-spring solver (Provot 1995 + Baraff-Witkin 1998 substep) is
   advanced by a fixed Δt per animation frame, accumulating spring, gravity,
   and damping forces, integrating velocity + position, then resolving body
   collisions.  The body is treated as **kinematic** (infinitely massive) —
   the cloth receives impulses from it but does not push the body.

4. **Pose sequence loop**
   For each animation frame [0, N_frames-1]:
     a. Interpolate pose from keyframes at time t = frame × dt_anim.
     b. LBS-deform avatar mesh → current_body_verts.
     c. Advance cloth one sim step (with current_body_verts as collider).
     d. Record cloth vertex positions.

Output: per-frame cloth vertex positions (shape: N_frames × Nv × 3, cm).

Architecture
------------
ClothSimOnRiggedResult    — output dataclass
cloth_sim_on_rigged        — main entry point (works on supplied mesh + rig)
cloth_sim_on_rigged_avatar — convenience: builds avatar + rig from CAESAR params

References
----------
Provot, X. (1995). "Deformation constraints in a mass-spring model."
  Graphics Interface 1995.  (spring topology + stability)
Baraff, D. & Witkin, A. (1998). "Large steps in cloth simulation."
  SIGGRAPH '98.  (substep stability criterion)
Bridson, R., Marino, S., Fedkiw, R. (2003). "Simulation of clothing
  with folds and wrinkles." SCA '03.  (mesh-triangle collision response)
Mohr, A. & Gleicher, M. (2003). "Deformation-sensitive decimation."
  (LBS formulation used in kerf_textiles.rigged_avatar)

Honest limitations
------------------
- Linear-blend skinning only (no dual-quaternion or corrective shapes).
- Cloth-to-cloth self-collision not implemented.
- Cloth does not push back on the character (kinematic body).
- No friction: collision response cancels only inward velocity.
- Single garment panel (not multi-panel simultaneous).
- Animation is FK only; no IK, no motion-capture import.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from kerf_textiles.mass_spring import (
    ClothMesh,
    PlanePrimitive,
    solve_step,
)
from kerf_textiles.garment_drape import (
    body_region_centroid,
    place_panel_near_region,
    resolve_mesh_collisions,
    compute_fit_tension,
    DrapeOnAvatarResult,
    drape_garment_on_avatar,
    _REGION_LANDMARKS,
)
from kerf_textiles.rigged_avatar import (
    AvatarRig,
    Keyframe,
    N_JOINTS,
    TOTAL_DOF,
    build_rig_from_avatar,
    interpolate_pose,
    sample_pose_sequence,
    zero_pose,
)


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClothSimOnRiggedResult:
    """
    Output of :func:`cloth_sim_on_rigged`.

    Attributes
    ----------
    frame_verts : np.ndarray, shape (N_frames, Nv, 3)
        Per-frame cloth vertex positions in cm.
    frame_body_verts : np.ndarray, shape (N_frames, Nb, 3)
        Per-frame deformed body mesh vertex positions in cm.
    frame_fit_tension : np.ndarray, shape (N_frames, Nv)
        Per-frame per-vertex fit tension (spring stretch ratio).
    frame_energy : np.ndarray, shape (N_frames,)
        Total cloth kinetic + spring potential energy per frame (J).
    max_penetration_per_frame : np.ndarray, shape (N_frames,)
        Maximum cloth-body penetration depth per frame (cm).
    n_frames : int
        Number of animation frames.
    n_cloth_particles : int
        Number of cloth particles.
    n_body_verts : int
        Number of avatar body vertices.
    cloth_rows, cloth_cols : int
        Grid dimensions of the cloth mesh.
    converged_static : bool
        Whether the initial static drape (pre-animation) converged.
    notes : list[str]
        Informational messages from the simulation.
    """
    frame_verts:            np.ndarray   # (N_frames, Nv, 3)  cm
    frame_body_verts:       np.ndarray   # (N_frames, Nb, 3)  cm
    frame_fit_tension:      np.ndarray   # (N_frames, Nv)
    frame_energy:           np.ndarray   # (N_frames,)
    max_penetration_per_frame: np.ndarray  # (N_frames,)
    n_frames:               int
    n_cloth_particles:      int
    n_body_verts:           int
    cloth_rows:             int
    cloth_cols:             int
    converged_static:       bool
    notes:                  List[str]


# ---------------------------------------------------------------------------
# Main simulation entry point
# ---------------------------------------------------------------------------

def cloth_sim_on_rigged(
    rig: AvatarRig,
    avatar_faces: np.ndarray,          # (Nf, 3) int32
    keyframes: Sequence[Keyframe],
    landmarks: Dict,
    height_cm: float = 168.0,
    # Cloth panel parameters
    panel_width_cm: float = 40.0,
    panel_height_cm: float = 50.0,
    panel_rows: int = 10,
    panel_cols: int = 10,
    target_region: str = "torso",
    # Physics parameters
    mass_per_particle_kg: float = 0.003,
    k_structural: float = 80.0,
    k_shear: float = 40.0,
    k_bend: float = 4.0,
    velocity_damping: float = 0.97,
    cloth_thickness_cm: float = 0.1,
    pin_top_edge: bool = True,
    # Simulation timing
    static_settle_steps: int = 800,
    static_dt: float = 0.005,
    static_tol: float = 1e-3,
    n_frames: int = 20,
    dt_anim: float = 0.033,     # ~30 fps
    sim_steps_per_frame: int = 5,
    sim_dt: float = 0.005,
    t_start: Optional[float] = None,
    t_end:   Optional[float] = None,
) -> ClothSimOnRiggedResult:
    """
    Run cloth simulation on a rigged, animated avatar.

    The garment is first settled on the avatar in bind pose (static drape),
    then the animation begins — per frame the avatar is posed via LBS and
    the cloth is advanced against the updated body collider.

    Parameters
    ----------
    rig : AvatarRig
        Rigged avatar (bind vertices + skin weights + bind positions).
    avatar_faces : np.ndarray, shape (Nf, 3)
        Triangle face indices of the avatar mesh.
    keyframes : sequence of Keyframe
        Pose sequence.  If empty, a static T-pose is used.
    landmarks : dict
        CAESAR landmark slices (for panel auto-placement).
    height_cm : float
        Avatar standing height (cm).
    panel_width_cm, panel_height_cm : float
        Flat panel dimensions (cm).
    panel_rows, panel_cols : int
        Grid resolution.
    target_region : str
        Body region for panel placement.
    mass_per_particle_kg : float
        Per-particle mass (kg).
    k_structural, k_shear, k_bend : float
        Spring stiffnesses (N/m).
    velocity_damping : float
        Per-sub-step velocity damping multiplier.
    cloth_thickness_cm : float
        Collision offset thickness (cm).
    pin_top_edge : bool
        If True, pin the top row during static settle; unpin for animation
        to let the garment move freely with the character's body.
        (Top row remains pinned in animation too, simulating neckline.)
    static_settle_steps : int
        Steps for initial static drape in bind pose.
    static_dt : float
        Time step for static settle.
    static_tol : float
        RMS velocity convergence tolerance for static settle.
    n_frames : int
        Number of animation frames to simulate.
    dt_anim : float
        Duration of each animation frame (seconds).
    sim_steps_per_frame : int
        Number of cloth integration sub-steps per animation frame.
    sim_dt : float
        Time step for each animation sub-step.
    t_start, t_end : float or None
        Time range to sample the pose sequence over.

    Returns
    -------
    ClothSimOnRiggedResult
    """
    notes: List[str] = []

    # -------------------------------------------------------------------------
    # 0. Build initial cloth mesh on bind-pose avatar
    # -------------------------------------------------------------------------
    bind_verts_cm = rig.bind_verts.copy()   # (Nb, 3) in cm

    # Build cloth mesh (spacing in metres)
    spacing_m = (panel_width_cm / 100.0) / max(1, panel_cols - 1)
    cloth = ClothMesh(
        rows=panel_rows,
        cols=panel_cols,
        spacing=spacing_m,
        mass=mass_per_particle_kg,
        k_structural=k_structural,
        k_shear=k_shear,
        k_bend=k_bend,
    )

    # Rescale height dimension
    row_scale = (panel_height_cm / 100.0) / max(1e-10, (panel_rows - 1) * spacing_m)
    if abs(row_scale - 1.0) > 0.01:
        new_pos = []
        for r in range(panel_rows):
            for c in range(panel_cols):
                idx = cloth._idx(r, c)
                p = cloth.positions[idx]
                new_pos.append((p[0], p[1] * row_scale, p[2] * row_scale))
        cloth.positions = new_pos

    # Auto-position panel near body region
    centroid = body_region_centroid(
        bind_verts_cm, avatar_faces, landmarks, target_region, height_cm
    )
    region_lms = _REGION_LANDMARKS.get(target_region, _REGION_LANDMARKS["torso"])
    half_widths = []
    for lm_name in region_lms:
        lm = landmarks.get(lm_name)
        if lm is not None and hasattr(lm, "a_cm"):
            half_widths.append(lm.a_cm)
    region_radius_cm = max(half_widths) + 2.0 if half_widths else 20.0
    place_panel_near_region(cloth, centroid, region_radius_cm=region_radius_cm, offset_cm=5.0)

    if pin_top_edge:
        for c in range(panel_cols):
            cloth.pin(0, c)

    # -------------------------------------------------------------------------
    # 1. Static settle: drape garment on bind-pose body
    # -------------------------------------------------------------------------
    ankle_lm = landmarks.get("ankle")
    floor_y_cm = ankle_lm.z_cm if ankle_lm is not None else 6.0
    floor = PlanePrimitive(height=floor_y_cm / 100.0)

    converged_static = False
    for step in range(1, static_settle_steps + 1):
        solve_step(cloth, dt=static_dt, velocity_damping=velocity_damping, colliders=[floor])
        cloth.positions, cloth.velocities, _ = resolve_mesh_collisions(
            cloth.positions, cloth.velocities, cloth.pinned,
            bind_verts_cm, avatar_faces, thickness_cm=cloth_thickness_cm,
        )
        if step % 50 == 0 and cloth.rms_velocity() < static_tol:
            converged_static = True
            notes.append(f"Static settle converged at step {step}.")
            break

    if not converged_static:
        notes.append(f"Static settle reached max {static_settle_steps} steps (not converged).")

    # -------------------------------------------------------------------------
    # 2. Sample pose sequence
    # -------------------------------------------------------------------------
    if not keyframes:
        poses = [zero_pose()] * n_frames
        notes.append("No keyframes supplied: using static T-pose for all frames.")
    else:
        poses = sample_pose_sequence(keyframes, n_frames, t_start=t_start, t_end=t_end)
        notes.append(f"Sampled {n_frames} frames from {len(keyframes)} keyframes.")

    # -------------------------------------------------------------------------
    # 3. Animation loop: update body collider + advance cloth per frame
    # -------------------------------------------------------------------------
    Nv = len(cloth.positions)
    Nb = len(rig.bind_verts)
    Nf = n_frames

    frame_verts = np.zeros((Nf, Nv, 3), dtype=np.float64)
    frame_body  = np.zeros((Nf, Nb, 3), dtype=np.float64)
    frame_tension = np.zeros((Nf, Nv), dtype=np.float64)
    frame_energy  = np.zeros(Nf, dtype=np.float64)
    frame_maxpen  = np.zeros(Nf, dtype=np.float64)

    for fi in range(Nf):
        pose = poses[fi]

        # --- Update body collider from rig pose ---
        posed_body = rig.pose_mesh(pose)   # (Nb, 3) in cm

        # --- Advance cloth sim_steps_per_frame sub-steps ---
        max_pen_this_frame = 0.0
        for _ in range(sim_steps_per_frame):
            solve_step(
                cloth, dt=sim_dt,
                velocity_damping=velocity_damping,
                colliders=[floor],
            )
            cloth.positions, cloth.velocities, pen = resolve_mesh_collisions(
                cloth.positions, cloth.velocities, cloth.pinned,
                posed_body, avatar_faces,
                thickness_cm=cloth_thickness_cm,
            )
            if pen > max_pen_this_frame:
                max_pen_this_frame = pen

        # --- Record frame ---
        frame_verts[fi] = np.array(
            [[p[0] * 100.0, p[1] * 100.0, p[2] * 100.0] for p in cloth.positions],
            dtype=np.float64,
        )
        frame_body[fi]  = posed_body
        frame_tension[fi] = compute_fit_tension(cloth)
        frame_energy[fi]  = cloth.total_energy()
        frame_maxpen[fi]  = max_pen_this_frame

    notes.append(
        f"Animation: {Nf} frames, {sim_steps_per_frame} steps/frame, "
        f"dt={sim_dt}s, avg energy={float(frame_energy.mean()):.4g} J."
    )

    return ClothSimOnRiggedResult(
        frame_verts=frame_verts,
        frame_body_verts=frame_body,
        frame_fit_tension=frame_tension,
        frame_energy=frame_energy,
        max_penetration_per_frame=frame_maxpen,
        n_frames=Nf,
        n_cloth_particles=Nv,
        n_body_verts=Nb,
        cloth_rows=panel_rows,
        cloth_cols=panel_cols,
        converged_static=converged_static,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Convenience: build from CAESAR measurements
# ---------------------------------------------------------------------------

def cloth_sim_on_rigged_avatar(
    keyframes: Sequence[Keyframe],
    height_cm: float = 168.0,
    bust_cm: float = 92.0,
    waist_cm: float = 74.0,
    hip_cm: float = 96.0,
    sex: str = "female",
    panel_width_cm: float = 40.0,
    panel_height_cm: float = 50.0,
    panel_rows: int = 10,
    panel_cols: int = 10,
    target_region: str = "torso",
    n_frames: int = 20,
    static_settle_steps: int = 800,
    **kwargs,
) -> ClothSimOnRiggedResult:
    """
    Build a CAESAR body-form avatar, attach a skeletal rig, and run cloth
    simulation over a pose sequence.

    This is the main convenience entry point used by the LLM tool.
    """
    from kerf_apparel.avatar import build_body_form

    bf = build_body_form(
        height_cm=height_cm,
        bust_cm=bust_cm,
        waist_cm=waist_cm,
        hip_cm=hip_cm,
        sex=sex,
        n_vertices_per_ring=20,
        n_slices_per_segment=3,
    )

    rig = build_rig_from_avatar(
        avatar_verts=bf.vertices,
        avatar_faces=bf.faces,
        height_cm=height_cm,
        falloff_cm=30.0,
    )

    return cloth_sim_on_rigged(
        rig=rig,
        avatar_faces=bf.faces,
        keyframes=keyframes,
        landmarks=bf.landmarks,
        height_cm=height_cm,
        panel_width_cm=panel_width_cm,
        panel_height_cm=panel_height_cm,
        panel_rows=panel_rows,
        panel_cols=panel_cols,
        target_region=target_region,
        n_frames=n_frames,
        static_settle_steps=static_settle_steps,
        **kwargs,
    )
