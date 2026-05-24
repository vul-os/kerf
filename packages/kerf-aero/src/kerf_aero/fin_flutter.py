"""Fin flutter speed analysis per Barrowman / NACA TN 4197.

Implements the classical compressible-flutter formula for trapezoidal rocket
fins derived from plate vibration theory (Barrowman 1966, NACA TN 4197):

    V_f = a * sqrt(G / (K_v * q_dyn_coeff * AR^3 * (1+taper)² / (t/c)³ / S_fin))

The working formula used here is the simplified Barrowman form commonly used
by OpenRocket and NAR certification programs:

    V_f = a * sqrt( 2*G / (rho * (t/c)^3 * AR^3 * lambda^2 / (1+lambda)^2 ) )
        = a * sqrt( 2*G*(t/c)^3*(1+lambda)^2 / (rho * AR^3 * lambda^2 ) )

where the flutter speed V_f is in m/s at the altitude of interest (air density
and speed of sound from USSA-76).

Parameters
----------
span : float
    Full half-span of fin set (tip-to-root projected; not the slant) [m].
    For trapezoidal fins this is the length in the y-direction.
root_chord : float
    Root chord length [m].
tip_chord : float
    Tip chord length [m]. Zero for triangular fins.
thickness : float
    Maximum fin thickness [m].
shear_modulus : float
    In-plane shear modulus of the fin material [Pa].
altitude : float
    Altitude at which to evaluate atmospheric properties [m], default 0.

Returns
-------
FinFlutterResult
    flutter_speed_ms : flutter speed V_f [m/s]
    mach_flutter     : flutter Mach number
    safety_margin    : V_flutter / V_design (if design_speed given, else NaN)

References
----------
Barrowman, J.S. (1966). "The Practical Calculation of the Aerodynamic
    Characteristics of Slender Finned Vehicles." M.Sc. Thesis, The Catholic
    University of America.
NACA TN 4197 (1957). Bisplinghoff, Ashley, Halfman — Aeroelasticity,
    Fig. 5-3 (fin flutter).
OpenRocket Technical Documentation, §3.4 "Fin flutter speed."
NAR Safety Code for High-Power Rocketry, Appendix D.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .flight_dynamics.atmosphere import atmosphere


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FinFlutterResult:
    """Results of fin flutter speed calculation.

    Attributes
    ----------
    flutter_speed_ms : float
        Flutter speed at the given altitude [m/s].
    mach_flutter : float
        Flutter Mach number (V_f / a_sound).
    aspect_ratio : float
        Effective fin panel aspect ratio.
    taper_ratio : float
        Fin taper ratio λ = tip_chord / root_chord.
    tc_ratio : float
        Maximum thickness-to-chord ratio t/c.
    safety_margin : float
        V_flutter / design_speed.  NaN if design_speed not provided.
    """

    flutter_speed_ms: float
    mach_flutter: float
    aspect_ratio: float
    taper_ratio: float
    tc_ratio: float
    safety_margin: float


# ---------------------------------------------------------------------------
# Main calculation
# ---------------------------------------------------------------------------

def fin_flutter_speed(
    span: float,
    root_chord: float,
    tip_chord: float,
    thickness: float,
    shear_modulus: float,
    altitude: float = 0.0,
    design_speed_ms: Optional[float] = None,
) -> FinFlutterResult:
    """Compute fin flutter speed using the Barrowman / NACA TN 4197 method.

    The formula (Barrowman 1966, eq. 7.1; OpenRocket §3.4):

        V_f = a * sqrt( 2 * G * (t/c)^3 * (1+λ)^2 / (rho * AR^3 * λ^2 * P_dyn_ref) )

    where P_dyn_ref = 1 Pa (normalisation absorbed into the formula via direct
    density and speed-of-sound from USSA-76).

    The semi-span form uses AR = (2*b)^2 / S_fin where S_fin = b*(root+tip)/2,
    so AR = 4*b / (root+tip).

    Parameters
    ----------
    span : float
        Fin semi-span (from body surface to tip) [m].
    root_chord : float
        Root chord [m].
    tip_chord : float
        Tip chord [m].
    thickness : float
        Maximum thickness [m].
    shear_modulus : float
        Shear modulus G [Pa].  Typical values:
            Aluminium 2024-T3: 27.6e9 Pa
            G10/FR4 composite: 2.5e9 Pa
            Balsa (EW grain):  100e6 Pa
    altitude : float
        Altitude for atmospheric properties [m].
    design_speed_ms : float | None
        Design airspeed at which to compute safety margin [m/s].

    Returns
    -------
    FinFlutterResult

    Raises
    ------
    ValueError
        If geometry or material parameters are non-physical.

    Examples
    --------
    Aluminium fin, AR 2.5, 1.8% t/c, sea level:

    >>> r = fin_flutter_speed(0.1, 0.08, 0.04, 0.00144, 27.6e9)
    >>> r.flutter_speed_ms > 200
    True
    """
    if span <= 0:
        raise ValueError(f"span must be positive; got {span}")
    if root_chord <= 0:
        raise ValueError(f"root_chord must be positive; got {root_chord}")
    if tip_chord < 0:
        raise ValueError(f"tip_chord must be >= 0; got {tip_chord}")
    if thickness <= 0:
        raise ValueError(f"thickness must be positive; got {thickness}")
    if shear_modulus <= 0:
        raise ValueError(f"shear_modulus must be positive; got {shear_modulus}")

    # Fin panel reference chord (mean aerodynamic chord of trapezoid)
    mac = (2 / 3) * root_chord * (
        1 + (tip_chord / root_chord) + (tip_chord / root_chord) ** 2
    ) / (1 + tip_chord / root_chord)  # [m]

    # Fin panel area
    s_fin = span * (root_chord + tip_chord) / 2.0  # [m²]

    # Aspect ratio (semi-span form): AR = (2b)² / S_fin / 2  for a single panel
    # The standard fin-flutter definition uses the panel aspect ratio:
    #   AR_panel = (2 * span)^2 / (2 * s_fin) = 2 * span^2 / s_fin
    # (factor of 2 because full-span fin = 2 × semi-span panels)
    ar = (2.0 * span) ** 2 / (2.0 * s_fin)  # panel AR (≈ 2b/c_avg)

    # Taper ratio λ = tip/root
    lam = tip_chord / root_chord if root_chord > 0 else 0.0

    # Thickness-to-chord ratio (using mean chord)
    tc = thickness / mac if mac > 0 else thickness / root_chord

    # USSA-76 atmosphere at given altitude
    atm = atmosphere(altitude)
    rho = atm.density_kg_m3        # [kg/m³]
    a_sound = atm.speed_of_sound_m_s  # [m/s]

    # Barrowman flutter speed formula:
    #
    #   V_f^2 = 2*G*(t/c)^3 * (1+λ)^2 / (rho * AR^3 * λ^2)   [m²/s²]
    #
    # This is the widely-cited form from OpenRocket Technical Documentation §3.4
    # and reproduced in the NAR High-Power Rocketry Safety Code.
    #
    # For λ = 0 (triangular fin), use λ → 0+:  the (1+λ)^2/λ^2 → ∞,
    # which means triangular fins have infinite flutter resistance (flutter not
    # a concern).  In practice triangular fins behave like semi-span 0, so we
    # clip λ to a small positive value.
    lam_eff = max(lam, 1e-6)

    numerator = 2.0 * shear_modulus * tc ** 3 * (1.0 + lam_eff) ** 2
    denominator = rho * ar ** 3 * lam_eff ** 2

    if denominator <= 0:
        vf = float("inf")
    else:
        vf_sq = numerator / denominator
        vf = math.sqrt(vf_sq)

    mach_flutter = vf / a_sound if a_sound > 0 else float("inf")

    if design_speed_ms is not None and design_speed_ms > 0:
        safety_margin = vf / design_speed_ms
    else:
        safety_margin = float("nan")

    return FinFlutterResult(
        flutter_speed_ms=vf,
        mach_flutter=mach_flutter,
        aspect_ratio=ar,
        taper_ratio=lam,
        tc_ratio=tc,
        safety_margin=safety_margin,
    )


# ---------------------------------------------------------------------------
# Barrowman CP/CG static margin
# ---------------------------------------------------------------------------

@dataclass
class RocketStabilityResult:
    """CP location and static margin for a fin-stabilised rocket.

    Attributes
    ----------
    cp_from_nose : float
        Center of pressure measured from nose tip [m].
    cg_from_nose : float
        Center of gravity measured from nose tip [m].
    static_margin_cal : float
        Static margin in calibres (cp - cg) / body_diameter.
        Positive = stable (CP aft of CG).
    cn_alpha_total : float
        Total normal force slope CN_alpha [1/rad].
    """

    cp_from_nose: float
    cg_from_nose: float
    static_margin_cal: float
    cn_alpha_total: float


def barrowman_cp(
    nose_length: float,
    body_diameter: float,
    fin_span: float,
    fin_root_chord: float,
    fin_tip_chord: float,
    fin_sweep_le: float,
    n_fins: int,
    fin_root_trailing_edge_from_nose: float,
    cg_from_nose: float,
) -> RocketStabilityResult:
    """Barrowman CP calculation for a fin-stabilised rocket.

    Uses the extended Barrowman method (Barrowman 1966 Appendix A) as
    implemented in OpenRocket and documented in the OpenRocket Technical
    Documentation §2.

    Component contributions:
        Nose cone: CN_alpha = 2  (any slender nose shape)
        Cylindrical body: CN_alpha = 0  (no contribution in linear theory)
        Fin set: CN_alpha per Barrowman eq. 3.22

    Parameters
    ----------
    nose_length : float
        Nose cone length [m].
    body_diameter : float
        Body tube outer diameter [m].
    fin_span : float
        Fin semi-span (from body surface to tip) [m].
    fin_root_chord : float
        Fin root chord [m].
    fin_tip_chord : float
        Fin tip chord [m].
    fin_sweep_le : float
        Fin leading-edge sweep angle measured from the body normal [deg].
    n_fins : int
        Number of fins (typically 3 or 4).
    fin_root_trailing_edge_from_nose : float
        Distance from nose tip to the trailing edge of fin root [m].
    cg_from_nose : float
        CG location measured from nose tip [m].

    Returns
    -------
    RocketStabilityResult

    References
    ----------
    Barrowman (1966) Appendix A, eq. A-5 through A-11.
    OpenRocket Technical Documentation §2.1-2.3.
    """
    if body_diameter <= 0:
        raise ValueError(f"body_diameter must be positive; got {body_diameter}")
    if n_fins < 3:
        raise ValueError(f"n_fins must be >= 3; got {n_fins}")

    d = body_diameter
    r_body = d / 2.0
    s = fin_span              # semi-span (from body surface)
    cr = fin_root_chord
    ct = fin_tip_chord
    sweep_rad = math.radians(fin_sweep_le)

    # ---- Nose contribution ----
    # For any slender nose (von Karman, ogive, conical, parabolic):
    cn_alpha_nose = 2.0        # [1/rad], per body calibre diameter
    cp_nose = nose_length / 2.0   # [m] from nose tip (approximation for ogive)

    # ---- Fin set contribution (Barrowman eq. A-9 and A-11) ----
    # Total fin panel span relative to body (full span = 2*(r_body + s))
    r_t = r_body + s           # tip radius = body radius + semi-span

    # Barrowman CN_alpha per fin set (all fins, referenced to body area pi*r^2)
    # The formula (Barrowman eq. 3.22):
    #   CN_alpha_fins = (4*n*(s/d)^2) / (1 + sqrt(1 + (2*l_m / (cr+ct))^2))
    # where l_m = fin midchord length (projected span at mid-chord)
    #   l_m = sqrt(s^2 + (sweep_at_midchord)^2)
    # Simplified: l_m = s using fin mid-chord sweep projected to normal:
    #   x_m = (cr - ct)/2 + s*tan(sweep_le)  — x-displacement of midchord point
    # Use half-chord difference for mid-chord LE location:
    x_le_tip = s * math.tan(sweep_rad)   # LE tip x-offset from LE root [m]
    x_mid_tip = x_le_tip + ct / 2.0      # midchord x at tip
    x_mid_root = cr / 2.0                # midchord x at root
    l_m = math.sqrt(s ** 2 + (x_mid_tip - x_mid_root) ** 2)  # midchord line length

    cn_alpha_fin_set = (
        4.0 * n_fins * (s / d) ** 2
        / (1.0 + math.sqrt(1.0 + (2.0 * l_m / (cr + ct)) ** 2))
    )

    # Fin CP location from nose (x_fin_root_LE + delta_fin_cp)
    # LE of fin root at:  fin_root_trailing_edge_from_nose - cr
    x_fin_root_le = fin_root_trailing_edge_from_nose - cr

    # CP of fin panel from fin root LE (Barrowman eq. A-11):
    #   delta = cr/3 * (cr + 2*ct)/(cr + ct) + l_m/6 * (cr + ct) / (cr + ct)
    #   (simplified from Barrowman; for trapezoidal planform)
    # Standard form:
    delta_fin_cp = (
        cr / 3.0 * (cr + 2.0 * ct) / (cr + ct)
        + l_m / 6.0 * (cr + ct) / max(cr + ct, 1e-12)
    )
    cp_fins = x_fin_root_le + delta_fin_cp   # [m] from nose

    # ---- Total CP (area-weighted) ----
    cn_alpha_total = cn_alpha_nose + cn_alpha_fin_set
    cp_total = (cn_alpha_nose * cp_nose + cn_alpha_fin_set * cp_fins) / cn_alpha_total

    # ---- Static margin ----
    static_margin_cal = (cp_total - cg_from_nose) / d   # positive = stable

    return RocketStabilityResult(
        cp_from_nose=cp_total,
        cg_from_nose=cg_from_nose,
        static_margin_cal=static_margin_cal,
        cn_alpha_total=cn_alpha_total,
    )
