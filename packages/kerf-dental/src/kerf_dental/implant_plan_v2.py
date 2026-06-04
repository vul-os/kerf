"""
kerf_dental.implant_plan_v2 — Extended implant planning with brand specs,
prosthetic-driven placement, and primary stability estimation.

References
----------
- Misch CE (2014). Contemporary Implant Dentistry, 3rd ed. Ch 5, §22.
- ITI Treatment Guide Vol 1 (Bone Augmentation Procedures).
- Turkyilmaz I et al. (2007). "The relationship between insertion torque and
  ISQ values for Straumann Bone-Level implants." Clin Implant Dent 9:S9-14.

DISCLAIMER
----------
NOT FDA-cleared or CE-marked as a medical device. All plans require review
by a qualified dental clinician.

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from kerf_dental.crown_bridge import ToothNumber


# ---------------------------------------------------------------------------
# Implant brand catalogue
# ---------------------------------------------------------------------------

@dataclass
class ImplantSpec:
    """Standard implant system specification."""

    brand: str
    """'Straumann BLT' | 'NobelActive' | 'Astra EV' | 'Generic'"""

    diameter_mm: float
    """Implant body diameter (mm). Typical 3.3–6.0 mm."""

    length_mm: float
    """Implant body length (mm). Typical 6–16 mm."""

    platform: str
    """Connection platform code.
    Straumann: 'NC' | 'RC' | 'WC'
    Nobel: 'NP' | 'RP' | 'WP'
    Astra: 'S' | 'R'
    """

    def __post_init__(self):
        if self.diameter_mm <= 0 or self.length_mm <= 0:
            raise ValueError("diameter_mm and length_mm must be positive")


@dataclass
class ImplantPosition:
    """3D placement of the implant in jaw coordinates."""

    fixture_tip: np.ndarray
    """(3,) apical end of implant."""

    platform_position: np.ndarray
    """(3,) coronal platform."""

    axis_direction: np.ndarray
    """(3,) unit vector apical → coronal."""

    angulation_deg: tuple[float, float]
    """(mesial-distal, buccal-lingual) angulation in degrees."""

    def __post_init__(self):
        self.fixture_tip = np.asarray(self.fixture_tip, dtype=float)
        self.platform_position = np.asarray(self.platform_position, dtype=float)
        self.axis_direction = np.asarray(self.axis_direction, dtype=float)
        norm = np.linalg.norm(self.axis_direction)
        if norm > 1e-9:
            self.axis_direction = self.axis_direction / norm


@dataclass
class ImplantPlan:
    """Complete implant plan with placement, bone quality, and safety metrics."""

    tooth_position: ToothNumber
    implant: ImplantSpec
    position: ImplantPosition
    bone_density_HU: float
    """Hounsfield Units from CBCT in the planned region."""

    distance_to_nerve_mm: float
    """Minimum distance from implant trajectory to mandibular nerve (mm).
    Use 999.0 if no nerve data available."""

    distance_to_sinus_mm: float
    """Minimum distance from implant tip to sinus floor (mm).
    Use 999.0 if not applicable."""

    is_prosthetic_driven: bool
    """True if position was derived from crown emergence target."""

    insertion_torque_estimate_n_cm: float
    """Estimated insertion torque (Ncm). Derived from bone density per Misch Ch 5."""

    primary_stability_score: int
    """Implant stability quotient estimate (ISQ-like) 1–10.
    Based on Turkyilmaz et al. (2007) insertion torque–ISQ correlation."""

    honest_caveat: str = (
        "EDUCATIONAL/PLANNING ONLY: Primary stability and torque estimates "
        "are derived from HU-based density models (Misch 2014 Ch 5). "
        "Clinical outcome depends on surgical technique, bone morphology, "
        "and patient factors. NOT FDA-cleared or CE-marked as a medical device."
    )


# ---------------------------------------------------------------------------
# Bone density → torque/stability mapping (Misch 2014 Ch 5)
# ---------------------------------------------------------------------------

def _hu_to_torque(mean_hu: float) -> float:
    """
    Estimate insertion torque (Ncm) from mean HU.

    Based on Misch 2014 Ch 5 bone density-torque relationship:
    - D1 (> 1250 HU): 45–50 Ncm
    - D2 (850–1250 HU): 35–45 Ncm
    - D3 (350–849 HU): 20–35 Ncm
    - D4 (150–349 HU): 10–20 Ncm
    - D4- (< 150 HU): < 10 Ncm
    """
    if mean_hu > 1250:
        return 48.0
    elif mean_hu >= 850:
        return 40.0 + (mean_hu - 850) / (1250 - 850) * 8.0
    elif mean_hu >= 350:
        return 20.0 + (mean_hu - 350) / (850 - 350) * 15.0
    elif mean_hu >= 150:
        return 10.0 + (mean_hu - 150) / (350 - 150) * 10.0
    else:
        return max(5.0, mean_hu / 150.0 * 10.0)


def _torque_to_stability_score(torque_ncm: float) -> int:
    """
    Convert insertion torque to stability score 1–10.

    Reference: Turkyilmaz et al. (2007) ISQ = 57.4 + 0.7 × torque (linear fit).
    Normalise ISQ 50–80 → score 1–10.
    """
    isq = 57.4 + 0.7 * torque_ncm  # approximate linear fit
    isq = max(50.0, min(85.0, isq))
    score = int(round((isq - 50.0) / (85.0 - 50.0) * 9.0 + 1.0))
    return max(1, min(10, score))


def _compute_region_hu(
    cbct_volume_hu: np.ndarray,
    tip: np.ndarray,
    axis: np.ndarray,
    length_mm: float,
    voxel_spacing_mm: tuple[float, float, float] = (0.4, 0.4, 0.4),
    n_samples: int = 40,
) -> float:
    """Sample HU along implant trajectory and return mean."""
    entry = tip + axis * length_mm  # platform
    exit_ = tip                      # apex

    ts = np.linspace(0.0, 1.0, n_samples)
    pts = entry[np.newaxis, :] + ts[:, np.newaxis] * (exit_ - entry)[np.newaxis, :]

    sx, sy, sz = voxel_spacing_mm
    nz, ny, nx = cbct_volume_hu.shape

    ix = np.round(pts[:, 0] / sx).astype(int)
    iy = np.round(pts[:, 1] / sy).astype(int)
    iz = np.round(pts[:, 2] / sz).astype(int)

    valid = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny) & (iz >= 0) & (iz < nz)
    hu = np.zeros(n_samples, dtype=float)
    hu[valid] = cbct_volume_hu[iz[valid], iy[valid], ix[valid]]
    n_valid = int(valid.sum())
    return float(hu[valid].mean()) if n_valid > 0 else 0.0


def _select_implant_size(
    available_bone_mm: float,
    width_available_mm: float,
    bone_hu: float,
    brand: str = "Straumann BLT",
) -> ImplantSpec:
    """
    Auto-select implant size: longest/widest that respects safety margins.

    Reference: ITI Treatment Guide Vol 1 — minimum 1 mm clearance all around.
    """
    # Available length = bone height minus safety margins
    safe_length = max(6.0, available_bone_mm - 2.0)
    # Available diameter = ridge width minus 1.5 mm each side
    safe_diam = max(3.3, width_available_mm - 3.0)

    # Standard lengths (mm) for Straumann BLT
    if brand == "Straumann BLT":
        lengths = [16.0, 14.0, 12.0, 10.0, 8.0, 6.0]
        diameters = [4.8, 4.1, 3.3]
        platforms = {4.8: "WC", 4.1: "RC", 3.3: "NC"}
    elif brand == "NobelActive":
        lengths = [15.0, 13.0, 11.5, 10.0, 8.5]
        diameters = [5.0, 4.3, 3.5]
        platforms = {5.0: "WP", 4.3: "RP", 3.5: "NP"}
    else:
        lengths = [14.0, 12.0, 10.0, 8.0]
        diameters = [4.5, 4.0, 3.5]
        platforms = {4.5: "R", 4.0: "R", 3.5: "S"}

    chosen_length = lengths[0]
    for l in lengths:
        if l <= safe_length:
            chosen_length = l
            break

    chosen_diam = diameters[0]
    for d in diameters:
        if d <= safe_diam:
            chosen_diam = d
            break

    return ImplantSpec(
        brand=brand,
        diameter_mm=chosen_diam,
        length_mm=chosen_length,
        platform=platforms.get(chosen_diam, "RC"),
    )


def assess_bone_density(
    cbct_volume_hu: np.ndarray,
    region_bbox: tuple,
) -> dict:
    """
    Misch classification D1-D4 from average HU within bounding box region.

    Reference: Misch CE (1990). "Bone classification: training the clinician
    for treatment approaches." Implant Dent 1990;(10):6-11.

    Parameters
    ----------
    cbct_volume_hu : ndarray (nz, ny, nx)
    region_bbox : ((x0,y0,z0), (x1,y1,z1)) in mm, or voxel indices

    Returns
    -------
    dict with keys: classification, mean_hu, min_hu, max_hu, std_hu
    """
    vol = np.asarray(cbct_volume_hu, dtype=float)

    if isinstance(region_bbox, tuple) and len(region_bbox) == 2:
        # Interpret as voxel slices or mm coords (use as integer voxel bbox)
        lo = np.asarray(region_bbox[0], dtype=int)
        hi = np.asarray(region_bbox[1], dtype=int)
        nz, ny, nx = vol.shape
        x0, y0, z0 = np.clip(lo, 0, [nx, ny, nz] - np.ones(3, int))
        x1, y1, z1 = np.clip(hi, 0, [nx, ny, nz])
        region = vol[int(z0):int(z1), int(y0):int(y1), int(x0):int(x1)]
    else:
        region = vol

    if region.size == 0:
        region = vol

    mean_hu = float(region.mean())
    min_hu = float(region.min())
    max_hu = float(region.max())
    std_hu = float(region.std())

    # Misch classification
    if mean_hu > 1250:
        classification = "D1"
        description = "Cortical bone (mandibular symphysis anterior)"
    elif mean_hu >= 850:
        classification = "D2"
        description = "Dense cancellous + cortical shell"
    elif mean_hu >= 350:
        classification = "D3"
        description = "Porous cancellous (typical maxilla)"
    elif mean_hu >= 150:
        classification = "D4"
        description = "Very porous cancellous (posterior maxilla)"
    else:
        classification = "D4-"
        description = "Sub-threshold (inadequate primary stability likely)"

    return {
        "classification": classification,
        "description": description,
        "mean_hu": round(mean_hu, 1),
        "min_hu": round(min_hu, 1),
        "max_hu": round(max_hu, 1),
        "std_hu": round(std_hu, 1),
    }


def plan_implant(
    tooth_position: ToothNumber,
    cbct_volume_hu: np.ndarray,
    crown_emergence_target: np.ndarray,
    nerve_polyline: Optional[np.ndarray] = None,
    sinus_floor_mesh: Optional[tuple] = None,
    brand: str = "Straumann BLT",
    voxel_spacing_mm: tuple[float, float, float] = (0.4, 0.4, 0.4),
) -> ImplantPlan:
    """
    Auto-select implant size (longest/widest that respects safety margins).

    Prosthetic-driven: placement derived from crown emergence target.

    Reference: ITI Treatment Guide Vol 1 + Misch 2014 Ch 5.

    Parameters
    ----------
    tooth_position : ToothNumber
    cbct_volume_hu : ndarray (nz, ny, nx)
        CBCT Hounsfield Unit volume.
    crown_emergence_target : ndarray (3,)
        Where the crown should emerge (platform position in mm).
    nerve_polyline : ndarray (N, 3), optional
        Mandibular nerve canal polyline (mm).
    sinus_floor_mesh : (vertices, triangles), optional
        Sinus floor surface for clearance check.
    brand : str
    voxel_spacing_mm : tuple

    Returns
    -------
    ImplantPlan

    HONEST: Bone height and width estimates are derived from CBCT volume
    dimensions and voxel spacing. Clinical measurement requires full CBCT
    analysis by a qualified clinician.
    """
    vol = np.asarray(cbct_volume_hu, dtype=float)
    nz, ny, nx = vol.shape
    sx, sy, sz = voxel_spacing_mm

    # Determine available bone from volume extents (simplified)
    available_bone_mm = nz * sz - 2.0  # conservative
    width_available_mm = min(nx * sx, ny * sy) - 3.0  # conservative

    # Prosthetic axis: from emergence target in occlusal direction
    axis = np.array([0.0, 0.0, -1.0])  # apical direction (occlusal → apical)

    # Select implant spec
    mean_hu_estimate = float(vol.mean())
    implant = _select_implant_size(
        available_bone_mm=available_bone_mm,
        width_available_mm=width_available_mm,
        bone_hu=mean_hu_estimate,
        brand=brand,
    )

    # Compute fixture tip (apical) from platform + axis * length
    platform = np.asarray(crown_emergence_target, dtype=float)
    tip = platform + axis * implant.length_mm

    position = ImplantPosition(
        fixture_tip=tip,
        platform_position=platform,
        axis_direction=-axis,  # store apical→coronal
        angulation_deg=(0.0, 0.0),  # prosthetic-driven = aligned
    )

    # Sample HU along trajectory
    mean_hu = _compute_region_hu(
        vol, tip, -axis, implant.length_mm, voxel_spacing_mm
    )
    if mean_hu == 0.0:
        mean_hu = mean_hu_estimate

    # Nerve clearance
    dist_nerve = 999.0
    if nerve_polyline is not None:
        nc = np.asarray(nerve_polyline, dtype=float)
        if nc.ndim == 2 and len(nc) > 0:
            # Min distance from trajectory to nerve
            d = platform - tip
            d_sq = float(np.dot(d, d))
            if d_sq > 1e-12:
                rel = nc - tip[np.newaxis, :]
                t = np.clip(np.dot(rel, d) / d_sq, 0.0, 1.0)
                closest = tip[np.newaxis, :] + t[:, np.newaxis] * d[np.newaxis, :]
                dists = np.linalg.norm(nc - closest, axis=1)
                dist_nerve = float(np.min(dists))

    # Sinus clearance (simplified: distance from tip to sinus point cloud)
    dist_sinus = 999.0
    if sinus_floor_mesh is not None:
        sinus_pts = np.asarray(sinus_floor_mesh[0], dtype=float)
        if sinus_pts.ndim == 2 and len(sinus_pts) > 0:
            dists = np.linalg.norm(sinus_pts - tip[np.newaxis, :], axis=1)
            dist_sinus = float(np.min(dists))

    torque = _hu_to_torque(mean_hu)
    stability = _torque_to_stability_score(torque)

    return ImplantPlan(
        tooth_position=tooth_position,
        implant=implant,
        position=position,
        bone_density_HU=mean_hu,
        distance_to_nerve_mm=dist_nerve,
        distance_to_sinus_mm=dist_sinus,
        is_prosthetic_driven=True,
        insertion_torque_estimate_n_cm=torque,
        primary_stability_score=stability,
    )
