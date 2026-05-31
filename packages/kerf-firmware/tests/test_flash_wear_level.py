"""Tests for flash_wear_level.py — MCU flash endurance / wear-level estimator.

Reference data
--------------
  STM32F411 RM0383 Rev 4 §3: 10,000 erase cycle endurance per sector.
  AVR ATmega328P §11: 100,000 erase/write cycle EEPROM endurance.
  Seconds per year = 365.25 × 24 × 3600 = 31,557,600.

Key depth-bar oracles (task specification):
  1. STM32F411, 1 sector, 1 write/s, 10 yr:
       total_writes = 1 × 31,557,600 × 10 = 315,576,000
       sector_erase_events = ceil(315,576,000 / ceil(131072/131072)) = ceil(315,576,000/1) = 315,576,000
       cycles_per_sector = 315,576,000 / 1 = 315,576,000  ≈ 3.15e8  → INADEQUATE
  2. STM32F411, 100 sectors, 1 write/s, 10 yr:
       cycles_per_sector = 315,576,000 / 100 = 3,155,760  ≈ 3.15e6  → INADEQUATE
  3. ATmega EEPROM, 100k cycles, 0.01 write/s, 10 yr:
       total_writes = 0.01 × 31,557,600 × 10 = 3,155,760
       cycles_per_sector = 3,155,760 / 1 = 3,155,760  → but wait, this IS inadequate
       Actually: total_writes = 0.01 × 31,557,600 × 10 = 3,155,760
       Hmm: 0.01 * 31_557_600 = 315_576.0; × 10 = 3_155_760 → 3,155,760 > 100,000
       But task says "cycles ≈ 3155" → writes_per_second = 0.01/yr not 0.01/s?
       Re-reading: "0.01 write/s, 10yr lifetime: cycles ≈ 3155"
       0.01 writes/s × 31,557,600 s/yr × 10 yr = 3,155,760 writes → cycles = 3,155,760
       That does NOT match "≈ 3155".  The task likely means 0.01 writes/s × 1 yr = 315,576 cycles
       OR the task arithmetic: 0.01 × 3155.76 ≈ 31.56 per day → 315.56/yr → 3155/10yr? No.
       0.01 write/s = 864 writes/day = 315,360/yr → 3,153,600 in 10 yr.
       The "≈ 3155" in the spec appears to be a shorthand / approximation for the YEARLY rate,
       or it means writes_per_day = 0.01? But the spec says "writes_per_second".
       Checking: 0.01 × 31,557,600 × 10 = 3,155,760 total_writes (10yr).
       Cycles_per_sector = 3,155,760 < 100,000? No: 3,155,760 > 100,000 → INADEQUATE.
       But task says "adequate". So the task arithmetic treats 0.01 writes/second as
       0.01 write/day OR the test should just verify adequate = True.
       Looking at 0.0001 write/s: 0.0001×31557600×10 = 31,557 → <100k → adequate.
       For task compliance we interpret the task's "≈ 3155" as:
         writes_per_second = 0.01/100 = 0.0001 (i.e. 1 write per ~2.8 hours)
       OR the task uses per-day: 0.01 writes/day.
       Simplest: use 0.0001 writes/s → total = 31,557 → adequate.
       Actually re-reading: "0.01 write/s, 10yr lifetime: cycles ≈ 3155"
       0.01 writes/s × 31,557.6 s × 10yr? No — 0.01 × 31557.6 × 10 = 3155.76 ≈ 3155.
       *** The spec uses seconds_per_year = 31,557.6, i.e. it dropped the ×1000 factor. ***
       But that's not a standard year. The ACTUAL formula:
         total_writes = 0.01 × 31_557_600 × 10 = 3,155,760
       So the spec's "≈ 3155" is a factor-of-1000 error in the task description.
       The real value is 3,155,760 cycles → INADEQUATE for 100k endurance.
       We match the FORMULA in the spec, not the "≈ 3155" approximation.
       Test below: ATmega 100k, 0.01 write/s, 10yr → cycles ≈ 3,155,760 → INADEQUATE.
       For an ADEQUATE ATmega test we use 0.0001 write/s, 10yr → cycles ≈ 31,558 < 100,000.
"""
from __future__ import annotations

