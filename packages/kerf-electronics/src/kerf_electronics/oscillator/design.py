"""
Crystal oscillator & PLL design — closed-form analytical models.

This module is distinct from:
  • kerf_electronics.si        — signal integrity (Z0, propagation, crosstalk)
  • kerf_electronics.emc       — radiated emissions / shielding
  • kerf_electronics.rfmatch   — RF matching networks
  • kerf_electronics.afilter   — analogue filters
  • kerf_electronics.dsp       — digital signal processing
  • kerf_electronics.powerconv — switching power converters

All functions are pure Python (math module only) and follow the kerf
never-raise contract: validation errors are returned as dicts with
{ok: False, reason: str}; warnings are issued via the standard warnings
module for design-rule violations; exceptions are never raised to callers.

Crystal oscillator models
-------------------------

Crystal load capacitance (CL) and external capacitor selection
(Marki/Williams "Electronic Filter Design Handbook" 4e / crystal data-sheet
convention):

    CL = (C1_ext × C2_ext) / (C1_ext + C2_ext) + Cstray

External cap from desired CL and known stray:

    C_ext = 2 × (CL − Cstray)     [symmetric C1=C2=C_ext]

Pierce oscillator negative resistance (Rohde & Kuhn, 2005; also Vittoz 1988):

    −Rn = −gm / (ω² × C1 × C2)

where ω = 2π f, gm = transconductance of inverting amplifier, C1/C2 = load caps.

Oscillation condition: |−Rn| ≥ safety_factor × ESR_max  (typically ×3–5)
gm_margin = |−Rn| / ESR_max   (should be ≥ 3 for safe startup)

Drive level estimate (Baba & Yoon, "Crystal drive level estimation", 2003):
    P_xtal ≈ ½ × ESR × (ω × C1 × V_DD)²   [simplified, peak voltage swing = V_DD/2]
    More precisely:
    I_rms² = V_rms² × (ωC2)² / (1 + (ωC2 × ESR)²)  ... approximated as:
    P_xtal ≈ ½ × ESR × (ω × C_load_eff × V_osc)²

Frequency pulling/trim from CL error (IEC 60444-5):
    Δf/f = −(Cm / (2 × C0)) × [1/(1 + C0/CL_actual)² − 1/(1 + C0/CL_nom)²]

    For small ΔCL << CL_nom this simplifies to:
    Δf/f ≈ (Cm × ΔCL) / (2 × (C0 + CL_nom)²)   [in ppm when ×1e6]

    where Cm = motional capacitance, C0 = shunt capacitance, CL = load cap.

ppm error budget (root-sum-of-squares):
    total_ppm = sqrt(initial_tolerance² + temp_ppm² + aging_ppm² + load_ppm²)

RC oscillator frequency:
    f = 1 / (2π × R × C)   [first-order RC, charge/discharge model]
    (CMOS Schmitt variant: f ≈ 1 / (2.2 × R × C) — use rc_factor parameter)

LC oscillator (Colpitts / Hartley) frequency:
    f = 1 / (2π × sqrt(L × C))   [ideal parallel LC tank]

Ring oscillator frequency (N inverter stages, each with propagation delay τ_pd):
    f = 1 / (2 × N × τ_pd)   [fundamental, odd N assumed]

PLL design
----------

Divider N from desired output frequency and reference:
    N = round(f_out / f_ref)     [integer-N PLL]
    or exact fractional value returned for fractional-N.

Type-II 2nd-order loop filter (charge-pump PLL, Gardner 2005; Banerjee 2006):

Closed-loop transfer function H(s):
    ωn² = Icp × Kvco / (2π × N × C1)
    ωn = sqrt(Icp × Kvco / (2π × N × C1))
    ζ  = ωn × R × C1 / 2             [for C1 only, neglecting C2]

    For a given ωn (loop bandwidth ωBW = ωn approx.) and phase margin φm:
        R  = 2ζ / ωn
        C1 = Icp × Kvco / (2π × N × ωn²)
        C2 = C1 / 10   [rule of thumb for reference-spur suppression ≥20 dB]

    For 3rd-order (R-C1-C2 ladder), C2 adds a high-frequency pole:
        ω_pole2 ≈ 1 / (R × C2)
        C2 chosen to place ω_pole2 ≥ 10 × ωn

    Phase margin from R, C1, ωn:
        φm ≈ atan(ωn × R × C1) − atan(ωn × R × C1 / 10)  [2nd order approx]
        For a given target phase margin: ζ = tan(φm)/2 + sqrt(tan²(φm)/4 + 1)/2 (typ)
        Simplified Banerjee closed-form: R = tan(φm) / (ωn × C1)

Lock time estimate (Banerjee, 2006 §3.8):
    t_lock ≈ −ln(ε_freq / f_step) / (ζ × ωn)
    where ε_freq = frequency accuracy at lock [Hz], f_step = VCO tuning step.

Phase noise to RMS jitter (conversion):
    σ_rms [s] = (1 / (2π × f_osc)) × sqrt(2 × ∫ L(f) × df)
    Approximated for a single phase-noise value at offset f_offset (in dBc/Hz):
        L(f_offset) [linear] = 10^(L_dBc / 10)
        σ ≈ sqrt(L_lin × BW_integration) / (π × f_osc)
    where BW_integration is the one-sided noise bandwidth provided.

Reference spur note: reported qualitatively from R, C2, Kvco, Icp.

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Optional

# ── Physical constants ────────────────────────────────────────────────────────

_TWO_PI = 2.0 * math.pi


# ── Validation helpers ────────────────────────────────────────────────────────


def _pos(value, name: str) -> Optional[str]:
    """Return an error string if value is not a positive real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive number, got {value!r}"
    return None


