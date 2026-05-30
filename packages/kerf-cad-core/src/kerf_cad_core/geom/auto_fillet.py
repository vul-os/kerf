"""GK-P auto_fillet — smart fillet recommendation engine.

Identifies edges in a B-rep ``Body`` where fillets are beneficial for:
  * **Stress concentration reduction** — interior (concave) corners per
    Peterson 1974 "Stress Concentration Factors", formula
    Kt = 1 + 2·sqrt(d/r) for a notch under tension.
  * **Ergonomics / visual quality** — exterior (convex) corners per
    Boothroyd-Dewhurst 2002 §6 (fillet sizing for casting/moulding).
  * **Manufacturing intent** — design_intent keyword tunes radius rules:
    - 'auto'           : heuristic per corner type
    - 'molded_plastic' : radius = wall_thickness / 2  (Boothroyd §6.5)
    - 'machined'       : radius = cutter_diameter / 2 (typically 0.5–3 mm)
    - 'cast'           : radius = wall_thickness       (BS 4500A practice)

Public API
----------
recommend_fillets(body, stress_relief_priority=True, design_intent='auto',
                  wall_thickness_hint=None, cutter_diameter_hint=None)
    -> FilletRecommendationResult

apply_fillet_recommendations(body, recommendations) -> Body

estimate_stress_reduction(edge, recommended_radius,
                          base_stress_concentration=3.0) -> float

LLM tools (registered when kerf_chat is available):
    brep_recommend_fillets
    brep_apply_fillet_recommendations

References
----------
Peterson, R.E. (1974). Stress Concentration Factors. Wiley.
Boothroyd, G. & Dewhurst, P. (2002). Product Design for Manufacture and
    Assembly, 2nd ed. CRC Press.  §6 — plastic-part design guidelines.
ISO 6892-1:2019 — Metallic materials — Tensile testing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Edge,
    Face,
    Line3,
    validate_body,
)
from kerf_cad_core.geom.fillet_solid import (
    fillet_solid_edge,
    _find_incident_faces,
)


__all__ = [
    "recommend_fillets",
    "apply_fillet_recommendations",
    "estimate_stress_reduction",
    "FilletRecommendationResult",
    "EdgeRecommendation",
]

# ---------------------------------------------------------------------------
# Design-intent radius defaults (mm)
# ---------------------------------------------------------------------------

_EXTERIOR_RADIUS_DEFAULT = 1.0    # mm — hand-feel / aesthetics baseline
_EXTERIOR_RADIUS_MIN = 0.5
_EXTERIOR_RADIUS_MAX = 2.0
_PETERSON_ALPHA = 0.1             # radius = 0.1 × min face dimension (Peterson rule)
_MACHINED_DEFAULT_CUTTER_DIAM = 6.0  # mm — conservative end-mill


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EdgeRecommendation:
    """Per-edge fillet recommendation.

    Attributes
    ----------
    edge_index : int
        Index of the edge in ``body.all_edges()``.
    corner_type : str
        ``'interior_corner'`` (concave dihedral — stress relief priority)
        or ``'exterior_corner'`` (convex dihedral — ergonomics/aesthetics).
    recommended_radius : float
        Radius in millimetres (model units).
    priority : str
        ``'high'`` for stress-relief edges, ``'low'`` for aesthetic edges.
    rationale : str
        Human-readable explanation citing the applicable standard.
    estimated_kt_before : float
        Stress concentration factor Kt *before* fillet (bare sharp corner
        approximated as ``base_stress_concentration``).
    estimated_kt_after : float
        Stress concentration factor Kt *after* applying the recommended
        fillet per Peterson 1974 Kt = 1 + 2·sqrt(d/r).  Equal to 1.0 for
        exterior corners (stress-concentration formula does not apply to
        convex dihedral in isolation).
    applicable : bool
        False if the fillet_solid machinery does not support this edge
        (e.g. circular arc curve, non-planar support faces).
    """

    edge_index: int
    corner_type: str
    recommended_radius: float
    priority: str
    rationale: str
    estimated_kt_before: float = 3.0
    estimated_kt_after: float = 1.0
    applicable: bool = True


@dataclass
class FilletRecommendationResult:
    """Aggregate result returned by :func:`recommend_fillets`.

    Attributes
    ----------
    per_edge_recommendation : list[EdgeRecommendation]
        One entry per edge of the body (``applicable=False`` entries are
        edges the engine skipped — non-linear curves, etc.).
    total_recommended : int
        Count of edges with ``applicable=True``.
    stress_relief_count : int
        Count of interior-corner recommendations (high priority).
    aesthetic_count : int
        Count of exterior-corner recommendations (low priority).
    design_intent : str
        The design intent passed by the caller.
    """

    per_edge_recommendation: List[EdgeRecommendation] = field(
        default_factory=list
    )
    total_recommended: int = 0
    stress_relief_count: int = 0
    aesthetic_count: int = 0
    design_intent: str = "auto"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _dihedral_angle_and_type(
    face_a: Face, face_b: Face, edge: Edge
) -> tuple[float, str]:
    """Return (dihedral_angle_deg, corner_type).

    ``corner_type`` is ``'interior_corner'`` when the dihedral measured
    *inside the solid* is acute (< 180°, concave from outside) or
    ``'exterior_corner'`` when it is > 180° (convex from outside).

    For two planar faces the dihedral is measured by the dot product of
    their outward normals.  The convention here matches the B-rep
    orientation: a box has all convex (exterior) corners.

    ``Face.surface_normal(0.5, 0.5)`` returns the outward normal already
    accounting for face orientation, so we use that directly.

    Parameters
    ----------
    face_a, face_b : Face
        The two faces incident to ``edge``.
    edge : Edge
        The shared edge (unused; reserved for future curved-edge support).

    Returns
    -------
    (angle_deg, corner_type) where angle_deg is in [0, 180].
    """
    # Use surface_normal which already handles face orientation.
    n_a: np.ndarray = face_a.surface_normal(0.5, 0.5)
    n_b: np.ndarray = face_b.surface_normal(0.5, 0.5)

    # Angle between outward normals.
    cos_theta = float(np.clip(np.dot(_unit(n_a), _unit(n_b)), -1.0, 1.0))
    angle_deg = math.degrees(math.acos(cos_theta))

    # For a convex (exterior) corner the two outward normals point away
    # from each other (angle > 90°); for a concave (interior) corner they
    # point toward each other (angle < 90°).
    if angle_deg < 90.0:
        return (angle_deg, "interior_corner")
    return (angle_deg, "exterior_corner")


def _face_min_dimension(face: Face) -> float:
    """Return an estimate of the minimum dimension of a planar face.

    Computed as the shortest edge length in the face's outer loop.
    Fallback: 10 mm.
    """
    outer = face.outer_loop()
    if outer is None:
        return 10.0
    lengths = []
    for ce in outer.coedges:
        e = ce.edge
        if isinstance(e.curve, Line3):
            p0 = np.asarray(e.curve.p0, dtype=float)
            p1 = np.asarray(e.curve.p1, dtype=float)
            lengths.append(float(np.linalg.norm(p1 - p0)))
    return min(lengths) if lengths else 10.0


def _adjacent_face_min_dim(
    face_a: Face, face_b: Face
) -> float:
    """Return the minimum of the two faces' minimum dimensions."""
    return min(_face_min_dimension(face_a), _face_min_dimension(face_b))


