"""Watchdog timeout interval checker.

Computes the actual watchdog timeout interval for MCU IWDG/WDT peripherals given
the oscillator clock, prescaler, and reload value, then verifies that the timeout
covers the application's worst-case loop latency with an adequate safety margin.

Architecture references
-----------------------
STM32F411 Reference Manual (RM0383 Rev 3) §17 — Independent Watchdog (IWDG):
  * Clock source: LSI RC oscillator, typically 32 kHz (not prescised — varies
    ±10–15% with temperature/process; check RM0383 Table 54 for min/typ/max).
  * Prescaler register PR: values 4, 8, 16, 32, 64, 128, 256 (PR[2:0] bits).
  * Reload register RLR: 0–4095 (12-bit; loaded into 12-bit down-counter).
  * Timeout formula: t = (prescaler × (reload + 1)) / f_LSI
  * IWDG counter counts DOWN from reload to 0, then resets the MCU.

ATmega328P Datasheet §11 — Watchdog Timer:
  * Clock source: Internal 128 kHz oscillator (typ; varies ±10% temperature,
    ±15% voltage — see ATmega328P Electrical Characteristics §32).
  * Prescaler options: 2K, 4K, 8K, 16K, 32K, 64K, 128K, 256K, 512K, 1024K
    (i.e. prescaler = 2048 .. 1048576) — but the WDT has an independent fixed
    prescaler chain; for simplicity this module models the prescaler as an integer
    divider applied to the nominal WDT clock as supplied by the user.
  * Reload register: 0–1023 (10-bit), but in practice the ATmega328P WDT has
    a fixed set of timeout periods (16 ms – 8 s) selected by WDTO fuse bits, not
    a free-reload register. This module models the general formula for consistency.

General timeout formula (both architectures)
--------------------------------------------
  timeout_s = prescaler × (reload + 1) / clock_hz

Adequacy criterion (ARM Keil AN259 + IEC 61508 SIL-2 watchdog guidance)
------------------------------------------------------------------------
  adequate = actual_timeout_ms > 2 × worst_case_loop_ms

Rationale: the watchdog must not expire during the legitimate slowest execution
path. A factor of 2× gives the ISR, DMA, and scheduling jitter budget without
requiring the application to do more than one kick per loop iteration. A factor
of 2.5× is used for the recommended reload calculation to give a visible margin.

HONEST CAVEATS
--------------
* This model assumes the LSI/internal RC oscillator frequency is ideal (exactly
  the nominal clock_hz). In practice, STM32 LSI varies ±10–15% over temperature
  and process (RM0383 Table 54). ATmega128 kHz WDT varies ±10% (Vcc) × ±10%
  (temperature). Real safety margin should subtract ≥10% from the computed
  timeout to account for oscillator tolerance.
* The 2× adequate threshold is a minimum design rule, not a guarantee. For
  safety-critical applications (ISO 26262, IEC 61508) a dedicated watchdog
  manager (window watchdog, challenge-response) is required.
* This check does NOT model the STM32 Window Watchdog (WWDG), which adds an
  open-window upper-bound constraint. IWDG only.
* ATmega WDT reload-value parameter is provided for API consistency; in
  firmware the ATmega WDT period is set by WDTO fuse bits, not an arbitrary
  reload register. Use the formula output as an approximation for fixed periods.
* Clock source accuracy is not calibrated or trimmed in this model.

References
----------
  STM32F411 Reference Manual RM0383 Rev 3, §17 — IWDG.
  ATmega328P Datasheet Rev 7810D §11 — Watchdog Timer.
  ARM Keil Application Note AN259 — Using Watchdog Timers in Embedded Systems.
  IEC 61508:2010 Part 2, §7.4.3.7 — Watchdog monitoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class WatchdogConfig:
    """Watchdog peripheral configuration.

    Attributes
    ----------
    clock_hz:
        Watchdog clock source frequency in Hz.
        Typical values:
          * STM32F411 IWDG: 32_000 (LSI RC, typ).
          * ATmega328P WDT: 128_000 (internal RC, typ).
    prescaler:
        Integer prescaler applied to the clock before the countdown counter.
        STM32F411 IWDG PR valid values: 4, 8, 16, 32, 64, 128, 256.
        ATmega WDT prescaler chain: 2048, 4096, 8192, 16384, 32768, 65536,
          131072, 262144, 524288, 1048576 (from §11 Table 11-2).
        Any positive integer is accepted by this model; the caller is
        responsible for using a value the hardware actually supports.
    reload_value:
        Down-counter initial (reload) value.
        STM32F411 IWDG RLR: 0–4095 (12-bit counter).
        ATmega328P WDT: 0–1023 (10-bit WDTO value, used for formula consistency).
        Counter counts from reload_value down to 0 then triggers a reset.
    mcu_label:
        Human-readable MCU/watchdog identifier, e.g.
        ``"STM32F411CE IWDG"`` or ``"ATmega328P WDT"``.
    """
    clock_hz: int
    prescaler: int
    reload_value: int
    mcu_label: str

    def __post_init__(self) -> None:
        if self.clock_hz <= 0:
            raise ValueError(
                f"WatchdogConfig '{self.mcu_label}': clock_hz must be > 0, "
                f"got {self.clock_hz}"
            )
        if self.prescaler <= 0:
            raise ValueError(
                f"WatchdogConfig '{self.mcu_label}': prescaler must be > 0, "
                f"got {self.prescaler}"
            )
        if self.reload_value < 0:
            raise ValueError(
                f"WatchdogConfig '{self.mcu_label}': reload_value must be >= 0, "
                f"got {self.reload_value}"
            )


@dataclass
class WorstCaseLoopLatency:
    """Application worst-case loop (kick) latency estimate.

    Attributes
    ----------
    worst_case_ms:
        Worst-case time between consecutive watchdog kicks, in milliseconds.
        This must cover ALL paths through the application loop:
          * ISR pile-up (all interrupts fire back-to-back),
          * SD card write latency (can be 100–500 ms for FAT32),
          * Sensor timeout (I2C/SPI slave NACK + retry),
          * RTOS task preemption budget,
          * Manual specification from datasheet or measurement.
    source:
        Label describing the origin of the worst-case estimate.
        Suggested values:
          ``"ISR_pile_up"``     — interrupt storm analysis.
          ``"sd_write"``        — SD card max write latency.
          ``"sensor_timeout"``  — sensor bus retry budget.
          ``"manual_spec"``     — manually specified (worst-case guessed).
    """
    worst_case_ms: float
    source: str

    def __post_init__(self) -> None:
        if self.worst_case_ms <= 0:
            raise ValueError(
                f"WorstCaseLoopLatency '{self.source}': worst_case_ms must be > 0, "
                f"got {self.worst_case_ms}"
            )


@dataclass
class WatchdogIntervalReport:
    """Result of :func:`check_watchdog_interval`.

    Attributes
    ----------
    actual_timeout_ms:
        Actual computed watchdog timeout in milliseconds:
        ``prescaler × (reload_value + 1) / clock_hz × 1000``.
    headroom_ms:
        Absolute margin between the actual timeout and the worst-case loop
        latency: ``actual_timeout_ms − worst_case_ms``.
        Negative if the watchdog expires before the worst-case loop finishes.
    safety_margin_pct:
        Relative margin expressed as a percentage:
        ``(actual_timeout_ms / worst_case_ms − 1) × 100``.
        Values < 100 % mean the timeout is less than 2× worst-case (inadequate
        per the ARM Keil 2× rule).
    adequate:
        True iff ``actual_timeout_ms > 2 × worst_case_ms`` (ARM Keil AN259
        minimum). False if the watchdog may fire during a legitimate slow loop.
    recommended_reload:
        When ``adequate`` is False: the smallest integer reload value that
        achieves exactly 2.5× worst-case margin with the given clock and
        prescaler. ``None`` when already adequate.
    honest_caveat:
        Plain-text caveat describing what this check does NOT model.
    """
    actual_timeout_ms: float
    headroom_ms: float
    safety_margin_pct: float
    adequate: bool
    recommended_reload: Optional[int]
    honest_caveat: str

    def as_dict(self) -> dict:
        return {
            "actual_timeout_ms": round(self.actual_timeout_ms, 6),
            "headroom_ms": round(self.headroom_ms, 6),
            "safety_margin_pct": round(self.safety_margin_pct, 3),
            "adequate": self.adequate,
            "recommended_reload": self.recommended_reload,
            "honest_caveat": self.honest_caveat,
        }


# ── Caveat constant ───────────────────────────────────────────────────────────

_HONEST_CAVEAT: str = (
    "Assumes ideal LSI/internal RC oscillator at exactly the nominal clock_hz. "
    "STM32F411 LSI accuracy: ±10–15% over temperature and process (RM0383 Table 54). "
    "ATmega328P WDT oscillator: ±10% (voltage) × ±10% (temperature). "
    "Real safety margin should subtract ≥10% from computed timeout to account for "
    "oscillator tolerance. The 2× adequate criterion (ARM Keil AN259) is a minimum "
    "design rule; safety-critical applications (ISO 26262, IEC 61508 SIL-2+) require "
    "a window watchdog or challenge-response scheme, not a simple timeout check. "
    "STM32 WWDG (window watchdog) upper-bound constraint is NOT modelled here. "
    "ATmega WDT reload_value is used for formula consistency; in hardware the ATmega "
    "WDT period is selected by WDTO fuse bits, not an arbitrary 10-bit reload register."
)


# ── Core computation ──────────────────────────────────────────────────────────

def check_watchdog_interval(
    config: WatchdogConfig,
    latency: WorstCaseLoopLatency,
) -> WatchdogIntervalReport:
    """Compute actual watchdog timeout and verify it covers the worst-case loop.

    Algorithm (RM0383 §17, ATmega328P §11)
    ---------------------------------------
    1. Timeout (seconds):

       ``timeout_s = prescaler × (reload_value + 1) / clock_hz``

    2. Adequacy criterion (ARM Keil AN259):

       ``adequate = timeout_ms > 2 × worst_case_ms``

    3. If inadequate, recommended reload for 2.5× margin:

       ``target_timeout_s = 2.5 × worst_case_ms / 1000``
       ``recommended_reload = ceil(target_timeout_s × clock_hz / prescaler) − 1``

    Parameters
    ----------
    config:
        Watchdog peripheral configuration (clock, prescaler, reload).
    latency:
        Application worst-case loop latency estimate.

    Returns
    -------
    WatchdogIntervalReport
        Full report with timeout, headroom, margin, adequacy, and optional
        recommended reload value.

    Examples
    --------
    STM32F411 IWDG — LSI=32 kHz, prescaler=64, reload=4095:

    >>> cfg = WatchdogConfig(
    ...     clock_hz=32_000,
    ...     prescaler=64,
    ...     reload_value=4095,
    ...     mcu_label="STM32F411 IWDG",
    ... )
    >>> lat = WorstCaseLoopLatency(worst_case_ms=5_000.0, source="manual_spec")
    >>> report = check_watchdog_interval(cfg, lat)
    >>> report.actual_timeout_ms  # 64*4096/32000*1000
    8192.0
    >>> report.adequate
    True

    References
    ----------
    STM32F411 RM0383 Rev 3 §17 — IWDG.
    ATmega328P Datasheet §11 — Watchdog Timer.
    ARM Keil AN259 — Using Watchdog Timers in Embedded Systems.
    """
    import math

    # ── Timeout (seconds) ────────────────────────────────────────────────────
    timeout_s = (config.prescaler * (config.reload_value + 1)) / config.clock_hz
    timeout_ms = timeout_s * 1000.0

    # ── Headroom and margin ───────────────────────────────────────────────────
    headroom_ms = timeout_ms - latency.worst_case_ms
    safety_margin_pct = (timeout_ms / latency.worst_case_ms - 1.0) * 100.0

    # ── Adequacy (ARM Keil 2× rule) ───────────────────────────────────────────
    adequate = timeout_ms > 2.0 * latency.worst_case_ms

    # ── Recommended reload if inadequate ─────────────────────────────────────
    recommended_reload: Optional[int] = None
    if not adequate:
        # Target: exactly 2.5× worst-case
        target_s = 2.5 * latency.worst_case_ms / 1000.0
        # prescaler × (reload + 1) / clock_hz = target_s
        # → reload + 1 = ceil(target_s × clock_hz / prescaler)
        # → reload = ceil(...) - 1
        raw_counter = target_s * config.clock_hz / config.prescaler
        recommended_reload = math.ceil(raw_counter) - 1

    return WatchdogIntervalReport(
        actual_timeout_ms=timeout_ms,
        headroom_ms=headroom_ms,
        safety_margin_pct=safety_margin_pct,
        adequate=adequate,
        recommended_reload=recommended_reload,
        honest_caveat=_HONEST_CAVEAT,
    )
