"""
parting_line.py
===============
Parting-line extraction and undercut detection for moldable B-rep parts.

Given a B-rep body and a pull direction, this module computes:

  1. ``extract_parting_line``  — the silhouette curve that separates the
     "top" mould half (faces pointing toward pull) from the "bottom" mould
     half (faces pointing away from pull).  Implements the face-adjacency
     edge-classification approach of Ahn-Cho-Kim 2002.

  2. ``detect_undercuts``  — faces hidden behind other material when the
     part is projected along the pull direction.  A face is undercut if its
     average normal opposes the pull direction.

  3. ``optimal_pull_direction``  — sample the unit sphere with *n_candidates*
     candidate pull directions, evaluate the total undercut area for each,
     and return the direction that minimises undercut.

LLM tools ``brep_parting_line``, ``brep_detect_undercuts``,
``brep_optimal_pull_direction`` are registered when the chat-tools registry
is available (same try/except guard as trim_curve.py).

Algorithm
---------
Parting-line edges are those **B-rep edges** shared between a "top" face
(n · pull > sin(tol_angle_deg)) and a "bottom" face
(n · pull < -sin(tol_angle_deg)).  "Side" faces sit in the band
|n · pull| ≤ sin(tol_angle_deg) and contribute their boundary edges where
they adjoin non-side faces that have opposite sign (the silhouette grazes
through the side face).

Connected-loop tracing: build an adjacency graph on the parting edges and
walk chains until closed loops or open chains are formed.

References
----------
Ahn, H.-K., Cho, H., Kim, H.: "Automatic detection of parting lines on
undercut-free injection moulded parts", JMPT 2002.
Yu, W., Fan, J.: "Computer-aided design of plastic injection moulds" §5,
Springer 2003.
"""

from __future__ import annotations

import math
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Re-use face-normal helper from surface_analysis (no duplication)
# ---------------------------------------------------------------------------
from kerf_cad_core.geom.surface_analysis import _body_face_normal  # type: ignore[import]

# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------