def _edge_is_straight(edge: Edge) -> bool:
    return isinstance(edge.curve, Line3)


# ---------------------------------------------------------------------------
# Peterson Kt formula (1974)
# ---------------------------------------------------------------------------


def estimate_stress_reduction(
    edge: Edge,
    recommended_radius: float,
    base_stress_concentration: float = 3.0,
) -> float:
    """Estimate the post-fillet stress concentration factor Kt.

    Uses Peterson 1974 notch-sensitivity formula for a circular fillet
    under uniaxial tension:

        Kt = 1 + 2 · sqrt(d / r)

    where ``d`` is estimated as the edge length (as a proxy for the
    characteristic depth of the stress riser) and ``r`` is the fillet
    radius.

    For ``r <= 0`` or non-straight edges the function returns
    ``base_stress_concentration`` unchanged.

    Parameters
    ----------
    edge : Edge
        The B-rep edge being filleted.
    recommended_radius : float
        Fillet radius (model units, assumed mm).
    base_stress_concentration : float
        Kt before fillet (sharp corner); defaults to 3.0, a conservative
        value for a 90° notch under bending (Peterson Table 2.1).

    Returns
    -------
    kt_after : float
        The estimated Kt after applying the fillet.  Always >= 1.0.

    Notes
    -----
    The formula is strictly valid for a notch in a flat bar under tension.
    For 3-D interior corners the formula is conservative (over-estimates
    Kt).  For exterior (convex) corners Kt = 1 in practice; callers should
    check ``EdgeRecommendation.corner_type`` before interpreting this value.
    """
    if recommended_radius <= 0.0:
        return float(base_stress_concentration)
    if not isinstance(edge.curve, Line3):
        return float(base_stress_concentration)

    p0 = np.asarray(edge.curve.p0, dtype=float)
    p1 = np.asarray(edge.curve.p1, dtype=float)
    d = float(np.linalg.norm(p1 - p0))
    if d < 1e-12:
        return float(base_stress_concentration)

    kt = 1.0 + 2.0 * math.sqrt(d / recommended_radius)
    # Clamp: Kt must be >= 1 and should not exceed the un-filleted value.
    kt = min(kt, float(base_stress_concentration))
    return max(1.0, kt)


