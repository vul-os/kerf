"""
kerf_cad_core.elecpower — NEC building/industrial electrical power distribution.

Scope: building-scale NEC distribution (Art. 220, 240, 250, 310, 430, 450).
Distinct from elecsafety/ (device creepage/arc-flash), protection/, and pdn/.

Public API (re-exported for convenience):

    from kerf_cad_core.elecpower import (
        demand_load,
        conductor_ampacity,
        conductor_size_for_load,
        voltage_drop,
        conduit_fill,
        overcurrent_device_size,
        motor_branch_circuit,
        transformer_feeder_size,
        short_circuit_analysis,
        power_factor_correction,
        grounding_conductor_size,
        panel_schedule_rollup,
        generator_ups_size,
    )

References
----------
NFPA 70 (NEC) 2023:
  Art. 220 — Branch-Circuit, Feeder, and Service Load Calculations
  Art. 240 — Overcurrent Protection
  Art. 250 — Grounding and Bonding
  Art. 310 — Conductors for General Wiring
  Art. 430 — Motors, Motor Circuits, and Controllers
  Art. 450 — Transformers and Transformer Vaults

Author: imranparuk
"""

from kerf_cad_core.elecpower.distribution import (
    demand_load,
    conductor_ampacity,
    conductor_size_for_load,
    voltage_drop,
    conduit_fill,
    overcurrent_device_size,
    motor_branch_circuit,
    transformer_feeder_size,
    short_circuit_analysis,
    power_factor_correction,
    grounding_conductor_size,
    panel_schedule_rollup,
    generator_ups_size,
)

__all__ = [
    "demand_load",
    "conductor_ampacity",
    "conductor_size_for_load",
    "voltage_drop",
    "conduit_fill",
    "overcurrent_device_size",
    "motor_branch_circuit",
    "transformer_feeder_size",
    "short_circuit_analysis",
    "power_factor_correction",
    "grounding_conductor_size",
    "panel_schedule_rollup",
    "generator_ups_size",
]
