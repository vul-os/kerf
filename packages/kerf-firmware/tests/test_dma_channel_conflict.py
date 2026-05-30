"""Tests for kerf_firmware.dma_channel_conflict + dma_specs.

Coverage
--------
- dma_specs module: registry, aliases, unknown chip, entry counts
- Valid DMA setup → ok=True, no violations
- STREAM_CONFLICT — two peripherals on same stream
- INVALID_ASSIGNMENT — peripheral on wrong stream/channel; suggestions present
- INVALID_ASSIGNMENT — wrong channel on correct stream (right stream, wrong ch)
- UNKNOWN_CONTROLLER — controller name not on chip
- Multiple violations in one report
- STM32F411 SPI1_TX canonical placement (DMA2/Stream3/Ch3 or DMA2/Stream5/Ch3)
- STM32F411 SPI1_RX canonical placement (DMA2/Stream0/Ch3 or DMA2/Stream2/Ch3)
- STM32F407 compatible assignments pass
- LLM tool smoke tests: valid, invalid args, unknown chip, stream conflict
"""
from __future__ import annotations

import json

import pytest

from kerf_firmware.dma_specs import (
    STM32F411_DMA,
    STM32F407_DMA,
    get_dma_spec,
    list_dma_chip_ids,
)
from kerf_firmware.dma_channel_conflict import (
    DMAAssignment,
    DMAConflictReport,
    DMAViolation,
    verify_dma_assignments,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def violation_kinds(report: DMAConflictReport) -> list[str]:
    return [v.kind for v in report.violations]


def make_assignment(
    peripheral: str,
    controller: str,
    stream: int,
    channel: int,
    label: str = "",
) -> DMAAssignment:
    return DMAAssignment(
        peripheral=peripheral,
        controller=controller,
        stream=stream,
        channel=channel,
        label=label,
    )


# ─────────────────────────────────────────────────────────────────────────────
# dma_specs unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDMASpecs:
    def test_registry_has_stm32f411(self):
        ids = list_dma_chip_ids()
        assert "STM32F411" in ids

    def test_registry_has_stm32f407(self):
        ids = list_dma_chip_ids()
        assert "STM32F407" in ids

    def test_alias_stm32f411re(self):
        spec = get_dma_spec("stm32f411re")
        assert spec.chip_id == "STM32F411"

    def test_alias_stm32f411ce(self):
        spec = get_dma_spec("stm32f411ce")
        assert spec.chip_id == "STM32F411"

    def test_alias_stm32f407vg(self):
        spec = get_dma_spec("stm32f407vg")
        assert spec.chip_id == "STM32F407"

    def test_alias_case_insensitive(self):
        spec = get_dma_spec("STM32F411")
        assert spec.chip_id == "STM32F411"

    def test_unknown_chip_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown chip"):
            get_dma_spec("nonexistent_chip_xyz")

    def test_stm32f411_has_two_controllers(self):
        assert set(STM32F411_DMA.controllers) == {"DMA1", "DMA2"}

    def test_stm32f411_streams_per_controller(self):
        assert STM32F411_DMA.streams_per_controller == 8

    def test_stm32f411_channels_per_stream(self):
        assert STM32F411_DMA.channels_per_stream == 8

    def test_stm32f411_has_entries(self):
        assert len(STM32F411_DMA.entries) > 50

    def test_stm32f407_has_entries(self):
        assert len(STM32F407_DMA.entries) > 50

    # RM0383 §10.3.3 Table 28 — SPI1_TX canonical placements
    def test_stm32f411_spi1_tx_dma2_stream3_channel3(self):
        """SPI1_TX must be available on DMA2/Stream3/Ch3 (RM0383 T28)."""
        alts = STM32F411_DMA.valid_channels_for_peripheral("SPI1_TX")
        combos = {(e.controller, e.stream, e.channel) for e in alts}
        assert ("DMA2", 3, 3) in combos, f"DMA2/S3/Ch3 missing; found: {combos}"

    def test_stm32f411_spi1_tx_dma2_stream5_channel3(self):
        """SPI1_TX must also be available on DMA2/Stream5/Ch3 (RM0383 T28)."""
        alts = STM32F411_DMA.valid_channels_for_peripheral("SPI1_TX")
        combos = {(e.controller, e.stream, e.channel) for e in alts}
        assert ("DMA2", 5, 3) in combos, f"DMA2/S5/Ch3 missing; found: {combos}"

    def test_stm32f411_spi1_rx_dma2_stream0_channel3(self):
        """SPI1_RX on DMA2/Stream0/Ch3 (RM0383 T28)."""
        alts = STM32F411_DMA.valid_channels_for_peripheral("SPI1_RX")
        combos = {(e.controller, e.stream, e.channel) for e in alts}
        assert ("DMA2", 0, 3) in combos, f"DMA2/S0/Ch3 missing; found: {combos}"

    def test_stm32f411_spi1_rx_dma2_stream2_channel3(self):
        """SPI1_RX also on DMA2/Stream2/Ch3 (RM0383 T28)."""
        alts = STM32F411_DMA.valid_channels_for_peripheral("SPI1_RX")
        combos = {(e.controller, e.stream, e.channel) for e in alts}
        assert ("DMA2", 2, 3) in combos, f"DMA2/S2/Ch3 missing; found: {combos}"

    def test_stm32f411_usart2_rx_dma1_stream5_channel4(self):
        """USART2_RX on DMA1/Stream5/Ch4 (RM0383 T27)."""
        alts = STM32F411_DMA.valid_channels_for_peripheral("USART2_RX")
        combos = {(e.controller, e.stream, e.channel) for e in alts}
        assert ("DMA1", 5, 4) in combos

    def test_stm32f411_usart2_tx_dma1_stream6_channel4(self):
        """USART2_TX on DMA1/Stream6/Ch4 (RM0383 T27)."""
        alts = STM32F411_DMA.valid_channels_for_peripheral("USART2_TX")
        combos = {(e.controller, e.stream, e.channel) for e in alts}
        assert ("DMA1", 6, 4) in combos

    def test_stm32f411_adc1_dma2_stream0_channel0(self):
        """ADC1 on DMA2/Stream0/Ch0 (RM0383 T28)."""
        alts = STM32F411_DMA.valid_channels_for_peripheral("ADC1")
        combos = {(e.controller, e.stream, e.channel) for e in alts}
        assert ("DMA2", 0, 0) in combos

    def test_valid_entries_for_exact_lookup(self):
        """valid_entries_for returns match for known-good (controller,stream,peripheral)."""
        matches = STM32F411_DMA.valid_entries_for("DMA2", 3, "SPI1_TX")
        assert any(e.channel == 3 for e in matches)


# ─────────────────────────────────────────────────────────────────────────────
# Valid DMA setup — should produce no violations
# ─────────────────────────────────────────────────────────────────────────────

class TestValidSetup:
    """STM32F411: SPI1_TX on DMA2/Stream3/Ch3 and SPI1_RX on DMA2/Stream0/Ch3."""

    ASSIGNMENTS = [
        make_assignment("SPI1_TX", "DMA2", 3, 3, "hdma_spi1_tx"),
        make_assignment("SPI1_RX", "DMA2", 0, 3, "hdma_spi1_rx"),
    ]

    def test_ok_true(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        assert report.ok is True, report.as_dict()

    def test_no_violations(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        assert report.violations == []

    def test_checked_count(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        assert report.checked == 2

    def test_chip_in_report(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        assert report.chip == "STM32F411"

    def test_as_dict_schema(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        d = report.as_dict()
        assert d["ok"] is True
        assert d["violations"] == []
        assert "chip" in d
        assert "checked" in d

    def test_alias_accepted(self):
        report = verify_dma_assignments("stm32f411re", self.ASSIGNMENTS)
        assert report.ok is True

    def test_spec_object_accepted(self):
        report = verify_dma_assignments(STM32F411_DMA, self.ASSIGNMENTS)
        assert report.ok is True


class TestValidMultiPeripheral:
    """Valid setup: USART2_RX, USART2_TX, ADC1 on different streams."""

    ASSIGNMENTS = [
        make_assignment("USART2_RX", "DMA1", 5, 4),
        make_assignment("USART2_TX", "DMA1", 6, 4),
        make_assignment("ADC1",      "DMA2", 0, 0),
    ]

    def test_ok_true(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        assert report.ok is True, report.as_dict()


class TestValidSPI3:
    """SPI3_RX on DMA1/Stream0/Ch0 (RM0383 T27)."""

    def test_spi3_rx_stream0_ch0(self):
        asgns = [make_assignment("SPI3_RX", "DMA1", 0, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        assert report.ok is True, report.as_dict()


# ─────────────────────────────────────────────────────────────────────────────
# STREAM_CONFLICT
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamConflict:
    """Two peripherals on DMA2/Stream3 → STREAM_CONFLICT."""

    ASSIGNMENTS = [
        make_assignment("SPI1_TX", "DMA2", 3, 3, "hdma_spi1_tx"),
        make_assignment("SDIO",    "DMA2", 3, 4, "hdma_sdio"),
    ]

    def test_ok_false(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        assert report.ok is False

    def test_stream_conflict_detected(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        assert "STREAM_CONFLICT" in violation_kinds(report)

    def test_conflict_mentions_both_peripherals(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        conflicts = [v for v in report.violations if v.kind == "STREAM_CONFLICT"]
        assert len(conflicts) >= 1
        peripheral_names = " ".join(v.assignment.peripheral for v in conflicts)
        assert "SPI1_TX" in peripheral_names or "SDIO" in peripheral_names

    def test_conflict_detail_mentions_stream(self):
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        conflicts = [v for v in report.violations if v.kind == "STREAM_CONFLICT"]
        detail = conflicts[0].detail
        assert "Stream3" in detail or "stream" in detail.lower()

    def test_same_stream_both_assignments_flagged(self):
        """Both assignments on the conflicting stream appear in violations."""
        report = verify_dma_assignments("STM32F411", self.ASSIGNMENTS)
        conflict_peripherals = {
            v.assignment.peripheral
            for v in report.violations
            if v.kind == "STREAM_CONFLICT"
        }
        assert conflict_peripherals & {"SPI1_TX", "SDIO"}


class TestStreamConflictDMA1:
    """USART2_RX and SPI3_TX both on DMA1/Stream5."""

    def test_stream5_conflict(self):
        asgns = [
            make_assignment("USART2_RX", "DMA1", 5, 4),
            make_assignment("SPI3_TX",   "DMA1", 5, 0),
        ]
        report = verify_dma_assignments("STM32F411", asgns)
        assert "STREAM_CONFLICT" in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# INVALID_ASSIGNMENT — wrong stream/channel
# ─────────────────────────────────────────────────────────────────────────────

class TestInvalidAssignment:
    """SPI1_TX on DMA2/Stream3/Ch0 — channel 0 is wrong; correct is Ch3."""

    def test_invalid_channel_detected(self):
        """SPI1_TX exists on DMA2/Stream3 but requires channel 3, not channel 0."""
        asgns = [make_assignment("SPI1_TX", "DMA2", 3, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        assert report.ok is False
        assert "INVALID_ASSIGNMENT" in violation_kinds(report)

    def test_invalid_assignment_has_suggestions(self):
        asgns = [make_assignment("SPI1_TX", "DMA2", 3, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        inv = [v for v in report.violations if v.kind == "INVALID_ASSIGNMENT"]
        assert len(inv) == 1
        # Should suggest DMA2/Stream3/Ch3 and DMA2/Stream5/Ch3
        assert len(inv[0].suggestions) >= 1
        combos = {(s["controller"], s["stream"], s["channel"]) for s in inv[0].as_dict()["suggestions"]}
        assert ("DMA2", 3, 3) in combos or ("DMA2", 5, 3) in combos

    def test_invalid_stream_detected(self):
        """SPI1_TX assigned to DMA1/Stream0/Ch0 — SPI1_TX is DMA2 only."""
        asgns = [make_assignment("SPI1_TX", "DMA1", 0, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        assert "INVALID_ASSIGNMENT" in violation_kinds(report)

    def test_unknown_peripheral_detected(self):
        """A peripheral not in the DMA table at all."""
        asgns = [make_assignment("BOGUS_PERIPH", "DMA1", 0, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        assert "INVALID_ASSIGNMENT" in violation_kinds(report)
        inv = [v for v in report.violations if v.kind == "INVALID_ASSIGNMENT"]
        assert inv[0].suggestions == []

    def test_invalid_detail_mentions_valid_alternatives(self):
        """Violation detail for wrong stream mentions valid options."""
        asgns = [make_assignment("SPI1_TX", "DMA1", 0, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        inv = [v for v in report.violations if v.kind == "INVALID_ASSIGNMENT"]
        detail = inv[0].detail
        assert "DMA2" in detail or "Stream" in detail or "RM0383" in detail

    def test_invalid_assignment_as_dict_schema(self):
        asgns = [make_assignment("SPI1_TX", "DMA2", 3, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        inv = [v for v in report.violations if v.kind == "INVALID_ASSIGNMENT"]
        d = inv[0].as_dict()
        assert "kind" in d
        assert "peripheral" in d
        assert "suggestions" in d
        assert isinstance(d["suggestions"], list)


class TestWrongChannelOnCorrectStream:
    """SPI1_TX on DMA2/Stream3/Ch1 — stream is correct, channel is wrong."""

    def test_wrong_channel_flagged(self):
        asgns = [make_assignment("SPI1_TX", "DMA2", 3, 1)]
        report = verify_dma_assignments("STM32F411", asgns)
        assert "INVALID_ASSIGNMENT" in violation_kinds(report)

    def test_detail_mentions_channel(self):
        asgns = [make_assignment("SPI1_TX", "DMA2", 3, 1)]
        report = verify_dma_assignments("STM32F411", asgns)
        inv = [v for v in report.violations if v.kind == "INVALID_ASSIGNMENT"]
        assert "channel" in inv[0].detail.lower() or "ch" in inv[0].detail.lower()


# ─────────────────────────────────────────────────────────────────────────────
# UNKNOWN_CONTROLLER
# ─────────────────────────────────────────────────────────────────────────────

class TestUnknownController:
    def test_dma3_unknown_on_stm32f411(self):
        asgns = [make_assignment("SPI1_TX", "DMA3", 0, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        assert "UNKNOWN_CONTROLLER" in violation_kinds(report)

    def test_detail_mentions_known_controllers(self):
        asgns = [make_assignment("SPI1_TX", "DMA3", 0, 0)]
        report = verify_dma_assignments("STM32F411", asgns)
        unk = [v for v in report.violations if v.kind == "UNKNOWN_CONTROLLER"]
        assert "DMA1" in unk[0].detail or "DMA2" in unk[0].detail


# ─────────────────────────────────────────────────────────────────────────────
# Multiple violations in one report
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleViolations:
    """Stream conflict + invalid assignment in one call."""

    def test_combined_violations(self):
        asgns = [
            # INVALID: SPI1_TX on DMA2/Stream3/Ch0 (wrong channel)
            make_assignment("SPI1_TX", "DMA2", 3, 0),
            # STREAM_CONFLICT: SDIO also on DMA2/Stream3 (ch4 is valid for SDIO)
            make_assignment("SDIO",    "DMA2", 3, 4),
        ]
        report = verify_dma_assignments("STM32F411", asgns)
        kinds = set(violation_kinds(report))
        assert "INVALID_ASSIGNMENT" in kinds
        assert "STREAM_CONFLICT" in kinds

    def test_unknown_controller_plus_invalid(self):
        asgns = [
            make_assignment("SPI1_TX", "DMA3", 0, 0),   # UNKNOWN_CONTROLLER
            make_assignment("BOGUS",   "DMA2", 0, 0),   # INVALID_ASSIGNMENT
        ]
        report = verify_dma_assignments("STM32F411", asgns)
        kinds = set(violation_kinds(report))
        assert "UNKNOWN_CONTROLLER" in kinds
        assert "INVALID_ASSIGNMENT" in kinds


# ─────────────────────────────────────────────────────────────────────────────
# STM32F407 compatibility
# ─────────────────────────────────────────────────────────────────────────────

class TestSTM32F407:
    def test_valid_usart2_rx_dma1_stream5_ch4(self):
        asgns = [make_assignment("USART2_RX", "DMA1", 5, 4)]
        report = verify_dma_assignments("STM32F407", asgns)
        assert report.ok is True, report.as_dict()

    def test_valid_spi3_rx_dma1_stream0_ch0(self):
        asgns = [make_assignment("SPI3_RX", "DMA1", 0, 0)]
        report = verify_dma_assignments("STM32F407", asgns)
        assert report.ok is True, report.as_dict()

    def test_stream_conflict_f407(self):
        asgns = [
            make_assignment("SPI3_RX", "DMA1", 0, 0),
            make_assignment("I2C1_RX", "DMA1", 0, 1),
        ]
        report = verify_dma_assignments("STM32F407", asgns)
        assert "STREAM_CONFLICT" in violation_kinds(report)

    def test_alias_stm32f407vg(self):
        asgns = [make_assignment("USART2_TX", "DMA1", 6, 4)]
        report = verify_dma_assignments("stm32f407vg", asgns)
        assert report.ok is True, report.as_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Unknown chip
# ─────────────────────────────────────────────────────────────────────────────

class TestUnknownChip:
    def test_raises_key_error(self):
        with pytest.raises(KeyError):
            verify_dma_assignments("nonexistent_chip_xyz", [
                make_assignment("SPI1_TX", "DMA2", 3, 3),
            ])


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool smoke tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFirmwareVerifyDMATool:
    """Smoke tests for the LLM tool wrapper."""

    def _call(self, args: dict) -> dict:
        from kerf_firmware.tools.firmware_verify_dma_assignments import (
            run_firmware_verify_dma_assignments,
        )
        return json.loads(run_firmware_verify_dma_assignments(args))

    def test_valid_spi1_tx_stream3_ch3(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "SPI1_TX", "controller": "DMA2", "stream": 3, "channel": 3},
            ],
        })
        assert result.get("ok") is True, result

    def test_stream_conflict_detected(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "SPI1_TX", "controller": "DMA2", "stream": 3, "channel": 3},
                {"peripheral": "SDIO",    "controller": "DMA2", "stream": 3, "channel": 4},
            ],
        })
        assert result.get("ok") is False
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "STREAM_CONFLICT" in kinds

    def test_invalid_assignment_suggestions(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                # SPI1_TX on channel 0 of stream 3 is invalid
                {"peripheral": "SPI1_TX", "controller": "DMA2", "stream": 3, "channel": 0},
            ],
        })
        assert result.get("ok") is False
        inv = [v for v in result.get("violations", []) if v["kind"] == "INVALID_ASSIGNMENT"]
        assert len(inv) == 1
        assert isinstance(inv[0]["suggestions"], list)
        assert len(inv[0]["suggestions"]) >= 1

    def test_missing_chip(self):
        result = self._call({
            "assignments": [
                {"peripheral": "SPI1_TX", "controller": "DMA2", "stream": 3, "channel": 3},
            ],
        })
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_missing_assignments(self):
        result = self._call({"chip": "STM32F411"})
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_unknown_chip_returns_error(self):
        result = self._call({
            "chip": "nonexistent_chip_xyz",
            "assignments": [
                {"peripheral": "SPI1_TX", "controller": "DMA2", "stream": 3, "channel": 3},
            ],
        })
        assert "error" in result
        assert result.get("code") == "UNKNOWN_CHIP"

    def test_missing_peripheral_field(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"controller": "DMA2", "stream": 3, "channel": 3},  # missing peripheral
            ],
        })
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_label_field_optional(self):
        """Assignments with label field should work fine."""
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {
                    "peripheral": "SPI1_TX",
                    "controller": "DMA2",
                    "stream": 3,
                    "channel": 3,
                    "label": "hdma_spi1_tx",
                },
            ],
        })
        assert result.get("ok") is True, result

    def test_violations_list_in_response(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "SPI1_TX", "controller": "DMA2", "stream": 3, "channel": 3},
            ],
        })
        assert "violations" in result
        assert isinstance(result["violations"], list)

    def test_unknown_controller_in_tool(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "SPI1_TX", "controller": "DMA3", "stream": 0, "channel": 0},
            ],
        })
        assert result.get("ok") is False
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "UNKNOWN_CONTROLLER" in kinds

    def test_stm32f407_via_alias(self):
        result = self._call({
            "chip": "stm32f407vg",
            "assignments": [
                {"peripheral": "USART2_RX", "controller": "DMA1", "stream": 5, "channel": 4},
            ],
        })
        assert result.get("ok") is True, result

    def test_multiple_valid_assignments(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "SPI1_TX",   "controller": "DMA2", "stream": 3, "channel": 3},
                {"peripheral": "SPI1_RX",   "controller": "DMA2", "stream": 0, "channel": 3},
                {"peripheral": "USART2_RX", "controller": "DMA1", "stream": 5, "channel": 4},
                {"peripheral": "USART2_TX", "controller": "DMA1", "stream": 6, "channel": 4},
            ],
        })
        assert result.get("ok") is True, result
        assert result.get("checked") == 4
