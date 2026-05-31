"""I2C clock-stretch worst-case effective speed analyser.

Computes the worst-case effective I²C bus speed when one or more slave devices
exercise SCL clock stretching, and verifies that the configured SCL low-timeout
does not violate the I²C-bus specification.

Clock stretching (NXP UM10204 §3.1.9)
--------------------------------------
A slave device that cannot keep up with the master's clock rate holds SCL LOW
after the master releases it.  The master must wait (poll) until SCL goes HIGH
before continuing.  Each byte transfer consists of 9 SCL pulses (8 data bits +
1 ACK/NACK bit).

Worst-case effective clock model
---------------------------------
For a single byte at nominal clock f_nom (Hz):

  t_byte_nominal = 9 / f_nom          seconds per byte (9 SCL pulses)

When the worst-case stretching slave inserts t_stretch microseconds of hold per
byte, the actual time per byte becomes:

  t_byte_effective = (9 / f_nom) + (t_stretch / 1e6)   seconds

The effective I²C clock frequency is:

  f_effective = 9 / t_byte_effective   Hz

This is derived from the ratio of SCL pulses to total elapsed time.

Timeout compliance (NXP UM10204 §3.1.9 + ARM Cortex-M I²C peripheral docs)
-----------------------------------------------------------------------------
Many MCU I²C peripherals implement an SCL low-timeout: if SCL is held LOW
for longer than t_timeout, the peripheral resets the bus and logs an error.

For a transaction of N bytes, the cumulative stretch time is:

  t_cumulative_us = worst_stretch_per_byte_us × N

This must be strictly less than the SCL low-timeout:

  timeout_compliant = t_cumulative_us < scl_low_timeout_ms × 1000

Note: the NXP UM10204 Rev 7 §3.1.9 does not mandate a maximum stretch
duration; it is implementation-defined.  ARM Cortex-M STM32 I²C peripheral
(RM0383 §26.6) provides a configurable TIMEOUTB register for cumulative SCL
low-timeout detection.  This check is conservative: individual byte stretch
times are accumulated linearly; real buses may reset after any single pulse
exceeds the threshold, not just the cumulative total.

HONEST CAVEATS
--------------
* Assumes synchronous single-master bus — multi-master arbitration is NOT
  modelled.  Clock stretching interactions between concurrent masters are
  undefined in this model.
* Assumes all slave devices stretch on every byte at their worst-case rate
  simultaneously, which is the conservative pessimistic bound.
* The effective-clock formula counts one master-driven clock cycle per bit plus
  the full stretch window; inter-byte bus-free time (t_BUF) and start/stop
  overhead are not included per byte.
* Rise/fall time derating for capacitive loads (NXP UM10204 §3.1) is not
  modelled.  At 400 kHz Fast Mode with C_bus > 100 pF, effective frequency
  further degrades.
* This check does NOT replace oscilloscope/logic-analyser verification on the
  target hardware.

References
----------
  NXP UM10204 Rev 7 (I²C-bus specification and user manual) §3.1.9 — Clock
    stretching.
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §I2C Timing.
  STM32F411 Reference Manual (RM0383 Rev 3) §26.6 — I2C TIMEOUTB register.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class I2CMasterConfig:
    """I²C master (MCU) configuration.

    Attributes
    ----------
    nominal_clock_hz:
        The I²C SCL clock frequency programmed into the MCU peripheral, in Hz.
        Standard Mode: 100_000; Fast Mode: 400_000; Fast-Mode Plus: 1_000_000.
    scl_low_timeout_ms:
        SCL low-timeout threshold in milliseconds.  If SCL is held LOW (by a
        stretching slave) for a cumulative time exceeding this value during a
        transaction, the peripheral flags a timeout error.
        Configured via the I²C peripheral TIMEOUTB register (RM0383 §26.6) or
        equivalent.  Set to 0.0 to disable timeout compliance checking.
    mcu_label:
        Human-readable MCU identifier, e.g. ``"STM32F411CE I2C1 @ 400 kHz"``.
    """
    nominal_clock_hz: int
    scl_low_timeout_ms: float
    mcu_label: str

    def __post_init__(self) -> None:
        if self.nominal_clock_hz <= 0:
            raise ValueError(
                f"I2CMasterConfig '{self.mcu_label}': nominal_clock_hz must be > 0, "
                f"got {self.nominal_clock_hz}"
            )
        if self.scl_low_timeout_ms < 0:
            raise ValueError(
                f"I2CMasterConfig '{self.mcu_label}': scl_low_timeout_ms must be >= 0, "
                f"got {self.scl_low_timeout_ms}"
            )


@dataclass
class I2CSlaveSpec:
    """I²C slave device specification.

    Attributes
    ----------
    device_label:
        Human-readable device identifier, e.g. ``"SHT31 humidity sensor"``.
    address:
        7-bit I²C slave address (0x00–0x7F).
    max_stretch_per_byte_us:
        Maximum clock-stretch duration the slave may assert per byte transfer,
        in microseconds.  From the device datasheet SCL low-extension timing
        parameter.  Set to 0.0 for devices that never stretch.
    supports_stretching:
        True if the slave can assert clock stretching (SCL held LOW after the
        master releases it).  False for slaves that are always ready.
    """
    device_label: str
    address: int
    max_stretch_per_byte_us: float
    supports_stretching: bool

    def __post_init__(self) -> None:
        if not (0x00 <= self.address <= 0x7F):
            raise ValueError(
                f"I2CSlaveSpec '{self.device_label}': address must be 0x00–0x7F, "
                f"got 0x{self.address:02X}"
            )
        if self.max_stretch_per_byte_us < 0:
            raise ValueError(
                f"I2CSlaveSpec '{self.device_label}': max_stretch_per_byte_us must be "
                f">= 0, got {self.max_stretch_per_byte_us}"
            )


@dataclass
class I2CClockStretchReport:
    """Result of :func:`check_i2c_clock_stretch`.

    Attributes
    ----------
    effective_clock_hz:
        Worst-case effective I²C clock frequency (Hz) after accounting for the
        maximum clock-stretch inserted by the slowest slave.
    worst_case_stretch_per_byte_us:
        Maximum stretch time per byte (µs) across all slaves.  Zero if no
        slave stretches.
    timeout_compliant:
        True iff the cumulative stretch across the transaction does not exceed
        the master's scl_low_timeout_ms.  Always True when scl_low_timeout_ms
        is 0.0 (timeout disabled).
    slowest_slave:
        Label of the slave device with the highest max_stretch_per_byte_us.
        Empty string when no slaves are provided or none stretch.
    throughput_degradation_pct:
        Percentage reduction in I²C throughput compared to the nominal clock:
        ``(1 - effective_clock_hz / nominal_clock_hz) * 100``.
        0.0 when there is no stretching.
    honest_caveat:
        Plain-text engineering caveat describing what this check does NOT model.
    """
    effective_clock_hz: float
    worst_case_stretch_per_byte_us: float
    timeout_compliant: bool
    slowest_slave: str
    throughput_degradation_pct: float
    honest_caveat: str

    def as_dict(self) -> dict:
        return {
            "effective_clock_hz": round(self.effective_clock_hz, 2),
            "worst_case_stretch_per_byte_us": round(self.worst_case_stretch_per_byte_us, 3),
            "timeout_compliant": self.timeout_compliant,
            "slowest_slave": self.slowest_slave,
            "throughput_degradation_pct": round(self.throughput_degradation_pct, 3),
            "honest_caveat": self.honest_caveat,
        }


# ── Caveat constant ───────────────────────────────────────────────────────────

_HONEST_CAVEAT: str = (
    "Assumes synchronous single-master I²C bus; multi-master arbitration is NOT "
    "modelled. Worst-case stretch is assumed on every byte simultaneously for "
    "all stretching slaves — this is conservative. Rise/fall time derating for "
    "high bus capacitance (NXP UM10204 §3.1) and inter-byte bus-free time "
    "(t_BUF) are not included. Start/stop condition overhead is ignored. "
    "Timeout compliance check accumulates stretch linearly across bytes — "
    "some MCU peripherals timeout on any single SCL-low pulse, not the "
    "cumulative total. Always verify with a logic analyser on target hardware."
)


# ── Core computation ──────────────────────────────────────────────────────────

def check_i2c_clock_stretch(
    master: I2CMasterConfig,
    slaves: List[I2CSlaveSpec],
    bytes_per_transaction: int = 8,
) -> I2CClockStretchReport:
    """Compute worst-case effective I²C bus speed with clock stretching.

    Algorithm (NXP UM10204 §3.1.9):

    1.  Nominal time per byte (9 SCL pulses — 8 data bits + 1 ACK/NACK):

        ``t_byte_nominal_s = 9 / nominal_clock_hz``

    2.  Worst-case stretch per byte = max(slave.max_stretch_per_byte_us)
        across all slaves (accounting for supports_stretching flag).

    3.  Effective time per byte:

        ``t_byte_effective_s = t_byte_nominal_s + worst_stretch_us / 1e6``

    4.  Effective clock:

        ``effective_clock_hz = 9 / t_byte_effective_s``

    5.  Timeout compliance:

        ``cumulative_stretch_us = worst_stretch_us * bytes_per_transaction``

        ``timeout_compliant = cumulative_stretch_us < scl_low_timeout_ms * 1000``

        When scl_low_timeout_ms == 0.0 the timeout is disabled; result is True.

    Parameters
    ----------
    master:
        I²C master configuration (MCU peripheral settings + timeout).
    slaves:
        List of I²C slave device specifications on this bus segment.
    bytes_per_transaction:
        Number of data bytes per transaction, used to compute cumulative
        stretch for timeout compliance.  Defaults to 8.

    Returns
    -------
    I2CClockStretchReport
        Full report with effective clock, degradation, compliance, and caveats.

    Examples
    --------
    STM32F411 I2C1 at 400 kHz with SHT31 stretching up to 50 µs per byte:

    >>> master = I2CMasterConfig(
    ...     nominal_clock_hz=400_000,
    ...     scl_low_timeout_ms=25.0,
    ...     mcu_label="STM32F411CE I2C1",
    ... )
    >>> slave = I2CSlaveSpec(
    ...     device_label="SHT31",
    ...     address=0x44,
    ...     max_stretch_per_byte_us=50.0,
    ...     supports_stretching=True,
    ... )
    >>> report = check_i2c_clock_stretch(master, [slave])
    >>> report.effective_clock_hz  # doctest: +ELLIPSIS
    2...

    References
    ----------
    NXP UM10204 Rev 7 §3.1.9 — Clock stretching.
    STM32F411 RM0383 Rev 3 §26.6 — I2C TIMEOUTB register.
    """
    nominal_hz = master.nominal_clock_hz

    # ── Nominal time per byte (seconds) ──────────────────────────────────────
    t_byte_nominal_s = 9.0 / nominal_hz

    # ── Find worst-case stretch ───────────────────────────────────────────────
    slowest_slave_label = ""
    worst_stretch_us = 0.0

    stretching_slaves = [
        s for s in slaves
        if s.supports_stretching and s.max_stretch_per_byte_us > 0.0
    ]

    if stretching_slaves:
        slowest = max(stretching_slaves, key=lambda s: s.max_stretch_per_byte_us)
        worst_stretch_us = slowest.max_stretch_per_byte_us
        slowest_slave_label = slowest.device_label
    elif slaves:
        # All slaves present but none stretch: pick first for label context
        slowest_slave_label = ""

    # ── Effective time per byte ───────────────────────────────────────────────
    t_byte_effective_s = t_byte_nominal_s + worst_stretch_us / 1_000_000.0

    # ── Effective clock frequency ─────────────────────────────────────────────
    effective_clock_hz = 9.0 / t_byte_effective_s

    # ── Throughput degradation ────────────────────────────────────────────────
    throughput_degradation_pct = (1.0 - effective_clock_hz / nominal_hz) * 100.0

    # ── Timeout compliance ────────────────────────────────────────────────────
    if master.scl_low_timeout_ms == 0.0:
        # Timeout disabled — compliance is vacuously true
        timeout_compliant = True
    else:
        cumulative_stretch_us = worst_stretch_us * bytes_per_transaction
        timeout_threshold_us = master.scl_low_timeout_ms * 1000.0
        timeout_compliant = cumulative_stretch_us < timeout_threshold_us

    return I2CClockStretchReport(
        effective_clock_hz=effective_clock_hz,
        worst_case_stretch_per_byte_us=worst_stretch_us,
        timeout_compliant=timeout_compliant,
        slowest_slave=slowest_slave_label,
        throughput_degradation_pct=throughput_degradation_pct,
        honest_caveat=_HONEST_CAVEAT,
    )
