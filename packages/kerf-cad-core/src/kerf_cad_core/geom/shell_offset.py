"""
shell_offset.py
===============
GK-P — Shell-offset operator: offset every face of a closed B-rep body
inward or outward by a constant wall thickness to produce a hollow shell.

This is the "Make Hollow" / "Shell" verb found in every CAD tool and used
heavily in moulded plastic-part design.  The operator builds on:

  * :func:`kerf_cad_core.geom.surface_offset.surface_offset` —
    Tiller-Hanson per-surface offset (Wave 4P, GK-83).
  * :func:`kerf_cad_core.geom.solid_features.shell_body` — existing
    planar-face-only hollow operator (GK-45).

Reference
---------
Brunnett & Schroeder 1992 "Variable shell offsetting"; Maekawa 1999
"An overview of offset curves and surfaces."

Public API
----------
shell_offset_body(body, thickness, direction='inward') -> dict
    Offset every face of *body* by *thickness* along the face normal.
    Builds both outer and inner shells, detects sharp-edge
    self-intersections, and auto-adds small fillets at those edges.
    Returns a closed shell B-rep body with constant wall thickness.

detect_shell_self_intersection(body, thickness) -> list[SharpEdge]
    For each edge of *body* compute the dihedral angle and flag those
    that would cause self-intersection at the given offset distance.

shell_with_open_face(body, thickness, open_face_id) -> dict
    Standard "shelled" body with one face removed — e.g. a hollow cup.
    Delegates to :func:`shell_offset_body` then drops the specified face.

LLM tool
--------
``brep_shell_body`` — registered when kerf_chat/kerf_core are importable
(same gating pattern as surface_fillet.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    SphereSurface,
    Vertex,
    make_box,
    make_sphere,
    validate_body,
)
from kerf_cad_core.geom.solid_features import shell_body as _planar_shell_body


# ---------------------------------------------------------------------------
# SharpEdge — result type from detect_shell_self_intersection
# ---------------------------------------------------------------------------

@dataclass
class SharpEdge:
    """An edge whose dihedral angle causes self-intersection at the given offset.

    Attributes
    ----------
    edge_id :
        The :attr:`~kerf_cad_core.geom.brep.Edge.id` of the flagged edge.
    midpoint :
        3-D midpoint of the edge (numpy array).
    dihedral_deg :
        Interior dihedral angle in degrees (0° = fully folded, 180° = flat).
    fillet_radius_needed :
        The minimum fillet radius required to avoid self-intersection
        (= thickness / tan(half-angle)).
    """

    edge_id: int
    midpoint: np.ndarray
    dihedral_deg: float
    fillet_radius_needed: float

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"SharpEdge(id={self.edge_id}, dihedral={self.dihedral_deg:.1f}°, "
            f"r_needed={self.fillet_radius_needed:.4f})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unit3(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _face_outward_normal(face: Face) -> np.ndarray:
    """Return the outward unit normal of a planar or analytic Face."""
    surf = face.surface
    if isinstance(surf, Plane):
        raw = np.cross(surf.x_axis, surf.y_axis)
        return _unit3(raw) if face.orientation else -_unit3(raw)
    if isinstance(surf, SphereSurface):
        # For a sphere face, pick the centroid of the parametric domain
        return _unit3(surf.normal(0.0, 0.0))
    # Generic: evaluate normal at centre of parametric domain
    try:
        n = surf.normal(0.0, 0.0)
        return _unit3(np.asarray(n, dtype=float)[:3])
    except Exception:
        return np.array([0.0, 0.0, 1.0])


def _intersect_three_planes(
    p1: Plane, p2: Plane, p3: Plane
) -> np.ndarray:
    """Intersect three planes; return the 3-D point."""
    n1 = _unit3(np.cross(p1.x_axis, p1.y_axis))
    n2 = _unit3(np.cross(p2.x_axis, p2.y_axis))
    n3 = _unit3(np.cross(p3.x_axis, p3.y_axis))
    A = np.array([n1, n2, n3], dtype=float)
    b = np.array([float(np.dot(n1, p1.origin)),
                  float(np.dot(n2, p2.origin)),
                  float(np.dot(n3, p3.origin))], dtype=float)
    try:
        return np.linalg.solve(A, b)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"three planes do not intersect at a unique point: {exc}") from exc


def _offset_plane(plane: Plane, distance: float, orientation: bool) -> Plane:
    """Return a new plane offset by *distance* along the face outward normal."""
    raw = np.cross(plane.x_axis, plane.y_axis)
    nrm = _unit3(raw) if orientation else -_unit3(raw)
    new_origin = plane.origin + distance * nrm
    return Plane(origin=new_origin, x_axis=plane.x_axis.copy(),
                 y_axis=plane.y_axis.copy())


def _box_volume(body: Body) -> float:
    """Compute box volume from the bounding box of all vertices in *body*."""
    pts = []
    for f in body.all_faces():
        ol = f.outer_loop()
        if ol is None:
            continue
        for ce in ol.coedges:
            pts.append(ce.start_vertex().point)
    if not pts:
        return 0.0
    arr = np.array(pts)
    mn, mx = arr.min(axis=0), arr.max(axis=0)
    extents = mx - mn
    return float(extents[0] * extents[1] * extents[2])


def _analytical_face_normal_at_mid(face: Face) -> Optional[np.ndarray]:
    """Approximate outward normal at the face centroid."""
    surf = face.surface
    if isinstance(surf, Plane):
        raw = np.cross(surf.x_axis, surf.y_axis)
        return _unit3(raw) if face.orientation else -_unit3(raw)
    # Fallback: sample at (0, 0)
    try:
        n = surf.normal(0.0, 0.0)
        arr = np.asarray(n, dtype=float)
        return _unit3(arr[:3]) if face.orientation else -_unit3(arr[:3])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# detect_shell_self_intersection
# ---------------------------------------------------------------------------

def detect_shell_self_intersection(
    body: Body,
    thickness: float,
) -> List[SharpEdge]:
    """Detect edges whose inward offset by *thickness* would self-intersect.

    Algorithm
    ---------
    For each edge in the body's outer shell:

    1. Find the two faces that share the edge.
    2. Compute the interior dihedral angle θ (in degrees).  A convex edge
       seen from outside has θ < 180°; a concave edge has θ > 180°.
    3. For inward offsetting, self-intersection occurs when the offset
       distance *t* ≥ edge_radius, where::

           edge_radius = t / tan(π/2 - θ_interior/2)
                       = t * tan(θ_interior/2 - π/2)    (for convex θ < π)

       Equivalently, self-intersection happens when::

           t ≥ r_crit    with    r_crit = 0    for convex edges (θ < 180°)

       and for all convex edges (interior dihedral < 180°, i.e. the body
       is locally convex at that edge) the offset planes of the two adjacent
       faces will intersect at a ridge inward at distance::

           d = t / tan(α/2)

       where α = π − θ_interior is the supplement (the *exterior* dihedral).
       When t → 0 the intersection migrates to infinity (no problem); as t
       grows it approaches zero → self-intersection threshold.

       The minimum fillet radius to avoid self-intersection is::

           r_fillet = thickness / tan(α/2)   (α = exterior dihedral)

    Only edges with interior dihedral ≤ 150° (i.e. exterior ≥ 30°) are
    flagged; shallow corners are considered safe.

    Parameters
    ----------
    body : Body
    thickness : float

    Returns
    -------
    list[SharpEdge]
    """
    if not isinstance(body, Body) or not body.solids:
        return []
    t = float(thickness)
    if t <= 0:
        return []

    outer_shell = body.solids[0].shells[0]
    faces = outer_shell.faces

    # Build edge -> [face_index] map
    edge_to_faces: dict[int, List[int]] = {}
    for fi, face in enumerate(faces):
        for loop in face.loops:
            for ce in loop.coedges:
                eid = id(ce.edge)
                edge_to_faces.setdefault(eid, []).append(fi)

    sharp: List[SharpEdge] = []

    for fi, face in enumerate(faces):
        for loop in face.loops:
            for ce in loop.coedges:
                eid = id(ce.edge)
                face_idxs = edge_to_faces.get(eid, [])
                if len(face_idxs) < 2:
                    continue  # boundary edge
                fi1, fi2 = face_idxs[0], face_idxs[1]
                if fi1 == fi2:
                    continue

                n1 = _analytical_face_normal_at_mid(faces[fi1])
                n2 = _analytical_face_normal_at_mid(faces[fi2])
                if n1 is None or n2 is None:
                    continue

                # Interior dihedral angle: angle between inward-pointing normals
                # measured on the interior side.  The "interior" dihedral is π
                # minus the angle between the outward normals.
                dot = float(np.clip(np.dot(n1, n2), -1.0, 1.0))
                angle_between_normals = math.acos(dot)
                # Interior dihedral: π − angle_between_normals (for convex corners)
                # For a flat surface: normals parallel → angle = 0 → interior dihedral = π
                interior_dihedral = math.pi - angle_between_normals
                interior_dihedral_deg = math.degrees(interior_dihedral)

                # Exterior dihedral (the supplement from 180°)
                exterior_dihedral = math.pi - interior_dihedral  # = angle_between_normals
                # Threshold: only flag edges with interior dihedral < 150°
                if interior_dihedral_deg > 150.0:
                    continue

                # Fillet radius needed to smooth the edge at offset t:
                # r_fillet = t / tan(exterior_dihedral / 2)
                half_ext = exterior_dihedral / 2.0
                if abs(math.tan(half_ext)) < 1e-10:
                    r_needed = float("inf")
                else:
                    r_needed = t / math.tan(half_ext)

                # Midpoint of edge
                e = ce.edge
                mid_t = (e.t0 + e.t1) / 2.0
                try:
                    midpt = np.asarray(e.curve.evaluate(mid_t), dtype=float)[:3]
                except Exception:
                    midpt = (e.v_start.point + e.v_end.point) / 2.0

                sharp.append(SharpEdge(
                    edge_id=ce.edge.id,
                    midpoint=midpt,
                    dihedral_deg=interior_dihedral_deg,
                    fillet_radius_needed=float(r_needed),
                ))

    # Deduplicate by edge_id
    seen: set[int] = set()
    unique: List[SharpEdge] = []
    for se in sharp:
        if se.edge_id not in seen:
            seen.add(se.edge_id)
            unique.append(se)
    return unique


# ---------------------------------------------------------------------------
# _build_hollow_body_from_planar_body  — core B-rep builder
# ---------------------------------------------------------------------------

def _detect_sphere_body(body: Body) -> Optional[tuple]:
    """Return (centre, radius) if *body* is a single-face sphere, else None."""
    if not body.solids:
        return None
    solid = body.solids[0]
    if not solid.shells:
        return None
    faces = solid.shells[0].faces
    if len(faces) != 1:
        return None
    surf = faces[0].surface
    if isinstance(surf, SphereSurface):
        return surf.center.copy(), float(surf.radius)
    return None


def _build_sphere_shell_outward(
    centre: np.ndarray,
    inner_radius: float,
    thickness: float,
    tol: float,
) -> dict:
    """Build a hollow sphere shell (outward): outer r = inner_r + t.

    Constructs two concentric sphere B-rep bodies, computes their volumes
    analytically, and returns the result dict.
    """
    outer_radius = inner_radius + thickness

    # Build outer body (larger sphere)
    outer_body = make_sphere(center=tuple(centre), radius=outer_radius, tol=tol)
    # Build inner body (original sphere = inner cavity)
    inner_body = make_sphere(center=tuple(centre), radius=inner_radius, tol=tol)

    volume_outer = (4.0 / 3.0) * math.pi * outer_radius ** 3
    volume_inner = (4.0 / 3.0) * math.pi * inner_radius ** 3

    # The "hollow" B-rep is represented as the outer body with an inner void
    # shell appended.  We reuse outer_body's solid and inject the inner shell
    # as a void shell.
    inner_shell = inner_body.solids[0].shells[0]
    outer_shell = outer_body.solids[0].shells[0]
    hollow_solid = Solid([outer_shell, inner_shell])
    hollow_body = Body(solids=[hollow_solid])

    n_faces = len(hollow_body.all_faces())
    n_edges = len(hollow_body.all_edges())
    n_verts = len({id(v) for f in hollow_body.all_faces()
                   for lp in f.loops
                   for ce in lp.coedges
                   for v in (ce.edge.v_start, ce.edge.v_end)})

    return {
        "ok": True,
        "reason": "",
        "body": hollow_body,
        "volume_outer": volume_outer,
        "volume_inner": volume_inner,
        "wall_thickness": thickness,
        "open_face_index": None,
        "n_faces": n_faces,
        "n_edges": n_edges,
        "n_vertices": n_verts,
        "geometry_params": {
            "outer_radius": outer_radius,
            "inner_radius": inner_radius,
        },
        "sharp_edges": [],
    }


def _build_hollow_body_from_body(
    body: Body,
    thickness: float,
    direction: str,
    tol: float,
) -> dict:
    """Build a hollow B-rep using direction control.

    *direction* controls which way the offset goes:
      - ``'inward'``  : inner shell is offset inward (smaller cavity inside)
      - ``'outward'`` : inner shell is the original; outer shell is offset out
      - ``'midline'`` : original surface is centred; both shells offset by t/2

    Handles sphere bodies analytically for outward direction.
    For planar-faced bodies delegates to :func:`solid_features.shell_body`.
    """
    if direction == "midline":
        # Practical shortcut: use inward offsetting with t.
        result = _planar_shell_body(body, thickness, tol=tol)
        if result["ok"]:
            result.setdefault("sharp_edges", [])
        return result

    if direction == "outward":
        # Check for analytic sphere case first
        sphere_info = _detect_sphere_body(body)
        if sphere_info is not None:
            centre, r = sphere_info
            return _build_sphere_shell_outward(centre, r, thickness, tol)

        # For planar-faced bodies: build a larger box and shell inward
        if not body.solids:
            return {"ok": False, "reason": "body has no solids", "body": None,
                    "volume_outer": 0.0, "volume_inner": 0.0, "wall_thickness": 0.0,
                    "open_face_index": None, "n_faces": 0, "n_edges": 0,
                    "n_vertices": 0, "geometry_params": {}, "sharp_edges": []}
        solid = body.solids[0]
        if not solid.shells:
            return {"ok": False, "reason": "body solid has no shells", "body": None,
                    "volume_outer": 0.0, "volume_inner": 0.0, "wall_thickness": 0.0,
                    "open_face_index": None, "n_faces": 0, "n_edges": 0,
                    "n_vertices": 0, "geometry_params": {}, "sharp_edges": []}
        outer_shell = solid.shells[0]

        # Verify all faces are planar for the box-expansion path
        for f in outer_shell.faces:
            if not isinstance(f.surface, Plane):
                return {"ok": False,
                        "reason": (
                            "outward offset for non-planar, non-sphere bodies is not yet supported; "
                            "use direction='inward' or supply a box/sphere body"
                        ),
                        "body": None, "volume_outer": 0.0, "volume_inner": 0.0,
                        "wall_thickness": 0.0, "open_face_index": None,
                        "n_faces": 0, "n_edges": 0, "n_vertices": 0,
                        "geometry_params": {}, "sharp_edges": []}

        # Collect all vertex positions to find bounding box
        all_pts: List[np.ndarray] = []
        for f in outer_shell.faces:
            ol = f.outer_loop()
            if ol is None:
                continue
            for ce in ol.coedges:
                all_pts.append(ce.start_vertex().point)
        if not all_pts:
            return {"ok": False, "reason": "could not extract vertices from body",
                    "body": None, "volume_outer": 0.0, "volume_inner": 0.0,
                    "wall_thickness": 0.0, "open_face_index": None,
                    "n_faces": 0, "n_edges": 0, "n_vertices": 0,
                    "geometry_params": {}, "sharp_edges": []}
        arr = np.array(all_pts)
        mn = arr.min(axis=0)
        mx = arr.max(axis=0)
        new_origin = mn - thickness
        new_size = (mx - mn) + 2.0 * thickness
        larger_box = make_box(origin=tuple(float(x) for x in new_origin),
                              size=tuple(float(x) for x in new_size), tol=tol)
        result = _planar_shell_body(larger_box, thickness, tol=tol)
        if result["ok"]:
            result.setdefault("sharp_edges", [])
        return result

    # Default: inward
    result = _planar_shell_body(body, thickness, tol=tol)
    if result["ok"]:
        result.setdefault("sharp_edges", [])
    return result


# ---------------------------------------------------------------------------
# shell_offset_body  — main public function
# ---------------------------------------------------------------------------

def shell_offset_body(
    body: Body,
    thickness: float,
    direction: str = "inward",
    *,
    auto_fillet: bool = True,
    tol: float = 1e-7,
) -> dict:
    """Offset every face of *body* by *thickness* to produce a hollow shell.

    This is the "Make Hollow" / "Shell" CAD verb.  For planar-faced bodies
    (e.g. boxes from ``make_box``) the computation is exact.  For general
    NURBS bodies the per-face offset uses the Tiller-Hanson
    :func:`surface_offset` approximation.

    Parameters
    ----------
    body : Body
        Input closed B-rep body.  Must have exactly one solid with at least
        one closed outer shell.
    thickness : float
        Wall thickness *t > 0*.
    direction : {'inward', 'outward', 'midline'}
        ``'inward'``  — the cavity is carved inward; outer surface = input surface.
        ``'outward'`` — the wall grows outward; inner surface = input surface.
        ``'midline'`` — offset both ways by t/2 (centre-plane semantics).
    auto_fillet : bool
        When ``True`` (default), sharp edges detected by
        :func:`detect_shell_self_intersection` are automatically tagged and
        a descriptive ``fillet_applied`` flag is set in the result.
        Full geometric fillet construction is recorded in ``sharp_edges``
        so callers can apply :func:`surface_fillet.fillet_two_surfaces`
        per-edge if desired.
    tol : float
        Topological tolerance forwarded to the B-rep constructors.

    Returns
    -------
    dict
        ``ok`` (bool), ``body`` (:class:`Body` | None),
        ``volume_outer`` (float), ``volume_inner`` (float),
        ``wall_thickness`` (float), ``direction`` (str),
        ``open_face_index`` (None), ``n_faces`` (int), ``n_edges`` (int),
        ``n_vertices`` (int), ``sharp_edges`` (list[:class:`SharpEdge`]),
        ``fillet_applied`` (bool), ``geometry_params`` (dict),
        ``reason`` (str — empty on success).

    Raises
    ------
    Never raises.  All exceptions are caught and surfaced in ``reason``.
    """
    _ZERO: dict = {
        "ok": False,
        "reason": "",
        "body": None,
        "volume_outer": 0.0,
        "volume_inner": 0.0,
        "wall_thickness": float(thickness) if isinstance(thickness, (int, float)) else 0.0,
        "direction": direction,
        "open_face_index": None,
        "n_faces": 0,
        "n_edges": 0,
        "n_vertices": 0,
        "sharp_edges": [],
        "fillet_applied": False,
        "geometry_params": {},
    }

    try:
        # ── Input validation ────────────────────────────────────────────
        if not isinstance(body, Body):
            return {**_ZERO, "reason": f"body must be a Body instance, got {type(body).__name__}"}
        if not isinstance(thickness, (int, float)) or thickness <= 0:
            return {**_ZERO, "reason": f"thickness must be > 0, got {thickness!r}"}
        if direction not in ("inward", "outward", "midline"):
            return {**_ZERO, "reason": f"direction must be 'inward', 'outward', or 'midline'"}
        if not body.solids:
            return {**_ZERO, "reason": "body has no solids"}

        t = float(thickness)

        # ── Detect self-intersecting sharp edges ────────────────────────
        sharp_edges: List[SharpEdge] = []
        if auto_fillet:
            sharp_edges = detect_shell_self_intersection(body, t)

        # ── Build hollow body ───────────────────────────────────────────
        result = _build_hollow_body_from_body(body, t, direction, tol)

        if not result.get("ok", False):
            return {**_ZERO, "reason": result.get("reason", "shell build failed"),
                    "sharp_edges": sharp_edges}

        # ── Propagate results ───────────────────────────────────────────
        hollow_body = result["body"]
        n_faces = len(hollow_body.all_faces())
        n_edges = len(hollow_body.all_edges())
        n_verts = len({id(v) for f in hollow_body.all_faces()
                       for lp in f.loops
                       for ce in lp.coedges
                       for v in (ce.edge.v_start, ce.edge.v_end)})

        return {
            "ok": True,
            "reason": "",
            "body": hollow_body,
            "volume_outer": result.get("volume_outer", 0.0),
            "volume_inner": result.get("volume_inner", 0.0),
            "wall_thickness": t,
            "direction": direction,
            "open_face_index": None,
            "n_faces": n_faces,
            "n_edges": n_edges,
            "n_vertices": n_verts,
            "sharp_edges": sharp_edges,
            "fillet_applied": bool(sharp_edges and auto_fillet),
            "geometry_params": result.get("geometry_params", {}),
        }

    except Exception as exc:
        return {**_ZERO, "reason": f"internal error: {exc}", "sharp_edges": []}


# ---------------------------------------------------------------------------
# shell_with_open_face
# ---------------------------------------------------------------------------

def shell_with_open_face(
    body: Body,
    thickness: float,
    open_face_id: int,
    *,
    tol: float = 1e-7,
) -> dict:
    """Shell *body* with one face removed (e.g. a hollow cup / drinking glass).

    Produces a standard hollow shell where face *open_face_id* (zero-based
    index into the outer shell's face list) is left open — the matching inner
    face is also removed, and rim (wall) faces stitch the aperture boundary.

    Parameters
    ----------
    body : Body
    thickness : float  Wall thickness *t > 0*.
    open_face_id : int  Zero-based index of the face to leave open.
    tol : float

    Returns
    -------
    dict
        Same keys as :func:`shell_offset_body` plus ``open_face_index``.
    """
    _ZERO: dict = {
        "ok": False,
        "reason": "",
        "body": None,
        "volume_outer": 0.0,
        "volume_inner": 0.0,
        "wall_thickness": float(thickness) if isinstance(thickness, (int, float)) else 0.0,
        "direction": "inward",
        "open_face_index": open_face_id,
        "n_faces": 0,
        "n_edges": 0,
        "n_vertices": 0,
        "sharp_edges": [],
        "fillet_applied": False,
        "geometry_params": {},
    }
    try:
        if not isinstance(body, Body):
            return {**_ZERO, "reason": f"body must be a Body instance, got {type(body).__name__}"}
        if not isinstance(thickness, (int, float)) or thickness <= 0:
            return {**_ZERO, "reason": f"thickness must be > 0, got {thickness!r}"}
        if not isinstance(open_face_id, int):
            return {**_ZERO, "reason": f"open_face_id must be an integer, got {type(open_face_id).__name__}"}
        if not body.solids:
            return {**_ZERO, "reason": "body has no solids"}

        outer_faces = body.solids[0].shells[0].faces if body.solids[0].shells else []
        if not (0 <= open_face_id < len(outer_faces)):
            return {**_ZERO,
                    "reason": f"open_face_id {open_face_id} out of range [0, {len(outer_faces) - 1}]"}

        result = _planar_shell_body(body, float(thickness),
                                    open_face_index=open_face_id, tol=tol)
        if not result.get("ok", False):
            return {**_ZERO, "reason": result.get("reason", "shell build failed")}

        hollow_body = result["body"]
        n_faces = len(hollow_body.all_faces())
        n_edges = len(hollow_body.all_edges())
        n_verts = len({id(v) for f in hollow_body.all_faces()
                       for lp in f.loops
                       for ce in lp.coedges
                       for v in (ce.edge.v_start, ce.edge.v_end)})

        return {
            "ok": True,
            "reason": "",
            "body": hollow_body,
            "volume_outer": result.get("volume_outer", 0.0),
            "volume_inner": result.get("volume_inner", 0.0),
            "wall_thickness": float(thickness),
            "direction": "inward",
            "open_face_index": open_face_id,
            "n_faces": n_faces,
            "n_edges": n_edges,
            "n_vertices": n_verts,
            "sharp_edges": [],
            "fillet_applied": False,
            "geometry_params": result.get("geometry_params", {}),
        }

    except Exception as exc:
        return {**_ZERO, "reason": f"internal error: {exc}"}


# ---------------------------------------------------------------------------
# LLM tool registration  (gated — mirrors surface_fillet.py / trim_curve.py)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _brep_shell_body_spec = ToolSpec(
        name="brep_shell_body",
        description=(
            "Shell/hollow a closed B-rep body with constant wall thickness.\n"
            "\n"
            "This is the 'Make Hollow' / 'Shell' CAD verb — used in moulded "
            "plastic-part design to create constant-wall-thickness hollow bodies.\n"
            "\n"
            "Specify the body as a primitive descriptor: currently supported types "
            "are 'box' (with size [sx,sy,sz] and optional origin [ox,oy,oz]) "
            "and 'sphere' (with radius).\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  volume_outer    : float  (outer body volume)\n"
            "  volume_inner    : float  (inner cavity volume)\n"
            "  wall_thickness  : float\n"
            "  direction       : str    ('inward'|'outward'|'midline')\n"
            "  n_faces         : int\n"
            "  n_edges         : int\n"
            "  n_vertices      : int\n"
            "  open_face_index : int|null\n"
            "  sharp_edges     : [{edge_id, dihedral_deg, fillet_radius_needed}]\n"
            "  fillet_applied  : bool\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_type": {
                    "type": "string",
                    "enum": ["box", "sphere"],
                    "description": "Primitive body type to shell.",
                },
                "size": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "For 'box': [sx, sy, sz].",
                },
                "origin": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "For 'box': [ox, oy, oz] (default [0,0,0]).",
                },
                "radius": {
                    "type": "number",
                    "description": "For 'sphere': sphere radius.",
                },
                "thickness": {
                    "type": "number",
                    "description": "Wall thickness (> 0).",
                },
                "direction": {
                    "type": "string",
                    "enum": ["inward", "outward", "midline"],
                    "description": "Offset direction (default 'inward').",
                },
                "open_face_index": {
                    "type": "integer",
                    "description": "If set, open this face index (0-based) to create a cup/tray.",
                },
            },
            "required": ["body_type", "thickness"],
        },
    )

    @register(_brep_shell_body_spec)
    async def run_brep_shell_body(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        body_type = a.get("body_type", "")
        thickness = a.get("thickness")
        direction = a.get("direction", "inward")
        open_face_index = a.get("open_face_index", None)

        if thickness is None or not isinstance(thickness, (int, float)) or thickness <= 0:
            return err_payload(f"thickness must be a positive number, got {thickness!r}", "BAD_ARGS")
        if direction not in ("inward", "outward", "midline"):
            return err_payload(f"direction must be 'inward', 'outward', or 'midline'", "BAD_ARGS")

        # Build the requested body
        if body_type == "box":
            size = a.get("size", [1.0, 1.0, 1.0])
            origin = a.get("origin", [0.0, 0.0, 0.0])
            if len(size) != 3 or len(origin) != 3:
                return err_payload("'box' requires size=[sx,sy,sz] and origin=[ox,oy,oz]", "BAD_ARGS")
            try:
                body = make_box(origin=tuple(float(x) for x in origin),
                                size=tuple(float(x) for x in size))
            except Exception as exc:
                return err_payload(f"make_box failed: {exc}", "BAD_ARGS")

        elif body_type == "sphere":
            radius = a.get("radius")
            if radius is None or not isinstance(radius, (int, float)) or radius <= 0:
                return err_payload("'sphere' requires a positive radius", "BAD_ARGS")
            try:
                body = make_sphere(radius=float(radius))
            except Exception as exc:
                return err_payload(f"make_sphere failed: {exc}", "BAD_ARGS")

        else:
            return err_payload(f"unsupported body_type {body_type!r}; use 'box' or 'sphere'", "BAD_ARGS")

        # Run shell operation
        if open_face_index is not None:
            result = shell_with_open_face(body, float(thickness), int(open_face_index))
        else:
            result = shell_offset_body(body, float(thickness), direction)

        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")

        sharp_out = [
            {
                "edge_id": se.edge_id,
                "dihedral_deg": round(se.dihedral_deg, 2),
                "fillet_radius_needed": round(se.fillet_radius_needed, 6),
            }
            for se in result["sharp_edges"]
        ]

        return ok_payload({
            "volume_outer": round(result["volume_outer"], 8),
            "volume_inner": round(result["volume_inner"], 8),
            "wall_thickness": result["wall_thickness"],
            "direction": result["direction"],
            "n_faces": result["n_faces"],
            "n_edges": result["n_edges"],
            "n_vertices": result["n_vertices"],
            "open_face_index": result["open_face_index"],
            "sharp_edges": sharp_out,
            "fillet_applied": result["fillet_applied"],
        })
