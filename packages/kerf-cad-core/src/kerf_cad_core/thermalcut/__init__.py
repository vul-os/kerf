"""
kerf_cad_core.thermalcut — thermal/abrasive cutting-process engineering.

Covers laser, plasma, oxyfuel, and abrasive-waterjet (AWJ) cutting processes.
Distinct from:
  cncfeeds/  — chip-forming machining (milling/drilling/turning feeds & speeds)
  turning/   — lathe cycle G-code generation
  nesting/   — sheet-layout nesting
  gcode/     — G-code post-processing

This module computes *process parameters* only:
  - Maximum cut speed vs material thickness & power (energy-balance model)
  - Kerf width and taper angle
  - Heat-affected zone (HAZ) width estimate
  - Pierce time and lead-in geometry
  - Edge quality / dross regime as a function of traverse speed
  - Gas / abrasive consumption rate and cost
  - Power / amperage selection for a given thickness
  - AWJ: orifice/mixing-tube sizing, abrasive flow, jet power, standoff,
         traverse speed from machinability number
  - Nozzle / standoff recommendations
  - Part cost roll-up: (cut length / speed + pierces × pierce_time) × machine_rate
                       + consumables
  - Cross-process comparison for a given material / thickness

Pure Python; no OCC dependency.

Public API (re-exported for convenience):

    from kerf_cad_core.thermalcut import (
        laser_cut_speed,
        plasma_cut_speed,
        oxyfuel_cut_speed,
        waterjet_cut_speed,
        kerf_width,
        taper_angle,
        haz_width,
        pierce_time,
        lead_in_length,
        edge_quality_regime,
        gas_consumption,
        abrasive_consumption,
        select_power,
        waterjet_params,
        part_cost,
        process_compare,
    )

References
----------
Steen & Mazumder, "Laser Material Processing", 4th ed., Springer 2010
Metcalfe & Quigley, ESAB Plasma Cutting Handbook, 3rd ed.
AWS C5.2 — Recommended Practices for Plasma Arc Cutting
OMAX Waterjet Cutting System Technical Reference, 2019
Hashish, M., "A Model for Abrasive-Waterjet Machining", J. Eng. for Ind. 1989
Cutting Technology, Fronius/Lincoln Electric gas-cutting guides

Author: imranparuk
"""

from kerf_cad_core.thermalcut.process import (
    laser_cut_speed,
    plasma_cut_speed,
    oxyfuel_cut_speed,
    waterjet_cut_speed,
    kerf_width,
    taper_angle,
    haz_width,
    pierce_time,
    lead_in_length,
    edge_quality_regime,
    gas_consumption,
    abrasive_consumption,
    select_power,
    waterjet_params,
    part_cost,
    process_compare,
)

__all__ = [
    "laser_cut_speed",
    "plasma_cut_speed",
    "oxyfuel_cut_speed",
    "waterjet_cut_speed",
    "kerf_width",
    "taper_angle",
    "haz_width",
    "pierce_time",
    "lead_in_length",
    "edge_quality_regime",
    "gas_consumption",
    "abrasive_consumption",
    "select_power",
    "waterjet_params",
    "part_cost",
    "process_compare",
]
