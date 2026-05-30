"""face_planarity.py -- BREP-FACE-PLANARITY-CHECK

Determine if a B-rep Face is planar (within a tolerance), fit the
best-fit plane via SVD, and report the maximum out-of-plane deviation
and a 0-to-1 planarity score.

Algorithm
---------
1. Sample the face surface uniformly on a samples x samples grid in
   (u, v) space spanning the full UV domain of the underlying surface.
2. Compute the centroid of all sample points.
3. Centre the point cloud and form the 3 x N data matrix; compute the
   thin SVD.  The right singular vector corresponding to the smallest
   singular value is the normal of the best-fit plane
   (Pratt 1987 s3; Eberly, Geometric Tools, s6.6).
4. Measure the signed distances of all sample points from the plane;
   record max_deviation = max |d_i|.
5. Compute planarity_score = max_deviation / bbox_diagonal.
6. Compare max_deviation against tolerance (default 1e-4 * bbox_diagonal).

Honest flag / v1 caveat: full UV-domain sampling -- inner trim loops
(holes) are NOT excluded. The fit may be biased for faces with large
inner voids. Will be fixed in v2 with loop-aware UV sampling.

References
----------
Pratt, V. (1987). Direct least-squares fitting of algebraic surfaces.
SIGGRAPH Computer Graphics, 21(4), 145-152.
Eberly, D. (2020). Geometric Tools for Computer Graphics, s6.6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Face

__all__ = [
    "PlanarityReport",
    "check_face_planarity",
]


@dataclass
class PlanarityReport:
    """Result of a face planarity check."""

    is_planar: bool
    plane_origin: Optional[np.ndarray]
    plane_normal: Optional[np.ndarray]
    max_deviation: float
    planarity_score: float
    tolerance: float
    samples_used: int
    caveat: str = (
        "v1: full UV-domain sampling -- trimmed inner loops (holes) are NOT "
        "excluded; plane fit may be slightly biased for faces with large inner voids."
    )


def _surface_uv_domain(surface) -> Tuple[float, float, float, float]:
    knots_u = getattr(surface, "knots_u", None)
    knots_v = getattr(surface, "knots_v", None)
    if knots_u is not None and knots_v is not None:
        u_min = float(knots_u[0])
        u_max = float(knots_u[-1])
        v_min = float(knots_v[0])
        v_max = float(knots_v[-1])
        if u_max <= u_min:
            u_min, u_max = 0.0, 1.0
        if v_max <= v_min:
            v_min, v_max = 0.0, 1.0
        return u_min, u_max, v_min, v_max
    return 0.0, 1.0, 0.0, 1.0


def _sample_surface_points(surface, samples: int) -> np.ndarray:
    u_min, u_max, v_min, v_max = _surface_uv_domain(surface)
    us = np.linspace(u_min, u_max, samples)
    vs = np.linspace(v_min, v_max, samples)
    pts = []
    for u in us:
        for v in vs:
            try:
                p = surface.evaluate(float(u), float(v))
                p = np.asarray(p, dtype=float).ravel()
                if p.shape == (3,) and np.all(np.isfinite(p)):
                    pts.append(p)
            except Exception:
                pass
    if not pts:
        return np.empty((0, 3), dtype=float)
    return np.array(pts, dtype=float)


def _bbox_diagonal(pts: np.ndarray) -> float:
    if pts.shape[0] < 2:
        return 0.0
    mn = pts.min(axis=0)
    mx = pts.max(axis=0)
    return float(np.linalg.norm(mx - mn))


def _fit_plane_svd(pts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Fit best-fit plane via SVD (Pratt 1987 s3; Eberly s6.6)."""
    centroid = pts.mean(axis=0)
    centred = pts - centroid
    _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    normal = vt[-1]
    norm_len = np.linalg.norm(normal)
    if norm_len < 1e-14:
        normal = np.array([0.0, 0.0, 1.0])
    else:
        normal = normal / norm_len
    return centroid, normal


def check_face_planarity(
    face: Face,
    tolerance: Optional[float] = None,
    samples: int = 10,
) -> PlanarityReport:
    """Check whether a B-rep face is planar within a given tolerance.

    Parameters
    ----------
    face : Face
        B-rep face whose surface implements evaluate(u, v) -> (3,) array.
    tolerance : float or None
        Max allowed out-of-plane deviation for is_planar=True.
        Default: 1e-4 * bbox_diagonal; or 1e-9 for degenerate faces.
    samples : int
        Grid points per UV axis. Total = samples**2. Default 10. Min 2.

    Returns
    -------
    PlanarityReport
    """
    samples = max(samples, 2)
    surface = face.surface
    pts = _sample_surface_points(surface, samples)

    if pts.shape[0] < 3:
        tol_used = tolerance if tolerance is not None else 1e-9
        return PlanarityReport(
            is_planar=True,
            plane_origin=pts[0] if pts.shape[0] == 1 else np.zeros(3),
            plane_normal=np.array([0.0, 0.0, 1.0]),
            max_deviation=0.0,
            planarity_score=0.0,
            tolerance=tol_used,
            samples_used=pts.shape[0],
        )

    bbox_diag = _bbox_diagonal(pts)
    if tolerance is None:
        tolerance = 1e-4 * bbox_diag if bbox_diag > 0.0 else 1e-9

    centroid, normal = _fit_plane_svd(pts)
    deviations = (pts - centroid) @ normal
    max_deviation = float(np.max(np.abs(deviations)))
    planarity_score = max_deviation / bbox_diag if bbox_diag > 0.0 else 0.0
    is_planar = max_deviation <= tolerance

    return PlanarityReport(
        is_planar=is_planar,
        plane_origin=centroid,
        plane_normal=normal,
        max_deviation=max_deviation,
        planarity_score=planarity_score,
        tolerance=tolerance,
        samples_used=pts.shape[0],
    )
