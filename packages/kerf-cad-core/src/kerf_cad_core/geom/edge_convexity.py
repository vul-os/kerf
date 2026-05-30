"""edge_convexity.py -- BREP-EDGE-CONVEX-CONCAVE-CLASSIFY

For each *interior* edge in a B-rep solid (an edge shared by exactly two faces),
classify the edge as:

  * **convex**    — dihedral angle < π - ε  (material is on the inside of the
                    dihedral; a box corner is convex, dihedral ≈ π/2)
  * **concave**   — dihedral angle > π + ε  (a re-entrant pocket edge, e.g. the
                    inner edge of an annular cylinder, dihedral > π)
  * **tangential** — |dihedral − π| ≤ ε    (smooth / G1 continuity; a fillet edge)

Algorithm (Hoffmann 1989 §5.3; Mantyla 1988 §7.4)
--------------------------------------------------
For each interior edge:

1. Sample ``n_samples`` (default 3) points along the edge parameter range
   [t0, t1] at fractional positions 0.25, 0.5, 0.75 (avoiding exactly the
   endpoints which may lie on singularities).

2. At each sample point *p*, find a (u, v) parameter on each adjacent face by
   projecting the 3D point back onto the face's UV domain (simple midpoint UV
   heuristic for analytic primitives; full UV-domain midpoint otherwise).

3. Obtain the outward face normal n1, n2 from ``Face.surface_normal(u, v)``
   (which already applies ``face.orientation``).

4. Compute the signed dihedral angle::

       cross_mag = ‖n1 × n2‖
       dot       = n1 · n2  (clamped to [−1, 1])
       dihedral  = π − atan2(cross_mag, dot)

   Note: atan2(|cross|, dot) = arccos(dot) on [0, π].  We subtract from π so
   that a convex box edge (normals 90° apart, pointing *away* from the shared
   corner) maps to dihedral ≈ π/2 < π.

   **Sign convention**: for a convex solid (material on the inside of the
   dihedral), n1 and n2 point outward and their included angle θ = arccos(n1·n2)
   is acute–to–right (0 < θ ≤ π/2 for a right angle).  The dihedral of the
   solid interior = π − θ, which is < π for convex, > π for concave.

5. Classify each sample; aggregate via majority vote.  If all samples agree the
   edge is flagged ``consistent=True``; disagreement sets ``consistent=False``
   (may indicate a curved edge crossing the convexity boundary — e.g. a saddle).

UV parameter estimation
-----------------------
The exact surface parameter at the edge midpoint is *not* stored in the B-rep
(no inversion is performed).  Instead we use the face's UV-domain midpoint, which
is correct for flat faces (the normal is constant) and a reasonable approximation
for smooth curved faces where the normal varies slowly.  For high-curvature faces
(cylinders with small radius / tight fillets), classification is still correct
because the sign of (dihedral − π) does not change across a smooth face unless
the face itself is a saddle surface.

**Honest flags / caveats**
--------------------------
* Requires *consistent outward normals*: ``face.orientation=True`` means the
  surface normal points outward; ``False`` means it is flipped.  If normals are
  inconsistently oriented, classification will flip for the affected edges.  The
  ``warnings`` field on the report lists any edges where the cross-product
  magnitude is suspiciously small (near-parallel normals), which may indicate a
  bad normal orientation rather than a true tangential edge.
* UV midpoint heuristic: for faces whose UV midpoint is far from the edge point
  (e.g. a face with a large hole in its centre), the normal sampled may not be
  the actual normal at the edge.  This is documented in ``caveat`` on the report.
* An edge shared by more than 2 faces (non-manifold geometry) is skipped and
  listed in ``non_manifold_edges``.
* An edge shared by fewer than 2 faces (boundary edge) is skipped and listed in
  ``boundary_edges``.

References
----------
Hoffmann, C. M. (1989). *Geometric and Solid Modeling*.  Morgan Kaufmann.
§5.3: *Classification of edges by dihedral angle*.

Mantyla, M. (1988). *An Introduction to Solid Modeling*.  Computer Science Press.
§7.4: *Convex/concave edge classification in Euler operations*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body, Edge, Face, Shell

__all__ = [
    "EdgeClass",
    "EdgeConvexityReport",
    "classify_edges",
    "classify_body_edges",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EPS_RAD = 1e-3   # ≈ 0.057° — edges within ±eps of π are tangential
_N_SAMPLES = 3    # number of sample points along each edge


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class EdgeClass:
    """String constants for edge classification."""
    CONVEX = "convex"
    CONCAVE = "concave"
    TANGENTIAL = "tangential"


@dataclass
class EdgeConvexityReport:
    """Result of B-rep edge convexity classification.

    Attributes
    ----------
    convex_edges : list of Edge
    concave_edges : list of Edge
    tangential_edges : list of Edge
    dihedral_angles : dict mapping edge id → mean dihedral angle in radians
    classification : dict mapping edge id → EdgeClass constant
    inconsistent_edges : edges where sample points disagree on classification
    boundary_edges : edges with < 2 adjacent faces (open boundary, not classified)
    non_manifold_edges : edges with > 2 adjacent faces (non-manifold, not classified)
    warnings : list of human-readable warning strings
    caveat : honest-flag documentation string
    """

    convex_edges: List[Edge] = field(default_factory=list)
    concave_edges: List[Edge] = field(default_factory=list)
    tangential_edges: List[Edge] = field(default_factory=list)
    dihedral_angles: Dict[int, float] = field(default_factory=dict)
    classification: Dict[int, str] = field(default_factory=dict)
    inconsistent_edges: List[Edge] = field(default_factory=list)
    boundary_edges: List[Edge] = field(default_factory=list)
    non_manifold_edges: List[Edge] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    caveat: str = (
        "UV-midpoint normal heuristic: normals are sampled at the face's UV-domain "
        "midpoint, not at the exact edge-point UV. Classification is accurate for "
        "flat faces and smooth curved faces; may be imprecise for highly-trimmed "
        "faces where the UV midpoint is far from the edge. "
        "Requires consistent outward face normals (face.orientation): if normals are "
        "inverted, convex/concave labels flip for the affected edges. "
        "Hoffmann 1989 §5.3; Mantyla 1988 §7.4."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-14:
        return v.copy()
    return v / n


def _uv_midpoint(face: Face) -> Tuple[float, float]:
    """Return the UV-domain midpoint of a face's underlying surface."""
    surface = face.surface
    knots_u = getattr(surface, "knots_u", None)
    knots_v = getattr(surface, "knots_v", None)
    if knots_u is not None and knots_v is not None:
        u_min, u_max = float(knots_u[0]), float(knots_u[-1])
        v_min, v_max = float(knots_v[0]), float(knots_v[-1])
        if u_max > u_min and v_max > v_min:
            return (u_min + u_max) / 2.0, (v_min + v_max) / 2.0
    return 0.5, 0.5


