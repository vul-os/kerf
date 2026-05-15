"""
kerf_cad_core.piping — ASME B31.3 process piping engineering calculations.

Public API (re-exported for convenience):

    from kerf_cad_core.piping import (
        required_wall_thickness,
        pressure_drop,
        allowable_span,
        thermal_expansion,
        guided_cantilever_leg,
        expansion_stress_check,
        schedule_lookup,
    )

Distinct from civil.hydraulics (potable-water network flow solver).
This module targets ASME B31.3 Process Piping: refinery, chemical plant,
and industrial process service.

References
----------
ASME B31.3-2022 — Process Piping
Crane Technical Paper 410 (TP-410) — Flow of Fluids Through Valves, Fittings and Pipe
MSS SP-69 — Pipe Hangers and Supports

Author: imranparuk
"""

from kerf_cad_core.piping.process import (
    required_wall_thickness,
    pressure_drop,
    allowable_span,
    thermal_expansion,
    guided_cantilever_leg,
    expansion_stress_check,
    schedule_lookup,
)

__all__ = [
    "required_wall_thickness",
    "pressure_drop",
    "allowable_span",
    "thermal_expansion",
    "guided_cantilever_leg",
    "expansion_stress_check",
    "schedule_lookup",
]
