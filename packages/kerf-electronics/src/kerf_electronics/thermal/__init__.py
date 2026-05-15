"""
kerf-electronics thermal sub-package.

Steady-state junction-temperature estimator for PCB components.

Public surface
--------------
  thermal_junction          — Tj = Ta + P * (θjc + θcs + θsa)
  thermal_heatsink_required — minimum θsa to keep Tj ≤ Tj_max
  thermal_board_report      — multi-component board hotspot rollup
  copper_spreading_resistance — first-order board copper-spreading θ
"""
from kerf_electronics.thermal.model import (
    ThermalComponent,
    ThermalResult,
    BoardThermalResult,
    ComponentBoardResult,
    thermal_junction,
    thermal_heatsink_required,
    copper_spreading_resistance,
    thermal_board_report,
)

__all__ = [
    "ThermalComponent",
    "ThermalResult",
    "BoardThermalResult",
    "ComponentBoardResult",
    "thermal_junction",
    "thermal_heatsink_required",
    "copper_spreading_resistance",
    "thermal_board_report",
]
