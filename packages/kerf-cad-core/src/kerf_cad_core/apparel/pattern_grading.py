"""
kerf_cad_core.apparel.pattern_grading — Multi-size pattern grading.

Implements landmark-based garment pattern grading: distributing incremental
size differences across pattern pieces according to grading rules.

References
----------
Aldrich, W. (2015). "Metric Pattern Cutting for Women's Wear", 6th ed.
    Wiley-Blackwell, Oxford. (ISBN 978-1-4051-9848-9)
    §2 "Pattern grading by measurement increments."
    ("Aldrich 6e")

Mullet, K. (2015). "Concepts of Pattern Grading", 2nd ed.
    Fairchild Books, New York. (ISBN 978-1-60901-629-5)
    Part II "Grade rules for standard measurements."
    ("Mullet 2e")

Honest caveats
--------------
- Grading is applied as a piecewise-linear interpolation from the base size
  outward.  True production grading tools (e.g. Gerber AccuMark, Lectra
  Modaris) use per-landmark rule tables that allow non-uniform distribution;
  this implementation supports the same via per-landmark GradingRule objects.
- Landmark matching uses exact ID matching; no fuzzy or nearest-point fallback
  is implemented.  Unmapped vertices are interpolated from the two nearest
  mapped landmarks along the outline.
- Size names are compared as strings in the order supplied by the caller.
  Standard size sequences (XS<S<M<L<XL) are the caller's responsibility.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GradingRule:
    """Per-landmark grading increment from one size to the adjacent size.

    Attributes
    ----------
    landmark_id : str
        Identifier matching a named point on the pattern.
        Standard names follow Aldrich 6e §2 and ISO 8559-3:2018 Table 1:
        ``'shoulder_neck'``, ``'underarm'``, ``'waist_left'``,
        ``'waist_right'``, ``'hip_left'``, ``'hip_right'``, etc.
    x_grade_cm_per_size : float
        Horizontal increment in cm per size step (positive = outward).
        Aldrich 6e Table 2.1 typical values: shoulder_neck ≈ 0.2 cm,
        underarm ≈ 0.5 cm, waist ≈ 0.5 cm, hip ≈ 0.5 cm.
    y_grade_cm_per_size : float
        Vertical increment in cm per size step.
    """

    landmark_id: str
    x_grade_cm_per_size: float
    y_grade_cm_per_size: float


@dataclass
class GradedSizes:
    """Multi-size pattern set produced by :func:`grade_pattern`.

    Attributes
    ----------
    base_size : str
        Name of the base (reference) size, e.g. ``'M'``.
    sizes : list[str]
        Ordered list of all sizes including the base, e.g.
        ``['XS', 'S', 'M', 'L', 'XL']``.
    patterns : dict[str, list[list[tuple[float, float]]]]
        ``size → list of piece outlines``.  Each outline is an ordered list
        of (x_mm, y_mm) vertices forming a closed polygon.
    """

    base_size: str
    sizes: list[str]
    patterns: dict[str, list[list[tuple[float, float]]]]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _outline_perimeter(outline: list[tuple[float, float]]) -> float:
    """Return total perimeter length of a closed polygon."""
    n = len(outline)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        x0, y0 = outline[i]
        x1, y1 = outline[(i + 1) % n]
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def _arc_lengths(outline: list[tuple[float, float]]) -> list[float]:
    """Return cumulative arc-length array for a closed polygon (length n+1)."""
    arcs = [0.0]
    for i in range(len(outline)):
        x0, y0 = outline[i]
        x1, y1 = outline[(i + 1) % len(outline)]
        arcs.append(arcs[-1] + math.hypot(x1 - x0, y1 - y0))
    return arcs


def _grade_piece(
    piece: list[tuple[float, float]],
    landmarks: dict[str, int],
    rules: list[GradingRule],
    step: float,
) -> list[tuple[float, float]]:
    """Apply grading to a single pattern piece.

    Parameters
    ----------
    piece : list[tuple[float, float]]
        Vertex list (x_mm, y_mm).
    landmarks : dict[str, int]
        Mapping of landmark_id → vertex index in *piece*.
    rules : list[GradingRule]
        Per-landmark increment rules.
    step : float
        Number of size steps from base (negative = smaller, positive = larger).

    Returns
    -------
    list[tuple[float, float]]
        Graded vertex list.
    """
    n = len(piece)
    if n == 0:
        return []

    # Build per-vertex displacement from rules
    displacements: dict[int, tuple[float, float]] = {}
    for rule in rules:
        if rule.landmark_id in landmarks:
            idx = landmarks[rule.landmark_id]
            dx = rule.x_grade_cm_per_size * step * 10.0   # cm → mm
            dy = rule.y_grade_cm_per_size * step * 10.0
            displacements[idx] = (dx, dy)

    if not displacements:
        # No landmarks mapped: apply uniform scale from centroid
        # (Mullet 2e fallback: scale uniformly for unmapped pieces)
        cx = sum(v[0] for v in piece) / n
        cy = sum(v[1] for v in piece) / n
        # Approximate uniform grade as a fraction of perimeter
        perim = _outline_perimeter(piece)
        scale = 1.0 + (step * 5.0 * 10.0) / max(perim, 1e-9)
        return [(cx + (v[0] - cx) * scale, cy + (v[1] - cy) * scale) for v in piece]

    # Interpolate displacements for non-landmark vertices by arc-length
    arc = _arc_lengths(piece)
    total = arc[-1]
    if total < 1e-9:
        return list(piece)

    # Collect (arc_position, dx, dy) for all landmarks
    anchors: list[tuple[float, float, float]] = []
    for idx, (dx, dy) in sorted(displacements.items()):
        anchors.append((arc[idx], dx, dy))

    # Wrap-around: duplicate first/last for closed curve interpolation
    if anchors:
        first_a, first_dx, first_dy = anchors[0]
        last_a, last_dx, last_dy = anchors[-1]
        # Add wraparound anchors
        anchors_ext = (
            [(last_a - total, last_dx, last_dy)]
            + anchors
            + [(first_a + total, first_dx, first_dy)]
        )
    else:
        anchors_ext = anchors

    graded: list[tuple[float, float]] = []
    for i, (x, y) in enumerate(piece):
        s = arc[i]
        dx_i, dy_i = _interp_displacement(s, anchors_ext)
        graded.append((x + dx_i, y + dy_i))
    return graded


def _interp_displacement(
    s: float,
    anchors: list[tuple[float, float, float]],
) -> tuple[float, float]:
    """Linearly interpolate (dx, dy) at arc-position *s* from *anchors*."""
    if len(anchors) == 0:
        return (0.0, 0.0)
    if len(anchors) == 1:
        return (anchors[0][1], anchors[0][2])

    # Find bracketing anchors
    for i in range(len(anchors) - 1):
        s0, dx0, dy0 = anchors[i]
        s1, dx1, dy1 = anchors[i + 1]
        if s0 <= s <= s1:
            if abs(s1 - s0) < 1e-12:
                return (dx0, dy0)
            t = (s - s0) / (s1 - s0)
            return (dx0 + t * (dx1 - dx0), dy0 + t * (dy1 - dy0))

    # Extrapolation: clamp to last
    return (anchors[-1][1], anchors[-1][2])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def grade_pattern(
    base_pattern: object,
    rules: list[GradingRule],
    target_sizes: list[str],
    base_size: str = "M",
    landmarks: dict[str, int] | None = None,
) -> GradedSizes:
    """Grade a base pattern to multiple target sizes.

    **Honest flag**: uses piecewise-linear landmark interpolation.  Commercial
    grading systems (Gerber AccuMark, Lectra Modaris) support curved grade
    lines and rule-tree inheritance; this implementation supports only linear
    grade rules as described in Aldrich 6e §2 and Mullet 2e Part II.

    The base pattern must expose a ``pieces`` attribute that is a list of piece
    outlines (list of (x_mm, y_mm) tuples).  Alternatively, a bare list of
    outlines is accepted directly.

    Parameters
    ----------
    base_pattern : object
        Pattern object with a ``.pieces`` attribute (list of outlines), or a
        plain list of outlines.
    rules : list[GradingRule]
        Per-landmark grading rules.  Each rule specifies the x/y increment
        per size step from the base size.
    target_sizes : list[str]
        Sizes to generate, e.g. ``['XS', 'S', 'M', 'L', 'XL']``.  The
        ``base_size`` string is inserted if absent.  Order determines the
        step index (base_size → step 0).
    base_size : str
        Name of the reference size, default ``'M'``.
    landmarks : dict[str, int] | None
        Optional mapping of landmark_id → vertex index in each piece.  If
        ``None``, an empty dict is used (triggers uniform-scale fallback for
        each piece).

    Returns
    -------
    GradedSizes
        All sizes including the base.
    """
    # Extract raw outlines
    if isinstance(base_pattern, list):
        base_pieces: list[list[tuple[float, float]]] = base_pattern
    elif hasattr(base_pattern, "pieces"):
        base_pieces = base_pattern.pieces  # type: ignore[union-attr]
    else:
        raise ValueError(
            "base_pattern must be a list of outlines or have a .pieces attribute"
        )

    lm: dict[str, int] = landmarks or {}

    # Build size ordering with base at step 0
    all_sizes = list(target_sizes)
    if base_size not in all_sizes:
        all_sizes.append(base_size)
    all_sizes = sorted(set(all_sizes), key=lambda s: all_sizes.index(s) if s in all_sizes else 0)

    # Determine step index for each size relative to base
    try:
        base_idx = all_sizes.index(base_size)
    except ValueError:
        base_idx = 0

    patterns: dict[str, list[list[tuple[float, float]]]] = {}
    for i, size in enumerate(all_sizes):
        step = float(i - base_idx)
        if step == 0.0:
            patterns[size] = [list(piece) for piece in base_pieces]
        else:
            patterns[size] = [_grade_piece(piece, lm, rules, step) for piece in base_pieces]

    return GradedSizes(
        base_size=base_size,
        sizes=all_sizes,
        patterns=patterns,
    )


def pattern_area(outline: list[tuple[float, float]]) -> float:
    """Return the signed area of a closed polygon (mm²) via shoelace formula.

    Positive for counter-clockwise orientation.
    """
    n = len(outline)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = outline[i]
        x1, y1 = outline[(i + 1) % n]
        area += (x0 * y1) - (x1 * y0)
    return area / 2.0
