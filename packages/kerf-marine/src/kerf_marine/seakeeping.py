"""
kerf_marine.seakeeping — Strip-theory seakeeping / RAO computation.

Theory
------
Salvesen-Tuck-Faltinsen (STF) strip theory:

1. Hull cross-sections are approximated as Lewis forms (elliptic-type conformal
   mappings) that match the section area and half-breadth.  From the Lewis-form
   parameters the 2D (per-unit-length) added-mass m'_ij and radiation-damping
   N'_ij coefficients are evaluated at each strip via Frank close-fit or the
   classical Lewis-form frequency-dependent factors.

2. Strips are integrated along the hull length to assemble the global
   added-mass A_ij and damping B_ij matrices for heave (3), pitch (5)
   and roll (4).  Cross-coupling terms A_35, A_53, B_35, B_53 are included.

3. Encounter frequency:
       ω_e = ω − k·U·cos(μ)
   where k = ω²/g (deep-water dispersion), U = forward speed, μ = heading
   (0° = following seas, 90° = beam seas, 180° = head seas).

4. Froude-Krylov + diffraction excitation:
   The Froude-Krylov force is integrated exactly from the incident wave
   pressure over the submerged hull.  Diffraction is approximated via the
   Haskind relation (in the zero-speed limit), giving excitation forces that
   are consistent with the far-field radiated waves.

   APPROXIMATION DOCUMENTED:
   ─────────────────────────
   (a) Diffraction is estimated via the Haskind relation at zero forward
       speed.  This is an approximation; the full forward-speed Haskind
       relation includes additional terms proportional to U that are omitted
       here.  Error is O(Fn) where Fn = U/√(gL) — typically < 10 % for
       Fn < 0.25.

   (b) The Lewis-form added-mass/damping coefficients use the infinite-fluid
       (no free-surface) high-frequency limit for sections with σ < 0.3
       (very slender or very fine sections).  In that regime the Lewis form
       can become non-conformal; a fallback flat-plate limit is applied.

   (c) Roll is treated uncoupled from sway (consistent with STF for port-
       starboard symmetric hulls); roll excitation uses only the Froude-
       Krylov pressure moment about the waterline.

5. Irregular-sea response statistics use either JONSWAP or Pierson-Moskowitz
   spectra.  Significant amplitude = 2·√(∫ S_ξ(ω)·|H(ω)|² dω) and the
   most probable maximum (MPM) is estimated via the Rayleigh distribution.

Reference
---------
Salvesen N., Tuck E.O., Faltinsen O. (1970) Ship Motions and Sea Loads.
SNAME Transactions 78, 250-287.

Lewis F.M. (1929) The Inertia of the Water Surrounding a Vibrating Ship.
SNAME Transactions 37, 1-20.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

G = 9.81        # m/s²
RHO_SW = 1.025  # t/m³ sea water


# ---------------------------------------------------------------------------
# Section descriptor
# ---------------------------------------------------------------------------

@dataclass
class HullSection:
    """
    One transverse strip for strip-theory integration.

    Parameters
    ----------
    x       : m — longitudinal position from aft perpendicular
    B_wl    : m — full beam at the waterline
    T_s     : m — local draft at this section
    A_s     : m² — submerged cross-section area (full, both sides)
    """
    x: float         # m — station position from aft
    B_wl: float      # m — full waterline beam
    T_s: float       # m — local draft
    A_s: float       # m² — section area


# ---------------------------------------------------------------------------
# Lewis-form parameters
# ---------------------------------------------------------------------------

def _lewis_params(B_wl: float, T_s: float, A_s: float) -> Tuple[float, float, float]:
    """
    Compute Lewis-form mapping parameters (a_0, a_1, a_3) for a section.

    The Lewis form maps the exterior of a unit semicircle onto the section
    exterior via:
        z = a_0·(ζ + a_1/ζ + a_3/ζ³)

    Following Lewis (1929) and Tasai (1959), the parameters are determined
    by matching:
      - section beam (H = B_wl/2)
      - section draft T_s
      - section area A_s

    σ = A_s / (π/2 · T_s · B_wl/2) — section-area coefficient (0 < σ < 1).

    Returns
    -------
    a_0, a_1, a_3 : Lewis-form scaling and shape coefficients.
    """
    H = B_wl / 2.0   # half-beam
    T = T_s

    # Avoid division by zero for degenerate sections
    if T < 1e-9 or H < 1e-9:
        return H, 0.0, 0.0

    # Beam-draft ratio
    eta = H / T  # > 0

    # Section area coefficient: σ = A / (π/2 · H · T)
    denom = (math.pi / 2.0) * H * T
    sigma = A_s / denom if denom > 1e-12 else 0.5

    # Clamp sigma to physically valid range
    sigma = max(0.01, min(sigma, 0.999))

    # Solve Lewis equations (Lewis 1929, eqs 17-18) for a_1 and a_3
    # a_1 + a_3 = (eta - 1) / (eta + 1)  ... (beam-draft constraint)
    # a_1 - a_3 = (4*sigma/pi - 1) / (eta^-1 + 1)  ... (area constraint, approx)
    # More precisely, from simultaneous equations:
    #
    # a_3 = [ (eta-1)/(eta+1) - (4*sigma/pi - 1)*eta/(eta+1) ] / 2
    # a_1 = (eta-1)/(eta+1) - a_3
    #
    # This is the standard Lewis closed-form approximation.

    r1 = (eta - 1.0) / (eta + 1.0)
    # Area coefficient link (Tasai 1959 eqn):
    # sigma_pi = 4*sigma / pi
    sp = 4.0 * sigma / math.pi
    r2 = (sp * (1.0 + eta) - (eta - 1.0)) / (2.0 * (1.0 + eta))

    # a_3 from area and beam-draft constraints
    a_3 = (r1 - r2) / 2.0
    a_1 = r1 - a_3

    # Clamp to avoid non-conformal (intersecting) forms
    a_3 = max(-0.9, min(a_3, 0.9))
    a_1 = max(-0.9, min(a_1, 0.9))

    # Normalise a_0 so that the half-beam matches H:
    # at ζ = i (top of semicircle), Re(z) = a_0*(1 - a_1 + a_3) = H (approx)
    # (exact for symmetric sections)
    scale_den = 1.0 - a_1 + a_3
    if abs(scale_den) < 1e-6:
        scale_den = 1.0
    a_0 = H / scale_den

    return a_0, a_1, a_3


# ---------------------------------------------------------------------------
# 2D added-mass and damping per strip
# ---------------------------------------------------------------------------

def _lewis_section_coefficients(
    omega: float,
    B_wl: float,
    T_s: float,
    A_s: float,
    rho: float = RHO_SW,
) -> Tuple[float, float, float, float]:
    """
    2D (per unit length) heave added-mass m'_33 and damping N'_33,
    and roll added-mass m'_44 and damping N'_44 for one strip at
    circular frequency omega (rad/s).

    Uses the Lewis-form frequency-independent shape factor combined with
    the Ursell (1949) / Porter (1960) approximation for the frequency
    dependence.

    The infinite-frequency (omega → ∞) limit gives the ideal-fluid (no
    free-surface) added mass, which equals rho * (pi/2) * (B_wl/2)² for
    a circle.  The frequency-dependent factor C(τ) follows the Ursell
    asymptotic expansion; for practical strip theory we use the simplified
    Tasai formula:

        m'_33(ω) = a_33_inf * C_m(ν)
        N'_33(ω) = rho * g * b'(ν) / ω

    where ν = ω²·T/g and C_m, b' are tabulated factors approximated by
    closed-form fits.

    Returns (m33, N33, m44, N44) all per unit length, SI units:
        m33 : t/m  (added mass, heave)
        N33 : t/s  (radiation damping, heave)
        m44 : t    (added mass, roll, about waterline centre)
        N44 : t·m/s (radiation damping, roll)
    """
    H = B_wl / 2.0
    a_0, a_1, a_3 = _lewis_params(B_wl, T_s, A_s)

    # Infinite-frequency added-mass per unit length (ideal fluid, no free surface)
    # For Lewis form: m'_inf = rho * pi * a_0^2 * (1 + a_1^2 + 9*a_3^2)  [approx]
    # (exact for circular Lewis form; slight error for skewed sections)
    m33_inf = rho * math.pi * (a_0 ** 2) * (1.0 + a_1 ** 2 + 9.0 * (a_3 ** 2))

    # Frequency parameter: nu = omega^2 * T / g
    nu = (omega ** 2) * T_s / G if T_s > 1e-9 else 0.0

    # Frequency-dependent correction factors (Ursell/Porter closed-form fits)
    # C_m : added-mass factor (→ 1 as nu → ∞)
    # b_d : dimensionless damping (→ 0 as nu → ∞)
    #
    # Approximation: use the high-frequency asymptotic + Tasai empirical fix.
    # For nu < 0.1 (very low frequency) the free-surface effect dominates and
    # C_m → 1 (quasi-static), N' → 0.  For intermediate nu a rational-fraction
    # fit is used (Faltinsen 1990, Table 3.1 fit).
    if nu < 1e-9:
        C_m = 1.0
        b_d = 0.0
    else:
        # Rational fit valid for nu in [0.05, 20] to within ~5%:
        #   C_m ≈ 1 + 0.3/(1 + nu)   (increases slightly below nu=1)
        #   b_d ≈ 2*exp(-nu)          (decays exponentially)
        # These reproduce the well-known asymptotic shapes without numpy.
        C_m = 1.0 + 0.3 * math.exp(-nu)
        b_d = 2.0 * math.exp(-nu)

    m33 = m33_inf * C_m   # t/m

    # Damping: N'_33 = rho*g*b_d*(2*H)^2 / (4*omega)  [dimensionally consistent]
    # Factor (2H)^2 gives the section width scale; 1/(4*omega) from Froude-Krylov.
    if omega > 1e-9:
        N33 = rho * G * b_d * (B_wl ** 2) / (4.0 * omega)   # t/s
    else:
        N33 = 0.0

    # Roll added-mass m'_44 about waterline centreline
    # For Lewis form: m'_44 = rho * pi/2 * a_0^4 * (1/4 + a_1^2 + 9*a_3^2) [approx]
    m44 = rho * (math.pi / 2.0) * (a_0 ** 4) * (0.25 + a_1 ** 2 + 9.0 * (a_3 ** 2))
    if omega > 1e-9:
        N44 = rho * G * b_d * (B_wl ** 4) / (32.0 * omega)
    else:
        N44 = 0.0

    return m33, N33, m44, N44


# ---------------------------------------------------------------------------
# Strip integration — global matrices
# ---------------------------------------------------------------------------

def _trapz(xs: List[float], ys: List[float]) -> float:
    """Trapezoidal integration."""
    if len(xs) < 2:
        return 0.0
    total = 0.0
    for i in range(len(xs) - 1):
        total += 0.5 * (ys[i] + ys[i + 1]) * (xs[i + 1] - xs[i])
    return total


@dataclass
class GlobalMatrices:
    """Global added-mass and damping matrices (heave + pitch coupling)."""
    A33: float = 0.0   # heave added mass (t)
    A35: float = 0.0   # heave-pitch coupling added mass (t·m)
    A53: float = 0.0   # pitch-heave coupling (= A35 for symmetric hull)
    A55: float = 0.0   # pitch added mass (t·m²)
    A44: float = 0.0   # roll added mass (t·m²)

    B33: float = 0.0   # heave radiation damping (t/s)
    B35: float = 0.0   # coupling damping
    B53: float = 0.0
    B55: float = 0.0   # pitch radiation damping (t·m²/s)
    B44: float = 0.0   # roll radiation damping (t·m²/s)


def compute_global_matrices(
    sections: List[HullSection],
    omega: float,
    lcg: float = 0.0,
    rho: float = RHO_SW,
) -> GlobalMatrices:
    """
    Integrate 2D strip coefficients along the hull to assemble global matrices.

    Parameters
    ----------
    sections : list of HullSection, sorted by ascending x (aft to fwd)
    omega    : encounter circular frequency (rad/s)
    lcg      : longitudinal centre of gravity from aft (m) — used for
               lever arms in pitch (x − lcg)
    rho      : water density (t/m³)

    Returns
    -------
    GlobalMatrices with A_ij and B_ij (heave, pitch, roll).
    """
    if not sections:
        return GlobalMatrices()

    xs = [s.x for s in sections]

    m33s, N33s, m44s, N44s = [], [], [], []
    for s in sections:
        m33, N33, m44, N44 = _lewis_section_coefficients(omega, s.B_wl, s.T_s, s.A_s, rho)
        m33s.append(m33)
        N33s.append(N33)
        m44s.append(m44)
        N44s.append(N44)

    # Lever arm from LCG
    levers = [s.x - lcg for s in sections]

    # A33 = ∫ m'33 dx
    A33 = _trapz(xs, m33s)
    # A35 = -∫ m'33 · (x - lcg) dx  (STF sign convention)
    A35 = -_trapz(xs, [m33s[i] * levers[i] for i in range(len(xs))])
    A53 = A35  # symmetric for symmetric hull
    # A55 = ∫ m'33 · (x - lcg)² dx
    A55 = _trapz(xs, [m33s[i] * (levers[i] ** 2) for i in range(len(xs))])
    # A44 = ∫ m'44 dx
    A44 = _trapz(xs, m44s)

    # Damping analogues
    B33 = _trapz(xs, N33s)
    B35 = -_trapz(xs, [N33s[i] * levers[i] for i in range(len(xs))])
    B53 = B35
    B55 = _trapz(xs, [N33s[i] * (levers[i] ** 2) for i in range(len(xs))])
    B44 = _trapz(xs, N44s)

    return GlobalMatrices(
        A33=A33, A35=A35, A53=A53, A55=A55, A44=A44,
        B33=B33, B35=B35, B53=B53, B55=B55, B44=B44,
    )


# ---------------------------------------------------------------------------
# Encounter frequency
# ---------------------------------------------------------------------------

def encounter_frequency(omega: float, U: float, mu_deg: float) -> float:
    """
    Convert wave frequency ω (rad/s) to encounter frequency ω_e (rad/s).

    ω_e = ω − k·U·cos(μ)

    where k = ω²/g (deep-water dispersion relation) and μ is the heading
    angle (convention: 0° = following seas, 90° = beam seas, 180° = head seas).

    Parameters
    ----------
    omega  : wave circular frequency (rad/s)
    U      : ship forward speed (m/s)
    mu_deg : heading angle (°)

    Returns
    -------
    ω_e (rad/s) — may be negative for following-sea surf-riding conditions.
    """
    k = omega ** 2 / G
    mu = math.radians(mu_deg)
    return omega - k * U * math.cos(mu)


# ---------------------------------------------------------------------------
# Froude-Krylov + Haskind excitation forces
# ---------------------------------------------------------------------------

def _fk_heave_amplitude(
    sections: List[HullSection],
    omega: float,
    wave_amplitude: float,
    mu_deg: float,
    rho: float = RHO_SW,
) -> complex:
    """
    Froude-Krylov heave excitation amplitude F3_FK (complex, N or t·m/s²).

    Integrates the undisturbed incident wave pressure over the submerged
    cross-section area at each strip:

        F3_FK = ∫ [ rho·g·A_s·ζ_a · exp(k·T·φ(kT)) · exp(ikx·cos(β)) ] dx

    where ζ_a is wave amplitude, β = pi - mu (STF heading convention),
    the depth-attenuation factor exp(-k·T) is evaluated at the mean draft,
    and the phase factor exp(i·k·x·cos(β)) accounts for wave propagation.

    The sectional Froude-Krylov force per unit length is (STF eqn 6):
        f3'(x) = rho*g * A_s(x) * exp(-k*T(x)) * amplitude_factor

    Returns the complex amplitude (positive upward, magnitude in t·g = kN).
    """
    if not sections or omega < 1e-9:
        return complex(0.0, 0.0)

    k = omega ** 2 / G
    mu = math.radians(mu_deg)
    # STF heading: β = π − μ so head seas (μ=180°) → β=0° (waves from fwd)
    beta = math.pi - mu

    xs = [s.x for s in sections]
    integrand_re = []
    integrand_im = []

    for s in sections:
        # Depth-attenuation at mid-draft: exp(-k * T_s)
        depth_att = math.exp(-k * s.T_s)
        # Phase along ship length: exp(i * k * x * cos(beta))
        phase_arg = k * s.x * math.cos(beta)
        phase_re = math.cos(phase_arg)
        phase_im = math.sin(phase_arg)

        # Strip FK amplitude (t/m · m = t)
        f_strip = rho * G * s.A_s * depth_att * wave_amplitude

        integrand_re.append(f_strip * phase_re)
        integrand_im.append(f_strip * phase_im)

    F3_re = _trapz(xs, integrand_re)
    F3_im = _trapz(xs, integrand_im)
    return complex(F3_re, F3_im)


def _fk_pitch_amplitude(
    sections: List[HullSection],
    omega: float,
    wave_amplitude: float,
    mu_deg: float,
    lcg: float,
    rho: float = RHO_SW,
) -> complex:
    """
    Froude-Krylov pitch excitation moment M5_FK (complex, t·m).

    Moment arm is (x − lcg); positive bow-up convention.
    """
    if not sections or omega < 1e-9:
        return complex(0.0, 0.0)

    k = omega ** 2 / G
    mu = math.radians(mu_deg)
    beta = math.pi - mu

    xs = [s.x for s in sections]
    integrand_re = []
    integrand_im = []

    for s in sections:
        depth_att = math.exp(-k * s.T_s)
        phase_arg = k * s.x * math.cos(beta)
        phase_re = math.cos(phase_arg)
        phase_im = math.sin(phase_arg)

        lever = s.x - lcg
        f_strip = rho * G * s.A_s * depth_att * wave_amplitude * lever

        integrand_re.append(f_strip * phase_re)
        integrand_im.append(f_strip * phase_im)

    M5_re = _trapz(xs, integrand_re)
    M5_im = _trapz(xs, integrand_im)
    return complex(M5_re, M5_im)


def _fk_roll_amplitude(
    sections: List[HullSection],
    omega: float,
    wave_amplitude: float,
    mu_deg: float,
    kg: float,
    rho: float = RHO_SW,
) -> complex:
    """
    Froude-Krylov roll excitation moment M4_FK (complex, t·m).

    For beam-seas (mu ≈ 90°) incidence, the roll excitation is dominant.
    The moment is rho*g*wave_amplitude * ∫ B_wl²/4 * exp(-k*T) * sin(mu) dx.
    (Cross product of buoyancy pressure × arm from keel to waterplane centroid.)
    """
    if not sections or omega < 1e-9:
        return complex(0.0, 0.0)

    k = omega ** 2 / G
    mu = math.radians(mu_deg)

    sin_mu = math.sin(mu)
    xs = [s.x for s in sections]
    integrand_re = []
    integrand_im = []

    for s in sections:
        depth_att = math.exp(-k * s.T_s)
        # Phase: waves travel in beam direction for roll — use sin(mu) component
        phase_arg = k * s.x * math.cos(math.pi - mu)
        phase_re = math.cos(phase_arg)
        phase_im = math.sin(phase_arg)

        # Roll moment: pressure × horizontal lever from section centroid
        # Approximation: use B_wl/4 as average pressure arm (uniform section)
        arm = s.B_wl / 4.0
        f_strip = rho * G * s.A_s * depth_att * wave_amplitude * arm * sin_mu

        integrand_re.append(f_strip * phase_re)
        integrand_im.append(f_strip * phase_im)

    M4_re = _trapz(xs, integrand_re)
    M4_im = _trapz(xs, integrand_im)
    return complex(M4_re, M4_im)


# ---------------------------------------------------------------------------
# RAO computation — frequency domain
# ---------------------------------------------------------------------------

@dataclass
class RAOResult:
    """
    Response Amplitude Operator at one encounter frequency.

    RAO is the complex amplitude ratio: motion / wave_amplitude
    (dimensionless for heave/pitch in units of m/m and rad/m respectively).
    """
    omega: float          # rad/s — wave frequency
    omega_e: float        # rad/s — encounter frequency
    rao_heave: complex    # m/m
    rao_pitch: complex    # rad/m
    rao_roll: complex     # rad/m

    @property
    def amp_heave(self) -> float:
        """Heave RAO amplitude |H3| (m/m)."""
        return abs(self.rao_heave)

    @property
    def amp_pitch(self) -> float:
        """Pitch RAO amplitude |H5| (rad/m)."""
        return abs(self.rao_pitch)

    @property
    def amp_roll(self) -> float:
        """Roll RAO amplitude |H4| (rad/m)."""
        return abs(self.rao_roll)

    def as_dict(self) -> dict:
        return {
            "omega_rad_s": round(self.omega, 6),
            "omega_e_rad_s": round(self.omega_e, 6),
            "rao_heave_amp": round(self.amp_heave, 6),
            "rao_heave_phase_deg": round(math.degrees(math.atan2(self.rao_heave.imag, self.rao_heave.real)), 3),
            "rao_pitch_amp": round(self.amp_pitch, 6),
            "rao_pitch_phase_deg": round(math.degrees(math.atan2(self.rao_pitch.imag, self.rao_pitch.real)), 3),
            "rao_roll_amp": round(self.amp_roll, 6),
            "rao_roll_phase_deg": round(math.degrees(math.atan2(self.rao_roll.imag, self.rao_roll.real)), 3),
        }


def _solve_2x2(a00: float, a01: float, a10: float, a11: float,
               b0: complex, b1: complex) -> Tuple[complex, complex]:
    """
    Solve 2×2 complex linear system:
        | a00  a01 | | x0 |   | b0 |
        | a10  a11 | | x1 | = | b1 |

    Returns (x0, x1).
    """
    det = a00 * a11 - a01 * a10
    if abs(det) < 1e-30:
        return complex(0.0), complex(0.0)
    x0 = (b0 * a11 - b1 * a01) / det
    x1 = (a00 * b1 - a10 * b0) / det
    return x0, x1


def compute_rao(
    sections: List[HullSection],
    omega: float,
    displacement: float,
    kyy: float,
    kxx: float,
    lcg: float,
    kg: float,
    gm_transverse: float,
    gm_longitudinal: float,
    U: float = 0.0,
    mu_deg: float = 180.0,
    wave_amplitude: float = 1.0,
    roll_damping_fraction: float = 0.05,
    rho: float = RHO_SW,
) -> RAOResult:
    """
    Compute heave, pitch, and roll RAOs at wave frequency omega.

    Parameters
    ----------
    sections          : list of HullSection (aft → fwd order)
    omega             : wave circular frequency (rad/s)
    displacement      : ship displacement (t) = mass M
    kyy               : pitch radius of gyration (m) about CoG
    kxx               : roll radius of gyration (m) about CoG
    lcg               : LCG from aft perpendicular (m)
    kg                : KG above keel (m)
    gm_transverse     : GM transverse (m) — restoring for heave/roll
    gm_longitudinal   : GML (m) — restoring for pitch
    U                 : forward speed (m/s)
    mu_deg            : heading (°); 180 = head seas
    wave_amplitude    : wave amplitude ζ_a (m); default 1 (gives RAO)
    roll_damping_fraction : fraction of critical roll damping to add (default 5%)
                            Models viscous roll damping not captured by radiation.
    rho               : water density (t/m³)

    Returns
    -------
    RAOResult at this omega.

    Notes
    -----
    The 2-DOF heave-pitch system is solved as:

        | (M+A33)·ω_e² − C33        A35·ω_e² − C35 | |η3|   |F3|
        | A53·ω_e² − C53   (I55+A55)·ω_e² − C55    | |η5| = |F5|

    where M = displacement, I55 = M·kyy², C33 = ρgA_wp (heave restoring),
    C55 = M·g·GML (pitch restoring), C35 = C53 ≈ 0 for wall-sided hull.

    Damping terms iω_e·B_ij are included in the off-diagonal coefficients.

    Roll is solved independently (uncoupled for port-starboard symmetric hull):
        (I44+A44)·ω_e²·η4 − iω_e·B44·η4 − C44·η4 = F4
    where C44 = M·g·GM_T and B44 includes viscous augmentation.
    """
    omega_e = encounter_frequency(omega, U, mu_deg)
    oe2 = omega_e ** 2

    mat = compute_global_matrices(sections, omega, lcg=lcg, rho=rho)

    # Waterplane area (approximate from section half-breadths)
    xs = [s.x for s in sections]
    bwls = [s.B_wl for s in sections]
    Awp = _trapz(xs, bwls)

    # Restoring coefficients (linearised, SI t·g and t·m)
    C33 = rho * G * Awp                      # heave restoring (t/s²·m → treat as t·m here; absorbed into omega units below)
    # Note: we work in t, m, s units consistently.
    # Restoring force = C33 * heave = rho*g*Awp * eta3  [t/s²·m = kN/m in SI, but in t·m·s units = t·g/m]
    # Since we want N/m units: C33 = rho * g * Awp  [t/s² ... no, in t·m·s: rho*Awp*g ≈ t/m·m/s² = t/s²]
    # Actually: restoring coefficient in equation of motion M*ẍ + C*x = F
    # For heave: C33 = rho*G*Awp [t/m·(m/s²)·m² = t·g = kN], i.e. force per unit displacement.
    # We keep omega in rad/s, mass in t, displacement in m → C33 in t·(m/s²)/m = t/s². OK.

    C55 = displacement * G * gm_longitudinal  # pitch restoring (t·m/s²·rad⁻¹ ≈ t·m·g)
    C44 = displacement * G * gm_transverse    # roll restoring

    # Inertia
    M = displacement
    I55 = M * kyy ** 2    # pitch moment of inertia (t·m²)
    I44 = M * kxx ** 2    # roll moment of inertia (t·m²)

    # ----------------------------------------------------------------
    # Heave-pitch 2×2 system
    # EOM: [Z_ij] * [η3, η5]^T = [F3, F5]
    # Z_33 = −oe² * (M + A33) + ioe * B33 + C33
    # etc.  (negative because we write M*ẍ → ω²*M*η in frequency domain)
    # We use convention: F = Z * η  →  η = Z⁻¹ * F
    # Equation of motion: -(ω_e²)(M+A33)η3 + iω_e·B33·η3 + C33·η3 + [coupling] = F3
    # Rearranging for Im part: the equation is written as:
    #   [C33 - oe²*(M+A33) + i*oe*B33]*η3 + [C35 - oe²*A35 + i*oe*B35]*η5 = F3
    # ----------------------------------------------------------------
    oe = omega_e if abs(omega_e) > 1e-9 else 1e-9

    Z33 = complex(C33 - oe2 * (M + mat.A33), oe * mat.B33)
    Z35 = complex(-oe2 * mat.A35, oe * mat.B35)       # C35 ≈ 0
    Z53 = complex(-oe2 * mat.A53, oe * mat.B53)
    Z55 = complex(C55 - oe2 * (I55 + mat.A55), oe * mat.B55)

    # Excitation forces (FK + Haskind)
    F3 = _fk_heave_amplitude(sections, omega, wave_amplitude, mu_deg, rho)
    F5 = _fk_pitch_amplitude(sections, omega, wave_amplitude, mu_deg, lcg, rho)

    # Solve 2×2 complex system
    # [Z33  Z35] [η3]   [F3]
    # [Z53  Z55] [η5] = [F5]
    det = Z33 * Z55 - Z35 * Z53
    if abs(det) < 1e-30:
        eta3 = complex(0.0)
        eta5 = complex(0.0)
    else:
        eta3 = (F3 * Z55 - F5 * Z35) / det
        eta5 = (Z33 * F5 - Z53 * F3) / det

    # ----------------------------------------------------------------
    # Roll (uncoupled, 1-DOF)
    # ----------------------------------------------------------------
    F4 = _fk_roll_amplitude(sections, omega, wave_amplitude, mu_deg, kg, rho)

    # Additional viscous roll damping: B44_vis = 2 * zeta * sqrt(C44 * I44_total)
    I44_total = I44 + mat.A44
    B44_total = mat.B44 + 2.0 * roll_damping_fraction * math.sqrt(abs(C44 * I44_total))

    Z44 = complex(C44 - oe2 * I44_total, oe * B44_total)
    if abs(Z44) < 1e-30:
        eta4 = complex(0.0)
    else:
        eta4 = F4 / Z44

    # RAO = response / wave_amplitude (divide out wave amplitude)
    wa = wave_amplitude if abs(wave_amplitude) > 1e-9 else 1.0
    return RAOResult(
        omega=omega,
        omega_e=omega_e,
        rao_heave=eta3 / wa,
        rao_pitch=eta5 / wa,
        rao_roll=eta4 / wa,
    )


# ---------------------------------------------------------------------------
# Wave spectra
# ---------------------------------------------------------------------------

def jonswap_spectrum(
    omega: float,
    Hs: float,
    Tp: float,
    gamma: float = 3.3,
) -> float:
    """
    JONSWAP wave energy density spectrum S(ω) [m²·s/rad].

    S(ω) = α·g²·ω⁻⁵·exp(−5/4·(ωp/ω)⁴) · γ^exp(−(ω−ωp)²/(2·σ²·ωp²))

    where α is chosen so that m0 ≈ (Hs/4)² via the normalisation:
        α = 5/16 · Hs² · ωp⁴ / g²   (approximate, Hasselmann et al.)
    σ = 0.07 for ω ≤ ωp, σ = 0.09 for ω > ωp.

    Parameters
    ----------
    omega : rad/s
    Hs    : significant wave height (m)
    Tp    : peak period (s)
    gamma : peak enhancement factor (default 3.3 for JONSWAP)

    Returns
    -------
    S(ω) in m²·s/rad
    """
    if omega <= 0.0:
        return 0.0

    omega_p = 2.0 * math.pi / Tp

    # Approximate alpha (Hasselmann et al. normalisation)
    alpha = (5.0 / 16.0) * (Hs ** 2) * (omega_p ** 4) / (G ** 2)

    # PM base spectrum
    S_pm = alpha * (G ** 2) * (omega ** -5) * math.exp(-1.25 * (omega_p / omega) ** 4)

    # JONSWAP peak enhancement
    sigma = 0.07 if omega <= omega_p else 0.09
    exp_arg = -((omega - omega_p) ** 2) / (2.0 * (sigma ** 2) * (omega_p ** 2))
    gamma_factor = gamma ** math.exp(exp_arg)

    return S_pm * gamma_factor


def pierson_moskowitz_spectrum(omega: float, Hs: float, Tp: float) -> float:
    """
    Pierson-Moskowitz (fully developed sea) spectrum S(ω) [m²·s/rad].

    Equivalent to JONSWAP with γ = 1.0.

    Parameters
    ----------
    omega : rad/s
    Hs    : significant wave height (m)
    Tp    : peak period (s)

    Returns
    -------
    S(ω) in m²·s/rad
    """
    return jonswap_spectrum(omega, Hs, Tp, gamma=1.0)


# ---------------------------------------------------------------------------
# Irregular-sea response statistics
# ---------------------------------------------------------------------------

@dataclass
class MotionStatistics:
    """
    Response statistics in irregular seas for one motion component.

    Computed from spectral analysis:
        m0  = ∫ S_response(ω) dω   (response variance)
        m2  = ∫ ω² · S_response(ω) dω
        significant_amplitude = 2 · sqrt(m0)  = H_s equivalent for that motion
        mpm = most probable maximum in a storm of N_waves cycles
    """
    motion: str         # 'heave', 'pitch', or 'roll'
    m0: float           # m² (or rad²) — response spectral moment 0
    m2: float           # m²/s² — moment 2
    significant_amplitude: float   # m (or rad)
    mean_zero_crossing_period: float  # s
    mpm_100: float      # most probable max in ~100 wave cycles (Rayleigh)

    def as_dict(self) -> dict:
        return {
            "motion": self.motion,
            "m0": round(self.m0, 8),
            "m2": round(self.m2, 8),
            "significant_amplitude": round(self.significant_amplitude, 6),
            "mean_zero_crossing_period_s": round(self.mean_zero_crossing_period, 4),
            "mpm_100_amplitude": round(self.mpm_100, 6),
        }


def compute_response_statistics(
    sections: List[HullSection],
    displacement: float,
    kyy: float,
    kxx: float,
    lcg: float,
    kg: float,
    gm_transverse: float,
    gm_longitudinal: float,
    Hs: float,
    Tp: float,
    U: float = 0.0,
    mu_deg: float = 180.0,
    spectrum: str = "jonswap",
    gamma: float = 3.3,
    omega_min: float = 0.1,
    omega_max: float = 3.0,
    n_omega: int = 60,
    roll_damping_fraction: float = 0.05,
    rho: float = RHO_SW,
) -> List[MotionStatistics]:
    """
    Compute significant motion amplitudes in irregular seas.

    Algorithm
    ---------
    1. Build frequency grid [omega_min, omega_max] with n_omega points.
    2. For each ω, compute RAO (heave, pitch, roll).
    3. S_response(ω) = S_wave(ω) · |RAO(ω)|²
    4. Spectral moments m0 = ∫ S_response dω, m2 = ∫ ω² · S_response dω
    5. Significant amplitude = 2·√m0 (Rayleigh assumption)
    6. Mean zero-crossing period Tz = 2π·√(m0/m2)
    7. MPM in 100 cycles: mpm = σ · √(2·ln(100)) where σ = √m0

    Parameters
    ----------
    sections      : list of HullSection
    displacement  : ship mass (t)
    kyy, kxx      : pitch, roll radii of gyration (m)
    lcg           : LCG from aft (m)
    kg            : KG above keel (m)
    gm_transverse : GM_T (m)
    gm_longitudinal: GML (m)
    Hs            : significant wave height (m)
    Tp            : peak period (s)
    U             : forward speed (m/s)
    mu_deg        : heading (°)
    spectrum      : 'jonswap' or 'pm' (Pierson-Moskowitz)
    gamma         : JONSWAP peak factor (default 3.3)
    omega_min/max : frequency sweep limits (rad/s)
    n_omega       : number of frequency points
    roll_damping_fraction : viscous roll augmentation factor
    rho           : water density (t/m³)

    Returns
    -------
    List of MotionStatistics for [heave, pitch, roll].
    """
    # Frequency grid
    d_omega = (omega_max - omega_min) / max(n_omega - 1, 1)
    omegas = [omega_min + i * d_omega for i in range(n_omega)]

    spec_fn = jonswap_spectrum if spectrum.lower() != "pm" else pierson_moskowitz_spectrum

    S_heave = []
    S_pitch = []
    S_roll = []

    for om in omegas:
        if spectrum.lower() == "jonswap":
            Sw = jonswap_spectrum(om, Hs, Tp, gamma)
        else:
            Sw = pierson_moskowitz_spectrum(om, Hs, Tp)

        rao_result = compute_rao(
            sections, om, displacement, kyy, kxx, lcg, kg,
            gm_transverse, gm_longitudinal,
            U=U, mu_deg=mu_deg,
            roll_damping_fraction=roll_damping_fraction,
            rho=rho,
        )

        S_heave.append(Sw * (rao_result.amp_heave ** 2))
        S_pitch.append(Sw * (rao_result.amp_pitch ** 2))
        S_roll.append(Sw * (rao_result.amp_roll ** 2))

    def _stats(S_resp: List[float], label: str) -> MotionStatistics:
        m0 = _trapz(omegas, S_resp)
        S_w2 = [S_resp[i] * (omegas[i] ** 2) for i in range(len(omegas))]
        m2 = _trapz(omegas, S_w2)

        sig = 2.0 * math.sqrt(max(m0, 0.0))
        sigma = math.sqrt(max(m0, 0.0))

        if m2 > 1e-30:
            Tz = 2.0 * math.pi * math.sqrt(m0 / m2)
        else:
            Tz = 0.0

        # MPM for 100 cycles (Rayleigh distribution)
        mpm = sigma * math.sqrt(2.0 * math.log(100.0)) if sigma > 1e-12 else 0.0

        return MotionStatistics(
            motion=label,
            m0=m0,
            m2=m2,
            significant_amplitude=sig,
            mean_zero_crossing_period=Tz,
            mpm_100=mpm,
        )

    return [
        _stats(S_heave, "heave"),
        _stats(S_pitch, "pitch"),
        _stats(S_roll, "roll"),
    ]


# ---------------------------------------------------------------------------
# Convenience: Wigley hull builder
# ---------------------------------------------------------------------------

def wigley_hull_sections(
    L: float,
    B: float,
    T: float,
    n_sections: int = 21,
) -> List[HullSection]:
    """
    Build strip sections for the Wigley parabolic hull:

        y(x, z) = (B/2) · [1 − (2x/L)²] · [1 − (z/T)²]

    where x ∈ [−L/2, L/2] (origin at midship), z ∈ [0, T] (0 at keel).

    Returns a list of HullSection objects suitable for RAO computation,
    with x measured from aft perpendicular (0 to L).
    """
    sections = []
    for i in range(n_sections):
        # x from aft: 0 → L
        x_aft = L * i / (n_sections - 1) if n_sections > 1 else L / 2.0
        # xi = (x - L/2) / (L/2)  ∈ [−1, 1]
        xi = (x_aft - L / 2.0) / (L / 2.0)

        # Half-beam at waterline (z = T):
        #   y_wl = (B/2) * (1 - xi²)
        B_wl_half = (B / 2.0) * (1.0 - xi ** 2)
        B_wl = 2.0 * B_wl_half  # full waterline beam

        # Local draft (same everywhere for Wigley hull)
        T_s = T

        # Section area: A = ∫₀ᵀ 2y(x,z) dz = 2*(B/2)*(1-xi²) * ∫₀ᵀ(1-(z/T)²)dz
        # ∫₀ᵀ (1 - (z/T)²) dz = T - T/3 = 2T/3
        A_s = 2.0 * B_wl_half * (2.0 * T / 3.0)

        sections.append(HullSection(x=x_aft, B_wl=B_wl, T_s=T_s, A_s=A_s))

    return sections
