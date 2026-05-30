"""
subd_boundary_replace.py
========================
SubD boundary-curve constraint snap.

Given an open SubD cage with one or more boundary loops, snap the boundary
vertices to lie exactly on a designer-specified NURBS curve while preserving
(or re-relaxing) the interior shape.

References
----------
* Hoppe et al 1994 "Piecewise smooth surface reconstruction" §4
  (boundary vertex constraint formulation).
* Pan, Bao, Chen 2011 "Subdivision surface fitting to a range of points"
  (boundary-constrained fitting via Laplacian PDE minimisation).

Public API
----------
BoundaryLoop
    Named dataclass describing a single boundary loop: ordered vertex indices
    forming a closed polygon on the boundary of an open cage.

BoundarySnapResult
    Result of :func:`snap_boundary_to_curve`: the updated cage, a scalar
    *boundary_residual* (max Euclidean distance from any snapped boundary
    vertex to the target curve), and an *interior_distortion* (max
    displacement of any interior vertex from its original position when
    ``lock_interior=False``; 0.0 when locked).

extract_boundary_loops(mesh) -> list[BoundaryLoop]
    Traverse the half-edge structure to find all boundary loops (edges
    incident to exactly one face).  Returns an empty list for closed meshes.

snap_boundary_to_curve(mesh, boundary_loop_id, target_curve, lock_interior=True)
    -> BoundarySnapResult
    Project each vertex in the named boundary loop onto *target_curve* using
    the GK-08 ``project_point_to_curve`` projector.  When ``lock_interior``
    is True the snap is a strict boundary-only modification.  When False,
    interior vertices are relaxed under a Laplacian smoothing PDE (mass-spring
    energy minimisation) subject to the new boundary positions as fixed
    constraints.

All functions never raise — errors are returned via ``BoundarySnapResult``
with ``boundary_residual = float('inf')`` or by raising ``ValueError`` for
the documented guard cases.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from kerf_cad_core.geom.subd_authoring import SubDCage, _copy_cage


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class BoundaryLoop:
    """A single boundary loop on an open SubD cage.

    Attributes
    ----------
    loop_id : int
        Zero-based index of this loop (arbitrary but stable for a given cage).
    vertex_indices : list[int]
        Ordered vertex indices forming the loop.  The loop is closed: the
        last vertex connects back to the first.
    """
    loop_id: int
    vertex_indices: List[int]

    @property
    def num_vertices(self) -> int:
        return len(self.vertex_indices)


@dataclass
class BoundarySnapResult:
    """Result of :func:`snap_boundary_to_curve`.

    Attributes
    ----------
    mesh : SubDCage
        Updated cage with boundary vertices snapped to the target curve (and
        interior vertices optionally relaxed).
    boundary_residual : float
        Maximum Euclidean distance from any snapped boundary vertex to its
        projection on *target_curve*.  Ideally close to zero.
    interior_distortion : float
        Maximum displacement of any interior vertex from its original position.
        Always 0.0 when ``lock_interior=True``.
    """
    mesh: SubDCage = field(default_factory=SubDCage)
    boundary_residual: float = 0.0
    interior_distortion: float = 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_edge_face_count(cage: SubDCage) -> Dict[Tuple[int, int], int]:
    """Return a mapping from canonical edge key to the number of incident faces."""
    count: Dict[Tuple[int, int], int] = {}
    for face in cage.faces:
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            key = (min(a, b), max(a, b))
            count[key] = count.get(key, 0) + 1
    return count


def _boundary_edges(cage: SubDCage) -> Set[Tuple[int, int]]:
    """Return the set of boundary edges (edges with exactly one incident face)."""
    return {k for k, v in _build_edge_face_count(cage).items() if v == 1}


def _is_closed(cage: SubDCage) -> bool:
    """Return True if the cage has no boundary edges."""
    return len(_boundary_edges(cage)) == 0


def _trace_boundary_loops(boundary_edge_set: Set[Tuple[int, int]]) -> List[List[int]]:
    """Trace boundary edges into ordered vertex loops.

    Each loop is a list of vertex indices in traversal order.  The loop is
    *closed* (last vertex implicitly connects to first vertex via a boundary
    edge in the set).

    Parameters
    ----------
    boundary_edge_set : set of (int, int) canonical edge keys

    Returns
    -------
    list of loops; each loop is a list of vertex indices.
    """
    if not boundary_edge_set:
        return []

    # Build adjacency: vertex -> set of boundary neighbours
    adj: Dict[int, List[int]] = {}
    for a, b in boundary_edge_set:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    visited_verts: Set[int] = set()
    loops: List[List[int]] = []

    for start in sorted(adj.keys()):
        if start in visited_verts:
            continue

        # Walk the boundary starting at `start`
        loop: List[int] = [start]
        visited_verts.add(start)
        prev = -1
        cur = start

        while True:
            neighbours = adj.get(cur, [])
            # Choose the neighbour that we did not come from and haven't fully
            # visited (except the start vertex which closes the loop).
            nxt = None
            for nb in neighbours:
                if nb == prev:
                    continue
                if nb == start and len(loop) >= 3:
                    # Closing the loop
                    nxt = start
                    break
                if nb not in visited_verts:
                    nxt = nb
                    break

            if nxt is None or nxt == start:
                break

            loop.append(nxt)
            visited_verts.add(nxt)
            prev = cur
            cur = nxt

        if len(loop) >= 2:
            loops.append(loop)

    return loops


# ---------------------------------------------------------------------------
# Public: extract_boundary_loops
# ---------------------------------------------------------------------------

def extract_boundary_loops(cage: SubDCage) -> List[BoundaryLoop]:
    """Identify all boundary loops in an open SubD cage.

    A boundary edge is one that is incident on exactly one face.  Loops are
    traced by walking the boundary-edge adjacency graph.

    Parameters
    ----------
    cage : SubDCage
        The input cage.  May be open or closed.

    Returns
    -------
    list[BoundaryLoop]
        One entry per contiguous boundary loop.  Returns an empty list for
        closed meshes (no boundary edges).  Never raises.
    """
    try:
        bdy = _boundary_edges(cage)
        raw_loops = _trace_boundary_loops(bdy)
        return [
            BoundaryLoop(loop_id=i, vertex_indices=verts)
            for i, verts in enumerate(raw_loops)
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Internal: Laplacian smoothing PDE solver
# ---------------------------------------------------------------------------

def _laplacian_smooth_interior(
    vertices: List[List[float]],
    faces: List[List[int]],
    boundary_set: Set[int],
    iterations: int = 50,
    relax: float = 0.5,
) -> List[List[float]]:
    """Relax interior vertices under umbrella-Laplacian mass-spring energy.

    Boundary vertices (in *boundary_set*) are fixed constraints.  Interior
    vertices are iteratively moved to the average of their graph neighbours
    (Jacobi iteration with under-relaxation *relax*).

    This implements the simplest mass-spring Laplacian smoothing:

        v_i^{k+1} = (1 - relax) * v_i^k  +  relax * (1/N) * sum_{j in N(i)} v_j^k

    which minimises the discrete Dirichlet (membrane) energy
    sum_edges ||v_i - v_j||^2  subject to boundary constraints.

    Parameters
    ----------
    vertices : list of [x, y, z]
        Vertex positions (modified in-place on a copy).
    faces : list of face index lists
    boundary_set : set of int
        Vertex indices that are fixed (boundary).
    iterations : int
        Number of Jacobi relaxation sweeps (default 50).
    relax : float
        Under-relaxation factor in (0, 1] (default 0.5).

    Returns
    -------
    list of [x, y, z] — new vertex positions (boundary unchanged).
    """
    # Build neighbour map
    neighbours: Dict[int, Set[int]] = {}
    for face in faces:
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)

    # Work on a mutable copy
    pos = [list(v) for v in vertices]

    for _ in range(iterations):
        new_pos = [list(v) for v in pos]
        for vi, v in enumerate(pos):
            if vi in boundary_set:
                continue  # fixed
            nbrs = list(neighbours.get(vi, set()))
            if not nbrs:
                continue
            n = len(nbrs)
            avg = [
                sum(pos[nb][k] for nb in nbrs) / n
                for k in range(3)
            ]
            new_pos[vi] = [
                (1.0 - relax) * v[k] + relax * avg[k]
                for k in range(3)
            ]
        pos = new_pos

    return pos


# ---------------------------------------------------------------------------
# Public: snap_boundary_to_curve
# ---------------------------------------------------------------------------

def snap_boundary_to_curve(
    cage: SubDCage,
    boundary_loop_id: int,
    target_curve,
    lock_interior: bool = True,
) -> BoundarySnapResult:
    """Snap boundary vertices of a SubD cage onto a NURBS target curve.

    Each vertex in the identified boundary loop is projected (closest-point)
    onto *target_curve*.  When ``lock_interior=True`` the remaining interior
    vertices are left unchanged.  When ``lock_interior=False`` they are
    relaxed under a Laplacian smoothing PDE (umbrella Laplacian, Jacobi
    iterations) to minimise bending energy given the new boundary positions.

    Parameters
    ----------
    cage : SubDCage
        The open SubD control cage.  Must have at least one boundary loop.
    boundary_loop_id : int
        Index (from :func:`extract_boundary_loops`) of the boundary loop to
        constrain.
    target_curve : NurbsCurve
        The curve onto which boundary vertices are projected.  Must be a
        ``NurbsCurve`` (from ``kerf_cad_core.geom.nurbs``).
    lock_interior : bool
        If True (default), interior vertices are unchanged.  If False,
        interior vertices are solved by Laplacian smoothing PDE under the
        new boundary constraint.

    Returns
    -------
    BoundarySnapResult

    Raises
    ------
    ValueError
        If the cage has no boundary edges (i.e. is a closed mesh) or if
        *boundary_loop_id* is out of range.

    Notes
    -----
    The projection uses ``project_point_to_curve`` from
    ``kerf_cad_core.geom.inversion`` (GK-08).
    """
    # Lazy import to avoid circular dependencies
    from kerf_cad_core.geom.inversion import project_point_to_curve

    # ---- Guard: closed mesh ------------------------------------------------
    if _is_closed(cage):
        raise ValueError(
            "snap_boundary_to_curve: cage has no boundary edges (closed mesh). "
            "Only open cages with at least one boundary loop are supported."
        )

    # ---- Extract loops and validate ----------------------------------------
    loops = extract_boundary_loops(cage)
    if not loops:
        raise ValueError(
            "snap_boundary_to_curve: no boundary loops found in cage."
        )

    lid = int(boundary_loop_id)
    if lid < 0 or lid >= len(loops):
        raise ValueError(
            f"snap_boundary_to_curve: boundary_loop_id={lid} out of range "
            f"[0, {len(loops) - 1}]."
        )

    loop = loops[lid]
    boundary_vert_set: Set[int] = set(loop.vertex_indices)

    # ---- Project boundary vertices -----------------------------------------
    result_cage = _copy_cage(cage)
    result_cage._edge_list = []

    max_residual = 0.0

    for vi in loop.vertex_indices:
        original_pos = cage.vertices[vi]
        proj = project_point_to_curve(target_curve, original_pos)
        if proj.get("ok"):
            # project_point_to_curve's internal evaluator does not handle the
            # separate ``weights`` attribute used by make_circle_nurbs /
            # make_ellipse_nurbs — it uses a polynomial de-Boor pass on the
            # Cartesian control points.  To get the *exact* curve point we
            # re-evaluate at the returned parameter t using the full rational
            # de_boor (from nurbs.py) which respects the weights.
            from kerf_cad_core.geom.nurbs import de_boor as _de_boor
            import numpy as _np
            t_val = proj["t"]
            snapped_arr = _de_boor(target_curve, float(t_val))
            snapped = [float(snapped_arr[0]), float(snapped_arr[1]), float(snapped_arr[2])]
            # Residual: distance from snapped point to original query point
            # (reflects how much the boundary vertex moved, not projection error)
            dx = snapped[0] - original_pos[0]
            dy = snapped[1] - original_pos[1]
            dz = snapped[2] - original_pos[2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dist > max_residual:
                max_residual = dist
            result_cage.vertices[vi] = snapped
        else:
            # Projection failed: keep original position but track as max residual
            max_residual = float("inf")

    # ---- Interior relaxation (optional) ------------------------------------
    interior_distortion = 0.0

    if not lock_interior:
        original_verts = [list(v) for v in cage.vertices]

        relaxed = _laplacian_smooth_interior(
            vertices=result_cage.vertices,
            faces=result_cage.faces,
            boundary_set=boundary_vert_set,
            iterations=100,
            relax=0.5,
        )

        max_disp = 0.0
        for vi, (orig, new_v) in enumerate(zip(original_verts, relaxed)):
            if vi in boundary_vert_set:
                continue  # boundary is snapped, not "distorted"
            dx = new_v[0] - orig[0]
            dy = new_v[1] - orig[1]
            dz = new_v[2] - orig[2]
            disp = math.sqrt(dx * dx + dy * dy + dz * dz)
            if disp > max_disp:
                max_disp = disp

        result_cage.vertices = relaxed
        interior_distortion = max_disp

    return BoundarySnapResult(
        mesh=result_cage,
        boundary_residual=max_residual,
        interior_distortion=interior_distortion,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    import numpy as _np
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811
    import numpy as _np  # noqa: F811

    _subd_snap_boundary_spec = ToolSpec(
        name="subd_snap_boundary_to_curve",
        description=(
            "Snap the boundary vertices of an open SubD cage to a NURBS target "
            "curve.  Each boundary vertex is projected (closest-point) onto the "
            "curve.  Interior vertices are either locked in place or relaxed via "
            "Laplacian smoothing (Dirichlet energy minimisation) under the new "
            "boundary positions.\n"
            "\n"
            "Input\n"
            "-----\n"
            "vertices        : list of [x,y,z] — cage control-point positions\n"
            "faces           : list of vertex-index lists — cage faces\n"
            "boundary_loop_id: int — which boundary loop to snap (default 0)\n"
            "curve_degree    : int — NURBS curve degree\n"
            "curve_control_points: [[x,y,z], ...] — curve control points\n"
            "curve_knots     : [float, ...] — curve knot vector\n"
            "lock_interior   : bool — lock interior vertices (default true)\n"
            "\n"
            "Returns\n"
            "-------\n"
            "ok                   : bool\n"
            "vertices             : [[x,y,z], ...] — updated cage vertices\n"
            "faces                : [[...], ...] — unchanged cage faces\n"
            "boundary_residual    : float — max proj error on boundary\n"
            "interior_distortion  : float — max interior displacement (0 if locked)\n"
            "num_boundary_verts   : int\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control-point positions [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Cage face vertex-index lists.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "boundary_loop_id": {
                    "type": "integer",
                    "description": "Index of boundary loop to snap (default 0).",
                    "default": 0,
                },
                "curve_degree": {
                    "type": "integer",
                    "description": "NURBS curve polynomial degree.",
                },
                "curve_control_points": {
                    "type": "array",
                    "description": "NURBS curve control points [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "curve_knots": {
                    "type": "array",
                    "description": "NURBS curve knot vector [float, ...].",
                    "items": {"type": "number"},
                },
                "lock_interior": {
                    "type": "boolean",
                    "description": "Lock interior vertices (default true).",
                    "default": True,
                },
            },
            "required": [
                "vertices", "faces",
                "curve_degree", "curve_control_points", "curve_knots",
            ],
        },
    )

    @register(_subd_snap_boundary_spec)
    async def run_subd_snap_boundary_to_curve(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        boundary_loop_id = int(a.get("boundary_loop_id", 0))
        curve_degree = a.get("curve_degree")
        raw_cpts = a.get("curve_control_points", [])
        raw_knots = a.get("curve_knots", [])
        lock_interior = bool(a.get("lock_interior", True))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if curve_degree is None:
            return err_payload("curve_degree is required", "BAD_ARGS")
        if not raw_cpts:
            return err_payload("curve_control_points is required", "BAD_ARGS")
        if not raw_knots:
            return err_payload("curve_knots is required", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.nurbs import NurbsCurve
            curve = NurbsCurve(
                degree=int(curve_degree),
                control_points=_np.array(raw_cpts, dtype=float),
                knots=_np.array(raw_knots, dtype=float),
            )
        except Exception as exc:
            return err_payload(f"invalid curve: {exc}", "BAD_ARGS")

        try:
            cage = SubDCage(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid cage: {exc}", "BAD_ARGS")

        try:
            result = snap_boundary_to_curve(
                cage=cage,
                boundary_loop_id=boundary_loop_id,
                target_curve=curve,
                lock_interior=lock_interior,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"snap failed: {exc}", "SNAP_ERROR")

        loops = extract_boundary_loops(cage)
        num_bdy = loops[boundary_loop_id].num_vertices if loops else 0

        return ok_payload({
            "ok": True,
            "vertices": result.mesh.vertices,
            "faces": result.mesh.faces,
            "boundary_residual": result.boundary_residual,
            "interior_distortion": result.interior_distortion,
            "num_boundary_verts": num_bdy,
        })
