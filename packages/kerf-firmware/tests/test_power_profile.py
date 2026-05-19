"""
tests/test_power_profile.py
============================

Tests for PowerModel and the board-current table.

Coverage
--------
* Board lookup — canonical names, aliases, case-insensitivity, missing
* BoardProfile values — 15+ boards present with positive currents
* Peripheral construction — validation
* PowerModel — average current for always-on, duty-cycle, peripheral mixes
* PowerModel.summary() — serialisable shape
"""
from __future__ import annotations

import math
import pytest

from kerf_firmware.power_profile.board_currents import (
    BOARD_TABLE,
    BoardProfile,
    board_lookup,
    list_boards,
)
from kerf_firmware.power_profile.model import Peripheral, PowerModel


# ---------------------------------------------------------------------------
# Board-table sanity
# ---------------------------------------------------------------------------

class TestBoardTable:
    def test_at_least_15_boards_present(self):
        assert len(BOARD_TABLE) >= 15

    def test_all_active_currents_positive(self):
        for name, profile in BOARD_TABLE.items():
            assert profile.active_mA > 0, f"{name}: active_mA must be > 0"

    def test_all_sleep_currents_non_negative(self):
        for name, profile in BOARD_TABLE.items():
            assert profile.sleep_mA >= 0, f"{name}: sleep_mA must be >= 0"

    def test_all_sleep_currents_less_than_active(self):
        for name, profile in BOARD_TABLE.items():
            assert profile.sleep_mA < profile.active_mA, (
                f"{name}: sleep_mA ({profile.sleep_mA}) should be < active_mA ({profile.active_mA})"
            )

    def test_all_voltages_sensible(self):
        for name, profile in BOARD_TABLE.items():
            assert 1.8 <= profile.voltage_V <= 12.0, (
                f"{name}: voltage_V {profile.voltage_V} out of expected range"
            )

    def test_specific_boards_present(self):
        """Key boards users will reference must be in the table."""
        expected = [
            "Arduino Uno",
            "Arduino Nano",
            "Arduino Mega 2560",
            "Arduino Nano Every",
            "ESP8266",
            "ESP32",
            "ESP32-S2",
            "ESP32-S3",
            "ESP32-C3",
            "RP2040",
            "RP2350",
            "STM32F103",
            "STM32L476",
            "nRF52840",
            "Teensy 4.1",
            "SAMD21",
            "SAMD51",
        ]
        for board in expected:
            assert board in BOARD_TABLE, f"Expected board {board!r} in BOARD_TABLE"

    def test_list_boards_sorted(self):
        boards = list_boards()
        assert boards == sorted(boards)
        assert len(boards) == len(BOARD_TABLE)


# ---------------------------------------------------------------------------
# Board lookup
# ---------------------------------------------------------------------------

class TestBoardLookup:
    def test_canonical_name_resolves(self):
        p = board_lookup("ESP32")
        assert isinstance(p, BoardProfile)
        assert p.active_mA == 80.0

    def test_alias_resolves(self):
        assert board_lookup("esp32") == board_lookup("ESP32")

    def test_alias_pico_resolves_to_rp2040(self):
        assert board_lookup("pico") == board_lookup("RP2040")

    def test_alias_blue_pill(self):
        assert board_lookup("blue pill") == board_lookup("STM32F103")

    def test_alias_arduino_zero(self):
        assert board_lookup("arduino zero") == board_lookup("SAMD21")

    def test_unknown_board_raises_key_error(self):
        with pytest.raises(KeyError, match="not found"):
            board_lookup("ACME Microwidget 9000")

    def test_key_error_lists_available_boards(self):
        with pytest.raises(KeyError) as exc_info:
            board_lookup("nonexistent-board")
        assert "Arduino Uno" in str(exc_info.value)

    def test_case_insensitive_direct_match(self):
        # Keys have mixed case — lowercase variant should still resolve
        p = board_lookup("arduino uno")
        assert p.active_mA > 0


# ---------------------------------------------------------------------------
# Peripheral construction
# ---------------------------------------------------------------------------

class TestPeripheral:
    def test_valid_peripheral(self):
        p = Peripheral(name="GPS", current_mA=30.0)
        assert p.current_mA == 30.0
        assert p.always_on is False

    def test_always_on_peripheral(self):
        p = Peripheral(name="RTC", current_mA=0.005, always_on=True)
        assert p.always_on is True

    def test_zero_current_allowed(self):
        p = Peripheral(name="Dummy", current_mA=0.0)
        assert p.current_mA == 0.0

    def test_negative_current_raises(self):
        with pytest.raises(ValueError, match="current_mA must be >= 0"):
            Peripheral(name="Bad", current_mA=-1.0)


