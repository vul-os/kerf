"""
kerf_dental.implant_planning — Implant trajectory planning metrics.

References
----------
Misch CE (2014) *Contemporary Implant Dentistry*, 3rd ed. §22 — implant
site assessment, bone density D1-D4 classification, recommended dimensions.

EAO (European Association for Osseointegration) Clinical Guidelines —
axial alignment tolerance ≤ 10° deviation from prosthetic axis; mandibular
nerve safety margin ≥ 2 mm; maxillary sinus floor clearance ≥ 1 mm.

DISCLAIMER
----------
These algorithms implement Misch 2014 / EAO published guidelines for
educational and planning-support purposes.  This software is **NOT
FDA-cleared or CE-marked as a medical device** and must not be used as
the sole basis for clinical decisions.  All plans require review and
approval by a qualified dental clinician.

Public API
----------
ImplantPlan
    Trajectory definition: entry_point, exit_point, diameter, length,
    tooth_position (FDI notation).

ImplantMetrics
    Computed safety metrics: bone density classification, nerve clearance,
    sinus clearance, axial deviation, violations list.

compute_implant_metrics(plan, cbct_volume, ...) -> ImplantMetrics
    Core planning engine.  Samples HU along trajectory, measures distances
    to critical anatomy, checks EAO alignment limits.

recommend_implant_dimensions(tooth_position, bone_quality, sinus_present)
    -> ImplantPlan
    Return a default-sized plan per Misch §22 site-specific tables.

generate_surgical_guide_geometry(plan) -> dict
    Produce a cylinder-based guide geometry dict for downstream STL export.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Misch bone density classification (Misch 2014 §22, Table 22-1)
# ---------------------------------------------------------------------------

class BoneDensity:
    """HU thresholds from Misch 2014 §22 Table 22-1."""
    D1 = "D1"  # > 1250 HU  — cortical: mandibular symphysis anterior
    D2 = "D2"  # 850–1250 HU — dense cancellous + cortical shell
    D3 = "D3"  # 350–849 HU  — porous cancellous (most common maxilla)
    D4 = "D4"  # 150–349 HU  — very porous cancellous (posterior maxilla)
    # Below 150 HU is generally not adequate for primary stability (flagged)


def classify_bone_density(mean_hu: float) -> str:
    """
    Classify mean HU along implant trajectory per Misch 2014 §22 Table 22-1.

    Parameters
    ----------
    mean_hu : float
        Mean Hounsfield Unit value along the planned trajectory.

    Returns
    -------
    str — one of "D1", "D2", "D3", "D4", or "D4-" (sub-threshold).
    """
    if mean_hu > 1250:
        return BoneDensity.D1
    elif mean_hu >= 850:
        return BoneDensity.D2
    elif mean_hu >= 350:
        return BoneDensity.D3
    elif mean_hu >= 150:
        return BoneDensity.D4
    else:
        return "D4-"  # below clinically acceptable threshold


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ImplantPlan:
    """
    Planned implant trajectory in jaw coordinates (mm).

    All coordinates follow the CBCT/STL coordinate system in which the
    volume was registered.

    Parameters
    ----------
    entry_point : (x, y, z)
        Crestal bone surface entry (drill entry, mm).
    exit_point : (x, y, z)
        Apical tip of planned implant (mm).
    diameter_mm : float
        Implant body diameter (mm).  Default 4.0 mm.
    length_mm : float
        Implant body length (mm).  Default 10.0 mm.
    tooth_position : str
        FDI two-digit tooth notation, e.g. "16" = upper right first molar.
    prosthetic_axis : optional (x, y, z)
        Desired prosthetic long axis unit vector.  If None, the entry→exit
        direction is used as reference for axial-deviation check.
    """
    entry_point: tuple[float, float, float]
    exit_point: tuple[float, float, float]
    diameter_mm: float = 4.0
    length_mm: float = 10.0
    tooth_position: str = ""
    prosthetic_axis: Optional[tuple[float, float, float]] = None

    def __post_init__(self):
        e0 = np.array(self.entry_point, dtype=float)
        e1 = np.array(self.exit_point, dtype=float)
        if np.linalg.norm(e1 - e0) < 1e-6:
            raise ValueError(
                "entry_point and exit_point must be distinct (non-zero trajectory)."
            )
        if self.diameter_mm <= 0 or self.length_mm <= 0:
            raise ValueError("diameter_mm and length_mm must be positive.")

    @property
    def trajectory_vector(self) -> np.ndarray:
        """Unit vector from entry to exit (coronal → apical)."""
        v = np.array(self.exit_point, dtype=float) - np.array(self.entry_point, dtype=float)
        return v / np.linalg.norm(v)

    @property
    def trajectory_length_mm(self) -> float:
        """Euclidean distance between entry and exit (mm)."""
        v = np.array(self.exit_point, dtype=float) - np.array(self.entry_point, dtype=float)
        return float(np.linalg.norm(v))


@dataclass
class ImplantMetrics:
    """
    Computed implant trajectory metrics.

    Attributes
    ----------
    bone_density_classification : str
        Misch D1–D4 classification of mean HU along trajectory.
    mean_hu : float
        Mean Hounsfield Units sampled along trajectory.
    cortical_thickness_entry_mm : float
        Estimated cortical bone thickness at the entry point (mm).
    nerve_clearance_mm : float
        Minimum distance from trajectory to mandibular nerve curve (mm).
        ``None`` if no nerve curve was provided.
    sinus_clearance_mm : float
        Minimum distance from trajectory to maxillary sinus surface (mm).
        ``None`` if no sinus surface was provided.
    axial_deviation_deg : float
        Angular deviation (°) between planned axis and prosthetic axis.
    recommended_violations : list[str]
        Human-readable list of EAO/Misch guideline violations.  Empty = OK.
    n_samples : int
        Number of HU samples taken along trajectory.
    """
    bone_density_classification: str
    mean_hu: float
    cortical_thickness_entry_mm: float
    nerve_clearance_mm: Optional[float]
    sinus_clearance_mm: Optional[float]
    axial_deviation_deg: float
    recommended_violations: list[str]
    n_samples: int = 0


# ---------------------------------------------------------------------------
# HU sampling along trajectory
# ---------------------------------------------------------------------------

def _sample_hu_along_trajectory(
    entry: np.ndarray,
    exit_: np.ndarray,
    cbct_volume: np.ndarray,
    voxel_spacing_mm: tuple[float, float, float] = (0.4, 0.4, 0.4),
    n_samples: int = 50,
) -> np.ndarray:
    """
    Sample Hounsfield Units from *cbct_volume* along the line [entry, exit_].

    The volume is indexed as [z, y, x] (DICOM convention).  Voxel spacing
    in mm is (x, y, z).  Out-of-bounds samples are returned as 0 HU.

    Parameters
    ----------
    entry, exit_ : ndarray of shape (3,)  — world coordinates in mm.
    cbct_volume  : ndarray of shape (nz, ny, nx) — HU values.
    voxel_spacing_mm : (sx, sy, sz)
    n_samples    : int — number of points to sample.

    Returns
    -------
    ndarray of shape (n_samples,) — HU values along trajectory.
    """
    volume = np.asarray(cbct_volume, dtype=float)
    nz, ny, nx = volume.shape
    sx, sy, sz = voxel_spacing_mm

    ts = np.linspace(0.0, 1.0, n_samples)
    pts = entry[np.newaxis, :] + ts[:, np.newaxis] * (exit_ - entry)[np.newaxis, :]
    # Convert mm to voxel indices
    ix = pts[:, 0] / sx
    iy = pts[:, 1] / sy
    iz = pts[:, 2] / sz

    ix_int = np.round(ix).astype(int)
    iy_int = np.round(iy).astype(int)
    iz_int = np.round(iz).astype(int)

    valid = (
        (ix_int >= 0) & (ix_int < nx) &
        (iy_int >= 0) & (iy_int < ny) &
        (iz_int >= 0) & (iz_int < nz)
    )

    hu = np.zeros(n_samples, dtype=float)
    hu[valid] = volume[iz_int[valid], iy_int[valid], ix_int[valid]]
    return hu


def _estimate_cortical_thickness(
    hu_samples: np.ndarray,
    voxel_spacing_mm: float = 0.4,
    cortical_threshold_hu: float = 850.0,
) -> float:
    """
    Estimate cortical bone thickness at the entry end of the trajectory.

    Counts contiguous HU values above *cortical_threshold_hu* starting from
    the first sample, then converts sample count to mm.

    Cortical bone HU ≥ 850 HU corresponds to D1/D2 boundary (Misch 2014).
    """
    count = 0
    for hu in hu_samples:
        if hu >= cortical_threshold_hu:
            count += 1
        else:
            break
    return count * voxel_spacing_mm


# ---------------------------------------------------------------------------
# Distance to critical anatomy
# ---------------------------------------------------------------------------

def _min_distance_point_to_curve(
    entry: np.ndarray,
    exit_: np.ndarray,
    curve_pts: np.ndarray,
) -> float:
    """
    Minimum Euclidean distance from the line segment [entry, exit_] to a
    polyline defined by *curve_pts*.

    Uses the standard parametric segment-to-point formula:
        d = |entry + t*(exit_-entry) - P| for t in [0,1].
    """
    d = exit_ - entry
    d_sq = float(np.dot(d, d))
    if d_sq < 1e-12:
        return float(np.min(np.linalg.norm(curve_pts - entry, axis=1)))

    # t = dot(P - entry, d) / |d|^2, clipped to [0, 1]
    rel = curve_pts - entry[np.newaxis, :]  # (N, 3)
    t = np.clip(np.dot(rel, d) / d_sq, 0.0, 1.0)  # (N,)
    closest = entry[np.newaxis, :] + t[:, np.newaxis] * d[np.newaxis, :]  # (N, 3)
    dists = np.linalg.norm(curve_pts - closest, axis=1)
    return float(np.min(dists))


def _min_distance_segment_to_surface(
    entry: np.ndarray,
    exit_: np.ndarray,
    surface_pts: np.ndarray,
) -> float:
    """
    Minimum Euclidean distance from the line segment [entry, exit_] to a
    point cloud representing a surface.

    Identical to _min_distance_point_to_curve but conceptually for surfaces.
    """
    return _min_distance_point_to_curve(entry, exit_, surface_pts)


# ---------------------------------------------------------------------------
# Core metric engine
# ---------------------------------------------------------------------------

def compute_implant_metrics(
    plan: ImplantPlan,
    cbct_volume: np.ndarray,
    voxel_spacing_mm: tuple[float, float, float] = (0.4, 0.4, 0.4),
    mandibular_nerve_curve: Optional[np.ndarray] = None,
    maxillary_sinus_surface: Optional[np.ndarray] = None,
    n_samples: int = 50,
) -> ImplantMetrics:
    """
    Compute implant trajectory planning metrics from a CBCT volume.

    Parameters
    ----------
    plan : ImplantPlan
        Trajectory specification.
    cbct_volume : ndarray of shape (nz, ny, nx)
        CBCT Hounsfield Unit volume.  Use ``dicom_ingest`` to build this.
    voxel_spacing_mm : (sx, sy, sz)
        Voxel spacing in mm (default 0.4 mm isotropic CBCT resolution).
    mandibular_nerve_curve : ndarray of shape (N, 3), optional
        3-D polyline tracing the mandibular nerve canal (mm).
        Required for nerve-clearance check.
    maxillary_sinus_surface : ndarray of shape (M, 3), optional
        Point cloud of the maxillary sinus floor (mm).
        Required for sinus-clearance check.
    n_samples : int
        Number of sample points along the trajectory for HU extraction.
        Default 50.

    Returns
    -------
    ImplantMetrics

    Notes
    -----
    Safety thresholds (Misch 2014 / EAO):
    - Mandibular nerve clearance ≥ 2 mm
    - Maxillary sinus floor clearance ≥ 1 mm
    - Axial deviation ≤ 10° from prosthetic axis (EAO)
    - Bone density D4- (< 150 HU) is flagged as potentially inadequate
    """
    entry = np.array(plan.entry_point, dtype=float)
    exit_ = np.array(plan.exit_point, dtype=float)
    violations: list[str] = []

    # ------------------------------------------------------------------
    # 1. HU sampling + bone density classification (Misch §22)
    # ------------------------------------------------------------------
    volume = np.asarray(cbct_volume, dtype=float)
    hu_samples = _sample_hu_along_trajectory(
        entry, exit_, volume,
        voxel_spacing_mm=voxel_spacing_mm,
        n_samples=n_samples,
    )
    mean_hu = float(np.mean(hu_samples))
    density_class = classify_bone_density(mean_hu)

    if density_class == "D4-":
        violations.append(
            f"Bone density sub-threshold ({mean_hu:.0f} HU < 150 HU): "
            "primary stability may be insufficient (Misch 2014 §22)."
        )

    # ------------------------------------------------------------------
    # 2. Cortical bone thickness at entry
    # ------------------------------------------------------------------
    cortical_thick = _estimate_cortical_thickness(
        hu_samples,
        voxel_spacing_mm=float(voxel_spacing_mm[0]),
    )

    # ------------------------------------------------------------------
    # 3. Mandibular nerve clearance (EAO: ≥ 2 mm)
    # ------------------------------------------------------------------
    nerve_clearance: Optional[float] = None
    if mandibular_nerve_curve is not None:
        nc = np.asarray(mandibular_nerve_curve, dtype=float)
        if nc.ndim == 2 and nc.shape[1] == 3 and len(nc) >= 1:
            nerve_clearance = _min_distance_point_to_curve(entry, exit_, nc)
            if nerve_clearance < 2.0:
                violations.append(
                    f"Mandibular nerve clearance {nerve_clearance:.2f} mm < 2.0 mm "
                    "(EAO minimum safety margin)."
                )

    # ------------------------------------------------------------------
    # 4. Maxillary sinus floor clearance (EAO: ≥ 1 mm)
    # ------------------------------------------------------------------
    sinus_clearance: Optional[float] = None
    if maxillary_sinus_surface is not None:
        ss = np.asarray(maxillary_sinus_surface, dtype=float)
        if ss.ndim == 2 and ss.shape[1] == 3 and len(ss) >= 1:
            sinus_clearance = _min_distance_segment_to_surface(entry, exit_, ss)
            if sinus_clearance < 1.0:
                violations.append(
                    f"Maxillary sinus floor clearance {sinus_clearance:.2f} mm < 1.0 mm "
                    "(EAO minimum safety margin)."
                )

    # ------------------------------------------------------------------
    # 5. Axial deviation from prosthetic axis (EAO: ≤ 10°)
    # ------------------------------------------------------------------
    traj_vec = plan.trajectory_vector
    if plan.prosthetic_axis is not None:
        pa = np.array(plan.prosthetic_axis, dtype=float)
        pa_norm = np.linalg.norm(pa)
        if pa_norm > 1e-9:
            pa = pa / pa_norm
            cos_a = np.clip(float(np.dot(traj_vec, pa)), -1.0, 1.0)
            axial_deviation = math.degrees(math.acos(cos_a))
        else:
            axial_deviation = 0.0
    else:
        axial_deviation = 0.0

    if axial_deviation > 10.0:
        violations.append(
            f"Axial deviation {axial_deviation:.1f}° exceeds EAO 10° limit "
            "from prosthetic axis."
        )

    return ImplantMetrics(
        bone_density_classification=density_class,
        mean_hu=mean_hu,
        cortical_thickness_entry_mm=cortical_thick,
        nerve_clearance_mm=nerve_clearance,
        sinus_clearance_mm=sinus_clearance,
        axial_deviation_deg=axial_deviation,
        recommended_violations=violations,
        n_samples=n_samples,
    )


# ---------------------------------------------------------------------------
# Default sizing recommendation (Misch 2014 §22, site-specific tables)
# ---------------------------------------------------------------------------

# FDI tooth position → (arch, region) classification
# Upper arch: 11-18, 21-28; Lower arch: 31-38, 41-48
# Regions: anterior (canine/incisor), premolar, posterior-molar

_MISCH_DEFAULT_DIMS: dict[str, tuple[float, float]] = {
    # (diameter_mm, length_mm)
    # Anterior maxillary (upper incisors/canines: 11-13, 21-23)
    "anterior_maxillary": (3.5, 11.0),
    # Anterior mandibular (lower incisors/canines: 31-33, 41-43)
    "anterior_mandibular": (3.5, 11.0),
    # Premolar maxillary (14,15,24,25)
    "premolar_maxillary": (4.0, 10.0),
    # Premolar mandibular (34,35,44,45)
    "premolar_mandibular": (4.0, 11.0),
    # Posterior maxillary / molar (16,17,18,26,27,28)
    "posterior_maxillary": (4.0, 10.0),
    # Posterior mandibular / molar (36,37,38,46,47,48)
    "posterior_mandibular": (4.5, 10.0),
}

# Bone-quality adjustments: D3/D4 → wider/longer (Misch §22 Table 22-3)
_DENSITY_DIAMETER_ADJUST: dict[str, float] = {
    BoneDensity.D1: 0.0,
    BoneDensity.D2: 0.0,
    BoneDensity.D3: 0.5,   # prefer wider implant for poorer bone
    BoneDensity.D4: 0.5,
    "D4-": 0.5,
}
_DENSITY_LENGTH_ADJUST: dict[str, float] = {
    BoneDensity.D1: 0.0,
    BoneDensity.D2: 0.0,
    BoneDensity.D3: 1.0,   # prefer longer implant for poorer bone
    BoneDensity.D4: 2.0,
    "D4-": 2.0,
}


def _fdi_to_region(tooth_position: str) -> str:
    """
    Map FDI two-digit notation to one of the six Misch site keys.

    FDI quadrants: 1 = upper right, 2 = upper left, 3 = lower left, 4 = lower right.
    Tooth numbers within quadrant: 1=central incisor ... 8=third molar.
    """
    pos = str(tooth_position).strip()
    if len(pos) != 2 or not pos.isdigit():
        return "posterior_mandibular"  # safe default

    quadrant = int(pos[0])
    tooth = int(pos[1])

    is_upper = quadrant in (1, 2)
    arch = "maxillary" if is_upper else "mandibular"

    if tooth in (1, 2, 3):
        region = "anterior"
    elif tooth in (4, 5):
        region = "premolar"
    else:
        region = "posterior"

    return f"{region}_{arch}"


def recommend_implant_dimensions(
    tooth_position: str,
    bone_quality: str = BoneDensity.D2,
    sinus_present: bool = False,
    entry_point: Optional[tuple[float, float, float]] = None,
    prosthetic_axis: Optional[tuple[float, float, float]] = None,
) -> ImplantPlan:
    """
    Recommend implant dimensions per Misch 2014 §22 site-specific tables.

    Parameters
    ----------
    tooth_position : str
        FDI two-digit tooth number (e.g. "16" = upper right first molar).
    bone_quality : str
        Misch classification "D1"–"D4" or "D4-".  Default "D2".
    sinus_present : bool
        True if maxillary sinus is present.  Reduces length in posterior maxilla
        (Misch §22: shorter implants preferred with sinus lift protocols).
    entry_point : optional (x, y, z)
        Entry point in jaw coordinates (mm).  Defaults to origin.
    prosthetic_axis : optional (x, y, z)
        Prosthetic long axis direction.  Defaults to (0, 0, 1) (occlusal).

    Returns
    -------
    ImplantPlan with recommended diameter_mm and length_mm.

    Notes
    -----
    These recommendations follow Misch 2014 §22 Table 22-2 (implant width
    selection) and Table 22-3 (bone quality adjustments).  Clinical judgement
    must always override algorithmic suggestions.
    """
    region = _fdi_to_region(tooth_position)
    base_diam, base_len = _MISCH_DEFAULT_DIMS.get(
        region, _MISCH_DEFAULT_DIMS["posterior_mandibular"]
    )

    # Bone quality adjustment
    d_adj = _DENSITY_DIAMETER_ADJUST.get(bone_quality, 0.0)
    l_adj = _DENSITY_LENGTH_ADJUST.get(bone_quality, 0.0)

    diam = base_diam + d_adj
    length = base_len + l_adj

    # Sinus reduction: Misch §22 recommends shorter implants in pneumatised
    # maxillary posterior sites (or sinus-lift protocol with 8 mm minimum)
    if sinus_present and "maxillary" in region and "posterior" in region:
        length = max(8.0, length - 2.0)

    # Build trajectory: entry at origin, exit along occlusal axis by length
    ep = entry_point if entry_point is not None else (0.0, 0.0, 0.0)
    pa = prosthetic_axis if prosthetic_axis is not None else (0.0, 0.0, 1.0)
    pa_arr = np.array(pa, dtype=float)
    pa_norm = np.linalg.norm(pa_arr)
    if pa_norm > 1e-9:
        pa_arr = pa_arr / pa_norm
    else:
        pa_arr = np.array([0.0, 0.0, 1.0])

    ep_arr = np.array(ep, dtype=float)
    exit_pt = tuple((ep_arr + pa_arr * length).tolist())

    return ImplantPlan(
        entry_point=tuple(ep),
        exit_point=exit_pt,
        diameter_mm=diam,
        length_mm=length,
        tooth_position=str(tooth_position),
        prosthetic_axis=tuple(pa_arr.tolist()),
    )


# ---------------------------------------------------------------------------
# Surgical guide geometry (cylinder dict for STL export)
# ---------------------------------------------------------------------------

def generate_surgical_guide_geometry(
    plan: ImplantPlan,
    sleeve_wall_mm: float = 1.5,
    sleeve_height_mm: float = 5.0,
    n_sides: int = 32,
) -> dict:
    """
    Generate 3-D guide-sleeve cylinder geometry for a given implant plan.

    Produces a triangulated cylinder mesh (vertices + faces) centred at the
    entry point, aligned along the plan trajectory.  Suitable for downstream
    use with ``dental_stl_export``.

    Parameters
    ----------
    plan : ImplantPlan
    sleeve_wall_mm : float
        Wall thickness of the drill guide sleeve (mm).  Default 1.5 mm.
    sleeve_height_mm : float
        Height of the guide sleeve above the bone surface (mm).  Default 5.0 mm.
    n_sides : int
        Number of facets around the cylinder circumference.  Default 32.

    Returns
    -------
    dict with keys:
        vertices : list of [x, y, z]   — float, mm
        faces    : list of [i, j, k]   — int, vertex indices
        outer_radius_mm : float
        inner_radius_mm : float
        axis     : [x, y, z]           — unit vector
        entry    : [x, y, z]           — origin of sleeve (mm)
    """
    entry = np.array(plan.entry_point, dtype=float)
    axis = plan.trajectory_vector

    outer_r = plan.diameter_mm / 2.0 + sleeve_wall_mm
    inner_r = plan.diameter_mm / 2.0
    h = sleeve_height_mm

    # Build local frame: axis + two perpendicular vectors
    # Use Gram-Schmidt against a stable reference
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(axis, ref))) > 0.99:
        ref = np.array([1.0, 0.0, 0.0])
    u = np.cross(axis, ref)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    v /= np.linalg.norm(v)

    angles = np.linspace(0.0, 2 * math.pi, n_sides, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    vertices: list[list[float]] = []
    faces: list[list[int]] = []

    def _ring(center: np.ndarray, radius: float) -> int:
        """Add a ring of n_sides vertices at *center* with *radius*; return base index."""
        base = len(vertices)
        for ca, sa in zip(cos_a, sin_a):
            pt = center + radius * (ca * u + sa * v)
            vertices.append(pt.tolist())
        return base

    # Outer cylinder: bottom ring (at entry) + top ring (at entry + axis*h)
    top = entry + axis * h
    ob0 = _ring(entry, outer_r)    # outer bottom
    ot0 = _ring(top, outer_r)      # outer top
    ib0 = _ring(entry, inner_r)    # inner bottom (drill bore)
    it0 = _ring(top, inner_r)      # inner top

    # Side walls: outer sleeve lateral surface
    for i in range(n_sides):
        j = (i + 1) % n_sides
        faces.append([ob0 + i, ob0 + j, ot0 + j])
        faces.append([ob0 + i, ot0 + j, ot0 + i])

    # Side walls: inner bore lateral surface (reversed normals)
    for i in range(n_sides):
        j = (i + 1) % n_sides
        faces.append([ib0 + j, ib0 + i, it0 + i])
        faces.append([ib0 + j, it0 + i, it0 + j])

    # Top annular cap
    for i in range(n_sides):
        j = (i + 1) % n_sides
        faces.append([ot0 + i, ot0 + j, it0 + j])
        faces.append([ot0 + i, it0 + j, it0 + i])

    # Bottom annular cap (reversed for outward normals)
    for i in range(n_sides):
        j = (i + 1) % n_sides
        faces.append([ob0 + j, ob0 + i, ib0 + i])
        faces.append([ob0 + j, ib0 + i, ib0 + j])

    return {
        "vertices": vertices,
        "faces": faces,
        "outer_radius_mm": float(outer_r),
        "inner_radius_mm": float(inner_r),
        "axis": axis.tolist(),
        "entry": entry.tolist(),
        "tooth_position": plan.tooth_position,
        "n_triangles": len(faces),
    }
