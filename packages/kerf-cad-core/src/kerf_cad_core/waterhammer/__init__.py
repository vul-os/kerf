"""
kerf_cad_core.waterhammer — Hydraulic transient (water hammer) analysis.

Distinct from:
  civil.hydraulics       — steady pressurised pipe network (Hardy-Cross)
  pumpsys/               — pump operating point / affinity laws
  channel/               — open-channel (free-surface) flow
  piping/                — pipe stress, supports, flexibility

This module covers:
  - Pressure-wave celerity (a) from fluid bulk modulus + pipe elasticity +
    restraint factor + entrained-gas correction
  - Joukowsky head-rise: instantaneous closure and slow closure (pipe period
    2L/a, rapid vs slow criterion)
  - Method-of-Characteristics (MOC) single-pipe solver — uniform reach,
    Courant time-step, upstream reservoir BC, downstream valve with
    linear/parabolic closure law τ(t), dead-end BC
  - Head and velocity envelopes (max/min vs position and time)
  - Minimum safe valve-closure time to limit surge
  - Pump-trip transient (simplified rigid-column rundown + check-valve slam)
  - Surge protection sizing: air vessel (rigid-column), surge tank (oscillation
    period + amplitude), relief valve flow
  - Column-separation flag (head < vapor pressure)

All computations are pure Python (math only; no OCC, numpy, or scipy).
Warnings are set on the returned dict; exceptions are never raised.

Public API:

    from kerf_cad_core.waterhammer import (
        wave_speed,
        joukowsky_head_rise,
        moc_single_pipe,
        safe_closure_time,
        pump_trip_simplified,
        air_vessel_sizing,
        surge_tank_oscillation,
        relief_valve_flow,
    )

References
----------
Wylie, E.B. & Streeter, V.L. (1993) Fluid Transients in Systems. Prentice Hall.
Chaudhry, M.H. (2014) Applied Hydraulic Transients, 3rd ed. Springer.
Streeter, V.L. & Wylie, E.B. (1967) Hydraulic Transients. McGraw-Hill.

Author: imranparuk
"""

from kerf_cad_core.waterhammer.transient import (
    wave_speed,
    joukowsky_head_rise,
    moc_single_pipe,
    safe_closure_time,
    pump_trip_simplified,
    air_vessel_sizing,
    surge_tank_oscillation,
    relief_valve_flow,
)

__all__ = [
    "wave_speed",
    "joukowsky_head_rise",
    "moc_single_pipe",
    "safe_closure_time",
    "pump_trip_simplified",
    "air_vessel_sizing",
    "surge_tank_oscillation",
    "relief_valve_flow",
]
