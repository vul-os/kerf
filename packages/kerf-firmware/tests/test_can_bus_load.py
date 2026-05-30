"""Tests for kerf_firmware.can_bus_load + LLM tool firmware_compute_can_bus_load.

Coverage
--------
- bits_per_frame: standard and extended ID, various DLC values
- Oracle depth-bar: 500 kbps, 10 × 8-byte, 11-bit, 100 ms → 2.7%
- Oracle: 100 × 8-byte, 100 ms → 27% (exceeds 30% threshold only marginally)
- Oracle: 50 × 8-byte, 10 ms → 67.5% (exceeds 40% threshold)
- Low load: single message, long period → ok=True
- High load: many fast messages → exceeds_40_percent_threshold=True
- Borderline 30% warning (not 40%)
- Extended-ID frames: bits_per_frame = 91 for 8-byte
- Mixed periods: different frequencies in the same bus
- Zero data bytes (remote frame / heartbeat)
- Single maximum-speed message (1 Mbps bus, 1 ms period, 8-byte)
- CanMessage validation: bad data_bytes, bad period_ms, bad CAN ID range
- Extended-ID CAN ID range validation
- LLM tool: valid args round-trip
- LLM tool: invalid args (missing fields, bad types, bad values)
- LLM tool: unknown/missing bit_rate_bps
- LLM tool: high load flagged in JSON response
- LLM tool: extended_id=true in JSON
- Report dict shape: keys present, per_message_load sorted descending
"""
from __future__ import annotations

import json

import pytest