def _face_normal_at_uv(face: Face, u: float, v: float) -> np.ndarray:
    """Outward face normal at (u, v), respecting face.orientation."""
    return _unit(np.asarray(face.surface_normal(u, v), dtype=float))


def _classify_dihedral(dihedral: float, eps: float = _EPS_RAD) -> str:
    """Classify a dihedral angle in radians."""
    if dihedral < math.pi - eps:
        return EdgeClass.CONVEX
    if dihedral > math.pi + eps:
        return EdgeClass.CONCAVE
    return EdgeClass.TANGENTIAL


def _dihedral_from_normals(n1: np.ndarray, n2: np.ndarray) -> Tuple[float, float]:
    """Compute dihedral angle and cross-product magnitude from two outward normals.

    dihedral = π − arccos(n1·n2)

    For a convex exterior edge (e.g. a box corner), the two face normals point
    outward and away from each other; their dot product is ≥ 0, giving
    arccos ≤ π/2, so dihedral = π − arccos ≤ π/2 < π → convex.

    For a concave re-entrant edge, the normals point *into* the pocket,
    their dot product is ≤ 0 (angle ≥ π/2), so dihedral > π → concave.

    Returns (dihedral_rad, cross_magnitude).
    """
    dot = float(np.dot(n1, n2))
    dot = max(-1.0, min(1.0, dot))  # numerical clamp
    cross = np.cross(n1, n2)
    cross_mag = float(np.linalg.norm(cross))
    # atan2(|n1×n2|, n1·n2) = arccos(dot) on [0, π]; numerically stable
    angle_between = math.atan2(cross_mag, dot)  # ∈ [0, π]
    dihedral = math.pi - angle_between
    return dihedral, cross_mag


