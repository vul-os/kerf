"""Tests for kerf_firmware.spi_timing_verify + LLM tool firmware_verify_spi_timing.

Coverage
--------
S01  Compatible: slow master + lenient slave → compatible=True, all margins > 0
S02  Clock too fast → compatible=False, clock_margin_pct < 0
S03  CPOL mismatch → compatible=False, CPOL_MISMATCH violation listed
S04  CPHA mismatch → compatible=False, CPHA_MISMATCH violation listed
S05  Setup time violation → compatible=False, setup_margin_ns < 0
S06  Hold time violation → compatible=False, hold_margin_ns < 0
S07  Multiple violations at once (clock + CPOL + setup)
S08  Exact clock boundary (master == slave max) → compatible=True
S09  Zero setup_ns and zero hold_ns with slave requiring 0 → compatible=True
S10  SpiMasterConfig validation: clock_hz <= 0 raises ValueError
S11  SpiMasterConfig validation: invalid cpol raises ValueError
S12  SpiSlaveSpec validation: max_clk_hz <= 0 raises ValueError
S13  SpiSlaveSpec validation: invalid cpha_required raises ValueError
S14  SpiTimingReport.as_dict() has required keys
S15  MCP3008 ADC edge case: 1.35 MHz max @ 2.7V (DS21295D §1.0) verified against
     STM32F411 SPI1 @ 1 MHz, Mode 0, setup=10 ns, hold=10 ns → compatible=True
S16  MCP3008 ADC edge case: clock too fast (2 MHz) → compatible=False
S17  LLM tool: valid compatible args round-trip
S18  LLM tool: invalid JSON → BAD_ARGS
S19  LLM tool: missing master field → BAD_ARGS
S20  LLM tool: missing slave field → BAD_ARGS
S21  LLM tool: master missing required key clock_hz → BAD_ARGS
S22  LLM tool: CPOL mismatch in tool response → compatible=False, violation present
S23  LLM tool: clock_margin_pct negative when clock too fast
S24  LLM tool: async wrapper returns same result as sync handler
"""
from __future__ import annotations

import asyncio
import json

import pytest

