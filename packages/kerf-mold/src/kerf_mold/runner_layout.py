"""
kerf_mold.runner_layout — Injection-mold runner system design.

Generates a balanced cold-runner tree for multi-cavity injection molds:
  - Balanced runner tree using recursive binary-split geometry
  - Runner diameter sizing per Beaumont (2007) §6.5 rule-of-thumb:
      D_runner [mm] ≥ part_weight^0.25 + 0.5,  capped at 10 mm
  - Symmetry-based "natural balance" detection (equal branch lengths)
  - Artificial-balance flag when natural balance is not achievable (e.g. row layouts)
  - Pressure-drop estimation via Hagen-Poiseuille analogy (relative, dimensionless)

SCOPE: Cold-runner systems only.  Hot-runner systems are NOT modelled.

References:
  Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §6.5.
  Menges, G., Michaeli, W., Mohren, P. (2001). *How to Make Injection Molds*, 3rd ed., §6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Beaumont 2007 §6.5 — runner diameter lookup table (part weight → D [mm])
# Interpolation table: (part_weight_g, min_diameter_mm)
# ---------------------------------------------------------------------------

_BEAUMONT_TABLE_6_5: list[tuple[float, float]] = [
    (0.0,   2.0),
    (5.0,   2.5),
    (10.0,  3.2),
    (20.0,  3.6),
    (30.0,  4.0),
    (50.0,  4.5),
    (100.0, 5.5),
    (200.0, 6.4),
    (300.0, 7.0),
    (500.0, 8.0),
    (1000.0, 9.5),
]

_BEAUMONT_D_MAX_MM = 10.0  # Beaumont 2007 §6.5: cap at 10 mm for cold runners


def beaumont_runner_diameter(part_weight_g: float) -> float:
    """
    Return minimum runner diameter [mm] for *part_weight_g* grams.

    Rule-of-thumb formula: D = part_weight^0.25 + 0.5  (Beaumont 2007 §6.5).
    Result is clamped to [2.0, 10.0] mm and cross-checked against the
    Beaumont Table 6.5 lookup; the larger of formula vs. table is returned.
    """
    if part_weight_g <= 0.0:
        raise ValueError(f"part_weight_g must be > 0, got {part_weight_g!r}")

    # Formula value
    d_formula = part_weight_g ** 0.25 + 0.5

    # Table interpolation
    d_table = _interpolate_beaumont(part_weight_g)

    d = max(d_formula, d_table, 2.0)
    return min(d, _BEAUMONT_D_MAX_MM)


def _interpolate_beaumont(w: float) -> float:
    """Linear interpolation in Beaumont Table 6.5."""
    tbl = _BEAUMONT_TABLE_6_5
    if w <= tbl[0][0]:
        return tbl[0][1]
    if w >= tbl[-1][0]:
        return tbl[-1][1]
    for i in range(len(tbl) - 1):
        w0, d0 = tbl[i]
        w1, d1 = tbl[i + 1]
        if w0 <= w <= w1:
            t = (w - w0) / (w1 - w0)
            return d0 + t * (d1 - d0)
    return tbl[-1][1]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RunnerSegment:
    """A single straight segment in the runner tree.

    Attributes:
        segment_id: unique identifier, e.g. "R0", "R1_L", "R1_R".
        start: [x, y, z] mm — upstream end (closer to sprue).
        end: [x, y, z] mm — downstream end.
        diameter_mm: cold-runner bore diameter [mm].
        length_mm: Euclidean length (auto-computed if not provided).
        is_main: True for the main runner segment (from sprue to first branch).
    """
    segment_id: str
    start: list[float]
    end: list[float]
    diameter_mm: float
    length_mm: float = 0.0
    is_main: bool = False

    def __post_init__(self):
        if self.length_mm == 0.0:
            self.length_mm = _dist(self.start, self.end)


@dataclass
class RunnerLayout:
    """
    Complete runner tree for a multi-cavity mold.

    Attributes:
        runner_segments: list of RunnerSegment objects.
        diameters: mapping {segment_id: diameter_mm}.
        balance_score: float in [0, 1].  1.0 = perfectly naturally balanced
            (all paths from sprue to gate identical length).
            <1.0 = artificial balance required (different diameters per level).
        pressure_drop_estimate: relative pressure-drop coefficient
            (dimensionless — proportional to Σ L/D^4 per Hagen-Poiseuille).
        naturally_balanced: True when every path from sprue to gate has the
            same total runner length (Beaumont 2007 §6.5 "natural balance").
        artificial_balance_required: True when naturally_balanced is False.
            Only different diameters per branch can equalise fill (Menges §6).
        warnings: list of advisory strings.
        n_cavities: number of cavities served.
        sprue_position: [x, y, z] mm of the sprue entry point.
    """
    runner_segments: list[RunnerSegment] = field(default_factory=list)
    diameters: dict[str, float] = field(default_factory=dict)
    balance_score: float = 1.0
    pressure_drop_estimate: float = 0.0
    naturally_balanced: bool = True
    artificial_balance_required: bool = False
    warnings: list[str] = field(default_factory=list)
    n_cavities: int = 0
    sprue_position: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _dist(a: list[float], b: list[float]) -> float:
    """Euclidean distance between two 2-D or 3-D points."""
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def _midpoint(a: list[float], b: list[float]) -> list[float]:
    return [(ai + bi) / 2.0 for ai, bi in zip(a, b)]


def _gate_distances_from_sprue(
    segments: list[RunnerSegment],
    sprue_pos: list[float],
    gate_positions: list[list[float]],
) -> list[float]:
    """
    Total runner path length from sprue to each gate (gate = segment end-point
    closest to each cavity).  Uses a BFS/walk on the segment graph.
    """
    # Build adjacency: point (tuple) → connected points + cumulative lengths
    adj: dict[tuple, list[tuple[tuple, float]]] = {}

    def _pt(p: list[float]) -> tuple:
        return tuple(round(v, 6) for v in p)

    for seg in segments:
        s, e = _pt(seg.start), _pt(seg.end)
        adj.setdefault(s, []).append((e, seg.length_mm))
        adj.setdefault(e, []).append((s, seg.length_mm))

    # BFS from sprue
    src = _pt(sprue_pos)
    visited: dict[tuple, float] = {src: 0.0}
    queue = [src]
    while queue:
        nxt = []
        for node in queue:
            for neighbor, w in adj.get(node, []):
                if neighbor not in visited:
                    visited[neighbor] = visited[node] + w
                    nxt.append(neighbor)
        queue = nxt

    distances = []
    for gp in gate_positions:
        g = _pt(gp)
        # find closest segment endpoint
        best = min(visited.keys(), key=lambda p: _dist(list(p), list(g)))
        distances.append(visited.get(best, 0.0))
    return distances


def _is_collinear(pts: list[list[float]], tol: float = 1.0) -> bool:
    """Return True if all points lie on a single line (within *tol* mm)."""
    if len(pts) <= 2:
        return True
    p0 = pts[0]
    p_last = pts[-1]
    dx = p_last[0] - p0[0]
    dy = p_last[1] - p0[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length < tol:
        return True  # all points nearly coincident
    ux, uy = dx / length, dy / length
    for p in pts[1:-1]:
        ex, ey = p[0] - p0[0], p[1] - p0[1]
        perp = abs(ex * (-uy) + ey * ux)
        if perp > tol:
            return False
    return True


def _build_spine(
    sprue: list[float],
    sorted_indices: list[int],
    segments: list[RunnerSegment],
    gates: list[list[float]],
    part_weights: list[float],
    diameter_fn,
    next_id_fn,
) -> None:
    """
    Build a spine-and-branch runner for collinear (row) cavity layouts.

    The main runner (spine) runs from the sprue along the cavity row axis.
    Each cavity gets a direct branch off the spine at its x-position.
    Cavities further from the sprue have longer total paths → naturally
    unbalanced.  Artificial balance (graduated diameters) is required.

    References: Beaumont 2007 §6.5; Menges 2001 §6.
    """
    # Average diameter for spine
    avg_d = diameter_fn(
        sum(part_weights[i] for i in sorted_indices) / len(sorted_indices)
    )

    centroid_z = gates[sorted_indices[0]][2]

    # Sort by distance from sprue along x-axis
    sorted_by_x = sorted(sorted_indices, key=lambda i: gates[i][0])

    # Spine goes along x-axis at sprue y-coordinate
    spine_y = sprue[1]
    spine_z = centroid_z

    current_spine = list(sprue)

    for i in sorted_by_x:
        gate = gates[i]
        branch_pt = [gate[0], spine_y, spine_z]

        # Spine segment from current spine point to next branch point
        if _dist(current_spine, branch_pt) > 1e-6:
            seg_spine = RunnerSegment(
                segment_id=next_id_fn("R"),
                start=list(current_spine),
                end=list(branch_pt),
                diameter_mm=avg_d,
                is_main=(current_spine == list(sprue)),
            )
            segments.append(seg_spine)
            current_spine = list(branch_pt)

        # Perpendicular branch: branch_pt → gate
        seg_branch = RunnerSegment(
            segment_id=next_id_fn("R"),
            start=list(branch_pt),
            end=list(gate),
            diameter_mm=diameter_fn(part_weights[i]),
        )
        segments.append(seg_branch)


def _centroid(pts: list[list[float]]) -> list[float]:
    n = len(pts)
    return [sum(p[i] for p in pts) / n for i in range(len(pts[0]))]


def _pad3(p: list[float]) -> list[float]:
    """Ensure point has 3 components (pad z=0 if 2-D)."""
    if len(p) == 2:
        return [float(p[0]), float(p[1]), 0.0]
    return [float(p[0]), float(p[1]), float(p[2])]


def _hagen_poiseuille_coeff(segments: list[RunnerSegment]) -> float:
    """
    Relative pressure-drop coefficient: Σ (L / D^4).
    Proportional to actual ΔP for a Newtonian fluid at given flow rate
    (Hagen-Poiseuille: ΔP ∝ 128·μ·Q·L / (π·D^4)).
    Returned as a dimensionless ratio [mm^{-3}].
    """
    total = 0.0
    for seg in segments:
        d = seg.diameter_mm
        if d > 0:
            total += seg.length_mm / (d ** 4)
    return total


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def generate_runner_layout(
    cavity_positions: list[list[float]],
    part_weights: list[float],
    sprue_position: list[float],
    gate_positions: Optional[list[list[float]]] = None,
) -> RunnerLayout:
    """
    Design a cold-runner tree for a multi-cavity injection mold.

    Parameters
    ----------
    cavity_positions : list of [x, y] or [x, y, z] in mm.
        Centre positions of each cavity.
    part_weights : list of float
        Shot weight per cavity [grams].  Must match len(cavity_positions).
    sprue_position : [x, y] or [x, y, z] in mm
        Entry point of the sprue (typically mold centre).
    gate_positions : optional list of [x, y, z] in mm
        Injection gate positions per cavity.  Defaults to cavity_positions.

    Returns
    -------
    RunnerLayout
        runner_segments, diameters, balance_score, pressure_drop_estimate,
        naturally_balanced, artificial_balance_required, warnings.

    Notes
    -----
    - COLD RUNNERS ONLY.  Hot-runner systems are not modelled.
    - Natural balance: every path sprue→gate identical length → balance = 1.0.
    - 4-cavity symmetric (2×2 grid) produces an X-shape with equal branches.
    - 8-cavity row layout cannot be naturally balanced; artificial balance
      (varied diameters per branch) is flagged (Beaumont 2007 §6.5, Menges §6).
    - Runner diameter formula: D = W^0.25 + 0.5 mm, capped at 10 mm
      (Beaumont 2007 §6.5 Table 6.5).

    References
    ----------
    Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §6.5.
    Menges, G., Michaeli, W., Mohren, P. (2001). *How to Make Injection Molds*,
        3rd ed., §6.
    """
    n = len(cavity_positions)
    if n == 0:
        raise ValueError("cavity_positions must be non-empty")
    if len(part_weights) != n:
        raise ValueError(
            f"part_weights length ({len(part_weights)}) must match "
            f"cavity_positions length ({n})"
        )
    if any(w <= 0 for w in part_weights):
        raise ValueError("All part_weights must be > 0 g")

    # Normalise to 3-D
    sp = _pad3(sprue_position)
    cavs = [_pad3(c) for c in cavity_positions]
    gates = [_pad3(g) for g in gate_positions] if gate_positions else cavs

    if len(gates) != n:
        raise ValueError(
            f"gate_positions length ({len(gates)}) must match cavity_positions ({n})"
        )

    warnings: list[str] = [
        "NOTE: cold-runner systems only; hot runners are not modelled."
    ]

    # Average part weight for main runner sizing
    avg_weight = sum(part_weights) / n

    # ---------------------------------------------------------------------------
    # Single cavity — trivial: one segment sprue→gate
    # ---------------------------------------------------------------------------
    if n == 1:
        seg = RunnerSegment(
            segment_id="R_main",
            start=sp,
            end=gates[0],
            diameter_mm=beaumont_runner_diameter(part_weights[0]),
            is_main=True,
        )
        layout = RunnerLayout(
            runner_segments=[seg],
            diameters={"R_main": seg.diameter_mm},
            balance_score=1.0,
            naturally_balanced=True,
            artificial_balance_required=False,
            n_cavities=1,
            sprue_position=sp,
            warnings=warnings,
        )
        layout.pressure_drop_estimate = _hagen_poiseuille_coeff(layout.runner_segments)
        return layout

    # ---------------------------------------------------------------------------
    # Build runner tree
    # ---------------------------------------------------------------------------
    segments: list[RunnerSegment] = []
    seg_counter = [0]

    def _next_id(prefix: str = "R") -> str:
        seg_counter[0] += 1
        return f"{prefix}{seg_counter[0]}"

    def _build_tree(
        src: list[float],
        cavity_indices: list[int],
        level: int,
    ) -> None:
        """
        Recursively build a balanced binary tree from *src* to the sub-cavities
        at *cavity_indices*.
        """
        if len(cavity_indices) == 1:
            idx = cavity_indices[0]
            seg = RunnerSegment(
                segment_id=_next_id("R"),
                start=list(src),
                end=list(gates[idx]),
                diameter_mm=beaumont_runner_diameter(part_weights[idx]),
                is_main=(level == 0),
            )
            segments.append(seg)
            return

        # Split indices into two balanced halves
        mid = len(cavity_indices) // 2
        left_idx = cavity_indices[:mid]
        right_idx = cavity_indices[mid:]

        # Branch point = centroid of all cavity gates in this subtree
        branch_pt = _centroid([gates[i] for i in cavity_indices])

        # Segment from src to branch point (sub-runner)
        d_branch = beaumont_runner_diameter(
            sum(part_weights[i] for i in cavity_indices) / len(cavity_indices)
        )
        seg = RunnerSegment(
            segment_id=_next_id("R"),
            start=list(src),
            end=list(branch_pt),
            diameter_mm=d_branch,
            is_main=(level == 0),
        )
        segments.append(seg)

        # Recurse
        _build_tree(branch_pt, left_idx, level + 1)
        _build_tree(branch_pt, right_idx, level + 1)

    # Sort cavity indices so tree is constructed in geometric order
    sorted_indices = sorted(range(n), key=lambda i: (gates[i][0], gates[i][1]))

    if _is_collinear(gates):
        # Spine layout: runner runs as a spine with branches for each cavity.
        # Paths from sprue to far cavities are longer → unbalanced.
        _build_spine(sp, sorted_indices, segments, gates, part_weights,
                     beaumont_runner_diameter, _next_id)
    else:
        _build_tree(sp, sorted_indices, 0)

    # ---------------------------------------------------------------------------
    # Balance score: std-dev of path lengths, normalised
    # ---------------------------------------------------------------------------
    path_lengths = _gate_distances_from_sprue(segments, sp, gates)
    if len(path_lengths) > 1 and max(path_lengths) > 0:
        mean_len = sum(path_lengths) / len(path_lengths)
        std_len = math.sqrt(
            sum((l - mean_len) ** 2 for l in path_lengths) / len(path_lengths)
        )
        cv = std_len / mean_len  # coefficient of variation
        balance_score = max(0.0, 1.0 - cv)
    else:
        balance_score = 1.0

    naturally_balanced = balance_score >= 0.99
    artificial_balance_required = not naturally_balanced

    if artificial_balance_required:
        warnings.append(
            f"Artificial balance required: path lengths vary "
            f"(max={max(path_lengths):.1f} mm, min={min(path_lengths):.1f} mm). "
            "Use graduated runner diameters per Beaumont 2007 §6.5 and Menges §6 "
            "to equalise pressure drop across all cavities."
        )
    if n not in {1, 2, 4, 8, 16}:
        warnings.append(
            f"Odd cavity count ({n}): symmetric natural balance may not be achievable. "
            "Verify runner layout manually."
        )

    diameters = {seg.segment_id: seg.diameter_mm for seg in segments}
    pd_estimate = _hagen_poiseuille_coeff(segments)

    return RunnerLayout(
        runner_segments=segments,
        diameters=diameters,
        balance_score=round(balance_score, 6),
        pressure_drop_estimate=round(pd_estimate, 6),
        naturally_balanced=naturally_balanced,
        artificial_balance_required=artificial_balance_required,
        warnings=warnings,
        n_cavities=n,
        sprue_position=sp,
    )
