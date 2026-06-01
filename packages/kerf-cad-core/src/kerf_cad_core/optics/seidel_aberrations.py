"""
kerf_cad_core.optics.seidel_aberrations — third-order Seidel aberration coefficients
for a sequential lens stack.

Public API
----------
seidel_coefficients(surfaces, aperture=1.0, field_angle_deg=5.0) -> SeidelReport
    Compute the five Seidel third-order aberration sums for a lens stack.

Theory (Welford 1986 §6.2 / Born & Wolf §5.3)
-----------------------------------------------
Two paraxial rays are traced: the *marginal ray* (on-axis object, full aperture)
and the *chief ray* (edge-of-field object, through centre of the aperture stop).

At each surface j the refraction invariants are:

    A_j    = n_j  * i_j         marginal-ray refraction invariant
    Abar_j = n_j  * ibar_j      chief-ray refraction invariant
    H      = n * u * ybar - n * ubar * y   Lagrange / Smith-Helmholtz invariant
                                            (constant across all surfaces)

where i = u + y * c  (paraxial angle of incidence, Welford §3.3 sign convention)

Per-surface Seidel contributions (Welford 1986 §6.2, eqs. 6.1-6.5):

    SI_j   = -A^2    * h * delta(u/n)   [spherical aberration]
    SII_j  = -A*Abar * h * delta(u/n)   [coma]
    SIII_j = -Abar^2 * h * delta(u/n)   [astigmatism]
    SIV_j  = -H^2    * delta(c/n)       [field curvature, Petzval]
    SV_j   = (SIII_j + SIV_j) * Abar/A [distortion]

where:
    delta(u/n) = (u'/n')_j - (u/n)_j   [reduced angle change across surface]
    delta(c/n) = c_j * (1/n_j' - 1/n_j)
    h          = marginal ray height at surface j

Total wavefront aberration (primary, in waves at lambda=550 nm):
    Reported as sqrt(SI^2+SII^2+SIII^2+SIV^2+SV^2) / (8*lambda) as a scalar.

HONEST FLAG / SCOPE
--------------------
This module computes ONLY third-order (Seidel) aberrations via the paraxial
ray-trace. Real systems require Hopkins' exact wavefront difference (finite ray -
reference sphere) for higher-order aberrations.  In particular:

  * High-aperture systems (F/# < ~3) will show significant 5th-order terms
    not captured here.
  * Aspheric surfaces reduce Seidel but introduce higher-order wavefront error
    not modelled by this method.
  * Chromatic aberrations (axial + lateral) are outside the Seidel framework
    (monochromatic only).
  * Zernike decomposition of the wavefront via finite-ray OPD tracing is now
    implemented: see ``decompose_wavefront_zernike`` and ``ZernikeReport``.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §6.2 (Seidel aberration sums), §3.3 (paraxial nu-form trace).
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999,
    §5.3 (third-order aberration coefficients, eqs. 5.3.14-5.3.18).
Kingslake, R. -- "Lens Design Fundamentals", Academic Press, 1978.

Units: lengths in mm, angles in radians.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kerf_cad_core.optics.lens_stack_trace import _paraxial_refract, _paraxial_transfer
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


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SeidelReport:
    """
    Third-order Seidel aberration coefficients for a lens stack.

    Coefficients follow Welford (1986) §6.2 sign convention.
    A standard positive (converging) singlet in air has S_I > 0
    (under-corrected spherical aberration; marginal rays focus closer
    than the paraxial focal point).

    Attributes
    ----------
    S_I   : float  Spherical aberration sum.
    S_II  : float  Coma sum.
    S_III : float  Astigmatism sum.
    S_IV  : float  Field curvature (Petzval) sum.
    S_V   : float  Distortion sum.
    H     : float  Lagrange (Smith-Helmholtz) invariant.
    per_surface : list of per-surface contribution dicts.
    total_wavefront_aberration_waves : float
        Scalar wavefront error in waves at 550 nm: RSS(SI..SV) / (8*lambda).
        Third-order only; higher-order contributions not included.
    """

    S_I: float = 0.0
    S_II: float = 0.0
    S_III: float = 0.0
    S_IV: float = 0.0
    S_V: float = 0.0
    H: float = 0.0
    per_surface: list = field(default_factory=list)
    total_wavefront_aberration_waves: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "S_I": self.S_I,
            "S_II": self.S_II,
            "S_III": self.S_III,
            "S_IV": self.S_IV,
            "S_V": self.S_V,
            "H_lagrange": self.H,
            "per_surface": self.per_surface,
            "total_wavefront_aberration_waves": self.total_wavefront_aberration_waves,
            "honest_flag": (
                "Third-order (Seidel) only. "
                "Higher-order aberrations require Hopkins finite-ray OPD. "
                "Monochromatic; chromatic aberrations excluded."
            ),
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_LAMBDA_REF_MM = 550e-6  # 550 nm reference wavelength in mm


def seidel_coefficients(
    surfaces: list[dict],
    aperture: float = 1.0,
    field_angle_deg: float = 5.0,
    n_object: float = 1.0,
) -> SeidelReport | dict:
    """
    Compute the five Seidel third-order aberration coefficients for a
    sequential lens stack using a dual paraxial-ray trace.

    Algorithm (Welford 1986 §6.2)
    ------------------------------
    1. Trace the *marginal ray*: h_m = aperture, u_m = 0 (collimated input).
       This defines the aperture-height h and angle u at each surface.

    2. Trace the *chief ray*: h_c = 0, u_c = tan(field_angle_deg) at the
       first surface (stop at first surface, i.e., chief ray height = 0
       at surface 0).  This defines the chief-ray height ybar and angle ubar.

    3. At each surface compute the Seidel sum contributions per Welford (1986)
       §6.2 / Born & Wolf §5.3.

    Parameters
    ----------
    surfaces : list of surface dicts (c, t, n, optional k).
        Same format as trace_lens_stack.  Lengths in mm, c in mm^-1.
    aperture : float
        Marginal ray height at first surface (mm). Default 1.0 mm.
    field_angle_deg : float
        Chief-ray angle at the first surface (degrees). Default 5 deg.
    n_object : float
        Refractive index of object space (default 1.0 = air).

    Returns
    -------
    SeidelReport  on success.
    dict {ok: False, reason: ...}  on input error.

    References
    ----------
    Welford (1986) §6.2 (Seidel sums); §3.3 (paraxial nu-form trace).
    Born & Wolf (1999) §5.3 (aberration coefficients, eqs. 5.3.14-5.3.18).
    """
    # ---- Validate inputs ---------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    for nm, val, pos in [
        ("aperture", aperture, True),
        ("n_object", n_object, True),
    ]:
        e = _guard(nm, val, positive=pos)
        if e:
            return _err(e)

    e = _guard("field_angle_deg", field_angle_deg)
    if e:
        return _err(e)

    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    # ---- Marginal ray trace (h_m=aperture, u_m=0) --------------------------
    h_m = float(aperture)
    u_m = 0.0
    n = float(n_object)

    marginal: list[tuple[float, float, float]] = []  # (h, u_before, u_after)

    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_prime = float(surf["n"])
        u_m_prime = _paraxial_refract(h_m, u_m, n, n_prime, c)
        marginal.append((h_m, u_m, u_m_prime))
        h_m = _paraxial_transfer(h_m, u_m_prime, t)
        u_m = u_m_prime
        n = n_prime

    # ---- Chief ray trace (h_c=0 at first surface, u_c=field_angle) --------
    # Stop assumed at first surface (entrance pupil = first surface).
    h_c = 0.0
    u_c = math.tan(math.radians(float(field_angle_deg)))
    n = float(n_object)

    chief: list[tuple[float, float, float]] = []  # (ybar, ubar_before, ubar_after)

    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_prime = float(surf["n"])
        u_c_prime = _paraxial_refract(h_c, u_c, n, n_prime, c)
        chief.append((h_c, u_c, u_c_prime))
        h_c = _paraxial_transfer(h_c, u_c_prime, t)
        u_c = u_c_prime
        n = n_prime

    # ---- Lagrange invariant H ----------------------------------------------
    # H = n * (u * ybar - ubar * y) -- constant across all surfaces (Welford §3.6).
    # Evaluate at object space (before first surface):
    # marginal: h = aperture, u = 0; chief: h_c = 0, u_c = field angle
    n0 = float(n_object)
    h_m0, u_m0, _ = marginal[0]
    h_c0, u_c0, _ = chief[0]
    # H = n0 * (u_m0 * h_c0 - u_c0 * h_m0)
    H = n0 * (u_m0 * h_c0 - u_c0 * h_m0)

    # ---- Accumulate Seidel sums -------------------------------------------
    S_I = S_II = S_III = S_IV = S_V = 0.0
    per_surface = []

    n_in = float(n_object)
    for idx, surf in enumerate(surfaces):
        c = float(surf["c"])
        n_out = float(surf["n"])

        h, u_in, u_out = marginal[idx]
        ybar, ubar_in, ubar_out = chief[idx]

        # Paraxial angle of incidence (Welford §3.3: i = u + h*c)
        i_m = u_in + h * c        # marginal AOI before refraction
        i_c = ubar_in + ybar * c  # chief AOI before refraction

        # Refraction invariants A = n*i, Abar = n*ibar (Welford §6.2)
        A = n_in * i_m
        Abar = n_in * i_c

        # Reduced angle change delta(u/n) across surface
        delta_un = u_out / n_out - u_in / n_in

        # Petzval curvature change delta(c/n) = c * (1/n' - 1/n)
        delta_cn = c * (1.0 / n_out - 1.0 / n_in)

        # Per-surface Seidel contributions (Welford 1986 §6.2, eqs. 6.1-6.5)
        # Positive S_I => under-corrected spherical aberration (converging singlet)
        si   = -(A ** 2) * h * delta_un
        sii  = -(A * Abar) * h * delta_un
        siii = -(Abar ** 2) * h * delta_un
        siv  = -(H ** 2) * delta_cn
        # S_V = (SIII + SIV) * Abar/A, guard for A near zero (flat/non-refracting surface)
        if abs(A) > 1e-15:
            sv = (siii + siv) * (Abar / A)
        else:
            sv = 0.0

        S_I   += si
        S_II  += sii
        S_III += siii
        S_IV  += siv
        S_V   += sv

        per_surface.append({
            "surface": idx,
            "c_mm_inv": c,
            "n_in": n_in,
            "n_out": n_out,
            "h_mm": h,
            "ybar_mm": ybar,
            "A": A,
            "Abar": Abar,
            "delta_un": delta_un,
            "delta_cn": delta_cn,
            "SI_contrib": si,
            "SII_contrib": sii,
            "SIII_contrib": siii,
            "SIV_contrib": siv,
            "SV_contrib": sv,
        })

        n_in = n_out

    # ---- Total wavefront aberration (scalar, in waves at 550 nm) ----------
    # RSS of all five primary aberration sums, divided by 8*lambda (wave-optics scaling)
    rss = math.sqrt(S_I**2 + S_II**2 + S_III**2 + S_IV**2 + S_V**2)
    total_wfe_waves = rss / (8.0 * _LAMBDA_REF_MM)

    return SeidelReport(
        S_I=S_I,
        S_II=S_II,
        S_III=S_III,
        S_IV=S_IV,
        S_V=S_V,
        H=H,
        per_surface=per_surface,
        total_wavefront_aberration_waves=total_wfe_waves,
    )


# ---------------------------------------------------------------------------
# Zernike basis (Noll 1976, j = 1 .. 36)
# ---------------------------------------------------------------------------
#
# Noll-ordered Zernike polynomials over the unit disk.
# Each entry: (n, m, norm_factor, cos_flag)
#   n          radial degree
#   m          azimuthal frequency (signed: positive = cos term, negative = sin term)
#   norm_factor  √(n+1) for m=0, √(2(n+1)) for m≠0  (orthonormal on unit disk)
#   The radial polynomial R_n^|m|(ρ) is evaluated via the standard summation.
#
# Noll Table 1 (1976):  j=1..36, (n, m) pairs in standard Noll ordering.
# Reference: Noll, R.J. (1976) J. Opt. Soc. Am. 66, 207-211.
# Reference: Born & Wolf §9.2 (radial polynomials, Table 9.2).

# Each entry: (n, m) with m>0 = cos, m<0 = sin, m=0 = rotationally symmetric.
_NOLL_NM: list[tuple[int, int]] = [
    # j=1  n=0
    (0,  0),
    # j=2,3  n=1
    (1,  1), (1, -1),
    # j=4,5,6  n=2
    (2,  0), (2, -2), (2,  2),
    # j=7,8,9,10  n=3
    (3, -1), (3,  1), (3, -3), (3,  3),
    # j=11,12,13,14,15  n=4
    (4,  0), (4,  2), (4, -2), (4,  4), (4, -4),
    # j=16,17,18,19,20,21  n=5
    (5,  1), (5, -1), (5,  3), (5, -3), (5,  5), (5, -5),
    # j=22,23,24,25,26,27,28  n=6
    (6,  0), (6, -2), (6,  2), (6, -4), (6,  4), (6, -6), (6,  6),
    # j=29,30,31,32,33,34,35,36  n=7
    (7, -1), (7,  1), (7, -3), (7,  3), (7, -5), (7,  5), (7, -7), (7,  7),
]

# Human-readable names for j=1..36 (Noll 1976 + standard extensions)
_NOLL_NAMES: list[str] = [
    "piston",
    "tip", "tilt",
    "defocus", "astigmatism_45", "astigmatism_0",
    "coma_y", "coma_x", "trefoil_y", "trefoil_x",
    "spherical", "secondary_astig_0", "secondary_astig_45",
    "tetrafoil_x", "tetrafoil_y",
    "secondary_coma_x", "secondary_coma_y",
    "secondary_trefoil_x", "secondary_trefoil_y",
    "pentafoil_x", "pentafoil_y",
    "tertiary_spherical",
    "secondary_astig45_tertiary", "secondary_astig0_tertiary",
    "secondary_tetrafoil_x", "secondary_tetrafoil_y",
    "hexafoil_x", "hexafoil_y",
    "quaternary_coma_y", "quaternary_coma_x",
    "tertiary_trefoil_y", "tertiary_trefoil_x",
    "tertiary_pentafoil_y", "tertiary_pentafoil_x",
    "heptafoil_y", "heptafoil_x",
]

assert len(_NOLL_NM) == 36, "Noll table must have 36 entries"
assert len(_NOLL_NAMES) == 36, "Noll names must have 36 entries"


def _radial_polynomial(n: int, m_abs: int, rho: np.ndarray) -> np.ndarray:
    """
    Evaluate the radial Zernike polynomial R_n^m(ρ) for |m| = m_abs.

    Standard summation formula (Born & Wolf §9.2, eq. 9.2.2):

        R_n^m(ρ) = Σ_{s=0}^{(n-m)/2}  (-1)^s * (n-s)! / (s! * ((n+m)/2 - s)! * ((n-m)/2 - s)!)
                   * ρ^(n - 2s)

    Parameters
    ----------
    n     : radial degree (>= 0)
    m_abs : absolute azimuthal frequency (>= 0, must satisfy (n - m_abs) % 2 == 0)
    rho   : numpy array of normalised pupil radii in [0, 1]

    Returns
    -------
    numpy array  R_n^m(ρ)  values at each rho sample.
    """
    m = m_abs
    if (n - m) % 2 != 0:
        return np.zeros_like(rho)
    result = np.zeros_like(rho, dtype=np.float64)
    n_terms = (n - m) // 2
    for s in range(n_terms + 1):
        coeff = (
            ((-1) ** s)
            * math.factorial(n - s)
            / (
                math.factorial(s)
                * math.factorial((n + m) // 2 - s)
                * math.factorial((n - m) // 2 - s)
            )
        )
        result += coeff * rho ** (n - 2 * s)
    return result


def _zernike_basis(n: int, m: int, rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """
    Evaluate the Noll-normalised Zernike polynomial Z_n^m(ρ, θ).

    Normalisation (Noll 1976, eq. 1):
        norm = √(n+1)          for m = 0
        norm = √(2(n+1))       for m ≠ 0

    Azimuthal part:
        m > 0  →  cos(|m|·θ)
        m < 0  →  sin(|m|·θ)
        m = 0  →  1  (rotationally symmetric)

    Parameters
    ----------
    n, m  : Noll (n, m) indices.  m may be negative (sin term).
    rho   : numpy array, normalised pupil radius ∈ [0, 1].
    theta : numpy array, pupil angle ∈ [0, 2π).

    Returns
    -------
    numpy array of Z values at (rho, theta) sample points.
    """
    m_abs = abs(m)
    R = _radial_polynomial(n, m_abs, rho)
    norm = math.sqrt(n + 1) if m == 0 else math.sqrt(2.0 * (n + 1))
    if m == 0:
        az = np.ones_like(theta)
    elif m > 0:
        az = np.cos(m_abs * theta)
    else:
        az = np.sin(m_abs * theta)
    return norm * R * az


def _build_zernike_design_matrix(
    rho: np.ndarray,
    theta: np.ndarray,
    num_terms: int,
) -> np.ndarray:
    """
    Build the Zernike design matrix A of shape (N_samples, num_terms).

    Column j (0-indexed) is Z_{j+1}(ρ, θ) evaluated at all sample points.
    """
    n_samples = len(rho)
    A = np.empty((n_samples, num_terms), dtype=np.float64)
    for j in range(num_terms):
        n_deg, m_ord = _NOLL_NM[j]
        A[:, j] = _zernike_basis(n_deg, m_ord, rho, theta)
    return A


# ---------------------------------------------------------------------------
# OPL / OPD helpers (shared with coma_compute pattern)
# ---------------------------------------------------------------------------

def _surfaces_to_optical_zernike(
    surfaces: list[dict],
) -> tuple[list[OpticalSurface], list[float]]:
    """
    Convert {c, t, n, [k]} dicts to OpticalSurface objects.

    Returns (optical_surfaces, vertex_z_positions).
    First surface vertex is at z=0; subsequent surfaces at cumulative t offsets.
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


