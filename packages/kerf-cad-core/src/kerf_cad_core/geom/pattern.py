"""GK-87 Pattern (linear / circular / path, kernel-level).

Duplicate a :class:`~kerf_cad_core.geom.brep.Body` N times along a linear,
circular, or arbitrary-path rail.  The implementation is **pure-Python** — no
OCCT dependency — and works on any ``Body`` produced by the analytic primitive
constructors in :mod:`kerf_cad_core.geom.brep_build`.

Public API
----------
linear_pattern(body, direction, spacing, count) -> List[Body]
    Duplicate *body* *count* times (including the original) offset by
    multiples of ``spacing`` along *direction*.

circular_pattern(body, axis_point, axis_dir, count, total_angle=2π) -> List[Body]
    Duplicate *body* *count* times evenly around a rotation axis, returning
    one body per angular step starting at 0 (the original pose included in
    the returned list).

path_pattern(body, path_curve, count) -> List[Body]
    Distribute *count* copies of *body* at evenly-spaced parameter values
    along *path_curve* (any object with an ``evaluate(t) -> np.ndarray``
    method).  The first copy is at ``t = 0``, the last at ``t = 1``.

Internals
---------
The module reconstructs geometry objects with translated / rotated coordinates
rather than mutating the input ``Body``.  A helper ``_transform_body`` walks the
entire B-rep topology and applies the supplied 4×4 homogeneous matrix.

Transforms are built from:
* ``_translate_matrix(offset)`` — pure translation.
* ``_rotate_matrix(axis_point, axis_dir, angle)`` — rotation about an
  arbitrary axis (Rodrigues formula).
"""

from __future__ import annotations

import copy
import math
from typing import List, Sequence

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Vertex,
    Edge,
    Face,
    Loop,
    Coedge,
    Shell,
    Solid,
    Line3,
    CircleArc3,
    Plane,
    CylinderSurface,
    SphereSurface,
)


# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-15:
        raise ValueError("Zero-length vector cannot be normalised")
    return v / n


def _translate_matrix(offset: np.ndarray) -> np.ndarray:
    """Return a 4×4 homogeneous translation matrix."""
    m = np.eye(4)
    m[:3, 3] = offset
    return m


def _rotate_matrix(axis_point: np.ndarray, axis_dir: np.ndarray, angle: float) -> np.ndarray:
    """Return a 4×4 homogeneous rotation matrix about an arbitrary axis.

    Rodrigues' rotation formula.
    """
    k = _unit(np.asarray(axis_dir, dtype=float))
    K = np.array([
        [0.0, -k[2], k[1]],
        [k[2], 0.0, -k[0]],
        [-k[1], k[0], 0.0],
    ])
    R3 = np.eye(3) + math.sin(angle) * K + (1.0 - math.cos(angle)) * (K @ K)
    # Combine: first translate to origin, rotate, translate back
    # T_back @ R @ T_to_origin
    p = np.asarray(axis_point, dtype=float)
    m = np.eye(4)
    m[:3, :3] = R3
    # Translation part: R * (-p) + p
    m[:3, 3] = R3 @ (-p) + p
    return m


def _apply_matrix_to_point(m: np.ndarray, pt: np.ndarray) -> np.ndarray:
    """Apply a 4×4 homogeneous matrix to a 3-D point."""
    h = np.ones(4)
    h[:3] = pt
    return (m @ h)[:3]