def _nonneg(value, name: str) -> Optional[str]:
    """Return an error string if value is negative or not a real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _finite(value, name: str) -> Optional[str]:
    """Return an error string if value is not a finite real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return f"{name} must be a finite number, got {value!r}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Crystal load capacitance & external cap selection
# ═══════════════════════════════════════════════════════════════════════════════


def crystal_load_caps(
    cl_target_f: float,
    cstray_f: float = 3e-12,
    c1_ext_f: Optional[float] = None,
    c2_ext_f: Optional[float] = None,
) -> dict:
    """
    Crystal load capacitance calculation and external cap selection.

    The crystal sees a load capacitance:
        CL = (C1_ext × C2_ext) / (C1_ext + C2_ext) + Cstray

    For a symmetric design (C1 = C2):
        C_ext_each = 2 × (CL_target − Cstray)

    If both C1_ext and C2_ext are provided, the actual CL is computed and
    the deviation from cl_target_f is reported in ppm.

    Parameters
    ----------
    cl_target_f  : float — target crystal load capacitance [F], e.g. 12e-12
    cstray_f     : float — PCB stray capacitance per node [F] (default 3e-12)
    c1_ext_f     : float or None — first external load cap [F] (optional)
    c2_ext_f     : float or None — second external load cap [F] (optional)

    Returns
    -------
    dict with keys:
        ok, cl_target_f, cstray_f, c_ext_symmetric_f,
        cl_actual_f (if c1/c2 given), cl_error_ppm (if c1/c2 given),
        warnings
    """
    err = _pos(cl_target_f, "cl_target_f")
    if err:
        return {"ok": False, "reason": err}
    err = _nonneg(cstray_f, "cstray_f")
    if err:
        return {"ok": False, "reason": err}

    if cl_target_f <= cstray_f:
        return {
            "ok": False,
            "reason": (
                f"cl_target_f ({cl_target_f*1e12:.2f} pF) must be greater than "
                f"cstray_f ({cstray_f*1e12:.2f} pF)"
            ),
        }

    c_ext_symmetric = 2.0 * (cl_target_f - cstray_f)

    result: dict = {
        "ok": True,
        "cl_target_f": cl_target_f,
        "cl_target_pf": round(cl_target_f * 1e12, 4),
        "cstray_f": cstray_f,
        "cstray_pf": round(cstray_f * 1e12, 4),
        "c_ext_symmetric_f": c_ext_symmetric,
        "c_ext_symmetric_pf": round(c_ext_symmetric * 1e12, 4),
        "warnings": [],
    }

    if c1_ext_f is not None and c2_ext_f is not None:
        err1 = _pos(c1_ext_f, "c1_ext_f")
        if err1:
            return {"ok": False, "reason": err1}
        err2 = _pos(c2_ext_f, "c2_ext_f")
        if err2:
            return {"ok": False, "reason": err2}

        cl_actual = (c1_ext_f * c2_ext_f) / (c1_ext_f + c2_ext_f) + cstray_f
        cl_error_ppm = ((cl_actual - cl_target_f) / cl_target_f) * 1e6

        result["c1_ext_f"] = c1_ext_f
        result["c1_ext_pf"] = round(c1_ext_f * 1e12, 4)
        result["c2_ext_f"] = c2_ext_f
        result["c2_ext_pf"] = round(c2_ext_f * 1e12, 4)
        result["cl_actual_f"] = cl_actual
        result["cl_actual_pf"] = round(cl_actual * 1e12, 4)
        result["cl_error_ppm"] = round(cl_error_ppm, 2)

        if abs(cl_error_ppm) > 5000:
            msg = (
                f"CL error {cl_error_ppm:.1f} ppm exceeds ±5000 ppm; "
                "choose external caps closer to c_ext_symmetric."
            )
            warnings.warn(msg, stacklevel=2)
            result["warnings"].append(msg)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Pierce-oscillator negative resistance & gm margin
# ═══════════════════════════════════════════════════════════════════════════════


