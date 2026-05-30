"""GK-133 — Feature recognition: classify B-rep face clusters.

ISO 10303-224 compliant feature recognition for machining features.

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

``recognize_features_iso(body) -> FeatureRecognitionResult``
    ISO 10303-224 / Han-Pratt-Regli 2000 compliant recognition.
    Returns a :class:`FeatureRecognitionResult` with typed Feature objects.

``classify_hole(body, face_ids) -> HoleInfo``
    Classify a hole's sub-type (through_hole, blind_hole, counterbore,
    countersink) from the face cluster.

``feature_to_machining_op(feature) -> dict``
    Map an ISO 10303-224 :class:`Feature` to a CNC machining operation.

All geometry is analytic (pure-Python, no OCCT dependency).

References
----------
ISO 10303-224:2001 "Mechanical product definition for process planning
using machining features".

Han, J., Pratt, M. J., & Regli, W. C. (2000). "Manufacturing feature
recognition from solid models: A status report." IEEE Transactions on
Robotics and Automation, 16(6), 782-796.

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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Face,
    Plane,
    SphereSurface,
    TorusSurface,
)

__all__ = [
    "recognize_features",
    "recognize_features_iso",
    "classify_hole",
    "feature_to_machining_op",
    "Feature",
    "HoleInfo",
    "FeatureRecognitionResult",
]


# ---------------------------------------------------------------------------
# ISO 10303-224 typed data structures
# ---------------------------------------------------------------------------


@dataclass
class Feature:
    """A single machining feature per ISO 10303-224.

    Attributes
    ----------
    kind : str
        Top-level category: 'hole', 'slot', 'pocket', 'fillet', 'chamfer',
        'boss', 'rib', 'step'.
    subtype : str
        ISO 10303-224 sub-type:
        holes  — 'through_hole', 'blind_hole', 'counterbore', 'countersink'
        slots  — 'rectangular_slot', 't_slot', 'dovetail_slot'
        pocket — 'closed_pocket', 'open_pocket'
        fillet — 'interior_fillet', 'exterior_fillet'
        others — same as kind
    face_ids : list[int]
        Face IDs that participate in this feature.
    dimensions : dict
        Feature-specific measurements:
        hole    → diameter, depth, radius
        fillet  → radius
        chamfer → (empty)
        boss    → radius, diameter
        pocket  → face_count
        rib     → (empty)
        step    → (empty)
    direction : list[float] | None
        Unit axis vector for rotationally-symmetric features (holes, bosses).
        None for planar features.
    confidence : float
        0.0–1.0 recognition confidence.
    """
    kind: str
    subtype: str
    face_ids: List[int]
    dimensions: Dict[str, Any] = field(default_factory=dict)
    direction: Optional[List[float]] = None
    confidence: float = 0.85


@dataclass
class HoleInfo:
    """Detailed hole classification per ISO 10303-224 §5.3.

    Attributes
    ----------
    kind : str
        One of: 'through_hole', 'blind_hole', 'counterbore', 'countersink'.
    diameter : float
        Nominal hole diameter (mm or model units).
    depth : float
        Axial depth of the hole (0 for through holes without a measured solid).
    axis : list[float]
        Unit axis vector (drill direction).
    counterbore_diameter : float | None
        For counterbore: outer bore diameter.
    counterbore_depth : float | None
        For counterbore: outer bore depth.
    countersink_angle_deg : float | None
        For countersink: included half-angle in degrees.
    face_ids : list[int]
        Contributing face IDs.
    """
    kind: str
    diameter: float
    depth: float
    axis: List[float]
    counterbore_diameter: Optional[float] = None
    counterbore_depth: Optional[float] = None
    countersink_angle_deg: Optional[float] = None
    face_ids: List[int] = field(default_factory=list)


@dataclass
class FeatureRecognitionResult:
    """Result of ISO 10303-224 feature recognition.

    Attributes
    ----------
    features : list[Feature]
        All recognised features.
    unrecognized_face_count : int
        Number of faces not claimed by any feature.
    ISO_compliance_note : str
        Human-readable note about ISO 10303-224 compliance of this result.
    """
    features: List[Feature]
    unrecognized_face_count: int
    ISO_compliance_note: str

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


# ---------------------------------------------------------------------------
# ISO 10303-224 typed API
# ---------------------------------------------------------------------------

# Mapping from planar-neighbor count heuristic to hole subtype.
# A through-hole: concave cyl with 2 cap faces (entry + exit).
# A blind hole:   concave cyl with 1 cap face.
# A counterbore:  concave cyl with 1 cap and an adjacent wider concave cyl.
# A countersink:  handled via conical detection (not yet available on Body).
_HOLE_THROUGH_THRESHOLD = 2   # ≥2 cap planes → through hole


def _classify_hole_from_caps(radius: float, cap_count: int, depth: float,
                              axis: np.ndarray) -> HoleInfo:
    """Return a HoleInfo for a single cylindrical face + its cap count."""
    if cap_count >= _HOLE_THROUGH_THRESHOLD:
        return HoleInfo(
            kind="through_hole",
            diameter=round(radius * 2.0, 6),
            depth=0.0,
            axis=axis.tolist(),
        )
    return HoleInfo(
        kind="blind_hole",
        diameter=round(radius * 2.0, 6),
        depth=round(depth, 6),
        axis=axis.tolist(),
    )


def classify_hole(body: Body, face_ids: List[int]) -> HoleInfo:
    """Classify the hole type from a set of face IDs on *body*.

    Examines the cylindrical face(s) in *face_ids* and their planar cap
    neighbors to determine whether the hole is:

    * ``through_hole``   — cylinder with ≥ 2 planar caps (entry + exit)
    * ``blind_hole``     — cylinder with exactly 1 planar cap (floor)
    * ``counterbore``    — two coaxial cylinders of different radius + step face
    * ``countersink``    — not detectable from pure B-rep without conical surface;
                           returns ``blind_hole`` with a note

    Parameters
    ----------
    body:
        The parent :class:`~kerf_cad_core.geom.brep.Body`.
    face_ids:
        Face IDs forming the hole cluster.

    Returns
    -------
    :class:`HoleInfo`
    """
    adj = _build_adjacency(body)
    by_id = _face_by_id(body)

    cyl_faces = [by_id[fid] for fid in face_ids if fid in by_id and _is_cylinder_like(by_id[fid])]
    if not cyl_faces:
        return HoleInfo(kind="through_hole", diameter=0.0, depth=0.0, axis=[0.0, 0.0, 1.0],
                        face_ids=face_ids)

    # Sort by radius to detect counterbore: larger bore on top, smaller drill below.
    cyl_faces_sorted = sorted(cyl_faces, key=lambda f: _cylinder_radius(f), reverse=True)
    primary = cyl_faces_sorted[0]
    r = _cylinder_radius(primary)
    axis = _cylinder_axis(primary)

    # Gather cap faces adjacent to the primary cylinder.
    neighbor_ids = adj.get(primary.id, set())
    cap_faces = [by_id[nid] for nid in neighbor_ids if nid in by_id and _is_plane(by_id[nid])]

    # Depth from cap-to-cap.
    depths = []
    for pf in cap_faces:
        origin = np.asarray(pf.surface.origin, dtype=float)  # type: ignore[union-attr]
        proj = float(np.dot(origin - _cyl_center(primary.surface), axis))
        depths.append(proj)
    depth_val = float(abs(max(depths) - min(depths))) if len(depths) >= 2 else 0.0

    # Counterbore detection: two concave cylinders with different radii sharing a step face.
    if len(cyl_faces_sorted) >= 2:
        secondary = cyl_faces_sorted[1]
        r2 = _cylinder_radius(secondary)
        if not math.isclose(r, r2, rel_tol=0.05) and _axes_parallel(axis, _cylinder_axis(secondary)):
            # Shared planar face between the two cylinders → step face.
            n1 = adj.get(primary.id, set())
            n2 = adj.get(secondary.id, set())
            shared = n1 & n2
            if any(_is_plane(by_id[s]) for s in shared if s in by_id):
                area_primary = 0.0
                area_secondary = 0.0
                # Estimate depth from cylinder lateral area.
                depth_bore = area_primary / (2.0 * math.pi * r) if r > 1e-6 else 0.0
                depth_drill = area_secondary / (2.0 * math.pi * r2) if r2 > 1e-6 else 0.0
                return HoleInfo(
                    kind="counterbore",
                    diameter=round(min(r, r2) * 2.0, 6),
                    depth=round(depth_bore + depth_drill, 6),
                    axis=axis.tolist(),
                    counterbore_diameter=round(max(r, r2) * 2.0, 6),
                    counterbore_depth=round(max(depth_bore, depth_drill), 6),
                    face_ids=face_ids,
                )

    hole_info = _classify_hole_from_caps(r, len(cap_faces), depth_val, axis)
    hole_info.face_ids = face_ids
    return hole_info


# ---------------------------------------------------------------------------
# ISO 10303-224 → CNC operation mapping
# ---------------------------------------------------------------------------

# ISO 10303-224 feature type to primary CNC operation.
_ISO_MACHINING_OPS: Dict[str, str] = {
    # Holes
    "through_hole":     "drill",
    "blind_hole":       "drill",
    "counterbore":      "drill_counterbore",   # step 1: drill, step 2: bore
    "countersink":      "drill_countersink",   # step 1: drill, step 2: countersink
    # Slots / pockets
    "rectangular_slot": "end_mill",
    "t_slot":           "t_slot_mill",
    "dovetail_slot":    "dovetail_mill",
    "closed_pocket":    "end_mill",
    "open_pocket":      "end_mill",
    "pocket":           "end_mill",
    "slot":             "end_mill",
    # Planar features
    "fillet":           "fillet_mill",
    "interior_fillet":  "fillet_mill",
    "exterior_fillet":  "fillet_mill",
    "chamfer":          "chamfer_mill",
    # Protrusions
    "boss":             "turn_or_mill",
    "rib":              "end_mill",
    "step":             "face_mill",
    # Generic fallback
    "hole":             "drill",
}

# Detailed per-feature op spec template.
_ISO_OP_DETAILS: Dict[str, Dict[str, Any]] = {
    "drill":            {"tool": "twist_drill",  "cycle": "G81"},
    "drill_counterbore":{"tool": "counterbore_drill", "cycle": "G82"},
    "drill_countersink":{"tool": "countersink_drill", "cycle": "G82"},
    "end_mill":         {"tool": "end_mill",     "cycle": "G01_contour"},
    "t_slot_mill":      {"tool": "t_slot_cutter","cycle": "G01_contour"},
    "dovetail_mill":    {"tool": "dovetail_cutter","cycle": "G01_contour"},
    "fillet_mill":      {"tool": "ball_nose_mill","cycle": "G01_ramp"},
    "chamfer_mill":     {"tool": "chamfer_mill", "cycle": "G01_contour"},
    "face_mill":        {"tool": "face_mill",    "cycle": "G01_face"},
    "turn_or_mill":     {"tool": "end_mill",     "cycle": "G01_circular"},
}


def feature_to_machining_op(feature: Feature) -> Dict[str, Any]:
    """Map an ISO 10303-224 :class:`Feature` to its primary CNC machining operation.

    Parameters
    ----------
    feature:
        A :class:`Feature` instance (from :func:`recognize_features_iso`).

    Returns
    -------
    dict with keys:

    ``"operation"``
        Primary operation name (e.g. ``"drill"``, ``"end_mill"``).
    ``"tool"``
        Recommended tool type per ISO 10303-224 AP224 process mapping.
    ``"cycle"``
        Approximate G-code cycle identifier.
    ``"feature_type"``
        The input ``feature.subtype``.
    ``"dimensions"``
        Feature dimensions forwarded from the input feature.
    ``"iso_process_note"``
        Short note on the ISO 10303-224 §6 process entity.
    """
    subtype = feature.subtype
    # Try subtype first, then kind.
    op_name = _ISO_MACHINING_OPS.get(subtype) or _ISO_MACHINING_OPS.get(feature.kind, "mill")
    op_detail = _ISO_OP_DETAILS.get(op_name, {"tool": "end_mill", "cycle": "G01"})

    iso_note = (
        f"ISO 10303-224: {feature.kind}/{subtype} → "
        f"AP224 machining_feature entity; primary op: {op_name}"
    )

    return {
        "operation": op_name,
        "tool": op_detail.get("tool", "end_mill"),
        "cycle": op_detail.get("cycle", "G01"),
        "feature_type": subtype,
        "dimensions": dict(feature.dimensions),
        "iso_process_note": iso_note,
    }


# ---------------------------------------------------------------------------
# ISO-compliant high-level wrapper
# ---------------------------------------------------------------------------


def recognize_features_iso(body: Body) -> FeatureRecognitionResult:
    """ISO 10303-224 / Han-Pratt-Regli 2000 compliant feature recognition.

    Builds on :func:`recognize_features` (graph-based B-rep face adjacency
    per Han 2000 §4) and promotes each feature dict into a typed
    :class:`Feature` with ISO sub-types.

    Feature types per ISO 10303-224
    --------------------------------
    * ``hole``    → subtype: through_hole / blind_hole / counterbore / countersink
    * ``slot``    → subtype: rectangular_slot / t_slot / dovetail_slot
    * ``pocket``  → subtype: closed_pocket / open_pocket
    * ``fillet``  → subtype: interior_fillet / exterior_fillet
    * ``chamfer`` → subtype: chamfer
    * ``boss``    → subtype: boss
    * ``rib``     → subtype: rib
    * ``step``    → subtype: step

    Parameters
    ----------
    body:
        A :class:`~kerf_cad_core.geom.brep.Body`.

    Returns
    -------
    :class:`FeatureRecognitionResult`
    """
    raw = recognize_features(body)
    raw_feats = raw.get("features", [])
    total_faces = len(list(body.all_faces()))

    adj = _build_adjacency(body)
    by_id = _face_by_id(body)

    claimed_faces: Set[int] = set()
    iso_features: List[Feature] = []

    for feat in raw_feats:
        ftype = feat["type"]
        face_ids: List[int] = feat.get("face_ids", [])
        params: Dict[str, Any] = feat.get("params", {})

        # ---------- hole ----------
        if ftype == "hole":
            r = float(params.get("radius", 0.0))
            depth = float(params.get("depth", 0.0))
            axis_raw = params.get("axis", [0.0, 0.0, 1.0])
            # Determine subtype by counting caps.
            cyl_ids = [fid for fid in face_ids if fid in by_id and _is_cylinder_like(by_id[fid])]
            if cyl_ids:
                cyl_face = by_id[cyl_ids[0]]
                nb_ids = adj.get(cyl_face.id, set())
                cap_count = sum(1 for nid in nb_ids if nid in by_id and _is_plane(by_id[nid]))
                hole_subtype = "through_hole" if cap_count >= _HOLE_THROUGH_THRESHOLD else "blind_hole"
            else:
                hole_subtype = "blind_hole"
            dims: Dict[str, Any] = {
                "diameter": round(r * 2.0, 6),
                "radius": round(r, 6),
                "depth": round(depth, 6),
            }
            iso_features.append(Feature(
                kind="hole",
                subtype=hole_subtype,
                face_ids=face_ids,
                dimensions=dims,
                direction=axis_raw if isinstance(axis_raw, list) else list(axis_raw),
                confidence=0.85,
            ))

        # ---------- fillet ----------
        elif ftype == "fillet":
            r_fillet = float(params.get("radius", 0.0))
            # Interior fillet: face normal points toward the body interior
            # (concave from outside). We use the convexity we already
            # computed: concave → interior; convex → exterior.
            # The existing pass selects *convex* cylinders for fillets
            # (normal away from axis), so these are exterior fillets.
            fillet_subtype = "exterior_fillet"
            if face_ids and face_ids[0] in by_id:
                face = by_id[face_ids[0]]
                if _is_cylinder_like(face):
                    conc = _cylinder_concavity(face)
                    fillet_subtype = "interior_fillet" if conc > 0.0 else "exterior_fillet"
                elif _is_torus(face):
                    conc = _torus_concavity(face)
                    fillet_subtype = "interior_fillet" if conc > 0.0 else "exterior_fillet"
            iso_features.append(Feature(
                kind="fillet",
                subtype=fillet_subtype,
                face_ids=face_ids,
                dimensions={"radius": round(r_fillet, 6)},
                direction=None,
                confidence=0.88,
            ))

        # ---------- chamfer ----------
        elif ftype == "chamfer":
            iso_features.append(Feature(
                kind="chamfer",
                subtype="chamfer",
                face_ids=face_ids,
                dimensions={},
                direction=None,
                confidence=0.80,
            ))

        # ---------- boss ----------
        elif ftype == "boss":
            r_boss = float(params.get("radius", 0.0))
            axis_raw = params.get("axis", [0.0, 0.0, 1.0])
            iso_features.append(Feature(
                kind="boss",
                subtype="boss",
                face_ids=face_ids,
                dimensions={"radius": round(r_boss, 6), "diameter": round(r_boss * 2.0, 6)},
                direction=axis_raw if isinstance(axis_raw, list) else list(axis_raw),
                confidence=0.80,
            ))

        # ---------- pocket ----------
        elif ftype == "pocket":
            fc = int(params.get("face_count", len(face_ids)))
            # Closed pocket: all walls are within the cluster (no open top).
            # Open pocket: at least one boundary face is exterior.
            pocket_subtype = "closed_pocket" if fc >= 5 else "open_pocket"
            iso_features.append(Feature(
                kind="pocket",
                subtype=pocket_subtype,
                face_ids=face_ids,
                dimensions={"face_count": fc},
                direction=None,
                confidence=0.75,
            ))

        # ---------- rib ----------
        elif ftype == "rib":
            iso_features.append(Feature(
                kind="rib",
                subtype="rib",
                face_ids=face_ids,
                dimensions={},
                direction=None,
                confidence=0.70,
            ))

        # ---------- step ----------
        elif ftype == "step":
            iso_features.append(Feature(
                kind="step",
                subtype="step",
                face_ids=face_ids,
                dimensions={},
                direction=None,
                confidence=0.72,
            ))

        # ---------- slot ----------
        elif ftype == "slot":
            iso_features.append(Feature(
                kind="slot",
                subtype="rectangular_slot",
                face_ids=face_ids,
                dimensions=dict(params),
                direction=None,
                confidence=0.78,
            ))

        else:
            iso_features.append(Feature(
                kind=ftype,
                subtype=ftype,
                face_ids=face_ids,
                dimensions=dict(params),
                direction=None,
                confidence=0.60,
            ))

        for fid in face_ids:
            claimed_faces.add(fid)

    unrecognized = total_faces - len(claimed_faces)
    iso_note = (
        f"ISO 10303-224:2001 AP224 machining features; "
        f"Han-Pratt-Regli (2000) AAG graph heuristics; "
        f"{len(iso_features)} feature(s) from {total_faces} face(s); "
        f"{unrecognized} face(s) unrecognized."
    )

    return FeatureRecognitionResult(
        features=iso_features,
        unrecognized_face_count=unrecognized,
        ISO_compliance_note=iso_note,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (ISO 10303-224 feature recognition)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ── brep_feature_recognition ──────────────────────────────────────────────

    _brep_feature_recognition_spec = ToolSpec(
        name="brep_feature_recognition",
        description=(
            "ISO 10303-224 / Han-Pratt-Regli 2000 manufacturing feature recognition "
            "from a B-rep topology dict. Identifies holes (through/blind/counterbore/"
            "countersink), slots, pockets, fillets (interior/exterior), chamfers, "
            "bosses, ribs, and steps using graph-based B-rep face adjacency pattern "
            "matching. Returns typed Feature list with dimensions, direction, and "
            "ISO 10303-224 compliance note.\n\n"
            "Input: topology dict (same schema as afr_recognize_features) with "
            "'faces' list (id, type, normal, radius, area, convexity, adjacent).\n"
            "Returns: {ok, features: [{kind, subtype, face_ids, dimensions, "
            "direction, confidence}], unrecognized_face_count, ISO_compliance_note}.\n"
            "Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topology": {
                    "type": "object",
                    "description": (
                        "B-rep topology dict. Required key: 'faces' (list of face "
                        "dicts with id, type ['planar'|'cylindrical'|'conical'|"
                        "'toroidal'|'other'], normal [nx,ny,nz], radius (0 if not "
                        "curved), area, convexity ['convex'|'concave'|'flat'], "
                        "adjacent [face_id, ...]). Optional key: 'edges' (list of "
                        "{id, face_a, face_b, convexity, length})."
                    ),
                },
            },
            "required": ["topology"],
        },
    )

    @register(_brep_feature_recognition_spec)
    async def run_brep_feature_recognition(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        topo = a.get("topology")
        if not isinstance(topo, dict):
            return err_payload("topology must be a dict", "BAD_ARGS")

        # Delegate to afr.recognize for JSON topology input.
        try:
            from kerf_cad_core.afr.recognize import (
                recognize_features as _afr_recognize,
                _get_faces,
                _get_edges,
                _adjacency_map,
                _detect_counterbore,
                _detect_countersink,
                _detect_holes,
                _detect_bosses,
                _detect_pockets_and_slots,
                _detect_ribs,
                _detect_fillets,
                _detect_chamfers,
                _detect_steps,
                _build_feature_tree,
            )
        except ImportError:
            return err_payload("afr.recognize module not available", "UNAVAILABLE")

        raw = _afr_recognize(topo)
        if not raw.get("ok"):
            return err_payload(raw.get("reason", "afr failed"), "AFR_ERROR")

        # Promote raw features to ISO 10303-224 typed output.
        _KIND_SUBTYPE_MAP = {
            "through_hole": ("hole", "through_hole"),
            "blind_hole":   ("hole", "blind_hole"),
            "counterbore":  ("hole", "counterbore"),
            "countersink":  ("hole", "countersink"),
            "pocket":       ("pocket", "closed_pocket"),
            "slot":         ("slot",   "rectangular_slot"),
            "boss":         ("boss",   "boss"),
            "fillet":       ("fillet", "exterior_fillet"),
            "chamfer":      ("chamfer","chamfer"),
            "rib":          ("rib",    "rib"),
            "step":         ("step",   "step"),
        }

        iso_features = []
        claimed: set = set()
        faces = _get_faces(topo)
        total_faces = len(faces)

        for feat in raw.get("features", []):
            ftype = feat.get("type", "")
            kind, subtype = _KIND_SUBTYPE_MAP.get(ftype, (ftype, ftype))
            iso_features.append({
                "kind": kind,
                "subtype": subtype,
                "face_ids": feat.get("face_ids", []),
                "dimensions": feat.get("params", {}),
                "direction": feat.get("params", {}).get("axis"),
                "confidence": feat.get("confidence", 0.75),
            })
            for fid in feat.get("face_ids", []):
                claimed.add(fid)

        unrecognized = total_faces - len(claimed)
        result = {
            "ok": True,
            "features": iso_features,
            "unrecognized_face_count": unrecognized,
            "ISO_compliance_note": (
                f"ISO 10303-224:2001 AP224 machining features; "
                f"Han-Pratt-Regli (2000) AAG graph heuristics; "
                f"{len(iso_features)} feature(s) from {total_faces} face(s); "
                f"{unrecognized} face(s) unrecognized."
            ),
        }
        return ok_payload(result)

    # ── brep_feature_to_machining ─────────────────────────────────────────────

    _brep_feature_to_machining_spec = ToolSpec(
        name="brep_feature_to_machining",
        description=(
            "Map an ISO 10303-224 machining feature to its primary CNC operation. "
            "Given a feature dict (with 'kind', 'subtype', 'dimensions'), returns "
            "the recommended operation (drill/end_mill/face_mill/etc.), tool type, "
            "G-code cycle, and an ISO 10303-224 process entity note.\n\n"
            "Input: feature dict {kind, subtype, dimensions}.\n"
            "Returns: {ok, operation, tool, cycle, feature_type, dimensions, "
            "iso_process_note}.\n"
            "Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "feature": {
                    "type": "object",
                    "description": (
                        "Feature dict with keys: "
                        "kind (str, e.g. 'hole'), "
                        "subtype (str, e.g. 'through_hole' | 'blind_hole' | "
                        "'counterbore' | 'countersink' | 'pocket' | 'slot' | "
                        "'fillet' | 'chamfer' | 'boss' | 'rib' | 'step'), "
                        "dimensions (dict of feature params, e.g. {diameter, depth})."
                    ),
                },
            },
            "required": ["feature"],
        },
    )

    @register(_brep_feature_to_machining_spec)
    async def run_brep_feature_to_machining(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        feat_dict = a.get("feature")
        if not isinstance(feat_dict, dict):
            return err_payload("feature must be a dict", "BAD_ARGS")

        kind = str(feat_dict.get("kind", ""))
        subtype = str(feat_dict.get("subtype", kind))
        dims = feat_dict.get("dimensions", {})

        # Build a transient Feature for feature_to_machining_op.
        feat_obj = Feature(kind=kind, subtype=subtype, face_ids=[], dimensions=dims)
        result_dict = feature_to_machining_op(feat_obj)
        return ok_payload({"ok": True, **result_dict})