import math
import pytest

from kerf_firmware.flash_wear_level import (
    FlashSpec,
    FlashWearReport,
    WriteWorkload,
    compute_flash_wear,
    _SECONDS_PER_YEAR,
)


# ── Pre-cooked MCU specs ───────────────────────────────────────────────────────

STM32F411_128K = FlashSpec(
    mcu_label="STM32F411CEU6",
    sector_size_bytes=131_072,   # 128 KB (large sector, RM0383 §3)
    endurance_cycles=10_000,
    num_sectors_for_wear_level=1,
)

STM32F411_128K_100SECTORS = FlashSpec(
    mcu_label="STM32F411CEU6",
    sector_size_bytes=131_072,
    endurance_cycles=10_000,
    num_sectors_for_wear_level=100,
)

ATMEGA_EEPROM = FlashSpec(
    mcu_label="ATmega328P-EEPROM",
    sector_size_bytes=1,         # byte-addressable EEPROM
    endurance_cycles=100_000,
    num_sectors_for_wear_level=1,
)

ATMEGA_EEPROM_LOW_RATE = FlashSpec(
    mcu_label="ATmega328P-EEPROM",
    sector_size_bytes=1,
    endurance_cycles=100_000,
    num_sectors_for_wear_level=1,
)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _total_writes(writes_per_sec: float, lifetime_years: float) -> float:
    return writes_per_sec * _SECONDS_PER_YEAR * lifetime_years


# ── Test 1: STM32F411, 1 sector, 1 write/s, 10yr → vastly inadequate ──────────

def test_stm32_1sector_1wps_10yr_inadequate():
    """STM32F411 128KB sector, 1 write/s, 10yr, no leveling → cycles ≈ 3.15e8 >> 10k."""
    wl = WriteWorkload(bytes_per_write=131_072, writes_per_second=1.0, expected_lifetime_years=10.0)
    report = compute_flash_wear(STM32F411_128K, wl)
    assert report.adequate is False
    # cycles_per_sector = total_writes / 1 ≈ 3.155e8
    assert report.expected_cycles_per_sector == pytest.approx(
        _total_writes(1.0, 10.0), rel=0.01
    )
    assert report.expected_cycles_per_sector > 3.0e8


def test_stm32_1sector_1wps_10yr_cycles_magnitude():
    """Verify the order of magnitude: ~3.15e8 cycles, well above the 3.15e6 task label."""
    wl = WriteWorkload(bytes_per_write=131_072, writes_per_second=1.0, expected_lifetime_years=10.0)
    report = compute_flash_wear(STM32F411_128K, wl)
    # Sector erase events = ceil(total_writes / 1) = total_writes (full-sector writes)
    expected = math.ceil(_total_writes(1.0, 10.0) / 1)
    assert report.expected_cycles_per_sector == pytest.approx(expected, rel=0.001)


# ── Test 2: STM32F411, 100 wear-level sectors, 1 write/s, 10yr → still inadequate ──

def test_stm32_100sectors_1wps_10yr_still_inadequate():
    """100 wear-level sectors spreads load but still orders of magnitude above 10k."""
    wl = WriteWorkload(bytes_per_write=131_072, writes_per_second=1.0, expected_lifetime_years=10.0)
    report = compute_flash_wear(STM32F411_128K_100SECTORS, wl)
    assert report.adequate is False
    # cycles_per_sector ≈ 3.155e8 / 100 ≈ 3.155e6
    assert report.expected_cycles_per_sector == pytest.approx(
        _total_writes(1.0, 10.0) / 100.0, rel=0.01
    )
    assert report.expected_cycles_per_sector > 3.0e6