def _paraxial_image_dist_z(
    surfaces: list[dict],
    aperture_mm: float,
    n_object: float,
) -> float:
    """
    Paraxial image distance from the last surface (marginal ray h=aperture, u=0).
    Returns math.inf for afocal stacks.
    """
    h = float(aperture_mm)
    u = 0.0
    n = float(n_object)
    for s in surfaces:
        c = float(s["c"])
        t = float(s["t"])
        n_p = float(s["n"])
        u_p = _paraxial_refract(h, u, n, n_p, c)
        h = _paraxial_transfer(h, u_p, t)
        u = u_p
        n = n_p
    if abs(u) < 1e-18:
        return math.inf
    return -h / u


def _compute_opl_zernike(
    ray: Ray3D,
    optical_surfaces: list[OpticalSurface],
    n_object: float,
    img_z: float,
) -> float | None:
    """
    Trace *ray* through optical_surfaces and accumulate OPL up to image plane at img_z.

    OPL = Σ n_k * |segment_k|.  Returns OPL (mm), or None on failure (TIR / miss).
    """
    result = trace_skew_ray(ray, optical_surfaces, n_before_first=n_object)
    if result.tir_occurred:
        return None
    if len(result.ray_history) < 2:
        return None

    opl = 0.0
    n_current = n_object
    for k in range(len(result.ray_history) - 1):
        p0 = result.ray_history[k].origin_xyz
        p1 = result.ray_history[k + 1].origin_xyz
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        dz = p1[2] - p0[2]
        opl += n_current * math.sqrt(dx * dx + dy * dy + dz * dz)
        if k < len(optical_surfaces):
            n_current = optical_surfaces[k].refractive_index_after

    # Final segment from last intersection to image plane at img_z
    p_last = result.final_position_xyz
    d_last = result.final_direction_xyz
    if abs(d_last[2]) < 1e-18:
        return None
    t_img = (img_z - p_last[2]) / d_last[2]
    if t_img < 0.0:
        return None
    seg_len = math.sqrt(
        (d_last[0] * t_img) ** 2 + (d_last[1] * t_img) ** 2 + t_img ** 2
    )
    opl += n_current * seg_len
    return opl


