"""kerf-manufacturing: manufacturing process simulation plugins for Kerf.

v1 ships:
  - Injection-moulding fill simulation (Hele-Shaw approximation)
  - CAM feed-rate optimizer (Altintas 2012 chip-load + machine dynamics + deflection)

Out of scope for v1 (planned follow-up tickets):
- Residual stress & warpage prediction
- Fibre orientation (Folgar-Tucker model)
- Cooling-circuit optimisation
- Packing / hold-pressure phase
"""

from kerf_manufacturing.moldflow import (
    ShellMesh,
    GateLocation,
    CrossWLFCard,
    InjectionConditions,
    MoldFlowResult,
    run_moldflow,
)
from kerf_manufacturing.feed_rate import (
    compute_recommended_feed,
    optimize_toolpath_feed,
    estimate_cycle_time,
    OptimizedSegment,
)

__all__ = [
    # Moldflow
    "ShellMesh",
    "GateLocation",
    "CrossWLFCard",
    "InjectionConditions",
    "MoldFlowResult",
    "run_moldflow",
    # Feed-rate optimizer
    "compute_recommended_feed",
    "optimize_toolpath_feed",
    "estimate_cycle_time",
    "OptimizedSegment",
]
