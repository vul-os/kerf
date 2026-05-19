"""
kerf_firmware.power_profile
===========================

Power-profile estimation for embedded firmware projects.

Public API
----------
PowerModel   — duty-cycle aware average-current estimator.
battery_life — convenience wrapper: mAh + voltage → runtime hours.

Quick example::

    from kerf_firmware.power_profile import PowerModel
    from kerf_firmware.power_profile.battery_life import battery_life

    model = PowerModel(board="ESP32", duty_cycle=0.01)
    hours = battery_life(battery_mAh=3000, voltage=3.7, model=model)
    print(f"{hours:.0f} h")          # ~3 700 h
"""

from .model import PowerModel
from .battery_life import battery_life

__all__ = ["PowerModel", "battery_life"]