# ---------------------------------------------------------------------------
# ZernikeReport dataclass
# ---------------------------------------------------------------------------

@dataclass
class ZernikeReport:
    """
    Zernike wavefront decomposition from finite-ray OPD tracing.

    The OPD map W(ρ, θ) is built by tracing a bundle of skew rays from
    pupil samples through the lens stack and computing OPD relative to
    the chief ray.  The OPD samples are then fitted to the first
    ``num_terms`` Noll-ordered Zernike polynomials via numpy least-squares.

    Attributes
    ----------
    coefficients : list[float]
        Fitted Zernike coefficients c_1..c_{num_terms} in Noll order (waves).
        c_1 = piston, c_4 = defocus, c_7/c_8 = coma,
        c_11 = primary spherical, c_22 = secondary spherical.
    rms_waves : float
        RMS wavefront error of the fitted wavefront (waves).
        Computed as sqrt(Σ c_j² / num_terms) excluding piston (j=1).
    pv_waves : float
        Peak-to-valley wavefront error (waves) = max(W_fit) - min(W_fit)
        evaluated over the pupil sample grid.
    strehl_estimate : float
        Maréchal approximation: exp(-(2π·RMS)²).
        Valid when RMS << 1 wave (Maréchal 1947; Born & Wolf §9.3.2 eq. 9.3.7).
        Clamped to [0, 1].
    coefficient_names : list[str]
        Human-readable names aligned with ``coefficients``.
    fit_rms_residual : float
        RMS of (OPD_measured − OPD_fitted) across all sample points (waves).
        Small values indicate the Zernike basis adequately captures the wavefront.
    n_rays_valid : int
        Number of pupil rays successfully traced.
    honest_caveat : str
        Plain-text scope and limitations.
    """

    coefficients: list[float] = field(default_factory=list)
    rms_waves: float = 0.0
    pv_waves: float = 0.0
    strehl_estimate: float = 1.0
    coefficient_names: list[str] = field(default_factory=list)
    fit_rms_residual: float = 0.0
    n_rays_valid: int = 0
    honest_caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "coefficients": self.coefficients,
            "coefficient_names": self.coefficient_names,
            "rms_waves": self.rms_waves,
            "pv_waves": self.pv_waves,
            "strehl_estimate": self.strehl_estimate,
            "fit_rms_residual": self.fit_rms_residual,
            "n_rays_valid": self.n_rays_valid,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Zernike wavefront decomposition — public API
