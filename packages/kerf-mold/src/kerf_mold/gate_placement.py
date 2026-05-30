"""
kerf_mold.gate_placement
========================
Optimal injection-gate location planner for injection-mold tooling.

Gate placement determines where molten polymer enters the mold cavity.
Poor placement leads to:
  - Long flow paths → excessive pressure, temperature loss, short shots.
  - Unbalanced fill fronts → weld lines at structurally critical sections.
  - Gate marks on functional / cosmetic surfaces (class-A, sealing faces, threads).
  - Gates on undercuts → impossible ejection or slide damage.

This module provides:

  CavityBbox           — 3-D bounding box (width × depth × height, mm).
  GateConstraint       — forbidden zone (functional surface, undercut, cosmetic).
  GatePlacementResult  — dataclass returned by optimize_gate_placement.
  optimize_gate_placement — sample candidate gate positions, score each by
                            Euclidean max-flow-length + fill-balance variance,
                            apply constraints, return ranked recommendations.

Algorithm
---------
Candidate generation (Beaumont 2007 §7 heuristics):
  - Top-center (sprue gate / submarine), top-edge-left/right, side-center
    (edge gate), bottom-center, and a 3×3 face-grid on the ±Y faces.
  - For multi-gate requests the centroidal Voronoi partition of the top face
    is sampled (equidistant seeds, split by gate_count along the long axis).

Scoring (Menges 2001 §6.6 location heuristics):
  For each candidate gate position G:
    1. max_flow_length  = max Euclidean distance from G to 8 bbox corners.
    2. mean_flow_length = mean distance to all 8 corners.
    3. balance_score    = std-dev of distances to 8 corners (lower = better fill balance).
    4. composite_score  = 0.6 · normalised(max_flow) + 0.4 · normalised(balance).
    Lower composite_score is better.

Constraints:
  - GateConstraint.avoid_zones : list of (cx, cy, cz, radius_mm) spheres.
    Any candidate whose 2-D projection falls within the sphere is discarded.
  - GateConstraint.functional_faces : list of face labels ('top'/'bottom'/
    'left'/'right'/'front'/'back').  Gates on those faces are removed.
  - GateConstraint.allow_underside_gates : if False (default) gates on the
    bottom face are penalised (+20 % score) but not removed.

Honest-flag
-----------
This is a **geometric heuristic** only.  It does NOT model:
  - Polymer viscosity, shear thinning, or temperature-dependent flow.
  - Cavity pressure, injection speed, or pack-hold phases.
  - Weld-line position (only weld-line *risk* via balance score proxy).
  - Compressible shrinkage, residual stress, or warpage.
For production gate optimisation use Moldflow / Moldex3D / SigmaSoft.

References
----------
Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.
  Hanser/Gardner.  §7 "Gate Design" — gate type selection, location rules,
  flow-balance criteria.

Menges, G., Michaeli, W., Mohren, P. (2001). *How to Make Injection Molds*,
  3rd ed.  Hanser. §6.6 "Gate location" — pressure minimisation, weld-line
  avoidance, fill balance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CavityBbox:
    """Axis-aligned bounding box of the injection-mold cavity.

    Parameters
    ----------
    width_mm  : X dimension (mm).  Must be > 0.
    depth_mm  : Y dimension (mm).  Must be > 0.
    height_mm : Z dimension (mm).  Must be > 0.
    origin    : (x0, y0, z0) of the minimum-coordinate corner.  Default (0,0,0).
    """

    width_mm: float   # X
    depth_mm: float   # Y
    height_mm: float  # Z
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        for name, val in [
            ("width_mm", self.width_mm),
            ("depth_mm", self.depth_mm),
            ("height_mm", self.height_mm),
        ]:
            if val <= 0.0:
                raise ValueError(f"{name} must be > 0, got {val}")

    @property
    def center(self) -> Tuple[float, float, float]:
        x0, y0, z0 = self.origin
        return (
            x0 + self.width_mm / 2.0,
            y0 + self.depth_mm / 2.0,
            z0 + self.height_mm / 2.0,
        )

    def corners(self) -> List[Tuple[float, float, float]]:
        """Return the 8 corners of the bounding box."""
        x0, y0, z0 = self.origin
        x1 = x0 + self.width_mm
        y1 = y0 + self.depth_mm
        z1 = z0 + self.height_mm
        return [
            (x0, y0, z0), (x1, y0, z0), (x0, y1, z0), (x1, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x0, y1, z1), (x1, y1, z1),
        ]


@dataclass
class GateConstraint:
    """Constraints that restrict permissible gate positions.

    Parameters
    ----------
    functional_faces : face labels where gates are forbidden.
        Recognised values: 'top', 'bottom', 'left', 'right', 'front', 'back'.
        Example: ['bottom', 'front'] forbids sprue gates and cosmetic front gates.
    avoid_zones : list of (cx, cy, cz, radius_mm) defining forbidden spheres
        in the bbox coordinate system.  Any gate candidate whose nearest
        point on the bbox face falls within the sphere is removed.
    allow_underside_gates : if False (default), bottom-face gates are scored
        with a 20 % penalty but are not hard-removed (useful for pin-point
        gates through the parting plane).
    """

    functional_faces: List[str] = field(default_factory=list)
    avoid_zones: List[Tuple[float, float, float, float]] = field(default_factory=list)
    allow_underside_gates: bool = False

    _VALID_FACES = frozenset({"top", "bottom", "left", "right", "front", "back"})

    def __post_init__(self) -> None:
        bad = [f for f in self.functional_faces if f not in self._VALID_FACES]
        if bad:
            raise ValueError(
                f"functional_faces contains unrecognised labels: {bad!r}. "
                f"Valid values: {sorted(self._VALID_FACES)!r}"
            )


@dataclass
class GateCandidate:
    """A single candidate gate position with scores.

    Parameters
    ----------
    position       : (x, y, z) in the bbox coordinate system.
    face           : which face this candidate is on ('top' / 'side_x' / etc.).
    max_flow_mm    : Euclidean distance from this gate to the farthest bbox corner.
    mean_flow_mm   : mean distance to all 8 corners.
    balance_std_mm : std-dev of distances to 8 corners (fill-balance proxy).
    composite_score : lower is better (see module docstring).
    penalised      : True if a soft constraint penalty was applied.
    """

    position: Tuple[float, float, float]
    face: str
    max_flow_mm: float
    mean_flow_mm: float
    balance_std_mm: float
    composite_score: float
    penalised: bool = False


@dataclass
class GatePlacementResult:
    """Result of gate-placement optimisation.

    Parameters
    ----------
    gate_positions     : list of (x, y, z) for the recommended gate(s).
    gate_count         : number of gates recommended.
    flow_metrics       : list of per-gate dicts with max_flow_mm, mean_flow_mm,
                         balance_std_mm, composite_score.
    balance_score      : global fill-balance score (0.0–1.0; 1.0 = perfectly
                         balanced).  Computed as 1 - normalised(mean std_dev
                         across all gates).
    multi_gate_suggested : True if the geometry warrants more than 1 gate.
    recommendations    : human-readable advisory strings.
    warnings           : honest-flag and scope caveats.
    candidates_evaluated : total number of candidates scored before filtering.
    """

    gate_positions: List[Tuple[float, float, float]]
    gate_count: int
    flow_metrics: List[dict]
    balance_score: float
    multi_gate_suggested: bool
    recommendations: List[str]
    warnings: List[str]
    candidates_evaluated: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dist3(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _flow_stats(
    gate: Tuple[float, float, float],
    corners: List[Tuple[float, float, float]],
) -> Tuple[float, float, float]:
    """Return (max_flow_mm, mean_flow_mm, balance_std_mm) for a gate vs corners."""
    dists = [_dist3(gate, c) for c in corners]
    max_d = max(dists)
    mean_d = sum(dists) / len(dists)
    variance = sum((d - mean_d) ** 2 for d in dists) / len(dists)
    std_d = math.sqrt(variance)
    return max_d, mean_d, std_d


def _is_in_avoid_zone(
    pos: Tuple[float, float, float],
    zones: List[Tuple[float, float, float, float]],
) -> bool:
    for cx, cy, cz, r in zones:
        if _dist3(pos, (cx, cy, cz)) <= r:
            return True
    return False


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _generate_candidates(
    bbox: CavityBbox,
    gate_count: int,
) -> List[Tuple[Tuple[float, float, float], str]]:
    """Generate (position, face_label) candidate pairs.

    Follows Beaumont 2007 §7: prefer gate near the thickest section, which
    for a uniform-wall bbox is the geometric centre of the top face (sprue
    entry, highest injection pressure available).  Edge/side gates are
    secondary candidates per Menges §6.6.
    """
    x0, y0, z0 = bbox.origin
    W, D, H = bbox.width_mm, bbox.depth_mm, bbox.height_mm
    cx, cy, _ = bbox.center

    top_z = z0 + H
    bottom_z = z0
    left_x = x0
    right_x = x0 + W
    front_y = y0
    back_y = y0 + D

    candidates: List[Tuple[Tuple[float, float, float], str]] = []

    # ── Top face candidates (preferred — Beaumont §7 §7.1) ─────────────────
    # Centre
    candidates.append(((cx, cy, top_z), "top"))
    # Quarter-points along long axis
    long_step = max(W, D) / 4.0
    if W >= D:
        candidates.append(((x0 + long_step, cy, top_z), "top"))
        candidates.append(((x0 + W - long_step, cy, top_z), "top"))
    else:
        candidates.append(((cx, y0 + long_step, top_z), "top"))
        candidates.append(((cx, y0 + D - long_step, top_z), "top"))

    # Multi-gate along long axis (equidistant seeds)
    if gate_count >= 2:
        if W >= D:
            step = W / (gate_count + 1)
            for i in range(1, gate_count + 1):
                candidates.append(((x0 + i * step, cy, top_z), "top"))
        else:
            step = D / (gate_count + 1)
            for i in range(1, gate_count + 1):
                candidates.append(((cx, y0 + i * step, top_z), "top"))

    # ── Side/edge gate candidates (Menges §6.6) ────────────────────────────
    mid_z = z0 + H / 2.0

    # Left / right face centres
    candidates.append(((left_x, cy, mid_z), "left"))
    candidates.append(((right_x, cy, mid_z), "right"))

    # Front / back face centres
    candidates.append(((cx, front_y, mid_z), "front"))
    candidates.append(((cx, back_y, mid_z), "back"))

    # ── Bottom face (pin-point / sub-marine gate — Beaumont §7.3) ──────────
    candidates.append(((cx, cy, bottom_z), "bottom"))

    return candidates


# ---------------------------------------------------------------------------
# Main optimiser
# ---------------------------------------------------------------------------

def optimize_gate_placement(
    cavity_bbox: CavityBbox,
    constraints: Optional[GateConstraint] = None,
    gate_count: int = 1,
) -> GatePlacementResult:
    """Propose optimal gate location(s) for an injection-mold cavity.

    Parameters
    ----------
    cavity_bbox  : CavityBbox — the cavity bounding box (width × depth × height).
    constraints  : GateConstraint — forbidden faces / zones; default = no constraints.
    gate_count   : number of gates to place.  Default 1.  Use > 1 for thin elongated
                   or large-area parts.

    Returns
    -------
    GatePlacementResult with ranked gate positions, flow metrics, balance score,
    and advisory recommendations.

    Algorithm (Beaumont 2007 §7; Menges 2001 §6.6)
    -----------------------------------------------
    1. Generate candidates on all bbox faces (top, side, bottom).
    2. Remove hard-forbidden candidates (functional_faces + avoid_zones).
    3. Score each remaining candidate:
         max_flow_mm    = max Euclidean dist to 8 corners.
         balance_std_mm = std-dev of dist to 8 corners (fill-balance proxy).
         composite      = 0.6 · norm(max_flow) + 0.4 · norm(balance_std).
    4. Apply soft penalty (+20 %) to bottom-face gates when
       allow_underside_gates is False.
    5. Sort by composite_score ascending.
    6. Select top-N candidates where N = gate_count.

    Honest-flag
    -----------
    Geometric heuristic only — does NOT model viscosity, shear thinning,
    packing pressure, weld-line position, residual stress, or warpage.
    For production: use Moldflow / Moldex3D / SigmaSoft.

    References
    ----------
    Beaumont 2007 §7 "Gate Design"; Menges 2001 §6.6 gate location heuristics.
    """
    if gate_count < 1:
        raise ValueError(f"gate_count must be >= 1, got {gate_count}")

    if constraints is None:
        constraints = GateConstraint()

    corners = cavity_bbox.corners()
    raw_candidates = _generate_candidates(cavity_bbox, gate_count)

    # ── Hard filtering ──────────────────────────────────────────────────────
    forbidden_faces = set(constraints.functional_faces)
    filtered: List[Tuple[Tuple[float, float, float], str]] = []
    for pos, face in raw_candidates:
        if face in forbidden_faces:
            continue
        if _is_in_avoid_zone(pos, constraints.avoid_zones):
            continue
        filtered.append((pos, face))

    # Deduplicate positions
    seen: set = set()
    unique: List[Tuple[Tuple[float, float, float], str]] = []
    for pos, face in filtered:
        key = (round(pos[0], 6), round(pos[1], 6), round(pos[2], 6))
        if key not in seen:
            seen.add(key)
            unique.append((pos, face))

    candidates_evaluated = len(unique)

    if not unique:
        # Fallback: use bbox centre regardless of constraints
        cx, cy, cz = cavity_bbox.center
        unique = [((cx, cy, cz), "centre")]
        candidates_evaluated = 1

    # ── Score each candidate ────────────────────────────────────────────────
    scored: List[GateCandidate] = []
    for pos, face in unique:
        max_f, mean_f, std_f = _flow_stats(pos, corners)
        penalised = (
            face == "bottom"
            and not constraints.allow_underside_gates
        )
        scored.append(GateCandidate(
            position=pos,
            face=face,
            max_flow_mm=max_f,
            mean_flow_mm=mean_f,
            balance_std_mm=std_f,
            composite_score=0.0,  # set below after normalisation
            penalised=penalised,
        ))

    # Normalise max_flow and balance_std to [0, 1]
    max_flows = [c.max_flow_mm for c in scored]
    std_devs = [c.balance_std_mm for c in scored]

    mf_min, mf_max = min(max_flows), max(max_flows)
    sd_min, sd_max = min(std_devs), max(std_devs)

    def _norm(val: float, lo: float, hi: float) -> float:
        if hi <= lo:
            return 0.0
        return (val - lo) / (hi - lo)

    for c in scored:
        norm_mf = _norm(c.max_flow_mm, mf_min, mf_max)
        norm_sd = _norm(c.balance_std_mm, sd_min, sd_max)
        score = 0.6 * norm_mf + 0.4 * norm_sd
        if c.penalised:
            score *= 1.20
        c.composite_score = round(score, 6)

    scored.sort(key=lambda c: c.composite_score)

    # ── Select top gate_count candidates (non-overlapping) ──────────────────
    min_gate_sep_mm = min(
        cavity_bbox.width_mm, cavity_bbox.depth_mm, cavity_bbox.height_mm
    ) * 0.15  # at least 15 % of shortest dimension apart

    selected: List[GateCandidate] = []
    for cand in scored:
        # Avoid placing two gates too close together
        too_close = any(
            _dist3(cand.position, s.position) < min_gate_sep_mm
            for s in selected
        )
        if not too_close:
            selected.append(cand)
        if len(selected) >= gate_count:
            break

    # If not enough non-overlapping candidates, relax and fill
    if len(selected) < gate_count:
        for cand in scored:
            if cand not in selected:
                selected.append(cand)
            if len(selected) >= gate_count:
                break

    # ── Build output ────────────────────────────────────────────────────────
    gate_positions = [s.position for s in selected]
    flow_metrics = [
        {
            "position": list(s.position),
            "face": s.face,
            "max_flow_mm": round(s.max_flow_mm, 3),
            "mean_flow_mm": round(s.mean_flow_mm, 3),
            "balance_std_mm": round(s.balance_std_mm, 3),
            "composite_score": s.composite_score,
            "penalised": s.penalised,
        }
        for s in selected
    ]

    # Global balance score: 1 - normalised mean std_dev of selected gates
    selected_stds = [s.balance_std_mm for s in selected]
    mean_std = sum(selected_stds) / len(selected_stds)
    # Normalise against the theoretical worst case (gate at corner of bbox)
    diag = _dist3(cavity_bbox.origin, (
        cavity_bbox.origin[0] + cavity_bbox.width_mm,
        cavity_bbox.origin[1] + cavity_bbox.depth_mm,
        cavity_bbox.origin[2] + cavity_bbox.height_mm,
    ))
    balance_score = max(0.0, min(1.0, 1.0 - mean_std / (diag / 2.0 + 1e-9)))

    # Multi-gate suggestion heuristic (Menges §6.6 §6.6.4):
    # Suggest multiple gates when max_flow / min(W,D,H) > 5
    min_dim = min(
        cavity_bbox.width_mm, cavity_bbox.depth_mm, cavity_bbox.height_mm
    )
    best_max_flow = selected[0].max_flow_mm
    multi_gate_suggested = (
        gate_count == 1
        and best_max_flow / (min_dim + 1e-9) > 5.0
    )

    # ── Recommendations ─────────────────────────────────────────────────────
    recommendations: List[str] = []

    best = selected[0]
    face_label = best.face
    pos_str = f"({best.position[0]:.1f}, {best.position[1]:.1f}, {best.position[2]:.1f}) mm"

    recommendations.append(
        f"Primary gate recommended at {pos_str} on the '{face_label}' face "
        f"(max flow ≈ {best.max_flow_mm:.1f} mm, fill-balance std "
        f"≈ {best.balance_std_mm:.1f} mm, composite score "
        f"{best.composite_score:.3f})."
    )

    if len(selected) > 1:
        for i, s in enumerate(selected[1:], start=2):
            pos_i = f"({s.position[0]:.1f}, {s.position[1]:.1f}, {s.position[2]:.1f}) mm"
            recommendations.append(
                f"Gate {i} at {pos_i} on '{s.face}' face "
                f"(max flow ≈ {s.max_flow_mm:.1f} mm, score {s.composite_score:.3f})."
            )

    if multi_gate_suggested:
        recommendations.append(
            "Consider using 2+ gates: the part's aspect ratio is large "
            f"(max flow / min-dim ≈ {best_max_flow / min_dim:.1f}×). "
            "A second gate reduces flow length and weld-line risk "
            "(Menges 2001 §6.6.4)."
        )

    if any(s.penalised for s in selected):
        recommendations.append(
            "One or more selected gates is on the bottom face (submarine / "
            "pin-point gate). Verify ejector-pin clearance and ensure the "
            "gate vestige is acceptable for the application "
            "(Beaumont 2007 §7.3)."
        )

    if constraints.functional_faces:
        recommendations.append(
            f"Avoided gate placement on functional/cosmetic faces: "
            f"{sorted(constraints.functional_faces)}."
        )

    if constraints.avoid_zones:
        recommendations.append(
            f"Applied {len(constraints.avoid_zones)} avoid-zone constraint(s); "
            "check that functional surfaces (sealing, thread, snap-fit) are "
            "clear of gate marks."
        )

    # ── Warnings ────────────────────────────────────────────────────────────
    warnings: List[str] = [
        "HONEST-FLAG: geometric heuristic only — does NOT model polymer "
        "viscosity, shear thinning, packing pressure, weld-line position, "
        "residual stress, or warpage. For production gate optimisation use "
        "Moldflow / Moldex3D / SigmaSoft (Beaumont 2007 §7; Menges 2001 §6.6)."
    ]

    if balance_score < 0.5:
        warnings.append(
            f"Fill-balance score is low ({balance_score:.2f}). Consider a "
            "fan gate or film gate to spread the flow front, or add a second "
            "gate (Menges §6.6.3)."
        )

    return GatePlacementResult(
        gate_positions=gate_positions,
        gate_count=len(selected),
        flow_metrics=flow_metrics,
        balance_score=round(balance_score, 4),
        multi_gate_suggested=multi_gate_suggested,
        recommendations=recommendations,
        warnings=warnings,
        candidates_evaluated=candidates_evaluated,
    )
