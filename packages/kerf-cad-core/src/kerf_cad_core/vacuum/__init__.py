"""
kerf_cad_core.vacuum — vacuum-system design & analysis.

Distinct from:
  kerf_cad_core.pneumatics  — compressed-air / positive-pressure pneumatics
  kerf_cad_core.fluidpower  — hydraulic (incompressible) fluid-power
  kerf_cad_core.pumpsys     — centrifugal pump selection & operating point

This module covers the physics and engineering of vacuum systems:
flow-regime classification (Knudsen number), conductance of orifices and
tubes in molecular/viscous/transitional regimes, series/parallel conductance
networks, effective pumping speed at the chamber, pump-down time (volume +
surface-outgassing two-phase model), ultimate pressure, gas throughput,
outgassing rate, leak specification, mean free path, monolayer formation
time, and multi-stage pump matching.

Public API (re-exported for convenience):

    from kerf_cad_core.vacuum import (
        flow_regime,
        conductance_orifice,
        conductance_tube,
        conductance_series,
        conductance_parallel,
        effective_pumping_speed,
        pump_down_time,
        ultimate_pressure,
        gas_throughput,
        outgassing_rate,
        leak_rate_spec,
        rate_of_rise,
        mean_free_path,
        monolayer_time,
        pump_stage_match,
    )

References
----------
O'Hanlon, J.F., "A User's Guide to Vacuum Technology", 3rd ed., Wiley (2003).
Lafferty, J.M. (ed.), "Foundations of Vacuum Science and Technology",
  Wiley (1998).
Jousten, K. (ed.), "Handbook of Vacuum Technology", Wiley-VCH (2016).
Leybold Vacuum — Full-Line Catalogue (2019).
Knudsen, M., Ann. Phys. 28 (1909) 75–130.

Author: imranparuk
"""

from kerf_cad_core.vacuum.system import (
    flow_regime,
    conductance_orifice,
    conductance_tube,
    conductance_series,
    conductance_parallel,
    effective_pumping_speed,
    pump_down_time,
    ultimate_pressure,
    gas_throughput,
    outgassing_rate,
    leak_rate_spec,
    rate_of_rise,
    mean_free_path,
    monolayer_time,
    pump_stage_match,
)

__all__ = [
    "flow_regime",
    "conductance_orifice",
    "conductance_tube",
    "conductance_series",
    "conductance_parallel",
    "effective_pumping_speed",
    "pump_down_time",
    "ultimate_pressure",
    "gas_throughput",
    "outgassing_rate",
    "leak_rate_spec",
    "rate_of_rise",
    "mean_free_path",
    "monolayer_time",
    "pump_stage_match",
]