# ---------------------------------------------------------------------------
# Radius sizing rules (design intent)
# ---------------------------------------------------------------------------


def _radius_for_intent(
    corner_type: str,
    design_intent: str,
    adj_min_dim: float,
    wall_thickness_hint: Optional[float],
    cutter_diameter_hint: Optional[float],
) -> tuple[float, str]:
    """Return (radius_mm, rationale) for the given design intent and corner.

    Returns
    -------
    (radius, rationale_string)
    """
    wt = wall_thickness_hint if wall_thickness_hint and wall_thickness_hint > 0 else None
    cd = cutter_diameter_hint if cutter_diameter_hint and cutter_diameter_hint > 0 else None

    if corner_type == "interior_corner":
        # Peterson rule: r = 0.1 × adjacent_face_min_dim
        r_peterson = max(0.2, _PETERSON_ALPHA * adj_min_dim)

        if design_intent == "molded_plastic":
            if wt:
                r = wt / 2.0
                rationale = (
                    f"Molded-plastic interior corner: r = wall_thickness/2 = "
                    f"{wt:.2f}/2 = {r:.3f} mm (Boothroyd-Dewhurst §6.5). "
                    "Reduces sink marks and weld-line strength loss."
                )
            else:
                r = r_peterson
                rationale = (
                    f"Molded-plastic interior corner (no wall_thickness_hint): "
                    f"r = 0.1 × min_face_dim = {r:.3f} mm (Peterson 1974 §2.3). "
                    "Provide wall_thickness_hint for Boothroyd sizing."
                )
        elif design_intent == "machined":
            r = (cd / 2.0) if cd else _MACHINED_DEFAULT_CUTTER_DIAM / 2.0
            rationale = (
                f"Machined interior corner: r = cutter_diameter/2 = {r:.3f} mm. "
                "Minimum radius set by standard end-mill; Peterson Kt relief secondary."
            )
        elif design_intent == "cast":
            if wt:
                r = wt
                rationale = (
                    f"Cast interior corner: r = wall_thickness = {r:.3f} mm "
                    "(BS 4500A / Boothroyd-Dewhurst §6). Prevents shrinkage cracks."
                )
            else:
                r = r_peterson
                rationale = (
                    f"Cast interior corner (no wall_thickness_hint): "
                    f"r = 0.1 × min_face_dim = {r:.3f} mm (Peterson 1974 §2.3)."
                )
        else:  # 'auto'
            r = r_peterson
            rationale = (
                f"Interior corner stress relief: r = 0.1 × min_face_dim = "
                f"{adj_min_dim:.2f} × 0.1 = {r:.3f} mm (Peterson 1974 §2.3). "
                "Reduces stress concentration Kt in tension/bending."
            )

    else:  # exterior_corner
        if design_intent == "molded_plastic":
            if wt:
                r = wt / 2.0
                rationale = (
                    f"Molded-plastic exterior corner: r = wall_thickness/2 = "
                    f"{r:.3f} mm (Boothroyd-Dewhurst §6.5). Improves part ejection."
                )
            else:
                r = _EXTERIOR_RADIUS_DEFAULT
                rationale = (
                    f"Molded-plastic exterior corner: r = {r:.1f} mm default "
                    "(Boothroyd-Dewhurst §6). Provide wall_thickness_hint for precise sizing."
                )
        elif design_intent == "machined":
            r = _EXTERIOR_RADIUS_DEFAULT
            rationale = (
                f"Machined exterior corner: r = {r:.1f} mm for hand-feel "
                "and deburring compliance."
            )
        elif design_intent == "cast":
            if wt:
                r = max(_EXTERIOR_RADIUS_MIN, wt / 4.0)
                rationale = (
                    f"Cast exterior corner: r = wall_thickness/4 = {r:.3f} mm "
                    "(Boothroyd-Dewhurst §6). Reduces turbulence in metal flow."
                )
            else:
                r = _EXTERIOR_RADIUS_DEFAULT
                rationale = (
                    f"Cast exterior corner: r = {r:.1f} mm default "
                    "(Boothroyd-Dewhurst §6)."
                )
        else:  # 'auto'
            r = _EXTERIOR_RADIUS_DEFAULT
            rationale = (
                f"Exterior corner aesthetic fillet: r = {r:.1f} mm "
                "(0.5–2 mm typical for hand-feel and visual polish, "
                "Boothroyd-Dewhurst §6.3)."
            )

    return (float(r), rationale)


