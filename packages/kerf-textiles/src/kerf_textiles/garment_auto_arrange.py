"""
kerf_textiles.garment_auto_arrange
===================================
Automatic multi-panel garment arrangement around a parametric avatar, followed
by mass-spring cloth drape with seam-endpoint proximity constraints.

Concept
-------
Given a set of 2D garment panels (each specified by a bounding-box + label),
a set of seam/stitch definitions (pairs of panel edges that should be sewn),
and an avatar body form:

  1. **Body-zone classification** — map each panel to a body zone (front-torso,
     back-torso, left-sleeve, right-sleeve, left-leg, right-leg, …) by examining
     the panel label.  Zone centroids are computed from the avatar landmark slices
     using `body_region_centroid` from garment_drape.

  2. **Arrangement-point placement** — position every panel in 3D space around
     the avatar at an appropriate orientation and offset radius so that no panel
     starts inside the body surface.  Front panels face +Y, back panels face -Y,
     sleeves face ±X, leg panels face ±X lower body.  The panels are placed at
     the body zone centroid ± the cross-section half-width + clearance offset.

  3. **Seam proximity** — for each stitch definition, move the stitched edge
     endpoints of the two panels toward each other (spring-like attraction) at
     the start of simulation so that the seam is "connected" before gravity
     settles the garment.  This replicates the "Sew" step in Marvelous Designer.

  4. **Drape** — feed the arranged panels into the existing mass-spring solver
     (`garment_drape.drape_garment_on_avatar`) for each panel independently, with
     avatar mesh collision.  (Full multi-panel simultaneous cloth sim with inter-
     panel collision is out of scope — each panel settles independently on the
     avatar surface; the seam attract is a pre-sim nudge.)

  5. **Result** — return per-panel 3D transforms (translation + rotation),
     initial 3D positions before sim, and final draped vertex positions.

Panel zones and mapping
-----------------------
The panel label is matched (case-insensitive substring) against:

  front_bodice / front / bodice_front   -> zone "front_torso"
  back_bodice  / back  / bodice_back    -> zone "back_torso"
  sleeve / left_sleeve                  -> zone "left_sleeve"
  right_sleeve                          -> zone "right_sleeve"
  skirt_front  / skirt                  -> zone "skirt_front"
  skirt_back                            -> zone "skirt_back"
  trouser_front / pant_front / leg_f   -> zone "left_leg_front"
  trouser_back  / pant_back  / leg_b   -> zone "left_leg_back"
  collar / neckband                     -> zone "front_torso"   (high bust band)
  cuff                                  -> zone "left_sleeve"

Avatar coordinate system
------------------------
X = lateral (left/right), Y = front/back depth, Z = height (up).
All units in centimetres.

References
----------
Bridson, R. et al. (2003). "Simulation of clothing with folds and wrinkles."
  SCA '03.  (cloth collision response)
House, D. & Breen, D. (2000). "Cloth Modeling and Animation."  (panel arrangement)
Volino, P. & Magnenat-Thalmann, N. (2000). "Virtual Clothing."  (seam assembly)
Robinette, K. et al. (2002). CAESAR Final Report.  (body proportions)

Public API
----------
GarmentPanel            -- input panel specification
SeamDefinition          -- stitch between two panel edges
ArrangedPanel           -- output for one panel (transform + positions)
GarmentAutoArrangeResult -- full output
garment_auto_arrange    -- main entry point
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_textiles.garment_drape import (
    body_region_centroid,
    resolve_mesh_collisions,
    compute_fit_tension,
    DrapeOnAvatarResult,
    _REGION_LANDMARKS,
)
from kerf_textiles.mass_spring import ClothMesh


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GarmentPanel:
    """
    A single 2D garment panel to be placed around the avatar.

    Attributes
    ----------
    label : str
        Human label, e.g. "front_bodice", "back_bodice", "left_sleeve".
        Used for zone classification.
    width_cm : float
        Panel width in centimetres (horizontal dimension in 2D).
    height_cm : float
        Panel height in centimetres (vertical dimension in 2D).
    rows : int
        Cloth mesh grid rows (more = finer simulation). Default 8.
    cols : int
        Cloth mesh grid cols. Default 8.
    """
    label: str
    width_cm: float
    height_cm: float
    rows: int = 8
    cols: int = 8


@dataclass
class SeamDefinition:
    """
    A sewing seam connecting an edge of one panel to an edge of another.

    Attributes
    ----------
    panel_a : str
        Label of the first panel.
    edge_a : str
        Which edge of panel A is sewn: 'top', 'bottom', 'left', 'right'.
    panel_b : str
        Label of the second panel.
    edge_b : str
        Which edge of panel B is sewn: 'top', 'bottom', 'left', 'right'.
    """
    panel_a: str
    edge_a: str
    panel_b: str
    edge_b: str


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ArrangedPanel:
    """
    A panel after auto-arrangement (before and after drape).

    Attributes
    ----------
    label : str
        Panel label (matches input GarmentPanel.label).
    zone : str
        Body zone the panel was assigned to.
    translation_cm : np.ndarray, shape (3,)
        3D translation applied to place the panel (cm).
    rotation_euler_deg : np.ndarray, shape (3,)
        Euler angles (Rx, Ry, Rz) in degrees describing panel orientation.
    initial_positions_cm : np.ndarray, shape (N, 3)
        Panel particle positions BEFORE drape simulation (arranged, cm).
    draped_positions_cm : np.ndarray, shape (N, 3)
        Panel particle positions AFTER drape simulation (settled, cm).
    fit_tension : np.ndarray, shape (N,)
        Per-vertex spring stretch ratio after drape.
    no_deep_penetration : bool
        True if settled panel has no deep penetration into avatar.
    max_penetration_cm : float
        Maximum penetration depth after drape (cm).
    drape_converged : bool
        True if drape simulation converged.
    drape_steps_taken : int
        Steps taken in drape simulation.
    energy_history : list[float]
        Drape energy samples (for convergence check).
    rows : int
    cols : int
    """
    label: str
    zone: str
    translation_cm: np.ndarray
    rotation_euler_deg: np.ndarray
    initial_positions_cm: np.ndarray
    draped_positions_cm: np.ndarray
    fit_tension: np.ndarray
    no_deep_penetration: bool
    max_penetration_cm: float
    drape_converged: bool
    drape_steps_taken: int
    energy_history: List[float]
    rows: int
    cols: int


@dataclass
class GarmentAutoArrangeResult:
    """
    Full output of :func:`garment_auto_arrange`.

    Attributes
    ----------
    panels : list[ArrangedPanel]
        One entry per input GarmentPanel, in input order.
    seam_proximity_met : list[bool]
        One entry per SeamDefinition: True if the stitched edge endpoints
        were brought within seam_proximity_tol_cm of each other BEFORE drape.
    avatar_height_cm : float
    bust_cm, waist_cm, hip_cm : float
    n_avatar_verts : int
    n_avatar_faces : int
    """
    panels: List[ArrangedPanel]
    seam_proximity_met: List[bool]
    avatar_height_cm: float
    bust_cm: float
    waist_cm: float
    hip_cm: float
    n_avatar_verts: int
    n_avatar_faces: int


# ---------------------------------------------------------------------------
# Zone classification
# ---------------------------------------------------------------------------

# Maps body zone -> kerf_textiles.garment_drape region key + side offset sign
# (x_sign, y_sign): X=lateral offset sign, Y=front/back sign
_ZONE_MAP: Dict[str, Tuple[str, float, float]] = {
    "front_torso":      ("torso",      0.0,  1.0),
    "back_torso":       ("torso",      0.0, -1.0),
    "left_sleeve":      ("bust",      -1.0,  0.0),
    "right_sleeve":     ("bust",       1.0,  0.0),
    "skirt_front":      ("hip",        0.0,  1.0),
    "skirt_back":       ("hip",        0.0, -1.0),
    "left_leg_front":   ("knee",      -0.5,  1.0),
    "left_leg_back":    ("knee",      -0.5, -1.0),
    "right_leg_front":  ("knee",       0.5,  1.0),
    "right_leg_back":   ("knee",       0.5, -1.0),
}


def _classify_panel_zone(label: str) -> str:
    """
    Map a panel label to one of the known body zones.

    Matching rules (first match wins, case-insensitive):
      right_sleeve / rsleeve               -> right_sleeve
      left_sleeve  / lsleeve / sleeve      -> left_sleeve
      skirt_back   / skirt_b               -> skirt_back
      skirt_front  / skirt                 -> skirt_front
      right_leg / pant_right / trouser_r   -> right_leg_front
      left_leg  / pant_left  / trouser_l   -> left_leg_front
      trouser_back / pant_back / leg_b     -> left_leg_back
      back  / bodice_back  / back_bodice   -> back_torso
      front / bodice_front / front_bodice  -> front_torso

    Falls back to "front_torso" if nothing matches.
    """
    lo = label.lower()

    if any(k in lo for k in ("right_sleeve", "rsleeve")):
        return "right_sleeve"
    if any(k in lo for k in ("left_sleeve", "lsleeve", "sleeve")):
        return "left_sleeve"
    if any(k in lo for k in ("skirt_back", "skirt_b")):
        return "skirt_back"
    if any(k in lo for k in ("skirt_front", "skirt")):
        return "skirt_front"
    if any(k in lo for k in ("right_leg", "pant_right", "trouser_right", "leg_r")):
        return "right_leg_front"
    if any(k in lo for k in ("left_leg", "pant_left", "trouser_left", "leg_l")):
        return "left_leg_front"
    if any(k in lo for k in ("trouser_back", "pant_back", "leg_back", "leg_b")):
        return "left_leg_back"
    if any(k in lo for k in ("back_bodice", "bodice_back", "back")):
        return "back_torso"
    if any(k in lo for k in ("front_bodice", "bodice_front", "front",
                              "collar", "cuff", "neckband")):
        return "front_torso"
    return "front_torso"


# ---------------------------------------------------------------------------
# Zone -> drape region / placement
# ---------------------------------------------------------------------------

# Map zone to kerf avatar region key
_DRAPE_REGION_MAP: Dict[str, str] = {
    "front_torso":    "torso",
    "back_torso":     "torso",
    "left_sleeve":    "bust",
    "right_sleeve":   "bust",
    "skirt_front":    "hip",
    "skirt_back":     "hip",
    "left_leg_front": "knee",
    "left_leg_back":  "knee",
    "right_leg_front": "knee",
    "right_leg_back":  "knee",
}

# Euler rotation (degrees) applied to each zone's panel so the cloth
# faces the correct outward direction from the body.
# Convention: Rz = yaw around vertical axis.
_ZONE_ROTATION_DEG: Dict[str, np.ndarray] = {
    "front_torso":    np.array([0.0,   0.0,   0.0]),
    "back_torso":     np.array([0.0,   0.0, 180.0]),
    "left_sleeve":    np.array([0.0,   0.0,  90.0]),
    "right_sleeve":   np.array([0.0,   0.0, -90.0]),
    "skirt_front":    np.array([0.0,   0.0,   0.0]),
    "skirt_back":     np.array([0.0,   0.0, 180.0]),
    "left_leg_front": np.array([0.0,   0.0,  30.0]),
    "left_leg_back":  np.array([0.0,   0.0, 150.0]),
    "right_leg_front":np.array([0.0,   0.0, -30.0]),
    "right_leg_back": np.array([0.0,   0.0,-150.0]),
}


# ---------------------------------------------------------------------------
# Panel edge particle indices
# ---------------------------------------------------------------------------

def _edge_indices(mesh: ClothMesh, edge: str) -> List[int]:
    """
    Return the list of particle indices along the named edge of the cloth grid.

    edge: 'top' (row=0), 'bottom' (row=rows-1), 'left' (col=0), 'right' (col=cols-1)
    """
    rows, cols = mesh.rows, mesh.cols
    if edge == "top":
        return [mesh._idx(0, c) for c in range(cols)]
    elif edge == "bottom":
        return [mesh._idx(rows - 1, c) for c in range(cols)]
    elif edge == "left":
        return [mesh._idx(r, 0) for r in range(rows)]
    elif edge == "right":
        return [mesh._idx(r, cols - 1) for r in range(rows)]
    else:
        return []


def _edge_centroid(mesh: ClothMesh, edge: str) -> np.ndarray:
    """Return the centroid (m -> cm) of the named edge of the cloth mesh."""
    idxs = _edge_indices(mesh, edge)
    if not idxs:
        return np.zeros(3)
    pts = np.array([mesh.positions[i] for i in idxs]) * 100.0  # m -> cm
    return pts.mean(axis=0)


# ---------------------------------------------------------------------------
# Panel initial placement
# ---------------------------------------------------------------------------

def _build_cloth_mesh(panel: GarmentPanel, k_structural: float = 80.0,
                      k_shear: float = 40.0, k_bend: float = 4.0) -> ClothMesh:
    """Build a flat ClothMesh for the given panel dimensions."""
    spacing_m = (panel.width_cm / 100.0) / max(panel.cols - 1, 1)
    mesh = ClothMesh(
        rows=panel.rows,
        cols=panel.cols,
        spacing=spacing_m,
        mass=0.003,
        k_structural=k_structural,
        k_shear=k_shear,
        k_bend=k_bend,
    )
    # Scale row dimension to match panel height
    row_scale = (panel.height_cm / 100.0) / max((panel.rows - 1) * spacing_m, 1e-9)
    if abs(row_scale - 1.0) > 0.01:
        mesh.positions = [
            (p[0], p[1] * row_scale, p[2] * row_scale)
            for p in mesh.positions
        ]
    return mesh


def _zone_placement(
    zone: str,
    zone_centroid_cm: np.ndarray,
    half_width_cm: float,
    half_height_cm: float,
    offset_cm: float = 5.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute the 3D translation and Euler rotation (deg) for a panel in the
    given zone so it is placed around the body at a safe outward offset.

    Returns
    -------
    translation_cm : np.ndarray (3,)
        Where to move the panel centroid in cm.
    rotation_deg : np.ndarray (3,)
        Euler (Rx, Ry, Rz) in degrees.
    """
    _, x_sign, y_sign = _ZONE_MAP.get(zone, _ZONE_MAP["front_torso"])

    # Lateral arm offset for sleeves: place at +/-(half_width_cm * 2) from centre
    x_offset = x_sign * (half_width_cm + offset_cm)
    y_offset = y_sign * (half_height_cm + offset_cm)

    tx = float(zone_centroid_cm[0]) + x_offset
    ty = float(zone_centroid_cm[1]) + y_offset
    tz = float(zone_centroid_cm[2])

    rot = _ZONE_ROTATION_DEG.get(zone, np.zeros(3)).copy()
    return np.array([tx, ty, tz], dtype=np.float64), rot