# ---------------------------------------------------------------------------

_ZERNIKE_CAVEAT = (
    "Zernike wavefront decomposition via finite-ray OPD (Noll 1976 / Born & Wolf §9.2). "
    "OPD = OPL_ray − OPL_chief; OPL accumulated via 3-D skew-ray trace (trace_skew_ray, "
    "Born & Wolf §4.6 / Welford §5); Zernike coefficients fitted by numpy.linalg.lstsq "
    "to Noll-ordered Z_1..Z_36 (piston through 7th-order). "
    "Key mappings: Z_4=defocus, Z_5/Z_6=astigmatism, Z_7/Z_8=coma, "
    "Z_11=primary spherical, Z_12/Z_13=5th-order astig, "
    "Z_16/Z_17=secondary coma, Z_22=secondary spherical. "
    "Strehl by Maréchal approx exp(-(2π·RMS)²) — valid only when RMS≪1 wave. "
    "Monochromatic; conic surfaces only (no higher-order aspheric A4/A6 terms). "
    "Pupil sampled on a hex-polar grid; stop assumed at first surface. "
    "Higher-order content (j>36) aliases into the fit residual. "
    "Refs: Noll (1976) J. Opt. Soc. Am. 66 207; Born & Wolf (1999) §9.2; "
    "Maréchal (1947) Rev. Opt. 26 257."
)


