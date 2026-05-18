"""kerf-horology — watchmaking / horology plugin for Kerf.

Thin wrapper around the ``kerf_partsgen.generators.horology`` sub-package
that exposes LLM-callable tools for:

  * Swiss lever escapement geometry (escape wheel + pallet fork)
  * Gear-train wheel and pinion geometry
  * Mainspring barrel geometry
  * ``train_calculator`` — given target frequency + power reserve, computes
    the required gear-train ratio and a factored wheel/pinion solution

Public re-exports
-----------------
From ``kerf_partsgen.generators.horology``:

  involute_profile(module, num_teeth, pressure_angle_deg, n_points)
      → list[ProfilePoint]

  check_involute_profile(module, num_teeth, ...) → InvoluteCheckResult

From ``kerf_partsgen.generators.horology.train_calculator``:

  compute_train_ratio(freq_hz, power_reserve_hours, ...) → TrainSpec
  factorise_ratio(ratio, n_stages, ...)                   → list[TrainStage]

See ``llm_docs/horology.md`` for LLM tool documentation.
"""

__version__ = "0.1.0"

from kerf_partsgen.generators.horology.involute import (  # noqa: F401
    involute_profile,
    check_involute_profile,
    InvoluteCheckResult,
    ProfilePoint,
)
from kerf_partsgen.generators.horology.train_calculator import (  # noqa: F401
    compute_train_ratio,
    factorise_ratio,
    TrainSpec,
    TrainStage,
)

__all__ = [
    "__version__",
    "involute_profile",
    "check_involute_profile",
    "InvoluteCheckResult",
    "ProfilePoint",
    "compute_train_ratio",
    "factorise_ratio",
    "TrainSpec",
    "TrainStage",
]
