"""
Antenna element design — resonant dimensions, impedance, gain, bandwidth.

Distinct from:
  • kerf_electronics.rfmatch   — matching networks (L/pi/T, stub, balun)
  • kerf_electronics.linkbudget — path loss / link budget (Friis, FSPL)
  • kerf_electronics.emc        — EMC/EMI pre-compliance estimation
  • kerf_electronics.si         — signal integrity (Z0, propagation)

Supported antenna types
-----------------------
  half_wave_dipole      — resonant length, input impedance, gain, BW
  monopole              — quarter-wave monopole over ground (image theory)
  small_loop            — electrically-small loop (ka < 0.5)
  microstrip_patch      — rectangular patch (effective εr, L/W, fringing,
                          edge impedance, inset feed)
  yagi_uda              — Yagi-Uda (driven/reflector/director → gain, F/B)
  helical_axial         — helical antenna in axial (end-fire) mode
  horn_gain             — horn aperture gain from physical dimensions

General utilities
-----------------
  directivity_gain_efficiency   — D / G / η triangle
  beamwidth_directivity         — Kraus approximation (θ_E, θ_H → D)
  aperture_efficiency           — Aeff and ηap from gain and λ
  near_far_field_boundary       — Fraunhofer (2D²/λ) and reactive boundary
  polarization_axial_ratio      — axial ratio → polarisation loss factor
  ground_plane_image            — image-effect impedance and gain for monopole
  array_factor_ula              — uniform linear array AF, beam steering,
                                   grating lobe check
  vswr_bandwidth_from_q         — fractional bandwidth from antenna Q and VSWR

All functions are pure Python (math / cmath only) and follow the kerf
never-raise contract: validation errors are returned as dicts
  {"ok": False, "reason": <str>}
Limit/range warnings (electrically-small, out-of-band, grating lobes) are
issued via warnings.warn; exceptions are never raised to callers.

References
----------
  Balanis, C.A., "Antenna Theory", 4th ed. (Wiley, 2016).
  Kraus, J.D. & Marhefka, R.J., "Antennas for All Applications", 3rd ed. (McGraw-Hill, 2002).
  Pozar, D.M., "Microwave Engineering", 4th ed. (Wiley, 2012).

Author: imranparuk
"""
from __future__ import annotations

import cmath
import math
import warnings
from typing import Optional

# ── Physical constants ─────────────────────────────────────────────────────────

_C   = 2.997924580e8   # speed of light in vacuum [m/s]
_ETA = 376.730313668   # free-space wave impedance [Ω]  (= μ₀c)
_MU0 = 4.0 * math.pi * 1e-7   # permeability of free space [H/m]
_EPS0 = 8.854187817e-12        # permittivity of free space [F/m]

# ── Input validation helpers ──────────────────────────────────────────────────


def _pos(v, name: str) -> Optional[str]:
    """Return an error string if v is not a finite positive real number."""
    if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or v <= 0:
        return f"{name} must be a finite positive number, got {v!r}"
    return None


def _nonneg(v, name: str) -> Optional[str]:
    """Return an error string if v is negative or not finite."""
    if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or v < 0:
        return f"{name} must be >= 0, got {v!r}"
    return None


def _wavelength(freq_hz: float) -> float:
    return _C / freq_hz


# ══════════════════════════════════════════════════════════════════════════════
# 1. Half-wave dipole
# ══════════════════════════════════════════════════════════════════════════════

