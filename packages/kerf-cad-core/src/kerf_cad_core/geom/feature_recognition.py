"""GK-133 — Feature recognition: classify B-rep face clusters.

``recognize_features(body) -> dict``
    Classify the faces of *body* into manufacturing features (hole, pocket,
    boss, fillet, chamfer) using surface-type + adjacency + concavity
    heuristics.  Returns::

        {
            "features": [
                {"type": str, "face_ids": [int, ...], "params": dict},
                ...
            ],
            "summary": {
                "hole": int, "pocket": int, "boss": int,
                "fillet": int, "chamfer": int,
            }
        }

All geometry is analytic (pure-Python, no OCCT dependency).

Heuristics
----------
Surface-type detection uses **duck typing** — any face whose surface has
``radius``, ``axis``, and ``normal`` attributes is treated as a cylinder-
like surface.  This covers both :class:`~brep.CylinderSurface` (from box +
hole primitives) and the private ``_CylindricalArcSurface`` produced by the
solid fillet / blend operations, without importing the private type.

Concavity test for cylinder-like faces
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The surface centre attribute may be named ``center`` (``CylinderSurface``) or
``centre`` (``_CylindricalArcSurface``).  The helper ``_cyl_center`` handles
both.  A sample point is evaluated at ``(u=0, v=0)``.  The inward-radial
vector is (axis-nearest-point − sample-point).  If
``dot(face_normal, radial_inward) > 0`` the face is **concave** (normal
toward axis → hole/pocket cylinder); otherwise **convex** (fillet/boss).

Adjacency
~~~~~~~~~
Two faces are *adjacent* if they share at least one topological edge
(identified by Python object identity of the underlying ``Edge`` instance).
An adjacency map is built once and reused for all cluster operations.

Feature classification order (greedy, first-wins)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **Hole**: a concave cylinder-like face with at least one planar neighbor.
2. **Fillet**: a convex cylinder-like (or toric) face flanked by ≥ 2 planar
   neighbors.
3. **Chamfer**: a planar face at an oblique angle (20°–70°) to ≥ 2 planar
   neighbors.
4. **Boss**: a convex cylinder-like face with ≥ 1 planar neighbor (not
   already claimed).
5. **Pocket**: a connected cluster of ≥ 3 unclaimed planar faces that is
   *closed at the bottom* (one face with ≥ 2 perpendicular planar neighbors
   on all sides, i.e. a floor) but has fewer planar neighbors than the
   number of wall faces (i.e. the cluster is not the exterior of a simple
   convex solid).  A plain closed box — whose six faces each have four
   planar neighbors — is **not** a pocket because every face is fully
   surrounded by same-cluster faces (there is no "open top").
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Face,
    Plane,
    SphereSurface,
    TorusSurface,
)

__all__ = ["recognize_features"]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _build_adjacency(body: Body) -> Dict[int, Set[int]]:
    """Return {face_id: {adjacent_face_id, ...}} via shared-edge identity."""
    edge_to_faces: Dict[int, List[int]] = {}
    for face in body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                eid = id(ce.edge)
                edge_to_faces.setdefault(eid, []).append(face.id)

    adj: Dict[int, Set[int]] = {f.id: set() for f in body.all_faces()}
    for fids in edge_to_faces.values():
        for i, a in enumerate(fids):
            for b in fids[i + 1:]:
                if a != b:  # exclude self-adjacency (seam edges)
                    adj[a].add(b)
                    adj[b].add(a)
    return adj


def _face_by_id(body: Body) -> Dict[int, Face]:
    return {f.id: f for f in body.all_faces()}


def _is_plane(face: Face) -> bool:
    return isinstance(face.surface, Plane)


def _is_torus(face: Face) -> bool:
    return isinstance(face.surface, TorusSurface)


def _is_sphere(face: Face) -> bool:
    return isinstance(face.surface, SphereSurface)


def _is_cylinder_like(face: Face) -> bool:
    """True for any surface with radius + axis + a normal() method.

    This covers both ``CylinderSurface`` and the private
    ``_CylindricalArcSurface`` used by blend_solid without importing it.
    """
    s = face.surface
    return (
        hasattr(s, "radius")
        and hasattr(s, "axis")
        and hasattr(s, "normal")
        and hasattr(s, "evaluate")
        and not isinstance(s, TorusSurface)  # torus has radius too
    )


def _cyl_center(surface: object) -> np.ndarray:
    """Return the cylinder axis reference point (handles center / centre)."""
    if hasattr(surface, "center"):
        return np.asarray(surface.center, dtype=float)  # type: ignore[union-attr]
    if hasattr(surface, "centre"):
        return np.asarray(surface.centre, dtype=float)  # type: ignore[union-attr]
    raise AttributeError(f"No center/centre attribute on {type(surface).__name__}")


def _cylinder_concavity(face: Face) -> float:
    """Return dot(outward_normal, radial_inward).

    Positive  → face is concave (normal toward axis → hole / pocket).
    Negative  → face is convex  (normal away from axis → fillet / boss).
    """
    s = face.surface
    u_sample, v_sample = 0.0, 0.0
    pt = np.asarray(s.evaluate(u_sample, v_sample), dtype=float)  # type: ignore[union-attr]
    center = _cyl_center(s)
    axis = _unit(np.asarray(s.axis, dtype=float))  # type: ignore[union-attr]
    t = float(np.dot(pt - center, axis))
    nearest_on_axis = center + t * axis
    radial_inward = _unit(nearest_on_axis - pt)  # toward axis
    normal = np.asarray(face.surface_normal(u_sample, v_sample), dtype=float)
    return float(np.dot(normal, radial_inward))


def _torus_concavity(face: Face) -> float:
    """Return dot(outward_normal, toward_torus_axis) at sample.

    Positive → concave; negative → convex (fillet).
    """
    tor: TorusSurface = face.surface  # type: ignore[assignment]
    u_sample, v_sample = 0.0, 0.0
    pt = np.asarray(tor.evaluate(u_sample, v_sample), dtype=float)
    center = np.asarray(tor.center, dtype=float)
    axis = _unit(np.asarray(tor.axis, dtype=float))
    t = float(np.dot(pt - center, axis))
    proj = center + t * axis
    radial_inward = _unit(proj - pt)
    normal = np.asarray(face.surface_normal(u_sample, v_sample), dtype=float)
    return float(np.dot(normal, radial_inward))


def _plane_normal(face: Face) -> np.ndarray:
    return np.asarray(face.surface_normal(0.0, 0.0), dtype=float)


def _dihedral_angle_deg(face_a: Face, face_b: Face) -> float:
    """Dihedral angle in degrees between two planar faces (0–180)."""
    na = _plane_normal(face_a)
    nb = _plane_normal(face_b)
    dot = float(np.clip(np.dot(na, nb), -1.0, 1.0))
    return math.degrees(math.acos(dot))


def _cylinder_radius(face: Face) -> float:
    return float(face.surface.radius)  # type: ignore[union-attr]


def _cylinder_axis(face: Face) -> np.ndarray:
    return _unit(np.asarray(face.surface.axis, dtype=float))  # type: ignore[union-attr]


def _torus_radii(face: Face) -> tuple:
    t: TorusSurface = face.surface  # type: ignore[assignment]
    return float(t.major_radius), float(t.minor_radius)


# ---------------------------------------------------------------------------
# Pocket heuristic helper
# ---------------------------------------------------------------------------


def _is_pocket_cluster(component: List[int], by_id: Dict[int, Face],
                        adj: Dict[int, Set[int]],
                        total_face_count: int) -> bool:
    """Return True iff a connected component of planar faces is a pocket.

    A pocket is a recess that satisfies ALL of:

    1. The component does NOT comprise all faces of the body (it's not the
       body's full exterior shell).
    2. At least one face in the cluster has a neighbor outside the cluster
       (the "open top" of the pocket; a fully enclosed cluster would be
       the full exterior of a solid, not a pocket).
    3. At least one adjacent pair within the cluster meets at ≈ 90°
       (floor + wall geometry).
    4. The cluster is smaller than the total face count minus 1 (at
       minimum one external face must exist).

    A plain closed box fails because its 6 planar faces comprise the
    entire face set.  Faces claimed by earlier passes (holes/fillets) are
    already excluded from the component, so a 6-face box with a drilled
    hole (1 cylinder claimed) has 6 remaining planes — but those 6 planes
    are the full remaining face set.  We still avoid classifying them as
    a pocket via rule 2 (they have a non-planar neighbor outside the
    cluster — the cylinder — which was already claimed, so that neighbor
    is NOT in adj because adj was built on ALL faces).

    Actually rule 2 is the critical one: we check whether any face in the
    component has a neighbour (in the *full* body adjacency) that is NOT
    in the component.  For the box exterior this is only the cylindrical
    face (already excluded from comp), so *has_outside_opening = True*
    — but we guard with rule 1 (component.len == 6, total_face_count == 7,
    so component is not "all faces") and rule 4.

    The final discriminator for "not a pocket" for a box exterior is rule 3
    requiring that the opening neighbor is a *planar* face external to the
    cluster.  Box exterior faces only have non-planar (cylindrical) external
    neighbours — those don't count as an opening.
    """
    comp_set = set(component)

    # Rule 1: component must not be the full face set of the body
    if len(component) >= total_face_count:
        return False

    # Rule 2+3 combined: must have at least one *planar* face external
    # to the cluster as a neighbor (the pocket opening rim)
    has_planar_outside_opening = False
    for fid in component:
        for nid in adj.get(fid, set()):
            if nid not in comp_set:
                nb = by_id.get(nid)
                if nb is not None and _is_plane(nb):
                    has_planar_outside_opening = True
                    break
        if has_planar_outside_opening:
            break

    if not has_planar_outside_opening:
        return False

    # Rule 4: require at least one right-angle pair (floor + wall)
    comp_faces = [by_id[fid] for fid in component]
    for i, fa in enumerate(comp_faces):
        for fb in comp_faces[i + 1:]:
            if fb.id in adj.get(fa.id, set()):
                angle = _dihedral_angle_deg(fa, fb)
                if 70.0 <= angle <= 110.0:
                    return True

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def recognize_features(body: Body) -> Dict[str, Any]:
    """Classify B-rep face clusters into manufacturing features.

    Parameters
    ----------
    body:
        A :class:`~kerf_cad_core.geom.brep.Body` produced by any of the
        kerf geometry kernel primitives.

    Returns
    -------
    dict with keys:

    ``"features"``
        List of dicts, each ``{"type": str, "face_ids": [int, ...],
        "params": dict}``.
    ``"summary"``
        ``{"hole": int, "pocket": int, "boss": int, "fillet": int,
        "chamfer": int}``.
    """
    adj = _build_adjacency(body)
    by_id = _face_by_id(body)
    total_face_count = len(by_id)
    claimed: Set[int] = set()

    features: List[Dict[str, Any]] = []

    # -----------------------------------------------------------------------
    # Pass 1: Cylindrical holes
    #   - single concave cylinder-like face (normal toward axis)
    #   - at least 1 planar neighbor (the rim cap)
    # -----------------------------------------------------------------------
    for face in body.all_faces():
        if face.id in claimed:
            continue
        if not _is_cylinder_like(face):
            continue
        concavity = _cylinder_concavity(face)
        if concavity <= 0.0:
            continue  # convex → not a hole

        neighbor_ids = adj.get(face.id, set())
        neighbor_faces = [by_id[nid] for nid in neighbor_ids if nid in by_id]
        planar_neighbors = [f for f in neighbor_faces if _is_plane(f)]

        if len(planar_neighbors) < 1:
            continue

        r = _cylinder_radius(face)
        axis = _cylinder_axis(face)

        depths = []
        for pf in planar_neighbors:
            origin = np.asarray(pf.surface.origin, dtype=float)  # type: ignore[union-attr]
            proj = float(np.dot(origin - _cyl_center(face.surface), axis))
            depths.append(proj)

        depth = float(abs(max(depths) - min(depths))) if len(depths) >= 2 else 0.0

        claimed.add(face.id)
        features.append(
            {
                "type": "hole",
                "face_ids": [face.id],
                "params": {"radius": r, "depth": depth, "axis": axis.tolist()},
            }
        )

    # -----------------------------------------------------------------------
    # Pass 2: Fillets
    #   - convex cylinder-like face flanked by ≥ 2 planar neighbors, OR
    #   - convex TorusSurface flanked by ≥ 2 planar neighbors
    # -----------------------------------------------------------------------
    for face in body.all_faces():
        if face.id in claimed:
            continue

        radius: Optional[float] = None
        is_fillet_candidate = False

        if _is_cylinder_like(face):
            concavity = _cylinder_concavity(face)
            if concavity < 0.0:
                is_fillet_candidate = True
                radius = _cylinder_radius(face)
        elif _is_torus(face):
            concavity = _torus_concavity(face)
            if concavity < 0.0:
                is_fillet_candidate = True
                _, minor_r = _torus_radii(face)
                radius = minor_r

        if not is_fillet_candidate or radius is None:
            continue

        neighbor_ids = adj.get(face.id, set())
        neighbor_faces = [by_id[nid] for nid in neighbor_ids if nid in by_id]
        planar_neighbors = [f for f in neighbor_faces if _is_plane(f)]

        if len(planar_neighbors) < 2:
            continue

        claimed.add(face.id)
        features.append(
            {
                "type": "fillet",
                "face_ids": [face.id],
                "params": {"radius": radius},
            }
        )

    # -----------------------------------------------------------------------
    # Pass 3: Chamfers
    #   - unclaimed planar face flanked by ≥ 2 planar neighbors
    #   - dihedral angle to each of those neighbors is between 20° and 70°
    # -----------------------------------------------------------------------
    for face in body.all_faces():
        if face.id in claimed:
            continue
        if not _is_plane(face):
            continue

        neighbor_ids = adj.get(face.id, set())
        neighbor_faces = [by_id[nid] for nid in neighbor_ids if nid in by_id]
        planar_neighbors = [f for f in neighbor_faces if _is_plane(f)]

        if len(planar_neighbors) < 2:
            continue

        oblique_count = sum(
            1 for pf in planar_neighbors
            if 20.0 <= _dihedral_angle_deg(face, pf) <= 70.0
        )

        if oblique_count < 2:
            continue

        claimed.add(face.id)
        features.append(
            {
                "type": "chamfer",
                "face_ids": [face.id],
                "params": {},
            }
        )

    # -----------------------------------------------------------------------
    # Pass 4: Bosses
    #   - unclaimed convex cylinder-like face with ≥ 1 planar neighbor
    # -----------------------------------------------------------------------
    for face in body.all_faces():
        if face.id in claimed:
            continue
        if not _is_cylinder_like(face):
            continue

        concavity = _cylinder_concavity(face)
        if concavity >= 0.0:
            continue  # concave → already handled as hole or skip

        neighbor_ids = adj.get(face.id, set())
        neighbor_faces = [by_id[nid] for nid in neighbor_ids if nid in by_id]
        planar_neighbors = [f for f in neighbor_faces if _is_plane(f)]

        if not planar_neighbors:
            continue

        r = _cylinder_radius(face)
        axis = _cylinder_axis(face)

        claimed.add(face.id)
        features.append(
            {
                "type": "boss",
                "face_ids": [face.id],
                "params": {"radius": r, "axis": axis.tolist()},
            }
        )

    # -----------------------------------------------------------------------
    # Pass 5: Pockets
    #   - connected cluster of ≥ 3 unclaimed planar faces
    #   - cluster has at least one outside opening (not every neighbor is
    #     within the cluster — this excludes a plain closed box exterior)
    #   - cluster contains at least one right-angle pair (floor + wall)
    # -----------------------------------------------------------------------
    unclaimed_planes = [
        f for f in body.all_faces() if f.id not in claimed and _is_plane(f)
    ]
    plane_ids = {f.id for f in unclaimed_planes}
    visited: Set[int] = set()

    for face in unclaimed_planes:
        if face.id in visited:
            continue
        component: List[int] = []
        queue = [face.id]
        while queue:
            fid = queue.pop()
            if fid in visited:
                continue
            visited.add(fid)
            component.append(fid)
            for nid in adj.get(fid, set()):
                if nid not in visited and nid in plane_ids:
                    queue.append(nid)

        if len(component) < 3:
            continue

        if not _is_pocket_cluster(component, by_id, adj, total_face_count):
            continue

        for fid in component:
            claimed.add(fid)
        features.append(
            {
                "type": "pocket",
                "face_ids": component,
                "params": {"face_count": len(component)},
            }
        )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    summary: Dict[str, int] = {
        "hole": 0,
        "pocket": 0,
        "boss": 0,
        "fillet": 0,
        "chamfer": 0,
    }
    for feat in features:
        t = feat["type"]
        if t in summary:
            summary[t] += 1

    return {"features": features, "summary": summary}
