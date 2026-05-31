"""Tests for kerf_firmware.i2c_clock_stretch_check + LLM tool
firmware_check_i2c_clock_stretch.

Coverage
--------
I01  STM32F411 master 400 kHz + SHT31 (50 µs/byte stretch) → effective clock
     degrades from 400 kHz; cumulative 8×50µs=400µs < 25ms → timeout_compliant
I02  Aggressive stretcher (10 ms/byte, 8 bytes) → cumulative 80 ms exceeds
     25 ms timeout → timeout_compliant=False
I03  No-stretch slaves: effective == nominal exactly, degradation == 0.0
I04  Empty slaves list: no degradation, effective == nominal, compliant=True
I05  Multiple slaves: worst-case slave drives the result
I06  supports_stretching=False slave ignored even with nonzero stretch value
I07  scl_low_timeout_ms=0.0 disables timeout check → always compliant=True
I08  Dataclass validation: nominal_clock_hz <= 0 raises ValueError
I09  Dataclass validation: scl_low_timeout_ms < 0 raises ValueError
I10  Dataclass validation: I2CSlaveSpec address out of 0x7F range raises ValueError
I11  Dataclass validation: max_stretch_per_byte_us < 0 raises ValueError
I12  Report as_dict() has all required keys
I13  honest_caveat mentions single-master assumption
I14  100 kHz Standard Mode master + 200 µs/byte stretch → effective ≈ 36 kHz
I15  LLM tool: valid round-trip (STM32 400 kHz + SHT31 50 µs) → JSON response
I16  LLM tool: invalid JSON bytes → BAD_ARGS
I17  LLM tool: missing master field → BAD_ARGS
I18  LLM tool: missing slaves field → BAD_ARGS
I19  LLM tool: master missing nominal_clock_hz → BAD_ARGS
I20  LLM tool: slave missing device_label → BAD_ARGS
I21  LLM tool: aggressive stretcher triggers timeout_compliant=False in tool
I22  LLM tool: async wrapper returns same result as sync handler
I23  throughput_degradation_pct formula verified
I24  bytes_per_transaction parameter affects timeout compliance
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_firmware.i2c_clock_stretch_check import (
    I2CMasterConfig,
    I2CSlaveSpec,
    I2CClockStretchReport,
    check_i2c_clock_stretch,
)
from kerf_firmware.tools.firmware_check_i2c_clock_stretch import (
    run_firmware_check_i2c_clock_stretch,
    run_firmware_check_i2c_clock_stretch_async,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _master(
    nominal_clock_hz: int = 400_000,
    scl_low_timeout_ms: float = 25.0,
    mcu_label: str = "TestMCU",
) -> I2CMasterConfig:
    return I2CMasterConfig(
        nominal_clock_hz=nominal_clock_hz,
        scl_low_timeout_ms=scl_low_timeout_ms,
        mcu_label=mcu_label,
    )


def _slave(
    device_label: str = "TestSlave",
    address: int = 0x44,
    max_stretch_per_byte_us: float = 0.0,
    supports_stretching: bool = False,
) -> I2CSlaveSpec:
    return I2CSlaveSpec(
        device_label=device_label,
        address=address,
        max_stretch_per_byte_us=max_stretch_per_byte_us,
        supports_stretching=supports_stretching,
    )


def _tool(args: dict) -> dict:
    raw = run_firmware_check_i2c_clock_stretch(args)
    return json.loads(raw)


def _make_tool_args(
    nominal_clock_hz: int = 400_000,
    scl_low_timeout_ms: float = 25.0,
    mcu_label: str = "STM32F411CE I2C1",
    slaves: list | None = None,
    bytes_per_transaction: int = 8,
) -> dict:
    if slaves is None:
        slaves = [
            {
                "device_label": "SHT31",
                "address": 0x44,
                "max_stretch_per_byte_us": 50.0,
                "supports_stretching": True,
            }
        ]
    return {
        "master": {
            "nominal_clock_hz": nominal_clock_hz,
            "scl_low_timeout_ms": scl_low_timeout_ms,
            "mcu_label": mcu_label,
        },
        "slaves": slaves,
        "bytes_per_transaction": bytes_per_transaction,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helper: expected effective clock (independent calculation)
# ─────────────────────────────────────────────────────────────────────────────

def _expected_effective_hz(nominal_hz: int, stretch_us: float) -> float:
    """Compute effective I²C clock per NXP UM10204 §3.1.9 formula."""
    t_nominal_s = 9.0 / nominal_hz
    t_effective_s = t_nominal_s + stretch_us / 1_000_000.0
    return 9.0 / t_effective_s


# ─────────────────────────────────────────────────────────────────────────────
# I01  STM32 400 kHz + SHT31 50 µs/byte
# ─────────────────────────────────────────────────────────────────────────────

class TestSHT31Stretch:
    """I01 — STM32F411 @ 400 kHz + SHT31 50 µs/byte stretch, 25 ms timeout."""

    def test_i01_effective_clock_degrades(self):
        """I01a: effective_clock_hz < nominal (400 kHz) due to stretch."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        s = _slave(
            device_label="SHT31",
            address=0x44,
            max_stretch_per_byte_us=50.0,
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s])
        expected_hz = _expected_effective_hz(400_000, 50.0)
        assert report.effective_clock_hz == pytest.approx(expected_hz, rel=1e-6)
        assert report.effective_clock_hz < 400_000

    def test_i01_timeout_compliant_25ms(self):
        """I01b: 8 × 50 µs = 400 µs cumulative < 25 000 µs → compliant."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        s = _slave(
            device_label="SHT31",
            address=0x44,
            max_stretch_per_byte_us=50.0,
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s], bytes_per_transaction=8)
        assert report.timeout_compliant is True
        assert report.worst_case_stretch_per_byte_us == pytest.approx(50.0)
        assert report.slowest_slave == "SHT31"

    def test_i01_effective_approx_value(self):
        """I01c: formula check — 9/(9/400000 + 50e-6) ≈ 124138 Hz."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        s = _slave(
            device_label="SHT31",
            address=0x44,
            max_stretch_per_byte_us=50.0,
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s])
        # Independent formula: 9 / (9/400000 + 50/1e6) ≈ 124138 Hz
        assert report.effective_clock_hz == pytest.approx(124_137.9, rel=1e-3)