def half_wave_dipole(
    freq_hz: float,
    efficiency: float = 1.0,
    wire_diameter_m: float = 0.001,
) -> dict:
    """
    Resonant half-wave dipole design (Balanis §4.3).

    Resonant length (accounting for end effects):
        L_res = 0.4786 × λ   (empirical shortening factor ~4.3 % for thin wire)
        For a wire of finite diameter the exact shortening varies, but the
        standard analytical approximation for a thin dipole is used here.

    Input impedance at resonance (thin-dipole approximation):
        R_in ≈ 73.1 Ω,  X_in ≈ 42.5 Ω  (Balanis Table 4.2)
        The reactance is near-zero at the slightly shorter resonant length;
        we return both the half-wavelength impedance and the resonant length.

    Gain:
        G = η × D,   D ≈ 1.643  (Balanis §4.3)

    Bandwidth (VSWR ≤ 2 from Q):
        Q ≈ Rr / (X/Δf/f)  — approximated from VSWR=2 half-power bandwidth

    Parameters
    ----------
    freq_hz        : float — operating frequency [Hz]
    efficiency     : float — radiation efficiency η (0–1, default 1.0)
    wire_diameter_m : float — conductor diameter [m] (default 1 mm)

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, resonant_length_m, half_wave_length_m,
          R_in_ohm, X_in_ohm, gain_dbi, gain_dbd, directivity,
          radiation_efficiency, hpbw_e_plane_deg, hpbw_h_plane_deg,
          vswr_bw_fraction, vswr_bw_hz
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(efficiency, "efficiency")
    if err:
        return {"ok": False, "reason": err}
    if efficiency > 1.0:
        return {"ok": False, "reason": "efficiency must be <= 1.0"}
    err = _pos(wire_diameter_m, "wire_diameter_m")
    if err:
        return {"ok": False, "reason": err}

    lam = _wavelength(freq_hz)
    half_wave = 0.5 * lam

    # Resonant length (thin-dipole shortening)
    L_res = 0.4786 * lam   # ~4.3 % shortening

    # Electrically-thin check  (2a/λ < 0.01 considered thin)
    ka = math.pi * wire_diameter_m / lam
    if ka > 0.1:
        warnings.warn(
            f"half_wave_dipole: wire is not electrically thin "
            f"(2a/λ = {wire_diameter_m/lam:.4f}); "
            f"thin-wire impedance formulae may be inaccurate.",
            stacklevel=2,
        )

    # Impedance at half-wave point (not resonant, but useful reference)
    R_in = 73.1      # Ω  (Balanis Table 4.2)
    X_in = 42.5      # Ω

    # Directivity and gain
    D = 1.643
    G = efficiency * D
    G_dBi = 10.0 * math.log10(G)
    G_dBd = G_dBi - 2.15

    # HPBW: E-plane ≈ 78°, H-plane = 360° (omnidirectional)
    hpbw_e = 78.0
    hpbw_h = 360.0

    # VSWR=2 bandwidth via Q estimate
    # For a thin half-wave dipole Q ≈ 2 × Rr / (dX/dk × k)
    # Simplified: BW_VSWR2 ≈ Rr / (2 × |X_slope|)  where X_slope ≈ 150 Ω/octave
    # A well-known rule of thumb: BW ≈ Rr / (2 × 120) = 73 / 240 ≈ 30%
    # For VSWR ≤ 2: S=2 → |Γ|=1/3, BW_fraction ≈ 2/(Q×VSWR_factor)
    # Use Balanis §11.4 approximation: BW_VSWR2 = Rr / (120 × length_factor)
    Q_dipole = 2.0 * 120.0 / R_in   # ≈ 3.3 for thin half-wave dipole
    bw_fraction = 1.0 / (Q_dipole * math.sqrt(2))  # VSWR=2 half-BW × 2
    vswr_bw_hz = bw_fraction * freq_hz

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "resonant_length_m": round(L_res, 6),
        "half_wave_length_m": round(half_wave, 6),
        "R_in_ohm": R_in,
        "X_in_ohm": X_in,
        "directivity": round(D, 4),
        "gain_dbi": round(G_dBi, 3),
        "gain_dbd": round(G_dBd, 3),
        "radiation_efficiency": efficiency,
        "hpbw_e_plane_deg": hpbw_e,
        "hpbw_h_plane_deg": hpbw_h,
        "vswr_bw_fraction": round(bw_fraction, 5),
        "vswr_bw_hz": round(vswr_bw_hz, 1),
        "reference": "Balanis (2016) §4.3, Table 4.2",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. Monopole over ground plane (image theory)
# ══════════════════════════════════════════════════════════════════════════════

def monopole(
    freq_hz: float,
    efficiency: float = 1.0,
) -> dict:
    """
    Quarter-wave monopole over an infinite ground plane (Balanis §4.7).

    Image theory: the monopole + ground forms a full half-wave dipole image.

    Resonant length:
        L = λ/4 × 0.9574  (same 4.3 % shortening as dipole half-length)

    Input impedance (at λ/4):
        R_in = 36.5 Ω  (half the dipole value)
        X_in ≈ 21.25 Ω

    Gain:
        G = 2 × G_dipole = 2 × 1.643 × η = 3.286 × η
        G_dBi = 5.16 dBi  (over half-space)

    Parameters
    ----------
    freq_hz    : float — operating frequency [Hz]
    efficiency : float — radiation efficiency η (0–1, default 1.0)

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, resonant_length_m, quarter_wave_length_m,
          R_in_ohm, X_in_ohm, gain_dbi, directivity, radiation_efficiency
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(efficiency, "efficiency")
    if err:
        return {"ok": False, "reason": err}
    if efficiency > 1.0:
        return {"ok": False, "reason": "efficiency must be <= 1.0"}

    lam = _wavelength(freq_hz)
    quarter_wave = 0.25 * lam
    L_res = 0.4786 * lam / 2.0   # half of dipole resonant length

    R_in = 36.5
    X_in = 21.25
    D = 3.286
    G = efficiency * D
    G_dBi = 10.0 * math.log10(G)

    # HPBW (E-plane over ground = half-space): same ~78° as dipole over full-space
    hpbw_e = 78.0

    # Q and BW (same as dipole but 2× radiation resistance penalty offset)
    Q_mono = 2.0 * 120.0 / (2.0 * R_in)
    bw_fraction = 1.0 / (Q_mono * math.sqrt(2))
    vswr_bw_hz = bw_fraction * freq_hz

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "resonant_length_m": round(L_res, 6),
        "quarter_wave_length_m": round(quarter_wave, 6),
        "R_in_ohm": R_in,
        "X_in_ohm": X_in,
        "directivity": round(D, 4),
        "gain_dbi": round(G_dBi, 3),
        "radiation_efficiency": efficiency,
        "hpbw_e_plane_deg": hpbw_e,
        "hpbw_h_plane_deg": 360.0,
        "vswr_bw_fraction": round(bw_fraction, 5),
        "vswr_bw_hz": round(vswr_bw_hz, 1),
        "ground_plane_note": (
            "Assumes infinite perfectly conducting ground plane. "
            "Finite/imperfect ground reduces efficiency and alters impedance."
        ),
        "reference": "Balanis (2016) §4.7; image theory",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. Small loop antenna
# ══════════════════════════════════════════════════════════════════════════════

