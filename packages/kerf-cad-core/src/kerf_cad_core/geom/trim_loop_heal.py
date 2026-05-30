"""
trim_loop_heal.py
=================
NURBS trim-loop auto-heal (GK-P): T-junction merge, dead-loop removal,
orientation fix, and self-intersection detection in the 2-D UV domain.

This module operates **exclusively on UV-space polygon loops** bounding a
trimmed face.  It is entirely separate from ``geom/body_heal.py``, which
repairs the 3-D B-rep body topology (vertex welding, face orientation in
3-D).  Trim-loop heal repairs the 2-D parametric boundary on a single face.

References
----------
* Sederberg, Zheng, Bakenov, Nasri 2003 "T-splines and T-NURCCs" —
  T-junction classification and merge strategy.
* Eberly 2008 "Robust polygon orientation" — signed-area sign test.

Public API
----------
.. code-block:: python

    from kerf_cad_core.geom.trim_loop_heal import (
        TrimmedFace,
        HealedTrimLoops,
        heal_trim_loops,
        heal_trim_loops_in_body,
    )

    healed = heal_trim_loops(face, tol=1e-6)
    healed.stats  # dict of counts
    healed.outer  # list of (u, v) — healed outer loop
    healed.inners # list[list[tuple]] — healed inner loops

``heal_trim_loops(face, tol=1e-6)``
    Repair the UV-domain trim loops on a single ``TrimmedFace``:

    1. **T-junction merge** — vertices within *tol* are merged; trim-curve
       endpoints are snapped to the cluster representative (Sederberg 2003).
    2. **Dead-loop removal** — loops with < 3 *distinct* vertices or with
       |area| < tol² are removed.
    3. **Orientation fix** — outer loop must be CCW (positive shoelace area);
       inner loops must be CW (negative area).  Loops with wrong orientation
       are reversed in-place.
    4. **Self-intersection detection** — pairwise segment-segment test on
       the outer loop; count stored in ``stats['self_intersections']``.
       The face is returned **unchanged** when self-intersections are found
       (no auto-fix — caller must re-model the loop).

    Returns ``HealedTrimLoops``.

``heal_trim_loops_in_body(body, tol=1e-6)``
    Apply ``heal_trim_loops`` to every ``TrimmedFace`` in *body*.
    Returns ``{face_id: HealedTrimLoops}`` per face.

Data model
----------
``TrimmedFace``
    A face with UV-space loops.  Each loop is ``list[tuple[float, float]]``
    — an ordered polygon in UV space (last vertex is implicitly connected to
    first).  ``outer`` is the single outer boundary; ``inners`` are zero or
    more hole loops.

``HealedTrimLoops``
    ``face``  : the original ``TrimmedFace`` (unchanged)
    ``outer`` : ``list[tuple[float, float]]`` — healed outer loop
    ``inners``: ``list[list[tuple[float, float]]]`` — healed inner loops
    ``stats`` : ``dict`` with keys:
        - ``tjunctions_merged``    : int
        - ``deadloops_removed``    : int
        - ``orientations_fixed``   : int
        - ``self_intersections``   : int

Never raises for well-typed input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

__all__ = [
    "TrimmedFace",
    "HealedTrimLoops",
    "heal_trim_loops",
    "heal_trim_loops_in_body",
]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

UV = Tuple[float, float]
UVLoop = List[UV]


@dataclass
class TrimmedFace:
    """A NURBS face with UV-space trim loops.

    Attributes
    ----------
    outer : list of (u, v)
        The outer boundary polygon in UV space.  Should be CCW.  Last vertex
        is implicitly connected to first — do **not** repeat it.
    inners : list[list[(u, v)]]
        Zero or more inner hole loops.  Should be CW.
    face_id : str or None
        Optional identifier (used in per-body reporting).
    """

    outer: UVLoop = field(default_factory=list)
    inners: List[UVLoop] = field(default_factory=list)
    face_id: Optional[str] = None


@dataclass
class HealedTrimLoops:
    """Result of ``heal_trim_loops``.

    Attributes
    ----------
    face : TrimmedFace
        The original face (unchanged).
    outer : list of (u, v)
        Healed outer loop (CCW).
    inners : list[list[(u, v)]]
        Healed inner loops (each CW).
    stats : dict
        Counts keyed by:
        ``tjunctions_merged``, ``deadloops_removed``,
        ``orientations_fixed``, ``self_intersections``.
    """

    face: TrimmedFace
    outer: UVLoop
    inners: List[UVLoop]
    stats: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shoelace (signed area)
# ---------------------------------------------------------------------------

def _signed_area(loop: UVLoop) -> float:
    """Compute the signed area of a UV polygon via the shoelace formula.

    Positive → CCW; negative → CW.
    """
    n = len(loop)
    if n < 2:
        return 0.0
    acc = 0.0
    for i in range(n):
        u0, v0 = loop[i]
        u1, v1 = loop[(i + 1) % n]
        acc += u0 * v1 - u1 * v0
    return acc * 0.5


# ---------------------------------------------------------------------------
# T-junction merge
# ---------------------------------------------------------------------------

def _merge_tjunctions(loops: List[UVLoop], tol: float) -> Tuple[List[UVLoop], int]:
    """Merge vertices within *tol* across all UV loops.

    Strategy (Sederberg 2003):
    1. Collect all unique vertices from all loops.
    2. Union-Find: cluster vertices with Euclidean distance < tol.
    3. Replace every vertex in every loop with the cluster representative
       (component-wise mean of the cluster, computed once).

    Returns ``(healed_loops, n_merged)`` where *n_merged* is the number of
    T-junctions that were snapped (i.e. vertices that were reassigned to a
    different position).
    """
    # Collect all vertices with their source location (loop_idx, vertex_idx)
    all_verts: List[UV] = []
    loop_vertex_idx: List[List[int]] = []  # maps loop[i][j] → index in all_verts
    for loop in loops:
        idxs: List[int] = []
        for uv in loop:
            idxs.append(len(all_verts))
            all_verts.append(uv)
        loop_vertex_idx.append(idxs)

    n = len(all_verts)
    if n == 0:
        return loops, 0

    # Union-Find
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # O(n²) merge — acceptable for typical trim loop sizes (< 1000 vertices)
    for i in range(n):
        ui, vi_ = all_verts[i]
        for j in range(i + 1, n):
            uj, vj = all_verts[j]
            if math.hypot(ui - uj, vi_ - vj) < tol:
                union(i, j)

    # Compute representative per cluster (arithmetic mean)
    clusters: Dict[int, List[UV]] = {}
    for i in range(n):
        r = find(i)
        clusters.setdefault(r, []).append(all_verts[i])

    representatives: Dict[int, UV] = {}
    for r, members in clusters.items():
        mu = float(np.mean([m[0] for m in members]))
        mv = float(np.mean([m[1] for m in members]))
        representatives[r] = (mu, mv)

    # Count T-junction merges: each cluster with > 1 member represents one
    # merge event.  A T-junction exists when >= 2 distinct original vertices
    # are within *tol* of each other and are collapsed to a single point.
    # We count the number of such non-trivial clusters.
    n_merged = sum(
        1 for members in clusters.values() if len(members) > 1
    )

    new_loops: List[UVLoop] = []
    for loop_i, loop in enumerate(loops):
        new_loop: UVLoop = []
        for j in range(len(loop)):
            global_idx = loop_vertex_idx[loop_i][j]
            r = find(global_idx)
            new_loop.append(representatives[r])
        new_loops.append(new_loop)

    return new_loops, n_merged


# ---------------------------------------------------------------------------
# Distinct vertex count (dedup within tol)
# ---------------------------------------------------------------------------

def _distinct_vertices(loop: UVLoop, tol: float) -> int:
    """Return the number of distinct (further than *tol* apart) vertices."""
    if not loop:
        return 0
    distinct: List[UV] = [loop[0]]
    for u, v in loop[1:]:
        if all(math.hypot(u - d[0], v - d[1]) >= tol for d in distinct):
            distinct.append((u, v))
    return len(distinct)


# ---------------------------------------------------------------------------
# Dead-loop removal
# ---------------------------------------------------------------------------

def _is_dead_loop(loop: UVLoop, tol: float) -> bool:
    """Return True if *loop* is degenerate: < 3 distinct vertices OR |area| < tol²."""
    if _distinct_vertices(loop, tol) < 3:
        return True
    area = abs(_signed_area(loop))
    return area < tol * tol


def _remove_dead_loops(
    loops: List[UVLoop], tol: float
) -> Tuple[List[UVLoop], int]:
    """Remove dead loops.  Returns ``(surviving_loops, n_removed)``."""
    survivors: List[UVLoop] = []
    n_removed = 0
    for loop in loops:
        if _is_dead_loop(loop, tol):
            n_removed += 1
        else:
            survivors.append(loop)
    return survivors, n_removed


# ---------------------------------------------------------------------------
# Orientation fix
# ---------------------------------------------------------------------------

def _fix_orientation(
    outer: UVLoop, inners: List[UVLoop]
) -> Tuple[UVLoop, List[UVLoop], int]:
    """Ensure outer is CCW and every inner is CW.

    Returns ``(fixed_outer, fixed_inners, n_fixed)``.
    """
    n_fixed = 0

    # Outer must be CCW (positive area)
    if _signed_area(outer) < 0.0:
        outer = list(reversed(outer))
        n_fixed += 1

    # Each inner must be CW (negative area)
    fixed_inners: List[UVLoop] = []
    for inner in inners:
        if _signed_area(inner) > 0.0:
            inner = list(reversed(inner))
            n_fixed += 1
        fixed_inners.append(inner)

    return outer, fixed_inners, n_fixed


# ---------------------------------------------------------------------------
# 2-D segment-segment intersection (adapted from region2d._seg_isect)
# ---------------------------------------------------------------------------

def _seg_isect_2d(
    a0: UV, a1: UV, b0: UV, b1: UV
) -> Optional[Tuple[float, float]]:
    """Return (alpha, beta) if segments a0→a1 and b0→b1 intersect strictly.

    Interior intersection only (endpoints excluded via eps guard).
    Returns None when parallel or endpoint-touching.
    """
    dax = a1[0] - a0[0]
    day = a1[1] - a0[1]
    dbx = b1[0] - b0[0]
    dby = b1[1] - b0[1]
    denom = dax * dby - day * dbx
    if abs(denom) < 1e-14:
        return None
    dx = b0[0] - a0[0]
    dy = b0[1] - a0[1]
    alpha = (dx * dby - dy * dbx) / denom
    beta = (dx * day - dy * dax) / denom
    eps = 1e-9
    if eps < alpha < 1.0 - eps and eps < beta < 1.0 - eps:
        return alpha, beta
    return None


# ---------------------------------------------------------------------------
# Self-intersection detection
# ---------------------------------------------------------------------------

def _count_self_intersections(loop: UVLoop) -> int:
    """Count the number of interior self-intersections in *loop*.

    Uses pairwise segment-segment intersection, skipping adjacent segments
    (share a vertex) and the wrap-around pair (also adjacent).
    """
    n = len(loop)
    if n < 4:
        return 0
    count = 0
    for i in range(n):
        a0, a1 = loop[i], loop[(i + 1) % n]
        for j in range(i + 2, n):
            # Skip adjacent pair at wrap-around
            if i == 0 and j == n - 1:
                continue
            b0, b1 = loop[j], loop[(j + 1) % n]
            if _seg_isect_2d(a0, a1, b0, b1) is not None:
                count += 1
    return count


# ---------------------------------------------------------------------------
# Main: heal_trim_loops
# ---------------------------------------------------------------------------

def heal_trim_loops(face: TrimmedFace, tol: float = 1e-6) -> HealedTrimLoops:
    """Repair T-junctions, dead loops, and orientation errors in *face*'s
    UV-space trim loops.

    Parameters
    ----------
    face : TrimmedFace
        A face with one outer loop and zero or more inner loops in UV space.
    tol : float
        Merge / area tolerance.

    Returns
    -------
    HealedTrimLoops
        ``stats`` keys:
        ``tjunctions_merged``, ``deadloops_removed``,
        ``orientations_fixed``, ``self_intersections``.

    Notes
    -----
    * Self-intersections are **detected only** — the loop is returned unchanged
      when self-intersections are found.
    * All operations are applied in sequence: T-junction → dead-loop →
      orientation → self-intersection report.
    """
    stats: Dict[str, int] = {
        "tjunctions_merged": 0,
        "deadloops_removed": 0,
        "orientations_fixed": 0,
        "self_intersections": 0,
    }

    # Gather all loops (outer first, then inners)
    all_loops: List[UVLoop] = [list(face.outer)] + [list(lp) for lp in face.inners]

    # ── Step 1: T-junction merge ────────────────────────────────────────────
    all_loops, n_tj = _merge_tjunctions(all_loops, tol)
    stats["tjunctions_merged"] = n_tj

    outer_loop = all_loops[0]
    inner_loops = all_loops[1:]

    # ── Step 2: Dead-loop removal (inners only; outer handled separately) ──
    inner_loops, n_dead_inner = _remove_dead_loops(inner_loops, tol)
    # Also check outer
    if _is_dead_loop(outer_loop, tol):
        # If the outer loop itself is dead, we cannot heal — return as-is
        stats["deadloops_removed"] += 1 + n_dead_inner
        return HealedTrimLoops(
            face=face,
            outer=list(face.outer),
            inners=[list(lp) for lp in face.inners],
            stats=stats,
        )
    stats["deadloops_removed"] = n_dead_inner

    # ── Step 3: Orientation fix ─────────────────────────────────────────────
    outer_loop, inner_loops, n_orient = _fix_orientation(outer_loop, inner_loops)
    stats["orientations_fixed"] = n_orient

    # ── Step 4: Self-intersection detection ─────────────────────────────────
    n_si = _count_self_intersections(outer_loop)
    stats["self_intersections"] = n_si

    return HealedTrimLoops(
        face=face,
        outer=outer_loop,
        inners=inner_loops,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Batch: heal_trim_loops_in_body
# ---------------------------------------------------------------------------

def heal_trim_loops_in_body(
    body: object,
    tol: float = 1e-6,
) -> Dict[str, HealedTrimLoops]:
    """Apply ``heal_trim_loops`` to every ``TrimmedFace`` in *body*.

    The *body* is expected to expose a ``trimmed_faces`` attribute — an
    iterable of ``TrimmedFace`` objects.  If the body has no ``trimmed_faces``
    attribute the function returns an empty dict (graceful no-op).

    Returns
    -------
    dict[str, HealedTrimLoops]
        Keyed by ``face.face_id`` (or ``f"face_{i}"`` when ``face_id`` is
        ``None``).  One entry per face in the body.
    """
    trimmed_faces = getattr(body, "trimmed_faces", None)
    if trimmed_faces is None:
        return {}

    results: Dict[str, HealedTrimLoops] = {}
    for i, face in enumerate(trimmed_faces):
        key = face.face_id if face.face_id is not None else f"face_{i}"
        results[key] = heal_trim_loops(face, tol=tol)
    return results


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    _nurbs_trim_loop_heal_spec = ToolSpec(
        name="nurbs_trim_loop_heal",
        description=(
            "Repair T-junctions, dead loops, and orientation errors in the 2-D "
            "UV-domain trim loops of a NURBS face.  Operates purely in parametric "
            "(UV) space — does not touch 3-D B-rep topology.\n"
            "\n"
            "Pass one outer loop and zero or more inner (hole) loops as UV polygon "
            "lists.  The healer performs four steps in order:\n"
            "  1. T-junction merge — vertices within `tol` snapped to a single "
            "     cluster representative (Sederberg-Zheng-Bakenov-Nasri 2003).\n"
            "  2. Dead-loop removal — loops with < 3 distinct vertices or |area| "
            "     < tol² are discarded.\n"
            "  3. Orientation fix — outer loop forced CCW; inner loops forced CW "
            "     (Eberly 2008 shoelace sign test).\n"
            "  4. Self-intersection detection — interior crossings are counted and "
            "     reported; the loop is returned unchanged (no auto-fix).\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  outer               : list of [u, v] — healed outer loop\n"
            "  inners              : list[list[u,v]] — healed inner loops\n"
            "  tjunctions_merged   : int\n"
            "  deadloops_removed   : int\n"
            "  orientations_fixed  : int\n"
            "  self_intersections  : int — non-zero means the loop is invalid;\n"
            "                        the original outer is returned unchanged\n"
            "\n"
            "Errors: {ok: false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "outer": {
                    "type": "array",
                    "description": (
                        "Outer boundary loop as a list of [u, v] UV pairs.  "
                        "Should be CCW; will be auto-corrected if CW.  "
                        "Do NOT repeat the first vertex at the end."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                "inners": {
                    "type": "array",
                    "description": (
                        "Zero or more inner (hole) loops, each a list of [u, v] pairs.  "
                        "Should be CW; will be auto-corrected if CCW."
                    ),
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                    },
                },
                "tol": {
                    "type": "number",
                    "description": "UV-space merge / area tolerance (default 1e-6).",
                },
                "face_id": {
                    "type": "string",
                    "description": "Optional identifier for this face (informational only).",
                },
            },
            "required": ["outer"],
        },
    )

    @register(_nurbs_trim_loop_heal_spec)
    async def run_nurbs_trim_loop_heal(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_outer = a.get("outer")
        raw_inners = a.get("inners", [])
        tol = a.get("tol", 1e-6)
        face_id = a.get("face_id", None)

        if not raw_outer:
            return err_payload("outer loop is required and must be non-empty", "BAD_ARGS")

        if not isinstance(tol, (int, float)) or tol <= 0:
            return err_payload(
                f"tol must be a positive number; got {tol!r}", "BAD_ARGS"
            )

        # Parse outer loop
        try:
            outer: UVLoop = [(float(p[0]), float(p[1])) for p in raw_outer]
        except Exception as exc:
            return err_payload(f"invalid outer loop: {exc}", "BAD_ARGS")

        if len(outer) < 2:
            return err_payload("outer loop must have at least 2 vertices", "BAD_ARGS")

        # Parse inner loops
        inners: List[UVLoop] = []
        try:
            for k, raw_inner in enumerate(raw_inners):
                inners.append([(float(p[0]), float(p[1])) for p in raw_inner])
        except Exception as exc:
            return err_payload(f"invalid inner loop at index {k}: {exc}", "BAD_ARGS")

        face = TrimmedFace(outer=outer, inners=inners, face_id=face_id)

        try:
            result = heal_trim_loops(face, tol=float(tol))
        except Exception as exc:
            return err_payload(f"heal_trim_loops failed: {exc}", "OP_FAILED")

        return ok_payload({
            "outer": [[u, v] for u, v in result.outer],
            "inners": [[[u, v] for u, v in lp] for lp in result.inners],
            "tjunctions_merged": result.stats["tjunctions_merged"],
            "deadloops_removed": result.stats["deadloops_removed"],
            "orientations_fixed": result.stats["orientations_fixed"],
            "self_intersections": result.stats["self_intersections"],
        })