# ---------------------------------------------------------------------------
# Main recommendation engine
# ---------------------------------------------------------------------------


def recommend_fillets(
    body: Body,
    stress_relief_priority: bool = True,
    design_intent: str = "auto",
    wall_thickness_hint: Optional[float] = None,
    cutter_diameter_hint: Optional[float] = None,
) -> FilletRecommendationResult:
    """Identify edges where fillets are beneficial.

    For each straight edge in ``body`` the engine:

    1. Finds the two incident faces.
    2. Classifies the dihedral as ``'interior_corner'`` (concave, Kt > 1
       stress riser) or ``'exterior_corner'`` (convex, ergonomics target).
    3. Sizes the recommended radius per ``design_intent`` and the
       Peterson / Boothroyd rules.
    4. Estimates the Kt reduction for interior corners.

    Non-straight edges (circular arcs, NURBS) are included with
    ``applicable=False`` so the result list length equals
    ``len(body.all_edges())``.

    Parameters
    ----------
    body : Body
        A validated B-rep Body.
    stress_relief_priority : bool
        When True, interior corners are sorted before exterior corners in
        the result list (highest Kt-reduction first).
    design_intent : str
        One of ``'auto'``, ``'molded_plastic'``, ``'machined'``, ``'cast'``.
    wall_thickness_hint : float, optional
        Nominal wall thickness in model units (mm).  Used by molded-plastic
        and cast intent rules.
    cutter_diameter_hint : float, optional
        End-mill cutter diameter in mm.  Used by machined intent.

    Returns
    -------
    FilletRecommendationResult
    """
    edges = body.all_edges()
    recommendations: List[EdgeRecommendation] = []
    stress_count = 0
    aesthetic_count = 0

    for idx, edge in enumerate(edges):
        # Only straight edges are supported by fillet_solid_edge.
        if not _edge_is_straight(edge):
            recommendations.append(EdgeRecommendation(
                edge_index=idx,
                corner_type="exterior_corner",
                recommended_radius=0.0,
                priority="n/a",
                rationale="Skipped: non-straight edge (arc/NURBS). "
                          "Variable-radius fillet required.",
                estimated_kt_before=3.0,
                estimated_kt_after=3.0,
                applicable=False,
            ))
            continue

        incident = _find_incident_faces(body, edge)
        if len(incident) != 2:
            recommendations.append(EdgeRecommendation(
                edge_index=idx,
                corner_type="exterior_corner",
                recommended_radius=0.0,
                priority="n/a",
                rationale=f"Skipped: {len(incident)} incident faces "
                          f"(expected 2 for manifold body).",
                estimated_kt_before=3.0,
                estimated_kt_after=3.0,
                applicable=False,
            ))
            continue

        face_a, face_b = incident[0], incident[1]

        # Classify dihedral.
        _angle_deg, corner_type = _dihedral_angle_and_type(face_a, face_b, edge)

        # Adjacent-face minimum dimension for Peterson sizing.
        adj_min_dim = _adjacent_face_min_dim(face_a, face_b)

        # Size the radius per design intent.
        r, rationale = _radius_for_intent(
            corner_type=corner_type,
            design_intent=design_intent,
            adj_min_dim=adj_min_dim,
            wall_thickness_hint=wall_thickness_hint,
            cutter_diameter_hint=cutter_diameter_hint,
        )

        # Estimate Kt before/after for interior corners.
        if corner_type == "interior_corner":
            kt_before = 3.0
            kt_after = estimate_stress_reduction(
                edge, r, base_stress_concentration=kt_before
            )
            priority = "high"
            stress_count += 1
        else:
            kt_before = 1.0
            kt_after = 1.0
            priority = "low" if not stress_relief_priority else "low"
            aesthetic_count += 1

        recommendations.append(EdgeRecommendation(
            edge_index=idx,
            corner_type=corner_type,
            recommended_radius=r,
            priority=priority,
            rationale=rationale,
            estimated_kt_before=kt_before,
            estimated_kt_after=kt_after,
            applicable=True,
        ))

    if stress_relief_priority:
        recommendations.sort(key=lambda rec: (
            0 if rec.priority == "high" else 1,
            -(rec.estimated_kt_before - rec.estimated_kt_after),
        ))

    return FilletRecommendationResult(
        per_edge_recommendation=recommendations,
        total_recommended=sum(1 for r in recommendations if r.applicable),
        stress_relief_count=stress_count,
        aesthetic_count=aesthetic_count,
        design_intent=design_intent,
    )


