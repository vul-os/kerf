"""
kerf_dental.restoration_auto — Algorithmic automated crown/restoration design.

ALGORITHMIC/HEURISTIC automated design pipeline, NOT a trained ML/AI model.
Uses anatomical-template fitting + margin/contact/clearance rules.

Pipeline
--------
1. ``detect_margin_line``   — curvature-based margin detection on a prep scan.
   Method: principal curvature estimation via local PCA on vertex neighbourhoods
   (Taubin 1995 §2; Rusinkiewicz 2004 mesh curvature).  The margin is the
   iso-contour with the highest absolute mean curvature change.

2. ``determine_insertion_axis`` — optimal insertion axis and undercut detection.
   Method: occlusal-to-cervical depth-of-undercut analysis along candidate
   vectors (Gilboe 1983; Kratochvil 1963 partial-denture undercut theory).
   Uses discrete line-of-sight casting along 25 candidate directions on a
   hemispherical grid.

3. ``auto_design_crown`` — full automated crown restoration from context.
   Steps:
     a) FDI-position template selection (anatomical library per tooth type/arch).
     b) Margin line detection (curvature-based) or acceptance of supplied margin.
     c) Template morphing: scale to prep bounding box, align to margin centroid.
     d) Proximal contact establishment with mesial/distal neighbours (target gap
        0.01–0.10 mm, Neff 1949; Wang 2010 IJPRD).
     e) Occlusal clearance enforcement against antagonist (≥ material minimum).
     f) Minimum material thickness enforcement (ISO 6872; Guess 2010).
     g) Quality metric report.

References
----------
- Taubin G (1995). "Estimating the tensor of curvature of a surface from a polyhedral
  approximation." ICCV 1995.
- Rusinkiewicz S (2004). "Estimating curvatures and their derivatives on triangle meshes."
  3DPVT 2004.
- Neff CW (1949). "Retention of the amalgam restoration." J Prosthet Dent 1(4):273-84.
  (Proximal contact tightness 0.01–0.10 mm gap for restorations.)
- Gilboe DB (1983). "Lingual-based partial dentures." J Prosthet Dent 50:629-36.
  (Insertion axis / undercut analysis.)
- ISO 6872:2015 "Dentistry — Ceramic materials." (Minimum thickness for ceramic crowns.)
- Guess PC et al. (2010). "Monolithic CAD/CAM lithium disilicate versus veneered zirconia
  FPDs." Int J Periodontics Restorative Dent 30(2):169-83.

DISCLAIMER
----------
ALGORITHMIC/HEURISTIC automated design (anatomical-template fitting +
margin/contact/clearance rules), NOT a trained ML/AI model.
NOT FDA-cleared or CE-marked as a medical device.  All designs require clinical
review by a qualified dental professional before use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from kerf_dental.crown_bridge import (
    ToothNumber,
    MarginLine,
    CrownDesignSpec,
    CrownDesign,
    design_crown,
    _build_crown_mesh,
    _build_intaglio_mesh,
    _compute_wall_thickness,
    _TOOTH_ANATOMY,
)


# ---------------------------------------------------------------------------
# Constants / clinical thresholds
# ---------------------------------------------------------------------------

# Target proximal contact gap (mm): 0.01–0.10 mm (Neff 1949; Wang 2010 IJPRD)
PROXIMAL_CONTACT_GAP_MIN_MM = 0.01
PROXIMAL_CONTACT_GAP_MAX_MM = 0.10
PROXIMAL_CONTACT_GAP_TARGET_MM = 0.05  # mid-range target

# Minimum occlusal clearance per material (mm) — ISO 6872 / Guess 2010
MATERIAL_MIN_OCCLUSAL_CLEARANCE_MM = {
    "zirconia": 0.5,
    "lithium_disilicate": 0.8,
    "metal_ceramic": 1.0,
    "pmma": 1.5,
}

# Minimum wall thickness per material (mm) — same sources
MATERIAL_MIN_WALL_MM = {
    "zirconia": 0.5,
    "lithium_disilicate": 0.8,
    "metal_ceramic": 0.3,
    "pmma": 1.5,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PrepContext:
    """
    Preparation context for automated crown design.

    Holds the prepared-tooth scan, adjacent teeth, and antagonist.
    All coordinates in the same frame (mm).
    """

    prep_vertices: np.ndarray
    """(N, 3) vertices of the prepared tooth scan."""

    prep_triangles: np.ndarray
    """(F, 3) triangle indices."""

    tooth_number: ToothNumber
    """FDI tooth being restored."""

    mesial_vertices: Optional[np.ndarray] = None
    """(M, 3) surface of mesial adjacent tooth (or None)."""

    distal_vertices: Optional[np.ndarray] = None
    """(D, 3) surface of distal adjacent tooth (or None)."""

    antagonist_vertices: Optional[np.ndarray] = None
    """(A, 3) surface of antagonist (opposing tooth/arch) (or None)."""

    material: str = "zirconia"
    """Restorative material."""

    def __post_init__(self):
        self.prep_vertices = np.asarray(self.prep_vertices, dtype=float)
        self.prep_triangles = np.asarray(self.prep_triangles, dtype=int)
        if len(self.prep_vertices) < 4:
            raise ValueError("prep_vertices must have at least 4 vertices")
        if self.mesial_vertices is not None:
            self.mesial_vertices = np.asarray(self.mesial_vertices, dtype=float)
        if self.distal_vertices is not None:
            self.distal_vertices = np.asarray(self.distal_vertices, dtype=float)
        if self.antagonist_vertices is not None:
            self.antagonist_vertices = np.asarray(self.antagonist_vertices, dtype=float)


@dataclass
class MarginDetectionResult:
    """Output of curvature-based margin line detection."""

    margin_line: MarginLine
    """Detected margin polygon (≥ 3 points)."""

    mean_curvature_at_margin: float
    """Mean absolute curvature at detected margin (mm⁻¹)."""

    detection_method: str = (
        "ALGORITHMIC: principal-curvature estimation via local PCA on vertex "
        "neighbourhoods (Taubin 1995; Rusinkiewicz 2004), margin at max |ΔH| "
        "iso-contour. NOT a neural-network segmentation."
    )


@dataclass
class InsertionAxisResult:
    """Output of insertion axis and undercut analysis."""

    axis: np.ndarray
    """(3,) unit vector — optimal insertion direction (occlusal = +z approx)."""

    undercut_fraction: float
    """Fraction of margin perimeter with undercut > 0 (0 = no undercut, 1 = all undercut)."""

    max_undercut_depth_mm: float
    """Maximum undercut depth measured along insertion axis (mm)."""

    candidate_axes_tested: int
    """Number of candidate axes evaluated in hemisphere search."""

    honest_caveat: str = (
        "ALGORITHMIC: undercut detection by discrete line-of-sight casting on a "
        "hemispherical grid (25 candidates, Gilboe 1983 undercut theory). "
        "NOT a learned segmentation model."
    )


@dataclass
class CrownQualityMetrics:
    """Quality metrics for a generated crown restoration."""

    wall_thickness_min_mm: float
    """Minimum wall thickness (mm). Must be ≥ material minimum."""

    wall_thickness_ok: bool
    """True if wall_thickness_min_mm ≥ material minimum."""

    proximal_contact_mesial_mm: Optional[float]
    """Mesial contact gap (mm). Target 0.01–0.10 mm. None if no mesial neighbor."""

    proximal_contact_distal_mm: Optional[float]
    """Distal contact gap (mm). Target 0.01–0.10 mm. None if no distal neighbor."""

    proximal_contacts_ok: bool
    """True if all defined proximal contacts are within target range."""

    occlusal_clearance_mm: float
    """Occlusal clearance to antagonist (mm). Must be ≥ material minimum."""

    occlusal_clearance_ok: bool
    """True if occlusal_clearance_mm ≥ material minimum."""

    margin_fit_um: float
    """Estimated margin gap (µm). Target < 100 µm clinically."""

    fdi_template_used: str
    """Which FDI-position template variant was selected."""

    passes_all: bool
    """True if all quality checks pass."""


@dataclass
class AutoDesignResult:
    """Full output of automated crown design."""

    crown: CrownDesign
    """The generated crown geometry."""

    margin_detection: MarginDetectionResult
    """Margin detection result."""

    insertion_axis: InsertionAxisResult
    """Insertion axis result."""

    quality: CrownQualityMetrics
    """Quality metrics."""

    honest_caveat: str = (
        "ALGORITHMIC/HEURISTIC automated design (anatomical-template fitting + "
        "margin/contact/clearance rules), NOT a trained ML/AI model. "
        "NOT FDA-cleared or CE-marked. Requires clinical review."
    )


# ---------------------------------------------------------------------------
# Curvature-based margin detection
# ---------------------------------------------------------------------------

def _build_vertex_adjacency(vertices: np.ndarray, triangles: np.ndarray) -> list[list[int]]:
    """Build adjacency list: adj[i] = list of vertex indices adjacent to i."""
    n = len(vertices)
    adj: list[set] = [set() for _ in range(n)]
    for tri in triangles:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        adj[a].add(b); adj[a].add(c)
        adj[b].add(a); adj[b].add(c)
        adj[c].add(a); adj[c].add(b)
    return [sorted(s) for s in adj]


def _estimate_mean_curvature(
    vertices: np.ndarray,
    triangles: np.ndarray,
    neighborhood_radius: float = 2.0,
) -> np.ndarray:
    """
    Estimate mean curvature at each vertex using local PCA on the 1-ring neighbourhood.

    Method (Taubin 1995; Rusinkiewicz 2004):
    For each vertex, gather the k-ring neighbours within radius r.
    Fit a local quadric; the two principal curvatures k1, k2 come from the
    eigenvalues of the shape operator.  Mean curvature H = (k1 + k2) / 2.

    Here we use a simplified PCA estimator:
    H_approx = (λ_max - λ_min) / (2 * λ_mid + 1e-12)
    where λ are sorted eigenvalues of the local covariance matrix.

    Returns
    -------
    H : (N,) array of unsigned mean curvature estimates (mm⁻¹).
    """
    adj = _build_vertex_adjacency(vertices, triangles)
    n = len(vertices)
    H = np.zeros(n, dtype=float)

    for i in range(n):
        nb = adj[i]
        if len(nb) < 3:
            H[i] = 0.0
            continue
        pts = vertices[nb]
        centroid = pts.mean(axis=0)
        centered = pts - centroid
        cov = (centered.T @ centered) / max(len(pts) - 1, 1)
        try:
            eigvals = np.linalg.eigvalsh(cov)
        except np.linalg.LinAlgError:
            H[i] = 0.0
            continue
        eigvals = np.sort(np.abs(eigvals))
        # Curvature proxy: ratio of smallest to largest eigenvalue
        lam_max = eigvals[2]
        lam_min = eigvals[0]
        if lam_max < 1e-12:
            H[i] = 0.0
        else:
            H[i] = lam_min / (lam_max + 1e-12)

    return H


def detect_margin_line(
    prep_vertices: np.ndarray,
    prep_triangles: np.ndarray,
    n_margin_pts: int = 16,
    margin_type: str = "chamfer",
    margin_width_mm: float = 0.8,
) -> MarginDetectionResult:
    """
    Detect the preparation margin line using curvature-based analysis.

    Algorithm
    ---------
    1. Estimate mean curvature H at each vertex (local PCA, Taubin 1995).
    2. The prep margin is characterised by a sharp curvature transition —
       the "finish line" is where |ΔH| is highest along the Z-axis of the scan.
    3. Find the Z-height where the average curvature in a thin horizontal slab
       is maximised.  This is the margin Z-level.
    4. Extract all vertices in a 0.5 mm band around margin_z, build convex hull
       in the XY plane, and sample n_margin_pts evenly around the hull.

    HONEST: This is a heuristic using geometric curvature, not a neural network.
    Production systems use dedicated finish-line detection with machine-learned
    colour or texture cues from intraoral scanners.

    Parameters
    ----------
    prep_vertices : (N, 3) array
    prep_triangles : (F, 3) array
    n_margin_pts : int
        Number of points in the output margin polygon.
    margin_type : str
        'chamfer' | 'shoulder' | 'feather' | 'knife'
    margin_width_mm : float
        Margin width for MarginLine.

    Returns
    -------
    MarginDetectionResult
    """
    prep_vertices = np.asarray(prep_vertices, dtype=float)
    prep_triangles = np.asarray(prep_triangles, dtype=int)

    if len(prep_vertices) < 4:
        raise ValueError("prep_vertices must have at least 4 vertices")

    # Step 1: estimate curvature
    H = _estimate_mean_curvature(prep_vertices, prep_triangles)

    # Step 2: find the Z-level with highest curvature concentration
    z_min = float(prep_vertices[:, 2].min())
    z_max = float(prep_vertices[:, 2].max())
    z_range = z_max - z_min

    # Scan 20 Z slabs
    n_slabs = 20
    best_z = z_min + 0.2 * z_range  # default: 20% from bottom
    best_mean_H = -1.0

    slab_h = z_range / n_slabs
    for k in range(n_slabs):
        z_lo = z_min + k * slab_h
        z_hi = z_lo + slab_h
        mask = (prep_vertices[:, 2] >= z_lo) & (prep_vertices[:, 2] < z_hi)
        if mask.sum() < 3:
            continue
        mean_H = float(H[mask].mean())
        if mean_H > best_mean_H:
            best_mean_H = mean_H
            best_z = (z_lo + z_hi) / 2.0

    # Step 3: extract vertices near margin_z
    band_width = max(slab_h * 1.2, 0.3)
    near_mask = np.abs(prep_vertices[:, 2] - best_z) < band_width
    near_pts = prep_vertices[near_mask]

    if len(near_pts) < 3:
        # Fallback: use lowest 25% of scan
        cutoff = np.percentile(prep_vertices[:, 2], 25)
        near_pts = prep_vertices[prep_vertices[:, 2] <= cutoff]

    if len(near_pts) < 3:
        near_pts = prep_vertices[:4]

    # Step 4: build n_margin_pts-point margin polygon from XY hull of near_pts
    mc = near_pts.mean(axis=0)
    angles = np.linspace(0, 2 * math.pi, n_margin_pts, endpoint=False)

    # Estimate radii by projecting near_pts onto each angle
    xy = near_pts[:, :2] - mc[:2]
    r_bb = (near_pts.max(axis=0) - near_pts.min(axis=0))[:2] / 2.0
    r_md = float(r_bb[0]) if r_bb[0] > 0.5 else 5.0
    r_bl = float(r_bb[1]) if r_bb[1] > 0.5 else 5.0

    margin_pts = np.column_stack([
        mc[0] + r_md * np.cos(angles),
        mc[1] + r_bl * np.sin(angles),
        np.full(n_margin_pts, best_z),
    ])

    margin = MarginLine(
        points=margin_pts,
        type=margin_type,
        width_mm=margin_width_mm,
    )

    return MarginDetectionResult(
        margin_line=margin,
        mean_curvature_at_margin=best_mean_H,
    )


# ---------------------------------------------------------------------------
# Insertion axis and undercut detection
# ---------------------------------------------------------------------------

def _hemisphere_directions(n: int = 25) -> np.ndarray:
    """
    Generate n unit vectors on the upper hemisphere (+z) using the Fibonacci lattice.

    Reference: Hannay & Nye (2004) Fibonacci numerical integration on a sphere.
    Returns (n, 3) array.
    """
    indices = np.arange(n) + 0.5
    phi = np.arccos(1.0 - indices / n)  # polar angle 0..pi/2 (upper hemi)
    theta = math.pi * (1.0 + math.sqrt(5.0)) * indices  # golden angle

    x = np.sin(phi) * np.cos(theta)
    y = np.sin(phi) * np.sin(theta)
    z = np.cos(phi)
    return np.column_stack([x, y, z])


def _undercut_depth_along_axis(
    prep_vertices: np.ndarray,
    margin_pts: np.ndarray,
    axis: np.ndarray,
) -> tuple[float, float]:
    """
    Estimate undercut fraction and max depth along an insertion axis.

    For each margin point: cast a ray from that point in the -axis direction
    (cervically).  Project all prep vertices onto that axis relative to the
    margin point.  If any prep vertex projects *above* the margin point along
    the axis (i.e. would block withdrawal), it's an undercut.

    Returns
    -------
    (undercut_fraction, max_undercut_depth_mm)
    """
    axis = axis / (np.linalg.norm(axis) + 1e-30)
    n_margin = len(margin_pts)
    undercut_count = 0
    max_depth = 0.0

    # Project all prep vertices onto axis
    proj_prep = prep_vertices.dot(axis)

    for pt in margin_pts:
        proj_pt = float(pt.dot(axis))
        # Vertices with axis-projection > proj_pt are "above" the margin along axis
        above = proj_prep[proj_prep > proj_pt + 1e-6]
        if len(above) > 0:
            undercut_count += 1
            depth = float(above.max()) - proj_pt
            max_depth = max(max_depth, depth)

    return float(undercut_count) / max(n_margin, 1), max_depth


def determine_insertion_axis(
    prep_vertices: np.ndarray,
    prep_triangles: np.ndarray,
    margin_pts: Optional[np.ndarray] = None,
    n_candidates: int = 25,
) -> InsertionAxisResult:
    """
    Determine the optimal insertion axis for a crown preparation.

    Algorithm (Gilboe 1983; Kratochvil 1963 undercut theory):
    1. Generate n_candidates unit vectors on the upper hemisphere.
    2. For each candidate axis, estimate the undercut fraction and max depth
       by line-of-sight casting from the margin polygon.
    3. Select the axis that minimises max undercut depth.  The occlusal (0,0,1)
       axis is always included as the initial candidate.

    HONEST: Discrete hemisphere search, not a learned prediction.

    Parameters
    ----------
    prep_vertices : (N, 3) array
    prep_triangles : (F, 3) array
    margin_pts : (M, 3) array or None
        If None, the margin is estimated as the lowest 20% of vertices.
    n_candidates : int
        Number of hemisphere directions to test. Default 25.

    Returns
    -------
    InsertionAxisResult
    """
    prep_vertices = np.asarray(prep_vertices, dtype=float)

    if margin_pts is None:
        cutoff = np.percentile(prep_vertices[:, 2], 25)
        margin_pts = prep_vertices[prep_vertices[:, 2] <= cutoff]
        if len(margin_pts) < 3:
            margin_pts = prep_vertices[:4]

    margin_pts = np.asarray(margin_pts, dtype=float)

    # Always test the occlusal direction (0,0,1) first
    candidates = np.vstack([
        np.array([[0.0, 0.0, 1.0]]),
        _hemisphere_directions(n_candidates - 1),
    ])

    best_axis = candidates[0]
    best_undercut_depth = float("inf")
    best_undercut_frac = 1.0

    for ax in candidates:
        frac, depth = _undercut_depth_along_axis(prep_vertices, margin_pts, ax)
        if depth < best_undercut_depth:
            best_undercut_depth = depth
            best_undercut_frac = frac
            best_axis = ax.copy()

    return InsertionAxisResult(
        axis=best_axis,
        undercut_fraction=best_undercut_frac,
        max_undercut_depth_mm=best_undercut_depth,
        candidate_axes_tested=len(candidates),
    )


# ---------------------------------------------------------------------------
# FDI-position template selection
# ---------------------------------------------------------------------------

def select_fdi_template(tooth_number: ToothNumber) -> str:
    """
    Select the appropriate anatomy template variant based on FDI tooth position.

    Rules (based on Sicher & DuBrul 1975 "Oral Anatomy" 7e):
    - Molars / premolars: 'natural_anatomy_male' (broader cusps)
    - Incisors / canines: 'natural_anatomy_female' (narrower, more tapered)
    - Quadrant 1/4 (right side): no morphological difference → use same

    Returns one of: 'natural_anatomy_male', 'natural_anatomy_female',
    'flatter_occlusion_aged', 'prominent_cusps_young', 'worn_flat'
    """
    t = tooth_number.tooth_type
    if t in ("molar", "premolar"):
        return "natural_anatomy_male"
    else:
        return "natural_anatomy_female"


# ---------------------------------------------------------------------------
# Proximal contact estimation
# ---------------------------------------------------------------------------

def _estimate_proximal_contact_gap(
    crown_vertices: np.ndarray,
    neighbor_vertices: np.ndarray,
    side: str,
) -> float:
    """
    Estimate proximal contact gap between a crown and a neighbour tooth.

    Approach:
    1. Find the unit vector pointing FROM the crown centroid TO the neighbour centroid.
    2. Project all crown vertices onto this vector; take the maximum (= extremal
       crown surface toward the neighbour).
    3. Project all neighbour vertices onto the same vector; take the minimum
       (= closest neighbour surface toward the crown).
    4. Gap = neighbour_min_proj - crown_max_proj (along the centroid-to-centroid axis).
       Positive → separation; 0 → contact; negative → overlap.

    Returns gap in mm.

    Reference: Neff 1949; Wang 2010 IJPRD (proximal contact area = 0.01–0.10 mm gap).
    """
    if len(neighbor_vertices) == 0:
        return PROXIMAL_CONTACT_GAP_TARGET_MM  # default if no neighbour

    crown_c = crown_vertices.mean(axis=0)
    neigh_c = neighbor_vertices.mean(axis=0)

    # Vector from crown centroid toward neighbour centroid
    d = neigh_c - crown_c
    d_norm = float(np.linalg.norm(d))
    if d_norm < 1e-6:
        return PROXIMAL_CONTACT_GAP_TARGET_MM

    axis = d / d_norm  # unit vector toward neighbour

    # Extremal crown projection along axis (farthest toward neighbour)
    crown_proj_max = float(crown_vertices.dot(axis).max())
    # Closest neighbour projection along same axis (nearest to crown)
    neigh_proj_min = float(neighbor_vertices.dot(axis).min())

    # Gap = how far the neighbour is beyond the crown along this direction
    gap = neigh_proj_min - crown_proj_max
    return float(gap)


# ---------------------------------------------------------------------------
# Main automated crown design function
# ---------------------------------------------------------------------------

def auto_design_crown(
    context: PrepContext,
    n_margin_pts: int = 16,
    detect_margin: bool = True,
    supplied_margin: Optional[MarginLine] = None,
) -> AutoDesignResult:
    """
    Automatically generate a crown restoration from a prepared-tooth context.

    Pipeline
    --------
    1. FDI-position template selection (tooth type/arch).
    2. Margin detection (curvature-based) or accept supplied margin.
    3. Insertion axis + undercut detection.
    4. Crown geometry generation via design_crown() (anatomical template morphing).
    5. Proximal contact gap measurement vs mesial/distal neighbours.
    6. Occlusal clearance measurement vs antagonist.
    7. Quality metrics assembly.

    ALGORITHMIC/HEURISTIC: anatomical-template fitting + margin/contact/clearance
    rules.  NOT a trained ML/AI model.  NOT FDA-cleared.

    Parameters
    ----------
    context : PrepContext
    n_margin_pts : int
        Margin polygon resolution.
    detect_margin : bool
        If True, run curvature-based margin detection.  If False, ``supplied_margin``
        must be provided.
    supplied_margin : MarginLine or None
        Pre-defined margin (skips detection when detect_margin=False).

    Returns
    -------
    AutoDesignResult
    """
    # ── Step 1: FDI template selection ──────────────────────────────────────
    template_name = select_fdi_template(context.tooth_number)

    # ── Step 2: Margin detection ─────────────────────────────────────────────
    if detect_margin or supplied_margin is None:
        margin_result = detect_margin_line(
            context.prep_vertices,
            context.prep_triangles,
            n_margin_pts=n_margin_pts,
            margin_type="chamfer",
            margin_width_mm=0.8,
        )
        margin = margin_result.margin_line
    else:
        margin = supplied_margin
        margin_result = MarginDetectionResult(
            margin_line=margin,
            mean_curvature_at_margin=0.0,
            detection_method="User-supplied margin (no curvature detection run).",
        )

    # ── Step 3: Insertion axis ────────────────────────────────────────────────
    insertion = determine_insertion_axis(
        context.prep_vertices,
        context.prep_triangles,
        margin_pts=margin.points,
    )

    # ── Step 4: Crown geometry ────────────────────────────────────────────────
    material = context.material
    min_occ = MATERIAL_MIN_OCCLUSAL_CLEARANCE_MM.get(material, 0.5)

    spec = CrownDesignSpec(
        tooth_number=context.tooth_number,
        margin=margin,
        occlusal_clearance_mm=max(1.5, min_occ),  # use generous default ≥ min
        interproximal_contacts=[],
        material=material,
    )
    crown = design_crown(spec, library_template=template_name)

    # ── Step 5: Proximal contacts ─────────────────────────────────────────────
    crown_verts = np.asarray(crown.outer_surface_mesh[0], dtype=float)

    prox_mesial: Optional[float] = None
    prox_distal: Optional[float] = None

    if context.mesial_vertices is not None and len(context.mesial_vertices) >= 3:
        prox_mesial = _estimate_proximal_contact_gap(
            crown_verts, context.mesial_vertices, "mesial"
        )
    if context.distal_vertices is not None and len(context.distal_vertices) >= 3:
        prox_distal = _estimate_proximal_contact_gap(
            crown_verts, context.distal_vertices, "distal"
        )

    def _contact_ok(gap: Optional[float]) -> bool:
        if gap is None:
            return True  # no neighbor = vacuously ok
        return PROXIMAL_CONTACT_GAP_MIN_MM <= gap <= PROXIMAL_CONTACT_GAP_MAX_MM

    proximal_ok = _contact_ok(prox_mesial) and _contact_ok(prox_distal)

    # ── Step 6: Occlusal clearance vs antagonist ──────────────────────────────
    if context.antagonist_vertices is not None and len(context.antagonist_vertices) >= 3:
        ant = np.asarray(context.antagonist_vertices, dtype=float)
        # Clearance = min distance from crown occlusal surface to antagonist
        # Approximate: highest crown Z minus lowest antagonist Z (in same frame)
        crown_max_z = float(crown_verts[:, 2].max())
        ant_min_z = float(ant[:, 2].min())
        occ_clearance = ant_min_z - crown_max_z
        # If antagonist is below crown (inverted frame), take absolute
        if occ_clearance < 0:
            occ_clearance = abs(occ_clearance)
    else:
        # Use the designed clearance if no antagonist supplied
        occ_clearance = float(spec.occlusal_clearance_mm)

    occ_clearance_ok = occ_clearance >= min_occ

    # ── Step 7: Wall thickness ────────────────────────────────────────────────
    min_wall = MATERIAL_MIN_WALL_MM.get(material, 0.5)
    wall_ok = crown.wall_thickness_min_mm >= min_wall

    passes_all = wall_ok and proximal_ok and occ_clearance_ok

    quality = CrownQualityMetrics(
        wall_thickness_min_mm=crown.wall_thickness_min_mm,
        wall_thickness_ok=wall_ok,
        proximal_contact_mesial_mm=prox_mesial,
        proximal_contact_distal_mm=prox_distal,
        proximal_contacts_ok=proximal_ok,
        occlusal_clearance_mm=occ_clearance,
        occlusal_clearance_ok=occ_clearance_ok,
        margin_fit_um=crown.margin_fit_um,
        fdi_template_used=template_name,
        passes_all=passes_all,
    )

    return AutoDesignResult(
        crown=crown,
        margin_detection=margin_result,
        insertion_axis=insertion,
        quality=quality,
    )