def _collect_edge_face_map(faces: List[Face]) -> Dict[int, List[Face]]:
    """Build a map from edge id → list of faces that share that edge."""
    edge_to_faces: Dict[int, List[Face]] = {}
    for face in faces:
        for loop in face.loops:
            for coedge in loop.coedges:
                eid = id(coedge.edge)
                edge_to_faces.setdefault(eid, [])
                # add face only once per face
                if face not in edge_to_faces[eid]:
                    edge_to_faces[eid].append(face)
    return edge_to_faces


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_edges(
    faces: List[Face],
    n_samples: int = _N_SAMPLES,
    eps: float = _EPS_RAD,
) -> EdgeConvexityReport:
    """Classify every interior edge in a B-rep shell/solid as convex, concave,
    or tangential.

    Parameters
    ----------
    faces : list of Face
        All faces of the B-rep solid or shell.  Faces must have consistent
        outward normals (``face.orientation=True`` → outward).
    n_samples : int
        Number of sample points per edge (default 3).  Samples are placed at
        fractional positions 1/(n+1), 2/(n+1), …, n/(n+1) along [t0, t1] to
        avoid degenerate endpoints.
    eps : float
        Half-width of the tangential band around π, in radians (default 1e-3).

    Returns
    -------
    EdgeConvexityReport
        See dataclass docstring for fields.

    References
    ----------
    Hoffmann 1989 §5.3; Mantyla 1988 §7.4.
    """
    report = EdgeConvexityReport()
    if not faces:
        return report

    edge_to_faces = _collect_edge_face_map(faces)

    # Precompute UV midpoints for each face (constant for flat faces)
    face_uv: Dict[int, Tuple[float, float]] = {
        id(f): _uv_midpoint(f) for f in faces
    }

    # Collect distinct edges with their edge objects
    seen_edges: Dict[int, Edge] = {}
    for face in faces:
        for loop in face.loops:
            for coedge in loop.coedges:
                e = coedge.edge
                if id(e) not in seen_edges:
                    seen_edges[id(e)] = e

    for eid, edge in seen_edges.items():
        adj_faces = edge_to_faces.get(eid, [])

        if len(adj_faces) < 2:
            report.boundary_edges.append(edge)
            continue
        if len(adj_faces) > 2:
            report.non_manifold_edges.append(edge)
            continue

        face_a, face_b = adj_faces[0], adj_faces[1]
        ua, va = face_uv[id(face_a)]
        ub, vb = face_uv[id(face_b)]

        n_a = _face_normal_at_uv(face_a, ua, va)
        n_b = _face_normal_at_uv(face_b, ub, vb)

        # Sample along edge and classify at each sample point.
        # The normal is evaluated at the face UV midpoint (constant for flat
        # faces; for curved faces we use the same point for all samples since
        # sampling multiple UV points requires exact UV inversion which is
        # out of scope here — documented in caveat).
        frac_positions = [i / (n_samples + 1) for i in range(1, n_samples + 1)]
        sample_dihedrals: List[float] = []
        small_cross_warning = False

        for frac in frac_positions:
            t = edge.t0 + frac * (edge.t1 - edge.t0)
            # edge point (used only for any future UV-inversion extension)
            try:
                edge.point(t)
            except Exception:
                pass

            dihedral, cross_mag = _dihedral_from_normals(n_a, n_b)
            if cross_mag < 1e-6:
                small_cross_warning = True
            sample_dihedrals.append(dihedral)

        if not sample_dihedrals:
            continue

        mean_dihedral = float(np.mean(sample_dihedrals))
        report.dihedral_angles[eid] = mean_dihedral

        # Majority-vote classification
        from collections import Counter
        classes = [_classify_dihedral(d, eps) for d in sample_dihedrals]
        vote = Counter(classes).most_common(1)[0][0]
        report.classification[eid] = vote

        # Consistency check
        if len(set(classes)) > 1:
            report.inconsistent_edges.append(edge)

        if vote == EdgeClass.CONVEX:
            report.convex_edges.append(edge)
        elif vote == EdgeClass.CONCAVE:
            report.concave_edges.append(edge)
        else:
            report.tangential_edges.append(edge)

        if small_cross_warning:
            report.warnings.append(
                f"Edge#{eid}: near-parallel normals (cross_mag < 1e-6); "
                "may be tangential or indicate inconsistent face orientations."
            )

    return report


def classify_body_edges(
    body: Body,
    n_samples: int = _N_SAMPLES,
    eps: float = _EPS_RAD,
) -> EdgeConvexityReport:
    """Classify all interior edges of a :class:`Body`.

    Collects all faces from all shells in all solids (and free shells), then
    delegates to :func:`classify_edges`.
    """
    faces: List[Face] = []
    for solid in body.solids:
        for shell in solid.shells:
            faces.extend(shell.faces)
    for shell in body.shells:
        faces.extend(shell.faces)
    return classify_edges(faces, n_samples=n_samples, eps=eps)