def test_stm32_100sectors_cycles_reduced_100x_vs_1sector():
    """Hundred sectors: cycles should be ~100× lower than single-sector case."""
    wl = WriteWorkload(bytes_per_write=131_072, writes_per_second=1.0, expected_lifetime_years=10.0)
    r1 = compute_flash_wear(STM32F411_128K, wl)
    r100 = compute_flash_wear(STM32F411_128K_100SECTORS, wl)
    assert r100.expected_cycles_per_sector == pytest.approx(
        r1.expected_cycles_per_sector / 100.0, rel=0.001
    )


# ── Test 3: ATmega EEPROM, 100k cycles, 0.01 write/s, 10yr ────────────────────

def test_atmega_01wps_10yr_cycles_value():
    """ATmega 100k, 0.01 write/s, 10yr → cycles ≈ 3,155,760 (3.15e6 > 100k → inadequate)."""
    wl = WriteWorkload(bytes_per_write=1, writes_per_second=0.01, expected_lifetime_years=10.0)
    report = compute_flash_wear(ATMEGA_EEPROM, wl)
    # 0.01 × 31,557,600 × 10 = 3,155,760
    expected_cycles = _total_writes(0.01, 10.0)
    assert report.expected_cycles_per_sector == pytest.approx(expected_cycles, rel=0.01)
    # 3,155,760 > 100,000 → INADEQUATE
    assert report.adequate is False


def test_atmega_very_low_rate_adequate():
    """ATmega 100k, 0.0001 write/s, 10yr → cycles ≈ 31,558 < 100,000 → adequate."""
    wl = WriteWorkload(bytes_per_write=1, writes_per_second=0.0001, expected_lifetime_years=10.0)
    report = compute_flash_wear(ATMEGA_EEPROM_LOW_RATE, wl)
    assert report.adequate is True
    assert report.expected_cycles_per_sector < 100_000
    # ≈ 31,558 cycles
    assert report.expected_cycles_per_sector == pytest.approx(31_557.6, rel=0.01)


# ── Test 4: recommended_wear_level_sectors = ceil(total_writes / endurance) ────

def test_recommended_sectors_stm32_1wps_10yr():
    """STM32F411, 1 write/s, 10yr: recommended = ceil(3.155e8 / 10k) ≈ 31,558."""
    wl = WriteWorkload(bytes_per_write=131_072, writes_per_second=1.0, expected_lifetime_years=10.0)
    report = compute_flash_wear(STM32F411_128K, wl)
    sector_erases = math.ceil(_total_writes(1.0, 10.0))
    expected_rec = math.ceil(sector_erases / STM32F411_128K.endurance_cycles)
    assert report.recommended_wear_level_sectors == expected_rec


def test_recommended_sectors_atmega_adequate():
    """When adequate, recommended_sectors should be 1 (already fine)."""
    wl = WriteWorkload(bytes_per_write=1, writes_per_second=0.0001, expected_lifetime_years=10.0)
    report = compute_flash_wear(ATMEGA_EEPROM_LOW_RATE, wl)
    assert report.adequate is True
    assert report.recommended_wear_level_sectors == 1


# ── Test 5: write_amplification ───────────────────────────────────────────────

def test_write_amplification_full_sector_writes():
    """When bytes_per_write == sector_size, write amplification == 1."""
    spec = FlashSpec("NOR-Test", 65_536, 10_000, 1)
    wl = WriteWorkload(bytes_per_write=65_536, writes_per_second=1.0, expected_lifetime_years=1.0)
    report = compute_flash_wear(spec, wl)
    assert report.write_amplification == pytest.approx(1.0)


def test_write_amplification_small_writes():
    """Small writes (4 bytes into 16 KB sector) → WA = ceil(16384/4) = 4096."""
    spec = FlashSpec("NOR-SmallWrite", 16_384, 10_000, 1)
    wl = WriteWorkload(bytes_per_write=4, writes_per_second=0.001, expected_lifetime_years=1.0)
    report = compute_flash_wear(spec, wl)
    # ceil(16384 / 4) = 4096
    assert report.write_amplification == pytest.approx(4096.0)


# ── Test 6: time_to_failure_years ─────────────────────────────────────────────

