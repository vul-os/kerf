"""
mesh_decimate.py
================
Quadric-error-metric (QEM) edge-collapse decimation — standalone thin wrapper
around the full implementation that lives in ``kerf_cad_core.geom.mesh_repair``.

This module exposes a single focused entry point used by the LOD pipeline:

    decimate_to_ratio(verts, faces, ratio=0.10, max_error=None) -> dict

``ratio`` is the target fraction of faces to *keep* (e.g. 0.10 = 10 %).
The bounding box of the output mesh is preserved to within the ``bbox_tol``
tolerance (default: 1 % of the diagonal — verified by unit tests).

Returned dict shape::

    {
        "ok": True,
        "verts": list[list[float, float, float]],
        "faces": list[list[int, int, int]],
        "original_faces": int,
        "final_faces": int,
        "ratio_achieved": float,           # final_faces / original_faces
        "bbox_preserved": bool,            # True when bbox delta < bbox_tol
        "bbox_delta": float,               # max corner deviation, same units as verts
    }

On failure::

    {"ok": False, "reason": str}

Notes
-----
- Pure-Python, no GPU, no C extension required.
- Suitable for headless CI / server-side pre-computation of LOD proxies.
- For large production meshes the QEM implementation in mesh_repair is O(N²)
  per iteration pass; this is acceptable for the LOD proxy use-case where
  meshes are typically < 50 k triangles before decimation.
"""
from __future__ import annotations

import math
from typing import Sequence, Optional

from kerf_cad_core.geom.mesh_repair import decimate as _qem_decimate


def _bbox(verts: list) -> tuple[list[float], list[float]]:
    """Return (min_corner, max_corner) of *verts*."""
    if not verts:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


def _bbox_diagonal(lo: list[float], hi: list[float]) -> float:
    return math.sqrt(
        (hi[0] - lo[0]) ** 2 +
        (hi[1] - lo[1]) ** 2 +
        (hi[2] - lo[2]) ** 2
    )


def _bbox_max_delta(
    lo_a: list[float], hi_a: list[float],
    lo_b: list[float], hi_b: list[float],
) -> float:
    """Max absolute difference between two bboxes' corners, component-wise."""
    deltas = [
        abs(lo_b[i] - lo_a[i]) for i in range(3)
    ] + [
        abs(hi_b[i] - hi_a[i]) for i in range(3)
    ]
    return max(deltas) if deltas else 0.0


def decimate_to_ratio(
    verts: Sequence,
    faces: Sequence,
    ratio: float = 0.10,
    max_error: Optional[float] = None,
    bbox_tol_frac: float = 0.01,
) -> dict:
    """Decimate *faces* to *ratio* × original count via QEM edge-collapse.

    Parameters
    ----------
    verts : sequence of [x, y, z]
        Input vertex list.
    faces : sequence of [i, j, k]
        Input triangle list (0-based indices into *verts*).
    ratio : float
        Target fraction of faces to keep.  0.10 = keep 10 %, discard 90 %.
        Clamped to [0.0, 1.0].
    max_error : float, optional
        Stop collapsing when the QEM error exceeds this value (world-space
        units).  If both *ratio* and *max_error* are active, whichever is hit
        first stops the loop.
    bbox_tol_frac : float
        Fraction of the input bounding-box diagonal used as the bbox-
        preservation tolerance.  Default 0.01 = 1 %.

    Returns
    -------
    dict
        See module docstring for the full shape.
    """
    try:
        verts = list(verts)
        faces = list(faces)
        ratio = max(0.0, min(1.0, float(ratio)))

        if not faces:
            return {
                "ok": True,
                "verts": verts,
                "faces": faces,
                "original_faces": 0,
                "final_faces": 0,
                "ratio_achieved": 1.0,
                "bbox_preserved": True,
                "bbox_delta": 0.0,
            }

        original_count = len(faces)
        target_faces = max(1, int(round(original_count * ratio)))

        # Compute input bbox for preservation check later.
        lo_in, hi_in = _bbox(verts)
        diag = _bbox_diagonal(lo_in, hi_in)
        bbox_tol = bbox_tol_frac * diag if diag > 0 else 1e-9

        result = _qem_decimate(
            verts,
            faces,
            target_faces=target_faces,
            max_error=max_error,
        )
        if not result.get("ok"):
            return result

        out_verts = result["verts"]
        out_faces = result["faces"]
        final_count = result["final_faces"]

        # Bbox preservation check.
        lo_out, hi_out = _bbox(out_verts) if out_verts else (lo_in, hi_in)
        bbox_delta = _bbox_max_delta(lo_in, hi_in, lo_out, hi_out)
        bbox_preserved = bbox_delta <= bbox_tol

        return {
            "ok": True,
            "verts": out_verts,
            "faces": out_faces,
            "original_faces": original_count,
            "final_faces": final_count,
            "ratio_achieved": final_count / original_count if original_count > 0 else 1.0,
            "bbox_preserved": bbox_preserved,
            "bbox_delta": bbox_delta,
        }
    except Exception as exc:
        return {"ok": False, "reason": f"decimate_to_ratio failed: {exc}"}