# ─────────────────────────────────────────────────────────────────────────────
# I02  Aggressive stretcher violates timeout
# ─────────────────────────────────────────────────────────────────────────────

class TestAggressiveStretchTimeout:
    """I02 — 10 ms/byte × 8 bytes = 80 ms > 25 ms timeout → non-compliant."""

    def test_i02_timeout_violation(self):
        """I02: 10 ms/byte × 8 bytes cumulative = 80 ms > 25 ms → not compliant."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        s = _slave(
            device_label="SlowEEPROM",
            address=0x50,
            max_stretch_per_byte_us=10_000.0,  # 10 ms per byte
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s], bytes_per_transaction=8)
        # cumulative = 10_000 * 8 = 80_000 µs = 80 ms > 25 ms
        assert report.timeout_compliant is False
        assert report.worst_case_stretch_per_byte_us == pytest.approx(10_000.0)

    def test_i02_effective_clock_very_low(self):
        """I02b: 10 ms/byte stretch → effective clock well below nominal."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        s = _slave(
            device_label="SlowEEPROM",
            address=0x50,
            max_stretch_per_byte_us=10_000.0,
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s])
        # 9 / (22.5e-6 + 10e-3) ≈ 899 Hz
        assert report.effective_clock_hz < 1_000
        assert report.throughput_degradation_pct > 99.0


# ─────────────────────────────────────────────────────────────────────────────
# I03  No stretching slaves: effective == nominal
# ─────────────────────────────────────────────────────────────────────────────

class TestNoStretch:
    def test_i03_no_stretch_effective_equals_nominal(self):
        """I03: slave with supports_stretching=False → effective = nominal exactly."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        s = _slave(
            device_label="PCA9685",
            address=0x40,
            max_stretch_per_byte_us=0.0,
            supports_stretching=False,
        )
        report = check_i2c_clock_stretch(m, [s])
        assert report.effective_clock_hz == pytest.approx(400_000.0)
        assert report.worst_case_stretch_per_byte_us == pytest.approx(0.0)
        assert report.throughput_degradation_pct == pytest.approx(0.0)
        assert report.timeout_compliant is True

    def test_i03b_nonzero_stretch_but_stretching_false_ignored(self):
        """I06: supports_stretching=False slave with nonzero stretch → ignored."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        s = _slave(
            device_label="FakeSlave",
            address=0x20,
            max_stretch_per_byte_us=5_000.0,  # large value, but stretching disabled
            supports_stretching=False,
        )
        report = check_i2c_clock_stretch(m, [s])
        assert report.effective_clock_hz == pytest.approx(400_000.0)
        assert report.worst_case_stretch_per_byte_us == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# I04  Empty slaves list
