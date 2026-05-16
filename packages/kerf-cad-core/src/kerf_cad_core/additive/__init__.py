"""
kerf_cad_core.additive — additive-manufacturing process planning / DFAM.

Distinct from ``kerf_cad_core.injection`` (plastic injection moulding),
``kerf_cad_core.casting`` (metal sand/investment casting), and the
kerf-slicing G-code pipeline.

Public API (re-exported for convenience):

    from kerf_cad_core.additive import (
        process_params,
        build_time_estimate,
        support_volume,
        overhang_removability,
        orientation_cost,
        best_orientation,
        shrinkage_compensation,
        lattice_infill,
        feature_checks,
        cost_rollup,
        nesting_packing,
    )

Supported processes: FDM, SLA, SLS, MJF, DMLS.

References
----------
Gibson, I., Rosen, D. & Stucker, B. "Additive Manufacturing Technologies", 2nd ed.
Gibson, L.J. & Ashby, M.F. "Cellular Solids", 2nd ed.
EOS GmbH application notes (SLS/DMLS build-rate data).
Materialise & Formlabs process guides.

Author: imranparuk
"""

from kerf_cad_core.additive.dfam import (
    process_params,
    build_time_estimate,
    support_volume,
    overhang_removability,
    orientation_cost,
    best_orientation,
    shrinkage_compensation,
    lattice_infill,
    feature_checks,
    cost_rollup,
    nesting_packing,
)

__all__ = [
    "process_params",
    "build_time_estimate",
    "support_volume",
    "overhang_removability",
    "orientation_cost",
    "best_orientation",
    "shrinkage_compensation",
    "lattice_infill",
    "feature_checks",
    "cost_rollup",
    "nesting_packing",
]
