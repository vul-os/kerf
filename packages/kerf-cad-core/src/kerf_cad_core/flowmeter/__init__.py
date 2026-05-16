"""
kerf_cad_core.flowmeter — flow metering & flow-control sizing.

Public API (re-exported for convenience):

    from kerf_cad_core.flowmeter import (
        dp_meter,
        control_valve_liquid,
        control_valve_gas,
        control_valve_steam,
        prv_gas,
        prv_liquid,
        prv_steam,
        pitot_velocity,
        annubar_flow,
        v_notch_weir,
        rectangular_weir,
        parshall_flume,
        rotameter_scale,
        turndown_ratio,
    )

Distinct from:
  piping/      — B31.3 pipe stress
  civil/       — open-channel hydraulic networks
  pumpsys/     — pump selection & system curves
  pneumatics/  — compressed-air sizing

References
----------
ISO 5167-1/2/3:2003 — Differential-pressure meters
ISA-75.01.01-2007 / IEC 60534-2-1:2011 — Control-valve sizing
API 520 Part I (9th ed. 2014) — PRV sizing
API 526 (7th ed. 2017) — PRV designation letters

Author: imranparuk
"""

from kerf_cad_core.flowmeter.measure import (
    dp_meter,
    control_valve_liquid,
    control_valve_gas,
    control_valve_steam,
    prv_gas,
    prv_liquid,
    prv_steam,
    pitot_velocity,
    annubar_flow,
    v_notch_weir,
    rectangular_weir,
    parshall_flume,
    rotameter_scale,
    turndown_ratio,
)

__all__ = [
    "dp_meter",
    "control_valve_liquid",
    "control_valve_gas",
    "control_valve_steam",
    "prv_gas",
    "prv_liquid",
    "prv_steam",
    "pitot_velocity",
    "annubar_flow",
    "v_notch_weir",
    "rectangular_weir",
    "parshall_flume",
    "rotameter_scale",
    "turndown_ratio",
]
