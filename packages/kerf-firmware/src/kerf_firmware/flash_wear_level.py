"""Flash wear-level endurance estimator.

Estimates flash memory endurance and time-to-failure for a given MCU flash
sector layout, write workload, and EEPROM-like wear-leveling configuration.

Model
-----
  seconds_per_year  = 365.25 * 24 * 3600 = 31,557,600
  total_writes      = writes_per_second × seconds_per_year × expected_lifetime_years
  cycles_per_sector = total_writes / num_sectors_for_wear_level
  adequate          = cycles_per_sector ≤ endurance_cycles

Wear-leveling assumption
------------------------
This model assumes *perfect round-robin wear leveling*: every erase operation is
distributed uniformly across all N sectors.  Real firmware wear-leveling
algorithms (e.g. NuttX MTD, Zephyr NVS, custom EEPROM emulation) typically
achieve 80–90% of the theoretical ideal due to remapping tables, bad-block
overhead, and hot-sector skew.  Divide ``time_to_failure_years`` by 0.85 (or
the algorithm's measured efficiency) for a conservative real-world estimate.

References
----------
  STM32F411 RM0383 Rev 4 §3 (Embedded Flash Memory):
    - Dual-bank / sector-erase architecture; 10,000 erase cycles per sector
      at Tj = −40 to +85 °C (see Table 6, note 3).
    - Sector sizes: 16 KB × 4, 64 KB × 1, 128 KB × 3 for STM32F411CEU6 (512 KB).
  AVR ATmega328P §11 (EEPROM):
    - 100,000 erase/write cycles at 5 V, 25 °C (Table 29-11, Absolute Maximum Ratings
      note: endurance halved at Tj = 85 °C per §29.6).
  JEDEC JESD47 §9 — Flash memory endurance test standard.
  Micron AN-1015 — NAND Flash Wear-Leveling.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Seconds in one Julian year (365.25 × 24 × 3600).
_SECONDS_PER_YEAR: float = 365.25 * 24.0 * 3600.0


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class FlashSpec:
    """Description of one MCU flash bank / EEPROM under wear-level analysis.

    Attributes
    ----------
    mcu_label:
        Human-readable MCU identifier, e.g. ``"STM32F411CEU6"`` or
        ``"ATmega328P"``.
    sector_size_bytes:
        Size of one erasable sector or page in bytes.  For EEPROM this is
        the byte-addressable word size (1 byte per address for ATmega).
    endurance_cycles:
        Manufacturer-specified erase/write cycle endurance per sector.
        STM32F411 internal Flash: 10,000 (RM0383 §3 Table 6).
        ATmega328P EEPROM: 100,000 (datasheet §11).
    num_sectors_for_wear_level:
        Number of sectors used by the wear-leveling pool.  Setting this to 1
        means no wear leveling — all writes hit the same sector.  For
        EEPROM emulation on STM32 this is typically 2–N sectors cycling;
        for NVS/EEPROM emulation this should match the pool size.
    """
    mcu_label: str
    sector_size_bytes: int
    endurance_cycles: int
    num_sectors_for_wear_level: int

    def __post_init__(self) -> None:
        if self.sector_size_bytes <= 0:
            raise ValueError(
                f"FlashSpec '{self.mcu_label}': sector_size_bytes must be > 0, "
                f"got {self.sector_size_bytes}"
            )
        if self.endurance_cycles <= 0:
            raise ValueError(
                f"FlashSpec '{self.mcu_label}': endurance_cycles must be > 0, "
                f"got {self.endurance_cycles}"
            )
        if self.num_sectors_for_wear_level < 1:
            raise ValueError(
                f"FlashSpec '{self.mcu_label}': num_sectors_for_wear_level must be ≥ 1, "
                f"got {self.num_sectors_for_wear_level}"
            )


@dataclass
class WriteWorkload:
    """Description of the flash write workload.

    Attributes
    ----------
    bytes_per_write:
        Bytes written (or erased) per logical write operation.  For sector-
        erase flash this is typically the full sector size; for byte-
        addressable EEPROM it is the number of bytes updated per operation.
    writes_per_second:
        Average write operations per second (must be ≥ 0).  A value of 0.01
        means one write every 100 seconds; 1.0 means one per second.
    expected_lifetime_years:
        Target device lifetime in years over which wear is to be assessed.
        E.g. 10.0 for a decade-life industrial sensor.
    """
    bytes_per_write: int
    writes_per_second: float
    expected_lifetime_years: float

    def __post_init__(self) -> None:
        if self.bytes_per_write <= 0:
            raise ValueError(
                f"WriteWorkload: bytes_per_write must be > 0, got {self.bytes_per_write}"
            )
        if self.writes_per_second < 0.0:
            raise ValueError(
                f"WriteWorkload: writes_per_second must be ≥ 0, got {self.writes_per_second}"
            )
        if self.expected_lifetime_years <= 0.0:
            raise ValueError(
                f"WriteWorkload: expected_lifetime_years must be > 0, "
                f"got {self.expected_lifetime_years}"
            )


@dataclass
class FlashWearReport:
    """Result of :func:`compute_flash_wear`.

    Attributes
    ----------
    expected_cycles_per_sector:
        Projected erase/write cycles on each sector over the lifetime,
        assuming perfect uniform wear distribution.
    time_to_failure_years:
        Time (years) until the first sector is expected to reach its rated
        endurance limit under the given workload and wear-leveling factor.
        Equal to ``endurance_cycles × num_sectors / writes_per_second /
        seconds_per_year``.
    adequate:
        True iff ``expected_cycles_per_sector ≤ endurance_cycles``.  This
        means the device is expected to survive the full target lifetime.
    recommended_wear_level_sectors:
        Minimum number of wear-leveling sectors required to bring
        ``cycles_per_sector`` to exactly ``endurance_cycles`` over the
        target lifetime.  ``ceil(total_writes / endurance_cycles)``.
        Returns 1 when the workload is already within a single sector's budget.
    write_amplification:
        Ratio of *sector-level erase events* to *logical write events*.
        For single-byte EEPROM writes that trigger a full sector erase: 1.0
        (each logical write = one sector erase cycle).  For streaming block
        writes where ``bytes_per_write ≥ sector_size_bytes`` the ratio is
        also 1.0 (one erase per sector fill).  This model uses
        ``max(1, ceil(sector_size_bytes / bytes_per_write))`` — i.e. it takes
        at least ``ceil(sector/write)`` logical writes to fill one sector
        and trigger one erase, but in the worst case each logical write
        is smaller than a sector so every logical write triggers one erase.

        **Important**: this is a simplified static model.  Real EEPROM-
        emulation firmware may choose to erase only when a sector is full
        (reducing WA) or may double-write for ECC (increasing WA).  Use the
        actual firmware strategy's WA factor for production sizing.
    honest_caveat:
        Plain-English caveat summarising key model limitations.
    """
    expected_cycles_per_sector: float
    time_to_failure_years: float
    adequate: bool
    recommended_wear_level_sectors: int
    write_amplification: float
    honest_caveat: str


# ── Core computation ──────────────────────────────────────────────────────────

def compute_flash_wear(
    spec: FlashSpec,
    workload: WriteWorkload,
) -> FlashWearReport:
    """Estimate flash endurance and time-to-failure for the given parameters.

    Algorithm
    ---------
    1. total_writes = writes_per_second × seconds_per_year × lifetime_years
    2. write_amplification = max(1, ceil(sector_size / bytes_per_write))
    3. sector_erase_events = total_writes × write_amplification
       (upper-bound: each logical write triggers a sector erase)
    4. cycles_per_sector = sector_erase_events / num_sectors_for_wear_level
    5. time_to_failure = endurance_cycles × num_sectors / writes_per_second
                         / seconds_per_year / write_amplification
    6. adequate = cycles_per_sector ≤ endurance_cycles
    7. recommended_sectors = ceil(sector_erase_events / endurance_cycles)

    Parameters
    ----------
    spec:
        :class:`FlashSpec` describing the MCU flash / EEPROM under analysis.
    workload:
        :class:`WriteWorkload` describing the write rate and target lifetime.

    Returns
    -------
    FlashWearReport
        Full endurance report with adequacy flag and recommendation.

    Examples
    --------
    STM32F411 (10k endurance), 1 sector (no leveling), 1 write/s, 10 yr:

    >>> spec = FlashSpec("STM32F411", 131072, 10_000, 1)
    >>> wl   = WriteWorkload(131072, 1.0, 10.0)
    >>> r    = compute_flash_wear(spec, wl)
    >>> r.adequate
    False
    >>> round(r.expected_cycles_per_sector, -4)
    315580000.0

    ATmega328P EEPROM (100k endurance), 1 sector, 0.01 write/s, 10 yr:

    >>> spec2 = FlashSpec("ATmega328P-EEPROM", 1, 100_000, 1)
    >>> wl2   = WriteWorkload(1, 0.01, 10.0)
    >>> r2    = compute_flash_wear(spec2, wl2)
    >>> r2.adequate
    True
    >>> r2.expected_cycles_per_sector < 4000
    True

    References
    ----------
    STM32F411 RM0383 Rev 4 §3 (10,000 erase cycle endurance per sector).
    ATmega328P §11 (100,000 erase/write cycle EEPROM endurance).
    JEDEC JESD47 §9 — Flash memory endurance test standard.
    """
    seconds_per_year = _SECONDS_PER_YEAR
    total_writes = (
        workload.writes_per_second
        * seconds_per_year
        * workload.expected_lifetime_years
    )

    # Write amplification: at minimum 1 erase per logical write (small writes
    # to byte-addressable EEPROM), or 1 erase per ceil(sector / bytes_per_write)
    # logical writes when writes are large relative to sector size.
    writes_per_sector_fill = max(
        1, math.ceil(spec.sector_size_bytes / workload.bytes_per_write)
    )
    # Each write_per_sector_fill logical writes = 1 sector erase.
    # Total sector erase events = ceil(total_writes / writes_per_sector_fill).
    sector_erase_events = math.ceil(total_writes / writes_per_sector_fill) if total_writes > 0 else 0.0
    write_amplification = float(writes_per_sector_fill)

    # Cycles per sector under uniform wear leveling.
    cycles_per_sector = sector_erase_events / spec.num_sectors_for_wear_level

    # Time until first sector hits endurance limit (exact analytic form).
    if workload.writes_per_second > 0:
        time_to_failure_years = (
            float(spec.endurance_cycles)
            * float(spec.num_sectors_for_wear_level)
            * float(writes_per_sector_fill)
            / workload.writes_per_second
            / seconds_per_year
        )
    else:
        # Zero write rate → flash never wears out.
        time_to_failure_years = float("inf")

    adequate = cycles_per_sector <= spec.endurance_cycles

    # Minimum sectors needed so cycles_per_sector == endurance_cycles.
    if sector_erase_events > 0 and spec.endurance_cycles > 0:
        recommended_sectors = max(
            1,
            math.ceil(sector_erase_events / spec.endurance_cycles),
        )
    else:
        recommended_sectors = 1

    caveat = (
        "HONEST CAVEATS: (1) Perfect uniform wear distribution assumed — "
        "real firmware algorithms (NuttX MTD, Zephyr NVS, ST EEPROM emulation AN2594) "
        "achieve ~80–90%% of ideal; divide time_to_failure_years by 0.85 for "
        "a conservative estimate. "
        "(2) STM32F411 RM0383 §3 Table 6: 10,000 cycles at Tj=−40 to +85°C; "
        "endurance halves at Tj=125°C. "
        "(3) ATmega328P §11: 100,000 cycles at 5 V, 25°C; datasheet §29.6 notes "
        "endurance degradation at elevated temperature. "
        "(4) Write amplification model is worst-case (every logical write triggers "
        "a sector erase); streaming / buffered writes achieve lower WA. "
        "(5) Bad-block growth, ECC overhead, and partial-page programming not modelled."
    )

    return FlashWearReport(
        expected_cycles_per_sector=cycles_per_sector,
        time_to_failure_years=time_to_failure_years,
        adequate=adequate,
        recommended_wear_level_sectors=recommended_sectors,
        write_amplification=write_amplification,
        honest_caveat=caveat,
    )