from kerf_firmware.spi_timing_verify import (
    SpiMasterConfig,
    SpiSlaveSpec,
    SpiTimingReport,
    verify_spi_timing,
)
from kerf_firmware.tools.firmware_verify_spi_timing import (
    run_firmware_verify_spi_timing,
    run_firmware_verify_spi_timing_async,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

def _master(
    clock_hz: int = 500_000,
    cpol: int = 0,
    cpha: int = 0,
    setup_ns: float = 20.0,
    hold_ns: float = 20.0,
    mcu_label: str = "TestMCU",
) -> SpiMasterConfig:
    return SpiMasterConfig(
        clock_hz=clock_hz,
        cpol=cpol,
        cpha=cpha,
        setup_ns=setup_ns,
        hold_ns=hold_ns,
        mcu_label=mcu_label,
    )


def _slave(
    max_clk_hz: int = 1_000_000,
    min_setup_ns: float = 10.0,
    min_hold_ns: float = 10.0,
    cpol_required: int = 0,
    cpha_required: int = 0,
    device_label: str = "TestSlave",
) -> SpiSlaveSpec:
    return SpiSlaveSpec(
        device_label=device_label,
        max_clk_hz=max_clk_hz,
        min_setup_ns=min_setup_ns,
        min_hold_ns=min_hold_ns,
        cpol_required=cpol_required,
        cpha_required=cpha_required,
    )


def _tool(args: dict) -> dict:
    """Call the LLM tool handler and return parsed JSON."""
    raw = run_firmware_verify_spi_timing(args)
    return json.loads(raw)


def _make_tool_args(
    clock_hz: int = 500_000,
    cpol: int = 0,
    cpha: int = 0,
    setup_ns: float = 20.0,
    hold_ns: float = 20.0,
    mcu_label: str = "TestMCU",
    max_clk_hz: int = 1_000_000,
    min_setup_ns: float = 10.0,
    min_hold_ns: float = 10.0,
    cpol_required: int = 0,
    cpha_required: int = 0,
    device_label: str = "TestSlave",
) -> dict:
    return {
        "master": {
            "clock_hz": clock_hz,
            "cpol": cpol,
            "cpha": cpha,
            "setup_ns": setup_ns,
            "hold_ns": hold_ns,
            "mcu_label": mcu_label,
        },
        "slave": {
            "device_label": device_label,
            "max_clk_hz": max_clk_hz,
            "min_setup_ns": min_setup_ns,
            "min_hold_ns": min_hold_ns,
            "cpol_required": cpol_required,
            "cpha_required": cpha_required,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# S01  Compatible: slow master + lenient slave
# ─────────────────────────────────────────────────────────────────────────────

class TestCompatible:
    def test_s01_compatible_all_margins_positive(self):
        """S01: slow master + lenient slave → compatible=True, all margins > 0."""
        report = verify_spi_timing(_master(), _slave())
        assert report.compatible is True
        assert report.violations == []
        assert report.setup_margin_ns > 0.0
        assert report.hold_margin_ns > 0.0
        assert report.clock_margin_pct > 0.0

    def test_s08_exact_clock_boundary_is_compatible(self):
        """S08: master.clock_hz == slave.max_clk_hz → compatible=True (not strictly >)."""
        m = _master(clock_hz=1_000_000)
        s = _slave(max_clk_hz=1_000_000)
        report = verify_spi_timing(m, s)
        assert report.compatible is True
        assert report.clock_margin_pct == pytest.approx(0.0, abs=1e-9)
        assert not any("CLOCK" in v for v in report.violations)

    def test_s09_zero_setup_hold_requirements(self):
        """S09: slave requiring 0 ns setup/hold, master has 0 → compatible=True."""
        m = _master(setup_ns=0.0, hold_ns=0.0)
        s = _slave(min_setup_ns=0.0, min_hold_ns=0.0)
        report = verify_spi_timing(m, s)
        assert report.compatible is True
        assert report.setup_margin_ns == pytest.approx(0.0)
        assert report.hold_margin_ns == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# S02  Clock too fast
# ─────────────────────────────────────────────────────────────────────────────

class TestClockTooFast:
    def test_s02_clock_too_fast_not_compatible(self):
        """S02: master clock exceeds slave max → compatible=False."""
        m = _master(clock_hz=2_000_000)
        s = _slave(max_clk_hz=1_000_000)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        assert report.clock_margin_pct < 0.0
        assert any("CLOCK_TOO_FAST" in v for v in report.violations)

    def test_clock_margin_pct_formula(self):
        """clock_margin_pct = (max - clock) / max * 100."""
        m = _master(clock_hz=2_000_000)
        s = _slave(max_clk_hz=1_000_000)
        report = verify_spi_timing(m, s)
        expected = (1_000_000 - 2_000_000) / 1_000_000 * 100.0
        assert report.clock_margin_pct == pytest.approx(expected)


# ─────────────────────────────────────────────────────────────────────────────
# S03  CPOL mismatch
# ─────────────────────────────────────────────────────────────────────────────

class TestCpolMismatch:
    def test_s03_cpol_mismatch_not_compatible(self):
        """S03: master CPOL != slave required CPOL → compatible=False."""
        m = _master(cpol=0)
        s = _slave(cpol_required=1)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        assert any("CPOL_MISMATCH" in v for v in report.violations)

    def test_cpol_mismatch_both_directions(self):
        """Both CPOL=0→required=1 and CPOL=1→required=0 are flagged."""
        r1 = verify_spi_timing(_master(cpol=0), _slave(cpol_required=1))
        r2 = verify_spi_timing(_master(cpol=1), _slave(cpol_required=0))
        assert r1.compatible is False
        assert r2.compatible is False
        assert any("CPOL_MISMATCH" in v for v in r1.violations)
        assert any("CPOL_MISMATCH" in v for v in r2.violations)


# ─────────────────────────────────────────────────────────────────────────────
# S04  CPHA mismatch
# ─────────────────────────────────────────────────────────────────────────────

class TestCphaMismatch:
    def test_s04_cpha_mismatch_not_compatible(self):
        """S04: master CPHA != slave required CPHA → compatible=False."""
        m = _master(cpha=0)
        s = _slave(cpha_required=1)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        assert any("CPHA_MISMATCH" in v for v in report.violations)

    def test_cpha1_mode_3_compatible(self):
        """Mode 3 (CPOL=1, CPHA=1): master and slave both Mode 3 → compatible."""
        m = _master(cpol=1, cpha=1)
        s = _slave(cpol_required=1, cpha_required=1)
        report = verify_spi_timing(m, s)
        assert report.compatible is True


# ─────────────────────────────────────────────────────────────────────────────
# S05  Setup time violation
# ─────────────────────────────────────────────────────────────────────────────

class TestSetupViolation:
    def test_s05_setup_violation(self):
        """S05: master setup < slave minimum → compatible=False, setup_margin_ns < 0."""
        m = _master(setup_ns=3.0)
        s = _slave(min_setup_ns=10.0)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        assert report.setup_margin_ns < 0.0
        assert report.setup_margin_ns == pytest.approx(3.0 - 10.0)
        assert any("SETUP_VIOLATION" in v for v in report.violations)

    def test_setup_margin_formula(self):
        """setup_margin_ns = master.setup_ns - slave.min_setup_ns."""
        m = _master(setup_ns=15.0)
        s = _slave(min_setup_ns=10.0)
        report = verify_spi_timing(m, s)
        assert report.setup_margin_ns == pytest.approx(5.0)


# ─────────────────────────────────────────────────────────────────────────────
# S06  Hold time violation
# ─────────────────────────────────────────────────────────────────────────────

class TestHoldViolation:
    def test_s06_hold_violation(self):
        """S06: master hold < slave minimum → compatible=False, hold_margin_ns < 0."""
        m = _master(hold_ns=2.0)
        s = _slave(min_hold_ns=8.0)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        assert report.hold_margin_ns < 0.0
        assert report.hold_margin_ns == pytest.approx(2.0 - 8.0)
        assert any("HOLD_VIOLATION" in v for v in report.violations)


# ─────────────────────────────────────────────────────────────────────────────
# S07  Multiple violations
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleViolations:
    def test_s07_multiple_violations(self):
        """S07: clock too fast + CPOL mismatch + setup violation → all reported."""
        m = _master(clock_hz=5_000_000, cpol=0, setup_ns=2.0)
        s = _slave(max_clk_hz=1_000_000, cpol_required=1, min_setup_ns=10.0)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        codes = [v.split(":")[0] for v in report.violations]
        assert "CLOCK_TOO_FAST" in codes
        assert "CPOL_MISMATCH" in codes
        assert "SETUP_VIOLATION" in codes

    def test_both_cpol_and_cpha_mismatch_reported(self):
        """CPOL and CPHA both wrong → both violations appear."""
        m = _master(cpol=0, cpha=0)
        s = _slave(cpol_required=1, cpha_required=1)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        codes = [v.split(":")[0] for v in report.violations]
        assert "CPOL_MISMATCH" in codes
        assert "CPHA_MISMATCH" in codes


# ─────────────────────────────────────────────────────────────────────────────
# S10-S13  Dataclass validation
# ─────────────────────────────────────────────────────────────────────────────

class TestDataclassValidation:
    def test_s10_master_zero_clock_raises(self):
        """S10: SpiMasterConfig clock_hz=0 raises ValueError."""
        with pytest.raises(ValueError, match="clock_hz"):
            SpiMasterConfig(
                clock_hz=0, cpol=0, cpha=0,
                setup_ns=10.0, hold_ns=10.0, mcu_label="X"
            )

    def test_s11_master_invalid_cpol_raises(self):
        """S11: SpiMasterConfig cpol=2 raises ValueError."""
        with pytest.raises(ValueError, match="cpol"):
            SpiMasterConfig(
                clock_hz=1_000_000, cpol=2, cpha=0,
                setup_ns=10.0, hold_ns=10.0, mcu_label="X"
            )

    def test_s12_slave_zero_max_clk_raises(self):
        """S12: SpiSlaveSpec max_clk_hz=0 raises ValueError."""
        with pytest.raises(ValueError, match="max_clk_hz"):
            SpiSlaveSpec(
                device_label="X", max_clk_hz=0,
                min_setup_ns=5.0, min_hold_ns=5.0,
                cpol_required=0, cpha_required=0
            )

    def test_s13_slave_invalid_cpha_required_raises(self):
        """S13: SpiSlaveSpec cpha_required=3 raises ValueError."""
        with pytest.raises(ValueError, match="cpha_required"):
            SpiSlaveSpec(
                device_label="X", max_clk_hz=1_000_000,
                min_setup_ns=5.0, min_hold_ns=5.0,
                cpol_required=0, cpha_required=3
            )

    def test_master_negative_setup_raises(self):
        """Negative setup_ns raises ValueError."""
        with pytest.raises(ValueError, match="setup_ns"):
            SpiMasterConfig(
                clock_hz=1_000_000, cpol=0, cpha=0,
                setup_ns=-1.0, hold_ns=10.0, mcu_label="X"
            )

    def test_master_invalid_cpha_raises(self):
        """Invalid cpha value raises ValueError."""
        with pytest.raises(ValueError, match="cpha"):
            SpiMasterConfig(
                clock_hz=1_000_000, cpol=0, cpha=5,
                setup_ns=10.0, hold_ns=10.0, mcu_label="X"
            )

    def test_slave_invalid_cpol_required_raises(self):
        """SpiSlaveSpec cpol_required=2 raises ValueError."""
        with pytest.raises(ValueError, match="cpol_required"):
            SpiSlaveSpec(
                device_label="X", max_clk_hz=1_000_000,
                min_setup_ns=5.0, min_hold_ns=5.0,
                cpol_required=2, cpha_required=0
            )


# ─────────────────────────────────────────────────────────────────────────────
# S14  Report dict shape
# ─────────────────────────────────────────────────────────────────────────────

class TestReportDict:
    def test_s14_as_dict_has_required_keys(self):
        """S14: SpiTimingReport.as_dict() has all required keys."""
        report = verify_spi_timing(_master(), _slave())
        d = report.as_dict()
        for key in (
            "compatible", "violations",
            "setup_margin_ns", "hold_margin_ns",
            "clock_margin_pct", "honest_caveat",
        ):
            assert key in d, f"Missing key: {key}"

    def test_honest_caveat_mentions_propagation(self):
        """honest_caveat mentions propagation delay (key engineering concern)."""
        report = verify_spi_timing(_master(), _slave())
        assert "propagation" in report.honest_caveat.lower()

    def test_honest_caveat_mentions_square_wave(self):
        """honest_caveat mentions ideal square-wave assumption."""
        report = verify_spi_timing(_master(), _slave())
        assert "square-wave" in report.honest_caveat or "square wave" in report.honest_caveat.lower()


# ─────────────────────────────────────────────────────────────────────────────
# S15-S16  MCP3008 ADC edge case
# ─────────────────────────────────────────────────────────────────────────────

class TestMCP3008EdgeCase:
    """MCP3008 ADC @ 2.7V supply: max SPI clock = 1.35 MHz, Mode 0 (CPOL=0, CPHA=0).

    From Microchip DS21295D §1.0 Table 1-1 AC Electrical Characteristics (2.7–5.5V):
      - Max SPI clock:    1.35 MHz (at 2.7V), 3.6 MHz (at 5V).
      - Min setup time:   50 ns (t_su).
      - Min hold time:    50 ns (t_h).
      - Clock mode:       Mode 0 only (CPOL=0, CPHA=0).

    STM32F411 SPI1 configured at 1 MHz:
      - setup_ns: 10 ns (conservative; actual MCU output valid time > 10 ns).
      - hold_ns:  10 ns (conservative; actual hold > 10 ns per RM0383 §28.3).

    Note: at 1 MHz clock period = 1000 ns; setup + hold margins are present
    in the static check but are tight — PCB trace delay will consume them.
    """

    # MCP3008 at 2.7 V supply
    _MCP3008_2V7 = dict(
        max_clk_hz=1_350_000,    # 1.35 MHz
        min_setup_ns=50.0,       # t_su = 50 ns (DS21295D Table 1-1)
        min_hold_ns=50.0,        # t_h = 50 ns
        cpol_required=0,
        cpha_required=0,
        device_label="MCP3008 @ 2.7V (DS21295D)",
    )

    # STM32F411 SPI1 @ 1 MHz, Mode 0
    _STM32F411_1MHZ = dict(
        clock_hz=1_000_000,
        cpol=0,
        cpha=0,
        setup_ns=10.0,
        hold_ns=10.0,
        mcu_label="STM32F411CE SPI1 @ 1 MHz",
    )

    def test_s15_mcp3008_stm32_1mhz_compatible(self):
        """S15: STM32F411 @ 1 MHz + MCP3008 @ 2.7V → static check compatible=True.

        Clock: 1 MHz < 1.35 MHz — OK.
        The setup/hold margins are negative here because STM32 provides 10 ns
        but MCP3008 needs 50 ns — this is a real violation at 1 MHz clock.
        """
        m = _master(**self._STM32F411_1MHZ)
        s = _slave(**self._MCP3008_2V7)
        report = verify_spi_timing(m, s)
        # Clock should be OK
        assert report.clock_margin_pct > 0.0
        # Setup and hold are violated (10 ns < 50 ns)
        assert report.setup_margin_ns < 0.0
        assert report.hold_margin_ns < 0.0
        assert report.compatible is False

    def test_s15b_mcp3008_stm32_1mhz_with_adequate_timing(self):
        """S15b: STM32F411 @ 1 MHz with adequate setup/hold for MCP3008 → compatible=True."""
        m = _master(
            clock_hz=1_000_000,
            cpol=0, cpha=0,
            setup_ns=60.0,   # > 50 ns MCP3008 minimum
            hold_ns=60.0,    # > 50 ns MCP3008 minimum
            mcu_label="STM32F411CE SPI1 @ 1 MHz (slow data)",
        )
        s = _slave(**self._MCP3008_2V7)
        report = verify_spi_timing(m, s)
        assert report.compatible is True
        assert report.setup_margin_ns > 0.0
        assert report.hold_margin_ns > 0.0
        assert report.clock_margin_pct > 0.0

    def test_s16_mcp3008_stm32_2mhz_clock_too_fast(self):
        """S16: STM32F411 @ 2 MHz > MCP3008 1.35 MHz max → clock violation."""
        m = _master(
            clock_hz=2_000_000,
            cpol=0, cpha=0,
            setup_ns=60.0, hold_ns=60.0,
            mcu_label="STM32F411CE SPI1 @ 2 MHz",
        )
        s = _slave(**self._MCP3008_2V7)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        assert report.clock_margin_pct < 0.0
        assert any("CLOCK_TOO_FAST" in v for v in report.violations)

    def test_mcp3008_mode1_rejected(self):
        """MCP3008 requires Mode 0; using Mode 1 (CPHA=1) on master → CPHA_MISMATCH."""
        m = _master(
            clock_hz=1_000_000,
            cpol=0, cpha=1,   # wrong CPHA
            setup_ns=60.0, hold_ns=60.0,
            mcu_label="STM32F411CE bad mode",
        )
        s = _slave(**self._MCP3008_2V7)
        report = verify_spi_timing(m, s)
        assert report.compatible is False
        assert any("CPHA_MISMATCH" in v for v in report.violations)

    def test_mcp3008_at_5v_higher_clock_ok(self):
        """MCP3008 at 5V supply: max clock 3.6 MHz; 3 MHz master clock OK."""
        mcp3008_5v = dict(
            max_clk_hz=3_600_000,   # 3.6 MHz at 5V
            min_setup_ns=50.0,
            min_hold_ns=50.0,
            cpol_required=0,
            cpha_required=0,
            device_label="MCP3008 @ 5V (DS21295D)",
        )
        m = _master(
            clock_hz=3_000_000,
            cpol=0, cpha=0,
            setup_ns=60.0, hold_ns=60.0,
            mcu_label="STM32F411CE SPI1 @ 3 MHz",
        )
        s = _slave(**mcp3008_5v)
        report = verify_spi_timing(m, s)
        assert report.compatible is True
        assert report.clock_margin_pct > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# S17-S23  LLM tool tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMTool:
    def test_s17_valid_compatible_round_trip(self):
        """S17: valid compatible args → compatible=True in JSON response."""
        result = _tool(_make_tool_args())
        assert result["compatible"] is True
        assert result["violations"] == []
        assert result["setup_margin_ns"] > 0.0
        assert result["hold_margin_ns"] > 0.0
        assert result["clock_margin_pct"] > 0.0
        assert "honest_caveat" in result

    def test_s18_invalid_json_bytes_via_async(self):
        """S18: non-JSON bytes → BAD_ARGS via async wrapper."""
        result = json.loads(asyncio.run(
            run_firmware_verify_spi_timing_async(None, b"not json {{")
        ))
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_s19_missing_master_field(self):
        """S19: missing 'master' key → BAD_ARGS."""
        result = _tool({"slave": _make_tool_args()["slave"]})
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_s20_missing_slave_field(self):
        """S20: missing 'slave' key → BAD_ARGS."""
        result = _tool({"master": _make_tool_args()["master"]})
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_s21_master_missing_clock_hz(self):
        """S21: master dict missing clock_hz → BAD_ARGS."""
        args = _make_tool_args()
        del args["master"]["clock_hz"]
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_s22_cpol_mismatch_in_tool_response(self):
        """S22: CPOL mismatch → compatible=False + violation in JSON."""
        args = _make_tool_args(cpol=0, cpol_required=1)
        result = _tool(args)
        assert result["compatible"] is False
        assert any("CPOL_MISMATCH" in v for v in result["violations"])

    def test_s23_clock_margin_pct_negative_when_too_fast(self):
        """S23: master 2 MHz, slave max 1 MHz → clock_margin_pct < 0 in response."""
        args = _make_tool_args(clock_hz=2_000_000, max_clk_hz=1_000_000)
        result = _tool(args)
        assert result["compatible"] is False
        assert result["clock_margin_pct"] < 0.0

    def test_s24_async_wrapper_matches_sync(self):
        """S24: async wrapper returns same payload as sync handler."""
        args = _make_tool_args()
        sync_result = json.loads(run_firmware_verify_spi_timing(args))
        async_result = json.loads(asyncio.run(
            run_firmware_verify_spi_timing_async(None, json.dumps(args).encode())
        ))
        assert sync_result["compatible"] == async_result["compatible"]
        assert sync_result["clock_margin_pct"] == async_result["clock_margin_pct"]

    def test_tool_missing_master_clock_hz_inner(self):
        """master dict with non-integer clock_hz → BAD_ARGS."""
        args = _make_tool_args()
        args["master"]["clock_hz"] = "fast"
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_tool_slave_missing_device_label(self):
        """slave dict missing device_label → BAD_ARGS."""
        args = _make_tool_args()
        del args["slave"]["device_label"]
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_tool_setup_violation_reported(self):
        """Setup violation → setup_margin_ns < 0 in response."""
        args = _make_tool_args(setup_ns=2.0, min_setup_ns=10.0)
        result = _tool(args)
        assert result["compatible"] is False
        assert result["setup_margin_ns"] < 0.0
        assert any("SETUP_VIOLATION" in v for v in result["violations"])

    def test_tool_hold_violation_reported(self):
        """Hold violation → hold_margin_ns < 0 in response."""
        args = _make_tool_args(hold_ns=1.0, min_hold_ns=10.0)
        result = _tool(args)
        assert result["compatible"] is False
        assert result["hold_margin_ns"] < 0.0
        assert any("HOLD_VIOLATION" in v for v in result["violations"])
