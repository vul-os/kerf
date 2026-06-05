"""
kerf_dental.surgical_guide — Drill-guide design from implant plan.

Generates 3D-printable surgical guides with drill sleeves matching
implant axis directions from an ImplantPlan set.

References
----------
- Cassetta M et al. (2013). "How accurate is a guided implant surgery?
  A systematic review." Med Oral Patol Oral Cir Bucal 18(3):e461-9.
- Di Giacomo GAP et al. (2005). "Clinical application of stereolithographic
  surgical guides for implant placement." Int J Oral Maxillofac Implants 20:271-8.
- 3Shape Implant Studio (public documentation) — guide shell thickness 2.5 mm.

DISCLAIMER
----------
NOT FDA-cleared or CE-marked as a medical device. Surgical guides must be
clinically verified by a qualified dental surgeon before use.

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from kerf_dental.implant_plan_v2 import ImplantPlan, ImplantPosition


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DrillSleeve:
    """Cylindrical drill sleeve fitted to guide body."""

    inner_diameter_mm: float
    """Inner bore diameter matching drill protocol diameter (mm)."""

    outer_diameter_mm: float
    """Outer sleeve diameter (mm). Typically inner + 3.0 mm wall."""

    length_mm: float
    """Sleeve height (mm). Typical 5–8 mm."""

    position: ImplantPosition
    """Implant position the sleeve is designed for."""

    def __post_init__(self):
        if self.inner_diameter_mm <= 0 or self.outer_diameter_mm <= 0:
            raise ValueError("Sleeve diameters must be positive")
        if self.outer_diameter_mm <= self.inner_diameter_mm:
            raise ValueError("outer_diameter_mm must be > inner_diameter_mm")
        if self.length_mm <= 0:
            raise ValueError("length_mm must be positive")

    @property
    def wall_thickness_mm(self) -> float:
        return (self.outer_diameter_mm - self.inner_diameter_mm) / 2.0

    @property
    def axis_direction(self) -> np.ndarray:
        return self.position.axis_direction


@dataclass
class SurgicalGuide:
    """Complete surgical guide with arch shell, drill sleeves, and inspection windows."""

    arch_support_mesh: tuple
    """(vertices (V,3), triangles (F,3)) — rigid shell that sits on teeth."""

    sleeves: list[DrillSleeve]
    """One drill sleeve per implant position."""

    fenestrations: list[dict]
    """Cooling/inspection windows: list of {'center': (x,y,z), 'radius_mm': float}

    Inspection fenestrations serve two clinical purposes:
    1. Visual — surgeon can see tissue through the guide.
    2. Cooling — coolant reaches the drilling site (ISO 22977-compliant irrigation).

    Reference: Di Giacomo GAP et al. (2005) Int J Oral Maxillofac Implants 20:271-8.
    Recommended: ≥ 3 windows, radius ≥ 2 mm, spaced evenly along buccal flange.
    """

    sleeve_guide_stops: list[dict] = None
    """Drill-stop rings: list of {'sleeve_idx': int, 'depth_mm': float, 'ring_diam_mm': float}

    Guide stops prevent over-drilling by limiting insertion depth.
    Each stop is a raised ring on the sleeve exterior that contacts the drill
    handle when the target depth is reached.

    Reference: Cassetta M et al. (2013) Med Oral Patol Oral Cir Bucal 18(3):e461-9
    — guided surgery accuracy ±0.4 mm with metal sleeves.
    """

    fit_tolerance_mm: float = 0.1
    """Gap between guide and tooth surface (mm).

    Typical 0.05–0.15 mm for SLA-printed resin.
    Wider tolerance for bone-supported guides.
    Reference: 3Shape Implant Studio guide fit defaults (public IFU).
    """

    material: str = "biocompatible_resin"
    """SLA-printable material. 'biocompatible_resin' (default) | 'nylon_pa12'

    Biocompatible resin: ISO 10993-5 cytotoxicity tested, Class IIa CE marking required.
    Nylon PA12: for bone-supported guides with higher mechanical loads.
    """

    honest_caveat: str = (
        "EDUCATIONAL/PLANNING ONLY: This surgical guide geometry is parametric. "
        "Production guides require CBCT-based arch scanning, clinical fit testing, "
        "and surgeon approval. Guide accuracy ±0.5 mm typical (Cassetta et al. 2013). "
        "Material must be ISO 10993-5 biocompatibility-certified. "
        "NOT FDA-cleared or CE-marked as a medical device."
    )

    def __post_init__(self):
        if self.sleeve_guide_stops is None:
            self.sleeve_guide_stops = []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_arch_shell_mesh(
    arch_pts: np.ndarray,
    shell_offset_mm: float = 2.5,
    n_cols: int = 32,
) -> tuple:
    """
    Build a simplified arch shell by offsetting the arch point cloud inward.

    Strategy:
    1. Compute PCA normal of arch surface.
    2. Build a rectangular shell mesh from arch bounding box with thickness.
    3. This is a placeholder — production uses conformal offset of intraoral scan.

    Parameters
    ----------
    arch_pts : (N, 3) arch surface points
    shell_offset_mm : offset thickness (mm)

    Returns
    -------
    (vertices, triangles)
    """
    pts = np.asarray(arch_pts, dtype=float)
    if len(pts) < 3:
        raise ValueError("arch_pts must have at least 3 points")

    # Bounding box approach
    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    center = (lo + hi) / 2.0

    # Build a simple slab over the arch bounding box
    # Outer surface = at hi[2] + shell_offset_mm
    # Inner surface = at hi[2] (arch contact surface)
    x0, y0 = float(lo[0]), float(lo[1])
    x1, y1 = float(hi[0]), float(hi[1])
    z_outer = float(hi[2]) + shell_offset_mm
    z_inner = float(hi[2])

    # 8 corners of a box
    verts = np.array([
        [x0, y0, z_inner], [x1, y0, z_inner], [x1, y1, z_inner], [x0, y1, z_inner],  # bottom
        [x0, y0, z_outer], [x1, y0, z_outer], [x1, y1, z_outer], [x0, y1, z_outer],  # top
    ], dtype=float)

    # 12 triangles for a box
    tris = np.array([
        [0, 2, 1], [0, 3, 2],  # bottom face (inner)
        [4, 5, 6], [4, 6, 7],  # top face (outer)
        [0, 1, 5], [0, 5, 4],  # front
        [1, 2, 6], [1, 6, 5],  # right
        [2, 3, 7], [2, 7, 6],  # back
        [3, 0, 4], [3, 4, 7],  # left
    ], dtype=int)

    return verts, tris


def _build_sleeve_mesh(
    sleeve: DrillSleeve,
    n_sides: int = 24,
) -> tuple:
    """
    Build cylindrical sleeve mesh.

    Returns (vertices, triangles) for the annular cylinder.
    """
    inner_r = sleeve.inner_diameter_mm / 2.0
    outer_r = sleeve.outer_diameter_mm / 2.0
    h = sleeve.length_mm

    axis = sleeve.position.axis_direction
    origin = sleeve.position.platform_position.copy()

    # Build local frame
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(axis, ref))) > 0.99:
        ref = np.array([1.0, 0.0, 0.0])
    u = np.cross(axis, ref)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    v /= np.linalg.norm(v)

    angles = np.linspace(0.0, 2 * math.pi, n_sides, endpoint=False)
    cos_a, sin_a = np.cos(angles), np.sin(angles)

    verts = []
    faces = []

    def ring(center, r):
        base = len(verts)
        for ca, sa in zip(cos_a, sin_a):
            verts.append(center + r * (ca * u + sa * v))
        return base

    top = origin + axis * h
    ob0 = ring(origin, outer_r)
    ot0 = ring(top, outer_r)
    ib0 = ring(origin, inner_r)
    it0 = ring(top, inner_r)

    for i in range(n_sides):
        j = (i + 1) % n_sides
        faces += [[ob0+i, ob0+j, ot0+j], [ob0+i, ot0+j, ot0+i]]
        faces += [[ib0+j, ib0+i, it0+i], [ib0+j, it0+i, it0+j]]
        # Top annular cap
        faces += [[ot0+i, ot0+j, it0+j], [ot0+i, it0+j, it0+i]]
        # Bottom annular cap
        faces += [[ob0+j, ob0+i, ib0+i], [ob0+j, ib0+i, ib0+j]]

    return np.array(verts, dtype=float), np.array(faces, dtype=int)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def design_surgical_guide(
    plan: list[ImplantPlan],
    arch_model: tuple,
    sleeve_wall_mm: float = 1.5,
    sleeve_height_mm: float = 5.0,
    n_fenestrations: int = 3,
) -> SurgicalGuide:
    """
    Surface offset arch shell + cylindrical sleeves at implant positions.

    Each sleeve bore is coaxial with the corresponding implant axis direction.

    Parameters
    ----------
    plan : list[ImplantPlan]
        One or more implant plans.
    arch_model : (vertices, triangles)
        Intraoral scan of the arch (from load_intraoral_stl).
    sleeve_wall_mm : float
        Sleeve wall thickness (mm). Default 1.5 mm.
    sleeve_height_mm : float
        Sleeve protrusion height above arch (mm). Default 5.0 mm.
    n_fenestrations : int
        Number of ventilation/inspection windows in the guide. Default 3.

    Returns
    -------
    SurgicalGuide

    HONEST: Arch shell is a simplified bounding-box approximation.
    Production guides use full conformal offset of the intraoral scan surface.
    """
    arch_verts = np.asarray(arch_model[0], dtype=float)
    arch_shell_verts, arch_shell_tris = _build_arch_shell_mesh(arch_verts)

    sleeves = []
    for p in plan:
        sleeve = DrillSleeve(
            inner_diameter_mm=p.implant.diameter_mm,
            outer_diameter_mm=p.implant.diameter_mm + 2.0 * sleeve_wall_mm,
            length_mm=sleeve_height_mm,
            position=p.position,
        )
        sleeves.append(sleeve)

    # Fenestrations: evenly spaced along the arch bounding box X extent
    x_range = arch_verts[:, 0].max() - arch_verts[:, 0].min()
    y_mid = float(arch_verts[:, 1].mean())
    z_top = float(arch_verts[:, 2].max())
    fenestrations = []
    for i in range(n_fenestrations):
        t = (i + 0.5) / n_fenestrations
        fx = float(arch_verts[:, 0].min()) + t * x_range
        fenestrations.append({
            "center": (fx, y_mid, z_top + 1.5),
            "radius_mm": 2.0,
            "type": "cooling",
        })

    # Build drill-stop rings: depth-stop at implant length to prevent over-drilling.
    # Reference: Cassetta M et al. (2013) — guide stops limit depth error to ±0.4 mm.
    guide_stops = []
    for idx, (p, sleeve) in enumerate(zip(plan, sleeves)):
        stop_depth = p.implant.length_mm  # drill to implant length exactly
        guide_stops.append({
            "sleeve_idx": idx,
            "depth_mm": stop_depth,
            "ring_diam_mm": sleeve.outer_diameter_mm + 2.0,
            "ring_height_mm": 1.5,
            "note": f"Cassetta 2013 depth stop — ±0.4 mm accuracy at {stop_depth:.1f} mm depth",
        })

    return SurgicalGuide(
        arch_support_mesh=(arch_shell_verts, arch_shell_tris),
        sleeves=sleeves,
        fenestrations=fenestrations,
        sleeve_guide_stops=guide_stops,
    )
