"""GK-122: Interference / collision detection between two Body objects.
GK-123: Clearance / minimum-gap analysis between two Body objects.
GK-124: Mate constraint solver (coincident / concentric / distance / angle).

Pure-Python implementation (no OCCT dependency). Uses :func:`body_intersection`
(GK-18) to compute the overlapping region, then :func:`body_mass_props` to
measure its volume.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body, SphereSurface, CylinderSurface, TorusSurface, Plane
from kerf_cad_core.geom.boolean import body_intersection
from kerf_cad_core.geom.mass_props import body_mass_props

# Type alias for a 3-D point returned as a plain list of floats.
Point3 = List[float]


# ---------------------------------------------------------------------------
# Internal helpers: surface parameter-domain detection
# ---------------------------------------------------------------------------

def _face_surface_samples(face, face_grid: int = 6) -> list:
    """Return a flat list of 3-D sample points for *face*'s underlying surface.

    The parameter domain is determined as follows:

    * :class:`~kerf_cad_core.geom.brep.SphereSurface`:
      ``u ∈ [0, 2π], v ∈ [−π/2, π/2]``
    * :class:`~kerf_cad_core.geom.brep.CylinderSurface` /
      :class:`~kerf_cad_core.geom.brep.TorusSurface`:
      ``u ∈ [0, 2π]``; ``v`` bounded by projecting loop vertices onto axis.
    * :class:`~kerf_cad_core.geom.brep.Plane` and everything else:
      Derive UV bounds by projecting all loop vertices onto the surface axes
      (or fall back to ``[0, 1] × [0, 1]`` if no loop data is available).
    """
    surf = face.surface
    pts: list = []

    try:
        if isinstance(surf, SphereSurface):
            us = np.linspace(0.0, 2.0 * math.pi, face_grid, endpoint=False)
            # Always include the equator (v=0) and the poles in the latitude
            # grid so that the closest-point estimate is tight regardless of
            # which axis the separation vector points along.
            vs_base = np.linspace(-math.pi / 2.0, math.pi / 2.0, face_grid)
            vs = np.unique(np.concatenate([vs_base, [0.0]]))
            for u in us:
                for v in vs:
                    p = surf.evaluate(float(u), float(v))
                    pts.append(p.tolist())
            return pts

        # Gather 3-D vertex positions from all loops on this face.
        vert_pts = []
        for loop in face.loops:
            for v in loop.vertices():
                vert_pts.append(v.point)

        if isinstance(surf, (CylinderSurface, TorusSurface)):
            # Full angular sweep.
            us = np.linspace(0.0, 2.0 * math.pi, face_grid, endpoint=False)
            # v range: project vertex positions onto the axis direction.
            if vert_pts and isinstance(surf, CylinderSurface):
                axis = surf.axis
                centre = surf.center
                projs = [float(np.dot(p - centre, axis)) for p in vert_pts]
                v0, v1 = min(projs), max(projs)
            else:
                v0, v1 = 0.0, 1.0
            vs = np.linspace(v0, v1, face_grid)
            for u in us:
                for v in vs:
                    p = surf.evaluate(float(u), float(v))
                    pts.append(p.tolist())
            return pts

        # Generic / Plane: project vertices to derive UV bounds.
        if vert_pts and isinstance(surf, Plane):
            origin = surf.origin
            xa = surf.x_axis
            ya = surf.y_axis
            us_v = [float(np.dot(p - origin, xa)) for p in vert_pts]
            vs_v = [float(np.dot(p - origin, ya)) for p in vert_pts]
            u0, u1 = min(us_v), max(us_v)
            v0, v1 = min(vs_v), max(vs_v)
        else:
            u0, u1, v0, v1 = 0.0, 1.0, 0.0, 1.0

        us = np.linspace(u0, u1, face_grid)
        vs = np.linspace(v0, v1, face_grid)
        for u in us:
            for v in vs:
                p = surf.evaluate(float(u), float(v))
                pts.append(p.tolist())

    except Exception:  # pragma: no cover – defensive for exotic surface types
        pass

    return pts


def interference(
    body_a: Body,
    body_b: Body,
    tol: float = 1e-6,
    vol_tol: float = 1e-10,
) -> dict:
    """Detect geometric interference (overlap) between two solid bodies.

    Parameters
    ----------
    body_a:
        First :class:`~kerf_cad_core.geom.brep.Body`.
    body_b:
        Second :class:`~kerf_cad_core.geom.brep.Body`.
    tol:
        Geometric tolerance forwarded to :func:`body_intersection`.
    vol_tol:
        Volume threshold below which the intersection is treated as empty
        (handles degenerate face-touching / edge-touching cases that produce
        a zero-volume shell).  Default 1e-10.

    Returns
    -------
    dict with keys:

    ``"interferes"``
        ``True`` when the overlap volume exceeds *vol_tol*.
    ``"volume"``
        Absolute volume of the intersection region (``0.0`` when disjoint).
    ``"region"``
        The intersection :class:`~kerf_cad_core.geom.brep.Body` when
        *interferes* is ``True``, otherwise ``None``.
    """
    region = body_intersection(body_a, body_b, tol=tol)

    # An empty Body (no faces) means the inputs are disjoint.
    if not region.all_faces():
        return {"interferes": False, "volume": 0.0, "region": None}

    props = body_mass_props(region)
    vol = abs(props["volume"])

    if vol <= vol_tol:
        return {"interferes": False, "volume": 0.0, "region": None}

    return {"interferes": True, "volume": vol, "region": region}


# ---------------------------------------------------------------------------
# GK-123: Clearance / minimum-gap analysis
# ---------------------------------------------------------------------------

def _sample_body_points(
    body: Body,
    edge_samples: int = 8,
    face_grid: int = 6,
) -> np.ndarray:
    """Return a (N, 3) array of representative surface sample points for *body*.

    Strategy (pure-Python, no OCCT):
      1. All B-rep vertices.
      2. Interior samples along every edge (``edge_samples`` per edge).
      3. Grid samples over each face's underlying surface (``face_grid × face_grid``
         per face), using type-specific parameter domains (see
         :func:`_face_surface_samples`).
      4. If the body has *no* vertices (degenerate), fall back to the origin so
         that the caller still gets a non-empty array.
    """
    pts: list = []

    # 1. Vertices
    for v in body.all_vertices():
        pts.append(v.point.tolist())

    # 2. Edge interior samples
    for edge in body.all_edges():
        ts = np.linspace(edge.t0, edge.t1, edge_samples + 2)[1:-1]
        for t in ts:
            try:
                p = edge.point(float(t))
                pts.append(p.tolist())
            except Exception:  # pragma: no cover – defensive
                pass

    # 3. Face surface grid samples
    for face in body.all_faces():
        pts.extend(_face_surface_samples(face, face_grid=face_grid))

    if not pts:
        pts.append([0.0, 0.0, 0.0])

    return np.array(pts, dtype=float)


def _closest_pair(
    pts_a: np.ndarray,
    pts_b: np.ndarray,
) -> Tuple[int, int, float]:
    """Brute-force O(|A|·|B|) closest pair search.

    Returns ``(idx_a, idx_b, distance)``.

    For typical B-rep bodies (hundreds of sample points) this is fast enough.
    A vectorised implementation avoids a Python loop over all pairs.
    """
    # Compute all pairwise distances in one vectorised call.
    # Shape: (len_a, 1, 3) - (1, len_b, 3) → (len_a, len_b, 3)
    diff = pts_a[:, np.newaxis, :] - pts_b[np.newaxis, :, :]  # (A, B, 3)
    dist2 = np.einsum("ijk,ijk->ij", diff, diff)               # (A, B)
    flat_idx = int(np.argmin(dist2))
    ia = flat_idx // pts_b.shape[0]
    ib = flat_idx % pts_b.shape[0]
    return ia, ib, float(math.sqrt(dist2[ia, ib]))


def clearance(
    body_a: Body,
    body_b: Body,
    edge_samples: int = 8,
    face_grid: int = 6,
) -> dict:
    """Compute the minimum gap (clearance) between two :class:`Body` objects.

    The algorithm samples vertices and edge-interior points from each body's
    B-rep topology, then finds the closest pair of sample points via a
    vectorised brute-force search.  For disjoint convex bodies the vertex /
    edge samples are sufficient to locate the true minimum gap; for non-convex
    bodies the result is an upper-bound approximation whose accuracy improves
    with *edge_samples*.

    Parameters
    ----------
    body_a, body_b:
        The two :class:`~kerf_cad_core.geom.brep.Body` objects to analyse.
        They may be disjoint, touching, or overlapping.
    edge_samples:
        Number of interior sample points taken along each B-rep edge
        (in addition to the two endpoint vertices).  Default ``8``.

    Returns
    -------
    dict with keys:

    ``"gap"``
        Minimum distance between the two bodies' surface samples.
        Returns ``0.0`` (or a small negative value from the sample
        approximation) when the bodies overlap.
    ``"witness_a"``
        :data:`Point3` — the sample point on *body_a* closest to *body_b*.
    ``"witness_b"``
        :data:`Point3` — the sample point on *body_b* closest to *body_a*.

    Notes
    -----
    * Pure-Python / NumPy — no OCCT dependency.
    * The gap value is the *sample-based* distance; for curved surfaces it is
      an approximation (always ≥ the true minimum gap for convex shapes).
    * To detect interference (gap < 0), use :func:`interference` which
      computes the exact boolean intersection volume.

    Examples
    --------
    Two unit spheres with centres 5 units apart, radii 1 each::

        result = clearance(sphere_a, sphere_b)
        # result["gap"] ≈ 3.0  (5 − 1 − 1)
    """
    pts_a = _sample_body_points(body_a, edge_samples=edge_samples, face_grid=face_grid)
    pts_b = _sample_body_points(body_b, edge_samples=edge_samples, face_grid=face_grid)

    ia, ib, gap = _closest_pair(pts_a, pts_b)

    # When bodies overlap the surface-sample distance is always ≥ 0 because
    # all samples lie on the outer surface.  Detect interference and return
    # gap = 0.0 so callers can test ``gap ≤ 0`` as the overlap predicate.
    if gap > 0.0:
        iresult = interference(body_a, body_b)
        if iresult["interferes"]:
            # Pick representative witness points: closest surface samples
            # still make sense as contact-region indicators.
            return {
                "gap": 0.0,
                "witness_a": pts_a[ia].tolist(),
                "witness_b": pts_b[ib].tolist(),
            }

    return {
        "gap": gap,
        "witness_a": pts_a[ia].tolist(),
        "witness_b": pts_b[ib].tolist(),
    }


# ---------------------------------------------------------------------------
# GK-124: Mate constraint solver
# ---------------------------------------------------------------------------

_MATE_TYPES = frozenset({"coincident", "concentric", "distance", "angle"})


def _unit3(v: np.ndarray) -> np.ndarray:
    """Return a unit vector.  Raises ValueError for zero-length input."""
    n = np.linalg.norm(v)
    if n < 1e-14:
        raise ValueError(f"Cannot normalise near-zero vector {v!r}")
    return v / n


def _rotation_matrix_from_axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    """Build a 3×3 rotation matrix via Rodrigues' formula.

    Parameters
    ----------
    axis:
        Unit rotation axis (3-vector).
    angle:
        Rotation angle in **radians**.

    Returns
    -------
    np.ndarray of shape (3, 3).
    """
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    x, y, z = float(axis[0]), float(axis[1]), float(axis[2])
    return np.array(
        [
            [t * x * x + c,     t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c,     t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c    ],
        ],
        dtype=float,
    )


def _rotation_align_vectors(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return a 3×3 rotation matrix that rotates unit-vector *a* onto unit-vector *b*.

    Uses the cross-product axis + acos angle approach with a special case for
    anti-parallel vectors (rotate 180° about any perpendicular axis).
    """
    a = _unit3(a)
    b = _unit3(b)
    dot = float(np.dot(a, b))
    # Already aligned — identity
    if dot > 1.0 - 1e-12:
        return np.eye(3, dtype=float)
    # Anti-parallel — 180° about any perpendicular axis
    if dot < -1.0 + 1e-12:
        perp = _unit3(_perp_vec(a))
        return _rotation_matrix_from_axis_angle(perp, math.pi)
    axis = _unit3(np.cross(a, b))
    angle = math.acos(max(-1.0, min(1.0, dot)))
    return _rotation_matrix_from_axis_angle(axis, angle)


