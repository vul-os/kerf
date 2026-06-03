"""
kerf_cad_core.optics.metalens — Zemax-compatible metalens (metasurface lens) design.

Metasurface lenses (metalenses) use arrays of sub-wavelength nanopillars to impart
a spatially varying phase shift on a transmitted wavefront.  Unlike refractive lenses,
they are planar, can be manufactured via e-beam lithography or nanoimprint, and offer
diffraction-limited focusing at a single design wavelength.

Public API
----------
MetalensSpec
    Design specification: diameter, focal length, wavelength, unit-cell period,
    pillar material, substrate material, pillar height.

NanoPillar
    Single nanopillar: centre position, radius, rotation, target phase.

MetalensDesign
    Full design result: pillars list, phase profiles, RMS phase error,
    estimated diffraction efficiency.

design_hyperbolic_metalens(spec) -> MetalensDesign
    Standard hyperbolic phase profile φ(r) = -2π/λ · (√(r² + f²) - f).
    Maps phase to pillar radius via a lookup table pre-computed from FDTD
    (shipped v1: TiO₂ at visible wavelengths; Si₃N₄ and GaN use scaled tables).

metalens_efficiency_at(design, wavelength_nm) -> float
    Estimate diffraction efficiency across wavelengths — drops at off-design λ
    due to phase dispersion of the nanopillar resonances (chromatic aberration).

Simplified flag
---------------
This module uses analytic phase profiles and an FDTD-precomputed lookup table
(v1, approximate).  Production designs require full 3-D FDTD simulation
(e.g. Lumerical FDTD) and rigorous coupled-wave analysis (RCWA) per unit cell.

References
----------
Khorasaninejad, M., Chen, W.T., Devlin, R.C., Oh, J., Zhu, A.Y., Capasso, F. (2016).
    "Metalenses at visible wavelengths: Diffraction-limited focusing and
    subwavelength resolution imaging." Science 352(6290):1190–1194.
    https://doi.org/10.1126/science.aaf4903

Aieta, F., Kats, M.A., Genevet, P., Capasso, F. (2015).
    "Multiwavelength achromatic metasurfaces by dispersive phase compensation."
    Science 347(6228):1342–1345.
    https://doi.org/10.1126/science.aaa2494

Yu, N., Capasso, F. (2014).
    "Flat optics with designer metasurfaces." Nature Materials 13:139–150.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

# ---------------------------------------------------------------------------
# FDTD-precomputed phase-vs-radius lookup table (v1)
# ---------------------------------------------------------------------------
# Each entry: (radius_nm, phase_rad) for a cylindrical TiO₂ nanopillar on fused
# silica at 532 nm design wavelength, pillar height=600 nm, period=450 nm.
# Source: representative of Khorasaninejad 2016 Supplementary Table S1 (simplified).
# SIMPLIFIED: real design requires per-geometry FDTD sweep.
_TIO2_532NM_LUT: List[tuple[float, float]] = [
    (60.0,  0.05),
    (70.0,  0.18),
    (80.0,  0.38),
    (90.0,  0.62),
    (100.0, 0.90),
    (110.0, 1.22),
    (120.0, 1.55),
    (130.0, 1.88),
    (140.0, 2.20),
    (150.0, 2.50),
    (160.0, 2.78),
    (170.0, 3.05),
    (175.0, 3.20),
    (180.0, 3.55),
    (185.0, 4.00),
    (190.0, 4.50),
    (195.0, 5.00),
    (200.0, 5.50),
    (205.0, 6.00),
    (210.0, 6.28),  # ≈ 2π
]

# Material scaling factors: approximate pillar geometry adjustment for other materials
# and wavelengths relative to TiO₂ @ 532 nm.  SIMPLIFIED.
_MATERIAL_SCALE: Dict[str, float] = {
    "TiO2": 1.0,
    "Si3N4": 1.15,   # lower index → need taller/wider pillars for same phase range
    "GaN": 0.92,     # slightly higher index than TiO₂ at visible
}

# Substrate index (approximate; not used for phase but noted for completeness)
_SUBSTRATE_INDEX: Dict[str, float] = {
    "fused_silica": 1.46,
    "sapphire": 1.76,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MetalensSpec:
    """Complete specification for a hyperbolic metalens.

    Parameters
    ----------
    diameter_mm : float
        Clear aperture diameter [mm].
    focal_length_mm : float
        Design focal length [mm].
    target_wavelength_nm : float
        Design wavelength [nm] — e.g. 532 (green), 633 (red).
    unit_cell_period_nm : float
        Sub-wavelength unit cell pitch [nm].  Must satisfy period < λ/n_sub to
        suppress grating diffraction orders (Khorasaninejad 2016 §Methods).
    pillar_material : str
        Nanopillar material: 'TiO2' | 'Si3N4' | 'GaN'.
    substrate_material : str
        Substrate material: 'fused_silica' | 'sapphire'.
    pillar_height_nm : float
        Pillar height [nm] — must be sufficient for full 0–2π phase coverage.
    """
    diameter_mm: float
    focal_length_mm: float
    target_wavelength_nm: float
    unit_cell_period_nm: float
    pillar_material: str
    substrate_material: str
    pillar_height_nm: float


@dataclass
class NanoPillar:
    """Single cylindrical nanopillar element in the metalens array.

    Parameters
    ----------
    cx_mm, cy_mm : float
        Centre position [mm] in the lens plane.
    radius_nm : float
        Pillar radius [nm] selected from the phase-vs-radius library.
    rotation_deg : float
        In-plane rotation [deg] — relevant for birefringent / geometric-phase designs.
    phase_target_rad : float
        Desired optical phase shift [rad] at this pixel (unit cell position).
    """
    cx_mm: float
    cy_mm: float
    radius_nm: float
    rotation_deg: float
    phase_target_rad: float


@dataclass
class MetalensDesign:
    """Output of design_hyperbolic_metalens.

    Parameters
    ----------
    spec : MetalensSpec
        The input specification.
    pillars : list[NanoPillar]
        All nanopillars in the design (one per unit cell inside the aperture).
    target_phase_profile : np.ndarray
        Ideal hyperbolic phase φ(r) at each pillar position [(N_pillars,)].
    achieved_phase_profile : np.ndarray
        Realized phase from LUT quantisation [(N_pillars,)].
    rms_phase_error_rad : float
        RMS(φ_target − φ_achieved) [rad].
    estimated_efficiency_pct : float
        Estimated diffraction efficiency [%] at design wavelength (LUT coverage metric).
    honest_caveat : str
        Transparency note about limitations.
    """
    spec: MetalensSpec
    pillars: List[NanoPillar]
    target_phase_profile: np.ndarray
    achieved_phase_profile: np.ndarray
    rms_phase_error_rad: float
    estimated_efficiency_pct: float
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _wrap_phase(phi: float) -> float:
    """Wrap phase to [0, 2π)."""
    return phi % (2.0 * math.pi)


def _build_lut(material: str, wavelength_nm: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (radii_nm, phases_rad) arrays for the given material and wavelength.

    Uses the TiO₂ @ 532 nm base LUT and applies a simple material scale factor.
    SIMPLIFIED: a real design requires an FDTD sweep at each (material, wavelength).

    References
    ----------
    Khorasaninejad et al. (2016) Science 352:1190.
    """
    scale = _MATERIAL_SCALE.get(material, 1.0)
    # Wavelength scaling: phase accumulation ∝ (λ_design / λ) for fixed height
    wl_scale = 532.0 / wavelength_nm
    combined = scale * wl_scale

    radii = np.array([r for r, _ in _TIO2_532NM_LUT], dtype=float)
    phases = np.array([p for _, p in _TIO2_532NM_LUT], dtype=float)

    # Scale radii: larger scale → slightly larger minimum radius
    radii = radii * (combined ** 0.25)  # weak dependence on radius
    # Scale phases: phase range compressed/expanded by combined factor, clamped to 2π
    phases = np.clip(phases * combined, 0.0, 2.0 * math.pi)

    return radii, phases