def _apply_placement_to_mesh(
    mesh: ClothMesh,
    target_cm: np.ndarray,
) -> None:
    """
    Translate all mesh particles so the cloth centroid is at target_cm.
    Positions are stored in metres; target_cm is in cm.
    """
    n = len(mesh.positions)
    cx = sum(p[0] for p in mesh.positions) / n * 100.0
    cy = sum(p[1] for p in mesh.positions) / n * 100.0
    cz = sum(p[2] for p in mesh.positions) / n * 100.0

    dx = (target_cm[0] - cx) / 100.0
    dy = (target_cm[1] - cy) / 100.0
    dz = (target_cm[2] - cz) / 100.0

    mesh.positions = [
        (p[0] + dx, p[1] + dy, p[2] + dz)
        for p in mesh.positions
    ]


# ---------------------------------------------------------------------------
# Seam proximity check and pre-sim attraction
# ---------------------------------------------------------------------------

def _seam_proximity_met(
    mesh_a: ClothMesh,
    edge_a: str,
    mesh_b: ClothMesh,
    edge_b: str,
    tol_cm: float = 15.0,
) -> bool:
    """
    Check whether the centroid of edge_a on mesh_a is within tol_cm of
    the centroid of edge_b on mesh_b (in cm).
    """
    ca = _edge_centroid(mesh_a, edge_a)
    cb = _edge_centroid(mesh_b, edge_b)
    dist = float(np.linalg.norm(ca - cb))
    return dist <= tol_cm