def decompose_wavefront_zernike(
    surfaces: list[dict],
    field_height_mm: float = 0.0,
    aperture_radius_mm: float = 1.0,
    max_n: int = 8,
    num_pupil_samples: int = 128,
    n_object: float = 1.0,
    wavelength_mm: float = 550e-6,
) -> "ZernikeReport | dict":
    """
    Decompose the wavefront OPD into Zernike polynomials Z_1..Z_36 via
    finite-ray tracing through the lens stack.

    For each pupil sample (ρ_k, θ_k) a 3-D skew ray is traced from the
    entrance pupil through all surfaces to the paraxial image plane.  The
    optical path length OPL_k = Σ n_j · |seg_j| is accumulated, and the
    optical path difference OPD_k = OPL_k − OPL_chief gives the wavefront
    departure at that pupil point.  The OPD map is then fitted to the first
    36 Noll-ordered Zernike polynomials using numpy least-squares.

    Zernike index → aberration mapping (Noll 1976):
        Z_1        piston (global phase offset; excluded from RMS)
        Z_4        defocus (longitudinal focus shift)
        Z_5 / Z_6  primary astigmatism (45° / 0°)
        Z_7 / Z_8  primary coma (y / x)
        Z_11       primary spherical aberration (W040)
        Z_12/Z_13  5th-order astigmatism (secondary)
        Z_16/Z_17  secondary coma (W131 5th-order)
        Z_22       secondary spherical aberration (W060)

    Parameters
    ----------
    surfaces : list[dict]
        Sequential lens stack, same format as ``seidel_coefficients``.
        Each dict: c (mm^-1), t (mm), n (>= 1.0), optional k (conic const).
    field_height_mm : float
        Off-axis image height (mm) for which to compute the wavefront.
        0.0 = on-axis field point.  Default 0.0.
    aperture_radius_mm : float
        Entrance-pupil semi-diameter (mm).  Default 1.0.
    max_n : int
        Maximum radial order to include (unused; kept for API compatibility —
        always fits 36 terms, covering up to n=7).  Default 8.
    num_pupil_samples : int
        Number of pupil rays per ring.  Total samples = num_rings * num_per_ring
        from a hexapolar-style grid.  Minimum 16.  Default 128.
    n_object : float
        Refractive index of object space.  Default 1.0.
    wavelength_mm : float
        Reference wavelength for OPD-to-waves conversion (mm).
        Default 550 nm = 550e-6 mm.

    Returns
    -------
    ZernikeReport  on success.
    dict {ok: False, reason: ...}  on input error or afocal stack.

    References
    ----------
    Noll (1976) J. Opt. Soc. Am. 66, 207-211.
    Born & Wolf (1999) Principles of Optics, §9.2.
    Welford (1986) Aberrations of Optical Systems, §5.5.
    Maréchal (1947) Rev. Opt. Theor. Instrum. 26, 257-277.
    """
    # ---- Input validation ---------------------------------------------------
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
    if num_pupil_samples < 16:
        return _err("num_pupil_samples must be >= 16")

    ap = float(aperture_radius_mm)
    n0 = float(n_object)
    fh = float(field_height_mm)
    wl = float(wavelength_mm)

    _NUM_TERMS = 36

    # ---- Paraxial image distance --------------------------------------------
    img_dist = _paraxial_image_dist_z(surfaces, ap, n0)
    if not math.isfinite(img_dist):
        return _err(
            "afocal stack: no paraxial focus; Zernike OPD decomposition undefined"
        )

    # ---- Convert surfaces to OpticalSurface ---------------------------------
    optical_surfaces, vertex_z_list = _surfaces_to_optical_zernike(surfaces)
    last_z = vertex_z_list[-1] if vertex_z_list else 0.0
    img_z = last_z + img_dist

    # ---- Place source plane well in front of first surface ------------------
    z_start = vertex_z_list[0] - max(10.0 * ap, 1.0) if vertex_z_list else -max(10.0 * ap, 1.0)

    # ---- Chief ray (through centre of entrance pupil) -----------------------
    # Chief ray: from (0, 0, z_start) aimed at (0, fh, img_z)
    chief_dy = fh
    chief_dz = img_z - z_start
    chief_mag = math.sqrt(chief_dy ** 2 + chief_dz ** 2)
    chief_ray = Ray3D(
        origin_xyz=(0.0, 0.0, z_start),
        direction_xyz=(0.0, chief_dy / chief_mag, chief_dz / chief_mag),
        wavelength_nm=wl * 1e6,
    )
    opl_chief = _compute_opl_zernike(chief_ray, optical_surfaces, n0, img_z)
    if opl_chief is None:
        return _err(
            "Chief ray trace failed (TIR or missed surface); "
            "cannot compute Zernike OPD decomposition"
        )

    # ---- Hexapolar pupil grid: rings at rho = 0.25, 0.5, 0.75, 1.0 ---------
    # 4 rings × (num_pupil_samples // 4) azimuths per ring.
    n_rings = 4
    n_az = max(4, num_pupil_samples // n_rings)
    rho_rings = [0.25, 0.50, 0.75, 1.00]

    opd_list: list[float] = []
    rho_list: list[float] = []
    theta_list: list[float] = []
    n_valid = 0

    for rho_val in rho_rings:
        for k in range(n_az):
            theta_val = 2.0 * math.pi * k / n_az
            # Pupil ray: starts at entrance pupil with same chief-ray direction
            # but offset in (x, y) by (rho_val * ap * cos θ, rho_val * ap * sin θ)
            x_pup = ap * rho_val * math.cos(theta_val)
            y_pup = ap * rho_val * math.sin(theta_val)

            # Direction from pupil point (x_pup, y_pup, z_start) toward (0, fh, img_z)
            dx_r = -x_pup
            dy_r = fh - y_pup
            dz_r = img_z - z_start
            mag_r = math.sqrt(dx_r ** 2 + dy_r ** 2 + dz_r ** 2)
            if mag_r < 1e-18:
                continue

            pup_ray = Ray3D(
                origin_xyz=(x_pup, y_pup, z_start),
                direction_xyz=(dx_r / mag_r, dy_r / mag_r, dz_r / mag_r),
                wavelength_nm=wl * 1e6,
            )
            opl_ray = _compute_opl_zernike(pup_ray, optical_surfaces, n0, img_z)
            if opl_ray is None:
                continue

            opd_waves = (opl_ray - opl_chief) / wl
            opd_list.append(opd_waves)
            rho_list.append(rho_val)
            theta_list.append(theta_val)
            n_valid += 1

    if n_valid < _NUM_TERMS:
        return _err(
            f"Too few valid pupil rays ({n_valid}) for a {_NUM_TERMS}-term Zernike fit. "
            f"Increase num_pupil_samples or check for TIR/missed surfaces."
        )

    # ---- Least-squares Zernike fit ------------------------------------------
    rho_arr = np.array(rho_list, dtype=np.float64)
    theta_arr = np.array(theta_list, dtype=np.float64)
    opd_arr = np.array(opd_list, dtype=np.float64)

    A = _build_zernike_design_matrix(rho_arr, theta_arr, _NUM_TERMS)
    coeffs, _residuals, _rank, _sv = np.linalg.lstsq(A, opd_arr, rcond=None)

    # ---- Fitted wavefront: RMS and P-V ---------------------------------------
    w_fitted = A @ coeffs
    residual = opd_arr - w_fitted
    fit_rms_residual = float(np.sqrt(np.mean(residual ** 2)))

    # RMS of the wavefront = sqrt(Σ c_j² for j >= 2) excluding piston (j=1)
    # (Noll 1976: for orthonormal basis, <Z_j²> = 1, so RMS² = Σ c_j² / N_pupils
    # but on the unit disk: Var(W) = Σ_{j>=2} c_j²)
    rms_waves = float(np.sqrt(np.sum(coeffs[1:] ** 2)))

    # Peak-to-valley over the pupil sample grid
    pv_waves = float(np.max(w_fitted) - np.min(w_fitted))

    # Strehl by Maréchal approximation: S = exp(-(2π·σ)²)
    # where σ = RMS wavefront in waves (Maréchal 1947; Born & Wolf §9.3.2)
    strehl_raw = math.exp(-(2.0 * math.pi * rms_waves) ** 2)
    strehl_estimate = max(0.0, min(1.0, strehl_raw))

    return ZernikeReport(
        coefficients=[float(c) for c in coeffs],
        rms_waves=rms_waves,
        pv_waves=pv_waves,
        strehl_estimate=strehl_estimate,
        coefficient_names=_NOLL_NAMES[:_NUM_TERMS],
        fit_rms_residual=fit_rms_residual,
        n_rays_valid=n_valid,
        honest_caveat=_ZERNIKE_CAVEAT,
    )