# ---------------------------------------------------------------------------
# PowerModel — always-on (duty_cycle=1)
# ---------------------------------------------------------------------------

class TestPowerModelAlwaysOn:
    def test_esp32_always_on_average_equals_active(self):
        """duty_cycle=1 → average == active current (no sleep)."""
        model = PowerModel("ESP32", duty_cycle=1.0)
        assert model.average_current_mA == pytest.approx(80.0)

    def test_active_phase_includes_active_only_peripheral(self):
        perip = Peripheral("LED", current_mA=20.0, always_on=False)
        model = PowerModel("ESP32", peripherals=[perip], duty_cycle=1.0)
        assert model.active_phase_current_mA == pytest.approx(100.0)

    def test_active_phase_includes_always_on_peripheral(self):
        perip = Peripheral("Sensor", current_mA=5.0, always_on=True)
        model = PowerModel("ESP32", peripherals=[perip], duty_cycle=1.0)
        assert model.active_phase_current_mA == pytest.approx(85.0)

    def test_average_equals_active_when_duty_one(self):
        perip = Peripheral("GPS", current_mA=30.0)
        model = PowerModel("ESP32", peripherals=[perip], duty_cycle=1.0)
        assert model.average_current_mA == pytest.approx(110.0)

    def test_sleep_phase_excludes_active_only_peripheral(self):
        perip = Peripheral("LED", current_mA=20.0, always_on=False)
        model = PowerModel("ESP32", peripherals=[perip], duty_cycle=0.5)
        # sleep phase = ESP32 sleep (0.01) only — LED off
        assert model.sleep_phase_current_mA == pytest.approx(0.01)

    def test_sleep_phase_includes_always_on_peripheral(self):
        perip = Peripheral("RTC", current_mA=0.005, always_on=True)
        model = PowerModel("ESP32", peripherals=[perip])
        assert model.sleep_phase_current_mA == pytest.approx(0.01 + 0.005)


# ---------------------------------------------------------------------------
# PowerModel — duty cycle variations
# ---------------------------------------------------------------------------

class TestPowerModelDutyCycle:
    def test_always_sleeping_duty_zero(self):
        """duty_cycle=0 → average == sleep current."""
        model = PowerModel("ESP32", duty_cycle=0.0)
        assert model.average_current_mA == pytest.approx(0.01)

    def test_duty_cycle_50_percent(self):
        """50% duty: average = 0.5 * active + 0.5 * sleep."""
        model = PowerModel("ESP32", duty_cycle=0.5)
        expected = 0.5 * 80.0 + 0.5 * 0.01
        assert model.average_current_mA == pytest.approx(expected)

    def test_duty_cycle_1_percent(self):
        """1% active duty → mostly deep-sleep average."""
        model = PowerModel("ESP32", duty_cycle=0.01)
        expected = 0.01 * 80.0 + 0.99 * 0.01
        assert model.average_current_mA == pytest.approx(expected, rel=1e-6)

    def test_duty_cycle_out_of_range_raises(self):
        with pytest.raises(ValueError, match="duty_cycle must be in"):
            PowerModel("ESP32", duty_cycle=1.5)

    def test_duty_cycle_negative_raises(self):
        with pytest.raises(ValueError, match="duty_cycle must be in"):
            PowerModel("ESP32", duty_cycle=-0.1)

    def test_duty_cycle_exactly_zero_allowed(self):
        model = PowerModel("ESP32", duty_cycle=0.0)
        assert model.duty_cycle == 0.0

    def test_duty_cycle_exactly_one_allowed(self):
        model = PowerModel("ESP32", duty_cycle=1.0)
        assert model.duty_cycle == 1.0


# ---------------------------------------------------------------------------
# PowerModel — multiple peripherals
# ---------------------------------------------------------------------------