def _attract_seam_edges(
    mesh_a: ClothMesh,
    edge_a: str,
    mesh_b: ClothMesh,
    edge_b: str,
    blend: float = 0.4,
) -> None:
    """
    Move the particles on edge_a and edge_b toward each other (midpoint blend)
    to "sew" them together before simulation starts.

    blend=0.5 -> meet exactly at midpoint (full sew).
    blend=0.4 -> move 40% of the way toward midpoint (soft pre-attract).

    This operates in-place on both meshes (positions in metres).
    """
    idxs_a = _edge_indices(mesh_a, edge_a)
    idxs_b = _edge_indices(mesh_b, edge_b)

    if not idxs_a or not idxs_b:
        return

    # Pair corresponding endpoints by sorted index (one-to-one if same count,
    # else zip longest by repeating the last)
    max_len = max(len(idxs_a), len(idxs_b))

    def padded(lst, n):
        if not lst:
            return []
        return [lst[min(i, len(lst) - 1)] for i in range(n)]

    pa = padded(idxs_a, max_len)
    pb = padded(idxs_b, max_len)

    for ia, ib in zip(pa, pb):
        pos_a = np.array(mesh_a.positions[ia])
        pos_b = np.array(mesh_b.positions[ib])
        mid = (pos_a + pos_b) * 0.5
        new_a = pos_a + blend * (mid - pos_a)
        new_b = pos_b + blend * (mid - pos_b)
        mesh_a.positions[ia] = (float(new_a[0]), float(new_a[1]), float(new_a[2]))
        mesh_b.positions[ib] = (float(new_b[0]), float(new_b[1]), float(new_b[2]))


