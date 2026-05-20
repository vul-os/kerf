"""
kerf_cad_core.reverse_engineering.segmentation — Extended sequential RANSAC.

Extends the v1 scan/fit.py greedy_segment with:
  - cone   primitive (using ransac_fit_cone with LM refinement)
  - torus  primitive (using ransac_fit_torus)

All five primitives: plane / sphere / cylinder / cone / torus.

The segmentation loop is identical to v1 greedy_segment: iteratively peel off
the dominant primitive from the remaining point cloud until no primitive
achieves ≥ min_inlier_ratio of remaining points.

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any

from kerf_cad_core.scan.fit import (
    ransac_fit_plane,
    ransac_fit_sphere,
    ransac_fit_cylinder,
    _dist_to_plane,
    _dist_to_sphere,
    _dist_to_cylinder,
)
from kerf_cad_core.reverse_engineering.fit_cone import ransac_fit_cone, _dist_to_cone
from kerf_cad_core.reverse_engineering.fit_torus import ransac_fit_torus, _dist_fn as _dist_to_torus_fn


# ---------------------------------------------------------------------------
# Extended segmentation
# ---------------------------------------------------------------------------

_ALL_PRIMITIVES = ("plane", "sphere", "cylinder", "cone", "torus")


def _try_fit_ext(
    pts: list[list[float]],
    kind: str,
    threshold: float,
    seed: int,
) -> dict[str, Any]:
    if kind == "plane":
        return ransac_fit_plane(pts, threshold=threshold, seed=seed)
    if kind == "sphere":
        return ransac_fit_sphere(pts, threshold=threshold, seed=seed)
    if kind == "cylinder":
        return ransac_fit_cylinder(pts, threshold=threshold, seed=seed)
    if kind == "cone":
        return ransac_fit_cone(pts, threshold=threshold, seed=seed)
    if kind == "torus":
        return ransac_fit_torus(pts, threshold=threshold, seed=seed)
    return {"ok": False, "reason": f"unknown primitive: {kind}"}


def _dist_ext(
    p: list[float],
    kind: str,
    res: dict[str, Any],
    threshold: float,
) -> float:
    if kind == "plane":
        return _dist_to_plane(p, res["normal"], res["d"])
    if kind == "sphere":
        return _dist_to_sphere(p, res["centre"], res["radius"])
    if kind == "cylinder":
        return _dist_to_cylinder(p, res["axis"], res["axis_point"], res["radius"])
    if kind == "cone":
        return _dist_to_cone(p, res)
    if kind == "torus":
        return _dist_to_torus_fn(p, res)
    return float("inf")


def extended_segment(
    pts: list[list[float]],
    primitives: list[str] | None = None,
    threshold: float = 0.01,
    min_inlier_ratio: float = 0.1,
    seed: int = 42,
) -> dict[str, Any]:
    """Greedy multi-primitive segmentation (plane/sphere/cylinder/cone/torus).

    Iteratively finds the dominant primitive in the remaining unassigned cloud
    and peels it off, until no primitive achieves ≥ min_inlier_ratio of
    remaining points.

    Parameters
    ----------
    pts : list of [x,y,z]
    primitives : list of str | None
        Which types to search.  Default: all five.
    threshold : float
        Inlier distance threshold.
    min_inlier_ratio : float
        Minimum fraction of remaining points a primitive must claim.
    seed : int
        Random seed.

    Returns
    -------
    dict — ok, segments, unassigned_count, total_count.
    Each segment: {primitive, inlier_count, residual, ...fit params...}.
    """
    if primitives is None:
        primitives = list(_ALL_PRIMITIVES)

    if len(pts) < 3:
        return {"ok": False, "reason": f"need ≥3 points to segment; got {len(pts)}"}

    remaining = [list(p) for p in pts]
    total = len(pts)
    segments: list[dict] = []

    while len(remaining) >= 3:
        best_fit: dict[str, Any] | None = None
        best_inliers: list[list[float]] = []
        best_kind = ""

        for kind in primitives:
            # Minimum point requirements per primitive type
            min_pts = {"plane": 3, "sphere": 4, "cylinder": 6, "cone": 6, "torus": 7}
            if len(remaining) < min_pts.get(kind, 3):
                continue
            res = _try_fit_ext(remaining, kind, threshold, seed)
            if not res.get("ok"):
                continue
            inliers = [p for p in remaining if _dist_ext(p, kind, res, threshold) <= threshold]
            if len(inliers) > len(best_inliers):
                best_fit = res
                best_kind = kind
                best_inliers = inliers

        if best_fit is None or len(best_inliers) < min_inlier_ratio * len(remaining):
            break

        seg: dict[str, Any] = {
            "primitive": best_kind,
            "inlier_count": len(best_inliers),
            "residual": best_fit.get("residual", 0.0),
        }
        # Copy fit-specific params
        for key in ("normal", "d", "centre", "radius", "axis", "axis_point",
                    "apex", "half_angle", "R", "r"):
            if key in best_fit:
                seg[key] = best_fit[key]

        segments.append(seg)

        inlier_set = {id(p) for p in best_inliers}
        remaining = [p for p in remaining if id(p) not in inlier_set]

    return {
        "ok": True,
        "segments": segments,
        "unassigned_count": len(remaining),
        "total_count": total,
    }
