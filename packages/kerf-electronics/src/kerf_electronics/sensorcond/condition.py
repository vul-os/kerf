"""
Sensor signal-conditioning design — closed-form models.

Distinct from:
  kerf_electronics.afilter  — general analog filter design (Butterworth/Chebyshev/Bessel)
  kerf_electronics.dsp      — digital signal processing (FIR/IIR, FFT)
  kerf_electronics.si       — PCB signal integrity (Z0, crosstalk, propagation)
  kerf_electronics.emc      — EMC/EMI pre-compliance estimation

Covered topics
--------------
  Wheatstone bridge
      quarter-bridge, half-bridge, full-bridge output voltage vs strain & gauge factor;
      lead-wire resistance correction (3-wire and 2-wire); nonlinearity error;
      bridge excitation power & maximum safe excitation voltage.

  Strain-gauge → stress conversion
      using Young's modulus.

  RTD (Resistance Temperature Detector)
      Callendar-Van Dusen (CVD) forward (T → R) and inverse (R → T);
      lead-wire error for 2-wire, 3-wire, and 4-wire connections.

  Thermocouple
      NIST inverse polynomial (voltage → temperature) for types J, K, T, E, N, S, R, B;
      cold-junction compensation.

  Instrumentation amplifier
      gain, output-referred offset, CMRR-limited output error, gain drift contribution.

  ADC resolution
      required bits for a target measurement resolution;
      ENOB from noise spectral density.

  Anti-alias filter corner frequency selection.

  4-20 mA current loop
      engineering-unit ↔ current scaling; burden/compliance voltage.

  Noise budget (RSS).

  Sallen-Key vs MFB topology selection for the anti-alias filter.

All functions are pure Python (math module only) and follow the kerf
never-raise contract: validation errors are returned as dicts with
{ok: False, reason: str}; warnings are issued via the standard warnings
module for out-of-range, under-resolved, or CMRR-limited conditions;
exceptions are never raised to callers.

References
----------
  [1] Horowitz & Hill, "The Art of Electronics", 3rd ed., Cambridge, 2015.
  [2] Fraden, J., "Handbook of Modern Sensors", 4th ed., Springer, 2010.
  [3] NIST ITS-90 Thermocouple tables (https://srdata.nist.gov/its90/main).
  [4] Bentley, J.P., "Principles of Measurement Systems", 4th ed., Pearson, 2005.
  [5] IEC 60751:2008 — Industrial RTDs and Platinum Resistance Thermometers.
  [6] Analog Devices, "Instrumentation Amplifier Application Note AN-202".
  [7] Texas Instruments, "Signal Conditioning for Pressure Sensors", SLOA033.

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Optional

# ── Validation helpers ────────────────────────────────────────────────────────


def _chk_pos(value, name: str) -> Optional[str]:
    """Return error string if value is not a strictly positive real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive number, got {value!r}"
    return None


def _chk_nonneg(value, name: str) -> Optional[str]:
    """Return error string if value is not a non-negative real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _chk_real(value, name: str) -> Optional[str]:
    """Return error string if value is not a finite real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return f"{name} must be a finite real number, got {value!r}"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. Wheatstone bridge
# ══════════════════════════════════════════════════════════════════════════════