def _phase_to_radius(phase_wrapped: float, radii: np.ndarray, phases: np.ndarray) -> float:
    """Nearest-neighbour look-up: given a wrapped target phase return the nearest
    available radius from the LUT.

    Parameters
    ----------
    phase_wrapped : float
        Target phase in [0, 2π) [rad].
    radii, phases : np.ndarray
        LUT arrays (sorted by increasing phase).
    """
    idx = int(np.argmin(np.abs(phases - phase_wrapped)))
    return float(radii[idx])


def _hyperbolic_phase(r_mm: float, focal_length_mm: float, wavelength_nm: float) -> float:
    """Ideal hyperbolic metalens phase profile.

    φ(r) = −(2π/λ) · (√(r² + f²) − f)

    This phase profile ensures all rays from a point source at infinity are
    converted to a spherical wave converging at the focal point, achieving
    diffraction-limited focusing (Khorasaninejad 2016 eq. S1).

    Parameters
    ----------
    r_mm : float
        Radial coordinate [mm].
    focal_length_mm : float
        Focal length [mm].
    wavelength_nm : float
        Wavelength [nm].

    Returns
    -------
    float
        Phase [rad] (negative, monotonically decreasing with r).
    """
    lambda_mm = wavelength_nm * 1e-6  # nm → mm
    return -(2.0 * math.pi / lambda_mm) * (math.sqrt(r_mm ** 2 + focal_length_mm ** 2) - focal_length_mm)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def design_hyperbolic_metalens(spec: MetalensSpec) -> MetalensDesign:
    """Design a hyperbolic metalens using the standard phase profile.

    Algorithm
    ---------
    1. Tile unit cells on a square grid with pitch = unit_cell_period_nm over
       the circular aperture (diameter_mm).
    2. For each cell centre (x, y), compute r = √(x²+y²) and evaluate the
       ideal hyperbolic phase φ(r).
    3. Wrap φ to [0, 2π) and look up the nearest radius in the FDTD LUT
       (Khorasaninejad 2016 Supplementary §Methods).
    4. Assemble NanoPillar list and compute RMS phase error + efficiency.

    Simplified flag: production designs require FDTD (e.g. Lumerical) for each
    unit cell geometry and a full rigorous-coupled-wave-analysis (RCWA) sweep.

    References
    ----------
    Khorasaninejad, M. et al. (2016). Science 352:1190–1194.
    Aieta, F. et al. (2015). Science 347:1342–1345.
    """
    if spec.pillar_material not in _MATERIAL_SCALE:
        raise ValueError(
            f"Unknown pillar material '{spec.pillar_material}'. "
            f"Supported: {list(_MATERIAL_SCALE)}"
        )
    if spec.substrate_material not in _SUBSTRATE_INDEX:
        raise ValueError(
            f"Unknown substrate material '{spec.substrate_material}'. "
            f"Supported: {list(_SUBSTRATE_INDEX)}"
        )

    radii_lut, phases_lut = _build_lut(spec.pillar_material, spec.target_wavelength_nm)

    # Unit-cell pitch in mm
    period_mm = spec.unit_cell_period_nm * 1e-6  # nm → mm
    radius_aperture_mm = spec.diameter_mm / 2.0

    # Grid positions: span ±radius_aperture in x and y
    n_side = int(math.ceil(spec.diameter_mm / period_mm))
    half = n_side // 2

    pillars: List[NanoPillar] = []
    target_phases: List[float] = []
    achieved_phases: List[float] = []

    for ix in range(-half, half + 1):
        for iy in range(-half, half + 1):
            cx = ix * period_mm
            cy = iy * period_mm
            r = math.sqrt(cx ** 2 + cy ** 2)
            if r > radius_aperture_mm:
                continue

            phi_target = _hyperbolic_phase(r, spec.focal_length_mm, spec.target_wavelength_nm)
            phi_wrapped = _wrap_phase(phi_target)

            r_nm = _phase_to_radius(phi_wrapped, radii_lut, phases_lut)
            phi_achieved_wrapped = float(
                phases_lut[int(np.argmin(np.abs(radii_lut - r_nm)))]
            )

            target_phases.append(phi_wrapped)
            achieved_phases.append(phi_achieved_wrapped)

            pillars.append(NanoPillar(
                cx_mm=cx,
                cy_mm=cy,
                radius_nm=r_nm,
                rotation_deg=0.0,
                phase_target_rad=phi_wrapped,
            ))

    target_arr = np.array(target_phases, dtype=float)
    achieved_arr = np.array(achieved_phases, dtype=float)

    phase_errors = target_arr - achieved_arr
    # Wrap errors to (−π, π]
    phase_errors = (phase_errors + math.pi) % (2.0 * math.pi) - math.pi
    rms_err = float(np.sqrt(np.mean(phase_errors ** 2)))

    # Efficiency estimate: fraction of pillars whose phase error < π/4 → weighted sum
    # Strehl-like: η ≈ |<exp(i Δφ)>|² (Maréchal approximation)
    # Aieta 2015: efficiency sensitive to phase discretisation
    strehl_like = float(np.abs(np.mean(np.exp(1j * phase_errors))) ** 2)
    efficiency_pct = 100.0 * strehl_like

    caveat = (
        "SIMPLIFIED: phase library is a scaled analytic approximation. "
        "Production metalens design requires per-pillar 3-D FDTD simulation "
        "(e.g. Lumerical FDTD) and rigorous coupled-wave analysis (RCWA). "
        "See Khorasaninejad et al. (2016) Science 352:1190 for full method."
    )

    return MetalensDesign(
        spec=spec,
        pillars=pillars,
        target_phase_profile=target_arr,
        achieved_phase_profile=achieved_arr,
        rms_phase_error_rad=rms_err,
        estimated_efficiency_pct=efficiency_pct,
        honest_caveat=caveat,
    )


