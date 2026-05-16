"""
ADC/DAC data-converter system design — closed-form analytical models.

This module is distinct from:
  • kerf_electronics.dsp        — digital filters (FIR/IIR, FFT)
  • kerf_electronics.sensorcond — sensor conditioning amplifiers
  • kerf_electronics.afilter    — analogue anti-alias / reconstruction filters
  • kerf_electronics.si         — signal-integrity (Z0, propagation)

All functions are pure Python (math module only) and follow the kerf
never-raise contract: validation errors are returned as dicts with
{ok: False, reason: str}; performance-limit warnings are issued via the
standard warnings module; exceptions are never raised to callers.

Formulas and references
------------------------
Ideal ADC SNR (N-bit full-scale sine wave, Bennett 1948):
    SNR_ideal [dB] = 6.02 × N + 1.76

SNR with full-scale input backoff:
    SNR_backoff [dB] = SNR_ideal + 20×log10(V_in / V_fs)
    where V_in/V_fs ≤ 1 (backoff_db = 20×log10(V_in/V_fs) ≤ 0).

ENOB from SINAD (IEEE Std 1241-2010 §3.1.7):
    ENOB = (SINAD_dB − 1.76) / 6.02

SNR/SFDR/THD/SINAD relationships (Walden 1999):
    SINAD = −10×log10(10^(−SNR/10) + 10^(−SFDR/10) + 10^(THD_dBc/10))
    (THD_dBc is negative for distortion components below fundamental)

Total noise budget — RSS of independent noise floors:
    Quantisation noise: Vn_q = V_fs / (sqrt(6) × 2^N) [V_rms]
        → SNR_q [dB] = 6.02 N + 1.76  (same as ideal)
    Thermal / kTC noise (reset noise of sampling cap):
        Vn_kTC = sqrt(kT / C) [V_rms]  (k = 1.381e-23, T [K], C [F])
    Aperture-jitter SNR:
        SNR_jitter [dB] = −20×log10(2π × f_in [Hz] × t_j [s])
    Input-referred amplifier noise (spectral density integrated over BW):
        Vn_amp = e_n × sqrt(BW) [V_rms]  (e_n in V/sqrt(Hz))
    Total noise: Vn_total = RSS(Vn_q, Vn_kTC, Vn_amp)
    Overall SNR: 20×log10(V_fs / (sqrt(2) × 2 × Vn_total))
        (V_fs/2 is peak sine amplitude; RMS = V_fs/(2√2) )

Oversampling & decimation processing gain:
    OSR = f_s / (2 × BW)
    Process gain [dB] = 10×log10(OSR) / 2  [3 dB per octave]
    → equivalent Nyquist-rate ENOB_nyq = (SNR_with_osr − 1.76) / 6.02
    → required OSR for target ENOB: OSR = 4^(ENOB_target − ENOB_nyq)

ΔΣ modulator — SQNR and noise shaping (Candy & Temes 1992):
    SQNR [dB] ≈ 10×log10[ (π^(2L)) / (2L+1) ] + (6L+3) × 10×log10(OSR)
    where L = modulator order.  This is the ideal SQNR ignoring in-band
    distortion and stability limits.

SAR ADC conversion time and settling:
    t_convert = N × (t_comp + t_sw)
    where N = bits, t_comp = comparator decision time, t_sw = switch settling.
    RC settling (N+2 time constants to within 0.5 LSB):
        t_settle_rc = (N + 2) × τ  where τ = R_src × C_dac

Pipeline ADC latency and stage scaling:
    Latency = number of stages × T_clk
    For M-stage pipeline with B bits/stage + redundancy:
        Total bits = M × B + flash_bits (with digital correction)
    Stage residue gain: G = 2^B

DAC glitch settling and SFDR vs INL:
    SFDR [dBc] ≈ −20×log10( INL_lsb × 2^(1−N) )
        (INL_lsb in LSBs; typical approximation)
    Glitch area energy: E_glitch = V_glitch × t_glitch [V·s]
    t_settle to 0.5 LSB: from RC model, t = τ × ln(2 × V_step × 2^N / V_fs)

Reference noise contribution to LSB:
    LSB_size = V_ref / 2^N
    SNR_ref [dB] = −20×log10(e_ref_rms / (V_ref / (sqrt(6) × 2^N)))
        = 20×log10(V_ref / (sqrt(6) × 2^N × e_ref_rms))
    where e_ref_rms is the integrated reference noise voltage [V_rms].
    Reference drift error: δ_lsb = (ΔV_ref [ppm/°C] × ΔT × V_ref / 1e6) / LSB_size

ADC driver and RC anti-alias filter kickback settling:
    Kickback charge: ΔQ = C_in × V_step
    Settling time to N+2 time constants: t = (N + 2) × R × C_in
    Input RC anti-alias filter: f_−3dB = 1/(2π × R × C_aa)
    Settling to within 0.5 LSB requires t ≥ (N+2) × ln(2) / (2π × f_−3dB)

Required bits for a target dynamic range:
    N_min = ceil((DR_dB − 1.76) / 6.02)

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Optional

# ── Physical constants ────────────────────────────────────────────────────────

_K_BOLTZMANN = 1.381e-23   # Boltzmann constant [J/K]
_T_ROOM = 300.0            # Room temperature [K]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _validate_positive(value, name: str) -> Optional[str]:
    """Return error string if value is not a positive real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive number, got {value!r}"
    return None


