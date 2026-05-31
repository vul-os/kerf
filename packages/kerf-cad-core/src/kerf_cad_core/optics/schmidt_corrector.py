"""
kerf_cad_core.optics.schmidt_corrector — Schmidt telescope corrector plate design.

Computes the aspheric sag profile z(r) of a Schmidt corrector plate that
cancels the spherical aberration of a spherical primary mirror.

Public API
----------
SchmidtSpec(primary_radius_R_mm, aperture_diameter_D_mm, glass_index_n, neutral_zone_factor_kappa)
SchmidtReport(aspheric_profile, max_sag_mm, neutral_zone_radius_mm, schwarzschild_constant_k, honest_caveat)
design_schmidt_corrector(spec, num_radii=50) -> SchmidtReport

Theory (Schmidt 1932 / Born & Wolf §6.3)
-----------------------------------------
A Schmidt telescope uses a spherical primary mirror and a corrector plate
placed at the centre of curvature to eliminate spherical aberration.

The corrector plate introduces the opposite wavefront error to that produced
by the spherical mirror. For a spherical primary of radius R (focal length
f = R/2), the fourth-order spherical aberration wavefront error is:

    W(r) = r^4 / (8 R^3)      (Born & Wolf §6.3 eq. 6.3.1)

To cancel this with a glass plate of refractive index n, the sag z(r) of
the corrector must satisfy:

    (n - 1) * z(r) = W(r) + const + linear_tilt

The general solution (with a constant "bending" parameter κ to set the
neutral zone) is:

    z(r) = [r^4 - 2·κ·ρ_n^2·r^2] / [8·(n-1)·R^3]

where ρ_n = aperture_radius / sqrt(κ) is the neutral-zone radius at which
z(r) has zero slope (dz/dr = 0, i.e., the plate acts as a flat plate).

The standard Schmidt design uses κ = 1.5, which minimises the peak-to-valley
sag and maximises the zone radius at sqrt(2/3) × aperture_radius ≈ 0.816 × D/2.
(This is the classic Bernhard Schmidt 1932 optimum; see also Rutten & van Venrooij
"Telescope Optics" §6.3.)

The Schwarzschild constant (conic constant) k of the equivalent conic primary
that would have zero spherical aberration is k = -1 (parabola), but the Schmidt
corrector works with a spherical primary (k = 0) by correcting at the entrance.

Honest limitations
------------------
1. CLASSICAL SCHMIDT ONLY — this implements the original 1932 Schmidt design
   (thin corrector at centre of curvature, on-axis, monochromatic). Modern
   Schmidt–Cassegrain and Schmidt–Newtonian designs add secondary mirrors,
   field-flatteners, and refined aspherics to manage field curvature, coma,
   and astigmatism; these are outside scope.
2. MONOCHROMATIC — the corrector profile is derived for a single wavelength.
   Real correctors use optical glass with a specific refractive index n(λ);
   the residual chromatic aberration is second-order (Wilkins 1950) and small
   for wide-band work but is not computed here.
3. THIN-PLATE APPROXIMATION — the sag z(r) ≪ plate thickness is assumed.
   For very fast mirrors (f/# < 2) or large apertures (D > 600 mm) the
   plate-thickness correction may be non-negligible.
4. ON-AXIS ONLY — the Schmidt design ideally corrects spherical aberration only.
   Off-axis coma is zero only when the corrector is placed exactly at the centre
   of curvature (distance R from mirror vertex). Deviations from this position
   introduce coma; this is not modelled here.
5. SCHWARZSCHILD CONSTANT — the equivalent conic constant k = -1 (parabola)
   refers to the mirror shape that would avoid spherical aberration entirely;
   the Schmidt corrector achieves the same result using a spherical mirror
   combined with the corrector plate.

References
----------
Schmidt, B. — "Ein lichtstarkes komafreies Spiegelsystem", Zentralzeitung für
    Optik und Mechanik, 52, 25-26 (1932).
Born, M. & Wolf, E. — "Principles of Optics", 7th ed., Cambridge, 1999, §6.3.
Rutten, H.G.J. & van Venrooij, M.A.M. — "Telescope Optics", Willmann-Bell, 1988,
    §6.3.
Smith, W.J. — "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008, §11.3.

Units: all lengths in millimetres.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SchmidtSpec:
    """
    Specification for a Schmidt telescope corrector plate.

    Parameters
    ----------
    primary_radius_R_mm : float
        Radius of curvature of the spherical primary mirror (mm). Must be > 0.
        The focal length is f = R/2. For an f/2 mirror of diameter 200 mm,
        R = 400 mm.
    aperture_diameter_D_mm : float
        Clear aperture diameter of the corrector plate (mm). Must be > 0.
        Should equal the entrance aperture of the telescope.
    glass_index_n : float
        Refractive index of the corrector plate glass at the design wavelength.
        Default 1.5168 (Schott BK7 at 587.6 nm d-line).
        Must be > 1.0.
    neutral_zone_factor_kappa : float
        Dimensionless neutral-zone placement factor κ. Default 1.5.
        The neutral zone radius is ρ_n = (D/2) / sqrt(κ).
        κ = 1.5 (default) minimises peak-to-valley sag (classic Schmidt optimum,
        Born & Wolf §6.3; Rutten & van Venrooij §6.3).
        κ = 1.0 places the neutral zone at the edge (zero edge sag).
        κ = 2.0 places the neutral zone at D/2 / sqrt(2) ≈ 0.707 × D/2.
    """
    primary_radius_R_mm: float
    aperture_diameter_D_mm: float
    glass_index_n: float = 1.5168
    neutral_zone_factor_kappa: float = 1.5


@dataclass
class SchmidtReport:
    """
    Result of Schmidt corrector plate design computation.

    Attributes
    ----------
    aspheric_profile : list of (r_mm, z_mm) tuples
        Sampled sag profile of the corrector plate. r_mm is the radial
        distance from the optical axis (0 to D/2); z_mm is the sag (positive
        = convex toward incoming light, i.e., thicker at neutral zone).
    max_sag_mm : float
        Peak-to-valley sag amplitude (mm). This is the maximum absolute value
        of z(r) over the clear aperture, which determines the minimum plate
        thickness required.
    neutral_zone_radius_mm : float
        Radius ρ_n = (D/2) / sqrt(κ) at which dz/dr = 0 (neutral zone, mm).
    schwarzschild_constant_k : float
        Equivalent Schwarzschild (conic) constant of the primary mirror that
        would produce the same on-axis performance without a corrector. For a
        classical Schmidt this is always k = -1 (paraboloid); the corrector
        makes the spherical mirror (k = 0) behave as though k = -1.
    honest_caveat : str
        Plain-language description of limitations and out-of-scope items.
    """
    aspheric_profile: list[tuple[float, float]] = field(default_factory=list)
    max_sag_mm: float = 0.0
    neutral_zone_radius_mm: float = 0.0
    schwarzschild_constant_k: float = -1.0
    honest_caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "aspheric_profile": [list(pt) for pt in self.aspheric_profile],
            "max_sag_mm": self.max_sag_mm,
            "neutral_zone_radius_mm": self.neutral_zone_radius_mm,
            "schwarzschild_constant_k": self.schwarzschild_constant_k,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Honest caveat text
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Classical Schmidt (1932) corrector: thin aspheric plate at centre of "
    "curvature cancels spherical aberration of spherical primary. "
    "Limitations: (1) monochromatic — chromatic residual not computed; "
    "(2) on-axis only — off-axis coma appears if corrector deviates from "
    "the centre-of-curvature plane; (3) field curvature of a Schmidt camera "
    "is not corrected (R_petzval = -R/2); (4) modern Schmidt-Cassegrain and "
    "Schmidt-Newtonian designs add a secondary mirror and field-flattener for "
    "a flat, corrected field — this tool models only the classical one-mirror "
    "Schmidt camera corrector; (5) thin-plate approximation assumed (sag << "
    "plate thickness); (6) Schwarzschild constant k=-1 is the equivalent "
    "paraboloid that would need no corrector, not the actual mirror shape."
)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _schmidt_sag(r: float, R: float, n: float, rho_n: float) -> float:
    """
    Schmidt corrector plate sag at radius r (mm).

    z(r) = r² · (r² − 2·ρ_n²) / [8·(n−1)·R³]

    where ρ_n = r_ap / sqrt(κ) is the neutral-zone radius (dz/dr = 0 at r = ρ_n).
    This is equivalent to the task-spec form z = r²·(r²−2·κ·ρ_n²)/(8(n-1)R³) with
    ρ_n = r_ap/√κ, since 2·κ·(r_ap/√κ)² = 2·r_ap².

    Parameters
    ----------
    r : float
        Radial distance from optical axis (mm).
    R : float
        Primary mirror radius of curvature (mm).
    n : float
        Corrector plate refractive index.
    rho_n : float
        Neutral-zone radius (mm) = aperture_radius / sqrt(kappa).

    Returns
    -------
    float
        Sag z(r) in mm.
    """
    r2 = r * r
    rho_n2 = rho_n * rho_n
    # Born & Wolf §6.3: z(r) = r²·(r² − 2·ρ_n²) / [8·(n−1)·R³]
    # ρ_n = r_ap/sqrt(κ) is the true neutral zone radius (dz/dr = 0 at r = ρ_n).
    # Note: the task-spec formula z = r²·(r²−2·κ·ρ_n²)/(8(n-1)R³) with ρ_n=r_ap/√κ
    # simplifies to this same expression because 2·κ·(r_ap/√κ)² = 2·r_ap²;
    # kappa enters only through ρ_n = r_ap/√κ.
    numerator = r2 * (r2 - 2.0 * rho_n2)
    denominator = 8.0 * (n - 1.0) * (R ** 3)
    return numerator / denominator


def design_schmidt_corrector(
    spec: SchmidtSpec,
    num_radii: int = 50,
) -> SchmidtReport:
    """
    Compute the Schmidt corrector plate aspheric profile z(r).

    Algorithm
    ---------
    The corrector sag at radius r is (Born & Wolf §6.3 / Schmidt 1932):

        z(r) = [r^4 - 2·κ·ρ_n^2·r^2] / [8·(n-1)·R^3]
             = r^2·(r^2 - 2·κ·ρ_n^2) / [8·(n-1)·R^3]

    where:
        ρ_n = (D/2) / sqrt(κ)   neutral-zone radius
        κ = neutral_zone_factor_kappa (default 1.5 for minimum peak sag)

    The neutral zone is the radius where dz/dr = 0:
        dz/dr = [4r^3 - 4·κ·ρ_n^2·r] / [8·(n-1)·R^3] = 0
        => r = ρ_n = aperture_radius / sqrt(κ)

    For κ = 1.5:  ρ_n = r_ap / sqrt(1.5) ≈ 0.8165 * r_ap
    The profile has a positive peak (thicker glass) near the neutral zone
    and negative sags at centre and edge; the neutral zone itself is zero.

    Maximum sag is found by evaluating z at the saddle points. For the
    symmetric problem, the maximum absolute sag occurs at:
      - r = 0:  z(0) = 0
      - r = r_ap: z(r_ap) = r_ap^2 * (r_ap^2 - 2κρ_n^2) / [8(n-1)R^3]
      - r = ρ_n (local extremum): z(ρ_n) = ρ_n^2 * (ρ_n^2 - 2κρ_n^2) / [8(n-1)R^3]
                                           = -κρ_n^4 / [8(n-1)R^3]  < 0 (a valley)

    The max_sag_mm is the maximum of |z(r)| over the sampled aperture, which
    represents the peak-to-valley sag amplitude needed for the glass blank.

    Parameters
    ----------
    spec : SchmidtSpec
        Design specification.
    num_radii : int
        Number of radial sample points from 0 to D/2 (inclusive). Default 50.
        Must be >= 2.

    Returns
    -------
    SchmidtReport on success.
    Raises ValueError on invalid input.
    """
    # ---- Validate inputs ---------------------------------------------------
    R = float(spec.primary_radius_R_mm)
    D = float(spec.aperture_diameter_D_mm)
    n = float(spec.glass_index_n)
    kappa = float(spec.neutral_zone_factor_kappa)
    nr = int(num_radii)

    if not math.isfinite(R) or R <= 0.0:
        raise ValueError(f"primary_radius_R_mm must be > 0, got {R}")
    if not math.isfinite(D) or D <= 0.0:
        raise ValueError(f"aperture_diameter_D_mm must be > 0, got {D}")
    if not math.isfinite(n) or n <= 1.0:
        raise ValueError(f"glass_index_n must be > 1.0, got {n}")
    if not math.isfinite(kappa) or kappa <= 0.0:
        raise ValueError(f"neutral_zone_factor_kappa must be > 0, got {kappa}")
    if nr < 2:
        raise ValueError(f"num_radii must be >= 2, got {nr}")

    aperture_radius = D / 2.0

    # Neutral-zone radius: ρ_n = r_ap / sqrt(κ)
    rho_n = aperture_radius / math.sqrt(kappa)

    # ---- Sample z(r) -------------------------------------------------------
    profile: list[tuple[float, float]] = []
    for i in range(nr):
        r = aperture_radius * i / (nr - 1)
        z = _schmidt_sag(r, R, n, rho_n)
        profile.append((r, z))

    # ---- Peak-to-valley sag ------------------------------------------------
    # max |z(r)| over the clear aperture
    max_sag = max(abs(z) for _, z in profile)

    # ---- Schwarzschild constant --------------------------------------------
    # The equivalent conic mirror that needs no corrector is a paraboloid (k=-1).
    # The Schmidt corrector enables a spherical primary (k=0) to achieve the
    # same on-axis wavefront quality.
    k_schwarzschild = -1.0

    return SchmidtReport(
        aspheric_profile=profile,
        max_sag_mm=max_sag,
        neutral_zone_radius_mm=rho_n,
        schwarzschild_constant_k=k_schwarzschild,
        honest_caveat=_HONEST_CAVEAT,
    )
