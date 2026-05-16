"""
kerf_cad_core.earthworks — site earthworks & grading calculations.

Pure-Python (math only).  Distinct from:
  geotech/    — bearing capacity, settlement, slope stability
  surveying/  — COGO / traverse / area
  civil/      — road horizontal/vertical alignment
  pavement/   — pavement structural design

Submodules
----------
grading   — cross-section areas, earthwork volumes, borrow-pit grid volumes,
             cut/fill balance, mass-haul diagram, compaction, slope/batter,
             trench excavation, dewatering pump rate
tools     — LLM tool wrappers registered with the Kerf tool registry

Public API (re-exported for convenience)
----------------------------------------

    from kerf_cad_core.earthworks import (
        # cross-section
        cross_section_level,
        cross_section_two_level,
        cross_section_three_level,
        cross_section_by_coords,
        # volumes
        earthwork_volume,
        borrow_pit_volume,
        # balance
        cut_fill_balance,
        # mass-haul
        mass_haul,
        # compaction
        proctor_optimum,
        relative_compaction,
        lift_productivity,
        # geometry
        slope_daylight_offset,
        # trench
        trench_volume,
        # dewatering
        dewatering_pump_rate,
    )

References
----------
USBR "Design of Small Canal Structures" (1978)
Schofield & Wroth, "Critical State Soil Mechanics" (1968)
AASHTO "Standard Specifications for Highway Bridges" (2002)
Peurifoy, Schexnayder, Shapira, "Construction Planning, Equipment &
  Methods", 8th ed.
ASTM D698 / D1557 — Proctor compaction test.

Author: imranparuk
"""
from __future__ import annotations

from kerf_cad_core.earthworks.grading import (
    cross_section_level,
    cross_section_two_level,
    cross_section_three_level,
    cross_section_by_coords,
    earthwork_volume,
    borrow_pit_volume,
    cut_fill_balance,
    mass_haul,
    proctor_optimum,
    relative_compaction,
    lift_productivity,
    slope_daylight_offset,
    trench_volume,
    dewatering_pump_rate,
)

__all__ = [
    "cross_section_level",
    "cross_section_two_level",
    "cross_section_three_level",
    "cross_section_by_coords",
    "earthwork_volume",
    "borrow_pit_volume",
    "cut_fill_balance",
    "mass_haul",
    "proctor_optimum",
    "relative_compaction",
    "lift_productivity",
    "slope_daylight_offset",
    "trench_volume",
    "dewatering_pump_rate",
]
