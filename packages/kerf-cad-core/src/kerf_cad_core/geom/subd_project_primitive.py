"""
subd_project_primitive.py
=========================
Project SubD cage vertices onto analytic primitive surfaces (sphere, cylinder,
plane).  After projection the cage vertex positions lie exactly on the primitive
surface; topology (faces, edges, creases, sharpness) is preserved unchanged.

Use case: a coarse cage that *approximates* a primitive (e.g. a unit-cube cage
for a sphere) can be snapped to the exact analytic primitive before further
subdivision.  Two levels of Catmull-Clark subdivision on the projected cage
produce a limit surface whose deviation from the true primitive is far smaller
than the pre-projection approximation.

Public API
----------
ProjectionReport
    Dataclass: max_projection_distance (largest vertex displacement), mean
    projection distance, num_vertices.

project_cage_to_sphere(cage, center, radius) -> (SubDCage, ProjectionReport)
    Project every cage vertex onto the sphere surface.
    Formula: p' = center + radius * (p - center) / |p - center|
    Degenerate vertex coincident with center is left unchanged.

project_cage_to_cylinder(cage, axis_origin, axis_direction, radius)
    -> (SubDCage, ProjectionReport)
    Project every cage vertex onto the infinite right-circular cylinder.
    Formula: drop vertex onto the axis line, then offset radially.
    Degenerate vertex exactly on the axis is left unchanged.

project_cage_to_plane(cage, origin, normal) -> (SubDCage, ProjectionReport)
    Project every cage vertex onto the plane.
    Formula: p' = p - dot(p - origin, n_hat) * n_hat
    If normal is zero the cage is returned unchanged.

Honest flag
-----------
These operations displace *vertex positions only*.  They do NOT preserve face
areas, edge lengths, or dihedral angles.  If the original cage is a rough
approximation the projected cage will likely have non-uniform quads.  Run
``subd_loop_cut`` / ``subd_bevel`` after projection to redistribute topology if
needed.

All functions are pure-Python.  No OCCT, no NumPy required.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from kerf_cad_core.geom.subd_authoring import SubDCage


# ---------------------------------------------------------------------------
# ProjectionReport
# ---------------------------------------------------------------------------

@dataclass
class ProjectionReport:
    """Statistics from a cage→primitive projection.

    Attributes
    ----------
    num_vertices : int
        Number of cage vertices processed.
    max_projection_distance : float
        Largest displacement of any single vertex.
    mean_projection_distance : float
        Mean displacement across all vertices.
    honest_flag : bool
        Always True — face areas and edge lengths are NOT preserved.
    honest_note : str
        Human-readable caveat about what is and isn't preserved.
    """

    num_vertices: int = 0
    max_projection_distance: float = 0.0
    mean_projection_distance: float = 0.0
    honest_flag: bool = True
    honest_note: str = (
        "Vertex positions are snapped to the primitive surface. "
        "Face areas, edge lengths, and dihedral angles are NOT preserved."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _vec3_sub(a: List[float], b: List[float]) -> List[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _vec3_add(a: List[float], b: List[float]) -> List[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _vec3_scale(v: List[float], s: float) -> List[float]:
    return [v[0] * s, v[1] * s, v[2] * s]


def _vec3_dot(a: List[float], b: List[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec3_len(v: List[float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _vec3_normalize(v: List[float]) -> Tuple[List[float], float]:
    """Return (unit_vector, original_length).  Returns zero-vector + 0 if degenerate."""
    mag = _vec3_len(v)
    if mag < 1e-300:
        return [0.0, 0.0, 0.0], 0.0
    return [v[0] / mag, v[1] / mag, v[2] / mag], mag


def _vec3_dist(a: List[float], b: List[float]) -> float:
    return _vec3_len(_vec3_sub(a, b))


def _copy_cage(cage: SubDCage) -> SubDCage:
    """Deep-copy a SubDCage, preserving all metadata."""
    new_cage = SubDCage(
        vertices=[list(v) for v in cage.vertices],
        faces=[list(f) for f in cage.faces],
        sharpness=dict(cage.sharpness),
        bevel_weights=dict(cage.bevel_weights),
        _edge_list=list(cage._edge_list),
    )
    return new_cage


def _build_report(original_verts: List[List[float]],
                  projected_verts: List[List[float]]) -> ProjectionReport:
    n = len(original_verts)
    if n == 0:
        return ProjectionReport(num_vertices=0)
    dists = [_vec3_dist(original_verts[i], projected_verts[i]) for i in range(n)]
    return ProjectionReport(
        num_vertices=n,
        max_projection_distance=max(dists),
        mean_projection_distance=sum(dists) / n,
    )


# ---------------------------------------------------------------------------
# project_cage_to_sphere
# ---------------------------------------------------------------------------

def project_cage_to_sphere(
    cage: SubDCage,
    center: Sequence[float],
    radius: float,
) -> Tuple[SubDCage, ProjectionReport]:
    """Project every cage vertex onto a sphere.

    Parameters
    ----------
    cage : SubDCage
        Input control cage (not mutated).
    center : [cx, cy, cz]
        Sphere center.
    radius : float
        Sphere radius.  Must be positive; clamped to 1e-9 if smaller.

    Returns
    -------
    (SubDCage, ProjectionReport)
        A new cage with all vertices on the sphere surface, plus stats.

    Formula
    -------
    p' = center + radius * (p - center) / |p - center|
    Degenerate (p == center): vertex left unchanged.

    Notes
    -----
    Face areas and edge lengths are NOT preserved (honest flag).
    """
    c = [float(center[0]), float(center[1]), float(center[2])]
    r = max(float(radius), 1e-9)

    out = _copy_cage(cage)
    orig = [list(v) for v in cage.vertices]

    for i, v in enumerate(out.vertices):
        d = _vec3_sub(v, c)
        unit, mag = _vec3_normalize(d)
        if mag < 1e-12:
            # vertex coincides with center — leave unchanged
            continue
        out.vertices[i] = _vec3_add(c, _vec3_scale(unit, r))

    report = _build_report(orig, out.vertices)
    return out, report


# ---------------------------------------------------------------------------
# project_cage_to_cylinder
# ---------------------------------------------------------------------------

def project_cage_to_cylinder(
    cage: SubDCage,
    axis_origin: Sequence[float],
    axis_direction: Sequence[float],
    radius: float,
) -> Tuple[SubDCage, ProjectionReport]:
    """Project every cage vertex onto an infinite right-circular cylinder.

    Parameters
    ----------
    cage : SubDCage
        Input control cage (not mutated).
    axis_origin : [ox, oy, oz]
        A point on the cylinder axis.
    axis_direction : [dx, dy, dz]
        Direction vector of the cylinder axis (need not be unit length).
    radius : float
        Cylinder radius.  Must be positive; clamped to 1e-9 if smaller.

    Returns
    -------
    (SubDCage, ProjectionReport)
        A new cage with all vertices on the cylinder surface, plus stats.

    Algorithm
    ---------
    1. Project vertex onto axis line to find foot_point.
    2. Compute radial vector from axis to vertex (perpendicular to axis).
    3. Scale radial vector to radius.
    4. New position = foot_point + scaled_radial.
    Degenerate (radial magnitude == 0, vertex on axis): left unchanged.

    Notes
    -----
    The cylinder is infinite — no height capping.
    Face areas and edge lengths are NOT preserved (honest flag).
    """
    ao = [float(axis_origin[0]), float(axis_origin[1]), float(axis_origin[2])]
    axis_unit, axis_mag = _vec3_normalize(
        [float(axis_direction[0]), float(axis_direction[1]), float(axis_direction[2])]
    )
    r = max(float(radius), 1e-9)

    if axis_mag < 1e-12:
        # degenerate axis — return unchanged
        return _copy_cage(cage), ProjectionReport(
            num_vertices=len(cage.vertices),
            max_projection_distance=0.0,
            mean_projection_distance=0.0,
        )

    out = _copy_cage(cage)
    orig = [list(v) for v in cage.vertices]

    for i, v in enumerate(out.vertices):
        # vector from axis_origin to vertex
        p_minus_o = _vec3_sub(v, ao)
        # project onto axis
        t = _vec3_dot(p_minus_o, axis_unit)
        # foot point on axis
        foot = _vec3_add(ao, _vec3_scale(axis_unit, t))
        # radial vector (perpendicular to axis)
        radial = _vec3_sub(v, foot)
        radial_unit, radial_mag = _vec3_normalize(radial)
        if radial_mag < 1e-12:
            # vertex is on the axis — leave unchanged
            continue
        out.vertices[i] = _vec3_add(foot, _vec3_scale(radial_unit, r))

    report = _build_report(orig, out.vertices)
    return out, report


# ---------------------------------------------------------------------------
# project_cage_to_plane
# ---------------------------------------------------------------------------

def project_cage_to_plane(
    cage: SubDCage,
    origin: Sequence[float],
    normal: Sequence[float],
) -> Tuple[SubDCage, ProjectionReport]:
    """Project every cage vertex onto a plane.

    Parameters
    ----------
    cage : SubDCage
        Input control cage (not mutated).
    origin : [ox, oy, oz]
        Any point on the plane.
    normal : [nx, ny, nz]
        Plane normal vector (need not be unit length).

    Returns
    -------
    (SubDCage, ProjectionReport)
        A new cage with all vertices on the plane, plus stats.

    Formula
    -------
    p' = p - dot(p - origin, n_hat) * n_hat
    If normal is zero, the cage is returned unchanged.

    Notes
    -----
    Face areas and edge lengths are NOT preserved (honest flag).
    """
    o = [float(origin[0]), float(origin[1]), float(origin[2])]
    n_hat, n_mag = _vec3_normalize(
        [float(normal[0]), float(normal[1]), float(normal[2])]
    )

    if n_mag < 1e-12:
        return _copy_cage(cage), ProjectionReport(
            num_vertices=len(cage.vertices),
            max_projection_distance=0.0,
            mean_projection_distance=0.0,
        )

    out = _copy_cage(cage)
    orig = [list(v) for v in cage.vertices]

    for i, v in enumerate(out.vertices):
        p_minus_o = _vec3_sub(v, o)
        signed_dist = _vec3_dot(p_minus_o, n_hat)
        out.vertices[i] = _vec3_sub(v, _vec3_scale(n_hat, signed_dist))

    report = _build_report(orig, out.vertices)
    return out, report