def small_loop(
    freq_hz: float,
    loop_area_m2: float,
    n_turns: int = 1,
    efficiency: float = 1.0,
) -> dict:
    """
    Electrically-small loop antenna (Balanis §5.2).

    Valid when ka << 1 (ka = 2π × sqrt(A/π) / λ < 0.5 recommended).

    Radiation resistance (N-turn loop):
        Rr = 31171 × N² × (A/λ²)²   [Ω]  (Balanis eq. 5-24)
        = (η/6π) × (N × β² × A)²

    Directivity:
        D = 1.5  (same as short dipole, electric/magnetic duality)

    Gain:
        G = η × D = η × 1.5

    HPBW:
        E-plane (magnetic dipole) = H-plane of electric dipole = 90°
        But for a loop oriented in the xy-plane, the broadside HPBW ≈ 90° (figure-8)

    Parameters
    ----------
    freq_hz      : float — operating frequency [Hz]
    loop_area_m2 : float — enclosed loop area [m²]
    n_turns      : int   — number of turns (default 1)
    efficiency   : float — radiation efficiency η (0–1, default 1.0)

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, ka, electrically_small,
          radiation_resistance_ohm, directivity, gain_dbi,
          radiation_efficiency, hpbw_deg
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(loop_area_m2, "loop_area_m2")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(n_turns, int) or n_turns < 1:
        return {"ok": False, "reason": "n_turns must be a positive integer"}
    err = _pos(efficiency, "efficiency")
    if err:
        return {"ok": False, "reason": err}
    if efficiency > 1.0:
        return {"ok": False, "reason": "efficiency must be <= 1.0"}

    lam = _wavelength(freq_hz)
    beta = 2.0 * math.pi / lam
    # Equivalent radius of circular loop with given area
    radius = math.sqrt(loop_area_m2 / math.pi)
    ka = beta * radius

    electrically_small = ka < 0.5
    if not electrically_small:
        warnings.warn(
            f"small_loop: ka = {ka:.4f} >= 0.5 — antenna is NOT electrically small; "
            f"small-loop approximation will be inaccurate. "
            f"Consider a different model for larger loops.",
            stacklevel=2,
        )

    # Radiation resistance (Balanis eq. 5-24)
    Rr = 31171.0 * n_turns**2 * (loop_area_m2 / lam**2) ** 2

    D = 1.5
    G = efficiency * D
    G_dBi = 10.0 * math.log10(G)

    # HPBW: figure-8 pattern → HPBW ≈ 90° in broadside planes
    hpbw_deg = 90.0

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "ka": round(ka, 6),
        "electrically_small": electrically_small,
        "n_turns": n_turns,
        "loop_area_m2": loop_area_m2,
        "radiation_resistance_ohm": Rr,
        "directivity": round(D, 4),
        "gain_dbi": round(G_dBi, 3),
        "radiation_efficiency": efficiency,
        "hpbw_deg": hpbw_deg,
        "reference": "Balanis (2016) §5.2, eq. 5-24",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. Rectangular microstrip patch antenna
# ══════════════════════════════════════════════════════════════════════════════

def microstrip_patch(
    freq_hz: float,
    er: float,
    h_m: float,
    efficiency: float = 0.90,
) -> dict:
    """
    Rectangular microstrip patch antenna design (Balanis §14.2, Pozar §6.5).

    Computes the effective permittivity, patch dimensions (W × L), fringing
    extension ΔL, edge radiation conductance, input impedance at the edge,
    and the required inset-feed distance for 50 Ω matching.

    Step 1 — Patch width W (for maximum efficiency, Balanis eq. 14-6):
        W = c / (2f) × sqrt(2 / (εr + 1))

    Step 2 — Effective permittivity εr_eff (Balanis eq. 14-1):
        εr_eff = (εr + 1)/2 + (εr − 1)/2 × [1 + 12h/W]^(−0.5)

    Step 3 — Fringing extension ΔL (Balanis eq. 14-2):
        ΔL/h = 0.412 × (εr_eff + 0.3)(W/h + 0.264) / ((εr_eff − 0.258)(W/h + 0.8))

    Step 4 — Resonant patch length L (Balanis eq. 14-3):
        L = c / (2f sqrt(εr_eff)) − 2ΔL

    Step 5 — Edge radiation conductance (Balanis eq. 14-16):
        G1 = W / (120 λ) × [1 − (k₀h)²/24]   for W/λ < 0.35

    Step 6 — Input impedance at radiating edge:
        Rin_edge = 1 / (2 G1 + 2 G12)
        where G12 ≈ 0 (for small W/λ), so Rin_edge ≈ 1 / (2 G1)

    Step 7 — Inset feed distance y₀ for 50 Ω (Balanis eq. 14-22):
        Rin(y₀) = Rin_edge × cos²(π y₀ / L)
        → y₀ = (L/π) × arccos(sqrt(50 / Rin_edge))

    Parameters
    ----------
    freq_hz    : float — design frequency [Hz]
    er         : float — substrate relative permittivity
    h_m        : float — substrate thickness [m]
    efficiency : float — radiation efficiency η (0–1, default 0.90)

    Returns
    -------
    dict: ok, freq_hz, er, er_eff, h_m, patch_width_m, patch_length_m,
          delta_L_m, edge_impedance_ohm, inset_feed_m, gain_dbi, directivity,
          radiation_efficiency, hpbw_e_plane_deg, hpbw_h_plane_deg
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(er, "er")
    if err:
        return {"ok": False, "reason": err}
    if er < 1.0:
        return {"ok": False, "reason": "er must be >= 1.0"}
    err = _pos(h_m, "h_m")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(efficiency, "efficiency")
    if err:
        return {"ok": False, "reason": err}
    if efficiency > 1.0:
        return {"ok": False, "reason": "efficiency must be <= 1.0"}

    lam = _wavelength(freq_hz)
    k0 = 2.0 * math.pi / lam

    # Step 1: Width
    W = (_C / (2.0 * freq_hz)) * math.sqrt(2.0 / (er + 1.0))

    # Step 2: Effective permittivity
    if W / h_m >= 1.0:
        er_eff = ((er + 1.0) / 2.0
                  + (er - 1.0) / 2.0 * (1.0 + 12.0 * h_m / W) ** (-0.5))
    else:
        er_eff = ((er + 1.0) / 2.0
                  + (er - 1.0) / 2.0 * (1.0 + 12.0 * h_m / W) ** (-0.5)
                  + (er - 1.0) / 4.82 * (h_m / W) ** 2)

    # Step 3: Fringing extension
    Wh = W / h_m
    dL_h = 0.412 * ((er_eff + 0.3) * (Wh + 0.264)) / ((er_eff - 0.258) * (Wh + 0.8))
    delta_L = dL_h * h_m

    # Step 4: Patch length
    L = _C / (2.0 * freq_hz * math.sqrt(er_eff)) - 2.0 * delta_L
    if L <= 0:
        return {
            "ok": False,
            "reason": f"Computed patch length L = {L:.6f} m is non-positive; "
                      f"check er / h_m / freq_hz combination.",
        }

    # Step 5: Edge conductance
    k0h = k0 * h_m
    # Validity warning for thick substrates
    if k0h > 0.3:
        warnings.warn(
            f"microstrip_patch: substrate is electrically thick "
            f"(k0h = {k0h:.3f} > 0.3); Hammerstad thin-substrate "
            f"approximation may be inaccurate.",
            stacklevel=2,
        )
    G1 = W / (120.0 * lam) * (1.0 - (k0 * h_m) ** 2 / 24.0)
    if G1 <= 0:
        return {"ok": False, "reason": "Edge conductance G1 computed as non-positive; check inputs."}

    # Step 6: Edge input impedance  (G12 ≈ 0 for narrow patch)
    Rin_edge = 1.0 / (2.0 * G1)

    # Step 7: Inset feed for 50 Ω
    target_z = 50.0
    inset_feed = None
    if Rin_edge >= target_z:
        cos_arg = math.sqrt(target_z / Rin_edge)
        inset_feed = (L / math.pi) * math.acos(cos_arg)
    else:
        warnings.warn(
            f"microstrip_patch: Rin_edge = {Rin_edge:.1f} Ω < 50 Ω; "
            f"inset feed cannot achieve 50 Ω match at the radiating edge. "
            f"Consider a different substrate or dimensions.",
            stacklevel=2,
        )
        inset_feed = 0.0

    # Directivity / gain (Balanis §14.2).
    # The patch radiates from two radiating slots of width W and separation L.
    # Directivity ≈ 6 × W / λ  (Balanis eq. 14-18, valid for W/λ ≈ 0.5)
    # This is the well-known ~6.6 dBi result for a half-wave patch.
    D_approx = 6.0 * W / lam
    D = max(D_approx, 1.5)  # floor at ~ short-dipole directivity
    G = efficiency * D
    G_dBi = 10.0 * math.log10(G)

    # HPBW estimates (simplified from sinc radiation pattern of patch aperture)
    # E-plane HPBW ≈ 2 × arcsin(0.886 λ / L) but clamped; use sinc approx
    hpbw_e_approx = math.degrees(2.0 * math.asin(min(0.886 * lam / L, 1.0))) if L > 0 else 90.0
    hpbw_h_approx = math.degrees(2.0 * math.asin(min(0.886 * lam / W, 1.0))) if W > 0 else 90.0

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "er": er,
        "er_eff": round(er_eff, 5),
        "h_m": h_m,
        "patch_width_m": round(W, 6),
        "patch_length_m": round(L, 6),
        "delta_L_m": round(delta_L, 8),
        "edge_impedance_ohm": round(Rin_edge, 2),
        "inset_feed_m": round(inset_feed, 6) if inset_feed is not None else None,
        "directivity": round(D, 3),
        "gain_dbi": round(G_dBi, 3),
        "radiation_efficiency": efficiency,
        "hpbw_e_plane_deg": round(hpbw_e_approx, 1),
        "hpbw_h_plane_deg": round(hpbw_h_approx, 1),
        "reference": "Balanis (2016) §14.2; Pozar (2012) §6.5",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. Yagi-Uda antenna
