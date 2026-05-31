"""
face_normal_flip.py
===================
BREP-EDGE-FACE-NORMAL-FLIP — detect and fix B-rep faces whose outward normals
point inconsistently (some inverted relative to their neighbours).

Algorithm: Neighbour-consensus voting (iterative propagation)
-------------------------------------------------------------
For each pair of faces sharing an edge, the algorithm checks whether the two
face normals are "consistently oriented" relative to each other.

**Key insight for curved surfaces**: on a correctly-oriented convex surface
(e.g. a sphere or curved shell), adjacent outward face normals point in
similar — though not identical — directions, so dot(n_A, n_B) > 0 (both
facing roughly "outward").  When face B is accidentally inverted, its normal
is negated and dot(n_A, n_B_inverted) < 0 (anti-parallel).

For a face pair (A, B):
  - d = dot(n_A, n_B)
  - d > +threshold → both point the same general direction (consistent
    for a convex surface; no flip needed for B).
  - d < -threshold → anti-parallel normals → B is likely inverted; flip it.
  - |d| <= threshold → near-perpendicular → ambiguous; no action.

**Perpendicular-face limitation**: if adjacent normals are nearly orthogonal
(|d| <= threshold) the algorithm cannot determine whether B is inverted.
A unit cube has all-perpendicular adjacent normals → this algorithm cannot
detect a flipped cube face from normals alone.

A face is *marked for flip* if dot with its BFS parent in the propagation
tree is < -threshold (highly anti-parallel, indicating likely inversion).

Iterative propagation (max_iter = 10):
  1. For each connected component, BFS from the seed face.
  2. On each BFS edge (A → B, B not yet visited):
       - Compute d = dot(n_A_current, n_B_current).
       - If d < -threshold: flip n_B (restore co-orientation with n_A).
       - If d > threshold or |d| <= threshold: n_B left as-is.
  3. Repeat until no changes or max_iter reached.

After propagation, re-count consensus: fraction of definitive-signal edges
(|d| > threshold) that are co-oriented (d > 0) — i.e. correctly pointing
in compatible outward directions for a convex surface.

Honest caveats
--------------
* **Perpendicular-face limitation**: for adjacent faces with orthogonal
  normals (|dot(n_A, n_B)| < threshold), no flip signal is available.  A
  unit cube has all adjacent face normals perpendicular — this algorithm
  cannot detect a flipped cube face from its neighbours alone.  The algorithm
  reports which edges were ambiguous via the consensus_score (ambiguous edges
  excluded from count).
* **Isolated faces** (faces with no listed neighbours) cannot be voted;
  returned unchanged.
* **Seed-relative consistency**: the absolute orientation of each connected
  component is determined by the seed face's input normal.  If the seed face
  itself is inverted, the entire component will be consistently wrong.
* **Not a geometric B-rep heal**: does not recompute normals from surface
  derivatives.  Use in conjunction with NURBS surface_normal (Piegl-Tiller
  Alg. A4.2) or OCCT BRepLib::OrientClosedSolid.
* **Non-orientable shells**: Möbius-strip topology will produce conflicting
  votes; the algorithm reports non-convergence.

References
----------
- Mantyla, M. (1988) "An Introduction to Solid Modeling" §6.4
  (Face orientation consistency, §6.4.2 orientation propagation)
- Hoffmann, C. M. (1989) "Geometric and Solid Modeling" §3
  (Boundary representation, face orientation, §3.3 manifold shells)
- Weiler, K. (1985) "Edge-based data structures for solid modeling in
  curved-surface environments" §3 (half-edge orientation, radial-edge)
- Ericson, C. (2005) "Real-Time Collision Detection" §2.5 (outward normals)

Public API
----------
FaceNormalFlipResult : dataclass
    face_normals_after, num_faces_flipped, flipped_face_indices,
    consensus_score, honest_caveat

detect_and_flip_face_normals(faces_with_normals, max_iter=10, threshold=0.15)
    Iterative neighbour-consensus normal orientation correction.

LLM tool: ``brep_detect_and_flip_face_normals``
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class FaceNormalFlipResult:
    """Result of :func:`detect_and_flip_face_normals`.

    Attributes
    ----------
    face_normals_after : list[tuple[float, float, float]]
        Outward normal vectors for each face after correction (unit vectors).
        Flipped faces have their normals negated relative to the input.
    num_faces_flipped : int
        Total number of faces whose orientation was corrected.
    flipped_face_indices : list[int]
        Zero-based indices of flipped faces (into the original input list).
    consensus_score : float
        Fraction of definitive-signal shared edges (|dot| > threshold) that
        are co-oriented (d > 0) after correction — i.e. compatible outward
        normals on a convex surface.  A score of 1.0 means every non-ambiguous
        shared edge has consistently co-oriented normals (correct for convex
        shells).  Edges where adjacent normals are nearly perpendicular are
        excluded from this score.  Returns 1.0 if there are no
        definitive-signal edges.
    honest_caveat : str
        Human-readable note about limitations and approximations applied.
        Always non-empty; always reports the perpendicular-face limitation,
        isolated-face limitation, and seed-relative consistency.
    """
    face_normals_after: List[Tuple[float, float, float]]
    num_faces_flipped: int
    flipped_face_indices: List[int]
    consensus_score: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Normalise a 3-vector; return (0,0,1) if near-zero."""
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    mag = math.sqrt(x * x + y * y + z * z)
    if mag < 1e-14:
        return (0.0, 0.0, 1.0)
    return (x / mag, y / mag, z / mag)


