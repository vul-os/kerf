"""
tests/test_battery_life.py
===========================

Tests for battery_life() and battery_life_from_energy().

Key scenarios mandated by spec
-------------------------------
1. ESP32 always-on (duty=1.0), 3000 mAh → ~37 hours
2. ESP32 1% duty + 99% deep-sleep, 3000 mAh → ~3700 hours
3. Adding a 50 mA active-only peripheral reduces life proportionally
"""
from __future__ import annotations

import math
import pytest

from kerf_firmware.power_profile.model import Peripheral, PowerModel
from kerf_firmware.power_profile.battery_life import (
    battery_life,
    battery_life_from_energy,
)


# ---------------------------------------------------------------------------
# Spec scenario 1 — ESP32 always-on → ~37 hours
# ---------------------------------------------------------------------------

class TestESP32AlwaysOn:
    def test_3000_mah_always_on_approx_37_hours(self):
        """3000 mAh / 80 mA = 37.5 h  (within 5 % of 37 h)."""
        model = PowerModel("ESP32", duty_cycle=1.0)
        hours = battery_life(battery_mAh=3000, voltage=3.7, model=model)
        assert math.isclose(hours, 37.5, rel_tol=0.01), (
            f"Expected ~37.5 h for always-on ESP32, got {hours:.2f} h"
        )

    def test_always_on_hours_near_37(self):
        """Sanity: result is between 35 and 40 hours."""
        model = PowerModel("ESP32", duty_cycle=1.0)
        hours = battery_life(3000, 3.7, model)
        assert 35 <= hours <= 40, f"Expected 35–40 h, got {hours:.1f} h"


# ---------------------------------------------------------------------------
# Spec scenario 2 — ESP32 1% duty → ~3700 hours
# ---------------------------------------------------------------------------

class TestESP32LowDutyCycle:
    def test_1pct_duty_3000mah_approx_3700_hours(self):
        """1% duty-cycle, 3000 mAh should yield roughly 3700 h."""
        model = PowerModel("ESP32", duty_cycle=0.01)
        # average_mA = 0.01*80 + 0.99*0.01 = 0.8 + 0.0099 = 0.8099
        hours = battery_life(3000, 3.7, model)
        assert math.isclose(hours, 3000 / 0.8099, rel_tol=0.01), (
            f"Expected ~{3000/0.8099:.0f} h, got {hours:.0f} h"
        )

    def test_1pct_duty_hours_in_expected_range(self):
        model = PowerModel("ESP32", duty_cycle=0.01)
        hours = battery_life(3000, 3.7, model)
        assert 3500 <= hours <= 4000, f"Expected 3500–4000 h, got {hours:.0f} h"

    def test_low_duty_much_longer_than_always_on(self):
        """Low duty must be >> always-on life (at least 50×)."""
        always_on = battery_life(3000, 3.7, PowerModel("ESP32", duty_cycle=1.0))
        low_duty  = battery_life(3000, 3.7, PowerModel("ESP32", duty_cycle=0.01))
        assert low_duty > always_on * 50, (
            f"Low-duty life {low_duty:.0f} h should be > 50× always-on {always_on:.1f} h"
        )


# ---------------------------------------------------------------------------
# Spec scenario 3 — 50 mA peripheral reduces life proportionally
# ---------------------------------------------------------------------------