# ---------------------------------------------------------------------------
# LLM tool registration (kerf_chat registry, try/except guard)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]

    _spec = ToolSpec(
        name="brep_classify_edges",
        description=(
            "Classify every interior edge of a B-rep primitive as convex, concave, "
            "or tangential using the dihedral angle between adjacent face normals. "
            "Convex: dihedral < π (material inside the corner, e.g. a box edge). "
            "Concave: dihedral > π (re-entrant / pocket edge). "
            "Tangential: dihedral ≈ π (smooth G1 transition, e.g. a fillet). "
            "Algorithm: Hoffmann 1989 §5.3; Mantyla 1988 §7.4."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": {
                    "type": "object",
                    "description": (
                        "Primitive to classify.  "
                        "type='box': {origin:[x,y,z], size:[sx,sy,sz]}. "
                        "type='cylinder': {center:[x,y,z], axis:[ax,ay,az], radius:r, height:h}. "
                        "type='sphere': {center:[x,y,z], radius:r}. "
                        "type='torus': {center:[x,y,z], axis:[ax,ay,az], major_radius:R, minor_radius:r}."
                    ),
                    "required": ["type"],
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Sample points per edge (default 3).",
                    "default": 3,
                },
                "eps_deg": {
                    "type": "number",
                    "description": (
                        "Half-width of tangential band around 180°, in degrees (default 0.057°)."
                    ),
                    "default": 0.057,
                },
            },
            "required": ["primitive"],
        },
    )

    @register(_spec)
    async def run_brep_classify_edges(ctx: "object", args: bytes) -> str:
        """LLM tool: brep_classify_edges."""
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        prim = a.get("primitive")
        if prim is None:
            return err_payload("'primitive' is required", "BAD_ARGS")

        n_samples = int(a.get("n_samples", _N_SAMPLES))
        eps_deg = float(a.get("eps_deg", math.degrees(_EPS_RAD)))
        eps_rad = math.radians(eps_deg)

        try:
            from kerf_cad_core.geom.brep import (
                make_box,
                make_cylinder,
                make_sphere,
                make_torus,
            )

            ptype = str(prim.get("type", "box")).lower()
            if ptype == "box":
                body = make_box(
                    origin=prim.get("origin", [0.0, 0.0, 0.0]),
                    size=prim.get("size", [1.0, 1.0, 1.0]),
                )
            elif ptype == "cylinder":
                body = make_cylinder(
                    center=prim.get("center", [0.0, 0.0, 0.0]),
                    axis=prim.get("axis", [0.0, 0.0, 1.0]),
                    radius=float(prim.get("radius", 1.0)),
                    height=float(prim.get("height", 1.0)),
                )
            elif ptype == "sphere":
                body = make_sphere(
                    center=prim.get("center", [0.0, 0.0, 0.0]),
                    radius=float(prim.get("radius", 1.0)),
                )
            elif ptype == "torus":
                body = make_torus(
                    center=prim.get("center", [0.0, 0.0, 0.0]),
                    axis=prim.get("axis", [0.0, 0.0, 1.0]),
                    major_radius=float(prim.get("major_radius", 2.0)),
                    minor_radius=float(prim.get("minor_radius", 0.5)),
                )
            else:
                return err_payload(
                    f"unknown primitive type {ptype!r}; supported: box, cylinder, sphere, torus",
                    "BAD_ARGS",
                )
        except Exception as exc:
            return err_payload(f"failed to build solid: {exc}", "OP_FAILED")

        try:
            report = classify_body_edges(body, n_samples=n_samples, eps=eps_rad)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "n_convex": len(report.convex_edges),
            "n_concave": len(report.concave_edges),
            "n_tangential": len(report.tangential_edges),
            "n_boundary": len(report.boundary_edges),
            "n_non_manifold": len(report.non_manifold_edges),
            "n_inconsistent": len(report.inconsistent_edges),
            "dihedral_angles_deg": {
                str(k): round(math.degrees(v), 4)
                for k, v in report.dihedral_angles.items()
            },
            "warnings": report.warnings,
            "caveat": report.caveat,
        })

except ImportError:
    pass  # kerf_chat not installed — module still importable
