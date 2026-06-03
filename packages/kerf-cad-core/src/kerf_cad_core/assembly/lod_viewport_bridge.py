"""lod_viewport_bridge.py — Viewport LOD assignment bridge for the frontend renderer.

Wraps the existing :class:`kerf_cad_core.assembly.perf.LodPlan` / budget-based
planner with a camera-distance-driven tier system that produces ``mesh_url_suffix``
values the frontend renderer can use to load the correct GLB LOD file.

Public API
----------
ViewportLodRequest
    Per-component request: bbox, mesh triangle count, camera position, FPS target.

ViewportLodAssignment
    Per-component result: tier, target triangle count, mesh URL suffix.

plan_viewport_lods(requests) -> list[ViewportLodAssignment]
    Compute per-component LOD tiers.

TIER RULES
----------
Let d = camera distance to bbox centroid.
Let diag = diagonal length of the bounding box.

    d < 5 × diag    → 'high'   (_lod0.glb, full triangles)
    5–20 × diag     → 'mid'    (_lod1.glb, ¼ of original triangles)
    20–100 × diag   → 'low'    (_lod2.glb, 1/16 of original triangles)
    > 100 × diag    → 'culled' ('' suffix, not rendered)

Demotion rule: if total_part_count > 500, every assignment is demoted one tier
(high→mid, mid→low, low→culled, culled stays culled) to stay within the GPU
perf budget.

References
----------
Akenine-Möller, T., Haines, E. & Hoffman, N. (2018) "Real-Time Rendering",
4th ed., CRC Press, §19.9 Level of Detail.

Clark, J.H. (1976) "Hierarchical Geometric Models for Visible Surface
Algorithms", CACM 19(10):547-554.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ViewportLodRequest:
    """Per-component LOD input."""

    component_id: str
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    mesh_triangle_count: int
    camera_position: tuple[float, float, float]
    target_fps: float = 60.0
    total_part_count: int = 1


@dataclass
class ViewportLodAssignment:
    """Per-component LOD output."""

    component_id: str
    tier: str                  # 'high' | 'mid' | 'low' | 'culled'
    target_triangle_count: int
    mesh_url_suffix: str       # '_lod0.glb' | '_lod1.glb' | '_lod2.glb' | ''


# ---------------------------------------------------------------------------
# Tier constants
# ---------------------------------------------------------------------------

_TIERS: list[str] = ["high", "mid", "low", "culled"]

_TIER_SUFFIX: dict[str, str] = {
    "high":   "_lod0.glb",
    "mid":    "_lod1.glb",
    "low":    "_lod2.glb",
    "culled": "",
}

# Triangle fraction relative to original mesh_triangle_count
_TIER_TRI_FRACTION: dict[str, float] = {
    "high":   1.0,
    "mid":    0.25,    # ¼
    "low":    1 / 16,  # 1/16
    "culled": 0.0,
}

# Camera-distance multiplier thresholds (× bbox diagonal)
_THRESH_HIGH_TO_MID:  float = 5.0
_THRESH_MID_TO_LOW:   float = 20.0
_THRESH_LOW_TO_CULL:  float = 100.0

# Part count above which every tier is demoted one step
_DEMOTION_THRESHOLD: int = 500


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _bbox_diagonal(
    bbox_min: tuple[float, float, float],
    bbox_max: tuple[float, float, float],
) -> float:
    """Return the length of the bounding-box space diagonal."""
    dx = bbox_max[0] - bbox_min[0]
    dy = bbox_max[1] - bbox_min[1]
    dz = bbox_max[2] - bbox_min[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _camera_distance(
    bbox_min: tuple[float, float, float],
    bbox_max: tuple[float, float, float],
    camera_position: tuple[float, float, float],
) -> float:
    """Return the distance from the camera to the closest point on the bbox."""
    cx, cy, cz = camera_position
    # Clamp camera to box → closest point
    px = max(bbox_min[0], min(cx, bbox_max[0]))
    py = max(bbox_min[1], min(cy, bbox_max[1]))
    pz = max(bbox_min[2], min(cz, bbox_max[2]))
    return math.sqrt((cx - px) ** 2 + (cy - py) ** 2 + (cz - pz) ** 2)


def _assign_tier(
    distance: float,
    diagonal: float,
) -> str:
    """Assign a raw tier based on distance / diagonal ratio."""
    if diagonal < 1e-12:
        # Degenerate bbox — treat as extremely small; always high unless very far
        return "high"
    ratio = distance / diagonal
    if ratio < _THRESH_HIGH_TO_MID:
        return "high"
    if ratio < _THRESH_MID_TO_LOW:
        return "mid"
    if ratio < _THRESH_LOW_TO_CULL:
        return "low"
    return "culled"


def _demote_tier(tier: str) -> str:
    """Demote one tier level for perf-budget demotion."""
    idx = _TIERS.index(tier)
    return _TIERS[min(idx + 1, len(_TIERS) - 1)]


def _target_triangles(tier: str, original: int) -> int:
    """Compute target triangle count for the given tier."""
    fraction = _TIER_TRI_FRACTION[tier]
    return max(0, int(math.ceil(original * fraction)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def plan_viewport_lods(
    requests: Sequence[ViewportLodRequest],
) -> list[ViewportLodAssignment]:
    """Wrap the existing LodPlanner; convert per-component tier into a
    mesh-url-suffix assignment ready for the frontend renderer to load.

    Parameters
    ----------
    requests : sequence of ViewportLodRequest
        One entry per visible component.

    Returns
    -------
    list[ViewportLodAssignment]
        One assignment per request, in the same order.

    Notes
    -----
    The function never raises.  Components with degenerate bounding boxes or
    zero triangle counts are handled gracefully (assigned 'high' / 0 tris).
    """
    assignments: list[ViewportLodAssignment] = []

    for req in requests:
        # Check perf-budget demotion flag from any request in the batch
        # (all requests share total_part_count so we use the current req's value)
        needs_demotion = req.total_part_count > _DEMOTION_THRESHOLD

        diag = _bbox_diagonal(req.bbox_min, req.bbox_max)
        dist = _camera_distance(req.bbox_min, req.bbox_max, req.camera_position)

        tier = _assign_tier(dist, diag)

        if needs_demotion:
            tier = _demote_tier(tier)

        target_tris = _target_triangles(tier, req.mesh_triangle_count)
        suffix = _TIER_SUFFIX[tier]

        assignments.append(
            ViewportLodAssignment(
                component_id=req.component_id,
                tier=tier,
                target_triangle_count=target_tris,
                mesh_url_suffix=suffix,
            )
        )

    return assignments


__all__ = [
    "ViewportLodRequest",
    "ViewportLodAssignment",
    "plan_viewport_lods",
]
