"""
kerf_cad_core.optics.lens_volume — glass volume and weight of a singlet lens.

Computes the glass volume and weight of a spherical-surface singlet (single-element)
lens from first principles, using the spherical-cap volume formula.

Theory (Smith "Modern Optical Engineering" 4th ed. §13 / Mahajan "Optical Imaging
and Aberrations" §1)
------------------------------------------------------------------------
For a lens with clear-aperture radius r, the sagitta (sag) of a spherical surface
of radius R is:

    h = R - sqrt(R² - r²)          [Smith §13.3 eq. 13.6]

The volume of a spherical cap of height h and base radius r is:

    V_cap = π·h²·(3R − h) / 3      [Smith §13.3 eq. 13.7; Mahajan §1.2]

The total lens volume is computed as:

    V_lens = π·r²·t_c  ± V_cap1  ± V_cap2

where t_c is the center thickness and the sign of each cap term depends on the
surface curvature:
  - Convex surface (curves away from glass, forms a dome): subtract cap (material
    has been removed from the reference cylinder).
  - Concave surface (curves into the glass, forms a bowl): add cap (material is
    present beyond the reference cylinder boundary).
  - Flat surface (|R| ≥ 1×10¹⁵ mm): cap height = 0, contribute nothing.

Sign convention (Cartesian, same as the lensmaker's equation)
--------------------------------------------------------------
  R > 0  : centre of curvature to the RIGHT of the surface.
             → Front surface convex  (dome pointing toward object).
             → Rear surface concave  (concave toward image).
  R < 0  : centre of curvature to the LEFT of the surface.
             → Front surface concave (bowl facing object).
             → Rear surface convex  (dome pointing toward image).
  R = ±∞ : flat surface (plano).

For the front surface (surface 1):
  R1 > 0  → surface is convex toward object → cap is SUBTRACTED from cylinder.
  R1 < 0  → surface is concave toward object → cap is ADDED to cylinder.

For the rear surface (surface 2):
  R2 < 0  → surface is convex toward image → cap is SUBTRACTED from cylinder.
  R2 > 0  → surface is concave toward image → cap is ADDED to cylinder.

Edge thickness
--------------
For a convex surface: the lens is thinner at the edge than at the centre.
For a concave surface: the lens is thicker at the edge.

    t_edge = t_center − sag1·sign1 − sag2·sign2

where sign = +1 for convex (subtracts material at edge) and −1 for concave.

Lens form classification
------------------------
Based on the Cartesian-sign of R1 and R2:

  biconvex    : R1 > 0 and R2 < 0
  biconcave   : R1 < 0 and R2 > 0
  plano_convex: one surface flat, the other convex (R1 > 0 R2=∞ or R1=∞ R2<0)
  plano_concave: one surface flat, the other concave
  meniscus    : both surfaces curved in the same direction (R1 and R2 same-sign)

HONEST CAVEATS
--------------
1. Spherical surfaces only. The sagitta formula h = R − √(R² − r²) applies to
   spherical surfaces.  Aspheric surfaces (conic sections, polynomial aspheres,
   freeform) require numerical integration of h(r²) = R·c·r²/(1+√(1−(1+k)c²r²))
   + Σ_i A_i·r^(2i) over the clear aperture.  Out of scope here.
2. No anti-reflection coating thickness.  AR coating layers are 100–500 nm thick
   and contribute negligibly to weight (< 0.01 g) but are not modelled.
3. Density is homogeneous.  Real glass melts have radial and axial density gradients
   (Schott TIE-31 §3); gradient-index (GRIN) lenses have radially-varying density.
   The homogeneous model is accurate to better than 0.3% for standard optical glasses.
4. Clear-aperture radius (not physical lens radius).  If the physical blank diameter
   exceeds the clear aperture, the actual weight will be larger.  Always use the
   physical blank radius for accurate weight budgets.
5. The center thickness must be positive and consistent (edge thickness must remain
   positive; a physically impossible lens is flagged with a warning).

References
----------
Smith, W.J. — "Modern Optical Engineering", 4th ed. McGraw-Hill, 2008.
    §13.3 (Lens Volume and Weight), §13.4 (Lens Forms).
Mahajan, V.N. — "Optical Imaging and Aberrations, Part I", SPIE Press, 2d ed. 2011.
    §1.2 (Sagitta and spherical cap geometry).
Schott AG — Technical Note TIE-29 "Refractive Index and Dispersion", 2016.
Schott AG — Technical Note TIE-31 "Homogeneity of Optical Glass", 2023.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Flat-surface threshold: |R| > _FLAT_THRESH is treated as plano (sag → 0)
# ---------------------------------------------------------------------------
_FLAT_THRESH = 1e15  # mm


# ---------------------------------------------------------------------------
# SingletLensSpec
# ---------------------------------------------------------------------------

@dataclass
class SingletLensSpec:
    """
    Specification for a spherical-surface singlet (single-element) lens.

    Attributes
    ----------
    radius_R1_mm : float
        Radius of curvature of the first (object-side) surface in mm.
        Positive → convex toward object (centre of curvature to the right).
        Use math.inf (or 1e18) for a flat surface.
    radius_R2_mm : float
        Radius of curvature of the second (image-side) surface in mm.
        Negative → convex toward image (centre of curvature to the left).
        Use math.inf (or 1e18) for a flat surface.
    center_thickness_mm : float
        Axial thickness at the optical axis (must be > 0).
    clear_aperture_radius_mm : float
        Semi-diameter of the optically used zone (must be > 0).
        For weight budgets, use the physical blank semi-diameter instead.
    glass_density_g_cm3 : float
        Glass density in g/cm³.  Default = 2.51 g/cm³ (Schott BK7).
        Common values: BK7 = 2.51, N-BK7 ≈ 2.51, SF11 = 4.74, N-SF11 ≈ 4.74,
        CaF2 ≈ 3.18, fused silica ≈ 2.20, N-LAK22 ≈ 3.67.
    """
    radius_R1_mm: float
    radius_R2_mm: float
    center_thickness_mm: float
    clear_aperture_radius_mm: float
    glass_density_g_cm3: float = 2.51  # BK7 default


# ---------------------------------------------------------------------------
# LensVolumeReport
# ---------------------------------------------------------------------------

@dataclass
class LensVolumeReport:
    """
    Volume and weight report for a spherical-surface singlet lens.

    Attributes
    ----------
    volume_mm3 : float
        Total glass volume in mm³.
    weight_g : float
        Glass weight in grams = volume_mm3 × density_g_per_mm3.
    edge_thickness_mm : float
        Lens thickness at the clear-aperture edge.  Positive for a physically
        realisable lens; negative indicates an impossible geometry (center
        thickness too small for the given radii and aperture).
    sag1_mm : float
        Sagitta of the first surface at the clear-aperture radius (mm).
    sag2_mm : float
        Sagitta of the second surface at the clear-aperture radius (mm).
    lens_form : str
        One of: "biconvex", "biconcave", "plano_convex", "plano_concave",
        "meniscus", "plano_plano" (flat-flat, unusual but valid).
    honest_caveat : str
        Scope limitations: spherical surfaces only; no AR coating; homogeneous
        density; clear aperture ≠ blank diameter.
    """
    volume_mm3: float
    weight_g: float
    edge_thickness_mm: float
    sag1_mm: float
    sag2_mm: float
    lens_form: str
    honest_caveat: str = field(default=(
        "Spherical surfaces only — aspheric sag requires numerical integration "
        "of h(ρ²)=Rc·ρ²/(1+√(1−(1+k)c²ρ²))+ΣA_i·ρ^(2i) (out of scope). "
        "No anti-reflection coating mass (AR layers ~100–500 nm, negligible). "
        "Homogeneous density assumed; GRIN or melt-inhomogeneous glass may differ "
        "by up to ~0.3% (Schott TIE-31 §3). "
        "clear_aperture_radius is the optically-used zone; physical blank radius "
        "will be larger, giving higher actual weight."
    ))

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict with ok=True."""
        return {
            "ok": True,
            "volume_mm3": round(self.volume_mm3, 4),
            "weight_g": round(self.weight_g, 5),
            "edge_thickness_mm": round(self.edge_thickness_mm, 4),
            "sag1_mm": round(self.sag1_mm, 6),
            "sag2_mm": round(self.sag2_mm, 6),
            "lens_form": self.lens_form,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sagitta(R_mm: float, r_mm: float) -> float:
    """
    Compute the sagitta (sag) of a spherical surface of radius R_mm at
    semi-diameter r_mm.

    h = |R| − sqrt(|R|² − r²)

    For a flat surface (|R| ≥ _FLAT_THRESH), returns 0.0.
    Raises ValueError if r > |R| (semi-diameter exceeds radius of curvature,
    which would make the square root imaginary — physically impossible for a
    complete spherical cap).

    References: Smith MOE §13.3 eq. 13.6; Mahajan §1.2.
    """
    abs_R = abs(R_mm)
    if abs_R >= _FLAT_THRESH:
        return 0.0
    arg = abs_R ** 2 - r_mm ** 2
    if arg < 0.0:
        raise ValueError(
            f"Semi-diameter {r_mm:.4f} mm exceeds radius of curvature |R|={abs_R:.4f} mm. "
            "Physically impossible: clear aperture cannot exceed the radius of the "
            "spherical surface."
        )
    return abs_R - math.sqrt(arg)


def _spherical_cap_volume(sag_mm: float, R_mm: float) -> float:
    """
    Volume of a spherical cap of height h and sphere radius |R|.

    V_cap = π·h²·(3·|R| − h) / 3     [Smith MOE §13.3 eq. 13.7]

    For h = 0 (flat surface), returns 0.
    """
    if sag_mm == 0.0:
        return 0.0
    abs_R = abs(R_mm)
    return math.pi * sag_mm ** 2 * (3.0 * abs_R - sag_mm) / 3.0


def _classify_lens_form(R1: float, R2: float) -> str:
    """
    Classify lens form from surface radii using the Cartesian sign convention.

    R1 > 0 → front surface convex toward object.
    R1 < 0 → front surface concave toward object.
    R2 < 0 → rear surface convex toward image.
    R2 > 0 → rear surface concave toward image.
    |R| ≥ _FLAT_THRESH → flat (plano).

    Classification table (Smith MOE §13.4):
      biconvex     : R1 > 0 and R2 < 0   (positive lens, thicker at centre)
      biconcave    : R1 < 0 and R2 > 0   (negative lens, thicker at edge)
      plano_convex : one flat + one convex
      plano_concave: one flat + one concave
      meniscus     : both curved, same direction (R1 and R2 same sign, non-flat)
      plano_plano  : both flat (window / parallel plate)
    """
    flat1 = abs(R1) >= _FLAT_THRESH
    flat2 = abs(R2) >= _FLAT_THRESH

    if flat1 and flat2:
        return "plano_plano"

    # Convexity flags (True = that surface is convex outward)
    conv1 = (not flat1) and (R1 > 0)   # front convex toward object
    conv2 = (not flat2) and (R2 < 0)   # rear  convex toward image

    conc1 = (not flat1) and (R1 < 0)
    conc2 = (not flat2) and (R2 > 0)

    if flat1 or flat2:
        # One surface is flat
        convex_side = conv1 or conv2
        if convex_side:
            return "plano_convex"
        return "plano_concave"

    # Both surfaces curved
    if conv1 and conv2:
        return "biconvex"
    if conc1 and conc2:
        return "biconcave"
    # Mixed: meniscus (same bending direction — one convex, one concave toward same side)
    return "meniscus"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_lens_volume(spec: SingletLensSpec) -> "LensVolumeReport | dict":
    """
    Compute the glass volume and weight of a singlet lens.

    Algorithm (Smith "Modern Optical Engineering" §13.3)
    -----------------------------------------------------
    1. Compute the sagitta of each surface at the clear-aperture radius:
           h_i = |R_i| − sqrt(|R_i|² − r²)
       For flat surfaces (|R_i| ≥ 1×10¹⁵ mm), h_i = 0.

    2. Compute the spherical cap volume of each surface:
           V_cap_i = π·h_i²·(3·|R_i| − h_i) / 3

    3. Determine whether each surface cap contributes positively or negatively
       to the lens volume (relative to the reference cylinder V_cyl = π·r²·t_c):
       - Surface 1 (front):  convex (R1 > 0) → subtract V_cap_1
                             concave (R1 < 0) → add V_cap_1
       - Surface 2 (rear):   convex (R2 < 0) → subtract V_cap_2
                             concave (R2 > 0) → add V_cap_2

    4. V_lens = V_cyl + sign1·V_cap_1 + sign2·V_cap_2
       (sign = +1 for concave / adds material; −1 for convex / removes material)

    5. Weight = V_lens × ρ
       where ρ = density_g_cm3 × 1×10⁻³  g/mm³   (1 cm³ = 1000 mm³)

    Parameters
    ----------
    spec : SingletLensSpec
        Lens specification including radii, thickness, clear aperture, and density.

    Returns
    -------
    LensVolumeReport
        Volume, weight, edge thickness, sag values, and honest caveats.
    dict
        ``{"ok": False, "reason": "..."}`` on validation error.

    Validation oracle (depth bar)
    -----------------------------
    Plano-convex BK7: R1=+100 mm, R2=∞, ct=5 mm, CA_r=12.5 mm, ρ=2.51 g/cm³
        sag1 = 100 − √(10000 − 156.25) = 0.7843 mm
        V_cap1 = π·(0.7843)²·(300 − 0.7843)/3 = 192.76 mm³
        V_cyl  = π·(12.5)²·5 = 2454.37 mm³
        V_lens = 2454.37 − 192.76 = 2261.61 mm³
        weight = 2261.61 × 2.51×10⁻³ = 5.677 g
    """
    # --- Input validation --------------------------------------------------
    if not isinstance(spec, SingletLensSpec):
        return {"ok": False, "reason": "spec must be a SingletLensSpec instance"}

    if not math.isfinite(spec.center_thickness_mm) or spec.center_thickness_mm <= 0:
        return {
            "ok": False,
            "reason": f"center_thickness_mm must be > 0, got {spec.center_thickness_mm}",
        }
    if not math.isfinite(spec.clear_aperture_radius_mm) or spec.clear_aperture_radius_mm <= 0:
        return {
            "ok": False,
            "reason": (
                f"clear_aperture_radius_mm must be > 0, got {spec.clear_aperture_radius_mm}"
            ),
        }
    if not math.isfinite(spec.glass_density_g_cm3) or spec.glass_density_g_cm3 <= 0:
        return {
            "ok": False,
            "reason": f"glass_density_g_cm3 must be > 0, got {spec.glass_density_g_cm3}",
        }

    R1 = spec.radius_R1_mm
    R2 = spec.radius_R2_mm
    r = spec.clear_aperture_radius_mm
    ct = spec.center_thickness_mm

    # --- Sagitta computation ----------------------------------------------
    try:
        h1 = _sagitta(R1, r)
        h2 = _sagitta(R2, r)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}

    # --- Spherical cap volumes -------------------------------------------
    V_cap1 = _spherical_cap_volume(h1, R1)
    V_cap2 = _spherical_cap_volume(h2, R2)

    # --- Sign convention for caps ----------------------------------------
    # Surface 1 (front):
    #   R1 > 0 (convex toward object) → cap removes material → subtract
    #   R1 < 0 (concave toward object) → cap adds material  → add
    #   flat (|R1| >= _FLAT_THRESH)   → h1 = 0, no contribution
    flat1 = abs(R1) >= _FLAT_THRESH
    flat2 = abs(R2) >= _FLAT_THRESH

    sign1 = 0.0
    if not flat1:
        sign1 = -1.0 if R1 > 0 else +1.0   # convex → subtract; concave → add

    # Surface 2 (rear):
    #   R2 < 0 (convex toward image, i.e. centre of curvature to the LEFT) → subtract
    #   R2 > 0 (concave toward image) → add
    sign2 = 0.0
    if not flat2:
        sign2 = -1.0 if R2 < 0 else +1.0   # convex (R2<0) → subtract; concave → add

    # --- Lens volume ------------------------------------------------------
    V_cylinder = math.pi * r ** 2 * ct
    V_lens = V_cylinder + sign1 * V_cap1 + sign2 * V_cap2

    if V_lens <= 0.0:
        return {
            "ok": False,
            "reason": (
                f"Computed lens volume is non-positive ({V_lens:.4f} mm³). "
                "The geometry is physically impossible: the center thickness is "
                "too small for the given surface radii and clear aperture."
            ),
        }

    # --- Edge thickness ---------------------------------------------------
    # sign1>0 (concave) adds sag at edge (thicker); sign1<0 (convex) removes (thinner)
    # edge_thickness = center_thickness - sign1_thickness_effect1 - sign2_thickness_effect2
    # For convex surfaces: they reduce edge thickness → subtract sag
    # For concave surfaces: they increase edge thickness → add sag
    # Effect of surface 1 on edge thickness:
    #   convex front (R1>0) → edge is thinner by h1: -h1
    #   concave front (R1<0) → edge is thicker by h1: +h1
    # Effect of surface 2 on edge thickness:
    #   convex rear (R2<0) → edge is thinner by h2: -h2
    #   concave rear (R2>0) → edge is thicker by h2: +h2

    edge_thickness = ct
    if not flat1:
        edge_thickness += (h1 if R1 < 0 else -h1)
    if not flat2:
        edge_thickness += (h2 if R2 > 0 else -h2)

    # --- Lens form classification ----------------------------------------
    lens_form = _classify_lens_form(R1, R2)

    # --- Weight -----------------------------------------------------------
    density_g_per_mm3 = spec.glass_density_g_cm3 * 1e-3  # g/cm³ → g/mm³
    weight_g = V_lens * density_g_per_mm3

    # --- Build caveat string with edge-thickness warning if needed --------
    base_caveat = LensVolumeReport.__dataclass_fields__["honest_caveat"].default
    extra = ""
    if edge_thickness < 0.0:
        extra = (
            " WARNING: computed edge_thickness < 0, indicating a physically "
            "impossible lens geometry (center thickness too thin for these radii "
            "and clear aperture)."
        )
    honest_caveat = base_caveat + extra

    return LensVolumeReport(
        volume_mm3=V_lens,
        weight_g=weight_g,
        edge_thickness_mm=edge_thickness,
        sag1_mm=h1,
        sag2_mm=h2,
        lens_form=lens_form,
        honest_caveat=honest_caveat,
    )
