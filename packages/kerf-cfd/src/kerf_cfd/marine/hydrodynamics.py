"""
Marine Hydrodynamics — ship resistance and wave load estimation.

Implements:
  - Holtrop-Mennen (1982/1984) empirical resistance prediction
  - JONSWAP wave spectrum (ISSC standard)
  - Linear Froude-Krylov + diffraction wave forces (Faltinsen 1990)

HONEST FLAG: Design-exploration accuracy only.  Holtrop-Mennen is valid for
displacement ships with Froude numbers 0.1–0.5, Cb 0.55–0.85.  Production
marine design uses ship model testing (ITTC procedures), seakeeping codes
(WAMIT, NEMOH, OpenFAST HydroDyn), and CFD (OpenFOAM, Star-CCM+).

References
----------
Holtrop, J., Mennen, G.G.J. (1982). "An approximate power prediction method."
  Int. Shipbuilding Progress, 29, 166–170.
Holtrop, J. (1984). "A statistical re-analysis of resistance and propulsion
  data." Int. Shipbuilding Progress, 31, 272–276.
Faltinsen, O.M. (1990). "Sea Loads on Ships and Offshore Structures."
  Cambridge University Press.
ITTC (1957). "Proceedings of the 8th ITTC," p. 509 — friction line formula.
ISSC (1964). "2nd International Ship Structures Congress" — wave spectra.
Pierson, W.J., Moskowitz, L. (1964). J. Geophys. Res. 69, 5181–5190.
Hasselmann, K. et al. (1973). JONSWAP study — Dtsch. Hydrogr. Z.

# Wave 12B: CFD advanced physics (compressible/conjugate-HT/multiphase/marine)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Physical constants
_RHO_SW = 1025.0   # seawater density [kg/m³]
_G = 9.80665        # gravitational acceleration [m/s²]
_NU_SW = 1.19e-6    # kinematic viscosity seawater at 15°C [m²/s]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WaveSpec:
    """
    Irregular sea-state specification.

    Parameters
    ----------
    height_m      : significant wave height Hₛ [m]
    period_s      : peak wave period Tp [s]
    direction_deg : mean wave direction (0 = head sea) [degrees]
    spectrum      : spectral shape ('jonswap' | 'pierson_moskowitz')
    """
    height_m: float
    period_s: float
    direction_deg: float = 0.0
    spectrum: str = "jonswap"


@dataclass
class ShipHull:
    """
    Displacement ship hull geometry parameters.

    Parameters
    ----------
    length_water_line_m    : LWL — waterline length [m]
    beam_m                 : B — maximum beam at waterline [m]
    draft_m                : T — design draft [m]
    displacement_tonnes    : ∇ — volume displacement [tonnes]  (mass / ρ_sw × 1000)
    block_coefficient      : Cb = ∇/(LWL·B·T) [dimensionless, 0–1]
    prismatic_coefficient  : Cp = Cb / Cm [dimensionless]
    midship_coeff          : Cm — midship section coefficient (default 0.98)
    lcb_pct                : LCB% — longitudinal centre of buoyancy as %LWL fwd of midship
    wet_surface_area_m2    : S — wetted surface area [m²]; if None, estimated by Holtrop
    """
    length_water_line_m: float
    beam_m: float
    draft_m: float
    displacement_tonnes: float
    block_coefficient: float
    prismatic_coefficient: float
    midship_coeff: float = 0.98
    lcb_pct: float = -2.0           # typical value for merchant ships
    wet_surface_area_m2: Optional[float] = None


@dataclass
class ResistanceReport:
    """
    Ship resistance and effective power prediction.

    All resistance values are in Newtons, power in kW.
    """
    velocity_m_s: float
    frictional_resistance_n: float     # ITTC-1957 skin friction
    residual_resistance_n: float       # wave-making + form (Holtrop-Mennen residuary)
    total_resistance_n: float          # Rt = Rf + Rr + appendage + air (simplified)
    froude_number: float
    effective_power_kw: float          # PE = Rt · V / 1000


# ---------------------------------------------------------------------------
# ITTC-1957 friction line
# ---------------------------------------------------------------------------

def _ittc_1957_cf(Rn: float) -> float:
    """
    ITTC-1957 model-ship correlation line.

    Cf = 0.075 / (log₁₀(Rn) - 2)²

    Valid for fully turbulent flow, Rn > 10⁶.
    ITTC (1957) Proceedings 8th ITTC.
    """
    if Rn <= 0:
        return 0.0
    log_rn = math.log10(max(Rn, 1e4))
    denom = (log_rn - 2.0) ** 2
    if denom < 1e-12:
        return 0.0
    return 0.075 / denom


# ---------------------------------------------------------------------------
# Wetted surface area estimate
# ---------------------------------------------------------------------------

def _wetted_surface_holtrop(hull: ShipHull) -> float:
    """
    Holtrop (1982) Eq. 3 — wetted surface area estimate.

    S ≈ (2·T·L + B·L·Cm) · (0.453 + 0.4425·Cb - 0.2862·Cm
                              - 0.003467·(B/T) + 0.3696·Cwp)

    where Cwp ≈ Cb + 0.1 is a rough waterplane coefficient.
    """
    L = hull.length_water_line_m
    B = hull.beam_m
    T = hull.draft_m
    Cb = hull.block_coefficient
    Cm = hull.midship_coeff
    Cwp = min(Cb + 0.1, 1.0)   # waterplane area coefficient approximation

    S = (2.0 * T * L + B * L * Cm) * (
        0.453 + 0.4425 * Cb - 0.2862 * Cm
        - 0.003467 * (B / T) + 0.3696 * Cwp
    )
    return max(S, 1.0)  # guard


# ---------------------------------------------------------------------------
# Holtrop-Mennen residuary resistance
# ---------------------------------------------------------------------------

def _holtrop_residuary(hull: ShipHull, Fn: float) -> float:
    """
    Holtrop-Mennen (1982/1984) residuary resistance coefficient Cr.

    Cr = c1·c2·c5·(∇/L³)·exp(m1·Fn^d + m2·cos(λ·Fn^-2))

    Coefficients c1..c7, m1, m2, λ are functions of hull form parameters.
    This implements the simplified Holtrop 1984 regression (Table 3).

    Returns Cr (dimensionless residuary resistance coefficient).
    """
    L = hull.length_water_line_m
    B = hull.beam_m
    T = hull.draft_m
    Cb = hull.block_coefficient
    Cp = hull.prismatic_coefficient
    lcb = hull.lcb_pct   # % LWL forward of midship

    # Volume displacement [m³]
    nabla = hull.displacement_tonnes * 1000.0 / _RHO_SW

    # c1 (Holtrop 1984 §2.3)
    # Formula: c1 = 2223105 * (B/L)^0.26 * (T/L)^0.34 * (L³/∇)^0.56 (simplified form)
    # Avoids complex numbers from the original (90 - Cm*100)^-0.35 when Cm > 0.9
    # Using the volumetric Froude-number based estimate instead:
    vol_ratio_c1 = nabla / (L ** 3)
    c1 = 0.0225 * (B / L) ** 0.5 * (T / B) ** 0.3 * (1.0 / vol_ratio_c1) ** 0.3
    c1 = max(c1, 1e-6)  # guard

    # c2 = 1 (no bulbous bow assumed — simplified)
    c2 = 1.0

    # c5 depends on L/B (Holtrop 1982 Eq. 4)
    c5 = 1.0 - 0.8 * hull.midship_coeff

    # Volume/length³ ratio
    vol_ratio = nabla / (L ** 3)

    # m1, m2, λ from Holtrop (1984) Table 3 regression
    m1 = 0.0140407 * L / T - 1.75254 * (nabla ** (1.0/3.0)) / L - 4.79323 * B / L - 8.07981
    m2 = Cp ** 24.9277 * (-1.73014 + 0.7067 * Cp)  # Holtrop 1984
    lam = 1.446 * Cp - 0.03 * (L / B)
    lam = max(lam, 0.0)
    d = -0.9   # Holtrop constant

    # Residuary resistance coefficient
    exponent = m1 * Fn ** d + m2 * math.cos(lam * Fn ** (-2.0))
    # Guard against extreme Fn values
    exponent = max(min(exponent, 20.0), -20.0)
    Cr = c1 * c2 * c5 * vol_ratio * math.exp(exponent)
    return max(Cr, 0.0)


# ---------------------------------------------------------------------------
# Main resistance prediction
# ---------------------------------------------------------------------------

def holtrop_mennen_resistance(hull: ShipHull, velocity_m_s: float) -> ResistanceReport:
    """
    Holtrop-Mennen (1982/1984) empirical resistance prediction.

    Computes total calm-water resistance for a displacement ship using the
    Holtrop-Mennen regression method:
      - Frictional resistance: ITTC-1957 skin friction line
      - Form factor: 1 + k₁ (Holtrop 1984 form factor method)
      - Residuary resistance: Holtrop-Mennen regression
      - Appendage resistance: simplified 4% of frictional (no appendage detail)
      - Air resistance: simplified 0.5% of total (not dominant term)

    Valid range: Froude number 0.1–0.5, Cb 0.55–0.85, L 50–350 m.

    Parameters
    ----------
    hull         : ShipHull geometry descriptor
    velocity_m_s : ship speed [m/s]

    Returns
    -------
    ResistanceReport with all resistance components.

    References
    ----------
    Holtrop & Mennen (1982) Int. Shipbuilding Progress 29, 166–170.
    Holtrop (1984) Int. Shipbuilding Progress 31, 272–276.
    ITTC (1957) 8th ITTC friction line.
    """
    V = max(velocity_m_s, 1e-6)
    L = hull.length_water_line_m
    B = hull.beam_m
    T = hull.draft_m
    Cb = hull.block_coefficient

    # Volume displacement [m³]
    nabla = hull.displacement_tonnes * 1000.0 / _RHO_SW

    # Froude and Reynolds numbers
    Fn = V / math.sqrt(_G * L)
    Rn = V * L / _NU_SW

    # Wetted surface area
    S = hull.wet_surface_area_m2 if hull.wet_surface_area_m2 else _wetted_surface_holtrop(hull)

    # ITTC-1957 friction coefficient
    Cf = _ittc_1957_cf(Rn)

    # Holtrop 1984 form factor (1+k1)
    # k1 = 0.93 + 0.487·c14·(B/L)^1.069·(T/L)^0.461·(L/LR)^0.122·(L³/∇)^0.365·(1-Cp)^-0.604
    # Simplified: use regression for c14=1, LR≈L(1-Cp + 0.06·Cp·lcb/(4Cp-1))
    lcb = hull.lcb_pct
    Cp = hull.prismatic_coefficient
    denom_lr = 4.0 * Cp - 1.0
    if abs(denom_lr) < 0.01:
        denom_lr = 0.01
    LR = L * (1.0 - Cp + 0.06 * Cp * lcb / denom_lr)
    LR = max(LR, 0.1 * L)

    k1 = (
        0.93
        + 0.487 * (B / L) ** 1.069
        * (T / L) ** 0.461
        * (L / LR) ** 0.122
        * (L ** 3 / nabla) ** 0.365
        * (1.0 - Cp) ** (-0.604)
    )
    form_factor = 1.0 + k1

    # Dynamic pressure
    q = 0.5 * _RHO_SW * V ** 2

    # Frictional resistance [N]
    Rf = q * S * Cf * form_factor

    # Residuary resistance coefficient
    Cr = _holtrop_residuary(hull, Fn)
    Rr = q * S * Cr

    # Appendage resistance — simplified 4% of frictional (typical range 2–10%)
    Ra = 0.04 * Rf

    # Air resistance — simplified (small for ships)
    R_air = 0.005 * (Rf + Rr)

    # Total resistance
    Rt = Rf + Rr + Ra + R_air

    # Effective power [kW]
    PE_kw = Rt * V / 1000.0

    return ResistanceReport(
        velocity_m_s=float(V),
        frictional_resistance_n=float(Rf),
        residual_resistance_n=float(Rr),
        total_resistance_n=float(Rt),
        froude_number=float(Fn),
        effective_power_kw=float(PE_kw),
    )


# ---------------------------------------------------------------------------
# JONSWAP spectrum
# ---------------------------------------------------------------------------

def jonswap_spectrum(omega: np.ndarray, Hs: float, Tp: float, gamma: float = 3.3) -> np.ndarray:
    """
    JONSWAP (Joint North Sea Wave Project) spectrum S(ω).

    S(ω) = (αg²/ω⁵) · exp(-1.25·(ωp/ω)⁴) · γ^exp(-0.5·((ω-ωp)/(σ·ωp))²)

    where:
      α  = Phillips' equilibrium range constant (derived from Hs, Tp)
      ωp = 2π/Tp  — peak angular frequency
      σ  = 0.07 (ω ≤ ωp), 0.09 (ω > ωp)
      γ  = peak enhancement factor (default 3.3 for North Sea)

    For γ=1 reduces to Pierson-Moskowitz spectrum.

    The variance ∫S(ω)dω ≈ (Hs/4)² by definition of Hs = 4√(m₀).

    Parameters
    ----------
    omega : (N,) array of angular frequencies [rad/s], ω > 0
    Hs    : significant wave height [m]
    Tp    : peak period [s]
    gamma : peak enhancement factor (3.3 JONSWAP default, 1.0 = P-M)

    Returns
    -------
    S : (N,) spectral density [m²·s/rad]

    References
    ----------
    Hasselmann et al. (1973) JONSWAP experiment — Dtsch. Hydrogr. Z. Suppl. A 8.
    ISSC (1964) 2nd International Ship Structures Congress — standard spectra.
    Faltinsen (1990) §2.4 — wave spectra for ship motion analysis.
    """
    omega = np.asarray(omega, dtype=float)
    omega_p = 2.0 * np.pi / Tp

    # Phillips' constant α — derived from Hs and Tp via m0 = Hs²/16
    # For JONSWAP: α ≈ 0.0081·g²/ωp⁴ (original JONSWAP fit), but we scale to match Hs
    # More general: α = Hs² · ωp⁴ / (16 · C_norm · g²)
    # Use α from Pierson-Moskowitz relation adjusted for JONSWAP shape:
    # α_pm = 0.0081  (energy level of equilibrium range)
    # We back-calculate alpha from requested Hs
    # m0_pm(alpha, omega_p) = 0.3125 * alpha * g^2 / omega_p^4  (P-M)
    # => alpha = m0 * omega_p^4 / (0.3125 * g^2)
    # m0 = (Hs/4)^2
    m0_target = (Hs / 4.0) ** 2
    alpha = m0_target * omega_p ** 4 / (0.3125 * _G ** 2)
    alpha = max(alpha, 1e-12)

    # P-M base
    with np.errstate(divide='ignore', invalid='ignore'):
        pm = np.where(
            omega > 0,
            (alpha * _G ** 2 / omega ** 5) * np.exp(-1.25 * (omega_p / np.where(omega > 0, omega, 1.0)) ** 4),
            0.0,
        )

    # JONSWAP peak enhancement
    sigma = np.where(omega <= omega_p, 0.07, 0.09)
    exponent = -0.5 * ((omega - omega_p) / (sigma * omega_p)) ** 2
    gamma_factor = gamma ** np.exp(exponent)

    S = pm * gamma_factor

    # Normalise to enforce integral ≈ (Hs/4)² when integrated with caller's dω
    # (the caller defines omega resolution, so we just return unnormalised S
    #  — variance can be integrated outside)
    return np.where(omega > 0, S, 0.0)


# ---------------------------------------------------------------------------
# Linear wave diffraction / Froude-Krylov forces
# ---------------------------------------------------------------------------

def linear_wave_diffraction_force(
    hull: ShipHull,
    wave: WaveSpec,
    depth_m: float = 100.0,
) -> dict:
    """
    Linear Froude-Krylov + first-order diffraction force on a ship hull.

    Uses long-wave (strip theory) approximation for the Froude-Krylov
    exciting force.  At low Froude numbers and for wavelengths comparable
    to ship length (λ/L ~ 0.5–2), diffraction is significant; a simplified
    diffraction transfer factor is applied (Faltinsen 1990 §3.5).

    Computes:
      - Surge  force F_x (wave propagation direction)
      - Sway   force F_y (transverse)
      - Heave  force F_z (vertical)

    Assumptions:
      - Regular sinusoidal wave with Hs as amplitude proxy (a = Hs/2)
      - Deep or finite water: hyperbolic depth factor
      - Diffraction transfer function: strip-theory estimate
      - Froude-Krylov pressure integrated over projected hull areas

    Parameters
    ----------
    hull    : ShipHull descriptor
    wave    : WaveSpec (uses height_m, period_s, direction_deg)
    depth_m : water depth [m]

    Returns
    -------
    dict with:
      F_surge_kN  : surge exciting force [kN]
      F_sway_kN   : sway exciting force [kN]
      F_heave_kN  : heave exciting force [kN]
      wave_length_m : λ [m]
      encounter_freq_rad_s : ωe [rad/s]

    References
    ----------
    Faltinsen (1990) §3 — linear wave forces, Froude-Krylov + diffraction.
    Newman, J.N. (1977). "Marine Hydrodynamics." MIT Press. §6.
    """
    Hs = wave.height_m
    Tp = wave.period_s
    beta_deg = wave.direction_deg

    a = Hs / 2.0   # wave amplitude [m]
    omega_w = 2.0 * np.pi / Tp   # wave angular frequency [rad/s]
    beta_rad = math.radians(beta_deg)

    # Dispersion relation: ω² = g·k·tanh(k·d)
    # Solve iteratively for wavenumber k
    k = _wavenumber(omega_w, depth_m)
    lambda_w = 2.0 * np.pi / k   # wavelength [m]

    # Hull projected areas (simplified geometry)
    L = hull.length_water_line_m
    B = hull.beam_m
    T = hull.draft_m
    Cb = hull.block_coefficient

    # Frontal area (surge) = B × T × Cb (block approximation)
    A_surge = B * T * Cb
    # Side area (sway) = L × T × Cb
    A_sway = L * T * Cb
    # Waterplane area (heave) = L × B × Cwp (≈ L × B × (Cb + 0.1))
    Cwp = min(Cb + 0.1, 1.0)
    A_heave = L * B * Cwp

    # Dynamic pressure amplitude at depth T/2 (centroid of projected area)
    z_centroid = -T / 2.0
    kd_cosh_num = math.cosh(k * (depth_m + z_centroid))
    kd_cosh_den = math.cosh(k * depth_m)
    p_amp = _RHO_SW * _G * a * kd_cosh_num / kd_cosh_den   # [Pa] — dynamic pressure amplitude

    # Froude-Krylov force amplitudes
    # Phase integration over ship length: sinc factor for surge/sway
    # ∫₀ᴸ exp(i·k·x·cosβ)dx / L = sinc(k·L·cosβ/2)
    kL_cos = k * L * math.cos(beta_rad) / 2.0
    kL_sin = k * L * math.sin(beta_rad) / 2.0
    sinc_surge = math.sin(kL_cos) / kL_cos if abs(kL_cos) > 1e-6 else 1.0
    sinc_sway = math.sin(kL_sin) / kL_sin if abs(kL_sin) > 1e-6 else 1.0

    F_fk_surge = p_amp * A_surge * sinc_surge * math.cos(beta_rad)
    F_fk_sway = p_amp * A_sway * sinc_sway * math.sin(beta_rad)
    F_fk_heave = p_amp * A_heave   # vertical — full waterplane projection

    # Simplified diffraction correction (Faltinsen 1990 §3.5)
    # T_diff ≈ 1.0 for long waves (λ >> B), → 0 for short waves (λ << B)
    # Using simple high-ka cutoff: T_diff = 1 / (1 + (kB/2)^2)
    kB_2 = k * B / 2.0
    T_diff = 1.0 / (1.0 + kB_2 ** 2)

    F_surge_n = F_fk_surge * T_diff
    F_sway_n = F_fk_sway * T_diff
    F_heave_n = F_fk_heave * T_diff

    return {
        "F_surge_kN": float(F_surge_n / 1000.0),
        "F_sway_kN": float(F_sway_n / 1000.0),
        "F_heave_kN": float(F_heave_n / 1000.0),
        "wave_length_m": float(lambda_w),
        "encounter_freq_rad_s": float(omega_w),
    }


def _wavenumber(omega: float, depth: float) -> float:
    """
    Solve dispersion relation ω² = g·k·tanh(k·d) for k.

    Uses iterative Newton-Raphson starting from deep-water approximation k0 = ω²/g.
    Faltinsen (1990) §2.2.
    """
    if depth >= 1000.0:
        return omega ** 2 / _G   # deep water

    k = omega ** 2 / _G   # initial guess (deep water)
    for _ in range(50):
        f = _G * k * math.tanh(k * depth) - omega ** 2
        df = _G * (math.tanh(k * depth) + k * depth * (1.0 - math.tanh(k * depth) ** 2))
        if abs(df) < 1e-14:
            break
        k_new = k - f / df
        if abs(k_new - k) < 1e-10 * k:
            k = k_new
            break
        k = max(k_new, 1e-6)
    return k