def _apply_matrix_to_vec(m: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Apply the rotational part of a 4×4 matrix to a direction vector."""
    return m[:3, :3] @ v


# ---------------------------------------------------------------------------
# Geometry object transformers
# ---------------------------------------------------------------------------

def _transform_geom_obj(geom, m: np.ndarray):
    """Return a new geometry object (surface or curve) with the transform applied.

    Handles the analytic types in :mod:`kerf_cad_core.geom.brep` plus
    :class:`~kerf_cad_core.geom.nurbs.NurbsCurve` / ``NurbsSurface``.
    """
    if geom is None:
        return None

    if isinstance(geom, Line3):
        return Line3(
            _apply_matrix_to_point(m, geom.p0),
            _apply_matrix_to_point(m, geom.p1),
        )

    if isinstance(geom, CircleArc3):
        new_center = _apply_matrix_to_point(m, geom.center)
        new_x = _apply_matrix_to_vec(m, geom.x_axis)
        new_y = _apply_matrix_to_vec(m, geom.y_axis)
        arc = CircleArc3(
            center=new_center,
            radius=geom.radius,
            x_axis=new_x,
            y_axis=new_y,
            t0=geom.t0,
            t1=geom.t1,
        )
        # CircleArc3.__post_init__ re-normalises axes; preserve pre-normalised values
        arc.x_axis = _unit(new_x)
        arc.y_axis = _unit(new_y)
        return arc

    if isinstance(geom, Plane):
        new_origin = _apply_matrix_to_point(m, geom.origin)
        new_x = _apply_matrix_to_vec(m, geom.x_axis)
        new_y = _apply_matrix_to_vec(m, geom.y_axis)
        return Plane(origin=new_origin, x_axis=new_x, y_axis=new_y)

    if isinstance(geom, CylinderSurface):
        new_center = _apply_matrix_to_point(m, geom.center)
        new_axis = _apply_matrix_to_vec(m, geom.axis)
        new_xref = _apply_matrix_to_vec(m, geom.x_ref)
        return CylinderSurface(
            center=new_center,
            axis=new_axis,
            radius=geom.radius,
            x_ref=new_xref,
        )

    if isinstance(geom, SphereSurface):
        new_center = _apply_matrix_to_point(m, geom.center)
        return SphereSurface(center=new_center, radius=geom.radius)

    # NurbsCurve / NurbsSurface: operate on control points
    try:
        from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
        if isinstance(geom, NurbsCurve):
            new_ctrl = np.array([_apply_matrix_to_point(m, cp) for cp in geom.control_points])
            return NurbsCurve(
                degree=geom.degree,
                knots=geom.knots.copy(),
                control_points=new_ctrl,
            )
        if isinstance(geom, NurbsSurface):
            rows, cols, _ = geom.control_points.shape
            new_ctrl = geom.control_points.copy()
            for i in range(rows):
                for j in range(cols):
                    new_ctrl[i, j] = _apply_matrix_to_point(m, geom.control_points[i, j])
            return NurbsSurface(
                degree_u=geom.degree_u,
                degree_v=geom.degree_v,
                knots_u=geom.knots_u.copy(),
                knots_v=geom.knots_v.copy(),
                control_points=new_ctrl,
            )
    except ImportError:
        pass

    # Unknown type: return a shallow copy (best-effort)
    return copy.copy(geom)


# ---------------------------------------------------------------------------
# Body transformer (deep structural copy + geometry transform)
# ---------------------------------------------------------------------------

def _transform_body(body: Body, m: np.ndarray) -> Body:
    """Return a new :class:`Body` with every geometric entity transformed by *m*.

    The new body has entirely fresh topology objects (vertices, edges, faces,
    shells, solids) so the result is independent of the source body.
    """
    # -- Vertices --
    old_to_new_vertex: dict = {}

    def _clone_vertex(v: Vertex) -> Vertex:
        if id(v) not in old_to_new_vertex:
            new_pt = _apply_matrix_to_point(m, v.point)
            nv = Vertex(new_pt, v.tol)
            old_to_new_vertex[id(v)] = nv
        return old_to_new_vertex[id(v)]

    # -- Edges --
    old_to_new_edge: dict = {}

    def _clone_edge(e: Edge) -> Edge:
        if id(e) not in old_to_new_edge:
            new_geom = _transform_geom_obj(e.curve, m)
            new_vs = _clone_vertex(e.v_start)
            new_ve = _clone_vertex(e.v_end)
            ne = Edge(new_geom, e.t0, e.t1, new_vs, new_ve, e.tol)
            old_to_new_edge[id(e)] = ne
        return old_to_new_edge[id(e)]

    def _clone_coedge(ce: Coedge) -> Coedge:
        return Coedge(_clone_edge(ce.edge), ce.orientation)

    def _clone_loop(lp: Loop) -> Loop:
        new_coedges = [_clone_coedge(ce) for ce in lp.coedges]
        nl = Loop(new_coedges, is_outer=lp.is_outer)
        # Carry over anchor vertex if present (mvfs seed loops)
        av = getattr(lp, "_anchor_vertex", None)
        if av is not None:
            nl._anchor_vertex = _clone_vertex(av)
        return nl

    def _clone_face(f: Face) -> Face:
        new_srf = _transform_geom_obj(f.surface, m)
        new_loops = [_clone_loop(lp) for lp in f.loops]
        return Face(new_srf, new_loops, orientation=f.orientation, tol=f.tol)

    def _clone_shell(sh: Shell) -> Shell:
        new_faces = [_clone_face(f) for f in sh.faces]
        ns = Shell(new_faces, is_closed=sh.is_closed)
        return ns

    def _clone_solid(sol: Solid) -> Solid:
        new_shells = [_clone_shell(sh) for sh in sol.shells]
        return Solid(new_shells)

    new_solids = [_clone_solid(sol) for sol in body.solids]
    new_free_shells = [_clone_shell(sh) for sh in body.shells]
    new_wires = [_clone_loop(w) for w in body.wires]
    return Body(solids=new_solids, shells=new_free_shells, wires=new_wires)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def linear_pattern(
    body: Body,
    direction: Sequence[float],
    spacing: float,
    count: int,
) -> List[Body]:
    """Return *count* copies of *body* spaced *spacing* apart along *direction*.

    The first element of the returned list is a copy of *body* at its original
    position (offset = 0).  Subsequent elements are offset by ``i * spacing *
    unit(direction)`` for *i* in 1 .. count-1.

    Parameters
    ----------
    body:
        Source body to duplicate.
    direction:
        3-D vector giving the direction of spacing (need not be unit length).
    spacing:
        Distance between consecutive copies (in model units).
    count:
        Total number of bodies to produce (>= 1).  count=1 returns a single
        copy at the original position.

    Returns
    -------
    List of *count* independent :class:`Body` objects.
    """
    if count < 1:
        raise ValueError(f"linear_pattern: count must be >= 1, got {count}")
    if spacing < 0:
        raise ValueError(f"linear_pattern: spacing must be non-negative, got {spacing}")

    d = _unit(np.asarray(direction, dtype=float))
    result: List[Body] = []
    for i in range(count):
        offset = float(i) * spacing * d
        m = _translate_matrix(offset)
        result.append(_transform_body(body, m))
    return result


def circular_pattern(
    body: Body,
    axis_point: Sequence[float],
    axis_dir: Sequence[float],
    count: int,
    total_angle: float = 2.0 * math.pi,
) -> List[Body]:
    """Return *count* copies of *body* rotated evenly around an axis.

    The first element is a copy of *body* at angle=0 (its original orientation
    relative to the axis).  Subsequent copies are rotated by
    ``i * total_angle / count`` for *i* in 1 .. count-1.

    Parameters
    ----------
    body:
        Source body to duplicate.
    axis_point:
        A point on the rotation axis.
    axis_dir:
        Direction of the rotation axis.
    count:
        Total number of bodies (>= 1).
    total_angle:
        Total angular sweep in radians (default 2π = full circle).

    Returns
    -------
    List of *count* independent :class:`Body` objects.
    """
    if count < 1:
        raise ValueError(f"circular_pattern: count must be >= 1, got {count}")

    ap = np.asarray(axis_point, dtype=float)
    ad = np.asarray(axis_dir, dtype=float)
    step = total_angle / count

    result: List[Body] = []
    for i in range(count):
        angle = float(i) * step
        m = _rotate_matrix(ap, ad, angle)
        result.append(_transform_body(body, m))
    return result


def path_pattern(
    body: Body,
    path_curve,
    count: int,
) -> List[Body]:
    """Return *count* copies of *body* distributed along *path_curve*.

    Copies are placed at parameter values ``t = i / (count - 1)`` for
    *i* in 0 .. count-1 (or ``t = 0`` when count=1).  Each copy is
    translated so that its **original centroid** (computed as the mean of
    all vertex positions) moves to ``path_curve.evaluate(t)``.

    Parameters
    ----------
    body:
        Source body to duplicate.
    path_curve:
        Any object that implements ``evaluate(t: float) -> np.ndarray``
        for *t* in [0, 1].
    count:
        Total number of bodies (>= 1).

    Returns
    -------
    List of *count* independent :class:`Body` objects.
    """
    if count < 1:
        raise ValueError(f"path_pattern: count must be >= 1, got {count}")

    # Compute centroid of the source body (mean vertex position)
    verts = body.all_vertices()
    if not verts:
        centroid = np.zeros(3)
    else:
        centroid = np.mean([v.point for v in verts], axis=0)

    result: List[Body] = []
    for i in range(count):
        t = 0.0 if count == 1 else float(i) / float(count - 1)
        target_pt = np.asarray(path_curve.evaluate(t), dtype=float)
        offset = target_pt - centroid
        m = _translate_matrix(offset)
        result.append(_transform_body(body, m))
    return result
