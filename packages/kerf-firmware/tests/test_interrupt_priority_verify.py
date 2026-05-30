"""Tests for kerf_firmware.interrupt_priority_verify + interrupt_specs.

Coverage
--------
- interrupt_specs module: registry, aliases, unknown chip, IRQ counts, PRIGROUP maths
- Valid setup (TIM2 priority 1, ADC priority 8) → ok=True, no violations
- SAME_PREEMPT_PRIORITY — two peripherals at same preemption level
- OUT_OF_RANGE — priority value outside 0..15
- RT_IN_LOW_BAND — TIM peripheral at priority 12 (LOW band)
- NON_RT_IN_RT_BAND — USB/ADC at priority 2 (RT band)
- UNKNOWN_PERIPHERAL — name not in IRQ table
- BASEPRI_MISCONFIGURED — BASEPRI=0 and BASEPRI>max
- BASEPRI valid note generated
- allow_same_preempt suppresses SAME_PREEMPT_PRIORITY
- PRIGROUP override changes preemption level calculation
- STM32F407 compatibility
- LLM tool smoke tests: valid, invalid args, unknown chip, conflict
"""
from __future__ import annotations

import json

import pytest

from kerf_firmware.interrupt_specs import (
    STM32F411_IRQ,
    STM32F407_IRQ,
    get_interrupt_spec,
    list_interrupt_chip_ids,
    RT_BAND,
    NORMAL_BAND,
    LOW_BAND,
)
from kerf_firmware.interrupt_priority_verify import (
    IRQAssignment,
    InterruptPriorityReport,
    PriorityViolation,
    verify_interrupt_priorities,
    _preempt_priority,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def violation_kinds(report: InterruptPriorityReport) -> list[str]:
    return [v.kind for v in report.violations]


def make_assignment(peripheral: str, priority: int, label: str = "") -> IRQAssignment:
    return IRQAssignment(peripheral=peripheral, priority=priority, label=label)


# ─────────────────────────────────────────────────────────────────────────────
# interrupt_specs unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestInterruptSpecs:
    def test_registry_has_stm32f411(self):
        assert "STM32F411" in list_interrupt_chip_ids()

    def test_registry_has_stm32f407(self):
        assert "STM32F407" in list_interrupt_chip_ids()

    def test_alias_stm32f411re(self):
        spec = get_interrupt_spec("stm32f411re")
        assert spec.chip_id == "STM32F411"

    def test_alias_stm32f411ce(self):
        spec = get_interrupt_spec("stm32f411ce")
        assert spec.chip_id == "STM32F411"

    def test_alias_stm32f407vg(self):
        spec = get_interrupt_spec("stm32f407vg")
        assert spec.chip_id == "STM32F407"

    def test_alias_case_insensitive(self):
        spec = get_interrupt_spec("stm32F411")
        assert spec.chip_id == "STM32F411"

    def test_unknown_chip_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown chip"):
            get_interrupt_spec("nonexistent_chip_xyz")

    def test_stm32f411_priority_bits(self):
        assert STM32F411_IRQ.priority_bits == 4

    def test_stm32f411_max_priority_is_15(self):
        assert STM32F411_IRQ.min_priority == 15

    def test_stm32f411_min_priority_is_0(self):
        assert STM32F411_IRQ.max_priority == 0

    def test_stm32f411_has_irqs(self):
        assert len(STM32F411_IRQ.irqs) > 30

    def test_stm32f407_has_more_irqs_than_f411(self):
        assert len(STM32F407_IRQ.irqs) > len(STM32F411_IRQ.irqs)

    def test_tim2_is_rt(self):
        irq = STM32F411_IRQ.irq_by_name("TIM2")
        assert irq is not None
        assert irq.rt_class == "RT"

    def test_adc_is_low(self):
        irq = STM32F411_IRQ.irq_by_name("ADC")
        assert irq is not None
        assert irq.rt_class == "LOW"

    def test_otg_fs_is_low(self):
        irq = STM32F411_IRQ.irq_by_name("OTG_FS")
        assert irq is not None
        assert irq.rt_class == "LOW"

    def test_usart1_is_normal(self):
        irq = STM32F411_IRQ.irq_by_name("USART1")
        assert irq is not None
        assert irq.rt_class == "NORMAL"

    def test_exti0_is_rt(self):
        irq = STM32F411_IRQ.irq_by_name("EXTI0")
        assert irq is not None
        assert irq.rt_class == "RT"

    def test_irq_by_name_alias_tim2_irqn(self):
        irq = STM32F411_IRQ.irq_by_name("TIM2_IRQn")
        assert irq is not None
        assert irq.name == "TIM2"

    def test_irq_by_name_case_insensitive(self):
        irq = STM32F411_IRQ.irq_by_name("tim2")
        assert irq is not None
        assert irq.name == "TIM2"

    def test_irq_by_name_unknown_returns_none(self):
        irq = STM32F411_IRQ.irq_by_name("BOGUS_PERIPH_XYZ")
        assert irq is None

    def test_rt_irqs_list_nonempty(self):
        rt = STM32F411_IRQ.rt_irqs()
        assert len(rt) > 0
        assert all(i.rt_class == "RT" for i in rt)

    def test_low_irqs_list_nonempty(self):
        low = STM32F411_IRQ.low_irqs()
        assert len(low) > 0
        assert all(i.rt_class == "LOW" for i in low)


class TestPriorityBands:
    def test_rt_band_starts_at_0(self):
        assert RT_BAND.start == 0
        assert 3 in RT_BAND

    def test_normal_band_starts_at_4(self):
        assert 4 in NORMAL_BAND
        assert 8 in NORMAL_BAND

    def test_low_band_ends_at_15(self):
        assert 9 in LOW_BAND
        assert 15 in LOW_BAND
        assert 16 not in LOW_BAND


class TestPRIGROUP:
    """ARM Cortex-M Generic UG §B3.3 Table B3-2 — PRIGROUP arithmetic."""

    def test_prigroup3_gives_16_preempt_levels(self):
        # PRIGROUP=3: all 4 bits are preempt → 2^4 = 16 levels
        assert STM32F411_IRQ.num_preempt_levels(prigroup=3) == 16

    def test_prigroup4_gives_8_preempt_levels(self):
        # PRIGROUP=4: 3 preempt bits → 2^3 = 8 levels
        assert STM32F411_IRQ.num_preempt_levels(prigroup=4) == 8

    def test_prigroup5_gives_4_preempt_levels(self):
        assert STM32F411_IRQ.num_preempt_levels(prigroup=5) == 4

    def test_prigroup4_gives_2_sub_levels(self):
        assert STM32F411_IRQ.num_sub_levels(prigroup=4) == 2

    def test_prigroup3_gives_1_sub_level(self):
        assert STM32F411_IRQ.num_sub_levels(prigroup=3) == 1

    def test_preempt_priority_extraction_prigroup4(self):
        # PRIGROUP=4: sub_bits=1, so raw >> 1 gives preempt priority
        # raw=2 (binary 0010) → preempt = 2>>1 = 1
        assert _preempt_priority(2, 4, 4) == 1

    def test_preempt_priority_extraction_prigroup3(self):
        # PRIGROUP=3: sub_bits=0, so raw is the preemption priority directly
        assert _preempt_priority(5, 4, 3) == 5

    def test_two_priorities_same_preempt_level_prigroup4(self):
        # PRIGROUP=4: priorities 4 and 5 both map to preempt level 2
        # raw=4 → 4>>1=2; raw=5 → 5>>1=2
        assert _preempt_priority(4, 4, 4) == _preempt_priority(5, 4, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Valid setup — should produce no violations
# ─────────────────────────────────────────────────────────────────────────────

class TestValidSetup:
    """STM32F411: TIM2 at priority 1 (RT), ADC at priority 8 (NORMAL).

    Oracle: ADC (priority 8) cannot preempt TIM2 (priority 1) because
    lower number = higher actual priority (ARM Cortex-M Generic UG §B3.3).
    """

    ASSIGNMENTS = [
        make_assignment("TIM2",    1, "htim2"),
        make_assignment("ADC",     8, "hadc"),
        make_assignment("USART1",  6, "huart1"),
    ]

    def test_ok_true(self):
        report = verify_interrupt_priorities("STM32F411", self.ASSIGNMENTS)
        assert report.ok is True, report.as_dict()

    def test_no_violations(self):
        report = verify_interrupt_priorities("STM32F411", self.ASSIGNMENTS)
        assert report.violations == []

    def test_checked_count(self):
        report = verify_interrupt_priorities("STM32F411", self.ASSIGNMENTS)
        assert report.checked == 3

    def test_chip_in_report(self):
        report = verify_interrupt_priorities("STM32F411", self.ASSIGNMENTS)
        assert report.chip == "STM32F411"

    def test_as_dict_schema(self):
        report = verify_interrupt_priorities("STM32F411", self.ASSIGNMENTS)
        d = report.as_dict()
        assert d["ok"] is True
        assert d["violations"] == []
        assert "chip" in d
        assert "checked" in d
        assert "prigroup" in d
        assert "num_preempt_levels" in d

    def test_alias_accepted(self):
        report = verify_interrupt_priorities("stm32f411re", self.ASSIGNMENTS)
        assert report.ok is True

    def test_spec_object_accepted(self):
        report = verify_interrupt_priorities(STM32F411_IRQ, self.ASSIGNMENTS)
        assert report.ok is True

    def test_notes_contain_prigroup(self):
        report = verify_interrupt_priorities("STM32F411", self.ASSIGNMENTS)
        notes_text = " ".join(report.notes)
        assert "PRIGROUP" in notes_text


# ─────────────────────────────────────────────────────────────────────────────
# SAME_PREEMPT_PRIORITY
# ─────────────────────────────────────────────────────────────────────────────

class TestSamePreemptPriority:
    """Two peripherals at the same preemption priority → non-determinism flag."""

    def test_same_priority_flagged(self):
        asgns = [
            make_assignment("TIM2",   5, "htim2"),
            make_assignment("TIM3",   5, "htim3"),
        ]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert report.ok is False
        assert "SAME_PREEMPT_PRIORITY" in violation_kinds(report)

    def test_conflict_mentions_both_peripherals(self):
        asgns = [
            make_assignment("TIM2",   5),
            make_assignment("USART1", 5),
        ]
        report = verify_interrupt_priorities("STM32F411", asgns)
        conflicts = [v for v in report.violations if v.kind == "SAME_PREEMPT_PRIORITY"]
        assert len(conflicts) >= 1
        all_peripherals = " ".join(v.assignment.peripheral for v in conflicts)
        assert "TIM2" in all_peripherals or "USART1" in all_peripherals

    def test_peers_populated(self):
        asgns = [
            make_assignment("TIM2",   5),
            make_assignment("TIM3",   5),
        ]
        report = verify_interrupt_priorities("STM32F411", asgns)
        conflicts = [v for v in report.violations if v.kind == "SAME_PREEMPT_PRIORITY"]
        for c in conflicts:
            assert len(c.peers) >= 1

    def test_allow_same_preempt_suppresses_violation(self):
        asgns = [
            make_assignment("TIM2",   5),
            make_assignment("TIM3",   5),
        ]
        report = verify_interrupt_priorities(
            "STM32F411", asgns, allow_same_preempt=True
        )
        assert "SAME_PREEMPT_PRIORITY" not in violation_kinds(report)

    def test_prigroup3_same_priority_5_is_conflict(self):
        """With PRIGROUP=3 (no sub bits), raw 5 == preempt 5 for both."""
        asgns = [
            make_assignment("TIM2",   5),
            make_assignment("SPI1",   5),
        ]
        report = verify_interrupt_priorities("STM32F411", asgns, prigroup=3)
        assert "SAME_PREEMPT_PRIORITY" in violation_kinds(report)

    def test_prigroup4_different_preempt_levels_no_conflict(self):
        """With PRIGROUP=4 raw 4 → preempt 2; raw 6 → preempt 3; no conflict."""
        asgns = [
            make_assignment("TIM2",  4),
            make_assignment("SPI1",  6),
        ]
        report = verify_interrupt_priorities("STM32F411", asgns, prigroup=4)
        assert "SAME_PREEMPT_PRIORITY" not in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# OUT_OF_RANGE
# ─────────────────────────────────────────────────────────────────────────────

class TestOutOfRange:
    def test_priority_16_out_of_range(self):
        asgns = [make_assignment("TIM2", 16)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert report.ok is False
        assert "OUT_OF_RANGE" in violation_kinds(report)

    def test_priority_255_out_of_range(self):
        asgns = [make_assignment("TIM2", 255)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "OUT_OF_RANGE" in violation_kinds(report)

    def test_priority_negative_out_of_range(self):
        asgns = [make_assignment("TIM2", -1)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "OUT_OF_RANGE" in violation_kinds(report)

    def test_priority_15_valid(self):
        asgns = [make_assignment("ADC", 15)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "OUT_OF_RANGE" not in violation_kinds(report)

    def test_priority_0_valid(self):
        asgns = [make_assignment("TIM2", 0)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "OUT_OF_RANGE" not in violation_kinds(report)

    def test_out_of_range_detail_mentions_range(self):
        asgns = [make_assignment("TIM2", 20)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        v = [v for v in report.violations if v.kind == "OUT_OF_RANGE"]
        assert len(v) == 1
        assert "15" in v[0].detail or "range" in v[0].detail.lower()


# ─────────────────────────────────────────────────────────────────────────────
# RT_IN_LOW_BAND
# ─────────────────────────────────────────────────────────────────────────────

class TestRTInLowBand:
    def test_tim2_at_priority_12_flagged(self):
        asgns = [make_assignment("TIM2", 12)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "RT_IN_LOW_BAND" in violation_kinds(report)

    def test_exti0_at_priority_15_flagged(self):
        asgns = [make_assignment("EXTI0", 15)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "RT_IN_LOW_BAND" in violation_kinds(report)

    def test_tim2_at_priority_3_not_flagged(self):
        asgns = [make_assignment("TIM2", 3)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "RT_IN_LOW_BAND" not in violation_kinds(report)

    def test_rt_in_low_band_detail_mentions_band(self):
        asgns = [make_assignment("TIM2", 12)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        v = [v for v in report.violations if v.kind == "RT_IN_LOW_BAND"]
        assert len(v) == 1
        assert "LOW" in v[0].detail or "low" in v[0].detail.lower()

    def test_normal_peripheral_in_low_band_not_rt_flag(self):
        """USART1 (NORMAL class) at priority 12 — no RT_IN_LOW_BAND."""
        asgns = [make_assignment("USART1", 12)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "RT_IN_LOW_BAND" not in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# NON_RT_IN_RT_BAND
# ─────────────────────────────────────────────────────────────────────────────

class TestNonRTInRTBand:
    def test_adc_at_priority_2_flagged(self):
        asgns = [make_assignment("ADC", 2)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "NON_RT_IN_RT_BAND" in violation_kinds(report)

    def test_otg_fs_at_priority_0_flagged(self):
        asgns = [make_assignment("OTG_FS", 0)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "NON_RT_IN_RT_BAND" in violation_kinds(report)

    def test_adc_at_priority_9_not_flagged(self):
        """ADC at priority 9 (LOW band) — correct placement."""
        asgns = [make_assignment("ADC", 9)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "NON_RT_IN_RT_BAND" not in violation_kinds(report)

    def test_non_rt_in_rt_detail_mentions_band(self):
        asgns = [make_assignment("OTG_FS", 1)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        v = [v for v in report.violations if v.kind == "NON_RT_IN_RT_BAND"]
        assert len(v) == 1
        assert "RT" in v[0].detail

    def test_normal_peripheral_in_rt_band_not_flagged(self):
        """SPI1 (NORMAL class) at priority 2 — no NON_RT_IN_RT_BAND."""
        asgns = [make_assignment("SPI1", 2)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "NON_RT_IN_RT_BAND" not in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# UNKNOWN_PERIPHERAL
# ─────────────────────────────────────────────────────────────────────────────

class TestUnknownPeripheral:
    def test_bogus_peripheral_flagged(self):
        asgns = [make_assignment("BOGUS_PERIPH_XYZ", 5)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        assert "UNKNOWN_PERIPHERAL" in violation_kinds(report)

    def test_detail_mentions_peripheral_name(self):
        asgns = [make_assignment("BOGUS_PERIPH_XYZ", 5)]
        report = verify_interrupt_priorities("STM32F411", asgns)
        v = [v for v in report.violations if v.kind == "UNKNOWN_PERIPHERAL"]
        assert "BOGUS_PERIPH_XYZ" in v[0].detail

    def test_unknown_not_propagated_to_other_checks(self):
        """UNKNOWN_PERIPHERAL should not also generate SAME_PREEMPT_PRIORITY."""
        asgns = [
            make_assignment("BOGUS_PERIPH_XYZ", 5),
            make_assignment("TIM2", 5),
        ]
        report = verify_interrupt_priorities("STM32F411", asgns)
        # UNKNOWN_PERIPHERAL for BOGUS; SAME_PREEMPT only for known peripherals
        unknown_v = [v for v in report.violations if v.kind == "UNKNOWN_PERIPHERAL"]
        same_v = [v for v in report.violations if v.kind == "SAME_PREEMPT_PRIORITY"]
        assert len(unknown_v) == 1
        # TIM2 alone at priority 5 → no SAME_PREEMPT (only one known peripheral)
        assert len(same_v) == 0


# ─────────────────────────────────────────────────────────────────────────────
# BASEPRI checks
# ─────────────────────────────────────────────────────────────────────────────

class TestBASEPRI:
    def test_basepri_zero_flagged(self):
        asgns = [make_assignment("TIM2", 1)]
        report = verify_interrupt_priorities(
            "STM32F411", asgns, basepri_threshold=0
        )
        assert "BASEPRI_MISCONFIGURED" in violation_kinds(report)

    def test_basepri_zero_detail_mentions_masking(self):
        asgns = [make_assignment("TIM2", 1)]
        report = verify_interrupt_priorities(
            "STM32F411", asgns, basepri_threshold=0
        )
        v = [v for v in report.violations if v.kind == "BASEPRI_MISCONFIGURED"]
        assert "masking" in v[0].detail.lower() or "BASEPRI" in v[0].detail

    def test_basepri_above_max_flagged(self):
        asgns = [make_assignment("TIM2", 1)]
        report = verify_interrupt_priorities(
            "STM32F411", asgns, basepri_threshold=16
        )
        assert "BASEPRI_MISCONFIGURED" in violation_kinds(report)

    def test_basepri_valid_generates_note(self):
        asgns = [make_assignment("TIM2", 1)]
        report = verify_interrupt_priorities(
            "STM32F411", asgns, basepri_threshold=5
        )
        assert "BASEPRI_MISCONFIGURED" not in violation_kinds(report)
        notes_text = " ".join(report.notes)
        assert "BASEPRI" in notes_text or "basepri" in notes_text.lower()

    def test_basepri_none_no_violation(self):
        asgns = [make_assignment("TIM2", 1)]
        report = verify_interrupt_priorities("STM32F411", asgns, basepri_threshold=None)
        assert "BASEPRI_MISCONFIGURED" not in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# Combined violation scenarios
# ─────────────────────────────────────────────────────────────────────────────

class TestCombinedViolations:
    def test_rt_in_low_plus_same_priority(self):
        """TIM2 at priority 10 (RT in LOW band) + TIM3 also at 10 (same preempt)."""
        asgns = [
            make_assignment("TIM2", 10),
            make_assignment("TIM3", 10),
        ]
        report = verify_interrupt_priorities("STM32F411", asgns)
        kinds = set(violation_kinds(report))
        assert "RT_IN_LOW_BAND" in kinds
        assert "SAME_PREEMPT_PRIORITY" in kinds

    def test_multiple_out_of_range(self):
        asgns = [
            make_assignment("TIM2",  20),
            make_assignment("USART1", 16),
        ]
        report = verify_interrupt_priorities("STM32F411", asgns)
        oor = [v for v in report.violations if v.kind == "OUT_OF_RANGE"]
        assert len(oor) == 2


# ─────────────────────────────────────────────────────────────────────────────
# STM32F407 compatibility
# ─────────────────────────────────────────────────────────────────────────────

class TestSTM32F407:
    def test_valid_tim2_adc_f407(self):
        asgns = [
            make_assignment("TIM2", 1),
            make_assignment("ADC",  8),
        ]
        report = verify_interrupt_priorities("STM32F407", asgns)
        assert report.ok is True, report.as_dict()

    def test_f407_has_can1_tx(self):
        irq = STM32F407_IRQ.irq_by_name("CAN1_TX")
        assert irq is not None

    def test_f407_can1_tx_priority_5_no_violation(self):
        asgns = [make_assignment("CAN1_TX", 5)]
        report = verify_interrupt_priorities("STM32F407", asgns)
        assert "UNKNOWN_PERIPHERAL" not in violation_kinds(report)

    def test_alias_stm32f407vg(self):
        asgns = [make_assignment("TIM2", 2)]
        report = verify_interrupt_priorities("stm32f407vg", asgns)
        assert report.chip == "STM32F407"


# ─────────────────────────────────────────────────────────────────────────────
# Unknown chip
# ─────────────────────────────────────────────────────────────────────────────

class TestUnknownChip:
    def test_raises_key_error(self):
        with pytest.raises(KeyError):
            verify_interrupt_priorities("nonexistent_chip_xyz", [
                make_assignment("TIM2", 1),
            ])


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool smoke tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFirmwareVerifyInterruptPrioritiesTool:
    """Smoke tests for the LLM tool wrapper."""

    def _call(self, args: dict) -> dict:
        from kerf_firmware.tools.firmware_verify_interrupt_priorities import (
            run_firmware_verify_interrupt_priorities,
        )
        return json.loads(run_firmware_verify_interrupt_priorities(args))

    def test_valid_tim2_priority1_adc_priority8(self):
        """Oracle: TIM2 at priority 1, ADC at priority 8 → ADC won't preempt TIM2."""
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "TIM2", "priority": 1},
                {"peripheral": "ADC",  "priority": 8},
            ],
        })
        assert result.get("ok") is True, result

    def test_same_priority_conflict_detected(self):
        """Two peripherals at priority 5 → SAME_PREEMPT_PRIORITY."""
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "TIM2",   "priority": 5},
                {"peripheral": "USART1", "priority": 5},
            ],
        })
        assert result.get("ok") is False
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "SAME_PREEMPT_PRIORITY" in kinds

    def test_out_of_range_priority(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "TIM2", "priority": 99},
            ],
        })
        assert result.get("ok") is False
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "OUT_OF_RANGE" in kinds

    def test_rt_in_low_band(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "TIM2", "priority": 12},
            ],
        })
        assert result.get("ok") is False
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "RT_IN_LOW_BAND" in kinds

    def test_missing_chip(self):
        result = self._call({
            "assignments": [{"peripheral": "TIM2", "priority": 1}],
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
            "assignments": [{"peripheral": "TIM2", "priority": 1}],
        })
        assert "error" in result
        assert result.get("code") == "UNKNOWN_CHIP"

    def test_missing_peripheral_field(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [{"priority": 1}],
        })
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_violations_list_in_response(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [{"peripheral": "TIM2", "priority": 1}],
        })
        assert "violations" in result
        assert isinstance(result["violations"], list)

    def test_allow_same_preempt_flag(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "TIM2",   "priority": 5},
                {"peripheral": "USART1", "priority": 5},
            ],
            "allow_same_preempt": True,
        })
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "SAME_PREEMPT_PRIORITY" not in kinds

    def test_basepri_zero_flagged_via_tool(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [{"peripheral": "TIM2", "priority": 1}],
            "basepri_threshold": 0,
        })
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "BASEPRI_MISCONFIGURED" in kinds

    def test_prigroup_override_via_tool(self):
        """PRIGROUP=3 (full 4 preempt bits): priorities 4 and 5 are different levels."""
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "TIM2",   "priority": 4},
                {"peripheral": "USART1", "priority": 5},
            ],
            "prigroup": 3,
        })
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "SAME_PREEMPT_PRIORITY" not in kinds

    def test_stm32f407_via_alias(self):
        result = self._call({
            "chip": "stm32f407vg",
            "assignments": [{"peripheral": "TIM2", "priority": 2}],
        })
        assert result.get("chip") == "STM32F407"

    def test_label_field_optional(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [
                {"peripheral": "TIM2", "priority": 1, "label": "htim2"},
            ],
        })
        assert result.get("ok") is True, result

    def test_response_includes_num_preempt_levels(self):
        result = self._call({
            "chip": "STM32F411",
            "assignments": [{"peripheral": "TIM2", "priority": 1}],
        })
        assert "num_preempt_levels" in result
        assert result["num_preempt_levels"] > 0
