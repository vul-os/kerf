"""
kerf_mold.warpage_index
=======================
Heuristic warpage-risk index (0–100) for injection-moulded parts.

Theory — Beaumont 2007 §10 + Menges 2001 §8
--------------------------------------------
Warpage in injection-moulded parts arises from differential shrinkage driven by
four primary factors:

1.  Wall-thickness uniformity (Beaumont 2007 §10.2; Menges 2001 §8.2)
    Non-uniform walls cool at different rates: thick sections stay molten longer
    and shrink more; thin sections freeze early.  The differential shrinkage
    across adjacent sections creates a bending moment that warps the part.
    This is the single largest driver of warpage for most commodity plastics.
    Perfect uniformity (100 %) → minimum differential; highly non-uniform
    (< 60 %) → severe risk.

2.  Gate location (Beaumont 2007 §10.3; Menges 2001 §8.4)
    Gate location determines the direction of melt flow and hence the
    orientation of frozen-in molecular/fibre alignment.  A centred gate
    produces a near-symmetric filling pattern and minimises the flow-induced
    residual-stress differential.  Edge, corner, or unbalanced gates introduce
    strong flow-directionality gradients; the in-flow vs cross-flow shrinkage
    anisotropy (especially for semi-crystalline and glass-filled grades) is the
    dominant driver for those parts.

3.  Polymer grade (Beaumont 2007 §10.4; Menges 2001 §8.3 Table 8.2)
    Amorphous polymers (PC, ABS, PMMA) shrink nearly isotropically and have
    relatively low and predictable shrinkage (0.4–0.8 %).  Semi-crystalline
    polymers (PP, PA66, POM) undergo additional volumetric collapse on
    crystallisation, greatly amplifying differential shrinkage.  Glass-filled
    grades (GF-PA66, GF-PP) exhibit extreme in-flow vs cross-flow shrinkage
    anisotropy (Menges 2001 Table 8.2: in-flow ≈ 0.2 %, cross-flow ≈ 0.8–1.0 %)
    making warpage nearly certain without careful gate/runner balance.

4.  Cooling uniformity / post-eject cooling time (Beaumont 2007 §10.5;
    Menges 2001 §8.5)
    A short post-ejection cooling time means the part is still above the
    heat-distortion temperature (HDT) and continues to creep and warp.
    For semi-crystalline grades crystallisation also continues post-ejection.
    Mold temperature above the polymer's recommended range also increases
    residence-time-at-temperature and hence differential shrinkage.

Scoring model
-------------
The 0–100 index is a weighted sum of four penalty sub-scores:

  Sub-score          Max points   Primary reference
  ─────────────────  ──────────   ─────────────────────────────────────
  Wall uniformity    30           Beaumont 2007 §10.2; Menges 2001 §8.2
  Gate location      25           Beaumont 2007 §10.3; Menges 2001 §8.4
  Polymer grade      20           Beaumont 2007 §10.4; Menges 2001 §8.3
  Post-eject cooling 15           Beaumont 2007 §10.5; Menges 2001 §8.5
  Mold temperature   10           Beaumont 2007 §10.6; Menges 2001 §8.6
  ─────────────────  ──────────
  Total              100

Risk thresholds (Beaumont 2007 §10.1 rule-of-thumb):
  0–24   → "low"    (acceptable; minor tool adjustment may be needed)
  25–49  → "medium" (elevated; design or process change recommended)
  50–74  → "high"   (significant; likely visible warpage in production)
  75–100 → "severe" (near-certain reject; major redesign required)

Honest caveats
--------------
This is a first-principles SCREENING TOOL only.  Real warpage prediction
requires finite-element simulation of the entire filling + packing + cooling
cycle (Moldflow, Moldex3D, or SigmaSoft 3D Warp module):
  • Orientation-dependent shrinkage tensors are not computed here.
  • Part geometry (planar vs deep-drawn vs box) is not considered.
  • Packing pressure, injection speed, and hold time are not inputs.
  • Runner imbalance, multiple gates, and sequential valve gating are not
    modelled.
  • Residual-stress relaxation and creep post-ejection are not modelled.
Use the index to flag high-risk designs early in the design review stage.
Validate with Moldflow/Moldex3D FEM before production tooling.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §10 — Warpage Analysis (root-cause diagnostics).
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §8 — Post-mold shrinkage and warpage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Polymer grade database — warpage-risk contribution
# (Beaumont 2007 §10.4 + Menges 2001 §8.3 Table 8.2)
# ---------------------------------------------------------------------------

#: Warpage sub-score (0–20) for each supported polymer grade.
#: Key: canonical grade name (upper-case); Value: (score, description).
#: Amorphous polymers score low (uniform isotropic shrinkage, 0.4–0.8 %).
#: Semi-crystalline and glass-filled grades score high (anisotropic shrinkage).
_POLYMER_SCORES: Dict[str, Tuple[float, str]] = {
    # Amorphous — low warpage risk
    "PC":       (5.0,  "PC — amorphous; isotropic shrinkage 0.4–0.7 %; low warpage tendency (Menges 2001 Table 8.2)"),
    "ABS":      (7.0,  "ABS — amorphous; isotropic shrinkage 0.4–0.7 %; low warpage tendency (Menges 2001 Table 8.2)"),
    "PMMA":     (6.0,  "PMMA — amorphous; isotropic shrinkage 0.3–0.6 %; low warpage tendency"),
    "PS":       (6.0,  "PS — amorphous; isotropic shrinkage 0.4–0.7 %; low warpage tendency"),
    "ABS-PC":   (6.0,  "ABS-PC blend — amorphous; isotropic shrinkage 0.4–0.7 %; low warpage tendency"),
    # Semi-crystalline — medium warpage risk
    "PP":       (14.0, "PP — semi-crystalline; shrinkage 1.0–2.5 %; significant crystallisation-driven differential shrinkage (Beaumont 2007 §10.4)"),
    "PA66":     (13.0, "PA66 — semi-crystalline; shrinkage 0.8–1.5 %; moisture-uptake affects post-mold dimensions (Menges 2001 §8.3)"),
    "PA6":      (13.0, "PA6 — semi-crystalline; shrinkage 0.8–1.5 %; similar to PA66"),
    "POM":      (15.0, "POM (acetal) — semi-crystalline; shrinkage 1.8–2.5 %; high crystallinity → elevated warpage risk (Menges 2001 §8.3)"),
    "HDPE":     (16.0, "HDPE — semi-crystalline; shrinkage 1.5–3.5 %; highest isotropic shrinkage among commodity plastics"),
    "PET":      (13.0, "PET — semi-crystalline; shrinkage 1.0–2.5 %; orientation-sensitive"),
    # Glass-fibre-filled — severe anisotropic warpage risk
    "GF-PA66":  (20.0, "GF-PA66 (glass-filled nylon) — extreme in-flow vs cross-flow shrinkage anisotropy (Menges 2001 Table 8.2: in-flow ≈ 0.2 %, cross-flow ≈ 0.8–1.0 %); near-certain warpage without FEM-guided gate design"),
    "GF-PP":    (19.0, "GF-PP (glass-filled PP) — severe anisotropic shrinkage; high warpage risk (Menges 2001 §8.3)"),
    "GF-PA6":   (19.0, "GF-PA6 (glass-filled nylon 6) — severe anisotropic shrinkage; high warpage risk"),
    "GF-PBT":   (18.0, "GF-PBT (glass-filled polyester) — severe anisotropic shrinkage; high warpage risk"),
    "LCP":      (17.0, "LCP (liquid crystal polymer) — extreme molecular orientation; expert filling simulation required"),
}

#: Fallback score for unknown polymers (medium risk with caveat).
_POLYMER_FALLBACK_SCORE: float = 10.0
_POLYMER_FALLBACK_DESC: str = (
    "Unknown polymer — assigned medium risk score. "
    "Consult the Menges 2001 §8.3 Table 8.2 shrinkage range for your specific grade."
)

# ---------------------------------------------------------------------------
# Gate-location penalty (Beaumont 2007 §10.3)
# ---------------------------------------------------------------------------

#: Warpage sub-score (0–25) per gate location.
#: Centred gate → balanced fill → minimum differential residual stress.
#: Corner / unbalanced → severe flow-direction gradients.
_GATE_SCORES: Dict[str, Tuple[float, str]] = {
    "centered":    (3.0,  "Centred gate — near-symmetric fill; minimal flow-direction residual-stress gradient (Beaumont 2007 §10.3)"),
    "edge":        (14.0, "Edge gate — strong flow directionality; moderate in-flow vs cross-flow differential (Beaumont 2007 §10.3)"),
    "corner":      (22.0, "Corner gate — severe fill asymmetry; large flow-direction residual-stress differential; elevated warpage risk (Beaumont 2007 §10.3 + Menges 2001 §8.4)"),
    "unbalanced":  (25.0, "Unbalanced gate(s) — multiple gates with unequal flow paths; weld-line + differential-shrinkage compound warpage; highest risk category (Beaumont 2007 §10.3)"),
}

#: Default when gate_location not recognised.
_GATE_FALLBACK_SCORE: float = 14.0
_GATE_FALLBACK_DESC: str = (
    "Unrecognised gate location — assigned edge-gate risk score. "
    "Supported values: 'centered', 'edge', 'corner', 'unbalanced'."
)

# ---------------------------------------------------------------------------
# Risk-level thresholds
# ---------------------------------------------------------------------------

_RISK_THRESHOLDS: List[Tuple[float, str]] = [
    (0.0,  "low"),
    (25.0, "medium"),
    (50.0, "high"),
    (75.0, "severe"),
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class WarpageSpec:
    """Input specification for the warpage-index computation.

    Attributes
    ----------
    wall_thickness_uniformity_pct : float
        How uniform the part wall thickness is, expressed as a percentage.
        100 = perfectly uniform (all walls the same thickness);
        50 = the thickest wall is twice the thinnest (or equivalent).
        Must be in the range [0, 100].
        Rule-of-thumb: for warpage control, keep variation within ±25 % of the
        nominal wall (i.e., uniformity_pct ≥ 80 %).  Ref: Beaumont 2007 §10.2.
    gate_location : str
        Qualitative gate-location category.  One of:
        ``"centered"`` — gate at or near the geometric centre of the projected
            cavity area; produces the most balanced fill front.
        ``"edge"`` — gate at one edge of the part (most common for side-gated
            cold-runner tools).
        ``"corner"`` — gate at a corner or extremity of the part; worst
            single-gate filling balance.
        ``"unbalanced"`` — multiple gates with significantly different flow
            lengths, or a single eccentric gate producing highly asymmetric fill.
    polymer_grade : str
        Polymer material grade.  Supported values (case-insensitive):
        amorphous (low risk): ``"PC"``, ``"ABS"``, ``"PMMA"``, ``"PS"``,
            ``"ABS-PC"``
        semi-crystalline (medium risk): ``"PP"``, ``"PA66"``, ``"PA6"``,
            ``"POM"``, ``"HDPE"``, ``"PET"``
        glass-filled (high risk): ``"GF-PA66"``, ``"GF-PP"``, ``"GF-PA6"``,
            ``"GF-PBT"``, ``"LCP"``
        Unknown grades receive a medium fallback score with a warning caveat.
    post_eject_cooling_time_s : float
        Time (seconds) between part ejection from the mold and the part being
        placed on a flat cool surface (or otherwise constrained against further
        warp).  Longer times allow the part to reach dimensional stability
        before any distortion force is applied.  Must be ≥ 0.
        Beaumont 2007 §10.5: for most rigid amorphous parts, 30 s is adequate;
        for semi-crystalline or glass-filled grades, 60–120 s is recommended.
    mold_temp_C : float
        Mold (coolant) temperature [°C].  Must be ≥ 0.
        A higher mold temperature slows solidification, increases residual
        stress annealing time (which can reduce warpage), but also extends
        cycle time and — for semi-crystalline grades — promotes higher
        crystallinity and its associated larger volumetric shrinkage.
        Recommended ranges vary strongly by polymer; this heuristic uses a
        single scale relative to a "safe" mid-range of 40–80 °C.
    """

    wall_thickness_uniformity_pct: float  # 0–100, 100 = perfectly uniform
    gate_location: str                    # "centered"|"edge"|"corner"|"unbalanced"
    polymer_grade: str
    post_eject_cooling_time_s: float      # seconds ≥ 0
    mold_temp_C: float                    # °C ≥ 0

    def __post_init__(self) -> None:
        if not (0.0 <= self.wall_thickness_uniformity_pct <= 100.0):
            raise ValueError(
                f"wall_thickness_uniformity_pct must be in [0, 100], "
                f"got {self.wall_thickness_uniformity_pct}"
            )
        if self.post_eject_cooling_time_s < 0.0:
            raise ValueError(
                f"post_eject_cooling_time_s must be >= 0, "
                f"got {self.post_eject_cooling_time_s}"
            )
        if self.mold_temp_C < 0.0:
            raise ValueError(
                f"mold_temp_C must be >= 0, got {self.mold_temp_C}"
            )


@dataclass
class WarpageIndexReport:
    """Output of compute_warpage_index.

    Attributes
    ----------
    warpage_index : float
        Heuristic warpage risk score in [0, 100].
        0 = ideal (no predicted warpage); 100 = severe warpage expected.
    risk_level : str
        Qualitative risk classification:
        ``"low"`` (0–24), ``"medium"`` (25–49), ``"high"`` (50–74),
        ``"severe"`` (75–100).
    primary_warp_driver : str
        Name of the input factor that contributes most to the index.
        One of: ``"wall_uniformity"``, ``"gate_location"``,
        ``"polymer_grade"``, ``"cooling_time"``, ``"mold_temperature"``.
    mitigation_suggestions : list[str]
        Ordered list of actionable mitigation recommendations.
        Empty when warpage_index ≤ 10 (negligible risk).
        The suggestions are prioritised by their sub-score contribution.
    honest_caveat : str
        Plain-language statement of model limitations.
    sub_scores : dict[str, float]
        Breakdown of each factor's contribution to the total index.
        Keys: ``"wall_uniformity"``, ``"gate_location"``,
        ``"polymer_grade"``, ``"cooling_time"``, ``"mold_temperature"``.
    """

    warpage_index: float
    risk_level: str
    primary_warp_driver: str
    mitigation_suggestions: List[str]
    honest_caveat: str
    sub_scores: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Caveat template
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Heuristic warpage-risk index based on Beaumont 2007 §10 (Warpage Analysis) "
    "and Menges 2001 §8 (Post-mold shrinkage). "
    "This is a SCREENING TOOL only — score ±15 pts uncertainty is normal. "
    "Real warpage prediction requires full filling + packing + cooling FEM "
    "simulation (Moldflow, Moldex3D, or SigmaSoft 3D Warp): orientation-dependent "
    "shrinkage tensors, part geometry, packing pressure, injection speed, hold time, "
    "runner imbalance, multiple gates, and residual-stress relaxation are NOT modelled "
    "here. Use this index to flag high-risk designs early in the design review stage. "
    "Validate with Moldflow/Moldex3D FEM before production tooling commit."
)


# ---------------------------------------------------------------------------
# Sub-score functions
# ---------------------------------------------------------------------------

def _wall_uniformity_score(uniformity_pct: float) -> float:
    """Wall-thickness uniformity → 0–30 pts.

    Based on Beaumont 2007 §10.2 + Menges 2001 §8.2:
    - 100 % uniform → 0 pts (no differential cooling)
    - 80 % (±25 % variation) → ~6 pts (acceptable range)
    - 60 % (±67 % variation) → ~18 pts (elevated risk)
    - 0 % (no constraint) → 30 pts (worst case)

    Piecewise linear:
      u ∈ [80, 100] → score = (100−u)/20 × 6        (0→6 pts)
      u ∈ [50, 80)  → score = 6 + (80−u)/30 × 14    (6→20 pts)
      u ∈ [0, 50)   → score = 20 + (50−u)/50 × 10   (20→30 pts)
    """
    u = float(uniformity_pct)
    if u >= 80.0:
        return (100.0 - u) / 20.0 * 6.0
    elif u >= 50.0:
        return 6.0 + (80.0 - u) / 30.0 * 14.0
    else:
        return 20.0 + (50.0 - u) / 50.0 * 10.0


def _cooling_time_score(cooling_time_s: float) -> float:
    """Post-eject cooling time → 0–15 pts.

    Based on Beaumont 2007 §10.5 + Menges 2001 §8.5:
    - ≥ 120 s → 0 pts  (well above typical HDT stabilisation window)
    - 30 s   → ~7 pts  (adequate for amorphous; borderline for semi-cryst.)
    - 5 s    → ~13 pts (part above HDT; likely to warp on ejection surface)
    - 0 s    → 15 pts  (immediate constraint / stacking → severe warp risk)

    Exponential decay: score = 15 × exp(−t/40)
    Rationale: most cooling benefit accrues in the first 40 s (characteristic
    time based on Menges 2001 §8.5 HDT stabilisation).
    """
    import math
    t = max(0.0, float(cooling_time_s))
    return 15.0 * math.exp(-t / 40.0)


def _mold_temp_score(mold_temp_C: float, polymer_grade: str) -> float:
    """Mold temperature deviation from polymer-specific optimum → 0–10 pts.

    Based on Beaumont 2007 §10.6 + Menges 2001 §8.6:
    Each polymer has a "safe" recommended mold-temperature range.  Operating
    outside this range (either too cold — frozen-in stress — or too hot —
    extended residence time + crystallisation for semi-cryst.) increases
    warpage risk.

    Simplified heuristic:
    - Within [T_low, T_high]: score = 0
    - Below T_low (cold mold): score = min(10, (T_low - T_actual) / T_low × 10)
    - Above T_high: score = min(10, (T_actual - T_high) / 50 × 10)
      (50 °C above recommended → maximum penalty; higher temps extend
      residual-stress window and promote crystallinity for semi-cryst.)
    """
    T = float(mold_temp_C)
    grade_upper = polymer_grade.strip().upper()

    # Recommended mold-temperature ranges [°C] — Menges 2001 §5.4 Table 5.3
    # Amorphous polymers
    _MOLD_TEMP_RANGES: Dict[str, Tuple[float, float]] = {
        "PC":      (70.0, 120.0),
        "ABS":     (40.0,  80.0),
        "PMMA":    (40.0,  80.0),
        "PS":      (20.0,  60.0),
        "ABS-PC":  (60.0, 100.0),
        # Semi-crystalline
        "PP":      (20.0,  80.0),
        "PA66":    (70.0, 120.0),
        "PA6":     (50.0, 100.0),
        "POM":     (60.0, 120.0),
        "HDPE":    (20.0,  60.0),
        "PET":     (10.0,  30.0),
        # Glass-filled — typically same base polymer recommendation
        "GF-PA66": (70.0, 120.0),
        "GF-PP":   (40.0,  80.0),
        "GF-PA6":  (50.0, 100.0),
        "GF-PBT":  (60.0, 120.0),
        "LCP":     (60.0, 100.0),
    }

    t_low, t_high = _MOLD_TEMP_RANGES.get(grade_upper, (40.0, 80.0))

    if t_low <= T <= t_high:
        return 0.0
    elif T < t_low:
        # Too cold — frozen-in orientation stress
        deviation = t_low - T
        return min(10.0, deviation / max(t_low, 1.0) * 10.0)
    else:
        # Too hot — extended crystallisation window for semi-cryst.
        deviation = T - t_high
        return min(10.0, deviation / 50.0 * 10.0)


# ---------------------------------------------------------------------------
# Mitigation logic
# ---------------------------------------------------------------------------

def _build_mitigations(
    sub_scores: Dict[str, float],
    spec: "WarpageSpec",
    polymer_desc: str,
    gate_desc: str,
) -> List[str]:
    """Return prioritised mitigation suggestions based on sub-score magnitudes."""

    suggestions: List[str] = []

    # Sort contributors by score descending
    ranked = sorted(sub_scores.items(), key=lambda kv: kv[1], reverse=True)

    for factor, score in ranked:
        if score < 1.0:
            continue

        if factor == "wall_uniformity" and score > 2.0:
            u = spec.wall_thickness_uniformity_pct
            if u < 80.0:
                suggestions.append(
                    f"Wall uniformity is {u:.0f} % — redesign to keep wall thickness variation "
                    f"within ±25 % of nominal (target ≥ 80 %). "
                    f"Transition zones, ribs, and bosses should taper gradually "
                    f"(Beaumont 2007 §10.2; Menges 2001 §8.2)."
                )
            if u < 60.0:
                suggestions.append(
                    "Consider adding uniform ribs or coring-out thick sections rather than "
                    "varying wall thickness; this is the single highest-impact warpage mitigation."
                )

        elif factor == "gate_location" and score > 3.0:
            if spec.gate_location in ("corner", "unbalanced"):
                suggestions.append(
                    f"Gate location '{spec.gate_location}' produces a highly asymmetric fill "
                    f"front. Move gate to the geometric centroid of the projected cavity area, "
                    f"or use a balanced multi-gate system with equal flow lengths "
                    f"(Beaumont 2007 §10.3 + mold_check_runner_balance)."
                )
            elif spec.gate_location == "edge":
                suggestions.append(
                    "Edge gate introduces in-flow vs cross-flow shrinkage differential. "
                    "Consider moving to a fan or film gate to distribute flow direction, "
                    "or relocate to part centroid (Beaumont 2007 §10.3)."
                )

        elif factor == "polymer_grade" and score > 5.0:
            grade_upper = spec.polymer_grade.strip().upper()
            if grade_upper.startswith("GF-") or grade_upper == "LCP":
                suggestions.append(
                    f"Glass-filled/LCP grades have extreme in-flow vs cross-flow shrinkage "
                    f"anisotropy. Warpage FEM simulation (Moldflow/Moldex3D) is mandatory "
                    f"before production tooling. Consider unfilled or mineral-filled alternatives "
                    f"if tight flatness tolerances are required (Menges 2001 §8.3 Table 8.2)."
                )
            elif grade_upper in ("PP", "POM", "HDPE"):
                suggestions.append(
                    f"{grade_upper} is semi-crystalline with high shrinkage anisotropy. "
                    f"Ensure uniform wall thickness, balanced runner system, and adequate "
                    f"post-ejection cooling time to reduce crystallisation-driven warpage "
                    f"(Menges 2001 §8.3)."
                )
            elif grade_upper in ("PA66", "PA6"):
                suggestions.append(
                    f"{grade_upper} (nylon) absorbs moisture post-ejection, causing dimensional "
                    f"change. Control humidity during cooling phase and consider annealing in "
                    f"water/oil at 80–100 °C (Menges 2001 §8.3)."
                )

        elif factor == "cooling_time" and score > 3.0:
            t = spec.post_eject_cooling_time_s
            suggestions.append(
                f"Post-ejection cooling time of {t:.1f} s is short. "
                f"Increase to ≥ 60 s for semi-crystalline / glass-filled grades, "
                f"or ≥ 30 s for amorphous grades, before placing part on a flat surface. "
                f"Use a cooling jig/fixture if rapid cycle time is required "
                f"(Beaumont 2007 §10.5)."
            )

        elif factor == "mold_temperature" and score > 2.0:
            t = spec.mold_temp_C
            suggestions.append(
                f"Mold temperature {t:.0f} °C is outside the recommended range for "
                f"{spec.polymer_grade}. Review mold temperature controller settings; "
                f"excessively cold molds freeze in residual orientation stress; "
                f"excessively hot molds extend crystallisation window for semi-cryst. grades "
                f"(Menges 2001 §8.6)."
            )

    # Always suggest FEM if index > 50
    total = sum(sub_scores.values())
    if total > 50.0:
        suggestions.append(
            "Index > 50: full FEM warpage simulation (Moldflow, Moldex3D, or SigmaSoft) "
            "is strongly recommended before committing to production tooling. "
            "Identify high-warp regions from the orientation-tensor shrinkage map."
        )

    return suggestions


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_warpage_index(spec: WarpageSpec) -> WarpageIndexReport:
    """Compute the heuristic warpage index for an injection-moulded part.

    Parameters
    ----------
    spec : WarpageSpec
        Part and process specification.

    Returns
    -------
    WarpageIndexReport
        Warpage index (0–100), risk level, primary driver, mitigations,
        sub-score breakdown, and honest caveat.

    Raises
    ------
    ValueError
        If spec contains out-of-range values (validated in WarpageSpec.__post_init__).

    Notes
    -----
    Scoring formula (Beaumont 2007 §10 + Menges 2001 §8):

        index = w_wall + w_gate + w_poly + w_cool + w_temp

    where each sub-score is capped at its respective maximum:
        w_wall  ∈ [0, 30]  — wall-thickness non-uniformity
        w_gate  ∈ [0, 25]  — gate-location penalty
        w_poly  ∈ [0, 20]  — polymer shrinkage character
        w_cool  ∈ [0, 15]  — insufficient post-ejection cooling
        w_temp  ∈ [0, 10]  — mold temperature out of recommended range
    """
    # --- Sub-score: wall uniformity (0–30) ---
    w_wall = _wall_uniformity_score(spec.wall_thickness_uniformity_pct)
    w_wall = max(0.0, min(30.0, w_wall))

    # --- Sub-score: gate location (0–25) ---
    gate_key = spec.gate_location.strip().lower()
    gate_score, gate_desc = _GATE_SCORES.get(
        gate_key, (_GATE_FALLBACK_SCORE, _GATE_FALLBACK_DESC)
    )
    w_gate = max(0.0, min(25.0, gate_score))

    # --- Sub-score: polymer grade (0–20) ---
    grade_key = spec.polymer_grade.strip().upper()
    poly_score, poly_desc = _POLYMER_SCORES.get(
        grade_key, (_POLYMER_FALLBACK_SCORE, _POLYMER_FALLBACK_DESC)
    )
    w_poly = max(0.0, min(20.0, poly_score))

    # --- Sub-score: post-ejection cooling time (0–15) ---
    w_cool = _cooling_time_score(spec.post_eject_cooling_time_s)
    w_cool = max(0.0, min(15.0, w_cool))

    # --- Sub-score: mold temperature (0–10) ---
    w_temp = _mold_temp_score(spec.mold_temp_C, grade_key)
    w_temp = max(0.0, min(10.0, w_temp))

    # --- Total index ---
    index = w_wall + w_gate + w_poly + w_cool + w_temp
    index = round(max(0.0, min(100.0, index)), 2)

    # --- Risk level ---
    risk_level = "low"
    for threshold, level in _RISK_THRESHOLDS:
        if index >= threshold:
            risk_level = level

    # --- Primary driver (highest sub-score) ---
    sub_scores: Dict[str, float] = {
        "wall_uniformity":  round(w_wall, 3),
        "gate_location":    round(w_gate, 3),
        "polymer_grade":    round(w_poly, 3),
        "cooling_time":     round(w_cool, 3),
        "mold_temperature": round(w_temp, 3),
    }
    primary_driver = max(sub_scores, key=lambda k: sub_scores[k])

    # --- Mitigation suggestions ---
    mitigations = _build_mitigations(sub_scores, spec, poly_desc, gate_desc)

    return WarpageIndexReport(
        warpage_index=index,
        risk_level=risk_level,
        primary_warp_driver=primary_driver,
        mitigation_suggestions=mitigations,
        honest_caveat=_HONEST_CAVEAT,
        sub_scores=sub_scores,
    )