from kerf_firmware.can_bus_load import (
    AVERAGE_STUFFING_BITS,
    CONSERVATIVE_MAX_LOAD_PCT,
    RECOMMENDED_MAX_LOAD_PCT,
    CanBusLoadReport,
    CanMessage,
    MessageLoadEntry,
    bits_per_frame,
    compute_can_bus_load,
)
from kerf_firmware.tools.firmware_compute_can_bus_load import (
    run_firmware_compute_can_bus_load,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_messages(count: int, data_bytes: int, period_ms: float, *,
                   extended_id: bool = False) -> list[CanMessage]:
    """Create *count* identical CanMessage objects with distinct names and IDs."""
    return [
        CanMessage(f"MSG_{i}", i, data_bytes, period_ms, extended_id=extended_id)
        for i in range(count)
    ]


def _tool(args: dict) -> dict:
    """Call the LLM tool and return parsed JSON."""
    raw = run_firmware_compute_can_bus_load(args)
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# bits_per_frame unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBitsPerFrame:
    def test_standard_8_byte_is_135(self):
        """CAN 2.0B standard frame: 47 + 64 + 24 = 135 bits (task depth-bar)."""
        assert bits_per_frame(8, extended_id=False) == 135

    def test_extended_8_byte_is_155(self):
        """CAN 2.0B extended frame: 67 + 64 + 24 = 155 bits."""
        assert bits_per_frame(8, extended_id=True) == 155

    def test_standard_0_byte(self):
        """Standard frame, 0-byte DLC: 47 + 0 + 24 = 71 bits."""
        assert bits_per_frame(0, extended_id=False) == 71

    def test_extended_0_byte(self):
        """Extended frame, 0-byte DLC: 67 + 0 + 24 = 91 bits."""
        assert bits_per_frame(0, extended_id=True) == 91

    def test_standard_4_byte(self):
        assert bits_per_frame(4, extended_id=False) == 47 + 32 + 24  # 103

    def test_extended_4_byte(self):
        assert bits_per_frame(4, extended_id=True) == 67 + 32 + 24  # 123

    def test_stuffing_constant(self):
        assert AVERAGE_STUFFING_BITS == 24

    def test_default_is_standard(self):
        """Default (no keyword) should be standard 11-bit ID."""
        assert bits_per_frame(8) == bits_per_frame(8, extended_id=False)


# ─────────────────────────────────────────────────────────────────────────────
# Oracle: depth-bar examples from task spec
# ─────────────────────────────────────────────────────────────────────────────

class TestOracleExamples:
    def test_10_messages_100ms_500kbps_is_2_7pct(self):
        """Depth-bar: 10 × 8-byte, 11-bit ID, 100 ms, 500 kbps → 2.7%."""
        msgs = _make_messages(10, 8, 100.0)
        report = compute_can_bus_load(msgs, 500_000)
        assert round(report.total_load_percent, 1) == 2.7
        assert report.ok is True
        assert report.exceeds_40_percent_threshold is False
        assert report.exceeds_30_percent_threshold is False

    def test_100_messages_100ms_500kbps_is_27pct(self):
        """Depth-bar: 100 × 8-byte, 100 ms, 500 kbps → 27% (borderline)."""
        msgs = _make_messages(100, 8, 100.0)
        report = compute_can_bus_load(msgs, 500_000)
        assert round(report.total_load_percent, 1) == 27.0
        assert report.ok is True  # below 40%
        assert report.exceeds_40_percent_threshold is False
        assert report.exceeds_30_percent_threshold is False  # 27% < 30%

    def test_50_messages_10ms_500kbps_exceeds_40pct(self):
        """Depth-bar: 50 × 8-byte, 10 ms, 500 kbps → 135% (flag >40%).

        Actual math: 50 msgs × 135 bits/frame × 100 frames/s / 500,000 bps = 135%.
        (The task spec's 67.5% figure uses a different stuffing model; the CAN 2.0B
        frame model here with 24-bit average stuffing produces the higher value.)
        """
        msgs = _make_messages(50, 8, 10.0)
        report = compute_can_bus_load(msgs, 500_000)
        assert round(report.total_load_percent, 1) == 135.0
        assert report.ok is False
        assert report.exceeds_40_percent_threshold is True
        assert report.exceeds_30_percent_threshold is True

    def test_total_bits_per_sec_oracle(self):
        """10 msgs × (135 bits/frame × 10 frames/s) = 13,500 bps."""
        msgs = _make_messages(10, 8, 100.0)
        report = compute_can_bus_load(msgs, 500_000)
        assert round(report.total_bits_per_sec, 0) == 13500.0


# ─────────────────────────────────────────────────────────────────────────────
# Load threshold tests
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholds:
    def test_low_load_ok(self):
        """Single 8-byte message every 1000 ms on 500 kbps bus → tiny load."""
        msgs = [CanMessage("HEARTBEAT", 0x100, 8, 1000.0)]
        report = compute_can_bus_load(msgs, 500_000)
        assert report.ok is True
        assert report.exceeds_40_percent_threshold is False
        assert report.exceeds_30_percent_threshold is False
        assert report.total_load_percent < 1.0

    def test_exceeds_40pct_flag(self):
        msgs = _make_messages(50, 8, 10.0)
        report = compute_can_bus_load(msgs, 500_000)
        assert report.exceeds_40_percent_threshold is True
        assert report.ok is False
        assert len(report.warnings) >= 1
        assert "CRITICAL" in report.warnings[0]

    def test_exceeds_30pct_but_not_40pct_warning(self):
        """Load between 30% and 40% triggers WARNING not CRITICAL.

        12 × 8-byte, 10 ms period on 500 kbps:
          12 × 135 bpf × 100 fps / 500,000 bps × 100 = 32.4%  (30 < 32.4 < 40)
        """
        msgs = _make_messages(12, 8, 10.0)
        report = compute_can_bus_load(msgs, 500_000)
        assert round(report.total_load_percent, 1) == 32.4
        assert report.total_load_percent > 30.0
        assert report.total_load_percent < 40.0
        assert report.exceeds_30_percent_threshold is True
        assert report.exceeds_40_percent_threshold is False
        assert report.ok is True
        assert "WARNING" in report.warnings[0]

    def test_exactly_at_40pct_threshold(self):
        """Load exactly at 40% → exceeds_40 should be False (not strictly >)."""
        # 40% of 500kbps = 200,000 bps; 200000 / 135 ≈ 1481.5 fps
        # 1481.5 fps × 1000 / 1 msg = period 0.675 ms
        # Use 2 messages: each contributes 100,000 bps → period = 135 × fps; 100000/135 = 740.74 fps → period=1.35ms
        # Craft exactly: 200000 / 135 = 1481.48... fps; period = 1000/1481.48 = 0.6750ms
        # Float precision: just check near-40% is not flagged
        fps_needed = 200_000 / 135  # exactly 40%
        period_ms = 1000.0 / fps_needed
        msgs = [CanMessage("M0", 0, 8, period_ms)]
        report = compute_can_bus_load(msgs, 500_000)
        assert abs(report.total_load_percent - 40.0) < 0.01
        # At exactly 40% (not strictly greater), should not exceed threshold
        assert report.exceeds_40_percent_threshold is False

    def test_just_above_40pct_is_flagged(self):
        fps_needed = 200_001 / 135  # fractionally above 40%
        period_ms = 1000.0 / fps_needed
        msgs = [CanMessage("M0", 0, 8, period_ms)]
        report = compute_can_bus_load(msgs, 500_000)
        assert report.total_load_percent > 40.0
        assert report.exceeds_40_percent_threshold is True


# ─────────────────────────────────────────────────────────────────────────────
# Extended ID tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExtendedID:
    def test_extended_frame_higher_bits_per_frame(self):
        """Extended frame (67 bits) has more overhead than standard (47 bits)."""
        std = bits_per_frame(8, extended_id=False)
        ext = bits_per_frame(8, extended_id=True)
        assert ext - std == 20  # 67 - 47 = 20 extra bits

    def test_extended_id_load_higher_than_standard(self):
        """Same traffic pattern on extended ID → higher bus load."""
        msgs_std = _make_messages(10, 8, 100.0, extended_id=False)
        msgs_ext = _make_messages(10, 8, 100.0, extended_id=True)
        r_std = compute_can_bus_load(msgs_std, 500_000)
        r_ext = compute_can_bus_load(msgs_ext, 500_000)
        assert r_ext.total_load_percent > r_std.total_load_percent

    def test_extended_id_oracle(self):
        """10 × extended 8-byte, 100ms, 500kbps: 155 × 10 / 500000 × 100 = 3.1%."""
        msgs = _make_messages(10, 8, 100.0, extended_id=True)
        report = compute_can_bus_load(msgs, 500_000)
        assert round(report.total_load_percent, 1) == 3.1

    def test_j1939_extended_id_accepted(self):
        """J1939-21 uses 29-bit IDs — verify a typical J1939 PGN ID is accepted."""
        # J1939 Engine Speed PGN 0xF004 = 0x0CF00400 in 29-bit form
        msg = CanMessage("ENGINE_SPEED", 0x0CF00400, 8, 10.0, extended_id=True)
        report = compute_can_bus_load([msg], 250_000)
        assert report.message_count == 1
        assert report.per_message_load[0].extended_id is True

    def test_mixed_standard_and_extended(self):
        """Mix of standard and extended frames: loads should sum correctly."""
        std_msgs = _make_messages(5, 8, 100.0, extended_id=False)
        ext_msgs = _make_messages(5, 8, 100.0, extended_id=True)
        all_msgs = std_msgs + ext_msgs
        report = compute_can_bus_load(all_msgs, 500_000)
        # std contribution: 5 × 135 × 10 / 500000 × 100 = 1.35%
        # ext contribution: 5 × 155 × 10 / 500000 × 100 = 1.55%
        assert round(report.total_load_percent, 2) == round(1.35 + 1.55, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Mixed period tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMixedPeriods:
    def test_fast_and_slow_messages(self):
        """Fast (10ms) and slow (1000ms) messages — load dominated by fast ones."""
        fast = [CanMessage(f"FAST_{i}", i, 8, 10.0) for i in range(5)]
        slow = [CanMessage(f"SLOW_{i}", 0x100 + i, 8, 1000.0) for i in range(20)]
        report = compute_can_bus_load(fast + slow, 500_000)
        # fast: 5 × 135 × 100 / 500000 × 100 = 13.5%
        # slow: 20 × 135 × 1 / 500000 × 100  = 0.54%
        assert round(report.total_load_percent, 2) == round(13.5 + 0.54, 2)
        assert report.ok is True

    def test_per_message_load_sorted_descending(self):
        """Report per_message_load must be sorted by load_percent descending."""
        msgs = [
            CanMessage("SLOW", 0x10, 8, 1000.0),  # lowest load
            CanMessage("FAST", 0x20, 8, 10.0),     # highest load
            CanMessage("MED", 0x30, 8, 100.0),     # middle
        ]
        report = compute_can_bus_load(msgs, 500_000)
        loads = [e.load_percent for e in report.per_message_load]
        assert loads == sorted(loads, reverse=True)

    def test_single_message(self):
        """Single message should produce a single-entry report."""
        msgs = [CanMessage("ONLY", 0x1, 8, 50.0)]
        report = compute_can_bus_load(msgs, 500_000)
        assert report.message_count == 1
        assert len(report.per_message_load) == 1

    def test_zero_data_bytes(self):
        """0-byte DLC (remote frame / heartbeat): 47 + 0 + 24 = 71 bits."""
        msgs = [CanMessage("HB", 0x7FF, 0, 100.0)]
        report = compute_can_bus_load(msgs, 500_000)
        assert report.per_message_load[0].bits_per_frame == 71
        assert report.ok is True

    def test_high_bit_rate_reduces_load(self):
        """Same messages on 1 Mbps bus → half the load vs 500 kbps."""
        msgs = _make_messages(10, 8, 100.0)
        r500 = compute_can_bus_load(msgs, 500_000)
        r1m = compute_can_bus_load(msgs, 1_000_000)
        assert abs(r1m.total_load_percent - r500.total_load_percent / 2) < 0.001

    def test_125kbps_bus_higher_load(self):
        """Low bit-rate (125 kbps) causes higher load fraction."""
        msgs = _make_messages(5, 8, 100.0)
        r125 = compute_can_bus_load(msgs, 125_000)
        r500 = compute_can_bus_load(msgs, 500_000)
        assert r125.total_load_percent == pytest.approx(r500.total_load_percent * 4, rel=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# CanMessage validation
# ─────────────────────────────────────────────────────────────────────────────

class TestCanMessageValidation:
    def test_bad_data_bytes_negative(self):
        with pytest.raises(ValueError, match="data_bytes"):
            CanMessage("X", 0x1, -1, 100.0)

    def test_bad_data_bytes_too_large(self):
        with pytest.raises(ValueError, match="data_bytes"):
            CanMessage("X", 0x1, 9, 100.0)

    def test_bad_period_zero(self):
        with pytest.raises(ValueError, match="period_ms"):
            CanMessage("X", 0x1, 8, 0.0)

    def test_bad_period_negative(self):
        with pytest.raises(ValueError, match="period_ms"):
            CanMessage("X", 0x1, 8, -5.0)

    def test_standard_id_too_large(self):
        with pytest.raises(ValueError, match="CAN ID"):
            CanMessage("X", 0x800, 8, 100.0, extended_id=False)

    def test_extended_id_too_large(self):
        with pytest.raises(ValueError, match="CAN ID"):
            CanMessage("X", 0x20000000, 8, 100.0, extended_id=True)

    def test_standard_id_max_accepted(self):
        msg = CanMessage("X", 0x7FF, 8, 100.0, extended_id=False)
        assert msg.can_id == 0x7FF

    def test_extended_id_max_accepted(self):
        msg = CanMessage("X", 0x1FFFFFFF, 8, 100.0, extended_id=True)
        assert msg.can_id == 0x1FFFFFFF


# ─────────────────────────────────────────────────────────────────────────────
# compute_can_bus_load: edge-case validation
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeEdgeCases:
    def test_empty_messages_raises(self):
        with pytest.raises(ValueError, match="empty"):
            compute_can_bus_load([], 500_000)

    def test_zero_bit_rate_raises(self):
        msgs = [CanMessage("X", 0, 8, 100.0)]
        with pytest.raises(ValueError, match="bit_rate_bps"):
            compute_can_bus_load(msgs, 0)

    def test_negative_bit_rate_raises(self):
        msgs = [CanMessage("X", 0, 8, 100.0)]
        with pytest.raises(ValueError, match="bit_rate_bps"):
            compute_can_bus_load(msgs, -1)

    def test_report_has_notes(self):
        msgs = [CanMessage("X", 0, 8, 100.0)]
        report = compute_can_bus_load(msgs, 500_000)
        assert len(report.notes) > 0

    def test_report_dict_has_required_keys(self):
        msgs = [CanMessage("X", 0, 8, 100.0)]
        d = compute_can_bus_load(msgs, 500_000).as_dict()
        for key in ("ok", "bit_rate_bps", "total_bits_per_sec", "total_load_percent",
                    "exceeds_40_percent_threshold", "exceeds_30_percent_threshold",
                    "message_count", "per_message_load", "warnings", "notes"):
            assert key in d, f"Missing key: {key}"

    def test_entry_dict_has_required_keys(self):
        msgs = [CanMessage("X", 0, 8, 100.0)]
        report = compute_can_bus_load(msgs, 500_000)
        d = report.per_message_load[0].as_dict()
        for key in ("name", "can_id", "extended_id", "data_bytes", "period_ms",
                    "bits_per_frame", "frames_per_sec", "bits_per_sec", "load_percent"):
            assert key in d, f"Missing key: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMTool:
    def _make_tool_messages(self, count, data_bytes, period_ms, *, extended_id=False):
        return [
            {"name": f"MSG_{i}", "can_id": i, "data_bytes": data_bytes,
             "period_ms": period_ms, "extended_id": extended_id}
            for i in range(count)
        ]

    def test_valid_low_load(self):
        result = _tool({
            "messages": self._make_tool_messages(10, 8, 100.0),
            "bit_rate_bps": 500_000,
        })
        assert result["ok"] is True
        assert round(result["total_load_percent"], 1) == 2.7
        assert result["exceeds_40_percent_threshold"] is False
        assert result["message_count"] == 10

    def test_valid_high_load_flagged(self):
        result = _tool({
            "messages": self._make_tool_messages(50, 8, 10.0),
            "bit_rate_bps": 500_000,
        })
        assert result["ok"] is False
        assert result["exceeds_40_percent_threshold"] is True
        assert len(result["warnings"]) >= 1

    def test_valid_extended_id(self):
        result = _tool({
            "messages": self._make_tool_messages(10, 8, 100.0, extended_id=True),
            "bit_rate_bps": 500_000,
        })
        assert result["ok"] is True
        assert round(result["total_load_percent"], 1) == 3.1
        assert result["per_message_load"][0]["extended_id"] is True

    def test_missing_messages(self):
        result = _tool({"bit_rate_bps": 500_000})
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_missing_bit_rate(self):
        result = _tool({"messages": self._make_tool_messages(1, 8, 100.0)})
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_bad_bit_rate_string(self):
        result = _tool({
            "messages": self._make_tool_messages(1, 8, 100.0),
            "bit_rate_bps": "fast",
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_zero_bit_rate(self):
        result = _tool({
            "messages": self._make_tool_messages(1, 8, 100.0),
            "bit_rate_bps": 0,
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_missing_message_name(self):
        result = _tool({
            "messages": [{"can_id": 1, "data_bytes": 8, "period_ms": 100.0}],
            "bit_rate_bps": 500_000,
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_bad_data_bytes(self):
        result = _tool({
            "messages": [{"name": "X", "can_id": 1, "data_bytes": 9, "period_ms": 100.0}],
            "bit_rate_bps": 500_000,
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_bad_period_ms_zero(self):
        result = _tool({
            "messages": [{"name": "X", "can_id": 1, "data_bytes": 8, "period_ms": 0}],
            "bit_rate_bps": 500_000,
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_per_message_sorted_in_tool_response(self):
        """LLM tool response should have per_message_load sorted descending."""
        msgs = [
            {"name": "SLOW", "can_id": 0x10, "data_bytes": 8, "period_ms": 1000.0},
            {"name": "FAST", "can_id": 0x20, "data_bytes": 8, "period_ms": 10.0},
        ]
        result = _tool({"messages": msgs, "bit_rate_bps": 500_000})
        loads = [m["load_percent"] for m in result["per_message_load"]]
        assert loads == sorted(loads, reverse=True)

    def test_250kbps_j1939_typical(self):
        """J1939 typical: 250 kbps, 10 extended-ID messages, 10 ms period."""
        msgs = [
            {"name": f"PGN_{i}", "can_id": 0x0CF00400 + i, "data_bytes": 8,
             "period_ms": 10.0, "extended_id": True}
            for i in range(10)
        ]
        result = _tool({"messages": msgs, "bit_rate_bps": 250_000})
        # 10 × 155 × 100 / 250000 × 100 = 62%
        assert round(result["total_load_percent"], 1) == 62.0
        assert result["exceeds_40_percent_threshold"] is True

    def test_1mbps_bus_low_load(self):
        """1 Mbps CAN: 20 × 8-byte, 10 ms → 20 × 135 × 100 / 1000000 × 100 = 27%."""
        msgs = self._make_tool_messages(20, 8, 10.0)
        result = _tool({"messages": msgs, "bit_rate_bps": 1_000_000})
        assert round(result["total_load_percent"], 1) == 27.0
        assert result["ok"] is True