# ══════════════════════════════════════════════════════════════════════════════

def yagi_uda(
    freq_hz: float,
    n_directors: int = 3,
    boom_wavelengths: float = 0.4,
    efficiency: float = 0.95,
) -> dict:
    """
    Yagi-Uda antenna design estimator (Balanis §10.3, Kraus Table 11-1).

    Uses empirical scaling laws for element lengths and spacings, then
    estimates gain and front-to-back ratio via Kraus/Stutzman regression curves.

    Element lengths (standard Yagi design, Balanis §10.3):
        Driven element:  L_d = 0.47 λ
        Reflector:       L_r = 0.505 λ
        Directors:       L_di = (0.4 + 0.006 × spacing/λ) λ  (first-order)

    Spacings (recommended defaults per Balanis Table 10.6):
        Reflector–driven: 0.25 λ
        Director spacing: (boom_wavelengths / n_directors) λ (evenly distributed)

    Gain estimate (Kraus eq. 11-4, valid for 3–15 elements, boom 0.2–2 λ):
        G_dBi ≈ 10 × log10(4.15 × N_el × d_avg/λ)
        where N_el = total elements, d_avg = mean element spacing/λ.

    F/B estimate (empirical, ≈ 15–25 dB for typical Yagis):
        F/B ≈ G_dBi + 5   (crude bound; full FDTD gives exact value)

    Parameters
    ----------
    freq_hz         : float — operating frequency [Hz]
    n_directors     : int   — number of director elements (0–10)
    boom_wavelengths : float — total boom length in wavelengths (0.2–3.0)
    efficiency      : float — radiation efficiency η (0–1, default 0.95)

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, n_elements, n_directors,
          driven_length_m, reflector_length_m, director_length_m,
          reflector_spacing_m, director_spacing_m,
          gain_dbi, fb_ratio_db, hpbw_e_plane_deg, boom_length_m,
          radiation_efficiency
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(n_directors, int) or n_directors < 0:
        return {"ok": False, "reason": "n_directors must be a non-negative integer"}
    if n_directors > 10:
        warnings.warn(
            f"yagi_uda: n_directors = {n_directors} > 10; "
            f"empirical gain formula degrades in accuracy beyond 10 directors.",
            stacklevel=2,
        )
    err = _pos(boom_wavelengths, "boom_wavelengths")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(efficiency, "efficiency")
    if err:
        return {"ok": False, "reason": err}
    if efficiency > 1.0:
        return {"ok": False, "reason": "efficiency must be <= 1.0"}

    lam = _wavelength(freq_hz)

    # Element lengths
    L_driven = 0.47 * lam
    L_reflector = 0.505 * lam
    # Director spacing
    refl_spacing = 0.25 * lam
    if n_directors > 0:
        dir_spacing = (boom_wavelengths - 0.25) * lam / max(n_directors, 1)
        if dir_spacing < 0.1 * lam:
            warnings.warn(
                f"yagi_uda: director spacing = {dir_spacing/lam:.3f}λ < 0.1λ; "
                f"consider fewer directors or longer boom.",
                stacklevel=2,
            )
    else:
        dir_spacing = 0.0

    # Director length (depends on spacing, Balanis Table 10.6 first row approximation)
    s_lam = dir_spacing / lam if n_directors > 0 else 0.3
    L_director = (0.4 + 0.006 * s_lam) * lam

    n_elements = 1 + 1 + n_directors   # driven + reflector + directors

    # Gain estimate (Kraus empirical eq.)
    # d_avg = average spacing across all inter-element gaps
    if n_elements > 1:
        d_avg = boom_wavelengths / (n_elements - 1)
    else:
        d_avg = 0.25
    G_linear = 4.15 * n_elements * d_avg
    G = efficiency * G_linear
    G_dBi = 10.0 * math.log10(max(G, 1.0))

    # F/B crude estimate
    fb_db = G_dBi + 5.0  # rough upper bound for well-designed Yagi

    # HPBW (endfire array Balanis §6.8): θ_-3dB ≈ 2 × arcsin(sqrt(2/(N_el × k × d)))
    # Simplified: HPBW ≈ 102 / sqrt(G_linear)
    hpbw_e = 102.0 / math.sqrt(max(G_linear, 1.0))

    boom_length = boom_wavelengths * lam

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "n_elements": n_elements,
        "n_directors": n_directors,
        "driven_length_m": round(L_driven, 6),
        "reflector_length_m": round(L_reflector, 6),
        "director_length_m": round(L_director, 6),
        "reflector_spacing_m": round(refl_spacing, 6),
        "director_spacing_m": round(dir_spacing, 6),
        "boom_length_m": round(boom_length, 6),
        "gain_dbi": round(G_dBi, 2),
        "fb_ratio_db": round(fb_db, 1),
        "hpbw_e_plane_deg": round(hpbw_e, 1),
        "radiation_efficiency": efficiency,
        "reference": "Balanis (2016) §10.3; Kraus (2002) Table 11-1",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. Helical antenna (axial mode)
# ══════════════════════════════════════════════════════════════════════════════

def helical_axial(
    freq_hz: float,
    n_turns: int,
    circumference_wavelengths: float = 1.0,
    pitch_angle_deg: float = 12.5,
    efficiency: float = 0.95,
) -> dict:
    """
    Axial-mode (end-fire) helical antenna design (Balanis §10.4, Kraus §7-5).

    Valid range: 0.75 ≤ C/λ ≤ 1.33, α ≈ 12–14°.

    Dimensions:
        Circumference: C = C_λ × λ
        Pitch: S = C × tan(α) = S_λ × λ  where S_λ = C_λ × tan(α)
        Axial length: A = N × S

    Gain (Kraus approximation, Balanis eq. 10-21):
        G ≈ η × 11.8 × N × C_λ² × S_λ

    Input impedance (Kraus §7-5, empirical):
        R_in ≈ 140 × C_λ   [Ω] (good for 1 ≤ C_λ ≤ 1.3, axial mode)

    HPBW (Kraus eq. 10-12):
        HPBW ≈ 52 / (C_λ × sqrt(N × S_λ))  [degrees]

    Parameters
    ----------
    freq_hz                 : float — operating frequency [Hz]
    n_turns                 : int   — number of helix turns (N ≥ 3)
    circumference_wavelengths : float — helix circumference in λ (default 1.0)
    pitch_angle_deg         : float — pitch angle [degrees] (default 12.5°)
    efficiency              : float — radiation efficiency η (0–1, default 0.95)

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, n_turns, circumference_m, pitch_m,
          axial_length_m, R_in_ohm, gain_dbi, hpbw_deg, axial_ratio,
          radiation_efficiency, in_axial_mode_range
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(n_turns, int) or n_turns < 1:
        return {"ok": False, "reason": "n_turns must be a positive integer"}
    err = _pos(circumference_wavelengths, "circumference_wavelengths")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(pitch_angle_deg, "pitch_angle_deg")
    if err:
        return {"ok": False, "reason": err}
    if pitch_angle_deg >= 90.0:
        return {"ok": False, "reason": "pitch_angle_deg must be < 90°"}
    err = _pos(efficiency, "efficiency")
    if err:
        return {"ok": False, "reason": err}
    if efficiency > 1.0:
        return {"ok": False, "reason": "efficiency must be <= 1.0"}

    lam = _wavelength(freq_hz)
    C_lam = circumference_wavelengths
    alpha_rad = math.radians(pitch_angle_deg)
    S_lam = C_lam * math.tan(alpha_rad)

    in_axial_mode = 0.75 <= C_lam <= 1.33 and 12.0 <= pitch_angle_deg <= 14.0
    if not in_axial_mode:
        warnings.warn(
            f"helical_axial: antenna is OUT of the recommended axial-mode range "
            f"(C/λ={C_lam:.3f}, α={pitch_angle_deg:.1f}°); "
            f"formulas are unreliable outside 0.75 ≤ C/λ ≤ 1.33, 12° ≤ α ≤ 14°.",
            stacklevel=2,
        )

    if n_turns < 3:
        warnings.warn(
            f"helical_axial: n_turns = {n_turns} < 3; axial-mode approximations "
            f"require at least 3 turns.",
            stacklevel=2,
        )

    C_m = C_lam * lam
    S_m = S_lam * lam
    A_m = n_turns * S_m

    # Gain (Kraus / Balanis eq. 10-21)
    G_linear = efficiency * 11.8 * n_turns * C_lam**2 * S_lam
    G_dBi = 10.0 * math.log10(max(G_linear, 1.0))

    # Input impedance (Kraus empirical)
    R_in = 140.0 * C_lam

    # HPBW (Kraus eq. 10-12)
    hpbw_arg = C_lam * math.sqrt(n_turns * S_lam)
    hpbw_deg_val = 52.0 / hpbw_arg if hpbw_arg > 0 else 90.0

    # Axial ratio (for circular polarisation, AR → 1 for large N)
    # AR = (2N + 1) / (2N)   Balanis eq. 10-15
    AR = (2.0 * n_turns + 1.0) / (2.0 * n_turns)

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "n_turns": n_turns,
        "circumference_wavelengths": C_lam,
        "pitch_angle_deg": pitch_angle_deg,
        "circumference_m": round(C_m, 6),
        "pitch_m": round(S_m, 6),
        "axial_length_m": round(A_m, 6),
        "R_in_ohm": round(R_in, 1),
        "gain_dbi": round(G_dBi, 2),
        "hpbw_deg": round(hpbw_deg_val, 1),
        "axial_ratio": round(AR, 5),
        "in_axial_mode_range": in_axial_mode,
        "radiation_efficiency": efficiency,
        "reference": "Balanis (2016) §10.4; Kraus (2002) §7-5",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 7. Horn antenna gain from aperture