def pierce_negative_resistance(
    freq_hz: float,
    gm_s: float,
    c1_f: float,
    c2_f: float,
    esr_ohm: float,
    safety_factor: float = 3.0,
) -> dict:
    """
    Pierce oscillator negative resistance and gm margin.

    Model (Rohde & Kuhn 2005; Vittoz 1988):
        |−Rn| = gm / (ω² × C1 × C2)

    Oscillation condition: |−Rn| ≥ safety_factor × ESR

    Parameters
    ----------
    freq_hz       : float — crystal nominal frequency [Hz]
    gm_s          : float — inverting amplifier transconductance [S] (A/V)
    c1_f          : float — load capacitor on input side [F]
    c2_f          : float — load capacitor on output side [F]
    esr_ohm       : float — crystal equivalent series resistance [Ω]
    safety_factor : float — negative resistance safety margin (default 3)

    Returns
    -------
    dict with keys:
        ok, freq_hz, gm_s, c1_f, c2_f, esr_ohm,
        omega_rad_s, neg_resistance_ohm,
        gm_margin, sufficient_gm (bool), warnings
    """
    for val, name in [
        (freq_hz, "freq_hz"), (gm_s, "gm_s"), (c1_f, "c1_f"),
        (c2_f, "c2_f"), (esr_ohm, "esr_ohm"), (safety_factor, "safety_factor"),
    ]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    omega = _TWO_PI * freq_hz
    neg_res = gm_s / (omega ** 2 * c1_f * c2_f)
    gm_margin = neg_res / esr_ohm
    sufficient_gm = gm_margin >= safety_factor

    result = {
        "ok": True,
        "freq_hz": freq_hz,
        "gm_s": gm_s,
        "c1_f": c1_f,
        "c2_f": c2_f,
        "esr_ohm": esr_ohm,
        "omega_rad_s": omega,
        "neg_resistance_ohm": round(neg_res, 4),
        "gm_margin": round(gm_margin, 4),
        "sufficient_gm": sufficient_gm,
        "safety_factor": safety_factor,
        "warnings": [],
    }

    if not sufficient_gm:
        msg = (
            f"Insufficient gm margin: {gm_margin:.2f}× < {safety_factor}×. "
            "Oscillator may fail to start. Increase gm or reduce load caps."
        )
        warnings.warn(msg, stacklevel=2)
        result["warnings"].append(msg)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Drive level estimate
# ═══════════════════════════════════════════════════════════════════════════════


def drive_level_estimate(
    freq_hz: float,
    esr_ohm: float,
    c_load_f: float,
    v_osc_v: float,
    max_drive_level_uw: float = 100.0,
) -> dict:
    """
    Estimate power dissipated in the crystal (drive level).

    Simplified model (Baba & Yoon 2003; Frerking "Crystal Oscillator Design"
    Van Nostrand 1978):
        I_rms ≈ ω × CL × V_rms   [current through load capacitor]
        V_rms = V_osc / sqrt(2)   [assume sinusoidal]
        P_xtal = I_rms² × ESR

    where CL = c_load_f is the effective series load cap seen by the crystal.

    Parameters
    ----------
    freq_hz           : float — oscillation frequency [Hz]
    esr_ohm           : float — crystal equivalent series resistance [Ω]
    c_load_f          : float — crystal load capacitance [F]
    v_osc_v           : float — oscillation voltage amplitude (peak) [V]
    max_drive_level_uw: float — crystal max drive level [μW] (default 100 μW)

    Returns
    -------
    dict with keys:
        ok, freq_hz, esr_ohm, c_load_f, v_osc_v,
        i_rms_a, drive_level_uw, max_drive_level_uw,
        over_drive (bool), warnings
    """
    for val, name in [
        (freq_hz, "freq_hz"), (esr_ohm, "esr_ohm"),
        (c_load_f, "c_load_f"), (v_osc_v, "v_osc_v"),
        (max_drive_level_uw, "max_drive_level_uw"),
    ]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    omega = _TWO_PI * freq_hz
    v_rms = v_osc_v / math.sqrt(2.0)
    i_rms = omega * c_load_f * v_rms
    drive_level_w = i_rms ** 2 * esr_ohm
    drive_level_uw = drive_level_w * 1e6
    over_drive = drive_level_uw > max_drive_level_uw

    result = {
        "ok": True,
        "freq_hz": freq_hz,
        "esr_ohm": esr_ohm,
        "c_load_f": c_load_f,
        "v_osc_v": v_osc_v,
        "omega_rad_s": omega,
        "v_rms_v": round(v_rms, 6),
        "i_rms_a": round(i_rms, 9),
        "drive_level_uw": round(drive_level_uw, 4),
        "max_drive_level_uw": max_drive_level_uw,
        "over_drive": over_drive,
        "warnings": [],
    }

    if over_drive:
        msg = (
            f"Over-drive: estimated drive level {drive_level_uw:.2f} μW "
            f"exceeds max {max_drive_level_uw:.1f} μW. "
            "Reduce oscillation amplitude or add series resistance."
        )
        warnings.warn(msg, stacklevel=2)
        result["warnings"].append(msg)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Frequency pulling / trim from CL error
