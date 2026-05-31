"""
kerf_mold.flow_length_check
============================
Flow-length-to-wall-thickness (L/T) ratio checker for injection-mold cavity
features — the primary short-shot risk indicator.

Theory
------
The L/T ratio is the ratio of the maximum flow path length (L, mm) from the
gate to the farthest cavity extremity, divided by the nominal wall thickness
(T, mm) of the flow path cross-section.  Each thermoplastic material has an
empirical maximum L/T limit above which the melt front cools and freezes before
filling the cavity — producing a "short shot".

Material limits (Beaumont 2007 Table 4.2; Menges 2001 §6.2.1)
--------------------------------------------------------------
These are representative upper-bound L/T ratios for injection pressure of
~140 MPa (20,000 psi) and wall thickness in the 2–4 mm range.  Limits are
somewhat sensitive to injection pressure, melt temperature, and gate design;
the values below are conservative mid-range handbook figures.

  Material  | L/T limit  | Source
  --------- | ---------- | -------
  ABS       | 150        | Beaumont 2007 Table 4.2
  PC        | 220        | Beaumont 2007 Table 4.2
  PP        | 300        | Beaumont 2007 Table 4.2
  PA66      | 250        | Beaumont 2007 Table 4.2
  POM       | 200        | Beaumont 2007 Table 4.2
  PMMA      | 180        | Beaumont 2007 Table 4.2

Risk thresholds
---------------
  ≤ 80 % of limit → "safe"       (comfortable margin)
  80–100 % of limit → "caution"  (borderline; verify process conditions)
  > 100 % of limit → "short_shot" (predicted short shot; reduce L or increase T)

Recommended minimum thickness
------------------------------
  recommended_min_thickness_mm = flow_length_mm / (material_lt_limit × safety_factor)

where safety_factor = 0.85 (15 % safety margin applied to material limit), so:

  recommended_min_thickness_mm = flow_length_mm / (material_lt_limit × 0.85)

This ensures the operating L/T ratio stays below 85 % of the published limit.

Honest caveat
-------------
This is a rule-based L/T check only.  It does NOT perform:
  - Hagen-Poiseuille or Hele-Shaw viscous pressure-drop simulation.
  - Thermal analysis of the melt-front cooling during fill.
  - Sensitivity to injection pressure, melt temperature, or gate geometry.
  - Analysis of multi-gate or complex 3-D flow paths.
For a full fill simulation use Moldflow, Moldex3D, or SigmaSoft.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007, §4.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.2.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Material L/T limit table  (Beaumont 2007 Table 4.2 + Menges 2001 §6.2.1)
# ---------------------------------------------------------------------------

#: Maximum flow-length-to-wall-thickness ratios by material.
#: Source: Beaumont J.P. "Runner and Gating Design Handbook", 2007, Table 4.2;
#: cross-checked against Menges 2001 §6.2.1.
#: Keys are case-insensitive uppercase material grade strings.
MATERIAL_LT_LIMITS: Dict[str, float] = {
    "ABS":   150.0,
    "PC":    220.0,
    "PP":    300.0,
    "PA66":  250.0,
    "POM":   200.0,
    "PMMA":  180.0,
}

# Risk threshold fractions
_SAFE_THRESHOLD: float = 0.80    # ≤ 80 % of limit → safe
_CAUTION_THRESHOLD: float = 1.00  # 80–100 % → caution; > 100 % → short_shot

# Safety factor applied when computing recommended_min_thickness_mm
# (15 % margin below material limit, i.e. target ≤ 85 % of limit)
_SAFETY_FACTOR: float = 0.85


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class FlowFeature:
    """A single cavity flow feature to be checked.

    Parameters
    ----------
    id : str
        Unique identifier for this feature (e.g. "rib_01", "thin_wall_A").
    flow_length_mm : float
        Distance (mm) from the gate to the farthest point in this feature's
        flow path.  Must be > 0.
    wall_thickness_mm : float
        Nominal wall (cross-section) thickness (mm) through which the melt
        must flow.  Must be > 0.
    material_grade : str
        Material grade key; must match a key in MATERIAL_LT_LIMITS (case-
        insensitive).  E.g. "ABS", "PP", "PC".
    """

    id: str
    flow_length_mm: float
    wall_thickness_mm: float
    material_grade: str

    def __post_init__(self) -> None:
        if self.flow_length_mm <= 0.0:
            raise ValueError(
                f"FlowFeature '{self.id}': flow_length_mm must be > 0, "
                f"got {self.flow_length_mm}"
            )
        if self.wall_thickness_mm <= 0.0:
            raise ValueError(
                f"FlowFeature '{self.id}': wall_thickness_mm must be > 0, "
                f"got {self.wall_thickness_mm}"
            )


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class FlowLengthReport:
    """Report produced by compute_flow_length_check.

    Attributes
    ----------
    feature_results : list[dict]
        Per-feature results.  Each dict contains:
          - "id"                    : feature identifier
          - "flow_length_mm"        : input flow length (mm)
          - "wall_thickness_mm"     : input wall thickness (mm)
          - "material_grade"        : normalised material grade
          - "lt_ratio"              : L/T = flow_length_mm / wall_thickness_mm
          - "material_lt_limit"     : handbook limit for this material
          - "utilisation_fraction"  : lt_ratio / material_lt_limit
          - "risk"                  : "safe" | "caution" | "short_shot"
          - "detail"                : human-readable explanation string

    worst_feature_id : str
        ID of the feature with the highest utilisation fraction (closest to or
        beyond the material limit).

    recommended_min_thickness_mm : float
        The recommended minimum wall thickness for the worst-case feature:
          flow_length_mm / (material_lt_limit × safety_factor=0.85).
        Provides 15 % safety margin below the material L/T limit.

    honest_caveat : str
        Plain-language statement of what this check does NOT do.
    """

    feature_results: List[dict]
    worst_feature_id: str
    recommended_min_thickness_mm: float
    honest_caveat: str = field(default=(
        "L/T ratio check only (Beaumont 2007 Table 4.2 + Menges 2001 §6.2.1). "
        "Does NOT simulate viscous pressure drop, melt-front temperature, "
        "injection speed sensitivity, or multi-gate flow balance. "
        "For a full fill simulation use Moldflow, Moldex3D, or SigmaSoft."
    ))


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def compute_flow_length_check(
    features: List[FlowFeature],
    material_db_override: Optional[Dict[str, float]] = None,
) -> FlowLengthReport:
    """Compute L/T ratio per cavity feature and assess short-shot risk.

    For each feature the function calculates:
        lt_ratio = flow_length_mm / wall_thickness_mm

    and compares it against the material's handbook limit
    (Beaumont 2007 Table 4.2; Menges 2001 §6.2.1).  Risk is classified as:

      "safe"       — lt_ratio ≤ 0.80 × limit
      "caution"    — 0.80 × limit < lt_ratio ≤ limit
      "short_shot" — lt_ratio > limit

    The recommended minimum wall thickness for the worst-case feature is:
        flow_length_mm / (material_lt_limit × 0.85)

    Parameters
    ----------
    features : list of FlowFeature
        One or more cavity features to evaluate.  Must be non-empty.
    material_db_override : dict, optional
        Overrides (or extends) MATERIAL_LT_LIMITS.  Keys are upper-case
        material grade strings; values are L/T limit floats.  Useful for
        unusual grades or proprietary materials.

    Returns
    -------
    FlowLengthReport

    Raises
    ------
    ValueError
        If ``features`` is empty or a FlowFeature has an unrecognised material
        grade and no override is provided.
    """
    if not features:
        raise ValueError("features must be a non-empty list of FlowFeature")

    # Build effective material limit lookup
    material_db: Dict[str, float] = {**MATERIAL_LT_LIMITS}
    if material_db_override:
        material_db.update(
            {k.upper(): v for k, v in material_db_override.items()}
        )

    feature_results: List[dict] = []
    worst_utilisation: float = -1.0
    worst_feature_id: str = features[0].id
    worst_flow_length: float = features[0].flow_length_mm
    worst_limit: float = 1.0  # will be overwritten

    for feat in features:
        grade_key = feat.material_grade.upper()
        if grade_key not in material_db:
            raise ValueError(
                f"FlowFeature '{feat.id}': unknown material_grade "
                f"'{feat.material_grade}'. "
                f"Known grades: {sorted(material_db.keys())}. "
                f"Pass material_db_override to add custom grades."
            )
        limit = material_db[grade_key]
        lt_ratio = feat.flow_length_mm / feat.wall_thickness_mm
        utilisation = lt_ratio / limit

        if utilisation <= _SAFE_THRESHOLD:
            risk = "safe"
            detail = (
                f"L/T={lt_ratio:.1f} is {utilisation*100:.1f}% of the "
                f"{grade_key} limit ({limit:.0f}) — comfortable margin."
            )
        elif utilisation <= _CAUTION_THRESHOLD:
            risk = "caution"
            detail = (
                f"L/T={lt_ratio:.1f} is {utilisation*100:.1f}% of the "
                f"{grade_key} limit ({limit:.0f}) — borderline; "
                f"verify injection pressure, melt temperature, and gate size."
            )
        else:
            risk = "short_shot"
            detail = (
                f"L/T={lt_ratio:.1f} exceeds the {grade_key} limit "
                f"({limit:.0f}) by {(utilisation-1.0)*100:.1f}% — "
                f"short shot predicted. Increase wall thickness or add "
                f"a gate closer to this feature."
            )

        feature_results.append({
            "id": feat.id,
            "flow_length_mm": round(feat.flow_length_mm, 4),
            "wall_thickness_mm": round(feat.wall_thickness_mm, 4),
            "material_grade": grade_key,
            "lt_ratio": round(lt_ratio, 4),
            "material_lt_limit": limit,
            "utilisation_fraction": round(utilisation, 6),
            "risk": risk,
            "detail": detail,
        })

        if utilisation > worst_utilisation:
            worst_utilisation = utilisation
            worst_feature_id = feat.id
            worst_flow_length = feat.flow_length_mm
            worst_limit = limit

    # Recommended minimum thickness for the worst-case flow length
    # Target operating L/T at 85 % of the material limit (15 % safety margin)
    recommended_min_thickness_mm = worst_flow_length / (worst_limit * _SAFETY_FACTOR)

    return FlowLengthReport(
        feature_results=feature_results,
        worst_feature_id=worst_feature_id,
        recommended_min_thickness_mm=round(recommended_min_thickness_mm, 4),
    )