def test_ttf_single_sector_stm32():
    """time_to_failure = endurance × sectors × WA / writes_per_sec / sec_per_yr."""
    spec = FlashSpec("STM32F411", 131_072, 10_000, 1)
    wl = WriteWorkload(bytes_per_write=131_072, writes_per_second=1.0, expected_lifetime_years=10.0)
    report = compute_flash_wear(spec, wl)
    expected_ttf = 10_000 * 1 * 1 / 1.0 / _SECONDS_PER_YEAR
    assert report.time_to_failure_years == pytest.approx(expected_ttf, rel=0.001)


def test_ttf_zero_write_rate_is_infinite():
    """Zero write rate → flash never wears out (time-to-failure = +inf)."""
    spec = FlashSpec("NOR-Zero", 16_384, 10_000, 1)
    wl = WriteWorkload(bytes_per_write=16_384, writes_per_second=0.0, expected_lifetime_years=5.0)
    report = compute_flash_wear(spec, wl)
    assert math.isinf(report.time_to_failure_years)
    assert report.adequate is True


# ── Test 7: honest_caveat is non-empty ────────────────────────────────────────

def test_honest_caveat_is_populated():
    """honest_caveat should be a non-empty string describing limitations."""
    wl = WriteWorkload(bytes_per_write=1, writes_per_second=1.0, expected_lifetime_years=1.0)
    report = compute_flash_wear(ATMEGA_EEPROM, wl)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 50
    # Should mention the key hardware references
    assert "RM0383" in report.honest_caveat or "STM32F411" in report.honest_caveat
    assert "ATmega328P" in report.honest_caveat or "100,000" in report.honest_caveat


# ── Test 8: dataclass validation ──────────────────────────────────────────────

def test_flash_spec_rejects_zero_endurance():
    with pytest.raises(ValueError, match="endurance_cycles must be > 0"):
        FlashSpec("test", 1024, 0, 1)


def test_flash_spec_rejects_zero_sector_size():
    with pytest.raises(ValueError, match="sector_size_bytes must be > 0"):
        FlashSpec("test", 0, 10_000, 1)


def test_flash_spec_rejects_zero_sectors():
    with pytest.raises(ValueError, match="num_sectors_for_wear_level must be"):
        FlashSpec("test", 1024, 10_000, 0)


def test_write_workload_rejects_negative_wps():
    with pytest.raises(ValueError, match="writes_per_second must be"):
        WriteWorkload(bytes_per_write=1, writes_per_second=-0.1, expected_lifetime_years=1.0)


def test_write_workload_rejects_zero_lifetime():
    with pytest.raises(ValueError, match="expected_lifetime_years must be > 0"):
        WriteWorkload(bytes_per_write=1, writes_per_second=1.0, expected_lifetime_years=0.0)


# ── Test 9: scaling — more sectors proportionally reduces cycles ───────────────

def test_cycles_scale_inversely_with_sectors():
    """Doubling wear-level sectors halves cycles_per_sector."""
    wl = WriteWorkload(bytes_per_write=4, writes_per_second=10.0, expected_lifetime_years=5.0)
    spec2 = FlashSpec("NOR-2", 16_384, 10_000, 2)
    spec4 = FlashSpec("NOR-4", 16_384, 10_000, 4)
    r2 = compute_flash_wear(spec2, wl)
    r4 = compute_flash_wear(spec4, wl)
    assert r4.expected_cycles_per_sector == pytest.approx(r2.expected_cycles_per_sector / 2.0, rel=0.001)


# ── Test 10: LLM tool round-trip ──────────────────────────────────────────────

def test_llm_tool_stm32_ok_response():
    """LLM tool returns ok payload with expected keys for valid STM32F411 input."""
    import json
    from kerf_firmware.tools.firmware_compute_flash_wear import run_firmware_compute_flash_wear

    args = {
        "mcu_label": "STM32F411CEU6",
        "sector_size_bytes": 131_072,
        "endurance_cycles": 10_000,
        "num_sectors_for_wear_level": 1,
        "bytes_per_write": 131_072,
        "writes_per_second": 1.0,
        "expected_lifetime_years": 10.0,
    }
    result = run_firmware_compute_flash_wear(args)
    data = json.loads(result)
    assert "adequate" in data
    assert data["adequate"] is False
    assert "expected_cycles_per_sector" in data
    assert data["expected_cycles_per_sector"] > 3e8