# ─────────────────────────────────────────────────────────────────────────────

class TestEmptySlaves:
    def test_i04_empty_slaves_no_degradation(self):
        """I04: no slaves → effective = nominal, no degradation, compliant."""
        m = _master(nominal_clock_hz=100_000, scl_low_timeout_ms=10.0)
        report = check_i2c_clock_stretch(m, [])
        assert report.effective_clock_hz == pytest.approx(100_000.0)
        assert report.worst_case_stretch_per_byte_us == pytest.approx(0.0)
        assert report.throughput_degradation_pct == pytest.approx(0.0)
        assert report.timeout_compliant is True
        assert report.slowest_slave == ""


# ─────────────────────────────────────────────────────────────────────────────
# I05  Multiple slaves: worst-case drives result
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleSlaves:
    def test_i05_worst_case_slave_selected(self):
        """I05: three slaves; worst-case (200 µs) drives effective clock."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=100.0)
        s1 = _slave("SHT31", 0x44, max_stretch_per_byte_us=50.0, supports_stretching=True)
        s2 = _slave("BNO055", 0x28, max_stretch_per_byte_us=200.0, supports_stretching=True)
        s3 = _slave("PCA9685", 0x40, max_stretch_per_byte_us=10.0, supports_stretching=True)
        report = check_i2c_clock_stretch(m, [s1, s2, s3])
        assert report.worst_case_stretch_per_byte_us == pytest.approx(200.0)
        assert report.slowest_slave == "BNO055"
        expected_hz = _expected_effective_hz(400_000, 200.0)
        assert report.effective_clock_hz == pytest.approx(expected_hz, rel=1e-6)

    def test_i05b_mix_of_stretching_and_non_stretching(self):
        """I05b: mix — only stretching slaves contribute to worst-case."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=100.0)
        s1 = _slave("FastSlave", 0x10, max_stretch_per_byte_us=0.0, supports_stretching=False)
        s2 = _slave("SlowSlave", 0x20, max_stretch_per_byte_us=75.0, supports_stretching=True)
        report = check_i2c_clock_stretch(m, [s1, s2])
        assert report.worst_case_stretch_per_byte_us == pytest.approx(75.0)
        assert report.slowest_slave == "SlowSlave"


# ─────────────────────────────────────────────────────────────────────────────
# I07  Timeout disabled (scl_low_timeout_ms=0.0)
# ─────────────────────────────────────────────────────────────────────────────

