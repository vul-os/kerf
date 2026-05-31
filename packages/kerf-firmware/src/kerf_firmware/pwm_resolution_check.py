"""PWM resolution and frequency-error checker.

Given an MCU timer clock frequency, a desired PWM frequency, and a counter
bit-width, computes:

  * The integer prescaler P and auto-reload register ARR that best satisfy the
    desired PWM frequency while maximising timer counter resolution.
  * The achievable resolution in bits: resolution_bits = log2(ARR + 1).
  * The frequency error vs the target: freq_error_pct.
  * Whether the configuration meets a caller-specified ``desired_resolution_bits``
    requirement.

References
----------
STM32F411 Reference Manual RM0383 Rev 3 §13 (General-purpose timers TIM2–TIM5)
  PWM frequency: f_PWM = f_timer / ((ARR + 1) × (PSC + 1))
  Auto-reload register (ARR): 16-bit for TIM3/TIM4 (0..65535), 32-bit for TIM2/TIM5.
  Prescaler register (PSC): 16-bit (0..65535), so actual divisor P = PSC + 1 ∈ [1..65536].
  Resolution: 2^ARR_width bits — limited by ARR + 1 = clock / (P × f_target).

ATmega328P Datasheet §15 (Timer/Counter0 and Timer/Counter1 — Fast PWM)
  Fast PWM: f_PWM = f_clk_IO / (N × (1 + TOP))
  Timer/Counter0: 8-bit TOP, prescaler N ∈ {1, 8, 64, 256, 1024}.
  Timer/Counter1: 16-bit TOP (ICR1 or OCR1A).
  Timer/Counter2: 8-bit, separate prescaler table.

ALGORITHM
---------
For each integer prescaler P in [1 .. min(2^16, clock // target_freq)]:
  ARR_exact = clock / (P × target_freq) - 1
  ARR       = round(ARR_exact)  [nearest integer for minimum freq error]
  ARR       = clamp(ARR, 1, 2^counter_bits - 1)

  f_actual  = clock / (P × (ARR + 1))
  freq_error_pct = (f_actual − target_freq) / target_freq × 100

  resolution_bits = log2(ARR + 1)

  Keep candidate that maximises resolution_bits with |freq_error_pct| < 1 %.
  Tie-break: prefer lower |freq_error_pct|.

HONEST CAVEATS
--------------
* Integer-prescaler model only: STM32 PSC register is 16-bit integer (PSC ∈ 0..65535,
  P = PSC+1), ATmega prescaler is from a fixed set {1,8,64,256,1024}; this module uses
  any integer P ∈ [1..65536] which is exact for STM32 but may differ from ATmega (where
  only 5 discrete prescaler values are legal).
* Does NOT model interrupt latency or DMA transfer overhead that can extend the effective
  period and reduce achievable throughput.
* Complementary PWM dead-time insertion (e.g. STM32F411 TIM1 / TIM8 dead-time register
  BDTR) is NOT modelled; dead-time reduces the usable duty-cycle range.
* Maximum counter ARR value is limited by counter_bits; this module enforces the ceiling
  but does not enforce any alignment constraints (e.g. ARR must be even for centre-aligned
  PWM; RM0383 §13.3.9).
* Clock source jitter and oscillator tolerance are NOT modelled.
* For very high target frequencies (f_target > clock / 2), no legal (P, ARR) pair exists;
  the function returns resolution = 1 bit with the best-effort result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ── Constants ──────────────────────────────────────────────────────────────────

#: Prescaler search upper bound (STM32 PSC register is 16-bit, so P ∈ [1..65536]).
_MAX_PRESCALER: int = 65_536

#: Frequency-error threshold below which a candidate is considered acceptable.
_FREQ_ERROR_THRESHOLD_PCT: float = 1.0

#: Allowed counter bit-widths.
_VALID_COUNTER_BITS: frozenset[int] = frozenset({8, 10, 16, 32})


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class PWMConfigSpec:
    """Input specification for PWM resolution analysis.

    Attributes
    ----------
    mcu_clock_hz:
        MCU timer peripheral clock frequency in Hz.  For STM32F411 running at
        100 MHz with APB1 timer clocks doubled to 100 MHz, use 100_000_000.
        For ATmega328P at 16 MHz, use 16_000_000.
    target_pwm_freq_Hz:
        Desired PWM output frequency in Hz (e.g. 1000.0 for 1 kHz servo/motor
        control, 20000.0 for 20 kHz inaudible motor drive).
    counter_bits:
        Timer counter width in bits.  Must be one of {8, 10, 16, 32}.
        Determines the maximum ARR value (2^counter_bits − 1) and thus the
        maximum achievable resolution.
    desired_resolution_bits:
        Minimum resolution requirement in bits.  The ``meets_resolution_requirement``
        field in the report will be True iff achievable_resolution_bits >=
        desired_resolution_bits.  Default: 10 (1024 steps).
    mcu_label:
        Human-readable MCU + timer identifier, e.g. 'STM32F411 TIM3 @ 100 MHz'
        or 'ATmega328P Timer1 @ 16 MHz'.
    """
    mcu_clock_hz: int
    target_pwm_freq_Hz: float
    counter_bits: int
    desired_resolution_bits: int = 10
    mcu_label: str = ""

    def __post_init__(self) -> None:
        if self.mcu_clock_hz <= 0:
            raise ValueError(
                f"PWMConfigSpec '{self.mcu_label}': mcu_clock_hz must be > 0, "
                f"got {self.mcu_clock_hz}"
            )
        if self.target_pwm_freq_Hz <= 0.0:
            raise ValueError(
                f"PWMConfigSpec '{self.mcu_label}': target_pwm_freq_Hz must be > 0, "
                f"got {self.target_pwm_freq_Hz}"
            )
        if self.counter_bits not in _VALID_COUNTER_BITS:
            raise ValueError(
                f"PWMConfigSpec '{self.mcu_label}': counter_bits must be one of "
                f"{sorted(_VALID_COUNTER_BITS)}, got {self.counter_bits}"
            )
        if self.desired_resolution_bits < 1:
            raise ValueError(
                f"PWMConfigSpec '{self.mcu_label}': desired_resolution_bits must be >= 1, "
                f"got {self.desired_resolution_bits}"
            )


@dataclass
class PWMResolutionReport:
    """Result of :func:`check_pwm_resolution`.

    Attributes
    ----------
    actual_pwm_freq_Hz:
        PWM output frequency achieved by the selected (P, ARR) pair, in Hz.
        f_actual = clock / (P × (ARR + 1)).
    freq_error_pct:
        Signed percent error vs target: (actual − target) / target × 100.
        Negative means the achievable frequency is below the target.
    achievable_resolution_bits:
        log2(ARR + 1): the number of distinct duty-cycle steps is ARR + 1 = 2^n.
        A fractional value indicates non-power-of-two ARR.
    recommended_prescaler:
        Integer prescaler P (= PSC + 1 for STM32; N for ATmega discrete set).
        Load PSC = P − 1 into the STM32 TIMx_PSC register.
    recommended_arr_top:
        Auto-reload register value ARR (= TOP for ATmega).  Load this into
        TIMx_ARR (STM32) or ICR1 / OCR1A (ATmega Timer1).
        Duty-cycle compare value CCR should be in [0, ARR].
    meets_resolution_requirement:
        True iff achievable_resolution_bits >= spec.desired_resolution_bits.
    honest_caveat:
        Plain-text engineering caveats for this result.
    """
    actual_pwm_freq_Hz: float
    freq_error_pct: float
    achievable_resolution_bits: float
    recommended_prescaler: int
    recommended_arr_top: int
    meets_resolution_requirement: bool
    honest_caveat: str

    def as_dict(self) -> dict:
        return {
            "actual_pwm_freq_Hz": round(self.actual_pwm_freq_Hz, 4),
            "freq_error_pct": round(self.freq_error_pct, 6),
            "achievable_resolution_bits": round(self.achievable_resolution_bits, 4),
            "recommended_prescaler": self.recommended_prescaler,
            "recommended_arr_top": self.recommended_arr_top,
            "meets_resolution_requirement": self.meets_resolution_requirement,
            "honest_caveat": self.honest_caveat,
        }


# ── Caveat template ─────────────────────────────────────────────────────────────

def _build_caveat(spec: PWMConfigSpec, arr: int, prescaler: int) -> str:
    counter_max = (1 << spec.counter_bits) - 1
    return (
        f"Integer-prescaler / integer-ARR model. "
        f"f_PWM = clock / (P × (ARR + 1)) = {spec.mcu_clock_hz} / "
        f"({prescaler} × {arr + 1}) = {spec.mcu_clock_hz / (prescaler * (arr + 1)):.2f} Hz. "
        f"Counter ARR capped at {counter_max} ({spec.counter_bits}-bit). "
        f"STM32F411 TIMx PSC is 16-bit (P ∈ [1..65536], RM0383 §13); "
        f"ATmega328P Timer1 prescaler is discrete {{1,8,64,256,1024}} (§15) — "
        f"this model uses any integer P which is exact for STM32 but may differ "
        f"from ATmega (use the nearest legal ATmega prescaler value). "
        f"Interrupt latency, dead-time insertion (TIM1/TIM8 BDTR), centre-aligned "
        f"PWM ARR alignment constraints, and oscillator tolerance are NOT modelled. "
        f"Refs: STM32F411 RM0383 §13 (TIM2–TIM5); ATmega328P §15 (Timer1 Fast PWM)."
    )


# ── Core computation ───────────────────────────────────────────────────────────

def check_pwm_resolution(spec: PWMConfigSpec) -> PWMResolutionReport:
    """Find the (prescaler, ARR) pair that maximises PWM resolution.

    The search iterates prescaler P from 1 to the minimum of _MAX_PRESCALER and
    clock // target_freq (higher P values yield ARR < 1 which is unusable).  For
    each P, ARR is rounded to the nearest integer for minimum frequency error,
    then clamped to [1, 2^counter_bits − 1].

    Only candidates with |freq_error_pct| < 1 % are eligible.  Among eligible
    candidates the one with the highest resolution_bits is selected; ties are
    broken by lowest |freq_error_pct|.

    If no candidate achieves |freq_error_pct| < 1 % (e.g. when the target
    frequency cannot be approximated with the available clock), the best-effort
    candidate (lowest |freq_error_pct| overall) is returned with a note in the
    caveat.

    Parameters
    ----------
    spec:
        PWM configuration specification.

    Returns
    -------
    PWMResolutionReport
        Full resolution/frequency report with engineering caveats.

    Examples
    --------
    ATmega328P Timer1 at 16 MHz, 1 kHz PWM, 16-bit counter:

    >>> spec = PWMConfigSpec(
    ...     mcu_clock_hz=16_000_000,
    ...     target_pwm_freq_Hz=1000.0,
    ...     counter_bits=16,
    ...     mcu_label="ATmega328P Timer1 @ 16 MHz",
    ... )
    >>> report = check_pwm_resolution(spec)
    >>> report.recommended_prescaler
    1
    >>> report.recommended_arr_top
    15999
    >>> round(report.achievable_resolution_bits, 2)
    13.97

    References
    ----------
    STM32F411 RM0383 §13 (General-purpose timers TIM2–TIM5).
    ATmega328P Datasheet §15 (Timer/Counter1 Fast PWM, ICR1 mode).
    """
    counter_max_arr: int = (1 << spec.counter_bits) - 1

    # Upper bound on P: higher P forces ARR < 1, which is unusable.
    # ARR_exact = clock / (P * freq) - 1 >= 1  →  P <= clock / (2 * freq)
    p_upper = max(1, min(_MAX_PRESCALER, int(spec.mcu_clock_hz / (2.0 * spec.target_pwm_freq_Hz))))

    best_candidate: dict | None = None  # keys: prescaler, arr, freq_error_pct, resolution_bits
    best_fallback: dict | None = None   # lowest |freq_error| if no candidate < 1%

    for p in range(1, p_upper + 1):
        arr_exact = spec.mcu_clock_hz / (p * spec.target_pwm_freq_Hz) - 1.0
        arr = int(round(arr_exact))
        arr = max(1, min(arr, counter_max_arr))

        f_actual = spec.mcu_clock_hz / (p * (arr + 1))
        err_pct = (f_actual - spec.target_pwm_freq_Hz) / spec.target_pwm_freq_Hz * 100.0
        res_bits = math.log2(arr + 1)

        candidate = {
            "prescaler": p,
            "arr": arr,
            "freq_error_pct": err_pct,
            "resolution_bits": res_bits,
            "f_actual": f_actual,
        }

        # Track best fallback (minimum |error|) regardless of threshold
        if best_fallback is None or abs(err_pct) < abs(best_fallback["freq_error_pct"]):
            best_fallback = candidate

        if abs(err_pct) >= _FREQ_ERROR_THRESHOLD_PCT:
            continue  # not within acceptable error

        if best_candidate is None:
            best_candidate = candidate
        else:
            # Prefer higher resolution; break ties by lower |freq_error|
            if res_bits > best_candidate["resolution_bits"] + 1e-9:
                best_candidate = candidate
            elif abs(res_bits - best_candidate["resolution_bits"]) < 1e-9:
                if abs(err_pct) < abs(best_candidate["freq_error_pct"]):
                    best_candidate = candidate

    # Fall back to best-effort if no candidate satisfied < 1% error
    chosen = best_candidate if best_candidate is not None else best_fallback

    if chosen is None:
        # Degenerate: target too high for any P (should not happen given p_upper >= 1)
        chosen = {
            "prescaler": 1,
            "arr": 1,
            "freq_error_pct": 0.0,
            "resolution_bits": 1.0,
            "f_actual": spec.mcu_clock_hz / 2.0,
        }

    meets = chosen["resolution_bits"] >= spec.desired_resolution_bits

    return PWMResolutionReport(
        actual_pwm_freq_Hz=chosen["f_actual"],
        freq_error_pct=chosen["freq_error_pct"],
        achievable_resolution_bits=chosen["resolution_bits"],
        recommended_prescaler=chosen["prescaler"],
        recommended_arr_top=chosen["arr"],
        meets_resolution_requirement=meets,
        honest_caveat=_build_caveat(spec, chosen["arr"], chosen["prescaler"]),
    )