def _validate_nonneg(value, name: str) -> Optional[str]:
    """Return error string if value is not a non-negative real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _validate_bits(bits, name: str = "bits") -> Optional[str]:
    if not isinstance(bits, int) or bits < 1 or bits > 64:
        return f"{name} must be an integer in [1, 64], got {bits!r}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ideal_snr
# ═══════════════════════════════════════════════════════════════════════════════


def ideal_snr(bits: int) -> dict:
    """
    Ideal ADC SNR for an N-bit full-scale sine wave input.

    Bennett (1948):
        SNR_ideal [dB] = 6.02 × N + 1.76

    Parameters
    ----------
    bits : int — ADC resolution [bits] (1–64)

    Returns
    -------
    dict: ok, bits, snr_ideal_db, dynamic_range_db
    """
    err = _validate_bits(bits)
    if err:
        return {"ok": False, "reason": err}

    snr = 6.02 * bits + 1.76
    dr = 6.02 * bits  # dynamic range (0 dB input → noise floor)

    if bits < 4:
        warnings.warn(
            f"ideal_snr: {bits}-bit converter gives only {snr:.1f} dB SNR; "
            "practical converters are typically ≥ 8 bits.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "bits": bits,
        "snr_ideal_db": round(snr, 2),
        "dynamic_range_db": round(dr, 2),
        "formula": "6.02 × N + 1.76  (Bennett 1948)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. snr_with_backoff
# ═══════════════════════════════════════════════════════════════════════════════


def snr_with_backoff(bits: int, backoff_db: float) -> dict:
    """
    ADC SNR with full-scale input backoff.

    When the input signal is backed off below full scale by backoff_db:
        SNR_actual = SNR_ideal + backoff_db
        (backoff_db ≤ 0 always, e.g. −6 dB for half-scale input)

    Parameters
    ----------
    bits       : int   — ADC resolution [bits]
    backoff_db : float — input backoff below full scale [dB] (must be ≤ 0)

    Returns
    -------
    dict: ok, bits, backoff_db, snr_ideal_db, snr_actual_db, enob_actual
    """
    err = _validate_bits(bits)
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(backoff_db, (int, float)) or math.isnan(backoff_db):
        return {"ok": False, "reason": "backoff_db must be a real number"}
    if backoff_db > 0:
        return {"ok": False, "reason": "backoff_db must be ≤ 0 (input below full scale)"}

    snr_ideal = 6.02 * bits + 1.76
    snr_actual = snr_ideal + backoff_db
    enob_actual = (snr_actual - 1.76) / 6.02

    if enob_actual < bits - 4:
        warnings.warn(
            f"snr_with_backoff: {backoff_db:.1f} dB backoff on {bits}-bit ADC gives "
            f"ENOB = {enob_actual:.1f} bits; converter appears under-resolved for this "
            f"input level.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "bits": bits,
        "backoff_db": backoff_db,
        "snr_ideal_db": round(snr_ideal, 2),
        "snr_actual_db": round(snr_actual, 2),
        "enob_actual": round(enob_actual, 3),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. enob_from_sinad
# ═══════════════════════════════════════════════════════════════════════════════


def enob_from_sinad(sinad_db: float) -> dict:
    """
    Effective Number of Bits (ENOB) from measured SINAD.

    IEEE Std 1241-2010 §3.1.7:
        ENOB = (SINAD_dB − 1.76) / 6.02

    Parameters
    ----------
    sinad_db : float — measured SINAD [dB]

    Returns
    -------
    dict: ok, sinad_db, enob, implied_ideal_bits
    """
    if not isinstance(sinad_db, (int, float)) or math.isnan(sinad_db):
        return {"ok": False, "reason": "sinad_db must be a real number"}
    if sinad_db <= 0:
        return {"ok": False, "reason": "sinad_db must be positive"}

    enob = (sinad_db - 1.76) / 6.02
    implied_bits = math.ceil(enob)

    if enob < 1.0:
        warnings.warn(
            f"enob_from_sinad: SINAD = {sinad_db:.1f} dB gives ENOB = {enob:.2f} bits; "
            "converter appears severely under-resolved.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "sinad_db": round(sinad_db, 3),
        "enob": round(enob, 4),
        "implied_ideal_bits": implied_bits,
        "formula": "ENOB = (SINAD − 1.76) / 6.02  (IEEE Std 1241-2010)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. snr_sfdr_thd_sinad_interconvert
# ═══════════════════════════════════════════════════════════════════════════════


def snr_sfdr_thd_sinad_interconvert(
    snr_db: Optional[float] = None,
    sfdr_dbc: Optional[float] = None,
    thd_dbc: Optional[float] = None,
    sinad_db: Optional[float] = None,
) -> dict:
    """
    Interconvert ADC/DAC spectral performance metrics.

    Walden (1999) composite model:
        SINAD = −10×log10( 10^(−SNR/10) + 10^(−SFDR/10) + 10^(THD_dBc/10) )
        (THD_dBc is negative — distortion components below fundamental)

    Given any combination of three metrics, the fourth is computed.
    Provide exactly 3 of the 4 arguments.

    Parameters
    ----------
    snr_db   : float | None — signal-to-noise ratio [dB] (noise only, no harmonics)
    sfdr_dbc : float | None — spurious-free dynamic range [dBc] (positive value)
    thd_dbc  : float | None — total harmonic distortion [dBc] (negative, e.g. −60)
    sinad_db : float | None — signal-to-noise-and-distortion ratio [dB]

    Returns
    -------
    dict: ok, snr_db, sfdr_dbc, thd_dbc, sinad_db, enob
    """
    provided = {
        "snr_db": snr_db,
        "sfdr_dbc": sfdr_dbc,
        "thd_dbc": thd_dbc,
        "sinad_db": sinad_db,
    }
    given = {k: v for k, v in provided.items() if v is not None}
    missing = [k for k, v in provided.items() if v is None]

    if len(given) < 3:
        return {
            "ok": False,
            "reason": f"Provide exactly 3 of the 4 metrics; missing: {missing}",
        }

    try:
        if sinad_db is None:
            # Compute SINAD from SNR, SFDR, THD
            # THD_dBc is negative; 10^(THD/10) is a small positive number
            sinad_db = -10.0 * math.log10(
                10.0 ** (-snr_db / 10.0)
                + 10.0 ** (-sfdr_dbc / 10.0)
                + 10.0 ** (thd_dbc / 10.0)
            )
        elif snr_db is None:
            # Compute SNR from SINAD, SFDR, THD
            total = 10.0 ** (-sinad_db / 10.0)
            sfdr_term = 10.0 ** (-sfdr_dbc / 10.0)
            thd_term = 10.0 ** (thd_dbc / 10.0)
            snr_term = total - sfdr_term - thd_term
            if snr_term <= 0:
                return {
                    "ok": False,
                    "reason": "Inconsistent inputs: computed SNR noise power is non-positive",
                }
            snr_db = -10.0 * math.log10(snr_term)
        elif sfdr_dbc is None:
            # Compute SFDR from SINAD, SNR, THD
            total = 10.0 ** (-sinad_db / 10.0)
            snr_term = 10.0 ** (-snr_db / 10.0)
            thd_term = 10.0 ** (thd_dbc / 10.0)
            sfdr_term = total - snr_term - thd_term
            if sfdr_term <= 0:
                return {
                    "ok": False,
                    "reason": "Inconsistent inputs: computed SFDR spur power is non-positive",
                }
            sfdr_dbc = -10.0 * math.log10(sfdr_term)
        else:
            # Compute THD from SINAD, SNR, SFDR
            total = 10.0 ** (-sinad_db / 10.0)
            snr_term = 10.0 ** (-snr_db / 10.0)
            sfdr_term = 10.0 ** (-sfdr_dbc / 10.0)
            thd_term = total - snr_term - sfdr_term
            if thd_term <= 0:
                return {
                    "ok": False,
                    "reason": "Inconsistent inputs: computed THD distortion power is non-positive",
                }
            thd_dbc = 10.0 * math.log10(thd_term)
    except Exception as exc:
        return {"ok": False, "reason": f"Computation error: {exc}"}

    enob = (sinad_db - 1.76) / 6.02

    return {
        "ok": True,
        "snr_db": round(snr_db, 3),
        "sfdr_dbc": round(sfdr_dbc, 3),
        "thd_dbc": round(thd_dbc, 3),
        "sinad_db": round(sinad_db, 3),
        "enob": round(enob, 4),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. total_noise_budget
# ═══════════════════════════════════════════════════════════════════════════════


def total_noise_budget(
    bits: int,
    v_fs: float,
    freq_in_hz: float,
    t_jitter_s: float,
    cap_dac_f: float = 1e-12,
    en_amp_v_per_rtHz: float = 0.0,
    bw_hz: float = 1e6,
    temp_k: float = _T_ROOM,
) -> dict:
    """
    Total noise budget for an ADC: quantisation + thermal (kTC) + aperture-jitter
    + input-referred amplifier noise, combined as RSS.

    Noise sources
    -------------
    Quantisation:  Vn_q = V_fs / (sqrt(6) × 2^N)
    kTC thermal:   Vn_kTC = sqrt(kT / C_dac)
    Jitter:        SNR_jitter = −20×log10(2π × f_in × t_j)
                  → Vn_jitter = V_fs / (sqrt(2) × 2^(SNR_jitter/6.02 + 0.293))
                  (derived by mapping jitter SNR to an equivalent noise RMS)
    Amplifier:     Vn_amp = e_n × sqrt(BW)

    Overall SNR:
        Vn_total = RSS(Vn_q, Vn_kTC, Vn_jitter, Vn_amp)
        V_sig_rms = V_fs / (2 × sqrt(2))   (full-scale sine)
        SNR_total = 20×log10(V_sig_rms / Vn_total)

    Flags (via warnings.warn):
      • jitter-limited  : jitter noise > 6 dB above quantisation noise
      • under-resolved  : quantisation noise dominates SNR by > 10 dB
      • thermal-limited : kTC noise > 6 dB above quantisation noise

    Parameters
    ----------
    bits              : int   — ADC resolution [bits]
    v_fs              : float — full-scale range peak-to-peak [V]
    freq_in_hz        : float — input signal frequency [Hz]
    t_jitter_s        : float — aperture / clock jitter [s RMS]
    cap_dac_f         : float — DAC sampling capacitor [F] (default 1 pF)
    en_amp_v_per_rtHz : float — input-referred amp voltage noise density [V/√Hz] (default 0)
    bw_hz             : float — noise integration bandwidth [Hz] (default 1 MHz)
    temp_k            : float — temperature [K] (default 300 K)

    Returns
    -------
    dict: ok, bits, v_fs, vn_q_vrms, vn_ktc_vrms, snr_jitter_db, vn_jitter_vrms,
          vn_amp_vrms, vn_total_vrms, snr_total_db, dominant_noise,
          jitter_limited, under_resolved, thermal_limited, warnings_list
    """
    err = _validate_bits(bits)
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(v_fs, "v_fs")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(freq_in_hz, "freq_in_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(t_jitter_s, "t_jitter_s")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(cap_dac_f, "cap_dac_f")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_nonneg(en_amp_v_per_rtHz, "en_amp_v_per_rtHz")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(bw_hz, "bw_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(temp_k, "temp_k")
    if err:
        return {"ok": False, "reason": err}

    # Quantisation noise RMS (uniform distribution, full-scale)
    vn_q = v_fs / (math.sqrt(6.0) * (2 ** bits))

    # kTC thermal noise RMS
    vn_ktc = math.sqrt(_K_BOLTZMANN * temp_k / cap_dac_f)

    # Aperture-jitter SNR and equivalent noise
    snr_jitter_db = -20.0 * math.log10(2.0 * math.pi * freq_in_hz * t_jitter_s)
    # Map jitter-limited SNR to an equivalent RMS noise fraction of full scale
    # Using: SNR_jitter = 20*log10(V_sig_rms / Vn_jitter), V_sig_rms = V_fs/(2√2)
    v_sig_rms = v_fs / (2.0 * math.sqrt(2.0))
    vn_jitter = v_sig_rms / (10.0 ** (snr_jitter_db / 20.0))

    # Input-referred amplifier noise integrated over BW
    vn_amp = en_amp_v_per_rtHz * math.sqrt(bw_hz) if en_amp_v_per_rtHz > 0 else 0.0

    # RSS total noise
    vn_total = math.sqrt(vn_q ** 2 + vn_ktc ** 2 + vn_jitter ** 2 + vn_amp ** 2)
    snr_total_db = 20.0 * math.log10(v_sig_rms / vn_total) if vn_total > 0 else math.inf

    # Identify dominant noise source
    noise_powers = {
        "quantisation": vn_q ** 2,
        "kTC_thermal": vn_ktc ** 2,
        "aperture_jitter": vn_jitter ** 2,
        "amplifier": vn_amp ** 2,
    }
    dominant = max(noise_powers, key=noise_powers.__getitem__)

    warn_list = []
    jitter_limited = False
    under_resolved = False
    thermal_limited = False

    # Jitter-limited flag: jitter noise power > 4× quantisation (6 dB)
    if vn_jitter ** 2 > 4.0 * vn_q ** 2:
        jitter_limited = True
        msg = (
            f"total_noise_budget: JITTER-LIMITED — jitter noise ({vn_jitter*1e6:.3f} µVrms) "
            f"exceeds quantisation noise ({vn_q*1e6:.3f} µVrms) by > 6 dB. "
            f"Reduce aperture jitter or lower input frequency."
        )
        warnings.warn(msg, stacklevel=2)
        warn_list.append(msg)

    # Under-resolved flag: quantisation dominates SNR by > 10 dB (others negligible)
    snr_q_only = 20.0 * math.log10(v_sig_rms / vn_q) if vn_q > 0 else math.inf
    if abs(snr_q_only - snr_total_db) < 1.0 and bits < 8:
        under_resolved = True
        msg = (
            f"total_noise_budget: UNDER-RESOLVED — {bits}-bit quantisation dominates; "
            f"consider higher resolution."
        )
        warnings.warn(msg, stacklevel=2)
        warn_list.append(msg)

    # Thermal-limited flag: kTC noise > 4× quantisation noise
    if vn_ktc ** 2 > 4.0 * vn_q ** 2:
        thermal_limited = True
        msg = (
            f"total_noise_budget: THERMAL-LIMITED — kTC noise ({vn_ktc*1e6:.3f} µVrms) "
            f"exceeds quantisation noise ({vn_q*1e6:.3f} µVrms) by > 6 dB. "
            f"Increase sampling capacitor."
        )
        warnings.warn(msg, stacklevel=2)
        warn_list.append(msg)

    return {
        "ok": True,
        "bits": bits,
        "v_fs": v_fs,
        "vn_q_vrms": vn_q,
        "vn_ktc_vrms": vn_ktc,
        "snr_jitter_db": round(snr_jitter_db, 2),
        "vn_jitter_vrms": vn_jitter,
        "vn_amp_vrms": vn_amp,
        "vn_total_vrms": vn_total,
        "snr_total_db": round(snr_total_db, 2),
        "dominant_noise": dominant,
        "jitter_limited": jitter_limited,
        "under_resolved": under_resolved,
        "thermal_limited": thermal_limited,
        "warnings_list": warn_list,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 6. oversampling_gain
# ═══════════════════════════════════════════════════════════════════════════════


def oversampling_gain(
    bits: int,
    osr: float,
    target_enob: Optional[float] = None,
) -> dict:
    """
    Oversampling and decimation processing gain.

    Process gain [dB] = 10 × log10(OSR) / 2  (3 dB per octave of oversampling)
    OSR = f_s / (2 × signal_BW)

    With decimation (sinc³ or similar), the noise floor in the signal band
    is reduced by the process gain, increasing the effective ENOB.

    Required OSR for a target ENOB:
        OSR_req = 4^(ENOB_target − ENOB_nyq)

    Flags (via warnings.warn):
      • OSR-insufficient: required OSR > 256 (impractical for most architectures)

    Parameters
    ----------
    bits        : int          — Nyquist-rate ADC resolution [bits]
    osr         : float        — oversampling ratio (≥ 1)
    target_enob : float | None — desired ENOB after decimation (optional)

    Returns
    -------
    dict: ok, bits, osr, snr_nyquist_db, process_gain_db, snr_with_osr_db,
          enob_with_osr, osr_required (if target_enob provided),
          osr_insufficient (flag)
    """
    err = _validate_bits(bits)
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(osr, (int, float)) or math.isnan(osr) or osr < 1.0:
        return {"ok": False, "reason": "osr must be a real number ≥ 1"}

    snr_nyq = 6.02 * bits + 1.76
    process_gain_db = 10.0 * math.log10(osr) / 2.0
    snr_osr = snr_nyq + process_gain_db
    enob_osr = (snr_osr - 1.76) / 6.02

    osr_required = None
    if target_enob is not None:
        if not isinstance(target_enob, (int, float)) or math.isnan(target_enob) or target_enob <= 0:
            return {"ok": False, "reason": "target_enob must be a positive number"}
        enob_nyq = (snr_nyq - 1.76) / 6.02
        osr_required = 4.0 ** max(0.0, target_enob - enob_nyq)

    osr_insufficient = False
    if osr_required is not None and osr_required > 256:
        osr_insufficient = True
        warnings.warn(
            f"oversampling_gain: OSR-INSUFFICIENT — achieving ENOB = {target_enob:.1f} from "
            f"a {bits}-bit ADC requires OSR = {osr_required:.0f}, which is impractical. "
            f"Use a higher-resolution Nyquist-rate converter or ΔΣ architecture.",
            stacklevel=2,
        )

    result = {
        "ok": True,
        "bits": bits,
        "osr": osr,
        "snr_nyquist_db": round(snr_nyq, 2),
        "process_gain_db": round(process_gain_db, 2),
        "snr_with_osr_db": round(snr_osr, 2),
        "enob_with_osr": round(enob_osr, 4),
        "osr_insufficient": osr_insufficient,
    }
    if osr_required is not None:
        result["target_enob"] = target_enob
        result["osr_required"] = round(osr_required, 1)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 7. delta_sigma_sqnr
# ═══════════════════════════════════════════════════════════════════════════════


def delta_sigma_sqnr(order: int, osr: float) -> dict:
    """
    Ideal SQNR for a ΔΣ modulator of given order and OSR.

    Candy & Temes (1992) ideal noise-shaping formula:
        SQNR [dB] ≈ 10×log10[ (π^(2L)) / (2L+1) ] + (6L+3) × 10×log10(OSR)
        where L = modulator order.

    Valid for first-order (L=1) through fifth-order (L=5) single-bit modulators.
    Higher orders require careful stability analysis (not modelled here).

    Flags (via warnings.warn):
      • order > 5: stability warnings required in practice
      • OSR < 4:  insufficient for noise shaping to be effective

    Parameters
    ----------
    order : int   — modulator order L (1–8)
    osr   : float — oversampling ratio (≥ 2)

    Returns
    -------
    dict: ok, order, osr, sqnr_db, enob_equivalent
    """
    if not isinstance(order, int) or order < 1 or order > 8:
        return {"ok": False, "reason": "order must be an integer in [1, 8]"}
    if not isinstance(osr, (int, float)) or math.isnan(osr) or osr < 2:
        return {"ok": False, "reason": "osr must be a real number ≥ 2"}

    L = order
    # SQNR [dB] = 10*log10(pi^(2L)/(2L+1)) + (6L+3)*10*log10(OSR)
    sqnr_db = (
        10.0 * math.log10((math.pi ** (2 * L)) / (2 * L + 1))
        + (6 * L + 3) * 10.0 * math.log10(osr)
    )
    enob = (sqnr_db - 1.76) / 6.02

    warn_list = []
    if order > 5:
        msg = (
            f"delta_sigma_sqnr: order-{order} modulator — practical stability requires "
            f"loop-filter optimization (e.g. CIFB/CRFB topology). Ideal SQNR reported."
        )
        warnings.warn(msg, stacklevel=2)
        warn_list.append(msg)

    osr_insufficient = False
    if osr < 4:
        osr_insufficient = True
        msg = (
            f"delta_sigma_sqnr: OSR = {osr:.1f} is very low for ΔΣ — noise shaping "
            f"requires OSR ≥ 4 to be effective."
        )
        warnings.warn(msg, stacklevel=2)
        warn_list.append(msg)

    return {
        "ok": True,
        "order": order,
        "osr": osr,
        "sqnr_db": round(sqnr_db, 2),
        "enob_equivalent": round(enob, 4),
        "osr_insufficient": osr_insufficient,
        "warnings_list": warn_list,
        "formula": "Candy & Temes (1992): SQNR = 10log10(π^(2L)/(2L+1)) + (6L+3)×10log10(OSR)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 8. sar_conversion_time
# ═══════════════════════════════════════════════════════════════════════════════


def sar_conversion_time(
    bits: int,
    t_comp_s: float,
    t_sw_s: float,
    r_src_ohm: float = 0.0,
    c_dac_f: float = 1e-12,
) -> dict:
    """
    SAR ADC conversion time including comparator and switch settling, plus
    RC settling time for the input kickback.

    SAR conversion time:
        t_convert = N × (t_comp + t_sw)

    RC settling to within 0.5 LSB (requires N+2 time constants):
        τ = R_src × C_dac
        t_settle_rc = (N + 2) × τ

    Total time (if RC settling is bottleneck):
        t_total = max(t_convert, t_settle_rc)

    Parameters
    ----------
    bits      : int   — ADC resolution [bits]
    t_comp_s  : float — comparator decision time per cycle [s]
    t_sw_s    : float — switch settling time per cycle [s]
    r_src_ohm : float — source resistance [Ω] (default 0 — no RC settling)
    c_dac_f   : float — DAC capacitance [F] (default 1 pF)

    Returns
    -------
    dict: ok, bits, t_compare_s, t_settle_rc_s, t_total_s, throughput_max_sps
    """
    err = _validate_bits(bits)
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(t_comp_s, "t_comp_s")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(t_sw_s, "t_sw_s")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_nonneg(r_src_ohm, "r_src_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(c_dac_f, "c_dac_f")
    if err:
        return {"ok": False, "reason": err}

    t_compare = bits * (t_comp_s + t_sw_s)
    tau = r_src_ohm * c_dac_f
    t_settle_rc = (bits + 2) * tau if r_src_ohm > 0 else 0.0
    t_total = max(t_compare, t_settle_rc)
    throughput = 1.0 / t_total if t_total > 0 else math.inf

    return {
        "ok": True,
        "bits": bits,
        "t_compare_s": t_compare,
        "t_settle_rc_s": t_settle_rc,
        "t_total_s": t_total,
        "throughput_max_sps": throughput,
        "tau_s": tau,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 9. pipeline_latency
# ═══════════════════════════════════════════════════════════════════════════════


def pipeline_latency(
    num_stages: int,
    bits_per_stage: int,
    t_clk_s: float,
    flash_bits: int = 0,
) -> dict:
    """
    Pipeline ADC latency, total bit resolution, and stage residue gain.

    Pipeline ADC model:
        Total effective bits ≈ num_stages × bits_per_stage + flash_bits
            (with digital redundancy correction, each stage contributes
             bits_per_stage raw bits minus 1 redundant bit, but for
             budgeting we report nominal resolution)
        Latency = num_stages × T_clk
        Stage residue gain = 2^bits_per_stage

    Parameters
    ----------
    num_stages     : int   — number of pipeline stages
    bits_per_stage : int   — bits resolved per stage (typical 1–4)
    t_clk_s        : float — clock period [s]
    flash_bits     : int   — flash backend bits (default 0)

    Returns
    -------
    dict: ok, num_stages, bits_per_stage, flash_bits, total_bits_nominal,
          latency_s, latency_clocks, stage_gain, throughput_sps
    """
    if not isinstance(num_stages, int) or num_stages < 1:
        return {"ok": False, "reason": "num_stages must be a positive integer"}
    if not isinstance(bits_per_stage, int) or bits_per_stage < 1 or bits_per_stage > 8:
        return {"ok": False, "reason": "bits_per_stage must be an integer in [1, 8]"}
    err = _validate_positive(t_clk_s, "t_clk_s")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(flash_bits, int) or flash_bits < 0:
        return {"ok": False, "reason": "flash_bits must be a non-negative integer"}

    total_bits = num_stages * bits_per_stage + flash_bits
    latency_s = num_stages * t_clk_s
    stage_gain = 2 ** bits_per_stage
    throughput = 1.0 / t_clk_s  # pipeline: one sample per clock after fill

    return {
        "ok": True,
        "num_stages": num_stages,
        "bits_per_stage": bits_per_stage,
        "flash_bits": flash_bits,
        "total_bits_nominal": total_bits,
        "latency_s": latency_s,
        "latency_clocks": num_stages,
        "stage_gain": stage_gain,
        "throughput_sps": throughput,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 10. dac_glitch_sfdr
# ═══════════════════════════════════════════════════════════════════════════════


def dac_glitch_sfdr(
    bits: int,
    inl_lsb: float,
    v_fs: float,
    v_glitch_v: float,
    t_glitch_s: float,
    tau_s: float,
) -> dict:
    """
    DAC glitch/settling analysis and SFDR estimate from INL.

    SFDR from INL (approximate):
        SFDR [dBc] ≈ −20×log10(INL_lsb × 2^(1−N))
        (INL in LSBs, N = bits)

    Glitch area (energy):
        E_glitch = V_glitch × t_glitch  [V·s]

    Settling time to 0.5 LSB:
        t_settle = τ × ln(2 × V_step × 2^N / V_fs)
        where V_step is the DAC output voltage step (taken as V_fs/2 worst case)

    Parameters
    ----------
    bits       : int   — DAC resolution [bits]
    inl_lsb    : float — integral nonlinearity [LSBs] (positive)
    v_fs       : float — full-scale voltage range [V]
    v_glitch_v : float — glitch voltage amplitude [V]
    t_glitch_s : float — glitch duration [s]
    tau_s      : float — output RC settling time constant [s]

    Returns
    -------
    dict: ok, bits, inl_lsb, sfdr_dbc, e_glitch_vs, t_settle_s, lsb_size_v
    """
    err = _validate_bits(bits)
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(inl_lsb, "inl_lsb")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(v_fs, "v_fs")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(v_glitch_v, "v_glitch_v")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(t_glitch_s, "t_glitch_s")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(tau_s, "tau_s")
    if err:
        return {"ok": False, "reason": err}

    lsb_v = v_fs / (2 ** bits)
    sfdr_dbc = -20.0 * math.log10(inl_lsb * (2 ** (1 - bits)))
    e_glitch = v_glitch_v * t_glitch_s

    # Settling: worst-case is a full-scale step (V_fs/2), settle to 0.5 LSB
    v_step = v_fs / 2.0
    arg = 2.0 * v_step * (2 ** bits) / v_fs  # = 2^bits, simplifies to bits
    t_settle = tau_s * math.log(arg) if arg > 1 else 0.0

    return {
        "ok": True,
        "bits": bits,
        "inl_lsb": inl_lsb,
        "v_fs": v_fs,
        "lsb_size_v": lsb_v,
        "sfdr_dbc": round(sfdr_dbc, 2),
        "e_glitch_vs": e_glitch,
        "t_settle_s": round(t_settle, 12),
        "formula": "SFDR ≈ −20log10(INL_lsb × 2^(1−N))",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 11. reference_noise_lsb
# ═══════════════════════════════════════════════════════════════════════════════


def reference_noise_lsb(
    bits: int,
    v_ref: float,
    e_ref_rms_v: float,
    drift_ppm_per_c: float = 0.0,
    delta_temp_c: float = 0.0,
) -> dict:
    """
    Reference noise and drift contribution to ADC/DAC LSB error.

    LSB size:
        LSB_v = V_ref / 2^N

    Reference-noise contribution to SNR:
        SNR_ref [dB] = 20×log10(V_ref / (sqrt(6) × 2^N × e_ref_rms))
        (quantisation-equivalent noise from reference noise)

    Drift error in LSBs:
        δ_lsb = (drift_ppm_per_°C × ΔT × V_ref / 1e6) / LSB_v
               = drift_ppm_per_°C × ΔT × 2^N / 1e6

    Parameters
    ----------
    bits           : int   — converter resolution [bits]
    v_ref          : float — reference voltage [V]
    e_ref_rms_v    : float — integrated reference noise [V RMS]
    drift_ppm_per_c : float — reference temperature coefficient [ppm/°C] (default 0)
    delta_temp_c   : float — temperature excursion [°C] (default 0)

    Returns
    -------
    dict: ok, bits, v_ref, lsb_v, e_ref_rms_v, snr_ref_db,
          drift_error_lsb, drift_error_v
    """
    err = _validate_bits(bits)
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(v_ref, "v_ref")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(e_ref_rms_v, "e_ref_rms_v")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_nonneg(drift_ppm_per_c, "drift_ppm_per_c")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_nonneg(delta_temp_c, "delta_temp_c")
    if err:
        return {"ok": False, "reason": err}

    lsb_v = v_ref / (2 ** bits)
    vn_q = v_ref / (math.sqrt(6.0) * (2 ** bits))
    snr_ref_db = 20.0 * math.log10(vn_q / e_ref_rms_v) if e_ref_rms_v > 0 else math.inf

    drift_v = (drift_ppm_per_c * delta_temp_c * v_ref) / 1e6
    drift_lsb = drift_v / lsb_v

    return {
        "ok": True,
        "bits": bits,
        "v_ref": v_ref,
        "lsb_v": lsb_v,
        "e_ref_rms_v": e_ref_rms_v,
        "snr_ref_db": round(snr_ref_db, 2),
        "drift_error_v": round(drift_v, 9),
        "drift_error_lsb": round(drift_lsb, 4),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 12. adc_driver_settling
# ═══════════════════════════════════════════════════════════════════════════════


def adc_driver_settling(
    bits: int,
    r_ohm: float,
    c_in_f: float,
    c_aa_f: Optional[float] = None,
) -> dict:
    """
    ADC driver and RC anti-alias filter kickback settling analysis.

    Kickback charge: ΔQ ≈ C_in × V_step  (V_step ≈ V_fs / 2 worst case)
    Settling time to within 0.5 LSB (N+2 time constants):
        τ = R × C_in
        t_settle = (N + 2) × τ

    Anti-alias filter −3 dB frequency (if C_aa provided):
        f_−3dB = 1 / (2π × R × C_aa)

    Minimum settling time for AA filter:
        t_settle_aa = (N + 2) × ln(2) / (2π × f_−3dB)

    Parameters
    ----------
    bits   : int         — ADC resolution [bits]
    r_ohm  : float       — driver source resistance [Ω]
    c_in_f : float       — ADC input capacitance (kickback / sample cap) [F]
    c_aa_f : float|None  — anti-alias filter capacitor [F] (optional)

    Returns
    -------
    dict: ok, bits, r_ohm, c_in_f, tau_s, t_settle_s,
          f_aa_3db_hz (None if c_aa_f not given), t_settle_aa_s (None if not given)
    """
    err = _validate_bits(bits)
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(r_ohm, "r_ohm")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(c_in_f, "c_in_f")
    if err:
        return {"ok": False, "reason": err}

    tau = r_ohm * c_in_f
    t_settle = (bits + 2) * tau

    f_aa = None
    t_settle_aa = None
    if c_aa_f is not None:
        err = _validate_positive(c_aa_f, "c_aa_f")
        if err:
            return {"ok": False, "reason": err}
        f_aa = 1.0 / (2.0 * math.pi * r_ohm * c_aa_f)
        # t_settle for AA: (N+2) × ln(2) / (2π × f_-3dB)
        t_settle_aa = (bits + 2) * math.log(2.0) / (2.0 * math.pi * f_aa)

    return {
        "ok": True,
        "bits": bits,
        "r_ohm": r_ohm,
        "c_in_f": c_in_f,
        "tau_s": tau,
        "t_settle_s": t_settle,
        "f_aa_3db_hz": f_aa,
        "t_settle_aa_s": t_settle_aa,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 13. bits_for_dynamic_range
# ═══════════════════════════════════════════════════════════════════════════════


def bits_for_dynamic_range(dr_db: float) -> dict:
    """
    Minimum ADC bits required to achieve a target dynamic range.

    Bennett (1948):
        N_min = ceil((DR_dB − 1.76) / 6.02)

    Parameters
    ----------
    dr_db : float — target dynamic range [dB]

    Returns
    -------
    dict: ok, dr_db, bits_min, snr_achieved_db, margin_db
    """
    err = _validate_positive(dr_db, "dr_db")
    if err:
        return {"ok": False, "reason": err}

    bits_exact = (dr_db - 1.76) / 6.02
    bits_min = max(1, math.ceil(bits_exact))
    snr_achieved = 6.02 * bits_min + 1.76
    margin_db = snr_achieved - dr_db

    return {
        "ok": True,
        "dr_db": round(dr_db, 2),
        "bits_min": bits_min,
        "snr_achieved_db": round(snr_achieved, 2),
        "margin_db": round(margin_db, 2),
        "formula": "N = ceil((DR_dB − 1.76) / 6.02)",
    }
