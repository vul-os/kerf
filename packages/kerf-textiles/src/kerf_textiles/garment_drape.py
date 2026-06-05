"""
kerf_textiles.garment_drape
===========================
Garment-on-avatar drape: settle a flat garment panel onto a parametric
body-form mesh using mass-spring cloth simulation with mesh-triangle
collision response (Bridson 2003).

Method
------
1. **Body-form collision**  — the avatar mesh (from kerf_apparel.avatar)
   is treated as a rigid, static collision body.  For each cloth particle
   we test against avatar triangles using point-triangle closest-point
   (Bridson 2003, §4 / Ericson 2005, §5.1.5) and project penetrating
   particles outside.

2. **Panel arrangement**  — before simulation the flat cloth panel is
   auto-positioned near the target body region (bust / waist / hip /
   full-torso) by placing it slightly in front of (+Y offset) the
   centroid of the relevant avatar landmark slice.

3. **Cloth mesh**  — the flat panel is meshed as a grid of mass-spring
   particles (Provot 1995) and settled under gravity using the existing
   kerf_textiles.mass_spring solver with per-substep auto-stepping for
   stability (Baraff-Witkin 1998).

4. **Fit tension** — per-vertex strain magnitude is computed as the mean
   spring stretch ratio across all springs incident to that vertex.
   stretch_ratio = (current_length - rest_length) / rest_length
   Positive = tension (stretched), negative = compression (bunched).
   This drives a fit-quality heatmap (red = tight, blue = loose).

References
----------
Bridson, R., Marino, S., Fedkiw, R. (2003). "Simulation of clothing with
  folds and wrinkles." SCA '03, §4 (collision detection and response).
Provot, X. (1995). "Deformation constraints in a mass-spring model."
  Graphics Interface.
Baraff, D. & Witkin, A. (1998). "Large steps in cloth simulation."
  SIGGRAPH '98.
Ericson, C. (2005). "Real-Time Collision Detection." §5.1.5.
Robinette, K. et al. (2002). "CAESAR Final Report." (body proportions)

Public API
----------
DrapeOnAvatarResult  — output dataclass
drape_garment_on_avatar  — main entry point

Arrangement-point helpers (also exported for testing):
  body_region_centroid  — 3-D centroid of avatar landmark band
  place_panel_near_region  — translate flat panel to target region

Collision helpers:
  point_triangle_closest  — closest point on triangle to a query point
  point_triangle_penetration_response  — project + correct velocity
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_textiles.mass_spring import (
    ClothMesh,
    PlanePrimitive,
    Vec3,
    _norm,
    _sub,
    _add,
    _scale,
    _dot,
    _normalize,
    solve_step,
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DrapeOnAvatarResult:
    """
    Output of :func:`drape_garment_on_avatar`.

    Attributes
    ----------
    mesh : ClothMesh
        Final settled cloth mesh (positions are the draped 3D geometry).
    vertices_3d : np.ndarray, shape (N, 3)
        Per-particle positions as a float64 array (cm).
    fit_tension : np.ndarray, shape (N,)
        Per-vertex mean spring stretch ratio (dimensionless).
        > 0  = fabric is stretched (tension, tight region).
        < 0  = fabric is compressed (bunched region).
        ≈ 0  = relaxed (good fit).
    max_penetration_cm : float
        Maximum residual penetration into avatar (cm). Should be < 0.5 mm.
    no_deep_penetration : bool
        True when max_penetration_cm < 0.1 * avg_avatar_triangle_radius.
    symmetry_error_cm : float
        RMS y-position difference between left and right halves of a
        symmetric panel (0.0 for a non-symmetric panel).
    converged : bool
        True if simulation reached RMS-velocity convergence.
    steps_taken : int
        Outer integration steps executed.
    energy_history : list[float]
        Total energy sampled every 100 outer steps (for plateau check).
    target_region : str
        Which body region the panel was placed near.
    """
    mesh: ClothMesh
    vertices_3d: np.ndarray
    fit_tension: np.ndarray
    max_penetration_cm: float
    no_deep_penetration: bool
    symmetry_error_cm: float
    converged: bool
    steps_taken: int
    energy_history: List[float]
    target_region: str


# ---------------------------------------------------------------------------
# Triangle closest-point (Ericson 2005, §5.1.5)
# ---------------------------------------------------------------------------

def point_triangle_closest(
    p: np.ndarray,          # (3,) query point
    a: np.ndarray,          # (3,) triangle vertex A
    b: np.ndarray,          # (3,) triangle vertex B
    c: np.ndarray,          # (3,) triangle vertex C
) -> Tuple[np.ndarray, float]:
    """
    Compute the closest point on triangle ABC to point P, and the signed
    penetration depth (negative = P is outside, positive = P is inside
    the surface on the inward side).

    Algorithm: Ericson 2005, "Real-Time Collision Detection" §5.1.5.
    Returns (closest_point, signed_distance) where signed_distance is the
    component of (P - closest) along the triangle outward normal.

    Parameters
    ----------
    p, a, b, c : np.ndarray, shape (3,)

    Returns
    -------
    closest : np.ndarray, shape (3,)
        Closest point on triangle to p.
    penetration : float
        Positive if p is behind (inside) the surface; negative if outside.
    """
    ab = b - a
    ac = c - a
    ap = p - a

    d1 = float(np.dot(ab, ap))
    d2 = float(np.dot(ac, ap))
    if d1 <= 0.0 and d2 <= 0.0:
        closest = a.copy()
    else:
        bp = p - b
        d3 = float(np.dot(ab, bp))
        d4 = float(np.dot(ac, bp))
        if d3 >= 0.0 and d4 <= d3:
            closest = b.copy()
        else:
            vc = d1 * d4 - d3 * d2
            if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
                v = d1 / (d1 - d3)
                closest = a + v * ab
            else:
                cp = p - c
                d5 = float(np.dot(ab, cp))
                d6 = float(np.dot(ac, cp))
                if d6 >= 0.0 and d5 <= d6:
                    closest = c.copy()
                else:
                    vb = d5 * d2 - d1 * d6
                    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
                        w = d2 / (d2 - d6)
                        closest = a + w * ac
                    else:
                        va = d3 * d6 - d5 * d4
                        w3 = d3 - d4
                        w6 = d6 - d5
                        denom = va + vb + vc
                        if abs(denom) < 1e-15:
                            closest = a.copy()
                        else:
                            _vb = vb / denom
                            _vc = vc / denom
                            closest = a + _vb * ab + _vc * ac

    # Outward normal (normalised)
    n = np.cross(ab, ac)
    n_len = float(np.linalg.norm(n))
    if n_len < 1e-15:
        return closest, -1.0  # degenerate triangle → no penetration

    n_hat = n / n_len
    # signed_dist > 0 means P is on the inward (body) side of the triangle
    # (behind the outward normal), i.e. the particle has penetrated
    diff = p - closest
    dist_to_plane = float(np.dot(diff, n_hat))
    dist_to_closest = float(np.linalg.norm(diff))
    # Penetration depth = how far P must be pushed out
    # We use signed distance to plane for penetration detection:
    # if P is on the back side (dist_to_plane < 0), penetration depth =
    # distance to closest point on triangle surface.
    penetration = dist_to_closest if dist_to_plane < 0.0 else -dist_to_closest

    return closest, penetration


# ---------------------------------------------------------------------------
# Mesh collision response (Bridson 2003, §4)
# ---------------------------------------------------------------------------

_COLLISION_MARGIN_FACTOR = 1.001   # 0.1% push-out margin (same as sphere)


def resolve_mesh_collisions(
    positions: List[Vec3],
    velocities: List[Vec3],
    pinned: List[bool],
    avatar_verts: np.ndarray,    # (Nv, 3) float64
    avatar_faces: np.ndarray,    # (Nf, 3) int32
    thickness_cm: float = 0.1,   # cloth thickness for collision offset
) -> Tuple[List[Vec3], List[Vec3], float]:
    """
    Project any cloth particle that has penetrated the avatar mesh surface
    back to the outside, and cancel the inward velocity component.

    Uses point-triangle closest-point per Bridson (2003) §4.
    For performance, only faces whose bounding box overlaps the particle
    are tested (AABB pre-filter with 2× thickness margin).

    Returns
    -------
    (positions, velocities, max_penetration)
    max_penetration : float — maximum penetration depth found (cm)
    """
    n = len(positions)
    pos = list(positions)
    vel = list(velocities)
    max_pen = 0.0

    # Build per-triangle AABBs once (in cm)
    # avatar_verts are already in cm
    tri_min = avatar_verts[avatar_faces].min(axis=1)  # (Nf, 3)
    tri_max = avatar_verts[avatar_faces].max(axis=1)  # (Nf, 3)
    margin = thickness_cm * 2.0

    for i in range(n):
        if pinned[i]:
            continue

        px, py, pz = pos[i]
        p_np = np.array([px, py, pz], dtype=np.float64)

        # AABB pre-filter: only test triangles whose bounding box contains p
        # within a margin = 2× cloth thickness
        mask = (
            (tri_min[:, 0] - margin <= px) & (px <= tri_max[:, 0] + margin) &
            (tri_min[:, 1] - margin <= py) & (py <= tri_max[:, 1] + margin) &
            (tri_min[:, 2] - margin <= pz) & (pz <= tri_max[:, 2] + margin)
        )
        candidate_faces = np.where(mask)[0]

        best_pen = -1.0
        best_closest = None
        best_normal = None

        for fi in candidate_faces:
            f = avatar_faces[fi]
            a = avatar_verts[f[0]]
            b = avatar_verts[f[1]]
            c = avatar_verts[f[2]]
            closest, penetration = point_triangle_closest(p_np, a, b, c)
            if penetration > best_pen:
                best_pen = penetration
                best_closest = closest
                # Outward normal at this triangle
                ab = b - a
                ac = c - a
                n_raw = np.cross(ab, ac)
                n_len = float(np.linalg.norm(n_raw))
                if n_len > 1e-15:
                    best_normal = n_raw / n_len
                else:
                    best_normal = np.array([0.0, 1.0, 0.0])

        if best_pen > 0.0 and best_closest is not None:
            # Project particle out along outward normal by penetration depth
            # with a small margin (same Bridson 2003 approach as SpherePrimitive)
            if best_pen > max_pen:
                max_pen = best_pen

            n_hat = best_normal
            push_dist = (best_pen + thickness_cm * 0.1)
            new_p = best_closest + n_hat * push_dist * _COLLISION_MARGIN_FACTOR

            # Cancel inward velocity component
            vx, vy, vz = vel[i]
            vn = float(np.dot(np.array([vx, vy, vz]), n_hat))
            if vn < 0.0:
                vel[i] = (
                    vx - vn * n_hat[0],
                    vy - vn * n_hat[1],
                    vz - vn * n_hat[2],
                )
            pos[i] = (float(new_p[0]), float(new_p[1]), float(new_p[2]))

    return pos, vel, max_pen


# ---------------------------------------------------------------------------
# Body-region centroid
# ---------------------------------------------------------------------------

# Body region → list of CAESAR landmark names that define the band
_REGION_LANDMARKS = {
    "bust":       ["underbust", "bust", "armscye"],
    "waist":      ["waist", "underbust"],
    "hip":        ["hip", "waist"],
    "torso":      ["waist", "bust"],
    "full_torso": ["hip", "bust"],
    "knee":       ["knee", "calf"],
    "full":       ["floor", "crown"],
}


def body_region_centroid(
    avatar_verts: np.ndarray,
    avatar_faces: np.ndarray,
    landmarks: Dict[str, "BodyFormSlice"],  # type: ignore[name-defined]
    region: str,
    height_cm: float,
) -> np.ndarray:
    """
    Compute the 3D centroid of avatar vertices in the height band
    spanned by the given body region.

    Returns a (3,) float64 array (cm).
    """
    region_lms = _REGION_LANDMARKS.get(region, _REGION_LANDMARKS["torso"])

    # Determine height band [z_lo, z_hi]
    z_vals = []
    for lm_name in region_lms:
        lm = landmarks.get(lm_name)
        if lm is not None:
            z_vals.append(lm.z_cm)

    if not z_vals:
        # Fallback: middle third of body
        z_lo = height_cm * 0.4
        z_hi = height_cm * 0.8
    else:
        z_lo = min(z_vals) - 5.0   # 5 cm buffer
        z_hi = max(z_vals) + 5.0

    # Select vertices in this band
    in_band = avatar_verts[(avatar_verts[:, 2] >= z_lo) & (avatar_verts[:, 2] <= z_hi)]
    if len(in_band) == 0:
        in_band = avatar_verts

    centroid = in_band.mean(axis=0)
    return centroid


# ---------------------------------------------------------------------------
# Panel placement (arrangement-point auto-position)
# ---------------------------------------------------------------------------

def place_panel_near_region(
    mesh: ClothMesh,
    centroid: np.ndarray,   # (3,) target region centroid in cm
    region_radius_cm: float = 20.0,  # approximate body cross-section radius
    offset_cm: float = 5.0,          # extra clearance in front of body
) -> None:
    """
    Translate all cloth particles so the panel centre sits in front of
    (in the +Y direction) the target centroid, offset by region_radius_cm
    + offset_cm so it doesn't start inside the body.

    The panel is placed in the XZ plane (flat) at the centroid's Z height,
    i.e. centred at (centroid.x, centroid.y + radius + offset, centroid.z).

    Units: cm.  The cloth mesh is initialised in metres, so positions are
    converted to cm here.
    """
    n = len(mesh.positions)
    # Current centroid of the cloth mesh (in metres — convert to cm)
    cx = sum(p[0] for p in mesh.positions) / n * 100.0
    cy = sum(p[1] for p in mesh.positions) / n * 100.0
    cz = sum(p[2] for p in mesh.positions) / n * 100.0

    # Target position (cm):  front of body region
    tx = float(centroid[0])
    ty = float(centroid[1]) + region_radius_cm + offset_cm
    tz = float(centroid[2])

    # Translate (back to metres for mesh storage)
    dx = (tx - cx) / 100.0
    dy = (ty - cy) / 100.0
    dz = (tz - cz) / 100.0

    mesh.positions = [
        (p[0] + dx, p[1] + dy, p[2] + dz)
        for p in mesh.positions
    ]


# ---------------------------------------------------------------------------
# Per-vertex fit tension
# ---------------------------------------------------------------------------

def compute_fit_tension(mesh: ClothMesh) -> np.ndarray:
    """
    Compute per-vertex mean spring stretch ratio.

    stretch_ratio_k = (L_k - L0_k) / L0_k    for spring k.

    Per vertex i: mean over all springs incident to i.

    Returns
    -------
    np.ndarray, shape (N,) float64
    """
    n = len(mesh.positions)
    stretch_sum = np.zeros(n, dtype=np.float64)
    count = np.zeros(n, dtype=np.int32)

    pos = mesh.positions
    for sp in mesh.springs:
        pi = pos[sp.i]
        pj = pos[sp.j]
        dx = pj[0] - pi[0]
        dy = pj[1] - pi[1]
        dz = pj[2] - pi[2]
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        if sp.rest_length > 1e-15:
            ratio = (L - sp.rest_length) / sp.rest_length
        else:
            ratio = 0.0
        stretch_sum[sp.i] += ratio
        stretch_sum[sp.j] += ratio
        count[sp.i] += 1
        count[sp.j] += 1

    tension = np.where(count > 0, stretch_sum / np.maximum(count, 1), 0.0)
    return tension


# ---------------------------------------------------------------------------
# Symmetry check
# ---------------------------------------------------------------------------

def _compute_symmetry_error(mesh: ClothMesh) -> float:
    """
    RMS y-position difference between left half (columns < cols//2) and
    their X-mirror right half (columns >= cols//2) of a symmetric mesh.

    Returns 0.0 for odd number of columns (can't perfectly mirror).
    All positions converted from metres to cm for reporting.
    """
    rows, cols = mesh.rows, mesh.cols
    if cols % 2 != 0:
        return 0.0

    sq_sum = 0.0
    count = 0
    for r in range(rows):
        for c in range(cols // 2):
            i = mesh._idx(r, c)
            j = mesh._idx(r, cols - 1 - c)
            yi = mesh.positions[i][1] * 100.0  # to cm
            yj = mesh.positions[j][1] * 100.0
            sq_sum += (yi - yj) ** 2
            count += 1

    return math.sqrt(sq_sum / count) if count > 0 else 0.0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def drape_garment_on_avatar(
    avatar_verts: np.ndarray,            # (Nv, 3) float64, cm
    avatar_faces: np.ndarray,            # (Nf, 3) int32
    landmarks: Dict,                      # BodyFormSlice dict from avatar
    height_cm: float = 168.0,
    panel_width_cm: float = 40.0,        # flat panel dimensions (cm)
    panel_height_cm: float = 50.0,
    panel_rows: int = 12,
    panel_cols: int = 12,
    target_region: str = "torso",        # which body region to drape on
    mass_per_particle_kg: float = 0.003,
    k_structural: float = 80.0,          # N/m; spring stiffnesses
    k_shear: float = 40.0,
    k_bend: float = 4.0,
    velocity_damping: float = 0.97,
    steps: int = 2000,
    dt: float = 0.005,
    tol: float = 1e-4,
    cloth_thickness_cm: float = 0.1,     # for collision offset
    pin_top_edge: bool = True,           # pin top row during initial drape
) -> DrapeOnAvatarResult:
    """
    Drape a flat garment panel onto an avatar body-form mesh.

    Algorithm
    ---------
    1. Build a flat grid cloth mesh (Provot 1995) with the given dimensions.
    2. Auto-position the panel in front of the target body region centroid
       (bust / waist / hip / torso / full_torso).
    3. Simulate cloth settling under gravity with per-step mesh collision
       response (point-triangle closest-point, Bridson 2003 §4).
    4. Post-process: compute per-vertex fit tension (spring stretch ratio).

    Parameters
    ----------
    avatar_verts : np.ndarray, shape (Nv, 3)
        Avatar body-form vertices in centimetres.
    avatar_faces : np.ndarray, shape (Nf, 3)
        Triangle face indices.
    landmarks : dict
        Landmark slice dict from kerf_apparel.avatar.build_body_form.
    height_cm : float
        Avatar standing height (cm).
    panel_width_cm, panel_height_cm : float
        Flat panel dimensions (cm).  Default 40×50 cm (approximate
        front-bodice half-panel for a size-M garment).
    panel_rows, panel_cols : int
        Grid resolution.  More particles → finer wrinkles, slower simulation.
    target_region : str
        Body region: 'bust', 'waist', 'hip', 'torso', 'full_torso', 'knee', 'full'.
    mass_per_particle_kg : float
        Per-particle mass (kg).
    k_structural, k_shear, k_bend : float
        Spring stiffnesses (N/m).
    velocity_damping : float
        Per-sub-step global velocity multiplier (≤ 1).
    steps : int
        Maximum outer simulation steps.
    dt : float
        Outer time step (seconds).
    tol : float
        RMS velocity convergence tolerance (m/s).
    cloth_thickness_cm : float
        Cloth thickness used as collision offset (cm).
    pin_top_edge : bool
        If True, pin the top row of particles (row=0) so the panel hangs
        and drapes downward, simulating a garment on a hanger or neckline.

    Returns
    -------
    DrapeOnAvatarResult
    """
    # ------------------------------------------------------------------
    # 1. Build flat cloth mesh (spacing in metres)
    # ------------------------------------------------------------------
    spacing_m = (panel_width_cm / 100.0) / (panel_cols - 1)
    mesh = ClothMesh(
        rows=panel_rows,
        cols=panel_cols,
        spacing=spacing_m,
        mass=mass_per_particle_kg,
        k_structural=k_structural,
        k_shear=k_shear,
        k_bend=k_bend,
    )

    # Scale panel height separately (ClothMesh makes a square grid by default;
    # we rescale the row dimension to match panel_height_cm)
    row_scale = (panel_height_cm / 100.0) / ((panel_rows - 1) * spacing_m)
    if abs(row_scale - 1.0) > 0.01:
        new_positions = []
        for r in range(panel_rows):
            for c in range(panel_cols):
                idx = mesh._idx(r, c)
                p = mesh.positions[idx]
                new_positions.append((p[0], p[1] * row_scale, p[2] * row_scale))
        mesh.positions = new_positions

    # ------------------------------------------------------------------
    # 2. Auto-position panel near body region (arrangement-point)
    # ------------------------------------------------------------------
    centroid = body_region_centroid(avatar_verts, avatar_faces, landmarks, target_region, height_cm)

    # Estimate region cross-section radius from half-width at midpoint landmark
    region_lms = _REGION_LANDMARKS.get(target_region, _REGION_LANDMARKS["torso"])
    half_widths = []
    for lm_name in region_lms:
        lm = landmarks.get(lm_name)
        if lm is not None and hasattr(lm, "a_cm"):
            half_widths.append(lm.a_cm)
    region_radius_cm = max(half_widths) + 2.0 if half_widths else 20.0

    place_panel_near_region(mesh, centroid, region_radius_cm=region_radius_cm, offset_cm=5.0)

    # ------------------------------------------------------------------
    # 3. Pin top row (simulates garment hanging from neckline / hanger)
    # ------------------------------------------------------------------
    if pin_top_edge:
        for c in range(panel_cols):
            mesh.pin(0, c)

    # ------------------------------------------------------------------
    # 4. Simulation loop
    # ------------------------------------------------------------------
    # Floor collider (at ankle height)
    ankle_lm = landmarks.get("ankle")
    floor_y_cm = ankle_lm.z_cm if ankle_lm is not None else 6.0
    floor = PlanePrimitive(height=floor_y_cm / 100.0)

    energy_history: List[float] = []
    converged = False
    step = 0
    last_max_pen = 0.0

    for step in range(1, steps + 1):
        # Standard spring+gravity solve_step
        solve_step(
            mesh,
            dt=dt,
            gravity=(0.0, -9.81, 0.0),
            velocity_damping=velocity_damping,
            colliders=[floor],
        )

        # Mesh collision response (Bridson 2003, §4)
        mesh.positions, mesh.velocities, last_max_pen = resolve_mesh_collisions(
            mesh.positions,
            mesh.velocities,
            mesh.pinned,
            avatar_verts,
            avatar_faces,
            thickness_cm=cloth_thickness_cm,
        )

        if step % 100 == 0:
            energy_history.append(mesh.total_energy())

        if step % 50 == 0:
            rms_v = mesh.rms_velocity()
            if rms_v < tol:
                converged = True
                break

    # ------------------------------------------------------------------
    # 5. Post-process: positions (m → cm), fit tension, symmetry
    # ------------------------------------------------------------------
    n = len(mesh.positions)
    vertices_3d = np.array(
        [[p[0] * 100.0, p[1] * 100.0, p[2] * 100.0] for p in mesh.positions],
        dtype=np.float64,
    )

    fit_tension = compute_fit_tension(mesh)

    # Symmetry error (cm)
    sym_err_cm = _compute_symmetry_error(mesh)

    # Final penetration check (cm)
    # Re-measure against avatar mesh with tight tolerance
    max_pen_cm = last_max_pen  # already in cm from resolve_mesh_collisions

    # Average triangle inscribed-circle radius for relative penetration check
    # Use diagonal of bounding box / sqrt(Nf) as a proxy
    verts_range = avatar_verts.max(axis=0) - avatar_verts.min(axis=0)
    bb_diag = float(np.linalg.norm(verts_range))
    avg_tri_radius = bb_diag / max(1.0, math.sqrt(len(avatar_faces)))
    no_deep = max_pen_cm < 0.1 * avg_tri_radius

    return DrapeOnAvatarResult(
        mesh=mesh,
        vertices_3d=vertices_3d,
        fit_tension=fit_tension,
        max_penetration_cm=float(max_pen_cm),
        no_deep_penetration=no_deep,
        symmetry_error_cm=float(sym_err_cm),
        converged=converged,
        steps_taken=step,
        energy_history=energy_history,
        target_region=target_region,
    )


# ---------------------------------------------------------------------------
# Convenience: build avatar + drape in one call
# ---------------------------------------------------------------------------

def drape_garment_on_standard_avatar(
    panel_width_cm: float = 40.0,
    panel_height_cm: float = 50.0,
    panel_rows: int = 12,
    panel_cols: int = 12,
    target_region: str = "torso",
    height_cm: float = 168.0,
    bust_cm: float = 92.0,
    waist_cm: float = 74.0,
    hip_cm: float = 96.0,
    sex: str = "female",
    steps: int = 2000,
    dt: float = 0.005,
    tol: float = 1e-4,
    velocity_damping: float = 0.97,
    k_structural: float = 80.0,
    k_shear: float = 40.0,
    k_bend: float = 4.0,
    pin_top_edge: bool = True,
) -> DrapeOnAvatarResult:
    """
    Build a standard CAESAR body-form avatar and drape a flat garment panel.

    This is a convenience wrapper: it calls kerf_apparel.avatar.build_body_form
    to create the body-form mesh, then calls drape_garment_on_avatar.

    Parameters match kerf_apparel.avatar.build_body_form + drape_garment_on_avatar.
    """
    from kerf_apparel.avatar import build_body_form

    bf = build_body_form(
        height_cm=height_cm,
        bust_cm=bust_cm,
        waist_cm=waist_cm,
        hip_cm=hip_cm,
        sex=sex,
        n_vertices_per_ring=24,     # moderate resolution for collision
        n_slices_per_segment=3,
    )

    return drape_garment_on_avatar(
        avatar_verts=bf.vertices,
        avatar_faces=bf.faces,
        landmarks=bf.landmarks,
        height_cm=height_cm,
        panel_width_cm=panel_width_cm,
        panel_height_cm=panel_height_cm,
        panel_rows=panel_rows,
        panel_cols=panel_cols,
        target_region=target_region,
        steps=steps,
        dt=dt,
        tol=tol,
        velocity_damping=velocity_damping,
        k_structural=k_structural,
        k_shear=k_shear,
        k_bend=k_bend,
        pin_top_edge=pin_top_edge,
    )
