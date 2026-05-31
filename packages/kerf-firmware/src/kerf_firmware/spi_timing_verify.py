"""SPI master/slave timing compatibility verifier.

Checks whether an SPI master configuration is compatible with an SPI slave
device's datasheet timing requirements, according to the Motorola SPI bus
specification (the canonical CPOL/CPHA reference) and ARM Cortex-M Generic
User Guide §SPI Timing.

Clock mode (CPOL/CPHA)
----------------------
The Motorola SPI specification defines four modes by two bits:

  CPOL (Clock Polarity):
    0 — clock idles LOW.
    1 — clock idles HIGH.

  CPHA (Clock Phase):
    0 — data sampled on the LEADING (first) clock edge.
    1 — data sampled on the TRAILING (second) clock edge.

  Mode 0: CPOL=0, CPHA=0 — idle LOW, sample on rising edge.
  Mode 1: CPOL=0, CPHA=1 — idle LOW, sample on falling edge.
  Mode 2: CPOL=1, CPHA=0 — idle HIGH, sample on falling edge.
  Mode 3: CPOL=1, CPHA=1 — idle HIGH, sample on rising edge.

  The master's CPOL and CPHA registers MUST exactly match the slave device's
  required mode; no conversion is possible at the hardware level.

Setup and hold times
--------------------
Per the ARM Cortex-M Generic UG §SPI Timing and Motorola SPI bus specification:

  t_su (setup time):  The time that MOSI must be stable BEFORE the
                      sampling clock edge.  Master must present data at
                      least master.setup_ns ns before the edge;
                      slave requires at least slave.min_setup_ns ns.
                      Violation: master.setup_ns < slave.min_setup_ns.

  t_h  (hold time):   The time that MOSI must remain stable AFTER the
                      sampling clock edge.  Master holds data for at
                      least master.hold_ns ns after the edge;
                      slave requires at least slave.min_hold_ns ns.
                      Violation: master.hold_ns < slave.min_hold_ns.

Clock frequency
---------------
  The slave specifies a maximum SPI clock frequency (max_clk_hz).
  The master's configured clock (clock_hz) must not exceed this limit.
  Violation: master.clock_hz > slave.max_clk_hz.

HONEST CAVEATS
--------------
* This verifier assumes ideal square-wave clock signals.  PCB trace
  propagation delay, parasitic capacitance, crosstalk, and signal
  slew-rate degradation are NOT modelled.  In practice, at high
  SPI clock frequencies (> 10 MHz) trace length, load capacitance,
  and series termination resistors reduce effective setup/hold margins
  beyond what this static check captures.
* The setup_ns and hold_ns values used for the master should represent
  the DATA-VALID window of the specific MCU SPI peripheral as specified
  in the device datasheet (e.g. STM32F411 RM0383 §28.3 electrical
  characteristics), not the theoretical 1/(2 × clock_hz) window.
* Temperature, supply voltage, and PCB stackup affect actual timing.
  Always verify on the target hardware with a logic analyser.

References
----------
  Motorola SPI Bus Specification (Motorola, 1979 — canonical CPOL/CPHA).
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §SPI Timing.
  Microchip MCP3008 datasheet DS21295D §1.0 (AC electrical characteristics).
  STM32F411 Reference Manual (RM0383 Rev 3) §28.3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class SpiMasterConfig:
    """SPI master (MCU) configuration.

    Attributes
    ----------
    clock_hz:
        SPI clock frequency programmed into the MCU peripheral, in Hz.
        E.g. 1_000_000 for 1 MHz.
    cpol:
        Clock polarity (0 or 1).  See module docstring for semantics.
    cpha:
        Clock phase (0 or 1).  See module docstring for semantics.
    setup_ns:
        Data setup time the master guarantees before the sampling clock
        edge, in nanoseconds.  Taken from the MCU SPI peripheral AC
        electrical characteristics table.
    hold_ns:
        Data hold time the master guarantees after the sampling clock
        edge, in nanoseconds.  Taken from the MCU SPI peripheral AC
        electrical characteristics table.
    mcu_label:
        Human-readable MCU label, e.g. ``"STM32F411CE @ 1 MHz SPI1"``.
    """
    clock_hz: int
    cpol: int
    cpha: int
    setup_ns: float
    hold_ns: float
    mcu_label: str

    def __post_init__(self) -> None:
        if self.clock_hz <= 0:
            raise ValueError(
                f"SpiMasterConfig '{self.mcu_label}': clock_hz must be > 0, "
                f"got {self.clock_hz}"
            )
        if self.cpol not in (0, 1):
            raise ValueError(
                f"SpiMasterConfig '{self.mcu_label}': cpol must be 0 or 1, "
                f"got {self.cpol}"
            )
        if self.cpha not in (0, 1):
            raise ValueError(
                f"SpiMasterConfig '{self.mcu_label}': cpha must be 0 or 1, "
                f"got {self.cpha}"
            )
        if self.setup_ns < 0:
            raise ValueError(
                f"SpiMasterConfig '{self.mcu_label}': setup_ns must be >= 0, "
                f"got {self.setup_ns}"
            )
        if self.hold_ns < 0:
            raise ValueError(
                f"SpiMasterConfig '{self.mcu_label}': hold_ns must be >= 0, "
                f"got {self.hold_ns}"
            )


@dataclass
class SpiSlaveSpec:
    """SPI slave (peripheral device) timing requirements from its datasheet.

    Attributes
    ----------
    device_label:
        Human-readable device label, e.g. ``"MCP3008 ADC"``.
    max_clk_hz:
        Maximum SPI clock frequency accepted by the slave, in Hz.
        The master's clock_hz must not exceed this value.
    min_setup_ns:
        Minimum data setup time required by the slave, in nanoseconds.
        The master must guarantee at least this many ns of setup time.
    min_hold_ns:
        Minimum data hold time required by the slave, in nanoseconds.
        The master must guarantee at least this many ns of hold time.
    cpol_required:
        Required CPOL value (0 or 1) for this slave device.
    cpha_required:
        Required CPHA value (0 or 1) for this slave device.
    """
    device_label: str
    max_clk_hz: int
    min_setup_ns: float
    min_hold_ns: float
    cpol_required: int
    cpha_required: int

    def __post_init__(self) -> None:
        if self.max_clk_hz <= 0:
            raise ValueError(
                f"SpiSlaveSpec '{self.device_label}': max_clk_hz must be > 0, "
                f"got {self.max_clk_hz}"
            )
        if self.min_setup_ns < 0:
            raise ValueError(
                f"SpiSlaveSpec '{self.device_label}': min_setup_ns must be >= 0, "
                f"got {self.min_setup_ns}"
            )
        if self.min_hold_ns < 0:
            raise ValueError(
                f"SpiSlaveSpec '{self.device_label}': min_hold_ns must be >= 0, "
                f"got {self.min_hold_ns}"
            )
        if self.cpol_required not in (0, 1):
            raise ValueError(
                f"SpiSlaveSpec '{self.device_label}': cpol_required must be 0 or 1, "
                f"got {self.cpol_required}"
            )
        if self.cpha_required not in (0, 1):
            raise ValueError(
                f"SpiSlaveSpec '{self.device_label}': cpha_required must be 0 or 1, "
                f"got {self.cpha_required}"
            )


@dataclass
class SpiTimingReport:
    """Result of :func:`verify_spi_timing`.

    Attributes
    ----------
    compatible:
        True iff ALL timing checks pass (clock, setup, hold, CPOL, CPHA).
    violations:
        List of human-readable violation strings, empty when compatible=True.
    setup_margin_ns:
        master.setup_ns - slave.min_setup_ns.  Positive = margin.
        Negative = violation.
    hold_margin_ns:
        master.hold_ns - slave.min_hold_ns.  Positive = margin.
        Negative = violation.
    clock_margin_pct:
        (slave.max_clk_hz - master.clock_hz) / slave.max_clk_hz * 100.
        Positive = margin (master clock below slave maximum).
        Negative = violation (master clock exceeds slave maximum).
    honest_caveat:
        Plain-text engineering caveat about what this check does NOT cover.
    """
    compatible: bool
    violations: List[str]
    setup_margin_ns: float
    hold_margin_ns: float
    clock_margin_pct: float
    honest_caveat: str

    def as_dict(self) -> dict:
        return {
            "compatible": self.compatible,
            "violations": self.violations,
            "setup_margin_ns": round(self.setup_margin_ns, 3),
            "hold_margin_ns": round(self.hold_margin_ns, 3),
            "clock_margin_pct": round(self.clock_margin_pct, 3),
            "honest_caveat": self.honest_caveat,
        }


# ── Core verification ─────────────────────────────────────────────────────────

#: Caveat appended to every report — see module docstring for elaboration.
_HONEST_CAVEAT: str = (
    "Assumes ideal square-wave SPI clock signals. "
    "PCB trace propagation delay, parasitic capacitance, crosstalk, and "
    "signal slew-rate degradation are NOT modelled. "
    "At SPI clock frequencies above ~10 MHz, effective setup/hold margins "
    "on the PCB may be significantly smaller than reported here. "
    "Verify on target hardware with a logic analyser. "
    "The master setup_ns/hold_ns values must come from the MCU datasheet "
    "SPI AC electrical characteristics, not from 1/(2*clock_hz) theory."
)


def verify_spi_timing(
    master: SpiMasterConfig,
    slave: SpiSlaveSpec,
) -> SpiTimingReport:
    """Verify timing compatibility between an SPI master and a slave device.

    Checks performed (Motorola SPI spec + ARM Cortex-M Generic UG §SPI Timing):

    1. Clock frequency: master.clock_hz <= slave.max_clk_hz.
    2. Data setup time: master.setup_ns >= slave.min_setup_ns.
    3. Data hold time: master.hold_ns >= slave.min_hold_ns.
    4. CPOL match: master.cpol == slave.cpol_required.
    5. CPHA match: master.cpha == slave.cpha_required.

    Parameters
    ----------
    master:
        SPI master configuration (MCU SPI peripheral settings).
    slave:
        SPI slave timing requirements from the device datasheet.

    Returns
    -------
    SpiTimingReport
        Full compatibility report with margins and violation list.

    Examples
    --------
    Compatible configuration (slow master, lenient slave):

    >>> master = SpiMasterConfig(
    ...     clock_hz=500_000, cpol=0, cpha=0,
    ...     setup_ns=10.0, hold_ns=10.0, mcu_label="MCU @ 500 kHz"
    ... )
    >>> slave = SpiSlaveSpec(
    ...     device_label="MyADC", max_clk_hz=1_000_000,
    ...     min_setup_ns=5.0, min_hold_ns=5.0,
    ...     cpol_required=0, cpha_required=0
    ... )
    >>> report = verify_spi_timing(master, slave)
    >>> report.compatible
    True

    Clock too fast:

    >>> master2 = SpiMasterConfig(
    ...     clock_hz=2_000_000, cpol=0, cpha=0,
    ...     setup_ns=10.0, hold_ns=10.0, mcu_label="MCU @ 2 MHz"
    ... )
    >>> report2 = verify_spi_timing(master2, slave)
    >>> report2.compatible
    False

    References
    ----------
    Motorola SPI Bus Specification (canonical CPOL/CPHA definition).
    ARM Cortex-M Generic User Guide (ARM DUI 0553B) §SPI Timing.
    """
    violations: list[str] = []

    # ── 1. Clock frequency check ─────────────────────────────────────────────
    clock_margin_pct = (
        (slave.max_clk_hz - master.clock_hz) / slave.max_clk_hz * 100.0
    )
    if master.clock_hz > slave.max_clk_hz:
        violations.append(
            f"CLOCK_TOO_FAST: master clock {master.clock_hz:,} Hz exceeds slave "
            f"maximum {slave.max_clk_hz:,} Hz "
            f"(margin {clock_margin_pct:.1f}%); "
            f"reduce SCLK or select a faster-rated slave device."
        )

    # ── 2. Setup time check ──────────────────────────────────────────────────
    setup_margin_ns = master.setup_ns - slave.min_setup_ns
    if master.setup_ns < slave.min_setup_ns:
        violations.append(
            f"SETUP_VIOLATION: master setup time {master.setup_ns:.1f} ns is less than "
            f"slave minimum {slave.min_setup_ns:.1f} ns "
            f"(deficit {-setup_margin_ns:.1f} ns); "
            f"reduce SPI clock rate or use a slave with shorter setup requirement."
        )

    # ── 3. Hold time check ───────────────────────────────────────────────────
    hold_margin_ns = master.hold_ns - slave.min_hold_ns
    if master.hold_ns < slave.min_hold_ns:
        violations.append(
            f"HOLD_VIOLATION: master hold time {master.hold_ns:.1f} ns is less than "
            f"slave minimum {slave.min_hold_ns:.1f} ns "
            f"(deficit {-hold_margin_ns:.1f} ns); "
            f"reduce SPI clock rate or use a slave with shorter hold requirement."
        )

    # ── 4. CPOL match check ──────────────────────────────────────────────────
    if master.cpol != slave.cpol_required:
        violations.append(
            f"CPOL_MISMATCH: master CPOL={master.cpol} but slave requires "
            f"CPOL={slave.cpol_required}; "
            f"reconfigure the MCU SPI peripheral CPOL bit "
            f"(Motorola SPI spec: CPOL=0 idle-LOW, CPOL=1 idle-HIGH)."
        )

    # ── 5. CPHA match check ──────────────────────────────────────────────────
    if master.cpha != slave.cpha_required:
        violations.append(
            f"CPHA_MISMATCH: master CPHA={master.cpha} but slave requires "
            f"CPHA={slave.cpha_required}; "
            f"reconfigure the MCU SPI peripheral CPHA bit "
            f"(Motorola SPI spec: CPHA=0 sample-on-leading-edge, "
            f"CPHA=1 sample-on-trailing-edge)."
        )

    return SpiTimingReport(
        compatible=(len(violations) == 0),
        violations=violations,
        setup_margin_ns=setup_margin_ns,
        hold_margin_ns=hold_margin_ns,
        clock_margin_pct=clock_margin_pct,
        honest_caveat=_HONEST_CAVEAT,
    )