class TestPeripheralImpact:
    def test_50mA_active_peripheral_reduces_life_proportionally(self):
        """
        Adding a 50 mA active-only peripheral to ESP32 (always-on):
          base life  = 3000 / 80  = 37.5 h
          with life  = 3000 / 130 ≈ 23.1 h
          ratio = 80 / 130 ≈ 0.615
        """
        base_model = PowerModel("ESP32", duty_cycle=1.0)
        with_model = PowerModel(
            "ESP32",
            peripherals=[Peripheral("Sensor", current_mA=50.0)],
            duty_cycle=1.0,
        )
        base_hours = battery_life(3000, 3.7, base_model)
        with_hours = battery_life(3000, 3.7, with_model)

        expected_ratio = 80.0 / 130.0
        actual_ratio   = with_hours / base_hours
        assert math.isclose(actual_ratio, expected_ratio, rel_tol=1e-6), (
            f"Expected ratio {expected_ratio:.4f}, got {actual_ratio:.4f}"
        )

    def test_50mA_always_on_peripheral_also_reduces_life(self):
        """always_on=True peripheral drains current in sleep too."""
        base_model = PowerModel("ESP32", duty_cycle=0.01)
        with_model = PowerModel(
            "ESP32",
            peripherals=[Peripheral("BLE chip", current_mA=50.0, always_on=True)],
            duty_cycle=0.01,
        )
        base_hours = battery_life(3000, 3.7, base_model)
        with_hours = battery_life(3000, 3.7, with_model)
        assert with_hours < base_hours, "Always-on peripheral should reduce battery life"

    def test_large_peripheral_dominates_at_high_duty(self):
        """A 500 mA motor peripheral should dominate the ESP32's 80 mA."""
        perip = Peripheral("Motor", current_mA=500.0)
        model = PowerModel("ESP32", peripherals=[perip], duty_cycle=1.0)
        hours = battery_life(3000, 3.7, model)
        # 3000 / 580 ≈ 5.17 h
        assert math.isclose(hours, 3000.0 / 580.0, rel_tol=0.01)

    def test_zero_current_peripheral_no_impact(self):
        """A 0 mA peripheral (e.g. placeholder) should not change life."""
        base = battery_life(3000, 3.7, PowerModel("ESP32", duty_cycle=1.0))
        with_zero = battery_life(
            3000, 3.7,
            PowerModel("ESP32", peripherals=[Peripheral("Empty", current_mA=0.0)], duty_cycle=1.0),
        )
        assert math.isclose(base, with_zero, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestBatteryLifeValidation:
    def test_zero_battery_mah_raises(self):
        model = PowerModel("ESP32")
        with pytest.raises(ValueError, match="battery_mAh must be > 0"):
            battery_life(battery_mAh=0, voltage=3.7, model=model)

    def test_negative_battery_mah_raises(self):
        model = PowerModel("ESP32")
        with pytest.raises(ValueError, match="battery_mAh must be > 0"):
            battery_life(battery_mAh=-100, voltage=3.7, model=model)

    def test_zero_voltage_raises(self):
        model = PowerModel("ESP32")
        with pytest.raises(ValueError, match="voltage must be > 0"):
            battery_life(battery_mAh=3000, voltage=0, model=model)

    def test_negative_voltage_raises(self):
        model = PowerModel("ESP32")
        with pytest.raises(ValueError, match="voltage must be > 0"):
            battery_life(battery_mAh=3000, voltage=-1, model=model)


# ---------------------------------------------------------------------------
# battery_life_from_energy()
# ---------------------------------------------------------------------------

class TestBatteryLifeFromEnergy:
    def test_wh_conversion_consistent_with_mah(self):
        """11.1 Wh / 3.7 V = 3000 mAh → same result as battery_life."""
        model = PowerModel("ESP32", duty_cycle=1.0)
        from_mah = battery_life(3000, 3.7, model)
        from_wh  = battery_life_from_energy(11.1, 3.7, model)
        assert math.isclose(from_mah, from_wh, rel_tol=1e-4)

    def test_zero_wh_raises(self):
        model = PowerModel("ESP32")
        with pytest.raises(ValueError, match="battery_Wh must be > 0"):
            battery_life_from_energy(0, 3.7, model)

    def test_negative_wh_raises(self):
        model = PowerModel("ESP32")
        with pytest.raises(ValueError, match="battery_Wh must be > 0"):
            battery_life_from_energy(-5, 3.7, model)


# ---------------------------------------------------------------------------
# Cross-board sanity
# ---------------------------------------------------------------------------

class TestCrossBoardBatteryLife:
    """Ensure all 15+ boards yield finite, positive battery-life estimates."""

    from kerf_firmware.power_profile.board_currents import BOARD_TABLE

    @pytest.mark.parametrize("board_name", list(BOARD_TABLE.keys()))
    def test_battery_life_finite_positive(self, board_name):
        model = PowerModel(board_name, duty_cycle=0.1)
        hours = battery_life(battery_mAh=1000, voltage=3.7, model=model)
        assert math.isfinite(hours), f"{board_name}: battery_life returned non-finite"
        assert hours > 0, f"{board_name}: battery_life returned non-positive"

    @pytest.mark.parametrize("board_name", list(BOARD_TABLE.keys()))
    def test_low_duty_longer_than_always_on(self, board_name):
        """For every board, 1% duty should be longer than always-on."""
        always_on = battery_life(1000, 3.7, PowerModel(board_name, duty_cycle=1.0))
        low_duty  = battery_life(1000, 3.7, PowerModel(board_name, duty_cycle=0.01))
        assert low_duty >= always_on, (
            f"{board_name}: low-duty life {low_duty:.1f} h should be >= always-on {always_on:.1f} h"
        )


# ---------------------------------------------------------------------------
# Different battery sizes
# ---------------------------------------------------------------------------

class TestBatterySizes:
    """Life scales linearly with battery capacity."""

    def test_double_capacity_doubles_life(self):
        model = PowerModel("ESP32", duty_cycle=1.0)
        h1 = battery_life(1000, 3.7, model)
        h2 = battery_life(2000, 3.7, model)
        assert math.isclose(h2, 2 * h1, rel_tol=1e-9)

    def test_small_coin_cell_300mah(self):
        model = PowerModel("ESP32-C3", duty_cycle=0.01)
        hours = battery_life(300, 3.0, model)
        assert hours > 0
        assert math.isfinite(hours)

    def test_large_lipo_pack(self):
        model = PowerModel("RP2040", duty_cycle=0.05)
        hours = battery_life(10_000, 3.7, model)
        assert hours > 0
        assert math.isfinite(hours)