# ---------------------------------------------------------------------------
# Application helper
# ---------------------------------------------------------------------------


def apply_fillet_recommendations(
    body: Body,
    recommendations: FilletRecommendationResult,
) -> Body:
    """Apply recommended fillets to the body, highest-priority first.

    Fillets are applied one at a time using :func:`fillet_solid_edge`.
    The engine skips edges whose recommendation has ``applicable=False``
    or where ``fillet_solid_edge`` returns ``ok=False`` (e.g. radius
    exceeds face extent).

    Returns the resulting ``Body`` (each applied fillet produces a new
    Body; if no fillets can be applied the original body is returned).

    .. warning::
        The edge indices in ``recommendations`` reference the *original*
        body's edge list.  After each fillet the topology changes and
        index-based access is no longer valid; this function rebuilds the
        edge list mapping by matching vertex positions after each step.
        For robustness, apply at most one fillet per call and reconstruct
        recommendations if the body has changed substantially.
    """
    current_body = body
    original_edges = body.all_edges()

    # Sort recommendations: high priority first, skip non-applicable.
    applicable = [
        rec for rec in recommendations.per_edge_recommendation
        if rec.applicable and rec.recommended_radius > 0
    ]
    applicable.sort(key=lambda r: (0 if r.priority == "high" else 1))

    for rec in applicable:
        if rec.edge_index >= len(original_edges):
            continue

        orig_edge = original_edges[rec.edge_index]
        # Find the matching edge in the current body by vertex proximity.
        p0_orig = np.asarray(orig_edge.v_start.point, dtype=float)
        p1_orig = np.asarray(orig_edge.v_end.point, dtype=float)

        matched_edge: Optional[Edge] = None
        for e in current_body.all_edges():
            a = np.asarray(e.v_start.point, dtype=float)
            b = np.asarray(e.v_end.point, dtype=float)
            if (
                (np.linalg.norm(a - p0_orig) < 1e-4
                 and np.linalg.norm(b - p1_orig) < 1e-4)
                or
                (np.linalg.norm(a - p1_orig) < 1e-4
                 and np.linalg.norm(b - p0_orig) < 1e-4)
            ):
                matched_edge = e
                break

        if matched_edge is None:
            continue

        result = fillet_solid_edge(current_body, matched_edge, rec.recommended_radius)
        if isinstance(result, dict) and result.get("ok"):
            new_body = result["body"]
            if new_body is not None:
                current_body = new_body
        # On failure: skip this edge silently, continue with remaining.

    return current_body


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors surface_fillet.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # brep_recommend_fillets
    # ------------------------------------------------------------------

    _recommend_spec = ToolSpec(
        name="brep_recommend_fillets",
        description=(
            "Analyse a B-rep body and recommend where fillets should be applied.\n"
            "\n"
            "For each straight edge the engine classifies the dihedral as:\n"
            "  interior_corner — concave, stress-relief priority (Peterson 1974)\n"
            "  exterior_corner — convex, ergonomics / visual-quality\n"
            "\n"
            "Radius is sized per design_intent:\n"
            "  auto           : Peterson r=0.1×min_face_dim (interior) / 1 mm (exterior)\n"
            "  molded_plastic : r = wall_thickness/2  (Boothroyd-Dewhurst §6.5)\n"
            "  machined       : r = cutter_diameter/2\n"
            "  cast           : r = wall_thickness    (BS 4500A)\n"
            "\n"
            "Input: axis-aligned box body described by corner [x,y,z] and dimensions "
            "[dx,dy,dz], or an explicit list of edges.\n"
            "\n"
            "Returns:\n"
            "  total_recommended : int\n"
            "  stress_relief_count : int\n"
            "  aesthetic_count : int\n"
            "  recommendations : [{edge_index, corner_type, recommended_radius, "
            "priority, rationale, kt_before, kt_after, applicable}]\n"
            "\n"
            "Error: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "corner": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Box origin [x, y, z].",
                },
                "dims": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Box dimensions [dx, dy, dz].",
                },
                "design_intent": {
                    "type": "string",
                    "enum": ["auto", "molded_plastic", "machined", "cast"],
                    "description": "Radius-sizing rule.",
                },
                "stress_relief_priority": {
                    "type": "boolean",
                    "description": (
                        "Sort interior-corner (stress-relief) edges first."
                    ),
                },
                "wall_thickness_hint": {
                    "type": "number",
                    "description": "Wall thickness in mm (for molded_plastic / cast).",
                },
                "cutter_diameter_hint": {
                    "type": "number",
                    "description": "End-mill cutter diameter in mm (for machined).",
                },
            },
            "required": ["corner", "dims"],
        },
    )

    @register(_recommend_spec)
    async def run_brep_recommend_fillets(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        corner = a.get("corner")
        dims = a.get("dims")
        if not corner or len(corner) != 3:
            return err_payload("corner must be [x,y,z]", "BAD_ARGS")
        if not dims or len(dims) != 3:
            return err_payload("dims must be [dx,dy,dz]", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.brep_build import box_to_body as _box
            body = _box(corner, float(dims[0]), float(dims[1]), float(dims[2]))
        except Exception as exc:
            return err_payload(f"box_to_body failed: {exc}", "BUILD_ERROR")

        try:
            result = recommend_fillets(
                body,
                stress_relief_priority=bool(a.get("stress_relief_priority", True)),
                design_intent=str(a.get("design_intent", "auto")),
                wall_thickness_hint=a.get("wall_thickness_hint"),
                cutter_diameter_hint=a.get("cutter_diameter_hint"),
            )
        except Exception as exc:
            return err_payload(f"recommend_fillets error: {exc}", "ENGINE_ERROR")

        recs = [
            {
                "edge_index": r.edge_index,
                "corner_type": r.corner_type,
                "recommended_radius": round(r.recommended_radius, 4),
                "priority": r.priority,
                "rationale": r.rationale,
                "kt_before": round(r.estimated_kt_before, 4),
                "kt_after": round(r.estimated_kt_after, 4),
                "applicable": r.applicable,
            }
            for r in result.per_edge_recommendation
        ]
        return ok_payload({
            "total_recommended": result.total_recommended,
            "stress_relief_count": result.stress_relief_count,
            "aesthetic_count": result.aesthetic_count,
            "design_intent": result.design_intent,
            "recommendations": recs,
        })

    # ------------------------------------------------------------------
    # brep_apply_fillet_recommendations
    # ------------------------------------------------------------------

    _apply_spec = ToolSpec(
        name="brep_apply_fillet_recommendations",
        description=(
            "Apply fillet recommendations to a B-rep box body.\n"
            "\n"
            "Builds the box from corner+dims, calls recommend_fillets with the "
            "given parameters, then applies all high-priority (stress-relief) "
            "fillets using fillet_solid_edge.  Returns the topology of the "
            "resulting body.\n"
            "\n"
            "Returns:\n"
            "  ok : bool\n"
            "  faces_applied : int  — number of successfully applied fillets\n"
            "  face_count : int     — faces in final body\n"
            "  edge_count : int\n"
            "  vertex_count : int\n"
            "  body_valid : bool    — validate_body result\n"
            "\n"
            "Error: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "corner": {
                    "type": "array",
                    "items": {"type": "number"},
                },
                "dims": {
                    "type": "array",
                    "items": {"type": "number"},
                },
                "design_intent": {
                    "type": "string",
                    "enum": ["auto", "molded_plastic", "machined", "cast"],
                },
                "stress_relief_only": {
                    "type": "boolean",
                    "description": "If true, only apply high-priority stress-relief fillets.",
                },
                "wall_thickness_hint": {"type": "number"},
                "cutter_diameter_hint": {"type": "number"},
            },
            "required": ["corner", "dims"],
        },
    )

    @register(_apply_spec)
    async def run_brep_apply_fillet_recommendations(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        corner = a.get("corner")
        dims = a.get("dims")
        if not corner or len(corner) != 3:
            return err_payload("corner must be [x,y,z]", "BAD_ARGS")
        if not dims or len(dims) != 3:
            return err_payload("dims must be [dx,dy,dz]", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.brep_build import box_to_body as _box
            body = _box(corner, float(dims[0]), float(dims[1]), float(dims[2]))
        except Exception as exc:
            return err_payload(f"box_to_body failed: {exc}", "BUILD_ERROR")

        try:
            result = recommend_fillets(
                body,
                design_intent=str(a.get("design_intent", "auto")),
                wall_thickness_hint=a.get("wall_thickness_hint"),
                cutter_diameter_hint=a.get("cutter_diameter_hint"),
            )
        except Exception as exc:
            return err_payload(f"recommend_fillets error: {exc}", "ENGINE_ERROR")

        stress_only = bool(a.get("stress_relief_only", False))
        if stress_only:
            for rec in result.per_edge_recommendation:
                if rec.priority != "high":
                    rec.applicable = False

        before_faces = len(body.all_faces())
        try:
            final_body = apply_fillet_recommendations(body, result)
        except Exception as exc:
            return err_payload(f"apply_fillet_recommendations error: {exc}", "ENGINE_ERROR")

        after_faces = len(final_body.all_faces())
        faces_applied = (after_faces - before_faces) // 1  # each fillet adds 1 face

        val = validate_body(final_body)

        return ok_payload({
            "ok": True,
            "faces_applied": max(0, after_faces - before_faces),
            "face_count": after_faces,
            "edge_count": len(final_body.all_edges()),
            "vertex_count": len(final_body.all_vertices()),
            "body_valid": bool(val.get("ok", False)),
        })