class TestTimeoutDisabled:
    def test_i07_zero_timeout_always_compliant(self):
        """I07: scl_low_timeout_ms=0.0 → timeout checking disabled → True."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=0.0)
        s = _slave(
            device_label="AggressiveSlave",
            address=0x30,
            max_stretch_per_byte_us=100_000.0,  # 100 ms/byte — extreme
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s], bytes_per_transaction=100)
        assert report.timeout_compliant is True


# ─────────────────────────────────────────────────────────────────────────────
# I08–I11  Dataclass validation
# ─────────────────────────────────────────────────────────────────────────────

class TestDataclassValidation:
    def test_i08_master_zero_clock_raises(self):
        """I08: nominal_clock_hz=0 raises ValueError."""
        with pytest.raises(ValueError, match="nominal_clock_hz"):
            I2CMasterConfig(nominal_clock_hz=0, scl_low_timeout_ms=25.0, mcu_label="X")

    def test_i08b_master_negative_clock_raises(self):
        """I08b: nominal_clock_hz<0 raises ValueError."""
        with pytest.raises(ValueError, match="nominal_clock_hz"):
            I2CMasterConfig(nominal_clock_hz=-1, scl_low_timeout_ms=25.0, mcu_label="X")

    def test_i09_master_negative_timeout_raises(self):
        """I09: scl_low_timeout_ms < 0 raises ValueError."""
        with pytest.raises(ValueError, match="scl_low_timeout_ms"):
            I2CMasterConfig(nominal_clock_hz=400_000, scl_low_timeout_ms=-1.0, mcu_label="X")

    def test_i10_slave_address_out_of_range_raises(self):
        """I10: address > 0x7F raises ValueError."""
        with pytest.raises(ValueError, match="address"):
            I2CSlaveSpec(
                device_label="X", address=0x80,
                max_stretch_per_byte_us=0.0, supports_stretching=False,
            )

    def test_i11_slave_negative_stretch_raises(self):
        """I11: max_stretch_per_byte_us < 0 raises ValueError."""
        with pytest.raises(ValueError, match="max_stretch_per_byte_us"):
            I2CSlaveSpec(
                device_label="X", address=0x44,
                max_stretch_per_byte_us=-1.0, supports_stretching=False,
            )


# ─────────────────────────────────────────────────────────────────────────────
# I12–I13  Report shape and caveat content
# ─────────────────────────────────────────────────────────────────────────────

class TestReportShape:
    def test_i12_as_dict_has_required_keys(self):
        """I12: as_dict() contains all required keys."""
        m = _master()
        s = _slave(supports_stretching=True, max_stretch_per_byte_us=50.0)
        report = check_i2c_clock_stretch(m, [s])
        d = report.as_dict()
        for key in (
            "effective_clock_hz",
            "worst_case_stretch_per_byte_us",
            "timeout_compliant",
            "slowest_slave",
            "throughput_degradation_pct",
            "honest_caveat",
        ):
            assert key in d, f"Missing key: {key}"

    def test_i13_caveat_mentions_single_master(self):
        """I13: honest_caveat mentions single-master assumption."""
        m = _master()
        report = check_i2c_clock_stretch(m, [])
        assert "single-master" in report.honest_caveat.lower()


# ─────────────────────────────────────────────────────────────────────────────
# I14  100 kHz Standard Mode + 200 µs/byte stretch
# ─────────────────────────────────────────────────────────────────────────────

class TestStandardMode:
    def test_i14_100khz_200us_stretch(self):
        """I14: 100 kHz Standard Mode + 200 µs/byte → effective ≈ 36 kHz."""
        m = _master(nominal_clock_hz=100_000, scl_low_timeout_ms=50.0)
        s = _slave(
            device_label="SlowSensor",
            address=0x60,
            max_stretch_per_byte_us=200.0,
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s])
        # 9 / (9/100000 + 200e-6) = 9 / (90e-6 + 200e-6) = 9/290e-6 ≈ 31034 Hz
        expected_hz = _expected_effective_hz(100_000, 200.0)
        assert report.effective_clock_hz == pytest.approx(expected_hz, rel=1e-6)
        assert report.effective_clock_hz < 100_000
        assert report.throughput_degradation_pct > 0.0

    def test_i14b_timeout_compliance_check(self):
        """I14b: 100 kHz + 200 µs × 8 = 1600 µs < 50 ms → compliant."""
        m = _master(nominal_clock_hz=100_000, scl_low_timeout_ms=50.0)
        s = _slave(
            device_label="SlowSensor",
            address=0x60,
            max_stretch_per_byte_us=200.0,
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s], bytes_per_transaction=8)
        # 200 * 8 = 1600 µs < 50_000 µs
        assert report.timeout_compliant is True


# ─────────────────────────────────────────────────────────────────────────────
# I23  throughput_degradation_pct formula
# ─────────────────────────────────────────────────────────────────────────────

class TestThroughputDegradation:
    def test_i23_degradation_formula(self):
        """I23: throughput_degradation = (1 - f_eff/f_nom) * 100."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        s = _slave(
            device_label="SHT31",
            address=0x44,
            max_stretch_per_byte_us=50.0,
            supports_stretching=True,
        )
        report = check_i2c_clock_stretch(m, [s])
        expected_deg = (1.0 - report.effective_clock_hz / 400_000) * 100.0
        assert report.throughput_degradation_pct == pytest.approx(expected_deg, rel=1e-6)

    def test_i23b_no_stretch_zero_degradation(self):
        """I23b: no stretch → throughput_degradation_pct == 0.0."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=25.0)
        report = check_i2c_clock_stretch(m, [])
        assert report.throughput_degradation_pct == pytest.approx(0.0, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# I24  bytes_per_transaction parameter
# ─────────────────────────────────────────────────────────────────────────────

class TestBytesPerTransaction:
    def test_i24_larger_transaction_can_violate_timeout(self):
        """I24: small stretch OK for 1 byte but violates for 100 bytes."""
        m = _master(nominal_clock_hz=400_000, scl_low_timeout_ms=1.0)
        s = _slave(
            device_label="DeviceA",
            address=0x55,
            max_stretch_per_byte_us=20.0,
            supports_stretching=True,
        )
        # 1 byte: 20 µs < 1000 µs → compliant
        r1 = check_i2c_clock_stretch(m, [s], bytes_per_transaction=1)
        assert r1.timeout_compliant is True
        # 100 bytes: 20 * 100 = 2000 µs > 1000 µs → not compliant
        r100 = check_i2c_clock_stretch(m, [s], bytes_per_transaction=100)
        assert r100.timeout_compliant is False


# ─────────────────────────────────────────────────────────────────────────────
# I15–I22  LLM tool tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMTool:
    def test_i15_valid_round_trip(self):
        """I15: valid STM32 400 kHz + SHT31 50 µs → JSON with all keys."""
        result = _tool(_make_tool_args())
        assert "effective_clock_hz" in result
        assert "timeout_compliant" in result
        assert "slowest_slave" in result
        assert "throughput_degradation_pct" in result
        assert "honest_caveat" in result
        assert result["timeout_compliant"] is True
        assert result["effective_clock_hz"] < 400_000

    def test_i16_invalid_json_bytes_via_async(self):
        """I16: non-JSON bytes → BAD_ARGS via async wrapper."""
        result = json.loads(asyncio.run(
            run_firmware_check_i2c_clock_stretch_async(None, b"not json {{")
        ))
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_i17_missing_master_field(self):
        """I17: missing 'master' key → BAD_ARGS."""
        result = _tool({"slaves": []})
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_i18_missing_slaves_field(self):
        """I18: missing 'slaves' key → BAD_ARGS."""
        result = _tool({
            "master": {
                "nominal_clock_hz": 400_000,
                "scl_low_timeout_ms": 25.0,
                "mcu_label": "TestMCU",
            }
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_i19_master_missing_nominal_clock_hz(self):
        """I19: master missing nominal_clock_hz → BAD_ARGS."""
        args = _make_tool_args()
        del args["master"]["nominal_clock_hz"]
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_i20_slave_missing_device_label(self):
        """I20: slave missing device_label → BAD_ARGS."""
        args = _make_tool_args()
        del args["slaves"][0]["device_label"]
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_i21_aggressive_stretcher_tool_not_compliant(self):
        """I21: 10 ms/byte × 8 bytes = 80 ms > 25 ms → timeout_compliant=False in tool."""
        args = _make_tool_args(
            slaves=[{
                "device_label": "SlowEEPROM",
                "address": 0x50,
                "max_stretch_per_byte_us": 10_000.0,
                "supports_stretching": True,
            }],
            bytes_per_transaction=8,
        )
        result = _tool(args)
        assert result["timeout_compliant"] is False
        assert result["worst_case_stretch_per_byte_us"] == pytest.approx(10_000.0)

    def test_i22_async_wrapper_matches_sync(self):
        """I22: async wrapper returns same payload as sync handler."""
        args = _make_tool_args()
        sync_result = json.loads(run_firmware_check_i2c_clock_stretch(args))
        async_result = json.loads(asyncio.run(
            run_firmware_check_i2c_clock_stretch_async(None, json.dumps(args).encode())
        ))
        assert sync_result["effective_clock_hz"] == pytest.approx(
            async_result["effective_clock_hz"], rel=1e-6
        )
        assert sync_result["timeout_compliant"] == async_result["timeout_compliant"]

    def test_tool_empty_slaves_no_degradation(self):
        """Tool with empty slaves list → effective equals nominal, no degradation."""
        args = _make_tool_args(slaves=[])
        result = _tool(args)
        assert result["effective_clock_hz"] == pytest.approx(400_000.0, rel=1e-6)
        assert result["throughput_degradation_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_tool_master_invalid_clock_hz(self):
        """Tool with non-integer nominal_clock_hz → BAD_ARGS."""
        args = _make_tool_args()
        args["master"]["nominal_clock_hz"] = "fast"
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_tool_slave_not_dict(self):
        """Slave that is not a dict (e.g. a string) → BAD_ARGS."""
        args = _make_tool_args(slaves=["not_a_dict"])
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_tool_bytes_per_transaction_zero(self):
        """bytes_per_transaction=0 → BAD_ARGS."""
        args = _make_tool_args()
        args["bytes_per_transaction"] = 0
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_tool_multiple_slaves_worst_case(self):
        """Tool with multiple slaves picks worst-case in JSON response."""
        args = _make_tool_args(
            slaves=[
                {
                    "device_label": "SHT31",
                    "address": 0x44,
                    "max_stretch_per_byte_us": 50.0,
                    "supports_stretching": True,
                },
                {
                    "device_label": "BNO055",
                    "address": 0x28,
                    "max_stretch_per_byte_us": 200.0,
                    "supports_stretching": True,
                },
            ]
        )
        result = _tool(args)
        assert result["worst_case_stretch_per_byte_us"] == pytest.approx(200.0)
        assert result["slowest_slave"] == "BNO055"
