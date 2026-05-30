"""
kerf_mold.cooling_channel_conflict
====================================
Geometric conflict detection for injection-mold cooling-channel layouts.

Four conflict classes are detected:

  CHANNEL_SPACING  — two channels are closer than ``min_spacing_factor × diameter``
                     (Menges 2001 §6.5: typically 2× bore diameter centre-to-centre
                     minimum; a reasonable minimum clearance is 1× diameter gap,
                     i.e. 2× diameter c-t-c).

  CHANNEL_EJECTOR  — a cooling channel axis comes within
                     (channel_radius + ejector_radius) of an ejector-pin axis,
                     indicating a physical intersection.

  WALL_CLEARANCE   — a channel centreline is closer than ``min_spacing_factor × radius``
                     to any cavity-face plane, risking thin-wall breakthrough.

  MOLD_BOUNDS      — any point along a channel segment lies outside the mold-base
                     bounding box.

Geometry
--------
All channels are represented as 3-D line segments (start, end).  Ejector pins are
3-D line segments whose axis runs from (x, y, z_bottom) to (x, y, z_top).

Minimum distance between two skew/parallel line segments is computed with the
exact closed-form formula (adapted from Ericson 2005 "Real-Time Collision
Detection" §5.1.9).  This is a **heuristic approximation** suitable for straight
(gun-drilled) channels.  Curved, conformal (3-D-printed conformal) cooling channels
require triangulated mesh distance which is *out of scope*; a ``curved_channel`` flag
on the ``CoolingChannel3D`` dataclass will trigger a ``SCOPE_LIMIT`` warning.

References
----------
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001 — §6.5 Cooling-channel design rules.
Ericson C. "Real-Time Collision Detection", Morgan Kaufmann 2005 — §5.1.9
  Closest points on two line segments.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

Point3 = Tuple[float, float, float]
"""A 3-D point (x, y, z) in mm."""


@dataclass
class CoolingChannel3D:
    """A straight gun-drilled cooling channel.

    Parameters
    ----------
    start:          Entry-point (mm).
    end:            Exit-point (mm).
    diameter_mm:    Bore diameter (mm).  Typical range 6–16 mm (Menges §6.5).
    label:          Human-readable channel identifier.
    curved:         If True the channel is a conformal (non-straight) path.
                    Conflict detection is *approximate* for curved channels; a
                    SCOPE_LIMIT warning is appended to the report.
    """

    start: Point3
    end: Point3
    diameter_mm: float = 10.0
    label: str = ""
    curved: bool = False

    @property
    def radius_mm(self) -> float:
        return self.diameter_mm / 2.0

    @property
    def length_mm(self) -> float:
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        dz = self.end[2] - self.start[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)


@dataclass
class EjectorPin3D:
    """Ejector pin represented as a vertical (or oblique) axis segment.

    Parameters
    ----------
    start:       Bottom of pin travel (mm) — typically z = 0.
    end:         Top of pin travel (mm) — typically z = mold-base height.
    diameter_mm: Pin diameter (mm).
    label:       Human-readable identifier.
    """

    start: Point3
    end: Point3
    diameter_mm: float = 4.76
    label: str = ""

    @property
    def radius_mm(self) -> float:
        return self.diameter_mm / 2.0


@dataclass
class CavityWall:
    """An infinite half-space defined by a normal vector and a point on the wall.

    The cavity face occupies the plane ``normal · (p − point_on_wall) = 0``.
    Channels must keep their centreline at least ``clearance_mm`` away from
    this plane.
    """

    normal: Point3
    """Unit outward normal pointing *away* from the steel."""
    point_on_wall: Point3
    """Any point on the cavity-face plane (mm)."""
    label: str = ""


@dataclass
class MoldBbox:
    """Axis-aligned bounding box of the mold base block.

    All six faces are checked.  A channel whose *any* sample point falls outside
    exits the steel and is flagged MOLD_BOUNDS.
    """

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


@dataclass
class Conflict:
    """A single detected conflict.

    Attributes
    ----------
    conflict_type:  One of ``CHANNEL_SPACING``, ``CHANNEL_EJECTOR``,
                    ``WALL_CLEARANCE``, ``MOLD_BOUNDS``.
    channel_a:      Label of the first channel involved.
    channel_b:      Label of the second entity (channel, ejector pin, or face).
    location_mm:    Closest-point coordinates on ``channel_a`` (mm).
    gap_mm:         Measured minimum gap between the two bodies (edge-to-edge),
                    in mm.  Negative gap = overlap.
    min_required_mm: Required minimum gap for this rule (mm).
    severity:       Integer 1–5.  Rule:
                      5 = overlap (gap_mm < 0)
                      4 = gap < 0.5 × min_required
                      3 = gap < min_required
                      2 = gap < 1.5 × min_required (warning zone)
                      1 = informational
    description:    Human-readable explanation.
    """

    conflict_type: str
    channel_a: str
    channel_b: str
    location_mm: Point3
    gap_mm: float
    min_required_mm: float
    severity: int
    description: str


@dataclass
class CoolingConflictReport:
    """Full conflict report for a cooling-channel layout.

    Attributes
    ----------
    conflicts:          List of detected conflicts, ordered by severity (5→1).
    n_channels:         Number of channels analysed.
    n_ejector_pins:     Number of ejector pins checked.
    n_cavity_walls:     Number of cavity walls checked.
    scope_warnings:     Non-fatal limitations (e.g. curved-channel approximation).
    """

    conflicts: List[Conflict]
    n_channels: int
    n_ejector_pins: int
    n_cavity_walls: int
    scope_warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

_EPS = 1e-12


def _dot3(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub3(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _len3(v: Point3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _lerp3(p: Point3, q: Point3, t: float) -> Point3:
    """Linear interpolation between p and q at parameter t."""
    return (
        p[0] + t * (q[0] - p[0]),
        p[1] + t * (q[1] - p[1]),
        p[2] + t * (q[2] - p[2]),
    )


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _segment_segment_closest(
    p1: Point3, p2: Point3, p3: Point3, p4: Point3
) -> Tuple[float, Point3, Point3]:
    """
    Compute the minimum distance between line segment [p1,p2] and [p3,p4].

    Returns (distance, closest_point_on_p1p2, closest_point_on_p3p4).

    Algorithm: Ericson 2005 §5.1.9 (segment-segment closest points).
    Handles parallel and degenerate cases explicitly.

    Notes
    -----
    This is an exact closed-form solution for straight segments.
    Curved (conformal) channels require a different approach.
    """
    d1 = _sub3(p2, p1)  # direction of first segment
    d2 = _sub3(p4, p3)  # direction of second segment
    r = _sub3(p1, p3)

    a = _dot3(d1, d1)  # squared length of seg 1
    e = _dot3(d2, d2)  # squared length of seg 2
    f = _dot3(d2, r)

    if a < _EPS and e < _EPS:
        # Both segments degenerate to points
        return _len3(_sub3(p1, p3)), p1, p3

    if a < _EPS:
        # First segment degenerates to a point
        s = 0.0
        t = _clamp(f / e, 0.0, 1.0)
    else:
        c = _dot3(d1, r)
        if e < _EPS:
            # Second segment degenerates to a point
            t = 0.0
            s = _clamp(-c / a, 0.0, 1.0)
        else:
            # General non-degenerate case
            b = _dot3(d1, d2)
            denom = a * e - b * b  # determinant
            if abs(denom) > _EPS:
                # Not parallel — clamp s
                s = _clamp((b * f - c * e) / denom, 0.0, 1.0)
            else:
                # Parallel segments — pick s = 0
                s = 0.0
            t = (b * s + f) / e
            # Clamp t and recompute s if t was clamped
            if t < 0.0:
                t = 0.0
                s = _clamp(-c / a, 0.0, 1.0)
            elif t > 1.0:
                t = 1.0
                s = _clamp((b - c) / a, 0.0, 1.0)

    cp1 = _lerp3(p1, p2, s)
    cp2 = _lerp3(p3, p4, t)
    dist = _len3(_sub3(cp1, cp2))
    return dist, cp1, cp2


def _point_to_plane_signed(pt: Point3, normal: Point3, plane_pt: Point3) -> float:
    """Signed distance from *pt* to an infinite plane (positive = normal side)."""
    diff = _sub3(pt, plane_pt)
    return _dot3(diff, normal)


def _segment_to_plane_min_dist(
    p1: Point3, p2: Point3, normal: Point3, plane_pt: Point3
) -> Tuple[float, Point3]:
    """
    Minimum unsigned distance from segment [p1,p2] to a plane.

    Returns (min_distance, closest_point_on_segment).
    """
    d1 = _point_to_plane_signed(p1, normal, plane_pt)
    d2 = _point_to_plane_signed(p2, normal, plane_pt)
    if d1 * d2 < 0.0:
        # Segment crosses the plane -> distance 0
        t = d1 / (d1 - d2)
        crossing = _lerp3(p1, p2, t)
        return 0.0, crossing
    # Both points on same side — minimum is the closer endpoint
    if abs(d1) <= abs(d2):
        return abs(d1), p1
    else:
        return abs(d2), p2


def _segment_to_bbox_min_clearance(
    p1: Point3, p2: Point3, bbox: MoldBbox
) -> Tuple[float, Point3]:
    """
    Minimum *signed* penetration depth of segment [p1,p2] into ``bbox``.

    Returns (min_clearance, worst_point):
      - clearance > 0  -> segment is inside by ``clearance`` mm at the closest face.
      - clearance <= 0 -> segment exits the bbox; |clearance| is the penetration.
    """
    # Sample a grid of points on the segment
    n_samples = 20
    min_clearance = float("inf")
    worst_pt: Point3 = p1
    for i in range(n_samples + 1):
        t = i / n_samples
        pt = _lerp3(p1, p2, t)
        # Distance to each of the 6 faces (positive = inside)
        margins = [
            pt[0] - bbox.x_min,
            bbox.x_max - pt[0],
            pt[1] - bbox.y_min,
            bbox.y_max - pt[1],
            pt[2] - bbox.z_min,
            bbox.z_max - pt[2],
        ]
        # The clearance for this point is the minimum margin (smallest distance
        # to any face).  If the point is outside, at least one margin is negative.
        pt_clearance = min(margins)
        if pt_clearance < min_clearance:
            min_clearance = pt_clearance
            worst_pt = pt
    return min_clearance, worst_pt


# ---------------------------------------------------------------------------
# Severity helper
# ---------------------------------------------------------------------------

def _severity(gap_mm: float, min_required_mm: float) -> int:
    """Map (gap, required) onto 1–5 severity scale.

    5 = overlap (gap <= 0)
    4 = gap < 0.5 × required
    3 = gap < required
    2 = gap < 1.5 × required
    1 = informational (>= 1.5 × required)
    """
    if gap_mm <= 0.0:
        return 5
    ratio = gap_mm / max(min_required_mm, _EPS)
    if ratio < 0.5:
        return 4
    if ratio < 1.0:
        return 3
    if ratio < 1.5:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def verify_cooling_channels(
    channels: Sequence[CoolingChannel3D],
    ejector_pins: Sequence[EjectorPin3D],
    cavity_bbox: MoldBbox,
    cavity_walls: Sequence[CavityWall],
    *,
    min_spacing_factor: float = 2.0,
) -> CoolingConflictReport:
    """
    Verify a cooling-channel layout for geometric conflicts.

    Implements the four conflict classes described in Menges 2001 §6.5:

    1. **CHANNEL_SPACING** — channel-to-channel minimum distance < required.
       Required = ``min_spacing_factor × max(diameter_a, diameter_b) / 2``
       (edge-to-edge gap).  Default factor = 2.0 -> gap must be >= 1 × bore
       diameter, which corresponds to the "2× diameter c-t-c" rule in §6.5.

    2. **CHANNEL_EJECTOR** — channel centreline comes within
       (channel_radius + pin_radius) of an ejector-pin axis segment,
       indicating a physical overlap.

    3. **WALL_CLEARANCE** — channel centreline is closer than
       ``min_spacing_factor × channel_radius`` to any cavity-face plane,
       risking thin-wall breakthrough.

    4. **MOLD_BOUNDS** — any sample point on a channel exits the mold-base
       bounding box.

    Parameters
    ----------
    channels:
        List of :class:`CoolingChannel3D` objects.
    ejector_pins:
        List of :class:`EjectorPin3D` objects.
    cavity_bbox:
        :class:`MoldBbox` — axis-aligned box of the entire mold block.
    cavity_walls:
        Sequence of :class:`CavityWall` objects (cavity-face planes the channels
        must not approach too closely).
    min_spacing_factor:
        Multiplier on channel radius for minimum edge-to-edge clearance.
        Default 2.0 (Menges 2001 §6.5 rule: 2× diameter centre-to-centre <->
        1× diameter edge-to-edge gap, which is factor 2.0 on radius).

    Returns
    -------
    :class:`CoolingConflictReport`

    Notes
    -----
    **Honest scope flags**:

    * This is a **heuristic minimum-distance analysis** for straight
      (gun-drilled) channels.  CFD-based hot-spot analysis is out of scope.
    * Curved (3-D-printed conformal) channels require triangulated mesh distance
      computation; a ``SCOPE_LIMIT`` warning is appended when ``channel.curved``
      is True.

    References
    ----------
    Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
      Hanser 2001 — §6.5 Cooling-channel design rules.
    Ericson C. "Real-Time Collision Detection", Morgan Kaufmann 2005 — §5.1.9.
    """
    conflicts: List[Conflict] = []
    scope_warnings: List[str] = []

    channels = list(channels)
    ejector_pins = list(ejector_pins)
    cavity_walls = list(cavity_walls)

    for ch in channels:
        if ch.curved:
            scope_warnings.append(
                f"Channel '{ch.label}' is marked curved=True.  "
                "Conflict detection uses end-point-segment approximation only; "
                "exact conformal-channel distance requires triangulated mesh — "
                "out of scope (Menges 2001 §6.5 note on conformal cooling)."
            )

    # ------------------------------------------------------------------
    # 1. CHANNEL_SPACING: pairwise channel-channel minimum distance
    #    Menges 2001 §6.5: channels must not be closer than 2× diameter
    #    centre-to-centre, i.e. edge-to-edge gap >= 1× bore diameter.
    #    Using min_spacing_factor (default 2.0) × radius = 1× diameter gap.
    # ------------------------------------------------------------------
    for i in range(len(channels)):
        for j in range(i + 1, len(channels)):
            ca = channels[i]
            cb = channels[j]
            # Required edge-to-edge gap
            required_gap_mm = min_spacing_factor * max(ca.radius_mm, cb.radius_mm)
            # Centre-to-centre minimum distance
            ctc_dist, cp_a, cp_b = _segment_segment_closest(
                ca.start, ca.end, cb.start, cb.end
            )
            # Edge-to-edge gap = c-t-c dist - ra - rb
            edge_gap = ctc_dist - ca.radius_mm - cb.radius_mm
            if edge_gap < required_gap_mm:
                sev = _severity(edge_gap, required_gap_mm)
                conflicts.append(
                    Conflict(
                        conflict_type="CHANNEL_SPACING",
                        channel_a=ca.label or f"ch{i}",
                        channel_b=cb.label or f"ch{j}",
                        location_mm=cp_a,
                        gap_mm=round(edge_gap, 4),
                        min_required_mm=round(required_gap_mm, 4),
                        severity=sev,
                        description=(
                            f"Channels '{ca.label}' and '{cb.label}' are "
                            f"{edge_gap:.2f} mm apart (edge-to-edge); "
                            f"minimum required {required_gap_mm:.2f} mm "
                            f"(Menges 2001 §6.5: 2x diameter c-t-c rule, "
                            f"factor={min_spacing_factor})."
                        ),
                    )
                )

    # ------------------------------------------------------------------
    # 2. CHANNEL_EJECTOR: channel axis vs. ejector-pin axis
    #    Conflict when centre-to-centre dist < (channel_r + pin_r).
    # ------------------------------------------------------------------
    for i, ch in enumerate(channels):
        for j, ep in enumerate(ejector_pins):
            # For channel-ejector, apply min_spacing_factor design margin
            design_gap = min_spacing_factor * max(ch.radius_mm, ep.radius_mm)
            ctc_dist, cp_ch, cp_ep = _segment_segment_closest(
                ch.start, ch.end, ep.start, ep.end
            )
            edge_gap = ctc_dist - ch.radius_mm - ep.radius_mm
            if edge_gap < design_gap:
                sev = _severity(edge_gap, design_gap)
                conflicts.append(
                    Conflict(
                        conflict_type="CHANNEL_EJECTOR",
                        channel_a=ch.label or f"ch{i}",
                        channel_b=ep.label or f"pin{j}",
                        location_mm=cp_ch,
                        gap_mm=round(edge_gap, 4),
                        min_required_mm=round(design_gap, 4),
                        severity=sev,
                        description=(
                            f"Channel '{ch.label}' and ejector pin '{ep.label}' "
                            f"edge-to-edge gap = {edge_gap:.2f} mm; "
                            f"minimum required {design_gap:.2f} mm "
                            f"(Menges 2001 §6.5 / Yu-Fan 2003 §10.3 interference rule)."
                        ),
                    )
                )

    # ------------------------------------------------------------------
    # 3. WALL_CLEARANCE: channel centreline to each cavity-face plane
    #    Minimum clearance = min_spacing_factor × channel_radius so that
    #    the remaining steel wall is >= channel_radius thick (Menges §6.5).
    # ------------------------------------------------------------------
    for i, ch in enumerate(channels):
        for wk, wall in enumerate(cavity_walls):
            required_clearance = min_spacing_factor * ch.radius_mm
            dist, cp = _segment_to_plane_min_dist(
                ch.start, ch.end, wall.normal, wall.point_on_wall
            )
            # gap = dist - radius (edge of bore to wall)
            edge_gap = dist - ch.radius_mm
            if edge_gap < required_clearance:
                sev = _severity(edge_gap, required_clearance)
                wlabel = wall.label or f"wall{wk}"
                conflicts.append(
                    Conflict(
                        conflict_type="WALL_CLEARANCE",
                        channel_a=ch.label or f"ch{i}",
                        channel_b=wlabel,
                        location_mm=cp,
                        gap_mm=round(edge_gap, 4),
                        min_required_mm=round(required_clearance, 4),
                        severity=sev,
                        description=(
                            f"Channel '{ch.label}' wall clearance to '{wlabel}' "
                            f"= {edge_gap:.2f} mm; minimum required "
                            f"{required_clearance:.2f} mm "
                            f"(Menges 2001 §6.5: >=2x radius steel to cavity face)."
                        ),
                    )
                )

    # ------------------------------------------------------------------
    # 4. MOLD_BOUNDS: channel exits the mold-base bounding box
    # ------------------------------------------------------------------
    for i, ch in enumerate(channels):
        clearance, worst_pt = _segment_to_bbox_min_clearance(
            ch.start, ch.end, cavity_bbox
        )
        if clearance < ch.radius_mm:
            # Edge of channel exits or is very close to exiting
            edge_clearance = clearance - ch.radius_mm
            sev = _severity(edge_clearance, ch.radius_mm)
            conflicts.append(
                Conflict(
                    conflict_type="MOLD_BOUNDS",
                    channel_a=ch.label or f"ch{i}",
                    channel_b="mold_base",
                    location_mm=worst_pt,
                    gap_mm=round(edge_clearance, 4),
                    min_required_mm=round(ch.radius_mm, 4),
                    severity=sev,
                    description=(
                        f"Channel '{ch.label}' exits mold-base bounds at "
                        f"({worst_pt[0]:.1f}, {worst_pt[1]:.1f}, {worst_pt[2]:.1f}) mm; "
                        f"bore edge is {abs(edge_clearance):.2f} mm outside the bbox "
                        f"(Menges 2001 §6.5: channels must terminate within the mold block)."
                    ),
                )
            )

    # Sort by severity descending, then by channel label
    conflicts.sort(key=lambda c: (-c.severity, c.channel_a, c.channel_b))

    return CoolingConflictReport(
        conflicts=conflicts,
        n_channels=len(channels),
        n_ejector_pins=len(ejector_pins),
        n_cavity_walls=len(cavity_walls),
        scope_warnings=scope_warnings,
    )