def _perp_vec(v: np.ndarray) -> np.ndarray:
    """Return an arbitrary vector perpendicular to *v* (not normalised)."""
    if abs(float(v[0])) < 0.9:
        return np.array([1.0, 0.0, 0.0]) - float(v[0]) * v
    return np.array([0.0, 1.0, 0.0]) - float(v[1]) * v


def _make_homogeneous(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Build a 4×4 column-vector homogeneous transform from R (3×3) and t (3,)."""
    T = np.eye(4, dtype=float)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def _face_plane_info(face) -> Tuple[np.ndarray, np.ndarray]:
    """Extract (centroid, normal) from a planar or analytic face.

    * For a :class:`~kerf_cad_core.geom.brep.Plane` surface: use
      ``origin`` and ``normal()``.
    * For any other surface: sample the face at (u, v) = (0.5, 0.5) and
      use the surface normal there.

    Returns
    -------
    (centroid, normal) both as 1-D float arrays.
    """
    surf = face.surface
    if isinstance(surf, Plane):
        return np.asarray(surf.origin, dtype=float), _unit3(
            np.asarray(surf.normal(), dtype=float)
        )
    # Generic: sample centre of UV domain
    p = np.asarray(surf.evaluate(0.5, 0.5), dtype=float)
    n = _unit3(np.asarray(surf.normal(0.5, 0.5), dtype=float))
    return p, n


def _face_cylinder_info(face) -> Tuple[np.ndarray, np.ndarray, float]:
    """Extract (axis_point, axis_dir, radius) from a cylindrical face.

    Parameters
    ----------
    face:
        A B-rep :class:`~kerf_cad_core.geom.brep.Face` whose ``.surface``
        is a :class:`~kerf_cad_core.geom.brep.CylinderSurface`.

    Returns
    -------
    Tuple ``(center, axis, radius)`` where *center* is a point on the axis.

    Raises
    ------
    ValueError
        If the face surface is not a :class:`CylinderSurface`.
    """
    surf = face.surface
    if not isinstance(surf, CylinderSurface):
        raise ValueError(
            f"Concentric mate requires CylinderSurface faces; got {type(surf).__name__}"
        )
    return (
        np.asarray(surf.center, dtype=float),
        _unit3(np.asarray(surf.axis, dtype=float)),
        float(surf.radius),
    )


def _face_centroid(face) -> np.ndarray:
    """Approximate the face centroid using B-rep vertex positions.

    Falls back to the surface origin / centre if no vertices are available.
    """
    pts = []
    for loop in face.loops:
        for v in loop.vertices():
            pts.append(np.asarray(v.point, dtype=float))
    if pts:
        return np.mean(pts, axis=0)
    # Fallback: surface evaluate at (0.5, 0.5)
    return np.asarray(face.surface.evaluate(0.5, 0.5), dtype=float)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def solve_mate(
    body,
    mate_type: str,
    ref_a,
    ref_b,
    *,
    distance: float = 0.0,
    angle: float = 0.0,
    tol: float = 1e-9,
) -> dict:
    """Compute the rigid transform that satisfies a geometric mate constraint.

    Solves the constraint **without** modifying ``body`` in-place — callers
    apply the returned transform as they see fit.

    Parameters
    ----------
    body:
        The :class:`~kerf_cad_core.geom.brep.Body` to be repositioned
        (the *moving* part).  Only used for concentric mates where we need
        to know which axis to move.
    mate_type:
        One of ``"coincident"``, ``"concentric"``, ``"distance"``,
        ``"angle"``.
    ref_a:
        Reference geometry on the *fixed* part (a
        :class:`~kerf_cad_core.geom.brep.Face`).
    ref_b:
        Reference geometry on *body* (a
        :class:`~kerf_cad_core.geom.brep.Face`).
    distance:
        Target separation for ``"distance"`` mates (default ``0.0``).
    angle:
        Target angle in **radians** for ``"angle"`` mates (default ``0.0``).
    tol:
        Geometric tolerance (currently informational; not used to abort).

    Returns
    -------
    dict with keys:

    ``"transform"``
        4×4 homogeneous transformation matrix (``np.ndarray``) to apply to
        every point of ``body``.  Post-multiply column vectors:
        ``p_new = T @ [x, y, z, 1]``.
    ``"ok"``
        ``True`` when a valid transform was found.
    ``"error"``
        Absent when ``ok`` is ``True``; an explanation string otherwise.

    Raises
    ------
    ValueError
        If *mate_type* is not one of the four supported values.

    Notes
    -----
    * Pure-Python / NumPy — no OCCT dependency.
    * Only rigid (isometric) transforms are produced; no scaling.

    Examples
    --------
    Coincident face mate — face A at Z=0, face B at Z=2::

        result = solve_mate(body_b, "coincident", face_a, face_b)
        T = result["transform"]
        # Apply T to every vertex of body_b → face B now touches face A.

    Concentric cylinder mate::

        result = solve_mate(body_b, "concentric", cyl_face_a, cyl_face_b)
        T = result["transform"]
        # After applying T, cylinder-B axis == cylinder-A axis.
    """
    if mate_type not in _MATE_TYPES:
        raise ValueError(
            f"Unknown mate_type {mate_type!r}; must be one of {sorted(_MATE_TYPES)}"
        )

    # ValueError propagates — it signals wrong geometry type (programmer error).
    # Other unexpected exceptions are caught and returned as ok=False dicts.
    try:
        if mate_type == "coincident":
            return _solve_coincident(ref_a, ref_b)
        if mate_type == "concentric":
            return _solve_concentric(ref_a, ref_b)
        if mate_type == "distance":
            return _solve_distance(ref_a, ref_b, distance)
        # angle
        return _solve_angle(ref_a, ref_b, angle)
    except ValueError:
        raise
    except Exception as exc:  # pragma: no cover — surfaces malformed
        return {"transform": np.eye(4, dtype=float), "ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Per-mate-type solvers
# ---------------------------------------------------------------------------


def _solve_coincident(ref_a, ref_b) -> dict:
    """Move *body* so that ``ref_b`` face is flush against ``ref_a`` face.

    Algorithm
    ---------
    1. Extract the centroid and outward normal of each face.
    2. Build a rotation that aligns ``nB`` anti-parallel to ``nA``
       (mating faces point toward each other).
    3. Translate so that the centroid of the (rotated) ``ref_b`` lands on
       the plane defined by ``ref_a``.

    The resulting transform is:  ``T = Translate(t) @ Rotate(R)``
    (i.e. first rotate, then translate).
    """
    cA, nA = _face_plane_info(ref_a)
    cB, nB = _face_plane_info(ref_b)

    # Rotate B's normal to be anti-parallel to A's normal (faces touch).
    R = _rotation_align_vectors(nB, -nA)

    # After rotation, where does cB land?
    cB_rot = R @ cB

    # Translate so that cB_rot lies in the plane (cA, nA):
    # project along nA so the face is flush (zero offset)
    proj = float(np.dot(cA - cB_rot, nA))
    t = proj * nA

    T = _make_homogeneous(R, t)
    return {"transform": T, "ok": True}


def _solve_concentric(ref_a, ref_b) -> dict:
    """Align the cylinder axis of ``ref_b`` with the cylinder axis of ``ref_a``.

    Algorithm
    ---------
    1. Extract ``(center_A, axis_A)`` and ``(center_B, axis_B)`` from the
       cylindrical faces.
    2. Rotate ``axis_B`` onto ``axis_A``.
    3. After rotation, compute the translation that moves (rotated)
       ``center_B`` onto the axis line of A:
       ``t = center_A + proj * axis_A - R @ center_B``
       where ``proj`` keeps the axial position as close as possible (no
       unnecessary along-axis movement).

    Analytic oracle: after applying the transform the distance from any point
    on axis B to axis A is zero (axes are collinear).
    """
    cA, axA, _ = _face_cylinder_info(ref_a)
    cB, axB, _ = _face_cylinder_info(ref_b)

    # Align axes (accept both parallel and anti-parallel — same axis line).
    dot = float(np.dot(axA, axB))
    target = axA if dot >= 0.0 else -axA
    R = _rotation_align_vectors(axB, target)

    # Move rotated cB to lie on axis A (project onto axis to preserve axial pos).
    cB_rot = R @ cB
    # Closest point on axis A to cB_rot:
    proj_scalar = float(np.dot(cB_rot - cA, axA))
    closest_on_A = cA + proj_scalar * axA
    t = closest_on_A - cB_rot

    T = _make_homogeneous(R, t)
    return {"transform": T, "ok": True}


def _solve_distance(ref_a, ref_b, target_distance: float) -> dict:
    """Translate ``body`` along the plane normal until the face separation
    equals *target_distance*.

    Algorithm
    ---------
    1. Extract ``(cA, nA)`` from the fixed plane (``ref_a``).
    2. Extract ``cB`` from ``ref_b`` (only centroid needed; the normal is
       only used if the face is not already parallel — but we always move
       along ``nA``).
    3. Current signed distance of cB from plane A:
       ``d_current = dot(cB - cA, nA)``
    4. Required additional translation along nA:
       ``delta = target_distance - d_current``

    Pure translation (no rotation); preserves body orientation.
    """
    cA, nA = _face_plane_info(ref_a)
    cB = _face_centroid(ref_b)

    d_current = float(np.dot(cB - cA, nA))
    delta = target_distance - d_current
    t = delta * nA

    T = _make_homogeneous(np.eye(3, dtype=float), t)
    return {"transform": T, "ok": True}


def _solve_angle(ref_a, ref_b, target_angle_rad: float) -> dict:
    """Rotate ``body`` about the intersection of the two face normals until
    the dihedral angle between the faces equals *target_angle_rad*.

    Algorithm
    ---------
    1. Extract normals ``nA`` and ``nB`` from the two faces.
    2. The rotation axis is ``nA × nB`` (or any axis perpendicular to both
       normals if they are parallel/anti-parallel).
    3. Current angle between the normals:
       ``theta_current = acos(clamp(dot(nA, nB), -1, 1))``
    4. Required additional rotation:
       ``delta_theta = target_angle_rad - theta_current``
    5. Apply that rotation about the axis through ``cB`` (the centroid of
       ``ref_b``) so the body pivots in-place.

    The rotation centre is the centroid of ``ref_b`` (keeping that point
    fixed minimises overall body displacement).
    """
    _, nA = _face_plane_info(ref_a)
    cB, nB = _face_plane_info(ref_b)

    dot_val = float(np.dot(nA, nB))
    dot_clamped = max(-1.0, min(1.0, dot_val))
    theta_current = math.acos(dot_clamped)
    delta_theta = target_angle_rad - theta_current

    # Rotation axis
    cross = np.cross(nA, nB)
    if np.linalg.norm(cross) < 1e-12:
        # Normals are parallel/anti-parallel — choose any perpendicular axis.
        cross = _perp_vec(nA)
    axis = _unit3(cross)

    R = _rotation_matrix_from_axis_angle(axis, delta_theta)

    # Pivot about cB: T = Translate(cB) @ Rotate(R) @ Translate(-cB)
    t = cB - R @ cB

    T = _make_homogeneous(R, t)
    return {"transform": T, "ok": True}
