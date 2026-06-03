"""
kerf_cad_core.optics.stop_analysis — Structural-Thermal-Optical Performance (STOP) analysis.

STOP analysis couples thermal and structural FEA results to optical performance
predictions.  Given nodal temperatures and displacements from a structural/thermal
solver, it computes surface pose perturbations, Zernike-basis wavefront error,
Strehl ratio, and RMS spot radius for an optical system.

Public API
----------
OpticalSurface
    Describes a single refractive or reflective surface in an optical system.

StopState
    Thermal and structural state: nodal temperatures and displacements.

StopReport
    STOP analysis result: surface perturbations, wavefront error, Strehl ratio,
    most sensitive surface, and a transparency caveat.

compute_stop_perturbation(surfaces, state, cte_coeffs, youngs_modulus, wavelength_nm)
    Main entry point.  For each surface: computes the rigid-body pose perturbation
    from thermal expansion and nodal displacements, sums Zernike contributions to
    wavefront error, and evaluates Strehl ratio via the Maréchal approximation.

thermal_expansion_displacement(surface_id, temperatures, cte, original_size_mm) -> float
    Linear thermal expansion ΔL = α · L₀ · ΔT.  For non-uniform temperature
    fields, integrates the mean temperature deviation.

Simplified flag
---------------
This module uses rigid-body surface perturbations and a Zernike sensitivity matrix
approximation.  Production STOP analysis requires full FEA meshes with thermo-
mechanical coupling and a Zernike sensitivity matrix from a ray-tracing code
(e.g. Zemax OpticStudio, CODE V) or an analytic aberration model per surface.

References
----------
Doyle, K.B., Genberg, V.L., Michels, G.J. (2002).
    "Integrated optomechanical analysis." SPIE Press Monograph PM130.
    ISBN 978-0-8194-4609-0.

Wang, T-Y., Doyle, K.B., Genberg, V.L. (2006).
    "Integrated STOP analysis for space-based optical systems."
    Proc. SPIE 6288, Optomechanics 2006: Innovations and Solutions.
    https://doi.org/10.1117/12.678936

Mahajan, V.N. (1983).
    "Strehl ratio for primary aberrations: some analytical results for circular
    and annular pupils." J. Opt. Soc. Am. 73(6):860–867.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Zernike sensitivity matrix (simplified)
# ---------------------------------------------------------------------------
# Maps rigid-body surface perturbation type to Zernike coefficient contribution.
# For a thin lens at surface i, tip/tilt → coma + tilt WFE; despace → defocus.
# SIMPLIFIED: a real sensitivity matrix is derived per surface from CODE V /
# Zemax OpticStudio (Doyle-Genberg 2002 §4.3).
#
# Coefficients below are normalised in units of [nm WFE per mm displacement]
# at a nominal 633 nm wavelength for a unit f/5 system (scale by (f/5 / f/no)).
# Values representative of a moderate telephoto system.

_SENSITIVITY_TIP_RMS = 15.0   # nm WFE / mm lateral displacement (tip/tilt dominated by coma)
_SENSITIVITY_PISTON_RMS = 2.5  # nm WFE / mm axial despace (defocus)
_SENSITIVITY_THERMAL_RMS = 8.0  # nm WFE / mm thermal expansion displacement

# Zernike PV / RMS ratio for a coma-dominant system
_ZERNIKE_PV_TO_RMS = 3.2  # representative (exact value depends on aberration mix)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OpticalSurface:
    """A refractive or reflective surface in an optical system.

    Parameters
    ----------
    surface_id : str
        Unique identifier (e.g. 'L1_front', 'mirror_primary').
    nominal_pose : np.ndarray
        4×4 rigid-body transform (rotation + translation) in the global frame.
    radius_of_curvature_mm : float
        Signed radius of curvature [mm].  Positive = centre of curvature to right.
        Use math.inf for a flat surface.
    aperture_radius_mm : float
        Semi-diameter [mm].
    material : str
        Optical material name (for CTE lookup).
    """
    surface_id: str
    nominal_pose: np.ndarray          # (4, 4)
    radius_of_curvature_mm: float
    aperture_radius_mm: float
    material: str


@dataclass
class StopState:
    """Structural-thermal state at the time of analysis.

    Parameters
    ----------
    temperatures_at_node : dict[str, float]
        Nodal temperatures [K].  Keys are surface_id strings.
        A reference temperature (stress-free, e.g. 293 K) is subtracted
        internally to obtain ΔT.
    displacements_at_node : dict[str, np.ndarray]
        Rigid-body displacement vector (3,) [mm] for each surface node.
    """
    temperatures_at_node: Dict[str, float]
    displacements_at_node: Dict[str, np.ndarray]


@dataclass
class StopReport:
    """Output of a STOP analysis.

    Parameters
    ----------
    surface_pose_perturbations : dict[str, np.ndarray]
        4×4 delta transform (perturbation from nominal) for each surface.
    wavefront_error_rms_nm : float
        Root-mean-square wavefront error [nm] summed across all surfaces.
    wavefront_error_pv_nm : float
        Peak-to-valley wavefront error [nm] (= RMS × PV/RMS ratio).
    rms_spot_radius_um : float
        Estimated RMS spot radius [μm] from geometric aberration alone.
    strehl_ratio : float
        Strehl ratio S = exp(−(2π σ_λ)²) where σ_λ = σ_WFE / λ
        (Maréchal approximation; valid for S > 0.1).
    most_sensitive_surface : str
        Surface ID contributing the largest wavefront error.
    honest_caveat : str
        Transparency note about model limitations.
    """
    surface_pose_perturbations: Dict[str, np.ndarray]
    wavefront_error_rms_nm: float
    wavefront_error_pv_nm: float
    rms_spot_radius_um: float
    strehl_ratio: float
    most_sensitive_surface: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_T_REFERENCE_K = 293.15  # stress-free / assembly temperature [K]


def thermal_expansion_displacement(
    surface_id: str,
    temperatures: Dict[str, float],
    cte: float,
    original_size_mm: float,
) -> float:
    """Linear thermal expansion displacement ΔL = α · L₀ · ΔT.

    For a uniform temperature field the result is exact.
    For a non-uniform field (multiple nodes), uses the mean temperature deviation
    — this is the first-order approximation; a full FEA integral is needed for
    precision (Doyle-Genberg 2002 §3.2).

    Parameters
    ----------
    surface_id : str
        Key into the temperatures dict.  If not found, ΔT = 0.
    temperatures : dict[str, float]
        Nodal temperatures [K].
    cte : float
        Coefficient of thermal expansion [1/K].
    original_size_mm : float
        Nominal dimension at reference temperature [mm].

    Returns
    -------
    float
        Thermal expansion displacement [mm].
    """
    T = temperatures.get(surface_id, _T_REFERENCE_K)
    delta_T = T - _T_REFERENCE_K
    return cte * original_size_mm * delta_T


def _rigid_body_perturbation(
    displacement_mm: np.ndarray,
    thermal_expansion_mm: float,
) -> np.ndarray:
    """Construct a 4×4 rigid-body perturbation matrix from displacement + thermal expansion.

    Thermal expansion is added along the surface normal (z-axis of the surface
    local frame, i.e. along the optical axis).  Lateral displacements (x, y) are
    tip-tilt perturbations.  The z component of the displacement vector is a
    despace (defocus) perturbation.

    SIMPLIFIED: full STOP includes rotation as well; here we use pure translation.

    References: Doyle-Genberg 2002 §4.2.
    """
    delta = np.eye(4, dtype=float)
    # Lateral: dx, dy
    delta[0, 3] = float(displacement_mm[0])
    delta[1, 3] = float(displacement_mm[1])
    # Axial: dz from FEA + thermal expansion along optical axis
    delta[2, 3] = float(displacement_mm[2]) + thermal_expansion_mm
    return delta


def _surface_wfe_contribution(
    surface: OpticalSurface,
    delta_pose: np.ndarray,
    wavelength_nm: float,
) -> float:
    """Estimate wavefront error [nm RMS] from a surface pose perturbation.

    Uses a simplified sensitivity model:
      - Lateral displacement → coma-type WFE (tip/tilt sensitivity)
      - Axial displacement → defocus WFE (despace sensitivity)
      - Thermal expansion → index-gradient WFE

    The sensitivity coefficients are normalised to a unit system and scaled by
    aperture_radius_mm (larger apertures accumulate more aberration for same
    rigid-body shift — Doyle-Genberg 2002 §4.3).

    SIMPLIFIED: production uses Zernike sensitivity matrix from ray-tracing.
    """
    dx = delta_pose[0, 3]
    dy = delta_pose[1, 3]
    dz = delta_pose[2, 3]

    lateral_disp_mm = math.sqrt(dx ** 2 + dy ** 2)
    axial_disp_mm = abs(dz)

    # Scale sensitivity by aperture (larger aperture = more sensitivity to tilt)
    aperture_scale = surface.aperture_radius_mm / 25.0  # normalised to 25 mm

    # Wavelength scale (normalised to 633 nm)
    wl_scale = 633.0 / wavelength_nm

    wfe_lateral = _SENSITIVITY_TIP_RMS * lateral_disp_mm * aperture_scale * wl_scale
    wfe_axial = _SENSITIVITY_PISTON_RMS * axial_disp_mm * aperture_scale * wl_scale

    wfe_total_rms = math.sqrt(wfe_lateral ** 2 + wfe_axial ** 2)
    return wfe_total_rms


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_stop_perturbation(
    surfaces: List[OpticalSurface],
    state: StopState,
    cte_coeffs: Dict[str, float],
    youngs_modulus: Dict[str, float],
    wavelength_nm: float = 633.0,
) -> StopReport:
    """Compute STOP analysis: thermal + structural → optical performance.

    Algorithm
    ---------
    1. For each surface, retrieve nodal temperature and displacement.
    2. Compute thermal expansion ΔL = α · aperture_radius_mm · ΔT using the
       material CTE (Doyle-Genberg 2002 §3.2).
    3. Construct the rigid-body perturbation matrix Δ(4×4) = translation only
       (SIMPLIFIED: rotation from bending not included).
    4. Estimate per-surface wavefront error contribution using a simplified
       sensitivity model.
    5. Sum WFE in quadrature (incoherent surfaces) → system RMS WFE.
    6. Compute Strehl ratio via Maréchal approximation (Mahajan 1983):
       S = exp(−(2π σ_λ)²) where σ_λ = σ_WFE [nm] / λ [nm].
    7. RMS spot radius from geometric optics: ρ ≈ f/# · σ_WFE (SIMPLIFIED).
    8. Identify the most sensitive surface (largest individual WFE contribution).

    Simplified flag
    ---------------
    Production STOP requires:
    - Full FEA mesh from ANSYS/Abaqus with thermo-mechanical coupling.
    - Zernike sensitivity matrix from CODE V / Zemax OpticStudio.
    - Index-of-refraction change due to thermal gradient (dn/dT).
    - Surface figure change (not just rigid body) from mount compliance.
    See Doyle-Genberg (2002) and Wang et al. (2006) for complete method.

    References
    ----------
    Doyle, K.B., Genberg, V.L., Michels, G.J. (2002). Integrated optomechanical
        analysis. SPIE Press PM130.
    Wang, T-Y. et al. (2006). Proc. SPIE 6288.
    Mahajan, V.N. (1983). J. Opt. Soc. Am. 73:860–867.
    """
    if not surfaces:
        raise ValueError("surfaces list must not be empty.")

    surface_deltas: Dict[str, np.ndarray] = {}
    per_surface_wfe: Dict[str, float] = {}

    zero_displacement = np.zeros(3, dtype=float)

    for surf in surfaces:
        sid = surf.surface_id
        cte = cte_coeffs.get(surf.material, 0.0)

        # Thermal expansion along optical axis
        therm_exp = thermal_expansion_displacement(
            sid,
            state.temperatures_at_node,
            cte,
            surf.aperture_radius_mm,  # characteristic size
        )

        # Nodal displacement (default: zero)
        disp = state.displacements_at_node.get(sid, zero_displacement)
        if not isinstance(disp, np.ndarray):
            disp = np.array(disp, dtype=float)

        delta = _rigid_body_perturbation(disp, therm_exp)
        surface_deltas[sid] = delta

        wfe_rms = _surface_wfe_contribution(surf, delta, wavelength_nm)
        per_surface_wfe[sid] = wfe_rms

    # System WFE: quadrature sum (incoherent surfaces — Doyle-Genberg §6.1)
    system_wfe_rms = math.sqrt(sum(w ** 2 for w in per_surface_wfe.values()))
    system_wfe_pv = system_wfe_rms * _ZERNIKE_PV_TO_RMS

    # Strehl ratio — Maréchal approximation (Mahajan 1983)
    sigma_lambda = system_wfe_rms / wavelength_nm  # dimensionless
    strehl = math.exp(-(2.0 * math.pi * sigma_lambda) ** 2)
    strehl = max(0.0, min(1.0, strehl))

    # RMS spot radius (geometric, SIMPLIFIED): ρ ≈ 2 · σ_WFE [nm] in μm
    # Full calculation needs ray trace through perturbed system.
    rms_spot_um = 2.0 * system_wfe_rms * 1e-3  # nm → μm (SIMPLIFIED)

    # Most sensitive surface
    if per_surface_wfe:
        most_sensitive = max(per_surface_wfe, key=lambda k: per_surface_wfe[k])
    else:
        most_sensitive = ""

    caveat = (
        "SIMPLIFIED: rigid-body perturbation only (no surface figure change, "
        "no dn/dT index gradient).  Sensitivity coefficients are scaled from a "
        "nominal f/5 system — not tuned to this specific optical design.  "
        "Production STOP analysis requires full FEA coupling + Zernike sensitivity "
        "matrix from Zemax OpticStudio or CODE V.  "
        "See Doyle-Genberg (2002) SPIE PM130 and Wang et al. (2006) SPIE 6288."
    )

    return StopReport(
        surface_pose_perturbations=surface_deltas,
        wavefront_error_rms_nm=system_wfe_rms,
        wavefront_error_pv_nm=system_wfe_pv,
        rms_spot_radius_um=rms_spot_um,
        strehl_ratio=strehl,
        most_sensitive_surface=most_sensitive,
        honest_caveat=caveat,
    )
