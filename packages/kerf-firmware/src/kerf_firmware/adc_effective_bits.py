"""ADC Effective Number of Bits (ENOB) calculator.

Computes the effective number of bits of an MCU ADC from either:
  * a SINAD specification (ENOB = (SINAD_dB - 1.76) / 6.02), or
  * a directly-specified ENOB from the datasheet.

Optionally improves ENOB through oversampling (averaging N samples and
decimating): each doubling of the oversampling ratio (OSR) adds 0.5 effective
bits, so OSR = 4^k gives k additional bits.

Also recommends the OSR needed to reach a user-supplied target_bits.

References
----------
  Analog Devices MT-003 (Rev. B) — "Understand SINAD, ENOB, SNR, THD,
    THD+N, and SFDR So You Don't Get Lost in the Noise Floor":
    ENOB = (SINAD_dB − 1.76) / 6.02.
  Texas Instruments SBAA221 — "Oversampling and Decimation to Increase ADC
    Resolution": ENOB_after = ENOB + log2(OSR) / 2; requires OSR white-noise
    samples averaged and then decimated (√OSR noise reduction); actual gain
    limited by correlated noise sources (PSU ripple, 50/60 Hz mains hum,
    quantisation plateaux on slowly-varying signals).
  Maxim Integrated AN2861 — "Oversampling for ADCs".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

#: SINAD-to-ENOB conversion numerator offset per ADI MT-003.
_SINAD_OFFSET: float = 1.76

#: SINAD-to-ENOB conversion denominator (6.02 dB/bit for full-scale sine).
_SINAD_SCALE: float = 6.02

#: Oversampling gain per ADI / TI: each doubling of OSR → +0.5 effective bits.
#: ENOB_after = ENOB + log2(OSR) / 2.
_OVERSAMPLING_GAIN_PER_LOG2_OSR: float = 0.5


# ── Input dataclasses ─────────────────────────────────────────────────────────

@dataclass
class ADCSpec:
    """Specification for an MCU ADC channel.

    Attributes
    ----------
    nominal_bits:
        Nominal (architectural) resolution in bits, e.g. 12 for a 12-bit ADC.
    sinad_dB:
        Signal-to-Noise-And-Distortion ratio in dB at full-scale input, from
        the datasheet AC-performance table.  Used to compute ENOB when
        ``enob_specified`` is None.  Typical: 12-bit ADCs specify ~68–74 dB.
    enob_specified:
        Effective Number Of Bits read directly from the datasheet.  When both
        ``sinad_dB`` and ``enob_specified`` are provided, ``enob_specified``
        takes priority.  When neither is provided, a nominal estimate
        (ENOB = nominal_bits − 0.5) is used with a caveat.
    sampling_rate_Hz:
        ADC sampling rate in Hz (used for informational notes only; does not
        affect ENOB arithmetic).
    reference_voltage_V:
        ADC reference voltage in volts (VREF+, e.g. 3.3 V for most MCUs).
    signal_full_scale_V:
        Peak-to-peak voltage of the actual input signal.  Used to compute the
        effective voltage resolution after oversampling.  Must be ≤
        reference_voltage_V.
    """
    nominal_bits: int
    sampling_rate_Hz: int
    reference_voltage_V: float
    signal_full_scale_V: float
    sinad_dB: Optional[float] = None
    enob_specified: Optional[float] = None

    def __post_init__(self) -> None:
        if self.nominal_bits < 1 or self.nominal_bits > 32:
            raise ValueError(
                f"nominal_bits must be in [1, 32], got {self.nominal_bits}"
            )
        if self.sampling_rate_Hz <= 0:
            raise ValueError(
                f"sampling_rate_Hz must be > 0, got {self.sampling_rate_Hz}"
            )
        if self.reference_voltage_V <= 0:
            raise ValueError(
                f"reference_voltage_V must be > 0, got {self.reference_voltage_V}"
            )
        if self.signal_full_scale_V <= 0:
            raise ValueError(
                f"signal_full_scale_V must be > 0, got {self.signal_full_scale_V}"
            )
        if self.signal_full_scale_V > self.reference_voltage_V:
            raise ValueError(
                f"signal_full_scale_V ({self.signal_full_scale_V} V) must be ≤ "
                f"reference_voltage_V ({self.reference_voltage_V} V)"
            )
        if self.sinad_dB is not None and self.sinad_dB <= 0:
            raise ValueError(
                f"sinad_dB must be > 0, got {self.sinad_dB}"
            )
        if self.enob_specified is not None and self.enob_specified <= 0:
            raise ValueError(
                f"enob_specified must be > 0, got {self.enob_specified}"
            )


@dataclass
class OversamplingSpec:
    """Oversampling and decimation parameters.

    Attributes
    ----------
    oversample_ratio:
        Number of raw ADC samples accumulated before decimation.  Must be a
        positive integer; powers-of-4 (1, 4, 16, 64, 256, …) give exactly
        integer extra bits.  The ENOB gain formula works for any positive OSR.
    decimation:
        Decimation factor applied after accumulation.  For the standard
        "accumulate OSR samples and divide-by-OSR" implementation, set this
        to ``oversample_ratio``.  Informational only — does not change the
        ENOB computation (which depends only on the noise averaging gain
        implied by oversample_ratio).
    """
    oversample_ratio: int = 1
    decimation: int = 1

    def __post_init__(self) -> None:
        if self.oversample_ratio < 1:
            raise ValueError(
                f"oversample_ratio must be ≥ 1, got {self.oversample_ratio}"
            )
        if self.decimation < 1:
            raise ValueError(
                f"decimation must be ≥ 1, got {self.decimation}"
            )


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class ADCEffectiveBitsReport:
    """Result of :func:`compute_adc_enob`.

    Attributes
    ----------
    enob_no_oversampling:
        ENOB before any oversampling, derived from ``sinad_dB`` (via ADI
        MT-003 formula) or ``enob_specified``, or nominal estimate.
    enob_after_oversampling:
        ENOB after applying the oversampling gain:
        ``enob_no_oversampling + log2(OSR) / 2``.
    effective_resolution_uV:
        Voltage resolution in microvolts of the effective ADC+oversampling
        system, scaled to the actual signal swing:
        ``signal_full_scale_V / 2^enob_after_oversampling × 1e6 µV``.
    recommended_oversample_ratio_for_target_bits:
        Smallest power-of-4 OSR that achieves ``target_bits`` effective bits
        from the base ENOB.  None when ``target_bits`` was not requested or
        base ENOB already meets the target.
    snr_dB:
        Estimated SNR in dB for the combined system.  Derived as:
        ``6.02 × enob_after_oversampling + 1.76`` (inverse ADI MT-003).
    honest_caveat:
        Plain-English caveat summarising what this model does NOT capture.
    """
    enob_no_oversampling: float
    enob_after_oversampling: float
    effective_resolution_uV: float
    recommended_oversample_ratio_for_target_bits: Optional[int]
    snr_dB: float
    honest_caveat: str

    def as_dict(self) -> dict:
        return {
            "enob_no_oversampling": round(self.enob_no_oversampling, 4),
            "enob_after_oversampling": round(self.enob_after_oversampling, 4),
            "effective_resolution_uV": round(self.effective_resolution_uV, 4),
            "recommended_oversample_ratio_for_target_bits": (
                self.recommended_oversample_ratio_for_target_bits
            ),
            "snr_dB": round(self.snr_dB, 4),
            "honest_caveat": self.honest_caveat,
        }


# ── Core computation ──────────────────────────────────────────────────────────

def _enob_from_sinad(sinad_dB: float) -> float:
    """Compute ENOB from SINAD per ADI MT-003.

    Formula: ENOB = (SINAD_dB − 1.76) / 6.02

    Parameters
    ----------
    sinad_dB:
        Signal-to-Noise-And-Distortion ratio in dB.

    Returns
    -------
    float
        Effective number of bits.

    Examples
    --------
    >>> round(_enob_from_sinad(68.0), 4)
    11.0332

    References
    ----------
    ADI MT-003 Rev. B — Equation 1.
    """
    return (sinad_dB - _SINAD_OFFSET) / _SINAD_SCALE


def _enob_gain_from_osr(osr: int) -> float:
    """Compute the ENOB gain from an oversampling ratio.

    ENOB_gain = log2(OSR) / 2 = log2(sqrt(OSR))

    Parameters
    ----------
    osr:
        Oversampling ratio (number of accumulated samples).

    Returns
    -------
    float
        Additional effective bits provided by oversampling.

    Examples
    --------
    >>> round(_enob_gain_from_osr(16), 4)
    2.0

    References
    ----------
    TI SBAA221 — Section 2.1: each 4× OSR adds 1 bit.
    Maxim AN2861 — Table 1: OSR to extra bits.
    """
    if osr <= 1:
        return 0.0
    return math.log2(osr) * _OVERSAMPLING_GAIN_PER_LOG2_OSR


def _recommend_osr_for_target(base_enob: float, target_bits: float) -> Optional[int]:
    """Return the smallest power-of-4 OSR that lifts base_enob to target_bits.

    OSR = 4^(target_bits − base_enob)

    If base_enob already meets or exceeds target_bits, returns None.

    Parameters
    ----------
    base_enob:
        ENOB before oversampling.
    target_bits:
        Desired effective number of bits.

    Returns
    -------
    int or None
        Recommended OSR as the smallest power-of-4 ≥ the exact value, or
        None if base_enob >= target_bits.

    Examples
    --------
    >>> _recommend_osr_for_target(11.0, 14.0)
    64

    References
    ----------
    TI SBAA221 — OSR = 4^(extra_bits_needed).
    """
    if base_enob >= target_bits:
        return None
    extra_bits = target_bits - base_enob
    # exact: 4^extra_bits; round up to next power of 4
    exact_osr = 4.0 ** extra_bits
    # Enumerate powers of 4 (= squares of powers of 2): 1, 4, 16, 64, 256, ...
    k = 0
    while (4 ** k) < exact_osr - 1e-9:
        k += 1
    return 4 ** k


_OVERSAMPLING_CAVEAT = (
    "OVERSAMPLING MODEL ASSUMES WHITE (RANDOM) NOISE ONLY. "
    "Correlated noise sources — mains-frequency hum (50/60 Hz), PSU switching "
    "ripple, reference noise, and quantisation plateaux on slowly-varying DC "
    "signals — DO NOT average out with oversampling; they limit the practical "
    "ENOB improvement to well below the theoretical log2(OSR)/2 gain. "
    "Thermal noise (kT/C) on the sample-and-hold capacitor sets an absolute "
    "floor that oversampling cannot overcome. "
    "Dither injection (a small white-noise signal added before sampling) can "
    "break quantisation plateaux and partially recover theoretical gain. "
    "Ref: ADI MT-003 Rev. B; TI SBAA221; Maxim AN2861."
)


def compute_adc_enob(
    adc: ADCSpec,
    oversampling: OversamplingSpec,
    target_bits: Optional[float] = None,
) -> ADCEffectiveBitsReport:
    """Compute the effective number of bits of an ADC, optionally with oversampling.

    Algorithm
    ---------
    1. Derive base ENOB (priority order):
       a. If ``adc.enob_specified`` is set → use directly.
       b. Elif ``adc.sinad_dB`` is set → ENOB = (SINAD_dB − 1.76) / 6.02.
       c. Else → ENOB = nominal_bits − 0.5 (rough estimate; caveat added).
    2. Apply oversampling gain:
       ENOB_after = ENOB + log2(OSR) / 2.
    3. Compute voltage resolution:
       LSB_V = signal_full_scale_V / 2^ENOB_after.
       effective_resolution_uV = LSB_V × 1e6.
    4. Estimate SNR:
       SNR_dB = 6.02 × ENOB_after + 1.76 (inverse ADI MT-003 formula).
    5. Recommend OSR for target (if provided):
       recommended_osr = 4^ceil(target_bits − base_enob).

    Parameters
    ----------
    adc:
        ADC specification.
    oversampling:
        Oversampling / decimation parameters.
    target_bits:
        Desired effective resolution in bits.  When provided, the tool
        calculates the minimum power-of-4 OSR required.

    Returns
    -------
    ADCEffectiveBitsReport
        Full report with ENOB before/after oversampling, voltage resolution,
        recommended OSR, estimated SNR, and honest caveats.

    Raises
    ------
    ValueError
        If any parameter is out of range.

    Examples
    --------
    12-bit ADC, SINAD = 68 dB, no oversampling:
    >>> spec = ADCSpec(12, 100_000, 3.3, 3.3, sinad_dB=68.0)
    >>> os = OversamplingSpec()
    >>> r = compute_adc_enob(spec, os)
    >>> round(r.enob_no_oversampling, 2)
    11.03

    Same ADC, OSR = 16:
    >>> os16 = OversamplingSpec(oversample_ratio=16)
    >>> r16 = compute_adc_enob(spec, os16)
    >>> round(r16.enob_after_oversampling, 2)
    13.03

    References
    ----------
    ADI MT-003 Rev. B — SINAD-to-ENOB formula; SNR = 6.02·N + 1.76 for sine.
    TI SBAA221 — Oversampling / decimation; each 4× OSR adds 1 bit.
    Maxim AN2861 — Practical oversampling guidance.
    """
    # ── 1. Derive base ENOB ───────────────────────────────────────────────────
    used_nominal_fallback = False

    if adc.enob_specified is not None:
        base_enob = adc.enob_specified
        enob_source = f"datasheet ENOB = {base_enob:.4f} bits"
    elif adc.sinad_dB is not None:
        base_enob = _enob_from_sinad(adc.sinad_dB)
        enob_source = (
            f"ENOB = (SINAD {adc.sinad_dB:.2f} dB − {_SINAD_OFFSET}) / {_SINAD_SCALE} "
            f"= {base_enob:.4f} bits (ADI MT-003)"
        )
    else:
        base_enob = float(adc.nominal_bits) - 0.5
        enob_source = (
            f"ENOB estimated as nominal_bits − 0.5 = {base_enob:.4f} bits "
            "(no SINAD or datasheet ENOB provided; this is a rough approximation)"
        )
        used_nominal_fallback = True

    # ── 2. Apply oversampling gain ────────────────────────────────────────────
    osr = oversampling.oversample_ratio
    gain = _enob_gain_from_osr(osr)
    enob_after = base_enob + gain

    # ── 3. Voltage resolution ─────────────────────────────────────────────────
    # LSB voltage at the effective resolution, relative to signal swing
    effective_lsb_V = adc.signal_full_scale_V / (2.0 ** enob_after)
    resolution_uV = effective_lsb_V * 1e6

    # ── 4. SNR estimate ───────────────────────────────────────────────────────
    snr_dB = _SINAD_SCALE * enob_after + _SINAD_OFFSET

    # ── 5. Recommended OSR for target ─────────────────────────────────────────
    rec_osr: Optional[int] = None
    if target_bits is not None:
        rec_osr = _recommend_osr_for_target(base_enob, target_bits)

    # ── Build caveat ──────────────────────────────────────────────────────────
    caveats: list[str] = []
    if osr > 1:
        caveats.append(_OVERSAMPLING_CAVEAT)
    if used_nominal_fallback:
        caveats.append(
            "ENOB WAS ESTIMATED from nominal_bits − 0.5 because neither sinad_dB "
            "nor enob_specified was provided. Obtain SINAD or ENOB from the ADC "
            "datasheet AC-performance table for an accurate result."
        )
    if not caveats:
        caveats.append(
            "No oversampling applied. ENOB reflects the single-sample conversion "
            "quality per ADI MT-003. Correlated interference (mains hum, PSU noise) "
            "may further degrade real-world dynamic range."
        )

    caveat = "  |  ".join(caveats)

    return ADCEffectiveBitsReport(
        enob_no_oversampling=base_enob,
        enob_after_oversampling=enob_after,
        effective_resolution_uV=resolution_uV,
        recommended_oversample_ratio_for_target_bits=rec_osr,
        snr_dB=snr_dB,
        honest_caveat=caveat,
    )
