"""
kerf_cad_core.apparel.seam_layout — Seam types, allowances, and stitch geometry.

Models construction seam specifications and computes outward-offset seam
allowance polygons for flat garment pattern pieces.

References
----------
Aldrich, W. (2015). "Metric Pattern Cutting for Women's Wear", 6th ed.
    Wiley-Blackwell, Oxford.  §1 "Seam allowances and stitching lines."
    ("Aldrich 6e")

Mullet, K. (2015). "Concepts of Pattern Grading", 2nd ed.
    Fairchild Books, New York.
    ("Mullet 2e")

ISO 4916:1991 — Textiles. Seam types. Classification and terminology.
    Defines seam type codes: ISO 1 (plain), ISO 4 (flat-felled), etc.

ASTM D6193-16 — Standard Practice for Stitches and Seams.
    Classifies stitch types (301 lock, 504 overlock, 401 chainstitch) and
    seam types (SSa plain, LSa flat-felled, etc.).

Honest caveats
--------------
- The outward polygon offset is computed using a simple per-vertex outward
  normal (miter) method.  This can produce self-intersecting polygons at
  convex corners with large allowances.  Production CAD tools (Gerber, Lectra)
  use arc joins at acute corners.  Callers should validate output with
  :func:`is_outline_closed`.
- Thread strength values are indicative only.  Actual sewing thread tensile
  strength depends on thread construction, stitch tension, fabric weight, and
  wash cycles.  Values approximate Coats Astra 120 tex thread at 15 stitches/25mm.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SeamSpec:
    """Construction seam specification.

    Attributes
    ----------
    seam_type : str
        ISO 4916:1991 / ASTM D6193 seam class:
        ``'plain'`` (SSa, ISO 1) — most common single-fold seam.
        ``'french'`` (SSf) — enclosed seam for sheer fabrics.
        ``'flat_felled'`` (LSa, ISO 4) — sportswear, denim; two rows of stitching.
        ``'overlock'`` (EFa, ISO 2) — serged edge finish; 3- or 5-thread.
    allowance_mm : float
        Seam allowance width in millimetres.
        Aldrich 6e §1: standard 15 mm for most garments; 6–10 mm for curved seams.
    stitch_pitch_mm : float
        Distance between stitch needle entries in millimetres.
        ASTM D6193 SPI (stitches per inch): 12 SPI ≈ 2.1 mm pitch; 8 SPI ≈ 3.2 mm.
    thread_strength_n : float
        Estimated seam tensile strength in Newtons.
        Indicative: plain seam ~200 N, flat-felled ~350 N, overlock ~180 N.
    """

    seam_type: str = "plain"
    allowance_mm: float = 15.0
    stitch_pitch_mm: float = 2.5
    thread_strength_n: float = 200.0


@dataclass
class SeamAllowanceResult:
    """Output of :func:`lay_seam_allowance`.

    Attributes
    ----------
    original_outline : list[tuple[float, float]]
        The input stitching line (unchanged).
    allowance_outline : list[tuple[float, float]]
        Outward-offset polygon (cut line).
    allowance_mm : float
        Applied allowance width.
    seam_spec : SeamSpec
        The seam specification used.
    honest_caveat : str
        Caveat note.
    """

    original_outline: list[tuple[float, float]]
    allowance_outline: list[tuple[float, float]]
    allowance_mm: float
    seam_spec: SeamSpec
    honest_caveat: str = (
        "Outward offset uses per-vertex miter normals; may self-intersect at "
        "sharp convex corners with large allowances. "
        "Verify with is_outline_closed() before cutting. "
        "Aldrich 6e §1 recommends clipping miter joints at corners < 30°."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _polygon_winding(outline: list[tuple[float, float]]) -> float:
    """Return twice the signed area (positive = CCW, negative = CW)."""
    n = len(outline)
    acc = 0.0
    for i in range(n):
        x0, y0 = outline[i]
        x1, y1 = outline[(i + 1) % n]
        acc += (x0 * y1) - (x1 * y0)
    return acc  # 2 × signed_area


def _vertex_outward_normals(
    outline: list[tuple[float, float]],
    sign: float,
) -> list[tuple[float, float]]:
    """Compute per-vertex miter normals pointing outward.

    Parameters
    ----------
    outline : list[tuple[float, float]]
        Closed polygon vertices.
    sign : float
        +1 for outward (CCW polygon), -1 for CW polygon.

    Returns
    -------
    list[tuple[float, float]]
        Per-vertex normalised miter normal vectors.
    """
    n = len(outline)
    normals: list[tuple[float, float]] = []
    for i in range(n):
        # Previous and next vertices (wrap)
        prev = outline[(i - 1) % n]
        curr = outline[i]
        nxt = outline[(i + 1) % n]

        # Edge vectors
        ex0, ey0 = curr[0] - prev[0], curr[1] - prev[1]
        ex1, ey1 = nxt[0] - curr[0], nxt[1] - curr[1]

        # Outward normals for each edge (rotated 90° to the left = CCW)
        len0 = math.hypot(ex0, ey0)
        len1 = math.hypot(ex1, ey1)
        # Outward normal for a CCW polygon: rotate edge 90° clockwise → (ey/len, -ex/len).
        # For a CW polygon (sign=-1) the sense is inverted.
        if len0 < 1e-12:
            n0 = (0.0, 0.0)
        else:
            n0 = (ey0 / len0 * sign, -ex0 / len0 * sign)
        if len1 < 1e-12:
            n1 = (0.0, 0.0)
        else:
            n1 = (ey1 / len1 * sign, -ex1 / len1 * sign)

        # Miter normal = average of adjacent edge normals, normalised
        mx = n0[0] + n1[0]
        my = n0[1] + n1[1]
        mlen = math.hypot(mx, my)
        if mlen < 1e-12:
            # Degenerate — use edge normal
            normals.append(n0 if len0 >= len1 else n1)
        else:
            normals.append((mx / mlen, my / mlen))
    return normals


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lay_seam_allowance(
    pattern_outline: list[tuple[float, float]],
    seam_spec: SeamSpec,
) -> list[tuple[float, float]]:
    """Offset a closed pattern outline outward by seam allowance.

    **Honest flag**: uses per-vertex miter normal offsetting.  Sharp convex
    corners (< ~30°) can produce self-intersecting polygons.  Production CAD
    tools use arc joins or spline blending at acute corners (Aldrich 6e §1).

    The outline should be a closed polygon; the last vertex need not repeat
    the first.

    Parameters
    ----------
    pattern_outline : list[tuple[float, float]]
        Stitching line (inner boundary) in mm.
    seam_spec : SeamSpec
        Seam type and allowance width.

    Returns
    -------
    list[tuple[float, float]]
        Cut-line polygon offset outward by ``seam_spec.allowance_mm``.
    """
    n = len(pattern_outline)
    if n < 3:
        return list(pattern_outline)

    d = seam_spec.allowance_mm
    winding = _polygon_winding(pattern_outline)
    sign = 1.0 if winding >= 0.0 else -1.0   # CCW polygon → outward = left normal

    normals = _vertex_outward_normals(pattern_outline, sign)
    offset: list[tuple[float, float]] = []
    for (x, y), (nx, ny) in zip(pattern_outline, normals):
        offset.append((x + nx * d, y + ny * d))
    return offset


def lay_seam_allowance_full(
    pattern_outline: list[tuple[float, float]],
    seam_spec: SeamSpec,
) -> SeamAllowanceResult:
    """As :func:`lay_seam_allowance` but returns a full :class:`SeamAllowanceResult`.

    **Honest flag**: same caveat as :func:`lay_seam_allowance`.
    """
    allowance = lay_seam_allowance(pattern_outline, seam_spec)
    return SeamAllowanceResult(
        original_outline=list(pattern_outline),
        allowance_outline=allowance,
        allowance_mm=seam_spec.allowance_mm,
        seam_spec=seam_spec,
    )


def is_outline_closed(
    outline: list[tuple[float, float]],
    tol_mm: float = 0.1,
) -> bool:
    """Return True if the outline is topologically closed (first ≈ last vertex).

    Parameters
    ----------
    outline : list[tuple[float, float]]
        Polygon vertex list.
    tol_mm : float
        Tolerance in mm.
    """
    if len(outline) < 2:
        return len(outline) == 1
    dx = outline[-1][0] - outline[0][0]
    dy = outline[-1][1] - outline[0][1]
    return math.hypot(dx, dy) <= tol_mm


def stitch_line_points(
    segment: tuple[tuple[float, float], tuple[float, float]],
    pitch_mm: float,
) -> list[tuple[float, float]]:
    """Generate stitch needle-entry points along a seam segment.

    Parameters
    ----------
    segment : tuple of two (x, y) points
        Seam segment start and end in mm.
    pitch_mm : float
        Distance between stitches in mm.

    Returns
    -------
    list[tuple[float, float]]
        Stitch positions along the segment including start and end.
    """
    (x0, y0), (x1, y1) = segment
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1e-9 or pitch_mm <= 0.0:
        return [(x0, y0)]
    n_stitches = max(1, int(length / pitch_mm))
    pts = []
    for i in range(n_stitches + 1):
        t = i / n_stitches
        pts.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
    return pts


def seam_allowance_area(
    original_outline: list[tuple[float, float]],
    offset_outline: list[tuple[float, float]],
) -> float:
    """Return the area (mm²) of the seam allowance strip between two outlines.

    Uses the shoelace formula on the combined ring (outer CCW + inner CW).
    """
    def shoelace(pts: list[tuple[float, float]]) -> float:
        n = len(pts)
        acc = 0.0
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            acc += (x0 * y1) - (x1 * y0)
        return abs(acc) / 2.0

    outer_area = shoelace(offset_outline)
    inner_area = shoelace(original_outline)
    return abs(outer_area - inner_area)
