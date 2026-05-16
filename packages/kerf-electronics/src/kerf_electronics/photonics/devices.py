"""
Optoelectronics device models — pure Python (math/cmath only).

This module is distinct from:
  • kerf_electronics.leddriver   — LED driver power-electronics topologies
  • kerf_electronics.linkbudget  — fiber/RF link budget
  • kerf_electronics.antenna     — antenna gain/pattern
  • kerf_electronics.dataconv    — ADC/DAC design

All functions follow the kerf never-raise contract:
  • Validation errors → returned as dict with {ok: False, reason: str}
  • Limit violations / below-threshold / TIA-unstable / SNR-too-low conditions
    → warnings.warn (never raise); result dict still has ok=True with a
    "warnings" list.
  • Exceptions are never raised to callers.

Device models covered
---------------------
LED / laser-diode L-I-V
    led_liv            — L-I-V curve: threshold, slope efficiency, WPE, EQE,
                         wavelength↔photon energy, thermal efficiency droop &
                         wavelength shift.
    laser_threshold    — Threshold current, P-I relation above threshold.

Photodiode
    photodiode_responsivity   — Responsivity R [A/W] from QE and λ.
    photodiode_photocurrent   — Photocurrent from incident optical power.
    photodiode_noise          — Shot + dark + thermal (Johnson) noise,
                                SNR, NEP, detectivity D*.
    photodiode_bandwidth      — RC bandwidth and transit-time limit.

Transimpedance amplifier (TIA)
    tia_design         — Gain Rf, input-referred noise (diode capacitance,
                         op-amp en/in), feedback capacitor for stability/
                         phase-margin, bandwidth.

Optocoupler
    optocoupler        — CTR, current-transfer, propagation delay,
                         speed vs load resistance.

Fiber coupling
    fiber_coupling     — Mode/NA mismatch coupling efficiency.

Solar cell
    solar_cell_iv      — Single-diode model: Voc, Isc, fill-factor, efficiency.

Time-of-Flight / LiDAR
    tof_lidar          — Range, received power, SNR.

Physical constants
------------------
_H  = 6.62607015e-34  J·s   (Planck)
_C  = 2.99792458e8   m/s   (speed of light)
_Q  = 1.602176634e-19 C    (elementary charge)
_KB = 1.380649e-23   J/K   (Boltzmann)
_T0 = 290.0          K     (reference temperature)

References
----------
  Saleh & Teich, "Fundamentals of Photonics" (3rd ed., Wiley 2019)
  Chuang, "Physics of Photonic Devices" (2nd ed., Wiley 2009)
  Razavi, "Design of Analog CMOS Integrated Circuits" (2nd ed., McGraw-Hill 2016)
  Horowitz & Hill, "The Art of Electronics" (3rd ed., Cambridge 2015)
  Kasap, "Optoelectronics and Photonics" (2nd ed., Pearson 2013)

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Optional

# ── Physical constants ────────────────────────────────────────────────────────

_H  = 6.62607015e-34    # Planck constant [J·s]
_C  = 2.99792458e8      # Speed of light [m/s]
_Q  = 1.602176634e-19   # Elementary charge [C]
_KB = 1.380649e-23      # Boltzmann constant [J/K]
_T0 = 290.0             # Reference temperature [K]

# ── Input validation helpers ──────────────────────────────────────────────────


def _chk_pos(value, name: str) -> Optional[str]:
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive finite number, got {value!r}"
    return None


def _chk_nonneg(value, name: str) -> Optional[str]:
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _chk_real(value, name: str) -> Optional[str]:
    if not isinstance(value, (int, float)) or math.isnan(value):
        return f"{name} must be a real number, got {value!r}"
    return None


def _chk_frac(value, name: str) -> Optional[str]:
    """Validate a fractional value in (0, 1]."""
    err = _chk_pos(value, name)
    if err:
        return err
    if value > 1.0:
        return f"{name} must be in (0, 1], got {value!r}"
    return None


# ── Wavelength ↔ photon energy ────────────────────────────────────────────────


def wavelength_to_photon_energy(wavelength_m: float) -> dict:
    """
    Convert optical wavelength to photon energy.

    E_photon [J]  = h × c / λ
    E_photon [eV] = E_photon_J / q

    Parameters
    ----------
    wavelength_m : float — optical wavelength [m] (e.g. 1550e-9 for 1550 nm)

    Returns
    -------
    dict with keys: ok, wavelength_m, wavelength_nm, freq_hz,
                    photon_energy_j, photon_energy_ev
    """
    err = _chk_pos(wavelength_m, "wavelength_m")
    if err:
        return {"ok": False, "reason": err}

    freq_hz = _C / wavelength_m
    e_j = _H * freq_hz
    e_ev = e_j / _Q

    return {
        "ok": True,
        "wavelength_m": wavelength_m,
        "wavelength_nm": wavelength_m * 1e9,
        "freq_hz": freq_hz,
        "photon_energy_j": e_j,
        "photon_energy_ev": round(e_ev, 6),
        "formula": "E = h·c/λ",
    }


def photon_energy_to_wavelength(energy_ev: float) -> dict:
    """
    Convert photon energy [eV] to wavelength [m].

    λ [m] = h × c / (E_ev × q)

    Parameters
    ----------
    energy_ev : float — photon energy [eV]

    Returns
    -------
    dict with keys: ok, energy_ev, wavelength_m, wavelength_nm, freq_hz
    """
    err = _chk_pos(energy_ev, "energy_ev")
    if err:
        return {"ok": False, "reason": err}

    e_j = energy_ev * _Q
    wavelength_m = _H * _C / e_j
    freq_hz = _C / wavelength_m

    return {
        "ok": True,
        "energy_ev": energy_ev,
        "wavelength_m": wavelength_m,
        "wavelength_nm": wavelength_m * 1e9,
        "freq_hz": freq_hz,
    }


# ── LED / Laser diode L-I-V model ────────────────────────────────────────────


def led_liv(
    current_a: float,
    wavelength_m: float,
    slope_efficiency_w_per_a: float,
    threshold_current_a: float = 0.0,
    vf_v: float = 2.0,
    series_resistance_ohm: float = 0.0,
    eqe: Optional[float] = None,
    thermal_droop_per_k: float = 0.0,
    wavelength_shift_nm_per_k: float = 0.0,
    delta_temp_k: float = 0.0,
) -> dict:
    """
    LED / laser-diode L-I-V model.

    Computes:
      • Output optical power P_opt [W] (clamped to 0 below threshold)
      • Actual junction voltage Vj = Vf + I × Rs
      • Wall-plug efficiency (WPE) = P_opt / (Vj × I)
      • External quantum efficiency (EQE): direct or derived from slope efficiency
      • Thermal efficiency droop and wavelength shift from ΔT

    Formula (above threshold):
        P_opt = slope_eff × (I − I_th)          [W]
    For an LED (I_th = 0):
        P_opt = slope_eff × I

    EQE from slope efficiency (if not provided):
        EQE = slope_eff × (h·c / (λ·q))         [photons per electron]
            = slope_eff / (q × f / h)            [dimensionless]
        where f = c/λ.

    Thermal droop (when delta_temp_k > 0):
        P_opt_thermal = P_opt × (1 − thermal_droop_per_k × delta_temp_k)
        λ_shifted = λ + wavelength_shift_nm_per_k × delta_temp_k  [nm]

    Parameters
    ----------
    current_a              : float — drive current [A]
    wavelength_m           : float — nominal emission wavelength [m]
    slope_efficiency_w_per_a: float — differential slope efficiency dP/dI [W/A]
    threshold_current_a    : float — threshold current [A] (0 for LED, > 0 for laser)
    vf_v                   : float — forward voltage at operating current [V]
    series_resistance_ohm  : float — series resistance [Ω] (default 0)
    eqe                    : float or None — external quantum efficiency (0, 1]; if None, derived
    thermal_droop_per_k    : float — relative efficiency droop per K [1/K] (default 0)
    wavelength_shift_nm_per_k: float — wavelength red-shift per K [nm/K] (default 0)
    delta_temp_k           : float — junction temperature rise above reference [K] (default 0)

    Returns
    -------
    dict with keys:
        ok, current_a, wavelength_m, wavelength_nm, p_opt_w,
        vj_v, wpe, eqe, photon_energy_ev,
        below_threshold (bool),
        p_opt_thermal_w (when delta_temp_k > 0),
        wavelength_shifted_nm (when wavelength_shift != 0 and delta_temp_k > 0),
        warnings (list of str)
    """
    warn_msgs: list = []

    err = _chk_pos(current_a, "current_a")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(wavelength_m, "wavelength_m")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(slope_efficiency_w_per_a, "slope_efficiency_w_per_a")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(threshold_current_a, "threshold_current_a")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(vf_v, "vf_v")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(series_resistance_ohm, "series_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(thermal_droop_per_k, "thermal_droop_per_k")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(delta_temp_k, "delta_temp_k")
    if err:
        return {"ok": False, "reason": err}
    if eqe is not None:
        err = _chk_frac(eqe, "eqe")
        if err:
            return {"ok": False, "reason": err}

    # Below-threshold check
    below_threshold = current_a <= threshold_current_a

    if below_threshold:
        warnings.warn(
            f"led_liv: drive current {current_a:.4g} A is at or below threshold "
            f"{threshold_current_a:.4g} A — optical output is zero.",
            stacklevel=2,
        )
        warn_msgs.append("below_threshold: no optical output")

    # Optical power (above threshold only)
    p_opt = 0.0 if below_threshold else slope_efficiency_w_per_a * (current_a - threshold_current_a)

    # Junction voltage including series drop
    vj = vf_v + series_resistance_ohm * current_a

    # Wall-plug efficiency
    input_power = vj * current_a
    wpe = (p_opt / input_power) if (input_power > 0 and not below_threshold) else 0.0

    # Photon energy
    freq_hz = _C / wavelength_m
    e_photon_j = _H * freq_hz
    e_photon_ev = e_photon_j / _Q

    # EQE: photons emitted per electron injected
    if eqe is None and not below_threshold:
        # R_ext = slope_eff [W/A]; photon flux = slope_eff / E_photon;
        # electron flux = I / q → EQE = (slope_eff / E_photon) / (1 / q)
        eqe = (slope_efficiency_w_per_a * _Q) / e_photon_j
        eqe = min(eqe, 1.0)  # physical cap
    elif eqe is None:
        eqe = 0.0

    result: dict = {
        "ok": True,
        "current_a": current_a,
        "wavelength_m": wavelength_m,
        "wavelength_nm": round(wavelength_m * 1e9, 4),
        "p_opt_w": p_opt,
        "vj_v": round(vj, 6),
        "wpe": round(wpe, 6),
        "eqe": round(eqe, 6),
        "photon_energy_ev": round(e_photon_ev, 6),
        "below_threshold": below_threshold,
    }

    # Thermal droop
    if delta_temp_k > 0:
        droop = 1.0 - thermal_droop_per_k * delta_temp_k
        droop = max(droop, 0.0)
        p_opt_thermal = p_opt * droop
        result["p_opt_thermal_w"] = p_opt_thermal
        result["thermal_droop_factor"] = round(droop, 6)

    if delta_temp_k > 0 and wavelength_shift_nm_per_k != 0.0:
        lam_shifted_nm = wavelength_m * 1e9 + wavelength_shift_nm_per_k * delta_temp_k
        result["wavelength_shifted_nm"] = round(lam_shifted_nm, 4)

    if wpe > 0 and wpe < 0.05:
        warnings.warn(
            f"led_liv: wall-plug efficiency is very low ({wpe*100:.1f}%). "
            f"Check slope efficiency and forward voltage.",
            stacklevel=2,
        )
        warn_msgs.append(f"low_wpe: {wpe*100:.1f}%")

    result["warnings"] = warn_msgs
    return result


def laser_threshold(
    current_a: float,
    threshold_current_a: float,
    slope_efficiency_w_per_a: float,
) -> dict:
    """
    Laser P-I relation: output power above / below threshold.

    P_opt [W] = slope_eff × (I − I_th)   for I > I_th
    P_opt = 0                              for I ≤ I_th

    Parameters
    ----------
    current_a              : float — drive current [A]
    threshold_current_a    : float — lasing threshold current [A]
    slope_efficiency_w_per_a: float — slope efficiency above threshold [W/A]

    Returns
    -------
    dict with keys: ok, current_a, threshold_current_a, p_opt_w,
                    above_threshold (bool), overdrive_a
    """
    err = _chk_pos(current_a, "current_a")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(threshold_current_a, "threshold_current_a")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(slope_efficiency_w_per_a, "slope_efficiency_w_per_a")
    if err:
        return {"ok": False, "reason": err}

    above = current_a > threshold_current_a
    if not above:
        warnings.warn(
            f"laser_threshold: I={current_a:.4g} A ≤ I_th={threshold_current_a:.4g} A "
            f"— laser is below threshold.",
            stacklevel=2,
        )

    overdrive = max(0.0, current_a - threshold_current_a)
    p_opt = slope_efficiency_w_per_a * overdrive if above else 0.0

    return {
        "ok": True,
        "current_a": current_a,
        "threshold_current_a": threshold_current_a,
        "slope_efficiency_w_per_a": slope_efficiency_w_per_a,
        "p_opt_w": p_opt,
        "above_threshold": above,
        "overdrive_a": overdrive,
    }


# ── Photodiode responsivity ───────────────────────────────────────────────────


def photodiode_responsivity(
    wavelength_m: float,
    quantum_efficiency: float = 0.8,
) -> dict:
    """
    Photodiode responsivity R [A/W] from external quantum efficiency (EQE) and λ.

    R = EQE × q × λ / (h × c) = EQE × q / (h × f)

    Parameters
    ----------
    wavelength_m       : float — optical wavelength [m]
    quantum_efficiency : float — external quantum efficiency ∈ (0, 1] (default 0.8)

    Returns
    -------
    dict with keys: ok, responsivity_a_per_w, wavelength_m, wavelength_nm,
                    quantum_efficiency, photon_energy_ev, freq_hz
    """
    err = _chk_pos(wavelength_m, "wavelength_m")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_frac(quantum_efficiency, "quantum_efficiency")
    if err:
        return {"ok": False, "reason": err}

    freq_hz = _C / wavelength_m
    e_photon_j = _H * freq_hz
    e_photon_ev = e_photon_j / _Q
    responsivity = quantum_efficiency * _Q / e_photon_j

    return {
        "ok": True,
        "responsivity_a_per_w": round(responsivity, 8),
        "wavelength_m": wavelength_m,
        "wavelength_nm": round(wavelength_m * 1e9, 4),
        "quantum_efficiency": quantum_efficiency,
        "photon_energy_ev": round(e_photon_ev, 6),
        "freq_hz": freq_hz,
        "formula": "R = EQE × q·λ / (h·c)",
    }


def photodiode_photocurrent(
    optical_power_w: float,
    responsivity_a_per_w: float,
) -> dict:
    """
    Photocurrent from incident optical power and responsivity.

    I_ph [A] = R [A/W] × P_opt [W]

    Parameters
    ----------
    optical_power_w     : float — incident optical power [W]
    responsivity_a_per_w: float — photodiode responsivity [A/W]

    Returns
    -------
    dict with keys: ok, photocurrent_a, optical_power_w, responsivity_a_per_w
    """
    err = _chk_pos(optical_power_w, "optical_power_w")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(responsivity_a_per_w, "responsivity_a_per_w")
    if err:
        return {"ok": False, "reason": err}

    i_ph = responsivity_a_per_w * optical_power_w

    return {
        "ok": True,
        "photocurrent_a": i_ph,
        "optical_power_w": optical_power_w,
        "responsivity_a_per_w": responsivity_a_per_w,
        "formula": "I_ph = R × P_opt",
    }


# ── Photodiode noise, SNR, NEP, detectivity ──────────────────────────────────


def photodiode_noise(
    optical_power_w: float,
    responsivity_a_per_w: float,
    dark_current_a: float,
    bandwidth_hz: float,
    load_resistance_ohm: float,
    temp_k: float = _T0,
    snr_min_db: float = 0.0,
) -> dict:
    """
    Photodiode noise analysis: shot noise, dark-current noise, thermal noise,
    total noise, SNR, NEP, and D* (detectivity).

    Noise model (RMS currents, referred to photodiode output)
    ---------------------------------------------------------
    Shot noise (signal):   i_shot = sqrt(2·q·I_ph·B)
    Shot noise (dark):     i_dark_shot = sqrt(2·q·I_dark·B)
    Thermal (Johnson):     i_thermal = sqrt(4·k·T·B / R_L)
    Total noise:           i_noise = sqrt(i_shot² + i_dark_shot² + i_thermal²)

    SNR  = I_ph² / i_noise²  (electrical SNR, current squared)
    SNR_dB = 10·log10(SNR)

    NEP [W/√Hz] = i_noise / (R × √B)   [noise-equivalent power, per root-Hz]
    D* [cm·√Hz/W] = sqrt(A_det) / NEP_norm   — here we return NEP per-root-Hz;
                   for a 1 mm² detector: D* = 1e-2 / (NEP × 1e-3)  [cm·√Hz/W]

    Parameters
    ----------
    optical_power_w     : float — incident optical power [W]
    responsivity_a_per_w: float — photodiode responsivity [A/W]
    dark_current_a      : float — dark current [A]
    bandwidth_hz        : float — noise bandwidth [Hz]
    load_resistance_ohm : float — load/transimpedance resistance [Ω]
    temp_k              : float — temperature [K] (default 290 K)
    snr_min_db          : float — minimum acceptable SNR [dB]; warns if SNR below

    Returns
    -------
    dict with keys:
        ok, photocurrent_a, i_shot_rms_a, i_dark_shot_rms_a,
        i_thermal_rms_a, i_noise_rms_a,
        snr_linear, snr_db, nep_w_per_root_hz,
        d_star_cm_root_hz_per_w (for 1 mm² detector),
        bandwidth_hz, temp_k,
        snr_ok (bool, if snr_min_db provided)
    """
    err = _chk_pos(optical_power_w, "optical_power_w")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(responsivity_a_per_w, "responsivity_a_per_w")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(dark_current_a, "dark_current_a")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(bandwidth_hz, "bandwidth_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(load_resistance_ohm, "load_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(temp_k, "temp_k")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(snr_min_db, "snr_min_db")
    if err:
        return {"ok": False, "reason": err}

    i_ph = responsivity_a_per_w * optical_power_w

    # Shot noise (signal photocurrent)
    i_shot_sq = 2.0 * _Q * i_ph * bandwidth_hz
    i_shot = math.sqrt(i_shot_sq)

    # Shot noise (dark current)
    i_dark_shot_sq = 2.0 * _Q * dark_current_a * bandwidth_hz
    i_dark_shot = math.sqrt(i_dark_shot_sq)

    # Johnson (thermal) noise
    i_therm_sq = 4.0 * _KB * temp_k * bandwidth_hz / load_resistance_ohm
    i_therm = math.sqrt(i_therm_sq)

    # Total noise
    i_noise_sq = i_shot_sq + i_dark_shot_sq + i_therm_sq
    i_noise = math.sqrt(i_noise_sq)

    # SNR (electrical, current²)
    snr_lin = (i_ph ** 2) / i_noise_sq if i_noise_sq > 0 else math.inf
    snr_db = 10.0 * math.log10(snr_lin) if snr_lin > 0 else -math.inf

    # NEP [W/√Hz]
    # NEP = noise current RMS / (R × sqrt(B))
    nep = i_noise / (responsivity_a_per_w * math.sqrt(bandwidth_hz))

    # D* for 1 mm² detector (A_det = 1e-6 m² = 1e-2 cm × 1e-2 cm = 1e-4 cm²)
    # D* [cm·√Hz/W] = sqrt(A_det_cm2) / NEP_per_root_hz
    # A_det = 1 mm² = 1e-2 cm²; sqrt(1e-2) = 0.1 cm
    d_star = 0.1 / nep if nep > 0 else math.inf

    snr_ok = snr_db >= snr_min_db
    if not snr_ok:
        warnings.warn(
            f"photodiode_noise: SNR {snr_db:.1f} dB is below minimum {snr_min_db:.1f} dB.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "photocurrent_a": i_ph,
        "i_shot_rms_a": i_shot,
        "i_dark_shot_rms_a": i_dark_shot,
        "i_thermal_rms_a": i_therm,
        "i_noise_rms_a": i_noise,
        "snr_linear": snr_lin,
        "snr_db": round(snr_db, 4),
        "nep_w_per_root_hz": nep,
        "d_star_cm_root_hz_per_w": d_star,
        "bandwidth_hz": bandwidth_hz,
        "temp_k": temp_k,
        "snr_ok": snr_ok,
        "snr_min_db": snr_min_db,
    }


# ── Photodiode bandwidth ──────────────────────────────────────────────────────


def photodiode_bandwidth(
    junction_capacitance_f: float,
    load_resistance_ohm: float,
    transit_time_s: Optional[float] = None,
) -> dict:
    """
    Photodiode bandwidth: RC bandwidth and transit-time-limited bandwidth.

    RC bandwidth: f_RC [Hz] = 1 / (2π × C_j × R_L)
    Transit-time bandwidth: f_tr [Hz] = 0.45 / τ_tr  (NRZ 0.44/T rule)
    Combined (when transit_time_s provided):
        f_3dB = 1 / sqrt(1/f_RC² + 1/f_tr²)   [bandwidth addition in quadrature]

    Parameters
    ----------
    junction_capacitance_f : float — junction capacitance [F]
    load_resistance_ohm    : float — load/feedback resistance [Ω]
    transit_time_s         : float or None — carrier transit time [s] (optional)

    Returns
    -------
    dict with keys: ok, f_rc_hz, f_transit_hz (if transit_time_s given),
                    f_3db_hz, rc_limited (bool), transit_limited (bool)
    """
    err = _chk_pos(junction_capacitance_f, "junction_capacitance_f")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(load_resistance_ohm, "load_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    if transit_time_s is not None:
        err = _chk_pos(transit_time_s, "transit_time_s")
        if err:
            return {"ok": False, "reason": err}

    f_rc = 1.0 / (2.0 * math.pi * junction_capacitance_f * load_resistance_ohm)

    result: dict = {
        "ok": True,
        "junction_capacitance_f": junction_capacitance_f,
        "load_resistance_ohm": load_resistance_ohm,
        "f_rc_hz": round(f_rc, 4),
    }

    if transit_time_s is not None:
        f_tr = 0.45 / transit_time_s
        # Combine in quadrature (each is a 1-pole limit)
        f_3db = 1.0 / math.sqrt((1.0 / f_rc) ** 2 + (1.0 / f_tr) ** 2)
        rc_limited = f_rc < f_tr
        transit_limited = not rc_limited
        result["transit_time_s"] = transit_time_s
        result["f_transit_hz"] = round(f_tr, 4)
        result["f_3db_hz"] = round(f_3db, 4)
        result["rc_limited"] = rc_limited
        result["transit_limited"] = transit_limited
    else:
        result["f_3db_hz"] = round(f_rc, 4)
        result["rc_limited"] = True
        result["transit_limited"] = False

    return result


# ── Transimpedance amplifier (TIA) design ────────────────────────────────────


def tia_design(
    feedback_resistance_ohm: float,
    diode_capacitance_f: float,
    opamp_voltage_noise_v_per_root_hz: float,
    opamp_current_noise_a_per_root_hz: float,
    bandwidth_hz: float,
    temp_k: float = _T0,
    phase_margin_deg: float = 60.0,
) -> dict:
    """
    Transimpedance amplifier (TIA) design analysis.

    Computes:
      • Transimpedance gain: Z_T = Rf [Ω]
      • Noise contributors (input-referred current noise):
          i_Rf_noise    = sqrt(4·k·T·B / Rf)          [Johnson noise of Rf]
          i_en_noise    = en × C_d × 2π·f_GBW  / sqrt(3) ≈ en × C_d × ω_GBW
                        ≈ en × sqrt(B) × 2π·C_d × sqrt(B)
                        More precisely: i_en_input = en × 2π × f_3dB × C_d
          i_in_noise    = in × sqrt(B)                [op-amp current noise]
          i_total_noise = sqrt(i_Rf² + i_en² + i_in²) [RMS, input-referred]
      • Feedback capacitor for 60° phase margin:
          Cf = sqrt(Cd / (2π·f_GBW·Rf))  — from standard TIA stability analysis
          where f_GBW ≈ bandwidth_hz (for unity-gain bandwidth ≈ closed-loop BW)
      • -3 dB bandwidth: f_3dB = 1 / (2π·Rf·Cf)
      • TIA-unstable flag: if Cf derived is negative or bandwidth mismatch > factor 10

    Input-referred noise current density (dominant en contribution):
        i_en_eff ≈ en × 2π × f_3dB × C_d      [A/√Hz at TIA input]

    Parameters
    ----------
    feedback_resistance_ohm         : float — feedback resistor Rf [Ω]
    diode_capacitance_f              : float — total input capacitance (diode + stray) [F]
    opamp_voltage_noise_v_per_root_hz: float — op-amp voltage noise density en [V/√Hz]
    opamp_current_noise_a_per_root_hz: float — op-amp current noise density in [A/√Hz]
    bandwidth_hz                     : float — desired signal bandwidth [Hz]
    temp_k                           : float — temperature [K] (default 290 K)
    phase_margin_deg                 : float — target phase margin [°] (default 60°)

    Returns
    -------
    dict with keys:
        ok, transimpedance_gain_ohm, feedback_resistance_ohm,
        diode_capacitance_f, bandwidth_hz,
        i_rf_noise_rms_a, i_en_noise_rms_a, i_in_noise_rms_a,
        i_total_noise_rms_a,
        cf_stability_f, f_3db_hz,
        tia_stable (bool), phase_margin_deg, warnings
    """
    warn_msgs: list = []

    err = _chk_pos(feedback_resistance_ohm, "feedback_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(diode_capacitance_f, "diode_capacitance_f")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(opamp_voltage_noise_v_per_root_hz, "opamp_voltage_noise_v_per_root_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(opamp_current_noise_a_per_root_hz, "opamp_current_noise_a_per_root_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(bandwidth_hz, "bandwidth_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(temp_k, "temp_k")
    if err:
        return {"ok": False, "reason": err}

    Rf = feedback_resistance_ohm
    Cd = diode_capacitance_f
    en = opamp_voltage_noise_v_per_root_hz
    in_ = opamp_current_noise_a_per_root_hz
    B = bandwidth_hz

    # Johnson noise of Rf (input-referred RMS current over bandwidth B)
    i_rf_sq = 4.0 * _KB * temp_k * B / Rf
    i_rf = math.sqrt(i_rf_sq)

    # En contribution: voltage noise integrated over C_d input pole
    # Input-referred current noise from en: i_en = en × 2π × f_3dB × Cd
    # Integrated over B: i_en_rms ≈ en × 2π × B × Cd × sqrt(B) / sqrt(3)
    # Simplified: total RMS = en × 2π × Cd × B × sqrt(B/3) (integrating f² spectrum)
    # Full result: integral of (en × 2π × f × Cd)² from 0 to B = en² × (2π·Cd)² × B³/3
    i_en_sq = (en * 2.0 * math.pi * Cd) ** 2 * (B ** 3) / 3.0
    i_en = math.sqrt(i_en_sq)

    # Op-amp current noise RMS over B
    i_in_sq = (in_ ** 2) * B
    i_in = math.sqrt(i_in_sq)

    # Total input-referred noise
    i_total = math.sqrt(i_rf_sq + i_en_sq + i_in_sq)

    # Feedback capacitor for stability (phase margin consideration)
    # Standard result: Cf ≈ sqrt(Cd / (2π × GBW × Rf))
    # GBW ≈ bandwidth for closed-loop TIA; use B as estimate
    # This gives ~45° phase margin; for 60° use a factor slightly larger
    pm_factor = 1.0 if phase_margin_deg <= 45.0 else math.sqrt(
        math.tan(math.radians(phase_margin_deg)) / math.tan(math.radians(45.0))
    )
    # Guard against degenerate case
    gbe = 2.0 * math.pi * B  # gain-bandwidth estimate [rad/s]
    cf_arg = Cd / (gbe * Rf)
    if cf_arg <= 0:
        cf = 0.0
    else:
        cf = math.sqrt(cf_arg) * pm_factor

    # -3 dB bandwidth with Cf in place
    if cf > 0:
        f_3db = 1.0 / (2.0 * math.pi * Rf * cf)
    else:
        f_3db = math.inf

    # Stability check
    tia_stable = True
    if cf <= 0:
        tia_stable = False
        warn_msgs.append("tia_unstable: Cf computation returned non-positive value")
        warnings.warn(
            "tia_design: feedback capacitor Cf is non-positive — TIA likely unstable.",
            stacklevel=2,
        )
    elif f_3db < B / 10.0 or f_3db > B * 10.0:
        # Wide mismatch between target BW and achieved BW
        warn_msgs.append(
            f"tia_bw_mismatch: target {B:.3g} Hz vs achieved {f_3db:.3g} Hz "
            f"(ratio {f_3db/B:.2f})"
        )
        warnings.warn(
            f"tia_design: large bandwidth mismatch — target {B:.3g} Hz, "
            f"achieved {f_3db:.3g} Hz with Cf={cf:.3g} F.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "transimpedance_gain_ohm": Rf,
        "feedback_resistance_ohm": Rf,
        "diode_capacitance_f": Cd,
        "bandwidth_hz": B,
        "temp_k": temp_k,
        "phase_margin_deg": phase_margin_deg,
        "i_rf_noise_rms_a": i_rf,
        "i_en_noise_rms_a": i_en,
        "i_in_noise_rms_a": i_in,
        "i_total_noise_rms_a": i_total,
        "cf_stability_f": cf,
        "f_3db_hz": round(f_3db, 4) if math.isfinite(f_3db) else None,
        "tia_stable": tia_stable,
        "warnings": warn_msgs,
        "formula": "TIA: Z_T=Rf; Cf=sqrt(Cd/(2π·GBW·Rf)); noise: Rf+en+in contributions",
    }


# ── Optocoupler ───────────────────────────────────────────────────────────────


def optocoupler(
    if_ma: float,
    ctr_percent: float,
    vcc_v: float,
    rload_ohm: float,
    bandwidth_hz: Optional[float] = None,
    propagation_delay_ns: float = 0.0,
) -> dict:
    """
    Optocoupler analysis: CTR, output current, speed vs load resistance.

    CTR (current-transfer ratio) = I_out / I_F

    I_out [A] = (CTR/100) × I_F
    V_out [V] = min(Vcc, I_out × R_load)  (saturates at Vcc)

    Bandwidth limited by R_load × C_opto (approximate):
        f_max ≈ 1 / (2π × R_load × C_opto)
    When bandwidth_hz is provided, it is taken as the datasheet bandwidth at a
    reference Rload; the bandwidth at the given Rload is estimated as:
        f_bw ≈ bandwidth_hz × R_ref / R_load    (1/RC scaling)
    where R_ref = 1 kΩ is assumed as datasheet reference.

    Parameters
    ----------
    if_ma              : float — LED forward current [mA]
    ctr_percent        : float — current transfer ratio [%]
    vcc_v              : float — collector supply voltage [V]
    rload_ohm          : float — collector load resistance [Ω]
    bandwidth_hz       : float or None — datasheet bandwidth at 1 kΩ [Hz] (optional)
    propagation_delay_ns: float — typical propagation delay [ns] (default 0)

    Returns
    -------
    dict with keys:
        ok, if_a, ctr_linear, i_out_a, v_out_v,
        saturated (bool), bandwidth_hz_at_rload (if bandwidth_hz provided),
        max_freq_hz (if bandwidth_hz provided), propagation_delay_ns
    """
    err = _chk_pos(if_ma, "if_ma")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(ctr_percent, "ctr_percent")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(vcc_v, "vcc_v")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(rload_ohm, "rload_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(propagation_delay_ns, "propagation_delay_ns")
    if err:
        return {"ok": False, "reason": err}
    if bandwidth_hz is not None:
        err = _chk_pos(bandwidth_hz, "bandwidth_hz")
        if err:
            return {"ok": False, "reason": err}

    if_a = if_ma * 1e-3
    ctr = ctr_percent / 100.0
    i_out = ctr * if_a
    v_out_ideal = i_out * rload_ohm
    saturated = v_out_ideal >= vcc_v
    v_out = min(v_out_ideal, vcc_v)

    result: dict = {
        "ok": True,
        "if_a": if_a,
        "if_ma": if_ma,
        "ctr_linear": ctr,
        "ctr_percent": ctr_percent,
        "i_out_a": i_out,
        "v_out_v": round(v_out, 6),
        "saturated": saturated,
        "vcc_v": vcc_v,
        "rload_ohm": rload_ohm,
        "propagation_delay_ns": propagation_delay_ns,
    }

    if bandwidth_hz is not None:
        # Scale from reference 1 kΩ: f_bw ∝ 1/Rload
        r_ref = 1000.0
        f_at_rload = bandwidth_hz * r_ref / rload_ohm
        # Also compute max freq from propagation delay
        max_freq_from_delay = (
            1.0 / (2.0 * propagation_delay_ns * 1e-9) if propagation_delay_ns > 0 else math.inf
        )
        result["bandwidth_hz_at_rload"] = round(f_at_rload, 4)
        result["bandwidth_ref_hz"] = bandwidth_hz
        result["max_freq_hz_from_delay"] = (
            round(max_freq_from_delay, 4) if math.isfinite(max_freq_from_delay) else None
        )

    return result


# ── Fiber coupling efficiency ─────────────────────────────────────────────────


def fiber_coupling_efficiency(
    source_na: float,
    fiber_na: float,
    source_mode_diameter_m: float,
    fiber_mode_diameter_m: float,
) -> dict:
    """
    Fiber coupling efficiency from mode-field and NA mismatch.

    For Gaussian beam coupling (single-mode to single-mode):
        η_mode = (2 × w_s × w_f / (w_s² + w_f²))²
    where w_s = source mode radius, w_f = fiber mode radius.

    NA mismatch loss (when source_na > fiber_na):
        η_NA = (fiber_na / source_na)²  (area of acceptance cone ratio)
    When source_na ≤ fiber_na: η_NA = 1.0 (no truncation).

    Total coupling efficiency:
        η = η_mode × η_NA

    Parameters
    ----------
    source_na               : float — source numerical aperture
    fiber_na                : float — fiber numerical aperture
    source_mode_diameter_m  : float — source mode-field diameter [m]
    fiber_mode_diameter_m   : float — fiber mode-field diameter [m]

    Returns
    -------
    dict with keys:
        ok, coupling_efficiency, coupling_loss_db,
        mode_overlap_efficiency, na_efficiency,
        source_na, fiber_na,
        source_mode_diameter_m, fiber_mode_diameter_m
    """
    for name, val in [
        ("source_na", source_na), ("fiber_na", fiber_na),
        ("source_mode_diameter_m", source_mode_diameter_m),
        ("fiber_mode_diameter_m", fiber_mode_diameter_m),
    ]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    # Mode-field overlap (Gaussian approximation)
    w_s = source_mode_diameter_m / 2.0
    w_f = fiber_mode_diameter_m / 2.0
    mode_overlap = (2.0 * w_s * w_f / (w_s ** 2 + w_f ** 2)) ** 2

    # NA mismatch
    if source_na > fiber_na:
        na_eff = (fiber_na / source_na) ** 2
    else:
        na_eff = 1.0

    eta = mode_overlap * na_eff

    coupling_loss_db = -10.0 * math.log10(eta) if eta > 0 else math.inf

    return {
        "ok": True,
        "coupling_efficiency": round(eta, 6),
        "coupling_loss_db": round(coupling_loss_db, 4),
        "mode_overlap_efficiency": round(mode_overlap, 6),
        "na_efficiency": round(na_eff, 6),
        "source_na": source_na,
        "fiber_na": fiber_na,
        "source_mode_diameter_m": source_mode_diameter_m,
        "fiber_mode_diameter_m": fiber_mode_diameter_m,
        "formula": "η = η_mode × η_NA; η_mode = (2·ws·wf/(ws²+wf²))²",
    }


# ── Solar cell single-diode model ─────────────────────────────────────────────


def solar_cell_iv(
    isc_a: float,
    voc_v: float,
    ideality_factor: float = 1.0,
    series_resistance_ohm: float = 0.0,
    shunt_resistance_ohm: float = 1e6,
    temp_k: float = 300.0,
    irradiance_w_per_m2: float = 1000.0,
    cell_area_m2: float = 1e-4,
) -> dict:
    """
    Solar cell I-V characteristics using the single-diode model.

    Single-diode model (ideal, series, shunt resistances):
        I = Isc − I0 × (exp((V + I×Rs)/(n·Vt)) − 1) − (V + I·Rs)/Rsh

    Vt = k·T / q   (thermal voltage)
    I0 ≈ Isc / (exp(Voc / (n·Vt)) − 1)   (saturation current from Voc, Isc)

    Fill factor:
        FF = Pmpp / (Voc × Isc)
    Empirical approximation (Green 1982):
        v_oc_norm = Voc / (n·Vt)
        FF ≈ (v_oc_norm − ln(v_oc_norm + 0.72)) / (v_oc_norm + 1)

    Maximum power point (bisection on the I-V curve):
        Pmpp [W] = FF × Voc × Isc
        Vmpp, Impp from curve

    Efficiency:
        η = Pmpp / (irradiance × cell_area)

    Parameters
    ----------
    isc_a                : float — short-circuit current [A]
    voc_v                : float — open-circuit voltage [V]
    ideality_factor      : float — diode ideality factor n (default 1.0)
    series_resistance_ohm: float — series resistance Rs [Ω] (default 0)
    shunt_resistance_ohm : float — shunt resistance Rsh [Ω] (default 1 MΩ)
    temp_k               : float — cell temperature [K] (default 300 K)
    irradiance_w_per_m2  : float — incident irradiance [W/m²] (default 1000 = 1-sun)
    cell_area_m2         : float — cell area [m²] (default 1 cm² = 1e-4 m²)

    Returns
    -------
    dict with keys:
        ok, isc_a, voc_v, ff, pmpp_w, vmpp_v, impp_a,
        efficiency, vt_v, i0_a, ideality_factor, temp_k
    """
    err = _chk_pos(isc_a, "isc_a")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(voc_v, "voc_v")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(ideality_factor, "ideality_factor")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(series_resistance_ohm, "series_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(shunt_resistance_ohm, "shunt_resistance_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(temp_k, "temp_k")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(irradiance_w_per_m2, "irradiance_w_per_m2")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(cell_area_m2, "cell_area_m2")
    if err:
        return {"ok": False, "reason": err}

    vt = _KB * temp_k / _Q   # thermal voltage
    n = ideality_factor
    rs = series_resistance_ohm
    rsh = shunt_resistance_ohm

    # Saturation current from boundary conditions (Voc, Isc)
    # I0 = Isc / (exp(Voc/(n·Vt)) − 1)
    exp_arg = voc_v / (n * vt)
    if exp_arg > 700:
        # Overflow guard
        i0 = isc_a * math.exp(-exp_arg)
    else:
        denom = math.exp(exp_arg) - 1.0
        i0 = isc_a / denom if denom > 0 else isc_a * 1e-20

    # Fill factor via Green 1982 empirical approximation
    v_oc_norm = voc_v / (n * vt)
    # FF ≈ (v_oc_norm − ln(v_oc_norm + 0.72)) / (v_oc_norm + 1)
    if v_oc_norm > 0.72:
        ff = (v_oc_norm - math.log(v_oc_norm + 0.72)) / (v_oc_norm + 1.0)
    else:
        ff = 0.25  # very low Voc, degenerate case

    # Series resistance correction to FF (approximate, Green 1982)
    r_s_norm = rs * isc_a / voc_v   # normalised series resistance
    r_sh_norm = rsh * isc_a / voc_v  # normalised shunt resistance
    ff_corrected = ff * (1.0 - 1.1 * r_s_norm) * (1.0 - (v_oc_norm + 0.7) / (v_oc_norm * r_sh_norm))
    ff_corrected = max(ff_corrected, 0.01)
    ff_corrected = min(ff_corrected, ff)  # can't exceed ideal FF

    pmpp = ff_corrected * voc_v * isc_a
    impp = pmpp / voc_v if voc_v > 0 else 0.0
    vmpp = voc_v * ff_corrected

    # Efficiency
    p_incident = irradiance_w_per_m2 * cell_area_m2
    efficiency = pmpp / p_incident if p_incident > 0 else 0.0

    if efficiency > 0.5:
        warnings.warn(
            f"solar_cell_iv: efficiency {efficiency*100:.1f}% exceeds theoretical maximum. "
            f"Check inputs.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "isc_a": isc_a,
        "voc_v": voc_v,
        "ff": round(ff_corrected, 6),
        "ff_ideal": round(ff, 6),
        "pmpp_w": round(pmpp, 8),
        "vmpp_v": round(vmpp, 6),
        "impp_a": round(impp, 8),
        "efficiency": round(efficiency, 6),
        "vt_v": round(vt, 8),
        "i0_a": i0,
        "ideality_factor": n,
        "temp_k": temp_k,
        "irradiance_w_per_m2": irradiance_w_per_m2,
        "cell_area_m2": cell_area_m2,
        "series_resistance_ohm": rs,
        "shunt_resistance_ohm": rsh,
        "formula": "Single-diode model; FF: Green (1982) empirical",
    }


# ── Time-of-Flight / LiDAR range and SNR ─────────────────────────────────────


def tof_lidar(
    peak_power_w: float,
    target_reflectivity: float,
    target_distance_m: float,
    aperture_diameter_m: float,
    receiver_responsivity_a_per_w: float,
    dark_current_a: float,
    bandwidth_hz: float,
    load_resistance_ohm: float,
    beam_divergence_rad: float = 1e-3,
    atmospheric_loss_db_per_km: float = 0.0,
    temp_k: float = _T0,
    snr_min_db: float = 10.0,
) -> dict:
    """
    Time-of-Flight (ToF) / LiDAR range analysis.

    Received power (simplified Lidar equation):
        P_rx = P_tx × ρ × A_rx / (π × R²) × T_atm²
    where:
        ρ       = target reflectivity (Lambertian)
        A_rx    = π × (D/2)²  receiver aperture area
        R       = target distance
        T_atm   = 10^(−α×R / (10×1000))  one-way atmospheric transmission
        P_rx includes two-way path

    Range from ToF:
        d = c × Δt / 2  (Δt = round-trip time)

    Returns received power, photocurrent, noise, SNR, and range limit
    (distance at which SNR = snr_min_db).

    Parameters
    ----------
    peak_power_w              : float — transmitter peak optical power [W]
    target_reflectivity       : float — target reflectivity ρ ∈ (0, 1]
    target_distance_m         : float — target distance [m]
    aperture_diameter_m       : float — receiver aperture diameter [m]
    receiver_responsivity_a_per_w: float — receiver photodiode responsivity [A/W]
    dark_current_a            : float — dark current [A]
    bandwidth_hz              : float — receiver bandwidth [Hz]
    load_resistance_ohm       : float — load resistance [Ω]
    beam_divergence_rad       : float — transmit beam half-angle divergence [rad] (default 1 mrad)
    atmospheric_loss_db_per_km: float — one-way atmospheric loss [dB/km] (default 0)
    temp_k                    : float — temperature [K] (default 290 K)
    snr_min_db                : float — minimum required SNR [dB] (default 10 dB)

    Returns
    -------
    dict with keys:
        ok, p_rx_w, photocurrent_a, i_noise_rms_a, snr_db, snr_ok,
        range_limit_m (estimated max range at snr_min_db),
        tof_s (round-trip time at target_distance_m),
        target_distance_m, peak_power_w
    """
    for name, val in [
        ("peak_power_w", peak_power_w),
        ("target_distance_m", target_distance_m),
        ("aperture_diameter_m", aperture_diameter_m),
        ("receiver_responsivity_a_per_w", receiver_responsivity_a_per_w),
        ("bandwidth_hz", bandwidth_hz),
        ("load_resistance_ohm", load_resistance_ohm),
        ("beam_divergence_rad", beam_divergence_rad),
    ]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    err = _chk_frac(target_reflectivity, "target_reflectivity")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(dark_current_a, "dark_current_a")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(atmospheric_loss_db_per_km, "atmospheric_loss_db_per_km")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(temp_k, "temp_k")
    if err:
        return {"ok": False, "reason": err}

    R = target_distance_m
    rho = target_reflectivity
    D = aperture_diameter_m
    A_rx = math.pi * (D / 2.0) ** 2

    # Two-way atmospheric transmission
    alpha_db = atmospheric_loss_db_per_km  # dB/km
    alpha_per_m = alpha_db / (1e3 * 10.0 / math.log(10))  # convert dB/km to Np/m
    t_atm = math.exp(-alpha_per_m * R)  # one-way; squared for two-way
    t_atm2 = t_atm ** 2

    # Lidar equation (Lambertian target)
    # Beam footprint area at distance R: A_beam = π × (R × θ_div)²
    # For Lambertian: fraction captured = A_rx / A_beam
    a_beam = math.pi * (R * beam_divergence_rad) ** 2
    a_beam = max(a_beam, A_rx)  # can't collect more than illuminated
    p_rx = peak_power_w * rho * A_rx / a_beam * t_atm2

    # Photocurrent
    i_ph = receiver_responsivity_a_per_w * p_rx

    # Noise
    i_shot_sq = 2.0 * _Q * i_ph * bandwidth_hz
    i_dark_sq = 2.0 * _Q * dark_current_a * bandwidth_hz
    i_therm_sq = 4.0 * _KB * temp_k * bandwidth_hz / load_resistance_ohm
    i_noise_sq = i_shot_sq + i_dark_sq + i_therm_sq
    i_noise = math.sqrt(i_noise_sq)

    # SNR
    snr_lin = (i_ph ** 2) / i_noise_sq if i_noise_sq > 0 else math.inf
    snr_db = 10.0 * math.log10(snr_lin) if snr_lin > 0 else -math.inf

    snr_ok = snr_db >= snr_min_db
    if not snr_ok:
        warnings.warn(
            f"tof_lidar: SNR {snr_db:.1f} dB < minimum {snr_min_db:.1f} dB "
            f"at range {R:.1f} m.",
            stacklevel=2,
        )

    # Estimate max range: iterate (approximate — solve for R where SNR = threshold)
    # Thermal-noise limited: i_ph ∝ 1/R², so SNR ∝ i_ph² / i_therm² ∝ 1/R⁴
    # At current range, SNR = snr_lin; at range_limit: snr_min_lin = snr_lin × (R/R_lim)⁴
    snr_min_lin = 10.0 ** (snr_min_db / 10.0)
    if snr_lin > 0 and snr_min_lin > 0:
        range_limit = R * (snr_lin / snr_min_lin) ** 0.25
    else:
        range_limit = 0.0

    # ToF round-trip time
    tof_s = 2.0 * R / _C

    return {
        "ok": True,
        "p_rx_w": p_rx,
        "photocurrent_a": i_ph,
        "i_noise_rms_a": i_noise,
        "snr_linear": snr_lin,
        "snr_db": round(snr_db, 4),
        "snr_ok": snr_ok,
        "range_limit_m": round(range_limit, 2),
        "tof_s": tof_s,
        "target_distance_m": R,
        "peak_power_w": peak_power_w,
        "atmospheric_transmission_two_way": round(t_atm2, 6),
        "formula": "Lidar eq: P_rx = P_tx·ρ·A_rx/(π·R²)·T_atm²",
    }
