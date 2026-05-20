"""
kerf_cad_core.reverse_engineering.pipeline — High-level reverse-engineering pipeline.

run_pipeline(pts, ...) -> dict
    1. Pre-filter noise (statistical outlier removal)
    2. Segment into primitives (extended_segment)
    3. Classify each segment (classify_primitive)

Author: imranparuk
"""
from __future__ import annotations

from typing import Any

from kerf_cad_core.reverse_engineering.noise import statistical_outlier_removal
from kerf_cad_core.reverse_engineering.segmentation import extended_segment
from kerf_cad_core.reverse_engineering.feature_map import classify_primitive


def run_pipeline(
    pts: list[list[float]],
    filter_k: int = 8,
    filter_n_sigma: float = 2.0,
    primitives: list[str] | None = None,
    threshold: float = 0.01,
    min_inlier_ratio: float = 0.1,
    seed: int = 42,
    skip_filter: bool = False,
) -> dict[str, Any]:
    """Run the full reverse-engineering pipeline.

    Steps
    -----
    1. Statistical outlier removal (unless skip_filter=True).
    2. Extended sequential-RANSAC segmentation.
    3. Feature-type classification of each segment.

    Parameters
    ----------
    pts : list of [x,y,z]
    filter_k : int
        kNN count for outlier filter.
    filter_n_sigma : float
        Sigma threshold for outlier filter.
    primitives : list[str] | None
        Which primitive types to attempt.
    threshold : float
        RANSAC inlier threshold.
    min_inlier_ratio : float
        Minimum inlier fraction per segment.
    seed : int
        Random seed.
    skip_filter : bool
        If True, skip the noise pre-filter step.

    Returns
    -------
    dict with keys:
        ok           : bool
        input_count  : int
        filtered_count : int
        outlier_count  : int
        segments       : list of enriched segment dicts (adds 'feature_type')
        unassigned_count : int
        total_count    : int
    """
    if len(pts) < 3:
        return {"ok": False, "reason": f"need ≥3 points; got {len(pts)}"}

    # Step 1: filter
    if skip_filter:
        filtered = [list(p) for p in pts]
        outlier_indices: list[int] = []
    else:
        filtered, outlier_indices = statistical_outlier_removal(pts, k=filter_k, n_sigma=filter_n_sigma)

    if len(filtered) < 3:
        return {
            "ok": False,
            "reason": "too few points remain after filtering",
            "input_count": len(pts),
            "filtered_count": len(filtered),
            "outlier_count": len(outlier_indices),
        }

    # Step 2: segment
    seg_result = extended_segment(
        filtered,
        primitives=primitives,
        threshold=threshold,
        min_inlier_ratio=min_inlier_ratio,
        seed=seed,
    )
    if not seg_result.get("ok"):
        return {
            "ok": False,
            "reason": seg_result.get("reason", "segmentation failed"),
            "input_count": len(pts),
            "filtered_count": len(filtered),
            "outlier_count": len(outlier_indices),
        }

    # Step 3: classify
    segments = seg_result["segments"]
    for seg in segments:
        seg["feature_type"] = classify_primitive(seg)

    return {
        "ok": True,
        "input_count": len(pts),
        "filtered_count": len(filtered),
        "outlier_count": len(outlier_indices),
        "segments": segments,
        "unassigned_count": seg_result["unassigned_count"],
        "total_count": seg_result["total_count"],
    }