# ══════════════════════════════════════════════════════════════════════════════

def horn_gain(
    freq_hz: float,
    aperture_width_m: float,
    aperture_height_m: float,
    aperture_efficiency: float = 0.51,
    efficiency: float = 0.95,
) -> dict:
    """
    Horn antenna gain from aperture dimensions (Balanis §13.2).

    Physical aperture area:
        Ap = a × b

    Effective aperture:
        Aeff = ηap × Ap

    Gain:
        G = η × 4π × Aeff / λ²
          = η × ηap × 4π × a × b / λ²

    HPBW (E-plane and H-plane for a pyramidal horn, Balanis Table 13.1):
        θ_E ≈ 0.886 × λ / b   [rad]
        θ_H ≈ 0.886 × λ / a   [rad]

    Standard optimum pyramidal horn aperture efficiency ηap ≈ 0.51 (Balanis §13.6).

    Parameters
    ----------
    freq_hz            : float — operating frequency [Hz]
    aperture_width_m   : float — aperture width a [m]  (H-plane dimension)
    aperture_height_m  : float — aperture height b [m] (E-plane dimension)
    aperture_efficiency : float — aperture efficiency ηap (default 0.51)
    efficiency         : float — total radiation efficiency η (default 0.95)

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, aperture_width_m, aperture_height_m,
          aperture_efficiency, physical_aperture_m2, effective_aperture_m2,
          gain_dbi, hpbw_e_plane_deg, hpbw_h_plane_deg, radiation_efficiency
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(aperture_width_m, "aperture_width_m")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(aperture_height_m, "aperture_height_m")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(aperture_efficiency, "aperture_efficiency")
    if err:
        return {"ok": False, "reason": err}
    if aperture_efficiency > 1.0:
        return {"ok": False, "reason": "aperture_efficiency must be <= 1.0"}
    err = _pos(efficiency, "efficiency")
    if err:
        return {"ok": False, "reason": err}
    if efficiency > 1.0:
        return {"ok": False, "reason": "efficiency must be <= 1.0"}

    lam = _wavelength(freq_hz)
    Ap = aperture_width_m * aperture_height_m
    Aeff = aperture_efficiency * Ap

    G = efficiency * 4.0 * math.pi * Aeff / lam**2
    G_dBi = 10.0 * math.log10(max(G, 1.0))

    # HPBW
    hpbw_e = math.degrees(0.886 * lam / aperture_height_m)
    hpbw_h = math.degrees(0.886 * lam / aperture_width_m)

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "aperture_width_m": aperture_width_m,
        "aperture_height_m": aperture_height_m,
        "aperture_efficiency": aperture_efficiency,
        "physical_aperture_m2": round(Ap, 8),
        "effective_aperture_m2": round(Aeff, 8),
        "gain_dbi": round(G_dBi, 3),
        "hpbw_e_plane_deg": round(hpbw_e, 2),
        "hpbw_h_plane_deg": round(hpbw_h, 2),
        "radiation_efficiency": efficiency,
        "reference": "Balanis (2016) §13.2, §13.6",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. General: directivity ↔ gain ↔ efficiency
# ══════════════════════════════════════════════════════════════════════════════

def directivity_gain_efficiency(
    *,
    directivity: float = None,
    gain_dbi: float = None,
    efficiency: float = None,
) -> dict:
    """
    Compute the third member of the D / G / η triangle.

    G [linear] = η × D
    G [dBi]   = 10 × log10(η × D)

    Exactly two of the three parameters must be provided.

    Parameters
    ----------
    directivity : float — linear directivity D (must be >= 1.0)
    gain_dbi    : float — gain [dBi]
    efficiency  : float — radiation efficiency η (0 < η ≤ 1.0)

    Returns
    -------
    dict: ok, directivity, gain_dbi, efficiency
    """
    provided = sum(x is not None for x in (directivity, gain_dbi, efficiency))
    if provided != 2:
        return {
            "ok": False,
            "reason": "Exactly 2 of directivity, gain_dbi, efficiency must be provided.",
        }

    if directivity is not None and efficiency is not None:
        # Compute gain
        err = _pos(directivity, "directivity")
        if err:
            return {"ok": False, "reason": err}
        err = _pos(efficiency, "efficiency")
        if err:
            return {"ok": False, "reason": err}
        if efficiency > 1.0:
            return {"ok": False, "reason": "efficiency must be <= 1.0"}
        G = efficiency * directivity
        G_dBi = 10.0 * math.log10(G)
        return {"ok": True, "directivity": directivity, "gain_dbi": round(G_dBi, 5),
                "efficiency": efficiency}

    if gain_dbi is not None and efficiency is not None:
        # Compute directivity
        err = _pos(efficiency, "efficiency")
        if err:
            return {"ok": False, "reason": err}
        if efficiency > 1.0:
            return {"ok": False, "reason": "efficiency must be <= 1.0"}
        if not isinstance(gain_dbi, (int, float)):
            return {"ok": False, "reason": "gain_dbi must be a number"}
        G = 10.0 ** (gain_dbi / 10.0)
        D = G / efficiency
        return {"ok": True, "directivity": round(D, 5), "gain_dbi": gain_dbi,
                "efficiency": efficiency}

    if directivity is not None and gain_dbi is not None:
        # Compute efficiency
        err = _pos(directivity, "directivity")
        if err:
            return {"ok": False, "reason": err}
        if not isinstance(gain_dbi, (int, float)):
            return {"ok": False, "reason": "gain_dbi must be a number"}
        G = 10.0 ** (gain_dbi / 10.0)
        eta = G / directivity
        if not (0.0 < eta <= 1.0):
            warnings.warn(
                f"directivity_gain_efficiency: computed efficiency η = {eta:.4f} "
                f"is outside (0, 1]; check input values.",
                stacklevel=2,
            )
        return {"ok": True, "directivity": directivity, "gain_dbi": gain_dbi,
                "efficiency": round(eta, 6)}

    return {"ok": False, "reason": "Unexpected parameter combination."}


# ══════════════════════════════════════════════════════════════════════════════
# 9. Beamwidth ↔ directivity (Kraus approximation)
# ══════════════════════════════════════════════════════════════════════════════

def beamwidth_directivity(
    hpbw_e_deg: float,
    hpbw_h_deg: float,
) -> dict:
    """
    Estimate directivity from E-plane and H-plane half-power beamwidths.

    Kraus approximation (Kraus eq. 2-27 / Balanis eq. 2-65):
        D ≈ 41253 / (θ_E × θ_H)
    where θ_E, θ_H are in degrees.

    Also returns the Tai–Pereira refined approximation (Balanis eq. 2-68):
        D ≈ 72815 / (θ_E² + θ_H²)

    Parameters
    ----------
    hpbw_e_deg : float — E-plane HPBW [degrees]
    hpbw_h_deg : float — H-plane HPBW [degrees]

    Returns
    -------
    dict: ok, hpbw_e_deg, hpbw_h_deg, directivity_kraus, directivity_tai,
          gain_dbi_kraus, gain_dbi_tai
    """
    err = _pos(hpbw_e_deg, "hpbw_e_deg")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(hpbw_h_deg, "hpbw_h_deg")
    if err:
        return {"ok": False, "reason": err}
    if hpbw_e_deg > 360.0 or hpbw_h_deg > 360.0:
        return {"ok": False, "reason": "HPBW cannot exceed 360°"}

    D_kraus = 41253.0 / (hpbw_e_deg * hpbw_h_deg)
    D_tai   = 72815.0 / (hpbw_e_deg**2 + hpbw_h_deg**2)

    return {
        "ok": True,
        "hpbw_e_deg": hpbw_e_deg,
        "hpbw_h_deg": hpbw_h_deg,
        "directivity_kraus": round(D_kraus, 4),
        "directivity_tai": round(D_tai, 4),
        "gain_dbi_kraus": round(10.0 * math.log10(max(D_kraus, 1.0)), 3),
        "gain_dbi_tai": round(10.0 * math.log10(max(D_tai, 1.0)), 3),
        "reference": "Kraus (2002) eq. 2-27; Balanis (2016) eq. 2-65/2-68",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 10. Aperture efficiency and effective aperture
# ══════════════════════════════════════════════════════════════════════════════

def aperture_efficiency(
    freq_hz: float,
    gain_dbi: float,
    physical_aperture_m2: float = None,
) -> dict:
    """
    Effective aperture and aperture efficiency from gain and frequency.

    Aeff = G × λ² / (4π)

    If physical_aperture_m2 is provided:
        ηap = Aeff / Ap

    Parameters
    ----------
    freq_hz              : float — frequency [Hz]
    gain_dbi             : float — antenna gain [dBi]
    physical_aperture_m2 : float — physical aperture area [m²] (optional)

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, gain_dbi, effective_aperture_m2,
          physical_aperture_m2 (if provided), aperture_efficiency (if Ap given)
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(gain_dbi, (int, float)):
        return {"ok": False, "reason": "gain_dbi must be a number"}

    lam = _wavelength(freq_hz)
    G = 10.0 ** (gain_dbi / 10.0)
    Aeff = G * lam**2 / (4.0 * math.pi)

    result = {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "gain_dbi": gain_dbi,
        "effective_aperture_m2": round(Aeff, 10),
    }

    if physical_aperture_m2 is not None:
        err = _pos(physical_aperture_m2, "physical_aperture_m2")
        if err:
            return {"ok": False, "reason": err}
        eta_ap = Aeff / physical_aperture_m2
        result["physical_aperture_m2"] = physical_aperture_m2
        result["aperture_efficiency"] = round(eta_ap, 5)

    result["reference"] = "Balanis (2016) §2.8"
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 11. Near/far-field (Fraunhofer) boundary
# ══════════════════════════════════════════════════════════════════════════════

