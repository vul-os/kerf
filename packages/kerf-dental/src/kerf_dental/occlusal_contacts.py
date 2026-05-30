"""
kerf_dental.occlusal_contacts — Occlusal contact analysis for dental arch meshes.

Identifies where upper and lower dental arches touch, groups contact vertices
into anatomically coherent contact regions, reports pressure distribution, and
simulates articulator motion to track contact shifts during jaw movement.

Method
------
Based on the gap-distance contact model described in Okeson (2019) "Management
of Temporomandibular Disorders and Occlusion", 8th ed., §8 (Functional Occlusion
and Mandibular Movements).  Pressure proxy follows the linear elastic contact
approximation: relative contact intensity ∝ 1/gap² (gap in μm) as used in
photoelastic occlusal analysis literature.

This module implements the geometry; it does NOT claim ADA certification or
compliance with ADA Code of Dental Procedures D0710.

Units
-----
All mesh coordinates are in millimetres (dental convention).
Gaps are reported in micrometres (μm) because clinically meaningful occlusal
gaps are 10–200 μm.

References
----------
  Okeson JP. "Management of Temporomandibular Disorders and Occlusion",
    8th ed., Elsevier, 2019. §8 (Functional Occlusion).
  Koos B et al. "Evaluation of dental occlusion with an intraoral scan-based
    technique." J Prosthet Dent 119(4):634–640, 2018.
  Podhorsky A et al. "Contact area measurement with T-Scan III vs. Fuji II."
    Clin Oral Investig 19:1555–1565, 2015.

Public API
----------
  compute_occlusal_contacts(upper_arch, lower_arch, threshold_um) -> OcclusalReport
  mark_high_pressure_zones(report, max_pressure_threshold) -> list[ContactRegion]
  compute_articulator_motion(upper, lower, motion, ...) -> ArticulatorResult
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Sequence

import numpy as np
from numpy.typing import ArrayLike
from scipy.spatial import KDTree


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------

@dataclass
class ContactRegion:
    """A contiguous group of contact vertices identified on the lower arch.

    Attributes
    ----------
    vertex_indices : list[int]
        Indices into lower_arch.vertices for this region's contact vertices.
    center_mm : np.ndarray, shape (3,)
        Centroid of all contact vertices (mm).
    area_mm2 : float
        Estimated contact-patch area (mm²).  Computed as the sum of per-vertex
        Voronoi areas across the region, approximated via the mean nearest-
        neighbour distance in the local patch.
    mean_gap_um : float
        Mean gap to the opposing arch (μm) across this region.
    max_pressure : float
        Maximum pressure proxy in this region (1 / gap_um², normalised to the
        minimum non-zero gap in the whole report; dimensionless).
    gaps_um : np.ndarray
        Per-vertex gaps within this region (μm).
    is_flagged : bool
        True after mark_high_pressure_zones() identifies this region as
        exceeding the clinical review threshold.
    """

    vertex_indices: list[int]
    center_mm: np.ndarray          # shape (3,)
    area_mm2: float
    mean_gap_um: float
    max_pressure: float
    gaps_um: np.ndarray            # shape (K,)
    is_flagged: bool = False


@dataclass
class OcclusalReport:
    """Output of :func:`compute_occlusal_contacts`.

    Attributes
    ----------
    contact_regions : list[ContactRegion]
        Detected contact patches, sorted by descending max_pressure.
    total_contact_area_mm2 : float
        Sum of contact patch areas (mm²).
    max_pressure : float
        Highest pressure proxy across all regions (dimensionless, 1/gap²
        normalised so the smallest detectable gap → 1.0).
    gap_distribution_um : np.ndarray
        Gaps at **all** lower-arch vertices that are within threshold_um of the
        upper arch (i.e., the raw data underlying contact_regions).
    threshold_um : float
        The gap threshold used to classify a vertex as "in contact" (μm).
    n_lower_vertices_evaluated : int
        Number of lower-arch vertices queried.
    """

    contact_regions: list[ContactRegion]
    total_contact_area_mm2: float
    max_pressure: float
    gap_distribution_um: np.ndarray
    threshold_um: float
    n_lower_vertices_evaluated: int


@dataclass
class ArticulatorResult:
    """Output of :func:`compute_articulator_motion`.

    Attributes
    ----------
    motion : str
        One of 'lateral', 'protrusive', or 'centric'.
    steps : list[OcclusalReport]
        One report per motion step (position along the path).
    contact_count_by_step : list[int]
        Number of contact regions at each step.
    persistent_region_indices : list[int]
        Indices into steps[0].contact_regions whose centers remain within
        *persistence_radius_mm* of a contact in the **final** step.
    disappeared_region_indices : list[int]
        Contact region indices from steps[0] absent in the final step.
    shift_vectors_mm : list[np.ndarray]
        Per-step mean contact-center displacement relative to step 0 (mm).
    """

    motion: str
    steps: list[OcclusalReport]
    contact_count_by_step: list[int]
    persistent_region_indices: list[int]
    disappeared_region_indices: list[int]
    shift_vectors_mm: list[np.ndarray]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_float64_pts(pts: ArrayLike, name: str = "mesh") -> np.ndarray:
    """Coerce *pts* to (N, 3) float64; validate shape."""
    arr = np.asarray(pts, dtype=np.float64)
    if arr.ndim == 1 and arr.shape[0] == 3:
        arr = arr[None, :]
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(
            f"Expected (N, 3) array for {name}; got shape {arr.shape}"
        )
    return arr


def _voronoi_area_estimate(vertices: np.ndarray) -> np.ndarray:
    """Approximate per-vertex Voronoi area via mean squared NN distance.

    For a uniform vertex distribution the Voronoi cell area ≈ d_nn² / 2
    where d_nn is the nearest-neighbour distance (Aurenhammer 1991).
    This is a fast O(N log N) approximation; not exact for irregular meshes.

    Returns area per vertex in mm².
    """
    if len(vertices) < 2:
        return np.ones(len(vertices)) * 1.0  # fallback

    tree = KDTree(vertices)
    # k=2 → self + 1 neighbour; take second column
    dists, _ = tree.query(vertices, k=min(2, len(vertices)))
    if dists.ndim == 1:
        nn_dist = dists
    else:
        nn_dist = dists[:, 1] if dists.shape[1] > 1 else dists[:, 0]
    return 0.5 * nn_dist ** 2  # mm²


def _flood_fill_regions(
    contact_mask: np.ndarray,      # (N,) bool — which lower vertices are in contact
    lower_vertices: np.ndarray,    # (N, 3)
    adjacency_radius_mm: float = 2.0,
) -> list[list[int]]:
    """Group contact vertices into contiguous regions by spatial adjacency.

    Two contact vertices belong to the same region if their Euclidean distance
    is ≤ adjacency_radius_mm.  Uses union-find (disjoint-set) for O(N α(N)).

    Parameters
    ----------
    contact_mask : (N,) bool
        True for vertices classified as in-contact with the upper arch.
    lower_vertices : (N, 3)
        Vertex positions of the lower arch (mm).
    adjacency_radius_mm : float
        Spatial adjacency threshold (default 2.0 mm — roughly one tooth cusp
        width, large enough to merge fragmented contact pixels on a dense mesh).

    Returns
    -------
    regions : list of lists
        Each inner list contains the indices (into the **original** lower-arch
        vertex array) of one contiguous contact region.
    """
    contact_idx = np.where(contact_mask)[0]
    if len(contact_idx) == 0:
        return []

    contact_pts = lower_vertices[contact_idx]

    # Build adjacency via radius query
    tree = KDTree(contact_pts)
    pairs = tree.query_pairs(r=adjacency_radius_mm)   # set of (i, j) pairs (local idx)

    # Union-find
    parent = list(range(len(contact_idx)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, j in pairs:
        union(i, j)

    # Collect groups
    groups: dict[int, list[int]] = {}
    for local_i, global_i in enumerate(contact_idx):
        root = find(local_i)
        groups.setdefault(root, []).append(int(global_i))

    return list(groups.values())


def _pressure_proxy(gap_um: np.ndarray, eps_um: float = 1.0) -> np.ndarray:
    """Compute pressure proxy as 1/(gap_um + eps_um)².

    eps_um avoids division by zero for exact-contact vertices (gap=0).
    Returns un-normalised values in 1/μm².
    """
    return 1.0 / (gap_um + eps_um) ** 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_occlusal_contacts(
    upper_arch: ArrayLike,
    lower_arch: ArrayLike,
    threshold_um: float = 50.0,
    adjacency_radius_mm: float = 2.0,
) -> OcclusalReport:
    """Identify occlusal contact patches between upper and lower dental arches.

    For each vertex in *lower_arch*, the nearest point on *upper_arch* is
    found (KD-tree O(N log M)).  Vertices with gap < *threshold_um* are
    contact candidates.  Adjacent contact vertices are grouped into contact
    regions via spatial flood-fill; each region gets an area, centroid, and
    pressure proxy.

    Method reference: Okeson (2019) §8 — occlusal contact detection via
    opposing-arch proximity analysis.

    Parameters
    ----------
    upper_arch : array-like (M, 3)
        Vertices of the maxillary (upper) arch mesh (mm).
    lower_arch : array-like (N, 3)
        Vertices of the mandibular (lower) arch mesh (mm).
    threshold_um : float
        Gap threshold in micrometres.  Vertices with gap < threshold_um are
        classified as "in contact".  Clinical default: 50 μm (Koos 2018).
    adjacency_radius_mm : float
        Spatial radius for grouping contact vertices into regions (mm).
        Default 2.0 mm (approx. one inter-cusp width).

    Returns
    -------
    OcclusalReport
        Detected contact regions with area, pressure, and gap statistics.

    Notes
    -----
    The pressure proxy 1/gap² is an analogy to Hertzian contact pressure
    (which scales as P ∝ 1/√δ for a sphere-on-flat) adapted for the discrete
    vertex representation used in intraoral scan meshes.  It is NOT a validated
    stress analysis; use only as a relative ranking of contact intensity.
    """
    upper = _to_float64_pts(upper_arch, "upper_arch")
    lower = _to_float64_pts(lower_arch, "lower_arch")

    # Step 1: KD-tree nearest-neighbour query — gap in mm → convert to μm
    tree = KDTree(upper)
    dists_mm, _ = tree.query(lower, workers=1)
    gaps_um = dists_mm * 1_000.0  # mm → μm

    # Step 2: Contact mask
    contact_mask = gaps_um < threshold_um

    # Step 3: Flood-fill into regions
    region_groups = _flood_fill_regions(contact_mask, lower, adjacency_radius_mm)

    # Step 4: Per-region Voronoi areas (computed across all lower vertices for
    #         density estimate, then summed per region)
    all_areas_mm2 = _voronoi_area_estimate(lower)

    # Step 5: Normalisation constant for pressure (use minimum non-zero gap
    #         across all contact vertices so the highest-pressure point → 1.0)
    contact_gaps = gaps_um[contact_mask]
    if len(contact_gaps) > 0:
        min_gap = float(np.min(contact_gaps))
        # eps avoids div-by-zero when gap == 0
        ref_pressure = float(_pressure_proxy(np.array([min_gap]), eps_um=1.0)[0])
    else:
        ref_pressure = 1.0

    # Step 6: Build ContactRegion objects
    contact_regions: list[ContactRegion] = []
    for idx_list in region_groups:
        idxs = np.array(idx_list, dtype=np.intp)
        region_gaps = gaps_um[idxs]
        region_verts = lower[idxs]
        center = region_verts.mean(axis=0)
        area = float(all_areas_mm2[idxs].sum())
        mean_gap = float(region_gaps.mean())
        pressures = _pressure_proxy(region_gaps, eps_um=1.0)
        # Normalise so that the globally-highest pressure == 1.0
        max_p = float(pressures.max() / ref_pressure) if ref_pressure > 0 else 0.0

        contact_regions.append(ContactRegion(
            vertex_indices=idx_list,
            center_mm=center,
            area_mm2=area,
            mean_gap_um=mean_gap,
            max_pressure=max_p,
            gaps_um=region_gaps,
        ))

    # Sort by descending pressure (highest clinical risk first)
    contact_regions.sort(key=lambda r: r.max_pressure, reverse=True)

    total_area = sum(r.area_mm2 for r in contact_regions)
    global_max_p = contact_regions[0].max_pressure if contact_regions else 0.0

    return OcclusalReport(
        contact_regions=contact_regions,
        total_contact_area_mm2=total_area,
        max_pressure=global_max_p,
        gap_distribution_um=contact_gaps,
        threshold_um=threshold_um,
        n_lower_vertices_evaluated=len(lower),
    )


def mark_high_pressure_zones(
    report: OcclusalReport,
    max_pressure_threshold: float = 0.5,
) -> list[ContactRegion]:
    """Flag contact regions whose normalised max_pressure exceeds *max_pressure_threshold*.

    Mutates the *is_flagged* attribute of matching regions in-place and
    returns the flagged subset.  Flagged regions warrant clinical review
    for premature contacts or occlusal interferences (Okeson 2019, §8.4).

    Parameters
    ----------
    report : OcclusalReport
        Output from :func:`compute_occlusal_contacts`.
    max_pressure_threshold : float
        Normalised pressure cutoff (0–1).  Regions with max_pressure above this
        value are flagged.  Default 0.5 (50 % of maximum contact intensity).

    Returns
    -------
    list[ContactRegion]
        Flagged regions, sorted by descending max_pressure.
    """
    flagged: list[ContactRegion] = []
    for region in report.contact_regions:
        if region.max_pressure > max_pressure_threshold:
            region.is_flagged = True
            flagged.append(region)
    return sorted(flagged, key=lambda r: r.max_pressure, reverse=True)


def compute_articulator_motion(
    upper: ArrayLike,
    lower: ArrayLike,
    motion: Literal["lateral", "protrusive", "centric"] = "centric",
    *,
    n_steps: int = 5,
    step_mm: float = 0.5,
    threshold_um: float = 50.0,
    persistence_radius_mm: float = 3.0,
) -> ArticulatorResult:
    """Simulate jaw movement and track occlusal contact shifts.

    Translates the lower arch along a simplified motion path relative to the
    upper arch and reports contact changes at each step.  This simulates the
    articulator movements described in Okeson (2019) §8 (functional movements):

    - **centric** — small closing motion (−Z translation: lower moves upward
      toward upper arch); models centric closure.
    - **protrusive** — forward (+Y) movement of the mandible; models Class I
      protrusive path.
    - **lateral** — transverse (±X) movement; models lateral excursion.

    The model is a rigid-body translation simulation (no condylar path, no
    Bennett angle).  Sufficient for identifying which contacts persist vs
    disappear during functional movement.

    Parameters
    ----------
    upper : array-like (M, 3)
        Upper arch vertices (mm), fixed.
    lower : array-like (N, 3)
        Lower arch vertices (mm), starting position (maximum intercuspation).
    motion : {"lateral", "protrusive", "centric"}
        Jaw movement type.
    n_steps : int
        Number of incremental positions to evaluate (default 5).
    step_mm : float
        Magnitude of each incremental step in mm (default 0.5 mm).
    threshold_um : float
        Contact gap threshold in μm (default 50 μm).
    persistence_radius_mm : float
        Two regions "persist" if their centers are within this radius (mm)
        across first and last step (default 3.0 mm).

    Returns
    -------
    ArticulatorResult

    Notes
    -----
    The motion vectors follow the dental convention with +X = patient's right,
    +Y = anterior, +Z = superior (occlusal).
    """
    upper_arr = _to_float64_pts(upper, "upper_arch")
    lower_arr = _to_float64_pts(lower, "lower_arch")

    # Motion direction vectors (unit vectors in dental coordinate system)
    _direction_map: dict[str, np.ndarray] = {
        "centric":    np.array([ 0.0,  0.0,  1.0]),   # inferior→superior closure
        "protrusive": np.array([ 0.0,  1.0,  0.0]),   # posterior→anterior
        "lateral":    np.array([ 1.0,  0.0,  0.0]),   # right excursion
    }
    if motion not in _direction_map:
        raise ValueError(
            f"motion must be one of {list(_direction_map.keys())}; got {motion!r}"
        )
    direction = _direction_map[motion]

    steps: list[OcclusalReport] = []
    for i in range(n_steps):
        offset = direction * (i * step_mm)
        lower_shifted = lower_arr + offset
        report = compute_occlusal_contacts(
            upper_arr, lower_shifted,
            threshold_um=threshold_um,
        )
        steps.append(report)

    contact_count_by_step = [len(s.contact_regions) for s in steps]

    # Shift vectors: mean contact center displacement relative to step 0
    shift_vectors: list[np.ndarray] = []
    if steps[0].contact_regions:
        c0 = np.mean([r.center_mm for r in steps[0].contact_regions], axis=0)
    else:
        c0 = np.zeros(3)

    for s in steps:
        if s.contact_regions:
            ci = np.mean([r.center_mm for r in s.contact_regions], axis=0)
        else:
            ci = c0.copy()
        shift_vectors.append(ci - c0)

    # Persistence: which initial regions are close to a region in the last step
    first_step = steps[0]
    last_step = steps[-1]
    persistent: list[int] = []
    disappeared: list[int] = []

    for i, r0 in enumerate(first_step.contact_regions):
        found = False
        for rf in last_step.contact_regions:
            if np.linalg.norm(r0.center_mm - rf.center_mm) <= persistence_radius_mm:
                found = True
                break
        if found:
            persistent.append(i)
        else:
            disappeared.append(i)

    return ArticulatorResult(
        motion=motion,
        steps=steps,
        contact_count_by_step=contact_count_by_step,
        persistent_region_indices=persistent,
        disappeared_region_indices=disappeared,
        shift_vectors_mm=shift_vectors,
    )