# ---------------------------------------------------------------------------
# Collision-free check (panels outside avatar at start)
# ---------------------------------------------------------------------------

def _panel_outside_avatar(
    mesh: ClothMesh,
    avatar_verts: np.ndarray,
    avatar_faces: np.ndarray,
    cloth_thickness_cm: float = 0.1,
) -> bool:
    """
    Return True if NO cloth particle deeply penetrates the avatar mesh.

    Uses resolve_mesh_collisions (Bridson 2003) with 1 step to detect
    initial penetrations. Returns True if max_penetration is near zero.
    """
    _, _, max_pen = resolve_mesh_collisions(
        list(mesh.positions),
        list(mesh.velocities),
        list(mesh.pinned),
        avatar_verts,
        avatar_faces,
        thickness_cm=cloth_thickness_cm,
    )
    # Avatar bounding box diagonal / sqrt(faces) as scale
    verts_range = avatar_verts.max(axis=0) - avatar_verts.min(axis=0)
    bb_diag = float(np.linalg.norm(verts_range))
    avg_tri_r = bb_diag / max(1.0, math.sqrt(len(avatar_faces)))
    return max_pen < 0.1 * avg_tri_r


# ---------------------------------------------------------------------------
# Energy decrease check
# ---------------------------------------------------------------------------