def near_far_field_boundary(
    freq_hz: float,
    max_dimension_m: float,
) -> dict:
    """
    Near-field / far-field boundary distances (Balanis §2.2.4).

    Reactive near-field:       R < 0.62 × sqrt(D³/λ)
    Radiating near-field:      0.62 sqrt(D³/λ) ≤ R < 2D²/λ
    Far-field (Fraunhofer):    R ≥ 2D²/λ

    Also returns the plane-wave boundary R_pw = λ/(2π) used in EMC.

    Parameters
    ----------
    freq_hz          : float — operating frequency [Hz]
    max_dimension_m  : float — maximum antenna dimension D [m]

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, max_dimension_m,
          reactive_near_field_m, radiating_near_field_boundary_m,
          fraunhofer_distance_m, plane_wave_boundary_m
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(max_dimension_m, "max_dimension_m")
    if err:
        return {"ok": False, "reason": err}

    lam = _wavelength(freq_hz)
    D = max_dimension_m

    r_reactive  = 0.62 * math.sqrt(D**3 / lam)
    r_fraunhofer = 2.0 * D**2 / lam
    r_pw = lam / (2.0 * math.pi)

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "max_dimension_m": max_dimension_m,
        "reactive_near_field_m": round(r_reactive, 6),
        "radiating_near_field_boundary_m": round(r_reactive, 6),
        "fraunhofer_distance_m": round(r_fraunhofer, 6),
        "plane_wave_boundary_m": round(r_pw, 6),
        "reference": "Balanis (2016) §2.2.4",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 12. Polarisation & axial ratio → polarisation loss factor
# ══════════════════════════════════════════════════════════════════════════════

def polarization_axial_ratio(
    axial_ratio: float,
    tilt_angle_deg: float = 0.0,
) -> dict:
    """
    Polarisation loss factor (PLF) from axial ratio (Balanis §2.12).

    Axial ratio AR = |E_major / E_minor| (AR = 1 → circular, AR = ∞ → linear).

    Polarisation loss factor (worst-case mismatch):
        PLF_min = ((AR − 1) / (AR + 1))²
        PLF_max = 1.0  (perfect alignment)

    For circular-to-linear:
        PLF = 0.5  (3 dB polarisation loss)

    For linear-to-linear with tilt angle τ:
        PLF = cos²(τ)

    Parameters
    ----------
    axial_ratio    : float — axial ratio (>= 1.0; 1 = circular, large = linear)
    tilt_angle_deg : float — linear polarisation tilt angle [degrees] (default 0)

    Returns
    -------
    dict: ok, axial_ratio, tilt_angle_deg, plf_worst_case,
          plf_loss_db_worst, plf_linear_tilt, is_circular, is_linear
    """
    err = _nonneg(axial_ratio - 1.0, "axial_ratio - 1")
    if axial_ratio < 1.0:
        return {"ok": False, "reason": "axial_ratio must be >= 1.0 (AR = E_max/E_min)"}

    is_circular = axial_ratio <= 1.05
    is_linear   = axial_ratio >= 100.0

    plf_worst = ((axial_ratio - 1.0) / (axial_ratio + 1.0)) ** 2
    plf_worst_db = 10.0 * math.log10(max(plf_worst, 1e-30))

    tau_rad = math.radians(tilt_angle_deg)
    plf_linear = math.cos(tau_rad) ** 2

    return {
        "ok": True,
        "axial_ratio": axial_ratio,
        "tilt_angle_deg": tilt_angle_deg,
        "plf_worst_case": round(plf_worst, 6),
        "plf_loss_db_worst": round(plf_worst_db, 3),
        "plf_linear_tilt": round(plf_linear, 6),
        "is_circular": is_circular,
        "is_linear": is_linear,
        "reference": "Balanis (2016) §2.12",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 13. Ground-plane image effect (monopole over ground)
# ══════════════════════════════════════════════════════════════════════════════

def ground_plane_image(
    dipole_R_in_ohm: float,
    dipole_X_in_ohm: float,
    dipole_gain_dbi: float,
) -> dict:
    """
    Image-theory effect of an infinite ground plane on a monopole over ground.

    From image theory (Balanis §4.7):
        R_monopole = R_dipole / 2
        X_monopole = X_dipole / 2
        D_monopole = 2 × D_dipole  (radiation only into upper half-space)

    Parameters
    ----------
    dipole_R_in_ohm : float — dipole input resistance [Ω]
    dipole_X_in_ohm : float — dipole input reactance [Ω]
    dipole_gain_dbi : float — dipole gain [dBi]

    Returns
    -------
    dict: ok, monopole_R_in_ohm, monopole_X_in_ohm, monopole_gain_dbi,
          monopole_directivity_vs_dipole_db
    """
    err = _pos(dipole_R_in_ohm, "dipole_R_in_ohm")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(dipole_X_in_ohm, (int, float)):
        return {"ok": False, "reason": "dipole_X_in_ohm must be a number"}
    if not isinstance(dipole_gain_dbi, (int, float)):
        return {"ok": False, "reason": "dipole_gain_dbi must be a number"}

    mono_R = dipole_R_in_ohm / 2.0
    mono_X = dipole_X_in_ohm / 2.0
    # D_monopole = 2 × D_dipole  → gain_dBi increases by 3 dB
    mono_G_dBi = dipole_gain_dbi + 3.01

    return {
        "ok": True,
        "monopole_R_in_ohm": round(mono_R, 3),
        "monopole_X_in_ohm": round(mono_X, 3),
        "monopole_gain_dbi": round(mono_G_dBi, 3),
        "monopole_directivity_vs_dipole_db": 3.01,
        "reference": "Balanis (2016) §4.7; image theory",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 14. Uniform linear array factor (ULA)
# ══════════════════════════════════════════════════════════════════════════════

def array_factor_ula(
    freq_hz: float,
    n_elements: int,
    element_spacing_m: float,
    scan_angle_deg: float = 0.0,
    check_grating_lobes: bool = True,
) -> dict:
    """
    Uniform linear array (ULA) factor and beam-steering analysis (Balanis §6.2).

    Array factor (N isotropic elements, uniform excitation, spacing d):
        AF(θ) = sum_{n=0}^{N-1} exp(jn × (k d cos θ + β))
              = sin(N ψ/2) / (N sin(ψ/2))   [normalised]
    where ψ = k d cos θ + β, β = −k d cos θ₀ (scan phase).

    Grating-lobe condition (Balanis §6.2):
        Grating lobe occurs when d / λ >= 1 / (1 + |cos θ₀|)
        For broadside (θ₀=90°): d/λ >= 1.0
        For endfire (θ₀=0°):    d/λ >= 0.5

    Returns AF vs θ (sampled at 1° intervals), null positions, and
    the main-lobe HPBW for the scanned beam.

    Parameters
    ----------
    freq_hz            : float — operating frequency [Hz]
    n_elements         : int   — number of array elements N
    element_spacing_m  : float — element spacing d [m]
    scan_angle_deg     : float — main-beam scan angle θ₀ [degrees] (default 0 = endfire)
    check_grating_lobes : bool — issue warning if grating lobes present (default True)

    Returns
    -------
    dict: ok, freq_hz, wavelength_m, n_elements, element_spacing_m,
          element_spacing_wavelengths, scan_angle_deg, array_gain_dbi,
          hpbw_deg, grating_lobe_present, grating_lobe_angles_deg,
          null_angles_deg
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(n_elements, int) or n_elements < 1:
        return {"ok": False, "reason": "n_elements must be a positive integer"}
    err = _pos(element_spacing_m, "element_spacing_m")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(scan_angle_deg, (int, float)):
        return {"ok": False, "reason": "scan_angle_deg must be a number"}

    lam = _wavelength(freq_hz)
    k = 2.0 * math.pi / lam
    d_lam = element_spacing_m / lam

    theta0_rad = math.radians(scan_angle_deg)
    # Inter-element phase for scan
    beta = -k * element_spacing_m * math.cos(theta0_rad)

    # Grating lobe check
    cos_t0 = math.cos(theta0_rad)
    gl_threshold = 1.0 / (1.0 + abs(cos_t0))
    grating_lobe_present = d_lam >= gl_threshold

    grating_lobe_angles = []
    if grating_lobe_present and check_grating_lobes:
        # Find grating lobe positions: k d cos(θ_gl) + β = ±2π m, m=1,2,...
        for m in range(1, 5):
            for sign in (1, -1):
                arg = (sign * 2.0 * math.pi * m - beta) / (k * element_spacing_m)
                if -1.0 <= arg <= 1.0:
                    angle_gl = math.degrees(math.acos(arg))
                    if abs(angle_gl - scan_angle_deg) > 5.0:
                        grating_lobe_angles.append(round(angle_gl, 1))
        warnings.warn(
            f"array_factor_ula: GRATING LOBE(S) present at d/λ = {d_lam:.3f} "
            f"(threshold {gl_threshold:.3f}) for scan angle {scan_angle_deg}°. "
            f"Grating lobe angles: {grating_lobe_angles}",
            stacklevel=2,
        )

    # Null positions: ψ = ±2πm/N → cos(θ_null) = (∓2πm/N − β) / (kd)
    null_angles = []
    for m in range(1, n_elements):
        for sign in (1, -1):
            psi_null = sign * 2.0 * math.pi * m / n_elements
            arg = (psi_null - beta) / (k * element_spacing_m)
            if -1.0 <= arg <= 1.0:
                a_deg = round(math.degrees(math.acos(arg)), 1)
                if a_deg not in null_angles and abs(a_deg - scan_angle_deg) > 1.0:
                    null_angles.append(a_deg)

    # Array gain over isotropic: G = N (coherent addition)
    array_gain_dBi = 10.0 * math.log10(n_elements)

    # HPBW (Balanis §6.2): HPBW ≈ 2 × arcsin(0.886 λ / (N d sin θ₀))
    # Broadside (θ₀=90°): HPBW ≈ 0.886 λ / (N d) [rad]
    sin_t0 = math.sin(theta0_rad)
    if abs(sin_t0) > 0.01:
        hpbw_rad = 2.0 * math.asin(min(0.886 * lam / (n_elements * element_spacing_m * abs(sin_t0)), 1.0))
    else:
        # Endfire case: HPBW ≈ 2 arccos(1 - 0.886λ/(Nd))
        arg_endo = 1.0 - 0.886 * lam / (n_elements * element_spacing_m + 1e-30)
        arg_endo = max(-1.0, min(1.0, arg_endo))
        hpbw_rad = 2.0 * math.acos(arg_endo)

    hpbw_deg_val = math.degrees(hpbw_rad)

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "wavelength_m": round(lam, 6),
        "n_elements": n_elements,
        "element_spacing_m": element_spacing_m,
        "element_spacing_wavelengths": round(d_lam, 5),
        "scan_angle_deg": scan_angle_deg,
        "inter_element_phase_rad": round(beta, 5),
        "array_gain_dbi": round(array_gain_dBi, 3),
        "hpbw_deg": round(hpbw_deg_val, 2),
        "grating_lobe_present": grating_lobe_present,
        "grating_lobe_angles_deg": sorted(set(grating_lobe_angles)),
        "null_angles_deg": sorted(set(null_angles)),
        "reference": "Balanis (2016) §6.2",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 15. VSWR bandwidth from Q
