"""
kerf_cad_core.optics.coma_compute — comatic aberration metrics from a lens stack.

Public API
----------
compute_coma(stack, field_angles_deg, n_pupil_rays=16,
             aperture_radius_mm=1.0, n_object=1.0,
             compute_opd=False) -> ComaReport | dict

compute_finite_ray_coma(surfaces, field_height_mm, num_pupil_samples=64,
                        aperture_radius_mm=1.0, n_object=1.0,
                        wavelength_mm=0.000587) -> FiniteRayOpdReport | dict

Theory (Welford 1986 §11.4 / Born & Wolf §5.3)
-----------------------------------------------
Coma is the second Seidel aberration (S_II).  For a ray at pupil rim (ρ=1) and
field height η in the tangential plane, the transverse aberration is (Welford
1986 §11.4, Born & Wolf §5.3 eq. 5.3.29):

    Tangential coma  = 3 * S_II * η      (mean displacement of upper/lower rim rays)
    Sagittal  coma   =     S_II * η      (displacement of sagittal rim rays)

where S_II is the Seidel coma coefficient and η is the chief-ray image height.
The relationship tangential = 3 × sagittal defines the "comatic flare".

Algorithm — Seidel (third-order)
---------------------------------
1.  Establish the paraxial focal plane: trace a marginal ray (h=aperture_mm,
    u=0) and record the paraxial image distance d_img.
2.  For each field angle θ_f:
    a.  Compute the paraxial chief-ray image height y₀ by propagating a chief
        ray (h=0 at first surface, u=tan θ_f) through the system paraxially and
        then projecting to d_img.
    b.  Trace N rim rays at heights h_k = aperture_mm * cos(φ_k) and angles
        u_k = tan(θ_f) using exact meridional Snell (trace_lens_stack).
    c.  Propagate each rim ray to d_img by continuing the exact ray: take the
        last surface (Y_last, L_out, M_out) from the meridional trace and
        compute Y_img = Y_last + (M_out/L_out) * d_img.
    d.  Tangential coma = |mean_y_tang - y₀|  where mean_y_tang is the mean of
        Y_img for tangential-fan rays (|sin(φ_k)| < 0.5, i.e. near φ=0 or π).
        This equals 3 * |S_II| * |y₀| in the Seidel limit (Welford §11.4).
    e.  Sagittal coma = tangential_coma / 3 (exact equality in Seidel limit;
        Welford §11.4 eq. 11.4.4).
    f.  total_coma = sqrt(tangential² + sagittal²).
    g.  Seidel prediction = 3 * |S_II| * |y₀| (Born & Wolf §5.3 eq. 5.3.29).
    h.  seidel_match_fraction = |total_coma - seidel_pred_total| / seidel_pred_total.

Algorithm — Finite-ray OPD (Welford §5.5 / Born & Wolf §9.2)
--------------------------------------------------------------
For an off-axis field point at image height y_field, trace rays from N pupil
samples through the system via 3-D skew ray tracing (trace_skew_ray).  The
Optical Path Length (OPL) for each ray is accumulated as:

    OPL = Σ n_k * |segment_k|

where the sum is over all ray segments between consecutive intersection points.
OPD_i = OPL_i - OPL_chief (chief ray OPL).  The OPD map W(ρ, θ) is then
fitted to Noll-ordered Zernike polynomials.  The Zernike Z_7 coefficient
(coma_y = √8·(3ρ³−2ρ)·sin θ, Noll 1976) extracts the primary coma content.

The Seidel W_131 coefficient relates to Z_7 via (Born & Wolf §9.2):
    Z_7 coefficient ≈ W_131 / (√8 · 3/8) for pupil-rim normalised OPD.

Depth bar (OPTICS-COMA-COMPUTE)
--------------------------------
* Flat surfaces (c=0, zero power): afocal stack → coma = 0 (no image plane).
* BK7 biconvex (R=±50 mm, t=5 mm, n=1.5168) at 14° field, 5 mm aperture:
  total_coma > 1 μm (1e-3 mm).
* Field-angle scaling: coma scales linearly with |tan(θ)| (small-angle limit).
* Seidel match: |total_coma - seidel_pred| / seidel_pred < 0.25 at ≤ 5° field
  (3rd-order dominates; factor-3 relationship between tangential and sagittal).

HONEST FLAG
-----------
This module computes third-order (Seidel) coma AND (optionally) finite-ray OPD
coma via Zernike Z_7 fitting.  The finite-ray OPD path uses 3-D skew ray tracing
(trace_skew_ray) to capture higher-order coma contributions beyond the Seidel
third-order prediction.  The Seidel prediction is 3rd-order only and degrades for:
  * Large field angles (> ~10° for fast systems)
  * Fast (low f/#) systems where 5th-order terms dominate
  * Aspheric surfaces that introduce higher-order wavefront error

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §11.4 (comatic aberration, tangential and sagittal coma, flare length,
    eq. 11.4.4 tangential coma = 3 × sagittal coma).
    §5.5 (finite-ray OPD, optical path difference from reference sphere).
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999,
    §5.3 (transverse ray aberrations from Seidel wavefront coefficients,
    eq. 5.3.29 coma aberration; tangential/sagittal decomposition).
    §9.2 (Zernike polynomial expansion of wavefront OPD).
Noll, R.J. (1976) "Zernike polynomials and atmospheric turbulence",
    J. Opt. Soc. Am. 66, 207-211.

Units: lengths in mm, angles in radians.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import (
    trace_lens_stack,
    _paraxial_refract,
    _paraxial_transfer,
)
from kerf_cad_core.optics.seidel_aberrations import seidel_coefficients
from kerf_cad_core.optics.skew_ray_tracer import (
    Ray3D,
    OpticalSurface,
    trace_skew_ray,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    return None


def _validate_surface(s: Any, idx: int) -> str | None:
    if not isinstance(s, dict):
        return f"surface[{idx}] must be a dict"
    for fld in ("c", "t", "n"):
        if fld not in s:
            return f"surface[{idx}] missing required field '{fld}'"
        err = _guard(f"surface[{idx}].{fld}", s[fld])
        if err:
            return err
    if float(s["n"]) < 1.0:
        return f"surface[{idx}].n must be >= 1.0"
    return None


def _paraxial_image_distance(
    surfaces: list[dict],
    aperture_mm: float,
    n_object: float,
) -> float:
    """
    Paraxial image distance from a marginal ray (h=aperture_mm, u=0).

    Returns the distance from the last surface vertex to the paraxial focus.
    Returns math.inf for afocal/zero-power stacks.
    """
    h = aperture_mm
    u = 0.0
    n = n_object
    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_p = float(surf["n"])
        u_p = _paraxial_refract(h, u, n, n_p, c)
        h = _paraxial_transfer(h, u_p, t)
        u = u_p
        n = n_p
    if abs(u) < 1e-18:
        return math.inf
    return -h / u


def _paraxial_chief_image_height(
    surfaces: list[dict],
    field_angle_deg: float,
    n_object: float,
    img_dist: float,
) -> float:
    """
    Paraxial chief-ray image height at the focal plane (img_dist from last surface).

    Chief ray: h=0 at first surface (stop at first surface), u = tan(field_angle_deg).
    """
    u_c = math.tan(math.radians(field_angle_deg))
    h_c = 0.0
    n = n_object
    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_p = float(surf["n"])
        u_c_p = _paraxial_refract(h_c, u_c, n, n_p, c)
        h_c = _paraxial_transfer(h_c, u_c_p, t)
        u_c = u_c_p
        n = n_p
    return h_c + u_c * img_dist


def _propagate_to_imgplane(last_mer: dict, img_dist: float) -> float | None:
    """
    Propagate the exact meridional ray from the last surface to the focal plane.

    last_mer  : last entry in meridional_surfaces from trace_lens_stack.
    img_dist  : paraxial image distance from last surface vertex (mm).

    Returns the Y intercept at the focal plane, or None if the ray failed.
    """
    Y = last_mer.get("Y_mm")
    L = last_mer.get("L_out")
    M = last_mer.get("M_out")
    if Y is None or L is None or M is None:
        return None
    if not (math.isfinite(Y) and math.isfinite(L) and math.isfinite(M)):
        return None
    if abs(L) < 1e-15:
        return None
    return Y + (M / L) * img_dist


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ComaFieldPoint:
    """
    Coma metrics at a single field angle.

    Attributes
    ----------
    field_angle_deg       : float  Field angle (degrees).
    tangential_coma_mm    : float  Mean Y-displacement of tangential-fan rim rays
                                   from chief-ray image point (mm).  Equals
                                   3 * |S_II| * |y₀| in the Seidel limit
                                   (Welford 1986 §11.4).
    sagittal_coma_mm      : float  Sagittal coma = tangential_coma / 3 (mm).
    total_coma_mm         : float  sqrt(tangential² + sagittal²) (mm).
    seidel_prediction_mm  : float  3 * |S_II| * |y₀| (mm); Born & Wolf §5.3 eq. 5.3.29.
    seidel_match_fraction : float  |total_coma - seidel_pred_total| / seidel_pred_total;
                                   math.nan when seidel_pred < 1e-15.
    chief_ray_y_mm        : float  Paraxial chief-ray image height y₀ (mm).
    n_rays_valid          : int    Number of rim rays successfully traced.
    """

    field_angle_deg: float = 0.0
    tangential_coma_mm: float = 0.0
    sagittal_coma_mm: float = 0.0
    total_coma_mm: float = 0.0
    seidel_prediction_mm: float = 0.0
    seidel_match_fraction: float = math.nan
    chief_ray_y_mm: float = 0.0
    n_rays_valid: int = 0

    def to_dict(self) -> dict:
        return {
            "field_angle_deg": self.field_angle_deg,
            "tangential_coma_mm": self.tangential_coma_mm,
            "sagittal_coma_mm": self.sagittal_coma_mm,
            "total_coma_mm": self.total_coma_mm,
            "seidel_prediction_mm": self.seidel_prediction_mm,
            "seidel_match_fraction": (
                self.seidel_match_fraction
                if math.isfinite(self.seidel_match_fraction)
                else None
            ),
            "chief_ray_y_mm": self.chief_ray_y_mm,
            "n_rays_valid": self.n_rays_valid,
        }


@dataclass
class ComaReport:
    """
    Coma aberration report for a lens stack across multiple field angles.

    Attributes
    ----------
    per_field             : list[ComaFieldPoint]
    aperture_radius_mm    : float  Entrance-pupil rim radius used.
    S_II                  : float  Seidel coma coefficient from paraxial trace.
    opd_per_field         : list   Finite-ray OPD results (FiniteRayOpdReport or dict)
                                   per non-zero field angle.  Empty list when
                                   compute_coma(..., compute_opd=False).
    honest_flag           : str    Scope and limitations.
    """

    per_field: list = field(default_factory=list)
    aperture_radius_mm: float = 1.0
    S_II: float = 0.0
    opd_per_field: list = field(default_factory=list)
    honest_flag: str = (
        "Third-order (Seidel) coma computed from paraxial pupil-rim trace. "
        "Higher-order coma (Hopkins 5th-order, oblique spherical aberration) "
        "is available via compute_finite_ray_coma() or compute_coma(..., compute_opd=True): "
        "finite-ray OPD traced via 3-D skew rays (trace_skew_ray) and fitted "
        "to Zernike Z_7 (coma_y, Noll 1976). "
        "Monochromatic; chromatic coma excluded. "
        "Stop assumed at first surface."
    )

    def to_dict(self) -> dict:
        opd_list = []
        for opd in self.opd_per_field:
            if hasattr(opd, "to_dict"):
                opd_list.append(opd.to_dict())
            else:
                opd_list.append(opd)
        return {
            "ok": True,
            "aperture_radius_mm": self.aperture_radius_mm,
            "S_II": self.S_II,
            "per_field": [fp.to_dict() for fp in self.per_field],
            "opd_per_field": opd_list,
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Finite-ray OPD result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FiniteRayOpdReport:
    """
    Result of finite-ray OPD coma analysis via Zernike Z_7 fitting.

    Attributes
    ----------
    wave_aberration_W131_rms_waves : float
        RMS wavefront OPD in waves (at the specified wavelength) attributed
        to coma (i.e. the RMS of the Z_7-term-only wavefront across the pupil).
        Computed as |z7_coeff| * sqrt(pi) / wavelength_mm (units: waves).
        Honest: this is the Zernike Z_7 RMS projection; higher-order coma
        terms (Z_14, Z_17, ...) are excluded.
    zernike_Z7_coeff : float
        Fitted Noll Z_7 (coma_y = sqrt(8)*(3ρ³-2ρ)*sinθ) coefficient in mm
        (same units as the OPD input).  Positive = wavefront leads for upper
        pupil half.  Relation to Born & Wolf W_131: Z_7 ≈ W_131 / (3*sqrt(8)/8).
    compared_to_seidel : float
        Residual (finite_ray_rms_waves - seidel_rms_waves) / seidel_rms_waves.
        Positive = finite-ray OPD > Seidel prediction (higher-order contribution
        present).  math.nan when seidel_rms_waves < 1e-15.
    seidel_rms_waves : float
        Seidel third-order coma prediction as RMS wavefront (waves) for
        reference; computed from S_II via the Welford §11.4 formula.
    n_rays_valid : int
        Number of pupil sample rays successfully traced.
    honest_caveat : str
        Scope and limitations of this finite-ray OPD analysis.
    """

    wave_aberration_W131_rms_waves: float = 0.0
    zernike_Z7_coeff: float = 0.0
    compared_to_seidel: float = math.nan
    seidel_rms_waves: float = 0.0
    n_rays_valid: int = 0
    honest_caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "wave_aberration_W131_rms_waves": self.wave_aberration_W131_rms_waves,
            "zernike_Z7_coeff": self.zernike_Z7_coeff,
            "compared_to_seidel": (
                self.compared_to_seidel
                if math.isfinite(self.compared_to_seidel)
                else None
            ),
            "seidel_rms_waves": self.seidel_rms_waves,
            "n_rays_valid": self.n_rays_valid,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Finite-ray OPD helpers
# ---------------------------------------------------------------------------

_OPD_CAVEAT = (
    "Finite-ray OPD coma (Welford §5.5 / Born & Wolf §9.2): "
    "OPL accumulated via 3-D skew ray trace (trace_skew_ray); "
    "OPD = OPL_ray - OPL_chief; Zernike Z_7 (Noll 1976 coma_y) fitted "
    "via numpy least-squares to N pupil sample rays on a uniform annular grid. "
    "Monochromatic; wavelength sets OPD-to-waves conversion. "
    "Higher-order aspheric terms (A4, A6, ...) NOT supported by skew tracer. "
    "Pupil sampling: uniform grid in (rho, theta); 2 annular zones × N/2 azimuths. "
    "Z_7-only RMS projection: higher-order coma terms (Z_14, Z_17, ...) excluded. "
    "Stop at first surface; n_object = refractive index of input medium."
)


def _surfaces_to_optical(
    surfaces: list[dict],
    n_object: float,
) -> tuple[list[OpticalSurface], list[float]]:
    """
    Convert stack dicts {c, t, n} to OpticalSurface objects for trace_skew_ray.

    Also returns the list of cumulative vertex z-positions so that we can
    place the source ray at z < first surface and target the image plane.

    Returns (optical_surfaces, vertex_z_list).
    The vertex_z of the first surface is set to 0.0; subsequent surfaces
    are placed at cumulative thickness offsets.
    """
    optical: list[OpticalSurface] = []
    z_verts: list[float] = []
    z = 0.0
    for s in surfaces:
        c = float(s["c"])
        t = float(s["t"])
        n_after = float(s["n"])
        k = float(s.get("k", 0.0))
        radius_mm = (1.0 / c) if abs(c) > 1e-18 else 0.0
        optical.append(OpticalSurface(
            vertex_z_mm=z,
            radius_mm=radius_mm,
            refractive_index_after=n_after,
            conic_k=k,
        ))
        z_verts.append(z)
        z += t
    return optical, z_verts


def _compute_opl(
    ray: Ray3D,
    optical_surfaces: list[OpticalSurface],
    n_object: float,
    img_z: float,
) -> float | None:
    """
    Trace ray through optical_surfaces and accumulate OPL up to the image plane z.

    OPL = Σ n_k * segment_length_k  over all segments from start to img_z.

    Returns OPL (mm), or None if the ray failed (TIR, missed surface, etc.).
    """
    result = trace_skew_ray(ray, optical_surfaces, n_before_first=n_object)
    if result.tir_occurred:
        return None

    # Check that ray history has at least 2 entries (start + at least one surface)
    if len(result.ray_history) < 2:
        return None

    opl = 0.0
    n_current = n_object

    # ray_history[0] = input ray (origin = start of ray).
    # ray_history[k] = ray after k-th surface refraction (origin = intersection).
    # Each segment k→k+1: from ray_history[k].origin to ray_history[k+1].origin,
    # in medium with refractive index n_k.
    for k in range(len(result.ray_history) - 1):
        p0 = result.ray_history[k].origin_xyz
        p1 = result.ray_history[k + 1].origin_xyz
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        dz = p1[2] - p0[2]
        seg_len = math.sqrt(dx * dx + dy * dy + dz * dz)
        opl += n_current * seg_len
        # n_current updates to n_after of the surface just crossed.
        # The surface index k corresponds to optical_surfaces[k].
        if k < len(optical_surfaces):
            n_current = optical_surfaces[k].refractive_index_after

    # Final segment: from last intersection to image plane at z=img_z
    p_last = result.final_position_xyz
    d_last = result.final_direction_xyz
    if abs(d_last[2]) < 1e-18:
        return None  # ray parallel to image plane
    t_img = (img_z - p_last[2]) / d_last[2]
    if t_img < 0.0:
        # Ray moving away from image plane — still trace backwards for OPL
        # (this can happen in unusual geometries; skip rather than corrupt OPL)
        return None
    seg_len = math.sqrt(
        (d_last[0] * t_img) ** 2 + (d_last[1] * t_img) ** 2 + t_img ** 2
    )
    opl += n_current * seg_len
    return opl


def _zernike_z7(rho: float, theta: float) -> float:
    """Z_7 = sqrt(8) * (3*rho^3 - 2*rho) * sin(theta)  (Noll 1976 coma_y)."""
    return math.sqrt(8.0) * (3.0 * rho ** 3 - 2.0 * rho) * math.sin(theta)


def _fit_z7_coefficient(opd_samples: list[tuple[float, float, float]]) -> float:
    """
    Fit Z_7 coefficient to OPD samples via direct least-squares inner product
    on the Noll orthonormal basis.

    Because Z_7 is orthogonal to all other Zernike polynomials over the unit disk,
    the coefficient is:

        c_7 = (1/π) * Σ_k  OPD_k * Z_7(ρ_k, θ_k) * ΔA_k

    For uniformly weighted samples (equal area weights), this reduces to a
    simple mean inner product:

        c_7 ≈ (2 / N) * Σ_k  OPD_k * Z_7(ρ_k, θ_k)

    where the factor 2/N accounts for the Noll normalisation ∫∫ Z_7^2 dA = π
    and the uniform sampling over the unit disk (∫∫ dA = π → normalised to 1).

    We use pure-Python least-squares on [c_7] only via the projection formula.
    This avoids a numpy dependency in the hot path (skew_ray_tracer is also
    pure-Python).

    Returns the c_7 coefficient in the same units as OPD_k.
    """
    numerator = 0.0
    denominator = 0.0
    for rho, theta, opd in opd_samples:
        z7 = _zernike_z7(rho, theta)
        numerator += opd * z7
        denominator += z7 * z7
    if denominator < 1e-30:
        return 0.0
    return numerator / denominator


# ---------------------------------------------------------------------------
# Public finite-ray OPD function
# ---------------------------------------------------------------------------

def compute_finite_ray_coma(
    surfaces: list[dict],
    field_height_mm: float,
    num_pupil_samples: int = 64,
    aperture_radius_mm: float = 1.0,
    n_object: float = 1.0,
    wavelength_mm: float = 0.000587,  # 587 nm (d-line)
) -> "FiniteRayOpdReport | dict":
    """
    Compute finite-ray OPD coma via Zernike Z_7 fitting (Welford §5.5 / Born & Wolf §9.2).

    For the off-axis field point at image height ``field_height_mm``, traces
    ``num_pupil_samples`` rays from a uniform annular pupil grid through the
    system using 3-D skew ray tracing (trace_skew_ray).  At each ray, the
    optical path length (OPL = Σ n_k · segment_k) is accumulated.  The OPD
    relative to the chief ray:

        OPD_i = OPL_i - OPL_chief

    is then projected onto the Noll Z_7 basis (coma_y) via a direct inner-
    product estimator.  The RMS wavefront coma is reported in waves at
    ``wavelength_mm``.

    The Seidel prediction for W_131 is also computed for comparison:
        W_131_seidel ≈ (3/8) * S_II / (n_exit * u_exit^2)   [Born & Wolf §5.3]
    and the residual compared_to_seidel = (finite_rms - seidel_rms) / seidel_rms
    is positive when higher-order coma dominates.

    Parameters
    ----------
    surfaces : list of surface dicts
        Each dict: c (mm^-1), t (mm), n (>= 1.0), optional k.
    field_height_mm : float
        Off-axis field height at the image plane (mm).  Used to compute the
        chief-ray direction angle.
    num_pupil_samples : int
        Number of pupil rays to trace (excluding chief ray).  Default 64.
        Must be >= 8.
    aperture_radius_mm : float
        Entrance-pupil rim radius (mm).  Default 1.0.
    n_object : float
        Refractive index of object space.  Default 1.0.
    wavelength_mm : float
        Wavelength for OPD-to-waves conversion (mm).  Default 587 nm = 5.87e-4 mm.

    Returns
    -------
    FiniteRayOpdReport  on success.
    dict {ok: False, reason: ...}  on input error or afocal stack.

    References
    ----------
    Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §5.5.
    Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999, §9.2.
    Noll, R.J. (1976) "Zernike polynomials and atmospheric turbulence",
        J. Opt. Soc. Am. 66, 207-211.
    """
    # ---- Input validation --------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list of surface dicts")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    e = _guard("field_height_mm", field_height_mm)
    if e:
        return _err(e)
    e = _guard("aperture_radius_mm", aperture_radius_mm, positive=True)
    if e:
        return _err(e)
    e = _guard("n_object", n_object, positive=True)
    if e:
        return _err(e)
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")
    e = _guard("wavelength_mm", wavelength_mm, positive=True)
    if e:
        return _err(e)

    try:
        num_pupil_samples = int(num_pupil_samples)
    except (TypeError, ValueError):
        return _err("num_pupil_samples must be an integer")
    if num_pupil_samples < 8:
        return _err("num_pupil_samples must be >= 8")

    ap = float(aperture_radius_mm)
    n0 = float(n_object)
    fh = float(field_height_mm)
    wl = float(wavelength_mm)

    # ---- Paraxial image distance -------------------------------------------
    img_dist = _paraxial_image_distance(surfaces, ap, n0)
    if not math.isfinite(img_dist):
        return _err("afocal stack: no paraxial focus; finite-ray OPD undefined")

    # ---- Build OpticalSurface list and image plane z -----------------------
    optical_surfaces, vertex_z_list = _surfaces_to_optical(surfaces, n0)

    # The last surface vertex z + img_dist = z-coordinate of the image plane
    last_z = vertex_z_list[-1] if vertex_z_list else 0.0
    img_z = last_z + img_dist

    # ---- Seidel S_II reference for comparison ------------------------------
    # Estimate field angle from field_height_mm / img_dist (small-angle)
    if abs(img_dist) > 1e-10:
        field_angle_deg = math.degrees(math.atan(abs(fh) / abs(img_dist)))
    else:
        field_angle_deg = 0.0

    seidel_ref = seidel_coefficients(
        surfaces, aperture=ap,
        field_angle_deg=max(field_angle_deg, 1e-3),
        n_object=n0,
    )
    S_II = seidel_ref.S_II if not isinstance(seidel_ref, dict) else 0.0

    # Seidel tangential coma at this field height:
    #   tangential_coma_seidel = 3 * |S_II| * |y_chief|
    # Convert to OPD (waves) via Born & Wolf §5.3:
    #   W_131 ≈ (1/2) * S_II * h² * y_chief  (wavefront coefficient)
    # Seidel RMS wavefront ≈ W_131 / sqrt(2) (RMS of coma wavefront = max/sqrt(2))
    # We use the transverse coma -> wavefront relation:
    #   W_131 (mm) = S_II * (aperture/EFL)² * y_chief / (n_exit * u_exit)
    # For simplicity, estimate from Seidel tangential coma:
    #   seidel_tan_coma_mm ≈ 3 * |S_II| * |fh|  (Born & Wolf §5.3 eq. 5.3.29)
    # and convert to RMS waves using the Zernike Z_7 relation:
    #   RMS_coma_waves = Z_7_coeff_from_seidel / wavelength_mm
    # where Z_7_from_seidel = (S_II * fh) / (3 * sqrt(8) / (3*8)) (estimated)
    #
    # Simpler: just report Seidel RMS in waves from the tangential coma prediction:
    #   seidel_tan_coma ≈ 3 * |S_II| * |fh|
    #   seidel_rms_waves ≈ seidel_tan_coma / (3 * sqrt(2)) / wavelength_mm
    # (factor 1/sqrt(2) approximates coma RMS ~ coma_max / sqrt(2))
    seidel_tan_coma_mm = 3.0 * abs(S_II) * abs(fh)
    seidel_rms_waves = (seidel_tan_coma_mm / (3.0 * math.sqrt(2.0))) / wl

    # ---- Chief ray: propagate along the optical axis with field offset -----
    # Chief ray starts at z well before the first surface, y=0 (stop at first
    # surface), with u = fh / img_dist direction so it hits y=fh at image plane.
    # We place the source at z = vertex_z_list[0] - 10*ap to be clear of first surface.
    z_start = vertex_z_list[0] - max(10.0 * ap, 1.0) if vertex_z_list else -10.0

    # Chief ray direction: aims from (0, 0, z_start) toward (0, fh, img_z)
    chief_dy = fh
    chief_dz = img_z - z_start
    chief_mag = math.sqrt(chief_dy ** 2 + chief_dz ** 2)
    chief_ray = Ray3D(
        origin_xyz=(0.0, 0.0, z_start),
        direction_xyz=(0.0, chief_dy / chief_mag, chief_dz / chief_mag),
        wavelength_nm=wl * 1e6,  # mm -> nm
    )
    opl_chief = _compute_opl(chief_ray, optical_surfaces, n0, img_z)
    if opl_chief is None:
        return _err(
            "Chief ray trace failed (TIR or missed surface); "
            "cannot compute finite-ray OPD"
        )

    # ---- Pupil sampling: 2 annular rings × num_pupil_samples/2 azimuths ---
    # Use 2 rings at rho = 0.5 and 1.0 to give a representative OPD map with
    # num_pupil_samples / 2 azimuths per ring (rounded to nearest integer >= 4).
    n_az = max(4, num_pupil_samples // 2)
    pupil_rings = [0.5, 1.0]

    opd_samples: list[tuple[float, float, float]] = []
    n_valid = 0

    for rho in pupil_rings:
        for k in range(n_az):
            theta = 2.0 * math.pi * k / n_az
            # Pupil coordinates: enter-pupil plane is the first surface
            x_pup = ap * rho * math.cos(theta)
            y_pup = ap * rho * math.sin(theta)

            # The pupil ray starts at the entrance pupil (first surface), at
            # (x_pup, y_pup, z_start) and propagates toward the image plane.
            # Direction: same azimuthal tilt as chief ray plus pupil offset.
            # We send each pupil ray from (x_pup, y_pup, z_start) toward
            # (0, fh, img_z), mimicking a telecentric object illumination
            # from the pupil.  The OPL difference captures wavefront aberration.
            dx_r = 0.0 - x_pup
            dy_r = fh - y_pup
            dz_r = img_z - z_start
            mag_r = math.sqrt(dx_r ** 2 + dy_r ** 2 + dz_r ** 2)
            if mag_r < 1e-18:
                continue

            pupil_ray = Ray3D(
                origin_xyz=(x_pup, y_pup, z_start),
                direction_xyz=(dx_r / mag_r, dy_r / mag_r, dz_r / mag_r),
                wavelength_nm=wl * 1e6,
            )
            opl_ray = _compute_opl(pupil_ray, optical_surfaces, n0, img_z)
            if opl_ray is None:
                continue

            opd = opl_ray - opl_chief
            opd_samples.append((rho, theta, opd))
            n_valid += 1

    if n_valid < 8:
        return _err(
            f"Too few valid pupil rays ({n_valid}); cannot fit Z_7 coefficient. "
            "Check aperture_radius_mm and surface geometry."
        )

    # ---- Fit Z_7 coefficient -----------------------------------------------
    z7_coeff = _fit_z7_coefficient(opd_samples)

    # RMS of Z_7 wavefront over unit disk = |c_7| * sqrt(pi/2) / sqrt(pi) = |c_7| / sqrt(2)
    # (since Noll Z_7 has RMS = 1/sqrt(pi) * sqrt(integral Z_7^2 dA) and integral = pi)
    # Actually, for Noll orthonormal polynomials: ∫∫ Z_j^2 dA = π, so
    # the RMS contribution = |c_7| * sqrt(π) / sqrt(π) = |c_7|  (RMS = coefficient)
    # for orthonormal basis.  Convert to waves:
    rms_opd_mm = abs(z7_coeff)
    rms_waves = rms_opd_mm / wl

    # ---- Residual vs Seidel ------------------------------------------------
    if seidel_rms_waves > 1e-15:
        compared_to_seidel = (rms_waves - seidel_rms_waves) / seidel_rms_waves
    else:
        compared_to_seidel = math.nan

    return FiniteRayOpdReport(
        wave_aberration_W131_rms_waves=rms_waves,
        zernike_Z7_coeff=z7_coeff,
        compared_to_seidel=compared_to_seidel,
        seidel_rms_waves=seidel_rms_waves,
        n_rays_valid=n_valid,
        honest_caveat=_OPD_CAVEAT,
    )


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_coma(
    stack: list[dict],
    field_angles_deg: list[float],
    n_pupil_rays: int = 16,
    aperture_radius_mm: float = 1.0,
    n_object: float = 1.0,
    compute_opd: bool = False,
    opd_num_pupil_samples: int = 64,
    opd_wavelength_mm: float = 0.000587,
) -> "ComaReport | dict":
    """
    Compute coma aberration metrics for each field angle in a lens stack.

    Algorithm (Welford 1986 §11.4 / Born & Wolf §5.3)
    ---------------------------------------------------
    1.  Establish the paraxial focal plane by tracing a marginal ray
        (h=aperture_radius_mm, u=0) paraxially.
    2.  For each field angle:
        a.  Compute paraxial chief-ray image height y₀ (stop at first surface).
        b.  Trace N rim rays at h_k = aperture_radius_mm * cos(φ_k),
            u_k = tan(θ_f) using exact meridional Snell (trace_lens_stack).
        c.  Propagate each ray to the paraxial focal plane using the last-
            surface meridional exit direction.
        d.  Tangential coma = |mean_Y_tang − y₀| for rays with |sin(φ)| < 0.5
            (tangential fan, near φ = 0 or π; Welford §11.4).
        e.  Sagittal coma = tangential_coma / 3 (Welford §11.4 eq. 11.4.4).
        f.  total_coma = sqrt(tan² + sag²).
        g.  Seidel prediction = 3 × |S_II| × |y₀| (Born & Wolf §5.3 eq. 5.3.29).

    When ``compute_opd=True``, additionally calls ``compute_finite_ray_coma``
    for each non-zero field angle and attaches the ``FiniteRayOpdReport`` to
    the ``ComaReport.opd_per_field`` list.

    Parameters
    ----------
    stack : list of surface dicts
        Each dict: c (mm^-1), t (mm), n (>= 1.0), optional k.
    field_angles_deg : list of float
        Field angles in degrees. 0 = on-axis.
    n_pupil_rays : int
        Number of rim rays per field (default 16). Must be >= 4.
    aperture_radius_mm : float
        Entrance-pupil rim radius (mm). Default 1.0.
    n_object : float
        Refractive index of object space. Default 1.0.
    compute_opd : bool
        If True, also run finite-ray OPD analysis via Zernike Z_7 fitting
        for each non-zero field angle.  Default False (opt-in to avoid the
        additional 3-D skew ray tracing cost).
    opd_num_pupil_samples : int
        Pupil sample count for finite-ray OPD (default 64).  Passed to
        ``compute_finite_ray_coma``.
    opd_wavelength_mm : float
        Wavelength for OPD-to-waves conversion (mm).  Default 587 nm.

    Returns
    -------
    ComaReport  on success.
    dict {ok: False, reason: ...}  on input error.

    References
    ----------
    Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
        §11.4 (comatic flare length, tangential and sagittal coma).
        §5.5 (finite-ray OPD).
    Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999,
        §5.3 (transverse ray aberrations from Seidel coefficients,
        eq. 5.3.29 tangential/sagittal coma).
        §9.2 (Zernike OPD expansion).
    """
    # ---- Input validation ---------------------------------------------------
    if not isinstance(stack, list) or len(stack) == 0:
        return _err("stack must be a non-empty list of surface dicts")

    for idx, s in enumerate(stack):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    if not isinstance(field_angles_deg, list) or len(field_angles_deg) == 0:
        return _err("field_angles_deg must be a non-empty list")

    e = _guard("aperture_radius_mm", aperture_radius_mm, positive=True)
    if e:
        return _err(e)
    e = _guard("n_object", n_object, positive=True)
    if e:
        return _err(e)
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    try:
        n_pupil_rays = int(n_pupil_rays)
    except (TypeError, ValueError):
        return _err("n_pupil_rays must be an integer")
    if n_pupil_rays < 4:
        return _err("n_pupil_rays must be >= 4")

    ap = float(aperture_radius_mm)
    n0 = float(n_object)

    # ---- Paraxial image distance -------------------------------------------
    img_dist = _paraxial_image_distance(stack, ap, n0)
    if not math.isfinite(img_dist):
        # Afocal / zero-power stack: coma undefined in Seidel sense.
        # Return zero coma for all field angles (no comatic flare without a focus).
        per_field_zero = []
        for ang in field_angles_deg:
            try:
                ang_f = float(ang)
            except (TypeError, ValueError):
                return _err(f"field_angle {ang!r} must be a number")
            per_field_zero.append(ComaFieldPoint(
                field_angle_deg=ang_f,
                tangential_coma_mm=0.0,
                sagittal_coma_mm=0.0,
                total_coma_mm=0.0,
                seidel_prediction_mm=0.0,
                seidel_match_fraction=math.nan,
                chief_ray_y_mm=0.0,
                n_rays_valid=0,
            ))
        return ComaReport(per_field=per_field_zero, aperture_radius_mm=ap, S_II=0.0,
                          opd_per_field=[])

    # ---- Seidel S_II -------------------------------------------------------
    # S_II embeds the aperture height h at each surface via A = n*i = n*(u + h*c).
    # Evaluate at 5° reference so the chief-ray contribution is non-zero.
    # Welford 1986 §6.2.
    _ref_field = 5.0
    seidel_ref = seidel_coefficients(
        stack, aperture=ap, field_angle_deg=_ref_field, n_object=n0
    )
    S_II = seidel_ref.S_II if not isinstance(seidel_ref, dict) else 0.0

    # ---- Pupil azimuth angles ----------------------------------------------
    azimuths = [2.0 * math.pi * k / n_pupil_rays for k in range(n_pupil_rays)]

    # ---- Per-field computation ---------------------------------------------
    per_field: list[ComaFieldPoint] = []

    for ang_deg in field_angles_deg:
        try:
            ang_deg = float(ang_deg)
        except (TypeError, ValueError):
            return _err(f"field_angle {ang_deg!r} must be a number")

        # Paraxial chief-ray image height at focal plane
        y_chief = _paraxial_chief_image_height(stack, ang_deg, n0, img_dist)
        u_field = math.tan(math.radians(ang_deg))

        # Trace rim rays and propagate to paraxial focal plane
        tang_y_vals: list[float] = []
        n_valid = 0

        for phi in azimuths:
            # Meridional height of this pupil ray: h = ap * cos(phi)
            # The angle stays at u_field (we sample the pupil in height, not angle).
            ray_h = ap * math.cos(phi)

            result = trace_lens_stack(
                stack, ray_h=ray_h, ray_u=u_field, n_object=n0
            )
            if not result.get("ok"):
                continue

            mer = result.get("meridional_surfaces")
            if not mer:
                continue
            Y_img = _propagate_to_imgplane(mer[-1], img_dist)
            if Y_img is None:
                continue

            n_valid += 1

            # Tangential fan: |sin(phi)| < 0.5 selects rays near φ=0 or φ=π
            if abs(math.sin(phi)) < 0.5:
                tang_y_vals.append(Y_img)

        if n_valid == 0 or len(tang_y_vals) == 0:
            per_field.append(ComaFieldPoint(
                field_angle_deg=ang_deg,
                tangential_coma_mm=math.nan,
                sagittal_coma_mm=math.nan,
                total_coma_mm=math.nan,
                seidel_prediction_mm=0.0,
                seidel_match_fraction=math.nan,
                chief_ray_y_mm=y_chief,
                n_rays_valid=n_valid,
            ))
            continue

        # Tangential coma = |mean(Y_tang) - y_chief|  (Welford §11.4)
        tan_coma = abs(sum(tang_y_vals) / len(tang_y_vals) - y_chief)

        # Sagittal coma = tangential / 3  (Welford §11.4 eq. 11.4.4)
        sag_coma = tan_coma / 3.0

        total_coma = math.sqrt(tan_coma ** 2 + sag_coma ** 2)

        # Seidel prediction for tangential coma:
        #   tangential_coma_seidel = 3 * |S_II| * |y_chief|
        # (Born & Wolf §5.3 eq. 5.3.29; S_II already encodes aperture height h
        # at each surface via A = n*(u + h*c).)
        seidel_pred_tan = 3.0 * abs(S_II) * abs(y_chief)
        seidel_pred_sag = seidel_pred_tan / 3.0
        seidel_pred_total = math.sqrt(seidel_pred_tan ** 2 + seidel_pred_sag ** 2)

        if seidel_pred_total > 1e-15:
            match_frac = abs(total_coma - seidel_pred_total) / seidel_pred_total
        else:
            match_frac = math.nan

        per_field.append(ComaFieldPoint(
            field_angle_deg=ang_deg,
            tangential_coma_mm=tan_coma,
            sagittal_coma_mm=sag_coma,
            total_coma_mm=total_coma,
            seidel_prediction_mm=seidel_pred_tan,   # tangential Seidel (diagnostic)
            seidel_match_fraction=match_frac,
            chief_ray_y_mm=y_chief,
            n_rays_valid=n_valid,
        ))

    # ---- Optional finite-ray OPD -------------------------------------------
    opd_per_field: list = []
    if compute_opd:
        for fp in per_field:
            ang_deg = fp.field_angle_deg
            y_chief = fp.chief_ray_y_mm
            # Only run OPD for non-zero fields (zero field → no coma by symmetry)
            if abs(ang_deg) < 1e-6 or not math.isfinite(y_chief):
                opd_per_field.append(None)
                continue
            opd_result = compute_finite_ray_coma(
                surfaces=stack,
                field_height_mm=y_chief,
                num_pupil_samples=opd_num_pupil_samples,
                aperture_radius_mm=ap,
                n_object=n0,
                wavelength_mm=opd_wavelength_mm,
            )
            opd_per_field.append(opd_result)

    return ComaReport(
        per_field=per_field,
        aperture_radius_mm=ap,
        S_II=S_II,
        opd_per_field=opd_per_field,
    )
