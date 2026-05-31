"""kerf_cad_core.subd — Catmull-Clark SubD limit-surface analysis utilities.

This subpackage collects higher-level SubD operations that build on the
foundational evaluators in ``kerf_cad_core.geom.subd`` and
``kerf_cad_core.geom.subd_stam``.

Modules
-------
limit_walk_cross_curve
    SUBD-LIMIT-WALK-CROSS-CURVE: walk a parametric path on the CC limit
    surface and intersect with a planar cut (Stam 1998 evaluator + 5-iter
    bisection refinement).
edge_loop_select
    SUBD-CAGE-EDGE-LOOP-SELECT: directional edge-loop walk on a quad cage;
    stops at irregular vertex (valence≠4) or loop closure
    (Bommes-Lévy-Pietroni 2013 §3.2).
limit_normal_fit
    SUBD-LIMIT-NORMAL-FIT: sample the CC limit-surface normal n̂(u,v) at
    a uniform (u,v) grid on each cage face using Stam (1998) exact tangents;
    compute residuals vs bilinear face-corner approximation for shading use.
"""

from kerf_cad_core.subd.limit_walk_cross_curve import (
    CrossCurveResult,
    walk_subd_limit_cross_plane,
)
from kerf_cad_core.subd.edge_loop_select import (
    EdgeLoopResult,
    select_edge_loop,
)
from kerf_cad_core.subd.limit_normal_fit import (
    LimitNormalFitResult,
    sample_subd_limit_normals,
)

__all__ = [
    "CrossCurveResult",
    "walk_subd_limit_cross_plane",
    "EdgeLoopResult",
    "select_edge_loop",
    "LimitNormalFitResult",
    "sample_subd_limit_normals",
]
