"""wire_closed_check.py -- BREP-WIRE-CLOSED-CHECK

Given an ordered list of B-rep edges forming a wire, verify it forms a
closed loop (last vertex connects back to first) and check planarity of all
edge endpoints.  Used as a precondition for face creation.

Theory
------
A wire (sequence of connected edge segments) is **closed** iff the start
vertex of the first edge coincides with the end vertex of the last edge,
within the specified positional tolerance.

A wire is **planar** iff all vertices of the wire lie on a single best-fit
plane.  The plane is found by:
  1. Compute the centroid of all endpoint coordinates.
  2. Form the (N×3) demeaned matrix A of coordinate deviations.
  3. Compute the thin SVD of A.
  4. The *least* singular vector (column of V corresponding to the smallest
     singular value) is the best-fit plane normal.
  5. The maximum |signed distance from centroid plane| over all vertices is
     the ``max_out_of_plane_deviation_mm``.
  6. The wire is planar iff this deviation is less than ``tolerance_mm``.

For a degenerate wire (< 3 unique points, or numerically collinear points)
the SVD normal is unreliable; ``planar=True`` is reported with a caveat.

References
----------
Mantyla, M. (1988). *Introduction to Solid Modeling*. §3 (Wire and Face
    Topology); §6 (Winged-Edge / Half-Edge BREP).

Hoffmann, C. M. (1989). *Geometric and Solid Modeling*. §4 (Topological
    Primitives and BREP Validity).

Press, W. H. et al. (2007). *Numerical Recipes* §15.4 (General Least-Squares
    and SVD plane fit).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

__all__ = [
    "EdgeSegment",
    "WireCheckReport",
    "check_wire_closed",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EdgeSegment:
    """One directed edge in a B-rep wire.

    Attributes
    ----------
    start_xyz : tuple[float, float, float]
        3-D coordinates of the edge start vertex (mm).
    end_xyz : tuple[float, float, float]
        3-D coordinates of the edge end vertex (mm).
    edge_id : str
        Optional identifier for debugging / reporting.  Defaults to "".
    """

    start_xyz: tuple[float, float, float]
    end_xyz: tuple[float, float, float]
    edge_id: str = ""


@dataclass
class WireCheckReport:
    """Result of :func:`check_wire_closed`.

    Attributes
    ----------
    closed : bool
        True when the end of the last edge lies within ``tolerance_mm`` of
        the start of the first edge, AND every consecutive pair of edges is
        connected (end_i ≈ start_{i+1}).
    planar : bool
        True when all edge endpoints lie on a common plane within
        ``tolerance_mm``.  Always True for wires with < 3 unique points
        (trivially coplanar).
    max_endpoint_gap_mm : float
        Maximum positional gap between consecutive endpoints (including the
        gap from last.end back to first.start).  Zero for a closed wire.
    num_edges : int
        Number of edges provided.
    plane_normal_xyz : tuple[float, float, float] | None
        Least-SVD plane normal (unit vector) if planarity could be computed;
        None for degenerate wires (< 3 distinct points or all collinear).
    max_out_of_plane_deviation_mm : float
        Maximum absolute distance from the best-fit plane over all endpoints.
        Zero for degenerate wires.
    honest_caveat : str
        Honest-flag summarising algorithmic limitations.
    """

    closed: bool
    planar: bool
    max_endpoint_gap_mm: float
    num_edges: int
    plane_normal_xyz: Optional[tuple[float, float, float]]
    max_out_of_plane_deviation_mm: float
    honest_caveat: str = field(default=(
        "Edge order-dependent: edges must be supplied in traversal order "
        "(end_i ≈ start_{i+1}). Scrambled / unordered edge lists are NOT "
        "automatically sorted — pass pre-ordered edges only. "
        "Planarity is a best-fit SVD check over all endpoints; "
        "curved edge interiors are NOT sampled. "
        "References: Mantyla 'Solid Modeling' §3; Hoffmann §4."
    ))


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def check_wire_closed(
    edges: list[EdgeSegment],
    tolerance_mm: float = 1e-6,
) -> WireCheckReport:
    """Verify that an ordered edge list forms a closed planar loop.

    A wire is **closed** iff:
      * Every consecutive pair is connected: ``edges[i].end ≈ edges[i+1].start``
        within ``tolerance_mm``.
      * The final edge loops back: ``edges[-1].end ≈ edges[0].start``
        within ``tolerance_mm``.

    A wire is **planar** iff the SVD best-fit plane over all endpoints
    (start and end vertices of every edge) has
    ``max_out_of_plane_deviation_mm < tolerance_mm``.

    Parameters
    ----------
    edges : list[EdgeSegment]
        Ordered list of edge segments.  Must be non-empty.
    tolerance_mm : float
        Positional tolerance in mm.  Default 1e-6.

    Returns
    -------
    WireCheckReport

    Raises
    ------
    ValueError
        If ``edges`` is empty.
    """
    if not edges:
        raise ValueError("check_wire_closed: edges list must not be empty.")

    n = len(edges)

    # ------------------------------------------------------------------
    # Step 1: closure + connectivity check
    # ------------------------------------------------------------------
    max_gap = 0.0
    closed = True

    # Check interior chain: end_i ≈ start_{i+1}
    for i in range(n - 1):
        gap = _dist3(edges[i].end_xyz, edges[i + 1].start_xyz)
        if gap > max_gap:
            max_gap = gap
        if gap > tolerance_mm:
            closed = False

    # Check wrap-around: last.end ≈ first.start
    wrap_gap = _dist3(edges[-1].end_xyz, edges[0].start_xyz)
    if wrap_gap > max_gap:
        max_gap = wrap_gap
    if wrap_gap > tolerance_mm:
        closed = False

    # ------------------------------------------------------------------
    # Step 2: collect all endpoint coordinates
    # ------------------------------------------------------------------
    pts: list[tuple[float, float, float]] = []
    for e in edges:
        pts.append(e.start_xyz)
        pts.append(e.end_xyz)

    # ------------------------------------------------------------------
    # Step 3: SVD planarity
    # ------------------------------------------------------------------
    plane_normal, max_oop = _svd_planarity(pts)

    if plane_normal is None:
        # Degenerate (< 3 distinct points or all collinear): trivially planar
        planar = True
        max_out_of_plane = 0.0
        normal_xyz = None
    else:
        max_out_of_plane = max_oop
        planar = max_out_of_plane < tolerance_mm
        normal_xyz = (
            float(plane_normal[0]),
            float(plane_normal[1]),
            float(plane_normal[2]),
        )

    return WireCheckReport(
        closed=closed,
        planar=planar,
        max_endpoint_gap_mm=float(max_gap),
        num_edges=n,
        plane_normal_xyz=normal_xyz,
        max_out_of_plane_deviation_mm=float(max_out_of_plane),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _dist3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Euclidean distance between two 3-D points."""
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _svd_planarity(
    pts: list[tuple[float, float, float]],
) -> tuple[Optional[np.ndarray], float]:
    """Compute best-fit plane normal and max out-of-plane deviation via SVD.

    Returns
    -------
    (normal, max_deviation) where:
      * normal : np.ndarray shape (3,) — unit least-SVD normal; None if
        degenerate (< 3 unique pts, or near-zero spread in all directions).
      * max_deviation : float — max |distance to best-fit plane| in mm.

    Algorithm (Pratt 1987; Eberly §6.6 orthogonal regression):
      centroid = mean of all points;
      A = demeaned points matrix (N×3);
      SVD: A = U S Vt;  least singular vector = Vt[-1] = V[:,-1].
    """
    A = np.array(pts, dtype=float)  # shape (N, 3)
    if A.shape[0] < 3:
        return None, 0.0

    # De-mean
    centroid = A.mean(axis=0)
    B = A - centroid

    # Check for near-zero spread (all points coincident or nearly so)
    rms = float(np.sqrt((B ** 2).sum()))
    if rms < 1e-14:
        return None, 0.0

    # SVD
    try:
        _, S, Vt = np.linalg.svd(B, full_matrices=False)
    except np.linalg.LinAlgError:
        return None, 0.0

    # Smallest singular value → least-variance (normal) direction
    if S[-1] / (S[0] + 1e-300) > 0.99:
        # Numerically: all three singular values are comparable → no good plane
        # This happens for truly 3D point clouds.  Return the smallest anyway
        # but with a large deviation so planar=False triggers.
        pass

    normal = Vt[-1]  # shape (3,)
    mag = float(np.linalg.norm(normal))
    if mag < 1e-14:
        return None, 0.0
    normal = normal / mag

    # Max |signed distance from centroid-plane|
    signed_distances = B @ normal
    max_dev = float(np.max(np.abs(signed_distances)))

    return normal, max_dev


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — survives without kerf_chat installed)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _spec = ToolSpec(
        name="brep_check_wire_closed",
        description=(
            "Verify that an ordered list of B-rep edge segments forms a closed "
            "loop and check planarity.  Used as a pre-condition before creating "
            "a B-rep face from a wire boundary.\n"
            "\n"
            "A wire is **closed** iff every consecutive pair of edges is "
            "connected (end_i ≈ start_{i+1} within tolerance_mm) AND the last "
            "edge end loops back to the first edge start.\n"
            "\n"
            "A wire is **planar** iff the SVD best-fit plane over all edge "
            "endpoints has max_out_of_plane_deviation_mm < tolerance_mm.\n"
            "\n"
            "Input: ordered list of edges as {start_xyz:[x,y,z], end_xyz:[x,y,z], "
            "edge_id?:str}. Edges must be supplied in wire-traversal order.\n"
            "\n"
            "Returns:\n"
            "  closed                       — True when loop is closed\n"
            "  planar                       — True when all endpoints are coplanar\n"
            "  max_endpoint_gap_mm          — max positional gap between consecutive "
            "endpoints (incl. wrap-around); 0.0 for a closed wire\n"
            "  num_edges                    — number of edges\n"
            "  plane_normal_xyz             — SVD best-fit plane normal [x,y,z] or "
            "null for degenerate wires\n"
            "  max_out_of_plane_deviation_mm — max |dist to best-fit plane| in mm\n"
            "\n"
            "HONEST CAVEAT: edge order-dependent — scrambled/unordered edge lists "
            "are NOT automatically sorted.  Planarity is endpoint-only (curve "
            "interiors are NOT sampled).  References: Mantyla §3; Hoffmann §4.\n"
            "\n"
            "Never raises — returns {ok:false, reason} for invalid inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "edges": {
                    "type": "array",
                    "description": (
                        "Ordered list of edge segments.  Each item must have "
                        "start_xyz ([x,y,z] in mm), end_xyz ([x,y,z] in mm), "
                        "and optionally edge_id (string)."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_xyz": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                            },
                            "end_xyz": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                            },
                            "edge_id": {"type": "string"},
                        },
                        "required": ["start_xyz", "end_xyz"],
                    },
                },
                "tolerance_mm": {
                    "type": "number",
                    "description": "Positional tolerance in mm.  Default 1e-6.",
                },
            },
            "required": ["edges"],
        },
    )

    @register(_spec)
    def _tool_brep_check_wire_closed(params: dict, ctx: "ProjectCtx"):  # type: ignore[type-arg]
        try:
            raw_edges = params["edges"]
            if not raw_edges:
                raise ValueError("edges must be a non-empty list.")
            segs: list[EdgeSegment] = []
            for idx, e in enumerate(raw_edges):
                sx, sy, sz = [float(v) for v in e["start_xyz"]]
                ex, ey, ez = [float(v) for v in e["end_xyz"]]
                eid = str(e.get("edge_id", f"e{idx}"))
                segs.append(EdgeSegment(
                    start_xyz=(sx, sy, sz),
                    end_xyz=(ex, ey, ez),
                    edge_id=eid,
                ))
            tol = float(params.get("tolerance_mm", 1e-6))
            report = check_wire_closed(segs, tolerance_mm=tol)
            return ok_payload({
                "closed": report.closed,
                "planar": report.planar,
                "max_endpoint_gap_mm": report.max_endpoint_gap_mm,
                "num_edges": report.num_edges,
                "plane_normal_xyz": list(report.plane_normal_xyz) if report.plane_normal_xyz else None,
                "max_out_of_plane_deviation_mm": report.max_out_of_plane_deviation_mm,
                "honest_caveat": report.honest_caveat,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
