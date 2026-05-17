"""evaluators.py — concrete Feature kinds + their evaluators.

Each evaluator translates a :class:`Feature` (its ``params`` and resolved
``inputs``) into a call to one of the existing Body-emitting geometry verbs
and constructs a :class:`NamingTable` mapping the structural roles of the
produced topology to live entities. The naming table is what makes
downstream :class:`PersistentSelector` references survive parameter edits.

The evaluator set covers a real production workflow:

  * Box / Cylinder / Sphere primitives
  * Boolean union / difference / intersection
  * Edge Chamfer (constant width)
  * Edge Fillet (rolling-ball)

The roles assigned by each evaluator are deliberately structural — they
encode the *shape* of the produced topology, not any numeric parameter
value, so a parameter edit cleanly preserves the names.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.boolean import (
    body_difference,
    body_intersection,
    body_union,
)
from kerf_cad_core.geom.brep import (
    Body,
    CylinderSurface,
    Edge,
    Face,
    Plane,
    SphereSurface,
    Vertex,
)
from kerf_cad_core.geom.brep_build import (
    box_to_body,
    cylinder_to_body,
    sphere_to_body,
)
from kerf_cad_core.geom.chamfer import chamfer_edge
from kerf_cad_core.geom.fillet_solid import fillet_solid_edge
from kerf_cad_core.geom.history.dag import (
    EvaluationContext,
    EvaluationResult,
    FeatureDAG,
)
from kerf_cad_core.geom.history.feature import (
    Feature,
    FeatureRef,
    MissingReferenceError,
    PersistentSelector,
)
from kerf_cad_core.geom.history.persistent_naming import (
    NamingTable,
    edge_role_for_box,
    face_role_for_box_planar,
    vertex_role_for_box,
)


# ---------------------------------------------------------------------------
# Helper constructors — these wrap Feature() with the right ``kind`` and
# ``params`` shape so users don't have to memorise the schema.
# ---------------------------------------------------------------------------


def BoxFeature(
    corner: Tuple[float, float, float],
    dx: float,
    dy: float,
    dz: float,
    *,
    tol: float = 1e-7,
    id: Optional[str] = None,
) -> Feature:
    """Construct a ``"box"``-kind Feature."""
    kwargs: Dict[str, Any] = {
        "kind": "box",
        "params": {
            "corner": tuple(float(c) for c in corner),
            "dx": float(dx),
            "dy": float(dy),
            "dz": float(dz),
            "tol": float(tol),
        },
    }
    if id is not None:
        kwargs["id"] = id
    return Feature(**kwargs)


def CylinderFeature(
    axis_pt: Tuple[float, float, float],
    axis_dir: Tuple[float, float, float],
    radius: float,
    height: float,
    *,
    tol: float = 1e-7,
    id: Optional[str] = None,
) -> Feature:
    kwargs: Dict[str, Any] = {
        "kind": "cylinder",
        "params": {
            "axis_pt": tuple(float(c) for c in axis_pt),
            "axis_dir": tuple(float(c) for c in axis_dir),
            "radius": float(radius),
            "height": float(height),
            "tol": float(tol),
        },
    }
    if id is not None:
        kwargs["id"] = id
    return Feature(**kwargs)


def SphereFeature(
    centre: Tuple[float, float, float],
    radius: float,
    *,
    tol: float = 1e-7,
    id: Optional[str] = None,
) -> Feature:
    kwargs: Dict[str, Any] = {
        "kind": "sphere",
        "params": {
            "centre": tuple(float(c) for c in centre),
            "radius": float(radius),
            "tol": float(tol),
        },
    }
    if id is not None:
        kwargs["id"] = id
    return Feature(**kwargs)


def BooleanFeature(
    op: str,
    a: FeatureRef,
    b: FeatureRef,
    *,
    tol: float = 1e-6,
    id: Optional[str] = None,
) -> Feature:
    """Construct a ``"boolean"``-kind Feature.

    ``op`` must be one of ``"union"``, ``"difference"``, ``"intersection"``.
    """
    if op not in {"union", "difference", "intersection"}:
        raise ValueError(
            f"BooleanFeature: op must be union/difference/intersection, got {op!r}"
        )
    kwargs: Dict[str, Any] = {
        "kind": "boolean",
        "inputs": {"a": a, "b": b},
        "params": {"op": op, "tol": float(tol)},
    }
    if id is not None:
        kwargs["id"] = id
    return Feature(**kwargs)


def ChamferEdgeFeature(
    body: FeatureRef,
    edge: PersistentSelector,
    width: float,
    *,
    tol: float = 1e-6,
    id: Optional[str] = None,
) -> Feature:
    """Construct a ``"chamfer_edge"``-kind Feature.

    ``edge`` is a :class:`PersistentSelector` referring to an edge on the
    feature that produced ``body`` (typically the same feature; the body and
    the edge come from the same upstream).
    """
    kwargs: Dict[str, Any] = {
        "kind": "chamfer_edge",
        "inputs": {"body": body, "edge": edge},
        "params": {"width": float(width), "tol": float(tol)},
    }
    if id is not None:
        kwargs["id"] = id
    return Feature(**kwargs)


def FilletEdgeFeature(
    body: FeatureRef,
    edge: PersistentSelector,
    radius: float,
    *,
    tol: float = 1e-6,
    id: Optional[str] = None,
) -> Feature:
    kwargs: Dict[str, Any] = {
        "kind": "fillet_edge",
        "inputs": {"body": body, "edge": edge},
        "params": {"radius": float(radius), "tol": float(tol)},
    }
    if id is not None:
        kwargs["id"] = id
    return Feature(**kwargs)


# ---------------------------------------------------------------------------
# Box evaluator
# ---------------------------------------------------------------------------


def _eval_box(feature: Feature, ctx: EvaluationContext) -> EvaluationResult:
    p = feature.params
    body = box_to_body(
        corner=p["corner"],
        dx=p["dx"],
        dy=p["dy"],
        dz=p["dz"],
        tol=p.get("tol", 1e-7),
    )
    table = _build_box_naming_table(feature.id, body)
    return EvaluationResult(body=body, naming_table=table)


def _build_box_naming_table(feature_id: str, body: Body) -> NamingTable:
    """Populate a :class:`NamingTable` for a box Body.

    Roles assigned:
      * face: +X, -X, +Y, -Y, +Z, -Z
      * edge: sorted pair of incident face roles, e.g. ``+Y/+Z``
      * vertex: sorted triple of octant signs, e.g. ``+X/+Y/-Z``
    """
    table = NamingTable(feature_id=feature_id)
    # Faces — by axis-aligned normal.
    face_role_map: Dict[Face, str] = {}
    for f in body.all_faces():
        role = face_role_for_box_planar(f)
        if role is not None:
            table.register_face(role, f)
            face_role_map[f] = role
    # Edges — by sorted pair of incident face roles.
    edge_incident: Dict[int, List[Face]] = {}
    for f in body.all_faces():
        for lp in f.loops:
            for ce in lp.coedges:
                e = ce.edge
                edge_incident.setdefault(id(e), []).append(f)
    for f in body.all_faces():
        for lp in f.loops:
            for ce in lp.coedges:
                e = ce.edge
                if id(e) not in edge_incident:
                    continue
                # We want exactly two distinct incident faces with roles.
                incident = edge_incident[id(e)]
                role_pairs = []
                for inc_f in incident:
                    r = face_role_map.get(inc_f)
                    if r is not None and r not in role_pairs:
                        role_pairs.append(r)
                if len(role_pairs) >= 2:
                    pair_sorted = sorted(role_pairs[:2])
                    role = f"{pair_sorted[0]}/{pair_sorted[1]}"
                    if role not in table.edges:
                        table.register_edge(role, e)
    # Vertices — by octant about the centroid of the box.
    verts = body.all_vertices()
    if verts:
        centroid = np.mean(
            np.array([v.point for v in verts], dtype=float), axis=0
        )
        for v in verts:
            role = vertex_role_for_box(v.point, centroid)
            if role not in table.vertices:
                table.register_vertex(role, v)
    return table


# ---------------------------------------------------------------------------
# Cylinder evaluator
# ---------------------------------------------------------------------------


def _eval_cylinder(feature: Feature, ctx: EvaluationContext) -> EvaluationResult:
    p = feature.params
    body = cylinder_to_body(
        axis_pt=p["axis_pt"],
        axis_dir=p["axis_dir"],
        radius=p["radius"],
        height=p["height"],
        tol=p.get("tol", 1e-7),
    )
    table = _build_cylinder_naming_table(feature.id, body, p["axis_dir"])
    return EvaluationResult(body=body, naming_table=table)


def _build_cylinder_naming_table(
    feature_id: str,
    body: Body,
    axis_dir: Tuple[float, float, float],
) -> NamingTable:
    """Populate naming for a cylinder Body.

    Faces:
      * lateral      — the CylinderSurface
      * cap_bottom   — planar cap at axis_pt
      * cap_top      — planar cap at axis_pt + height*axis_dir

    Edges:
      * rim_bottom, rim_top, seam
    """
    table = NamingTable(feature_id=feature_id)
    axis = np.asarray(axis_dir, dtype=float)
    axis /= max(float(np.linalg.norm(axis)), 1e-15)

    cap_faces: List[Tuple[float, Face]] = []
    lateral_face: Optional[Face] = None
    for f in body.all_faces():
        if isinstance(f.surface, CylinderSurface):
            lateral_face = f
        elif isinstance(f.surface, Plane):
            # Project surface origin onto the axis to decide top vs bottom.
            origin = np.asarray(f.surface.origin, dtype=float)
            proj = float(np.dot(origin, axis))
            cap_faces.append((proj, f))
    if lateral_face is not None:
        table.register_face("lateral", lateral_face)
    cap_faces.sort(key=lambda t: t[0])
    if len(cap_faces) >= 1:
        table.register_face("cap_bottom", cap_faces[0][1])
    if len(cap_faces) >= 2:
        table.register_face("cap_top", cap_faces[-1][1])

    # Edges: rims (circular) + seam (straight on lateral)
    for e in body.all_edges():
        try:
            length = float(
                np.linalg.norm(
                    np.asarray(e.end_point()) - np.asarray(e.start_point())
                )
            )
        except Exception:
            length = 0.0
        # Two endpoints coincident -> circle
        is_circle = length < 1e-9 and e.v_start is e.v_end
        if is_circle:
            # Distinguish top vs bottom by midpoint projection on axis
            try:
                midpoint = np.asarray(
                    e.point(0.5 * (e.t0 + e.t1)), dtype=float
                )
                proj = float(np.dot(midpoint, axis))
            except Exception:
                proj = 0.0
            # Assign whichever is lower as rim_bottom
            if "rim_bottom" not in table.edges:
                table.register_edge("rim_bottom", e)
                continue
            existing = table.edges.get("rim_bottom")
            if existing is not None:
                try:
                    existing_mid = np.asarray(
                        existing.point(0.5 * (existing.t0 + existing.t1)),
                        dtype=float,
                    )
                    existing_proj = float(np.dot(existing_mid, axis))
                except Exception:
                    existing_proj = 0.0
                if proj < existing_proj:
                    table.register_edge("rim_top", existing)
                    table.register_edge("rim_bottom", e)
                else:
                    table.register_edge("rim_top", e)
        else:
            if "seam" not in table.edges:
                table.register_edge("seam", e)
    return table


# ---------------------------------------------------------------------------
# Sphere evaluator
# ---------------------------------------------------------------------------


def _eval_sphere(feature: Feature, ctx: EvaluationContext) -> EvaluationResult:
    p = feature.params
    body = sphere_to_body(
        centre=p["centre"],
        radius=p["radius"],
        tol=p.get("tol", 1e-7),
    )
    table = NamingTable(feature_id=feature.id)
    for f in body.all_faces():
        if isinstance(f.surface, SphereSurface):
            table.register_face("surface", f)
            break
    for e in body.all_edges():
        table.register_edge("seam", e)
        break
    return EvaluationResult(body=body, naming_table=table)


# ---------------------------------------------------------------------------
# Boolean evaluator
# ---------------------------------------------------------------------------


def _eval_boolean(feature: Feature, ctx: EvaluationContext) -> EvaluationResult:
    op = feature.params["op"]
    tol = feature.params.get("tol", 1e-6)
    body_a = ctx.upstream_bodies["a"]
    body_b = ctx.upstream_bodies["b"]
    table_a = ctx.upstream_tables["a"]
    table_b = ctx.upstream_tables["b"]

    if op == "union":
        result_body = body_union(body_a, body_b, tol=tol)
    elif op == "difference":
        result_body = body_difference(body_a, body_b, tol=tol)
    elif op == "intersection":
        result_body = body_intersection(body_a, body_b, tol=tol)
    else:
        raise ValueError(f"unknown boolean op {op!r}")

    # Carry forward face roles by signature/centroid match. The B-rep boolean
    # may produce a Body whose faces are freshly constructed but
    # geometrically the same as a survivor of A or B.
    table = NamingTable(feature_id=feature.id)
    _carry_boolean_face_roles(table, result_body, table_a, table_b, op)
    # Edges: roles inherited as the sorted pair of incident face roles
    # (only assigned where both incident faces have roles).
    _build_boolean_edge_roles(table, result_body)

    return EvaluationResult(body=result_body, naming_table=table)


def _face_centroid(face: Face) -> np.ndarray:
    outer = face.outer_loop()
    if outer is None or not outer.coedges:
        return np.zeros(3)
    pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
    # de-dup
    seen = set()
    uniq = []
    for p in pts:
        key = tuple(round(float(x), 9) for x in p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    if not uniq:
        return np.zeros(3)
    return np.mean(np.array(uniq), axis=0)


def _face_normal(face: Face) -> np.ndarray:
    try:
        return np.asarray(face.surface_normal(0.5, 0.5), dtype=float)
    except Exception:
        return np.zeros(3)


def _faces_match(a: Face, b: Face, atol: float = 1e-4) -> bool:
    """Heuristic geometric match between two faces (centroid + normal)."""
    ca, cb = _face_centroid(a), _face_centroid(b)
    if float(np.linalg.norm(ca - cb)) > atol:
        return False
    na, nb = _face_normal(a), _face_normal(b)
    if float(np.linalg.norm(na - nb)) > 1e-3 and float(
        np.linalg.norm(na + nb)
    ) > 1e-3:
        return False
    return True


def _carry_boolean_face_roles(
    out_table: NamingTable,
    result_body: Body,
    table_a: NamingTable,
    table_b: NamingTable,
    op: str,
) -> None:
    """For each face on the result, try to match it to a face on A or B and
    inherit that role (prefixed with ``A:`` or ``B:``). Faces with no
    geometric match get a fresh ``boundary:<i>`` role assigned in
    centroid-sorted order for determinism.
    """
    # Build candidate lists.
    a_candidates = [(role, table_a.faces[role]) for role in table_a.face_roles()]
    b_candidates = [(role, table_b.faces[role]) for role in table_b.face_roles()]

    result_faces = list(result_body.all_faces())
    boundary_faces: List[Face] = []

    for f in result_faces:
        matched_role: Optional[str] = None
        for role, src_face in a_candidates:
            if _faces_match(f, src_face):
                matched_role = f"A:{role}"
                break
        if matched_role is None:
            for role, src_face in b_candidates:
                if _faces_match(f, src_face):
                    matched_role = f"B:{role}"
                    break
        if matched_role is not None and matched_role not in out_table.faces:
            out_table.register_face(matched_role, f)
        else:
            boundary_faces.append(f)

    # Deterministically sort boundary faces by centroid, then assign indices.
    boundary_faces.sort(
        key=lambda f: tuple(round(float(x), 6) for x in _face_centroid(f))
    )
    for idx, f in enumerate(boundary_faces):
        role = f"boundary:{idx}"
        if role not in out_table.faces:
            out_table.register_face(role, f)


def _build_boolean_edge_roles(table: NamingTable, body: Body) -> None:
    """Assign each edge a role from the sorted pair of its incident face
    roles (using the roles already registered on ``table``)."""
    face_to_role: Dict[int, str] = {}
    for role, f in table.faces.items():
        face_to_role[id(f)] = role

    edge_incident: Dict[int, List[Face]] = {}
    for f in body.all_faces():
        for lp in f.loops:
            for ce in lp.coedges:
                e = ce.edge
                edge_incident.setdefault(id(e), []).append(f)

    seen_roles: set = set()
    for e_id, faces in edge_incident.items():
        roles = []
        for f in faces:
            r = face_to_role.get(id(f))
            if r is not None and r not in roles:
                roles.append(r)
        if len(roles) < 2:
            continue
        pair = sorted(roles[:2])
        role = f"{pair[0]}|{pair[1]}"
        if role in seen_roles:
            # Append a disambiguation index in centroid order.
            for i in range(1, 999):
                cand = f"{role}#{i}"
                if cand not in seen_roles:
                    role = cand
                    break
        seen_roles.add(role)
        # find the edge object: faces[0]'s loop hosts a coedge with this edge
        target_edge: Optional[Edge] = None
        for f in faces:
            for lp in f.loops:
                for ce in lp.coedges:
                    if id(ce.edge) == e_id:
                        target_edge = ce.edge
                        break
                if target_edge is not None:
                    break
            if target_edge is not None:
                break
        if target_edge is not None and role not in table.edges:
            table.register_edge(role, target_edge)


# ---------------------------------------------------------------------------
# Chamfer evaluator
# ---------------------------------------------------------------------------


def _eval_chamfer_edge(
    feature: Feature, ctx: EvaluationContext
) -> EvaluationResult:
    body_ref = feature.inputs["body"]
    edge_sel = feature.inputs["edge"]
    if not isinstance(edge_sel, PersistentSelector):
        raise TypeError(
            "chamfer_edge: 'edge' input must be a PersistentSelector"
        )

    # Resolve the live edge through the upstream producing feature's naming
    # table. This is the keystone — the role tag, not the Python object id,
    # is what the user sees.
    edge = ctx.resolve_selector(edge_sel)
    if not isinstance(edge, Edge):
        raise TypeError(
            f"chamfer_edge: selector resolved to {type(edge).__name__}, not Edge"
        )

    # Upstream body
    body = ctx.upstream_bodies.get("body")
    if body is None:
        # PersistentSelector path: pick the producing feature's body
        body = ctx.upstream_bodies.get("body__body")
    if body is None:
        raise RuntimeError("chamfer_edge: cannot find upstream body")

    width = float(feature.params["width"])
    tol = float(feature.params.get("tol", 1e-6))

    # Re-find the corresponding edge in the body by identity. Since the edge
    # selector resolved against the producing feature's naming table, the
    # returned Edge object IS an edge of body (same Python object), so it
    # can be passed directly to chamfer_edge.
    new_body = chamfer_edge(body, edge, width, tol=tol)

    # Build naming table for the new body. The chamfer preserves most box
    # topology; the new bevel face gets role ``bevel:<edge_role>``.
    table = NamingTable(feature_id=feature.id)
    # Re-attempt axis-aligned naming on result; for a box-chamfer, the
    # supports plus a new planar bevel face are all axis-aligned-ish but the
    # bevel face is 45 deg (NOT axis aligned). We tag survivors by their
    # axis-aligned role + the bevel by signature.
    bevel_candidates: List[Face] = []
    for f in new_body.all_faces():
        role = face_role_for_box_planar(f)
        if role is not None and role not in table.faces:
            table.register_face(role, f)
        else:
            bevel_candidates.append(f)
    # Tag the bevel face(s) deterministically.
    for idx, f in enumerate(
        sorted(
            bevel_candidates,
            key=lambda fa: tuple(
                round(float(x), 6) for x in _face_centroid(fa)
            ),
        )
    ):
        table.register_face(f"bevel:{edge_sel.role}#{idx}", f)
    # Edges: inherit by face-pair roles where possible.
    _build_boolean_edge_roles(table, new_body)
    return EvaluationResult(body=new_body, naming_table=table)


# ---------------------------------------------------------------------------
# Fillet evaluator
# ---------------------------------------------------------------------------


def _eval_fillet_edge(
    feature: Feature, ctx: EvaluationContext
) -> EvaluationResult:
    edge_sel = feature.inputs["edge"]
    if not isinstance(edge_sel, PersistentSelector):
        raise TypeError(
            "fillet_edge: 'edge' input must be a PersistentSelector"
        )
    edge = ctx.resolve_selector(edge_sel)
    if not isinstance(edge, Edge):
        raise TypeError(
            f"fillet_edge: selector resolved to {type(edge).__name__}, not Edge"
        )
    body = ctx.upstream_bodies.get("body")
    if body is None:
        body = ctx.upstream_bodies.get("body__body")
    if body is None:
        raise RuntimeError("fillet_edge: cannot find upstream body")

    radius = float(feature.params["radius"])
    tol = float(feature.params.get("tol", 1e-6))

    result = fillet_solid_edge(body, edge, radius, tol=tol)
    if not result.get("ok"):
        # Wrap into a MissingReferenceError-style descriptive failure.
        # This keeps a "too-large fillet that obliterates the edge" path
        # observable to callers (used by the test).
        raise MissingReferenceError(
            edge_sel,
            {
                "face": [],
                "edge": [edge_sel.role],
                "vertex": [],
                "_fillet_failure_reason": [result.get("reason", "unknown")],
            },
        )

    new_body = result.get("body")
    if new_body is None:
        raise RuntimeError("fillet_edge: result body was None")

    table = NamingTable(feature_id=feature.id)
    fillet_face = result.get("fillet_face")
    # Survivors: axis-aligned planar role if possible
    for f in new_body.all_faces():
        if f is fillet_face:
            continue
        role = face_role_for_box_planar(f)
        if role is not None and role not in table.faces:
            table.register_face(role, f)
    if fillet_face is not None:
        table.register_face(f"fillet:{edge_sel.role}", fillet_face)
    # Anything else not yet named: boundary-style
    leftover: List[Face] = [
        f for f in new_body.all_faces() if id(f) not in {id(x) for x in table.faces.values()}
    ]
    for idx, f in enumerate(
        sorted(
            leftover,
            key=lambda fa: tuple(round(float(x), 6) for x in _face_centroid(fa)),
        )
    ):
        cand = f"fillet_side:{edge_sel.role}#{idx}"
        if cand not in table.faces:
            table.register_face(cand, f)
    _build_boolean_edge_roles(table, new_body)
    return EvaluationResult(body=new_body, naming_table=table)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_DEFAULT_EVALUATORS = {
    "box": _eval_box,
    "cylinder": _eval_cylinder,
    "sphere": _eval_sphere,
    "boolean": _eval_boolean,
    "chamfer_edge": _eval_chamfer_edge,
    "fillet_edge": _eval_fillet_edge,
}


def register_default_evaluators(dag: FeatureDAG) -> None:
    """Register the built-in evaluators on a :class:`FeatureDAG`."""
    for kind, ev in _DEFAULT_EVALUATORS.items():
        dag.register_evaluator(kind, ev)


__all__ = [
    "BoxFeature",
    "CylinderFeature",
    "SphereFeature",
    "BooleanFeature",
    "ChamferEdgeFeature",
    "FilletEdgeFeature",
    "register_default_evaluators",
]
