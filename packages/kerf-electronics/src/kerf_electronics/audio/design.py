"""
Audio electronics and loudspeaker design — closed-form models.

This module is distinct from:
  • kerf_electronics.afilter   — generic analog filter design
  • kerf_electronics.dsp       — digital signal processing
  • kerf_electronics.sensorcond — sensor conditioning
  • kerf_electronics.powerconv — switching-mode power converters

All functions are pure Python (math/cmath only) and follow the kerf
never-raise contract: validation errors return {"ok": False, "reason": str};
limit exceedances / clipping / over-excursion are reported via
warnings.warn; exceptions are never raised to callers.

References
----------
Self, D. — "Audio Power Amplifier Design Handbook" (5th ed., 2009)
Leach, W.M. — "Introduction to Electroacoustics and Audio Amplifier Design"
Thiele, A.N. — "Loudspeakers in Vented Boxes" (1971)
Small, R.H. — "Vented-Box Loudspeaker Systems" (1973)
Linkwitz, S. — Linkwitz-Riley filter derivation (1976)
Zverev, A.I. — "Handbook of Filter Synthesis" (1967)
Beranek, L.L. — "Acoustics" (2nd ed., 1993)

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Optional

# ── Physical constants ─────────────────────────────────────────────────────────
_PI = math.pi
_SPL_REF = 20e-6          # reference sound pressure 20 μPa (0 dB SPL)
_RHO_AIR = 1.20           # air density [kg/m³] at ~20 °C
_C_AIR = 343.0            # speed of sound in air [m/s] at ~20 °C


# ── Input validation helpers ───────────────────────────────────────────────────

def _vp(value, name: str) -> Optional[str]:
    """Validate positive real number. Return error string or None."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive number, got {value!r}"
    return None


