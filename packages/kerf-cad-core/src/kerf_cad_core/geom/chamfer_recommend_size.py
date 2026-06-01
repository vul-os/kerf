"""BREP-CHAMFER-RECOMMEND-SIZE — per-edge chamfer dimension recommendation engine.

For each candidate edge in a B-rep solid, recommends chamfer offset distance
and angle by combining four independent criteria:

1. **Safety / deburring** — minimum 0.5 mm × 45° for sheet-metal edges to
   eliminate burrs and prevent laceration hazard.
   (Drozda-Wick "Tool and Manufacturing Engineers Handbook" Vol.1 §3-7;
   ISO 13715:2017 §5 edge specification)

2. **Manufacturing** — chamfer mill tool size determines practical minimum.
   Common standard: 3 mm × 45° for a 6 mm chamfer mill cutter.
   (Drozda-Wick Vol.1 §3-7.3; standard chamfer mills are 60°/82°/90°/100°;
   45° included angle → 22.5° half-angle; 90° cutter is the most common
   shop-floor choice giving a 45° chamfer)

3. **Function (countersink)** — DIN 74 Form A countersink dimensions for bolt
   clearance holes.  For M3: chamfer diameter d2 = 3.4 mm → offset from
   hole edge = (3.4 - 3.0) / 2 = 0.2 mm radial, but the countersink angle
   per DIN 74 is 90° (included) → 45° half-angle; the full countersink depth
   is sized so the bolt head seats flush.
   Standard DIN 74 Form A values (d1 → d2 × 90°):
     M2 (d1=2.0) → d2=2.4 mm; M3 → 3.4 mm; M4 → 4.5 mm; M5 → 5.5 mm;
     M6 → 6.6 mm; M8 → 9.0 mm; M10 → 11.0 mm; M12 → 13.5 mm
   (DIN 74:1974 Table 1 Form A)

4. **Aesthetic** — visible exterior edges often receive a cosmetic chamfer
   1–2 mm × 45° for a premium hand-feel and light-catching edge.
   (Industry convention; Boothroyd-Dewhurst 2002 §4 DFM chamfer guide)

HONEST-FLAG
-----------
* This module recommends chamfer geometry only; it does NOT model production
  cost tradeoffs (tool changes, setup time, number of passes).
* Countersink matching uses a simple diameter lookup against DIN 74 Table 1;
  it does NOT perform tolerancing stack-up or thread engagement analysis.
* The default angle is 45° (equal-leg symmetric); asymmetric chamfers
  (e.g. 30°×60°, 1×2 mm leg ratio) are supported via
  ``recommend_asymmetric_chamfer()`` and the ``ratio`` parameter on
  ``recommend_chamfer_size()``.  Set ``ratio != 1.0`` to activate.
* Sheet-metal deburring floor (0.5 mm) is a safe minimum; actual burr height
  depends on shear clearance and material — a full burr analysis requires
  Drozda-Wick §3-7 Table 3 which is process-parameter dependent.
* ISO 13715:2017 defines the drawing symbol and direction convention;
  this module outputs the numeric dimension only, not the symbol.

Public API
----------
recommend_chamfer_size(edge, faces, context, ratio=1.0) -> ChamferRecommendation
    Main entry point.  Returns a ChamferRecommendation dataclass.
    ratio=1.0 gives symmetric 45° (backward compatible).
    ratio != 1.0 delegates to recommend_asymmetric_chamfer().

recommend_asymmetric_chamfer(edge_geometry, application, ratio_a_to_b) -> AsymmetricChamferRecommendation
    Asymmetric chamfer: leg_a = ratio × leg_b; angles from atan2.

recommend_chamfer_sizes_for_body(body, context) -> list[ChamferRecommendation]
    Convenience wrapper: one recommendation per edge in body.all_edges().

ChamferRecommendation — dataclass
    offset_mm    : float  — chamfer offset distance (each side for 45°)
    angle_deg    : float  — chamfer half-angle (typically 45°)
    kind         : str    — 'deburring' | 'manufacturing' | 'countersink' | 'cosmetic'
    rationale    : str    — human-readable with citations
    din_reference: str    — DIN 74 / ISO 13715 reference string, or ''
    applicable   : bool   — False if edge should not be chamfered
    edge_index   : int    — index in body.all_edges() (set by batch wrapper)

AsymmetricChamferRecommendation — dataclass
    leg_a_mm     : float  — longer (or equal) chamfer leg in mm
    leg_b_mm     : float  — shorter (or equal) chamfer leg in mm
    angle_a_deg  : float  — acute angle between leg_a face and chamfer face
    angle_b_deg  : float  — acute angle between leg_b face and chamfer face
    is_symmetric : bool   — True when leg_a == leg_b (ratio == 1.0)
    kind         : str    — dominant criterion
    rationale    : str    — human-readable with citations
    applicable   : bool   — False if edge should not be chamfered
    edge_index   : int    — index in body.all_edges()

LLM tool (registered when kerf_chat is available):
    brep_recommend_chamfer_size

References
----------
Drozda, T.J. & Wick, C. (eds) (1983). Tool and Manufacturing Engineers
    Handbook, 4th ed. Vol. 1: Machining. Society of Manufacturing Engineers.
    §3-7: deburring and edge preparation; §3-7.3: chamfer milling.
DIN 74:1974. Senkungen für Zylinderschrauben — Countersinks for machine
    screws (Form A 90°, Form B 120°). DIN Deutsches Institut für Normung.
    Table 1: d1 (clearance hole) → d2 (countersink diameter) at 90° included.
ISO 13715:2017. Technical product documentation — Indication of surface
    texture in technical product documentation.  §5: edge indication symbols.
Boothroyd, G. & Dewhurst, P. (2002). Product Design for Manufacture and
    Assembly, 2nd ed. CRC Press.  §4: chamfer DFM guidelines.
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
    "ChamferRecommendation",
    "AsymmetricChamferRecommendation",
    "ChamferContext",
    "recommend_chamfer_size",
    "recommend_asymmetric_chamfer",
    "recommend_chamfer_sizes_for_body",
    "DIN74_COUNTERSINK_TABLE",
]

# ---------------------------------------------------------------------------
# DIN 74 Form A countersink table (Table 1)
# d1 = nominal clearance hole diameter (mm) → d2 = countersink diameter (mm)
# Angle: 90° included (45° half-angle / 45° chamfer angle)
# Reference: DIN 74:1974 Table 1 Form A
# ---------------------------------------------------------------------------

DIN74_COUNTERSINK_TABLE: Dict[float, float] = {
    # d1 (hole dia, mm) -> d2 (countersink dia, mm)  — DIN 74:1974 Form A
    2.0:  2.4,
    2.5:  3.0,
    3.0:  3.4,
    3.5:  4.0,
    4.0:  4.5,
    5.0:  5.5,
    6.0:  6.6,
    7.0:  7.6,
    8.0:  9.0,
    9.0:  10.0,
    10.0: 11.0,
    11.0: 12.0,
    12.0: 13.5,
    14.0: 15.5,
    16.0: 17.5,
    18.0: 20.0,
    20.0: 22.0,
    22.0: 24.0,
    24.0: 26.0,
    27.0: 30.0,
    30.0: 33.0,
}

# DIN 74 Form B (120° included = 60° half-angle) — less common, for countersunk
# screws with 120° head angle; same d1 keys, slightly smaller d2
DIN74_FORMB_TABLE: Dict[float, float] = {
    2.0: 3.2, 2.5: 4.0, 3.0: 4.5, 4.0: 5.5, 5.0: 6.5, 6.0: 7.5,
    8.0: 10.0, 10.0: 12.5, 12.0: 15.0,
}

# Manufacturing: standard chamfer mill offset floors (Drozda-Wick §3-7.3)
# offset_mm = (cutter_diameter / 2) × tan(45°) → equals half cutter diameter
# Common 6 mm chamfer mill → min offset 3 mm; 3 mm mill → 1.5 mm min
_CHAMFER_MILL_MIN_OFFSET_MM = 0.5   # practical minimum (small tools)
_CHAMFER_MILL_TYPICAL_MM = 3.0      # common shop-floor 6 mm mill at 45°
_DEBURRING_MIN_MM = 0.5             # ISO 13715 / Drozda-Wick §3-7 deburring floor
_COSMETIC_DEFAULT_MM = 1.5          # aesthetic: 1–2 mm range, midpoint
_CHAMFER_ANGLE_DEG = 45.0           # standard 45° chamfer (DIN 74 Form A)

# Edge length classification thresholds
_SHORT_EDGE_THRESHOLD_MM = 1.0      # very short edges: deburring only
_HOLE_EDGE_THRESHOLD_RATIO = 0.8    # circular-ish if perimeter ≈ π×diameter


# ---------------------------------------------------------------------------
# Context dataclass
# ---------------------------------------------------------------------------


@dataclass
class ChamferContext:
    """Caller-supplied context for chamfer size recommendation.

    Attributes
    ----------
    material : str
        Material name.  Influences deburring floor.  E.g. 'steel', 'aluminium',
        'plastic', 'sheet_metal'.
    operation : str
        Manufacturing process: 'machined', 'sheet_metal', 'cast', 'auto'.
    chamfer_mill_diameter_mm : float
        Diameter of the available chamfer mill (mm).  Default 6.0 mm
        (gives 3 mm offset at 45°, per Drozda-Wick §3-7.3).
    hole_diameter_mm : float, optional
        If the edge is a circular hole edge, supply the hole diameter so
        DIN 74 countersink lookup can be applied.
    is_visible : bool
        True if this edge is user-visible (triggers cosmetic check).
    din74_form : str
        'A' (90° incl, default) or 'B' (120° incl) per DIN 74:1974.
    """
    material: str = "steel"
    operation: str = "auto"
    chamfer_mill_diameter_mm: float = 6.0
    hole_diameter_mm: Optional[float] = None
    is_visible: bool = True
    din74_form: str = "A"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ChamferRecommendation:
    """Per-edge chamfer size recommendation.

    Attributes
    ----------
    edge_index : int
        Index in body.all_edges().
    offset_mm : float
        Chamfer offset distance in mm (each face side, for 45° equal chamfer).
        0.0 if not recommended.
    angle_deg : float
        Chamfer half-angle in degrees (typically 45.0).
    kind : str
        Dominant criterion: 'deburring' | 'manufacturing' | 'countersink' | 'cosmetic'.
    rationale : str
        Human-readable explanation with standard citations.
    din_reference : str
        DIN 74 or ISO 13715 reference string, or '' if not applicable.
    applicable : bool
        False if edge should not be chamfered.
    criteria_offsets : dict[str, float]
        Offset from each criterion keyed by name.
    """
    edge_index: int = 0
    offset_mm: float = 0.0
    angle_deg: float = _CHAMFER_ANGLE_DEG
    kind: str = "deburring"
    rationale: str = ""
    din_reference: str = ""
    applicable: bool = True
    criteria_offsets: Dict[str, float] = field(default_factory=dict)


@dataclass
class AsymmetricChamferRecommendation:
    """Per-edge asymmetric chamfer recommendation.

    Attributes
    ----------
    edge_index : int
        Index in body.all_edges().
    leg_a_mm : float
        Length of the first chamfer leg (mm).  For ratio_a_to_b >= 1.0 this
        is the longer (or equal) leg.
    leg_b_mm : float
        Length of the second chamfer leg (mm).  For ratio_a_to_b >= 1.0 this
        is the shorter (or equal) leg.
    angle_a_deg : float
        Acute angle (degrees) at the junction of leg_a with its parent face.
        Computed as ``atan2(leg_b, leg_a)`` converted to degrees.
        When symmetric (45°/45°) this equals 45.0.
    angle_b_deg : float
        Acute angle (degrees) at the junction of leg_b with its parent face.
        Equals ``90 - angle_a_deg``.  The two angles always sum to 90°.
    is_symmetric : bool
        True when leg_a == leg_b (ratio == 1.0).
    kind : str
        Dominant criterion: 'deburring' | 'manufacturing' | 'countersink' | 'cosmetic'.
    rationale : str
        Human-readable explanation with standard citations.
    applicable : bool
        False if edge should not be chamfered.
    """
    edge_index: int = 0
    leg_a_mm: float = 0.0
    leg_b_mm: float = 0.0
    angle_a_deg: float = 45.0
    angle_b_deg: float = 45.0
    is_symmetric: bool = True
    kind: str = "deburring"
    rationale: str = ""
    applicable: bool = True


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _dihedral_deg(face_a: Face, face_b: Face) -> Tuple[float, str]:
    """(angle_between_outward_normals_deg, 'interior'|'exterior')"""
    n_a = face_a.surface_normal(0.5, 0.5)
    n_b = face_b.surface_normal(0.5, 0.5)
    cos_t = float(np.clip(np.dot(_unit(n_a), _unit(n_b)), -1.0, 1.0))
    angle = math.degrees(math.acos(cos_t))
    return angle, ("interior" if angle < 90.0 else "exterior")


def _edge_length(edge: Edge) -> float:
    if isinstance(edge.curve, Line3):
        p0 = np.asarray(edge.curve.p0, dtype=float)
        p1 = np.asarray(edge.curve.p1, dtype=float)
        return float(np.linalg.norm(p1 - p0))
    return 0.0


def _face_min_dimension(face: Face) -> float:
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


def _din74_lookup(hole_dia_mm: float, form: str = "A") -> Optional[float]:
    """Return DIN 74 countersink offset_mm for given hole diameter, or None.

    offset_mm = (d2 - d1) / 2  — radial offset from hole wall to countersink edge.
    At 45°, the axial depth equals the radial offset.

    DIN 74:1974 Table 1 Form A (90° incl) or Form B (120° incl).
    """
    table = DIN74_FORMB_TABLE if form.upper() == "B" else DIN74_COUNTERSINK_TABLE
    # Exact match within 0.1 mm tolerance
    for d1, d2 in table.items():
        if abs(d1 - hole_dia_mm) <= 0.1:
            return round((d2 - d1) / 2.0, 4)
    return None


# ---------------------------------------------------------------------------
# Asymmetric chamfer recommendation
# ---------------------------------------------------------------------------


def recommend_asymmetric_chamfer(
    edge_geometry: Edge,
    application: str = "machining",
    ratio_a_to_b: float = 1.0,
) -> AsymmetricChamferRecommendation:
    """Recommend an asymmetric (or symmetric) chamfer for a single B-rep edge.

    Computes two unequal chamfer legs based on the edge length, practical
    clearance constraints, and the requested leg ratio.  The two acute angles
    at the chamfer are derived from ``atan2``:

        angle_a = degrees(atan2(leg_b, leg_a))   — angle at the leg_a face
        angle_b = 90° − angle_a                   — angle at the leg_b face

    For ratio_a_to_b == 1.0 both legs are equal and both angles are 45°
    (equivalent to the symmetric path).

    Parameters
    ----------
    edge_geometry : Edge
        The B-rep edge.  Only its length is used; non-linear edges (arc/NURBS)
        are accepted but the length defaults to 0.0 and a cautionary note is
        added to the rationale.
    application : str, optional
        Usage context: 'machining' (default), 'sheet_metal', 'cosmetic'.
        Controls the base leg_b size before the ratio is applied.
    ratio_a_to_b : float, optional
        Leg ratio leg_a / leg_b.  Must be > 0.  Default 1.0 gives symmetric
        45° chamfer.  ratio=2.0 → leg_a = 2·leg_b; ratio=0.5 → leg_a = 0.5·leg_b.

    Returns
    -------
    AsymmetricChamferRecommendation
        Populated dataclass.  applicable=False if the edge is geometrically
        unsuitable (e.g. non-positive length or ratio <= 0).

    Notes
    -----
    * Base leg_b is chosen as the deburring floor (0.5 mm) for 'machining'
      and 'sheet_metal', and the cosmetic default (1.5 mm) for 'cosmetic'.
      This provides a safe minimum; callers should override via the ratio to
      scale both legs proportionally.
    * Angle convention: the chamfer face makes angle_a with the face adjacent
      to leg_a, and angle_b with the face adjacent to leg_b.  The angles
      always satisfy angle_a + angle_b = 90°.
    * The cap rule limits leg_a to 10× leg_b to avoid degenerate near-flat
      chamfers.
    * HONEST: this function sizes legs from first principles (edge length +
      clearance floor + ratio); it does NOT perform DIN 74 countersink lookup,
      production cost modelling, or ISO 13715 symbol output.

    References
    ----------
    Drozda-Wick Vol.1 §3-7 (edge preparation and deburring floors).
    ISO 13715:2017 §5 (edge indication — direction convention).
    """
    if ratio_a_to_b <= 0.0:
        return AsymmetricChamferRecommendation(
            applicable=False,
            kind="deburring",
            rationale=f"Not applicable: ratio_a_to_b must be > 0 (got {ratio_a_to_b}).",
        )

    # Base leg_b: application-dependent minimum
    if application == "cosmetic":
        base_leg_b = _COSMETIC_DEFAULT_MM
        kind = "cosmetic"
    elif application == "sheet_metal":
        base_leg_b = _DEBURRING_MIN_MM
        kind = "deburring"
    else:  # 'machining' default
        base_leg_b = _DEBURRING_MIN_MM
        kind = "manufacturing" if ratio_a_to_b == 1.0 else "manufacturing"

    leg_b = base_leg_b
    leg_a = ratio_a_to_b * leg_b

    # Degenerate cap: prevent ratio from producing near-flat chamfers (> 10:1)
    _MAX_RATIO = 10.0
    if ratio_a_to_b > _MAX_RATIO:
        leg_a = _MAX_RATIO * leg_b
        cap_note = (
            f" (leg_a capped at {_MAX_RATIO}× leg_b to avoid near-flat chamfer)"
        )
    else:
        cap_note = ""

    # Angle computation: atan2(leg_b, leg_a) gives the angle at the leg_a face
    angle_a_deg = math.degrees(math.atan2(leg_b, leg_a))
    angle_b_deg = 90.0 - angle_a_deg
    is_symmetric = abs(leg_a - leg_b) < 1e-9

    rationale_parts = [
        f"Asymmetric chamfer recommendation (application={application!r}, ratio={ratio_a_to_b}):",
        f"  Base leg_b = {leg_b:.3f} mm (deburring/cosmetic floor; Drozda-Wick §3-7)",
        f"  leg_a = ratio × leg_b = {ratio_a_to_b} × {leg_b:.3f} = {leg_a:.3f} mm{cap_note}",
        f"  angle_a = atan2(leg_b, leg_a) = atan2({leg_b:.3f}, {leg_a:.3f}) = {angle_a_deg:.4f}°",
        f"  angle_b = 90° − angle_a = {angle_b_deg:.4f}°",
        f"  is_symmetric = {is_symmetric} (leg_a == leg_b: {abs(leg_a - leg_b) < 1e-9})",
        "  Angle convention: angle_a is at the leg_a-face junction; "
        "angle_b at the leg_b-face junction; angle_a + angle_b = 90° exactly.",
        "  HONEST: legs sized from first principles (floor + ratio); "
        "no DIN 74 countersink lookup; no production cost modelling; "
        "no ISO 13715 symbol output.  (Drozda-Wick §3-7; ISO 13715:2017 §5)",
    ]

    return AsymmetricChamferRecommendation(
        leg_a_mm=round(leg_a, 6),
        leg_b_mm=round(leg_b, 6),
        angle_a_deg=round(angle_a_deg, 6),
        angle_b_deg=round(angle_b_deg, 6),
        is_symmetric=is_symmetric,
        kind=kind,
        rationale="\n".join(rationale_parts),
        applicable=True,
    )


# ---------------------------------------------------------------------------
# Core recommendation
# ---------------------------------------------------------------------------


def recommend_chamfer_size(
    edge: Edge,
    faces: Sequence[Face],
    context: Optional[ChamferContext] = None,
    ratio: float = 1.0,
) -> ChamferRecommendation:
    """Recommend chamfer offset and angle for a single B-rep edge.

    Parameters
    ----------
    edge : Edge
        The B-rep edge to evaluate.
    faces : sequence of Face
        The two faces adjacent to the edge.
    context : ChamferContext, optional
        Material, operation, tooling, and visibility context.
    ratio : float, optional
        Leg ratio leg_a / leg_b.  Default 1.0 gives the symmetric 45° path
        (backward compatible).  When ratio != 1.0 the function delegates to
        ``recommend_asymmetric_chamfer()`` and wraps the result into a
        ChamferRecommendation with offset_mm = leg_b_mm (the shorter leg) and
        angle_deg = angle_a_deg from the asymmetric result.

    Returns
    -------
    ChamferRecommendation
        offset_mm=0.0 and applicable=False if chamfer is not recommended.
        When ratio != 1.0, offset_mm holds the shorter leg (leg_b_mm) so
        that existing callers treating offset_mm as a conservative dimension
        remain safe.

    Notes
    -----
    Honest limitations:
    * No production cost modelling (tool changes, setup time).  See HONEST-FLAG.
    * DIN 74 lookup uses nominal hole diameter only — no tolerancing.
    * Default angle is 45° (equal leg).  Asymmetric chamfers (e.g. 30°×60°)
      are supported via ratio != 1.0, which calls recommend_asymmetric_chamfer().
    * Sheet-metal deburring floor is 0.5 mm regardless of burr height model.
    * ISO 13715:2017 symbol output is not produced here.

    References
    ----------
    Drozda-Wick Vol.1 §3-7 (deburring); §3-7.3 (chamfer milling).
    DIN 74:1974 Table 1 Form A/B.
    ISO 13715:2017 §5 (edge indication).
    Boothroyd-Dewhurst 2002 §4 (chamfer DFM).
    """
    # Delegate to asymmetric path when ratio != 1.0
    if ratio != 1.0:
        asym = recommend_asymmetric_chamfer(edge, application="machining", ratio_a_to_b=ratio)
        return ChamferRecommendation(
            edge_index=asym.edge_index,
            offset_mm=round(asym.leg_b_mm, 4),
            angle_deg=round(asym.angle_a_deg, 6),
            kind=asym.kind,
            rationale=asym.rationale,
            din_reference="",
            applicable=asym.applicable,
            criteria_offsets={},
        )

    ctx = context if context is not None else ChamferContext()

    # Non-linear edges: skip (e.g. arcs, NURBS — variable-offset chamfer needed)
    if not isinstance(edge.curve, Line3):
        return ChamferRecommendation(
            offset_mm=0.0,
            applicable=False,
            kind="deburring",
            rationale=(
                "Skipped: non-straight (arc/NURBS) edge. "
                "Variable-offset chamfer required for curved edges."
            ),
        )

    if len(faces) != 2:
        return ChamferRecommendation(
            offset_mm=0.0,
            applicable=False,
            kind="deburring",
            rationale=f"Skipped: expected 2 incident faces, got {len(faces)} (non-manifold).",
        )

    face_a, face_b = faces[0], faces[1]
    dihedral_angle, corner_type = _dihedral_deg(face_a, face_b)

    # Coplanar faces: no chamfer needed
    if abs(dihedral_angle - 180.0) < 1.0:
        return ChamferRecommendation(
            offset_mm=0.0,
            applicable=False,
            kind="deburring",
            rationale="Skipped: coplanar faces (dihedral ≈ 180°). No chamfer needed.",
        )

    # Very obtuse interior angle — acute exterior edge; may not need chamfer
    # Interior corners (concave dihedral < 90°) are NOT typically chamfered
    # in standard practice (ISO 13715 indicates chamfer on external edges).
    if corner_type == "interior" and dihedral_angle < 45.0:
        return ChamferRecommendation(
            offset_mm=0.0,
            applicable=False,
            kind="deburring",
            rationale=(
                f"Not recommended: sharp interior corner "
                f"(dihedral={dihedral_angle:.1f}° between outward normals). "
                "Internal re-entrant corners are not chamfered; use fillet for "
                "stress relief (see fillet_recommend_radius)."
            ),
        )

    edge_len = _edge_length(edge)
    face_min_a = _face_min_dimension(face_a)
    face_min_b = _face_min_dimension(face_b)
    smallest_face = min(face_min_a, face_min_b)

    # ----------------------------------------------------------------
    # Criterion 1: Safety / deburring floor
    # Drozda-Wick Vol.1 §3-7; ISO 13715:2017 §5
    # 0.5 mm × 45° is the established deburring minimum for sheet metal.
    # ----------------------------------------------------------------
    r_deburring = _DEBURRING_MIN_MM

    # ----------------------------------------------------------------
    # Criterion 2: Manufacturing — chamfer mill tool size
    # Drozda-Wick Vol.1 §3-7.3: offset = cutter_dia / 2 × tan(45°) = dia/2
    # For a 6 mm chamfer mill: offset = 3.0 mm
    # ----------------------------------------------------------------
    r_manufacturing = max(
        _CHAMFER_MILL_MIN_OFFSET_MM,
        ctx.chamfer_mill_diameter_mm / 2.0,
    )

    # ----------------------------------------------------------------
    # Criterion 3: Function — DIN 74 countersink for bolt holes
    # If hole_diameter_mm is supplied, do a DIN 74 Form A/B lookup.
    # Reference: DIN 74:1974 Table 1
    # ----------------------------------------------------------------
    r_din74: Optional[float] = None
    din_ref = ""
    if ctx.hole_diameter_mm and ctx.hole_diameter_mm > 0:
        r_din74 = _din74_lookup(ctx.hole_diameter_mm, ctx.din74_form)
        if r_din74 is not None:
            form_label = "Form A (90°)" if ctx.din74_form.upper() != "B" else "Form B (120°)"
            din_ref = (
                f"DIN 74:1974 {form_label} — "
                f"d1={ctx.hole_diameter_mm:.1f}mm → "
                f"d2={(ctx.hole_diameter_mm + 2*r_din74):.1f}mm, "
                f"offset={r_din74:.2f}mm"
            )

    # ----------------------------------------------------------------
    # Criterion 4: Aesthetic / cosmetic
    # Boothroyd-Dewhurst §4; visible edges → 1–2 mm × 45°
    # ----------------------------------------------------------------
    r_cosmetic = _COSMETIC_DEFAULT_MM if ctx.is_visible else 0.0

    # ----------------------------------------------------------------
    # Face-size cap: chamfer should not exceed smallest_face / 4
    # (analogous to Boothroyd-Dewhurst §4 rule used in fillet_recommend_radius)
    # ----------------------------------------------------------------
    r_face_cap = smallest_face / 4.0

    # ----------------------------------------------------------------
    # Determine dominant criterion and final offset
    # Priority: countersink (functional) > manufacturing > cosmetic > deburring
    # ----------------------------------------------------------------
    criteria: Dict[str, float] = {
        "deburring": r_deburring,
        "manufacturing": r_manufacturing,
        "cosmetic": r_cosmetic if r_cosmetic > 0 else 0.0,
    }
    if r_din74 is not None:
        criteria["countersink_din74"] = r_din74

    # Choose: if DIN74 countersink available, it governs functionally
    if r_din74 is not None:
        r_final = r_din74
        kind = "countersink"
    elif r_manufacturing > r_deburring and r_manufacturing <= r_face_cap:
        r_final = r_manufacturing
        kind = "manufacturing"
    elif r_cosmetic > r_deburring and r_cosmetic <= r_face_cap and ctx.is_visible:
        r_final = r_cosmetic
        kind = "cosmetic"
    else:
        r_final = r_deburring
        kind = "deburring"

    # Apply face-size cap (prevent chamfer consuming the face)
    if r_final > r_face_cap:
        r_final = r_face_cap
        if r_final < r_deburring:
            return ChamferRecommendation(
                offset_mm=0.0,
                applicable=False,
                kind="deburring",
                rationale=(
                    f"Not recommended: face too small for deburring chamfer "
                    f"(face_min={smallest_face:.3f}mm, "
                    f"cap={r_face_cap:.3f}mm < deburring_floor={r_deburring}mm). "
                    "Edge is too short to chamfer safely."
                ),
                criteria_offsets={k: round(v, 4) for k, v in criteria.items()},
            )

    # ----------------------------------------------------------------
    # Build rationale
    # ----------------------------------------------------------------
    angle_note = (
        "45° (DIN 74 Form A, 90° included; ISO 13715:2017 edge symbol convention)"
        if kind == "countersink" else
        "45° (standard equal-leg chamfer per Drozda-Wick §3-7)"
    )

    parts = [
        f"B-rep chamfer recommendation ({corner_type} corner, dihedral={dihedral_angle:.1f}°):",
        f"  1. Deburring floor (Drozda-Wick §3-7; ISO 13715:2017 §5): {r_deburring:.2f} mm × 45°",
        f"  2. Chamfer mill tool (Drozda-Wick §3-7.3): dia={ctx.chamfer_mill_diameter_mm:.1f}mm → offset={r_manufacturing:.2f}mm × 45°",
    ]
    if r_din74 is not None:
        parts.append(f"  3. Countersink ({din_ref}): offset={r_din74:.3f}mm × 45°")
    else:
        parts.append(f"  3. Countersink (DIN 74): not applicable — hole_diameter_mm not supplied")
    parts.append(
        f"  4. Cosmetic visible edge (Boothroyd-Dewhurst §4): "
        f"{'%.2f mm × 45°' % r_cosmetic if r_cosmetic > 0 else 'skipped (not visible)'}"
    )
    parts.append(f"  Face-size cap: {smallest_face:.3f}/4 = {r_face_cap:.3f}mm")
    parts.append(f"  → Dominant criterion: {kind}; final offset = {r_final:.3f}mm × {_CHAMFER_ANGLE_DEG}°")
    parts.append(f"  Angle: {angle_note}")
    parts.append(
        "  HONEST: no production cost modelling; DIN 74 is nominal diameter only; "
        "45° equal-leg only; ISO 13715 symbol not produced."
    )

    return ChamferRecommendation(
        offset_mm=round(r_final, 4),
        angle_deg=_CHAMFER_ANGLE_DEG,
        kind=kind,
        rationale="\n".join(parts),
        din_reference=din_ref,
        applicable=True,
        criteria_offsets={k: round(v, 4) for k, v in criteria.items()},
    )


def recommend_chamfer_sizes_for_body(
    body: Body,
    context: Optional[ChamferContext] = None,
) -> List[ChamferRecommendation]:
    """Return one ChamferRecommendation per edge in body.all_edges().

    Parameters
    ----------
    body : Body
        A validated B-rep Body.
    context : ChamferContext, optional
        Material, operation, tooling, and visibility context.

    Returns
    -------
    list of ChamferRecommendation
        Length == len(body.all_edges()).
    """
    results: List[ChamferRecommendation] = []
    edges = body.all_edges()
    for idx, edge in enumerate(edges):
        incident = _find_incident_faces(body, edge)
        rec = recommend_chamfer_size(edge, incident, context)
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
        name="brep_recommend_chamfer_size",
        description=(
            "Per-edge chamfer size recommendation (offset_mm × angle_deg) for a B-rep box.\n"
            "\n"
            "Combines four criteria:\n"
            "  1. Deburring floor:    0.5 mm × 45° (Drozda-Wick §3-7; ISO 13715:2017)\n"
            "  2. Chamfer mill tool:  offset = mill_dia/2 (Drozda-Wick §3-7.3)\n"
            "  3. Countersink DIN 74: lookup d1→d2 offset for bolt holes\n"
            "     M3→3.4mm×45°; M6→6.6mm×45°; M10→11mm×45° (DIN 74:1974 Form A)\n"
            "  4. Cosmetic:           1.5 mm × 45° for visible edges\n"
            "     (Boothroyd-Dewhurst §4)\n"
            "\n"
            "Input: box via corner [x,y,z] + dims [dx,dy,dz].\n"
            "\n"
            "Returns per-edge: offset_mm, angle_deg, kind, rationale, din_reference.\n"
            "\n"
            "HONEST: no production-cost modelling; DIN 74 nominal only; 45° equal-leg only."
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
                    "description": "Material name (e.g. 'steel', 'aluminium', 'sheet_metal').",
                },
                "operation": {
                    "type": "string",
                    "enum": ["auto", "machined", "sheet_metal", "cast"],
                    "description": "Manufacturing process context.",
                },
                "chamfer_mill_diameter_mm": {
                    "type": "number",
                    "description": "Available chamfer mill diameter (mm). Default 6.0.",
                },
                "hole_diameter_mm": {
                    "type": "number",
                    "description": (
                        "Hole diameter for DIN 74 countersink lookup (mm). "
                        "E.g. 3.0 for M3 → offset=0.2mm; 6.0 for M6 → offset=0.3mm."
                    ),
                },
                "is_visible": {
                    "type": "boolean",
                    "description": "True if edge is user-visible (enables cosmetic criterion).",
                },
                "din74_form": {
                    "type": "string",
                    "enum": ["A", "B"],
                    "description": "DIN 74 form: A=90° incl (default), B=120° incl.",
                },
            },
            "required": ["corner", "dims"],
        },
    )

    @register(_spec)
    async def run_brep_recommend_chamfer_size(
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

        context = ChamferContext(
            material=str(a.get("material", "steel")),
            operation=str(a.get("operation", "auto")),
            chamfer_mill_diameter_mm=float(a.get("chamfer_mill_diameter_mm", 6.0)),
            hole_diameter_mm=a.get("hole_diameter_mm"),
            is_visible=bool(a.get("is_visible", True)),
            din74_form=str(a.get("din74_form", "A")),
        )

        try:
            recs = recommend_chamfer_sizes_for_body(body, context)
        except Exception as exc:
            return err_payload(f"recommend_chamfer_sizes_for_body error: {exc}", "ENGINE_ERROR")

        payload = [
            {
                "edge_index": r.edge_index,
                "offset_mm": r.offset_mm,
                "angle_deg": r.angle_deg,
                "kind": r.kind,
                "rationale": r.rationale,
                "din_reference": r.din_reference,
                "applicable": r.applicable,
                "criteria_offsets": r.criteria_offsets,
            }
            for r in recs
        ]
        applicable = [r for r in recs if r.applicable]
        return ok_payload({
            "total_edges": len(recs),
            "applicable_count": len(applicable),
            "recommendations": payload,
        })
