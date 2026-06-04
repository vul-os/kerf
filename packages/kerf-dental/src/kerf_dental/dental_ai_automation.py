"""
kerf_dental.dental_ai_automation — Template-based AI assist for crown design.

Uses deterministic shape-descriptor matching (Hu moments on tooth projections)
to select the best tooth library template for a preparation mesh.

References
----------
- Mörmann WH (2006). "The evolution of the CEREC system." JADA 137(9 Suppl):7S-13S.
  (CEREC Bluecam/Bluecam workflow — template library matching).
- Hu MK (1962). "Visual pattern recognition by moment invariants."
  IRE Trans Inf Theory 8(2):179-87.
- Fasbinder DJ (2010). "Clinical performance of CAD/CAM restorations."
  JADA 141 Suppl 2:3S-9S.

DISCLAIMER
----------
NOT a real neural network. This module uses deterministic template matching
with 2D Hu moment invariants projected onto the occlusal plane.
NOT FDA-cleared or CE-marked as a medical device. AI-assisted crown design
requires clinical review by a qualified dentist or dental technician.

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from kerf_dental.crown_bridge import ToothNumber, MarginLine
from kerf_dental.intraoral_scan import IntraoralScan


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ToothTemplate:
    """Library tooth template for morphing."""

    tooth_number: ToothNumber
    template_name: str
    """'natural_anatomy_male' | 'natural_anatomy_female' | 'flatter_occlusion_aged' |
    'prominent_cusps_young' | 'worn_flat'"""

    vertices: np.ndarray
    """(N, 3) template mesh vertices (mm)."""

    triangles: np.ndarray
    """(F, 3) triangle indices."""

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, dtype=float)
        self.triangles = np.asarray(self.triangles, dtype=int)

    @property
    def bounding_box_size(self) -> np.ndarray:
        """(3,) bounding box dimensions in mm (MD, BL, height)."""
        return self.vertices.max(axis=0) - self.vertices.min(axis=0)

    @property
    def centroid(self) -> np.ndarray:
        return self.vertices.mean(axis=0)


@dataclass
class TemplateMatch:
    """Result of template matching."""

    template: ToothTemplate
    morph_score: float
    """0–1, higher = better fit to preparation shape."""

    scale_factor: tuple[float, float, float]
    """(sx, sy, sz) scale to fit template to prep dimensions."""

    honest_caveat: str = (
        "TEMPLATE MATCHING, NOT NEURAL NETWORK: morph_score uses "
        "2D Hu moment invariants on the occlusal projection. "
        "Not a trained model — deterministic shape descriptors only. "
        "Reference: Mörmann 2006 (CEREC library morphing)."
    )


# ---------------------------------------------------------------------------
# Hu moment shape descriptors
# ---------------------------------------------------------------------------

def _compute_hu_moments(pts_2d: np.ndarray) -> np.ndarray:
    """
    Compute 7 Hu moment invariants for a 2D point cloud.

    Reference: Hu MK (1962) IRE Trans Inf Theory 8(2):179-87.

    The 7 Hu moments are invariant to translation, scale, and rotation.
    Used here as a shape descriptor for the occlusal projection of a tooth.

    Parameters
    ----------
    pts_2d : (N, 2) array of 2D points

    Returns
    -------
    (7,) array of Hu moment invariants (log-scaled for stability)
    """
    if len(pts_2d) < 3:
        return np.zeros(7)

    # Central moments up to order 3
    mu_x = float(pts_2d[:, 0].mean())
    mu_y = float(pts_2d[:, 1].mean())
    cx = pts_2d[:, 0] - mu_x
    cy = pts_2d[:, 1] - mu_y

    def _raw_moment(p, q):
        return float(np.sum(cx**p * cy**q))

    m20 = _raw_moment(2, 0)
    m02 = _raw_moment(0, 2)
    m11 = _raw_moment(1, 1)
    m30 = _raw_moment(3, 0)
    m03 = _raw_moment(0, 3)
    m12 = _raw_moment(1, 2)
    m21 = _raw_moment(2, 1)

    # Scale normalisation: divide by m00^(1+(p+q)/2)
    m00 = float(len(pts_2d))  # approximate
    if m00 < 1e-10:
        return np.zeros(7)

    n20 = m20 / m00**2
    n02 = m02 / m00**2
    n11 = m11 / m00**2
    n30 = m30 / m00**2.5
    n03 = m03 / m00**2.5
    n12 = m12 / m00**2.5
    n21 = m21 / m00**2.5

    # 7 Hu moment invariants
    hu = np.zeros(7)
    hu[0] = n20 + n02
    hu[1] = (n20 - n02)**2 + 4 * n11**2
    hu[2] = (n30 - 3*n12)**2 + (3*n21 - n03)**2
    hu[3] = (n30 + n12)**2 + (n21 + n03)**2
    hu[4] = (n30 - 3*n12)*(n30 + n12)*((n30+n12)**2 - 3*(n21+n03)**2) + \
             (3*n21 - n03)*(n21+n03)*(3*(n30+n12)**2 - (n21+n03)**2)
    hu[5] = (n20 - n02)*((n30+n12)**2 - (n21+n03)**2) + \
             4*n11*(n30+n12)*(n21+n03)
    hu[6] = (3*n21 - n03)*(n30+n12)*((n30+n12)**2 - 3*(n21+n03)**2) - \
             (n30 - 3*n12)*(n21+n03)*(3*(n30+n12)**2 - (n21+n03)**2)

    # Log-scale for numerical stability (Hu 1962 sign convention)
    log_hu = np.zeros(7)
    for i, h in enumerate(hu):
        if abs(h) > 1e-300:
            log_hu[i] = math.copysign(math.log10(abs(h) + 1e-300), h)
        else:
            log_hu[i] = 0.0

    return log_hu


def _project_to_occlusal(mesh_verts: np.ndarray) -> np.ndarray:
    """Project mesh vertices onto their best-fit occlusal plane (XY projection of PCA)."""
    if len(mesh_verts) < 3:
        return mesh_verts[:, :2]

    centroid = mesh_verts.mean(axis=0)
    centered = mesh_verts - centroid
    _, _, vh = np.linalg.svd(centered, full_matrices=False)

    # Normal is the smallest variance direction
    normal = vh[2]
    if normal[2] < 0:
        normal = -normal

    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(ref, normal)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    x_ax = np.cross(normal, ref)
    x_ax /= np.linalg.norm(x_ax)
    y_ax = np.cross(normal, x_ax)
    y_ax /= np.linalg.norm(y_ax)

    return np.column_stack([centered.dot(x_ax), centered.dot(y_ax)])


# ---------------------------------------------------------------------------
# Default tooth library
# ---------------------------------------------------------------------------

def _make_default_library(tooth_number: ToothNumber) -> list[ToothTemplate]:
    """
    Build a small default library of 5 template variants for a given tooth.

    Templates are parametric meshes with varying cusp prominence:
    - natural_anatomy_male: medium cusps
    - natural_anatomy_female: slightly smaller
    - flatter_occlusion_aged: worn, flatter cusps
    - prominent_cusps_young: higher, sharper cusps
    - worn_flat: minimal cusp relief
    """
    from kerf_dental.crown_bridge import _build_crown_mesh, MarginLine

    # Standard margin polygon for this tooth type
    tooth_key = f"{tooth_number.tooth_type}_{tooth_number.arch}"
    anatomy_sizes = {
        "incisor_maxillary": (8.5, 7.0, 10.5, 1),
        "incisor_mandibular": (5.3, 6.0, 9.0, 1),
        "canine_maxillary": (7.5, 8.0, 10.0, 1),
        "canine_mandibular": (6.9, 7.7, 11.0, 1),
        "premolar_maxillary": (7.0, 9.0, 8.5, 2),
        "premolar_mandibular": (7.0, 8.0, 8.5, 2),
        "molar_maxillary": (10.0, 11.5, 7.5, 4),
        "molar_mandibular": (11.0, 10.5, 7.5, 4),
    }
    md, bl, h, n_cusps = anatomy_sizes.get(tooth_key, (10.0, 10.0, 7.5, 4))

    # Build base margin polygon (elliptical)
    n_margin = 16
    angles = np.linspace(0, 2 * math.pi, n_margin, endpoint=False)
    margin_pts = np.column_stack([
        (md / 2) * np.cos(angles),
        (bl / 2) * np.sin(angles),
        np.zeros(n_margin),
    ])

    templates = []
    variants = [
        ("natural_anatomy_male", h, 0.20, n_cusps),
        ("natural_anatomy_female", h * 0.95, 0.18, n_cusps),
        ("flatter_occlusion_aged", h * 0.85, 0.10, n_cusps),
        ("prominent_cusps_young", h * 1.05, 0.28, n_cusps),
        ("worn_flat", h * 0.75, 0.05, n_cusps),
    ]

    for name, crown_h, cusp_frac, nc in variants:
        try:
            verts, tris = _build_crown_mesh(
                margin_pts,
                crown_height=crown_h,
                n_cusps=nc,
                cusp_depth_fraction=cusp_frac,
            )
            templates.append(ToothTemplate(
                tooth_number=tooth_number,
                template_name=name,
                vertices=verts,
                triangles=tris,
            ))
        except Exception:
            pass  # Skip failed variants

    return templates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_tooth_template(
    prep_mesh: tuple,
    tooth_number: ToothNumber,
    library: list[ToothTemplate],
) -> TemplateMatch:
    """
    Template-based AI assist: pick the library template best matching prep shape.

    Uses 2D Hu moment invariants on the occlusal projection as shape descriptors.
    Lower Euclidean distance between descriptor vectors = better match.

    HONEST: Not a real neural network — deterministic template-matching with
    shape descriptors (Hu moments). Clinical selection requires visual review.

    Reference: Mörmann WH (2006) CEREC library morphing workflow.

    Parameters
    ----------
    prep_mesh : (vertices (N,3), triangles (F,3))
        The preparation mesh (scan of prepared tooth).
    tooth_number : ToothNumber
        The tooth being restored.
    library : list[ToothTemplate]
        Library of template teeth to match against.

    Returns
    -------
    TemplateMatch — the best-matching template and morph parameters.
    """
    if not library:
        raise ValueError("library must not be empty")

    prep_verts = np.asarray(prep_mesh[0], dtype=float)
    if len(prep_verts) < 3:
        raise ValueError("prep_mesh must have at least 3 vertices")

    # Compute Hu moments for the preparation
    prep_2d = _project_to_occlusal(prep_verts)
    prep_hu = _compute_hu_moments(prep_2d)

    # Compute Hu moments for each template and find best match
    best_template = library[0]
    best_score = 0.0
    best_scale = (1.0, 1.0, 1.0)
    min_dist = float("inf")

    prep_bb = prep_verts.max(axis=0) - prep_verts.min(axis=0)

    for tmpl in library:
        tmpl_2d = _project_to_occlusal(tmpl.vertices)
        tmpl_hu = _compute_hu_moments(tmpl_2d)

        # Euclidean distance between log-Hu descriptor vectors
        dist = float(np.linalg.norm(prep_hu - tmpl_hu))

        if dist < min_dist:
            min_dist = dist
            best_template = tmpl

            # Compute scale factors
            tmpl_bb = tmpl.vertices.max(axis=0) - tmpl.vertices.min(axis=0)
            sx = float(prep_bb[0] / tmpl_bb[0]) if tmpl_bb[0] > 1e-6 else 1.0
            sy = float(prep_bb[1] / tmpl_bb[1]) if tmpl_bb[1] > 1e-6 else 1.0
            sz = float(prep_bb[2] / tmpl_bb[2]) if tmpl_bb[2] > 1e-6 else 1.0
            best_scale = (sx, sy, sz)

    # Convert distance to score: score = exp(-dist / scale) normalised to [0, 1]
    # Use reference scale from max inter-template distance
    all_dists = []
    for tmpl in library:
        d = float(np.linalg.norm(prep_hu - _compute_hu_moments(_project_to_occlusal(tmpl.vertices))))
        all_dists.append(d)

    max_dist = max(all_dists) if all_dists else 1.0
    if max_dist < 1e-12:
        best_score = 1.0
    else:
        best_score = float(1.0 - min_dist / max_dist)
    best_score = max(0.0, min(1.0, best_score))

    return TemplateMatch(
        template=best_template,
        morph_score=best_score,
        scale_factor=best_scale,
    )


def auto_design_crown_from_scan(
    scan: IntraoralScan,
    tooth_number: ToothNumber,
) -> "object":
    """
    End-to-end auto crown design: detect margin from prep, build from template.

    Pipeline:
    1. Build default tooth library for the given tooth number.
    2. Match best template using Hu moment descriptors.
    3. Design crown from matched template + preparation bounding box.

    Reference: Mörmann WH (2006) CEREC Bluecam workflow — automatic crown proposal.

    Parameters
    ----------
    scan : IntraoralScan
        Full arch scan containing the prepared tooth.
    tooth_number : ToothNumber
        The tooth to restore.

    Returns
    -------
    CrownDesign (from kerf_dental.crown_bridge)

    HONEST: Margin detection is based on bounding-box estimation from the scan.
    Production systems use dedicated margin line detection algorithms (marching
    surface descent + landmark annotation).
    """
    from kerf_dental.crown_bridge import (
        CrownDesignSpec, MarginLine, design_crown,
    )

    # Build library
    library = _make_default_library(tooth_number)

    if not library:
        raise RuntimeError(f"Failed to build template library for tooth {tooth_number.fdi}")

    # Use scan as prep mesh
    prep_mesh = (scan.vertices, scan.triangles)

    # Match template
    match = match_tooth_template(prep_mesh, tooth_number, library)

    # Build margin from scan bounding box (simplified prep margin detection)
    verts = scan.vertices
    centroid = verts.mean(axis=0)

    # Estimate margin at 20% height from bottom of scan
    bb_lo = verts.min(axis=0)
    bb_hi = verts.max(axis=0)
    margin_z = float(bb_lo[2] + 0.2 * (bb_hi[2] - bb_lo[2]))

    # Find vertices near this height
    near_margin = verts[np.abs(verts[:, 2] - margin_z) < 0.5]
    if len(near_margin) < 3:
        near_margin = verts[verts[:, 2] < np.percentile(verts[:, 2], 30)]

    if len(near_margin) < 3:
        near_margin = verts[:3]  # fallback

    # Build 16-point margin from near_margin (use evenly spaced subset)
    n_margin = 16
    angles = np.linspace(0, 2 * math.pi, n_margin, endpoint=False)
    mc = near_margin.mean(axis=0)

    # Estimate radius from near-margin cloud
    bb_range = near_margin.max(axis=0) - near_margin.min(axis=0)
    r_md = bb_range[0] / 2.0
    r_bl = bb_range[1] / 2.0
    margin_pts = np.column_stack([
        mc[0] + r_md * np.cos(angles),
        mc[1] + r_bl * np.sin(angles),
        np.full(n_margin, margin_z),
    ])

    margin = MarginLine(
        points=margin_pts,
        type="chamfer",
        width_mm=0.8,
    )

    spec = CrownDesignSpec(
        tooth_number=tooth_number,
        margin=margin,
        occlusal_clearance_mm=1.5,
        interproximal_contacts=[],
        material="zirconia",
    )

    return design_crown(spec, library_template=match.template.template_name)