def wheatstone_bridge_output(
    excitation_v: float,
    gauge_factor: float,
    strain_ue: float,
    config: str = "quarter",
    lead_resistance_ohm: float = 0.0,
    nominal_resistance_ohm: float = 350.0,
) -> dict:
    """
    Compute the output voltage of a Wheatstone bridge strain-gauge circuit.

    Supports quarter-bridge (one active arm), half-bridge (two active arms,
    opposite sign convention, e.g. bending beam), and full-bridge (four active
    arms, two in tension, two in compression).

    Model
    -----
    Gauge resistance change:
        ΔR/R = GF × ε          where ε = strain_ue × 1e-6

    Quarter-bridge (linearised):
        Vout = (Vex / 4) × GF × ε        [Fraden §6.4 / Bentley §4.3]
        Exact (nonlinear):
        Vout = Vex × (ΔR/R) / (4 + 2×ΔR/R)

    Half-bridge (two complementary arms):
        Vout = (Vex / 2) × GF × ε        (linearised)
        Exact: Vout = Vex × (ΔR/R) / (2 + 0)   (complementary cancels 2nd order)

    Full-bridge (four active arms, balanced):
        Vout = Vex × GF × ε              (linearised, exact for ideal full bridge)

    Lead-wire correction (2-wire only; 3-wire and 4-wire are handled elsewhere):
        The lead resistance adds to the active arm resistance, reducing sensitivity.
        Corrected GF_eff = GF × Rg / (Rg + Rlead)
        where Rg = nominal_resistance_ohm.

    Nonlinearity error is flagged when ΔR/R > 0.01 (1%) for quarter/half bridges
    via warnings.warn.

    Parameters
    ----------
    excitation_v          : float — bridge excitation voltage [V]
    gauge_factor          : float — strain-gauge gauge factor (dimensionless, typical 2.0)
    strain_ue             : float — applied strain [µε = microstrain]
    config                : str   — 'quarter', 'half', or 'full' (default 'quarter')
    lead_resistance_ohm   : float — total lead resistance for the active arm [Ω] (default 0)
    nominal_resistance_ohm: float — nominal gauge resistance Rg [Ω] (default 350)

    Returns
    -------
    dict with keys:
        ok, config, excitation_v, gauge_factor, strain_ue,
        delta_r_over_r, vout_linearised_v, vout_exact_v,
        nonlinearity_error_pct, lead_wire_sensitivity_loss_pct,
        lead_resistance_ohm, nominal_resistance_ohm
    """
    err = _chk_pos(excitation_v, "excitation_v")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(gauge_factor, "gauge_factor")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_real(strain_ue, "strain_ue")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(lead_resistance_ohm, "lead_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(nominal_resistance_ohm, "nominal_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    config = config.lower().strip()
    if config not in ("quarter", "half", "full"):
        return {"ok": False, "reason": "config must be 'quarter', 'half', or 'full'"}

    strain = strain_ue * 1e-6
    rg = nominal_resistance_ohm
    rl = lead_resistance_ohm

    # Lead-wire sensitivity loss
    if rl > 0:
        gf_eff = gauge_factor * rg / (rg + rl)
        lead_loss_pct = (1.0 - gf_eff / gauge_factor) * 100.0
    else:
        gf_eff = gauge_factor
        lead_loss_pct = 0.0

    delta_r_over_r = gf_eff * strain  # ΔR/R

    # Nonlinearity check (quarter and half bridges are susceptible)
    nonlin_threshold = 0.01
    if config in ("quarter", "half") and abs(delta_r_over_r) > nonlin_threshold:
        warnings.warn(
            f"wheatstone_bridge_output: ΔR/R = {delta_r_over_r:.4f} exceeds 1%; "
            f"nonlinearity error is significant for {config}-bridge configuration.",
            stacklevel=2,
        )

    x = delta_r_over_r  # shorthand
    vex = excitation_v

    if config == "quarter":
        # Linearised: Vout = (Vex/4) × GF × ε
        vout_lin = (vex / 4.0) * x
        # Exact Wheatstone bridge output
        denom = 4.0 + 2.0 * x
        vout_exact = vex * x / denom if denom != 0 else 0.0
    elif config == "half":
        # Two complementary active arms
        vout_lin = (vex / 2.0) * x
        vout_exact = (vex / 2.0) * x  # cancellation of even-order nonlinearity
    else:  # full
        # Four active arms
        vout_lin = vex * x
        vout_exact = vex * x

    # Nonlinearity error (quarter only — meaningful)
    if abs(vout_lin) > 0:
        nonlin_error_pct = abs(vout_exact - vout_lin) / abs(vout_lin) * 100.0
    else:
        nonlin_error_pct = 0.0

    return {
        "ok": True,
        "config": config,
        "excitation_v": excitation_v,
        "gauge_factor": gauge_factor,
        "strain_ue": strain_ue,
        "delta_r_over_r": round(delta_r_over_r, 8),
        "vout_linearised_v": round(vout_lin, 9),
        "vout_exact_v": round(vout_exact, 9),
        "nonlinearity_error_pct": round(nonlin_error_pct, 4),
        "lead_wire_sensitivity_loss_pct": round(lead_loss_pct, 4),
        "lead_resistance_ohm": lead_resistance_ohm,
        "nominal_resistance_ohm": nominal_resistance_ohm,
        "formula": "Fraden §6.4 / Bentley §4.3 Wheatstone bridge",
    }


def bridge_excitation_power(
    excitation_v: float,
    nominal_resistance_ohm: float = 350.0,
) -> dict:
    """
    Compute bridge excitation power dissipated per arm and total.

    For a balanced bridge (all four arms = Rg):
        I_arm = Vex / (2 × Rg)
        P_arm = Vex² / (4 × Rg)
        P_total = Vex² / Rg

    Self-heating warning is issued when P_arm exceeds 30 mW (typical limit
    for bonded strain gauges per Vishay Measurements Group Application Note B-127).

    Parameters
    ----------
    excitation_v           : float — bridge excitation voltage [V]
    nominal_resistance_ohm : float — nominal gauge resistance [Ω] (default 350 Ω)

    Returns
    -------
    dict with keys: ok, excitation_v, nominal_resistance_ohm,
                    i_arm_a, p_arm_w, p_total_w, max_safe_excitation_v
    """
    err = _chk_pos(excitation_v, "excitation_v")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(nominal_resistance_ohm, "nominal_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}

    rg = nominal_resistance_ohm
    i_arm = excitation_v / (2.0 * rg)
    p_arm = excitation_v ** 2 / (4.0 * rg)
    p_total = excitation_v ** 2 / rg

    # Maximum safe excitation: P_arm = 30 mW → Vex_max = sqrt(4 × Rg × 30e-3)
    p_limit = 30e-3
    vex_max = math.sqrt(4.0 * rg * p_limit)

    if p_arm > p_limit:
        warnings.warn(
            f"bridge_excitation_power: arm power {p_arm*1e3:.1f} mW exceeds "
            f"typical 30 mW self-heating limit for bonded strain gauges. "
            f"Maximum safe excitation: {vex_max:.2f} V.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "excitation_v": excitation_v,
        "nominal_resistance_ohm": rg,
        "i_arm_a": round(i_arm, 6),
        "p_arm_w": round(p_arm, 6),
        "p_total_w": round(p_total, 6),
        "max_safe_excitation_v": round(vex_max, 3),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. Strain-gauge → stress
# ══════════════════════════════════════════════════════════════════════════════

def strain_to_stress(
    strain_ue: float,
    youngs_modulus_gpa: float,
) -> dict:
    """
    Convert microstrain to stress using Hooke's law.

    σ = E × ε

    Parameters
    ----------
    strain_ue          : float — strain [µε]
    youngs_modulus_gpa : float — Young's modulus [GPa]
                                  (steel ≈ 200 GPa, aluminium ≈ 70 GPa)

    Returns
    -------
    dict with keys: ok, strain_ue, youngs_modulus_gpa, stress_pa, stress_mpa
    """
    err = _chk_real(strain_ue, "strain_ue")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(youngs_modulus_gpa, "youngs_modulus_gpa")
    if err:
        return {"ok": False, "reason": err}

    strain = strain_ue * 1e-6
    E = youngs_modulus_gpa * 1e9  # Pa
    stress_pa = E * strain
    stress_mpa = stress_pa * 1e-6

    return {
        "ok": True,
        "strain_ue": strain_ue,
        "youngs_modulus_gpa": youngs_modulus_gpa,
        "stress_pa": round(stress_pa, 3),
        "stress_mpa": round(stress_mpa, 6),
        "formula": "σ = E × ε  (Hooke's law)",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. RTD — Callendar-Van Dusen
# ══════════════════════════════════════════════════════════════════════════════

# IEC 60751 PT100/PT1000 CVD coefficients
_CVD_A = 3.9083e-3   # °C⁻¹
_CVD_B = -5.775e-7   # °C⁻²
_CVD_C = -4.183e-12  # °C⁻⁴  (only valid for T < 0 °C)

# Typical PT100 at 0 °C
_R0_PT100 = 100.0    # Ω at 0 °C


def rtd_resistance(
    temperature_c: float,
    r0_ohm: float = 100.0,
    alpha: float = _CVD_A,
    beta: float = _CVD_B,
    delta: float = _CVD_C,
) -> dict:
    """
    Callendar-Van Dusen forward model: temperature → resistance.

    IEC 60751:2008 equations:
        For T ≥ 0 °C:   R(T) = R₀ × (1 + A×T + B×T²)
        For T < 0 °C:   R(T) = R₀ × (1 + A×T + B×T² + C×(T−100)×T³)

    Valid range: −200 °C to +850 °C for Pt RTDs.

    Parameters
    ----------
    temperature_c : float — temperature [°C]
    r0_ohm        : float — resistance at 0 °C [Ω] (default 100.0 for PT100)
    alpha         : float — CVD coefficient A (default IEC 60751: 3.9083e-3 °C⁻¹)
    beta          : float — CVD coefficient B (default IEC 60751: −5.775e-7 °C⁻²)
    delta         : float — CVD coefficient C (default IEC 60751: −4.183e-12 °C⁻⁴)

    Returns
    -------
    dict with keys: ok, temperature_c, r0_ohm, resistance_ohm
    """
    err = _chk_real(temperature_c, "temperature_c")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(r0_ohm, "r0_ohm")
    if err:
        return {"ok": False, "reason": err}

    if temperature_c < -200.0 or temperature_c > 850.0:
        warnings.warn(
            f"rtd_resistance: temperature {temperature_c} °C is outside the "
            f"IEC 60751 valid range −200…850 °C.  Result may be inaccurate.",
            stacklevel=2,
        )

    T = temperature_c
    if T >= 0.0:
        R = r0_ohm * (1.0 + alpha * T + beta * T ** 2)
    else:
        R = r0_ohm * (1.0 + alpha * T + beta * T ** 2 + delta * (T - 100.0) * T ** 3)

    return {
        "ok": True,
        "temperature_c": temperature_c,
        "r0_ohm": r0_ohm,
        "resistance_ohm": round(R, 6),
        "formula": "IEC 60751 Callendar-Van Dusen",
    }


def rtd_temperature(
    resistance_ohm: float,
    r0_ohm: float = 100.0,
    alpha: float = _CVD_A,
    beta: float = _CVD_B,
) -> dict:
    """
    Callendar-Van Dusen inverse model: resistance → temperature.

    For T ≥ 0 °C (quadratic, closed-form):
        T = (−A + sqrt(A² − 4B×(1 − R/R₀))) / (2B)

    For negative temperatures the cubic C term is required; a Newton–Raphson
    iteration is used (converges in <10 iterations for Pt RTDs).

    Parameters
    ----------
    resistance_ohm : float — measured resistance [Ω]
    r0_ohm         : float — resistance at 0 °C [Ω] (default 100.0 for PT100)
    alpha          : float — CVD coefficient A (default 3.9083e-3 °C⁻¹)
    beta           : float — CVD coefficient B (default −5.775e-7 °C⁻²)

    Returns
    -------
    dict with keys: ok, resistance_ohm, r0_ohm, temperature_c
    """
    err = _chk_pos(resistance_ohm, "resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(r0_ohm, "r0_ohm")
    if err:
        return {"ok": False, "reason": err}

    # Minimum R at −200 °C
    r_at_minus200 = rtd_resistance(-200.0, r0_ohm, alpha, beta, _CVD_C)
    if resistance_ohm < r_at_minus200.get("resistance_ohm", 0) - 0.1:
        warnings.warn(
            f"rtd_temperature: resistance {resistance_ohm:.3f} Ω is below the "
            f"PT100 −200 °C value.  Result may be invalid.",
            stacklevel=2,
        )

    # Quadratic formula for T ≥ 0
    # R/R₀ = 1 + A×T + B×T²  →  B×T² + A×T + (1 − R/R₀) = 0
    rn = resistance_ohm / r0_ohm
    discriminant = alpha ** 2 - 4.0 * beta * (1.0 - rn)
    if discriminant < 0:
        return {"ok": False, "reason": "negative discriminant; check R0 and coefficients"}
    T_pos = (-alpha + math.sqrt(discriminant)) / (2.0 * beta)

    # If T_pos >= 0, return it directly (C term not needed)
    if T_pos >= 0.0:
        return {
            "ok": True,
            "resistance_ohm": resistance_ohm,
            "r0_ohm": r0_ohm,
            "temperature_c": round(T_pos, 4),
            "formula": "IEC 60751 CVD inverse (quadratic, T≥0)",
        }

    # Newton–Raphson for T < 0 (with C term)
    T = T_pos  # initial guess
    for _ in range(20):
        fwd = rtd_resistance(T, r0_ohm, alpha, beta, _CVD_C)
        R_calc = fwd["resistance_ohm"]
        # dR/dT = R₀ × (A + 2B×T + C×(4T³ − 300T²))
        dRdT = r0_ohm * (alpha + 2.0 * beta * T + _CVD_C * (4.0 * T ** 3 - 300.0 * T ** 2))
        delta_T = (resistance_ohm - R_calc) / dRdT if dRdT != 0 else 0.0
        T += delta_T
        if abs(delta_T) < 1e-6:
            break

    return {
        "ok": True,
        "resistance_ohm": resistance_ohm,
        "r0_ohm": r0_ohm,
        "temperature_c": round(T, 4),
        "formula": "IEC 60751 CVD inverse (Newton-Raphson, T<0)",
    }


def rtd_lead_wire_error(
    measurement_resistance_ohm: float,
    lead_resistance_ohm: float,
    wiring: str = "3-wire",
    r0_ohm: float = 100.0,
) -> dict:
    """
    Compute the temperature error introduced by lead-wire resistance in RTD circuits.

    2-wire: Both leads add directly to the measured resistance.
        R_error = 2 × Rlead
        ΔT = (R_error / R₀) / alpha_approx

    3-wire: Kelvin (3-wire) connection cancels one lead, leaving one unpaired
        differential lead:
        R_error ≈ 0  (ideal match) / Rlead (mismatch)
        For balanced leads: R_error ≈ 0; this function assumes ideal balance.

    4-wire: Kelvin (4-wire) — zero lead error.

    Alpha_approx = CVD coefficient A ≈ 3.85e-3 °C⁻¹ (sensitivity of Pt100 near 0 °C).

    Parameters
    ----------
    measurement_resistance_ohm : float — raw measured resistance [Ω]
    lead_resistance_ohm        : float — resistance of one lead [Ω]
    wiring                     : str   — '2-wire', '3-wire', '4-wire' (default '3-wire')
    r0_ohm                     : float — RTD R₀ [Ω] (default 100.0)

    Returns
    -------
    dict with keys: ok, wiring, r_error_ohm, temperature_error_c,
                    corrected_resistance_ohm
    """
    err = _chk_pos(measurement_resistance_ohm, "measurement_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(lead_resistance_ohm, "lead_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(r0_ohm, "r0_ohm")
    if err:
        return {"ok": False, "reason": err}
    wiring = wiring.lower().replace(" ", "").replace("-", "")
    if wiring not in ("2wire", "3wire", "4wire"):
        return {"ok": False, "reason": "wiring must be '2-wire', '3-wire', or '4-wire'"}

    alpha_approx = 3.85e-3  # Pt100 sensitivity ~ 0.385 Ω/°C at 0 °C

    if wiring == "2wire":
        r_error = 2.0 * lead_resistance_ohm
    elif wiring == "3wire":
        # Ideal 3-wire cancels both leads; real case: small imbalance assumed zero
        r_error = 0.0
    else:  # 4wire
        r_error = 0.0

    temp_error = r_error / (r0_ohm * alpha_approx)
    corrected_r = measurement_resistance_ohm - r_error

    if wiring == "2wire" and abs(temp_error) > 0.5:
        warnings.warn(
            f"rtd_lead_wire_error: 2-wire lead error {temp_error:.2f} °C exceeds 0.5 °C. "
            f"Consider 3-wire or 4-wire connection.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "wiring": wiring,
        "measurement_resistance_ohm": measurement_resistance_ohm,
        "lead_resistance_ohm": lead_resistance_ohm,
        "r_error_ohm": round(r_error, 6),
        "temperature_error_c": round(temp_error, 4),
        "corrected_resistance_ohm": round(corrected_r, 6),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. Thermocouple — NIST inverse polynomial (voltage → temperature)
# ══════════════════════════════════════════════════════════════════════════════

# NIST ITS-90 inverse polynomial coefficients
# Format: {type: [(v_min_mv, v_max_mv, [d0, d1, d2, ... dn]), ...]}
# Coefficients are for voltage in mV → temperature in °C.
# Source: https://srdata.nist.gov/its90/main

_NIST_INVERSE = {
    "J": [
        (-8.095, 0.0, [0.0, 1.9528268e1, -1.2286185, -1.0752178, -5.9086933e-1,
                       -1.7256713e-1, -2.8131513e-2, -2.3963370e-3, -8.3823321e-5]),
        (0.0, 42.919, [0.0, 1.978425e1, -2.001204e-1, 1.036969e-2, -2.549687e-4,
                       3.585153e-6, -5.344285e-8, 5.099890e-10, 0.0]),
        (42.919, 69.553, [-3.11358187e3, 3.00543684e2, -9.94773230, 1.70276630e-1,
                           -1.43033468e-3, 4.73886084e-6, 0.0, 0.0, 0.0]),
    ],
    "K": [
        (-5.891, 0.0, [0.0, 2.5173462e1, -1.1662878, -1.0833638, -8.9773540e-1,
                       -3.7342377e-1, -8.6632643e-2, -1.0450598e-2, -5.1920577e-4]),
        (0.0, 20.644, [0.0, 2.508355e1, 7.860106e-2, -2.503131e-1, 8.315270e-2,
                       -1.228034e-2, 9.804036e-4, -4.413030e-5, 1.057734e-6, -1.052755e-8]),
        (20.644, 54.886, [-1.318058e2, 4.830222e1, -1.646031, 5.464731e-2, -9.650715e-4,
                           8.802193e-6, -3.110810e-8, 0.0, 0.0]),
    ],
    "T": [
        (-5.603, 0.0, [0.0, 2.5949192e1, -2.1316967e-1, 7.9018692e-1, 4.2527777e-1,
                       1.3304473e-1, 2.0241446e-2, 1.2668171e-3, 0.0]),
        (0.0, 20.872, [0.0, 2.592800e1, -7.602961e-1, 4.637791e-2, -2.165394e-3,
                       6.048144e-5, -7.293422e-7, 0.0, 0.0]),
    ],
    "E": [
        (-8.825, 0.0, [0.0, 1.6977288e1, -4.3514970e-1, -1.5859697e-1, -9.2502871e-2,
                       -2.6084314e-2, -4.1360199e-3, -3.4034030e-4, -1.1564890e-5]),
        (0.0, 76.373, [0.0, 1.7057035e1, -2.3301759e-1, 6.5435585e-3, -7.3562749e-5,
                       -1.7896001e-6, 8.4036165e-8, -1.3735879e-9, 1.0629823e-11,
                       -3.2447087e-14]),
    ],
    "N": [
        (-3.990, 0.0, [0.0, 3.8436847e1, 1.1010485, 5.2229312, 7.2060525,
                       5.8488586, 2.7754916, 7.7075166e-1, 1.1582665e-1, 7.3138868e-3]),
        (0.0, 20.613, [0.0, 3.86896e1, -1.08267, 4.70205e-2, -2.12169e-6,
                       -1.17272e-4, 5.39280e-6, -7.98156e-8, 0.0]),
        (20.613, 47.513, [1.972485e1, 3.300943e1, -3.915159e-1, 9.855391e-3,
                           -1.274371e-4, 7.767022e-7, 0.0, 0.0, 0.0]),
    ],
    "S": [
        (-0.235, 1.874, [0.0, 1.84949460e2, -8.00504062e1, 1.02237430e2,
                          -1.52248592e2, 1.88821343e2, -1.59085941e2, 8.23027880e1,
                          -2.34181944e1, 2.79786260]),
        (1.874, 11.950, [1.291507177, 1.466298863e2, -1.534713402e1, 3.145945973,
                          -4.163257839e-1, 3.187963771e-2, -1.291637500e-3, 2.183475087e-5,
                          -1.447379511e-7, 8.211272125e-9]),
        (11.950, 17.536, [-8.087801117e1, 1.621573104e2, -8.536869453, 4.719686976e-1,
                           -1.441693666e-2, 2.081618890e-4, 0.0, 0.0, 0.0]),
        (17.536, 18.693, [5.333875126e4, -1.235892298e4, 1.092657613e3,
                           -4.265693686e1, 6.247205420e-1, 0.0, 0.0, 0.0, 0.0]),
    ],
    "R": [
        (-0.226, 1.923, [0.0, 1.88984213e2, -9.34633971e1, 1.30207751e2,
                          -2.27031500e2, 3.51496472e2, -3.95520905e2, 2.77892560e2,
                          -1.04516093e2, 1.97663290e1]),
        (1.923, 13.228, [1.334584505, 1.472644573e2, -1.844024844e1, 4.031129726,
                          -6.249428360e-1, 6.468412046e-2, -4.458750426e-3, 1.994710149e-4,
                          -5.313401790e-6, 6.481976217e-8]),
        (13.228, 19.739, [-8.199599416e1, 1.553962042e2, -8.342197663, 4.279433549e-1,
                           -1.191577910e-2, 1.492290091e-4, 0.0, 0.0, 0.0]),
        (19.739, 21.103, [3.406177836e4, -7.023729171e3, 5.582903813e2,
                           -1.952394635e1, 2.560740231e-1, 0.0, 0.0, 0.0, 0.0]),
    ],
    "B": [
        (0.291, 2.431, [9.8423321e1, 6.9971500e2, -8.4765304e2, 1.0052644e3,
                         -8.3345952e2, 4.5508542e2, -1.5523037e2, 2.9886750e1, -2.4742860]),
        (2.431, 13.820, [2.1315071e2, 2.8510504e2, -5.2742887e1, 9.9160804,
                          -1.2965303, 1.1195870e-1, -6.0625199e-3, 1.8661696e-4, -2.4878585e-6]),
    ],
}

_TC_VALID_TYPES = tuple(_NIST_INVERSE.keys())


def thermocouple_temperature(
    voltage_mv: float,
    tc_type: str,
    cold_junction_temp_c: float = 0.0,
) -> dict:
    """
    Convert thermocouple EMF (millivolts) to temperature using NIST ITS-90
    inverse polynomial, with cold-junction compensation.

    Cold-junction compensation:
        The measured voltage includes both the sensing-junction and reference-junction
        contribution.  With a cold-junction temperature T_cj != 0 °C:
            V_effective = V_measured + V_cj(T_cj)
        where V_cj is obtained from the forward NIST polynomial for the same TC type.
        Since we only have the inverse polynomial here, the CJC is handled by
        adding the RTD-measured cold-junction temperature's equivalent voltage using
        the Seebeck coefficient at 0 °C:
            V_cj ≈ S₀ × T_cj   (linear approximation around 0 °C)
        For a more accurate result, the forward NIST polynomial should be used.
        This function issues a warning if T_cj > 5 °C to alert about linearity.

    Valid thermocouple types: J, K, T, E, N, S, R, B.

    Parameters
    ----------
    voltage_mv           : float — measured thermocouple EMF [mV]
    tc_type              : str   — thermocouple type (J/K/T/E/N/S/R/B)
    cold_junction_temp_c : float — cold-junction (reference) temperature [°C] (default 0)

    Returns
    -------
    dict with keys: ok, tc_type, voltage_mv, cold_junction_temp_c,
                    temperature_c, cjc_voltage_mv
    """
    err = _chk_real(voltage_mv, "voltage_mv")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_real(cold_junction_temp_c, "cold_junction_temp_c")
    if err:
        return {"ok": False, "reason": err}
    tc_type = tc_type.upper().strip()
    if tc_type not in _NIST_INVERSE:
        return {
            "ok": False,
            "reason": (
                f"tc_type must be one of {list(_NIST_INVERSE.keys())}, got {tc_type!r}"
            ),
        }

    # Approximate Seebeck coefficients at 0 °C [µV/°C] for CJC
    _S0 = {"J": 51.7, "K": 39.4, "T": 38.7, "E": 58.7,
           "N": 25.9, "S": 6.4, "R": 6.0, "B": 0.0}
    s0_uv_c = _S0.get(tc_type, 40.0)
    cjc_voltage_mv = s0_uv_c * cold_junction_temp_c * 1e-3  # µV/°C × °C → µV → mV

    if abs(cold_junction_temp_c) > 5.0:
        warnings.warn(
            f"thermocouple_temperature: cold-junction temp {cold_junction_temp_c} °C "
            f"is >5 °C from 0 °C reference; linear CJC approximation may introduce "
            f"up to ~0.5 °C error.  Use a forward NIST polynomial for exact CJC.",
            stacklevel=2,
        )

    v_eff = voltage_mv + cjc_voltage_mv

    # Find the applicable polynomial range
    segments = _NIST_INVERSE[tc_type]
    coeffs = None
    for v_lo, v_hi, c in segments:
        if v_lo <= v_eff <= v_hi:
            coeffs = c
            break
    if coeffs is None:
        # Out of range — use nearest segment
        if v_eff < segments[0][0]:
            coeffs = segments[0][2]
            warnings.warn(
                f"thermocouple_temperature: voltage {v_eff:.4f} mV is below the "
                f"Type-{tc_type} NIST range ({segments[0][0]} mV).  Result may be inaccurate.",
                stacklevel=2,
            )
        else:
            coeffs = segments[-1][2]
            warnings.warn(
                f"thermocouple_temperature: voltage {v_eff:.4f} mV is above the "
                f"Type-{tc_type} NIST range ({segments[-1][1]} mV).  Result may be inaccurate.",
                stacklevel=2,
            )

    # Horner evaluation
    T = 0.0
    for i, c in enumerate(coeffs):
        T += c * (v_eff ** i)

    return {
        "ok": True,
        "tc_type": tc_type,
        "voltage_mv": voltage_mv,
        "cold_junction_temp_c": cold_junction_temp_c,
        "cjc_voltage_mv": round(cjc_voltage_mv, 6),
        "effective_voltage_mv": round(v_eff, 6),
        "temperature_c": round(T, 3),
        "formula": "NIST ITS-90 inverse polynomial",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. Instrumentation amplifier — gain and error budget
# ══════════════════════════════════════════════════════════════════════════════

def instrumentation_amp_gain(
    r_gain_ohm: float,
    r_internal_ohm: float = 49.4e3,
    gain_error_pct: float = 0.5,
    offset_voltage_uv: float = 50.0,
    cmrr_db: float = 80.0,
    common_mode_v: float = 0.0,
    gain_drift_ppm_c: float = 10.0,
    temperature_delta_c: float = 25.0,
) -> dict:
    """
    Compute instrumentation amplifier (INA) gain and total output-referred error.

    Standard three-op-amp INA gain:
        G = 1 + 2 × R_internal / R_gain     [Horowitz & Hill §5.15]

    Total output-referred error (referred back to input for clarity):
        e_offset   = V_os × G         [amplified offset]
        e_cmrr     = V_cm / 10^(CMRR/20)   [CMRR-limited input error]
        e_gain_err = V_signal × gain_error_pct / 100
        e_drift    = V_os × (gain_drift_ppm_c × 1e-6 × G × ΔT)  [gain drift]

    Total input-referred RMS error (RSS):
        e_total_rms = sqrt(e_offset² + e_cmrr² + e_drift²)

    CMRR warning issued when e_cmrr > e_offset (CMRR-limited regime).

    Parameters
    ----------
    r_gain_ohm        : float — external gain-setting resistor [Ω]
    r_internal_ohm    : float — internal resistor pair (default 49.4 kΩ for INA128)
    gain_error_pct    : float — initial gain error [%] (default 0.5%)
    offset_voltage_uv : float — input offset voltage [µV] (default 50 µV)
    cmrr_db           : float — CMRR [dB] (default 80 dB)
    common_mode_v     : float — common-mode voltage at inputs [V] (default 0)
    gain_drift_ppm_c  : float — gain temperature coefficient [ppm/°C] (default 10)
    temperature_delta_c : float — expected temperature change from calibration [°C] (default 25)

    Returns
    -------
    dict with keys:
        ok, gain, r_gain_ohm, e_offset_uv, e_cmrr_uv,
        e_gain_error_pct, e_drift_uv, e_total_rms_uv, cmrr_limited
    """
    err = _chk_pos(r_gain_ohm, "r_gain_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(r_internal_ohm, "r_internal_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(offset_voltage_uv, "offset_voltage_uv")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(cmrr_db, "cmrr_db")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_real(common_mode_v, "common_mode_v")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(gain_drift_ppm_c, "gain_drift_ppm_c")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(temperature_delta_c, "temperature_delta_c")
    if err:
        return {"ok": False, "reason": err}

    gain = 1.0 + 2.0 * r_internal_ohm / r_gain_ohm

    # Input-referred errors [µV]
    e_offset_uv = offset_voltage_uv  # already input-referred
    cmrr_linear = 10.0 ** (cmrr_db / 20.0)
    e_cmrr_uv = abs(common_mode_v) / cmrr_linear * 1e6  # V → µV
    e_drift_uv = (offset_voltage_uv * gain_drift_ppm_c * 1e-6 * temperature_delta_c)

    e_total_rms_uv = math.sqrt(e_offset_uv ** 2 + e_cmrr_uv ** 2 + e_drift_uv ** 2)

    cmrr_limited = e_cmrr_uv > e_offset_uv
    if cmrr_limited:
        warnings.warn(
            f"instrumentation_amp_gain: CMRR-limited! e_cmrr={e_cmrr_uv:.1f} µV > "
            f"e_offset={e_offset_uv:.1f} µV.  "
            f"Common-mode voltage ({common_mode_v} V) dominates error budget.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "gain": round(gain, 4),
        "r_gain_ohm": r_gain_ohm,
        "e_offset_uv": round(e_offset_uv, 3),
        "e_cmrr_uv": round(e_cmrr_uv, 3),
        "e_gain_error_pct": gain_error_pct,
        "e_drift_uv": round(e_drift_uv, 3),
        "e_total_rms_uv": round(e_total_rms_uv, 3),
        "cmrr_limited": cmrr_limited,
        "formula": "Horowitz & Hill §5.15 three-op-amp INA",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. ADC resolution
# ══════════════════════════════════════════════════════════════════════════════

def adc_required_bits(
    full_scale_range_v: float,
    target_resolution_mv: float,
) -> dict:
    """
    Compute the minimum ADC bit-width for a target measurement resolution.

    N_bits ≥ ceil(log2(FSR / target_res))

    A warning is issued when ≥ 24 bits are required (typically noise-limited
    before bitwidth-limited).

    Parameters
    ----------
    full_scale_range_v    : float — ADC full-scale input range [V]
    target_resolution_mv  : float — required resolution [mV]

    Returns
    -------
    dict with keys: ok, full_scale_range_v, target_resolution_mv,
                    ideal_bits, recommended_bits, lsb_size_mv
    """
    err = _chk_pos(full_scale_range_v, "full_scale_range_v")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(target_resolution_mv, "target_resolution_mv")
    if err:
        return {"ok": False, "reason": err}

    target_res_v = target_resolution_mv * 1e-3
    ratio = full_scale_range_v / target_res_v
    ideal_bits = math.log2(ratio)
    recommended_bits = math.ceil(ideal_bits)
    lsb_size_mv = full_scale_range_v / (2 ** recommended_bits) * 1e3

    if recommended_bits >= 24:
        warnings.warn(
            f"adc_required_bits: {recommended_bits}-bit ADC required.  "
            f"At this resolution the design is typically noise-limited rather than "
            f"quantization-limited.  Verify ENOB with enob_from_noise().",
            stacklevel=2,
        )

    return {
        "ok": True,
        "full_scale_range_v": full_scale_range_v,
        "target_resolution_mv": target_resolution_mv,
        "ideal_bits": round(ideal_bits, 4),
        "recommended_bits": recommended_bits,
        "lsb_size_mv": round(lsb_size_mv, 6),
    }


def enob_from_noise(
    noise_rms_uv: float,
    full_scale_range_v: float,
) -> dict:
    """
    Compute Effective Number of Bits (ENOB) from input-referred RMS noise.

    ENOB = log2(FSR / (noise_rms × sqrt(12)))     [noise floor model]
         = log2(FSR / (noise_rms × 2√3))

    A warning is issued when ENOB < 10 (noise-limited design) or ENOB > 24
    (suspect input values).

    Parameters
    ----------
    noise_rms_uv       : float — input-referred RMS noise [µV]
    full_scale_range_v : float — ADC full-scale input range [V]

    Returns
    -------
    dict with keys: ok, noise_rms_uv, full_scale_range_v, enob
    """
    err = _chk_pos(noise_rms_uv, "noise_rms_uv")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(full_scale_range_v, "full_scale_range_v")
    if err:
        return {"ok": False, "reason": err}

    noise_rms_v = noise_rms_uv * 1e-6
    enob = math.log2(full_scale_range_v / (noise_rms_v * math.sqrt(12.0)))

    if enob < 10.0:
        warnings.warn(
            f"enob_from_noise: ENOB = {enob:.1f} bits — noise-limited design.  "
            f"Review front-end noise sources.",
            stacklevel=2,
        )
    if enob > 24.0:
        warnings.warn(
            f"enob_from_noise: ENOB = {enob:.1f} bits > 24 — verify noise figure inputs.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "noise_rms_uv": noise_rms_uv,
        "full_scale_range_v": full_scale_range_v,
        "enob": round(enob, 3),
        "formula": "ENOB = log2(FSR / (Vnoise_rms × √12))",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 7. Anti-alias filter corner frequency
# ══════════════════════════════════════════════════════════════════════════════

def antialias_filter_corner(
    sample_rate_hz: float,
    stopband_attenuation_db: float = 40.0,
    filter_order: int = 2,
) -> dict:
    """
    Recommend the anti-alias filter −3 dB corner frequency for a given ADC
    sample rate, stopband attenuation, and filter order.

    Strategy:
        Nyquist frequency:   f_nyq = fs / 2
        Stopband edge:       f_stop = f_nyq  (must be ≥ A_stop attenuation)
        Using a Butterworth roll-off approximation:
            |H(f)|² ≈ 1 / (1 + (f/fc)^(2N))
        Solving for fc given attenuation A_stop [dB] at f_nyq:
            fc = f_nyq / 10^(A_stop / (20 × N))

    The passband (−3 dB) is set at fc.  A warning is issued when fc < fs/4
    (the filter cutoff is unusually low, losing more than half of the Nyquist band).

    Parameters
    ----------
    sample_rate_hz          : float — ADC sample rate [Hz]
    stopband_attenuation_db : float — required attenuation at Nyquist [dB] (default 40 dB)
    filter_order            : int   — filter order N (default 2)

    Returns
    -------
    dict with keys: ok, sample_rate_hz, nyquist_hz, filter_corner_hz,
                    stopband_attenuation_db, filter_order, bandwidth_ratio
    """
    err = _chk_pos(sample_rate_hz, "sample_rate_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(stopband_attenuation_db, "stopband_attenuation_db")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(filter_order, int) or filter_order < 1:
        return {"ok": False, "reason": "filter_order must be a positive integer"}

    f_nyq = sample_rate_hz / 2.0
    # fc = f_nyq / 10^(A/(20N))
    fc = f_nyq / (10.0 ** (stopband_attenuation_db / (20.0 * filter_order)))

    bandwidth_ratio = fc / f_nyq

    if fc < sample_rate_hz / 4.0:
        warnings.warn(
            f"antialias_filter_corner: recommended fc = {fc:.1f} Hz is less than "
            f"fs/4 = {sample_rate_hz/4:.1f} Hz.  More than half the Nyquist band "
            f"is attenuated.  Consider a higher-order filter or lower attenuation.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "sample_rate_hz": sample_rate_hz,
        "nyquist_hz": f_nyq,
        "filter_corner_hz": round(fc, 3),
        "stopband_attenuation_db": stopband_attenuation_db,
        "filter_order": filter_order,
        "bandwidth_ratio": round(bandwidth_ratio, 4),
        "formula": "Butterworth: fc = f_nyq / 10^(A_stop / (20N))",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. 4-20 mA current loop
# ══════════════════════════════════════════════════════════════════════════════

def loop_4_20ma_scaling(
    current_ma: float,
    span_low: float,
    span_high: float,
) -> dict:
    """
    Scale a 4-20 mA loop current to engineering units.

    Engineering value = span_low + (I - 4) / 16 × (span_high - span_low)

    A warning is issued if current_ma is outside [3.8, 20.5] mA (fault range).

    Parameters
    ----------
    current_ma  : float — loop current [mA]
    span_low    : float — engineering unit value at 4 mA
    span_high   : float — engineering unit value at 20 mA

    Returns
    -------
    dict with keys: ok, current_ma, span_low, span_high, value, fraction
    """
    err = _chk_real(current_ma, "current_ma")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_real(span_low, "span_low")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_real(span_high, "span_high")
    if err:
        return {"ok": False, "reason": err}
    if span_low == span_high:
        return {"ok": False, "reason": "span_low and span_high must differ"}

    if current_ma < 3.8 or current_ma > 20.5:
        warnings.warn(
            f"loop_4_20ma_scaling: current {current_ma} mA is outside the "
            f"normal operating range [3.8, 20.5] mA.  "
            f"Check for open-circuit (<3.8) or over-range (>20.5) condition.",
            stacklevel=2,
        )

    fraction = (current_ma - 4.0) / 16.0
    value = span_low + fraction * (span_high - span_low)

    return {
        "ok": True,
        "current_ma": current_ma,
        "span_low": span_low,
        "span_high": span_high,
        "fraction": round(fraction, 6),
        "value": round(value, 6),
    }


def loop_burden_voltage(
    current_ma: float,
    burden_resistance_ohm: float,
    supply_voltage_v: float,
    transmitter_min_compliance_v: float = 3.0,
) -> dict:
    """
    Compute voltage across the loop burden resistor and check compliance headroom.

    V_burden = I × R_burden
    V_available = supply_voltage_v − V_burden
    compliance_margin = V_available − transmitter_min_compliance_v

    A warning is issued when compliance_margin < 1 V.

    Parameters
    ----------
    current_ma                    : float — loop current [mA]
    burden_resistance_ohm         : float — total series burden resistance [Ω]
    supply_voltage_v              : float — loop supply voltage [V]
    transmitter_min_compliance_v  : float — minimum transmitter compliance voltage [V] (default 3 V)

    Returns
    -------
    dict with keys: ok, v_burden_v, v_available_v, compliance_margin_v, compliant
    """
    err = _chk_pos(current_ma, "current_ma")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(burden_resistance_ohm, "burden_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(supply_voltage_v, "supply_voltage_v")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(transmitter_min_compliance_v, "transmitter_min_compliance_v")
    if err:
        return {"ok": False, "reason": err}

    i_a = current_ma * 1e-3
    v_burden = i_a * burden_resistance_ohm
    v_available = supply_voltage_v - v_burden
    compliance_margin = v_available - transmitter_min_compliance_v
    compliant = compliance_margin >= 0.0

    if compliance_margin < 1.0:
        warnings.warn(
            f"loop_burden_voltage: compliance margin {compliance_margin:.2f} V < 1 V. "
            f"Transmitter may not regulate at maximum current with this burden.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "current_ma": current_ma,
        "burden_resistance_ohm": burden_resistance_ohm,
        "supply_voltage_v": supply_voltage_v,
        "v_burden_v": round(v_burden, 4),
        "v_available_v": round(v_available, 4),
        "compliance_margin_v": round(compliance_margin, 4),
        "compliant": compliant,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 9. Sensor noise budget RSS
# ══════════════════════════════════════════════════════════════════════════════

def noise_budget_rss(
    noise_sources_uv: list,
) -> dict:
    """
    Compute the root-sum-of-squares (RSS) total noise from a list of
    independent noise sources.

    V_total_rms = sqrt(V₁² + V₂² + ... + Vₙ²)

    A warning is issued when any single source dominates (>70% of total variance),
    indicating the budget is dominated by that source.

    Parameters
    ----------
    noise_sources_uv : list of float — list of RMS noise amplitudes [µV]

    Returns
    -------
    dict with keys: ok, noise_sources_uv, total_rms_uv,
                    dominant_source_index, dominant_source_fraction
    """
    if not isinstance(noise_sources_uv, (list, tuple)) or len(noise_sources_uv) == 0:
        return {"ok": False, "reason": "noise_sources_uv must be a non-empty list of numbers"}

    validated = []
    for i, v in enumerate(noise_sources_uv):
        err = _chk_nonneg(v, f"noise_sources_uv[{i}]")
        if err:
            return {"ok": False, "reason": err}
        validated.append(float(v))

    total_var = sum(v ** 2 for v in validated)
    total_rms = math.sqrt(total_var) if total_var > 0 else 0.0

    dom_idx = max(range(len(validated)), key=lambda i: validated[i] ** 2)
    dom_frac = (validated[dom_idx] ** 2 / total_var) if total_var > 0 else 1.0

    if dom_frac > 0.70:
        warnings.warn(
            f"noise_budget_rss: source[{dom_idx}] = {validated[dom_idx]:.2f} µV "
            f"dominates {dom_frac*100:.0f}% of total noise variance.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "noise_sources_uv": [round(v, 4) for v in validated],
        "total_rms_uv": round(total_rms, 4),
        "dominant_source_index": dom_idx,
        "dominant_source_fraction": round(dom_frac, 4),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 10. Sallen-Key vs MFB topology selector
# ══════════════════════════════════════════════════════════════════════════════

def filter_topology_select(
    gain: float,
    q_factor: float,
    supply_single_ended: bool = False,
    low_noise_priority: bool = False,
) -> dict:
    """
    Recommend Sallen-Key (SK) or Multiple-Feedback (MFB) topology for a
    second-order active lowpass anti-alias filter.

    Decision rules (from Horowitz & Hill §6.3 / TI SLOA049):

    Sallen-Key is preferred when:
      - Unity gain (G ≈ 1) or low gain (G ≤ 3)
      - Low Q is required (Q ≤ 1)
      - Single-ended (non-inverting) output is needed
      - Noise is not critical

    MFB is preferred when:
      - Higher gain (G > 3) is needed without additional op-amp
      - Higher Q (Q > 1) with good sensitivity
      - Inverting output is acceptable
      - Low noise is a priority (MFB has better noise performance for high Q)

    Parameters
    ----------
    gain                : float — required filter gain (absolute, ≥ 1)
    q_factor            : float — required Q factor (0.5 → Butterworth 2nd-order,
                                  0.707 → Bessel)
    supply_single_ended : bool  — True if only single-ended supply (no split rail)
    low_noise_priority  : bool  — True if noise is the primary concern

    Returns
    -------
    dict with keys: ok, recommended_topology, reason, gain, q_factor
    """
    err = _chk_pos(gain, "gain")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(q_factor, "q_factor")
    if err:
        return {"ok": False, "reason": err}

    reasons = []
    sk_score = 0
    mfb_score = 0

    if gain <= 3.0:
        sk_score += 2
        reasons.append(f"G={gain:.2f}≤3 favours Sallen-Key")
    else:
        mfb_score += 2
        reasons.append(f"G={gain:.2f}>3 favours MFB (no extra gain stage)")

    if q_factor <= 1.0:
        sk_score += 1
        reasons.append(f"Q={q_factor:.3f}≤1 favours Sallen-Key (low sensitivity)")
    else:
        mfb_score += 1
        reasons.append(f"Q={q_factor:.3f}>1 favours MFB (better high-Q sensitivity)")

    if supply_single_ended:
        sk_score += 1
        reasons.append("Single-ended supply favours Sallen-Key (non-inverting)")

    if low_noise_priority and q_factor > 1.0:
        mfb_score += 1
        reasons.append("Low-noise + high-Q combination favours MFB")

    topology = "sallen-key" if sk_score >= mfb_score else "mfb"

    return {
        "ok": True,
        "recommended_topology": topology,
        "gain": gain,
        "q_factor": q_factor,
        "supply_single_ended": supply_single_ended,
        "low_noise_priority": low_noise_priority,
        "sk_score": sk_score,
        "mfb_score": mfb_score,
        "reasons": reasons,
    }