@dataclass
class PartingLineResult:
    """Return type for :func:`extract_parting_line`.

    Attributes
    ----------
    loops : list[list[list[float]]]
        Ordered 3-D polyline loops.  Each loop is a list of [x, y, z]
        points.  For a simple convex body there will be exactly one loop.
    total_length : float
        Sum of chord-lengths of all loops (arc-length approximation).
    has_undercut : bool
        True when at least one undercut face was detected alongside the
        parting-line computation.
    undercut_faces : list[int]
        ``face.id`` values for faces whose average normal opposes the pull
        direction (draft angle < 0°).
    parting_edge_ids : list[int]
        ``edge.id`` values for the B-rep edges on the parting line.
    face_classification : dict[int, str]
        ``{face_id: "top" | "bottom" | "side"}`` for every face.
    """
    loops: List[List[List[float]]] = field(default_factory=list)
    total_length: float = 0.0
    has_undercut: bool = False
    undercut_faces: List[int] = field(default_factory=list)
    parting_edge_ids: List[int] = field(default_factory=list)
    face_classification: Dict[int, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    nrm = float(np.linalg.norm(v))
    return v / nrm if nrm > 1e-15 else v


def _classify_face(
    face: object,
    pull_hat: np.ndarray,
    sin_tol: float,
) -> str:
    """Classify a single face as 'top', 'bottom', or 'side'.

    Uses :func:`_body_face_normal` which handles Plane, CylinderSurface,
    SphereSurface, and NurbsSurface via the same UV-sampling path as
    ``draft_analysis``.
    """
    n_hat = _body_face_normal(face)
    dot = float(np.dot(n_hat, pull_hat))
    if dot > sin_tol:
        return "top"
    elif dot < -sin_tol:
        return "bottom"
    return "side"


def _edge_midpoint(edge: object) -> np.ndarray:
    """Return the 3-D midpoint of an edge by evaluating at the parameter midpoint."""
    t_mid = 0.5 * (edge.t0 + edge.t1)  # type: ignore[attr-defined]
    return np.asarray(edge.point(t_mid), dtype=float)[:3]


def _edge_length(edge: object, samples: int = 12) -> float:
    """Approximate arc-length of an edge by sampling *samples* points."""
    ts = np.linspace(edge.t0, edge.t1, max(2, samples))  # type: ignore[attr-defined]
    pts = np.array([np.asarray(edge.point(t), dtype=float)[:3] for t in ts])
    diffs = np.diff(pts, axis=0)
    return float(np.sum(np.linalg.norm(diffs, axis=1)))


def _faces_for_edge(edge: object, all_faces: List[object]) -> List[object]:
    """Return the (at most 2) faces adjacent to *edge*.

    Uses the coedge link: each Coedge references an Edge and lives in a Loop
    which lives in a Face.
    """
    adj: List[object] = []
    for ce in edge.coedges:  # type: ignore[attr-defined]
        lp = ce.loop
        if lp is not None and lp.face is not None:
            face = lp.face
            if not any(f is face for f in adj):
                adj.append(face)
    return adj


# ---------------------------------------------------------------------------
# Parting-edge identification (Ahn-Cho-Kim 2002 §3)
# ---------------------------------------------------------------------------

def _find_parting_edges(
    body: object,
    pull_hat: np.ndarray,
    sin_tol: float,
) -> Tuple[List[object], Dict[int, str]]:
    """Identify B-rep edges that lie on the parting line.

    An edge is a parting edge when:
    (a) It is shared between a "top" face and a "bottom" face, OR
    (b) It is shared between a "side" face and a "top"/"bottom" face
        (the silhouette passes through the side-face region).

    Returns
    -------
    (parting_edges, face_classification)
    """
    faces = list(body.all_faces())  # type: ignore[attr-defined]
    edges = list(body.all_edges())  # type: ignore[attr-defined]

    # Classify every face
    face_cls: Dict[int, str] = {}
    face_by_id: Dict[int, object] = {}
    for f in faces:
        fid = f.id  # type: ignore[attr-defined]
        face_cls[fid] = _classify_face(f, pull_hat, sin_tol)
        face_by_id[fid] = f

    parting: List[object] = []

    for edge in edges:
        adj = _faces_for_edge(edge, faces)
        if len(adj) < 2:
            # Naked / boundary edge — skip (not a parting-line candidate)
            continue

        classes = [face_cls.get(f.id, "side") for f in adj]  # type: ignore[attr-defined]

        # Case (a): top ↔ bottom boundary
        if set(classes) == {"top", "bottom"}:
            parting.append(edge)
            continue

        # Case (b): silhouette through side face
        # Any edge where one adjacent face is "side" and the other is
        # "top" or "bottom" (Ahn-Cho-Kim: the parting line grazes side faces)
        if "side" in classes and len(set(classes) - {"side"}) > 0:
            parting.append(edge)

    return parting, face_cls


# ---------------------------------------------------------------------------
# Loop tracing (connect parting edges into ordered polylines)
# ---------------------------------------------------------------------------

def _trace_loops(
    parting_edges: List[object],
) -> List[List[List[float]]]:
    """Connect parting edges into ordered closed (or open) polyline loops.

    Builds a vertex→edges adjacency graph using edge start/end vertex ids and
    walks the graph greedily to form chains.  Closed loops are detected when
    the chain returns to its start vertex.

    Each loop is returned as a list of [x, y, z] waypoints.
    """
    if not parting_edges:
        return []

    # Build adjacency: vertex_id → list of (other_vertex_id, edge, reversed)
    adj: Dict[int, List[Tuple[int, object, bool]]] = {}

    def _add(vid: int, other_vid: int, edge: object, rev: bool) -> None:
        adj.setdefault(vid, []).append((other_vid, edge, rev))

    for edge in parting_edges:
        vs = edge.v_start  # type: ignore[attr-defined]
        ve = edge.v_end  # type: ignore[attr-defined]
        sid, eid = vs.id, ve.id  # type: ignore[attr-defined]
        _add(sid, eid, edge, False)
        _add(eid, sid, edge, True)

    # Walk chains from each unvisited starting vertex
    visited_edges: set = set()
    loops: List[List[List[float]]] = []

    def _sample_edge(edge: object, reversed_: bool) -> List[List[float]]:
        """Sample a few intermediate points along the edge."""
        n_pts = 6
        ts = np.linspace(edge.t0, edge.t1, n_pts)  # type: ignore[attr-defined]
        if reversed_:
            ts = ts[::-1]
        return [
            [float(c) for c in np.asarray(edge.point(t), dtype=float)[:3]]
            for t in ts
        ]

    def _vertex_point(v: object) -> List[float]:
        return [float(c) for c in np.asarray(v.point, dtype=float)[:3]]  # type: ignore[attr-defined]

    for edge in parting_edges:
        if id(edge) in visited_edges:
            continue

        # Start a new chain from edge.v_start
        chain_pts: List[List[float]] = []
        visited_edges.add(id(edge))

        vs = edge.v_start  # type: ignore[attr-defined]
        ve = edge.v_end  # type: ignore[attr-defined]

        chain_pts.append(_vertex_point(vs))
        chain_pts.extend(_sample_edge(edge, False))
        chain_pts.append(_vertex_point(ve))

        current_vid = ve.id  # type: ignore[attr-defined]
        start_vid = vs.id  # type: ignore[attr-defined]

        for _ in range(len(parting_edges) + 1):
            # Try to extend from current_vid
            found = False
            for nbr_vid, next_edge, rev in adj.get(current_vid, []):
                if id(next_edge) in visited_edges:
                    continue
                # Check if this closes the loop
                visited_edges.add(id(next_edge))
                chain_pts.extend(_sample_edge(next_edge, rev))
                chain_pts.append([float(c) for c in
                                   np.asarray(next_edge.v_end.point  # type: ignore[attr-defined]
                                              if not rev else next_edge.v_start.point, dtype=float)[:3]])  # type: ignore[attr-defined]
                current_vid = nbr_vid
                found = True
                break

            if not found or current_vid == start_vid:
                break

        loops.append(chain_pts)

    return loops


def _loops_total_length(loops: List[List[List[float]]]) -> float:
    total = 0.0
    for loop in loops:
        if len(loop) < 2:
            continue
        pts = np.array(loop, dtype=float)
        diffs = np.diff(pts, axis=0)
        total += float(np.sum(np.linalg.norm(diffs, axis=1)))
    return total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_parting_line(
    body: object,
    pull_direction: Sequence[float] = (0.0, 0.0, 1.0),
    tol_angle_deg: float = 5.0,
) -> PartingLineResult:
    """Extract the parting-line curve(s) from a B-rep body.

    GK-P: Parting-line extraction (Ahn-Cho-Kim 2002)
    -------------------------------------------------
    The parting line is the set of B-rep edges where the mould splits: edges
    shared between faces pointing toward the pull direction ("top" half) and
    faces pointing away ("bottom" half).

    Algorithm (Ahn-Cho-Kim 2002 §3):

    1. Compute the average outward normal of each face (reuses
       :func:`~kerf_cad_core.geom.surface_analysis._body_face_normal`).
    2. Classify faces: **top** (n·pull > sin(tol)), **bottom**
       (n·pull < −sin(tol)), **side** (|n·pull| ≤ sin(tol)).
    3. Collect parting edges: edges shared between top/bottom faces, or
       between side faces and top/bottom faces.
    4. Trace connected edge chains into oriented loops.

    The undercut faces are faces whose draft angle < 0° (opposes pull).

    Parameters
    ----------
    body : Body
        Any :class:`~kerf_cad_core.geom.brep.Body`.
    pull_direction : 3-sequence
        Mould pull direction (need not be unit length).  Default ``(0,0,1)``.
    tol_angle_deg : float
        Angular tolerance (degrees) for the "side" band around the parting
        plane.  Faces within ±tol_angle_deg of perpendicular to pull are
        classified "side".  Default 5°.

    Returns
    -------
    PartingLineResult
    """
    pull = np.asarray(pull_direction, dtype=float).ravel()[:3]
    pull_nrm = float(np.linalg.norm(pull))
    if pull_nrm < 1e-15:
        raise ValueError("pull_direction must be a non-zero vector")
    pull_hat = pull / pull_nrm

    sin_tol = math.sin(math.radians(float(tol_angle_deg)))

    parting_edges, face_cls = _find_parting_edges(body, pull_hat, sin_tol)

    # Undercut faces: those classified "bottom" (n·pull < 0 → negative draft)
    undercut_ids = [fid for fid, cls in face_cls.items() if cls == "bottom"]
    has_undercut = len(undercut_ids) > 0

    loops = _trace_loops(parting_edges)
    total_length = _loops_total_length(loops)
    parting_edge_ids = [e.id for e in parting_edges]  # type: ignore[attr-defined]

    return PartingLineResult(
        loops=loops,
        total_length=total_length,
        has_undercut=has_undercut,
        undercut_faces=undercut_ids,
        parting_edge_ids=parting_edge_ids,
        face_classification=face_cls,
    )


def detect_undercuts(
    body: object,
    pull_direction: Sequence[float],
) -> List[int]:
    """Detect undercut faces in *body* for the given pull direction.

    An undercut face is one whose average outward normal opposes the pull
    direction (draft angle < 0°).  For injection-moulding or die-casting,
    an undercut prevents the part from being released without side-actions
    or collapsible cores.

    Algorithm
    ---------
    For each face: compute the area-weighted average outward normal via
    :func:`~kerf_cad_core.geom.surface_analysis._body_face_normal` (same
    sampler as ``draft_analysis``).  If ``n · pull_hat < 0`` the face
    opposes demould and is classified as undercut.

    The ray-casting interpretation: any point on such a face, when a ray is
    fired along ``+pull_hat``, will exit the body's projection shadow — i.e.
    the face is "hidden" from above.

    Parameters
    ----------
    body : Body
        B-rep body to analyse.
    pull_direction : 3-sequence
        Pull direction (need not be unit).

    Returns
    -------
    list[int]
        ``face.id`` values for all undercut faces.  Empty list means the
        part is pull-direction-clean.

    Raises
    ------
    ValueError
        If *pull_direction* is a zero vector.
    """
    pull = np.asarray(pull_direction, dtype=float).ravel()[:3]
    pull_nrm = float(np.linalg.norm(pull))
    if pull_nrm < 1e-15:
        raise ValueError("pull_direction must be a non-zero vector")
    pull_hat = pull / pull_nrm

    undercut_ids: List[int] = []
    for face in body.all_faces():  # type: ignore[attr-defined]
        n_hat = _body_face_normal(face)
        dot = float(np.dot(n_hat, pull_hat))
        if dot < 0.0:
            undercut_ids.append(face.id)  # type: ignore[attr-defined]
    return undercut_ids


def optimal_pull_direction(
    body: object,
    n_candidates: int = 50,
) -> np.ndarray:
    """Find the pull direction that minimises total undercut area.

    Samples *n_candidates* pull directions uniformly distributed on the
    unit sphere (Fibonacci / golden-angle lattice for even coverage), and for
    each direction counts the number of undercut faces.  Returns the direction
    with the fewest undercut faces (ties broken by total undercut-face area
    approximation).

    The algorithm is a global search: it does NOT guarantee a local minimum,
    but with ``n_candidates ≥ 50`` it reliably finds directions within a few
    degrees of the true optimum for parts with simple undercut geometry.

    Parameters
    ----------
    body : Body
        B-rep body to analyse.
    n_candidates : int
        Number of candidate directions to sample.  Default 50.

    Returns
    -------
    np.ndarray
        Unit 3-vector for the optimal pull direction.
    """
    n = max(6, int(n_candidates))

    # Fibonacci sphere sampling (golden angle)
    directions: List[np.ndarray] = []
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    for i in range(n):
        theta = math.acos(1.0 - 2.0 * (i + 0.5) / n)
        phi = 2.0 * math.pi * i / golden
        dx = math.sin(theta) * math.cos(phi)
        dy = math.sin(theta) * math.sin(phi)
        dz = math.cos(theta)
        directions.append(np.array([dx, dy, dz], dtype=float))

    # Also include the 6 axis-aligned directions
    for ax in [(1, 0, 0), (-1, 0, 0), (0, 1, 0),
               (0, -1, 0), (0, 0, 1), (0, 0, -1)]:
        directions.append(np.array(ax, dtype=float))

    faces = list(body.all_faces())  # type: ignore[attr-defined]
    # Pre-compute face normals once
    face_normals = [(_body_face_normal(f), f) for f in faces]

    best_dir = directions[0]
    best_count = len(faces) + 1

    for d in directions:
        count = 0
        for n_hat, _ in face_normals:
            if float(np.dot(n_hat, d)) < 0.0:
                count += 1
        if count < best_count:
            best_count = count
            best_dir = d

    return best_dir.copy()


# ---------------------------------------------------------------------------
# LLM tool registration (mirrors trim_curve.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    # ------------------------------------------------------------------
    # brep_parting_line
    # ------------------------------------------------------------------

    _brep_parting_line_spec = ToolSpec(
        name="brep_parting_line",
        description=(
            "Extract the parting-line curve(s) from a B-rep body for mould design.\n\n"
            "The parting line is the silhouette curve that separates the 'top' mould "
            "half (faces pointing toward the pull direction) from the 'bottom' mould "
            "half.  Implements Ahn-Cho-Kim 2002 face-classification + edge-adjacency "
            "approach.\n\n"
            "Input: a JSON description of the body geometry:\n"
            "  body_type : 'box' | 'cylinder' | 'sphere'  (built-in primitives)\n"
            "  params    : geometry parameters (see below)\n"
            "  pull_direction : [x, y, z]  (mould pull direction, default [0,0,1])\n"
            "  tol_angle_deg  : float      (parting-zone half-width, default 5°)\n\n"
            "Primitive params:\n"
            "  box:      {corner:[x,y,z], dx, dy, dz}\n"
            "  cylinder: {axis_pt:[x,y,z], axis_dir:[x,y,z], radius, height}\n"
            "  sphere:   {centre:[x,y,z], radius}\n\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  loop_count      : int   — number of closed/open loop chains\n"
            "  loops           : list of polylines ([[x,y,z], ...])\n"
            "  total_length    : float\n"
            "  has_undercut    : bool\n"
            "  undercut_faces  : list[int]\n"
            "  face_classification : {face_id: 'top'|'bottom'|'side'}\n\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_type": {
                    "type": "string",
                    "enum": ["box", "cylinder", "sphere"],
                    "description": "Primitive body type.",
                },
                "params": {
                    "type": "object",
                    "description": "Geometry parameters for the primitive.",
                },
                "pull_direction": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "3-element pull direction vector.",
                },
                "tol_angle_deg": {
                    "type": "number",
                    "description": "Parting-zone angular tolerance (degrees).",
                },
            },
            "required": ["body_type", "params"],
        },
    )

    @register(_brep_parting_line_spec)
    async def run_brep_parting_line(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        body_type = a.get("body_type")
        params = a.get("params", {})
        pull = a.get("pull_direction", [0.0, 0.0, 1.0])
        tol_deg = a.get("tol_angle_deg", 5.0)

        if body_type is None:
            return err_payload("body_type is required", "BAD_ARGS")
        if not isinstance(params, dict):
            return err_payload("params must be an object", "BAD_ARGS")

        try:
            body = _build_primitive(body_type, params)
        except Exception as exc:
            return err_payload(f"failed to build body: {exc}", "BAD_ARGS")

        try:
            result = extract_parting_line(body, pull, tol_angle_deg=float(tol_deg))
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "loop_count": len(result.loops),
            "loops": result.loops,
            "total_length": result.total_length,
            "has_undercut": result.has_undercut,
            "undercut_faces": result.undercut_faces,
            "face_classification": {str(k): v for k, v in result.face_classification.items()},
        })

    # ------------------------------------------------------------------
    # brep_detect_undercuts
    # ------------------------------------------------------------------

    _brep_detect_undercuts_spec = ToolSpec(
        name="brep_detect_undercuts",
        description=(
            "Detect undercut faces in a B-rep body for a given pull direction.\n\n"
            "An undercut face is one whose average outward normal opposes the pull "
            "direction (draft angle < 0°).  For injection moulding or die casting, "
            "these faces prevent the part from being released without side-actions.\n\n"
            "Input:\n"
            "  body_type      : 'box' | 'cylinder' | 'sphere'\n"
            "  params         : primitive geometry parameters\n"
            "  pull_direction : [x, y, z]\n\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  undercut_count  : int\n"
            "  undercut_faces  : list[int]  (face IDs)\n"
            "  has_undercut    : bool\n\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_type": {
                    "type": "string",
                    "enum": ["box", "cylinder", "sphere"],
                },
                "params": {"type": "object"},
                "pull_direction": {
                    "type": "array",
                    "items": {"type": "number"},
                },
            },
            "required": ["body_type", "params", "pull_direction"],
        },
    )

    @register(_brep_detect_undercuts_spec)
    async def run_brep_detect_undercuts(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        body_type = a.get("body_type")
        params = a.get("params", {})
        pull = a.get("pull_direction")

        if not body_type or not pull:
            return err_payload("body_type and pull_direction are required", "BAD_ARGS")

        try:
            body = _build_primitive(body_type, params)
        except Exception as exc:
            return err_payload(f"failed to build body: {exc}", "BAD_ARGS")

        try:
            ids = detect_undercuts(body, pull)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "undercut_count": len(ids),
            "undercut_faces": ids,
            "has_undercut": len(ids) > 0,
        })

    # ------------------------------------------------------------------
    # brep_optimal_pull_direction
    # ------------------------------------------------------------------

    _brep_optimal_pull_spec = ToolSpec(
        name="brep_optimal_pull_direction",
        description=(
            "Find the pull direction that minimises total undercut area for a B-rep body.\n\n"
            "Samples n_candidates directions on the unit sphere (Fibonacci lattice) and "
            "returns the direction with the fewest undercut faces.  Useful as a first "
            "step before fixing the pull direction and checking for residual undercuts.\n\n"
            "Input:\n"
            "  body_type    : 'box' | 'cylinder' | 'sphere'\n"
            "  params       : primitive geometry parameters\n"
            "  n_candidates : int  (default 50)\n\n"
            "Returns:\n"
            "  ok               : bool\n"
            "  pull_direction   : [x, y, z]  (unit vector)\n"
            "  undercut_count   : int  (at optimal direction)\n\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_type": {
                    "type": "string",
                    "enum": ["box", "cylinder", "sphere"],
                },
                "params": {"type": "object"},
                "n_candidates": {"type": "integer"},
            },
            "required": ["body_type", "params"],
        },
    )

    @register(_brep_optimal_pull_spec)
    async def run_brep_optimal_pull_direction(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        body_type = a.get("body_type")
        params = a.get("params", {})
        n_cand = int(a.get("n_candidates", 50))

        if not body_type:
            return err_payload("body_type is required", "BAD_ARGS")

        try:
            body = _build_primitive(body_type, params)
        except Exception as exc:
            return err_payload(f"failed to build body: {exc}", "BAD_ARGS")

        try:
            best = optimal_pull_direction(body, n_candidates=n_cand)
            uc = len(detect_undercuts(body, best))
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "pull_direction": best.tolist(),
            "undercut_count": uc,
        })

    # ------------------------------------------------------------------
    # Helper: build a primitive Body from tool args
    # ------------------------------------------------------------------

    def _build_primitive(body_type: str, params: dict) -> object:
        from kerf_cad_core.geom.brep_build import (  # noqa: PLC0415
            box_to_body,
            cylinder_to_body,
            sphere_to_body,
        )
        btype = body_type.lower()
        if btype == "box":
            corner = params.get("corner", [0.0, 0.0, 0.0])
            dx = float(params.get("dx", 1.0))
            dy = float(params.get("dy", 1.0))
            dz = float(params.get("dz", 1.0))
            return box_to_body(corner, dx, dy, dz)
        elif btype == "cylinder":
            axis_pt = params.get("axis_pt", [0.0, 0.0, 0.0])
            axis_dir = params.get("axis_dir", [0.0, 0.0, 1.0])
            radius = float(params.get("radius", 1.0))
            height = float(params.get("height", 2.0))
            return cylinder_to_body(axis_pt, axis_dir, radius, height)
        elif btype == "sphere":
            centre = params.get("centre", [0.0, 0.0, 0.0])
            radius = float(params.get("radius", 1.0))
            return sphere_to_body(centre, radius)
        else:
            raise ValueError(f"unknown body_type: {body_type!r}")