# ══════════════════════════════════════════════════════════════════════════════

def vswr_bandwidth_from_q(
    freq_hz: float,
    q_factor: float,
    vswr_limit: float = 2.0,
) -> dict:
    """
    Fractional impedance bandwidth from antenna Q and VSWR limit.

    For a series-resonant antenna with quality factor Q and target VSWR S:
        BW_fraction = (S − 1) / (Q × sqrt(S))   [Balanis §11.4 / Yaghjian & Best 2005]

    Also known as the Chu–Harrington limit bound when Q = Q_Chu.

    Parameters
    ----------
    freq_hz    : float — centre frequency [Hz]
    q_factor   : float — antenna quality factor Q (> 0)
    vswr_limit : float — VSWR threshold (>= 1.0, default 2.0)

    Returns
    -------
    dict: ok, freq_hz, q_factor, vswr_limit, bw_fraction,
          bw_hz, bw_lower_hz, bw_upper_hz, return_loss_db
    """
    err = _pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(q_factor, "q_factor")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(vswr_limit, (int, float)) or vswr_limit < 1.0:
        return {"ok": False, "reason": "vswr_limit must be >= 1.0"}

    S = vswr_limit
    bw_fraction = (S - 1.0) / (q_factor * math.sqrt(S))
    bw_hz = bw_fraction * freq_hz
    f_lo = freq_hz - bw_hz / 2.0
    f_hi = freq_hz + bw_hz / 2.0

    # Return loss at VSWR = S
    Gamma = (S - 1.0) / (S + 1.0)
    rl_db = -20.0 * math.log10(Gamma) if Gamma > 0 else math.inf

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "q_factor": q_factor,
        "vswr_limit": vswr_limit,
        "bw_fraction": round(bw_fraction, 6),
        "bw_hz": round(bw_hz, 1),
        "bw_lower_hz": round(f_lo, 1),
        "bw_upper_hz": round(f_hi, 1),
        "return_loss_db": round(rl_db, 3),
        "reference": "Yaghjian & Best (2005); Balanis (2016) §11.4",
    }
