"""
kerf_systems.components
=======================

Lumped-element component library.

Each component exposes:

    residuals(t, x, dx, params) -> list[float]

where x / dx are the full system state / derivative vectors
(components receive a *slice* view for their own variables).

For standalone use, each module also exposes factory helpers that return
``(residual_fn, n_vars, var_names, default_x0)`` tuples.

Domains
-------
  thermal    — ThermalMass, ThermalResistance, ThermalCapacitance,
               ThermalSource, TemperatureSensor
  hydraulic  — HydraulicOrifice, HydraulicPump, HydraulicTank,
               HydraulicResistance, HydraulicCapacitance
  electrical — Resistor, Capacitor, Inductor, VoltageSource,
               CurrentSource, Ground
  control    — PController, PIController, PIDController,
               Integrator, Gain, TransferFunction1
"""

from kerf_systems.components.thermal import (
    ThermalMass,
    ThermalResistance,
    ThermalCapacitance,
    ThermalSource,
    TemperatureSensor,
)
from kerf_systems.components.hydraulic import (
    HydraulicOrifice,
    HydraulicPump,
    HydraulicTank,
    HydraulicResistance,
    HydraulicCapacitance,
)
from kerf_systems.components.electrical import (
    Resistor,
    Capacitor,
    Inductor,
    VoltageSource,
    CurrentSource,
    Ground,
)
from kerf_systems.components.control import (
    PController,
    PIController,
    PIDController,
    Integrator,
    Gain,
    TransferFunction1,
)

__all__ = [
    "ThermalMass", "ThermalResistance", "ThermalCapacitance",
    "ThermalSource", "TemperatureSensor",
    "HydraulicOrifice", "HydraulicPump", "HydraulicTank",
    "HydraulicResistance", "HydraulicCapacitance",
    "Resistor", "Capacitor", "Inductor", "VoltageSource",
    "CurrentSource", "Ground",
    "PController", "PIController", "PIDController",
    "Integrator", "Gain", "TransferFunction1",
]
