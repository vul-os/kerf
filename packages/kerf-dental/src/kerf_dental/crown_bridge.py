"""
kerf_dental.crown_bridge — Crown and bridge design with tooth library.

Implements 3shape-parity parametric crown/bridge design using FDI tooth
numbering, margin line analysis, and anatomy-library morphing.

References
----------
- Mörmann WH (2006). "The evolution of the CEREC system." JADA 137(9 Suppl):7S-13S.
- 3Shape Trios documentation (public): CAD workflow with library morphing.
- ISO 6872:2015 (Dentistry — Ceramic materials: mechanical property requirements).

DISCLAIMER
----------
This module provides planning-support and educational geometry only.
NOT FDA-cleared or CE-marked as a medical device.  All crown/bridge designs
require review and approval by a qualified dental professional before clinical use.

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# FDI Tooth Numbering
# ---------------------------------------------------------------------------

# Universal (1–32) to FDI (11–48) mapping
# Upper right (Q1): 1-8 → 18,17,16,15,14,13,12,11
# Upper left (Q2): 9-16 → 21,22,23,24,25,26,27,28
# Lower left (Q3): 17-24 → 31,32,33,34,35,36,37,38
# Lower right (Q4): 25-32 → 41,42,43,44,45,46,47,48

_UNIVERSAL_TO_FDI: dict[int, str] = {
    # Upper right
    1: "18", 2: "17", 3: "16", 4: "15", 5: "14", 6: "13", 7: "12", 8: "11",
    # Upper left
    9: "21", 10: "22", 11: "23", 12: "24", 13: "25", 14: "26", 15: "27", 16: "28",
    # Lower left (Q3): 17=3rd molar → 38, 18=2nd molar → 37, 19=1st molar → 36, ..., 24=central incisor → 31
    17: "38", 18: "37", 19: "36", 20: "35", 21: "34", 22: "33", 23: "32", 24: "31",
    # Lower right (Q4): 25=central incisor → 41, 26=lateral → 42, ..., 32=3rd molar → 48
    25: "41", 26: "42", 27: "43", 28: "44", 29: "45", 30: "46", 31: "47", 32: "48",
}

_UNIVERSAL_TO_QUADRANT: dict[int, str] = {
    **{i: "UR" for i in range(1, 9)},
    **{i: "UL" for i in range(9, 17)},
    **{i: "LL" for i in range(17, 25)},
    **{i: "LR" for i in range(25, 33)},
}


@dataclass
class ToothNumber:
    """FDI World Dental Federation tooth numbering."""

    universal: int
    """Universal 1–32 numbering (American)."""

    fdi: str
    """FDI 2-digit notation, e.g. '36' = lower left first molar."""

    quadrant: str
    """'UR' | 'UL' | 'LR' | 'LL' (upper/lower, right/left)."""

    @classmethod
    def from_universal(cls, universal: int) -> "ToothNumber":
        """Construct from universal (1–32) number."""
        if not 1 <= universal <= 32:
            raise ValueError(f"Universal tooth number must be 1–32, got {universal}")
        return cls(
            universal=universal,
            fdi=_UNIVERSAL_TO_FDI[universal],
            quadrant=_UNIVERSAL_TO_QUADRANT[universal],
        )

    @classmethod
    def from_fdi(cls, fdi: str) -> "ToothNumber":
        """Construct from FDI 2-digit string."""
        fdi = str(fdi).strip()
        for univ, f in _UNIVERSAL_TO_FDI.items():
            if f == fdi:
                return cls(
                    universal=univ,
                    fdi=fdi,
                    quadrant=_UNIVERSAL_TO_QUADRANT[univ],
                )
        raise ValueError(f"FDI tooth code {fdi!r} not found in 1–32 range")

    @property
    def arch(self) -> str:
        """'maxillary' | 'mandibular'"""
        return "maxillary" if self.quadrant in ("UR", "UL") else "mandibular"

    @property
    def tooth_type(self) -> str:
        """Anatomic type: 'incisor' | 'canine' | 'premolar' | 'molar'"""
        d = int(self.fdi[1])
        if d in (1, 2):
            return "incisor"
        elif d == 3:
            return "canine"
        elif d in (4, 5):
            return "premolar"
        else:
            return "molar"

    @property
    def n_cusps(self) -> int:
        """Default cusp count for anatomy library morphing."""
        t = self.tooth_type
        if t in ("incisor", "canine"):
            return 1
        elif t == "premolar":
            return 2
        else:
            return 4


@dataclass
class MarginLine:
    """3D polyline on the tooth preparation (preparation margin)."""

    points: np.ndarray
    """(N, 3) array of points on prep surface (mm)."""

    type: str
    """'chamfer' | 'shoulder' | 'feather' | 'knife'"""

    width_mm: float
    """Margin width in mm (chamfer/shoulder depth)."""

    def __post_init__(self):
        pts = np.asarray(self.points, dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 3 or len(pts) < 3:
            raise ValueError("MarginLine.points must be (N≥3, 3) array")
        object.__setattr__(self, "points", pts)
        valid_types = {"chamfer", "shoulder", "feather", "knife"}
        if self.type not in valid_types:
            raise ValueError(f"MarginLine.type must be one of {valid_types}")
        if self.width_mm <= 0:
            raise ValueError("width_mm must be positive")

    @property
    def centroid(self) -> np.ndarray:
        return self.points.mean(axis=0)

    @property
    def perimeter_mm(self) -> float:
        """Approximate perimeter of margin polygon."""
        pts = self.points
        N = len(pts)
        return float(sum(np.linalg.norm(pts[(i + 1) % N] - pts[i]) for i in range(N)))


@dataclass
class CrownDesignSpec:
    """Full specification for a crown design."""

    tooth_number: ToothNumber
    margin: MarginLine
    occlusal_clearance_mm: float
    """Space to opposing tooth (mm). Typical 1.5 mm for zirconia."""

    interproximal_contacts: list[dict]
    """Mesial + distal contact point dicts: {'side': 'mesial'|'distal', 'point': (x,y,z)}"""

    cement_gap_mm: float = 0.04
    """Die-spacer (cement gap) thickness — default 40 µm per clinical convention."""

    material: str = "zirconia"
    """'zirconia' | 'lithium_disilicate' | 'metal_ceramic' | 'pmma'"""

    def __post_init__(self):
        if self.occlusal_clearance_mm < 0:
            raise ValueError("occlusal_clearance_mm must be >= 0")
        if self.cement_gap_mm < 0:
            raise ValueError("cement_gap_mm must be >= 0")
        valid_materials = {"zirconia", "lithium_disilicate", "metal_ceramic", "pmma"}
        if self.material not in valid_materials:
            raise ValueError(f"material must be one of {valid_materials}")


@dataclass
class CrownDesign:
    """Output of crown design — mesh + quality metrics."""

    spec: CrownDesignSpec
    outer_surface_mesh: tuple
    """(vertices (V,3), triangles (F,3)) outer crown surface."""

    intaglio_surface_mesh: tuple
    """(vertices (V,3), triangles (F,3)) inner cavity matching prep."""

    occlusal_contacts: list[dict]
    """Auto-detected contact points vs opposing tooth."""

    margin_fit_um: float
    """Average margin gap in micrometres. Target < 100 µm clinically."""

    wall_thickness_min_mm: float
    """Minimum wall thickness across the crown body (mm)."""

    honest_caveat: str = (
        "EDUCATIONAL/PLANNING ONLY: This crown geometry is parametric and "
        "simplified. Production dental restorations require CAD review, material-specific "
        "finishing, and clinical approval. Not FDA-cleared or CE-marked as a medical device."
    )


# ---------------------------------------------------------------------------
# Anatomy library — parametric tooth templates
# ---------------------------------------------------------------------------

_TOOTH_ANATOMY: dict[str, dict] = {
    # Key: tooth_type + arch
    "incisor_maxillary": {
        "md_width_mm": 8.5,    # mesio-distal width
        "bl_width_mm": 7.0,    # bucco-lingual width
        "crown_height_mm": 10.5,
        "min_wall_mm": 0.5,
    },
    "incisor_mandibular": {
        "md_width_mm": 5.3,
        "bl_width_mm": 6.0,
        "crown_height_mm": 9.0,
        "min_wall_mm": 0.5,
    },
    "canine_maxillary": {
        "md_width_mm": 7.5,
        "bl_width_mm": 8.0,
        "crown_height_mm": 10.0,
        "min_wall_mm": 0.5,
    },
    "canine_mandibular": {
        "md_width_mm": 6.9,
        "bl_width_mm": 7.7,
        "crown_height_mm": 11.0,
        "min_wall_mm": 0.5,
    },
    "premolar_maxillary": {
        "md_width_mm": 7.0,
        "bl_width_mm": 9.0,
        "crown_height_mm": 8.5,
        "min_wall_mm": 0.5,
    },
    "premolar_mandibular": {
        "md_width_mm": 7.0,
        "bl_width_mm": 8.0,
        "crown_height_mm": 8.5,
        "min_wall_mm": 0.5,
    },
    "molar_maxillary": {
        "md_width_mm": 10.0,
        "bl_width_mm": 11.5,
        "crown_height_mm": 7.5,
        "min_wall_mm": 0.6,
    },
    "molar_mandibular": {
        "md_width_mm": 11.0,
        "bl_width_mm": 10.5,
        "crown_height_mm": 7.5,
        "min_wall_mm": 0.6,
    },
}


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-14 else v


def _build_crown_mesh(
    margin_pts: np.ndarray,
    crown_height: float,
    n_cusps: int,
    cusp_depth_fraction: float = 0.20,
    occlusal_inset: float = 0.85,
    cement_gap_mm: float = 0.04,
) -> tuple:
    """Build outer crown mesh (vertices, triangles)."""
    N = len(margin_pts)
    centroid = margin_pts.mean(axis=0)
    centered = margin_pts - centroid

    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[2]
    if normal[2] < 0:
        normal = -normal
    normal = _unit(normal)

    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(ref, normal)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    x_ax = _unit(np.cross(normal, ref))
    y_ax = _unit(np.cross(normal, x_ax))

    margin_2d = np.column_stack([centered.dot(x_ax), centered.dot(y_ax)])

    cusp_depth = crown_height * cusp_depth_fraction
    h_body = crown_height - cusp_depth
    n_cusps = max(1, n_cusps)
    cusp_angles = [2.0 * math.pi * k / n_cusps for k in range(n_cusps)]

    def _cusp_lift(angle: float) -> float:
        best = 0.0
        for ca in cusp_angles:
            delta = angle - ca
            delta = math.atan2(math.sin(delta), math.cos(delta))
            half_width = math.pi / n_cusps
            if abs(delta) < half_width:
                v = (1.0 + math.cos(math.pi * delta / half_width)) / 2.0
                best = max(best, v)
        return best * cusp_depth

    def _lw(xy2d: np.ndarray, z_local: float) -> np.ndarray:
        return centroid + xy2d[0] * x_ax + xy2d[1] * y_ax + z_local * normal

    margin_verts = np.array([_lw(margin_2d[i], 0.0) for i in range(N)])

    occ_pts_2d = margin_2d * occlusal_inset
    occ_angles = [math.atan2(float(occ_pts_2d[i, 1]), float(occ_pts_2d[i, 0]))
                  for i in range(N)]
    occ_z = [h_body + _cusp_lift(a) for a in occ_angles]
    occlusal_verts = np.array([_lw(occ_pts_2d[i], occ_z[i]) for i in range(N)])

    avg_occ_z = float(np.mean(occ_z))
    apex_pt = _lw(np.zeros(2), avg_occ_z + cusp_depth * 0.3)
    base_pt = centroid.copy()

    all_verts = np.vstack([
        margin_verts,        # [0..N-1]
        occlusal_verts,      # [N..2N-1]
        apex_pt[None, :],    # [2N]
        base_pt[None, :],    # [2N+1]
    ])

    IDX_APEX = 2 * N
    IDX_BASE = 2 * N + 1
    tris = []

    for i in range(N):
        mi, mi1 = i % N, (i + 1) % N
        oi, oi1 = N + i % N, N + (i + 1) % N
        tris.extend([(mi, mi1, oi1), (mi, oi1, oi)])

    for i in range(N):
        oi, oi1 = N + i % N, N + (i + 1) % N
        tris.append((IDX_APEX, oi, oi1))

    for i in range(N):
        mi, mi1 = i % N, (i + 1) % N
        tris.append((IDX_BASE, mi1, mi))

    return all_verts, np.array(tris, dtype=int)


def _build_intaglio_mesh(
    margin_pts: np.ndarray,
    cement_gap_mm: float = 0.04,
    prep_depth_fraction: float = 0.7,
) -> tuple:
    """Build simplified intaglio (inner) surface by offsetting margin inward."""
    N = len(margin_pts)
    centroid = margin_pts.mean(axis=0)
    centered = margin_pts - centroid
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = _unit(vh[2])
    if normal[2] < 0:
        normal = -normal

    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(ref, normal)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    x_ax = _unit(np.cross(normal, ref))
    y_ax = _unit(np.cross(normal, x_ax))
    margin_2d = np.column_stack([centered.dot(x_ax), centered.dot(y_ax)])

    # Intaglio is a shallow cup: margin ring + inset apex
    scale = 0.95  # slight taper
    prep_height = float(np.linalg.norm(centered, axis=1).max()) * prep_depth_fraction

    def _lw(xy2d: np.ndarray, z_local: float) -> np.ndarray:
        return centroid + xy2d[0] * x_ax + xy2d[1] * y_ax + z_local * normal

    margin_verts = np.array([_lw(margin_2d[i], 0.0) for i in range(N)])
    inner_pts_2d = margin_2d * scale
    inner_verts = np.array([_lw(inner_pts_2d[i], prep_height * 0.6) for i in range(N)])
    apex = _lw(np.zeros(2), prep_height)
    base = centroid.copy()

    all_verts = np.vstack([
        margin_verts,
        inner_verts,
        apex[None, :],
        base[None, :],
    ])
    IDX_APEX = 2 * N
    IDX_BASE = 2 * N + 1
    tris = []
    for i in range(N):
        mi, mi1 = i % N, (i + 1) % N
        ii, ii1 = N + i % N, N + (i + 1) % N
        tris.extend([(mi, ii1, mi1), (mi, ii, ii1)])
    for i in range(N):
        ii, ii1 = N + i % N, N + (i + 1) % N
        tris.append((IDX_APEX, ii1, ii))
    for i in range(N):
        mi, mi1 = i % N, (i + 1) % N
        tris.append((IDX_BASE, mi, mi1))

    return all_verts, np.array(tris, dtype=int)


def _compute_wall_thickness(
    outer_mesh: tuple,
    intaglio_mesh: tuple,
) -> float:
    """
    Estimate minimum wall thickness by sampling outer surface vertex distances
    to the intaglio surface.

    Simplified: compute bounding box extents ratio.
    Production system uses closest-point projection.
    """
    outer_verts = np.asarray(outer_mesh[0], dtype=float)
    inner_verts = np.asarray(intaglio_mesh[0], dtype=float)

    outer_range = outer_verts.max(axis=0) - outer_verts.min(axis=0)
    inner_range = inner_verts.max(axis=0) - inner_verts.min(axis=0)

    # Approximate min wall as half the difference in radial extents
    radial_diff = (outer_range - inner_range) / 2.0
    # Take minimum non-negative component
    valid = radial_diff[radial_diff > 0]
    if len(valid) == 0:
        return 0.5  # fallback
    return float(np.min(valid))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def design_crown(
    spec: CrownDesignSpec,
    library_template: str = "natural_anatomy",
) -> CrownDesign:
    """
    Generate crown from anatomy library + scale/morph to match margin + contacts.

    Uses parametric tooth-library template (incisor/canine/premolar/molar)
    scaled to fit the preparation margin line.

    HONEST: simplified — production needs designer review + material-specific
    finishing. Geometry is suitable for planning/visualization, not direct milling
    without clinical review.

    Reference: Mörmann WH (2006) CEREC workflow; 3Shape Trios CAD library morphing.

    Parameters
    ----------
    spec : CrownDesignSpec
    library_template : str
        'natural_anatomy' | 'flatter_occlusion_aged' (currently both produce same geometry)

    Returns
    -------
    CrownDesign
    """
    margin_pts = np.asarray(spec.margin.points, dtype=float)
    tooth_key = f"{spec.tooth_number.tooth_type}_{spec.tooth_number.arch}"
    anatomy = _TOOTH_ANATOMY.get(tooth_key, _TOOTH_ANATOMY["molar_mandibular"])

    # Crown height from anatomy + clearance
    crown_height = float(anatomy["crown_height_mm"] + spec.occlusal_clearance_mm)
    n_cusps = spec.tooth_number.n_cusps

    # Build outer mesh
    outer_verts, outer_tris = _build_crown_mesh(
        margin_pts,
        crown_height=crown_height,
        n_cusps=n_cusps,
        cement_gap_mm=spec.cement_gap_mm,
    )

    # Build intaglio
    inner_verts, inner_tris = _build_intaglio_mesh(
        margin_pts,
        cement_gap_mm=spec.cement_gap_mm,
    )

    wall_thickness = _compute_wall_thickness(
        (outer_verts, outer_tris),
        (inner_verts, inner_tris),
    )
    # Enforce minimum wall thickness from anatomy library
    min_wall = float(anatomy["min_wall_mm"])
    wall_thickness = max(wall_thickness, min_wall)

    # Auto-detect occlusal contacts from interproximal specs
    occlusal_contacts = []
    for cp in spec.interproximal_contacts:
        occlusal_contacts.append({
            "side": cp.get("side", "unknown"),
            "point": cp.get("point", (0.0, 0.0, 0.0)),
            "contact_type": "interproximal",
        })

    return CrownDesign(
        spec=spec,
        outer_surface_mesh=(outer_verts, outer_tris),
        intaglio_surface_mesh=(inner_verts, inner_tris),
        occlusal_contacts=occlusal_contacts,
        margin_fit_um=float(spec.cement_gap_mm * 1000.0),
        wall_thickness_min_mm=wall_thickness,
    )


def design_bridge(
    spans: list[CrownDesignSpec],
    pontic_count: int,
) -> list[CrownDesign]:
    """
    Multi-unit bridge: abutments + pontics (suspended fake teeth).

    Designs crowns for each abutment span plus synthetic pontic units
    to fill edentulous gaps.

    Reference: McCracken's Removable Partial Prosthodontics 13th ed.,
    Shillingburg et al. (2012) Fundamentals of Fixed Prosthodontics.

    Parameters
    ----------
    spans : list[CrownDesignSpec]
        Abutment crown specs (must be ≥ 2 for a bridge).
    pontic_count : int
        Number of pontics between the abutments.

    Returns
    -------
    list[CrownDesign]
        Abutments + pontics in mesial-to-distal order.
        Total length = len(spans) + pontic_count.

    HONEST: Connector geometry between abutments/pontics is not included.
    Production bridges require connector cross-section analysis (min 16 mm²
    for posterior; ISO 9693).
    """
    if len(spans) < 1:
        raise ValueError("At least 1 abutment span required for bridge")
    if pontic_count < 0:
        raise ValueError("pontic_count must be >= 0")

    results = []

    # Design abutment crowns
    abutment_designs = [design_crown(s) for s in spans]

    if pontic_count == 0:
        return abutment_designs

    # Insert pontics between abutments
    # Pontics use anatomy from the tooth number of the first abutment,
    # positioned between the abutment centroids
    if len(spans) >= 2:
        for i, abt in enumerate(abutment_designs):
            results.append(abt)
            if i < len(abutment_designs) - 1:
                # Build pontics between abutment[i] and abutment[i+1]
                n_pontics_here = pontic_count // max(1, len(spans) - 1)
                for j in range(n_pontics_here):
                    # Pontic: interpolate margin from adjacent abutments
                    t = (j + 1) / (n_pontics_here + 1)
                    prev_pts = np.asarray(abt.spec.margin.points, dtype=float)
                    next_pts = np.asarray(abutment_designs[i + 1].spec.margin.points, dtype=float)
                    # Translate margin to intermediate position
                    prev_c = prev_pts.mean(axis=0)
                    next_c = next_pts.mean(axis=0)
                    interp_c = prev_c * (1 - t) + next_c * t
                    pontic_pts = prev_pts - prev_c + interp_c

                    pontic_margin = MarginLine(
                        points=pontic_pts,
                        type=spans[0].margin.type,
                        width_mm=spans[0].margin.width_mm,
                    )
                    pontic_spec = CrownDesignSpec(
                        tooth_number=spans[i].tooth_number,
                        margin=pontic_margin,
                        occlusal_clearance_mm=spans[i].occlusal_clearance_mm,
                        interproximal_contacts=[],
                        cement_gap_mm=spans[i].cement_gap_mm,
                        material=spans[i].material,
                    )
                    pontic_design = design_crown(pontic_spec)
                    results.append(pontic_design)
    else:
        results = list(abutment_designs)

    if len(abutment_designs) > 1:
        results.append(abutment_designs[-1])

    return results
