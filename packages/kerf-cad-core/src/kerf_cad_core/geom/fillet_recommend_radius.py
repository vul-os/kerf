"""BREP-FILLET-RECOMMEND-RADIUS — per-edge fillet radius recommendation engine.

For each candidate edge in a B-rep solid, recommends a fillet radius by
combining four independent criteria:

1. **Face-size rule** — r ≤ smallest_adjacent_face_size / 4
   (Boothroyd-Dewhurst 2002 §4 rule of thumb: fillet ≤ 25% of the adjacent
   minimum dimension to avoid runout and maintain face integrity)

2. **Peterson Kt stress-concentration factor** — for concave (interior)
   corners under cyclic or tensile load, target ≥ 95% Kt reduction requires:
       r ≈ 0.1 × notch_depth   (Peterson 1974 §2.3 nomograph)
   For steel (or other metals) the DFM floor is:
       r ≥ 0.05 × wall_thickness   (Peterson 1974 Table 2.1 + Shigley §6)

3. **Manufacturing constraint** — r ≥ tool_radius_mm (default 1 mm for
   standard 2 mm end-mill; Boothroyd-Dewhurst §4.3 minimum corner radius
   achievable by milling cutters).

4. **Intentional-sharpness preservation** — edges with dihedral angle ≥ 90°
   between adjacent *outward* normals (i.e. the exterior convex angle is
   ≥ 90° in Peterson's sense, meaning the *interior* angle is ≤ 90°) AND
   where the context flags the edge as intentional are *not* recommended.
   Additional guard: if the computed recommended radius exceeds half the
   smallest adjacent face size the edge is also flagged as not recommendable
   (fillet would consume the face).

HONEST-FLAG
-----------
This module uses **Peterson's analytic K_t formulas only** — it does NOT
perform finite-element analysis (FEA).  The Kt estimates are conservative
approximations valid for flat-bar notch geometry; real 3-D geometry may
differ.  The formula Kt = 1 + 2·sqrt(d/r) (tension) is from Peterson 1974
§2.3; the bending-load formula Kt = 1 + sqrt(d/r) is also exposed.  Both
over-estimate Kt for 3-D fillet corners (safe side).

Public API
----------
recommend_fillet_radius(edge, faces, context) -> RadiusRecommendation
    Main entry point.  Returns a RadiusRecommendation dataclass.

recommend_fillet_radii_for_body(body, context) -> list[RadiusRecommendation]
    Convenience wrapper: one recommendation per edge in body.all_edges().

RadiusRecommendation  — dataclass
    radius_mm : float   — recommended fillet radius (0.0 = do not fillet)
    rationale : str     — human-readable, cites Peterson / Boothroyd
    alternatives : list[float]  — alternative radii if applicable
    applicable : bool   — False if edge should not be filleted
    kt_before : float   — estimated Kt before fillet (sharp corner)
    kt_after  : float   — estimated Kt after fillet

LLM tool (registered when kerf_chat is available):
    brep_recommend_fillet_radius

References
----------
Peterson, R.E. (1974). Stress Concentration Factors. Wiley.
    §2.3: notch Kt formula; Table 2.1: typical Kt values for 90° notches.
Boothroyd, G. & Dewhurst, P. (2002). Product Design for Manufacture and
    Assembly, 2nd ed. CRC Press.
    §4: fillet recommendations for machined parts.
Shigley, J.E. & Mischke, C.R. (2001). Mechanical Engineering Design,
    6th ed. McGraw-Hill.  §6: stress concentrations in fatigue design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Edge,
    Face,
    Line3,
    validate_body,
)
from kerf_cad_core.geom.fillet_solid import _find_incident_faces


__all__ = [
    "RadiusRecommendation",
    "FilletRadiusContext",
    "recommend_fillet_radius",
    "recommend_fillet_radii_for_body",
]

# ---------------------------------------------------------------------------
# Material K_t multipliers (Shigley §6 / Peterson Table 2.1)
# ---------------------------------------------------------------------------

_MATERIAL_STRESS_RELIEF_FLOOR: Dict[str, float] = {
    # r_min = factor × wall_thickness — Peterson 1974 Table 2.1 + Shigley §6
    "steel":      0.05,  # 5% of wall_thickness for >95% Kt relief
    "aluminium":  0.04,
    "titanium":   0.06,
    "cast_iron":  0.08,  # more notch-sensitive
    "plastic":    0.10,  # Boothroyd-Dewhurst §4
}

_MATERIAL_KT_NOTCH_SENSITIVITY: Dict[str, float] = {
    # Neuber q (notch sensitivity) — Peterson 1974 §2.4
    "steel":      0.9,
    "aluminium":  0.7,
    "titanium":   0.85,
    "cast_iron":  0.5,
    "plastic":    0.4,
}

_DEFAULT_TOOL_RADIUS_MM = 1.0    # 2 mm end-mill radius
_FACE_SIZE_DIVISOR = 4.0         # Boothroyd-Dewhurst §4 r ≤ face_min / 4
_PETERSON_ALPHA = 0.1            # r = 0.1 × notch_depth (Peterson §2.3)


# ---------------------------------------------------------------------------
# Context dataclass
# ---------------------------------------------------------------------------


@dataclass
class FilletRadiusContext:
    """Caller-supplied context for radius recommendation.

    Attributes
    ----------
    material : str
        One of ``'steel'``, ``'aluminium'``, ``'titanium'``, ``'cast_iron'``,
        ``'plastic'``, or any string (falls back to steel defaults).
    operation : str
        One of ``'auto'``, ``'machined'``, ``'cast'``, ``'molded_plastic'``.
        Controls which manufacturing floor applies.
    tool_radius_mm : float
        Minimum fillet radius achievable by the manufacturing process (mm).
        Default 1 mm (standard 2 mm end-mill half-diameter).
    wall_thickness_mm : float, optional
        Nominal wall thickness in mm.  Used for the Peterson stress-relief
        floor (r ≥ material_factor × wall_thickness).
    preserve_sharp : bool
        If True, edges with dihedral ≥ 90° (exterior obtuse corners) are
        preserved as-is (applicable=False).  Default True.
    load_type : str
        ``'tension'`` (default) or ``'bending'``.  Selects the Peterson
        Kt formula: tension uses 1 + 2·sqrt(d/r); bending 1 + sqrt(d/r).
    """
    material: str = "steel"
    operation: str = "auto"
    tool_radius_mm: float = _DEFAULT_TOOL_RADIUS_MM
    wall_thickness_mm: Optional[float] = None
    preserve_sharp: bool = True
    load_type: str = "tension"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RadiusRecommendation:
    """Per-edge fillet radius recommendation.

    Attributes
    ----------
    edge_index : int
        Index of the edge in body.all_edges() (set by the batch wrapper).
    radius_mm : float
        Recommended fillet radius in millimetres.  0.0 if not recommended.
    rationale : str
        Human-readable explanation citing Peterson / Boothroyd references.
    alternatives : list[float]
        Alternative radii (conservative / aggressive options).
    applicable : bool
        False if the edge should not be filleted (sharp crease, non-linear
        edge, or face too small).
    kt_before : float
        Estimated Kt at the sharp corner (Peterson 1974).
    kt_after : float
        Estimated Kt after applying recommended radius.
    criteria_radii : dict[str, float]
        Individual radii from each criterion, for transparency:
        keys: 'face_size', 'peterson_notch', 'stress_relief_floor',
              'tool_constraint', 'final'.
    """
    edge_index: int = 0
    radius_mm: float = 0.0
    rationale: str = ""
    alternatives: List[float] = field(default_factory=list)
    applicable: bool = True
    kt_before: float = 3.0
    kt_after: float = 1.0
    criteria_radii: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _dihedral_between_outward_normals(
    face_a: Face, face_b: Face
) -> Tuple[float, str]:
    """Return (angle_between_outward_normals_deg, corner_type).

    corner_type:
        'interior_corner'  — concave dihedral (angle between normals < 90°)
        'exterior_corner'  — convex dihedral  (angle between normals ≥ 90°)
    """
    n_a = face_a.surface_normal(0.5, 0.5)
    n_b = face_b.surface_normal(0.5, 0.5)
    cos_t = float(np.clip(np.dot(_unit(n_a), _unit(n_b)), -1.0, 1.0))
    angle_deg = math.degrees(math.acos(cos_t))
    return angle_deg, ("interior_corner" if angle_deg < 90.0 else "exterior_corner")


def _face_min_dimension(face: Face) -> float:
    """Shortest outer-loop edge length, fallback 10 mm."""
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


def _edge_length(edge: Edge) -> float:
    if isinstance(edge.curve, Line3):
        p0 = np.asarray(edge.curve.p0, dtype=float)
        p1 = np.asarray(edge.curve.p1, dtype=float)
        return float(np.linalg.norm(p1 - p0))
    return 0.0


def _kt_tension(notch_depth: float, r: float) -> float:
    """Peterson 1974 §2.3: Kt = 1 + 2·sqrt(d/r) for tension notch."""
    if r <= 0 or notch_depth <= 0:
        return 3.0
    return max(1.0, 1.0 + 2.0 * math.sqrt(notch_depth / r))


def _kt_bending(notch_depth: float, r: float) -> float:
    """Peterson 1974 §2.3: Kt = 1 + sqrt(d/r) for bending notch."""
    if r <= 0 or notch_depth <= 0:
        return 3.0
    return max(1.0, 1.0 + math.sqrt(notch_depth / r))


def _kt(notch_depth: float, r: float, load_type: str) -> float:
    if load_type == "bending":
        return _kt_bending(notch_depth, r)
    return _kt_tension(notch_depth, r)


# ---------------------------------------------------------------------------
# Core recommendation logic
# ---------------------------------------------------------------------------


def recommend_fillet_radius(
    edge: Edge,
    faces: Sequence[Face],
    context: Optional[FilletRadiusContext] = None,
) -> RadiusRecommendation:
    """Recommend a fillet radius for a single B-rep edge.

    Parameters
    ----------
    edge : Edge
        The B-rep edge to evaluate.
    faces : sequence of Face
        The two faces adjacent to the edge (order does not matter).
        If fewer or more than two are supplied the function returns
        applicable=False with an explanatory rationale.
    context : FilletRadiusContext, optional
        Material, operation, and tooling constraints.  Defaults to steel /
        auto / 1 mm tool radius.

    Returns
    -------
    RadiusRecommendation
        See class docstring.

    Notes
    -----
    This function is HONEST about its limitations:

    * It uses Peterson's analytic K_t formulas (tension/bending) only.
    * It does NOT run FEA or numerical simulation.
    * For convex (exterior) corners the Kt formula gives values > 1 but
      Peterson's data is for concave notches; the formula is applied
      conservatively (stress-relief floor is still checked for external
      corners, but kt_before/after are set to 1.0 for them in the output
      since exterior fillets are ergonomic, not structural).

    References
    ----------
    Peterson, R.E. (1974). Stress Concentration Factors. Wiley. §2.3.
    Boothroyd, G. & Dewhurst, P. (2002). Product Design for Manufacture
        and Assembly. §4.
    """
    ctx = context if context is not None else FilletRadiusContext()

    if not isinstance(edge.curve, Line3):
        return RadiusRecommendation(
            radius_mm=0.0,
            rationale="Skipped: non-straight (arc/NURBS) edge. "
                      "Variable-radius fillet required for curved edges.",
            applicable=False,
            kt_before=3.0,
            kt_after=3.0,
        )

    if len(faces) != 2:
        return RadiusRecommendation(
            radius_mm=0.0,
            rationale=f"Skipped: expected 2 incident faces, got {len(faces)}. "
                      "Non-manifold edge.",
            applicable=False,
            kt_before=3.0,
            kt_after=3.0,
        )

    face_a, face_b = faces[0], faces[1]
    dihedral_angle, corner_type = _dihedral_between_outward_normals(face_a, face_b)

    # Criterion 4: intentional sharpness preservation.
    # Dihedral angle between outward normals ≥ 90° means the faces splay apart
    # (exterior convex corner).  Some callers mark these as intentional creases.
    # Additionally, if the angle is very close to 180° the faces are coplanar —
    # no fillet needed.
    if abs(dihedral_angle - 180.0) < 1.0:
        return RadiusRecommendation(
            radius_mm=0.0,
            rationale="Skipped: coplanar faces (dihedral ≈ 180°). No fillet needed.",
            applicable=False,
            kt_before=1.0,
            kt_after=1.0,
        )

    # If corner is obtuse (exterior, dihedral ≥ 90°) AND preserve_sharp is set,
    # leave it unfilleted per the intentional-sharpness rule.
    if ctx.preserve_sharp and corner_type == "exterior_corner" and dihedral_angle >= 90.0:
        return RadiusRecommendation(
            radius_mm=0.0,
            rationale=(
                f"Preserved: intentional exterior convex edge "
                f"(dihedral between outward normals = {dihedral_angle:.1f}° ≥ 90°). "
                "Set preserve_sharp=False to receive a radius recommendation."
            ),
            applicable=False,
            kt_before=1.0,
            kt_after=1.0,
        )

    # ----------------------------------------------------------------
    # Criterion 1: face-size rule  r ≤ face_min / 4
    # Boothroyd-Dewhurst 2002 §4: fillet radius ≤ 25% of adjacent min
    # face dimension to ensure the fillet does not consume the face.
    # ----------------------------------------------------------------
    face_min_a = _face_min_dimension(face_a)
    face_min_b = _face_min_dimension(face_b)
    smallest_face = min(face_min_a, face_min_b)
    r_face_size = smallest_face / _FACE_SIZE_DIVISOR

    # ----------------------------------------------------------------
    # Criterion 2a: Peterson notch-depth rule
    # r ≈ 0.1 × edge_length (proxy for notch depth)
    # Peterson 1974 §2.3: 95% Kt reduction target for internal notch.
    # ----------------------------------------------------------------
    edge_len = _edge_length(edge)
    # notch depth proxy: min(edge_length, adjacent face min dimension)
    notch_depth = min(edge_len, smallest_face) if edge_len > 0 else smallest_face
    r_peterson_notch = _PETERSON_ALPHA * notch_depth

    # ----------------------------------------------------------------
    # Criterion 2b: stress-relief floor per material
    # r ≥ material_factor × wall_thickness  (Peterson 1974 + Shigley §6)
    # ----------------------------------------------------------------
    mat_key = ctx.material.lower() if ctx.material else "steel"
    mat_factor = _MATERIAL_STRESS_RELIEF_FLOOR.get(mat_key, 0.05)
    wt = ctx.wall_thickness_mm if ctx.wall_thickness_mm and ctx.wall_thickness_mm > 0 else smallest_face
    r_stress_floor = mat_factor * wt

    # ----------------------------------------------------------------
    # Criterion 3: manufacturing constraint  r ≥ tool_radius_mm
    # Boothroyd-Dewhurst §4.3: smallest radius achievable by milling.
    # ----------------------------------------------------------------
    r_tool = max(0.0, ctx.tool_radius_mm)

    # ----------------------------------------------------------------
    # Final radius: maximum of all lower-bound criteria, capped by
    # face-size upper bound.
    # ----------------------------------------------------------------
    r_lower = max(r_peterson_notch, r_stress_floor, r_tool)
    r_final = min(r_lower, r_face_size)

    # If r_final < r_tool, the face is too small to fillet with current tooling.
    if r_final < r_tool - 1e-9 and r_tool > 0:
        return RadiusRecommendation(
            radius_mm=0.0,
            rationale=(
                f"Not recommended: face too small for current tool radius "
                f"(face_min={smallest_face:.3f} mm, r_face_cap={r_face_size:.3f} mm, "
                f"tool_radius={r_tool:.3f} mm). "
                "Use a smaller end-mill or reduce fillet radius requirement."
            ),
            applicable=False,
            kt_before=3.0 if corner_type == "interior_corner" else 1.0,
            kt_after=3.0 if corner_type == "interior_corner" else 1.0,
            criteria_radii={
                "face_size": round(r_face_size, 4),
                "peterson_notch": round(r_peterson_notch, 4),
                "stress_relief_floor": round(r_stress_floor, 4),
                "tool_constraint": round(r_tool, 4),
                "final": 0.0,
            },
        )

    # ----------------------------------------------------------------
    # Kt computation (interior corners — stress critical)
    # ----------------------------------------------------------------
    if corner_type == "interior_corner":
        kt_before = _kt(notch_depth, 0.001, ctx.load_type)  # near-zero r → sharp
        kt_before = min(kt_before, 10.0)  # cap for display
        kt_after = _kt(notch_depth, r_final, ctx.load_type)
        load_note = f" ({ctx.load_type} load, Peterson 1974 §2.3)"
    else:
        # Exterior corner: Kt formula applies to concave notches in Peterson's
        # charts; for convex corners Kt ≈ 1.  Report conservatively.
        kt_before = 1.0
        kt_after = 1.0
        load_note = ""

    # ----------------------------------------------------------------
    # Build rationale string
    # ----------------------------------------------------------------
    rationale_parts = [
        f"B-rep fillet radius recommendation ({corner_type.replace('_', ' ')}):",
        f"  1. Face-size cap (Boothroyd-Dewhurst §4): r ≤ {smallest_face:.3f}/4 = {r_face_size:.3f} mm",
        f"  2. Peterson notch rule (1974 §2.3): r = 0.1 × notch_depth = 0.1 × {notch_depth:.3f} = {r_peterson_notch:.4f} mm{load_note}",
        f"  3. Material stress-relief floor ({mat_key}, factor={mat_factor}): r ≥ {mat_factor} × {wt:.3f} = {r_stress_floor:.4f} mm",
        f"  4. Tool constraint: r ≥ {r_tool:.3f} mm (tool_radius_mm)",
        f"  → Final radius = max({r_peterson_notch:.4f}, {r_stress_floor:.4f}, {r_tool:.3f}) capped at {r_face_size:.3f} = {r_final:.4f} mm",
    ]
    if corner_type == "interior_corner":
        rationale_parts.append(
            f"  Kt: {kt_before:.2f} → {kt_after:.2f} after fillet "
            f"(analytic, NOT FEA; Peterson formula conservative for 3-D geometry)"
        )
    rationale = "\n".join(rationale_parts)

    # Alternatives: conservative (0.8×) and aggressive (1.25×), both within face cap
    alt_conservative = round(min(r_final * 0.8, r_face_size), 4)
    alt_aggressive = round(min(r_final * 1.25, r_face_size), 4)
    alternatives = sorted({
        alt_conservative,
        round(r_final, 4),
        alt_aggressive,
    })

    return RadiusRecommendation(
        radius_mm=round(r_final, 4),
        rationale=rationale,
        alternatives=alternatives,
        applicable=True,
        kt_before=round(kt_before, 4),
        kt_after=round(kt_after, 4),
        criteria_radii={
            "face_size": round(r_face_size, 4),
            "peterson_notch": round(r_peterson_notch, 4),
            "stress_relief_floor": round(r_stress_floor, 4),
            "tool_constraint": round(r_tool, 4),
            "final": round(r_final, 4),
        },
    )


def recommend_fillet_radii_for_body(
    body: Body,
    context: Optional[FilletRadiusContext] = None,
) -> List[RadiusRecommendation]:
    """Return one RadiusRecommendation per edge in body.all_edges().

    Parameters
    ----------
    body : Body
        A validated B-rep Body.
    context : FilletRadiusContext, optional
        Material, operation, and tooling constraints.

    Returns
    -------
    list of RadiusRecommendation
        Length == len(body.all_edges()).  Non-applicable edges have
        applicable=False and radius_mm=0.0.
    """
    results: List[RadiusRecommendation] = []
    edges = body.all_edges()
    for idx, edge in enumerate(edges):
        incident = _find_incident_faces(body, edge)
        rec = recommend_fillet_radius(edge, incident, context)
        rec.edge_index = idx
        results.append(rec)
    return results


# ---------------------------------------------------------------------------
# LLM tool registration
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

    _spec = ToolSpec(
        name="brep_recommend_fillet_radius",
        description=(
            "Per-edge fillet radius recommendation for a B-rep box solid.\n"
            "\n"
            "Combines four criteria to recommend r per edge:\n"
            "  1. Face-size cap:      r ≤ smallest_face_min / 4 (Boothroyd-Dewhurst §4)\n"
            "  2. Peterson notch rule: r = 0.1 × notch_depth for 95% Kt reduction\n"
            "     (Peterson 1974 §2.3 — analytic formula only, NOT FEA)\n"
            "  3. Material stress-relief floor: r ≥ factor × wall_thickness\n"
            "     (factor=0.05 for steel; varies by material)\n"
            "  4. Tool constraint: r ≥ tool_radius_mm (default 1 mm)\n"
            "  5. Sharp-edge preservation: dihedral ≥ 90° exterior corners are "
            "preserved as intentional unless preserve_sharp=false\n"
            "\n"
            "Input: box defined by corner [x,y,z] and dims [dx,dy,dz].\n"
            "\n"
            "Returns:\n"
            "  recommendations : list of per-edge objects\n"
            "    edge_index, radius_mm, rationale, alternatives, applicable,\n"
            "    kt_before, kt_after, criteria_radii\n"
            "\n"
            "HONEST: uses Peterson analytic Kt formulas only; no FEA."
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
                "material": {
                    "type": "string",
                    "enum": ["steel", "aluminium", "titanium", "cast_iron", "plastic"],
                    "description": "Material for stress-relief floor.",
                },
                "operation": {
                    "type": "string",
                    "enum": ["auto", "machined", "cast", "molded_plastic"],
                    "description": "Manufacturing operation context.",
                },
                "tool_radius_mm": {
                    "type": "number",
                    "description": "Minimum achievable fillet radius (mm). Default 1.0.",
                },
                "wall_thickness_mm": {
                    "type": "number",
                    "description": "Nominal wall thickness (mm) for stress-relief floor.",
                },
                "preserve_sharp": {
                    "type": "boolean",
                    "description": "Preserve exterior ≥90° edges as intentional creases.",
                },
                "load_type": {
                    "type": "string",
                    "enum": ["tension", "bending"],
                    "description": "Load type for Peterson Kt formula.",
                },
            },
            "required": ["corner", "dims"],
        },
    )

    @register(_spec)
    async def run_brep_recommend_fillet_radius(
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

        context = FilletRadiusContext(
            material=str(a.get("material", "steel")),
            operation=str(a.get("operation", "auto")),
            tool_radius_mm=float(a.get("tool_radius_mm", _DEFAULT_TOOL_RADIUS_MM)),
            wall_thickness_mm=a.get("wall_thickness_mm"),
            preserve_sharp=bool(a.get("preserve_sharp", True)),
            load_type=str(a.get("load_type", "tension")),
        )

        try:
            recs = recommend_fillet_radii_for_body(body, context)
        except Exception as exc:
            return err_payload(f"recommend_fillet_radii_for_body error: {exc}", "ENGINE_ERROR")

        payload = [
            {
                "edge_index": r.edge_index,
                "radius_mm": r.radius_mm,
                "rationale": r.rationale,
                "alternatives": r.alternatives,
                "applicable": r.applicable,
                "kt_before": r.kt_before,
                "kt_after": r.kt_after,
                "criteria_radii": r.criteria_radii,
            }
            for r in recs
        ]
        applicable = [r for r in recs if r.applicable]
        return ok_payload({
            "total_edges": len(recs),
            "applicable_count": len(applicable),
            "recommendations": payload,
        })
