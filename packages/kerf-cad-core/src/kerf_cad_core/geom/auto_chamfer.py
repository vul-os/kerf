"""Auto-chamfer recommendation for B-rep bodies.

Identifies convex edges that benefit from chamfering per design-for-manufacturing
standards (SME Tool & Manufacturing Engineers Handbook Vol 6 §3; ISO 13715).

Public API
----------
recommend_chamfers(body, safety_chamfer_mm=0.5, manufacturing_chamfer_mm=1.0)
    → ChamferRecommendationResult
        Per-edge classification and recommended widths.

apply_chamfer_recommendations(body, recommendations) → Body
    Apply all recommended chamfers to a body, returning the chamfered result.

chamfer_size_by_design_intent(edge_info, intent='auto') → float
    Compute appropriate chamfer width for a given edge and design intent.

Edge classification scheme
--------------------------
All classifications operate on the **dihedral angle** measured as the interior
solid angle (i.e. the angle *inside* the material), using outward face normals:

    dihedral_interior = π − acos(n1 · n2)

where n1, n2 are the outward normals of the two faces sharing the edge.  A
convex edge (material corner visible from outside) has interior dihedral < π,
i.e. n1 · n2 > −1.  A concave (re-entrant) edge has interior dihedral > π.

Classification labels (per ISO 13715 intent + SME Handbook §3 guidance):

  'safety_chamfer'       dihedral_interior ≥ 80°  AND  edge is near the
                         convex-hull boundary (handling region heuristic).
                         Recommended for all handled/touched parts where a
                         sharp corner poses injury risk.  Typical size: 0.5mm.

  'manufacturing_chamfer' dihedral_interior ≥ 90°  AND  corner is geometrically
                         significant (perpendicular junction).  Aids chip
                         clearance and tool entry; required by many shop
                         standards.  Typical size: 1.0mm.

  'cosmetic_chamfer'     Convex edge with dihedral_interior < 90°  (acute
                         material corner — already sharp but not right-angle).
                         Optional cosmetic break, no structural requirement.

  'no_chamfer'           Re-entrant (concave) edge, boundary edge (< 2 faces),
                         non-linear edge, or dihedral below detection threshold.

Note: on a box (12 edges, all 90° interior dihedrals, all on the convex hull),
every edge is classified 'safety_chamfer' because all satisfy the ≥ 80° threshold
and all lie on the convex-hull boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body, Edge, Face, Line3, Plane
from kerf_cad_core.geom.chamfer import chamfer_edge


__all__ = [
    "ChamferKind",
    "EdgeChamferInfo",
    "ChamferRecommendationResult",
    "recommend_chamfers",
    "apply_chamfer_recommendations",
    "chamfer_size_by_design_intent",
]

# ---------------------------------------------------------------------------
# Constants (per SME Handbook Vol 6 §3 / ISO 13715)
# ---------------------------------------------------------------------------

_DIHEDRAL_SAFETY_DEG: float = 80.0       # deg — threshold for safety chamfer
_DIHEDRAL_MANUFACTURING_DEG: float = 90.0  # deg — threshold for manufacturing chamfer
_MIN_EDGE_LENGTH: float = 1e-4           # m — ignore degenerate edges

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

ChamferKind = str  # 'safety_chamfer' | 'manufacturing_chamfer' | 'cosmetic_chamfer' | 'no_chamfer'


@dataclass
class EdgeChamferInfo:
    """Recommendation record for one edge.

    Attributes
    ----------
    edge : Edge
        Reference to the B-rep edge.
    kind : ChamferKind
        Classification label.
    dihedral_deg : float
        Interior dihedral angle in degrees (NaN for non-manifold/boundary edges).
    is_convex : bool
        True when the edge protrudes outward (material corner).
    is_on_hull_boundary : bool
        True when the edge midpoint lies on or near the convex-hull surface
        (handling-region heuristic).
    recommended_width : float
        Recommended chamfer width in mm (0.0 when kind == 'no_chamfer').
    edge_length : float
        Approximate edge length.
    """

    edge: Edge
    kind: ChamferKind
    dihedral_deg: float
    is_convex: bool
    is_on_hull_boundary: bool
    recommended_width: float
    edge_length: float


@dataclass
class ChamferRecommendationResult:
    """Result of recommend_chamfers().

    Attributes
    ----------
    per_edge : list[EdgeChamferInfo]
        One record per edge in the body.
    total_recommended_edges : int
        Number of edges with kind != 'no_chamfer'.
    recommended_widths : dict[str, float]
        Mapping kind → default recommended width (mm).
    design_intent_notes : list[str]
        Human-readable notes explaining the classification decisions.
    """

    per_edge: List[EdgeChamferInfo] = field(default_factory=list)
    total_recommended_edges: int = 0
    recommended_widths: Dict[str, float] = field(default_factory=dict)
    design_intent_notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> Optional[np.ndarray]:
    """Normalise vector; return None for degenerate zero-length vectors."""
    n = float(np.linalg.norm(v))
    if n < 1e-14:
        return None
    return v / n


def _faces_of_edge(body: Body, edge: Edge) -> List[Face]:
    """Return all faces sharing *edge* in *body*."""
    result: List[Face] = []
    for face in body.all_faces():
        for lp in face.loops:
            for ce in lp.coedges:
                if ce.edge is edge:
                    result.append(face)
                    break
            else:
                continue
            break
    return result


def _outward_normal_at_edge(face: Face) -> Optional[np.ndarray]:
    """Return the outward face normal for a planar face."""
    if not isinstance(face.surface, Plane):
        # For non-planar faces sample at (0.5, 0.5)
        try:
            n = np.asarray(face.surface.normal(0.5, 0.5), dtype=float)
        except Exception:
            return None
    else:
        plane: Plane = face.surface
        n = np.cross(plane.x_axis, plane.y_axis)

    u = _unit(n)
    if u is None:
        return None
    # Respect face orientation
    return u if face.orientation else -u


def _dihedral_angle_deg(n1: np.ndarray, n2: np.ndarray) -> float:
    """Interior dihedral angle from two outward face normals.

    The interior dihedral is the angle *inside* the material.
    For a convex edge (box corner), interior dihedral = 90° and
    n1 · n2 = 0 (faces are perpendicular, normals diverge).

    Formula:
        cos(exterior_angle) = n1 · n2
        interior_dihedral   = 180° - exterior_angle   (for convex edge)

    Equivalently:
        interior_dihedral = acos(−n1 · n2)

    So a cube edge has interior_dihedral = acos(0) = 90°.
    A sharper corner has interior_dihedral < 90°.
    A re-entrant edge has interior_dihedral > 180° (but we clamp to [0, 180]).
    """
    dot = float(np.clip(np.dot(n1, n2), -1.0, 1.0))
    # interior_dihedral = 180 - exterior; exterior = acos(dot)
    exterior_deg = math.degrees(math.acos(dot))
    interior_deg = 180.0 - exterior_deg
    return interior_deg


def _is_convex_edge(n1: np.ndarray, n2: np.ndarray) -> bool:
    """Return True when the edge is convex (outward-protruding corner).

    For a convex edge the outward normals of the two faces point *away*
    from each other: their dot product is > −1 and typically near 0 for a
    right-angle.  A concave (re-entrant) edge has normals pointing toward
    each other (dot product → +1 at a 180° reflex).

    Heuristic: edge is convex when the interior dihedral < 180°,
    i.e. the exterior angle between the faces (measured *outside* the
    material) is > 0°.  Equivalently: dot(n1, n2) < 1.0 (not co-planar and
    not reflex).

    Practically: interior_dihedral < 180° ↔ edge is convex.
    We threshold at 179° to exclude near-planar edges.
    """
    interior = _dihedral_angle_deg(n1, n2)
    return interior < 179.0


def _convex_hull_vertices(pts: np.ndarray) -> np.ndarray:
    """Compute 3-D convex hull and return hull vertex indices.

    Falls back to returning all points when fewer than 4 (degenerate hull).
    Uses a simple QHull approximation via the gift-wrapping heuristic on the
    bounding box — exact enough for the on-hull heuristic.
    """
    try:
        from scipy.spatial import ConvexHull  # type: ignore[import]
        hull = ConvexHull(pts)
        return pts[np.unique(hull.simplices.flatten())]
    except ImportError:
        pass
    except Exception:
        pass
    # Fallback: approximate hull as the bounding-box extreme points
    extremes = []
    for axis in range(3):
        extremes.append(pts[np.argmin(pts[:, axis])])
        extremes.append(pts[np.argmax(pts[:, axis])])
    return np.array(extremes)


def _is_on_convex_hull(
    edge_mid: np.ndarray,
    all_vertices: np.ndarray,
    tol: float = 1e-3,
) -> bool:
    """Return True when *edge_mid* lies on or near the convex hull surface.

    Heuristic: compute the convex hull of all body vertices, then check
    whether *edge_mid* is within *tol* of the hull surface (i.e. its
    distance to the hull is < tol).  Interior points have larger distances.

    Falls back to True (conservative: always recommend chamfer) when the
    convex hull computation fails or when scipy is unavailable.
    """
    if len(all_vertices) < 4:
        return True  # degenerate body — assume on boundary

    try:
        from scipy.spatial import ConvexHull, Delaunay  # type: ignore[import]
        hull = ConvexHull(all_vertices)
        # Distance from point to each hull facet (signed: negative = inside)
        # A point on the hull has distance ≈ 0 to at least one facet.
        min_dist = float("inf")
        for eq in hull.equations:
            normal_h = eq[:3]
            offset = eq[3]
            d = float(np.dot(normal_h, edge_mid) + offset)
            min_dist = min(min_dist, abs(d))
        return min_dist < tol
    except ImportError:
        return True  # scipy absent — conservative: assume on hull
    except Exception:
        return True  # QHull failure on degenerate shapes


# ---------------------------------------------------------------------------
# chamfer_size_by_design_intent
# ---------------------------------------------------------------------------


def chamfer_size_by_design_intent(
    edge_info: EdgeChamferInfo,
    intent: str = "auto",
) -> float:
    """Compute chamfer width (mm) for *edge_info* given *intent*.

    Parameters
    ----------
    edge_info : EdgeChamferInfo
        Classification record for the edge.
    intent : str
        One of ``'safety'``, ``'manufacturing'``, ``'aesthetic'``,
        ``'auto'`` (default).  ``'auto'`` selects based on the edge's
        classified kind.

    Returns
    -------
    float
        Recommended chamfer width in mm.  0.0 for 'no_chamfer' edges.

    Design rules (SME Handbook Vol 6 §3)
    -------------------------------------
    * Safety chamfer on handled parts: 0.5 mm × 45° (C0.5)
    * Manufacturing chamfer at machine entries: 1.0 mm × 45° (C1.0)
    * Cosmetic/aesthetic break edge: 0.3 mm × 45°
    * No chamfer: 0.0
    """
    if edge_info.kind == "no_chamfer":
        return 0.0

    resolved_intent = intent
    if intent == "auto":
        resolved_intent = edge_info.kind  # use the classified kind directly

    if resolved_intent in ("safety", "safety_chamfer"):
        return 0.5
    if resolved_intent in ("manufacturing", "manufacturing_chamfer"):
        return 1.0
    if resolved_intent in ("aesthetic", "cosmetic", "cosmetic_chamfer"):
        return 0.3

    # Unknown intent: fall back on classified kind
    return {
        "safety_chamfer": 0.5,
        "manufacturing_chamfer": 1.0,
        "cosmetic_chamfer": 0.3,
    }.get(edge_info.kind, 0.0)


# ---------------------------------------------------------------------------
# recommend_chamfers
# ---------------------------------------------------------------------------


def recommend_chamfers(
    body: Body,
    safety_chamfer_mm: float = 0.5,
    manufacturing_chamfer_mm: float = 1.0,
) -> ChamferRecommendationResult:
    """Classify every edge of *body* for chamfer recommendation.

    Parameters
    ----------
    body : Body
        A ``validate_body``-clean B-rep body.
    safety_chamfer_mm : float
        Override the default safety chamfer width (mm).
    manufacturing_chamfer_mm : float
        Override the default manufacturing chamfer width (mm).

    Returns
    -------
    ChamferRecommendationResult
        Per-edge classification, total recommended count, width map, and
        design-intent notes.

    Algorithm
    ---------
    1. Collect all body vertices for the convex-hull boundary heuristic.
    2. For each edge:
       a. Find all faces sharing the edge.
       b. If not exactly 2 faces: classify 'no_chamfer' (boundary / non-manifold).
       c. Compute outward normals for both faces.
       d. Compute interior dihedral angle.
       e. Classify:
          - interior < 180° AND on hull AND ≥ 80°  → safety_chamfer
          - interior < 180° AND on hull AND ≥ 90°  → manufacturing_chamfer
            (the 80°–90° band gives safety only, not manufacturing)
          - interior < 180° AND < 80°             → cosmetic_chamfer
          - else                                  → no_chamfer

    Note: 'safety_chamfer' takes precedence over 'manufacturing_chamfer' when
    both thresholds are met (the safety label conveys the stronger requirement).
    An edge ≥ 90° on the hull is classified 'safety_chamfer' (not
    'manufacturing_chamfer') because it satisfies both criteria and the safety
    requirement is more important per SME §3.2.
    """
    per_edge: List[EdgeChamferInfo] = []

    # Collect all vertex positions for convex-hull heuristic
    verts = body.all_vertices()
    if verts:
        all_vertex_pts = np.array([v.point for v in verts], dtype=float)
    else:
        all_vertex_pts = np.zeros((0, 3))

    cosmetic_width = 0.3  # mm

    recommended_widths = {
        "safety_chamfer": safety_chamfer_mm,
        "manufacturing_chamfer": manufacturing_chamfer_mm,
        "cosmetic_chamfer": cosmetic_width,
        "no_chamfer": 0.0,
    }

    notes: List[str] = [
        "ISO 13715 / SME Handbook Vol 6 §3 classification applied.",
        f"Safety chamfer threshold: {_DIHEDRAL_SAFETY_DEG}° interior dihedral, width={safety_chamfer_mm}mm.",
        f"Manufacturing chamfer threshold: {_DIHEDRAL_MANUFACTURING_DEG}° interior dihedral, width={manufacturing_chamfer_mm}mm.",
        "Convex-hull boundary heuristic used for handling-region classification.",
        "Only straight-line (Line3) edges with exactly 2 planar faces are actionable; others: no_chamfer.",
    ]

    edges = body.all_edges()

    for edge in edges:
        # Edge length filter — skip degenerate edges
        edge_length = edge.length()
        if edge_length < _MIN_EDGE_LENGTH:
            per_edge.append(EdgeChamferInfo(
                edge=edge,
                kind="no_chamfer",
                dihedral_deg=float("nan"),
                is_convex=False,
                is_on_hull_boundary=False,
                recommended_width=0.0,
                edge_length=edge_length,
            ))
            continue

        # Find adjacent faces
        adj_faces = _faces_of_edge(body, edge)
        if len(adj_faces) != 2:
            per_edge.append(EdgeChamferInfo(
                edge=edge,
                kind="no_chamfer",
                dihedral_deg=float("nan"),
                is_convex=False,
                is_on_hull_boundary=False,
                recommended_width=0.0,
                edge_length=edge_length,
            ))
            continue

        face_a, face_b = adj_faces[0], adj_faces[1]

        # Outward normals
        n_a = _outward_normal_at_edge(face_a)
        n_b = _outward_normal_at_edge(face_b)
        if n_a is None or n_b is None:
            per_edge.append(EdgeChamferInfo(
                edge=edge,
                kind="no_chamfer",
                dihedral_deg=float("nan"),
                is_convex=False,
                is_on_hull_boundary=False,
                recommended_width=0.0,
                edge_length=edge_length,
            ))
            continue

        dihedral_deg = _dihedral_angle_deg(n_a, n_b)
        is_convex = _is_convex_edge(n_a, n_b)

        # On-hull heuristic: check edge midpoint
        if isinstance(edge.curve, Line3):
            edge_mid = 0.5 * (edge.curve.p0 + edge.curve.p1)
        else:
            edge_mid = 0.5 * (edge.v_start.point + edge.v_end.point)

        is_on_hull = _is_on_convex_hull(edge_mid, all_vertex_pts)

        # Classification
        if not is_convex:
            kind: ChamferKind = "no_chamfer"
            width = 0.0
        elif dihedral_deg >= _DIHEDRAL_SAFETY_DEG and is_on_hull:
            # ≥ 80° on hull → safety chamfer (covers both 80-90 and ≥90 bands)
            kind = "safety_chamfer"
            width = safety_chamfer_mm
        elif dihedral_deg >= _DIHEDRAL_MANUFACTURING_DEG:
            # ≥ 90° not on hull boundary (interior corner of complex body)
            kind = "manufacturing_chamfer"
            width = manufacturing_chamfer_mm
        elif is_convex:
            # convex but < 80° or off hull
            kind = "cosmetic_chamfer"
            width = cosmetic_width
        else:
            kind = "no_chamfer"
            width = 0.0

        per_edge.append(EdgeChamferInfo(
            edge=edge,
            kind=kind,
            dihedral_deg=dihedral_deg,
            is_convex=is_convex,
            is_on_hull_boundary=is_on_hull,
            recommended_width=width,
            edge_length=edge_length,
        ))

    total_recommended = sum(
        1 for e in per_edge if e.kind != "no_chamfer"
    )

    return ChamferRecommendationResult(
        per_edge=per_edge,
        total_recommended_edges=total_recommended,
        recommended_widths=recommended_widths,
        design_intent_notes=notes,
    )


# ---------------------------------------------------------------------------
# apply_chamfer_recommendations
# ---------------------------------------------------------------------------


def apply_chamfer_recommendations(
    body: Body,
    recommendations: ChamferRecommendationResult,
    tol: float = 1e-6,
) -> Body:
    """Apply all recommended chamfers to *body*.

    Iterates over ``recommendations.per_edge`` in the order returned by
    ``recommend_chamfers`` and applies each chamfer sequentially using
    :func:`~kerf_cad_core.geom.chamfer.chamfer_edge`.

    Only edges with ``kind != 'no_chamfer'`` and ``recommended_width > 0``
    are chamfered.  The function skips edges that are no longer present in
    the updated body (they may have been consumed by a prior chamfer).

    Parameters
    ----------
    body : Body
        A ``validate_body``-clean B-rep body — the *same* body that was
        passed to ``recommend_chamfers``.
    recommendations : ChamferRecommendationResult
        Result from ``recommend_chamfers(body, ...)``.
    tol : float
        Sewing tolerance passed to the underlying ``chamfer_edge`` calls.

    Returns
    -------
    Body
        New ``validate_body``-clean body with all recommended chamfers applied.

    Notes
    -----
    * Sequential application: each chamfer modifies the body topology.
      Edge references from ``recommendations`` become stale after the first
      chamfer.  Edges are matched by their *midpoint position* in the
      updated body rather than by identity.
    * Chamfer failures (width exceeds face, non-planar face, etc.) are
      silently skipped to maintain robustness.
    """
    from kerf_cad_core.geom.chamfer import ChamferError

    current_body = body

    for info in recommendations.per_edge:
        if info.kind == "no_chamfer" or info.recommended_width <= 0.0:
            continue

        width = info.recommended_width

        # Find the corresponding edge in the current body by midpoint proximity
        if isinstance(info.edge.curve, Line3):
            target_mid = 0.5 * (info.edge.curve.p0 + info.edge.curve.p1)
        else:
            target_mid = 0.5 * (info.edge.v_start.point + info.edge.v_end.point)

        best_edge: Optional[Edge] = None
        best_dist = float("inf")
        for e in current_body.all_edges():
            if isinstance(e.curve, Line3):
                mid = 0.5 * (e.curve.p0 + e.curve.p1)
            else:
                mid = 0.5 * (e.v_start.point + e.v_end.point)
            d = float(np.linalg.norm(mid - target_mid))
            if d < best_dist:
                best_dist = d
                best_edge = e

        if best_edge is None or best_dist > tol * 1000:
            continue  # edge no longer exists in this body

        try:
            current_body = chamfer_edge(current_body, best_edge, width, tol=tol)
        except (ChamferError, Exception):
            # Skip edges that can't be chamfered (non-planar, width exceeds, etc.)
            continue

    return current_body


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors surface_fillet.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ── brep_recommend_chamfers ────────────────────────────────────────────

    _recommend_spec = ToolSpec(
        name="brep_recommend_chamfers",
        description=(
            "Analyse a B-rep box body and classify every edge for chamfer "
            "recommendation per ISO 13715 / SME Handbook Vol 6 §3 design-for-"
            "manufacturing rules.\n"
            "\n"
            "Provide the box as corner [x,y,z] and extents dx, dy, dz.  "
            "Optional safety_chamfer_mm (default 0.5) and "
            "manufacturing_chamfer_mm (default 1.0) override the widths.\n"
            "\n"
            "Returns:\n"
            "  ok                     : bool\n"
            "  total_recommended_edges: int\n"
            "  recommended_widths     : {kind: mm}\n"
            "  design_intent_notes    : [str]\n"
            "  per_edge               : [{kind, dihedral_deg, is_convex,\n"
            "                            is_on_hull_boundary, recommended_width,\n"
            "                            edge_length}]\n"
            "\n"
            "Edge kinds: 'safety_chamfer', 'manufacturing_chamfer', "
            "'cosmetic_chamfer', 'no_chamfer'.\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "corner": {
                    "type": "array",
                    "description": "Box corner [x, y, z].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "dx": {"type": "number", "description": "Box extent in X (> 0)."},
                "dy": {"type": "number", "description": "Box extent in Y (> 0)."},
                "dz": {"type": "number", "description": "Box extent in Z (> 0)."},
                "safety_chamfer_mm": {
                    "type": "number",
                    "description": "Safety chamfer width in mm (default 0.5).",
                },
                "manufacturing_chamfer_mm": {
                    "type": "number",
                    "description": "Manufacturing chamfer width in mm (default 1.0).",
                },
            },
            "required": ["corner", "dx", "dy", "dz"],
        },
    )

    @register(_recommend_spec)
    async def run_brep_recommend_chamfers(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        corner = a.get("corner")
        dx = a.get("dx")
        dy = a.get("dy")
        dz = a.get("dz")
        if corner is None or dx is None or dy is None or dz is None:
            return err_payload("corner, dx, dy, dz are required", "BAD_ARGS")
        if not isinstance(corner, (list, tuple)) or len(corner) != 3:
            return err_payload("corner must be [x, y, z]", "BAD_ARGS")
        if not all(isinstance(v, (int, float)) and v > 0 for v in [dx, dy, dz]):
            return err_payload("dx, dy, dz must be positive numbers", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.brep_build import box_to_body
            body = box_to_body(
                [float(corner[0]), float(corner[1]), float(corner[2])],
                float(dx), float(dy), float(dz),
            )
        except Exception as exc:
            return err_payload(f"box construction failed: {exc}", "OP_FAILED")

        safety_mm = float(a.get("safety_chamfer_mm", 0.5))
        manuf_mm = float(a.get("manufacturing_chamfer_mm", 1.0))

        result = recommend_chamfers(body, safety_chamfer_mm=safety_mm,
                                    manufacturing_chamfer_mm=manuf_mm)

        return ok_payload({
            "total_recommended_edges": result.total_recommended_edges,
            "recommended_widths": result.recommended_widths,
            "design_intent_notes": result.design_intent_notes,
            "per_edge": [
                {
                    "kind": info.kind,
                    "dihedral_deg": round(info.dihedral_deg, 4)
                        if not math.isnan(info.dihedral_deg) else None,
                    "is_convex": info.is_convex,
                    "is_on_hull_boundary": info.is_on_hull_boundary,
                    "recommended_width": info.recommended_width,
                    "edge_length": round(info.edge_length, 6),
                }
                for info in result.per_edge
            ],
        })

    # ── brep_apply_chamfer_recommendations ────────────────────────────────

    _apply_spec = ToolSpec(
        name="brep_apply_chamfer_recommendations",
        description=(
            "Build a box, run auto-chamfer recommendation, and apply all "
            "recommended chamfers, returning the resulting body topology.\n"
            "\n"
            "Provide the box as corner [x,y,z] and extents dx, dy, dz.  "
            "Optional safety_chamfer_mm (default 0.5) and "
            "manufacturing_chamfer_mm (default 1.0) control widths.\n"
            "\n"
            "Returns:\n"
            "  ok                      : bool\n"
            "  original_euler          : {V, E, F}\n"
            "  result_euler            : {V, E, F}\n"
            "  chamfers_applied        : int  (number of chamfers successfully applied)\n"
            "  total_recommended_edges : int\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "corner": {
                    "type": "array",
                    "description": "Box corner [x, y, z].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "dx": {"type": "number", "description": "Box extent in X (> 0)."},
                "dy": {"type": "number", "description": "Box extent in Y (> 0)."},
                "dz": {"type": "number", "description": "Box extent in Z (> 0)."},
                "safety_chamfer_mm": {
                    "type": "number",
                    "description": "Safety chamfer width in mm (default 0.5).",
                },
                "manufacturing_chamfer_mm": {
                    "type": "number",
                    "description": "Manufacturing chamfer width in mm (default 1.0).",
                },
            },
            "required": ["corner", "dx", "dy", "dz"],
        },
    )

    @register(_apply_spec)
    async def run_brep_apply_chamfer_recommendations(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        corner = a.get("corner")
        dx = a.get("dx")
        dy = a.get("dy")
        dz = a.get("dz")
        if corner is None or dx is None or dy is None or dz is None:
            return err_payload("corner, dx, dy, dz are required", "BAD_ARGS")
        if not isinstance(corner, (list, tuple)) or len(corner) != 3:
            return err_payload("corner must be [x, y, z]", "BAD_ARGS")
        if not all(isinstance(v, (int, float)) and v > 0 for v in [dx, dy, dz]):
            return err_payload("dx, dy, dz must be positive numbers", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.brep_build import box_to_body
            body = box_to_body(
                [float(corner[0]), float(corner[1]), float(corner[2])],
                float(dx), float(dy), float(dz),
            )
        except Exception as exc:
            return err_payload(f"box construction failed: {exc}", "OP_FAILED")

        safety_mm = float(a.get("safety_chamfer_mm", 0.5))
        manuf_mm = float(a.get("manufacturing_chamfer_mm", 1.0))

        original_euler = body.euler_counts()
        recommendations = recommend_chamfers(body, safety_chamfer_mm=safety_mm,
                                             manufacturing_chamfer_mm=manuf_mm)

        result_body = apply_chamfer_recommendations(body, recommendations)
        result_euler = result_body.euler_counts()

        # Count how many chamfers were actually applied
        original_faces = original_euler.get("F", 0)
        result_faces = result_euler.get("F", 0)
        chamfers_applied = result_faces - original_faces  # each chamfer adds 1 face

        return ok_payload({
            "original_euler": original_euler,
            "result_euler": result_euler,
            "chamfers_applied": chamfers_applied,
            "total_recommended_edges": recommendations.total_recommended_edges,
        })
