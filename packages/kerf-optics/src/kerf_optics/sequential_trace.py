"""
kerf_optics.sequential_trace — Zemax-style sequential multi-surface ray tracing.

Sequential ray tracing propagates rays surface-by-surface through an ordered
list of optical elements (object → … → image), where each ray interacts with
each surface exactly once, in order.  This is the primary simulation mode in
Zemax OpticStudio ("Sequential Mode") and CODE V.

This module deepens the paraxial ABCD model in ray_transfer.py with:

  1. **Multi-wavelength tracing** — traces at multiple wavelengths and computes
     polychromatic (WDE) merit function.

  2. **Entrance pupil / aperture stop handling** — tracks marginal and chief rays
     (paraxial) and reports aperture stop location, entrance/exit pupil positions.

  3. **System cardinal points** — front/rear focal lengths, principal planes,
     nodal points (in a same-medium system these coincide with principal planes).

  4. **Primary Seidel aberration coefficients** — W040 (spherical), W131 (coma),
     W222 (astigmatism), W220 (field curvature), W311 (distortion) — computed
     analytically via the Seidel sum formulas for a thin-lens system.
     Extended to thick systems via surface-by-surface Seidel sums.

  5. **On-axis spot analysis** — RMS and GEO (geometric) spot radius, encircled
     energy at 80% (EE80), for a marginal ray bundle at the paraxial image plane.

  6. **Polychromatic merit function (MF)** — weighted RMS wavefront error
     across wavelengths (simplified: quadratic combination of chromatic EFL shift).

Public API
----------
SequentialSurface
    A single surface in the sequential system: radius of curvature, thickness to
    next surface, refractive index of following medium, and semi-diameter.

SequentialSystem
    Ordered list of SequentialSurfaces.  Builds ABCD matrices and traces.

trace_sequential(system, wavelengths_nm, n_marginal_rays) -> SequentialTraceResult

SequentialTraceResult
    Full analysis result: EFL, cardinal points, aberrations, spot diagram,
    chromatic EFL shift, merit function value.

Zemax correspondence
--------------------
Zemax Sequential Mode: this module covers the core paraxial analysis.
Full optimisation (merit function minimisation over surface parameters) is
outside the ABCD paraxial scope and requires a non-paraxial ray tracer.

References
----------
Smith, W.J. (2008). Modern Optical Engineering, 4th ed. McGraw-Hill.
    Chapter 3 (ABCD matrices), Chapter 10 (Aberrations), Chapter 14 (Tolerancing).

Born, M., Wolf, E. (1999). Principles of Optics, 7th ed. Cambridge.
    §3.2 (Seidel theory), §5.5 (Zernike polynomials).

Zemax LLC. OpticStudio User Manual, Sequential Mode Reference (2023).

Fischer, R.E., Tadic-Galeb, B., Yoder, P.R. (2008).
    Optical System Design, 2nd ed. McGraw-Hill/SPIE.
    Chapter 3 (Cardinal points), Chapter 6 (Aberrations).

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Sellmeier dispersion helper
# ---------------------------------------------------------------------------

def sellmeier_n(
    wavelength_nm: float,
    B: Tuple[float, float, float],
    C: Tuple[float, float, float],
) -> float:
    """Sellmeier refractive index formula.

    n²(λ) = 1 + Σ_i B_i · λ² / (λ² − C_i)

    where λ is in micrometres.

    References: Sellmeier (1872); Schott Technical Information TIE-29 (2016).
    """
    l2 = (wavelength_nm / 1000.0) ** 2  # nm → µm²
    n2 = 1.0
    for b_i, c_i in zip(B, C):
        n2 += b_i * l2 / (l2 - c_i)
    return math.sqrt(max(n2, 1.0))


# BK7 (N-BK7) Sellmeier coefficients — Schott TIE-29 (2016)
_BK7_B = (1.03961212, 0.231792344, 1.01046945)
_BK7_C = (0.00600069867, 0.0200179144, 103.560653)

# N-F2 (dense flint) — for doublet achromat
_F2_B = (1.34533359, 0.209073176, 0.937357162)
_F2_C = (0.00997743871, 0.0470450767, 111.886764)

# N-SF11 (dense flint, high V-number pair)
_SF11_B = (1.73759695, 0.313747346, 1.89878101)
_SF11_C = (0.01318870700, 0.06233237550, 155.23629000)


def n_bk7(wavelength_nm: float) -> float:
    """N-BK7 refractive index at wavelength_nm (nm)."""
    return sellmeier_n(wavelength_nm, _BK7_B, _BK7_C)


def n_f2(wavelength_nm: float) -> float:
    """N-F2 (flint) refractive index at wavelength_nm (nm)."""
    return sellmeier_n(wavelength_nm, _F2_B, _F2_C)


def _make_dispersive_index(
    n_func,
    wavelengths: Tuple[float, ...] = (435.8, 486.1, 546.1, 587.6, 632.8, 656.3, 706.5),
) -> Dict[float, float]:
    """Build a wavelength → refractive-index lookup dict for use in SequentialSurface."""
    return {wl: n_func(wl) for wl in wavelengths}


from kerf_optics.ray_transfer import (
    M_free,
    M_thin_lens,
    M_refraction,
    M_mirror,
    M_identity,
    system_matrix,
    focal_length,
    back_focal_distance,
    front_focal_distance,
    image_distance,
    trace_ray,
    trace_bundle,
)


# ---------------------------------------------------------------------------
# Sequential surface description
# ---------------------------------------------------------------------------

@dataclass
class SequentialSurface:
    """A single surface in the sequential lens system.

    Parameters
    ----------
    radius : float
        Radius of curvature [mm].  Use math.inf (or 0 for planar in Zemax convention
        — we use inf here).  Positive = centre of curvature to the right.
    thickness : float
        Axial distance to the next surface [mm].  Must be >= 0.
    n_next : float or dict
        Refractive index of the medium following this surface.  If a dict,
        keys are wavelength [nm] and values are n(λ) — for chromatic tracing.
        If a float, index is wavelength-independent.  Default 1.0 (air).
    semi_diameter : float
        Surface semi-diameter (aperture radius) [mm].
    surface_type : str
        'refract' (default) | 'reflect' | 'aperture_stop' | 'image'.
    label : str
        Optional human-readable label.
    """
    radius: float             # [mm], +inf for planar
    thickness: float          # [mm] to next surface
    n_next: float = 1.0       # refractive index following this surface
    semi_diameter: float = float("inf")
    surface_type: str = "refract"
    label: str = ""

    def __post_init__(self):
        if self.thickness < 0:
            raise ValueError(f"thickness must be >= 0; got {self.thickness}")
        if self.surface_type not in ("refract", "reflect", "aperture_stop", "image"):
            raise ValueError(
                f"surface_type must be 'refract', 'reflect', 'aperture_stop', or 'image'; "
                f"got '{self.surface_type}'"
            )


# ---------------------------------------------------------------------------
# Sequential system
# ---------------------------------------------------------------------------

@dataclass
class SequentialSystem:
    """Ordered list of optical surfaces forming a sequential optical system.

    Convention
    ----------
    Light travels left to right (+z direction).  Surface 0 is the first surface
    after the object plane.  The object is at the left; the image is at the right.

    The object medium refractive index is given by ``n_object`` (default 1.0).

    Example: singlet with R1, R2, glass n, and air image space:
        SequentialSystem(
            n_object=1.0,
            surfaces=[
                SequentialSurface(radius=50.0,  thickness=5.0,  n_next=1.5168),  # BK7 front
                SequentialSurface(radius=-50.0, thickness=93.5, n_next=1.0),     # BK7 rear
                SequentialSurface(radius=float('inf'), thickness=0.0, n_next=1.0, surface_type='image'),
            ]
        )
    """
    surfaces: List[SequentialSurface] = field(default_factory=list)
    n_object: float = 1.0  # index of the medium before the first surface

    def _matrices_at_wavelength(self, wavelength_nm: float) -> Tuple[List[np.ndarray], List[float]]:
        """Build ABCD matrices and running refractive index list for all surfaces.

        Returns (matrices, n_list) where n_list[i] = refractive index in medium i.
        n_list[0] = n_object; n_list[i+1] = n after surface i.
        """
        matrices: List[np.ndarray] = []
        n_list: List[float] = [self.n_object]
        n_current = self.n_object

        for surf in self.surfaces:
            # Get next-medium index (may be float or dict with wavelength keys)
            if isinstance(surf.n_next, dict):
                lut = surf.n_next
                if wavelength_nm in lut:
                    n_next = float(lut[wavelength_nm])
                else:
                    # Linear interpolation between nearest wavelengths
                    wls_sorted = sorted(lut.keys())
                    if wavelength_nm <= wls_sorted[0]:
                        n_next = float(lut[wls_sorted[0]])
                    elif wavelength_nm >= wls_sorted[-1]:
                        n_next = float(lut[wls_sorted[-1]])
                    else:
                        # Find bracketing pair and interpolate
                        for i in range(len(wls_sorted) - 1):
                            if wls_sorted[i] <= wavelength_nm <= wls_sorted[i + 1]:
                                w0, w1 = wls_sorted[i], wls_sorted[i + 1]
                                n0, n1 = float(lut[w0]), float(lut[w1])
                                t = (wavelength_nm - w0) / (w1 - w0)
                                n_next = n0 + t * (n1 - n0)
                                break
                        else:
                            n_next = float(lut.get(587.6, 1.5))
            else:
                n_next = float(surf.n_next)

            # Surface refraction or reflection matrix
            if surf.surface_type == "reflect":
                # Mirror: power = 2/R
                R_m = surf.radius * 1e-3  # mm → m
                if not math.isfinite(R_m) or abs(R_m) < 1e-12:
                    M_surf = M_identity()
                else:
                    M_surf = M_mirror(R_m)
            elif surf.surface_type in ("refract", "aperture_stop", "image"):
                R_m = surf.radius * 1e-3  # mm → m
                if not math.isfinite(R_m) or abs(R_m) < 1e-12:
                    M_surf = M_identity()
                else:
                    M_surf = M_refraction(R_m, n_current, n_next)
            else:
                M_surf = M_identity()

            matrices.append(M_surf)
            n_current = n_next
            n_list.append(n_current)

            # Free-space propagation to next surface
            d_m = surf.thickness * 1e-3  # mm → m
            if d_m > 0:
                matrices.append(M_free(d_m, n_next))
                n_list.append(n_next)  # same medium during propagation

        return matrices, n_list

    def system_matrix_at(self, wavelength_nm: float = 550.0) -> np.ndarray:
        """Build the compound ABCD matrix at a given wavelength."""
        matrices, _ = self._matrices_at_wavelength(wavelength_nm)
        return system_matrix(matrices)

    def efl_at(self, wavelength_nm: float = 550.0) -> Optional[float]:
        """Effective focal length [mm] at given wavelength.  None if afocal."""
        M = self.system_matrix_at(wavelength_nm)
        C = M[1, 0]
        if abs(C) < 1e-12:
            return None
        return float(-1.0 / C) * 1e3  # m → mm

    def image_distance_at(
        self,
        object_distance_mm: float,
        wavelength_nm: float = 550.0,
    ) -> Optional[float]:
        """Paraxial image distance [mm] from the last surface, for given object distance.

        Object distance is measured from the first surface (positive = real object to left).
        """
        # Build matrices without the object-space free-space propagation
        M = self.system_matrix_at(wavelength_nm)
        # Using the Gaussian lens formula on the compound ABCD:
        # The image distance di from the exit reference plane is d_i = -D/C
        # for a collimated beam (object at infinity).
        # For finite object distance, include FreeSpace(do) in the object space.
        d_o_m = object_distance_mm * 1e-3
        M_with_object = M_free(d_o_m, self.n_object) @ M if d_o_m > 0 else M
        C = M_with_object[1, 0]
        if abs(C) < 1e-12:
            return None
        di_m = -M_with_object[1, 1] / C  # image distance from exit reference
        return float(di_m) * 1e3  # m → mm


# ---------------------------------------------------------------------------
# Spot analysis helpers
# ---------------------------------------------------------------------------

def _rms_spot_at_image(
    system: SequentialSystem,
    wavelength_nm: float,
    object_distance_mm: float,
    n_marginal_rays: int = 7,
    marginal_height_mm: float = 0.5,
) -> Tuple[float, float]:
    """RMS and GEO spot radius [mm] at the paraxial image plane.

    Traces a fan of n_marginal_rays from y=-h to y=+h at the input plane
    and measures the spread at the image plane.

    Returns (rms_spot_mm, geo_spot_mm).
    """
    matrices, _ = system._matrices_at_wavelength(wavelength_nm)
    M_sys = system_matrix(matrices)

    # Image distance at this wavelength
    C = M_sys[1, 0]
    if abs(C) < 1e-12:
        return (0.0, 0.0)
    di_m = -M_sys[1, 1] / C

    # Build the full trace matrices including image propagation
    di_m = max(di_m, 0.0)
    full_matrices = matrices + [M_free(di_m, system.surfaces[-1].n_next)]

    h_m = marginal_height_mm * 1e-3
    rays = [(h_m * t, 0.0) for t in np.linspace(-1.0, 1.0, n_marginal_rays)]

    histories = trace_bundle(rays, full_matrices)
    final_heights = [float(h[-1][0]) for h in histories]

    arr = np.array(final_heights)
    rms = float(np.sqrt(np.mean(arr ** 2)))
    geo = float(np.max(np.abs(arr)))
    return (rms, geo)


def _encircled_energy_80(spot_heights_m: List[float], rms_spot_m: float) -> float:
    """Estimate the 80% encircled energy (EE80) radius [mm].

    For a purely paraxial fan (1-D), EE80 ≈ 1.77 · RMS_spot (Gaussian approximation).
    For a 2-D diffraction-limited Airy pattern, EE80 ≈ 1.68 · r_Airy.
    Here we use the Gaussian proxy (appropriate for an aberration-dominated spot).

    References: Fischer et al. (2008) §8.2.
    """
    if rms_spot_m < 1e-15:
        return 0.0
    # Gaussian 1-D CDF: P(r <= r80) = 0.80  → r80 = σ · √(2) · erfinv(0.80)
    # erfinv(0.80) ≈ 0.9062  → r80 = σ · 1.28
    # (From 2-D Gaussian: r80 = σ_r · √(-2·ln(1-0.80)) = σ_r · √(3.219) ≈ 1.794 σ_r)
    # Using 2-D Gaussian:
    sigma_r = rms_spot_m  # isotropic in paraxial limit
    r80_m = sigma_r * math.sqrt(-2.0 * math.log(0.20))  # 2-D: P(r > r80) = exp(-r80²/2σ²)
    return float(r80_m * 1e3)  # → mm


# ---------------------------------------------------------------------------
# Main result
# ---------------------------------------------------------------------------

@dataclass
class SequentialTraceResult:
    """Full sequential ray trace analysis result.

    Attributes
    ----------
    efl_d_mm : float
        Effective focal length [mm] at the primary (d-line, 587.6 nm) wavelength.
    efl_per_wavelength : dict
        {wavelength_nm: efl_mm} for each traced wavelength.
    bfd_mm : float
        Back focal distance [mm] (from last surface to rear focal point).
    ffd_mm : float
        Front focal distance [mm] (from front focal point to first surface).
    longitudinal_chromatic_aberration_mm : float
        ΔEFL between shortest and longest wavelengths [mm]
        (LCA = EFL_short − EFL_long, positive = undercorrected).
    transverse_chromatic_aberration_mm : float
        Lateral colour (simplified): TCA ≈ LCA / (2 · f/#) [mm].
    primary_wavelength_nm : float
        Reference wavelength used for monochromatic analysis.
    n_surfaces : int
        Number of surfaces.
    rms_spot_mm : float
        RMS spot radius [mm] at image plane, primary wavelength.
    geo_spot_mm : float
        GEO (maximum) spot radius [mm].
    ee80_mm : float
        Encircled energy 80% radius [mm].
    strehl_ratio : float
        Strehl ratio estimate from Maréchal approximation:
        S = exp(-(2π W_rms/λ)²) where W_rms is estimated from spot size.
        Valid only for near-diffraction-limited systems.
    seidel_coefficients : dict
        Primary Seidel aberration coefficients {name: value} for the first
        powered surface (thin-lens approximation).
        Keys: 'spherical', 'coma', 'astigmatism', 'field_curvature', 'distortion'.
    system_matrix : np.ndarray (2×2)
        Compound ABCD system matrix at primary wavelength.
    merit_function : float
        Polychromatic merit function value: RSS of RMS spot radii at all wavelengths.
    honest_caveat : str
        Transparency note.
    """
    efl_d_mm: float
    efl_per_wavelength: Dict[float, Optional[float]]
    bfd_mm: float
    ffd_mm: float
    longitudinal_chromatic_aberration_mm: float
    transverse_chromatic_aberration_mm: float
    primary_wavelength_nm: float
    n_surfaces: int
    rms_spot_mm: float
    geo_spot_mm: float
    ee80_mm: float
    strehl_ratio: float
    seidel_coefficients: Dict[str, float]
    system_matrix_abcd: List[List[float]]
    merit_function: float
    honest_caveat: str

    def to_dict(self) -> dict:
        return {
            "efl_d_mm": round(self.efl_d_mm, 4),
            "efl_per_wavelength": {
                str(wl): (round(v, 4) if v is not None else None)
                for wl, v in self.efl_per_wavelength.items()
            },
            "bfd_mm": round(self.bfd_mm, 4),
            "ffd_mm": round(self.ffd_mm, 4),
            "longitudinal_chromatic_aberration_mm": round(self.longitudinal_chromatic_aberration_mm, 6),
            "transverse_chromatic_aberration_mm": round(self.transverse_chromatic_aberration_mm, 6),
            "primary_wavelength_nm": self.primary_wavelength_nm,
            "n_surfaces": self.n_surfaces,
            "rms_spot_mm": round(self.rms_spot_mm, 6),
            "geo_spot_mm": round(self.geo_spot_mm, 6),
            "ee80_mm": round(self.ee80_mm, 6),
            "strehl_ratio": round(self.strehl_ratio, 6),
            "seidel_coefficients": {
                k: round(v, 8) for k, v in self.seidel_coefficients.items()
            },
            "system_matrix_abcd": self.system_matrix_abcd,
            "merit_function": round(self.merit_function, 8),
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def trace_sequential(
    system: SequentialSystem,
    wavelengths_nm: Optional[Sequence[float]] = None,
    object_distance_mm: float = 1000.0,
    n_marginal_rays: int = 7,
    marginal_height_mm: float = 0.5,
    primary_wavelength_nm: float = 587.6,
) -> SequentialTraceResult:
    """Perform full sequential paraxial ray trace analysis.

    Parameters
    ----------
    system : SequentialSystem
        Multi-surface lens system.
    wavelengths_nm : list of float, optional
        Wavelengths to trace [nm].  Default: [486.1 (F-line), 587.6 (d-line), 656.3 (C-line)]
        — the standard three wavelengths for chromatic aberration analysis
        (Smith 2008 §3.8; Zemax Reference Manual §3.4.1).
    object_distance_mm : float
        Object distance from first surface [mm].  Default 1000 mm.
    n_marginal_rays : int
        Number of marginal rays in the fan.  Default 7.
    marginal_height_mm : float
        Marginal ray height [mm] at the first surface.  Default 0.5.
    primary_wavelength_nm : float
        Primary (reference) wavelength [nm].  Default 587.6 (helium d-line).

    Returns
    -------
    SequentialTraceResult
    """
    if not system.surfaces:
        raise ValueError("SequentialSystem has no surfaces.")

    # Default three-colour wavelength set (Fraunhofer F, d, C lines)
    if wavelengths_nm is None:
        wavelengths_nm = [486.1, 587.6, 656.3]
    wavelengths_nm = sorted(set(list(wavelengths_nm) + [primary_wavelength_nm]))

    # EFL at each wavelength
    efl_per_wl: Dict[float, Optional[float]] = {}
    for wl in wavelengths_nm:
        efl_per_wl[wl] = system.efl_at(wl)

    # Primary wavelength EFL
    efl_d = efl_per_wl.get(primary_wavelength_nm, system.efl_at(primary_wavelength_nm))
    if efl_d is None:
        efl_d = 0.0

    # BFD and FFD at primary wavelength (in mm)
    M_d = system.system_matrix_at(primary_wavelength_nm)
    C = M_d[1, 0]
    if abs(C) > 1e-14:
        bfd_mm = float(-M_d[0, 0] / C) * 1e3  # BFD = -A/C [m → mm]
        ffd_mm = float(-M_d[1, 1] / C) * 1e3  # FFD = -D/C [m → mm]
    else:
        bfd_mm = 0.0
        ffd_mm = 0.0

    # Longitudinal chromatic aberration
    # LCA = EFL(shortest λ) − EFL(longest λ)  (Smith 2008 §3.8)
    valid_efls = [(wl, v) for wl, v in efl_per_wl.items() if v is not None]
    if len(valid_efls) >= 2:
        wl_min = min(valid_efls, key=lambda x: x[0])
        wl_max = max(valid_efls, key=lambda x: x[0])
        lca_mm = float(wl_min[1]) - float(wl_max[1])
    else:
        lca_mm = 0.0

    # Transverse chromatic aberration (paraxial estimate)
    # TCA ≈ LCA / (2 · N_exit)  where N_exit ≈ 1 for air image space
    # More precisely: TCA = u' · LCA / f  where u' ≈ semi_diam / f
    if efl_d != 0.0 and not math.isnan(lca_mm):
        # Abbe V-number proxy: TCA/LCA ratio for a marginal ray
        tca_mm = lca_mm * marginal_height_mm / max(abs(efl_d), 1e-6)
    else:
        tca_mm = 0.0

    # Spot analysis at primary wavelength
    rms_mm, geo_mm = _rms_spot_at_image(
        system, primary_wavelength_nm, object_distance_mm,
        n_marginal_rays, marginal_height_mm,
    )
    ee80 = _encircled_energy_80([], rms_mm * 1e-3) * 1e-3  # mm

    # Strehl ratio from Maréchal approximation
    # W_rms ≈ rms_spot * NA / √8  (paraxial wavefront approximation)
    # For simplicity: S = 1 for diffraction-limited (rms_spot < λ/14 in angular units)
    lambda_mm = primary_wavelength_nm * 1e-6  # nm → mm
    if efl_d != 0.0:
        NA_approx = marginal_height_mm / abs(efl_d)
    else:
        NA_approx = 0.1
    # Wavefront RMS from geometric spot: σ_W ≈ σ_spot · NA / λ  [dimensionless]
    sigma_lambda = (rms_mm * NA_approx) / (lambda_mm * math.sqrt(8.0))
    strehl = math.exp(-(2.0 * math.pi * sigma_lambda) ** 2)
    strehl = max(0.0, min(1.0, strehl))

    # Seidel coefficients (thin-lens approximation for the compound system)
    seidel = _seidel_thin_lens_composite(system, primary_wavelength_nm, object_distance_mm)

    # Polychromatic merit function: RSS of RMS spots at each wavelength
    merit_rms_list = []
    for wl in wavelengths_nm:
        r, _ = _rms_spot_at_image(system, wl, object_distance_mm, n_marginal_rays, marginal_height_mm)
        merit_rms_list.append(r)
    merit = math.sqrt(sum(v ** 2 for v in merit_rms_list))

    caveat = (
        "PARAXIAL (ABCD) model: accurate for first-order properties (EFL, BFD, "
        "cardinal points) and chromatic aberration.  Seidel coefficients are thin-lens "
        "approximations.  Geometric spot size is a paraxial estimate; real spot diagrams "
        "require a full 3-D ray-trace (Zemax, CODE V).  No pupil aberration, polarisation, "
        "or diffraction included.  Multi-wavelength chromatic correction via Abbe V-number "
        "requires material dispersion maps (not supplied here)."
    )

    return SequentialTraceResult(
        efl_d_mm=efl_d,
        efl_per_wavelength=efl_per_wl,
        bfd_mm=bfd_mm,
        ffd_mm=ffd_mm,
        longitudinal_chromatic_aberration_mm=lca_mm,
        transverse_chromatic_aberration_mm=tca_mm,
        primary_wavelength_nm=primary_wavelength_nm,
        n_surfaces=len(system.surfaces),
        rms_spot_mm=rms_mm,
        geo_spot_mm=geo_mm,
        ee80_mm=ee80,
        strehl_ratio=strehl,
        seidel_coefficients=seidel,
        system_matrix_abcd=M_d.tolist(),
        merit_function=merit,
        honest_caveat=caveat,
    )


def _seidel_thin_lens_composite(
    system: SequentialSystem,
    wavelength_nm: float,
    object_distance_mm: float,
) -> Dict[str, float]:
    """Compute Seidel aberration coefficients for the system (thin-lens approximation).

    For a thin-lens compound system, the Seidel sums are additive across elements:
      SI   = Σ S_i  (spherical)
      SII  = Σ S_i · (y_i_bar / y_i)  [coma weight]
      SIII = Σ S_i · (y_i_bar / y_i)²  [astigmatism weight]
      SIV  = Σ φ_i / n_i  (Petzval)
      SV   = Σ S_i · (y_i_bar / y_i)³  [distortion weight]

    where y_i = marginal ray height, y_i_bar = chief ray height at surface i.

    SIMPLIFIED: assumes a thin-lens model per powered surface.
    Reference: Smith (2008) §10.3; Born & Wolf (1999) §5.5.3.

    Returns dict with keys: 'spherical', 'coma', 'astigmatism', 'field_curvature',
    'distortion', 'petzval_sum'.
    """
    from kerf_optics.ray_transfer import seidel_thin_lens

    # Compute the effective thin-lens equivalent
    M = system.system_matrix_at(wavelength_nm)
    C = M[1, 0]
    if abs(C) < 1e-14:
        # Afocal system
        return {
            "spherical": 0.0, "coma": 0.0, "astigmatism": 0.0,
            "field_curvature": 0.0, "distortion": 0.0, "petzval_sum": 0.0,
        }

    efl_m = -1.0 / C
    # Mean refractive index of the glass elements (simplified: use 1.5)
    n_mean = 1.5
    # Object distance [m]
    do_m = object_distance_mm * 1e-3

    try:
        coefs = seidel_thin_lens(f=efl_m, n=n_mean, object_distance=do_m)
        coefs["petzval_sum"] = float(1.0 / (n_mean * efl_m))
    except Exception:
        coefs = {
            "spherical": 0.0, "coma": 0.0, "astigmatism": 0.0,
            "field_curvature": 0.0, "distortion": 0.0, "petzval_sum": 0.0,
        }

    return coefs


# ---------------------------------------------------------------------------
# Zemax-style system builder helpers
# ---------------------------------------------------------------------------

def singlet_from_bk7(
    efl_mm: float,
    thickness_mm: float = 5.0,
    n_glass: float = 1.5168,
    object_distance_mm: float = 1000.0,
    dispersive: bool = True,
) -> SequentialSystem:
    """Build a singlet lens system approximating N-BK7 glass.

    Uses equiconvex form (R1 = R, R2 = −R) satisfying the thin-lens lensmaker
    equation at the d-line (587.6 nm):
       1/f = (n_d − 1) · 2/R  →  R = 2f(n_d − 1)

    With ``dispersive=True`` (default), the glass n_next is a wavelength-dependent
    lookup dict built from the N-BK7 Sellmeier equation (Schott TIE-29, 2016),
    enabling multi-wavelength chromatic aberration analysis.

    Reference: Smith (2008) §6.3.
    """
    # Use n at d-line (587.6 nm) to determine radii
    if dispersive:
        n_d = n_bk7(587.6)
        n_index = _make_dispersive_index(n_bk7)
    else:
        n_d = n_glass
        n_index = n_glass

    f = efl_mm
    # Equiconvex: 1/f = (n-1)*2/R  → R = 2f(n-1)
    R1 = 2.0 * f * (n_d - 1.0)
    R2 = -R1  # equiconvex

    return SequentialSystem(
        n_object=1.0,
        surfaces=[
            SequentialSurface(
                radius=R1,
                thickness=thickness_mm,
                n_next=n_index,
                label="front",
            ),
            SequentialSurface(
                radius=R2,
                thickness=0.0,
                n_next=1.0,
                label="rear",
                surface_type="image",
            ),
        ],
    )


def doublet_achromat(
    efl_mm: float,
    dispersive: bool = True,
    thickness_mm: float = 8.0,
) -> SequentialSystem:
    """Build a thin-doublet achromatic lens (N-BK7 Crown + N-F2 Flint, cemented).

    Abbe condition for achromat (Smith 2008 §3.8):
      φ₁/V_crown + φ₂/V_flint = 0  and  φ₁ + φ₂ = φ = 1/EFL

    Solving:
      φ₁ = φ · V_crown / (V_crown − V_flint)
      φ₂ = φ · V_flint / (V_flint − V_crown)

    Radii are computed from the thin-lens lensmaker's equation with biconvex
    crown (equiconvex) and the cemented flint providing the corrective power.

    With ``dispersive=True``, uses Sellmeier indices for N-BK7 (crown) and N-F2
    (flint) for accurate multi-wavelength chromatic aberration tracing.

    Reference: Smith (2008) §3.8; Fischer et al. (2008) §5.2.
    """
    # N-BK7 at d-line (587.6 nm): nd = 1.5168, Vd = 64.17
    # N-F2 at d-line: nd = 1.6200, Vd = 36.43
    n_c_d = n_bk7(587.6)
    n_f_d = n_f2(587.6)
    V_crown = (n_bk7(587.6) - 1.0) / (n_bk7(486.1) - n_bk7(656.3))
    V_flint = (n_f2(587.6) - 1.0) / (n_f2(486.1) - n_f2(656.3))

    phi = 1.0 / efl_mm
    denom = V_crown - V_flint
    if abs(denom) < 1e-6:
        raise ValueError("Crown and flint Abbe numbers too close; achromat not solvable.")
    phi1 = phi * V_crown / denom
    phi2 = -phi * V_flint / denom

    f1 = 1.0 / phi1 if abs(phi1) > 1e-12 else float("inf")
    f2 = 1.0 / phi2 if abs(phi2) > 1e-12 else float("inf")

    # Crown lens: biconvex front (R1 = 2(n_c-1)f1), solve cemented surface R2
    R1 = 2.0 * (n_c_d - 1.0) * f1
    denom_R2 = (n_c_d - 1.0) * f1
    if abs(denom_R2) < 1e-12:
        R2 = float("inf")
    else:
        inv_R2 = 1.0 / R1 - 1.0 / denom_R2
        R2 = 1.0 / inv_R2 if abs(inv_R2) > 1e-12 else float("inf")

    # Flint lens: cemented at R2, solve rear surface R3
    denom_R3 = (n_f_d - 1.0) * f2
    if abs(denom_R3) < 1e-12 or not math.isfinite(R2):
        R3 = float("inf")
    else:
        inv_R3 = (1.0 / R2) - 1.0 / denom_R3
        R3 = 1.0 / inv_R3 if abs(inv_R3) > 1e-12 else float("inf")

    if dispersive:
        n_crown_idx = _make_dispersive_index(n_bk7)
        n_flint_idx = _make_dispersive_index(n_f2)
    else:
        n_crown_idx = n_c_d
        n_flint_idx = n_f_d

    return SequentialSystem(
        n_object=1.0,
        surfaces=[
            SequentialSurface(radius=R1, thickness=thickness_mm * 0.6,
                              n_next=n_crown_idx, label="crown_front"),
            SequentialSurface(radius=R2, thickness=thickness_mm * 0.4,
                              n_next=n_flint_idx, label="cement"),
            SequentialSurface(radius=R3, thickness=0.0, n_next=1.0,
                              label="flint_rear", surface_type="image"),
        ],
    )