def _vnn(value, name: str) -> Optional[str]:
    """Validate non-negative real number. Return error string or None."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _vr(value, name: str) -> Optional[str]:
    """Validate any real number (may be negative). Return error string or None."""
    if not isinstance(value, (int, float)) or math.isnan(value):
        return f"{name} must be a real number, got {value!r}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Power Amplifier Classes
# ═══════════════════════════════════════════════════════════════════════════════


def amp_class_a(
    vcc: float,
    rl: float,
    iq_factor: float = 1.0,
) -> dict:
    """
    Class-A amplifier analysis (single-ended, resistive bias current).

    The quiescent current is set so the output can swing rail-to-rail:
        Iq = Vcc / (2 * RL)   (minimum for full swing)
    multiplied by iq_factor (default 1.0 = minimum quiescent).

    Power relationships (Self §2.2):
        Pout_max  = Vcc² / (8 * RL)          [peak sinusoidal into RL]
        Psupply   = Vcc * Iq                  [constant regardless of output]
        Pdiss     = Psupply − Pout            [device dissipation at Pout]
        Pdiss_max = Psupply                   [at zero signal, worst case]
        η         = Pout / Psupply
        η_max     = 25 %  (theoretical peak for class A with resistive bias)

    Parameters
    ----------
    vcc       : float — supply voltage [V] (single-rail; symmetric ±Vcc → use Vcc peak)
    rl        : float — load resistance [Ω]
    iq_factor : float — Iq multiplier ≥ 1.0 (default 1.0 = minimum for full swing)

    Returns
    -------
    dict : ok, vcc, rl, iq_a, pout_max_w, psupply_w, pdiss_max_w,
           pdiss_at_pout_max_w, efficiency_max_pct, efficiency_at_pout_max_pct
    """
    for name, val in [("vcc", vcc), ("rl", rl)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}
    if not isinstance(iq_factor, (int, float)) or math.isnan(iq_factor) or iq_factor < 1.0:
        return {"ok": False, "reason": f"iq_factor must be >= 1.0, got {iq_factor!r}"}

    iq = iq_factor * vcc / (2.0 * rl)
    psupply = vcc * iq
    pout_max = vcc ** 2 / (8.0 * rl)
    pdiss_max = psupply          # worst case: zero signal
    pdiss_at_pout_max = psupply - pout_max
    eff_max = (pout_max / psupply) * 100.0 if psupply > 0 else 0.0
    eff_at_pout = eff_max  # occurs at the same point for ideal class A

    if eff_max > 25.1:
        warnings.warn(
            f"amp_class_a: efficiency {eff_max:.1f}% exceeds theoretical class-A "
            "maximum of 25%. Check iq_factor.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "vcc": vcc,
        "rl": rl,
        "iq_factor": iq_factor,
        "iq_a": round(iq, 6),
        "psupply_w": round(psupply, 4),
        "pout_max_w": round(pout_max, 4),
        "pdiss_max_w": round(pdiss_max, 4),
        "pdiss_at_pout_max_w": round(pdiss_at_pout_max, 4),
        "efficiency_max_pct": round(eff_max, 2),
        "efficiency_at_pout_max_pct": round(eff_at_pout, 2),
        "note": "Ideal class-A (resistive bias). Theoretical η_max = 25%.",
    }


def amp_class_b(
    vcc: float,
    rl: float,
) -> dict:
    """
    Class-B push-pull amplifier analysis (complementary pair, ideal).

    Power relationships (Self §3.2 / Leach §5.3):
        Pout_max  = Vcc² / (2 * RL)          [peak sine into RL]
        Psupply   = (2/π) × (Vcc / RL) × Vpk [function of output amplitude Vpk]
        At Pout_max (Vpk = Vcc):
            Psupply = 2 × Vcc² / (π × RL)
        Pdiss_max per device:
            occurs at Vpk = Vcc/√2  →  dPdiss/dVpk = 0
            Pdiss_per_device_max = Vcc² / (π² × RL)
        η_max = π/4 ≈ 78.54 %   (at full output power)
        η_at_pout_max is the same as η_max for ideal class B.

    Parameters
    ----------
    vcc : float — single-rail supply voltage [V]
    rl  : float — load resistance [Ω]

    Returns
    -------
    dict : ok, vcc, rl, pout_max_w, psupply_at_pout_max_w,
           pdiss_per_device_max_w, vpk_at_worst_dissipation_v,
           efficiency_max_pct
    """
    for name, val in [("vcc", vcc), ("rl", rl)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    pout_max = vcc ** 2 / (2.0 * rl)
    # Supply at full output (Vpk = Vcc)
    psupply_at_pout_max = 2.0 * vcc ** 2 / (_PI * rl)
    eff_max = (_PI / 4.0) * 100.0   # 78.539...%
    # Worst-case dissipation per device: Vpk_worst = Vcc/π
    vpk_worst = vcc / _PI
    pdiss_per_device_max = vcc ** 2 / (_PI ** 2 * rl)

    return {
        "ok": True,
        "vcc": vcc,
        "rl": rl,
        "pout_max_w": round(pout_max, 4),
        "psupply_at_pout_max_w": round(psupply_at_pout_max, 4),
        "pdiss_per_device_max_w": round(pdiss_per_device_max, 4),
        "vpk_at_worst_dissipation_v": round(vpk_worst, 4),
        "efficiency_max_pct": round(eff_max, 4),
        "note": (
            "Ideal class-B push-pull. Theoretical η_max = π/4 ≈ 78.54%. "
            "Worst-case device dissipation at Vpk = Vcc/π."
        ),
    }


def amp_class_ab(
    vcc: float,
    rl: float,
    vq: float = 0.65,
) -> dict:
    """
    Class-AB amplifier analysis (approximate, crossover-quiescent bias).

    Class AB lies between A and B. A small quiescent bias Vq across the
    emitter resistors (or equivalent) reduces crossover distortion.
    The quiescent current Iq ≈ Vq / (2 * Re) is device-specific; here
    vq is the differential quiescent forward-bias voltage in V.

    Approximation: efficiency and dissipation are bounded by class A (lower
    eff) and class B (upper eff).  This function returns both bounds and the
    midpoint as an estimate.

    Pout_max   = Vcc² / (2 × RL)     [same as class B, assuming rail-to-rail]
    η_min      = η_class_A = 25 %    [lower bound]
    η_max      = η_class_B = 78.54 % [upper bound]
    η_estimate = 0.6 × η_max        [typical class AB, Self §4)

    Parameters
    ----------
    vcc : float — supply voltage [V]
    rl  : float — load resistance [Ω]
    vq  : float — quiescent bias voltage [V] (default 0.65 V, one diode drop)

    Returns
    -------
    dict : ok, vcc, rl, vq, pout_max_w, efficiency_lower_pct,
           efficiency_upper_pct, efficiency_estimate_pct
    """
    for name, val in [("vcc", vcc), ("rl", rl)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}
    err = _vnn(vq, "vq")
    if err:
        return {"ok": False, "reason": err}

    pout_max = vcc ** 2 / (2.0 * rl)
    eff_lower = 25.0           # class A bound
    eff_upper = (_PI / 4.0) * 100.0  # class B bound ≈ 78.54%
    eff_est = 0.60 * eff_upper  # typical AB

    return {
        "ok": True,
        "vcc": vcc,
        "rl": rl,
        "vq": vq,
        "pout_max_w": round(pout_max, 4),
        "efficiency_lower_pct": round(eff_lower, 2),
        "efficiency_upper_pct": round(eff_upper, 4),
        "efficiency_estimate_pct": round(eff_est, 2),
        "note": (
            "Class-AB efficiency is bounded by class A (25%) and class B (78.54%). "
            "Estimate ≈ 60% of class-B upper bound (typical practical class AB, Self §4)."
        ),
    }


def amp_class_d(
    vcc: float,
    rl: float,
    fsw_hz: float,
    dead_time_ns: float = 50.0,
    lc_order: int = 2,
) -> dict:
    """
    Class-D switching amplifier analysis.

    Ideal efficiency: η = π²/8 ≈ 100% (no switching losses, no dead-time loss).
    Practical efficiency is reduced by:
      1. Dead-time loss: during dead time td, the half-bridge output is clamped
         by the body diodes; this introduces a voltage drop ΔV = Vcc × (2×td×fsw).
         Power loss: Pdead ≈ Pout × 2 × td × fsw  (first-order).
      2. Switching loss: not modelled here; use gate-drive module.

    LC reconstruction filter (2nd-order Butterworth, -3 dB at fb):
        L = RL / (2 × π × fb × Q)   with Q = 1/√2 (Butterworth)
        C = 1 / (RL × 2 × π × fb × Q)

    Default filter bandwidth: fb = fsw / 10 (rule of thumb for 60 dB attenuation).
    Filter order selectable: 2 (standard LC) only; higher orders → note.

    Output power (ideal, into RL):
        Pout_max = Vcc² / (2 × RL)

    Parameters
    ----------
    vcc          : float — supply voltage [V]
    rl           : float — load resistance [Ω]
    fsw_hz       : float — switching frequency [Hz]
    dead_time_ns : float — half-bridge dead time [ns] (default 50 ns)
    lc_order     : int   — LC filter order (currently only 2 supported)

    Returns
    -------
    dict : ok, vcc, rl, fsw_hz, dead_time_ns, pout_max_w,
           efficiency_ideal_pct, dead_time_loss_pct, efficiency_est_pct,
           filter_L_H, filter_C_F, filter_fb_hz
    """
    for name, val in [("vcc", vcc), ("rl", rl), ("fsw_hz", fsw_hz)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}
    err = _vnn(dead_time_ns, "dead_time_ns")
    if err:
        return {"ok": False, "reason": err}
    if lc_order != 2:
        return {"ok": False, "reason": "lc_order must be 2 (higher orders not yet supported)"}

    pout_max = vcc ** 2 / (2.0 * rl)
    eff_ideal = 100.0  # ignoring all losses

    td_s = dead_time_ns * 1e-9
    dead_loss_frac = 2.0 * td_s * fsw_hz        # fraction of Pout lost to dead time
    dead_loss_pct = dead_loss_frac * 100.0
    eff_est = max(0.0, eff_ideal - dead_loss_pct)

    if dead_loss_pct > 20.0:
        warnings.warn(
            f"amp_class_d: dead-time loss {dead_loss_pct:.1f}% is unusually high "
            f"(dead_time_ns={dead_time_ns}, fsw_hz={fsw_hz:.0f}). "
            "Consider reducing dead time or switching frequency.",
            stacklevel=2,
        )

    # LC reconstruction filter (2nd-order Butterworth)
    fb = fsw_hz / 10.0
    q = 1.0 / math.sqrt(2.0)      # Butterworth Q
    omega_b = 2.0 * _PI * fb
    filt_L = rl / (omega_b * q)
    filt_C = 1.0 / (rl * omega_b * q)

    return {
        "ok": True,
        "vcc": vcc,
        "rl": rl,
        "fsw_hz": fsw_hz,
        "dead_time_ns": dead_time_ns,
        "lc_order": lc_order,
        "pout_max_w": round(pout_max, 4),
        "efficiency_ideal_pct": round(eff_ideal, 2),
        "dead_time_loss_pct": round(dead_loss_pct, 4),
        "efficiency_est_pct": round(eff_est, 4),
        "filter_fb_hz": round(fb, 2),
        "filter_L_H": filt_L,
        "filter_C_F": filt_C,
        "note": (
            "Ideal class-D efficiency = 100%. Practical efficiency reduced by "
            "dead-time and switching losses. LC filter is 2nd-order Butterworth "
            "with fb = fsw/10."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Heatsink Thermal Resistance
# ═══════════════════════════════════════════════════════════════════════════════


def heatsink_rth(
    pdiss_w: float,
    tj_max_c: float,
    ta_c: float,
    rth_jc: float,
    rth_cs: float = 0.5,
) -> dict:
    """
    Required heatsink thermal resistance for a given power dissipation.

    Thermal model (junction-to-ambient):
        Tj = Ta + Pdiss × (Rth_jc + Rth_cs + Rth_sa)

    Solving for Rth_sa:
        Rth_sa = (Tj_max - Ta) / Pdiss - Rth_jc - Rth_cs

    Parameters
    ----------
    pdiss_w   : float — device power dissipation [W]
    tj_max_c  : float — maximum junction temperature [°C]
    ta_c      : float — ambient temperature [°C]
    rth_jc    : float — junction-to-case thermal resistance [°C/W]
    rth_cs    : float — case-to-heatsink (interface) thermal resistance [°C/W]
                        default 0.5 °C/W (typical TO-247 with compound)

    Returns
    -------
    dict : ok, pdiss_w, tj_max_c, ta_c, rth_jc, rth_cs, rth_sa_required,
           tj_actual_c
    """
    for name, val in [("pdiss_w", pdiss_w), ("tj_max_c", tj_max_c)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}
    for name, val in [("rth_jc", rth_jc), ("rth_cs", rth_cs)]:
        err = _vnn(val, name)
        if err:
            return {"ok": False, "reason": err}
    err = _vr(ta_c, "ta_c")
    if err:
        return {"ok": False, "reason": err}

    if ta_c >= tj_max_c:
        return {
            "ok": False,
            "reason": f"ta_c ({ta_c} °C) must be less than tj_max_c ({tj_max_c} °C)",
        }

    rth_sa = (tj_max_c - ta_c) / pdiss_w - rth_jc - rth_cs
    tj_actual = ta_c + pdiss_w * (rth_jc + rth_cs + max(rth_sa, 0.0))

    if rth_sa < 0.0:
        warnings.warn(
            f"heatsink_rth: required Rth_sa = {rth_sa:.3f} °C/W is negative — "
            "junction-to-case losses alone exceed the thermal budget. "
            "Reduce Pdiss or increase Tj_max.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "pdiss_w": pdiss_w,
        "tj_max_c": tj_max_c,
        "ta_c": ta_c,
        "rth_jc": rth_jc,
        "rth_cs": rth_cs,
        "rth_sa_required_c_per_w": round(rth_sa, 4),
        "tj_actual_c": round(tj_actual, 2),
        "note": "Rth_sa < 0 means the package alone cannot meet the thermal budget.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Thiele-Small — Sealed Box
# ═══════════════════════════════════════════════════════════════════════════════


def sealed_box(
    vas_l: float,
    qts: float,
    fs_hz: float,
    qtc: float = 0.707,
) -> dict:
    """
    Sealed loudspeaker enclosure alignment (Thiele-Small).

    For a target system Q (Qtc), the required box volume is:

        α = (Qtc / Qts)² − 1              [compliance ratio]
        Vb = Vas / α                       [box volume]
        f3 = fc × sqrt(Qtc² − 0.5 +
             sqrt((Qtc² − 0.5)² + 0.25))   [−3 dB frequency]
        fc = fs × sqrt(α + 1)              [system resonance]
        Qmc = Qtc (for purely resistively loaded box)

    Common Qtc targets:
        0.5   — maximally flat group delay (Bessel equivalent)
        0.707 — Butterworth (maximally flat amplitude, −3 dB at fc)
        1.0   — slight bass boost (+3 dB peak, extended bass)

    Parameters
    ----------
    vas_l   : float — equivalent compliance volume [litres]
    qts     : float — total driver Q at fs (dimensionless)
    fs_hz   : float — driver free-air resonance frequency [Hz]
    qtc     : float — target system Q (default 0.707 Butterworth)

    Returns
    -------
    dict : ok, vas_l, qts, fs_hz, qtc, vb_l, fc_hz, f3_hz, alpha
    """
    for name, val in [("vas_l", vas_l), ("qts", qts), ("fs_hz", fs_hz), ("qtc", qtc)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    if qtc <= qts:
        return {
            "ok": False,
            "reason": (
                f"qtc ({qtc}) must be > qts ({qts}): the box can only raise system Q "
                "above the free-air Qts."
            ),
        }

    alpha = (qtc / qts) ** 2 - 1.0
    vb_l = vas_l / alpha
    fc_hz = fs_hz * math.sqrt(alpha + 1.0)
    # f3 of 2nd-order high-pass with Q = Qtc:
    # H(s) = s²/(s² + s/Qtc + 1); -3 dB when |H(jΩ)| = 1/√2
    # Ω_3dB = sqrt(1 - 1/(2*Qtc²) + sqrt((1 - 1/(2*Qtc²))² + 1)) ... simplified:
    q = qtc
    inner = q ** 2 - 0.5
    omega_3 = math.sqrt(inner + math.sqrt(inner ** 2 + 0.25))
    f3_hz = fc_hz * omega_3

    if vb_l < 1.0:
        warnings.warn(
            f"sealed_box: Vb = {vb_l:.2f} L is very small. "
            "Check driver parameters and target Qtc.",
            stacklevel=2,
        )
    if qtc > 1.2:
        warnings.warn(
            f"sealed_box: Qtc = {qtc:.2f} > 1.2; significant bass hump expected.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "vas_l": vas_l,
        "qts": qts,
        "fs_hz": fs_hz,
        "qtc": qtc,
        "alpha": round(alpha, 6),
        "vb_l": round(vb_l, 4),
        "fc_hz": round(fc_hz, 3),
        "f3_hz": round(f3_hz, 3),
        "note": (
            "Sealed box Thiele-Small alignment. "
            "Qtc=0.707 → Butterworth. Qtc=0.5 → max flat group delay."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Thiele-Small — Vented (Bass-Reflex) Box
# ═══════════════════════════════════════════════════════════════════════════════

# QB3 and SBB4 normalised alignment tables (Vb/Vas, fb/fs) from
# Small (1973) "Vented-Box Loudspeaker Systems" Part I, Table II/III.
# Indexed by Qts in steps: only key Qts values are stored; interpolation is linear.

_QB3_TABLE = {
    # Qts : (alpha = Vas/Vb, fb/fs)
    0.20: (8.80, 1.000),
    0.25: (5.29, 0.990),
    0.30: (3.38, 0.975),
    0.35: (2.27, 0.960),
    0.40: (1.58, 0.946),
    0.45: (1.13, 0.931),
    0.50: (0.82, 0.918),
}

_SBB4_TABLE = {
    # Qts : (alpha, fb/fs)
    0.20: (10.0, 1.000),
    0.25: (6.26, 0.990),
    0.30: (4.06, 0.975),
    0.35: (2.72, 0.958),
    0.40: (1.87, 0.941),
    0.45: (1.33, 0.923),
    0.50: (0.97, 0.907),
}


def _interpolate_table(table: dict, qts: float):
    """Linear interpolation in a Qts-indexed table. Returns (alpha, fb_ratio)."""
    keys = sorted(table.keys())
    if qts <= keys[0]:
        return table[keys[0]]
    if qts >= keys[-1]:
        return table[keys[-1]]
    for i in range(len(keys) - 1):
        k0, k1 = keys[i], keys[i + 1]
        if k0 <= qts <= k1:
            t = (qts - k0) / (k1 - k0)
            a0, r0 = table[k0]
            a1, r1 = table[k1]
            return (a0 + t * (a1 - a0), r0 + t * (r1 - r0))
    return table[keys[-1]]


def vented_box(
    vas_l: float,
    qts: float,
    fs_hz: float,
    re_ohm: float,
    sd_cm2: float,
    alignment: str = "QB3",
    port_diameter_mm: float = 50.0,
) -> dict:
    """
    Vented (bass-reflex) loudspeaker enclosure design (Thiele-Small).

    Supported alignments: "QB3" (quasi-Butterworth 3rd order) and "SBB4"
    (sub-Chebyshev / maximally flat 4th order, Small 1973).

    Port length (Lv) is calculated from the Helmholtz resonator formula:
        fb = (c / 2π) × sqrt(Sd_port / (Vb × (Lv + k × d_port)))
    Solving for Lv:
        Lv = (c² × Ap) / ((2π × fb)² × Vb_m3) − k × d_port

    where Ap = π × (d_port/2)², k = 0.732 (flanged end-correction, Beranek §5.7),
    c = speed of sound.

    Port air velocity (chuffing check):
        v_port = (Sd_m2 × Xmax_m × ωb) / Ap   [approximation at resonance]
    Chuffing threshold: v_port > 5 % of speed of sound (17 m/s, Leach §9.4).

    Note: Sd_cm2 and Xmax are driver parameters.  Xmax is estimated from Qts/fs
    if not provided; this function uses a nominal Xmax = 5 mm for the chuffing check.

    Parameters
    ----------
    vas_l           : float — equivalent compliance volume [litres]
    qts             : float — total driver Q
    fs_hz           : float — driver resonance [Hz]
    re_ohm          : float — DC resistance of voice coil [Ω]
    sd_cm2          : float — effective piston area [cm²]
    alignment       : str   — "QB3" or "SBB4"
    port_diameter_mm: float — port tube diameter [mm] (default 50 mm)

    Returns
    -------
    dict : ok, alignment, vb_l, fb_hz, port_length_mm, port_diameter_mm,
           port_velocity_mps, chuffing_warning
    """
    for name, val in [("vas_l", vas_l), ("qts", qts), ("fs_hz", fs_hz),
                      ("re_ohm", re_ohm), ("sd_cm2", sd_cm2),
                      ("port_diameter_mm", port_diameter_mm)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    alignment = alignment.upper().strip()
    if alignment not in ("QB3", "SBB4"):
        return {"ok": False, "reason": "alignment must be 'QB3' or 'SBB4'"}

    table = _QB3_TABLE if alignment == "QB3" else _SBB4_TABLE
    alpha, fb_ratio = _interpolate_table(table, qts)

    vb_l = vas_l / alpha
    fb_hz = fs_hz * fb_ratio
    vb_m3 = vb_l * 1e-3

    # Port dimensions
    dp_m = port_diameter_mm * 1e-3
    ap_m2 = _PI * (dp_m / 2.0) ** 2

    # End correction factor for flanged port (Beranek)
    k_end = 0.732
    omega_b = 2.0 * _PI * fb_hz
    # Helmholtz: fb = (c/2π) × sqrt(Ap / (Vb × (Lv + k×dp)))
    # → Lv = (c² × Ap) / ((ωb)² × Vb) − k × dp
    lv_m = (_C_AIR ** 2 * ap_m2) / (omega_b ** 2 * vb_m3) - k_end * dp_m
    lv_mm = lv_m * 1e3

    if lv_mm <= 0.0:
        warnings.warn(
            f"vented_box: calculated port length {lv_mm:.1f} mm is <= 0. "
            "Port diameter may be too large. Try a smaller port.",
            stacklevel=2,
        )
        lv_mm = 0.0

    # Port air velocity check at box resonance (nominal Xmax = 5 mm)
    xmax_m = 5e-3   # nominal driver Xmax
    sd_m2 = sd_cm2 * 1e-4
    v_port = (sd_m2 * xmax_m * omega_b) / ap_m2 if ap_m2 > 0 else 0.0

    chuffing = v_port > 17.0  # 5% of c_air ≈ 17 m/s
    if chuffing:
        warnings.warn(
            f"vented_box: port air velocity {v_port:.1f} m/s exceeds 17 m/s "
            "(5% of speed of sound). Port chuffing likely. Increase port diameter.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "alignment": alignment,
        "vas_l": vas_l,
        "qts": qts,
        "fs_hz": fs_hz,
        "alpha": round(alpha, 4),
        "vb_l": round(vb_l, 3),
        "fb_hz": round(fb_hz, 3),
        "port_diameter_mm": port_diameter_mm,
        "port_length_mm": round(lv_mm, 2),
        "port_area_cm2": round(ap_m2 * 1e4, 4),
        "port_velocity_mps": round(v_port, 2),
        "chuffing_warning": chuffing,
        "note": (
            f"Thiele-Small {alignment} alignment. "
            "Port velocity check uses nominal Xmax = 5 mm."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Driver SPL Sensitivity and Maximum SPL
# ═══════════════════════════════════════════════════════════════════════════════


def driver_spl(
    sensitivity_db_1w_1m: float,
    power_w: float,
    xmax_mm: float,
    sd_cm2: float,
    re_ohm: float,
    distance_m: float = 1.0,
) -> dict:
    """
    Driver SPL sensitivity response and maximum SPL (power & excursion limited).

    SPL at power P and distance d:
        SPL = sensitivity + 10×log10(P) − 20×log10(d)

    Maximum power-limited SPL uses rated power (power_w).

    Maximum excursion-limited SPL (at 1 m, at 100 Hz — simplified):
        Pmax_excursion = (2π × f × Xmax × Sd)² × ρ_air / (2π × Re)
    This is the acoustic power assuming the driver is at resonance and
    Xmax is reached.  A simplified version (Leach §6.3):
        SPL_max_excursion = 112 + 20×log10(f × Xmax_m × Sd_m2 / Re_Ω × 20)
    Here we use a direct calculation at 100 Hz as a useful reference.

    Parameters
    ----------
    sensitivity_db_1w_1m : float — sensitivity [dB SPL @ 1 W, 1 m]
    power_w              : float — rated input power [W]
    xmax_mm              : float — peak linear excursion [mm]
    sd_cm2               : float — effective piston area [cm²]
    re_ohm               : float — voice coil DC resistance [Ω]
    distance_m           : float — listening distance [m] (default 1.0 m)

    Returns
    -------
    dict : ok, spl_at_rated_power_db, spl_at_1w_1m_db,
           spl_excursion_limited_100hz_db, power_w, xmax_mm, distance_m
    """
    for name, val in [("sensitivity_db_1w_1m", sensitivity_db_1w_1m),
                      ("power_w", power_w), ("xmax_mm", xmax_mm),
                      ("sd_cm2", sd_cm2), ("re_ohm", re_ohm),
                      ("distance_m", distance_m)]:
        if name == "sensitivity_db_1w_1m":
            err = _vr(val, name)
        else:
            err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    spl_at_1w_1m = sensitivity_db_1w_1m  # by definition
    dist_correction = 20.0 * math.log10(distance_m) if distance_m != 1.0 else 0.0
    spl_rated = sensitivity_db_1w_1m + 10.0 * math.log10(power_w) - dist_correction

    # Excursion-limited SPL at 100 Hz, 1 m (Leach approximation)
    f_ref = 100.0
    xmax_m = xmax_mm * 1e-3
    sd_m2 = sd_cm2 * 1e-4
    omega = 2.0 * _PI * f_ref
    # Peak acoustic pressure at 1 m from a piston (far field):
    # p = (ρ × c × k × Sd × Xmax) / (2π × r) where k = ω/c
    # SPL = 20*log10(p / p_ref)
    p_peak = (_RHO_AIR * _C_AIR * (omega / _C_AIR) * sd_m2 * xmax_m) / (2.0 * _PI * 1.0)
    spl_excursion = 20.0 * math.log10(p_peak / _SPL_REF) if p_peak > 0 else -math.inf

    if spl_excursion > 130.0:
        warnings.warn(
            f"driver_spl: excursion-limited SPL {spl_excursion:.1f} dB > 130 dB. "
            "Check driver parameters.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "sensitivity_db_1w_1m": sensitivity_db_1w_1m,
        "power_w": power_w,
        "xmax_mm": xmax_mm,
        "sd_cm2": sd_cm2,
        "re_ohm": re_ohm,
        "distance_m": distance_m,
        "spl_at_1w_1m_db": round(spl_at_1w_1m, 2),
        "spl_at_rated_power_db": round(spl_rated, 2),
        "spl_excursion_limited_100hz_db": round(spl_excursion, 2),
        "note": "Excursion-limited SPL calculated at 100 Hz, 1 m (piston far-field model).",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Passive Crossover Networks
# ═══════════════════════════════════════════════════════════════════════════════

# Butterworth (Chebyshev Q=0.707) and Linkwitz-Riley (double-Butterworth, −6 dB at fc)
# normalised g-values (Zverev tables).
# Format: order → list of normalised g-values g[1..n]

_BW_G = {
    1: [1.0],
    2: [1.4142, 1.4142],
    3: [1.0, 2.0, 1.0],
    4: [0.7654, 1.8478, 1.8478, 0.7654],
}

_LR_G = {
    # LR4 = cascade of two 2nd-order Butterworth (each Q=0.707)
    2: [1.0, 1.0],     # LR2 (each -3 dB, −6 dB combined at fc)
    4: [0.7654, 1.8478, 1.8478, 0.7654],  # LR4 (same as BW4, but level-matched)
}


def passive_crossover(
    fc_hz: float,
    z_load: float,
    order: int = 2,
    topology: str = "butterworth",
) -> dict:
    """
    Passive crossover component values (L and C) for a resistive load.

    Supported topologies:
        "butterworth"       — maximally flat, −3 dB at fc (1st–4th order)
        "linkwitz-riley"    — −6 dB at fc, in-phase summing (2nd and 4th order)

    For each stage: element values are computed from normalised g-values.
    The low-pass prototype is denormalised to:
        C_i = g_i / (2π × fc × Z)   [shunt capacitors, odd g in LCL...]
        L_i = g_i × Z / (2π × fc)   [series inductors, even g in LCL...]

    Component sequence follows: L(series), C(shunt), L(series), C(shunt)...

    Parameters
    ----------
    fc_hz    : float — crossover frequency [Hz]
    z_load   : float — nominal load impedance [Ω] (resistive)
    order    : int   — filter order 1, 2, 3, or 4 (Butterworth); 2 or 4 (L-R)
    topology : str   — "butterworth" or "linkwitz-riley"

    Returns
    -------
    dict : ok, fc_hz, z_load, order, topology, components[]
           where components = list of {"type": "L"/"C", "value_H": ..., "value_F": ...}
    """
    for name, val in [("fc_hz", fc_hz), ("z_load", z_load)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    topology = topology.lower().strip().replace("-", "").replace("_", "")
    topo_map = {
        "butterworth": "butterworth",
        "linkwitzriley": "linkwitz-riley",
        "lr": "linkwitz-riley",
    }
    if topology not in topo_map:
        return {
            "ok": False,
            "reason": f"topology must be 'butterworth' or 'linkwitz-riley', got {topology!r}",
        }
    topology = topo_map[topology]

    if topology == "butterworth":
        if order not in _BW_G:
            return {"ok": False, "reason": f"Butterworth order must be 1–4, got {order}"}
        g_vals = _BW_G[order]
    else:
        if order not in _LR_G:
            return {"ok": False, "reason": f"Linkwitz-Riley order must be 2 or 4, got {order}"}
        g_vals = _LR_G[order]

    omega_c = 2.0 * _PI * fc_hz
    components = []
    # Series inductors (indices 0, 2, ...) and shunt capacitors (indices 1, 3, ...)
    # following L-C-L-C prototype network (ladder low-pass prototype)
    for i, g in enumerate(g_vals):
        if i % 2 == 0:
            # Series inductor
            val_h = g * z_load / omega_c
            components.append({
                "stage": i + 1,
                "type": "L",
                "value_H": val_h,
                "value_mH": round(val_h * 1e3, 6),
            })
        else:
            # Shunt capacitor
            val_f = g / (omega_c * z_load)
            components.append({
                "stage": i + 1,
                "type": "C",
                "value_F": val_f,
                "value_uF": round(val_f * 1e6, 6),
            })

    return {
        "ok": True,
        "fc_hz": fc_hz,
        "z_load": z_load,
        "order": order,
        "topology": topology,
        "components": components,
        "note": (
            "Values are for low-pass network; swap L↔C for high-pass. "
            "Assumes resistive (non-reactive) load."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Zobel (Impedance Compensation) Network
# ═══════════════════════════════════════════════════════════════════════════════


def zobel_network(
    re_ohm: float,
    le_mh: float,
) -> dict:
    """
    Zobel (impedance compensation) RC network for a loudspeaker driver.

    The Zobel network flattens the rising voice-coil inductance impedance:
        Rz = Re   (series resistance)
        Cz = Le / Re²   (shunt capacitance)

    This presents a nominally resistive load to the crossover network
    across the audio band (Leach §7.2).

    Parameters
    ----------
    re_ohm : float — DC voice coil resistance [Ω]
    le_mh  : float — voice coil inductance [mH]

    Returns
    -------
    dict : ok, re_ohm, le_mh, rz_ohm, cz_uF
    """
    for name, val in [("re_ohm", re_ohm), ("le_mh", le_mh)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    le_h = le_mh * 1e-3
    rz = re_ohm
    cz_f = le_h / (re_ohm ** 2)
    cz_uf = cz_f * 1e6

    return {
        "ok": True,
        "re_ohm": re_ohm,
        "le_mh": le_mh,
        "rz_ohm": round(rz, 4),
        "cz_uF": round(cz_uf, 4),
        "note": "Zobel network: place Rz+Cz in series, wired in shunt across driver terminals.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# L-pad Attenuator
# ═══════════════════════════════════════════════════════════════════════════════


def lpad_attenuator(
    attenuation_db: float,
    z_source: float,
    z_load: float,
) -> dict:
    """
    L-pad resistive attenuator values for loudspeaker level matching.

    An L-pad consists of a series resistor Rs (in series with the signal path)
    and a shunt resistor Rp (from signal to ground), forming an L-network that
    attenuates the signal while maintaining the source and load impedances.

    Design equations (maintaining load impedance Z_load):
        Rp = Z_load / (sqrt(10^(Adb/10)) − 1)
        Rs = Z_source × (1 − 1/sqrt(10^(Adb/10)))
             adjusted so that input impedance = Z_source.

    Standard simplified L-pad (Beranek §5.5):
        Voltage ratio: k = 10^(−Adb/20)
        Rs = Z_load × (1/k − 1)
        Rp = Z_load × k / (1 − k)     when Z_source << Z_load

    Here the general resistor divider approach is used:
        k = 10^(−Adb/20) [voltage ratio]
        The two resistors form a divider with:
            Vout = Vin × Rp / (Rs + Rp)  when Rp >> Z_load
        For matched attenuator: Rp || Z_load in the divider.

    This function uses the simple voltage divider (no Z_source matching):
        Rs = Z_load × (1 − k) / k   (series)
        Rp = Z_load × k / (1 − k)   ... solved from Vout/Vin = k with Rp||Z_load
    For a true matched L-pad, Rp accounts for Z_load:
        Z_in = Rs + Rp || Z_load = Z_source  (when desired)

    Parameters
    ----------
    attenuation_db : float — desired attenuation [dB] (positive = reduce level)
    z_source       : float — source impedance [Ω] (amplifier output)
    z_load         : float — load impedance [Ω] (driver nominal impedance)

    Returns
    -------
    dict : ok, attenuation_db, rs_ohm, rp_ohm, actual_attenuation_db
    """
    for name, val in [("attenuation_db", attenuation_db),
                      ("z_source", z_source), ("z_load", z_load)]:
        if name == "attenuation_db":
            err = _vnn(val, name)
        else:
            err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    if attenuation_db == 0.0:
        return {
            "ok": True,
            "attenuation_db": 0.0,
            "rs_ohm": 0.0,
            "rp_ohm": float("inf"),
            "actual_attenuation_db": 0.0,
            "note": "Zero attenuation; Rs=0, Rp=∞ (no network needed).",
        }

    k = 10.0 ** (-attenuation_db / 20.0)   # voltage ratio (< 1)
    # L-pad for voltage divider into Z_load:
    # Vout = Vin × (Rp || Z_load) / (Rs + Rp || Z_load) = k × Vin
    # Assume Rp >> Z_load (dominant load): simplified:
    #   k = Z_load / (Z_load + Rs)  → Rs = Z_load × (1/k - 1)
    #   Rp provides parallel trimming; for ideal L-pad: Rp large relative to Z_load
    rs = z_load * (1.0 / k - 1.0)
    # For a proper L-pad maintaining Z_source:
    rp = z_source * z_load / (z_source - k * k * z_load) if z_source > k * k * z_load else None

    # Actual attenuation with computed Rs (shunt into Z_load, no Rp contribution)
    actual_k = z_load / (z_load + rs)
    actual_adb = -20.0 * math.log10(actual_k)

    result = {
        "ok": True,
        "attenuation_db": attenuation_db,
        "z_source": z_source,
        "z_load": z_load,
        "rs_ohm": round(rs, 4),
        "actual_attenuation_db": round(actual_adb, 3),
        "note": "L-pad: Rs in series, Rp in shunt to ground across driver terminals.",
    }
    if rp is not None and rp > 0:
        result["rp_ohm"] = round(rp, 4)
    else:
        result["rp_ohm"] = None

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Damping Factor
# ═══════════════════════════════════════════════════════════════════════════════


def damping_factor(
    amp_zout_ohm: float,
    re_ohm: float,
    cable_r_ohm: float = 0.1,
) -> dict:
    """
    Amplifier damping factor and its effect on driver control.

    Damping factor (DF) is defined as the ratio of the loudspeaker impedance
    (nominally Re) to the total source impedance seen by the driver:

        DF = Re / (Zout + R_cable)

    where Zout is the amplifier output impedance and R_cable is the total
    cable resistance (one-way × 2 for round trip).

    A DF < 10 significantly reduces amplifier control of cone motion
    (Leach §5.5); DF > 100 is generally considered excellent.

    Parameters
    ----------
    amp_zout_ohm : float — amplifier output impedance [Ω]
    re_ohm       : float — driver DC voice coil resistance [Ω]
    cable_r_ohm  : float — cable resistance (round trip) [Ω] (default 0.1 Ω)

    Returns
    -------
    dict : ok, amp_zout_ohm, re_ohm, cable_r_ohm, total_source_ohm,
           damping_factor, quality_note
    """
    for name, val in [("amp_zout_ohm", amp_zout_ohm), ("re_ohm", re_ohm)]:
        err = _vnn(val, name)
        if err:
            return {"ok": False, "reason": err}
    err = _vnn(cable_r_ohm, "cable_r_ohm")
    if err:
        return {"ok": False, "reason": err}

    total_z = amp_zout_ohm + cable_r_ohm
    if total_z <= 0.0:
        return {"ok": False, "reason": "Total source impedance (amp_zout + cable_r) must be > 0"}

    df = re_ohm / total_z

    if df < 10.0:
        quality = "Poor (< 10): significant back-EMF braking reduction"
        warnings.warn(
            f"damping_factor: DF = {df:.1f} is below 10. Amplifier control of cone "
            "motion is significantly impaired. Reduce cable resistance or use a "
            "lower-output-impedance amplifier.",
            stacklevel=2,
        )
    elif df < 50.0:
        quality = "Marginal (10–50): noticeable effect on transient response"
    elif df < 100.0:
        quality = "Good (50–100)"
    else:
        quality = "Excellent (> 100)"

    return {
        "ok": True,
        "amp_zout_ohm": amp_zout_ohm,
        "re_ohm": re_ohm,
        "cable_r_ohm": cable_r_ohm,
        "total_source_ohm": round(total_z, 6),
        "damping_factor": round(df, 2),
        "quality_note": quality,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# dB Mathematics
# ═══════════════════════════════════════════════════════════════════════════════


def spl_add(*spl_db: float) -> dict:
    """
    Add multiple incoherent SPL sources (dB).

    Incoherent (power) addition:
        SPL_total = 10 × log10(sum(10^(SPL_i / 10)))

    Parameters
    ----------
    *spl_db : float — two or more SPL values in dB

    Returns
    -------
    dict : ok, spl_values_db, spl_total_db
    """
    if len(spl_db) < 2:
        return {"ok": False, "reason": "spl_add requires at least two SPL values"}
    for i, v in enumerate(spl_db):
        err = _vr(v, f"spl_db[{i}]")
        if err:
            return {"ok": False, "reason": err}

    total = 10.0 * math.log10(sum(10.0 ** (s / 10.0) for s in spl_db))
    return {
        "ok": True,
        "spl_values_db": list(spl_db),
        "spl_total_db": round(total, 3),
        "note": "Incoherent (power) SPL addition.",
    }


def spl_distance(
    spl_ref_db: float,
    d_ref_m: float,
    d_target_m: float,
) -> dict:
    """
    SPL at a new distance using the inverse-square law (free field, point source).

        SPL(d) = SPL(d_ref) − 20 × log10(d / d_ref)

    Parameters
    ----------
    spl_ref_db : float — SPL [dB] at reference distance
    d_ref_m    : float — reference distance [m]
    d_target_m : float — target distance [m]

    Returns
    -------
    dict : ok, spl_ref_db, d_ref_m, d_target_m, spl_target_db
    """
    err = _vr(spl_ref_db, "spl_ref_db")
    if err:
        return {"ok": False, "reason": err}
    for name, val in [("d_ref_m", d_ref_m), ("d_target_m", d_target_m)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    spl_target = spl_ref_db - 20.0 * math.log10(d_target_m / d_ref_m)
    return {
        "ok": True,
        "spl_ref_db": spl_ref_db,
        "d_ref_m": d_ref_m,
        "d_target_m": d_target_m,
        "spl_target_db": round(spl_target, 3),
    }


def db_voltage(
    v_ratio: float,
) -> dict:
    """
    Convert a voltage ratio to dB (20 × log10(V_ratio)).

    Parameters
    ----------
    v_ratio : float — voltage ratio V_out / V_in (must be > 0)

    Returns
    -------
    dict : ok, v_ratio, db
    """
    err = _vp(v_ratio, "v_ratio")
    if err:
        return {"ok": False, "reason": err}
    return {"ok": True, "v_ratio": v_ratio, "db": round(20.0 * math.log10(v_ratio), 6)}


def db_power(
    p_ratio: float,
) -> dict:
    """
    Convert a power ratio to dB (10 × log10(P_ratio)).

    Parameters
    ----------
    p_ratio : float — power ratio P_out / P_in (must be > 0)

    Returns
    -------
    dict : ok, p_ratio, db
    """
    err = _vp(p_ratio, "p_ratio")
    if err:
        return {"ok": False, "reason": err}
    return {"ok": True, "p_ratio": p_ratio, "db": round(10.0 * math.log10(p_ratio), 6)}


# ═══════════════════════════════════════════════════════════════════════════════
# A-weighting
# ═══════════════════════════════════════════════════════════════════════════════


def a_weighting(freq_hz: float) -> dict:
    """
    A-weighting correction in dB at a given frequency.

    IEC 61672-1 / ANSI S1.4 A-weighting formula:
        A(f) = 2.0 + 20×log10(Ra(f))

    where:
        Ra(f) = (12200² × f⁴) /
                ((f² + 20.6²) × sqrt((f² + 107.7²) × (f² + 737.9²)) × (f² + 12200²))

    Normalised so that A(1000 Hz) = 0 dB.

    Parameters
    ----------
    freq_hz : float — frequency [Hz] (positive)

    Returns
    -------
    dict : ok, freq_hz, a_weighting_db
    """
    err = _vp(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}

    f = freq_hz
    f2 = f ** 2
    # A-weighting transfer function (IEC 61672-1)
    num = (12200.0 ** 2) * (f2 ** 2)
    den = (
        (f2 + 20.6 ** 2)
        * math.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2))
        * (f2 + 12200.0 ** 2)
    )
    if den == 0:
        return {"ok": False, "reason": "denominator zero in A-weighting formula"}

    ra = num / den
    # Normalisation: at 1000 Hz, Ra_1kHz is a fixed value
    f0 = 1000.0
    f0_2 = f0 ** 2
    num0 = (12200.0 ** 2) * (f0_2 ** 2)
    den0 = (
        (f0_2 + 20.6 ** 2)
        * math.sqrt((f0_2 + 107.7 ** 2) * (f0_2 + 737.9 ** 2))
        * (f0_2 + 12200.0 ** 2)
    )
    ra0 = num0 / den0
    a_db = 20.0 * math.log10(ra / ra0)

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "a_weighting_db": round(a_db, 4),
        "note": "IEC 61672-1 A-weighting. Normalised to 0 dB at 1 kHz.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Line-level / Impedance Bridging
# ═══════════════════════════════════════════════════════════════════════════════


def impedance_bridging(
    z_source: float,
    z_load: float,
) -> dict:
    """
    Impedance bridging analysis for line-level audio connections.

    In audio engineering, "bridging" means the load impedance is much higher
    than the source impedance (Z_load >> Z_source), maximising voltage transfer
    (not power transfer).  The recommended ratio is Z_load / Z_source ≥ 10.

    Voltage transfer factor:
        Av = Z_load / (Z_source + Z_load)
        Av_db = 20 × log10(Av)

    Power transfer (matched impedances maximise power):
        P_rel = 4 × Z_source × Z_load / (Z_source + Z_load)²
        P_rel_db = 10 × log10(P_rel)

    Parameters
    ----------
    z_source : float — source (output) impedance [Ω]
    z_load   : float — load (input) impedance [Ω]

    Returns
    -------
    dict : ok, z_source, z_load, ratio, av_linear, av_db,
           power_transfer_db, bridging_ok
    """
    for name, val in [("z_source", z_source), ("z_load", z_load)]:
        err = _vp(val, name)
        if err:
            return {"ok": False, "reason": err}

    ratio = z_load / z_source
    av = z_load / (z_source + z_load)
    av_db = 20.0 * math.log10(av)
    p_rel = 4.0 * z_source * z_load / (z_source + z_load) ** 2
    p_rel_db = 10.0 * math.log10(p_rel)
    bridging_ok = ratio >= 10.0

    if not bridging_ok:
        warnings.warn(
            f"impedance_bridging: Z_load/Z_source = {ratio:.1f} < 10. "
            "Significant voltage loading; impedance bridging condition not met. "
            "Consider a buffer or impedance transformer.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "z_source": z_source,
        "z_load": z_load,
        "ratio": round(ratio, 4),
        "av_linear": round(av, 6),
        "av_db": round(av_db, 4),
        "power_transfer_db": round(p_rel_db, 4),
        "bridging_ok": bridging_ok,
        "note": "Bridging OK when Z_load/Z_source ≥ 10 (audio standard).",
    }