def energy_decreased(energy_history: List[float]) -> bool:
    """
    Return True if the drape energy decreased from beginning to end.
    Checks that the last sample is less than the first (monotone decrease
    is not required -- just a net reduction).
    """
    if len(energy_history) < 2:
        return True  # too few samples to assess
    return energy_history[-1] <= energy_history[0]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def garment_auto_arrange(
    panels: Sequence[GarmentPanel],
    seams: Sequence[SeamDefinition],
    avatar_verts: np.ndarray,          # (Nv, 3) float64, cm
    avatar_faces: np.ndarray,          # (Nf, 3) int32
    landmarks: Dict,                   # BodyFormSlice dict from avatar
    height_cm: float = 168.0,
    bust_cm: float = 92.0,
    waist_cm: float = 74.0,
    hip_cm: float = 96.0,
    offset_cm: float = 5.0,            # clearance offset from body surface
    seam_attract_blend: float = 0.4,   # pre-sim seam attraction strength
    seam_proximity_tol_cm: float = 15.0,
    drape_steps: int = 1200,
    drape_dt: float = 0.005,
    drape_tol: float = 1e-3,
    drape_velocity_damping: float = 0.97,
    k_structural: float = 80.0,
    k_shear: float = 40.0,
    k_bend: float = 4.0,
    cloth_thickness_cm: float = 0.1,
    pin_top_edge: bool = True,
) -> GarmentAutoArrangeResult:
    """
    Automatically arrange 2D garment panels around an avatar and drape them.

    Algorithm
    ---------
    1. For each panel, classify it to a body zone (front_torso, back_torso,
       left_sleeve, right_sleeve, skirt_front, ...) using the panel label.
    2. Compute the zone centroid from avatar landmarks.
    3. Place each panel in 3D at the zone centroid +/- radius + offset, oriented
       so the cloth faces outward from the body.
    4. For each seam definition, attract the two stitched edge endpoints toward
       each other by `seam_attract_blend` fraction.
    5. Drape each panel independently on the avatar using mass-spring simulation
       with mesh-triangle collision (Bridson 2003).
    6. Return per-panel transforms, initial and draped positions, tension fields,
       seam proximity flags, and drape convergence.

    Parameters
    ----------
    panels : list of GarmentPanel
    seams : list of SeamDefinition
    avatar_verts : np.ndarray, shape (Nv, 3), cm
    avatar_faces : np.ndarray, shape (Nf, 3)
    landmarks : dict
        Landmark dict from kerf_apparel.avatar.build_body_form.
    height_cm, bust_cm, waist_cm, hip_cm : float
        Avatar body measurements.
    offset_cm : float
        Extra clearance from body surface on panel placement.
    seam_attract_blend : float
        How far to move each seam edge toward the other (0=none, 0.5=midpoint).
    seam_proximity_tol_cm : float
        Tolerance for seam proximity check (cm). A seam is "met" if the two
        edge centroids are within this distance AFTER attraction.
    drape_steps, drape_dt, drape_tol, drape_velocity_damping : float
        Drape simulation parameters.
    k_structural, k_shear, k_bend : float
        Spring stiffnesses (N/m).
    cloth_thickness_cm : float
    pin_top_edge : bool
        If True, pin the top row of each panel (garment hangs from neckline).

    Returns
    -------
    GarmentAutoArrangeResult
    """
    from kerf_textiles.mass_spring import PlanePrimitive, solve_step

    # ------------------------------------------------------------------
    # 1. Build cloth meshes
    # ------------------------------------------------------------------
    meshes: Dict[str, ClothMesh] = {}
    for panel in panels:
        meshes[panel.label] = _build_cloth_mesh(
            panel, k_structural=k_structural, k_shear=k_shear, k_bend=k_bend
        )

    # ------------------------------------------------------------------
    # 2. Classify zones and compute centroids
    # ------------------------------------------------------------------
    zones: Dict[str, str] = {}
    zone_centroids: Dict[str, np.ndarray] = {}
    zone_half_widths: Dict[str, float] = {}

    for panel in panels:
        zone = _classify_panel_zone(panel.label)
        zones[panel.label] = zone

        # Drape region key for body_region_centroid
        drape_region = _DRAPE_REGION_MAP.get(zone, "torso")
        centroid = body_region_centroid(
            avatar_verts, avatar_faces, landmarks, drape_region, height_cm
        )
        zone_centroids[panel.label] = centroid

        # Estimate cross-section half-width from landmark semi-axes
        region_lms = _REGION_LANDMARKS.get(drape_region, _REGION_LANDMARKS["torso"])
        half_widths = []
        for lm_name in region_lms:
            lm = landmarks.get(lm_name)
            if lm is not None and hasattr(lm, "a_cm"):
                half_widths.append(lm.a_cm)
        zone_half_widths[panel.label] = max(half_widths) + 2.0 if half_widths else 20.0

    # ------------------------------------------------------------------
    # 3. Place panels at zone positions (arrangement-point auto-position)
    # ------------------------------------------------------------------
    translations: Dict[str, np.ndarray] = {}
    rotations: Dict[str, np.ndarray] = {}

    for panel in panels:
        zone = zones[panel.label]
        centroid = zone_centroids[panel.label]
        hw = zone_half_widths[panel.label]

        # Panel half-dimensions for placement offset
        ph = panel.height_cm / 2.0

        target_cm, rot_deg = _zone_placement(
            zone=zone,
            zone_centroid_cm=centroid,
            half_width_cm=hw,
            half_height_cm=ph,
            offset_cm=offset_cm,
        )

        translations[panel.label] = target_cm
        rotations[panel.label] = rot_deg

        _apply_placement_to_mesh(meshes[panel.label], target_cm)

    # ------------------------------------------------------------------
    # 4. Seam pre-attraction (sewing step)
    # ------------------------------------------------------------------
    seam_proximity_met: List[bool] = []

    for seam in seams:
        mesh_a = meshes.get(seam.panel_a)
        mesh_b = meshes.get(seam.panel_b)
        if mesh_a is None or mesh_b is None:
            seam_proximity_met.append(False)
            continue

        # Attract before checking proximity
        _attract_seam_edges(mesh_a, seam.edge_a, mesh_b, seam.edge_b,
                            blend=seam_attract_blend)

        # Check proximity after attraction
        met = _seam_proximity_met(mesh_a, seam.edge_a, mesh_b, seam.edge_b,
                                  tol_cm=seam_proximity_tol_cm)
        seam_proximity_met.append(met)

    # ------------------------------------------------------------------
    # 5. Capture initial positions before drape
    # ------------------------------------------------------------------
    initial_positions: Dict[str, np.ndarray] = {}
    for panel in panels:
        mesh = meshes[panel.label]
        initial_positions[panel.label] = np.array(
            [[p[0] * 100.0, p[1] * 100.0, p[2] * 100.0] for p in mesh.positions],
            dtype=np.float64,
        )

    # ------------------------------------------------------------------
    # 6. Drape each panel independently
    # ------------------------------------------------------------------
    # Floor at ankle height
    ankle_lm = landmarks.get("ankle")
    floor_y_cm = ankle_lm.z_cm if ankle_lm is not None else 6.0
    floor = PlanePrimitive(height=floor_y_cm / 100.0)

    arranged_panels: List[ArrangedPanel] = []

    for panel in panels:
        zone = zones[panel.label]
        drape_region = _DRAPE_REGION_MAP.get(zone, "torso")

        mesh = meshes[panel.label]

        # Pin top row
        if pin_top_edge:
            for c in range(mesh.cols):
                mesh.pin(0, c)

        energy_history: List[float] = []
        converged = False
        step = 0
        last_max_pen = 0.0

        for step in range(1, drape_steps + 1):
            solve_step(
                mesh,
                dt=drape_dt,
                gravity=(0.0, -9.81, 0.0),
                velocity_damping=drape_velocity_damping,
                colliders=[floor],
            )
            # Avatar mesh collision response (Bridson 2003)
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
                if rms_v < drape_tol:
                    converged = True
                    break

        # Post-process
        verts_3d = np.array(
            [[p[0] * 100.0, p[1] * 100.0, p[2] * 100.0] for p in mesh.positions],
            dtype=np.float64,
        )
        fit_tension = compute_fit_tension(mesh)

        # Penetration check
        verts_range = avatar_verts.max(axis=0) - avatar_verts.min(axis=0)
        bb_diag = float(np.linalg.norm(verts_range))
        avg_tri_r = bb_diag / max(1.0, math.sqrt(len(avatar_faces)))
        no_deep = last_max_pen < 0.1 * avg_tri_r

        arranged_panels.append(ArrangedPanel(
            label=panel.label,
            zone=zone,
            translation_cm=translations[panel.label],
            rotation_euler_deg=rotations[panel.label],
            initial_positions_cm=initial_positions[panel.label],
            draped_positions_cm=verts_3d,
            fit_tension=fit_tension,
            no_deep_penetration=no_deep,
            max_penetration_cm=float(last_max_pen),
            drape_converged=converged,
            drape_steps_taken=step,
            energy_history=energy_history,
            rows=panel.rows,
            cols=panel.cols,
        ))

    return GarmentAutoArrangeResult(
        panels=arranged_panels,
        seam_proximity_met=seam_proximity_met,
        avatar_height_cm=height_cm,
        bust_cm=bust_cm,
        waist_cm=waist_cm,
        hip_cm=hip_cm,
        n_avatar_verts=int(len(avatar_verts)),
        n_avatar_faces=int(len(avatar_faces)),
    )