class TestPowerModelPeripherals:
    def test_multiple_active_only_peripherals(self):
        peripherals = [
            Peripheral("Motor", current_mA=200.0),
            Peripheral("LCD", current_mA=15.0),
        ]
        model = PowerModel("ESP32", peripherals=peripherals, duty_cycle=1.0)
        assert model.average_current_mA == pytest.approx(80.0 + 200.0 + 15.0)

    def test_mixed_peripheral_types_at_50_duty(self):
        peripherals = [
            Peripheral("GPS", current_mA=30.0, always_on=False),
            Peripheral("RTC", current_mA=0.005, always_on=True),
        ]
        model = PowerModel("ESP32", peripherals=peripherals, duty_cycle=0.5)
        active = 80.0 + 30.0 + 0.005
        sleep = 0.01 + 0.005
        expected = 0.5 * active + 0.5 * sleep
        assert model.average_current_mA == pytest.approx(expected)

    def test_50mA_peripheral_reduces_life_proportionally(self):
        """Adding a 50 mA active-only peripheral scales life inversely."""
        model_base = PowerModel("ESP32", duty_cycle=1.0)
        model_with = PowerModel(
            "ESP32",
            peripherals=[Peripheral("Sensor", current_mA=50.0)],
            duty_cycle=1.0,
        )
        # Life ratio should be inversely proportional to current ratio
        base_mA = model_base.average_current_mA      # 80
        with_mA = model_with.average_current_mA      # 130
        assert with_mA == pytest.approx(base_mA + 50.0)
        # battery_life is inversely proportional to average_current_mA
        ratio = base_mA / with_mA
        # 80/130 ≈ 0.615
        assert ratio == pytest.approx(80.0 / 130.0, rel=1e-6)

    def test_no_peripherals_is_valid(self):
        model = PowerModel("ESP32")
        assert model.peripherals == []


# ---------------------------------------------------------------------------
# PowerModel — board profile direct injection
# ---------------------------------------------------------------------------

class TestPowerModelDirectProfile:
    def test_accepts_board_profile_object(self):
        profile = BoardProfile(active_mA=10.0, sleep_mA=0.001, voltage_V=3.3)
        model = PowerModel(board=profile, duty_cycle=1.0)
        assert model.average_current_mA == pytest.approx(10.0)

    def test_profile_sleep_respected(self):
        profile = BoardProfile(active_mA=10.0, sleep_mA=0.5, voltage_V=3.3)
        model = PowerModel(board=profile, duty_cycle=0.0)
        assert model.average_current_mA == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# PowerModel.summary()
# ---------------------------------------------------------------------------

class TestPowerModelSummary:
    def test_summary_has_expected_keys(self):
        model = PowerModel("ESP32", duty_cycle=0.5)
        s = model.summary()
        for key in ("board", "duty_cycle", "active_phase_mA", "sleep_phase_mA", "average_mA", "peripherals"):
            assert key in s, f"Missing key {key!r} in summary"

    def test_summary_peripherals_list(self):
        model = PowerModel(
            "ESP32",
            peripherals=[Peripheral("GPS", current_mA=30.0)],
            duty_cycle=1.0,
        )
        s = model.summary()
        assert len(s["peripherals"]) == 1
        assert s["peripherals"][0]["name"] == "GPS"

    def test_summary_values_are_finite(self):
        model = PowerModel("ESP32", duty_cycle=0.01)
        s = model.summary()
        assert math.isfinite(s["average_mA"])
        assert math.isfinite(s["active_phase_mA"])
        assert math.isfinite(s["sleep_phase_mA"])

    def test_summary_duty_cycle_stored(self):
        model = PowerModel("ESP32", duty_cycle=0.25)
        assert model.summary()["duty_cycle"] == 0.25


# ---------------------------------------------------------------------------
# A representative cross-section of boards
# ---------------------------------------------------------------------------

class TestBoardSpecificValues:
    """Spot-check a handful of boards to catch obvious table typos."""

    @pytest.mark.parametrize("board,min_active,max_active", [
        ("Arduino Uno",    30,  120),
        ("ESP32",          50,  150),
        ("RP2040",         10,   60),
        ("STM32L476",       5,   30),
        ("nRF52840",        2,   15),
        ("Teensy 4.1",     60,  200),
    ])
    def test_active_current_in_plausible_range(self, board, min_active, max_active):
        p = board_lookup(board)
        assert min_active <= p.active_mA <= max_active, (
            f"{board}: active_mA={p.active_mA} not in [{min_active}, {max_active}]"
        )

    @pytest.mark.parametrize("board,max_sleep", [
        ("ESP32",      1.0),   # deep-sleep << 1 mA
        ("RP2040",     1.0),   # DORMANT < 1 mA
        ("STM32L476",  0.01),  # Shutdown << 0.01 mA
        ("nRF52840",   0.01),  # System-off << 0.01 mA
    ])
    def test_sleep_current_is_very_low(self, board, max_sleep):
        p = board_lookup(board)
        assert p.sleep_mA < max_sleep, (
            f"{board}: sleep_mA={p.sleep_mA} should be < {max_sleep} mA"
        )
