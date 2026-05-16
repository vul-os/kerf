"""
kerf_cad_core.hydroturbine — hydropower plant engineering.

Pure-Python module (no OCC dependency) covering:
  - Gross/net head and hydraulic power  P = ρ·g·Q·H·η
  - Turbine-type selection from head, flow, and specific speed
    (Pelton / Turgo / Crossflow / Francis / Kaplan / Bulb)
  - Runner speed and synchronous-speed pole matching
  - Penstock diameter (economic velocity), Darcy-Weisbach friction head
    loss, wall thickness for internal pressure
  - Water-hammer pressure rise: Joukowsky & Allievi
  - Surge-tank sizing (simple cylindrical)
  - Draft-tube & Thoma cavitation sigma vs critical sigma
  - Runaway speed estimation
  - Flow-duration-curve → annual energy, capacity factor, plant factor
  - Pelton jet/bucket sizing
  - Micro-hydro quick sizing

Public API
----------
from kerf_cad_core.hydroturbine import (
    plant_power,
    turbine_type_selection,
    runner_speed,
    synchronous_speed_poles,
    penstock_diameter,
    penstock_friction_loss,
    penstock_wall_thickness,
    water_hammer_joukowsky,
    water_hammer_allievi,
    surge_tank_area,
    thoma_cavitation,
    runaway_speed,
    flow_duration_energy,
    pelton_jet_sizing,
    micro_hydro_quick,
)

References
----------
Çengel & Cimbala, "Fluid Mechanics" (4th ed.) — turbomachinery chapter
Warnick, "Hydropower Engineering", Prentice-Hall (1984)
IEC 60193 — Hydraulic turbines, storage pumps and pump-turbines
Gordon, J.L., "Hydraulic Turbine Efficiency" (1999), Can. J. Civ. Eng.
Moody, "Hydraulic Machinery" — draft-tube / Thoma sigma

Author: imranparuk
"""

from kerf_cad_core.hydroturbine.plant import (
    plant_power,
    turbine_type_selection,
    runner_speed,
    synchronous_speed_poles,
    penstock_diameter,
    penstock_friction_loss,
    penstock_wall_thickness,
    water_hammer_joukowsky,
    water_hammer_allievi,
    surge_tank_area,
    thoma_cavitation,
    runaway_speed,
    flow_duration_energy,
    pelton_jet_sizing,
    micro_hydro_quick,
)

__all__ = [
    "plant_power",
    "turbine_type_selection",
    "runner_speed",
    "synchronous_speed_poles",
    "penstock_diameter",
    "penstock_friction_loss",
    "penstock_wall_thickness",
    "water_hammer_joukowsky",
    "water_hammer_allievi",
    "surge_tank_area",
    "thoma_cavitation",
    "runaway_speed",
    "flow_duration_energy",
    "pelton_jet_sizing",
    "micro_hydro_quick",
]