# ---------------------------------------------------------------------------
# Convenience: build avatar + auto-arrange in one call
# ---------------------------------------------------------------------------

def garment_auto_arrange_on_standard_avatar(
    panels: Sequence[GarmentPanel],
    seams: Sequence[SeamDefinition],
    height_cm: float = 168.0,
    bust_cm: float = 92.0,
    waist_cm: float = 74.0,
    hip_cm: float = 96.0,
    sex: str = "female",
    offset_cm: float = 5.0,
    seam_attract_blend: float = 0.4,
    seam_proximity_tol_cm: float = 15.0,
    drape_steps: int = 1200,
    drape_dt: float = 0.005,
    drape_tol: float = 1e-3,
    drape_velocity_damping: float = 0.97,
    k_structural: float = 80.0,
    k_shear: float = 40.0,
    k_bend: float = 4.0,
    pin_top_edge: bool = True,
) -> GarmentAutoArrangeResult:
    """
    Build a standard CAESAR body-form avatar and auto-arrange + drape panels.

    Parameters
    ----------
    panels : list of GarmentPanel
    seams  : list of SeamDefinition
    height_cm, bust_cm, waist_cm, hip_cm, sex : float / str
        Avatar body measurements + sex.
    All remaining kwargs forwarded to :func:`garment_auto_arrange`.

    Returns
    -------
    GarmentAutoArrangeResult
    """
    from kerf_apparel.avatar import build_body_form

    bf = build_body_form(
        height_cm=height_cm,
        bust_cm=bust_cm,
        waist_cm=waist_cm,
        hip_cm=hip_cm,
        sex=sex,
        n_vertices_per_ring=24,
        n_slices_per_segment=3,
    )

    return garment_auto_arrange(
        panels=panels,
        seams=seams,
        avatar_verts=bf.vertices,
        avatar_faces=bf.faces,
        landmarks=bf.landmarks,
        height_cm=height_cm,
        bust_cm=bust_cm,
        waist_cm=waist_cm,
        hip_cm=hip_cm,
        offset_cm=offset_cm,
        seam_attract_blend=seam_attract_blend,
        seam_proximity_tol_cm=seam_proximity_tol_cm,
        drape_steps=drape_steps,
        drape_dt=drape_dt,
        drape_tol=drape_tol,
        drape_velocity_damping=drape_velocity_damping,
        k_structural=k_structural,
        k_shear=k_shear,
        k_bend=k_bend,
        pin_top_edge=pin_top_edge,
    )