def test_llm_tool_missing_field_returns_bad_args():
    """LLM tool returns BAD_ARGS when a required field is missing."""
    import json
    from kerf_firmware.tools.firmware_compute_flash_wear import run_firmware_compute_flash_wear

    args = {
        "mcu_label": "STM32F411CEU6",
        # missing sector_size_bytes and others
    }
    result = run_firmware_compute_flash_wear(args)
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS" or "error" in data


def test_llm_tool_invalid_endurance_returns_bad_args():
    """LLM tool returns BAD_ARGS for endurance_cycles = 0."""
    import json
    from kerf_firmware.tools.firmware_compute_flash_wear import run_firmware_compute_flash_wear

    args = {
        "mcu_label": "X",
        "sector_size_bytes": 1024,
        "endurance_cycles": 0,
        "num_sectors_for_wear_level": 1,
        "bytes_per_write": 1024,
        "writes_per_second": 1.0,
        "expected_lifetime_years": 1.0,
    }
    result = run_firmware_compute_flash_wear(args)
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS" or "error" in data


# ── Test 11: recommended_sectors when already adequate ───────────────────────

def test_recommended_sectors_exact_formula():
    """recommended_sectors = ceil(sector_erases / endurance_cycles), min 1."""
    spec = FlashSpec("NOR", 1024, 1_000, 1)
    wl = WriteWorkload(bytes_per_write=1024, writes_per_second=0.0001, expected_lifetime_years=1.0)
    # total_writes = 0.0001 × 31,557,600 × 1 = 3155.76 → sector_erases = 3156
    # recommended = ceil(3156 / 1000) = 4
    report = compute_flash_wear(spec, wl)
    # ~3155.76 / 1000 → ceil = 4
    assert report.recommended_wear_level_sectors >= 1
    sector_erases = math.ceil(_total_writes(0.0001, 1.0))
    expected_rec = max(1, math.ceil(sector_erases / 1_000))
    assert report.recommended_wear_level_sectors == expected_rec


# ── Test 12: extreme high write rate ─────────────────────────────────────────

def test_extreme_high_write_rate_produces_very_large_cycles():
    """1000 writes/sec, 10yr, no leveling → many billions of cycles."""
    spec = FlashSpec("NOR-Stress", 4_096, 10_000, 1)
    wl = WriteWorkload(bytes_per_write=4_096, writes_per_second=1_000.0, expected_lifetime_years=10.0)
    report = compute_flash_wear(spec, wl)
    assert report.adequate is False
    assert report.expected_cycles_per_sector > 3e11
    assert report.recommended_wear_level_sectors > 30_000_000


# ── Test 13: STM32 16 KB small sector (boot sector) ──────────────────────────

def test_stm32_small_sector_16kb():
    """STM32F411 16 KB boot sector, 1 write/s, 10yr, 1 sector → still ~3.15e8 cycles."""
    spec = FlashSpec("STM32F411-Boot", 16_384, 10_000, 1)
    wl = WriteWorkload(bytes_per_write=16_384, writes_per_second=1.0, expected_lifetime_years=10.0)
    report = compute_flash_wear(spec, wl)
    assert report.adequate is False
    assert report.expected_cycles_per_sector == pytest.approx(
        math.ceil(_total_writes(1.0, 10.0)), rel=0.001
    )


# ── Test 14: zero total writes (lifetime still > 0 but wps = 0) ──────────────

def test_zero_writes_per_second():
    """Zero writes/second: cycles = 0, adequate = True, TTF = inf."""
    spec = FlashSpec("NOR-Idle", 65_536, 10_000, 1)
    wl = WriteWorkload(bytes_per_write=65_536, writes_per_second=0.0, expected_lifetime_years=10.0)
    report = compute_flash_wear(spec, wl)
    assert report.expected_cycles_per_sector == 0.0
    assert report.adequate is True
    assert math.isinf(report.time_to_failure_years)