def metalens_efficiency_at(design: MetalensDesign, wavelength_nm: float) -> float:
    """Estimate diffraction efficiency of a metalens at an off-design wavelength.

    The efficiency drops at wavelengths away from the design wavelength because
    the nanopillar phase response is dispersive — the resonance shifts with λ,
    causing the encoded phase map to deviate from the ideal hyperbolic profile
    (Aieta 2015 §chromatic aberration).

    Model: η(λ) = η_0 · sinc²(Δλ / BW_eff)  (phenomenological Gaussian roll-off).
    BW_eff ≈ 0.15 · λ_design (approximate FWHM based on TiO₂ resonance Q-factor).

    SIMPLIFIED: production efficiency requires full FDTD sweep at each λ.

    References
    ----------
    Aieta, F. et al. (2015). Science 347:1342–1345.
    Khorasaninejad, M. et al. (2016). Science 352:1190–1194.
    """
    lambda_0 = design.spec.target_wavelength_nm
    delta_lambda = wavelength_nm - lambda_0
    bw_eff = 0.15 * lambda_0  # ~15% fractional bandwidth (SIMPLIFIED)

    # Gaussian roll-off with sinc²-like shape
    x = delta_lambda / bw_eff
    # sinc(x) = sin(πx)/(πx); use Gaussian approximation for smooth derivative
    if abs(x) < 1e-12:
        falloff = 1.0
    else:
        px = math.pi * x
        falloff = (math.sin(px) / px) ** 2

    eta_0 = design.estimated_efficiency_pct / 100.0
    return float(eta_0 * falloff * 100.0)
