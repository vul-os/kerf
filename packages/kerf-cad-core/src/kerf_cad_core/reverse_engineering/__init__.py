"""
kerf_cad_core.reverse_engineering — point-cloud reverse-engineering pipeline v2.

Sub-modules
-----------
io              Parse ASCII + binary PLY / PCD files into numpy-compatible lists.
noise           Pre-filtering: statistical outlier removal, bilateral/Laplacian smoothing.
fit_cone        Cone primitive: linear seed + Levenberg-Marquardt refinement.
fit_torus       Torus primitive: RANSAC-based algebraic fit.
segmentation    Extended sequential-RANSAC including cone + torus.
feature_map     Feature-type classification (plane/sphere/cylinder/cone/torus).
pipeline        High-level compose: load → filter → segment → map.

Deferred (OCC / NURBS required):
    Topology / feature ordering  — depends on T-100/T-101 NURBS kernel.
    Freeform / Class-A surfaces  — depends on NURBS surfacing (T-100).

Author: imranparuk
"""
from kerf_cad_core.reverse_engineering.io import (
    load_ply,
    load_pcd,
    UnsupportedFormatError,
)
from kerf_cad_core.reverse_engineering.noise import (
    statistical_outlier_removal,
    laplacian_smooth,
)
from kerf_cad_core.reverse_engineering.fit_cone import (
    fit_cone_direct,
    ransac_fit_cone,
    refine_cone_lm,
)
from kerf_cad_core.reverse_engineering.fit_torus import (
    fit_torus_direct,
    ransac_fit_torus,
)
from kerf_cad_core.reverse_engineering.segmentation import extended_segment
from kerf_cad_core.reverse_engineering.feature_map import classify_primitive
from kerf_cad_core.reverse_engineering.pipeline import run_pipeline

__all__ = [
    "load_ply",
    "load_pcd",
    "UnsupportedFormatError",
    "statistical_outlier_removal",
    "laplacian_smooth",
    "fit_cone_direct",
    "ransac_fit_cone",
    "refine_cone_lm",
    "fit_torus_direct",
    "ransac_fit_torus",
    "extended_segment",
    "classify_primitive",
    "run_pipeline",
]