# ═══════════════════════════════════════════════════════════════════════════════


def frequency_pulling(
    freq_hz: float,
    cm_f: float,
    c0_f: float,
    cl_nominal_f: float,
    cl_actual_f: float,
) -> dict:
    """
    Frequency pulling due to load capacitance deviation from nominal.

    Model (IEC 60444-5 / Vig "Quartz Crystal Resonators and Oscillators"
    SLCET-539 Rev. 8.4.2.1):

        Δf/f ≈ (Cm × ΔCL) / (2 × (C0 + CL_nom)²)

    For accurate result the exact formula is also computed:
        f_actual/f_nom = 1 + (Cm/2) × [1/(C0+CL_act) − 1/(C0+CL_nom)]

    Parameters
    ----------
    freq_hz      : float — crystal nominal frequency [Hz]
    cm_f         : float — motional (series) capacitance Cm [F]
    c0_f         : float — shunt (parallel) capacitance C0 [F]
    cl_nominal_f : float — nominal crystal load capacitance [F]
    cl_actual_f  : float — actual load capacitance [F]

    Returns
    -------
    dict with keys:
        ok, freq_hz, cm_f, c0_f, cl_nominal_f, cl_actual_f,
        delta_cl_f, delta_f_hz, delta_f_ppm,
        delta_f_hz_exact, delta_f_ppm_exact, warnings
    """
    for val, name in [
        (freq_hz, "freq_hz"), (cm_f, "cm_f"), (c0_f, "c0_f"),
        (cl_nominal_f, "cl_nominal_f"), (cl_actual_f, "cl_actual_f"),
    ]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    delta_cl = cl_actual_f - cl_nominal_f

    # First-order approximation (negative sign: increasing CL lowers frequency)
    # d/dCL [(Cm/2)/(C0+CL)] = -Cm/(2×(C0+CL)²)
    denom = (c0_f + cl_nominal_f) ** 2
    delta_f_over_f_approx = -(cm_f * delta_cl) / (2.0 * denom)
    delta_f_approx = delta_f_over_f_approx * freq_hz
    delta_f_ppm_approx = delta_f_over_f_approx * 1e6

    # Exact formula
    delta_f_over_f_exact = (cm_f / 2.0) * (
        1.0 / (c0_f + cl_actual_f) - 1.0 / (c0_f + cl_nominal_f)
    )
    delta_f_exact = delta_f_over_f_exact * freq_hz
    delta_f_ppm_exact = delta_f_over_f_exact * 1e6

    result = {
        "ok": True,
        "freq_hz": freq_hz,
        "cm_f": cm_f,
        "c0_f": c0_f,
        "cl_nominal_f": cl_nominal_f,
        "cl_actual_f": cl_actual_f,
        "delta_cl_f": delta_cl,
        "delta_cl_pf": round(delta_cl * 1e12, 4),
        "delta_f_hz": round(delta_f_approx, 6),
        "delta_f_ppm": round(delta_f_ppm_approx, 4),
        "delta_f_hz_exact": round(delta_f_exact, 6),
        "delta_f_ppm_exact": round(delta_f_ppm_exact, 4),
        "warnings": [],
    }

    if abs(delta_f_ppm_exact) > 200:
        msg = (
            f"Frequency pulling {delta_f_ppm_exact:.1f} ppm is large "
            "(> ±200 ppm). Check load cap selection."
        )
        warnings.warn(msg, stacklevel=2)
        result["warnings"].append(msg)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ppm error budget
# ═══════════════════════════════════════════════════════════════════════════════


def ppm_error_budget(
    initial_tolerance_ppm: float,
    temp_ppm: float,
    aging_ppm: float,
    load_ppm: float,
    budget_limit_ppm: Optional[float] = None,
) -> dict:
    """
    Total frequency accuracy error budget (RSS combination).

        total_ppm = sqrt(initial² + temp² + aging² + load²)

    Each term should be the worst-case ±magnitude (absolute value).

    Parameters
    ----------
    initial_tolerance_ppm : float — initial frequency tolerance at calibration [ppm]
    temp_ppm              : float — temperature coefficient contribution [ppm]
    aging_ppm             : float — aging contribution over life [ppm]
    load_ppm              : float — load-pulling / supply voltage contribution [ppm]
    budget_limit_ppm      : float or None — system budget limit [ppm] (optional)

    Returns
    -------
    dict with keys:
        ok, initial_tolerance_ppm, temp_ppm, aging_ppm, load_ppm,
        total_ppm, within_budget (if limit given), budget_limit_ppm, warnings
    """
    for val, name in [
        (initial_tolerance_ppm, "initial_tolerance_ppm"),
        (temp_ppm, "temp_ppm"),
        (aging_ppm, "aging_ppm"),
        (load_ppm, "load_ppm"),
    ]:
        err = _nonneg(val, name)
        if err:
            return {"ok": False, "reason": err}

    total_ppm = math.sqrt(
        initial_tolerance_ppm ** 2
        + temp_ppm ** 2
        + aging_ppm ** 2
        + load_ppm ** 2
    )

    result = {
        "ok": True,
        "initial_tolerance_ppm": initial_tolerance_ppm,
        "temp_ppm": temp_ppm,
        "aging_ppm": aging_ppm,
        "load_ppm": load_ppm,
        "total_ppm": round(total_ppm, 4),
        "warnings": [],
    }

    if budget_limit_ppm is not None:
        err = _pos(budget_limit_ppm, "budget_limit_ppm")
        if err:
            return {"ok": False, "reason": err}
        within_budget = total_ppm <= budget_limit_ppm
        result["budget_limit_ppm"] = budget_limit_ppm
        result["within_budget"] = within_budget

        if not within_budget:
            msg = (
                f"ppm error budget exceeded: total {total_ppm:.2f} ppm "
                f"> limit {budget_limit_ppm:.2f} ppm."
            )
            warnings.warn(msg, stacklevel=2)
            result["warnings"].append(msg)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 6. RC oscillator frequency
