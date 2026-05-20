"""
kerf_cad_core.reverse_engineering.feature_map — Feature-type classification.

Maps a fitted primitive dict (from segmentation) to a canonical feature-type
label.  The full CAD feature ordering (boss/cut/slot, B-rep assembly) is
deferred pending OCC / NURBS surfacing (T-100/T-101).

Currently implemented:
    classify_primitive  — returns a simple string label from a segment dict.

Deferred:
    topology_order      — feature ordering / B-rep topology (depends on OCC).
    freeform_surface    — freeform / Class-A surface fitting (depends on NURBS).

Author: imranparuk
"""
from __future__ import annotations

from typing import Any


_LABELS: dict[str, str] = {
    "plane":    "analytic_plane",
    "sphere":   "analytic_sphere",
    "cylinder": "analytic_cylinder",
    "cone":     "analytic_cone",
    "torus":    "analytic_torus",
}


def classify_primitive(segment: dict[str, Any]) -> str:
    """Return a feature-type label for a fitted primitive segment.

    Parameters
    ----------
    segment : dict
        A segment dict as returned by extended_segment or greedy_segment.

    Returns
    -------
    str
        One of: analytic_plane, analytic_sphere, analytic_cylinder,
        analytic_cone, analytic_torus, or 'unknown' if the primitive
        is not recognised.
    """
    prim = segment.get("primitive", "")
    return _LABELS.get(prim, "unknown")