def _dot(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    """Dot product of two 3-vectors."""
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


def _negate(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (-float(v[0]), -float(v[1]), -float(v[2]))


def _build_adjacency(faces_with_normals: List[Dict]) -> Dict[int, Set[int]]:
    """Build face-adjacency graph from ``neighbor_face_indices`` lists.

    Returns a dict mapping face index (0-based) → set of neighbour indices.
    The graph is made symmetric: if i lists j as neighbour, j is added as
    neighbour of i regardless of whether j lists i.
    """
    n = len(faces_with_normals)
    graph: Dict[int, Set[int]] = {i: set() for i in range(n)}
    for i, face in enumerate(faces_with_normals):
        for j in (face.get("neighbor_face_indices") or []):
            j_int = int(j)
            if 0 <= j_int < n and j_int != i:
                graph[i].add(j_int)
                graph[j_int].add(i)
    return graph


def _connected_components(graph: Dict[int, Set[int]]) -> List[List[int]]:
    """Find connected components via BFS. Returns list of node lists."""
    visited: Set[int] = set()
    components: List[List[int]] = []
    for start in sorted(graph.keys()):
        if start in visited:
            continue
        component: List[int] = []
        queue = [start]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            queue.extend(sorted(graph[node] - visited))
        components.append(component)
    return components


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

_DEFAULT_THRESHOLD = 0.15


def detect_and_flip_face_normals(
    faces_with_normals: List[Dict],
    max_iter: int = 10,
    threshold: float = _DEFAULT_THRESHOLD,
) -> FaceNormalFlipResult:
    """Detect and correct B-rep faces with inconsistent outward normals.

    Uses iterative neighbour-consensus BFS to propagate consistent orientation.
    For each BFS edge (A → B), if dot(n_A, n_B) > threshold (co-oriented),
    n_B is flipped.  If |dot| <= threshold (near-perpendicular), B is left
    unchanged (ambiguous).

    Parameters
    ----------
    faces_with_normals : list[dict]
        Each dict must have:
          - ``"normal"``: ``[nx, ny, nz]`` — outward normal vector (will be
            normalised internally).
          - ``"neighbor_face_indices"``: list of int — 0-based indices into
            ``faces_with_normals`` of faces sharing an edge.
            Absent or empty → face is isolated (cannot be voted).
    max_iter : int
        Maximum propagation iterations (default 10).  Terminates early if
        no face changes orientation in an iteration.
    threshold : float
        Dot-product threshold for "definitive signal" (default 0.15).
        Edge pairs with |dot(n_A, n_B)| <= threshold are treated as
        ambiguous (near-perpendicular) and do not trigger a flip.
        Recommended: 0.1–0.3.

    Returns
    -------
    FaceNormalFlipResult
        See dataclass docstring.

    Notes
    -----
    **Curved-surface assumption**: this algorithm assumes that on a
    CORRECTLY-ORIENTED convex surface, adjacent face normals point in
    compatible (roughly co-oriented, dot > 0) outward directions.  An
    INVERTED face has dot < -threshold with its neighbours.  This assumption
    holds for curved convex meshes (sphere, dome, curved shell) but NOT for:
    - **Perpendicular adjacent faces** (unit cube: all adjacent normals at 90°,
      dot = 0).  All edges are ambiguous; no flip is detected.
    - **Flat meshes**: all faces have identical normals → all co-oriented →
      algorithm reports 0 flips (consistent).
    - **Concave surfaces**: correct adjacent normals may have dot < 0 for a
      concave region, causing false flips.

    **All-inward input**: if all faces consistently point inward the algorithm
    reports 0 flips (they are already co-oriented with each other from the
    BFS perspective).  Absolute orientation cannot be determined without
    vertex positions or a known interior point.

    References
    ----------
    Mantyla (1988) §6.4.2 — face orientation propagation.
    Hoffmann (1989) §3.3 — manifold shell orientation.
    """
    n = len(faces_with_normals)
    if n == 0:
        return FaceNormalFlipResult(
            face_normals_after=[],
            num_faces_flipped=0,
            flipped_face_indices=[],
            consensus_score=1.0,
            honest_caveat=(
                "Empty face list. "
                "Algorithm operates on normal vectors + adjacency topology only; "
                "cannot detect flips in perpendicular-adjacent faces (e.g. unit cube) "
                "— those edges are ambiguous (|dot|<=threshold). "
                "Isolated faces (no neighbour_face_indices) are returned unchanged. "
                "Absolute orientation seeded from first face; all-inward input "
                "produces consistent but absolutely-wrong result. "
                "For production use OCCT BRepLib::OrientClosedSolid. "
                "(Mantyla §6.4; Hoffmann §3)"
            ),
        )

    # --- Step 1: normalise input normals ---
    normals: List[Tuple[float, float, float]] = []
    for face in faces_with_normals:
        raw = face.get("normal") or [0.0, 0.0, 1.0]
        if isinstance(raw, (list, tuple)) and len(raw) >= 3:
            normals.append(_normalize((raw[0], raw[1], raw[2])))
        else:
            normals.append((0.0, 0.0, 1.0))

    # --- Step 2: build adjacency ---
    graph = _build_adjacency(faces_with_normals)

    # --- Step 3: track cumulative flip state ---
    flipped: List[bool] = [False] * n
    working: List[Tuple[float, float, float]] = list(normals)

    # --- Step 4: iterative BFS propagation ---
    caveats_parts: List[str] = []
    converged = False

    for iteration in range(max_iter):
        changed_this_iter = False
        components = _connected_components(graph)

        for component in components:
            if len(component) <= 1:
                continue  # isolated face — no signal

            visited_bfs: Set[int] = set()
            seed = component[0]  # deterministic (components sorted by index)
            queue = [seed]
            visited_bfs.add(seed)

            while queue:
                current = queue.pop(0)
                n_current = working[current]

                for neighbour in sorted(graph[current]):
                    if neighbour not in set(component):
                        continue
                    n_neighbour = working[neighbour]
                    d = _dot(n_current, n_neighbour)

                    if neighbour not in visited_bfs:
                        # First visit: determine orientation relative to current.
                        # On a correctly-oriented convex surface, adjacent normals
                        # are co-oriented (dot > 0).  If dot < -threshold, the
                        # neighbour is likely inverted → flip it back.
                        if d < -threshold:
                            # Anti-parallel → neighbour is likely inverted; flip.
                            working[neighbour] = _negate(n_neighbour)
                            flipped[neighbour] = not flipped[neighbour]
                            changed_this_iter = True
                        # If d >= -threshold (co-oriented or ambiguous): no action.
                        visited_bfs.add(neighbour)
                        queue.append(neighbour)

        if not changed_this_iter:
            converged = True
            break

    if not converged:
        caveats_parts.append(
            f"Orientation propagation did not fully converge in {max_iter} "
            "iterations. Shell may be non-orientable (Möbius-strip topology) "
            "or contain conflicting adjacency cycles. "
            "Result is best-effort; manual review recommended (Mantyla §6.4)."
        )

    # --- Step 5: consensus score (definitive-signal edges only) ---
    # Count edges where |dot| > threshold (non-ambiguous).
    # A correctly-oriented convex surface has all such edges co-oriented (d > 0).
    total_definitive = 0
    co_oriented_definitive = 0
    for i in range(n):
        for j in graph[i]:
            if j > i:  # count each edge once
                d = _dot(working[i], working[j])
                if abs(d) > threshold:
                    total_definitive += 1
                    if d > 0.0:
                        co_oriented_definitive += 1

    consensus_score = (
        float(co_oriented_definitive) / float(total_definitive)
        if total_definitive > 0
        else 1.0  # no definitive-signal edges → vacuously consistent
    )

    # --- Step 6: collect results ---
    flipped_indices = [i for i in range(n) if flipped[i]]
    num_flipped = len(flipped_indices)
    final_normals: List[Tuple[float, float, float]] = list(working)
    isolated_count = sum(1 for i in range(n) if not graph[i])

    caveats_parts += [
        (
            "PERPENDICULAR-FACE LIMITATION: adjacent faces whose normals are "
            f"nearly orthogonal (|dot|<={threshold:.2f}) produce no flip signal — "
            "e.g. a unit cube has all-perpendicular adjacent normals and NO flip "
            "can be detected from normals alone. "
            "Algorithm assumes correctly-oriented CONVEX surface: adjacent normals "
            "co-oriented (dot > 0); inverted face has dot < -threshold with neighbours. "
            "NOT valid for concave surfaces or open flat meshes. "
            "Provide vertex positions + centroid test for reliable absolute orientation "
            "(Weiler 1985 §3)."
        ),
        (
            f"Isolated faces (no neighbours): {isolated_count} face(s) "
            "returned unchanged. "
            "Faces sharing only a vertex are NOT adjacent (radial-edge model)."
        ),
        (
            "Seed-relative consistency: absolute orientation seeded from the "
            "first face in each connected component. "
            "An all-inward input produces internally consistent but absolutely-wrong result. "
            "For production B-rep healing use OCCT BRepLib::OrientClosedSolid "
            "or BRepBuilderAPI_Sewing. (Mantyla §6.4; Hoffmann §3)"
        ),
    ]

    return FaceNormalFlipResult(
        face_normals_after=final_normals,
        num_faces_flipped=num_flipped,
        flipped_face_indices=flipped_indices,
        consensus_score=consensus_score,
        honest_caveat=" | ".join(caveats_parts),
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — only fires when kerf_chat is installed)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _flip_spec = ToolSpec(
        name="brep_detect_and_flip_face_normals",
        description=(
            "Detect and fix B-rep faces whose outward normals point inconsistently "
            "(some inverted relative to their neighbours).\n\n"
            "Uses iterative neighbour-consensus BFS voting (Mantyla §6.4 / Hoffmann §3):\n"
            "For each BFS edge (A → B): if dot(n_A, n_B) > threshold (co-oriented), "
            "face B is flipped.  If |dot| <= threshold (near-perpendicular), "
            "B is left unchanged (ambiguous — no reliable signal).\n\n"
            "Input: list of face dicts, each with:\n"
            "  - ``normal``: [nx, ny, nz] — outward normal (normalised internally)\n"
            "  - ``neighbor_face_indices``: [int, ...] — 0-based indices of adjacent "
            "faces sharing an edge with this face\n\n"
            "Returns:\n"
            "  ``face_normals_after`` — corrected normal list (unit vectors)\n"
            "  ``num_faces_flipped`` — number of faces corrected\n"
            "  ``flipped_face_indices`` — 0-based indices of flipped faces\n"
            "  ``consensus_score`` — fraction of definitive-signal shared edges "
            "(|dot|>threshold) that are anti-parallel after correction\n"
            "  ``honest_caveat`` — limitation notes\n\n"
            "**Critical caveats**:\n"
            "  - PERPENDICULAR-FACE LIMITATION: cannot detect flips when all "
            "neighbours are nearly orthogonal (e.g. unit cube — all adjacent "
            "face normals have dot=0). For such cases provide vertex positions "
            "and use a centroid-based outward test.\n"
            "  - Isolated faces (no neighbours) cannot be voted; returned unchanged.\n"
            "  - Absolute orientation seeded from the first face per component.\n"
            "  - Not a geometric B-rep heal: does not recompute normals from "
            "surface derivatives.\n\n"
            "Refs: Mantyla §6.4; Hoffmann §3; Weiler 1985 §3."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "faces": {
                    "type": "array",
                    "description": (
                        "List of face dicts. Each dict must have:\n"
                        "  - 'normal': [nx, ny, nz] (outward normal)\n"
                        "  - 'neighbor_face_indices': [int, ...] (0-based indices "
                        "of edge-adjacent faces; omit or empty for isolated face)"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "normal": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Normal vector [nx, ny, nz].",
                            },
                            "neighbor_face_indices": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Indices of edge-adjacent faces.",
                            },
                        },
                        "required": ["normal"],
                    },
                },
                "max_iter": {
                    "type": "integer",
                    "description": "Max propagation iterations (default 10).",
                },
                "threshold": {
                    "type": "number",
                    "description": (
                        "Dot-product threshold for definitive signal (default 0.15). "
                        "Edges with |dot(n_A,n_B)| <= threshold are ambiguous and "
                        "do not trigger a flip."
                    ),
                },
            },
            "required": ["faces"],
        },
    )

    @register(_flip_spec)
    async def run_brep_detect_and_flip_face_normals(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

        faces_raw = a.get("faces")
        if faces_raw is None or not isinstance(faces_raw, list):
            return err_payload(
                "'faces' must be a list of face dicts with 'normal' and optional "
                "'neighbor_face_indices'",
                "BAD_ARGS",
            )

        max_iter = int(a.get("max_iter", 10))
        if max_iter < 1:
            return err_payload("max_iter must be >= 1", "BAD_ARGS")

        threshold = float(a.get("threshold", _DEFAULT_THRESHOLD))

        try:
            result = detect_and_flip_face_normals(
                faces_with_normals=faces_raw,
                max_iter=max_iter,
                threshold=threshold,
            )
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "face_normals_after": [list(n) for n in result.face_normals_after],
            "num_faces_flipped": result.num_faces_flipped,
            "flipped_face_indices": result.flipped_face_indices,
            "consensus_score": result.consensus_score,
            "honest_caveat": result.honest_caveat,
        })