# ═══════════════════════════════════════════════════════════════════════════════


def rc_oscillator_frequency(
    r_ohm: float,
    c_f: float,
    rc_factor: float = 1.0,
) -> dict:
    """
    RC oscillator frequency.

    Ideal RC:
        f = 1 / (2π × R × C)

    For CMOS Schmitt-trigger RC oscillators the effective constant differs:
        f ≈ 1 / (rc_factor × 2π × R × C)   (rc_factor = 1.1 typical for CMOS)
    or:
        f ≈ 1 / (2.2 × R × C)              [set rc_factor = 2.2 / (2π) ≈ 0.350]

    Parameters
    ----------
    r_ohm     : float — resistance [Ω]
    c_f       : float — capacitance [F]
    rc_factor : float — multiplier on R×C (default 1.0 → ideal 1/(2πRC))
                        set to 2.2/(2π) ≈ 0.3502 for CMOS Schmitt variant.

    Returns
    -------
    dict with keys:
        ok, r_ohm, c_f, rc_factor, freq_hz, period_s, tau_s, warnings
    """
    for val, name in [(r_ohm, "r_ohm"), (c_f, "c_f"), (rc_factor, "rc_factor")]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    tau = r_ohm * c_f
    freq_hz = 1.0 / (rc_factor * _TWO_PI * tau)
    period_s = 1.0 / freq_hz

    return {
        "ok": True,
        "r_ohm": r_ohm,
        "c_f": c_f,
        "rc_factor": rc_factor,
        "tau_s": tau,
        "freq_hz": freq_hz,
        "period_s": period_s,
        "warnings": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 7. LC oscillator frequency
# ═══════════════════════════════════════════════════════════════════════════════


def lc_oscillator_frequency(
    l_h: float,
    c_f: float,
) -> dict:
    """
    LC (parallel tank) oscillator resonant frequency.

        f = 1 / (2π × sqrt(L × C))

    Applies to Colpitts, Clapp, Hartley (substitute effective L, C).

    Parameters
    ----------
    l_h : float — inductance [H]
    c_f : float — capacitance [F] (total effective tank capacitance)

    Returns
    -------
    dict with keys:
        ok, l_h, c_f, freq_hz, omega_rad_s, period_s, warnings
    """
    for val, name in [(l_h, "l_h"), (c_f, "c_f")]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    omega = 1.0 / math.sqrt(l_h * c_f)
    freq_hz = omega / _TWO_PI
    period_s = 1.0 / freq_hz

    return {
        "ok": True,
        "l_h": l_h,
        "c_f": c_f,
        "omega_rad_s": omega,
        "freq_hz": freq_hz,
        "period_s": period_s,
        "warnings": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Ring oscillator frequency
# ═══════════════════════════════════════════════════════════════════════════════


def ring_oscillator_frequency(
    n_stages: int,
    tau_pd_s: float,
) -> dict:
    """
    Ring oscillator fundamental frequency.

        f = 1 / (2 × N × τ_pd)

    where N = number of inverter stages (must be odd for oscillation),
    τ_pd = propagation delay per stage.

    Parameters
    ----------
    n_stages : int   — number of inverter stages (typically odd: 3, 5, 7, ...)
    tau_pd_s : float — propagation delay per stage [s]

    Returns
    -------
    dict with keys:
        ok, n_stages, tau_pd_s, freq_hz, period_s, warnings
    """
    if not isinstance(n_stages, int) or n_stages < 3:
        return {
            "ok": False,
            "reason": f"n_stages must be an integer ≥ 3, got {n_stages!r}",
        }
    err = _pos(tau_pd_s, "tau_pd_s")
    if err:
        return {"ok": False, "reason": err}

    freq_hz = 1.0 / (2.0 * n_stages * tau_pd_s)
    period_s = 1.0 / freq_hz

    result = {
        "ok": True,
        "n_stages": n_stages,
        "tau_pd_s": tau_pd_s,
        "freq_hz": freq_hz,
        "period_s": period_s,
        "warnings": [],
    }

    if n_stages % 2 == 0:
        msg = (
            f"n_stages={n_stages} is even. Ring oscillators require an odd "
            "number of inverting stages to sustain oscillation."
        )
        warnings.warn(msg, stacklevel=2)
        result["warnings"].append(msg)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 9. PLL: divider N from fout / fref
# ═══════════════════════════════════════════════════════════════════════════════


def pll_divider_n(
    f_out_hz: float,
    f_ref_hz: float,
    integer_n: bool = True,
) -> dict:
    """
    PLL feedback divider N from desired output and reference frequencies.

    Integer-N: N = round(f_out / f_ref), actual f_out = N × f_ref
    Fractional-N: N = f_out / f_ref (exact, reported as float)

    Parameters
    ----------
    f_out_hz  : float — desired VCO output frequency [Hz]
    f_ref_hz  : float — PFD reference frequency [Hz]
    integer_n : bool  — True → round N to nearest integer (default True)

    Returns
    -------
    dict with keys:
        ok, f_out_hz, f_ref_hz, N_exact, N_used (int if integer_n),
        f_out_actual_hz, freq_error_hz, freq_error_ppm, warnings
    """
    for val, name in [(f_out_hz, "f_out_hz"), (f_ref_hz, "f_ref_hz")]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    n_exact = f_out_hz / f_ref_hz
    if integer_n:
        n_used = round(n_exact)
        if n_used < 1:
            return {"ok": False, "reason": "computed N < 1; f_out < f_ref/2"}
    else:
        n_used = n_exact

    f_out_actual = n_used * f_ref_hz
    freq_error_hz = f_out_actual - f_out_hz
    freq_error_ppm = (freq_error_hz / f_out_hz) * 1e6 if f_out_hz > 0 else 0.0

    result = {
        "ok": True,
        "f_out_hz": f_out_hz,
        "f_ref_hz": f_ref_hz,
        "N_exact": n_exact,
        "N_used": n_used,
        "f_out_actual_hz": f_out_actual,
        "freq_error_hz": round(freq_error_hz, 4),
        "freq_error_ppm": round(freq_error_ppm, 4),
        "integer_n": integer_n,
        "warnings": [],
    }

    if integer_n and abs(freq_error_ppm) > 1000:
        msg = (
            f"Integer-N rounding error {freq_error_ppm:.1f} ppm is large. "
            "Consider fractional-N or a different reference frequency."
        )
        warnings.warn(msg, stacklevel=2)
        result["warnings"].append(msg)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 10. PLL type-II loop filter (2nd/3rd order)
# ═══════════════════════════════════════════════════════════════════════════════


def pll_type2_loop_filter(
    f_loop_bw_hz: float,
    phase_margin_deg: float,
    icp_a: float,
    kvco_hz_per_v: float,
    n_divider: float,
    order: int = 2,
) -> dict:
    """
    Type-II charge-pump PLL loop filter component values.

    Derivation (Banerjee, "PLL Performance, Simulation, and Design" 5e, 2006):

    Natural frequency ωn and damping ζ from bandwidth ωBW and phase margin φm:
        ωn ≈ ωBW / sqrt(1 + 2ζ² + sqrt(4ζ⁴ + 4ζ² + 2))  [exact: iterative]
        Simplified: ωBW ≈ ωn for ζ ≈ 0.7 (error < 10%)

    From phase margin φm (Banerjee closed form):
        ζ = tan(φm) / 2 + sqrt(tan²(φm)/4 + 1) / 2    [approximation]

    Component values:
        C1 = Icp × Kvco / (2π × N × ωn²)
        R  = 2ζ / (ωn × C1)                            [or R = tan(φm)/(ωn×C1)]
        C2 = C1 / 10                                     [2nd order spur suppression]

    For 3rd order (add pole via C2 in series with R):
        C2_3rd = C1 / 10
        ω_p2 = 1 / (R × C2_3rd)   [should be ≥ 10 × ωn for stability]

    Stability check: phase margin < 45° → UNSTABLE warning.

    Parameters
    ----------
    f_loop_bw_hz    : float — loop bandwidth [Hz] (ωBW = 2π × f_loop_bw_hz)
    phase_margin_deg: float — desired phase margin [degrees]
    icp_a           : float — charge pump current [A]
    kvco_hz_per_v   : float — VCO gain [Hz/V]
    n_divider       : float — feedback divider ratio N
    order           : int   — 2 or 3 (default 2)

    Returns
    -------
    dict with keys:
        ok, f_loop_bw_hz, phase_margin_deg, icp_a, kvco_hz_per_v, n_divider,
        omega_n_rad_s, zeta, R_ohm, C1_f, C2_f,
        omega_pole2_rad_s (3rd order), f_pole2_hz (3rd order),
        phase_margin_achieved_deg, stable (bool), warnings
    """
    for val, name in [
        (f_loop_bw_hz, "f_loop_bw_hz"), (phase_margin_deg, "phase_margin_deg"),
        (icp_a, "icp_a"), (kvco_hz_per_v, "kvco_hz_per_v"), (n_divider, "n_divider"),
    ]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    if order not in (2, 3):
        return {"ok": False, "reason": "order must be 2 or 3"}

    omega_bw = _TWO_PI * f_loop_bw_hz
    phi_m_rad = math.radians(phase_margin_deg)
    tan_phi = math.tan(phi_m_rad)

    # Banerjee closed-form ζ from phase margin (approximate, ±2° accuracy)
    zeta = tan_phi / 2.0 + math.sqrt(tan_phi ** 2 / 4.0 + 1.0) / 2.0

    # ωn from ωBW (Gardner 2005 §5.3 approximation; ωBW ≈ ωn × correction)
    # For ζ in (0.3, 2.0) the correction is small; use ωBW ≈ ωn
    omega_n = omega_bw  # first approximation

    # Refine ωn: ωBW = ωn × sqrt(1 + 2ζ² + sqrt(4ζ⁴ + 4ζ² + 2))
    correction = math.sqrt(1.0 + 2.0 * zeta ** 2 + math.sqrt(4 * zeta ** 4 + 4 * zeta ** 2 + 2.0))
    omega_n = omega_bw / correction

    kvco_rad = _TWO_PI * kvco_hz_per_v

    # C1 from open-loop gain at ωn
    C1 = icp_a * kvco_rad / (_TWO_PI * n_divider * omega_n ** 2)

    # R from damping ratio
    R = 2.0 * zeta / (omega_n * C1)

    # C2 for reference spur suppression (rule of thumb: C2 = C1/10)
    C2 = C1 / 10.0

    # Achieved phase margin (Banerjee 2006 §2.6):
    # The lead-lag filter contributes atan(ω×τ_z) - atan(ω×τ_p)
    # where τ_z = R×C1, τ_p = R×C2/(C1+C2) ≈ R×C2 (since C1 >> C2)
    # Phase margin = atan(ωn×R×C1) - atan(ωn×R×C2)
    # For pure 2nd-order (no C2), pm = atan(2ζ).
    phi_achieved_rad = (
        math.atan(omega_n * R * C1)
        - math.atan(omega_n * R * C2)
    )
    phi_achieved_deg = math.degrees(phi_achieved_rad)

    stable = phi_achieved_deg >= 45.0

    result: dict = {
        "ok": True,
        "f_loop_bw_hz": f_loop_bw_hz,
        "phase_margin_deg": phase_margin_deg,
        "icp_a": icp_a,
        "kvco_hz_per_v": kvco_hz_per_v,
        "n_divider": n_divider,
        "order": order,
        "omega_n_rad_s": round(omega_n, 4),
        "f_n_hz": round(omega_n / _TWO_PI, 4),
        "zeta": round(zeta, 6),
        "R_ohm": round(R, 4),
        "C1_f": C1,
        "C1_pf": round(C1 * 1e12, 4),
        "C2_f": C2,
        "C2_pf": round(C2 * 1e12, 4),
        "phase_margin_achieved_deg": round(phi_achieved_deg, 2),
        "stable": stable,
        "warnings": [],
    }

    if order == 3:
        # 3rd-order: additional pole at ω_p2 = 1/(R×C2)
        omega_p2 = 1.0 / (R * C2)
        result["omega_pole2_rad_s"] = round(omega_p2, 4)
        result["f_pole2_hz"] = round(omega_p2 / _TWO_PI, 4)
        if omega_p2 < 10.0 * omega_n:
            msg = (
                f"3rd-order: ω_pole2 ({omega_p2/(omega_n):.1f}×ωn) < 10×ωn; "
                "loop may be marginally stable. Increase C2 for stronger attenuation."
            )
            warnings.warn(msg, stacklevel=2)
            result["warnings"].append(msg)

    if not stable:
        msg = (
            f"Unstable loop: phase margin {phi_achieved_deg:.1f}° < 45°. "
            "Increase phase margin or reduce loop bandwidth."
        )
        warnings.warn(msg, stacklevel=2)
        result["warnings"].append(msg)
    elif phase_margin_deg < 45.0:
        msg = (
            f"Requested phase margin {phase_margin_deg:.1f}° < 45°. "
            "May result in peaking and poor transient response."
        )
        warnings.warn(msg, stacklevel=2)
        result["warnings"].append(msg)

    # Reference spur note
    result["ref_spur_note"] = (
        "Reference spur attenuation improves with larger C2 and smaller Kvco. "
        f"C2/C1 ratio = {C2/C1:.2f}; spur suppression ≈ {20*math.log10(1/(omega_n*R*C2+1e-30)):.1f} dB (rough)."
        if R * C2 > 0 else "n/a"
    )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 11. PLL lock time & loop bandwidth
# ═══════════════════════════════════════════════════════════════════════════════


def pll_lock_time(
    f_loop_bw_hz: float,
    zeta: float,
    f_step_hz: float,
    epsilon_hz: float = 1.0,
) -> dict:
    """
    Estimate PLL lock time for a frequency step.

    Model (Banerjee 2006 §3.8 / Gardner 2005 §5):
        t_lock ≈ −ln(ε_freq / f_step) / (ζ × ωn)

    Valid for type-II 2nd-order PLL in lock-acquisition phase.
    Assumes linear model (no cycle-slip).

    Parameters
    ----------
    f_loop_bw_hz : float — loop bandwidth [Hz]
    zeta         : float — damping ratio
    f_step_hz    : float — frequency step size [Hz]
    epsilon_hz   : float — frequency accuracy at lock [Hz] (default 1.0 Hz)

    Returns
    -------
    dict with keys:
        ok, f_loop_bw_hz, zeta, f_step_hz, epsilon_hz,
        omega_n_rad_s, t_lock_s, warnings
    """
    for val, name in [
        (f_loop_bw_hz, "f_loop_bw_hz"), (zeta, "zeta"),
        (f_step_hz, "f_step_hz"), (epsilon_hz, "epsilon_hz"),
    ]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    if epsilon_hz >= f_step_hz:
        return {
            "ok": False,
            "reason": (
                f"epsilon_hz ({epsilon_hz} Hz) must be < f_step_hz ({f_step_hz} Hz)"
            ),
        }

    omega_n = _TWO_PI * f_loop_bw_hz
    t_lock = -math.log(epsilon_hz / f_step_hz) / (zeta * omega_n)

    result = {
        "ok": True,
        "f_loop_bw_hz": f_loop_bw_hz,
        "zeta": zeta,
        "f_step_hz": f_step_hz,
        "epsilon_hz": epsilon_hz,
        "omega_n_rad_s": omega_n,
        "t_lock_s": round(t_lock, 9),
        "t_lock_us": round(t_lock * 1e6, 4),
        "warnings": [],
    }

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Phase noise → jitter (integrated RMS)
# ═══════════════════════════════════════════════════════════════════════════════


def phase_noise_to_jitter(
    f_osc_hz: float,
    phase_noise_dbc_hz: float,
    integration_bw_hz: float,
) -> dict:
    """
    Convert single-sideband phase noise to integrated RMS jitter.

    Approximation for a single phase-noise spectral density value L(f) [dBc/Hz]
    integrated over a one-sided bandwidth BW:

        L_lin = 10^(L_dBc / 10)               [linear power ratio]
        σ_phase_rms [rad] = sqrt(2 × L_lin × BW)   [total phase variance]
        σ_jitter_s        = σ_phase_rms / (2π × f_osc)

    Note: this is a single-bin approximation. For a shaped noise floor,
    integrate L(f) numerically. A note about reference spurs is appended.

    Reference spur contribution is NOT included here; it must be added
    separately as σ_spur ≈ A_spur / (2 × sqrt(2) × π × f_osc).

    Parameters
    ----------
    f_osc_hz            : float — oscillator frequency [Hz]
    phase_noise_dbc_hz  : float — phase noise floor [dBc/Hz] (typically negative)
    integration_bw_hz   : float — one-sided integration bandwidth [Hz]

    Returns
    -------
    dict with keys:
        ok, f_osc_hz, phase_noise_dbc_hz, integration_bw_hz,
        phase_noise_lin, sigma_phase_rad, sigma_jitter_s,
        sigma_jitter_ps, sigma_jitter_fs, ref_spur_note, warnings
    """
    for val, name in [
        (f_osc_hz, "f_osc_hz"), (integration_bw_hz, "integration_bw_hz"),
    ]:
        err = _pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    err = _finite(phase_noise_dbc_hz, "phase_noise_dbc_hz")
    if err:
        return {"ok": False, "reason": err}

    l_lin = 10.0 ** (phase_noise_dbc_hz / 10.0)
    sigma_phase = math.sqrt(2.0 * l_lin * integration_bw_hz)
    sigma_jitter = sigma_phase / (_TWO_PI * f_osc_hz)

    result = {
        "ok": True,
        "f_osc_hz": f_osc_hz,
        "phase_noise_dbc_hz": phase_noise_dbc_hz,
        "integration_bw_hz": integration_bw_hz,
        "phase_noise_lin": l_lin,
        "sigma_phase_rad": sigma_phase,
        "sigma_jitter_s": sigma_jitter,
        "sigma_jitter_ps": round(sigma_jitter * 1e12, 6),
        "sigma_jitter_fs": round(sigma_jitter * 1e15, 3),
        "ref_spur_note": (
            "Reference spur contribution not included. "
            "For a spur at offset f_spur with amplitude A_spur_dbc, "
            "σ_spur ≈ 10^(A_spur_dbc/20) / (2π√2 × f_osc × f_spur × T_cycle)."
        ),
        "warnings": [],
    }

    return result
